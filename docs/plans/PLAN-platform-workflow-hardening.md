# Plan

## Intent
Surgically harden five resurfacing workflow friction points: block STRATEGIC plans from the
executor until telemetry tables are confirmed operational, fix the Gemini CLI trust-workspace
failure, make the plan-critique gate accept explicitly-deferred Lambda deployment steps,
stop tracking the active-session log in git, and make AWS profile resolution consistent
in the DQ runner and sync_recommendations. All five changes directly reduce workflow
interruption cost for the sole developer iterating on the self-improving trading system.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-workflow-hardening

## Phase
Phase 1: Core Infrastructure (complete) -- Platform parallel track (ongoing)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.gitignore` | Modify | Add `logs/.telemetry-active-session.json` to stop merge conflicts on the active-session file (point 4) |
| `CLAUDE.md` | Modify | Add "Temporary Operational Constraints" block -- no STRATEGIC plans + DEFERRED Lambda pattern (points 1, 3) |
| `docs/DECISIONS.md` | Modify | Add Decision 67 -- Lambda deployment deferred pending telemetry table readiness (point 3) |
| `scripts/llm_client.py` | Modify | Pass `GEMINI_CLI_TRUST_WORKSPACE=true` in subprocess env for `_gemini_call` (point 2) |
| `.claude/skills/plan-critique/SKILL.md` | Modify | Update step 12b (DEFERRED exception) + add step 12d (STRATEGIC block gate) when Decision 67 is active (point 3) |
| `.agents/skills/plan-critique/SKILL.md` | Modify | Mirror identical step 12b and 12d changes (Decision 58: `.agents/` is canonical interactive layer) |
| `scripts/data_quality_runner.py` | Modify | Add `--profile` CLI arg + `AWS_PROFILE` / `AWS_DEFAULT_PROFILE` / `company-aws-profile` fallback chain (point 5, rec-631) |
| `scripts/sync_recommendations.py` | Modify | Remove redundant `os.environ["AWS_PROFILE"]` mutation at line 166 (point 5, rec-658) |

## Bundled Recommendations
- **rec-631**: data_quality_runner: resolve AWS profile without requiring AWS_PROFILE env var (High, S)
- **rec-658**: sync_recommendations: remove redundant os.environ AWS_PROFILE mutation (Medium, XS)

## Acceptance Criteria
- [ ] `git check-ignore -v logs/.telemetry-active-session.json` reports the file as ignored
- [ ] `CLAUDE.md` contains a "Temporary Operational Constraints" section with both the STRATEGIC plan block and the DEFERRED Lambda pattern
- [ ] `docs/DECISIONS.md` contains Decision 67 with `Status: Active` and an explicit reversal condition
- [ ] `grep -n "GEMINI_CLI_TRUST_WORKSPACE" scripts/llm_client.py` returns a match on the `subprocess.run` env kwarg
- [ ] Running a Gemini CLI call via `llm_client.py` exits with code 0 (not 55) without any manual env var set
- [ ] `.claude/skills/plan-critique/SKILL.md` step 12b references Decision 67 and the DEFERRED exception; step 12d blocks STRATEGIC plans when Decision 67 is active
- [ ] `.agents/skills/plan-critique/SKILL.md` contains identical step 12b and 12d changes
- [ ] `python -m scripts.data_quality_runner --help` shows a `--profile` argument
- [ ] Running `python -m scripts.data_quality_runner --dry-run` without `AWS_PROFILE` set in the shell resolves the `company-aws-profile` profile and does not raise `Unable to locate credentials`
- [ ] `grep "os.environ\[.AWS_PROFILE.\]" scripts/sync_recommendations.py` returns no match

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Confirm .gitignore covers active-session file | `git check-ignore -v logs/.telemetry-active-session.json` | Prints the matching rule from `.gitignore` | Add `logs/.telemetry-active-session.json` entry to `.gitignore` |
| 2 | pre-deploy | Confirm CLAUDE.md temporary constraints block exists | `grep -c "Temporary Operational Constraints" CLAUDE.md` | Prints `1` | Re-apply the CLAUDE.md edit |
| 3 | pre-deploy | Confirm Decision 67 is present and active | `grep -A5 "Decision 67" docs/DECISIONS.md \| head -10` | Shows Decision 67 with `Status: Active` | Re-apply the DECISIONS.md edit |
| 4 | pre-deploy | Confirm trust env var is set in subprocess call | `grep -n "GEMINI_CLI_TRUST_WORKSPACE" scripts/llm_client.py` | Line number in `_gemini_call` subprocess.run env kwarg | Re-apply the llm_client.py edit |
| 5 | pre-deploy | Confirm Gemini CLI exits 0 with trust env active | `.venv/Scripts/python.exe -c "from scripts.llm_client import _gemini_call; r = _gemini_call('say: ok', model=None, tools=False, timeout=60, purpose='smoke', session_id='test', check=False); print('exit:', r.exit_code)"` | `exit: 0` (not 55) | Verify `GEMINI_CLI_TRUST_WORKSPACE` is in subprocess env dict |
| 6 | pre-deploy | Confirm both plan-critique SKILL.md files have DEFERRED exception | `grep -c "Decision 67" .claude/skills/plan-critique/SKILL.md && grep -c "Decision 67" .agents/skills/plan-critique/SKILL.md` | Both print `1` | Re-apply the SKILL.md edits |
| 7 | pre-deploy | Confirm --profile arg is present in DQ runner | `.venv/Scripts/python.exe -m scripts.data_quality_runner --help 2>&1 \| grep -i profile` | Shows `--profile` in usage | Re-apply the data_quality_runner.py edit |
| 8 | pre-deploy | Confirm DQ runner resolves profile without AWS_PROFILE | `cmd /c "set AWS_PROFILE= && .venv/Scripts/python.exe -m scripts.data_quality_runner --dry-run 2>&1 \| head -5"` | No `Unable to locate credentials` error; shows profile resolution or dry-run output | Check fallback chain logic in data_quality_runner.py |
| 9 | pre-deploy | Confirm env mutation removed from sync_recommendations | `grep -c "os.environ\[.AWS_PROFILE.\]" scripts/sync_recommendations.py` | Prints `0` | Re-apply the sync_recommendations.py edit |

## Constraints
- No changes to Lambda infrastructure, Terraform, or `.github/agents/` (dispatcher remains disabled)
- `CLAUDE.md` Temporary Operational Constraints section must be clearly annotated with reversal condition to avoid permanent entrenchment
- Decision 67 must reference both the STRATEGIC plan block and Lambda deployment deferral as a single coupled decision (both reverse together when telemetry is confirmed)
- `data_quality_runner.py` fallback chain must be: `--profile` arg > `AWS_PROFILE` env > `AWS_DEFAULT_PROFILE` env > `company-aws-profile` hard default. Do not use `os.environ` mutation.
- `sync_recommendations.py` rec-658 fix: remove only the `os.environ["AWS_PROFILE"] = args.profile` mutation at line 166; do not alter the existing profile fallback chain at lines 64/118
- No rescue agents or workaround loops (Decision 55)

## Context
- Decision 66 (Precision Context Injection) was added in the most recent merge -- Decision 67 follows
- `scripts/llm_client.py` is in `_LAMBDA_SCRIPTS` (build_lambda.py line 43); this plan's own Lambda-packaged file changes are covered by the DEFERRED pattern established here
- `config/` is fully Lambda-packaged (build_lambda.py line 71); this is why any config change triggers plan-critique step 12b -- the detection is correct, only the enforcement mode changes when Decision 67 is active
- `.claude/skills/plan-critique/SKILL.md` is used by `run_skill.py`; `.agents/skills/plan-critique/SKILL.md` is the canonical interactive layer per Decision 58. Both must be updated. The two files differ only in context file references (`docs/PROJECT_CONTEXT.md` vs `.github/copilot-instructions.md`) -- do not normalise this divergence here.
- rec-507 (closed) removed the JSONL log files from git tracking; `.telemetry-active-session.json` uses `.json` extension and was not covered by the `logs/.telemetry-*.jsonl` glob
- `boto3.Session()` at `data_quality_runner.py:540` creates a sessionless client; the fix is `boto3.Session(profile_name=_profile)` where `_profile` uses the fallback chain

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (confirm next decision number is 67)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **`.gitignore`** -- append `logs/.telemetry-active-session.json` after the existing `logs/.telemetry-*.jsonl` line (around line 112). One line addition.

2. **`CLAUDE.md`** -- insert the following block immediately after the `## Branching` section and before `## Memory policy`:
   ```
   ## Temporary Operational Constraints
   <!-- REVERSAL: Delete this entire section when (a) telemetry Athena tables confirmed
        operational end-to-end and (b) Lambda dispatcher re-enabled per the runbook below. -->
   - **No STRATEGIC plans:** The executor cannot safely action recs until telemetry tables
     are confirmed operational. All plans must be IMPLEMENTATION type until Decision 67 is reversed.
   - **Lambda deployment deferred (Decision 67):** The Lambda dispatcher is disabled. Plans
     touching Lambda-packaged files (`config/`, `scripts/llm_client.py`, `src/data/handlers/`,
     `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`) must include a
     `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test
     (pending Decision 67 reversal)` execution step in lieu of active deployment steps.
   ```

