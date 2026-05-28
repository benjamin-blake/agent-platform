# Plan

## Intent

Collapse the five-CLI ops-recommendations pipeline behind a single three-function API
(`file_rec`, `update_rec`, `sync`) so that the class of incident documented in
`docs/INTENT-ops-pipeline-consolidation.md` — silent compaction failure composing with
destructive JSONL overwrite composing with stale read-modify-write — is architecturally
impossible rather than merely documented.

## Plan Type

IMPLEMENTATION

## Verification Tier

V3

## Branch

agent/ops-pipeline-consolidation

## Phase

Phase Platform: Automation Platform (Parallel Track)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `terraform/iceberg_tables.tf` | Apply (DDL already correct, not modified) | rec-605: deploy pending view DDL that renames `_rn` -> `row_num`, unblocking `ops_recommendations_current` |
| `scripts/ops_writer.py` | Modify | Distinguish infra errors from "no staging files" in `compact()`; pass `boto3_session` to `wr.athena.to_iceberg` |
| `scripts/sync_ops.py` | Modify | Rename `pull` -> `_rebuild_local_cache` (private, add staging guard); add `_pull_single_table`; add `dec-*` ID filter in `_coerce_ops_rec_row`; hard-remove `drain` and `pull` CLI subcommands |
| `scripts/ops_data_portal.py` | Modify | `update_rec`: targeted Athena SELECT for existing record (never JSONL); bake `_sync_table()` post-sync into `update_rec` and `file_rec`; add public `sync()` returning `SyncReport`; hard-remove `--drain` CLI arg |
| `scripts/session_postflight.py` | Modify | Replace `OpsWriter().compact_all()` + `sync_ops.sync()` with `ops_data_portal.sync()` |
| `CLAUDE.md` | Modify | Update agent surface to three functions only; remove drain/compact/refresh-views/pull references; add offline-connectivity note for `update_rec` |
| `docs/PROJECT_CONTEXT.md` | Modify | Remove `--drain`/`sync_ops.pull()` from Known Gotchas; remove rec-605/rec-609 prerequisite warning (bundled here); update Operational Data Governance section |
| `docs/DECISIONS.md` | Modify | Add Decision 69: ops pipeline consolidation |
| `tests/test_ops_data_portal.py` | Modify | Tests for `sync()`, `update_rec` Athena read path, `file_rec` post-sync, offline failure mode |
| `tests/test_ops_writer.py` | Modify/Create | `compact()` raises on credential error; `boto3_session` forwarded to `to_iceberg` |
| `tests/test_sync_ops.py` | Modify | Guard on `_rebuild_local_cache`; `dec-*` ID filter; hard-removed CLI subcommands exit non-zero |

## Bundled Recommendations

- **rec-605** (Critical/XS): Apply pending terraform fix for `_rn` column ambiguity in `ops_recommendations_current`
- **rec-609** (Critical/M): `ops_recommendations_current` returns string-typed lists; filter `dec-*` contamination
- **rec-610** (Critical/M): Umbrella — closes when rec-605 and rec-609 close

## Infrastructure Dependencies

| Resource | File | Change | Timing |
|----------|------|--------|--------|
| `aws_athena_named_query` / view DDL for `ops_recommendations_current` | `terraform/iceberg_tables.tf` | Deploy already-correct DDL (`row_num` alias); no file edit required | Pre-code (Step 1) |

`terraform apply` is agent-executed in this plan per explicit user authorization during
the 2026-05-09 planning session. The standard CLAUDE.md "Apply is never automatic" rule
is overridden for this plan only. The implement agent must present `terraform plan` output
before applying and stop if the plan shows more than the single view resource change.

## Acceptance Criteria

