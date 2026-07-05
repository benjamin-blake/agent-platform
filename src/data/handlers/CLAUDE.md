# Lambda handlers — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Lambda packaging contract
Files here are bundled into Lambda zip artefacts via `scripts/build_lambda.py`. Plans modifying any handler must include the build, deploy, and post-deploy verification sequence — not just code edits. The dispatcher and findings-processor are the two Lambda functions whose code is updated.

### Required steps for Lambda-touching plans
1. **Build**: `bin/venv-python -m scripts.build_lambda`
2. **Deploy**: `bin/venv-python -m scripts.build_lambda --deploy` uploads to S3 and updates Lambda function code.
3. **Smoke-test (post-deploy)**: `bin/venv-python -m scripts.run_scheduled_agent --smoke-test NAME` when the runner exposes it (grep for `_smoke_test` or `--smoke-test`). Otherwise an explicit `--trigger-lambda NAME` invocation with expected observable output.

If any of these are missing from a plan that touches handlers here, the plan is incomplete — flag it during `/plan` Step 4 (Lambda Deployment Assessment).

## Pipeline plumbing
- All handlers must accept a `force_{param}` event field for plan-driven re-runs.
- IAM-modifying plans: `terraform apply` must precede Lambda code deploy. See `terraform/CLAUDE.md` for the IAM precedence rule.
- Scheduled-agent handlers route by the `provider` field in `.github/agents/schedule.yaml` — not by `LLM_PROVIDER` env var.
- `agent-platform-data-lake` is the agent log bucket for cron workflows. Don't write to other buckets unless the plan explicitly says so.

## Model ID format reminder
Model IDs differ by provider -- e.g., legacy Copilot SDK IDs (`claude-haiku-4.5`, `claude-sonnet-4.6`) vs. GitHub Models IDs (e.g., `gpt-5-mini`). Do not interchange — see `docs/contracts/inference-provider.yaml` and Decision 116 (supersedes Decision 49).

## awswrangler 3.x gotchas
- `temp_s3_dir` was renamed `temp_path`. Verify `awswrangler.__version__` before calling, or pin in `requirements.txt`.
- `fill_missing_columns_in_df=True` re-adds missing Iceberg schema columns as `object`/null-typed, which breaks writes for `array<>`/typed array columns. For Iceberg tables with `array<string>` or `array<int>`, prefer explicit per-table dtype overrides or `fill_missing_columns_in_df=False` with the full column set.
