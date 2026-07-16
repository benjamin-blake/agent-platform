"""Tests for the scripts/ops_portal/risk_scoring.py surface: compute_risk() (radon complexity
+ coverage.xml line-rate -> low/medium/high risk tier).

Split out of the former tests/test_ops_data_portal.py monolith (rec-2709 Wave 3).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")


class TestComputeRisk:
    """Tests for compute_risk()."""

    def _radon_mock(self, stdout: str, returncode: int = 0):
        """Return a mock subprocess.CompletedProcess with given stdout."""
        from unittest.mock import MagicMock

        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        return m

    def test_low_tier_returned_for_small_r(self) -> None:
        """R = (1 * 0.1) / 0.1 = 1.0 -> 'low' (C=1 from radon, S=XS, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (1)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "XS") == "low"

    def test_medium_tier_returned_for_mid_r(self) -> None:
        """R = (2 * 0.5) / 0.1 = 10 -> 'medium' (C=2, effort=S, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (2)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "S") == "medium"

    def test_high_tier_returned_for_large_r(self) -> None:
        """R = (10 * 1.0) / 0.1 = 100 -> 'high' (C=10, effort=M, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - C (10)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "M") == "high"

    def test_fallback_c_on_radon_failure(self) -> None:
        """Radon subprocess exception -> C=1.0 fallback, formula still produces valid tier."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", side_effect=OSError("radon missing")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("missing.py", "XS")
        assert result in ("low", "medium", "high")

    def test_fallback_c_on_empty_radon_output(self) -> None:
        """Radon returns empty stdout -> C=1.0 fallback."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "XS")
        assert result in ("low", "medium", "high")

    def test_fallback_c_on_nonzero_radon_returncode(self) -> None:
        """Radon non-zero exit -> C=1.0 fallback (returncode check)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("error output", returncode=1)),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "M")
        assert result in ("low", "medium", "high")

    def test_coverage_xml_line_rate_applied(self, tmp_path: Path) -> None:
        """When coverage.xml has a matching class entry, M = line_rate + 0.1."""
        coverage_xml = tmp_path / "coverage.xml"
        coverage_xml.write_text(
            '<?xml version="1.0"?>'
            "<coverage><packages><package><classes>"
            '<class filename="scripts/ops_data_portal.py" line-rate="0.9"></class>'
            "</classes></package></packages></coverage>",
            encoding="utf-8",
        )
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (1)\n")),
            patch("scripts.ops_portal.risk_scoring._COVERAGE_XML", coverage_xml),
        ):
            from scripts.ops_data_portal import compute_risk

            # C=1, S=0.1 (XS), M=0.9+0.1=1.0 -> R=0.1 -> 'low'
            assert compute_risk("scripts/ops_data_portal.py", "XS") == "low"

    def test_unknown_effort_uses_fallback_scale(self) -> None:
        """Unknown effort label falls back to S=1.0."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "UNKNOWN")
        assert result in ("low", "medium", "high")

    def test_max_complexity_used_from_multiple_blocks(self) -> None:
        """Takes the maximum cyclomatic complexity across all blocks in the file."""
        radon_out = "file.py\n    F 1:0 a - A (2)\n    F 10:0 b - C (12)\n    F 20:0 c - A (1)\n"
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock(radon_out)),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            # C=12, S=0.1 (XS), M=0.1 -> R=(12*0.1)/0.1=12 -> medium
            assert compute_risk("file.py", "XS") == "medium"
