"""Per-package conftest scaffold for tests/checks/ (Decision 131).

This is the FIRST sub-package conftest under tests/ -- an example of the pattern later
mirror-decomposition waves follow, not a relocation of any existing fixture.

pytest merges this conftest with the root tests/conftest.py for every test collected under
tests/checks/ (and its sub-packages, e.g. tests/checks/hygiene/): fixtures declared in either
file are visible to tests here. The GLOBAL guards stay solely in the root conftest and apply
here automatically without redeclaration:

- Recursion guards: _VALIDATE_DEPTH / _COVERAGE_SUBPROCESS env vars (set in the root conftest;
  the PYTEST_CURRENT_TEST early-exit lives in scripts/validate.py main(), per Decision 130
  point 4).
- Socket guards: --disable-socket in pyproject.toml addopts, lifted selectively by the root
  conftest's _allow_network_for_integration autouse fixture for @pytest.mark.integration tests.

This file intentionally declares NO fixtures. Per-wave decompositions migrate each package's
own autouse fixtures (currently several executor/src-specific autouse fixtures still living in
the root conftest) down into the matching sub-conftest as that package's tests move -- not in
this foundation, which moves zero test files (AGENTS.md SLOC governance / rec-2709 Wave 0).
"""
