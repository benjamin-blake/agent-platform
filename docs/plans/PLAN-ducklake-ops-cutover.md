# Plan

## Intent
Cut the live RECOMMENDATIONS persistence path over from Iceberg/Athena to DuckLake-on-Neon (T2.19, recs-first
slice), preserving the Decision-69 Single-Portal caller surface and the closed read/write boundary. The one-time
data move is an OPERATIONAL maintenance-plane seed -- NOT a new agent write surface and NOT a writer "import" mode;
the only ops write surface remains `file_rec`/`update_rec` through the writer. Decisions and the remaining ops_*
tables are explicitly deferred to their own migrations (decisions' source of truth is `DECISIONS.md`, so they
rebuild, not migrate). This also lands the catalog-reinit step missing from the cutover sequence (rec-2099) and
relocates the smoke harness so it can never collide with the production catalog again.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-ops-cutover.md

## Phase
Phase 2 (Platform), T2 tier, T2.19 ("DuckLake ops write/read migration"). This slice completes the
RECOMMENDATIONS portion of T2.19; **T2.19 stays `in_progress`** with decisions + `ops_session_log` /
`ops_execution_plans` / `ops_priority_queue` as a tracked follow-up. T2.18's ops_compaction-retirement tail
also **defers** (ops_compaction stays live to serve the not-yet-migrated tables on Iceberg). depends_on
[T2.16, T2.17, T2.18]; T2.16/T2.17 complete, T2.18 in_progress -- this is the human-directed recs-first
continuation.

## Migration strategy
**BIG-BANG cutover (recs only) + documented rollback.** Safety: the one-time recs seed runs + parity-verifies
BEFORE the cutover flip; an `OPS_STORAGE_BACKEND` flag flips recs transport in one step and reverts in one step;
the Iceberg recs path stays fully intact until sign-off; and the Decision-82 churn re-gate, a `pg_restore`
restore drill, read-your-write, and DQ all run as sign-off gates BEFORE the flip is made default. Because
decisions + the other ops tables remain on Iceberg, **ops_compaction stays live** (its retirement defers to the
final table's migration) -- so rollback is real and nothing else is disturbed.

## Migration mechanism (the data move)
- **No writer "import" mode.** The agent write surface stays exactly `file_rec`/`update_rec` -> `ducklake_writer`,
  whose only write semantics is the normal mint-derived SCD2 path. No alternate/bootstrap write path is added to
  the agent-facing writer.
- **Operational maintenance-plane seed.** The one-time recs move is a TEMPORARY action on `ducklake_maintenance`
  (already a privileged catalog-admin artifact: DDL, GC, pg_dump), invoked over 443 via `aws lambda invoke` by the
  `agent_platform` role -- NOT a public Function URL, NOT an agent surface. It reuses the runtime `schema_gate` +
  `write_scd2` so seeded rows are schema-valid and SCD2-correct.
- **Current-state only; ids + timestamps preserved.** The seed migrates each rec's CURRENT version (SCD2 version
  history is dropped -- accepted), preserving `id` (rec-NNN, required for cross-refs + the DynamoDB counter) and the
  original `created_timestamp` / `last_updated_timestamp` (required to keep the Decision-64 `2026-05-01` anchor and
  DQ recency honest). Decision-70 physically-deleted rows are excluded.
- **Lambda-mediated, not Postgres-direct.** There is no Neon 5432 egress from CC-web, so the seed, the catalog
  reinit, and the restore drill are all `ducklake_maintenance` actions invoked over 443; the recs read-source
  (Iceberg current-state) is read via the existing reader over Athena (443, already working) and passed to the seed
  action (~360 rows, well under the sync-invoke limit).
- **Seed removed after.** `seed_ops_recommendations` is deleted (maintenance redeploy) post-sign-off; the recurring
  DR actions (`catalog_reinit`, `restore_drill`) are retained as legitimate operational ops.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| config/lambda/ducklake/field_semantics.yaml | Modify | Add the `ops_recommendations` SCD2 schema (per-table column map: types/roles/partitions). **Relocate the SMOKE tables to a dedicated META_SCHEMA `ducklake_smoke`** (they currently squat on the production `ducklake_ops` meta-schema -- the root cause of rec-2099) so smoke can never collide with the production catalog. Decisions + other ops_* schemas deferred. |
