from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry, validation_result


@pytest.fixture(autouse=True)
def _reset_attributions():
    validation_result._ATTRIBUTIONS.clear()
    validation_result._OUTCOMES.clear()
    yield
    validation_result._ATTRIBUTIONS.clear()
    validation_result._OUTCOMES.clear()


def test_clear_removes_stale_result(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("stale", encoding="utf-8")
    validation_result.clear(path)
    assert not path.exists()


def test_clear_resets_the_attribution_accumulator(tmp_path: Path) -> None:
    validation_result._ATTRIBUTIONS.append({"check": "stale_check", "label": "stale label"})
    validation_result.clear(tmp_path / "result.json")
    assert validation_result._ATTRIBUTIONS == []


def test_dispatch_recording_attributes_each_newly_appended_label() -> None:
    def _two_failures(failed: list[str]) -> None:
        failed.append("first problem")
        failed.append("second problem")

    failed: list[str] = []
    validation_result.dispatch_recording("validate_two_things", failed, _two_failures)
    assert failed == ["first problem", "second problem"]
    assert validation_result._ATTRIBUTIONS == [
        {"check": "validate_two_things", "label": "first problem"},
        {"check": "validate_two_things", "label": "second problem"},
    ]


def test_record_scaffold_outcome_harvests_a_declared_outcome() -> None:
    """record_scaffold_outcome() is the scaffold-side counterpart to dispatch_recording()'s
    outcome harvest -- used by non-check scaffolds like ensure_fresh_dq_results."""
    with registry.outcome_scope("my_scaffold", kind="scaffold"):
        registry.examined(3, unit="items")
    validation_result.record_scaffold_outcome("my_scaffold", 0, [])
    row = validation_result._OUTCOMES[-1]
    assert row.check == "my_scaffold"
    assert row.kind == "scaffold"
    assert row.status == "enforced"


def test_record_scaffold_outcome_is_failed_when_failed_grew() -> None:
    with registry.outcome_scope("failing_scaffold", kind="scaffold"):
        registry.examined(1)
    failed = ["already there", "new problem"]
    validation_result.record_scaffold_outcome("failing_scaffold", before=1, failed=failed)
    row = validation_result._OUTCOMES[-1]
    assert row.status == "failed"


def test_dispatch_recording_attributes_nothing_on_a_passing_check() -> None:
    failed: list[str] = []
    validation_result.dispatch_recording("validate_ok", failed, lambda failed: None)
    assert failed == []
    assert validation_result._ATTRIBUTIONS == []


def test_dispatch_recording_does_not_attribute_pre_existing_entries() -> None:
    """Only labels newly appended by THIS check are attributed -- a pre-existing `failed` entry
    from an earlier check must not be re-attributed to the current one."""

    def _adds_one_more(failed: list[str]) -> None:
        failed.append("new problem")

    failed: list[str] = ["earlier problem"]
    validation_result.dispatch_recording("validate_second", failed, _adds_one_more)
    assert failed == ["earlier problem", "new problem"]
    assert validation_result._ATTRIBUTIONS == [{"check": "validate_second", "label": "new problem"}]


def test_dispatch_recording_calls_the_resolved_callable_at_call_time() -> None:
    """`fn` is whatever the CALLER resolved (scripts.checks.registry.resolve(name)) and is invoked
    directly -- late-bound by the caller, not by a namespace lookup inside this function."""
    calls: list[str] = []

    def _fn(failed: list[str]) -> None:
        calls.append("called")
        failed.append("patched")

    failed: list[str] = []
    validation_result.dispatch_recording("validate_x", failed, _fn)
    assert calls == ["called"]
    assert failed == ["patched"]
    assert validation_result._ATTRIBUTIONS == [{"check": "validate_x", "label": "patched"}]


def test_write_completed_is_bounded_atomic_and_secret_free(tmp_path: Path) -> None:
    path = tmp_path / "debug" / "result.json"
    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00", exit_code=1, failed_checks=["lint"], path=path
        )
    assert json.loads(path.read_text(encoding="utf-8")) == record
    assert record["git_head"] == "abc123"
    assert record["failed_checks"] == ["lint"]
    assert not list(path.parent.glob("*.tmp"))
    assert "secret" not in path.read_text(encoding="utf-8").lower()


