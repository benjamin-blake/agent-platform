# Plan

## Intent

Correct invalid `automatable` and `risk` values in `ops_recommendations` Iceberg data,
graduate the three corresponding DQ checks from `enforced: false` to `enforced: true`,
and remove the `.gitignore` exception that causes outbox files to surface as uncommitted
changes in every session. Advances the ops data quality enforcement arc (Phase 1 complete,
Phase 2 schema backfill in progress).

## Plan Type

IMPLEMENTATION

## Verification Tier

V3 (Athena integration -- migration writes to Iceberg; DQ runner verifies against
`ops_recommendations_current` view)

## Branch

agent/dq-ops-rec-nulls

## Phase

Phase 1: Core Infrastructure (complete) / Phase Platform (parallel, ongoing)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `config/executor_capabilities.yaml` | Create | Machine-readable executor boundary patterns and maturity ceiling (Decision 44). Canonical source of truth; `validate.py` and migration script both read from here instead of defining the list inline. |
| `scripts/migrate_dq_ops_recs.py` | Create | Backfill 44 null `automatable` records and normalise ~38 invalid `risk` values via OpsWriter. Dry-run safe, idempotent. |
| `config/data_quality/ops.yaml` | Modify | Graduate `automatable [not_null]`, `risk [not_null]`, `risk [accepted_values]` to `enforced: true`. |
| `.gitignore` | Modify | Remove the `!logs/.ops-outbox/ops_recommendations_pending/` exception (Option A -- outbox files are ephemeral local buffers, not source artifacts). |
| `tests/test_migrate_dq_ops_recs.py` | Create | Unit tests for correction logic (boundary check, risk normalisation). OpsWriter mocked. |
| `scripts/validate.py` | Modify | Replace inline `_EXECUTOR_BOUNDARY_PATTERNS` tuple with a loader that reads `config/executor_capabilities.yaml` -- single source of truth, Decision 44 constraint. |

## Infrastructure Dependencies

| File | Packaged in Lambda? | Lambda reads it? | Deploy required? |
|------|--------------------|--------------------|-----------------|
| `config/data_quality/ops.yaml` | Yes (data-pipeline.zip, ops-compaction.zip via `build_lambda.py:71,154`) | No -- grep of `src/data/handlers/` and `scripts/execute_recommendation.py` returns zero references | No |
| `config/executor_capabilities.yaml` | Yes (same bundles, `config/` is copied wholesale) | No -- new file; no Lambda handler references it | No |

Lambda rebuild is **not required** for this plan. Evidence: `grep -rn "executor_capabilities\|data_quality/ops\|data_quality_runner" src/data/handlers/ scripts/execute_recommendation.py` returns no matches. If that changes (e.g., a Lambda is later wired to read these files), the pre-deploy checklist must be updated to include build and smoke-test steps per Decision 47.

## Bundled Recommendations

- **rec-611** (High/S): Fix `automatable=true` on boundary-file recs rec-496, rec-532,
  rec-569 (violate Decision 44). The migration script will correct these as a natural
  byproduct of running the boundary check formula over all open recs.

## Acceptance Criteria

