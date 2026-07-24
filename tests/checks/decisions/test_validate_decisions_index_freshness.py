"""Tests for validate_decisions_index_freshness() -- the DCG-08 drift/absence gate.

Mirrors tests/checks/deps/test_validate_dependency_graph_freshness.py's patch-seam pattern,
but this check's absence behavior is the OPPOSITE of validate_dependency_graph_freshness: the
decisions index is a REQUIRED committed artifact (Step 6b fork 2), so a missing file FAILS
rather than no-ops.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.checks.decisions.validate_decisions_index_freshness import (
    validate_decisions_index_freshness,
)
from scripts.decisions_index import build_index


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
