# Plan

## Intent

Close three of the six data quality enforcement gaps identified in the DQ audit
(`PLAN-audit-ops-recs-dq-scalability.md`): the silent empty-PASS vulnerability (Gap 1),
missing recency checks on ops tables (Gap 4), and the fail-open harness exception path (Gap 5).
Together these harden the DQ gate from "silent-pass on empty runs" to "fail-closed with clear
error signals," advancing the verification system toward the definition-equals-enforcement
convergence target.

## Plan Type

IMPLEMENTATION

## Verification Tier

V3

## Branch

agent/dq-harden-gaps-1-4-5

## Phase

Phase Platform - verification system maturation (parallel to Phase 2 schema backfill).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `scripts/data_quality_runner.py` | Modify | Gap 1: guard empty result set -- set verdict to "ERROR" when no checks ran; refuse writing PASS in `_save_latest_result` when total == 0 |
| `scripts/verifiers/data_quality.py` | Modify | Gap 1: return FAIL HARD_GATE before the `if verdict == "PASS":` block when total == 0 |
| `config/data_quality/ops.yaml` | Modify | Gap 4: add `recency:` block (column: `last_updated_timestamp`) to all 5 ops tables; also remove legacy `trade_date` and `ingested_at` column checks (Decision 56 cleanup -- these columns no longer exist in Iceberg, causing ERROR on every live Athena run) [Lambda-packaged -- triggers V3] |
| `scripts/executor/postflight.py` | Modify | Gap 5: replace the fail-open `except Exception` at line 1007 with error-level log, `emit_process_event("verification_gate_error", ...)`, and `return False` |
| `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Add + Annotate | Cherry-pick audit plan from `agent/audit-ops-recs-dq-scalability`; append `## Implementation Progress` section recording which gaps this session closed and what the next stages are |

## Bundled Recommendations

None. The three gaps correspond to candidate recommendations from the audit that have not been
formally filed (executor is non-functional; implementing directly).

## Acceptance Criteria

- [ ] Running `scripts/data_quality_runner.py` with zero matching checks writes
      `verdict: "ERROR"` (not `"PASS"`) to `logs/debug/dq-latest.json` with `total: 0`
- [ ] `DataQualityVerifier` returns `FAIL` `HARD_GATE` when `dq-latest.json` has `total: 0`,
      even if `verdict` in the file is `"PASS"`
- [ ] All 5 ops tables in `config/data_quality/ops.yaml` have a `recency:` block targeting
      `last_updated_timestamp` (Decision 56 column name)
- [ ] Legacy `trade_date` and `ingested_at` column checks removed from all ops tables in
      `config/data_quality/ops.yaml` (columns no longer exist in Iceberg after Decision 56)
- [ ] `_run_verifiers_gate` in `postflight.py` catches harness exceptions, logs at `error`
      level, emits a `"verification_gate_error"` process event, and returns `False`
