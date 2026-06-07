# Plan

## Intent
Close the last red exit-criterion (EC8 churn p95 commit-latency) of platform tier T2.17 by correcting the
churn gate's concurrency model from "N writer threads inside ONE Lambda container" to "N concurrent
Function-URL invocations, each its own container/vCPU" -- the production write model ratified by CD.33 /
Decision 81. The 2000ms p95 / 0.20 OCC-collision budget VALUES are unchanged; only the measurement subject
changes. This unblocks the DuckLake chain (T2.18 -> T2.19 ops cutover) that moves the self-improving
platform's governance store onto a latency-bounded lakehouse write substrate.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (`src/lambdas/ducklake_writer/handler.py` is an `status: active` Lambda artifact; the EC8 gate is a
post-deploy SigV4 invocation against the live writer Function URL. The reader is exercised as a regression
gate but is NOT re-deployed -- no reader code or shared-runtime change is in scope.)

## Plan Path
docs/plans/PLAN-t2-17-ec8-invocation-fanout.md

## Phase
Platform tier T2.17 -- "DuckLake Lambda runtime -- extension layer + version pin (Neon catalog, no VPC
attach)" (YAML `status: not_started`; surfaced as `next_eligible` in the preflight roadmap view -- this plan
flips it to `complete`). 7/8 post-deploy EC gates green at PR #87; EC8 (churn) is the single
remaining red criterion. PR #89 shipped Phase-1 attribution and stopped at VP-13 per Decision 55. This plan
resolves EC8 via the SECONDARY escape hatch (concurrency-model frame correction) that
`PLAN-ducklake-churn-latency-rca.md` documented as requiring human sign-off -- now granted.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/lambdas/ducklake_writer/handler.py` | Modify | Add `action_churn_single` (ONE writer, returns the per-stage attribution dict already produced by `_churn_one_writer`) and a `setup`-gated table pre-create (force_recreate, called once by the client before the concurrent burst to avoid a CREATE race). Keep `action_churn` (the 8-thread in-container burst) intact but reclassify it as an opt-in single-container STRESS DIAGNOSTIC -- it is no longer the EC8 gate. |
| `scripts/ducklake_neon_smoke_test.py` | Modify | Rewrite `lambda_churn` (EC8) to: (1) issue ONE `churn_single` setup invocation to pre-create tables; (2) fan out `CHURN_WRITERS` (=8) CONCURRENT SigV4 POSTs of `{"action":"churn_single"}` via a client-side `ThreadPoolExecutor` (threads only issue HTTP -- the CPU-bound DuckDB work runs server-side, one writer per container); (3) aggregate the N per-invocation dicts into collision_rate + p95 wall + breakdown; (4) loud-fail vs the UNCHANGED budget. Add an opt-in `--lambda-churn-incontainer` flag mapping to the old `action_churn` diagnostic. |
| `terraform/personal/ducklake_lambdas.tf` | Modify | Comment-only: update the `ducklake_writer` `memory_size = 3008` rationale to "retained as baseline headroom per human decision" (the Branch-P budget-chasing rationale is superseded by the frame correction). VALUE unchanged (3008) -> no `terraform plan` diff, no apply. |
| `tests/test_ducklake_writer_handler.py` | Modify | Cover `action_churn_single` (returns the per-stage keys; single writer) + the `setup` pre-create path; retain the `action_churn` diagnostic tests. 100% of new lines. |
| `tests/test_ducklake_neon_smoke_test.py` | Modify | Cover the fan-out `lambda_churn`: mock `_sigv4_invoke` to return N per-invocation bodies, assert N concurrent calls, correct aggregation (collision_rate/p95), loud-fail on budget breach, and the opt-in `--lambda-churn-incontainer` dispatch. |
| `docs/DECISIONS.md` | Modify | Ratify the EC8 frame-correction Decision (next sequential number -- see Ordered Step 6). Records: budget VALUES unchanged; subject = production fan-out per CD.33; in-container burst retained as diagnostic; 3008MB retained as baseline; quota-increase requirement withdrawn. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Flip T2.17 `status: not_started -> complete` once 8/8 EC gates pass; reword the EC8 exit criterion to the invocation-fan-out definition. |
| `docs/SESSION_LOG.md` | Modify | Record the frame-correction disposition, the final EC8 fan-out p95/collision result, and an explicit note superseding the PR-#89 "blocked on Lambda quota" projection. |

## Bundled Recommendations
- **Quota-increase blocker rec** (filed at PR #89 close per `docs/SESSION_LOG.md`: "request Lambda memory
  quota increase eu-west-2 -> >=6144MB"). This plan makes that requirement obsolete. Locate the open rec in
  the `ops_recommendations` warehouse (search title/context for "Lambda memory quota" / "EC8" / "3008") and
  SUPERSEDE/close it via `bin/venv-python -m scripts.ops_data_portal` (`update_rec`) with a rationale
  pointing at the ratified frame-correction Decision. Do NOT edit the JSONL cache directly (Decision 69/70).
- rec-2091 (constant consolidation) was already closed at PR #89 -- nothing to do.

## Infrastructure Dependencies
| Resource | File | Change | Apply posture | Lambda-deploy ordering |
|----------|------|--------|---------------|------------------------|
| `aws_lambda_function.ducklake_writer` `memory_size` | `terraform/personal/ducklake_lambdas.tf` | Comment-only; VALUE stays 3008 | No `terraform plan` diff -> no apply. (If a diff appears, STOP -- the value was changed.) | A code `--deploy` IS still required for the `handler.py` change; `memory_size` is unchanged so no config apply precedes it. No IAM change. |

No new IAM roles/policies. The writer/reader roles are unchanged, so this stays off the manual
`agent_platform_admin` path.

## Acceptance Criteria
- [ ] EC8 passes against the live `ducklake_writer` Function URL via the NEW fan-out path: N=8 concurrent
      `churn_single` invocations report aggregate `within_budget=true`, `p95_commit_ms <= 2000.0`,
      `collision_rate <= 0.20`.
- [ ] The fan-out aggregate body includes the per-stage breakdown (connect, commit, wall, cpu, occ_retries)
      sourced from the N independent invocations -- the evidence that each writer ran on its own vCPU
      (per-invocation `wall_cpu_ratio` near 1, not the ~10-31x in-container starvation).
- [ ] All 8 post-deploy EC gates green: attach, ingress, idempotency, partition, inlining, loudfail, churn
      (writer) + reader.
- [ ] The 2000ms / 0.20 budget constants are UNCHANGED in value (`COMMIT_LATENCY_BUDGET_MS = 2000.0`,
      `OCC_COLLISION_RATE_BUDGET = 0.20` in `src/common/ducklake_runtime.py`) -- verified by grep. This is a
      measurement-subject change, NOT a Decision-55 budget relaxation.
- [ ] `CHURN_WRITERS = 8` unchanged; `OCC_MAX_ATTEMPTS` unchanged; loud-fail semantics intact.
- [ ] The in-container `action_churn` burst is reachable ONLY via the opt-in `--lambda-churn-incontainer`
      flag and is NOT part of the default EC gate sweep.
- [ ] `ducklake_writer` `memory_size` is 3008 (unchanged) with an updated rationale comment.
- [ ] The EC8 frame-correction Decision is ratified in `docs/DECISIONS.md` (next sequential number).
- [ ] T2.17 `status` flipped to `complete` in `docs/ROADMAP-PLATFORM.yaml` with the EC8 criterion reworded.
- [ ] The quota-increase blocker rec is superseded/closed via the ops portal.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Budget constants unchanged in value | `grep -n "COMMIT_LATENCY_BUDGET_MS = 2000.0\|OCC_COLLISION_RATE_BUDGET = 0.20\|CHURN_WRITERS = 8\|OCC_MAX_ATTEMPTS = 5" src/common/ducklake_runtime.py` | All four lines present, values unchanged | If any value changed, revert -- Decision 55/75 forbid relaxing the budget |
| 2 | [pre-deploy] | New single-writer action exists + is wired | `grep -n "def action_churn_single\|\"churn_single\"\|'churn_single'" src/lambdas/ducklake_writer/handler.py` | `action_churn_single` defined and dispatched on the `churn_single` action | If absent, add the action + dispatch entry |
| 3 | [pre-deploy] | Fan-out gate issues concurrent INVOCATIONS, not threads | `grep -n "ThreadPoolExecutor\|churn_single\|_sigv4_invoke" scripts/ducklake_neon_smoke_test.py` | `lambda_churn` fans `CHURN_WRITERS` concurrent `_sigv4_invoke({"action":"churn_single"})` calls | If it still posts a single `{"action":"churn"}`, rewrite the fan-out |
| 4 | [pre-deploy] | Writer handler unit tests pass | `bin/venv-python -m pytest tests/test_ducklake_writer_handler.py -q` | All pass; `action_churn_single` + setup covered | Fix handler/test until green |
| 5 | [pre-deploy] | Smoke-test unit tests pass | `bin/venv-python -m pytest tests/test_ducklake_neon_smoke_test.py tests/test_build_lambda.py -q` | All pass; fan-out + aggregation + opt-in diagnostic covered | Fix until green |
| 6 | [pre-deploy] | Full presubmit (CI-equivalent) | `bin/venv-python -m scripts.validate` | Exit 0 (lint, format, coverage, prompts, imports, roadmap schema) | Address each failure |
| 7 | [pre-deploy] | Affected-artifact set is writer only | `bin/venv-python -c "from scripts.lambda_manifest import compute_affected_artifacts as c; print(sorted(c(['src/lambdas/ducklake_writer/handler.py'])))"` | `['ducklake_writer']` | If reader appears, recheck manifest `includes`; if so add a reader deploy step |
| 8 | [pre-deploy] | Build the writer artifact | `bin/venv-python -m scripts.build_lambda --ducklake-only` | Writer zip + layer build under the size limit | Fix packaging (manifest includes / DUCKLAKE_DEPS) |
| 9 | [pre-deploy] | Terraform shows no diff (memory unchanged) | `terraform -chdir=terraform/personal plan` | "No changes" for `ducklake_writer` `memory_size` (comment-only edit). Present output. | If a diff appears, the value was changed -- revert to 3008 |
| 10 | [deploy] | Deploy the writer function code | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` | `ducklake_writer` updated from S3 | Re-run; check S3 bucket/key parity |
| 11 | [post-deploy] | EC8 fan-out within budget | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn --profile agent_platform` | Prints `CHURN OK ... within_budget` with `p95_commit_ms <= 2000.0`, `collision_rate <= 0.20`; per-invocation `wall_cpu_ratio` ~1; exit 0 | If still over budget at N=8, capture the breakdown and STOP -- escalate per Constraints (do NOT relax the budget); per human steer, reconsider N |
| 12 | [post-deploy] | Each invocation ran on its own vCPU | Inspect the VP-11 breakdown / CloudWatch `ChurnWallCpuRatio` | Per-invocation wall/cpu ratio near 1 (vs ~10-31x in-container) -- confirms the frame correction removed the starvation artifact | If ratio is still high, the fan-out is collapsing onto one container -- verify concurrency / cold-start handling |
| 13 | [post-deploy] | Writer EC gates (regression) | `for g in attach ingress idempotency partition inlining loudfail; do bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-$g --profile agent_platform || exit 1; done` | Each prints OK; exit 0 | Fix the regressing gate before re-attempting churn |
| 14 | [post-deploy] | Reader gate (closed boundary; no redeploy) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-reader --profile agent_platform` | `READER OK rows>=1 write_denied=true` | Boundary regression -- fix |
| 15 | [post-deploy] | Opt-in in-container diagnostic still RUNS (not a gate) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn-incontainer --profile agent_platform` | Prints the in-container breakdown and DOES NOT abort the sweep (a budget miss here is informational, not a gate failure) | If the flag is unrecognised or it aborts the sweep, fix the opt-in dispatch |
| 16 | [post-deploy] | T2.17 roadmap status flipped | `bin/venv-python -m scripts.platform_roadmap` then `grep -n "id: T2.17" -A40 docs/ROADMAP-PLATFORM.yaml \| grep status` | YAML validates; T2.17 `status: complete` | If validation fails, fix the YAML; if still not_started, flip it |

## Constraints
- **Do NOT relax the budget (Decision 55 / CD.33 / Decision 81).** The 2000ms p95 and 0.20 collision-rate
  constants keep their VALUES. This plan changes WHAT EC8 measures (production invocation fan-out), not the
  threshold. No "degrade-to-pass," no silent threshold edit (VP-1 grep-guards this).
- **Pin the budget-comparison term (implicit-relaxation guard).** The fan-out gate applies the 2000ms budget
  to per-invocation `latency_ms` (wall) p95 -- the identical term the in-container `action_churn` used.
  Silently switching the budget to the `commit_ms` breakdown term (which excludes connect/cold-start) would
  be an implicit relaxation and is forbidden. The breakdown still surfaces `connect_ms`/`commit_ms`
  separately for attribution, but the gate term is wall p95.
- **This is a Decision-75 frame correction, ratified by human sign-off** (the SECONDARY escape hatch in
  `PLAN-ducklake-churn-latency-rca.md`). It MUST be recorded as a Decision before the gate is reported
  green -- the gate is not silently redefined.
- **Production concurrency model is N invocations + OCC (CD.33 clause 3).** EC8 fans out N invocations of
  the SINGLE `ducklake_writer` artifact (NOT N artifacts -- preserves CD.33 clause 1 "path split is not for
  concurrency"). Concurrency is OCC + multiple invocations, never reserved-concurrency=1 or SQS FIFO.
- **Loud-fail preserved (Decision 81 clause 3):** schema-gate reject and OCC-retry exhaustion still raise;
  `OCC_MAX_ATTEMPTS` is unchanged.
- **Catalog authority = CD.34 (Neon), not Decision 78 (RDS).** Known doc-lag: cite CD.34 for any catalog
  detail; do NOT cite Decision 78 clause 3 as catalog authority. This plan does NOT adopt the Neon pooler
  (no Branch C), so there is no live catalog-governance interaction.
- **Per-Lambda V3 gating (Decision 79 / CD.16 / CD.24):** only `ducklake_writer` is affected -> build +
  deploy + smoke for the writer; the reader runs as a regression gate without redeploy. DuckDB stays pinned
  (OQ.12 lockstep, 1.5.3).
- **Portal write discipline (Decision 69/70):** the blocker-rec supersession goes through
  `scripts.ops_data_portal` (`update_rec`); never edit `logs/.recommendations-log.jsonl` directly.
- **Single-Portal deferral intact (Decision 78/81):** the Function URLs remain T2.17 smoke-test ingress
  ONLY; no `ops_*` table is wired behind them (T2.19 cutover untouched).
- No rescue agents or workaround loops (Decision 55). If the N=8 fan-out cannot reach budget, stop and
  report the breakdown -- do not hack the gate.

## Context
- **Why EC8 was red (PR #89 attribution).** `action_churn` runs 8 `ThreadPoolExecutor` writers inside ONE
  Lambda container. Measured wall/cpu ratio 31.73x at 1024MB and 10.35x at 3008MB; p95_cpu_ms ~862ms is
  ALREADY inside the 2000ms budget. The only failing term is scheduling delay from over-subscribing 8
  CPU-bound DuckDB engines onto <2 vCPU. Reaching budget in that model needs ~6 vCPU (~10240MB), blocked by
  an AWS account-age Lambda max-memory quota (capped at 3008MB).
- **Why the fan-out is the correct measurement.** Production ops writes (`file_rec`/`update_rec`) are
  independent single-commit Lambda invocations -- each its own container/vCPU. The 8-threads-in-one-
  container harness is harsher than and unrepresentative of production, and CPU-starves in a way production
  never will. The architecturally-meaningful OCC-collision sub-gate is preserved (and arguably exercised
  more faithfully) by N truly-concurrent invocations hitting the same Neon catalog simultaneously; only the
  corrupted latency measurement is fixed.
- **Cold-start consideration (implementation note).** N=8 concurrent invocations may incur cold starts
  (extension-layer load + ATTACH inside `connect_ms`). The fan-out pre-creates tables once (one warm
  `churn_single` setup call) before the burst, mirroring the existing `churn_gate` pre-warm. The breakdown
  surfaces `connect_ms` vs `commit_ms` so any residual cold-start skew is attributable. Per the human steer,
  N=8 is deliberately high; if it cannot pass, capture the breakdown and reconsider N (do not relax the
  budget).
- **Memory decision (human).** `ducklake_writer` stays at 3008MB as a baseline (NOT reverted to 1024),
  giving each single-writer invocation ~1.7 vCPU of headroom. Comment-only tf edit; no apply.
- **Decisions to reference (decision-scout CITE, Verdict NO_FLAGS):** 81/CD.33 (production concurrency
  model -- authoritative), 55 (no budget relax), 75 (frame-correction precedent), 79 (per-Lambda V3
  gating), 77 (sandbox auto-apply -- here a no-op since no tf diff), 70 (portal rec discipline). NOTEs:
  (a) state EC8 fans out N invocations of the single writer artifact (CD.33 clause 1); (b) cite CD.34 not
  Decision 78 for catalog detail.
- **Decision numbering.** At planning time the max top-level heading in `docs/DECISIONS.md` is Decision 81
  (dec-1089); Decision 82 = CD.34 is referenced from the roadmap. The implementer confirms the current max
  (DECISIONS.md + `ops_decisions`) and allocates the next free sequential number.
- ci-rca: preflight `ci_rca_recs` is empty -- nothing to fold in.
- Branch was 0 commits behind `origin/main` at planning time (no Main Divergence Assessment needed).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `claude/platform-roadmap-t2-17-T2poK`)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md consulted via the decision-scout gate (CITE: 81/CD.33, 55, 75, 79, 77, 70; NOTE: CD.34 vs 78, CD.33 clause 1)
- [ ] All files in the Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS `agent_platform` chain verified (`aws sts get-caller-identity --profile agent_platform`)

## Ordered Execution Steps
1. **Handler: single-writer action.** In `src/lambdas/ducklake_writer/handler.py` add `action_churn_single`:
   on `{"action":"churn_single","setup":true}` pre-create the SCD2 tables (`create_scd2_tables(force_recreate=True)`)
   and return `{"ok":true,"setup":true}`; on `{"action":"churn_single"}` (no setup) resolve dsn + frozen
   creds, run ONE `_churn_one_writer(...)`, and return its per-stage dict (`latency_ms`, `collided`,
   `connect_ms`, `commit_ms`, `cpu_ms`, `occ_retries`) plus `ok:true`. Wire the new action into the handler
   dispatch. Leave `action_churn` untouched (it stays callable for the opt-in diagnostic). Run VP-2.
2. **Smoke test: invocation fan-out.** In `scripts/ducklake_neon_smoke_test.py` rewrite `lambda_churn`:
   (a) one setup invocation `{"action":"churn_single","setup":true}`; (b) a client `ThreadPoolExecutor`
   issuing `CHURN_WRITERS` concurrent `_sigv4_invoke(writer_url, {"action":"churn_single"})` calls;
   (c) aggregate the N bodies -- `collision_rate = collided/N`, `p95` of `latency_ms`, breakdown p95s
   (connect/commit/cpu) + per-invocation `wall_cpu_ratio`; (d) evaluate vs `COMMIT_LATENCY_BUDGET_MS` /
   `OCC_COLLISION_RATE_BUDGET` and loud-fail (`SmokeTestFailure`) on breach, matching the existing
   message/no-relax wording. **Pin the budget-comparison term:** apply the budget to per-invocation
   `latency_ms` (wall) p95 -- the SAME term the in-container `action_churn` gated on -- NOT the more lenient
   `commit_ms` breakdown term. Switching to `commit_ms` would be an implicit Decision-55 relaxation; keep the
   subject "per-invocation wall latency" so "within_budget" means the same thing across both paths. Add a
   `--lambda-churn-incontainer` arg (wired into the argparse mutually-exclusive gate group AND the
   `_LAMBDA_GATES`/`main` dispatch, alongside the other `--lambda-*` gates) that posts the legacy
   `{"action":"churn"}` and prints its breakdown WITHOUT gating the sweep. Run VP-3.
3. **Tests.** Update `tests/test_ducklake_writer_handler.py` (action_churn_single + setup; retain
   action_churn diagnostic coverage) and `tests/test_ducklake_neon_smoke_test.py` (mock `_sigv4_invoke` to
   return N bodies; assert N concurrent calls, aggregation, loud-fail, opt-in dispatch). 100% of new lines.
   Run VP-4, VP-5.
4. **Terraform comment.** In `terraform/personal/ducklake_lambdas.tf` update only the `memory_size = 3008`
   rationale comment (baseline headroom per human decision; frame-correction supersedes Branch-P). Run VP-9
   to confirm no plan diff.
5. **Presubmit.** Run VP-6 (`scripts.validate`); fix to green.
6. **Ratify the Decision.** Confirm the current max Decision number, then add the EC8 frame-correction
   Decision to `docs/DECISIONS.md` (title: "EC8 churn gate measures production invocation fan-out, not
   in-container thread contention"). Body: budget VALUES unchanged (not a Decision-55 relaxation; a
   Decision-75 measurement-subject correction); subject = N concurrent invocations of the single
   `ducklake_writer` per CD.33 clause 3; in-container `action_churn` retained as opt-in diagnostic; 3008MB
   retained as baseline; the quota-increase requirement is withdrawn. Cite 81/CD.33, 55, 75, 79; catalog =
   CD.34.
7. **Build + deploy the writer.** Run VP-7, VP-8, VP-10.
8. **Post-deploy gate sweep.** Run VP-11, VP-12, VP-13, VP-14, VP-15. All gates green; capture the fan-out
   breakdown. If VP-11 cannot reach budget at N=8, STOP and report the breakdown (escalate per Constraints).
9. **Flip roadmap status.** With 8/8 green, set T2.17 `status: complete` in `docs/ROADMAP-PLATFORM.yaml` and
   reword the EC8 exit criterion to the invocation-fan-out definition. Run VP-16.
10. **Close-out.** Supersede/close the quota-increase blocker rec via `scripts.ops_data_portal`
    (`update_rec`) citing the new Decision. Write the `docs/SESSION_LOG.md` disposition: the frame
    correction, the live fan-out p95/collision + per-invocation wall/cpu ratio, and an explicit note that
    this supersedes the PR-#89 "blocked on Lambda quota" projection.
11. **Execute Verification Plan** -- run every VP step. Loop until pass. If the V3 fan-out cannot reach
    budget unrecoverably at N=8, stop and report root cause (Decision 55) -- do not relax the gate; per the
    human steer, reconsider N as a follow-up.
12. Report: the fan-out per-invocation breakdown, the final EC8 p95/collision, the full 8/8 gate status, and
    the ratified Decision number.
