"""Tests for validate_pr_conflict_signal() -- pr-conflict-signal.yml structural guard."""

import copy
from unittest.mock import patch

from scripts.checks.ci_guards.validate_pr_conflict_signal import validate_pr_conflict_signal

_VALID_WORKFLOW = {
    "on": {"push": {"branches": ["main"]}, "workflow_dispatch": {}},
    "jobs": {
        "detect-conflicts": {
            "permissions": {"contents": "read", "pull-requests": "write"},
            "steps": [
                {
                    "continue-on-error": True,
                    "run": ("gh pr list --base main claude/ ... mergeable ... UNKNOWN ... CONFLICTING ... conflict-wake: ..."),
                }
            ],
        }
    },
}

_MODULE = "scripts.checks.ci_guards.validate_pr_conflict_signal"


class TestValidatePrConflictSignalPassPath:
    """Pass-path: the real workflow file, and a valid mocked _load, both leave failed empty."""

    def test_passes_against_real_workflow_file(self) -> None:
        failed: list[str] = []
        validate_pr_conflict_signal(failed)
        assert failed == []

    def test_passes_with_well_formed_mocked_data(self) -> None:
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert failed == []


class TestValidatePrConflictSignalFailPath:
    """Fail-path: mocked data missing each asserted property appends a distinct failure."""

    def test_load_failure_records_failure_no_propagation(self) -> None:
        with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert len(failed) == 1
        assert "unreadable" in failed[0]

    def test_wrong_push_branches_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["push"]["branches"] = ["main", "develop"]
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("push trigger" in f for f in failed)

    def test_missing_workflow_dispatch_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        del data["on"]["workflow_dispatch"]
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("workflow_dispatch" in f for f in failed)

    def test_no_jobs_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"] = {}
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("no jobs defined" in f for f in failed)

    def test_missing_pull_requests_write_permission_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["permissions"] = {"contents": "read"}
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("pull-requests: write" in f for f in failed)

    def test_missing_claude_filter_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["run"] = (
            "gh pr list --base main ... mergeable ... UNKNOWN ... CONFLICTING ... conflict-wake: ..."
        )
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("claude/* head filter" in f for f in failed)

    def test_missing_mergeable_poll_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["run"] = (
            "gh pr list claude/ ... UNKNOWN ... CONFLICTING ... conflict-wake: ..."
        )
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("mergeable poll" in f for f in failed)

    def test_missing_unknown_skip_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["run"] = (
            "gh pr list claude/ ... mergeable ... CONFLICTING ... conflict-wake: ..."
        )
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("UNKNOWN-skip handling" in f for f in failed)

    def test_missing_conflicting_gate_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["run"] = (
            "gh pr list claude/ ... mergeable ... UNKNOWN ... conflict-wake: ..."
        )
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("CONFLICTING-only comment gate" in f for f in failed)

    def test_missing_dedup_marker_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["run"] = (
            "gh pr list claude/ ... mergeable ... UNKNOWN ... CONFLICTING ..."
        )
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("head-SHA dedup marker" in f for f in failed)

    def test_missing_continue_on_error_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["detect-conflicts"]["steps"][0]["continue-on-error"] = False
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_pr_conflict_signal(failed)
        assert any("continue-on-error" in f for f in failed)
