# Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive Python wizard (`setup.py`) that configures, installs, and launches the Gateway Agent Platform in one run.

**Architecture:** Seven tasks build the wizard bottom-up — state persistence, token validation, background installer, config/deploy writers, wizard step functions, orchestrator, and entry point. Each task adds one focused file with its tests before wiring everything together.

**Tech Stack:** Python 3.11+, asyncio, urllib.request (stdlib), python-telegram-bot (already in requirements.txt), shutil, subprocess

---

## File Map

| File | Purpose |
|------|---------|
| `src/setup/__init__.py` | package marker |
| `src/setup/state.py` | WizardState dataclass + load/save/reset to JSON |
| `src/setup/validator.py` | HTTP token validation (Telegram + Discord) |
| `src/setup/installer.py` | detect installed CLIs; background install tasks |
| `src/setup/deploy.py` | write config.toml, .env, systemd unit, docker-compose, data dirs |
| `src/setup/wizard.py` | 8 step functions + run_wizard() orchestrator |
| `setup.py` | entry point: argparse + asyncio.run() |
| `tests/setup/__init__.py` | package marker |
| `tests/setup/test_state.py` | state load/save/reset/mark tests |
| `tests/setup/test_validator.py` | token validation with mocked urllib |
| `tests/setup/test_installer.py` | shutil.which mock + subprocess mock |
| `tests/setup/test_deploy.py` | file content verification in tmpdir |
| `tests/setup/test_wizard.py` | step sequencing, resume, --reset |

---

### Task 1: State Module

**Files:**
- Create: `src/setup/__init__.py`
- Create: `src/setup/state.py`
- Create: `tests/setup/__init__.py`
- Create: `tests/setup/test_state.py`

- [ ] **Step 1: Create package markers**

```bash
touch /tmp/telegram-to-control/src/setup/__init__.py
touch /tmp/telegram-to-control/tests/setup/__init__.py
```

- [ ] **Step 2: Write the failing tests**

`tests/setup/test_state.py`:
```python
import pytest
from pathlib import Path
from src.setup.state import (
    WizardState, load_state, save_state, reset_state,
    is_step_done, mark_step_done,
)


def test_load_state_returns_default_when_missing(tmp_path):
    state = load_state(str(tmp_path / "state.json"))
    assert state.completed_steps == []
    assert state.channel == ""
    assert state.telegram_token == ""
    assert state.allowed_user_ids == []


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    s = WizardState(
        channel="telegram",
        telegram_token="abc",
        completed_steps=[1, 2],
        allowed_user_ids=[999],
        selected_clis=["claude"],
        search_mode="fts5",
        update_notifications=True,
        deploy_mode="systemd",
    )
    save_state(s, path)
    loaded = load_state(path)
    assert loaded.channel == "telegram"
    assert loaded.telegram_token == "abc"
    assert 1 in loaded.completed_steps
    assert 2 in loaded.completed_steps
    assert loaded.allowed_user_ids == [999]
    assert loaded.selected_clis == ["claude"]
    assert loaded.deploy_mode == "systemd"


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "data" / "sub" / "state.json")
    save_state(WizardState(), path)
    assert Path(path).exists()


def test_reset_state_removes_file(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(WizardState(completed_steps=[1]), path)
    reset_state(path)
    assert not Path(path).exists()


def test_reset_state_noop_when_missing(tmp_path):
    reset_state(str(tmp_path / "no-state.json"))  # must not raise


def test_is_step_done_false_initially():
    s = WizardState()
    assert not is_step_done(s, 1)
    assert not is_step_done(s, 5)


def test_mark_step_done_and_check():
    s = WizardState()
    mark_step_done(s, 3)
    assert is_step_done(s, 3)
    assert not is_step_done(s, 4)


def test_mark_step_done_idempotent():
    s = WizardState()
    mark_step_done(s, 1)
    mark_step_done(s, 1)
    assert s.completed_steps.count(1) == 1


def test_load_state_ignores_unknown_keys(tmp_path):
    import json
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({"channel": "telegram", "future_key": "ignored"}))
    state = load_state(path)
    assert state.channel == "telegram"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_state.py -v 2>&1 | head -20
```
Expected: `ImportError` or `ModuleNotFoundError` for `src.setup.state`

- [ ] **Step 4: Implement `src/setup/state.py`**

```python
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WizardState:
    completed_steps: list[int] = field(default_factory=list)
    channel: str = ""
    telegram_token: str = ""
    discord_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    selected_clis: list[str] = field(default_factory=list)
    search_mode: str = "fts5"
    update_notifications: bool = True
    deploy_mode: str = "foreground"


_FIELDS = set(WizardState.__dataclass_fields__)


def load_state(path: str) -> WizardState:
    p = Path(path)
    if not p.exists():
        return WizardState()
    with open(p) as f:
        data = json.load(f)
    return WizardState(**{k: v for k, v in data.items() if k in _FIELDS})


def save_state(state: WizardState, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "completed_steps": state.completed_steps,
            "channel": state.channel,
            "telegram_token": state.telegram_token,
            "discord_token": state.discord_token,
            "allowed_user_ids": state.allowed_user_ids,
            "selected_clis": state.selected_clis,
            "search_mode": state.search_mode,
            "update_notifications": state.update_notifications,
            "deploy_mode": state.deploy_mode,
        }, f, indent=2)


def reset_state(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def is_step_done(state: WizardState, step: int) -> bool:
    return step in state.completed_steps


def mark_step_done(state: WizardState, step: int) -> None:
    if step not in state.completed_steps:
        state.completed_steps.append(step)
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_state.py -v
```
Expected: 9 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/__init__.py src/setup/state.py tests/setup/__init__.py tests/setup/test_state.py && git commit -m "feat: add setup wizard state persistence module"
```

---

### Task 2: Validator Module

**Files:**
- Create: `src/setup/validator.py`
- Create: `tests/setup/test_validator.py`

- [ ] **Step 1: Write the failing tests**

`tests/setup/test_validator.py`:
```python
import pytest
import urllib.error
from unittest.mock import patch, MagicMock
from src.setup.validator import validate_telegram_token, validate_discord_token


