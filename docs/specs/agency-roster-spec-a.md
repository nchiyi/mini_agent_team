# Spec A: Roster + Agency Module (Final)

## 1. 範圍
- `roster/*.md` schema 定義
- `modules/agency/` 模組實作 (manifest.yaml, handler.py)
- `/agency list|info|use|clear` 指令集
- `active_role` session storage 規範

## 2. Roster Schema (Markdown Frontmatter)
- `slug`: (Required) 唯一穩定識別碼 (a-z, 0-9, -)。
- `name`: (Required) 顯示名稱。
- `summary`: (Required) 功能描述 (供語義索引)。
- `identity`: 角色專業背景與口吻。
- `rules`: 行為準則 (DNA)，執行時將注入。
- `preferred_runner`: 建議引擎 (claude/gemini/codex)。

## 3. 實作細節
- **落點**: `modules/agency/` (符合現有 loader 規範)。
- **Session**: `active_role` 存在用戶 session 中，`/new` 或 `/reset` 時需清除。
- **整合**: 預設 `Department Head` 為系統保留角色。