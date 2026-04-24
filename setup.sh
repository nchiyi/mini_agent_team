#!/bin/bash
# Interactive setup script for Telegram AI Agent Platform on Ubuntu 24.04

echo "=========================================================="
echo "🤖 Telegram AI Agent Platform - Installation & Setup"
echo "=========================================================="
echo ""

if [ "$EUID" -eq 0 ]; then
    echo "❌ 錯誤：請不要使用 sudo 執行此腳本！"
    echo "💡 正確用法：請直接執行 ./setup.sh (安裝過程中若需權限會自動提示密碼)"
    echo "⚠️ 使用 sudo 會導致 Systemd 用戶服務 (User Service) 無法正確綁定到你的帳號。"
    exit 1
fi


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
mkdir -p secrets
# 讀取現有的 secrets/.env
if [ -f secrets/.env ]; then
    source secrets/.env 2>/dev/null
    echo "💡 偵測到現有的 secrets/.env 設定。"
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

echo "正在更新 secrets/.env 設定檔..."
cat <<EOF > secrets/.env
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
ALLOWED_USER_IDS=$ALLOWED_IDS
DEFAULT_CWD=${DEFAULT_CWD:-$HOME}
DEBUG_LOG=${DEBUG_LOG:-false}
EOF
chmod 600 secrets/.env
echo "✅ secrets/.env 檔更新完成。"
echo ""

# 4. Optional Search API (Tavily)
echo "[選擇性安裝] 設定進階搜尋引擎 (Tavily API)"
if [ -n "$TAVILY_API_KEY" ]; then
    CURRENT_TAVILY="已設定"
else
    CURRENT_TAVILY="無"
fi
read -p "請輸入 Tavily API Key (選填，若無請直接按 Enter 使用內建搜尋) [目前: $CURRENT_TAVILY]: " NEW_TAVILY_KEY
TAVILY_KEY=${NEW_TAVILY_KEY:-$TAVILY_API_KEY}

if [ -n "$TAVILY_KEY" ]; then
    echo "TAVILY_API_KEY=$TAVILY_KEY" >> secrets/.env
    echo "✅ 已啟用 Tavily 進階搜尋引擎。"
else
    echo "ℹ️ 未設定 Tavily API Key，將使用內建的 DuckDuckGo 綜合搜尋。"
fi
echo ""

# 4. Optional Skills Setup
echo "[4/4] 選擇性安裝進階模組"
echo ""

if [ -d "$HOME/.cache/ms-playwright" ] && ls -1d "$HOME/.cache/ms-playwright/chromium-"* >/dev/null 2>&1; then
    echo "✅ 偵測到已安裝 Browser Eye 核心組件 (Chromium)，跳過安裝。"
else
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
fi

# 5.2 Optional: Semantic Memory (Phase 3 - Intelligence Upgrade)
echo ""
# Since dependencies are in requirements.txt, we already have them.
# We can just inform the user instead of prompting.
echo "✅ 語義記憶組件已就緒 (套件已隨 requirements.txt 安裝)。"


echo "✅ Python 套件處理完成。"
echo ""

# 6. Systemd User Service Setup
echo "[6/6] 設定 Systemd 用戶服務與管理工具..."
chmod +x agent

# Migration: stop old user-level telegram-agent service if it exists
if systemctl --user is-active --quiet telegram-agent 2>/dev/null; then
    echo "⚠️ 偵測到舊版 telegram-agent 服務，正在遷移至 gateway-agent..."
    systemctl --user stop telegram-agent
    systemctl --user disable telegram-agent
    rm -f "$HOME/.config/systemd/user/telegram-agent.service"
    systemctl --user daemon-reload
fi

# Migration: stop old system-level service if it exists (requires sudo once)
if systemctl is-active --quiet telegram-agent 2>/dev/null; then
    echo "⚠️ 偵測到舊版系統服務，正在移除..."
    sudo systemctl stop telegram-agent
    sudo systemctl disable telegram-agent
    sudo rm -f /etc/systemd/system/telegram-agent.service
    sudo systemctl daemon-reload
fi

SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
SERVICE_FILE="$SERVICE_DIR/gateway-agent.service"
CURRENT_DIR=$(pwd)

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Gateway Agent Platform
After=network.target

[Service]
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python3 main.py
Restart=always
RestartSec=5
Environment="PATH=$CURRENT_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=default.target
EOF

# Use systemctl --user
systemctl --user daemon-reload
systemctl --user enable gateway-agent
systemctl --user start gateway-agent

# Enable linger so services run when user is logged out
echo "🔓 啟用 Linger 模式 (確保登出後 Bot 持續執行)..."
sudo loginctl enable-linger $USER

echo "✅ Systemd 用戶服務啟動完成！"
echo ""
echo "=========================================================="
echo "🎉 安裝完成！您的 Gateway Agent 已在背景執行。"
echo ""
echo "🚀 簡易管理指令 (在專案目錄下執行):"
echo "👉 ./agent status  - 檢查執行狀態"
echo "👉 ./agent logs    - 查看即時日誌"
echo "👉 ./agent restart - 重啟服務"
echo "👉 ./agent debug on/off - 切換詳細日誌模式"
echo ""
echo "💡 提示：若想在任何地方都能使用，請執行: sudo ln -s \$(pwd)/agent /usr/local/bin/agent"
echo "=========================================================="
