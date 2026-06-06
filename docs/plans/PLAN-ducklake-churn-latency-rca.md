# Plan

## Intent
Root-cause and reduce the DuckLake EC8 "churn" gate p95 commit latency (observed ~23s in-Lambda) below
the 2000ms CD.33 budget WITHOUT relaxing the budget, closing the last red exit-criterion of T2.17 so the
operational lakehouse write path can advance toward the T2.19 production cutover. This keeps the
self-improving platform's governance store on a proven, latency-bounded write substrate.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (both `ducklake_writer` and `ducklake_reader` are `status: active` Lambda artifacts; the shared
`src/common/ducklake_runtime.py` is in scope, so per Decision 79 / `compute_affected_artifacts` BOTH
artifacts require build + deploy + post-deploy SigV4 smoke-test.)

## Plan Path
docs/plans/PLAN-ducklake-churn-latency-rca.md

## Phase
Platform tier T2.17 - "DuckLake Lambda runtime -- extension layer + version pin (Neon catalog, no VPC
attach)" (currently `next_eligible` on the platform roadmap). EC8/churn is the single un-met exit
criterion remaining from PR #87 (7/8 post-deploy EC gates green at merge).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/lambdas/ducklake_writer/handler.py` | Modify | Phase 1: instrument `action_churn`/`_churn_one_writer` with per-stage latency attribution (connect+LOAD, ATTACH, per-commit catalog round-trip via the already-returned `WriteResult.commit_ms`/`occ_retries`, OCC backoff) plus wall-clock vs thread-CPU time to detect vCPU starvation; surface the breakdown in the churn response body + CloudWatch. Phase 2: apply the measurement-selected fix branch(es). rec-2091: import the budget/marker constants from `ducklake_runtime` instead of redefining them. |
| `src/common/ducklake_runtime.py` | Modify | rec-2091: become the single home for `COMMIT_LATENCY_BUDGET_MS`, `OCC_COLLISION_RATE_BUDGET`, `CHURN_WRITERS`, `CHURN_WRITES_PER_WRITER`, and the OCC collision markers (both the writer handler and the smoke test import them). Phase 2 (conditional, Branch O/C): OCC-backoff-schedule tuning and/or optional pooled-host support in `open_connection`/`fetch_dsn` if Phase-1 attribution points there. |
| `scripts/ducklake_neon_smoke_test.py` | Modify | rec-2091: import the consolidated constants from `ducklake_runtime` (drop the local duplicates). Surface the new per-stage breakdown in the `--lambda-churn` print line. Phase 2 (conditional, Branch C): a pooled-endpoint transaction-safety proof variant. |
| `terraform/personal/ducklake_lambdas.tf` | Modify | Phase 2 Branch P (primary, most likely): raise `ducklake_writer` `memory_size` (1024 -> stepped, see decision tree) to allocate more vCPU so the existing 8-way in-process concurrency meets the budget honestly. Non-IAM, non-destructive -> Decision 77 sandbox auto-apply behind the fail-closed guard. |
| `terraform/personal/neon_ducklake_catalog.tf` | Modify (conditional, Branch C) | Expose the Neon `host_pooler` endpoint in the DSN secret JSON so the runtime can use the pooled endpoint -- ONLY after the transaction-safety proof passes. Non-IAM -> Decision 77 auto-apply. |
| `tests/test_ducklake_writer_handler.py` | Modify | Update `test_handler_churn`/`test_churn_one_writer*` for the new breakdown dict; cover the relocated-constant imports and any Phase-2 handler fix code (100% of new lines). |
| `tests/test_ducklake_runtime.py` | Modify | Cover the relocated constants and any runtime fix (backoff schedule / pooled-host selection). |
| `tests/test_ducklake_neon_smoke_test.py` | Modify | Cover the constant-import change, the new `--lambda-churn` print, and any pooler-proof variant. |
| `docs/SESSION_LOG.md` | Modify | Record the RCA disposition with the live attribution decomposition + final p95, superseding rec-2084's "latency-waived-with-rationale" projection (which the EC8 result falsified). |
| `docs/plans/PLAN-ducklake-churn-latency-rca.md` | Create | This plan. |

## Bundled Recommendations
- **rec-2091** (open, Low, code-review): "Churn budgets and OCC markers duplicated between writer handler
  and smoke test." Consolidate `COMMIT_LATENCY_BUDGET_MS` / `OCC_COLLISION_RATE_BUDGET` / `CHURN_WRITERS`
  / `CHURN_WRITES_PER_WRITER` / OCC markers into `src/common/ducklake_runtime.py` as the single source;
  the writer handler and smoke test import them. Close via the ops portal (`update_rec`) on completion.

