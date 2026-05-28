# PLAN: Priority Queue Pipeline — Athena-Native Flow

**Branch:** `agent/platform-priority-queue-athena`
**Phase:** Platform Wave 1 (Priority Queue Pipeline)
**Verification Tier:** V2 (Infrastructure Integration)
**Date:** 2026-04-22

---

## Goal

Replace the stale JSONL-based priority queue pipeline with an Athena-native flow. The rec-curator reads from `ops_recommendations_current` (Athena view), emits priority-queue-entry findings, and the findings processor routes them directly to the `ops_priority_queue` Iceberg table via `OpsWriter.write()`. No intermediate JSONL file. The `ops_priority_queue_current` Athena view becomes the single source of truth.

## Problem Statement

The `ops_priority_queue` Athena table is always empty. Two root causes:

1. **Stale input:** `_preload_rec_curator_context()` reads raw `.recommendations-log.jsonl` from S3, which contains every historical snapshot of every rec. The model sees duplicate entries at different statuses. Should read from `ops_recommendations_current` Athena view (deduplicated current state).

2. **Contaminated output:** `findings_processor_handler` calls `read_all_agent_findings()` which reads ALL agent findings across ALL agents and ALL time. Old `priority-queue-entry` findings from previous rec-curator runs mix with new ones, contaminating the queue with stale entries.

## Design Decision

Follow the same pattern as all other ops tables: **append-only Iceberg + view**. Eliminate the intermediate `priority-queue/.priority-queue.jsonl` S3 file and the `overwrite_jsonl()` call. The Iceberg table is the canonical store, and `ops_priority_queue_current` filters to the latest `queue_run_id`.

The priority queue is a Lambda-produced artifact — it has no meaningful local source. Accept that it requires SSO. Show `(priority queue unavailable — SSO expired)` in preflight when Athena is unreachable.

---

## Scope

| File | Action | LOC Est. |
|------|--------|----------|
| `src/data/handlers/scheduled_agent_handler.py` | Modify | ~60 |
| `src/data/handlers/findings_processor_handler.py` | Modify | ~30 |
| `scripts/session_preflight.py` | Modify | ~40 |
| `scripts/s3_log_store.py` | Modify (cleanup) | ~15 |
| `docs/contracts/ops-data-store.md` | Update | ~10 |
| `tests/test_scheduled_agent_handler.py` | Update | ~40 |
| `tests/test_findings_processor_handler.py` | Update | ~30 |
| `tests/test_session_preflight.py` | Update | ~30 |
| `tests/test_s3_log_store.py` | Update | ~10 |

**No Terraform changes.** The `ops_priority_queue` table, `ops_priority_queue_current` view, IAM permissions, S3 event triggers, and ops_compaction Lambda are all already deployed and verified working.

**Lambda deployment required:** Changes to `scheduled_agent_handler.py`, `findings_processor_handler.py`, and `s3_log_store.py` are all packaged in the Lambda zip. Requires `python -m scripts.build_lambda --deploy` after merge.

---

## Steps

### Step 1: Add `_query_athena_recs()` helper to `scheduled_agent_handler.py`

