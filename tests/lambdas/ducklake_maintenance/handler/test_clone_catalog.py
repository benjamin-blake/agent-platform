"""action_clone_catalog (OQ.12 canary rehearsal -- Neon native branch, Decision 100) concern for
src/lambdas/ducklake_maintenance/handler.py (100% coverage, mocked).

Split from the former tests/test_ducklake_maintenance_handler.py monolith (rec-2709 Wave 8).
Functions copied VERBATIM; _clone_catalog_branch_patches (with its nested _FakeCon) stays LOCAL
to this module.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from tests.fixtures.ducklake_maintenance_handler import _FULL_DSN, _response_body

pytestmark = pytest.mark.unit

_BRANCH_HOST = "br-fake-abc.us-east-2.aws.neon.tech"


def _clone_catalog_branch_patches(*, schemata_rows=None, open_raises=None):
    """Return a stack of patches for action_clone_catalog Neon-branch tests."""

    class _FakeCon:
        def execute(self, sql):
            return self

        def fetchall(self):
            if open_raises:
                raise open_raises
            return schemata_rows if schemata_rows is not None else [("public",)]

        def close(self):
            pass

    con_mock = _FakeCon()

    if open_raises:

        def _open_raises(*, dsn=None, data_path=None, meta_schema=None, extension_directory=None):
            raise open_raises

        open_patch = patch.object(h.rt, "open_connection", side_effect=_open_raises)
    else:
        open_patch = patch.object(h.rt, "open_connection", return_value=con_mock)

    return (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        open_patch,
    )


_PROD_DATA_PATH = "s3://b/ducklake/"


def test_action_clone_catalog_happy_path():
    """Happy path: branch_host + data_path in event, ATTACH succeeds, returns ok."""
    p = _clone_catalog_branch_patches()
    with p[0], p[1] as open_mock:
        result = h.action_clone_catalog(
            {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
        )
    assert result["ok"] is True
    assert result["cloned"] is True
    assert result["meta_schema"] == "ducklake_ops"
    assert result["branch_host"] == _BRANCH_HOST
    call_kwargs = open_mock.call_args[1]
    assert call_kwargs["dsn"]["host"] == _BRANCH_HOST
    assert call_kwargs["dsn"]["dbname"] == _FULL_DSN["dbname"]
    assert call_kwargs["meta_schema"] == "ducklake_ops"
    assert call_kwargs["data_path"] == _PROD_DATA_PATH


def test_action_clone_catalog_branch_dsn_inherits_prod_credentials():
    """branch_dsn must use prod role/password/dbname with only host substituted."""
    p = _clone_catalog_branch_patches()
    with p[0], p[1] as open_mock:
        h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None)
    call_dsn = open_mock.call_args[1]["dsn"]
    assert call_dsn["host"] == _BRANCH_HOST
    assert call_dsn["dbname"] == _FULL_DSN["dbname"]
    assert call_dsn["username"] == _FULL_DSN["username"]
    assert call_dsn["password"] == _FULL_DSN["password"]  # pragma: allowlist secret -- fake fixture


def test_action_clone_catalog_missing_branch_host_loud_fails():
    """Missing branch_host in event raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="branch_host is required"):
            h.action_clone_catalog({"action": "clone_catalog", "data_path": _PROD_DATA_PATH}, None)


def test_action_clone_catalog_missing_data_path_loud_fails():
    """Missing data_path in event raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="data_path is required"):
            h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST}, None)


def test_action_clone_catalog_invalid_data_path_loud_fails():
    """Non-s3:// data_path raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="data_path is required"):
            h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": "/local/path"}, None)


def test_action_clone_catalog_empty_schemata_loud_fails():
    """Empty information_schema.schemata result raises CatalogDrError (Decision 55)."""
    p = _clone_catalog_branch_patches(schemata_rows=[])
    with p[0], p[1]:
        with pytest.raises(h.catalog_dr.CatalogDrError, match="empty information_schema.schemata"):
            h.action_clone_catalog(
                {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
            )


def test_action_clone_catalog_attach_failure_loud_fails():
    """open_connection raising DuckLakeRuntimeError propagates (Decision 55 loud-fail)."""
    p = _clone_catalog_branch_patches(open_raises=h.rt.DuckLakeRuntimeError("ATTACH fail"))
    with p[0], p[1]:
        with pytest.raises(h.rt.DuckLakeRuntimeError, match="ATTACH fail"):
            h.action_clone_catalog(
                {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
            )


def test_action_clone_catalog_no_pg_dump_no_pg_restore():
    """Surface-retirement: pg_dump, pg_restore, CREATE DATABASE, DROP DATABASE must never be called."""
    pg_dump_calls = []
    pg_restore_calls = []
    p = _clone_catalog_branch_patches()
    with (
        p[0],
        p[1],
        patch.object(h.catalog_dr, "build_pg_dump_cmd", side_effect=lambda *a, **kw: pg_dump_calls.append(1) or []),
        patch.object(h.catalog_dr, "run_pg_restore", side_effect=lambda *a, **kw: pg_restore_calls.append(1)),
    ):
        h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None)
    assert pg_dump_calls == [], "build_pg_dump_cmd must not be called on the clone path (Decision 100)"
    assert pg_restore_calls == [], "run_pg_restore must not be called on the clone path (Decision 100)"


def test_action_clone_catalog_is_connectionless():
    """clone_catalog must appear in _CONNECTIONLESS_ACTIONS (handler skips open_connection call)."""
    assert "clone_catalog" in h._CONNECTIONLESS_ACTIONS


def test_action_clone_catalog_listed_in_actions():
    """clone_catalog must appear in _ACTIONS and in the handler's action list response."""
    assert "clone_catalog" in h._ACTIONS
    body = _response_body(h.handler({"action": "bad"}))
    assert "clone_catalog" in body["actions"]
