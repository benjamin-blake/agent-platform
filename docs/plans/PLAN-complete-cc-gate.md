# Plan

## Intent
Complete rec-429 by landing the cyclomatic-complexity (CC) hard gate in `scripts/validate.py`. The SLOC half of Decision 43 already ships (`validate_sloc_limits` at validate.py:1041, wired at validate.py:1945, covered by `TestValidateSlocLimits` at test_validate.py:755) and all 12 over-SLOC files carry the waiver. The CC half is the outstanding second mandate from Decision 43; this plan closes both rec-429 and rec-430 in a single PR.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/complete-cc-gate

## Phase
Phase 1: Core Infrastructure (complete). Tooling hardening, not a new roadmap tier.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/validate.py` | Modify | Add `_CC_LIMIT = 20` constant + `validate_cc_limits(failed)` function + wire into the `--pre` branch (line 2263 area, after `validate_product_roadmap`) per rec-859 RCA's `earliest_viable_gate = "pre"` classification |
| `tests/test_validate.py` | Modify | Add `validate_cc_limits` symbol import + `TestValidateCcLimits` test class mirroring `TestValidateSlocLimits` |
| `scripts/llm_client.py` | Modify | Add `# complexity-waiver: decision-43` as line 1 (`_gemini_call` = 59 branches) |
| `scripts/product_roadmap.py` | Modify | Add `# complexity-waiver: decision-43` as line 1 (`_validate_graph` = 48) |
| `scripts/sync_ops.py` | Modify | Add `# complexity-waiver: decision-43` as line 1 (`_rebuild_local_cache` = 32, `_pull_single_table` = 23) |
| `scripts/platform_roadmap.py` | Modify | Add `# complexity-waiver: decision-43` as line 1 (`_validate_graph` = 28) |
| `src/data/feature_engine.py` | Modify | Add `# complexity-waiver: decision-43` as line 1 (`_add_technicals` = 21) |

## Bundled Recommendations
- **rec-429** (Critical, S) -- the work item this plan implements. SLOC half already shipped; this lands the CC half.
- **rec-430** (High, XS) -- functionally complete (12/12 SLOC-over-limit files already carry the waiver). Closed by this plan via portal update.

## Infrastructure Dependencies
No `.tf` files in scope. **One Lambda-packaged file in scope** (`scripts/llm_client.py`, member of `_LAMBDA_SCRIPTS`); edit is comment-only (single waiver header line) with zero runtime impact. Per CLAUDE.md Temporary Operational Constraints (Decision 67 freeze), Lambda rebuild + deploy + smoke-test is DEFERRED -- see Ordered Execution Step 9.

