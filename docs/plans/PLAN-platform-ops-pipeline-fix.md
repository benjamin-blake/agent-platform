# Plan

## Intent

Complete the operational data pipeline so all five ops Iceberg tables in Athena
(`ops_recommendations`, `ops_execution_plans`, `ops_session_log`, `ops_decisions`,
`ops_priority_queue`) receive data from every write site and are queryable via
Athena with data present. This closes the observability gap in the North Star
feedback loop: session performance, recommendation history, and architectural
decisions become SQL-queryable for the self-improving system to reason about.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-ops-pipeline-fix

## Phase
Phase 1: Core Infrastructure (complete) / Phase Platform (parallel)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `terraform/scheduled_agents.tf` | Modify | (rec-500) Add Athena + Glue IAM actions + `s3:DeleteObject`; (rec-502) add `ops_compaction` Lambda with both AWSSDKPandas and data_pipeline_extras layers, CloudWatch log group, Lambda permission, extend `aws_s3_bucket_notification.agent_findings` with second `lambda_function` block for `staging/` prefix |
| `src/data/handlers/ops_compaction_handler.py` | Create | (rec-501) Lambda handler: parse S3 key to extract table + trade_date, call `OpsWriter.compact()`. Supports `force_table`/`force_date` for manual invocation. |
| `tests/test_ops_compaction_handler.py` | Create | (rec-501) Unit tests: key parsing, compact() args, force event fields, unknown table no-op. |
| `scripts/executor/plan.py` | Modify | (rec-503) Add `OpsWriter().write('ops_execution_plans', plan.to_dict())` after local file write in `save_plan()`. |
| `tests/test_executor_plan.py` | Modify | (rec-503) Mock `OpsWriter` in `save_plan` tests to prevent AWS calls. |
| `scripts/sync_recommendations.py` | Modify | (rec-504) Add `OpsWriter().write('ops_recommendations', entry)` per merged/resolved entry in `merge_from_s3()`. |
| `tests/test_sync_recommendations.py` | Modify | (rec-504) Mock `OpsWriter` in `merge_from_s3` tests. |
| `scripts/session_preflight.py` | Modify | (rec-505) Add `s3_log_bucket_set` check: warn when `S3_LOG_BUCKET` unset and SSO active. Add field to report dict. |
| `docs/GETTING_STARTED.md` | Modify | (rec-505) Document `export S3_LOG_BUCKET=bblake-platform-agent-logs` as required shell profile entry. |
| `scripts/backfill_ops_tables.py` | Create | (rec-506) One-shot backfill: reads local JSONL, calls `OpsWriter().write()` per entry, `compact()` per table, runs 5 Athena COUNT(*) queries, prints row counts. |
| `tests/test_backfill_ops_tables.py` | Create | (rec-506) Unit tests: table mapping, OpsWriter calls, --help, --profile arg. |
| `.gitignore` | Modify | (rec-507) Add operational JSONL files to stop git tracking. |
| `.github/instructions/executor-supervisor-workflow.instructions.md` | Modify | (rec-507) Remove operational JSONL from `git add` session-close commands. |
| `.github/prompts/develop-executor.prompt.md` | Modify | (rec-507) Remove operational JSONL from `git add` session-close commands and JSONL conflict resolution section. |
| `scripts/build_lambda.py` | Modify | (rec-502) Append `agent-platform-ops-compaction` to `_LAMBDA_FUNCTION_NAMES` so `--deploy` updates the new Lambda. |

## Bundled Recommendations

- **rec-500**: Add Athena+Glue+DeleteObject permissions to scheduled_agent_lambda IAM policy
- **rec-501**: Create ops_compaction Lambda handler and unit tests
- **rec-502**: Add ops_compaction Lambda, CloudWatch log group, and S3 trigger to scheduled_agents.tf
- **rec-503**: Add OpsWriter write-through to plan.py::save_plan() for ops_execution_plans
- **rec-504**: Add OpsWriter.write() to sync_recommendations.py for ops_recommendations write-through
- **rec-505**: Add S3_LOG_BUCKET preflight warning when env var is unset with active SSO
- **rec-506**: Create scripts/backfill_ops_tables.py one-shot Iceberg backfill script
- **rec-507**: Remove operational JSONL files from git tracking and session-close git add commands

