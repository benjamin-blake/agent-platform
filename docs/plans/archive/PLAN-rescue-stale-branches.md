# Plan

## Intent
Rescue two stale branches (`agent/audit-ops-recs-dq-scalability` and `agent/verifier-sensor-suite`)
whose open PRs accumulated merge conflicts while main advanced. Both represent completed
implementation work that should have been merged by the `/implement` workflow. This plan brings
both to main to close the gap.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/rescue-stale-branches

## Phase
Phase Platform - verification system maturation (parallel to Phase 2 schema backfill).

## Scope

Files modified during execution span multiple branches. The implementing agent must check out each
rescue branch to perform the rebase and conflict resolution.

### On `agent/audit-ops-recs-dq-scalability`
| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Modify | Accept main's version (which has the Implementation Progress section tracking Sessions A/B) during rebase conflict resolution. |

### On `agent/verifier-sensor-suite`
| File | Action | Purpose |
|------|--------|---------|
| `logs/.telemetry-active-session.json` | Modify | Accept main's version (runtime session state, not logic). |
| `scripts/ops_writer.py` | Modify | Conflict resolution: accept main as base and apply any branch additions; main already has the SLOC waiver (`# complexity-waiver: decision-43`). |
| `scripts/verifiers/__init__.py` | Modify | Conflict resolution: merge both sides -- include main's registry entries AND the branch's new sensors (SchemaIntegrityVerifier, CausalChainVerifier). |
| `scripts/verifiers/harness.py` | Modify | Conflict resolution: merge both sides -- branch adds `--verifier` CLI flag; main may have independent harness changes. Keep both. |
| `scripts/verifiers/outbox_health.py` | Modify | Conflict resolution: branch rewrites stale-file logic (HARD_GATE >24h, ADVISORY 2-24h). Prioritise branch logic; absorb main's independent changes. |
| `tests/test_verifier_harness.py` | Modify | Conflict resolution: merge BOTH test sets -- never drop tests from either side. |

### On `agent/rescue-stale-branches`
| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/PLAN-rescue-stale-branches.md` | Create | This plan document. |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] PR #283 (`agent/audit-ops-recs-dq-scalability`) is in state MERGED.
- [ ] PR #277 (`agent/verifier-sensor-suite`) is in state MERGED.
- [ ] `scripts.validate --quick` exits 0 on the `verifier-sensor-suite` branch before its merge.
- [ ] `tests/test_sensors.py` and `tests/test_verifier_harness.py` both pass with no failures.
- [ ] `SchemaIntegrityVerifier` reports no Pydantic-to-Athena schema drift.
- [ ] `CausalChainVerifier` finds its nonce in Athena (end-to-end telemetry pipeline proven).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | Plan file has Implementation Progress section (audit-ops) | `grep -c "Implementation Progress" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `1` | Rebase conflict resolution took wrong side; re-apply `git checkout --theirs` |
| 2 | pre-deploy | PR #283 merged | `gh pr view 283 --json state --jq '.state'` | `"MERGED"` | Re-run `gh pr merge 283 --squash --delete-branch` |
| 3 | pre-deploy | Unit tests pass (verifier-sensor-suite branch) | `.venv/Scripts/python.exe -m pytest tests/test_sensors.py tests/test_verifier_harness.py -v` | All tests pass, 0 failures | Fix failing tests; re-run validate after each fix |
| 4 | pre-deploy | Full quick validation passes (verifier-sensor-suite branch) | `.venv/Scripts/python.exe -m scripts.validate --quick` | Exit 0 | Fix each reported failure; most pre-existing failures resolve automatically after rebase |
| 5 | pre-deploy | OutboxHealthVerifier runs without HARD_GATE | `.venv/Scripts/python.exe -m scripts.verifiers.harness --verifier OutboxHealthVerifier` | `PASS` or `ADVISORY` (not `HARD_GATE`) | Check `logs/.ops-outbox/` for files older than 24h; drain via `python -m scripts.ops_data_portal --drain` |
| 6 | post-deploy | SSO session active | `aws sts get-caller-identity --profile company-aws-profile` | Returns account `REDACTED-ACCOUNT-ID` | Run `aws sso login --profile company-aws-profile` then re-run |
| 7 | post-deploy | SchemaIntegrityVerifier finds no drift | `.venv/Scripts/python.exe -m scripts.verifiers.harness --verifier SchemaIntegrityVerifier` | `PASS` - no Pydantic-to-Athena column drift | Inspect reported drift; file recommendation if schema change is intentional |
| 8 | post-deploy | CausalChainVerifier proves end-to-end telemetry | `.venv/Scripts/python.exe -m scripts.verifiers.harness --verifier CausalChainVerifier` | `PASS` - nonce found in Athena within 60s | Check `telemetry_process_events_current` Athena view; if pipeline broken, STOP and file RCA |
| 9 | post-deploy | PR #277 merged | `gh pr view 277 --json state --jq '.state'` | `"MERGED"` | Re-run `gh pr merge 277 --squash --delete-branch` |

## Constraints
- Only modify the files listed in the Scope table.
- When resolving conflicts, never discard tests from either side -- merge both test sets.
- Use `git push --force-with-lease` (not `--force`) when updating the rescue branches.
- Do not re-implement anything from scratch; conflict resolution only.
- No rescue agents or workaround loops (Decision 55).
- If CausalChainVerifier (VP step 8) fails unrecoverably, stop and invoke the RCA skill rather than proceeding.

