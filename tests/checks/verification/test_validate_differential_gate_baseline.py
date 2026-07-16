"""Tests for validate_differential_gate_baseline(). Mirror of
scripts/checks/verification/validate_differential_gate_baseline.py -- merges
TestDifferentialGateStep and the module-level
test_differential_gate_step_passes_on_live_tree (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.verification.validate_differential_gate_baseline import validate_differential_gate_baseline


class TestDifferentialGateStep:
    """Tests for validate_differential_gate_baseline() in validate.py full tier."""

    def test_passes_when_kernel_file_contains_sentinel(self) -> None:
        """Gate passes when scripts/verification_checks.py exists and has SLOT_COUNT: int = 6."""
        failed: list[str] = []
        validate_differential_gate_baseline(failed)
        assert not failed, f"Differential gate baseline failed: {failed}"

    def test_fails_when_sentinel_absent(self, tmp_path: Path) -> None:
        """Gate fails if the kernel file lacks the expected sentinel line."""
        kernel_dir = tmp_path / "scripts"
        kernel_dir.mkdir()
        (kernel_dir / "verification_checks.py").write_text("# no sentinel here\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_differential_gate_baseline(failed)
        assert any("Differential gate baseline" in f for f in failed)


def test_differential_gate_step_passes_on_live_tree() -> None:
    """VP step 9: differential gate baseline step passes on the live code tree."""
    failed: list = []
    validate_differential_gate_baseline(failed)
    assert not failed
