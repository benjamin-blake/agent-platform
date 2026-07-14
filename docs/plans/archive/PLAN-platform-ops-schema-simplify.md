# Plan

## Intent
Simplify the ops data store schema to use clear SCD Type 2 timestamp semantics (`created_timestamp`, `last_updated_timestamp`) and repartition on `day(last_updated_timestamp)`, eliminating confusing date/timestamp proliferation. Prevent future schema drift between tables and views by using `SELECT *` in all `_current` views.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-ops-schema-simplify

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| terraform/iceberg_tables.tf | Modify | Update 5 ops table CREATE TABLE definitions (new columns, new partition spec) and 3 ops view definitions to use `SELECT *` pattern |
| scripts/ops_writer.py | Modify | Replace `ingested_at`/`trade_date` injection with `created_timestamp`/`last_updated_timestamp`; update S3 key prefix; map `date` field to `created_timestamp` |
| scripts/migrate_schema.py | Modify | Add migration function for the 5-step table repartition dance (CTAS -> DROP -> CREATE -> INSERT -> DROP tmp) |
| scripts/session_preflight.py | Modify | Update ops_recommendations_current query to use `created_timestamp` instead of `date` column |
| scripts/backfill_ops_tables.py | Modify | Replace `ingested_at`/`trade_date` with new column names |
| src/data/handlers/ops_compaction_handler.py | Modify | Update S3 key parsing regex from `trade_date=` to `dt=` format |
| tests/test_ops_writer.py | Modify | Update S3 key format assertions from `trade_date=` to `dt=` |
| tests/test_ops_compaction_handler.py | Modify | Update test event S3 key format |
| docs/DECISIONS.md | Modify | Add Decision 56: SCD Type 2 Schema Simplification |

## Bundled Recommendations
None -- but this plan will LOG recommendations for:
- Telemetry table equivalent migration (created_timestamp/last_updated_timestamp)
- Telemetry view migration to SELECT * pattern
- session_preflight.py telemetry query updates (trade_date references that target telemetry tables -- out of scope here)

## Acceptance Criteria
- [ ] All 5 ops tables use `created_timestamp timestamp` + `last_updated_timestamp timestamp`, partitioned by `day(last_updated_timestamp)`
- [ ] `date` and `trade_date` columns removed from all ops tables (`date` from `ops_recommendations` and `ops_session_log`; schema-evolved `date`/`id`/`keywords` from `ops_decisions`); `date` field mapped to `created_timestamp` in write path
- [ ] `ops_recommendations_current` and `ops_decisions_current` views use `SELECT * ... ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY last_updated_timestamp DESC) ... WHERE row_num = 1`
- [ ] `ops_priority_queue_current` view uses `SELECT *` with correlated subquery (`WHERE queue_run_id = (SELECT queue_run_id ... ORDER BY last_updated_timestamp DESC LIMIT 1)`)
- [ ] `ops_writer.py` injects `created_timestamp` and `last_updated_timestamp` (not `ingested_at`/`trade_date`)
- [ ] `ops_compaction_handler.py` parses the new S3 key format
- [ ] `session_preflight.py` ops queries use `created_timestamp` instead of removed `date` column
- [ ] Decision 56 documented
- [ ] Recommendations logged for equivalent telemetry table migration and preflight telemetry query updates
- [ ] All tests pass (`pytest tests/`)
- [ ] `python scripts/validate.py` passes
- [ ] End-to-end: write a rec via ops_data_portal, compact, query `ops_recommendations_current` in Athena, confirm the rec is returned with correct data

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Validate terraform syntax | `cd terraform && terraform validate` | Exit 0, no errors | Fix HCL syntax |
| 2 | [pre-deploy] | Validate Python changes | `python scripts/validate.py` | Exit 0 | Fix lint/import errors |
| 3 | [pre-deploy] | Run all tests | `python -m pytest tests/test_ops_writer.py tests/test_ops_compaction_handler.py -v` | All tests pass | Fix test assertions |
| 4 | [pre-deploy] | Confirm ops_writer maps date to created_timestamp | `python -m pytest tests/test_ops_writer.py -k "created_timestamp" -v` | Test passes confirming date->created_timestamp mapping | Fix write path mapping |
| 5 | [post-deploy] | Run migration script for all 5 ops tables | `python -m scripts.migrate_schema --migrate-ops-timestamps --profile company-aws-profile` | Prints success for each table migration | Check Athena error output |
| 6 | [post-deploy] | Deploy Lambda with updated ops_writer and compaction handler | `python -m scripts.build_lambda --deploy` | Lambda updated successfully | Check build errors |
| 7 | [post-deploy] | Apply terraform (views only -- human-gated) | `cd terraform && terraform apply -target=null_resource.create_ops_views` | Views recreated | Fix view SQL |
| 8 | [post-deploy] | Write a test rec via portal and compact | `python -m scripts.verify_schema_migration --write-probe --profile company-aws-profile` | Rec staged and compacted without error | Check column mapping |
| 9 | [post-deploy] | Query Athena to confirm rec is queryable with new schema | `python -m scripts.verify_schema_migration --query-probe --profile company-aws-profile` | Returns 1 row with `created_timestamp` and `last_updated_timestamp` populated, no `trade_date` or `date` column | Check migration or compact logic |

