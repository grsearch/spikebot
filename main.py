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

    from bot import run as run_bot
    from web.dashboard import run_web

    # 先启动 Web Dashboard（非阻塞，返回 runner 供最终 cleanup）
    web_runner = await run_web()

    try:
        await run_bot()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        await web_runner.cleanup()
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
