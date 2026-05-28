# Plan

## Intent
Prove the telemetry system is end-to-end operational before proceeding to Phase E (Cloud Analysis Agent) by creating a comprehensive validation script that verifies schema integrity, column population, FK referential integrity, and view correctness across all 7 Iceberg tables. This closes the feedback loop: the autonomous system cannot improve itself without trustworthy telemetry data.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-telemetry-validation

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/validate_telemetry.py | Create | Three-layer validation script: schema integrity, column population, FK referential integrity |
| tests/test_validate_telemetry.py | Create | Unit tests for the validation script (mocked Athena calls) |
| scripts/telemetry_schemas.py | Modify | Add `get_all_columns(table)` and `get_required_columns(table)` helper functions used by the validator |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `python -m scripts.validate_telemetry --help` prints usage and exits 0
- [ ] `python -m scripts.validate_telemetry --dry-run` performs schema introspection checks without querying Athena and exits 0
- [ ] `AWS_PROFILE=company-aws-profile python -m scripts.validate_telemetry` runs all three validation layers and produces a JSON report at `logs/debug/telemetry-validation-{date}.json`
- [ ] Exit code is 0 if all required columns of all tables have >0 population; exit code 1 otherwise with clear diagnostic output
- [ ] `python -m pytest tests/test_validate_telemetry.py -q` passes with all mocked scenarios (empty tables, partial population, FK violations)
- [ ] `python -m scripts.validate` exits 0 (no lint/import regressions)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Import and dry-run check (schema introspection only) | `python -m scripts.validate_telemetry --dry-run` | Prints schema report comparing Python dataclass fields to expected Iceberg columns for all 7 tables; exits 0 | Fix import paths or schema helper functions |
| 2 | [pre-deploy] | Unit tests pass with mocked Athena | `python -m pytest tests/test_validate_telemetry.py -v` | All tests pass (mock scenarios: full population, empty table, FK orphan, schema drift) | Fix test setup or validation logic |
| 3 | [pre-deploy] | Validate.py passes | `python -m scripts.validate` | Exit 0 | Fix lint/import errors |
| 4 | [post-deploy] | Lambda zip rebuild and deploy after telemetry_schemas.py change | `python -m scripts.build_lambda --deploy && python -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Build succeeds, deploy succeeds, smoke test passes (Lambda cold-starts without import errors) | Fix telemetry_schemas.py import-time side effects |
| 5 | [post-deploy] | Run full validation against live Athena | `AWS_PROFILE=company-aws-profile python -m scripts.validate_telemetry 2>&1; echo "exit:$?"` | Produces structured report; identifies which tables/columns are empty; exit code reflects actual state | Fix Athena query syntax or permissions |
| 6 | [post-deploy] | Verify JSON report written | `ls -la logs/debug/telemetry-validation-*.json && python -c "import json; r=json.load(open(sorted(__import__('glob').glob('logs/debug/telemetry-validation-*.json'))[-1])); print(f'tables_checked: {len(r[\"tables\"])}, layers: {list(r.keys())}')"` | File exists, contains keys: `tables`, `views`, `fk_checks`, `schema_drift`; `tables_checked` == 7 | Fix report writing logic |
| 7 | [post-deploy] | Verify FK integrity results are present in report | `python -c "import json; r=json.load(open(sorted(__import__('glob').glob('logs/debug/telemetry-validation-*.json'))[-1])); fk=r['fk_checks']; print(f'fk_checks: {len(fk)} relationships tested'); assert len(fk) >= 4, 'Expected at least 4 FK relationships'"` | At least 4 FK relationships checked (phases->sessions, steps->phases, model_calls->sessions, transcripts->sessions) | Fix FK query generation |

## Constraints
- AWS profile `company-aws-profile` required for Athena queries (SSO must be active)
- Athena workgroup `agent-platform-production` (engine v3) required for Iceberg operations
- Script must never raise on Athena errors -- graceful degradation with diagnostic output
- Must work on Windows (pathlib, no shell-specific logic in write paths)
- Script must be importable without AWS credentials (deferred imports for boto3/awswrangler)
- No `eval()`/`exec()` -- query generation uses f-strings with validated table/column names only

## Context
- **Decision 51:** Local-First Outbox + Bidirectional Sync. Outbox files may contain data that hasn't been compacted yet.
- **INTENT-telemetry-system.md:** Authoritative schema spec. 7 tables in star schema with `telemetry_` prefix.
- **Known gotcha (awswrangler 3.x):** `temp_s3_dir` -> `temp_path` rename. Verify parameter name before calling.
- **Known gotcha (Iceberg integer promotion):** Integer columns may have been promoted to `bigint`. Validator should accept both.
- **VP Gap Analysis finding:** Prior plans verified only structural existence (tests pass, imports work) but never verified actual data population in Athena. This plan exists to close that gap permanently.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add schema helper functions to telemetry_schemas.py

Modify `scripts/telemetry_schemas.py` to add two public helper functions after the `validate_record` function:

```python
def get_all_columns(table_name: str) -> list[str]:
    """Return ordered list of all column names for a telemetry table."""

