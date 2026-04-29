# mini_agent_team — Project MAGI

> 一個 process 同時駕馭 N 個 Telegram bot、各自綁不同 CLI agent（Claude Code / Codex / Gemini）、私訊安全、群組 opt-in。

> 🇬🇧 **English:** see [README.en.md](README.en.md).

> 📘 **完整使用手冊**：[`docs/user-manual.md`](docs/user-manual.md) — 安裝 / 認證 / 操作 / 命令 / 情境 / 除錯 一站式。

---

## 設計原則（讀我！）

MAT 是「個人 / 小團隊本機助理」場景，不是公開服務。三條核心原則：

1. **預設只接受 1:1 私訊**。所有群組行為（多 bot 在群組共處、bot↔bot 對話、`@all` 風扇出）一律是 opt-in 開關，**預設關閉**。安裝完成後就算被加進群組也不會回應，必須在 `config/config.toml` 為該 bot 明確開啟。
2. **per-bot 隔離**。每個 bot 自己的 token / runner / role / 記憶。同一個 user 在 `dev_bot` 跟 `search_bot` 的對話不會互通；同一個 bot 在 DM 跟群組的對話也不會互通。Memory 用 `(user_id, channel, bot_id, chat_id)` 四元組分桶，端到端隔離。
3. **Legacy 單 bot 安裝零改動相容**。`config.toml` 沒有任何 `[bots.*]` 區塊時自動讀 `TELEGRAM_BOT_TOKEN`，行為完全跟舊版一致。

### 三個群組相關的 opt-in 開關

| 開關 | 預設 | 啟用後的行為 | 風險 |
|------|------|-------------|------|
| `allow_all_groups` | `false` | bot 可在「任何邀請它進的群組」回應；保持 `false` 時必須列入 `allowed_chat_ids` 白名單 | 開啟 = 任何拉它進群組的人都能用它 |
| `allow_bot_messages` | `"off"` | `"mentions"` = 別的 bot 明確 @ 我才回；`"all"` = 看到任何 bot 訊息都評估 | `"all"` 容易觸發 bot↔bot 迴圈（有 turn-cap 兜底）|
| `respond_to_at_all` | `false` | 一句 `@all` / `@大家` / `@everyone` 同時喚醒群組所有 bot 一起回應 | 開啟 = 一句話 fan-out 多個 LLM 呼叫，token 用量倍增 |

---

## 功能總覽（按使用頻率排）

### 個人助理（1:1 私訊，預設可用）

- **自然語言對話** — 直接傳訊息，預設 runner（claude / codex / gemini）即時回覆，串流邊跑邊更新
- **Roster 語義路由** — 用 FastEmbed 把訊息匹配到 `roster/*.md` 的角色，自動切到該專家
- `/use <role>` — 切換到指定 roster 角色（roster slug 對應 `roster/<slug>.md`）
- `/claude` / `/codex` / `/gemini` — 切換當前 runner（也可用 `/<runner> <prompt>` 一次性丟訊息）
- `/discuss <r1,r2,...> <prompt>` — 多 runner 腦力激盪（同一個 session，記憶共用）
- `/debate <r1,r2,...> <prompt>` — 多 runner 對立辯論
- `/relay <r1,r2,...> <prompt>` — 多 runner 串聯接力
- `/remember <text>` — 寫入 Tier 1 永久事實（jsonl）
- `/forget <keyword>` — 刪除 Tier 1 內含 keyword 的事實
- `/recall <query>` — 全文搜尋 Tier 3 對話歷史（FTS5）
- `/new` — 重置當前 session 的對話 context
- `/cancel` — 中斷正在跑的回覆
- `/status` — 系統 / session 狀態
- `/usage` — token 用量統計
- `/voice on` / `/voice off` — 啟用/關閉語音回覆（合成成 audio file 送回）

### 多 bot 共存（B-1，編 config 啟用）

- `[bots.<id>]` 多 bot 設定 — 一個 MAT process 同時服務 N 個 Telegram bot
- per-bot `default_runner` — 每個 bot 預先綁一個 CLI（dev_bot=claude, review_bot=codex, search_bot=gemini）
- per-bot `default_role` — 啟動時自動套用 roster 角色，user 不必每次 `/use`
- per-bot allowlist override — `allowed_user_ids` / `allow_all_users` 可單獨指定（覆蓋全域）
- per-bot `token_env` — 每個 bot 自己的 env var 存 token；secrets/.env 一行一個
- **記憶完全隔離** — `(user_id, channel, bot_id)` 三元組各自獨立 Tier 1 / Tier 3，不同 bot 不互通
- legacy 單 bot 自動 fallback — 沒有 `[bots.*]` 時自動讀 `TELEGRAM_BOT_TOKEN`，舊安裝無痛

