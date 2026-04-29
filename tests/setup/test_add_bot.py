"""Standalone add-bot tool: append a [bots.X] block + BOT_<ID>_TOKEN env."""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_add_bot_appends_to_existing_config(tmp_path, monkeypatch):
    from src.setup.add_bot import add_bot_to_config

    config_path = tmp_path / "config.toml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        '[gateway]\ndefault_runner = "claude"\n\n'
        '[bots.dev]\nchannel = "telegram"\ntoken_env = "BOT_DEV_TOKEN"\n'
    )
    env_path.write_text('BOT_DEV_TOKEN="existing"\n')

    new_bot = {
        "id": "ops", "channel": "telegram",
        "token_env": "BOT_OPS_TOKEN", "_token_value": "new_token",
        "default_runner": "claude",
    }
    async def fake_collect(**kwargs):
        return new_bot
    monkeypatch.setattr("src.setup.add_bot.collect_bot", fake_collect)

    await add_bot_to_config(
        config_path=str(config_path), env_path=str(env_path),
        channel="telegram",
    )

    toml_text = config_path.read_text()
    env_text = env_path.read_text()
    assert "[bots.dev]" in toml_text   # existing preserved
    assert "[bots.ops]" in toml_text   # new appended
    assert 'BOT_DEV_TOKEN="existing"' in env_text
    assert 'BOT_OPS_TOKEN="new_token"' in env_text


@pytest.mark.asyncio
async def test_add_bot_rejects_duplicate_id(tmp_path, monkeypatch):
    from src.setup.add_bot import add_bot_to_config, DuplicateBotIdError

    config_path = tmp_path / "config.toml"
    config_path.write_text('[bots.dev]\nchannel = "telegram"\n')
    env_path = tmp_path / ".env"
    env_path.write_text('')

    async def fake_collect(**kwargs):
        return {"id": "dev", "channel": "telegram", "token_env": "BOT_DEV_TOKEN", "_token_value": "x"}
    monkeypatch.setattr("src.setup.add_bot.collect_bot", fake_collect)

    with pytest.raises(DuplicateBotIdError):
        await add_bot_to_config(
            config_path=str(config_path), env_path=str(env_path),
            channel="telegram",
        )
