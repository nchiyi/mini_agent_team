"""
Smoke test for the setup wizard — Phase 3.

Launches the bot process, waits for a ready signal, sends a verification
message to the configured user, and waits for an 'ok' reply.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.setup.state import WizardState

# ---------------------------------------------------------------------------
# ANSI helpers (duplicated locally so this module is self-contained)
# ---------------------------------------------------------------------------
_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"

_READY_SIGNALS = (
    "bot started",
    "gateway ready",
    "polling started",
    "connected to discord",
)

_VERIFICATION_MSG = "Setup complete, reply 'ok' to verify"


# ---------------------------------------------------------------------------
# 1. wait_for_bot_ready
# ---------------------------------------------------------------------------

async def wait_for_bot_ready(
    proc: asyncio.subprocess.Process,
    timeout: int = 60,
) -> bool:
    """
    Read proc stdout/stderr and return True when a ready signal is found.

    Ready signals (case-insensitive):
      - "bot started"
      - "gateway ready"
      - "polling started"
      - "connected to discord"

    Returns False if *timeout* seconds elapse without any signal.
    The stream is NOT closed by this function — the caller keeps reading.
    """
    if proc.stdout is None:
        return False

    # We collect lines for diagnostic purposes (shared buffer lives in caller).
    try:
        async with asyncio.timeout(timeout):
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                # Echo to terminal so the user sees live output
                sys.stdout.write(f"  {line}\n")
                sys.stdout.flush()
                lower = line.lower()
                if any(sig in lower for sig in _READY_SIGNALS):
                    return True
    except TimeoutError:
        return False
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception:
        return False
    # Stream closed before signal
    return False


# ---------------------------------------------------------------------------
# 2. send_verification (Telegram)
# ---------------------------------------------------------------------------

async def send_verification_telegram(token: str, user_id: int) -> bool:
    """
    Send a DM to *user_id* via the Telegram Bot API.

    POST https://api.telegram.org/bot{token}/sendMessage
    Returns True on success.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": user_id,
        "text": _VERIFICATION_MSG,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return bool(data.get("ok"))
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# 3. send_verification (Discord)
# ---------------------------------------------------------------------------

async def send_verification_discord(token: str, user_id: int) -> bool:
    """
    Send a DM to *user_id* via the Discord Bot API (discord.py).
    Returns True on success.
    """
    try:
        import discord  # type: ignore[import]
    except ImportError:
        print(f"{_Y}⚠ discord.py not installed — skipping Discord verification{_X}")
        return False

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    success = False

    @client.event
    async def on_ready() -> None:  # type: ignore[misc]
        nonlocal success
        try:
            user = await client.fetch_user(user_id)
            await user.send(_VERIFICATION_MSG)
            success = True
        except Exception as exc:
            print(f"{_Y}⚠ Could not send Discord DM: {exc}{_X}")
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=30)
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    return success


# ---------------------------------------------------------------------------
# 4. wait_for_ok_reply (Telegram — getUpdates polling)
# ---------------------------------------------------------------------------

