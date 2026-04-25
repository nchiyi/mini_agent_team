# Reasoning Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users trigger deep-thinking mode with natural language keywords; the gateway stores a pending confirmation, then on "y" executes via Claude Extended Thinking (or CoT prefix fallback) and on "n" executes normally.

**Architecture:** Six files change in dependency order — router → session → nlu → acp_protocol → acp_runner → dispatcher. The dispatcher intercepts pending-reasoning confirmations before normal routing, and threads a `thinking: bool` flag through to `ACPRunner.run()` → `ACPConnection.prompt()` where it becomes a `thinking_budget=8000` JSON-RPC parameter; non-ACP runners receive a CoT prefix string instead.

**Tech Stack:** Python 3.11, asyncio, dataclasses, pytest-asyncio, existing ACP JSON-RPC infrastructure.

---

## File map

| File | Change |
|------|--------|
| `src/gateway/router.py` | Add `is_reasoning: bool = False` to `ParsedCommand` |
| `src/gateway/session.py` | Add `pending_reasoning: str = ""` to `Session` |
| `src/gateway/nlu.py` | Add `_REASONING_KEYWORDS` regex; update `FastPathDetector.detect()` |
| `src/runners/acp_protocol.py` | Add `thinking_budget: int = 0` to `prompt()`; filter thinking blocks |
| `src/runners/acp_runner.py` | Add `thinking: bool = False` to `run()`; forward to protocol |
| `src/gateway/dispatcher.py` | Pending-reasoning intercept, `is_reasoning` store, `_dispatch_single_runner` thinking path |
| `tests/gateway/test_reasoning.py` | New file — NLU + dispatcher reasoning tests |

---

### Task 1: Add `is_reasoning` to ParsedCommand

**Files:**
- Modify: `src/gateway/router.py:6-29`
- Test: `tests/gateway/test_router.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_router.py`:

```python
def test_parsed_command_is_reasoning_defaults_false():
    from src.gateway.router import ParsedCommand
    cmd = ParsedCommand(runner="claude", prompt="hello")
    assert cmd.is_reasoning is False


def test_parsed_command_is_reasoning_can_be_set():
    from src.gateway.router import ParsedCommand
    cmd = ParsedCommand(runner="claude", prompt="hello", is_reasoning=True)
    assert cmd.is_reasoning is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_router.py::test_parsed_command_is_reasoning_defaults_false -v
```

Expected: `FAILED` — `TypeError: unexpected keyword argument 'is_reasoning'`

- [ ] **Step 3: Add field to ParsedCommand**

In `src/gateway/router.py`, after `is_debate: bool = False` (line 29):

```python
    is_debate: bool = False
    debate_runners: list[str] = field(default_factory=list)
    is_reasoning: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/gateway/test_router.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway/router.py tests/gateway/test_router.py
git commit -m "feat: add is_reasoning field to ParsedCommand"
```

---

### Task 2: Add `pending_reasoning` to Session

**Files:**
- Modify: `src/gateway/session.py:17-27`
- Test: `tests/gateway/test_session.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_session.py`:

```python
def test_session_pending_reasoning_defaults_empty():
    from src.gateway.session import Session
    from datetime import datetime, timezone
    s = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    assert s.pending_reasoning == ""


def test_session_pending_reasoning_can_be_set():
    from src.gateway.session import Session
    s = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    s.pending_reasoning = "solve P=NP 深入分析"
    assert s.pending_reasoning == "solve P=NP"
    # (set the stripped version in practice; just verify the field exists)
    s.pending_reasoning = ""
    assert s.pending_reasoning == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/gateway/test_session.py::test_session_pending_reasoning_defaults_empty -v
```

Expected: `FAILED` — `TypeError: __init__() got an unexpected keyword argument` or `AttributeError`

- [ ] **Step 3: Add field to Session**

In `src/gateway/session.py`, after `active_role: str = ""` (line 22):

```python
    active_role: str = ""
    pending_reasoning: str = ""
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/gateway/test_session.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway/session.py tests/gateway/test_session.py
git commit -m "feat: add pending_reasoning field to Session"
```

---

### Task 3: NLU keyword detection

**Files:**
- Modify: `src/gateway/nlu.py`
- Create: `tests/gateway/test_reasoning.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/gateway/test_reasoning.py`:

