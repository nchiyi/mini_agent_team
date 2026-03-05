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
echo "正在準備認證流程，這可能需要幾秒鐘..."

python3 -c "
import subprocess, re, sys, time, os

def fix_url(text):
    # 修復可能的網址斷行或字元缺失問題 (特別是 /auth/ 變成 /aut/)
    url_match = re.search(r'(https://accounts\.google\.com/o/oauth2/v2/auth\?[^\s\n\r]+)', text)
    if not url_match:
        # 嘗試找不完全的網址並補上 h
        url_match = re.search(r'(https://accounts\.google\.com/o/oauth2/v2/aut\?[^\s\n\r]+)', text)
        if url_match:
            return url_match.group(1).replace('/aut?', '/auth?')
    return url_match.group(1) if url_match else None

print('正在啟動 gemini login...')
# 使用標準 subprocess 搭配串流讀取
p = subprocess.Popen(['gemini', 'login'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=sys.stdin, text=True, bufsize=1)

output = ''
url_shown = False

# 設置超時，避免無限等待
start_time = time.time()

while p.poll() is None:
    # 讀取一行或部分輸出
    line = p.stdout.readline()
    if not line:
        if time.time() - start_time > 30:
            print('\n操作超時，請嘗試手動執行 gemini login。')
            break
        time.sleep(0.1)
        continue
    
    output += line
    # 我們不隱藏原本的輸出，讓使用者知道進度
    sys.stdout.write(line)
    sys.stdout.flush()
    
    if not url_shown and ('https://' in line or 'authorize' in line.lower()):
        # 嘗試從累積的輸出中提取並修復網址
        url = fix_url(output)
        if url:
            print('\n' + '='*80)
            print('✨ 發現授權網址 (已自動修復可能存在的 h 缺失錯誤)：')
            print('\n' + url)
            print('\n' + '='*80 + '\n')
            url_shown = True

# 讓使用者完成後續手動輸入
p.wait()
" || {
    echo "⚠️ 自動認證助手失敗，改用原始模式..."
    gemini login
}

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
