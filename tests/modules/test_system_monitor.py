import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_system_monitor_returns_cpu_mem_disk():
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.return_value = 42.5
    mem = MagicMock()
    mem.used = 2 * 1024**3
    mem.total = 8 * 1024**3
    mem.percent = 25.0
    mock_psutil.virtual_memory.return_value = mem
    disk = MagicMock()
    disk.used = 100 * 1024**3
    disk.total = 500 * 1024**3
    disk.percent = 20.0
    mock_psutil.disk_usage.return_value = disk

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        import importlib
        import modules.system_monitor.handler as smh
        importlib.reload(smh)

        chunks = await _collect(smh.handle("/sysinfo", "", 1, "tg"))
        combined = "".join(chunks)
        assert "42.5%" in combined
        assert "2.0GB" in combined
        assert "8.0GB" in combined
        assert "100.0GB" in combined


async def test_system_monitor_no_psutil_yields_install_hint():
    import sys
    saved = sys.modules.pop("psutil", None)
    try:
        import importlib
        import modules.system_monitor.handler as smh
        importlib.reload(smh)

        chunks = await _collect(smh.handle("/sysinfo", "", 1, "tg"))
        assert any("psutil" in c for c in chunks)
    finally:
        if saved:
            sys.modules["psutil"] = saved
