# Intent: Unified Telemetry System

This document defines the intent, vision, data model, and design boundaries for the repository's telemetry infrastructure. It is the authoritative specification for how every workflow -- manual, autonomous, and scheduled -- captures, stores, and queries operational data.

**Supersedes:** `docs/INTENT-recommendation-executor.md` sections on Telemetry Requirements and Storage. The executor intent document remains authoritative for executor architecture and recommendation lifecycle; this document governs all telemetry concerns.

**Supersedes decisions:** Decision 34 (Unified Cross-Workflow Session Telemetry), Decision 50 (Append-Only Ops Data Store) telemetry-specific aspects. The ops data store pattern (outbox + Iceberg compaction) is retained and generalized; the specific table schemas and write paths are replaced by this document.

**Builds on:** Decision 51 (Local-First Outbox + Bidirectional Sync). The telemetry write path follows the same outbox pattern (`OpsWriter`) established for ops tables -- local resilience via outbox, best-effort S3 staging, Iceberg compaction at session close.

**Supersedes ROADMAP Wave 2 deliverables:** Wave 2 ("Telemetry Root Cause Fix") described `scripts/log_writer.py` and `docs/contracts/log-storage.md`. This intent document is the broader redesign that subsumes those deliverables. The duplicate rate fix is achieved by the new schema design (no more monolithic `.session-telemetry.jsonl`).

---

## North Star

The telemetry system exists to make the autonomous self-improving loop observable and controllable. Every workflow execution -- a human-driven `/plan` session, an autonomous executor run, a scheduled Lambda agent -- produces structured telemetry that flows into a star schema queryable via Athena. This data enables:

1. **Cost control** -- per-model, per-phase, per-recommendation cost attribution
2. **Process quality measurement** -- success rates, rework rates, escalation frequency
3. **Autonomous anomaly detection** -- a cloud agent statistically identifies outlier sessions and generates improvement recommendations
4. **Prompt performance tracking** -- correlate prompt versions (via hash) with outcomes to measure whether prompt changes improve results
5. **System health dashboards** -- are the scheduled agents running? Is the executor improving over time? Where does wall-clock time go?

The telemetry system is not optional infrastructure. It is the feedback sensor that closes the RSI (Recursive Self-Improvement) loop. Without trustworthy telemetry, the system cannot identify its own weaknesses, cannot prioritize improvements, and cannot verify that changes actually helped.

---

## Architecture Overview

### Storage: Outbox + Iceberg Compaction

All telemetry follows the same write path established by Decision 51 (Local-First Outbox) and the existing `OpsWriter` class:

```
Producer (executor, agent, Lambda)
    |
    v
emit(table, record)                 -- unified write interface
    |
    +---> Local outbox (synchronous, never fails)
    |     logs/.ops-outbox/{table}/{uuid}.jsonl
    |
    +---> S3 staging (best-effort write-through)
          s3://{bucket}/staging/{table}/trade_date={date}/batch-{uuid}.jsonl

          ... later, at session close or on schedule ...

Compaction (via OpsWriter.compact_all())
    |
    v
Iceberg table in trading_formulas_db
    s3://{bucket}/iceberg/{table}/
```

**Local outbox** is the system of record for in-flight sessions. It provides crash recovery, offline resilience (works without AWS credentials), and test isolation (no external writes during pytest). This is the same outbox pattern from Decision 51 -- `logs/.ops-outbox/{table}/` -- extended to support the telemetry tables.

**S3 staging** is best-effort write-through. If it fails, the outbox retains the data. Compaction catches up. Stale outbox entries (>24h) are flagged by `validate.py` per Decision 51.

**Iceberg compaction** runs at session close (for executor/manual sessions) and on schedule (for Lambda-produced data). It reads staging files, merges into the Iceberg table via `awswrangler.athena.to_iceberg(mode="append")`, and deletes processed staging files.

**Lambda write path:** Lambda functions (scheduled agents, findings processor) are stateless and have no persistent local filesystem. In Lambda context (detected via `AWS_LAMBDA_FUNCTION_NAME` env var), writes go directly to S3 staging, bypassing the local outbox.

### Database: trading_formulas_db (telemetry_ prefix)

All telemetry tables live in the existing `trading_formulas_db` Glue database, using a `telemetry_` prefix to distinguish them from domain tables (`market_data`, `formula_lineage`, etc.) and operational tables (`ops_recommendations`, `ops_decisions`, etc.).

**Rationale:** A single database avoids cross-database JOIN complexity when correlating telemetry with recommendation entities, reduces Terraform scaffolding, and simplifies Glue Catalog management. Per-table Iceberg properties (VACUUM, OPTIMIZE) and IAM resource-level permissions provide the same isolation guarantees that a separate database would offer. The `telemetry_` prefix provides clear logical separation.

### Unified Write Interface

The existing `OpsWriter` class (in `scripts/ops_writer.py`) is extended to support the 7 telemetry tables alongside the existing ops tables. A unified write interface (`emit()` or equivalent) replaces the current scattered write functions: `write_run_summary()`, `emit_failure_summary()`, `_append_step_telemetry()`, `_capture_executor_telemetry()`, `write_session_envelope()`.

The write interface:
- Accepts a table name and record dict
- Auto-populates `ingested_at` and `trade_date` if missing
- Writes to the local outbox (synchronous, never raises)
- Best-effort write-through to S3 staging
- Performs schema validation: unknown fields are dropped with a warning, missing required fields proceed with nulls and a warning