## Constraints
- Athena engine v3 required (workgroup: agent-platform-production)
- `ALTER TABLE RENAME COLUMN` supported in Iceberg v2 on Athena v3, but repartition requires CTAS dance
- Telemetry tables are OUT OF SCOPE -- log recs only (including preflight queries that target telemetry tables)
- `awswrangler` must use `temp_path` parameter (v3.x API)
- No Docker -- all migration runs via local Python + Athena queries
- Iceberg `PARTITIONED BY (day(last_updated_timestamp))` uses partition transforms (Iceberg spec v2)
- `date` field from callers (ops_data_portal etc.) is mapped to `created_timestamp` in the write path -- callers are NOT modified

## Context
- Decision 50: Append-Only Ops Data Store via Iceberg (current architecture)
- Decision 56 (new): Documents this schema simplification rationale
- Known gotcha: `CREATE TABLE IF NOT EXISTS` does not update TBLPROPERTIES -- must DROP and recreate for partition change
- Known gotcha: Iceberg integer promotion -- existing `int` may have been promoted to `bigint`
- The views currently use explicit column lists which drift from the tables
- Single developer context makes `SELECT *` in views acceptable (no risk of exposing unexpected columns to other consumers)
- `ops_compaction_handler.py` Lambda parses S3 keys -- must update regex to match new key format
- `session_preflight.py` line 297 queries `ops_recommendations_current` using `date` column -- must update to `created_timestamp`
- `session_preflight.py` lines 731/785 query TELEMETRY tables using `trade_date` -- these are OUT OF SCOPE (telemetry tables not migrated)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Add Decision 56 to docs/DECISIONS.md** -- Title: "SCD Type 2 Schema Simplification for Ops Tables". Document: problem (confusing date/timestamp columns, view-table drift from explicit column lists), decision (use `created_timestamp` + `last_updated_timestamp`, partition by `day(last_updated_timestamp)`, views use `SELECT *`, map incoming `date` field to `created_timestamp`), rationale (single developer, prevents drift, clearer SCD2 semantics). Supersedes timestamp/partition aspects of Decision 50. Place after Decision 55.

2. **Update terraform/iceberg_tables.tf -- ops table definitions** -- For all 5 ops tables: replace `ingested_at timestamp` with `created_timestamp timestamp` + `last_updated_timestamp timestamp`; remove `trade_date date` column; change `PARTITIONED BY (trade_date)` to `PARTITIONED BY (day(last_updated_timestamp))`. Additionally remove `date string` from: `ops_recommendations` (creation date -> `created_timestamp`), `ops_session_log` (session date -> `created_timestamp`). Note: `ops_decisions` has schema-evolved `date`, `id`, and `keywords` columns that exist in the live table but NOT in the Terraform DDL -- these will be dropped during migration.

3. **Update terraform/iceberg_tables.tf -- ops view definitions** -- Rewrite all 3 `_current` views:
   - `ops_recommendations_current` and `ops_decisions_current` use:
     ```sql
     CREATE OR REPLACE VIEW {db}.{table}_current AS
     SELECT *
     FROM (
       SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY last_updated_timestamp DESC) row_num
       FROM {db}.{table}
     )
     WHERE row_num = 1
     ```
     PKs: `ops_recommendations` -> `id`, `ops_decisions` -> `decision_id`.
   - `ops_priority_queue_current` retains its correlated-subquery pattern (returns ALL entries from the latest curator run, not one row per entity):
     ```sql
     CREATE OR REPLACE VIEW {db}.ops_priority_queue_current AS
     SELECT * FROM {db}.ops_priority_queue
     WHERE queue_run_id = (
       SELECT queue_run_id FROM {db}.ops_priority_queue
       ORDER BY last_updated_timestamp DESC LIMIT 1
     )
     ```