### 群組多 bot 協作（B-2，全部 opt-in）

- `allow_all_groups` / `allowed_chat_ids` — 群組白名單；預設只回應指定 chat_id
- `allow_bot_messages = "off" | "mentions" | "all"` — bot↔bot 對話開關
- `trusted_bot_ids` — 進一步把可回應的 bot 限制在白名單
- `respond_to_at_all` — 是否回應 `@all` / `@大家` / `@everyone` 集體召喚
- **bot 迴圈防護** — 每個 `(channel, chat_id)` 連續 bot 訊息上限 10 次（`src/gateway/bot_turns.py`），任何人類訊息把計數歸零
- **群組記憶隔離** — `(user_id, channel, bot_id, chat_id)` 四元組分桶；DM 跟群組分別記
- BotFather Privacy Mode 提示 — 要做自然語言定址需 `/setprivacy → Disable`

### 雙層記憶系統

- **Tier 1（永久事實）** — `data/memory/cold/permanent/*.jsonl`，by `/remember` 寫入或自動 distill 產生
- **Tier 3（對話歷史）** — `data/db/history.db` SQLite + FTS5 全文檢索
- **自動精煉** — 對話超過 `distill_trigger_turns`（預設 20 輪）自動把舊歷史摘要成 Tier 1 事實，避免 context 爆炸
- **語義 fallback**（可選）— `search_mode = "fts5+vector"` 啟用 vector 搜尋

### Roster（角色系統）

- `roster/*.md` frontmatter 註冊角色（slug / name / summary / identity / rules）
- 自然語言訊息經 FastEmbed semantic match 自動路由到匹配的 role
- `/use <slug>` 手動切換
- prompt prefix 注入：role identity + rules 自動拼到 system prompt

### Runner（CLI agent）

- **ACP runner**（預設）— `claude-agent-acp` / `codex-acp` / `gemini --acp --yolo`，JSON-RPC over ndjson 持久 session，回應毫秒級
- **CLI runner** — 傳統 spawn 子程序模式（fallback）
- 自動 OAuth via `mat auth`（docker 模式必跑一次）
- per-runner `timeout_seconds` / `context_token_budget` 可調

### 部署模式

- **foreground** — `python3 main.py`，開發 / 除錯
- **launchd** — macOS 桌機常駐（`~/Library/LaunchAgents/`）
- **systemd** — Linux 伺服器常駐（`systemctl --user`）
- **docker compose** — 跨機器移植，自動掛載 OAuth volume

### 語音（optional）

- **STT**（語音 → 文字） — Groq Whisper 雲端優先；fallback 到本機 `faster-whisper`
- **TTS**（文字 → 語音） — Microsoft Edge TTS（`zh-TW-HsiaoChenNeural` 預設聲線）；fallback 到 gTTS
- 用 `/voice on` 開啟，bot 會把每次回覆同步合成 audio file 一起回送

### Skills（外掛指令）

- `skills/<name>/skill.md` 註冊 manifest
- loader 自動掃描並註冊 slash commands
- 內建：`web_search` / `vision`（`/describe` 圖像辨識）/ `system_monitor`（`/sysinfo`）/ `mcp` / `agency` / `agent_team`

### 認證（白名單）

- **全域白名單** — `secrets/.env` 的 `ALLOWED_USER_IDS`（fail-closed：未設預設拒絕所有人）
- **per-channel override** — `[telegram] allowed_user_ids` / `[discord] allowed_user_ids`
- **per-bot override** — `[bots.<id>] allowed_user_ids` / `allow_all_users`（B-1 新增；最高優先順序）
- **container OAuth** — docker 模式用 `mat auth` 完成 device-flow，token 寫進 named volume 持久化

---

## 快速安裝

### 一鍵安裝（推薦）

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
| 6 | 自動把 `mat` symlink 到 `/usr/local/bin/mat`（會 sudo 一次）|

精靈完成後 bot **已上線**，且 `mat` 指令在任何目錄都能用。

