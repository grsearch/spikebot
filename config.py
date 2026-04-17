"""
Spike Arbitrage Bot - 配置文件
所有参数均可通过 Dashboard 热更新，无需重启
"""

# ── Binance API (USD-M Futures 合约) ─────────────────────────
API_KEY     = "YOUR_API_KEY"
API_SECRET  = "YOUR_API_SECRET"
BASE_URL    = "https://fapi.binance.com"   # 合约API端点

# ── 合约设置 ─────────────────────────────────────────────────
LEVERAGE    = 5       # 杠杆倍数（1~125，建议 3~10）
                      # 5x 意味着：100U 保证金 = 500U 仓位
                      # TP/SL 是基于"仓位价格变动"，所以实际盈亏 = 保证金 × 杠杆 × 价格变动%
MARGIN_TYPE = "ISOLATED"  # ISOLATED(逐仓) | CROSSED(全仓)
                          # 逐仓：单笔亏完不影响其他仓位（推荐）
                          # 全仓：所有保证金共享（风险大）

# ── 扫描模式 ─────────────────────────────────────────────────
# "single" = 只盯一个币
# "list"   = 手动指定列表
# "auto"   = 每15分钟查涨幅榜自动筛选
SCAN_MODE   = "single"
SYMBOL      = "CTSIUSDT"
BASE_ASSET  = "CTSI"          # 合约里用不上，保留
QUOTE_ASSET = "USDT"          # 保证金资产

SYMBOL_LIST = [
    "CTSIUSDT", "SOLUSDT", "SUIUSDT", "FETUSDT",
    "INJUSDT",  "ARBUSDT", "APEUSDT", "STXUSDT",
]

# auto 模式参数
AUTO_MIN_GAIN_PCT    = 3.0        # 24h振幅绝对值 >= 此值（合约平静行情3-8%很常见）
AUTO_MIN_VOLUME_USDT = 5_000_000  # 24h成交额 >= 此值（500万U）
AUTO_MAX_SYMBOLS     = 10
AUTO_REFRESH_SEC     = 900        # 15分钟重新筛选

# ── 插针检测参数 ──────────────────────────────────────────────
# 数学关系说明：
#   对于下插针K线 body_ratio = 1 - recovery
#   即实体占针比例 和 回归比例 是同一个量的两种表达
#   所以只需控制 recovery 即可（旧版的 SPIKE_RATIO 被移除）
SPIKE_VS_ATR = 2.5    # 针长 / ATR(20) >= 此值（只抓大针，质量优先）
ATR_PERIOD   = 20
MIN_SPIKE_PIPS = 0.00005  # 当前未使用（SPIKE_VS_ATR已足够过滤）
SPIKE_RATIO  = 2.5    # 已弃用（保留供回测兼容）

# ── 入场条件 ──────────────────────────────────────────────────
# 当根1秒K线收盘后判断，下一根K线用市价单入场
# 触发要求：当根K线插针后已部分回归，处于 [MIN_RECOVERY, MAX_RECOVERY] 区间
#
# 为什么需要 MIN_RECOVERY（最小回归）：
#   == 0 时：价格可能还在针尖，还没确认反转，风险大
#   == 0.20：已回升20%，初步确认转折
#
# 为什么需要 MAX_RECOVERY（最大回归）：
#   == 1.0 时：已完全回到针根，没有利润空间了
#   == 0.70：还有30%空间留给止盈
#
MIN_RECOVERY = 0.25   # 入场更早 → R:R更好
MAX_RECOVERY = 0.40   # 最多回归40%，保证R:R>=1.2
                      # 关键推导:
                      #   recovery=25% → R:R≈2.1
                      #   recovery=30% → R:R≈1.7
                      #   recovery=40% → R:R≈1.2 (下限)

