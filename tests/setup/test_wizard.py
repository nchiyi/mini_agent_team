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
    # "bad" token → invalid, "good" token → valid, then "y" to confirm identity.
    responses = iter(["bad", "good", "y"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    valid_result = MagicMock(valid=True, skipped=False, bot_username="mybot", bot_id=1)
    side_effects = [MagicMock(valid=False, skipped=False, error_category=None), valid_result]
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
    # New behaviour: auto-capture prompts for confirmation — answer "y".
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "y")
    with patch("src.setup.wizard._capture_telegram_user_id", return_value=99999):
        await wizard.step_3_allowlist(state)
    assert state.allowed_user_ids == [99999]


@pytest.mark.asyncio
async def test_step3_discord_manual(monkeypatch):
    # Discord channel with token but capture returns None → user types ID manually.
    state = WizardState(
        channels=["discord"], completed_steps=[1, 2], discord_token="disc-tok"
    )
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "777")
    with patch("src.setup.wizard._capture_discord_user_id", return_value=None):
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
    # is_cli_installed now returns (bool, version_str)
    with patch("src.setup.wizard.is_cli_installed", return_value=(True, "v1.0")):
        await wizard.step_4_clis(state)
    assert state.selected_clis == ["claude", "codex"]
    assert 4 in state.completed_steps


@pytest.mark.asyncio
async def test_step4_queues_install_for_missing(monkeypatch):
    """Missing CLIs are now installed in the foreground (not background)."""
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "claude")
    with patch("src.setup.wizard.is_cli_installed", return_value=(False, "")):
        with patch(
            "src.setup.wizard.install_cli_foreground",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await wizard.step_4_clis(state)
    assert "claude" in state.selected_clis


@pytest.mark.asyncio
async def test_step4_defaults_to_claude_on_empty(monkeypatch):
    state = WizardState(completed_steps=[1, 2, 3])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "")
    with patch("src.setup.wizard.is_cli_installed", return_value=(True, "v1.0")):
        await wizard.step_4_clis(state)
    assert "claude" in state.selected_clis


@pytest.mark.asyncio
async def test_step4_skipped_if_done():
    state = WizardState(completed_steps=[1, 2, 3, 4], selected_clis=["codex"])
    await wizard.step_4_clis(state)
    assert state.selected_clis == ["codex"]


# ── Step 4.5: ACP ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step4_5_orchestrator_claude(monkeypatch):
    """Mode 1 with claude as primary → only asks about claude-agent-acp."""
    state = WizardState(selected_clis=["claude", "codex"])
    call_count = {"n": 0}

    def fake_prompt(*a, **kw):
        call_count["n"] += 1
        return "1" if call_count["n"] == 1 else "Y"  # 1st=mode, rest=install confirm

    monkeypatch.setattr("src.setup.wizard._prompt", fake_prompt)
    with patch("src.setup.wizard.is_acp_installed", return_value=(False, "claude-agent-acp")), \
         patch("src.setup.wizard.is_npm_available", return_value=True), \
         patch("src.setup.wizard.install_acp_foreground", new_callable=AsyncMock, return_value=True):
        await wizard.step_4_5_acp(state)
    assert state.acp_mode == "orchestrator"
    assert state.installed_acp == ["claude-agent-acp"]
    assert "acp_setup.done" in state.completed


@pytest.mark.asyncio
async def test_step4_5_gateway_installs_all(monkeypatch):
    """Mode 2 with claude + codex → asks about both ACP packages."""
    state = WizardState(selected_clis=["claude", "codex"])
    call_count = {"n": 0}

    def fake_prompt(*a, **kw):
        call_count["n"] += 1
        return "2" if call_count["n"] == 1 else "Y"

    monkeypatch.setattr("src.setup.wizard._prompt", fake_prompt)
    with patch("src.setup.wizard.is_acp_installed", return_value=(False, "some-acp")), \
         patch("src.setup.wizard.is_npm_available", return_value=True), \
         patch("src.setup.wizard.install_acp_foreground", new_callable=AsyncMock, return_value=True):
        await wizard.step_4_5_acp(state)
    assert state.acp_mode == "gateway"
    assert "acp_setup.done" in state.completed
    assert len(state.installed_acp) == 2