def get_required_columns(table_name: str) -> list[str]:
    """Return list of required (non-nullable) column names for a telemetry table."""
```

These use the existing `_SCHEMA_FIELDS` and `_SCHEMA_CLASSES` module-level dicts. Must not raise on unknown table names (return empty list with warning).

**Acceptance:** `python -m pytest tests/test_telemetry_schemas.py::TestSchemaHelpers -q --tb=short`

---

### Step 2: Create scripts/validate_telemetry.py -- Layer 1 (Schema Integrity)

Create `scripts/validate_telemetry.py` with:

- `main()` entry point with argparse: `--dry-run` (schema-only, no Athena), `--table` (filter to one table), `--output` (report path, default `logs/debug/telemetry-validation-{date}.json`)
- `check_schema_integrity()` function: for each of the 7 tables, compare `get_all_columns(table)` against the Athena DDL (`SHOW COLUMNS IN trading_formulas_db.{table}`). Report columns in Python but not Athena (missing) and columns in Athena but not Python (extra).
- AWS profile detection via env var `AWS_PROFILE` or `--profile` arg. If no credentials, schema integrity runs in dry-run mode (comparing Python schemas only, printing expected vs actual).
- All Athena queries use `WorkGroup='agent-platform-production'` and poll for completion.
- Output: JSON report dict with `schema_drift` key.

**Acceptance:** `python -m scripts.validate_telemetry --dry-run 2>&1 | grep -q "schema_drift"`

---

### Step 3: Add Layer 2 (Column Population Coverage)

Add `check_population_coverage()` function to `scripts/validate_telemetry.py`:

For each table, generate and execute:
```sql
SELECT
    COUNT(*) AS total_rows,
    COUNT(column_name) AS non_null_count
FROM trading_formulas_db.{table}
WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
```

One query per table (use `COALESCE` counting for all columns in a single SELECT to minimize Athena cost). Structure:
```sql
SELECT COUNT(*) AS total_rows,
       SUM(CASE WHEN session_id IS NOT NULL THEN 1 ELSE 0 END) AS session_id_count,
       SUM(CASE WHEN workflow IS NOT NULL THEN 1 ELSE 0 END) AS workflow_count,
       ...
FROM trading_formulas_db.{table}
WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
```

Compute `population_pct = non_null / total * 100` for each column. Classify:
- `PASS`: required column with population > 0%
- `FAIL`: required column with population == 0% (or table has 0 rows)
- `WARN`: optional column with population == 0%
- `OK`: optional column with population > 0%

Add results to the JSON report under `tables` key.

**Acceptance:** `grep -q "check_population_coverage" scripts/validate_telemetry.py && grep -q "total_rows" scripts/validate_telemetry.py`

---

### Step 4: Add Layer 3 (FK Referential Integrity)

Add `check_fk_integrity()` function to `scripts/validate_telemetry.py`:

Verify these FK relationships:
1. `telemetry_phases.session_id` -> `telemetry_sessions.session_id`
2. `telemetry_steps.phase_id` -> `telemetry_phases.phase_id`
3. `telemetry_steps.session_id` -> `telemetry_sessions.session_id`
4. `telemetry_model_calls.session_id` -> `telemetry_sessions.session_id` (where session_id IS NOT NULL)
5. `telemetry_transcripts.session_id` -> `telemetry_sessions.session_id` (where session_id IS NOT NULL)
6. `telemetry_model_calls.invocation_id` -> `telemetry_agent_invocations.invocation_id` (where invocation_id IS NOT NULL)

For each relationship, execute:
```sql
SELECT COUNT(*) AS orphan_count
FROM trading_formulas_db.{child_table} c
LEFT JOIN trading_formulas_db.{parent_table} p ON c.{fk_col} = p.{pk_col}
WHERE c.{fk_col} IS NOT NULL AND p.{pk_col} IS NULL
  AND c.trade_date >= CURRENT_DATE - INTERVAL '30' DAY
