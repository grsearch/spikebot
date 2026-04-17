"""
插针检测引擎 v5 - 最终版

关键数学推导：
  对于下插针K线（close在open和low之间）:
    spike_drop = open - low   （整根针的长度）
    body       = open - close （K线实体，因为close<open）
    wick_below_body = close - low  （close到low的距离）
    
    定义 recovery = wick_below_body / spike_drop = (close-low)/(open-low)
    定义 body_ratio = body / spike_drop = (open-close)/(open-low)
    
    则: recovery + body_ratio = (close-low + open-close)/(open-low) = 1
    
    这意味着 recovery 和 body_ratio 是一个量的两种表达:
    - recovery = 0.30 → body_ratio = 0.70 (实体占针70%)
    - recovery = 0.50 → body_ratio = 0.50 (实体等于针)
    - recovery = 0.70 → body_ratio = 0.30 (实体占针30%)
    
  因此 SPIKE_RATIO 参数被移除，只保留 SPIKE_VS_ATR 和 recovery 范围。

触发条件：
  ① spike_drop / ATR >= SPIKE_VS_ATR    针足够大
  ② MIN_RECOVERY <= recovery <= MAX_RECOVERY   已回归但未过度
  ③ R:R >= MIN_RR                       风险收益比足够

价格计算：
  entry = candle.close              下根K线市价入场
  tp    = entry + (open - entry) × TP_RATIO    目标是回归到开盘价
  sl    = low - max(针长 × SL_RATIO, ATR × SL_ATR_MULT)  针尖下方自适应
"""
import logging
from dataclasses import dataclass
from typing import Optional
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class SpikeSignal:
    direction: str
    entry_price: float
    take_profit: float
    stop_loss: float
    spike_tip: float
    spike_root: float
    spike_length: float
    atr: float
    recovery_pct: float
    rr_ratio: float
    score: float
    candle: Candle = None


