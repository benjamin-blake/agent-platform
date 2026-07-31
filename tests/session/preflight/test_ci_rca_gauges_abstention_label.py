"""TestAbstentionLabelAccuracy, split out of test_ci_rca_gauges.py (PLAN-ci-rca-abstention-and-
citation): that file carries a module-level `pytest.importorskip("boto3")` guard for other,
unrelated tests -- pr-validate's fast tier installs only requirements-fast + requirements-dev, so
boto3 is absent there and the whole module (this class included) would be skipped, which the
interactive VP-replay gate (T3.15 c2) reads as a hard failure (exit 4, no collectors), not a
benign skip. `_preflight` itself imports cleanly without boto3 (verified directly); only that
file's blanket importorskip line pulled this class down with it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.fixtures.session_preflight_module import preflight as _preflight


class TestAbstentionLabelAccuracy:
    """PLAN-ci-rca-abstention-and-citation AC5: the gauge dict key and the printed label both
    name the widened {low, undetermined} set -- no surviving 'undetermined'-only label."""

    def test_compute_gauge_key_is_low_or_undetermined_count(self) -> None:
        with patch("scripts.ci_rca.probe_health.compute_abstention_rate", return_value=(3, 6, 0.5)):
            gauge = _preflight._compute_ci_rca_abstention([{"id": "rec-1"}], window_days=14)
        assert "low_or_undetermined_count" in gauge
        assert "undetermined_count" not in gauge

    def test_printed_label_names_widened_set(self, capsys: pytest.CaptureFixture) -> None:
        gauge = {"low_or_undetermined_count": 4, "total_count": 16, "rate": 0.25, "window_days": 14}
        _preflight.print_ci_rca_abstention_gauge(gauge)
        out = capsys.readouterr().out
        assert "low-confidence/undetermined" in out
        assert "4/16" in out
