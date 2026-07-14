# Plan

## Intent
Delete three cohorts of corrupt and orphaned records from the `ops_recommendations` Iceberg table, then graduate five `enforced: false` DQ checks to `enforced: true`. Adds an `OpsWriter` write-path guard to prevent null-id records from reaching Athena in future. Advances the Phase 4 (Data Quality Resolution) arc by eliminating the blocking data conditions that have held four checks in `enforced: false` since PR #296.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-ops-rec-corrections

## Phase
Phase Platform (Automation Infrastructure) -- parallel track to Phase 1 (Core Infrastructure, COMPLETE)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_writer.py` | Modify | Add id-validation guard in `write()` for `ops_recommendations`: log error and return without staging if `entry["id"]` does not match `^rec-\d+$` |
| `tests/test_ops_writer.py` | Modify | Add tests for the id-validation guard (missing id, invalid format, valid id) inside `TestOpsWriterWrite` |
| `config/data_quality/ops.yaml` | Modify | Graduate 5 checks from `enforced: false` to `enforced: true`; delete `date:` column section from `ops_session_log` |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `SELECT COUNT(*) FROM trading_formulas_db.ops_recommendations WHERE id IS NULL AND created_timestamp >= DATE('2026-05-01')` returns 0 after the zombie DELETE.
- [ ] `SELECT COUNT(*) FROM trading_formulas_db.ops_recommendations WHERE status IN ('Decided', 'Unknown')` returns 0 after the status-corruption DELETE.
- [ ] `SELECT COUNT(*) FROM trading_formulas_db.ops_recommendations WHERE id IN ('rec-001', 'rec-002')` returns 0 after the stub DELETE.
- [ ] Fresh DQ run after all three DELETEs shows PASS for: `ops_recommendations / id / not_null`, `source / not_null`, `effort / not_null`, `priority / not_null`, `status / not_null`.
- [ ] `ops.yaml` diff shows exactly 5 `enforced:` values changed from `false` to `true` and the `date:` block absent from `ops_session_log.columns`.
- [ ] `.venv/Scripts/python.exe -m scripts.validate` exits 0 on the branch after YAML changes (graduation guard satisfied; DQ run must precede this).
- [ ] `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` exits 0 and Lambda is updated.
- [ ] `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` exits 0 after deploy.
- [ ] `pytest tests/test_ops_writer.py` exits 0 with new guard tests passing.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | [pre-deploy] | Count zombie rows in base table | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; s=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query(\"SELECT COUNT(*) n FROM trading_formulas_db.ops_recommendations WHERE id IS NULL AND created_timestamp >= DATE('2026-05-01')\", database='trading_formulas_db', boto3_session=s, workgroup='agent-platform-production', ctas_approach=False); print(df['n'].iloc[0])"` | `6` | Recheck WHERE clause; run `aws sso login --profile company-aws-profile` if credentials expired |
| 2 | [pre-deploy] | Count status-corrupt and stub rows | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; s=boto3.Session(profile_name='company-aws-profile'); kw=dict(database='trading_formulas_db',boto3_session=s,workgroup='agent-platform-production',ctas_approach=False); print('status-corrupt:', wr.athena.read_sql_query(\"SELECT COUNT(*) n FROM trading_formulas_db.ops_recommendations WHERE status IN ('Decided','Unknown')\",**kw)['n'].iloc[0]); print('stubs:', wr.athena.read_sql_query(\"SELECT COUNT(*) n FROM trading_formulas_db.ops_recommendations WHERE id IN ('rec-001','rec-002')\",**kw)['n'].iloc[0])"` | `status-corrupt: 31` / `stubs: 2` | Counts may be 0 if already cleaned -- proceed; any other unexpected value: investigate before deleting |
| 3 | [pre-deploy] | Execute three Iceberg DELETEs and confirm all counts reach 0 | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; s=boto3.Session(profile_name='company-aws-profile'); kw=dict(database='trading_formulas_db',workgroup='agent-platform-production',boto3_session=s,wait=True); wr.athena.start_query_execution(sql=\"DELETE FROM trading_formulas_db.ops_recommendations WHERE id IS NULL AND created_timestamp >= DATE('2026-05-01')\",**kw); wr.athena.start_query_execution(sql=\"DELETE FROM trading_formulas_db.ops_recommendations WHERE status IN ('Decided','Unknown')\",**kw); wr.athena.start_query_execution(sql=\"DELETE FROM trading_formulas_db.ops_recommendations WHERE id IN ('rec-001','rec-002')\",**kw); print('done')"` | `done` with no exceptions; re-run VP#1 and VP#2 commands to confirm all counts are `0` | Athena DML error: verify workgroup is `agent-platform-production` (not `primary`); wait 30s for commit and retry |
| 4 | [pre-deploy] | Run DQ runner; confirm five target checks pass | `.venv/Scripts/python.exe -m scripts.data_quality_runner` | `dq-latest.json` shows PASS for `ops_recommendations / id / not_null`, `source / not_null`, `effort / not_null`, `priority / not_null`, `status / not_null` | If any remain FAIL: run `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; s=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query('SELECT id, source, effort, priority, status FROM trading_formulas_db.ops_recommendations_current WHERE id IS NULL OR source IS NULL OR effort IS NULL OR priority IS NULL OR status IS NULL', database='trading_formulas_db', boto3_session=s, workgroup='agent-platform-production', ctas_approach=False); print(df)"` to identify the remaining violating rows |
| 5 | [pre-deploy] | OpsWriter guard unit tests (pre-package verification) | `.venv/Scripts/python.exe -m pytest tests/test_ops_writer.py -x` | All tests pass | Fix guard implementation in `OpsWriter.write()` before proceeding to Lambda build |
| 6 | [post-deploy] | Build and deploy Lambda with guard in package | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` | Exits 0; Lambda function code updated | Syntax error in `ops_writer.py`: run `ruff check --fix scripts/ops_writer.py` and retry |
| 7 | [post-deploy] | Smoke test Lambda runtime loads new `OpsWriter` | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Exit 0; no import or runtime crash | Check CloudWatch logs for `/aws/lambda/agent-platform-scheduled-agent-dispatcher`; likely a packaging error -- re-run build step |
| 8 | [post-deploy] | Graduation guard allows all YAML flips | `.venv/Scripts/python.exe -m scripts.validate` | Exits 0 | Guard blocked a flip: re-run DQ runner (VP#4) to refresh `dq-latest.json`; if check is genuinely FAIL, diagnose before re-attempting |
| 9 | [post-deploy] | Final DQ run with graduated YAML | `.venv/Scripts/python.exe -m scripts.data_quality_runner` | Overall failure count lower than pre-session baseline (was 26F / 2W / 1E); the 5 graduated checks show PASS; `ops_session_log` ERROR verdict absent | Regression in a graduated check: YAML edit introduced a typo or wrong `enforced` value -- recheck ops.yaml diff |

## Constraints
- Iceberg `DELETE FROM` requires workgroup `agent-platform-production` (engine v3). The `primary` workgroup (engine v2) does not support Iceberg DML and will silently fail or error.
- `OpsWriter` contract: never raises exceptions to callers (see module docstring). The id-validation guard must `logger.error(...)` and `return`, not `raise`.
- `status.accepted_values` is NOT graduated in this session -- it is blocked on rec-594 (Pydantic Literal validation for the status field at write time). Only `status.not_null` graduates.
- The graduation guard in `validate.py` reads `dq-latest.json`. The DQ runner MUST be invoked (VP#4) before `validate.py` presubmit (VP#8), or the guard will not see updated verdicts and may reject legitimate flips.
- The five checks being graduated already carry `enforced: false` in dict form. Change only the `enforced:` value; do not restructure the surrounding YAML block or remove the `exclude_before` gates.
- No rescue agents or workaround loops (Decision 55).
- If VP#4 shows a check still FAIL after the DELETEs, stop and diagnose with the targeted SELECT in the VP#4 Fix-If column before editing any YAML.

## Context
- **Investigation (2026-05-07)**: post-anchor DQ failures for id/source/effort/priority all traced to one zombie record (NULL id, created 2026-05-05, 6 raw Iceberg rows from a portal retry storm). The zombie's `created_timestamp` falls after the `exclude_before: 2026-05-01` anchor, so the temporal gate does not protect it. Root cause: `OpsWriter.write()` staged the record to S3 without validating that `id` is non-null; `compact_all()` flushed it to Iceberg.
- **Status corruption**: 31 records with `status IN ('Decided', 'Unknown')` are ops_decisions entries written to the wrong table during early migration (Decision 56 era). 2 stub records (`rec-001`, `rec-002`) have empty/null fields. All are safely deletable -- `docs/DECISIONS.md` has already captured any still-relevant content from those records.
- **`ops_session_log.date`**: the `date` column was dropped from the Iceberg schema (Decision 56). The DQ check produces `ERROR` (SQL fails to compile) rather than `FAIL`. Deleting the YAML block eliminates the ERROR verdict with no data changes needed.
- **Phase 3 graduation guard**: live since PR #296. It blocks flipping a check to `enforced: true` if `dq-latest.json` shows a non-PASS verdict for that check. This is a safety net -- do not attempt to bypass it.
- **source.not_null graduation**: the manifest classified source as `NEEDS_WRITE_FIX` (broader governance work). The `not_null` check specifically is safe to graduate once the zombie is deleted -- the manifest's decided_action explicitly calls for keeping it enforced as a harness health signal. The broader write-fix work (source registry, CI gate) is separate scope.
- **Lambda packaging**: `scripts/ops_writer.py` is listed in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py:45`. The id-validation guard must be packaged and deployed before the smoke test.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Add id-validation guard to `scripts/ops_writer.py`**: At the top of `write()`, before any S3 staging logic, add a guard for `table == "ops_recommendations"`. Extract `rec_id = str(entry.get("id") or "")`. If it does not match `re.compile(r"^rec-\d+$")`, call `logger.error("ops_writer: refusing to stage ops_recommendations record with invalid id %r", rec_id)` and `return`. Ensure `re` is imported at module level. Line length must stay under 127 chars (ruff E501). Run `ruff check --fix scripts/ops_writer.py` after editing.

2. **Add tests to `tests/test_ops_writer.py`** inside `TestOpsWriterWrite`: (a) `test_write_rejects_ops_recommendations_with_missing_id` -- call `write("ops_recommendations", {"title": "orphan"})` with S3 mocked; assert `put_object` was not called; (b) `test_write_rejects_ops_recommendations_with_invalid_id_format` -- call with `{"id": "dec-001", ...}`; assert `put_object` not called; (c) `test_write_accepts_ops_recommendations_with_valid_rec_id` -- call with `{"id": "rec-042", ...}`; assert write proceeds normally. Run `pytest tests/test_ops_writer.py -x` to confirm all pass (VP#5).

3. **Build and deploy Lambda** (VP#6): `.venv/Scripts/python.exe -m scripts.build_lambda --deploy`. Confirm exit 0.

4. **Smoke test Lambda runtime** (VP#7): `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness`. Confirm exit 0.

5. **Verify pre-delete row counts** (VP#1-2): confirm 6 zombie rows, 31 status-corrupt rows, 2 stub rows. Stop and investigate if any count is unexpected and non-zero.

6. **Execute Iceberg DELETEs** (VP#3): run the combined awswrangler invocation from VP#3. Re-run VP#1 and VP#2 counts to confirm all return 0.

7. **Run DQ runner** (VP#4): `.venv/Scripts/python.exe -m scripts.data_quality_runner`. Confirm `logs/debug/dq-latest.json` shows PASS for the five target checks. Do not proceed to Step 8 if any remain FAIL -- use the diagnostic query in the VP#4 Fix-If column.

8. **Update `config/data_quality/ops.yaml`**:
   - Under `ops_recommendations`, change `enforced: false` to `enforced: true` on the `not_null` test for each of: `id`, `source`, `effort`, `priority`, `status`. Remove only the inline comment on each of those five lines (the `# post-anchor data condition: ...` and `# nulls present` text); do not touch `exclude_before` values or surrounding YAML structure.
   - Under `ops_session_log.columns`, delete the entire `date:` key block (three lines: the `date:` key, its `tests:` child, and the `- not_null: ...` entry).

9. **Execute Verification Plan steps 8-9** (VP#8-9): run `validate.py` presubmit, then a final DQ run. Loop on any failure until resolved. The graduation guard is the enforcement mechanism -- if it fires, re-run the DQ runner and retry before investigating further.

10. **Report**: confirm DELETEs and row counts, which checks graduated, DQ aggregate verdict before and after, Lambda smoke test result, test pass/fail, and that `status.accepted_values` was intentionally left at `enforced: false` pending rec-594.
