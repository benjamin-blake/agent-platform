# Plan

## Intent
Stop the ongoing flood of "Investigate executor failure for rec-100" recommendations bleeding into `logs/.recommendations-log.jsonl` from a stale pending-outbox queue. Adds dedupe at every write path that can mint executor postmortems, purges the existing 27 duplicates, and lays defence-in-depth so the same loop cannot recur if the executor is reactivated.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2 (Python source, mocked DynamoDB at the unit boundary, plus an Athena read for end-to-end confirmation)

## Branch
agent/fix-postmortem-bleed

## Phase
Phase 1: Core Infrastructure (COMPLETE) — this is platform hygiene against a regression discovered in the recommendation pipeline.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_data_portal.py` | Modify | Add `find_open_postmortem_for(failed_rec_id)` helper; modify `drain_pending()` to consult it before allocating a new ID for any record where `source == "executor-postmortem"`; add `purge_postmortems_for(failed_rec_id)` that deletes matching DynamoDB items via `boto3` and rewrites the local JSONL cache; add a `--purge-postmortems-for REC_ID` CLI subcommand. |
| `scripts/executor/jsonl_store.py` | Modify | `_create_postmortem_recommendation` consults the helper; updates the existing open postmortem's `context` field with an incremented attempt counter instead of filing a new one. |
| `scripts/execute_recommendation.py` | Modify | Rec selector skips any rec that has at least one open `executor-postmortem` recommendation referencing it in the title; honour `ALLOW_POISONED_RECS=true` env override for human-driven retries. |
| `tests/test_ops_data_portal.py` | Modify | Unit tests for `find_open_postmortem_for`, the dedupe branch in `drain_pending`, and `purge_postmortems_for` (mocked DynamoDB). |
| `tests/test_executor_jsonl_store.py` | Modify | Extend `TestCreatePostmortemRecommendation` with the existing-open-postmortem branch (asserts `update_rec` called, not `file_rec`). |

## Bundled Recommendations
None. The top-5 priority queue items (rec-429, rec-435, rec-325, rec-340, rec-497) do not align with this fix.

## Infrastructure Dependencies
None. No `.tf` files, no Lambda deploy.

## Acceptance Criteria
- [ ] `_create_postmortem_recommendation` does not call `file_rec` when an open postmortem for the same `failed_rec_id` already exists; instead it calls `update_rec` to bump the attempt counter in the existing record's `context` field.
- [ ] `drain_pending` does not allocate a new DynamoDB ID for a pending postmortem when an open postmortem for the same `failed_rec_id` already exists; the pending file is deleted, the existing record is updated.
- [ ] The rec selector in `execute_recommendation.py` skips any rec with ≥1 open `executor-postmortem` referencing its ID, unless `ALLOW_POISONED_RECS=true`.
- [ ] After running `python -m scripts.ops_data_portal --purge-postmortems-for rec-100 --profile company-aws-profile`:
  - All 14 stale `*.json` files in `logs/.ops-outbox/ops_recommendations_pending/` whose title contains `rec-100` are deleted.
  - The 27 already-drained "Investigate executor failure for rec-100" entries are removed from `logs/.recommendations-log.jsonl` and from the `ops_recommendations` DynamoDB table.
  - rec-100 itself is updated to `status=declined` with a resolution noting the SCP block on IAM/OIDC operations and the cleanup operation.
- [ ] Athena view `ops_recommendations_current` returns zero rows for `WHERE title LIKE 'Investigate executor failure for rec-100%' AND status = 'open'` after a `sync_ops pull`.
- [ ] `python -m scripts.validate --quick` passes; new tests in `tests/test_ops_data_portal.py` and `tests/test_executor_jsonl_store.py` pass.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Run new and existing unit tests for the portal dedupe + purge surface. | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -q` | All tests pass; new tests for `find_open_postmortem_for`, drain dedupe, and purge behaviour are visible in output. | Tests fail: read assertion, fix the helper or its caller. Do not weaken assertions. |
| 2 | [pre-deploy] | Run new and existing unit tests for `_create_postmortem_recommendation`. | `.venv/Scripts/python.exe -m pytest tests/test_executor_jsonl_store.py::TestCreatePostmortemRecommendation -q` | All tests pass, including the new "open postmortem already exists" branch which asserts `update_rec` is called and `file_rec` is not. | If file_rec is still called: dedupe helper not wired; trace the call. |
| 3 | [pre-deploy] | Exercise the dedupe path against the real local JSONL with mocked DynamoDB to confirm `_create_postmortem_recommendation` updates instead of files when a duplicate exists. | `.venv/Scripts/python.exe -c "from unittest.mock import patch; from scripts.executor.jsonl_store import _create_postmortem_recommendation; from scripts.ops_data_portal import find_open_postmortem_for; print('helper finds existing rec-100 postmortem:', find_open_postmortem_for('rec-100') is not None)"` | Prints `helper finds existing rec-100 postmortem: True` (proves the helper sees the 27 currently-poisoned entries before cleanup). | If False: helper signature/lookup wrong, check fixture data or JSONL path. |
| 4 | [pre-deploy] | Confirm rec selector skips rec-100 when its open postmortems exist. | `.venv/Scripts/python.exe -c "from scripts.execute_recommendation import _is_poisoned_rec; print('rec-100 poisoned:', _is_poisoned_rec('rec-100'))"` | Prints `rec-100 poisoned: True`. | If False: selector helper not reading recs correctly. |
| 5 | [pre-deploy] | Confirm env override disables the skip. | `ALLOW_POISONED_RECS=true .venv/Scripts/python.exe -c "import os; from scripts.execute_recommendation import _is_poisoned_rec; print('override active:', not _is_poisoned_rec('rec-100'))"` | Prints `override active: True`. | If False: env-var reading not wired. |
| 6 | [pre-deploy] | Run the cleanup CLI in dry-run mode (added flag) to preview deletions before applying. | `.venv/Scripts/python.exe -m scripts.ops_data_portal --purge-postmortems-for rec-100 --dry-run --profile company-aws-profile` | Reports plan: 14 pending files to delete, 27 JSONL entries to remove, 27 DynamoDB items to delete, rec-100 to be declined. No filesystem or DynamoDB writes. | If write attempted: dry-run flag not honoured. |
| 7 | [pre-deploy] | Apply the cleanup. | `.venv/Scripts/python.exe -m scripts.ops_data_portal --purge-postmortems-for rec-100 --profile company-aws-profile` | Reports: 14 pending files deleted, 27 JSONL entries removed, 27 DynamoDB items deleted, rec-100 declined. Exit code 0. | If error: capture error, fix portal logic, retry. |
| 8 | [pre-deploy] | Confirm pending outbox is clean of rec-100 references. | `.venv/Scripts/python.exe -c "from pathlib import Path; import json; matches = [f for f in Path('logs/.ops-outbox/ops_recommendations_pending').glob('*.json') if 'rec-100' in json.loads(f.read_text(encoding='utf-8')).get('title','')]; print('rec-100 pending files remaining:', len(matches))"` | Prints `rec-100 pending files remaining: 0`. | If > 0: cleanup did not iterate all files; check filter. |
| 9 | [pre-deploy] | Confirm local JSONL is clean of duplicate rec-100 postmortems. | `.venv/Scripts/python.exe -c "import json; recs = [json.loads(l) for l in open('logs/.recommendations-log.jsonl', encoding='utf-8') if l.strip()]; matches = [r for r in recs if r.get('title','').startswith('Investigate executor failure for rec-100')]; print('rec-100 postmortems in local JSONL:', len(matches))"` | Prints `rec-100 postmortems in local JSONL: 0`. | If > 0: JSONL rewrite missed entries; check filter. |
| 10 | [pre-deploy] | Confirm rec-100 itself is declined. | `.venv/Scripts/python.exe -c "import json; r = next(j for l in open('logs/.recommendations-log.jsonl', encoding='utf-8') if (j := json.loads(l)).get('id') == 'rec-100'); print('rec-100 status:', r.get('status'))"` | Prints `rec-100 status: declined`. | If still open: update_rec call missing from cleanup. |
| 11 | [post-cleanup, AWS] | Sync the local cache from Athena to confirm the source-of-truth no longer contains the duplicates. | `.venv/Scripts/python.exe -m scripts.sync_ops pull --profile company-aws-profile` | Reports row counts; ops_recommendations count drops by ~27 from baseline. | If sync errors: confirm SSO via `aws sts get-caller-identity --profile company-aws-profile`. |
| 12 | [post-cleanup, AWS] | Direct Athena query to confirm Athena has zero open rec-100 postmortems (user-requested sanity check). | `aws athena start-query-execution --query-string "SELECT count(*) AS open_rec100_postmortems FROM ops.ops_recommendations_current WHERE title LIKE 'Investigate executor failure for rec-100%%' AND status = 'open'" --result-configuration "OutputLocation=s3://agent-platform-agent-logs/athena-results/" --query-execution-context "Database=ops" --profile company-aws-profile --output text --query 'QueryExecutionId'` then poll: `aws athena get-query-results --query-execution-id <ID> --profile company-aws-profile --output json` | Single row, single column, value `0`. | If > 0: Athena view stale; wait for OpsWriter compaction (every ~10 min) and retry; if persistent, inspect `ops_recommendations` Iceberg snapshots for the deletion record. |
| 13 | [post-cleanup, AWS] | Confirm rec-100 is declined in Athena. | `aws athena start-query-execution --query-string "SELECT id, status FROM ops.ops_recommendations_current WHERE id = 'rec-100'" --result-configuration "OutputLocation=s3://agent-platform-agent-logs/athena-results/" --query-execution-context "Database=ops" --profile company-aws-profile --output text --query 'QueryExecutionId'` then poll `aws athena get-query-results`. | Single row: id=rec-100, status=declined. | If still open: re-run `--update-rec rec-100 --status declined` via portal CLI. |
| 14 | [post-cleanup] | Re-run preflight to confirm the priority queue and non-automatable counts no longer surface rec-100 postmortems. | `.venv/Scripts/python.exe -m scripts.session_preflight` | `non_automatable_recommendations` count drops by ~27. No "Investigate executor failure for rec-100" entries appear in `non_automatable_details`. | If still surfaced: cache not refreshed; re-run `sync_ops pull`. |
| 15 | [pre-deploy] | Full validate sweep before commit. | `.venv/Scripts/python.exe -m scripts.validate --quick` | All checks pass. | Fix lint/test failures before committing. |

