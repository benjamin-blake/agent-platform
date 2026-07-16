"""Tests for validate_verifier_hermeticity() (T3.6 AST gate)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.verification.validate_verifier_hermeticity import validate_verifier_hermeticity


class TestVerifierHermeticity:
    """Tests for validate_verifier_hermeticity() (T3.6 AST gate)."""

    def test_real_tree_is_clean(self) -> None:
        """The live scripts/verifiers/ tree produces no hermeticity violations."""
        failed: list[str] = []
        validate_verifier_hermeticity(failed)
        assert failed == [], f"Expected no failures against real verifier tree, got: {failed}"

    def test_hermetic_declared_with_time_time_fails(self, tmp_path: Path) -> None:
        """A HERMETIC-defaulting class using time.time() is rejected."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "clock_verifier.py").write_text(
            "import time\n\nclass ClockVerifier:\n    async def verify(self):\n        return time.time()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("time.time" in f for f in failed), f"Expected time.time violation, got: {failed}"

    def test_hermetic_declared_with_boto3_import_fails(self, tmp_path: Path) -> None:
        """A HERMETIC-defaulting file importing boto3 is rejected."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "network_verifier.py").write_text(
            "import boto3\n\nclass NetworkVerifier:\n    async def verify(self):\n        pass\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("boto3" in f for f in failed), f"Expected boto3 violation, got: {failed}"

    def test_non_hermetic_declared_with_time_time_is_exempt(self, tmp_path: Path) -> None:
        """A NON_HERMETIC_BY_CONSTRUCTION verifier using time.time() is exempt."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "exempt_verifier.py").write_text(
            "import time\n\n"
            "class ExemptVerifier:\n"
            "    hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION\n"
            "    async def verify(self):\n"
            "        return time.time()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert failed == [], f"Expected no failures for NON_HERMETIC verifier, got: {failed}"

    def test_three_level_datetime_now_fails(self, tmp_path: Path) -> None:
        """import datetime; datetime.datetime.now() is caught (3-level dotted name)."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "three_level_verifier.py").write_text(
            "import datetime\n\n"
            "class ThreeLevelVerifier:\n"
            "    async def verify(self):\n"
            "        return datetime.datetime.now()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("datetime.datetime.now" in f for f in failed), f"Expected datetime.datetime.now violation, got: {failed}"

    def test_syntax_error_file_is_skipped(self, tmp_path: Path) -> None:
        """A file with a SyntaxError is skipped without crashing the gate."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "bad_syntax.py").write_text(
            "def broken(\n    # unclosed paren\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert failed == [], f"SyntaxError file must be skipped, got: {failed}"
