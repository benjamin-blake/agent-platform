# Tests — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Test isolation (CRITICAL)
- Never spawn `pytest tests/` (full suite) from a script that any test imports. Recursion risk.
- Three-layer defence is already in place: `_VALIDATE_DEPTH` env var in `validate.py`, `_COVERAGE_SUBPROCESS` env var, and `tests/conftest.py` sets both. Don't remove any layer without understanding the full chain.
- Tests that mock subprocess-spawning functions must mock **both** `subprocess.Popen` AND `subprocess.run`. Mocking only one is a common silent failure.
- Tests that assume files don't exist must mock `pathlib.Path.exists()` explicitly.
- Use `missing_ok=True` for `Path.unlink()` in cleanup paths so tearDown doesn't crash on partial state.

## Coverage policy
Every source file modified on a branch must have a corresponding test file with 100% coverage of the new code. Plan test stub creation when modifying pre-existing scripts that lack test files. Enforced by `scripts/test_coverage_checker.py`.

## Mock exhaustion (postflight.py)
When `scripts/executor/postflight.py` adds a new `subprocess.run` call inside any function (e.g., `cleanup_after_merge()`, `finalize()`), count the total call sequence and update the mock `side_effect` counts in `tests/test_execute_recommendation.py`. Missing mock entries cause silent `StopIteration` failures that only surface in CI. See rec-117, rec-325.

## After editing tests
- After **removing** a test class: run `ruff check --fix` to catch unused imports (F401).
- After **adding** a test class: verify all modules used in `side_effect=` or assertions are imported at module scope.

## Test-count coupling (hardcoded exact-count assertions)
- Never assert an exact `len(X) == N` (or Yoda `N == len(X)`) against a production collection
  that grows by addition (e.g. a registry loaded from YAML, a table-name list). The collection
  grows, the literal doesn't, and the assertion breaks CI on the next addition -- often on a
  PR that never touched the test file, so the `--pre` diff-aware tier never selects it and the
  break only surfaces post-merge (see rec-2572..2576).
- Instead: derive independently (cross-check against a raw-text scan or a different SoT),
  assert a growth-safe invariant (uniqueness via `len(X) == len(set(X))`, a membership floor
  of required entries), or assert a wiring contract (`derived_list == [transform(e) for e in
  source()]`).
- Never derive a count by re-parsing the exact same structured source the code path already
  uses (tautological), and never cross-check `len(A + B) == len(A) + len(B)` when the composite
  is literally the concatenation of its parts -- that's an always-true list identity, not an
  independent check.
- For a deliberately-sized fixture that is genuinely controlled (not a growing production
  collection) but incidentally touches a curated collection, add a
  `# count-coupling-ok: <reason>` waiver comment on the assert's line rather than deriving.
- Enforced by `scripts/checks/hygiene/validate_test_count_coupling.py` (both `--pre` and full
  presubmit tiers, Decision 104) -- scans `tests/**/*.py` for the pattern, including aliased
  locals tainted by a curated loader call and string-subscript keys into a curated field.

## Acceptance command rules (when filing recommendations from tests)
- No `pytest -k` selectors in acceptance commands — LLM-generated test names are unpredictable and rename between runs. Use `grep` to verify the test exists, then run via `pytest tests/test_file.py::ClassName`.
- Acceptance commands must not contain `python -c` one-liners (shell-quoting fragility).

## Namespace migration discipline
When refactoring a monolith into a package, all `@patch("module.symbol")` calls must be updated to the new submodule locations. Enumerate via grep before refactoring; for large suites, write a bulk replacement script rather than editing by hand.

## ruff format and tests
- Never split the same module's imports across two blocks at the top of a test file — `ruff format` silently drops symbols from the second block. Use one consolidated block with `# noqa: F401` if needed.
