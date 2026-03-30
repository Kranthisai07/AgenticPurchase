"""
MCPClientSingleton — Model Context Protocol client for tool calling.
Provides a single shared MCP session across the application lifetime.
"""
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_instance: "MCPClient | None" = None


class MCPClient:
    """
    Thin wrapper around MCP tool invocation.
    Used when agents need to call external tools via the MCP protocol.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    async def call_tool(
        self,
        server: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke an MCP tool on a given server."""
        logger.debug("mcp.call_tool", server=server, tool=tool_name)
        # MCP tool invocation — actual transport handled by server config
        raise NotImplementedError(
            f"MCP tool '{tool_name}' on server '{server}' called — "
            "connect to a live MCP server in production"
        )

    async def close(self) -> None:
        self._sessions.clear()


def get_mcp_client() -> MCPClient:
    global _instance
    if _instance is None:
        _instance = MCPClient()
    return _instance
