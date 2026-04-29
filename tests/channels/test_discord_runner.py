import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.bot_registry import BotRegistry


@pytest.mark.asyncio
async def test_run_discord_for_bot_registers_username_on_ready(monkeypatch):
    """Each Discord bot registers (channel='discord', username, bot_id) at startup."""
    from src.channels.discord_runner import run_discord_for_bot
    from src.core.bots import BotConfig

    monkeypatch.setenv("BOT_DEV_DC_TOKEN", "fake")
    bot_cfg = BotConfig(
        id="dev_dc", channel="discord", token_env="BOT_DEV_DC_TOKEN",
    )

    registry = BotRegistry()

    # 假 ctx
    ctx = MagicMock()
    ctx.bot_registry = registry
    ctx.cfg.discord.allowed_user_ids = []
    ctx.cfg.discord.allow_all_users = True
    ctx.cfg.discord.allow_bot_messages = "off"
    ctx.cfg.discord.allow_user_messages = "all"
    ctx.cfg.discord.allowed_channel_ids = None
    ctx.cfg.discord.trusted_bot_ids = None
    ctx.cfg.allowed_user_ids = []
    ctx.cfg.allow_all_users = True

    # mock DiscordAdapter 不真的連線；改寫 start() 為觸發 on_ready 後立即返回
    fake_user = MagicMock(); fake_user.name = "dev_bot"; fake_user.id = 999
    with patch("src.channels.discord_runner.DiscordAdapter") as adapter_cls:
        adapter = MagicMock()
        adapter.start = AsyncMock()
        adapter._client = MagicMock(); adapter._client.user = fake_user
        adapter._maybe_register_self = lambda: registry.register(
            channel="discord", username="dev_bot", bot_id="dev_dc",
        )
        adapter_cls.return_value = adapter

        # 模擬：start() 被 await 之後 adapter 主動觸發 register
        async def fake_start():
            adapter._maybe_register_self()
        adapter.start.side_effect = fake_start

        await run_discord_for_bot(ctx, bot_cfg)

    assert registry.resolve(channel="discord", username="dev_bot") == "dev_dc"


@pytest.mark.asyncio
async def test_gateway_handler_drops_inbound_when_should_handle_false(monkeypatch):
    """Inbound for a group not in allowlist is filtered before dispatch()."""
    from src.channels.discord_runner import _make_gateway_handler
    from src.channels.base import InboundMessage
    from src.core.bots import BotConfig
    from src.gateway.bot_turns import BotTurnTracker

    bot_cfg = BotConfig(
        id="dev_dc", channel="discord",
        allow_all_groups=False, allowed_chat_ids=[123],  # -100 not allowed
    )
    ctx = MagicMock()
    ctx.bot_turns = BotTurnTracker()

    dispatch_calls = []
    async def fake_dispatch(*args, **kwargs):
        dispatch_calls.append(args)

    handler = _make_gateway_handler(
        ctx=ctx, bot_cfg=bot_cfg, adapter=MagicMock(),
        bridges={}, dispatch_fn=fake_dispatch,
    )
    inbound = InboundMessage(
        user_id=1, channel="discord", text="hi", message_id="42",
        attachments=[], bot_id="dev_dc", chat_id=-100, chat_type="text",
        mentioned_bot_ids=["dev_dc"], from_bot=False,
        reply_to_message_id=None, reply_to_user_id=None,
    )
    await handler(inbound)
    assert dispatch_calls == []


@pytest.mark.asyncio
async def test_gateway_handler_calls_dispatch_when_should_handle_true(monkeypatch):
    from src.channels.discord_runner import _make_gateway_handler
    from src.channels.base import InboundMessage
    from src.core.bots import BotConfig
    from src.gateway.bot_turns import BotTurnTracker

    bot_cfg = BotConfig(id="dev_dc", channel="discord", allow_all_groups=True)
    ctx = MagicMock()
    ctx.bot_turns = BotTurnTracker()

    dispatch_calls = []
    async def fake_dispatch(*args, **kwargs):
        dispatch_calls.append(args)

    handler = _make_gateway_handler(
        ctx=ctx, bot_cfg=bot_cfg, adapter=MagicMock(),
        bridges={}, dispatch_fn=fake_dispatch,
    )
    inbound = InboundMessage(
        user_id=1, channel="discord", text="hi", message_id="42",
        attachments=[], bot_id="dev_dc", chat_id=-100, chat_type="text",
        mentioned_bot_ids=["dev_dc"], from_bot=False,
        reply_to_message_id=None, reply_to_user_id=None,
    )
    await handler(inbound)
    assert len(dispatch_calls) == 1