Related-but-NOT-bundled (context only): rec-2084 (closed predecessor -- see Context); rec-2087, rec-2089,
rec-2090 (tangential DuckLake recs left open).

## Infrastructure Dependencies
| Resource | File | Change | Apply posture | Lambda-deploy ordering |
|----------|------|--------|---------------|------------------------|
| `aws_lambda_function.ducklake_writer` `memory_size` | `terraform/personal/ducklake_lambdas.tf` | Raise 1024 -> stepped value | Decision 77 sandbox AUTO-APPLY (non-IAM, non-destructive; the guard `scripts/terraform_apply_guard.py` returns exit 0). Present `terraform plan` output regardless. | No IAM change, so no IAM-precedence constraint. `memory_size` is a function-config attribute applied by `terraform apply`; a code `--deploy` is still required for the handler-source change. |
| `aws_secretsmanager_secret_version.ducklake_neon_catalog_dsn` (add `host_pooler`) | `terraform/personal/neon_ducklake_catalog.tf` | Branch C only; add pooled host to the DSN JSON | Decision 77 auto-apply (secret-version update is NOT in the guard's IAM-sensitive types). Gated on the transaction-safety proof passing first. | None. |

No new IAM roles/policies are created by this plan (the existing writer/reader roles are unchanged), so
unlike the original T2.17 apply this does NOT route to the manual `agent_platform_admin` path.

## Acceptance Criteria
- [ ] EC8 churn gate passes against the live `ducklake_writer` Function URL: the `--lambda-churn` response
      reports `within_budget=true` and `p95_commit_ms <= 2000.0` with `collision_rate <= 0.20`.
- [ ] The churn response body includes a per-stage attribution breakdown (connect+LOAD, ATTACH, commit,
      OCC backoff, wall vs CPU) -- the RCA evidence, not just a pass/fail.
- [ ] All 8 post-deploy EC gates are green: attach, ingress, idempotency, partition, inlining, loudfail,
      churn (writer) + reader.
- [ ] The 2000ms / 0.20 budget constants are UNCHANGED in value (verified by grep) -- moved location
      (rec-2091) but never relaxed (Decision 55).
- [ ] OCC attempt budget (`OCC_MAX_ATTEMPTS`) unchanged; loud-fail semantics intact.
- [ ] rec-2091 closed via the ops portal.
- [ ] If the SECONDARY (concurrency-model) escape hatch is reached: a recommendation proposing the
      concurrency-model Decision is filed via the portal and the gate is left red pending human
      ratification -- the gate is NOT silently redefined.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Budget constants unchanged in value | `grep -n "2000" src/common/ducklake_runtime.py && grep -n "0.20\|0\.2[^0-9]" src/common/ducklake_runtime.py` | `COMMIT_LATENCY_BUDGET_MS = 2000.0` and `OCC_COLLISION_RATE_BUDGET = 0.20` present in the runtime module | If the value changed, revert -- Decision 55 forbids relaxing the budget |
| 2 | [pre-deploy] | No duplicate budget literals remain (rec-2091) | `grep -rn "COMMIT_LATENCY_BUDGET_MS =\|OCC_COLLISION_RATE_BUDGET =" src/lambdas/ducklake_writer/handler.py scripts/ducklake_neon_smoke_test.py` | No assignment matches (handler + smoke import from runtime) | If a local re-definition remains, replace with an import from `ducklake_runtime` |
| 3 | [pre-deploy] | Writer handler unit tests pass (incl. new breakdown) | `bin/venv-python -m pytest tests/test_ducklake_writer_handler.py -q` | All pass; churn tests assert the breakdown keys | Fix handler/test until green |
| 4 | [pre-deploy] | Runtime unit tests pass | `bin/venv-python -m pytest tests/test_ducklake_runtime.py -q` | All pass | Fix runtime/test until green |
| 5 | [pre-deploy] | Smoke-test unit tests pass | `bin/venv-python -m pytest tests/test_ducklake_neon_smoke_test.py tests/test_build_lambda.py -q` | All pass | Fix until green |
| 6 | [pre-deploy] | Full presubmit (CI-equivalent) | `bin/venv-python -m scripts.validate` | Exit 0 (lint, format, coverage, prompts, imports) | Address each failure |
| 7 | [pre-deploy] | Affected-artifact set is writer + reader | `bin/venv-python -c "from scripts.lambda_manifest import compute_affected_artifacts as c; print(sorted(c(['src/common/ducklake_runtime.py','src/lambdas/ducklake_writer/handler.py'])))"` | `['ducklake_reader', 'ducklake_writer']` | If a slug is missing, recheck manifest `includes` |
| 8 | [pre-deploy] | Build both DuckLake artifacts | `bin/venv-python -m scripts.build_lambda --ducklake-only` | Both zips + both layer zips build under the size limit | Fix packaging (DUCKLAKE_DEPS / manifest includes) |
| 9 | [pre-deploy] | Terraform plan for `memory_size` (+ optional pooler) | `terraform -chdir=terraform/personal plan` | Plan shows ONLY `memory_size` (and, Branch C only, the DSN-secret) change; no IAM/destroy. Present output to the human. | If the plan shows IAM/destroy, stop -- out of scope |
| 10 | [deploy] | Apply terraform (sandbox auto-apply posture) | `terraform -chdir=terraform/personal apply` (or push-to-main sandbox auto-apply behind the guard) | `memory_size` applied; guard exit 0 | If the guard fail-closes, the change touched a sensitive type -- re-scope |
| 11 | [deploy] | Deploy both Lambda function codes | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` | Both functions updated from S3 | Re-run; check S3 bucket/key parity |
| 12 | [post-deploy] | Phase-1 attribution captured | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn --profile agent_platform` | Response/print includes the per-stage breakdown (connect+LOAD, ATTACH, commit, OCC backoff, wall, cpu). Record the decomposition in the plan outcome + SESSION_LOG. | If keys absent, the instrumentation did not deploy -- rebuild/redeploy |
| 13 | [post-deploy] | EC8 churn within budget | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn --profile agent_platform` | Prints `CHURN OK ... within_budget` with `p95_commit_ms <= 2000.0`; exit 0 | Apply the next decision-tree branch (P -> C -> O); if none fits, SECONDARY escape hatch |
| 14 | [post-deploy] | Writer EC gates (regression) | `for g in attach ingress idempotency partition inlining loudfail; do bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-$g --profile agent_platform || exit 1; done` | Each prints OK; exit 0 | Fix the regressing gate before re-attempting churn |
| 15 | [post-deploy] | Reader gate (closed boundary, post-rebuild) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-reader --profile agent_platform` | `READER OK rows>=1 write_denied=true` | Reader rebuild/deploy or boundary regression -- fix |
| 16 | [post-deploy] | Branch C only: pooler transaction-safety proof | `DUCKLAKE_USE_POOLER=1 bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-idempotency --profile agent_platform && DUCKLAKE_USE_POOLER=1 bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-loudfail --profile agent_platform` | Both pass through the pooled endpoint (multi-statement DuckLake txns hold; no silent drop) | If either fails, the pooler is transaction-UNSAFE -- do NOT adopt it; revert the DSN change and rely on Branch P |

## Constraints
- **Do NOT relax the budget (Decision 55 / CD.33 / Decision 81).** The 2000ms p95 and 0.20 collision-rate
  constants keep their VALUES; rec-2091 only relocates them. No "degrade-to-pass," no silent threshold
  edit. The fix must attack latency.
- **Loud-fail preserved (Decision 81 clause 3):** schema-gate reject and OCC-retry exhaustion still raise;
  `OCC_MAX_ATTEMPTS` (the Decision-55-protected stop signal) is unchanged. OCC *backoff schedule* timing is
  distinct from the attempt budget and MAY be tuned (Branch O).
- **No new IAM** (keeps the apply on the Decision 77 sandbox auto-apply path; present `terraform plan`
  regardless per terraform/CLAUDE.md).
- **Single-Portal deferral intact (Decision 78/81):** the Function URLs remain T2.17 smoke-test ingress
  ONLY; no `ops_*` table is wired behind them (T2.19 cutover untouched).
- **Per-Lambda V3 gating (Decision 79 / CD.16 / CD.24):** both `ducklake_writer` and `ducklake_reader`
  (active) get build + deploy + smoke; DuckDB stays pinned (OQ.12 lockstep, 1.5.3).
- **Neon pooler is gated (CD.34 / `neon_ducklake_catalog.tf`):** adopt the `host_pooler` endpoint ONLY
  after the transaction-safety proof (VP-16) passes -- DuckLake commits are multi-statement transactions
  that PgBouncer transaction-mode pooling can break.
- No rescue agents or workaround loops (Decision 55). If V3 cannot reach budget, stop and RCA (escape
  hatch), do not hack the gate.

## Context
- **Predecessor rec-2084 (closed).** The churn gate previously failed at the *smoke-test* (non-Lambda)
  level: p95 8692ms, collision_rate 0.000. It was patched (pre-warm one ATTACH + pre-fetch STS creds once,
  shared across the 8 workers via `_creds`). T2.16b VP-2 was then disposed "latency-waived-with-rationale"
  on the explicit projection that **"production Lambda -> Neon same-region path strips the RTT; projected
  p95 lands under budget."** The live EC8 result (~23s, WORSE) **falsifies that projection** -- explaining
  the falsification is the RCA's job. The decomposition recorded in rec-2084 (~3500ms of a 4774ms p95 was
  RTT-bound commit, on residential Windows) is the prior datum; the new attribution must show what
  dominates in-Lambda.
