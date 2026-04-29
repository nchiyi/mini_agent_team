# 使用情境指南

> 5 套情境化設定 + 操作教學，從最簡單的單 bot 私訊到多 bot 辯論。每篇皆包含可貼上即用的 `config/config.toml` 片段、Telegram / Discord 雙 channel 設定步驟、Mermaid 架構圖與訊息流程圖。

## 適用對象

如果你已經跑過 `mat setup`、bot 已經會回 1:1 私訊，但想：

- 多開幾隻 bot 同時上線（每隻綁不同 CLI / role）
- 把多隻 bot 拉進同一個群組做協作
- 讓 bot 互相 `@mention` 串接工作
- 用 `@all` 廣播題目讓多隻 bot 各自獻策再綜合
- 安排 bot 站不同立場辯論議題

那麼這 5 篇文件正是為你寫的。

---

## 情境總覽

| # | 情境 | 主要機制 | 群組需求 | 適合場景 |
|---|------|---------|---------|---------|
| 1 | [DM 1:1 對話](01-dm-1on1.md) | DM short-circuit、`default_runner` / `default_role` | 不需要 | 個人助理、單一專家 bot |
| 2 | [群組 1:多 bot](02-group-multibot.md) | `allowed_chat_ids` 白名單、`@mention` 路由、`allow_bot_messages = "off"` | 同群組 | 多人共用 bot 工具箱 |
| 3 | [Bot 接力工作](03-bot-relay.md) | `allow_bot_messages = "mentions"`、`BotTurnTracker` cap、`claim_message` dedup | 同群組 | 流水線任務、跨專業交棒 |
| 4 | [多 bot 共同研究](04-collaborative-research.md) | `respond_to_at_all`、`_AT_ALL_RE`、群組 history 綜合 | 同群組 | 廣徵意見、頭腦風暴 |
| 5 | [多 bot 辯論觀點](05-debate.md) | per-bot 不同 `default_role` + `@all` + turn-cap | 同群組 | 立場碰撞、決策前驗證 |

---

## 系統機制總覽圖

下圖把 5 個情境用到的關鍵機制集中標示——讀完每個情境後可回來對照。

```mermaid
graph TD
  User[使用者] -->|傳訊息| Channel{Channel}
  Channel -->|telegram| TgRunner[telegram_runner.py]
  Channel -->|discord| DcRunner[discord_runner.py]

  TgRunner --> Policy[policy.py: should_handle]
  DcRunner --> Policy

  Policy -->|DM| DispatchDM[dispatch -- 情境 1]
  Policy -->|群組 + 自己被 @ mention| DispatchMention[dispatch -- 情境 2/3]
  Policy -->|群組 + 來源是 bot + allow_bot_messages 通過| DispatchRelay[dispatch -- 情境 3]
  Policy -->|@ all 經 _AT_ALL_RE 展開| DispatchAtAll[dispatch -- 情境 4/5]

  DispatchDM --> Runner[Runner: claude / codex / gemini]
  DispatchMention --> Runner
  DispatchRelay --> Runner
  DispatchAtAll --> Runner

  DispatchRelay -.連續 bot 訊息 cap=10.-> TurnCap[BotTurnTracker]
  DispatchAtAll -.訊息 dedup.-> ClaimMsg[claim_message]
```

機制對照：

- **DM short-circuit**：`src/gateway/policy.py` 的 `should_handle()` 對 `chat_type == "private"` 直接放行，無需任何群組欄位（情境 1）。
- **`@mention` 路由**：`mentioned_bot_ids` 由 `src/channels/telegram_runner.py:_build_inbound_from_update` 用 `bot_registry.resolve()` 解析；`policy.py` 第 71 行起檢查當前 bot 是否在 mention 名單（情境 2、3）。
- **bot↔bot 訊息**：`policy.py` 第 52 行起依 `allow_bot_messages` 三段值決定接受程度（情境 3）。
- **`@all` 展開**：`src/gateway/dispatcher.py:42` 的 `_AT_ALL_RE = r"(?<!\S)@(all|大家|everyone)\b"` 偵測；命中時 `_expand_at_all()` 把 `mentioned_bot_ids` 展成註冊表內全部 bot id（情境 4、5）。每隻 bot 的 `respond_to_at_all` 必須個別開啟才會被喚醒。
- **Turn cap**：`BotTurnTracker.cap = 10`（`src/gateway/bot_turns.py:23`）保護 bot↔bot 不無限互回（情境 3、4、5）。
- **訊息 dedup**：`claim_message()`（同檔 31 行）保證同一個 `message_id` 只有一隻 bot 拿到處理權，避免 `@all` 場景重複回覆。
- **記憶四元組分桶**：`(user_id, channel, bot_id, chat_id)`（README.md 第 657 行），所以 DM 的對話與群組的對話互不外洩。

---

## 通用前置作業

開始任何情境前請先確認：

1. `mat setup` 已跑過、`mat status` 顯示 running。
2. `secrets/.env` 內 `ALLOWED_USER_IDS` 包含你的 user id（不然全被擋）。
3. 想用群組情境的話，去 BotFather `/setprivacy → Disable`（Telegram），或在 Discord Developer Portal 開 `Message Content Intent`（Discord）。否則 bot 在群組看不到完整訊息文字。

接下來請挑一個情境開始：

- 第一次用：[情境 1（DM 1:1 對話）](01-dm-1on1.md)
- 多人協作：[情境 2（群組 1:多 bot）](02-group-multibot.md)
- 流水線任務：[情境 3（Bot 接力工作）](03-bot-relay.md)
- 廣徵意見：[情境 4（多 bot 共同研究）](04-collaborative-research.md)
- 辯論觀點：[情境 5（多 bot 辯論）](05-debate.md)

---

## 相關文件

- [`README.md`](../../README.md) — 專案總覽、設計原則、快速安裝
- [`docs/user-manual.md`](../user-manual.md) — 完整使用手冊（安裝、認證、命令參考、除錯）
- [`docs/discord-multi-bot.md`](../discord-multi-bot.md) — Discord 多 bot 專屬細節（Developer Portal 步驟、channel id 取得方式）
- [`config/config.toml.example`](../../config/config.toml.example) — 註解完整的設定檔範例
