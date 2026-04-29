"""bot_prompts.collect_bot — interactive single-bot config helper."""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_collect_bot_minimal_telegram(monkeypatch):
    """Happy path: user supplies just token + id; defaults fill the rest."""
    from src.setup.bot_prompts import collect_bot

    prompts = iter([
        "fake_token",   # token
        "dev",          # id
        "",             # label (default)
        "",             # default_runner (default = wizard's default)
        "",             # default_role
        "n",            # allow_all_groups
        "",             # allowed_chat_ids
        "off",          # allow_bot_messages
    ])
    monkeypatch.setattr(
        "src.setup.bot_prompts._prompt", lambda *a, **kw: next(prompts),
    )
    with patch("src.setup.bot_prompts.validate_telegram_token") as v:
        v.return_value = type("R", (), {
            "valid": True, "skipped": False, "bot_username": "dev_bot", "bot_id": 1,
        })()
        bot = await collect_bot(channel="telegram", default_runner="claude")

    assert bot["id"] == "dev"
    assert bot["channel"] == "telegram"
    assert bot["token_env"] == "BOT_DEV_TOKEN"
    assert bot["_token_value"] == "fake_token"  # secret carrier; written to .env in step_8
    assert bot.get("allow_all_groups") is False or "allow_all_groups" not in bot
    assert bot.get("allow_bot_messages", "off") == "off"


@pytest.mark.asyncio
async def test_collect_bot_with_groups(monkeypatch):
    """Group settings: allow_all_groups=true OR allowed_chat_ids=[…]."""
    from src.setup.bot_prompts import collect_bot

    prompts = iter([
        "tok", "ops", "",  "claude", "",
        "y",                        # allow_all_groups
        "",                         # allowed_chat_ids skipped because allow_all_groups
        "mentions",                 # allow_bot_messages
    ])
    monkeypatch.setattr("src.setup.bot_prompts._prompt", lambda *a, **kw: next(prompts))
    with patch("src.setup.bot_prompts.validate_telegram_token") as v:
        v.return_value = type("R", (), {"valid": True, "skipped": False, "bot_username": "ops_bot", "bot_id": 2})()
        bot = await collect_bot(channel="telegram", default_runner="claude")

    assert bot["allow_all_groups"] is True
    assert "allowed_chat_ids" not in bot or bot["allowed_chat_ids"] == []
    assert bot["allow_bot_messages"] == "mentions"


@pytest.mark.asyncio
async def test_collect_bot_with_allowed_chat_ids(monkeypatch):
    from src.setup.bot_prompts import collect_bot

    prompts = iter([
        "tok", "support", "", "claude", "",
        "n",                            # not allow_all_groups
        "-1001234, -1005678",           # allowed_chat_ids
        "off",
    ])
    monkeypatch.setattr("src.setup.bot_prompts._prompt", lambda *a, **kw: next(prompts))
    with patch("src.setup.bot_prompts.validate_telegram_token") as v:
        v.return_value = type("R", (), {"valid": True, "skipped": False, "bot_username": "support_bot", "bot_id": 3})()
        bot = await collect_bot(channel="telegram", default_runner="claude")

    assert bot["allowed_chat_ids"] == [-1001234, -1005678]


@pytest.mark.asyncio
async def test_collect_bot_id_must_be_slug(monkeypatch):
    """Reject ids that don't fit BOT_<ID>_TOKEN naming."""
    from src.setup.bot_prompts import collect_bot

    prompts = iter([
        "tok",
        "has space!",   # rejected
        "ok-id",        # rejected (dash)
        "ok_id",        # accepted
        "", "claude", "", "n", "", "off",
    ])
    monkeypatch.setattr("src.setup.bot_prompts._prompt", lambda *a, **kw: next(prompts))
    with patch("src.setup.bot_prompts.validate_telegram_token") as v:
        v.return_value = type("R", (), {"valid": True, "skipped": False, "bot_username": "x", "bot_id": 1})()
        bot = await collect_bot(channel="telegram", default_runner="claude")

    assert bot["id"] == "ok_id"
    assert bot["token_env"] == "BOT_OK_ID_TOKEN"
