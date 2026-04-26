"""Tests for src/setup/preflight.py"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.setup.preflight import (
    _check_disk,
    _check_python,
    _check_venv,
    _check_network,
    run_preflight,
    _MIN_PYTHON,
    _MIN_DISK_GB,
)


# ---------------------------------------------------------------------------
# _check_python
# ---------------------------------------------------------------------------

class TestCheckPython:
    def test_passes_when_version_sufficient(self):
        """Current interpreter already satisfies the constraint (3.11+)."""
        ok, msg = _check_python()
        v = sys.version_info
        if (v.major, v.minor) >= _MIN_PYTHON:
            assert ok is True
            assert "Python" in msg

    def test_fails_when_version_too_old(self):
        """Simulate an old interpreter version."""
        import types as _types
        fake_vi = _types.SimpleNamespace(major=3, minor=9, micro=0)
        mock_sys = MagicMock()
        mock_sys.version_info = fake_vi
        mock_sys.exit.side_effect = SystemExit(1)
        with patch("src.setup.preflight.sys", mock_sys):
            ok, msg = _check_python()
        assert ok is False
        assert "3.9" in msg
        assert "pyenv install" in msg


# ---------------------------------------------------------------------------
# _check_disk
# ---------------------------------------------------------------------------

class TestCheckDisk:
    def test_passes_when_disk_sufficient(self):
        """Mock plenty of free space."""
        gb = _MIN_DISK_GB + 10
        fake_stat = MagicMock(free=int(gb * 1024**3))
        with patch("shutil.disk_usage", return_value=fake_stat):
            ok, msg = _check_disk()
        assert ok is True
        assert "GB free" in msg

    def test_fails_when_disk_insufficient(self):
        """Mock insufficient free space."""
        gb = _MIN_DISK_GB - 1
        fake_stat = MagicMock(free=int(gb * 1024**3))
        with patch("shutil.disk_usage", return_value=fake_stat):
            ok, msg = _check_disk()
        assert ok is False
        assert "Free up space" in msg or "only" in msg


# ---------------------------------------------------------------------------
# _check_network
# ---------------------------------------------------------------------------

class TestCheckNetwork:
    @pytest.mark.asyncio
    async def test_all_reachable(self):
        """All hosts return True — every result should be ok."""
        async def fake_open(*a, **kw):
            writer = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return AsyncMock(), writer

        with patch("asyncio.open_connection", side_effect=fake_open):
            results = await _check_network()

        assert all(ok for ok, _ in results)
        assert all("reachable" in msg for _, msg in results)

    @pytest.mark.asyncio
    async def test_one_unreachable_fails(self):
        """One host times out — that item should be not-ok."""
        import asyncio as _asyncio

        call_count = {"n": 0}

        async def partial_open(host, port):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionRefusedError("forced failure")
            writer = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return AsyncMock(), writer

        with patch("asyncio.open_connection", side_effect=partial_open):
            results = await _check_network()

        # first host must fail
        assert results[0][0] is False
        assert "unreachable" in results[0][1]
        # remaining hosts pass
        assert all(ok for ok, _ in results[1:])

    @pytest.mark.asyncio
    async def test_all_unreachable(self):
        """All hosts fail — every result should be not-ok."""
        async def always_fail(*a, **kw):
            raise ConnectionRefusedError("forced failure")

        with patch("asyncio.open_connection", side_effect=always_fail):
            results = await _check_network()

        assert all(not ok for ok, _ in results)


# ---------------------------------------------------------------------------
# _check_venv
# ---------------------------------------------------------------------------

class TestCheckVenv:
    def test_passes_when_venv_exists(self, tmp_path):
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python3").touch()
        ok, msg = _check_venv(str(tmp_path))
        assert ok is True

    def test_fails_when_venv_missing(self, tmp_path):
        ok, msg = _check_venv(str(tmp_path))
        assert ok is False
        assert "python3 -m venv venv" in msg


# ---------------------------------------------------------------------------
# run_preflight (integration-style)
# ---------------------------------------------------------------------------

class TestRunPreflight:
    """Integration tests that wire the whole function with selective mocks."""

    def _good_disk(self):
        return MagicMock(free=int((_MIN_DISK_GB + 20) * 1024**3))

    def _bad_disk(self):
        return MagicMock(free=int(1 * 1024**3))

    async def _network_ok(self):
        return [(True, f"host{i} reachable") for i in range(4)]

    async def _network_fail(self):
        return [(False, f"host{i} unreachable — check network/firewall and retry") for i in range(4)]

    @pytest.mark.asyncio
    async def test_all_pass(self, tmp_path):
        """All checks green — should NOT raise SystemExit."""
        # create venv
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python3").touch()

        with (
            patch("shutil.disk_usage", return_value=self._good_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_ok),
        ):
            # Should complete without raising
            await run_preflight(str(tmp_path))

    @pytest.mark.asyncio
    async def test_disk_fail_exits(self, tmp_path):
        """Insufficient disk → sys.exit(1)."""
        # create venv so that's not the failing check
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python3").touch()

        with (
            patch("shutil.disk_usage", return_value=self._bad_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_ok),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await run_preflight(str(tmp_path))
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_python_version_fail_exits(self, tmp_path):
        """Old Python version → sys.exit(1)."""
        import types as _types
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python3").touch()

        fake_vi = _types.SimpleNamespace(major=3, minor=9, micro=0)
        mock_sys = MagicMock()
        mock_sys.version_info = fake_vi
        mock_sys.exit.side_effect = SystemExit(1)
        with (
            patch("src.setup.preflight.sys", mock_sys),
            patch("shutil.disk_usage", return_value=self._good_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_ok),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await run_preflight(str(tmp_path))
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_network_fail_exits(self, tmp_path):
        """Unreachable network → sys.exit(1), but all results printed first."""
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python3").touch()

        with (
            patch("shutil.disk_usage", return_value=self._good_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_fail),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await run_preflight(str(tmp_path))
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_venv_missing_exits(self, tmp_path):
        """Missing venv → sys.exit(1)."""
        # Do NOT create venv
        with (
            patch("shutil.disk_usage", return_value=self._good_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_ok),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await run_preflight(str(tmp_path))
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_multiple_failures_all_printed_before_exit(self, tmp_path, capsys):
        """Ensure ALL results are printed even when multiple checks fail."""
        # No venv + bad disk
        with (
            patch("shutil.disk_usage", return_value=self._bad_disk()),
            patch("src.setup.preflight._check_network", side_effect=self._network_ok),
        ):
            with pytest.raises(SystemExit):
                await run_preflight(str(tmp_path))

        captured = capsys.readouterr()
        # Both the disk failure and venv failure messages must appear in output
        assert "GB free" in captured.out
        assert "venv not found" in captured.out