3. **`docs/DECISIONS.md`** -- insert Decision 67 at the top of the file (most-recent-first order), after the `# Decisions` header but before Decision 66:
   ```
   ## Decision 67: Lambda Deployment and STRATEGIC Plan Execution Deferred Pending Telemetry Readiness (Active - Temporary)

   **Status:** Active -- remove when reversal condition is met
   **Reversal condition:** Telemetry Athena tables (`telemetry_sessions`, `telemetry_process_events`,
   `telemetry_model_calls`, `telemetry_phases`, `telemetry_steps`) confirmed operational end-to-end
   with passing data quality checks AND Lambda dispatcher re-enabled per the CLAUDE.md runbook.

   **Effect on planning:**
   - STRATEGIC plans are blocked. All plans must be IMPLEMENTATION type.
   - Plans touching Lambda-packaged files must include a
     `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test
     (pending Decision 67 reversal)` step instead of active deployment steps.

   **Effect on plan-critique:** Step 12b accepts the DEFERRED marker pattern rather than
   recommending REVISE. Outputs a WARN noting the deferred deployment.

   **Rationale:** The executor telemetry pipeline (telemetry_sessions etc.) is not yet confirmed
   operational. Running executor-mediated recs risks silent telemetry loss. Lambda dispatcher
   is separately disabled pending telemetry confirmation and scheduled-agent migration completion.
   Both gates reverse together.
   ```

