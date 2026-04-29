# 情境 5：多 bot 辯論觀點

> 跟情境 4（共同研究）的差別：本情境**刻意製造立場對立**。每隻 bot 配不同的 roster 角色——保守派 / 激進派 / 務實派——對同一議題從各自立場出聲。Bot 可選擇互相 `@mention` 反駁，或單純並列出聲讓 user 對照。`BotTurnTracker` cap 確保辯論不無限延續。

## 適用場景

- 決策前壓力測試：先讓 conservative_bot 跟 progressive_bot 互打一輪，找出方案盲點再決定
- 道德 / 風險議題：拋議題給 ethicist_bot vs pragmatist_bot 看立場光譜
- 學習用：自己想練思辨，把多個立場排出來看
- 寫作 / 簡報前的前期工作：找出論點正反兩面再寫

跟情境 4 的差別：情境 4 預期最終得到「共識」；本情境預期得到「立場光譜 + 最有力論點」，未必有共識。

## 系統需求

| 項目 | 內容 |
|------|------|
| Channel | 一個共用 group / channel |
| Bot 數 | 至少 2 隻（建議 3 隻：保守 / 激進 / 中立）|
| 必填欄位 | `allowed_chat_ids = [...]`、各 bot **不同 `default_role`**、`respond_to_at_all = true` |
| 關鍵欄位 | `allow_bot_messages = "mentions"`（要互相反駁的話）|
| 系統機制 | per-bot `default_role` + roster 立場 prompt + `BotTurnTracker.cap = 10` |
| Roster | 自訂三個立場角色（本情境會建立 `conservative` / `progressive` / `pragmatist`） |

關鍵：**每隻 bot 雖然跑同一個 LLM 也沒關係，立場差異主要靠 `roster/<slug>.md` 的 `identity` + `rules` 注入**。

實作流程（`src/gateway/dispatcher.py:79-99`）：

```python
def apply_role_prompt(prompt, role_slug, base_dir):
    role_file = repo_root() / "roster" / f"{role_slug}.md"
    prefix = build_role_prompt_prefix(role_slug)   # 讀 roster md 拼 prompt
    body = prefix + prompt if prefix else prompt
    return _MAT_SYSTEM_PREFIX + body
```

→ 每次 dispatch 開頭都會把對應 role 的 identity + rules 黏在 prompt 前面。所以三隻 bot 即便都跑 claude，輸出的論點走向會被各自 roster identity 拉開。

---

## 設定步驟

### Telegram

#### 1. 建立四隻 bot（三個辯論者 + 一個主持人，可選）

延續前面情境的方法，BotFather `/newbot` 各跑一次：

```
myteam_conservative_bot   保守派
myteam_progressive_bot    激進派
myteam_pragmatist_bot     務實派
myteam_moderator_bot      主持人（選用，作辯後綜合）
```

每隻都 `/setprivacy → Disable`、加進同一個群組。

#### 2. 建立三個立場 roster

`roster/conservative.md`：

```markdown
---
slug: conservative
name: 保守派 (Conservative)
summary: 重視穩定、降低風險、保守變更，傾向先驗證再採納新方案。
identity: 你是一位重視穩定與風險控管的保守派思考者，傾向先驗證、再採納新方案。你會質疑流行潮流，提醒成本與不確定性。
rules:
  - 對任何新提案先列出「最壞情況」與「不可逆風險」。
  - 引用「歷史上類似改變失敗的案例」作為對照。
  - 拒絕「因為流行所以該做」的論證；要求量化效益。
  - 結論必須包含「如果不做會發生什麼」的反問。
preferred_runner: claude
tags:
  - debate
  - conservative
---
保守派立場，搭配辯論場景使用。
```

`roster/progressive.md`：

```markdown
---
slug: progressive
name: 激進派 (Progressive)
summary: 重視進步、快速迭代、嘗試新方案，傾向先做再修。
identity: 你是一位重視快速迭代與長期願景的激進派思考者，傾向「先做再修」。你會挑戰現狀，強調機會成本與創新可能。
rules:
  - 對任何方案先列出「不行動的代價」與「機會成本」。
  - 引用「成功的破壞式創新案例」（例如 iPhone 取代 BlackBerry）。
  - 拒絕「以前沒做過」的反對論證；要求說明「為什麼現在不能是第一次」。
  - 結論必須包含「實驗最小可行方案」的具體建議。
preferred_runner: claude
tags:
  - debate
  - progressive
---
激進派立場，搭配辯論場景使用。
```