## Constraints
- Single Portal Invariant (Decision 51): all writes and the new physical delete operation MUST go through `scripts/ops_data_portal.py`. The cleanup script does not write directly to `logs/.recommendations-log.jsonl`; it calls portal APIs and the portal updates the cache.
- RCA-First Architecture (Decision 55): no rescue agents, no workaround loops. The dedupe + selector skip are deterministic guards, not LLM-mediated repair.
- Self-Modification Boundary (Decision 44): `scripts/execute_recommendation.py` and `scripts/executor/*.py` are boundary files — they CAN be modified through this `/plan` → `/implement` flow because the plan was written by the human-supervised planner, not the executor itself. The new test files and portal helper sit on the same boundary side.
- No comments in new code unless the *why* is non-obvious (per CLAUDE.md). Type hints required.
- Windows shell: prefer `.venv/Scripts/python.exe` over bare `python` (CLAUDE.md).
- Test isolation: new tests must mock `scripts.ops_data_portal.file_rec`, `update_rec`, and any boto3 client at the unit boundary. No live DynamoDB or Athena calls during pytest.
- Schema compatibility: the attempt-counter update modifies `context` and `last_updated_timestamp` only. No new fields on the Recommendation Pydantic model — keeps the change V2-only with no schema migration.
- **JSONL rewrite safety (Windows)**: `purge_postmortems_for` must use the rename-create-delete pattern: write new content to `logs/.recommendations-log.jsonl.new`, atomically rename existing to `logs/.recommendations-log.jsonl.old`, rename `.new` to canonical, then delete `.old`. Mirrors the `_atomic_write` pattern at `scripts/executor/jsonl_store.py:301-320`. Prevents partial-write corruption on Windows where file replace can fail under handle contention.
- **Title matching is case-sensitive on `rec-NNN`**: the postmortem title format is fixed (`Investigate executor failure for rec-{N}` with lowercase `rec-`); `find_open_postmortem_for` matches strictly on this lowercase pattern. No need for case-insensitive matching given the producer-side format guarantee.
- **Deferred imports preserved**: in `scripts/executor/jsonl_store.py`, the call to `find_open_postmortem_for` MUST follow the existing deferred-import pattern at `_create_postmortem_recommendation:274` (`from scripts.ops_data_portal import file_rec  # noqa: PLC0415`). Top-level import would risk a circular dependency on the executor → portal axis.