4. **`scripts/llm_client.py`** -- in `_gemini_call`, add `env={**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"}` to the `subprocess.run` call. The call currently has no `env` kwarg; add it as the last keyword argument before the closing parenthesis.

5. **`.claude/skills/plan-critique/SKILL.md`** and **`.agents/skills/plan-critique/SKILL.md`** --
   apply the same two changes to both files:

   a. Replace step 12b entirely with:
   ```
   12b. **Lambda deployment completeness (IMPLEMENTATION plans only):** If any file in the
   Scope table is Lambda-packaged (under `src/data/handlers/`, `.github/agents/schedule.yaml`,
   `.github/prompts/scheduled/`, `config/`, or in `_LAMBDA_SCRIPTS` in
   `scripts/build_lambda.py`), the Ordered Execution Steps MUST include: (a) a
   `build_lambda.py --deploy` step, (b) a smoke-test step using
   `run_scheduled_agent.py --smoke-test`, and (c) model ID validation against
   `docs/contracts/inference-provider.md` if model IDs are changed. If any are missing,
   recommend REVISE. Exception: if `docs/DECISIONS.md` contains an active Decision 67
   (Lambda deployment deferred pending telemetry readiness), a step explicitly marked
   `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test
   (pending Decision 67 reversal)` is acceptable in lieu of active deployment steps --
   output a WARN (not REVISE) noting the deferred deployment debt. Reference: Decision 47,
   Decision 67, Step 4 (Lambda Deployment Assessment) of plan.prompt.md.
   ```

   b. Add new step 12d immediately after step 12c:
   ```
   12d. **STRATEGIC plan gate:** If the plan's `## Plan Type` is `STRATEGIC` AND
   `docs/DECISIONS.md` contains an active Decision 67, recommend REVISE with:
   "STRATEGIC plans are blocked while Decision 67 is active (telemetry tables not yet
   confirmed operational). Convert to an IMPLEMENTATION plan or wait for Decision 67
   reversal."
   ```

   Note: `.agents/skills/plan-critique/SKILL.md` references `.github/copilot-instructions.md`
   where `.claude/skills/plan-critique/SKILL.md` references `docs/PROJECT_CONTEXT.md` --
   this is a pre-existing divergence, do not normalise it in this plan.

6. **`scripts/data_quality_runner.py`** -- three changes:
   a. Add `import os` at the top of the file (it is not currently present -- confirmed by grep).
      Find the function containing `boto3.Session()` (line ~540). Add a `profile_name: str | None = None`
      parameter to that function's signature. Replace the call with:
      ```python
      _profile = profile_name or os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE") or "company-aws-profile"
      session = boto3.Session(profile_name=_profile)
      ```
   b. In `main()` argument parser: add:
      ```python
      parser.add_argument("--profile", default=None, metavar="PROFILE",
                          help="AWS SSO profile name (default: AWS_PROFILE env, then company-aws-profile)")
      ```
   c. In `main()`, pass `profile_name=args.profile` when calling the check-execution function.
      Do not use `os.environ` mutation anywhere in this change.

7. **`scripts/sync_recommendations.py`** -- remove the entire `if args.profile:` block at lines 165-166
   (both the guard and the mutation). The `args.profile` value is already forwarded through
   the explicit `profile=args.profile` parameter at the downstream call sites (lines 64/118);
   removing only line 166 would leave an empty guard block.

8. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** -- `scripts/llm_client.py` is a Lambda-packaged file (`_LAMBDA_SCRIPTS`, build_lambda.py:43). Lambda deployment is deferred until Decision 67 is reversed per the CLAUDE.md runbook. No action required now.

9. **Execute Verification Plan** -- run each VP step in order. Loop until all pass. If VP5 (Gemini smoke test) fails unrecoverably, stop and analyze root cause (Decision 55).

10. **Report:** what was implemented, VP results, rec-631 and rec-658 closure evidence.
