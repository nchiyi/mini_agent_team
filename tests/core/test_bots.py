import os
import pytest
from src.core.bots import BotConfig, load_bots


def test_legacy_env_only_yields_one_default_bot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "12345:legacy_token")
    bots = load_bots(raw_toml={}, default_runner="claude")
    assert len(bots) == 1
    assert bots[0].id == "default"
    assert bots[0].token_env == "TELEGRAM_BOT_TOKEN"
    assert bots[0].token == "12345:legacy_token"
    assert bots[0].default_runner == "claude"


def test_explicit_bots_section(monkeypatch):
    monkeypatch.setenv("BOT_DEV_TOKEN", "11111:dev")
    monkeypatch.setenv("BOT_SEARCH_TOKEN", "22222:search")
    raw = {
        "bots": {
            "dev": {"token_env": "BOT_DEV_TOKEN", "default_runner": "claude",
                    "default_role": "fullstack-dev"},
            "search": {"token_env": "BOT_SEARCH_TOKEN", "default_runner": "gemini",
                       "default_role": "researcher"},
        }
    }
    bots = load_bots(raw_toml=raw, default_runner="claude")
    assert {b.id for b in bots} == {"dev", "search"}
    by_id = {b.id: b for b in bots}
    assert by_id["dev"].token == "11111:dev"
    assert by_id["dev"].default_role == "fullstack-dev"
    assert by_id["search"].default_runner == "gemini"


def test_missing_env_drops_bot_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("BOT_DEV_TOKEN", raising=False)
    raw = {"bots": {"dev": {"token_env": "BOT_DEV_TOKEN"}}}
    bots = load_bots(raw_toml=raw, default_runner="claude")
    assert bots == []
    assert "BOT_DEV_TOKEN" in caplog.text


def test_no_tokens_returns_empty(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bots = load_bots(raw_toml={}, default_runner="claude")
    assert bots == []


def test_bot_config_group_defaults():
    from src.core.bots import BotConfig
    b = BotConfig(id="dev")
    assert b.bot_username == ""
    assert b.bot_id_telegram == 0
    assert b.allow_bot_messages == "off"
    assert b.trusted_bot_ids is None
    assert b.allowed_chat_ids is None
    assert b.allow_all_groups is False


def test_load_bots_parses_group_fields(monkeypatch):
    monkeypatch.setenv("BOT_DEV_TOKEN", "1:dev")
    raw = {
        "bots": {
            "dev": {
                "token_env": "BOT_DEV_TOKEN",
                "default_runner": "claude",
                "allow_bot_messages": "mentions",
                "allowed_chat_ids": [-100123, -200456],
                "allow_all_groups": False,
                "trusted_bot_ids": [555, 666],
            },
        }
    }
    from src.core.bots import load_bots
    bots = load_bots(raw_toml=raw, default_runner="claude")
    assert len(bots) == 1
    b = bots[0]
    assert b.allow_bot_messages == "mentions"
    assert b.allowed_chat_ids == [-100123, -200456]
    assert b.allow_all_groups is False
    assert b.trusted_bot_ids == [555, 666]


def test_load_bots_group_fields_default_when_missing(monkeypatch):
    """If [bots.X] doesn't set group fields, defaults apply."""
    monkeypatch.setenv("BOT_DEV_TOKEN", "1:dev")
    raw = {"bots": {"dev": {"token_env": "BOT_DEV_TOKEN"}}}
    from src.core.bots import load_bots
    bots = load_bots(raw_toml=raw, default_runner="claude")
    assert len(bots) == 1
    b = bots[0]
    assert b.allow_bot_messages == "off"
    assert b.allowed_chat_ids is None
    assert b.allow_all_groups is False
    assert b.trusted_bot_ids is None


def test_bot_config_respond_to_at_all_default_false():
    from src.core.bots import BotConfig
    b = BotConfig(id="dev")
    assert b.respond_to_at_all is False


def test_load_bots_parses_respond_to_at_all(monkeypatch):
    monkeypatch.setenv("BOT_DEV_TOKEN", "1:dev")
    raw = {"bots": {"dev": {
        "token_env": "BOT_DEV_TOKEN",
        "respond_to_at_all": True,
    }}}
    from src.core.bots import load_bots
    bots = load_bots(raw_toml=raw, default_runner="claude")
    assert bots[0].respond_to_at_all is True


def test_legacy_discord_fallback_when_no_bots_section_but_discord_token_set(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake")
    bots = load_bots(raw_toml={}, default_runner="claude")
    assert len(bots) == 1
    assert bots[0].id == "default"
    assert bots[0].channel == "discord"
    assert bots[0].token_env == "DISCORD_BOT_TOKEN"
    assert bots[0].default_runner == "claude"


def test_legacy_telegram_fallback_still_works(monkeypatch):
    """Don't regress the existing Telegram legacy fallback."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    bots = load_bots(raw_toml={}, default_runner="claude")
    assert len(bots) == 1
    assert bots[0].channel == "telegram"


def test_legacy_both_fallbacks_when_both_tokens_set(monkeypatch):
    """If both legacy env vars exist, get both default bots."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg_fake")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "dc_fake")
    bots = load_bots(raw_toml={}, default_runner="claude")
    channels = sorted(b.channel for b in bots)
    assert channels == ["discord", "telegram"]


def test_explicit_bots_section_skips_legacy_fallback(monkeypatch):
    monkeypatch.setenv("BOT_DEV_TOKEN", "x")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "y")
    bots = load_bots(
        raw_toml={"bots": {"dev": {"channel": "telegram", "token_env": "BOT_DEV_TOKEN"}}},
        default_runner="claude",
    )
    # 走顯式 bots 路徑就不走 legacy fallback；Discord 條目應該也要在 bots.* 才會出現
    assert [b.id for b in bots] == ["dev"]