| src/common/ducklake_runtime.py | Modify | Table-parameterize `create_scd2_tables` / `write_scd2` / `read_current` / `schema_gate` / MERGE SQL + `_SCD2_COLUMNS` + `SMOKE_*` constants (per-table, field_semantics-driven); **extend `_PY_TYPE_FOR_SQL`** to arrays/ints/booleans. Author + exercise `ops_recommendations` now; mechanism ready for later tables. Smoke back-compat retained (now under `ducklake_smoke`). Mint-once-outside-OCC preserved (CD.33 cl.2). |
| src/lambdas/ducklake_writer/handler.py | Modify | Add production `write_ops` / `update_ops` for `ops_recommendations` (schema gate + bounded OCC = OQ.10 + SCD2; in-transaction referential check for `update_ops`, CD.33 cl.8 / D-5). **No import/bypass mode** -- the writer's only write semantics is the normal mint-derived path. |
| src/lambdas/ducklake_reader/handler.py | Modify | Add `read_ops_current` / `read_ops_history` / `query_ops` for `ops_recommendations` (Reader-protocol semantics incl. row_filter). |
| src/lambdas/ducklake_maintenance/handler.py | Modify | Add OPERATIONAL admin actions (invoked over 443 via `aws lambda invoke`, `agent_platform` role -- not agent surfaces, not public URLs): (1) `catalog_reinit` -- drop the squatting `ducklake_ops` meta-schema (DESTROYS disposable smoke state) + initialize `ducklake_ops` at the production DATA_PATH `s3://agent-platform-data-lake/ducklake/`; (2) `seed_ops_recommendations` -- TEMPORARY one-time bootstrap: accept recs current-state rows, exclude D70, `schema_gate` + `write_scd2` with PRESERVED id + original timestamps (current-state only, history dropped), idempotent by DROP+recreate, self-report parity; (3) `restore_drill` -- `pg_dump`->`pg_restore` into a scratch catalog + read-your-write. `seed_ops_recommendations` is REMOVED post-sign-off (maintenance redeploy); `catalog_reinit` + `restore_drill` retained. |
| scripts/ops_data_portal.py | Modify | Route `file_rec` / `update_rec` transport to the `ducklake_writer` Function URL behind `OPS_STORAGE_BACKEND` (RECS ONLY). **`file_decision` / `update_decision` + decisions reads STAY on the current Iceberg path** (decisions deferred). `update_rec` referential loud-fail (remove the permissive upsert-on-absent). `sync` for recs becomes a DuckLake cache-pull; the Iceberg outbox/compact internals remain for the deferred tables. Add `--sync` (expose `sync()`), `--selftest-read`, `--selftest-roundtrip` CLI subcommands (VP9/14/15). **No import surface added to the portal.** |
| src/common/iceberg_reader.py | Modify | Add `DuckLakeReader` (recs reads via the `ducklake_reader` Function URL) selected by `OPS_STORAGE_BACKEND`; `DuckDBIcebergReader` retained for decisions/other tables AND as the recs rollback target. |
| scripts/sync_ops.py | Modify | Rebuild the RECS read-cache from DuckLake (via the reader); decisions/other tables still rebuilt from Athena/Iceberg (dual-source during the transition). |
| scripts/session_preflight.py | Modify | Recs reads via the DuckLake reader (flagged); decisions/queue reads unchanged. |
| config/agent/data_quality/ops.yaml | Modify | **Dual-backend within ops:** `ops_recommendations` checks target the DuckLake `current` TABLE (DuckDB dialect); `ops_decisions` + the other ops tables stay on Athena (`_current` views). Add the recs clause-8 checks (ULID-history uniq, `current` uniq via id, referential). Preserve the D64 `exclude_before: '2026-05-01'` anchor. |
| scripts/data_quality_runner.py | Modify | Per-backend compilation/dispatch: recs -> DuckDB-dialect over the reader; decisions/others -> Athena (unchanged). Not a one-line swap. |
| src/common/catalog_dr.py | Modify | Add the `pg_restore` restore helper (custom-format FP-B dumps) used by the maintenance `restore_drill` action. |
| scripts/ducklake_neon_smoke_test.py | Modify | Smoke uses the new `ducklake_smoke` META_SCHEMA. Add 443 gates that invoke the Lambda actions: `--ops-read-your-write` (recs, via writer/reader URLs), `--ops-churn-regate` (recs, D82: CHURN_WRITERS=4, 2000ms/0.20, per-invocation wall), and `--catalog-restore-drill` (invokes maintenance `restore_drill`). |
| terraform/personal/ducklake_lambdas.tf | Modify | writer/reader prod `DUCKLAKE_DATA_PATH` (`ducklake/`) + `ops_recommendations` IAM (writer RW, reader RO); maintenance env/config for the new actions (maintenance already holds catalog + DuckLake RW); smoke catalog env -> `ducklake_smoke`. HUMAN-GATED (IAM, Decision 77/35). |
| tests/test_ducklake_runtime.py | Modify | Recs schema-parameterized write/read/gate tests + smoke (`ducklake_smoke`) back-compat. |
| tests/test_ops_data_portal.py | Modify | Recs transport swap + flag; decisions stay on Iceberg; `update_rec` referential loud-fail (assert the permissive path is GONE); **assert no import/bypass write surface exists**; `--sync`/`--selftest-*` subcommands. |
| tests/test_ops_seed.py | Create | Maintenance seed: id + timestamp preservation, D70 exclusion, current-state-only (no version history beyond the single seed row), DROP+recreate idempotency, parity self-report. |
| AGENTS.md | Modify | Transition-state source-of-truth: `ops_recommendations` source of truth = DuckLake-on-Neon (reads via reader, writes via writer through the portal; **the only ops write surface is `file_rec`/`update_rec`** -- no import path); `ops_decisions` + other ops tables REMAIN on the Iceberg/Athena path pending their own migrations; break-glass for the recs catalog = audited PlatformAdmin on Neon+S3 (no Athena escape hatch). |
| docs/PROJECT_CONTEXT.md | Modify | Update storage-architecture / source-of-truth / escape-hatch sections to the recs-on-DuckLake transition state. |
| docs/runbooks/ducklake-catalog-operations.md | Modify | Add: `catalog_reinit` (DESTRUCTIVE, IRREVERSIBLE) procedure; the maintenance-plane recs seed; `restore_drill`; rollback (flip recs to iceberg); smoke relocated to `ducklake_smoke`; all ops Lambda-mediated over 443 (no 5432 from CC-web). |
| docs/ROADMAP-PLATFORM.yaml | Modify | T2.19 -> recs portion done; decisions + remaining ops tables tracked as the follow-up; **ops_compaction retirement DEFERRED** (stays live for non-migrated tables) -- T2.18 tail carries forward. Record rec-2099 resolved (reinit step added) + OQ.7/OQ.10 enacted for recs. |
| docs/SESSION_LOG.md | Modify | Session entry. |

