# Plan

## Intent
Finalise the T2.19 recs-first DuckLake ops cutover: restore main's full-tier CI to green (4 open
ci_rca recs raised by the cutover sequence) and complete the ~90%-done live cutover through sign-off.
Preserves the Decision-81 closed boundary and the Decision-78/81 Single-Portal caller surface; no new
agent write surface is introduced.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-ops-finalize.md

## Phase
Phase 2 (Platform), T2 tier, T2.19 ("DuckLake ops write/read migration"). This plan completes the
RECS slice of T2.19 begun in `PLAN-ducklake-ops-cutover.md` (merged via PR #106): it lands the CI-green
fixes for the 4 ci_rca recs the cutover sequence raised, plus the live cutover sign-off. Transitions the
T2.19 recs-slice `in_progress` -> recs-complete; `ops_decisions` (rebuilds from `DECISIONS.md`),
`ops_session_log`, `ops_execution_plans`, `ops_priority_queue` remain DEFERRED follow-ups on the
Iceberg/Athena path. ops_compaction stays live. depends_on the predecessor cutover plan (landed).

## Current State (resumption point -- read FIRST)
**PHASE 0 + PHASE 1 are LANDED on main; the live-connectivity blocker is RESOLVED. A fresh agent
resumes at the PHASE 2 deploy/IAM/sign-off tail (VP9 onward).**
- **PHASE 0+1 landed** (PR #108 `f2e5cd9` + PR #109 `3e5152e`), MERGE CHECKPOINT A GREEN:
  - SCD2 pure/impure split done -- `src/common/ducklake_scd2_schema.py` created; `ducklake_runtime.py`
    is now **432 SLOC** (< 500, Decision-43, NO waiver). VP1-VP4 satisfied.
  - `validate_sloc_limits` added to the `--pre` tier; `get_changed_files()` drops deleted paths. VP3 done.
  - D64 `2026-05-01` anchor restored on `automatable`+`risk`; offending row remediated; DQ 0 violations. VP5 done.
  - Full presubmit green; **rec-2103/2104/2105/2106 CLOSED** (`ci_rca=0` at preflight). VP6 done.
  - PHASE 1 dead code removed: `scripts/migrate_ops_iceberg_to_ducklake.py` + its test DELETED. VP7 done.
  - `AgentPlatformRuntime` inline policy confirmed out-of-band (deferred, VP8). PlatformDev
    `lambda:InvokeFunction` grant landed in #109 (`platform_roles.tf`).
- **Live-connectivity blocker RESOLVED** (PR #110 plan + PR #111 `c49d2b0`, branch
  `claude/ducklake-neon-connect-rca-17a47n`): the previous agent could not sign off because the live
  Lambdas appeared to hit a Neon blackhole (120s hangs). Root cause: `libpq_conninfo` set **no
  `connect_timeout`**, so DNS/TCP/AUTH/ATTACH failures all blocked to the Lambda wall and looked
  identical. Fix: bounded `connect_timeout=10s` (`DUCKLAKE_CONNECT_TIMEOUT_S`-overridable) +
  a phased `connect_probe` diagnostic action on writer+reader. Live-verified: `lambda_attach` GREEN
  (`connect_ms` ~585-596ms), reader OK rows=4, both probes `phase_reached=attach ok=True`. The 10-15s
  ATTACH is DuckLake scale-to-zero **cold-resume, within the 18s budget** -- NOT a hang. **No Neon
  endpoint/project/credential fix was needed.** Writer + reader were redeployed with this runtime.
- **REMAINING (this plan's resumption scope): VP9 -> VP16.** Deploy byte-currency confirm (incl.
  maintenance + catalog_dr, which were not re-smoked in the connect-rca session), the `github_ci`
  `InvokeFunction` grant (corrected verb -- see below), the cutover SIGN-OFF flip (3 sites still
  `iceberg`), the atomic docs flip, seed-action removal + maintenance redeploy, and PHASE 3 bookkeeping.
- **Driving rec: rec-2111** (open, High) -- "resume PHASE 2/3 sign-off tail". rec-2099 (open) closes at
  seed-removal (VP15). rec-2107/2108/2109/2110 were stale ci_rca dupes already CLOSED by the connect-rca session.

## Predecessor & cross-plan VP numbering
Continues `PLAN-ducklake-ops-cutover.md`, which defined cutover gates VP1-VP17 and landed the recs
runtime/writer/reader/maintenance + the maintenance seed + the cutover scaffolding. This plan OWNS the
sign-off tail (cutover VP14/15/16/17), DEFERS cutover VP11 (restore-drill, see Risks & Deviations), and
adds new CI-green + cleanup gates. To avoid ambiguity, THIS plan's Verification Plan is numbered 1..16;
each step that corresponds to a cutover gate is annotated `(= cutover VPx)`.

## Sequencing & merge checkpoints
- PHASE 0 + PHASE 1 form a self-contained GREEN slice -- they restore main's full-tier CI and remove
  dead code, touching no live AWS state. **MERGE CHECKPOINT A:** merge PHASE 0+1 to main FIRST (squash
  via GitHub MCP: fast `--pre` PR tier, then post-merge full tier) to clear the 5-run-red main BEFORE the
  live cutover work. Close rec-2103/2104/2105/2106 at this checkpoint.
- PHASE 2 + PHASE 3 (live cutover sign-off + bookkeeping) land as a follow-on merge AFTER checkpoint A is
  green. This keeps the human-gated apply + live deploy + sign-off off the critical path of restoring
  green main.
- Rationale: main is currently RED (5 consecutive full-tier runs); the closing-report's "unblock main
  fast" goal is best served by merging the CI-green slice first. The PHASE 0 split's Lambda deploy rides
  PHASE 2 -- the refactor is behaviour-preserving and flag-gated to `iceberg` by default, so main can
  carry the refactored source while the deployed Lambdas still run the pre-split runtime until the PHASE 2
  redeploy (deploy-deferred-within-plan, NOT a Decision-79 deploy-skip).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| src/common/ducklake_scd2_schema.py | Create | New sibling module holding the PURE, I/O-free schema layer extracted from `ducklake_runtime.py` (~130 SLOC): the spec/ordering/resolve helpers (`ScdTableSpec`, `_order_columns`, `resolve_table_spec`, `ops_table_names`), the DDL/MERGE/SELECT SQL builders (`_column_ddl`, `_build_merge_history_sql`, `_build_merge_current_sql`, `_build_select_existing_created_sql`), `_write_params`, the pure `schema_gate` validator (line 490 -- no connection arg, no `.execute`), and the `_PY_TYPE_FOR_SQL` type map. Seam = "what the SCD2 schema IS and how to render its SQL", with NO live-connection coupling. **To keep the dependency strictly one-directional (`runtime -> schema`, NO import cycle), the move MUST ALSO carry the shared LEAF symbols the extracted code references:** the pure dataclasses `WriteIdentity`/`WriteResult`, the exception(s) `schema_gate` raises plus the `DuckLakeRuntimeError` base they derive from (co-locate `SchemaGateError`/`ReferentialError`), the constants `CATALOG_ALIAS` + `SMOKE_HISTORY_TABLE`/`SMOKE_CURRENT_TABLE` that the builders/`resolve_table_spec` reference, and the `load_field_semantics` chain (`_field_semantics_path`/`_load_field_semantics_cached`/`load_field_semantics` -- loads the static schema-contract YAML; file I/O, not catalog I/O, so it belongs with the schema layer). A literal 11-symbol-only extraction would create a circular import (VP1/VP4 would catch it, but they are enumerated here so the implementer does not hit it). SLOC still clears (~419 with the leaves included). Pure functions -> DB-free unit-testable (assert on SQL strings), which VP1's byte-identical check leverages. Lambda-packaged. Behaviour-preserving pure move. (rec-2103/rec-2106) |
| src/common/ducklake_runtime.py | Modify | Move the pure schema/SQL layer OUT (to the new module); RETAIN the EXECUTION layer -- `open_connection`, `write_scd2` (OCC transaction loop), `create_scd2_tables`, `read_current`/`read_history`/`query_current`, DSN/conninfo, metrics, OCC helpers -- and IMPORT the builders/spec/gate -- plus the shared leaves that moved with them (the `WriteIdentity`/`WriteResult` dataclasses, the SCD2 exception hierarchy, `CATALOG_ALIAS`, `SMOKE_*`, `load_field_semantics`) -- back from `ducklake_scd2_schema`. One-directional dependency (runtime -> schema, never the reverse). Lands the file under the Decision-43 500 SLOC limit (589 currently / 576 at ci_rca filing, both > 500). No behaviour change. (rec-2103/rec-2106) |
| src/lambdas/ducklake_writer/manifest.yaml | Modify | Add `src/common/ducklake_scd2_schema.py` to `includes[]`. The manifest lists `src/common` files by NAME (not the package); without this the writer bundle ships without the new module and import-fails at runtime. |
| src/lambdas/ducklake_reader/manifest.yaml | Modify | Same: add `src/common/ducklake_scd2_schema.py` to `includes[]`. |
| src/lambdas/ducklake_maintenance/manifest.yaml | Modify | Same: add `src/common/ducklake_scd2_schema.py` to `includes[]`. |
| src/lambdas/ducklake_catalog_dr/manifest.yaml | Modify | Add `src/common/ducklake_scd2_schema.py` to `includes[]`. catalog_dr is `status: active` and explicitly bundles `ducklake_runtime.py` (manifest line 10), which its handler imports via `catalog_dr.py`; after the split the runtime imports the new sibling module, so WITHOUT this, `--check-bundles` / `validate_lambda_bundle_completeness` import-resolution fails catalog_dr at presubmit + CI -- reddening the very PHASE 0 slice meant to restore green main. |
| src/lambdas/data-pipeline/manifest.yaml | Modify | Add `src/common/ducklake_scd2_schema.py` to `excludes[]`. data-pipeline uses `includes: - src/` (whole-tree) and ALREADY excludes `ducklake_runtime.py` to keep DuckLake runtime code out of the zip (closed boundary / 262MB ceiling); the new sibling module is DuckLake runtime code the copytree would otherwise leak in -- exclude it for consistency. (Affected anyway by the SIGN-OFF `iceberg_reader.py` flip, which IS bundled -> byte-currency rebuild + existing smoke.) |
| src/lambdas/ops-compaction/manifest.yaml | Modify | Same exclude as data-pipeline (identical exclusion block + minimal-zip invariant). Affected by the `iceberg_reader.py` flip -> byte-currency rebuild + existing smoke. |
| scripts/validate.py | Modify | (a) Add `validate_sloc_limits(failed)` to the `--pre` tier next to `validate_cc_limits` (line ~2676) -- SLOC is currently presubmit-only (line 2234), which is why PR #106 passed `--pre` but failed the full tier post-merge; the CC twin already runs in `--pre` per the rec-859 `earliest_viable_gate="pre"` precedent, so this mirrors it. (b) Fix `get_changed_files()` (line ~109) to drop DELETED paths before they are fed to ruff (PHASE 1 prerequisite -- deleting the migrate script otherwise makes ruff choke on a missing path). |
| config/agent/data_quality/ops.yaml | Modify | Restore the Decision-64 `exclude_before: '2026-05-01'` recency anchor on the `automatable` + `risk` not_null checks for `ops_recommendations` -- they anomalously LACK the anchor every other column check carries. Consistency-restoration, NOT gate-weakening. (rec-2104/rec-2105) |
| tests/test_ducklake_scd2_schema.py | Create | Unit tests for the extracted module: schema-spec + DDL/MERGE builders produce the expected SQL. |
| tests/test_ducklake_runtime.py | Modify | Update imports for the split; assert the re-imported builders produce DDL/MERGE SQL byte-identical to pre-split (behaviour-preserving). |
| tests/test_validate.py | Modify | Assert `validate_sloc_limits` runs in the `--pre` tier; assert `get_changed_files()` filters deleted paths before ruff. |
| scripts/migrate_ops_iceberg_to_ducklake.py | Delete | Superseded by the maintenance `seed_ops_recommendations` action (cutover plan). Dead code (closing-report item 8). Grep-confirm no live references first. |
| tests/test_migrate_ops_iceberg_to_ducklake.py | Delete | Test for the deleted script. |
| terraform/personal/platform_roles.tf | No change (deferred) | The redundant `AgentPlatformRuntime` inline policy (closing-report item 8) is applied OUT-OF-BAND via the `platform_breakglass` admin user and is NOT codified in `terraform/personal/` (terraform/CLAUDE.md:24-25, 64) -- it cannot be removed by editing this file, nor does it appear in `terraform plan`. Its removal is already a documented `platform_breakglass` follow-up; DEFERRED out of this branch's scope (not a terraform/personal/ edit). |
| scripts/ducklake_neon_smoke_test.py | Modify (optional) | Add a Neon warm-up to the churn gate's pre-warm phase (closing-report item 8). Do NOT change the Decision-82 `CHURN_WRITERS=4` / 2000ms / 0.20 budget. |
| terraform/personal/oidc.tf | Confirm-or-add (idempotent) | Grant the `github_ci` OIDC role(s) (`agent-platform-github-ci-pr` / `-branch`) the **`lambda:InvokeFunction`** they need to read recs over the reader Function URL during CI/DQ (closing-report item 1). **CORRECTED VERB (rec-2111):** the action is `lambda:InvokeFunction`, NOT `lambda:InvokeFunctionUrl` -- live-verified in `platform_roles.tf` (#109 comment, lines ~133-144): the Function-URL IAM authorizer checks `InvokeFunction`; `InvokeFunctionUrl` alone is INSUFFICIENT (the IAM simulator falsely reports it allowed). Scope the grant to the reader/writer ARNs; `InvokeFunctionUrl` MAY be retained alongside for AWS-doc alignment but is not sufficient on its own. First CHECK whether #109 already added this to the `github_ci_*` policies; only add if absent. HUMAN-GATED apply (Decision 77/35). |
| terraform/personal/ducklake_lambdas.tf | Confirm (no change expected) | Confirm the PlatformDev `lambda:InvokeFunction` grant on the writer+reader Function URLs landed in #109 (`platform_roles.tf`, verified live 2026-06-09) after the URL-consumer audit (item 1). No edit unless the audit shows a missing consumer grant. HUMAN-GATED. |
| scripts/ops_data_portal.py | Modify | SIGN-OFF (= cutover VP16): flip `_DEFAULT_OPS_STORAGE_BACKEND` `"iceberg"` -> `"ducklake"` (line 71). (rec-2104/rec-2105 source-file) |
| src/common/iceberg_reader.py | Modify | SIGN-OFF: flip `_DEFAULT_OPS_STORAGE_BACKEND` `"iceberg"` -> `"ducklake"` (line 39). |
| scripts/data_quality_runner.py | Modify | SIGN-OFF: flip the inline default `"iceberg"` -> `"ducklake"` (line 81). |
| src/lambdas/ducklake_maintenance/handler.py | Modify | POST-SIGN-OFF (= cutover VP17): remove the TEMPORARY `seed_ops_recommendations` action; redeploy maintenance; confirm the recs closed boundary. (closes rec-2099) |
| AGENTS.md | Modify | Source-of-truth update ATOMIC with sign-off, in TWO parts: (a) ADD that `ops_recommendations` source of truth = DuckLake-on-Neon by DEFAULT (no such wording exists today -- additive; do not search for "flagged" text to drop); AND (b) AMEND the "Warehouse-as-source-of-truth invariant" section so it no longer self-contradicts post-flip -- the blanket "Athena (over Iceberg) is the single source of truth for ALL operational data" claim (line ~96) and the read-cache "rebuilt FROM Athena" line (line ~99) must EXEMPT `ops_recommendations` (recs SoT = DuckLake; the recs read-cache is rebuilt from the DuckLake reader, and the Iceberg-DELETE-resurrection caveat at line ~101 is scoped to the still-Iceberg tables). Decisions/other ops tables stay on Athena; only write surface = `file_rec`/`update_rec` via the portal. |
| docs/PROJECT_CONTEXT.md | Modify | Storage-architecture / source-of-truth flip to recs-on-DuckLake-by-default. |
| docs/runbooks/ducklake-catalog-operations.md | Modify | Rewrite Section 6 (rollback/sign-off) for the post-flip default; add the restore-drill DEFERRAL note + compensating controls (daily `pg_dump`-to-S3, >25h freshness alarm, Neon native PITR, retained Iceberg recs snapshot) pointing to the follow-up rec. ALSO remove the stale `migrate_ops_iceberg_to_ducklake` CLI reference (line ~473, the old direct-Neon sequence) so deleting the script in PHASE 1 leaves no dangling doc reference. |
| docs/ROADMAP-PLATFORM.yaml | Modify | T2.19 recs-slice -> recs-complete; decisions + `ops_session_log`/`ops_execution_plans`/`ops_priority_queue` tracked as follow-ups; ops_compaction retirement still deferred. Update `progress_note`. |
| docs/SESSION_LOG.md | Modify | Session entry. |

## Bundled Recommendations
- **rec-2111** (manual, High) -- **DRIVING REC for the resumption.** "Resume ducklake-ops-finalize PHASE 2/3
  sign-off tail (lambda_attach GREEN; correct oidc.tf grant to lambda:InvokeFunction)." Close at PHASE 3
  bookkeeping (VP16) once sign-off + seed-removal land.
- **rec-2103 + rec-2106** (ci_rca, SLOC): CLOSED at CHECKPOINT A (#108). [done]
- **rec-2104 + rec-2105** (ci_rca, DQ FAIL): CLOSED at CHECKPOINT A (#108/#109) -- row remediated via
  `update_rec` + D64 anchor restored. [done]
- **rec-2107/2108 (SLOC) + rec-2109/2110 (DQ)** (ci_rca): stale duplicates of the above raised after the
  fixes already landed; CLOSED by the connect-rca session (#111) as moot. `ci_rca=0` at preflight. [done]
- **rec-2099** (catalog-reinit / seed cleanup; OPEN, High): closes at PHASE 2 step 15 (= cutover VP17 --
  seed removed, closed boundary confirmed).
- **NEW (filed in PHASE 3):** VP11 catalog-DR restore-drill follow-up -- a HARD GATE that must pass
  before the NEXT ops table migrates to DuckLake (see Risks & Deviations).

## Infrastructure Dependencies
| Item | Detail |
|------|--------|
| Modified resources | `github_ci` OIDC role(s) gain **`lambda:InvokeFunction`** (CORRECTED verb, rec-2111) on the reader (and writer if the audit shows it is needed) Function URL (item 1); PlatformDev grant already landed in #109. OPTIONAL: remove the redundant `AgentPlatformRuntime` inline policy (out-of-band, deferred). No new Lambdas. No IAM WIDENING beyond the `InvokeFunction` grant (narrower than the prior `InvokeFunctionUrl` framing -- `InvokeFunction` is the action the URL authorizer actually checks). |
| Apply posture | HUMAN-GATED via `agent_platform_admin` (Decision 35 + 77). The `InvokeFunction` grant touches IAM -> trips the fail-closed `terraform_apply_guard.py`; present plan to human before apply. If #109 already added the `github_ci` grant, this apply is a no-op (confirm via `terraform plan` showing no changes). |
| Lambda deployment (Decision 79 / CD.16) | `compute_affected_artifacts()` over the real scope returns SIX active artifacts. The 4 DuckLake functions -- `ducklake_writer`, `ducklake_reader`, `ducklake_maintenance`, AND `ducklake_catalog_dr` -- are all built + deployed by `build_lambda --ducklake-only --deploy` (step 11) + smoke-tested. `ducklake_catalog_dr` is NOT byte-equivalent: its manifest bundles `src/common/ducklake_runtime.py` (line 10), so the split changes its zip -- it is rebuilt + redeployed + its existing smoke run. The deploy is sequenced to PHASE 2 because the refactor is behaviour-preserving + flag-gated to `iceberg` -- deploy-deferred-within-plan, NOT a CD.16 deploy-skip. No model IDs touched (deterministic SQL) -> inference-provider validation N/A. |
| Transitively-affected artifacts (Decision 79) | The remaining 2 of the 6 -- `data-pipeline` + `ops-compaction` -- use `includes: - src/` and DELIBERATELY `excludes:` `src/common/ducklake_runtime.py` (DuckLake runtime stays OUT of these minimal/closed-boundary zips). They are affected because the SIGN-OFF `iceberg_reader.py` flip IS bundled (src/common, not excluded), changing their zip; the new `ducklake_scd2_schema.py` is ALSO added to their `excludes[]` so the split does NOT leak DuckLake runtime code in (consistency with the existing `ducklake_runtime.py` exclusion). Verified: `ops_compaction_handler.py` does NOT import `iceberg_reader` / `make_reader` / `OPS_STORAGE_BACKEND` -> NO behavioural delta. They are NOT built by `--ducklake-only`; rebuild for byte-currency (`build_lambda` for those slugs) + run their EXISTING smoke (no new behaviour to verify). Recorded so the change is not silent against Decision 79 (mirrors the predecessor's transitively-affected row). |
| Egress | No Neon 5432 from CC-web; all Postgres-direct ops Lambda-mediated over 443. Reader/writer Function URLs + Athena reads over 443. |
| Timing | PHASE 0/1 = `[pre-deploy]` (merge-first, restores green main); PHASE 2 IAM apply + writer/reader/maintenance deploy = `[pre-deploy]`/`[post-deploy]`; sign-off flip + seed removal = `[post-deploy]`. |

## Acceptance Criteria
- [ ] main full-tier CI is GREEN: `ducklake_runtime.py` < 500 SLOC (behaviour-preserving SPLIT, not a `# complexity-waiver`, Decision 43); `ops_recommendations` DQ PASS; all 4 ci_rca recs (rec-2103/2104/2105/2106) closed.
- [ ] `validate_sloc_limits` runs in the `--pre` tier (mirrors `validate_cc_limits` / rec-859) so a future SLOC breach is caught pre-merge, not post-merge.
- [ ] The split is behaviour-preserving: DDL/MERGE SQL byte-identical to pre-split; all 4 DuckLake bundles (writer/reader/maintenance/catalog_dr) INCLUDE the new module and the 2 closed-boundary zips (data-pipeline/ops-compaction) EXCLUDE it (`--check-bundles` green across every active artifact).
- [ ] The DQ fix is consistency-restoration + data remediation, NOT gate-weakening (Decision 55/72): the offending row is corrected via `update_rec`; the D64 `2026-05-01` anchor is RESTORED (value unchanged) on `automatable`+`risk` to match every other column check.
- [ ] Dead code removed: `scripts/migrate_ops_iceberg_to_ducklake.py` + its test deleted (superseded by the maintenance seed); `get_changed_files()` drops deleted paths before ruff.
- [ ] PlatformDev `lambda:InvokeFunction` confirmed live (landed #109); all reader/writer Function-URL consumers audited; the `github_ci` OIDC role can read recs over the reader URL for CI/DQ via the `lambda:InvokeFunction` grant (CORRECTED verb, rec-2111 -- NOT `InvokeFunctionUrl`) (item 1).
- [ ] Connectivity readiness PROVEN before sign-off: `connect_probe` reader+writer `phase_reached=attach ok=True`; `lambda_attach` GREEN; the 10-15s ATTACH recognised as DuckLake cold-resume (within budget), not a hang (connect-rca #111).
- [ ] CUTOVER SIGNED OFF: `_DEFAULT_OPS_STORAGE_BACKEND` flipped `iceberg`->`ducklake` in all 3 sites (`ops_data_portal.py:71`, `iceberg_reader.py:39`, `data_quality_runner.py:81`); `--selftest-roundtrip` green; `AGENTS.md` + `docs/PROJECT_CONTEXT.md` + runbook updated atomically to recs-on-DuckLake-by-default.
- [ ] `seed_ops_recommendations` REMOVED from the maintenance handler + redeployed; recs closed boundary confirmed; rec-2099 closed.
- [ ] Per-Lambda V3 (Decision 79): the 4 DuckLake functions (writer/reader/maintenance/catalog_dr) rebuilt + deployed + smoked (catalog_dr is NOT byte-equivalent -- it bundles the split runtime); `data-pipeline` + `ops-compaction` rebuilt for byte-currency + existing smoke (no behavioural delta).
- [ ] The VP11 restore-drill deferral is recorded as an EXPLICIT deviation (Decision 81 cl.7) with compensating controls AND a follow-up rec filed as a HARD GATE before the next ops table migrates.
- [ ] Scope boundary unchanged from the cutover plan: ONLY `ops_recommendations`; decisions + `ops_session_log`/`ops_execution_plans`/`ops_priority_queue` DEFERRED + on Iceberg/Athena; ops_compaction stays live; telemetry out of scope (Decision 78 cl.2).
- [ ] Rollback still real: `OPS_STORAGE_BACKEND=iceberg` restores the recs Iceberg path (intact) -- rehearsed before sign-off.

## Verification Plan
**Steps 1-8 are COMPLETE (PHASE 0+1, landed #108/#109, CHECKPOINT A green). Retained for audit; do
NOT re-run them. The connect-rca session (#111) added a connectivity-readiness gate -- see step 9a.
A resuming agent starts at step 9.**

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [DONE #108] | Unit-test the SCD2 schema split: new module + runtime; DDL/MERGE byte-identical to pre-split | `bin/venv-python -m pytest tests/test_ducklake_scd2_schema.py tests/test_ducklake_runtime.py -q` | DONE: split landed, builders byte-identical | n/a (landed) |
| 2 | [DONE #108] | Assert `ducklake_runtime.py` under the SLOC limit, NO waiver (count directly -- `validate_sloc_limits` puts per-file detail on stdout, not the `failed` list) | `bin/venv-python -c "p='src/common/ducklake_runtime.py'; ls=open(p,encoding='utf-8').read().splitlines(); sloc=len([l for l in ls if l.strip() and not l.strip().startswith('#')]); w=any('complexity-waiver: decision-43' in l for l in ls[:10]); print('SLOC=%d waiver=%s' % (sloc,w), 'PASS' if sloc<=500 and not w else 'FAIL')"` | DONE: `SLOC=432 waiver=False PASS` | n/a (landed) |
| 3 | [DONE #108] | Assert the SLOC gate runs in `--pre` AND `get_changed_files()` drops deleted paths | `bin/venv-python -m pytest tests/test_validate.py -q` | DONE: both assertions pass | n/a (landed) |
| 4 | [DONE #108] | Validate manifests; `--check-bundles` import-resolves EVERY active artifact | `bin/venv-python -m scripts.lambda_manifest --validate && bin/venv-python -m scripts.lambda_manifest --check-bundles` | DONE: `ducklake_scd2_schema.py` bundles into writer/reader/maintenance/catalog_dr; excluded from data-pipeline/ops-compaction | n/a (landed) |
| 5 | [DONE #108] | Identify + remediate the offending `ops_recommendations` row, restore the anchor, re-run DQ | `update_rec` the row; then `bin/venv-python -m scripts.data_quality_runner && bin/venv-python -c "import json;print(json.load(open('logs/debug/dq-latest.json'))['verdict'])"` | DONE: DQ 0 violations; D64 anchor restored on `automatable`+`risk` | n/a (landed) |
| 6 | [DONE #108] | Full presubmit green (authoritative main gate) | `bin/venv-python -m scripts.validate` | DONE: PASS. **MERGE CHECKPOINT A reached; rec-2103/2104/2105/2106 CLOSED** | n/a (landed) |
| 7 | [DONE #108] | Confirm no live CODE refs, then delete the migrate script + its test; re-validate | `grep -rn "migrate_ops_iceberg_to_ducklake" ...` then delete then `bin/venv-python -m scripts.validate --pre` | DONE: `scripts/migrate_ops_iceberg_to_ducklake.py` + test deleted; `--pre` PASS | n/a (landed) |
| 8 | [DONE #109] | Confirm the `AgentPlatformRuntime` inline policy is out-of-band (NOT in `terraform/personal/`) -> removal DEFERRED | `grep -rn "AgentPlatformRuntime" terraform/personal/*.tf \|\| echo "out-of-band, deferred"` | DONE: out-of-band per terraform/CLAUDE.md; deferred. PlatformDev `lambda:InvokeFunction` grant landed in #109 | n/a (landed) |
| 9a | [pre-deploy] | **CONNECTIVITY READINESS (connect-rca #111).** Run the phased `connect_probe` against reader+writer; confirm `phase_reached=attach ok=True` and that ATTACH latency is cold-resume (~10-15s), not a hang. This is the gate the previous agent lacked -- it proves connectivity is healthy BEFORE deploy/flip. | `bin/venv-python -m scripts.ducklake_neon_smoke_test --connect-probe` (SigV4-invokes reader+writer `connect_probe`; diagnostic) | Both probes `phase_reached=attach failed_phase=None ok=True`; `auth_ms` sub-second; `attach_ms` < 18s (cold-resume). `lambda_attach` GREEN | A probe stops at `dns`/`tcp`/`auth` -> that named phase is the real fault (endpoint/SG/secret); STOP + RCA. ATTACH > budget -> raise `DUCKLAKE_CONNECT_TIMEOUT_S` or investigate Neon resume |
| 9 | [pre-deploy] | Confirm PlatformDev `lambda:InvokeFunction` works live (reader-URL recs read, landed #109) + audit all reader/writer URL consumers | `OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-read` (reads recs via the reader Function URL under PlatformDev) then `grep -rn "InvokeFunction\|FunctionUrl\|DUCKLAKE_READER_URL\|DUCKLAKE_WRITER_URL" scripts/ src/ terraform/personal/` to enumerate consumers | `--selftest-read` PASS (reader URL returns recs under PlatformDev); consumer list complete; the `github_ci` grant gap identified (if any) | 403/AccessDenied for PlatformDev -> unexpected (grant landed #109), re-check ARNs; for `github_ci` -> step 10 is the fix |
| 10 | [pre-deploy] | HUMAN-GATED terraform apply: confirm-or-add the `github_ci` **`lambda:InvokeFunction`** grant (CORRECTED verb, rec-2111; NOT `InvokeFunctionUrl`) | `terraform -chdir=terraform/personal plan` (review) then `apply` if changes (admin) | Grant present (added if #109 did not already); NO unexpected destroys; guard passes. If `plan` shows no changes, grant already landed -> no-op | Unexpected destroy/IAM -> STOP (Decision 77 guard) |
| 11 | [post-deploy] | Rebuild + deploy the 4 DuckLake functions with the split runtime (NOTE: writer+reader were already redeployed live in #111 with the split runtime + `connect_timeout`; this step ensures byte-currency across ALL 4 and redeploys `ducklake_maintenance` + `ducklake_catalog_dr`, which were NOT re-smoked in the connect-rca session); rebuild the 2 transitively-affected artifacts for byte-currency + run their existing smoke | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` (writer/reader/maintenance/catalog_dr) then rebuild + smoke `data-pipeline` + `ops-compaction` | 4 DuckLake functions live with the refactored runtime + `connect_timeout` (incl. `ducklake_catalog_dr` -- NOT byte-equivalent, it bundles the split runtime); data-pipeline + ops-compaction rebuilt, existing smoke green, no behavioural delta | Deploy error -> check the function map; behavioural delta in the transitive pair -> STOP (unexpected import, Decision 79) |
| 12 | [post-deploy] | DQ over DuckLake green (= cutover VP14) | `OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.data_quality_runner && bin/venv-python -c "import json;print(json.load(open('logs/debug/dq-latest.json'))['verdict'])"` | `PASS`; recs clause-8 checks green; decisions/others unaffected | FAIL -> RCA (Decision 55); cutover blocked |
| 13 | [post-deploy] | Rollback rehearsal (= cutover VP15): both backends serve recs reads | `OPS_STORAGE_BACKEND=iceberg bin/venv-python -m scripts.ops_data_portal --selftest-read && OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-read` | Both serve recs reads; Iceberg path + ops_compaction intact | Rollback broken -> fix BEFORE sign-off |
| 14 | [post-deploy] | CUTOVER SIGN-OFF (= cutover VP16): assert outbox empty, flip the 3 defaults, round-trip | assert `logs/.ops-outbox` empty, then flip the 3 sites, then `bin/venv-python -m scripts.ops_data_portal --selftest-roundtrip` | A `file_rec`-shaped write lands in DuckLake + reads back; no Iceberg recs write | Outbox non-empty -> re-parity; roundtrip fails -> revert the flag, RCA |
| 15 | [post-deploy] | POST-SIGN-OFF (= cutover VP17): remove the seed + redeploy maintenance; confirm closed boundary | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy && bin/venv-python -m scripts.validate && grep -rn "OpsWriter().write" scripts/ src/ | grep -i "ops_recommendations\|file_rec\|update_rec" | grep -v test` | Seed action gone; validate PASS; no live Iceberg recs write path (only the flagged rollback shim) | A recs bypass remains -> route through the writer; close rec-2099 |
| 16 | [post-deploy] | File the VP11 restore-drill follow-up rec (hard gate) + close rec-2099; update ROADMAP + SESSION_LOG | `file_rec(...)` for the restore-drill gate; `update_rec` rec-2099 closed; edit ROADMAP/SESSION_LOG | Rec filed with the "must pass before next ops table" framing; rec-2099 closed; roadmap recs-slice marked complete | Portal unreachable -> outbox + retry per Decision 51 |

**VP11 (cutover restore-drill): DEFERRED -- not executed in this plan.** Tracked by the step-16 follow-up
rec; rationale + compensating controls in Risks & Deviations.

## Constraints
- **The DQ fix is consistency-restoration, NOT gate-weakening (Decision 55/72/64).** The offending row is
  REMEDIATED via `update_rec` (the real data fix); the D64 `2026-05-01` anchor is RESTORED (value
  unchanged) so `automatable`+`risk` match every other column check. Do NOT loosen, drop, or date-shift
  any check to make CI pass.
- **The SLOC fix is a behaviour-preserving SPLIT, NOT a `# complexity-waiver` (Decision 43).** The
  extracted module MUST bundle into writer/reader/maintenance (manifest `includes[]`) or they import-fail.
- **ci_rca recs are addressed in THIS `/plan` -> `/implement` flow, never inline-patched (Decision 72/73
  + merge protocol).** This plan IS that required review.
- Single-Portal invariant (Decision 78 cl.6 / 81 cl.4): the sign-off flip changes only the DEFAULT
  transport; the `file_rec`/`update_rec` caller surface is unchanged; no import/bypass surface is added.
- Closed boundary for recs (Decision 81 cl.7): post-flip, recs reads/writes transit reader/writer only;
  no Athena escape hatch; break-glass = audited PlatformAdmin on Neon+S3.
- Per-Lambda V3 (Decision 79 / CD.16): `compute_affected_artifacts()` returns SIX active artifacts -- the 4
  DuckLake functions (writer/reader/maintenance/catalog_dr, all built by `--ducklake-only`; catalog_dr is
  NOT byte-equivalent -- it bundles the split runtime) plus the transitively-affected `data-pipeline` +
  `ops-compaction` (bundle the changed `src/common` files; rebuild for byte-currency + existing smoke, no
  behavioural delta). The PHASE 0 split's deploy is deploy-deferred-within-plan to PHASE 2
  (behaviour-preserving, flag-gated) -- not a deploy-skip.
- Terraform apply human-gated (Decision 35 + 77); the `github_ci` `lambda:InvokeFunction` grant (corrected
  verb, rec-2111) trips the fail-closed guard.
- Scope boundary unchanged: ONLY `ops_recommendations`; decisions + the other ops tables DEFERRED on
  Iceberg/Athena; ops_compaction stays live. Telemetry out of scope (Decision 78 cl.2).
- Decision-82 churn budget untouched: the optional Neon warm-up (PHASE 1) is a pre-warm addition only;
  `CHURN_WRITERS=4` / 2000ms / 0.20 unchanged.
- No rescue agents / workaround loops (Decision 55): a DQ / deploy / sign-off / roundtrip failure STOPS
  the work -- do not relax a threshold or skip a gate.
- No emojis; ASCII hyphens; ruff line length 127; type hints; `bin/venv-python` for all Python.

## Risks & Deviations
- **DEVIATION (Decision 81 cl.7) -- catalog-DR restore drill deferred at sign-off.** Decision 81 clause 7
  ratifies "catalog DR = a daily PITR export to a dedicated S3 bucket with a TESTED restore runbook."
  This plan signs off the recs cutover (step 14) with the `pg_restore` restore drill (cutover VP11)
  UNDRILLED, because the pgclient Lambda layer ships `pg_dump` but not `pg_restore`; adding it needs a
  non-CC-web operator AL2023 layer rebuild. The deviation is ACCEPTED (human-directed) with compensating
  controls: (1) the daily `pg_dump`-to-S3 export runs; (2) the >25h freshness CloudWatch alarm fires if
  it stops; (3) Neon's own native PITR / branch backups provide an independent restore path; (4) the
  Iceberg recs snapshot is retained as the flagged rollback target. **Tracking:** a follow-up rec is filed
  in PHASE 3 (step 16) as a HARD GATE -- the restore drill MUST pass before the NEXT ops table migrates to
  DuckLake. Recorded here per the decision-scout WARN so the deviation is auditable rather than silent.
- **NOTE (Decision 79 / CD.16) -- split deploy deferred within-plan.** PHASE 0 edits the Lambda-packaged
  `ducklake_runtime.py` + the 3 manifests but the writer/reader/maintenance redeploy happens in PHASE 2
  (steps 11/15). This is sequencing, not a deploy-skip: the change is behaviour-preserving + flag-gated to
  `iceberg`, and the same plan deploys it. A reviewer should not read PHASE 0's merge as a CD.16 violation.
- **RISK -- cutover-window concurrency.** As in the cutover plan, a `file_rec` issued by another session
  between the PHASE 0 merge and the step-14 flip writes to Iceberg (still default until the flip). The
  step-14 outbox-empty assertion is the mitigation; a sole-operator window is assumed.

## Context
- **Connectivity resolution (connect-rca #111 -- why this plan is now unblocked):** The previous agent
  could not complete the PHASE 2 sign-off because the live ops Lambdas appeared to hit a Neon blackhole
  (120s hangs on connect). RCA (PR #110 plan, PR #111 `c49d2b0`) found the real cause: `libpq_conninfo`
  set NO `connect_timeout`, so DNS/TCP/AUTH/ATTACH failures all blocked to the 120s Lambda wall and were
  indistinguishable. A phased probe proved the postgres connect is sub-second (AUTH 131-728ms); the 10-16s
  was DuckDB extension LOAD + S3 setup + Neon scale-to-zero cold-resume, WITHIN budget. **No Neon endpoint,
  project, or credential fix was needed.** Fix shipped: bounded `connect_timeout=10s` (env
  `DUCKLAKE_CONNECT_TIMEOUT_S`) in `ducklake_runtime.libpq_conninfo`, plus `src/common/ducklake_connect_probe.py`
  (phased DNS->TCP->AUTH->ATTACH diagnostic) wired as a `connect_probe` action on writer+reader handlers
  (dispatched via `_CONNECTIONLESS_ACTIONS` before the normal open, so it runs even if a real open would hang)
  and a `--connect-probe` gate in the smoke driver. Live-verified GREEN. Implementing-agent takeaways:
  (1) a 10-15s ATTACH is cold-resume, NOT a fault -- do not treat it as a hang; (2) use step 9a's
  `connect_probe` as the connectivity-readiness gate before deploy/flip; (3) the `github_ci` oidc.tf grant
  verb is `lambda:InvokeFunction`, not `InvokeFunctionUrl` (rec-2111).
- **Predecessor:** `PLAN-ducklake-ops-cutover.md` (merged PR #106) landed the recs
  runtime/writer/reader/maintenance + the maintenance seed + the cutover VP1-17 scaffolding. This plan
  finalises the two remaining gap-classes: (A) main full-tier CI red for 5 runs since the sequence began
  (4 ci_rca recs); (B) the live cutover ~90% done but not signed off.
- **Why the SLOC breach:** parameterizing the runtime for `ops_recommendations` (cutover plan) pushed
  `ducklake_runtime.py` to 589 SLOC (576 at ci_rca filing) > the D43 500 limit. The split restores the
  limit without losing the parameterization.
- **Refactor seam (principled separation, not an SLOC-driven cut):** the split follows the pure/impure
  boundary. `ducklake_scd2_schema.py` takes the I/O-free schema-spec + SQL-string builders + the pure
  `schema_gate` validator; `ducklake_runtime.py` keeps everything bound to a live DuckDB connection
  (connect / transaction / OCC / reads / metrics). This yields high cohesion (all SQL generation in one
  module, all execution in the other), low one-directional coupling (runtime imports schema, never the
  reverse), and a DB-free-unit-testable schema layer. The seam is verifiable: VP1 asserts the extracted
  builders emit byte-identical DDL/MERGE SQL, so a wrong seam (e.g. dragging a connection-bound function
  into the "pure" module, or leaving a builder behind) shows up as an import cycle or a test failure.
- **Why the gate missed it pre-merge:** `validate_sloc_limits` is presubmit-only (`validate.py:2234`); the
  cyclomatic-complexity twin is ALSO in `--pre` (`validate.py:2676`, rec-859 `earliest_viable_gate="pre"`).
  PR #106 passed `--pre`, failed the full tier post-merge. This plan adds SLOC to `--pre` to close the gap.
- **The DQ failure:** one `ops_recommendations` row with NULL `automatable`, NULL `risk`, `context` below
  the quality threshold. The `context` check is already D64-anchored yet still flags the row -> the row is
  POST-2026-05-01 (a genuine bad row to remediate). The `automatable`/`risk` not_null checks anomalously
  LACK the anchor; restoring it matches every other column check. Triage the exact row at implementation;
  remediate via `update_rec`; restore the anchor. (rec-2104/rec-2105 attribute the failure to
  `ops_data_portal.py`, the write path that produced the row -- which is in Scope for the flip.)
- **VP11 deferral:** human-accepted; tracked by a follow-up rec (PHASE 3) rather than a decision amendment,
  per human direction. Decision-scout WARN (D81 cl.7) folded as an explicit deviation with compensating
  controls (see Risks & Deviations).
- **Decisions cited:** 43 (SLOC split not waiver), 81 (CD.33 cutover/boundary/flip; cl.7 DR), 79 (CD.16
  per-Lambda manifests+deploy), 64 (2026-05-01 anchor preserved), 70 (portal `update_rec` remediation),
  72+73 (ci_rca via `/plan`, forward-fix), 67 (STRATEGIC suspended -> single IMPLEMENTATION plan), 60
  (`--pre` vs presubmit tiers), 78 (Single-Portal transport-agnostic; telemetry out of scope), 77+35
  (human-gated apply), 82 (churn budget untouched), 48 (V3), 83 (branch protection; post-merge full tier
  non-wedging so forward-fix holds).
- **Decision-scout verdict:** FLAGS_FOUND. Flag 1 (D81 cl.7 restore-drill, WARN) -> accepted deviation +
  follow-up rec. Flag 2 (D79 deploy deferral, NOTE) -> deploy-deferred-within-plan to PHASE 2. Both folded
  above.
- **Preflight (resumption, 2026-06-09):** `ci_rca=0` (all 4 original + 4 connect-rca dupes closed); main
  0 behind/0 ahead. Driving rec-2111 + rec-2099 open. No Neon 5432 egress from CC-web; Lambda-mediated over 443.
  (Original authoring was on branch `claude/happy-wozniak-r7fcgv`; PHASE 0+1 landed via #108/#109.)

## Pre-Implementation Checklist (resumption -- PHASE 0+1 already landed)
- [ ] Branch confirmed not on `main` (resuming agent is on its own harness session branch)
- [ ] This plan's **Current State** block read -- PHASE 0+1 landed (#108/#109), connectivity unblocked (#111); resumption starts at VP9
- [ ] `docs/PROJECT_CONTEXT.md` + DECISIONS.md (43, 81, 79, 64, 70, 72, 73, 67, 60, 78, 77, 35, 82, 48, 83) read
- [ ] `PLAN-ducklake-ops-cutover.md` read (predecessor; cutover VP numbering)
- [ ] Resumption scope files located + readable (the 3 flip sites, maintenance handler, oidc.tf, ducklake_lambdas.tf, the 3 docs, roadmap, session log)
- [ ] **Step 9a connectivity-readiness gate run FIRST**: `connect_probe` reader+writer `phase_reached=attach ok=True` (the gate the previous agent lacked)
- [ ] `compute_affected_artifacts(changed_files)` run -- confirm the SIX affected active artifacts (4 DuckLake functions incl. `ducklake_catalog_dr` + the transitively-affected `data-pipeline` + `ops-compaction`)
- [ ] `aws lambda invoke` / reader-URL read confirmed under the `agent_platform` role over 443 (PlatformDev `lambda:InvokeFunction` landed #109)

## Ordered Execution Steps
**Steps 1-7 are COMPLETE (PHASE 0+1, landed #108/#109). A resuming agent STARTS AT STEP 7.5
(connectivity gate) then step 8.**
1. ~~**PHASE 0a -- `src/common/ducklake_scd2_schema.py`:** extract the SCD2 schema/SQL layer (pure move);
   re-import in `ducklake_runtime.py`; < 500 SLOC.~~ DONE (#108; runtime now 432 SLOC).
2. ~~**PHASE 0a -- manifests (6):** add `ducklake_scd2_schema.py` to `includes[]` (writer/reader/maintenance/catalog_dr)
   + `excludes[]` (data-pipeline/ops-compaction).~~ DONE (#108).
3. ~~**PHASE 0b -- `scripts/validate.py`:** `validate_sloc_limits` -> `--pre`; `get_changed_files()` drops deleted paths.~~ DONE (#108).
4. ~~**PHASE 0c -- `config/agent/data_quality/ops.yaml`:** restore the `2026-05-01` anchor; remediate the row via `update_rec`.~~ DONE (#108).
5. ~~**PHASE 0 tests:** `tests/test_ducklake_scd2_schema.py`; update runtime + validate tests.~~ DONE (#108).
6. ~~**VP1-6; presubmit green. MERGE CHECKPOINT A** -- close rec-2103/2104/2105/2106.~~ DONE (#108/#109; `ci_rca=0`).
7. ~~**PHASE 1 -- cleanup:** delete `scripts/migrate_ops_iceberg_to_ducklake.py` + its test; `AgentPlatformRuntime`
   inline policy DEFERRED (out-of-band).~~ DONE (#108). (Optional Neon churn-gate warm-up: still optional, not done.)
7.5. **RESUME HERE -- connectivity-readiness gate (connect-rca #111):** run VP9a `connect_probe` on reader+writer;
   confirm `phase_reached=attach ok=True` and ATTACH ~10-15s = cold-resume (not a hang). STOP + RCA if any
   probe stops at dns/tcp/auth. This is the gate the previous agent lacked.
8. **PHASE 2 -- IAM:** confirm PlatformDev `lambda:InvokeFunction` live (landed #109) + audit URL consumers;
   confirm-or-add the `github_ci` **`lambda:InvokeFunction`** grant in `oidc.tf` (CORRECTED verb, rec-2111 --
   NOT `InvokeFunctionUrl`). HUMAN-GATED terraform apply (after plan review; no-op if #109 already added it).
9. **PHASE 2 -- deploy:** rebuild + deploy the 4 DuckLake functions (writer/reader/maintenance/catalog_dr)
   with the split runtime (`build_lambda --ducklake-only --deploy`); rebuild the transitively-affected
   `data-pipeline` + `ops-compaction` for byte-currency + run their existing smoke (no behavioural delta, Decision 79).
10. **PHASE 2 -- sign-off gates:** run VP12 (DQ over DuckLake), VP13 (rollback rehearsal), VP14 (SIGN-OFF
    flip of the 3 defaults + `--selftest-roundtrip`), VP15 (remove seed + redeploy + closed-boundary confirm).
    Any V3 gate failing unrecoverably -> STOP + RCA (Decision 55).
11. **PHASE 2 -- docs (atomic with VP14):** `AGENTS.md` + `docs/PROJECT_CONTEXT.md` + runbook flip to
    recs-on-DuckLake-by-default; runbook Section 6 rewrite + restore-drill deferral note + compensating controls.
12. **PHASE 3 -- bookkeeping:** file the VP11 restore-drill follow-up rec (hard gate); close rec-2099.
    `docs/ROADMAP-PLATFORM.yaml` T2.19 recs-slice complete; `docs/SESSION_LOG.md` entry.
13. **Execute Verification Plan** -- run each step in order. Loop until pass. If a V3 gate fails
    unrecoverably, stop and analyze root cause (Decision 55).
14. **Report:** SLOC before/after, `--pre` SLOC-gate proof, DQ verdict + remediated row, the 4+1 rec
    closures, the `lambda:InvokeFunction` consumer audit, deploy confirmations, DQ-over-DuckLake verdict, rollback
    rehearsal, sign-off roundtrip evidence, seed-removal confirmation, the filed VP11 follow-up rec id, and
    the explicit deferred-scope list.