## Acceptance Criteria
- [ ] `_CC_LIMIT = 20` constant defined in `scripts/validate.py` adjacent to `_SLOC_LIMIT`
- [ ] `validate_cc_limits(failed: list[str]) -> None` defined in `scripts/validate.py`, walking `scripts/` and `src/`, parsing AST, counting `If`/`For`/`While`/`Try`/`ExceptHandler`/`With`/`BoolOp` nodes per `FunctionDef`/`AsyncFunctionDef`, flagging functions with count > 20 unless the file's first 10 lines contain `_WAIVER_PATTERN`
- [ ] `validate_cc_limits(failed)` called from the `--pre` branch (`scripts/validate.py` ~line 2263) immediately after `validate_product_roadmap(failed)`, NOT from `run_python_checks()`. Rationale: rec-859 RCA classified O(lines) AST checks as `earliest_viable_gate = "pre"`; placing CC in `--pre` from day 1 avoids the tier-placement debt that `PLAN-sloc-promotion-to-pre` (queued under T1.13) will lift from the SLOC gate.
- [ ] `TestValidateCcLimits` class in `tests/test_validate.py` covers: over-limit catch, waivered allow, under-limit allow, `__init__.py` skip (4 tests minimum, mirroring `TestValidateSlocLimits`)
- [ ] 5 files (`scripts/llm_client.py`, `scripts/product_roadmap.py`, `scripts/sync_ops.py`, `scripts/platform_roadmap.py`, `src/data/feature_engine.py`) carry `# complexity-waiver: decision-43` as line 1
- [ ] `bin/venv-python -m scripts.validate` (full presubmit) exits 0 on this branch
- [ ] rec-429 closed via `ops_data_portal update_rec` with status=closed
- [ ] rec-430 closed via `ops_data_portal update_rec` with status=closed

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | New CC tests pass (includes the sentinel test `test_catches_over_limit_function` that builds a tmp_path mirror with a 21+ branch function -- this replaces the on-disk-mutation sentinel of the prior draft) | `bin/venv-python -m pytest tests/test_validate.py::TestValidateCcLimits -v` | All 4 tests pass; `test_catches_over_limit_function` specifically asserts the gate trips on an over-limit function and that the error message names the function | Inspect AST-walk counting logic; verify waiver-detection mirrors SLOC (`_WAIVER_PATTERN.search` on first 10 lines); verify `_SLOC_EXCLUDE_DIRS` reuse |
| 2 | pre-deploy | Existing validate tests still green (no regression) | `bin/venv-python -m pytest tests/test_validate.py -x -q` | All tests pass; no regression in `TestValidateSlocLimits`, `TestValidateComplexity`, etc. | If a SLOC test fails, the new constant placement disturbed module-load order; restore constant grouping |
| 3 | pre-deploy | Fast tier (`--pre`) clean -- this tier now contains the new CC gate | `bin/venv-python -m scripts.validate --pre` | Exits 0; the `--pre` output includes a CC-gate section reporting "All functions within CC limits or waivered." Elapsed time stays under `_FAST_TIER_BUDGET_SECONDS` (300s); current `--pre` baseline is ~12s and CC adds <100ms per scanned file (~200 files = <20s) | If `--pre` exits non-zero on this branch despite waivers, the gate is misdetecting; debug `ast.walk` traversal. If budget is breached, run `bin/venv-python -m scripts.validate --pre --ignore-budget --ignore-budget-reason "diagnosing CC gate cost"` to surface per-check timing |
| 4 | pre-deploy | Full presubmit clean (CC gate is no longer in this tier, but presubmit must still pass) | `bin/venv-python -m scripts.validate` | Exits 0 | If gate fails in any check (not the CC one), it's an unrelated regression; investigate via the failing check's own log |
| 5 | post-merge | Housekeeping: close rec-429 and rec-430 via ops portal | `bin/venv-python -m scripts.ops_data_portal update_rec --id rec-429 --status closed --notes "CC gate landed in validate.py:validate_cc_limits(), wired in --pre branch per rec-859 RCA earliest_viable_gate classification; covered by TestValidateCcLimits"` then `bin/venv-python -m scripts.ops_data_portal update_rec --id rec-430 --status closed --notes "12/12 Day-1 over-SLOC files carry # complexity-waiver: decision-43; CC half of Decision 43 now enforced by validate_cc_limits() in --pre"` | Both calls return success; `bin/venv-python -m scripts.sync_ops pull` then a JSONL grep confirms both recs show `status: closed` | If portal call fails with SSO error, run `aws sso login --profile company-aws-profile` and retry. If a portal call fails with schema error, surface the error verbatim and STOP -- do not edit the JSONL directly (warehouse-as-SoT invariant). |

