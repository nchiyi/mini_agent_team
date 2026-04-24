import urllib.error
from unittest.mock import patch, MagicMock
from src.setup.validator import validate_telegram_token, validate_discord_token


def _make_mock_response(body: bytes, status: int = 200):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = body
    mock.status = status
    return mock


def test_validate_telegram_token_valid():
    resp = _make_mock_response(b'{"ok": true, "result": {"id": 123}}')
    # token format must pass regex before network call
    valid_fmt = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefgh"
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token(valid_fmt).valid is True


def test_validate_telegram_token_ok_false():
    resp = _make_mock_response(b'{"ok": false}')
    valid_fmt = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefgh"
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token(valid_fmt).valid is False


def test_validate_telegram_token_network_error():
    valid_fmt = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefgh"
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        result = validate_telegram_token(valid_fmt)
        assert result.skipped is True


def test_validate_telegram_token_bad_json():
    resp = _make_mock_response(b"not-json")
    valid_fmt = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefgh"
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_telegram_token(valid_fmt).skipped is True


def test_validate_discord_token_valid():
    resp = _make_mock_response(b'{"id": "123"}', status=200)
    with patch("urllib.request.urlopen", return_value=resp):
        assert validate_discord_token("valid-token").valid is True


def test_validate_discord_token_unauthorized():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(None, 401, "Unauthorized", {}, None),
    ):
        assert validate_discord_token("bad-token").valid is False


def test_validate_discord_token_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert validate_discord_token("token").skipped is True