`roster/pragmatist.md`：

```markdown
---
slug: pragmatist
name: 務實派 (Pragmatist)
summary: 重視實效、衡量 trade-offs、避免極端，尋求兩端平衡。
identity: 你是一位務實派，不偏向保守也不偏向激進，重視實際可執行性與短中期回報。你會主動找雙方論點的盲點。
rules:
  - 列出兩端立場的核心利弊，並指出「雙方都忽略的第三條路」。
  - 提供具體可量化的決策標準（例：「如果 X 達 Y 就 go」）。
  - 拒絕情緒化或意識形態化的論證。
  - 結論必須給「最小成本實驗」與「明確 abort 條件」。
preferred_runner: claude
tags:
  - debate
  - pragmatist
---
務實派立場，平衡其他兩派的辯論。
```

`roster/moderator.md`（選用，作辯後綜合）：

```markdown
---
slug: moderator
name: 主持人 (Moderator)
summary: 主持辯論、整理各方論點、給出最終決策建議。
identity: 你是辯論主持人。你不偏袒任何一方，負責把多個對立立場整理成「論點地圖」、找出真正分歧、給出最終決策建議。
rules:
  - 列出每方的「核心主張」與「最強論證」。
  - 指出「真正的分歧點」（往往不在表面，而在價值觀差異）。
  - 給出「如果是我會怎麼決定」的明確結論，並交代理由。
  - 拒絕「兩邊都對」的虛假平衡。
preferred_runner: claude
tags:
  - debate
  - moderator
---
辯論主持人，負責綜合與決策建議。
```

#### 3. 寫 `secrets/.env`

```env
ALLOWED_USER_IDS=123456789
BOT_CONS_TOKEN=...
BOT_PROG_TOKEN=...
BOT_PRAG_TOKEN=...
BOT_MOD_TOKEN=...
```

#### 4. 寫 `config/config.toml`

```toml
[bots.cons]
channel              = "telegram"
token_env            = "BOT_CONS_TOKEN"
default_runner       = "claude"
default_role         = "conservative"          # ← 立場 roster
label                = "Conservative"
allow_all_groups     = false
allowed_chat_ids     = [-1001234567890]
allow_bot_messages   = "mentions"              # 允許其他立場 @ 我反駁
respond_to_at_all    = true                    # 接受 @all 觸發

[bots.prog]
channel              = "telegram"
token_env            = "BOT_PROG_TOKEN"
default_runner       = "claude"
default_role         = "progressive"
label                = "Progressive"
allow_all_groups     = false
allowed_chat_ids     = [-1001234567890]
allow_bot_messages   = "mentions"
respond_to_at_all    = true

[bots.prag]
channel              = "telegram"
token_env            = "BOT_PRAG_TOKEN"
default_runner       = "claude"
default_role         = "pragmatist"
label                = "Pragmatist"
allow_all_groups     = false
allowed_chat_ids     = [-1001234567890]
allow_bot_messages   = "mentions"
respond_to_at_all    = true

[bots.mod]
channel              = "telegram"
token_env            = "BOT_MOD_TOKEN"
default_runner       = "claude"
default_role         = "moderator"
label                = "Moderator"
allow_all_groups     = false
allowed_chat_ids     = [-1001234567890]
allow_bot_messages   = "mentions"              # 三派吵完後它要看見訊息來綜合
respond_to_at_all    = false                   # 主持人不參與並列辯論
                                                # 由 user 單獨 @mod 召喚
```

> **三隻辯論者都用 `claude`**——立場差異不靠 LLM 不同，靠 role identity 不同。也可以混搭（cons=claude, prog=codex, prag=gemini）讓「立場 + LLM 個性」雙重多樣性。

#### 5. 重啟驗證

```bash
mat restart
mat logs 50 | grep "Registered bot"
# 應有四行
```

### Discord

把 `channel = "discord"`、`allowed_chat_ids = [<discord channel id>]`，其餘照上面 schema。立場 roster 跟 Telegram 共用（roster 是 channel-agnostic）。

---

## 操作方式

### 範例 A：三派並列辯論（無互相反駁）

