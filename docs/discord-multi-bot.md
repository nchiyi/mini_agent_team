# 多 Discord bot 設定指南

> 本檔對齊 Telegram 多 bot 設計（README.md `多 bot 共存（B-1）` / `群組多 bot 協作（B-2）` 章節）。Discord 端的多 bot 與 Telegram 行為等價：同一個 MAT process 同時起 N 個 Discord client，每個 bot 各自綁 token / runner / role / 群組權限，跑同一份 `should_handle()` policy gate 與 turn-cap。
>
> 共通的設計動機（為什麼要多 bot、記憶隔離、群組對話 turn-cap）請看 README，本檔只列 Discord 專屬差異與設定步驟。

---

## 1. 為什麼會有多 Discord bot 需求

| 用途 | 設定 |
|---|---|
| 不同 role 走不同 CLI（dev / reviewer / researcher） | 每個 bot 各自 `default_runner` + `default_role` |
| 不同權限範圍（內部 vs 公開 channel） | 每個 bot 獨立 `allowed_chat_ids` / `allow_all_groups` |
| 不同對 bot↔bot 的態度（一隻接 relay bot、一隻封閉） | 每個 bot 獨立 `allow_bot_messages` / `trusted_bot_ids` |
| 對 user 也想分桶（一隻 internal、一隻 client-facing） | 每個 bot 獨立 `allowed_user_ids` / `allow_all_users` |

記憶與 Telegram 多 bot 一樣以 `(user_id, channel, bot_id, chat_id)` 四元組分桶（README.md 第 66 行），不同 Discord bot 之間的歷史完全不互通。

---

## 2. Discord Developer Portal 準備工作

每個 bot 需要 Discord 端一次性設定：

1. 進 <https://discord.com/developers/applications>，建立新的 Application（每個 bot 一個 application）。
2. 在左側 **Bot** 頁建 bot user。
3. **Privileged Gateway Intents**：開啟 `Message Content Intent`（不然 `message.content` 會空白）。Discord 的等價於 Telegram BotFather 的 Privacy Mode。
4. **Reset Token** 取得 token，貼進 `secrets/.env`。
5. **OAuth2 → URL Generator**：勾 `bot` scope + 你要的 permissions（最小通常是 `Send Messages` + `Read Message History`），產生邀請連結把 bot 拉進你的 server。

每個 bot 重複以上五步驟。

---

## 3. config.toml 設定方式

### 多 Discord bot（DM 限定，最簡）

```toml
[bots.dev_dc]
channel        = "discord"
token_env      = "BOT_DEV_DC_TOKEN"
default_runner = "claude"
default_role   = "fullstack-dev"

[bots.search_dc]
channel        = "discord"
token_env      = "BOT_SEARCH_DC_TOKEN"
default_runner = "gemini"
default_role   = "researcher"
```

→ 兩個 bot 同時上線，都只接受 1:1 DM（沒寫任何群組欄位 = 群組關閉）。

### 多 Discord bot + 群組白名單

```toml
[bots.dev_dc]
channel              = "discord"
token_env            = "BOT_DEV_DC_TOKEN"
default_runner       = "claude"
default_role         = "fullstack-dev"
allow_all_groups     = false
allowed_chat_ids     = [1234567890]   # Discord channel id（整數）
allow_bot_messages   = "mentions"

[bots.search_dc]
channel              = "discord"
token_env            = "BOT_SEARCH_DC_TOKEN"
default_runner       = "gemini"
default_role         = "researcher"
allow_all_groups     = true
allow_bot_messages   = "off"
```

`secrets/.env`：

```env
BOT_DEV_DC_TOKEN=...
BOT_SEARCH_DC_TOKEN=...
```

### 取得 Discord channel id

桌面版 Discord：**User Settings → Advanced → Developer Mode** 開啟，然後對 channel 名右鍵 → **Copy Channel ID**。Discord channel id 是正整數（不像 Telegram 群組 chat_id 是負數）。

