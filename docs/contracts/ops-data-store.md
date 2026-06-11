# Boundary Contract: Ops Data Store

> **Decision 84 (2026-06-11) supersedes the two-backend split below for `ops_recommendations`,
> `ops_decisions`, and `ops_priority_queue`: all three are on the DuckLake closed boundary as
> the SOLE backend (no `OPS_STORAGE_BACKEND` flag, no Athena path, no offline outbox; rec ids
> writer-allocated via `file_ops`; reads via named verbs). `ops_session_log` /
> `ops_execution_plans` remain as described pending T2.26. Authoritative topology:
> `docs/contracts/read-engine.yaml` (version 3) + `docs/INTENT-ducklake-consolidation.md`.
> Athena/Iceberg sections below are retained for the demolition audit trail.**

## Overview

Operational structured logs were stored across two backends (T2.19 cutover, Decision 81):

**ops_recommendations** -- DuckLake closed boundary (T2.19 / Decision 81 cl.7).
- Authoritative store: Neon serverless-Postgres DuckLake catalog (`/ducklake/` S3 prefix).
- Write path ONLY: `ops_data_portal.file_rec` / `update_rec` -> ducklake_writer Function URL.
- Read path ONLY: `make_reader()` -> ducklake_reader Function URL.
- No OpsWriter/Iceberg staging, no Athena `ops_recommendations_current` view (DROPPED at T2.19).
- No Athena fallback on the ducklake backend (Decision 81 cl.7 hard constraint).

**All other ops_* tables** (execution_plans, session_log, decisions, priority_queue) --
Iceberg/Athena (unchanged).
- Authoritative store: `agent-platform-data-lake` S3 bucket, `iceberg/` prefix.
- Write path: `OpsWriter.write()` -> S3 staging -> `OpsWriter.compact()` -> Iceberg via awswrangler.
- Read path: `DuckDBIcebergReader` first; Athena fallback (CD.8/CD.15 escape hatch retained until those tables migrate).
- Current state via `ops_*_current` ROW_NUMBER() views (decisions + priority_queue views retained).

**Database (non-recs Iceberg tables):** `agent_platform` (Glue catalog, Athena engine v3, personal account).
**Workgroup:** `agent-platform-production` (engine v3 required for Iceberg operations).

---

## Table Schemas

All tables follow these conventions:
- `trade_date` (date) -- partition key, matching `market_data` table convention
- `ingested_at` (timestamp) -- version key for ROW_NUMBER() deduplication in views
- Parquet + gzip compression
- `write.metadata.delete-after-commit.enabled = true`
- `write.metadata.previous-versions-max = 10`
- INSERT-only semantics (no MERGE, no DELETE except test cleanup)

### ops_recommendations (DuckLake backend -- Decision 81 cl.7)

Recommendation state snapshots. Authoritative store: Neon DuckLake catalog via the closed
ducklake_writer / ducklake_reader Lambda boundary. Local `logs/.recommendations-log.jsonl`
is a read-only cache rebuilt from the warehouse via `sync_ops pull`.
No `ops_recommendations_current` Athena view -- DROPPED at T2.19 (Decision 81 cl.7 / T2.7 scoped partial).

| Column | Type | Description |
|--------|------|-------------|
| id | string | Recommendation ID (e.g., rec-001) |
| date | string | ISO date of creation (YYYY-MM-DD) |
| title | string | Concise description (< 100 chars) |
| source | string | Origin: executor-supervision, code-review, planning, brainstorm |
| effort | string | XS, S, M, L, or XL |
| priority | string | Critical, High, Medium, or Low |
| status | string | open, closed, failed, declined, or superseded |
| automatable | boolean | Whether the executor can handle this |
| risk | string | low, medium, or high |
| file | string | Primary target file path |
| context | string | Why this rec exists (self-contained for executor) |
| acceptance | string | Shell command returning 0 on success |
| dependencies | array\<string\> | Blocking rec IDs |
| tags | array\<string\> | Categorisation tags |
| resolution | string | Why declined or superseded (when applicable) |
| execution_result | string | success, failure, manual, or already_implemented |
| execution_date | string | ISO-8601 timestamp set by executor on close |
| execution_branch | string | Branch name set by executor |
| execution_pr_url | string | PR URL set by executor |
| execution_premium_requests | double | Cost in premium requests, set by executor |
| execution_steps | int | Step count, set by executor |
| ingested_at | timestamp | Pipeline ingestion timestamp (version key) |
| trade_date | date | Partition key (date of ingestion) |

### ops_execution_plans

Mirrors `logs/.execution-plans.jsonl`. One row per planning run.

