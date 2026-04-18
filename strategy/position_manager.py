"""
仓位管理器 - 合约版 + 跟踪止盈 (Trailing TP)
新增功能:
  1. Trailing TP: 价格达到一定盈利后激活跟踪止盈，锁定更大利润
  2. 分段止盈: 达到部分TP后自动将SL移到成本价（break-even）
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict

from strategy.detector import SpikeSignal
from core.exchange import BinanceREST

logger = logging.getLogger(__name__)


@dataclass
class Position:
    id: int
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    take_profit: float       # 原始TP（最后兜底）
    stop_loss: float         # 当前SL（可能被trailing调整）
    original_sl: float       # 原始SL，记录用
    open_time: float
    # Trailing TP 状态
    trailing_active: bool = False
    peak_price: float = 0.0   # BUY: 最高价 / SELL: 最低价
    # 元数据
    order_id: Optional[int] = None
    status: str = "OPEN"
    close_price: float = 0.0
    close_reason: str = ""
    pnl_usdt: float = 0.0
    signal_score: float = 0.0
    rr_ratio: float = 0.0
    spike_length: float = 0.0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.open_time

    def calc_pnl(self, exit_price: float) -> float:
        if self.direction == "BUY":
            return (exit_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - exit_price) * self.quantity


class PositionManager:
    def __init__(self, exchange: BinanceREST, config):
        self.ex  = exchange
        self.cfg = config
        self._positions: list[Position] = []
        self._pos_counter = 0
        self._total_pnl   = 0.0
        self._win_count   = 0
        self._loss_count  = 0
        self._filters: Dict[str, dict] = {}
        self._default_filters = {"qty_step": 1.0, "price_step": 0.00001, "min_qty": 1.0}

    async def init_filters(self, symbol: str = None):
        await self._fetch_filters(symbol or self.cfg.SYMBOL)

    async def _fetch_filters(self, symbol: str):
        if symbol in self._filters:
            return
        try:
            info = await self.ex.get_exchange_info(symbol)
            if not info:
                self._filters[symbol] = self._default_filters.copy()
                return
            fi = {"qty_step": 1.0, "price_step": 0.00001, "min_qty": 1.0}
            if "quantityPrecision" in info:
                qp = int(info["quantityPrecision"])
                fi["qty_step"] = 10 ** (-qp) if qp > 0 else 1.0
            if "pricePrecision" in info:
                pp = int(info["pricePrecision"])
                fi["price_step"] = 10 ** (-pp) if pp > 0 else 1.0
            for f in info.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    fi["qty_step"] = float(f["stepSize"])
                    fi["min_qty"]  = float(f["minQty"])
                elif f["filterType"] == "MARKET_LOT_SIZE":
                    fi["min_qty"]  = float(f["minQty"])
                elif f["filterType"] == "PRICE_FILTER":
                    fi["price_step"] = float(f["tickSize"])
                elif f["filterType"] == "MIN_NOTIONAL":
                    fi["min_notional"] = float(f.get("notional", 5.0))
            self._filters[symbol] = fi
            logger.info(f"{symbol} filters: {fi}")
        except Exception as e:
            logger.warning(f"获取{symbol}精度失败: {e}")
            self._filters[symbol] = self._default_filters.copy()

    def _get_filter(self, symbol: str) -> dict:
        return self._filters.get(symbol, self._default_filters)

    def _round_qty(self, qty: float, symbol: str) -> float:
        step = self._get_filter(symbol)["qty_step"]
        if step == 0:
            return qty
        return round(round(qty / step) * step, 8)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions if p.status == "OPEN"]

    @property
    def stats(self) -> dict:
        total = self._win_count + self._loss_count
        return {
            "total_trades": total,
            "win":          self._win_count,
            "loss":         self._loss_count,
            "win_rate":     round(self._win_count / total * 100, 1) if total else 0,
            "total_pnl":    round(self._total_pnl, 4),
            "open_count":   len(self.open_positions),
        }

    async def try_open(self, signal: SpikeSignal, symbol: str = None) -> Optional[Position]:
        sym = symbol or self.cfg.SYMBOL
        await self._fetch_filters(sym)

        if len(self.open_positions) >= self.cfg.MAX_OPEN_ORDERS:
            return None

        for p in self.open_positions:
            if p.symbol == sym and p.direction == signal.direction:
                return None

        if signal.score < 25:
            return None

        # ── 趋势过滤：逆趋势交易有天然劣势 ────────────────
        # 如果开启 MARKET_FILTER，在明显趋势中只做顺趋势
        if getattr(self.cfg, "MARKET_FILTER", False):
            from bot import STATE
            det = STATE.get("detectors", {}).get(sym)
            if det:
                ma_long  = det._calc_ma(99)
                ma_short = det._calc_ma(20)
                if ma_long > 0 and ma_short > 0:
                    # BUY 信号在下跌趋势中（MA20 < MA99）不做
                    trend_bearish = ma_short < ma_long * 0.997
                    trend_bullish = ma_short > ma_long * 1.003
                    if signal.direction == "BUY" and trend_bearish:
                        logger.debug(f"{sym} BUY 被趋势过滤（下跌中）")
                        return None
                    if signal.direction == "SELL" and trend_bullish:
                        logger.debug(f"{sym} SELL 被趋势过滤（上涨中）")
                        return None

        try:
            bal = await self.ex.get_asset_balance(self.cfg.QUOTE_ASSET)
            margin_amount = min(self.cfg.ORDER_USDT, bal * 0.95)
        except Exception:
            margin_amount = self.cfg.ORDER_USDT

        leverage = getattr(self.cfg, "LEVERAGE", 5)
        position_value = margin_amount * leverage
        qty = self._round_qty(position_value / signal.entry_price, sym)
        min_qty = self._get_filter(sym)["min_qty"]
        if qty < min_qty:
            return None

        logger.info(
            f"Opening {sym} {signal.direction} | "
            f"entry≈{signal.entry_price:.6f} "
            f"tp={signal.take_profit:.6f} sl={signal.stop_loss:.6f} "
            f"R:R={signal.rr_ratio} score={signal.score}"
        )

        try:
            order = await self.ex.place_market_order(
                symbol=sym, side=signal.direction, quantity=qty,
                reduce_only=False,
            )
            # ── 合约市价单是异步成交 ──────────────────────
            # Binance返回 status: NEW, executedQty: 0 是正常的
            # 只要 orderId 存在，就认为下单成功（后续会成交）
            order_id = order.get("orderId")
            if not order_id:
                logger.error(f"{sym} 下单无orderId，异常响应: {order}")
                return None

            # 尝试立即拿成交价；拿不到就用信号价兜底
            # 实盘中 try_open 返回后，仓位监控会用当前市价计算盈亏，不太依赖入场价精度
            filled_qty = float(order.get("executedQty", 0))
            avg_price_str = order.get("avgPrice") or order.get("averagePrice")
            
            if filled_qty <= 0 or not avg_price_str or float(avg_price_str) <= 0:
                # 异步成交：用下单数量作为已成交，用信号价作为估算成交价
                # 这样仓位能立即被监控，不会错过TP/SL
                filled_qty = qty
                filled_price = signal.entry_price
                logger.info(f"{sym} 市价单异步成交中，使用下单数量{qty}和信号价{filled_price}")
                # 注：如果实际成交价偏离较大，后续monitor会发现并触发相应退出
            else:
                filled_price = float(avg_price_str)

            self._pos_counter += 1
            pos = Position(
                id=self._pos_counter,
                symbol=sym,
                direction=signal.direction,
                entry_price=filled_price,
                quantity=filled_qty,
                take_profit=signal.take_profit,
                stop_loss=signal.stop_loss,
                original_sl=signal.stop_loss,
                open_time=time.time(),
                order_id=order.get("orderId"),
                signal_score=signal.score,
                rr_ratio=signal.rr_ratio,
                spike_length=signal.spike_length,
                peak_price=filled_price,  # 初始化为入场价
            )
            self._positions.append(pos)
            logger.info(f"Position #{pos.id} {sym} opened @ {filled_price:.6f}")
            return pos

        except Exception as e:
            logger.error(f"Open failed {sym}: {e}")
            return None

    async def monitor_positions(self, current_price: float, symbol: str = None):
        for pos in list(self.open_positions):
            if symbol and pos.symbol != symbol:
                continue
            await self._check_exit(pos, current_price)

    async def _check_exit(self, pos: Position, price: float):
        """
        退出逻辑（按优先级）：
          1. 止损 SL
          2. Trailing TP（如果已激活）
          3. Break-even（达到部分盈利，SL上移到成本价）
          4. 超时 TIMEOUT
          5. 原始 TP（兜底，达到后直接平仓）
        """
        use_trail = getattr(self.cfg, "USE_TRAILING_TP", True)
        trail_activate_pct = getattr(self.cfg, "TRAIL_ACTIVATE_PCT", 0.3)
        trail_retrace_pct  = getattr(self.cfg, "TRAIL_RETRACE_PCT", 0.3)
        be_activate_pct    = getattr(self.cfg, "BE_ACTIVATE_PCT", 0.5)

        reason = None
        exit_price = price

        if pos.direction == "BUY":
            # 更新峰值
            if price > pos.peak_price:
                pos.peak_price = price

            # 1. SL 优先检查
            if price <= pos.stop_loss:
                reason = "SL"
                exit_price = pos.stop_loss
            else:
                # 当前盈利相对针长的比例
                profit_abs = price - pos.entry_price
                profit_pct = profit_abs / pos.spike_length if pos.spike_length > 0 else 0

                # 2. Break-even: 盈利>=50%针长时，SL上移到成本价+
                if (not pos.trailing_active
                    and profit_pct >= be_activate_pct
                    and pos.stop_loss < pos.entry_price):
                    # SL移到入场价上方0.05%（留点手续费缓冲）
                    new_sl = pos.entry_price * 1.0005
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = new_sl
                        logger.info(f"#{pos.id} BE激活: SL上移到 {new_sl:.6f}")

                # 3. Trailing TP 激活: 盈利>=activate_pct针长
                if use_trail and not pos.trailing_active and profit_pct >= trail_activate_pct:
                    pos.trailing_active = True
                    logger.info(f"#{pos.id} Trailing TP激活 @ {price:.6f}")

                # 4. Trailing 逻辑: 从峰值回撤一定比例就平仓
                if pos.trailing_active:
                    peak_profit = pos.peak_price - pos.entry_price
                    retrace = (pos.peak_price - price) / pos.spike_length if pos.spike_length > 0 else 0
                    if retrace >= trail_retrace_pct and price > pos.entry_price * 1.0005:
                        reason = "TRAIL"
                        exit_price = price

                # 5. 硬TP兜底: 达到原始TP也走
                if not reason and price >= pos.take_profit:
                    reason = "TP"
                    exit_price = pos.take_profit

        else:  # SELL
            if price < pos.peak_price or pos.peak_price == pos.entry_price:
                pos.peak_price = price

            if price >= pos.stop_loss:
                reason = "SL"
                exit_price = pos.stop_loss
            else:
                profit_abs = pos.entry_price - price
                profit_pct = profit_abs / pos.spike_length if pos.spike_length > 0 else 0

                if (not pos.trailing_active
                    and profit_pct >= be_activate_pct
                    and pos.stop_loss > pos.entry_price):
                    new_sl = pos.entry_price * 0.9995
                    if new_sl < pos.stop_loss:
                        pos.stop_loss = new_sl
                        logger.info(f"#{pos.id} BE激活: SL下移到 {new_sl:.6f}")

                if use_trail and not pos.trailing_active and profit_pct >= trail_activate_pct:
                    pos.trailing_active = True
                    logger.info(f"#{pos.id} Trailing TP激活 @ {price:.6f}")

                if pos.trailing_active:
                    retrace = (price - pos.peak_price) / pos.spike_length if pos.spike_length > 0 else 0
                    if retrace >= trail_retrace_pct and price < pos.entry_price * 0.9995:
                        reason = "TRAIL"
                        exit_price = price

                if not reason and price <= pos.take_profit:
                    reason = "TP"
                    exit_price = pos.take_profit

        if not reason and pos.age_seconds >= self.cfg.MAX_HOLD_SECONDS:
            reason = "TIMEOUT"
            exit_price = price

        if reason:
            await self._close(pos, exit_price, reason)

    async def _close(self, pos: Position, exit_price: float, reason: str):
        close_side = "SELL" if pos.direction == "BUY" else "BUY"
        logger.info(
            f"Closing #{pos.id} {pos.symbol} {pos.direction} @ {exit_price:.6f} "
            f"[{reason}] age={pos.age_seconds:.1f}s"
        )
        try:
            await self.ex.place_market_order(
                pos.symbol, close_side, pos.quantity, reduce_only=True
            )
        except Exception as e:
            logger.error(f"Close failed: {e}")

        pnl = pos.calc_pnl(exit_price)
        pos.status       = "CLOSED"
        pos.close_price  = exit_price
        pos.close_reason = reason
        pos.pnl_usdt     = round(pnl, 4)
        self._total_pnl += pnl
        if pnl > 0:
            self._win_count  += 1
        else:
            self._loss_count += 1
        logger.info(f"#{pos.id} closed | PnL={pnl:+.4f} USDT")

    def get_recent_trades(self, n: int = 20) -> list[Position]:
        return [p for p in self._positions if p.status == "CLOSED"][-n:]