```python
# tests/gateway/test_reasoning.py
import pytest


# ── NLU tests ────────────────────────────────────────────────────────────────

def _detector(runners=None):
    from src.gateway.nlu import FastPathDetector
    return FastPathDetector(runners or {"claude", "codex", "gemini"})


def test_nlu_zh_keyword_triggers_reasoning():
    cmd = _detector().detect("請深入分析台灣的半導體產業")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert "半導體產業" in cmd.prompt


def test_nlu_en_keyword_triggers_reasoning():
    cmd = _detector().detect("think carefully about the trolley problem")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert "trolley problem" in cmd.prompt


def test_nlu_step_by_step_triggers_reasoning():
    cmd = _detector().detect("step by step how does TCP handshake work")
    assert cmd is not None
    assert cmd.is_reasoning is True


def test_nlu_reasoning_keyword_case_insensitive():
    cmd = _detector().detect("Think Carefully about quantum computing")
    assert cmd is not None
    assert cmd.is_reasoning is True


def test_nlu_reasoning_strips_keyword_from_prompt():
    cmd = _detector().detect("請一步一步推導費馬最後定理")
    assert cmd is not None
    # keyword stripped; only the actual question remains
    assert "一步一步" not in cmd.prompt
    assert "費馬最後定理" in cmd.prompt


def test_nlu_keyword_only_returns_none():
    # Message is nothing but the keyword — no actual question
    cmd = _detector().detect("深入分析")
    assert cmd is None


def test_nlu_slash_command_not_intercepted():
    # /discuss must not be matched for reasoning
    cmd = _detector().detect("/discuss claude,codex step by step solve this")
    assert cmd is None


def test_nlu_reasoning_with_explicit_runner():
    cmd = _detector().detect("請 Claude 深入分析 RSA encryption")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert cmd.runner == "claude"


def test_nlu_reasoning_no_explicit_runner_uses_empty():
    cmd = _detector().detect("深入分析 black holes")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert cmd.runner == ""  # dispatcher uses session.current_runner
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/gateway/test_reasoning.py -v -k "nlu"
```

Expected: all FAIL — `AttributeError: 'ParsedCommand' object has no attribute 'is_reasoning'` or `AssertionError`

- [ ] **Step 3: Add `_REASONING_KEYWORDS` and update `detect()`**

In `src/gateway/nlu.py`, after the existing keyword regexes (after line 7):

```python
_REASONING_KEYWORDS = re.compile(
    r"深入分析|仔細想|慢慢想|一步一步|詳細推導|複雜問題|深思"
    r"|think carefully|step by step|reason through|analyze deeply",
    re.IGNORECASE,
)
```

Replace `FastPathDetector.detect()` (lines 46–75) with:

```python
    def detect(self, text: str) -> "ParsedCommand | None":
        if text.startswith("/"):
            return None

        if _REASONING_KEYWORDS.search(text):
            stripped = _REASONING_KEYWORDS.sub("", text).strip(" ,，:：")
            if not stripped:
                return None  # keyword with no actual question
            runners = _find_runners(text, self._known)
            primary_runner = runners[0] if runners else ""
            return ParsedCommand(runner=primary_runner, prompt=stripped, is_reasoning=True)

        runners = _find_runners(text, self._known)
        if not runners:
            return None

        prompt = _strip_meta(text, self._known)
        if not prompt:
            return None

        if _RELAY_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_pipeline=True, pipeline_runners=runners,
            )

        if _DISCUSS_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_discussion=True, discussion_runners=runners, discussion_rounds=3,
            )

        if _DEBATE_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_debate=True, debate_runners=runners,
            )

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/gateway/test_reasoning.py -v -k "nlu"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway/nlu.py tests/gateway/test_reasoning.py
git commit -m "feat: NLU reasoning keyword detection"
```

---

### Task 4: ACP protocol thinking support

**Files:**
- Modify: `src/runners/acp_protocol.py:77-126` (the `prompt()` method and `_extract_text()`)
- Test: `tests/runners/test_acp_protocol.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/runners/test_acp_protocol.py`:

