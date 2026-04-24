from pathlib import Path


_RUNNER_CONFIGS: dict[str, str] = {
    "claude": (
        '[runners.claude]\npath = "claude"\n'
        'args = []\n'
        "timeout_seconds = 300\ncontext_token_budget = 4000"
    ),
    "codex": (
        '[runners.codex]\npath = "codex"\n'
        'args = []\n'
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
update_notifications = {update_notifications}

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
search_mode = "{search_mode}"

[modules]
dir = "modules"

[discord]
allow_bot_messages = "off"
allow_user_messages = "all"
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
    default_runner = config.get("default_runner", "claude")
    if default_runner not in _RUNNER_CONFIGS:
        raise ValueError(f"Unknown runner: {default_runner!r}. Must be one of {list(_RUNNER_CONFIGS)}")
    content = _TOML_TEMPLATE.format(
        default_runner=default_runner,
        runner_sections=sections,
        search_mode=config.get("search_mode", "fts5"),
        update_notifications="true" if config.get("update_notifications", True) else "false",
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def write_env_file(path: str, env: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '{k}="{v}"'.format(
            k=k,
            v=str(v).replace(chr(10), "").replace(chr(13), "").replace('"', '\\"'),
        )
        for k, v in env.items()
    ]
    content = "\n".join(lines) + "\n" if lines else ""
    p.write_text(content)
    p.chmod(0o600)


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
