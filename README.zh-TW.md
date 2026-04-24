# mini_agent_team (Project MAGI)

**隨身攜帶的 AI 軟體公司** — 透過 Telegram 與 Discord 連接本地端強大 CLI Agent（Claude Code, Gemini CLI, Codex 等）。具備「虛擬企業 (Agency)」架構、雙層持久記憶與自動精煉機制。

> English documentation: [README.md](README.md)

---

## 系統架構圖 (Project MAGI)

```mermaid
flowchart TB
    subgraph Clients ["接入終端 (Input Channels)"]
        TG["📱 Telegram (Bot API)"]
        DC["🎮 Discord (discord.py)"]
    end
    
    subgraph Gateway ["智能中樞 (MAGI Gateway)"]
        direction TB
        Adapter["🔌 多平台適配器 (BaseAdapter)"]
        Router["🚦 語義路由與 NLU (RoleRouter)"]
        Session["⏳ 對話 Session 管理 (SessionManager)"]
        Bridge["⚡ 串流橋接 (StreamingBridge)"]
    end

    subgraph Agency ["虛擬企業 (Virtual Agency)"]
        direction LR
        Roster{{"📋 Roster DNA 庫<br/>(roster/*.md)"}}
        Roles["👨‍💻 Code Auditor<br/>🕵️ Bug Hunter<br/>🚀 DevOps"]
    end

    subgraph Memory ["雙層記憶系統 (Memory Tier)"]
        direction LR
        T1[("📝 Tier 1: 永久筆記<br/>JSONL (Facts/Summaries)")]
        T3[("📚 Tier 3: 歷史存檔<br/>SQLite FTS5 (History)")]
        Distill{"♻️ 自動精煉<br/>(Distillation)"}
    end

    subgraph Runners ["執行陣列 (Execution Matrix)"]
        direction TB
        Orchestrator{"🎭 編排模式<br/>Discuss/Debate/Relay"}
        CR["🤖 CLIRunner (Subprocess)"]
        CL["Claude Code"]
        GM["Gemini CLI"]
        CX["Codex / Custom"]
    end

    %% 連接線
    Clients --> Adapter
    Adapter --> Router
    Router --> Session
    Session --> Roster
    Roster --> Roles
    Roles --> Orchestrator
    
    Orchestrator <--> T1 & T3
    T3 -.->|超過閾值| Distill
    Distill -.->|生成摘要| T1

    Orchestrator --> CR
    CR --> CL & GM & CX
    CR -- "實時串流" --> Bridge
    Bridge --> Adapter

    %% 樣式美化
    classDef platform fill:#f0f7ff,stroke:#0052cc,color:#0052cc
    classDef magi fill:#fff9f0,stroke:#d4a017,color:#d4a017
    classDef agency fill:#fdf2f2,stroke:#c53030,color:#c53030
    classDef memory fill:#f3faf7,stroke:#2f855a,color:#2f855a
    classDef exec fill:#f9f5ff,stroke:#6b46c1,color:#6b46c1
    
    class Clients,TG,DC platform
    class Gateway,Adapter,Router,Session,Bridge magi
    class Agency,Roster,Roles agency
    class Memory,T1,T3,Distill memory
    class Runners,Orchestrator,CR,CL,GM,CX exec
```

---

## 核心亮點

- **多平台同步**：一個後端同時接通 Telegram 與 Discord。
- **虛擬企業架構 (Virtual Agency)**：透過 `roster/*.md` 定義專家職位 DNA，系統根據語義自動切換專家。
- **多 Agent 協作**：支援 Discuss（討論）、Debate（辯論）與 Relay（串聯）模式。
- **自動記憶精煉 (Distillation)**：自動摘要過長對話，解決 Context Window 爆炸問題。
- **即時串流回覆**：採用 Streaming Bridge 技術，回覆邊生成邊更新。
- **雙層儲存架構**：
  - **Tier 1**: 永久事實與自動摘要 (JSONL)。
  - **Tier 3**: 可全文檢索的對話歷史 (SQLite FTS5)。

---

## 快速開始 (Quick Start)

### 前置需求

- **Git**
- **CLI Agents**：至少安裝以下其一：`claude`（Claude Code）、`gemini`（Gemini CLI）或 `codex`。
- **Tokens**：Telegram Bot Token 和/或 Discord Bot Token。
- **Python 3.11+**：執行環境所需。若本機版本較舊，安裝程式會自動提示升級。

### 一鍵安裝