- [ ] `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` exists on `main` (via this PR) and
      contains a `## Implementation Progress` section noting Gaps 1, 4, 5 closed and
      Sessions B/C/D as the remaining stages

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] static | Confirm runner empty-result guard exists | `grep -n "not results" scripts/data_quality_runner.py` | Match visible near the verdict aggregation block | Add `if not results: verdict = "ERROR"` before has_fail/has_error check |
| 2 | [pre-deploy] unit | Confirm empty `RunResult` writes non-PASS to dq-latest.json | `.venv/Scripts/python.exe -c "from scripts.data_quality_runner import RunResult, _save_latest_result; import json,pathlib; _save_latest_result(RunResult()); d=json.loads(pathlib.Path('logs/debug/dq-latest.json').read_text()); assert d['verdict']!='PASS',f'FAIL: got {d[\"verdict\"]}'; print('OK')"` | Prints `OK` | Fix guard in `_save_latest_result` or verdict aggregation so empty run produces `ERROR` |
| 3 | [pre-deploy] unit | Confirm verifier returns FAIL on empty-PASS JSON | `.venv/Scripts/python.exe -c "import asyncio,json,pathlib; p=pathlib.Path('logs/debug/dq-latest.json'); p.write_text(json.dumps({'verdict':'PASS','total':0,'passed':0,'failed':0,'warned':0,'errored':0,'timestamp':'2099-01-01T00:00:00+00:00','duration_seconds':0.0})); p.touch(); from scripts.verifiers.data_quality import DataQualityVerifier; r=asyncio.run(DataQualityVerifier('t').verify()); assert 'FAIL' in str(r.status),f'Got {r.status}'; print('OK')"` | Prints `OK`. **Restore dq-latest.json** by running the real runner after this step. | Add `total = data.get("total", 0)` check and FAIL HARD_GATE return in verifier before PASS branch |
| 4 | [pre-deploy] static | Confirm 5 recency blocks in ops.yaml targeting correct column | `grep -c "recency:" config/data_quality/ops.yaml && grep -A 2 "recency:" config/data_quality/ops.yaml \| grep "last_updated_timestamp"` | First command returns `5`; second returns 5 matching lines | Add missing `recency:` blocks or fix column name to `last_updated_timestamp` (Decision 56) |
| 5 | [pre-deploy] static | Confirm ops.yaml is valid YAML | `.venv/Scripts/python.exe -c "import yaml; yaml.safe_load(open('config/data_quality/ops.yaml')); print('OK')"` | Prints `OK` | Fix YAML indentation or syntax |
| 6 | [pre-deploy] static | Confirm harness emits process event on failure | `grep -n "verification_gate_error" scripts/executor/postflight.py` | At least one match | Add `emit_process_event("verification_gate_error", ...)` in the except block |
| 7 | [pre-deploy] static | Confirm harness returns False on exception | `grep -A 8 "verification_gate_error" scripts/executor/postflight.py` | `return False` visible after the event emission | Change `return True` to `return False` in the except block |
| 8 | [pre-deploy] static | Confirm audit plan has progress annotation | `grep -c "Implementation Progress" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `>= 1` | Add `## Implementation Progress` section to the audit plan |
| 9 | [post-deploy] integration | Confirm Lambda smoke test passes after deploy | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness 2>&1 \| tail -10` | Exit 0, no ERROR lines | Check Lambda deploy logs; if `doc-freshness` is not a valid agent name, substitute a valid agent from `schedule.yaml` |

## Constraints

- This plan does not address Gaps 2, 3, 6, or the ratchet design -- those are Sessions B, C, D.
- VP step 3 writes synthetic data to `logs/debug/dq-latest.json`. Restore it immediately
  afterwards by running `.venv/Scripts/python.exe -m scripts.data_quality_runner --dry-run`
  (or any real run) so subsequent VP steps and preflight are not misled.
- `emit_process_event` is imported at the top of `scripts/executor/postflight.py` (line 26) --
  no new import needed.
- Recency checks must target `last_updated_timestamp` (not `ingested_at`) -- Decision 56
  replaced `ingested_at` as the SCD2 ordering column.
- The existing `not_null` tests on `ingested_at` and `trade_date` in `ops.yaml` target columns
  that no longer exist in the Iceberg tables after Decision 56. Remove them as part of this
  session -- leaving them causes Athena to return ERROR results on every live run, preventing
  the DQ report from ever reaching PASS.
- Recency thresholds are calibrated to expected write cadence: ops_recommendations/ops_decisions
  (24h warn / 168h error), ops_execution_plans/ops_session_log (48h warn / 168h error),
  ops_priority_queue (36h warn / 72h error -- curator runs daily).
- `config/data_quality/ops.yaml` is packaged into `data-pipeline.zip` via
  `scripts/build_lambda.py:71` -- any edit to this file requires a Lambda rebuild and deploy.
  The DQ runner itself runs locally, not in Lambda; the deploy requirement is a packaging
  boundary, not a behavioral one.
- No rescue agents or workaround loops (Decision 55).

## Context

- Source audit: `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (currently on
  `agent/audit-ops-recs-dq-scalability` -- cherry-pick as Step 1).
- `_run_verifiers_gate` is at `scripts/executor/postflight.py:973`. The fail-open except is at
  line 1007. `emit_process_event` is already imported at line 26.
- Verdict aggregation in runner at line 459; `_save_latest_result` at line 616.
- Verifier PASS branch at `scripts/verifiers/data_quality.py:70`. The staleness check (Gap 3,
  not in scope) is at line 56.
- `recency:` YAML format from `config/data_quality/telemetry.yaml`:
  ```yaml
  recency:
    column: started_at
    warn_after_hours: 48
    error_after_hours: 168
  ```
  Use `last_updated_timestamp` as the column for all ops tables (Decision 56 rename).