## Context
- **Root cause discovered during planning**: `session_postflight.py:679` calls `drain_pending()` from `ops_data_portal.py` at the end of every `/plan` and `/implement` session. That function blindly drains `*.json` files from `logs/.ops-outbox/ops_recommendations_pending/`, allocating a fresh DynamoDB rec ID per file. 14 stale rec-100 postmortems queued in mid-April (when the executor ran offline) are still in that directory and continue to drip into the visible log.
- **Why rec-100 specifically**: per its own `resolution` field, `agent/rec-100` became a kitchen-sink branch causing 1222 phantom telemetry entries via a `skip_to_postflight` feedback loop. SCP blocks IAM/OIDC operations, making rec-100 fundamentally un-executable. See rec-331..rec-336 for the structural fixes that were already filed.
- **Why the bleed wasn't noticed earlier**: the original `_create_postmortem_recommendation` was added before the offline-mode pending outbox existed, so it had no dedupe. When the offline outbox was added (Decision 51), `drain_pending` was wired to ID allocation but inherited no knowledge of postmortem semantics.
- **Why dedupe goes in two places**: `_create_postmortem_recommendation` is the production source for new postmortems; `drain_pending` is the source for old queued ones. Both must check.
- **User intent on cleanup**: physically remove the 27 poisoned recs (not just mark declined) — the rec log is still being verified for production use, so physical removal is acceptable in this exceptional case. Hard delete from DynamoDB requires a new portal API (`purge_postmortems_for`); this is a deliberate one-shot extension, not a general-purpose delete.
- **Decision 55 compliance**: the dedupe/skip helpers are pattern-matched recovery (well-understood failure class), not LLM judgment. Permitted.
- **Friction patterns**: none surfaced from preflight.
- **Known gotcha (rec-360 reference)**: `_append_to_local_jsonl` in `ops_data_portal.py` does NOT have a `PYTEST_CURRENT_TEST` guard. New tests must mock at the `file_rec` / `update_rec` boundary so live JSONL is not appended during pytest.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`agent/fix-postmortem-bleed`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (Decisions 44, 51, 55)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO active (`aws sts get-caller-identity --profile company-aws-profile`) — required for VP steps 6, 7, 11, 12, 13.

