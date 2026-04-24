# tests/modules/test_mcp.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_mcp_list_no_config(tmp_path, monkeypatch):
    """With no mcp_servers.toml, /mcp-list returns helpful message."""
    import modules.mcp.handler as handler_mod
    monkeypatch.setattr(handler_mod, "_CONFIG_PATH", tmp_path / "mcp_servers.toml")
    monkeypatch.setattr(handler_mod, "_clients", {})
    monkeypatch.setattr(handler_mod, "_cmd_to_server", {})
    monkeypatch.setattr(handler_mod, "_initialized", False)

    chunks = []
    async for chunk in handler_mod.handle("/mcp-list", "", 1, "telegram"):
        chunks.append(chunk)
    output = "".join(chunks)
    assert "No MCP servers" in output or "mcp_servers.toml" in output


async def test_mcp_generic_no_server(tmp_path, monkeypatch):
    """Unknown server in /mcp call returns error."""
    import modules.mcp.handler as handler_mod
    monkeypatch.setattr(handler_mod, "_CONFIG_PATH", tmp_path / "mcp_servers.toml")
    monkeypatch.setattr(handler_mod, "_clients", {})
    monkeypatch.setattr(handler_mod, "_cmd_to_server", {})
    monkeypatch.setattr(handler_mod, "_initialized", True)

    chunks = []
    async for chunk in handler_mod.handle("/mcp", "nonexistent list_files {}", 1, "telegram"):
        chunks.append(chunk)
    output = "".join(chunks)
    assert "Unknown MCP server" in output or "Usage" in output


async def test_mcp_client_config_parse(tmp_path):
    """McpServerConfig dataclass stores all fields correctly."""
    from modules.mcp.client import McpServerConfig
    cfg = McpServerConfig(
        name="test",
        transport="stdio",
        command=["npx", "server"],
        env={"FOO": "bar"},
        url="",
        commands=["/test"],
    )
    assert cfg.name == "test"
    assert cfg.transport == "stdio"
    assert cfg.commands == ["/test"]
