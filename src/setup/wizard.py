import asyncio
import os
import subprocess
import sys

from src.setup.state import WizardState, is_step_done, mark_step_done
from src.setup.state import load_state, save_state, reset_state, detect_mode
from src.setup.state import is_micro_step_done, mark_micro_step_done
from src.setup.validator import validate_telegram_token, validate_discord_token
from src.setup.installer import (
    is_cli_installed, install_cli, install_cli_foreground,
    install_ollama, install_ollama_foreground, progress_reporter,
    _CLI_SIZES,
    ACP_PACKAGES, is_acp_installed, install_acp_foreground, is_npm_available,
)
from src.setup.deploy import (
    write_config_toml, write_env_file, write_systemd_unit,
    write_docker_compose, create_data_dirs,
    _TOML_TEMPLATE, _RUNNER_CONFIGS,
)
from src.setup.config_writer import write_config_with_diff, write_env_with_diff
from src.setup.preflight import run_preflight
from src.setup.smoke_test import run_smoke_test

_background_tasks: set[asyncio.Task] = set()

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"


def _hdr(n, title: str) -> None:
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

    # Print token acquisition guide for selected channels only
    print("\n  How to get your tokens:")
    if "telegram" in state.channels:
        print("  • Telegram: message @BotFather → /newbot → copy the token")
        print("    https://t.me/BotFather")
    if "discord" in state.channels:
        print("  • Discord: https://discord.com/developers/applications")
        print("    → New Application → Bot → Reset Token → copy token")
        print("    Enable: Message Content Intent + Server Members Intent")

    mark_step_done(state, 1)


def _error_message_telegram(result) -> str:
    """Return a descriptive error message based on error_category."""
    if result.error_category == "auth":
        return "Auth error: token rejected by Telegram. Re-create via @BotFather."
    if result.error_category == "rate_limit":
        return "Rate-limited — wait 30s and try again."
    if result.error_category == "network":
        return "Network error — check internet connection and retry."
    return "Invalid token. Try again."


def _error_message_discord(result) -> str:
    """Return a descriptive error message based on error_category."""
    if result.error_category == "auth":
        return "Auth error: token rejected by Discord. Re-create via the Developer Portal."
    if result.error_category == "rate_limit":
        return "Rate-limited — wait 30s and try again."
    if result.error_category == "network":
        return "Network error — check internet connection and retry."
    return "Invalid token. Try again."


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
                name_part = f"@{result.bot_username}" if result.bot_username else "(username unknown)"
                id_part = f" (id: {result.bot_id})" if result.bot_id else ""
                _ok(f"Telegram token valid — {name_part}{id_part}")
                confirm = _prompt("Is this your bot? (y/n)", "y")
                if confirm.lower() == "n":
                    state.telegram_token = None
                    _err("Token rejected. Please enter a different token.")
                    _attempts += 1
                    continue
                break
            _attempts += 1
            _err(_error_message_telegram(result))
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
                name_part = f"@{result.bot_username}" if result.bot_username else "(username unknown)"
                id_part = f" (id: {result.bot_id})" if result.bot_id else ""
                _ok(f"Discord token valid — {name_part}{id_part}")
                confirm = _prompt("Is this your bot? (y/n)", "y")
                if confirm.lower() == "n":
                    state.discord_token = None
                    _err("Token rejected. Please enter a different token.")
                    _attempts += 1
                    continue
                break
            _attempts += 1
            _err(_error_message_discord(result))
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


async def _capture_discord_user_id(token: str, timeout: int = 30) -> int | None:
    """Listen for the first Discord message to auto-capture the sender's user ID.

    Mirrors the logic of `_capture_telegram_user_id`.  Returns the integer
    user ID on success, or None on timeout / import error.
    """
    try:
        import discord
    except ImportError:
        return None

    captured: list[int] = []
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message: discord.Message) -> None:  # type: ignore[override]
        if not message.author.bot:
            captured.append(message.author.id)

    print(f"  Send any message to your Discord bot now (waiting {timeout}s)...")
    print("  (Press Ctrl-C to skip and enter your ID manually)")

    runner_task = asyncio.create_task(client.start(token))
    try:
        for _ in range(timeout):
            await asyncio.sleep(1)
            if captured:
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        runner_task.cancel()
        try:
            await client.close()
        except Exception:
            pass
        try:
            await runner_task
        except (asyncio.CancelledError, Exception):
            pass

    return captured[0] if captured else None


