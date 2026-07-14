# Plan

## Intent

Execute Phase 0+1 (Portal Foundation and DQ Infrastructure) of the `ops_decisions` graduation arc in a single coordinated PR. Phase 0+1 batches portal enrichment with DQ infrastructure because the portal's write-time validators depend on the DQ manifest being present (per `docs/INTENT-ops-decisions-graduation.md` Decision Registry: "Phase 0+1 batches portal foundation with DQ infrastructure"). Splitting Phase 0+1 by deliverable produces the foot-cannons the INTENT enumerates (postflight resurrection during transition, view collapse pre-backfill, half-built update_decision read path). This plan also bundles `rec-721` (canonical-guard test for `logs/.decisions-index.jsonl`) into the bypass-audit deliverable.

## Plan Type

IMPLEMENTATION (override on the 5-file / 8-step heuristic: Phase 0+1's deliverables are interlocking by design; splitting creates the foot-cannons the INTENT explicitly warns about. Run via human-supervised /implement, not the executor — Decision 67's STRATEGIC constraint targets executor-action paths, not /implement.)

## Verification Tier

V3 (Athena DDL `ALTER TABLE`, Iceberg DML `UPDATE`, view rewrite across three sources, DynamoDB counter write, terraform apply). Highest tier wins.

## Branch

`agent/ops-decisions-phase-0-1`

## Phase

`ops_decisions` graduation arc — Phase 0+1 (Portal Foundation and DQ Infrastructure). NOT_STARTED in `docs/INTENT-ops-decisions-graduation.md` Phase Overview at planning time.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `scripts/session_postflight.py` | Modify | D1: replace `_stage_document_derived_tables` body with single `logger.warning`; remove `--stage-documents` CLI argparse arg and its call site |
| `scripts/sync_recommendations.py` | Modify | D2: add `reseed_decisions_counter(max_id: int)` using `UpdateExpression="SET current_value = :max"` + `ConditionExpression="attribute_not_exists(current_value) OR current_value < :max"`; add docstring note on `seed_counters` distinguishing it (bootstrap only) |
| `terraform/iceberg_tables.tf` | Modify | D3: ADD COLUMNS `id string` and `related_decisions_v2 array<string>` to `ops_decisions` (update CREATE TABLE DDL in same file for fresh-deploy parity); D5: rewrite `CREATE OR REPLACE VIEW ops_decisions_current` to `ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC)` |
| `scripts/ops_writer.py` | Modify | D5: update inline view SQL in `_refresh_view` to match terraform `PARTITION BY id` |
| `scripts/sync_ops.py` | Modify | D5: extend `_coerce_ops_decisions_row` to populate both `id` and legacy `decision_id`; D11: add `_DECISIONS_SYNC_REJECTS_LOG = _LOGS_DIR / "debug" / "decisions-sync-rejects.jsonl"` and log dual-write invariant violations |
| `scripts/executor/jsonl_store.py` | Modify | D6: add `class Decision(BaseModel)` with required (`id`, `title`, `status`, `created_timestamp`, `last_updated_timestamp`) and optional (`problem`, `decision_text`, `context`, `decided_date`, `related_decisions: Optional[list[int]]`, `related_decisions_v2: Optional[list[str]]`, `decision_id: Optional[int]`) fields; `model_config = ConfigDict(extra="ignore")`; `@model_validator(mode='after')` enforces `int(id.split('-')[1]) == decision_id` when both set; D8: add `load_decision(decision_id: str \| int)`, `load_all_decisions()`, `DECISIONS_JSONL` constant |
| `scripts/ops_data_portal.py` | Modify | D7: enrich `file_decision(fields, profile=None, _migration_int_id: Optional[int] = None) -> str` (return `dec-NNN`; bypass allocator only when `_migration_int_id` set; dual-write `id` + `decision_id`; outbox queue preserves `_migration_int_id`; --dry-run via context-manager); `update_decision(decision_id: str, updates, profile=None) -> bool` (str arg; reads from `ops_decisions_current` via new `_fetch_decision_from_athena`; raises `NotImplementedError` until Step 11 of execution removes the assertion); `drain_pending_decisions(profile=None) -> dict` |
| `scripts/validate.py` | Modify | D10: add `validate_decisions_local_writes()` mirroring `validate_recommendations_write_path`; whitelist only `ops_data_portal.py` and `sync_ops.py`. Extend existing `validate_warehouse_write_sources` whitelist comments (DO NOT duplicate the function) noting `ops_decisions` is now governed. Bundle rec-721: add canonical-guard test reference to ensure presence is tested. |
| `config/data_quality/ops.yaml` | Modify | D9: enrich `ops_decisions` block with `description` and `semantics` per column (extended contract per Decision 65). Add shape validators (`id` regex `^dec-\d+$`, not_null for `id`, `title`) as `enforced: false` with `phase4_session: ops-decisions-graduation-phase-5`. Leave existing checks at current `enforced` state. |
| `config/data_quality/decisions/ops_decisions.yaml` | Create | D9: per-field decision manifest mirroring `config/data_quality/decisions/ops_recommendations.yaml`. Every field carries `root_cause_class`, `human_decision: pending` (Phase 2 narrows to `approved`), `enforcement_ready`, `phase4_session: ops-decisions-graduation-phase-5`, `notes`, `current_test`, `last_verdict`. |
| `tests/test_jsonl_store_decision.py` | Create | Tests for `Decision` Pydantic model: id regex, dual-write invariant, extra=ignore, load_decision/load_all_decisions, schema round-trip. |
| `tests/test_ops_data_portal_decisions.py` | Create | Tests for `file_decision` (allocator path; `_migration_int_id` bypass path; outbox queue preserves int; dual-write of `id` and `decision_id`); `update_decision` (NotImplementedError pre-D4; str arg; merge semantics); `drain_pending_decisions` (replay path preserves `_migration_int_id`). |
| `tests/test_sync_recommendations_decisions.py` | Create | Tests for `reseed_decisions_counter`: idempotent (re-run with same max), monotonic (re-run with higher max), rejected (lower max raises ConditionalCheckFailedException). |
| `tests/test_validate_decisions.py` | Create | Tests for `validate_decisions_local_writes` (whitelist enforced; rejects unauthorized callers). Bundles rec-721: covers `logs/.decisions-index.jsonl` write-path canonical guard in `TestValidateScheduledAgentLogs` (or equivalent test class). |
| `docs/INTENT-ops-decisions-graduation.md` | Modify | Maintenance: update Phase Overview row for Phase 0+1 (NOT_STARTED → COMPLETE); fill in Plan and PR fields; refresh Live State at Planning Time snapshot (re-query Athena/DynamoDB at execution time). |
| `docs/INTENT-dq-enforcement.md` | Modify (light) | Maintenance: verify Phase 4 Session Map cross-ref for `ops_decisions` still points at the graduation arc (may be no-op). |