```

Report orphan counts. `orphan_count > 0` = WARN (not blocking, but diagnostic).

Also verify the 7 views return rows:
- `telemetry_sessions_current`
- `telemetry_phases_current`
- `telemetry_steps_current`
- `telemetry_agent_invocations_current`
- `telemetry_session_summary_30d`
- `telemetry_phase_time_distribution`
- `telemetry_event_frequency_30d`

For each: `SELECT COUNT(*) FROM {view} LIMIT 1`. Report row count.

Add results to report under `fk_checks` and `views` keys.

**Acceptance:** `grep -q "check_fk_integrity" scripts/validate_telemetry.py && grep -q "orphan_count" scripts/validate_telemetry.py`

---

### Step 5: Wire up main() and report generation

Wire all three layers together in `main()`:
1. Parse args
2. If `--dry-run`: run schema introspection only (compare Python schemas, print expected columns)
3. Else: run all three layers, aggregate results
4. Determine exit code: if ANY required column in ANY table has 0% population, exit 1
5. Write JSON report to `logs/debug/telemetry-validation-{date}.json`
6. Print human-readable summary table to stdout (table name | total rows | required cols passing | optional cols populated | FK orphans | verdict)

The script must handle Athena query polling (start_query_execution -> get_query_execution loop with exponential backoff, max 60s per query).

**Acceptance:** `python -m scripts.validate_telemetry --help | grep -q "dry-run"`

---

### Step 6: Create tests/test_validate_telemetry.py

Create unit tests with mocked Athena client:

- `TestSchemaIntegrity`: mock `SHOW COLUMNS` returning exact match, extra columns, missing columns
- `TestPopulationCoverage`: mock query results for full population, empty table (0 rows), partial population (some required columns null)
- `TestFKIntegrity`: mock JOIN query showing 0 orphans, >0 orphans
- `TestViewCheck`: mock view queries returning >0 rows, 0 rows
- `TestDryRun`: verify dry-run mode doesn't call Athena
- `TestReportGeneration`: verify JSON report structure matches expected schema
- `TestExitCode`: verify exit 1 when required column has 0 population

Mock pattern: patch `boto3.Session` to return a mock Athena client. Use `side_effect` for query result sequences.

**Acceptance:** `python -m pytest tests/test_validate_telemetry.py -q --tb=short`

---

### Step 7: Run test suite and validate

Run `python -m pytest tests/test_validate_telemetry.py tests/test_telemetry_schemas.py -q --tb=short` -- all tests must pass.

Run `python -m scripts.validate --ci` -- must exit 0.

**Acceptance:** `python -m scripts.validate --ci`

---

### Step 7b: Lambda deployment (telemetry_schemas.py is Lambda-packaged)

Since `scripts/telemetry_schemas.py` is in `_LAMBDA_SCRIPTS`, rebuild and deploy the Lambda zip to verify the additive change doesn't break cold starts:

1. `python -m scripts.build_lambda` -- rebuild zip
2. `python -m scripts.build_lambda --deploy` -- upload to S3 and update Lambda
3. `python -m scripts.run_scheduled_agent --smoke-test doc-freshness` -- verify Lambda still starts

**Acceptance:** `python -m scripts.build_lambda --deploy && python -m scripts.run_scheduled_agent --smoke-test doc-freshness`

---

### Step 8: **Execute Verification Plan**

Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

---

### Step 9: Report

Report: what was implemented, verification results (actual outcomes from VP steps), telemetry population state discovered, and any bugs found/fixed during validation.
