# Plan

## Intent
Complete the ops_recommendations cleanup that three prior sessions initiated but did not
finish: diagnose why Athena DELETEs for rec-608 and the NULL-id ghost row did not take
effect, purge those rows with an assertion-bearing script, and investigate whether any
active write-path bypass continues to produce hollow records -- restoring data quality
verdict to PASS and adding a Class E root cause to the shared remediation taxonomy.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-ops-rec-rca-stuck-deletes

## Phase
Phase Platform (parallel track) -- DQ enforcement arc, post-wave-3 residual cleanup

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/cleanup_ops_rec_orphans.py` | Create | Assertion-bearing DELETE + VACUUM for known orphan IDs and NULL-id ghost rows; polls until SUCCEEDED; re-queries `ops_recommendations_current` to assert absence; documents the stuck-DELETE RCA in its module docstring |
| `tests/test_cleanup_ops_rec_orphans.py` | Create | Unit tests (mock boto3): dry-run path, DELETE SQL construction, post-assert failure, VACUUM invocation |
| `config/data_quality/decisions/ops_recommendations.yaml` | Modify | Update stale `current_test` for automatable/risk; set `last_verdict: PASS` for status/automatable/risk after purge; record RCA findings |
| `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | Modify | Add Class E (post-deploy cleanup step not executed or not asserted) to root cause taxonomy |

## Bundled Recommendations
None.

## Infrastructure Dependencies
None. No `.tf` files in scope. Athena DML is issued via `boto3`; VACUUM requires engine v3 -- `agent-platform-production` workgroup used throughout.

## Acceptance Criteria
- [ ] `SELECT count(*) FROM trading_formulas_db.ops_recommendations_current WHERE id IN ('rec-608', 'rec-633') OR id IS NULL` returns 0
- [ ] `python -m scripts.data_quality_runner` exits with `verdict: PASS` and `failed: 0` for all `ops_recommendations` checks
- [ ] `python -m scripts.sync_ops pull` completes with 0 new rows rejected for rec-608 or id=NULL
- [ ] Bypass audit (grep sweep) returns no active write paths outside the portal contract; or a follow-up rec is filed if one is found
- [ ] Decision manifest updated: status/automatable/risk `last_verdict: PASS`, Class E RCA documented
- [ ] `python -m scripts.validate` exits 0 (presubmit)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | [pre-deploy] | Enumerate current failing rows | `.venv/Scripts/python.exe -c "import boto3,time; s=boto3.Session(profile_name='company-aws-profile'); a=s.client('athena',region_name='eu-west-2'); eid=a.start_query_execution(QueryString=\"SELECT id, status, automatable, risk FROM trading_formulas_db.ops_recommendations_current WHERE status IS NULL OR automatable IS NULL OR risk IS NULL OR (created_timestamp IS NOT NULL AND last_updated_timestamp IS NOT NULL AND created_timestamp > last_updated_timestamp)\",WorkGroup='agent-platform-production',ResultConfiguration={'OutputLocation':'s3://bblake-platform-agent-logs/athena-scratch/'})['QueryExecutionId']; [time.sleep(2) for _ in range(30) if a.get_query_execution(QueryExecutionId=eid)['QueryExecution']['Status']['State'] not in ('SUCCEEDED','FAILED','CANCELLED')]; [print(r) for r in a.get_query_results(QueryExecutionId=eid)['ResultSet']['Rows']]"` | Lists rec-608, the NULL-id ghost row, and any additional violators | Confirm workgroup is agent-platform-production (engine v3); if FAILED check SSO |
| 2 | [pre-deploy] | Bypass audit | `grep -rn "OpsWriter\|append_jsonl\|_RECS_KEY" scripts/ tests/ --include="*.py" \| grep -v "ops_data_portal.py\|sync_ops.py\|ops_writer.py\|test_ops_writer\|test_sync_ops\|test_ops_data_portal"` | No unguarded write paths outside portal contract | File follow-up rec for any live bypass; continue with cleanup |
| 3 | [pre-deploy] | Unit tests for purge script | `.venv/Scripts/python.exe -m pytest tests/test_cleanup_ops_rec_orphans.py -v` | All 4 tests pass | Fix script or test logic before running live Athena DML |
| 4 | [post-deploy] | Dry-run purge | `.venv/Scripts/python.exe -m scripts.cleanup_ops_rec_orphans --dry-run` | Prints target row IDs without executing DELETE | If no output, VP step 1 found 0 violators -- skip step 5 and verify DQ directly |
| 5 | [post-deploy] | Execute purge | `.venv/Scripts/python.exe -m scripts.cleanup_ops_rec_orphans` | Prints `PURGE_COMPLETE: 0 orphan rows remain` | Verify Athena QueryExecution status is SUCCEEDED (not FAILED); confirm engine v3 workgroup; check Athena console for DML errors |
| 6 | [post-deploy] | Sync cache and confirm zero rejects | `.venv/Scripts/python.exe -m scripts.sync_ops pull 2>&1 \| grep -E "rejected\|pulled\|WARNING"` | `pulled N rows for ops_recommendations` with no rejection warnings for rec-608 or id=NULL | Re-run purge if rejections persist; investigate whether row is being re-staged from outbox |
| 7 | [post-deploy] | DQ runner full verdict | `.venv/Scripts/python.exe -m scripts.data_quality_runner && .venv/Scripts/python.exe -c "import json; d=json.load(open('logs/debug/dq-latest.json')); print(d['verdict'], d.get('failed',0), 'failed'); assert d['verdict']=='PASS' and d.get('failed',0)==0"` | Prints `PASS 0 failed` | Identify remaining violators from VP step 1 output and re-run purge for those IDs |