This ensures forward compatibility (new code writing to old schemas) without silent data loss. The specific module structure and function signatures are implementation details to be resolved in the Phase A plan.

---

## Data Model: 7-Table Star Schema

### Relationships

```
telemetry_sessions (1)
    |-- (N) telemetry_phases
    |       |-- (N) telemetry_steps
    |       |-- (N) telemetry_model_calls
    |       |-- (N) telemetry_process_events
    |       |-- (N) telemetry_transcripts
    |-- (N) telemetry_model_calls       (phase-less calls)
    |-- (N) telemetry_process_events    (session-level events)
    |-- (N) telemetry_transcripts       (session-level transcripts)

telemetry_agent_invocations (standalone, no FK to sessions)
    |-- (N) telemetry_model_calls       (via invocation_id)
    |-- (N) telemetry_transcripts       (via invocation_id)
```

Every table is partitioned by `trade_date` (date). Every table has `ingested_at` (timestamp) for deduplication via `ROW_NUMBER()` views where needed. All primary keys are UUIDs.

---

### Table 1: telemetry_sessions

**Grain:** One row per workflow invocation (a `/plan` session, an `/implement` session, a single executor recommendation run, a strategic review).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `session_id` | string | No | PK. UUID generated at session start. |
| `workflow` | string | No | Enum: `plan`, `implement`, `executor`, `scheduled_agent`, `strategic_review`. |
| `branch` | string | Yes | Git branch. Null for scheduled agents. |
| `rec_ids` | array&lt;string&gt; | Yes | Recommendation IDs addressed. Null for non-rec work. |
| `plan_slug` | string | Yes | Plan file slug. Null if no plan. |
| `started_at` | timestamp | No | Session start (ISO-8601). |
| `ended_at` | timestamp | Yes | Session end. Null if crashed/abandoned. |
| `duration_seconds` | int | Yes | Wall-clock duration. |
| `outcome` | string | No | Enum: `success`, `failed`, `abandoned`, `partial`, `timeout`, `already_implemented`. |
| `failure_reason` | string | Yes | Structured failure class (see Process Events taxonomy). |
| `failure_phase` | string | Yes | Which phase failed. |
| `premium_requests_total` | double | No | Aggregated billing cost. |
| `files_changed` | int | Yes | Total files modified. |
| `lines_added` | int | Yes | |
| `lines_removed` | int | Yes | |
| `steps_total` | int | Yes | Planned steps. |
| `steps_completed` | int | Yes | Actually completed steps. |
| `process_event_count` | int | No | Total process events in this session. |
| `rework_count` | int | No | Count of tier=rework events. |
| `exception_count` | int | No | Count of tier=exception events. |
| `scope_drift_files` | array&lt;string&gt; | Yes | Files changed that were not in the plan scope. |
| `pr_url` | string | Yes | GitHub PR URL. |
| `ci_outcome` | string | Yes | Enum: `passed`, `failed`, `timeout`, `skipped`. |
| `model_primary` | string | Yes | Primary model used. |
| `execution_attempt` | int | No | Retry number. 1 = first attempt. |
| `parent_session_id` | string | Yes | For retries, links to the original session. |
| `coverage_before` | double | Yes | Test coverage % at session start. |
| `coverage_after` | double | Yes | Test coverage % at session end. |
| `ingested_at` | timestamp | No | Write timestamp. |
| `trade_date` | date | No | Partition key. |

---

### Table 2: telemetry_phases

**Grain:** One row per phase within a session. A session has 1-N phases in sequence.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `phase_id` | string | No | PK. UUID. |
| `session_id` | string | No | FK to `telemetry_sessions`. |
| `phase` | string | No | Enum: `preflight`, `plan_generation`, `critique`, `refinement`, `implementation`, `validation`, `acceptance`, `code_review`, `code_review_fix`, `ci_wait`, `ci_fix`, `merge`, `merge_recovery`, `cleanup`, `postflight`. |
| `phase_order` | int | No | Sequence within session (1, 2, 3...). |
| `started_at` | timestamp | No | Phase start. |
| `ended_at` | timestamp | Yes | Phase end. Null if ongoing/crashed. |
| `duration_seconds` | int | Yes | |
| `outcome` | string | No | Enum: `success`, `failed`, `skipped`, `retried`, `escalated`. |
| `attempt_number` | int | No | Which attempt of this phase (1 = first). |
| `max_attempts` | int | Yes | Configured max attempts for this phase. |
| `model_used` | string | Yes | Model for this phase. |
| `premium_requests` | double | No | Cost of this phase. |
| `tokens_input` | int | Yes | Total input tokens consumed in this phase. |
| `tokens_output` | int | Yes | Total output tokens generated in this phase. |
| `revision_count` | int | Yes | For critique/refinement: number of revisions. |
| `blocking_findings_count` | int | Yes | For code_review: number of blocking findings. |
| `plan_steps_json` | string | Yes | For plan_generation: JSON array of structured plan steps (preserves step data for plans that are never fully executed). |
| `metadata_json` | string | Yes | JSON blob for phase-specific data not in named columns. |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

