# Tests — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Test file placement — mirror convention (Decision 131, amends Decision 104)
Source-to-test mapping is gated by a retiring grandfather-table in `scripts/test_coverage_checker.py`
(`map_source_to_test`). While a home is still listed in `_RETIRING_GRANDFATHER_HOMES`, the
pre-inversion Decision-104 colocation rule applies unchanged (e.g. every `scripts/checks/**/*.py`
colocates its tests in `tests/test_validate.py`). Once a wave retires that home (deletes its one
basename line from `_RETIRING_GRANDFATHER_HOMES`), every source path that used to colocate there
instead resolves via the MIRROR convention:

- Drop the leading `src`/`scripts` root segment, keep the remaining directory sub-path, and name
  the test `test_<stem>.py` in that mirrored directory. Examples:
  - `scripts/checks/hygiene/validate_prose_allowlist.py` -> `tests/checks/hygiene/test_validate_prose_allowlist.py`
  - `scripts/executor/step_runner.py` -> `tests/executor/test_step_runner.py`
  - `src/common/config.py` -> `tests/common/test_config.py`
- A declared concern-split monolith (a single-file source with no per-submodule source to mirror
  1:1) instead resolves to a test PACKAGE DIRECTORY, not a single file -- e.g.
  `scripts/ops_writer.py` -> `tests/ops_writer/` (concern-split `test_*.py` modules inside), which
  `check_test_file_exists` accepts once it exists with >=1 `test_*.py`.
- A wave retires a home by deleting exactly its one basename line from `_RETIRING_GRANDFATHER_HOMES`
  -- a low-conflict, one-line edit -- then creates the mirror test file(s)/package and deletes the
  home's `config/sloc_budgets.yaml` entry.

Every mirror test directory carries an `__init__.py` (prepend import mode; fully-qualified,
collision-free module paths). Shared helpers live in `tests/fixtures/` (an importable package,
exempt from the cross-test-import guard because its names never start with `test_`) or in conftest
fixtures -- never imported from another `test_*` module. The existing `tests/test_verifiers/` lacks
its `__init__.py` and will be normalized by its own wave, not this one.

**Later-wave hand-offs (read before decomposing a roster home):**
(a) Three roster homes -- `test_executor_step_runner.py`, `test_executor_plan.py`,
`test_executor_postflight.py` -- have NO source path mapping to them (`scripts/executor/**` returns
`None` in the grandfather helper, preserved per Decision 124). Their decomposition is a PURE
test-file split + `config/sloc_budgets.yaml` entry deletion; deleting their
`_RETIRING_GRANDFATHER_HOMES` line is a no-op (the mirror branch never fires, since the source still
returns `None`). The "one-line retirement" is therefore NOT uniform across all 24 roster homes.
(b) Drop-root is safe/chosen because it matches repo precedent (`tests/checks/`,
`tests/test_verifiers/`) and is collision-free for the fixed 24-home roster (no `scripts/<x>/` vs
`src/<x>/` subdirectory-name overlap exists). Known boundary: a future such collision would need a
preserve-root exception for that pair -- out of scope now, flagged for the map's maintainer
(`scripts/test_coverage_checker.py`).

## No cross-test imports
A test module must never import from another `test_*` module -- each mirror package must be
self-contained. Shared helpers live in `conftest.py` fixtures or `tests/fixtures/` (an importable
package whose names never start with `test_`, so both are exempt by construction). Enforced by
`scripts/checks/hygiene/validate_no_cross_test_imports.py` (both `--pre` and full presubmit tiers).
The one pre-existing violation at foundation time, `tests/test_verifier_harness.py` (a re-export
shim of `tests/test_verifiers/test_harness.py`), is grandfathered in a documented
`_GRANDFATHERED_CROSS_TEST_IMPORTS` allowlist until a later wave removes the shim.

## Per-package conftest hierarchy
The global recursion guards (`_VALIDATE_DEPTH`, `_COVERAGE_SUBPROCESS`, the `PYTEST_CURRENT_TEST`
early-exit in `scripts/validate.py` `main()`) and socket guards (`--disable-socket` addopts + the
`_allow_network_for_integration` autouse fixture) live SOLELY in the root `tests/conftest.py`.
pytest merges conftests up the tree, so a sub-package `tests/<pkg>/conftest.py` (e.g.
`tests/checks/conftest.py`, the foundation's example scaffold) layers UNDER the root automatically
without redeclaring globals. Package-specific autouse fixtures migrate into the matching
sub-conftest per-wave, alongside that package's test-file decomposition -- not all at once.

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
