# Plan

## Intent
Graduate the 4 remaining advisory wave-2 DQ checks for `ops_recommendations` to `enforced: true`,
completing Phase 4 for all non-deferred fields. Introduce `UNENFORCED_FAIL` verdict for advisory
failures system-wide and embed `write_time` enforcement metadata into `ops.yaml` as the unified
read/write config template -- one manifest consumed by both the DQ runner and (after
`dq-write-enforcement-unification`) the portal.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-wave2-ops-rec-graduation

## Phase
Phase 1: Core Infrastructure (COMPLETE per ROADMAP.md) -- executing within Phase 4 of the DQ
enforcement arc (INTENT-dq-enforcement.md).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/data_quality_runner.py` | Modify | `UNENFORCED_FAIL` verdict for `enforced: false, severity: error` failures; split `failed`/`unenforced_fail` in aggregate |
| `tests/test_data_quality_runner.py` | Modify | Tests for `UNENFORCED_FAIL` verdict, aggregate split, graduation guard interaction |
| `config/data_quality/ops.yaml` | Modify | Add `exclude_before: '2026-05-01'` to 4 wave-2 checks; add `write_time`/`python` metadata to ops_recommendations columns; graduate 4 checks to `enforced: true` after DQ confirms PASS |
| `config/data_quality/decisions/ops_recommendations.yaml` | Modify | Update `last_verdict`, `enforcement_ready`, `resolved_date` for `file`, `context`, `acceptance` |
| `docs/INTENT-dq-enforcement.md` | Modify | Update Phase 4 Session Map wave-2 row; document `write_time` template output |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `ops.yaml` `file.not_null`, `context.not_null`, `context.expression`, `acceptance.not_null` all have `enforced: true` and `exclude_before: '2026-05-01'`
- [ ] `ops.yaml` `file`, `context`, `acceptance`, `automatable`, `risk`, `source` columns contain `write_time: true` on applicable tests; `context.expression` contains `python: "len(value.strip()) >= 80"`
- [ ] `data_quality_runner.py` emits `UNENFORCED_FAIL` (never `FAIL`) for `severity: error, enforced: false` failures; `FAIL` reserved for `enforced: true` failures only
- [ ] `dq-latest.json` aggregate includes `unenforced_fail` count; `failed` count reflects enforced-only failures
- [ ] Live DQ run confirms all 4 wave-2 checks return `PASS`
- [ ] `validate.py` graduation guard treats `UNENFORCED_FAIL` as non-PASS (blocks graduation)
- [ ] `validate.py` full presubmit passes with no regressions
- [ ] `decisions/ops_recommendations.yaml` `last_verdict` updated to `PASS` for `file`, `context`, `acceptance`
- [ ] INTENT doc Phase 4 Session Map reflects wave-2 graduation complete

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | `UNENFORCED_FAIL` verdict fires for `enforced: false, severity: error` failing check | `pytest tests/test_data_quality_runner.py -v -k "unenforced"` | All unenforced verdict tests pass | Check verdict assignment path in `run_checks`; verify `check.enforced == False and check.severity == "error"` conditional |
| 2 | [pre-deploy] | Graduation guard treats `UNENFORCED_FAIL` as non-PASS | `pytest tests/test_data_quality_runner.py -v -k "graduation"` | Guard blocks flip when verdict is `UNENFORCED_FAIL` | Verify graduation guard condition in `scripts/validate.py` reads `verdict != "PASS"`; `UNENFORCED_FAIL` satisfies this without code change |
| 3 | [post-deploy] | All 4 wave-2 checks return `PASS` after `exclude_before` active | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml && .venv/Scripts/python.exe -c "import json; d=json.load(open('logs/debug/dq-latest.json')); wave2=[c for c in d['checks'] if c['table']=='ops_recommendations' and c['column'] in ('file','context','acceptance')]; assert all(c['verdict']=='PASS' for c in wave2), wave2"` | Assertion passes with empty list of failures | Run Athena query (OES 5) to identify residual post-2026-05-01 failing rows; backfill via `update_rec`; re-run |
| 4 | [post-deploy] | No `FAIL` verdict on `enforced: false` checks anywhere in the run | `.venv/Scripts/python.exe -c "import json; d=json.load(open('logs/debug/dq-latest.json')); raw=[c for c in d['checks'] if c['verdict']=='FAIL']; assert raw == [] or all(c.get('enforced', True) for c in raw), [c for c in raw if not c.get('enforced', True)]"` | Assertion passes | Identify which check emits raw `FAIL` with `enforced: false`; trace through `run_checks` verdict assignment |
| 5 | [post-deploy] | Graduation guard accepts `enforced: true` flip for all 4 checks | `.venv/Scripts/python.exe -m scripts.validate 2>&1 \| grep -iE "graduation\|not yet pass\|UNENFORCED"` | Zero graduation guard rejection lines | Verify `dq-latest.json` has `PASS` for all 4 checks; if not, repeat OES 4-5 backfill loop |
| 6 | [post-deploy] | Full presubmit passes | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Diagnose failing check from output |