- [ ] `automatable [not_null]` reports PASS (enforced) in DQ runner output
- [ ] `risk [not_null]` reports PASS (enforced) in DQ runner output
- [ ] `risk [accepted_values]` reports PASS (enforced) in DQ runner output
- [ ] DQ runner overall verdict remains PASS (no regressions in other checks)
- [ ] rec-496, rec-532, rec-569 have `automatable=False` in the local cache after sync
- [ ] `.gitignore` no longer contains `!logs/.ops-outbox/ops_recommendations_pending/`
- [ ] `python -m scripts.validate --quick` exits 0

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | **STOP-GATE: verify `_current` view deduplication (rec-605)** | `.venv/Scripts/python.exe -c "import scripts.athena_client as a; r=a.query('SELECT COUNT(*) total, COUNT(DISTINCT id) distinct_ids FROM ops_recommendations_current', profile='company-aws-profile'); print(r)"` | `total` equals `distinct_ids` (or within 5% -- minor SCD2 lag acceptable); if `total` >> `distinct_ids` (e.g. 935 vs 630), the `_rn` deduplication bug is active. **Do not proceed past this step until it passes.** | Run `terraform apply` targeting the `ops_recommendations_current` view resource in `terraform/iceberg_tables.tf`, then re-run this check |
| 2 | pre-deploy | Unit tests for correction logic | `.venv/Scripts/python.exe -m pytest tests/test_migrate_dq_ops_recs.py -v` | All tests green, 0 failures | Fix failing test logic before proceeding |
| 3 | pre-deploy | Dry-run shows expected corrections | `.venv/Scripts/python.exe -m scripts.migrate_dq_ops_recs --dry-run 2>&1` | Output lists ~44 `automatable` corrections and ~38 `risk` normalizations; no OpsWriter writes occur; exit 0 | If count differs significantly from expected, recheck VP step 1 (view may still be returning duplicates) |
| 4 | post-deploy | No null/invalid `automatable` in current view | `.venv/Scripts/python.exe -c "import scripts.athena_client as a; r=a.query('SELECT COUNT(*) n FROM ops_recommendations_current WHERE automatable IS NULL', profile='company-aws-profile'); print(r)"` | `n = 0` | Re-run migration; check OpsWriter wrote to correct table |
| 5 | post-deploy | No invalid `risk` in current view | `.venv/Scripts/python.exe -c "import scripts.athena_client as a; r=a.query(\"SELECT DISTINCT risk FROM ops_recommendations_current WHERE risk NOT IN ('low','medium','high') OR risk IS NULL\", profile='company-aws-profile'); print(r)"` | Empty result set | Re-run migration; check normalisation map |
| 6 | post-deploy | DQ runner PASS on all three graduated checks | `.venv/Scripts/python.exe -m scripts.data_quality_runner 2>&1 \| grep -E "automatable\|risk"` | Three lines each showing `PASS` | If still FAIL: check Athena row count vs DQ runner query; may need `sync_ops pull` first |
| 7 | post-deploy | rec-611 resolved -- boundary recs corrected | `.venv/Scripts/python.exe -m scripts.sync_ops pull && .venv/Scripts/python.exe -c "import json; by_id={r['id']:r for ln in open('logs/.recommendations-log.jsonl',encoding='utf-8',errors='replace') for r in [json.loads(ln)]}; bad=[i for i in ['rec-496','rec-532','rec-569'] if by_id.get(i,{}).get('automatable') is True]; print('OK' if not bad else bad)"` | `OK` | Investigate why OpsWriter write did not persist for these IDs |
| 8 | post-deploy | validate exits 0 | `.venv/Scripts/python.exe -m scripts.validate --quick` | Exit 0 | Fix any regressions before committing |
| 9 | post-deploy | validate.py boundary loader works (no import regression) | `.venv/Scripts/python.exe -c "from scripts.validate import _EXECUTOR_BOUNDARY_PATTERNS; assert len(_EXECUTOR_BOUNDARY_PATTERNS) > 5; print('OK', len(_EXECUTOR_BOUNDARY_PATTERNS), 'patterns')"` | `OK N patterns` where N matches count from `config/executor_capabilities.yaml` | Check YAML parse; check file path resolution in validate.py loader |
| 10 | post-deploy | Lambda bundle contains updated config files (Decision 47 -- replaces smoke-test; scheduled agents disabled since May 2026 and return `{"status":"disabled"}`) | `unzip -l dist/data-pipeline.zip \| grep -E "config/executor_capabilities.yaml\|config/data_quality/ops.yaml"` | Both file paths appear in the zip listing | Check `build_lambda --deploy` completed without error; re-run if listing is empty |

## Constraints

- **rec-605 is a hard prerequisite (STOP if unresolved):** The `ops_recommendations_current`
  Athena view has an ambiguous `_rn` column bug that breaks SCD Type 2 deduplication,
  causing the view to return all historical row versions (~935 rows) rather than one
  current row per ID (~630). The migration script querying a broken view would operate
  on stale/duplicate rows, producing incorrect corrections. The terraform fix is already
  in `terraform/iceberg_tables.tf` (line 1025, `AS row_num`); it just needs
  `terraform apply`. VP step 1 verifies the view is deduplicated before proceeding.
  If VP step 1 fails, apply terraform (`terraform apply -target=...iceberg_tables`) and
  re-run the check before continuing. Do not proceed past VP step 1 until it passes.
