# Plan

## Intent

Implement `exclude_before` temporal gating in the DQ runner and use it to graduate the
`ops_recommendations` bootstrap-artifact fields (id, title, source, effort, priority) to
`enforced: true`. Simultaneously clean up three Phase 3 annotation residuals: the stale
`date` column check (column dropped in Decision 56), the `effort.accepted_values`
enforcement anomaly (set to `enforced: true` by Phase 3 when DQ showed PASS, but
FAIL in the Phase 4 investigation run), and the `source.accepted_values` list (validation
moves to write-time per the Phase 4 decisions).

## Plan Type

IMPLEMENTATION

## Verification Tier

V3

## Branch

agent/dq-bootstrap-temporal-gate

## Phase

Phase 1: Core Infrastructure (complete) -- this plan is Phase 4 DQ arc work.
See `docs/INTENT-dq-enforcement.md` for arc phase structure.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-dq-enforcement.md` | Modify | Phase 3 -> COMPLETE (plan + PR); Phase 4 -> IN_PROGRESS |
| `scripts/data_quality_runner.py` | Modify | Add `exclude_before: str | None = None` to `Check`; update all loader branches and SQL generation to apply temporal filter |
| `tests/test_data_quality_runner.py` | Modify | Tests for `exclude_before`: dataclass default, loader read, SQL injection per check type, row_count/recency do not inject |
| `config/data_quality/ops.yaml` | Modify | Wave 1 cleanup (remove `date` block, fix `effort.accepted_values` anomaly, drop `source.accepted_values`); Wave 2 annotation (add `exclude_before: '2026-05-01'` to bootstrap checks, graduate PASS verdicts) |

## Bundled Recommendations

None. Open recs explicitly out of scope for this session.

## Infrastructure Dependencies

`config/data_quality/ops.yaml` is packaged into the data-pipeline Lambda zip via
`scripts/build_lambda.py:71` (`shutil.copytree(ROOT / "config", app_dir / "config")`).
Changes to this file require a Lambda rebuild. The Lambda scheduled agents are currently
disabled (CLAUDE.md runbook, May 2026 migration), so full deploy and smoke-test are
conditional on re-enablement. The build step must still run pre-merge to verify packaging
integrity; deploy runs post-merge when Lambda is re-enabled.

| Resource | Change | Timing |
|----------|--------|--------|
| `data-pipeline.zip` (Lambda package) | Rebuild to include updated `config/data_quality/ops.yaml` | [pre-deploy]: build only; [post-deploy]: deploy when Lambda re-enabled per CLAUDE.md runbook |

## Acceptance Criteria

- [ ] `docs/INTENT-dq-enforcement.md` Phase 3 row shows COMPLETE / `PLAN-dq-ratchet-phase-3.md` / #296; Phase 4 row shows IN_PROGRESS
- [ ] `date` column block removed from `ops_recommendations` in `ops.yaml`; DQ dry-run returns no ERROR for that check
- [ ] `effort.accepted_values` is `enforced: false` with inline comment explaining the Phase 3 annotation anomaly
- [ ] `source.accepted_values` block removed from `ops.yaml`
- [ ] `Check` dataclass has `exclude_before: str | None = None` field
- [ ] All `_compile_column_test` dict-form branches (`not_null`, `unique`, `accepted_values`, `relationships`, `expression`) inject `AND created_timestamp >= DATE('{exclude_before}')` into SQL when `exclude_before` is set; bare-string paths default to `None`
- [ ] `load_checks` reads `exclude_before` from dict-form column tests and passes to `Check`; table-level checks (`row_count`, `recency`) read but do not inject (aggregate SQL unchanged)
- [ ] `pytest tests/test_data_quality_runner.py -x -q` passes
- [ ] All 6 bootstrap checks in `ops.yaml` annotated with `exclude_before: '2026-05-01'`; those that PASS in the live DQ run graduated to `enforced: true`
- [ ] `grep -n "enforced: false" config/data_quality/ops.yaml | grep -v "#"` returns zero lines
- [ ] Lambda build completes without error

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit tests for `exclude_before` pass | `.venv/Scripts/python.exe -m pytest tests/test_data_quality_runner.py -x -q 2>&1 \| tail -5` | All tests pass including new `exclude_before` tests | Dataclass missing field; SQL branch not injecting temporal clause; loader not reading param from YAML |
| 2 | [pre-deploy] | Dry-run with cleaned ops.yaml produces no loader error | `.venv/Scripts/python.exe -m scripts.data_quality_runner --dry-run --file config/data_quality/ops.yaml 2>&1 \| head -10` | Completes without error; check count is 14 (was 16: -2 for removed `date` and `source.accepted_values`) | Loader error parsing `exclude_before` param; YAML form not handled |
| 3 | [pre-deploy] | Live DQ run with temporal gates produces per-check verdicts | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml 2>&1 \| tail -20` | Run completes; `dq-latest.json` updated; no ERROR for `date` column | Athena SSO expired; bootstrap checks still FAIL with temporal gate (data condition -- see Step 6 notes) |
| 4 | [pre-deploy] | Bootstrap checks PASS with temporal gate | `.venv/Scripts/python.exe -c "import json; d=json.load(open('logs/debug/dq-latest.json')); [print(f\"{c['column']}.{c['test']}: {c['verdict']}\") for c in d['checks'] if c['table']=='ops_recommendations']"` | `id.not_null`, `title.not_null`, `source.not_null`, `effort.not_null`, `effort.accepted_values`, `priority.not_null` all show `PASS`; `priority.accepted_values` and `created_timestamp.not_null` show `PASS` | Any bootstrap check shows FAIL: post-anchor cohort has a real data problem -- convert to Category B, add inline comment, do not graduate |
| 5 | [pre-deploy] | Graduation guard accepts all `enforced` flips | `.venv/Scripts/python.exe -m scripts.validate --quick 2>&1 \| grep -A5 "graduation guard"` | `No enforced graduation violations` | A check was flipped to `enforced: true` but its verdict in `dq-latest.json` is FAIL or ERROR -- revert that flip |
| 6 | [pre-deploy] | No unannotated `enforced: false` in `ops.yaml` | `grep -n "enforced: false" config/data_quality/ops.yaml \| grep -v "#"` | Zero lines | Add inline `# reason` comment on the same line as any bare `enforced: false` |
| 7 | [pre-deploy] | Lambda package builds without error | `.venv/Scripts/python.exe -m scripts.build_lambda 2>&1 \| tail -5` | Build completes; `lambda-packages/data-pipeline.zip` written | Build error in `config/data_quality/` -- verify YAML is valid; re-run DQ dry-run |
| 8 | [post-deploy] | Lambda deploy when re-enabled | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy --profile company-aws-profile 2>&1 \| tail -5` | Deploy succeeds; Lambda function updated with new `ops.yaml` | Only required when Lambda scheduled agents are re-enabled per CLAUDE.md runbook |

## Constraints

- `exclude_before` always filters on `created_timestamp`. Other tables that use a different
  creation timestamp column will need a `exclude_before_column` extension in a future plan.
  For Phase 4 (`ops_recommendations`), `created_timestamp` is the correct column.
- `NULL >= DATE(...)` evaluates to NULL in Athena (not TRUE), so records with null
  `created_timestamp` are excluded from temporally-gated checks. This is correct behavior
  for the 23 pre-migration records with null `created_timestamp`.
- Never flip `enforced: false -> true` for a check that is not PASS in `dq-latest.json`.
  The graduation guard will block the merge, but verify manually as a pre-commit check.
- `source.accepted_values` is `severity: warn` (not `severity: error`) -- removing it does
  not change the enforced gate, only removes the advisory signal. The write-time source
  registry is the replacement; see `docs/PROJECT_CONTEXT.md` Data Quality section.
- Only `ops_recommendations` bootstrap checks get `exclude_before` in this plan.
  Telemetry table decisions have not been made; do not annotate `telemetry.yaml`.
- No rescue agents or workaround loops (Decision 55).

## Context

- Phase 3 (PR #296, 2026-05-06): deployed `enforced` ratchet field in runner, graduation
  guard in `validate.py`, YAML annotation of both YAML files, Decision 62. INTENT still
  shows Phase 3 as NOT_STARTED -- this plan corrects that housekeeping gap.
- `effort.accepted_values` anomaly: Phase 3 agent ran DQ where the check showed PASS
  (bootstrap empty-string records possibly not in `_current` view at that exact moment).
  Phase 4 investigation run 13 minutes later showed FAIL. Currently `enforced: true` in
  ops.yaml despite being FAIL -- this blocks any merge touching DQ-covered paths.
- `source.accepted_values` has `severity: warn`; its accepted_values list is missing 11+
  active source identifiers. Per Phase 4 decision: drop the DQ check, replace with
  write-time validation against `config/data_quality/source_registry.yaml` (separate plan).
- Graduation guard in `validate.py:1190` matches checks by `(table, column, test)` tuple.
  `exclude_before` is transparent to the guard -- the guard sees the verdict from the
  temporally-filtered query, not the filter itself. No changes to `validate.py` needed.
- Bootstrap anchor for `ops_recommendations`: `2026-05-01` (from decision manifest
  `config/data_quality/decisions/ops_recommendations.yaml`, field `bootstrap_anchor`).
- After this plan: `automatable.not_null`, `risk.*`, `status.*` remain `enforced: false`
  (need write-path fixes or data corrections -- separate sessions per Phase 4 protocol).
- The portal hardening work stream (Pydantic write-path enforcement, source registry,
  `executor_capabilities.yaml`) is a separate implementation session.

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] `docs/INTENT-dq-enforcement.md` read in full
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` read
- [ ] All Scope files located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Update `docs/INTENT-dq-enforcement.md`**
   - Phase Overview table: Phase 3 row -> `COMPLETE` / `PLAN-dq-ratchet-phase-3.md` / `#296`;
     Phase 4 row -> `IN_PROGRESS`.
   - Phase 3 section body: `Status: NOT_STARTED` -> `Status: COMPLETE`; fill in Plan and PR fields.
   - Phase 4 section body: `Status: NOT_STARTED` -> `Status: IN_PROGRESS`.
   - Update `last_updated` to current date.

