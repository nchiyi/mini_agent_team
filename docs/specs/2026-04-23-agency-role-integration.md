# Feature Spec: Agency-Agents Role Integration (V3 - Pre-Alpha)

## 1. 願景與設計哲學
將 `mini_agent_team` 轉型為「層級化虛擬企業」。
- **結構化 DNA**: 使用 Markdown Frontmatter 定義具備明確規則的角色。
- **部門主管制**: 預設以 `Department Head` 作為 L1 決策者。
- **扁平化 V1**: 僅限 L1 (主管) -> L2 (執行者) 兩層架構，禁止遞迴。

## 2. 角色庫規範 (Roster Schema)
存放於 `roster/*.md`，統一採用 Markdown Frontmatter 格式：
- `slug`: (Required) 唯一穩定識別碼 (a-z, 0-9, -)。
- `name`: (Required) 顯示名稱。
- `summary`: (Required) 一句話功能描述 (供語義索引)。
- `identity`: 角色專業背景與口吻。
- `rules`: 行為準則 (DNA)，執行時將 prepend 到 prompt。
- `preferred_runner`: 建議的執行引擎 (如 claude, gemini)。

## 3. 架構實作路徑 (Updated)

### Phase 1: Roster & Module Handler
- **目錄結構**: `roster/` 置於 root。
- **Module 落點**: 於 `modules/agency/` 實作 (包含 `manifest.yaml` 與 `handler.py`)。
- **指令集**: `/agency list|info|use`。
- **Session 管理**: `active_role` 作用域為 per-session，與 `/new`, `/reset` 連動清理。

### Phase 2: Role-Aware Planning/Execution
- **模型升級**: `SubTask` 結構改為 `{role, runner, prompt, dod}`。
- **DNA 注入**: Executor 執行前按 `Identity`, `Rules`, `Task Brief` 三段式 prepend DNA。
- **Runner 解析優先級**: User 指定 > Role 建議 (`preferred_runner`) > 系統預設。

### Phase 3: Performance Polish
- **語義路由**: 基於 `slug` 與 `summary` 建立本地語義匹配索引。
- **精準檔案導航**: 自動掃描僅限 `cwd` 深度 2 內之關鍵檔案，避免無謂的 Token 佔用。

## 4. 關鍵優化與限制
- **禁止遞迴**: L2 Sub-agent 禁止再次規劃。
- **環境對齊**: 所有執行路徑統一錨定至專案根目錄。