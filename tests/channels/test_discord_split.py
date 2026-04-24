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
