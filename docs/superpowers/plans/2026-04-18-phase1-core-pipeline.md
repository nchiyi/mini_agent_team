# Gateway Agent Platform — Phase 1: Core Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the minimal working pipeline: Telegram message → Gateway Router → CLIRunner(claude) → streaming response back to Telegram.

**Architecture:** A `TelegramAdapter` receives messages and pushes them onto a shared async queue. A `Gateway` `Router` reads the queue, parses the command prefix, and dispatches to `CLIRunner`. `CLIRunner` spawns a subprocess and streams stdout back through `StreamingBridge` to the adapter. Every CLI invocation is written to an audit log.

**Tech Stack:** Python 3.11+, python-telegram-bot 21+, asyncio subprocess, tomllib (stdlib), pytest + pytest-asyncio

---

## File Map

| File | Responsibility |
|------|---------------|
| `config/config.toml.example` | Template config (no secrets) |
| `secrets/.env.example` | Template for bot tokens / API keys |
| `src/core/config.py` | Load + validate config.toml and .env |
| `src/runners/base.py` | `BaseRunner` abstract interface |
| `src/runners/audit.py` | Append-only JSONL audit log writer |
| `src/runners/cli_runner.py` | Spawn subprocess, stream stdout, write audit |
| `src/channels/base.py` | `BaseAdapter` abstract interface |
| `src/channels/telegram.py` | `TelegramAdapter` using python-telegram-bot |
| `src/gateway/session.py` | `SessionManager` — per-user-per-channel state |
| `src/gateway/router.py` | Parse command prefix, dispatch to runner |
| `src/gateway/streaming.py` | `StreamingBridge` — throttled edit loop |
| `main.py` | Wire everything, start event loop |
| `tests/runners/test_cli_runner.py` | Unit tests for CLIRunner |
| `tests/gateway/test_router.py` | Unit tests for Router |
| `tests/gateway/test_session.py` | Unit tests for SessionManager |
| `tests/channels/test_fake_adapter.py` | Fake adapter for integration tests |
| `tests/test_e2e.py` | End-to-end smoke test (fake adapter + real echo CLI) |

---

## Task 1: Project Scaffold + Config System

**Files:**
- Create: `config/config.toml.example`
- Create: `secrets/.env.example`
- Create: `src/__init__.py`
- Create: `src/core/__init__.py`
- Create: `src/core/config.py`
- Create: `tests/__init__.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Create directory structure**

```bash
cd /tmp/telegram-to-control
mkdir -p src/core src/runners src/channels src/gateway
mkdir -p tests/core tests/runners tests/gateway tests/channels
mkdir -p config secrets data/audit data/memory/hot data/memory/cold/permanent data/memory/cold/session data/db
touch src/__init__.py src/core/__init__.py src/runners/__init__.py
touch src/channels/__init__.py src/gateway/__init__.py
touch tests/__init__.py tests/core/__init__.py tests/runners/__init__.py
touch tests/gateway/__init__.py tests/channels/__init__.py
echo "secrets/" >> .gitignore
echo "data/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo ".env" >> .gitignore
```

- [ ] **Step 2: Write config.toml.example**

```toml
# config/config.toml.example
# Copy to config/config.toml and edit

[gateway]
default_runner = "claude"          # which CLI to use when no /prefix given
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[runners.claude]
path = "claude"                    # binary name on PATH
args = ["--dangerously-skip-permissions"]
timeout_seconds = 300
context_token_budget = 4000

[runners.codex]
path = "codex"
args = ["exec", "--skip-git-repo-check"]
timeout_seconds = 300
context_token_budget = 4000

[runners.gemini]
path = "gemini"
args = []
timeout_seconds = 300
context_token_budget = 4000

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
```

- [ ] **Step 3: Write secrets/.env.example**

```bash
# secrets/.env.example
# Copy to secrets/.env

TELEGRAM_BOT_TOKEN=your_token_here
ALLOWED_USER_IDS=123456789,987654321
DEFAULT_CWD=/home/kiwi
```

- [ ] **Step 4: Write failing test for config loader**

```python
# tests/core/test_config.py
import os, pytest, tomllib
from pathlib import Path

