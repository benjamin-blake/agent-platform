# Plan

## Intent
Implement Phase 3 (Ratchet Implementation) of the DQ enforcement maturity arc, introducing
the `enforced` boolean field so the 59 currently-failing checks become advisory rather than
blocking, unblocking the executor while preserving hard gates for checks that are verifiably
passing.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/dq-ratchet-phase-3

## Phase
Phase Platform - Wave 4 prerequisite (Autonomous Executor). Phase 3 must land before the
executor is re-enabled; the broad `DataQualityVerifier.covers` list (Phase 2, PR #286)
means any executor run touching `scripts/ops_data_portal.py` or `src/data/**` is blocked
until the ratchet is in place.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/data_quality_runner.py` | Modify | Add `enforced: bool = True` to `Check` dataclass; update `load_checks` (row_count, recency) and all `_compile_column_test` branches to read `enforced`; extend `_save_latest_result` to write `checks` array; add enforced-aware verdict aggregation to `run_checks` |
| `scripts/verifiers/data_quality.py` | Modify | Change missing-file path from `SKIPPED, ADVISORY` to `FAIL, HARD_GATE` (Known Gap closed in Phase 3) |
| `scripts/validate.py` | Modify | Add graduation guard: reads `git diff HEAD -- config/data_quality/` and `logs/debug/dq-latest.json`; blocks enforced:false -> true flips when check verdict != PASS; skipped on `--quick` |
| `config/data_quality/ops.yaml` | Modify | Annotate every `severity: error` check with explicit `enforced: true` or `enforced: false` (Wave 2 - requires live DQ run after Wave 1 commit) |
| `config/data_quality/telemetry.yaml` | Modify | Annotate every `severity: error` check with explicit `enforced: true` or `enforced: false` (Wave 2 - requires live DQ run after Wave 1 commit) |
| `docs/DECISIONS.md` | Modify | Add Decision 62: No separate DQ scheduled routine (Session E elimination) |
| `tests/test_data_quality_runner.py` | Modify | Add tests for `enforced` field on `Check`, loader reading, enforced-aware aggregation, and `checks` array in `_save_latest_result` output |
| `tests/test_verifiers/test_data_quality.py` | Modify | Update `test_verify_missing_file` to assert `FAIL, HARD_GATE` (currently asserts `SKIPPED, ADVISORY` - that is the behavior being changed) |
| `tests/test_validate.py` | Modify | Add graduation guard test class |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `enforced: bool = True` present on `Check` dataclass with that default
- [ ] `load_checks` reads `enforced` from `row_count` and `recency` YAML blocks; `_compile_column_test` reads `enforced` from all dict-form branches (`accepted_values`, `relationships`, `expression`, `not_null` dict, `unique` dict); bare-string tests default to `True`
- [ ] `_save_latest_result` writes a `checks` array; each entry has fields `table`, `column` (null for table-level), `test`, `verdict` - field name is `"test"` not `"test_type"`
- [ ] `run_checks`: `enforced: false` failures contribute ADVISORY (not FAIL) to aggregate; `severity: warn` checks remain advisory regardless of `enforced` value; `enforced: true` failures still produce FAIL aggregate
- [ ] Missing `dq-latest.json` returns `FAIL, HARD_GATE` from `DataQualityVerifier` (not `SKIPPED, ADVISORY`)
- [ ] Graduation guard in `validate.py`: blocks `enforced: false -> true` flip when verdict is FAIL; allows flip when PASS; warns but does not block when `dq-latest.json` is missing or has no `checks` array; treats SKIP verdict as inconclusive (warn, no block); blocks new check added directly as `enforced: true` when verdict is FAIL; skipped entirely on `--quick`
- [ ] All `severity: error` checks in both YAML files have explicit `enforced:` field; every `enforced: false` entry has an inline `# reason` comment on the same line
- [ ] Decision 62 filed in `docs/DECISIONS.md`
- [ ] `tests/test_verifiers/test_data_quality.py::test_verify_missing_file` updated and passes with new assertions
- [ ] All new and modified tests pass; `.venv/Scripts/python.exe -m scripts.validate --quick` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | post-Wave-1 | Runner enforced field, loader, and checks array: all runner tests pass | `.venv/Scripts/python.exe -m pytest tests/test_data_quality_runner.py -x -q 2>&1 \| tail -5` | All tests pass including new enforced and checks-array tests | `Check` missing `enforced` attr; loader not reading field; `_save_latest_result` missing `checks` key or using `"test_type"` instead of `"test"` |
| 2 | post-Wave-1 | Enforced-aware aggregation: false failure is ADVISORY not FAIL | `.venv/Scripts/python.exe -m pytest tests/test_data_quality_runner.py -k "advisory or aggregat" -x -q 2>&1 \| tail -3` | Test passes confirming `enforced=False` FAIL check does not produce FAIL aggregate | Aggregation path still treats all failures as FAIL regardless of enforced value |
| 3 | post-Wave-1 | Missing-file verifier change: now FAIL/HARD_GATE | `.venv/Scripts/python.exe -m pytest tests/test_verifiers/test_data_quality.py::test_verify_missing_file -x -q 2>&1 \| tail -3` | Test passes asserting `FAIL` + `HARD_GATE` | Verifier still returns `SKIPPED/ADVISORY` for missing file - the one-line change was not applied |
| 4 | post-Wave-1 | Graduation guard tests pass | `.venv/Scripts/python.exe -m pytest tests/test_validate.py -k "graduation" -x -q 2>&1 \| tail -3` | All graduation guard cases pass (block FAIL, allow PASS, warn on missing, warn on SKIP, skip on --quick) | Guard not blocking bad flip; or blocking on inconclusive SKIP when it should only warn |
| 5 | post-Wave-2 | YAML annotation complete: every enforced:false has inline comment | `grep -n "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml \| grep -v "#"` | Zero lines - all `enforced: false` entries have inline comments | Add `# reason` on the same line as each unannotated `enforced: false` |
| 6 | post-Wave-2 | No severity:error check left unannotated | `.venv/Scripts/python.exe -m scripts.data_quality_runner --dry-run 2>&1 \| head -5` | Dry-run completes without error; check count matches pre-change total (125) | Loader error reading `enforced` from a YAML form not yet handled |
| 7 | final | Full local validation passes | `.venv/Scripts/python.exe -m scripts.validate --quick` | Exit 0 | Ruff, import, or test failures introduced during implementation |

## Constraints
- Steps 1+2 of the INTENT (runner infrastructure + enforced-aware compiler) MUST be committed before any YAML annotation begins. The state where YAML has `enforced: false` entries but the runner does not yet respect them is dangerous (failures continue blocking as if the ratchet were not in place).
- `severity: warn` checks never require `enforced` annotation - skip them during YAML annotation.
- Bare-string tests (`- not_null`, `- unique`) that are currently PASS do not need conversion to dict form. Bare-string FAIL checks must be converted to dict form to receive `enforced: false`.
- The graduation guard fires only on the default presubmit tier. `validate.py --quick` skips it entirely - document this in the guard's output.
- `total == 0 -> FAIL, HARD_GATE` short-circuit at `scripts/verifiers/data_quality.py:83-89` must not be regressed.
- No rescue agents or workaround loops (Decision 55).
- `test_verify_missing_file` in `tests/test_verifiers/test_data_quality.py` must be updated (not just new tests added) - it currently asserts the old SKIPPED/ADVISORY behavior.
- **Lambda packaging note:** `config/data_quality/` is bulk-copied into `data-pipeline.zip` by `build_lambda.py:71` (`shutil.copytree(ROOT / "config", ...)`). However, zero Lambda handlers read these files (confirmed by grep of `src/data/handlers/`). The tier remains V2 because the YAML changes have no Lambda runtime effect. Decision 48's V3 trigger is "`_LAMBDA_SCRIPTS`-listed files" and "cross-service contract changes" - neither applies here. After this PR merges, run `python -m scripts.build_lambda --deploy` to refresh environment parity in the deployed zip.

## Context
- **INTENT anchor:** `docs/INTENT-dq-enforcement.md` is the authoritative spec. Read it in full before implementing. All Phase 3 decisions are `[DECIDED]` - do not re-litigate.
- **Phase 2 consequence:** `DataQualityVerifier.covers` includes `scripts/ops_data_portal.py` and `src/data/**` (broad list, PR #286). With 59 DQ failures, the executor is blocked on any rec touching those paths. Phase 3 unblocks this.
- **Two-wave commit sequence:** Wave 1 = Python changes (runner, verifier, validate.py, tests, DECISIONS.md). Wave 2 = YAML annotation. Wave 2 requires a live DQ run after Wave 1 is committed on the branch to produce a `checks` array in `dq-latest.json`. Do not annotate YAML before that run.
- **YAML annotation source of truth:** Run `.venv/Scripts/python.exe -m scripts.data_quality_runner` after Wave 1 commit. Read `logs/debug/dq-latest.json` `checks` array. Verdict FAIL -> `enforced: false`. Verdict PASS -> `enforced: true`. Verdict SKIP (dry-run) is inconclusive - do not use for annotation.
- **SSO requirement for YAML annotation:** The DQ runner needs Athena access. If SSO is unavailable, Wave 1 can be committed but Wave 2 (YAML annotation) cannot be completed. Phase 3 PR must not be merged until at least the `ops_recommendations` checks verified clean by PR #285 are graduated to `enforced: true` from a live run.
- **Decision 62 content:** Session E architecture (Claude Code cron -> EC2 runner -> dq-latest.json PR -> auto-merge) is eliminated. DQ runs as part of `validate.py`'s presubmit tier on the EC2 self-hosted runner with SSO credentials. No scheduling concern separate from validation itself. Reference: `docs/INTENT-dq-enforcement.md` Decision Registry, `docs/INTENT-validation-architecture.md`.
- **Post-merge:** After this PR merges: (1) update `docs/INTENT-dq-enforcement.md` Phase Overview table (Phase 3 Status -> COMPLETE, fill Plan and PR fields) on a separate `chore/dq-status-phase-3` branch per the INTENT's agent instructions; (2) run `python -m scripts.build_lambda --deploy` to refresh environment parity (the DQ YAMLs land in the zip via `config/` bulk copy but are not read by any Lambda handler). Neither is part of this implementation.
- **Phase 4 dependency:** Phase 4 (Data Quality Resolution) cannot begin until this PR merges. Phase 5 (Convergence) cannot begin until Phase 4 completes.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/INTENT-dq-enforcement.md` read in full
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (verify Decision 61 is the current last; new entry is Decision 62)
- [ ] All files in Scope table located and readable
- [ ] `scripts/data_quality_runner.py` - understand all `_compile_column_test` branches (str form, dict `accepted_values`, `relationships`, `expression`, `not_null` dict, `unique` dict) and `load_checks` table-level branches (`row_count`, `recency`)
- [ ] `tests/test_verifiers/test_data_quality.py::test_verify_missing_file` read - confirm it currently asserts `SKIPPED/ADVISORY` (the behavior being changed)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Wave 1: Python changes (commit before YAML annotation)

1. **Modify `scripts/data_quality_runner.py`** - four coordinated changes in one file edit:
   - Add `enforced: bool = True` to `Check` dataclass (after `severity` field)
   - In `load_checks`: add `enforced` read for `row_count` (`rc.get("enforced", True)`) and `recency` (`rec.get("enforced", True)`) table-level blocks; pass to `Check(..., enforced=enforced)`
   - In `_compile_column_test`: all dict-form branches read `enforced = params.get("enforced", True)` and pass it; bare-string (`isinstance(test, str)`) branches keep `enforced=True` default
   - In `_save_latest_result`: add `"checks"` key to the summary dict - list of `{"table": r.check.table, "column": r.check.column, "test": r.check.test_type, "verdict": r.verdict}` for each result; field name is `"test"` (not `"test_type"`)
   - In `run_checks` verdict aggregation (lines ~457-462): change `has_fail` to only count results where `r.verdict == "FAIL" and r.check.enforced`; `severity: warn` checks are already advisory (verdict is WARN not FAIL) so no special case needed

2. **Modify `tests/test_data_quality_runner.py`** - add tests for the four changes:
   - Test `Check` dataclass has `enforced=True` default
   - Test loader reads `enforced: false` from dict-form YAML test; defaults to `True` for bare-string form
   - Test `_save_latest_result` output contains `checks` array with correct schema (`table`, `column`, `test`, `verdict`); `column` is `None` for table-level checks
   - Test `run_checks` with a mix of `enforced=True` FAIL and `enforced=False` FAIL: aggregate verdict is FAIL only for enforced=True failures; enforced=False failures are present in results but do not drive aggregate

3. **Modify `scripts/verifiers/data_quality.py`** - one-line change: replace the missing-file return block (lines ~41-47) so `status=VerifierStatus.FAIL, severity=VerifierSeverity.HARD_GATE` instead of `SKIPPED/ADVISORY`; update the message to say "missing" not "missing."

4. **Modify `tests/test_verifiers/test_data_quality.py`** - update `test_verify_missing_file`: change assertions from `VerifierStatus.SKIPPED` / `VerifierSeverity.ADVISORY` to `VerifierStatus.FAIL` / `VerifierSeverity.HARD_GATE`

5. **Modify `scripts/validate.py`** - add graduation guard function:
   - New function `_check_graduation_guard(failed: list) -> None` (or inline in the presubmit path)
   - Reads `git diff HEAD -- config/data_quality/` to find changed YAML lines
   - Parses flips: `enforced: false` -> `enforced: true` transitions
   - Reads `logs/debug/dq-latest.json`; if missing or no `checks` key, emit warning and return (no block)
   - For each flip: look up `(table, column, test)` tuple in checks array; if verdict is FAIL, append to `failed` list with message; if verdict is SKIP, warn but do not block
   - For new checks added as `enforced: true` directly: same lookup and block logic
   - Guard is skipped when `--quick` flag is active; add note to output: "Note: --quick skips the enforced graduation guard"
   - Wire into the presubmit path (not the `--quick` path)

6. **Modify `tests/test_validate.py`** - add graduation guard test class with cases:
   - Blocks flip from `enforced: false` to `enforced: true` when verdict is FAIL
   - Allows flip when verdict is PASS
   - Warns but does not block when `dq-latest.json` is missing
   - Warns but does not block when `checks` array absent from `dq-latest.json`
   - Treats SKIP verdict as inconclusive (warn, no block)
   - Blocks new check added directly as `enforced: true` when verdict is FAIL
   - `--quick` flag skips guard entirely

7. **Modify `docs/DECISIONS.md`** - add Decision 62 before Decision 61 (most-recent-first ordering):
   - Title: No separate DQ scheduled routine (Session E elimination)
   - Status: Decided, Date: 2026-05-06
   - Content per the `[DECIDED]` entry in `docs/INTENT-dq-enforcement.md` Decision Registry

8. **Commit Wave 1 on branch:**
   ```
   git add scripts/data_quality_runner.py scripts/verifiers/data_quality.py scripts/validate.py docs/DECISIONS.md tests/test_data_quality_runner.py tests/test_verifiers/test_data_quality.py tests/test_validate.py
   git commit -m "feat(dq-ratchet-phase-3): runner infrastructure, verifier fix, graduation guard, Decision 62"
   ```

### Wave 2: YAML annotation (after live DQ run)

9. **Run DQ runner to get current check verdicts:**
   ```
   .venv/Scripts/python.exe -m scripts.data_quality_runner
   ```
   This populates `logs/debug/dq-latest.json` with the new `checks` array. If SSO is unavailable, stop here - do not proceed to YAML annotation.

10. **Read `logs/debug/dq-latest.json` `checks` array** - review the `(table, column, test, verdict)` tuples. Map: `"FAIL"` -> `enforced: false`, `"PASS"` -> `enforced: true`. Do not annotate checks with verdict `"SKIP"` or `"WARN"` (non-error severity checks do not need `enforced` at all).

11. **Modify `config/data_quality/ops.yaml`** - annotate every `severity: error` check:
    - Dict-form tests: add `enforced: true/false` as a sibling of existing params
    - Bare-string tests that are PASS: leave as bare strings (loader defaults to `enforced: true`)
    - Bare-string tests that are FAIL: convert to dict form and add `enforced: false  # brief reason`
    - Table-level (`row_count`, `recency`): add `enforced: true/false` as sibling of threshold params
    - Every `enforced: false` line must have an inline `#` comment on the same line

12. **Modify `config/data_quality/telemetry.yaml`** - same annotation protocol as ops.yaml

13. **Verify annotation completeness:**
    ```
    grep -n "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml | grep -v "#"
    ```
    Expected: zero lines. If any unannotated lines exist, add inline `#` comments before proceeding.

14. **Commit Wave 2 on branch:**
    ```
    git add config/data_quality/ops.yaml config/data_quality/telemetry.yaml
    git commit -m "feat(dq-ratchet-phase-3): YAML annotation - all severity:error checks annotated with enforced field"
    ```

### Final

15. **Execute Verification Plan** - run each VP step in order. Loop until all pass. If VP6 (dry-run check count) shows a mismatch, a YAML form is not being parsed - check `load_checks` for that test form.

16. **Report:** what was implemented, verification results, any YAML checks that required special handling (e.g., bare-string conversions, ambiguous category A vs B decisions).

## Work Areas (STRATEGIC plans only)
N/A - IMPLEMENTATION plan.
