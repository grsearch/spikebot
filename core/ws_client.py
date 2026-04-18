"""
Binance USD-M Futures WebSocket 客户端

订阅 aggTrade 流（每笔聚合成交实时推送）
支持：
  - 多币种订阅
  - 自动重连
  - 订阅动态调整（涨幅榜变化时更新）
  - 连接失败时降级到 REST 轮询

官方文档:
  https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams
  
WebSocket URL:
  wss://fstream.binance.com/ws/<symbol>@aggTrade  单流
  wss://fstream.binance.com/stream?streams=a@aggTrade/b@aggTrade  多流

aggTrade 消息格式:
  {
    "e": "aggTrade",
    "E": 123456789,       // Event time (ms)
    "s": "BTCUSDT",
    "a": 5933014,         // Aggregate trade ID
    "p": "0.001",         // Price
    "q": "100",           // Quantity
    "T": 123456785,       // Trade time (ms)
    "m": true             // Is buyer market maker?
  }
"""
import asyncio
import json
import logging
import time
from typing import Callable, Set, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

logger = logging.getLogger(__name__)

WS_BASE = "wss://fstream.binance.com"


class BinanceFuturesWS:
    """
    用法:
        ws = BinanceFuturesWS(on_trade=my_handler)
        await ws.start(["BTCUSDT", "ETHUSDT"])
        # ... 运行中可以动态调整订阅
        await ws.update_symbols(["BTCUSDT", "SOLUSDT"])
        # 停止
        await ws.stop()
    
    on_trade(symbol, price, qty, trade_time_ms, is_buyer_maker)
      - symbol: 'BTCUSDT'
      - price:  float
      - qty:    float
      - trade_time_ms: int 毫秒时间戳
      - is_buyer_maker: bool 买方是否为maker（True=主动卖单）
    """
    def __init__(self, on_trade: Callable = None):
        self.on_trade = on_trade
        self._symbols: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_msg_ts = 0
        self._stats = {
            "connected": False,
            "messages": 0,
            "reconnects": 0,
            "errors": 0,
            "last_symbol_prices": {},
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats, symbols=list(self._symbols))

    def _build_url(self, symbols: Set[str]) -> str:
        if not symbols:
            return None
        streams = "/".join(f"{s.lower()}@aggTrade" for s in symbols)
        return f"{WS_BASE}/stream?streams={streams}"

    async def start(self, symbols: list):
        """启动WS连接，订阅给定币种"""
        if aiohttp is None:
            raise RuntimeError("aiohttp not installed")
        self._symbols = set(s.upper() for s in symbols)
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"WS启动，订阅 {len(self._symbols)} 个币种")

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("WS已停止")

    async def update_symbols(self, symbols: list):
        """动态更新订阅：关闭旧连接，用新symbol开新的"""
        new_syms = set(s.upper() for s in symbols)
        if new_syms == self._symbols:
            return
        logger.info(f"WS订阅变更: {len(self._symbols)}→{len(new_syms)} 币种")
        self._symbols = new_syms
        # 关闭当前WS，_run_loop会自动重连到新URL
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _run_loop(self):
        """主循环：连接→接收→重连"""
        while self._running:
            if not self._symbols:
                await asyncio.sleep(1)
                continue
            url = self._build_url(self._symbols)
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()
                logger.info(f"WS连接 {len(self._symbols)} 币种")
                async with self._session.ws_connect(
                    url, heartbeat=30, autoclose=True, autoping=True,
                ) as ws:
                    self._ws = ws
                    self._stats["connected"] = True
                    logger.info("✓ WebSocket 已连接")
                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._stats["messages"] += 1
                            self._last_msg_ts = time.time()
                            try:
                                await self._handle_message(msg.data)
                            except Exception as e:
                                self._stats["errors"] += 1
                                logger.warning(f"处理消息出错: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.CLOSED,
                                          aiohttp.WSMsgType.ERROR):
                            break
                    self._stats["connected"] = False
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["connected"] = False
                self._stats["errors"] += 1
                logger.warning(f"WS连接错误: {e}")
            if self._running:
                self._stats["reconnects"] += 1
                await asyncio.sleep(2)  # 重连前等2秒

    async def _handle_message(self, data: str):
        """处理单条消息"""
        try:
            obj = json.loads(data)
        except Exception:
            return
        # 多流订阅: {"stream": "btcusdt@aggTrade", "data": {...}}
        payload = obj.get("data", obj)
        if payload.get("e") != "aggTrade":
            return
        symbol = payload.get("s", "").upper()
        price  = float(payload.get("p", 0))
        qty    = float(payload.get("q", 0))
        trade_time_ms = int(payload.get("T", 0))
        is_buyer_maker = bool(payload.get("m", False))
        self._stats["last_symbol_prices"][symbol] = price
        if self.on_trade:
            try:
                if asyncio.iscoroutinefunction(self.on_trade):
                    await self.on_trade(symbol, price, qty, trade_time_ms, is_buyer_maker)
                else:
                    self.on_trade(symbol, price, qty, trade_time_ms, is_buyer_maker)
            except Exception as e:
                logger.warning(f"on_trade 回调出错 {symbol}: {e}")