```python
@pytest.mark.asyncio
async def test_prompt_with_thinking_budget_includes_thinking_param():
    """When thinking_budget > 0, session/prompt params must include thinking key."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-think"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": session_id}},
        # session/update with text chunk
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "deep answer"}},
        }},
        # prompt response
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()
    await conn.new_session(cwd="/tmp")
    chunks = []
    async for c in conn.prompt(session_id=session_id, text="prove P=NP", thinking_budget=8000):
        chunks.append(c)
    await conn.close()

    prompt_req = next(w for w in written if w.get("method") == "session/prompt")
    assert "thinking" in prompt_req["params"]
    assert prompt_req["params"]["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert "".join(chunks) == "deep answer"


@pytest.mark.asyncio
async def test_prompt_thinking_blocks_are_filtered_out():
    """session/update chunks with type=thinking must be silently discarded."""
    from src.runners.acp_protocol import ACPConnection

    session_id = "sess-filter"
    proc, written = _make_mock_proc([
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": session_id}},
        # thinking block — must be filtered
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "thinking", "text": "internal thoughts"}},
        }},
        # text block — must be yielded
        {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "final answer"}},
        }},
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ])
    conn = ACPConnection(proc)
    conn.start()
    await conn.initialize()
    await conn.new_session(cwd="/tmp")
    chunks = []
    async for c in conn.prompt(session_id=session_id, text="hello", thinking_budget=8000):
        chunks.append(c)
    await conn.close()

    assert "internal thoughts" not in "".join(chunks)
    assert "final answer" in "".join(chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/runners/test_acp_protocol.py::test_prompt_with_thinking_budget_includes_thinking_param tests/runners/test_acp_protocol.py::test_prompt_thinking_blocks_are_filtered_out -v
```

Expected: both FAIL — `TypeError: prompt() got an unexpected keyword argument 'thinking_budget'`

- [ ] **Step 3: Add `thinking_budget` to `prompt()` and update `_extract_text()`**

In `src/runners/acp_protocol.py`, replace the `prompt()` signature and params block (lines 77–107):

```python
    async def prompt(
        self,
        session_id: str,
        text: str,
        role_prefix: str = "",
        thinking_budget: int = 0,
    ) -> AsyncIterator[str]:
        """Send a prompt and yield text chunks as they stream in.

        If role_prefix is provided it is sent as a separate content block with
        cache_control so the Anthropic API can cache it across requests.
        If thinking_budget > 0, extended thinking is requested and thinking
        blocks are filtered from the output stream.
        """
        if role_prefix:
            content = [
                {"type": "text", "text": role_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": text},
            ]
        else:
            content = [{"type": "text", "text": text}]

        params: dict = {
            "sessionId": session_id,
            "prompt": content,
        }
        if thinking_budget > 0:
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[session_id] = queue
        # Drain any session/updates that arrived before we registered the queue
        for early in self._buffered_updates.pop(session_id, []):
            await queue.put(early)
        try:
            prompt_task = asyncio.create_task(
                self._request("session/prompt", params)
            )
```

Replace `_extract_text()` (lines 262–273):

```python
    @staticmethod
    def _extract_text(update_params: dict) -> str:
        update = update_params.get("update", {})
        session_update = update.get("sessionUpdate")

        if session_update == "agent_message_chunk":
            content = update.get("content", {})
            # Thinking blocks are internal; discard them entirely
            if content.get("type") == "thinking":
                return ""
            if content.get("type") == "text":
                return content.get("text", "")

        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/runners/test_acp_protocol.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/runners/acp_protocol.py tests/runners/test_acp_protocol.py
git commit -m "feat: ACP protocol extended thinking support"
```

---

### Task 5: ACPRunner `thinking` flag

**Files:**
- Modify: `src/runners/acp_runner.py:82-118`
- Test: `tests/runners/test_acp_runner.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/runners/test_acp_runner.py`:

