# Plan

## Intent
Unblock the stalled T2.19 DuckLake ops cutover by root-causing why the reader/writer Lambda cannot
complete a Postgres connection to the Neon serverless catalog (today it hangs to the 120s Lambda
timeout -> 502). This is a focused, diagnostic-first unblock: it makes the failure legible, fixes the
root cause, and STOPS once in-Lambda ATTACH to Neon is proven green. The downstream sign-off tail
(DQ-over-DuckLake, the iceberg->ducklake default flip, seed removal, docs) is explicitly OUT OF SCOPE
and re-planned afterward (see Handoff).

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-neon-connect-rca.md

## Phase
Phase 2 (Platform), T2 tier, T2.19 ("DuckLake ops write/read migration"). This is the connectivity
prerequisite that gates the sign-off tail of `PLAN-ducklake-ops-finalize.md` (PHASE 2/3). It introduces
no new agent write surface and does not flip any default backend.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| src/common/ducklake_runtime.py | Modify | Add a bounded `connect_timeout` (default 10s, overridable via the `DUCKLAKE_CONNECT_TIMEOUT_S` env) to the libpq conninfo emitted by `libpq_conninfo` (line 210-217), so a connect that does not complete FAILS FAST with a precise libpq error instead of hanging to the 120s OS/Lambda wall. This is the single highest-leverage change: it converts the opaque 502-timeout into a diagnosable, logged error. Keep it a one-liner addition -- the file is 479/500 SLOC (Decision 43), so the phased probe goes in a NEW sibling module (next row), NOT here. Lambda-packaged (bundled in 4 DuckLake artifacts). |
| src/common/ducklake_connect_probe.py | Create | NEW diagnostic-only module holding `probe_connection(dsn, *, data_path, meta_schema, extension_directory, timeout_s)` -- a phased, each-phase-bounded connection diagnostic that NEVER hangs and returns a structured result: `{phase_reached, failed_phase, dns_ms, tcp_ms, auth_ms, attach_ms, ok, error}`. Phases, each with its own short timeout: (1) DNS -- `socket.getaddrinfo(host, 5432)`; (2) TCP -- raw `socket.create_connection((host, 5432), timeout=timeout_s)`; (3) AUTH -- `psycopg2.connect(..., connect_timeout=timeout_s, sslmode=require)` then close (proves credentials + Postgres reachability independent of DuckDB); (4) ATTACH -- delegate to `ducklake_runtime.open_connection(...)` + `SELECT 1`. Each phase is timed; the first to fail short-circuits and is reported as `failed_phase`. Pure-ish (only stdlib socket + psycopg2 + the runtime ATTACH); isolates the diagnostic concern and keeps `ducklake_runtime.py` under the SLOC budget (Decision 43). Lambda-packaged -- MUST be added to the 4 DuckLake manifests' `includes[]` (next rows). |
| src/lambdas/ducklake_writer/handler.py | Modify | Add a `connect_probe` action that is SPECIAL-CASED in `handler()` to run BEFORE `_open_writer_connection()` -- the normal open is what hangs today, so the probe MUST NOT depend on the pre-opened `con`. It fetches the DSN, calls `ducklake_connect_probe.probe_connection(...)` with the writer's DATA_PATH/META_SCHEMA/EXTENSION_DIRECTORY, and returns the structured phased result (200 even on a diagnosed failure -- the body carries `ok=False`+`failed_phase`; a probe that itself errors is a 5xx). Logs each phase to CloudWatch. Watch the writer handler SLOC budget; if tight, the action body is a thin delegate to the new module. |
| src/lambdas/ducklake_reader/handler.py | Modify | Same `connect_probe` action, pre-connection, read-scoped DATA_PATH/META_SCHEMA. The reader is the load-bearing path for the post-cutover recs reads, so its probe is the primary signal. |
| src/lambdas/ducklake_writer/manifest.yaml | Modify | Add `src/common/ducklake_connect_probe.py` to `includes[]` (the handler imports it; without this the bundle import-fails at runtime). |
| src/lambdas/ducklake_reader/manifest.yaml | Modify | Same `includes[]` addition. |
| src/lambdas/ducklake_maintenance/manifest.yaml | Modify | Add `src/common/ducklake_connect_probe.py` to `includes[]`. The maintenance bundle imports `ducklake_runtime` (which is byte-changed by the `connect_timeout` edit); adding the sibling keeps `--check-bundles` import-resolution green and the bundle self-consistent. (If the maintenance handler does not import the probe, this is still required only if `--check-bundles` flags a missing transitive import; VP4 is the arbiter -- add iff it flags.) |
| src/lambdas/ducklake_catalog_dr/manifest.yaml | Modify | Same: catalog_dr explicitly bundles `ducklake_runtime.py`; keep `--check-bundles` green after the runtime byte-change. Same VP4-arbiter caveat as maintenance. |
| scripts/ducklake_neon_smoke_test.py | Modify | Add a `--connect-probe` gate (driver) that SigV4-invokes the reader AND writer `connect_probe` actions over their Function URLs and prints the phased result (`CONNECT_PROBE reader=<phase> writer=<phase> ...`). This is the diagnostic-loop driver (NOT a pass/fail gate -- it reports the failing phase). Reuses `_sigv4_invoke` / `_function_url`. No change to any Decision-82 churn budget constant. |
| tests/test_ducklake_runtime.py | Modify | Assert `libpq_conninfo` includes `connect_timeout=<N>` (default 10) and honours `DUCKLAKE_CONNECT_TIMEOUT_S`. |
| tests/test_ducklake_connect_probe.py | Create | Unit-test `probe_connection`: each phase's failure is classified to the correct `failed_phase` (mock `socket.getaddrinfo`/`create_connection`/`psycopg2.connect`/`open_connection` to raise per phase); a fully-successful mock returns `ok=True, phase_reached="attach"`; assert no phase can hang (timeouts are passed through). |
| tests/test_ducklake_writer_handler.py | Modify | Assert the `connect_probe` action is dispatched WITHOUT relying on a pre-opened connection (i.e. it runs even when `_open_writer_connection` would hang -- mock it to raise/block and confirm the probe still returns), and returns the structured phased payload. |
| tests/test_ducklake_reader_handler.py | Modify | Same assertions for the reader `connect_probe`. |
| terraform/personal/neon_ducklake_catalog.tf | Modify (CONTINGENT) | ONLY if the diagnosis (VP6) shows a stale/unreachable endpoint host or a suspended/absent free-tier Neon project: re-derive/verify `database_host`, resume/recreate the Neon project/endpoint via the `neon` provider, and/or correct direct-vs-pooled host. HUMAN-GATED apply (Decision 77/35; the fail-closed guard blocks any `neon_*` update/replace/delete). NOT pre-committed -- the branch is taken only if VP6 selects it, and the exact edit is determined by the captured phase. |
| (secret) ducklake-neon-catalog-dsn | Refresh (CONTINGENT) | ONLY if VP6 shows an AUTH-phase failure (Neon role password rotated out of band) or a host correction: refresh the Secrets Manager DSN from the authoritative `terraform output` (Decision 37 runtime-fetch). Done via the terraform apply above (the secret version is Terraform-managed) -- no manual secret edit. |
| docs/SESSION_LOG.md | Modify | Session entry: the captured root-cause phase, the fix applied, the `lambda_attach` green proof, the 4 closed ci_rca recs, and the filed follow-up rec id. |

