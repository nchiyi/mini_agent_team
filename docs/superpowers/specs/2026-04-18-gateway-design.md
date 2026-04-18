# Gateway Agent Platform — Design Spec
**Date:** 2026-04-18  
**Repo:** nchiyi/telegram-to-control  
**Status:** Draft v2 — Codex review applied

---

## 變更紀錄（v2）
- 修正 CLIRunner 呼叫模型矛盾（長駐 vs 一次性）
- 修正實作順序（Adapter → Gateway → CLIRunner → Memory）
- 加入安全模型（audit log、危險操作攔截）
- 加入 `/cancel` 指令
- 修正模組系統「熱插拔」措辭（改為啟動時載入）
- 修正訊息長度限制（Telegram 4096 / Discord 2000）
- 加入 SQLite WAL 模式要求
- 加入中文 FTS5 斷詞說明
- AgentTeam 加入 git worktree 隔離
- 修正蒸餾觸發條件（輪數 + 話題切換）
- 修正 Tier 3「截斷」措辭（改為 context selection）
- Token 上限改為 per-runner 可配置

---

## 1. 目標

將現有 `telegram-to-control` 重新設計為一個**閘道式 AI Agent 平台**，以 Telegram / Discord 作為控制介面，優先透過 CLI（claude / codex / gemini / kiro 等）驅動 AI 能力，支援模組化擴充、分層記憶與 MCP 工具呼叫。

---

## 2. 架構總覽

```
src/
  channels/           ← 頻道 adapter（Telegram / Discord）
  gateway/            ← 核心閘道（路由、session、串流、安全）
  runners/            ← CLI 執行器（per-CLI adapter）
  core/               ← 記憶、排程、設定、audit log
  modules/            ← 功能模組（啟動時掃描載入）
config/               ← 設定檔（TOML，不含 secrets）
secrets/              ← bot token、API key（.gitignore）
data/
  memory/hot/         ← 壓縮 JSON（hot path，per-user）
  memory/cold/        ← 自然語言 .md（cold path，可 Git 追蹤）
  db/                 ← SQLite（WAL 模式）
  worktrees/          ← AgentTeam 並行執行的 git worktree
  audit/              ← audit log（每個 CLI 操作紀錄）
docs/
setup.py              ← 互動式安裝精靈（唯一入口）
```

---

## 3. 模組一：頻道 Adapter（ChannelAdapter）

### 3.1 設計
- `BaseAdapter`：定義共用介面（`send`, `send_stream`, `react`, `edit`）
  - 每個方法定義 capability flag；不支援的操作 fallback 到基本 `send`
- `TelegramAdapter`：python-telegram-bot，訊息上限 4096 字元
- `DiscordAdapter`：discord.py，訊息上限 2000 字元
- 串流 edit：每 1.5 秒更新一次，並處理 rate limit（指數退避）、訊息被刪除（fallback 新發）
- 兩個 adapter 各自管理 async lifecycle，透過共用 event queue 與 Gateway 溝通

### 3.2 驗收條件
- [ ] Telegram bot 可收發文字訊息
- [ ] Discord bot 可收發文字訊息
- [ ] 兩個 adapter 同時運行，互不干擾，其中一個 token 錯誤不影響另一個
- [ ] 串流訊息每 1.5 秒 edit 一次，rate limit 時退避，不崩潰
- [ ] Telegram 超過 4096 字元自動分割；Discord 超過 2000 字元自動分割
- [ ] `react` / `edit` 不支援時，fallback 到 `send`，不拋例外

---

## 4. 模組二：閘道核心（Gateway）

### 4.1 設計
- `Router`：解析指令前綴（`/claude`, `/codex`, `/gemini` 等），分派給對應 runner 或模組
  - 無前綴文字 → 交給 default runner（config 設定）
  - 指令衝突（多模組宣告同一 command）→ 啟動時報錯，不靜默覆蓋
- `SessionManager`：per-user-per-channel session（Telegram user A 和 Discord user A 是獨立 session）
  - session 包含：current runner、cwd（有白名單限制）、context buffer
  - idle 60 分鐘後自動釋放，釋放時清理 subprocess 和 temp files
- `StreamingBridge`：把 runner 的串流輸出轉送給 adapter
- `/cancel`：中止當前 user 的執行中任務，SIGTERM runner subprocess

