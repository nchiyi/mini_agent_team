"""Group-chat metadata on InboundMessage (B-2 Task 1)."""
from src.channels.base import InboundMessage


def test_inbound_message_group_fields_default_to_dm():
    m = InboundMessage(user_id=1, channel="telegram", text="hi", message_id="1")
    assert m.chat_id is None
    assert m.chat_type == "private"
    assert m.mentioned_bot_ids == []
    assert m.from_bot is False
    assert m.reply_to_message_id is None
    assert m.reply_to_user_id is None


def test_inbound_message_group_fields_settable():
    m = InboundMessage(
        user_id=1, channel="telegram", text="hey @dev", message_id="m1",
        chat_id=-100123, chat_type="supergroup",
        mentioned_bot_ids=["dev"], from_bot=False,
        reply_to_message_id="m0", reply_to_user_id=42,
    )
    assert m.chat_id == -100123
    assert m.chat_type == "supergroup"
    assert m.mentioned_bot_ids == ["dev"]
    assert m.from_bot is False
    assert m.reply_to_message_id == "m0"
    assert m.reply_to_user_id == 42


def test_inbound_message_from_bot_true():
    m = InboundMessage(
        user_id=1, channel="telegram", text="auto reply", message_id="m1",
        from_bot=True,
    )
    assert m.from_bot is True


def test_inbound_message_b1_bot_id_field_still_works():
    """Sanity check: B-1's bot_id default coexists with B-2's new fields."""
    m = InboundMessage(user_id=1, channel="telegram", text="hi", message_id="1")
    assert m.bot_id == "default"
    m2 = InboundMessage(user_id=1, channel="telegram", text="hi", message_id="1",
                        bot_id="dev", chat_id=-100, chat_type="supergroup")
    assert m2.bot_id == "dev"
    assert m2.chat_id == -100