## Constraints
- No STRATEGIC plans (CLAUDE.md, Decision 67 still active)
- Lambda deployment deferred (Decision 67) -- not in scope
- `write_time` and `python` fields added to `ops.yaml` are **metadata-only** in this plan; `scripts/ops_data_portal.py` is not modified here -- that is the scope of `dq-write-enforcement-unification`
- Do not flip `enforced: false` -> `enforced: true` before VP step 3 confirms PASS for all 4 checks
- RCA-before-action satisfied: root causes for `file`, `context`, `acceptance` are Class C in `decisions/ops_recommendations.yaml`
- `hard_gated` count computation is unaffected by the `UNENFORCED_FAIL` rename: only `enforced: true` failures contribute; no change to the `DataQualityVerifier` gate logic
- Graduation guard in `scripts/validate.py` reads `verdict != "PASS"` -- `UNENFORCED_FAIL` satisfies this condition without code change to the guard
- Data backfill (OES 5) is conditional and runs within this plan's branch; any `update_rec` calls go through `ops_data_portal` only

## Context
- Phase 4 Wave 2 marked "COMPLETE (PR #319)" in INTENT doc but 4 checks remain unenforced: PR added the checks without `exclude_before` and completed only partial backfill (19 automatable + 9 acceptance prose conversions). This plan closes that gap.
- Wave-2 checks currently show `FAIL` in `dq-latest.json` (2026-05-10 snapshot, pre-merge). With `exclude_before: '2026-05-01'` active, only open recs filed after that date are in scope; wave-2 write-time validators (merged 2026-05-11) ensure all new recs have valid `file`/`context`/`acceptance`. The residual cohort is recs filed between 2026-05-01 and 2026-05-11 that the wave-2 partial backfill missed.
- `UNENFORCED_FAIL` is a system-wide rename: all tables with `enforced: false, severity: error` checks will emit this verdict after OES 1. Expected count at first post-change DQ run: ~60 (current `unenforced_fail` pool across all tables in `dq-latest.json`).
- The `write_time` schema extension is the machine-readable spec for the follow-on `dq-write-enforcement-unification` plan. See OES 8 for the `file_rec` call to register that plan.
- Decision 65: `ops.yaml` extended contract (description + semantics per column) is already in place. `write_time` and `python` are additional machine-parseable fields in the same contract; no companion document needed.
- Deferred waves: Wave 4 (execution_result, execution_date, execution_branch, execution_pr_url, execution_steps) blocked by Decision 63 + Decision 67. Wave 5 (id, title, effort, priority, created_timestamp) blocked on exclude_before formal session tracking. Neither is in scope.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] `docs/INTENT-dq-enforcement.md` Phase 4 section read in full
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] `UNENFORCED_FAIL` graduation guard interaction confirmed: `validate.py` graduation guard already checks `verdict != "PASS"` -- no change to guard needed, only test coverage required

## Ordered Execution Steps

1. **`scripts/data_quality_runner.py`** -- In the per-check verdict assignment path, add conditional: when `check.severity == "error"` and `check.enforced == False` and the check result is failing, emit `"UNENFORCED_FAIL"` instead of `"FAIL"`. `"FAIL"` is now exclusively for `enforced: true` failures. Update `_save_latest_result`: add `unenforced_fail` key to the aggregate JSON (count of checks with verdict `"UNENFORCED_FAIL"`); update `failed` count to exclude unenforced failures. Update `_print_results` to emit the `UNENFORCED_FAIL` token unchanged (no separate rendering path -- this is an agent repo).

