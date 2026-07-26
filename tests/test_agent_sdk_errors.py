"""Tests for scripts/agent_sdk/errors.py -- the typed reader-boundary exception mapping."""

from __future__ import annotations

from scripts.agent_sdk.errors import (
    AgentToolError,
    ReaderBoundaryError,
    ReaderRuntimeError,
    UnknownActionError,
    VersionMismatchError,
    map_reader_error,
)
from src.common.iceberg_reader import ReaderInvokeError


def _invoke_error(status: int | None, body: dict | None, action: str = "describe") -> ReaderInvokeError:
    return ReaderInvokeError(action, status, "" if body is None else str(body), body)


def test_version_mismatch_maps_to_version_mismatch_error():
    exc = _invoke_error(500, {"ok": False, "error_type": "version_mismatch", "error": "schema drift"})
    mapped = map_reader_error(exc)
    assert isinstance(mapped, VersionMismatchError)
    assert "schema drift" in str(mapped)


def test_runtime_error_type_maps_to_reader_runtime_error():
    exc = _invoke_error(500, {"ok": False, "error_type": "runtime", "error": "unknown read verb 'bogus'"})
    mapped = map_reader_error(exc)
    assert isinstance(mapped, ReaderRuntimeError)
    assert "unknown read verb" in str(mapped)


def test_unknown_action_maps_to_unknown_action_error():
    exc = _invoke_error(400, {"ok": False, "error": "unknown action 'bogus'", "actions": ["describe", "named_read"]})
    mapped = map_reader_error(exc)
    assert isinstance(mapped, UnknownActionError)
    assert mapped.actions == ["describe", "named_read"]


def test_unrecognised_shape_maps_to_boundary_error_not_swallowed():
    """An error_type this mapping does not recognise must surface loudly, not silently default."""
    exc = _invoke_error(500, {"ok": False, "error_type": "something_new", "error": "boom"})
    mapped = map_reader_error(exc)
    assert isinstance(mapped, ReaderBoundaryError)


def test_non_json_body_maps_to_boundary_error():
    exc = _invoke_error(502, None)
    mapped = map_reader_error(exc)
    assert isinstance(mapped, ReaderBoundaryError)


def test_400_without_actions_list_maps_to_boundary_error():
    """A 400 body missing the `actions` list is an unrecognised shape, not assumed UnknownActionError."""
    exc = _invoke_error(400, {"ok": False, "error": "something else"})
    mapped = map_reader_error(exc)
    assert isinstance(mapped, ReaderBoundaryError)


def test_all_typed_errors_are_agent_tool_errors():
    for cls in (VersionMismatchError, ReaderRuntimeError, UnknownActionError, ReaderBoundaryError):
        assert issubclass(cls, AgentToolError)
    assert issubclass(AgentToolError, RuntimeError)


def test_unknown_action_error_message_uses_reader_error_text():
    exc = _invoke_error(400, {"ok": False, "error": "unknown action 'bogus'", "actions": []})
    mapped = map_reader_error(exc)
    assert "unknown action 'bogus'" in str(mapped)