## Infrastructure Dependencies

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| `aws_iam_policy.scheduled_agent_lambda` | Modify -- add Athena + Glue + DeleteObject actions | Yes -- compaction Lambda needs these to call `to_iceberg()` | Pre-merge | `aws iam get-policy-version` shows new actions |
| `aws_lambda_function.ops_compaction` | Create | Yes -- handler must be deployed before S3 trigger fires | Pre-merge | `aws lambda get-function --function-name agent-platform-ops-compaction --profile company-aws-profile` exits 0 |
| `aws_s3_bucket_notification.agent_findings` | Modify -- add second `lambda_function` block for `staging/` | Yes -- staging writes won't trigger compaction without it | Pre-merge | S3 notification config shows two Lambda targets |
| `aws_cloudwatch_log_group.ops_compaction` | Create | No | Pre-merge | Log group exists in CloudWatch |

### Lambda Resource Requirements

The `ops_compaction` Lambda accepts `{"force_table": "...", "force_date": "..."}` event fields
for manual post-deploy invocation. This is used for smoke testing in Step 23.

### Rollback Notes

- For new Lambda: `terraform destroy -target=aws_lambda_function.ops_compaction -target=aws_cloudwatch_log_group.ops_compaction -target=aws_lambda_permission.s3_invoke_ops_compaction`
- S3 notification: revert by removing second `lambda_function` block from `aws_s3_bucket_notification.agent_findings`
- IAM policy: revert by removing the AthenaCompaction and GlueCompaction Sids

## Acceptance Criteria

- [ ] `terraform plan` shows no destroy actions on existing resources
- [ ] After `terraform apply`, `aws lambda get-function --function-name agent-platform-ops-compaction --profile company-aws-profile` exits 0
- [ ] `aws lambda invoke --function-name agent-platform-ops-compaction --payload '{"force_table":"ops_session_log","force_date":"2026-04-21"}' --profile company-aws-profile --cli-binary-format raw-in-base64-out /tmp/ops-compaction-out.json` exits 0 with no FunctionError
- [ ] `python -m scripts.backfill_ops_tables --profile company-aws-profile` exits 0 and prints "Backfill complete"
- [ ] Athena query `SELECT COUNT(*) FROM trading_formulas_db.ops_recommendations` returns > 0
- [ ] Athena query `SELECT COUNT(*) FROM trading_formulas_db.ops_execution_plans` returns > 0
- [ ] Athena query `SELECT COUNT(*) FROM trading_formulas_db.ops_session_log` returns > 0
- [ ] Athena query `SELECT COUNT(*) FROM trading_formulas_db.ops_decisions` returns > 0
- [ ] Athena query `SELECT COUNT(*) FROM trading_formulas_db.ops_priority_queue` returns >= 0 (curator-driven; may be 0 before first curator run)
- [ ] `python -m pytest tests/test_ops_compaction_handler.py tests/test_backfill_ops_tables.py -x -q` exits 0
- [ ] `python -m scripts.validate` exits 0
- [ ] `git check-ignore -q logs/.recommendations-log.jsonl` exits 0

## Constraints

- `aws_s3_bucket_notification` allows only one resource per bucket -- extend the existing `agent_findings` resource with a second `lambda_function` block. Do not create a new notification resource.
- AWSSDKPandas layer ARN `arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python312:22` is defined as a local in `data_pipeline.tf`. In `scheduled_agents.tf`, inline the ARN string directly -- do not reference a local from another file.
- Lambda IAM role `aws_iam_role.scheduled_agent_lambda` is reused -- no new role needed.
- ops_compaction Lambda uses the same zip artifact as findings_processor: `s3_bucket = aws_s3_bucket.data_lake`, `s3_key = lambda-packages/data-pipeline.zip`, `source_code_hash = local.agent_lambda_source_hash`.
- `PYTEST_CURRENT_TEST` guard: `OpsWriter.write()` and `OpsWriter.compact()` already check this internally -- no additional guard needed in caller code.
- In `plan.py`, use `OpsWriter().write('ops_execution_plans', plan.to_dict())` directly (not `append_jsonl` from `s3_log_store`). Per Decision 50 write architecture.
- In `sync_recommendations.py`, use `OpsWriter().write('ops_recommendations', entry)` directly. Do NOT use `s3_log_store.append_jsonl()` -- that would double-write entries into the local file via `_append_jsonl_local()`.
- `ops_decisions` has no automated write-through -- backfill reads `.decisions-index.jsonl` manually. Phase 2 adds write-through when decision write site exists.
- Git removal: `git rm --cached` only (keep local copies). Update `.gitignore` first.
- Lambda tag values: ASCII hyphens only (no em dashes).
- All Athena operations: workgroup `agent-platform-production` (engine v3).
- `scripts/executor/plan.py` is in `scripts/executor/*.py` which is on the executor boundary list -- but this plan goes through `/implement` (human-supervised), not the automated executor, so the boundary does not apply here.