`allowed_chat_ids` 在 Discord 路徑下對應 `discord.Message.channel.id`（見 `src/channels/discord_adapter.py:180` 把 `message.channel.id` 寫進 `InboundMessage.chat_id`），policy 比對在 `src/gateway/policy.py:47-49`。

---

## 4. Auth 三層優先序

每個 bot 的 user allowlist 走「per-bot → per-channel → global」三層 fallback，與 Telegram 完全一致：

| 層級 | 設定欄位 | 設定位置 |
|---|---|---|
| per-bot（最高優先） | `allowed_user_ids` / `allow_all_users` | `[bots.<id>]` |
| per-channel | `allowed_user_ids` / `allow_all_users` | `[discord]` |
| global（fallback） | `ALLOWED_USER_IDS` / `gateway.allow_all_users` | `secrets/.env` / `[gateway]` |

實作位置：

- `src/channels/discord_runner.py:74-85` — `run_discord_for_bot` 從 `bot_cfg` 讀 per-bot 值，沒設才退 `cfg.discord`，最後丟給 `_resolve_channel_auth` 套 global fallback。
- `src/core/config.py:308-325` — `_resolve_channel_auth` 共用實作（Telegram / Discord 都呼叫）。

群組層的 `allowed_chat_ids` / `allow_all_groups` 是 per-bot 獨立欄位，不走 fallback——沒寫等於白名單為空 + `allow_all_groups=False` = 拒絕所有群組（README.md 第 15 行的「預設只接受 1:1 私訊」原則）。

---

## 5. 訊息 dedup 與 turn-cap 保證

**Dedup**：兩個 Discord bot 都被 `@all` / 都看得到群組訊息時，`BotTurnTracker.claim_message`（`src/gateway/bot_turns.py:31-50`）以 `(channel, chat_id, message_id)` 為 key，只有第一個叫到 `claim_message()` 的 bot 拿到 `True`，後到的 bot 一律返回 `False` 進而 `should_handle` 返回 `False`，避免重複回覆。實作銜接在 `src/gateway/policy.py:37-41`（DM）/ `:62-67`（bot 訊息）/ `:73-77`（群組 human 訊息）三條路徑。

**Turn-cap**：每個 `(channel, chat_id)` 連續 bot 訊息上限 10 次（`BotTurnTracker.cap=10`，`src/gateway/bot_turns.py:23`），任何人類訊息會把計數歸零。多 Discord bot 在同一個 channel 裡互回時，第 11 輪起會被 `cap_reached` 擋下（`src/gateway/policy.py:58-61`），等下一個人類訊息進來才解封。

實作鉤點在 `src/channels/discord_runner.py:38-46` 的 `gateway_handler`：每則通過 `should_handle` 的群組訊息，依 `inbound.from_bot` 呼叫 `note_bot_turn` 或 `reset_on_human`。Telegram 路徑跑同一段邏輯（`src/channels/telegram_runner.py`），所以 turn-cap 對 Telegram / Discord / 跨 channel（如果有）都一致。

> 注意：Task 0 修掉了 `policy.py` 與 `telegram_runner.py` 寫死 `channel="telegram"` 的 bug，現在 `cap_reached` / `note_bot_turn` / `reset_on_human` 都用 `inbound.channel`，所以 Discord 桶與 Telegram 桶各算各的，不會交叉污染。

---

## 6. Migration：從單 bot `[discord]` 升級到 `[bots.X]`

舊設定（單 bot）：

```toml
[discord]
allow_user_messages = "all"
allow_bot_messages  = "off"
# allowed_channel_ids = []
# allowed_user_ids    = [...]
# allow_all_users     = false
```

`secrets/.env` 內 `DISCORD_BOT_TOKEN=...`。

### 選項 A：什麼都不改（legacy fallback 自動接管）

