"""
Phase 1 tests for the wizard entry point (run_wizard):
  - fresh state: no file → mode=fresh, banner shows FRESH
  - resume state: file with current_step → mode=RESUME (interrupted at: ...)
  - reset mode: --reset flag → state cleared, restarts
  - launch mode: already configured → prints mode=LAUNCH and returns early
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.setup import wizard
from src.setup.state import WizardState, save_state


# Helper: build a fully-configured v2 state file (mode=launch)
def _write_launch_state(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 2,
        "mode": "launch",
        "current_step": "launch.done",
        "completed": ["launch.done"],
        "failed": [],
        "data": {},
        "channels": ["telegram"],
        "telegram_token": "tok",
        "discord_token": "",
        "allowed_user_ids": [1],
        "selected_clis": ["claude"],
        "search_mode": "fts5",
        "update_notifications": True,
        "deploy_mode": "foreground",
        "optional_packages": [],
    }
    Path(path).write_text(json.dumps(data))


# Helper: build a partial v2 state file (mode=resume)
def _write_resume_state(path: str, current_step: str = "token_validation.done") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 2,
        "mode": "resume",
        "current_step": current_step,
        "completed": ["channel_select.done"],
        "failed": [],
        "data": {},
        "channels": ["telegram"],
        "telegram_token": "",
        "discord_token": "",
        "allowed_user_ids": [],
        "selected_clis": [],
        "search_mode": "fts5",
        "update_notifications": True,
        "deploy_mode": "foreground",
        "optional_packages": [],
    }
    Path(path).write_text(json.dumps(data))


# ── fresh mode ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_fresh_mode_calls_all_steps(tmp_path, capsys):
    """With no state file, wizard runs in FRESH mode and calls every step."""
    state_path = str(tmp_path / "state.json")
    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock) as s2, \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock) as s3, \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]) as s4, \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None) as s5, \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock) as s6, \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock) as s7, \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock) as s8, \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock) as s9:
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))

    for step in (s1, s2, s3, s4, s5, s6, s7, s8, s9):
        step.assert_called_once()

    out = capsys.readouterr().out
    assert "FRESH" in out
    assert "MAT Setup Wizard" in out


# ── resume mode ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_resume_mode_banner(tmp_path, capsys):
    """State file with current_step → banner shows RESUME + interrupted step."""
    state_path = str(tmp_path / "state.json")
    _write_resume_state(state_path, current_step="token_validation.done")

    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None), \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))

    out = capsys.readouterr().out
    assert "RESUME" in out
    assert "token_validation.done" in out


# ── reset mode ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_reset_mode_clears_state(tmp_path, capsys):
    """--reset flag clears saved state; wizard re-runs from scratch."""
    state_path = str(tmp_path / "state.json")
    # Write a fully-configured v2 state
    _write_launch_state(state_path)
    assert Path(state_path).exists()

    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None), \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, reset=True, cwd=str(tmp_path))

    # step_1 must be called (state was wiped)
    s1.assert_called_once()
    out = capsys.readouterr().out
    assert "RESET" in out


# ── launch mode ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_launch_mode_returns_early(tmp_path, capsys):
    """Fully-configured state → mode=launch, wizard exits without re-running steps."""
    state_path = str(tmp_path / "state.json")
    _write_launch_state(state_path)

    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as s1, \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock) as s9:
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))

    s1.assert_not_called()
    s9.assert_not_called()
    out = capsys.readouterr().out
    assert "LAUNCH" in out


# ── v1 state file → wizard detects resume / launch ───────────────────────

@pytest.mark.asyncio
async def test_run_wizard_v1_resume_state(tmp_path, capsys):
    """Wizard handles a legacy v1 state file (no 'version' key) as resume."""
    state_path = str(tmp_path / "state.json")
    Path(state_path).write_text(json.dumps({
        "completed_steps": [1, 2, 3],
        "channels": ["telegram"],
        "telegram_token": "tok",
        "allowed_user_ids": [42],
        "selected_clis": [],
        "search_mode": "fts5",
        "update_notifications": True,
        "deploy_mode": "foreground",
        "optional_packages": [],
    }))

    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock) as s2, \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock) as s3, \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None), \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))

    out = capsys.readouterr().out
    assert "RESUME" in out


@pytest.mark.asyncio
async def test_run_wizard_v1_launch_state(tmp_path, capsys):
    """Wizard handles a legacy v1 state file with step 9 as launch mode."""
    state_path = str(tmp_path / "state.json")
    Path(state_path).write_text(json.dumps({
        "completed_steps": list(range(1, 10)),
        "channels": ["telegram"],
        "telegram_token": "tok",
        "allowed_user_ids": [1],
        "selected_clis": ["claude"],
        "search_mode": "fts5",
        "update_notifications": True,
        "deploy_mode": "foreground",
        "optional_packages": [],
    }))

    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as s1:
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))

    s1.assert_not_called()
    out = capsys.readouterr().out
    assert "LAUNCH" in out
