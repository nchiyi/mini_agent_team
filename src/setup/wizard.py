import asyncio
import os
import subprocess
import sys

from src.setup.state import WizardState, is_step_done, mark_step_done
from src.setup.state import load_state, save_state, reset_state
from src.setup.validator import validate_telegram_token, validate_discord_token
from src.setup.installer import is_cli_installed, install_cli, install_ollama, progress_reporter
from src.setup.deploy import (
    write_config_toml, write_env_file, write_systemd_unit,
    write_docker_compose, create_data_dirs,
)

_background_tasks: set[asyncio.Task] = set()

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"


def _hdr(n: int, title: str) -> None:
    print(f"\n{_B}[{n}/9] {title}{_X}")


def _ok(msg: str) -> None:
    print(f"{_G}✓ {msg}{_X}")


def _warn(msg: str) -> None:
    print(f"{_Y}⚠ {msg}{_X}")


def _err(msg: str) -> None:
    print(f"{_R}✗ {msg}{_X}")


def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    prompt_text = f"{msg}{suffix}: "
    try:
        if not sys.stdin.isatty():
            with open("/dev/tty", "r+") as _tty:
                _tty.write(prompt_text)
                _tty.flush()
                val = _tty.readline().rstrip("\n").strip()
        else:
            val = input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)
    return val or default


_ALL_CHANNELS = ["telegram", "discord"]


async def step_1_channel(state: WizardState) -> None:
    if is_step_done(state, 1):
        _ok(f"Step 1 done (channels: {', '.join(state.channels)})")
        return
    _hdr(1, "Channel Selection")
    selected: set[str] = set()

    while True:
        print("")
        for i, ch in enumerate(_ALL_CHANNELS, 1):
            mark = "x" if ch in selected else " "
            print(f"  [{mark}] {i}. {ch.capitalize()}")
        print("")
        raw = _prompt("Toggle channels (e.g. 1  or  1 2), Enter to confirm")
        if not raw:
            if not selected:
                _err("Select at least one channel.")
                continue
            break
        for token in raw.split():
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(_ALL_CHANNELS):
                    ch = _ALL_CHANNELS[idx]
                    if ch in selected:
                        selected.discard(ch)
                    else:
                        selected.add(ch)
                else:
                    _err(f"Invalid option: {token}")
            else:
                _err(f"Invalid input: {token!r}")

    state.channels = [ch for ch in _ALL_CHANNELS if ch in selected]
    _ok(f"Channels: {', '.join(state.channels)}")
    mark_step_done(state, 1)


async def step_2_token(state: WizardState) -> None:
    if is_step_done(state, 2):
        _ok("Step 2 done (tokens validated)")
        return
    _hdr(2, "Bot Token")
    if "telegram" in state.channels:
        _attempts = 0
        while True:
            hint = "  (type 's' to skip validation)" if _attempts >= 1 else ""
            token = _prompt(f"Telegram bot token{hint}")
            if not token:
                _err("Token required")
                continue
            if token.lower() == "s":
                token = _prompt("Telegram bot token (saved without validation)")
                if token:
                    state.telegram_token = token
                    _warn("Validation skipped — token saved as-is")
                break
            print("  Validating...")
            result = validate_telegram_token(token)
            if result.skipped:
                state.telegram_token = token
                _warn(f"Validation skipped ({result.reason}) — token saved as-is")
                break
            if result.valid:
                state.telegram_token = token
                _ok("Telegram token valid")
                break
            _attempts += 1
            _err("Invalid token. Try again.")
    if "discord" in state.channels:
        _attempts = 0
        while True:
            hint = "  (type 's' to skip validation)" if _attempts >= 1 else ""
            token = _prompt(f"Discord bot token{hint}")
            if not token:
                _err("Token required")
                continue
            if token.lower() == "s":
                token = _prompt("Discord bot token (saved without validation)")
                if token:
                    state.discord_token = token
                    _warn("Validation skipped — token saved as-is")
                break
            print("  Validating...")
            result = validate_discord_token(token)
            if result.skipped:
                state.discord_token = token
                _warn(f"Validation skipped ({result.reason}) — token saved as-is")
                break
            if result.valid:
                state.discord_token = token
                _ok("Discord token valid")
                break
            _attempts += 1
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
    print("  (Press Ctrl-C to skip and enter your ID manually)")
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
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for _cleanup in (app.updater.stop, app.stop, app.shutdown):
            try:
                await _cleanup()
            except Exception:
                pass
    return captured[0] if captured else None


