import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.state import WizardState, mark_step_done
from src.setup import wizard


# ── Step 1: channel ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step1_telegram(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "1")
    await wizard.step_1_channel(state)
    assert state.channel == "telegram"
    assert 1 in state.completed_steps


@pytest.mark.asyncio
async def test_step1_discord(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "2")
    await wizard.step_1_channel(state)
    assert state.channel == "discord"


@pytest.mark.asyncio
async def test_step1_both(monkeypatch):
    state = WizardState()
    monkeypatch.setattr("builtins.input", lambda _: "3")
    await wizard.step_1_channel(state)
    assert state.channel == "both"


@pytest.mark.asyncio
async def test_step1_skipped_if_done():
    state = WizardState(completed_steps=[1], channel="discord")
    await wizard.step_1_channel(state)  # no input() called — would raise StopIteration
    assert state.channel == "discord"


@pytest.mark.asyncio
async def test_step1_retries_on_invalid_choice(monkeypatch):
    state = WizardState()
    responses = iter(["9", "x", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    await wizard.step_1_channel(state)
    assert state.channel == "telegram"


# ── Step 2: token ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step2_telegram_valid_token(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1])
    monkeypatch.setattr("builtins.input", lambda _: "valid-tok")
    with patch("src.setup.wizard.validate_telegram_token", return_value=True):
        await wizard.step_2_token(state)
    assert state.telegram_token == "valid-tok"
    assert 2 in state.completed_steps


@pytest.mark.asyncio
async def test_step2_retries_invalid_token(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1])
    responses = iter(["bad", "good"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    side_effects = [False, True]
    idx = [0]
    def _validate(t):
        r = side_effects[idx[0]]; idx[0] += 1; return r
    with patch("src.setup.wizard.validate_telegram_token", side_effect=_validate):
        await wizard.step_2_token(state)
    assert state.telegram_token == "good"


@pytest.mark.asyncio
async def test_step2_discord_valid_token(monkeypatch):
    state = WizardState(channel="discord", completed_steps=[1])
    monkeypatch.setattr("builtins.input", lambda _: "disc-tok")
    with patch("src.setup.wizard.validate_discord_token", return_value=True):
        await wizard.step_2_token(state)
    assert state.discord_token == "disc-tok"


@pytest.mark.asyncio
async def test_step2_skipped_if_done():
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="existing")
    await wizard.step_2_token(state)
    assert state.telegram_token == "existing"


# ── Step 3: allowlist ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step3_manual_fallback(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="tok")
    monkeypatch.setattr("builtins.input", lambda _: "12345")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=None):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [12345]
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_auto_capture(monkeypatch):
    state = WizardState(channel="telegram", completed_steps=[1, 2], telegram_token="tok")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=99999):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [99999]


@pytest.mark.asyncio
async def test_step3_discord_manual(monkeypatch):
    state = WizardState(channel="discord", completed_steps=[1, 2])
    monkeypatch.setattr("builtins.input", lambda _: "777")
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [777]


@pytest.mark.asyncio
async def test_step3_skipped_if_done():
    state = WizardState(channel="telegram", completed_steps=[1, 2, 3], allowed_user_ids=[42])
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [42]
