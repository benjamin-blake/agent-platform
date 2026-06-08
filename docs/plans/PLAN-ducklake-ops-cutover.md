# Plan

## Intent
Cut the live operational persistence layer over from Iceberg/Athena to DuckLake-on-Neon (T2.19), so every
ops read/write transits the closed DuckLake reader/writer boundary while the Decision-69 Single-Portal
caller surface stays unchanged. This completes the DuckLake operational lakehouse and closes the remaining
T2.18 tail (ops_compaction retirement, pg_restore DR drill, co-tuning numbers) -- the persistence substrate
the self-improving feedback loop depends on.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-ops-cutover.md

## Phase
Phase 2 (Platform) -- T2 tier, DuckLake operational lakehouse. Tier item T2.19 ("DuckLake ops write/read
migration"), depends_on [T2.16, T2.17, T2.18]. T2.16/T2.17 complete; **T2.18 is `in_progress`** -- its
remaining exit criteria (ops_compaction retirement, restore drill, co-tuning numbers) are intrinsically
T2.19-cutover actions, so this plan is the explicit continuation that CLOSES T2.18's tail. (Dependency
nuance recorded per the human-directed `user_explicit_out_of_scope` continuation.)

## Migration strategy
**BIG-BANG cutover + documented rollback** (human-chosen; phased dual-write/shadow-read explicitly NOT
used). Safety is provided by: (a) exhaustive backfill + parity verification BEFORE the cutover commit;
(b) a transport feature-flag (`OPS_STORAGE_BACKEND=iceberg|ducklake`) that flips the live path in one
step and reverts in one step; (c) Iceberg + ops_compaction left FULLY INTACT until cutover sign-off, so
rollback is real; (d) the Decision-82 churn/OCC gate, a `pg_restore` DR restore drill, read-your-write,
and DQ all run as sign-off gates BEFORE Iceberg is retired. ops_compaction retirement is the LAST step,
strictly AFTER sign-off (Decision 78 clause 7).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| config/lambda/ducklake/field_semantics.yaml | Modify | Extend the SCD2 field-semantics contract from a single smoke `fields` map to **per-table** `ops_*` schemas (ops_recommendations, ops_decisions, ops_execution_plans, ops_session_log, ops_priority_queue): per-table column maps, types, input/derived roles, partition transforms. Single source of truth for both the write-time schema gate AND the DDL. |
| src/common/ducklake_runtime.py | Modify | Generalize `create_scd2_tables` / `write_scd2` / `read_current` / `schema_gate` / the MERGE SQL + `_SCD2_COLUMNS` + `SMOKE_*` table constants from smoke-table-hardcoded to **table-parameterized** (driven by per-table field_semantics). **Extend `_PY_TYPE_FOR_SQL`** beyond the current `{VARCHAR, TIMESTAMP}` to the real ops column types (arrays e.g. `tags`/`dependencies`/`related_decisions`, ints e.g. `decision_id`, booleans e.g. `automatable`). Keep smoke constants + signatures as back-compat defaults (T2.17 smoke gates must still pass). Mint-once-outside-OCC preserved (CD.33 cl.2). |
| src/lambdas/ducklake_writer/handler.py | Modify | Add production actions `write_ops` (INSERT history + MERGE current, schema-gated, bounded OCC = OQ.10) and `update_ops` (in-transaction referential existence check before MERGE -- loud-fail if the rec is absent, CD.33 clause 8 / D-5). The writer becomes the SOLE write authority for `ops_*` (CD.33 clause 4). Remove the T2.17 "do NOT wire ops_* here" deferral note. |
| src/lambdas/ducklake_reader/handler.py | Modify | Add production read actions `read_ops_current` / `read_ops_history` / `query_ops` implementing the `Reader` protocol semantics (current_state / query / latest_snapshot) over the real `ops_*` tables. Sole read authority (closed boundary). |
| scripts/ops_data_portal.py | Modify | Swap `file_rec` / `update_rec` / `file_decision` / `update_decision` transport from `OpsWriter().write()` (Iceberg) to invoking the `ducklake_writer` Function URL (SigV4). Preserve the **caller surface** verbatim (Decision 78 cl.6 / Decision 81 cl.4 -- Single-Portal invariant) + DynamoDB ID allocation. **`sync` is NOT byte-for-byte preserved**: under DuckLake the atomic catalog commit eliminates the outbox/drain/compact category (Decision 81 cl.4), so `sync` becomes a cache-pull-from-DuckLake (the Iceberg compact + `_refresh_view` + outbox-drain internals retire). **`update_rec` referential change:** the in-transaction existence check (CD.33 cl.8 / D-5) replaces today's permissive `existing or {}` upsert-on-absent -- an absent rec now loud-fails. Gate transport on `OPS_STORAGE_BACKEND` (rollback flag). Reads route via the DuckLake reader. Add `--selftest-read` / `--selftest-roundtrip` CLI subcommands (used by VP14/15: a flag-selected read / write+read round-trip against the active backend). |
| src/common/iceberg_reader.py | Modify | Add a `DuckLakeReader` implementing the `Reader` protocol over the `ducklake_reader` Function URL; select via the same `OPS_STORAGE_BACKEND` flag. Keep `DuckDBIcebergReader` intact as the rollback target until sign-off. |
| scripts/sync_ops.py | Modify | Rebuild the local read-cache from **DuckLake** (via the reader) instead of Athena/Iceberg. The cache stays a derivative projection (warehouse-as-source-of-truth invariant preserved, substrate swapped). |
| scripts/session_preflight.py | Modify | Point the preflight rec/queue reads at the DuckLake reader (behind the flag). |
| scripts/migrate_ops_iceberg_to_ducklake.py | Create | One-time backfill: read every live Iceberg `ops_*` row -> write into DuckLake via the generalized runtime, EXCLUDING Decision-70 physically-deleted bootstrap rows. Parity verification (per-table row count + content hash of `current`); loud-fail on any mismatch (Decision 55). **Idempotent by RE-CREATE, not append:** a re-run DROPs + recreates the DuckLake `ops_*` tables before reloading, so a failed-mid-sequence run never leaves a half-populated catalog that a later run appends onto (lakehouse resurrection-loop guard). |
| config/agent/data_quality/ops.yaml | Modify | Re-point the ops DQ backend from Athena (`athena_workgroup` / `view_suffix: _current`) to **DuckLake**. Add the CD.33-clause-8 checks: ULID uniqueness on history, `_current` uniqueness via the current MERGE key on `rec_id`/`id`, referential integrity. Preserve the Decision-64 `exclude_before: '2026-05-01'` anchor. |
| scripts/data_quality_runner.py | Modify | **Dual-backend dispatch:** compile the ops-table checks to **DuckDB dialect** against the DuckLake `current` TABLE (not the Athena `_current` view; Trino idioms like `date_diff('hour', ...)` must become DuckDB equivalents) via the reader; telemetry-table checks stay on Athena this slice. Not a one-line backend swap -- a real per-backend compilation path. |
| terraform/personal/ducklake_lambdas.tf | Modify | Widen the writer/reader exec-role IAM + `DUCKLAKE_DATA_PATH` from the smoke prefix to the production `ducklake/` data path + the `ops_*` S3 prefixes (writer: RW; reader: read-only). Closed boundary enforced at IAM. HUMAN-GATED (IAM). |
| terraform/scheduled_agents.tf | Modify | **Post-sign-off only:** retire `ops_compaction` -- disable its EventBridge schedule + S3-trigger and remove/repurpose the function. Sequenced strictly AFTER cutover sign-off (Decision 78 cl.7); Iceberg + ops_compaction stay live until then for rollback. |
| src/data/handlers/ops_compaction_handler.py | Modify | Post-sign-off: flip the deprecation marker to retired (or reduce to a stub). No change until sign-off. |
| src/lambdas/ops-compaction/manifest.yaml | Modify | Post-sign-off: `status: retired`/stub. |
| src/common/catalog_dr.py | Modify | Add a `pg_restore` restore helper (the FP-B dumps are `--format=custom`; the T2.16b drill used plain-SQL `psql`). Used by the restore-drill VP gate. |
| scripts/ducklake_neon_smoke_test.py | Modify | Add production gates: `--ops-read-your-write` (write via writer -> read via reader, same value), `--ops-churn-regate` (Decision-82 churn/OCC at production scope: CHURN_WRITERS=4, budgets 2000ms / 0.20, per-invocation wall), `--catalog-restore-drill` (pg_dump -> pg_restore into a scratch catalog -> read-your-write). |
| tests/test_ducklake_runtime.py | Modify | Table-parameterized write/read/gate tests for the `ops_*` schemas (mocked connection; real code paths). |
| tests/test_ops_data_portal.py | Modify | Transport-swap + flag tests: caller surface unchanged; `ducklake` backend invokes the writer; `iceberg` backend still works (rollback); ID allocation preserved; **assert the permissive `update_rec` upsert-on-absent path is GONE** (absent rec -> loud-fail, not silent create); `--selftest-read`/`--selftest-roundtrip` subcommands work. |
| tests/test_ops_migration.py | Create | Backfill parity + Decision-70 exclusion + idempotency tests (mocked readers/writers). |
| AGENTS.md | Modify | Update the "Warehouse-as-source-of-truth invariant" + "Operational data governance" sections: DuckLake-on-Neon is the source of truth (not Athena/Iceberg); read-cache rebuilt from DuckLake; `update_rec` connectivity = Neon catalog (Secrets Manager DSN), not Athena; break-glass = audited PlatformAdmin on Neon+S3 (no Athena escape hatch). Lands ATOMICALLY with the cutover. |
| docs/PROJECT_CONTEXT.md | Modify | Update the storage-architecture / source-of-truth / escape-hatch sections to the DuckLake end-state. |
| docs/runbooks/ducklake-catalog-operations.md | Modify | Add the cutover runbook, the rollback procedure (flip `OPS_STORAGE_BACKEND`), the pg_restore restore-drill, and the closed-boundary/break-glass operating notes. |
| docs/ROADMAP-PLATFORM.yaml | Modify | Mark T2.19 `complete`; mark T2.18 `complete` (its tail closed by this plan); record OQ.7/OQ.10 resolutions as enacted. |
| docs/SESSION_LOG.md | Modify | Session entry. |

