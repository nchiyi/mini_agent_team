# mini_agent_team — Project MAGI

**隨身 AI 軟體公司** — 用 Telegram / Discord 跟你本機的 Claude Code、Codex、Gemini CLI 對話。

> 🇬🇧 **English:** see [README.en.md](README.en.md).

---

## 架構總覽

### 訊息流程

```mermaid
flowchart LR
    subgraph Client["📱 終端"]
        TG["Telegram Bot"]
        DC["Discord Bot"]
    end

    subgraph Gateway["🚪 Gateway"]
        ADAPT["Channel Adapter<br/>(權限白名單)"]
        ROUTE["語義路由器<br/>(FastEmbed NLU)"]
        SESS["Session 管理<br/>(idle 60min)"]
        BRIDGE["Streaming Bridge<br/>(0.5s 刷新)"]
    end

    subgraph Memory["🧠 雙層記憶"]
        T1[("Tier 1<br/>永久事實 JSONL")]
        T3[("Tier 3<br/>歷史 SQLite FTS5")]
        DIST["♻️ 自動精煉"]
    end

    subgraph Agency["🎭 虛擬企業"]
        ROSTER["Roster<br/>roster/*.md"]
    end

    subgraph Runners["⚙️ ACP Runners"]
        ACP["JSON-RPC 2.0<br/>over ndjson"]
        CL["claude-code"]
        CX["codex"]
        GM["gemini-cli"]
    end

    TG & DC --> ADAPT --> ROUTE --> SESS
    SESS <--> T1 & T3
    T3 -.-> DIST -.-> T1
    SESS --> ROSTER
    ROSTER --> ACP
    ACP --> CL & CX & GM
    ACP --> BRIDGE --> ADAPT

    classDef c fill:#e3f2fd,stroke:#1976d2,color:#1976d2
    classDef g fill:#fff8e1,stroke:#f57c00,color:#f57c00
    classDef m fill:#e8f5e9,stroke:#388e3c,color:#388e3c
    classDef a fill:#fce4ec,stroke:#c2185b,color:#c2185b
    classDef r fill:#f3e5f5,stroke:#7b1fa2,color:#7b1fa2
    class Client,TG,DC c
    class Gateway,ADAPT,ROUTE,SESS,BRIDGE g
    class Memory,T1,T3,DIST m
    class Agency,ROSTER a
    class Runners,ACP,CL,CX,GM r
```

### 部署模式

| 模式 | 適用場景 | 啟動方式 | CLI 來源 |
|------|---------|----------|---------|
| **foreground** | 開發 / 除錯 | `python3 main.py` | 宿主 PATH |
| **launchd** (macOS) | 桌機常駐 | `~/Library/LaunchAgents/` | 宿主 PATH |
| **systemd** (Linux) | 伺服器常駐 | `systemctl --user` | 宿主 PATH |
| **docker** | 跨機器移植 | `docker compose up` | 容器內預裝 + 掛載宿主 OAuth |

Docker 模式自動：
1. 在 `python:3.11-slim` 容器內裝 Node.js 20 + 你選的 CLI（`@anthropic-ai/claude-code`、`@openai/codex`、`@google/gemini-cli`）
2. 把宿主 `~/.claude`、`~/.codex`、`~/.gemini` 唯讀掛進容器，CLI 直接用你已認證的 OAuth

---

## 核心特色

- **ACP 持久化 Session** — 不再每條訊息 spawn 子程序，回應從 2-4 秒降到毫秒級
- **零 API Key** — claude / codex / gemini 全程走個人訂閱 OAuth
- **多平台同時上線** — 一個後端同時接 Telegram + Discord
- **語義角色路由** — 用 FastEmbed 把訊息匹配到 `roster/*.md` 的專家定義
- **多 Agent 協作** — `/discuss`、`/debate`、`/relay` 三種模式
- **自動記憶精煉** — 對話超過 20 輪自動產生摘要，避免 context 爆炸
- **跨 Linux 發行版** — Ubuntu / Debian / Fedora / RHEL / Arch / Alpine / openSUSE 一鍵安裝
- **Mac 一鍵就緒** — 偵測到沒 Homebrew 自動安裝，再裝 Python 3.11

---

## 快速安裝

### 1. 一鍵安裝（推薦）

```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

安裝程式自動處理：

| 階段 | 動作 |
|------|------|
| 0 | 偵測作業系統 + 發行版（讀 `/etc/os-release`）|
| 1 | macOS 沒 Homebrew 詢問是否自動裝；Linux 用 distro 原生 pkg manager |
| 2 | 裝 Python 3.11+（只在版本不足時觸發）|
| 3 | clone repo + 建 venv + `pip install -r requirements.txt` |
| 4 | 啟動設定精靈（步驟 1-9，方向鍵 + Space + Enter 操作）|
| 5 | 選 docker 模式時自動 build 容器並啟動 |

精靈完成後 bot **已上線**，不需要額外指令。

### 2. 安裝 mat 全域指令（一次就好）

```bash
cd ~/mini_agent_team
sudo ./mat install-cmd
```

之後在任何目錄都能用 `mat ...`。

### 3. 手動安裝

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./venv/bin/python3 setup.py
```

