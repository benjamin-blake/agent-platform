"""Tests for validate_decisions_index_freshness() -- the DCG-08 drift/absence gate.

Mirrors tests/checks/deps/test_validate_dependency_graph_freshness.py's patch-seam pattern,
but this check's absence behavior is the OPPOSITE of validate_dependency_graph_freshness: the
decisions index is a REQUIRED committed artifact (Step 6b fork 2), so a missing file FAILS
rather than no-ops.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks.decisions.validate_decisions_index_freshness import (
    validate_decisions_index_freshness,
)
from scripts.decisions_index import build_index

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestDecisionsIndexFreshness:
    def test_fails_when_export_is_absent(self, tmp_path: Path) -> None:
        """Absence is itself a failure -- the opposite of the dependency-graph precedent."""
        missing = tmp_path / "nonexistent.json"
        with patch("scripts.decisions_index._EXPORT_PATH", missing):
            failed: list[str] = []
            validate_decisions_index_freshness(failed)
        assert len(failed) == 1
        msg = failed[0].lower()
        assert "missing" in msg or "regenerate" in msg

    def test_fails_when_export_is_a_hand_edit(self, tmp_path: Path) -> None:
        """A hand edit to the committed index (drift from the live corpus) fails."""
        export_path = tmp_path / "decisions-index.json"
        tampered_entry = {
            "number": 1,
            "title": "Tampered",
            "status": "Decided",
            "decided_date": "",
            "supersedes": [],
            "superseded_by": None,
            "amends": [],
        }
        tampered = {
            "decisions": [tampered_entry],
            "metadata": {"generated_by": "scripts.decisions_index"},
        }
        export_path.write_text(json.dumps(tampered), encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            validate_decisions_index_freshness(failed)
        assert len(failed) == 1
        msg = failed[0].lower()
        assert "stale" in msg or "drift" in msg or "decisions index" in msg

    def test_passes_when_export_matches_a_freshly_regenerated_tree(self, tmp_path: Path) -> None:
        """A freshly written, correctly-regenerated index passes cleanly."""
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text(json.dumps(build_index(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            validate_decisions_index_freshness(failed)
        assert not failed

    def test_fails_when_export_is_unreadable_json(self, tmp_path: Path) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text("not valid json {{{", encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            validate_decisions_index_freshness(failed)
        assert len(failed) == 1


class TestIndexMaxBytesContractPin:
    """VP step 3 / rec-3012 (migration step 5): docs/contracts/decision-entry.yaml's
    size_governance.index_max_bytes must never drift from the enforcing test constant. Homed
    here (covers the contract, not scripts/decisions_index.py) rather than in
    tests/test_decisions_index.py. Reads the constant by regexing tests/test_decisions_index.py's
    TEXT, never by importing it -- a tests/**/*.py import would trip Decision 131's
    cross-test-import guard (scripts/checks/hygiene/validate_no_cross_test_imports.py)."""

    def test_index_max_bytes_matches_the_enforcing_test_constant(self) -> None:
        contract = yaml.safe_load((_REPO_ROOT / "docs/contracts/decision-entry.yaml").read_text(encoding="utf-8"))
        source = (_REPO_ROOT / "tests/test_decisions_index.py").read_text(encoding="utf-8")
        match = re.search(r"_COMMITTED_INDEX_MAX_BYTES = (\S+)", source)
        assert match is not None, "_COMMITTED_INDEX_MAX_BYTES assignment not found"
        pin = int(match.group(1).replace("_", ""))
        assert contract["size_governance"]["index_max_bytes"] == pin, (contract["size_governance"]["index_max_bytes"], pin)

    def test_lever_by_ceiling_matrix_carries_the_index_max_bytes_row(self) -> None:
        contract = yaml.safe_load((_REPO_ROOT / "docs/contracts/decision-entry.yaml").read_text(encoding="utf-8"))
        matrix = contract["size_governance"]["lever_by_ceiling_matrix"]
        assert "index_max_bytes" in matrix, sorted(matrix)