2. **Modify `scripts/data_quality_runner.py`** (Wave 1 -- Python only, no YAML dependency)
   - Add `exclude_before: str | None = None` to `Check` dataclass after the `enforced` field.
   - In `load_checks` table-level branches (`row_count`, `recency`): read
     `rc.get("exclude_before")` / `rec.get("exclude_before")` and pass to `Check(...)`.
     Do NOT inject into the SQL; aggregate checks are not temporally gated.
   - In `_compile_column_test`, for all dict-form branches: add
     `exclude_before = params.get("exclude_before") if isinstance(params, dict) else None`
     and pass to `Check(...)`. Inject the temporal clause into SQL as follows:
     - `not_null`: append `AND created_timestamp >= DATE('{eb}')` after `IS NULL`
     - `unique`: add `WHERE created_timestamp >= DATE('{eb}') ` before `GROUP BY` in inner query
     - `accepted_values`: append `AND created_timestamp >= DATE('{eb}')` after the NOT IN clause
     - `relationships`: append `AND child.created_timestamp >= DATE('{eb}')` after the final
       `parent.{to_column} IS NULL` condition
     - `expression`: append `AND created_timestamp >= DATE('{eb}')` after `WHERE NOT ({expr})`
   - Bare-string `not_null` / `unique` paths: `exclude_before` is always `None` (no params dict).
   - Commit this as a standalone Wave 1 commit before touching YAML.

