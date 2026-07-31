"""Tests for scripts/sync/ops.py -- coercion-helper edge-branch concern.

PLAN-coverage-paydown-ops-writer-sync-ops: covers the remaining uncovered branches across
_coerce_rows_list (8), _coerce_ops_execution_plans_row (8), _coerce_ops_decisions_row (4),
_coerce_athena_array (4) = 24 statements. Collision-free (existing module is test_coercion.py).
"""

from __future__ import annotations

from unittest.mock import patch


class TestCoerceAthenaArrayExceptionPaths:
    def test_list_input_skips_element_that_fails_elem_type_conversion(self):
        """A native-list element that raises ValueError/TypeError on elem_type() is dropped."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array([1, "not-an-int", 2], elem_type=int) == [1, 2]

    def test_scalar_fallback_returns_empty_list_on_conversion_failure(self):
        """A non-bracketed scalar string that fails elem_type() conversion returns []."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("not-an-int", elem_type=int) == []


class TestIntCoercionExceptionPaths:
    """The int()-conversion except branches shared shape across three row coercers."""

    def test_ops_rec_row_unparsable_execution_steps_becomes_none(self):
        """_coerce_ops_rec_row: a non-numeric execution_steps string is caught and becomes None."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "execution_steps": "not-a-number"}
        result = _coerce_ops_rec_row(row)
        assert result["execution_steps"] is None

    def test_ops_priority_queue_row_unparsable_rank_becomes_none(self):
        """_coerce_ops_priority_queue_row: a non-numeric rank string is caught and becomes None."""
        from scripts.sync.ops import _coerce_ops_priority_queue_row

        row = {"rank": "not-a-number", "compound_with": "[]", "gates": "[]"}
        result = _coerce_ops_priority_queue_row(row)
        assert result["rank"] is None

    def test_ops_session_log_row_unparsable_duration_becomes_none(self):
        """_coerce_ops_session_log_row: a non-numeric duration_minutes string is caught and becomes None."""
        from scripts.sync.ops import _coerce_ops_session_log_row

        row = {"duration_minutes": "not-a-number", "recs_attempted": "[]", "recs_closed": "[]"}
        result = _coerce_ops_session_log_row(row)
        assert result["duration_minutes"] is None


class TestCoerceOpsDecisionsRowExceptionPaths:
    def test_unparsable_decision_id_string_becomes_none(self):
        """A decision_id that cannot be int()-coerced becomes None (caught ValueError)."""
        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"decision_id": "not-a-number"}
        result = _coerce_ops_decisions_row(row)
        assert result["decision_id"] is None

    def test_id_without_hyphen_suffix_raises_indexerror_caught_silently(self):
        """id.split('-')[1] raising IndexError (no hyphen) is caught -- no reject, no crash."""
        from scripts.sync.ops import _coerce_ops_decisions_row

        with patch("scripts.sync.ops._write_decisions_sync_reject") as mock_reject:
            result = _coerce_ops_decisions_row({"id": "dec", "decision_id": "5"})

        assert result["id"] == "dec"
        assert result["decision_id"] == 5
        mock_reject.assert_not_called()

    def test_id_suffix_non_numeric_raises_valueerror_caught_silently(self):
        """int(dec_id.split('-')[1]) raising ValueError (non-numeric suffix) is caught silently."""
        from scripts.sync.ops import _coerce_ops_decisions_row

        with patch("scripts.sync.ops._write_decisions_sync_reject") as mock_reject:
            result = _coerce_ops_decisions_row({"id": "dec-abc", "decision_id": "7"})

        assert result["id"] == "dec-abc"
        assert result["decision_id"] == 7
        mock_reject.assert_not_called()


class TestCoerceOpsExecutionPlansRow:
    """The whole function -- not exercised by any existing test module."""

    def test_decodes_valid_json_blob_columns(self):
        """steps/critique_history JSON-string blobs decode to native Python lists."""
        from scripts.sync.ops import _coerce_ops_execution_plans_row

        row = {
            "id": "plan-001",
            "steps": '[{"step": 1, "action": "do it"}]',
            "critique_history": '["round 1 feedback"]',
        }
        result = _coerce_ops_execution_plans_row(row)
        assert result["steps"] == [{"step": 1, "action": "do it"}]
        assert result["critique_history"] == ["round 1 feedback"]

    def test_blank_string_decodes_to_empty_list(self):
        """A blank/whitespace-only string field decodes to []."""
        from scripts.sync.ops import _coerce_ops_execution_plans_row

        row = {"id": "plan-002", "steps": "   ", "critique_history": ""}
        result = _coerce_ops_execution_plans_row(row)
        assert result["steps"] == []
        assert result["critique_history"] == []

    def test_malformed_json_is_left_unchanged(self):
        """Malformed JSON raises JSONDecodeError, which is caught -- the raw string survives."""
        from scripts.sync.ops import _coerce_ops_execution_plans_row

        row = {"id": "plan-003", "steps": "not valid json{{{"}
        result = _coerce_ops_execution_plans_row(row)
        assert result["steps"] == "not valid json{{{"

    def test_non_string_field_is_left_unchanged(self):
        """A field that is already a native list (not a str) is passed through untouched."""
        from scripts.sync.ops import _coerce_ops_execution_plans_row

        row = {"id": "plan-004", "steps": [{"step": 1}], "critique_history": None}
        result = _coerce_ops_execution_plans_row(row)
        assert result["steps"] == [{"step": 1}]
        assert result["critique_history"] is None

    def test_missing_fields_are_absent_not_crashing(self):
        """A row without steps/critique_history keys returns unchanged, no KeyError."""
        from scripts.sync.ops import _coerce_ops_execution_plans_row

        row = {"id": "plan-005"}
        result = _coerce_ops_execution_plans_row(row)
        assert result == {"id": "plan-005"}


class TestCoerceRowsListDispatch:
    """_coerce_rows_list's per-table dispatch branches and reject-counting path."""

    def test_rejects_invalid_ops_recommendations_row_and_skips_it(self):
        """A row that _coerce_ops_rec_row rejects (returns None) is excluded from the output list."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [
            {"id": "dec-42", "title": "invalid prefix", "source": "manual", "effort": "S", "priority": "Low"},
            {"id": "rec-001", "title": "valid", "source": "manual", "effort": "S", "priority": "Low"},
        ]
        result = _coerce_rows_list("ops_recommendations", rows)
        assert len(result) == 1
        assert result[0]["id"] == "rec-001"

    def test_rejects_ops_recommendations_row_missing_required_fields(self):
        """A row missing a required field is rejected and excluded, logging via _write_sync_reject."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"id": "rec-001", "title": "", "source": "manual", "effort": "S", "priority": "Low"}]
        with patch("scripts.sync.ops._write_sync_reject") as mock_reject:
            result = _coerce_rows_list("ops_recommendations", rows)
        assert result == []
        mock_reject.assert_called_once()

    def test_dispatches_ops_priority_queue_coercion(self):
        """_coerce_rows_list routes ops_priority_queue rows through _coerce_ops_priority_queue_row."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"rank": "3", "compound_with": "[]", "gates": "[]"}]
        result = _coerce_rows_list("ops_priority_queue", rows)
        assert result[0]["rank"] == 3

    def test_dispatches_ops_decisions_coercion(self):
        """_coerce_rows_list routes ops_decisions rows through _coerce_ops_decisions_row."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"decision_id": "42", "related_decisions": "[]"}]
        result = _coerce_rows_list("ops_decisions", rows)
        assert result[0]["decision_id"] == 42

    def test_dispatches_ops_session_log_coercion(self):
        """_coerce_rows_list routes ops_session_log rows through _coerce_ops_session_log_row."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"duration_minutes": "45", "recs_attempted": "[]", "recs_closed": "[]"}]
        result = _coerce_rows_list("ops_session_log", rows)
        assert result[0]["duration_minutes"] == 45

    def test_dispatches_ops_execution_plans_coercion(self):
        """_coerce_rows_list routes ops_execution_plans rows through _coerce_ops_execution_plans_row."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"id": "plan-001", "steps": '["step 1"]'}]
        result = _coerce_rows_list("ops_execution_plans", rows)
        assert result[0]["steps"] == ["step 1"]

    def test_unrecognised_table_passes_rows_through_unmodified(self):
        """A table name with no dispatch branch passes rows through as-is."""
        from scripts.sync.ops import _coerce_rows_list

        rows = [{"foo": "bar"}]
        result = _coerce_rows_list("not_a_dispatched_table", rows)
        assert result == [{"foo": "bar"}]