**Design note:** `attempt_number` and `max_attempts` capture the retry structure directly. When the planning phase escalates models after 2 failures, you see three `telemetry_phases` rows: `(phase=plan_generation, attempt_number=1, outcome=failed)`, `(phase=plan_generation, attempt_number=2, outcome=failed)`, `(phase=plan_generation, attempt_number=3, outcome=success, model_used=claude-opus-4.6)`. The retry graph is a simple query: `WHERE session_id = X ORDER BY phase_order`.

---

### Table 3: telemetry_steps

**Grain:** One row per implementation step within a plan.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `step_id` | string | No | PK. UUID. |
| `session_id` | string | No | FK to `telemetry_sessions`. |
| `phase_id` | string | No | FK to `telemetry_phases` (the implementation phase). |
| `step_number` | int | No | 1-indexed step within plan. |
| `total_steps` | int | No | Total planned steps. |
| `title` | string | No | Step title from plan. |
| `target_file` | string | Yes | Primary file being modified. |
| `action` | string | Yes | Enum: `create`, `modify`, `delete`. |
| `started_at` | timestamp | No | |
| `ended_at` | timestamp | Yes | |
| `duration_seconds` | int | Yes | |
| `outcome` | string | No | Enum: `success`, `failed`, `retried`, `skipped`, `ghost_step`. |
| `model_used` | string | Yes | |
| `premium_requests` | double | No | |
| `tokens_input` | int | Yes | |
| `tokens_output` | int | Yes | |
| `acceptance_command` | string | Yes | The acceptance check that was run. |
| `acceptance_passed` | boolean | Yes | |
| `acceptance_duration_seconds` | int | Yes | How long acceptance took to run. |
| `diff_stat` | string | Yes | Git diff summary. |
| `lines_added` | int | Yes | |
| `lines_removed` | int | Yes | |
| `retry_count` | int | No | Times this step was retried (0 = first attempt succeeded). |
| `model_escalated_from` | string | Yes | Previous model if escalation occurred. |
| `prompt_hash` | string | Yes | Hash for prompt reproducibility. |
| `transcript_path` | string | Yes | Path to transcript file (for quick lookup without joining). |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

---

### Table 4: telemetry_process_events

**Grain:** One row per notable event during execution. This table replaces the legacy "friction" concept with a structured process control framework.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `event_id` | string | No | PK. UUID. |
| `session_id` | string | Yes | FK to `telemetry_sessions`. Null for standalone anomaly detections. |
| `phase_id` | string | Yes | FK to `telemetry_phases`. |
| `step_id` | string | Yes | FK to `telemetry_steps`. |
| `rec_id` | string | Yes | Recommendation being worked on. |
| `timestamp` | timestamp | No | When the event was observed. |
| `tier` | string | No | Enum: `decision`, `rework`, `exception`, `anomaly`. |
| `category` | string | No | See canonical category enum below. |
| `severity` | string | No | Enum: `info`, `warning`, `error`, `critical`. |
| `description` | string | No | Human-readable event description. |
| `root_cause` | string | Yes | Structured root cause (populated by recovery agents or cloud analysis). |
| `resolution` | string | Yes | How the event was resolved. |
| `time_lost_seconds` | int | Yes | Estimated time consumed by this event. |
| `rec_filed` | string | Yes | Recommendation ID filed to address this event. |
| `detected_by` | string | No | Enum: `executor_script`, `recovery_agent`, `cloud_analysis_agent`, `manual`. |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

#### Process Event Tiers

| Tier | Definition | Detection Method | Examples |
|------|-----------|-----------------|----------|
| **decision** | The system chose one path over another at a branching point. Normal operation, but the choice and its outcome must be recorded for heuristic tuning. | Deterministic: emitted by the executor script at the moment of decision. | Model escalation, critique auto-approve, validation quarantine, skip-to-postflight, doc-only fallback, no-changes-needed classification, rec selection logic. |
| **rework** | The system looped back to a prior phase. Expected to happen sometimes; frequency is the signal. | Deterministic: emitted by the executor script at the point of retry. | Critique revision, implementation step retry, validation failure with retry, CI fix attempt, commit hook retry, code review fix attempt, git pull retry. |
| **exception** | The system invoked an exceptional/escalation path not used during normal execution. Should be investigated. | Deterministic: emitted by the executor script when escalation occurs. | Plan escalation agent called (>3 revisions), merge recovery agent called, e2e test failure after code review passed, postmortem rec creation, escalation model exhausted, acceptance rewrite agent, self-repair loop, session budget abort. |
| **anomaly** | A statistical outlier detected post-hoc against rolling baselines. | Post-hoc: emitted by cloud analysis agent after session completion. | Cost > p90, duration > p90, step count exceeds plan, multiple tier 1 events compounding, model call failure rate spike. |

#### Canonical Category Enum

**Preflight:**
`rec_not_found`, `acceptance_lint_fail`, `acceptance_infeasible`, `not_eligible`, `checkpoint_conflict`, `checkpoint_stale`, `jsonl_dirty`, `branch_create_fail`, `branch_exists_reuse`, `already_implemented`, `skip_to_postflight`

**Planning:**
`plan_gen_success`, `plan_gen_cli_error`, `model_escalation_plan`, `escalation_exhausted_plan`, `acceptance_challenged`, `no_steps_parsed`, `no_changes_needed`, `budget_exceeded`