## Bundled Recommendations
- **rec-2107 + rec-2108** (ci_rca, `ducklake_runtime.py` SLOC=589 > 500): STALE -- resolved by the PHASE 0+1
  split (commit `f2e5cd9`; `ducklake_runtime.py` now 479 SLOC). Close as resolved at VP1, each `update_rec`
  citing commit `3e5152e`/`f2e5cd9` + the live SLOC fact.
- **rec-2109 + rec-2110** (ci_rca, `ops_recommendations` DQ FAIL: NULL automatable/risk + sub-80 context):
  STALE -- the offending row was remediated and the D64 anchor restored in PHASE 0+1; 0 rows currently
  violate the checks and main full-tier CI is green at `3e5152e`. Close as resolved (one may be a duplicate
  of the other -- close the later as duplicate), each `update_rec` citing the green CI run + the 0-violation fact.
- **NEW (filed at VP8):** a follow-up rec to RESUME the finalize PHASE 2/3 sign-off tail once connectivity is
  green -- carries the corrected `oidc.tf` grant spec (`lambda:InvokeFunction`, NOT the finalize plan's
  `InvokeFunctionUrl`) and the captured connectivity root-cause as context.

## Infrastructure Dependencies
| Item | Detail |
|------|--------|
| Modified resources (CONTINGENT only) | `neon_ducklake_catalog.tf` -- Neon project/endpoint/host and/or the Terraform-managed DSN secret version. Taken ONLY if VP6 diagnoses a stale host / suspended project / rotated password. No IAM change. No new Lambdas. |
| Apply posture | HUMAN-GATED via `agent_platform_admin` (Decision 77 + 35). Any `neon_*` update/replace/delete trips the fail-closed `terraform_apply_guard.py`; present `terraform plan` to the human before apply. A `neon_*` CREATE (project re-provision) returns guard exit 0 but is still presented per the terraform/CLAUDE.md plan-before-apply rule. |
| Lambda deployment (Decision 79 / CD.16) | `compute_affected_artifacts(changed_files)` over the real scope MUST be run (VP4); the `connect_timeout` edit to `src/common/ducklake_runtime.py` is bundled in FOUR active artifacts -- `ducklake_writer`, `ducklake_reader`, `ducklake_maintenance`, `ducklake_catalog_dr`. All 4 are rebuilt + deployed for byte-currency via `build_lambda --ducklake-only --deploy`. `ducklake_writer` + `ducklake_reader` ALSO gain the new `connect_probe` action + the new bundled module, and are the load-bearing smoke targets (connect_probe + lambda_attach). No model IDs touched (deterministic SQL/sockets) -> inference-provider validation N/A. |
| Egress | NO Neon 5432 from CC-web; the entire diagnostic loop is Lambda-mediated over 443 (SigV4 Function-URL invoke -> in-Lambda connect to Neon) plus CloudWatch log reads. The out-of-band Neon liveness check (VP6) uses the Neon API / `terraform -chdir=terraform/personal refresh`-style state read, also over 443. |
| Timing | VP1-4 = `[pre-deploy]`; deploy + connect_probe + diagnosis + fix + lambda_attach = `[post-deploy]`. |

