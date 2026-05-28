# Plan

## Intent
Eliminate the class of failures where Lambda-executed code passes local tests but fails in production by closing three systemic gaps: (1) planning agents that are blind to Lambda deployment requirements, (2) a GitHub Models API dependency that limits model choice and creates a second inference backend to maintain, and (3) no reusable mechanism to deploy-invoke-verify Lambda changes end-to-end. This directly advances the North Star by making the automation platform's agents more reliable and self-sufficient.

## Plan Type
STRATEGIC

## Branch
agent/infra-bedrock-lambda-hardening

## Phase
Phase Platform -- Wave 1.5: Lambda Reliability + Bedrock Migration

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/prompts/plan.prompt.md` | Modify | Add Lambda Deployment Assessment rule to human-driven planning |
| `.github/agents/plan-critique.agent.md` | Modify | Add Lambda deployment verification critique rule |
| `config/prompts/executor/planning.prompt.md` | Modify | Add Lambda Deployment Assessment rule to executor planning |
| `config/prompts/executor/critique.prompt.md` | Modify | Add Lambda deployment verification critique rule |
| `.github/copilot-instructions.md` | Modify | Add `build_lambda.py` to File Router; add Lambda deployment gotcha to Known Gotchas |
| `docs/DECISIONS.md` | Modify | Add Decision 46: Single inference provider (Bedrock) for Lambda agents; update Decision 37 status to 'Partially superseded by Decision 46 for inference provider' |
| `docs/contracts/inference-provider.md` | Create | Inference provider contract: model naming, provider field schema, IAM requirements |
| `docs/ROADMAP.md` | Modify | Add Wave 1.5 (Lambda Reliability + Bedrock Migration) to Phase Platform |
| `scripts/bedrock_client.py` | Create | Bedrock `converse` API client mirroring `chat_completion()` interface |
| `tests/test_bedrock_client.py` | Create | Tests for Bedrock client (mocked boto3) |
| `.github/agents/schedule.yaml` | Modify | Add `provider` field to all agents; change all models to Bedrock model IDs |
| `src/data/handlers/scheduled_agent_handler.py` | Modify | Route by `provider` field: `bedrock` uses `bedrock_client`, `github-models` uses existing client |
| `tests/test_scheduled_agent_handler.py` | Modify | Tests for provider routing |
| `terraform/scheduled_agents.tf` | Modify | Add `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` to Lambda IAM policy |
| `src/data/handlers/findings_processor_handler.py` | Modify | Migrate `chat_completion` import from `github_models_client` to `bedrock_client` for comparison step |
| `tests/test_findings_processor_handler.py` | Modify | Update mocks for Bedrock client in comparison tests |
| `scripts/run_scheduled_agent.py` | Modify | Add `--smoke-test` flag for deploy-invoke-verify cycle |
| `tests/test_run_scheduled_agent.py` | Modify | Tests for `--smoke-test` flag |
| `scripts/build_lambda.py` | Modify | Add `bedrock_client.py` to `_LAMBDA_SCRIPTS`; add `--deploy` flag to automate S3 upload + `update-function-code` |
| `tests/test_build_lambda.py` | Modify | Tests for `--deploy` flag |

## Bundled Recommendations
None directly bundled. Related open recs for context:
- **rec-354** (open, M): Bedrock JSON schema output for executor planning -- downstream of Decision 40 P2, not this plan
- **rec-450** (open, XS): Dedicated EventBridge rule for rec-curator -- not needed given daily cron in dispatcher

## Infrastructure Dependencies
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| Lambda IAM policy (bedrock:InvokeModel) | modify | Yes -- bedrock_client.py calls Bedrock API | pre-merge | `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{"force_agent":"doc-freshness"}' --cli-binary-format raw-in-base64-out --profile company-aws-profile /tmp/smoke.json && cat /tmp/smoke.json` |

### Deploy Timing Guidance
The IAM permission must be applied BEFORE merging the Python code that calls Bedrock. Without it, all 6 scheduled agents will fail on their next cron trigger.

### Rollback Notes
- IAM policy change is additive (adding bedrock permissions). Rollback: remove the Bedrock statements from the IAM policy, revert schedule.yaml models to `openai/gpt-4.1` / `gpt-5-mini`, redeploy Lambda. No data migration needed.

