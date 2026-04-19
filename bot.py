"""
主交易循环 - 多币种版本
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional

import config as cfg_module
from core.exchange import BinanceREST
from core.scanner import SymbolScanner
from core.ws_client import BinanceFuturesWS
from strategy.detector import SpikeDetector, Candle
from strategy.tick_detector import TickSpikeDetector, TickSignal
from strategy.position_manager import PositionManager
from strategy.risk_manager import RiskManager

logger = logging.getLogger(__name__)

STATE = {
    "running":          False,
    "trading_paused":   False,
    "dry_run":          False,
    "scan_mode":        "single",
    "symbols_active":   [],
    "prices":           {},
    "last_tick":        0,
    "signals_found":    0,
    "signals_blocked":  0,
    "detectors":        {},
    "positions":        None,
    "risk":             None,
    "errors":           [],
    "diag":             {},
    # 网格搜索
    "grid_running":     False,
    "grid_progress":    0,
    "grid_total":       0,
    "grid_results":     [],
    "grid_best":        None,
    "grid_sym_results": {},
    "grid_log":         [],
    # 参数快照
    "live_config":      {},
}

BALANCE_UPDATE_INTERVAL = 30


def _snapshot_config() -> dict:
    keys = [
        "SCAN_MODE", "SYMBOL", "SYMBOL_LIST",
        "SPIKE_RATIO", "SPIKE_VS_ATR", "ATR_PERIOD", "MIN_SPIKE_PIPS",
        "MIN_RECOVERY", "MAX_RECOVERY",
        "TP_RATIO", "SL_RATIO", "SL_ATR_MULT", "MIN_RR",
        "MAX_HOLD_SECONDS", "ORDER_USDT", "MAX_OPEN_ORDERS",
        "MA_PERIOD", "TREND_FILTER", "POLL_INTERVAL_MS",
        "DAILY_LOSS_LIMIT_USDT", "MAX_DRAWDOWN_PCT",
        "MAX_CONSECUTIVE_LOSSES", "MAX_DAILY_TRADES",
        "AUTO_MIN_GAIN_PCT", "AUTO_MIN_VOLUME_USDT",
        "AUTO_MAX_SYMBOLS", "AUTO_REFRESH_SEC",
        "LEVERAGE", "MARGIN_TYPE",
        "USE_TRAILING_TP", "TRAIL_ACTIVATE_PCT", "TRAIL_RETRACE_PCT",
        "BE_ACTIVATE_PCT", "MARKET_FILTER", "FEE_RATE",
        "RUN_MODE", "TICK_LOOKBACK_MS", "TICK_MIN_SPIKE_PCT",
        "TICK_TP_RATIO", "TICK_SL_RATIO", "TICK_COOLDOWN_MS", "TICK_MAX_HOLD_MS",
    ]
    return {k: getattr(cfg_module, k, None) for k in keys}


class SymbolWorker:
    def __init__(self, symbol: str, exchange: BinanceREST,
                 pm: PositionManager, rm: RiskManager):
        self.symbol   = symbol
        self.ex       = exchange
        self.pm       = pm
        self.rm       = rm
        self.detector = SpikeDetector(cfg_module)
        self._last_candle_time = 0
        STATE["detectors"][symbol] = self.detector

    async def tick(self):
        klines = await self.ex.get_klines(self.symbol, "1m", cfg_module.KLINE_LIMIT)
        if not klines:
            return

        self.detector.update(klines)
        closed = [k for k in klines if k.get("is_closed", True)]
        if not closed:
            return

        latest = closed[-1]
        price  = latest["close"]
        STATE["prices"][self.symbol] = price

        if latest["open_time"] == self._last_candle_time:
            await self._monitor(price)
            return

        self._last_candle_time = latest["open_time"]
        candle = Candle(
            open_time=latest["open_time"],
            open=latest["open"],  high=latest["high"],
            low=latest["low"],    close=latest["close"],
            volume=latest["volume"],
        )

        # 诊断数据
        atr   = self.detector._atr_cache
        lower = candle.lower_wick
        upper = candle.upper_wick
        body  = max(candle.body, candle.range * 0.01)
        STATE["diag"] = {
            "symbol":          self.symbol,
            "last_open":       candle.open,
            "last_high":       candle.high,
            "last_low":        candle.low,
            "last_close":      candle.close,
            "lower_wick":      lower,
            "upper_wick":      upper,
            "body":            body,
            "atr":             atr,
            "ratio_body":      max(lower, upper) / body if body > 0 else 0,
            "ratio_atr":       max(lower, upper) / atr  if atr  > 0 else 0,
            "recovery":        (candle.close - candle.low) / lower if lower > 0 else 0,
            "cfg_spike_ratio": cfg_module.SPIKE_RATIO,
            "cfg_spike_atr":   cfg_module.SPIKE_VS_ATR,
            "cfg_min_rec":     getattr(cfg_module, 'MIN_RECOVERY', 0.20),
            "cfg_max_rec":     getattr(cfg_module, 'MAX_RECOVERY', 0.70),
        }

        signal = self.detector.detect(candle)
        if signal:
            STATE["signals_found"] += 1
            logger.info(
                f"[{self.symbol}] SPIKE {signal.direction} "
                f"score={signal.score} R:R={signal.rr_ratio} "
                f"tip={signal.spike_tip:.6f} entry={signal.entry_price:.6f} "
                f"tp={signal.take_profit:.6f} sl={signal.stop_loss:.6f}"
            )
            if STATE.get("trading_paused", False):
                STATE["signals_blocked"] += 1
                logger.info(f"[{self.symbol}] 交易已暂停，信号被忽略")
            else:
                can_trade, reason = self.rm.can_trade()
                if STATE["dry_run"]:
                    if can_trade:
                        await self.pm.try_open(signal, self.symbol)
                    else:
                        STATE["signals_blocked"] += 1
                elif can_trade:
                    await self.pm.try_open(signal, self.symbol)
                else:
                    STATE["signals_blocked"] += 1
                    logger.warning(f"[{self.symbol}] 风控拦截: {reason}")

        await self._monitor(price)

    async def _monitor(self, price: float):
        open_before = {p.id for p in self.pm.open_positions}
        await self.pm.monitor_positions(price, self.symbol)
        open_after  = {p.id for p in self.pm.open_positions}
        for pos in self.pm._positions:
            if pos.id in (open_before - open_after) and pos.status == "CLOSED":
                self.rm.record_trade(pos.pnl_usdt)


class TradingBot:
    def __init__(self):
        self.ex      = BinanceREST(
            cfg_module.API_KEY, cfg_module.API_SECRET, cfg_module.BASE_URL,
            leverage=getattr(cfg_module, "LEVERAGE", 5),
        )
        self.pm      = PositionManager(self.ex, cfg_module)
        self.rm      = RiskManager(cfg_module)
        self.scanner = SymbolScanner(self.ex, cfg_module)
        self._workers: Dict[str, SymbolWorker] = {}
        self._running    = False
        self._tick_count = 0
        # ── Tick 模式相关 ──
        self._run_mode = getattr(cfg_module, "RUN_MODE", "kline").lower()
        self._ws: Optional[BinanceFuturesWS] = None
        self._tick_detectors: Dict[str, TickSpikeDetector] = {}
        self._last_prices_ms: Dict[str, int] = {}
        STATE["run_mode"] = self._run_mode

        STATE["positions"]   = self.pm
        STATE["risk"]        = self.rm
        STATE["scan_mode"]   = getattr(cfg_module, "SCAN_MODE", "single")
        STATE["live_config"] = _snapshot_config()

    async def start(self):
        logger.info("=== Spike Bot Starting ===")
        await self.pm.init_filters()

        try:
            equity = await self.ex.get_total_equity(cfg_module.QUOTE_ASSET)
            self.rm.update_balance(equity)
            logger.info(f"账户总权益: {equity:.2f} {cfg_module.QUOTE_ASSET}")
        except Exception as e:
            logger.warning(f"获取余额失败: {e}")

        lev = getattr(cfg_module, "LEVERAGE", 5)
        mt  = getattr(cfg_module, "MARGIN_TYPE", "ISOLATED")
        logger.info(f"实盘交易 | 合约 | 杠杆{lev}x | {mt}")
        logger.info(f"运行模式: {self._run_mode.upper()}")
        self._running    = True
        STATE["running"] = True

        if self._run_mode == "tick":
            await self._run_tick_mode()
        else:
            await self._run_kline_mode()

    async def _run_kline_mode(self):
        """原有的K线+REST轮询模式"""
        while self._running:
            t0 = time.monotonic()
            try:
                await self._tick()
            except Exception as e:
                err = f"{datetime.now().strftime('%H:%M:%S')} [{type(e).__name__}] {e}"
                logger.error(f"Tick error: {e}", exc_info=True)
                STATE["errors"].append(err)
                STATE["errors"] = STATE["errors"][-60:]

            elapsed  = (time.monotonic() - t0) * 1000
            sleep_ms = max(0, cfg_module.POLL_INTERVAL_MS - elapsed)
            await asyncio.sleep(sleep_ms / 1000)

    async def _run_tick_mode(self):
        """
        Tick级实时模式：
          - 用 WebSocket 订阅 aggTrade 流
          - 每笔成交触发 tick_detector 检测
          - 检测到插针立即异步下单
          - 定期（每5s）更新订阅币种 + 风控
        """
        # 初始化 WebSocket
        self._ws = BinanceFuturesWS(on_trade=self._on_ws_trade)

        # 首次扫描获取币种列表
        try:
            symbols = await self.scanner.get_symbols()
        except Exception as e:
            logger.error(f"首次扫描失败: {e}")
            symbols = [cfg_module.SYMBOL]

        STATE["symbols_active"] = symbols
        # 为每个币种建一个 TickSpikeDetector
        for sym in symbols:
            self._tick_detectors[sym] = TickSpikeDetector(sym, cfg_module)
            # 预热 filters
            asyncio.create_task(self.pm._fetch_filters(sym))

        # 启动 WebSocket
        await self._ws.start(symbols)

        # 主循环：定期扫描更新订阅、检查持仓超时、刷新余额
        last_scan = 0
        last_balance_check = 0
        while self._running:
            try:
                now = time.time()

                # 每 scan_interval 秒重新扫描 + 更新订阅
                scan_interval = getattr(cfg_module, "AUTO_REFRESH_SEC", 900)
                if now - last_scan > scan_interval:
                    last_scan = now
                    try:
                        new_syms = await self.scanner.get_symbols()
                        if new_syms and set(new_syms) != set(STATE.get("symbols_active", [])):
                            STATE["symbols_active"] = new_syms
                            # 保留有持仓的币种
                            open_syms = {p.symbol for p in self.pm.open_positions}
                            sub_syms = list(set(new_syms) | open_syms)
                            for s in sub_syms:
                                if s not in self._tick_detectors:
                                    self._tick_detectors[s] = TickSpikeDetector(s, cfg_module)
                            await self._ws.update_symbols(sub_syms)
                    except Exception as e:
                        logger.warning(f"扫描更新失败: {e}")

                # 每30秒刷新总权益
                if now - last_balance_check > 30:
                    last_balance_check = now
                    try:
                        equity = await self.ex.get_total_equity(cfg_module.QUOTE_ASSET)
                        self.rm.update_balance(equity)
                    except Exception:
                        pass

                # 持仓监控（用WS收到的最新价）
                await self._tick_check_positions()

                # WS 统计
                STATE["last_tick"] = int(now)
                STATE["ws_stats"] = self._ws.stats if self._ws else {}

                await asyncio.sleep(0.5)  # 主循环每0.5s跑一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"tick主循环错误: {e}", exc_info=True)
                STATE["errors"].append(f"{datetime.now().strftime('%H:%M:%S')} [tick] {e}")
                STATE["errors"] = STATE["errors"][-60:]
                await asyncio.sleep(1)

        # 退出时清理
        if self._ws:
            await self._ws.stop()

    async def _on_ws_trade(self, symbol: str, price: float, qty: float,
                           trade_time_ms: int, is_buyer_maker: bool):
        """
        WebSocket 每笔成交回调 — 核心热路径
        
        必须快：任何阻塞都会导致消息堆积
        把下单放到 asyncio.create_task 异步去做
        """
        STATE["prices"][symbol] = price
        self._last_prices_ms[symbol] = trade_time_ms

        det = self._tick_detectors.get(symbol)
        if det is None:
            return

        signal = det.on_trade(price, qty, trade_time_ms, is_buyer_maker)
        if signal is None:
            return

        STATE["signals_found"] = STATE.get("signals_found", 0) + 1
        logger.info(f"[TICK] {symbol} {signal.direction} "
                    f"tip={signal.spike_tip:.6f} entry={signal.entry_price:.6f} "
                    f"tp={signal.take_profit:.6f} sl={signal.stop_loss:.6f} "
                    f"({signal.reason})")

        # 暂停检查
        if STATE.get("trading_paused", False):
            STATE["signals_blocked"] = STATE.get("signals_blocked", 0) + 1
            logger.info(f"[TICK] {symbol} 交易已暂停，信号被忽略")
            return

        # 风控检查
        can_trade, reason = self.rm.can_trade()
        if not can_trade:
            STATE["signals_blocked"] = STATE.get("signals_blocked", 0) + 1
            return

        # 异步下单，不阻塞 WS 消息处理
        asyncio.create_task(self._tick_open_position(signal, symbol))

    async def _tick_open_position(self, signal: TickSignal, symbol: str):
        """把 TickSignal 适配成 SpikeSignal 调 PositionManager"""
        from strategy.detector import SpikeSignal as KSig
        ks = KSig(
            direction=signal.direction,
            entry_price=signal.entry_price,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            spike_tip=signal.spike_tip,
            spike_root=signal.spike_root,
            spike_length=signal.spike_length,
            atr=0.0, recovery_pct=0.0, rr_ratio=0.0, score=100.0, candle=None,
        )
        try:
            await self.pm.try_open(ks, symbol)
        except Exception as e:
            logger.error(f"tick 下单失败 {symbol}: {e}")

    async def _tick_check_positions(self):
        """
        tick 模式的持仓监控：
          1. TP/SL 检查（用最新价）
          2. 超时检查（TICK_MAX_HOLD_MS，默认3秒）
        """
        if not self.pm.open_positions:
            return
        max_hold_ms = getattr(cfg_module, "TICK_MAX_HOLD_MS", 3000)
        now = time.time()
        for pos in list(self.pm.open_positions):
            price = STATE.get("prices", {}).get(pos.symbol, 0)
            if price <= 0:
                continue
            age_ms = (now - pos.open_time) * 1000
            # TP/SL 优先
            await self.pm.monitor_positions(price, pos.symbol)
            # tick模式超时（覆盖原 MAX_HOLD_SECONDS）
            if pos.status == "OPEN" and age_ms >= max_hold_ms:
                logger.info(f"[TICK-TIMEOUT] #{pos.id} {pos.symbol} {age_ms:.0f}ms")
                await self.pm._close(pos, price, "TIMEOUT")

    async def _tick(self):
        self._tick_count += 1

        if self._tick_count % BALANCE_UPDATE_INTERVAL == 0:
            try:
                # 用总权益而不是可用余额，避免持仓锁保证金时误判高回撤
                equity = await self.ex.get_total_equity(cfg_module.QUOTE_ASSET)
                self.rm.update_balance(equity)
            except Exception:
                pass

        symbols = await self.scanner.get_symbols()
        STATE["symbols_active"] = symbols
        STATE["last_tick"]      = int(time.time())
        STATE["scan_mode"]      = getattr(cfg_module, "SCAN_MODE", "single")

        for sym in symbols:
            if sym not in self._workers:
                logger.info(f"添加币种: {sym}")
                self._workers[sym] = SymbolWorker(sym, self.ex, self.pm, self.rm)

        for sym in list(self._workers.keys()):
            if sym not in symbols:
                # 有未平仓位时不删除 worker（继续监控 TP/SL/timeout）
                has_open = any(p.symbol == sym for p in self.pm.open_positions)
                if has_open:
                    logger.info(f"币种{sym}已移出扫描列表，但有持仓，继续监控")
                    continue
                logger.info(f"移除币种: {sym}")
                del self._workers[sym]
                STATE["detectors"].pop(sym, None)
                STATE["prices"].pop(sym, None)

        sym_list = list(self._workers.keys())
        for i in range(0, len(sym_list), 5):
            batch = sym_list[i:i+5]
            results = await asyncio.gather(
                *[self._workers[s].tick() for s in batch],
                return_exceptions=True
            )
            for sym, res in zip(batch, results):
                if isinstance(res, Exception):
                    logger.warning(f"[{sym}] tick error: {res}")
            if i + 5 < len(sym_list):
                await asyncio.sleep(0.1)

        # ── 全局持仓监控（双重保险）─────────────────────────
        # 就算 worker 意外死亡/被移除，持仓也要被监控
        # 每10个tick (约8秒) 检查一次所有持仓
        if self._tick_count % 10 == 0:
            await self._orphan_monitor()

    async def _orphan_monitor(self):
        """
        全局持仓监控：
          1. 对所有持仓检查 timeout（不依赖worker）
          2. 对没在worker管辖内的持仓(孤儿)，主动查价检查 TP/SL
        """
        open_positions = self.pm.open_positions
        if not open_positions:
            return

        # 按symbol分组需要查价的
        orphan_syms = set()
        for pos in open_positions:
            if pos.symbol not in self._workers:
                orphan_syms.add(pos.symbol)

        # 查孤儿币种的最新价
        for sym in orphan_syms:
            try:
                ticker = await self.ex.get_ticker(sym)
                price = float(ticker.get("askPrice", 0) or ticker.get("bidPrice", 0))
                if price > 0:
                    STATE["prices"][sym] = price
                    logger.debug(f"[孤儿监控] {sym} @ {price}")
                    # 用PositionManager的监控逻辑检查这个币的持仓
                    await self.pm.monitor_positions(price, sym)
            except Exception as e:
                logger.warning(f"[孤儿监控] {sym} 查价失败: {e}")

        # 对所有持仓强制检查timeout（即使worker还在也做一次兜底）
        # monitor_positions 里已经有 timeout 逻辑
        for pos in list(self.pm.open_positions):
            if pos.age_seconds >= cfg_module.MAX_HOLD_SECONDS:
                # 已经超时还没平，强制平
                cur_price = STATE.get("prices", {}).get(pos.symbol, 0)
                if cur_price > 0:
                    logger.warning(f"[孤儿监控] 强制平仓 #{pos.id} {pos.symbol} 超时 {pos.age_seconds:.0f}s")
                    await self.pm._close(pos, cur_price, "TIMEOUT")

    def stop(self):
        self._running    = False
        STATE["running"] = False

    def apply_live_config(self, updates: dict):
        allowed = {
            "SPIKE_RATIO", "SPIKE_VS_ATR", "MIN_SPIKE_PIPS",
            "MIN_RECOVERY", "MAX_RECOVERY",
            "TP_RATIO", "SL_RATIO", "SL_ATR_MULT", "MIN_RR",
            "MAX_HOLD_SECONDS", "ORDER_USDT", "MAX_OPEN_ORDERS",
            "TREND_FILTER", "MA_PERIOD",
            "DAILY_LOSS_LIMIT_USDT", "MAX_DRAWDOWN_PCT",
            "MAX_CONSECUTIVE_LOSSES",
            "SCAN_MODE", "SYMBOL", "SYMBOL_LIST",
            "AUTO_MIN_GAIN_PCT", "AUTO_MIN_VOLUME_USDT",
            "AUTO_MAX_SYMBOLS", "AUTO_REFRESH_SEC",
            "LEVERAGE", "MARGIN_TYPE",
            "USE_TRAILING_TP", "TRAIL_ACTIVATE_PCT", "TRAIL_RETRACE_PCT",
            "BE_ACTIVATE_PCT", "MARKET_FILTER",
            "TICK_LOOKBACK_MS", "TICK_MIN_SPIKE_PCT",
            "TICK_TP_RATIO", "TICK_SL_RATIO",
            "TICK_COOLDOWN_MS", "TICK_MAX_HOLD_MS",
        }
        changed = []
        for k, v in updates.items():
            if k in allowed:
                setattr(cfg_module, k, v)
                changed.append(f"{k}={v}")
        if changed:
            logger.info(f"热更新: {', '.join(changed)}")
            STATE["live_config"] = _snapshot_config()
            STATE["scan_mode"]   = getattr(cfg_module, "SCAN_MODE", "single")
            for sym, worker in self._workers.items():
                worker.detector = SpikeDetector(cfg_module)
                STATE["detectors"][sym] = worker.detector
        return changed


_bot_instance: TradingBot = None


async def run():
    global _bot_instance
    _bot_instance = TradingBot()
    try:
        await _bot_instance.start()
    finally:
        await _bot_instance.ex.close()
