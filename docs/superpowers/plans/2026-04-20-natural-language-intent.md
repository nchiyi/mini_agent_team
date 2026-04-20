# Natural Language Intent Detection — Feasibility Plan

**Goal:** Allow users to trigger relay / discuss / debate modes using natural language instead of slash commands.

**Examples of what should work:**
```
"請讓 claude 和 gemini 接力幫我設計這個 API"
"讓三個 AI 辯論一下：Python 還是 Go 比較好"
"用討論模式，claude 和 codex 幫我想這個架構"
"relay claude, codex: write a Python sort function"
"have claude and gemini debate this: microservices vs monolith"
```

---

## Feasibility Assessment: 3 Approaches

### Approach A — Keyword / Regex NLU
**How it works:** Router scans for trigger words (接力, relay, 討論, discuss, 辯論, debate, 三方) + runner names before falling through to the default runner.

**Pros:**
- Zero latency (no extra API call)
- No extra cost
- Works offline

**Cons:**
- Fragile — misses variations ("幫我讓兩個模型互相討論", "ask claude then gemini")
- Needs a maintained keyword list for both Chinese and English
- Can't reliably extract the runners list from free-form text

**Verdict:** Good as a fast-path pre-filter. Not sufficient alone.

---

### Approach B — LLM Intent Classifier
**How it works:** Before dispatching any message, send it to a lightweight runner with a structured prompt. Get back JSON indicating mode + runners + cleaned prompt. Then dispatch normally.

```
System prompt:
  You are an intent classifier. Given a user message, output JSON:
  {
    "mode": "single" | "relay" | "discuss" | "debate",
    "runners": ["claude", "gemini", ...],   // only known runners
    "prompt": "the actual question/task, stripped of meta-instructions",
    "confidence": 0.0-1.0
  }
  Known runners: {runners_list}
  If mode is "single" or confidence < 0.7, set mode="single" and runners=[].
```

**Pros:**
- High accuracy across languages (Chinese, English, mixed)
- Understands context and intent variations
- Extensible to future modes without code changes

**Cons:**
- Adds ~1-3s latency per message (one extra runner call)
- Extra token cost for every message, even non-multi-agent ones
- Requires at least one runner to be configured and available

**Verdict:** Best accuracy, but latency cost applied to ALL messages is unacceptable for normal use.

---

### Approach C — Hybrid (Recommended)
**How it works:** Two-phase detection:

1. **Fast-path (regex):** Check for explicit multi-agent trigger patterns. If matched with high confidence, dispatch without LLM classification.
2. **LLM classifier (on ambiguity):** Only invoked when the fast-path detects a *weak signal* (e.g., runner names mentioned but no explicit mode keyword).

**Trigger heuristic for LLM fallback:**
- Message contains 2+ runner names AND any of: 接力/relay/討論/discuss/辯論/debate/比較/compare/互相/each other/讓它們/ask them
- Message does NOT start with `/` (explicit slash commands always bypass NLU)

**Result:** Normal messages → 0 extra latency. Ambiguous multi-agent messages → 1 LLM call.

**Estimated trigger rate:** ~5% of messages (users who intentionally invoke multi-agent without slash commands).

---

## Recommended Implementation: Approach C

### Architecture

```
User message
    │
    ├─ Starts with /? ──→ Router (existing slash command logic)
    │
    └─ No slash?
         │
         ├─ Fast-path regex NLU ──→ high confidence? ──→ ParsedCommand (relay/discuss/debate)
         │
         └─ Weak signal detected?
               │
               Yes ──→ LLM Classifier ──→ confidence ≥ 0.7? ──→ ParsedCommand
               │                                └─ No ──→ single runner (default)
               │
               No ──→ single runner (default)
```

### New file: `src/gateway/nlu.py`

Responsibilities:
- `FastPathDetector.detect(text, known_runners)` → `ParsedCommand | None`
- `LLMIntentClassifier.classify(text, runner, known_runners)` → `ParsedCommand | None`
- `IntentDetector.detect(text, known_runners, runners_dict)` → `ParsedCommand | None` (orchestrates both)

### Fast-path patterns (covers ~80% of natural language cases)

| Pattern | Mode |
|---------|------|
| `(接力\|relay\|chain\|one after)` + 2 runner names | relay |
| `(討論\|discuss\|對話\|exchange\|conversation between)` + 2 runner names | discuss |
| `(辯論\|debate\|argue\|比較\|compare\|誰比較好\|which is better)` + 3 runner names | debate |
| `(辯論\|debate)` + 2 runner names | debate (2-runner variant, needs spec change) |

Runner name matching: exact match + common aliases
- `claude` → claude, Claude, claude-code, claude code
- `codex` → codex, Codex, openai
- `gemini` → gemini, Gemini, google
- `kiro` → kiro, Kiro, aws

### LLM Classifier prompt (stored in `src/gateway/nlu.py`)

```python
_CLASSIFIER_PROMPT = """
You are an intent classifier for an AI gateway bot. Given a user message, output valid JSON only.

Known runners: {runners}

Output schema:
{{
  "mode": "single" | "relay" | "discuss" | "debate",
  "runners": [],
  "prompt": "<the actual question, with meta-instructions removed>",
  "confidence": <0.0-1.0>
}}

Rules:
- "relay": user wants sequential chaining (A then B then C)
- "discuss": user wants back-and-forth exchange between agents
- "debate": user wants parallel independent answers + voting/comparison
- "single": everything else
- If runners not specified, set runners=[]
- confidence < 0.7 → always set mode="single"

Message: {message}
"""
```

### Integration points

1. `src/gateway/nlu.py` — new file (FastPathDetector + LLMIntentClassifier + IntentDetector)
2. `main.py dispatch()` — call `IntentDetector.detect()` when `not cmd.is_pipeline and not cmd.is_discussion and not cmd.is_debate` and message has no `/`
3. `src/core/config.py` — add `nlu_enabled: bool = True` and `nlu_classifier_runner: str = ""` (empty = use default runner)

### Edge cases to handle

| Case | Handling |
|------|----------|
| Only 1 runner available | Fall back to single mode |
| LLM classifier itself errors | Catch + fall back to single mode silently |
| User says "use claude then gemini" but only claude configured | Relay with available runners only, warn user |
| Confidence exactly 0.7 | Treat as single (conservative) |
| Very short message ("debate this") without runners | Fall back to single (no runners to extract) |

---

## Implementation Order

1. **Task 1** — `src/gateway/nlu.py`: FastPathDetector (regex-based, no LLM)
2. **Task 2** — Wire FastPathDetector into `dispatch()` in main.py
3. **Task 3** — `src/gateway/nlu.py`: LLMIntentClassifier (LLM-based)
4. **Task 4** — Wire LLMIntentClassifier as fallback
5. **Task 5** — Add `nlu_enabled` / `nlu_classifier_runner` to config
6. **Task 6** — Tests + README update

**Estimated effort:** 4-6 hours.

---

## What does NOT change

- Slash commands (`/relay`, `/discuss`, `/debate`) continue to work exactly as before — NLU is additive, not replacing.
- Users who prefer explicit commands lose nothing.
- NLU can be disabled with `nlu_enabled = false` in config.
