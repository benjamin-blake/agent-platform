# Plan

## Intent
Make `python -m scripts.validate --ci` exit 0 again on a fresh feature branch by addressing the systemic drift introduced when commit 852ea71 (PR #287, fix-postmortem-bleed) added a postmortem-presence preflight gate to `_execute_recommendation_inner`, and prevent recurrence by adding a `validate --ci` preflight gate to the `/implement` workflow. This restores the autonomous-improvement feedback loop (the North Star) by re-establishing reliable CI signal and closing the meta-gap that PR #289's incomplete cleanup left behind.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/rec-610-systemic-drift

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/execute_recommendation.py` | Modify | Add `PYTEST_CURRENT_TEST` early-return guard to `_is_poisoned_rec()` (pattern from commit 723be18 / rec-419) so production code does not consult global JSONL state during pytest runs. |
| `tests/test_execute_recommendation.py` | Modify | (a) Add a unit test asserting `_is_poisoned_rec()` returns False when `PYTEST_CURRENT_TEST` is set, regardless of postmortem state. (b) Remove the now-redundant `monkeypatch.setenv("ALLOW_POISONED_RECS","true")` band-aid in `test_review_gate_blocking_findings_fails_before_finalize` that PR #289 introduced for rec-608. |
| `.claude/commands/implement.md` | Modify | Add a `python -m scripts.validate --ci` step to the Preflight section before plan acceptance. On non-zero exit, file each failed check as a recommendation via the portal, surface a go/no-go to the human, and STOP if no-go. Decision 57 SSO-skip discipline applies. |
| `.claude/skills/implement/SKILL.md` | Modify | Document the new preflight gate in the "Preflight Constraints" section: when the gate fires, the FAIL contract (rec-file + STOP), and the SSO-unavailable disposition (skip with actionable guidance, no crash). |

## Bundled Recommendations
- **rec-610** (umbrella, closed by completion of this plan) — three preexisting blockers from commit 852ea71.
- **rec-613** (subsumed, closed by Step 1) — "5 additional test failures with same root cause"; actual count is 17 and all are addressed by the structural guard.
- **rec-607** (closed as already-addressed) — the SLOC-limit symptom no longer fires; `scripts/ops_data_portal.py` already has `# complexity-waiver: decision-43` on line 1 (added by PR #289 as an out-of-scope inline fix). No code change required, status update only.

Out of scope, deferred to follow-up plans:
- **rec-605** + **rec-609** -> bundle into `agent/rec-605-data-pipeline` (V3, terraform apply for `ops_recommendations_current` view + Pydantic robustness against list-as-string Athena columns).
- **rec-611** -> separate small plan (portal `--automatable` CLI flag).
- **rec-612** -> separate triage (37 scheduled_agent_handler tests, possibly testing migrated/disabled code).

## Infrastructure Dependencies
None. No `.tf` files in scope; no Lambda packaging. Pure Python + workflow/skill prose changes.

## Acceptance Criteria
- [ ] All 281 tests in `tests/test_execute_recommendation.py` pass (zero failures, zero errors).
- [ ] `python -m scripts.validate --ci` exits 0 on this branch.
- [ ] `_is_poisoned_rec("rec-100")` returns False when `PYTEST_CURRENT_TEST` is set in the environment, regardless of JSONL postmortem state.
- [ ] A new unit test in `tests/test_execute_recommendation.py` covers the guard (test name pattern: contains `poisoned_rec_pytest_guard`).
- [ ] `.claude/commands/implement.md` Step 1 contains a literal `python -m scripts.validate --ci` invocation between the `session_preflight` call and plan acceptance, with documented FAIL handling.
- [ ] `.claude/skills/implement/SKILL.md` "Preflight Constraints" section documents the new gate, its FAIL contract, and the Decision 57 SSO-skip disposition.
- [ ] `rec-607`, `rec-610`, and `rec-613` show `status: closed` in `logs/.recommendations-log.jsonl` (via portal updates, not direct edits).
- [ ] The `monkeypatch.setenv("ALLOW_POISONED_RECS","true")` band-aid is removed from `test_review_gate_blocking_findings_fails_before_finalize`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Run the full `tests/test_execute_recommendation.py` suite to confirm all 17 previously-failing tests now pass and nothing regressed. | `.venv/Scripts/python.exe -m pytest tests/test_execute_recommendation.py -q --tb=no` | Exit 0. Output ends with `281 passed` (no failures, no errors). | <281 pass: inspect each failing test stack, confirm `_is_poisoned_rec` early-returns when `PYTEST_CURRENT_TEST` is set, ensure the guard is at function entry not later. If the new unit test fails, the guard logic is wrong; re-check os.environ.get vs literal comparison. |
| 2 | pre-deploy | Run the full presubmit gate (the same gate `/implement` will now invoke at preflight). | `.venv/Scripts/python.exe -m scripts.validate --ci` | Exit 0. Final line: `All checks passed.` | Non-zero exit: read the "Failed checks" list and address each. SLOC: confirm waiver header still on line 1. Schema: re-validate JSONL. Lint: run `ruff check --fix`. Test failures: return to VP1. |
| 3 | pre-deploy | Run the new unit test that proves the guard fires when `PYTEST_CURRENT_TEST` is set. | `.venv/Scripts/python.exe -m pytest tests/test_execute_recommendation.py -v -k poisoned_rec_pytest_guard` | `1 passed`. Test name visible in output. | 0 collected: the test name does not contain `poisoned_rec_pytest_guard` -- rename it. Test fails: the guard does not check `os.environ.get("PYTEST_CURRENT_TEST")` correctly. |
| 4 | pre-deploy | Verify the `/implement` workflow's Step 1 contains the new `validate --ci` gate within the Step 1 section (not just somewhere in the file). | `.venv/Scripts/python.exe -c "import re; c=open('.claude/commands/implement.md',encoding='utf-8').read(); m=re.search(r'## Step 1[\s\S]*?(?=^## Step 2)', c, re.MULTILINE); assert m, 'Step 1 boundary not found'; assert 'scripts.validate --ci' in m.group(0), 'validate --ci missing from Step 1'; print('PASS')"` | `PASS` printed. | Edit `.claude/commands/implement.md` Step 1 to add the literal command and FAIL contract before plan acceptance. |
| 5 | pre-deploy | Verify the `/implement` skill's "Preflight Constraints" section documents the new gate. | `.venv/Scripts/python.exe -c "import re; c=open('.claude/skills/implement/SKILL.md',encoding='utf-8').read(); m=re.search(r'## Preflight Constraints[\s\S]*?(?=^## )', c, re.MULTILINE); assert m, 'Preflight Constraints section not found'; section=m.group(0); assert 'validate --ci' in section, 'validate --ci gate not documented'; assert 'Decision 57' in section or 'SSO' in section, 'SSO-skip discipline missing'; print('PASS')"` | `PASS` printed. | Edit `.claude/skills/implement/SKILL.md` to add the preflight gate, FAIL handling, and SSO-skip disposition under "Preflight Constraints". |
| 6 | pre-deploy | Confirm rec-607, rec-610, rec-613 are all closed in the local JSONL cache (last-wins). | `.venv/Scripts/python.exe -c "import json; latest={}; \n[latest.update({e['id']:e}) for e in (json.loads(s) for s in open('logs/.recommendations-log.jsonl',encoding='utf-8') if s.strip() and not s.lstrip().startswith('#')) if e.get('id') in {'rec-607','rec-610','rec-613'}]; got={k:v.get('status') for k,v in latest.items()}; assert sorted(got.items()) == [('rec-607','closed'),('rec-610','closed'),('rec-613','closed')], got; print('PASS:', got)"` | `PASS: {'rec-607': 'closed', 'rec-610': 'closed', 'rec-613': 'closed'}` | Any not closed: run `.venv/Scripts/python.exe -m scripts.ops_data_portal --update-rec rec-XXX --status closed --resolution "..."` for each missing entry. Never edit the JSONL directly (Single Portal Invariant). |
| 7 | pre-deploy | Behavioural cross-check: confirm the band-aid was actually removed (rather than commented out) and no `ALLOW_POISONED_RECS` monkeypatch remains in the bypassed test. | `grep -nE "ALLOW_POISONED_RECS" tests/test_execute_recommendation.py \|\| echo "no_match"` | `no_match` (the grep finds zero hits in this file). | Match found: open the file at the matched line and remove the monkeypatch + its preamble comment. Re-run VP1 to confirm the test still passes via the structural guard. |

## Constraints
- **INTENT-validation-architecture.md**: do **not** add a third execution surface to `validate.py`. The /implement preflight gate must call the existing default presubmit tier via its `--ci` alias (will become flagless after migration step 5 / rec-599). Adding a new "cheap subset" mode would violate Constraint 1 of the INTENT doc ("if an agent has to ask a human 'which flag should I use', the design has failed").
- **Decision 44 (Executor Self-Modification Boundary)**: every file in Scope is an executor-boundary file. This work proceeds via /plan -> /implement; the autonomous executor must not touch any of these.
- **Decision 55 (RCA-First Executor)**: a failed `validate --ci` at /implement preflight emits a structured RCA (file recs, surface to human), never a rescue agent.
- **Decision 57 (Interactive vs Autonomous SSO)**: the new gate must skip with actionable guidance when SSO is unavailable, not crash. Pattern: existing `ensure_fresh_dq_results()` in `scripts/validate.py` already implements this disposition for the DQ runner.
- **Single Portal Invariant**: rec-607/rec-610/rec-613 closures go through `python -m scripts.ops_data_portal --update-rec`. Never `Edit` or `Write` to `logs/.recommendations-log.jsonl` directly (caught by `validate_rec_write_paths`).
- **No rescue agents or workaround loops** (Decision 55).
- **Windows compatibility**: subprocess invocations use `sys.executable`, pass `encoding="utf-8", errors="replace"` with `text=True`, list form not shell strings.
- **Plain ASCII only**. No emojis, no em-dashes -- Windows console encoding mangles em-dashes.

## Context
- **Trigger source**: commit 852ea71 (PR #287, fix-postmortem-bleed) added `_is_poisoned_rec()` and called it inside `_execute_recommendation_inner()`. The function calls `find_open_postmortem_for(rec_id)`, which reads global JSONL state. 17 tests in `tests/test_execute_recommendation.py` invoke `execute_recommendation("rec-100")` without mocking that lookup.
- **Why the gate fires**: the local JSONL contains `rec-606` (`source: executor-postmortem`, `status: open`, title: `Investigate executor failure for rec-100`). PR #287 declined `rec-100` itself but did not close `rec-606`. The gate filters on the postmortem's title (substring match for `failed_rec_id`), so rec-100's status is irrelevant; rec-606's open status is what trips it.
- **Cleanup misidentification**: PR #289 (b127bac, dq-validate-integration) closed rec-608 by adding `monkeypatch.setenv("ALLOW_POISONED_RECS","true")` to one specific test, then filed rec-613 stating "5 additional tests" had the same root cause. Actual count is 17 tests across `TestCheckpointing`, `TestStepTelemetryPersistence`, `TestPostValidationAcceptancePath`, `TestResumePostflight`, `TestWarmBaseAndAutoResume`, `TestDocOnlyValidationFallback`, and `TestPostflightValidationQuarantine`. The band-aid pattern would not have been sustainable at 17 monkeypatches and would have ossified the test-isolation defect.
- **Codebase precedent for the structural fix**: commit 723be18 (rec-419) added a `PYTEST_CURRENT_TEST` defensive guard to `write_run_summary()` for the same class of problem -- production code that consults global filesystem state breaking tests that don't mock it. The same pattern applies cleanly to `_is_poisoned_rec()`. This is not a code smell; it is the documented pattern in this repository for this exact failure mode.
- **Why the procedural gate matters**: rec-610's "key planning artefact" is the procedural recommendation that `/implement` should run `validate --ci` at preflight rather than discovering blockers at VP12 after code is written. The cost of running `--ci` once at session start (~5 min) is dramatically lower than the cost of a half-finished implementation that hits a CI blocker mid-session.
- **Out-of-scope state**: `sync_ops pull` is currently failing on `INVALID_VIEW: Column '_rn' is ambiguous` (rec-605). This blocks the latent rec-609 Pydantic schema bug from manifesting -- the bug only fires once rec-605's terraform apply lands and Athena writes list-typed columns into the local JSONL cache. Both go into the follow-up `agent/rec-605-data-pipeline` plan.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (current: `agent/rec-610-systemic-drift`).
- [ ] `docs/PROJECT_CONTEXT.md` read (loaded into planning session).
- [ ] `docs/DECISIONS.md` read (Decisions 43, 44, 55, 57 referenced).
- [ ] All files in Scope table located and readable (verified during planning).
- [ ] `docs/INTENT-validation-architecture.md` read (governs Q1 architectural decision).
- [ ] Acceptance Criteria understood and verifiable.

## Ordered Execution Steps
1. **Add the structural guard.** In `scripts/execute_recommendation.py`, modify `_is_poisoned_rec(rec_id: str)` to early-return `False` when `os.environ.get("PYTEST_CURRENT_TEST")` is truthy, before the `ALLOW_POISONED_RECS` check and before the `find_open_postmortem_for` lookup. Match the comment style of the existing pattern in `write_run_summary()` (commit 723be18). Update the docstring to mention the test-isolation contract.

2. **Add a unit test for the guard.** In `tests/test_execute_recommendation.py`, add a new test (name must contain `poisoned_rec_pytest_guard`) that:
   - With `PYTEST_CURRENT_TEST` set, asserts `_is_poisoned_rec("rec-100")` returns `False` (regardless of JSONL state).
   - With `PYTEST_CURRENT_TEST` unset *and* `ALLOW_POISONED_RECS` unset, monkeypatches `find_open_postmortem_for` to return a fake open postmortem dict, and asserts `_is_poisoned_rec("rec-100")` returns `True` (proving the guard does not over-broadly bypass).
   - Use `monkeypatch.delenv(..., raising=False)` and `monkeypatch.setenv(...)` for env management; use `monkeypatch.setattr` for `find_open_postmortem_for`.

3. **Remove the band-aid from rec-608's test.** In `tests/test_execute_recommendation.py::TestExecuteRecommendation::test_review_gate_blocking_findings_fails_before_finalize`, delete the 3-line preamble comment and the `monkeypatch.setenv("ALLOW_POISONED_RECS", "true")` line. Restore the test signature to `def test_review_gate_blocking_findings_fails_before_finalize(self):` if it was changed (parameter `monkeypatch` may still be needed if other monkeypatching exists in the test body -- verify before removing). Run the test alone to confirm it now passes via the structural guard.

4. **Add the procedural gate to the workflow.** In `.claude/commands/implement.md` Step 1 ("Run Preflight"), append a sub-step **after** the `session_preflight --open-session` call and **before** Step 2: invoke `python -m scripts.validate --ci`. Document the FAIL contract:
   - Non-zero exit -> parse the "Failed checks:" list, file each failed check as a recommendation via `python -m scripts.ops_data_portal --file-rec ...` with `automatable: false`, surface go/no-go to the human, STOP if no-go.
   - SSO-related failures (Decision 57) -> skip with actionable guidance, do not crash. Pattern reference: `ensure_fresh_dq_results()` in `scripts/validate.py`.

5. **Document the gate in the implement skill.** In `.claude/skills/implement/SKILL.md` under "## Preflight Constraints (Workflow Step 1)", add a new bullet after `outbox_synced: false`:
   - **`validate --ci` non-zero exit** -- The gate has detected pre-existing blockers on the branch. File each failed check as a recommendation via the portal (`automatable: false`), surface to human with go/no-go, STOP if no-go. SSO-unavailable -> skip with actionable guidance per Decision 57; do not crash.

6. **Close stale recs via the portal.** Run, in order:
   - `python -m scripts.ops_data_portal --update-rec rec-607 --status closed --resolution "Already addressed: scripts/ops_data_portal.py has '# complexity-waiver: decision-43' on line 1 (added by PR #289). validate_sloc_limits passes; no code change required."`
   - `python -m scripts.ops_data_portal --update-rec rec-613 --status closed --resolution "Subsumed by rec-610 structural fix: PYTEST_CURRENT_TEST guard in _is_poisoned_rec covers all 17 affected tests (rec-613 cited only 5). The band-aid pattern is no longer needed."`
   - `python -m scripts.ops_data_portal --update-rec rec-610 --status closed --resolution "Umbrella resolved by structural test-isolation guard (scripts/execute_recommendation.py) + procedural gate addition to /implement workflow + skill. Sub-recs disposition: rec-607 closed (already-addressed), rec-608 already closed (PR #289), rec-609 deferred to agent/rec-605-data-pipeline (latent until rec-605 lands)."`

   If the portal cannot reach DynamoDB, the writes queue to the outbox and drain on next preflight. The acceptance check (VP6) reads the local JSONL cache; the portal updates the cache directly even when offline.

7. **Execute the Verification Plan.** Run VP1-VP7 in order. Loop on any FAIL until all pass. If a VP step fails for an environment reason, attempt the documented recovery (e.g., `aws sso login --profile company-aws-profile`) and re-run; do not mark the step PASS without the actual command succeeding.

8. **Report.** Output the IMPLEMENTATION report per the implement skill: files changed, VP compliance table, code-review findings actioned, recs closed, and any out-of-scope discoveries (file new recs for them).
