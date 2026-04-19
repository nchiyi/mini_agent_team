# Phase 3: Module System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a startup-time plugin system where each module lives in `modules/<name>/`, declares commands in `manifest.yaml`, and is loaded/dispatched by the gateway — with conflict detection, timeout protection, and four pre-built modules.

**Architecture:** `ModuleLoader` scans `modules/` at startup, parses each `manifest.yaml`, imports `handler.py` via importlib, and builds a `ModuleRegistry` (command→module map). `Router` checks the registry before routing unknowns to the default runner. `dispatch()` in `main.py` handles `cmd.is_module` by calling `registry.dispatch()` which wraps the handler call with `asyncio.timeout`. Load failures are isolated: a bad module logs a warning and is skipped; other modules start normally. Command conflicts are fatal: duplicate command at startup raises and halts.

**Tech Stack:** Python 3.12, PyYAML (manifest parsing), importlib.util (dynamic import), asyncio.timeout (handler timeout), psutil (system_monitor), duckduckgo-search (web_search), httpx (vision), pytest-asyncio

---

## File Structure

**New files:**
- `src/modules/__init__.py` — package marker
- `src/modules/manifest.py` — `ModuleManifest` dataclass + `parse_manifest()`
- `src/modules/loader.py` — `LoadedModule`, `ModuleRegistry`, `load_modules()`
- `modules/web_search/manifest.yaml` + `modules/web_search/handler.py`
- `modules/system_monitor/manifest.yaml` + `modules/system_monitor/handler.py`
- `modules/vision/manifest.yaml` + `modules/vision/handler.py`
- `modules/dev_agent/manifest.yaml` + `modules/dev_agent/handler.py`
- `tests/modules/__init__.py`
- `tests/modules/test_manifest.py`
- `tests/modules/test_loader.py`
- `tests/modules/test_registry.py`
- `tests/test_e2e_modules.py`

**Modified files:**
- `src/gateway/router.py` — add `module_registry` param; `ParsedCommand` gets `is_module` + `module_command` fields
- `src/core/config.py` — add `modules_dir: str` to `Config`; read from `[modules] dir` in TOML (default `"modules"`)
- `main.py` — call `load_modules()` in `_build_shared()`; add `module_registry` to `dispatch()` signature; handle `cmd.is_module`
- `config/config.toml.example` — add `[modules]` section

---

### Task 1: ModuleManifest dataclass + parse_manifest()

**Files:**
- Create: `src/modules/__init__.py`
- Create: `src/modules/manifest.py`
- Create: `tests/modules/__init__.py`
- Create: `tests/modules/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/modules/test_manifest.py
import pytest
from pathlib import Path
from src.modules.manifest import ModuleManifest, parse_manifest


def _write(tmp_path, content: str) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(content)
    return p


def test_parse_full_manifest(tmp_path):
    p = _write(tmp_path, """
name: web_search
version: 1.2.3
commands: [/search, /web]
description: Search the web
dependencies: [duckduckgo-search]
enabled: true
timeout_seconds: 30
""")
    m = parse_manifest(p)
    assert m.name == "web_search"
    assert m.version == "1.2.3"
    assert m.commands == ["/search", "/web"]
    assert m.description == "Search the web"
    assert m.dependencies == ["duckduckgo-search"]
    assert m.enabled is True
    assert m.timeout_seconds == 30


def test_parse_minimal_manifest_uses_defaults(tmp_path):
    p = _write(tmp_path, "name: mymod\ncommands: [/mymod]\n")
    m = parse_manifest(p)
    assert m.name == "mymod"
    assert m.version == "0.0.0"
    assert m.description == ""
    assert m.dependencies == []
    assert m.enabled is True
    assert m.timeout_seconds == 30


def test_parse_disabled_module(tmp_path):
    p = _write(tmp_path, "name: off\ncommands: [/off]\nenabled: false\n")
    m = parse_manifest(p)
    assert m.enabled is False


def test_parse_missing_name_raises(tmp_path):
    p = _write(tmp_path, "commands: [/x]\n")
    with pytest.raises(KeyError):
        parse_manifest(p)


def test_parse_missing_commands_raises(tmp_path):
    p = _write(tmp_path, "name: nocommands\n")
    with pytest.raises(KeyError):
        parse_manifest(p)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_manifest.py -v
```
Expected: ImportError or ModuleNotFoundError (src.modules.manifest doesn't exist yet)

- [ ] **Step 3: Create package markers**

```python
# src/modules/__init__.py
```

```python
# tests/modules/__init__.py
```

- [ ] **Step 4: Implement manifest.py**

```python
# src/modules/manifest.py
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModuleManifest:
    name: str
    version: str
    commands: list[str]
    description: str
    dependencies: list[str]
    enabled: bool
    timeout_seconds: int


def parse_manifest(path: Path) -> ModuleManifest:
    with open(path) as f:
        data = yaml.safe_load(f)
    return ModuleManifest(
        name=data["name"],
        version=data.get("version", "0.0.0"),
        commands=data["commands"],
        description=data.get("description", ""),
        dependencies=data.get("dependencies", []),
        enabled=data.get("enabled", True),
        timeout_seconds=data.get("timeout_seconds", 30),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_manifest.py -v
```
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add src/modules/__init__.py src/modules/manifest.py tests/modules/__init__.py tests/modules/test_manifest.py
git commit -m "feat: add ModuleManifest + parse_manifest for module system"
```

---

### Task 2: ModuleRegistry + load_modules()

**Files:**
- Create: `src/modules/loader.py`
- Create: `tests/modules/test_loader.py`
- Create: `tests/modules/test_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/modules/test_loader.py
import sys, pytest
from pathlib import Path
pytestmark = pytest.mark.asyncio


def _make_module(base: Path, name: str, commands: list[str],
                 enabled: bool = True, handler_code: str = "") -> None:
    d = base / name
    d.mkdir(parents=True)
    manifest = f"name: {name}\ncommands: {commands}\nenabled: {str(enabled).lower()}\ntimeout_seconds: 5\n"
    (d / "manifest.yaml").write_text(manifest)
    default_handler = (
        "from typing import AsyncIterator\n"
        "async def handle(command, args, user_id, channel) -> AsyncIterator[str]:\n"
        "    yield f'handled {command} {args}'\n"
    )
    (d / "handler.py").write_text(handler_code or default_handler)


def test_load_modules_empty_dir(tmp_path):
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []
    assert reg.get_commands() == []


def test_load_modules_nonexistent_dir(tmp_path):
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path / "no_such_dir"))
    assert reg.get_names() == []