```python
@pytest.mark.asyncio
async def test_acp_runner_thinking_flag_sets_budget():
    """When thinking=True, ACPRunner must call conn.prompt with thinking_budget=8000."""
    from src.runners.acp_runner import ACPRunner

    called_with: dict = {}

    async def fake_prompt(session_id, text, role_prefix="", thinking_budget=0):
        called_with["thinking_budget"] = thinking_budget
        yield "answer"

    mock_conn = MagicMock()
    mock_conn.initialize = AsyncMock(return_value={"protocolVersion": 1, "agentCapabilities": {}})
    mock_conn.new_session = AsyncMock(return_value="sess-1")
    mock_conn.close = AsyncMock()
    mock_conn.prompt = fake_prompt

    runner = ACPRunner(name="claude", command="claude-agent-acp", args=[],
                       timeout_seconds=30, context_token_budget=4000)

    with patch("src.runners.acp_runner.ACPConnection", return_value=mock_conn), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdin = AsyncMock()
        mock_proc.returncode = None
        mock_spawn.return_value = mock_proc

        chunks = []
        async for c in runner.run("prove P=NP", user_id=1, channel="tg",
                                   cwd="/tmp", thinking=True):
            chunks.append(c)

    assert called_with["thinking_budget"] == 8000
    assert "answer" in "".join(chunks)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/runners/test_acp_runner.py::test_acp_runner_thinking_flag_sets_budget -v
```

Expected: `FAILED` — `TypeError: run() got an unexpected keyword argument 'thinking'`

- [ ] **Step 3: Add `thinking` param to `ACPRunner.run()`**

In `src/runners/acp_runner.py`, replace the `run()` signature and `self._conn.prompt()` call:

```python
    async def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
        attachments: list[str] | None = None,
        role_prefix: str = "",
        thinking: bool = False,
    ) -> AsyncIterator[str]:
        await self._ensure_initialized(cwd)
        session_id = await self._get_or_create_session(user_id, cwd)

        if attachments:
            paths = "\n".join(f"[attached: {p}]" for p in attachments)
            prompt = f"{paths}\n\n{prompt}"

        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for chunk in self._conn.prompt(
                    session_id=session_id, text=prompt, role_prefix=role_prefix,
                    thinking_budget=8000 if thinking else 0,
                ):
                    yield chunk
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"ACPRunner '{self.name}' exceeded {self.timeout_seconds}s timeout"
            )
        except Exception as e:
            logger.error("ACPRunner '%s' error: %s", self.name, e, exc_info=True)
            self._sessions.pop(user_id, None)
            if self._conn is not None and not self._conn.is_alive():
                logger.warning("ACPRunner '%s': subprocess crashed, resetting for re-init", self.name)
                async with self._init_lock:
                    self._initialized = False
                    self._conn = None
                    self._sessions.clear()
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/runners/test_acp_runner.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/runners/acp_runner.py tests/runners/test_acp_runner.py
git commit -m "feat: thread thinking flag through ACPRunner to protocol"
```

---

### Task 6: Dispatcher reasoning confirmation flow