Plus one **Athena DDL operation** (not a file change): `UPDATE ops_decisions SET id = 'dec-' || lpad(...)` backfill, executed against workgroup `agent-platform-production` between D3 ALTER and D5 view rewrite. Optional housekeeping: `OPTIMIZE ... REWRITE DATA USING BIN_PACK` + `VACUUM`.

Plus one **DynamoDB write** (not a file change): call `reseed_decisions_counter(MAX(parsed_id))` against the `agent-platform-counters` table.

## Bundled Recommendations

- **rec-721**: Add test for `logs/.decisions-index.jsonl` canonical guard in `TestValidateScheduledAgentLogs`. Natural extension of D10's `validate_decisions_local_writes`. Bundled into `tests/test_validate_decisions.py`.

Not bundled (deferred):
- rec-763, rec-764 (manifests for `ops_execution_plans`, `ops_priority_queue`): sibling tables, not Phase 0+1 scope.
- rec-228, rec-235, rec-129, rec-139, rec-223 (DECISIONS.md content / cross-ref issues): folded into Phase 3a / 4 of the graduation arc.

## Infrastructure Dependencies

| Resource | Pre-merge / Post-deploy | Notes |
|----------|-------------------------|-------|
| Athena `ops_decisions` table | Post-deploy: `ALTER TABLE ADD COLUMNS` × 2 | One column per statement; workgroup `agent-platform-production` (engine v3). Ignore "already exists" on re-run per `terraform/CLAUDE.md`. |
| Athena `ops_decisions_current` view | Post-deploy: `terraform apply` updates DDL; `OpsWriter._refresh_view` patched in same PR | Three-source patch invariant (terraform / `ops_writer.py` / `sync_ops.py`). PR description must include diff-summary confirming all three. |
| Athena `ops_decisions` rows | Post-deploy: `UPDATE` backfill | Must execute AFTER D3 ALTER and BEFORE D5 view rewrite. Verify `COUNT WHERE id IS NULL = 0`. |
| DynamoDB `agent-platform-counters` | Post-deploy: `UpdateItem` (idempotent SET + ConditionExpression) | Reseed `decisions` counter to current `MAX(parsed_id)`. Reseed is monotonic — never lowers counter. |
| Terraform plan | Pre-merge: `terraform plan` output presented to human | Never `terraform apply` without human approval per CLAUDE.md gotcha. |
| Lambda packaging | DEFERRED (per Decision 67) | This plan DOES touch Lambda-packaged artifacts: `scripts/ops_writer.py` is in `_LAMBDA_SCRIPTS` at `scripts/build_lambda.py:45`; the entire `config/` directory (modified in D9: `config/data_quality/ops.yaml` + new `config/data_quality/decisions/ops_decisions.yaml`) is copied into `data-pipeline.zip` at `build_lambda.py:71` and `:154`. Per CLAUDE.md Temporary Operational Constraints, active deploy is replaced by: `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)`. Code changes still merge; the Lambda zip will pick them up at the next post-Decision-67 deploy. |