### 手動安裝

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./venv/bin/python3 setup.py
sudo ./mat install-cmd     # 一次性，安裝 mat 全域指令
```

### 設定精靈步驟（mat setup）

| Step | 內容 | 互動 |
|------|------|------|
| 0 | Pre-flight：Python / 磁碟 / 網路 / pkg manager / systemd / Docker | 自動 |
| 1 | Channel Selection — Telegram / Discord / 兩者 | checkbox |
| 2 | Bot Token — 貼上並驗證 | 文字輸入 |
| 3 | Allowlist — 你的 user ID（傳訊息給 bot 自動抓 / Enter 跳過）| 自動 / Enter |
| 4 | CLI Tools — claude / codex / gemini，未裝會自動 npm install | checkbox |
| 4.5 | ACP 協作模式 — orchestrator / multi / both | 單選 |
| 5 | Search Mode — fts5 / fts5+vector | 單選 |
| 6 | Optional Features — Discord 語音 / 瀏覽器技能 / Tavily | checkbox |
| 7 | Update Notifications — 啟動時檢查新 release | y/n |
| 8 | Deploy Mode — foreground / systemd / launchd / docker | 單選 |
| 9 | 寫設定 + 啟動服務 + smoke test | 自動 |

> 多 bot（B-1）/ 群組多 bot（B-2）目前必須手動編 `config/config.toml`，wizard 還不收集（保留為單 bot UX，避免雜訊）。

---

## 設定檔

### `secrets/.env`（敏感資訊，chmod 600）

```env
# Legacy 單 bot
TELEGRAM_BOT_TOKEN=123456789:AABBCC...
DISCORD_BOT_TOKEN=                       # 選填
ALLOWED_USER_IDS=123456789,987654321     # 必填，空白即拒絕所有人
DEFAULT_CWD=/path/to/work/dir            # CLI 子程序的工作目錄
DEBUG_LOG=false

# 多 bot（B-1）— 每個 bot 一行 token env
BOT_DEV_TOKEN=11111:abcdef...
BOT_REVIEW_TOKEN=22222:fedcba...
BOT_SEARCH_TOKEN=33333:ghijkl...

# 選填：語音 STT 雲端
GROQ_API_KEY=
```

### `config/config.toml` — 三個並列範例

#### A. Legacy 單 bot（最常見，預設安裝就是這個）

```toml
[gateway]
default_runner = "claude"
session_idle_minutes = 60
stream_edit_interval_seconds = 1.5

[runners.claude]
type = "acp"
path = "claude-agent-acp"
timeout_seconds = 300

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
distill_trigger_turns = 20
search_mode = "fts5"
```

→ 沒有任何 `[bots.*]`：自動讀 `TELEGRAM_BOT_TOKEN` 起單一 bot。

#### B. 多 bot（B-1）— 三個 bot 各司其職，DM 限定

```toml
[bots.dev]
channel        = "telegram"
token_env      = "BOT_DEV_TOKEN"
default_runner = "claude"
default_role   = "fullstack-dev"
label          = "Dev Assistant"

[bots.review]
channel        = "telegram"
token_env      = "BOT_REVIEW_TOKEN"
default_runner = "codex"
default_role   = "code-auditor"

[bots.search]
channel        = "telegram"
token_env      = "BOT_SEARCH_TOKEN"
default_runner = "gemini"
default_role   = "researcher"
```

→ 三個 bot 同時上線，每個各自記憶獨立。**沒開任何群組欄位 = 只接受 1:1 DM**。

#### C. 群組多 bot（B-2）— 三個 opt-in 全開

```toml
[bots.dev]
channel              = "telegram"
token_env            = "BOT_DEV_TOKEN"
default_runner       = "claude"
default_role         = "fullstack-dev"
# 群組 opt-in
allow_all_groups     = false                  # 白名單模式（推薦）
allowed_chat_ids     = [-1001234567890]       # 你的群組 chat_id（負數）
allow_bot_messages   = "mentions"             # 別的 bot @ 我才回
respond_to_at_all    = true                   # 願意接受 @all 集體呼叫

[bots.review]
channel              = "telegram"
token_env            = "BOT_REVIEW_TOKEN"
default_runner       = "codex"
default_role         = "code-auditor"
allow_all_groups     = false
allowed_chat_ids     = [-1001234567890]
allow_bot_messages   = "mentions"
respond_to_at_all    = true