| Column | Type | Description |
|--------|------|-------------|
| plan_id | string | Unique plan ID (UUID) |
| rec_id | string | Recommendation ID this plan targets |
| branch | string | Git branch for this execution |
| plan_type | string | IMPLEMENTATION or STRATEGIC |
| verification_tier | string | V1, V2, or V3 |
| steps_json | string | JSON-encoded ordered execution steps array |
| scope_json | string | JSON-encoded scope table |
| model_used | string | Model ID used for planning (Copilot SDK format) |
| critique_result | string | APPROVED, NEEDS_REVISION, or EXHAUSTED |
| ingested_at | timestamp | Pipeline ingestion timestamp (version key) |
| trade_date | date | Partition key (date of ingestion) |

### ops_session_log

Mirrors `logs/.session-telemetry.jsonl`. One row per session event.

| Column | Type | Description |
|--------|------|-------------|
| session_id | string | Unique session ID (UUID) |
| date | string | ISO date (YYYY-MM-DD) |
| branch | string | Git branch active during session |
| session_type | string | executor-supervision, planning, implementation, strategic-review |
| recs_attempted | array\<string\> | Rec IDs attempted this session |
| recs_closed | array\<string\> | Rec IDs successfully closed this session |
| summary | string | Human-readable session summary |
| premium_requests_used | double | Total premium requests consumed |
| duration_minutes | int | Session wall-clock duration |
| ingested_at | timestamp | Pipeline ingestion timestamp (version key) |
| trade_date | date | Partition key (date of ingestion) |

### ops_decisions

Mirrors `docs/DECISIONS.md`. One row per decision state snapshot.
There is no existing JSONL write site for decisions -- Phase 2 will add write-through
from the decision management workflow.

| Column | Type | Description |
|--------|------|-------------|
| decision_id | int | Sequential decision number (e.g., 50) |
| title | string | Decision title |
| status | string | Decided, Superseded, or Open |
| problem | string | Problem statement |
| decision_text | string | The decision made |
| context | string | Why this decision was made |
| decided_date | string | ISO date decided |
| related_decisions | array\<int\> | Related decision IDs |
| ingested_at | timestamp | Pipeline ingestion timestamp (version key) |
| trade_date | date | Partition key (date of ingestion) |

### ops_priority_queue

Mirrors `priority-queue/.priority-queue.jsonl` (S3 key). One row per queue entry per run.
All entries from a single curator run share the same `queue_run_id`.

| Column | Type | Description |
|--------|------|-------------|
| queue_run_id | string | UUID shared by all entries in one curator run |
| rank | int | Priority rank within the run (1 = highest) |
| rec_id | string | Recommendation ID |
| mode | string | solo or compound |
| compound_with | array\<string\> | Other rec IDs in compound run |
| rationale | string | Why this rec is ranked here |
| gates | array\<string\> | Blocking gate conditions |
| estimated_premium_requests | double | Estimated cost for this rec |
| north_star_impact | string | How this serves the North Star |
| decay_date | string | Date after which this entry is stale |
| status | string | queued, executing, or done |
| ingested_at | timestamp | Pipeline ingestion timestamp (version key) |
| trade_date | date | Partition key (date of ingestion) |

---

## View Definitions (Athena -- non-recs Iceberg tables only)

Views expose the current state of each append-only Iceberg table using ROW_NUMBER() deduplication.
All views are in database `agent_platform` (personal account).

`ops_recommendations_current` -- DROPPED at T2.19 (Decision 81 cl.7). No replacement view;
recs current state is served exclusively by the ducklake_reader Function URL.

### ops_decisions_current

```sql
CREATE OR REPLACE VIEW agent_platform.ops_decisions_current AS
SELECT * EXCEPT (row_num)
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY ingested_at DESC) AS row_num
  FROM agent_platform.ops_decisions
)
WHERE row_num = 1
```

### ops_priority_queue_current

Returns only entries from the most recent curator run.

```sql
CREATE OR REPLACE VIEW agent_platform.ops_priority_queue_current AS
SELECT *
FROM agent_platform.ops_priority_queue
WHERE queue_run_id = (
  SELECT queue_run_id
  FROM agent_platform.ops_priority_queue
  ORDER BY ingested_at DESC
  LIMIT 1
)
```

---

## S3 Prefix Layout

All ops data lives in bucket `agent-platform-agent-logs`.

