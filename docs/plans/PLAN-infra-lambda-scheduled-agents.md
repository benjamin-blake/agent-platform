# Plan

## Intent

Migrate scheduled agents from GitHub Actions (blocked by corporate SCP) to AWS Lambda + GitHub Models API, establishing a scalable convention-based architecture where agents auto-discover their output paths and findings are automatically processed into recommendations without manual intervention.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-lambda-scheduled-agents

## Phase

Infrastructure (post-Phase 1)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `src/data/handlers/scheduled_agent_handler.py` | Create | Dispatcher Lambda: reads manifest, runs agents via GitHub Models API, writes to `agents/{name}/{timestamp}.jsonl` |
| `src/data/handlers/findings_processor_handler.py` | Create | Processor Lambda: unions findings, compares against recommendations, appends new recommendations |
| `scripts/github_models_client.py` | Create | HTTP client for `https://models.github.ai/inference/chat/completions` |
| `.github/prompts/scheduled/findings-compare.prompt.md` | Create | Agent prompt for comparing findings to existing recommendations |
| `terraform/scheduled_agents.tf` | Create | Lambda functions, EventBridge rule, S3 event notification, Secrets Manager, IAM roles |
| `terraform/data_pipeline.tf` | Modify | Remove OIDC provider data source, IAM role, policy attachment (~70 lines) |
| `terraform/variables.tf` | Modify | Remove `create_github_oidc_provider` variable |
| `terraform/outputs.tf` | Modify | Remove `github_actions_agent_logs_role_arn` output |
| `terraform/terraform.tfvars` | Modify | Remove `create_github_oidc_provider = false` line |
| `.github/workflows/scheduled-agents.yml` | Delete | No longer needed — replaced by Lambda |
| `scripts/s3_log_store.py` | Modify | Add `write_timestamped_findings()` and `list_agent_findings()` functions |
| `tests/test_s3_log_store.py` | Modify | Add tests for new s3_log_store functions |
| `scripts/run_scheduled_agent.py` | Modify | Factor out core logic into reusable module for Lambda handler |
| `docs/DECISIONS.md` | Modify | Supersede Decision 36, add Decision 37 (Lambda + GitHub Models API) |
| `docs/GETTING_STARTED.md` | Modify | Update scheduled agents section (remove GitHub Actions, document Lambda) |
| `.github/copilot-instructions.md` | Modify | Update file router, adjust SCP gotcha wording |
| `.github/copilot_instructions.md` | Modify | Mirror changes (legacy duplicate) |
| `docs/CHANGELOG.md` | Modify | Document migration |
| `tests/test_scheduled_agent_handler.py` | Create | Tests for dispatcher Lambda |
| `tests/test_findings_processor_handler.py` | Create | Tests for processor Lambda |
| `tests/test_github_models_client.py` | Create | Tests for HTTP client |

## Infrastructure Dependencies

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing |
|----------|-----------------|------------------------------|---------------|
| `aws_lambda_function.scheduled_agent_dispatcher` | create | N/A (is the code) | post-merge |
| `aws_lambda_function.findings_processor` | create | N/A (is the code) | post-merge |
| `aws_cloudwatch_event_rule.hourly_agents` | create | No | post-merge |
| `aws_s3_bucket_notification.agent_findings` | create | No | post-merge |
| `aws_secretsmanager_secret.github_pat` | create | Yes (Lambda reads it) | pre-merge |
| `aws_iam_role.scheduled_agent_lambda` | create | Yes (Lambda assumes it) | pre-merge |
| `aws_iam_openid_connect_provider.github_actions` | destroy | No | post-merge |
| `aws_iam_role.github_actions_agent_logs` | destroy | No | post-merge |

**Deploy sequence:**
1. Create Secrets Manager secret manually (contains GitHub PAT)
2. `terraform apply` to create IAM roles and Lambda infrastructure
3. Deploy Lambda code via `scripts/build_lambda.py`
4. Verify with manual test invocation
5. Remove obsolete OIDC resources in subsequent apply

## S3 Key Structure

```
s3://bblake-platform-agent-logs/
├── agents/                                    ← Raw findings per agent (convention-based)
│   ├── doc-freshness/
│   │   └── 2026-04-07T06:00:00Z.jsonl
│   ├── orphan-code/
│   │   └── 2026-04-08T06:00:00Z.jsonl
│   └── {any-new-agent}/                       ← Auto-created on first run
│       └── {ISO-timestamp}.jsonl
├── findings/                                  ← Unified findings (processor output)
│   └── unified.jsonl                          ← All findings with "source" field
└── recommendations/                           ← Agent-generated recommendations
    └── agent-recommendations.jsonl            ← Separate from local rec log
```

**Recommendation Log Separation:**
- **Local:** `logs/.recommendations-log.jsonl` — IDs: `rec-NNN` — for manual sessions, code review
- **S3:** `recommendations/agent-recommendations.jsonl` — IDs: `agent-NNN` — for Lambda-generated
- **No conflicts:** Different keys, different ID namespaces
- **Preflight surfaces both:** `session_preflight.py` reports counts from both sources
- **Processor compares against both:** Avoids duplicating findings already in either log