def test_write_completed_emits_schema_v3_with_failed_check_attributions(tmp_path: Path) -> None:
    """failed_checks/failed_check_attributions keep their exact schema_version 2 shape
    byte-for-byte under the v3 bump (Decision 142 lineage -- scripts.ci_rca.taxonomy's Priority-0
    attribution path is a live consumer)."""
    path = tmp_path / "debug" / "result.json"
    validation_result._ATTRIBUTIONS.append({"check": "validate_test_coverage", "label": "Coverage below 100%"})
    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00",
            exit_code=1,
            failed_checks=["validate_test_coverage"],
            path=path,
        )
    assert record["schema_version"] == 3
    assert record["failed_check_attributions"] == [{"check": "validate_test_coverage", "label": "Coverage below 100%"}]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 3
    assert on_disk["failed_check_attributions"] == record["failed_check_attributions"]


def test_write_completed_attributions_is_a_snapshot_not_a_live_reference(tmp_path: Path) -> None:
    """write_completed must copy the accumulator -- a later clear() must not mutate the
    already-written record's in-memory dict."""
    path = tmp_path / "debug" / "result.json"
    validation_result._ATTRIBUTIONS.append({"check": "validate_x", "label": "problem"})
    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00", exit_code=1, failed_checks=["validate_x"], path=path
        )
    validation_result.clear(path)
    assert record["failed_check_attributions"] == [{"check": "validate_x", "label": "problem"}]


def test_write_completed_emits_check_outcomes_and_consistent_rollups(tmp_path: Path) -> None:
    path = tmp_path / "debug" / "result.json"
    validation_result.dispatch_recording("vacuous_check", [], lambda f: registry.examined(0))
    validation_result.dispatch_recording("enforced_check", [], lambda f: registry.examined(4))
    validation_result.dispatch_recording("skipped_check", [], lambda f: registry.skipped("no input"))
    validation_result.dispatch_recording("undeclared_check", [], lambda f: None)
    failed_list: list[str] = []
    validation_result.dispatch_recording("failing_check", failed_list, lambda f: f.append("bad"))

    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00", exit_code=1, failed_checks=failed_list, path=path
        )

    statuses = {row["check"]: row["status"] for row in record["check_outcomes"]}
    assert statuses == {
        "vacuous_check": "vacuous",
        "enforced_check": "enforced",
        "skipped_check": "skipped",
        "undeclared_check": "undeclared",
        "failing_check": "failed",
    }
    # Rollups agree with check_outcomes -- each non-"failed" status appears in exactly one bucket,
    # and the bucket totals sum to the non-failed row count.
    assert record["ran_checks"] == 1
    assert record["skipped_checks"] == 1
    assert record["vacuous_checks"] == 1
    assert record["undeclared_checks"] == 1
    non_failed_rows = sum(1 for status in statuses.values() if status != "failed")
    assert record["ran_checks"] + record["skipped_checks"] + record["vacuous_checks"] + record["undeclared_checks"] == (
        non_failed_rows
    )
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["check_outcomes"] == record["check_outcomes"]


def test_write_completed_check_outcomes_is_a_snapshot_not_a_live_reference(tmp_path: Path) -> None:
    """A later clear() must not mutate an already-written record's check_outcomes list."""
    path = tmp_path / "debug" / "result.json"
    validation_result.dispatch_recording("check_x", [], lambda f: registry.examined(1))
    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00", exit_code=0, failed_checks=[], path=path
        )
    validation_result.clear(path)
    assert record["check_outcomes"] == [
        {
            "check": "check_x",
            "kind": "check",
            "status": "enforced",
            "examined_count": 1,
            "examined_unit": "items",
            "skipped_reason": None,
        }
    ]


def test_visible_writer_warns_without_raising(capsys) -> None:
    with patch("scripts.checks.validation_result.write_completed", side_effect=OSError("disk full")):
        validation_result.write_completed_visible(started_at="now", exit_code=0, failed_checks=[])
    assert "WARNING: validation evidence could not be written: OSError" in capsys.readouterr().out