```
agent-platform-agent-logs/
  staging/
    ops_recommendations/
      trade_date=YYYY-MM-DD/
        batch-{uuid}.jsonl      <- OpsWriter.write() staging files
    ops_execution_plans/
      trade_date=YYYY-MM-DD/
        batch-{uuid}.jsonl
    ops_session_log/
      trade_date=YYYY-MM-DD/
        batch-{uuid}.jsonl
    ops_decisions/
      trade_date=YYYY-MM-DD/
        batch-{uuid}.jsonl
    ops_priority_queue/
      trade_date=YYYY-MM-DD/
        batch-{uuid}.jsonl
  iceberg/
    ops_recommendations/        <- Iceberg table data
    ops_execution_plans/
    ops_session_log/
    ops_decisions/
    ops_priority_queue/
  tmp/                          <- awswrangler temporary files during compaction
```

---

## Write Flow

```
local JSONL write
    --> s3_log_store.append_jsonl / overwrite_jsonl
        --> OpsWriter.write(table, entry)   [best-effort, never propagates failure]
            --> S3 put_object to staging/{table}/trade_date=YYYY-MM-DD/batch-{uuid}.jsonl

session_postflight.run_auto()
    --> OpsWriter.compact_all()             [best-effort, never propagates failure]
        --> for each table:
            OpsWriter.compact(table, trade_date)
                --> list staging/{table}/trade_date=YYYY-MM-DD/ files
                --> read all JSONL entries into pandas DataFrame
                --> awswrangler.athena.to_iceberg(df, ..., mode="append")
                --> delete processed staging files

Athena views (ops_*_current)
    --> ROW_NUMBER() deduplication across ingested_at versions
    --> always returns latest snapshot per entity
```

---

## Key-to-Table Routing Map

Used by `scripts/s3_log_store.py` write-through logic.

| S3 / local key | Iceberg table | Notes |
|----------------|---------------|-------|
| `.recommendations-log.jsonl` | `ops_recommendations` | write-through via append_jsonl |
| `.execution-plans.jsonl` | `ops_execution_plans` | write-through via append_jsonl |
| `.session-telemetry.jsonl` | `ops_session_log` | write-through via append_jsonl |
| `priority-queue/.priority-queue.jsonl` | `ops_priority_queue` | write-through via overwrite_jsonl (shared queue_run_id per call) |
| `docs/DECISIONS.md` (manual) | `ops_decisions` | No automated write-through -- deferred to Phase 2 |

---

## Column Conventions

- `trade_date` (date, partition key): always `datetime.date.today().isoformat()` at write time
- `ingested_at` (timestamp, version key): always `datetime.datetime.now(datetime.UTC).isoformat()` at write time
- Both columns are injected by `OpsWriter.write()`, not the caller
- These conventions match the `market_data` table pattern in `terraform/iceberg_tables.tf`

---

## Graceful Degradation

`OpsWriter` is designed for best-effort writes. Callers (s3_log_store.py, session_postflight.py)
must never fail due to OpsWriter errors.

| Condition | Behaviour |
|-----------|-----------|
| `S3_LOG_BUCKET` env var unset | `write()` is a no-op (local-only mode) |
| `PYTEST_CURRENT_TEST` env var set | `write()` and `compact()` skip all S3/Athena calls |
| `boto3` unavailable | `write()` logs warning and returns |
| `awswrangler` unavailable | `compact()` logs warning, returns 0 |
| S3 upload failure | `write()` logs warning and returns (never raises) |
| Athena compaction failure | `compact()` logs warning, returns 0 (staging files preserved) |

---

## Related

- `scripts/ops_writer.py` -- OpsWriter class implementation
- `scripts/s3_log_store.py` -- write-through routing
- `scripts/session_postflight.py` -- compact_all() call in session-close
- `scripts/build_lambda.py` -- ops_writer.py and telemetry_schemas.py included in `_LAMBDA_SCRIPTS`
- `terraform/iceberg_tables.tf` -- table and view DDL
- Decision 50 (`docs/DECISIONS.md`) -- Append-Only Ops Data Store
- Decision 45 (`docs/DECISIONS.md`) -- S3 as Authoritative Source (superseded by Decision 50)
- Decision 48 (`docs/DECISIONS.md`) -- Verification Tier Classification

---

## Telemetry Tables

The 7 telemetry tables form a star schema for workflow observability. They follow the same
conventions as the operational tables above (trade_date partition, ingested_at version key,
INSERT-only, parquet+gzip).

**Authoritative spec:** `docs/INTENT-telemetry-system.md` (Phase A).
**Write interface:** `OpsWriter.emit(table, record)` -- schema-validated, never raises.
**Schema validation:** `scripts/telemetry_schemas.py` -- `validate_record()` drops unknown
fields and passes through missing required fields with a warning (forward-compatibility).

### telemetry_sessions

