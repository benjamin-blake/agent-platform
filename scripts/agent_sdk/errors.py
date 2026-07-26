"""Typed exceptions for the ducklake_reader boundary's error responses (Decision 55 fail-loud).

The reader Lambda (src/lambdas/ducklake_reader/handler.py) returns three distinct failure shapes:
  HTTP 400 {"ok": false, "error": ..., "actions": [...]}        -- the action name itself is unknown.
  HTTP 500 {"ok": false, "error_type": "version_mismatch", ...} -- rt.VersionMismatchError.
  HTTP 500 {"ok": false, "error_type": "runtime", ...}          -- rt.DuckLakeRuntimeError (unknown
                                                                    verb, bad params, unknown table).
src.common.iceberg_reader.DuckLakeReader raises ReaderInvokeError (carrying the HTTP status and the
parsed JSON body) for any of these; map_reader_error() below maps that onto one of the types here,
derived from what the handler actually returns -- not the writer's envelope shape. A shape this
mapping does not recognise maps to ReaderBoundaryError, a loud generic, rather than being swallowed.
"""

from __future__ import annotations

from src.common.iceberg_reader import ReaderInvokeError


class AgentToolError(RuntimeError):
    """Base class for every typed error this module raises."""


class UnknownActionError(AgentToolError):
    """The reader rejected the action name itself (HTTP 400, no `error_type` field)."""

    def __init__(self, message: str, actions: list[str]) -> None:
        self.actions = actions
        super().__init__(message)


class VersionMismatchError(AgentToolError):
    """The reader's `error_type` was `"version_mismatch"` (rt.VersionMismatchError server-side)."""


class ReaderRuntimeError(AgentToolError):
    """The reader's `error_type` was `"runtime"` (rt.DuckLakeRuntimeError server-side --

    unknown verb, a param mismatch, or an unknown ops table).
    """


class ReaderBoundaryError(AgentToolError):
    """An unrecognised reader failure shape. Never silently swallowed (Decision 55)."""


def map_reader_error(exc: ReaderInvokeError) -> AgentToolError:
    """Map *exc* onto one of this module's typed exceptions.

    Falls through to ReaderBoundaryError for any shape this mapping does not recognise (a missing
    or non-JSON body, an unexpected error_type, or a 400 without an `actions` list) -- an
    unrecognised error must surface loudly, never as a silent default or a swallowed exception.
    """
    body = exc.body
    if not isinstance(body, dict):
        return ReaderBoundaryError(str(exc))

    error_type = body.get("error_type")
    if error_type == "version_mismatch":
        return VersionMismatchError(str(body.get("error") or exc))
    if error_type == "runtime":
        return ReaderRuntimeError(str(body.get("error") or exc))
    if exc.status == 400 and isinstance(body.get("actions"), list):
        return UnknownActionError(str(body.get("error") or exc), list(body["actions"]))

    return ReaderBoundaryError(str(exc))
