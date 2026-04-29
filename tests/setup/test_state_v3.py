"""Schema v3: WizardState.bots field + v2→v3 migration."""
import json

from src.setup.state import WizardState, load_state, _SCHEMA_VERSION


def test_schema_version_is_3():
    assert _SCHEMA_VERSION == 3


def test_state_default_bots_is_empty_list():
    s = WizardState()
    assert s.bots == []


def test_state_bots_preserves_explicit_value():
    s = WizardState(bots=[{"id": "dev", "channel": "telegram"}])
    assert s.bots == [{"id": "dev", "channel": "telegram"}]


def test_v2_state_with_telegram_token_migrates_to_default_bot(tmp_path):
    """v2 state files have telegram_token but no bots; migration synthesises one."""
    state_path = tmp_path / "wizard_state.json"
    state_path.write_text(json.dumps({
        "version": 2,
        "telegram_token": "abc",
        "discord_token": "",
        "channels": ["telegram"],
    }))
    s = load_state(str(state_path))
    assert s.version == 3
    assert s.telegram_token == "abc"  # legacy field preserved
    assert any(b["id"] == "default" and b["channel"] == "telegram" for b in s.bots)
    # token_env naming: TELEGRAM_BOT_TOKEN for legacy
    tg = next(b for b in s.bots if b["channel"] == "telegram")
    assert tg["token_env"] == "TELEGRAM_BOT_TOKEN"


def test_v2_state_with_both_tokens_migrates_to_two_bots(tmp_path):
    state_path = tmp_path / "wizard_state.json"
    state_path.write_text(json.dumps({
        "version": 2,
        "telegram_token": "tg",
        "discord_token": "dc",
        "channels": ["telegram", "discord"],
    }))
    s = load_state(str(state_path))
    assert {(b["id"], b["channel"]) for b in s.bots} == {
        ("default", "telegram"),
        ("default", "discord"),
    }


def test_v2_state_with_neither_token_migrates_to_empty_bots(tmp_path):
    state_path = tmp_path / "wizard_state.json"
    state_path.write_text(json.dumps({"version": 2, "channels": []}))
    s = load_state(str(state_path))
    assert s.bots == []


def test_v3_state_with_explicit_bots_does_not_double_synthesise(tmp_path):
    """Already-v3 state should round-trip without injecting default bots."""
    state_path = tmp_path / "wizard_state.json"
    state_path.write_text(json.dumps({
        "version": 3,
        "telegram_token": "abc",
        "channels": ["telegram"],
        "bots": [{"id": "dev", "channel": "telegram", "token_env": "BOT_DEV_TOKEN"}],
    }))
    s = load_state(str(state_path))
    assert len(s.bots) == 1
    assert s.bots[0]["id"] == "dev"