## Bundled Recommendations
- **rec-2099** (real, confirmed at implementation): the cutover sequence was missing a catalog-reinit step (the `ducklake_ops` meta-schema squats at the smoke data path, so ATTACH at `ducklake/` fails). Resolved by the `catalog_reinit` maintenance action + smoke relocation to `ducklake_smoke` (root-cause fix). Close at sign-off.

## Infrastructure Dependencies
| Item | Detail |
|------|--------|
| Modified resources | writer/reader exec-role IAM + `DUCKLAKE_DATA_PATH` -> production `ducklake/` + `ops_recommendations` prefix (writer RW, reader RO); maintenance gains the operational actions (reuses its existing catalog + DuckLake RW; env/config only); smoke catalog META_SCHEMA -> `ducklake_smoke`. **ops_compaction NOT retired** this slice (still serves decisions/others). |
| Apply posture | HUMAN-GATED via `agent_platform_admin` (Decision 35 + 77); IAM widening trips the fail-closed guard. |
| Catalog reinit | DESTRUCTIVE + IRREVERSIBLE (drops the smoke-squatting meta-schema). Safe NOW: only disposable T2.17 smoke state exists at `ducklake_ops`; no production data. Run as a deliberate, documented step via `aws lambda invoke` (not terraform). |
| Lambda deployment (Decision 79) | `ducklake_writer` + `ducklake_reader` + **`ducklake_maintenance`** are MODIFIED active artifacts -> per-Lambda V3 build + deploy + smoke each. `ducklake_catalog_dr` unchanged. No model IDs touched (deterministic SQL) -> inference-provider validation N/A. |
| Egress | No Neon 5432 from CC-web; all Postgres-direct ops are Lambda-mediated over 443. Iceberg/Athena reads (recs source for the seed) work from CC-web over 443. |
| Timing | schema/runtime/seed-logic/DQ = `[pre-deploy]`; IAM apply + writer/reader/maintenance deploy = `[pre-deploy]`/`[post-deploy]`; catalog_reinit + seed + sign-off gates = `[post-deploy]`; seed-action removal = `[post-deploy]`, post-sign-off. |

