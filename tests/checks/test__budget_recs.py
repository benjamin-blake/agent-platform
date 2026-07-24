"""Tests for scripts/checks/_budget_recs.py -- budget-breach/bypass rec filing (Decision 128).

TestBudgetBreachRecFiling and TestBudgetRecFilingCiGuard are relocated VERBATIM (method bodies
and names unchanged) from tests/validate/test_budget_rec_filing.py, which is deleted as part of
this move -- _file_budget_breach_rec / _file_budget_bypass_rec now live in
scripts/checks/_budget_recs.py, not scripts/checks/_scaffolding.py (Decision 128
decompose-don't-raise). TestFindOpenBudgetBreachRec and TestBudgetBreachRecDedupe are new
(VTS-20, audit validate-test-suite-4df4d48).
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks._budget_recs import (
    _file_budget_breach_rec,
    _file_budget_bypass_rec,
    _find_open_budget_breach_rec,
)


class TestBudgetBreachRecFiling:
    """Tests for _file_budget_breach_rec and _file_budget_bypass_rec helpers.

    These exercise the LOCAL (non-CI) path -- CI-guard behaviour is covered separately by
    TestBudgetRecFilingCiGuard below. Every test here runs with CI unset regardless of the
    ambient environment (this file itself runs under CI="true" in the pr-validate/main-validate
    CI jobs), so the local-path assertions stay deterministic.
    """

    @pytest.fixture(autouse=True)
    def _no_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)

    def test_breach_rec_calls_file_rec_with_budget_breach_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_breach"

    def test_breach_rec_context_contains_elapsed_and_manifest(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "scripts/validate.py" in fields["context"]
        assert "6.7 min" in fields["context"] or "6." in fields["context"]

    def test_breach_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_breach_rec(400.0, [], None)

    def test_bypass_rec_calls_file_rec_with_budget_bypass_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_bypass"
        assert "disk issue" in fields["context"]

    def test_bypass_rec_reason_null_when_omitted(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, [], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "none provided" in fields["context"].lower()

    def test_bypass_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_bypass_rec(60.0, [], None)

    def test_breach_priority_is_accepted_value(self) -> None:
        """_file_budget_breach_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_bypass_priority_is_accepted_value(self) -> None:
        """_file_budget_bypass_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_breach_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_breach_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise

    def test_bypass_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_bypass_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise


class TestBudgetRecFilingCiGuard:
    """CI-guard on the budget rec-filing helpers (Decision 84 I-4 / ULID anomaly root cause).

    The pr-validate CI job installs requirements-fast.txt (no python-ulid) and configures no AWS
    credentials, so a real portal file_rec() write there raises a swallowed ModuleNotFoundError
    from ducklake_runtime's mint_write_identity. With CI=="true" neither helper may even attempt
    the portal import -- it must print a loud diagnostic instead (never a silent skip, never a
    buffered outbox entry).
    """

    def test_breach_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_breach_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err
        assert "400.0" not in captured.err  # sanity: elapsed is rendered as minutes, not raw seconds
        assert "6.7" in captured.err or "6." in captured.err

    def test_breach_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()

    def test_bypass_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_bypass_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        captured = capsys.readouterr()
        assert "disk issue" in captured.err

    def test_bypass_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()


class TestFindOpenBudgetBreachRec:
    """Pure matching-logic tests for _find_open_budget_breach_rec (VTS-20)."""

    def test_matches_on_branch_and_phase_substrings(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "budget_breach",
                "status": "open",
                "context": "Fast-tier budget breach: 8.0 min elapsed. Branch: agent/foo. Dominant phase: lint. ",
            }
        ]
        result = _find_open_budget_breach_rec(rows, "agent/foo", "lint")
        assert result is not None
        assert result["id"] == "rec-1"

    def test_no_match_on_different_source(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "budget_bypass",
                "status": "open",
                "context": "Branch: agent/foo. Dominant phase: lint. ",
            }
        ]
        assert _find_open_budget_breach_rec(rows, "agent/foo", "lint") is None

    def test_no_match_on_closed_status(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "budget_breach",
                "status": "closed",
                "context": "Branch: agent/foo. Dominant phase: lint. ",
            }
        ]
        assert _find_open_budget_breach_rec(rows, "agent/foo", "lint") is None

    def test_no_match_on_different_phase(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "budget_breach",
                "status": "open",
                "context": "Branch: agent/foo. Dominant phase: pytest_diff. ",
            }
        ]
        assert _find_open_budget_breach_rec(rows, "agent/foo", "lint") is None

    def test_no_match_on_different_branch(self) -> None:
        rows = [
            {
                "id": "rec-1",
                "source": "budget_breach",
                "status": "open",
                "context": "Branch: agent/bar. Dominant phase: lint. ",
            }
        ]
        assert _find_open_budget_breach_rec(rows, "agent/foo", "lint") is None

    def test_empty_rows_returns_none(self) -> None:
        assert _find_open_budget_breach_rec([], "agent/foo", "lint") is None


class TestBudgetBreachRecDedupe:
    """VTS-20 (audit validate-test-suite-4df4d48): a repeated fast-tier budget breach on the
    same (branch, dominant_phase) updates the existing open budget_breach rec instead of filing
    a duplicate. The dedupe lookup reads the open_recs reader boundary
    (src.common.iceberg_reader.make_reader via _fetch_open_recs), never
    logs/.recommendations-log.jsonl."""

    @pytest.fixture(autouse=True)
    def _no_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)

    def test_repeat_breach_same_branch_and_phase_updates_existing_rec(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")
        existing_rec = {
            "id": "rec-9001",
            "source": "budget_breach",
            "status": "open",
            "context": (
                "Fast-tier budget breach: 8.0 min elapsed (limit 5 min). Branch: agent/test. "
                "Dominant phase: pytest_diff. Diff manifest (1 files): scripts/validate.py. "
            ),
        }

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
            patch("scripts.checks._budget_recs._fetch_open_recs", return_value=[existing_rec]),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_not_called()
        mock_portal.update_rec.assert_called_once()
        call_args = mock_portal.update_rec.call_args[0]
        assert call_args[0] == "rec-9001"
        assert "pytest_diff" in call_args[1]["context"]

    def test_new_branch_or_phase_files_new_rec(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/other\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
            patch("scripts.checks._budget_recs._fetch_open_recs", return_value=[]),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()
        mock_portal.update_rec.assert_not_called()

    def test_non_matching_existing_rec_files_new_rec_not_update(self) -> None:
        """A DIFFERENT branch/phase's open budget_breach rec must not be mistaken for a match."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")
        other_rec = {
            "id": "rec-1234",
            "source": "budget_breach",
            "status": "open",
            "context": (
                "Fast-tier budget breach: 6.0 min elapsed (limit 5 min). Branch: some/other-branch. Dominant phase: lint. "
            ),
        }

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
            patch("scripts.checks._budget_recs._fetch_open_recs", return_value=[other_rec]),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()
        mock_portal.update_rec.assert_not_called()

    def test_reader_unreachable_degrades_to_file_rec(self) -> None:
        """A reader exception during the dedupe lookup must not crash -- it falls through to
        filing a new rec (the breach is still recorded, Decision 55)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
            patch(
                "scripts.checks._budget_recs._fetch_open_recs",
                side_effect=RuntimeError("reader unreachable"),
            ),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()
        mock_portal.update_rec.assert_not_called()

    def test_ci_guard_touches_neither_reader_nor_portal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
            patch("scripts.checks._budget_recs._fetch_open_recs") as mock_fetch,
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_not_called()
        mock_portal.update_rec.assert_not_called()
        mock_run.assert_not_called()
        mock_fetch.assert_not_called()

    def test_dedupe_never_reads_local_recommendations_cache(self) -> None:
        """The dedupe lookup must read the reader boundary, never
        logs/.recommendations-log.jsonl (Decision 84 warehouse-SoT: a read cache is never a write
        source). Asserts neither of the two established local-cache-read mechanisms
        (RECOMMENDATIONS_FILE / read_jsonl) is imported into this module -- a structural
        dependency check, not a string-absence scan (the module's own docstring legitimately
        documents this invariant by naming the path in prose)."""
        from scripts.checks import _budget_recs

        assert not hasattr(_budget_recs, "RECOMMENDATIONS_FILE")
        assert not hasattr(_budget_recs, "read_jsonl")