async def step_3_allowlist(state: WizardState) -> None:
    if is_step_done(state, 3):
        _ok(f"Step 3 done (user IDs: {state.allowed_user_ids})")
        return
    _hdr(3, "Allowlist — Authorised User IDs")
    if "telegram" in state.channels and state.telegram_token:
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
        _warn("No user IDs set — bot will be LOCKED (no one can use it). Re-run step 3 to add a user ID.")
    mark_step_done(state, 3)


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
    tokens = [c.strip() for c in raw.split(",") if c.strip()]
    selected = [c for c in tokens if c in _ALL_CLIS]
    invalid = [c for c in tokens if c not in _ALL_CLIS]
    if invalid:
        _warn(f"Unrecognised CLIs ignored: {invalid}")
    if not selected:
        selected = ["claude"]
        _ok("Defaulting to claude")
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
        _t = asyncio.create_task(progress_reporter(bg_tasks, task_names))
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)
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
        _t = asyncio.create_task(progress_reporter([t], ["ollama"]))
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)
        _ok("Installing Ollama in background...")
        mark_step_done(state, 5)
        return t
    state.search_mode = "fts5"
    _ok("Search mode: FTS5")
    mark_step_done(state, 5)
    return None


_OPTIONAL_GROUPS: list[tuple[str, str, list[str]]] = [
    ("discord_voice", "Discord 語音頻道  (PyNaCl)",             ["PyNaCl"]),
    ("voice",         "語音輸入/輸出 STT/TTS  (groq, edge-tts)", ["groq", "edge-tts"]),
    ("browser",       "瀏覽器技能  (playwright, html2text)",     ["playwright", "html2text"]),
    ("tavily",        "Tavily 高級搜尋  (tavily-python)",        ["tavily-python"]),
]


def _pkg_installed(pkg: str) -> bool:
    import importlib.util
    name = pkg.split("[")[0].replace("-", "_").lower()
    return importlib.util.find_spec(name) is not None