```
你：「@all 議題：我們要不要強制要求每個 PR 都做 code review？
     團隊 5 人，目前是「自己看自己沒問題就 merge」」

@myteam_cons_bot（保守派 + claude）：
  最壞情況：強制 review 之後，
  - 變成形式化「LGTM」走過場，反而比現在更糟
  - 5 人團隊每天輪流 review 變成 bottleneck
  - 反作用：開發速度下降 30-50%
  歷史案例：Google 早期強制 review 也是經多年才收歛出當前的 critique culture
  如果不做會發生什麼？確實有 bug 漏進 prod 的風險，但用 CI/CD 的測試覆蓋率也能 mitigate

@myteam_prog_bot（激進派 + claude）：
  不行動的代價：
  - 5 人團隊「自己看自己」= 集體盲點，沒有人能真正 review
  - 每個 bug 漏進 prod 平均花 8x dev time 修，遠超過 review 成本
  機會成本：放棄了「團隊互相學習」這個最快的 onboard 機制
  破壞式案例：Linus Torvalds 的 Linux kernel review 流程，也是強制執行才形成文化
  最小可行：先做 1 個月，每個 PR 至少 1 人 review，月底評估速度與 bug 率

@myteam_prag_bot（務實派 + claude）：
  雙方盲點：
  - 保守派沒考慮「不 review 的隱性代價」
  - 激進派沒考慮「review 品質」這個變數（爛 review 比沒 review 還糟）
  第三條路：先做「分級 review」
  - 影響核心邏輯的 PR：強制 review
  - 純 typo / dependency bump：自審即可
  決策標準：3 個月後看「prod incident 數量」決定是否擴大覆蓋
  Abort 條件：開發速度下降超過 25% 就回滾

→ 三派出聲，user 看完已經有「論點全景圖」
```

### 範例 B：bot 互相 `@mention` 反駁

```
你：「@all 議題：每天上班是 09:00 還是 11:00？」

@cons_bot：「09:00 才是專業文化的展現，11:00 太鬆散...」
  （在最後加一句）「@prog_bot 你不會反對吧」

@prog_bot：「09:00 是工業時代遺產，創意工作者的高效時段在 14:00-22:00...
  @cons_bot 你說的『專業文化』其實是 status signaling，不是生產力」

@cons_bot：「@prog_bot 你說的『創意工作者』在我們這種 Ops 團隊根本不適用，
  生產系統不會在 14:00 才開始有 traffic」

→ 互相反駁，turn-cap 計數中（每輪 +1，第 11 輪起會被擋下）

你：「@mod_bot 主持綜合一下」

@mod_bot（主持人 + claude）：
  論點地圖：
  - cons_bot：強調 status signaling、團隊文化、生產系統 ops 視角
  - prog_bot：強調個體高效時段、知識工作者特性、彈性
  真正分歧點：「我們是 ops-driven 還是 creative-driven 團隊」這個身份認知
  我會怎麼決定？團隊角色 60% creative，40% ops，因此核心時段 11:00-16:00
  必到，09:00-11:00 跟 16:00-19:00 為彈性時段。每月 review 是否照預期。
```

---

## 架構圖

```mermaid
graph TD
  User[使用者] -->|"@all 議題"| Group[Telegram group]

  Group --> Cons[cons_bot]
  Group --> Prog[prog_bot]
  Group --> Prag[prag_bot]
  Group --> Mod[mod_bot]

  Cons --> RoleC[apply_role_prompt 套上 conservative identity]
  Prog --> RoleP[apply_role_prompt 套上 progressive identity]
  Prag --> RoleR[apply_role_prompt 套上 pragmatist identity]
  Mod --> RoleM[respond_to_at_all=false 跳過]

  RoleC --> Cd1[claude 跑保守派 prompt]
  RoleP --> Cd2[claude 跑激進派 prompt]
  RoleR --> Cd3[claude 跑務實派 prompt]

  Cd1 --> Out1[保守派論點 可含 @ 對方]
  Cd2 --> Out2[激進派論點]
  Cd3 --> Out3[務實派論點]

  Out1 --> Group
  Out2 --> Group
  Out3 --> Group

  Group -.bot 互回觸發 turn-cap 計數.-> TurnCap[BotTurnTracker counter +1 每輪]
  TurnCap -.cap=10.-> Stop[第 11 輪起 should_handle drop]

  User -->|"@mod 綜合"| Group2[第二輪]
  Group2 --> Mod2[mod_bot 看見 mention]
  Mod2 --> Cd4[claude 跑主持人 prompt 整合論點]
  Cd4 --> Out4[最終決策建議]
  Out4 --> Group2
```

