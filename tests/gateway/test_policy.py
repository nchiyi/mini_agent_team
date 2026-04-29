"""Sanity tests for the extracted policy module.

The full behaviour matrix is covered in tests/channels/test_telegram_policy.py
(inherited from B-2 Task 6); these tests just verify the symbol is reachable
from the new gateway location.
"""
from src.channels.base import InboundMessage
from src.core.bots import BotConfig
from src.gateway.bot_turns import BotTurnTracker
from src.gateway.policy import should_handle


def _msg(*, channel="telegram", chat_id=-100, mentioned_bot_ids=None,
         message_id=None, from_bot=False, chat_type="supergroup", **overrides):
    base = dict(
        user_id=1, channel=channel, text="hi",
        message_id=message_id if message_id is not None else "1",
        bot_id="dev", chat_id=chat_id, chat_type=chat_type,
        mentioned_bot_ids=list(mentioned_bot_ids or []), from_bot=from_bot,
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


def test_group_message_id_processed_once_across_multiple_bots():
    turns = BotTurnTracker()
    dev = _cfg(id="dev", allow_all_groups=True)
    codex = _cfg(id="codex", allow_all_groups=True)
    msg = _msg(message_id="42", mentioned_bot_ids=["dev", "codex"])

    assert should_handle(msg, dev, turns=turns) is True
    assert should_handle(msg, codex, turns=turns) is False


def test_group_different_message_ids_each_process():
    turns = BotTurnTracker()
    cfg = _cfg(id="dev", allow_all_groups=True)

    assert should_handle(_msg(message_id="42", mentioned_bot_ids=["dev"]), cfg, turns=turns) is True
    assert should_handle(_msg(message_id="43", mentioned_bot_ids=["dev"]), cfg, turns=turns) is True


def test_group_empty_message_id_keeps_per_bot_policy():
    turns = BotTurnTracker()
    dev = _cfg(id="dev", allow_all_groups=True)
    codex = _cfg(id="codex", allow_all_groups=True)
    msg = _msg(message_id="", mentioned_bot_ids=["dev", "codex"])

    assert should_handle(msg, dev, turns=turns) is True
    assert should_handle(msg, codex, turns=turns) is True


def test_re_export_from_telegram_runner_still_works():
    """Backward compat: telegram_runner._should_handle still resolves to same function."""
    from src.channels.telegram_runner import _should_handle
    from src.gateway.policy import should_handle as canonical
    assert _should_handle is canonical


def test_bot_to_bot_turn_cap_uses_inbound_channel_not_hardcoded_telegram():
    """Regression: cap_reached() must look up the right channel bucket."""
    turns = BotTurnTracker(cap=1)
    # 把 telegram 桶填滿到 cap
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    cfg = _cfg(id="dev", allow_all_groups=True, allow_bot_messages="all")
    # discord 訊息進來，cap_reached 應查 discord 桶（空），故 should_handle == True
    msg = _msg(
        channel="discord",
        chat_id=-100,
        from_bot=True,
        mentioned_bot_ids=["dev"],
        message_id="42",
    )
    assert should_handle(msg, cfg, turns=turns) is True