**Critique/Refinement:**
`critique_approved`, `critique_needs_revision`, `critique_cycling_detected`, `critique_exhausted`, `critique_skip`, `refine_no_steps`

**Implementation:**
`step_success`, `step_cli_error`, `ghost_step`, `ruff_error`, `validate_timeout`, `validate_failed`, `acceptance_failed`, `acceptance_timeout`, `scope_enforcement_fail`, `commit_hook_retry`, `step_file_revert`, `model_escalation_impl`

**Code Review:**
`code_review_pass`, `code_review_fail`, `code_review_fix_attempt`

**Postflight:**
`scope_drift_detected`, `validation_quarantine`, `validation_emergency_bypass`, `validation_doc_only_fallback`, `post_validation_acceptance_fail`

**CI/Merge:**
`ci_pass`, `ci_timeout`, `ci_failure`, `ci_fix_deterministic`, `ci_fix_llm_escalation`, `ci_fix_exhausted`, `merge_success`, `merge_fail`, `merge_recovery_success`, `merge_recovery_exhausted`, `postmortem_rec_created`

**Cleanup:**
`checkout_main_fail`, `pull_retry`, `cache_cleanup`, `branch_delete`

**Autonomous Decisions:**
`rec_selection`, `session_budget_abort`, `no_changes_verified`

**Cloud Analysis:**
`cost_outlier`, `duration_outlier`, `step_count_outlier`, `rework_rate_outlier`, `model_failure_spike`, `pattern_detected`

This enum is extensible. New categories are added by appending to the relevant group. Categories are never removed; deprecated categories are documented as such.

---

### Table 5: telemetry_model_calls

**Grain:** One row per LLM invocation. Captures every call to any model provider.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `call_id` | string | No | PK. UUID. |
| `session_id` | string | Yes | FK to `telemetry_sessions`. Null for scheduled agent calls. |
| `phase_id` | string | Yes | FK to `telemetry_phases`. |
| `step_id` | string | Yes | FK to `telemetry_steps`. |
| `invocation_id` | string | Yes | FK to `telemetry_agent_invocations`. For scheduled agent calls. |
| `timestamp` | timestamp | No | Call start. |
| `duration_seconds` | int | Yes | Latency. |
| `provider` | string | No | Enum: `copilot_cli`, `copilot_sdk`, `github_models`. |
| `model` | string | No | Model identifier (e.g., `claude-haiku-4.5`, `gpt-5-mini`). |
| `purpose` | string | No | Enum: `planning`, `critique`, `refinement`, `implementation`, `code_review`, `code_review_fix`, `ci_fix`, `merge_recovery`, `risk_classification`, `findings`, `comparison`, `escalation_diagnosis`, `acceptance_rewrite`, `self_repair`. |
| `tokens_input` | int | Yes | Input tokens consumed. |
| `tokens_output` | int | Yes | Output tokens generated. |
| `premium_requests` | double | No | Billing unit. |
| `exit_code` | int | Yes | LLM call exit code. |
| `copilot_session_id` | string | Yes | Copilot CLI session ID for reuse tracking. |
| `prompt_hash` | string | Yes | Hash for prompt version tracking. |
| `error` | string | Yes | Error message if failed. |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

---

### Table 6: telemetry_transcripts

**Grain:** One row per agent transcript file. Stores metadata and an S3 pointer, not the transcript content itself.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `transcript_id` | string | No | PK. UUID. |
| `session_id` | string | Yes | FK to `telemetry_sessions`. |
| `phase_id` | string | Yes | FK to `telemetry_phases`. |
| `step_id` | string | Yes | FK to `telemetry_steps`. |
| `invocation_id` | string | Yes | FK to `telemetry_agent_invocations`. For scheduled agent transcripts. |
| `timestamp` | timestamp | No | When transcript was produced. |
| `purpose` | string | No | Enum: same as `telemetry_model_calls.purpose`. |
| `local_path` | string | No | Local filesystem path (e.g., `logs/transcripts/plan-rec-100-1711800000.md`). |
| `s3_key` | string | Yes | S3 key once uploaded. |
| `size_bytes` | int | No | Transcript file size. |
| `token_count` | int | Yes | Estimated token count of transcript content. |
| `model_used` | string | Yes | Model that produced this transcript. |
| `rec_id` | string | Yes | Recommendation ID if applicable. |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

**Design note:** Transcript content is NOT stored in Iceberg. The table is a metadata index for locating and filtering transcripts. Content lives in local `logs/transcripts/` files and is synced to S3 `transcripts/` prefix. Querying transcript content is a two-step operation: filter in Athena, then fetch from S3.

---

### Table 7: telemetry_agent_invocations

**Grain:** One row per scheduled agent Lambda invocation. Standalone -- not part of a session.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `invocation_id` | string | No | PK. UUID. |
| `agent_name` | string | No | Agent identifier (e.g., `doc-freshness`, `rec-curator`). |
| `trigger` | string | No | Enum: `eventbridge`, `manual`, `smoke_test`. |
| `started_at` | timestamp | No | Lambda invocation start. |
| `ended_at` | timestamp | Yes | |
| `duration_seconds` | int | Yes | |
| `outcome` | string | No | Enum: `success`, `failed`, `timeout`, `throttled`. |
| `model_used` | string | Yes | |
| `provider` | string | Yes | Enum: `copilot_sdk`, `github_models`. |
| `premium_requests` | double | No | |
| `tokens_input` | int | Yes | |
| `tokens_output` | int | Yes | |
| `findings_count` | int | Yes | Number of findings produced. |
| `recs_created` | int | Yes | Recs auto-filed by findings processor. |
| `queue_entries_written` | int | Yes | Priority queue entries (rec-curator). |
| `error` | string | Yes | Error message if failed. |
| `lambda_request_id` | string | Yes | AWS Lambda request ID for CloudWatch correlation. |
| `ingested_at` | timestamp | No | |
| `trade_date` | date | No | Partition key. |