### 4.2 驗收條件
- [ ] 收到 `/claude 寫一個 hello world` → 交給 CLIRunner(claude)
- [ ] 收到 `/codex 重構這個函式` → 交給 CLIRunner(codex)
- [ ] 收到一般文字 → 交給 default runner（config 指定）
- [ ] session idle 60 分鐘後自動釋放，subprocess 被清理
- [ ] `/use codex` 切換 default runner，下一則訊息套用
- [ ] `/cancel` 中止執行中任務，回覆確認訊息
- [ ] 兩個模組宣告同一 command → 啟動失敗並報錯
- [ ] cwd 設定到不存在路徑 → 回覆錯誤，不崩潰

---

## 5. 模組三：CLI 執行器（CLIRunner）

### 5.1 呼叫模型（確定選用：每次任務啟動獨立子進程）

**設計決定：** 不使用長駐 JSON-RPC 協定（各 CLI 行為不一致，難以統一）。改用**每次任務啟動獨立 subprocess**，stdin 送入 prompt，stdout/stderr 串流回傳，任務完成後關閉進程。

```
每個任務：
  subprocess.Popen([cli_path, *args], stdin=PIPE, stdout=PIPE, stderr=PIPE)
  → 送入 prompt（含 context）
  → asyncio 逐行讀 stdout，串流回 Gateway
  → EOF 或 timeout → 關閉進程
```

- 每個 CLI 有獨立的 `CLIAdapter`（處理各自的 flag、TTY 偽裝、ANSI 過濾、輸出格式）
- 支援工具呼叫自動確認（目前僅 claude 和 codex 有此機制）
- Claude 額外整合 MCP 工具呼叫層
- `APIRunner`：OAuth / API key 模式（介面同 CLIRunner，未來實作）

### 5.2 安全模型
- 所有 CLI 呼叫記錄到 `data/audit/YYYY-MM-DD.jsonl`（timestamp、user、runner、prompt 摘要、cwd）
- 危險操作攔截清單（config 可配置）：`rm -rf /`、`git push --force main` 等 → 攔截並詢問確認
- 不預設使用 `--dangerously-skip-permissions`；需要時由 config 明確啟用，並記錄 audit

### 5.3 驗收條件
- [ ] `CLIRunner("claude")` 可送出 prompt 並收到串流回應
- [ ] `CLIRunner("codex")` 可送出 prompt 並收到串流回應
- [ ] `CLIRunner("gemini")` 可送出 prompt 並收到串流回應
- [ ] runner timeout（預設 5 分鐘）後自動終止，回覆 timeout 訊息
- [ ] CLI 未安裝時，setup 或 runtime 給出明確錯誤，不崩潰
- [ ] 每次呼叫寫入 audit log（可查最近 N 筆）
- [ ] 危險指令被 CLI 輸出觸發時，回覆確認提示再執行

---

## 6. 模組四：記憶系統（Memory）

### 6.1 分層設計

| 層級 | 名稱 | 儲存格式 | 存放位置 | 清除規則 |
|------|------|----------|----------|----------|
| Tier 1 | 永久記憶 | .md 自然語言 | `data/memory/cold/permanent/` | 永不自動清除，人工管理 |
| Tier 2 | 工作記憶 | 壓縮 JSON (hot) + .md 原始備份 (cold) | hot: `data/memory/hot/` / cold: `data/memory/cold/session/` | 蒸餾觸發後壓縮，.md 備份永久保留 |
| Tier 3 | 對話歷史 | SQLite（WAL 模式）| `data/db/history.db` | 永久儲存；context 組裝時只取最近 N 輪，不刪資料 |

**注意：** Tier 3 不刪資料，「截斷」指的是 context 組裝時的 selection，不是資料清除。

### 6.2 SQLite 設定
- 啟用 WAL 模式（`PRAGMA journal_mode=WAL`）防止多 async 寫入衝突
- 所有寫入透過單一 async 佇列序列化

### 6.3 Context 組裝上限（per-runner 可配置）
```
System prompt          ≤ 500 tokens（固定）
Tier 1 永久記憶摘要    ≤ 800 tokens（FTS 篩選，最相關片段）
Tier 2 工作記憶 JSON   ≤ 600 tokens
Tier 3 對話歷史        ≤ 2000 tokens（最近 N 輪）
當前訊息               剩餘空間
總計預算               config 設定（預設 4000，claude 可設更高）
```
Token 計數使用 tiktoken（cl100k_base），中文估算偏高，預留 20% buffer。

