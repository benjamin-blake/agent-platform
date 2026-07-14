# Plan

## Intent
Converge `scripts/validate.py` from its current five-flag world to the two-tier model
defined in Decision 60 (presubmit default + `--pre` edit-loop), and immediately
activate branch protection on `main` now that the self-hosted EC2 runner is stable.
This closes the last two open gates on the Decision 60 migration sequence (steps 4 and 5)
and hardens the merge process so CI is a required gate rather than an advisory.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/validate-two-tier

## Phase
Phase Platform: Automation Platform (Wave Control / Decision 60 migration step 4-5)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/validate.py` | Modify | Remove `--ci`, `--scope`, `--integration`, `--verifiers` flags; rename `--quick` -> `--pre`; make default scope always `"all"`; replace `--ci` branch-guard bypass with `CI` env-var check |
| `tests/test_validate.py` | Modify | Update `--quick` -> `--pre` in all test fixtures and assertions |
| `scripts/session_postflight.py` | Modify | Replace `["scripts/validate.py", "--ci"]` with `["-m", "scripts.validate"]` (no flag) |
| `scripts/execute_recommendation.py` | Modify | Replace `--ci` arg in `_validate_args` / `_validate_label` (executor boundary - human-reviewed) |
| `scripts/executor/step_runner.py` | Modify | Replace `"--quick"` with `"--pre"` in subprocess call (executor boundary) |
| `scripts/executor/acceptance_lint.py` | Modify | Update rejection rule: ban `--ci` -> ban `--pre` in acceptance commands; update help text (executor boundary) |
| `scripts/executor/formatters.py` | Modify | Update `--quick` comment reference (executor boundary) |
| `scripts/executor/postflight.py` | Modify | Update `--ci` log message reference (executor boundary) |
| `tests/test_execute_recommendation.py` | Modify | Update `"mode": "--ci"` fixture (executor boundary test) |
| `tests/test_executor_step_runner.py` | Modify | Update `--quick` -> `--pre` in mock side-effect list |
| `.github/workflows/ci.yml` | Modify | Change `python scripts/validate.py --ci` -> `python -m scripts.validate` (no flags); update header comment |
| `CLAUDE.md` | Modify | Update merge protocol: `--quick` -> `--pre`, remove `--ci`/`--scope all` references, update two-tier note |
| `GEMINI.md` | Modify | Replace `validate.py --ci` and `--scope all` references with `python -m scripts.validate` |
| `.claude/skills/implement/SKILL.md` | Modify | Replace `validate --ci non-zero exit` reference; ban `--pre` in acceptance commands instead of `--ci` |
| `.agents/skills/implement/SKILL.md` | Modify | Ban `--pre` in acceptance commands instead of `--ci`; update `--quick` reference |
| `.agents/workflows/implement.md` | Modify | Update `--quick` -> `--pre` |
| `.github/prompts/implement.prompt.md` | Modify | Ban `--pre` in acceptance commands instead of `--ci`; update `--quick` -> `--pre` |
| `.github/instructions/executor-planning.instructions.md` | Modify | Update `--ci` Windows gotcha (now moot since no --ci); update checklist item to ban `--pre` |
| `config/prompts/executor/planning.prompt.md` | Modify | Same as executor-planning.instructions.md (same content, two surfaces) |
| `docs/INTENT-validation-architecture.md` | Modify | Update end-state description: `--quick` -> `--pre`; update migration step 4/5 to mark complete |
| `docs/DECISIONS.md` | Modify | Amend Decision 60: change end-state flag name from `--quick` to `--pre`; record that the rename was an explicit user instruction at planning time (2026-05-09) |

## Bundled Recommendations
- rec-587 (Consolidate validate.py flags to two-tier model) -- directly implemented by this plan
- rec-599 (duplicate of rec-587) -- closed as superseded by this plan

Close via ops portal as part of execution:
- rec-598 (Stand up self-hosted runner -- done, PR #310)
- rec-586 (duplicate of rec-598 -- done)
- rec-schema-probe-001 (schema migration verification probe -- superseded)

## Acceptance Criteria
- [ ] `python -m scripts.validate --pre` runs lint/format/prompt checks only and exits in <= 30s
- [ ] `python -m scripts.validate` (no flags) runs full check suite and exits 0 on a clean branch
- [ ] `python scripts/validate.py --ci` exits non-zero (flag no longer exists)
- [ ] `python scripts/validate.py --quick` exits non-zero (flag renamed)
- [ ] `python scripts/validate.py --scope python` exits non-zero (flag removed)
- [ ] `.github/workflows/ci.yml` validate step calls `python -m scripts.validate` with no flags
- [ ] `pytest tests/test_validate.py -q` exits 0
- [ ] `pytest tests/test_executor_step_runner.py -q` exits 0
- [ ] Main branch protection enabled: `validate-python` + `terraform-validate` both required
- [ ] Five stale [FAILED] PRs (#167, #170, #194, #199, #248) closed

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Old flags rejected | `python -m scripts.validate --ci 2>&1; echo $?` | Exit non-zero (unrecognised argument) | Flag was not removed from argparse |
| 2 | pre-deploy | Old --quick rejected | `python -m scripts.validate --quick 2>&1; echo $?` | Exit non-zero (unrecognised argument) | Rename was not applied |
| 3 | pre-deploy | --pre runs quickly | `time python -m scripts.validate --pre 2>&1` | Lint + format + prompts only, exits 0, wall time <= 30s | Wrong checks included in --pre path |
| 4 | pre-deploy | Default runs full suite | `python -m scripts.validate 2>&1 \| tail -5` | `=== Validation Summary (scope: all) === All checks passed.` | Default scope not set to "all" |
| 5 | pre-deploy | test_validate passes | `python -m pytest tests/test_validate.py -q --tb=short 2>&1 \| tail -10` | All pass, 0 failed | --quick fixture not updated to --pre |
| 6 | pre-deploy | test_executor_step_runner passes | `python -m pytest tests/test_executor_step_runner.py -q --tb=short 2>&1 \| tail -10` | All pass, 0 failed | --quick not replaced with --pre in mock |
| 7 | pre-deploy | test_execute_recommendation passes | `python -m pytest tests/test_execute_recommendation.py -q --tb=short 2>&1 \| tail -10` | All pass, 0 failed | --ci mode fixture not updated |
| 8 | pre-deploy | CI workflow updated | `grep "scripts.validate" .github/workflows/ci.yml` | Shows `python -m scripts.validate` with no `--ci` | Workflow not updated |
| 9 | post-deploy | Branch protection active | `gh api repos/$(gh repo view --json nameWithOwner --jq .nameWithOwner)/branches/main --jq '.protection.enabled'` | `true` | API call not executed or failed |
| 10 | post-deploy | Required checks configured | `gh api repos/$(gh repo view --json nameWithOwner --jq .nameWithOwner)/branches/main/protection/required_status_checks --jq '.contexts'` | Contains `validate-python` and `terraform-validate` | Wrong check names used |

## Constraints
- Decision 44: `execute_recommendation.py`, `executor/*.py`, `tests/test_execute_recommendation.py`, `tests/test_executor_step_runner.py` are executor boundary files -- this plan is `/implement`-only, not executor-automatable
- Decision 67: No STRATEGIC plans. This is IMPLEMENTATION type
- Decision 60 step 4 ("freeze --quick surface with parity tests") is satisfied by running the existing test suite rather than writing new snapshot tests -- the executor already has comprehensive tests for `--pre` behavior via `test_validate.py`
- `config/prompts/executor/planning.prompt.md` is under `config/`, which is Lambda-packaged per CLAUDE.md; a DEFERRED Lambda deploy step is required per Decision 67
- Branch protection API call requires `gh auth` to be valid; confirm with `gh auth status` before step 10
- `docs/INTENT-validation-architecture.md` step 4/5 migration markers should be updated to DONE but the section deletion (step 7 of Decision 60) is deferred to a future plan

## Context
- Decision 60: Two-tier validation architecture migration sequence; this plan implements steps 4-5
- Decision 68: The 1-week stability observation window is waived by explicit user instruction during the 2026-05-09 planning session ("enable now, decision 68 was an agent decision as opposed to my own"); branch protection is enabled immediately in this plan
- Decision 44: Executor self-modification boundary enforced for all `executor/` files
- Decision 67: All plans must be IMPLEMENTATION type until telemetry tables confirmed operational
- The five stale PRs (#167, #170, #194, #199, #248) are executor-generated "[FAILED]" artifacts from before the runner was operational; closing them does not lose the underlying recs which remain open in the recommendations log
- rec-587 and rec-599 are duplicates covering this exact work
- `--scope auto` / `detect_scope()` / `get_changed_files()` become dead code after this change -- remove them
- The branch guard must remain but switch bypass condition from `not args.ci` to `os.environ.get("CI") == "true"` (GitHub Actions sets CI=true); without this CI runs on `push: branches: [main]` would fail
- `.antigravity/workflows/implement.md` is legacy/deep-frozen; update its `--quick` reference only if the file is explicitly in scope for this session, otherwise leave for Wave 5 cleanup
- `docs/CHANGELOG.md` does not require updating; it is a historical record
- `logs/debug/plan-gen-context-*.md` are debug artifacts; do not update them
- `docs/plans/*.md` containing `--quick` are historical plan files; do not update them

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Close stale PRs** -- run `gh pr close 167 170 194 199 248 --comment "Closing stale executor-failed PR; runner now operational. Rec remains open for re-execution."`

2. **Close recs via ops portal** -- call `python -m scripts.ops_data_portal` to close rec-598, rec-586, rec-schema-probe-001 (status=closed, resolution="Done: self-hosted runner live per PR #310"), and close rec-587, rec-599 (status=closed, resolution="Implemented by PLAN-validate-two-tier")

3. **Modify `scripts/validate.py`** -- apply all flag changes in a single edit:
   - Remove `--ci`, `--scope`, `--integration`, `--verifiers` from `argparse` and all call sites
   - Rename `--quick` -> `--pre` everywhere in this file
   - Remove `scope = "all" if args.ci else args.scope` logic; replace with `scope = "all"` unconditionally
   - Remove the `scope == "auto"` detection block (`get_changed_files`, `detect_scope` calls)
   - Delete `get_changed_files()` function entirely (now dead code, no tests reference it)
   - Delete `detect_scope()` function entirely (now dead code, no tests reference it)
   - Remove `get_changed_files()` and `detect_scope()` functions (now dead code)
   - Replace branch guard condition `if not args.ci:` with `if os.environ.get("CI") != "true":`
   - Remove the `--integration` path (`run_integration_checks`) and the function itself (or leave as dead code with a TODO if it has test coverage that would break)
   - Update the warning message that mentions `--scope all or --ci` (now unreachable, but if the auto-detection block is removed, this message goes with it)
   - Update help text and comments referencing old flags
   - Update `_DQ_FRESHNESS_SECONDS` comment if it references `--quick`
   - Update `Note: --quick skips the enforced graduation guard.` -> `Note: --pre skips the enforced graduation guard.`

4. **Modify `tests/test_validate.py`** -- find all `sys.argv = ["validate.py", "--quick"]` fixtures and rename to `"--pre"`; update any assertion strings that mention `"--quick"` or `"scope: quick"`

5. **Modify executor boundary Python files** (four files, one edit each):
   - `scripts/executor/step_runner.py:966`: `"--quick"` -> `"--pre"`
   - `scripts/executor/acceptance_lint.py:113`: update the rejection message and any internal check for `--ci` flag in acceptance commands (the lint rule should now flag `--pre` as invalid in acceptance commands, same reasoning: full suite too slow for acceptance)
   - `scripts/executor/formatters.py:114,235`: update comment references from `--quick` to `--pre`
   - `scripts/executor/postflight.py:1178`: update log message referencing `--ci`

6. **Modify `scripts/session_postflight.py`** -- update `run_validate()` function: replace `["scripts/validate.py", "--ci"]` with `["-m", "scripts.validate"]` (no --ci flag); update the docstring at line 118-124

7. **Modify `scripts/execute_recommendation.py`** -- update lines 2305-2306: replace `["--ci"]` with `[]` (empty list, no flags = full check); update `_validate_label` to `""` or `"presubmit"` accordingly

8. **Modify test files** (two files):
   - `tests/test_execute_recommendation.py:5329`: update `"mode": "--ci"` to `"mode": ""` or equivalent
   - `tests/test_executor_step_runner.py:1047`: update the `--quick` reference in the mock side-effect condition to `--pre`

9. **Modify workflow and instruction files** (bulk pass -- all are text/reference updates):
   - `.github/workflows/ci.yml`: line 2 comment + line 45 command
   - `CLAUDE.md`: merge protocol section (lines ~82-84)
   - `GEMINI.md`: lines 20 and 23
   - `.claude/skills/implement/SKILL.md`: lines 28 and 120
   - `.agents/skills/implement/SKILL.md`: lines 104 and 118
   - `.agents/workflows/implement.md`: line 73
   - `.github/prompts/implement.prompt.md`: line 139 and 219
   - `.github/instructions/executor-planning.instructions.md`: lines 52 and 94
   - `config/prompts/executor/planning.prompt.md`: lines 129 and 209
   - `docs/INTENT-validation-architecture.md`: update `--quick` -> `--pre` in end-state description; mark migration steps 4-5 as DONE

10. **Enable branch protection** via gh CLI:
    ```bash
    gh api repos/$(gh repo view --json nameWithOwner --jq .nameWithOwner)/branches/main/protection \
      --method PUT \
      --field required_status_checks='{"strict":false,"checks":[{"context":"validate-python","app_id":-1},{"context":"terraform-validate","app_id":-1}]}' \
      --field enforce_admins=false \
      --field required_pull_request_reviews=null \
      --field restrictions=null
    ```
    Confirm with: `gh api repos/.../branches/main --jq '.protection'`

11. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** -- `config/prompts/executor/planning.prompt.md` is Lambda-packaged; deploy and smoke-test are required but blocked until Decision 67 is reversed. Record this debt as a recommendation via the ops portal if the deferred step is reached.

12. **Execute Verification Plan** -- run each VP step in order. Fix any failure before proceeding to step 12. For VP step 9 and 10 (branch protection), run after the PR is merged rather than before -- branch protection verifies the final state.

13. **Report** -- what was changed, test results, branch protection status confirmation.
