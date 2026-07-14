# Plan

## Intent
Eliminate the `_rn` and `row_num` column pollution that has entered the `ops_recommendations` and
`ops_decisions` Iceberg base tables, restore the `ops_recommendations_current` and
`ops_decisions_current` Athena views to a queryable state, and close every code-level gate that
allowed the contamination to re-enter after each pull/write cycle. This unblocks `sync_ops pull`,
session preflight, and the priority queue read -- restoring the self-improving feedback loop.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/fix-rn-schema-pollution

## Phase
Phase 1: Core Infrastructure (COMPLETE) -- platform hygiene fix blocking operational pipeline reads.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/executor/jsonl_store.py` | Modify | Remove the `row_num` and `rn` (alias `_rn`) fields from the `Recommendation` Pydantic model; these are SCD2 view-only columns that were whitelisted in commit e4c8a9d instead of being stripped from the polluted local cache. Update the comment block. |
| `scripts/ops_writer.py` | Modify | (a) Add `"_rn"` to the existing drop-column guard in `compact()` alongside `"row_num"` so both are stripped from staged DataFrames before `to_iceberg`. (b) Fix every SQL string in `_refresh_view` to use `AS row_num` instead of `AS _rn`, aligning Python with the canonical Terraform DDL. This closes the `_refresh_view`-driven re-drift path where Python was overwriting the Terraform-correct Athena view with a conflicting alias. |
| `scripts/sync_ops.py` | Modify | Strip `_rn` and `row_num` keys from every row dict in `pull()` before writing to local JSONL. Closes the pull->cache->write feedback loop permanently. |
| `tests/test_executor_jsonl_store.py` | Modify | Remove `_rn` and `row_num` from the existing fixture (lines 501-502); add an assertion that `Recommendation.model_validate` raises `ValidationError` when either field is present (`extra="forbid"` must now reject both). |
| `tests/test_ops_writer.py` | Modify | Add a test asserting that `compact()` drops a DataFrame column named `_rn` AND one named `row_num` before passing to `to_iceberg`. The existing `row_num` drop is guarded; confirm `_rn` is now also guarded. |
| `tests/test_sync_ops.py` | Modify | Add a test asserting that `pull()` strips `_rn` and `row_num` keys from rows returned by Athena before writing them to the local JSONL file. |

## Bundled Recommendations
None. rec-625 (consolidate drain mechanisms) filed separately and out of scope.

## Infrastructure Dependencies
No `.tf` changes required. Terraform DDL already declares `AS row_num` and the `null_resource`
already has `triggers = { query_hash = md5(each.value) }`.

**Lambda deployment required.** `scripts/ops_writer.py` is in `_LAMBDA_SCRIPTS` in
`scripts/build_lambda.py` and is packaged into the scheduled-agent dispatcher and findings-processor
Lambda functions. Without deploying the updated `ops_writer.py`, the Lambda runtime will continue to
call `_refresh_view` with the old `AS _rn` alias, immediately re-poisoning the Athena view after the
DDL fix. Deploy BEFORE running any live DDL steps.

- Pre-deploy: code changes committed to branch
- Deploy: `.venv/Scripts/python.exe -m scripts.build_lambda --deploy`
- Post-deploy smoke test: `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness`
- Live DDL (post-deploy only): ALTER TABLE DROP COLUMN + CREATE OR REPLACE VIEW

## Acceptance Criteria
- [ ] `Recommendation.model_validate({"id": "rec-001", "status": "open", "_rn": "1"})` raises `ValidationError`.
- [ ] `Recommendation.model_validate({"id": "rec-001", "status": "open", "row_num": 1})` raises `ValidationError`.
- [ ] `OpsWriter.compact()` strips both `_rn` and `row_num` from a staged DataFrame before calling `to_iceberg` (asserted by unit test with mocked `wr.athena.to_iceberg`).
- [ ] `sync_ops.pull()` does not write `_rn` or `row_num` keys into the local JSONL files (asserted by unit test with mocked Athena paginator returning rows containing both keys).
- [ ] `_refresh_view` SQL strings in `ops_writer.py` use `AS row_num` throughout; no remaining `AS _rn` occurrences.
- [ ] `logs/.recommendations-log.jsonl` and `logs/.decisions-index.jsonl` contain no rows with `_rn` or `row_num` keys (one-shot sanitization step).
- [ ] Athena `DESCRIBE ops_recommendations` shows neither `_rn` nor `row_num` column.
- [ ] Athena `DESCRIBE ops_decisions` shows no `_rn` column.
- [ ] `sync_ops pull` completes without `INVALID_VIEW` error and logs row counts for `ops_recommendations` and `ops_decisions`.
- [ ] `.venv/Scripts/python.exe -m scripts.validate --quick` passes on the branch.
- [ ] `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` succeeds; no build errors.
- [ ] `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` exits 0.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Run updated unit tests for Pydantic model rejection | `.venv/Scripts/python.exe -m pytest tests/test_executor_jsonl_store.py -q` | All tests pass; new `ValidationError` assertions visible | Fix field removal or ConfigDict; do not weaken assertions |
| 2 | pre-deploy | Run updated unit tests for writer drop guard | `.venv/Scripts/python.exe -m pytest tests/test_ops_writer.py -q` | All tests pass; new `_rn` drop assertion visible | Verify drop guard added to correct branch in `compact()` |
| 3 | pre-deploy | Run updated unit tests for pull filter | `.venv/Scripts/python.exe -m pytest tests/test_sync_ops.py -q` | All tests pass; new column-strip assertion visible | Verify strip applied before JSONL write, not after |
| 4 | pre-deploy | Confirm no `AS _rn` alias remains in ops_writer.py | `grep -n "AS _rn" scripts/ops_writer.py` | No output (zero matches) | Rename remaining occurrences to `AS row_num` |
| 5 | pre-deploy | Confirm drop guard now includes _rn | `grep -n '"_rn"' scripts/ops_writer.py` | Matches the drop-columns block in `compact()` | Add `"_rn"` to the drop list |
| 6 | pre-deploy | Full quick validate on branch | `.venv/Scripts/python.exe -m scripts.validate --quick` | All checks pass | Fix any lint or test failures before proceeding |
| 7 | pre-deploy | Sanitize local JSONL cache (strip _rn and row_num) | `.venv/Scripts/python.exe -c "import json; from pathlib import Path; STRIP={'_rn','row_num'}; [Path(p).write_text('\n'.join(json.dumps({k:v for k,v in json.loads(l).items() if k not in STRIP},ensure_ascii=False) for l in Path(p).read_text(encoding='utf-8').splitlines() if l.strip())+'\n',encoding='utf-8',newline='\n') or print(p,'sanitized') for p in ['logs/.recommendations-log.jsonl','logs/.decisions-index.jsonl'] if Path(p).exists()]"` | Prints `logs/.recommendations-log.jsonl sanitized` and `logs/.decisions-index.jsonl sanitized`; no error | Check file encoding or JSON parse error; inspect first failing line |
| 8 | [pre-deploy] | Build and deploy Lambda with updated ops_writer.py | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` | Build succeeds; Lambda function code updated; no size-limit error | If size error: check build output; if credentials error: refresh SSO (`aws sso login --profile company-aws-profile`) |
| 9 | [post-deploy] | Smoke test Lambda with updated ops_writer | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Exit code 0; no runtime errors in output | If non-zero: check Lambda logs in CloudWatch (`/aws/lambda/agent-platform-scheduled-agent-dispatcher`); look for import errors from updated ops_writer |
| 10 | [post-deploy] | DROP _rn from ops_recommendations (live Iceberg DDL) | `QEID=$(aws athena start-query-execution --query-string "ALTER TABLE trading_formulas_db.ops_recommendations DROP COLUMN _rn" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 10 && aws athena get-query-execution --query-execution-id $QEID --profile company-aws-profile --query 'QueryExecution.Status.State' --output text` | SUCCEEDED | If FAILED: check StateChangeReason; if "column does not exist" skip and continue |
| 11 | [post-deploy] | DROP row_num from ops_recommendations | `QEID=$(aws athena start-query-execution --query-string "ALTER TABLE trading_formulas_db.ops_recommendations DROP COLUMN row_num" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 10 && aws athena get-query-execution --query-execution-id $QEID --profile company-aws-profile --query 'QueryExecution.Status.State' --output text` | SUCCEEDED | Same as step 10 |
| 12 | [post-deploy] | DROP _rn from ops_decisions | `QEID=$(aws athena start-query-execution --query-string "ALTER TABLE trading_formulas_db.ops_decisions DROP COLUMN _rn" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 10 && aws athena get-query-execution --query-execution-id $QEID --profile company-aws-profile --query 'QueryExecution.Status.State' --output text` | SUCCEEDED | If "column does not exist" skip |
| 13 | [post-deploy] | Re-fire ops_recommendations_current view (AS row_num) | `QEID=$(aws athena start-query-execution --query-string "CREATE OR REPLACE VIEW trading_formulas_db.ops_recommendations_current AS SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num FROM trading_formulas_db.ops_recommendations) WHERE row_num = 1" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 10 && aws athena get-query-execution --query-execution-id $QEID --profile company-aws-profile --query 'QueryExecution.Status.State' --output text` | SUCCEEDED | Verify steps 10-11 completed; check base table DESCRIBE if still failing |
| 14 | [post-deploy] | Re-fire ops_decisions_current view (AS row_num) | `QEID=$(aws athena start-query-execution --query-string "CREATE OR REPLACE VIEW trading_formulas_db.ops_decisions_current AS SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY last_updated_timestamp DESC) AS row_num FROM trading_formulas_db.ops_decisions) WHERE row_num = 1" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 10 && aws athena get-query-execution --query-execution-id $QEID --profile company-aws-profile --query 'QueryExecution.Status.State' --output text` | SUCCEEDED | Verify step 12 completed first; fix base table state and retry |
| 15 | [post-deploy] | Confirm DESCRIBE shows no rogue columns | `QEID=$(aws athena start-query-execution --query-string "DESCRIBE trading_formulas_db.ops_recommendations" --work-group agent-platform-production --profile company-aws-profile --output text --query 'QueryExecutionId') && sleep 5 && aws athena get-query-results --query-execution-id $QEID --profile company-aws-profile --query 'ResultSet.Rows[*].Data[0].VarCharValue' --output text` | Column list contains neither `_rn` nor `row_num` | If still present: re-run DROP; check for schema_evolution re-injection from staged S3 data |
| 16 | [post-deploy] | Pull from Athena succeeds end-to-end | `.venv/Scripts/python.exe -m scripts.sync_ops pull` | Row counts logged for all tables; no `INVALID_VIEW` error in output | If still invalid view: confirm steps 13/14 SUCCEEDED; inspect live Athena console for stored view DDL |
| 17 | [post-deploy] | Confirm local JSONL clean after pull | `.venv/Scripts/python.exe -c "import json; from pathlib import Path; rows=json.loads('['+','.join(l for l in Path('logs/.recommendations-log.jsonl').read_text(encoding='utf-8').splitlines() if l.strip())+']'); bad=[r for r in rows if '_rn' in r or 'row_num' in r]; print('contaminated rows:',len(bad))"` | Prints `contaminated rows: 0` | If > 0: pull filter not applied; check sync_ops.py strip logic; re-pull |

