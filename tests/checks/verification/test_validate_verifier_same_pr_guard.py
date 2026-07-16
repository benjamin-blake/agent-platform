"""Tests for validate_verifier_same_pr_guard() (VF-06). Mirror of
scripts/checks/verification/validate_verifier_same_pr_guard.py -- merges
TestSamePrGuard, TestSamePrGuardHelpers, TestSamePrGuardDifferential, and the
module-level test_same_pr_guard_passes_on_no_verifier_in_diff (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import verification_graduation
from scripts.checks.verification.validate_verifier_same_pr_guard import validate_verifier_same_pr_guard


class TestSamePrGuard:
    """Tests for validate_verifier_same_pr_guard() in validate.py --pre tier."""

    def test_no_violations_when_no_verifier_in_diff(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_no_violation_when_verifier_newly_added(self, tmp_path: Path) -> None:
        """Exception (b): a brand-new verifier file is exempt from the guard.

        Its covers ('**') intersects the diff, so this also exercises the VF-06 c3
        differential dispatch path -- stubbed here to an admitted outcome since the
        differential mechanism itself (real worktree) is covered by
        TestSamePrGuardDifferential below.
        """
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "new_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['**']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/new_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/validate.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=rel + "\n"),
            ),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="stubbed for AST-level guard test"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation for newly-added verifier: {failed}"

    def test_no_violation_exception_c_no_covered_in_diff(self, tmp_path: Path) -> None:
        """Exception (c): verifier modified but no covered file in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/some_module.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/other.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation when no covered file in diff: {failed}"

    def test_violation_detected_when_verifier_and_covered_both_modified(self, tmp_path: Path) -> None:
        """Same-PR guard fires when an existing verifier AND a file it covers are both in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        target = "scripts/target.py"
        (tmp_path / "scripts" / "target.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "scripts" / "target.py").write_text("# target\n", encoding="utf-8")
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, target]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert "Verifier same-PR guard" in failed


class TestSamePrGuardHelpers:
    """Edge-case coverage for _extract_verifier_covers and the guard's structural branches."""

    def test_extract_verifier_covers_annotated_assignment(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    covers: list[str] = ['a.py', 'b.py']\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) == ["a.py", "b.py"]

    def test_extract_verifier_covers_returns_none_when_absent(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    pass\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) is None

    def test_verifiers_dir_missing_returns_early(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_syntax_error_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        rel = "scripts/verifiers/broken.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_no_classes_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "no_classes.py").write_text("x = 1\n", encoding="utf-8")
        rel = "scripts/verifiers/no_classes.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed


class TestSamePrGuardDifferential:
    """VP step 7: validate_verifier_same_pr_guard's exception-(b) differential branch (VF-06 c3).

    The differential mechanism itself is covered by tests/test_verification_graduation.py; here
    we drive the validate.py wiring with a stubbed scripts.verification_graduation.
    """

    def _setup_new_verifier(self, tmp_path: Path) -> str:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "new_verifier.py").write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n", encoding="utf-8"
        )
        target = tmp_path / "scripts" / "target.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# target\n", encoding="utf-8")
        return "scripts/verifiers/new_verifier.py"

    def test_exception_b_differential_admits(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="admitted"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_tautological_fails(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False,
                    skipped=False,
                    reason="not admitted -- verifier passes even with its covered change reverted",
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_exception_b_non_hermetic_advisory_skip_does_not_block(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False, skipped=True, reason="advisory SKIP -- NON_HERMETIC_BY_CONSTRUCTION new verifier"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_error_surfaces(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("error --" in f for f in failed), failed


def test_same_pr_guard_passes_on_no_verifier_in_diff() -> None:
    """VP step 6: same-PR guard passes when no verifier file is in the diff."""
    failed: list = []
    with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
        validate_verifier_same_pr_guard(failed)
    assert not failed