async def _pip_install(packages: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "--quiet", *packages,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        _warn(f"pip install failed: {stderr.decode(errors='replace').strip()}")
        return False
    return True


async def step_6_optional(state: WizardState) -> None:
    if is_step_done(state, 6):
        _ok(f"Step 6 done (optional: {state.optional_packages or 'none'})")
        return
    _hdr(6, "Optional Features")
    selected: set[str] = set()

    while True:
        print("")
        for i, (key, label, pkgs) in enumerate(_OPTIONAL_GROUPS, 1):
            mark = "x" if key in selected else " "
            status = _G + "installed" + _X if all(_pkg_installed(p) for p in pkgs) else _Y + "not installed" + _X
            print(f"  [{mark}] {i}. {label}  — {status}")
        print("")
        raw = _prompt("Toggle options (e.g. 1 2), Enter to confirm (skip = none)")
        if not raw:
            break
        for token in raw.split():
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(_OPTIONAL_GROUPS):
                    key = _OPTIONAL_GROUPS[idx][0]
                    if key in selected:
                        selected.discard(key)
                    else:
                        selected.add(key)
                else:
                    _err(f"Invalid option: {token}")

    to_install: list[str] = []
    for key, _, pkgs in _OPTIONAL_GROUPS:
        if key in selected:
            for p in pkgs:
                if not _pkg_installed(p):
                    to_install.append(p)
    state.optional_packages = list(selected)

    if to_install:
        print(f"  Installing: {', '.join(to_install)}")
        ok = await _pip_install(to_install)
        if ok:
            _ok(f"Installed: {', '.join(to_install)}")
        # post-install: playwright needs browser download
        if "browser" in selected and "playwright" in to_install:
            print("  Downloading Playwright browsers (chromium)...")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
    elif selected:
        _ok("All selected packages already installed")
    else:
        _ok("No optional packages selected")

    mark_step_done(state, 6)


async def step_7_updates(state: WizardState) -> None:
    if is_step_done(state, 7):
        _ok(f"Step 7 done (update notifications: {state.update_notifications})")
        return
    _hdr(7, "Update Notifications")
    print("  Check for new GitHub releases on startup and print a notice.")
    print("  (Never auto-updates — you control when to update.)")
    choice = _prompt("Enable? (y/n)", "y")
    state.update_notifications = choice.lower() != "n"
    _ok(f"Update notifications: {'on' if state.update_notifications else 'off'}")
    mark_step_done(state, 7)


async def step_8_deploy(state: WizardState) -> None:
    if is_step_done(state, 8):
        _ok(f"Step 8 done (deploy: {state.deploy_mode})")
        return
    _hdr(8, "Deploy Mode")
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
    mark_step_done(state, 8)


def _print_completion_systemd(cwd: str) -> None:
    print(f"\n{_B}{'='*52}{_X}")
    print(f"{_G}{_B}  ✅  Setup complete — bot is running in background.{_X}")
    print(f"{_B}{'='*52}{_X}")
    print(f"  {_B}Manage:{_X}")
    print("    systemctl --user status  gateway-agent   # status")
    print("    systemctl --user stop    gateway-agent   # stop")
    print("    systemctl --user restart gateway-agent   # restart")
    print("    journalctl --user -u gateway-agent -f    # live logs")
    print(f"  {_B}Uninstall:{_X}")
    print(f"    bash {cwd}/uninstall.sh")
    print(f"{_B}{'='*52}{_X}\n")


def _print_completion_docker(cwd: str) -> None:
    print(f"\n{_B}{'='*52}{_X}")
    print(f"{_G}{_B}  ✅  Setup complete — bot is running in Docker.{_X}")
    print(f"{_B}{'='*52}{_X}")
    print(f"  {_B}Manage:{_X}")
    print(f"    docker compose -f {cwd}/docker-compose.yml ps       # status")
    print(f"    docker compose -f {cwd}/docker-compose.yml logs -f  # live logs")
    print(f"    docker compose -f {cwd}/docker-compose.yml down     # stop")
    print(f"  {_B}Uninstall:{_X}")
    print(f"    bash {cwd}/uninstall.sh")
    print(f"{_B}{'='*52}{_X}\n")


async def step_9_launch(
    state: WizardState,
    cwd: str,
    bg_tasks: list[asyncio.Task],
) -> None:
    if is_step_done(state, 9):
        _ok("Already configured — skipping launch step.")
        return
    _hdr(9, "Writing config and launching")
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
        {
            "default_runner": runners[0],
            "runners": runners,
            "search_mode": state.search_mode,
            "update_notifications": state.update_notifications,
        },
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
    mark_step_done(state, 9)
    if state.deploy_mode == "systemd":
        write_systemd_unit(cwd)
        r1 = subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        r2 = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "gateway-agent"], check=False
        )
        if r1.returncode != 0 or r2.returncode != 0:
            _warn("systemctl returned non-zero — check service status manually")
        else:
            _ok("Systemd service started: gateway-agent")
        _print_completion_systemd(cwd)
    elif state.deploy_mode == "docker":
        write_docker_compose(cwd)
        r = subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=False)
        if r.returncode != 0:
            _warn("docker compose returned non-zero — check container status manually")
        else:
            _ok("Docker container started")
        _print_completion_docker(cwd)
    else:
        python = os.path.join(cwd, "venv", "bin", "python3")
        if not os.path.exists(python):
            _warn("venv python not found, falling back to system python3")
            python = "python3"
        save_state(state, os.path.join(cwd, "data", "setup-state.json"))
        print(f"\n{_B}{'='*52}{_X}")
        print(f"{_G}{_B}  Bot is starting — this terminal is now the bot.{_X}")
        print(f"  Press Ctrl-C to stop.")
        print(f"{_B}{'='*52}{_X}\n")
        os.execv(python, [python, os.path.join(cwd, "main.py")])


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
    await step_6_optional(state)
    save_state(state, state_path)
    await step_7_updates(state)
    save_state(state, state_path)
    await step_8_deploy(state)
    save_state(state, state_path)
    await step_9_launch(state, cwd, bg_tasks)


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Gateway Agent setup wizard")
    _ap.add_argument("--reset", action="store_true", help="Wipe saved state and start from step 1")
    _args = _ap.parse_args()
    asyncio.run(run_wizard(cwd=os.path.abspath("."), reset=_args.reset))
