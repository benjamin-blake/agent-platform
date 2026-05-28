# Plan

## Intent
Eliminate all write-path bypasses for `ops_recommendations`, hard-delete the 2 hollow records that
block DQ graduation, and seal creation-time validation so the "patch-delete, hollow-record reappears"
cycle cannot repeat. This is a prerequisite for the executor telemetry work: the executor reads the
recommendation store on every run and any hollow record can corrupt plan generation.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-ops-rec-enforcement

## Phase
Phase 4 - Data Quality & Observability

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `config/data_quality/dq_tombstones.yaml` | Create | Git-tracked hard-delete manifest for rec-608 and rec-633 |
| `scripts/data_quality_runner.py` | Modify | Add tombstone-resurrection HARD_GATE check |
| `scripts/ops_data_portal.py` | Modify | Seal `file_rec()` with non-empty required-field validation |
| `scripts/executor/jsonl_store.py` | Modify | Fix `_create_postmortem_recommendation()` required fields; drop 8 Decision-56-deprecated Pydantic fields (rec-602) |
| `scripts/ops_writer.py` | Modify | Add backstop guard in `write("ops_recommendations", ...)` for 7 required non-empty fields |
| `scripts/sync_ops.py` | Modify | Add reject-and-log pass in `pull()` → `logs/debug/dq-sync-rejects.jsonl` |
| `scripts/run_scheduled_agent.py` | Modify | Replace `append_jsonl(_RECS_KEY, finding)` with `ops_data_portal.enqueue_findings()` |
| `scripts/s3_log_store.py` | Modify | Remove `"ops_recommendations"` entry from `_OPS_TABLE_ROUTING` |
| `scripts/backfill_ops_tables.py` | Delete | One-time migration complete; direct OpsWriter bypass |
| `tests/test_backfill_ops_tables.py` | Delete | Tests for deleted script |
| `scripts/migrate_dq_ops_recs.py` | Delete | One-time migration complete (PR #303); direct OpsWriter bypass |
| `tests/test_migrate_dq_ops_recs.py` | Delete | Tests for deleted script |
| `personal_scripts/_file_infra_recs.py` | Delete | Hardcoded IDs, writes directly to JSONL, completely bypasses portal |
| `scratch/verify_pipeline.py` | Delete | Scratch verification file; direct OpsWriter instantiation |
| `scripts/validate.py` | Modify | Expand portal-bypass linter regex to include `personal_scripts/` directory |
| `config/data_quality/ops.yaml` | Modify | Add `accepted_values` for `source`; add `created_timestamp <= last_updated_timestamp` expression check |

## Bundled Recommendations
- **rec-602**: Drop 8 Decision-56-deprecated fields from `Recommendation` Pydantic model in `executor/jsonl_store.py`
  (`date`, `execution_steps_attempted`, `execution_steps_total`, `failure_reason`, `failure_step`,
  `ingested_at`, `rn`, `trade_date`)

## Acceptance Criteria
- [ ] DQ runner reports 0 FAIL for all `ops_recommendations` not_null checks (title, source, effort, priority)
- [ ] DQ runner reports PASS on a new `created_timestamp <= last_updated_timestamp` expression check
- [ ] Hard-delete of rec-608 and rec-633 confirmed: neither ID appears in `ops_recommendations_current` Athena view
- [ ] `config/data_quality/dq_tombstones.yaml` committed with both IDs; DQ runner resurrection check emits HARD_GATE if they reappear
- [ ] `file_rec()` raises `ValueError` when called with any empty required field (title, source, effort, priority, file, context, acceptance)
- [ ] `_create_postmortem_recommendation()` always sets all 7 required fields; 8 deprecated fields removed from `Recommendation` model
- [ ] `scripts/run_scheduled_agent.py` uses `enqueue_findings()` — no `append_jsonl(".recommendations-log.jsonl", ...)` calls remain
- [ ] `_OPS_TABLE_ROUTING` in `s3_log_store.py` does NOT contain `ops_recommendations` key
- [ ] `backfill_ops_tables.py`, `migrate_dq_ops_recs.py`, `personal_scripts/_file_infra_recs.py`, `scratch/verify_pipeline.py` deleted
- [ ] `validate.py` portal-bypass linter catches direct writes in `personal_scripts/` (confirmed via linter run)
- [ ] `pytest` passes (no regressions from deletions or model changes)
- [ ] Lambda smoke test passes (`--smoke-test rec-curator`) confirming `enqueue_findings()` is active in deployed package

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | Confirm rec-608/633 still exist in Athena before deletion | `.venv/Scripts/python.exe -c "from scripts.ops_writer import OpsWriter; w=OpsWriter(); r=w._athena_query(\"SELECT id,title,source,effort,priority FROM trading_formulas_db.ops_recommendations_current WHERE id IN ('rec-608','rec-633')\"); print(r)"` | Two rows returned with empty fields | Already gone — skip hard delete step |
| 2 | pre-deploy | Hard delete rec-608 and rec-633 from Iceberg | `.venv/Scripts/python.exe -c "from scripts.ops_writer import OpsWriter; w=OpsWriter(); w._athena_execute(\"DELETE FROM trading_formulas_db.ops_recommendations WHERE id IN ('rec-608','rec-633')\")"` | No exception | Athena permission error — check IAM policy for DELETE on Iceberg |
| 3 | pre-deploy | Confirm hard delete took effect | `.venv/Scripts/python.exe -c "from scripts.ops_writer import OpsWriter; w=OpsWriter(); r=w._athena_query(\"SELECT COUNT(*) AS n FROM trading_formulas_db.ops_recommendations_current WHERE id IN ('rec-608','rec-633')\"); print(r)"` | `n = 0` | Rows still present — re-run DELETE, check table refresh |
| 4 | pre-deploy | Verify tombstone resurrection check triggers on synthetic test | `.venv/Scripts/python.exe -m scripts.data_quality_runner --table ops_recommendations --checks tombstone_resurrection 2>&1` | Check emits HARD_GATE for rec-608 or rec-633 if they exist; PASS if absent | HARD_GATE not emitted — inspect tombstones.yaml path and DQ runner loader |
| 5 | pre-deploy | Confirm `file_rec()` rejects empty required fields | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import file_rec; file_rec({'title':'','source':'test','effort':'S','priority':'High','file':'x.py','context':'c','acceptance':'a'})"` | `ValueError` raised | No error — check non-empty guard in `file_rec()` |
| 6 | pre-deploy | Confirm `file_rec()` accepts fully-populated rec | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import file_rec; print('ok')"` | No import error | Import error — check for syntax issues in portal |
| 7 | pre-deploy | Verify `ops_writer.py` backstop raises on empty title | `.venv/Scripts/python.exe -c "from scripts.ops_writer import OpsWriter; w=OpsWriter(); w.write('ops_recommendations', {'id':'test-999','title':'','source':'test','effort':'S','priority':'High','file':'x','context':'c','acceptance':'a','status':'open','automatable':False,'risk':'low','created_timestamp':'2026-05-08T00:00:00'})"` | `ValueError` raised | No error — check backstop guard in `ops_writer.py` `write()` |
| 8 | pre-deploy | Confirm `run_scheduled_agent.py` has no `append_jsonl` calls for recs key | `.venv/Scripts/python.exe -m scripts.validate --quick 2>&1 \| grep -i "portal.bypass"` | No portal-bypass violations reported | Violations found — re-check `run_scheduled_agent.py` fix and `validate.py` linter scope |
| 9 | pre-deploy | Confirm `s3_log_store._OPS_TABLE_ROUTING` has no ops_recommendations key | `.venv/Scripts/python.exe -c "from scripts.s3_log_store import _OPS_TABLE_ROUTING; assert 'ops_recommendations' not in _OPS_TABLE_ROUTING, _OPS_TABLE_ROUTING; print('clean')"` | `clean` | AssertionError — routing entry still present |
| 10 | pre-deploy | Verify Pydantic model ignores deprecated fields from legacy Iceberg rows | `.venv/Scripts/python.exe -c "from scripts.executor.jsonl_store import Recommendation; r=Recommendation.model_validate({'id':'t','title':'t','source':'s','effort':'S','priority':'High','status':'open','automatable':False,'risk':'low','created_timestamp':'2026-05-08T00:00:00','file':'f','context':'c','acceptance':'a','date':'2026-05-08','ingested_at':'2026-05-08','rn':1,'trade_date':'2026-05-08'}); print('compat ok')"` | `compat ok` | `ValidationError` — model has `extra='forbid'`; strip deprecated keys in `_coerce_ops_rec_row()` before calling `model_validate()` |
| 11 | pre-deploy | Run full unit test suite | `.venv/Scripts/python.exe -m pytest tests/ -x -q 2>&1 \| tail -20` | All tests pass; no `test_backfill_ops_tables` or `test_migrate_dq_ops_recs` entries | Failures — investigate; do NOT skip |
| 12 | pre-deploy | Run validate --quick for portal bypass and schema checks | `.venv/Scripts/python.exe -m scripts.validate --quick 2>&1 \| tail -30` | No FAIL lines | FAIL lines — fix before proceeding to V3 |
| 13 | post-deploy | Sync local JSONL cache from Athena post-delete | `.venv/Scripts/python.exe -m scripts.sync_ops pull 2>&1` | Sync completes; rec-608/633 absent from local cache; no rejects-log entry for valid recs | Rejects for valid recs — inspect `dq-sync-rejects.jsonl` |
| 14 | post-deploy | Run DQ runner against live Athena and confirm 4 checks now PASS | `.venv/Scripts/python.exe -m scripts.data_quality_runner 2>&1 \| grep -A2 "ops_recommendations"` | title, source, effort, priority not_null checks all PASS (previously FAIL) | Still FAIL — check that hard delete propagated through Iceberg compaction; may need to trigger compaction |
| 15 | post-deploy | Confirm DQ verdict improves | `.venv/Scripts/python.exe -c "import json,pathlib; d=json.loads(pathlib.Path('logs/debug/dq-latest.json').read_text()); print(d.get('verdict'), d.get('fail_count'), 'fails')"` | verdict PASS or fewer than 64 failures (previously 64F); ops_recommendations 0 FAIL | Still FAIL — check `dq-latest.json` for specific table failures |
| 16 | post-deploy | Lambda smoke test -- verify rec-curator runs through new `enqueue_findings()` path | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test rec-curator 2>&1 \| tail -15` | Smoke test exits 0; no errors from `enqueue_findings` | Non-zero exit or enqueue error -- check deployed Lambda package version matches local changes |

## Constraints
- Iceberg DELETE requires the `agent-platform-production` Athena workgroup and valid AWS SSO session (Decision 57)
- Single Portal Invariant: all ops_recommendations writes go through `ops_data_portal.py` (no direct OpsWriter instantiation for this table from application code)
- SCD2 append-only: hard delete is the only mechanism to remove rows; compact after delete to avoid scan amplification
- No rescue agents or workaround loops (Decision 55)
- `validate.py` is the single source of truth for CI checks; any new linter rule must land there first
- rec-602 (Pydantic field removal) must be backward-compatible with existing Iceberg rows: Pydantic model changes affect writes only, not Athena reads

## Context
- Root cause of 4 failing DQ checks: rec-608 and rec-633 have empty title/source/effort/priority; both are status=closed with valid `last_updated_timestamp >= 2026-05-01`, pushing them past the `exclude_before` temporal gate
- `run_scheduled_agent.py:247` uses `append_jsonl(".recommendations-log.jsonl", finding)` which triggers OpsWriter write-through via `s3_log_store._OPS_TABLE_ROUTING` — a hidden bypass that has been writing zero-validation records to Iceberg since the routing table was added
- `_create_postmortem_recommendation()` in `jsonl_store.py` is the only remaining legitimate non-portal write path for executor-created recs; it must be fixed to set all required fields, not rely on defaults
- Decision 56: the 8 deprecated fields were removed from the Iceberg schema but still exist in the Pydantic model, causing OpsWriter to emit columns that Iceberg silently ignores (harmless but confusing)
- Decision 61: scheduled-agent findings flow through `ops_recommendations` via `source` field using `enqueue_findings()`, NOT `append_jsonl`
- `sync_ops.pull()` already calls `_coerce_ops_rec_row()` for type coercion (PR #301); the reject-and-log pass sits after coercion, before cache write
- The tombstone YAML pattern is preferable to a new Iceberg table: cheaper, git-diffable, and survives Athena outages

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (especially Decision 56, 57, 61)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO session valid (needed for VP steps 1-3 and 12-14)

## Ordered Execution Steps
1. **Read** `docs/PROJECT_CONTEXT.md`, `docs/DECISIONS.md` — confirm Decision 56 deprecated fields and Decision 61 enqueue_findings path before touching code
2. **Create** `config/data_quality/dq_tombstones.yaml` — YAML list of hard-deleted record IDs with metadata (id, table, deleted_at, reason, deleted_by). Initial entries: rec-608 and rec-633.
3. **Modify** `scripts/data_quality_runner.py` — load `dq_tombstones.yaml`; after querying `ops_recommendations_current`, cross-reference tombstoned IDs; emit `HARD_GATE` result for any match with message "resurrected tombstoned record"
4. **Modify** `scripts/ops_data_portal.py` `file_rec()` — define `_REQUIRED_NONEMPTY = ["title", "source", "effort", "priority", "file", "context", "acceptance"]`; add guard at entry to `file_rec()` that raises `ValueError` for any field that is absent or strips to empty string
5. **Modify** `scripts/executor/jsonl_store.py` — (a) fix `_create_postmortem_recommendation()` to always populate all 7 required non-empty fields with sensible fallbacks; (b) remove the 8 Decision-56-deprecated fields from the `Recommendation` Pydantic model (rec-602)
6. **Modify** `scripts/ops_writer.py` `write()` — add backstop guard: if `table_name == "ops_recommendations"`, validate that `["title", "source", "effort", "priority", "file", "context", "acceptance"]` are present and non-empty; raise `ValueError` if not (last-resort defence, does not replace portal validation)
7. **Modify** `scripts/sync_ops.py` `pull()` — after `_coerce_ops_rec_row()` call, validate the 7 required non-empty fields; for rows that fail, write the row + error to `logs/debug/dq-sync-rejects.jsonl` and skip from the local cache write; log count of rejected rows
8. **Modify** `scripts/run_scheduled_agent.py` — replace `append_jsonl(_RECS_KEY, finding)` at line ~247 with `from scripts.ops_data_portal import enqueue_findings; enqueue_findings(finding_path_or_dict)` — align with Decision 61; remove `_RECS_KEY` constant if no longer used
9. **Modify** `scripts/s3_log_store.py` — remove `"ops_recommendations": "ops_recommendations"` (or similar) entry from `_OPS_TABLE_ROUTING` dict; this closes the hidden append_jsonl bypass
10. **Delete** `scripts/backfill_ops_tables.py` and `tests/test_backfill_ops_tables.py`
11. **Delete** `scripts/migrate_dq_ops_recs.py` and `tests/test_migrate_dq_ops_recs.py`
12. **Delete** `personal_scripts/_file_infra_recs.py`
13. **Delete** `scratch/verify_pipeline.py`
14. **Modify** `scripts/validate.py` — expand portal-bypass linter `_BYPASS_PATTERNS` to include `personal_scripts/` in its search scope (currently likely limited to `scripts/` and `src/`)
15. **Modify** `config/data_quality/ops.yaml` — for `ops_recommendations.source`: add `accepted_values` test (list the known valid source slugs from `run_scheduled_agent.py`); add `created_timestamp <= last_updated_timestamp` expression check under the table-level `checks:` block
16. **Run** VP steps 1-12 (pre-deploy) — confirm deletion candidates exist, confirm Athena DELETE succeeds (VP 2 IS the hard delete), verify guards, run tests and validate; Pydantic compat check (VP 10) must pass before Lambda deploy
17. **Build and deploy Lambda package** — `.venv/Scripts/python.exe -m scripts.build_lambda --deploy`; this activates `run_scheduled_agent.py`'s new `enqueue_findings()` path in the deployed function
18. **Run** VP steps 13-16 (post-deploy) — sync local cache, run DQ runner, confirm 4 previously-failing checks now PASS, run Lambda smoke test
19. **Commit** all changes with message `feat(dq-ops-rec-enforcement): seal write path, hard-delete hollow recs, graduate 4 DQ checks`
20. **Report**: which checks transitioned FAIL→PASS, which files were deleted, confirmation that tombstone check is active, the new DQ verdict, and smoke test result
