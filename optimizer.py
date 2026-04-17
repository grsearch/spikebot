"""
参数优化器 - 网格搜索最优策略参数
python optimizer.py

耗时较长，建议先用 backtest.py 确认策略可行再跑优化
"""
import asyncio
import copy
import sys
import os
import itertools
sys.path.insert(0, os.path.dirname(__file__))

import config
from core.exchange import BinanceREST
from strategy.detector import SpikeDetector, Candle


# ── 搜索空间定义 ──────────────────────────────────────────────
PARAM_GRID = {
    "SPIKE_RATIO":    [2.5, 3.0, 3.5, 4.0],
    "SPIKE_VS_ATR":   [2.0, 2.5, 3.0],
    "RECOVERY_RATIO": [0.40, 0.50, 0.60],
    "TP_RATIO":       [0.60, 0.70, 0.80],
    "SL_RATIO":       [0.08, 0.10, 0.15],
    "MAX_HOLD_SECONDS": [20, 30, 45],
}

# 优化目标：可选 "win_rate" | "sharpe" | "expectancy"
OPTIMIZE_FOR = "expectancy"

# 最小样本量（少于此数量的参数组合不算）
MIN_SAMPLES = 10


class FakeConfig:
    """可动态修改参数的配置对象"""
    def __init__(self, base_cfg):
        for k in dir(base_cfg):
            if not k.startswith("_"):
                setattr(self, k, getattr(base_cfg, k))


def simulate_trade(sig, future_candles, cfg) -> dict:
    for k in future_candles:
        hi, lo = k["high"], k["low"]
        if sig.direction == "BUY":
            if lo <= sig.stop_loss:
                return {"reason": "SL", "pnl": sig.stop_loss - sig.entry_price}
            if hi >= sig.take_profit:
                return {"reason": "TP", "pnl": sig.take_profit - sig.entry_price}
        else:
            if hi >= sig.stop_loss:
                return {"reason": "SL", "pnl": sig.entry_price - sig.stop_loss}
            if lo <= sig.take_profit:
                return {"reason": "TP", "pnl": sig.entry_price - sig.take_profit}

    ep = future_candles[-1]["close"] if future_candles else sig.entry_price
    pnl = (ep - sig.entry_price) if sig.direction == "BUY" else (sig.entry_price - ep)
    return {"reason": "TIMEOUT", "pnl": pnl}


def evaluate_params(klines: list, cfg: FakeConfig) -> dict:
    det = SpikeDetector(cfg)
    results = []

    for i in range(cfg.ATR_PERIOD + 1, len(klines)):
        window = klines[max(0, i - 200):i]
        det.update(window)
        k = klines[i]
        candle = Candle(
            open_time=k["open_time"],
            open=k["open"], high=k["high"],
            low=k["low"],   close=k["close"],
            volume=k["volume"],
        )
        sig = det.detect(candle)
        if sig:
            future = klines[i + 1: i + 1 + cfg.MAX_HOLD_SECONDS]
            out = simulate_trade(sig, future, cfg)
            results.append(out)

    if len(results) < MIN_SAMPLES:
        return None

    wins = sum(1 for r in results if r["reason"] == "TP")
    pnls = [r["pnl"] for r in results]
    total_pnl = sum(pnls)
    win_rate  = wins / len(results)
    avg_win   = sum(p for p in pnls if p > 0) / max(wins, 1)
    avg_loss  = abs(sum(p for p in pnls if p < 0)) / max(len(results) - wins, 1)
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    # Sharpe（简化版，无无风险利率）
    import statistics
    std = statistics.stdev(pnls) if len(pnls) > 1 else 1e-9
    sharpe = (sum(pnls) / len(pnls)) / std if std > 0 else 0

    return {
        "n":          len(results),
        "win_rate":   round(win_rate * 100, 1),
        "total_pnl":  round(total_pnl, 5),
        "expectancy": round(expectancy, 6),
        "sharpe":     round(sharpe, 3),
        "avg_win":    round(avg_win, 6),
        "avg_loss":   round(avg_loss, 6),
    }


async def fetch_klines(days=2) -> list:
    ex = BinanceREST(config.API_KEY, config.API_SECRET, config.BASE_URL)
    print(f"拉取 {days} 天历史K线...")
    all_klines = []
    end_time = None
    for i in range(days * 24 * 3600 // 1000 + 1):
        params = {"symbol": config.SYMBOL, "interval": "1s", "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        try:
            batch = await ex.get_klines(config.SYMBOL, "1s", 1000)
            if not batch:
                break
            all_klines = batch + all_klines
            end_time = batch[0]["open_time"] - 1
            if i % 10 == 0:
                print(f"  已拉取 {len(all_klines)} 根...")
        except Exception as e:
            print(f"  拉取失败: {e}")
            break
        await asyncio.sleep(0.2)
    await ex.close()
    print(f"共获取 {len(all_klines)} 根1秒K线\n")
    return all_klines


async def run_optimizer():
    klines = await fetch_klines(days=2)
    if not klines:
        print("无数据，退出")
        return

    # 生成参数组合
    keys   = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = list(itertools.product(*values))
    total  = len(combos)
    print(f"开始网格搜索：{total} 种参数组合...\n")

    best_score = -999
    best_params = None
    best_metrics = None
    all_results = []

    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        cfg = FakeConfig(config)
        for k, v in params.items():
            setattr(cfg, k, v)

        metrics = evaluate_params(klines, cfg)
        if metrics is None:
            continue

        score = metrics[OPTIMIZE_FOR]
        all_results.append((score, params, metrics))

        if score > best_score:
            best_score  = score
            best_params = params
            best_metrics = metrics

        if (idx + 1) % 20 == 0:
            print(f"进度: {idx+1}/{total} | 当前最优 {OPTIMIZE_FOR}={best_score:.4f}")

    # 排序输出 Top 10
    all_results.sort(key=lambda x: x[0], reverse=True)
    print(f"\n{'='*70}")
    print(f"Top 10 参数组合（按 {OPTIMIZE_FOR} 排序）")
    print(f"{'='*70}")

    header = f"{'rank':<5} {'n':<5} {'wr%':<7} {'expect':<10} {'sharpe':<8} {'pnl':<10} | 参数"
    print(header)
    print("-" * 70)

    for rank, (score, params, m) in enumerate(all_results[:10], 1):
        param_str = " ".join(f"{k.replace('_',''[:3])}={v}" for k, v in params.items())
        print(
            f"{rank:<5} {m['n']:<5} {m['win_rate']:<7} "
            f"{m['expectancy']:<10.5f} {m['sharpe']:<8.3f} "
            f"{m['total_pnl']:<10.4f} | {param_str}"
        )

    print(f"\n{'='*70}")
    print("最优参数（直接复制到 config.py）:")
    print(f"{'='*70}")
    for k, v in best_params.items():
        print(f"{k:<25} = {v}")
    print(f"\n对应指标: {best_metrics}")


if __name__ == "__main__":
    asyncio.run(run_optimizer())