async def step_3_allowlist(state: WizardState) -> None:
    if is_step_done(state, 3):
        _ok(f"Step 3 done (user IDs: {state.allowed_user_ids})")
        return

    while True:
        _hdr(3, "Allowlist — Authorised User IDs")
        collected: list[int] = list(state.allowed_user_ids)

        # ── Telegram auto-capture ─────────────────────────────────────────────
        if "telegram" in state.channels and state.telegram_token:
            uid = await _capture_telegram_user_id(state.telegram_token)
            if uid:
                confirm = _prompt(f"  Captured: {uid} — Is this you? (y/n)", "y")
                if confirm.lower() != "n":
                    if uid not in collected:
                        collected.append(uid)
                    _ok(f"Telegram user ID confirmed: {uid}")
                else:
                    raw = _prompt("Enter your Telegram user ID manually")
                    if raw.isdigit():
                        collected.append(int(raw))
            else:
                raw = _prompt("Enter your Telegram user ID manually")
                if raw.isdigit():
                    collected.append(int(raw))

        # ── Discord auto-capture ──────────────────────────────────────────────
        if "discord" in state.channels and state.discord_token:
            uid = await _capture_discord_user_id(state.discord_token)
            if uid:
                confirm = _prompt(f"  Captured: {uid} — Is this you? (y/n)", "y")
                if confirm.lower() != "n":
                    if uid not in collected:
                        collected.append(uid)
                    _ok(f"Discord user ID confirmed: {uid}")
                else:
                    raw = _prompt("Enter your Discord user ID manually")
                    if raw.isdigit():
                        collected.append(int(raw))
            else:
                raw = _prompt("Enter your Discord user ID manually")
                if raw.isdigit():
                    collected.append(int(raw))

        # ── Fallback: neither channel has a token (shouldn't happen normally) ─
        if not state.channels or (
            "telegram" not in state.channels and "discord" not in state.channels
        ):
            raw = _prompt("Enter your user ID")
            if raw.isdigit():
                collected.append(int(raw))

        state.allowed_user_ids = collected

        # ── Fail-loud if still empty ──────────────────────────────────────────
        if not state.allowed_user_ids:
            print(f"\n{_Y}⚠ No user IDs set.{_X}")
            print("  Bot will reject ALL requests unless you set allow_all_users=true.")
            allow_all = _prompt(
                "  Allow ALL users? This is dangerous in public servers. (y/n)", "n"
            )
            if allow_all.lower() == "y":
                state.data["allow_all_users"] = True
                _warn("All users allowed — make sure this is intentional.")
                break
            # User said no — loop back to the top of step 3
            _err("Re-starting step 3. Please provide at least one user ID.")
            continue

        break

    mark_step_done(state, 3)


_ALL_CLIS = ["claude", "codex", "gemini", "kiro"]


async def step_4_clis(state: WizardState) -> list[asyncio.Task]:
    if is_step_done(state, 4):
        _ok(f"Step 4 done (CLIs: {state.selected_clis})")
        return []
    _hdr(4, "CLI Tools")
    for cli in _ALL_CLIS:
        installed, version = is_cli_installed(cli)
        if installed:
            ver_str = f" ({version})" if version else ""
            print(f"  {cli}: installed{ver_str}")
        else:
            size_str = _CLI_SIZES.get(cli, "")
            size_part = f" ({size_str})" if size_str else ""
            print(f"  {cli}: not installed{size_part}")
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
    for cli in selected:
        installed, _ = is_cli_installed(cli)
        if not installed:
            size_str = _CLI_SIZES.get(cli, "")
            size_hint = f" ({size_str})" if size_str else ""
            print(f"  Installing {cli}{size_hint}... (this may take 1-2 min)")
            success = await install_cli_foreground(cli)
            if not success:
                _err(f"Failed to install {cli}. Fix the error above and re-run setup.")
                sys.exit(1)
            _ok(f"{cli} installed")
    mark_step_done(state, 4)
    return []


