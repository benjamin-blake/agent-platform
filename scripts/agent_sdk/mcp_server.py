"""READ-ONLY MCP stdio server projecting DuckLake NAMED_READS as agent tools (T0.8, Decision 81 cl.2).

On startup, calls DuckLakeReader.describe() ONCE and projects one MCP tool per returned verb -- the
tool list is DERIVED from the warehouse's own registry, never hand-maintained: adding a verb to
NAMED_READS surfaces a new tool automatically, with zero edits to this module. Projects nothing
else: no write verb, no infra/probe action, and no raw-SQL parameter (Decision 84 I-3 -- the
named-verb boundary only). A failed describe() at startup RAISES; there is no fallback to a
hardcoded verb list (Decision 55).

WRITE LEG DEFERRED (operator decision, round-1 plan critique): the write verbs' only prospective
bound was a module-level Python literal inside this agent-editable server, which is weaker than the
in-handler guard Decision 143 requires. This module therefore projects reads only.

KNOWN LIMITATION: the tool list is fetched once at process startup (stdio transport is one process
per session) -- a verb added to NAMED_READS after this process started surfaces only on the next
session (server restart). The derivation property still holds; freshness is per-session, not live.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import anyio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from scripts.agent_sdk.errors import AgentToolError, map_reader_error
from src.common.iceberg_reader import DuckLakeReader, ReaderInvokeError, make_reader

logger = logging.getLogger(__name__)

SERVER_NAME = "agent-platform-ducklake-reads"

# Decision 126 ambience mitigation: agents reach for whatever surface is most VISIBLE, not
# whichever is sanctioned. Every projected tool's description carries this cache-first guidance so
# a verb added to NAMED_READS later inherits it automatically -- applied once, here, by the shared
# projection template, never restated per-verb.
_CACHE_FIRST_NOTE = (
    " Prefer this named read over pulling the whole table into a local cache and re-querying it in "
    "Python (Decision 88 invariant (ii))."
)


def _tool_description(meta: dict[str, Any]) -> str:
    """Build one tool's description: the verb's own text plus the shared cache-first guidance."""
    return f"{meta['description']}{_CACHE_FIRST_NOTE}"


def build_tool_registry(verbs: dict[str, dict[str, Any]]) -> list[types.Tool]:
    """Project one MCP Tool per entry in *verbs* (a describe()-shaped verb -> schema mapping).

    Derived, not hand-maintained: this function iterates whatever *verbs* contains and must never
    filter against a local list of known verb names -- doing so would reinstate the
    hand-registration this design exists to eliminate.
    """
    return [
        types.Tool(name=verb, description=_tool_description(meta), inputSchema=meta["params_schema"])
        for verb, meta in verbs.items()
    ]


def _invoke_verb(reader: DuckLakeReader, verb: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Call the reader's named() verb, mapping a boundary failure onto a typed exception.

    Never swallows an error: a ReaderInvokeError is mapped via errors.map_reader_error and
    re-raised, so a boundary rejection surfaces as a distinct type rather than a generic failure.
    """
    try:
        return reader.named(verb, **arguments)
    except ReaderInvokeError as exc:
        raise map_reader_error(exc) from exc


def create_server(reader: DuckLakeReader | None = None) -> Server:
    """Build the MCP server: fetch the verb schema ONCE and register the derived tool surface.

    Fails loudly (Decision 55): a describe() failure (unreachable reader, credentials, a boundary
    error) raises here rather than falling back to a hardcoded verb list or starting with a
    partial surface -- there is no try/except around the describe() call below.
    """
    # make_reader() is annotated -> Reader (the Protocol, which deliberately does not declare
    # describe() -- see src/common/iceberg_reader.py's Reader docstring) but only ever
    # constructs a DuckLakeReader in practice; cast narrows the type at this one call site
    # rather than widening the Protocol by omission.
    active_reader = reader if reader is not None else cast(DuckLakeReader, make_reader())
    verbs = active_reader.describe()

    tools = build_tool_registry(verbs)
    tool_by_name = {tool.name: tool for tool in tools}

    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in tool_by_name:
            raise AgentToolError(f"unknown tool {name!r}: expected one of {sorted(tool_by_name)}")
        rows = _invoke_verb(active_reader, name, arguments)
        return {"rows": rows, "row_count": len(rows)}

    return server


async def _run_stdio(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(notification_options=NotificationOptions()),
        )


def main() -> None:
    server = create_server()
    anyio.run(_run_stdio, server)


if __name__ == "__main__":
    main()
