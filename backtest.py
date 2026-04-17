"""
回测脚本 - 用真实历史K线验证策略参数
python backtest.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import config
from core.exchange import BinanceREST
from strategy.detector import SpikeDetector, Candle


async def run_backtest(symbol="CTSIUSDT", days=3):
    print(f"\n=== 回测 {symbol} 近{days}天1秒K线 ===\n")

    ex = BinanceREST(config.API_KEY, config.API_SECRET, config.BASE_URL)
    det = SpikeDetector(config)

    # 每次最多拉1000根（Binance限制），分批拉取
    klines_all = []
    limit_per_batch = 1000
    batches = days * 24 * 3600 // limit_per_batch + 1

    print(f"拉取历史数据（{batches}批）...")
    end_time = None
    for i in range(batches):
        params = {"symbol": symbol, "interval": "1s", "limit": limit_per_batch}
        if end_time:
            params["endTime"] = end_time
        try:
            batch = await ex.get_klines(symbol, "1s", limit_per_batch)
            if not batch:
                break
            klines_all = batch + klines_all
            end_time = batch[0]["open_time"] - 1
            print(f"  批次{i+1}: {len(batch)}根，最早={batch[0]['open_time']}")
        except Exception as e:
            print(f"  拉取失败: {e}")
            break

    await ex.close()

    if not klines_all:
        print("未获取到数据，退出")
        return

    print(f"\n共获取 {len(klines_all)} 根1秒K线，开始检测...\n")

    # 模拟逐根回放
    signals = []
    for i in range(config.ATR_PERIOD + 1, len(klines_all)):
        window = klines_all[max(0, i-200):i]
        det.update(window)
        k = klines_all[i]
        candle = Candle(
            open_time=k["open_time"],
            open=k["open"], high=k["high"],
            low=k["low"],   close=k["close"],
            volume=k["volume"],
        )
        sig = det.detect(candle)
        if sig:
            # 向后看 MAX_HOLD_SECONDS 根，模拟出场
            future = klines_all[i+1 : i+1+config.MAX_HOLD_SECONDS]
            outcome = simulate_trade(sig, future)
            signals.append((sig, outcome))

    # 统计
    if not signals:
        print("未发现任何信号")
        return

    wins = losses = timeouts = 0
    total_pnl = 0.0
    print(f"{'方向':<6} {'评分':<6} {'入场':<10} {'出场':<10} {'原因':<8} {'盈亏':<10}")
    print("-" * 55)
    for sig, out in signals[-50:]:  # 打印最后50条
        pnl_str = f"{out['pnl']:+.5f}"
        print(f"{sig.direction:<6} {sig.score:<6.0f} {sig.entry_price:<10.6f} "
              f"{out['exit_price']:<10.6f} {out['reason']:<8} {pnl_str}")

    for sig, out in signals:
        total_pnl += out['pnl']
        if out['reason'] == 'TP':    wins    += 1
        elif out['reason'] == 'SL':  losses  += 1
        else:                         timeouts += 1

    total = len(signals)
    print(f"\n{'='*55}")
    print(f"总信号数:   {total}")
    print(f"胜率(TP):   {wins/total*100:.1f}%  ({wins}次)")
    print(f"亏损(SL):   {losses/total*100:.1f}%  ({losses}次)")
    print(f"超时:       {timeouts/total*100:.1f}%  ({timeouts}次)")
    print(f"总PnL:      {total_pnl:+.4f} USDT（基于{config.ORDER_USDT}U每单估算）")
    print(f"平均每笔:   {total_pnl/total:+.5f} USDT")

    # 按评分分段分析
    print(f"\n─ 按评分段分析 ─")
    for lo, hi in [(0,40),(40,60),(60,80),(80,100)]:
        subset = [(s,o) for s,o in signals if lo <= s.score < hi]
        if not subset: continue
        w = sum(1 for _,o in subset if o['reason']=='TP')
        print(f"  score [{lo:>2}-{hi}): {len(subset):>4}笔  胜率={w/len(subset)*100:>5.1f}%")


def simulate_trade(sig, future_candles: list) -> dict:
    """向后逐根检查TP/SL是否触及"""
    for k in future_candles:
        hi, lo = k["high"], k["low"]
        if sig.direction == "BUY":
            if lo <= sig.stop_loss:
                return {"reason": "SL", "exit_price": sig.stop_loss,
                        "pnl": (sig.stop_loss - sig.entry_price) * (config.ORDER_USDT / sig.entry_price)}
            if hi >= sig.take_profit:
                return {"reason": "TP", "exit_price": sig.take_profit,
                        "pnl": (sig.take_profit - sig.entry_price) * (config.ORDER_USDT / sig.entry_price)}
        else:
            if hi >= sig.stop_loss:
                return {"reason": "SL", "exit_price": sig.stop_loss,
                        "pnl": (sig.entry_price - sig.stop_loss) * (config.ORDER_USDT / sig.entry_price)}
            if lo <= sig.take_profit:
                return {"reason": "TP", "exit_price": sig.take_profit,
                        "pnl": (sig.entry_price - sig.take_profit) * (config.ORDER_USDT / sig.entry_price)}

    # 超时：以最后一根收盘价出场
    ep = future_candles[-1]["close"] if future_candles else sig.entry_price
    if sig.direction == "BUY":
        pnl = (ep - sig.entry_price) * (config.ORDER_USDT / sig.entry_price)
    else:
        pnl = (sig.entry_price - ep) * (config.ORDER_USDT / sig.entry_price)
    return {"reason": "TIMEOUT", "exit_price": ep, "pnl": pnl}


if __name__ == "__main__":
    asyncio.run(run_backtest())