## Context
- **Why these branches stalled:** The `/implement` sessions that created these branches ended before Step 7 (commit flow). The branches were pushed and PRs created, but the session was abandoned before `gh pr merge` was called. Main continued to advance, causing the PRs to accumulate merge conflicts.
- **audit-ops plan file on main:** A later session added an "Implementation Progress" section to the plan file directly on main (tracking the Sessions A/B gap-fix PRs #285/#286). The branch has the original version. Resolution: accept main's version (`--theirs`) during rebase.
- **`logs/.telemetry-active-session.json`:** Always accept main's version -- this is runtime session state written at branch-creation time, not implementation logic.
- **verifier-sensor-suite CI failure (May 1):** Failed on validate-python due to pre-existing issues in `session_postflight.py`, `sync_ops.py`, `classify_risk.py`, `s3_log_store.py` (all since fixed on main), plus `ops_writer.py` SLOC violation (main already has the waiver). After rebasing onto main, most CI failures will vanish automatically. Only branch-specific failures (test failures in new files) require manual fixes.
- **`test_verifier_harness.py` exists on main:** Added by `agent/verifier-harness-orchestrator` (PR #276, merged 2026-05-01). The branch also adds tests to this file. Both test sets must be preserved.
- Decision 57: if SSO expires during V3 verification, run `aws sso login --profile company-aws-profile` and retry.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Confirm SSO is active** -- `aws sts get-caller-identity --profile company-aws-profile`. If expired, run `aws sso login --profile company-aws-profile` and confirm account `REDACTED-ACCOUNT-ID` before continuing.

2. **Rescue `agent/audit-ops-recs-dq-scalability` (PR #283)**
   - `git checkout agent/audit-ops-recs-dq-scalability`
   - `git rebase origin/main`
   - If conflict in `docs/plans/PLAN-audit-ops-recs-dq-scalability.md`: `git checkout --theirs docs/plans/PLAN-audit-ops-recs-dq-scalability.md && git add docs/plans/PLAN-audit-ops-recs-dq-scalability.md && git rebase --continue`
   - `git push --force-with-lease origin agent/audit-ops-recs-dq-scalability`
   - `gh pr merge 283 --squash --delete-branch`
   - Execute VP steps 1-2.

3. **Rescue `agent/verifier-sensor-suite` (PR #277) -- rebase and conflict resolution**
   - `git checkout agent/verifier-sensor-suite`
   - `git rebase origin/main` -- expect conflicts in 6 files
   - Resolve each file using the Scope table guidance:
     - `logs/.telemetry-active-session.json`: `git checkout --theirs`
     - `scripts/ops_writer.py`: accept main as base; verify the `# complexity-waiver: decision-43` header is present on line 1; apply any branch-specific additions that are not already on main
     - `scripts/verifiers/__init__.py`: manually merge -- read both versions, include registry entries from BOTH sides
     - `scripts/verifiers/harness.py`: manually merge -- read both versions; the branch adds `--verifier` argument filtering; preserve it alongside any main-side changes
     - `scripts/verifiers/outbox_health.py`: manually merge -- favour the branch's HARD_GATE/ADVISORY severity logic; absorb independent main-side changes
     - `tests/test_verifier_harness.py`: manually merge -- include ALL test methods from both sides; never drop a test
   - After each file is resolved: `git add <file>`
   - `git rebase --continue` (may need to repeat for each conflict commit in the rebase sequence)

4. **Fix remaining CI failures on `agent/verifier-sensor-suite`**
   - `.venv/Scripts/python.exe -m scripts.validate --quick`
   - Address any failures. Pre-existing failures from before the rebase should now be resolved automatically. Only branch-specific failures (new test files) require manual fixes.
   - Re-run validate until exit 0.

5. **Execute Verification Plan steps 3-5** (pre-deploy VP on `agent/verifier-sensor-suite`).

6. **Build and deploy Lambda** -- `scripts/ops_writer.py` is in `_LAMBDA_SCRIPTS` in `build_lambda.py`; any change to it requires a redeploy before V3 integration checks run.
   - `.venv/Scripts/python.exe -m scripts.build_lambda --deploy --profile company-aws-profile`
   - Confirm the deploy succeeds (exit 0) before continuing.

7. **Push and run V3 verification**
   - `git push --force-with-lease origin agent/verifier-sensor-suite`
   - Execute VP steps 6-8 (post-deploy; requires active SSO session; Lambda now reflects conflict-resolved `ops_writer.py`).

8. **Merge PR #277**
   - `gh pr merge 277 --squash --delete-branch`
   - Execute VP step 9.

9. **Execute Verification Plan** -- produce the full VP Compliance Table before merging this planning branch.

10. **Merge this planning branch**
   - `git checkout agent/rescue-stale-branches`
   - `git push origin HEAD`
   - `gh pr create --title "plan(rescue-stale-branches): rescue audit-ops and verifier-sensor-suite branches" --body "Rescue two stale branches left open due to session abandonment before commit flow. Both rebased, conflicts resolved, CI passing, V3 verification complete." --base main`
   - `gh pr merge --squash --delete-branch`
   - `git checkout main && git pull origin main`

11. **Report** -- state which PRs were merged, actual VP outcomes, any recs filed.