async def wait_for_ok_reply_telegram(
    token: str,
    user_id: int,
    timeout: int = 120,
) -> bool:
    """
    Poll getUpdates until *user_id* sends a message containing 'ok'
    (case-insensitive), or *timeout* seconds elapse.

    Returns True on success.
    """
    offset: int | None = None
    deadline = asyncio.get_running_loop().time() + timeout

    while asyncio.get_running_loop().time() < deadline:
        params: dict[str, object] = {"timeout": 10, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset

        query = urllib.parse.urlencode(params)
        url = f"https://api.telegram.org/bot{token}/getUpdates?{query}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError):
            await asyncio.sleep(3)
            continue

        if not data.get("ok"):
            await asyncio.sleep(3)
            continue

        for update in data.get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            from_id = (msg.get("from") or {}).get("id")
            text = (msg.get("text") or "").lower()
            if from_id == user_id and "ok" in text:
                return True

        # Short sleep so we don't hammer the API when there are no updates
        await asyncio.sleep(2)

    return False


# ---------------------------------------------------------------------------
# 5. wait_for_ok_reply (Discord)
# ---------------------------------------------------------------------------

async def wait_for_ok_reply_discord(
    token: str,
    user_id: int,
    timeout: int = 120,
) -> bool:
    """
    Use a discord.py Client to listen for a DM containing 'ok'
    (case-insensitive) from *user_id*.

    Returns True on success.
    """
    try:
        import discord  # type: ignore[import]
    except ImportError:
        print(f"{_Y}⚠ discord.py not installed — skipping Discord ok-wait{_X}")
        return False

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    got_ok: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    @client.event
    async def on_message(message: discord.Message) -> None:  # type: ignore[misc]
        if (
            message.author.id == user_id
            and isinstance(message.channel, discord.DMChannel)
            and "ok" in message.content.lower()
        ):
            if not got_ok.done():
                got_ok.set_result(True)
            await client.close()

    async def _run() -> bool:
        try:
            async with asyncio.timeout(timeout):
                await client.start(token)
                return await got_ok
        except TimeoutError:
            return False
        except Exception:
            return False
        finally:
            if not client.is_closed():
                await client.close()

    return await _run()


# ---------------------------------------------------------------------------
# 6. Diagnostic printer
# ---------------------------------------------------------------------------

def _print_diagnostic(
    exit_code: int | None,
    last_lines: list[str],
) -> None:
    print(f"\n{_R}✗ Smoke test failed.{_X}")
    code_str = str(exit_code) if exit_code is not None else "still running"
    print(f"  Bot process exit code: {code_str}")
    if last_lines:
        print("  Last lines of output:")
        for ln in last_lines[-10:]:
            print(f"    {ln}")
    print(f"\n  {_B}Suggested fixes:{_X}")
    print("  • Check token validity: python -m src.setup.validator")
    print("  • Check logs: journalctl --user -u gateway-agent -n 50")
    print("  • Re-run setup: python -m src.setup.wizard --reset")
    print()


# ---------------------------------------------------------------------------
# 7. run_smoke_test — main entry point
# ---------------------------------------------------------------------------

async def run_smoke_test(
    state: "WizardState",
    proc: asyncio.subprocess.Process,
) -> bool:
    """
    Orchestrate the full smoke test:

    1. wait_for_bot_ready (reads stdout from *proc*)
    2. For each channel in state.channels:
       - send_verification_{channel}
       - wait_for_ok_reply_{channel}
    3. Return True if all pass, False + diagnostic on any failure.

    If state.data.get("allow_all_users") is True and state.allowed_user_ids
    is empty, the verification DM step is skipped (bot won't know who to ping).
    """
    # ------------------------------------------------------------------
    # Guard: if allow_all_users and no known user_id, skip verification
    # ------------------------------------------------------------------
    allow_all = state.data.get("allow_all_users", False)
    has_user = bool(state.allowed_user_ids)

    if allow_all and not has_user:
        print(
            f"{_Y}⚠ allow_all_users is set and no specific user ID captured — "
            f"skipping smoke-test verification DM.{_X}"
        )
        # Still wait for ready signal so we know the bot started
        _ready = await wait_for_bot_ready(proc, timeout=60)
        if not _ready:
            _print_diagnostic(proc.returncode, [])
            return False
        return True

    target_user_id = state.allowed_user_ids[0] if has_user else None

    # ------------------------------------------------------------------
    # Step 1: wait for bot ready signal
    # ------------------------------------------------------------------
    print("  Waiting for bot ready signal…")
    ready = await wait_for_bot_ready(proc, timeout=60)
    if not ready:
        _print_diagnostic(proc.returncode, [])
        return False

    print(f"{_G}✓ Bot ready signal received.{_X}")

    if target_user_id is None:
        # No user to ping — call it done
        return True

    # ------------------------------------------------------------------
    # Step 2: verification DM + ok-reply for each channel
    # ------------------------------------------------------------------
    for channel in state.channels:
        print(f"  Sending verification message via {channel}…")

        if channel == "telegram":
            sent = await send_verification_telegram(
                state.telegram_token, target_user_id
            )
        elif channel == "discord":
            sent = await send_verification_discord(
                state.discord_token, target_user_id
            )
        else:
            print(f"{_Y}⚠ Unknown channel {channel!r} — skipping{_X}")
            continue

        if not sent:
            print(f"{_R}✗ Could not send verification message via {channel}.{_X}")
            _print_diagnostic(proc.returncode, [])
            return False

        print(f"  Waiting for 'ok' reply via {channel} (up to 120 s)…")

        if channel == "telegram":
            replied = await wait_for_ok_reply_telegram(
                state.telegram_token, target_user_id, timeout=120
            )
        else:
            replied = await wait_for_ok_reply_discord(
                state.discord_token, target_user_id, timeout=120
            )

        if not replied:
            print(f"{_R}✗ No 'ok' reply from user via {channel} within 120 s.{_X}")
            _print_diagnostic(proc.returncode, [])
            return False

        print(f"{_G}✓ Received 'ok' reply via {channel}.{_X}")

    return True
