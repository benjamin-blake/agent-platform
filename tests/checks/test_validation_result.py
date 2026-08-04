from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import validation_result


@pytest.fixture(autouse=True)
def _reset_attributions():
    validation_result._ATTRIBUTIONS.clear()
    yield
    validation_result._ATTRIBUTIONS.clear()


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

    namespace = {"validate_two_things": _two_failures}
    failed: list[str] = []
    validation_result.dispatch_recording("validate_two_things", failed, namespace)
    assert failed == ["first problem", "second problem"]
    assert validation_result._ATTRIBUTIONS == [
        {"check": "validate_two_things", "label": "first problem"},
        {"check": "validate_two_things", "label": "second problem"},
    ]


def test_dispatch_recording_attributes_nothing_on_a_passing_check() -> None:
    namespace = {"validate_ok": lambda failed: None}
    failed: list[str] = []
    validation_result.dispatch_recording("validate_ok", failed, namespace)
    assert failed == []
    assert validation_result._ATTRIBUTIONS == []


def test_dispatch_recording_does_not_attribute_pre_existing_entries() -> None:
    """Only labels newly appended by THIS check are attributed -- a pre-existing `failed` entry
    from an earlier check must not be re-attributed to the current one."""

    def _adds_one_more(failed: list[str]) -> None:
        failed.append("new problem")

    namespace = {"validate_second": _adds_one_more}
    failed: list[str] = ["earlier problem"]
    validation_result.dispatch_recording("validate_second", failed, namespace)
    assert failed == ["earlier problem", "new problem"]
    assert validation_result._ATTRIBUTIONS == [{"check": "validate_second", "label": "new problem"}]


def test_dispatch_recording_intercepts_via_namespace_patch() -> None:
    """The namespace dict is consulted at call time (not a captured reference), matching
    validate.py's `patch("validate.<name>")` interception contract."""
    namespace = {"validate_x": lambda failed: failed.append("original")}
    namespace["validate_x"] = lambda failed: failed.append("patched")
    failed: list[str] = []
    validation_result.dispatch_recording("validate_x", failed, namespace)
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


def test_write_completed_emits_schema_v2_with_failed_check_attributions(tmp_path: Path) -> None:
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
    assert record["schema_version"] == 2
    assert record["failed_check_attributions"] == [{"check": "validate_test_coverage", "label": "Coverage below 100%"}]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 2
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


def test_visible_writer_warns_without_raising(capsys) -> None:
    with patch("scripts.checks.validation_result.write_completed", side_effect=OSError("disk full")):
        validation_result.write_completed_visible(started_at="now", exit_code=0, failed_checks=[])
    assert "WARNING: validation evidence could not be written: OSError" in capsys.readouterr().out