## Acceptance Criteria

- [ ] Dispatcher Lambda reads `schedule.yaml` and invokes GitHub Models API for due agents
- [ ] Dispatcher writes findings to `agents/{name}/{timestamp}.jsonl` (convention-based path)
- [ ] Processor Lambda triggers on S3 `ObjectCreated` events in `agents/` prefix
- [ ] Processor unions findings into `findings/unified.jsonl` with `source` field
- [ ] Processor compares findings against both local mirror and S3 recommendations
- [ ] Processor appends new recommendations to `recommendations/agent-recommendations.jsonl`
- [ ] GitHub PAT stored in Secrets Manager, read by Lambda at runtime
- [ ] All OIDC/GitHub Actions infrastructure removed from Terraform
- [ ] `scheduled-agents.yml` workflow deleted
- [ ] Documentation updated (DECISIONS.md, GETTING_STARTED.md, copilot_instructions)
- [ ] All tests pass (`pytest tests/`)
- [ ] Validation passes (`python scripts/validate.py`)

## Constraints

- **No Docker:** Lambda uses zip packaging (per copilot_instructions.md)
- **Python 3.12:** Lambda runtime must match local development
- **Free GitHub Models tier:** 150 RPD, 15 RPM — sufficient for current 4 agents/week
- **Lambda timeout:** 15 minutes max — sufficient for sequential agent execution
- **No GitHub issues:** Recommendations log is the single source of truth

## Context

