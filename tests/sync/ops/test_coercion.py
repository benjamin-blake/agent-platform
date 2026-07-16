"""Athena/reader row-coercion helpers concern: tests/sync/ops/test_coercion.py (rec-2709 Wave 10).

Split from the former tests/test_sync_ops.py monolith: TestCoerceOpsRecRow, TestCoerceAthenaArray,
TestCoerceOpsPriorityQueueRow, TestCoerceOpsDecisionsRow, TestCoerceOpsSessionLogRow, and the
module-level test_coerce_athena_array_handles_native_list.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _coerce_ops_rec_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsRecRow:
    def test_coerces_bracket_array_fields_to_list(self):
        """Athena bracket-array strings are split into Python lists."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "[dep-001, dep-002]", "tags": "[alpha, beta]", "execution_steps": "3"}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == ["dep-001", "dep-002"]
        assert result["tags"] == ["alpha", "beta"]
        assert result["execution_steps"] == 3

    def test_coerces_empty_bracket_to_empty_list(self):
        """An empty bracket string '[]' becomes an empty Python list."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "[]", "tags": "[]", "execution_steps": ""}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []
        assert result["execution_steps"] is None

    def test_coerces_null_varchar_to_empty_list(self):
        """A null VarChar '' for array fields becomes an empty list."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "", "tags": ""}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []

    def test_coerces_execution_steps_integer_string(self):
        """A numeric string for execution_steps becomes an int."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "execution_steps": "5"}
        result = _coerce_ops_rec_row(row)
        assert result["execution_steps"] == 5

    def test_passes_through_int_execution_steps_unchanged(self):
        """An already-int execution_steps value is not modified."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "execution_steps": 7}
        result = _coerce_ops_rec_row(row)
        assert result["execution_steps"] == 7

    def test_handles_missing_fields_gracefully(self):
        """Rows without array/int fields get safe defaults, no KeyError."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "status": "open"}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []
        assert result["execution_steps"] is None

    def test_coerces_automatable_empty_string_to_none(self):
        """Athena NULL for automatable arrives as '' and must become None."""
        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "automatable": ""}
        result = _coerce_ops_rec_row(row)
        assert result["automatable"] is None

    def test_coerces_automatable_true_string_to_bool(self):
        """Athena boolean strings 'true'/'false' become Python booleans."""
        from scripts.sync.ops import _coerce_ops_rec_row

        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": "true"})["automatable"] is True
        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": "false"})["automatable"] is False

    def test_passes_through_bool_automatable_unchanged(self):
        """An already-bool automatable value is not modified."""
        from scripts.sync.ops import _coerce_ops_rec_row

        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": True})["automatable"] is True
        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": False})["automatable"] is False


# ---------------------------------------------------------------------------
# _coerce_athena_array() tests
# ---------------------------------------------------------------------------


class TestCoerceAthenaArray:
    def test_bracket_string_parses_to_list(self):
        """'[a, b]' parses to ['a', 'b']."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("[a, b]") == ["a", "b"]

    def test_empty_bracket_returns_empty_list(self):
        """'[]' returns []."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("[]") == []

    def test_empty_string_returns_empty_list(self):
        """Athena NULL ('')  returns []."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("") == []

    def test_none_value_returns_empty_list(self):
        """None input returns []."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array(None) == []

    def test_scalar_string_wraps_in_list(self):
        """A plain string without brackets becomes a one-element list."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("rec-001") == ["rec-001"]

    def test_int_elem_type_coerces_elements(self):
        """elem_type=int converts each element."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("[1, 2, 3]", elem_type=int) == [1, 2, 3]

    def test_int_elem_type_invalid_element_skipped(self):
        """Invalid elements for the given elem_type are silently skipped."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("[1, notanint, 3]", elem_type=int) == [1, 3]

    def test_scalar_int_elem_type_wraps(self):
        """A plain '5' with elem_type=int returns [5]."""
        from scripts.sync.ops import _coerce_athena_array

        assert _coerce_athena_array("5", elem_type=int) == [5]


