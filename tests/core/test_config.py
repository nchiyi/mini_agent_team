# tests/core/test_config.py
import os, pytest, tomllib
from pathlib import Path

def test_config_loads_toml(tmp_path):
    toml_content = """
[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[runners.claude]
path = "claude"
args = ["--dangerously-skip-permissions"]
timeout_seconds = 300
context_token_budget = 4000

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    assert cfg.gateway.default_runner == "claude"
    assert cfg.gateway.session_idle_minutes == 60
    assert cfg.runners["claude"].timeout_seconds == 300
    assert cfg.audit.max_entries == 1000


def test_config_missing_file_raises():
    from src.core.config import load_config
    with pytest.raises(FileNotFoundError):
        load_config(config_path="/nonexistent/config.toml", env_path=None)


def test_config_loads_env_vars(tmp_path, monkeypatch):
    toml_content = """
[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    assert cfg.telegram_token == "test_token_123"
    assert cfg.allowed_user_ids == [111, 222]


def test_config_upgrades_legacy_runner_args(tmp_path):
    toml_content = """
[gateway]
default_runner = "codex"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[runners.codex]
path = "codex"
args = ["exec", "--skip-git-repo-check"]

[runners.gemini]
path = "gemini"
args = []

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    # Legacy args are upgraded to the new safe default (empty list)
    assert cfg.runners["codex"].args == []
    assert cfg.runners["gemini"].args == []


def test_config_keeps_custom_runner_args(tmp_path):
    toml_content = """
[gateway]
default_runner = "codex"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[runners.codex]
path = "codex"
args = ["exec", "--model", "gpt-5.4"]

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content)

    from src.core.config import load_config
    cfg = load_config(config_path=str(config_file), env_path=None)

    assert cfg.runners["codex"].args == ["exec", "--model", "gpt-5.4"]


def test_legacy_single_token_yields_default_bot(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "12345:legacy")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("""[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20
""")
    from src.core.config import load_config
    cfg = load_config(str(cfg_path), env_path=None)
    assert hasattr(cfg, "bots")
    assert len(cfg.bots) == 1
    assert cfg.bots[0].id == "default"
    assert cfg.bots[0].default_runner == "claude"


def test_multibot_section_parsed(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_DEV_TOKEN", "1:dev")
    monkeypatch.setenv("BOT_SEARCH_TOKEN", "2:search")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("""[gateway]
default_runner = "claude"
session_idle_minutes = 60
max_message_length_telegram = 4096
max_message_length_discord = 2000
stream_edit_interval_seconds = 1.5

[audit]
path = "data/audit"
max_entries = 1000

[memory]
db_path = "data/db/history.db"
hot_path = "data/memory/hot"
cold_permanent_path = "data/memory/cold/permanent"
cold_session_path = "data/memory/cold/session"
tier3_context_turns = 20
distill_trigger_turns = 20

[bots.dev]
token_env = "BOT_DEV_TOKEN"
default_runner = "claude"

[bots.search]
token_env = "BOT_SEARCH_TOKEN"
default_runner = "gemini"
""")
    from src.core.config import load_config
    cfg = load_config(str(cfg_path), env_path=None)
    assert len(cfg.bots) == 2
    assert {b.id for b in cfg.bots} == {"dev", "search"}