- [ ] `ops_recommendations_current` view is queryable without `_rn` ambiguity error (rec-605)
- [ ] `dec-*` rows no longer appear in `logs/.recommendations-log.jsonl` after `sync_ops pull` (rec-609)
- [ ] `OpsWriter.compact()` raises `RuntimeError` on credential/infra failure; returns `int` on "no staging files"
- [ ] `OpsWriter.compact()` passes `boto3_session` to `wr.athena.to_iceberg`
- [ ] `update_rec` reads existing record from Athena `ops_recommendations_current`, not from JSONL
- [ ] `update_rec` and `file_rec` both trigger `_sync_table("ops_recommendations")` after writing
- [ ] `ops_data_portal.sync()` exists, is callable with no args, returns a `SyncReport`-compatible dict
- [ ] `--drain` arg removed from `ops_data_portal` CLI; `drain` and `pull` subcommands removed from `sync_ops` CLI
- [ ] `session_postflight.py` calls `ops_data_portal.sync()` instead of the old two-step
- [ ] `python -m scripts.validate --ci` exits 0

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Terraform plan: confirm only view DDL changes | `AWS_PROFILE=company-aws-profile terraform plan 2>&1 \| grep -E "Plan:|will be|must be|Error"` | Shows 1 resource to update/replace; no IAM/table schema changes | More than 1 resource affected — stop, investigate diff before applying |
| 2 | pre-deploy | Terraform apply (agent-executed per planning authorization) | `AWS_PROFILE=company-aws-profile terraform apply -auto-approve 2>&1 \| tail -5` | "Apply complete! Resources: 1 added/changed" | Apply failed — check credentials, inspect error, do not proceed to code changes |
| 3 | post-deploy | View is queryable without ambiguity error | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -c "import boto3,time; s=boto3.Session(profile_name='company-aws-profile'); a=s.client('athena',region_name='eu-west-2'); eid=a.start_query_execution(QueryString='SELECT id FROM trading_formulas_db.ops_recommendations_current LIMIT 1',WorkGroup='agent-platform-production',ResultConfiguration={'OutputLocation':'s3://bblake-platform-agent-logs/athena-results/'})['QueryExecutionId']; [time.sleep(2) or None for _ in range(30) if a.get_query_execution(QueryExecutionId=eid)['QueryExecution']['Status']['State'] not in ('SUCCEEDED','FAILED','CANCELLED')]; print(a.get_query_execution(QueryExecutionId=eid)['QueryExecution']['Status']['State'])"` | Prints `SUCCEEDED` | Terraform apply did not propagate — wait 30s and retry; if FAILED, read StateChangeReason |
| 4 | post-deploy | `compact()` returns 0 for "no staging files" (not an error) | `.venv/Scripts/python.exe -m pytest tests/test_ops_writer.py -k "no_staging" -q 2>&1 \| tail -5` | 1 passed | Regression in compact return-path |
| 5 | post-deploy | `compact()` raises `RuntimeError` on credential error (not returns 0) | `.venv/Scripts/python.exe -m pytest tests/test_ops_writer.py -k "infra_error or credential" -q 2>&1 \| tail -5` | 1 passed | Bare `except Exception: return 0` still present — re-read ops_writer.py:491 |
| 6 | post-deploy | `compact()` passes `boto3_session` to `to_iceberg` | `.venv/Scripts/python.exe -m pytest tests/test_ops_writer.py -k "boto3_session" -q 2>&1 \| tail -5` | 1 passed | Session not forwarded |
| 7 | post-deploy | `update_rec` reads from Athena (corrupt JSONL does not corrupt merged record) | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -k "update_rec_athena_read" -q 2>&1 \| tail -5` | 1 passed | JSONL read still present in `update_rec` — check ops_data_portal.py line ~202 |
| 8 | post-deploy | `file_rec` triggers post-sync (new rec visible in JSONL after call) | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -k "file_rec_post_sync" -q 2>&1 \| tail -5` | 1 passed | `_sync_table` not called in `file_rec` |
| 9 | post-deploy | `update_rec` triggers post-sync | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -k "update_rec_post_sync" -q 2>&1 \| tail -5` | 1 passed | `_sync_table` not called in `update_rec` |
| 10 | post-deploy | `sync()` is callable and returns structured report | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -k "sync_report" -q 2>&1 \| tail -5` | 1 passed | `sync()` missing or wrong return type |
| 11 | post-deploy | Hard-removed CLI subcommands exit non-zero | `.venv/Scripts/python.exe -m scripts.sync_ops drain 2>&1; echo "exit:$?"` | Non-zero exit, "invalid choice" or equivalent error message | CLI not removed from argparse |
| 12 | post-deploy | `dec-*` rows no longer appear in JSONL after sync | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -m scripts.sync_ops sync 2>&1 \| tail -3 && python -c "import json,pathlib; lines=[json.loads(l) for l in pathlib.Path('logs/.recommendations-log.jsonl').read_text().splitlines() if l.strip()]; bad=[r['id'] for r in lines if not r.get('id','').startswith(('rec-','agent-','test-'))]; print(len(bad),'bad IDs'); assert len(bad)==0" 2>&1` | Prints "0 bad IDs" | Filter not applied in `_coerce_ops_rec_row` |
| 13 | post-deploy | Full validation suite passes | `.venv/Scripts/python.exe -m scripts.validate --ci 2>&1 \| tail -15` | Exit 0 | Inspect failures — likely test regression or missed reference to removed CLI |

