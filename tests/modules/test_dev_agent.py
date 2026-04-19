import asyncio, pytest
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_dev_agent_empty_args_shows_usage(monkeypatch):
    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_dev_agent_runs_subprocess(monkeypatch, tmp_path):
    monkeypatch.setenv("DEV_AGENT_BINARY", "echo")
    monkeypatch.setenv("DEV_AGENT_ARGS", "")
    monkeypatch.setenv("DEV_AGENT_TIMEOUT", "10")

    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "hello from dev_agent", 1, "tg"))
    combined = "".join(chunks)
    assert "hello from dev_agent" in combined


async def test_dev_agent_binary_not_found(monkeypatch):
    monkeypatch.setenv("DEV_AGENT_BINARY", "totally_nonexistent_binary_xyz")
    monkeypatch.setenv("DEV_AGENT_ARGS", "")

    import importlib
    import modules.dev_agent.handler as dah
    importlib.reload(dah)

    chunks = await _collect(dah.handle("/dev", "do something", 1, "tg"))
    combined = "".join(chunks)
    assert "not found" in combined.lower() or "error" in combined.lower()
