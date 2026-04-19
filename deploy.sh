#!/bin/bash
# ============================================================
# Spike Bot — 一键部署脚本
# 适用于：Ubuntu 20.04/22.04，Python 3.10+
# Dashboard 通过 localtunnel 生成公网 HTTPS 链接
# ============================================================

set -e
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BOT_DIR"

echo "========================================================"
echo " Spike Bot 部署脚本"
echo "========================================================"

# ── 1. 检查 Python ────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装：sudo apt install python3 python3-pip"
    exit 1
fi
PY=$(python3 --version 2>&1)
echo "[OK] $PY"

# ── 2. 安装 Python 依赖 ───────────────────────────────────────
echo "[*] 安装 Python 依赖..."
pip3 install -r requirements.txt -q

# ── 3. 检查 Node.js / localtunnel ────────────────────────────
echo "[*] 检查 localtunnel..."
if ! command -v node &>/dev/null; then
    echo "[*] Node.js 未安装，正在安装..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null
    sudo apt-get install -y nodejs 2>/dev/null
fi
if ! command -v lt &>/dev/null; then
    echo "[*] 安装 localtunnel..."
    sudo npm install -g localtunnel -q
fi
echo "[OK] localtunnel 已就绪"

# ── 4. 检查 config.py ────────────────────────────────────────
if grep -q "YOUR_API_KEY" config.py; then
    echo ""
    echo "[!] 请先填写 config.py 里的 API_KEY 和 API_SECRET，然后重新运行此脚本。"
    echo "    nano config.py"
    echo ""
    exit 1
fi

# ── 5. 创建日志目录 ───────────────────────────────────────────
mkdir -p logs

# ── 6. 停止旧进程（如有）────────────────────────────────────
if [ -f bot.pid ]; then
    OLD_PID=$(cat bot.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[*] 停止旧 bot 进程 PID=$OLD_PID..."
        kill "$OLD_PID" && sleep 1
    fi
    rm -f bot.pid
fi
if [ -f tunnel.pid ]; then
    OLD_TUN=$(cat tunnel.pid)
    if kill -0 "$OLD_TUN" 2>/dev/null; then
        kill "$OLD_TUN" 2>/dev/null || true
    fi
    rm -f tunnel.pid
fi

# ── 7. 启动 Bot（后台）────────────────────────────────────────
echo "[*] 启动 Bot..."
nohup python3 main.py > logs/stdout.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > bot.pid
echo "[OK] Bot 已启动，PID=$BOT_PID"

# ── 8. 等待 Dashboard 端口就绪 ───────────────────────────────
WEB_PORT=$(python3 -c "import config; print(config.WEB_PORT)" 2>/dev/null || echo "8888")
echo "[*] 等待 Dashboard 启动（端口 $WEB_PORT）..."
for i in $(seq 1 20); do
    if curl -s "http://127.0.0.1:$WEB_PORT" >/dev/null 2>&1; then
        echo "[OK] Dashboard 已就绪"
        break
    fi
    sleep 1
    if [ $i -eq 20 ]; then
        echo "[WARN] Dashboard 超时，请检查 logs/stdout.log"
    fi
done

# ── 9. 启动 localtunnel ───────────────────────────────────────
echo "[*] 启动 localtunnel（端口 $WEB_PORT）..."
nohup lt --port "$WEB_PORT" > logs/tunnel.log 2>&1 &
TUNNEL_PID=$!
echo $TUNNEL_PID > tunnel.pid

# 等待 localtunnel 输出链接
sleep 3
TUNNEL_URL=""
for i in $(seq 1 10); do
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.loca\.lt' logs/tunnel.log 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

echo ""
echo "========================================================"
echo " ✅  Bot 已启动！"
echo ""
if [ -n "$TUNNEL_URL" ]; then
    echo "  🌐  Dashboard 公网地址: $TUNNEL_URL"
    echo "      (localtunnel 首次访问需点击「Click to Continue」)"
else
    echo "  🌐  Dashboard 本地地址: http://127.0.0.1:$WEB_PORT"
    echo "      (localtunnel 链接获取失败，查看 logs/tunnel.log)"
fi
echo ""
echo "  📋  查看日志: tail -f logs/bot.log"
echo "  🔗  查看隧道: cat logs/tunnel.log"
echo "  🛑  停止 Bot:  kill \$(cat bot.pid)"
echo "========================================================"