- **Leading hypothesis (to confirm, not assume).** `action_churn` runs 8 `ThreadPoolExecutor` writers
  inside ONE 1024MB Lambda (~0.57 vCPU). The "8 concurrent writers" are really 8 CPU-bound DuckDB engines
  contending for <1 vCPU -- harsher than real production fan-out (N separate invocations, each its own
  vCPU) and CPU-bound, which residential-RTT smoke testing masked. `write_scd2` already returns `commit_ms`
  + `occ_retries`, but `_churn_one_writer` discards them -- the attribution data is one capture away.
- **Why EC8 can finally run:** the Lambda-invoke gates only need HTTPS to the Function URL + STS from the
  caller; the TCP/5432 egress block that prevented the smoke-level churn gate from running in CC-web does
  not apply to the in-Lambda path (the Neon connection is made inside the Lambda, in-region).
- **Decision flag (NOTE, from decision-scout).** Decision 78 clause 3 ratifies the catalog as RDS
  PostgreSQL, but the in-tree reality is Neon (RDS retired; Neon governed by CD.34). This is doc-lag. If
  Branch C (Neon pooler) is taken in-plan, do NOT cite Decision 78 as authority for the Neon change -- cite
  CD.34 -- and file a follow-up rec noting Decision 78 clause 3 needs a superseding/amendment entry to
  reflect the Neon catalog. (The code's "Decision 37 runtime-fetch" reference is a secret-fetch-PATTERN
  precedent, not catalog governance.)
