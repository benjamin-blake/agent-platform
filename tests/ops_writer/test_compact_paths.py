"""Tests for scripts/ops_writer.py -- compact()'s DataFrame-transform concern.

PLAN-coverage-paydown-ops-writer-sync-ops: covers compact()'s remaining 17 statements (mixed
NaN->None coercion, all-null column drop, int/bool column casts, schema-evolution detection
exception path) PLUS the 14 statements of _parse_list, a closure DEFINED INSIDE compact()
(scripts/ops_writer.py:415-429) and reachable only by driving compact() with a DataFrame
carrying a dependencies/tags column. New module rather than growth of test_compact.py
(329/500 SLOC) or test_compact_edge_cases.py (228/500), per Decision 128/130 decompose-by-default.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas  # noqa: F401

from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


def _make_mock_client_with_staging(entries: list[dict], table: str = "ops_priority_queue") -> MagicMock:
    """Build a mock boto3 client that returns *entries* as one staging file."""
    mock_client = MagicMock()
    line_bytes = b"\n".join(json.dumps(e).encode() for e in entries)

    mock_paginator = MagicMock()
    mock_page = {"Contents": [{"Key": f"staging/{table}/dt=2026-04-20/batch-abc.jsonl"}]}
    mock_paginator.paginate.return_value = [mock_page]
    mock_client.get_paginator.return_value = mock_paginator

    mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}
    return mock_client


def _run_compact_capture_df(entries: list[dict], table: str = "ops_priority_queue", get_table_types_side_effect=None):
    """Run compact() against *entries* and return the DataFrame passed to wr.athena.to_iceberg."""
    mock_client = _make_mock_client_with_staging(entries, table=table)
    writer = _make_writer()
    writer._client = mock_client

    captured: dict = {}

    def _capture(df, **kwargs):
        captured["df"] = df.copy()

    with (
        patch("scripts.ops_writer._AWR_AVAILABLE", True),
        patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
        patch.object(writer, "_bucket", return_value="my-bucket"),
        patch.object(writer, "_is_test_env", return_value=False),
        patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
        patch("scripts.ops_writer.wr") as mock_wr,
    ):
        if get_table_types_side_effect is not None:
            mock_wr.catalog.get_table_types.side_effect = get_table_types_side_effect
        else:
            mock_wr.catalog.get_table_types.return_value = {}
        mock_wr.athena.to_iceberg.side_effect = _capture
        writer.compact(table, "2026-04-20")

    return captured["df"]


class TestOpsWriterCompactNullHandling:
    """Mixed-NaN->None coercion and the all-null-column drop."""

    def test_compact_coerces_mixed_missing_object_column_to_none(self):
        """A genuinely object-dtype column (mixed str/int) with a missing row becomes None, not NaN.

        pandas 3.x infers a uniform-string column as StringDtype (na_value=nan), which never
        satisfies compact()'s `df[c].dtype == object` guard -- only a column pandas cannot infer
        as a single non-object dtype (here: str mixed with int) actually lands as object dtype,
        which is the real-world shape (a legacy/mixed-type field) that motivated this coercion.
        """
        entries = [
            {
                "id": "ep-001",
                "note": "hello",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-002",
                "note": 123,
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-003",
                # "note" omitted entirely -> NaN after pd.DataFrame construction
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        df = _run_compact_capture_df(entries)
        assert df["note"].dtype == object
        assert df.loc[df["id"] == "ep-003", "note"].iloc[0] is None

    def test_compact_drops_all_null_column(self):
        """A column that is None on every row is dropped before to_iceberg."""
        entries = [
            {
                "id": "ep-001",
                "always_null": None,
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-002",
                "always_null": None,
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        df = _run_compact_capture_df(entries)
        assert "always_null" not in df.columns


class TestOpsWriterCompactTypeCoercion:
    """Int and bool column casts applied before to_iceberg."""

    def test_compact_casts_execution_steps_to_int64(self):
        """execution_steps (a known _INT_COLUMNS member) is coerced to pandas Int64."""
        import pandas as pd

        entries = [
            {
                "id": "ep-001",
                "execution_steps": "5",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        df = _run_compact_capture_df(entries)
        assert str(df["execution_steps"].dtype) == "Int64"
        assert df["execution_steps"].iloc[0] == 5
        assert isinstance(df["execution_steps"].dtype, pd.Int64Dtype)

    def test_compact_casts_automatable_string_to_bool(self):
        """automatable (the sole _BOOL_COLUMNS member) maps 'true'/'false' strings to booleans."""
        entries = [
            {
                "id": "ep-001",
                "automatable": "true",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-002",
                "automatable": "false",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        df = _run_compact_capture_df(entries)
        assert bool(df.loc[df["id"] == "ep-001", "automatable"].iloc[0]) is True
        assert bool(df.loc[df["id"] == "ep-002", "automatable"].iloc[0]) is False


class TestOpsWriterCompactParseListClosure:
    """_parse_list -- a closure defined INSIDE compact(), reachable only via a list column."""

    def test_parse_list_covers_every_branch_across_rows(self):
        """One dependencies column, five rows, each exercising a distinct _parse_list branch."""
        entries = [
            {
                "id": "ep-native-list",
                "dependencies": ["dep-native-1", "dep-native-2"],  # isinstance(v, list) branch
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-none",
                "dependencies": None,  # not-str/not-list -> []
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-blank",
                "dependencies": "   ",  # str but blank after strip -> []
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-quoted-literal",
                "dependencies": "['dep-lit-1', 'dep-lit-2']",  # valid ast.literal_eval -> list
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-bracket-not-literal",
                "dependencies": "[dep-bad-1, dep-bad-2]",  # bracketed but NOT a valid literal -> except -> fallback
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
            {
                "id": "ep-comma-only",
                "dependencies": "dep-plain-1, dep-plain-2",  # no brackets -> straight to comma fallback
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        df = _run_compact_capture_df(entries)
        by_id = df.set_index("id")["dependencies"]

        assert by_id["ep-native-list"] == ["dep-native-1", "dep-native-2"]
        assert by_id["ep-none"] == []
        assert by_id["ep-blank"] == []
        assert by_id["ep-quoted-literal"] == ["dep-lit-1", "dep-lit-2"]
        # ast.literal_eval raises on unquoted identifiers (e.g. "dep-bad-1" parses as a
        # subtraction expression, not a literal) -- falls through to the comma-split fallback,
        # which does not strip the outer brackets from the first/last element.
        assert by_id["ep-bracket-not-literal"] == ["[dep-bad-1", "dep-bad-2]"]
        assert by_id["ep-comma-only"] == ["dep-plain-1", "dep-plain-2"]


class TestOpsWriterCompactGuardBranches:
    """compact()'s pre-DataFrame guards, driven with a real (non-DuckLake-boundary) table.

    rec-2931: sibling tests in test_compact_edge_cases.py pass table="ops_recommendations" for
    these same guards, which short-circuits at compact()'s own DuckLake-boundary rejection
    (line 301) before ever reaching the guard under test -- vacuously green. These use
    "ops_priority_queue" (a real Iceberg-compacted table) so each guard is genuinely exercised.
    """

    def test_compact_awswrangler_unavailable_returns_zero(self):
        """compact() returns 0 without touching S3 when _AWR_AVAILABLE is False."""
        writer = _make_writer()
        writer._client = MagicMock()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", False),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.compact("ops_priority_queue", "2026-04-20")
        assert result == 0
        writer._client.get_paginator.assert_not_called()

    def test_compact_boto3_unavailable_returns_zero(self):
        """compact() returns 0 without touching S3 when _BOTO3_AVAILABLE is False."""
        writer = _make_writer()
        writer._client = MagicMock()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", False),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.compact("ops_priority_queue", "2026-04-20")
        assert result == 0
        writer._client.get_paginator.assert_not_called()

    def test_compact_returns_zero_in_test_env(self):
        """compact() returns 0 when _is_test_env() is True, even with a resolved bucket."""
        writer = _make_writer()
        writer._client = MagicMock()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=True),
        ):
            result = writer.compact("ops_priority_queue", "2026-04-20")
        assert result == 0
        writer._client.get_paginator.assert_not_called()

    def test_compact_returns_zero_when_get_client_returns_none(self):
        """compact() returns 0 when _get_client() resolves to None (offline)."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=None),
        ):
            result = writer.compact("ops_priority_queue", "2026-04-20")
        assert result == 0

    def test_compact_get_object_failure_for_one_key_leaves_others_processed(self):
        """A get_object failure for one staging key is caught and logged; other keys still read."""
        good_entry = {
            "id": "ep-001",
            "created_timestamp": "2026-04-20T10:00:00+00:00",
            "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
        }
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "staging/ops_priority_queue/dt=2026-04-20/batch-bad.jsonl"},
                    {"Key": "staging/ops_priority_queue/dt=2026-04-20/batch-good.jsonl"},
                ]
            }
        ]
        mock_client.get_paginator.return_value = mock_paginator

        def _get_object(Bucket, Key):  # noqa: N803
            if Key.endswith("batch-bad.jsonl"):
                raise RuntimeError("S3 read failure")
            return {"Body": MagicMock(read=MagicMock(return_value=json.dumps(good_entry).encode("utf-8")))}

        mock_client.get_object.side_effect = _get_object

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.catalog.get_table_types.return_value = {}
            count = writer.compact("ops_priority_queue", "2026-04-20")

        assert count == 1  # only the good key's row survives

    def test_compact_returns_zero_when_all_rows_filtered_out(self):
        """compact() returns 0 when every staging line is blank (rows ends up empty)."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_priority_queue/dt=2026-04-20/batch-blank.jsonl"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"\n\n  \n"))}

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            count = writer.compact("ops_priority_queue", "2026-04-20")

        assert count == 0


class TestOpsWriterCompactSchemaEvolutionDetectionFailure:
    """The schema-evolution detection's own try/except (table not yet created)."""

    def test_compact_get_table_types_failure_treated_as_initial_creation(self):
        """wr.catalog.get_table_types raising is swallowed -- treated as first-time table creation."""
        entries = [
            {
                "id": "ep-001",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        mock_client = _make_mock_client_with_staging(entries)
        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
            patch.object(writer, "_refresh_view") as mock_refresh,
        ):
            mock_wr.catalog.get_table_types.side_effect = RuntimeError("table does not exist yet")
            count = writer.compact("ops_priority_queue", "2026-04-20")

        assert count == 1
        mock_wr.athena.to_iceberg.assert_called_once()
        # schema_evolved stays False when detection itself fails -- _refresh_view is never called
        mock_refresh.assert_not_called()
