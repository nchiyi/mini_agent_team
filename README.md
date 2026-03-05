# 🤖 Telegram-to-Control (Agentic Edition)

這是一個進化版的 Telegram AI Agent 平台，透過 Gemini CLI 與高度模組化的技能系統，將你的 Telegram 變成一個強大的遠端指令中心與自主 AI 助手。

---

## 🚀 核心黑科技 (Core Intelligence)

### 1. 自主思考引擎 (Autonomous Reasoning / ReAct)
Agent 不再只是回答問題，而是具備 **Reason + Act** 循環。它會自動拆解任務、選擇工具、觀察結果，最後給出答案。

### 2. 語義記憶 (Semantic Memory / RAG)
整合 **FAISS 向量資料庫**，Agent 具備長短期記憶能力：
- **長期事實**：自動記住你的喜好與專案背景。
- **智慧檢索**：在回答前自動搜尋相關歷史文獻，提供更精準的 context。

### 3. 瀏覽器眼睛 (Browser Eye)
透過 **Playwright**，Agent 可以開啟瀏覽器看網頁、抓取內容並總結資訊。

---

## 🛠️ 技能與工具 (Skills & Tools)

你可以透過自然語言觸發以下技能，或使用具體的指令：

| 技能名稱 | 指令 (Tools) | 說明 |
| :--- | :--- | :--- |
| **Browser Eye** | `/browse`, `/search` | 瀏覽網頁、Google 搜尋、網頁轉 Markdown。 |
| **Dev Agent** | `/dev` | 核心 Coding 助手，處理開發任務。 |
| **System Monitor** | `/sys` | 查看伺服器 CPU、記憶體、硬碟狀態。 |
| **Usage Monitor** | `/usage`, `/stats` | 查看 API 總用量或詳細對話 Token 紀錄。 |
| **Model Manager** | `/model` | 即時切換 Gemini 模型版本。 |
| **News Fetcher** | `/news` | 抓取全球即時科技與新聞。 |
| **Project Tracker** | `/projects` | 掃描本地 Git 專案狀態。 |
| **Deployer** | `/deploy`, `/install` | 自動部署本地專案或從 GitHub 安裝新東西。 |
| **Installer** | `/install_skill` | 動態下載並載入新的 Python 技能模組。 |

---

## 📦 安裝與啟動

### 1. 快速部署 (互動式腳本)
最簡單的方式是使用我們提供的 `setup.sh`，它會引導你完成連網、認證以及選擇性功能（瀏覽器、向量資料庫）的安裝：

```bash
git clone https://github.com/nchiyi/telegram-to-control.git
cd telegram-to-control
bash setup.sh
```

---

## 📱 管理指令 (CLI Admin)

專案目錄內附帶 `agent` 腳本，方便你管理背景服務：
- `./agent status` - 檢查 Bot 狀態
- `./agent logs` - 查看即時日誌
- `./agent restart` - 重啟服務
- `./agent debug on/off` - 切換詳細除錯日誌

---

## 📄 License
MIT
