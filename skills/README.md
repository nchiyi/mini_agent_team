# 🧩 Skills 系統開發手冊

本目錄存放 Telegram AI Agent 的所有「技能腳本」。每個技能都是一個獨立的 Python 模組，透過 `skills/__init__.py` 自動載入。

---

## 🛠️ 開發規範 (Standards)

為了維持系統的整潔與可維護性，請遵循以下規範：

1.  **檔案命名**：使用蛇形命名法 (snake_case)，例如 `my_new_skill.py`。
2.  **類別定義**：必須繼承 `BaseSkill` 並實作 `handle()` 異步方法。
3.  **屬性規範**：
    *   `name`: 內部識別碼，請使用 **snake_case** (如 `"browser_eye"`)。
    *   `description`: 使用 **繁體中文** 描述功能，會顯示在幫助選單中。
    *   `commands`: 該技能負責的 `/` 指令列表。
    *   `schedule`: (非必填) Cron 表達式，用於執行定時任務。
4.  **錯誤處理**：在 `handle()` 中使用 `try...except` 封裝，返回友善的中文錯誤訊息。

---

## 📚 擴充教學 (Extension Guide)

### 範例代碼
```python
from .base_skill import BaseSkill

class MySkill(BaseSkill):
    name = "my_skill"
    description = "這是一個範例技能"
    commands = ["/hello"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        name = args[0] if args else "陌生人"
        return f"你好, {name}！這是我執行的指令: {command}"
```

### 自動載入機制
系統啟動時會掃描此目錄，只要類別繼承了 `BaseSkill` 且不是 `BaseSkill` 本身，就會自動實例化並註冊到 `Engine` 中。

---

## 🔍 指令索引 (Tool Index)

| 指令 | 技能檔案 | 功能描述 | 外部相依 |
| :--- | :--- | :--- | :--- |
| `/browse`, `/search` | `browser_skill.py` | 網頁瀏覽與搜尋 | `playwright`, `html2text` |
| `/sys` | `system_monitor.py` | 系統狀態監控 | 無 |
| `/usage` | `usage_monitor.py` | API 用量與成本監控 | 無 |
| `/news`, `/subscribe` | `news_fetcher.py` | 新聞搜尋與訂閱 | 無 |
| `/projects`, `/status` | `project_tracker.py` | Git 專案進度追蹤 | `git` (CLI) |
| `/deploy`, `/logs` | `deployer.py` | 專案部署與日誌查看 | 無 |
| `/install_skill` | `skill_installer.py` | 動態安裝新技能模組 | 無 |
| `/dev` | `dev_agent.py` | AI 輔助開發引擎 | 無 |

---

## ⚠️ 相依性說明

部分技能需要額外的系統組件：
- **Browser Eye**: 
  1. `pip install playwright html2text`
  2. `playwright install chromium`
- **Semantic Memory** (Core API):
  1. `pip install faiss-cpu sentence-transformers numpy`

---