## Ordered Execution Steps
1. **`scripts/ops_data_portal.py`** — add three pieces:
   1. `find_open_postmortem_for(failed_rec_id: str) -> Optional[dict]` — loads local JSONL, returns the first open record where `source == "executor-postmortem"` and the title contains `failed_rec_id`. Returns `None` if not found. Pure-function, no side effects.
   2. Modify `drain_pending()`: for each pending file whose `fields.get("source") == "executor-postmortem"`, extract the failed_rec_id from the title via regex `rec-\d+`; call `find_open_postmortem_for`; if a duplicate exists, **update** the existing record's `context` (append `"; attempt N+1 at <iso>"`) via `update_rec`, **delete** the pending file, and increment a `deduped` counter. Otherwise fall through to the existing path.
   3. `purge_postmortems_for(failed_rec_id: str, dry_run: bool = False) -> dict` — discovers (a) pending files matching the rec, (b) drained JSONL entries matching the rec, (c) the source rec itself. Returns counts. If `dry_run=False`: physically deletes pending files, calls `boto3.client('dynamodb').delete_item` for each drained postmortem in `ops_recommendations`, rewrites local JSONL via the **rename-create-delete pattern** (`.new` → swap → delete `.old`) to prevent Windows partial-write corruption, then calls `update_rec(failed_rec_id, {"status": "declined", "resolution": "<SCP block + cleanup note>"})`.
   4. CLI: add `--purge-postmortems-for REC_ID` with optional `--dry-run`, wired in `main()`.
