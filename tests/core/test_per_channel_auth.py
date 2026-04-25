# tests/core/test_per_channel_auth.py
"""
Tests for per-channel auth fallback chain (issue #58).

Scenarios covered:
  (a) only global ALLOWED_USER_IDS set — both channels inherit global
  (b) only per-channel override set — channel uses its own, the other inherits global
  (c) both global and per-channel set (conflict) — per-channel wins
  (d) neither global nor per-channel set — deny all
"""
import pytest

_BASE_TOML = """
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


def _write_config(tmp_path, extra: str = "") -> str:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(_BASE_TOML + extra)
    return str(cfg_file)


# ── (a) only global set ──────────────────────────────────────────────────────

def test_only_global_telegram_inherits(tmp_path, monkeypatch):
    """When only ALLOWED_USER_IDS is set globally, telegram inherits it."""
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")
    path = _write_config(tmp_path)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    ids, allow_all = _resolve_channel_auth(cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    assert ids == [111, 222]
    assert allow_all is False


def test_only_global_discord_inherits(tmp_path, monkeypatch):
    """When only ALLOWED_USER_IDS is set globally, discord inherits it."""
    monkeypatch.setenv("ALLOWED_USER_IDS", "333")
    path = _write_config(tmp_path)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    ids, allow_all = _resolve_channel_auth(cfg, cfg.discord.allowed_user_ids, cfg.discord.allow_all_users)
    assert ids == [333]
    assert allow_all is False


# ── (b) only per-channel set ─────────────────────────────────────────────────

def test_only_telegram_override(tmp_path, monkeypatch):
    """Per-channel telegram override used; discord falls back to global (empty → deny)."""
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    extra = """
[telegram]
allowed_user_ids = [500, 501]
"""
    path = _write_config(tmp_path, extra)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    tg_ids, tg_all = _resolve_channel_auth(cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    assert tg_ids == [500, 501]
    assert tg_all is False

    # discord has no override and no global → deny all
    dc_ids, dc_all = _resolve_channel_auth(cfg, cfg.discord.allowed_user_ids, cfg.discord.allow_all_users)
    assert dc_ids == []
    assert dc_all is False


def test_only_discord_override(tmp_path, monkeypatch):
    """Per-channel discord override used; telegram falls back to global."""
    monkeypatch.setenv("ALLOWED_USER_IDS", "999")
    extra = """
[discord]
allowed_user_ids = [700]
allow_all_users = false
"""
    path = _write_config(tmp_path, extra)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    # telegram uses global
    tg_ids, tg_all = _resolve_channel_auth(cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    assert tg_ids == [999]

    # discord uses per-channel
    dc_ids, dc_all = _resolve_channel_auth(cfg, cfg.discord.allowed_user_ids, cfg.discord.allow_all_users)
    assert dc_ids == [700]
    assert dc_all is False


# ── (c) both global and per-channel set — per-channel wins ───────────────────

def test_per_channel_overrides_global(tmp_path, monkeypatch):
    """Per-channel ids win over global ids when both are set."""
    monkeypatch.setenv("ALLOWED_USER_IDS", "111,222")
    extra = """
[telegram]
allowed_user_ids = [999]

[discord]
allow_all_users = true
"""
    path = _write_config(tmp_path, extra)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    # telegram override replaces global
    tg_ids, tg_all = _resolve_channel_auth(cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    assert tg_ids == [999]
    assert tg_all is False

    # discord override: allow_all wins over global strict list
    dc_ids, dc_all = _resolve_channel_auth(cfg, cfg.discord.allowed_user_ids, cfg.discord.allow_all_users)
    assert dc_all is True


def test_per_channel_allow_all_overrides_global_strict(tmp_path, monkeypatch):
    """Per-channel allow_all_users=true wins even when global has strict user list."""
    monkeypatch.setenv("ALLOWED_USER_IDS", "100,200,300")
    extra = """
[telegram]
allow_all_users = true
"""
    path = _write_config(tmp_path, extra)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    tg_ids, tg_all = _resolve_channel_auth(cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    assert tg_all is True
    assert tg_ids == []   # no per-channel ids, just allow_all


# ── (d) neither global nor per-channel set — deny all ────────────────────────

def test_no_auth_configured_denies_all(tmp_path, monkeypatch):
    """When neither global nor per-channel auth is configured, deny all."""
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    path = _write_config(tmp_path)

    from src.core.config import load_config, _resolve_channel_auth
    cfg = load_config(config_path=path, env_path=None)

    for channel_ids, channel_all in [
        (cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users),
        (cfg.discord.allowed_user_ids, cfg.discord.allow_all_users),
    ]:
        ids, allow_all = _resolve_channel_auth(cfg, channel_ids, channel_all)
        assert ids == []
        assert allow_all is False


# ── startup log helpers ──────────────────────────────────────────────────────

def test_log_channel_auth_emits_strict(tmp_path, monkeypatch, caplog):
    """Startup log emits 'strict' when a user list is set."""
    import logging
    monkeypatch.setenv("ALLOWED_USER_IDS", "1,2,3")
    path = _write_config(tmp_path)

    with caplog.at_level(logging.INFO, logger="src.core.config"):
        from src.core.config import load_config
        load_config(config_path=path, env_path=None)

    assert any("telegram auth: strict (3 users) [source=global]" in r.message for r in caplog.records)
    assert any("discord auth: strict (3 users) [source=global]" in r.message for r in caplog.records)


def test_log_channel_auth_emits_open_with_channel_override(tmp_path, monkeypatch, caplog):
    """Startup log emits 'open' with 'channel-override' source when per-channel allow_all is set."""
    import logging
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    extra = """
[discord]
allow_all_users = true
"""
    path = _write_config(tmp_path, extra)

    with caplog.at_level(logging.INFO, logger="src.core.config"):
        from src.core.config import load_config
        load_config(config_path=path, env_path=None)

    assert any("discord auth: open [source=channel-override]" in r.message for r in caplog.records)


def test_log_channel_auth_emits_deny_all(tmp_path, monkeypatch, caplog):
    """Startup log emits 'deny-all' when no auth is configured."""
    import logging
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    path = _write_config(tmp_path)

    with caplog.at_level(logging.INFO, logger="src.core.config"):
        from src.core.config import load_config
        load_config(config_path=path, env_path=None)

    assert any("telegram auth: deny-all [source=global]" in r.message for r in caplog.records)
    assert any("discord auth: deny-all [source=global]" in r.message for r in caplog.records)
