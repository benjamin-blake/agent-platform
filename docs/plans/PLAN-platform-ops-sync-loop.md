# Plan

## Intent
Close the feedback loop so every agent session -- regardless of SSO state --
reads fresh operational data and every write reaches the Iceberg authoritative
store eventually. This replaces the fragile "hope S3_LOG_BUCKET is set and SSO
is active" pattern with a deterministic local-first outbox + bidirectional sync
architecture, ensuring the self-improving system always has the data it needs to
reason about its own performance.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-ops-sync-loop

## Phase
Phase Platform (parallel)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_writer.py` | Modify | Add local outbox fallback: when S3 put_object fails (SSO expired, network), write entry to `logs/.ops-outbox/{table}/{uuid}.jsonl` instead of silently dropping it |
| `scripts/sync_ops.py` | Create | Bidirectional sync script: `drain` flushes outbox entries to S3 via OpsWriter, `pull` queries Athena `_current` views and overwrites local JSONL files, `sync` does drain-then-pull. Requires SSO. |
| `scripts/session_preflight.py` | Modify | After SSO + S3_LOG_BUCKET checks (~line 966), call `sync_ops.sync()` when SSO is active. Surface outbox size in preflight report. |
| `scripts/session_postflight.py` | Modify | In `run_auto()` after log-housekeeping (~line 600), call `sync_ops.sync()` best-effort. |
| `scripts/execute_recommendation.py` | Modify | (a) In `file_hotfix_rec()` (~line 971), add `OpsWriter().write("ops_recommendations", hotfix_rec)` after the direct JSONL write. (b) Near between-rec checkpoint, call `sync_ops.drain()` best-effort. |
| `scripts/executor/jsonl_store.py` | Modify | In `_create_postmortem_recommendation()` (~line 352), add `OpsWriter().write("ops_recommendations", postmortem)` after the direct JSONL write. |
| `scripts/validate.py` | Modify | Add `validate_outbox_staleness()` check: warn if any outbox files exist older than 24h. |
| `.gitignore` | Modify | Add `logs/.ops-outbox/` to prevent tracking outbox files. |
| `docs/DECISIONS.md` | Modify | Record Decision 51: Local-first outbox + sync architecture for ops data. |
| `tests/test_sync_ops.py` | Create | Unit tests: drain logic, pull logic, Athena query mocking, outbox file cleanup, SSO-required gate. |
| `tests/test_ops_writer.py` | Modify | Add tests for outbox fallback: S3 failure writes to outbox dir, outbox file content matches entry. |
| `tests/test_execute_recommendation.py` | Modify | Mock OpsWriter in `file_hotfix_rec()` tests. |
| `tests/test_executor_jsonl_store.py` | Modify | Mock OpsWriter in `_create_postmortem_recommendation()` tests. |
| `tests/test_validate.py` | Modify | Add test for `validate_outbox_staleness()`. |

## Acceptance Criteria
- [ ] `python -m scripts.sync_ops drain` exits 0 when outbox is empty
- [ ] `python -m scripts.sync_ops pull --profile company-aws-profile` exits 0 and writes local JSONL files with data from Athena views
- [ ] `python -m scripts.sync_ops sync --profile company-aws-profile` exits 0 (drain then pull)
- [ ] When `S3_LOG_BUCKET` is set but SSO is expired, calling `OpsWriter().write(...)` creates a file in `logs/.ops-outbox/{table}/`
- [ ] After SSO reactivates, `python -m scripts.sync_ops drain` flushes all outbox files to S3 and deletes them
- [ ] `python -m scripts.validate` exits 0
- [ ] `python -m pytest tests/test_sync_ops.py tests/test_ops_writer.py tests/test_execute_recommendation.py tests/test_validate.py -x -q` exits 0
- [ ] `logs/.ops-outbox/` appears in `.gitignore`
- [ ] Decision 51 recorded in `docs/DECISIONS.md`

## Constraints
- **5 ops tables only**: `ops_recommendations`, `ops_execution_plans`, `ops_session_log`,
  `ops_decisions`, `ops_priority_queue`. Telemetry logs (`.retro-lite-log.jsonl`,
  `.execution-step-telemetry.jsonl`, etc.) are out of scope -- separate plan pending
  schema design.
- **Athena views for pull**: Use `ops_recommendations_current`, `ops_execution_plans`
  (full table, no _current view needed -- append-only plans), `ops_session_log`,
  `ops_decisions_current`, `ops_priority_queue_current`. All queries use workgroup
  `agent-platform-production` (engine v3).
- **sync_ops requires SSO**: The `drain` and `pull` subcommands must check SSO status
  before attempting AWS calls. If SSO is expired, print a warning and exit 0 (non-blocking).
  Callers (preflight, postflight, executor) treat sync as best-effort.
- **Outbox directory**: `logs/.ops-outbox/{table_name}/{uuid}.jsonl` -- one file per
  failed write, same JSON content as what OpsWriter.write() would have staged to S3.
  Using a directory per table keeps the drain logic simple (glob per table, re-write each).
- **Never raise from sync_ops when called as library**: All functions must catch exceptions
  and log warnings. Callers are session-critical paths (preflight, postflight, executor)
  and must not fail due to sync issues.
- **OpsWriter.write() outbox fallback must not break Lambda**: In Lambda, S3_LOG_BUCKET is
  always set and S3 is always reachable. The outbox fallback only activates when the S3
  put_object call raises an exception. This is a behavioral no-op in Lambda since S3 calls
  succeed there. Lambda rebuild is required because `ops_writer.py` is in the zip, but
  no functional change in the Lambda environment.
- **Cost control -- drain-only between recs**: Between-rec hooks (Step 7b) must call
  `drain()` only, NOT full `sync()`. Full `sync()` (drain + pull) triggers 5 Athena
  queries per invocation. A 4-rec batch session with full sync at each checkpoint would
  fire 5 x (1 + 1 + 4) = 30 Athena queries. Restrict full `sync()` to preflight and
  postflight only.
- **Pull overwrites local files**: `sync_ops pull` replaces the entire local JSONL file
  with Athena data. Any entries not yet in Athena (still in outbox) would be lost from
  the local file. Therefore, `sync` always runs `drain` before `pull` to flush pending
  entries first.
- **Executor boundary**: `scripts/executor/jsonl_store.py` and `scripts/execute_recommendation.py`
  are NOT on the executor self-modification boundary list. `scripts/executor/postflight.py`
  IS on the boundary, but we only call `sync_ops.drain()` from it (no structural changes
  to the postflight logic itself). This plan goes through `/implement` (human-supervised).
- **Windows subprocess**: `sync_ops.py` calls `aws` CLI for SSO checks. Use
  `encoding='utf-8', errors='replace'` with `text=True` on all subprocess calls.
- **Lambda deployment**: After modifying `ops_writer.py`, `python -m scripts.build_lambda`
  must be run. The outbox path is unreachable in Lambda so no deploy verification is needed
  beyond `build_lambda` succeeding.

## Context
- **Decision 50** (`docs/DECISIONS.md`): Iceberg append-only ops data store. Already decided
  and implemented. This plan adds the sync layer on top.
- **Decision 51** (to be recorded): Local-first outbox + bidirectional sync. Problem: agents
  in local sessions have stale data and writes are lost when SSO expires. Decision: every
  write goes through OpsWriter with local outbox fallback; a `sync_ops` script drains the
  outbox and pulls fresh data from Athena. Agents always read local JSONL. Enforcement via
  preflight/postflight/executor hooks and validate.py staleness checks.
- **`docs/contracts/ops-data-store.md`**: Authoritative schema for all 5 tables. The
  `_current` views use `ROW_NUMBER() OVER (PARTITION BY id ORDER BY ingested_at DESC)`
  for deduplication.
- **Existing read sites** (all read from local JSONL -- no change needed):
  `session_preflight.py`, `validate.py`, `execute_recommendation.py`,
  `executor/jsonl_store.py`, `scheduled_agent_handler.py` (Lambda, reads from Athena
  directly -- already migrated on the previous branch).
- **Existing write bypass holes** (to be fixed in this plan):
  - `execute_recommendation.py:971` -- `file_hotfix_rec()` writes directly via `open()`
  - `executor/jsonl_store.py:352` -- `_create_postmortem_recommendation()` writes directly
  - Both bypass OpsWriter, so entries never reach Iceberg
- **Known gotcha (Import Safety)**: `sync_ops.py` imports OpsWriter at function level to
  avoid import-time failures when boto3/awswrangler unavailable.
- **Known gotcha (Test Isolation)**: Mock both `OpsWriter` and `subprocess.run` in
  sync_ops tests. Never call real AWS APIs from tests.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] `copilot-instructions.md` read (rules, gotchas, file router)
- [ ] `docs/DECISIONS.md` read (Decision 50 understood)
- [ ] `docs/contracts/ops-data-store.md` read (table schemas, view definitions, staging prefix)
- [ ] `scripts/ops_writer.py` read (write() method, S3 put_object call at ~line 157, except block at ~line 164)
- [ ] `scripts/session_preflight.py` read (s3_log_bucket_set check at ~line 966)
- [ ] `scripts/session_postflight.py` read (run_auto() function at ~line 530)
- [ ] `scripts/execute_recommendation.py` read (file_hotfix_rec() at ~line 924)
- [ ] `scripts/executor/jsonl_store.py` read (_create_postmortem_recommendation() at ~line 340)
- [ ] `scripts/validate.py` read (validate_recommendations_schema() pattern at ~line 300)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> Execute these in sequence. Do not substitute the Scope table as a work list.

### Step 1: Modify `scripts/ops_writer.py` -- add outbox fallback

In the `write()` method, modify the except block (~line 164) that currently only logs
the S3 failure. Add outbox fallback logic:

1. After the existing `logger.warning(...)` line inside the except block, add:
   ```python
   self._write_to_outbox(table, staged)
   ```

2. Add a new private method `_write_to_outbox(self, table: str, entry: dict) -> None`:
   ```python
   def _write_to_outbox(self, table: str, entry: dict) -> None:
       """Write a failed S3 entry to the local outbox for later drain."""
       try:
           outbox_dir = Path(__file__).parent.parent / "logs" / ".ops-outbox" / table
           outbox_dir.mkdir(parents=True, exist_ok=True)
           outbox_file = outbox_dir / f"{uuid.uuid4()}.jsonl"
           outbox_file.write_text(
               json.dumps(entry, ensure_ascii=False) + "\n",
               encoding="utf-8",
           )
       except Exception as exc:  # noqa: BLE001
           logger.warning("ops_writer: outbox write failed for %s: %s", table, exc)
   ```

3. Add `from pathlib import Path` to the imports at the top of the file (if not already present).

4. Also add outbox fallback to the early-return path where `_get_client()` returns None
   (~line 159). Currently it silently returns. Add `self._write_to_outbox(table, staged)`
   before the return.

5. Do NOT add outbox when `_is_test_env()` returns True or when bucket is empty -- those
   are intentional no-ops.

Verify: `grep -q '_write_to_outbox' scripts/ops_writer.py` exits 0.

### Step 2: Update `tests/test_ops_writer.py` -- outbox fallback tests

Add a new test class `TestOpsWriterOutbox`:

- **(a)** Test that when `put_object` raises an exception, a file is created in
  `logs/.ops-outbox/{table}/` containing the entry JSON.
  Mock `_get_client()` to return a mock whose `put_object` raises `Exception("SSO expired")`.
  Use `tmp_path` and monkeypatch `Path(__file__).parent.parent` or mock `_write_to_outbox`
  to write to tmp_path. Verify file exists and contains the expected JSON.

- **(b)** Test that when `_get_client()` returns None (boto3 unavailable), the entry is
  written to outbox.

- **(c)** Test that in test env (`PYTEST_CURRENT_TEST` set), no outbox file is created.

- **(d)** Test that when bucket is empty, no outbox file is created.

Run: `python -m pytest tests/test_ops_writer.py -x -q` -- must exit 0.

### Step 3: Create `scripts/sync_ops.py`

Create the bidirectional sync script with:

**Module-level:**
- `logging.getLogger(__name__)` for all logging
- Constants: `_REPO_ROOT`, `_LOGS_DIR`, `_OUTBOX_DIR = _LOGS_DIR / ".ops-outbox"`
- Table-to-local-file mapping (same as existing read sites):
  ```python
  _TABLE_TO_LOCAL: dict[str, str] = {
      "ops_recommendations": ".recommendations-log.jsonl",
      "ops_execution_plans": ".execution-plans.jsonl",
      "ops_session_log": ".session-telemetry.jsonl",
      "ops_decisions": ".decisions-index.jsonl",
      "ops_priority_queue": "priority-queue/.priority-queue.jsonl",
  }
  ```
- Table-to-Athena-view mapping:
  ```python
  _TABLE_TO_VIEW: dict[str, str] = {
      "ops_recommendations": "ops_recommendations_current",
      "ops_execution_plans": "ops_execution_plans",
      "ops_session_log": "ops_session_log",
      "ops_decisions": "ops_decisions_current",
      "ops_priority_queue": "ops_priority_queue_current",
  }
  ```

**Functions:**

1. `check_sso() -> bool`:
   Run `aws sts get-caller-identity --profile company-aws-profile` via subprocess.
   Return True if exit code 0, False otherwise. Use `encoding='utf-8', errors='replace'`.

2. `drain() -> dict[str, int]`:
   - If `_OUTBOX_DIR` does not exist or is empty, return `{}`.
   - Import `OpsWriter` from `scripts.ops_writer` (lazy import).
   - For each table subdirectory in `_OUTBOX_DIR`:
     - For each `.jsonl` file in the subdirectory:
       - Read the JSON entry.
       - Call `OpsWriter().write(table, entry)`.
       - If write succeeds (no exception), delete the outbox file.
       - Count drained entries per table.
   - Return `{table: count}` dict.
   - Log summary: "Drained N entries for {table}".
   - Never raise -- catch and log all exceptions.

3. `pull(profile: str | None = None) -> dict[str, int]`:
   - If not `check_sso()`: log warning, return `{}`.
   - Import `boto3` (lazy import).
   - Create Athena client using profile if provided.
   - For each table in `_TABLE_TO_VIEW`:
     - Execute `SELECT * FROM trading_formulas_db.{view}` via Athena
       (workgroup `agent-platform-production`).
     - Poll for completion (max 120s, 2s intervals).
     - On success, paginate results with `get_query_results` using `NextToken`
       to fetch all pages (default page size is 1000 rows; ops_recommendations
       already has 500+ entries and will grow).
     - Convert rows to list of dicts (skip header row).
     - Write to local JSONL file (overwrite entire file).
     - Count rows per table.
   - Return `{table: row_count}` dict.
   - Log summary per table.
   - Never raise -- catch and log per-table, continue to next table on failure.

4. `sync(profile: str | None = None) -> dict[str, dict[str, int]]`:
   - Call `drain()`, then call `pull(profile)`.
   - Return `{"drained": drain_result, "pulled": pull_result}`.

5. `outbox_summary() -> dict[str, int]`:
   - Count files per table in `_OUTBOX_DIR`.
   - Return `{table: file_count}` dict. Empty dict if no outbox.
   - Used by preflight to surface outbox size without draining.

6. `main()` -- argparse CLI:
   - Subcommands: `drain`, `pull`, `sync`
   - `--profile` option (default: `company-aws-profile`)
   - Print results as JSON to stdout.

Verify: `python -m scripts.sync_ops drain` exits 0.

### Step 4: Create `tests/test_sync_ops.py`

Unit tests covering:

- **(a)** `drain()` with empty outbox returns `{}`.
- **(b)** `drain()` reads outbox files, calls `OpsWriter().write()` for each, deletes
  files on success. Mock OpsWriter. Use `tmp_path` for outbox directory.
- **(c)** `drain()` when OpsWriter.write() raises, file is NOT deleted (retry next time).
- **(d)** `pull()` with SSO expired returns `{}` with warning logged. Mock `check_sso()`.
- **(e)** `pull()` queries Athena, writes local JSONL files. Mock boto3 Athena client.
  Verify local file contains expected rows.
- **(f)** `sync()` calls drain then pull in order.
- **(g)** `outbox_summary()` counts files correctly.
- **(h)** `main()` with `--help` exits 0.

Mock `boto3`, `OpsWriter`, and `subprocess.run` in all tests. Use `tmp_path` and
monkeypatch for file paths. Never call real AWS APIs.

Run: `python -m pytest tests/test_sync_ops.py -x -q` -- must exit 0.

### Step 5: Modify `scripts/session_preflight.py` -- hook sync at session start

After the existing `s3_log_bucket_set` check (~line 966), add:

```python
# Outbox summary (always available, even without SSO)
try:
    from scripts.sync_ops import outbox_summary, sync as sync_ops_sync

    outbox = outbox_summary()
    if outbox:
        total = sum(outbox.values())
        print(f"Ops outbox: {total} pending entries ({outbox})", file=sys.stderr)
