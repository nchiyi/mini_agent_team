"""Interactive helpers for collecting one bot's config.

Used by:
- wizard step_2_token (multi-bot loop)
- src.setup.add_bot (standalone post-install tool)

Returns a dict shaped for src/setup/deploy.py:_render_bots_sections, plus a
private ``_token_value`` field that the caller writes into secrets/.env via
BOT_<ID>_TOKEN. ``_token_value`` is stripped before the dict is rendered to
TOML.
"""
from __future__ import annotations

import re
from typing import Any

from src.setup.validator import (
    validate_telegram_token, validate_discord_token,
)


_SLUG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def _prompt(text: str, default: str = "") -> str:
    """Indirection so tests can monkeypatch."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"  {text}{suffix}: ").strip()
    return raw or default


def _err(msg: str) -> None:
    print(f"  ✗ {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _warn(msg: str) -> None:
    print(f"  ! {msg}")


def _validate_id(bid: str) -> bool:
    return bool(_SLUG_RE.match(bid))


def _parse_int_list(raw: str) -> list[int]:
    if not raw.strip():
        return []
    out: list[int] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            _warn(f"Skipping non-integer chat id: {piece!r}")
    return out


async def collect_bot(*, channel: str, default_runner: str) -> dict[str, Any]:
    """Interactively collect one bot's config. Returns dict for [bots.X] block.

    Caller is responsible for ensuring `id` is unique within the existing bots
    list — this helper validates only slug shape.
    """
    # 1. Token (with validation, retry loop, skip option)
    validator = (
        validate_telegram_token if channel == "telegram"
        else validate_discord_token
    )
    while True:
        token = _prompt(f"{channel} bot token (type 's' to skip validation)")
        if not token:
            _err("Token required")
            continue
        if token.lower() == "s":
            token = _prompt(f"{channel} bot token (saved without validation)")
            if token:
                break
            continue
        print("  Validating...")
        result = validator(token)
        if result.valid or result.skipped:
            uname = getattr(result, "bot_username", "") or "(unknown)"
            _ok(f"{channel} token OK — @{uname}")
            break
        _err(getattr(result, "reason", "validation failed"))

    # 2. Bot id (slug)
    while True:
        bid = _prompt("Bot id (slug, used for env var name and config key)")
        if not bid:
            _err("Bot id required")
            continue
        if not _validate_id(bid):
            _err("Bot id must match [a-zA-Z][a-zA-Z0-9_]*")
            continue
        break

    # 3. Optional metadata
    label = _prompt("Label (free text, optional)")
    runner = _prompt("Default runner", default_runner)
    role = _prompt("Default role (optional)")

    # 4. Group settings
    allow_all = _prompt("Allow this bot in all groups? (y/n)", "n").lower().startswith("y")
    # Always consume the chat-ids prompt so the prompt sequence is stable for
    # callers/tests; the value is only honoured when allow_all is False.
    raw_ids = _prompt(
        "Allowed group chat_ids (comma-separated, leave empty for DMs only)"
    )
    allowed_chat_ids: list[int] = [] if allow_all else _parse_int_list(raw_ids)
    abm = _prompt(
        "Allow bot-to-bot messages? (off / mentions / all)", "off",
    ).lower()
    if abm not in ("off", "mentions", "all"):
        _warn(f"Invalid allow_bot_messages={abm!r}, defaulting to 'off'")
        abm = "off"

    out: dict[str, Any] = {
        "id": bid,
        "channel": channel,
        "token_env": f"BOT_{bid.upper()}_TOKEN",
        "_token_value": token,
        "default_runner": runner,
    }
    if label:
        out["label"] = label
    if role:
        out["default_role"] = role
    if allow_all:
        out["allow_all_groups"] = True
    elif allowed_chat_ids:
        out["allowed_chat_ids"] = allowed_chat_ids
    if abm != "off":
        out["allow_bot_messages"] = abm
    return out