只要沒有任何 `[bots.X] channel = "discord"` 條目，`src/core/bots.py:72-78` 的 legacy fallback 會在偵測到 `DISCORD_BOT_TOKEN` env 後合成一筆 `BotConfig(id="default", channel="discord", token_env="DISCORD_BOT_TOKEN", default_runner=<gateway.default_runner>)`。`_build_channel_tasks()` 把它當成普通的多 bot 條目排程，行為與舊版完全一致。

如果同時有 `TELEGRAM_BOT_TOKEN` + `DISCORD_BOT_TOKEN` 而沒寫 `[bots.*]`，會合成兩筆——兩邊都用 `id="default"`，靠 `channel` 區分。所有路由 key（`BotTurnTracker` 的 `(channel, chat_id)`、`bot_registry` 的 `(channel, username)`、Tier1 檔名 `{user_id}_{channel}_{bot_id}_{chat_id}.jsonl`）都帶 channel，所以同 id 不會衝突；對稱命名也讓未來 cross-channel memory 聚合自然落在 `(user_id, "default")`。見 `src/core/bots.py:72-78`。

### 選項 B：升級成顯式 `[bots.X]`（推薦）

1. 在 `config/config.toml` 加：

   ```toml
   [bots.assistant_dc]
   channel        = "discord"
   token_env      = "DISCORD_BOT_TOKEN"   # 直接沿用既有 env var
   default_runner = "claude"              # 對齊既有 [gateway].default_runner
   ```

2. 重新啟動 MAT（`mat restart`）。
3. （選用）想加第二個 bot：在 `secrets/.env` 多寫一行 `BOT_FOO_DC_TOKEN=...`，然後在 `config.toml` 多加 `[bots.foo_dc]` 區塊即可。

升級後 `[discord]` 區塊仍可保留作為 per-channel 預設，但 per-bot 欄位（`allowed_chat_ids` / `allow_bot_messages` / `allowed_user_ids` 等）的優先序更高。

### 雙向相容性檢查

- 既有 `DISCORD_BOT_TOKEN` 不需改名，`token_env = "DISCORD_BOT_TOKEN"` 會直接讀。
- `[discord]` 區塊保留：`allow_user_messages` / `allowed_channel_ids` / `trusted_bot_ids` 等沒被 per-bot 覆蓋的欄位仍有效。
- 沒寫 `default_runner` 時自動套 `[gateway].default_runner`（`src/core/bots.py:44`）。

---

## 7. 疑難排解

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| Bot 上線但群組訊息沒反應 | Message Content Intent 沒開 | Developer Portal → Bot → Privileged Gateway Intents → 勾 Message Content |
| `Bot %r dropped: env var %s is not set` 警告 | `token_env` 名稱對應的 env 沒寫 | 檢查 `secrets/.env` 是否有對應 `BOT_<ID>_TOKEN` |
| 兩支 bot 都回應同一則 `@all` 訊息 | Dedup 失效（不該發生） | 檢查 `BotTurnTracker` 是否被多 instance 化（應在 `AppContext` 共用一個） |
| 升級後舊單 bot 不上線 | `[bots.X]` 區塊存在但沒包含舊 token 對應的 entry | legacy fallback 只在「**完全沒有** `[bots.X]`」時才觸發；要嘛把舊 bot 加進 `[bots.X]`，要嘛清空 `[bots]` 區塊 |

---

## 相關檔案速查

- `src/channels/discord_runner.py` — per-bot launcher（`run_discord_for_bot` / `_make_gateway_handler`）
- `src/channels/discord_adapter.py` — `DiscordAdapter`（接受 `bot_id` 參數）
- `src/core/bots.py` — `BotConfig` / `load_bots`（含 legacy fallback）
- `src/gateway/policy.py` — `should_handle`（DM / 群組 / bot↔bot 三條路徑）
- `src/gateway/bot_turns.py` — `BotTurnTracker`（claim_message dedup + turn-cap）
- `config/config.toml.example` — 多 Discord bot 範例段落
