"""
Phase 2-B: Token Validator Tests
Tests for enriched ValidationResult fields: bot_username, bot_id, error_category.
"""
import json
import urllib.error
from unittest.mock import patch, MagicMock

from src.setup.validator import validate_telegram_token, validate_discord_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(body: bytes, status: int = 200):
    """Create a mock urllib response context manager."""
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = body
    mock.status = status
    return mock


_VALID_TG_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefgh"


# ---------------------------------------------------------------------------
# Telegram — valid token
# ---------------------------------------------------------------------------

def test_telegram_valid_returns_bot_username():
    body = json.dumps({
        "ok": True,
        "result": {"id": 987654321, "username": "MyAwesomeBot", "is_bot": True},
    }).encode()
    resp = _make_response(body)
    with patch("urllib.request.urlopen", return_value=resp):
        result = validate_telegram_token(_VALID_TG_TOKEN)

    assert result.valid is True
    assert result.bot_username == "MyAwesomeBot"
    assert result.bot_id == 987654321
    assert result.error_category is None


def test_telegram_valid_bot_id_populated():
    body = json.dumps({
        "ok": True,
        "result": {"id": 111222333, "username": "AnotherBot"},
    }).encode()
    resp = _make_response(body)
    with patch("urllib.request.urlopen", return_value=resp):
        result = validate_telegram_token(_VALID_TG_TOKEN)

    assert result.valid is True
    assert result.bot_id == 111222333


# ---------------------------------------------------------------------------
# Telegram — 401 auth error
# ---------------------------------------------------------------------------

def test_telegram_401_sets_auth_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 401, "Unauthorized", {}, None),
    ):
        result = validate_telegram_token(_VALID_TG_TOKEN)

    assert result.valid is False
    assert result.error_category == "auth"
    assert result.bot_username is None


# ---------------------------------------------------------------------------
# Telegram — network error
# ---------------------------------------------------------------------------

def test_telegram_network_error_sets_network_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        result = validate_telegram_token(_VALID_TG_TOKEN)

    assert result.error_category == "network"
    # skipped=True means the wizard will save the token without hard-failing
    assert result.skipped is True


# ---------------------------------------------------------------------------
# Telegram — rate limit (429)
# ---------------------------------------------------------------------------

def test_telegram_429_sets_rate_limit_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None),
    ):
        result = validate_telegram_token(_VALID_TG_TOKEN)

    assert result.valid is False
    assert result.error_category == "rate_limit"


# ---------------------------------------------------------------------------
# Discord — valid token
# ---------------------------------------------------------------------------

def test_discord_valid_returns_bot_username():
    body = json.dumps({"id": "555666777", "username": "DiscordAwesomeBot"}).encode()
    resp = _make_response(body, status=200)
    with patch("urllib.request.urlopen", return_value=resp):
        result = validate_discord_token("valid.discord.token")

    assert result.valid is True
    assert result.bot_username == "DiscordAwesomeBot"
    assert result.bot_id == 555666777
    assert result.error_category is None


def test_discord_valid_bot_id_is_int():
    body = json.dumps({"id": "999888777", "username": "IntBot"}).encode()
    resp = _make_response(body, status=200)
    with patch("urllib.request.urlopen", return_value=resp):
        result = validate_discord_token("valid.discord.token")

    assert isinstance(result.bot_id, int)
    assert result.bot_id == 999888777


# ---------------------------------------------------------------------------
# Discord — 401 auth error
# ---------------------------------------------------------------------------

def test_discord_401_sets_auth_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 401, "Unauthorized", {}, None),
    ):
        result = validate_discord_token("bad-token")

    assert result.valid is False
    assert result.error_category == "auth"
    assert result.bot_username is None


# ---------------------------------------------------------------------------
# Discord — network error
# ---------------------------------------------------------------------------

def test_discord_network_error_sets_network_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("timeout"),
    ):
        result = validate_discord_token("some-token")

    assert result.error_category == "network"
    assert result.skipped is True


# ---------------------------------------------------------------------------
# Discord — rate limit (429)
# ---------------------------------------------------------------------------

def test_discord_429_sets_rate_limit_category():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None),
    ):
        result = validate_discord_token("some-token")

    assert result.valid is False
    assert result.error_category == "rate_limit"