- **Single Portal Invariant:** All writes to `ops_recommendations` go through
  `OpsWriter.write()`. No direct `Edit`/`Write` to `.recommendations-log.jsonl`.
- **`validate.py` is not a boundary file:** Decision 44 defines the boundary as executor
  machinery -- `execute_recommendation.py`, its submodules, prompts, and executor tests.
  `validate.py` is a CI/development tool that agents do not invoke autonomously; it is
  neither an executor submodule nor a prompt. It must NOT be added to `boundary_patterns`.
- **No temporal gate yet:** `exclude_before` is not implemented in the DQ runner
  (per `DQ_REMEDIATION_METHODOLOGY.md`). Graduation without a temporal gate requires
  the backfill to cover ALL null/invalid records -- the migration script must query
  Athena `ops_recommendations_current` (not just the stale local JSONL) to be certain.
- **automatable formula (backfill simplification):** The approved formula is
  `automatable = (file NOT IN boundary) AND (risk_score <= ceiling)`. For the backfill,
  the boundary check is applied exactly; the risk ceiling check defaults to True for
  historical records where radon CC and coverage data are unavailable. This is safe
  because the boundary is the hard constraint (Decision 44); the ceiling is a soft
  operational gate that will be enforced at write time once ops_data_portal is updated
  (separate follow-on work, not in this plan).
- **Outbox in flux:** A parallel agent is resolving outbox/DynamoDB environment variable
  bugs. OpsWriter.write() uses the stable write path. If OpsWriter emits to outbox due
  to SSO gaps during the migration run, drain via `sync_ops pull` before VP step 3.
