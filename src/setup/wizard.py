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
