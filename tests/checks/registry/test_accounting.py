"""Tests for the accounting channel (Decision 170): registry.py's examined()/skipped()/
outcome_scope() declaration API and its status-derivation function, exercised through a REAL
dispatch pass (validation_result.dispatch_recording -- the actual production harvesting path),
not a direct unit call on derive_status()/build_outcome() alone.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks import registry, validation_result


class TestStatusDerivationThroughRealDispatch:
    """VP step 1: five outcome states, proven distinguishable after a real dispatch_recording()
    pass -- not four collapsed into "not failed"."""

    def setup_method(self) -> None:
        validation_result.clear()

    def _dispatch(self, name: str, fn) -> list[str]:
        failed: list[str] = []
        validation_result.dispatch_recording(name, failed, fn)
        return failed

    def test_examined_zero_yields_vacuous(self) -> None:
        self._dispatch("check_vacuous", lambda failed: registry.examined(0))
        row = validation_result._OUTCOMES[-1]
        assert row.check == "check_vacuous"
        assert row.kind == "check"
        assert row.status == "vacuous"
        assert row.examined_count == 0
        assert row.examined_unit == "items"

    def test_examined_positive_yields_enforced(self) -> None:
        self._dispatch("check_enforced", lambda failed: registry.examined(3, unit="files"))
        row = validation_result._OUTCOMES[-1]
        assert row.status == "enforced"
        assert row.examined_count == 3
        assert row.examined_unit == "files"

    def test_skipped_yields_skipped(self) -> None:
        self._dispatch("check_skipped", lambda failed: registry.skipped("no creds"))
        row = validation_result._OUTCOMES[-1]
        assert row.status == "skipped"
        assert row.skipped_reason == "no creds"
        assert row.examined_count is None

    def test_no_declaration_yields_undeclared(self) -> None:
        self._dispatch("check_undeclared", lambda failed: None)
        row = validation_result._OUTCOMES[-1]
        assert row.status == "undeclared"
        assert row.examined_count is None
        assert row.skipped_reason is None

    def test_append_to_failed_yields_failed_regardless_of_declaration(self) -> None:
        """Any append to `failed` => "failed", even when the check ALSO declared examined()."""

        def _fn(failed: list[str]) -> None:
            registry.examined(5)
            failed.append("boom")

        failed = self._dispatch("check_failing", _fn)
        assert failed == ["boom"]
        row = validation_result._OUTCOMES[-1]
        assert row.status == "failed"

    def test_skipped_declaration_also_loses_to_a_failed_append(self) -> None:
        def _fn(failed: list[str]) -> None:
            registry.skipped("ignored")
            failed.append("boom")

        self._dispatch("check_failing_after_skip", _fn)
        row = validation_result._OUTCOMES[-1]
        assert row.status == "failed"


class TestDeclarationSlotAndRowAccumulatorLifecycle:
    """The per-dispatch DECLARATION SLOT resets on each outcome_scope entry; the ROW ACCUMULATOR
    resets per RUN via validation_result.clear() -- mirroring _ATTRIBUTIONS' contract."""

    def setup_method(self) -> None:
        validation_result.clear()

    def test_declaration_slot_does_not_leak_between_dispatches(self) -> None:
        validation_result.dispatch_recording("first", [], lambda f: registry.examined(7))
        validation_result.dispatch_recording("second", [], lambda f: None)
        rows = {o.check: o for o in validation_result._OUTCOMES}
        assert rows["first"].status == "enforced"
        assert rows["second"].status == "undeclared"

    def test_row_accumulator_grows_by_one_per_dispatch_within_a_run(self) -> None:
        for i in range(3):
            validation_result.dispatch_recording(f"check_{i}", [], lambda f: registry.examined(1))
        assert len(validation_result._OUTCOMES) == 3

    def test_clear_resets_the_row_accumulator_between_runs(self) -> None:
        validation_result.dispatch_recording("check_x", [], lambda f: registry.examined(1))
        assert len(validation_result._OUTCOMES) == 1
        validation_result.clear()
        assert validation_result._OUTCOMES == []

    def test_outcome_scope_resets_a_stale_declaration_left_by_a_prior_scope(self) -> None:
        """A pathological caller that calls examined()/skipped() OUTSIDE any outcome_scope just
        before a real dispatch must not have that stray declaration attributed to the dispatch."""
        registry.examined(99)  # stray declaration, no active scope
        validation_result.dispatch_recording("clean_dispatch", [], lambda f: None)
        row = validation_result._OUTCOMES[-1]
        assert row.status == "undeclared"


class TestScaffoldOutcomeHarvest:
    """record_scaffold_outcome() is the scaffold-side harvesting counterpart to
    dispatch_recording() -- used by non-check scaffolds like ensure_fresh_dq_results."""

    def setup_method(self) -> None:
        validation_result.clear()

    def test_scaffold_outcome_is_recorded_with_kind_scaffold(self) -> None:
        failed: list[str] = []
        before = len(failed)
        with registry.outcome_scope("my_scaffold", kind="scaffold"):
            registry.skipped("not needed")
        validation_result.record_scaffold_outcome("my_scaffold", before, failed)
        row = validation_result._OUTCOMES[-1]
        assert row.check == "my_scaffold"
        assert row.kind == "scaffold"
        assert row.status == "skipped"

    def test_scaffold_that_appends_to_failed_is_failed_regardless_of_declaration(self) -> None:
        failed: list[str] = []
        before = len(failed)
        with registry.outcome_scope("failing_scaffold", kind="scaffold"):
            registry.examined(4)
            failed.append("scaffold broke")
        validation_result.record_scaffold_outcome("failing_scaffold", before, failed)
        row = validation_result._OUTCOMES[-1]
        assert row.status == "failed"


class TestWriteCompletedEmitsCheckOutcomesAndRollups:
    def setup_method(self) -> None:
        validation_result.clear()

    def test_write_completed_records_one_row_per_dispatched_check_and_rollups(self, tmp_path: Path) -> None:
        validation_result.dispatch_recording("vacuous_check", [], lambda f: registry.examined(0))
        validation_result.dispatch_recording("enforced_check", [], lambda f: registry.examined(2))
        validation_result.dispatch_recording("skipped_check", [], lambda f: registry.skipped("unavailable"))
        validation_result.dispatch_recording("undeclared_check", [], lambda f: None)
        failed_list: list[str] = []
        validation_result.dispatch_recording("failing_check", failed_list, lambda f: f.append("bad"))

        record = validation_result.write_completed(
            started_at=validation_result.utc_now(),
            exit_code=1,
            failed_checks=failed_list,
            path=tmp_path / "validation-result.json",
        )

        by_check = {row["check"]: row for row in record["check_outcomes"]}
        assert len(record["check_outcomes"]) == 5
        assert by_check["vacuous_check"]["status"] == "vacuous"
        assert by_check["enforced_check"]["status"] == "enforced"
        assert by_check["skipped_check"]["status"] == "skipped"
        assert by_check["undeclared_check"]["status"] == "undeclared"
        assert by_check["failing_check"]["status"] == "failed"
        assert record["ran_checks"] == 1
        assert record["skipped_checks"] == 1
        assert record["vacuous_checks"] == 1
        assert record["undeclared_checks"] == 1
