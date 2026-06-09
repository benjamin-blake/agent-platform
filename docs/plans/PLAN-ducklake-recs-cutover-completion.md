# Plan

## Intent
Complete the T2.19 `ops_recommendations` DuckLake cutover across every read and write surface so the ducklake reader/writer Lambdas become the SOLE recs data path (Decision 81 cl.7 closed boundary). This restores the operational-feedback observability the self-improving loop depends on (preflight rec surfacing, ci-rca diagnosis) and eliminates a reachable write split-brain that can silently divert recs to the dead Iceberg backend.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-recs-cutover-completion.md

## Phase
Platform T2.19 (DuckLake recs cutover) completion + T2.7 (recs `ops_recommendations_current` view retirement -- scoped partial; sibling decisions/priority-queue views remain until those tables migrate).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/ops_writer.py | Modify | Remove `ops_recommendations` from `_OPS_TABLE_NAMES`; hard-reject recs in `write()`/`compact()`; stop maintaining the `ops_recommendations_current` view in `_refresh_view`. Net: OpsWriter can no longer stage/compact recs to Iceberg. |
| scripts/sync_ops.py | Modify | `drain()` must skip (loud-warn) the `ops_recommendations` outbox dir instead of routing it to `OpsWriter.write()`. Remove the recs Athena fallback: `_pull_single_table_athena` recs path, `_TABLE_TO_VIEW["ops_recommendations"]` (:46), and the recs S3-staging guard (~:456-478). |
| scripts/ops_data_portal.py | Modify | Remove the Athena fallback branch in `_fetch_rec_from_athena` for the ducklake backend (reader-only, loud-fail); make `_drain_outbox`/`sync()` exclude the recs outbox; add a loud-fail guard to `_delete_postmortems_from_iceberg`/`purge_postmortems_for` so they raise on the ducklake backend rather than silently DELETE the wrong (Iceberg) store. Consolidate the duplicate `_resolve_function_url_via_api` with iceberg_reader (rec-2116). |
| scripts/session_preflight.py | Modify | Remove the stale Athena `ops_recommendations_current` fallbacks for recs at the 5 read sites (`_count_recommendations_athena` :461-466, `_fetch_ci_rca_recs`/`_since`, `_check_forward_fix_recursion`, `_check_budget_bypass_alert`) and the raw no-reader query in `read_context_files` (:1086). On reader-unreachable emit a LOUD `recs_read_status: "reader_unreachable"` degraded signal -- never a false zero (Decision 55). |
| src/data/handlers/scheduled_agent_handler.py | Modify | Repoint `_preload_rec_curator_context` (:302) from the Athena `trading_formulas_db.ops_recommendations_current` query to `make_reader().current_state("ops_recommendations", row_filter="status = 'open'")`. (Lambda currently DISABLED, but remediated so re-enable does not resurrect a non-compliant read.) |
| src/data/handlers/ops_compaction_handler.py | Modify | Exclude `ops_recommendations` from the compacted table set (the module is already marked DEPRECATED; the recs code path must be inert). |
| src/common/iceberg_reader.py | Modify | Add an SSM resolution step to `_reader_url()` (and the writer equivalent): resolution order becomes env (`DUCKLAKE_READER_URL`) -> SSM parameter (path from the Lambda manifest `runtime_config[]`) -> `terraform output` -> `lambda:GetFunctionUrlConfig`. House the single shared `_resolve_function_url_via_api` here (rec-2116). |
| src/lambdas/ducklake_reader/manifest.yaml | Modify | Declare `runtime_config: ["/agent-platform/ducklake/reader_url"]` (Decision 79 SSOT). |
| src/lambdas/ducklake_writer/manifest.yaml | Modify | Declare `runtime_config: ["/agent-platform/ducklake/writer_url"]`. |
| terraform/personal/ducklake_lambdas.tf | Modify | Add `aws_ssm_parameter` resources publishing the reader/writer Function URLs to `/agent-platform/ducklake/reader_url` and `/writer_url` (value = `aws_lambda_function_url.*.function_url`). |
| terraform/personal/platform_roles.tf | Modify | Add a scoped read-only `ssm:GetParameter` statement on `arn:aws:ssm:eu-west-2:<acct>:parameter/agent-platform/ducklake/*` to PlatformDev, with an inline comment citing Decision 81 (endpoint-discovery only, not a data-plane expansion). |
| terraform/personal/main.tf | Modify | DROP the `ops_recommendations_current` Athena/Glue view DDL (:289-298) per read-engine.yaml T2.7. Gated to land AFTER the reader-only read path (slice 2). |
| .github/workflows/ci-rca.yml | Modify | After "Fetch failed run logs", assert `test -s /tmp/ci-rca-failed.log`; on empty, retry with backoff for the `workflow_run` log-availability race, then fail loudly so the agent is never invoked on a 0-byte log. Resolves rec-2117 + rec-2118. |
| scripts/validate.py | Modify | Extend `validate_warehouse_write_sources` to FORBID `OpsWriter().write("ops_recommendations" ...)` (and `.compact("ops_recommendations" ...)`) anywhere -- a table-specific block that the current whitelist-based guard does not provide. |
| docs/contracts/ops-data-store.md | Modify | Update the recs section: source of truth = DuckLake via the closed reader/writer boundary; remove the OpsWriter/Iceberg recs description. |
| docs/contracts/read-engine.yaml | Modify | Mark the recs `_current`-view retirement done (scoped partial); record that `ops_decisions_current`/`ops_priority_queue_current` retire in their own cutovers; recs reads = DuckLake closed boundary. |
| docs/ARCHITECTURE-WORKFLOW.md | Modify | Lines ~375/381: recs no longer read via the `ops_recommendations_current` Athena view; describe the DuckLake reader path. |
| config/lambda/ducklake/field_semantics.yaml | Modify | Relabel `current_table: ops_recommendations_current` (:184) to avoid collision with the now-dropped Iceberg view name (cosmetic/SSOT hygiene). |
| tests/test_ops_writer.py | Modify | Lock: recs not in `TABLE_NAMES`; `write("ops_recommendations", ...)` and `compact("ops_recommendations")` are rejected/inert. |
| tests/test_sync_ops.py | Modify | Lock: `drain()` skips the recs outbox dir and never calls `OpsWriter.write("ops_recommendations", ...)`. |
| tests/test_ops_data_portal.py | Modify | Lock: `_fetch_rec_from_athena` is reader-only on the ducklake backend; `_drain_outbox` excludes recs; postmortem-DELETE loud-fails on ducklake. |
| tests/test_ops_compaction_handler.py | Modify | Lock: recs excluded from compaction. |
| tests/test_session_preflight.py | Modify | Lock: reader-unreachable yields the loud degraded signal (not a false zero) at every recs read site, incl. :1086. |
| tests/test_validate.py | Modify | Lock: the guard fails on an injected `OpsWriter().write("ops_recommendations", ...)` call site. |
| tests/test_iceberg_reader.py | Modify | Lock: SSM resolution (env unset, terraform absent, SSM param present -> URL resolved via `ssm:GetParameter`, mocked). |