# ── 止盈止损（基于针尖计算，不受入场价影响）────────────────────
# BUY  示例：针尖=6.980，针长=0.020
#   tp = 6.980 + 0.020 * 0.75 = 6.995
#   sl = 6.980 - max(0.020*0.10, ATR*0.5)  ← 两者取大，自适应
#
# 风险收益比检查（代码会过滤 R:R < MIN_RR 的信号）：
#   TP距离 = tp - entry
#   SL距离 = entry - sl
#   R:R = TP距离 / SL距离，至少要 >= 1.5
#
TP_RATIO     = 1.3    # 止盈目标（仅在TRAILING未激活时生效，作为兜底）
                      # 1.3=超过针根30%，给TRAILING更多发挥空间
SL_RATIO     = 0.10   # 止损基础比例：针尖 - 针长 × 10%
SL_ATR_MULT  = 0.5    # 止损ATR倍数：针尖 - ATR × 0.5（两者取大）
MIN_RR       = 1.5    # 最低风险收益比（需覆盖手续费）
                        # 胜率50% + R:R=1.5 → 期望值为正
                        # 胜率45% + R:R=2.0 → 勉强覆盖手续费
                        # 胜率40% + R:R=2.5 → 需要非常严格的信号质量

MAX_HOLD_SECONDS = 60  # 超时强制平仓（合约+trailing需要更长时间）

# ── 手续费 ───────────────────────────────────────────────────
FEE_RATE     = 0.0004 # 合约手续费 Taker 0.04%（VIP0），开+平共 0.08%
                      # BNB 抵扣: 0.03%, VIP1后更低

# ── 跟踪止盈 (Trailing Take Profit) — 核心改进 ────────────────
# 问题：原始TP离入场近，一点波动就触发，只赚0.04U
# 方案：价格达到一定盈利后激活"跟踪"模式，让利润继续奔跑
USE_TRAILING_TP    = True
TRAIL_ACTIVATE_PCT = 0.30  # 盈利达到针长30%时激活跟踪（不再用原TP）
TRAIL_RETRACE_PCT  = 0.20  # 从峰值回撤20%针长就平仓锁利

# ── Break-even 保本 ──────────────────────────────────────────
# 达到50%针长盈利时，SL自动上移到入场价+0.05%（至少保本出场）
BE_ACTIVATE_PCT    = 0.50

# ── 市场趋势过滤 ─────────────────────────────────────────────
# 在明显趋势市场中关闭逆势信号
# True: MA20在MA99下方0.3%以上时，只允许SELL信号（不做BUY抄底）
#        MA20在MA99上方0.3%以上时，只允许BUY信号（不做SELL做空）
MARKET_FILTER      = True

# ── 趋势过滤 ──────────────────────────────────────────────────
MA_PERIOD    = 99
TREND_FILTER = False   # True时：MA在价格上方则降低BUY信号评分

# ── 仓位与资金管理 ────────────────────────────────────────────
ORDER_USDT      = 20.0  # 每笔下单金额
MAX_OPEN_ORDERS = 2     # 同时最多持仓笔数

# ── 轮询 ─────────────────────────────────────────────────────
POLL_INTERVAL_MS = 800   # REST轮询间隔（毫秒）
KLINE_LIMIT      = 120   # 每次拉取K线根数

# ── 风险控制 ──────────────────────────────────────────────────
DAILY_LOSS_LIMIT_USDT  = 10.0  # 每日最大亏损，触发熔断
MAX_DRAWDOWN_PCT       = 5.0   # 最大回撤%，触发熔断
MAX_CONSECUTIVE_LOSSES = 5     # 最大连续亏损次数
MAX_DAILY_TRADES       = 200
CIRCUIT_COOLDOWN_SEC   = 3600  # 熔断冷却1小时

# ── 模式 ─────────────────────────────────────────────────────
DRY_RUN = False   # True=空跑模拟 / False=实盘

# ── Web Dashboard ─────────────────────────────────────────────
WEB_HOST = "0.0.0.0"
WEB_PORT = 8888

# ── 日志 ─────────────────────────────────────────────────────
LOG_DIR   = "logs"
LOG_LEVEL = "INFO"
