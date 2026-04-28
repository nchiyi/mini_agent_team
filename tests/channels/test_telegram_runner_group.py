"""B-2 Task 5: helper extracts chat_id / chat_type / mentions / from_bot."""
from unittest.mock import MagicMock

from src.gateway.bot_registry import BotRegistry


def _fake_update(*, chat_id, chat_type, text, user_id=99,
                 mentions=None, is_bot=False, reply_to=None,
                 message_id=1, caption=None):
    """Build a MagicMock that quacks like a python-telegram-bot Update.

    `mentions` is list of (offset, length) tuples; the mention text is
    sliced from `text` at runtime.
    """
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.effective_user.is_bot = is_bot
    upd.message.message_id = message_id
    upd.message.text = text
    upd.message.caption = caption
    upd.message.chat.id = chat_id
    upd.message.chat.type = chat_type
    upd.message.from_user.id = user_id
    upd.message.from_user.is_bot = is_bot
    if mentions:
        ents = []
        for offset, length in mentions:
            ent = MagicMock()
            ent.type = "mention"
            ent.offset = offset
            ent.length = length
            ents.append(ent)
        upd.message.entities = ents
    else:
        upd.message.entities = []
    upd.message.reply_to_message = reply_to
    return upd


def test_extracts_chat_id_and_type():
    from src.channels.telegram_runner import _build_inbound_from_update
    upd = _fake_update(chat_id=-100123, chat_type="supergroup", text="hi")
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert inbound.chat_id == -100123
    assert inbound.chat_type == "supergroup"
    assert inbound.from_bot is False
    assert inbound.mentioned_bot_ids == []
    assert inbound.bot_id == "dev"


def test_dm_chat_type():
    from src.channels.telegram_runner import _build_inbound_from_update
    upd = _fake_update(chat_id=99, chat_type="private", text="hi")
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert inbound.chat_type == "private"
    assert inbound.chat_id == 99


def test_parses_mentions_via_registry():
    from src.channels.telegram_runner import _build_inbound_from_update
    text = "@user_dev_bot please review"
    reg = BotRegistry()
    reg.register(channel="telegram", username="user_dev_bot", bot_id="dev")
    upd = _fake_update(chat_id=-100123, chat_type="supergroup", text=text,
                       mentions=[(0, len("@user_dev_bot"))])
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=reg)
    assert inbound.mentioned_bot_ids == ["dev"]


def test_unknown_mention_dropped():
    """A @username not in the registry should NOT contribute to mentioned_bot_ids."""
    from src.channels.telegram_runner import _build_inbound_from_update
    text = "@stranger_bot hello"
    reg = BotRegistry()
    upd = _fake_update(chat_id=-100123, chat_type="supergroup", text=text,
                       mentions=[(0, len("@stranger_bot"))])
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=reg)
    assert inbound.mentioned_bot_ids == []


def test_multiple_mentions_distinct():
    from src.channels.telegram_runner import _build_inbound_from_update
    text = "@dev_bot and @search_bot please discuss"
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="search_bot", bot_id="search")
    upd = _fake_update(
        chat_id=-100123, chat_type="supergroup", text=text,
        mentions=[(0, len("@dev_bot")), (13, len("@search_bot"))],
    )
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=reg)
    assert set(inbound.mentioned_bot_ids) == {"dev", "search"}


def test_marks_from_bot_when_sender_is_bot():
    from src.channels.telegram_runner import _build_inbound_from_update
    upd = _fake_update(chat_id=-100123, chat_type="group", text="hi", is_bot=True)
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert inbound.from_bot is True


def test_extracts_reply_to_message():
    from src.channels.telegram_runner import _build_inbound_from_update
    reply = MagicMock()
    reply.message_id = 50
    reply.from_user.id = 12345
    upd = _fake_update(chat_id=-100, chat_type="group", text="answer", reply_to=reply)
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert inbound.reply_to_message_id == "50"
    assert inbound.reply_to_user_id == 12345


def test_no_reply_yields_none_fields():
    from src.channels.telegram_runner import _build_inbound_from_update
    upd = _fake_update(chat_id=-100, chat_type="group", text="hi")
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert inbound.reply_to_message_id is None
    assert inbound.reply_to_user_id is None


def test_caption_used_when_text_missing():
    """Telegram messages with attachments may have caption instead of text."""
    from src.channels.telegram_runner import _build_inbound_from_update
    upd = _fake_update(
        chat_id=-100, chat_type="group", text=None, caption="photo caption",
    )
    inbound = _build_inbound_from_update(upd, bot_id="dev", registry=BotRegistry())
    assert "photo caption" in inbound.text


def test_at_all_expansion_skipped_when_flag_off():
    """A bot with respond_to_at_all=False ignores @all even in authorised group."""
    from src.channels.base import InboundMessage
    from src.channels.telegram_runner import _maybe_expand_at_all
    from src.core.bots import BotConfig
    from src.gateway.bot_registry import BotRegistry
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="codex_bot", bot_id="codex")
    bot_cfg = BotConfig(id="dev", respond_to_at_all=False)
    inbound = InboundMessage(
        user_id=1, channel="telegram", text="@all please discuss",
        message_id="1", bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=[],
    )
    out = _maybe_expand_at_all(inbound, bot_cfg, reg)
    assert out.mentioned_bot_ids == []   # untouched


def test_at_all_expansion_applied_when_flag_on():
    from src.channels.base import InboundMessage
    from src.channels.telegram_runner import _maybe_expand_at_all
    from src.core.bots import BotConfig
    from src.gateway.bot_registry import BotRegistry
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="codex_bot", bot_id="codex")
    bot_cfg = BotConfig(id="dev", respond_to_at_all=True)
    inbound = InboundMessage(
        user_id=1, channel="telegram", text="@all please discuss",
        message_id="1", bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=[],
    )
    out = _maybe_expand_at_all(inbound, bot_cfg, reg)
    assert set(out.mentioned_bot_ids) == {"dev", "codex"}


def test_at_all_no_change_when_text_lacks_pattern():
    from src.channels.base import InboundMessage
    from src.channels.telegram_runner import _maybe_expand_at_all
    from src.core.bots import BotConfig
    from src.gateway.bot_registry import BotRegistry
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    bot_cfg = BotConfig(id="dev", respond_to_at_all=True)
    inbound = InboundMessage(
        user_id=1, channel="telegram", text="just hi @dev_bot",
        message_id="1", bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=["dev"],
    )
    out = _maybe_expand_at_all(inbound, bot_cfg, reg)
    assert out.mentioned_bot_ids == ["dev"]