## Bundled Recommendations
None. (Open recs at preflight: 359 open / 303 non-automatable -- soft-cap breached, informational under Decision 73; none specific to the ops cutover. ci_rca=0.)

## Infrastructure Dependencies
| Item | Detail |
|------|--------|
| Modified resources | Writer/reader exec-role IAM widened to the production `ducklake/` data path + `ops_*` prefixes (writer RW, reader read-only); `DUCKLAKE_DATA_PATH` env flipped smoke -> production on both. Post-sign-off: `ops_compaction` EventBridge rule + S3 notification + function removed/disabled. |
| Apply posture | **HUMAN-GATED** via `agent_platform_admin` (Decision 35 + 77). The IAM widening + the ops_compaction destroy both trip the deterministic fail-closed guard -> manual admin path, NOT push-to-main auto-apply. |
| IAM precedence | IAM widening applied BEFORE the writer/reader code deploy (terraform CLAUDE.md). The ops_compaction destroy applies AFTER cutover sign-off. |
| Lambda deployment (CD.16 / Decision 79) | `ducklake_writer` + `ducklake_reader` are MODIFIED active artifacts -> per-Lambda V3 build + deploy + smoke-test each. No new layer build (reuse ducklake-deps/extensions). No model IDs touched (deterministic SQL, no LLM) -> inference-provider validation N/A. |
| Timing | Schema/runtime/backfill/DQ = `[pre-deploy]`. IAM apply + writer/reader deploy = `[pre-deploy]` (apply) / `[post-deploy]` (deploy). Cutover sign-off gates (churn, restore-drill, read-your-write, DQ) = `[post-deploy]`. ops_compaction retirement = `[post-deploy]`, post-sign-off. |