---

## Autonomous Executor Workflow

The executor is a Python script that follows a deterministic state machine with non-deterministic LLM calls at specific points. The telemetry system instruments every transition.

### Target Workflow (Future State)

This workflow replaces the current `/develop-executor` supervisor prompt. The human is removed from the loop. Recovery agents are called by the script itself.

```
a. PLANNING AGENT
   Input:  recommendation context, acceptance criteria, target files
   Output: structured plan with numbered steps
   Telemetry: telemetry_phases(phase=plan_generation), telemetry_model_calls, telemetry_transcripts

b. CRITIQUE AGENT
   Input:  plan, recommendation context
   Output: APPROVED or NEEDS_REVISION with specific issues
   Telemetry: telemetry_phases(phase=critique), telemetry_model_calls, telemetry_transcripts

c. ESCALATION AGENT (called only if >3 critique revisions)
   Input:  plan, critique history, acceptance criteria
   Output: diagnosis -- acceptance criteria already met, criteria impossible,
           plan fundamentally wrong, or approved-with-overrides
   Telemetry: telemetry_phases(phase=escalation_diagnosis),
              telemetry_process_events(tier=exception, category=critique_exhausted)

d. IMPLEMENTATION STEP AGENT (one call per step, free to iterate within limits)
   Input:  step description, target file content, test file content, acceptance command
   Output: code changes
   Telemetry: telemetry_steps, telemetry_model_calls, telemetry_transcripts

e. SCRIPT VALIDATES
   Deterministic: ruff fix, validate.py, acceptance command
   On failure: return to (d) with validation output as context
   On pass: proceed to (f)
   Telemetry: telemetry_process_events(tier=rework, category=validate_failed) on failure

f. CODE REVIEW + E2E AGENT
   Input:  all changed files, test results, acceptance criteria
   Output: blocking findings list, or APPROVED
   If blocking: implements fixes, returns to (d) with review context
   If approved: proceeds to (g)
   If e2e test fails: telemetry_process_events(tier=exception, category=e2e_failure)
   Telemetry: telemetry_phases(phase=code_review), telemetry_model_calls

g. SCRIPT MERGES
   Deterministic: push, PR create, CI wait, squash merge
   Telemetry: telemetry_phases(phase=merge)

h. MERGE RECOVERY AGENT (called only if merge fails)
   Input:  merge error, branch state, PR state
   Output: resolved state (merged, or escalated to human)
   Telemetry: telemetry_phases(phase=merge_recovery),
              telemetry_process_events(tier=exception, category=merge_fail)
```

### Telemetry Injection Points

Every transition in the state machine above is instrumented:

| Transition | What is emitted |
|-----------|----------------|
| Session start | `telemetry_sessions` record (partial, `ended_at` null) |
| Phase start | `telemetry_phases` record (partial, `ended_at` null) |
| Phase end | Update `telemetry_phases` with outcome, duration, cost |
| Step start | `telemetry_steps` record (partial) |
| Step end | Update `telemetry_steps` with outcome, diff, cost |
| LLM call | `telemetry_model_calls` record |
| Transcript saved | `telemetry_transcripts` record |
| Decision made | `telemetry_process_events(tier=decision)` |
| Retry/loop-back | `telemetry_process_events(tier=rework)` |
| Escalation invoked | `telemetry_process_events(tier=exception)` |
| Session end | Update `telemetry_sessions` with final outcome, aggregates |

"Update" means emitting a new record with the same PK and a later `ingested_at`. The Iceberg `ROW_NUMBER()` view returns the latest version.

---

## Process Event Framework

### What Replaces "Friction"

The legacy telemetry system used a concept called "friction" -- freetext descriptions of things that went wrong, captured by a human supervisor reviewing transcripts after each recommendation. This was appropriate during early development when the system needed human judgment to identify problems.

In the autonomous workflow, "friction" is replaced by **process events** -- structured records emitted by the executor script itself (for Tier 1-3) and by a cloud analysis agent (for Tier 4). The key differences:

| Aspect | Legacy Friction | Process Events |
|--------|----------------|----------------|
| **Detection** | Human reads transcripts after the fact | Script emits at point of occurrence (Tier 1-3) or cloud agent detects statistically (Tier 4) |
| **Schema** | Freetext `friction` field, `missing_context`, `deviation` | Structured `tier`, `category`, `severity`, FK to session/phase/step |
| **Trigger** | Always manual (`run_retro_lite.py --append`) | Automatic: Tier 1-3 emitted by executor. Tier 4 emitted by cloud agent. |
| **Analysis** | `friction_analysis.py` counts pattern occurrences in text | Athena SQL: `SELECT category, COUNT(*) FROM telemetry_process_events GROUP BY category` |
| **Action** | Human files recommendations based on patterns | Cloud agent files recommendations when anomalies recur. Recovery agents act in real-time. |