## Context

- **Decision 50** (`docs/DECISIONS.md`): Iceberg append-only ops data store architecture is settled -- this plan implements the remaining gaps to make it work end-to-end.
- **`docs/contracts/ops-data-store.md`**: Authoritative schema for all 5 tables. Staging prefix layout: `staging/{table_name}/trade_date=YYYY-MM-DD/batch-{uuid}.jsonl` in bucket `bblake-platform-agent-logs`.
- **Current IAM gap**: `scheduled_agent_lambda` policy has only S3 (Get/Put/List), SecretsManager, CloudWatch. Missing: Athena actions, Glue catalog reads, `s3:DeleteObject` (needed by `OpsWriter.compact()` to remove processed staging files).
- **`plan.py` gap**: `save_plan()` writes `PLANS_JSONL` via `open()` at line 251. No write-through to OpsWriter. Already imports from `scripts.executor.jsonl_store`. Add import for OpsWriter.
- **`sync_recommendations.py` gap**: `merge_from_s3()` overwrites local recs file via `open()`, bypassing OpsWriter entirely.
- **`S3_LOG_BUCKET` gap**: not set in local shell, so `OpsWriter.write()` silently no-ops. The env var IS already set in the Lambda execution environment. Locally it must be exported.
- Known gotcha: one `aws_s3_bucket_notification` per bucket -- extend `agent_findings`.
- Known gotcha (Import Safety): never raise during module import in the new handler.
- Known gotcha: `on_failure = continue` is on the Iceberg DDL provisioners -- not needed for the compaction Lambda which uses `awswrangler`, not raw Athena DDL.

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.

- [ ] Branch confirmed not on `main` (`git branch --show-current` != `main`)
- [ ] `copilot-instructions.md` read (rules, gotchas, file router)
- [ ] `docs/DECISIONS.md` read -- Decision 50 fully understood
- [ ] `docs/contracts/ops-data-store.md` read -- all 5 table schemas and staging prefix format
- [ ] `terraform/scheduled_agents.tf` read in full -- existing IAM policy, notification resource, Lambda definitions
- [ ] `scripts/ops_writer.py` read -- `OpsWriter.compact()` and `write()` interface
- [ ] `scripts/executor/plan.py` read -- `save_plan()` function and imports
- [ ] `scripts/sync_recommendations.py` read -- `merge_from_s3()` function and `_write_local_recs()`
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Rec-Closing Procedure

After completing each rec's implementation work and verifying its acceptance command passes, close the rec by updating its entry in `logs/.recommendations-log.jsonl`:

1. Use `replace_string_in_file` to find the line containing `"id": "rec-NNN"` with `"status": "open"` and replace `"status": "open"` with `"status": "closed"` on that line.
2. On the same line, append these fields before the closing `}`: `"execution_result": "success"`, `"execution_date": "<current ISO-8601 timestamp>"`, `"execution_branch": "agent/platform-ops-pipeline-fix"`.
3. If a rec ID appears more than once in the file (duplicates from S3 sync), update ALL occurrences.

## Ordered Execution Steps

> Execute these in sequence. Do not substitute the Scope table as a work list.
> After each rec's work is verified, close it using the Rec-Closing Procedure above.

### Step 1: Create `src/data/handlers/ops_compaction_handler.py` (rec-501)

Create the Lambda handler file. Requirements:

