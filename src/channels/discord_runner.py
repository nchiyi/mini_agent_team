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
from src.gateway.dispatcher import dispatch as _default_dispatch
from src.gateway.policy import should_handle
from src.gateway.streaming import StreamingBridge

if TYPE_CHECKING:
    from src.core.bots import BotConfig
    from src.gateway.app_context import AppContext

logger = logging.getLogger(__name__)


def _make_gateway_handler(
    *, ctx, bot_cfg, adapter, bridges: dict, dispatch_fn=_default_dispatch,
):
    """Build the per-bot gateway_handler closure.

    Pulled out so it's directly testable without spinning a Discord client.
    """
    cfg = ctx.cfg

    async def gateway_handler(inbound):
        if not should_handle(inbound, bot_cfg, ctx.bot_turns):
            return

        if inbound.chat_type != "private" and inbound.chat_id is not None:
            if inbound.from_bot:
                ctx.bot_turns.note_bot_turn(
                    channel=inbound.channel, chat_id=inbound.chat_id,
                )
            else:
                ctx.bot_turns.reset_on_human(
                    channel=inbound.channel, chat_id=inbound.chat_id,
                )

        if inbound.user_id not in bridges:
            bridges[inbound.user_id] = StreamingBridge(
                adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds,
            )
        bridge = bridges[inbound.user_id]
        await dispatch_fn(
            inbound, bridge, ctx.session_mgr, ctx.router, ctx.runners,
            ctx.tier1, ctx.tier3, ctx.assembler,
            lambda t: adapter.send(inbound.user_id, t),
            recent_turns=cfg.memory.tier3_context_turns,
            module_registry=ctx.module_registry,
            cfg=cfg,
            nlu_detector=ctx.nlu_detector,
            rate_limiter=ctx.rate_limiter,
        )

    return gateway_handler


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

    # Closure ordering: DiscordAdapter requires gateway_handler at construction
    # time, but the handler must reference the adapter (for .send and
    # StreamingBridge). Resolve via a thin proxy + late binding — same trick
    # the legacy main.run_discord used. The proxy forwards attribute access
    # to the real adapter once it's been built and stored in adapter_ref.
    bridges: dict = {}
    adapter_ref: list = [None]

    class _AdapterProxy:
        def __getattr__(self, name):
            return getattr(adapter_ref[0], name)

    gateway_handler = _make_gateway_handler(
        ctx=ctx, bot_cfg=bot_cfg, adapter=_AdapterProxy(), bridges=bridges,
    )

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
    adapter_ref[0] = adapter
    logger.info("Discord bot %s starting", bot_cfg.id)
    await adapter.start()
