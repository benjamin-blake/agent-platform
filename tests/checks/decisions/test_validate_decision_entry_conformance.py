"""Tests for validate_decision_entry_conformance(). Mirror of
scripts/checks/decisions/validate_decision_entry_conformance.py (DAF-03 / Decision 134 cl.3 /
PLAN-daf-authoring-grammar).

Exercises the root/baseline_reader injection seams (mirrors the vp_replay /
graduation_completeness precedents) rather than real git plumbing for the deterministic cases;
one test uses a real throwaway directory with no git repo at all to prove the default reader's
own SKIP-on-unreachable path end-to-end (mirrors
tests/checks/verification/test_validate_graduation_completeness.py's
test_origin_main_unreachable_advisory_skips).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.decisions.validate_decision_entry_conformance import (
    validate_decision_entry_conformance,
)

_CONTRACT_YAML = "required_markers:\n  - Status\n  - Date\n  - Decision\n"


def _write_contract(root: Path, contract_text: str = _CONTRACT_YAML) -> None:
    contracts_dir = root / "docs" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "decision-entry.yaml").write_text(contract_text, encoding="utf-8")


def _write_decisions_md(root: Path, content: str, archive_content: str = "") -> None:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "DECISIONS.md").write_text(content, encoding="utf-8")
    (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_content, encoding="utf-8")


class TestSkipOnUnreachableBaseline:
    def test_injected_none_baseline_skips(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        _write_decisions_md(tmp_path, "## Decision 1: New entry (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: None)
        assert failed == []

    def test_default_reader_skips_with_no_git_repo_at_all(self, tmp_path: Path) -> None:
        """No .git directory anywhere under tmp_path -- origin/main is genuinely unreachable,
        exercising the DEFAULT baseline_reader (not an injected seam)."""
        _write_contract(tmp_path)
        _write_decisions_md(tmp_path, "## Decision 1: New entry (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path)
        assert failed == []


class TestNewEntryConformance:
    def test_canonical_new_entry_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        _write_decisions_md(
            tmp_path,
            "## Decision 5: A well-formed new entry (Decided)\n\n"
            "**Status:** Decided\n\n**Date:** 2026-07-16\n\n**Decision:** Do the thing.\n",
        )
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert failed == []

    def test_non_canonical_new_entry_fails(self, tmp_path: Path) -> None:
        """A new entry missing the required Date marker fails -- named in the failure message."""
        _write_contract(tmp_path)
        _write_decisions_md(
            tmp_path,
            "## Decision 5: A malformed new entry (Decided)\n\n**Status:** Decided\n\n**Decision:** Do the thing.\n",
        )
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert failed == ["Decision-entry conformance"]

    def test_decorated_decision_marker_is_tolerated_on_new_entry(self, tmp_path: Path) -> None:
        """A decorated '**Decision (...):**' marker still satisfies the required 'Decision'
        marker (decision_marker_tolerance in decision-entry.yaml)."""
        _write_contract(tmp_path)
        _write_decisions_md(
            tmp_path,
            "## Decision 5: Decorated marker entry (Decided)\n\n"
            "**Status:** Decided\n\n**Date:** 2026-07-16\n\n**Decision (four invariants):** Do the thing.\n",
        )
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert failed == []

    def test_no_new_entries_passes_trivially(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        _write_decisions_md(tmp_path, "## Decision 1: Already known (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: {1})
        assert failed == []


class TestHistoricalEntryGrandfathered:
    def test_modified_historical_entry_is_not_flagged(self, tmp_path: Path) -> None:
        """A decision number already present in the baseline is grandfathered even when its
        current-tree body is missing required markers (the DPI-07 promote scenario: Decisions
        52/53/54 carry no separate **Date:** marker and must not self-fail)."""
        _write_contract(tmp_path)
        _write_decisions_md(
            tmp_path,
            "## Decision 1: Historical, now missing Date (Decided)\n\n"
            "**Status:** Decided -- April 2026\n\n**Decision:** Historical body.\n",
        )
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: {1})
        assert failed == []

    def test_archive_h3_to_h2_promote_does_not_manufacture_a_new_entry(self, tmp_path: Path) -> None:
        """Baseline computed over h3-shaped text (pre-promote); current tree has the same
        number promoted to h2 (post-promote) and missing the Date marker -- must not be
        flagged as new, proving the shared '#{2,3}' grammar covers both heading levels."""
        _write_contract(tmp_path)
        # baseline_reader simulates decisions_md.iter_decision_headings() over the origin/main
        # (pre-promote, h3) blob -- decision 52 is visible there too, via the same #{2,3} grammar.
        _write_decisions_md(
            tmp_path,
            "",
            archive_content="## Decision 52: Promoted entry (Decided)\n\n**Status:** Decided -- April 2026\n",
        )
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: {52})
        assert failed == []


class TestMissingContract:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        _write_decisions_md(tmp_path, "## Decision 1: X (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert len(failed) == 1
        assert "decision-entry.yaml" in failed[0]

    def test_contract_missing_required_markers_key_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, contract_text="header_form: something\n")
        _write_decisions_md(tmp_path, "## Decision 1: X (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_decision_entry_conformance(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert len(failed) == 1
        assert "required_markers" in failed[0]


class TestRealContractIntegration:
    """Sanity check against the REAL docs/contracts/decision-entry.yaml required_markers list,
    proving the check reads the actual contract shape rather than a test-local assumption."""

    def test_real_contract_required_markers_are_status_date_decision(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        contract_path = repo_root / "docs" / "contracts" / "decision-entry.yaml"
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        assert data["required_markers"] == ["Status", "Date", "Decision"]