# ---------------------------------------------------------------------------
# _coerce_ops_priority_queue_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsPriorityQueueRow:
    def test_coerces_rank_string_to_int(self):
        from scripts.sync.ops import _coerce_ops_priority_queue_row

        row = {"rank": "3", "compound_with": "[]", "gates": "[]"}
        result = _coerce_ops_priority_queue_row(row)
        assert result["rank"] == 3
        assert result["compound_with"] == []
        assert result["gates"] == []

    def test_coerces_array_fields(self):
        from scripts.sync.ops import _coerce_ops_priority_queue_row

        row = {"rank": "1", "compound_with": "[rec-002, rec-003]", "gates": "[gate-a]"}
        result = _coerce_ops_priority_queue_row(row)
        assert result["compound_with"] == ["rec-002", "rec-003"]
        assert result["gates"] == ["gate-a"]

    def test_null_rank_becomes_none(self):
        from scripts.sync.ops import _coerce_ops_priority_queue_row

        row = {"rank": ""}
        result = _coerce_ops_priority_queue_row(row)
        assert result["rank"] is None


# ---------------------------------------------------------------------------
# _coerce_ops_decisions_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsDecisionsRow:
    def test_coerces_decision_id_string_to_int(self):
        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"decision_id": "42", "related_decisions": "[]"}
        result = _coerce_ops_decisions_row(row)
        assert result["decision_id"] == 42
        assert result["related_decisions"] == []

    def test_coerces_related_decisions_array_to_int_list(self):
        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"decision_id": "1", "related_decisions": "[2, 3, 4]"}
        result = _coerce_ops_decisions_row(row)
        assert result["related_decisions"] == [2, 3, 4]

    def test_null_decision_id_becomes_none(self):
        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"decision_id": ""}
        result = _coerce_ops_decisions_row(row)
        assert result["decision_id"] is None

    def test_populates_id_from_decision_id_when_absent(self):
        """When id is absent, populates it as dec-NNN from decision_id (D11)."""
        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"decision_id": "37"}
        result = _coerce_ops_decisions_row(row)
        assert result["id"] == "dec-037"
        assert result["decision_id"] == 37

    def test_dual_write_violation_logs_reject(self):
        """Mismatched id/decision_id calls _write_decisions_sync_reject (D11)."""
        from unittest.mock import patch

        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"id": "dec-010", "decision_id": "99"}
        with patch("scripts.sync.ops._write_decisions_sync_reject") as mock_reject:
            _coerce_ops_decisions_row(row)
        mock_reject.assert_called_once()
        reason = mock_reject.call_args[0][1]
        assert "dual-write invariant" in reason

    def test_no_reject_when_invariant_holds(self):
        """Matched id/decision_id does not call _write_decisions_sync_reject (D11)."""
        from unittest.mock import patch

        from scripts.sync.ops import _coerce_ops_decisions_row

        row = {"id": "dec-042", "decision_id": "42"}
        with patch("scripts.sync.ops._write_decisions_sync_reject") as mock_reject:
            _coerce_ops_decisions_row(row)
        mock_reject.assert_not_called()


# ---------------------------------------------------------------------------
# _coerce_ops_session_log_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsSessionLogRow:
    def test_coerces_array_fields(self):
        from scripts.sync.ops import _coerce_ops_session_log_row

        row = {"recs_attempted": "[rec-001, rec-002]", "recs_closed": "[rec-001]", "duration_minutes": "45"}
        result = _coerce_ops_session_log_row(row)
        assert result["recs_attempted"] == ["rec-001", "rec-002"]
        assert result["recs_closed"] == ["rec-001"]
        assert result["duration_minutes"] == 45

    def test_null_duration_becomes_none(self):
        from scripts.sync.ops import _coerce_ops_session_log_row

        row = {"duration_minutes": ""}
        result = _coerce_ops_session_log_row(row)
        assert result["duration_minutes"] is None

    def test_empty_array_fields_return_empty_list(self):
        from scripts.sync.ops import _coerce_ops_session_log_row

        row = {"recs_attempted": "", "recs_closed": "[]"}
        result = _coerce_ops_session_log_row(row)
        assert result["recs_attempted"] == []
        assert result["recs_closed"] == []


def test_coerce_athena_array_handles_native_list():
    """DuckLake reader returns native lists; the coercion returns them element-typed (not re-parsed)."""
    from scripts.sync.ops import _coerce_athena_array

    assert _coerce_athena_array(["rec-1", "rec-2"]) == ["rec-1", "rec-2"]
    assert _coerce_athena_array([1, 2, 3], elem_type=int) == [1, 2, 3]
    assert _coerce_athena_array([None, "x"]) == ["x"]
    # Athena string form still parses
    assert _coerce_athena_array("[a, b]") == ["a", "b"]
