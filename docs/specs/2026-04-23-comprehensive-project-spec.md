# mini_agent_team 完整軟體需求規格書 (SRS) 暨 專案開發計畫書

**文件版本:** V1.2 (Full Comprehensive Edition)
**文件狀態:** 審閱中
**發布日期:** 2026-04-23
**專案代號:** Project MAGI (Virtual Agency Infrastructure)

---

## 1. 專案背景與願景 (Vision & Background)

### 1.1 核心理念
`mini_agent_team` 旨在建構一個**「隨身攜帶的 AI 軟體公司」**。它不僅是一個聊天機器人，而是一個具備「決策大腦 (L1)」、「專業執行 (L2)」與「長期記憶 (Tier 3)」的動態代理人環境。它解決了行動端開發者無法高效使用本地端強大 AI (如 Claude Code) 的痛點，並透過「虛擬企業 (Agency)」架構，實現了複雜任務的自動化拆解與並行處置。

### 1.2 業務目標
- **極致的交互體驗**: 實現端到端的 Streaming 響應，讓手機端的延遲感降至最低。
- **高精準度的專家系統**: 透過 Roster 角色庫，強制 AI 遵守特定領域的行為準則 (DNA)，而非通用的模型回應。
- **自主環境感知**: 系統應具備自動掃描路徑與識別專案結構的能力，徹底消除「請提供完整路徑」的低效率對話。

---

## 2. 系統功能詳細說明 (Detailed Functional Descriptions)

### 2.1 指令系統與交互邏輯 (The Command Interface)
系統支援三類指令交互：
- **元指令 (Meta Commands)**:
    - `/status`: 回報當前所有 Runner 狀態、Token 消耗量與選定的角色。
    - `/reset` / `/new`: 執行 Session 與路徑狀態的清理，確保下一個任務的乾淨環境。
    - `/remember <fact>`: 手動將事實存入 Tier 3 長期記憶（FAISS 向量庫）。
- **協作模式指令 (Multi-Agent Modes)**:
    - `/discuss <runners> <prompt>`: 觸發模型間的對話，用於腦力激盪。
    - `/relay <runners> <prompt>`: 鏈式處理任務，A 的輸出作為 B 的輸入。
    - `/debate <runners> <prompt>`: 讓不同模型針對同一議題進行辯論，產出對比分析。
- **虛擬企業指令 (Agency Commands)**:
    - `/agency use <role_slug>`: 啟動特定專家 DNA。
    - `/agency info <role_slug>`: 顯示該專家的行為規則、優先模型與專業背景。

### 2.2 自然語言意圖路由 (Intelligent Intent Routing)
系統內建三層解析路徑：
1. **正規路徑 (Regex)**: 快速辨識顯式指令與已知關鍵字。
2. **語義路徑 (Semantic)**: 當用戶輸入模糊人話時（如「幫我看看這段 code 穩不穩」），路由器會調用本地 Embedding 模型進行向量比對，自動判定應由 `code-auditor` 角色接手。
3. **決策路徑 (LLM)**: 若前兩層無法判定，則由 L1 (Department Head) 進行最終意圖評估。

---

## 3. 虛擬企業治理架構 (The Agency Architecture)

### 3.1 層級化分派模型 (Hierarchical Governance)
- **L1: 部門主管 (Department Head)**:
    - **任務**: 接收用戶輸入，調用 `planner.py` 產出 JSON 分派清單。
    - **環境對齊**: 負責在分派前執行 `ls-files`，將「必要」的路徑資訊注入分派 JSON。
- **L2: 專家 Sub-agents**:
    - **執行機制**: 每個 Sub-agent 在獨立的 `git worktree` 中執行，互不干擾。
    - **DNA 繼承**: 自動加載對應的 `roster/*.md`，將身份與規則 prepend 到 System Prompt。

### 3.2 Roster DNA 規範 (The Genetic Code)
角色定義必須包含以下維度，以確保行為一致性：
- **Identity (身份)**: 定義專業背景（如：你是擁有 10 年經驗的 Rust 工程師）。
- **Mission (核心任務)**: 該角色的終極存在目標。
- **Critical Rules (強制準則)**: 如「禁止使用外部庫」、「必須編寫單元測試」。
- **Precedence (權限優先級)**: 當使用者指令與規則衝突時的處置邏輯。

---

## 4. 記憶體系統深度設計 (Advanced Memory Management)

系統採用「多級緩存」與「語義檢索」相結合的機制：
- **L0: Context Window (動態上下文)**:
    - 自動對超長對話進行「摘要提煉 (Distillation)」，將重要進度保存，丟棄冗餘 Token。