## Bundled Recommendations
- **rec-2117** (open, ci_rca, Critical) -- resolved by the ci-rca.yml log-fetch guard (slice 4).
- **rec-2118** (open, ci_rca, Critical) -- resolved by the same guard.
- **rec-2116** (open, code-review) -- consolidate the duplicated `_resolve_function_url_via_api` helper across portal and iceberg_reader; folded into slice 3 (the SSM resolver work touches that code).

## Infrastructure Dependencies
| Resource | File | Change | Timing | Apply routing |
|---|---|---|---|---|
| `aws_ssm_parameter` reader_url / writer_url | terraform/personal/ducklake_lambdas.tf | create | post-merge | Sandbox auto-apply (non-IAM, non-destroy) behind the fail-closed guard + subagent plan review (Decision 77) |
| PlatformDev `ssm:GetParameter` statement | terraform/personal/platform_roles.tf | modify (IAM) | post-merge | MANUAL admin-apply -- the IAM-change arm of `terraform_apply_guard.py` is fail-closed (Decision 77); surface the plan output to the human |
| DROP `ops_recommendations_current` view DDL | terraform/personal/main.tf | delete (DML) | post-merge, AFTER slice 2 lands | Auto-apply (view drop is DML, not destroy/IAM/trust) -- but ordering-gated on reader-only reads first |