@pytest.mark.asyncio
async def test_step4_5_gemini_primary_mode1_skips(monkeypatch):
    """Mode 1 with gemini as primary → no ACP needed, step skips cleanly."""
    state = WizardState(selected_clis=["gemini"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "1")
    with patch("src.setup.wizard.is_acp_installed", return_value=(True, "")):
        await wizard.step_4_5_acp(state)
    assert state.acp_mode == "orchestrator"
    assert state.installed_acp == []
    assert "acp_setup.done" in state.completed


@pytest.mark.asyncio
async def test_step4_5_all_already_installed(monkeypatch):
    """All ACP packages present → step completes without prompting for install."""
    state = WizardState(selected_clis=["claude", "codex"])
    prompts = []

    def capturing_prompt(msg, *a, **kw):
        prompts.append(msg)
        return "2"  # mode 2, but no install prompt should follow

    monkeypatch.setattr("src.setup.wizard._prompt", capturing_prompt)
    with patch("src.setup.wizard.is_acp_installed", return_value=(True, "some-acp")):
        await wizard.step_4_5_acp(state)
    # Only the mode selection prompt should have appeared
    assert len(prompts) == 1
    assert "acp_setup.done" in state.completed


@pytest.mark.asyncio
async def test_step4_5_npm_missing_shows_manual_and_continues(monkeypatch, capsys):
    """npm not found → warns, shows manual command, does not abort."""
    state = WizardState(selected_clis=["claude"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "1")
    with patch("src.setup.wizard.is_acp_installed", return_value=(False, "claude-agent-acp")), \
         patch("src.setup.wizard.is_npm_available", return_value=False):
        await wizard.step_4_5_acp(state)
    out = capsys.readouterr().out
    assert "npm" in out
    assert "acp_setup.done" in state.completed


@pytest.mark.asyncio
async def test_step4_5_skipped_if_done():
    """Step is idempotent — does nothing if already completed."""
    from src.setup.state import mark_micro_step_done
    state = WizardState(selected_clis=["claude"])
    mark_micro_step_done(state, "acp_setup.done")
    state.acp_mode = "orchestrator"
    await wizard.step_4_5_acp(state)
    assert state.acp_mode == "orchestrator"  # unchanged


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
    """Ollama is now installed in the foreground; step_5 always returns None."""
    state = WizardState(completed_steps=[1, 2, 3, 4])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: "2")
    with patch(
        "src.setup.wizard.install_ollama_foreground",
        new_callable=AsyncMock,
        return_value=True,
    ):
        task = await wizard.step_5_search(state)
    assert state.search_mode == "fts5+embedding"
    # Foreground install — no background task returned
    assert task is None


@pytest.mark.asyncio
async def test_step5_ollama_fails_fallback_fts5(monkeypatch):
    """Ollama install fails → user accepts FTS5 fallback → step completes."""
    state = WizardState(completed_steps=[1, 2, 3, 4])
    # choice=2 then "y" to accept FTS5 fallback
    responses = iter(["2", "y"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    with patch(
        "src.setup.wizard.install_ollama_foreground",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await wizard.step_5_search(state)
    assert state.search_mode == "fts5"
    assert 5 in state.completed_steps


@pytest.mark.asyncio
async def test_step5_ollama_fails_user_declines_fallback(monkeypatch):
    """Ollama install fails → user declines FTS5 fallback → step NOT marked done."""
    state = WizardState(completed_steps=[1, 2, 3, 4])
    responses = iter(["2", "n"])
    monkeypatch.setattr("src.setup.wizard._prompt", lambda *a, **kw: next(responses))
    with patch(
        "src.setup.wizard.install_ollama_foreground",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await wizard.step_5_search(state)
    assert 5 not in state.completed_steps


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
    with patch("src.setup.wizard.subprocess.run", return_value=MagicMock(returncode=0)):
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
    with patch("src.setup.wizard.run_preflight", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_5_acp", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock) as mock_launch:
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
    with patch("src.setup.wizard.run_preflight", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_1_channel", new_callable=AsyncMock) as mock_s1, \
         patch("src.setup.wizard.step_2_token", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_3_allowlist", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_clis", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_4_5_acp", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_5_search", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_6_optional", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_7_updates", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_8_deploy", new_callable=AsyncMock), \
         patch("src.setup.wizard.step_9_launch", new_callable=AsyncMock):
        await wizard.run_wizard(state_path=state_path, reset=True, cwd=str(tmp_path))
    # step_1 must be called because state was reset (steps re-run)
    mock_s1.assert_called_once()


# ── step_9_launch ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step8_writes_config_and_env(tmp_path):
    """Foreground mode: writes config/env then runs smoke test."""
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7, 8],
        channels=["telegram"], telegram_token="TOK",
        allowed_user_ids=[111], selected_clis=["claude"],
        search_mode="fts5", update_notifications=True,
        deploy_mode="foreground",
    )
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: iter([])
    mock_proc.returncode = 0

    with patch("src.setup.wizard.write_config_with_diff") as mock_cfg, \
         patch("src.setup.wizard.write_env_with_diff") as mock_env, \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.save_state"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("src.setup.wizard.run_smoke_test", new_callable=AsyncMock, return_value=False), \
         patch("sys.exit"):
        await wizard.step_9_launch(state, str(tmp_path))
    mock_cfg.assert_called_once()
    mock_env.assert_called_once()
    # New API: write_env_with_diff receives (path, content_str, label=...)
    env_path_arg = mock_env.call_args[0][0]
    env_content_arg = mock_env.call_args[0][1]
    assert "TELEGRAM_BOT_TOKEN" in env_content_arg
    assert "TOK" in env_content_arg


@pytest.mark.asyncio
async def test_step8_allow_all_users_written_to_env(tmp_path):
    """When state.data['allow_all_users'] is True, .env must contain ALLOW_ALL_USERS=true."""
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7, 8],
        channels=["telegram"], telegram_token="TOK",
        allowed_user_ids=[],  # empty — operator chose allow-all
        selected_clis=["claude"],
        search_mode="fts5", update_notifications=True,
        deploy_mode="foreground",
    )
    state.data["allow_all_users"] = True

    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: iter([])
    mock_proc.returncode = 0

    with patch("src.setup.wizard.write_config_with_diff"), \
         patch("src.setup.wizard.write_env_with_diff") as mock_env, \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.save_state"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("src.setup.wizard.run_smoke_test", new_callable=AsyncMock, return_value=False), \
         patch("sys.exit"):
        await wizard.step_9_launch(state, str(tmp_path))

    env_content = mock_env.call_args[0][1]
    assert "ALLOW_ALL_USERS" in env_content
    assert "true" in env_content
    assert "ALLOWED_USER_IDS" not in env_content  # no user IDs → should not be emitted


@pytest.mark.asyncio
async def test_step8_allow_all_users_not_written_when_false(tmp_path):
    """When allow_all_users is not set, .env must NOT contain ALLOW_ALL_USERS."""
    state = WizardState(
        completed_steps=[1, 2, 3, 4, 5, 6, 7, 8],
        channels=["telegram"], telegram_token="TOK",
        allowed_user_ids=[42], selected_clis=["claude"],
        search_mode="fts5", update_notifications=True,
        deploy_mode="foreground",
    )

    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: iter([])
    mock_proc.returncode = 0

    with patch("src.setup.wizard.write_config_with_diff"), \
         patch("src.setup.wizard.write_env_with_diff") as mock_env, \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.save_state"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("src.setup.wizard.run_smoke_test", new_callable=AsyncMock, return_value=False), \
         patch("sys.exit"):
        await wizard.step_9_launch(state, str(tmp_path))

    env_content = mock_env.call_args[0][1]
    assert "ALLOW_ALL_USERS" not in env_content


@pytest.mark.asyncio
async def test_step8_systemd_calls_systemctl(tmp_path):
    """Systemd mode: writes unit, runs systemctl, runs smoke test."""
    state = WizardState(
        completed_steps=list(range(1, 9)),
        channels=["telegram"], telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="systemd",
    )
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: iter([])
    mock_proc.returncode = 0
    mock_proc.terminate = MagicMock()

    with patch("src.setup.wizard.write_config_with_diff"), \
         patch("src.setup.wizard.write_env_with_diff"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_systemd_unit") as mock_unit, \
         patch("subprocess.run") as mock_run, \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("src.setup.wizard.run_smoke_test", new_callable=AsyncMock, return_value=True):
        await wizard.step_9_launch(state, str(tmp_path))
    mock_unit.assert_called_once()
    assert mock_run.call_count >= 1


@pytest.mark.asyncio
async def test_step8_docker_calls_compose(tmp_path):
    """Docker mode: writes compose file, runs docker compose up, runs smoke test."""
    state = WizardState(
        completed_steps=list(range(1, 9)),
        channels=["telegram"], telegram_token="T",
        allowed_user_ids=[1], selected_clis=["claude"],
        search_mode="fts5", update_notifications=False,
        deploy_mode="docker",
    )
    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: iter([])
    mock_proc.returncode = 0
    mock_proc.terminate = MagicMock()

    with patch("src.setup.wizard.write_config_with_diff"), \
         patch("src.setup.wizard.write_env_with_diff"), \
         patch("src.setup.wizard.create_data_dirs"), \
         patch("src.setup.wizard.write_docker_compose") as mock_dc, \
         patch("subprocess.run") as mock_run, \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
         patch("src.setup.wizard.run_smoke_test", new_callable=AsyncMock, return_value=True):
        await wizard.step_9_launch(state, str(tmp_path))
    mock_dc.assert_called_once()
    mock_run.assert_called_once()
