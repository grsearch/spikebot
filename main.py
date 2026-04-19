#!/usr/bin/env python3
"""启动: python3 main.py"""
import asyncio, logging, sys, os
from logging.handlers import RotatingFileHandler
import config

os.makedirs(config.LOG_DIR, exist_ok=True)

def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL))
    ch = logging.StreamHandler(sys.stdout); ch.setFormatter(fmt); root.addHandler(ch)
    fh = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "bot.log"),
        maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt); root.addHandler(fh)
    return logging.getLogger("main")

async def main():
    logger = setup_logging()

    if config.API_KEY == "YOUR_API_KEY":
        logger.error("请先在 config.py 填写 API_KEY / API_SECRET")
        sys.exit(1)

    logger.info("=" * 55)
    logger.info("实盘交易模式（LIVE）")
    logger.info(f"扫描: {config.SCAN_MODE}  |  Dashboard: http://0.0.0.0:{config.WEB_PORT}")
    logger.info("=" * 55)

    from bot import TradingBot
    from core.exchange import BinanceREST
    from core.scanner import SymbolScanner
    from strategy.position_manager import PositionManager
    from strategy.risk_manager import RiskManager
    from web.dashboard import run_dashboard

    ex = BinanceREST(config.API_KEY, config.API_SECRET, config.BASE_URL)
    scanner = SymbolScanner(ex, config)
    pm = PositionManager(ex, config)
    rm = RiskManager(config)
    bot_instance = TradingBot(ex, scanner, pm, rm, config)

    dashboard_task = asyncio.create_task(
        run_dashboard(bot_instance, config.WEB_HOST, config.WEB_PORT)
    )
    bot_task = asyncio.create_task(bot_instance.start())

    try:
        await asyncio.gather(bot_task, dashboard_task)
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        bot_instance._running = False
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
