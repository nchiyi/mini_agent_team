# tests/test_e2e.py
"""
End-to-end smoke test: FakeAdapter → Router → CLIRunner(echo) → StreamingBridge → FakeAdapter
No real Telegram or Claude CLI required.
"""
import asyncio, sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def test_e2e_plain_text_routes_to_default_runner(tmp_path):
    from fake_adapter import FakeAdapter
    from src.core.config import GatewayConfig, RunnerConfig, AuditConfig, MemoryConfig, Config
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(
        name="echo",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    # Simulate receiving a message
    user_id = 1
    channel = "telegram"
    text = "hello from e2e"

    session = session_mgr.get_or_create(user_id=user_id, channel=channel)
    cmd = await router.parse(text)

    if cmd.is_reset:
        pass  # not testing this path
    elif cmd.is_switch_runner:
        session.current_runner = cmd.runner
    else:
        active_runner = runners[session.current_runner]
        output_stream = active_runner.run(
            prompt=cmd.prompt,
            user_id=user_id,
            channel=channel,
            cwd=session.cwd,
        )
        await bridge.stream(user_id=user_id, chunks=output_stream)

    assert any("hello from e2e" in m for m in adapter.sent + list(adapter.edits.values()))


async def test_e2e_slash_prefix_routes_to_correct_runner(tmp_path):
    from fake_adapter import FakeAdapter
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    echo_runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                            context_token_budget=1000, audit=audit)
    runners = {"echo": echo_runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    user_id = 1
    channel = "telegram"
    text = "/echo dispatched correctly"

    session = session_mgr.get_or_create(user_id=user_id, channel=channel)
    cmd = await router.parse(text)

    assert cmd.runner == "echo"
    active_runner = runners[cmd.runner]
    await bridge.stream(
        user_id=user_id,
        chunks=active_runner.run(prompt=cmd.prompt, user_id=user_id, channel=channel, cwd=session.cwd),
    )

    assert any("dispatched correctly" in m for m in adapter.sent + list(adapter.edits.values()))