- **Decision 36:** Established OIDC approach — now superseded due to SCP blocking `sts:AssumeRoleWithWebIdentity` from external IPs
- **SCP discovery:** CloudTrail showed `AccessDenied` with `"errorMessage": "An unknown error occurred"` — signature of org-level SCP denial
- **GitHub Models API:** `https://models.github.ai/inference/chat/completions` — OpenAI-compatible, PAT auth, same free models as Copilot CLI
- **Existing `s3_log_store.py`:** Already has S3/local fallback pattern — extend rather than replace

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] `copilot_instructions.md` read (rules, gotchas, file router)
- [ ] `DECISIONS.md` read (Decision 36 context, other open decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO session active (`aws sso login --profile company-aws-profile`)

## Ordered Execution Steps

### Phase 1: GitHub Models Client

1. Create `scripts/github_models_client.py`:
   - Function `chat_completion(prompt: str, model: str, api_key: str) -> dict`
   - POST to `https://models.github.ai/inference/chat/completions`
   - Headers: `Authorization: Bearer {api_key}`, `Content-Type: application/json`
   - Request body: `{"model": model, "messages": [{"role": "user", "content": prompt}]}`
   - Return parsed JSON response
   - Handle rate limit (429) with exponential backoff
   - Handle errors gracefully (return error dict, don't raise)

2. Create `tests/test_github_models_client.py`:
   - Mock `requests.post` for all tests
   - Test successful response parsing
   - Test 429 rate limit retry logic
   - Test error handling (500, timeout, malformed JSON)

### Phase 2: S3 Log Store Extensions

3. Modify `scripts/s3_log_store.py`:
   - Add `write_timestamped_findings(agent_name: str, findings: list[dict]) -> str`:
     - Writes to `agents/{agent_name}/{ISO-timestamp}.jsonl`
     - Returns the S3 key written
   - Add `list_agent_findings(agent_name: str | None = None) -> list[str]`:
     - Lists keys under `agents/` (or `agents/{agent_name}/` if specified)
   - Add `read_all_agent_findings() -> list[dict]`:
     - Reads all JSONL files under `agents/*/`
     - Adds `source` field to each entry (agent name + timestamp from key)

4. Add tests for new functions in existing `tests/test_s3_log_store.py` or create new test file.

### Phase 3: Dispatcher Lambda Handler

5. Create `src/data/handlers/scheduled_agent_handler.py`:
   - `handler(event, context)` entry point
   - Read `schedule.yaml` from bundled zip (or S3 if needed)
   - Determine which agents are due based on current UTC time (reuse logic from `run_scheduled_agent.py`)
   - For each due agent:
     - Read prompt file from bundled zip
     - Call `github_models_client.chat_completion()`
     - Parse findings from response
     - Call `s3_log_store.write_timestamped_findings()`
   - Return summary of agents run and findings counts

6. Modify `scripts/run_scheduled_agent.py`:
   - Factor out `is_agent_due()`, `load_manifest()`, `parse_findings()` into importable functions
   - Keep CLI entry point working for local testing
   - Handler imports these functions rather than duplicating

7. Create `tests/test_scheduled_agent_handler.py`:
   - Mock `github_models_client.chat_completion`
   - Mock `s3_log_store.write_timestamped_findings`
   - Test agent selection based on cron
   - Test findings parsing and writing

### Phase 4: Findings Processor Lambda Handler

8. Create `.github/prompts/scheduled/findings-compare.prompt.md`:
   - System prompt explaining the task
   - Input: unified findings JSON, existing recommendations JSON
   - Output: JSON with `duplicates` (IDs of existing recs that match) and `new_recommendations` (list of new rec objects)
   - Criteria for duplicate detection (same file + similar issue)
   - Criteria for recommendation creation (priority, effort estimation)

9. Create `src/data/handlers/findings_processor_handler.py`:
   - `handler(event, context)` entry point
   - Triggered by S3 event (extract bucket/key from event)
   - **Step 1 (deterministic):**
     - Call `s3_log_store.read_all_agent_findings()`
     - Write to `findings/unified.jsonl`
   - **Step 2 (agent comparison):**
     - Read `findings/unified.jsonl`
     - Read `recommendations/agent-recommendations.jsonl` (S3)
     - Read `recommendations/local-mirror.jsonl` (copy of local log, updated by postflight)
     - Call `github_models_client.chat_completion()` with comparison prompt
     - Parse response, append new recommendations with `agent-NNN` IDs
     - Write updated `recommendations/agent-recommendations.jsonl`

10. Create `tests/test_findings_processor_handler.py`:
    - Mock S3 reads/writes
    - Mock `github_models_client.chat_completion`
    - Test deterministic union step
    - Test duplicate detection
    - Test new recommendation creation with correct ID namespace

### Phase 5: Terraform Infrastructure

11. Create `terraform/scheduled_agents.tf`:
    - `aws_secretsmanager_secret.github_pat` + `aws_secretsmanager_secret_version` (placeholder, manual value)
    - `aws_iam_role.scheduled_agent_lambda` with trust policy for Lambda
    - `aws_iam_policy.scheduled_agent_lambda` with permissions:
      - S3: `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on `bblake-platform-agent-logs`
      - Secrets Manager: `secretsmanager:GetSecretValue` on `github_pat` secret ARN
      - CloudWatch Logs: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
    - `aws_lambda_function.scheduled_agent_dispatcher`
    - `aws_lambda_function.findings_processor`
    - `aws_cloudwatch_event_rule.hourly_agents` (cron: `0 * * * ? *`)
    - `aws_cloudwatch_event_target` linking rule to dispatcher Lambda
    - `aws_lambda_permission` for EventBridge to invoke dispatcher
    - `aws_s3_bucket_notification.agent_findings` on `agents/` prefix → findings_processor
    - `aws_lambda_permission` for S3 to invoke processor

12. Modify `terraform/data_pipeline.tf`:
    - Remove `data "aws_iam_openid_connect_provider" "github_actions_existing"` block
    - Remove `resource "aws_iam_openid_connect_provider" "github_actions"` block
    - Remove `locals { github_oidc_provider_arn = ... }` block
    - Remove `resource "aws_iam_role" "github_actions_agent_logs"` block
    - Remove `resource "aws_iam_role_policy_attachment" "github_actions_agent_logs"` block
    - Keep `aws_iam_policy.agent_logs_s3_access` (reused by new Lambda role)

13. Modify `terraform/variables.tf`:
    - Remove `variable "create_github_oidc_provider"` block

14. Modify `terraform/outputs.tf`:
    - Remove `output "github_actions_agent_logs_role_arn"` block
    - Add `output "scheduled_agent_dispatcher_arn"`
    - Add `output "findings_processor_arn"`

15. Modify `terraform/terraform.tfvars`:
    - Remove `create_github_oidc_provider = false` line

### Phase 6: Cleanup and Documentation

16. Delete `.github/workflows/scheduled-agents.yml`

17. Modify `docs/DECISIONS.md`:
    - Update Decision 36 status to "Superseded by Decision 37"
    - Add Decision 37: Lambda + GitHub Models API for Scheduled Agents
      - Context: SCP blocks OIDC from external IPs
      - Decision: Use Lambda + GitHub Models API instead of GitHub Actions + Copilot CLI
      - Trade-offs: Requires Secrets Manager for PAT, but avoids SCP entirely

18. Modify `docs/GETTING_STARTED.md`:
    - Update "Scheduled Agents" section
    - Remove GitHub Actions setup instructions
    - Add Lambda deployment instructions
    - Document Secrets Manager PAT setup

19. Modify `.github/copilot-instructions.md`:
    - Update File Router entries for scheduled agents
    - Adjust SCP gotcha to reference Lambda solution
    - Add entries for new files

20. Modify `.github/copilot_instructions.md`:
    - Mirror changes from copilot-instructions.md

21. Modify `docs/CHANGELOG.md`:
    - Add entry for Lambda migration
    - Note Decision 36 superseded

### Phase 7: Validation

22. Run `pytest tests/` — all tests must pass

23. Run `python scripts/validate.py` — must exit 0

24. Present Terraform plan for human review:
    ```bash
    cd terraform && terraform plan -out=tfplan
    ```
    Wait for human confirmation before apply.

25. Report what was implemented and any design decisions made during implementation
