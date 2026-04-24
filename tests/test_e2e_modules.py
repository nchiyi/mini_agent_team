# tests/test_e2e_modules.py
"""
E2E test: fake module command dispatched through full gateway dispatch().
No real Telegram/Discord or CLI runner required.
"""
import asyncio, sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def test_module_command_dispatched_e2e(tmp_path):
    from fake_adapter import FakeAdapter
    from src.channels.base import InboundMessage
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler
    from src.skills.loader import ModuleRegistry, LoadedModule
    from src.skills.manifest import ModuleManifest

    # Build fake module
    async def ping_handler(command, args, user_id, channel):
        yield f"pong:{args}"

    reg = ModuleRegistry()
    reg.register(LoadedModule(
        manifest=ModuleManifest(name="ping", version="1.0", commands=["/ping"],
                                description="", dependencies=[], enabled=True, timeout_seconds=5),
        handler=ping_handler,
    ))

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo",
                    module_registry=reg)
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo",
                                  default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    tier1 = Tier1Store(permanent_dir=str(tmp_path / "permanent"))
    tier3 = Tier3Store(db_path=str(tmp_path / "history.db"))
    await tier3.init()

    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=1000)

    from main import dispatch

    inbound = InboundMessage(user_id=1, channel="tg", text="/ping hello", message_id="1")
    await dispatch(
        inbound, bridge, session_mgr, router, runners,
        tier1, tier3, assembler,
        lambda t: adapter.send(1, t),
        recent_turns=20,
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    assert any("pong:hello" in m for m in all_output)

    await tier3.close()


async def test_status_shows_context_and_modules(tmp_path):
    from fake_adapter import FakeAdapter
    from src.channels.base import InboundMessage
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler
    from src.skills.loader import ModuleRegistry, LoadedModule
    from src.skills.manifest import ModuleManifest

    async def ping_handler(command, args, user_id, channel):
        yield "pong"

    reg = ModuleRegistry()
    reg.register(LoadedModule(
        manifest=ModuleManifest(name="ping", version="1.0", commands=["/ping"],
                                description="", dependencies=[], enabled=True, timeout_seconds=5),
        handler=ping_handler,
    ))

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo",
                    module_registry=reg)
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo",
                                  default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)
    tier1 = Tier1Store(permanent_dir=str(tmp_path / "permanent"))
    tier3 = Tier3Store(db_path=str(tmp_path / "history.db"))
    await tier3.init()
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=1000)

    from main import dispatch

    inbound = InboundMessage(user_id=1, channel="tg", text="/status", message_id="1")
    await dispatch(
        inbound, bridge, session_mgr, router, runners,
        tier1, tier3, assembler,
        lambda t: adapter.send(1, t),
        recent_turns=20,
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    combined = " ".join(all_output)
    # /status should show runner, context tokens, turns, modules
    assert "Runner:" in combined
    assert "Context:" in combined
    assert "tokens" in combined
    assert "ping" in combined  # module name visible

    await tier3.close()


async def test_unknown_command_falls_through_to_runner(tmp_path):
    """Command not in registry → default runner (echo) handles it."""
    from fake_adapter import FakeAdapter
    from src.channels.base import InboundMessage
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler
    from src.skills.loader import ModuleRegistry

    reg = ModuleRegistry()  # empty
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo",
                    module_registry=reg)
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo",
                                  default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)
    tier1 = Tier1Store(permanent_dir=str(tmp_path / "permanent"))
    tier3 = Tier3Store(db_path=str(tmp_path / "history.db"))
    await tier3.init()
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=1000)

    from main import dispatch

    inbound = InboundMessage(user_id=1, channel="tg", text="/unknown cmd", message_id="1")
    await dispatch(
        inbound, bridge, session_mgr, router, runners,
        tier1, tier3, assembler,
        lambda t: adapter.send(1, t),
        recent_turns=20,
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    assert len(all_output) > 0

    await tier3.close()


async def test_active_role_is_injected_into_default_dispatch(tmp_path):
    from fake_adapter import FakeAdapter
    from src.channels.base import InboundMessage
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager, set_active_role
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler
    from src.skills.loader import ModuleRegistry

    roster_dir = tmp_path / "roster"
    roster_dir.mkdir()
    (roster_dir / "code-auditor.md").write_text(
        "---\n"
        "slug: code-auditor\n"
        "name: Code Auditor\n"
        "summary: Review code changes\n"
        "identity: You are a meticulous code auditor.\n"
        "rules:\n"
        "  - Focus on correctness\n"
        "---\n"
        "Body\n",
        encoding="utf-8",
    )

    reg = ModuleRegistry()
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(name="echo", binary="echo", args=[], timeout_seconds=5,
                       context_token_budget=1000, audit=audit)
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo",
                    module_registry=reg)
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo",
                                  default_cwd=str(tmp_path))
    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)
    tier1 = Tier1Store(permanent_dir=str(tmp_path / "permanent"))
    tier3 = Tier3Store(db_path=str(tmp_path / "history.db"))
    await tier3.init()
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=1000)

    from main import dispatch

    set_active_role(1, "tg", "code-auditor")
    inbound = InboundMessage(user_id=1, channel="tg", text="review this patch", message_id="1")
    await dispatch(
        inbound, bridge, session_mgr, router, runners,
        tier1, tier3, assembler,
        lambda t: adapter.send(1, t),
        recent_turns=20,
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    combined = " ".join(all_output)
    assert "You are a meticulous code auditor." in combined
    assert "Focus on correctness" in combined

    await tier3.close()