def _make_mock_response(body: bytes, status: int = 200):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = body
    mock.status = status
    return mock


def test_validate_telegram_token_valid():
    resp = _make_mock_response(b'{"ok": true, "result": {"id": 123}}')
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token("valid-token") is True


def test_validate_telegram_token_ok_false():
    resp = _make_mock_response(b'{"ok": false}')
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token("bad-token") is False


def test_validate_telegram_token_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        assert validate_telegram_token("token") is False


def test_validate_telegram_token_bad_json():
    resp = _make_mock_response(b"not-json")
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token("token") is False


def test_validate_discord_token_valid():
    resp = _make_mock_response(b'{"id": "123"}', status=200)
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_discord_token("valid-token") is True


def test_validate_discord_token_unauthorized():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 401, "Unauthorized", {}, None),
    ):
        assert validate_discord_token("bad-token") is False


def test_validate_discord_token_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert validate_discord_token("token") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_validator.py -v 2>&1 | head -10
```
Expected: `ImportError` for `src.setup.validator`

- [ ] **Step 3: Implement `src/setup/validator.py`**

```python
import json
import urllib.error
import urllib.request


def validate_telegram_token(token: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return bool(data.get("ok"))
    except (urllib.error.URLError, ValueError):
        return False


def validate_discord_token(token: str) -> bool:
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_validator.py -v
```
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/validator.py tests/setup/test_validator.py && git commit -m "feat: add token validator for Telegram and Discord"
```

---

### Task 3: Installer Module

**Files:**
- Create: `src/setup/installer.py`
- Create: `tests/setup/test_installer.py`

- [ ] **Step 1: Write the failing tests**

`tests/setup/test_installer.py`:
```python
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.installer import is_cli_installed, install_cli, install_ollama, progress_reporter


def test_is_cli_installed_found():
    with patch("shutil.which", return_value="/usr/bin/claude"):
        assert is_cli_installed("claude") is True


def test_is_cli_installed_not_found():
    with patch("shutil.which", return_value=None):
        assert is_cli_installed("claude") is False


@pytest.mark.asyncio
async def test_install_cli_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        name, success = await install_cli("claude")
    assert name == "claude"
    assert success is True


@pytest.mark.asyncio
async def test_install_cli_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        name, success = await install_cli("codex")
    assert name == "codex"
    assert success is False


@pytest.mark.asyncio
async def test_install_cli_unknown_returns_false():
    name, success = await install_cli("unknown-tool")
    assert name == "unknown-tool"
    assert success is False


@pytest.mark.asyncio
async def test_install_ollama_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await install_ollama()
    assert result is True


@pytest.mark.asyncio
async def test_install_ollama_install_fails():
    mock_proc_fail = AsyncMock()
    mock_proc_fail.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_fail):
        result = await install_ollama()
    assert result is False


@pytest.mark.asyncio
async def test_progress_reporter_exits_when_tasks_done():
    task = asyncio.create_task(asyncio.sleep(0))
    await task  # mark done
    # Should return without blocking
    await asyncio.wait_for(progress_reporter([task], ["claude"], interval=1), timeout=3)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_installer.py -v 2>&1 | head -10
```
Expected: `ImportError` for `src.setup.installer`

- [ ] **Step 3: Implement `src/setup/installer.py`**

```python
import asyncio
import shutil


_CLI_INSTALL: dict[str, list[str]] = {
    "claude": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "gemini": ["npm", "install", "-g", "@google/generative-ai"],
    "kiro": ["npm", "install", "-g", "@aws/kiro"],
}

_OLLAMA_INSTALL = ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
_OLLAMA_PULL = ["ollama", "pull", "nomic-embed-text"]


def is_cli_installed(name: str) -> bool:
    return shutil.which(name) is not None


async def install_cli(name: str) -> tuple[str, bool]:
    cmd = _CLI_INSTALL.get(name)
    if not cmd:
        return name, False
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.wait()
    return name, proc.returncode == 0


async def install_ollama() -> bool:
    proc = await asyncio.create_subprocess_exec(
        *_OLLAMA_INSTALL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.wait()
    if proc.returncode != 0:
        return False
    proc2 = await asyncio.create_subprocess_exec(
        *_OLLAMA_PULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc2.wait()
    return proc2.returncode == 0


async def progress_reporter(
    tasks: list[asyncio.Task], names: list[str], interval: int = 30
) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(interval)
        elapsed += interval
        pending = [names[i] for i, t in enumerate(tasks) if not t.done()]
        if not pending:
            break
        print(f"[background] Still installing: {', '.join(pending)} ({elapsed}s elapsed)")
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_installer.py -v
```
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/installer.py tests/setup/test_installer.py && git commit -m "feat: add background CLI and Ollama installer"
```

---

### Task 4: Deploy Module

**Files:**
- Create: `src/setup/deploy.py`
- Create: `tests/setup/test_deploy.py`

- [ ] **Step 1: Write the failing tests**

`tests/setup/test_deploy.py`:
```python
import pytest
from pathlib import Path
from unittest.mock import patch
from src.setup.deploy import (
    write_config_toml, write_env_file, write_systemd_unit,
    write_docker_compose, create_data_dirs,
)


def test_write_config_toml_creates_file(tmp_path):
    path = str(tmp_path / "config/config.toml")
    write_config_toml(path, {"default_runner": "claude", "runners": ["claude"]})
    assert Path(path).exists()


def test_write_config_toml_contains_default_runner(tmp_path):
    path = str(tmp_path / "config.toml")
    write_config_toml(path, {"default_runner": "codex", "runners": ["codex"]})
    content = Path(path).read_text()
    assert 'default_runner = "codex"' in content


def test_write_config_toml_includes_runner_sections(tmp_path):
    path = str(tmp_path / "config.toml")
    write_config_toml(path, {"default_runner": "claude", "runners": ["claude", "gemini"]})
    content = Path(path).read_text()
    assert "[runners.claude]" in content
    assert "[runners.gemini]" in content
    assert "[runners.codex]" not in content


def test_write_env_file_creates_file(tmp_path):
    path = str(tmp_path / "secrets/.env")
    write_env_file(path, {"TELEGRAM_BOT_TOKEN": "abc"})
    assert Path(path).exists()


def test_write_env_file_content(tmp_path):
    path = str(tmp_path / ".env")
    write_env_file(path, {"TELEGRAM_BOT_TOKEN": "tok123", "ALLOWED_USER_IDS": "456,789"})
    content = Path(path).read_text()
    assert "TELEGRAM_BOT_TOKEN=tok123" in content
    assert "ALLOWED_USER_IDS=456,789" in content


def test_write_systemd_unit_content(tmp_path):
    with patch.object(Path, "home", return_value=tmp_path):
        write_systemd_unit("/opt/gateway")
    unit_path = tmp_path / ".config/systemd/user/gateway-agent.service"
    assert unit_path.exists()
    content = unit_path.read_text()
    assert "WorkingDirectory=/opt/gateway" in content
    assert "ExecStart=/opt/gateway/venv/bin/python3 main.py" in content
    assert "Restart=always" in content


def test_write_docker_compose_content(tmp_path):
    write_docker_compose(str(tmp_path))
    compose = (tmp_path / "docker-compose.yml").read_text()
    assert "gateway:" in compose
    assert "./data:/app/data" in compose
    assert "restart: unless-stopped" in compose


def test_write_docker_compose_creates_dockerfile_if_missing(tmp_path):
    write_docker_compose(str(tmp_path))
    assert (tmp_path / "Dockerfile").exists()


def test_write_docker_compose_does_not_overwrite_existing_dockerfile(tmp_path):
    existing = "FROM custom-base\n"
    (tmp_path / "Dockerfile").write_text(existing)
    write_docker_compose(str(tmp_path))
    assert (tmp_path / "Dockerfile").read_text() == existing


def test_create_data_dirs(tmp_path):
    create_data_dirs(str(tmp_path))
    for subdir in ["data/memory/hot", "data/memory/cold/permanent",
                   "data/memory/cold/session", "data/db", "data/audit"]:
        assert (tmp_path / subdir).is_dir()


def test_create_data_dirs_idempotent(tmp_path):
    create_data_dirs(str(tmp_path))
    create_data_dirs(str(tmp_path))  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_deploy.py -v 2>&1 | head -10
```
Expected: `ImportError` for `src.setup.deploy`

- [ ] **Step 3: Implement `src/setup/deploy.py`**

```python
from pathlib import Path


_RUNNER_CONFIGS: dict[str, str] = {
    "claude": (
        '[runners.claude]\npath = "claude"\n'
        'args = ["--dangerously-skip-permissions"]\n'
        "timeout_seconds = 300\ncontext_token_budget = 4000"
    ),
    "codex": (
        '[runners.codex]\npath = "codex"\n'
        'args = ["--approval-policy", "auto"]\n'
        "timeout_seconds = 300\ncontext_token_budget = 4000"
    ),
    "gemini": (
        '[runners.gemini]\npath = "gemini"\nargs = []\n'
        "timeout_seconds = 300\ncontext_token_budget = 4000"
    ),
    "kiro": (
        '[runners.kiro]\npath = "kiro"\nargs = []\n'
        "timeout_seconds = 300\ncontext_token_budget = 4000"
    ),
}

_TOML_TEMPLATE = """\
[gateway]
default_runner = "{default_runner}"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

{runner_sections}

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

[modules]
dir = "modules"
"""

_DOCKERFILE = (
    "FROM python:3.11-slim\n"
    "WORKDIR /app\n"
    "COPY requirements.txt .\n"
    "RUN pip install -r requirements.txt\n"
    "COPY . .\n"
    'CMD ["python", "main.py"]\n'
)

_DOCKER_COMPOSE = (
    "services:\n"
    "  gateway:\n"
    "    build: .\n"
    "    restart: unless-stopped\n"
    "    volumes:\n"
    "      - ./config:/app/config:ro\n"
    "      - ./secrets:/app/secrets:ro\n"
    "      - ./data:/app/data\n"
    "    environment:\n"
    "      - PYTHONUNBUFFERED=1\n"
)


def write_config_toml(path: str, config: dict) -> None:
    runners = config.get("runners", [])
    sections = "\n\n".join(
        _RUNNER_CONFIGS[r] for r in runners if r in _RUNNER_CONFIGS
    )
    content = _TOML_TEMPLATE.format(
        default_runner=config.get("default_runner", "claude"),
        runner_sections=sections,
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def write_env_file(path: str, env: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")


def write_systemd_unit(cwd: str) -> None:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    path_env = (
        f"{cwd}/venv/bin:/usr/local/sbin:/usr/local/bin"
        ":/usr/sbin:/usr/bin:/sbin:/bin"
    )
    content = (
        "[Unit]\n"
        "Description=Gateway Agent Platform\n"
        "After=network.target\n\n"
        "[Service]\n"
        f"WorkingDirectory={cwd}\n"
        f"ExecStart={cwd}/venv/bin/python3 main.py\n"
        "Restart=always\n"
        "RestartSec=5\n"
        f'Environment="PATH={path_env}"\n\n'
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    (unit_dir / "gateway-agent.service").write_text(content)


def write_docker_compose(cwd: str) -> None:
    base = Path(cwd)
    dockerfile = base / "Dockerfile"
    if not dockerfile.exists():
        dockerfile.write_text(_DOCKERFILE)
    (base / "docker-compose.yml").write_text(_DOCKER_COMPOSE)


def create_data_dirs(base: str) -> None:
    for subdir in (
        "data/memory/hot",
        "data/memory/cold/permanent",
        "data/memory/cold/session",
        "data/db",
        "data/audit",
    ):
        (Path(base) / subdir).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_deploy.py -v
```
Expected: 11 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/deploy.py tests/setup/test_deploy.py && git commit -m "feat: add deploy module — config.toml, .env, systemd, docker writers"
```

---

### Task 5: Wizard Steps 1–3 (Channel, Token, Allowlist)

**Files:**
- Create: `src/setup/wizard.py` (partial — steps 1-3 + helpers)
- Create: `tests/setup/test_wizard.py` (partial)

- [ ] **Step 1: Write the failing tests**

`tests/setup/test_wizard.py`:
```python
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.state import WizardState, mark_step_done
from src.setup import wizard


# ── Step 1: channel ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step1_telegram(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "1")
    await wizard.step_1_channel(state)
    assert state.channel == "telegram"
    assert 1 in state.completed_steps


@pytest.mark.asyncio
async def test_step1_discord(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "2")
    await wizard.step_1_channel(state)
    assert state.channel == "discord"


@pytest.mark.asyncio
async def test_step1_both(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "3")
    await wizard.step_1_channel(state)
    assert state.channel == "both"


@pytest.mark.asyncio
async def test_step1_skipped_if_done():
    state = WizardState(completed_steps=[1], channel="discord")
    await wizard.step_1_channel(state)  # no input() called — would raise StopIteration
    assert state.channel == "discord"


@pytest.mark.asyncio
async def test_step1_retries_on_invalid_choice(monkeypatch):
    state = WizardState()
    responses = iter(["9", "x", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    await wizard.step_1_channel(state)
    assert state.channel == "telegram"


# ── Step 2: token ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step2_telegram_valid_token(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1])
    monkeypatch.setattr("builtins.input", lambda _: "valid-tok")
    with patch("src.setup.wizard.validate_telegram_token", return_value=True):
        await wizard.step_2_token(state)
    assert state.telegram_token == "valid-tok"
    assert 2 in state.completed_steps


@pytest.mark.asyncio
async def test_step2_retries_invalid_token(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1])
    responses = iter(["bad", "good"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    side_effects = [False, True]
    idx = [0]
    def _validate(t):
        r = side_effects[idx[0]]; idx[0] += 1; return r
    with patch("src.setup.wizard.validate_telegram_token", side_effect=_validate):
        await wizard.step_2_token(state)
    assert state.telegram_token == "good"


@pytest.mark.asyncio
async def test_step2_discord_valid_token(monkeypatch):
    state = WizardState(channel="discord", completed_steps=[1])
    monkeypatch.setattr("builtins.input", lambda _: "disc-tok")
    with patch("src.setup.wizard.validate_discord_token", return_value=True):
        await wizard.step_2_token(state)
    assert state.discord_token == "disc-tok"


@pytest.mark.asyncio
async def test_step2_skipped_if_done():
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="existing")
    await wizard.step_2_token(state)
    assert state.telegram_token == "existing"


# ── Step 3: allowlist ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step3_manual_fallback(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="tok")
    monkeypatch.setattr("builtins.input", lambda _: "12345")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=None):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [12345]
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_auto_capture(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="tok")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=99999):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [99999]


@pytest.mark.asyncio
async def test_step3_discord_manual(monkeypatch):
    state = WizardState(channel="discord", completed_steps=[1, 2])
    monkeypatch.setattr("builtins.input", lambda _: "777")
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [777]


@pytest.mark.asyncio
async def test_step3_skipped_if_done():
    state = WizardState(channel="telegram", completed_steps=[1, 2, 3], allowed_user_ids=[42])
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [42]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_wizard.py -v 2>&1 | head -10
```
Expected: `ImportError` for `src.setup.wizard`

- [ ] **Step 3: Implement `src/setup/wizard.py` (steps 1–3 + helpers)**

```python
import asyncio
import sys

from src.setup.state import WizardState, is_step_done, mark_step_done
from src.setup.validator import validate_telegram_token, validate_discord_token

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"


def _hdr(n: int, title: str) -> None:
    print(f"\n{_B}[{n}/8] {title}{_X}")


def _ok(msg: str) -> None:
    print(f"{_G}✓ {msg}{_X}")


def _warn(msg: str) -> None:
    print(f"{_Y}⚠ {msg}{_X}")


def _err(msg: str) -> None:
    print(f"{_R}✗ {msg}{_X}")


def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{msg}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)
    return val or default


async def step_1_channel(state: WizardState) -> None:
    if is_step_done(state, 1):
        _ok(f"Step 1 done (channel: {state.channel})")
        return
    _hdr(1, "Channel Selection")
    print("  1. Telegram only\n  2. Discord only\n  3. Both")
    while True:
        choice = _prompt("Choose", "1")
        if choice == "1":
            state.channel = "telegram"
            break
        elif choice == "2":
            state.channel = "discord"
            break
        elif choice == "3":
            state.channel = "both"
            break
        else:
            _err("Enter 1, 2, or 3")
    _ok(f"Channel: {state.channel}")
    mark_step_done(state, 1)


async def step_2_token(state: WizardState) -> None:
    if is_step_done(state, 2):
        _ok("Step 2 done (tokens validated)")
        return
    _hdr(2, "Bot Token")
    if state.channel in ("telegram", "both"):
        while True:
            token = _prompt("Telegram bot token")
            if not token:
                _err("Token required")
                continue
            print("  Validating...")
            if validate_telegram_token(token):
                state.telegram_token = token
                _ok("Telegram token valid")
                break
            _err("Invalid token. Try again.")
    if state.channel in ("discord", "both"):
        while True:
            token = _prompt("Discord bot token")
            if not token:
                _err("Token required")
                continue
            print("  Validating...")
            if validate_discord_token(token):
                state.discord_token = token
                _ok("Discord token valid")
                break
            _err("Invalid token. Try again.")
    mark_step_done(state, 2)


async def _capture_telegram_user_id(token: str, timeout: int = 30) -> int | None:
    try:
        from telegram import Update
        from telegram.ext import Application, MessageHandler, ContextTypes, filters
    except ImportError:
        return None

    captured: list[int] = []

    async def _handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user:
            captured.append(update.effective_user.id)

    print(f"  Send any message to your bot now (waiting {timeout}s)...")
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.ALL, _handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    try:
        for _ in range(timeout):
            await asyncio.sleep(1)
            if captured:
                break
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
    return captured[0] if captured else None


async def step_3_allowlist(state: WizardState) -> None:
    if is_step_done(state, 3):
        _ok(f"Step 3 done (user IDs: {state.allowed_user_ids})")
        return
    _hdr(3, "Allowlist — Authorised User IDs")
    if state.channel in ("telegram", "both") and state.telegram_token:
        uid = await _capture_telegram_user_id(state.telegram_token)
        if uid:
            state.allowed_user_ids = [uid]
            _ok(f"Captured user ID: {uid}")
        else:
            raw = _prompt("Enter your Telegram user ID manually")
            if raw.isdigit():
                state.allowed_user_ids = [int(raw)]
    else:
        raw = _prompt("Enter your Discord user ID")
        if raw.isdigit():
            state.allowed_user_ids = [int(raw)]
    if not state.allowed_user_ids:
        _warn("No user IDs set — bot will be accessible to anyone!")
    mark_step_done(state, 3)
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_wizard.py -v
```
Expected: 16 tests pass (all step 1-3 tests)

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/wizard.py tests/setup/test_wizard.py && git commit -m "feat: add wizard steps 1-3 (channel, token, allowlist)"
```

---

### Task 6: Wizard Steps 4–7 (CLI, Search, Updates, Deploy)

**Files:**
- Modify: `src/setup/wizard.py` (add steps 4–7)
- Modify: `tests/setup/test_wizard.py` (add step 4–7 tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/setup/test_wizard.py`:
```python
# ── Step 4: CLI ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step4_selects_clis(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("builtins.input", lambda _: "claude,codex")
    with patch("src.setup.wizard.is_cli_installed", return_value=True):
        tasks = await wizard.step_4_clis(state)
    assert state.selected_clis == ["claude", "codex"]
    assert tasks == []  # all installed, no background tasks
    assert 4 in state.completed_steps


@pytest.mark.asyncio
async def test_step4_queues_install_for_missing(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("builtins.input", lambda _: "claude")
    with patch("src.setup.wizard.is_cli_installed", return_value=False):
        with patch("src.setup.wizard.install_cli", new_callable=AsyncMock, return_value=("claude", True)):
            tasks = await wizard.step_4_clis(state)
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_step4_defaults_to_claude_on_empty(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("builtins.input", lambda _: "")
    with patch("src.setup.wizard.is_cli_installed", return_value=True):
        await wizard.step_4_clis(state)
    assert "claude" in state.selected_clis


@pytest.mark.asyncio
async def test_step4_skipped_if_done():
    state = WizardState(completed_steps=[1, 2, 3, 4], selected_clis=["codex"])
    tasks = await wizard.step_4_clis(state)
    assert tasks == []
    assert state.selected_clis == ["codex"]


# ── Step 5: search ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step5_fts5_default(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4])
    monkeypatch.setattr("builtins.input", lambda _: "1")
    task = await wizard.step_5_search(state)
    assert state.search_mode == "fts5"
    assert task is None
    assert 5 in state.completed_steps


@pytest.mark.asyncio
async def test_step5_embedding_returns_task(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4])
    monkeypatch.setattr("builtins.input", lambda _: "2")
    with patch("src.setup.wizard.install_ollama", new_callable=AsyncMock, return_value=True):
        task = await wizard.step_5_search(state)
    assert state.search_mode == "fts5+embedding"
    assert task is not None


@pytest.mark.asyncio
async def test_step5_skipped_if_done():
    state = WizardState(completed_steps=[1, 2, 3, 4, 5], search_mode="fts5+embedding")
    task = await wizard.step_5_search(state)
    assert task is None
    assert state.search_mode == "fts5+embedding"


# ── Step 6: updates ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step6_updates_on(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5])
    monkeypatch.setattr("builtins.input", lambda _: "y")
    await wizard.step_6_updates(state)
    assert state.update_notifications is True
    assert 6 in state.completed_steps


@pytest.mark.asyncio
async def test_step6_updates_off(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5])
    monkeypatch.setattr("builtins.input", lambda _: "n")
    await wizard.step_6_updates(state)
    assert state.update_notifications is False


# ── Step 7: deploy ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step7_foreground(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6])
    monkeypatch.setattr("builtins.input", lambda _: "1")
    await wizard.step_7_deploy(state)
    assert state.deploy_mode == "foreground"
    assert 7 in state.completed_steps


@pytest.mark.asyncio
async def test_step7_systemd(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6])
    monkeypatch.setattr("builtins.input", lambda _: "2")
    await wizard.step_7_deploy(state)
    assert state.deploy_mode == "systemd"


@pytest.mark.asyncio
async def test_step7_docker(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6])
    monkeypatch.setattr("builtins.input", lambda _: "3")
    await wizard.step_7_deploy(state)
    assert state.deploy_mode == "docker"
```

- [ ] **Step 2: Run tests to verify new tests fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_wizard.py -v 2>&1 | tail -20
```
Expected: ~13 new test failures for steps 4-7

- [ ] **Step 3: Add steps 4–7 to `src/setup/wizard.py`**

Add these imports at the top of `src/setup/wizard.py` (after existing imports):
```python
from src.setup.installer import is_cli_installed, install_cli, install_ollama, progress_reporter
```

Then append these functions:
```python
_ALL_CLIS = ["claude", "codex", "gemini", "kiro"]


async def step_4_clis(state: WizardState) -> list[asyncio.Task]:
    if is_step_done(state, 4):
        _ok(f"Step 4 done (CLIs: {state.selected_clis})")
        return []
    _hdr(4, "CLI Tools")
    for cli in _ALL_CLIS:
        status = "installed" if is_cli_installed(cli) else "not found"
        print(f"  {cli}: {status}")
    raw = _prompt("Select CLIs (comma-separated: claude,codex,gemini,kiro)", "claude")
    selected = [c.strip() for c in raw.split(",") if c.strip() in _ALL_CLIS]
    if not selected:
        selected = ["claude"]
    state.selected_clis = selected
    bg_tasks: list[asyncio.Task] = []
    task_names: list[str] = []
    for cli in selected:
        if not is_cli_installed(cli):
            print(f"  Queuing background install: {cli}")
            t = asyncio.create_task(install_cli(cli))
            bg_tasks.append(t)
            task_names.append(cli)
    if bg_tasks:
        asyncio.create_task(progress_reporter(bg_tasks, task_names))
        _ok(f"Installing {task_names} in background — continuing...")
    mark_step_done(state, 4)
    return bg_tasks


async def step_5_search(state: WizardState) -> asyncio.Task | None:
    if is_step_done(state, 5):
        _ok(f"Step 5 done (search: {state.search_mode})")
        return None
    _hdr(5, "Search Mode")
    print("  1. FTS5 keyword search (default, no extra install)")
    print("  2. FTS5 + embedding (background Ollama install)")
    choice = _prompt("Choose", "1")
    if choice == "2":
        state.search_mode = "fts5+embedding"
        t = asyncio.create_task(install_ollama())
        asyncio.create_task(progress_reporter([t], ["ollama"]))
        _ok("Installing Ollama in background...")
        mark_step_done(state, 5)
        return t
    state.search_mode = "fts5"
    _ok("Search mode: FTS5")
    mark_step_done(state, 5)
    return None


async def step_6_updates(state: WizardState) -> None:
    if is_step_done(state, 6):
        _ok(f"Step 6 done (update notifications: {state.update_notifications})")
        return
    _hdr(6, "Update Notifications")
    print("  Check for new GitHub releases on startup and print a notice.")
    print("  (Never auto-updates — you control when to update.)")
    choice = _prompt("Enable? (y/n)", "y")
    state.update_notifications = choice.lower() != "n"
    _ok(f"Update notifications: {'on' if state.update_notifications else 'off'}")
    mark_step_done(state, 6)


async def step_7_deploy(state: WizardState) -> None:
    if is_step_done(state, 7):
        _ok(f"Step 7 done (deploy: {state.deploy_mode})")
        return
    _hdr(7, "Deploy Mode")
    print("  1. foreground  — run in terminal (Ctrl-C to stop)")
    print("  2. systemd     — user service, auto-restart, survives logout")
    print("  3. docker      — docker compose (requires Docker)")
    choice = _prompt("Choose", "1")
    if choice == "2":
        state.deploy_mode = "systemd"
    elif choice == "3":
        state.deploy_mode = "docker"
    else:
        state.deploy_mode = "foreground"
    _ok(f"Deploy mode: {state.deploy_mode}")
    mark_step_done(state, 7)
```

- [ ] **Step 4: Run all wizard tests**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_wizard.py -v
```
Expected: ~29 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/wizard.py tests/setup/test_wizard.py && git commit -m "feat: add wizard steps 4-7 (CLI, search, updates, deploy)"
```

---

### Task 7: Step 8, Orchestrator, Entry Point

**Files:**
- Modify: `src/setup/wizard.py` (add step_8_launch + run_wizard)
- Create: `setup.py`
- Modify: `tests/setup/test_wizard.py` (add orchestrator tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/setup/test_wizard.py`:
```python
# ── run_wizard orchestrator ──────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_resumes_skipping_completed_steps(tmp_path):
    from src.setup.state import save_state
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7],
        channel="telegram",
        telegram_token="tok",
        allowed_user_ids=[123],
        selected_clis=["claude"],
        search_mode="fts5",
        update_notifications=True,
        deploy_mode="foreground",
    )
    state_path = str(tmp_path / "state.json")
    save_state(state, state_path)
    with patch("src.setup.wizard.step_8_launch", new_callable=AsyncMock) as mock_launch:
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))
    mock_launch.assert_called_once()


@pytest.mark.asyncio
async def test_run_wizard_reset_clears_state(tmp_path):
    from src.setup.state import save_state
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6, 7],
                        channel="telegram", telegram_token="tok",
                        allowed_user_ids=[1], selected_clis=["claude"],
                        search_mode="fts5", update_notifications=True,
                        deploy_mode="foreground")
    state_path = str(tmp_path / "state.json")
    save_state(state, state_path)
    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as mock_s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None), \
         patch("src.setup.wizard.step_6_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, reset=True, cwd=str(tmp_path))
    # step_1 must be called because state was reset (steps re-run)
    mock_s1.assert_called_once()


# ── step_8_launch ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step8_writes_config_and_env(tmp_path):
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7],
        channel="telegram", telegram_token="TOK",
        allowed_user_ids=[111], selected_clis=["claude"],
        search_mode="fts5", update_notifications=True,
        deploy_mode="foreground",
    )
    with patch("src.setup.wizard.write_config_toml") as mock_cfg, \
         patch("src.setup.wizard.write_env_file") as mock_env, \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("os.execv"):
        await wizard.step_8_launch(state, str(tmp_path), [])
    mock_cfg.assert_called_once()
    mock_env.assert_called_once()
    _, env_kwargs = mock_env.call_args
    # env_file content passed as second positional arg
    env_arg = mock_env.call_args[0][1]
    assert env_arg.get("TELEGRAM_BOT_TOKEN") == "TOK"
    assert env_arg.get("ALLOWED_USER_IDS") == "111"


@pytest.mark.asyncio
async def test_step8_systemd_calls_systemctl(tmp_path):
    state = WizardState(
        completed_steps=list(range(1, 8)),
        channel="telegram", telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="systemd",
    )
    with patch("src.setup.wizard.write_config_toml"), \
         patch("src.setup.wizard.write_env_file"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_systemd_unit") as mock_unit, \
         patch("subprocess.run") as mock_run:
        await wizard.step_8_launch(state, str(tmp_path), [])
    mock_unit.assert_called_once()
    assert mock_run.call_count >= 1


@pytest.mark.asyncio
async def test_step8_docker_calls_compose(tmp_path):
    state = WizardState(
        completed_steps=list(range(1, 8)),
        channel="telegram", telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="docker",
    )
    with patch("src.setup.wizard.write_config_toml"), \
         patch("src.setup.wizard.write_env_file"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_docker_compose") as mock_dc, \
         patch("subprocess.run") as mock_run:
        await wizard.step_8_launch(state, str(tmp_path), [])
    mock_dc.assert_called_once()
    mock_run.assert_called_once()
```

- [ ] **Step 2: Run tests to verify new tests fail**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/test_wizard.py::test_run_wizard_resumes_skipping_completed_steps -v 2>&1 | tail -5
```
Expected: FAILED — `run_wizard` not defined

- [ ] **Step 3: Add `step_8_launch` and `run_wizard` to `src/setup/wizard.py`**

Add these imports to `src/setup/wizard.py` (after existing imports):
```python
import os
import subprocess

from src.setup.deploy import (
    write_config_toml, write_env_file, write_systemd_unit,
    write_docker_compose, create_data_dirs,
)
from src.setup.state import load_state, save_state, reset_state
```

Then append:
```python
async def step_8_launch(
    state: WizardState,
    cwd: str,
    bg_tasks: list[asyncio.Task],
) -> None:
    _hdr(8, "Writing config and launching")
    if bg_tasks:
        print("  Waiting for background installs to complete...")
        results = await asyncio.gather(*bg_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                _warn(f"Background install error: {r}")
    create_data_dirs(cwd)
    runners = state.selected_clis or ["claude"]
    write_config_toml(
        os.path.join(cwd, "config", "config.toml"),
        {"default_runner": runners[0], "runners": runners},
    )
    env: dict[str, str] = {}
    if state.telegram_token:
        env["TELEGRAM_BOT_TOKEN"] = state.telegram_token
    if state.discord_token:
        env["DISCORD_BOT_TOKEN"] = state.discord_token
    if state.allowed_user_ids:
        env["ALLOWED_USER_IDS"] = ",".join(str(i) for i in state.allowed_user_ids)
    env["DEFAULT_CWD"] = cwd
    write_env_file(os.path.join(cwd, "secrets", ".env"), env)
    if state.deploy_mode == "systemd":
        write_systemd_unit(cwd)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "gateway-agent"], check=False
        )
        _ok("Systemd service started: gateway-agent")
    elif state.deploy_mode == "docker":
        write_docker_compose(cwd)
        subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=False)
        _ok("Docker container started")
    else:
        python = os.path.join(cwd, "venv", "bin", "python3")
        if not os.path.exists(python):
            python = "python3"
        _ok("Launching bot...")
        os.execv(python, [python, os.path.join(cwd, "main.py")])
    mark_step_done(state, 8)


async def run_wizard(
    state_path: str = "data/setup-state.json",
    reset: bool = False,
    cwd: str = ".",
) -> None:
    cwd = os.path.abspath(cwd)
    if reset:
        reset_state(state_path)
        print("State reset. Starting fresh.\n")
    state = load_state(state_path)
    print(f"\n{'='*52}")
    print("  Gateway Agent Platform — Setup Wizard")
    print(f"{'='*52}\n")
    bg_tasks: list[asyncio.Task] = []

    await step_1_channel(state)
    save_state(state, state_path)
    await step_2_token(state)
    save_state(state, state_path)
    await step_3_allowlist(state)
    save_state(state, state_path)
    cli_tasks = await step_4_clis(state)
    bg_tasks.extend(cli_tasks)
    save_state(state, state_path)
    ollama_task = await step_5_search(state)
    if ollama_task:
        bg_tasks.append(ollama_task)
    save_state(state, state_path)
    await step_6_updates(state)
    save_state(state, state_path)
    await step_7_deploy(state)
    save_state(state, state_path)
    await step_8_launch(state, cwd, bg_tasks)
    save_state(state, state_path)
```

- [ ] **Step 4: Create `setup.py`**

```python
#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.setup.wizard import run_wizard


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gateway Agent Platform — interactive setup wizard"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear saved progress and restart from step 1"
    )
    parser.add_argument(
        "--cwd", default=".",
        help="Project root directory (default: current directory)"
    )
    args = parser.parse_args()
    asyncio.run(run_wizard(reset=args.reset, cwd=args.cwd))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all wizard tests**

```bash
cd /tmp/telegram-to-control && python -m pytest tests/setup/ -v
```
Expected: All tests PASS (35+ tests)

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
cd /tmp/telegram-to-control && python -m pytest --tb=short -q
```
Expected: All previously passing tests still pass

- [ ] **Step 7: Commit**

```bash
cd /tmp/telegram-to-control && git add src/setup/wizard.py setup.py tests/setup/test_wizard.py && git commit -m "feat: add wizard step 8, orchestrator, and setup.py entry point"
```

---

## Self-Review

| Spec requirement | Covered by |
|-----------------|-----------|
| setup.py entry point | Task 7 |
| State persistence (data/setup-state.json) | Task 1 |
| Resume from last completed step | Task 7: run_wizard loads state |
| --reset flag | Task 7: run_wizard + setup.py |
| Step 1: channel selection | Task 5 |
| Step 2: token validation with retry | Task 2 + Task 5 |
| Step 3: auto-capture user ID, 30s timeout | Task 5: _capture_telegram_user_id |
| Step 4: CLI detect + background install | Task 3 + Task 6 |
| Step 5: FTS5 or embedding + Ollama | Task 3 + Task 6 |
| Step 6: update notification toggle | Task 6 |
| Step 7: foreground/systemd/docker | Task 4 + Task 6 |
| Step 8: write files + launch | Task 4 + Task 7 |
| No new deps | Confirmed: only stdlib + existing requirements |
| data/memory + data/db never cleared | create_data_dirs only uses mkdir |
| Background progress every 30s | installer.progress_reporter |
