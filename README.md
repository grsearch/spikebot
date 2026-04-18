# Binance 合约插针套利 Bot - Tick 模式

## 环境要求

- AWS Tokyo / 阿里云香港 (到 Binance 延迟 < 30ms)
- Ubuntu 22.04+ 或 Debian 11+
- Python 3.10+

## 安装

```bash
# 1. 解压
unzip ctsi_bot.zip
cd ctsi_bot

# 2. 装依赖
pip3 install -r requirements.txt

# 3. 填 API Key
nano config.py
#   API_KEY    = "你的合约API Key"
#   API_SECRET = "你的合约API Secret"
#   其他默认值保持不变
```

## API Key 权限要求

在 Binance API 管理页：
- ✓ 启用合约
- ✓ 启用交易
- 不需要提现权限
- 建议绑定服务器 IP

## 合约账户准备

- 主账户划转 100+ USDT 到 U本位合约账户
- 持仓模式：机器人会自动检测并切换为单向

## 启动

### 空跑测试（推荐先跑2小时）
```bash
nohup python3 main.py --dry-run > logs/stdout.log 2>&1 &
```

### 实盘
```bash
nohup python3 main.py --live > logs/stdout.log 2>&1 &
```

### 停止
```bash
pkill -f "python3 main.py"
```

### 重启
```bash
pkill -f "python3 main.py"
sleep 2
nohup python3 main.py --dry-run > logs/stdout.log 2>&1 &
```

## Dashboard 访问（localtunnel 方案）

Dashboard 默认监听 `0.0.0.0:8888`，在 AWS 服务器上需要暴露出来。

**推荐用 localtunnel**（不需要开放安全组端口）：

```bash
# 安装 localtunnel（只装一次）
sudo apt install -y npm
sudo npm install -g localtunnel

# 启动隧道
nohup lt --port 8888 > logs/tunnel.log 2>&1 &

# 查看分配到的URL
cat logs/tunnel.log
# 例如: your url is: https://deep-cars-knock.loca.lt
```

打开URL后第一次会有一个确认页，点 **"Click to Continue"** 进入 Dashboard。

**注意事项：**
- localtunnel URL 是临时的，重启后会变
- 不是 ngrok（别装错）
- 如果URL打不开，可能该 IP 被 localtunnel 临时屏蔽了，可以换一个子域名：`lt --port 8888 --subdomain mybot-xxx`

**另一个方案（开端口）：**
如果想固定URL，可以在 AWS 安全组开放 8888 端口（**只对你的IP开放**），然后直接访问 `http://服务器IP:8888`。

## 关键配置（config.py）

| 参数 | 默认 | 说明 |
|------|------|------|
| `RUN_MODE` | `tick` | tick=WebSocket实时 / kline=REST轮询 |
| `LEVERAGE` | 5 | 杠杆倍数 |
| `ORDER_USDT` | 20 | 每笔保证金金额（实际仓位 = 20×5=100U）|
| `MAX_OPEN_ORDERS` | 2 | 同时最多持仓数 |
| `SCAN_MODE` | auto | 自动扫描涨幅榜 |
| `AUTO_MAX_SYMBOLS` | 6 | 同时监控币种数 |
| `TICK_MAX_HOLD_MS` | 3000 | 持仓最多 3 秒 |
| `TICK_TP_RATIO` | 0.40 | 止盈=针长×40% |
| `TICK_SL_RATIO` | 0.25 | 止损=针尖再下行 25% 针长 |

## 策略概述

**插针套利（tick 版本）：**

1. WebSocket 实时订阅涨幅榜前6币种的 `@aggTrade` 流
2. 滑动窗口（2秒）检测价格异常：针长 > 2.5倍ATR
3. 确认"已反弹10~50%"的时机入场（紧接下单市价单）
4. 最多持仓 3 秒
   - 达到止盈 → 平仓
   - 触及止损 → 平仓
   - 超时 → 平仓

## 自动保护

- **涨幅榜过滤**：只选 `status=TRADING` 的永续合约，自动排除 `SETTLING`（即将下架）币
- **持仓模式**：启动时自动切换为单向模式
- **孤儿持仓监控**：币种被移出涨幅榜后仍会跟进 TP/SL/超时
- **Rate limit 保护**：接近上限时主动延迟

## 风控

- 日亏损限额：10 USDT
- 账户回撤：5%
- 连续亏损：5次
- 熔断后冷却：1小时

## 日志

- `logs/bot.log` — 主日志
- `logs/stdout.log` — 标准输出
- `logs/tunnel.log` — localtunnel 日志
- Dashboard 实时诊断面板

## 常见问题

**Q: 启动报 -4061 错误**
A: 合约是双向持仓模式，代码会自动切换。如失败手动切换：U本位合约 → 偏好设置 → 持仓模式 → 单向

**Q: 报 -2019 Margin is insufficient**
A: 合约钱包 USDT 不足，从主账户划转

**Q: 扫描不到币 / 扫到下架币**
A: 已修复。scanner 现在先拉 exchangeInfo 过滤 status=TRADING

**Q: URL 变成 ffapi.binance.com 报错**
A: 已修复子串替换bug。只有 `://api.binance.com` 才会被替换

**Q: Rate limit**
A: 降低 `AUTO_MAX_SYMBOLS`（config.py）到 4

**Q: WebSocket 断开**
A: 正常，会自动重连（log 里有 "WS连接..." 日志）

## 联系方式

部署或运行问题日志发回来查看。
