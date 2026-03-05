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

# 3. Gemini CLI Login (Check and Login)
echo "[3/6] Gemini CLI 認證檢查..."
# 檢查是否已經登入 (透過 gemini --list-sessions 測試)
if gemini --list-sessions 2>/dev/null | grep -q "Session"; then
    echo "✅ 偵測到已登入的 Gemini 帳號，跳過登入步驟。"
else
    echo "=========================================================="
    echo "🚀 正在啟動「遠端穩定認證模式」..."
    echo "💡 提示："
    echo "   1. 終端機會顯示一段長網址，請【完整複製】並在瀏覽器中開啟。"
    echo "   2. 授權後，Google 會給你一串「Authorization code」，請複製它。"
    echo "   3. 回到終端機，貼上程式碼並按 Enter。"
    echo "=========================================================="
    echo ""
    sleep 1
    # 使用 TERM=dumb 強制進入 OOB 模式，並在登入後嘗試退出 shell (如果有的話)
    TERM=dumb gemini login
    echo "✅ Gemini 登錄流程已觸發。"
fi
echo ""

# 4. Telegram Bot Token Setup
echo "[4/6] 設定 Telegram Bot"
# 讀取現有的 .env
if [ -f .env ]; then
    source .env 2>/dev/null
    echo "💡 偵測到現有的 .env 設定。"
fi

# 提示輸入，如果有舊值則顯示為預設
read -p "請輸入 Telegram Bot Token [目前: ${TELEGRAM_BOT_TOKEN:-無}]: " NEW_TOKEN
BOT_TOKEN=${NEW_TOKEN:-$TELEGRAM_BOT_TOKEN}

read -p "請輸入 Telegram User ID [目前: ${ALLOWED_USER_IDS:-允許所有人}]: " NEW_IDS
ALLOWED_IDS=${NEW_IDS:-$ALLOWED_USER_IDS}

# 如果兩者都空白，提示警告
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ 錯誤: 必須提供 Bot Token 才能運作！"
    exit 1
fi

echo "正在更新 .env 設定檔..."
cat <<EOF > .env
# telegram-to-control
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
ALLOWED_USER_IDS=$ALLOWED_IDS
DEFAULT_CWD=${DEFAULT_CWD:-$HOME}
DEBUG_LOG=${DEBUG_LOG:-false}
EOF
echo "✅ .env 檔更新完成。"
echo ""

# 5. Python Environment
echo "[5/6] 設定 Python 虛擬環境與安裝套件..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "✅ Python 套件安裝完成。"
echo ""

# 6. Systemd Service Setup
echo "[6/6] 設定 Systemd 背景服務與管理工具..."
chmod +x agent
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
echo ""
echo "🚀 簡易管理指令 (在專案目錄下執行):"
echo "👉 ./agent status  - 檢查執行狀態"
echo "👉 ./agent logs    - 查看即時日誌"
echo "👉 ./agent restart - 重啟服務"
echo "👉 ./agent debug on/off - 切換詳細日誌模式"
echo ""
echo "💡 提示：若想在任何地方都能使用，請執行: sudo ln -s \$(pwd)/agent /usr/local/bin/agent"
echo "=========================================================="