## Acceptance Criteria
- [ ] main full-tier CI confirmed GREEN at `3e5152e`; the 4 STALE ci_rca recs (rec-2107/2108/2109/2110) closed via `update_rec`, each citing the resolving commit + the live SLOC/DQ evidence. No other open ci_rca rec exists (preflight HARD-BLOCK clear).
- [ ] `libpq_conninfo` emits a bounded `connect_timeout` (default 10s, `DUCKLAKE_CONNECT_TIMEOUT_S`-overridable); a non-completing connect now FAILS FAST (<~12s) with a precise libpq error instead of hanging to the 120s wall. Proven by unit test AND by the live probe returning within seconds.
- [ ] `probe_connection` (in `src/common/ducklake_connect_probe.py`) classifies a failure to the correct phase (DNS / TCP / AUTH / ATTACH), is unit-tested, and cannot hang (each phase bounded).
- [ ] The `connect_probe` action is live on the writer + reader Lambdas, runs BEFORE the normal connection open, and a SigV4 invoke returns the precise failing phase + per-phase timings (captured from the live result and CloudWatch).
- [ ] The connectivity root cause is IDENTIFIED (named phase + underlying cause) and FIXED -- not worked around. If the fix is a Neon/secret change it went through the HUMAN-GATED terraform apply (Decision 77/35).
- [ ] `lambda_attach` is GREEN: in-Lambda ATTACH to Neon succeeds (`version=1.5.3`, `source=layer`, a real connect+commit latency reported) on BOTH the writer and the reader path. This is the unblock proof.
- [ ] Per-Lambda V3 (Decision 79): the 4 DuckLake functions rebuilt + deployed for byte-currency; writer+reader smoke-tested (connect_probe + lambda_attach); maintenance + catalog_dr existing smoke green (no behavioural delta beyond the timeout one-liner).
- [ ] A follow-up rec is filed (HARD prerequisite framing) to resume the finalize PHASE 2/3 sign-off, carrying the corrected `oidc.tf` grant spec (`lambda:InvokeFunction`) and the captured root-cause; `docs/SESSION_LOG.md` updated.
- [ ] Scope boundary held: NO `_DEFAULT_OPS_STORAGE_BACKEND` flip, NO seed removal, NO `oidc.tf` edit, NO docs source-of-truth flip in THIS plan -- those remain the finalize PHASE 2/3 follow-up. Loud-fail / stop-and-RCA on any unrecoverable V3 gate (Decision 55); no threshold relaxation, no rescue loop.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm main CI green + the 4 ci_rca recs are stale, then close them via the portal | `bin/venv-python -m scripts.sloc src/common/ducklake_runtime.py` (expect <=500) then a probe that 0 open recs violate the DQ checks (NULL automatable/risk or context<80), then `update_rec` rec-2107/2108/2109/2110 closed (cite `3e5152e`) | SLOC<=500; 0 violating rows; all 4 recs CLOSED; preflight re-run shows empty `ci_rca_recs` | A rec is NOT actually resolved (e.g. a live violation reappears) -> do NOT close it; re-scope to fix the live issue first |
| 2 | [pre-deploy] | Unit-test the `connect_timeout` addition + the phased probe classification | `bin/venv-python -m pytest tests/test_ducklake_runtime.py tests/test_ducklake_connect_probe.py -q` | All pass; conninfo carries `connect_timeout=10` (and honours the env override); each mocked phase-failure classifies to the right `failed_phase`; a success path returns `ok=True phase_reached=attach` | A phase misclassifies or the timeout is absent -> fix the probe/conninfo |
| 3 | [pre-deploy] | Handler tests: `connect_probe` runs WITHOUT a pre-opened connection | `bin/venv-python -m pytest tests/test_ducklake_writer_handler.py tests/test_ducklake_reader_handler.py -q` | Both pass; with `_open_*_connection` mocked to raise/block, the `connect_probe` action STILL returns the structured phased payload (proves it is pre-connection) | The probe depends on the hung open -> move the special-case ahead of `_open_*_connection` in `handler()` |
| 4 | [pre-deploy] | Manifests validate; `--check-bundles` import-resolves the new module into the affected bundles; confirm the affected-artifact set | `bin/venv-python -m scripts.lambda_manifest --validate && bin/venv-python -m scripts.lambda_manifest --check-bundles` then `bin/venv-python -c "from scripts.lambda_manifest import compute_affected_artifacts; print(sorted(compute_affected_artifacts(['src/common/ducklake_runtime.py','src/common/ducklake_connect_probe.py','src/lambdas/ducklake_writer/handler.py','src/lambdas/ducklake_reader/handler.py'])))"` | All active artifacts validate; `ducklake_connect_probe.py` import-resolves in writer/reader (+ maintenance/catalog_dr if they import it); affected set = the 4 DuckLake functions | A bundle import-fails on the missing module -> add it to that manifest's `includes[]` (the VP4 arbiter) |
| 5 | [pre-deploy] | Full presubmit green (authoritative, CI-identical) | `bin/venv-python -m scripts.validate` | PASS incl. SLOC (`ducklake_runtime.py` still <=500 after the one-liner; the probe lives in its own module) + lint/format/tests | Any failure -> fix; if SLOC regressed, the probe logic does NOT belong in `ducklake_runtime.py` -- keep it in the sibling module |
| 6 | [post-deploy] | Deploy the 4 DuckLake functions, then SigV4-invoke `connect_probe` on reader+writer AND run the out-of-band Neon liveness check IN PARALLEL; capture the failing phase | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` then `bin/venv-python -m scripts.ducklake_neon_smoke_test --connect-probe --profile agent_platform` then read CloudWatch `/aws/lambda/agent-platform-ducklake-reader`; SEPARATELY query Neon project/endpoint state (Neon API or `terraform -chdir=terraform/personal state show 'neon_project.ducklake_catalog'` + compare `database_host` to the DSN secret's `host`) | The probe returns a NAMED `failed_phase` within seconds (no 120s hang); the Neon-state check reports whether the project/endpoint is active and whether the DSN host matches the live endpoint | The probe itself 5xx's -> the action is mis-wired (regress to VP3); if it still hangs, `connect_timeout` did not propagate into the ATTACH conninfo -> verify the DuckDB `postgres` ATTACH receives the timeout |
| 7 | [post-deploy] | Apply the diagnosis-matched fix (decision tree), then re-probe. LOUD-FAIL if no branch matches (Decision 55) | DNS/TCP fail + host mismatch OR project suspended/absent -> re-derive/resume/recreate via `neon_ducklake_catalog.tf` + refresh the DSN secret, HUMAN-GATED `terraform -chdir=terraform/personal apply` after plan review; pooled-vs-direct mismatch -> correct `database_host` to the DIRECT endpoint (Decision 82); AUTH fail -> refresh the Terraform-managed DSN secret from `terraform output`; then re-run `--connect-probe` | The previously-failing phase now passes; the probe reaches `phase_reached=attach ok=True` | No branch matches the captured phase -> STOP and RCA (Decision 55); do NOT relax a timeout or add a retry-until-pass loop to mask it |
| 8 | [post-deploy] | The unblock proof: in-Lambda ATTACH green on writer AND reader; then file the follow-up rec + SESSION_LOG | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-attach --profile agent_platform` (writer) and `--lambda-reader` (reader read path) then `file_rec(...)` the resume-sign-off follow-up + edit `docs/SESSION_LOG.md` | `LAMBDA_ATTACH OK version=1.5.3 source=layer connect_ms=... commit_ms=...`; reader path green; follow-up rec filed with the corrected `lambda:InvokeFunction` oidc spec + root-cause; SESSION_LOG updated | ATTACH still fails -> the VP7 fix was incomplete; re-capture the phase (VP6) and re-branch; portal unreachable -> outbox + retry (Decision 51) |