## Constraints
- Single Portal Invariant (Decision 51): local JSONL sanitization in step 7 writes files directly because the cache is gitignored and pull-only; this is the only permitted exception to direct file writes.
- Iceberg `ALTER TABLE DROP COLUMN` is permanent and irreversible. Columns `_rn` and `row_num` are synthetic SCD2 deduplication artifacts, not data fields. Dropping them is safe.
- Self-modification boundary (Decision 44): `scripts/executor/jsonl_store.py` and `tests/test_executor_jsonl_store.py` are boundary files but are permitted in this `/plan` -> `/implement` flow because the planner (not the executor) is driving the change.
- Windows subprocess safety: use `encoding='utf-8', errors='replace'` for subprocess calls; do not invoke bare `python`.
- All DDL verification steps (10-15) use the `agent-platform-production` workgroup (engine v3). Do NOT use the `primary` workgroup for Iceberg DDL.
- Test isolation: new tests in test_ops_writer.py and test_sync_ops.py must mock `wr.athena.to_iceberg` and the Athena boto3 paginator respectively. No live AWS calls in pytest.

## Context
- **Root commit**: e4c8a9d (#279) "harden-ops-schema" whitelisted `_rn` (as `rn` with alias) and `row_num` into the Pydantic schema when migrating `extra="allow"` -> `extra="forbid"`. Correct fix was to sanitize the polluted local JSONL; instead the toxic columns were promoted to schema fields.
- **Writer gap**: `compact()` at line 348-350 of `ops_writer.py` only drops `"row_num"`; the guard for `"_rn"` is absent. Both escape through `wr.athena.to_iceberg(schema_evolution=True)`.
- **View drift mechanism**: `_refresh_view()` fires on schema evolution events and uses `AS _rn` in its SQL. Terraform uses `AS row_num`. Any schema evolution event caused `_refresh_view` to overwrite the Terraform-correct Athena view with a conflicting alias, making `WHERE _rn = 1` in the view ambiguous with the rogue base column.
- **Terraform trigger is sound**: `null_resource.create_ops_views` already has `triggers = { query_hash = md5(each.value) }`. No Terraform changes needed; aligning `_refresh_view` Python SQL to match Terraform closes the drift.
- **ops_decisions asymmetry**: only `_rn` visible in local JSONL (no `row_num`). Still requires DROP and view re-fire. Verification plan accounts for this via conditional skip.
- **Decision 56** (SCD Type 2 simplification, 2026-04-30) declared these columns view-only. The schema and writer should have been updated at that point; this plan completes the intent of Decision 56.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`scripts/executor/jsonl_store.py`**: Remove `row_num` field (line 58) and `rn` field with `alias="_rn"` (line 59) from the `Recommendation` model. Update the SCD2 comment block to read "SCD2 timestamps managed by OpsWriter; row deduplication is view-only and must not appear in base table writes."
2. **`scripts/ops_writer.py`**: (a) In `compact()`, extend the drop-columns check to also drop `"_rn"` (current guard only drops `"row_num"`). (b) In `_refresh_view()`, replace every occurrence of `AS _rn` with `AS row_num` in all SQL strings, and update every `WHERE _rn = 1` to `WHERE row_num = 1`.
3. **`scripts/sync_ops.py`**: In `pull()`, after constructing each row dict via `dict(zip(header, data))`, add a one-liner to strip `_rn` and `row_num` keys before appending to `rows`.
4. **`tests/test_executor_jsonl_store.py`**: Remove `"row_num": 1` and `"_rn": "1"` from the existing fixture; add two new test methods (or parametrize) asserting that `Recommendation.model_validate` raises `ValidationError` when `_rn` is present and when `row_num` is present.
5. **`tests/test_ops_writer.py`**: Add a test class or method that mocks `wr.athena.to_iceberg`, calls `compact()` with a DataFrame containing `_rn` and `row_num` columns, and asserts neither column is present in the DataFrame passed to the mock.
6. **`tests/test_sync_ops.py`**: Add a test asserting that when the Athena paginator mock returns rows containing `_rn` and `row_num` keys, the resulting JSONL written to disk contains neither key.
7. **Lambda build + deploy**: Run `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` to package the updated `ops_writer.py` into both Lambda functions. This MUST complete before any live DDL steps -- an un-deployed Lambda would re-fire `_refresh_view` with the old `AS _rn` alias and undo the view fix.
8. **Execute Verification Plan** -- run steps 1-17 in order. Stop and analyze root cause on any unrecoverable V3 failure (Decision 55). Do not weaken test assertions or skip DDL steps.
9. Report: what was changed, verification results, row counts from sync_ops pull.
