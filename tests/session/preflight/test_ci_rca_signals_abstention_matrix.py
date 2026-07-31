"""TestAbstentionSurfaceConfidenceMatrix, split out of test_ci_rca_signals.py (PLAN-ci-rca-
abstention-and-citation): that file carries a module-level `pytest.importorskip("boto3")` guard
for other, unrelated tests -- pr-validate's fast tier installs only requirements-fast +
requirements-dev, so boto3 is absent there and the whole module (this class included) would be
skipped, which the interactive VP-replay gate (T3.15 c2) reads as a hard failure (exit 4, no
collectors), not a benign skip. `_preflight` itself imports cleanly without boto3 (verified
directly); only that file's blanket importorskip line pulled this class down with it.
"""

from __future__ import annotations

import json

from tests.fixtures.session_preflight_module import preflight as _preflight


class TestAbstentionSurfaceConfidenceMatrix:
    """PLAN-ci-rca-abstention-and-citation AC3/VP2: the abstention-review surface admits
    rca_confidence in {low, undetermined}, not undetermined alone -- and still excludes high,
    medium and a rec with no rca_confidence at all."""

    def _make_row(self, rec_id: str, rca_confidence: str | None) -> dict:
        ctx: dict = {"schema_version": 2}
        if rca_confidence is not None:
            ctx["rca_confidence"] = rca_confidence
        return {
            "id": rec_id,
            "source": "ci_rca",
            "status": "open",
            "title": f"CI failure {rec_id}",
            "priority": "Critical",
            "created_timestamp": "2026-06-30T10:00:00Z",
            "context_v2_json": json.dumps(ctx),
        }

    def test_low_confidence_surfaces(self) -> None:
        rows = [self._make_row("rec-low", "low")]
        result = _preflight._derive_ci_rca_undetermined_open(rows)
        assert [r["id"] for r in result] == ["rec-low"]

    def test_undetermined_still_surfaces(self) -> None:
        rows = [self._make_row("rec-undetermined", "undetermined")]
        result = _preflight._derive_ci_rca_undetermined_open(rows)
        assert [r["id"] for r in result] == ["rec-undetermined"]

    def test_high_confidence_does_not_surface(self) -> None:
        rows = [self._make_row("rec-high", "high")]
        assert _preflight._derive_ci_rca_undetermined_open(rows) == []

    def test_medium_confidence_does_not_surface(self) -> None:
        rows = [self._make_row("rec-medium", "medium")]
        assert _preflight._derive_ci_rca_undetermined_open(rows) == []

    def test_absent_confidence_does_not_surface(self) -> None:
        rows = [self._make_row("rec-absent", None)]
        assert _preflight._derive_ci_rca_undetermined_open(rows) == []

    def test_mixed_confidence_matrix(self) -> None:
        rows = [
            self._make_row("rec-low", "low"),
            self._make_row("rec-undetermined", "undetermined"),
            self._make_row("rec-high", "high"),
            self._make_row("rec-medium", "medium"),
            self._make_row("rec-absent", None),
        ]
        result = _preflight._derive_ci_rca_undetermined_open(rows)
        assert {r["id"] for r in result} == {"rec-low", "rec-undetermined"}

    def test_section_title_and_decision_substring_retained(self, capsys) -> None:
        recs = [self._make_row("rec-low", "low")]
        _preflight.print_ci_rca_undetermined_recs(recs)
        out = capsys.readouterr().out
        assert "CI-RCA Abstention Review" in out
        assert "Decision 73 L5" in out

    def test_overflow_label_matches_widened_wording(self, capsys) -> None:
        recs = [self._make_row(f"rec-{i}", "low") for i in range(7)]
        _preflight.print_ci_rca_undetermined_recs(recs)
        out = capsys.readouterr().out
        assert "showing 5 of 7" in out
        assert "low-confidence/undetermined" in out
