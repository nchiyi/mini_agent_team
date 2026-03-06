#!/bin/bash
# Interactive setup script for Telegram AI Agent Platform on Ubuntu 24.04

echo "=========================================================="
echo "🤖 Telegram AI Agent Platform - Installation & Setup"
echo "=========================================================="
echo ""

# 1. System Requirements
echo "[1/4] 檢查系統環境與安裝依賴..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl
echo "✅ 系統環境準備完成。"
echo ""

# 2. Python Environment Setup
echo "[2/4] 設定 Python 虛擬環境與安裝套件..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ 虛擬環境 (venv) 建立完成。"
fi
source venv/bin/activate
pip install -r requirements.txt
echo "✅ Python 相依套件安裝完成。"
echo ""

# 3. Telegram Bot Token Setup
echo "[3/4] 設定 Telegram Bot"
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

# 4. Optional Skills Setup
echo "[4/4] 選擇性安裝進階模組"
echo ""
read -p "是否安裝 「Browser Eye」瀏覽器擴展功能？(可讓 Agent 讀取網頁內容) [y/N]: " INSTALL_BROWSER
if [[ "$INSTALL_BROWSER" =~ ^[Yy]$ ]]; then
    echo "🌐 正在安裝瀏覽器引擎 (Chromium)..."
    python3 -m playwright install chromium
    # Install system deps for playwright using sudo to ensure interactive permission
    sudo python3 -m playwright install-deps chromium
    echo "✅ 瀏覽器擴展安裝完成。"
else
    echo "⏭️ 跳過瀏覽器擴展安裝。"
fi

# 5.2 Optional: Semantic Memory (Phase 3 - Intelligence Upgrade)
echo ""
read -p "是否安裝 「Semantic Memory」語義記憶擴展？(提供語義搜尋與長期記憶，需額外下載 400MB 模型) [y/N]: " INSTALL_SEMANTIC
if [[ "$INSTALL_SEMANTIC" =~ ^[Yy]$ ]]; then
    echo "🧠 正在準備語義記憶引擎..."
    # Dependencies are already in requirements.txt, but we might want to trigger a pre-download
    # or just let it happen on first start.
    echo "✅ 語義記憶組件已就緒。"
else
    echo "⏭️ 跳過語義記憶安裝。"
fi

echo "✅ Python 套件處理完成。"
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