## Constraints
- **RCA-first, loud-fail (Decision 55).** The probe makes the failure LEGIBLE; the fix addresses the named
  root cause. A failing phase with no matching branch STOPS the work -- never relax `connect_timeout`, never
  add a retry-until-it-passes loop, never widen a threshold to mask the hang.
- **Decision 43 SLOC budget.** `ducklake_runtime.py` is 479/500; the `connect_timeout` change is a one-liner
  and the phased probe lives in `src/common/ducklake_connect_probe.py`. Do NOT add a `# complexity-waiver`;
  if runtime approaches 500, move logic OUT to the sibling module.
- **Closed boundary preserved (Decision 81 / CD.33).** No new ops write surface; the probe is a diagnostic
  read of the connection path. The reader stays read-scoped, the writer write-scoped.
- **Per-Lambda V3 (Decision 79 / CD.16).** Derive the deploy set from `compute_affected_artifacts` (VP4),
  not by assertion; all 4 byte-affected DuckLake functions rebuilt + deployed; writer+reader smoke-tested.
- **Terraform apply HUMAN-GATED (Decision 77 + 35).** The CONTINGENT Neon/secret fix routes through
  `agent_platform_admin` with a presented `terraform plan`; the fail-closed guard blocks any `neon_*`
  update/replace/delete. Decision 77 (not bare 35) is the controlling clause for the sandbox posture.
