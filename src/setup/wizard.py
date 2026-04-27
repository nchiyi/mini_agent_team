import asyncio
import os
import subprocess
import sys

from src.setup.state import WizardState
from src.setup.state import load_state, save_state, reset_state, detect_mode
from src.setup.state import is_micro_step_done, mark_micro_step_done, set_current_step
from src.setup.validator import validate_telegram_token, validate_discord_token
from src.setup.installer import (
    is_cli_installed, install_cli_foreground,
    install_ollama_foreground, install_docker_foreground,
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

try:
    import questionary as _q
    _has_questionary = True
except ImportError:
    _q = None  # type: ignore[assignment]
    _has_questionary = False


async def _q_ask(question) -> object:
    # macOS kqueue cannot register stdin fd for EVENT_READ via asyncio
    # (OSError [Errno 22]).  Fix: run the prompt in a thread with a fresh
    # SelectorEventLoop backed by PollSelector (select.poll), which does
    # support watching stdin on macOS.  Thread-local set_event_loop is safe
    # here — it does not affect the outer loop running in the main thread.
    def _run():
        import selectors
        loop = asyncio.SelectorEventLoop(selectors.PollSelector())
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(question.unsafe_ask_async())
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    return await asyncio.to_thread(_run)


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
    if is_micro_step_done(state, "channel_select.done"):
        _ok(f"Step 1 done (channels: {', '.join(state.channels)})")
        return
    set_current_step(state, "channel_select.started")
    _hdr(1, "Channel Selection")
    selected: set[str] = set()

    if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
        while True:
            result = await _q_ask(_q.checkbox(
                "Select channels (Space to toggle, Enter to confirm):",
                choices=[_q.Choice(ch.capitalize(), value=ch) for ch in _ALL_CHANNELS],
            ))
            if result is None:
                print("\nSetup cancelled.")
                sys.exit(0)
            if not result:
                _err("Select at least one channel.")
                continue
            selected = set(result)
            break
    else:
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

    mark_micro_step_done(state, "channel_select.done")


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
    if is_micro_step_done(state, "token_validation.done"):
        _ok("Step 2 done (tokens validated)")
        return
    set_current_step(state, "token_validation.started")
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
                    state.telegram_token = ""
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
                    state.discord_token = ""
                    _err("Token rejected. Please enter a different token.")
                    _attempts += 1
                    continue
                break
            _attempts += 1
            _err(_error_message_discord(result))
    mark_micro_step_done(state, "token_validation.done")


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
    if is_micro_step_done(state, "allowlist.done"):
        _ok(f"Step 3 done (user IDs: {state.allowed_user_ids})")
        return
    set_current_step(state, "allowlist.started")
    _hdr(3, "Allowlist — Authorised User IDs")
    collected: list[int] = list(state.allowed_user_ids)

    # ── Telegram auto-capture ─────────────────────────────────────────────
    if "telegram" in state.channels and state.telegram_token:
        use_capture = _prompt("  Auto-capture your Telegram user ID? Send a message to your bot. (Y/n)", "y")
        if use_capture.lower() != "n":
            uid = await _capture_telegram_user_id(state.telegram_token)
            if uid:
                confirm = _prompt(f"  Captured: {uid} — Is this you? (y/n)", "y")
                if confirm.lower() != "n":
                    if uid not in collected:
                        collected.append(uid)
                    _ok(f"Telegram user ID confirmed: {uid}")
                else:
                    raw = _prompt("Enter your Telegram user ID manually (or Enter to skip)")
                    if raw.isdigit():
                        collected.append(int(raw))
            else:
                raw = _prompt("Enter your Telegram user ID manually (or Enter to skip)")
                if raw.isdigit():
                    collected.append(int(raw))
        else:
            raw = _prompt("Enter your Telegram user ID manually (or Enter to skip)")
            if raw.isdigit():
                collected.append(int(raw))

    # ── Discord auto-capture ──────────────────────────────────────────────
    if "discord" in state.channels and state.discord_token:
        use_capture = _prompt("  Auto-capture your Discord user ID? Send a message to your bot. (Y/n)", "y")
        if use_capture.lower() != "n":
            uid = await _capture_discord_user_id(state.discord_token)
            if uid:
                confirm = _prompt(f"  Captured: {uid} — Is this you? (y/n)", "y")
                if confirm.lower() != "n":
                    if uid not in collected:
                        collected.append(uid)
                    _ok(f"Discord user ID confirmed: {uid}")
                else:
                    raw = _prompt("Enter your Discord user ID manually (or Enter to skip)")
                    if raw.isdigit():
                        collected.append(int(raw))
            else:
                raw = _prompt("Enter your Discord user ID manually (or Enter to skip)")
                if raw.isdigit():
                    collected.append(int(raw))
        else:
            raw = _prompt("Enter your Discord user ID manually (or Enter to skip)")
            if raw.isdigit():
                collected.append(int(raw))

    # ── Fallback: neither channel has a token (shouldn't happen normally) ─
    if not state.channels or (
        "telegram" not in state.channels and "discord" not in state.channels
    ):
        raw = _prompt("Enter your user ID (or Enter to skip)")
        if raw.isdigit():
            collected.append(int(raw))

    state.allowed_user_ids = collected

    # ── Handle empty allowlist gracefully — deferred config ──────────────
    if not state.allowed_user_ids:
        print(f"\n{_Y}⚠ No user IDs set.{_X}")
        print("  Bot will reject ALL requests unless you set allow_all_users=true.")
        allow_all = _prompt(
            "  Allow ALL users? This is dangerous in public servers. (y/n)", "n"
        )
        if allow_all.lower() == "y":
            state.data["allow_all_users"] = True
            _warn("All users allowed — make sure this is intentional.")
        else:
            _warn("No user IDs configured — edit secrets/.env to add ALLOWED_USER_IDS before starting the bot.")

    mark_micro_step_done(state, "allowlist.done")


_ALL_CLIS = ["claude", "codex", "gemini", "kiro"]


async def step_4_clis(state: WizardState) -> None:
    if is_micro_step_done(state, "cli_select.done"):
        _ok(f"Step 4 done (CLIs: {state.selected_clis})")
        return
    set_current_step(state, "cli_select.started")
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
    mark_micro_step_done(state, "cli_select.done")


async def step_4_5_acp(state: WizardState) -> None:
    if is_micro_step_done(state, "acp_setup.done"):
        _ok(f"Step 4.5 done (mode: {state.acp_mode})")
        return

    set_current_step(state, "acp_setup.started")
    _hdr("4.5", "AI 協作模式")

    cli_list = ", ".join(state.selected_clis) if state.selected_clis else "（未選擇）"
    print(f"\n你已選擇的 AI 工具：{cli_list}\n")

    _acp_choices = [
        ("1", "讓 Claude 自己決定怎麼協調 — 只需安裝 1 個套件"),
        ("2", "用指令讓 AI 輪流發言 (/discuss, /debate) — 每個 AI 各需 1 個套件"),
        ("3", "兩種都要"),
    ]

    if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
        result = await _q_ask(_q.select(
            "這些 AI 你希望怎麼合作？",
            choices=[_q.Choice(label, value=val) for val, label in _acp_choices],
        ))
        if result is None:
            print("\nSetup cancelled.")
            sys.exit(0)
        raw = result
    else:
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


async def step_5_search(state: WizardState) -> None:
    if is_micro_step_done(state, "search_mode.done"):
        _ok(f"Step 5 done (search: {state.search_mode})")
        return
    set_current_step(state, "search_mode.started")
    _hdr(5, "Search Mode")

    if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
        result = await _q_ask(_q.select(
            "Search mode:",
            choices=[
                _q.Choice("FTS5 keyword search  (default, no extra install)", value="1"),
                _q.Choice("FTS5 + embedding  (Ollama ~500MB — foreground install)", value="2"),
            ],
        ))
        if result is None:
            print("\nSetup cancelled.")
            sys.exit(0)
        choice = result
    else:
        print("  1. FTS5 keyword search (default, no extra install)")
        print("  2. FTS5 + embedding (Ollama ~500MB — foreground install)")
        choice = _prompt("Choose", "1")
    if choice == "2":
        print("  Installing Ollama (~500MB) — this will take a few minutes...")
        ok = await install_ollama_foreground()
        if not ok:
            _err("Ollama install failed.")
            fallback = _prompt("  Continue with FTS5-only search? (Y/n)", "y")
            if fallback.lower() == "n":
                _warn("Search mode left unset — re-run setup or run /config later.")
                return
            state.search_mode = "fts5"
            _warn("Falling back to FTS5. Embedding search disabled.")
        else:
            state.search_mode = "fts5+embedding"
            _ok("Ollama installed")
        mark_micro_step_done(state, "search_mode.done")
        return
    state.search_mode = "fts5"
    _ok("Search mode: FTS5")
    mark_micro_step_done(state, "search_mode.done")


# (key, label, size_hint, packages)
_OPTIONAL_GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("discord_voice", "Discord 語音頻道  (PyNaCl)",              "~10 MB",  ["PyNaCl"]),
    ("voice",         "語音輸入/輸出 STT/TTS  (groq, edge-tts)", "~50 MB",  ["groq", "edge-tts"]),
    ("browser",       "瀏覽器技能  (playwright + Chromium)",     "~1.5 GB", ["playwright", "html2text"]),
    ("tavily",        "Tavily 高級搜尋  (tavily-python)",         "~1 MB",   ["tavily-python"]),
]

