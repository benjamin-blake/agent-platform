# Plan

## Intent
Establish a single mandatory gateway for all recommendation and decision writes, enforcing DynamoDB-based ID allocation, Pydantic validation, and OpsWriter S3 staging on every operation. This eliminates the current drift where three separate write paths (Copilot Chat inline python, executor file_hotfix_rec, jsonl_store in-place rewrite) bypass the intended S3-first architecture. After this plan, the local JSONL becomes a read-only cache pulled from Athena, and all writes flow exclusively through `scripts/ops_data_portal.py`.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/platform-ops-data-portal

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/ops_data_portal.py | Create | Unified write gateway: `file_rec()`, `update_rec()`, `file_decision()`, `update_decision()`, plus CLI entrypoint |
| scripts/execute_recommendation.py | Modify | Replace `file_hotfix_rec()` internals to delegate to `ops_data_portal.file_rec()` |
| scripts/executor/jsonl_store.py | Modify | Replace `update_recommendation_status()` to delegate to `ops_data_portal.update_rec()`, replace `_create_postmortem_recommendation()` to delegate to `ops_data_portal.file_rec()`, redirect `_reset_rec_status()` through portal, deprecate `get_next_rec_id()` |
| scripts/sync_recommendations.py | Modify | Remove `merge_from_s3()`, `push_closures_to_s3()`, `_read_agent_recs()`, `_write_agent_recs()`, `_write_local_recs()` (dead code under new architecture); remove `--merge` and `--push-closures` flags |
| scripts/session_preflight.py | Modify | Replace `merge_from_s3()` call with `sync_ops.pull("ops_recommendations")` |
| scripts/session_postflight.py | Modify | Remove `push_closures_to_s3()` import and call block; wire `drain_pending()` before `sync_ops.sync()`; confirm sync_ops.sync() already covers cache refresh |
| scripts/validate.py | Modify | Add `validate_rec_write_paths()` that scans `.py` files for direct JSONL writes; whitelist only portal and sync_recommendations |
| .github/copilot-instructions.md | Modify | Add Known Gotcha enforcing portal usage; update Recommendations Log Schema section |
| tests/test_ops_data_portal.py | Create | Full test coverage for file_rec, update_rec, file_decision, update_decision, offline outbox |
| tests/test_sync_recommendations.py | Modify | Remove tests for merge_from_s3/push_closures_to_s3; add test that `--merge` and `--push-closures` flags are rejected |
| tests/test_validate.py | Modify | Add test for validate_rec_write_paths rule |
| tests/test_execute_recommendation.py | Modify | Update `TestHotfixBranch` tests to mock `ops_data_portal.file_rec` instead of asserting local JSONL writes |
| tests/test_executor_jsonl_store.py | Modify | Update `_reset_rec_status` and `_create_postmortem_recommendation` tests to verify portal delegation |

## Bundled Recommendations
- rec-521: Centralised rec ID allocation via DynamoDB atomic counter (already implemented; this plan wires it as the ONLY path)

## Acceptance Criteria
- [ ] `python -m scripts.ops_data_portal --file-rec --title "test" --file scripts/ops_data_portal.py --context "test" --acceptance "true" --effort XS --priority Low --source planning --risk low` prints `rec-NNN` and writes to OpsWriter staging (or outbox if offline)
- [ ] `python -m scripts.ops_data_portal --update-rec rec-NNN --status closed --execution_result success` updates the rec via OpsWriter
- [ ] `python -m scripts.ops_data_portal --file-decision --title "test" --status open --rationale "test"` prints decision ID
- [ ] No `.py` file outside the whitelist directly writes to `.recommendations-log.jsonl` (enforced by validate.py)
- [ ] `python -m scripts.validate` exits 0 (including new write-path enforcement rule)
- [ ] `python -m pytest tests/test_ops_data_portal.py tests/test_sync_recommendations.py -x -q` passes
- [ ] `file_hotfix_rec()` delegates to portal (does not allocate IDs locally)
- [ ] `update_recommendation_status()` delegates to portal (does not rewrite local file directly)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Portal file_rec with mocked DynamoDB | `python -m pytest tests/test_ops_data_portal.py -x -q -k file_rec` | All tests pass | Fix portal logic |
| 2 | [pre-deploy] | Portal update_rec with mocked OpsWriter | `python -m pytest tests/test_ops_data_portal.py -x -q -k update_rec` | All tests pass | Fix update logic |
| 3 | [pre-deploy] | Portal offline fallback queues to outbox | `python -m pytest tests/test_ops_data_portal.py -x -q -k offline` | Rec queued to outbox | Fix outbox path |
| 4 | [pre-deploy] | Validate catches illegal direct appends | `python -m pytest tests/test_validate.py -x -q -k rec_write_paths` | Test passes | Fix regex or whitelist |
| 5 | [pre-deploy] | Full validate passes | `python -m scripts.validate` | Exit 0 | Fix whatever validate reports |
| 6 | [pre-deploy] | file_hotfix_rec delegates to portal | `grep -q "ops_data_portal" scripts/execute_recommendation.py` | Exit 0 | Fix delegation |
| 7 | [pre-deploy] | update_recommendation_status delegates | `grep -q "ops_data_portal" scripts/executor/jsonl_store.py` | Exit 0 | Fix delegation |
| 8 | [pre-deploy] | merge_from_s3 removed | `! grep -q "def merge_from_s3" scripts/sync_recommendations.py` | Exit 0 (function absent) | Remove function |

