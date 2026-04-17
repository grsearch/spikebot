"""
风险控制模块
- 每日亏损熔断
- 最大回撤保护
- 连续亏损冷却
- 账户余额安全检查
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    # 每日统计
    day: date = field(default_factory=date.today)
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_wins: int = 0

    # 回撤追踪
    peak_balance: float = 0.0
    current_balance: float = 0.0

    # 连续亏损
    consecutive_losses: int = 0
    last_loss_time: float = 0.0

    # 熔断状态
    circuit_broken: bool = False
    circuit_reason: str = ""
    circuit_time: float = 0.0
    circuit_cooldown: float = 3600.0  # 熔断冷却1小时

    def reset_daily(self):
        self.day = date.today()
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        logger.info("Daily stats reset")

    @property
    def daily_win_rate(self) -> float:
        if self.daily_trades == 0:
            return 0.0
        return self.daily_wins / self.daily_trades * 100

    @property
    def drawdown_pct(self) -> float:
        if self.peak_balance == 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / self.peak_balance * 100


class RiskManager:
    def __init__(self, config):
        self.cfg = config
        self.state = RiskState()
        self._enabled = True

    def update_balance(self, balance: float):
        """每次拉取账户余额后调用"""
        self.state.current_balance = balance
        if balance > self.state.peak_balance:
            self.state.peak_balance = balance

        # 检查每日重置
        today = date.today()
        if self.state.day != today:
            self.state.reset_daily()

    def record_trade(self, pnl: float):
        """每笔交易完成后调用"""
        self.state.daily_pnl += pnl
        self.state.daily_trades += 1

        if pnl > 0:
            self.state.daily_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1
            self.state.last_loss_time = time.time()

        logger.info(
            f"Trade recorded: pnl={pnl:+.4f} | "
            f"daily={self.state.daily_pnl:+.4f} | "
            f"consec_loss={self.state.consecutive_losses}"
        )
        self._check_circuit_breaker()

    def _check_circuit_breaker(self):
        cfg = self.cfg

        # 1. 每日亏损上限
        daily_loss_limit = getattr(cfg, 'DAILY_LOSS_LIMIT_USDT', 10.0)
        if self.state.daily_pnl <= -daily_loss_limit:
            self._trigger(f"每日亏损达到上限 {daily_loss_limit} USDT")
            return

        # 2. 最大回撤
        max_dd = getattr(cfg, 'MAX_DRAWDOWN_PCT', 5.0)
        if self.state.drawdown_pct >= max_dd:
            self._trigger(f"回撤达到 {self.state.drawdown_pct:.1f}% (上限{max_dd}%)")
            return

        # 3. 连续亏损
        max_consec = getattr(cfg, 'MAX_CONSECUTIVE_LOSSES', 5)
        if self.state.consecutive_losses >= max_consec:
            self._trigger(f"连续亏损 {self.state.consecutive_losses} 次")
            return

    def _trigger(self, reason: str):
        if not self.state.circuit_broken:
            logger.warning(f"⚡ 熔断触发: {reason}")
            self.state.circuit_broken = True
            self.state.circuit_reason = reason
            self.state.circuit_time = time.time()

    def can_trade(self) -> tuple[bool, str]:
        """
        返回 (是否允许交易, 原因)
        每次 try_open 前调用
        """
        if not self._enabled:
            return False, "风控模块已关闭"

        if self.state.circuit_broken:
            elapsed = time.time() - self.state.circuit_time
            if elapsed < self.state.circuit_cooldown:
                remaining = int(self.state.circuit_cooldown - elapsed)
                return False, f"熔断冷却中 {remaining}s | {self.state.circuit_reason}"
            else:
                # 冷却结束，自动恢复
                logger.info("熔断冷却结束，恢复交易")
                self.state.circuit_broken = False
                self.state.consecutive_losses = 0

        # 每日交易次数上限
        max_daily = getattr(self.cfg, 'MAX_DAILY_TRADES', 200)
        if self.state.daily_trades >= max_daily:
            return False, f"今日交易次数达上限 {max_daily}"

        return True, "OK"

    def manual_reset(self):
        """手动解除熔断（dashboard按钮调用）"""
        self.state.circuit_broken = False
        self.state.circuit_reason = ""
        self.state.consecutive_losses = 0
        logger.warning("风控熔断已手动解除")

    @property
    def status_dict(self) -> dict:
        s = self.state
        ok, reason = self.can_trade()
        return {
            "can_trade":          ok,
            "reason":             reason,
            "circuit_broken":     s.circuit_broken,
            "circuit_reason":     s.circuit_reason,
            "daily_pnl":          round(s.daily_pnl, 4),
            "daily_trades":       s.daily_trades,
            "daily_win_rate":     round(s.daily_win_rate, 1),
            "consecutive_losses": s.consecutive_losses,
            "drawdown_pct":       round(s.drawdown_pct, 2),
            "peak_balance":       round(s.peak_balance, 2),
            "current_balance":    round(s.current_balance, 2),
        }