2. **`scripts/executor/jsonl_store.py`** — modify `_create_postmortem_recommendation`:
   - Before constructing `postmortem_fields`, call `find_open_postmortem_for(failed_rec_id)` using a **deferred import** (`from scripts.ops_data_portal import find_open_postmortem_for  # noqa: PLC0415`) — same pattern as the existing `file_rec` import on line 274 to avoid circular deps.
   - If found: call `update_rec(existing["id"], {"context": existing["context"] + f"; attempt N+1 at {datetime.now(...).isoformat()}", "last_updated_timestamp": ...})`. Log "[POSTMORTEM] Deduped: updated existing %s for %s".
   - If not found: existing path (file_rec) — unchanged.
3. **`scripts/execute_recommendation.py`** — at the rec-selection site (after the existing `automatable` filter, before the rec is dispatched to plan-load):
   - Add `_is_poisoned_rec(rec_id: str) -> bool` helper that returns True iff `find_open_postmortem_for(rec_id)` returns a record AND `os.environ.get("ALLOW_POISONED_RECS","").lower() != "true"`.
   - Filter the candidate rec list with this helper. Log skipped recs at WARNING level once.
4. **`tests/test_ops_data_portal.py`** — add a new `TestPostmortemDedupe` class:
   - `test_find_open_postmortem_for_returns_match`: seeds a fake JSONL via `tmp_path` and `monkeypatch` of `RECS_JSONL`; asserts the helper finds an existing entry.
   - `test_find_open_postmortem_for_returns_none_when_declined`: confirms only `status=open` matches.
   - `test_drain_pending_dedupes_existing_postmortem`: pre-seeds an open postmortem in JSONL + a pending file for the same failed_rec_id; mocks `_next_id`; asserts `update_rec` called, `file_rec` (i.e. the new-allocation path) NOT called, pending file deleted.
   - `test_purge_postmortems_for_dry_run`: asserts no writes happen, returns expected counts.
   - `test_purge_postmortems_for_executes_full_cleanup`: mocks boto3 dynamodb client; asserts 27 delete_item calls with expected keys, JSONL rewrite called, update_rec called with status=declined.
5. **`tests/test_executor_jsonl_store.py`** — extend `TestCreatePostmortemRecommendation`:
   - `test_dedupes_when_open_postmortem_exists`: patches `find_open_postmortem_for` to return a fake record; asserts `update_rec` called with attempt-counter context; asserts `file_rec` NOT called.
   - `test_files_new_when_no_open_postmortem`: existing test path, kept as-is.
6. **Execute Verification Plan** — run each VP step. Loop until pass. If V3-equivalent steps (Athena queries) fail unrecoverably, stop and analyze root cause (Decision 55).
7. **Run cleanup CLI** (VP steps 6, 7) to clear the existing 27 duplicates and 14 stale pending files.
8. **Run `validate.py --quick`** (VP step 15). Must be green before commit.
9. **Report**: what was implemented, VP results table, count of cleaned-up entries, current rec-100 status, current open-postmortem count for rec-100 in Athena.

## Open Questions Resolved During Planning
- **Q1 (dedupe behaviour)**: option (b) — update existing postmortem with attempt counter. Confirmed.
- **Q2 (env override on selector skip)**: included as `ALLOW_POISONED_RECS=true`. Default is to skip. User did not push back; documented as proposed.
- **Q3 (cleanup scope)**: full physical removal of the 27 duplicates from JSONL + DynamoDB. Confirmed; user explicitly opted for hard removal over `status=declined` for this one-time cleanup.