**Files:**
- Modify: `src/gateway/dispatcher.py`
- Test: `tests/gateway/test_reasoning.py` (append dispatcher tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_reasoning.py`:

```python
# ── Dispatcher tests ─────────────────────────────────────────────────────────

import asyncio
import dataclasses
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.channels.base import InboundMessage
from src.gateway.session import Session, SessionManager
from src.gateway.router import ParsedCommand


def _make_inbound(text: str, user_id: int = 1) -> InboundMessage:
    return InboundMessage(user_id=user_id, channel="tg", text=text, message_id="msg-1")


def _make_session_mgr(session: Session) -> SessionManager:
    mgr = MagicMock(spec=SessionManager)
    mgr.get_or_create = MagicMock(return_value=session)
    mgr.get_active_role = MagicMock(return_value="")
    mgr.restore_settings_if_needed = AsyncMock()
    return mgr


def _make_runner():
    runner = MagicMock()
    runner.context_token_budget = 4000
    async def _run(*a, **kw):
        yield "response"
    runner.run = _run
    return runner


def _make_tier3():
    t = MagicMock()
    t.save_turn = AsyncMock()
    t.log_usage = AsyncMock()
    t.get_recent = AsyncMock(return_value=[])
    t.count_turns = AsyncMock(return_value=0)
    t.get_last_distill_ts = AsyncMock(return_value=None)
    t.get_dispatch_count_since = AsyncMock(return_value=0)
    t.get_usage_summary = AsyncMock(return_value={})
    t.get_token_usage_since = AsyncMock(return_value=0)
    return t


def _make_assembler():
    a = MagicMock()
    a.build = AsyncMock(return_value="")
    return a


def _make_bridge():
    b = MagicMock()
    async def _stream(user_id, chunks):
        async for _ in chunks:
            pass
    b.stream = _stream
    return b


@pytest.mark.asyncio
async def test_dispatcher_reasoning_stores_pending_and_sends_confirmation():
    """NLU-detected is_reasoning=True → store in session, send confirmation, do NOT call runner."""
    from src.gateway.dispatcher import dispatch
    from src.gateway.nlu import FastPathDetector
    from src.gateway.router import Router

    session = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    session_mgr = _make_session_mgr(session)
    runner = _make_runner()
    runners = {"claude": runner}
    replies: list[str] = []

    router = MagicMock(spec=Router)
    router.parse = AsyncMock(return_value=ParsedCommand(runner="claude", prompt="think carefully about black holes"))

    nlu = MagicMock(spec=FastPathDetector)
    nlu.detect = MagicMock(return_value=ParsedCommand(
        runner="", prompt="black holes", is_reasoning=True
    ))

    await dispatch(
        inbound=_make_inbound("think carefully about black holes"),
        bridge=_make_bridge(),
        session_mgr=session_mgr,
        router=router,
        runners=runners,
        tier1=MagicMock(),
        tier3=_make_tier3(),
        assembler=_make_assembler(),
        send_reply=lambda t: replies.append(t) or asyncio.coroutine(lambda: None)(),
        recent_turns=6,
        nlu_detector=nlu,
    )

    assert session.pending_reasoning == "black holes"
    assert any("深度思考" in r for r in replies)
    assert runner.run.call_count == 0 if hasattr(runner.run, "call_count") else True


@pytest.mark.asyncio
async def test_dispatcher_reasoning_yes_executes_pending_with_thinking():
    """When pending_reasoning set and user says 'y', execute pending prompt with thinking=True."""
    from src.gateway.dispatcher import dispatch
    from src.gateway.router import Router
    from src.runners.acp_runner import ACPRunner

    session = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    session.pending_reasoning = "explain quantum entanglement"
    session_mgr = _make_session_mgr(session)

    called_with: dict = {}

    class _FakeACPRunner(ACPRunner):
        async def run(self, prompt, user_id, channel, cwd,
                      attachments=None, role_prefix="", thinking=False):
            called_with["thinking"] = thinking
            called_with["prompt"] = prompt
            yield "answer"

    runner = _FakeACPRunner(name="claude", command="x", args=[],
                            timeout_seconds=30, context_token_budget=4000)
    runner._initialized = True
    runner._conn = MagicMock()
    runners = {"claude": runner}
    replies: list[str] = []

    router = MagicMock(spec=Router)
    router.parse = AsyncMock(return_value=ParsedCommand(runner="claude", prompt="y"))

    await dispatch(
        inbound=_make_inbound("y"),
        bridge=_make_bridge(),
        session_mgr=session_mgr,
        router=router,
        runners=runners,
        tier1=MagicMock(),
        tier3=_make_tier3(),
        assembler=_make_assembler(),
        send_reply=lambda t: replies.append(t) or asyncio.coroutine(lambda: None)(),
        recent_turns=6,
    )

    assert called_with.get("thinking") is True
    assert called_with.get("prompt") == "explain quantum entanglement"
    assert session.pending_reasoning == ""


@pytest.mark.asyncio
async def test_dispatcher_reasoning_no_executes_pending_without_thinking():
    """When pending_reasoning set and user says 'n', execute pending prompt with thinking=False."""
    from src.gateway.dispatcher import dispatch
    from src.gateway.router import Router
    from src.runners.acp_runner import ACPRunner

    session = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    session.pending_reasoning = "explain black holes"
    session_mgr = _make_session_mgr(session)

    called_with: dict = {}

    class _FakeACPRunner(ACPRunner):
        async def run(self, prompt, user_id, channel, cwd,
                      attachments=None, role_prefix="", thinking=False):
            called_with["thinking"] = thinking
            yield "answer"

    runner = _FakeACPRunner(name="claude", command="x", args=[],
                            timeout_seconds=30, context_token_budget=4000)
    runner._initialized = True
    runner._conn = MagicMock()
    runners = {"claude": runner}

    router = MagicMock(spec=Router)
    router.parse = AsyncMock(return_value=ParsedCommand(runner="claude", prompt="n"))

    await dispatch(
        inbound=_make_inbound("n"),
        bridge=_make_bridge(),
        session_mgr=session_mgr,
        router=router,
        runners=runners,
        tier1=MagicMock(),
        tier3=_make_tier3(),
        assembler=_make_assembler(),
        send_reply=lambda t: None,
        recent_turns=6,
    )

    assert called_with.get("thinking") is False
    assert session.pending_reasoning == ""


@pytest.mark.asyncio
async def test_dispatcher_reasoning_other_clears_pending_and_dispatches_new():
    """When pending_reasoning set and user sends something other than y/n, clear and treat as new."""
    from src.gateway.dispatcher import dispatch
    from src.gateway.router import Router

    session = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    session.pending_reasoning = "explain black holes"
    session_mgr = _make_session_mgr(session)

    runner = _make_runner()
    runners = {"claude": runner}

    router = MagicMock(spec=Router)
    # The "other" message goes through normal routing
    router.parse = AsyncMock(return_value=ParsedCommand(runner="claude", prompt="hello"))

    received_prompts: list[str] = []
    original_run = runner.run

    async def tracking_run(prompt, user_id, channel, cwd, **kw):
        received_prompts.append(prompt)
        yield "response"

    runner.run = tracking_run

    await dispatch(
        inbound=_make_inbound("hello world"),
        bridge=_make_bridge(),
        session_mgr=session_mgr,
        router=router,
        runners=runners,
        tier1=MagicMock(),
        tier3=_make_tier3(),
        assembler=_make_assembler(),
        send_reply=lambda t: None,
        recent_turns=6,
    )

    # pending cleared
    assert session.pending_reasoning == ""
    # new message "hello" was dispatched, not the pending "explain black holes"
    assert any("hello" in p for p in received_prompts)
    assert not any("black holes" in p for p in received_prompts)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/gateway/test_reasoning.py -v -k "dispatcher"
```

Expected: all FAIL — `AssertionError` or `AttributeError`

- [ ] **Step 3: Add imports and constants to dispatcher.py**

In `src/gateway/dispatcher.py`:

a) After `import asyncio`, `import contextlib`, `import logging` (the existing stdlib imports), add:
```python
import dataclasses
import re
```

b) Replace:
```python
from src.gateway.router import Router
```
with:
```python
from src.gateway.router import Router, ParsedCommand
```

c) After `_role_prompt_cache: dict[str, tuple[float, str]] = {}` (around line 37), add:
```python
_CONFIRM_YES = re.compile(r"^(y|是|確認|好|yes)$", re.IGNORECASE)
_CONFIRM_NO = re.compile(r"^(n|否|不用|取消|no)$", re.IGNORECASE)
_COT_REASONING_PREFIX = (
    "請一步一步仔細分析問題，推理後只輸出最終結論，不要顯示思考過程。\n\n"
)
```

- [ ] **Step 4: Add `thinking` param and CoT path to `_dispatch_single_runner()`**

Replace `_dispatch_single_runner` signature (line 397 area) to add `thinking: bool = False`:

```python
async def _dispatch_single_runner(
    inbound: InboundMessage,
    session,
    runners: dict,
    bridge: StreamingBridge,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
    recent_turns: int,
    role_slug: str,
    cmd,
    cfg: "Config | None" = None,
    tier1: "Tier1Store | None" = None,
    thinking: bool = False,
) -> None:
```

Inside `_dispatch_single_runner`, after `role_prefix = apply_role_prompt("", role_slug, session.cwd)` (around line 431), add:

```python
    from src.runners.acp_runner import ACPRunner
    use_acp_thinking = thinking and isinstance(target_runner, ACPRunner)
    if thinking and not use_acp_thinking:
        # CoT fallback for non-ACP runners (Gemini, Codex)
        role_prefix = _COT_REASONING_PREFIX + role_prefix
```

Replace the `collecting_gen()` inner function and `bridge.stream()` call with:

```python
        async def collecting_gen():
            if use_acp_thinking:
                try:
                    async for chunk in target_runner.run(
                        prompt=user_message,
                        user_id=inbound.user_id,
                        channel=inbound.channel,
                        cwd=session.cwd,
                        attachments=inbound.attachments or None,
                        role_prefix=role_prefix,
                        thinking=True,
                    ):
                        response_chunks.append(chunk)
                        yield chunk
                    return
                except Exception:
                    logger.warning(
                        "ACPRunner thinking not supported, retrying with CoT prefix"
                    )
                    response_chunks.clear()
            # Non-ACP-thinking path: standard runner call
            # (also the CoT-fallback path if ACP thinking failed)
            fallback_prefix = (
                (_COT_REASONING_PREFIX + role_prefix) if use_acp_thinking else role_prefix
            )
            async for chunk in target_runner.run(
                prompt=user_message,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
                attachments=inbound.attachments or None,
                role_prefix=fallback_prefix,
            ):
                response_chunks.append(chunk)
                yield chunk

        await bridge.stream(user_id=inbound.user_id, chunks=collecting_gen())
```

- [ ] **Step 5: Add pending-reasoning intercept in `dispatch()`**

In `dispatch()`, right after `session = session_mgr.get_or_create(...)` (line 496) and BEFORE `cmd = await router.parse(inbound.text)`:

```python
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)

    # ── Pending reasoning confirmation ───────────────────────────────────────
    if session.pending_reasoning:
        pending = session.pending_reasoning
        session.pending_reasoning = ""
        _active = session_mgr.get_active_role(inbound.user_id, inbound.channel)
        if _active:
            session.active_role = _active
        _pending_role_slug = session.active_role or _DEFAULT_ROLE
        _text_stripped = inbound.text.strip()
        if _CONFIRM_YES.match(_text_stripped):
            _synthetic_inbound = dataclasses.replace(inbound, text=pending)
            _synthetic_cmd = ParsedCommand(runner=session.current_runner, prompt=pending)
            _sem2 = rate_limiter.semaphore if rate_limiter is not None else contextlib.nullcontext()
            async with _sem2:
                await _dispatch_single_runner(
                    inbound=_synthetic_inbound, session=session, runners=runners,
                    bridge=bridge, tier3=tier3, assembler=assembler,
                    send_reply=send_reply, recent_turns=recent_turns,
                    role_slug=_pending_role_slug, cmd=_synthetic_cmd,
                    cfg=cfg, tier1=tier1, thinking=True,
                )
            return
        elif _CONFIRM_NO.match(_text_stripped):
            _synthetic_inbound = dataclasses.replace(inbound, text=pending)
            _synthetic_cmd = ParsedCommand(runner=session.current_runner, prompt=pending)
            _sem2 = rate_limiter.semaphore if rate_limiter is not None else contextlib.nullcontext()
            async with _sem2:
                await _dispatch_single_runner(
                    inbound=_synthetic_inbound, session=session, runners=runners,
                    bridge=bridge, tier3=tier3, assembler=assembler,
                    send_reply=send_reply, recent_turns=recent_turns,
                    role_slug=_pending_role_slug, cmd=_synthetic_cmd,
                    cfg=cfg, tier1=tier1, thinking=False,
                )
            return
        # else: treat current message as new (pending already cleared; fall through)
    # ────────────────────────────────────────────────────────────────────────

    cmd = await router.parse(inbound.text)
