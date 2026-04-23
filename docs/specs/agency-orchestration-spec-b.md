# Spec B: Role-Aware Planner / Executor (Final)

## 1. 範圍
- `SubTask` 模型擴充
- Planner 輸出 schema 調整
- Executor 角色解析邏輯
- DNA 拼接格式 (Prepend)

## 2. 模型與邏輯
- **SubTask**: `{role: slug, runner: str, prompt: str, dod: str}`。
- **DNA Prepend**: 執行前按 [Identity] / [Rules] / [Task Brief] 三段式組裝。
- **優先級**: User Override > Role Preferred Runner > System Default。
- **限制**: 嚴格執行 L1 (主管) -> L2 (執行者) 兩層扁平架構，禁止遞迴。

## 3. 完成標準
- 依賴 Spec A 的 Roster 與 Session State。
- 實現 `Department Head` 的 L1 規劃能力。