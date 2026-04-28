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
