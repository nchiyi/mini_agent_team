import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.state import WizardState, mark_step_done
from src.setup import wizard


# ── Step 1: channel ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step1_telegram(monkeypatch):
    state = WizardState()
    responses = iter(["1", ""])  # toggle telegram, then confirm
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    await wizard.step_1_channel(state)
    assert "telegram" in state.channels
    assert 1 in state.completed_steps


@pytest.mark.asyncio
async def test_step1_discord(monkeypatch):
    state = WizardState()
    responses = iter(["2", ""])  # toggle discord, then confirm
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    await wizard.step_1_channel(state)
    assert "discord" in state.channels


@pytest.mark.asyncio
async def test_step1_both(monkeypatch):
    state = WizardState()
    responses = iter(["1 2", ""])  # toggle both at once, then confirm
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    await wizard.step_1_channel(state)
    assert "telegram" in state.channels
    assert "discord" in state.channels


@pytest.mark.asyncio
async def test_step1_skipped_if_done():
    state = WizardState(completed_steps=[1], channels=["discord"])
    await wizard.step_1_channel(state)  # no _prompt called — would raise StopIteration
    assert "discord" in state.channels


@pytest.mark.asyncio
async def test_step1_retries_on_invalid_choice(monkeypatch):
    state = WizardState()
    responses = iter(["9", "x", "1", ""])  # invalid, invalid, toggle telegram, confirm
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    await wizard.step_1_channel(state)
    assert "telegram" in state.channels


# ── Step 2: token ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step2_telegram_valid_token(monkeypatch):
    state = WizardState(channels=["telegram"], completed_steps=[1])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "valid-tok")
    ok = MagicMock(valid=True, skipped=False)
    with patch("src.setup.wizard.validate_telegram_token", return_value=ok):
        await wizard.step_2_token(state)
    assert state.telegram_token == "valid-tok"
    assert 2 in state.completed_steps


@pytest.mark.asyncio
async def test_step2_retries_invalid_token(monkeypatch):
    state = WizardState(channels=["telegram"], completed_steps=[1])
    responses = iter(["bad", "good"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    side_effects = [MagicMock(valid=False, skipped=False), MagicMock(valid=True, skipped=False)]
    idx = [0]
    def _validate(t):
        r = side_effects[idx[0]]; idx[0] += 1; return r
    with patch("src.setup.wizard.validate_telegram_token", side_effect=_validate):
        await wizard.step_2_token(state)
    assert state.telegram_token == "good"


@pytest.mark.asyncio
async def test_step2_discord_valid_token(monkeypatch):
    state = WizardState(channels=["discord"], completed_steps=[1])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "disc-tok")
    ok = MagicMock(valid=True, skipped=False)
    with patch("src.setup.wizard.validate_discord_token", return_value=ok):
        await wizard.step_2_token(state)
    assert state.discord_token == "disc-tok"


@pytest.mark.asyncio
async def test_step2_skipped_if_done():
    state = WizardState(channels=["telegram"], completed_steps=[1, 2], telegram_token="existing")
    await wizard.step_2_token(state)
    assert state.telegram_token == "existing"


# ── Step 3: allowlist ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step3_manual_fallback(monkeypatch):
    state = WizardState(channels=["telegram"], completed_steps=[1, 2], telegram_token="tok")
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "12345")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=None):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [12345]
    assert 3 in state.completed_steps


@pytest.mark.asyncio
async def test_step3_auto_capture(monkeypatch):
    state = WizardState(channels=["telegram"], completed_steps=[1, 2], telegram_token="tok")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=99999):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [99999]


@pytest.mark.asyncio
async def test_step3_discord_manual(monkeypatch):
    state = WizardState(channels=["discord"], completed_steps=[1, 2])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "777")
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [777]


@pytest.mark.asyncio
async def test_step3_skipped_if_done():
    state = WizardState(channels=["telegram"], completed_steps=[1, 2, 3], allowed_user_ids=[42])
    await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [42]


# ── Step 4: CLI ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step4_selects_clis(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "claude,codex")
    with patch("src.setup.wizard.is_cli_installed", return_value=True):
        tasks = await wizard.step_4_clis(state)
    assert state.selected_clis == ["claude", "codex"]
    assert tasks == []  # all installed, no background tasks
    assert 4 in state.completed_steps


@pytest.mark.asyncio
async def test_step4_queues_install_for_missing(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "claude")
    with patch("src.setup.wizard.is_cli_installed", return_value=False):
        with patch("src.setup.wizard.install_cli", new_callable=AsyncMock, return_value=("claude", True)):
            tasks = await wizard.step_4_clis(state)
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_step4_defaults_to_claude_on_empty(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "")
    with patch("src.setup.wizard.is_cli_installed", return_value=True):
        await wizard.step_4_clis(state)
    assert "claude" in state.selected_clis


@pytest.mark.asyncio
async def test_step4_skipped_if_done():
    state = WizardState(completed_steps=[1, 2, 3, 4], selected_clis=["codex"])
    tasks = await wizard.step_4_clis(state)
    assert tasks == []
    assert state.selected_clis == ["codex"]


