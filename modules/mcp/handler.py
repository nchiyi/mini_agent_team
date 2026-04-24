# modules/mcp/handler.py
"""
MCP module handler. Reads config/mcp_servers.toml, connects to MCP servers,
and dispatches gateway slash commands to the appropriate tool.
"""
import logging
from pathlib import Path
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/mcp_servers.toml")
_clients: dict[str, "McpClient"] = {}           # server_name → McpClient
_cmd_to_server: dict[str, str] = {}             # slash_cmd → server_name
_initialized = False


def _load_config() -> list["McpServerConfig"]:
    from modules.mcp.client import McpServerConfig
    if not _CONFIG_PATH.exists():
        return []
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore

    with open(_CONFIG_PATH, "rb") as f:
        raw = tomllib.load(f)

    servers = []
    for s in raw.get("servers", []):
        servers.append(McpServerConfig(
            name=s["name"],
            transport=s.get("transport", "stdio"),
            command=s.get("command", []),
            env=s.get("env", {}),
            url=s.get("url", ""),
            commands=s.get("commands", []),
        ))
    return servers


async def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    from modules.mcp.client import McpClient
    servers = _load_config()
    if not servers:
        logger.info("No MCP servers configured in %s", _CONFIG_PATH)
        return

    for cfg in servers:
        client = McpClient(cfg)
        try:
            await client.connect()
            _clients[cfg.name] = client
            for cmd in cfg.commands:
                _cmd_to_server[cmd] = cfg.name
            tools = await client.list_tools()
            logger.info("MCP server '%s' connected: %d tools", cfg.name, len(tools))
        except Exception:
            logger.error("Failed to connect MCP server '%s'", cfg.name, exc_info=True)


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    try:
        await _ensure_initialized()
    except Exception as e:
        yield f"MCP init error: {e}"
        return

    if command == "/mcp-list":
        if not _clients:
            yield "No MCP servers connected. Add servers to config/mcp_servers.toml."
            return
        lines = ["Connected MCP servers:"]
        for name, client in _clients.items():
            tools = await client.list_tools()
            tool_names = ", ".join(t.name for t in tools) or "(no tools)"
            lines.append(f"\n• {name} [{len(tools)} tools]: {tool_names}")
        yield "\n".join(lines)
        return

    if command == "/mcp":
        parts = args.strip().split(None, 2)
        if len(parts) < 2:
            yield "Usage: /mcp <server> <tool> [args_json]"
            return
        server_name, tool_name = parts[0], parts[1]
        raw_args = parts[2] if len(parts) > 2 else "{}"
        client = _clients.get(server_name)
        if not client:
            yield f"Unknown MCP server '{server_name}'. Use /mcp-list to see connected servers."
            return
        try:
            import json
            tool_args = json.loads(raw_args)
        except Exception:
            tool_args = {"input": raw_args}
        try:
            result = await client.call_tool(tool_name, tool_args)
            yield result or "(empty response)"
        except Exception as e:
            yield f"MCP tool error: {e}"
        return

    server_name = _cmd_to_server.get(command)
    if not server_name:
        yield f"No MCP server registered for command '{command}'."
        return

    client = _clients.get(server_name)
    if not client:
        yield f"MCP server '{server_name}' not available."
        return

    tools = await client.list_tools()
    if not tools:
        yield f"Server '{server_name}' has no tools."
        return

    # Use first tool with a single-input schema, or just the first tool
    tool = tools[0]
    props = tool.input_schema.get("properties", {})
    if props:
        first_key = next(iter(props))
        tool_args = {first_key: args.strip()}
    else:
        tool_args = {}

    try:
        result = await client.call_tool(tool.name, tool_args)
        yield result or "(empty response)"
    except Exception as e:
        yield f"MCP call error: {e}"
