"""Facade for the agent_sdk package -- re-exports the MCP server entrypoint and typed error types.

Decision 104 sole-home discipline: import the server entrypoint and error types from here.
"""

from __future__ import annotations

from scripts.agent_sdk.errors import (
    AgentToolError,
    ReaderBoundaryError,
    ReaderRuntimeError,
    UnknownActionError,
    VersionMismatchError,
    map_reader_error,
)
from scripts.agent_sdk.mcp_server import build_tool_registry, create_server, main

__all__ = [
    "AgentToolError",
    "ReaderBoundaryError",
    "ReaderRuntimeError",
    "UnknownActionError",
    "VersionMismatchError",
    "map_reader_error",
    "build_tool_registry",
    "create_server",
    "main",
]