---

## 訊息流程

```mermaid
sequenceDiagram
  autonumber
  participant U as 使用者
  participant G as Group
  participant Cs as cons_bot
  participant Pg as prog_bot
  participant Pr as prag_bot
  participant Md as mod_bot
  participant T as BotTurnTracker
  participant Cl as claude

  U->>G: 「@all 強制 code review？」
  G-->>Cs: msg @all
  G-->>Pg: msg @all
  G-->>Pr: msg @all
  G-->>Md: msg @all
  Cs->>Cs: respond_to_at_all=true 展開
  Pg->>Pg: respond_to_at_all=true 展開
  Pr->>Pr: respond_to_at_all=true 展開
  Md->>Md: respond_to_at_all=false drop

  par 三派並列
    Cs->>Cl: prompt + conservative identity
    Cl-->>Cs: 「最壞情況...」
    Cs-->>G: 回應 含 @ prog_bot
  and
    Pg->>Cl: prompt + progressive identity
    Cl-->>Pg: 「不行動代價...」
    Pg-->>G: 回應
  and
    Pr->>Cl: prompt + pragmatist identity
    Cl-->>Pr: 「雙方盲點...」
    Pr-->>G: 回應
  end

  Note over Cs,Pr: dedup 機制下 第一個搶到 claim_message 的 bot 處理；實務上 多 bot 並列回應仰賴方案 2 /discuss

  G-->>Pg: cons 訊息 from_bot mention=prog
  Pg->>T: cap_reached 否
  Pg->>T: claim_message
  T-->>Pg: True
  Pg->>T: note_bot_turn counter=1
  Pg->>Cl: prompt + progressive
  Cl-->>Pg: 「@cons 你說的是 signaling」
  Pg-->>G: 反駁

  Note over T: 每一棒 bot 互回 counter +1；到 10 自動停 等 human reset

  U->>G: 「@mod 綜合」
  G-->>Md: msg human mention=mod
  Md->>Cl: prompt + moderator + 群組 inbound 引用
  Cl-->>Md: 「論點地圖 / 真正分歧 / 我會怎麼決定」
  Md-->>G: 主持人結論
```

---

## 常見問題