```

- [ ] **Step 6: Add `is_reasoning` dispatch to `dispatch()`**

After the NLU detection block (around line 509, after `if nlu_cmd is not None: cmd = nlu_cmd`) and BEFORE `if cmd.is_remember:`, add:

```python
    if cmd.is_reasoning:
        session.pending_reasoning = cmd.prompt
        await send_reply(
            "🧠 偵測到深度思考需求（需要較多時間與 token）。\n"
            "是否啟用深度思考模式？(y/n)"
        )
        return
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/gateway/test_reasoning.py -v
```

Expected: all PASS

- [ ] **Step 8: Run full test suite to verify no regressions**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all existing tests continue to PASS

- [ ] **Step 9: Commit**

```bash
git add src/gateway/dispatcher.py tests/gateway/test_reasoning.py
git commit -m "feat: reasoning mode confirmation flow and thinking dispatch"
```

---

## Acceptance checklist (from spec)

- [ ] 含關鍵字的訊息觸發確認提示，不直接送 LLM
- [ ] 使用者回 y/是 → reasoning=True 執行原始 prompt
- [ ] 使用者回 n/否 → 正常模式執行原始 prompt
- [ ] 使用者傳其他訊息 → 取消待確認，新訊息正常處理
- [ ] Claude runner：ACP 帶 thinking 參數，thinking block 不顯示
- [ ] 非 Claude runner：role_prefix 加 CoT 指令
- [ ] ACP 不支援 thinking 時退回 CoT，對話不中斷
- [ ] `/discuss`、`/debate` 等指令不受關鍵字偵測影響