- **ci_rca recs closed via the portal, evidence-backed (Decision 72/73).** Closure is lifecycle resolution
  (CI already green), NOT an inline CI patch; each `update_rec` cites the resolving commit + the live fact.
- **Single-Portal (Decision 78/81).** All rec writes transit `ops_data_portal` (`update_rec`/`file_rec`);
  the only direct file edit is `docs/SESSION_LOG.md` (markdown ETL source, never `logs/.recommendations-log.jsonl`).
- **Runtime DSN fetch (Decision 37).** Any secret refresh is Terraform-managed + runtime-fetched; no manual
  secret edit and no DSN committed to the repo.
- **Scope boundary.** NO backend-default flip, NO seed removal, NO `oidc.tf` edit, NO docs SoT flip here --
  those are the finalize PHASE 2/3 follow-up (Handoff). Telemetry + other ops tables out of scope.
- No emojis; ASCII hyphens; ruff line length 127; type hints; `bin/venv-python` for all Python.

## Context
- **Why this plan exists:** `PLAN-ducklake-ops-finalize.md` landed PHASE 0+1 (CI-green: SCD2 split ->
  `ducklake_runtime.py` 479 SLOC, `--pre` SLOC gate, D64 DQ anchor) and the PlatformDev
  `lambda:InvokeFunction` IAM fix (commits `f2e5cd9`, `3e5152e`; PRs #108/#109). main full-tier CI is GREEN.
  But the finalize PHASE 2/3 sign-off tail (DQ-over-DuckLake, rollback rehearsal, the 3-site default flip,
  seed removal) ALL require a live reader/writer round-trip to Neon -- and that round-trip currently hangs
  to the 120s timeout. This plan is the connectivity prerequisite the finalize tail sits behind.
- **The diagnosis gap (the cold-start question):** the hang is NOT explained by Neon scale-to-zero
  cold-resume. The runtime already budgets cold-resume at ~18s (`lambda_attach` EC1) and pre-warms for it
  (the churn gate). A 120s hang that persists across repeated attempts and two IAM roles does not fit
  resume latency (which self-resolves after the first wake). The proximate cause of the OPACITY is that
  `libpq_conninfo` (`ducklake_runtime.py:210-217`) sets NO `connect_timeout`, so libpq blocks on the
  handshake to the OS/Lambda wall -- making DNS, TCP-blackhole, TLS, and Postgres-auth failures all look
  identical. The previous agent never saw the real failure. Likeliest true causes (UNPROVEN until VP6): a
  stale/unreachable Neon endpoint host in the DSN, a suspended/absent free-tier Neon project, or a
  pooled-vs-direct host mismatch.
- **Handler hang constraint:** `handler()` opens the connection BEFORE dispatching the action
  (reader `handler.py:167`, writer analogous), so a `connect_probe` that uses the pre-opened `con` would
  itself hang. The probe MUST be special-cased ahead of `_open_*_connection()` -- VP3 enforces this.
- **The 4 ci_rca recs are stale:** filed against the earlier RED runs (`d1b4214`, `e2047ef`) before the
  split + anchor fix merged. rec-2107/2108 (SLOC=589) are moot (now 479); rec-2109/2110 (DQ FAIL) are moot
  (0 violating rows, CI green). They are open bookkeeping; VP1 closes them with evidence. The preflight
  HARD BLOCK is satisfied on same-file (`ducklake_runtime.py`) + same-category (SLOC / DQ).
- **Decision-scout verdict: FLAGS_FOUND** (2 NOTE flags, both folded, no pivot):
  - D72/73 (ci_rca governance) -- closure is evidence-backed lifecycle resolution (CI green at `3e5152e`),
    not an inline patch; each `update_rec` cites the resolving commit. Confirm no OTHER open ci_rca rec.
  - D78/81 Single-Portal -- all rec writes via the portal; SESSION_LOG is the only direct file edit (md ETL
    source, not a warehouse read-cache). Already compliant.
- **Decisions cited:** 55 (RCA-first / loud-fail, no rescue loop), 81 + CD.33 (closed boundary + the
  ducklake runtime being unblocked), 79 + CD.16 (per-Lambda affected-set + deploy), 77 + 35 (human-gated
  terraform apply; 77 controls the sandbox posture), 48 (V3 tier + behavioural acceptance), 37 (runtime DSN
  fetch / Terraform-managed secret), 72 + 73 (ci_rca via /plan, evidence-backed closure, no inline patch),
  82 (DIRECT-vs-pooled Neon endpoint facts for the pooled-mismatch branch), 43 (500-SLOC budget on
  `ducklake_runtime.py`), 34 / CD.34 (Neon free-tier catalog posture: no IP-allow-list, sslmode=require,
  scale-to-zero). NOTE: the authoritative Neon posture is CD.34 (a warehouse decision); confirm it via the
  warehouse if the VP7 project-recreation branch is reached.
- **Preflight:** branch `claude/ducklake-unblock-plan-n3nlec`; 0 commits behind `origin/main` (no Main
  Divergence -- no Scope file overlaps `main_files_changed_since_branch`). 4 open ci_rca recs (stale; closed
  at VP1). No Neon 5432 egress from CC-web -- the whole loop is Lambda-mediated over 443.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`claude/ducklake-unblock-plan-n3nlec`)
