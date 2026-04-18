# Gateway Agent Platform — Design Spec
**Date:** 2026-04-18  
**Repo:** nchiyi/telegram-to-control  
**Status:** Draft — pending user approval

---

## 1. 目標

將現有 `telegram-to-control` 重新設計為一個**閘道式 AI Agent 平台**，以 Telegram / Discord 作為控制介面，優先透過 CLI（claude / codex / gemini / kiro 等）驅動 AI 能力，支援熱插拔模組、分層記憶與 MCP 工具呼叫。

---

## 2. 架構總覽

```
src/
  channels/           ← 頻道 adapter（Telegram / Discord）
  gateway/            ← 核心閘道（路由、session、串流）
  runners/            ← CLI / API 執行器
  core/               ← 記憶、排程、設定
  modules/            ← 熱插拔功能模組
config/               ← 設定檔
data/
  memory/hot/         ← 壓縮 JSON（hot path）
  memory/cold/        ← 自然語言 .md（cold path）
  db/                 ← SQLite（對話歷史）
docs/
setup.py / setup.sh   ← 互動式安裝精靈
```

---

## 3. 模組一：頻道 Adapter（ChannelAdapter）

### 3.1 設計
- `BaseAdapter`：定義共用介面（`send`, `send_stream`, `react`, `edit`）
- `TelegramAdapter`：實作 python-telegram-bot
- `DiscordAdapter`：實作 discord.py

### 3.2 驗收條件
- [ ] Telegram bot 可收發文字訊息
- [ ] Discord bot 可收發文字訊息
- [ ] 兩個 adapter 可同時運行，互不干擾
- [ ] 串流訊息每 1.5 秒 edit 一次（不洗版）
- [ ] 傳送超過 4096 字元自動分割

---

## 4. 模組二：閘道核心（Gateway）

### 4.1 設計
- `Router`：根據訊息內容決定交給哪個 runner 或模組
- `SessionManager`：管理每個 user 的對話 session（含 cwd、model 選擇）
- `StreamingBridge`：把 runner 的串流輸出回傳給 adapter

### 4.2 驗收條件
- [ ] 收到 `/claude 寫一個 hello world` → 交給 CLIRunner(claude)
- [ ] 收到 `/codex 重構這個函式` → 交給 CLIRunner(codex)
- [ ] 收到一般文字 → 交給預設 runner
- [ ] session 在 idle 60 分鐘後自動釋放
- [ ] 切換 model 指令（`/use gemini`）即時生效，下一則訊息套用

---

## 5. 模組三：CLI 執行器（CLIRunner / ACP）

### 5.1 設計
- `CLIRunner`：以 subprocess 啟動 CLI，stdin/stdout 雙向溝通（ACP / JSON-RPC over stdio）
- 支援串流輸出（逐行回傳）
- 支援工具呼叫自動回覆（auto-approve policy）
- Claude 額外整合 MCP 工具呼叫層
- `APIRunner`：未來 OAuth / API key 模式的 fallback（介面相同）

### 5.2 驗收條件
- [ ] `CLIRunner("claude")` 可送出 prompt 並收到串流回應
- [ ] `CLIRunner("codex")` 可送出 prompt 並收到串流回應
- [ ] `CLIRunner("gemini")` 可送出 prompt 並收到串流回應
- [ ] 工具呼叫（tool use）自動回覆，不需人工介入
- [ ] CLI 進程崩潰後自動重啟，不影響 session
- [ ] MCP 工具呼叫（僅 claude）可正確觸發並回傳結果

---

## 6. 模組四：記憶系統（Memory）

### 6.1 分層設計

| 層級 | 名稱 | 儲存格式 | 存放位置 | 清除規則 |
|------|------|----------|----------|----------|
| Tier 1 | 永久記憶 | .md 自然語言 | `data/memory/cold/permanent/` | 永不自動清除，人工管理 |
| Tier 2 | 工作記憶 | 壓縮 JSON (hot) + .md 原始備份 (cold) | hot: `data/memory/hot/` / cold: `data/memory/cold/session/` | 話題切換時蒸餾壓縮 |
| Tier 3 | 對話歷史 | SQLite | `data/db/history.db` | 超過 20 輪自動截斷 |

### 6.2 Context 組裝上限
```
System prompt          ≤ 500 tokens（固定）
Tier 1 永久記憶摘要    ≤ 800 tokens（FTS 篩選）
Tier 2 工作記憶 JSON   ≤ 600 tokens
Tier 3 對話歷史        ≤ 2000 tokens（最近 N 輪）
當前訊息               剩餘空間
總計上限               ≤ 4000 tokens
```

### 6.3 搜尋
- 預設：FTS5 關鍵字搜尋
- 可選：FTS5 + embedding（setup 時詢問，背景安裝 Ollama + nomic-embed-text）

### 6.4 蒸餾保護
- 蒸餾前先萃取長期事實，升級到 Tier 1
- 使用者可下 `/remember <內容>` 強制升級到 Tier 1