[bots.search]
channel              = "telegram"
token_env            = "BOT_SEARCH_TOKEN"
default_runner       = "gemini"
default_role         = "researcher"
allow_all_groups     = true                   # search bot 開放任何群組
allow_bot_messages   = "off"                  # 但不跟其他 bot 互動
respond_to_at_all    = true
```

> 三個欄位 `allow_all_groups` / `allow_bot_messages` / `respond_to_at_all` 全部預設關閉；不寫等於不開。

群組 `chat_id` 取得方式：先把 bot 加進群組，發任意一句話，看 `mat logs` 找 `chat_id=` 即可（負數）。

**Telegram BotFather 必做：**自然語言定址需關掉 Privacy Mode：`/setprivacy → 選 bot → Disable`。只用 `@username` 定址不關也行。

---

## 使用情境演示

### Scenario 1：單 bot 個人助理（最常見，預設安裝就能用）

```
你 → @yourname_bot：「寫個 Python 腳本把 csv 轉成 json」
yourname_bot（claude）：[完整程式碼]

你 → @yourname_bot：「改成支援 nested objects」
yourname_bot（claude）：[更新版，session 內記得上一輪]

你 → @yourname_bot：「/remember 我偏好用 dataclasses 不用 dict」
yourname_bot：「Remembered: 我偏好用 dataclasses 不用 dict」

→ 之後所有對話 yourname_bot 都會記得這個偏好（Tier 1 永久事實）
```

### Scenario 2：多 bot 各司其職（B-1，編 config.toml 啟用）

```
情境：你開三個 bot，每個綁一個 CLI 跟一個 role
- @dev_bot     → claude  + fullstack-dev
- @review_bot  → codex   + code-auditor
- @search_bot  → gemini  + researcher

你 → @dev_bot：「寫個 GraphQL resolver fetch user with posts」
dev_bot（claude）：[程式碼，帶潛在 N+1 問題]

你 → @review_bot：「[貼上 dev_bot 的程式碼] 看看有什麼問題」
review_bot（codex）：「N+1 query：每個 user 拉 posts 都另開 query。
                      建議用 DataLoader 做 batching…」

你 → @search_bot：「GraphQL DataLoader 跟 batching pattern 比較」
search_bot（gemini）：[研究結果，引用文件連結]

→ 三個 bot 各自記憶獨立。dev_bot 不會看到你跟 search_bot 說過什麼，
  反之亦然。memory 用 (user_id, channel, bot_id) 三元組分桶。
```

### Scenario 3：DM 內多 runner 辯論（/discuss，預設可用）

```
你 → @yourname_bot：「/discuss claude,codex,gemini Postgres 跟 SQLite 哪個適合多人協作的小工具？」

yourname_bot（claude）：「[論點 A：Postgres 並發處理較好…]」
yourname_bot（codex）：「[反駁 + 論點 B：SQLite WAL 模式對小團隊已足夠…]」
yourname_bot（gemini）：「[第三方視角 C：取決於部署複雜度…]」

→ 一個 bot session 內三個 runner 接力，記憶共用。
  /debate 改用對立辯論模式；/relay 改用串聯接力。
```

### Scenario 4：群組三 bot 同房（B-2，需 opt-in 三個開關）

```
前置設定（config.toml 每個 bot 都要開）：
  allow_all_groups   = false
  allowed_chat_ids   = [-1001234567890]
  allow_bot_messages = "mentions"     # 只有別的 bot @ 我才回
  respond_to_at_all  = true           # 接受 @all 集體呼叫

群組對話（你 + dev_bot + review_bot + search_bot 都在）：

你：「@dev_bot 寫個快取裝飾器」
dev_bot（claude）：[程式碼]

你：「@review_bot 你覺得呢？」
review_bot（codex）：「TTL 沒做、cache key 沒處理 mutable args、
                      thread-safe 也沒考慮…」

你：「@all 那大家覺得用 Python 內建 functools.lru_cache 夠不夠？」
dev_bot（claude）：「[小工具場景夠用，但…]」
review_bot（codex）：「[lru_cache 不能 invalidate 單一 key…]」
search_bot（gemini）：「[研究：cachetools / diskcache 何時該換…]」

→ 防迴圈：三個 bot 連續互回 10 輪會自動沉默，等下一個人類訊息才解封。
→ 群組記憶 (user_id, channel, bot_id, chat_id) 四元組獨立；
  你在 DM 跟 dev_bot 講的內容不會洩漏到群組。
```

### Scenario 5：語音輸入 + 跨平台（optional）

```
前置：secrets/.env 設好 GROQ_API_KEY，bot 訊息打 /voice on

你 → @yourname_bot：[傳語音訊息「明天提醒我跑壓力測試」]
yourname_bot：「[Transcribed]: 明天提醒我跑壓力測試」
yourname_bot（claude）：「好的，已記住明天要跑壓力測試…」
                        + [audio file 同步合成回傳]

