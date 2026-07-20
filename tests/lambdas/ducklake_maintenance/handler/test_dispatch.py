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
    assert "catalog_reinit" in body["actions"]
    assert "restore_drill" in body["actions"]
    assert "merge_ops" in body["actions"]
    assert "catalog_stats" in body["actions"]
    assert "reconcile_columns" in body["actions"]
    assert "clone_catalog" in body["actions"]
    # The 4 smoke actions moved to ducklake_maintenance_smoke (T2.18 c9 split) -- must NOT be
    # reachable on the admin function (blast-radius invariant).
    assert "merge" not in body["actions"]
    assert "gc" not in body["actions"]
    assert "breaker_probe" not in body["actions"]
    assert "hot_merge" not in body["actions"]


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
    with patch.dict(h._ACTIONS, {"catalog_reinit": raiser}):
        with patch.object(h, "_emit_maintenance_metric"):
            r = h.handler({"action": "catalog_reinit"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert body["error_type"] == "breaker"
    assert body["breaker_tripped"] is True


def test_handler_version_mismatch_maps_to_500():
    raiser = MagicMock(side_effect=VersionMismatchError("bad version"))
    with patch.dict(h._ACTIONS, {"catalog_reinit": raiser}):
        r = h.handler({"action": "catalog_reinit"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "version_mismatch"


def test_handler_runtime_error_maps_to_500():
    raiser = MagicMock(side_effect=DuckLakeRuntimeError("runtime fail"))
    with patch.dict(h._ACTIONS, {"catalog_reinit": raiser}):
        r = h.handler({"action": "catalog_reinit"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "runtime"


def test_handler_catalog_dr_error_maps_to_500():
    raiser = MagicMock(side_effect=h.catalog_dr.CatalogDrError("restore boom"))
    with patch.dict(h._ACTIONS, {"restore_drill": raiser}):
        r = h.handler({"action": "restore_drill"})
    assert r["statusCode"] == 500
    assert _response_body(r)["error_type"] == "catalog_dr"