except Exception:  # noqa: BLE001
    outbox = {}

# Drain outbox + pull fresh data if SSO is active
if sso_status == "ok" and s3_log_bucket_set:
    try:
        result = sync_ops_sync()
        drained = sum(result.get("drained", {}).values())
        pulled = sum(result.get("pulled", {}).values())
        if drained or pulled:
            print(
                f"Ops sync: drained {drained} outbox entries, pulled {pulled} rows from Athena",
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001
        pass  # sync is best-effort
```

Add `"ops_outbox": outbox` to the `report` dict.

Verify: `grep -q 'sync_ops' scripts/session_preflight.py` exits 0.

### Step 6: Modify `scripts/session_postflight.py` -- hook sync at session end

In `run_auto()`, AFTER the `OpsWriter().compact_all()` call (~line 635), NOT after
log-housekeeping. This ordering is critical: drain flushes outbox entries to S3 staging,
then compact writes them to Iceberg, and only THEN does pull read fresh Iceberg data.
If placed before compact, pull returns stale Athena data missing the just-drained entries.

```python
# Best-effort ops sync (drain outbox + pull latest from Athena)
# MUST run after compact_all() so pull reads freshly-compacted Iceberg data
try:
    from scripts.sync_ops import sync as sync_ops_sync
    sync_ops_sync()
except Exception:  # noqa: BLE001
    pass  # sync must never fail session close
```

Verify: `grep -q 'sync_ops' scripts/session_postflight.py` exits 0.

### Step 7: Modify `scripts/execute_recommendation.py` -- fix hotfix bypass + add drain

Two changes:

**(a)** In `file_hotfix_rec()` (~line 971), after the existing `fh.write(...)` block
and before the `logger.info(...)` call, add:

```python
try:
    from scripts.ops_writer import OpsWriter
    OpsWriter().write("ops_recommendations", hotfix_rec)
except Exception:  # noqa: BLE001
    pass  # OpsWriter is best-effort
```

**(b)** In `execute_batch()` (~line 3059), after each rec completes successfully
(after the success/failure log at ~line 3108), add a drain-only call:

```python
try:
    from scripts.sync_ops import drain as drain_outbox
    drain_outbox()
except Exception:  # noqa: BLE001
    pass  # drain is best-effort; full sync runs at preflight/postflight only
```

Do NOT call full `sync()` here -- only `drain()`. See Constraints for cost rationale.

Verify: `grep -q 'OpsWriter' scripts/execute_recommendation.py` exits 0.

### Step 8: Modify `scripts/executor/jsonl_store.py` -- fix postmortem bypass

In `_create_postmortem_recommendation()` (~line 352), after the existing `fh.write(...)`
block and before the `logger.info(...)` call, add:

```python
try:
    from scripts.ops_writer import OpsWriter
    OpsWriter().write("ops_recommendations", postmortem)
except Exception:  # noqa: BLE001
    pass  # OpsWriter is best-effort
```

Verify: `grep -q 'OpsWriter' scripts/executor/jsonl_store.py` exits 0.

### Step 9: Update tests for bypass fixes

**(a)** In `tests/test_execute_recommendation.py`, add `@patch('scripts.execute_recommendation.OpsWriter')`
(or patch at the import site) to any test that calls `file_hotfix_rec()`. The mock prevents
real AWS calls. If OpsWriter is lazy-imported inside the function, patch
`scripts.ops_writer.OpsWriter` instead.

**(b)** In the jsonl_store test file, add similar mock for `_create_postmortem_recommendation()`
tests (if they exist). If no test exercises this function, note it for a future test addition.

Run: `python -m pytest tests/test_execute_recommendation.py -x -q` -- must exit 0.

### Step 10: Modify `scripts/validate.py` -- outbox staleness check

Add a new function `validate_outbox_staleness(failed: list[str]) -> None`:

```python
def validate_outbox_staleness(failed: list[str]) -> None:
    """Warn if ops outbox has files older than 24 hours."""
    print("\n=== Ops outbox staleness check ===")
    outbox_dir = _ROOT / "logs" / ".ops-outbox"
    if not outbox_dir.exists():
        print("  No outbox directory -- OK")
        return
    import time
    now = time.time()
    stale_count = 0
    for table_dir in outbox_dir.iterdir():
        if not table_dir.is_dir():
            continue
        for f in table_dir.glob("*.jsonl"):
            age_hours = (now - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_count += 1
    if stale_count > 0:
        msg = f"  WARNING: {stale_count} outbox entries older than 24h -- run: python -m scripts.sync_ops drain"
        print(msg)
        # Warning only, not a hard failure (SSO may be legitimately unavailable).
        # Uncomment the next line to make it a hard failure:
        # failed.append(msg)
    else:
        total = sum(1 for _ in outbox_dir.rglob("*.jsonl"))
        print(f"  {total} outbox entries, none stale -- OK")
```

Call this function from the main validation sequence (in `validate_all()` or wherever
the other `validate_*` functions are called), after `validate_recommendations_schema()`.

Verify: `grep -q 'validate_outbox_staleness' scripts/validate.py` exits 0.

### Step 11: Update `tests/test_validate.py`

Add `TestValidateOutboxStaleness` class:

- **(a)** No outbox directory: passes with "No outbox directory" message.
- **(b)** Outbox with recent files (< 24h): passes with count displayed.
- **(c)** Outbox with stale files (> 24h): prints WARNING.

Use `tmp_path` for outbox directory. Monkeypatch `_ROOT` in validate module.

Run: `python -m pytest tests/test_validate.py -x -q` -- must exit 0.

### Step 12: Modify `.gitignore`

After the existing ops JSONL entries (~line 101), add:

```
# Outbox (local staging for failed S3 writes -- drained by sync_ops)
logs/.ops-outbox/
```

Verify: `grep -q 'ops-outbox' .gitignore` exits 0.

### Step 13: Record Decision 51 in `docs/DECISIONS.md`

Find the last numbered decision entry and add Decision 51:

```markdown
### 51. Local-first outbox + bidirectional sync for ops data

**Status:** Decided
**Date:** 2026-04-23

**Problem:** Agent sessions lose operational writes when SSO expires (OpsWriter.write()
silently no-ops) and start with stale local data because nothing pulls from Athena.
The self-improvement loop cannot function if the system cannot reliably read its own
history or persist new observations.

**Decision:** Adopt a local-first outbox pattern:
- **Writes:** All writes go through OpsWriter.write(). On S3 failure, entries are written
  to a local outbox (`logs/.ops-outbox/{table}/{uuid}.jsonl`).
- **Reads:** Agents always read local JSONL files. A `sync_ops.py` script pulls the latest
  state from Athena `_current` views and overwrites local files.
- **Sync:** `sync_ops.py` runs drain-then-pull. Integrated into preflight (session start),
  postflight (session end), and executor between-rec checkpoints.
- **Enforcement:** validate.py warns on stale outbox entries (> 24h).

**Rationale:** Deterministic local reads (no network dependency for reads), no data loss
on SSO expiry (outbox persists), idempotent flush (Iceberg deduplicates via ingested_at),
and structurally-enforced freshness via hooks in every session lifecycle phase.
```

Verify: `grep -q 'Decision 51' docs/DECISIONS.md` exits 0 (or however decisions are numbered there).

### Step 14: Run all affected tests

```bash
python -m pytest tests/test_sync_ops.py tests/test_ops_writer.py tests/test_execute_recommendation.py tests/test_validate.py tests/test_session_preflight.py tests/test_session_postflight.py -x -q
```

All tests must pass. Fix any failures before proceeding.

### Step 15: Run `ruff check --fix` and `ruff format`

```bash
ruff check --fix scripts/ops_writer.py scripts/sync_ops.py scripts/session_preflight.py scripts/session_postflight.py scripts/execute_recommendation.py scripts/executor/jsonl_store.py scripts/validate.py tests/test_sync_ops.py tests/test_ops_writer.py tests/test_execute_recommendation.py tests/test_validate.py
ruff format scripts/ops_writer.py scripts/sync_ops.py scripts/session_preflight.py scripts/session_postflight.py scripts/execute_recommendation.py scripts/executor/jsonl_store.py scripts/validate.py tests/test_sync_ops.py tests/test_ops_writer.py tests/test_execute_recommendation.py tests/test_validate.py
```

### Step 16: Run `python -m scripts.validate`

Must exit 0. Fix any issues before proceeding.

### Step 17: Lambda build and deploy

```bash
python -m scripts.build_lambda --deploy
```

Must exit 0. This rebuilds `data-pipeline.zip` to include the updated `ops_writer.py`
with the outbox fallback and deploys it to Lambda. The outbox path is unreachable in
Lambda (S3 is always available there), but deploy verifies the Lambda can import the
modified module without syntax/import errors.

### Step 18: Integration test with SSO

If SSO is active:

```bash
export S3_LOG_BUCKET=agent-platform-agent-logs
python -m scripts.sync_ops pull --profile company-aws-profile
```

Verify local JSONL files are updated with data from Athena. Check:
- `wc -l logs/.recommendations-log.jsonl` shows > 0 lines
- `wc -l logs/.execution-plans.jsonl` shows > 0 lines
- `wc -l logs/.session-telemetry.jsonl` shows > 0 lines
- `wc -l logs/.decisions-index.jsonl` shows > 0 lines

If SSO is expired, skip this step -- the unit tests (Step 14) cover the logic.

### Step 19: Report

Report what was implemented:
- List each file changed and the nature of the change.
- Confirm all Acceptance Criteria pass.
- Note Decision 51 was recorded.
- Note any design decisions made during implementation.