→ STT 走 Groq Whisper 雲端優先，沒設 GROQ_API_KEY 時 fallback 到本機
  faster-whisper。TTS 用 Edge TTS 預設聲線 zh-TW-HsiaoChenNeural。
→ /voice off 關掉後 bot 只回文字。
```

---

## 認證 CLI agents（docker 模式必跑一次）

Docker 模式下 bot 跑在隔離的容器內，不能直接讀宿主的 OAuth 憑證（特別是 macOS 把 Claude Code 憑證存在 Keychain，**不是檔案**，無論怎麼 mount 都拿不到）。

解法：**容器內走一次 device-flow OAuth**，token 寫進 docker named volume `mat-agent-home` 持久化，跨重啟跟 image 重 build 都不會丟。

### 一行完成

```bash
mat auth        # 互動選單，依序登入 claude / codex / gemini
```

### 個別登入

```bash
mat auth claude     # → docker compose exec -it gateway claude setup-token
mat auth codex      # → docker compose exec -it gateway codex login --device-auth
mat auth gemini     # → docker compose exec -it gateway gemini  (互動模式)
mat auth all        # 依序跑全部
```

各 CLI 認證機制（依實際 CLI 行為驗證過）：

| CLI | 認證流程 |
|-----|---------|
| claude | `claude setup-token` 印一個 URL，瀏覽器登入後 paste token 回 terminal |
| codex | `codex login --device-auth` 印 URL + 短 code，手機開 URL 輸入 code 即可（**不能用裸 `codex login`** — 那會啟動 localhost browser flow，container 網路名空間不通）|
| gemini | gemini-cli 沒獨立 `login` 子指令，認證內建在主程式啟動時。`mat auth gemini` 在容器內互動跑 `gemini`，第一次啟動會跳 Google OAuth；完成後 `/quit` 或 Ctrl-D 結束 |

### 確認哪些已認證

```bash
mat auth status