## Acceptance Criteria
- [ ] All ops writes go through the DuckLake writer via `ops_data_portal`; the portal **caller surface** (`file_rec`/`update_rec`/`file_decision`/`update_decision`/`sync` signatures) is unchanged (Decision 78 cl.6 / Decision 81 cl.4 -- Single-Portal invariant, transport swapped). `sync` internals are re-pointed: cache-pull from DuckLake; the Iceberg outbox-drain/compact category retires (Decision 81 cl.4). `update_rec` on an absent rec now loud-fails (referential, CD.33 cl.8) -- the prior permissive upsert-on-absent path is removed.
- [ ] `DuckDBIcebergReader` is replaced by `DuckLakeReader` for all operational read paths (portal, sync_ops, preflight); `DuckDBIcebergReader` retained only as the rollback target until sign-off.
- [ ] SCD2 reproduced in DuckLake for the `ops_*` tables: `current` write-through projection + append `history`; each write is one DuckLake txn (INSERT history + MERGE current from the in-hand delta); read-your-write verified in the smoke gate (CD.33 clause 7 / R-4 / C-1).
- [ ] **OQ.7 resolved as a CLOSED boundary** (Decision 81 cl.7): every ops read transits `ducklake_reader`, every write `ducklake_writer`; NO out-of-band access and **NO Athena escape hatch**; the only break-glass is the audited PlatformAdmin principal reading the Neon catalog credential (Secrets Manager) + S3, plus catalog-DR PITR export.
- [ ] OQ.10 resolved: writer concurrency = bounded application-level OCC retry (backoff+jitter, loud-fail on exhaustion) in the writer; reserved-concurrency=1 and SQS FIFO explicitly rejected as over-serialising (CD.33 clause 2). Verified by the Decision-82 churn re-gate at production scope.
- [ ] `ducklake_writer` owns the schema-enforcement gate; no write path bypasses it (CD.33 clause 4). Two-layer DQ: (L1) write-time schema gate + structural SCD2/idempotency + in-transaction `update_rec` referential check; (L2) batch DQ checks (ULID-history uniqueness, `_current` uniqueness, referential, recency, Decision-64 anchor) read from DuckLake and gating CI.
- [ ] Backfill complete + parity-verified: per-table Iceberg-vs-DuckLake `_current` row counts + content match (excluding Decision-70 physically-deleted rows); a parity failure loud-fails and blocks cutover (Decision 55).
- [ ] Catalog-DR restore drilled: a catalog rebuilt from the daily S3 `pg_dump` via `pg_restore` (version-matched to the pinned engine) passes read-your-write BEFORE cutover sign-off (CD.33 O-2 as amended by CD.34).
- [ ] Connection-churn / OCC-commit-latency headroom re-validated against production-shaped concurrency at cutover (Decision 82: CHURN_WRITERS=4, 2000ms / 0.20 budgets, per-invocation wall -- no relaxation to commit_ms).
- [ ] Rollback proven: flipping `OPS_STORAGE_BACKEND` back to `iceberg` restores the Iceberg path with Iceberg + ops_compaction still intact (tested before sign-off).
- [ ] Agent instructions updated atomically with cutover: `AGENTS.md` + `docs/PROJECT_CONTEXT.md` describe DuckLake-on-Neon as source of truth, the closed boundary/break-glass, and the Neon (not Athena) connectivity for `update_rec`.
- [ ] Per-Lambda V3 build + deploy + smoke-test pass for `ducklake_writer` and `ducklake_reader` (Decision 79).
- [ ] ops_compaction retired (schedule + trigger + function removed) ONLY after sign-off; T2.19 marked complete and T2.18 marked complete (tail closed).
- [ ] **Scope boundary:** this plan migrates the five `ops_*` tables. Telemetry-table migration is tracked separately (Decision 78 cl.2) and is OUT of scope; "co-tuning numbers" here = recomputing the maintenance breaker/merge thresholds for the now-live ops write rate, not telemetry migration. The dormant executor write paths (ops_execution_plans, ops_priority_queue -- executor paused per CD.17) are schema-ready in the generalized writer and route through it when the executor resumes.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit-test table-parameterized runtime (write/read/gate over ops_* schemas) + smoke back-compat | `bin/venv-python -m pytest tests/test_ducklake_runtime.py -q` | All pass; smoke-table T2.17 paths still green; ops_* schemas write/read/gate correctly | A smoke path regressed or an ops schema mismatches field_semantics -> fix the parameterization |
| 2 | [pre-deploy] | Unit-test portal transport swap + rollback flag + outbox/ID preservation | `bin/venv-python -m pytest tests/test_ops_data_portal.py -q` | Portal surface unchanged; `ducklake` backend invokes the writer; `iceberg` backend intact; outbox/ID alloc preserved | Surface drift / flag not honoured -> fix |
| 3 | [pre-deploy] | Unit-test backfill parity + Decision-70 exclusion + idempotency | `bin/venv-python -m pytest tests/test_ops_migration.py -q` | Parity comparator catches an injected mismatch; D70 rows excluded; re-run is idempotent | Comparator misses a mismatch -> strengthen before any real backfill |
| 4 | [pre-deploy] | Validate writer/reader manifests + bundles + affected-artifact set | `bin/venv-python -m scripts.lambda_manifest --validate && bin/venv-python -m scripts.lambda_manifest --check-bundles` | writer + reader validate + bundle (field_semantics ops schemas included) | Missing include (e.g. field_semantics) -> add to manifest |
| 5 | [pre-deploy] | Full presubmit (lint/format/tests/prompts/schema/DQ) | `bin/venv-python -m scripts.validate` | PASS (CI-identical) | Any failure -> fix; CI is authoritative |
| 6 | [pre-deploy] | Build writer + reader zips (writer+reader only; confirm maintenance is NOT redeployed with stale config) | `bin/venv-python -m scripts.build_lambda --ducklake-only` | writer + reader zips built + uploaded; ducklake_maintenance package unchanged from FP-B (verify its zip hash/LastModified is untouched) | Build error -> fix; if `--ducklake-only` would redeploy maintenance, scope the build to writer+reader |
| 7 | [pre-deploy] | HUMAN-GATED IAM apply (writer/reader prod data-path + ops_* prefixes) | `terraform -chdir=terraform/personal apply` (via `agent_platform_admin`, after plan review) | Writer RW + reader read-only on production `ducklake/` + `ops_*`; no destroys (ops_compaction untouched yet); present plan to human | Unexpected destroy -> stop (D77 guard) |
| 8 | [post-deploy] | Deploy writer + reader code (writer+reader only, not maintenance) | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` | writer + reader code updated from S3; maintenance function untouched | Deploy error -> check function map; maintenance redeployed -> scope `--deploy` to writer+reader |
| 9 | [post-deploy] | Drain + assert the Iceberg outbox EMPTY before backfill (so pending offline writes are captured), then create the ops_* DuckLake tables (re-create) + backfill + verify parity | `bin/venv-python -m scripts.ops_data_portal --sync && find logs/.ops-outbox -type f \| grep -q . && echo "OUTBOX NOT EMPTY -- STOP" || bin/venv-python -m scripts.migrate_ops_iceberg_to_ducklake --execute --verify-parity` | Outbox empty (all pending writes drained to Iceberg first); per-table `current` row count + content match (excl. D70); `parity=PASS` | Outbox not empty -> drain to Iceberg before backfill; Parity FAIL -> STOP, RCA (Decision 55), re-run re-creates tables (no append) |
| 10 | [post-deploy] | Catalog-DR restore drill (pg_restore the custom-format dump into a scratch catalog; read-your-write) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --catalog-restore-drill` | Restore succeeds; read-your-write on the restored catalog passes; engine version matches | Restore fails / version mismatch -> fix pg_restore path before sign-off |
| 11 | [post-deploy] | Production read-your-write through the closed boundary (write via writer, read via reader) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-read-your-write` | Value written via `write_ops` is returned by `read_ops_current`; update via `update_ops` reflected; absent-rec `update_ops` loud-fails (referential) | Read-your-write fails / referential not enforced -> fix writer/reader |
| 12 | [post-deploy] | Decision-82 churn/OCC re-gate at production scope | `bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-churn-regate` | collision_rate <= 0.20 AND p95 per-invocation wall <= 2000ms (no relaxation to commit_ms) | Over budget -> RCA (do NOT relax the budget, Decision 82/55) |
| 13 | [post-deploy] | DQ runner over DuckLake ops tables (two-layer L2 backstop) | `bin/venv-python -m scripts.data_quality_runner && bin/venv-python -c "import json;d=json.load(open('logs/debug/dq-latest.json'));print(d['verdict'])"` | `PASS`; clause-8 checks (ULID-history uniq, `_current` uniq, referential) present + green; D64 anchor honoured | Any DQ failure -> RCA; cutover blocked until PASS |
| 14 | [post-deploy] | Rollback rehearsal: flip to iceberg, confirm Iceberg path live, flip back (uses the new `--selftest-read` subcommand added to the portal) | `OPS_STORAGE_BACKEND=iceberg bin/venv-python -m scripts.ops_data_portal --selftest-read && OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-read` | Both backends serve reads; Iceberg + ops_compaction confirmed intact | Rollback path broken -> fix BEFORE sign-off (rollback is the big-bang safety net) |
| 15 | [post-deploy] | CUTOVER SIGN-OFF: re-assert outbox empty (no in-flight writes since backfill), then flip `OPS_STORAGE_BACKEND` default to `ducklake` + end-to-end portal write+read on DuckLake (new `--selftest-roundtrip` subcommand) | `find logs/.ops-outbox -type f \| grep -q . && echo "IN-FLIGHT WRITES -- re-backfill" \|\| bin/venv-python -m scripts.ops_data_portal --selftest-roundtrip` | Outbox still empty (operating assumption: no concurrent ops writes during the cutover window); a `file_rec`-shaped write lands in DuckLake and reads back via the portal; no Iceberg write occurs | Outbox non-empty -> re-run VP9 incremental re-parity; roundtrip fails -> revert the default flag; RCA |
| 16 | [post-deploy] | POST-SIGN-OFF: retire ops_compaction (apply the destroy) + confirm gone | `terraform -chdir=terraform/personal apply` (admin) then `aws lambda get-function --function-name agent-platform-ops-compaction --profile agent_platform 2>&1 \| grep -q ResourceNotFound && echo RETIRED` | ops_compaction schedule+trigger+function removed; `RETIRED` printed | Still present -> complete the destroy (only after 9-15 all green) |
| 17 | [post-deploy] | Confirm Single-Portal closed boundary: no residual Iceberg write path | `bin/venv-python -m scripts.validate` + `grep -rn "OpsWriter().write" scripts/ src/ \| grep -v test` | validate PASS; no live `OpsWriter().write` ops call sites remain (only the flagged rollback shim, if retained) | A bypass remains -> route it through the writer |

## Constraints
- No rescue agents or workaround loops (Decision 55). A backfill parity failure, a DQ failure, a churn-budget breach, or a failed restore drill STOPS the cutover -- do not relax a budget/threshold or skip a gate to proceed.
- Single-Portal invariant (Decision 78 cl.6 / Decision 81 cl.4): the portal caller surface MUST NOT change. Only the transport underneath swaps. No new write path may bypass `ops_data_portal` / the writer.
- Closed boundary (Decision 81 cl.7): no Athena escape hatch; break-glass = audited PlatformAdmin on Neon+S3 only.
- Decision 82 churn gate measured per-invocation wall, CHURN_WRITERS=4, budgets 2000ms / 0.20 -- no implicit relaxation to commit_ms.
- ops_compaction stays live until cutover sign-off (Decision 78 cl.7); its retirement is the final, post-sign-off step. Iceberg data is retained (not deleted) until sign-off so rollback is real.
- **Cutover-window operating assumption:** no concurrent ops writes during the window between the parity backfill (VP9) and the sign-off flip (VP15). Enforced by draining + asserting the outbox empty before backfill and re-asserting it empty immediately before the flip; a non-empty outbox at VP15 forces an incremental re-parity before proceeding. (Sole-developer sandbox -- a hard write-freeze is unnecessary, but the assumption is explicit and gate-checked.)
- Backfill MUST exclude Decision-70 physically-deleted bootstrap rows; DQ MUST preserve the Decision-64 `2026-05-01` anchor.
- DuckDB pinned 1.5.3 / DuckLake v1.0 lockstep (OQ.12). pg_restore must version-match the dump.
- Terraform apply is human-gated (Decision 35 + 77); the fail-closed guard stays fail-closed.
- Only modify files in the Scope table. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`.
- No emojis; ASCII hyphens only; ruff line length 127; type hints; `bin/venv-python` for all Python.