## Constraints
- DynamoDB `agent-platform-counters` table must already exist and be seeded (prerequisite: ops-data-pipeline plan)
- `sync_recommendations.next_id()` already works -- portal calls it, does not reimplement
- OpsWriter existing outbox pattern (`logs/.ops-outbox/`) reused for offline fallback
- Portal must NOT import from `execute_recommendation.py` or circular deps will result
- Local JSONL transitions to read-only cache -- portal writes to OpsWriter AND write-through to local (transitional)
- Windows-compatible: no bash idioms in portal code
- Pydantic `Recommendation` model from `jsonl_store.py` reused for validation

## Context
- DynamoDB counter and `next_id()` already exist in `sync_recommendations.py`
- OpsWriter handles S3 staging + local outbox fallback -- portal just calls `OpsWriter().write()`
- `Recommendation` Pydantic model in `scripts/executor/jsonl_store.py` -- reuse for validation
- Four write paths to consolidate: (1) `file_hotfix_rec` in execute_recommendation.py, (2) `update_recommendation_status` + `_create_postmortem_recommendation` + `_reset_rec_status` in jsonl_store.py, (3) inline terminal python from Copilot Chat, (4) `get_next_rec_id` local allocation (deprecated)
- The `agent-*` ID concept in `merge_from_s3()/push_closures_to_s3()` was never activated -- remove entirely
- Decision 51 (Local-First Outbox) governs offline: queue to outbox, drain on next postflight
- Offline mode (Option B): rec queued without ID to pending outbox; Pydantic validation is SKIPPED for pending entries (ID is required field); validate when draining with allocated ID
- `sync_ops.py::pull()` already handles Athena -> local cache sync for ops_recommendations -- reuse it instead of building a parallel sync path
- Portal imports `Recommendation` from `jsonl_store.py`; `jsonl_store.py` imports from portal at function level (deferred) to avoid circular imports

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Part 1: Create the Portal

1. **Create `scripts/ops_data_portal.py`** -- Single gateway module with:
   - Imports: `sync_recommendations.next_id`, `ops_writer.OpsWriter`, `executor.jsonl_store.Recommendation` (validation), `executor.jsonl_store.RECS_JSONL` (write-through)
   - **`file_rec(fields: dict, profile: str | None = None) -> str`**:
     - Call `next_id("recommendations", profile=profile)`. If RuntimeError (DynamoDB unreachable): write `fields` (with `id: None`) to `logs/.ops-outbox/ops_recommendations_pending/{uuid}.json`, return `"pending-{uuid}"` (skip validation for pending entries -- validate when draining)
     - Merge allocated ID + `date` (default today) into fields
     - Validate via `Recommendation.model_validate(fields)` -- raise on schema failure (only when ID was allocated successfully)
     - Call `OpsWriter().write("ops_recommendations", fields)`
     - Write-through: append validated record to local JSONL (transitional)
     - Return allocated ID string (e.g. `rec-522`)
   - **`update_rec(rec_id: str, updates: dict, profile: str | None = None) -> bool`**:
     - Read current rec from local JSONL via `jsonl_store.load_recommendation(rec_id)`
     - If not found locally, proceed with updates-only (Athena is source of truth)
     - Merge updates into existing record
     - Validate merged record via `Recommendation.model_validate(merged)`
     - Call `OpsWriter().write("ops_recommendations", merged)` (last-write-wins in Iceberg)
     - Write-through: atomic rewrite of matching line in local JSONL
     - Return True on success
   - **`file_decision(fields: dict, profile: str | None = None) -> int`**:
     - Call `next_id("decisions", profile=profile)`. If RuntimeError: queue to outbox, return -1
     - Merge `decision_id` + `date` into fields
     - Call `OpsWriter().write("ops_decisions", fields)`
     - Return the decision ID integer
   - **`update_decision(decision_id: int, updates: dict, profile: str | None = None) -> bool`**:
     - Merge updates into record with `decision_id`
     - Call `OpsWriter().write("ops_decisions", merged)`
     - Return True
   - **CLI** (`def main()` + argparse):
     - `--file-rec` with required: `--title`, `--file`, `--context`, `--acceptance`, `--effort`, `--priority`, `--source`, `--risk`; optional: `--automatable`, `--tags`, `--dependencies`, `--verification`, `--verification-tier`
     - `--update-rec REC_ID` with optional updatable fields
     - `--file-decision` with: `--title`, `--status`, `--rationale`
     - `--update-decision DECISION_ID` with optional fields
     - `--profile` for AWS override
     - Print ID to stdout on success; error to stderr + exit 1 on failure