3. **Modify `tests/test_data_quality_runner.py`**
   - `test_check_exclude_before_default`: `Check(...).exclude_before is None`
   - `test_load_checks_reads_exclude_before`: YAML with `not_null: {enforced: false, exclude_before: '2026-01-01'}` -> Check has `exclude_before == '2026-01-01'`
   - `test_compile_not_null_with_exclude_before`: SQL contains `AND created_timestamp >= DATE('2026-01-01')`
   - `test_compile_accepted_values_with_exclude_before`: SQL contains the temporal clause after the NOT IN condition
   - `test_compile_unique_with_exclude_before`: inner subquery SQL contains `WHERE created_timestamp >= DATE(...)` before `GROUP BY`
   - `test_row_count_ignores_exclude_before_in_sql`: `row_count` block with `exclude_before: '2026-01-01'` in YAML -- compiled SQL does NOT contain `created_timestamp`; `Check.exclude_before` field is set
   - Run VP step 1. Fix any failures before proceeding to Step 4.

4. **Modify `config/data_quality/ops.yaml`** (Wave 1 YAML cleanup -- no `exclude_before` yet)
   - Remove the entire `date:` column block from `ops_recommendations` (the `not_null` check
     that produces ERROR because the column was dropped in Decision 56).
   - Change `effort.accepted_values` from `enforced: true` ->
     `enforced: false  # Phase 3 annotation anomaly: bootstrap empty strings fail XS/S/M/L/XL; graduates via exclude_before`
   - Remove the entire `source.accepted_values` block (decision: drop DQ check; write-time
     validation via source registry replaces it).
   - Run VP step 2 (dry-run). Expected check count: 14 (was 16).

5. **Add `exclude_before` to bootstrap checks in `config/data_quality/ops.yaml`** (Wave 2 YAML)
   Add `exclude_before: '2026-05-01'` to the following checks. Keep `enforced: false` for now
   (graduation happens after the live DQ run in step 6):
   - `id.not_null`
   - `title.not_null`
   - `source.not_null`
   - `effort.not_null`
   - `effort.accepted_values` (already `enforced: false` from step 4)
   - `priority.not_null`
   - `priority.accepted_values` (already `enforced: true`; add `exclude_before` for consistency
     with the decision; no enforcement change needed)
   - Add new `created_timestamp:` column block with
     `not_null: {enforced: false, exclude_before: '2026-05-01'}`.
     This is the new check specified in the Phase 4 decision for `created_timestamp`.

6. **Run VP step 3 (live DQ run) then VP step 4 (read verdicts)**
   Run the DQ runner. Read `dq-latest.json` `checks` array for `table=ops_recommendations`.
   For each bootstrap check that shows `"PASS"`: flip `enforced` to `true` in `ops.yaml` --
   the graduation guard will permit the flip. Add or update the inline comment.
   For any check that shows `"FAIL"` despite the temporal gate: do NOT graduate; add inline
   comment `enforced: false  # post-anchor data condition: [brief reason]` and leave for a
   follow-on Phase 4 session.

7. **Run VP steps 5 and 6** (graduation guard + no-unannotated check). Loop until both pass.

8. **Run VP step 7** (Lambda build). Fix any packaging error before committing.

9. **Report**: list which checks were graduated to `enforced: true`, which remain `enforced: false`
   with reasons, and the final check count breakdown from `dq-latest.json`.