### Cloud Analysis Agent

A scheduled Lambda agent (running daily or triggered on session completion) performs statistical anomaly detection:

1. **Query recent sessions:** `SELECT * FROM telemetry_sessions WHERE trade_date >= CURRENT_DATE - INTERVAL '1' DAY`
2. **Compute rolling baselines:** For each metric (cost, duration, rework_count, exception_count), compute p50/p90 over the last 30 days of sessions with the same `workflow` type.
3. **Flag anomalies:** Any session where a metric exceeds p90 gets a Tier 4 `anomaly` process event.
4. **Detect patterns:** If the same `category` of Tier 2-3 event occurs in 3+ sessions within 7 days, the agent files a recommendation.
5. **Cost trend analysis:** If total `premium_requests_total` across all sessions in the last 7 days exceeds a configurable threshold, emit a `cost_outlier` anomaly.

The cloud agent writes its findings as `telemetry_process_events(tier=anomaly, detected_by=cloud_analysis_agent)` and, when patterns warrant it, creates recommendations via `emit("telemetry_process_events", ...)` and the standard recommendation filing pipeline.

---

## Scheduled Agent Observability

Scheduled agents (doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, rec-curator) currently produce findings but have zero observability into their own execution. The telemetry system fixes this.

### Lambda Handler Instrumentation

The `scheduled_agent_handler.py` Lambda emits:
- One `telemetry_agent_invocations` record per agent run
- One `telemetry_model_calls` record per LLM call within the run
- One `telemetry_transcripts` record if the agent produces a transcript

These records go directly to S3 staging (no local outbox -- Lambdas are stateless). Compaction runs in the findings processor Lambda or on a schedule.

### Findings Processor Instrumentation

The `findings_processor_handler.py` Lambda emits:
- Updates to the `telemetry_agent_invocations` record with `findings_count`, `recs_created`, `queue_entries_written`

---

## Athena Views

### Current-State Views

For tables where records are updated (sessions, phases, steps), provide `_current` views:

```sql
CREATE OR REPLACE VIEW telemetry_sessions_current AS
SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY session_id ORDER BY ingested_at DESC
    ) AS rn
    FROM trading_formulas_db.telemetry_sessions
) WHERE rn = 1;
```

Similar views for `telemetry_phases_current`, `telemetry_steps_current`.

### Analytical Views

Pre-built views for common queries:

**Session summary (last 30 days):**
```sql
CREATE OR REPLACE VIEW telemetry_session_summary_30d AS
SELECT
    workflow,
    COUNT(*) AS session_count,
    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count,
    ROUND(AVG(duration_seconds) / 60.0, 1) AS avg_duration_minutes,
    ROUND(SUM(premium_requests_total), 2) AS total_cost,
    SUM(rework_count) AS total_rework_events,
    SUM(exception_count) AS total_exception_events
FROM telemetry_sessions_current
WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY workflow;
```

**Phase time distribution:**
```sql
CREATE OR REPLACE VIEW telemetry_phase_time_distribution AS
SELECT
    phase,
    COUNT(*) AS occurrences,
    ROUND(AVG(duration_seconds), 1) AS avg_seconds,
    ROUND(APPROX_PERCENTILE(duration_seconds, 0.9), 1) AS p90_seconds,
    ROUND(SUM(premium_requests), 2) AS total_cost
FROM telemetry_phases_current
WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY phase;
```

**Process event frequency:**
```sql
CREATE OR REPLACE VIEW telemetry_event_frequency_30d AS
SELECT
    tier,
    category,
    COUNT(*) AS occurrences,
    COUNT(DISTINCT session_id) AS affected_sessions
FROM telemetry_process_events
WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY tier, category
ORDER BY occurrences DESC;
```

---

## What This Supersedes

### Files Replaced

| Current File | Disposition |
|-------------|------------|
| `logs/.session-telemetry.jsonl` | Replaced by `telemetry_sessions` WAL + Iceberg |
| `logs/.execution-step-telemetry.jsonl` | Replaced by `telemetry_steps` WAL + Iceberg |
| `logs/.retro-lite-log.jsonl` | Replaced by `telemetry_process_events` WAL + Iceberg |
| `logs/.session-metrics-log.jsonl` | Fields absorbed into `telemetry_sessions` |
| `logs/.friction-analysis-log.jsonl` | Replaced by Athena queries on `telemetry_process_events` |
| `logs/.plan-audit-log.jsonl` | Plan scope drift absorbed into `telemetry_process_events(category=scope_drift_detected)` + phase metadata |
| `logs/.token-budget-log.jsonl` | Replaced by `telemetry_model_calls` per-call token tracking |
| `logs/.copilot-otel.jsonl` | Replaced by `telemetry_model_calls` |
| `logs/.transcript-index.jsonl` | Replaced by `telemetry_transcripts` |
| `logs/runs/*.json` | Replaced by `telemetry_sessions` + `telemetry_phases` |
| `logs/failure-summaries/*.json` | Replaced by `telemetry_process_events` + `telemetry_phases` |

### Tables Replaced