- **Lambda smoke-test replaced:** Scheduled Lambda agents were disabled in May 2026
  (migration to Claude Code scheduled agents) and return `{"status": "disabled"}`.
  The conventional `--smoke-test doc-freshness` command cannot exit 0 without re-enabling
  agents (a runbook-level operation outside this plan's scope). VP step 9 uses zip
  artifact verification instead -- this directly proves the changed config files are
  present in the deployed bundle, which is the property Decision 47 actually requires.
- No rescue agents or workaround loops (Decision 55).
- Do not add checks or changes outside the three `automatable`/`risk` fields.

## Context

- Decision 44: executor boundary files must always have `automatable: false`. Boundary
  patterns defined in `validate.py:_EXECUTOR_BOUNDARY_PATTERNS` (lines 41-61) are the
  canonical set; this plan moves them to `config/executor_capabilities.yaml`.
- Decision manifest (`config/data_quality/decisions/ops_recommendations.yaml`): both
  `automatable` and `risk` have `human_decision: approved` as of 2026-05-07.
- DQ methodology (`docs/dq/DQ_REMEDIATION_METHODOLOGY.md`): Class C = write path gap
  (automatable); Class D = true corruption (risk). Both require data correction before
  enforcement.
- `ops_recommendations` is SCD Type 2 (append-only). Corrections write a new row version
  via OpsWriter -- the original null/invalid version remains in history. The `_current`
  view resolves to the newest version per `id`.
- Session telemetry UUID: `41beec93-e234-4560-9997-fa776e18bfef`

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main` (`agent/dq-ops-rec-nulls`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` Decision 44 read
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` read (both fields `approved`)
- [ ] `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

0. **Run VP step 1 (rec-605 stop-gate)** -- Before writing any code, verify the
   `ops_recommendations_current` view is correctly deduplicated. If `total != distinct_ids`,
   run `terraform apply` targeting the view resource in `terraform/iceberg_tables.tf`
   (the fix -- renaming `AS _rn` to `AS row_num` -- is already in the DDL at line 1025),
   then re-run until the check passes. This is a read-only prerequisite that costs
   nothing to check and avoids running a migration on corrupted Athena input.

1. **Create `config/executor_capabilities.yaml`** -- Extract the boundary pattern list
   verbatim from `validate.py:_EXECUTOR_BOUNDARY_PATTERNS` (lines 41-61). Add
   `maturity_ceiling: 1.0` (current ceiling; raise history starts empty). This file is
   the canonical source of truth going forward. Format:
   ```yaml
   boundary_patterns:
     - execute_recommendation.py
     - scripts/executor/
     - ...
   maturity_ceiling: 1.0
   ceiling_history: []
   ```

2. **Modify `scripts/validate.py`** -- Replace the inline `_EXECUTOR_BOUNDARY_PATTERNS`
   tuple with a loader: `yaml.safe_load(open('config/executor_capabilities.yaml'))['boundary_patterns']`.
   Wrap in a module-level `_load_boundary_patterns()` call. Existing behaviour must be
   identical -- the patterns are unchanged, only their source moves.

3. **Create `scripts/migrate_dq_ops_recs.py`** -- Implement the backfill script:
   - `parse_args()`: `--dry-run` flag, `--profile` (default `company-aws-profile`)
   - `load_boundary_patterns()`: reads `config/executor_capabilities.yaml`
   - `query_target_records()`: queries `ops_recommendations_current` via `athena_client`
     for records where `automatable IS NULL` OR `risk NOT IN ('low','medium','high')` OR
     `risk IS NULL`. Returns list of dicts with `id`, `file`, `effort`, `automatable`,
     `risk`, and all other required fields.
   - `correct_automatable(rec, boundary_patterns)`: returns `False` if any boundary
     pattern is a substring of `rec['file']`; else `True`.
   - `correct_risk(rec)`: normalises to lowercase if already a valid case variant
     (`Low`→`low`, `Medium`→`medium`, `High`→`high`); maps `unclassified`, `''`, and
     any value not containing `/` or `.` to `'low'`; maps anything else (freetext with
     spaces) to `'low'`.
   - `run(dry_run, profile)`: for each target record, apply corrections, call
     `OpsWriter.write()` (or skip if dry-run), print a summary line per record.
   - `main()`: orchestrator. Print totals. Exit 0.

4. **Create `tests/test_migrate_dq_ops_recs.py`** -- Unit tests:
   - `test_correct_automatable_boundary_file`: file matching boundary pattern → `False`
   - `test_correct_automatable_non_boundary`: non-boundary file → `True`
   - `test_correct_risk_wrong_case`: `'Low'`→`'low'`, `'High'`→`'high'`
   - `test_correct_risk_unclassified`: `'unclassified'`→`'low'`
   - `test_correct_risk_freetext`: description-length string → `'low'`
   - `test_correct_risk_empty`: `''`→`'low'`
   - `test_correct_risk_valid_unchanged`: `'medium'` → `'medium'` (idempotent)

5. **Run VP step 1**: `pytest tests/test_migrate_dq_ops_recs.py -v`. Fix any failures.

6. **Run VP step 2** (dry-run): `.venv/Scripts/python.exe -m scripts.migrate_dq_ops_recs --dry-run`.
   Confirm output shows ~44 automatable corrections and ~38 risk normalizations.
   Review the specific record IDs listed for any surprises before proceeding.

7. **Run migration live**: `.venv/Scripts/python.exe -m scripts.migrate_dq_ops_recs`.
   If OpsWriter emits outbox warnings (SSO gap), run `sync_ops pull` to drain before
   running VP steps 3-4.

8. **Modify `config/data_quality/ops.yaml`** -- For the three failing checks, flip
   `enforced: true`. Also ensure `status [not_null]` remains `enforced: true` (graduated
   in previous session -- do not regress). Do not touch any other field.

9. **Modify `.gitignore`** -- Remove these two lines:
   ```
   !logs/.ops-outbox/ops_recommendations_pending/
   !logs/.ops-outbox/ops_recommendations_pending/*.json
   ```
   The parent `logs/.ops-outbox/**` entry already gitignores the directory.

10. **Rebuild and deploy Lambda** -- `config/` is packaged wholesale into `data-pipeline.zip`
    and `ops-compaction.zip` (Decision 47 mandatory step):
    ```
    .venv/Scripts/python.exe -m scripts.build_lambda --deploy
    ```
    This ensures the deployed Lambda bundles include `config/executor_capabilities.yaml`
    and the updated `config/data_quality/ops.yaml`, preventing config drift for any future
    Lambda handler that may read from `config/`.

11. **Execute Verification Plan** (VP steps 4-10). Loop on any failure until all pass.

12. **Report**: what was migrated, DQ verdicts before/after for the three checks,
    rec-611 resolution status.
