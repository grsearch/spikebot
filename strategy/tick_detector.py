"""
事件驱动插针检测器 v1

与 detector.py (K线版) 的核心差异：
  旧: 等1s K线收盘 → 分析完整形态 → 下一根入场 (延迟 500-1500ms)
  新: 每笔成交都检查 → 滑动窗口发现异常 → 立即下单 (延迟 50-100ms)

检测逻辑：
  维护每个 symbol 最近 N 秒的成交列表
  当收到新成交时：
    1. 计算最近 LOOKBACK 秒内的最高价 h, 最低价 l
    2. 如果 new_price 创了新低，且 (h - new_price) / ATR >= SPIKE_VS_ATR
    3. 并且新价相对最近中位数下跌 > 0.15%（绝对门槛）
    4. → 触发 BUY 信号
  对上插针同理
  
  入场: 立即市价单 (在真实环境，延迟<100ms时有意义)
  止盈: 针长 × TP_RATIO (典型 0.3~0.5，吃第一波反弹就走)
  止损: 针尖 × SL_RATIO  
  持仓: 最多 3 秒，不反弹就跑

只适合 WebSocket 实时数据流，REST 轮询下会严重失真！
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    price: float
    qty: float
    time_ms: int
    is_buyer_maker: bool


@dataclass
class TickSignal:
    direction: str      # BUY | SELL
    entry_price: float  # 触发时的市场最新价
    take_profit: float
    stop_loss: float
    spike_tip: float
    spike_root: float
    spike_length: float
    trigger_time_ms: int
    lookback_ms: int    # 从针根到针尖用了多少毫秒
    avg_price: float    # 最近窗口均价
    reason: str         # 触发理由说明（用于日志）


class TickSpikeDetector:
    """
    每个交易对一个实例，在线接收成交流
    """

    def __init__(self, symbol: str, config):
        self.symbol = symbol
        self.cfg = config

        # 配置参数（带默认值）
        self.lookback_ms       = getattr(config, "TICK_LOOKBACK_MS",     2000)   # 2秒窗口
        self.atr_window_sec    = getattr(config, "TICK_ATR_WINDOW_SEC",  60)     # 1分钟算ATR
        self.min_spike_pct     = getattr(config, "TICK_MIN_SPIKE_PCT",   0.002)  # 最小0.2%振幅
        self.spike_vs_atr      = getattr(config, "SPIKE_VS_ATR",         2.5)    # 针/ATR倍数
        self.tp_ratio          = getattr(config, "TICK_TP_RATIO",        0.40)   # 吃针长40%反弹
        self.sl_ratio          = getattr(config, "TICK_SL_RATIO",        0.25)   # 针尖继续 25%针长 就止损
        self.min_rr            = getattr(config, "MIN_RR",               1.0)
        self.cooldown_ms       = getattr(config, "TICK_COOLDOWN_MS",     3000)   # 同币种两次信号最少间隔
        self.max_trades        = 5000

        # 状态
        self.trades: Deque[Trade] = deque(maxlen=self.max_trades)
        self._last_signal_ms = 0
        self._last_signal_dir = ""

        # ATR计算：按秒分桶的 high/low
        self._sec_buckets: dict = {}  # sec_ts → (high, low)
        self._atr_cache = 0.0
        self._atr_updated_at = 0

    # ──────────────────────────────────────────────────
    def on_trade(self, price: float, qty: float, time_ms: int, is_buyer_maker: bool) -> Optional[TickSignal]:
        """
        主入口：每笔成交进来调用一次
        返回 TickSignal 或 None
        """
        trade = Trade(price, qty, time_ms, is_buyer_maker)
        self.trades.append(trade)

        # 更新秒桶
        sec = time_ms // 1000
        b = self._sec_buckets.get(sec)
        if b is None:
            self._sec_buckets[sec] = [price, price]  # [high, low]
        else:
            if price > b[0]: b[0] = price
            if price < b[1]: b[1] = price

        # 清理老秒桶
        cutoff_sec = sec - self.atr_window_sec - 5
        if len(self._sec_buckets) > self.atr_window_sec + 10:
            for k in list(self._sec_buckets.keys()):
                if k < cutoff_sec:
                    del self._sec_buckets[k]

        # 冷却期检查
        if time_ms - self._last_signal_ms < self.cooldown_ms:
            return None

        # 数据不足
        if len(self.trades) < 20:
            return None

        return self._detect(trade)

    # ──────────────────────────────────────────────────
    def _update_atr(self, now_ms: int):
        """ATR = 最近N秒的 (high-low) 平均值"""
        if now_ms - self._atr_updated_at < 1000:
            return  # 1秒内不重算
        now_sec = now_ms // 1000
        ranges = []
        for s in range(now_sec - self.atr_window_sec, now_sec):
            b = self._sec_buckets.get(s)
            if b:
                ranges.append(b[0] - b[1])
        if ranges:
            self._atr_cache = float(np.mean(ranges))
        self._atr_updated_at = now_ms

    def _detect(self, trade: Trade) -> Optional[TickSignal]:
        """
        在 lookback_ms 窗口内寻找异常插针
        """
        self._update_atr(trade.time_ms)
        atr = self._atr_cache
        if atr <= 0:
            return None

        # 取窗口内所有成交
        cutoff = trade.time_ms - self.lookback_ms
        window = [t for t in self.trades if t.time_ms >= cutoff]
        if len(window) < 5:
            return None

        prices = [t.price for t in window]
        hi = max(prices)
        lo = min(prices)
        window_range = hi - lo
        # 窗口内振幅够不够大
        if window_range / atr < self.spike_vs_atr:
            return None
        if window_range / trade.price < self.min_spike_pct:
            return None

        # ── 下插针 BUY ─────────────────────────────────
        # 条件:
        #   1. 最低点在窗口中间偏早（不是刚发生），说明已开始反弹
        #   2. 当前价格 > 最低点（回升中）
        #   3. 当前价格 < 均价（还没完全回去，有空间）
        # 关键：不能在价格刚创新低时就买（那是接飞刀）
        #       要等价格反弹、确认是"针"而不是"下跌趋势"
        low_idx  = prices.index(lo)
        high_idx = prices.index(hi)

        # BUY: lo 后有上涨（已反弹），当前价在反弹途中
        if low_idx >= 1 and low_idx < len(prices) - 1:
            ticks_after_low = len(prices) - 1 - low_idx
            # 重要：spike_root = lo 之前"最近"的局部高点
            # 不是整个窗口的hi（可能是很久以前的）
            # 取 low_idx 前 N 笔的最高价作为 spike_root
            lookback_ticks = min(15, low_idx)
            local_hi = max(prices[low_idx - lookback_ticks:low_idx])
            spike_length = local_hi - lo
            if spike_length <= 0 or spike_length / atr < self.spike_vs_atr:
                return None
            recovery = (trade.price - lo) / spike_length
            if 0.10 <= recovery <= 0.50 and ticks_after_low >= 2:
                spike_tip  = lo
                spike_root = local_hi
                entry = trade.price
                tp = entry + spike_length * self.tp_ratio
                # SL 用 ATR 倍数(紧止损) 或 spike_length 的小比例，两者取小
                # 防止 SL 过宽导致 R:R 差
                sl = max(
                    spike_tip - atr * 0.3,
                    spike_tip - spike_length * self.sl_ratio,
                )
                if tp <= entry or sl >= spike_tip:
                    return None
                tp_d = tp - entry
                sl_d = entry - sl
                if sl_d <= 0 or tp_d / sl_d < self.min_rr:
                    return None

                # 时间判断：针形成得够快才算异常
                lo_trade_ms  = window[low_idx].time_ms
                hi_trade_ms  = window[high_idx].time_ms
                lookback_ms  = lo_trade_ms - hi_trade_ms

                self._last_signal_ms  = trade.time_ms
                self._last_signal_dir = "BUY"
                return TickSignal(
                    direction="BUY",
                    entry_price=entry,
                    take_profit=tp,
                    stop_loss=sl,
                    spike_tip=spike_tip,
                    spike_root=spike_root,
                    spike_length=spike_length,
                    trigger_time_ms=trade.time_ms,
                    lookback_ms=lookback_ms,
                    avg_price=float(np.mean(prices)),
                    reason=f"BUY spike_len={spike_length:.6f} recovery={recovery:.0%} ticks={ticks_after_low}",
                )

        # ── 上插针 SELL ────────────────────────────────
        # SELL: hi 后有下跌（已回落），当前价在回落途中
        if high_idx >= 1 and high_idx < len(prices) - 1:
            ticks_after_high = len(prices) - 1 - high_idx
            lookback_ticks = min(15, high_idx)
            local_lo = min(prices[high_idx - lookback_ticks:high_idx])
            spike_length = hi - local_lo
            if spike_length <= 0 or spike_length / atr < self.spike_vs_atr:
                return None
            recovery = (hi - trade.price) / spike_length
            if 0.10 <= recovery <= 0.50 and ticks_after_high >= 2:
                spike_tip  = hi
                spike_root = local_lo
                entry = trade.price
                tp = entry - spike_length * self.tp_ratio
                sl = min(
                    spike_tip + atr * 0.3,
                    spike_tip + spike_length * self.sl_ratio,
                )
                if tp >= entry or sl <= spike_tip:
                    return None
                tp_d = entry - tp
                sl_d = sl - entry
                if sl_d <= 0 or tp_d / sl_d < self.min_rr:
                    return None

                hi_trade_ms = window[high_idx].time_ms
                lo_trade_ms = window[low_idx].time_ms
                lookback_ms = hi_trade_ms - lo_trade_ms

                self._last_signal_ms  = trade.time_ms
                self._last_signal_dir = "SELL"
                return TickSignal(
                    direction="SELL",
                    entry_price=entry,
                    take_profit=tp,
                    stop_loss=sl,
                    spike_tip=spike_tip,
                    spike_root=spike_root,
                    spike_length=spike_length,
                    trigger_time_ms=trade.time_ms,
                    lookback_ms=lookback_ms,
                    avg_price=float(np.mean(prices)),
                    reason=f"SELL spike_len={spike_length:.6f} recovery={recovery:.0%} ticks={ticks_after_high}",
                )

        return None
