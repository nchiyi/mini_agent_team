from pathlib import Path


_RUNNER_CONFIGS: dict[str, str] = {
    # `path` MUST point at the ACP-speaking binary, not the bare CLI:
    # - claude / codex have wrapper packages (claude-agent-acp / codex-acp)
    #   that translate stdio JSON-RPC for the host CLI.
    # - gemini speaks ACP natively when invoked with --acp --yolo.
    # Spawning the bare `claude` or `codex` here would hang the bot at
    # JSON-RPC handshake (the typing indicator shows but no reply ever).
    "claude": (
        '[runners.claude]\ntype = "acp"\npath = "claude-agent-acp"\n'
        'args = []\n'
        'timeout_seconds = 300\ncontext_token_budget = 4000'
    ),
    "codex": (
        '[runners.codex]\ntype = "acp"\npath = "codex-acp"\n'
        'args = []\n'
        'timeout_seconds = 300\ncontext_token_budget = 4000'
    ),
    "gemini": (
        '[runners.gemini]\ntype = "acp"\npath = "gemini"\n'
        'args = ["--acp", "--yolo"]\n'
        'timeout_seconds = 300\ncontext_token_budget = 4000'
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
    "# Install Node.js 20 (NodeSource) + curl + ca-certificates + tini so we can\n"
    "# `npm install -g` the user-selected agent CLIs (claude/codex/gemini)\n"
    "# inside the container — without this, the bot calls subprocess('claude')\n"
    "# and gets FileNotFoundError because the host's CLIs aren't visible here.\n"
    "# tini is for proper PID 1 signal handling (graceful Ctrl-C).\n"
    "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
    "        curl ca-certificates gnupg tini \\\n"
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
    "# Without CLAUDE_CODE_EXECUTABLE, claude-agent-acp uses its own bundled\n"
    "# SDK cli.js (a separate Anthropic upstream issue, openab #418) and\n"
    "# silently ignores the globally-installed `claude` binary — leading to\n"
    "# 'Authentication required' even when /root/.claude is fully populated.\n"
    "# Force the adapter to use our installed claude binary.\n"
    "ENV CLAUDE_CODE_EXECUTABLE=/usr/local/bin/claude\n"
    "\n"
    "COPY . .\n"
    'ENTRYPOINT ["/usr/bin/tini", "--"]\n'
    'CMD ["python", "main.py"]\n'
)


def _build_compose_yaml(oauth_mounts: list[str] | None = None) -> str:
    """Build docker-compose.yml.

    `oauth_mounts` is kept for backwards-compat but no longer used in the
    primary path: bind-mounting the host's `~/.claude` etc. doesn't work on
    macOS (Claude Code stores credentials in the macOS Keychain, not as a
    file). See docs/openab-research.md.

    Replacement: a Docker named volume `mat-agent-home` is mounted at /root
    inside the container. The user runs `mat auth <cli>` once after install
    to do device-flow OAuth inside the container; tokens persist in the
    volume across container restarts and image rebuilds.
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
        # Persistent agent home — holds .claude/.codex/.gemini OAuth state.
        # Named volume (not bind mount) so credentials live in Docker-managed
        # storage, separate from host's ~/.claude (which on macOS is just
        # Keychain pointers and doesn't help the container anyway).
        "      - mat-agent-home:/root",
    ]
    # Legacy path: if explicit oauth_mounts are passed (e.g. user-edited
    # docker-compose.yml on Linux where files are usable), still honour them.
    for m in (oauth_mounts or []):
        lines.append(f"      - {m}")
    lines.extend([
        "    environment:",
        "      - PYTHONUNBUFFERED=1",
        "      - HOME=/root",
        "",
        "volumes:",
        "  mat-agent-home:",
        "",
    ])
    return "\n".join(lines)


# Backwards-compat: callers that import _DOCKER_COMPOSE still work (defaults
# to no OAuth mounts).
_DOCKER_COMPOSE = _build_compose_yaml()


def _render_bots_sections(bots: list[dict]) -> str:
    """Render each bot dict as a [bots.<id>] TOML block. Skip fields whose value
    is empty/None so we don't emit ``default_runner = ""`` cruft."""
    blocks: list[str] = []
    for bot in bots:
        bid = bot.get("id")
        if not bid:
            continue
        lines: list[str] = [f"[bots.{bid}]"]
        for field in ("channel", "token_env", "default_runner", "default_role", "label"):
            val = bot.get(field)
            if val:
                lines.append(f'{field} = "{val}"')
        # Future B-2 fields go here, all opt-in / skip-if-default.
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def write_config_toml(path: str, config: dict) -> None:
    runners = config.get("runners", [])
    sections = "\n\n".join(
        _RUNNER_CONFIGS[r] for r in runners if r in _RUNNER_CONFIGS
    )
    default_runner = config.get("default_runner", "claude")
    if default_runner not in _RUNNER_CONFIGS:
        raise ValueError(
            f"Unknown runner: {default_runner!r}. Must be one of {list(_RUNNER_CONFIGS)}"
        )
    content = _TOML_TEMPLATE.format(
        default_runner=default_runner,
        runner_sections=sections,
        search_mode=config.get("search_mode", "fts5"),
        update_notifications="true" if config.get("update_notifications", True) else "false",
    )
    bots = config.get("bots") or []
    if bots:
        content = content.rstrip() + "\n\n" + _render_bots_sections(bots) + "\n"
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
