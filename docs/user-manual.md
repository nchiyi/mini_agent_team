# MAT 使用手冊

> 給自架 MAT 的 power user。安裝、認證、操作、對話、除錯一站式。
>
> 適合：已經有 GitHub / Docker / 終端機基礎，想跑自己的 Telegram/Discord bot 串接 Claude / Codex / Gemini 的人。
>
> 本檔範例值（如 `@nchiyi01bot`、`user_id=8359434933`、`chat_id=-1001234567890`、`BOT_DEV_TOKEN=...`）皆為示範用途，實際請替換成自己的值。

## 目錄

- [1. 系統需求與架構速覽](#1-系統需求與架構速覽)
- [2. 安裝](#2-安裝)
- [3. 第一次認證 CLI agents（必讀）](#3-第一次認證-cli-agents必讀)
- [4. 日常操作](#4-日常操作)
- [5. 對話命令參考](#5-對話命令參考)
- [6. 設定檔解說](#6-設定檔解說)
- [7. 使用情境](#7-使用情境)
- [8. 除錯指南](#8-除錯指南)
- [9. 升級流程](#9-升級流程)
- [10. FAQ](#10-faq)
- [11. 進階主題](#11-進階主題)
- [12. 給開發者](#12-給開發者)

---

## 1. 系統需求與架構速覽

### 1.1 主機需求

| 項目 | 最低 | 建議 |
|------|------|------|
| OS | macOS 13+ / Ubuntu 22.04+ / Debian 12+ | macOS 14+ / Ubuntu 24.04 |
| Python | 3.11 | 3.12 或 3.13 |
| Docker | 24.0（docker 模式才需要） | 27+ |
| Node.js | 20 LTS（ACP wrapper 才需要） | 22 LTS |
| 磁碟 / RAM | 2 GB / 1 GB free | 5 GB / 2 GB |

### 1.2 架構速覽

```
Telegram / Discord adapter
        ▼
gateway/dispatcher.py  (router + nlu + rate_limit + session + streaming)
        ▼
runners/ACPRunner | CLIRunner  →  claude / codex / gemini
        ▼
Memory: Tier1 (jsonl 永久事實) + Tier3 (SQLite + FTS5 對話歷史)
```

### 1.3 為什麼要 Docker

Docker 模式下，gateway process 與 Claude / Codex / Gemini CLI 都跑在 container 內：CLI agent 跟 host 隔離、OAuth credential 寫進 named volume `mat-agent-home`（跨 image rebuild 持久化）、升級用 `docker compose up -d --build` 一鍵替換。代價：第一次跑必須在 container 內重新做一次 OAuth（host 的 Keychain 進不去 container），詳見 §3。

### 1.4 部署模式比較

| 模式 | 適用 | 啟動方式 | 缺點 |
|------|------|---------|------|
| `docker` | macOS / Linux 單機，**最穩**、隔離度高 | `mat start` | 容器內要另外 auth |
| `foreground` | 開發 / 排查 | `mat run`（前景） | 關終端機就掛 |
| `launchd` | macOS 永續 | `mat service-install` | 重啟可能要重 auth |
| `systemd` | Linux 永續 | `mat service-install` | 同上 |

部署模式儲存在 `data/setup-state.json` 的 `deploy_mode` 欄位，由 `mat setup` 互動式 wizard 選擇。`mat mode` 可印出當前模式。

---

## 2. 安裝

### 2.1 一鍵安裝（推薦）

```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

這個指令會：

1. 在當前目錄 `git clone` 到 `mini_agent_team/`。
2. 找到合適的 `python3.11+`（自動探 Homebrew、pyenv、`/usr/local/bin`）。
3. 建 venv、裝 `requirements.txt`。
4. 跑互動式 wizard（`setup.py`）讓你選 deploy mode、貼 token、設白名單。

注意：不可在 `mini_agent_team/` 內再次執行 install.sh（會被 guard 擋下）。

### 2.2 手動安裝（需要客製時）

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config/config.toml.example config/config.toml
cp .env.example secrets/.env
# 接著手動編輯 config/config.toml + secrets/.env
mat install-cmd       # 把 mat 註冊到 /usr/local/bin
```

### 2.3 Docker 模式特有步驟

選 docker 模式後 wizard 會自動幫你產生 `docker-compose.yml` + `Dockerfile`（產出後可在 repo 根目錄看到）。第一次啟動：

```bash
mat start            # docker compose up -d
mat status           # 確認 gateway container 是 running
mat logs 50          # 看最後 50 行 log
```

注意：image build 內含 Python deps + Claude / Codex / Gemini CLI 的 Node 套件，第一次建可能要 5-10 分鐘。

---

## 3. 第一次認證 CLI agents（**必讀**）

這節是踩坑歸納，請務必照做。

### 3.1 為什麼 Docker 模式要在 container 內認證

Claude Code、Codex、Gemini CLI 各有自己的 OAuth flow。在 host 跑這些 CLI 時，token 寫進：

- macOS：`~/Library/Keychain` 或 `~/.claude/`、`~/.codex/`、`~/.gemini/`
- Linux：`~/.claude/`、`~/.codex/`、`~/.gemini/`

但 container 是獨立 user namespace、看不到 host 的 home。所以：

> Host 已經登入 Claude Code，**container 內仍然沒有 token**。

解法：在 container 內再走一次 device-flow OAuth。token 會落到 named volume `mat-agent-home`（mount 到 `/root/`），跨重啟、跨 image rebuild 持久化。

### 3.2 各 CLI 認證方式

#### 3.2.1 Claude Code

```bash
mat auth claude
```

實際執行：`docker compose exec -it gateway claude setup-token`

流程：

1. 終端機印出 URL + device code。
2. 用瀏覽器開那個 URL、登入 Anthropic 帳號、貼 code。
3. 瀏覽器顯示 `OAuth token: sk-ant-oat01-XXXX...`。
4. **手動把 token 貼進 `secrets/.env` 的 `CLAUDE_CODE_OAUTH_TOKEN=`**。
5. `mat restart` 讓 container 重讀 .env。

驗證：

```bash
docker compose exec -T gateway sh -c 'env | grep CLAUDE_CODE_OAUTH'
# 應看到：CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

> ⚠️ **常見踩雷**：用 `>>` 把 token 補進 .env 並非永遠有效。詳見 §3.4。

#### 3.2.2 Codex

```bash
mat auth codex
```

實際執行：`docker compose exec -it gateway codex login --device-auth`

流程：device-flow（同上），但 token 會自己寫進 container 內 `/root/.codex/auth.json`，**不需要動 .env**。

驗證：

```bash
mat auth status
# 預期看到：✓ .codex (1 files)
```

#### 3.2.3 Gemini

```bash
mat auth gemini
```

實際執行：`docker compose exec -it gateway gemini`

Gemini CLI 沒有獨立 `login` 子命令。第一次互動式啟動會觸發 OAuth 選單：

1. 選 `Login with Google`（或設 `GEMINI_API_KEY`）。
2. 瀏覽器開啟 Google OAuth 頁面授權。
3. 終端機看到 `Authentication successful` → `Ctrl-D` 或輸入 `/quit` 離開。

token 寫進 `/root/.gemini/oauth_creds.json`，效期一年。

### 3.3 確認認證成功

到 Telegram 對你的 bot（例如 `@nchiyi01bot`）送一則 `hi`：

| Bot 回應 | 意義 |
|----------|------|
| 正常文字回覆（如 "Hello! How can I help?"） | 認證 OK ✅ |
| `An error occurred. Please try again.` | 認證失敗。看 §3.4 + §8.1 |
| `Unauthorized.` | `ALLOWED_USER_IDS` 沒設或不含你的 user_id。看 §8.1.2 |
| 完全無反應（連 typing indicator 都沒） | Telegram 連線問題。看 §8.2 |

### 3.4 認證踩雷實錄

| 症狀 | 原因 | 修法 |
|------|------|------|
| `~/.claude/credentials.json` 是 0 bytes | Device-flow URL 沒走完，token 沒寫入 | 重跑 `mat auth claude`，OAuth 完成才退出 |
| `mat auth claude` 完成後 .env 仍沒看到 token | shell 用 `>>` redirect 把 export 結果塞進 .env，但 export 沒輸出 | 用編輯器 `nano secrets/.env` 手動貼 token |
| `export CLAUDE_CODE_OAUTH_TOKEN=...` 在 host shell 跑，container 看不到 | env var 只在 host shell process，container 從 `secrets/.env` 讀 | 把它寫進 `secrets/.env` 然後 `mat restart` |
| Bot 用了一週突然 `An error occurred` | token 過期 | 重跑 `mat auth <claude\|codex\|gemini>` |

> **關鍵反模式**：`echo "CLAUDE_CODE_OAUTH_TOKEN=$X" >> secrets/.env`
>
> 如果 `$X` 是空的（例如 device-flow 沒走完）這條會寫入空值。`load_dotenv()` 讀到空字串覆蓋掉之前的值，container 認證再次失敗。
>
> **正確做法**：用編輯器（`nano` / `vim` / VSCode）開 `secrets/.env`，貼上完整 token，存檔，`mat restart`。

### 3.5 認證持久化

| CLI | Token 位置 | 持久化方式 | 過期 |
|-----|-----------|-----------|------|
| claude | `secrets/.env` 的 `CLAUDE_CODE_OAUTH_TOKEN` | host bind mount | 約 10 天～30 天 |
| codex | `/root/.codex/auth.json`（container 內） | named volume `mat-agent-home` | 約 30 天 |
| gemini | `/root/.gemini/oauth_creds.json`（container 內） | named volume | 約 1 年 |

`docker compose down` 不會刪 named volume；`docker compose down -v` 才會。重 build image（`mat update`）也保留 volume。

---

## 4. 日常操作

### 4.1 `mat` 命令完整清單

`mat` 是個 dispatcher，依 `data/setup-state.json` 的 `deploy_mode` 自動選 docker / agent backend。

#### 生命週期

| 命令 | 說明 | 範例 |
|------|------|------|
| `mat start` | 啟動 bot（docker 模式 = `docker compose up -d`；其他 = launchctl/systemctl 啟動 service） | `mat start` |
| `mat stop` | 停止 bot | `mat stop` |
| `mat restart` | 重啟（讀新的 .env / config） | `mat restart` |
| `mat status` | 看 container / service 狀態 | `mat status` |
| `mat run` | 前景執行（用 host venv 跑 main.py，繞過 backend）；除錯用 | `mat run` |

#### 日誌

| 命令 | 說明 | 範例 |
|------|------|------|
| `mat logs` | 即時 tail（Ctrl-C 離開） | `mat logs` |
| `mat logs <N>` | 印最後 N 行 | `mat logs 200` |
| `mat logs grep <pat>` | 過濾關鍵字 | `mat logs grep "Authentication"` |
| `mat logs error` | 只看錯誤訊息 | `mat logs error` |
| `mat logs today` | 只看今天的訊息 | `mat logs today` |
| `mat debug on` | 切換 `DEBUG_LOG=true` 並重啟 | `mat debug on` |
| `mat debug off` | 切換 `DEBUG_LOG=false` 並重啟 | `mat debug off` |

> 即時 follow 模式（`mat logs` 不帶參數）目前用 `docker compose logs -f`。如果發現某些 log 沒及時出現，可改用 `mat logs 100` 重抓最後 100 行。

#### 設定 / 維護

| 命令 | 說明 | 範例 |
|------|------|------|
| `mat setup` | 第一次設定或重新跑 wizard | `mat setup` |
| `mat setup --reset` | 清掉 setup state 從頭跑 | `mat setup --reset` |
| `mat config` | 改 Telegram / Discord token、白名單 | `mat config` |
| `mat update` | `git pull` + 重啟 / 重 build | `mat update` |
| `mat mode` | 印出目前 deploy mode + backend | `mat mode` |

#### CLI agent OAuth（docker 模式必跑一次）

| 命令 | 說明 |
|------|------|
| `mat auth` | 互動選單 |
| `mat auth claude` | 認證 Claude Code（device-flow） |
| `mat auth codex` | 認證 Codex（device-flow） |
| `mat auth gemini` | 互動式啟動 gemini，OAuth 完成後 `/quit` |
| `mat auth all` | 依序跑全部 |
| `mat auth status` | 查看哪些 CLI 已認證 |

#### Service unit（launchd / systemd 模式）

| 命令 | 說明 |
|------|------|
| `mat service-install` | 建立並載入 service（macOS = LaunchAgent；Linux = systemd unit） |
| `mat service-uninstall` | 卸載 service |

#### 全域指令

| 命令 | 說明 |
|------|------|
| `mat install-cmd` | symlink mat 到 `/usr/local/bin`（一次性） |

### 4.2 升級 — rebuild 還是 restart？

| 改了什麼 | 該做什麼 |
|---------|---------|
| `config/config.toml`、`secrets/.env`、`roster/*.md`、`skills/*.py` | `mat restart` |
| `requirements.txt`、`Dockerfile`、CLI 版本 | `mat update`（docker 會 rebuild image） |
| 完全重來（保留 volume） | `mat stop && mat start` |
| 完全重來（連認證也清掉） | `docker compose down -v && mat start && mat auth all` |

---

## 5. 對話命令參考

### 5.1 自然語言路由（NLU fast path）

`src/gateway/nlu.py` 在 slash 命令之前先看訊息有沒有以下關鍵字。命中就會直接走多 runner 模式，不需要 `/discuss` 等開頭。

| 關鍵字（中／英） | 觸發模式 | 條件 |
|------------------|---------|------|
| `接力`、`relay`、`chain`、`one after another` | pipeline | 同句出現 ≥2 個 runner 名 |
| `討論`、`discuss`、`對話`、`conversation between` | discussion（3 輪） | 同句出現 ≥2 個 runner 名 |
| `辯論`、`debate`、`argue`、`比較`、`誰比較好` | debate | 同句出現 ≥2 個 runner 名 |
| `深入分析`、`仔細想`、`step by step`、`reason through` | reasoning（會先問 y/n） | 任何長度的問題 |

Runner 別名：

- `claude` ↔ `claude code`、`claude-code`
- `codex` ↔ `openai`
- `gemini` ↔ `google`

範例：

```
> 請 claude 跟 gemini 討論一下要怎麼設計快取層
[Round 1 — CLAUDE] thinking...
[Round 1 — CLAUDE] (回應)
[Round 2 — GEMINI] thinking...
[Round 2 — GEMINI] (回應)
[Round 3 — CLAUDE] thinking...
[CONCLUSION] (synthesis)
```

### 5.2 Slash 命令完整清單

按 `src/gateway/router.py` 列。所有命令在 DM 都有效；群組則需 `@<bot>` mention 觸發。

#### 5.2.1 控制類

| 命令 | 行為 | Bot 回應 |
|------|------|---------|
| `/cancel` | 中斷正在跑的回覆 | `No active task to cancel.` |
| `/status` | 印 runner / context tokens / turns / modules / role / cwd / auth | `Runner: claude\nContext: 1245/4000 tokens\nTurns: 12\n...` |
| `/reset` | 清掉當前 session 的 active role（記憶不動） | `Context cleared.` |
| `/new` | 開新 session（同 `/reset`，語意更清楚） | `New session started.` |
| `/usage` | 印 daily / weekly token budget + 各 runner 累計 | `今日已用：12,450 / 200,000 tokens (6.2%)\n...` |

#### 5.2.2 Runner 切換

##### `/use <runner>`

切換當前 session 的 runner（後續訊息都走這個 runner）。

```
你: /use codex
bot: Switched to codex
```

##### `/<runner> <prompt>`

一次性丟訊息給指定 runner（不改 session 預設）。

```
你: /codex 寫一個 Python 函數計算費氏數列
bot: (Codex 回覆 …)
你: 然後呢                      ← 這條回到原本 runner
bot: (預設 runner 回覆 …)
```

#### 5.2.3 多 runner 協作

##### `/discuss <r1,r2,...>[,rounds=N] <prompt>`

多 runner 接力討論，預設 3 輪、上限 6。最後會由最後一個 runner 做 synthesis。

```
你: /discuss claude,gemini,rounds=4 設計一個 rate-limit 演算法
bot: [Round 1 — CLAUDE] thinking...
bot: [Round 1 — CLAUDE] Token bucket 是經典選擇 …
bot: [Round 2 — GEMINI] thinking...
bot: [Round 2 — GEMINI] 補充一下 sliding window …
bot: …
bot: [SYNTHESIS — GEMINI] summarising...
bot: [CONCLUSION] (整合結論 …)
```

##### `/debate <r1,r2,...> <prompt>`

票選式辯論：每個 runner 出一個答案，然後互相投票選出 winner。

```
你: /debate claude,codex,gemini Python vs Rust for CLI tools?
bot: [DEBATE] CLAUDE vs CODEX vs GEMINI
bot: [A] CLAUDE\n(回答)
bot: [B] CODEX\n(回答)
bot: [C] GEMINI\n(回答)
bot: [VOTING] Each runner casting vote...
bot: [CLAUDE votes B] (理由)
bot: [CODEX votes B] (理由)
bot: [GEMINI votes A] (理由)
bot: [RESULT] Winner: CODEX (2/3 votes)
```

##### `/relay <r1,r2,...> <prompt>`

pipeline 接力：前一個 runner 的輸出當下一個 runner 的輸入，最多 4 輪。

```
你: /relay claude,codex 幫我寫個排序演算法，然後請 codex 補測試
bot: [CLAUDE →] processing...
bot: [CLAUDE →] (sort 函數)
bot: [CODEX →→] processing...
bot: [CODEX →→] (補上 unit test)
```

#### 5.2.4 記憶類

##### `/remember <text>`

寫入 Tier 1 永久事實（jsonl）。隔離鍵 `(user_id, channel, bot_id, chat_id)`。

```
你: /remember 我用 zsh + oh-my-zsh，主機叫 kiwi
bot: Remembered: 我用 zsh + oh-my-zsh，主機叫 kiwi
```

##### `/forget <keyword>`

刪除 Tier 1 內含 keyword 的事實。

```
你: /forget zsh
bot: Removed 1 entries matching 'zsh'
```

##### `/recall <query>`

全文搜尋 Tier 3 對話歷史（FTS5），最多 5 筆。

```
你: /recall 排序
bot: USER: 幫我寫個排序演算法
     ASSISTANT: (sort 函數 …)
     USER: /relay claude,codex 幫我寫個排序演算法 …
```

#### 5.2.5 語音

##### `/voice on` / `/voice off`

啟用 / 關閉語音回覆（合成成 audio file 送回 Telegram）。

```
你: /voice on
bot: Voice replies enabled. Send a voice message or text to try.
```

#### 5.2.6 Skill 命令（動態）

`skills/<name>/manifest.json` 可註冊 slash 命令。`router.py` 會先看 runner、再看 skill registry。例如裝了 `web_search` skill：

```
你: /search MAT 多 bot 架構
bot: (web_search skill 回應 …)
```

完整命令列表用 `/status`，行末 `Modules:` 就是當前可用的 skill 列表。

### 5.3 攻擊面提示（給 power user）

- **Roster / skill 注入 prompt prefix**：每次 dispatch，`apply_role_prompt()` 會把 `roster/<slug>.md` 的內容當 prefix 塞進 prompt。如果你修改 roster 檔案，新 prompt 會立刻生效（`_role_prompt_cache` 比對 mtime）。
- **不要把 secret 寫進 `config/config.toml`**：這檔案不在 git ignore（除了 example 版本）。secret 一律放 `secrets/.env`。
- **`--dangerously-skip-permissions`、`--full-auto`、`--yolo`** 這類 runner args 會讓 CLI 直接幫你 `rm -rf`、寫檔、跑指令而不問。`config.py` 在 startup 會 log warning，但不會擋。請只在受信任的訊息來源啟用。
- **`allow_all_users = true`** 會讓 bot 接受任何人的訊息。除非你在搞公開 demo，否則不要開。

---

## 6. 設定檔解說

### 6.1 `secrets/.env`

| 變數 | 必要 | 說明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | legacy 單 bot 模式必填 | 主 bot 的 token；無 `[bots.*]` 時走這個 |
| `BOT_<ID>_TOKEN` | 多 bot 模式必填 | 例：`BOT_DEV_TOKEN=123:abc...`，對應 `[bots.dev]` |
| `DISCORD_BOT_TOKEN` | 用 Discord 才填 | Discord bot token |
| `ALLOWED_USER_IDS` | 強烈建議 | 逗號分隔的 user id 白名單。範例：`8359434933,123456789` |
| `ALLOW_ALL_USERS` | 不建議 | `true` 會讓 bot 接受所有人訊息 |
| `DEFAULT_CWD` | 建議 | runner 的工作目錄；預設 `$HOME` |
| `CLAUDE_CODE_OAUTH_TOKEN` | docker 模式 + claude runner 必填 | 從 `mat auth claude` 拿到的 token |
| `GEMINI_API_KEY` | 可選 | 設了就略過 OAuth |
| `DEBUG_LOG` | 可選 | `true` 會印更多 log；用 `mat debug on` 切換 |
| `OLLAMA_BASE_URL` | 可選 | 自架 Ollama 用 |

範例：

```env
TELEGRAM_BOT_TOKEN=8359434933:AAH-example-token
ALLOWED_USER_IDS=8359434933
DEFAULT_CWD=/home/kiwi
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-example-token
# 多 bot 模式才需要：
BOT_DEV_TOKEN=...
BOT_SEARCH_TOKEN=...
```

### 6.2 `config/config.toml`

#### `[gateway]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `default_runner` | str | `"claude"` | 沒指定 runner 時走這個 |
| `session_idle_minutes` | int | `60` | session 閒置多久就丟 |
| `max_message_length_telegram` | int | `4096` | Telegram 訊息字數上限（會自動切多則） |
| `max_message_length_discord` | int | `2000` | Discord 同上 |
| `stream_edit_interval_seconds` | float | `1.5` | streaming 模式下多久 edit 一次訊息 |
| `allow_all_users` | bool | `false` | 同 `.env` 的 `ALLOW_ALL_USERS` |

#### `[gateway.rate_limit]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `enabled` | bool | `true` | 整個 rate limit 開關 |
| `per_user_per_minute` | int | `10` | 每用戶每分鐘最多幾條 |
| `burst` | int | `3` | 短時 burst |
| `max_concurrent_dispatches` | int | `5` | 同時最多幾個 runner 在跑 |
| `daily_token_budget` | int | `0`（無上限） | 例：`200000` 約 ~$1/day（Sonnet） |
| `weekly_token_budget` | int | `0` | 同上 |
| `warn_threshold` | float | `0.8` | 用到 80% 就警告 |
| `hard_stop_at_limit` | bool | `false` | `true` = 滿了拒收；`false` = 警告但放行 |

#### `[runners.<name>]`

每個 runner（claude / codex / gemini，也可加自訂）：

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `path` | str | `"claude"` | binary 路徑或 PATH 上的名字 |
| `args` | list[str] | `[]` | 啟動參數；`[]` 表示用 ACP 預設 |
| `timeout_seconds` | int | `300` | 單次 dispatch 超時 |
| `context_token_budget` | int | `4000` | context window 上限（用於 ContextAssembler 截斷） |
| `type` | str | `"acp"` | `"acp"` 或 `"cli"` |

ACP 模式特性：subprocess 持久化（不每次 cold start）、多 user session 隔離、串流逐 chunk 回。

#### `[memory]`

| 欄位 | 型別 | 說明 |
|------|------|------|
| `db_path` | str | SQLite 位置（Tier 3 + FTS5） |
| `hot_path` | str | hot cache 目錄 |
| `cold_permanent_path` | str | Tier 1 jsonl 位置 |
| `cold_session_path` | str | session 級冷儲存 |
| `tier3_context_turns` | int | context 組裝時最多回顧幾輪 |
| `distill_trigger_turns` | int | 對話超過幾輪自動 distill 進 Tier 1 |

#### `[telegram]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `allowed_user_ids` | list[int]\|None | None（用 global） | 整個 telegram channel 的白名單覆寫 |
| `allow_all_users` | bool\|None | None | 整個 telegram 開放（不建議） |

#### `[discord]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `allowed_channel_ids` | list[int] | `[]`（全 channel） | 限制只在這些 channel 回 |
| `allow_user_messages` | str | `"all"` | `"off"` / `"mentions"` / `"all"` |
| `allow_bot_messages` | str | `"off"` | 同上；控制是否處理 bot 來訊 |
| `trusted_bot_ids` | list[int] | `[]`（全部信任） | 配合 `allow_bot_messages != off`，限制只接受這些 bot |
| `allowed_user_ids` | list[int]\|None | None | discord channel 白名單覆寫 |
| `allow_all_users` | bool\|None | None | discord 開放 |

#### `[bots.<id>]`（多 bot）

每個 bot 一個 section。`<id>` 任意（建議短英數）。

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `channel` | str | `"telegram"` | `"telegram"` 或 `"discord"` |
| `token_env` | str | `BOT_<ID>_TOKEN` | `.env` 內的 env var 名 |
| `default_runner` | str | gateway 的 default | 此 bot 預設綁哪個 runner |
| `default_role` | str | `""` | roster slug（`roster/<slug>.md`） |
| `label` | str | `""` | UI 顯示用 |
| `allowed_user_ids` | list[int]\|None | None | bot 級白名單覆寫 |
| `allow_all_users` | bool\|None | None | bot 級開放 |
| `allow_bot_messages` | str | `"off"` | 同 discord，但用於 telegram 群組 |
| `trusted_bot_ids` | list[int]\|None | None | 信任的 bot id |
| `allowed_chat_ids` | list[int]\|None | None | 群組白名單 |
| `allow_all_groups` | bool | `false` | `true` = 任何邀請的群組都能用 |
| `respond_to_at_all` | bool | `false` | `true` = 回應 `@all` / `@大家` / `@everyone` |

完整範例見 §7.2、§7.4。

#### `[skills]` / `[modules]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `dir` | str | `"skills"` | skill 載入目錄 |

`[modules]` 是舊名 alias，仍可用。

#### `[voice]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `stt_provider` | str | `"groq"` | `"groq"` 或 `"faster-whisper"` |
| `tts_provider` | str | `"edge-tts"` | `"edge-tts"` 或 `"gtts"` |
| `tts_voice` | str | `"zh-TW-HsiaoChenNeural"` | edge-tts 的聲音名 |

#### `[audit]`

| 欄位 | 型別 | 說明 |
|------|------|------|
| `path` | str | audit log 目錄（CLIRunner 才寫） |
| `max_entries` | int | 上限 |

#### `[agent_team]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `max_depth` | int | `2` | role 內遞迴呼叫上限 |
| `fallback_role` | str | `"fullstack-dev"` | 路由失敗時的 fallback |

#### `[dispatch]`

| 欄位 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `max_pipeline_rounds` | int | `4` | `/relay` 最多接幾段 |
| `max_discussion_rounds` | int | `3` | `/discuss` 預設輪數 |
| `max_debate_voters` | int | `5` | `/debate` 最多幾個投票者 |
| `enforce_token_budget` | bool | `true` | pipeline 超過 budget 就提前停 |

---

## 7. 使用情境

### 7.1 單 bot 個人助理（最簡單）

**適用**：自己一個 user_id，DM 自家 bot 當日常助理。

設定：`[gateway].default_runner = "claude"`，`secrets/.env` 填 `TELEGRAM_BOT_TOKEN`、`ALLOWED_USER_IDS`、`CLAUDE_CODE_OAUTH_TOKEN`。`mat start` 後 log 應出現 `Telegram bot running [default]` 與 `telegram auth: strict (1 users)`。

```
你: hi
bot: Hello! How can I help today?
你: /remember 我的專案在 /home/kiwi/myapp
bot: Remembered: 我的專案在 /home/kiwi/myapp
```

### 7.2 多 bot 任務分流（B-1）

**適用**：把不同類型任務分給不同 bot（dev_bot=Claude、search_bot=Gemini、review_bot=Codex）。

```toml
[bots.dev]
token_env = "BOT_DEV_TOKEN"
default_runner = "claude"
default_role = "fullstack-dev"

[bots.search]
token_env = "BOT_SEARCH_TOKEN"
default_runner = "gemini"
default_role = "researcher"

[bots.review]
token_env = "BOT_REVIEW_TOKEN"
default_runner = "codex"
default_role = "code-auditor"
```

`secrets/.env` 補 `BOT_DEV_TOKEN`、`BOT_SEARCH_TOKEN`、`BOT_REVIEW_TOKEN`，`mat restart` 後 log 會有三條 `Telegram bot running [<id>]`。記憶以 `(user_id, channel, bot_id, chat_id)` 隔離 — 對 dev_bot 講過的東西 search_bot 看不到。

### 7.3 DM 內 `/discuss` 多 runner 辯論

**適用**：希望同一個對話裡讓 Claude 和 Gemini 接力討論，最後產生共識。

```
你: /discuss claude,gemini,rounds=4 設計快取層該用 LRU 還是 LFU
bot: [Round 1 — CLAUDE] thinking...
bot: [Round 1 — CLAUDE] LRU 適合存取模式有局部性的場景 …
bot: [Round 2 — GEMINI] thinking...
bot: [Round 2 — GEMINI] 補充：LFU 對長尾分佈表現更穩 …
bot: [Round 3 — CLAUDE] (回應 Gemini 的論點)
bot: [Round 4 — GEMINI] (再補充)
bot: [SYNTHESIS — GEMINI] summarising...
bot: [CONCLUSION] 結合兩位觀點：先用 LRU 起手，觀察存取分佈後決定是否切 LFU。
```

進階變奏：

- 改成自然語言：`請 claude 跟 gemini 討論一下 LRU vs LFU` → fast path 自動觸發
- 加 `,rounds=6`（上限 6）
- 把 token budget 設 0 避免提前停（`[runners.claude] context_token_budget = 8000`）

### 7.4 群組多 bot 協作（B-2，opt-in）

**適用**：把 dev_bot、search_bot、review_bot 拉進同一個 Telegram 群組讓他們互相喊話。

**前置**：

1. Telegram BotFather → `/setprivacy` → 選 bot → **Disable**（讓 bot 看到群組所有訊息，不只 mention）。
2. 把 bot 加進群組，記下 `chat_id`（負數，例如 `-1001234567890`）— 用 `mat logs grep chat_id` 在訊息進來後找。

每個 bot 都加：

```toml
[bots.dev]
# ...（其他欄位同 §7.2）
allow_all_groups = false
allowed_chat_ids = [-1001234567890]
allow_bot_messages = "mentions"
respond_to_at_all = true
```

**Transcript**（在群組內）：

```
你: @all 我想做一個 OAuth 服務，從何開始？
[dev_bot] OAuth 2.0 規範 RFC 6749 是起點 …
[search_bot] 業界主流 lib：authlib (Python)、passport (Node) …
你: @dev_bot 那能不能寫個 minimal 範例
[dev_bot] (Claude 回覆程式碼)
你: @search_bot 比較這個跟 keycloak 差在哪
[search_bot] (Gemini 回覆比較)
```

**Bot ↔ bot 防無限對話**：每個 `(channel, chat_id)` 連續 bot 訊息上限 10 次（`bot_turns.py`）；任何人類訊息會把計數歸零。

### 7.5 語音輸入

**適用**：手機上不方便打字，用 voice message 跟 bot 對話。

```
你: /voice on
bot: Voice replies enabled. Send a voice message or text to try.
你: (按住 Telegram 麥克風講「今天天氣怎樣」)
bot: [Transcribed]: 今天天氣怎樣
bot: (回覆文字 + 合成語音 audio)
你: /voice off
bot: Voice replies disabled.
```

STT 用 `[voice].stt_provider`（預設 groq），需要對應的 API key 在 `.env`：

```env
GROQ_API_KEY=gsk_example...
```

TTS 預設 `edge-tts`，免 key；若要換 Google TTS 改 `tts_provider = "gtts"`。

---

## 8. 除錯指南

### 8.1 Bot 沒回話

決策樹：

```
1. mat status
   ├─ container 不在 / service 沒跑 → mat start
   └─ 在 → 下一步
2. mat logs 100
   ├─ 看到 traceback → 找第一個非 framework 的 frame
   ├─ 沒看到任何訊息進來 → §8.2 (Telegram 連線)
   └─ 訊息進來但 runner 報錯 → §8.1.1
```

#### 8.1.1 「An error occurred. Please try again.」

來源：`src/gateway/dispatcher.py:546`，是 `_dispatch_single_runner` 捕捉到 runner exception 後的 generic 回覆。

**最常見原因：認證失敗。**

排查：

```bash
mat logs grep "Authentication"
mat logs grep "ACPRunner"
mat logs grep "OAuth"
```

| Log 訊息 | 原因 | 修法 |
|---------|------|------|
| `Authentication required` / `OAuth token invalid` | claude / codex / gemini 沒登入或 token 過期 | 重跑 `mat auth <cli>`，§3.4 |
| `Connection refused` / `EPIPE` / `BrokenPipeError` | ACP wrapper（`claude-agent-acp` 等）沒裝好 | 進 container 確認：`docker compose exec gateway which claude-agent-acp` |
| `OperationalError: no such table` | DB schema migration 沒跑 | `mat restart`；如還是錯看 §8.3 |
| `ACPRunner '<name>' subprocess crashed` | runner subprocess 掛了，會自動 reset；下一條訊息會 re-init | 看上一條 traceback 找原因 |

#### 8.1.2 「Unauthorized.」

來源：`src/channels/telegram_runner.py:185`。`adapter.is_authorized(user_id)` 回 `False`。

原因：`ALLOWED_USER_IDS` 沒設或不包含你的 user_id。

修法：

```bash
# 找你的 user_id（Telegram 找 @userinfobot）
echo "ALLOWED_USER_IDS=8359434933" >> secrets/.env  # 自己編輯比較安全
mat restart
```

更乾淨：用編輯器開 `secrets/.env` 確認沒重複設定。

#### 8.1.3 完全無反應 / 連 typing 都沒

可能：

- Telegram 409 Conflict（多實例 polling 同 token）→ §8.2
- Bot 名 / token 拼錯 → `mat logs grep "@"` 看註冊的 bot username 是不是你預期的
- network 問題（防火牆擋 `api.telegram.org`）→ `docker compose exec gateway curl -I https://api.telegram.org`

### 8.2 Telegram 409 Conflict

Log 看到：

```
ERROR main: Telegram Conflict: another instance is already running.
            Stop all other instances and restart. (Conflict: terminated by other getUpdates request)
```

來源：`main.py:218-224`。同一個 bot token 同時被兩個 process 在 `getUpdates`。

排查：

```bash
# 1. 本機有沒有其他 process
ps aux | grep -E "python.*main.py" | grep -v grep
ps aux | grep -E "telegram" | grep -v grep

# 2. Mac / 其他機器是否共用同一 token
# 看 .openclaw / 其他 MAT 安裝
ls ~/.openclaw/ 2>/dev/null
cat ~/.openclaw/openclaw.json 2>/dev/null | grep -i token

# 3. 確認自己 secrets/.env 的 token
grep TELEGRAM_BOT_TOKEN secrets/.env
```

修法：

- 找出另一個 polling 的 process 停掉。
- 不行的話，到 BotFather 重 generate token，更新 `.env`，`mat restart`。

### 8.3 Migration 失敗

Log 看到：

```
sqlite3.OperationalError: table settings_new already exists
```

或：

```
sqlite3.OperationalError: no such column: bot_id
```

原因：schema 升級到一半中斷，DB 處於不一致狀態。

修法（**先備份**）：

```bash
# 1. 停 bot
mat stop

# 2. 備份
cp data/db/history.db data/db/history.db.bak.$(date +%Y%m%d-%H%M%S)

# 3. 看 migration log
mat logs grep -i migration

# 4. 簡單修法：rename 舊 DB，啟動 bot 會自動建新 DB
mv data/db/history.db data/db/history.db.broken
mat start

# 5. 如果一定要保留歷史對話
sqlite3 data/db/history.db.bak ".schema turns"  # 看 schema
# 手動修 + 重 import — 這部分需要看具體 error 的 column 缺什麼
```

### 8.4 容器啟動失敗

```bash
docker compose ps
# gateway   exited (1)   …

mat logs 100
# 看 build error
```

常見原因：

| 症狀 | 原因 | 修法 |
|------|------|------|
| `no space left on device` | 磁碟滿 | `docker system prune -a` 清不用的 image |
| `port is already allocated` | port 撞 | 改 `docker-compose.yml` 的 port mapping |
| `Dockerfile: ADD failed` | source 改了但沒 rebuild | `mat update` 或 `docker compose up -d --build` |
| `python3.11: not found` | base image 太舊 | 換 base image（編輯 Dockerfile FROM 那行） |

### 8.5 對話送出但記不住

#### `/recall` 找不到

```bash
# 看 Tier 3 有沒有 turns
sqlite3 data/db/history.db "SELECT count(*) FROM turns WHERE user_id=8359434933;"

# 看 FTS5 有沒有 index
sqlite3 data/db/history.db "SELECT count(*) FROM turns_fts;"

# 如果 turns 有但 fts 沒 → rebuild index
sqlite3 data/db/history.db "INSERT INTO turns_fts(turns_fts) VALUES('rebuild');"
```

#### `/remember` 沒效

```bash
# 看 Tier 1 jsonl
ls -la data/memory/cold/permanent/
cat data/memory/cold/permanent/*.jsonl | tail -5
```

如果目錄不存在 → 權限問題：

```bash
mkdir -p data/memory/cold/permanent
chmod -R u+w data/memory/
mat restart
```

### 8.6 其他常見錯誤

| Log 訊息 | 原因 | 修法 |
|---------|------|------|
| `⏱ 訊息頻率過高...` | rate limit | 等一分鐘，或調高 `per_user_per_minute` |
| `⛔ 今日 token 已用盡` | daily budget 滿 | 隔天再試，或調大 `daily_token_budget` |
| `Runner '<name>' not found.` | runner 不在 `[runners.*]` | 用 `/use claude` 切回 |
| `Runner timed out.` | 單次 dispatch 超時 | 調大 `timeout_seconds`，或拆短問題 |

---

## 9. 升級流程

### 9.1 標準升級流程

```bash
# 1. 備份
cp -r data data.bak.$(date +%Y%m%d)
cp secrets/.env secrets/.env.bak.$(date +%Y%m%d)
cp config/config.toml config/config.toml.bak.$(date +%Y%m%d)

# 2. 拉新 code + rebuild
git pull --ff-only
mat update

# 3. 確認 migration 跑完
mat logs 200 | grep -iE "migration|schema|table"

# 4. 測 hi（在 Telegram 對 bot 送 hi）
```

### 9.2 升級失敗的 rollback

```bash
mat stop
git log --oneline -10                # 找上一個能跑的 commit
git reset --hard <COMMIT_SHA>
mv data data.failed && mv data.bak.20260428 data
mat start && mat logs
```

### 9.3 從 v1（單 bot）升級到 multi-bot

完全相容、零改動。原本的 `TELEGRAM_BOT_TOKEN` 會被 `load_bots()` fallback 邏輯包成 `[bots.default]`。

如果要切到顯式多 bot：

```toml
# 把原本的 TELEGRAM_BOT_TOKEN 改名
# secrets/.env:
#   - TELEGRAM_BOT_TOKEN=...
#   + BOT_MAIN_TOKEN=...

# config.toml 加：
[bots.main]
channel = "telegram"
token_env = "BOT_MAIN_TOKEN"
default_runner = "claude"
```

---

## 10. FAQ

**Q1. 我的記憶會不會丟？**
A. 不會。`data/db/history.db`（Tier 3）+ `data/memory/cold/permanent/*.jsonl`（Tier 1）都在 host bind mount，重 build image 不會動。完整備份：`tar czf mat-backup.tar.gz data/ secrets/`。

**Q2. 一個 user_id 可以同時用幾個 bot？**
A. 沒有上限。每個 `[bots.<id>]` 都自己 polling。資源限制：每個 bot 一個 process / event loop / Telegram poller。10 個還行，50 個建議分機器。

**Q3. 群組裡 bot 可以辯論嗎？**
A. 可以。先把每個 bot 開 `respond_to_at_all = true`，群組內送 `@all 一起想想 …`，每個 bot 各自獨立 dispatch。要 turn-based 接力目前沒原生支援，需要另寫 skill。

**Q4. token 多久要換？**
A. Claude OAuth 大約 10～30 天；Codex 約 30 天；Gemini 約 1 年。Bot 突然回 `An error occurred` 多半就是 token 到期，重跑 `mat auth <cli>` 即可。

**Q5. 怎麼從 v1 升級到多 bot？**
A. 看 §9.3。實際上只要加 `[bots.<id>]` section 就會自動切到多 bot 模式。

**Q6. 為什麼 Docker mode 要另外認證？**
A. Container 有自己的 user namespace + filesystem，看不到 host 的 `~/.claude/`、Keychain。詳見 §3.1。

**Q7. `/discuss` 跟群組多 bot 協作差別？**
A. `/discuss` 在單一 bot 內依序呼叫多個 runner（同一個 process、共用 session）。群組多 bot 是真的多個 bot polling、各自獨立 dispatch，記憶完全分桶。

**Q8. 怎麼禁用某個 runner？**
A. 把 `[runners.<name>]` 整個 section 刪掉或註解掉。或保留但改 `path = "/usr/bin/false"`（會 startup error 比較明顯）。

**Q9. 怎麼新增 roster role？**
A. 在 `roster/` 加 `<slug>.md`，前面 yaml frontmatter 至少要 `slug:`、`name:`、`identity:`。MAT 用 FastEmbed 算語義相似度自動路由。改完 `mat restart`。

**Q10. 可以接其他 LLM 嗎（例 Ollama、自架 vLLM）？**
A. 可以，但要寫 ACP wrapper 或新增 `type = "cli"` 的 runner。目前 ACP runner 假設 protocol 跟 claude-agent-acp 一致；CLI runner 假設 stdin → stdout 串流。最快 path：先用 OpenAI compatible API 包一層。

---

## 11. 進階主題（簡短帶過）

### 11.1 自訂 skill

`skills/<name>/manifest.json` 註冊命令、`skill.py` 實作 `async def dispatch(command, args, user_id, channel)` 並 `yield` 字串 chunk。`mat restart` 後 `/myskill ...` 即可觸發。範例見 `skills/web_search/`。

### 11.2 自訂 roster role

`roster/<slug>.md` 加 yaml frontmatter（`slug` / `name` / `summary` / `identity` / `rules`）。FastEmbed 用 `summary` 算語義相似度自動路由；也可手動 `/use <slug>` 切換。

### 11.3 接 Discord（多 channel）

填 `DISCORD_BOT_TOKEN` + `[discord].allowed_channel_ids`。Discord adapter 在 `src/channels/discord_adapter.py`，邏輯跟 Telegram 大致對稱（mention rule、bot-to-bot policy）。

### 11.4 接 voice

STT：在 `secrets/.env` 設 `GROQ_API_KEY` 或 `OPENAI_API_KEY`。TTS：edge-tts 免 key；換聲音改 `[voice].tts_voice`（完整列表 `edge-tts --list-voices`）。

### 11.5 Logs 集中

docker 模式可改 `docker-compose.yml` 的 `logging.driver`（`json-file`/`gelf`/`fluentd`）接 Loki / Datadog。

---

## 12. 給開發者

### 12.1 跑測試

```bash
cd /path/to/mini_agent_team
source venv/bin/activate
pytest tests/ -v
pytest tests/test_router.py -v       # 單檔
pytest -k "discuss" -v               # 名稱過濾
```

### 12.2 程式結構速覽

```
main.py                       # entry: load config + 啟動 channels
src/core/{config,bots}.py     # Config / BotConfig
src/core/memory/              # tier1.py (jsonl) / tier3.py (sqlite+fts5) / context.py
src/runners/                  # acp_runner.py / cli_runner.py
src/channels/                 # telegram_runner.py / discord_adapter.py
src/gateway/                  # dispatcher / router / nlu / rate_limit / session / streaming
src/skills/loader.py          # skill 動態載入
src/voice/                    # tts / stt
roster/*.md                   # 角色定義
skills/                       # 動態 skill
```

### 12.3 開 issue / PR

- Repo：<https://github.com/nchiyi/mini_agent_team>
- 開 issue 時請附：`mat status` 輸出、相關 `mat logs error` 片段、`config.toml`（mask 掉 token）、`mat mode`。
- PR 請對 `main` 分支，commit 訊息用「動詞 + 主題」開頭（例：`fix: telegram 409 race condition`）。

### 12.4 設計文件

進階設計細節在 `docs/superpowers/plans/`，依日期排：phase1 核心 pipeline、phase2 memory、phase3 modules、multi-agent-modes、ACP setup wizard、reasoning mode 等。

---

## 結語

MAT 的核心理念是「個人 / 小團隊本機助理」：預設安全（DM only）、一切 opt-in、per-bot 隔離、跨升級不丟資料。改成公開服務 / 多租戶用法請 fork 後自行加 per-user rate limit、at-rest 加密、skill/roster sandboxing、監控 alert。有 bug 或 feature request 歡迎開 issue。
