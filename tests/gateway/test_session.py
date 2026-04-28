# tests/gateway/test_session.py
import asyncio, pytest

def test_session_created_on_first_access():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    session = mgr.get_or_create(user_id=1, channel="telegram")
    assert session.user_id == 1
    assert session.channel == "telegram"
    assert session.current_runner == "claude"
    assert session.cwd == "/tmp"


def test_session_per_user_per_channel():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    s1 = mgr.get_or_create(user_id=1, channel="telegram")
    s2 = mgr.get_or_create(user_id=1, channel="discord")
    s3 = mgr.get_or_create(user_id=2, channel="telegram")
    assert s1 is not s2   # same user, different channel → different session
    assert s1 is not s3   # different user → different session
    assert mgr.get_or_create(user_id=1, channel="telegram") is s1  # idempotent


def test_session_set_runner():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    session = mgr.get_or_create(user_id=1, channel="telegram")
    session.current_runner = "codex"
    assert mgr.get_or_create(user_id=1, channel="telegram").current_runner == "codex"


def test_session_active_role_round_trip():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    mgr.set_active_role(user_id=1, channel="telegram", role="code-auditor")
    session = mgr.get_or_create(user_id=1, channel="telegram")
    assert session.active_role == "code-auditor"


def test_session_active_role_clear():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    mgr.set_active_role(user_id=1, channel="telegram", role="code-auditor")
    mgr.clear_active_role(user_id=1, channel="telegram")
    session = mgr.get_or_create(user_id=1, channel="telegram")
    assert session.active_role == ""


@pytest.mark.asyncio
async def test_session_idle_release():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=0, default_runner="claude", default_cwd="/tmp")
    s1 = mgr.get_or_create(user_id=1, channel="telegram")
    await asyncio.sleep(0.01)
    mgr.release_idle()
    s2 = mgr.get_or_create(user_id=1, channel="telegram")
    assert s1 is not s2   # old session was released, new one created


def test_session_pending_reasoning_defaults_empty():
    from src.gateway.session import Session
    from datetime import datetime, timezone
    s = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    assert s.pending_reasoning == ""


def test_session_pending_reasoning_can_be_set():
    from src.gateway.session import Session
    s = Session(user_id=1, channel="tg", current_runner="claude", cwd="/tmp")
    s.pending_reasoning = "solve P=NP 深入分析"
    assert s.pending_reasoning == "solve P=NP 深入分析"
    s.pending_reasoning = ""
    assert s.pending_reasoning == ""


def test_session_keyed_by_bot_id_when_provided():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    s1 = mgr.get_or_create(
        user_id=1, channel="telegram", bot_id="dev",
        default_runner_override="claude",
        default_role_override="fullstack-dev",
    )
    s2 = mgr.get_or_create(
        user_id=1, channel="telegram", bot_id="search",
        default_runner_override="gemini",
        default_role_override="researcher",
    )
    assert s1 is not s2
    assert s1.bot_id == "dev"
    assert s2.bot_id == "search"
    assert s1.current_runner == "claude"
    assert s2.current_runner == "gemini"
    assert s1.active_role == "fullstack-dev"
    assert s2.active_role == "researcher"


def test_legacy_session_default_bot_id():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=60, default_runner="claude", default_cwd="/tmp")
    s = mgr.get_or_create(user_id=1, channel="telegram")
    assert s.bot_id == "default"


def test_inbound_message_default_bot_id():
    from src.channels.base import InboundMessage
    m = InboundMessage(user_id=1, channel="telegram", text="hi", message_id="m1")
    assert m.bot_id == "default"


def test_inbound_message_bot_id_settable():
    from src.channels.base import InboundMessage
    m = InboundMessage(user_id=1, channel="telegram", text="hi", message_id="m1", bot_id="dev")
    assert m.bot_id == "dev"