## Acceptance Criteria
- [ ] RECS writes go through the DuckLake writer via `ops_data_portal`; the portal caller surface (`file_rec`/`update_rec` signatures) is unchanged (Decision 78 cl.6 / Decision 81 cl.4). **The only ops write surface remains `file_rec`/`update_rec` -- no import/bypass path is added to the writer or the portal** (verified by test + by code-grep at VP17).
- [ ] `ops_recommendations` reads transit `ducklake_reader`; the recs catalog has a CLOSED boundary (Decision 81 cl.7): no Athena escape hatch; break-glass = audited PlatformAdmin on Neon+S3.
- [ ] The one-time recs move is an OPERATIONAL maintenance-plane seed (not agent-facing): current-state only (history dropped, accepted), with `id` + original `created`/`last_updated` timestamps PRESERVED and D70 rows excluded; reuses `schema_gate` + `write_scd2`; parity-verified (per-rec count + content of `current` vs Iceberg) and loud-fails on mismatch (Decision 55).
- [ ] `seed_ops_recommendations` is REMOVED post-sign-off (maintenance redeployed without it); `catalog_reinit` + `restore_drill` retained as operational DR ops.
- [ ] Catalog reinit done: the `ducklake_ops` meta-schema is re-initialized at `ducklake/` (squatting smoke state destroyed); smoke relocated to `ducklake_smoke` (cannot collide with production again); rec-2099 closed.
- [ ] SCD2 current write-through verified for recs (one DuckLake txn = INSERT history + MERGE current; read-your-write green); OQ.10 bounded-OCC verified by the Decision-82 churn re-gate at production scope (CHURN_WRITERS=4, 2000ms / 0.20, per-invocation wall).
- [ ] Two-layer DQ for recs: L1 write-time schema gate + in-tx `update_rec` referential (loud-fail on absent); L2 batch DQ (ULID-history uniq, `current` uniq, referential, recency, D64 anchor) read from DuckLake and gating CI. `ops_decisions` + other ops DQ stay on Athena.
- [ ] Rollback proven: flipping `OPS_STORAGE_BACKEND` back to `iceberg` restores the recs Iceberg path (intact; ops_compaction live) -- tested before sign-off.
- [ ] All Postgres-direct ops (seed, catalog_reinit, restore_drill) run Lambda-mediated over 443 (no 5432 from CC-web).
- [ ] Per-Lambda V3 build + deploy + smoke pass for writer + reader + maintenance (Decision 79).
- [ ] **Scope boundary:** ONLY `ops_recommendations` migrates this slice. `ops_decisions` (rebuild from `DECISIONS.md`), `ops_session_log`, `ops_execution_plans`, `ops_priority_queue` are DEFERRED to their own migrations and REMAIN on the Iceberg/Athena path; their portal/read/DQ paths are untouched. ops_compaction STAYS LIVE; its retirement defers. Telemetry-table migration also out of scope (Decision 78 cl.2). T2.19 stays in_progress (recs done).
- [ ] Agent instructions updated atomically with cutover: `AGENTS.md` + `docs/PROJECT_CONTEXT.md` describe the transition state (recs -> DuckLake; decisions/others -> Athena; only-write-surface = portal; recs break-glass = Neon+S3).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit-test recs-parameterized runtime + smoke (ducklake_smoke) back-compat | `bin/venv-python -m pytest tests/test_ducklake_runtime.py -q` | All pass; smoke paths green under `ducklake_smoke`; recs schema write/read/gate correct | Smoke regressed / recs schema mismatch -> fix parameterization |
| 2 | [pre-deploy] | Unit-test portal recs transport + flag + no-import-surface + decisions-stay-Iceberg | `bin/venv-python -m pytest tests/test_ops_data_portal.py -q` | Recs `ducklake` backend invokes the writer; `iceberg` rollback intact; decisions unchanged; permissive `update_rec` gone; no import surface | Surface drift -> fix |
| 3 | [pre-deploy] | Unit-test maintenance seed (id/timestamp preserve, D70 excl, current-only, DROP+recreate, parity) | `bin/venv-python -m pytest tests/test_ops_seed.py -q` | Seed preserves id+timestamps, excludes D70, writes one current row per rec, idempotent, parity comparator catches an injected mismatch | Comparator misses a mismatch -> strengthen before any real seed |
| 4 | [pre-deploy] | Validate writer/reader/maintenance manifests + bundles | `bin/venv-python -m scripts.lambda_manifest --validate && bin/venv-python -m scripts.lambda_manifest --check-bundles` | 3 functions validate + bundle (field_semantics recs schema included) | Missing include -> add to manifest |
| 5 | [pre-deploy] | Full presubmit | `bin/venv-python -m scripts.validate` | PASS (CI-identical) | Any failure -> fix |
| 6 | [pre-deploy] | Build ducklake zips (`--ducklake-only` builds all 4; writer/reader/maintenance carry this slice's changes, catalog-dr unchanged) | `bin/venv-python -m scripts.build_lambda --ducklake-only` | 4 zips built + uploaded; catalog-dr source unchanged -> byte-equivalent | Build error -> fix |
| 7 | [pre-deploy] | HUMAN-GATED IAM apply (writer/reader prod path + ops_recommendations; maintenance env; smoke->ducklake_smoke) | `terraform -chdir=terraform/personal apply` (admin, after plan review) | writer RW + reader RO on `ducklake/`+`ops_recommendations`; NO destroys (ops_compaction untouched); present plan to human | Unexpected destroy -> stop (D77 guard) |
| 8 | [post-deploy] | Deploy ducklake function code (`--deploy` updates all 4) | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` | writer/reader/maintenance live with this slice's changes; catalog-dr byte-equivalent | Deploy error -> check function map |
| 9 | [post-deploy] | Catalog reinit (DESTRUCTIVE, deliberate) over 443: drop smoke squat + init `ducklake_ops` at `ducklake/` | `aws lambda invoke --function-name agent-platform-ducklake-maintenance --payload '{"action":"catalog_reinit","data_path":"s3://agent-platform-data-lake/ducklake/"}' --profile agent_platform /dev/stdout` | Reinit OK; production catalog ATTACHes at `ducklake/`; smoke state discarded (disposable) | ATTACH still mismatches -> RCA the meta-schema/data-path |
| 10 | [post-deploy] | Drain recs outbox to Iceberg + assert empty, read recs current-state (Athena, 443), seed via maintenance over 443, verify parity | `OPS_STORAGE_BACKEND=iceberg bin/venv-python -m scripts.ops_data_portal --sync && { find logs/.ops-outbox -type f \| grep -q . && echo "OUTBOX NOT EMPTY -- STOP" \|\| aws lambda invoke --function-name agent-platform-ducklake-maintenance --payload "$(bin/venv-python -m scripts.ducklake_neon_smoke_test --emit-recs-seed-payload)" --profile agent_platform /dev/stdout; }` | Outbox empty; per-rec `current` count + content match (excl D70); `parity=PASS`; ids + timestamps preserved | Outbox not empty -> drain first; Parity FAIL -> STOP, RCA (Decision 55); re-run re-creates (no append) |
| 11 | [post-deploy] | Catalog-DR restore drill over 443 (pg_dump->pg_restore scratch catalog + read-your-write) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --catalog-restore-drill` | Restore succeeds; read-your-write on the restored catalog passes; engine version matches | Restore fails / version mismatch -> fix before sign-off |
| 12 | [post-deploy] | Recs read-your-write through the closed boundary (write via writer URL, read via reader URL) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-read-your-write` | `write_ops` value returned by `read_ops_current`; `update_ops` reflected; absent-rec `update_ops` loud-fails (referential) | Fails -> fix writer/reader |
| 13 | [post-deploy] | Decision-82 churn/OCC re-gate (recs, production scope) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-churn-regate` | collision_rate <= 0.20 AND p95 per-invocation wall <= 2000ms | Over budget -> RCA (do NOT relax, D82/55) |
| 14 | [post-deploy] | DQ runner: recs over DuckLake (L2), decisions/others still Athena | `bin/venv-python -m scripts.data_quality_runner && bin/venv-python -c "import json;print(json.load(open('logs/debug/dq-latest.json'))['verdict'])"` | `PASS`; recs clause-8 checks present + green; D64 anchor honoured; decisions/others unaffected | Any DQ failure -> RCA; cutover blocked |
| 15 | [post-deploy] | Rollback rehearsal: flip recs to iceberg, confirm live, flip back | `OPS_STORAGE_BACKEND=iceberg bin/venv-python -m scripts.ops_data_portal --selftest-read && OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-read` | Both backends serve recs reads; Iceberg recs path + ops_compaction intact | Rollback broken -> fix BEFORE sign-off |
| 16 | [post-deploy] | CUTOVER SIGN-OFF: re-assert recs outbox empty, flip `OPS_STORAGE_BACKEND` default to `ducklake`, end-to-end recs write+read on DuckLake | `find logs/.ops-outbox -type f \| grep -q . && echo "IN-FLIGHT -- re-seed" \|\| bin/venv-python -m scripts.ops_data_portal --selftest-roundtrip` | Outbox empty (no concurrent recs writes during the window); a `file_rec`-shaped write lands in DuckLake + reads back; no Iceberg recs write | Outbox non-empty -> incremental re-parity; roundtrip fails -> revert flag; RCA |
| 17 | [post-deploy] | POST-SIGN-OFF: remove `seed_ops_recommendations` + redeploy maintenance; confirm recs closed boundary | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy && bin/venv-python -m scripts.validate && grep -rn "OpsWriter().write" scripts/ src/ \| grep -i "ops_recommendations\|file_rec\|update_rec" \| grep -v test` | seed action gone; validate PASS; no live Iceberg recs write path remains (only the flagged rollback shim) | A recs bypass remains -> route through the writer; seed still present -> remove + redeploy |

## Constraints
- **No alternate agent write path.** The only ops write surface is `file_rec`/`update_rec` -> `ducklake_writer` (normal mint-derived semantics). No import/bypass mode on the writer or portal. The one-time recs seed is operational-plane (maintenance, `aws lambda invoke`, schema-gated) and is REMOVED post-sign-off.
- No rescue agents / workaround loops (Decision 55). A parity / DQ / churn / restore-drill failure STOPS the cutover -- do not relax a budget/threshold or skip a gate.
- Single-Portal invariant (Decision 78 cl.6 / Decision 81 cl.4): caller surface unchanged; only recs transport swaps. Decisions + other tables stay on the current path.
- Closed boundary for recs (Decision 81 cl.7): no Athena escape hatch; break-glass = audited PlatformAdmin on Neon+S3.
- All Postgres-direct ops are Lambda-mediated over 443 (no Neon 5432 egress from CC-web).
- catalog_reinit is DESTRUCTIVE + IRREVERSIBLE -- a deliberate, documented step; safe now (only disposable smoke state exists).
- Cutover-window operating assumption: no concurrent recs writes between the seed (VP10) and the sign-off flip (VP16); enforced by outbox drain+assert at VP10 and re-assert at VP16.
- Backfill excludes Decision-70 rows; DQ preserves the Decision-64 `2026-05-01` anchor.
- ops_compaction stays LIVE (serves decisions/others on Iceberg); its retirement defers to the final table's migration. Iceberg recs data retained until sign-off so rollback is real.
- DuckDB 1.5.3 / DuckLake v1.0 lockstep (OQ.12); pg_restore version-matches the dump.
- Terraform apply human-gated (Decision 35 + 77). Only modify files in Scope. Out-of-scope bugs -> recs via the portal.
- No emojis; ASCII hyphens; ruff line length 127; type hints; `bin/venv-python` for all Python.

## Context
- **Why recs-only:** human-directed. Decisions' source of truth is `DECISIONS.md`, so they rebuild via the existing ETL rather than migrate -- cleanly separable into a follow-up. `ops_session_log` (telemetry) + `ops_execution_plans` / `ops_priority_queue` (executor-owned, executor PAUSED per CD.17) also defer. Deferring decisions means ops_compaction must stay live, so there is no retirement benefit to dragging the other tables in now -- recs-only is the minimal, lowest-risk slice.
- **Why no writer import mode (human-directed):** an alternate write path -- even one-time -- is a standing surface agents could misuse. Preserving `rec-NNN` ids is incompatible with `file_rec` (allocates new) and `update_rec` (referential loud-fail on absent), and preserving timestamps (D64 anchor + DQ recency) needs supplied-field writes -- so a bootstrap is unavoidable. The resolution is to put it on the OPERATIONAL plane (`ducklake_maintenance`, already privileged for DDL/GC/pg_dump), invoked via `aws lambda invoke` by the `agent_platform` role -- never an agent write surface -- reusing `schema_gate`+`write_scd2`, and removed after.
- **rec-2099 root cause:** T2.17 smoke initialized the production meta-schema name `ducklake_ops` pointing at the smoke data path (`ducklake-neon-smoke/`). DATA_PATH is a catalog property, so ATTACH at `ducklake/` fails. Fix = `catalog_reinit` + relocate smoke to its own `ducklake_smoke` meta-schema (so it never recurs and the smoke-gate back-compat stays coherent).
- **Existing substrate (do NOT rebuild):** `ducklake_writer`/`ducklake_reader` (T2.17, smoke-only) + `ducklake_maintenance`/`ducklake_catalog_dr` (T2.18) already deployed. The runtime is smoke-hardcoded today; this slice generalizes the mechanism + authors the recs schema + flips recs transport.
- **Decisions cited:** 78 (cl.2/6/7 -- DuckLake adoption, Single-Portal transport-agnostic, ops_compaction live-until-cutover), 81 (CD.33 -- writer/reader/maintenance split, OCC/OQ.10, schema gate, closed boundary/OQ.7, current write-through, clause-8 DQ), 82 (CD.34/EC8 churn gate), 79 (per-Lambda V3 for writer+reader+maintenance), 77+35 (human-gated apply), 55 (loud-fail), 48 (V3), 67 (STRATEGIC suspended -> IMPLEMENTATION), 70 (exclude deleted bootstrap rows), 64 (preserve 2026-05-01 anchor). Decision 69/50/51/56 superseded by 78 -- cite the preserved invariant via 78 cl.6 / 81 cl.4, not 69 as active law.
- **Decision-scout NOTE flags (folded):** D78 cl.7 (retirement after sign-off -- here, deferred entirely as ops_compaction stays live), D81 cl.7 (closed boundary, no Athena escape hatch), D78 cl.2 (telemetry out of scope).
- **Preflight:** branch `claude/platform-roadmap-plan-Z5kYz`. No Neon 5432 egress from CC-web (drives the Lambda-mediation). Iceberg/Athena reads work over 443.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md + DECISIONS.md (78,81,82,79,77,70,64,55,48,67,35) read
- [ ] Scope files located + readable (runtime, writer/reader/maintenance handlers, ops_data_portal, iceberg_reader, ops.yaml, field_semantics)
- [ ] Real `ops_recommendations` schema confirmed against the live Iceberg table before authoring field_semantics
- [ ] Confirm `aws lambda invoke` to `ducklake_maintenance` works over 443 with the `agent_platform` role (the Lambda-mediation precondition)
- [ ] DuckLake MERGE / meta-schema (ATTACH / DROP SCHEMA) semantics confirmed against pinned DuckDB 1.5.3

## Ordered Execution Steps
1. **`field_semantics.yaml`** -- author `ops_recommendations` schema; relocate smoke tables to META_SCHEMA `ducklake_smoke`.
2. **`ducklake_runtime.py`** -- table-parameterize the primitives + extend `_PY_TYPE_FOR_SQL` (arrays/ints/booleans); keep smoke (now `ducklake_smoke`) back-compat.
3. **`ducklake_writer`/`ducklake_reader` handlers** -- production `write_ops`/`update_ops` (gate+OCC+referential) and `read_ops_*` for recs; NO import mode.
4. **`ducklake_maintenance` handler** -- add `catalog_reinit`, `seed_ops_recommendations` (TEMP), `restore_drill` operational actions.
5. **`ops_data_portal.py`** -- recs transport behind `OPS_STORAGE_BACKEND`; decisions stay Iceberg; `update_rec` referential loud-fail; `--sync`/`--selftest-*`; no import surface.
6. **`iceberg_reader.py` + `sync_ops.py` + `session_preflight.py`** -- `DuckLakeReader` for recs (flagged); decisions/others on the old path.
7. **`ops.yaml` + `data_quality_runner.py`** -- recs DQ -> DuckDB/`current` table; decisions/others -> Athena; recs clause-8 checks; D64 anchor.
8. **`catalog_dr.py`** -- pg_restore helper for `restore_drill`.
9. **`ducklake_neon_smoke_test.py`** -- `ducklake_smoke` schema; `--emit-recs-seed-payload`, `--ops-read-your-write`, `--ops-churn-regate`, `--catalog-restore-drill`.
10. **`terraform/personal/ducklake_lambdas.tf`** -- writer/reader prod path + recs IAM; maintenance env; smoke->ducklake_smoke (HUMAN-GATED apply). ops_compaction untouched.
11. **Tests** -- `test_ducklake_runtime.py`, `test_ops_data_portal.py`, `test_ops_seed.py`.
12. **Run VP1-16** in order: reinit (9) -> seed+parity (10) -> restore-drill (11) -> read-your-write (12) -> churn (13) -> DQ (14) -> rollback rehearsal (15) -> sign-off flip (16). Any V3 gate failing unrecoverably -> STOP + RCA (Decision 55).
13. **POST-SIGN-OFF (VP17):** remove `seed_ops_recommendations` + redeploy maintenance; confirm recs closed boundary; close rec-2099.
14. **`AGENTS.md` + `PROJECT_CONTEXT.md` + runbook** -- transition-state instructions + reinit/seed/restore/rollback runbook (atomic with cutover).
15. **`ROADMAP-PLATFORM.yaml`** -- T2.19 recs done; decisions + remaining tables tracked; ops_compaction retirement deferred. **`SESSION_LOG.md`** -- entry.
16. Report: recs parity numbers, reinit confirmation, restore-drill result, churn p95/collision, DQ verdict, read-your-write evidence, rollback rehearsal, seed-removal confirmation, and the explicit deferred-scope list.
