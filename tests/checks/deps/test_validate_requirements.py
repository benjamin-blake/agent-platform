"""Tests for validate_requirements() -- VTS-14 network-error demotion (audit validate-test-suite-4df4d48)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.deps.validate_requirements import validate_requirements


def _write_requirements(tmp_path: Path, packages: list[str]) -> None:
    (tmp_path / "requirements.txt").write_text("\n".join(packages) + "\n", encoding="utf-8")


class TestValidateRequirementsNetworkDemotion:
    """VTS-14: a network-classified pip-index error is a loud warning, never a failure; a
    genuinely not-found (typo'd) package still reds."""

    def test_network_error_leaves_failed_empty(self, tmp_path: Path, capsys) -> None:
        _write_requirements(tmp_path, ["requests"])
        mock_result = MagicMock(returncode=1, stderr="ERROR: Could not find a version... Connection timed out")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []
        captured = capsys.readouterr()
        assert "network" in captured.out.lower()
        assert "warning" in captured.out.lower()

    def test_timeout_and_unreachable_are_also_classified_as_network(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["pkg-a", "pkg-b"])

        def fake_run(cmd, **kwargs):
            pkg = cmd[-1]
            if pkg == "pkg-a":
                stderr = "ERROR: Read timeout occurred while contacting PyPI"
            else:
                stderr = "Temporary failure: host unreachable"
            return MagicMock(returncode=1, stderr=stderr)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=fake_run),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []

    def test_not_found_package_still_fails(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["totally-not-a-real-package-xyz"])
        mock_result = MagicMock(returncode=1, stderr="ERROR: No matching distribution found")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]

    def test_mixed_run_fails_only_on_not_found(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["requests", "totally-not-a-real-package-xyz"])

        def fake_run(cmd, **kwargs):
            pkg = cmd[-1]
            if pkg == "requests":
                return MagicMock(returncode=1, stderr="ERROR: network unreachable")
            return MagicMock(returncode=1, stderr="ERROR: No matching distribution found")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=fake_run),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]

    def test_all_packages_found_no_warnings_no_failures(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["requests"])
        mock_result = MagicMock(returncode=0, stderr="")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []

    def test_wired_in_full_tier(self) -> None:
        """validate_requirements is a registered check in the full-tier sequence (post-merge
        only -- it is not part of pre_sequence())."""
        from scripts.checks import registry  # noqa: PLC0415

        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_requirements" in full_names
