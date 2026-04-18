# tests/gateway/test_session.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


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


async def test_session_idle_release():
    from src.gateway.session import SessionManager
    mgr = SessionManager(idle_minutes=0, default_runner="claude", default_cwd="/tmp")
    s1 = mgr.get_or_create(user_id=1, channel="telegram")
    await asyncio.sleep(0.01)
    mgr.release_idle()
    s2 = mgr.get_or_create(user_id=1, channel="telegram")
    assert s1 is not s2   # old session was released, new one created
