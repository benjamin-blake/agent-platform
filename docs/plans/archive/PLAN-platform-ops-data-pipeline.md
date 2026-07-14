# Plan

## Intent
Close the ops data pipeline gap so document-derived tables (ops_decisions, ops_recommendations) flow into Iceberg automatically on every session close, and provide a centralised atomic ID allocation service that eliminates rec/decision ID collisions across concurrent agents, worktrees, and executor instances.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-ops-data-pipeline

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| terraform/dynamodb.tf | Create | DynamoDB table `agent-platform-counters` with on-demand billing, partition key `counter_name` |
| scripts/sync_recommendations.py | Modify | Add `--next-id {counter_name}` subcommand: atomic DynamoDB increment, print `rec-NNN` or `decision-N` |
| scripts/session_postflight.py | Modify | Before compact_all(): re-parse DECISIONS.md, stage ops_decisions + ops_recommendations from JSONL sources |
| scripts/backfill_ops_tables.py | Modify | Export `_parse_decisions_md` and `_read_jsonl` as public API (rename to remove underscore prefix) |
| tests/test_backfill_ops_tables.py | Modify | Update 19 references to renamed `parse_decisions_md` and `read_jsonl` (drop underscore prefix) |
| tests/test_sync_recommendations.py | Modify | Add tests for `--next-id` and `--seed` with mocked DynamoDB |
| tests/test_session_postflight.py | Modify | Add tests for incremental staging step and `--stage-documents` CLI |

## Bundled Recommendations
- rec-521: Centralised rec ID allocation via DynamoDB atomic counter

## Infrastructure Dependencies
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| aws_dynamodb_table.counters | create | Yes (`--next-id` requires table) | pre-merge | `aws dynamodb get-item --table-name agent-platform-counters --key '{"counter_name":{"S":"recommendations"}}' --profile company-aws-profile` |

For rollback: `terraform destroy -target=aws_dynamodb_table.counters`

## Acceptance Criteria
- [ ] `python -m scripts.sync_recommendations --next-id recommendations --profile company-aws-profile` prints `rec-NNN` where NNN > 521
- [ ] `python -m scripts.sync_recommendations --next-id decisions --profile company-aws-profile` prints an integer > current max decision
- [ ] `python -m scripts.session_postflight --stage-documents` re-parses DECISIONS.md and stages ops_decisions + ops_recommendations (verified by VP step 10 and unit tests in VP step 2)
- [ ] `terraform plan` shows only the new DynamoDB table (no unrelated drift)
- [ ] All tests pass: `python -m pytest tests/test_backfill_ops_tables.py tests/test_sync_recommendations.py tests/test_session_postflight.py -x -q`
- [ ] `python -m scripts.validate` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit tests pass for new --next-id code with mocked DynamoDB | `python -m pytest tests/test_sync_recommendations.py -x -q` | All tests pass, 0 exit code | Fix test or implementation logic |
| 2 | [pre-deploy] | Unit tests pass for postflight incremental staging | `python -m pytest tests/test_session_postflight.py -x -q` | All tests pass, 0 exit code | Fix mock setup or staging logic |
| 3 | [pre-deploy] | Validate passes | `python -m scripts.validate` | Exit 0, no lint/import/test failures | Fix whatever validate reports |
| 4 | [pre-deploy] | Terraform validates | `cd terraform && terraform validate` | Success | Fix .tf syntax |
| 5 | [pre-deploy] | Terraform plan shows only new DynamoDB table | `cd terraform && terraform plan -target=aws_dynamodb_table.counters` | Plan: 1 to add, 0 to change, 0 to destroy | Remove unintended changes |
| 6 | [post-deploy] | Human-gated: terraform apply | `cd terraform && terraform apply -target=aws_dynamodb_table.counters` | Apply complete, table created | Check IAM permissions, SCP constraints |
| 7 | [post-deploy] | Seed counters with current max IDs (dynamic) | `python -m scripts.sync_recommendations --seed --profile company-aws-profile` | Prints seeded values for recommendations and decisions counters (dynamically reads max from local JSONL + DECISIONS.md) | Check table name, region, profile |
| 8 | [post-deploy] | Allocate a rec ID via CLI | `python -m scripts.sync_recommendations --next-id recommendations --profile company-aws-profile` | Prints `rec-522` (first allocation after seed) | Check DynamoDB permissions, table name |
| 9 | [post-deploy] | Allocate a decision ID via CLI | `python -m scripts.sync_recommendations --next-id decisions --profile company-aws-profile` | Prints integer `56` | Same as above |
| 10 | [post-deploy] | Run postflight document staging via CLI | `AWS_PROFILE=company-aws-profile S3_LOG_BUCKET=agent-platform-agent-logs python -m scripts.session_postflight --stage-documents` | Prints staging counts for ops_decisions and ops_recommendations, exits 0 | Check OpsWriter, S3 bucket, parse logic |

## Constraints
- No IAM users (Decision 36/37) -- DynamoDB accessed via SSO profile
- DynamoDB table must use on-demand billing (pay-per-request) to stay within budget
- Postflight staging must be best-effort (never fail session close)
- `_parse_decisions_md` reused from backfill_ops_tables (no duplication)
- Windows-compatible shell commands only

