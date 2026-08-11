"""Tests for validate_ci_rca_adjudication -- the bidirectional workflow-coverage,
filter/watched-equality, and entry-shape guard (PLAN-ci-rca-adjudication-guard).

Every negative case asserts a NON-EMPTY failed list -- a guard that cannot fail is the defect
this plan exists to prevent.
"""

from pathlib import Path

import pytest
import yaml

from scripts.checks.ci_guards.validate_ci_rca_adjudication import validate_ci_rca_adjudication

_VALID_ENTRY = {"tier": "not_a_gate", "ci_rca": "excluded", "owner": "platform", "rationale": "test fixture"}


def _write_ci_rca_yml(root: Path, workflows: list[str]) -> None:
    wf_dir = root / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "ci-rca.yml").write_text(
        yaml.dump({"name": "CI RCA", "on": {"workflow_run": {"workflows": workflows, "types": ["completed"]}}}),
        encoding="utf-8",
    )


def _patch_taxonomy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workflows_map: dict, names: list[str]) -> None:
    taxonomy = {
        "schema_version": 1,
        "taxonomy_version": 1,
        "function_to_category": {},
        "log_pattern_to_category": [],
        "workflows": workflows_map,
    }
    monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: taxonomy)
    monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: names)
    monkeypatch.setattr("scripts.ci_rca.taxonomy.ROOT", tmp_path)


class TestWorkflowCoverageBidirectional:
    def test_unregistered_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A real workflow file with no taxonomy entry must fail (direction 1)."""
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY)}, ["CI", "NewWorkflow"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'NewWorkflow'" in f and "absent from workflows" in f for f in failed), failed

    def test_stale_map_entry_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A taxonomy entry naming no real workflow file must fail (direction 2)."""
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY), "GhostWorkflow": dict(_VALID_ENTRY)}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'GhostWorkflow'" in f and "stale entry" in f for f in failed), failed


class TestFilterEqualsWatchedBidirectional:
    def test_watched_but_absent_from_filter_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])  # filter omits CI despite it being watched

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "absent from ci-rca.yml" in f for f in failed), failed

    def test_filter_has_unwatched_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY)}, ["CI"])
        _write_ci_rca_yml(tmp_path, ["CI"])  # CI is excluded in the taxonomy but present in the filter

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "is not ci_rca: watched" in f for f in failed), failed


class TestEntryShape:
    def test_missing_owner_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "owner": ""}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty owner" in f for f in failed), failed

    def test_invalid_owner_type_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "owner": None}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty owner" in f for f in failed), failed

    def test_missing_rationale_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "rationale": "   "}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty rationale" in f for f in failed), failed

    def test_invalid_ci_rca_value_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "ci_rca": "maybe"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "ci_rca='maybe'" in f for f in failed), failed

    def test_non_mapping_entry_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": "not-a-dict"}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "is not a mapping" in f for f in failed), failed


class TestHappyPath:
    def test_synthetic_consistent_state_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        excluded_entry = dict(_VALID_ENTRY)
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry, "Lint": excluded_entry}, ["CI", "Lint"])
        _write_ci_rca_yml(tmp_path, ["CI"])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, failed

    def test_real_repo_state_passes(self) -> None:
        """No monkeypatching -- runs against the actual repo state post-migration."""
        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, f"Expected no failures against real repo state, got: {failed}"


class TestErrorPaths:
    def test_taxonomy_load_error_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise():
            raise ValueError("boom")

        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", _raise)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("CI-RCA adjudication: boom" in f for f in failed), failed

    def test_malformed_ci_rca_yml_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / "ci-rca.yml").write_text("key: [unclosed", encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("could not read/parse" in f for f in failed), failed


class TestSharedAccumulatorIsolation:
    """Regression guard: `failed` is the SHARED cross-check accumulator scripts/validate.py
    dispatches every check into, not a private result list. A branch that reads `failed` itself
    (instead of a locally-scoped result) to decide whether to run a later assertion group would
    silently skip that group whenever an EARLIER, unrelated check in the same dispatch had already
    appended to it -- exactly the failure mode this test seeds and asserts against."""

    def test_filter_check_still_runs_with_preexisting_unrelated_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])  # filter omits CI despite it being watched

        failed: list[str] = ["some unrelated check already failed"]
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "absent from ci-rca.yml" in f for f in failed), failed