### Part 2: Redirect Existing Write Paths

2. **Modify `scripts/execute_recommendation.py::file_hotfix_rec()`**:
   - Remove local max-ID allocation logic
   - Remove `RECS_JSONL.open("a")` direct write
   - Remove `OpsWriter().write()` call (portal handles both)
   - New body: `from scripts.ops_data_portal import file_rec; return file_rec({...hotfix fields...})`
   - Keep function signature unchanged

2b. **Update `tests/test_execute_recommendation.py::TestHotfixBranch`**:
   - Mock `scripts.ops_data_portal.file_rec` instead of asserting direct local JSONL writes
   - Assert `file_rec` is called with expected fields from the hotfix
   - Remove assertions that read `RECS_JSONL` directly (portal handles write-through)

3. **Modify `scripts/executor/jsonl_store.py::update_recommendation_status()`**:
   - Remove full-file read/rewrite pattern
   - New body: `from scripts.ops_data_portal import update_rec; return update_rec(rec_id, updates)`
   - Keep function signature and ValidationError raise behavior

4. **Modify `scripts/executor/jsonl_store.py::_create_postmortem_recommendation()`**:
   - Remove local ID allocation and direct JSONL append
   - New body: `from scripts.ops_data_portal import file_rec; file_rec({...postmortem fields...})`

4b. **Modify `scripts/executor/jsonl_store.py::_reset_rec_status()`**:
   - Remove `_atomic_write(RECS_JSONL, ...)` direct file rewrite
   - New body: call `from scripts.ops_data_portal import update_rec` with `{"status": "open"}` + removal of failure fields

4c. **Deprecate `scripts/executor/jsonl_store.py::get_next_rec_id()`**:
   - Replace body with: `raise DeprecationWarning("Use scripts.ops_data_portal.file_rec() which allocates IDs via DynamoDB")`
   - Or simply remove if grep shows no remaining callers

4d. **Update `tests/test_executor_jsonl_store.py`**:
   - Update `_reset_rec_status` tests to mock `scripts.ops_data_portal.update_rec` and assert delegation
   - Update `_create_postmortem_recommendation` tests to mock `scripts.ops_data_portal.file_rec` and assert delegation
   - Remove assertions that check direct `_atomic_write` calls to local JSONL

### Part 3: Cache Sync (via existing sync_ops.py)

5. **Clean up `scripts/sync_recommendations.py`**:
   - **Remove**: `merge_from_s3()`, `push_closures_to_s3()`, `_read_agent_recs()`, `_write_agent_recs()`, `_write_local_recs()` (all dead code under new architecture)
   - Keep: `next_id()`, `seed_counters()`, `_read_local_recs()` (still needed for read)
   - Update argparse: remove `--merge` and `--push-closures` flags

6. **Modify `scripts/session_preflight.py`**:
   - Replace `merge_from_s3()` call with `from scripts.sync_ops import pull; pull()` (pulls ALL ops tables including ops_recommendations; heavier than targeted pull but correct given pull() signature takes a profile, not a table name)
   - Remove import of `merge_from_s3` from sync_recommendations