- **Decisions to reference:** 55 (RCA-first / no budget relax), 81 (CD.33 runtime + loud-fail), 79 (per-
  Lambda V3 gating), 77 (sandbox terraform auto-apply), 78 (DuckLake adoption -- with the RDS/Neon NOTE
  above), CD.34 (Neon catalog authority); related: 48 (V3 tier), 75 (frame-lock -- the concurrency-model
  escape hatch), 70 (portal write discipline for any Decision/rec filing).
- ci-rca: preflight `ci_rca_recs` is empty -- nothing was filed from PR #87's post-merge full tier, so
  there is nothing to fold in.
- Branch was 0 commits behind `origin/main` at planning time (no Main Divergence Assessment needed).

## Phase-2 Decision Tree (executed after Phase-1 attribution in VP-12)
Apply branches in order P -> C -> O until VP-13 reports `p95_commit_ms <= 2000.0`. Branches may compound.

- **Branch P (PRIMARY -- vCPU starvation).** Trigger: per-writer `wall_ms` >> `cpu_ms`, OR the sum of
  attributed per-stage ms is far below `wall_ms` (off-CPU scheduling wait), OR connect+ATTACH dominates and
  scales with writer count. Fix: raise `ducklake_writer` `memory_size` in `ducklake_lambdas.tf` in steps
  (1024 -> 3008 -> 5308 -> up to 10240) -- each ~1769MB grants ~1 full vCPU -- re-apply + re-run VP-13
  until under budget. Lowest risk, no code rebuild for the memory change itself. Stop at the smallest step
  that meets budget.
- **Branch C (commit RTT / catalog serialization).** Trigger: `commit_ms` dominates and is NOT CPU-bound
  even after Branch P gives adequate vCPU. Fix: run the pooler transaction-safety proof (VP-16). If SAFE,
  expose `host_pooler` in the DSN secret (`neon_ducklake_catalog.tf`) and select it in `open_connection`
  via an opt-in (e.g. `DUCKLAKE_USE_POOLER`/DSN field); re-run VP-13. If UNSAFE, revert and do not adopt
  the pooler -- record the proof result and continue to Branch O.
- **Branch O (OCC backoff waste).** Trigger: `occ_retries > 0` with a large `occ_backoff_ms` share. Fix:
  tune the OCC backoff SCHEDULE (`OCC_BASE_BACKOFF_S`/`OCC_MAX_BACKOFF_S`/jitter, e.g. decorrelated jitter)
  in `ducklake_runtime.py` so contended-but-successful writes sleep less -- WITHOUT changing
  `OCC_MAX_ATTEMPTS`. Re-run VP-13.
