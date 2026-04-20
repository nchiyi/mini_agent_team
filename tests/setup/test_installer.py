import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from src.setup.installer import is_cli_installed, install_cli, install_ollama, progress_reporter


def test_is_cli_installed_found():
    with patch("shutil.which", return_value="/usr/bin/claude"):
        assert is_cli_installed("claude") is True


def test_is_cli_installed_not_found():
    with patch("shutil.which", return_value=None):
        assert is_cli_installed("claude") is False


@pytest.mark.asyncio
async def test_install_cli_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        name, success = await install_cli("claude")
    assert name == "claude"
    assert success is True


@pytest.mark.asyncio
async def test_install_cli_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        name, success = await install_cli("codex")
    assert name == "codex"
    assert success is False


@pytest.mark.asyncio
async def test_install_cli_unknown_returns_false():
    name, success = await install_cli("unknown-tool")
    assert name == "unknown-tool"
    assert success is False


@pytest.mark.asyncio
async def test_install_ollama_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await install_ollama()
    assert result is True


@pytest.mark.asyncio
async def test_install_ollama_install_fails():
    mock_proc_fail = AsyncMock()
    mock_proc_fail.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_fail):
        result = await install_ollama()
    assert result is False


@pytest.mark.asyncio
async def test_install_ollama_pull_fails():
    mock_install = AsyncMock()
    mock_install.returncode = 0
    mock_pull = AsyncMock()
    mock_pull.returncode = 1
    with patch("asyncio.create_subprocess_exec", side_effect=[mock_install, mock_pull]):
        result = await install_ollama()
    assert result is False


@pytest.mark.asyncio
async def test_progress_reporter_exits_when_tasks_done():
    task = asyncio.create_task(asyncio.sleep(0))
    await task  # mark done
    # Should return without blocking
    await asyncio.wait_for(progress_reporter([task], ["claude"], interval=1), timeout=3)
