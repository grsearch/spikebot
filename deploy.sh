#!/bin/bash
# ============================================================
# CTSI Spike Bot - 腾讯云东京 部署脚本
# ============================================================

# 1. 安装依赖
cd ~/ctsi_bot
pip install -r requirements.txt

# 2. 填写 API Key（编辑 config.py）
# API_KEY    = "你的key"
# API_SECRET = "你的secret"

# 3. 先跑回测，验证策略参数
python backtest.py

# 4. 空跑测试（不下单）
python main.py --dry-run

# 5. 正式启动（后台运行）
nohup python main.py > logs/stdout.log 2>&1 &
echo "PID: $!"

# 6. 查看日志
# tail -f logs/bot.log

# 7. Dashboard 访问
# http://YOUR_SERVER_IP:8888
# 记得腾讯云安全组开放 8888 端口

# 停止
# kill $(cat bot.pid)
# 或
# pkill -f "python main.py"