---

## 設定精靈步驟

| Step | 內容 | 互動 |
|------|------|------|
| 0 | Pre-flight：Python / 磁碟 / 網路 / pkg manager / systemd / Docker | 自動 |
| 1 | Channel Selection — 選 Telegram、Discord 或兩者 | ☐ checkbox |
| 2 | Bot Token — 貼上並驗證 | 文字輸入 |
| 3 | Allowlist — 你的 user ID（傳訊息給 bot 自動抓 / Enter 跳過）| 自動 / Enter |
| 4 | CLI Tools — 勾 claude / codex / gemini，未裝的會自動 npm install | ☐ checkbox |
| 4.5 | ACP 協作模式 — orchestrator / multi / both | 單選 |
| 5 | Search Mode — fts5 / fts5+vector | 單選 |
| 6 | Optional Features — Discord 語音 / 瀏覽器技能 / Tavily | ☐ checkbox |
| 7 | Update Notifications — 啟動時檢查新 release | y/n |
| 8 | Deploy Mode — foreground / systemd（Linux）/ docker | 單選 |
| 9 | 寫設定 + 啟動服務 + smoke test | 自動 |

---

## 日常操作

### `mat` 全域指令（推薦）

```bash
mat start          # 背景啟動（依設定的部署模式）
mat stop           # 停止
mat restart        # 重啟
mat status         # 查看執行狀態
mat logs [N]       # 看日誌（預設 tail -f；可傳行數）
mat run            # 前景執行（除錯用）
mat config         # 修改 Token / 白名單
mat setup          # 重跑設定精靈
mat update         # git pull + 重啟
```

### Docker 模式

```bash
cd ~/mini_agent_team
docker compose ps                     # 狀態
docker compose logs -f gateway        # 即時日誌
docker compose restart                # 重啟
docker compose down                   # 停止
docker compose up -d --build          # 改設定後重 build
```

### Systemd 模式（Linux）

```bash
systemctl --user status   gateway-agent
systemctl --user restart  gateway-agent
journalctl --user -u gateway-agent -f
```

### Launchd 模式（macOS）

```bash
launchctl list | grep gateway
launchctl stop  com.kiwi.gateway-agent     # 暫停（KeepAlive 會自動重啟）
launchctl unload ~/Library/LaunchAgents/com.kiwi.gateway-agent.plist  # 完全停止
```

---

## 設定檔

### `secrets/.env`（敏感資訊，chmod 600）

```env
TELEGRAM_BOT_TOKEN=123456789:AABBCC...
DISCORD_BOT_TOKEN=                       # 選填
ALLOWED_USER_IDS=123456789,987654321     # 必填，空白即拒絕所有人
DEFAULT_CWD=/path/to/work/dir            # CLI 子程序的工作目錄
DEBUG_LOG=false
```

### `config/config.toml`

```toml
[gateway]
default_runner = "claude"
session_idle_minutes = 60
stream_edit_interval_seconds = 1.5

[runners.claude]
type = "acp"
path = "claude-agent-acp"
timeout_seconds = 300
context_token_budget = 4000

[runners.codex]
type = "acp"
path = "codex-acp"
timeout_seconds = 300

[runners.gemini]
type = "acp"
path = "gemini"
args = ["--acp", "--yolo"]
timeout_seconds = 300

[memory]
db_path = "data/db/history.db"
distill_trigger_turns = 20             # 超過 N 輪自動觸發精煉
search_mode = "fts5"                   # 或 "fts5+vector"

[discord]
allow_user_messages = "all"            # off / mentions / all
allow_bot_messages  = "off"            # off / mentions / all
trusted_bot_ids     = []
```

### Docker OAuth 路徑

容器內 `HOME=/root`，setup wizard 自動掛載：

| CLI | 宿主路徑 | 容器路徑 |
|-----|---------|----------|
| claude | `~/.claude` | `/root/.claude:ro` |
| codex | `~/.codex` | `/root/.codex:ro` |
| gemini | `~/.gemini` | `/root/.gemini:ro` |

只有實際存在的路徑才會被掛上去；不存在的會自動跳過。

---

## Bot 內指令

在 Telegram / Discord 對 bot 傳訊息時可用：