Lambda handlers (`ducklake_reader`/`ducklake_writer`) are NOT code-changed -- only their manifests' `runtime_config[]` declarations. The manifest is build/SSOT metadata consumed by the client-side `make_reader` resolver, not the Lambda at runtime, so no zip rebuild/redeploy is required. The Decision-79 per-Lambda V3 obligation is satisfied by the post-apply live smoke (VP steps 9-10) confirming the reader/writer Function URLs still serve under the new discovery path.

## Acceptance Criteria
- [ ] `ops_recommendations` is absent from `scripts/ops_writer.py` `_OPS_TABLE_NAMES`; `OpsWriter.write`/`compact` reject or no-op for recs.
- [ ] `sync_ops.drain` and `ops_data_portal._drain_outbox` never write recs to Iceberg (skip + loud-warn on the recs outbox dir).
- [ ] No recs read path falls back to the Athena `ops_recommendations_current` view; reader-unreachable yields a loud degraded signal, never a false `0`/`[]`.
- [ ] `make_reader()` resolves the reader Function URL with NO `DUCKLAKE_READER_URL` env var and NO terraform binary present, running as the PlatformDev (`agent_platform`) profile.
- [ ] `session_preflight` surfaces the open ci_rca recs (rec-2117, rec-2118) under "CI RCA Recs (open)" when run as PlatformDev.
- [ ] `.github/workflows/ci-rca.yml` never invokes the agent on a 0-byte log (asserts non-empty, retries, then fails loudly).
- [ ] `scripts/validate.py` fails when any non-portal site calls `OpsWriter().write("ops_recommendations", ...)`.
- [ ] The Athena `ops_recommendations_current` view is dropped and no compliant consumer remains.
- [ ] `_delete_postmortems_from_iceberg`/`purge_postmortems_for` raise loudly on the ducklake backend (no silent wrong-backend DELETE); a follow-on rec is filed for the real cutover.
- [ ] Docs/contracts describe recs as DuckLake-via-closed-boundary; the deep-frozen `.github/copilot-instructions.md` is NOT edited.
- [ ] Full presubmit (`bin/venv-python -m scripts.validate`) is green.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | OpsWriter rejects recs | `bin/venv-python -m pytest tests/test_ops_writer.py -k "recs_rejected or recs_not_in_table_names" -q` | PASS -- recs not in `TABLE_NAMES`; `write`/`compact` reject recs | recs still stageable to Iceberg -> finish slice 1 edits |
| 2 | [pre-deploy] | Outbox drain skips recs | `bin/venv-python -m pytest tests/test_sync_ops.py -k "drain_skips_recs" -q` | PASS -- `drain()` never calls `OpsWriter.write("ops_recommendations", ...)` | drain still routes recs -> add the skip/loud-warn branch |
| 3 | [pre-deploy] | Reader-only reads, loud degraded not false zero | `bin/venv-python -m pytest tests/test_session_preflight.py -k "recs_degraded_not_false_zero" -q` | PASS -- reader-unreachable yields `reader_unreachable`, not `0`/`[]` | Athena fallback still present -> remove it at the flagged sites |
| 4 | [pre-deploy] | Regression guard forbids recs->OpsWriter | `bin/venv-python -m pytest tests/test_validate.py -k "forbids_recs_opswriter" -q` | PASS -- guard flags an injected recs OpsWriter write | guard still whitelist-only -> add the table-specific block |
| 5 | [pre-deploy] | SSM URL resolution (mocked) | `bin/venv-python -m pytest tests/test_iceberg_reader.py -k "ssm_resolution" -q` | PASS -- env unset + terraform absent + SSM param present resolves the URL via `ssm:GetParameter` | resolver skips SSM -> insert SSM between env and terraform-output |
| 6 | [pre-deploy] | ci-rca empty-log guard present | `grep -q 'test -s /tmp/ci-rca-failed.log' .github/workflows/ci-rca.yml && echo GUARD_PRESENT` | prints `GUARD_PRESENT` (rec-2117/2118 acceptance) | guard missing -> add the non-empty assertion + retry |
| 7 | [pre-deploy] | Postmortem DELETE loud-fails on ducklake | `bin/venv-python -m pytest tests/test_ops_data_portal.py -k "postmortem_delete_loudfail_ducklake" -q` | PASS -- raises on the ducklake backend instead of Athena DELETE | still issues unconditional Athena DELETE -> add the backend guard |
| 8 | [post-deploy] | Terraform apply landed (SSM + IAM + view drop) | `aws ssm get-parameter --name /agent-platform/ducklake/reader_url --profile agent_platform --query 'Parameter.Value' --output text` | prints the reader Function URL | param absent -> apply `terraform/personal` (IAM arm = manual admin-apply, Decision 77) |
| 9 | [post-deploy] | LIVE zero-config discovery (the tool proof) | `env -u DUCKLAKE_READER_URL bin/venv-python -m scripts.session_preflight && bin/venv-python -m json.tool logs/.preflight-report.json | grep -A3 ci_rca_recs` | preflight reads DuckLake with no env var; `ci_rca_recs` lists rec-2117/rec-2118 (not `[]`) | reader unreachable -> verify SSM param + `ssm:GetParameter` grant applied |
| 10 | [post-deploy] | Closed-boundary read-your-write intact | `bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-read-your-write` | prints `OPS_RYW OK` (writer->reader round-trip; absent-update 409) | boundary broken -> inspect writer/reader; do not add an Athena escape hatch (Decision 81 cl.7) |
| 11 | [post-deploy] | Athena recs view dropped | `aws glue get-table --database-name agent_platform --name ops_recommendations_current --profile agent_platform 2>&1 | grep -q 'EntityNotFound' && echo VIEW_DROPPED` | prints `VIEW_DROPPED` | view still present -> confirm the main.tf DDL removal applied |
| 12 | [post-deploy] | Full presubmit green | `bin/venv-python -m scripts.validate` | exit 0 -- ruff, mypy, pytest, DQ runner, verifier harness, SLOC gate, the new guard all pass | any failure -> fix; if DQ/verifier touches recs confirm they use the reader |