| Current Table | Disposition |
|--------------|------------|
| `ops_session_log` | Replaced by `telemetry_sessions` (superset schema) |
| `ops_execution_plans` | Plan metadata absorbed into `telemetry_phases(phase=plan_generation, plan_steps_json=...)` + plan text stays in `PLAN-{slug}.md` files. Structured step data (step number, title, acceptance command) preserved in `plan_steps_json` even for plans that are never fully executed. |

### Tables Retained (Domain Entities, Not Telemetry)

| Table | Reason |
|-------|--------|
| `ops_recommendations` | Domain entity -- recommendation lifecycle, not telemetry |
| `ops_decisions` | Domain entity -- architectural decisions |
| `ops_priority_queue` | Domain entity -- executor work queue |
| All `trading_formulas_db` tables | Market data, formulas, performance -- unrelated to workflow telemetry |

### Scripts Replaced or Refactored

| Script | Disposition |
|--------|------------|
| `scripts/session_telemetry.py` | Replaced by extended `OpsWriter` and unified write interface |
| `scripts/session_metrics.py` | Session-level metrics computed during `telemetry_sessions` record finalization |
| `scripts/friction_analysis.py` | Replaced by Athena queries on `telemetry_process_events` |
| `scripts/run_retro_lite.py` | Replaced by process event emission within the executor |
| `scripts/transcript_index.py` | Replaced by transcript record emission when transcripts are saved |
| `scripts/token_budget.py` | Token tracking moved to per-call `telemetry_model_calls` records |
| `scripts/metrics_analysis.py` | Replaced by Athena analytical views |

### Prompts/Agents Affected

| File | Change |
|------|--------|
| `.github/prompts/develop-executor.prompt.md` | Long-term: eliminated. Short-term: updated to reference new telemetry tables instead of JSONL files. |
| `.github/agents/retro-lite.agent.md` | Deprecated. Replaced by process event emission within the executor script and cloud analysis agent. |
| `.github/agents/rca-analyst.agent.md` | Retained but invoked by the executor script, not the supervisor prompt. Takes `telemetry_process_events` as input instead of freetext friction. |
| `.github/agents/retrospective.agent.md` | Updated to query `telemetry_process_events` instead of `.retro-lite-log.jsonl`. |
| `scripts/session_postflight.py` | Refactored: postflight calls `OpsWriter.compact_all()` which now covers telemetry tables alongside ops tables. |
| `scripts/session_preflight.py` | Refactored: telemetry health checks query `telemetry_*` Athena views instead of parsing local JSONL files. |

---

## Implementation Phasing

This work is too large for a single plan. It decomposes into the following strategic plans, ordered by dependency:

### Phase A: Foundation (No External Dependencies)

**PLAN-telemetry-foundation**

1. Extend `OpsWriter` to support a configurable set of telemetry tables with the unified write interface
2. Define all 7 table schemas as Python dataclasses with validation
3. Add Iceberg table definitions for all 7 `telemetry_*` tables in Terraform (in `trading_formulas_db`)
4. Create Athena `_current` views and analytical views
5. Write comprehensive tests for the extended writer

**Gate:** Unified write interface works end-to-end (local outbox + S3 + compaction to Iceberg + Athena query returns data).

### Phase B: Executor Instrumentation

**PLAN-telemetry-executor-instrument**

1. Instrument `execute_recommendation.py` to emit `telemetry_sessions` and `telemetry_phases` records at phase boundaries
2. Instrument `step_runner.py` to emit `telemetry_steps` records
3. Instrument `copilot_wrapper.py` to emit `telemetry_model_calls` records on every LLM call
4. Replace `_append_step_telemetry()`, `write_run_summary()`, `emit_failure_summary()`, `write_session_envelope()` with unified write calls
5. Add process event emission at all deterministic trigger points (Tier 1-3)
6. Instrument transcript saving to emit `telemetry_transcripts` records

**Gate:** An executor run populates all 6 session-linked tables. Athena queries return complete session data.

### Phase C: Scheduled Agent Instrumentation

**PLAN-telemetry-scheduled-agents**

1. Instrument `scheduled_agent_handler.py` to emit `telemetry_agent_invocations` records
2. Instrument `findings_processor_handler.py` to emit updates
3. Instrument Copilot SDK calls in Lambda to emit `telemetry_model_calls`
4. Deploy updated Lambdas, verify with smoke tests

**Gate:** Scheduled agent runs are visible in `telemetry_agent_invocations` via Athena.

### Phase D: Manual Workflow Instrumentation

**PLAN-telemetry-manual-workflow**

1. Instrument `session_postflight.py` to emit `telemetry_sessions` for manual `/plan` and `/implement` workflows
2. Update preflight to read telemetry health from Athena views instead of local JSONL
3. Remove legacy JSONL write paths that have been replaced

**Gate:** Both manual and executor sessions appear in the same `telemetry_sessions` table.

### Phase E: Cloud Analysis Agent

**PLAN-telemetry-cloud-analysis**

1. Create the cloud analysis agent prompt
2. Implement as a scheduled Lambda agent (daily or session-triggered)
3. Agent queries `telemetry_sessions`, computes baselines, emits anomaly events
4. Agent files recommendations when patterns recur

**Gate:** Anomaly detection runs autonomously and produces actionable recommendations.

### Phase F: Legacy Cleanup

**PLAN-telemetry-legacy-cleanup**