**What:** Add a boto3-based Athena query helper that runs `SELECT ... FROM ops_recommendations_current WHERE status = 'open'` and returns a list of dicts. Uses `boto3.client("athena")` directly (no subprocess — we're in Lambda).

**Why:** The Lambda role already has `athena:StartQueryExecution` and `athena:GetQueryResults` permissions (scheduled_agents.tf L116-124). The 900s Lambda timeout provides ample headroom for the ~10-15s Athena query.

**Files:** `src/data/handlers/scheduled_agent_handler.py`

**Acceptance:** `python -m pytest tests/test_scheduled_agent_handler.py -x -q`

**Detail:**
- Query: `SELECT id, date, title, source, effort, priority, status, automatable, risk, file, context, acceptance, dependencies, tags FROM ops_recommendations_current WHERE status = 'open'`
- Database: `trading_formulas_db`, workgroup: `agent-platform-production`
- Athena output location: `s3://bblake-platform-agent-logs/athena-results/`
- Poll for completion with 2s intervals, up to 60s timeout
- On failure: log warning, fall back to existing `read_jsonl()` path (graceful degradation per ops_writer contract)
- Return: `list[dict]` matching the same shape the model currently receives

### Step 2: Update `_preload_rec_curator_context()` to use Athena

**What:** Replace `read_jsonl(".recommendations-log.jsonl")` with a call to `_query_athena_recs()`. The model now receives deduplicated, current-state recommendations.

**Why:** Eliminates the stale-input problem. The `ops_recommendations_current` view does `ROW_NUMBER() PARTITION BY id ORDER BY ingested_at DESC` deduplication.

**Files:** `src/data/handlers/scheduled_agent_handler.py`

**Acceptance:** `python -m pytest tests/test_scheduled_agent_handler.py -x -q`

**Detail:**
- Replace L136 `recs = read_jsonl(".recommendations-log.jsonl")` with `recs = _query_athena_recs()`
- Remove the Python-side `open_recs = [r for r in recs if ... status == "open"]` filter — the SQL query already filters
- Keep the `retro = read_jsonl(".retro-lite-log.jsonl")` call unchanged (no Athena view for retro-lite; raw file is adequate)
- Update the preamble header from `### logs/.recommendations-log.jsonl` to `### ops_recommendations_current (Athena view)` so the model knows the data source
- Fallback: if `_query_athena_recs()` returns `None` (Athena unavailable), fall back to `read_jsonl()` with a warning log

### Step 3: Route priority-queue-entry findings directly to OpsWriter in findings_processor

**What:** In `findings_processor_handler.handler()`, extract `priority-queue-entry` findings from the triggering S3 file only (not `read_all_agent_findings()`). Write each entry to `OpsWriter.write("ops_priority_queue", entry)` with a shared `queue_run_id`. Remove the `overwrite_jsonl()` call.

**Why:** Eliminates the contaminated-output problem. Each curator run produces a clean set of queue entries with a unique `queue_run_id`. The append-only Iceberg table stores all runs, and the view filters to the latest.

**Files:** `src/data/handlers/findings_processor_handler.py`

**Acceptance:** `python -m pytest tests/test_findings_processor_handler.py -x -q`

**Detail:**
- Extract the triggering S3 key from `event["Records"][0]["s3"]["object"]["key"]`
- Read only that file with `read_jsonl(trigger_key)` to get the latest findings
- Filter for `type == "priority-queue-entry"`
- Generate a shared `queue_run_id = str(uuid.uuid4())`
- For each entry: `entry["queue_run_id"] = queue_run_id`, then `OpsWriter.write("ops_priority_queue", entry)`
- Keep `read_all_agent_findings()` for the unified.jsonl union step (existing behaviour preserved)
- But filter OUT `priority-queue-entry` findings from the `all_findings` list used for unified.jsonl — these should not be treated as standard findings
- Remove the `_PRIORITY_QUEUE_KEY` constant and the `overwrite_jsonl()` call for priority queue
- Update the return dict: replace `"queue_entries_written"` key with `"queue_entries_staged"` to reflect the new flow

### Step 4: Rewrite `read_priority_queue()` in `session_preflight.py` to use Athena

**What:** Replace the JSONL file-based `read_priority_queue()` with an Athena query against `ops_priority_queue_current`.

**Why:** The JSONL file is being eliminated. The Athena view is the single source of truth. Local fallback is not meaningful — the priority queue is produced in Lambda.

**Files:** `scripts/session_preflight.py`

**Acceptance:** `python -m pytest tests/test_session_preflight.py::TestReadPriorityQueue -x -q`

**Detail:**
- Replace the body of `read_priority_queue()` with a call to `_run_athena_query()` (already exists in the module)
- Query: `SELECT rank, rec_id, rationale, north_star_impact, status FROM ops_priority_queue_current WHERE status = 'queued' ORDER BY rank ASC LIMIT {max_items}`
- On Athena failure: return `[]` (same as current behaviour when file is missing)
- Remove `PRIORITY_QUEUE_FILE` constant (L38)
- Remove the local JSONL file-reading code path from `read_priority_queue()`
- Athena returns all values as strings — cast `rank` to `int` in the dict construction

### Step 5: Clean up `s3_log_store.py` priority queue write-through

**What:** Remove the priority-queue-specific write-through code from `overwrite_jsonl()` and the `_OPS_PRIORITY_QUEUE_KEY` constant.

**Why:** The priority queue no longer uses `overwrite_jsonl()` — it routes directly to `OpsWriter.write()` in the findings processor. The write-through code is dead.

**Files:** `scripts/s3_log_store.py`

**Acceptance:** `python -m pytest tests/test_s3_log_store.py -x -q`

**Detail:**
- Remove `_OPS_PRIORITY_QUEUE_KEY` constant (L39)
- Remove the `if result and key == _OPS_PRIORITY_QUEUE_KEY and entries:` block in `overwrite_jsonl()` (L240-252)
- `overwrite_jsonl()` remains functional for other uses — only the priority queue write-through is removed

### Step 6: Update `docs/contracts/ops-data-store.md`

**What:** Update the contract to reflect the new flow.

**Files:** `docs/contracts/ops-data-store.md`

**Acceptance:** `grep -c "overwrite_jsonl" docs/contracts/ops-data-store.md` returns 0

**Detail:**
- Update the Key-to-Table Routing Map: remove the `priority-queue/.priority-queue.jsonl` row
- Update the Write Flow diagram: add a note that priority queue entries are routed directly by the findings processor, not via s3_log_store write-through
- Update the `ops_priority_queue` description to remove "Mirrors priority-queue/.priority-queue.jsonl"

### Step 7: Update tests

**What:** Update existing test files to match the new behaviour.

**Files:** `tests/test_scheduled_agent_handler.py`, `tests/test_findings_processor_handler.py`, `tests/test_session_preflight.py`, `tests/test_s3_log_store.py`

**Acceptance:** `python -m pytest tests/test_scheduled_agent_handler.py tests/test_findings_processor_handler.py tests/test_session_preflight.py tests/test_s3_log_store.py -x -q`

**Detail:**
- `test_scheduled_agent_handler.py`: Add test for `_query_athena_recs()` — mock boto3 athena client, verify SQL, verify fallback on failure. Update `_preload_rec_curator_context` tests to mock the Athena query instead of `read_jsonl`.
- `test_findings_processor_handler.py`: Update priority queue tests — mock `OpsWriter.write()` instead of `overwrite_jsonl()`. Verify `queue_run_id` is shared across entries. Verify trigger-key extraction from S3 event.
- `test_session_preflight.py`: Update `TestReadPriorityQueue` — mock `_run_athena_query()` instead of `PRIORITY_QUEUE_FILE`. Remove references to `PRIORITY_QUEUE_FILE`.
- `test_s3_log_store.py`: Remove tests for priority queue write-through in `overwrite_jsonl()`.

### Step 8: Validate and deploy

**What:** Run full local validation, build Lambda package, deploy.

**Acceptance:** `python -m scripts.validate --scope all` exits 0

**Detail:**
- Run `python -m scripts.validate --scope all`
- Run `python -m scripts.build_lambda --deploy`
- Verify deployment: invoke rec-curator via `force_agent` event payload
- Query `ops_priority_queue_current` in Athena to confirm rows appear

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Athena query fails in Lambda | Graceful fallback to `read_jsonl()` in Step 2. Priority queue routing in Step 3 only fires when findings exist — no failure if Athena is down. |
| `read_all_agent_findings()` still grows unbounded for unified.jsonl | Out of scope — this plan fixes priority queue correctness. Unified.jsonl growth is a follow-up (agent findings retention policy). |
| Tests for `read_priority_queue()` break due to `PRIORITY_QUEUE_FILE` removal | Step 7 explicitly updates all 5 test references found in `test_session_preflight.py`. |
| Priority queue not visible without SSO | Accepted trade-off. Priority queue is Lambda-produced; local fallback was always hollow. Preflight shows `(priority queue unavailable — SSO expired)`. |

## Complexity Assessment

**Complexity: Medium**
- 4 source files modified (all well-understood from prior analysis)
- 4 test files updated (existing test patterns, no new test infrastructure)
- 1 contract doc updated
- No Terraform changes
- No new dependencies
- Follows established patterns (Athena query helper mirrors `session_preflight._run_athena_query()`, OpsWriter.write() is the same pattern as all other ops tables)

## Lambda Deployment Assessment

Files in Lambda package: `scheduled_agent_handler.py`, `findings_processor_handler.py`, `s3_log_store.py` — all in `_LAMBDA_SCRIPTS` or `src/data/handlers/`. Requires `python -m scripts.build_lambda --deploy` after merge. Both `data-pipeline.zip` (dispatcher + findings-processor) and `ops-compaction.zip` need rebuild since `s3_log_store.py` is shared.