## Acceptance Criteria
- [ ] All 4 planning surfaces (plan.prompt.md, plan-critique.agent.md, executor planning.prompt.md, executor critique.prompt.md) contain a Lambda Deployment Assessment rule
- [ ] `copilot-instructions.md` File Router includes `build_lambda.py`; Known Gotchas includes Lambda deployment pipeline entry
- [ ] Decision 46 logged in `docs/DECISIONS.md` with rationale for Bedrock as single Lambda inference provider
- [ ] `docs/contracts/inference-provider.md` exists with model naming conventions and provider field schema
- [ ] `scripts/bedrock_client.py` exists with `converse()` function; tests pass
- [ ] `schedule.yaml` has `provider` field on all 6 agents; all models use Bedrock IDs (e.g., `anthropic.claude-3-5-haiku-20241022-v1:0`)
- [ ] `scheduled_agent_handler.py` routes by `provider` field; tests cover both `bedrock` and `github-models` paths
- [ ] `terraform/scheduled_agents.tf` IAM policy includes `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`
- [ ] `run_scheduled_agent.py --smoke-test doc-freshness` builds, deploys, invokes, and verifies end-to-end
- [ ] `build_lambda.py --deploy` uploads zip to S3 and updates all Lambda function codes
- [ ] All `pytest tests/` pass; `python scripts/validate.py` exits 0
- [ ] Manual verification: `--smoke-test rec-curator` succeeds with Bedrock Claude model in production Lambda

## Constraints
- No Docker on company VM -- Lambdas use zip packaging via S3
- Company SCP blocks IAM user creation and OIDC federation -- Bedrock access is via Lambda execution role (IAM-native, no secrets)
- Terraform changes require `terraform plan` output presented to human before applying. Apply is never automatic.
- Executor self-modification boundary (Decision 44) applies to `config/prompts/executor/planning.prompt.md` and `config/prompts/executor/critique.prompt.md` -- both are modified via `/plan` -> `/implement` (this plan), not the executor, so the boundary is respected
- `github_models_client.py` must be retained (not deleted) during the transition period. The `provider` field in schedule.yaml allows per-agent routing, so agents can be migrated incrementally if needed. However, the intent is all-at-once migration.
- Bedrock model IDs follow the format `provider.model-name-date-version:revision` (e.g., `anthropic.claude-3-5-haiku-20241022-v1:0`). These are NOT interchangeable with GitHub Models IDs or Copilot Chat model IDs.
- Windows subprocess gotcha applies to `build_lambda.py --deploy`: use `encoding='utf-8', errors='replace'` with `text=True`

## Context
- **Decision 40** (deferred): Executor platform migration to Copilot SDK + Bedrock BYOK. This plan does NOT implement Decision 40 -- it addresses the separate concern of Lambda agent inference. Decision 40 remains deferred pending SDK v1.0.
- **Decision 37**: Lambda + Secrets Manager pattern for automation. Bedrock migration partially supersedes the Secrets Manager dependency for inference (PAT no longer needed for model calls), but the PAT may still be needed for other GitHub API calls.
- **Decision 45**: S3 source of truth for cloud-produced logs. Unaffected by this plan.
- **Transcript evidence**: Priority queue pipeline implementation session (April 19, 2026) revealed 3 systemic failures: (a) no Lambda deployment step in plan, (b) model name `claude-opus-4.6` invalid on GitHub Models API, (c) Lambda had stale schedule.yaml and missing layer. All three are addressed by this plan.
- **Known gotcha -- Terraform workflow integration**: Plans with `.tf` files require `terraform plan` output presented to human before applying. Area B includes `.tf` changes.
- **Known gotcha -- Lambda tag values must use ASCII-safe characters**: Relevant for any new tags added to Lambda resources.
- **Bedrock availability**: `anthropic.claude-3-5-haiku-20241022-v1:0` (fast, cheap) and `anthropic.claude-3-5-sonnet-20241022-v2:0` (strong reasoning) are available in eu-west-2. Haiku replaces gpt-5-mini for lightweight agents; Sonnet replaces gpt-4.1 for rec-curator.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (Decisions 37, 40, 44, 45 -- no conflicts)
- [ ] docs/contracts/log-storage.md read (status values, write patterns)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Bedrock model availability confirmed in eu-west-2 (verify via `aws bedrock list-foundation-models --by-provider anthropic --profile company-aws-profile --region eu-west-2 --query "modelSummaries[*].modelId" --output text`)
- [ ] Bedrock invocation not blocked by SCP (verify via `aws bedrock-runtime invoke-model --model-id anthropic.claude-3-5-haiku-20241022-v1:0 --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}' --content-type application/json --accept application/json --profile company-aws-profile --region eu-west-2 /tmp/bedrock-test.json`)

