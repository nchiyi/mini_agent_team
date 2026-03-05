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
echo "正在啟動免干擾認證模式..."

cat << 'EOF' > /tmp/gemini_auth.py
import pty, os, sys, select, re, time

def main():
    master, slave = pty.openpty()
    pid = os.fork()
    if pid == 0:
        os.close(master)
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.close(slave)
        # 欺騙終端機寬度，防止它自己換行切斷網址
        os.system("stty cols 1000")
        os.execlp("gemini", "gemini", "login")

    os.close(slave)
    output = ""
    url_found = False
    
    try:
        while True:
            r, _, _ = select.select([master], [], [], 0.5)
            if master in r:
                data = os.read(master, 1024)
                if not data: break
                
                # Decode and clean
                text = data.decode('utf-8', 'ignore')
                output += text
                
                if not url_found and "Enter the authorization code:" in output:
                    url_found = True
                    
                    # 強制清除 TUI 的游標控制碼與斷行
                    clean = re.sub(r'\x1b\[.*?m', '', output)
                    clean = re.sub(r'\x1b\[.*?H', '', clean)
                    clean = re.sub(r'\x1b\[.*?J', '', clean)
                    clean = clean.replace('\r', '').replace('\n', '')
                    
                    m = re.search(r'(https://accounts\.google\.com/o/oauth2/v2/auth\?[^\s\x1b]+)', clean)
                    if m:
                        url = m.group(1)
                        # 🔥 終極殺招：強制修補網址錯誤，確保不管怎樣 h 都在
                        url = url.replace('/aut/cloud', '/auth/cloud')
                        
                        print("\n" + "="*80)
                        print("💎 請完整複製以下網址，到瀏覽器打開並授權：\n")
                        print(url)
                        print("\n" + "="*80 + "\n")
                        
                        # 避免環境的 Bracketed Paste Mode 干擾，用標準 input 單獨讀取
                        try:
                            code = input("📥 請貼上您的 Authorization code: ").strip()
                            os.write(master, (code + "\n").encode('utf-8'))
                            print("\n⏳ 驗證中，請稍候...")
                        except EOFError:
                            print("輸入中斷。")
                            sys.exit(1)
                            
                        # 把剩下的結果讀完
                        time.sleep(1)
                        while True:
                            r2, _, _ = select.select([master], [], [], 1.0)
                            if master in r2:
                                data2 = os.read(master, 1024)
                                if not data2: break
                            else:
                                break
                        print("✅ Gemini 登入完成。")
                        break
            else:
                if url_found: break
    except OSError:
        pass
    finally:
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass

if __name__ == "__main__":
    main()
EOF

python3 /tmp/gemini_auth.py
rm -f /tmp/gemini_auth.py
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