4. **Update scripts/ops_writer.py** -- In `write()`: for ops tables, map incoming `date` field to `created_timestamp` (pop `date` key, set as `created_timestamp`); replace `ingested_at`/`trade_date` setdefault with `created_timestamp`/`last_updated_timestamp`; update S3 key from `trade_date={trade_date}/` to `dt={date}/` (date derived from today). The `date` -> `created_timestamp` mapping applies to ALL ops table entries (ops_recommendations, ops_session_log, etc.) since multiple callers pass `date`. In `compact()`: update timestamp column handling -- rename `_ts_cols` list to reference `last_updated_timestamp` and `created_timestamp`; remove `trade_date` DataFrame processing. In `emit()`: for TELEMETRY tables, continue injecting `ingested_at` and `trade_date` unchanged (telemetry tables not migrated); only ops-table writes get new timestamp names. In `compact_all()`: derive date prefix from today. Also remove `"date": "string"`, `"id": "string"`, and `"keywords": "array<string>"` from `_OPS_TABLE_DTYPES["ops_decisions"]` since these schema-evolved columns no longer exist in the table schema.

5. **Update src/data/handlers/ops_compaction_handler.py** -- Update S3 key parsing regex from `trade_date=(\d{4}-\d{2}-\d{2})` to `dt=(\d{4}-\d{2}-\d{2})` (or equivalent pattern). Ensure the handler correctly identifies table name and date partition from the new key structure.

6. **Update scripts/migrate_schema.py** -- Add a `migrate_ops_timestamps()` function that performs the 5-step repartition dance for each ops table:
   - (a) CTAS to `{table}_tmp` with per-table column mapping:
     - `ops_recommendations`: SELECT all except `date`, `trade_date`; add `ingested_at AS last_updated_timestamp, ingested_at AS created_timestamp`
     - `ops_session_log`: SELECT all except `date`, `trade_date`; add `ingested_at AS last_updated_timestamp, ingested_at AS created_timestamp`
     - `ops_decisions`: SELECT all except `date`, `id` (legacy string), `keywords`, `trade_date`; add `ingested_at AS last_updated_timestamp, ingested_at AS created_timestamp`
     - `ops_execution_plans`, `ops_priority_queue`: SELECT all except `trade_date`; add `ingested_at AS last_updated_timestamp, ingested_at AS created_timestamp`
   - (b) DROP original table
   - (c) CREATE with new schema + `PARTITIONED BY (day(last_updated_timestamp))`
   - (d) `INSERT INTO {table} (col1, col2, ...) SELECT col1, col2, ... FROM {table}_tmp` -- explicit column list (not SELECT *) to handle column count differences
   - (e) DROP `{table}_tmp`
   - Add CLI entry point `--migrate-ops-timestamps`.

7. **Update scripts/session_preflight.py** -- At line 297: replace `date` column reference with `created_timestamp` in the SELECT for ops_recommendations_current. Also update line ~309 where `entry.get("date", "")` is used for aging comparison -- change to `entry.get("created_timestamp", "")`. Do NOT modify lines 731/785 (those query telemetry tables which are out of scope).

8. **Update scripts/backfill_ops_tables.py** -- Replace `ingested_at`/`trade_date` references with `created_timestamp`/`last_updated_timestamp`.

9. **Update tests/test_ops_writer.py** -- Update all S3 key format assertions from `trade_date={date}` to `dt={date}`. Update any assertions on `ingested_at`/`trade_date` fields to use `created_timestamp`/`last_updated_timestamp`.

10. **Update tests/test_ops_compaction_handler.py** -- Update test event S3 key format from `trade_date=` to `dt=`.

11. **Create scripts/verify_schema_migration.py** -- A small verification script with two modes: `--write-probe` (files a test rec via ops_data_portal and compacts) and `--query-probe` (queries Athena for the probe rec, asserts schema correctness, prints results). This avoids Windows bash quoting issues with complex `python -c` one-liners in VP steps.

12. **Lambda deploy** -- Run `python -m scripts.build_lambda --deploy` which builds and deploys BOTH `data-pipeline.zip` (contains `ops_writer.py` for scheduled agents) AND `ops-compaction.zip` (contains `ops_compaction_handler.py`). Both Lambda functions are updated.

13. **Log recommendations** -- Use `python -m scripts.ops_data_portal` to file 3 recs: (1) "Migrate telemetry tables to created_timestamp/last_updated_timestamp schema" targeting `terraform/iceberg_tables.tf` and `scripts/telemetry_schemas.py`, (2) "Migrate telemetry views to SELECT * pattern" targeting `terraform/iceberg_tables.tf`, (3) "Update session_preflight.py telemetry queries after telemetry table migration" targeting `scripts/session_preflight.py`.

14. Run `pytest tests/` -- all tests must pass.

15. Run `python scripts/validate.py` -- must exit 0.

16. **Execute Verification Plan** -- run each step from the table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

17. Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