- **SECONDARY escape hatch (concurrency-model frame challenge -- Decision 75).** Trigger: P+C+O cannot get
  the in-process 8-thread model under budget at a sane `memory_size` ceiling AND the attribution shows the
  8-threads-in-one-container model is the harness artifact (a single writer is well under budget; wall
  scales ~linearly with thread count). Action: do NOT redefine the gate inline. File a recommendation via
  `scripts.ops_data_portal` proposing a Decision that EC8 measure per-invocation latency under realistic
  production fan-out (N concurrent Function-URL *invocations*, each its own container/vCPU) rather than N
  threads in one invocation. Leave EC8 red pending human ratification of that Decision. This is a frame
  correction, not a budget relaxation -- but it changes what EC8 means, so it requires human sign-off.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `claude/ducklake-churn-latency-rca-4w85F`)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md consulted via the decision-scout gate (CITE: 55, 81, 79, 77, 78; NOTE: 78 RDS/Neon)
- [ ] All files in the Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS `agent_platform` chain verified (`aws sts get-caller-identity --profile agent_platform`)

## Ordered Execution Steps
1. **rec-2091 consolidation.** Move `COMMIT_LATENCY_BUDGET_MS`, `OCC_COLLISION_RATE_BUDGET`, `CHURN_WRITERS`,
   `CHURN_WRITES_PER_WRITER`, and the OCC collision markers into `src/common/ducklake_runtime.py` as the
   single source. Import them in `src/lambdas/ducklake_writer/handler.py` and
   `scripts/ducklake_neon_smoke_test.py`; delete the local duplicates. Run VP-1, VP-2.
2. **Phase 1 instrumentation.** In `_churn_one_writer`, capture the `WriteResult` from each `write_scd2`
   (it already returns `commit_ms` + `occ_retries`); time the `open_connection` call (connect+LOAD+ATTACH,
   split if cheaply separable); record `time.perf_counter()` wall and `time.thread_time()`/`process_time()`
   CPU per writer; sum OCC backoff. Aggregate in `action_churn` into a `breakdown` dict (per-stage p95 +
   wall-vs-cpu ratio) added to the response body, and emit the key stages to CloudWatch via the existing
   metric sink. Keep the existing `collision_rate`/`p95_commit_ms`/`within_budget` fields. Update the
   `--lambda-churn` print in the smoke test to show the breakdown.
3. **Update tests** (`tests/test_ducklake_writer_handler.py`, `tests/test_ducklake_runtime.py`,
   `tests/test_ducklake_neon_smoke_test.py`) for the relocated constants + the new breakdown dict; 100%
   coverage of new lines. Run VP-3, VP-4, VP-5.
4. **Presubmit.** Run VP-6 (`scripts.validate`); fix to green.
5. **Build + deploy (instrumentation first).** Run VP-7, VP-8, then deploy via VP-11 (and apply terraform
   VP-9/VP-10 only if a Branch-P memory change is already staged; otherwise deploy code first to capture a
   baseline attribution).
6. **Phase 1 capture.** Run VP-12; record the per-stage attribution decomposition in this plan's outcome
   notes and in `docs/SESSION_LOG.md`. Identify the dominant term.
7. **Phase 2 fix.** Follow the Decision Tree (P -> C -> O) based on the VP-12 attribution. For each branch:
   make the change, re-run pre-deploy gates (VP-3..6) if code changed, rebuild/redeploy affected
   artifact(s) (VP-8/VP-11) and re-apply terraform (VP-9/VP-10) as needed, then re-run VP-13.
8. **Full post-deploy gate sweep.** Run VP-13, VP-14, VP-15 (and VP-16 if Branch C was taken). All green.
9. **Close-out.** Close rec-2091 via `scripts.ops_data_portal` (`update_rec`). Write the SESSION_LOG
   disposition: the live attribution, the chosen fix branch(es), final p95, and an explicit note that this
   supersedes rec-2084's waived projection. If Branch C was taken, file the Decision-78 RDS/Neon amendment
   rec. If the SECONDARY escape hatch was reached, file the concurrency-model Decision rec and STOP.
10. **Execute Verification Plan** -- run every VP step. Loop until pass. If V3 cannot reach budget
    unrecoverably, stop and RCA via the SECONDARY escape hatch (Decision 55) -- do not relax the gate.
11. Report: the attribution decomposition, the fix branch(es) applied, the final EC8 p95, and the full
    8/8 gate status.
