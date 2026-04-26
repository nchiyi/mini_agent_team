import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.setup.installer import (
    is_cli_installed,
    ACP_PACKAGES, is_acp_installed, install_acp_foreground, is_npm_available,
)


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


# ========== ACP Package Tests ==========


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
