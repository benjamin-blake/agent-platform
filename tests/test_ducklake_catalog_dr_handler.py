"""Tests for src/lambdas/ducklake_catalog_dr/handler.py (RS-08, 100% coverage, mocked)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

import src.lambdas.ducklake_catalog_dr.handler as h

pytestmark = pytest.mark.unit

_FULL_DSN = {"username": "u", "password": "p", "host": "hostx", "dbname": "neondb", "sslmode": "require"}


def _response_body(r: dict[str, Any]) -> dict[str, Any]:
    return json.loads(r["body"])


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------


def test_parse_event_body_string():
    assert h._parse_event({"body": json.dumps({"force_bucket": "b"})}) == {"force_bucket": "b"}


def test_parse_event_body_dict():
    assert h._parse_event({"body": {"force_bucket": "b"}}) == {"force_bucket": "b"}


def test_parse_event_body_empty_string():
    assert h._parse_event({"body": ""}) == {}


def test_parse_event_direct_dict():
    assert h._parse_event({"force_bucket": "b"}) == {"force_bucket": "b"}


def test_parse_event_non_dict():
    assert h._parse_event("nonsense") == {}


# ---------------------------------------------------------------------------
# _response
# ---------------------------------------------------------------------------


def test_response_envelope():
    r = h._response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["ok"] is True
    assert r["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# handler() -- missing bucket
# ---------------------------------------------------------------------------


def test_handler_missing_bucket_returns_500():
    """No force_bucket in the event and no DUCKLAKE_DR_BUCKET configured -> 500, no dump attempted."""
    with patch.object(h, "DR_BUCKET", ""):
        r = h.handler({})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert "DUCKLAKE_DR_BUCKET" in body["error"]


# ---------------------------------------------------------------------------
# handler() -- success
# ---------------------------------------------------------------------------


def test_handler_success_returns_200():
    dump_result = {"ok": True, "bucket": "s3-dr-bucket", "s3_key": "catalog/dump.pgcustom"}
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN) as mock_fetch_dsn,
        patch.object(h.catalog_dr, "run_catalog_dump", return_value=dump_result) as mock_dump,
    ):
        r = h.handler({"force_bucket": "s3-dr-bucket"})

    assert r["statusCode"] == 200
    assert _response_body(r) == dump_result
    mock_fetch_dsn.assert_called_once_with(profile=h.PROFILE)
    args, kwargs = mock_dump.call_args
    assert args[0] == _FULL_DSN
    assert kwargs["bucket"] == "s3-dr-bucket"
    assert kwargs["pg_version"] == h.catalog_dr.PINNED_PG_VERSION
    assert kwargs["duckdb_version"] == h.rt.PINNED_DUCKDB_VERSION
    assert kwargs["pg_dump_path"] == h.PG_DUMP_PATH
    assert kwargs["profile"] == h.PROFILE
    assert kwargs["region"] == h.REGION


def test_handler_success_honors_force_overrides():
    """force_pg_dump_path / force_pg_version / force_duckdb_version flow through to run_catalog_dump."""
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.catalog_dr, "run_catalog_dump", return_value={"ok": True}) as mock_dump,
    ):
        h.handler(
            {
                "force_bucket": "s3-dr-bucket",
                "force_pg_dump_path": "/custom/pg_dump",
                "force_pg_version": "15",
                "force_duckdb_version": "1.2.3",
            }
        )

    _, kwargs = mock_dump.call_args
    assert kwargs["pg_dump_path"] == "/custom/pg_dump"
    assert kwargs["pg_version"] == "15"
    assert kwargs["duckdb_version"] == "1.2.3"


# ---------------------------------------------------------------------------
# handler() -- error mapping (loud-fail -> 5xx, Decision 55)
# ---------------------------------------------------------------------------


def test_handler_catalog_dr_error_maps_to_500():
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.catalog_dr, "run_catalog_dump", side_effect=h.catalog_dr.CatalogDrError("pg_dump exited 1")),
    ):
        r = h.handler({"force_bucket": "s3-dr-bucket"})

    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert body["error_type"] == "catalog_dr"
    assert "pg_dump exited 1" in body["error"]


def test_handler_runtime_error_maps_to_500():
    with patch.object(h.rt, "fetch_dsn", side_effect=h.rt.DuckLakeRuntimeError("DSN fetch failed")):
        r = h.handler({"force_bucket": "s3-dr-bucket"})

    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert body["error_type"] == "runtime"
    assert "DSN fetch failed" in body["error"]