## Context
- **Existing substrate (do NOT rebuild):** `ducklake_writer` (492 LOC) + `ducklake_reader` (130 LOC) already exist (`status: active`, T2.17) but operate on `ducklake_smoke_*` and are explicitly walled off from `ops_*`. The runtime primitives (`write_scd2`, `schema_gate`, OCC retry, `create_scd2_tables`, `read_current`) exist but are smoke-table-hardcoded (MERGE SQL at runtime lines ~404/413/423, read at ~539). `ducklake_maintenance` (T2.18) is deployed. T2.19 GENERALIZES the runtime to the real ops schemas and FLIPS the live transport -- it does not create new Lambdas.
- **Two-layer DQ (human-confirmed):** L1 = write-time enforcement in the writer (schema gate + structural SCD2/idempotency + in-transaction `update_rec` referential check, CD.33 clause 8 / D-5); L2 = batch DQ checks (`config/agent/data_quality/ops.yaml` via `data_quality_runner`, already a CI gate via `validate.py`) read from DuckLake. The existing ops.yaml already distinguishes the layers via `write_time: true` flags. T2.19 re-points the L2 backend Athena->DuckLake and adds the clause-8 checks; DQ is enforced from cutover (sign-off gate, VP13) and ongoing (CI).
- **Agent instructions (human-confirmed):** the agent COMMAND surface is unchanged (Single-Portal), so there is no new command to teach -- but `AGENTS.md` ("Warehouse-as-source-of-truth invariant" + "Operational data governance": currently "Athena over Iceberg is the single source of truth", "`update_rec` requires Athena connectivity") + `docs/PROJECT_CONTEXT.md` describe the retired substrate and MUST be corrected atomically with the cutover, else agents act on stale source-of-truth guidance.
- **Decisions this plan cites** (from the decision-scout gate, FLAGS_FOUND -- three NOTEs, no BLOCK):
  - **Decision 78** (adopt DuckLake; CD.31): clause 6/7 -- Single-Portal preserved (transport-agnostic), JSONL/Iceberg path continues until T2.19, ops_compaction retirement timing; clause 2 -- ops_* table scope.
  - **Decision 81** (ratifies CD.33): three-artifact split, OCC bounded-retry (OQ.10), schema-gate chokepoint (clause 4/5), closed boundary + break-glass (OQ.7, clause 7), current write-through SCD2 + key invariants + clause-8 DQ checks.
  - **Decision 82** (ratifies CD.34; EC8 churn gate): the cutover churn/OCC re-gate measurement (per-invocation wall, 2000ms/0.20, CHURN_WRITERS=4).
  - **Decision 79** (per-Lambda V3 build/deploy/smoke for writer + reader).
  - **Decision 77 + 35** (human-gated apply for IAM widening + ops_compaction destroy).
  - **Decision 55** (loud-fail; backfill parity / DQ / churn failures STOP the cutover).
  - **Decision 48** (V3 tier). **Decision 67** (STRATEGIC suspended -> single IMPLEMENTATION mega-plan).
  - **Decision 70** (exclude physically-deleted bootstrap rows from backfill). **Decision 64** (preserve the 2026-05-01 DQ anchor).