7. **Modify `scripts/session_postflight.py`**:
   - Remove `from scripts.sync_recommendations import push_closures_to_s3` import (line 64)
   - Remove the `push_closures_to_s3()` call block (lines 670-675)
   - Confirm `sync_ops.sync()` at line 695 already covers the same responsibility (push local changes + pull remote state)

### Part 3b: Pending Outbox Drain

7b. **Add `drain_pending()` to `scripts/ops_data_portal.py`**:
   - Scan `logs/.ops-outbox/ops_recommendations_pending/` for `*.json` files
   - For each file: load fields, call `next_id("recommendations")` to allocate an ID, merge ID + date, validate via `Recommendation.model_validate()`, write through `OpsWriter().write("ops_recommendations", rec)`, append to local JSONL, delete the pending file
   - If DynamoDB is still unreachable during drain: skip file, log warning, leave it for next drain attempt
   - Return `{"drained": N, "skipped": M}`
   - Wire into session_postflight.py: call `drain_pending()` before `sync_ops.sync()` so drained entries get included in the sync
   - Add tests: `test_drain_pending_success`, `test_drain_pending_dynamo_still_down`, `test_drain_pending_empty_dir`

### Part 4: Enforce

8. **Add `validate_rec_write_paths(failed: list[str])` to `scripts/validate.py`**:
   - Scan all `.py` under `scripts/` (recursively)
   - Skip whitelist: `scripts/ops_data_portal.py`, `scripts/sync_recommendations.py`
   - Detect patterns: `RECS_JSONL.open("a"`, `RECS_JSONL.open("w"`, `recommendations-log.jsonl` + `open(` + mode `a/w`
   - If match: `failed.append(f"Direct rec JSONL write in {file}:{lineno}")`
   - Wire into main validation flow

9. **Update `.github/copilot-instructions.md`**:
   - Add to Known Gotchas: "**Rec/Decision Write Portal (Critical):** Never append to logs/.recommendations-log.jsonl or logs/.decisions-index.jsonl directly. All writes MUST go through `python -m scripts.ops_data_portal` or `from scripts.ops_data_portal import file_rec, update_rec, file_decision, update_decision`. Direct file writes fail CI via `validate.py`. The local JSONL is a read-only cache refreshed from Athena via `sync_ops.pull()`."
   - Update File Router: add `| Rec/Decision write portal | [scripts/ops_data_portal.py](../scripts/ops_data_portal.py) |`

### Part 5: Tests

10. **Create `tests/test_ops_data_portal.py`**:
    - `test_file_rec_success`: mock next_id returns "rec-600", mock OpsWriter.write; assert returns "rec-600", OpsWriter called with validated record, local JSONL has new line
    - `test_file_rec_offline`: mock next_id raises RuntimeError; assert returns "pending-*", outbox file created in `ops_recommendations_pending/`
    - `test_file_rec_invalid_schema`: pass fields missing required key; assert raises ValidationError
    - `test_update_rec_success`: mock load_recommendation returns existing rec; assert OpsWriter called with merged record, local JSONL updated
    - `test_update_rec_invalid_status`: pass `status="done"`; assert raises ValueError
    - `test_file_decision_success`: mock next_id returns 56; assert OpsWriter called, returns 56
    - `test_cli_file_rec`: mock internals, invoke main with args, assert stdout contains rec ID
    - `test_drain_pending_success`: create pending file, mock next_id returns "rec-601"; assert file drained, OpsWriter called, pending file deleted
    - `test_drain_pending_dynamo_still_down`: mock next_id raises RuntimeError; assert pending file still exists, skipped count > 0
    - `test_drain_pending_empty_dir`: no pending files; assert returns `{"drained": 0, "skipped": 0}`

11. **Update `tests/test_sync_recommendations.py`**:
    - Remove: tests for `merge_from_s3`, `push_closures_to_s3`, `_read_agent_recs`, `_write_agent_recs`
    - Add: test that `--merge` and `--push-closures` flags are no longer accepted

12. **Add to tests for validate** (in `tests/test_validate.py` or existing test file):
    - `test_validate_rec_write_paths_catches_violation`: create a temp .py file with direct append, assert it fails
    - `test_validate_rec_write_paths_allows_whitelist`: assert portal file itself does not trigger

### Part 6: Validation

13. Run `python -m pytest tests/test_ops_data_portal.py tests/test_sync_recommendations.py -x -q` -- all must pass

14. Run `python -m scripts.validate` -- must exit 0

15. **Execute Verification Plan** -- run each step. Fix until all pass.

16. Report: what was implemented, verification results, bugs found and fixed