# 範例輸出：
# 📋  Auth status (/root inside container):
#   ✓ .claude (4 files)
#   ✓ .codex (10 files)
#   ✗ .gemini (empty / not authenticated)
```

### 切換 token / 完全清掉

```bash
mat auth <cli>           # 直接重跑覆蓋舊 token
docker compose down -v   # -v 連 named volume 一起刪
mat start && mat auth    # 重新認證
```

---

## 日常操作（全部用 `mat`）

`mat` 是唯一的使用者面向指令，會根據 `data/setup-state.json` 的 `deploy_mode` 自動 dispatch 到對應後端（docker / launchd / systemd）。

### 生命週期

```bash
mat start                  # 啟動 bot
mat stop                   # 停止
mat restart                # 重啟
mat status                 # 查看執行狀態
mat run                    # 前景執行（除錯用，繞過 backend）
```

### 日誌

```bash
mat logs                   # 即時 tail -f（Ctrl-C 離開）
mat logs 100               # 最後 100 行
mat logs grep "telegram"   # 只顯示包含 telegram 的行
mat logs error             # 只看 error / exception / traceback
mat logs today             # 只看今天的訊息
mat debug on               # 開啟詳細除錯日誌（會自動重啟）
mat debug off              # 關閉
```

### 設定 / 維護

```bash
mat config                 # 修改 Token / 白名單（會自動重啟）
mat setup                  # 重跑設定精靈（保留現有設定，只改要改的）
mat update                 # git pull + 重啟（docker 模式則重 build）
mat mode                   # 顯示目前 deploy_mode（除錯用）
```

### Service unit（launchd / systemd 模式才需要）

```bash
mat service-install        # 寫入並載入 launchd plist 或 systemd unit
mat service-uninstall      # 卸載
```

Docker 模式下這兩個會印「不適用」訊息（container 本身就是 daemon）。

### Backend 對照表（mat 內部如何 dispatch）

| `mat` 指令 | `docker` 模式 | `launchd` / `systemd` 模式 |
|-----------|---------------|---------------------------|
| `start` | `docker compose up -d` | `./agent start` |
| `stop` | `docker compose down` | `./agent stop` |
| `restart` | `docker compose restart` | `./agent restart` |
| `status` | `docker compose ps` | `./agent status` |
| `logs` | `docker compose logs -f gateway` | `tail -f data/bot.log` |
| `update` | `git pull` + `docker compose up -d --build` | `git pull` + `./agent restart` |
| `run` | venv 直接跑 main.py（繞過 docker，純前景）| 同 |
| `config` | 編輯 secrets/.env 後重啟 | 同 |

---

## 客製化

### 新增 Roster 角色

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

重啟 bot 後即可用 `/use data-scientist` 切換，或讓自然語言路由自動匹配。

### 新增 Skill（外掛指令）

在 `skills/<name>/skill.md` 寫 manifest，loader 會自動掃描並註冊 slash command。參考 `skills/web_search/`、`skills/vision/` 既有實作。

---

## 疑難排解

### Telegram 409 Conflict

> `Conflict: terminated by other getUpdates request`

代表同一個 token 有兩個 instance 在 polling。常見原因：
- 同台機器有 launchd / Docker / `python main.py` 同時跑（setup wizard 開頭會自動偵測並請你停舊的）
- **不同機器共用同一個 token**（例如 Mac 跟 Linux 都跑同一個 bot）— 換 token 是唯一解

### 群組裡 bot 不回應？

按以下順序檢查：

1. `allow_all_groups` 是否 `true`，或 `allowed_chat_ids` 是否包含當前 chat_id（`mat logs` 找 `chat_id=`，記得是負數）
2. BotFather Privacy Mode 是否關閉（自然語言定址需關；只用 `@username` 不必）
3. ALLOWED_USER_IDS（或 per-bot override）是否包含說話者的 user_id
4. 看 `mat logs error` 是否有 dispatch 失敗

### `@all` / `@大家` / `@everyone` 沒人回？

所有 bot 的 `respond_to_at_all` 預設是 `false`，**需要逐一在 `[bots.<id>]` 加 `respond_to_at_all = true`**。任何一個沒設的 bot 不會被 `@all` 喚醒。

### bot↔bot 訊息互相無視？

`allow_bot_messages` 預設 `"off"`。要讓 bot 互相對話需改成 `"mentions"`（被 @ 才回，較安全）或 `"all"`（全收，靠 turn-cap 兜底）。注意：兩個 bot 都設 `"all"` 容易快速吃掉 turn-cap，10 輪後會自動沉默。

### Bot 回 "An error occurred. Please try again." 或卡在 typing

Bot 收到訊息（你會看到 typing indicator），但 dispatch 後 ACP runner 失敗。常見原因（按可能性）：

1. **沒跑 `mat auth`**（最常見）— 容器內 CLI 無 OAuth credential。`mat logs error` 會看到 `'code': -32000, 'message': 'Authentication required'`。修法：`mat auth`。
2. **runner 路徑錯誤** — `[runners.X].path` 應指 ACP wrapper（`claude-agent-acp` / `codex-acp` / `gemini`），不是裸 CLI。`mat setup` 會用正確 template 重寫。
3. **沒重 build 容器** — 改 wizard 設定後要 `mat update` 或 `docker compose up -d --build`。
4. **CLAUDE_CODE_EXECUTABLE 沒設**（已修）— 沒設此 env，claude-agent-acp 會用 bundled SDK cli.js 而忽略安裝的 claude binary。新版 Dockerfile 已自動設好，舊 image 重 build 即可。

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
│   ├── channels/          # Telegram / Discord adapter, telegram_runner
│   ├── core/              # 設定、日誌、bots.py（多 bot）、雙層記憶
│   ├── gateway/           # router、role_router、session、bot_turns、bot_registry
│   ├── runners/           # ACP runner、CLI runner、JSON-RPC 協議
│   ├── setup/             # 精靈、preflight、smoke_test、deploy
│   └── voice/             # STT (Groq/whisper) / TTS (edge-tts/gtts)
├── skills/                # 內建 skill：web_search / vision / mcp / agency / ...
├── requirements.txt       # Python 依賴（pip-compile lock）
├── data/                  # 執行時：DB、log、memory（.gitignore）
├── secrets/               # token / .env（.gitignore）
└── config/                # config.toml + config.toml.example
```

---

## 安全備忘

- **白名單預設關閉**（fail-closed）：未設 `ALLOWED_USER_IDS` 拒絕所有訊息
- **群組相關全部 opt-in**：`allow_all_groups` / `allow_bot_messages` / `respond_to_at_all` 三個欄位預設 `false` / `"off"` / `false`
- **記憶嚴格隔離**：以 `(user_id, channel, bot_id, chat_id)` 四元組分桶，跨 user / 跨 bot / 跨 DM-vs-群組 都看不到彼此資料
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
