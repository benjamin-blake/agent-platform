# Plan

## Intent
Restore CI gate integrity by turning the four un-wired `verify_ci_workflow` guards into real `validate.py` presubmit merge gates (Decision 60), reconciling the two that still assert the retired self-hosted runner topology to the GitHub-hosted reality (CD.21), and reconciling the canonical CI/CD architecture doc so tooling and docs stop drifting. This hardens the trust loop the self-improving trading system depends on.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Plan Path
docs/plans/PLAN-ci-workflow-guards-wiring.md

## Phase
Platform / trust-loop hardening. Tier theme: T2 (CI verification-coverage restoration; T2.15-adjacent but disjoint -- T2.15's scope is ops.yaml DQ blocks + CausalChainVerifier, gated on CD.17/T3.2, and does not cover `verify_ci_workflow.py` guard wiring). Driven by ci-rca rec-2026 (planning soft-warn exception category `ci_rca`; not tier-gated).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/verify_ci_workflow.py` | Modify | Reconcile the two stale guards to CD.21: `_check_canary` asserts `runs-on == "ubuntu-latest"` (was `["self-hosted","linux"]`); `_check_concurrency` asserts no `pr-validate`/`main-validate`/canary job declares a `concurrency.group == "ci-runner"` (anti-regression guard -- the single-runner construct is obsolete on GitHub-hosted runners). Leave `_check_jobs_and_flags` and `_check_fetch_depth` unchanged. |
| `scripts/validate.py` | Modify | Add `validate_ci_workflow_guards(failed)` mirroring the existing `validate_ci_rca_trigger` pattern (sys.path injection + import + call the four `_check_*` functions, appending distinct failure labels); register it in `run_python_checks` next to `validate_ci_rca_trigger`. Harden error handling so a non-`AssertionError` exception records a failure instead of crashing presubmit, applied to BOTH the new function and `validate_ci_rca_trigger` (rec-2027). |
| `tests/test_verify_ci_workflow.py` | Create | Unit tests covering all 5 guard functions, both pass-path (valid fixture -> no raise) and fail-path (mutated fixture -> `AssertionError`) (rec-830). |
| `tests/test_validate.py` | Modify | Add tests for the new wiring: (a) `validate_ci_workflow_guards` appends nothing when guards pass; (b) when a guard raises a non-`AssertionError` (monkeypatched), the function records a failure and does not propagate (rec-2027). |
| `docs/INTENT-ci-cd-architecture.md` | Modify | Reconcile Section 2.5 (L8 concurrency row, line ~202), Section 9 "Single-runner concurrency and L8 sequencing" (lines ~590-609), and the mentions at lines ~230 and ~499 to the GitHub-hosted `ubuntu-latest` reality; record single-runner `ci-runner`/`cancel-in-progress:false` concurrency as retired by CD.21 (each `ubuntu-latest` job runs on its own isolated runner; no host serialization needed). Cite Decision 73 + CD.21. |

## Bundled Recommendations
- **rec-2026** (ci_rca, S, Low) -- "Wire remaining verify_ci_workflow guards into validate.py presubmit tier" (the anchor; clears the ci-rca HARD BLOCK).
- **rec-2027** (code-review, XS, Medium) -- "`validate_ci_rca_trigger` catches only `AssertionError`; other errors crash presubmit" (harden the shared pattern).
- **rec-830** (code-review, S, Medium) -- "`verify_ci_workflow.py` has no unit tests despite being a VP execution dependency".

## Infrastructure Dependencies
N/A -- no `.tf` files in scope. Per Path 1 (human decision), `.github/workflows/ci.yml` and `.github/workflows/main-canary.yml` are NOT modified: they already migrated to `ubuntu-latest` and dropped the concurrency block under CD.21, so there is no CI runtime change. The new gate runs in CI because CI invokes `validate.py` (no separate `ci.yml` edit -- per the merge protocol, never add a check to `ci.yml` without `validate.py` first; here it lives only in `validate.py`).

## Acceptance Criteria
- [ ] All four previously-unwired guards pass when invoked directly: `jobs-and-flags`, `fetch-depth`, `concurrency`, `canary` each print `OK`.
- [ ] `validate_ci_workflow_guards` is defined in `scripts/validate.py` AND called from `run_python_checks` (satisfies rec-2026's `grep -q 'validate_ci_workflow_guards' scripts/validate.py`).
- [ ] `_check_canary` asserts `ubuntu-latest`; `_check_concurrency` asserts the `ci-runner` group is absent (CD.21 reconciliation).
- [ ] Both `validate_ci_rca_trigger` and `validate_ci_workflow_guards` catch non-`AssertionError` exceptions and append a failure rather than raising (rec-2027), proven by a unit test.
- [ ] `tests/test_verify_ci_workflow.py` exists and covers pass + fail paths for all 5 guard functions (rec-830).
- [ ] `docs/INTENT-ci-cd-architecture.md` no longer asserts `ci-runner`/`cancel-in-progress:false` single-runner concurrency as current/BUILT; it records the construct as retired by CD.21.
- [ ] Full presubmit `bin/venv-python -m scripts.validate` exits 0 with the new `ci-workflow guards` gate reporting PASS.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Reconciled canary guard passes against the real workflow file | `bin/venv-python -m scripts.verify_ci_workflow canary` | prints `OK` | `FAIL: canary runs-on...` -> guard still asserts self-hosted; update assertion to `ubuntu-latest` |
| 2 | pre-deploy | Reconciled concurrency guard passes | `bin/venv-python -m scripts.verify_ci_workflow concurrency` | prints `OK` | `FAIL: ...concurrency...` -> guard still asserts the obsolete `ci-runner` positive block |
| 3 | pre-deploy | The two already-passing guards still pass | `bin/venv-python -m scripts.verify_ci_workflow jobs-and-flags && bin/venv-python -m scripts.verify_ci_workflow fetch-depth` | prints `OK` twice (exit 0) | a regression in the unchanged guards; revert unintended edits |
| 4 | pre-deploy | New unit tests cover pass + fail paths for all guards (rec-830) | `bin/venv-python -m pytest tests/test_verify_ci_workflow.py -q` | all tests pass; fail-path tests assert `AssertionError` is raised on mutated fixtures | a guard does not raise on bad input (gate is hollow) -> tighten the guard or fix the test fixture |
| 5 | pre-deploy | Error-handling robustness: a non-assert error is recorded, not raised (rec-2027) | `bin/venv-python -m pytest tests/test_validate.py -k "ci_workflow_guards or ci_rca_trigger" -q` | tests pass; injected `RuntimeError` yields a `failed` entry, no exception propagates | the function re-raises -> broaden `except AssertionError` to `except Exception` |
| 6 | pre-deploy | rec-2026 acceptance: guard runnable + wiring present | `bin/venv-python -m scripts.verify_ci_workflow jobs-and-flags && grep -q 'validate_ci_workflow_guards' scripts/validate.py` | exit 0 | missing function or call -> add `validate_ci_workflow_guards` and register in `run_python_checks` |
| 7 | pre-deploy | Integration: the gate runs inside presubmit and reports PASS | `bin/venv-python -m scripts.validate 2>&1 \| grep -i 'ci-workflow guards'` | shows the `=== ci-workflow guards gate ===` / `PASS` line | gate absent from output -> not registered in `run_python_checks` |
| 8 | pre-deploy | INTENT doc reconciled (no stale single-runner concurrency as current) | `bin/venv-python - <<'PY'\nimport re,sys\nt=open("docs/INTENT-ci-cd-architecture.md").read()\nassert re.search(r"retir|CD\\.21|ubuntu-latest", t), "no CD.21 reconciliation note"\nassert "BUILT (ci-workflow-restructure" not in t.split("L8 single-runner concurrency")[-1][:200] or "retir" in t.lower(), "L8 row still marks ci-runner BUILT without retirement note"\nprint("OK")\nPY` | prints `OK` | doc still claims `ci-runner` concurrency BUILT/current -> reconcile Sections 2.5/9 + lines ~230/~499 |
| 9 | pre-deploy | Full presubmit green | `bin/venv-python -m scripts.validate` | exit 0 | any gate fails -> fix per its message; do not weaken a gate to pass |

## Constraints
- `validate.py` is the single source of truth for merge gates (Decision 60). Do NOT add the guard to `ci.yml` separately (merge protocol: never add a check to `ci.yml` without adding it to `validate.py` first; here it lives only in `validate.py`).
- Path 1 (human decision 2026-06-01): do NOT edit `.github/workflows/ci.yml` or `.github/workflows/main-canary.yml`. No CI runtime/concurrency behavior change. The `ci-runner` single-runner construct is retired (CD.21), not replaced.
- No rescue agents or workaround loops (Decision 55). This is a reviewed root-cause forward-fix off a ci-rca rec (Decision 72), not an inline patch.
- `scripts/validate.py` carries a `# complexity-waiver: decision-43`; keep `validate_ci_workflow_guards` small and within the cyclomatic/SLOC gates -- factor the shared sys.path-injection + broad-except idiom rather than duplicating bulk.
- Python 3.12+, type hints required, ruff format, line length 127. No emojis; ASCII hyphens only. Invoke Python via `bin/venv-python`.
- Recommendation status changes go through the portal (`bin/venv-python -m scripts.ops_data_portal` -> `update_rec`); never edit `logs/.recommendations-log.jsonl` directly (Single Portal Invariant).

## Context
- **Driver / HARD BLOCK clearance:** open ci-rca rec `rec-2026` triggers the planning HARD BLOCK ("/plan cannot scope unrelated work while a ci-rca rec is open"). This plan satisfies Related-Work condition #1 (same file `scripts/verify_ci_workflow.py`) AND #3 (same failure category: validate.py false negative / CI verification coverage), so the block is cleared.
- **Bundle rationale:** rec-2027 fixes the error-handling crash in the exact function family being extended; rec-830 adds the missing tests for the module being promoted to a hard gate. All three are small and confined to two source files + their tests + the INTENT doc.
- **Decisions to cite:** Decision 60 (validate.py is the only gate), Decision 73 (owns `ci.yml`/`main-canary.yml` structure via this INTENT doc -- editing the concurrency narrative is editing Decision 73's architecture), Decision 48 (V2 classification; `.github/workflows/*.yml` is not in the V3 trigger list, and Path 1 edits no workflow YAML anyway), CD.21 (self-hosted EC2 runner retired 2026-05-28; canary moved to `ubuntu-latest`; authority for declaring single-runner concurrency obsolete). Honoured-not-violated: Decision 55/72 (reviewed forward-fix). Watch: Decision 43 (validate.py complexity waiver).
- **Decision-scout gate (2026-06-01):** Verdict FLAGS_FOUND. WARN (Decision 73 / INTENT doc concurrency drift) resolved by adding `docs/INTENT-ci-cd-architecture.md` to scope. NOTE (executor-freeze / heuristic suspension): 5-file plan would historically hint STRATEGIC, but STRATEGIC is suspended and the >5-file/>8-step heuristic is lifted -- IMPLEMENTATION is the correct and intended declaration.
- **Branch freshness:** 0 commits behind / 0 ahead of `origin/main` at planning time; no scope-overlap with recent main changes.
- **Already done:** the fifth guard (`ci-rca-filter`) is already wired via `validate_ci_rca_trigger` (scripts/validate.py:1973). This plan wires the remaining four.
- **Gotcha:** the guards read fixed relative paths (`.github/workflows/ci.yml`, `.github/workflows/main-canary.yml`, `.github/workflows/ci-rca.yml`, `.claude/agents/scheduled/ci-rca.md`). Unit tests must `monkeypatch.chdir(tmp_path)` and stage crafted fixture files under that tmp dir so pass/fail paths are exercised hermetically.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (Decisions 60, 73, 48, 55, 72, 43; candidate CD.21)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Confirmed Path 1: no `.github/workflows/*.yml` edits

## Ordered Execution Steps
1. **`scripts/verify_ci_workflow.py`** -- Reconcile `_check_canary`: assert `canary_job.get("runs-on") == "ubuntu-latest"` (string, matching `main-canary.yml`); drop the `isinstance(..., list)` + `["self-hosted","linux"]` assertions and the canary `concurrency` assertions tied to `ci-runner`. Reconcile `_check_concurrency`: instead of requiring a positive `ci-runner` block, assert that no `pr-validate`/`main-validate` job declares `concurrency.group == "ci-runner"` (anti-regression). Keep `_check_jobs_and_flags`, `_check_fetch_depth`, `_check_ci_rca_filter` unchanged.
2. **`scripts/validate.py`** -- Add `validate_ci_workflow_guards(failed: list[str]) -> None` mirroring `validate_ci_rca_trigger`: inject `ROOT` into `sys.path`, import `_check_jobs_and_flags`, `_check_fetch_depth`, `_check_concurrency`, `_check_canary`, run each, append a distinct failure label per guard. Wrap each guard call in `try/except Exception` so a non-assert error records a failure instead of crashing presubmit. Print a `=== ci-workflow guards gate ===` header and a `PASS:`/`FAIL:` line per guard. Factor the shared sys.path-injection idiom if it keeps the new function within the Decision 43 gates.
3. **`scripts/validate.py`** -- Harden `validate_ci_rca_trigger` the same way (broaden `except AssertionError` to `except Exception`, preserving the existing failure label) per rec-2027.
4. **`scripts/validate.py`** -- Register `validate_ci_workflow_guards(failed)` in `run_python_checks`, adjacent to `validate_ci_rca_trigger(failed)`.
5. **`tests/test_verify_ci_workflow.py`** (create) -- For each of the 5 guards, add a pass-path test (stage valid fixture files under `tmp_path` via `monkeypatch.chdir`; assert no raise) and a fail-path test (mutate one field; assert `AssertionError`). Cover at minimum: canary `ubuntu-latest` pass + `self-hosted` fail; concurrency absent-`ci-runner` pass + present-`ci-runner` fail; jobs-and-flags and fetch-depth pass + a representative fail; ci-rca-filter pass + missing-`FILED:` fail (rec-830).
6. **`tests/test_validate.py`** -- Add: (a) `validate_ci_workflow_guards` leaves `failed` empty when all guards pass; (b) monkeypatch one imported `_check_*` to raise `RuntimeError` and assert `validate_ci_workflow_guards` appends a failure and does not propagate; (c) the analogous non-assert test for `validate_ci_rca_trigger` (rec-2027).
7. **`docs/INTENT-ci-cd-architecture.md`** -- Reconcile Section 2.5 L8 concurrency row (~line 202), Section 9 (~lines 590-609), and the mentions at ~lines 230 and 499 to the GitHub-hosted `ubuntu-latest` reality. Record single-runner `ci-runner`/`cancel-in-progress:false` concurrency as retired by CD.21 (per-job isolated runners; no host serialization). Keep historical narrative accurate (note it was BUILT 2026-05-19, retired 2026-05-28 by CD.21). Cite Decision 73 + CD.21.
8. Run the edit-loop lint/format gate: `bin/venv-python -m scripts.validate --pre`. Fix any lint/format issues.
9. **Execute Verification Plan** -- run each step in order. Loop until all pass. Do not weaken any gate to make it pass; if a guard cannot pass against reality, re-diagnose (Decision 55).
10. After merge, mark rec-2026, rec-2027, rec-830 resolved via `bin/venv-python -m scripts.ops_data_portal` (`update_rec`, requires Athena via the `agent_platform` profile) -- never edit the JSONL cache directly.
11. Report: what was implemented, verification results (paste the VP command outputs), and the three rec status updates.
