# 🤖 Telegram-to-Control

透過 Telegram 遠端操控電腦上的 AI Coding Agent（Gemini CLI / Claude Code CLI）。

> 在任何地方用手機發 Telegram 訊息，就能讓電腦上的 AI agent 幫你寫 code、改 bug、分析專案。

---

## ✨ 功能

- 🤖 **多 Agent 支援** — Gemini CLI 和 Claude Code CLI 即時切換
- 🔒 **白名單驗證** — 只有授權的 Telegram User ID 能使用
- 📂 **工作目錄切換** — 指定 Agent 在哪個專案目錄下執行
- 📨 **自動分段** — 超長回覆自動分段發送
- ⏱️ **超時保護** — 預設 5 分鐘超時自動中止

## 📋 前置需求

| 項目 | 說明 |
|------|------|
| **Python** | 3.10+ |
| **Telegram Bot** | 從 [@BotFather](https://t.me/BotFather) 建立 |
| **AI CLI** | 至少安裝一個：Gemini CLI 或 Claude Code CLI |

### 安裝 AI CLI

```bash
# Gemini CLI
npm install -g @anthropic-ai/gemini-cli

# Claude Code CLI
npm install -g @anthropic-ai/claude-code
```

## 🚀 快速開始

```bash
# 1. Clone
git clone git@github.com:nchiyi/telegram-to-control.git
cd telegram-to-control

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定
cp .env.example .env
# 編輯 .env，填入你的 Bot Token 和 User ID

# 4. 啟動
python bot.py
```

## 📱 使用方式

在 Telegram 中：

| 指令 | 說明 |
|------|------|
| `/start` | 顯示歡迎訊息 |
| `/agent gemini\|claude` | 切換 AI Agent |
| `/cwd <路徑>` | 切換工作目錄 |
| `/status` | 查看目前設定 |
| `/agents` | 列出可用 Agent |
| 直接發文字 | 送給 Agent 執行 |

## 📂 專案結構

```
telegram-to-control/
├── bot.py                    # Telegram Bot 主程式
├── config.py                 # 設定管理
├── agents/
│   ├── __init__.py           # Agent 註冊
│   ├── base.py               # 基底類別
│   ├── gemini_agent.py       # Gemini CLI 串接
│   └── claude_agent.py       # Claude Code CLI 串接
├── requirements.txt
├── .env.example
└── .gitignore
```

## 📄 License

MIT
