"""Shared subprocess-mock helpers for the rec-2709 tests/test_validate.py decomposition.

tests/fixtures/ is an importable package exempt from the cross-test-import guard (its names
never start with test_), so both tests/checks/** and tests/validate/ consumers import from
here rather than from each other.
"""

from unittest.mock import MagicMock


def _mock_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a MagicMock that quacks like subprocess.CompletedProcess."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


def _pre_mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
    """Shared subprocess mock that handles git branch + everything else."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "agent/test-branch\n"
    return result