- **Decision flags (NOTE, folded in -- no pivot):** (1) D78 cl.7 -- ops_compaction retirement sequenced strictly AFTER sign-off, Iceberg kept intact for rollback (VP14/16); (2) D81 cl.7 -- "Athena escape hatch" framing DROPPED; OQ.7 is a CLOSED boundary, break-glass = PlatformAdmin on Neon+S3 only; (3) D78 cl.2/CD.34 -- telemetry migration OUT of scope, co-tuning numbers = ops-rate threshold recompute (stated in the scope-boundary AC).
- **Superseded-decision note (scout):** Decision 69/50/51/56 are superseded by Decision 78 -- the Single-Portal *invariant* survives transport-agnostic; cite Decision 78 cl.6 / Decision 81 cl.4, not Decision 69 as active law. Backfill reads FROM the Decision-50/56 Iceberg SCD2 store (historical context).
- **Preflight:** branch `claude/platform-roadmap-plan-Z5kYz`, main 0/0; creds OK (S3-reader ACCESS_DENIED warnings = known Iceberg-metadata->Athena fallback); ci_rca=0; non-automatable soft-cap breached (303, informational, Decision 73). T2.19 not in `next_eligible` (T2.18 in_progress) -- explicit human-directed continuation that closes T2.18.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (esp. 78, 81, 82, 79, 77, 70, 64, 55, 48, 67, 35)
- [ ] All files in Scope table located and readable (ducklake_runtime, writer/reader handlers, ops_data_portal, iceberg_reader, sync_ops, ops.yaml, field_semantics.yaml are the load-bearing edits)
- [ ] Acceptance Criteria understood and verifiable
- [ ] Real `ops_*` schemas confirmed against the live Iceberg tables before writing field_semantics (do not infer columns from memory)
- [ ] DuckLake `MERGE`/table-function signatures confirmed against the live pinned DuckDB 1.5.3 (not from memory)

