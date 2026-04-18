"""
Binance REST Client - USD-M Futures 合约版本
支持做多（LONG）和做空（SHORT），使用单向持仓模式
"""
import hashlib
import hmac
import time
import asyncio
import logging
from typing import Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


class BinanceREST:
    """
    合约版客户端：
      - 下单到 /fapi/v1/order （USD-M Futures）
      - 账户信息 /fapi/v2/account
      - K线 /fapi/v1/klines
      - 启动时自动设置杠杆
    """
    def __init__(self, api_key: str, api_secret: str, base_url: str,
                 leverage: int = 5, hedge_mode: bool = False):
        self.api_key    = api_key
        self.api_secret = api_secret
        # 自动把现货URL转合约URL（兼容旧config）
        if "api.binance.com" in base_url:
            base_url = base_url.replace("api.binance.com", "fapi.binance.com")
        self.base_url   = base_url.rstrip("/")
        self.leverage   = leverage
        self.hedge_mode = hedge_mode  # False=单向(默认), True=双向(LONG/SHORT同时持仓)
        self._session: Optional[aiohttp.ClientSession] = None
        self._weight_used = 0
        self._leverage_set = set()  # 已设置杠杆的symbol
        self._margin_type_set = set()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=timeout,
            )
        return self._session

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    async def _request(
        self, method: str, path: str, params: dict = None,
        signed: bool = False, retries: int = 3
    ) -> dict:
        session = await self._get_session()
        params  = params or {}
        if signed:
            params = self._sign(params)

        url = f"{self.base_url}{path}"
        last_err = None

        for attempt in range(retries):
            try:
                async with session.request(method, url, params=params) as resp:
                    used = resp.headers.get("X-MBX-USED-WEIGHT-1M", "0")
                    self._weight_used = int(used)

                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 10))
                        logger.warning(f"Rate limit hit, sleeping {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    # 主动退避：当权重使用 > 80%上限时主动延迟
                    # 合约默认上限 2400/min = 40/sec
                    if self._weight_used > 1920:  # 80%
                        logger.warning(f"API权重用至{self._weight_used}/2400，主动sleep 3s")
                        await asyncio.sleep(3)

                    if resp.status == 418:
                        logger.error("IP banned by Binance!")
                        await asyncio.sleep(60)
                        continue

                    data = await resp.json()
                    if resp.status != 200:
                        # 过滤一些"无害"的错误
                        code = data.get("code", 0) if isinstance(data, dict) else 0
                        # -4046: No need to change margin type (already set)
                        # -4059: No need to change position mode
                        # -4028: Leverage reduction is not supported in Isolated Mode with open positions
                        if code in (-4046, -4059):
                            return data
                        logger.error(f"API error {resp.status}: {data}")
                        last_err = data
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return data

            except asyncio.TimeoutError:
                logger.warning(f"Timeout attempt {attempt+1}/{retries}")
                last_err = "timeout"
                await asyncio.sleep(0.3)
            except aiohttp.ClientError as e:
                logger.warning(f"Network error: {e}")
                last_err = str(e)
                await asyncio.sleep(0.5)

        raise RuntimeError(f"Request failed after {retries} retries: {last_err}")

    # ── K线 ──────────────────────────────────────────────
    async def get_klines(self, symbol: str, interval: str = "1s", limit: int = 120):
        """
        合约K线接口
        - interval='1s': 合约API不支持，改用 aggTrades 本地合成
        - 其他: 直接调用 /fapi/v1/klines
        """
        if interval == "1s":
            return await self._synthesize_1s_klines(symbol, limit)

        data = await self._request("GET", "/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        klines = []
        for k in data:
            klines.append({
                "open_time": k[0],
                "open":  float(k[1]),
                "high":  float(k[2]),
                "low":   float(k[3]),
                "close": float(k[4]),
                "volume":float(k[5]),
                "close_time": k[6],
                "is_closed": True,
            })
        return klines

    async def _synthesize_1s_klines(self, symbol: str, limit: int = 120):
        """
        用 aggTrades 合成 1s K线
        
        策略：
          1. 先拉最近的1000笔
          2. 如果覆盖时间 < limit 秒 且 成交够多，再往前拉一页
          3. 如果已经覆盖 limit 秒就停止
        
        活跃币(CTSI/SOL等): 1000笔约覆盖 30秒~2分钟，通常一次够
        低活跃币: 可能需要多页拉取
        """
        target_duration_ms = limit * 1000  # 目标覆盖的毫秒数
        all_trades = []
        
        # 第一次拉最近的成交
        trades = await self._request("GET", "/fapi/v1/aggTrades", {
            "symbol": symbol, "limit": 1000
        })
        if not trades:
            return []
        all_trades = trades
        
        # 检查覆盖时间
        first_t = int(trades[0]["T"])
        last_t  = int(trades[-1]["T"])
        covered_ms = last_t - first_t
        
        # 如果覆盖不够 limit 秒，最多再拉2页（避免拖慢）
        pages_fetched = 1
        while covered_ms < target_duration_ms and pages_fetched < 3:
            # 用 endTime 往前翻
            try:
                prev_trades = await self._request("GET", "/fapi/v1/aggTrades", {
                    "symbol": symbol,
                    "endTime": first_t - 1,  # 严格小于之前第一笔的时间
                    "limit": 1000
                })
                if not prev_trades:
                    break
                all_trades = prev_trades + all_trades
                first_t = int(prev_trades[0]["T"])
                covered_ms = last_t - first_t
                pages_fetched += 1
            except Exception as e:
                logger.debug(f"{symbol} 历史aggTrades拉取失败: {e}")
                break
        
        trades = all_trades

        # 按秒分桶: key=秒级时间戳, value=[price, qty, ...]
        buckets = {}  # {second: {"prices":[...], "qtys":[...], "first_t":..., "last_t":...}}
        for t in trades:
            price = float(t["p"])
            qty   = float(t["q"])
            ms_t  = int(t["T"])
            sec_t = (ms_t // 1000) * 1000   # 对齐到秒

            if sec_t not in buckets:
                buckets[sec_t] = {
                    "first_price": price,
                    "high": price,
                    "low":  price,
                    "close_price": price,
                    "volume": qty,
                    "close_time": sec_t + 999,
                }
            else:
                b = buckets[sec_t]
                if price > b["high"]: b["high"] = price
                if price < b["low"]:  b["low"]  = price
                b["close_price"] = price  # 按时间顺序，最后一笔就是close
                b["volume"] += qty

        # 转成K线列表（按时间升序）
        sorted_times = sorted(buckets.keys())
        # 只保留最近 limit 根
        if len(sorted_times) > limit:
            sorted_times = sorted_times[-limit:]

        klines = []
        now_sec = int(time.time())
        for t in sorted_times:
            b = buckets[t]
            # 判断这根K线是否已关闭（当前秒内还在变动则未关闭）
            is_closed = (t // 1000) < now_sec
            klines.append({
                "open_time": t,
                "open":  b["first_price"],
                "high":  b["high"],
                "low":   b["low"],
                "close": b["close_price"],
                "volume": b["volume"],
                "close_time": b["close_time"],
                "is_closed": is_closed,
            })
        return klines

    async def get_orderbook(self, symbol: str, limit: int = 5):
        return await self._request("GET", "/fapi/v1/depth", {
            "symbol": symbol, "limit": limit
        })

    async def get_ticker(self, symbol: str):
        return await self._request("GET", "/fapi/v1/ticker/bookTicker", {
            "symbol": symbol
        })

    # ── 账户 & 持仓 ──────────────────────────────────────
    async def get_account(self):
        """合约账户信息"""
        return await self._request("GET", "/fapi/v2/account", {}, signed=True)

    async def get_asset_balance(self, asset: str = "USDT") -> float:
        """
        合约账户可用余额（用于开仓时判断够不够钱）
        """
        account = await self.get_account()
        if "availableBalance" in account:
            return float(account["availableBalance"])
        for a in account.get("assets", []):
            if a["asset"] == asset:
                return float(a["availableBalance"])
        return 0.0

    async def get_total_equity(self, asset: str = "USDT") -> float:
        """
        合约账户总权益 = 钱包余额 + 未实现盈亏
        用于风控计算回撤（不受持仓保证金锁定影响）
        
        有持仓时：
          availableBalance 会因保证金锁定而减少
          但 totalWalletBalance + unrealizedProfit 反映真实总资产
        """
        account = await self.get_account()
        # 优先用 totalMarginBalance（= 钱包+未实现盈亏）
        if "totalMarginBalance" in account:
            return float(account["totalMarginBalance"])
        # fallback: 钱包余额 + 未实现盈亏
        wallet = float(account.get("totalWalletBalance", 0))
        unrealized = float(account.get("totalUnrealizedProfit", 0))
        if wallet > 0:
            return wallet + unrealized
        # 再 fallback: 找资产
        for a in account.get("assets", []):
            if a["asset"] == asset:
                w = float(a.get("walletBalance", 0))
                u = float(a.get("unrealizedProfit", 0))
                return w + u
        return 0.0

    async def get_positions(self):
        """获取所有持仓"""
        return await self._request("GET", "/fapi/v2/positionRisk", {}, signed=True)

    async def get_position(self, symbol: str):
        """获取指定symbol的持仓"""
        positions = await self._request(
            "GET", "/fapi/v2/positionRisk",
            {"symbol": symbol}, signed=True
        )
        return positions[0] if positions else None

    async def get_exchange_info(self, symbol: str):
        """合约symbol信息"""
        data = await self._request("GET", "/fapi/v1/exchangeInfo", {})
        for s in data["symbols"]:
            if s["symbol"] == symbol:
                return s
        return None

    # ── 杠杆 & 保证金模式 ────────────────────────────────
    async def set_leverage(self, symbol: str, leverage: int = None):
        """设置指定symbol的杠杆倍数"""
        lev = leverage or self.leverage
        try:
            result = await self._request(
                "POST", "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": lev},
                signed=True
            )
            self._leverage_set.add(symbol)
            logger.info(f"{symbol} 杠杆设为 {lev}x")
            return result
        except Exception as e:
            logger.warning(f"设置{symbol}杠杆失败: {e}")
            return None

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED"):
        """
        设置保证金模式
        margin_type: ISOLATED（逐仓）| CROSSED（全仓）
        """
        try:
            result = await self._request(
                "POST", "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": margin_type},
                signed=True
            )
            self._margin_type_set.add(symbol)
            return result
        except Exception as e:
            # -4046: already this margin type, not an error
            if "-4046" not in str(e):
                logger.warning(f"设置{symbol}保证金模式失败: {e}")
            return None

    async def ensure_position_mode(self):
        """
        确保账户是单向持仓模式（One-way Mode）
        如果是双向(Hedge)模式，下单会报 -4061 错误
        只需在启动时调用一次
        """
        if getattr(self, "_position_mode_checked", False):
            return
        try:
            # 查询当前模式
            info = await self._request(
                "GET", "/fapi/v1/positionSide/dual", {}, signed=True
            )
            dual_side = info.get("dualSidePosition", False)
            if dual_side:
                logger.warning("账户为双向持仓模式，自动切换为单向模式...")
                try:
                    await self._request(
                        "POST", "/fapi/v1/positionSide/dual",
                        {"dualSidePosition": "false"}, signed=True
                    )
                    logger.info("✓ 已切换为单向持仓模式")
                except Exception as e:
                    if "-4059" in str(e):
                        pass  # 已经是单向
                    else:
                        logger.error(f"切换持仓模式失败，请手动切换: {e}")
            else:
                logger.info("✓ 账户已是单向持仓模式")
            self._position_mode_checked = True
        except Exception as e:
            logger.warning(f"持仓模式检测失败(可忽略): {e}")
            self._position_mode_checked = True

    async def ensure_symbol_setup(self, symbol: str):
        """启动时确保symbol已设置好杠杆+保证金模式+持仓模式"""
        await self.ensure_position_mode()
        if symbol not in self._leverage_set:
            await self.set_leverage(symbol)
        if symbol not in self._margin_type_set:
            await self.set_margin_type(symbol, "ISOLATED")

    # ── 下单 ────────────────────────────────────────────
    async def place_limit_order(
        self, symbol: str, side: str, quantity: float,
        price: float, time_in_force: str = "GTC",
        reduce_only: bool = False
    ) -> dict:
        """
        side: BUY（开多/平空）| SELL（开空/平多）
        单向模式下：
          BUY  = 开多（如当前无持仓）或 平空
          SELL = 开空 或 平多
        """
        await self.ensure_symbol_setup(symbol)
        params = {
            "symbol":      symbol,
            "side":        side,
            "type":        "LIMIT",
            "timeInForce": time_in_force,
            "quantity":    f"{quantity:.3f}",
            "price":       f"{price:.6f}",
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        return await self._request("POST", "/fapi/v1/order", params, signed=True)

    async def place_market_order(
        self, symbol: str, side: str, quantity: float,
        reduce_only: bool = False
    ) -> dict:
        """
        市价单
        reduce_only=True 表示只用于平仓，不会意外开新仓
        """
        await self.ensure_symbol_setup(symbol)
        params = {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": f"{quantity:.3f}",
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        return await self._request("POST", "/fapi/v1/order", params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        return await self._request("DELETE", "/fapi/v1/order", {
            "symbol": symbol, "orderId": order_id
        }, signed=True)

    async def get_open_orders(self, symbol: str = None) -> list:
        params = {"symbol": symbol} if symbol else {}
        return await self._request("GET", "/fapi/v1/openOrders", params, signed=True)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