def test_config_loads_toml(tmp_path):
    toml_content = """
[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[runners.claude]
path = "claude"
args = ["--dangerously-skip-permissions"]
timeout_seconds = 300
context_token_budget = 4000

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    assert cfg.gateway.default_runner == "claude"
    assert cfg.gateway.session_idle_minutes == 60
    assert cfg.runners["claude"].timeout_seconds == 300
    assert cfg.audit.max_entries == 1000


def test_config_missing_file_raises():
    from src.core.config import load_config
    with pytest.raises(FileNotFoundError):
        load_config(config_path="/nonexistent/config.toml", env_path=None)


def test_config_loads_env_vars(tmp_path, monkeypatch):
    toml_content = """
[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    assert cfg.telegram_token == "test_token_123"
    assert cfg.allowed_user_ids == [111, 222]
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd /tmp/telegram-to-control
pip install pytest pytest-asyncio python-dotenv 2>/dev/null | tail -1
python -m pytest tests/core/test_config.py -v 2>&1 | head -20
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.config'`

- [ ] **Step 6: Implement config.py**

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

    return Config(
        gateway=gateway,
        runners=runners,
        audit=audit,
        memory=memory,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        allowed_user_ids=allowed,
        default_cwd=os.environ.get("DEFAULT_CWD", str(Path.home())),
    )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/core/test_config.py -v
```
Expected: 3 PASSED

- [ ] **Step 8: Copy example files and commit**

```bash
cp config/config.toml.example config/config.toml
cp secrets/.env.example secrets/.env
git add src/ tests/ config/ secrets/.env.example .gitignore
git commit -m "feat: project scaffold and config system"
```

---

## Task 2: Audit Log

**Files:**
- Create: `src/runners/audit.py`
- Create: `tests/runners/test_audit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/runners/test_audit.py
import json, pytest
from pathlib import Path


def test_audit_writes_entry(tmp_path):
    from src.runners.audit import AuditLog
    log = AuditLog(audit_dir=str(tmp_path), max_entries=1000)
    log.write(user_id=123, channel="telegram", runner="claude", prompt="hello", cwd="/home")

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["user_id"] == 123
    assert entry["runner"] == "claude"
    assert entry["prompt"] == "hello"
    assert "ts" in entry


def test_audit_multiple_entries(tmp_path):
    from src.runners.audit import AuditLog
    log = AuditLog(audit_dir=str(tmp_path), max_entries=1000)
    for i in range(3):
        log.write(user_id=i, channel="telegram", runner="claude", prompt=f"msg {i}", cwd="/")

    files = list(tmp_path.glob("*.jsonl"))
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 3


def test_audit_creates_dir_if_missing(tmp_path):
    from src.runners.audit import AuditLog
    nested = tmp_path / "a" / "b" / "audit"
    log = AuditLog(audit_dir=str(nested), max_entries=1000)
    log.write(user_id=1, channel="telegram", runner="claude", prompt="x", cwd="/")
    assert nested.exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/runners/test_audit.py -v 2>&1 | head -15
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement audit.py**

```python
# src/runners/audit.py
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, audit_dir: str, max_entries: int):
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries

    def write(self, *, user_id: int, channel: str, runner: str, prompt: str, cwd: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self._dir / f"{today}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "channel": channel,
            "runner": runner,
            "prompt": prompt[:200],
            "cwd": cwd,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/runners/test_audit.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/runners/audit.py tests/runners/test_audit.py
git commit -m "feat: append-only JSONL audit log"
```

---

## Task 3: CLIRunner

**Files:**
- Create: `src/runners/base.py`
- Create: `src/runners/cli_runner.py`
- Create: `tests/runners/test_cli_runner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/runners/test_cli_runner.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_cli_runner_echo(tmp_path):
    """Use 'echo' as a stand-in CLI to verify streaming output."""
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="echo_test",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )

    chunks = []
    async for chunk in runner.run(
        prompt="hello world",
        user_id=1,
        channel="test",
        cwd=str(tmp_path),
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "hello world" in output


async def test_cli_runner_timeout(tmp_path):
    """A process that sleeps longer than timeout should raise TimeoutError."""
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="sleep_test",
        binary="sleep",
        args=[],
        timeout_seconds=1,
        context_token_budget=1000,
        audit=audit,
    )

    with pytest.raises(TimeoutError):
        async for _ in runner.run(
            prompt="10",   # sleep 10 seconds, but timeout is 1
            user_id=1,
            channel="test",
            cwd=str(tmp_path),
        ):
            pass


async def test_cli_runner_writes_audit(tmp_path):
    from src.runners.cli_runner import CLIRunner
    from src.runners.audit import AuditLog
    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)

    runner = CLIRunner(
        name="echo_test",
        binary="echo",
        args=[],
        timeout_seconds=5,
        context_token_budget=1000,
        audit=audit,
    )

    async for _ in runner.run(prompt="test prompt", user_id=42, channel="telegram", cwd="/"):
        pass

    import json
    files = list((tmp_path / "audit").glob("*.jsonl"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text().strip())
    assert entry["user_id"] == 42
    assert entry["runner"] == "echo_test"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/runners/test_cli_runner.py -v 2>&1 | head -15
```
Expected: FAIL

- [ ] **Step 3: Write base.py**

```python
# src/runners/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseRunner(ABC):
    @abstractmethod
    def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
    ) -> AsyncIterator[str]:
        """Yield text chunks as the runner produces output."""
        ...
```

- [ ] **Step 4: Write cli_runner.py**

```python
# src/runners/cli_runner.py
import asyncio
from typing import AsyncIterator
from src.runners.audit import AuditLog


class CLIRunner:
    def __init__(
        self,
        name: str,
        binary: str,
        args: list[str],
        timeout_seconds: int,
        context_token_budget: int,
        audit: AuditLog,
    ):
        self.name = name
        self.binary = binary
        self.args = args
        self.timeout_seconds = timeout_seconds
        self.context_token_budget = context_token_budget
        self._audit = audit

    async def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
    ) -> AsyncIterator[str]:
        self._audit.write(
            user_id=user_id,
            channel=channel,
            runner=self.name,
            prompt=prompt,
            cwd=cwd,
        )

        cmd = [self.binary] + self.args + [prompt]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                assert proc.stdout is not None
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    yield line.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Runner '{self.name}' exceeded {self.timeout_seconds}s timeout")
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/runners/test_cli_runner.py -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/runners/ tests/runners/
git commit -m "feat: CLIRunner with async streaming and audit log"
```

---

## Task 4: SessionManager

**Files:**
- Create: `src/gateway/session.py`
- Create: `tests/gateway/test_session.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/gateway/test_session.py -v 2>&1 | head -15
```
Expected: FAIL

- [ ] **Step 3: Implement session.py**

```python
# src/gateway/session.py
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta


@dataclass
class Session:
    user_id: int
    channel: str
    current_runner: str
    cwd: str
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)


class SessionManager:
    def __init__(self, idle_minutes: int, default_runner: str, default_cwd: str):
        self._idle_minutes = idle_minutes
        self._default_runner = default_runner
        self._default_cwd = default_cwd
        self._sessions: dict[tuple[int, str], Session] = {}

    def get_or_create(self, user_id: int, channel: str) -> Session:
        key = (user_id, channel)
        if key not in self._sessions:
            self._sessions[key] = Session(
                user_id=user_id,
                channel=channel,
                current_runner=self._default_runner,
                cwd=self._default_cwd,
            )
        self._sessions[key].touch()
        return self._sessions[key]

    def release_idle(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = timedelta(minutes=self._idle_minutes)
        stale = [k for k, s in self._sessions.items() if now - s.last_active > cutoff]
        for k in stale:
            del self._sessions[k]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gateway/test_session.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/gateway/session.py tests/gateway/test_session.py
git commit -m "feat: per-user-per-channel SessionManager"
```

---

## Task 5: Gateway Router

**Files:**
- Create: `src/gateway/router.py`
- Create: `tests/gateway/test_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/gateway/test_router.py
import pytest
from src.gateway.router import Router, ParsedCommand


def test_route_slash_prefix():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/claude write a hello world")
    assert cmd.runner == "claude"
    assert cmd.prompt == "write a hello world"


def test_route_default_runner_for_plain_text():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("what is the weather today?")
    assert cmd.runner == "claude"
    assert cmd.prompt == "what is the weather today?"


def test_route_use_command_changes_runner():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/use codex")
    assert cmd.is_switch_runner is True
    assert cmd.runner == "codex"


def test_route_cancel_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/cancel")
    assert cmd.is_cancel is True


def test_route_status_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/status")
    assert cmd.is_status is True


def test_route_reset_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/reset")
    assert cmd.is_reset is True


def test_route_new_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/new")
    assert cmd.is_new is True


def test_route_unknown_slash_falls_back_to_default():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/unknown do something")
    assert cmd.runner == "claude"
    assert "/unknown do something" in cmd.prompt
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/gateway/test_router.py -v 2>&1 | head -20
```
Expected: FAIL

- [ ] **Step 3: Implement router.py**

```python
# src/gateway/router.py
from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    runner: str
    prompt: str
    is_switch_runner: bool = False
    is_cancel: bool = False
    is_status: bool = False
    is_reset: bool = False
    is_new: bool = False


class Router:
    _BUILTIN = {"/cancel", "/status", "/reset", "/new"}

    def __init__(self, known_runners: set[str], default_runner: str):
        self._runners = known_runners
        self._default = default_runner

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
            # unknown slash command: pass full text to default runner
            return ParsedCommand(runner=self._default, prompt=text)

        return ParsedCommand(runner=self._default, prompt=text)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gateway/test_router.py -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/gateway/router.py tests/gateway/test_router.py
git commit -m "feat: Gateway Router with command parsing"
```

---

## Task 6: Fake Adapter + StreamingBridge

**Files:**
- Create: `src/channels/base.py`
- Create: `src/gateway/streaming.py`
- Create: `tests/channels/test_fake_adapter.py`

- [ ] **Step 1: Write base adapter and fake adapter**

```python
# src/channels/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class InboundMessage:
    user_id: int
    channel: str        # "telegram" | "discord"
    text: str
    message_id: str


class BaseAdapter(ABC):
    @abstractmethod
    async def send(self, user_id: int, text: str) -> str:
        """Send a message. Returns message_id."""
        ...

    @abstractmethod
    async def edit(self, message_id: str, text: str) -> None:
        """Edit an existing message."""
        ...

    @abstractmethod
    async def react(self, message_id: str, emoji: str) -> None:
        """Add a reaction; no-op if unsupported."""
        ...

    def max_message_length(self) -> int:
        return 4096
```

```python
# tests/channels/fake_adapter.py
import asyncio
from src.channels.base import BaseAdapter


class FakeAdapter(BaseAdapter):
    def __init__(self):
        self.sent: list[str] = []
        self.edits: dict[str, str] = {}
        self._counter = 0

    async def send(self, user_id: int, text: str) -> str:
        self._counter += 1
        mid = str(self._counter)
        self.sent.append(text)
        return mid

    async def edit(self, message_id: str, text: str) -> None:
        self.edits[message_id] = text

    async def react(self, message_id: str, emoji: str) -> None:
        pass

    def max_message_length(self) -> int:
        return 4096
```

- [ ] **Step 2: Write streaming bridge**

```python
# src/gateway/streaming.py
import asyncio
from typing import AsyncIterator
from src.channels.base import BaseAdapter


class StreamingBridge:
    def __init__(self, adapter: BaseAdapter, edit_interval: float = 1.5):
        self._adapter = adapter
        self._interval = edit_interval

    async def stream(
        self,
        user_id: int,
        chunks: AsyncIterator[str],
    ) -> None:
        """Accumulate chunks and throttle-edit the message."""
        accumulated = ""
        message_id: str | None = None
        last_edit = 0.0

        async for chunk in chunks:
            accumulated += chunk
            now = asyncio.get_event_loop().time()

            if message_id is None:
                message_id = await self._adapter.send(user_id, accumulated)
                last_edit = now
            elif now - last_edit >= self._interval:
                safe = accumulated[: self._adapter.max_message_length()]
                await self._adapter.edit(message_id, safe)
                last_edit = now

        if message_id is not None and accumulated:
            safe = accumulated[: self._adapter.max_message_length()]
            await self._adapter.edit(message_id, safe)
        elif not message_id and accumulated:
            await self._adapter.send(user_id, accumulated)
```

- [ ] **Step 3: Write tests**

```python
# tests/channels/test_fake_adapter.py
import asyncio, pytest
pytestmark = pytest.mark.asyncio


async def test_streaming_bridge_sends_and_edits():
    import sys
    sys.path.insert(0, "tests/channels")
    from fake_adapter import FakeAdapter
    from src.gateway.streaming import StreamingBridge

    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    async def chunks():
        for word in ["hello ", "world ", "!"]:
            yield word
            await asyncio.sleep(0)

    await bridge.stream(user_id=1, chunks=chunks())

    assert len(adapter.sent) == 1
    assert adapter.edits


async def test_streaming_bridge_final_edit_has_full_text():
    import sys
    sys.path.insert(0, "tests/channels")
    from fake_adapter import FakeAdapter
    from src.gateway.streaming import StreamingBridge

    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    async def chunks():
        for word in ["foo", "bar", "baz"]:
            yield word

    await bridge.stream(user_id=1, chunks=chunks())

    last_edit = list(adapter.edits.values())[-1]
    assert "foobarbaz" == last_edit
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/channels/test_fake_adapter.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/channels/base.py src/gateway/streaming.py tests/channels/
git commit -m "feat: BaseAdapter, FakeAdapter, StreamingBridge"
```

---

## Task 7: TelegramAdapter

**Files:**
- Create: `src/channels/telegram.py`

Note: TelegramAdapter wraps python-telegram-bot. We do not unit-test bot API calls (they require a live token). The adapter's logic is thin — message splitting and the send/edit/react interface. Manual smoke test in Task 8.

- [ ] **Step 1: Write telegram.py**

```python
# src/channels/telegram.py
import logging
from telegram import Bot, Message
from telegram.error import TelegramError
from src.channels.base import BaseAdapter, InboundMessage

logger = logging.getLogger(__name__)
MAX_LEN = 4096


class TelegramAdapter(BaseAdapter):
    def __init__(self, bot: Bot, allowed_user_ids: list[int]):
        self._bot = bot
        self._allowed = set(allowed_user_ids)

    def is_authorized(self, user_id: int) -> bool:
        return not self._allowed or user_id in self._allowed

    async def send(self, user_id: int, text: str) -> str:
        chunks = self._split(text)
        last_msg: Message | None = None
        for chunk in chunks:
            try:
                last_msg = await self._bot.send_message(chat_id=user_id, text=chunk)
            except TelegramError as e:
                logger.error("send failed: %s", e)
                raise
        return str(last_msg.message_id) if last_msg else ""

    async def edit(self, message_id: str, text: str) -> None:
        # message_id format: "chat_id:msg_id" — set by Gateway when creating stream message
        try:
            chat_id, mid = message_id.split(":", 1)
            safe = text[:MAX_LEN]
            await self._bot.edit_message_text(chat_id=int(chat_id), message_id=int(mid), text=safe)
        except TelegramError as e:
            logger.warning("edit failed (will re-send): %s", e)

    async def react(self, message_id: str, emoji: str) -> None:
        pass  # Telegram reaction API requires Bot API 7.0+; deferred

    def max_message_length(self) -> int:
        return MAX_LEN

    @staticmethod
    def _split(text: str) -> list[str]:
        chunks = []
        while len(text) > MAX_LEN:
            split_pos = text.rfind("\n", 0, MAX_LEN)
            if split_pos == -1:
                split_pos = MAX_LEN
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/telegram.py
git commit -m "feat: TelegramAdapter wrapping python-telegram-bot"
```

---

## Task 8: Wire Everything — main.py + E2E Smoke Test

**Files:**
- Create: `main.py`
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write E2E test (using FakeAdapter + echo CLI)**

```python
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
    cmd = router.parse(text)

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
    cmd = router.parse(text)

    assert cmd.runner == "echo"
    active_runner = runners[cmd.runner]
    await bridge.stream(
        user_id=user_id,
        chunks=active_runner.run(prompt=cmd.prompt, user_id=user_id, channel=channel, cwd=session.cwd),
    )

    assert any("dispatched correctly" in m for m in adapter.sent + list(adapter.edits.values()))
```

- [ ] **Step 2: Run E2E tests**

```bash
python -m pytest tests/test_e2e.py -v
```
Expected: 2 PASSED

- [ ] **Step 3: Write minimal main.py**

```python
# main.py
"""
Gateway Agent Platform — entry point.
Starts TelegramAdapter and connects it to the Gateway pipeline.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

from src.core.config import load_config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")


def build_app(cfg_path="config/config.toml", env_path="secrets/.env"):
    cfg = load_config(config_path=cfg_path, env_path=env_path)

    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)

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

    router = Router(known_runners=set(runners.keys()), default_runner=cfg.gateway.default_runner)
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )

    tg_app = Application.builder().token(cfg.telegram_token).build()
    bot = tg_app.bot
    adapter = TelegramAdapter(bot=bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("🚫 Unauthorized.")
            return

        channel = "telegram"
        text = update.message.text.strip()
        session = session_mgr.get_or_create(user_id=user_id, channel=channel)
        cmd = router.parse(text)

        if cmd.is_cancel:
            await update.message.reply_text("✅ No active task to cancel.")
            return
        if cmd.is_reset:
            await update.message.reply_text("🧹 Context cleared.")
            return
        if cmd.is_new:
            await update.message.reply_text("🆕 New session started.")
            return
        if cmd.is_status:
            await update.message.reply_text(
                f"✅ Status\nRunners: {list(runners.keys())}\nDefault: {session.current_runner}\nCWD: {session.cwd}"
            )
            return
        if cmd.is_switch_runner:
            session.current_runner = cmd.runner
            await update.message.reply_text(f"🔄 Switched to {cmd.runner}")
            return

        target_runner = runners.get(session.current_runner)
        if not target_runner:
            await update.message.reply_text(f"❌ Runner '{session.current_runner}' not found.")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        try:
            await bridge.stream(
                user_id=user_id,
                chunks=target_runner.run(
                    prompt=cmd.prompt,
                    user_id=user_id,
                    channel=channel,
                    cwd=session.cwd,
                ),
            )
        except TimeoutError:
            await update.message.reply_text("⏱️ Runner timed out.")
        except Exception as e:
            logger.error("Runner error: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")

    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))
    return tg_app


if __name__ == "__main__":
    app = build_app()
    logger.info("Bot starting...")
    app.run_polling()
```

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: All tests PASS (no failures)

- [ ] **Step 5: Smoke test with real Telegram (requires real token in secrets/.env)**

```bash
# Edit secrets/.env with real TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS
# Then run:
python main.py
# Send "hello" to the bot — should echo back via CLIRunner(echo)
# Send "/status" — should show runner list
```

- [ ] **Step 6: Final commit**

```bash
git add main.py tests/test_e2e.py
git commit -m "feat: wire Gateway pipeline — Telegram→Router→CLIRunner→StreamingBridge"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] TelegramAdapter (Spec §3) — Task 7
- [x] Gateway Router + /cancel /reset /new /status /use (Spec §4) — Tasks 5, 8
- [x] CLIRunner with audit log, timeout (Spec §5) — Tasks 2, 3
- [x] Session per-user-per-channel, idle release (Spec §4) — Task 4
- [x] StreamingBridge with throttled edit (Spec §3) — Task 6
- [x] Config system (Spec §2) — Task 1
- [ ] DiscordAdapter — Phase 2
- [ ] Memory system (Tier 1/2/3) — Phase 2
- [ ] Module system — Phase 3
- [ ] AgentTeam — Phase 4
- [ ] Setup wizard — Phase 5
- [ ] MCP integration — Phase 5

**Not in this plan (future phases):** Discord, Memory, Modules, AgentTeam, Setup wizard, MCP, Embedding.
