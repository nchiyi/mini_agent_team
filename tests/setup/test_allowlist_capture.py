"""Tests for Phase 2-C: allowlist auto-capture (Discord symmetric) + fail-loud."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.setup.state import WizardState
from src.setup import wizard


# ── _capture_discord_user_id ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discord_capture_success():
    """Discord auto-capture returns the sender's user ID when a message arrives."""
    # Simulate a discord.Client that fires on_message almost immediately.
    captured_ids: list[int] = []

    class _FakeMessage:
        author = MagicMock(id=987654321, bot=False)

    class _FakeClient:
        def __init__(self, intents=None):
            self._listeners: dict = {}

        def event(self, coro):
            # Register the decorated coroutine as an on_message handler.
            self._listeners[coro.__name__] = coro
            return coro

        async def start(self, token):
            # Immediately deliver a fake message so the capture loop breaks.
            handler = self._listeners.get("on_message")
            if handler:
                await handler(_FakeMessage())
            # Then block until cancelled.
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass

        async def close(self):
            pass

    fake_client = _FakeClient()

    with patch("src.setup.wizard._capture_discord_user_id", wraps=None) as _:
        pass  # We'll call the real function with the fake discord module.

    # Patch the `discord` module import inside the function.
    fake_discord_module = MagicMock()
    fake_discord_module.Intents.default.return_value = MagicMock()
    fake_discord_module.Client.return_value = fake_client
    fake_discord_module.Message = _FakeMessage

    with patch.dict("sys.modules", {"discord": fake_discord_module}):
        result = await asyncio.wait_for(
            wizard._capture_discord_user_id("fake-token", timeout=5),
            timeout=10,
        )

    assert result == 987654321


@pytest.mark.asyncio
async def test_discord_capture_timeout_returns_none():
    """Discord auto-capture returns None when no message arrives within the timeout."""

    class _FakeClientNoMessage:
        def __init__(self, intents=None):
            pass

        def event(self, coro):
            return coro

        async def start(self, token):
            # Never fires on_message — simulates absence of messages.
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass

        async def close(self):
            pass

    fake_discord_module = MagicMock()
    fake_discord_module.Intents.default.return_value = MagicMock()
    fake_discord_module.Client.return_value = _FakeClientNoMessage()

    with patch.dict("sys.modules", {"discord": fake_discord_module}):
        result = await asyncio.wait_for(
            wizard._capture_discord_user_id("fake-token", timeout=2),
            timeout=10,
        )

    assert result is None


@pytest.mark.asyncio
async def test_discord_capture_import_error_returns_none():
    """Returns None gracefully when the discord package is not installed."""
    with patch.dict("sys.modules", {"discord": None}):
        result = await wizard._capture_discord_user_id("fake-token", timeout=5)
    assert result is None


# ── step_3_allowlist — fail-loud behaviour ───────────────────────────────────

@pytest.mark.asyncio
async def test_step3_empty_allowlist_user_chooses_n_deferred_config(monkeypatch):
    """Empty allowlist + user refuses allow_all → warns and marks step done (deferred config)."""
    state = WizardState(channels=["discord"], completed_steps=[1, 2], discord_token="tok")

    async def _fake_discord_capture(token, timeout=30):
        return None

    # Prompts: opt-in = "y" (proceed with capture), manual entry = "" (skip), allow_all = "n"
    prompt_responses = iter(["y", "", "n"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(prompt_responses))

    with patch("src.setup.wizard._capture_discord_user_id", side_effect=_fake_discord_capture):
        await wizard.step_3_allowlist(state)

    # Step completes even with empty allowlist — deferred config via .env
    assert state.allowed_user_ids == []
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_empty_allowlist_user_chooses_y_sets_allow_all(monkeypatch):
    """Empty allowlist + user chooses 'y' (allow all) → state.allow_all_users = True."""
    state = WizardState(channels=["discord"], completed_steps=[1, 2], discord_token="tok")

    async def _fake_discord_capture(token, timeout=30):
        return None

    # Prompts: opt-in = "y" (proceed with capture), manual entry = "" (skip), allow_all = "y"
    prompt_responses = iter(["y", "", "y"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(prompt_responses))

    with patch("src.setup.wizard._capture_discord_user_id", side_effect=_fake_discord_capture):
        await wizard.step_3_allowlist(state)

    assert state.data.get("allow_all_users") is True
    assert 3 in state.completed_steps


# ── step_3_allowlist — dual-channel happy path ───────────────────────────────

@pytest.mark.asyncio
async def test_step3_discord_auto_capture_success(monkeypatch):
    """Discord auto-capture succeeds → user confirms → ID stored."""
    state = WizardState(channels=["discord"], completed_steps=[1, 2], discord_token="tok")

    async def _fake_discord_capture(token, timeout=30):
        return 111222333

    # Confirm prompt: "y"
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "y")

    with patch("src.setup.wizard._capture_discord_user_id", side_effect=_fake_discord_capture):
        await wizard.step_3_allowlist(state)

    assert state.allowed_user_ids == [111222333]
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_discord_auto_capture_user_rejects_then_manual(monkeypatch):
    """Discord auto-capture returns ID, user says 'n', falls back to manual entry."""
    state = WizardState(channels=["discord"], completed_steps=[1, 2], discord_token="tok")

    async def _fake_discord_capture(token, timeout=30):
        return 999888777

    # Confirm = n, then manual entry = 42
    prompt_responses = iter(["n", "42"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(prompt_responses))

    with patch("src.setup.wizard._capture_discord_user_id", side_effect=_fake_discord_capture):
        await wizard.step_3_allowlist(state)

    assert state.allowed_user_ids == [42]
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_both_channels_capture(monkeypatch):
    """Both Telegram and Discord auto-capture populate the allowlist."""
    state = WizardState(
        channels=["telegram", "discord"],
        completed_steps=[1, 2],
        telegram_token="tg-tok",
        discord_token="dc-tok",
    )

    async def _fake_tg_capture(token, timeout=30):
        return 100

    async def _fake_dc_capture(token, timeout=30):
        return 200

    # All confirm prompts = "y"
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "y")

    with patch("src.setup.wizard._capture_telegram_user_id", side_effect=_fake_tg_capture), \
         patch("src.setup.wizard._capture_discord_user_id", side_effect=_fake_dc_capture):
        await wizard.step_3_allowlist(state)

    assert 100 in state.allowed_user_ids
    assert 200 in state.allowed_user_ids
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_skipped_if_done():
    """step_3 is a no-op when already marked complete."""
    state = WizardState(channels=["discord"], completed_steps=[1, 2, 3], allowed_user_ids=[77])
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [77]