- Decision 48: V1=static, V2=unit, V3=integration.
- Decision 55: No rescue agents. Failures must be diagnosed and fixed at root cause.
- Decision 56: `last_updated_timestamp` replaced `ingested_at` as the SCD2 version key for
  all 5 ops tables. `trade_date` partition column also removed. Recency checks must target the
  new column name.
- Single Portal Invariant: never edit `logs/.recommendations-log.jsonl` directly.

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main` (must be `agent/dq-harden-gaps-1-4-5`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` decisions 48, 55, and 56 read
- [ ] All 5 files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable via the Verification Plan commands

## Ordered Execution Steps

1. Cherry-pick the audit plan into the working branch:
   `git checkout agent/audit-ops-recs-dq-scalability -- docs/plans/PLAN-audit-ops-recs-dq-scalability.md`
2. Fix `scripts/data_quality_runner.py` -- two locations:
   - At verdict aggregation (~line 459): add `if not results: verdict = "ERROR"` before the
     `has_fail`/`has_error` check so an empty run cannot produce `"PASS"`.
   - In `_save_latest_result` (~line 616): if `len(result.results) == 0`, override verdict to
     `"ERROR"` in the summary dict before writing (defense-in-depth; both guards should fire).
3. Fix `scripts/verifiers/data_quality.py` -- before the `if verdict == "PASS":` block at
   line 70: read `total = data.get("total", 0)` and return `VerifierResult(status=FAIL,
   severity=HARD_GATE, message="DQ report has total=0 -- runner may have silently skipped all
   checks.")` when `total == 0`.
4. Fix `config/data_quality/ops.yaml` -- two changes to each of the 5 ops tables:
   a. Remove the `trade_date` and `ingested_at` column test stanzas entirely -- these columns
      were removed by Decision 56 and will cause Athena ERROR results on every live run.
   b. Add a `recency:` block using `last_updated_timestamp` as the column (Decision 56 rename),
      with thresholds from the Constraints section.
5. Fix `scripts/executor/postflight.py` at line 1007 -- replace:
   ```python
   except Exception as exc:  # noqa: BLE001
       logger.warning("[VERIFY] Verifier harness failed to run (non-blocking): %s", exc)
       return True
   ```
   with:
   ```python
   except Exception as exc:  # noqa: BLE001
       logger.error("[VERIFY] Verifier harness threw unexpectedly: %s", exc)
       emit_process_event("verification_gate_error", {"error": str(exc)})
       return False
   ```
6. **Execute VP steps 1-8** (all [pre-deploy]) -- after VP step 3, restore `dq-latest.json`
   by re-running the DQ runner. Loop until all pre-deploy steps pass.
7. **Build and deploy Lambda package** (triggers V3):
   `.venv/Scripts/python.exe -m scripts.build_lambda`
   (No `--skip-upload` -- this builds zips and uploads to S3 in one pass. Requires valid AWS
   session. If SSO is expired, run `aws sso login --profile company-aws-profile` first.)
   Then run VP step 9 ([post-deploy]) to confirm the deploy succeeded.
   If the deploy is not available in this environment, document the blocker and stop (Decision 55).
8. Annotate `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` -- append the following section
   at the end of the file (replacing the `## Work Areas` stub):
   ```markdown
   ## Implementation Progress

   ### Session A - Gaps 1, 4, 5 (PLAN-dq-harden-gaps-1-4-5.md / agent/dq-harden-gaps-1-4-5)
   - Gaps closed: Gap 1 (empty PASS), Gap 4 (recency checks), Gap 5 (harness fail-open)
   - PR: [fill in PR number after merge]
   - Status: COMPLETE

   ### Remaining stages
   - **Session B** (PLAN-dq-gate-predicate.md): Gaps 3 + 6 -- stale DQ policy and
     coverage-based gate predicate.
   - **Session C** (PLAN-dq-validate-integration.md): Gap 2 -- `validate.py --integration`
     flag and CI wiring.
   - **Session D** (PLAN-dq-enforced-ratchet.md): RATCHET -- `enforced` field design,
     graduation guard in `validate.py`, deletion commitment. STRATEGIC plan.
   ```
9. Report: summarise what was implemented, paste VP results, confirm all acceptance criteria met.