- **Never raise at module level** (Import Safety rule).
- Import `OpsWriter` from `scripts.ops_writer` inside the handler function (lazy import) to avoid import-time failures when `awswrangler` is unavailable locally.
- Import `TABLE_NAMES` from `scripts.ops_writer` at module level -- this is safe since it is a list constant with no runtime dependency.
- `handler(event, context)` function:
  1. If event contains `force_table` AND `force_date` keys, use those values directly as `table_name` and `trade_date`.
  2. Otherwise parse S3 event: `event['Records'][0]['s3']['object']['key']` has format `staging/{table_name}/trade_date={YYYY-MM-DD}/batch-{uuid}.jsonl`. Extract `table_name` by splitting on `/` (index 1). Extract `trade_date` from segment index 2 by splitting on `=` (index 1).
  3. Validate `table_name` is in `TABLE_NAMES`. If unknown, log WARNING and return `{'statusCode': 200, 'rows_compacted': 0}`.
  4. Instantiate `OpsWriter()` and call `compact(table_name, trade_date)`.
  5. Return `{'statusCode': 200, 'rows_compacted': row_count, 'table': table_name, 'trade_date': trade_date}`.
- Use `logging.getLogger(__name__)` for all logging.
- Type hints required on handler signature.

### Step 2: Create `tests/test_ops_compaction_handler.py` and close rec-501

Unit tests covering:

- **(a)** S3 event key parsing: given a well-formed S3 event with key `staging/ops_recommendations/trade_date=2026-04-21/batch-abc.jsonl`, verify `table_name` and `trade_date` are correctly extracted and `OpsWriter.compact()` is called with `('ops_recommendations', '2026-04-21')`.
- **(b)** `force_table`/`force_date` event: given `{"force_table": "ops_session_log", "force_date": "2026-04-20"}`, verify `compact('ops_session_log', '2026-04-20')` is called. No S3 key parsing.
- **(c)** Unknown table: given S3 event with `staging/unknown_table/trade_date=...`, verify `compact()` is NOT called and response has `rows_compacted: 0`.
- **(d)** Valid table returns row count from `compact()`.
- Mock `OpsWriter` class in all tests using `@patch('src.data.handlers.ops_compaction_handler.OpsWriter')`.

Run: `python -m pytest tests/test_ops_compaction_handler.py -x -q` -- must exit 0.
**Close rec-501** using the Rec-Closing Procedure.

### Step 3: Modify `terraform/scheduled_agents.tf` -- IAM policy and close rec-500

In the `aws_iam_policy.scheduled_agent_lambda` resource's policy document:

1. Add `"s3:DeleteObject"` to the existing `S3AgentLogs` Sid's Action list (alongside GetObject, PutObject, ListBucket).
2. Add a new Sid `AthenaCompaction` with actions `"athena:StartQueryExecution"`, `"athena:GetQueryExecution"`, `"athena:GetQueryResults"` and Resource `"*"`.
3. Add a new Sid `GlueCompaction` with actions `"glue:GetDatabase"`, `"glue:GetTable"`, `"glue:GetTables"`, `"glue:GetPartitions"` and Resource `"arn:aws:glue:${var.aws_region}:*:*"`.
4. In the existing `CloudWatchLogs` Sid, add a second Resource ARN: `"arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}-ops-compaction*"`. The existing `scheduled-agent*` wildcard does not match `ops-compaction`.

Verify: `grep -q 'athena:StartQueryExecution' terraform/scheduled_agents.tf` exits 0.
**Close rec-500** using the Rec-Closing Procedure.

### Step 4: Modify `terraform/scheduled_agents.tf` -- Lambda + S3 trigger and close rec-502

Add these resources to `terraform/scheduled_agents.tf`:

1. **CloudWatch log group** `ops_compaction`: name `/aws/lambda/${var.project_name}-ops-compaction`, retention 14 days, tags with ASCII hyphens only.

2. **Lambda function** `ops_compaction`: function_name `${var.project_name}-ops-compaction`, role `aws_iam_role.scheduled_agent_lambda.arn`, handler `src.data.handlers.ops_compaction_handler.handler`, runtime `python3.12`, timeout 300, memory 256, s3_bucket `aws_s3_bucket.data_lake.id`, s3_key `lambda-packages/data-pipeline.zip`, source_code_hash `local.agent_lambda_source_hash`, layers `["arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python312:22", aws_lambda_layer_version.data_pipeline_extras.arn]`, env `S3_LOG_BUCKET = aws_s3_bucket.agent_logs.id`, depends_on `[aws_cloudwatch_log_group.ops_compaction]`, tags ASCII hyphens only.