One row per workflow invocation. Current state via `telemetry_sessions_current` view.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| session_id | string | No | PK. UUID. |
| workflow | string | No | Enum: plan, implement, executor, scheduled_agent, strategic_review. |
| branch | string | Yes | Git branch. Null for scheduled agents. |
| rec_ids | array\<string\> | Yes | Recommendation IDs addressed. |
| plan_slug | string | Yes | Plan file slug. |
| started_at | timestamp | No | Session start. |
| ended_at | timestamp | Yes | Session end. |
| duration_seconds | bigint | Yes | Wall-clock duration. |
| outcome | string | No | Enum: success, failed, abandoned, partial, timeout, already_implemented. |
| failure_reason | string | Yes | Structured failure class. |
| failure_phase | string | Yes | Which phase failed. |
| premium_requests_total | double | No | Aggregated billing cost. |
| files_changed | bigint | Yes | Total files modified. |
| lines_added | bigint | Yes | Lines added. |
| lines_removed | bigint | Yes | Lines removed. |
| steps_total | bigint | Yes | Planned steps. |
| steps_completed | bigint | Yes | Completed steps. |
| process_event_count | bigint | No | Total process events. |
| rework_count | bigint | No | Count of tier=rework events. |
| exception_count | bigint | No | Count of tier=exception events. |
| scope_drift_files | array\<string\> | Yes | Files changed not in plan scope. |
| pr_url | string | Yes | GitHub PR URL. |
| ci_outcome | string | Yes | Enum: passed, failed, timeout, skipped. |
| model_primary | string | Yes | Primary model used. |
| execution_attempt | bigint | No | Retry number (1 = first). |
| parent_session_id | string | Yes | For retries, links to original. |
| coverage_before | double | Yes | Test coverage % at session start. |
| coverage_after | double | Yes | Test coverage % at session end. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_phases

One row per phase within a session. Current state via `telemetry_phases_current` view.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| phase_id | string | No | PK. UUID. |
| session_id | string | No | FK to telemetry_sessions. |
| phase | string | No | Phase name (preflight, plan_generation, critique, etc.). |
| phase_order | bigint | No | Sequence within session. |
| started_at | timestamp | No | Phase start. |
| ended_at | timestamp | Yes | Phase end. |
| duration_seconds | bigint | Yes | Duration. |
| outcome | string | No | Enum: success, failed, skipped, retried, escalated. |
| attempt_number | bigint | No | Attempt within phase. |
| max_attempts | bigint | Yes | Configured max attempts. |
| model_used | string | Yes | Model for this phase. |
| premium_requests | double | No | Cost of phase. |
| tokens_input | bigint | Yes | Input tokens. |
| tokens_output | bigint | Yes | Output tokens. |
| revision_count | bigint | Yes | Critique/refinement revision count. |
| blocking_findings_count | bigint | Yes | Code review blocking findings. |
| plan_steps_json | string | Yes | JSON-encoded plan steps. |
| metadata_json | string | Yes | Phase-specific metadata blob. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_steps

One row per implementation step. Current state via `telemetry_steps_current` view.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| step_id | string | No | PK. UUID. |
| session_id | string | No | FK to telemetry_sessions. |
| phase_id | string | No | FK to telemetry_phases. |
| step_number | bigint | No | 1-indexed step. |
| total_steps | bigint | No | Total planned steps. |
| title | string | No | Step title from plan. |
| target_file | string | Yes | Primary file modified. |
| action | string | Yes | Enum: create, modify, delete. |
| started_at | timestamp | No | Step start. |
| ended_at | timestamp | Yes | Step end. |
| duration_seconds | bigint | Yes | Duration. |
| outcome | string | No | Enum: success, failed, retried, skipped, ghost_step. |
| model_used | string | Yes | Model used. |
| premium_requests | double | No | Cost. |
| tokens_input | bigint | Yes | Input tokens. |
| tokens_output | bigint | Yes | Output tokens. |
| acceptance_command | string | Yes | Acceptance check run. |
| acceptance_passed | boolean | Yes | Whether acceptance passed. |
| acceptance_duration_seconds | bigint | Yes | How long acceptance took. |
| diff_stat | string | Yes | Git diff summary. |
| lines_added | bigint | Yes | Lines added. |
| lines_removed | bigint | Yes | Lines removed. |
| retry_count | bigint | No | Times step was retried. |
| model_escalated_from | string | Yes | Previous model if escalated. |
| prompt_hash | string | Yes | Prompt version hash. |
| transcript_path | string | Yes | Path to transcript. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_process_events

