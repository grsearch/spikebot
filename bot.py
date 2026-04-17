"""
主交易循环 - 多币种版本
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict

import config as cfg_module
from core.exchange import BinanceREST
from core.scanner import SymbolScanner
from strategy.detector import SpikeDetector, Candle
from strategy.position_manager import PositionManager
from strategy.risk_manager import RiskManager

logger = logging.getLogger(__name__)

STATE = {
    "running":          False,
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
        "DRY_RUN", "LEVERAGE", "MARGIN_TYPE",
        "USE_TRAILING_TP", "TRAIL_ACTIVATE_PCT", "TRAIL_RETRACE_PCT",
        "BE_ACTIVATE_PCT", "MARKET_FILTER", "FEE_RATE",
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
        klines = await self.ex.get_klines(self.symbol, "1s", cfg_module.KLINE_LIMIT)
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

        STATE["positions"]   = self.pm
        STATE["risk"]        = self.rm
        STATE["dry_run"]     = getattr(cfg_module, "DRY_RUN", False)
        STATE["scan_mode"]   = getattr(cfg_module, "SCAN_MODE", "single")
        STATE["live_config"] = _snapshot_config()

    async def start(self):
        logger.info("=== Spike Bot Starting ===")
        await self.pm.init_filters()

        try:
            bal = await self.ex.get_asset_balance(cfg_module.QUOTE_ASSET)
            self.rm.update_balance(bal)
            logger.info(f"账户余额: {bal:.2f} {cfg_module.QUOTE_ASSET}")
        except Exception as e:
            logger.warning(f"获取余额失败: {e}")

        dry = STATE["dry_run"]
        lev = getattr(cfg_module, "LEVERAGE", 5)
        mt  = getattr(cfg_module, "MARGIN_TYPE", "ISOLATED")
        logger.info(f"模式: {'DRY-RUN 空跑' if dry else 'LIVE 实盘'} | 合约 | 杠杆{lev}x | {mt}")
        self._running    = True
        STATE["running"] = True

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

    async def _tick(self):
        self._tick_count += 1

        if self._tick_count % BALANCE_UPDATE_INTERVAL == 0:
            try:
                bal = await self.ex.get_asset_balance(cfg_module.QUOTE_ASSET)
                self.rm.update_balance(bal)
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
            # 如果切换了扫描模式或币种配置，立即重置 scanner 缓存，下次 tick 生效
            scan_keys = {"SCAN_MODE", "SYMBOL", "SYMBOL_LIST",
                         "AUTO_MIN_GAIN_PCT", "AUTO_MIN_VOLUME_USDT",
                         "AUTO_MAX_SYMBOLS", "AUTO_REFRESH_SEC"}
            if any(k in updates for k in scan_keys):
                self.scanner._last_refresh = 0
                self.scanner._symbols = []
                logger.info("scanner 缓存已重置，下次 tick 立即重新扫描")
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