## Constraints
- **Decision 43** (Directed Growth Governance) -- this plan implements the second half of Decision 43's structural-limits table. The 20-branch limit and waiver-comment pattern `# complexity-waiver: decision-43` are mandated by the decision. The branching-node set (`If`/`For`/`While`/`Try`/`ExceptHandler`/`With`/`BoolOp`) matches the rec-429 spec.
- **Decision 60** (Two-tier validation) -- `scripts/validate.py` is the canonical CI gate substrate. Adding the new check here propagates to CI automatically. **Tier placement: `--pre` (fast tier), NOT `run_python_checks()` (full tier).** This departs from the sibling `validate_sloc_limits` placement intentionally. Per `docs/INTENT-ci-rca-methodology.md` (rec-859 RCA), O(lines) AST checks have `earliest_viable_gate = "pre"`; the SLOC gate's full-tier placement was the documented detection-gap that allowed rec-859 to escape PR review, and `PLAN-sloc-promotion-to-pre` (queued under T1.13 exit criteria, `ROADMAP-PLATFORM.yaml:2400`) is the planned remediation. Landing CC in `--pre` from day 1 avoids doubling the migration debt and gives the future SLOC-promotion plan a model placement to mirror. Runtime: current `--pre` baseline ~12s + CC overhead <20s (200 files × <100ms AST walk) = well under `_FAST_TIER_BUDGET_SECONDS` (300s) per Decision 73.
- **Decision 67** (Lambda + STRATEGIC freeze) -- this plan is IMPLEMENTATION type, complies with the freeze.
- **Decision 73** (Diff-aware CI / forward-fix) -- gate placement in `--pre` means the check runs diff-aware on every PR (the gate scans all `.py` files under `scripts/` and `src/` regardless of the diff, but the gate is invoked from the diff-aware fast tier, so it fires at PR review time rather than only at merge). Runtime cost analysis confirms the gate fits the 5-min budget. If a future commit introduces an over-CC function in a non-waivered file, the gate trips at PR open, not at merge; the ci-rca path is only relevant for the SLOC gate (still full-tier) until `PLAN-sloc-promotion-to-pre` lands.
- **Decision 48** (Verification Tier Classification) -- V2 is correct (pure Python logic in scripts/, no external integration). Sentinel-test step (#3) exceeds V2 minimum and is intentional hardening because this modifies an active CI gate.
- **Decision 44** (Executor Self-Modification Boundary) -- none of the 7 scope files are executor-boundary files. No automatable rerouting needed.
- **Decision 55** (RCA-First / no rescue agents or workaround loops) -- pre-emptive waivering of the 5 known offenders avoids the forward-fix path; no rescue logic in scope.
- **Waiver semantics**: the rec-429 text says "anywhere in the file"; the shipped SLOC gate narrows this to "first 10 lines". This plan inherits the narrower interpretation for consistency with the shipped SLOC gate. Both gates use identical waiver-detection (`_WAIVER_PATTERN.search(header)` where `header = "\n".join(lines[:10])`).
- **No refactor of CC offenders** is in scope. The 6 currently-offending functions are waivered file-level. The gate's purpose is to prevent NEW monoliths from forming, not to refactor existing code. Per-function refactors (e.g., decomposing `_gemini_call`'s 59-branch dispatch) belong in separate recs.