# Packs that require a second confirmation before installing (large downloads).
_HEAVY_PACKS: dict[str, str] = {
    "browser": "~1.5 GB (Playwright + Chromium browser)",
}


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
    if is_micro_step_done(state, "optional_packages.done"):
        _ok(f"Step 6 done (optional: {state.optional_packages or 'none'})")
        return
    set_current_step(state, "optional_packages.started")
    _hdr(6, "Optional Features")
    print("  All optional — can be added later by re-running setup. Default: off.\n")
    selected: set[str] = set()

    if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
        choices = []
        for key, label, size, pkgs in _OPTIONAL_GROUPS:
            status = "installed" if all(_pkg_installed(p) for p in pkgs) else "not installed"
            choices.append(_q.Choice(f"{label}  ({size})  — {status}", value=key))
        result = await _q_ask(_q.checkbox(
            "Select optional features (Space to toggle, Enter to confirm, default: none):",
            choices=choices,
        ))
        if result is None:
            print("\nSetup cancelled.")
            sys.exit(0)
        selected = set(result)
    else:
        while True:
            print("")
            for i, (key, label, size, pkgs) in enumerate(_OPTIONAL_GROUPS, 1):
                mark = "x" if key in selected else " "
                status = _G + "installed" + _X if all(_pkg_installed(p) for p in pkgs) else _Y + "not installed" + _X
                print(f"  [{mark}] {i}. {label}  {_Y}({size}){_X}  — {status}")
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

    # Second confirmation for heavy packs
    for key, size_desc in _HEAVY_PACKS.items():
        if key in selected:
            confirm = _prompt(
                f"  ⚠ '{key}' requires {size_desc}. Download now? (y/n)", "n"
            )
            if confirm.lower() != "y":
                selected.discard(key)
                _warn(f"Skipped '{key}' — add later by re-running setup.")

    to_install: list[str] = []
    for key, _, _size, pkgs in _OPTIONAL_GROUPS:
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

    mark_micro_step_done(state, "optional_packages.done")