One row per notable event (replaces legacy friction concept). Append-only (no _current view).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| event_id | string | No | PK. UUID. |
| session_id | string | Yes | FK to telemetry_sessions. |
| phase_id | string | Yes | FK to telemetry_phases. |
| step_id | string | Yes | FK to telemetry_steps. |
| rec_id | string | Yes | Recommendation being worked on. |
| timestamp | timestamp | No | When event was observed. |
| tier | string | No | Enum: decision, rework, exception, anomaly. |
| category | string | No | Canonical category (see INTENT). |
| severity | string | No | Enum: info, warning, error, critical. |
| description | string | No | Human-readable description. |
| root_cause | string | Yes | Structured root cause. |
| resolution | string | Yes | How resolved. |
| time_lost_seconds | bigint | Yes | Time consumed by this event. |
| rec_filed | string | Yes | Rec filed to address this event. |
| detected_by | string | No | Enum: executor_script, recovery_agent, cloud_analysis_agent, manual. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_model_calls

One row per LLM invocation. Append-only (no _current view).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| call_id | string | No | PK. UUID. |
| session_id | string | Yes | FK to telemetry_sessions. |
| phase_id | string | Yes | FK to telemetry_phases. |
| step_id | string | Yes | FK to telemetry_steps. |
| invocation_id | string | Yes | FK to telemetry_agent_invocations. |
| timestamp | timestamp | No | Call start. |
| duration_seconds | bigint | Yes | Latency. |
| provider | string | No | Enum: copilot_cli, copilot_sdk, github_models. |
| model | string | No | Model identifier. |
| purpose | string | No | Call purpose enum (see INTENT). |
| tokens_input | bigint | Yes | Input tokens. |
| tokens_output | bigint | Yes | Output tokens. |
| premium_requests | double | No | Billing unit. |
| exit_code | bigint | Yes | LLM call exit code. |
| copilot_session_id | string | Yes | Copilot CLI session ID. |
| prompt_hash | string | Yes | Prompt version hash. |
| error | string | Yes | Error message if failed. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_transcripts

One row per transcript file (metadata index). Append-only (no _current view).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| transcript_id | string | No | PK. UUID. |
| session_id | string | Yes | FK to telemetry_sessions. |
| phase_id | string | Yes | FK to telemetry_phases. |
| step_id | string | Yes | FK to telemetry_steps. |
| invocation_id | string | Yes | FK to telemetry_agent_invocations. |
| timestamp | timestamp | No | When transcript was produced. |
| purpose | string | No | Purpose enum. |
| local_path | string | No | Local filesystem path. |
| s3_key | string | Yes | S3 key once uploaded. |
| size_bytes | bigint | No | File size. |
| token_count | bigint | Yes | Estimated token count. |
| model_used | string | Yes | Model that produced this. |
| rec_id | string | Yes | Rec ID if applicable. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### telemetry_agent_invocations

One row per scheduled Lambda agent invocation. Standalone (no FK to sessions).
Current state via `telemetry_agent_invocations_current` view.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| invocation_id | string | No | PK. UUID. |
| agent_name | string | No | Agent identifier. |
| trigger | string | No | Enum: eventbridge, manual, smoke_test. |
| started_at | timestamp | No | Lambda start. |
| ended_at | timestamp | Yes | Lambda end. |
| duration_seconds | bigint | Yes | Duration. |
| outcome | string | No | Enum: success, failed, timeout, throttled. |
| model_used | string | Yes | Model used. |
| provider | string | Yes | Enum: copilot_sdk, github_models. |
| premium_requests | double | No | Billing unit. |
| tokens_input | bigint | Yes | Input tokens. |
| tokens_output | bigint | Yes | Output tokens. |
| findings_count | bigint | Yes | Findings produced. |
| recs_created | bigint | Yes | Recs auto-filed. |
| queue_entries_written | bigint | Yes | Priority queue entries. |
| error | string | Yes | Error if failed. |
| lambda_request_id | string | Yes | AWS Lambda request ID. |
| ingested_at | timestamp | No | Version key. |
| trade_date | date | No | Partition key. |

### Telemetry Views

| View | Partition By | Purpose |
|------|-------------|---------|
| `telemetry_sessions_current` | session_id | Latest snapshot per session |
| `telemetry_phases_current` | phase_id | Latest snapshot per phase |
| `telemetry_steps_current` | step_id | Latest snapshot per step |
| `telemetry_agent_invocations_current` | invocation_id | Latest snapshot per agent invocation |
| `telemetry_session_summary_30d` | -- | Aggregation by workflow (30-day rolling) |
| `telemetry_phase_time_distribution` | -- | Aggregation by phase (30-day rolling) |
| `telemetry_event_frequency_30d` | -- | Aggregation by tier+category (30-day rolling) |