1. Remove deprecated scripts (`friction_analysis.py`, `run_retro_lite.py`, `transcript_index.py`, `session_telemetry.py`, `session_metrics.py`, `metrics_analysis.py`, `token_budget.py`)
2. Remove deprecated JSONL files and their references from all prompts, agents, and copilot-instructions.md
3. Archive `ops_session_log` and `ops_execution_plans` tables
4. Update all documentation references

**Gate:** `grep -r "retro-lite\|friction_analysis\|session_telemetry\|session_metrics\|token_budget" scripts/ src/ .github/` returns zero matches.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Star schema over flat files | Athena queries become simple JOINs. Each table has a clear grain. No more JSON parsing in SQL. |
| Same database with `telemetry_` prefix | Single database avoids cross-database JOIN complexity, reduces Terraform scaffolding, simplifies Glue Catalog management. Per-table Iceberg properties and IAM resource-level permissions provide equivalent isolation. |
| Extend OpsWriter + outbox pattern (Decision 51) | Reuses the already-tested outbox/compaction code from `scripts/ops_writer.py`. Avoids building a parallel write pipeline. Consistent local resilience mechanism across ops and telemetry. |
| Process events replace friction | Structured, machine-readable, emitted at point of occurrence. Enables autonomous analysis without human transcript review. |
| 4-tier classification (decision/rework/exception/anomaly) | Maps to process control theory: normal operation measurement, expected variation, exceptional paths, statistical detection. Each tier has a distinct detection method and response. |
| Transcripts as metadata index, not content store | Transcript content is large, rarely queried, and already stored as files. The Iceberg table indexes them for filtering; S3 stores the content. |
| Unified write interface | Single write path eliminates the scattered `_append_*` functions. Schema validation at write time. Consistent outbox + S3 behavior everywhere. |
| Phase-level timing as first-class table | Answers the most important operational question -- "where does time go?" -- which is unanswerable with the current session-level and step-level granularity. |
| Token tracking per model call, not per session | Enables cost attribution to specific phases and steps. Identifies which prompts consume the most tokens. |
| `attempt_number` / `max_attempts` on phases | Captures the retry graph directly in the schema instead of requiring complex event correlation. |
| Coverage at session level only | Running coverage per step doubles execution time with minimal incremental insight. Session-level delta is sufficient. |
| Critique/review delta as proxy metrics | `revision_count` and `blocking_findings_count` give the signal; transcript content gives the detail when needed. Avoids building structured diff capture machinery. |

---

## Constraints

1. **All timestamps are UTC.** Producers must normalize to UTC before writing. The system runs on a Windows host (GMT/BST) and Lambdas run in UTC -- mixed timezones in the same table would produce incorrect duration calculations.

2. **awswrangler Lambda dependency:** Iceberg compaction uses `awswrangler.athena.to_iceberg()`, available only via the AWSSDKPandas Lambda layer. Local compaction requires the `awswrangler` pip package.

3. **Athena engine v3 required:** All Iceberg operations (MERGE, VACUUM) require the `agent-platform-production` workgroup with engine v3.

4. **Outbox files follow Decision 51 conventions:** Outbox files at `logs/.ops-outbox/{table}/` are already gitignored. Stale entries (>24h) are flagged by `validate.py`.

5. **Schema evolution:** New columns are added via `ALTER TABLE ADD COLUMNS` (one column per statement, no `IF NOT EXISTS`). The write interface drops unknown fields, so new code can write to old schemas without error.

6. **No breaking changes during migration:** Phases B-D run in parallel with the legacy system. Both old and new telemetry are written simultaneously until Phase F removes the legacy paths. This ensures no data gaps during the transition.

7. **Test isolation:** Telemetry writes are no-ops when `PYTEST_CURRENT_TEST` is set, consistent with the existing `OpsWriter` behavior. Tests that need to verify telemetry emission mock the write interface directly.

8. **Windows compatibility:** All outbox paths use `pathlib.Path`. No shell-specific operations in the write path.

9. **Single-threaded executor assumption:** The executor runs one recommendation at a time. Concurrent access to outbox files is not a current concern. If parallel execution is added in the future, per-process outbox partitioning or file locking should be addressed.

10. **No data retention policy yet.** All telemetry is retained indefinitely. A retention and VACUUM schedule will be defined once baseline data volumes are established after Phase D.

---

## File Reference

| File | Purpose |
|------|---------|
| `docs/INTENT-telemetry-system.md` | This document. Authoritative spec for telemetry architecture. |
| `docs/INTENT-recommendation-executor.md` | Executor architecture (retained; telemetry sections superseded). |
| `scripts/ops_writer.py` | Extended to support telemetry tables alongside ops tables. Unified write interface. |
| `terraform/iceberg_tables.tf` | Iceberg table definitions for `telemetry_*` tables (added to existing file). |
| `scripts/session_postflight.py` | Calls `compact_all()` at session close. |
| `scripts/session_preflight.py` | Queries telemetry health from Athena views. |
| `scripts/execute_recommendation.py` | Primary telemetry producer (executor workflow). |
| `scripts/executor/step_runner.py` | Step-level telemetry producer. |
| `scripts/copilot_wrapper.py` | Model call telemetry producer. |
| `src/data/handlers/scheduled_agent_handler.py` | Agent invocation telemetry producer. |
| `src/data/handlers/findings_processor_handler.py` | Findings processing telemetry producer. |

---

**Last Updated:** April 23, 2026