### 6.4 搜尋
- 預設：FTS5 關鍵字搜尋（啟用 `unicode61` tokenizer 改善中文斷詞）
- 可選：FTS5 + embedding（setup 時詢問，背景安裝 Ollama + nomic-embed-text）
- Embedding 服務停止時，自動 fallback 到 FTS5，不中斷服務

### 6.5 蒸餾觸發條件（兩者皆會觸發）
- 對話超過 20 輪（輪數觸發）
- 使用者切換話題（由 LLM 偵測，每 5 輪判斷一次）

### 6.6 蒸餾保護
- 蒸餾前先萃取長期事實，升級到 Tier 1（附 timestamp，可審查）
- 使用者可下 `/remember <內容>` 強制升級到 Tier 1
- 使用者可下 `/forget <關鍵字>` 刪除 Tier 1 對應條目

### 6.7 驗收條件
- [ ] 對話超過 20 輪，自動蒸餾並壓縮到 Tier 2 hot JSON
- [ ] 蒸餾後 Tier 3 SQLite 原始資料仍在，可 `/recall` 查詢
- [ ] `/remember 我是工程師` → 寫入 Tier 1 .md，下次對話仍記得
- [ ] `/forget 工程師` → Tier 1 對應條目被刪除
- [ ] `/recall 閘道架構` → FTS5 搜尋 cold storage，回傳相關片段
- [ ] Context 組裝不超過 config 設定上限（可量測）
- [ ] Embedding 服務停止 → fallback 到 FTS5，不崩潰
- [ ] 多個 async 任務同時寫入 SQLite，不發生 lock error

---

## 7. 模組五：模組系統（Plugin System）

### 7.1 設計
每個模組是一個目錄，包含：
```
modules/web_search/
  manifest.yaml    ← 名稱、指令、描述、依賴、版本
  handler.py       ← 主邏輯（只能透過 Gateway 事件介面和外界溝通）
  README.md
```

`manifest.yaml` 範例：
```yaml
name: web_search
version: 1.0.0
commands: [/search, /web]
description: 網路搜尋（Tavily / DuckDuckGo）
dependencies: [duckduckgo-search]
enabled: true
timeout_seconds: 30
```

- **啟動時掃描載入**（不是真正熱插拔；修改模組需重啟）
- 模組間透過 Gateway 事件介面溝通，不直接 import
- 模組 handler 有 timeout 保護（manifest 設定）
- 模組依賴在獨立 virtualenv 安裝，避免主環境衝突
- 模組載入失敗 → 跳過該模組，其他模組正常啟動，記錄 warning

### 7.2 預裝模組清單
| 模組 | 指令 | 說明 |
|------|------|------|
| web_search | /search | Tavily / DuckDuckGo 搜尋 |
| system_monitor | /status | CPU / 記憶體 / 磁碟狀態 |
| vision | /describe | 圖片描述（Ollama vision model）|
| dev_agent | /dev | 開發任務（呼叫 CLIRunner）|

（排程功能由 `core/scheduler` 提供，不是獨立模組）

### 7.3 驗收條件
- [ ] 新增模組目錄 + manifest.yaml，重啟後指令可用
- [ ] 移除模組目錄，重啟後指令消失，其他模組正常運作
- [ ] 停用 web_search，`/search` 回覆「模組未啟用」，不崩潰
- [ ] 模組 handler timeout（超過 manifest 設定）→ 回覆 timeout，Gateway 不阻塞
- [ ] 模組載入 import error → 跳過並記錄 warning，其他模組正常

---

## 8. 模組六：Agent-to-Agent 協作（AgentTeam）

### 8.1 設計（對齊 my-claude-devteam）
- `AgentTeam`：管理多個 CLI agent 的協同執行
- P7 單任務：直接派給單一 agent
- P9 多模組任務：拆子任務，並行派給多個 agent（codex / gemini / claude）
- P10 架構決策：輸出策略文件，不直接實作
- 每個子任務有明確 DoD（完成定義），結果回報 Gateway，再推送頻道

