"""Sanity tests for the extracted policy module.

The full behaviour matrix is covered in tests/channels/test_telegram_policy.py
(inherited from B-2 Task 6); these tests just verify the symbol is reachable
from the new gateway location.
"""
from src.channels.base import InboundMessage
from src.core.bots import BotConfig
from src.gateway.policy import should_handle


def _msg(**overrides):
    base = dict(
        user_id=1, channel="telegram", text="hi", message_id="1",
        bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=[], from_bot=False,
    )
    base.update(overrides)
    return InboundMessage(**base)


def _cfg(**overrides):
    base = dict(id="dev", channel="telegram", token_env="BOT_DEV_TOKEN",
                allow_bot_messages="off", allow_all_groups=False, allowed_chat_ids=None)
    base.update(overrides)
    return BotConfig(**base)


def test_dm_always_passes():
    assert should_handle(_msg(chat_id=1, chat_type="private"), _cfg(), turns=None) is True


def test_group_dropped_when_unauthorized_and_unmentioned():
    assert should_handle(_msg(), _cfg(), turns=None) is False


def test_group_authorised_human_must_mention():
    cfg = _cfg(allow_all_groups=True)
    assert should_handle(_msg(mentioned_bot_ids=["dev"]), cfg, turns=None) is True
    assert should_handle(_msg(mentioned_bot_ids=[]), cfg, turns=None) is False


def test_re_export_from_telegram_runner_still_works():
    """Backward compat: telegram_runner._should_handle still resolves to same function."""
    from src.channels.telegram_runner import _should_handle
    from src.gateway.policy import should_handle as canonical
    assert _should_handle is canonical