## Constraints
- Decision 81 cl.7: recs reads/writes transit ONLY the ducklake reader/writer Function URLs -- NO Athena escape hatch may remain on the ducklake backend.
- Decision 55: loud-fail, no silent degradation. A reader outage must surface as an explicit degraded signal, never a false zero; no rescue agents or workaround loops.
- Single Portal Invariant + warehouse-as-SoT: the only recs write path is `file_rec`/`update_rec` -> `_ducklake_write` -> ducklake_writer. Never re-stage recs from a read cache.
- Decision 79: SSM paths are declared in the Lambda manifests' `runtime_config[]` (SSOT); the resolver reads the declared path.
- Decision 77: `terraform/personal/**` auto-applies behind the fail-closed guard, EXCEPT the IAM-change arm -> the `ssm:GetParameter` grant routes to manual admin-apply; present the plan output to the human.
- Decision 43: keep `validate.py`, `session_preflight.py`, `ops_data_portal.py` under 500 non-blank SLOC or carry `# complexity-waiver: decision-43`; prefer net-neutral edits.
- Deep-frozen surface: do NOT edit `.github/copilot-instructions.md` (PROJECT_CONTEXT.md is canonical and already reflects the cutover).
- No `python -c` one-liners in any rec `acceptance`/`verification` field authored as a by-product.

