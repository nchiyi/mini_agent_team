import pytest
from pathlib import Path
from src.setup.state import (
    WizardState, load_state, save_state, reset_state,
    is_step_done, mark_step_done,
)


def test_load_state_returns_default_when_missing(tmp_path):
    state = load_state(str(tmp_path / "state.json"))
    assert state.completed_steps == []
    assert state.channels == []
    assert state.telegram_token == ""
    assert state.allowed_user_ids == []


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    s = WizardState(
        channels=["telegram"],
        telegram_token="abc",
        completed_steps=[1, 2],
        allowed_user_ids=[999],
        selected_clis=["claude"],
        search_mode="fts5",
        update_notifications=True,
        deploy_mode="systemd",
    )
    save_state(s, path)
    loaded = load_state(path)
    assert "telegram" in loaded.channels
    assert loaded.telegram_token == "abc"
    assert 1 in loaded.completed_steps
    assert 2 in loaded.completed_steps
    assert loaded.allowed_user_ids == [999]
    assert loaded.selected_clis == ["claude"]
    assert loaded.deploy_mode == "systemd"


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "data" / "sub" / "state.json")
    save_state(WizardState(), path)
    assert Path(path).exists()


def test_reset_state_removes_file(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(WizardState(completed_steps=[1]), path)
    reset_state(path)
    assert not Path(path).exists()


def test_reset_state_noop_when_missing(tmp_path):
    reset_state(str(tmp_path / "no-state.json"))  # must not raise


def test_is_step_done_false_initially():
    s = WizardState()
    assert not is_step_done(s, 1)
    assert not is_step_done(s, 5)


def test_mark_step_done_and_check():
    s = WizardState()
    mark_step_done(s, 3)
    assert is_step_done(s, 3)
    assert not is_step_done(s, 4)


def test_mark_step_done_idempotent():
    s = WizardState()
    mark_step_done(s, 1)
    mark_step_done(s, 1)
    assert s.completed_steps.count(1) == 1


def test_load_state_ignores_unknown_keys(tmp_path):
    import json
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({"channels": ["telegram"], "future_key": "ignored"}))
    state = load_state(path)
    assert "telegram" in state.channels


def test_load_state_returns_default_on_corrupt_json(tmp_path):
    path = str(tmp_path / "state.json")
    Path(path).write_text("{corrupt json}")
    state = load_state(path)
    assert state.completed_steps == []
    assert state.channels == []