## Work Areas (STRATEGIC plans only)

| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| D: Decision 46 + Inference Provider Contract | `docs/DECISIONS.md`, `docs/contracts/inference-provider.md` (new) | Formalise the architectural direction before any code changes. Establishes: (1) Bedrock is the single inference provider for all Lambda agents, (2) model naming conventions (Bedrock model IDs only in schedule.yaml), (3) provider field schema (`provider: bedrock \| github-models`), (4) IAM requirements (bedrock:InvokeModel on Lambda role), (5) migration timeline (all agents in one batch). Must be done first -- Areas A, B, C reference this decision. | XS |
| A: Lambda Deployment Assessment (all planning surfaces) | `.github/prompts/plan.prompt.md`, `.github/agents/plan-critique.agent.md`, `config/prompts/executor/planning.prompt.md`, `config/prompts/executor/critique.prompt.md`, `.github/copilot-instructions.md` | Close the systemic gap where plans touching Lambda-executed code skip deployment verification and smoke testing. Add a "Lambda Deployment Assessment" rule to all 4 planning surfaces (duplicated for defence in depth per rec-023 rationale). Rule must state: if any file in Scope is packaged in the Lambda zip (check `_LAMBDA_SCRIPTS` in `build_lambda.py`, or lives under `src/data/handlers/`, `.github/agents/`, `.github/prompts/scheduled/`, `config/`), the plan MUST include: (a) a Lambda rebuild+deploy step, (b) a post-deploy smoke test step, (c) model ID validation against the inference provider contract. Also add `build_lambda.py` to the File Router and a Known Gotcha for the Lambda deployment pipeline. | S |
| B: Bedrock Client + Provider Routing | `scripts/bedrock_client.py` (new), `tests/test_bedrock_client.py` (new), `.github/agents/schedule.yaml`, `src/data/handlers/scheduled_agent_handler.py`, `tests/test_scheduled_agent_handler.py`, `terraform/scheduled_agents.tf`, `src/data/handlers/findings_processor_handler.py`, `tests/test_findings_processor_handler.py` | Replace GitHub Models API as the inference backend for all 6 scheduled agents AND the findings processor comparison step. Create `bedrock_client.py` with a `converse(prompt, model_id, region, max_tokens)` function using boto3 `bedrock-runtime` `converse` API. Returns same shape as `chat_completion()` for compatibility. Add `provider` field to `schedule.yaml` schema. Update `scheduled_agent_handler.py` to route by provider. Update `findings_processor_handler.py` to use `bedrock_client` for comparison. Add `bedrock:InvokeModel` to Lambda IAM policy in terraform. **`bedrock_client.py` must be added to `_LAMBDA_SCRIPTS` in `build_lambda.py`** to be packaged in the Lambda zip. `bedrock_client.py` is Lambda-only -- it does not pre-empt Decision 40's Copilot SDK BYOK path for the executor. **Migration strategy:** migrate `doc-freshness` first as canary, run `--smoke-test` in production Lambda, then batch-migrate remaining 5 agents. Model mapping: 5 lightweight agents to `anthropic.claude-3-5-haiku-20241022-v1:0`, rec-curator to `anthropic.claude-3-5-sonnet-20241022-v2:0`. Terraform changes require human approval before apply. | M |
| C: Scheduled Agent Smoke Test + Lambda Deploy | `scripts/run_scheduled_agent.py`, `tests/test_run_scheduled_agent.py`, `scripts/build_lambda.py`, `tests/test_build_lambda.py` | Create reusable deploy-invoke-verify cycle to prevent "passed locally, failed in Lambda." Two additions: (1) `build_lambda.py --deploy` flag that builds zip, uploads to S3 via `aws s3 cp`, then calls `aws lambda update-function-code` for both dispatcher and findings-processor Lambdas. (2) `run_scheduled_agent.py --smoke-test NAME` flag that runs `build_lambda.py --deploy`, then `--trigger-lambda NAME`, then verifies findings appeared in S3. Both use `subprocess.run()` with Windows-safe encoding. | M |