## Context
- This is the first planning session after the 2026-06-09 T2.19 recs cutover to DuckLake. An exhaustive read/write surface audit (this session) found the cutover moved the PRIMARY online paths to DuckLake but left multiple Iceberg/Athena paths live for recs.
- **Trigger / false signal:** preflight reported `ci_rca_recs: []` because, on the PlatformDev reader being undiscoverable in CC-web, it silently fell back to the stale Athena `ops_recommendations_current` view (which has no post-cutover recs). Two open Critical ci_rca recs (rec-2117, rec-2118) were in fact present in DuckLake; both report that ci-rca's log fetch returned a 0-byte log and it could not diagnose the underlying failure -- hence slice 4.
- **Headline risk (closed by slice 1):** `portal.sync()` unconditionally drains the OpsWriter outbox; `sync_ops.drain` routes EVERY outbox dir (incl. `ops_recommendations`) to `OpsWriter.write()` -> Iceberg; OpsWriter still owns recs; and `validate.py`'s guard explicitly permits it. Any recs row reaching that outbox lands silently in the dead store.
- **Reader is reachable, only undiscoverable:** smoke tests read the reader via SigV4-signed Function-URL invokes (PlatformDev holds `lambda:InvokeFunctionUrl`). The gap was URL discovery in CC-web; SSM discovery (slice 3) closes it with no IAM-describe grant. This was verified live in-session by sourcing the URL from terraform state and reading 818 recs.
- **Decision-scout (full scope): FLAGS_FOUND, no BLOCK.** Resolutions folded in: (a) the view DROP is a sound scoped partial of the T2.7 three-view retirement -- add a deferral note + sync read-engine.yaml, order after slice 2; (b) the postmortem-DELETE deferral is acceptable under Decision 70 + Decision 81 cl.2 (writer has no delete verb = net-new scope) -- add a loud-fail guard + follow-on rec; (c) the scoped `ssm:GetParameter` grant is a narrow same-pattern widening consistent with Decision 81 isolation.
- **Citation correction:** the OpsWriter write-through/warehouse-SoT framing cites **Decision 78** (DuckLake adoption), which SUPERSEDED Decision 50; do not cite 50.
- **Cited decisions:** 81, 79, 78, 77, 74, 72, 70, 55, 48, 43.
- **Deferrals (NOT in this plan):** (1) the real postmortem-DELETE cutover -- needs a new `delete_ops` verb on the ducklake_writer; file a follow-on rec citing Decision 70 + 81 cl.2. (2) Archival of the legacy one-shot tools `scripts/cleanup_ops_rec_orphans.py` and `scripts/migrate_ops_data.py` (no live callers; they still issue Athena recs reads/DELETEs) -- file a follow-on rec. (3) Retirement of `ops_decisions_current`/`ops_priority_queue_current` views -- deferred until those tables migrate.
- **Underlying CI failure follow-on:** the c20bfea4 `main-validate` cancellation (validate full-tier cancelled at ~9 min) remains undiagnosed; once ci-rca can read logs (slice 4), open a separate /plan (or re-run) to root-cause it.
- Branch was 0 commits behind `origin/main` at planning time (preflight `main_freshness.status: ok`).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`claude/affectionate-davinci-s07ytj`).
- [ ] docs/PROJECT_CONTEXT.md read.
- [ ] docs/DECISIONS.md entries 81, 79, 78, 77, 74, 72, 70, 55, 48, 43 read.
- [ ] All files in the Scope table located and readable.
- [ ] Acceptance Criteria understood and verifiable.
- [ ] `aws sts get-caller-identity --profile agent_platform` succeeds (reader/writer + SSM reads need the static-key chain).

## Ordered Execution Steps
1. **Slice 1 -- close the write split-brain (do FIRST).**
   - `scripts/ops_writer.py`: remove `ops_recommendations` from `_OPS_TABLE_NAMES`; in `write()` and `compact()` reject/no-op recs with a loud warning; delete the `ops_recommendations_current` branch in `_refresh_view`.
   - `scripts/sync_ops.py`: in `drain()` (`for table_dir in _OUTBOX_DIR.iterdir()`), skip `ops_recommendations` with a loud warning (a recs outbox entry post-cutover is an anomaly, not a drainable write).
   - `scripts/ops_data_portal.py`: ensure `sync()`/`_drain_outbox` excludes the recs outbox dir.
   - `src/data/handlers/ops_compaction_handler.py`: exclude `ops_recommendations` from the compacted set.
   - Pre-condition: portal `_ducklake_write` remains the only recs writer. Post-condition: no code path routes recs to Iceberg.