async def step_4_5_acp(state: WizardState) -> None:
    if is_micro_step_done(state, "acp_setup.done"):
        _ok(f"Step 4.5 done (mode: {state.acp_mode})")
        return

    _hdr("4.5", "AI 協作模式")

    cli_list = ", ".join(state.selected_clis) if state.selected_clis else "（未選擇）"
    print(f"\n你已選擇的 AI 工具：{cli_list}\n")
    print("這些 AI 你希望怎麼合作？\n")
    print("  [1] 讓 Claude 自己決定怎麼協調")
    print("      你直接對 Claude 說「請同時問 Codex 和 Gemini 的意見」，")
    print("      Claude 自己去呼叫它們、整合結果，再統一回答你。")
    print("      → 只需要安裝 1 個套件\n")
    print("  [2] 用指令讓 AI 輪流發言")
    print("      輸入 /discuss 或 /debate，")
    print("      bot 會依照你設定的順序讓每個 AI 依序發言，最後彙整。")
    print("      → 每個 AI 各需要 1 個套件\n")
    print("  [3] 兩種都要\n")

    raw = _prompt("選擇", "1").strip()
    primary = state.selected_clis[0] if state.selected_clis else ""

    if raw == "1":
        state.acp_mode = "orchestrator"
        targets = [primary] if primary in ACP_PACKAGES else []
    elif raw == "2":
        state.acp_mode = "gateway"
        targets = [c for c in state.selected_clis if c in ACP_PACKAGES]
    else:
        state.acp_mode = "both"
        targets = [c for c in state.selected_clis if c in ACP_PACKAGES]

    if not targets:
        _ok(f"{primary} 原生支援 ACP，無需額外安裝")
        state.installed_acp = []
        mark_micro_step_done(state, "acp_setup.done")
        return

    skipped: list[str] = []
    installed: list[str] = []
    print("")

    for cli in targets:
        npm_pkg, binary = ACP_PACKAGES[cli]
        already, _ = is_acp_installed(cli)
        if already:
            _ok(f"{binary} 已安裝")
            installed.append(binary)
            continue

        if not is_npm_available():
            _warn(f"npm 未找到，無法自動安裝 {binary}")
            print(f"    手動安裝：npm install -g {npm_pkg}")
            skipped.append(binary)
            continue

        ans = _prompt(f"安裝 {binary}？", "Y").strip().upper()
        if ans == "Y":
            print(f"  安裝 {npm_pkg}...")
            success = await install_acp_foreground(cli)
            if success:
                _ok(f"{binary} 安裝完成")
                installed.append(binary)
            else:
                _warn(f"{binary} 安裝失敗")
                print(f"    手動安裝：npm install -g {npm_pkg}")
                ans2 = _prompt("重試？", "N").strip().upper()
                if ans2 == "Y":
                    success2 = await install_acp_foreground(cli)
                    if success2:
                        _ok(f"{binary} 安裝完成")
                        installed.append(binary)
                    else:
                        _warn(f"{binary} 安裝再次失敗，跳過")
                        skipped.append(binary)
                else:
                    skipped.append(binary)
        else:
            print(f"    手動安裝：npm install -g {npm_pkg}")
            skipped.append(binary)

    state.installed_acp = installed
    mark_micro_step_done(state, "acp_setup.done")

    if skipped:
        _warn(f"跳過的 ACP 套件：{', '.join(skipped)}")
        _warn("若後續使用相關功能，請先手動安裝上述套件")


async def step_5_search(state: WizardState) -> asyncio.Task | None:
    if is_step_done(state, 5):
        _ok(f"Step 5 done (search: {state.search_mode})")
        return None
    _hdr(5, "Search Mode")
    print("  1. FTS5 keyword search (default, no extra install)")
    print("  2. FTS5 + embedding (Ollama ~500MB — foreground install)")
    choice = _prompt("Choose", "1")
    if choice == "2":
        state.search_mode = "fts5+embedding"
        print("  Installing Ollama (~500MB) — this will take a few minutes...")
        ok = await install_ollama_foreground()
        if not ok:
            _err("Ollama install failed. Fix above and re-run, or choose FTS5 only.")
            sys.exit(1)
        _ok("Ollama installed")
        mark_step_done(state, 5)
        return None
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


async def step_8_deploy(state: WizardState, cwd: str = ".") -> None:
    if is_step_done(state, 8):
        _ok(f"Step 8 done (deploy: {state.deploy_mode})")
        return
    _hdr(8, "Deploy Mode")
    print("  1. foreground  — run in terminal (Ctrl-C to stop)")
    print("  2. systemd     — user service, auto-restart, survives logout")
    print("  3. docker      — docker compose (requires Docker)")
    while True:
        choice = _prompt("Choose", "1")
        if choice == "2":
            # Pre-validate: systemd user session must be running
            r = subprocess.run(
                ["systemctl", "--user", "is-system-running"],
                capture_output=True, text=True,
            )
            if r.returncode not in (0, 1):  # 0=running, 1=degraded — both OK
                _err("systemd user session not running.")
                _err("Fix: loginctl enable-linger kiwi && systemctl --user start dbus.service")
                _err("Then re-run and choose systemd again.")
                continue
            state.deploy_mode = "systemd"
            break
        elif choice == "3":
            # Pre-validate: Docker daemon must be reachable
            r = subprocess.run(["docker", "info"], capture_output=True)
            if r.returncode != 0:
                _err("Docker daemon not running. Fix: sudo systemctl start docker")
                continue
            # Attempt a dry-run build to catch Dockerfile issues early (optional)
            r2 = subprocess.run(
                ["docker", "build", "--no-cache", "--dry-run", "."],
                capture_output=True,
                cwd=cwd,
            )
            if r2.returncode != 0:
                _warn("docker build --dry-run failed (may be unsupported by this Docker version) — continuing anyway")
            state.deploy_mode = "docker"
            break
        else:
            state.deploy_mode = "foreground"
            break
    _ok(f"Deploy mode: {state.deploy_mode}")
    mark_step_done(state, 8)