- [ ] `docs/PROJECT_CONTEXT.md` + DECISIONS.md (55, 81, 79, 77, 35, 48, 37, 72, 73, 82, 43, 34) read
- [ ] `PLAN-ducklake-ops-finalize.md` read (the tail this plan unblocks; the `InvokeFunctionUrl` -> `InvokeFunction` correction)
- [ ] Scope files located + readable (runtime, the new probe module, writer/reader handlers + manifests, the smoke driver, the tests)
- [ ] Confirmed via preflight that rec-2107/2108/2109/2110 are the ONLY open ci_rca recs (HARD-BLOCK clear before closing them)
- [ ] `compute_affected_artifacts(changed_files)` run -- confirm the 4 DuckLake functions are the affected active artifacts
- [ ] Reader/writer Function-URL invoke confirmed reachable under the `agent_platform` role over 443 (SigV4)

## Ordered Execution Steps
1. **VP1 -- close the stale ci_rca recs.** Confirm `ducklake_runtime.py` <=500 SLOC and 0 `ops_recommendations`
   rows violate the DQ checks; `update_rec` rec-2107/2108/2109/2110 to closed, each citing commit `3e5152e`
   (+ `f2e5cd9`) and the live SLOC/DQ evidence (close the duplicate as duplicate). Re-run preflight; confirm
   `ci_rca_recs` is empty.