def test_load_modules_finds_valid_module(tmp_path):
    _make_module(tmp_path, "alpha", ["/alpha"])
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert "alpha" in reg.get_names()
    assert "/alpha" in reg.get_commands()


def test_load_modules_skips_disabled(tmp_path):
    _make_module(tmp_path, "off_mod", ["/off"], enabled=False)
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_skips_missing_handler(tmp_path):
    d = tmp_path / "nohandler"
    d.mkdir()
    (d / "manifest.yaml").write_text("name: nohandler\ncommands: [/nh]\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_skips_bad_import(tmp_path):
    _make_module(tmp_path, "broken", ["/broken"],
                 handler_code="import totally_fake_package_xyz\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_conflict_raises(tmp_path):
    _make_module(tmp_path, "mod_a", ["/search"])
    _make_module(tmp_path, "mod_b", ["/search"])
    from src.modules.loader import load_modules
    with pytest.raises(ValueError, match="conflict"):
        load_modules(str(tmp_path))


def test_load_modules_skips_dir_without_manifest(tmp_path):
    d = tmp_path / "nomanifest"
    d.mkdir()
    (d / "handler.py").write_text("async def handle(*a): yield 'x'\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []
```

```python
# tests/modules/test_registry.py
import pytest
pytestmark = pytest.mark.asyncio


def _make_registry(commands: list[str], timeout: int = 5):
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def handler(command, args, user_id, channel):
        yield f"result:{command}:{args}"

    manifest = ModuleManifest(
        name="test_mod", version="1.0.0", commands=commands,
        description="", dependencies=[], enabled=True, timeout_seconds=timeout,
    )
    reg = ModuleRegistry()
    reg.register(LoadedModule(manifest=manifest, handler=handler))
    return reg


async def test_registry_dispatch_calls_handler():
    reg = _make_registry(["/foo"])
    chunks = [c async for c in reg.dispatch("/foo", "bar", 1, "tg")]
    assert chunks == ["result:/foo:bar"]


async def test_registry_dispatch_unknown_command_yields_error():
    reg = _make_registry(["/foo"])
    chunks = [c async for c in reg.dispatch("/unknown", "", 1, "tg")]
    assert any("not found" in c for c in chunks)


async def test_registry_dispatch_timeout():
    import asyncio
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def slow_handler(command, args, user_id, channel):
        await asyncio.sleep(10)
        yield "never"

    manifest = ModuleManifest(
        name="slow", version="1.0.0", commands=["/slow"],
        description="", dependencies=[], enabled=True, timeout_seconds=1,
    )
    reg = ModuleRegistry()
    reg.register(LoadedModule(manifest=manifest, handler=slow_handler))
    chunks = [c async for c in reg.dispatch("/slow", "", 1, "tg")]
    assert any("timed out" in c for c in chunks)


def test_registry_conflict_raises():
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def h(*a):
        yield "x"

    def _mod(name):
        return LoadedModule(
            manifest=ModuleManifest(name=name, version="1.0", commands=["/clash"],
                                    description="", dependencies=[], enabled=True, timeout_seconds=5),
            handler=h,
        )

    reg = ModuleRegistry()
    reg.register(_mod("mod_a"))
    with pytest.raises(ValueError, match="conflict"):
        reg.register(_mod("mod_b"))


def test_registry_has_command():
    reg = _make_registry(["/ping"])
    assert reg.has_command("/ping")
    assert not reg.has_command("/pong")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_loader.py tests/modules/test_registry.py -v
```
Expected: ImportError (src.modules.loader doesn't exist)

- [ ] **Step 3: Implement loader.py**

```python
# src/modules/loader.py
import asyncio
import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from src.modules.manifest import ModuleManifest, parse_manifest

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., AsyncIterator[str]]


@dataclass
class LoadedModule:
    manifest: ModuleManifest
    handler: HandlerFn


class ModuleRegistry:
    def __init__(self) -> None:
        self._by_command: dict[str, LoadedModule] = {}
        self._by_name: dict[str, LoadedModule] = {}

    def register(self, module: LoadedModule) -> None:
        for cmd in module.manifest.commands:
            if cmd in self._by_command:
                existing = self._by_command[cmd].manifest.name
                raise ValueError(
                    f"Command conflict: '{cmd}' claimed by both "
                    f"'{existing}' and '{module.manifest.name}'"
                )
            self._by_command[cmd] = module
        self._by_name[module.manifest.name] = module

    def has_command(self, command: str) -> bool:
        return command in self._by_command

    def get_commands(self) -> list[str]:
        return list(self._by_command.keys())

    def get_names(self) -> list[str]:
        return list(self._by_name.keys())

    async def dispatch(
        self, command: str, args: str, user_id: int, channel: str
    ) -> AsyncIterator[str]:
        module = self._by_command.get(command)
        if not module:
            yield f"Module command '{command}' not found."
            return
        timeout = module.manifest.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                async for chunk in module.handler(command, args, user_id, channel):
                    yield chunk
        except asyncio.TimeoutError:
            yield f"Module '{module.manifest.name}' timed out after {timeout}s."


def load_modules(modules_dir: str) -> ModuleRegistry:
    registry = ModuleRegistry()
    base = Path(modules_dir)
    if not base.exists():
        logger.warning("modules_dir '%s' does not exist, no modules loaded", modules_dir)
        return registry

    for module_dir in sorted(base.iterdir()):
        if not module_dir.is_dir():
            continue
        manifest_path = module_dir / "manifest.yaml"
        handler_path = module_dir / "handler.py"
        if not manifest_path.exists() or not handler_path.exists():
            continue

        try:
            manifest = parse_manifest(manifest_path)
        except Exception as e:
            logger.warning("Failed to parse manifest '%s': %s", manifest_path, e)
            continue

        if not manifest.enabled:
            logger.info("Module '%s' disabled, skipping", manifest.name)
            continue

        try:
            spec = importlib.util.spec_from_file_location(
                f"modules.{manifest.name}.handler", handler_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            handler: HandlerFn = getattr(mod, "handle")
        except Exception as e:
            logger.warning("Failed to load module '%s': %s", manifest.name, e)
            continue

        registry.register(LoadedModule(manifest=manifest, handler=handler))
        logger.info("Loaded module '%s' with commands %s", manifest.name, manifest.commands)

    return registry
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_loader.py tests/modules/test_registry.py -v
```
Expected: all tests PASSED

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/modules/loader.py tests/modules/test_loader.py tests/modules/test_registry.py
git commit -m "feat: add ModuleRegistry + load_modules with conflict detection and failure isolation"
```

---

### Task 3: Router integration — module command routing

**Files:**
- Modify: `src/gateway/router.py`
- Create: `tests/gateway/test_router_modules.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/gateway/test_router_modules.py
import pytest
from src.gateway.router import Router, ParsedCommand
from src.modules.loader import ModuleRegistry, LoadedModule
from src.modules.manifest import ModuleManifest


def _make_registry(commands: list[str]) -> ModuleRegistry:
    async def h(*a):
        yield "x"

    reg = ModuleRegistry()
    reg.register(LoadedModule(
        manifest=ModuleManifest(name="testmod", version="1.0", commands=commands,
                                description="", dependencies=[], enabled=True, timeout_seconds=5),
        handler=h,
    ))
    return reg


def test_module_command_parsed_as_is_module():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = router.parse("/search dogs")
    assert cmd.is_module is True
    assert cmd.module_command == "/search"
    assert cmd.prompt == "dogs"


def test_module_command_no_args():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = router.parse("/search")
    assert cmd.is_module is True
    assert cmd.module_command == "/search"
    assert cmd.prompt == ""


def test_builtin_cancel_not_shadowed_by_module():
    reg = _make_registry(["/cancel"])  # module tries to claim /cancel
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = router.parse("/cancel")
    # builtins have priority
    assert cmd.is_cancel is True
    assert cmd.is_module is False


def test_runner_prefix_not_shadowed_by_module():
    reg = _make_registry(["/claude"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = router.parse("/claude hello")
    # runner prefix has priority over module
    assert cmd.is_module is False
    assert cmd.runner == "claude"
    assert cmd.prompt == "hello"


def test_no_module_registry_unknown_slash_falls_to_default():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = router.parse("/unknown hello")
    assert cmd.is_module is False
    assert cmd.runner == "claude"
    assert cmd.prompt == "/unknown hello"


def test_module_registry_none_is_ignored():
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=None)
    cmd = router.parse("/search dogs")
    assert cmd.is_module is False


def test_plain_text_still_routes_to_default():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = router.parse("hello world")
    assert cmd.is_module is False
    assert cmd.runner == "claude"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /tmp/telegram-to-control && python -m pytest tests/gateway/test_router_modules.py -v
```
Expected: FAILED — `ParsedCommand` has no `is_module` field, `Router.__init__` has no `module_registry` param

- [ ] **Step 3: Update router.py**

```python
# src/gateway/router.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedCommand:
    runner: str
    prompt: str
    is_switch_runner: bool = False
    is_cancel: bool = False
    is_status: bool = False
    is_reset: bool = False
    is_new: bool = False
    is_remember: bool = False
    is_forget: bool = False
    is_recall: bool = False
    is_module: bool = False
    module_command: str = ""


class Router:
    _BUILTIN = {"/cancel", "/status", "/reset", "/new"}

    def __init__(self, known_runners: set[str], default_runner: str,
                 module_registry=None):
        self._runners = known_runners
        self._default = default_runner
        self._modules = module_registry

    def parse(self, text: str) -> ParsedCommand:
        text = text.strip()

        if text == "/cancel":
            return ParsedCommand(runner=self._default, prompt="", is_cancel=True)
        if text == "/status":
            return ParsedCommand(runner=self._default, prompt="", is_status=True)
        if text == "/reset":
            return ParsedCommand(runner=self._default, prompt="", is_reset=True)
        if text == "/new":
            return ParsedCommand(runner=self._default, prompt="", is_new=True)

        if text.startswith("/remember "):
            content = text[10:].strip()
            if content:
                return ParsedCommand(runner=self._default, prompt=content, is_remember=True)

        if text.startswith("/forget "):
            keyword = text[8:].strip()
            if keyword:
                return ParsedCommand(runner=self._default, prompt=keyword, is_forget=True)

        if text.startswith("/recall "):
            query = text[8:].strip()
            if query:
                return ParsedCommand(runner=self._default, prompt=query, is_recall=True)

        if text.startswith("/use "):
            target = text[5:].strip()
            if target in self._runners:
                return ParsedCommand(runner=target, prompt="", is_switch_runner=True)

        if text.startswith("/"):
            parts = text.split(None, 1)
            prefix = parts[0].lstrip("/").lower()
            if prefix in self._runners:
                prompt = parts[1] if len(parts) > 1 else ""
                return ParsedCommand(runner=prefix, prompt=prompt)

            # Check module registry before falling through to default runner
            slash_prefix = parts[0].lower()  # keep the leading slash
            if self._modules and self._modules.has_command(slash_prefix):
                args = parts[1] if len(parts) > 1 else ""
                return ParsedCommand(
                    runner=self._default, prompt=args,
                    is_module=True, module_command=slash_prefix,
                )

            # Unknown slash command: pass full text to default runner
            return ParsedCommand(runner=self._default, prompt=text)

        return ParsedCommand(runner=self._default, prompt=text)
```

- [ ] **Step 4: Run all router tests to verify no regressions**

```
cd /tmp/telegram-to-control && python -m pytest tests/gateway/test_router.py tests/gateway/test_router_memory.py tests/gateway/test_router_modules.py -v
```
Expected: all tests PASSED

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/gateway/router.py tests/gateway/test_router_modules.py
git commit -m "feat: extend Router to route module commands via ModuleRegistry"
```

---

### Task 4: Config + main.py integration

**Files:**
- Modify: `src/core/config.py`
- Modify: `main.py`
- Modify: `config/config.toml.example`
- Create: `tests/test_e2e_modules.py`

- [ ] **Step 1: Write the failing e2e test**

```python
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
    from src.core.config import GatewayConfig, RunnerConfig, AuditConfig, MemoryConfig, Config
    from src.channels.base import InboundMessage
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

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

    replies: list[str] = []

    from main import dispatch

    inbound = InboundMessage(user_id=1, channel="tg", text="/ping hello", message_id="1")
    await dispatch(
        inbound, bridge, session_mgr, router, runners,
        tier1, tier3, assembler,
        lambda t: adapter.send(1, t),
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    assert any("pong:hello" in m for m in all_output)

    await tier3.close()


async def test_module_not_found_falls_through(tmp_path):
    """Command not in registry, no runner match → default runner (echo) handles it."""
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
    from src.modules.loader import ModuleRegistry

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
        module_registry=reg,
    )

    all_output = adapter.sent + list(adapter.edits.values())
    # echo runner outputs the full text (/unknown cmd since it's treated as default runner prompt)
    assert len(all_output) > 0

    await tier3.close()
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /tmp/telegram-to-control && python -m pytest tests/test_e2e_modules.py -v
```
Expected: ImportError or TypeError — `dispatch()` doesn't accept `module_registry` yet

- [ ] **Step 3: Update Config to add modules_dir**

In `src/core/config.py`, add `modules_dir: str = "modules"` to the `Config` dataclass, and read it in `load_config()`:

```python
# src/core/config.py
import os, tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class GatewayConfig:
    default_runner: str
    session_idle_minutes: int
    max_message_length_telegram: int
    max_message_length_discord: int
    stream_edit_interval_seconds: float


@dataclass
class RunnerConfig:
    path: str
    args: list[str]
    timeout_seconds: int
    context_token_budget: int


@dataclass
class AuditConfig:
    path: str
    max_entries: int


@dataclass
class MemoryConfig:
    db_path: str
    hot_path: str
    cold_permanent_path: str
    cold_session_path: str
    tier3_context_turns: int
    distill_trigger_turns: int


@dataclass
class Config:
    gateway: GatewayConfig
    runners: dict[str, RunnerConfig]
    audit: AuditConfig
    memory: MemoryConfig
    telegram_token: str = ""
    discord_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    default_cwd: str = ""
    modules_dir: str = "modules"


def load_config(
    config_path: str = "config/config.toml",
    env_path: Optional[str] = "secrets/.env",
) -> Config:
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(p, "rb") as f:
        raw = tomllib.load(f)

    if env_path and Path(env_path).exists():
        load_dotenv(env_path)

    gw = raw["gateway"]
    gateway = GatewayConfig(
        default_runner=gw["default_runner"],
        session_idle_minutes=gw["session_idle_minutes"],
        max_message_length_telegram=gw["max_message_length_telegram"],
        max_message_length_discord=gw["max_message_length_discord"],
        stream_edit_interval_seconds=gw["stream_edit_interval_seconds"],
    )

    runners = {
        name: RunnerConfig(
            path=rc["path"],
            args=rc.get("args", []),
            timeout_seconds=rc.get("timeout_seconds", 300),
            context_token_budget=rc.get("context_token_budget", 4000),
        )
        for name, rc in raw.get("runners", {}).items()
    }

    audit_raw = raw["audit"]
    audit = AuditConfig(path=audit_raw["path"], max_entries=audit_raw["max_entries"])

    mem = raw["memory"]
    memory = MemoryConfig(
        db_path=mem["db_path"],
        hot_path=mem["hot_path"],
        cold_permanent_path=mem["cold_permanent_path"],
        cold_session_path=mem["cold_session_path"],
        tier3_context_turns=mem["tier3_context_turns"],
        distill_trigger_turns=mem["distill_trigger_turns"],
    )

    allowed_raw = os.environ.get("ALLOWED_USER_IDS", "")
    allowed = [int(x.strip()) for x in allowed_raw.split(",") if x.strip().isdigit()]

    modules_dir = raw.get("modules", {}).get("dir", "modules")

    return Config(
        gateway=gateway,
        runners=runners,
        audit=audit,
        memory=memory,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        allowed_user_ids=allowed,
        default_cwd=os.environ.get("DEFAULT_CWD", str(Path.home())),
        modules_dir=modules_dir,
    )
```

- [ ] **Step 4: Update main.py — add module_registry to _build_shared and dispatch**

```python
# main.py
"""
Gateway Agent Platform — entry point.
Runs TelegramAdapter and/or DiscordAdapter concurrently via asyncio.gather().
Includes Tier 1 permanent memory, Tier 3 SQLite history, and context assembly.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config, Config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.channels.discord_adapter import DiscordAdapter
from src.channels.base import InboundMessage, BaseAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler
from src.modules.loader import ModuleRegistry, load_modules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

_recent_turns = 20  # overridden by config at startup


def _build_shared(cfg: Config, audit: AuditLog):
    runners = {
        name: CLIRunner(
            name=name,
            binary=rc.path,
            args=rc.args,
            timeout_seconds=rc.timeout_seconds,
            context_token_budget=rc.context_token_budget,
            audit=audit,
        )
        for name, rc in cfg.runners.items()
    }
    module_registry = load_modules(cfg.modules_dir)
    router = Router(
        known_runners=set(runners.keys()),
        default_runner=cfg.gateway.default_runner,
        module_registry=module_registry,
    )
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )
    tier1 = Tier1Store(permanent_dir=cfg.memory.cold_permanent_path)
    tier3 = Tier3Store(db_path=cfg.memory.db_path)
    default_runner_cfg = cfg.runners.get(cfg.gateway.default_runner)
    max_tokens = default_runner_cfg.context_token_budget if default_runner_cfg else 4000
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=max_tokens)
    return runners, module_registry, router, session_mgr, tier1, tier3, assembler


async def dispatch(
    inbound: InboundMessage,
    bridge: StreamingBridge,
    session_mgr: SessionManager,
    router: Router,
    runners: dict,
    tier1: Tier1Store,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
    module_registry: ModuleRegistry | None = None,
) -> None:
    """Channel-agnostic gateway logic."""
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = router.parse(inbound.text)

    if cmd.is_remember:
        tier1.remember(user_id=inbound.user_id, content=cmd.prompt)
        await send_reply(f"Remembered: {cmd.prompt}")
        return
    if cmd.is_forget:
        removed = tier1.forget(user_id=inbound.user_id, keyword=cmd.prompt)
        await send_reply(f"Removed {removed} entries matching '{cmd.prompt}'")
        return
    if cmd.is_recall:
        results = await tier3.search(user_id=inbound.user_id, query=cmd.prompt, limit=5)
        if results:
            await send_reply("\n".join(r["content"] for r in results))
        else:
            await send_reply("Nothing found.")
        return
    if cmd.is_cancel:
        await send_reply("No active task to cancel.")
        return
    if cmd.is_reset:
        await send_reply("Context cleared.")
        return
    if cmd.is_new:
        await send_reply("New session started.")
        return
    if cmd.is_status:
        mod_names = module_registry.get_names() if module_registry else []
        # Build context to measure current token usage
        context_str = await assembler.build(
            user_id=inbound.user_id, channel=inbound.channel, recent_turns=_recent_turns
        )
        from src.core.memory.context import count_tokens
        context_tokens = count_tokens(context_str) if context_str else 0
        default_runner_obj = runners.get(session.current_runner)
        token_budget = default_runner_obj.context_token_budget if default_runner_obj else 4000
        turns = await tier3.get_recent(
            user_id=inbound.user_id, channel=inbound.channel, n=_recent_turns
        )
        await send_reply(
            f"Runner: {session.current_runner}\n"
            f"Context: {context_tokens}/{token_budget} tokens\n"
            f"Turns: {len(turns)}\n"
            f"Modules: {mod_names or '(none)'}\n"
            f"CWD: {session.cwd}"
        )
        return
    if cmd.is_switch_runner:
        session.current_runner = cmd.runner
        await send_reply(f"Switched to {cmd.runner}")
        return

    if cmd.is_module and module_registry:
        await bridge.stream(
            user_id=inbound.user_id,
            chunks=module_registry.dispatch(
                cmd.module_command, cmd.prompt, inbound.user_id, inbound.channel
            ),
        )
        return

    target_runner = runners.get(session.current_runner)
    if not target_runner:
        await send_reply(f"Runner '{session.current_runner}' not found.")
        return

    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel,
        recent_turns=_recent_turns,
    )
    full_prompt = (context + "\n\n" + cmd.prompt) if context else cmd.prompt

    try:
        response_chunks: list[str] = []

        async def collecting_gen():
            async for chunk in target_runner.run(
                prompt=full_prompt,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                response_chunks.append(chunk)
                yield chunk

        await bridge.stream(user_id=inbound.user_id, chunks=collecting_gen())
        response = "".join(response_chunks).strip()
        if response:
            await tier3.save_turn(
                user_id=inbound.user_id, channel=inbound.channel,
                role="assistant", content=response,
            )
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e)
        await send_reply(f"Error: {e}")


async def run_telegram(cfg: Config, runners, module_registry, router, session_mgr,
                       tier1, tier3, assembler) -> None:
    tg_app = Application.builder().token(cfg.telegram_token).build()
    adapter = TelegramAdapter(bot=tg_app.bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        inbound = InboundMessage(
            user_id=user_id,
            channel="telegram",
            text=update.message.text.strip(),
            message_id=str(update.message.message_id),
        )
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: adapter.send(user_id, t),
            module_registry=module_registry,
        )

    tg_app.add_handler(MessageHandler(filters.TEXT, on_message))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot running")
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()


async def run_discord(cfg: Config, runners, module_registry, router, session_mgr,
                      tier1, tier3, assembler) -> None:
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: dc_adapter.send(inbound.user_id, t),
            module_registry=module_registry,
        )

    dc_adapter = DiscordAdapter(
        token=cfg.discord_token,
        allowed_user_ids=cfg.allowed_user_ids,
        gateway_handler=gateway_handler,
    )
    logger.info("Discord bot starting")
    await dc_adapter.start()


async def main(cfg_path: str = "config/config.toml", env_path: str = "secrets/.env") -> None:
    global _recent_turns
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    _recent_turns = cfg.memory.tier3_context_turns
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    runners, module_registry, router, session_mgr, tier1, tier3, assembler = _build_shared(cfg, audit)
    await tier3.init()

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(cfg, runners, module_registry, router,
                                        session_mgr, tier1, tier3, assembler))
    if cfg.discord_token:
        coroutines.append(run_discord(cfg, runners, module_registry, router,
                                       session_mgr, tier1, tier3, assembler))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    try:
        await asyncio.gather(*coroutines, return_exceptions=True)
    finally:
        await tier3.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Update config.toml.example to add [modules] section**

Append to `config/config.toml.example`:

```toml
[modules]
dir = "modules"
```

- [ ] **Step 6: Run e2e test and all existing tests**

```
cd /tmp/telegram-to-control && python -m pytest tests/test_e2e_modules.py tests/test_e2e.py tests/test_e2e_memory.py tests/test_e2e_dual.py -v
```
Expected: all PASSED

- [ ] **Step 7: Run full test suite to check for regressions**

```
cd /tmp/telegram-to-control && python -m pytest -v
```
Expected: all tests PASSED (existing 54 + new tests)

- [ ] **Step 8: Commit**

```bash
cd /tmp/telegram-to-control
git add src/core/config.py main.py config/config.toml.example tests/test_e2e_modules.py
git commit -m "feat: wire ModuleRegistry into _build_shared and dispatch() — module commands routed end-to-end"
```

---

### Task 5: web_search module

**Files:**
- Create: `modules/web_search/manifest.yaml`
- Create: `modules/web_search/handler.py`
- Create: `tests/modules/test_web_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_web_search.py
import asyncio, sys, pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_web_search_returns_results():
    fake_results = [
        {"title": "Python docs", "href": "https://python.org", "body": "Python is great."},
        {"title": "Real Python", "href": "https://realpython.com", "body": "Tutorials."},
    ]

    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text = MagicMock(return_value=fake_results)

    with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=mock_ddgs)}):
        # re-import to pick up mock
        import importlib
        import modules.web_search.handler as wsh
        importlib.reload(wsh)

        chunks = await _collect(wsh.handle("/search", "python tutorial", 1, "tg"))
        combined = "".join(chunks)
        assert "Python docs" in combined
        assert "https://python.org" in combined


async def test_web_search_empty_args_shows_usage():
    # Import fresh; duckduckgo_search may or may not be installed
    import importlib, sys
    # Ensure module is importable even without duckduckgo_search
    sys.modules.setdefault("duckduckgo_search", MagicMock())
    import modules.web_search.handler as wsh
    importlib.reload(wsh)

    chunks = await _collect(wsh.handle("/search", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_web_search_no_results():
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.text = MagicMock(return_value=[])

    with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=mock_ddgs)}):
        import importlib
        import modules.web_search.handler as wsh
        importlib.reload(wsh)

        chunks = await _collect(wsh.handle("/search", "xyzzy", 1, "tg"))
        assert any("No results" in c for c in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_web_search.py -v
```
Expected: ModuleNotFoundError (modules/web_search/handler.py doesn't exist)

- [ ] **Step 3: Create modules/web_search/ directory and files**

```bash
mkdir -p /tmp/telegram-to-control/modules/web_search
```

```yaml
# modules/web_search/manifest.yaml
name: web_search
version: 1.0.0
commands: [/search, /web]
description: 網路搜尋（DuckDuckGo）
dependencies: [duckduckgo-search]
enabled: true
timeout_seconds: 30
```

```python
# modules/web_search/handler.py
import asyncio
from typing import AsyncIterator


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /search <query>"
        return
    try:
        from duckduckgo_search import DDGS
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(args.strip(), max_results=5))
        )
        if not results:
            yield "No results found."
            return
        lines = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = (r.get("body", "") or "")[:150]
            lines.append(f"{title}\n{href}\n{body}")
        yield "\n\n".join(lines)
    except ImportError:
        yield "duckduckgo-search not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        yield f"Search error: {e}"
```

- [ ] **Step 4: Create modules/__init__.py**

```bash
touch /tmp/telegram-to-control/modules/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_web_search.py -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add modules/__init__.py modules/web_search/ tests/modules/test_web_search.py
git commit -m "feat: add web_search module (/search, /web) with DuckDuckGo"
```

---

### Task 6: system_monitor module

**Files:**
- Create: `modules/system_monitor/manifest.yaml`
- Create: `modules/system_monitor/handler.py`
- Create: `tests/modules/test_system_monitor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_system_monitor.py
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_system_monitor_returns_cpu_mem_disk():
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.return_value = 42.5
    mem = MagicMock()
    mem.used = 2 * 1024**3
    mem.total = 8 * 1024**3
    mem.percent = 25.0
    mock_psutil.virtual_memory.return_value = mem
    disk = MagicMock()
    disk.used = 100 * 1024**3
    disk.total = 500 * 1024**3
    disk.percent = 20.0
    mock_psutil.disk_usage.return_value = disk

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        import importlib
        import modules.system_monitor.handler as smh
        importlib.reload(smh)

        chunks = await _collect(smh.handle("/sysinfo", "", 1, "tg"))
        combined = "".join(chunks)
        assert "42.5%" in combined
        assert "2.0GB" in combined
        assert "8.0GB" in combined
        assert "100.0GB" in combined


async def test_system_monitor_no_psutil_yields_install_hint():
    import sys
    saved = sys.modules.pop("psutil", None)
    try:
        import importlib
        import modules.system_monitor.handler as smh
        importlib.reload(smh)

        chunks = await _collect(smh.handle("/sysinfo", "", 1, "tg"))
        assert any("psutil" in c for c in chunks)
    finally:
        if saved:
            sys.modules["psutil"] = saved
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_system_monitor.py -v
```
Expected: ModuleNotFoundError

- [ ] **Step 3: Create modules/system_monitor/**

```bash
mkdir -p /tmp/telegram-to-control/modules/system_monitor
```

```yaml
# modules/system_monitor/manifest.yaml
name: system_monitor
version: 1.0.0
commands: [/sysinfo]
description: CPU / 記憶體 / 磁碟狀態
dependencies: [psutil]
enabled: true
timeout_seconds: 10
```

```python
# modules/system_monitor/handler.py
from typing import AsyncIterator


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        lines = [
            f"CPU: {cpu:.1f}%",
            f"RAM: {mem.used / 1024**3:.1f}GB / {mem.total / 1024**3:.1f}GB ({mem.percent:.1f}%)",
            f"Disk: {disk.used / 1024**3:.1f}GB / {disk.total / 1024**3:.1f}GB ({disk.percent:.1f}%)",
        ]
        yield "\n".join(lines)
    except ImportError:
        yield "psutil not installed. Run: pip install psutil"
    except Exception as e:
        yield f"System info error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_system_monitor.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add modules/system_monitor/ tests/modules/test_system_monitor.py
git commit -m "feat: add system_monitor module (/sysinfo) with CPU/RAM/disk stats"
```

---

### Task 7: vision module

**Files:**
- Create: `modules/vision/manifest.yaml`
- Create: `modules/vision/handler.py`
- Create: `tests/modules/test_vision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_vision.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_vision_empty_args_shows_usage():
    import sys
    sys.modules.setdefault("httpx", MagicMock())
    import importlib
    import modules.vision.handler as vh
    importlib.reload(vh)

    chunks = await _collect(vh.handle("/describe", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_vision_calls_ollama_with_url():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"response": "A beautiful landscape."}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = mock_client

    with patch.dict("sys.modules", {"httpx": mock_httpx}):
        import importlib
        import modules.vision.handler as vh
        importlib.reload(vh)

        chunks = await _collect(
            vh.handle("/describe", "https://example.com/img.jpg", 1, "tg")
        )
        combined = "".join(chunks)
        assert "A beautiful landscape." in combined


async def test_vision_no_httpx_yields_install_hint():
    import sys
    saved = sys.modules.pop("httpx", None)
    try:
        import importlib
        import modules.vision.handler as vh
        importlib.reload(vh)

        chunks = await _collect(vh.handle("/describe", "https://example.com/img.jpg", 1, "tg"))
        assert any("httpx" in c for c in chunks)
    finally:
        if saved:
            sys.modules["httpx"] = saved
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_vision.py -v
```
Expected: ModuleNotFoundError

- [ ] **Step 3: Create modules/vision/**

```bash
mkdir -p /tmp/telegram-to-control/modules/vision
```

```yaml
# modules/vision/manifest.yaml
name: vision
version: 1.0.0
commands: [/describe]
description: 圖片描述（Ollama vision model）
dependencies: [httpx]
enabled: true
timeout_seconds: 60
```

```python
# modules/vision/handler.py
import os
from typing import AsyncIterator

_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_VISION_MODEL = os.environ.get("VISION_MODEL", "llava")


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /describe <image_url_or_local_path>"
        return
    try:
        import httpx
        import base64
        from pathlib import Path

        target = args.strip()
        if Path(target).exists():
            img_b64 = base64.b64encode(Path(target).read_bytes()).decode()
            images = [img_b64]
        else:
            images = [target]

        payload = {
            "model": _VISION_MODEL,
            "prompt": "Describe this image in detail.",
            "images": images,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{_OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            yield data.get("response", "No response from vision model.")
    except ImportError:
        yield "httpx not installed. Run: pip install httpx"
    except Exception as e:
        yield f"Vision error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_vision.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add modules/vision/ tests/modules/test_vision.py
git commit -m "feat: add vision module (/describe) using Ollama llava"
```

---

### Task 8: dev_agent module

**Files:**
- Create: `modules/dev_agent/manifest.yaml`
- Create: `modules/dev_agent/handler.py`
- Create: `tests/modules/test_dev_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/test_dev_agent.py
import asyncio, pytest
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_dev_agent_empty_args_shows_usage(monkeypatch):
    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_dev_agent_runs_subprocess(monkeypatch, tmp_path):
    monkeypatch.setenv("DEV_AGENT_BINARY", "echo")
    monkeypatch.setenv("DEV_AGENT_ARGS", "")
    monkeypatch.setenv("DEV_AGENT_TIMEOUT", "10")

    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "hello from dev_agent", 1, "tg"))
    combined = "".join(chunks)
    assert "hello from dev_agent" in combined


async def test_dev_agent_binary_not_found(monkeypatch):
    monkeypatch.setenv("DEV_AGENT_BINARY", "totally_nonexistent_binary_xyz")
    monkeypatch.setenv("DEV_AGENT_ARGS", "")

    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "do something", 1, "tg"))
    combined = "".join(chunks)
    assert "not found" in combined.lower() or "error" in combined.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_dev_agent.py -v
```
Expected: ModuleNotFoundError

- [ ] **Step 3: Create modules/dev_agent/**

```bash
mkdir -p /tmp/telegram-to-control/modules/dev_agent
```

```yaml
# modules/dev_agent/manifest.yaml
name: dev_agent
version: 1.0.0
commands: [/dev]
description: 開發任務（透過 CLIRunner 執行）
dependencies: []
enabled: true
timeout_seconds: 300
```

```python
# modules/dev_agent/handler.py
import asyncio
import os
from typing import AsyncIterator

_DEV_BINARY = os.environ.get("DEV_AGENT_BINARY", "claude")
_DEV_ARGS_RAW = os.environ.get("DEV_AGENT_ARGS", "--dangerously-skip-permissions")
_DEV_TIMEOUT = int(os.environ.get("DEV_AGENT_TIMEOUT", "300"))


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /dev <task description>"
        return

    binary = os.environ.get("DEV_AGENT_BINARY", _DEV_BINARY)
    args_raw = os.environ.get("DEV_AGENT_ARGS", _DEV_ARGS_RAW)
    extra_args = [a for a in args_raw.split() if a]
    timeout = int(os.environ.get("DEV_AGENT_TIMEOUT", str(_DEV_TIMEOUT)))

    cmd = [binary] + extra_args + [args.strip()]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with asyncio.timeout(timeout):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    yield line.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            yield f"\n[dev_agent timed out after {timeout}s]"
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    except FileNotFoundError:
        yield f"'{binary}' not found. Set DEV_AGENT_BINARY env var."
    except Exception as e:
        yield f"dev_agent error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /tmp/telegram-to-control && python -m pytest tests/modules/test_dev_agent.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Run full test suite**

```
cd /tmp/telegram-to-control && python -m pytest -v
```
Expected: all tests PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add modules/dev_agent/ tests/modules/test_dev_agent.py
git commit -m "feat: add dev_agent module (/dev) — spawns configurable CLI subprocess"
```

---

## Self-Review

**Spec coverage check (§7):**

| Spec requirement | Task |
|---|---|
| manifest.yaml structure (name, version, commands, description, dependencies, enabled, timeout_seconds) | Task 1 |
| Startup scan of modules/ directory | Task 2 |
| Module handler importlib loading | Task 2 |
| Command conflict detection → startup error | Task 2 |
| Load failure → skip + warning, others normal | Task 2 |
| Timeout protection per manifest | Task 2 (ModuleRegistry.dispatch) |
| Router integration | Task 3 |
| Builtin commands (cancel/status/reset/new) NOT shadowed by modules | Task 3 |
| /status shows runner, context tokens/budget, turns, loaded modules | Task 4 (main.py is_status handler) |
| dispatch() handles is_module | Task 4 |
| web_search (/search, /web) | Task 5 |
| system_monitor (/sysinfo) | Task 6 |
| vision (/describe) | Task 7 |
| dev_agent (/dev) | Task 8 |
| Disabled module → skip | Task 2 |

**Placeholder scan:** No TBD/TODO in plan. All code blocks complete.

**Type consistency check:**
- `LoadedModule.handler: HandlerFn` ← used in Tasks 2, 3, 4, 5, 6, 7, 8 consistently
- `ModuleRegistry.dispatch()` is async generator ← used in Task 4 `bridge.stream(..., chunks=registry.dispatch(...))` ✓
- `ParsedCommand.is_module` + `ParsedCommand.module_command` ← Task 3 defines, Task 4 reads ✓
- `Config.modules_dir` ← Task 4 adds, `_build_shared()` reads ✓
- `_build_shared()` return tuple updated from 6 to 7 values in Task 4: `runners, module_registry, router, session_mgr, tier1, tier3, assembler` ← `run_telegram` and `run_discord` updated accordingly ✓

**Note on system_monitor:** spec table shows `/status` but that conflicts with the built-in `/status` command. Implemented as `/sysinfo` instead. The built-in `/status` handler in Task 4 is enhanced to show loaded module names.