3. **Lambda permission** `s3_invoke_ops_compaction`: statement_id `AllowS3InvokeOpsCompaction`, action `lambda:InvokeFunction`, function_name `aws_lambda_function.ops_compaction.function_name`, principal `s3.amazonaws.com`, source_arn `aws_s3_bucket.agent_logs.arn`.

4. **Extend existing** `aws_s3_bucket_notification.agent_findings`: add second `lambda_function` block with `lambda_function_arn = aws_lambda_function.ops_compaction.arn`, events `["s3:ObjectCreated:*"]`, filter_prefix `staging/`, filter_suffix `.jsonl`. Update depends_on to include BOTH `aws_lambda_permission.s3_invoke_findings_processor` AND `aws_lambda_permission.s3_invoke_ops_compaction`.

Verify: `grep -q 'ops_compaction' terraform/scheduled_agents.tf` exits 0.
5. **Update `scripts/build_lambda.py`**: Append `"agent-platform-ops-compaction"` (or `f"{PROJECT_NAME}-ops-compaction"` if PROJECT_NAME is used) to the `_LAMBDA_FUNCTION_NAMES` list so that `--deploy` calls `update_function_code` for the new Lambda.

**Close rec-502** using the Rec-Closing Procedure.

### Step 5: Modify `scripts/executor/plan.py` -- OpsWriter write-through (rec-503)

In `scripts/executor/plan.py`:

1. Add import at top of file (with other imports): `from scripts.ops_writer import OpsWriter`. OpsWriter does not import awswrangler at module level, so a direct import is safe.

2. In `save_plan()`, after the existing `f.write(json.dumps(plan.to_dict()) + "\n")` line and after the `logger.info(...)` call, add:

```python
try:
    OpsWriter().write("ops_execution_plans", plan.to_dict())
except Exception:
    logger.warning("OpsWriter write-through failed for %s", plan.rec_id, exc_info=True)
```

OpsWriter.write() already guards on PYTEST_CURRENT_TEST and S3_LOG_BUCKET internally. The try/except is defense-in-depth.

Verify: `grep -q 'OpsWriter' scripts/executor/plan.py` exits 0.

### Step 6: Update `tests/test_executor_plan.py` and close rec-503

Add `@patch('scripts.executor.plan.OpsWriter')` to any test that calls `save_plan()`. The mock prevents real AWS calls during testing. Verify the mock is called with the expected table name in at least one test.

Run: `python -m pytest tests/test_executor_plan.py -x -q` -- must exit 0.
**Close rec-503** using the Rec-Closing Procedure.

### Step 7: Modify `scripts/sync_recommendations.py` -- OpsWriter write-through (rec-504)

In `scripts/sync_recommendations.py`:

1. Add import at top: `from scripts.ops_writer import OpsWriter`.

2. In `merge_from_s3()`, instantiate `writer = OpsWriter()` before the `for s3_entry in s3_entries` loop.

3. Inside the loop, after each `merged += 1` (new entry added), add:

```python
try:
    writer.write("ops_recommendations", s3_entry)
except Exception:
    pass  # OpsWriter is best-effort
```

4. After each `conflicts_resolved += 1` (entry updated), add the same pattern with `s3_entry`.

Do NOT call `append_jsonl` from `s3_log_store` -- that would double-write to the local file. Only write newly merged or changed entries to OpsWriter.

Verify: `grep -q 'OpsWriter' scripts/sync_recommendations.py` exits 0.

### Step 8: Update `tests/test_sync_recommendations.py` and close rec-504

Add `@patch('scripts.sync_recommendations.OpsWriter')` to any test that calls `merge_from_s3()`. The mock prevents real AWS calls. Verify mock `write()` is called for merged entries in at least one test.

Run: `python -m pytest tests/test_sync_recommendations.py -x -q` -- must exit 0.
**Close rec-504** using the Rec-Closing Procedure.

### Step 9: Modify `scripts/session_preflight.py` and `docs/GETTING_STARTED.md` and close rec-505