2. **`src/common/ducklake_runtime.py`** -- add the bounded `connect_timeout` (default 10s,
   `DUCKLAKE_CONNECT_TIMEOUT_S`-overridable) to `libpq_conninfo`. Keep it a one-liner; confirm SLOC still <=500.
3. **`src/common/ducklake_connect_probe.py`** -- create the phased `probe_connection` diagnostic (DNS -> TCP ->
   AUTH -> ATTACH, each bounded, first-failure short-circuits, structured result). Pure delegate to
   `ducklake_runtime.open_connection` for the ATTACH phase.
4. **Writer + reader handlers** -- add the `connect_probe` action SPECIAL-CASED ahead of
   `_open_*_connection()` in `handler()`; thin delegate to the probe module; log each phase to CloudWatch.
5. **Manifests** -- add `src/common/ducklake_connect_probe.py` to `includes[]` for writer + reader (and
   maintenance/catalog_dr iff `--check-bundles` flags a missing import at VP4).
6. **Smoke driver** -- add the `--connect-probe` gate to `scripts/ducklake_neon_smoke_test.py` (SigV4-invoke
   reader+writer `connect_probe`, print the phased result). No churn-budget constant touched.
7. **Tests** -- create `tests/test_ducklake_connect_probe.py`; update `tests/test_ducklake_runtime.py`
   (conninfo timeout) and the writer/reader handler tests (probe runs pre-connection).
8. **Run VP1-5; full presubmit green** (`bin/venv-python -m scripts.validate`).
9. **VP6 -- deploy + capture.** `build_lambda --ducklake-only --deploy` (4 DuckLake functions); SigV4-invoke
   `--connect-probe`; read the reader CloudWatch log; IN PARALLEL run the out-of-band Neon liveness check
   (Neon API / terraform state `database_host` vs the DSN secret `host`). Record the named `failed_phase`.
10. **VP7 -- fix the named root cause** via the decision tree (host re-derive/resume/recreate +
    secret refresh -> HUMAN-GATED `terraform -chdir=terraform/personal apply` after plan review; pooled->direct
    host correction; or AUTH-secret refresh). LOUD-FAIL + STOP-and-RCA if no branch matches (Decision 55).
    Re-run `--connect-probe` until it reaches `phase_reached=attach ok=True`.
11. **VP8 -- prove the unblock.** `--lambda-attach` (writer) + `--lambda-reader` (reader) GREEN. File the
    follow-up rec (resume finalize PHASE 2/3; corrected `lambda:InvokeFunction` oidc spec + captured
    root-cause). Update `docs/SESSION_LOG.md`.
12. **Execute Verification Plan** -- run each step in order. Loop until pass. If a V3 gate fails unrecoverably,
    stop and analyze root cause (Decision 55) -- do not relax a threshold or add a rescue loop.
13. **Report:** the captured root-cause phase + underlying cause, the fix applied (incl. any human-gated
    terraform apply), the `lambda_attach` green proof (writer+reader), the 4 closed ci_rca recs, the filed
    follow-up rec id, and the explicit OUT-OF-SCOPE list (the finalize PHASE 2/3 sign-off tail).

## Handoff (next plan, OUT OF SCOPE here)
Once `lambda_attach` is green, resume `PLAN-ducklake-ops-finalize.md` PHASE 2/3 -- with ONE correction
carried by the VP8 follow-up rec: the `github_ci` `oidc.tf` grant MUST be `lambda:InvokeFunction` (NOT the
finalize plan's `lambda:InvokeFunctionUrl`; the Function-URL IAM authorizer checks `InvokeFunction`, proven
live in the IAM-fix session). Remaining finalize tail: VP12 (DQ over DuckLake), VP13 (rollback rehearsal),
VP14 (the 3-site `_DEFAULT_OPS_STORAGE_BACKEND` flip + `--selftest-roundtrip`), VP15 (seed removal + close
rec-2099), the docs source-of-truth flip, and the VP11 restore-drill follow-up/bookkeeping.
