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


def test_discord_is_authorized_empty_allowlist():
    from src.channels.discord_adapter import DiscordAdapter
    # Empty allowlist → everyone allowed
    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._allowed = set()
    assert adapter.is_authorized(12345) is True


def test_discord_is_authorized_with_allowlist():
    from src.channels.discord_adapter import DiscordAdapter
    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._allowed = {111, 222}
    assert adapter.is_authorized(111) is True
    assert adapter.is_authorized(999) is False
