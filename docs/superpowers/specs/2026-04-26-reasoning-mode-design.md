# Reasoning Mode — Design Spec

**Date:** 2026-04-26  
**Status:** Approved

---

## 背景

使用者提出高難度、需要深度推理的問題時，LLM 以一般模式回答容易產生幻覺或跳步。Reasoning Mode 讓使用者透過自然語言觸發「慢思考」模式，並在執行前徵求確認，避免非預期的高 token 消耗。

---

## 觸發關鍵字

中英文關鍵字，任一命中即觸發：

**中文：** 深入分析、仔細想、慢慢想、一步一步、詳細推導、複雜問題、深思

**英文：** think carefully、step by step、reason through、analyze deeply（大小寫不敏感）

觸發後關鍵字從 prompt 中剝除再送給 LLM。

---

## 改動範圍

| 檔案 | 改動 |
|------|------|
| `src/gateway/nlu.py` | 新增 `_REASONING_KEYWORDS` regex；`FastPathDetector.detect()` 偵測到關鍵字時回傳 `ParsedCommand(is_reasoning=True)` |
| `src/gateway/router.py` | `ParsedCommand` 加 `is_reasoning: bool = False` |
| `src/gateway/session.py` | `Session` dataclass 加 `pending_reasoning: str = ""` |
| `src/gateway/dispatcher.py` | 確認訊息邏輯 + y/n 判斷 + reasoning 路由 |
| `src/runners/acp_runner.py` | `run()` 加 `thinking: bool = False`，傳給 protocol |
| `src/runners/acp_protocol.py` | `prompt()` 加 `thinking_budget: int = 0`；帶入 JSON-RPC `thinking` 參數；從 stream 過濾 thinking block |

**不動：** discussion/debate/relay、記憶系統、其他 runner、roster 系統。

---

## 流程

### Phase 1 — 偵測與確認

```
使用者訊息（非 / 開頭）
   ↓
NLU FastPathDetector.detect()
   ├─ 命中 _REASONING_KEYWORDS？
   │     是 → ParsedCommand(is_reasoning=True, prompt=去除關鍵字後原文)
   │     否 → 正常流程（本文件後續略）
   ↓
dispatcher 偵測到 is_reasoning=True
   → 暫存 session.pending_reasoning = stripped_prompt
   → 回覆確認訊息：
     「🧠 偵測到深度思考需求（需要較多時間與 token）。
       是否啟用深度思考模式？(y/n)」
   → 結束此次 dispatch（不送 LLM）
```

### Phase 2 — 確認後執行

```
使用者下一則訊息
   ├─ session.pending_reasoning 非空（等待確認中）
   │
   ├─ 命中 y / 是 / 確認 / 好 / yes（大小寫不敏感）
   │     → 取出 pending_reasoning
   │     → 清除 session.pending_reasoning
   │     → dispatch with reasoning=True：
   │           if runner == "claude"
   │               → acp_runner.run(..., thinking=True)
   │               → acp_protocol.prompt(..., thinking_budget=8000)
   │               → JSON-RPC 帶 thinking={"type":"enabled","budget_tokens":8000}
   │               → stream 過濾：type=="thinking" 丟棄，type=="text" 輸出
   │           else（Gemini / Codex）
   │               → role_prefix 前加 CoT 指令：
   │                 「請一步一步仔細分析問題，推理後只輸出最終結論，
   │                   不要顯示思考過程。」
   │               → 正常 acp_runner.run()
   │
   ├─ 命中 n / 否 / 不用 / 取消 / no
   │     → 取出 pending_reasoning
   │     → 清除 session.pending_reasoning
   │     → dispatch with reasoning=False（正常流程）
   │
   └─ 其他訊息
         → 清除 session.pending_reasoning（取消待確認）
         → 視為全新訊息正常處理
```

---

## 錯誤處理

| 情況 | 行為 |
|------|------|
| claude-agent-acp 不支援 `thinking` 參數 | 自動退回 CoT prefix，不通知使用者 |
| Extended thinking 超時 | 同一般 runner timeout，回覆「思考超時，請再試一次」 |
| `pending_reasoning` 閒置超過 session idle 時間 | `SessionManager.release_idle()` 清除 Session 時一併清除 |
| Gemini / Codex 仍顯示思考過程 | mat 不額外過濾，由 LLM 自行決定輸出格式 |
| 使用者確認後又傳非 y/n 訊息 | 取消待確認，新訊息正常處理 |

---

## 技術細節

### NLU 關鍵字 regex

```python
_REASONING_KEYWORDS = re.compile(
    r"深入分析|仔細想|慢慢想|一步一步|詳細推導|複雜問題|深思"
    r"|think carefully|step by step|reason through|analyze deeply",
    re.IGNORECASE,
)
```

`FastPathDetector.detect()` 新增邏輯：
```python
if _REASONING_KEYWORDS.search(text):
    stripped = _REASONING_KEYWORDS.sub("", text).strip(" ,，:：")
    if not stripped:
        return None  # 訊息只有關鍵字，沒有實際問題，正常處理
    runners = _find_runners(text, self._known)
    primary_runner = runners[0] if runners else ""  # 空字串表示使用 session current_runner
    return ParsedCommand(runner=primary_runner, prompt=stripped, is_reasoning=True)
```

**runner 解析規則：** 訊息中若有明確提到 runner 名稱（如「請 Claude 深入分析…」），使用該 runner。否則 `runner=""` 由 dispatcher 退回使用 `session.current_runner`（與現有 slash command 邏輯一致）。

### ACP Protocol Extended Thinking

`acp_protocol.py` 的 `prompt()` 當 `thinking_budget > 0` 時，在 JSON-RPC params 加入：
```json
{
  "thinking": {
    "type": "enabled",
    "budget_tokens": 8000
  }
}
```

Response stream 的 chunk 若含 `"type": "thinking"` 則丟棄，僅輸出 `"type": "text"` 的 chunk。

### ParsedCommand 新欄位

```python
@dataclass
class ParsedCommand:
    ...
    is_reasoning: bool = False
```

### Session 新欄位

```python
@dataclass
class Session:
    ...
    pending_reasoning: str = ""
```

---

## 驗收條件

- [ ] 含關鍵字的訊息觸發確認提示，不直接送 LLM
- [ ] 使用者回 y/是 → 使用 reasoning=True 執行原始 prompt
- [ ] 使用者回 n/否 → 使用正常模式執行原始 prompt
- [ ] 使用者傳其他訊息 → 取消待確認，新訊息正常處理
- [ ] Claude runner：ACP 帶 thinking 參數，thinking block 不顯示給使用者
- [ ] 非 Claude runner：role_prefix 加 CoT 指令
- [ ] claude-agent-acp 不支援 thinking 時退回 CoT，對話不中斷
- [ ] `/discuss`、`/debate` 等指令不受關鍵字偵測影響