# ── Step 5: search ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step5_fts5_default(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "1")
    task = await wizard.step_5_search(state)
    assert state.search_mode == "fts5"
    assert task is None
    assert 5 in state.completed_steps


@pytest.mark.asyncio
async def test_step5_embedding_returns_task(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "2")
    with patch("src.setup.wizard.install_ollama", new_callable=AsyncMock, return_value=True):
        task = await wizard.step_5_search(state)
    assert state.search_mode == "fts5+embedding"
    assert task is not None


@pytest.mark.asyncio
async def test_step5_skipped_if_done():
    state = WizardState(completed_steps=[1, 2, 3, 4, 5], search_mode="fts5+embedding")
    task = await wizard.step_5_search(state)
    assert task is None
    assert state.search_mode == "fts5+embedding"


# ── Step 7: updates ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step6_updates_on(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "y")
    await wizard.step_7_updates(state)
    assert state.update_notifications is True
    assert 7 in state.completed_steps


@pytest.mark.asyncio
async def test_step6_updates_off(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "n")
    await wizard.step_7_updates(state)
    assert state.update_notifications is False


# ── Step 8: deploy ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step7_foreground(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6, 7])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "1")
    await wizard.step_8_deploy(state)
    assert state.deploy_mode == "foreground"
    assert 8 in state.completed_steps


@pytest.mark.asyncio
async def test_step7_systemd(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6, 7])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "2")
    await wizard.step_8_deploy(state)
    assert state.deploy_mode == "systemd"


@pytest.mark.asyncio
async def test_step7_docker(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6, 7])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "3")
    await wizard.step_8_deploy(state)
    assert state.deploy_mode == "docker"


# ── run_wizard orchestrator ──────────────────────────────────────

@pytest.mark.asyncio
async def test_run_wizard_resumes_skipping_completed_steps(tmp_path):
    from src.setup.state import save_state
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7, 8],
        channels=["telegram"],
        telegram_token="tok",
        allowed_user_ids=[123],
        selected_clis=["claude"],
        search_mode="fts5",
        update_notifications=True,
        deploy_mode="foreground",
    )
    state_path = str(tmp_path / "state.json")
    save_state(state, state_path)
    with patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock) as mock_launch:
        await wizard.run_wizard(state_path=state_path, cwd=str(tmp_path))
    mock_launch.assert_called_once()


@pytest.mark.asyncio
async def test_run_wizard_reset_clears_state(tmp_path):
    from src.setup.state import save_state
    state = WizardState(completed_steps=[1, 2, 3, 4, 5, 6, 7],
                        channels=["telegram"], telegram_token="tok",
                        allowed_user_ids=[1], selected_clis=["claude"],
                        search_mode="fts5", update_notifications=True,
                        deploy_mode="foreground")
    state_path = str(tmp_path / "state.json")
    save_state(state, state_path)
    with patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as mock_s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock, return_value=[]), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock, return_value=None), \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, reset=True, cwd=str(tmp_path))
    # step_1 must be called because state was reset (steps re-run)
    mock_s1.assert_called_once()


# ── step_8_launch ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step8_writes_config_and_env(tmp_path):
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7, 8],
        channels=["telegram"], telegram_token="TOK",
        allowed_user_ids=[111], selected_clis=["claude"],
        search_mode="fts5", update_notifications=True,
        deploy_mode="foreground",
    )
    with patch("src.setup.wizard.write_config_toml") as mock_cfg, \
         patch("src.setup.wizard.write_env_file") as mock_env, \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("os.execv"):
        await wizard.step_9_launch(state, str(tmp_path), [])
    mock_cfg.assert_called_once()
    mock_env.assert_called_once()
    # env_file content passed as second positional arg
    env_arg = mock_env.call_args[0][1]
    assert env_arg.get("TELEGRAM_BOT_TOKEN") == "TOK"
    assert env_arg.get("ALLOWED_USER_IDS") == "111"


@pytest.mark.asyncio
async def test_step8_systemd_calls_systemctl(tmp_path):
    state = WizardState(
        completed_steps=list(range(1, 9)),
        channels=["telegram"], telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="systemd",
    )
    with patch("src.setup.wizard.write_config_toml"), \
         patch("src.setup.wizard.write_env_file"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_systemd_unit") as mock_unit, \
         patch("subprocess.run") as mock_run:
        await wizard.step_9_launch(state, str(tmp_path), [])
    mock_unit.assert_called_once()
    assert mock_run.call_count >= 1


@pytest.mark.asyncio
async def test_step8_docker_calls_compose(tmp_path):
    state = WizardState(
        completed_steps=list(range(1, 9)),
        channels=["telegram"], telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="docker",
    )
    with patch("src.setup.wizard.write_config_toml"), \
         patch("src.setup.wizard.write_env_file"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_docker_compose") as mock_dc, \
         patch("subprocess.run") as mock_run:
        await wizard.step_9_launch(state, str(tmp_path), [])
    mock_dc.assert_called_once()
    mock_run.assert_called_once()