**Q: 三派 `@all` 都同時回了嗎？**
A: 跟[情境 4 的 `@all` dedup 行為](04-collaborative-research.md#常見問題)相同。實務上，因為 `claim_message` dedup，**多隻 bot 同時對 `@all` 回應有時只會有一隻接到**。要強制每隻都並列，目前最可靠：

- **方案 1**：user 在訊息中**逐一**點名：`@cons @prog @prag 議題...`——但 dedup 仍會只放第一隻通過
- **方案 2**：user 對單一 bot 用 `/debate claude,codex,gemini <題目>`，由 `_dispatch_debate`（`src/gateway/dispatcher.py:378-458`）內建多 runner 對立辯論 + 投票機制，**這是 MAT 真正內建的辯論模式**
- **方案 3**：user 對每個立場 bot **個別**單獨提問（`@cons 你怎麼看？` 然後 `@prog 你怎麼看？`），手動串起來

> **最推薦**：直接用 `/debate` 命令，這是 MAT 內建的辯論協議，含投票決勝負。詳見「進階」段落。

**Q: 為什麼 bot 跑同一個 LLM（claude）卻立場不同？**
A: `apply_role_prompt`（`src/gateway/dispatcher.py:79-99`）在每次 dispatch 把 roster identity + rules 黏在 prompt 最前面。`identity` 是身分定義（「你是一位重視穩定...的保守派」），`rules` 是行為規則（「對任何新提案先列出最壞情況」）。同一 LLM 看到不同 prompt prefix 會走不同推理路徑。

**Q: 立場差異不明顯，三派講得都差不多？**
A: 兩個地方加強：
1. **強化 roster identity / rules 對立性**：明確寫「拒絕 X 論證」「必須引用 Y」這種**禁令式**規則，比「強調」「重視」更有效
2. **prompt 工程**：對 user 提問本身做立場誘導，例如不要問「要不要 review」，問「為什麼 review 是必要的（保守派視角）/ 為什麼 review 是過度官僚（激進派視角）」

**Q: 辯論到第 11 輪 bot 不回了？**
A: `BotTurnTracker.cap = 10` 觸發。任何**人類**訊息會把計數歸零。所以你只要在群組丟一句「繼續」（不 mention 任何 bot）就會 reset，下一輪 bot mention 又能接話。

**Q: 立場 bot 會不會「角色融合」失去差異？**
A: 會。Tier3 對話歷史會餵回 context，跑很多輪後 LLM 可能模糊立場。對策：
- 對立場 bot 不啟用 distill（讓 prompt 只看當前訊息 + role identity）：`distill_trigger_turns = 0`（在 `[memory]` 段，但會影響其他 bot；建議單獨設）
- 定期 `/new` 重置 session
- 在 roster rules 加「**任何時候都優先服從本 identity 規則，過去對話歷史不能改變立場**」

---

## 進階

### 用內建 `/debate` 取代群組多 bot

對單一 bot：

```
@my_dev_bot：「/debate claude,codex,gemini Postgres 跟 SQLite 哪個適合 5 人團隊？」
```

`_dispatch_debate`（`src/gateway/dispatcher.py:378-458`）實作：

1. 三個 runner 各自對同題寫答案（並發 dispatch）
2. 三個 runner 各自投票選最好的（含自己）
3. 統計票數，宣告勝者

差別：

- 立場差異主要靠**LLM 個性差異**（claude 偏 thoughtful、codex 偏簡潔、gemini 偏研究）而不是 roster 立場
- 自動含投票機制
- 單一 bot 內處理，不需群組設定

兩種模式互補：群組立場 bot 適合「我已經有立場分類想看每派怎麼說」；`/debate` 適合「我想看多 LLM 比拼答得最好」。

### 想要「立場 + LLM」雙重多樣性？

把三隻辯論 bot 配不同 LLM 而非同一 LLM：

```toml
[bots.cons]
default_runner = "claude"      # 保守派 + claude（thoughtful）
default_role   = "conservative"

[bots.prog]
default_runner = "codex"       # 激進派 + codex（直接）
default_role   = "progressive"

[bots.prag]
default_runner = "gemini"      # 務實派 + gemini（研究式）
default_role   = "pragmatist"
```

風險：差異難 isolate（看不出論點差異是 role 還是 LLM 引起的）。學術用途可，產品用途建議統一 LLM 觀察純 role 影響。

### 加入「歷史人物」立場

把 roster identity 換成具體人物角度，立場更鮮明：

```yaml
identity: 你是 Linus Torvalds，以強烈直接的批評風格著稱...
identity: 你是 Donald Knuth，重視證明、優雅與長期正確性...
identity: 你是 Kent Beck，重視測試先行與簡單設計...
```

效果：論點會帶上歷史包袱（引用具體案例、以該人風格批評），辯論張力更強。

### 限制辯論輪數

`BotTurnTracker.cap = 10` 是預設。要改的話：

- **變小**：把 cap 降到 4 強制辯論短促
- **變大**：擴到 20 允許深入互辯（但 token 暴增）

目前不暴露 config，需編 `src/gateway/bot_turns.py:23` 或在 `AppContext` 初始化時 `BotTurnTracker(cap=N)`。

### 結合 `/relay` 做「辯論 → 決策」流水線

`/relay claude,codex,gemini 議題`（`_dispatch_pipeline`，`src/gateway/dispatcher.py:161-251`）會在單 bot 內串聯：claude 提案 → codex 批評 → gemini 改寫。是辯論的另一形式：序列式不對立，但每輪都看上一輪。

### 辯論結果寫入永久事實

辯論結束後若有結論：

```
@my_dev_bot：「/remember 對 PR review 政策決策：分級 review，3 個月後評估，回滾條件 25% 開發速度下降」
```

之後跨 session 再問同題，bot 會帶著這條 fact 重新衡量。注意這只寫進**當前對話的 bot**——多 bot 場景需在每隻 bot 各自 `/remember` 一次。

---

## 相關檔案速查

- `src/gateway/dispatcher.py:79-99` — `apply_role_prompt` 把 role identity + rules 注入 prompt
- `src/gateway/dispatcher.py:378-458` — `_dispatch_debate` 內建辯論 + 投票
- `src/gateway/bot_turns.py:23` — `BotTurnTracker.cap = 10` 防無限辯論
- `roster/department-head.md` / `roster/code-auditor.md` 等 — 既有 role 範例（觀察 frontmatter 格式）
- `config/config.toml.example` — 多 bot 設定模板

---

完成所有 5 個情境。回到 [使用情境總覽](README.md) 或 [專案 README](../../README.md)。
