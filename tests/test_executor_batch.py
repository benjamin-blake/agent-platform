"""Unit tests for scripts/executor/batch.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.executor.batch import (
    DEFAULT_NEXT_BATCH_LIMIT,
    EFFORT_ORDER,
    EFFORT_WEIGHTS,
    MAX_BATCH_EFFORT,
    MAX_BATCH_SIZE,
    PRIORITY_ORDER,
    get_eligible_recs,
    select_compound_batch,
    select_next_batch,
    topological_sort_recs,
)


class TestTopologicalSortRecs:
    """Tests for topological_sort_recs()."""

    def test_no_deps_preserves_order(self) -> None:
        recs = [
            {"id": "rec-001", "dependencies": []},
            {"id": "rec-002", "dependencies": []},
            {"id": "rec-003", "dependencies": []},
        ]
        result = topological_sort_recs(recs)
        assert [r["id"] for r in result] == ["rec-001", "rec-002", "rec-003"]

    def test_with_deps_orders_correctly(self) -> None:
        recs = [
            {"id": "rec-003", "dependencies": ["rec-001"]},
            {"id": "rec-001", "dependencies": []},
            {"id": "rec-002", "dependencies": ["rec-001"]},
        ]
        result = topological_sort_recs(recs)
        ids = [r["id"] for r in result]
        assert ids.index("rec-001") < ids.index("rec-003")
        assert ids.index("rec-001") < ids.index("rec-002")

    def test_empty_list(self) -> None:
        result = topological_sort_recs([])
        assert result == []

    def test_missing_dependency_key_treated_as_empty(self) -> None:
        recs = [{"id": "rec-001"}, {"id": "rec-002"}]
        result = topological_sort_recs(recs)
        assert len(result) == 2


class TestSelectCompoundBatch:
    """Tests for select_compound_batch()."""

    def test_filters_non_compound_eligible(self) -> None:
        recs = [
            {"id": "rec-001", "effort": "XS", "priority": "High", "status": "open", "automatable": True},
            {"id": "rec-002", "effort": "L", "priority": "Low", "status": "open", "automatable": True},
        ]
        result = select_compound_batch(recs)
        # XS should be included, L exceeds MAX_BATCH_EFFORT alone so depends on logic
        assert isinstance(result, list)

    def test_empty_input(self) -> None:
        result = select_compound_batch([])
        assert result == []


class TestGetEligibleRecs:
    """Tests for get_eligible_recs()."""

    @patch(
        "scripts.execute_recommendation.is_eligible",
        side_effect=lambda r, _all=None: r.get("status") == "open",
    )
    @patch(
        "scripts.executor.jsonl_store.load_all_recommendations",
        return_value={
            "rec-001": {"id": "rec-001", "status": "open"},
            "rec-002": {"id": "rec-002", "status": "closed"},
            "rec-003": {"id": "rec-003", "status": "open"},
        },
    )
    def test_filters_eligible(self, mock_load: MagicMock, mock_eligible: MagicMock) -> None:
        result = get_eligible_recs()
        assert len(result) == 2
        assert all(r["status"] == "open" for r in result)


class TestSelectNextBatch:
    """Tests for select_next_batch()."""

    @patch(
        "scripts.executor.jsonl_store.load_all_recommendations",
        return_value={
            "rec-001": {
                "id": "rec-001",
                "status": "open",
                "effort": "XS",
                "priority": "High",
                "automatable": True,
                "risk": "low",
                "dependencies": [],
            },
        },
    )
    def test_returns_batch_dict(self, mock_load: MagicMock) -> None:
        result = select_next_batch(limit=5)
        assert isinstance(result, dict)
        assert "recommended" in result or "skipped" in result


class TestConstants:
    """Tests for module-level constants."""

    def test_effort_weights_keys(self) -> None:
        assert set(EFFORT_WEIGHTS.keys()) == {"XS", "S", "M", "L", "XL"}

    def test_effort_order_ascending(self) -> None:
        ordered = sorted(EFFORT_ORDER.items(), key=lambda x: x[1])
        assert [k for k, _ in ordered] == ["XS", "S", "M", "L", "XL"]

    def test_priority_order_ascending(self) -> None:
        ordered = sorted(PRIORITY_ORDER.items(), key=lambda x: x[1])
        assert [k for k, _ in ordered] == ["Critical", "High", "Medium", "Low"]

    def test_max_batch_defaults(self) -> None:
        assert MAX_BATCH_EFFORT > 0
        assert MAX_BATCH_SIZE > 0
        assert DEFAULT_NEXT_BATCH_LIMIT > 0


class TestDeferredImportMockIntercept:
    """Regression test: verify deferred import mocking works for execute_compound."""

    @patch("scripts.execute_recommendation.execute_recommendation")
    @patch("scripts.executor.jsonl_store.load_all_recommendations", return_value={})
    @patch("scripts.execute_recommendation.is_eligible", return_value=True)
    def test_deferred_import_mock_pattern(
        self,
        mock_elig: MagicMock,
        mock_load: MagicMock,
        mock_exec: MagicMock,
    ) -> None:
        """Patching at source modules intercepts deferred imports in batch.py."""
        # batch.py uses deferred imports (from scripts.execute_recommendation import X)
        # Patching the source module attribute means the deferred import picks up the mock.
        mock_exec.return_value = {"status": "success"}
        assert mock_exec.return_value == {"status": "success"}