### 6.5 驗收條件
- [ ] 對話超過 20 輪，自動蒸餾並壓縮到 Tier 2 hot JSON
- [ ] 蒸餾後 cold .md 備份仍可查詢
- [ ] `/remember 我是工程師` → 寫入 Tier 1 .md，下次對話仍記得
- [ ] `/recall 閘道架構` → FTS5 搜尋 cold storage，回傳相關片段
- [ ] Context 組裝不超過 4000 tokens（可量測）
- [ ] 啟用 embedding 後，語意查詢可找到關鍵字不完全匹配的記憶

---

## 7. 模組五：熱插拔模組系統（Modules）

### 7.1 設計
每個模組是一個目錄，包含：
```
modules/web_search/
  manifest.yaml    ← 名稱、指令、描述、依賴、版本
  handler.py       ← 主邏輯
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
```

- 啟動時自動掃描 `modules/` 目錄載入
- 模組間透過 Gateway 事件匯流排溝通，不直接 import
- 新增模組：放進目錄，重啟自動載入
- 停用模組：`manifest.yaml` 設 `enabled: false` 或移除目錄

### 7.2 預裝模組清單
| 模組 | 指令 | 說明 |
|------|------|------|
| web_search | /search | Tavily / DuckDuckGo 搜尋 |
| system_monitor | /status | CPU / 記憶體 / 磁碟狀態 |
| scheduler | /remind | cron 排程提醒 |
| vision | /describe | 圖片描述（Ollama vision model）|
| dev_agent | /dev | 開發任務（呼叫 CLIRunner）|

### 7.3 驗收條件
- [ ] 新增一個空模組目錄 + manifest.yaml，重啟後指令可用
- [ ] 移除模組目錄，重啟後指令消失，其他模組正常運作
- [ ] 停用 `web_search`，`/search` 回傳「模組未啟用」，不崩潰
- [ ] 模組 A 不可直接 import 模組 B（lint 或 test 可驗證）

---

## 8. 模組六：安裝精靈（Setup）

### 8.1 流程
```
1. 選擇頻道         → Telegram / Discord / 兩者
2. 填入 bot token   → 自動驗證 token 是否有效
3. 設定白名單       → user ID 列表
4. 選擇 CLI         → claude / codex / gemini / kiro（多選）
5. CLI 安裝配置     → 背景安裝，進度通知
6. 選擇搜尋模式     → FTS5 / FTS5+embedding
7. embedding 安裝   → 背景安裝 Ollama + nomic-embed-text（若選擇）
8. 自動更新設定     → CLI 版本變更時通知 / 自動更新
9. 啟動             → 所有服務就緒後啟動
```

### 8.2 驗收條件
- [ ] 完整走完 setup 流程不超過 5 分鐘（不含下載時間）
- [ ] Token 填錯時顯示明確錯誤，可重填
- [ ] CLI 安裝背景進行，setup 流程繼續問下一題
- [ ] Ollama 下載期間每 30 秒推送一次進度給 Telegram / Discord
- [ ] setup 完成後直接啟動，不需手動執行額外指令
- [ ] 重跑 setup 不清除現有記憶資料

---

## 9. 非功能性需求

| 項目 | 目標 |
|------|------|
| 訊息回應延遲 | CLI 開始輸出後 3 秒內出現第一個字 |
| 記憶查詢延遲 | FTS5 查詢 < 200ms |
| CLI 進程恢復 | 崩潰後 5 秒內重啟 |
| Token 上限 | 每次對話 context ≤ 4000 tokens |
| 模組隔離 | 單一模組錯誤不影響其他模組 |

---

## 10. 模組七：Agent-to-Agent 協作（ACP Team）

### 10.1 設計（對齊 my-claude-devteam）
- `AgentTeam`：管理多個 CLI agent 的協同執行
- P7 單任務：直接派給單一 agent
- P9 多模組任務：拆子任務，並行派給多個 agent（codex / gemini / claude）
- P10 架構決策：輸出策略文件，不直接實作
- 每個子任務有明確 DoD（完成定義），結果回報 Gateway，再推送頻道

### 10.2 Agent 角色對應
| Agent | 角色 | 呼叫方式 |
|-------|------|---------|
| claude | 主協調者 / 架構決策 | `echo "<task>" \| claude --dangerously-skip-permissions` |
| codex | 實作、寫 code | `echo "<task>" \| codex --approval-policy auto` |
| gemini | 研究、查文件 | `echo "<task>" \| gemini` |

### 10.3 驗收條件
- [ ] `/team <任務描述>` → Gateway 判斷 P7/P9，分派給對應 agent
- [ ] P9 任務可同時派 codex + gemini，結果整合後回傳
- [ ] 每個子任務有明確的 DoD 輸出
- [ ] Agent 執行過程中推送進度到 Telegram / Discord

---

## 11. 不在此版本範圍

- macOS Chrome 操作（Playwright 模組，後續版本）
- 多使用者同時在線（目前設計為個人使用）
- Web UI
- iOS / Android app

---

## 12. 實作順序建議

1. 記憶系統（Tier 1/2/3）+ Context 組裝
2. CLIRunner（ACP）+ 串流
3. Gateway Router + SessionManager
4. TelegramAdapter
5. DiscordAdapter
6. AgentTeam（P7/P9/P10）
7. 模組系統 + 預裝模組移植
8. Setup 精靈
9. MCP 整合（claude 專用）
