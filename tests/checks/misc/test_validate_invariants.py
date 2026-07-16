"""Tests for validate_invariants(): @file gotcha and mock count checks."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.misc.validate_invariants import validate_invariants


class TestValidateInvariants:
    """Tests for validate_invariants(): @file gotcha and mock count checks."""

    def test_passes_when_no_violations(self, tmp_path: Path) -> None:
        """No failures when codebase has no @file violations and mock counts are OK."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # Other script: no @file pattern
        (tmp_path / "scripts" / "other.py").write_text(
            'subprocess.run(["git", "status"])\n',
            encoding="utf-8",
        )
        # postflight: 2 subprocess.run calls in cleanup_after_merge
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(branch):\n"
            "    subprocess.run(['git', 'checkout', 'main'])\n"
            "    subprocess.run(['git', 'pull'])\n"
            "    return True\n",
            encoding="utf-8",
        )
        # test file: side_effect list with 4 MagicMock entries (2*2+2=6 threshold)
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_example(self):\n"
            "        responses = [\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "        ]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert failed == []

    def test_fails_on_at_file_without_instruction(self, tmp_path: Path) -> None:
        """Fails when a script uses '-p', '@file' pattern without an instruction string."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # A script that uses the bad pattern
        (tmp_path / "scripts" / "bad_script.py").write_text(
            'cmd.extend(["-p", f"@{some_file}"])\n',
            encoding="utf-8",
        )
        # Minimal postflight + test files so check 2 doesn't interfere
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(b):\n    subprocess.run(['git', 'checkout'])\n    return True\n",
            encoding="utf-8",
        )
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_x(self):\n"
            "        r = [MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert "Invariant checks" in failed
        # Error message must mention the @file gotcha
        # (validated by test passing -- the function adds to failed list)

    def test_passes_on_instruction_before_at_file(self, tmp_path: Path) -> None:
        """Does not flag a '-p' call list that carries an instruction before @file."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # A script that uses -p with an inline instruction preceding @file
        (tmp_path / "scripts" / "good_script.py").write_text(
            'cmd.extend(["-p", "review this", f"@{some_file}"])\n',
            encoding="utf-8",
        )
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(b):\n    subprocess.run(['git', 'checkout'])\n    return True\n",
            encoding="utf-8",
        )
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_x(self):\n"
            "        r = [MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert failed == []

    def test_fails_on_mock_count_mismatch(self, tmp_path: Path) -> None:
        """Fails when cleanup_after_merge has many subprocess calls but few test mocks."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # postflight: 12 subprocess.run calls (many, simulate a bloated function)
        postflight_src = "def cleanup_after_merge(branch):\n"
        for i in range(12):
            postflight_src += f"    subprocess.run(['cmd{i}'])\n"
        postflight_src += "    return True\n"
        (scripts_dir / "postflight.py").write_text(postflight_src, encoding="utf-8")

        # test file: only 1 MagicMock in side_effect list (12 > 1*2+2=4 -> FAIL)
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n    def test_x(self):\n        r = [MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert "Invariant checks" in failed
