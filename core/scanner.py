"""
多币种扫描器
- single : 只监控 config.SYMBOL
- list   : 监控 config.SYMBOL_LIST
- auto   : 每N分钟查 Binance 合约 24h涨幅榜，只筛上涨且成交量达标的币
"""
import logging
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

_STABLES = {"USDC","BUSD","TUSD","USDP","FDUSD","DAI","USDD",
            "SUSD","FRAX","LUSD","EUR","GBP","AUD","BRL"}


class SymbolScanner:
    def __init__(self, exchange, config):
        self.ex  = exchange
        self.cfg = config
        self._symbols: List[str] = []
        self._last_refresh: float = 0
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
        查 Binance 合约 /fapi/v1/ticker/24hr
        筛选条件（合约市场，非现货）：
          1. USDT 计价合约
          2. 非稳定币 / 非杠杆代币
          3. 24h净涨幅 >= +AUTO_MIN_GAIN_PCT  （只要上涨，不要下跌）
          4. 24h成交额 >= AUTO_MIN_VOLUME_USDT
          5. 价格 >= AUTO_MIN_PRICE
        按合约净涨幅从高到低排序，取前 AUTO_MAX_SYMBOLS 个
        """
        min_gain = getattr(self.cfg, "AUTO_MIN_GAIN_PCT",    15.0)
        min_vol  = getattr(self.cfg, "AUTO_MIN_VOLUME_USDT", 10_000_000)
        min_px   = getattr(self.cfg, "AUTO_MIN_PRICE",       0.0001)
        max_n    = getattr(self.cfg, "AUTO_MAX_SYMBOLS",      10)

        try:
            tickers = await self.ex._request("GET", "/fapi/v1/ticker/24hr")
        except Exception as e:
            logger.error(f"扫描涨幅榜失败: {e}")
            return self._symbols or [self.cfg.SYMBOL]

        if not isinstance(tickers, list):
            logger.error(f"涨幅榜接口返回异常: {type(tickers)} {str(tickers)[:200]}")
            return self._symbols or [self.cfg.SYMBOL]

        # 拉取当前正在交易的合约白名单，过滤掉已下线/即将下线的合约
        trading_symbols: set = set()
        try:
            info = await self.ex._request("GET", "/fapi/v1/exchangeInfo")
            if isinstance(info, dict):
                for s in info.get("symbols", []):
                    if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
                        trading_symbols.add(s["symbol"])
            logger.info(f"当前TRADING状态永续合约: {len(trading_symbols)}个")
        except Exception as e:
            logger.warning(f"获取exchangeInfo失败，跳过白名单过滤: {e}")

        candidates = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            # 如果拿到了白名单，只保留TRADING状态的永续合约
            if trading_symbols and sym not in trading_symbols:
                continue
            base = sym[:-4]
            if base in _STABLES:
                continue
            if any(base.endswith(s) for s in ("UP","DOWN","BULL","BEAR","3L","3S")):
                continue
            try:
                gain_pct = float(t.get("priceChangePercent", 0))  # 合约净涨幅（已是百分比）
                vol_usdt = float(t.get("quoteVolume", 0))
                price    = float(t.get("lastPrice", 0))
                high     = float(t.get("highPrice", price))
                low      = float(t.get("lowPrice",  price))
                amp_pct  = (high - low) / price * 100 if price > 0 else 0
            except Exception:
                continue

            # 只要上涨的：净涨幅 >= +min_gain，不要负涨幅的币
            if (gain_pct >= min_gain
                    and vol_usdt >= min_vol
                    and price >= min_px):
                candidates.append({
                    "symbol":   sym,
                    "gain_pct": round(gain_pct, 2),
                    "amp_pct":  round(amp_pct, 2),
                    "vol_usdt": vol_usdt,
                    "price":    price,
                })

        # 按合约净涨幅降序（涨最多的排前面，对齐合约市场涨幅榜）
        candidates.sort(key=lambda x: x["gain_pct"], reverse=True)
        selected = candidates[:max_n]
        self.last_scan_detail = selected

        syms = [c["symbol"] for c in selected]
        if syms:
            summary = ", ".join(
                f"{c['symbol']}({c['gain_pct']:+.1f}% {c['vol_usdt']/1e6:.0f}M)"
                for c in selected
            )
            logger.info(f"合约涨幅榜筛选 {len(syms)} 个 (涨幅≥+{min_gain}%): {summary}")
        else:
            logger.warning(
                f"合约涨幅榜无符合条件的币 (涨幅≥+{min_gain}%, 成交额≥{min_vol/1e6:.0f}M)，保持原列表"
            )
            return self._symbols or [self.cfg.SYMBOL]

        return syms

    async def force_refresh(self):
        """手动触发立即重新筛选"""
        self._last_refresh = 0
        self._symbols = []
        return await self.get_symbols()
