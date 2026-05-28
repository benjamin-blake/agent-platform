from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import scripts.cleanup_ops_rec_orphans as _mod
from scripts.cleanup_ops_rec_orphans import KNOWN_ORPHAN_IDS


def _make_athena_client(post_count: int = 0) -> MagicMock:
    """Return a mock Athena client wired for successful execution."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "mock-qid"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    pre_result: dict = {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": "id"}]}]}}
    post_result: dict = {
        "ResultSet": {
            "Rows": [
                {"Data": [{"VarCharValue": "_col0"}]},
                {"Data": [{"VarCharValue": str(post_count)}]},
            ]
        }
    }
    client.get_query_results.side_effect = [pre_result, post_result]
    return client


def _make_session(client: MagicMock) -> MagicMock:
    session = MagicMock()
    session.client.return_value = client
    return session


def test_dry_run_does_not_delete() -> None:
    """purge_orphans(dry_run=True) issues only the pre-check SELECT; no DELETE submitted."""
    client = _make_athena_client()
    with patch.object(_mod, "boto3") as mock_boto3:
        mock_boto3.Session.return_value = _make_session(client)
        _mod.purge_orphans(dry_run=True)

    assert client.start_query_execution.call_count == 1
    sql: str = client.start_query_execution.call_args[1]["QueryString"]
    assert "DELETE" not in sql.upper()


def test_delete_sql_contains_known_ids() -> None:
    """The DELETE by-ID query includes every ID in KNOWN_ORPHAN_IDS."""
    client = _make_athena_client(post_count=0)
    with patch.object(_mod, "boto3") as mock_boto3:
        mock_boto3.Session.return_value = _make_session(client)
        _mod.purge_orphans(dry_run=False)

    all_sqls = [call[1]["QueryString"] for call in client.start_query_execution.call_args_list]
    delete_id_sql = next(s for s in all_sqls if "DELETE" in s.upper() and "NULL" not in s.upper())
    for rec_id in KNOWN_ORPHAN_IDS:
        assert rec_id in delete_id_sql, f"{rec_id!r} not found in DELETE SQL: {delete_id_sql!r}"


def test_post_assert_failure_raises() -> None:
    """AssertionError raised when post-assert count is non-zero."""
    client = _make_athena_client(post_count=1)
    with patch.object(_mod, "boto3") as mock_boto3:
        mock_boto3.Session.return_value = _make_session(client)
        with pytest.raises(AssertionError, match="1 orphan rows remain"):
            _mod.purge_orphans(dry_run=False)


def test_vacuum_called_after_delete() -> None:
    """VACUUM is submitted only after both DELETE statements complete."""
    client = _make_athena_client(post_count=0)
    with patch.object(_mod, "boto3") as mock_boto3:
        mock_boto3.Session.return_value = _make_session(client)
        _mod.purge_orphans(dry_run=False)

    all_sqls = [call[1]["QueryString"] for call in client.start_query_execution.call_args_list]
    delete_indices = [i for i, s in enumerate(all_sqls) if "DELETE" in s.upper()]
    vacuum_indices = [i for i, s in enumerate(all_sqls) if "VACUUM" in s.upper()]
    assert vacuum_indices, "No VACUUM call found"
    assert delete_indices, "No DELETE calls found"
    assert max(delete_indices) < min(vacuum_indices), "VACUUM must come after all DELETEs"


def test_row_count_empty() -> None:
    """_row_count returns 0 when ResultSet.Rows has only header."""
    client = MagicMock()
    # Header only
    client.get_query_results.return_value = {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": "count"}]}]}}
    assert _mod._row_count(client, "mock-qid") == 0