## Context
- Branch is freshly cut from main; main was 0 commits behind at preflight (`logs/.preflight-report.json` -> `main_freshness.commits_behind=0`).
- Preflight surfaced a stale Athena view warning (`telemetry_agent_invocations_current` column-count mismatch); unrelated to this plan, noted for separate triage.
- Day-1 SLOC over-limit list from the original rec-429 (`validate.py`, `step_runner.py`, `postflight.py`, `plan.py`, `execute_recommendation.py`) shifted since the rec was filed -- the current 12 over-SLOC files are: `scripts/execute_recommendation.py` (2862), `scripts/validate.py` (1906), `scripts/session_preflight.py` (1248), `scripts/executor/postflight.py` (1157), `scripts/ops_data_portal.py` (1005), `scripts/executor/step_runner.py` (967), `scripts/executor/plan.py` (752), `scripts/session_postflight.py` (672), `scripts/data_quality_runner.py` (669), `scripts/ops_writer.py` (584), `scripts/executor/batch.py` (568), `scripts/copilot_wrapper.py` (545). All 12 already carry the waiver.
- Day-1 CC offender list (6 functions in 5 files, none waivered before this plan): `scripts/llm_client.py::_gemini_call` (59), `scripts/product_roadmap.py::_validate_graph` (48), `scripts/sync_ops.py::_rebuild_local_cache` (32), `scripts/platform_roadmap.py::_validate_graph` (28), `scripts/sync_ops.py::_pull_single_table` (23), `src/data/feature_engine.py::_add_technicals` (21).
- The Day-1 CC-offender scan was performed at planning time using the exact AST-walk logic the new gate will implement; if any of these files are deleted or refactored before implementation lands, re-run the scan and update the waiver list accordingly.
- Decision-scout gate (Step 6a) returned NO_FLAGS. CITE list (Decisions 43, 60, 67) and RELATED list (Decisions 48, 44, 55, 73) all addressed above.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `agent/complete-cc-gate`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` Decision 43, 60, 67, 73, 48, 44, 55 understood (or the scout summary in this plan trusted)
- [ ] All 7 files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] SSO session active for portal closure step (`aws sts get-caller-identity --profile company-aws-profile`)

## Ordered Execution Steps
1. **Add `_CC_LIMIT` constant to `scripts/validate.py`** -- place adjacent to `_SLOC_LIMIT` at the existing block (currently lines 1036-1038). New line: `_CC_LIMIT = 20`.
2. **Implement `validate_cc_limits(failed)` in `scripts/validate.py`** -- insert immediately after `validate_sloc_limits()` body (i.e., before `validate_complexity()` at line 1078). Use the same directory walk pattern as `validate_sloc_limits`: iterate `(ROOT / "scripts", ROOT / "src")`, skip `__init__.py`, skip `_SLOC_EXCLUDE_DIRS` parts, read file content, split lines, check `_WAIVER_PATTERN.search("\n".join(lines[:10]))` for waiver. If not waivered, `ast.parse(content)`, walk each `FunctionDef`/`AsyncFunctionDef`, count `If`/`For`/`While`/`Try`/`ExceptHandler`/`With`/`BoolOp` descendants per function via `sum(1 for sub in ast.walk(node) if isinstance(sub, BRANCH_TYPES))`. Append to errors when count > `_CC_LIMIT`. If errors, print them and `failed.append("Cyclomatic complexity limits (Decision 43)")`. Handle `SyntaxError` from `ast.parse` by skipping the file silently (matches `validate_complexity` behaviour).
3. **Wire into the `--pre` branch** -- in `scripts/validate.py` line 2263 area, add `validate_cc_limits(failed)` immediately after `validate_product_roadmap(failed)` (which already lives in `--pre` with the comment "pure Python, sub-100ms, active editing surface" -- CC fits the identical rationale). Add an inline comment cross-referencing `docs/INTENT-ci-rca-methodology.md` rec-859 RCA. Do NOT also add it to `run_python_checks()` -- single-tier placement only.
4. **Add waiver to 5 CC-offender files** -- prepend `# complexity-waiver: decision-43\n` as line 1 of: `scripts/llm_client.py`, `scripts/product_roadmap.py`, `scripts/sync_ops.py`, `scripts/platform_roadmap.py`, `src/data/feature_engine.py`. Preserve shebang positioning if present (shebang stays line 1, waiver becomes line 2 -- mirror the existing pattern in `scripts/validate.py` where line 1 is `# complexity-waiver: decision-43` and line 2 is `#!/usr/bin/env python3`).
5. **Add `TestValidateCcLimits` to `tests/test_validate.py`** -- insert near `TestValidateSlocLimits` (line 755). Add `validate_cc_limits = _validate.validate_cc_limits` import at the top of the file (the existing import block at lines 20-43). Mirror the 4 SLOC test patterns: (a) `test_catches_over_limit_function` -- create tmp Python file with a function containing 21+ if-statements (the sentinel: this test alone proves the gate trips on real over-CC code without needing on-disk mutation of production files); assert `failed` length 1 and that the error message names the offending function; (b) `test_allows_waivered_file` -- same file but with waiver comment in first 10 lines, assert `failed == []`; (c) `test_allows_under_limit_function` -- function with 5 if-statements, assert `failed == []`; (d) `test_skips_init_files` -- over-CC function inside `__init__.py`, assert `failed == []`. Use `with patch("validate.ROOT", tmp_path)` to scope the directory walk to the test fixture (identical pattern to `TestValidateSlocLimits` -- see `tests/test_validate.py:765`).
6. **Run Verification Plan steps 1-5** in order. Loop until pass.
7. **Commit** the implementation (single commit, message body cites rec-429 and rec-430).
8. **Push branch, open PR, await CI green.** Full presubmit on the runner must pass.
9. **DEFERRED: `build_lambda.py --deploy + run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** -- `scripts/llm_client.py` is in `_LAMBDA_SCRIPTS`, so plans touching it normally require Lambda rebuild+deploy+smoke-test per CLAUDE.md Temporary Operational Constraints. The edit in this plan is a single-line `# complexity-waiver: decision-43` comment with zero runtime impact (no code path change, no import change, no wire-format change), so deferral is safe; explicit step retained for compliance and future readability.
10. **After merge:** run Verification Plan step 5 (portal closure for rec-429 and rec-430).
11. **Report**: what was implemented, verification results, both rec IDs closed.

## Rollback
- If the gate produces false-positive failures in CI post-merge: revert the merge commit (`git revert <sha>`) and file a follow-up rec capturing the false-positive pattern. Do NOT add a blanket waiver to silence the gate.
- If `validate_cc_limits` itself has a bug (e.g., `ast.walk` recursion miscount): a fast-follow fix-up commit is preferable to revert, since the gate's existence is more valuable than its momentary correctness.
- Waiver removals (Verification step 3 sentinel) are restored via `git checkout -- <file>` and are always single-file scoped.