```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

安裝程式會全程自動處理：

1. **Clone**（或更新）專案程式碼
2. **檢查 Python 版本** — 若 < 3.11，提示自動安裝（Ubuntu 使用 deadsnakes PPA，macOS 使用 brew）
3. **建立虛擬環境**並安裝所有套件
4. **啟動設定精靈**（8 個引導步驟）：
   - 選擇接入頻道（Telegram / Discord / 兩者）
   - 輸入並驗證 Bot Token
   - 設定授權白名單（自動捕捉你的 Telegram 用戶 ID）
   - 選擇 CLI 工具（claude, codex, gemini, kiro）
   - 選擇搜尋模式（FTS5 關鍵字 或 FTS5 + 向量嵌入）
   - 更新通知設定
   - 選擇部署方式（前景執行 / systemd / Docker）
   - 寫入設定檔並啟動

精靈完成後 Bot **已在執行中** — 無需任何額外指令。

### 手動安裝

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 -m src.setup.wizard
```

---

## Bot 管理指令

### 前景模式 (Foreground)
Bot 直接在終端機中運行，按 `Ctrl-C` 停止。

### Systemd 模式
```bash
systemctl --user status  gateway-agent   # 查看狀態
systemctl --user stop    gateway-agent   # 停止
systemctl --user restart gateway-agent   # 重啟
journalctl --user -u gateway-agent -f    # 即時日誌
```

### Docker 模式
```bash
docker compose ps        # 查看狀態
docker compose logs -f   # 即時日誌
docker compose down      # 停止
```

---

## 移除安裝 (Uninstall)

```bash
bash ~/mini_agent_team/uninstall.sh
```

移除程式將會：
- 停止並移除 systemd 服務（如有設定）
- 停止 Docker 容器（如有執行）
- 詢問是否**保留或刪除**對話資料（保留時自動備份）
- 刪除整個專案目錄

---

## 設定說明 (Configuration)

### `secrets/.env`
```env
TELEGRAM_BOT_TOKEN=你的Token
DISCORD_BOT_TOKEN=你的Token   # 選填
ALLOWED_USER_IDS=123456789,987654321  # 必填，空白則鎖定所有人
```

### `config/config.toml` 重要參數
```toml
[gateway]
default_runner = "claude"          # 預設使用的 AI Agent
session_idle_minutes = 60          # 閒置幾分鐘後重置 session
stream_edit_interval_seconds = 1.5 # 串流更新間隔（秒）

[runners.claude]
path = "claude"
args = ["--dangerously-skip-permissions"]
timeout_seconds = 300
context_token_budget = 4000        # 注入 context 的 token 上限

[runners.codex]
path = "codex"
args = ["exec", "--full-auto", "--skip-git-repo-check"]
timeout_seconds = 300
context_token_budget = 4000

[runners.gemini]
path = "gemini"
args = ["--approval-mode", "yolo"]
timeout_seconds = 300
context_token_budget = 4000

[memory]
db_path = "data/db/history.db"
distill_trigger_turns = 20  # 超過 N 輪自動啟動精煉
```

---

## 指令百科 (Commands)

| 分類 | 指令 | 說明 |
|------|------|------|
| **切換** | `/claude`, `/gemini` | 切換當前 AI Runner |
| | `/use <role>` | 切換至特定專家角色 (Roster) |
| **協作** | `/discuss <r1,r2> [p]` | 多 Agent 腦力激盪 |
| | `/debate <r1,r2> [p]` | 多 Agent 對比辯論 |
| **記憶** | `/remember <text>` | 存入永久事實 (Tier 1) |
| | `/recall <query>` | 全文搜尋歷史對話 (Tier 3) |
| **系統** | `/status`, `/usage` | 查看系統狀態與 Token 統計 |
| | `/new`, `/cancel` | 重置 Session 或中斷輸出 |

---

## 專案結構 (Structure)

```text
mini_agent_team/
├── main.py                # 核心入口 (The Brain)
├── install.sh             # 一鍵安裝腳本
├── uninstall.sh           # 完整移除腳本
├── roster/                # 專家角色 DNA 定義庫 (.md)
├── src/
│   ├── channels/          # TG/DC 適配器實作
│   ├── gateway/           # 語義路由、Session 與串流管理
│   ├── core/
│   │   └── memory/        # 雙層記憶 (Tier 1/3) 與精煉邏輯
│   ├── runners/           # CLI Subprocess 執行封裝
│   ├── setup/             # 設定精靈與部署輔助工具
│   └── agent_team/        # 多 Agent 協作模式邏輯
├── modules/               # 擴充外掛 (Web Search, Vision)
├── data/                  # 執行時數據 (Database, Logs)
└── config/                # 設定檔
```

---

## 安全設計

- **隱私隔離**：記憶以 `(user_id, channel)` 嚴格隔離，防止數據洩漏。
- **權限白名單**：`ALLOWED_USER_IDS` 為強制性設定，預設 fail-closed。
- **使用規範**：本工具僅限作為個人帳號之遠端控制工具。嚴禁將個人授權之 CLI Agent 提供給多人代理使用。

---

## License
MIT License