def _print_completion_systemd(cwd: str) -> None:
    W = 52
    print(f"\n{_B}{'='*W}{_X}")
    print(f"{_G}{_B}  ✅  Setup complete — bot is running!{_X}")
    print(f"{_B}{'='*W}{_X}")
    print(f"  {_B}Daily operations:{_X}")
    print("    systemctl --user status  gateway-agent   # status")
    print("    systemctl --user stop    gateway-agent   # stop")
    print("    systemctl --user restart gateway-agent   # restart")
    print("    journalctl --user -u gateway-agent -f    # live logs")
    print(f"    python -m src.setup.wizard --reset       # reconfigure")
    print(f"    bash {cwd}/uninstall.sh                  # uninstall")
    print(f"{_B}{'='*W}{_X}\n")


def _print_completion_docker(cwd: str) -> None:
    W = 52
    print(f"\n{_B}{'='*W}{_X}")
    print(f"{_G}{_B}  ✅  Setup complete — bot is running!{_X}")
    print(f"{_B}{'='*W}{_X}")
    print(f"  {_B}Daily operations:{_X}")
    print(f"    docker compose -f {cwd}/docker-compose.yml ps       # status")
    print(f"    docker compose -f {cwd}/docker-compose.yml logs -f  # live logs")
    print(f"    docker compose -f {cwd}/docker-compose.yml down     # stop")
    print(f"    python -m src.setup.wizard --reset                   # reconfigure")
    print(f"    bash {cwd}/uninstall.sh                              # uninstall")
    print(f"{_B}{'='*W}{_X}\n")