- **T1: SQLite WAL (短期歷史)**:
    - 高頻寫入的 JSONL 對話歷史，支援 FTS5 全文檢索，讓用戶能下指令「回顧昨天的討論」。
- **T3: FAISS Vector Space (事實地圖)**:
    - 儲存跨專案的長期事實（例如：使用者的部署偏好、常用伺服器位址）。

---

## 5. 技術堆棧與數據模型 (Technical Stack & Data Models)

### 5.1 核心技術選型
- **後端引擎**: Python 3.12+ (Asyncio-driven)。
- **通訊適配**: `python-telegram-bot`, `discord.py`。
- **本地 LLM 加速**: `sentence-transformers` (Vector Indexing), `onnxruntime` (Future Support)。
- **程序管理**: `asyncio.subprocess` 對底層二進制 (Claude Code, Gemini CLI) 進行非同步 I/O 監控。

### 5.2 核心數據結構 (Simplified Schema)
```sql
-- 設置表：存儲角色與個性
CREATE TABLE settings (
    user_id BIGINT,
    key TEXT, -- 'active_role', 'cwd_anchor', 'personality'
    value TEXT,
    updated_at TIMESTAMP
);

-- 審核日誌：追蹤 AI 的具體操作
CREATE TABLE audit_logs (
    session_id UUID,
    runner TEXT,
    command_sent TEXT,
    raw_output_path TEXT,
    token_cost FLOAT
);
```

---

## 6. 非功能性需求與邊界 (Non-Functional Constraints)

### 6.1 安全性規範
- **執行隔離**: 所有的代碼修改操作必須在生成的 Temp Worktree 中進行，未經用戶確認（或符合特定策略）不得合併至 Main 分支。
- **敏感資訊屏蔽**: 系統自動檢索 `.env` 檔案並在傳遞給外部模型前進行 Token 級別的屏蔽。

### 6.2 Token 經濟學 (Token Economy)
- **精準裁剪**: 禁止將全量目錄樹 (`tree`) 傳遞給 LLM。系統應優先使用「路徑映射表 (Path Map)」。
- **層級隔離**: L1 產生的規劃 JSON 是唯一的中介媒介，L2 不得讀取 L1 的思考過程 (Thought process) 以節省 Input Token。

---

## 7. 安裝與部署指南 (Deployment & Maintenance)

### 7.1 環境準備
1. 安裝 `claude-code` 與 `gemini-cli` 並完成授權。
2. 建立 Python 虛擬環境並安裝 `requirements.txt`。
3. 配置 `.env` 檔案中的 `TELEGRAM_TOKEN` 與 `ALLOWED_USER_IDS`。

### 7.2 初始化流程
1. 執行 `python setup.py --init` 建立本地 SQLite 資料庫。
2. 系統自動掃描 `roster/` 目錄並建立語義索引。
3. 啟動 `main.py` 進行心跳檢測。

---

## 8. 專案開發里程碑 (Project Roadmap)

### Phase 1: 基礎建設與角色庫 (已就緒)
- 實作 Roster 目錄結構與 Frontmatter 解析。
- 完成 `/agency` 核心指令開發。
- 擴充 SQLite 以支援持久化角色狀態。

### Phase 2: 層級化調度引擎 (開發中)
- 升級 `planner.py` 與 `executor.py` 支援角色委派。
- 實作 DNA 自動注入機制與三段式 Prompt 拼接。
- 整合 Git Worktree 自動建立與回收流程。

### Phase 3: 語義加速與檔案導航 (待啟動)
- 引入本地 Embedding 引擎，實現零成本意圖路由。
- 實作「智能路徑發現器」，讓 AI 能在不詢問路徑的情況下精確定位檔案。
- 增加 Web 前端管理介面，可視化查看 Agency 運作狀態。

---

## 9. 異常處理與修復策略 (Error Handling)

- **Runner 超時**: 當 CLI 工具超過 120s 未回應，系統自動終止子行程並向用戶回報最後 5 行輸出。
- **路徑衝突**: 若多個 Sub-agent 同時修改同一檔案，Executor 負責鎖定檔案或透過 Git Merge 機制解決衝突。
- **規劃失敗**: 若 Planner 產出無效 JSON，系統自動 fallback 至預設主管模式手動提示用戶修正。

---

## 10. 結語 (Closing)

`mini_agent_team` 不僅是一個工具，它代表了未來軟體開發的新正規：**由一個核心開發者搭配一組由 AI 組成的專業化部門**。透過本規格書定義的架構，我們將打造出一個穩定、高效、且具備深度專業知識的虛擬開發團隊。

---
**[文件審閱點: V1.2.0-Final]**