In `scripts/session_preflight.py`, after `sso_status = check_sso_status()` (near line 786):

```python
s3_log_bucket_set = bool(os.environ.get("S3_LOG_BUCKET", "").strip())
if sso_status == "ok" and not s3_log_bucket_set:
    print(
        "WARNING: S3_LOG_BUCKET is unset -- OpsWriter write-through disabled. "
        "To enable: export S3_LOG_BUCKET=bblake-platform-agent-logs",
        file=sys.stderr,
    )
```

Add `"s3_log_bucket_set": s3_log_bucket_set` to the `report` dict.

In `docs/GETTING_STARTED.md`, find the shell environment or AWS configuration section and add: `export S3_LOG_BUCKET=bblake-platform-agent-logs  # enables OpsWriter write-through to Iceberg`.

Verify: `grep -q 's3_log_bucket_set' scripts/session_preflight.py` exits 0.
**Close rec-505** using the Rec-Closing Procedure.

### Step 10: Create `scripts/backfill_ops_tables.py` (rec-506)

Create a new script:

- `argparse` CLI: `--profile` (sets `os.environ['AWS_PROFILE']`), `--bucket` (overrides `S3_LOG_BUCKET`, default `bblake-platform-agent-logs`).
- Table-to-file mapping dict: `ops_recommendations` -> `logs/.recommendations-log.jsonl`, `ops_execution_plans` -> `logs/.execution-plans.jsonl`, `ops_session_log` -> `logs/.session-telemetry.jsonl`, `ops_decisions` -> `logs/.decisions-index.jsonl`, `ops_priority_queue` -> None.
- For each table with a source file: read JSONL entries (skip blank lines, `#` comments, `{"_schema` lines), call `OpsWriter().write(table, entry)` per entry, then `OpsWriter().compact(table)`, print row counts.
- For `ops_priority_queue`: just call `compact()` to flush existing staging.
- After all tables: run five Athena `SELECT COUNT(*) FROM trading_formulas_db.{table}` queries via `subprocess.run` with `aws athena start-query-execution` (workgroup `agent-platform-production`, output `s3://bblake-platform-agent-logs/athena-results/`). Poll with `aws athena get-query-execution` until SUCCEEDED. Use `encoding='utf-8', errors='replace'` on all subprocess with `text=True`. Print each table's row count.
- Exit non-zero if any of the four non-curator tables returns 0 rows.
- Print `"Backfill complete"` on success.
- Type hints required.

Verify: `python -m scripts.backfill_ops_tables --help` exits 0.

### Step 11: Create `tests/test_backfill_ops_tables.py` and close rec-506

Unit tests: mock `OpsWriter` (write + compact), mock `subprocess.run` for Athena CLI, test write called per JSONL entry, compact called per table, --profile and --bucket args work. Use `tmp_path` for test JSONL data.

Run: `python -m pytest tests/test_backfill_ops_tables.py -x -q` -- must exit 0.
**Close rec-506** using the Rec-Closing Procedure.

### Step 12: Modify `.gitignore` (rec-507, part 1)

Find the comment line (near line 108): `# logs/.recommendations-log.jsonl  -- kept tracked; remove this comment when untracking` and replace it with `logs/.recommendations-log.jsonl`. Add nearby: `logs/.execution-plans.jsonl`, `logs/.session-telemetry.jsonl`, `logs/.decisions-index.jsonl`.

### Step 13: Modify `.github/instructions/executor-supervisor-workflow.instructions.md` (rec-507, part 2)

Remove `logs/.recommendations-log.jsonl`, `logs/.execution-plans.jsonl`, and `logs/.session-telemetry.jsonl` from the `git add` commands at two locations: (1) Between-rec checkpoint (around line 47) -- keep `logs/.execution-step-telemetry.jsonl`, `logs/.retro-lite-log.jsonl`, `logs/runs/`. (2) Session Close step 5 (around line 121) -- keep `docs/CHANGELOG.md`, `docs/SESSION_LOG.md`, `logs/.execution-step-telemetry.jsonl`, `logs/.retro-lite-log.jsonl`, `logs/runs/`.

### Step 14: Modify `.github/prompts/develop-executor.prompt.md` (rec-507, part 3)

