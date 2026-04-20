# tests/test_e2e_memory.py
"""
E2E test: memory commands and context assembly work through the gateway pipeline.
"""
import sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def _make_full_pipeline(tmp_path):
    from fake_adapter import FakeAdapter
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)
    return adapter, router, session_mgr, runners, bridge, t1, t3, assembler


async def _dispatch(user_id, channel, text, router, session_mgr, runners, bridge, adapter, t1, t3, assembler):
    from src.channels.base import InboundMessage
    session = session_mgr.get_or_create(user_id=user_id, channel=channel)
    cmd = router.parse(text)

    if cmd.is_remember:
        t1.remember(user_id=user_id, channel=channel, content=cmd.prompt)
        await adapter.send(user_id, f"Remembered: {cmd.prompt}")
        return
    if cmd.is_forget:
        removed = t1.forget(user_id=user_id, channel=channel, keyword=cmd.prompt)
        await adapter.send(user_id, f"Removed {removed} entries matching '{cmd.prompt}'")
        return
    if cmd.is_recall:
        results = await t3.search(user_id=user_id, channel=channel, query=cmd.prompt)
        if results:
            await adapter.send(user_id, "\n".join(r["content"] for r in results))
        else:
            await adapter.send(user_id, "Nothing found.")
        return
    if cmd.is_cancel or cmd.is_reset or cmd.is_new or cmd.is_status or cmd.is_switch_runner:
        await adapter.send(user_id, "ok")
        return

    # Save user turn
    await t3.save_turn(user_id=user_id, channel=channel, role="user", content=text)
    active_runner = runners[session.current_runner]

    response_chunks = []
    async def collecting_gen():
        async for chunk in active_runner.run(prompt=cmd.prompt, user_id=user_id, channel=channel, cwd=session.cwd):
            response_chunks.append(chunk)
            yield chunk

    await bridge.stream(user_id=user_id, chunks=collecting_gen())
    response = "".join(response_chunks).strip()
    if response:
        await t3.save_turn(user_id=user_id, channel=channel, role="assistant", content=response)


async def test_remember_stores_entry(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    await _dispatch(1, "telegram", "/remember I am a Python developer",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    entries = t1.list_entries(user_id=1, channel="telegram")
    assert len(entries) == 1
    assert "Python developer" in entries[0]["content"]
    assert any("Remembered" in m for m in adapter.sent)

    await t3.close()


async def test_forget_removes_entry(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    t1.remember(user_id=1, channel="telegram", content="I use vim")
    t1.remember(user_id=1, channel="telegram", content="I use emacs")
    await _dispatch(1, "telegram", "/forget emacs",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    entries = t1.list_entries(user_id=1, channel="telegram")
    assert len(entries) == 1
    assert "vim" in entries[0]["content"]

    await t3.close()


async def test_turns_saved_to_tier3(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    await _dispatch(1, "telegram", "test message",
                    router, session_mgr, runners, bridge, adapter, t1, t3, assembler)

    turns = await t3.get_recent(user_id=1, channel="telegram", n=10)
    assert any(t["role"] == "user" for t in turns)

    await t3.close()


async def test_context_included_in_subsequent_message(tmp_path):
    adapter, router, session_mgr, runners, bridge, t1, t3, assembler = await _make_full_pipeline(tmp_path)
    t1.remember(user_id=1, channel="telegram", content="context-fact-xyz")
    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "context-fact-xyz" in ctx

    await t3.close()
