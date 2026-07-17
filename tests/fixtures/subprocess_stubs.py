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
    """Shared subprocess mock that handles git branch + everything else.

    stderr is set to "" (not left as an auto-vivified MagicMock attribute) so callers that
    unconditionally build a combined stdout+stderr string (e.g.
    scripts.checks._scaffolding._attribute_batched_collect_errors, which must scan for a
    graceful SKIPPED line even on a returncode-0 batch) get a real string rather than a Mock.
    """
    result = MagicMock()
    result.returncode = 0
    result.stdout = "agent/test-branch\n"
    result.stderr = ""
    return result
