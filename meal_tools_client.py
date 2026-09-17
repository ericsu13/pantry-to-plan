"""Async stdio MCP client for the local Pantry-to-Plan meal tools server."""

from __future__ import annotations

from contextlib import AsyncExitStack
from datetime import timedelta
import json
from pathlib import Path
import sys
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_models import MCPToolDefinition


ROOT = Path(__file__).resolve().parent


class MealToolsClient(Protocol):
    async def list_tools(self) -> list[MCPToolDefinition]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class MCPToolError(RuntimeError):
    pass


class StdioMealToolsClient:
    """One MCP session spanning a complete agent run."""

    def __init__(
        self,
        *,
        server_path: Path | None = None,
        timeout_seconds: float = 10.0,
    ):
        self.server_path = server_path or ROOT / "meal_tools_server.py"
        self.timeout_seconds = timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "StdioMealToolsClient":
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_path)],
            cwd=ROOT,
        )
        read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("MCP client must be used inside 'async with'.")
        return self._session

    async def list_tools(self) -> list[MCPToolDefinition]:
        response = await self._require_session().list_tools()
        return [
            MCPToolDefinition(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
            )
            for tool in response.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._require_session().call_tool(
            name,
            arguments,
            read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
        )
        if result.isError:
            message = " ".join(
                str(getattr(item, "text", "")) for item in result.content
            ).strip()
            raise MCPToolError(message or f"MCP tool {name!r} failed.")
        if result.structuredContent is not None:
            return dict(result.structuredContent)
        text_parts = [
            item.text for item in result.content if getattr(item, "type", None) == "text"
        ]
        if not text_parts:
            return {}
        try:
            parsed = json.loads("".join(text_parts))
        except json.JSONDecodeError as exc:
            raise MCPToolError(f"MCP tool {name!r} returned non-JSON content.") from exc
        if not isinstance(parsed, dict):
            raise MCPToolError(f"MCP tool {name!r} returned a non-object result.")
        return parsed