2. **Slice 2 -- reader-only read path.**
   - `scripts/session_preflight.py`: remove the Athena recs fallbacks at the 5 sites + `read_context_files` :1086; introduce a `recs_read_status` degraded signal surfaced in the report and printed to the human; never substitute a stale/zero value.
   - `scripts/ops_data_portal.py`: make `_fetch_rec_from_athena` reader-only on the ducklake backend (loud-fail if unreachable; no Athena query).
   - `scripts/sync_ops.py`: remove the recs Athena fallback (`_pull_single_table_athena` recs path, `_TABLE_TO_VIEW["ops_recommendations"]`, recs S3-staging guard).
   - `src/data/handlers/scheduled_agent_handler.py`: repoint :302 to `make_reader().current_state(...)`.
3. **Slice 3 -- reader-as-tool discovery (SSM).**
   - `src/common/iceberg_reader.py`: insert SSM resolution into `_reader_url()` (and writer): env -> SSM (path from manifest `runtime_config[]`) -> terraform-output -> `GetFunctionUrlConfig`; consolidate the single `_resolve_function_url_via_api` here and have `ops_data_portal.py` import it (rec-2116).
   - `src/lambdas/ducklake_reader/manifest.yaml` + `ducklake_writer/manifest.yaml`: declare `runtime_config[]` SSM paths.
   - `terraform/personal/ducklake_lambdas.tf`: add the two `aws_ssm_parameter` resources.
   - `terraform/personal/platform_roles.tf`: add the scoped `ssm:GetParameter` statement (comment cites Decision 81).
4. **Slice 4 -- ci-rca log-fetch guard.** `.github/workflows/ci-rca.yml`: after the fetch, `test -s /tmp/ci-rca-failed.log`; on empty, retry with backoff (workflow_run log-availability race), then fail the step loudly so the agent never runs on a 0-byte log. Closes rec-2117/rec-2118.
5. **Slice 5 -- regression guard.** `scripts/validate.py`: extend `validate_warehouse_write_sources` with a table-specific block forbidding `OpsWriter().write("ops_recommendations" ...)`/`.compact("ops_recommendations" ...)` at any call site.
6. **Slice 6 -- drop the view + doc/contract sync (AFTER slice 2 lands).** `terraform/personal/main.tf`: remove the `ops_recommendations_current` view DDL. Update `docs/contracts/ops-data-store.md`, `docs/contracts/read-engine.yaml`, `docs/ARCHITECTURE-WORKFLOW.md`, `config/lambda/ducklake/field_semantics.yaml`. Do NOT touch `.github/copilot-instructions.md` (deep-frozen).
7. **Slice 7 -- tests.** Add/extend the seven test files to lock every behaviour in Acceptance Criteria (recs rejected by OpsWriter; drain skips recs; reader-only loud-degraded; guard forbids recs->OpsWriter; SSM resolution; postmortem-DELETE loud-fail).
8. **Deferrals (record, do not implement):** add the loud-fail guard to `_delete_postmortems_from_iceberg`/`purge_postmortems_for` (raise on ducklake), and file follow-on recs via `file_rec` for: (a) the postmortem-DELETE cutover (new writer `delete_ops` verb; cite Decision 70 + 81 cl.2), (b) archival of `cleanup_ops_rec_orphans.py` + `migrate_ops_data.py`, (c) `ops_decisions_current`/`ops_priority_queue_current` view retirement.
9. **Execute the Verification Plan** -- run each step; loop until pass. Terraform apply: present `terraform plan` output to the human; the `ssm:GetParameter` IAM statement routes to manual admin-apply (Decision 77). If a V3 post-deploy step fails unrecoverably, STOP and root-cause (Decision 55) -- do not add a fallback to satisfy the gate.
10. **Report:** what landed per slice, the verification results, the apply outcome, and the follow-on rec IDs filed for the deferrals.

## Work Areas (STRATEGIC plans only)
N/A -- IMPLEMENTATION plan (STRATEGIC classification suspended under the executor freeze; authored as a single comprehensive IMPLEMENTATION plan per AGENTS.md Temporary Operational Constraints).
