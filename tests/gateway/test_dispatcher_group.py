"""B-2 Task 8: chat_id passthrough + @all expansion."""
from src.channels.base import InboundMessage
from src.gateway.bot_registry import BotRegistry
from src.gateway.dispatcher import _expand_at_all, _AT_ALL_RE


def _msg(**overrides):
    base = dict(
        user_id=1, channel="telegram", text="hi", message_id="1",
        bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=[],
    )
    base.update(overrides)
    return InboundMessage(**base)


def test_at_all_regex_matches_variants():
    assert _AT_ALL_RE.search("hello @all")
    assert _AT_ALL_RE.search("@everyone please")
    assert _AT_ALL_RE.search("@大家 起來討論")
    assert _AT_ALL_RE.search("@ALL")
    assert _AT_ALL_RE.search(" @all ")


def test_at_all_regex_does_not_match_words_with_at_inside():
    assert not _AT_ALL_RE.search("contact@all-hands.com")
    assert not _AT_ALL_RE.search("call_all_users")
    assert not _AT_ALL_RE.search("recall")


def test_expand_at_all_returns_all_registered_when_pattern_present():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="codex_bot", bot_id="codex")
    reg.register(channel="telegram", username="search_bot", bot_id="search")
    inbound = _msg(text="@all 比較兩個方案", mentioned_bot_ids=[])
    expanded = _expand_at_all(inbound, reg)
    assert set(expanded) == {"dev", "codex", "search"}


def test_expand_at_all_passes_through_when_no_pattern():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="codex_bot", bot_id="codex")
    inbound = _msg(text="hello @dev_bot", mentioned_bot_ids=["dev"])
    expanded = _expand_at_all(inbound, reg)
    assert expanded == ["dev"]


def test_expand_at_all_returns_empty_when_pattern_but_no_registered_bots():
    reg = BotRegistry()
    inbound = _msg(text="@all anyone there?", mentioned_bot_ids=[])
    expanded = _expand_at_all(inbound, reg)
    assert expanded == []


def test_expand_at_all_uses_inbound_channel():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="discord", username="other_bot", bot_id="other")
    inbound = _msg(text="@all", channel="telegram", mentioned_bot_ids=[])
    expanded = _expand_at_all(inbound, reg)
    assert expanded == ["dev"]
