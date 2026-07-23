"""Tests for validate_ops_portal_patch_targets() (rec-2637 caller-aware facade-patch guard)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ci_guards.validate_ops_portal_patch_targets import _find_violations as _ops_portal_patch_violations


class TestValidateOpsPortalPatchTargets:
    """Tests for validate_ops_portal_patch_targets() (rec-2637 caller-aware facade-patch guard).

    Exercises the pure _find_violations(paths) core directly on synthetic temp files: a
    stale facade patch on a moved caller (file_decision) is rejected, the corrected
    submodule patch passes, and a facade-resident caller (file_rec) patching the same
    symbol name at the facade namespace is NOT flagged (caller-aware, not symbol-only).
    """

    def _write(self, tmp_path: Path, name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_ops_portal_patch_targets_stale_facade_patch_is_flagged(self, tmp_path: Path) -> None:
        body = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            "    with patch('scripts.ops_data_portal._ducklake_write'):\n"
            "        file_decision({'title': 'd'}, _skip_sync=True)\n"
        )
        path = self._write(tmp_path, "test_a.py", body)
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _ops_portal_patch_violations([path])
        assert len(violations) == 1
        assert "file_decision" in violations[0]

    def test_ops_portal_patch_targets_corrected_submodule_patch_not_flagged(self, tmp_path: Path) -> None:
        body = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            "    with patch('scripts.ops_portal.decisions._ducklake_write'):\n"
            "        file_decision({'title': 'd'}, _skip_sync=True)\n"
        )
        path = self._write(tmp_path, "test_b.py", body)
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _ops_portal_patch_violations([path])
        assert violations == []

    def test_ops_portal_patch_targets_flags_stale_orphan_guard_patch(self, tmp_path: Path) -> None:
        """rec-2637 failure mode for the DCG-03 guard: a test exercising backfill_decisions_from_md
        that patches scripts.ops_data_portal._assert_no_orphaned_current_rows (the facade
        namespace) must be flagged -- the caller resolves that symbol at its own submodule scope
        (scripts.ops_portal.decisions), so the facade patch never intercepts the call."""
        body = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            "    with patch('scripts.ops_data_portal._assert_no_orphaned_current_rows'):\n"
            "        backfill_decisions_from_md()\n"
        )
        path = self._write(tmp_path, "test_d.py", body)
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _ops_portal_patch_violations([path])
        assert len(violations) == 1
        assert "backfill_decisions_from_md" in violations[0]
        assert "_assert_no_orphaned_current_rows" in violations[0]

    def test_ops_portal_patch_targets_facade_resident_caller_not_flagged(self, tmp_path: Path) -> None:
        """file_rec is facade-resident -- patching scripts.ops_data_portal for the same
        symbol name a moved caller also uses must NOT be flagged (caller-aware)."""
        body = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            "    with patch('scripts.ops_data_portal._ducklake_write'):\n"
            "        file_rec({'title': 'd'}, _skip_sync=True)\n"
        )
        path = self._write(tmp_path, "test_c.py", body)
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _ops_portal_patch_violations([path])
        assert violations == []

    def test_registered_in_both_tiers(self) -> None:
        """validate_ops_portal_patch_targets appears in both pre_sequence() and full_sequence()."""
        from scripts.checks import registry

        names = [s.name for s in registry.pre_sequence() + registry.full_sequence()]
        assert names.count("validate_ops_portal_patch_targets") >= 2
