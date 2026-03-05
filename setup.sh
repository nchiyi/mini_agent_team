#!/bin/bash
# Interactive setup script for Telegram AI Agent Platform on Ubuntu 24.04

echo "=========================================================="
echo "🤖 Telegram AI Agent Platform - Installation & Setup"
echo "=========================================================="
echo ""

# 1. System Requirements
echo "[1/6] 檢查系統環境與安裝依賴..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl
# Install Node.js 20.x (required by Gemini CLI)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
echo "✅ 系統環境準備完成。"
echo ""

# 2. Install Gemini CLI
echo "[2/6] 安裝 Gemini CLI..."
sudo npm install -g @google/gemini-cli
echo "✅ Gemini CLI 安裝完成。"
echo ""

# 3. Gemini CLI Login (Interactive)
echo "[3/6] Gemini CLI 登入"
echo "=========================================================="
echo "⚠️ 警告：請務必【完整複製】整段網址，不要漏掉任何一個字母！"
echo "（先前有漏掉 https://www.googleapis.com/auth 裡的 'h' 導致錯誤的情況）"
echo "=========================================================="
echo "請照著下方的指示登入您的 Google 帳號："
gemini login
echo "✅ 假設 Gemini 登入完成。"
echo ""

# 4. Telegram Bot Token Setup
echo "[4/6] 設定 Telegram Bot"
read -p "請輸入您的 Telegram Bot Token (從 @BotFather 取得): " BOT_TOKEN
read -p "請輸入您的 Telegram User ID (留空表示允許所有人使用): " ALLOWED_IDS

echo "正在建立 .env 設定檔..."
cat <<EOF > .env
# telegram-to-control
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
ALLOWED_USER_IDS=$ALLOWED_IDS
DEFAULT_CWD=$HOME
EOF
echo "✅ .env 檔建立完成。"
echo ""

# 5. Python Environment
echo "[5/6] 設定 Python 虛擬環境與安裝套件..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "✅ Python 套件安裝完成。"
echo ""

# 6. Systemd Service Setup
echo "[6/6] 設定 Systemd 背景服務..."
SERVICE_FILE="/etc/systemd/system/telegram-agent.service"
CURRENT_DIR=$(pwd)
CURRENT_USER=$USER

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Telegram AI Agent Platform
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python3 bot.py
Restart=always
RestartSec=5
# Ensure environment variables like PATH are passed correctly for node/npm
Environment=\"PATH=$CURRENT_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\"

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable telegram-agent
sudo systemctl start telegram-agent

echo "✅ Systemd 服務啟動完成！"
echo ""
echo "=========================================================="
echo "🎉 安裝完成！您的 Telegram AI Agent 已在背景執行。"
echo "👉 檢查狀態指令: sudo systemctl status telegram-agent"
echo "👉 查看日誌指令: journalctl -u telegram-agent -f"
echo "=========================================================="