class SpikeDetector:
    def __init__(self, config):
        self.cfg = config
        self.candles: deque[Candle] = deque(maxlen=500)
        self._atr_cache: float = 0.0

    def update(self, klines: list):
        existing = {c.open_time for c in self.candles}
        for k in klines:
            if k["open_time"] not in existing:
                self.candles.append(Candle(
                    open_time=k["open_time"],
                    open=k["open"], high=k["high"],
                    low=k["low"],   close=k["close"],
                    volume=k["volume"],
                ))
        self._atr_cache = self._calc_atr()

    def _calc_atr(self) -> float:
        cs = list(self.candles)
        if len(cs) < 5:
            return 0.0
        n = min(self.cfg.ATR_PERIOD, len(cs) - 1)
        return float(np.mean([c.range for c in cs[-n:]])) or 0.0

    def _calc_ma(self, period: int) -> float:
        cs = list(self.candles)
        if len(cs) < period:
            return 0.0
        return float(np.mean([c.close for c in cs[-period:]]))

    def detect(self, candle: Candle) -> Optional[SpikeSignal]:
        atr = self._atr_cache
        if atr == 0:
            return None

        # ── 下插针 → BUY ──────────────────────────────────────
        spike_drop = candle.open - candle.low
        if spike_drop > atr * self.cfg.SPIKE_VS_ATR:
            recovery = (candle.close - candle.low) / spike_drop

            min_rec = getattr(self.cfg, 'MIN_RECOVERY', 0.30)
            max_rec = getattr(self.cfg, 'MAX_RECOVERY', 0.50)

            if min_rec <= recovery <= max_rec:
                spike_tip  = candle.low
                spike_root = candle.open
                entry      = candle.close

                # TP: entry 到 spike_root 距离的 TP_RATIO 倍
                # TP_RATIO=1.0 → TP在spike_root
                # TP_RATIO=1.5 → TP超过spike_root 50%
                if spike_root > entry:
                    tp = entry + (spike_root - entry) * self.cfg.TP_RATIO
                else:
                    tp = entry + atr * 0.3

                # SL: 针尖下方，两种算法取大
                sl_wick = spike_tip - spike_drop * self.cfg.SL_RATIO
                sl_atr  = spike_tip - atr * getattr(self.cfg, 'SL_ATR_MULT', 0.5)
                sl = min(sl_wick, sl_atr)

                if tp <= entry or sl >= spike_tip:
                    return None

                tp_dist = tp - entry
                sl_dist = entry - sl
                if sl_dist <= 0:
                    return None
                rr = tp_dist / sl_dist

                if rr < getattr(self.cfg, 'MIN_RR', 1.0):
                    return None

                score = self._score(spike_drop, atr, recovery, rr, candle.volume)

                if self.cfg.TREND_FILTER:
                    ma = self._calc_ma(self.cfg.MA_PERIOD)
                    if ma > candle.close * 1.005:
                        score *= 0.7

                return SpikeSignal(
                    direction="BUY",
                    entry_price=entry,
                    take_profit=tp,
                    stop_loss=sl,
                    spike_tip=spike_tip,
                    spike_root=spike_root,
                    spike_length=spike_drop,
                    atr=atr,
                    recovery_pct=round(recovery, 3),
                    rr_ratio=round(rr, 2),
                    score=score,
                    candle=candle,
                )

        # ── 上插针 → SELL ──────────────────────────────────────
        spike_rise = candle.high - candle.open
        if spike_rise > atr * self.cfg.SPIKE_VS_ATR:
            recovery = (candle.high - candle.close) / spike_rise

            min_rec = getattr(self.cfg, 'MIN_RECOVERY', 0.30)
            max_rec = getattr(self.cfg, 'MAX_RECOVERY', 0.50)

            if min_rec <= recovery <= max_rec:
                spike_tip  = candle.high
                spike_root = candle.open
                entry      = candle.close

                if spike_root < entry:
                    tp = entry - (entry - spike_root) * self.cfg.TP_RATIO
                else:
                    tp = entry - atr * 0.3

                sl_wick = spike_tip + spike_rise * self.cfg.SL_RATIO
                sl_atr  = spike_tip + atr * getattr(self.cfg, 'SL_ATR_MULT', 0.5)
                sl = max(sl_wick, sl_atr)

                if tp >= entry or sl <= spike_tip:
                    return None

                tp_dist = entry - tp
                sl_dist = sl - entry
                if sl_dist <= 0:
                    return None
                rr = tp_dist / sl_dist

                if rr < getattr(self.cfg, 'MIN_RR', 1.0):
                    return None

                score = self._score(spike_rise, atr, recovery, rr, candle.volume)

                return SpikeSignal(
                    direction="SELL",
                    entry_price=entry,
                    take_profit=tp,
                    stop_loss=sl,
                    spike_tip=spike_tip,
                    spike_root=spike_root,
                    spike_length=spike_rise,
                    atr=atr,
                    recovery_pct=round(recovery, 3),
                    rr_ratio=round(rr, 2),
                    score=score,
                    candle=candle,
                )

        return None

    def _score(self, spike_len, atr, recovery, rr, volume):
        s_spike = min(spike_len / atr / (self.cfg.SPIKE_VS_ATR * 2), 1.0) * 40
        min_rec = getattr(self.cfg, 'MIN_RECOVERY', 0.30)
        max_rec = getattr(self.cfg, 'MAX_RECOVERY', 0.50)
        ideal   = (min_rec + max_rec) / 2
        span    = (max_rec - min_rec) / 2 or 0.1
        s_rec   = max(0.0, 1.0 - abs(recovery - ideal) / span) * 25
        s_rr    = min(rr / 3.0, 1.0) * 20
        recent  = [c.volume for c in list(self.candles)[-20:]]
        avg_v   = float(np.mean(recent)) if recent else 1.0
        s_vol   = min((volume / avg_v) / 5.0, 1.0) * 15
        return round(s_spike + s_rec + s_rr + s_vol, 1)
