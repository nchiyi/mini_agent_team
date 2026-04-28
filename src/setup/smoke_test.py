"""
Smoke test for the setup wizard — Phase 3.

Launches the bot process, waits for a ready signal, sends a verification
message to the configured user, and waits for an 'ok' reply.
"""

from __future__ import annotations

import asyncio
import json
import re
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
    "telegram bot running",          # main.py: [main] INFO: Telegram bot running
    "application started",            # PTB: [telegram.ext.Application] INFO: Application started
    "shard id none has connected",    # discord.py: [discord.gateway] INFO: Shard ID None has connected to Gateway
    "bot started",
    "gateway ready",
    "polling started",
    "connected to discord",
)

_CONFLICT_SIGNALS = (
    "terminated by other getupdates",
    "telegram.error.conflict",
    "conflict: terminated by",
)

# Return values for run_smoke_test
RESULT_OK = "ok"
RESULT_CONFLICT = "conflict"
RESULT_FAILED = "failed"

_VERIFICATION_MSG = "Setup complete, reply 'ok' to verify"

# Redact bot tokens from log lines before printing to terminal.
# Telegram tokens look like: 123456789:ABCdef...
_TOKEN_RE = re.compile(r'/bot\d{5,15}:[A-Za-z0-9_-]{35,}/')


def _redact(line: str) -> str:
    return _TOKEN_RE.sub('/bot[REDACTED]/', line)


# ---------------------------------------------------------------------------
# 1. wait_for_bot_ready
# ---------------------------------------------------------------------------

async def wait_for_bot_ready(
    proc: asyncio.subprocess.Process,
    timeout: int = 60,
) -> tuple[bool, bool]:
    """
    Read proc stdout/stderr and return (ready, conflict_detected).

    Handles long-running containers whose --tail=50 history may contain old
    409 Conflict errors followed by 200 OK recoveries:
    - conflict flag is reset if 2 consecutive 200 OK responses appear after it
    - ready signal (startup message) always wins immediately

    Returns (False, True)  on unresolved conflict after timeout.
    Returns (False, False) on timeout with no signal.
    """
    if proc.stdout is None:
        return False, False

    conflict = False
    successes_after_conflict = 0
    try:
        async with asyncio.timeout(timeout):
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                sys.stdout.write(f"  {_redact(line)}\n")
                sys.stdout.flush()
                lower = line.lower()
                if any(sig in lower for sig in _CONFLICT_SIGNALS):
                    conflict = True
                    successes_after_conflict = 0
                elif conflict and "200 ok" in lower:
                    successes_after_conflict += 1
                    if successes_after_conflict >= 2:
                        # Bot recovered from a historical conflict — treat as ready
                        return True, False
                if any(sig in lower for sig in _READY_SIGNALS):
                    return True, False
    except TimeoutError:
        return False, conflict
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception:
        return False, conflict
    return False, conflict


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
    *,
    verify_reply: bool = True,
) -> str:
    """
    Orchestrate the full smoke test.

    Returns one of: RESULT_OK, RESULT_CONFLICT, RESULT_FAILED.

    1. wait_for_bot_ready (reads stdout from *proc*)
    2. For each channel in state.channels:
       - send_verification_{channel}
       - wait_for_ok_reply_{channel}   (skipped when verify_reply=False)

    Pass verify_reply=False for Docker/systemd modes where the bot owns
    the getUpdates stream — calling getUpdates from here would cause a
    Telegram 409 Conflict.

    If state.data.get("allow_all_users") is True and state.allowed_user_ids
    is empty, the verification DM step is skipped.
    """
    allow_all = state.data.get("allow_all_users", False)
    has_user = bool(state.allowed_user_ids)

    if allow_all and not has_user:
        print(
            f"{_Y}⚠ allow_all_users is set and no specific user ID captured — "
            f"skipping smoke-test verification DM.{_X}"
        )
        _ready, _conflict = await wait_for_bot_ready(proc, timeout=60)
        if _conflict:
            return RESULT_CONFLICT
        if not _ready:
            _print_diagnostic(proc.returncode, [])
            return RESULT_FAILED
        return RESULT_OK

    target_user_id = state.allowed_user_ids[0] if has_user else None

    # ------------------------------------------------------------------
    # Step 1: wait for bot ready signal
    # ------------------------------------------------------------------
    print("  Waiting for bot ready signal…")
    ready, conflict = await wait_for_bot_ready(proc, timeout=60)
    if conflict:
        return RESULT_CONFLICT
    if not ready:
        _print_diagnostic(proc.returncode, [])
        return RESULT_FAILED

    print(f"{_G}✓ Bot ready signal received.{_X}")

    if target_user_id is None:
        return RESULT_OK

    # ------------------------------------------------------------------
    # Step 2: verification DM + ok-reply for each channel
    # At least one channel must succeed; others produce warnings not failures.
    # ------------------------------------------------------------------
    any_verified = False
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
            print(f"{_Y}⚠ Could not send verification message via {channel} — skipping.{_X}")
            print(f"  (Discord DMs require the bot to share a server with the user){_X}" if channel == "discord" else "")
            continue

        # When verify_reply=False (Docker/systemd), skip getUpdates polling —
        # the running bot already owns that stream and a second caller causes 409.
        if not verify_reply:
            print(f"{_G}✓ Verification DM sent via {channel} — reply check skipped (bot owns the stream).{_X}")
            any_verified = True
            continue

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
            print(f"{_Y}⚠ No 'ok' reply from user via {channel} within 120 s.{_X}")
            continue

        print(f"{_G}✓ Received 'ok' reply via {channel}.{_X}")
        any_verified = True

    if not any_verified:
        _print_diagnostic(proc.returncode, [])
        return RESULT_FAILED

    return RESULT_OK
