"""Channel-agnostic dispatch policy gate.

Extracted from ``src/channels/telegram_runner.py`` (B-2 Task 6). Lives
under ``src/gateway/`` so future Discord multi-bot work can reuse the
same policy semantics. The implementation is intentionally pure (no IO,
no async): given an InboundMessage, a BotConfig, and an optional
BotTurnTracker, it returns True iff the dispatcher should process the
message for this bot.

Decision order:
1. DMs (chat_type == "private") always pass.
2. Groups: bot must be in allowed_chat_ids OR have allow_all_groups=True.
3. Bot-sourced messages: gated by allow_bot_messages
   (off / mentions / all). For "all", also check turn cap.
4. Human in group: only if this bot is in mentioned_bot_ids.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.channels.base import InboundMessage
    from src.core.bots import BotConfig
    from src.gateway.bot_turns import BotTurnTracker


def should_handle(
    inbound: "InboundMessage",
    bot_cfg: "BotConfig",
    turns: "BotTurnTracker | None",
) -> bool:
    """Return True iff the dispatcher should handle this inbound for bot_cfg.

    Pure function: no IO, no awaits. Safe to call from any sync code path.
    """
    if inbound.chat_type == "private":
        return True

    # ── Group authorisation ──
    if not bot_cfg.allow_all_groups:
        allowed = bot_cfg.allowed_chat_ids or []
        if inbound.chat_id not in allowed:
            return False

    # ── Bot-to-bot policy ──
    if inbound.from_bot:
        policy = bot_cfg.allow_bot_messages
        if policy == "off":
            return False
        if policy == "mentions" and bot_cfg.id not in inbound.mentioned_bot_ids:
            return False
        if turns is not None and inbound.chat_id is not None and turns.cap_reached(
            channel="telegram", chat_id=inbound.chat_id,
        ):
            return False
        return True

    # ── Human in group ──
    return bot_cfg.id in inbound.mentioned_bot_ids
