# Plan

## Intent
Close three post-Phase-4-session gaps in the DQ enforcement arc: wire the two DQ functions that exist
in validate.py but were never called back into the presubmit path (regression from PR #313); correct
the INTENT document's conflation of lifecycle state transitions with physical Iceberg deletion (a
semantic error that caused the PR #304 agent to believe it had deleted records it had only locally
removed); and remove stale tombstone entries and add the physical deletion protocol so future agents
know exactly how to destroy data when needed.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-intent-validate-wire

## Phase
Phase 1: Core Infrastructure (2 weeks) - COMPLETE (maintenance / gap-close)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-dq-enforcement.md` | Modify | Correct deletion vs lifecycle semantics; add three-step physical deletion protocol with NULL vs `''` predicate note; remove wrong "never use Iceberg DELETE" prohibition; update Phase 4 session map Wave 1/3/5 status |
| `config/data_quality/dq_tombstones.yaml` | Modify | Remove stale entries for rec-608 and rec-633 - both physically deleted 2026-05-09 via Athena DML DELETE + OPTIMIZE + VACUUM |
| `scripts/ops_data_portal.py` | Modify | Fix `drain_pending` except clause (~line 423): add `ValueError` so malformed outbox files are counted as `skipped` rather than propagating an unhandled exception |
| `docs/DECISIONS.md` | Modify | Document physical deletion precedent (rec-608/rec-633/rec-001/rec-002/null-id) and rationale for NOT adding a general portal delete function |
| `scripts/validate.py` | Modify | Wire `ensure_fresh_dq_results(failed)` then `validate_verification_harness(failed)` into the presubmit execution path - both functions were written with docstrings saying "called during presubmit tier" but have no call sites (regression from PR #313 two-tier consolidation) |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `python -m scripts.validate` (presubmit) output includes `=== Verification Harness (V3) ===` with a DataQualityVerifier result line
- [ ] `python -m scripts.validate --pre` does NOT invoke the DQ runner or verification harness (edit-loop tier unchanged)
- [ ] `drain_pending` in `ops_data_portal.py` except clause reads `(ValidationError, ValueError, OSError)`
- [ ] `config/data_quality/dq_tombstones.yaml` contains no entries for rec-608 or rec-633
- [ ] `INTENT-dq-enforcement.md` Phase 4 session map shows Wave 1: COMPLETE (PR #309), Wave 3: COMPLETE (PR #307), Wave 5: note referencing #299 temporal gate
- [ ] `INTENT-dq-enforcement.md` "Bootstrapping Causal Chain" section no longer contains the text "Correct deletion sequence" conflating status transitions with deletion; contains the three-step physical deletion protocol instead
- [ ] `DECISIONS.md` contains a new decision entry for physical deletion precedent
- [ ] `ops_recommendations` DQ run returns 18/18 PASS after all changes

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | Confirm DQ functions appear as both definitions AND call sites, neither inside `if args.pre:` block | `grep -n "ensure_fresh_dq_results\|validate_verification_harness" scripts/validate.py` | Each name appears on a `def` line and separately on a bare call line; no call appears before line where `scope = "all"` is set | Add the two calls to the presubmit execution block in `main()` |
| 2 | pre-deploy | Confirm edit-loop tier (`--pre`) does not invoke DQ | `.venv/Scripts/python.exe -m scripts.validate --pre 2>&1 \| grep -c "Verification Harness"` | Prints `0` | Ensure the two new calls are placed after the `if args.pre: ... sys.exit(...)` block, not inside it |
| 3 | pre-deploy | Confirm `drain_pending` except clause catches `ValueError` | `grep -n "except.*ValidationError" scripts/ops_data_portal.py` | Line reads `except (ValidationError, ValueError, OSError)` | Fix the except clause at the identified line |
| 4 | pre-deploy | Confirm tombstone entries removed | `grep -c "rec-608\|rec-633" config/data_quality/dq_tombstones.yaml` | Prints `0` | Remove the stale YAML blocks |
| 5 | pre-deploy | Confirm INTENT Wave 1/3 status updated | `grep -E "wave-1\|wave-3\|Wave 1\|Wave 3" docs/INTENT-dq-enforcement.md` | Both waves show COMPLETE with PR number references | Update the Phase 4 session map table |
| 6 | pre-deploy | Confirm old wrong deletion protocol text is gone | `grep -n "Correct deletion sequence\|never use.*Iceberg DELETE" docs/INTENT-dq-enforcement.md` | Zero matches | Rewrite the "Bootstrapping Causal Chain" section |
| 7 | pre-deploy [V3] | Run presubmit and confirm Verification Harness section fires with DataQualityVerifier result | `.venv/Scripts/python.exe -m scripts.validate 2>&1 \| grep -A 10 "Verification Harness"` | Section appears; DataQualityVerifier shows `[PASS]`, `[SKIPPED]`, or `[ADVISORY]` (SSO-dependent) but NOT absent | Wire `ensure_fresh_dq_results` + `validate_verification_harness` into `main()` execution path |
| 8 | pre-deploy | Confirm ops_recommendations DQ still passes after all changes | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml --table ops_recommendations 2>&1 \| grep "Data Quality:"` | `Data Quality: PASS` | Investigate regression; data was 18/18 PASS at session start |

