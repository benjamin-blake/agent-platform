"""Tests for validate_broker_env_reads() -- RESOLVE-BY-KEY-ONLY invariant (T2.14
exit criterion 3). Mirror of scripts/checks/product/trading/validate_broker_env_reads.py,
rec-2709 Wave 1."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.product.trading.validate_broker_env_reads import validate_broker_env_reads


class TestBrokerEnvReadGuard:
    """Tests for validate_broker_env_reads -- RESOLVE-BY-KEY-ONLY invariant (T2.14 exit criterion 3)."""

    def test_clean_tree_passes(self) -> None:
        """The live src/ + scripts/ tree contains no direct broker env reads."""
        failed: list[str] = []
        validate_broker_env_reads(failed)
        assert failed == [], f"Expected no failures against real tree, got: {failed}"

    def test_planted_environ_bracket_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.environ["ALPACA_API_KEY"] in a src file is flagged."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bad_adapter.py").write_text(
            'import os\nkey = os.environ["ALPACA_API_KEY"]\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_planted_getenv_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.getenv("ALPACA_SECRET") in a scripts file is flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'import os\nsecret = os.getenv("ALPACA_SECRET_KEY")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_planted_environ_get_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.environ.get("ALPACA_API_KEY") in a scripts file is flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'import os\nkey = os.environ.get("ALPACA_API_KEY", "")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_broker_secrets_py_is_self_excluded(self, tmp_path: Path) -> None:
        """scripts/broker_secrets.py is excluded even if it contains the pattern string."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "broker_secrets.py").write_text(
            '# patterns: os.environ["ALPACA_API_KEY"] os.getenv("ALPACA_SECRET")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"broker_secrets.py must be self-excluded, got: {failed}"

    def test_validate_py_is_self_excluded(self, tmp_path: Path) -> None:
        """scripts/validate.py is excluded even though it contains the pattern strings."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "validate.py").write_text(
            "patterns = [r'os\\.environ\\[\\s*[\"\\']ALPACA_']\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"validate.py must be self-excluded, got: {failed}"

    def test_tests_dir_is_not_scanned(self, tmp_path: Path) -> None:
        """Files under tests/ are not scanned (test fixtures may plant violations intentionally)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_adapter.py").write_text(
            'key = os.environ["ALPACA_API_KEY"]  # planted fixture\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"tests/ must not be scanned, got: {failed}"
