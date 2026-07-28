"""Behavioural tests for scripts/agent_sdk/mcp_server.py -- the derived MCP tool projection.

TestEndToEnd is the sole live-boundary test (it needs both @pytest.mark.integration, for the
conftest socket-block tripwire, AND @pytest.mark.aws, for conftest's _block_unmocked_aws_client
opt-out -- see tests/common/iceberg_reader/test_warehouse_parity.py for the same two-marker
pattern). It deliberately carries NO credentials-skip guard: absent credentials must fail this
test loudly, not silently pass it.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import types

from scripts.agent_sdk import errors as agent_errors
from scripts.agent_sdk.mcp_server import _invoke_verb, build_tool_registry, create_server
from src.common.iceberg_reader import ReaderInvokeError


def _verb_meta(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "table": "ops_recommendations",
        "description": "A named read verb.",
        "params": [],
        "paginable": False,
        "params_schema": {"type": "object", "properties": {}, "required": []},
    }
    meta.update(overrides)
    return meta


def _wire_input_schema(tool: types.Tool) -> dict[str, Any]:
    return tool.model_dump(by_alias=True)["inputSchema"]


class _StubReader:
    """A minimal DuckLakeReader stand-in: describe() returns a canned verb map; named() records calls."""

    def __init__(self, verbs: dict[str, dict], *, named_result: list | None = None, named_error: Exception | None = None):
        self._verbs = verbs
        self._named_result = named_result if named_result is not None else []
        self._named_error = named_error
        self.named_calls: list[tuple[str, dict]] = []

    def describe(self) -> dict:
        return self._verbs

    def named(self, verb: str, **params: Any) -> list[dict]:
        self.named_calls.append((verb, params))
        if self._named_error is not None:
            raise self._named_error
        return self._named_result


async def _list_tools_via_server(server) -> list[types.Tool]:
    handler = server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return result.root.tools


async def _call_tool_via_server(server, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    handler = server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments))
    result = await handler(req)
    return result.root


class TestProjection:
    """THE GENERATIVE RULE: the tool list is DERIVED from describe(), never hand-maintained."""

    def test_verb_present_only_in_describe_yields_tool_without_code_change(self):
        """A verb that exists ONLY in a stubbed describe payload is projected as a tool, with its
        param schema carried through from describe rather than restated locally."""
        verbs = {
            "totally_novel_verb": _verb_meta(
                description="A verb invented purely for this test.",
                params=["widget_id"],
                params_schema={
                    "type": "object",
                    "properties": {"widget_id": {"type": "string"}},
                    "required": ["widget_id"],
                },
            )
        }
        tools = build_tool_registry(verbs)
        assert len(tools) == 1
        tool = tools[0]
        assert tool.name == "totally_novel_verb"
        assert _wire_input_schema(tool) == verbs["totally_novel_verb"]["params_schema"]

    def test_multiple_verbs_all_projected(self):
        verbs = {"verb_a": _verb_meta(), "verb_b": _verb_meta(description="second verb")}
        tools = build_tool_registry(verbs)
        assert {t.name for t in tools} == {"verb_a", "verb_b"}

    def test_empty_verbs_yields_no_tools(self):
        assert build_tool_registry({}) == []


class TestReadOnlySurface:
    """No write verb, no infra/probe action, no raw-SQL parameter, no DuckLakeReader.query."""

    _FORBIDDEN_NAMES = frozenset(
        {
            "file_ops",
            "update_ops",
            "write_ops",
            "create_ops_tables",
            "create_tables",
            "churn",
            "connect_probe",
            "attach_check",
            "write_probe",
            "reset_warm_connection",
        }
    )

    def test_real_describe_output_projects_no_write_or_probe_action(self):
        from src.common.ducklake_scd2_schema import describe_named_reads

        real_verbs = describe_named_reads()
        tools = build_tool_registry(real_verbs)
        names = {t.name for t in tools}
        assert names & self._FORBIDDEN_NAMES == set()
        assert len(tools) == len(real_verbs)

    def test_no_tool_accepts_a_raw_sql_parameter(self):
        from src.common.ducklake_scd2_schema import describe_named_reads

        tools = build_tool_registry(describe_named_reads())
        for tool in tools:
            props = (_wire_input_schema(tool) or {}).get("properties", {})
            assert "sql" not in {p.lower() for p in props}, f"{tool.name} accepts a raw sql param"

    def test_query_method_is_never_invoked_by_the_projection(self):
        """DuckLakeReader.query (free-SQL) is not reachable through named-verb invocation."""
        stub = _StubReader(
            {
                "rec_by_id": _verb_meta(
                    params=["id"],
                    params_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                )
            }
        )
        stub.query = lambda *a, **k: pytest.fail("query() must never be called by the projection")  # type: ignore[attr-defined]

        _invoke_verb(stub, "rec_by_id", {"id": "rec-1"})
        assert stub.named_calls == [("rec_by_id", {"id": "rec-1"})]


class TestFailLoud:
    """A describe() failure raises; the server never starts with a partial or default tool list."""

    def test_describe_failure_propagates_at_server_creation(self):
        class _FailingReader:
            def describe(self):
                raise RuntimeError("reader unreachable")

        with pytest.raises(RuntimeError, match="reader unreachable"):
            create_server(reader=_FailingReader())

    def test_reader_invoke_error_on_describe_propagates_uncaught(self):
        class _FailingReader:
            def describe(self):
                raise ReaderInvokeError("describe", 500, "boom", {"ok": False, "error_type": "runtime", "error": "boom"})

        with pytest.raises(ReaderInvokeError):
            create_server(reader=_FailingReader())


class TestTypedErrors:
    """Boundary error responses map onto distinct typed exceptions; unknown shapes stay loud."""

    def test_reader_invoke_error_is_mapped_and_reraised(self):
        exc = ReaderInvokeError("named_read", 500, "boom", {"ok": False, "error_type": "runtime", "error": "unknown verb"})
        stub = _StubReader({}, named_error=exc)
        with pytest.raises(agent_errors.ReaderRuntimeError):
            _invoke_verb(stub, "rec_by_id", {"id": "x"})

    def test_unrecognised_error_shape_raises_loud_generic_not_swallowed(self):
        exc = ReaderInvokeError("named_read", 503, "boom", None)
        stub = _StubReader({}, named_error=exc)
        with pytest.raises(agent_errors.ReaderBoundaryError):
            _invoke_verb(stub, "rec_by_id", {"id": "x"})

    def test_non_reader_invoke_error_propagates_unmapped(self):
        """An error outside the reader boundary must not be mis-mapped into the reader taxonomy."""
        stub = _StubReader({}, named_error=ValueError("bad params"))
        with pytest.raises(ValueError, match="bad params"):
            _invoke_verb(stub, "rec_by_id", {"id": "x"})


class TestToolDescriptions:
    """Every projected tool carries the Decision 126 cache-first guidance, applied once by the
    shared projection template."""

    def test_every_tool_has_nonempty_description_naming_the_cache_first_rule(self):
        from src.common.ducklake_scd2_schema import describe_named_reads

        tools = build_tool_registry(describe_named_reads())
        assert tools, "expected at least one projected tool"
        for tool in tools:
            assert tool.description
            assert "cache" in tool.description.lower()

    def test_cache_first_note_applied_by_shared_template_not_per_verb(self):
        verbs = {"verb_a": _verb_meta(description="Verb A does X.")}
        tools = build_tool_registry(verbs)
        assert tools[0].description.startswith("Verb A does X.")
        assert "cache" in tools[0].description.lower()


@pytest.mark.integration
@pytest.mark.aws
class TestEndToEnd:
    """LIVE BOUNDARY PROOF: traverses the MCP tool surface end to end, not DuckLakeReader.named()
    directly -- a direct named() call passes on unmodified main and proves nothing about this
    plan. No credentials-skip guard: absent credentials must fail this test, not skip it green."""

    def test_rec_by_id_tool_returns_exactly_one_row_against_live_boundary(self, _allow_network_for_integration: None) -> None:
        server = create_server()

        tools = anyio.run(_list_tools_via_server, server)
        names = {t.name for t in tools}
        assert "open_recs" in names
        assert "rec_by_id" in names

        open_result = anyio.run(_call_tool_via_server, server, "open_recs", {})
        assert not open_result.isError, open_result.content
        assert open_result.structuredContent is not None
        open_rows = open_result.structuredContent["rows"]
        assert open_rows, "expected at least one open recommendation to discover an id from"
        rec_id = open_rows[0]["id"]

        rec_result = anyio.run(_call_tool_via_server, server, "rec_by_id", {"id": rec_id})
        assert not rec_result.isError, rec_result.content
        assert rec_result.structuredContent is not None
        rec_rows = rec_result.structuredContent["rows"]
        assert len(rec_rows) == 1
        assert rec_rows[0]["id"] == rec_id
