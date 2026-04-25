import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.installer import is_cli_installed, install_cli, install_ollama, progress_reporter


def test_is_cli_installed_found():
    with patch("shutil.which", return_value="/usr/bin/claude"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="v2.1.0\n", stderr="")):
        installed, version = is_cli_installed("claude")
    assert installed is True
    assert isinstance(version, str)


def test_is_cli_installed_not_found():
    with patch("shutil.which", return_value=None):
        installed, version = is_cli_installed("claude")
    assert installed is False
    assert version == ""


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


# ========== ACP Package Tests ==========
from src.setup.installer import ACP_PACKAGES, is_acp_installed, install_acp_foreground, is_npm_available


def test_acp_packages_has_claude_and_codex():
    assert "claude" in ACP_PACKAGES
    assert "codex" in ACP_PACKAGES
    assert "gemini" not in ACP_PACKAGES


def test_is_acp_installed_found():
    with patch("shutil.which", return_value="/usr/local/bin/claude-agent-acp"):
        installed, binary = is_acp_installed("claude")
    assert installed is True
    assert binary == "claude-agent-acp"


def test_is_acp_installed_not_found():
    with patch("shutil.which", return_value=None):
        installed, binary = is_acp_installed("claude")
    assert installed is False
    assert binary == "claude-agent-acp"


def test_is_acp_installed_no_package_needed():
    # gemini has no ACP package — treated as "already satisfied"
    installed, binary = is_acp_installed("gemini")
    assert installed is True
    assert binary == ""


def test_is_npm_available_found():
    with patch("shutil.which", return_value="/usr/bin/npm"):
        assert is_npm_available() is True


def test_is_npm_available_not_found():
    with patch("shutil.which", return_value=None):
        assert is_npm_available() is False


@pytest.mark.asyncio
async def test_install_acp_foreground_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    with patch("shutil.which", return_value="/usr/bin/npm"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await install_acp_foreground("claude")
    assert result is True


@pytest.mark.asyncio
async def test_install_acp_foreground_no_npm():
    with patch("shutil.which", return_value=None):
        result = await install_acp_foreground("claude")
    assert result is False


@pytest.mark.asyncio
async def test_install_acp_foreground_unknown_cli():
    result = await install_acp_foreground("gemini")
    assert result is True  # no-op, always succeeds


@pytest.mark.asyncio
async def test_install_acp_foreground_npm_fails():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    with patch("shutil.which", return_value="/usr/bin/npm"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await install_acp_foreground("codex")
    assert result is False
