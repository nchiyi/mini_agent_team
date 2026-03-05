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
echo "準備取得授權網址，請稍候..."

python3 -c "
import subprocess, re, sys

p = subprocess.Popen(['gemini', 'login'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
output = ''
url_found = False

while True:
    char = p.stdout.read(1)
    if not char: break
    output += char
    
    if not url_found and 'Enter the authorization code:' in output:
        url_match = re.search(r'(https://accounts.google.com[^\s\x1b]+)', output)
        if url_match:
            print('\n' + '='*80)
            print('💎 請完整複製以下網址，到瀏覽器打開並授權：\n')
            print(url_match.group(1))
            print('\n' + '='*80 + '\n')
            url_found = True
            
            # 提示使用者輸入
            code = input('請貼上您獲得的 Authorization code: ')
            p.stdin.write(code + '\n')
            p.stdin.flush()
            
            # 讀取剩餘輸出
            print('\n⏳ 驗證中...')
            remainder = p.stdout.read()
            if 'Successfully logged in' in remainder or 'Welcome' in remainder or 'Token' in remainder or not 'Error' in remainder:
                print('✅ 驗證完成！')
            else:
                print(remainder)
            break

p.wait()
"
echo "✅ Gemini 登入流程結束。"
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
