"""
多币种扫描器
- single : 只监控 config.SYMBOL
- list   : 监控 config.SYMBOL_LIST
- auto   : 每15分钟查 Binance 24h涨幅榜，按涨幅% + 成交量双条件筛选
"""
import logging
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

# 稳定币/计价币黑名单
_STABLES = {"USDC","BUSD","TUSD","USDP","FDUSD","DAI","USDD",
            "SUSD","FRAX","LUSD","EUR","GBP","AUD","BRL"}


class SymbolScanner:
    def __init__(self, exchange, config):
        self.ex  = exchange
        self.cfg = config
        self._symbols: List[str] = []
        self._last_refresh: float = 0
        # 上次筛选的详细信息（供 dashboard 展示）
        self.last_scan_detail: List[Dict] = []
        self.last_scan_time: float = 0

    async def get_symbols(self) -> List[str]:
        mode = getattr(self.cfg, "SCAN_MODE", "single")

        if mode == "single":
            return [self.cfg.SYMBOL]

        if mode == "list":
            return list(self.cfg.SYMBOL_LIST)

        if mode == "auto":
            interval = getattr(self.cfg, "AUTO_REFRESH_SEC", 900)
            now = time.time()
            if not self._symbols or (now - self._last_refresh) >= interval:
                self._symbols = await self._scan_gainers()
                self._last_refresh = now
                self.last_scan_time = now
            return self._symbols

        return [self.cfg.SYMBOL]

    async def _scan_gainers(self) -> List[str]:
        """
        查 Binance 24h ticker，筛选条件：
        1. USDT 计价
        2. 非稳定币
        3. |涨幅| >= AUTO_MIN_GAIN_PCT  （涨跌都算，大振幅 = 容易出插针）
        4. 成交额 >= AUTO_MIN_VOLUME_USDT
        5. 价格 >= AUTO_MIN_PRICE
        按 |涨幅| 从高到低，取前 AUTO_MAX_SYMBOLS 个
        """
        min_gain = getattr(self.cfg, "AUTO_MIN_GAIN_PCT",    30.0)
        min_vol  = getattr(self.cfg, "AUTO_MIN_VOLUME_USDT", 20_000_000)
        min_px   = getattr(self.cfg, "AUTO_MIN_PRICE",       0.0001)
        max_n    = getattr(self.cfg, "AUTO_MAX_SYMBOLS",      10)

        try:
            tickers = await self.ex._request("GET", "/fapi/v1/ticker/24hr")
        except Exception as e:
            logger.error(f"扫描涨幅榜失败: {e}")
            return self._symbols or [self.cfg.SYMBOL]

        candidates = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym[:-4]
            if base in _STABLES:
                continue
            # 排除杠杆代币（UP/DOWN/BULL/BEAR后缀）
            if any(base.endswith(s) for s in ("UP","DOWN","BULL","BEAR","3L","3S")):
                continue
            try:
                gain_pct = float(t.get("priceChangePercent", 0))  # 已是百分比
                vol_usdt = float(t.get("quoteVolume", 0))
                price    = float(t.get("lastPrice", 0))
                high     = float(t.get("highPrice", price))
                low      = float(t.get("lowPrice",  price))
                amp_pct  = (high - low) / price * 100 if price > 0 else 0
            except Exception:
                continue

            if (abs(gain_pct) >= min_gain
                    and vol_usdt >= min_vol
                    and price >= min_px):
                candidates.append({
                    "symbol":    sym,
                    "gain_pct":  round(gain_pct, 2),
                    "amp_pct":   round(amp_pct, 2),
                    "vol_usdt":  vol_usdt,
                    "price":     price,
                })

        # 按 |涨幅| 降序
        candidates.sort(key=lambda x: abs(x["gain_pct"]), reverse=True)
        selected = candidates[:max_n]
        self.last_scan_detail = selected

        syms = [c["symbol"] for c in selected]
        if syms:
            summary = ", ".join(
                f"{c['symbol']}({c['gain_pct']:+.1f}% {c['vol_usdt']/1e6:.0f}M)"
                for c in selected
            )
            logger.info(f"涨幅榜筛选 {len(syms)} 个: {summary}")
        else:
            logger.warning(f"涨幅榜无符合条件的币 (涨幅≥{min_gain}%, 成交额≥{min_vol/1e6:.0f}M)，保持原列表")
            syms = self._symbols or [self.cfg.SYMBOL]

        return syms

    async def force_refresh(self):
        """手动触发立即重新筛选"""
        self._last_refresh = 0
        return await self.get_symbols()
