"""Autouse recursion guard for the checker's own concern-split test package.

After PLAN-coverage-checker-self-enforcement, scripts/test_coverage_checker.py self-maps to
tests/test_coverage_checker/ -- the very directory these tests live in -- and main() /
check_per_file_coverage has no depth or pytest-context guard on its Popen(["pytest", ...]) call.
An unmocked --check-coverage test run from inside this package would therefore re-enter itself
without bound. This autouse fixture patches subprocess.Popen to raise by default so any test that
forgets to mock it fails fast and loud instead of forking. The one legitimate real-subprocess test
(test_dotted_cov_form_flags_undertested_module) patches ROOT to a tmp_path sandbox -- not a
recursion source -- and opts out via the `real_subprocess` marker (registered in pyproject.toml).
"""

import pytest

from tests.fixtures.coverage_checker_module import checker


def _raise_recursion_guard(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError(
        "subprocess.Popen was not mocked in a tests/test_coverage_checker/ test -- this package is "
        "the checker's own self-mapped test target, so an unmocked coverage subprocess call would "
        "recurse into itself. Mock test_coverage_checker.subprocess.Popen, or mark the test "
        "@pytest.mark.real_subprocess if it sandboxes ROOT to a tmp_path."
    )


@pytest.fixture(autouse=True)
def _guard_unmocked_subprocess(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("real_subprocess"):
        return
    monkeypatch.setattr(checker.subprocess, "Popen", _raise_recursion_guard)
