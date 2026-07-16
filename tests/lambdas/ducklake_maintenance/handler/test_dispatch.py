"""Envelope + handler dispatch + handler error-mapping concern for
src/lambdas/ducklake_maintenance/handler.py (T2.18, 100% coverage, mocked).

Split from the former tests/test_ducklake_maintenance_handler.py monolith (rec-2709 Wave 8).
Functions copied VERBATIM.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from src.common.ducklake_maintenance import DuckLakeMaintenanceError
from src.common.ducklake_runtime import DuckLakeRuntimeError, VersionMismatchError
from tests.fixtures.ducklake_maintenance_handler import _response_body

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _parse_event / _response
# ---------------------------------------------------------------------------


def test_parse_event_body_string():
    assert h._parse_event({"body": json.dumps({"action": "merge"})}) == {"action": "merge"}


def test_parse_event_body_dict():
    assert h._parse_event({"body": {"action": "gc"}}) == {"action": "gc"}


def test_parse_event_body_empty_string():
    assert h._parse_event({"body": ""}) == {}


def test_parse_event_direct_dict():
    assert h._parse_event({"action": "merge"}) == {"action": "merge"}


def test_parse_event_non_dict():
    assert h._parse_event("nonsense") == {}


def test_response_envelope():
    r = h._response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["ok"] is True
    assert r["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# handler dispatch
# ---------------------------------------------------------------------------


def test_handler_unknown_action():
    r = h.handler({"action": "nope"})
    assert r["statusCode"] == 400
    body = _response_body(r)
    assert "unknown action" in body["error"]
    assert "actions" in body


def test_handler_missing_action():
    r = h.handler({})
    assert r["statusCode"] == 400


def test_handler_lists_known_actions():
    r = h.handler({"action": "bad"})
    body = _response_body(r)
    assert "merge" in body["actions"]
    assert "gc" in body["actions"]
    assert "breaker_probe" in body["actions"]
    assert "hot_merge" in body["actions"]


def test_handler_lists_new_operational_actions():
    body = _response_body(h.handler({"action": "bad"}))
    for action in ("catalog_reinit", "restore_drill"):
        assert action in body["actions"]
    # seed_ops_recommendations was removed at the 2026-06-09 recs sign-off (closed boundary).
    assert "seed_ops_recommendations" not in body["actions"]


# ---------------------------------------------------------------------------
# handler error mapping (loud-fail -> 4xx/5xx)
# ---------------------------------------------------------------------------


def test_handler_maintenance_error_maps_to_500():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("breaker"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert body["error_type"] == "breaker"
    assert body["breaker_tripped"] is True


def test_handler_version_mismatch_maps_to_500():
    raiser = MagicMock(side_effect=VersionMismatchError("bad version"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "version_mismatch"


def test_handler_runtime_error_maps_to_500():
    raiser = MagicMock(side_effect=DuckLakeRuntimeError("runtime fail"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "runtime"


def test_handler_connection_closed_on_success():
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        good = MagicMock(return_value={"ok": True, "action": "merge", "tables": [], "files_after_merge": 0, "elapsed_ms": 1.0})
        with patch.dict(h._ACTIONS, {"merge": good}):
            with patch.object(h, "_emit_maintenance_metric"):
                h.handler({"action": "merge"})
        mock_con.close.assert_called_once()


def test_handler_connection_closed_on_error():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("trip"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                h.handler({"action": "merge"})
        mock_con.close.assert_called_once()


def test_handler_breaker_probe_via_handler_returns_500():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("tripped"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"breaker_probe": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                r = h.handler({"action": "breaker_probe"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["breaker_tripped"] is True


def test_handler_catalog_dr_error_maps_to_500():
    raiser = MagicMock(side_effect=h.catalog_dr.CatalogDrError("restore boom"))
    with patch.dict(h._ACTIONS, {"restore_drill": raiser}):
        r = h.handler({"action": "restore_drill"})
    assert r["statusCode"] == 500
    assert _response_body(r)["error_type"] == "catalog_dr"