## Constraints
- No STRATEGIC plans (Decision 67)
- Lambda deployment deferred (Decision 67): no Lambda-packaged files in scope
- VACUUM requires engine v3 -- always use `WorkGroup='agent-platform-production'`; never `primary` workgroup
- Do not write to `logs/.recommendations-log.jsonl` directly; all rec updates go through `ops_data_portal`
- `test_coverage_checker` requires test files for all modified source files -- `tests/test_cleanup_ops_rec_orphans.py` is mandatory
- No rescue agents or workaround loops (Decision 55); if VP step 5 raises `AssertionError`, stop and analyze before retrying

## Context
- **Root cause of stuck DELETEs**: PR #304 ("hard-deleted rec-608/rec-633") deleted local S3 outbox files -- the rows were already drained to Athena before the plan ran, so no Athena DML was ever issued. VP Step 7 of PLAN-dq-write-enforcement-unification prescribed an inline DELETE one-liner for `id IS NULL`; the implementation commit (b6ba53b) message contains no evidence it was executed, and the ghost row persists in the warehouse today (confirmed rejected at preflight 2026-05-11T20:55 UTC).
- **Bypass investigation basis**: User reports suspicion that validation or testing infrastructure is bypassing the portal. Evidence: rec-001 was closed by a concurrent session (`agent/ci-merge-gate-hardening`) with a resolution that was not prescribed by the plan; rec-002 was superseded in a separate session on the same day. Current code analysis shows PR #323 closed all known write-path bypasses in Python source, but the findings_processor Lambda still runs pre-#323 code (Decision 67 defers deployment). Grep audit in VP step 2 is the live check.
- **`ops_recommendations_current` view**: both `sync_ops.py` (line 48) and `data_quality_runner.py` (line 142) query this view; the view uses SCD2 deduplication (max `last_updated_timestamp` per id). The ghost row has `id IS NULL`, which means it has no deduplication key and every version persists in the view -- explaining why it is rejected on every sync.
- **Latest DQ run (15:39 UTC 2026-05-11)** pre-dates all May 11 fixes (PR #323 at ~16:06 UTC, rec-001 close at 19:52 UTC); a fresh run is required to establish current state.
- **rec-001**: now `status: closed`, non-null in automatable/risk -- will not contribute to not_null FAILs after fresh DQ run.
- **rec-049**: last rejected 2026-05-08; has empty file/context/acceptance (not status/automatable/risk); sync filter rejects it but DQ runner passes it (empty string != NULL). Not a FAIL contributor; out of scope for this plan.
- **telemetry_agent_invocations_current** view is stale (VIEW_IS_STALE error at preflight) -- unrelated to this plan; rec exists for that issue.
- Decision 67 must be reversed before the findings_processor Lambda guard (PR #323, Step 6 of implementation) can be deployed and smoke-tested.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Read `scripts/ops_data_portal.py` (drain_pending), `scripts/ops_writer.py` (compact(), ~lines 400-430), `scripts/sync_ops.py` (lines 40-80, _rebuild_local_cache), `scripts/data_quality_runner.py` (lines 135-155) to confirm current state; note any active write paths not covered by the bypass audit grep
2. Execute VP step 1 -- enumerate exact violator IDs from Athena; extend `KNOWN_ORPHAN_IDS` in the script with any IDs found beyond rec-608
3. Execute VP step 2 (bypass audit); file a rec via `scripts/ops_data_portal.py file_rec(...)` if an active bypass is found; note the rec ID in the session log
4. Create `scripts/cleanup_ops_rec_orphans.py`:
   - Module docstring: RCA summary -- PR #304 deleted outbox, not Athena; VP Step 7 not executed; this script closes the gap by treating DELETE + assert as one unit (see Class E in DQ_REMEDIATION_METHODOLOGY.md)
   - `KNOWN_ORPHAN_IDS: list[str] = ["rec-608", "rec-633"]` (extend with any additional IDs found in step 2)
   - `_WORKGROUP = "agent-platform-production"` and `_DATABASE = "trading_formulas_db"`
   - `_run_athena_query(client: any, sql: str) -> str`: submits query, polls every 2s up to 60s, raises `RuntimeError(f"Athena query {state}: {reason}")` on non-SUCCEEDED; returns `QueryExecutionId`
   - `_row_count(client: any, query_id: str) -> int`: parses first data row of `get_query_results` as int
   - `purge_orphans(dry_run: bool = False) -> None`: (a) pre-check -- query count of violators; print IDs; (b) if dry_run, return; (c) DELETE FROM ops_recommendations WHERE id IN ({comma-joined KNOWN_ORPHAN_IDS}); (d) DELETE FROM ops_recommendations WHERE id IS NULL; (e) VACUUM trading_formulas_db.ops_recommendations; (f) post-assert -- SELECT count(*) FROM ops_recommendations_current WHERE id IN (...) OR id IS NULL; assert == 0 or raise AssertionError with count; print `PURGE_COMPLETE: 0 orphan rows remain`
   - `__main__`: `argparse` with `--dry-run` flag; call `purge_orphans(dry_run=args.dry_run)`
5. Create `tests/test_cleanup_ops_rec_orphans.py`:
   - `test_dry_run_does_not_delete`: assert DELETE not called when dry_run=True
   - `test_delete_sql_contains_known_ids`: assert DELETE SQL includes each ID from `KNOWN_ORPHAN_IDS`
   - `test_post_assert_failure_raises`: mock post-assert count returning 1; assert `AssertionError` raised
   - `test_vacuum_called_after_delete`: assert VACUUM SQL issued after both DELETEs succeed
6. Execute VP step 3 (unit tests) -- all 4 pass before any live Athena DML
7. Execute VP step 4 (dry-run) -- confirm target rows are identified
8. Execute VP step 5 (live purge) -- DELETE + VACUUM + assert; note `QueryExecutionId`s for audit trail
9. Execute VP step 6 (sync cache)
10. Execute VP step 7 (DQ runner) -- confirm `PASS 0 failed`
11. Update `config/data_quality/decisions/ops_recommendations.yaml`:
    - `status.last_verdict: PASS`; add `rca_note` under status: `"Null-status rows were rec-608 (hollow, bypass via append_jsonl pre-PR-304) and ghost row (id=NULL, compact() artifact pre-PR-323). Cleaned by cleanup_ops_rec_orphans.py. Class E: post-deploy cleanup not executed in prior sessions."`
    - `automatable.last_verdict: PASS`; update `current_test` to `not_null (enforced: true, write_time: true)`
    - `risk.last_verdict: PASS`; update `current_test` to `not_null (enforced: true, write_time: true)`
    - Update `created_timestamp.current_test` to `expression created_timestamp <= last_updated_timestamp (enforced: true)`; set `last_verdict: PASS` (the ghost row causing this FAIL will have been purged)
    - Update `last_updated: 2026-05-12`
12. Update `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`: add Class E entry after Class D under "Root Cause Taxonomy"
13. Run `python -m scripts.validate` (presubmit, no flags) -- confirm exit 0
14. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** -- `config/data_quality/decisions/ops_recommendations.yaml` is Lambda-packaged; deploy and smoke-test once Decision 67 is reversed
15. Report: VP results, DQ verdict before and after, bypass audit outcome, RCA summary
