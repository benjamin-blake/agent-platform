"""Tests for the DCG-03 divergence guard in scripts/ops_portal/decisions.py
(PLAN-dcg-compaction-lifecycle, Decision 149; audits/decision-consolidation-growth-f79d6b5.yaml).

Covers the pure diff helper (_orphaned_current_ids), the checked-in allowlist loader
(_load_orphan_baseline), and the guard itself (_assert_no_orphaned_current_rows) via an
injected fake reader -- proving both the loud-failure path (a synthetic, non-baselined,
header-less decision_id) and the baselined-tolerated path (the real checked-in dec-010 entry).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestOrphanedCurrentIdsHelper:
    """Pure unit tests for _orphaned_current_ids -- no I/O, no reader, no filesystem."""

    def test_returns_current_ids_with_no_header_and_not_baselined(self) -> None:
        from scripts.ops_portal.decisions import _orphaned_current_ids

        current_ids = {"dec-001", "dec-002", "dec-999"}
        header_numbers = {1, 2}
        baseline: set[str] = set()

        assert _orphaned_current_ids(current_ids, header_numbers, baseline) == {"dec-999"}

    def test_baseline_suppresses_a_known_orphan(self) -> None:
        from scripts.ops_portal.decisions import _orphaned_current_ids

        current_ids = {"dec-001", "dec-010"}
        header_numbers = {1}
        baseline = {"dec-010"}

        assert _orphaned_current_ids(current_ids, header_numbers, baseline) == set()

    def test_headered_id_never_counted_as_orphan(self) -> None:
        from scripts.ops_portal.decisions import _orphaned_current_ids

        current_ids = {"dec-005"}
        header_numbers = {5}
        baseline: set[str] = set()

        assert _orphaned_current_ids(current_ids, header_numbers, baseline) == set()

    def test_empty_current_ids_yields_no_orphans(self) -> None:
        from scripts.ops_portal.decisions import _orphaned_current_ids

        assert _orphaned_current_ids(set(), {1, 2, 3}, {"dec-010"}) == set()

    def test_does_not_mutate_inputs(self) -> None:
        from scripts.ops_portal.decisions import _orphaned_current_ids

        current_ids = {"dec-001", "dec-999"}
        header_numbers = {1}
        baseline: set[str] = set()

        result = _orphaned_current_ids(current_ids, header_numbers, baseline)

        assert result == {"dec-999"}
        assert current_ids == {"dec-001", "dec-999"}
        assert header_numbers == {1}
        assert baseline == set()


class TestLoadOrphanBaseline:
    """Tests for _load_orphan_baseline -- the checked-in allowlist reader."""

    def test_loads_checked_in_dec_010_baseline(self) -> None:
        """The real, committed orphan_baseline.yaml seeds exactly dec-010 (DCG-03 discovery)."""
        from scripts.ops_portal.decisions import _load_orphan_baseline

        baseline = _load_orphan_baseline()

        assert "dec-010" in baseline

    def test_missing_file_returns_empty_set(self, tmp_path) -> None:
        from scripts.ops_portal import decisions as decisions_module

        with patch.object(decisions_module, "_ORPHAN_BASELINE_PATH", tmp_path / "does-not-exist.yaml"):
            assert decisions_module._load_orphan_baseline() == set()


class TestAssertNoOrphanedCurrentRows:
    """Synthetic removed-header test: an injected fake reader proves the loud-fail path,
    and the real checked-in dec-010 baseline proves the tolerated path."""

    def test_raises_on_new_non_baselined_orphan(self) -> None:
        """A non-baselined, header-less decision_id in the current projection raises RuntimeError."""
        from scripts.ops_portal.decisions import _assert_no_orphaned_current_rows

        fake_reader = MagicMock()
        fake_reader.current_state.return_value = [
            {"id": "dec-001", "status": "Decided"},
            {"id": "dec-999999", "status": "Decided"},  # synthetic: not baselined, no header
        ]

        with patch("scripts.decisions_md.decision_header_numbers", return_value={1}):
            with pytest.raises(RuntimeError, match="dec-999999"):
                _assert_no_orphaned_current_rows(reader=fake_reader)

        fake_reader.current_state.assert_called_once_with("ops_decisions")

    def test_tolerates_the_baselined_dec_010_orphan(self) -> None:
        """dec-010 (the real checked-in baseline entry) never trips the guard, even with an
        all-headed set of ids also present in the current projection."""
        from scripts.ops_portal.decisions import _assert_no_orphaned_current_rows

        fake_reader = MagicMock()
        fake_reader.current_state.return_value = [
            {"id": "dec-001", "status": "Decided"},
            {"id": "dec-010", "status": "open"},  # the real, pre-existing leaked test row
        ]

        with patch("scripts.decisions_md.decision_header_numbers", return_value={1}):
            _assert_no_orphaned_current_rows(reader=fake_reader)  # must not raise

    def test_ignores_rows_with_no_id(self) -> None:
        """A malformed row with no 'id' key is skipped rather than crashing or false-flagging."""
        from scripts.ops_portal.decisions import _assert_no_orphaned_current_rows

        fake_reader = MagicMock()
        fake_reader.current_state.return_value = [{"status": "Decided"}]

        with patch("scripts.decisions_md.decision_header_numbers", return_value=set()):
            _assert_no_orphaned_current_rows(reader=fake_reader)  # must not raise

    def test_default_reader_resolves_via_make_reader(self) -> None:
        """With no injected reader, the guard falls back to make_reader(profile=...)."""
        from scripts.ops_portal.decisions import _assert_no_orphaned_current_rows

        fake_reader = MagicMock()
        fake_reader.current_state.return_value = []

        with (
            patch("src.common.iceberg_reader.make_reader", return_value=fake_reader) as mock_make_reader,
            patch("scripts.decisions_md.decision_header_numbers", return_value=set()),
        ):
            _assert_no_orphaned_current_rows(profile="agent_platform")

        mock_make_reader.assert_called_once_with(profile="agent_platform")
        fake_reader.current_state.assert_called_once_with("ops_decisions")


class TestBackfillWiresOrphanGuard:
    """Confirms backfill_decisions_from_md calls the DCG-03 guard with its injectable seam."""

    def test_backfill_propagates_orphan_reader_and_raises(self) -> None:
        """A backfill run with zero DECISIONS.md entries still runs the orphan guard, which
        raises when the injected orphan_reader reports a new orphan."""
        fake_reader = MagicMock()
        fake_reader.current_state.return_value = [{"id": "dec-999999"}]

        with (
            patch("scripts.decisions_md.parse_decisions_md", return_value=[]),
            patch("scripts.decisions_md.decision_header_numbers", return_value=set()),
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import backfill_decisions_from_md

            with pytest.raises(RuntimeError, match="DCG-03 divergence guard"):
                backfill_decisions_from_md(orphan_reader=fake_reader)

        mock_sync.assert_not_called()
        fake_reader.current_state.assert_called_once_with("ops_decisions")

    def test_backfill_clean_run_with_baselined_orphan_only(self) -> None:
        """A backfill run tolerates the current-warehouse dec-010 orphan via the real baseline."""
        fake_reader = MagicMock()
        fake_reader.current_state.return_value = [{"id": "dec-010"}]

        with (
            patch("scripts.decisions_md.parse_decisions_md", return_value=[]),
            patch("scripts.decisions_md.decision_header_numbers", return_value=set()),
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import backfill_decisions_from_md

            result = backfill_decisions_from_md(orphan_reader=fake_reader)

        assert result == {"written": 0, "failed": 0, "skipped": 0}
        mock_sync.assert_not_called()