| 分類 | 指令 | 說明 |
|------|------|------|
| **切換 Runner** | `/claude`、`/codex`、`/gemini` | 切換當前 AI |
| | `/use <role>` | 切換到指定 roster 角色 |
| **多 Agent** | `/discuss <r1,r2> [prompt]` | 多 Agent 腦力激盪 |
| | `/debate <r1,r2> [prompt]` | 多 Agent 對立辯論 |
| | `/relay <r1,r2,...>` | 串聯接力 |
| **記憶** | `/remember <text>` | 寫入 Tier 1 永久事實 |
| | `/recall <query>` | 全文搜尋 Tier 3 歷史 |
| **系統** | `/status` | 系統狀態 |
| | `/usage` | Token 統計 |
| | `/new` | 重置當前 Session |
| | `/cancel` | 中斷正在跑的回覆 |
| **設定** | `/team`、`/agency`、`/dev` | 管理虛擬團隊 |
| | `/mcp-list`、`/mcp` | MCP 工具管理 |
| | `/sysinfo`、`/describe`、`/search` | 系統 / 視覺 / 網頁搜尋 |

---

## 客製化

### 新增專家角色（Roster）

在 `roster/` 加一個 `.md`：

```markdown
---
slug: data-scientist
name: 資料科學家
summary: 專注於資料分析、統計建模與 ML pipeline 設計。
identity: 你是經驗豐富的資料科學家，擅長把模糊問題拆解為可量化指標。
rules:
  - 提供分析時必須附上抽樣方法與信賴區間。
  - 拒絕未經驗證的因果聲明。
---
```

重啟 bot 後即可用 `/use data-scientist` 切換。

### 新增 Skill（外掛指令）

在 `modules/<name>/` 建立 manifest 與處理函式，loader 會自動掃描並註冊 slash commands。參考 `modules/web_search/`、`modules/vision/` 既有實作。

---

## 疑難排解

### Telegram 409 Conflict

> `Conflict: terminated by other getUpdates request`

代表同一個 token 有兩個 instance 在 polling。常見原因：
- 同台機器有 launchd / Docker / `python main.py` 同時跑（setup wizard 開頭會自動偵測並請你停舊的）
- **不同機器共用同一個 token**（例如 Mac 跟 Linux 都跑同一個 bot）— 換 token 是唯一解

### Bot 回 "An error occurred. Please try again."

容器內找不到 CLI 二進位檔。在 Docker 模式下發生，通常是：
- 沒重 build 容器（改 `state.selected_clis` 後要 `docker compose up -d --build`）
- 宿主 OAuth 沒掛載到容器（檢查 `~/.claude` 等路徑是否存在）

### Setup 精靈跳成文字輸入而非 arrow-key UI

需要 `/dev/tty` 可開。`curl ... | bash` 路徑下 install.sh 會自動把 stdin/stdout 重定向到 `/dev/tty`，理論上不會降級。如果還是降級，檢查是否在無 controlling terminal 環境（CI / cron / `docker exec` 沒加 `-t`）。

### Mac 系統 Python 3.9 衝突

macOS 內建的 `/usr/bin/python3` 是 3.9，太舊。MAT 必須用 venv：

```bash
./venv/bin/python3 -m src.setup.wizard --reset
```

不要直接用 `python3 setup.py`。

---

## 專案結構

```text
mini_agent_team/
├── main.py                # bot 入口
├── install.sh             # 一鍵安裝（含跨平台 pkg manager）
├── uninstall.sh           # 完整移除
├── mat                    # 全域 wrapper（mat install-cmd）
├── agent                  # 服務管理（launchd / systemd）
├── setup.py               # wizard 入口（python -m）
├── roster/                # 專家角色 DNA（.md frontmatter）
├── src/
│   ├── channels/          # Telegram / Discord adapter
│   ├── core/              # 設定、日誌、雙層記憶
│   ├── gateway/           # router、role_router、session、streaming
│   ├── runners/           # ACP runner、JSON-RPC 協議
│   ├── setup/             # 精靈、preflight、smoke_test、deploy
│   └── skills/            # skill loader
├── modules/               # 內建 skill：web_search / vision / mcp / ...
├── requirements.txt       # Python 依賴（pip-compile lock）
├── requirements.in        # 平台無關來源（macOS 用）
├── data/                  # 執行時：DB、log、memory（.gitignore）
├── secrets/               # token / .env（.gitignore）
└── config/                # config.toml（wizard 產生）
```

---

## 安全

- **白名單預設關閉**（fail-closed）：未設 `ALLOWED_USER_IDS` 拒絕所有訊息
- **記憶嚴格隔離**：以 `(user_id, channel)` 分桶，跨用戶看不到彼此資料
- **OAuth 唯讀掛載**：Docker 模式宿主憑證以 `:ro` 掛入，容器內無法寫回
- **僅限個人使用**：請勿把個人訂閱的 CLI 拿去當公開服務

---

## 移除

```bash
bash ~/mini_agent_team/uninstall.sh
```

互動式詢問是否保留對話資料，會清掉 launchd plist / systemd unit / Docker container。

---

## 授權

MIT License
