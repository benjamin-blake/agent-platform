"""Tests for validate_candidate_decision_ratification()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.roadmap.validate_candidate_decision_ratification import (
    _dec_number,
    validate_candidate_decision_ratification,
)


class TestCandidateDecisionRatification:
    """Tests for validate_candidate_decision_ratification() (Decision 105): R1/R2/R3."""

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup(self, tmp_path: Path, cd_yaml: str, decisions_md: str = "", archive_md: str | None = None) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + cd_yaml, encoding="utf-8")
        (docs_dir / "DECISIONS.md").write_text(decisions_md, encoding="utf-8")
        if archive_md is not None:
            (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_md, encoding="utf-8")

    def test_ratified_cd_resolves_via_header_passes(self, tmp_path: Path) -> None:
        """dec-078 resolves via the '## Decision 78:' header (int-derived, not string-padded)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.31\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-078\n    filed_via: ops_decisions:dec-078\n",
            decisions_md="## Decision 78: Adopt DuckLake (Decided)\n\nbody with stale Warehouse ID: dec-1085 text\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_cd_unknown_dec_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.99\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-999\n    filed_via: ops_decisions:dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_ratified_as_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    ratified_as: dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_dec_pointer_filed_via_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    filed_via: ops_decisions:dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_pending_literal_passes(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.6\n    title: t\n    state: pending\n"
            "    filed_via: pending_log_decision_lambda\n    realization_evidence: Realized.\n",
            decisions_md="",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_as_filed_via_mismatch_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.16\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-079\n    filed_via: ops_decisions:dec-080\n",
            decisions_md="## Decision 79: X (Decided)\n## Decision 80: Y (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_superseded_cd_exempt_from_r1(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.14\n    title: t\n    state: superseded\n    ratified_as: dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_malformed_dec_pointer_does_not_partially_resolve_rec_2467(self, tmp_path: Path) -> None:
        """rec-2467: a malformed pointer 'dec-0123abc' must fail loudly, not partially resolve to dec-123."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.99\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-0123abc\n    filed_via: ops_decisions:dec-0123abc\n",
            decisions_md="## Decision 123: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        assert _dec_number("dec-0123abc") is None

    def test_well_formed_dec_pointer_still_resolves_rec_2467(self) -> None:
        """The anchor must not regress a valid pointer like 'ops_decisions:dec-078'."""
        assert _dec_number("ops_decisions:dec-078") == 78

    def test_dec_resolves_via_archive_only(self, tmp_path: Path) -> None:
        """A dec-NNN whose header lives only in DECISIONS_ARCHIVE.md still resolves (union read)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.50\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-34\n    filed_via: ops_decisions:dec-34\n",
            decisions_md="## Decision 1: Something (Decided)\n",
            archive_md="## Decision 34: Unified Cross-Workflow Session Telemetry\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []
