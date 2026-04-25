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

    async def _send_reply(t):
        replies.append(t)

    await dispatch(
        inbound=_make_inbound("think carefully about black holes"),
        bridge=_make_bridge(),
        session_mgr=session_mgr,
        router=router,
        runners=runners,
        tier1=MagicMock(),
        tier3=_make_tier3(),
        assembler=_make_assembler(),
        send_reply=_send_reply,
        recent_turns=6,
        nlu_detector=nlu,
    )

    assert session.pending_reasoning == "black holes"
    assert any("深度思考" in r for r in replies)


@pytest.mark.asyncio
async def test_dispatcher_reasoning_yes_executes_pending_with_thinking():
    """When pending_reasoning is set and user says 'y', execute pending prompt with thinking=True."""
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
        send_reply=lambda t: None,
        recent_turns=6,
    )

    assert called_with.get("thinking") is True
    assert called_with.get("prompt") == "explain quantum entanglement"
    assert session.pending_reasoning == ""


@pytest.mark.asyncio
async def test_dispatcher_reasoning_no_executes_pending_without_thinking():
    """When pending_reasoning is set and user says 'n', execute pending prompt with thinking=False."""
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
    """When pending_reasoning is set and user sends something other than y/n, clear and treat as new."""
    from src.gateway.dispatcher import dispatch
    from src.gateway.router import Router

    session = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    session.pending_reasoning = "explain black holes"
    session_mgr = _make_session_mgr(session)

    runner = _make_runner()
    runners = {"claude": runner}

    router = MagicMock(spec=Router)
    router.parse = AsyncMock(return_value=ParsedCommand(runner="claude", prompt="hello"))

    received_prompts: list[str] = []

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
    # new message dispatched, not the pending one
    assert any("hello" in p for p in received_prompts)
    assert not any("black holes" in p for p in received_prompts)
