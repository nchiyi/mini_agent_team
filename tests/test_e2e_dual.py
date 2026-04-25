# tests/test_e2e_dual.py
"""
E2E smoke test: two FakeAdapters (one for Telegram, one for Discord)
share the same Router/SessionManager/runners. Proves channel isolation.
"""
import sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def _make_pipeline(tmp_path, tg_adapter, dc_adapter):
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(
        name="echo", binary="echo", args=[],
        timeout_seconds=5, context_token_budget=1000, audit=audit,
    )
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    bridges = {
        "telegram": StreamingBridge(tg_adapter, edit_interval=0.0),
        "discord":  StreamingBridge(dc_adapter, edit_interval=0.0),
    }
    adapters = {"telegram": tg_adapter, "discord": dc_adapter}

    async def dispatch(user_id: int, channel: str, text: str) -> None:
        session = session_mgr.get_or_create(user_id=user_id, channel=channel)
        cmd = await router.parse(text)
        adapter = adapters[channel]
        bridge = bridges[channel]

        if cmd.is_switch_runner:
            session.current_runner = cmd.runner
            await adapter.send(user_id, f"Switched to {cmd.runner}")
            return
        if cmd.is_cancel or cmd.is_reset or cmd.is_new or cmd.is_status:
            await adapter.send(user_id, "ok")
            return

        active_runner = runners[session.current_runner]
        await bridge.stream(
            user_id=user_id,
            chunks=active_runner.run(
                prompt=cmd.prompt, user_id=user_id,
                channel=channel, cwd=session.cwd,
            ),
        )

    return dispatch


async def test_both_channels_receive_responses(tmp_path):
    from fake_adapter import FakeAdapter
    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    await dispatch(user_id=1, channel="telegram", text="hello telegram")
    await dispatch(user_id=1, channel="discord",  text="hello discord")

    tg_out = " ".join(tg.sent + list(tg.edits.values()))
    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "hello telegram" in tg_out
    assert "hello discord" in dc_out


async def test_sessions_isolated_per_channel(tmp_path):
    from fake_adapter import FakeAdapter
    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    await dispatch(user_id=1, channel="telegram", text="/use echo")
    await dispatch(user_id=1, channel="discord", text="discord independent")

    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "discord independent" in dc_out


async def test_same_user_id_different_channels_dont_collide(tmp_path):
    from fake_adapter import FakeAdapter
    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    await dispatch(user_id=42, channel="telegram", text="tg msg")
    await dispatch(user_id=42, channel="discord",  text="dc msg")

    tg_out = " ".join(tg.sent + list(tg.edits.values()))
    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "tg msg" in tg_out
    assert "dc msg" in dc_out
    assert "dc msg" not in tg_out
    assert "tg msg" not in dc_out