async def step_7_updates(state: WizardState) -> None:
    if is_micro_step_done(state, "update_notifications.done"):
        _ok(f"Step 7 done (update notifications: {state.update_notifications})")
        return
    set_current_step(state, "update_notifications.started")
    _hdr(7, "Update Notifications")
    print("  Check for new GitHub releases on startup and print a notice.")
    print("  (Never auto-updates — you control when to update.)")

    if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
        result = await _q_ask(_q.confirm("Enable update notifications?", default=True))
        state.update_notifications = result if result is not None else True
    else:
        choice = _prompt("Enable? (y/n)", "y")
        state.update_notifications = choice.lower() != "n"
    _ok(f"Update notifications: {'on' if state.update_notifications else 'off'}")
    mark_micro_step_done(state, "update_notifications.done")


async def _wait_for_docker(timeout: int = 60) -> bool:
    """Poll `docker info` every 2s silently until it succeeds or timeout is reached."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(["docker", "info"], capture_output=True)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            return False
        await asyncio.sleep(2)
    return False


async def step_8_deploy(state: WizardState, cwd: str = ".") -> None:
    if is_micro_step_done(state, "deploy_mode.done"):
        _ok(f"Step 8 done (deploy: {state.deploy_mode})")
        return
    set_current_step(state, "deploy_mode.started")
    _hdr(8, "Deploy Mode")

    _deploy_choices = [
        ("1", "foreground  — run in terminal (Ctrl-C to stop)"),
        ("2", "systemd     — user service, auto-restart, survives logout"),
        ("3", "docker      — docker compose (requires Docker)"),
    ]

    while True:
        if _has_questionary and sys.stdin.isatty() and sys.stdout.isatty():
            result = await _q_ask(_q.select(
                "Deploy mode:",
                choices=[_q.Choice(label, value=val) for val, label in _deploy_choices],
            ))
            if result is None:
                print("\nSetup cancelled.")
                sys.exit(0)
            choice = result
        else:
            print("  1. foreground  — run in terminal (Ctrl-C to stop)")
            print("  2. systemd     — user service, auto-restart, survives logout")
            print("  3. docker      — docker compose (requires Docker)")
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
            # Pre-validate: Docker is installed and daemon is running
            try:
                r = subprocess.run(["docker", "info"], capture_output=True)
                docker_found = True
            except FileNotFoundError:
                docker_found = False

            if not docker_found:
                _err("Docker not found.")
                if sys.platform == "darwin":
                    hint = "brew install --cask docker  (requires Homebrew)"
                else:
                    hint = "curl -fsSL https://get.docker.com | sh"
                ans = _prompt(f"Auto-install Docker? ({hint}) (Y/n)", "y")
                if ans.lower() != "n":
                    print("  Installing Docker...")
                    ok = await install_docker_foreground()
                    if not ok:
                        if sys.platform == "darwin" and not __import__("shutil").which("brew"):
                            _err("Homebrew not found. Install from https://brew.sh then retry.")
                        else:
                            _err("Auto-install failed. Install Docker manually and try again.")
                        continue
                    _ok("Docker installed")
                else:
                    _err("Docker required for this deploy mode. Choose a different option.")
                    continue

            # At this point docker binary exists; check if daemon is running.
            # On macOS, Docker Desktop may need to be launched manually.
            try:
                r = subprocess.run(["docker", "info"], capture_output=True)
            except FileNotFoundError:
                _err("Docker binary not found. Restart your terminal and try again.")
                continue

            if r.returncode != 0:
                if sys.platform == "darwin":
                    _warn("Docker Desktop is not running. Please launch it now.")
                    _prompt("Press Enter when you have opened Docker Desktop")
                    print("  Waiting for Docker daemon to be ready...")
                else:
                    _warn("Docker daemon not running. Starting: sudo systemctl start docker")
                    subprocess.run(["sudo", "systemctl", "start", "docker"], check=False)
                ready = await _wait_for_docker(timeout=180)
                if not ready:
                    _err("Docker daemon not ready after 3 minutes. Make sure Docker Desktop is running, then try again.")
                    continue

            state.deploy_mode = "docker"
            break
        else:
            state.deploy_mode = "foreground"
            break
    _ok(f"Deploy mode: {state.deploy_mode}")
    mark_micro_step_done(state, "deploy_mode.done")


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


def _print_completion_docker(cwd: str, *, running: bool = True) -> None:
    W = 52
    print(f"\n{_B}{'='*W}{_X}")
    if running:
        print(f"{_G}{_B}  ✅  Setup complete — bot is running!{_X}")
    else:
        print(f"{_Y}{_B}  ⚠  Config written — start manually:{_X}")
        print(f"     docker compose -f {cwd}/docker-compose.yml up -d")
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
) -> None:
    if is_micro_step_done(state, "launch.done"):
        _ok("Already configured — skipping launch step.")
        return
    set_current_step(state, "launch.started")
    _hdr(9, "Writing config and launching")
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
    mark_micro_step_done(state, "launch.done")
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
        try:
            r = subprocess.run(["docker", "compose", "up", "-d"], cwd=cwd, check=False)
        except FileNotFoundError:
            _err("docker not found — cannot launch container.")
            _print_completion_docker(cwd, running=False)
            return
        if r.returncode != 0:
            _err("docker compose up -d failed — see error above.")
            _print_completion_docker(cwd, running=False)
            return
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
            _print_completion_docker(cwd, running=True)
        else:
            _err("Smoke test timed out — container may still be building or starting.")
            _print_completion_docker(cwd, running=False)
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
    *,
    headless_channel: str | None = None,
    headless_telegram_token: str | None = None,
    headless_discord_token: str | None = None,
    headless_allowed_user_ids: str | None = None,
    headless_allow_all_users: bool = False,
    headless_clis: str | None = None,
    headless_search_mode: str | None = None,
    headless_optional_packs: str | None = None,
    headless_update_notifications: bool | None = None,
    headless_deploy_mode: str | None = None,
    headless_acp_mode: str | None = None,
    skip_preflight: bool = False,
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

    # ── Headless pre-population: apply CLI flags and mark steps done ────────
    if headless_channel:
        state.channels = [c.strip() for c in headless_channel.split(",") if c.strip()]
        mark_micro_step_done(state, "channel_select.done")
    if headless_telegram_token:
        state.telegram_token = headless_telegram_token
    if headless_discord_token:
        state.discord_token = headless_discord_token
    if headless_telegram_token or headless_discord_token:
        mark_micro_step_done(state, "token_validation.done")
        _warn("Headless mode: tokens accepted without live validation — ensure tokens are correct.")
    if headless_allowed_user_ids:
        state.allowed_user_ids = [int(x) for x in headless_allowed_user_ids.split(",") if x.strip().isdigit()]
        mark_micro_step_done(state, "allowlist.done")
    elif headless_allow_all_users:
        state.data["allow_all_users"] = True
        mark_micro_step_done(state, "allowlist.done")
    if headless_clis:
        state.selected_clis = [c.strip() for c in headless_clis.split(",") if c.strip()]
        mark_micro_step_done(state, "cli_select.done")
    if headless_search_mode:
        state.search_mode = headless_search_mode
        mark_micro_step_done(state, "search_mode.done")
    if headless_optional_packs is not None:
        state.optional_packages = [p.strip() for p in headless_optional_packs.split(",") if p.strip()]
        mark_micro_step_done(state, "optional_packages.done")
    if headless_update_notifications is not None:
        state.update_notifications = headless_update_notifications
        mark_micro_step_done(state, "update_notifications.done")
    if headless_deploy_mode:
        state.deploy_mode = headless_deploy_mode
        mark_micro_step_done(state, "deploy_mode.done")
    _is_headless = any([
        headless_channel, headless_telegram_token, headless_discord_token,
        headless_allowed_user_ids, headless_allow_all_users, headless_clis,
        headless_search_mode, headless_optional_packs is not None,
        headless_update_notifications is not None, headless_deploy_mode,
    ])
    if _is_headless:
        state.acp_mode = headless_acp_mode or "orchestrator"
        mark_micro_step_done(state, "acp_setup.done")

    # fresh / resume / reset all run the full wizard (steps skip if done)
    if not skip_preflight:
        await run_preflight(cwd)
    await step_1_channel(state)
    save_state(state, state_path)
    await step_2_token(state)
    save_state(state, state_path)
    await step_3_allowlist(state)
    save_state(state, state_path)
    await step_4_clis(state)
    save_state(state, state_path)
    await step_4_5_acp(state)
    save_state(state, state_path)
    await step_5_search(state)
    save_state(state, state_path)
    await step_6_optional(state)
    save_state(state, state_path)
    await step_7_updates(state)
    save_state(state, state_path)
    await step_8_deploy(state, cwd=cwd)
    save_state(state, state_path)
    await step_9_launch(state, cwd)


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(
        description="MAT Setup Wizard — interactive or headless (--channel ... flags)",
    )
    _ap.add_argument("--reset", action="store_true", help="Wipe saved state and start from step 1")
    _ap.add_argument("--skip-preflight", action="store_true", help="Skip pre-flight checks (CI use)")
    # Headless flags — when all are provided the wizard runs without prompts
    _ap.add_argument("--channel", metavar="telegram|discord|telegram,discord", help="Channel(s) to configure")
    _ap.add_argument("--telegram-token", metavar="TOKEN", help="Telegram bot token")
    _ap.add_argument("--discord-token", metavar="TOKEN", help="Discord bot token")
    _ap.add_argument("--allowed-user-ids", metavar="ID1,ID2", help="Comma-separated allowed user IDs")
    _ap.add_argument("--allow-all-users", action="store_true", help="Allow all users (skip allowlist)")
    _ap.add_argument("--clis", metavar="claude,codex,...", help="CLI tools to install")
    _ap.add_argument("--search-mode", choices=["fts5", "fts5+embedding"], help="Search mode")
    _ap.add_argument("--optional-packs", metavar="voice,browser,...", help="Optional packs (empty string = none)")
    _ap.add_argument("--update-notifications", action="store_true", default=None, help="Enable update notifications")
    _ap.add_argument("--no-update-notifications", dest="update_notifications", action="store_false")
    _ap.add_argument("--deploy-mode", choices=["foreground", "systemd", "docker"], help="Deploy mode")
    _args = _ap.parse_args()
    asyncio.run(run_wizard(
        cwd=os.path.abspath("."),
        reset=_args.reset,
        skip_preflight=_args.skip_preflight,
        headless_channel=_args.channel,
        headless_telegram_token=_args.telegram_token,
        headless_discord_token=_args.discord_token,
        headless_allowed_user_ids=_args.allowed_user_ids,
        headless_allow_all_users=_args.allow_all_users,
        headless_clis=_args.clis,
        headless_search_mode=_args.search_mode,
        headless_optional_packs=_args.optional_packs,
        headless_update_notifications=_args.update_notifications,
        headless_deploy_mode=_args.deploy_mode,
    ))