### 8.2 Agent 角色對應
| Agent | 角色 | 呼叫方式 |
|-------|------|---------|
| claude | 主協調者 / 架構決策 | `CLIRunner("claude")` |
| codex | 實作、寫 code | `CLIRunner("codex")` |
| gemini | 研究、查文件 | `CLIRunner("gemini")` |

### 8.3 並行隔離（P9）
- 每個並行子任務在獨立 git worktree（`data/worktrees/<task-id>/`）執行
- 任務完成後，worktree 結果由 claude 整合，使用標準 git merge
- 衝突由 claude 仲裁，回報使用者確認後才 commit

### 8.4 驗收條件
- [ ] `/team <任務描述>` → Gateway 判斷 P7/P9，分派給對應 agent
- [ ] P9 任務中，codex 和 gemini 在獨立 worktree 並行執行，不互相干擾
- [ ] 其中一個子任務失敗 → 回報失敗原因，其他子任務繼續
- [ ] 每個子任務有明確 DoD 輸出
- [ ] Agent 執行過程中推送進度到 Telegram / Discord
- [ ] 任務完成後 worktree 自動清理

---

## 9. 模組七：安裝精靈（Setup）

### 9.1 流程
```
1. 選擇頻道         → Telegram / Discord / 兩者
2. 填入 bot token   → 自動驗證 token 是否有效（可重填）
3. 取得白名單 ID    → 引導使用者發送測試訊息自動取得 user ID
4. 選擇 CLI         → claude / codex / gemini / kiro（多選，背景安裝）
5. 選擇搜尋模式     → FTS5 / FTS5+embedding（後者背景安裝 Ollama）
6. 自動更新設定     → 版本變更時通知（不自動更新，避免 API 相容性問題）
7. 選擇部署模式     → foreground / systemd / docker
8. 啟動
```

### 9.2 進度通知
- CLI 和 Ollama 安裝在背景進行，不阻塞流程
- 安裝進度每 30 秒在 terminal 顯示（bot 尚未就緒，不推送到頻道）
- 所有服務就緒後才啟動 bot

### 9.3 驗收條件
- [ ] 完整走完 setup 流程不超過 5 分鐘（不含下載時間）
- [ ] Token 填錯時顯示明確錯誤，可重填
- [ ] CLI 安裝背景進行，setup 流程繼續問下一題
- [ ] setup 完成後直接啟動，不需手動執行額外指令
- [ ] 重跑 setup 不清除現有記憶資料
- [ ] setup 中途失敗後重跑，已完成的步驟不重做

---

## 10. 非功能性需求

| 項目 | 目標 |
|------|------|
| 訊息首字延遲 | 使用者送出訊息到出現第一個字 ≤ 5 秒 |
| 記憶查詢延遲 | FTS5 查詢 < 200ms |
| CLI 任務 timeout | 預設 5 分鐘，config 可調 |
| Token 上限 | per-runner 可配置，預設 4000 |
| 模組隔離 | 單一模組 exception 不影響其他模組 |
| Audit log | 每個 CLI 呼叫都有紀錄，可查最近 1000 筆 |

---

## 11. 不在此版本範圍

- macOS Chrome 操作（Playwright 模組，後續版本）
- 多使用者同時在線（目前設計為個人使用；多個白名單 user 各有獨立 session）
- APIRunner（OAuth / API key）
- Web UI
- iOS / Android app

---

## 12. 實作順序（已修正）

1. **Config schema + secrets 管理**（所有模組的設定來源先定義好）
2. **TelegramAdapter 最小版**（有真實 channel 回路才能驗證後續功能）
3. **Gateway Router + SessionManager**（定義 session 邊界）
4. **CLIRunner（基本版，claude 先）**+ audit log
5. **端到端冒煙測試**：Telegram → Gateway → CLIRunner → 回傳
6. **DiscordAdapter**（此時 BaseAdapter 已穩定）
7. **Memory 系統**（Tier 1/2/3，context 組裝）
8. **模組系統 + 預裝模組移植**
9. **AgentTeam（P7/P9/P10）**+ worktree 隔離
10. **Setup 精靈**
11. **MCP 整合**（claude 專用）
12. **Embedding 可選安裝**（最後，不影響核心路徑）
