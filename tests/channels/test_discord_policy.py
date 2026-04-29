"""Discord-specific policy integration: claim_message dedup across bots."""
from dataclasses import replace

import pytest
from unittest.mock import MagicMock

from src.channels.base import InboundMessage
from src.channels.discord_runner import _make_gateway_handler
from src.core.bots import BotConfig
from src.gateway.bot_turns import BotTurnTracker


def _ctx(turns):
    ctx = MagicMock()
    ctx.bot_turns = turns
    return ctx


def _msg(*, message_id, mentioned, bot_id="x"):
    return InboundMessage(
        user_id=1, channel="discord", text="@all hi",
        message_id=message_id, attachments=[], bot_id=bot_id,
        chat_id=-100, chat_type="text",
        mentioned_bot_ids=mentioned, from_bot=False,
        reply_to_message_id=None, reply_to_user_id=None,
    )


@pytest.mark.asyncio
async def test_two_discord_bots_same_message_id_only_first_dispatches():
    turns = BotTurnTracker()
    dev = BotConfig(id="dev_dc", channel="discord", allow_all_groups=True)
    ops = BotConfig(id="ops_dc", channel="discord", allow_all_groups=True)

    dispatched = []
    async def fake_dispatch(*args, **kwargs):
        dispatched.append(args[0].bot_id)

    base = _msg(message_id="42", mentioned=["dev_dc", "ops_dc"])
    # Mirror what each adapter does in production: stamp inbound.bot_id with
    # its own bot_cfg.id before handing the message to its gateway_handler.
    msg_dev = replace(base, bot_id="dev_dc")
    msg_ops = replace(base, bot_id="ops_dc")

    h_dev = _make_gateway_handler(
        ctx=_ctx(turns), bot_cfg=dev, adapter=MagicMock(),
        bridges={}, dispatch_fn=fake_dispatch,
    )
    h_ops = _make_gateway_handler(
        ctx=_ctx(turns), bot_cfg=ops, adapter=MagicMock(),
        bridges={}, dispatch_fn=fake_dispatch,
    )
    await h_dev(msg_dev)
    await h_ops(msg_ops)
    assert dispatched == ["dev_dc"]