2. **`tests/test_data_quality_runner.py`** -- Add tests:
   - `enforced: false + severity: error + failing check` -> verdict is `UNENFORCED_FAIL`
   - `enforced: true + severity: error + failing check` -> verdict is `FAIL`
   - `severity: warn + enforced: true + failing check` -> verdict is `WARN` (warn severity is always advisory regardless of `enforced`)
   - graduation guard blocks flip from `enforced: false` -> `enforced: true` when verdict is `UNENFORCED_FAIL`
   - `_save_latest_result` writes `unenforced_fail: N` in aggregate; `failed` count excludes unenforced failures

3. **`config/data_quality/ops.yaml` -- exclude_before + write_time metadata** -- For `ops_recommendations` only. Add `exclude_before: '2026-05-01'` to `file.not_null`, `context.not_null`, `context.expression`, `acceptance.not_null`. Add `write_time: true` to `file.not_null`, `context.not_null`, `context.expression`, `acceptance.not_null`. Add `python: "len(value.strip()) >= 80"` to `context.expression`. Add named-validator entries with `write_time: true, enforced: true`: `path_syntax` under `file.tests`, `acceptance_lint` under `acceptance.tests`. Add `write_time: true` to `source.not_null`, `automatable.not_null`, `risk.not_null`, `risk.accepted_values`. Do NOT flip `enforced` in this step.

4. **Run DQ runner and inspect** -- `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml`. Inspect `logs/debug/dq-latest.json` `checks` array for the 4 wave-2 checks. Proceed to OES 6 only if all 4 show `PASS`. If any show `UNENFORCED_FAIL`, proceed to OES 5.

5. **(Conditional) Athena backfill** -- Query: `SELECT id, file, context, acceptance FROM trading_formulas_db.ops_recommendations_current WHERE status='open' AND created_timestamp >= TIMESTAMP '2026-05-01 00:00:00' AND (file IS NULL OR context IS NULL OR acceptance IS NULL OR LENGTH(TRIM(context)) < 80)`. For each row: curate correct values; call `update_rec(id, {"file": ..., "context": ..., "acceptance": ...})`. Re-run DQ (OES 4). Loop until all 4 checks return `PASS`.

6. **`config/data_quality/ops.yaml` -- graduation** -- Flip `enforced: false` -> `enforced: true` for `file.not_null`, `context.not_null`, `context.expression`, `acceptance.not_null`. Remove inline `# data condition -- ... backfilled in wave-2` comments from those 4 entries (post-graduation noise).

7. **`config/data_quality/decisions/ops_recommendations.yaml`** -- Update `file`, `context`, `acceptance` fields: `last_verdict: PASS`, `enforcement_ready: GRADUATED`, `resolved_date: '2026-05-11'`, `resolution_pr: TBD` (fill in after merge).

8. **`docs/INTENT-dq-enforcement.md`** -- Update Phase 4 Session Map wave-2 row: append note `(4 checks graduated 2026-05-11; write_time metadata template in ops.yaml)`. File a recommendation via `ops_data_portal.file_rec` for the `dq-write-enforcement-unification` follow-on plan (title: "Refactor ops_data_portal write-time validation to dispatch from ops.yaml write_time entries"; file: `scripts/ops_data_portal.py`; effort: M; priority: High).

9. **Execute Verification Plan** -- run each VP step in order. Loop on VP step 3/OES 5 until all 4 checks PASS. If VP step 6 fails unrecoverably after 2 attempts, stop and analyze root cause (Decision 55).

10. **DEFERRED: `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` + `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` (pending Decision 67 reversal)** -- `config/data_quality/ops.yaml` is Lambda-packaged. Lambda rebuild and smoke-test are required after Decision 67 is reversed.

11. Report: checks graduated, VP results, residual backfill row count (0 expected), rec ID for `dq-write-enforcement-unification`.