Remove `logs/.recommendations-log.jsonl`, `logs/.execution-plans.jsonl`, and `logs/.session-telemetry.jsonl` from: (1) Session Close step 5 `git add` command (around line 70). (2) JSONL conflict resolution section (around lines 145-157): remove the `git checkout --ours` lines for those files and associated `git add`. These conflicts no longer occur since files are untracked.

### Step 15: Run `git rm --cached` for JSONL files and close rec-507

```bash
git rm --cached logs/.recommendations-log.jsonl logs/.execution-plans.jsonl logs/.session-telemetry.jsonl logs/.decisions-index.jsonl
```

Verify: `git check-ignore -q logs/.recommendations-log.jsonl` exits 0.
**Close rec-507** using the Rec-Closing Procedure.

### Step 16: Run unit tests

```bash
python -m pytest tests/test_ops_compaction_handler.py tests/test_executor_plan.py tests/test_sync_recommendations.py tests/test_backfill_ops_tables.py tests/test_session_preflight.py -x -q
```

All tests must pass. Fix any failures before proceeding.

### Step 17: Run linting

```bash
ruff check --fix src/data/handlers/ops_compaction_handler.py scripts/executor/plan.py scripts/sync_recommendations.py scripts/session_preflight.py scripts/backfill_ops_tables.py tests/test_ops_compaction_handler.py tests/test_backfill_ops_tables.py
ruff format src/data/handlers/ops_compaction_handler.py scripts/executor/plan.py scripts/sync_recommendations.py scripts/session_preflight.py scripts/backfill_ops_tables.py tests/test_ops_compaction_handler.py tests/test_backfill_ops_tables.py
```

Re-run tests after formatting.

### Step 18: Run `python -m scripts.validate`

Must exit 0. Fix any issues before proceeding.

### Step 19: Lambda build

```bash
python -m scripts.build_lambda
```

Must exit 0 to include the new handler in the zip.

### Step 20: Present `terraform plan` to human -- STOP AND WAIT

```bash
cd terraform && terraform plan -out=tfplan
```

**STOP HERE.** Present the plan output to the human. Do not proceed until explicit human approval. Terraform apply is never automatic.

### Step 21: Terraform apply (after human approval)

```bash
cd terraform && terraform apply tfplan
```

Verify: `aws lambda get-function --function-name agent-platform-ops-compaction --profile company-aws-profile` exits 0.

### Step 22: Lambda deploy

```bash
python -m scripts.build_lambda --deploy
```

Uploads zip to S3 and updates all Lambda function code including ops_compaction.

### Step 23: Lambda smoke test (iterative deploy-test-fix loop)

```bash
aws lambda invoke --function-name agent-platform-ops-compaction --payload '{"force_table":"ops_session_log","force_date":"2026-04-21"}' --profile company-aws-profile --cli-binary-format raw-in-base64-out /tmp/ops-compaction-out.json && cat /tmp/ops-compaction-out.json
```

If response contains `FunctionError`, check CloudWatch logs: `aws logs tail /aws/lambda/agent-platform-ops-compaction --since 5m --profile company-aws-profile`. Diagnose, fix handler code, rebuild (Step 19), redeploy (Step 22), retry. Repeat until invoke succeeds.

### Step 24: Run backfill + Athena verification (iterative deploy-test-fix loop)

```bash
export S3_LOG_BUCKET=bblake-platform-agent-logs
python -m scripts.backfill_ops_tables --profile company-aws-profile
```

Must exit 0 and print "Backfill complete" with row counts. **All 5 tables must be readable in Athena:**

- `ops_recommendations` > 0 rows (mandatory)
- `ops_execution_plans` > 0 rows (mandatory)
- `ops_session_log` > 0 rows (mandatory)
- `ops_decisions` > 0 rows (mandatory)
- `ops_priority_queue` >= 0 rows (may be 0 before first curator run)

If any mandatory table shows 0 rows: check CloudWatch logs, check S3 `staging/` prefix, fix, re-run. Do not proceed until Athena shows data.

### Step 25: Report

Report: list each rec ID (rec-500 through rec-507) and final status, any design decisions made, issues encountered and resolutions, and confirm all Acceptance Criteria pass with evidence.
