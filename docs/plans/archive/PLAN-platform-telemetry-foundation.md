# Plan

## Intent
Build the foundational telemetry write infrastructure (schemas, OpsWriter extension, Iceberg tables, Athena views) that enables Phase B-F of the telemetry system to instrument every workflow. This is the data layer that closes the RSI feedback loop -- without it, the system cannot observe its own behaviour.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-telemetry-foundation

## Phase
Phase Platform: Wave 2 (Telemetry Root Cause Fix) -- superseded by `docs/INTENT-telemetry-system.md` Phase A

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/telemetry_schemas.py` | Create | Define 7 telemetry table schemas as dataclasses with field metadata, validation, and dtype mappings |
| `scripts/ops_writer.py` | Modify | Extend TABLE_NAMES and _TABLE_DTYPES with 7 telemetry tables; add schema-validated `emit()` method |
| `scripts/sync_ops.py` | Modify | Add telemetry table-to-local and table-to-view mappings for pull/drain |
| `terraform/iceberg_tables.tf` | Modify | Add 7 `telemetry_*` Iceberg CREATE TABLE DDL and 4 `_current` views + 3 analytical views |
| `docs/contracts/ops-data-store.md` | Modify | Add telemetry table schemas to the boundary contract |
| `tests/test_telemetry_schemas.py` | Create | Unit tests for schema validation, field defaults, dtype mapping |
| `tests/test_ops_writer.py` | Modify | Add tests for telemetry table writes, emit() method, schema validation |
| `tests/test_sync_ops.py` | Modify | Add tests for telemetry table mappings in drain/pull |
| `scripts/build_lambda.py` | Modify | Add `telemetry_schemas.py` to `_LAMBDA_SCRIPTS` so Lambda can import it (ops_writer.py imports it) |

## Bundled Recommendations
- rec-364 (superseded by this work): "Unified telemetry write gateway with schema validation"
- rec-387 (superseded by this work): "validate.py: lint for raw JSONL writes that bypass log_writer"

## Infrastructure Dependencies
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| 7 `telemetry_*` Iceberg tables | create | Yes (compact writes to them) | Pre-merge (tables must exist for compaction) | `SELECT COUNT(*) FROM telemetry_sessions` returns 0 rows without error |
| 4 `telemetry_*_current` views | create | No (views are read convenience) | Post-merge (can be created after tables) | `SELECT * FROM telemetry_sessions_current LIMIT 1` returns empty result without error |
| 3 analytical views | create | No | Post-merge | `SELECT * FROM telemetry_session_summary_30d` returns empty result without error |
| Destroy commands: `terraform destroy -target=null_resource.create_telemetry_tables -target=null_resource.create_telemetry_views` | | | | |

## Acceptance Criteria
- [ ] `python -c "from scripts.telemetry_schemas import TelemetrySessions, TelemetryPhases, TelemetrySteps, TelemetryProcessEvents, TelemetryModelCalls, TelemetryTranscripts, TelemetryAgentInvocations"` imports all 7 schema classes without error
- [ ] `python -c "from scripts.ops_writer import TABLE_NAMES; assert 'telemetry_sessions' in TABLE_NAMES"` confirms telemetry tables are registered
- [ ] `python -c "from scripts.ops_writer import OpsWriter; w = OpsWriter(); w.emit('telemetry_sessions', {'session_id': 'test', 'workflow': 'executor', 'outcome': 'success'})"` writes to outbox without error (no S3 needed)
- [ ] `python -m pytest tests/test_telemetry_schemas.py tests/test_ops_writer.py tests/test_sync_ops.py -v` all pass
- [ ] `python -m scripts.validate` exits 0
- [ ] `terraform plan` shows 7 new table resources and 7 new view resources (no changes to existing resources)
- [ ] After `terraform apply`: `SELECT COUNT(*) FROM trading_formulas_db.telemetry_sessions` returns 0 rows without error
- [ ] After `terraform apply`: `SELECT * FROM trading_formulas_db.telemetry_sessions_current LIMIT 1` returns empty without error

## Verification Plan
| # | Action | Expected Outcome | Fix If |
|---|--------|-------------------|--------|
| 1 | Create a `TelemetrySessions` dataclass instance with only required fields (`session_id`, `workflow`, `outcome`, `started_at`, `premium_requests_total`, `process_event_count`, `rework_count`, `exception_count`, `execution_attempt`). Print it. | All required fields populated, optional fields are None, `ingested_at` and `trade_date` auto-populated | Dataclass __init__ or default logic is wrong |
| 2 | Call `TelemetrySessions.to_dict()` and pass the dict through schema validation. Add an unknown field `{"bogus_field": 123}` to the dict, validate again. | First call: valid dict. Second call: `bogus_field` dropped with warning logged | Validation does not filter unknown fields |
| 3 | Instantiate `OpsWriter()`, call `emit("telemetry_sessions", {...})` with a valid session dict locally (no S3). Check `logs/.ops-outbox/telemetry_sessions/` contains a JSONL file with the record. | File exists with one JSON line matching the input (plus auto-injected `ingested_at`, `trade_date`) | Outbox write path not wired for telemetry tables |
| 4 | Call `emit("telemetry_steps", {...})` with a valid step dict containing `array<string>` field `scope_drift_files`. Inspect outbox file. | Array field serialised as JSON array in JSONL | Array serialisation broken |
| 5 | Run `terraform plan` against the workspace. | 7 new `null_resource.create_telemetry_tables` and 7 new `null_resource.create_telemetry_views` resources. Zero changes to existing resources. | DDL syntax error or resource naming conflict |
| 6 | Run `terraform apply` (human-approved). Then run Athena query: `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='trading_formulas_db' AND table_name='telemetry_sessions' ORDER BY ordinal_position` | Returns all columns from the INTENT schema with correct types | Column types wrong in DDL |
| 7 | Write a test record to `telemetry_sessions` via OpsWriter S3 staging, then run `compact("telemetry_sessions", "2026-04-23")`. Query `SELECT * FROM telemetry_sessions WHERE session_id = '{test_id}'` via Athena. | Returns exactly 1 row matching the written record | Compaction dtype mismatch or staging prefix mismatch |
| 8 | Query `SELECT * FROM telemetry_sessions_current LIMIT 1` and all 3 analytical views and `telemetry_agent_invocations_current`. | All return empty results without error | View DDL references wrong table or column names |

## Constraints
- Python 3.12+, type hints required (copilot-instructions.md)
- Never raise exceptions during module import (Import Safety Patterns gotcha)
- `OpsWriter.emit()` must never raise to callers -- all failures logged as warnings
- Telemetry writes are no-ops when `PYTEST_CURRENT_TEST` is set (test isolation)
- `awswrangler` may not be available locally -- `compact()` gracefully returns 0 when unavailable
- Athena engine v3 required -- use `agent-platform-production` workgroup for all DDL and queries
- `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS` -- issue one column per statement if schema evolution needed later
- `_TABLE_DTYPES` must include explicit types for all `array<>` columns to prevent awswrangler null-inference failures
- Shell commands in this plan must be Bash-compatible (Windows Git Bash), not PowerShell
- Terraform `local-exec` provisioners use PowerShell (existing pattern in `iceberg_tables.tf`)
- `try()` must wrap `filemd5()` and `file()` on optional artifacts

## Context
- **Decision 50** (Append-Only Ops Data Store) established the Iceberg + staging + compaction pattern. This plan extends it.
- **Decision 51** (Local-First Outbox) established the outbox pattern for crash resilience. Telemetry tables use the same outbox.
- **Decision 34** (Unified Session Telemetry) is superseded by `INTENT-telemetry-system.md`.
- **INTENT-telemetry-system.md** is the authoritative spec. This plan implements Phase A only.
- **Telemetry health is CRITICAL**: 12 MB `.session-telemetry.jsonl`, 38% duplicate rate. The star schema design eliminates monolithic files.
- **awswrangler `fill_missing_columns_in_df=True` behaviour** (gotcha): Must provide explicit `_TABLE_DTYPES` for all `array<>` columns in telemetry tables to avoid `object`-typed null columns breaking compaction.
- **Iceberg integer promotion** (gotcha): Use `bigint` for all integer columns in DDL to avoid future promotion issues.
- **Existing OpsWriter has no schema validation** -- this plan adds it via the `emit()` method and `telemetry_schemas.py` dataclasses.
- The `emit()` method replaces the current scattered write functions (`write_session_envelope()`, `_append_step_telemetry()`, etc.) but those replacements happen in Phase B, not this plan. Phase A only builds the write infrastructure.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create `scripts/telemetry_schemas.py` -- Schema Definitions

Create `scripts/telemetry_schemas.py` containing:

1. **7 dataclasses** matching the INTENT-telemetry-system.md table schemas exactly:
   - `TelemetrySessions` -- 30 fields (session_id PK, workflow, branch, rec_ids array<string>, plan_slug, started_at, ended_at, duration_seconds, outcome, failure_reason, failure_phase, premium_requests_total, files_changed, lines_added, lines_removed, steps_total, steps_completed, process_event_count, rework_count, exception_count, scope_drift_files array<string>, pr_url, ci_outcome, model_primary, execution_attempt, parent_session_id, coverage_before, coverage_after, ingested_at, trade_date)
   - `TelemetryPhases` -- 20 fields (phase_id PK, session_id FK, phase, phase_order, started_at, ended_at, duration_seconds, outcome, attempt_number, max_attempts, model_used, premium_requests, tokens_input, tokens_output, revision_count, blocking_findings_count, plan_steps_json, metadata_json, ingested_at, trade_date)
   - `TelemetrySteps` -- 28 fields (step_id PK, session_id FK, phase_id FK, step_number, total_steps, title, target_file, action, started_at, ended_at, duration_seconds, outcome, model_used, premium_requests, tokens_input, tokens_output, acceptance_command, acceptance_passed, acceptance_duration_seconds, diff_stat, lines_added, lines_removed, retry_count, model_escalated_from, prompt_hash, transcript_path, ingested_at, trade_date)
   - `TelemetryProcessEvents` -- 17 fields (event_id PK, session_id FK, phase_id FK, step_id FK, rec_id, timestamp, tier, category, severity, description, root_cause, resolution, time_lost_seconds, rec_filed, detected_by, ingested_at, trade_date)
   - `TelemetryModelCalls` -- 19 fields (call_id PK, session_id FK, phase_id FK, step_id FK, invocation_id FK, timestamp, duration_seconds, provider, model, purpose, tokens_input, tokens_output, premium_requests, exit_code, copilot_session_id, prompt_hash, error, ingested_at, trade_date)
   - `TelemetryTranscripts` -- 15 fields (transcript_id PK, session_id FK, phase_id FK, step_id FK, invocation_id FK, timestamp, purpose, local_path, s3_key, size_bytes, token_count, model_used, rec_id, ingested_at, trade_date)
   - `TelemetryAgentInvocations` -- 19 fields (invocation_id PK, agent_name, trigger, started_at, ended_at, duration_seconds, outcome, model_used, provider, premium_requests, tokens_input, tokens_output, findings_count, recs_created, queue_entries_written, error, lambda_request_id, ingested_at, trade_date)

2. Each dataclass must have:
   - Type hints for all fields (str, int, float, bool, list[str], or None for nullable)
   - A `REQUIRED_FIELDS: ClassVar[set[str]]` listing non-nullable fields
   - A `TABLE_NAME: ClassVar[str]` (e.g., `"telemetry_sessions"`)

3. A module-level dict `TELEMETRY_TABLE_DTYPES` mapping each table name to its `_TABLE_DTYPES` entry (explicit Athena type overrides for `array<>`, `int`, `bigint` columns).

4. A module-level dict `TELEMETRY_TABLE_NAMES` listing all 7 table name strings.

5. A `validate_record(table_name: str, record: dict) -> dict` function that:
   - Looks up the schema for `table_name`
   - Drops unknown fields with `logger.warning`
   - Does NOT reject records with missing required fields (emits warning, returns record with nulls) -- forward compatibility
   - Returns the cleaned record

**Acceptance command:** `python -c "from scripts.telemetry_schemas import TELEMETRY_TABLE_NAMES; assert len(TELEMETRY_TABLE_NAMES) == 7"`

### Step 2: Create `tests/test_telemetry_schemas.py` -- Schema Tests

Create `tests/test_telemetry_schemas.py` with tests covering:

1. Each of the 7 dataclasses can be instantiated with only required fields (optional fields default to None)
2. `validate_record()` drops unknown fields and logs a warning
3. `validate_record()` passes through records with missing required fields (with warning)
4. `validate_record()` passes through a fully valid record unchanged
5. `TELEMETRY_TABLE_DTYPES` has entries for all 7 tables
6. Every `array<>` column in every table has an explicit dtype override (prevents the awswrangler null-inference gotcha)
7. `validate_record()` returns empty dict for an unrecognised table name (with warning)

**Acceptance command:** `python -m pytest tests/test_telemetry_schemas.py -v`

### Step 3: Extend `scripts/ops_writer.py` -- Register Telemetry Tables and Add `emit()`

Modify `scripts/ops_writer.py`:

1. Import `TELEMETRY_TABLE_NAMES` and `TELEMETRY_TABLE_DTYPES` from `scripts.telemetry_schemas`
2. Extend `TABLE_NAMES` by appending the 7 telemetry table names (keep existing 5 ops tables)
3. Merge `TELEMETRY_TABLE_DTYPES` into `_TABLE_DTYPES`
4. Add `emit(self, table: str, record: dict) -> None` method to `OpsWriter`:
   - Calls `validate_record(table, record)` from `telemetry_schemas`
   - Auto-injects `ingested_at` and `trade_date` via `setdefault` (same as `write()`)
   - Calls `self.write(table, cleaned_record)`
   - Never raises -- catches all exceptions
   - The `emit()` method is the recommended interface for telemetry tables; `write()` remains for ops tables (backward compatibility)

**Acceptance command:** `python -c "from scripts.ops_writer import TABLE_NAMES, OpsWriter; assert 'telemetry_sessions' in TABLE_NAMES; assert 'telemetry_agent_invocations' in TABLE_NAMES; assert hasattr(OpsWriter, 'emit')"`

### Step 3a: Add `telemetry_schemas.py` to Lambda Package

Modify `scripts/build_lambda.py`:

1. Add `"telemetry_schemas.py"` to the `_LAMBDA_SCRIPTS` list (ops_writer.py imports it at module level, so it must be in the Lambda package)

**Acceptance command:** `python -c "from scripts.build_lambda import _LAMBDA_SCRIPTS; assert 'telemetry_schemas.py' in _LAMBDA_SCRIPTS"`

### Step 4: Add OpsWriter Tests for Telemetry

Modify `tests/test_ops_writer.py`:

1. Add a `TestOpsWriterEmit` class with tests:
   - `test_emit_valid_telemetry_record` -- writes to S3, verifies `put_object` called with correct key prefix `staging/telemetry_sessions/trade_date=...`
   - `test_emit_drops_unknown_fields` -- verify unknown fields in input are not present in the S3 payload
   - `test_emit_missing_required_fields_still_writes` -- verify record with missing required fields still writes (with warning)
   - `test_emit_unknown_table_noop` -- verify emit with unrecognised table does nothing
   - `test_emit_outbox_fallback` -- verify outbox write when S3 unreachable, outbox file at `logs/.ops-outbox/telemetry_sessions/`
2. Add to `TestOpsWriterCompactAll`:
   - `test_compact_all_includes_telemetry_tables` -- verify `compact()` is called for all 12 tables (5 ops + 7 telemetry)

**Acceptance command:** `python -m pytest tests/test_ops_writer.py::TestOpsWriterEmit -v`

### Step 5: Extend `scripts/sync_ops.py` -- Telemetry Table Mappings

Modify `scripts/sync_ops.py`:

1. Add telemetry tables to `_TABLE_TO_LOCAL`:
   - `telemetry_sessions` -> `.telemetry-sessions.jsonl`
   - `telemetry_phases` -> `.telemetry-phases.jsonl`
   - `telemetry_steps` -> `.telemetry-steps.jsonl`
   - `telemetry_process_events` -> `.telemetry-process-events.jsonl`
   - `telemetry_model_calls` -> `.telemetry-model-calls.jsonl`
   - `telemetry_transcripts` -> `.telemetry-transcripts.jsonl`
   - `telemetry_agent_invocations` -> `.telemetry-agent-invocations.jsonl`

2. Add telemetry tables to `_TABLE_TO_VIEW`:
   - `telemetry_sessions` -> `telemetry_sessions_current` (view)
   - `telemetry_phases` -> `telemetry_phases_current` (view)
   - `telemetry_steps` -> `telemetry_steps_current` (view)
   - `telemetry_process_events` -> `telemetry_process_events` (table, no _current -- events are never updated)
   - `telemetry_model_calls` -> `telemetry_model_calls` (table, no _current -- calls are never updated)
   - `telemetry_transcripts` -> `telemetry_transcripts` (table, no _current -- transcript metadata is never updated)
   - `telemetry_agent_invocations` -> `telemetry_agent_invocations_current` (view -- findings processor emits updates with same invocation_id)

**Acceptance command:** `python -c "from scripts.sync_ops import _TABLE_TO_LOCAL; assert 'telemetry_sessions' in _TABLE_TO_LOCAL"`

### Step 6: Add sync_ops Tests for Telemetry Mappings

Modify `tests/test_sync_ops.py`:

1. Add test verifying all 7 telemetry tables appear in `_TABLE_TO_LOCAL`
2. Add test verifying all 7 telemetry tables appear in `_TABLE_TO_VIEW`
3. Add test verifying drain handles telemetry outbox files correctly (mock pattern consistent with existing tests)

**Acceptance command:** `python -m pytest tests/test_sync_ops.py::TestTelemetryMappings -v`

### Step 7: Add Terraform Iceberg Table DDL

Modify `terraform/iceberg_tables.tf`:

1. Add location entries in `locals.glue_tables` for all 7 telemetry tables:
   - Location: `s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_{name}/`
   - Columns matching the INTENT schema exactly
   - All integer columns use `bigint` (avoid promotion issues)
   - All partition columns: `trade_date date`

2. Add a new `locals.create_telemetry_table_queries` block with 7 CREATE TABLE DDL statements:
   - `telemetry_sessions` (30 columns + trade_date partition)
   - `telemetry_phases` (20 columns + trade_date partition)
   - `telemetry_steps` (27 columns + trade_date partition)
   - `telemetry_process_events` (17 columns + trade_date partition)
   - `telemetry_model_calls` (19 columns + trade_date partition)
   - `telemetry_transcripts` (15 columns + trade_date partition)
   - `telemetry_agent_invocations` (19 columns + trade_date partition)
   - All tables: `TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='gzip')`

3. Add `null_resource.create_telemetry_tables` resource (same `for_each` + PowerShell local-exec pattern as existing `create_iceberg_tables`)

**Acceptance command:** `cd terraform && terraform validate`

### Step 8: Add Terraform Athena Views

Continue modifying `terraform/iceberg_tables.tf`:

1. Add `locals.create_telemetry_view_queries` block with 7 views:

   **Current-state views (4):**
   - `telemetry_sessions_current` -- ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ingested_at DESC)
   - `telemetry_phases_current` -- ROW_NUMBER() OVER (PARTITION BY phase_id ORDER BY ingested_at DESC)
   - `telemetry_steps_current` -- ROW_NUMBER() OVER (PARTITION BY step_id ORDER BY ingested_at DESC)
   - `telemetry_agent_invocations_current` -- ROW_NUMBER() OVER (PARTITION BY invocation_id ORDER BY ingested_at DESC)

   **Analytical views (3):**
   - `telemetry_session_summary_30d` -- aggregation by workflow (count, success rate, avg duration, total cost, rework/exception counts)
   - `telemetry_phase_time_distribution` -- aggregation by phase (count, avg duration, p90 duration, total cost)
   - `telemetry_event_frequency_30d` -- aggregation by tier + category (count, affected sessions)

2. Add `null_resource.create_telemetry_views` resource (same pattern as `create_ops_views`), depends on `create_telemetry_tables`

**Acceptance command:** `cd terraform && terraform validate`

### Step 9: Update `docs/contracts/ops-data-store.md`

Modify `docs/contracts/ops-data-store.md`:

1. Add a "Telemetry Tables" section after the existing "Operational Tables" section
2. Document all 7 telemetry table schemas with column names, types, and descriptions (matching the INTENT document)
3. Document the 4 `_current` views and 3 analytical views
4. Note that telemetry tables follow the same conventions (trade_date partition, ingested_at version key, INSERT-only, parquet+gzip)
5. Reference `docs/INTENT-telemetry-system.md` as the authoritative spec

**Acceptance command:** `grep -c "telemetry_sessions" docs/contracts/ops-data-store.md`

### Step 10: Run pytest -- all tests must pass

```bash
python -m pytest tests/test_telemetry_schemas.py tests/test_ops_writer.py tests/test_sync_ops.py -v
```

Then run full suite:

```bash
python -m pytest tests/ -x
```

### Step 11: Run validate.py -- must exit 0

```bash
python -m scripts.validate
```

### Step 12: Build and Deploy Lambda

Since `ops_writer.py` and `telemetry_schemas.py` are Lambda-packaged files:

1. Run `python -m scripts.build_lambda` to rebuild the zip with updated modules
2. Run `python -m scripts.build_lambda --deploy` to upload to S3 and update Lambda function code
3. Run `python -m scripts.run_scheduled_agent --smoke-test doc-freshness` to verify Lambda import succeeds (no `ModuleNotFoundError` on `telemetry_schemas`)

**Acceptance command:** `python -m scripts.build_lambda`

### Step 13: Execute Verification Plan

Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

Note: Verification Plan steps 5-8 (Terraform) require human approval for `terraform apply`. Present the plan output and wait for approval.

### Step 14: Report

Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
