# mini_agent_team (Project MAGI)

**隨身攜帶的 AI 軟體公司** — 透過 Telegram 與 Discord 連接本機強大 CLI Agent（Claude Code、Gemini CLI 等）。具備「虛擬企業 (Agency)」架構、雙層持久記憶與自動精煉機制。

> English documentation: [README.md](README.md)

---

## 系統架構圖 (Project MAGI)

```mermaid
flowchart TB
    %% 外部平台
    subgraph Clients ["接入終端 (Clients)"]
        TG["📱 <b>Telegram</b>"]
        DC["🎮 <b>Discord</b>"]
    end
    
    subgraph Gateway ["智能中樞 (MAGI Gateway)"]
        direction TB
        Adapter["🔌 <b>多平台適配器</b><br/>(Adapters)"]
        Router["🚦 <b>語義路由 (NLU)</b><br/>(Semantic Router)"]
        Session["⏳ <b>對話 Session</b><br/>(State Manager)"]
    end

    subgraph Agency ["虛擬企業 (Virtual Agency)"]
        direction LR
        Role1["👨‍💻 <b>Code Auditor</b>"]
        Role2["🕵️ <b>Bug Hunter</b>"]
        Role3["🚀 <b>DevOps</b>"]
        Roster{{"📋 <b>Roster DNA庫</b>"}}
    end

    subgraph Memory ["雙層持久記憶 (Memory)"]
        direction LR
        T1[("📝 <b>Tier 1: 永久筆記</b><br/>事實 & 自動摘要")]
        T3[("📚 <b>Tier 3: 歷史存檔</b><br/>SQLite FTS5 檢索")]
        Distill{"♻️ <b>自動精煉</b><br/>(Distillation)"}
    end

    subgraph Execution ["執行矩陣 (Execution Matrix)"]
        direction TB
        Orchestrator{"🎭 <b>協作編排</b><br/>Discuss / Debate / Relay"}
        Runner["🤖 <b>CLI Runners</b><br/>Claude / Gemini / Codex"]
    end

    %% 連接線
    Clients --> Adapter
    Adapter --> Router
    Router --> Session
    Session --> Roster
    Roster --> Orchestrator
    Orchestrator <--> Memory
    Orchestrator --> Runner
    
    T3 -.->|超過閾值| Distill
    Distill -.->|生成摘要| T1

    Runner -- "Streaming" --> Adapter

    %% 樣式美化
    classDef platform fill:#f0f7ff,stroke:#0052cc,color:#0052cc,stroke-width:2px
    classDef magi fill:#fff9f0,stroke:#d4a017,color:#d4a017,stroke-width:2px
    classDef agency fill:#fdf2f2,stroke:#c53030,color:#c53030,stroke-width:2px
    classDef memory fill:#f3faf7,stroke:#2f855a,color:#2f855a,stroke-width:2px
    classDef exec fill:#f9f5ff,stroke:#6b46c1,color:#6b46c1,stroke-width:2px
    
    class Clients,TG,DC platform
    class Gateway,Adapter,Router,Session magi
    class Agency,Role1,Role2,Role3,Roster agency
    class Memory,T1,T3,Distill memory
    class Execution,Orchestrator,Runner exec
```

---

## 核心亮點

### 🏛️ 虛擬企業架構 (Virtual Agency)
不僅是聊天，而是建立一個具備「職位 DNA」的專家團隊。透過 `roster/*.md` 定義角色的使命與規則，系統會根據您的語義輸入（例如：「這段程式碼幫我過一遍」）自動切換到最適合的專家角色（如 `code-auditor`）。

### 🧠 記憶精煉 (Memory Distillation)
解決長對話導致的 Context 爆炸問題。當歷史對話過長時，系統會自動在背景啟動摘要程序，將過往細節壓縮成精煉事實並轉入 Tier 1 永久記憶，確保 AI 永遠記得重要的決策。

### 🎭 多 Agent 協作 (Orchestration)
內建「討論 (Discuss)」、「辯論 (Debate)」與「中繼 (Relay)」模式。您可以讓 Claude 與 Gemini 針對同一個架構問題進行辯論，產出更全面、低偏見的開發建議。

### ⚡ 極致串流體驗 (Streaming)
採用獨家 Streaming Bridge，無論是 CLI 工具產生的即時進度還是長篇代碼生成，都能在手機端即時跳動顯示，無需漫長等待。

---

## 快速開始

### 前置需求
- Python 3.12+
- 已安裝任一 CLI Agent：`claude` (Claude Code) 或 `gemini` (Gemini CLI)。
- Telegram/Discord Bot Token。

### 一鍵式安裝 (推薦)
```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

---

## 指令百科 (Command Encyclopedia)

| 分類 | 指令 | 說明 |
|------|------|------|
| **專家系統** | `/claude`, `/gemini` | 直接呼叫特定 AI Runner |
| | `/use <slug>` | 手動切換至 Roster 中的特定專家角色 |
| **協作模式** | `/discuss <r1,r2> [p]` | 多 Agent 腦力激盪 |
| | `/debate <r1,r2> [p]` | 多 Agent 對比辯論 |
| | `/relay <r1,r2> [p]` | 鏈式流水線處理 |
| **記憶操作** | `/remember <text>` | 存入永久事實 (Tier 1) |
| | `/recall <query>` | 全文搜尋歷史對話 (Tier 3) |
| **系統控制** | `/status`, `/usage` | 查看系統運行狀況與 Token 統計 |
| | `/new` 或 `/reset` | 重置當前 Session 與 Context |
| | `/cancel` | 立即停止目前的 AI 輸出 |
| | `/voice on/off` | 開啟或關閉語音轉文字功能 |

---

## 專案結構 (Directory Blueprint)

```text
mini_agent_team/
├── main.py                # 核心入口 (The Brain)
├── roster/                # 專家角色 DNA 定義庫
├── src/
│   ├── gateway/           # 語義路由與 NLU 核心
│   ├── core/memory/       # 雙層記憶與精煉邏輯
│   ├── agent_team/        # 多 Agent 協作模式實作
│   └── runners/           # CLI Subprocess 非同步監控
├── modules/               # 功能插件 (Web Search, Vision)
└── config/                # 系統配置與部署腳本
```

---

## 安全設計與政策

- **隱私至上**：記憶數據嚴格以 `(user_id, channel)` 進行物理隔離。
- **Fail-Closed**：`ALLOWED_USER_IDS` 為空時系統自動鎖定，防止未授權存取。
- **使用規範**：本平台僅限作為個人帳號之遠端控制工具。嚴禁將受版權保護的 CLI 工具（如 Claude Code）提供給多用戶代理使用。

---

## License

MIT License