## Context
- rec-521 context: multiple concurrent agents/worktrees produce ID collisions when each reads local max from gitignored JSONL
- DynamoDB atomic increment (`UpdateItem` with `ADD 1`, `ReturnValues=UPDATED_NEW`) is the canonical serverless pattern for distributed sequence generation
- One table with composite partition key supports unlimited counter types (recommendations, decisions, sessions, etc.)
- The postflight gap: recs filed via Copilot Chat bypass OpsWriter; decisions are document-derived and never go through OpsWriter during normal operation
- `backfill_ops_tables._parse_decisions_md()` already implements the DECISIONS.md parser -- reuse it
- Postflight already calls `compact_all()` and `sync_ops.sync()` -- the new staging step inserts before these

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `terraform/dynamodb.tf`** -- Define `aws_dynamodb_table.counters` with:
   - `name = "agent-platform-counters"`
   - `billing_mode = "PAY_PER_REQUEST"`
   - `hash_key = "counter_name"` (type S)
   - Tags consistent with other resources in `terraform/main.tf`
   - No `filemd5()` or `file()` calls (no optional artifacts)

2. **Export public API from `scripts/backfill_ops_tables.py`** -- Rename `_parse_decisions_md` to `parse_decisions_md` and `_read_jsonl` to `read_jsonl`. Update all internal callers (within the same file). Add `__all__` or just remove the underscore prefix. These are pure functions with no side effects.

2b. **Update `tests/test_backfill_ops_tables.py`** -- Fix all 19 references to renamed functions: replace `_parse_decisions_md` with `parse_decisions_md` and `_read_jsonl` with `read_jsonl` in imports and all test call sites.

3. **Add `--next-id` and `--seed` to `scripts/sync_recommendations.py`** -- Add argparse subcommands:
   - `--next-id COUNTER_NAME`: Import boto3, call `dynamodb.update_item(TableName='agent-platform-counters', Key={'counter_name': {'S': counter_name}}, UpdateExpression='ADD current_value :inc', ExpressionAttributeValues={':inc': {'N': '1'}}, ReturnValues='UPDATED_NEW')`. Extract the new value from response. If `counter_name == 'recommendations'`: print `rec-{value:03d}` (zero-padded to 3+ digits). If `counter_name == 'decisions'`: print the integer directly. Otherwise: print the integer (generic counter). Use `AWS_PROFILE` env var or `--profile` arg for session. Graceful error handling: if DynamoDB unreachable, print error to stderr and exit 1.
   - `--seed`: Dynamically compute current max rec ID from `logs/.recommendations-log.jsonl` and current max decision ID from `docs/DECISIONS.md` (via `parse_decisions_md`). Seed both counters in DynamoDB via `put_item`. Print seeded values. Requires `--profile` arg.

4. **Add `_stage_document_derived_tables()` to `scripts/session_postflight.py`** -- New function called before `compact_all()` in `run_auto()`:
   - Import `parse_decisions_md` from `scripts.backfill_ops_tables`
   - Import `read_jsonl` from `scripts.backfill_ops_tables`
   - Re-parse DECISIONS.md: call `parse_decisions_md()`, write result to `logs/.decisions-index.jsonl`
   - Stage ops_decisions: read `logs/.decisions-index.jsonl` via `read_jsonl()`, call `OpsWriter().write("ops_decisions", entry)` for each
   - Stage ops_recommendations: read `logs/.recommendations-log.jsonl` via `read_jsonl()`, call `OpsWriter().write("ops_recommendations", entry)` for each
   - Wrap entire function in try/except (best-effort, never fail session close)
   - Print staging counts to stderr

5. **Wire `_stage_document_derived_tables()` into `run_auto()` and add `--stage-documents` CLI flag** -- Insert call between step 7 (push_closures_to_s3) and step 8 (compact_all) in `run_auto()`. Must be best-effort with try/except like the existing compact step. Also add `--stage-documents` as a standalone flag in the argparse group that calls `_stage_document_derived_tables()` directly (for manual invocation and VP step 10).

6. **Add tests to `tests/test_sync_recommendations.py`** -- Test `--next-id` and `--seed`:
   - Mock `boto3.Session` and `dynamodb.update_item` response
   - Assert correct output format for `recommendations` counter (`rec-NNN`)
   - Assert correct output format for `decisions` counter (integer)
   - Assert error handling when DynamoDB is unreachable
   - Assert `--seed` reads max from local recs and DECISIONS.md, calls `put_item` with correct values

7. **Add tests to `tests/test_session_postflight.py`** -- Test `_stage_document_derived_tables()`:
   - Mock `parse_decisions_md` to return sample records
   - Mock `read_jsonl` to return sample records
   - Mock `OpsWriter.write` and assert it is called with correct table/entries
   - Assert function does not raise even when OpsWriter.write fails

8. Run `python -m pytest tests/test_backfill_ops_tables.py tests/test_sync_recommendations.py tests/test_session_postflight.py -x -q` -- all tests must pass

9. Run `python -m scripts.validate` -- must exit 0

10. **Execute Verification Plan** -- run each step from the table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

11. Report: what was implemented, verification results (actual outcomes), bugs found and fixed