## Ordered Execution Steps
1. **`config/lambda/ducklake/field_semantics.yaml`** -- author the per-table `ops_*` schemas (columns/types/roles/partitions) from the live Iceberg table definitions. This drives both the gate and the DDL.
2. **`src/common/ducklake_runtime.py`** -- table-parameterize `create_scd2_tables` / `write_scd2` / `read_current` / `schema_gate` / MERGE SQL + `_SCD2_COLUMNS` + `SMOKE_*` constants (per-table, field_semantics-driven); **extend `_PY_TYPE_FOR_SQL` to arrays/ints/booleans** for the real ops columns; keep smoke defaults for T2.17 back-compat; preserve mint-once-outside-OCC.
3. **`src/lambdas/ducklake_writer/handler.py`** + **`ducklake_reader/handler.py`** -- add production `write_ops`/`update_ops` (gate + OCC + in-tx referential) and `read_ops_current`/`read_ops_history`/`query_ops`; remove the T2.17 deferral notes.
4. **`scripts/migrate_ops_iceberg_to_ducklake.py`** -- backfill + parity verification (excl. D70); idempotent by DROP+re-create (never append, resurrection-loop guard); loud-fail on mismatch. Precondition: the Iceberg outbox is drained empty first (so pending offline writes are captured).
5. **`scripts/ops_data_portal.py`** -- transport swap behind `OPS_STORAGE_BACKEND` (writer Function URL), caller surface + ID alloc preserved; `update_rec` referential loud-fail (remove the permissive upsert-on-absent); `sync` re-pointed to a DuckLake cache-pull (retire the Iceberg outbox-drain/compact internals, D81 cl.4); add `--selftest-read` / `--selftest-roundtrip` CLI subcommands (for VP14/15); reads via the DuckLake reader.
6. **`src/common/iceberg_reader.py`** + **`scripts/sync_ops.py`** + **`scripts/session_preflight.py`** -- add `DuckLakeReader`, route reads/cache-rebuild through it (flagged); keep `DuckDBIcebergReader` as rollback target.
7. **`config/agent/data_quality/ops.yaml`** + **`scripts/data_quality_runner.py`** -- dual-backend dispatch: compile ops checks to DuckDB dialect against the DuckLake `current` TABLE (not the Athena `_current` view; translate Trino idioms e.g. `date_diff` -> DuckDB), telemetry checks stay on Athena; add clause-8 checks (ULID-history uniq, `current` uniq, referential); preserve D64 anchor.
8. **`src/common/catalog_dr.py`** -- add the pg_restore restore helper.
9. **`scripts/ducklake_neon_smoke_test.py`** -- add `--ops-read-your-write`, `--ops-churn-regate`, `--catalog-restore-drill` gates.
10. **`terraform/personal/ducklake_lambdas.tf`** -- widen writer/reader IAM + flip `DUCKLAKE_DATA_PATH` to production (HUMAN-GATED apply). Do NOT touch ops_compaction yet.
11. **Tests** -- `test_ducklake_runtime.py`, `test_ops_data_portal.py`, `test_ops_migration.py`.
12. **Execute Verification Plan VP1-15** in order. Backfill+parity (9), restore drill (10), read-your-write (11), churn re-gate (12), DQ (13), rollback rehearsal (14) ALL pass before the cutover sign-off (15). If any V3 gate fails unrecoverably, STOP and root-cause (Decision 55) -- do not relax a gate.
13. **POST-SIGN-OFF:** **`terraform/scheduled_agents.tf`** + **`ops_compaction_handler.py`** + **`ops-compaction/manifest.yaml`** -- retire ops_compaction (VP16); confirm closed boundary (VP17).
14. **`AGENTS.md`** + **`docs/PROJECT_CONTEXT.md`** + **`docs/runbooks/ducklake-catalog-operations.md`** -- update agent instructions + cutover/rollback/restore runbook (atomic with cutover).
15. **`docs/ROADMAP-PLATFORM.yaml`** -- mark T2.19 complete + T2.18 complete (tail closed); record OQ.7/OQ.10 enacted. **`docs/SESSION_LOG.md`** -- session entry.
16. Report: what was implemented, the live VP results (parity numbers, restore-drill result, churn p95/collision, DQ verdict, read-your-write evidence), rollback-rehearsal confirmation, ops_compaction retirement confirmation, and T2.18+T2.19 closure.