def _print_completion_foreground(cwd: str) -> None:
    W = 52
    print(f"\n{_B}{'='*W}{_X}")
    print(f"{_G}{_B}  ✅  Setup complete — bot is running!{_X}")
    print(f"{_B}{'='*W}{_X}")
    print(f"  {_B}Daily operations:{_X}")
    print("    python main.py                           # start (foreground)")
    print("    Ctrl-C                                   # stop")
    print("    python -m src.setup.wizard --reset       # reconfigure")
    print(f"    bash {cwd}/uninstall.sh                  # uninstall")
    print(f"{_B}{'='*W}{_X}\n")


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
    # Build config content using same template as deploy.py
    _runner_sections = "\n\n".join(
        _RUNNER_CONFIGS[r] for r in runners if r in _RUNNER_CONFIGS
    )
    _default_runner = runners[0]
    if _default_runner not in _RUNNER_CONFIGS:
        raise ValueError(f"Unknown runner: {_default_runner!r}")
    _config_content = _TOML_TEMPLATE.format(
        default_runner=_default_runner,
        runner_sections=_runner_sections,
        search_mode=state.search_mode or "fts5",
        update_notifications="true" if state.update_notifications else "false",
    )
    write_config_with_diff(
        os.path.join(cwd, "config", "config.toml"),
        _config_content,
        label="config.toml",
    )
    env: dict[str, str] = {}
    if state.telegram_token:
        env["TELEGRAM_BOT_TOKEN"] = state.telegram_token
    if state.discord_token:
        env["DISCORD_BOT_TOKEN"] = state.discord_token
    if state.allowed_user_ids:
        env["ALLOWED_USER_IDS"] = ",".join(str(i) for i in state.allowed_user_ids)
    if state.data.get("allow_all_users"):
        env["ALLOW_ALL_USERS"] = "true"
    env["DEFAULT_CWD"] = cwd
    _env_lines = [
        '{k}="{v}"'.format(
            k=k,
            v=str(v).replace(chr(10), "").replace(chr(13), "").replace('"', '\\"'),
        )
        for k, v in env.items()
    ]
    _env_content = "\n".join(_env_lines) + "\n" if _env_lines else ""
    write_env_with_diff(
        os.path.join(cwd, "secrets", ".env"),
        _env_content,
        label=".env",
    )
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
        print("  Running smoke test via journalctl…")
        journal_proc = await asyncio.create_subprocess_exec(
            "journalctl", "--user", "-u", "gateway-agent", "-f", "--lines=0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        ok = await run_smoke_test(state, journal_proc)
        journal_proc.terminate()
        if ok:
            _print_completion_systemd(cwd)
        else:
            _err("Smoke test failed — bot did not respond. Check logs above.")
            sys.exit(1)
    elif state.deploy_mode == "docker":
        write_docker_compose(cwd)
        r = subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=False)
        if r.returncode != 0:
            _warn("docker compose returned non-zero — check container status manually")
        else:
            _ok("Docker container started")
        print("  Running smoke test via docker logs…")
        docker_proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", os.path.join(cwd, "docker-compose.yml"),
            "logs", "-f", "--tail=0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        ok = await run_smoke_test(state, docker_proc)
        docker_proc.terminate()
        if ok:
            _print_completion_docker(cwd)
        else:
            _err("Smoke test failed — bot did not respond. Check logs above.")
            sys.exit(1)
    else:
        python = os.path.join(cwd, "venv", "bin", "python3")
        if not os.path.exists(python):
            _warn("venv python not found, falling back to system python3")
            python = "python3"
        save_state(state, os.path.join(cwd, "data", "setup-state.json"))
        print("  Starting bot…")
        proc = await asyncio.create_subprocess_exec(
            python, os.path.join(cwd, "main.py"),
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        ok = await run_smoke_test(state, proc)
        if ok:
            _print_completion_foreground(cwd)
            print("  Bot is running. Press Ctrl-C to stop.")
            try:
                async for line in proc.stdout:  # type: ignore[union-attr]
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
            except (KeyboardInterrupt, asyncio.CancelledError):
                proc.terminate()
        else:
            _err("Smoke test failed — bot did not respond. Check logs above.")
            proc.terminate()
            sys.exit(1)


def _print_banner(mode: str, current_step: str) -> None:
    """Print wizard banner with detected mode."""
    print(f"\n{_B}{'='*52}{_X}")
    print(f"{_B}  === MAT Setup Wizard ==={_X}")

    mode_upper = mode.upper()
    if mode == "resume" and current_step:
        print(f"  Mode: {_Y}{mode_upper}{_X} (interrupted at: {current_step})")
    elif mode == "launch":
        print(f"  Mode: {_G}{mode_upper}{_X} (already configured)")
    elif mode == "reset":
        print(f"  Mode: {_R}{mode_upper}{_X} (clearing saved state)")
    else:
        print(f"  Mode: {mode_upper}")

    print(f"{_B}{'='*52}{_X}\n")


async def run_wizard(
    state_path: str = "data/setup-state.json",
    reset: bool = False,
    cwd: str = ".",
) -> None:
    cwd = os.path.abspath(cwd)

    # ── Bootstrap: detect mode before loading state ─────────────────────────
    mode = detect_mode(state_path, reset=reset)

    if mode == "reset":
        reset_state(state_path)

    # Load state (load_state returns fresh WizardState if file is missing)
    state = load_state(state_path)
    state.mode = mode

    # Retrieve current_step for banner (may come from loaded state)
    current_step = state.current_step

    _print_banner(mode, current_step)

    # ── Mode branching ───────────────────────────────────────────────────────
    if mode == "launch":
        # Already fully configured — hand off to launch directly
        _ok("System already configured. Use --reset to reconfigure.")
        return

    # fresh / resume / reset all run the full wizard (steps skip if done)
    bg_tasks: list[asyncio.Task] = []

    await run_preflight(cwd)
    await step_1_channel(state)
    save_state(state, state_path)
    await step_2_token(state)
    save_state(state, state_path)
    await step_3_allowlist(state)
    save_state(state, state_path)
    cli_tasks = await step_4_clis(state)
    bg_tasks.extend(cli_tasks)
    save_state(state, state_path)
    await step_4_5_acp(state)
    save_state(state, state_path)
    ollama_task = await step_5_search(state)
    if ollama_task:
        bg_tasks.append(ollama_task)
    save_state(state, state_path)
    await step_6_optional(state)
    save_state(state, state_path)
    await step_7_updates(state)
    save_state(state, state_path)
    await step_8_deploy(state, cwd=cwd)
    save_state(state, state_path)
    await step_9_launch(state, cwd, bg_tasks)


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Gateway Agent setup wizard")
    _ap.add_argument("--reset", action="store_true", help="Wipe saved state and start from step 1")
    _args = _ap.parse_args()
    asyncio.run(run_wizard(cwd=os.path.abspath("."), reset=_args.reset))
