# modules/mcp/client.py
"""
MCP JSON-RPC client supporting stdio and SSE transports.
Uses the official `mcp` Python SDK when available.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    name: str
    transport: str          # "stdio" | "sse"
    command: list[str] = field(default_factory=list)   # stdio only
    env: dict[str, str] = field(default_factory=dict)  # stdio only
    url: str = ""           # SSE only
    commands: list[str] = field(default_factory=list)  # gateway slash commands


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict


class McpClient:
    """Lazy-connecting MCP client for a single server."""

    def __init__(self, cfg: McpServerConfig):
        self._cfg = cfg
        self._tools: list[McpTool] | None = None
        self._session = None
        self._ctx = None

    async def connect(self) -> None:
        """Establish connection and cache tool list."""
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore
            from mcp.client.stdio import stdio_client             # type: ignore
            from mcp.client.sse import sse_client                 # type: ignore
        except ImportError:
            raise RuntimeError("mcp package not installed — pip install mcp")

        if self._cfg.transport == "stdio":
            env = {**os.environ, **self._cfg.env}
            params = StdioServerParameters(
                command=self._cfg.command[0],
                args=self._cfg.command[1:],
                env=env,
            )
            self._ctx = stdio_client(params)
        elif self._cfg.transport == "sse":
            self._ctx = sse_client(self._cfg.url)
        else:
            raise ValueError(f"Unknown transport: {self._cfg.transport}")

        read, write = await self._ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        await self._refresh_tools()

    async def _refresh_tools(self) -> None:
        result = await self._session.list_tools()
        self._tools = [
            McpTool(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
            )
            for t in result.tools
        ]

    async def list_tools(self) -> list[McpTool]:
        if self._session is None:
            await self.connect()
        return self._tools or []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            await self.connect()
        result = await self._session.call_tool(name, arguments)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
        self._session = None
        self._ctx = None
        self._tools = None