## Acceptance Criteria

- [ ] `_stage_document_derived_tables` body is a single `logger.warning` line (no `OpsWriter.write` call; no DECISIONS.md parse)
- [ ] `--stage-documents` CLI flag removed from `argparse` and `run_auto` no longer calls the function
- [ ] `class Decision(BaseModel)` defined with `^dec-\d+$` id regex and dual-write `@model_validator`; `Decision.model_validate({"id":"dec-073","decision_id":72,...})` raises `ValidationError`
- [ ] `reseed_decisions_counter(max_id)` defined; idempotent (same max_id is no-op); monotonic (lower max_id rejected by ConditionExpression)
- [ ] `config/data_quality/decisions/ops_decisions.yaml` exists with one entry per `ops_decisions` field; every entry has `human_decision: pending` and `phase4_session: ops-decisions-graduation-phase-5`
- [ ] `config/data_quality/ops.yaml` `ops_decisions` block has `description` and `semantics` per column; shape validators added as `enforced: false`
- [ ] `validate_decisions_local_writes` function present in `scripts/validate.py`; whitelist contains exactly `ops_data_portal.py` and `sync_ops.py`
- [ ] `python -m scripts.validate` exits 0 on branch tip
- [ ] Athena `DESCRIBE ops_decisions` includes columns `id` (string) and `related_decisions_v2` (array<string>)
- [ ] Athena `SELECT COUNT(*) FROM ops_decisions WHERE id IS NULL` returns 0
- [ ] Athena `SHOW CREATE VIEW ops_decisions_current` contains `PARTITION BY id` (not `decision_id`)
- [ ] DynamoDB `decisions` counter value ≥ refreshed `MAX(parsed_id)`
- [ ] DQ runner produces fresh `logs/debug/dq-latest.json` with no enforced FAIL on `ops_decisions.*`
- [ ] `update_decision("dec-072", {...})` succeeds end-to-end against `ops_decisions_current` (NotImplementedError assertion removed; read path functional)
- [ ] `docs/INTENT-ops-decisions-graduation.md` Phase Overview shows Phase 0+1 status = COMPLETE with plan path and PR URL filled in

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm postflight bypass neutered (body has no `OpsWriter.write`) | `.venv/Scripts/python.exe -c "import ast, pathlib; tree=ast.parse(pathlib.Path('scripts/session_postflight.py').read_text()); fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_stage_document_derived_tables'); body_src=ast.unparse(fn); assert 'OpsWriter' not in body_src and 'decisions_md' not in body_src, body_src; print('ok')"` | prints `ok` | `OpsWriter` or `decisions_md` still referenced — function body not neutered. Replace body with single `logger.warning`. |
| 2 | [pre-deploy] | Confirm `--stage-documents` CLI flag removed | `.venv/Scripts/python.exe -c "import pathlib; src=pathlib.Path('scripts/session_postflight.py').read_text(); assert '--stage-documents' not in src and 'stage_documents' not in src, 'flag still present'; print('ok')"` | prints `ok` | flag still in argparse or call site. Remove both. |
| 3 | [pre-deploy] | Decision Pydantic dual-write invariant raises on mismatch | `.venv/Scripts/python.exe -c "from scripts.executor.jsonl_store import Decision; from pydantic import ValidationError; raised=False; t={'id':'dec-073','decision_id':72,'title':'t','status':'pending','created_timestamp':'2026-05-13T12:00:00Z','last_updated_timestamp':'2026-05-13T12:00:00Z'};\nimport sys\ntry: Decision.model_validate(t)\nexcept ValidationError: raised=True\nassert raised, 'dual-write invariant not enforced'; print('ok')"` | prints `ok` | ValidationError not raised — `@model_validator(mode='after')` missing or wrong. |
| 4 | [pre-deploy] | Decision Pydantic accepts matched id/decision_id | `.venv/Scripts/python.exe -c "from scripts.executor.jsonl_store import Decision; d=Decision.model_validate({'id':'dec-072','decision_id':72,'title':'t','status':'pending','created_timestamp':'2026-05-13T12:00:00Z','last_updated_timestamp':'2026-05-13T12:00:00Z'}); assert d.id=='dec-072' and d.decision_id==72; print('ok')"` | prints `ok` | ValidationError raised on matched pair — validator logic inverted. |
| 5 | [pre-deploy] | `reseed_decisions_counter` exists, is callable, has ConditionExpression in source | `.venv/Scripts/python.exe -c "import inspect; from scripts.sync_recommendations import reseed_decisions_counter; src=inspect.getsource(reseed_decisions_counter); assert 'ConditionExpression' in src and 'attribute_not_exists' in src and 'current_value' in src, src; print('ok')"` | prints `ok` | ImportError or function lacks the ConditionExpression — re-add per Deliverable 2 spec. |
| 6 | [pre-deploy] | `config/data_quality/decisions/ops_decisions.yaml` exists and has the manifest shape | `.venv/Scripts/python.exe -c "import yaml, pathlib; p=pathlib.Path('config/data_quality/decisions/ops_decisions.yaml'); assert p.exists(); d=yaml.safe_load(p.read_text()); fields=d.get('fields') or d.get('columns') or {}; assert len(fields)>0; assert all(('human_decision' in v or 'phase4_session' in v) for v in fields.values() if isinstance(v,dict)); print(f'fields={len(fields)}')"` | prints `fields=N` where N > 0 | file missing or no fields — create from template, mirror `ops_recommendations.yaml`. |
| 7 | [pre-deploy] | `ops.yaml` `ops_decisions` block has `description` + `semantics` for at least the canonical id column | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('config/data_quality/ops.yaml','r',encoding='utf-8')); od=d['tables']['ops_decisions']; assert 'description' in od; cols=od.get('columns',{}); has_id=any(k=='id' for k in cols.keys()); print(f'description=present, id_col={has_id}')"` | prints `description=present, id_col=True` | enrichment incomplete — add description, semantics, id column with shape validators. |
| 8 | [pre-deploy] | `validate_decisions_local_writes` present in `scripts/validate.py` | `.venv/Scripts/python.exe -c "import inspect; from scripts.validate import validate_decisions_local_writes; src=inspect.getsource(validate_decisions_local_writes); assert '.decisions-index.jsonl' in src; assert 'ops_data_portal' in src; assert 'sync_ops' in src; print('ok')"` | prints `ok` | function absent or whitelist incomplete — implement per Deliverable 10. |
| 9 | [pre-deploy] | Full unit test suite for new code passes | `.venv/Scripts/python.exe -m pytest tests/test_jsonl_store_decision.py tests/test_ops_data_portal_decisions.py tests/test_sync_recommendations_decisions.py tests/test_validate_decisions.py -x -v` | all pass | any failure — inspect output; rec-721 canonical-guard test failure means the guard isn't wired through. |
| 10 | [pre-deploy] | Pre-merge gate clean | `.venv/Scripts/python.exe -m scripts.validate` | exits 0 | non-zero exit — diagnose; common cause is bypass audit catching a new write site. |
| 11 | [pre-deploy] | Terraform plan diff is bounded to ops_decisions schema + view | `terraform -chdir=terraform plan -out=ops_decisions_phase01.tfplan 2>&1 \| tee /tmp/tfplan.txt && grep -c "ops_decisions" /tmp/tfplan.txt` | grep returns > 0; plan shows ALTER + view rewrite only | unrelated infrastructure changes appear — back out unintended drift before apply. PRESENT FULL PLAN TO HUMAN BEFORE APPLY. |
| 12 | [post-deploy] | ALTER TABLE landed; new columns visible in Athena | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; sess=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query('DESCRIBE trading_formulas_db.ops_decisions', database='trading_formulas_db', workgroup='agent-platform-production', boto3_session=sess); cols=set(df['col_name'].str.strip().tolist()); assert 'id' in cols and 'related_decisions_v2' in cols, sorted(cols); print('ok')"` | prints `ok` | column missing — `ALTER TABLE ADD COLUMNS` failed or wrong workgroup. Re-run one column per statement against engine v3. |
| 13 | [post-deploy] | Backfill `id` for all historical rows | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; sess=boto3.Session(profile_name='company-aws-profile'); qid=wr.athena.start_query_execution(sql=\"UPDATE trading_formulas_db.ops_decisions SET id = 'dec-' \|\| lpad(CAST(decision_id AS varchar), 3, '0') WHERE id IS NULL AND decision_id IS NOT NULL\", database='trading_formulas_db', workgroup='agent-platform-production', boto3_session=sess); wr.athena.wait_query(qid, boto3_session=sess); print('done', qid)"` | prints `done <query-id>` | query failure — check engine v3, workgroup, decision_id NULL rows (those need manual handling). |
| 14 | [post-deploy] | Zero NULL id rows after backfill | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; sess=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query('SELECT COUNT(*) AS n FROM trading_formulas_db.ops_decisions WHERE id IS NULL', database='trading_formulas_db', workgroup='agent-platform-production', boto3_session=sess); n=int(df.iloc[0]['n']); assert n==0, f'still {n} NULL ids'; print('ok')"` | prints `ok` | nonzero count — rows with NULL `decision_id` exist; mark as `dec-orphan-{rowid}` or hold-for-Phase-4 correction. |
| 15 | [post-deploy] | View rewrite landed; partitions by `id` | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; sess=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query(\"SHOW CREATE VIEW trading_formulas_db.ops_decisions_current\", database='trading_formulas_db', workgroup='agent-platform-production', boto3_session=sess); body=df.to_string(); assert 'PARTITION BY id' in body and 'PARTITION BY decision_id' not in body, body[:1000]; print('ok')"` | prints `ok` | still partitions by `decision_id` — `OpsWriter._refresh_view` may have reverted view. Verify both Terraform DDL and `ops_writer.py` inline SQL are patched. |
| 16 | [post-deploy] | Distinct `id` parity (rows preserved through view) | `.venv/Scripts/python.exe -c "import awswrangler as wr, boto3; sess=boto3.Session(profile_name='company-aws-profile'); df=wr.athena.read_sql_query('SELECT COUNT(DISTINCT id) AS n FROM trading_formulas_db.ops_decisions_current', database='trading_formulas_db', workgroup='agent-platform-production', boto3_session=sess); n=int(df.iloc[0]['n']); assert n>=37, f'distinct ids={n}; expected >=37'; print(f'distinct_ids={n}')"` | prints `distinct_ids=N` with N ≥ 37 | n is 1 or low — view collapsed rows; D4 backfill ordering violated. Diagnose and re-apply view rewrite. |
| 17 | [post-deploy] | DynamoDB `decisions` counter reseeded to ≥ MAX(parsed_id) | `.venv/Scripts/python.exe -c "import boto3, pathlib, re; sess=boto3.Session(profile_name='company-aws-profile'); ddb=sess.client('dynamodb', region_name='eu-west-2'); src=pathlib.Path('docs/DECISIONS.md').read_text()+pathlib.Path('docs/DECISIONS_ARCHIVE.md').read_text(); max_id=max(int(m.group(1)) for m in re.finditer(r'## Decision (\d+)', src)); r=ddb.get_item(TableName='agent-platform-counters', Key={'id':{'S':'decisions'}}); v=int(r['Item']['current_value']['N']); assert v >= max_id, f'counter {v} < max_id {max_id}'; print(f'counter={v}, max_id={max_id}')"` | prints `counter=N, max_id=M` with N ≥ M | counter < max_id — `reseed_decisions_counter` was not called or rejected. Call it manually with the refreshed max. |
| 18 | [post-deploy] | DQ runner refresh clears stale `ops_decisions.recency` FAIL | `.venv/Scripts/python.exe -m scripts.data_quality_runner && .venv/Scripts/python.exe -c "import json; d=json.load(open('logs/debug/dq-latest.json')); fails=[c for c in d['checks'] if c['verdict']=='FAIL' and c['table']=='ops_decisions']; assert not fails, fails; print('ops_decisions enforced FAILs:', len(fails))"` | prints `ops_decisions enforced FAILs: 0` | enforced FAIL still on `ops_decisions.*` — check YAML demotion landed; or another check legitimately failing (investigate). |
| 19 | [post-deploy] | `update_decision` end-to-end against live row | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import update_decision; result=update_decision('dec-001', {'context': 'phase-0-1 smoke test'}); assert result==True; print('ok')"` | prints `ok` | NotImplementedError raised — assertion not removed in Step 13 of execution. Or read path broken — diagnose `_fetch_decision_from_athena`. |
| 20 | [post-deploy] | INTENT doc updated to COMPLETE for Phase 0+1 | `grep -A 1 "Portal Foundation and DQ Infrastructure" docs/INTENT-ops-decisions-graduation.md \| grep -c "COMPLETE"` | returns ≥ 1 | still NOT_STARTED — finish maintenance step in execution. |

**Note on VP step count**: Phase 0+1's V3 surface area (DDL + DML + view + counter + portal) requires this many steps because each integration boundary needs a distinct check. The planning skill's anti-prose-VP rule (every step needs a literal command) is honoured throughout; the `Fix If` columns are specific.

## Constraints

- All writes to `ops_decisions` go through `scripts/ops_data_portal.py` (Decision 50; single portal invariant). The Phase 3a migration script will be the single documented allocator-bypass — Phase 0+1 does NOT introduce that bypass; it only adds the `_migration_int_id` private kwarg as scaffolding.
- Never directly edit `logs/.decisions-index.jsonl` — write-through happens via the portal; rebuild via `sync_ops pull`.
- `terraform apply` only after `terraform plan` is presented to the human (CLAUDE.md Terraform gotcha).
- This plan TOUCHES Lambda-packaged files (`scripts/ops_writer.py`, `config/`). Per CLAUDE.md Temporary Operational Constraints and Decision 67, active deploy steps are replaced by a single DEFERRED marker in execution; no `build_lambda.py --deploy` or `run_scheduled_agent.py --smoke-test` runs in this plan. The merged code persists for the post-Decision-67 deploy.
- No rescue agents or workaround loops (Decision 55).
- D3 → D4 → D5 ordering is mandatory (INTENT Decision Registry, line 929-936): ALTER (D3) before backfill (D4) before view rewrite (D5). Skipping or reordering collapses 37 rows into one winner in `_current`.
- `update_decision` raises `NotImplementedError` until Step 13 of execution removes the assertion. This is the gate that D4 has run.
- The view SQL diff-summary (terraform / `ops_writer.py` / `sync_ops.py` coercion) must appear in the PR description per INTENT Decision Registry.
- Postflight bypass MUST be neutered as Step 2 of execution (D1) — before any other portal work — because the function runs on every `--close-session` and would re-stage markdown-parsed rows over portal-written rows otherwise.

## Context

- `docs/INTENT-ops-decisions-graduation.md` is the strategic anchor for this arc. Read fully before starting execution.
- `docs/INTENT-dq-enforcement.md` is the parent arc; Phase 3 (DQ ratchet) is COMPLETE and operational — verified by the planning agent: `Check.enforced` field present (`scripts/data_quality_runner.py:52-63`), verdict aggregation filters by `enforced` (`:582`), graduation guard at `scripts/validate.py:1343-1422`. `ops_recommendations` is 100% graduated (precedent / proof of methodology).
- Decision 50: append-only ops data store via Iceberg.
- Decision 65: ops.yaml extended contract (`description` + `semantics` per column).
- Decision 67: Lambda deployment deferred — DOES affect this plan. `scripts/ops_writer.py` (D5) is in `_LAMBDA_SCRIPTS` (`scripts/build_lambda.py:45`); the `config/` tree (D9: `ops.yaml` edit + new `decisions/ops_decisions.yaml`) is bundled into `data-pipeline.zip` at `build_lambda.py:71` and `:154`. Code changes merge normally; the active `build_lambda.py --deploy` and `run_scheduled_agent.py --smoke-test` steps are replaced with the DEFERRED marker per CLAUDE.md Temporary Operational Constraints. Lambda will pick up the new bundle on the first deploy after Decision 67 reverses.
- **Live state at planning time (2026-05-13, post pull on `main`)**: 37 rows in `ops_decisions_current`; DECISIONS.md = 1252 lines / 36 headings; DECISIONS_ARCHIVE.md = 1370 lines / 17 headings (combined 53 entries); DynamoDB `decisions` counter = 58 (per `docs/INTENT-ops-decisions-graduation.md` line 51 snapshot — re-query at execution start); 251 open recommendations; `logs/debug/dq-latest.json` shows stale enforced FAIL on `ops_decisions.recency` (since demoted in `ops.yaml` to `enforced: false`; cleared by VP step 18).
- **State drift between planning and execution**: 24 files changed on `main` between session start and branch creation. Implementer MUST re-query Athena row count, DynamoDB counter, and max parsed decision ID at session start. The numbers above are illustrative, not authoritative for execution.
- Open recs touching ops_decisions or DECISIONS.md (informational; not bundled except rec-721): rec-228, rec-235, rec-129, rec-139, rec-223, rec-714, rec-721, rec-763, rec-764.
- Known gotcha: `OpsWriter().compact()` re-runs `_refresh_view` after every portal write. If view SQL in `ops_writer.py` is not patched in the SAME PR as the Terraform view DDL, every portal write reverts the view back to `PARTITION BY decision_id`. PR description must explicitly confirm all three sources patched.
- Known gotcha: Iceberg `UPDATE` produces MERGE-on-read delete files. `OPTIMIZE` (optional) compacts them. Skip OPTIMIZE if Phase 0+1 is time-bound — it is housekeeping, not a correctness gate.
- Known gotcha: `--stage-documents` CLI flag exists at `scripts/session_postflight.py:804-807` and is also called from `run_auto` near line 667. Both call sites must be removed in the same edit.

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main` (`git branch --show-current` returns `agent/ops-decisions-phase-0-1`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (focus: Decisions 50, 57, 65, 67)
- [ ] `docs/INTENT-ops-decisions-graduation.md` read fully
- [ ] `docs/INTENT-dq-enforcement.md` Phase 3 + Phase 4 cross-arc sections read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Live state re-queried: Athena `ops_decisions_current` row count; DynamoDB `decisions` counter value; max `## Decision N` heading across DECISIONS.md + DECISIONS_ARCHIVE.md; `_stage_document_derived_tables` body inspection
- [ ] AWS SSO login fresh (`aws sso login --profile company-aws-profile`); confirm via `aws sts get-caller-identity --profile company-aws-profile`
- [ ] Three-source view patch acknowledged (terraform + `ops_writer.py` + `sync_ops.py` coercion)
- [ ] Phase 4 deferred recs (rec-228, rec-235, rec-129, rec-139, rec-223) acknowledged as NOT in scope

## Ordered Execution Steps

1. **Preflight**. `.venv/Scripts/python.exe -m scripts.session_preflight`. Address any `venv_ok`, `sso_status`, `uncommitted_changes` issues. Re-derive live state numbers per Pre-Implementation Checklist.

2. **D1 — Neuter postflight bypass first (mandatory order).** In `scripts/session_postflight.py`: replace `_stage_document_derived_tables` body with a single `logger.warning("ops_decisions postflight ETL bypass neutered per Phase 0+1 of ops-decisions-graduation arc")`; remove the `--stage-documents` CLI argparse arg and its branch in `run_auto`. Update existing tests in `tests/` that import or assert on the function — replace assertions of write behaviour with assertions of the no-op warning.

3. **D6 — Decision Pydantic model.** Add `class Decision(BaseModel)` to `scripts/executor/jsonl_store.py` with required and optional fields per Scope table. Add `model_config = ConfigDict(extra="ignore")`. Add `@model_validator(mode='after')` enforcing `int(id.split('-')[1]) == decision_id` when both set. Add `DECISIONS_JSONL = Path("logs/.decisions-index.jsonl")` constant. Add tests to `tests/test_jsonl_store_decision.py`.

4. **D8 — Reader API.** In same file, add `load_decision(decision_id: str | int) -> Optional[dict]` (resolves either form) and `load_all_decisions() -> dict[str, dict]` (keyed by `id`; last-wins). Both read from `DECISIONS_JSONL`. Tests in same test file.

5. **D9 — DQ infrastructure.** Create `config/data_quality/decisions/ops_decisions.yaml` mirroring `ops_recommendations.yaml` shape; every field gets `root_cause_class`, `human_decision: pending`, `enforcement_ready`, `phase4_session: ops-decisions-graduation-phase-5`, `notes`, `current_test`, `last_verdict`. Enrich `config/data_quality/ops.yaml` `ops_decisions` block with `description` and `semantics` per column (Decision 65). Add shape validators (`id` regex, `id` not_null, `title` not_null) as `enforced: false` with `phase4_session` reference.

6. **D7 — Enrich portal.** In `scripts/ops_data_portal.py`: enrich `file_decision(fields, profile=None, _migration_int_id: Optional[int] = None) -> str` with allocator path (returns `f"dec-{n:03d}"`); `_migration_int_id` bypass path; dual-write of `id` and `decision_id`; outbox queue preserves `_migration_int_id` in JSON; `--dry-run` via context-manager flag. Enrich `update_decision(decision_id: str, updates, profile=None) -> bool` with str arg, reads from `ops_decisions_current` via new `_fetch_decision_from_athena`, **raises `NotImplementedError` at top of function** (gate that D4 has not yet run). Add `drain_pending_decisions(profile=None) -> dict`. Add tests to `tests/test_ops_data_portal_decisions.py`.

7. **D2 — Counter reseed helper.** In `scripts/sync_recommendations.py`: add `reseed_decisions_counter(max_id: int)` using `UpdateExpression="SET current_value = :max"` + `ConditionExpression="attribute_not_exists(current_value) OR current_value < :max"`. Annotate `seed_counters` with docstring note distinguishing bootstrap-only use. Tests to `tests/test_sync_recommendations_decisions.py`.

8. **D11 — Observability scaffolding.** In `scripts/sync_ops.py`: add `_DECISIONS_SYNC_REJECTS_LOG = _LOGS_DIR / "debug" / "decisions-sync-rejects.jsonl"`. Extend `_coerce_ops_decisions_row` to also populate `id` (preserving `decision_id`); log a sync-reject entry when dual-write invariant violated. Reserve path `logs/debug/decisions-migration-report.jsonl` (Phase 3a will write to it).

9. **D10 — Bypass audit + rec-721.** In `scripts/validate.py`: add `validate_decisions_local_writes()` mirroring `validate_recommendations_write_path`; whitelist contains exactly `ops_data_portal.py` and `sync_ops.py`. Extend existing `validate_warehouse_write_sources` whitelist comments to acknowledge `ops_decisions` is now governed (do NOT duplicate the function — extend in place; the existing whitelist already covers `ops_decisions` calls). Bundle rec-721: add a canonical-guard test in `tests/test_validate_decisions.py` that asserts a write to `logs/.decisions-index.jsonl` from any caller other than the two whitelisted modules is rejected.

10. **Run local presubmit.** `.venv/Scripts/python.exe -m scripts.validate`. Iterate until clean. If `validate_decisions_local_writes` flags a real bypass (not a false positive), file a rec via `ops_data_portal.file_rec` — do not inline-fix.

11. **D3 (terraform edit) — Schema evolution.** In `terraform/iceberg_tables.tf`: add `ALTER TABLE` lines (or use the existing column-add pattern in the file) for `id string` and `related_decisions_v2 array<string>`. Update the CREATE TABLE DDL in the same file so fresh deploys include the new columns. **Run `terraform plan -out=ops_decisions_phase01.tfplan`. Present full plan output to human. Do not apply yet.**

12. **D3 (Athena apply) — Live ALTER TABLE.** With human approval, issue `ALTER TABLE trading_formulas_db.ops_decisions ADD COLUMNS (id string);` then `ALTER TABLE trading_formulas_db.ops_decisions ADD COLUMNS (related_decisions_v2 array<string>);` against workgroup `agent-platform-production` (engine v3). Ignore "already exists" on re-run per `terraform/CLAUDE.md`. Verify VP step 12.

13. **D4 — Backfill.** Run `UPDATE trading_formulas_db.ops_decisions SET id = 'dec-' || lpad(CAST(decision_id AS varchar), 3, '0') WHERE id IS NULL AND decision_id IS NOT NULL;` via `awswrangler.athena.start_query_execution`. Workgroup `agent-platform-production`. Verify VP step 14 returns 0 NULL ids. Then **remove the `NotImplementedError` assertion from `update_decision`** in the same commit — the assertion existing was the gate that D4 had not yet run; removing it is the gate that it has. Optional housekeeping: `OPTIMIZE ... REWRITE DATA USING BIN_PACK` + `VACUUM` (skip if time-bound).

14. **D5 — View rewrite (all three sources, same commit).** In `terraform/iceberg_tables.tf` lines around 1031-1040: rewrite `CREATE OR REPLACE VIEW ops_decisions_current` SELECT to `ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC)`. In `scripts/ops_writer.py` lines around 574-583: update the inline view SQL in `_refresh_view` to match. (Already updated `sync_ops.py` coercion in step 8.) Run `terraform plan` again, present to human, then `terraform apply`. Verify VP step 15.

15. **D2 (live) — Reseed counter.** Compute max parsed decision ID from `docs/DECISIONS.md` + `docs/DECISIONS_ARCHIVE.md`. Call `reseed_decisions_counter(max_id)` against DynamoDB. Verify VP step 17.

16. **Refresh DQ verdict.** `.venv/Scripts/python.exe -m scripts.data_quality_runner` to refresh `logs/debug/dq-latest.json`. Verify VP step 18 (no enforced FAIL on `ops_decisions.*`).

17. **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal).** This plan modifies Lambda-packaged artifacts: `scripts/ops_writer.py` (in `_LAMBDA_SCRIPTS` at `scripts/build_lambda.py:45`) and `config/` (bundled into `data-pipeline.zip` at `build_lambda.py:71` and `:154`). Per CLAUDE.md Temporary Operational Constraints, active deploy and smoke-test steps are deferred until Decision 67 reverses. Record this deferral in the PR description and in the Phase 0+1 retrospective subsection of `INTENT-ops-decisions-graduation.md`. When Decision 67 reverses, file a follow-up rec (or include in the reversal rec) to run `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` and `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` (or another agent that exercises `ops_writer.py` / DQ config loading).

18. **Execute Verification Plan** — run each step 1-20 in order. Loop until pass. If V3 fails unrecoverably, stop and analyze root cause (Decision 55) — do not retry blindly.

19. **Doc maintenance (D-maintenance).** Update `docs/INTENT-ops-decisions-graduation.md`: Phase Overview row for Phase 0+1 (NOT_STARTED → COMPLETE), fill Plan field (this path), fill PR field (post-PR-creation). Refresh "Live State at Planning Time" snapshot with newly-queried numbers. Optionally append a brief "Phase 0+1 retrospective" subsection noting what landed and explicitly recording the Lambda-deploy deferral from Step 17. Light-check `docs/INTENT-dq-enforcement.md` Session Map cross-ref for `ops_decisions` (line ~505) — should still point at the graduation arc; no-op if already correct.

20. **Report**: what was implemented, verification results, three-source view diff-summary (per INTENT Decision Registry mandate), any deviations from this plan with reasoning, the deferred Lambda deploy/smoke-test for follow-up, suggested follow-ups for Phase 2.
