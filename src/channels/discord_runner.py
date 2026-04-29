"""Per-bot Discord orchestration. Mirrors src/channels/telegram_runner.py.

Each Discord bot in cfg.bots (channel='discord') gets one
run_discord_for_bot(ctx, bot_cfg) coroutine, scheduled by
main._build_channel_tasks().
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.channels.discord_adapter import DiscordAdapter
from src.core.config import _resolve_channel_auth

if TYPE_CHECKING:
    from src.core.bots import BotConfig
    from src.gateway.app_context import AppContext

logger = logging.getLogger(__name__)


async def run_discord_for_bot(ctx: "AppContext", bot_cfg: "BotConfig") -> None:
    """Launch one Discord client bound to a single bot.

    InboundMessage produced by this adapter is stamped with bot_id=bot_cfg.id.
    """
    cfg = ctx.cfg

    # 3-level precedence: bot → channel → global.
    allowed = (
        bot_cfg.allowed_user_ids
        if bot_cfg.allowed_user_ids is not None
        else cfg.discord.allowed_user_ids
    )
    allow_all = (
        bot_cfg.allow_all_users
        if bot_cfg.allow_all_users is not None
        else cfg.discord.allow_all_users
    )
    dc_ids, dc_all = _resolve_channel_auth(cfg, allowed, allow_all)

    async def gateway_handler(inbound):
        # Task 3 接 should_handle + dispatch；這裡先 stub
        return

    adapter = DiscordAdapter(
        token=bot_cfg.token,
        allowed_user_ids=dc_ids,
        gateway_handler=gateway_handler,
        bot_id=bot_cfg.id,
        allowed_channel_ids=cfg.discord.allowed_channel_ids,
        allow_bot_messages=bot_cfg.allow_bot_messages or cfg.discord.allow_bot_messages,
        allow_user_messages=cfg.discord.allow_user_messages,
        trusted_bot_ids=bot_cfg.trusted_bot_ids or cfg.discord.trusted_bot_ids,
        allow_all_users=dc_all,
        bot_registry=ctx.bot_registry,
    )
    logger.info("Discord bot %s starting", bot_cfg.id)
    await adapter.start()