## Constraints

- No STRATEGIC plans (Decision 67): this plan is IMPLEMENTATION.
- `terraform apply` is agent-executed per explicit planning-session authorization (2026-05-09) — this is a single-plan exception to the standard human-gate rule.
- **Lambda deployment deferred (Decision 67):** `scripts/ops_writer.py` IS a Lambda-packaged file (listed in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py` at line 45). The Lambda dispatcher is currently disabled. Per Decision 67, the plan must include a `DEFERRED` deployment step in lieu of active deployment. `scripts/ops_data_portal.py` and `scripts/sync_ops.py` are not Lambda-packaged and need no deployment step.
- No rescue agents or workaround loops (Decision 55).
- `update_rec` offline-mode change: after this plan, `update_rec` requires Athena connectivity for the read step and raises clearly if unreachable. The write path retains the outbox. This is intentional per the intent doc's "fail loud" principle.
- Recovery of today's partial records in `ops_recommendations` (the ~13 NULL-field rows from the incident) is deferred to a separate operational task (user Q5 decision, 2026-05-09). This plan fixes the architecture so the incident cannot recur; it does not clean existing polluted data.
- Only modify files listed in the Scope table. Out-of-scope bugs encountered during implementation become recommendations via `ops_data_portal`, not inline fixes.

## Context

- **Root cause of incident** (2026-05-09): `update_rec` read from JSONL (destructible cache); `sync_ops pull` overwrote that cache with stale Athena state; `OpsWriter.compact` swallowed a credential error as `return 0`; the three failures composed into partial-record Iceberg writes. Full incident chain: `docs/INTENT-ops-pipeline-consolidation.md`.
- **Decision 57** (Interactive vs Autonomous SSO): Interactive sessions should attempt auto-login on credential failure. The new `update_rec` Athena read follows this — if SSO is expired, raise with a clear message prompting `aws sso login`.
- **Decision 67**: Telemetry tables not yet confirmed operational; STRATEGIC plans blocked until reversed.
- **rec-605** terraform DDL is already correct in `terraform/iceberg_tables.tf` (line ~1025 uses `row_num`); only `terraform apply` is required.
- **rec-609** parser coercions (`_coerce_ops_rec_row`) are partially implemented in `sync_ops.py`; what remains is the `dec-*` ID filter and verifying all scalar/array coercions round-trip through Pydantic.
- **awswrangler 3.x**: `to_iceberg` accepts `boto3_session` at parameter position 373 (`_write_iceberg.py`) — confirmed in installed package. The intent doc was wrong that this parameter was unavailable; it exists and simply was not being passed.
- **session_postflight.py**: the current two-step (`compact_all()` then `sync_ops.sync()`) is the same destructive pattern that caused the incident at session close. Replacing it with `ops_data_portal.sync()` closes that vector.
- **JSONL role after this plan**: write-through diagnostic cache only. Nothing in the agent-facing code path reads from it except to populate it after a post-sync pull.

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main` (`agent/ops-pipeline-consolidation`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (especially Decisions 51, 55, 57, 67)
- [ ] `docs/INTENT-ops-pipeline-consolidation.md` read in full (incident chain is the spec)
- [ ] All Scope files located and readable
- [ ] `terraform plan` output reviewed before `terraform apply` (step 1 — even though apply is agent-executed, the plan output must be inspected first)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **terraform plan + apply (rec-605)** — run `terraform plan`, inspect output (must show only the `ops_recommendations_current` view resource), then run `terraform apply -auto-approve`. Verify via VP step 1-3. Do NOT proceed to code changes if apply fails.

2. **`scripts/ops_writer.py`: split `compact()` error paths** — replace the bare `except Exception as exc: return 0` block (line ~491) with two branches: `NoStagingFiles` path returns `0` (no keys found); any exception raised by `wr.athena.to_iceberg` or S3 credential setup re-raises as `RuntimeError(f"ops_writer.compact: infrastructure failure for {table}: {exc}")`. Also add `boto3_session=self._get_boto3_session()` to the `wr.athena.to_iceberg(...)` call, where `_get_boto3_session()` is a new method returning the `boto3.Session` already used in `_get_client()`. Run VP steps 4-6.

3. **`scripts/sync_ops.py`: harden the cache-rebuild path** — (a) rename `pull` -> `_rebuild_local_cache` (make private; update all internal callers); (b) add a staging-file guard at the top of `_rebuild_local_cache`: if any S3 staging files exist for `ops_recommendations` today, log a warning and raise `RuntimeError("_rebuild_local_cache: unstaged writes detected for ops_recommendations — call sync() first")`; (c) add `_pull_single_table(table: str) -> int` that runs the existing per-table pull logic for one table and returns row count; (d) add `dec-*` ID rejection to `_coerce_ops_rec_row`: after existing coercions, add `if not row.get("id","").startswith(("rec-","agent-","test-")): _write_sync_reject(row, f"invalid id prefix: {row.get('id')}"); return None` and handle `None` in the caller; (e) hard-remove `drain` and `pull` from the `choices` list in `argparse`. Run VP steps 11-12.

4. **`scripts/ops_data_portal.py`: targeted Athena read helper** — add private `_fetch_rec_from_athena(rec_id: str, profile: str | None = None) -> dict | None` that runs `SELECT * FROM trading_formulas_db.ops_recommendations_current WHERE id = '{rec_id}' LIMIT 1` via boto3 Athena, polls until SUCCEEDED (max 60s), parses the single result row through `_coerce_ops_rec_row` from sync_ops, and returns the dict (or raises `RuntimeError` on infra failure, returns `None` if not found). Use `ATHENA_WORKGROUP` and `_AWS_REGION` constants already in the module.

5. **`scripts/ops_data_portal.py`: `_sync_table()` helper** — add private `_sync_table(table: str) -> None` that calls in order: `OpsWriter().compact(table)` (raises on infra error per step 2); `OpsWriter()._refresh_view(table)`; `_pull_single_table(table)` from sync_ops (imported lazily). Any `RuntimeError` from compact propagates to the caller.

6. **`scripts/ops_data_portal.py`: rewire `update_rec`** — replace line ~202 (`existing = _sanitize_athena_record(load_recommendation(rec_id) or {})`) with: `existing = _fetch_rec_from_athena(rec_id, profile=profile) or {}`. Keep `_sanitize_athena_record` applied to the result. After `_append_to_local_jsonl(...)`, add `_sync_table("ops_recommendations")`. Update docstring: "Reads existing record from Athena `ops_recommendations_current` (requires SSO connectivity). Raises `RuntimeError` if Athena unreachable."

7. **`scripts/ops_data_portal.py`: rewire `file_rec`** — after `_append_to_local_jsonl(RECS_JSONL, merged)` (line ~166), add `_sync_table("ops_recommendations")`. Update docstring accordingly.

8. **`scripts/ops_data_portal.py`: add `sync()`** — add public function:
   ```python
   def sync(tables: list[str] | None = None) -> dict:
   ```
   Iterates the ops table list (or the provided subset), calls `OpsWriter().drain()` first, then for each table calls `_sync_table(table)` and records compacted row count and pulled row count. Returns `{"compacted": {table: rows}, "pulled": {table: rows}, "views_refreshed": [...]}`. Raises `RuntimeError` on any infra failure. Hard-remove `--drain` from the CLI `argparse` block.

9. **`scripts/session_postflight.py`: replace two-step with `sync()`** — remove the `OpsWriter().compact_all()` call and the `sync_ops_sync()` call (lines ~694-709). Replace with a single `ops_data_portal.sync()` call wrapped in `try/except` (sync must never fail session close — log warning and continue).

10. **`CLAUDE.md` + `docs/PROJECT_CONTEXT.md`: update agent surface** — (a) in CLAUDE.md "Operational data governance" section: replace the drain/pull/compact/refresh-views instructions with: "Agent surface is three functions: `file_rec`, `update_rec`, `sync`. Do not call `sync_ops`, `ops_writer`, or any drain/compact/pull CLIs directly."; add: "`update_rec` requires Athena connectivity (SSO). If unreachable, run `aws sso login --profile company-aws-profile` first." (b) In `docs/PROJECT_CONTEXT.md` Known Gotchas: remove the `--drain` and `sync_ops.pull()` instructions; remove the rec-605/rec-609 prerequisite warning from the DQ section. (c) In `docs/PROJECT_CONTEXT.md` Operational Data Governance: remove `python scripts/ops_data_portal.py --pull`, `--drain`, and `sync_ops.pull()` references; replace with `ops_data_portal.sync()`.

11. **`docs/DECISIONS.md`: add Decision 69** — title: "Ops Pipeline Consolidation: single-portal invariant enforced at primitive level"; status: open; rationale: "Five-CLI choreography leaked internal pipeline layers to agents, enabling silent-failure composition. Root-cause analysis in docs/INTENT-ops-pipeline-consolidation.md. Three architectural fixes: (1) update_rec reads from Athena (source of truth), not JSONL (destructible cache); (2) OpsWriter.compact raises on infra errors instead of returning 0; (3) ops_data_portal.sync() is the single flush primitive. CLI hard-removal enforces the boundary at the build level."

12. **Tests** — add/update:
    - `tests/test_ops_writer.py`: `test_compact_no_staging_returns_zero`, `test_compact_infra_error_raises`, `test_compact_passes_boto3_session_to_to_iceberg`
    - `tests/test_ops_data_portal.py`: `test_update_rec_reads_from_athena_not_jsonl` (mock `_fetch_rec_from_athena`, assert `load_recommendation` NOT called), `test_update_rec_post_sync` (assert `_sync_table` called), `test_file_rec_post_sync` (assert `_sync_table` called), `test_sync_returns_report`, `test_update_rec_raises_on_athena_unreachable`
    - `tests/test_sync_ops.py`: `test_rebuild_local_cache_guard_blocks_on_staging_files`, `test_coerce_ops_rec_row_rejects_dec_ids`, `test_drain_cli_removed`, `test_pull_cli_removed`

13. **Execute Verification Plan** — run VP steps 1-13 in order. Loop until all pass. If VP3 fails (view still broken after apply), stop and diagnose terraform state. If VP13 fails on `validate --ci`, do not merge — inspect each failure line.

14. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal)** — `scripts/ops_writer.py` is Lambda-packaged. The improved `compact()` error-raising behaviour and `boto3_session` forwarding will not be active in the deployed Lambda until Decision 67 is reversed and the Lambda is rebuilt and deployed. Until then, the Lambda compaction path retains the old silent-failure behaviour. When Decision 67 is reversed, run: `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -m scripts.build_lambda --deploy` then `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test ops-compaction`.

15. **Report** — state what was implemented, VP results, rec IDs to close (rec-605, rec-609, rec-610).
