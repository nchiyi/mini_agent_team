"""
Tests for state.py Phase 1 additions:
  - v2 schema (version, mode, current_step, completed, failed, data)
  - v1 → v2 migration
  - detect_mode()
  - micro-step helpers
  - backward-compat integer-step shims
"""
import json
import pytest
from pathlib import Path

from src.setup.state import (
    WizardState,
    load_state,
    save_state,
    reset_state,
    detect_mode,
    is_micro_step_done,
    mark_micro_step_done,
    set_current_step,
    is_step_done,
    mark_step_done,
)


# ── WizardState defaults ──────────────────────────────────────────────────

def test_fresh_state_defaults():
    s = WizardState()
    assert s.version == 2
    assert s.mode == "fresh"
    assert s.current_step == ""
    assert s.completed == []
    assert s.failed == []
    assert s.data == {}


# ── save / load round-trip (v2) ───────────────────────────────────────────

def test_save_load_v2_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    s = WizardState(
        mode="resume",
        current_step="token_validation.done",
        completed=["channel_select.done"],
        failed=[],
        channels=["telegram"],
        telegram_token="tok",
    )
    save_state(s, path)
    loaded = load_state(path)
    assert loaded.version == 2
    assert loaded.mode == "resume"
    assert loaded.current_step == "token_validation.done"
    assert "channel_select.done" in loaded.completed
    assert loaded.telegram_token == "tok"


def test_save_creates_parent_dirs_v2(tmp_path):
    path = str(tmp_path / "deep" / "nested" / "state.json")
    save_state(WizardState(), path)
    assert Path(path).exists()


# ── v1 → v2 migration ────────────────────────────────────────────────────

def test_v1_migration_fresh(tmp_path):
    """A v1 file with no completed_steps should migrate to mode=fresh."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "completed_steps": [],
        "channels": [],
        "telegram_token": "",
    }))
    state = load_state(path)
    assert state.version == 2
    assert state.mode == "fresh"
    assert state.completed == []


def test_v1_migration_resume(tmp_path):
    """A v1 file with steps 1-3 done should migrate to mode=resume."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "completed_steps": [1, 2, 3],
        "channels": ["telegram"],
        "telegram_token": "tok",
        "allowed_user_ids": [42],
    }))
    state = load_state(path)
    assert state.version == 2
    assert state.mode == "resume"
    assert "channel_select.done" in state.completed
    assert "token_validation.done" in state.completed
    assert "allowlist.done" in state.completed
    assert state.channels == ["telegram"]
    assert state.telegram_token == "tok"
    assert state.allowed_user_ids == [42]


def test_v1_migration_launch(tmp_path):
    """A v1 file with step 9 done should migrate to mode=launch."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "completed_steps": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "channels": ["telegram"],
        "telegram_token": "tok",
    }))
    state = load_state(path)
    assert state.mode == "launch"
    assert state.current_step == "launch.done"


def test_v1_migration_step8_is_launch(tmp_path):
    """Step 8 in v1 also counts as 'launch' (deploy was configured)."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "completed_steps": [1, 2, 3, 4, 5, 6, 7, 8],
        "channels": ["discord"],
    }))
    state = load_state(path)
    assert state.mode == "launch"


def test_v1_config_data_carried_over(tmp_path):
    """Configuration data must survive migration unchanged."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "completed_steps": [1],
        "channels": ["discord"],
        "discord_token": "dsc-tok",
        "allowed_user_ids": [999],
        "selected_clis": ["codex"],
        "search_mode": "fts5+embedding",
        "update_notifications": False,
        "deploy_mode": "systemd",
        "optional_packages": ["voice"],
    }))
    state = load_state(path)
    assert state.discord_token == "dsc-tok"
    assert state.allowed_user_ids == [999]
    assert state.selected_clis == ["codex"]
    assert state.search_mode == "fts5+embedding"
    assert state.update_notifications is False
    assert state.deploy_mode == "systemd"
    assert "voice" in state.optional_packages


# ── detect_mode() ─────────────────────────────────────────────────────────

def test_detect_mode_fresh_no_file(tmp_path):
    path = str(tmp_path / "nonexistent.json")
    assert detect_mode(path) == "fresh"


def test_detect_mode_reset_flag(tmp_path):
    """reset=True should always return 'reset', even if file exists."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({"version": 2, "mode": "launch", "completed": ["launch.done"]}))
    assert detect_mode(path, reset=True) == "reset"


def test_detect_mode_launch_v2(tmp_path):
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "version": 2,
        "mode": "launch",
        "current_step": "launch.done",
        "completed": ["launch.done"],
        "failed": [],
    }))
    assert detect_mode(path) == "launch"


def test_detect_mode_resume_v2(tmp_path):
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({
        "version": 2,
        "mode": "resume",
        "current_step": "token_validation.done",
        "completed": ["channel_select.done"],
        "failed": [],
    }))
    assert detect_mode(path) == "resume"


def test_detect_mode_resume_from_v1(tmp_path):
    """v1 file with partial steps → detect_mode returns 'resume'."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({"completed_steps": [1, 2]}))
    assert detect_mode(path) == "resume"


def test_detect_mode_launch_from_v1(tmp_path):
    """v1 file with step 9 → detect_mode returns 'launch'."""
    path = str(tmp_path / "state.json")
    Path(path).write_text(json.dumps({"completed_steps": [1, 2, 3, 4, 5, 6, 7, 8, 9]}))
    assert detect_mode(path) == "launch"


def test_detect_mode_corrupt_json(tmp_path):
    path = str(tmp_path / "state.json")
    Path(path).write_text("{corrupt}")
    assert detect_mode(path) == "fresh"


# ── micro-step helpers ────────────────────────────────────────────────────

def test_micro_step_initially_not_done():
    s = WizardState()
    assert not is_micro_step_done(s, "preflight.disk_check")


def test_mark_micro_step_done():
    s = WizardState()
    mark_micro_step_done(s, "preflight.disk_check")
    assert is_micro_step_done(s, "preflight.disk_check")


def test_mark_micro_step_done_idempotent():
    s = WizardState()
    mark_micro_step_done(s, "token_validation.telegram_ping")
    mark_micro_step_done(s, "token_validation.telegram_ping")
    assert s.completed.count("token_validation.telegram_ping") == 1


def test_set_current_step():
    s = WizardState()
    set_current_step(s, "allowlist.capture")
    assert s.current_step == "allowlist.capture"


# ── backward-compat integer-step shims ───────────────────────────────────

def test_int_step_shim_initially_false():
    s = WizardState()
    assert not is_step_done(s, 1)
    assert not is_step_done(s, 9)


def test_int_step_shim_mark_and_check():
    s = WizardState()
    mark_step_done(s, 3)
    assert is_step_done(s, 3)
    assert not is_step_done(s, 4)


def test_int_step_shim_idempotent():
    s = WizardState()
    mark_step_done(s, 1)
    mark_step_done(s, 1)
    assert s.completed.count("channel_select.done") == 1


def test_int_step_shim_writes_micro_id():
    s = WizardState()
    mark_step_done(s, 2)
    assert "token_validation.done" in s.completed


def test_int_step_shim_updates_current_step():
    """After marking step N done, current_step should advance."""
    s = WizardState()
    mark_step_done(s, 1)
    # current_step should now point past step 1
    assert s.current_step != ""