## Constraints
- No STRATEGIC plans (Decision 67 active - executor disabled pending telemetry confirmation)
- Lambda deployment deferred (Decision 67) - not in scope here
- `validate.py` is the single source of truth for CI checks; the two new call sites must mirror exactly what CI expects
- The `--pre` tier must remain fast (lint/format/prompts only) - DQ functions must NOT appear inside the `if args.pre:` block
- Physical deletion of Iceberg records was performed as a data action during this planning session (2026-05-09): rec-608, rec-633, rec-001, rec-002, and a null-id record. All five physically removed via Athena DML DELETE + OPTIMIZE + VACUUM. The plan documents this retroactively in DECISIONS.md.
- Only modify files explicitly in scope. The `_current` view SQL (no status filter) is intentional - `status=superseded` is a lifecycle state, not a deletion; the view correctly shows all records' latest state

## Context
- PR #304 (`83ec591`) committed "hard-deleted rec-608 and rec-633" but only removed them from local JSONL cache. The VP step prescribed `w._athena_execute()` - a non-existent method on OpsWriter. The Iceberg base table was never touched. Both records remained in Athena and fired HARD_GATE on every DQ run until the physical deletion performed today.
- PR #313 (`a1c05b8`, validate-two-tier consolidation) renamed `--integration` to no-flags presubmit but did not carry over the `ensure_fresh_dq_results` and `validate_verification_harness` call sites. Both functions survived with their docstrings intact but became dead code.
- `ops_recommendations_current` view has no `WHERE status NOT IN (...)` predicate - this is by design. The view materialises the latest SCD2 row per ID regardless of status. Filtering for active-only records is the query caller's responsibility, not the view's.
- Decision 65: `docs/dq/ops-recommendations-remediation-briefing.md` is a legacy artefact superseded by the ops.yaml extended contract. Do not load it.
- Decision 67: Lambda dispatcher disabled; no deployment steps needed here.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`docs/INTENT-dq-enforcement.md`** -- Rewrite the "Bootstrapping Causal Chain" section. Replace the "Correct deletion sequence" block (which conflates status=superseded with deletion) with two clearly separated subsections: (a) **Lifecycle state transition** -- `update_rec(id, {status: 'superseded'|'declined'})` marks a record's business state; the record remains in the SCD2 base table and `_current` view with its new status; used for recommendations that are closed/abandoned/superseded by newer work. (b) **Physical deletion protocol** -- three steps required to truly remove a record: (1) `DELETE FROM trading_formulas_db.ops_recommendations WHERE <predicate>` -- note that `WHERE id = ''` does NOT match `id IS NULL`; always use `WHERE id = '' OR id IS NULL` when targeting missing IDs; (2) `OPTIMIZE trading_formulas_db.ops_recommendations REWRITE DATA USING BIN_PACK` -- rewrites S3 data files to remove the deleted rows; skipping this step leaves the row bytes on S3 even though queries no longer return them; (3) `VACUUM trading_formulas_db.ops_recommendations` -- removes unreferenced snapshot and manifest files from S3; all three steps are required for complete physical removal. Remove the "Never use direct JSONL edits or Iceberg DELETE statements" prohibition -- replace with guidance: Iceberg DML DELETE is the correct tool for bootstrap/invalid records that cannot be logically closed (e.g., records with empty or invalid `status` that would fail Pydantic validation in `update_rec`). Update Phase 4 session map: Wave 1 -> COMPLETE (PR #309), Wave 3 -> COMPLETE (PR #307), Wave 5 -> add note that `exclude_before: '2026-05-01'` temporal gates were deployed in PR #299 making this wave effectively complete pending formal session tracking. Update `last_updated` field to 2026-05-09.
2. **`config/data_quality/dq_tombstones.yaml`** -- Remove the two stale YAML entries for `rec-608` and `rec-633`. Both records were physically deleted from Iceberg on 2026-05-09 via Athena DML DELETE + OPTIMIZE + VACUUM. The tombstone detection check is now vacuously satisfied (records absent from `_current` because they don't exist in the base table). Update the file header comment to note that tombstone entries should be removed once a record is physically deleted (physical deletion is the stronger guarantee; the tombstone check is only meaningful for records that still exist in Iceberg but should not appear in `_current`).
3. **`scripts/ops_data_portal.py`** -- In `drain_pending()`, locate the `except (ValidationError, OSError)` clause (~line 423). Change it to `except (ValidationError, ValueError, OSError)`. `ValueError` is raised by the OpsWriter backstop guard when a pending file has missing required fields; without this fix, the exception propagates unhandled rather than counting the file as `skipped` and logging the error cleanly.
4. **`docs/DECISIONS.md`** -- Add a new decision entry documenting: (a) Physical deletion of rec-608, rec-633, rec-001, rec-002, and one null-id record from `ops_recommendations` on 2026-05-09 (hollow bootstrap records that bypassed validation via the now-closed `append_jsonl -> s3_log_store` path from before PR #304); (b) Why physical deletion rather than `update_rec(status=superseded)` -- rec-001, rec-002, and the null-id record had empty/null `status` that would fail Pydantic `Literal` validation in `update_rec`; physical DELETE was the only viable path; (c) Decision NOT to add a general-purpose `delete_rec` function to `ops_data_portal` -- the portal's role is lifecycle management, not destruction; physical deletion should remain exceptional and deliberate; the DQ enforcement ratchet is the prevention mechanism; `_delete_postmortems_from_iceberg` remains private for its narrow use case.
5. **`scripts/validate.py`** -- In `main()`, after the prompts validation block (`validate_prompt_compliance(failed)`) and before the `print(f"\n=== Validation Summary...")` line, add the two calls in order: `ensure_fresh_dq_results(failed)` then `validate_verification_harness(failed)`. These calls must be placed AFTER the `if args.pre: ... sys.exit(...)` block (which returns early) - placing them after means they are unreachable from `--pre`. No new helper functions needed. No changes to either function body.
6. **Execute Verification Plan** -- run each VP step in order. All eight steps must pass. Loop until pass. If VP step 7 (V3 Verification Harness) fails unrecoverably due to infrastructure issues outside this scope, stop and file a recommendation rather than bypassing.
7. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** -- `config/data_quality/dq_tombstones.yaml` is packaged into the Lambda deployment bundle (`data-pipeline.zip` via `scripts/build_lambda.py`). The tombstone removal takes effect in the Lambda environment only after a redeploy. Until Decision 67 is reversed the Lambda dispatcher is disabled, so this has no operational impact; the DEFERRED step is recorded here to prevent the debt from being lost.
8. **Report** -- what was changed in each file, VP results, and confirmation that ops_recommendations DQ remains 18/18 PASS.
