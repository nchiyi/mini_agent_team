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
    "\n"
    "# Install Node.js 20 (NodeSource) + curl + ca-certificates so we can\n"
    "# `npm install -g` the user-selected agent CLIs (claude/codex/gemini/kiro)\n"
    "# inside the container — without this, the bot calls subprocess('claude')\n"
    "# and gets FileNotFoundError because the host's CLIs aren't visible here.\n"
    "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
    "        curl ca-certificates gnupg \\\n"
    "    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\\n"
    "    && apt-get install -y --no-install-recommends nodejs \\\n"
    "    && apt-get clean \\\n"
    "    && rm -rf /var/lib/apt/lists/*\n"
    "\n"
    "# Python deps (with optional extras for voice/browser/etc).\n"
    "COPY requirements.txt requirements.extra.txt ./\n"
    "RUN pip install --no-cache-dir -r requirements.txt && \\\n"
    "    if [ -s requirements.extra.txt ]; then pip install --no-cache-dir -r requirements.extra.txt; fi\n"
    "\n"
    "# Node CLIs — one package per line in requirements.npm.txt (written by\n"
    "# the wizard from state.selected_clis + ACP wrapper packages).\n"
    "COPY requirements.npm.txt ./\n"
    "RUN if [ -s requirements.npm.txt ]; then \\\n"
    "        xargs -a requirements.npm.txt -r npm install -g; \\\n"
    "    fi\n"
    "\n"
    "COPY . .\n"
    'CMD ["python", "main.py"]\n'
)


def _build_compose_yaml(oauth_mounts: list[str] | None = None) -> str:
    """Build docker-compose.yml with optional host-credential mounts.

    oauth_mounts is a list of strings of the form 'HOST_PATH:CONTAINER_PATH:ro'
    that gets injected into the volumes section so user-selected CLIs (claude,
    codex, gemini, ...) can use the host's already-authenticated credentials.
    """
    lines = [
        "services:",
        "  gateway:",
        "    build: .",
        "    restart: unless-stopped",
        "    volumes:",
        "      - ./config:/app/config:ro",
        "      - ./secrets:/app/secrets:ro",
        "      - ./data:/app/data",
    ]
    for m in (oauth_mounts or []):
        lines.append(f"      - {m}")
    lines.extend([
        "    environment:",
        "      - PYTHONUNBUFFERED=1",
        # Containerised CLIs read creds from $HOME — ensure it points at /root
        # where the OAuth mounts above land.
        "      - HOME=/root",
        "",
    ])
    return "\n".join(lines)


# Backwards-compat: callers that import _DOCKER_COMPOSE still work (defaults
# to no OAuth mounts).
_DOCKER_COMPOSE = _build_compose_yaml()


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


def write_docker_compose(cwd: str, oauth_mounts: list[str] | None = None) -> None:
    base = Path(cwd)
    dockerfile = base / "Dockerfile"
    # Always overwrite Dockerfile so changes to the template (Node install,
    # extra requirements files, etc.) propagate to existing installs after
    # `git pull` + re-run wizard.
    dockerfile.write_text(_DOCKERFILE)
    (base / "docker-compose.yml").write_text(_build_compose_yaml(oauth_mounts))


def create_data_dirs(base: str) -> None:
    for subdir in (
        "data/memory/hot",
        "data/memory/cold/permanent",
        "data/memory/cold/session",
        "data/db",
        "data/audit",
    ):
        (Path(base) / subdir).mkdir(parents=True, exist_ok=True)
