# tests/channels/test_discord_split.py
import pytest


def test_discord_split_long_message():
    from src.channels.discord_adapter import DiscordAdapter
    text = "a" * 2500
    chunks = DiscordAdapter._split(text)
    assert len(chunks) == 2
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == text


def test_discord_split_short_message():
    from src.channels.discord_adapter import DiscordAdapter
    text = "hello world"
    chunks = DiscordAdapter._split(text)
    assert chunks == ["hello world"]


def test_discord_split_at_newline():
    from src.channels.discord_adapter import DiscordAdapter
    # A line just under 2000 chars, then a newline, then more text
    text = ("a" * 1999) + "\n" + ("b" * 100)
    chunks = DiscordAdapter._split(text)
    assert len(chunks) == 2
    assert chunks[0].endswith("a")
    assert "b" in chunks[1]


def test_discord_is_authorized_empty_allowlist_denies_all():
    from src.channels.auth import AuthPolicy
    # Empty allowlist without allow_all_users → conservative: deny all
    policy = AuthPolicy(allowed_user_ids=[], allow_all_users=False)
    assert policy.is_authorized(12345) is False
    assert policy.mode == "unset"


def test_discord_is_authorized_allow_all_users():
    from src.channels.auth import AuthPolicy
    # allow_all_users=True overrides empty allowlist
    policy = AuthPolicy(allowed_user_ids=[], allow_all_users=True)
    assert policy.is_authorized(12345) is True
    assert policy.mode == "open"


def test_discord_is_authorized_with_allowlist():
    from src.channels.auth import AuthPolicy
    policy = AuthPolicy(allowed_user_ids=[111, 222])
    assert policy.is_authorized(111) is True
    assert policy.is_authorized(999) is False
    assert policy.mode == "strict"


# ─── B-2 Task 9: InboundMessage builder ──────────────────────────────────

from unittest.mock import MagicMock


def _fake_discord_message(*, channel_id, channel_type="text", text="hi",
                          author_id=99, author_is_bot=False, message_id=1,
                          mentions=None, reference=None):
    msg = MagicMock()
    msg.id = message_id
    msg.content = text
    msg.author.id = author_id
    msg.author.bot = author_is_bot
    msg.channel.id = channel_id
    # discord.ChannelType.text → str like "text"; we mock the enum's .name access
    ch_type = MagicMock()
    ch_type.name = channel_type
    msg.channel.type = ch_type
    msg.mentions = []
    if mentions:
        for uid, uname, is_bot in mentions:
            u = MagicMock()
            u.id = uid
            u.name = uname
            u.bot = is_bot
            msg.mentions.append(u)
    msg.reference = None
    if reference:
        msg.reference = MagicMock()
        msg.reference.message_id = reference
    return msg


def test_discord_inbound_carries_chat_id_and_type():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    msg = _fake_discord_message(channel_id=12345, channel_type="text", text="hi")
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=BotRegistry(),
    )
    assert inbound.chat_id == 12345
    assert inbound.chat_type == "text"
    assert inbound.user_id == 99
    assert inbound.from_bot is False
    assert inbound.bot_id == "default"


def test_discord_inbound_resolves_mentioned_bots_via_registry():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    reg = BotRegistry()
    reg.register(channel="discord", username="dev_bot", bot_id="dev")
    reg.register(channel="discord", username="codex_bot", bot_id="codex")
    msg = _fake_discord_message(
        channel_id=12345, text="hi everyone",
        mentions=[
            (1001, "dev_bot", True),
            (1002, "codex_bot", True),
            (2001, "human_user", False),  # human mention — must NOT contribute
        ],
    )
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=reg,
    )
    assert set(inbound.mentioned_bot_ids) == {"dev", "codex"}


def test_discord_inbound_drops_unknown_bot_mention():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    reg = BotRegistry()
    msg = _fake_discord_message(
        channel_id=1, text="hi @stranger",
        mentions=[(99, "stranger_bot", True)],
    )
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=reg,
    )
    assert inbound.mentioned_bot_ids == []


def test_discord_inbound_marks_from_bot():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    msg = _fake_discord_message(channel_id=1, author_is_bot=True)
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=BotRegistry(),
    )
    assert inbound.from_bot is True


def test_discord_inbound_extracts_reply_to():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    msg = _fake_discord_message(channel_id=1, reference=88888)
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=BotRegistry(),
    )
    assert inbound.reply_to_message_id == "88888"


def test_discord_inbound_dm_chat_type():
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    msg = _fake_discord_message(channel_id=42, channel_type="private", text="hi DM")
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=[], registry=BotRegistry(),
    )
    assert inbound.chat_type == "private"
    assert inbound.chat_id == 42


def test_discord_inbound_attachments_round_trip():
    """Attachments are caller-supplied, not extracted from message."""
    from src.channels.discord_adapter import DiscordAdapter
    from src.gateway.bot_registry import BotRegistry
    msg = _fake_discord_message(channel_id=1, text="see file")
    inbound = DiscordAdapter._build_inbound_from_message(
        msg, attachments=["/tmp/a.png", "/tmp/b.pdf"], registry=BotRegistry(),
    )
    assert inbound.attachments == ["/tmp/a.png", "/tmp/b.pdf"]
