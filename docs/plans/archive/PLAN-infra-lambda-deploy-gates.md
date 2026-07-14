# Plan

## Intent
Establish structural guardrails so that every plan touching Lambda-packaged code automatically includes deployment, IAM provisioning, and smoke-test verification steps -- closing the gap that allowed stale Lambda code to reach production undetected. This directly serves the North Star by making the autonomous agent pipeline self-correcting: the system can no longer silently deploy code without infrastructure readiness.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-lambda-deploy-gates

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| terraform/scheduled_agents.tf | Modify | Add BedrockInference IAM statement (rec-488) + rec-curator dedicated EventBridge rule (rec-450) |
| .github/copilot-instructions.md | Modify | Add build_lambda.py to File Router + Lambda deployment Known Gotcha (rec-484) |
| .github/prompts/plan.prompt.md | Modify | Add Lambda Deployment Assessment rule as new Step 5d (rec-480) |
| .github/agents/plan-critique.agent.md | Modify | Add Lambda deployment verification critique rule (rec-481) |
| config/prompts/executor/planning.prompt.md | Modify | Add Lambda Deployment Assessment section (rec-482) |
| config/prompts/executor/critique.prompt.md | Modify | Add Lambda deployment critique rule (rec-483) |

## Bundled Recommendations
| Rec | Effort | Priority | Title |
|-----|--------|----------|-------|
| rec-488 | XS | Critical | terraform/scheduled_agents.tf: add bedrock:InvokeModel to Lambda IAM policy |
| rec-450 | XS | Medium | Add dedicated EventBridge rule for rec-curator to terraform/scheduled_agents.tf |
| rec-484 | XS | Medium | copilot-instructions.md: build_lambda.py File Router + gotcha |
| rec-480 | XS | High | plan.prompt.md: Lambda Deployment Assessment rule |
| rec-481 | XS | High | plan-critique.agent.md: Lambda deployment critique rule |
| rec-482 | XS | High | executor planning.prompt.md: Lambda Deployment Assessment |
| rec-483 | XS | High | executor critique.prompt.md: Lambda deployment critique rule |

## Infrastructure Dependencies

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| aws_iam_policy.scheduled_agent_lambda (BedrockInference statement) | modify | Yes -- rec-485/486/489 Bedrock calls will fail without this | pre-merge (MUST apply before any Bedrock code merges) | `aws bedrock list-foundation-models --by-provider anthropic --profile company-aws-profile --region eu-west-2 --query "modelSummaries[0].modelId" --output text` (verifies IAM can reach Bedrock API) |
| aws_cloudwatch_event_rule.rec_curator_weekly | create | No -- additive infrastructure | pre-merge (bundled with IAM change) | `aws events describe-rule --name agent-platform-rec-curator-weekly --profile company-aws-profile --region eu-west-2` |
| aws_cloudwatch_event_target.rec_curator_weekly | create | No -- additive infrastructure | pre-merge (bundled) | Covered by rule describe above |
| aws_lambda_permission.allow_eventbridge_rec_curator | create | No -- additive infrastructure | pre-merge (bundled) | Implicit -- EventBridge target creation validates permission |

### Rollback Notes
- BedrockInference statement: Remove the statement block from the IAM policy, run `terraform apply`. No data migration.
- EventBridge resources: `terraform destroy -target=aws_cloudwatch_event_rule.rec_curator_weekly -target=aws_cloudwatch_event_target.rec_curator_weekly -target=aws_lambda_permission.allow_eventbridge_rec_curator`

## Acceptance Criteria
- [ ] `terraform/scheduled_agents.tf` contains `BedrockInference` IAM statement with `bedrock:InvokeModel` action
- [ ] `terraform/scheduled_agents.tf` contains `rec_curator_weekly` EventBridge rule (Monday 08:00 UTC)
- [ ] `terraform apply` succeeds with no errors (human-verified)
- [ ] `.github/copilot-instructions.md` File Router contains `build_lambda.py` entry
- [ ] `.github/copilot-instructions.md` Known Gotchas contains Lambda deployment pipeline gotcha
- [ ] `.github/prompts/plan.prompt.md` contains Lambda Deployment Assessment section (Step 5d)
- [ ] `.github/agents/plan-critique.agent.md` contains Lambda deployment critique rule
- [ ] `config/prompts/executor/planning.prompt.md` contains Lambda Deployment Assessment section
- [ ] `config/prompts/executor/critique.prompt.md` contains Lambda deployment critique rule
- [ ] `python scripts/validate.py` exits 0
- [ ] All 7 bundled recs marked closed in `logs/.recommendations-log.jsonl`

## Constraints
- Terraform apply requires human review of `terraform plan` output before applying (Known Gotcha)
- Executor boundary files (`config/prompts/executor/planning.prompt.md`, `config/prompts/executor/critique.prompt.md`) must go through /plan -> /implement, not the executor (Decision 44)
- Lambda tag values must use ASCII-safe characters only (Known Gotcha)
- No Docker on company VM -- Lambdas use zip packaging via S3- **Complexity waiver:** This plan has 6 scope files and 9 steps, which crosses the Step 5c threshold for STRATEGIC routing. Override rationale: all 7 bundled recs are XS-effort text insertions with pre-existing atomic decomposition. Converting to STRATEGIC would add process overhead with no quality benefit.
## Context
- Decision 47 (docs/DECISIONS.md): Bedrock as single Lambda inference provider. The IAM change in Step 1 is a prerequisite for all automatable Bedrock migration recs (rec-485 through rec-490).
- Decision 44: Executor self-modification boundary. rec-482 and rec-483 target executor prompt files, hence non-automatable.
- Decision 37: Lambda + Secrets Manager architecture. The BedrockInference IAM statement partially supersedes the GitHub Models PAT dependency for inference.
- docs/contracts/inference-provider.md: Authoritative reference for model IDs, IAM requirements, and provider field schema.
- rec-448 (closed): Defines .priority-queue.jsonl schema -- prerequisite for rec-450 (EventBridge rule).

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions -- confirmed: Decision 47, 44, 37 all aligned)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO session active (`aws sts get-caller-identity --profile company-aws-profile` returns account REDACTED-ACCOUNT-ID)

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Terraform -- add BedrockInference IAM + rec-curator EventBridge rule (rec-488, rec-450)

**File:** `terraform/scheduled_agents.tf`

**Pre-condition:** File exists, contains `aws_iam_policy.scheduled_agent_lambda` with S3AgentLogs, SecretsManagerGithubPat, and CloudWatchLogs statements but no Bedrock statement.

**Changes:**

1. **BedrockInference IAM statement (rec-488):** Add a new statement block to `aws_iam_policy.scheduled_agent_lambda`:
   ```hcl
   {
     Sid    = "BedrockInference"
     Effect = "Allow"
     Action = [
       "bedrock:InvokeModel",
       "bedrock:InvokeModelWithResponseStream"
     ]
     Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/*"
   }
   ```
   Update the comment above the policy block: replace "Model access is NOT controlled by IAM -- the Lambda calls the GitHub Models API" with "Bedrock model access is IAM-native (Decision 47). GitHub Models PAT retained for non-inference API calls."

2. **rec-curator EventBridge rule (rec-450):** After the existing EventBridge resources, add:
   - `aws_cloudwatch_event_rule.rec_curator_weekly` with `schedule_expression = "cron(0 8 ? * MON *)"` and `state = "DISABLED"` (enabled after rec-curator agent is added to Lambda package), description "Weekly rec-curator agent - prioritises recommendation backlog"
   - `aws_cloudwatch_event_target.rec_curator_weekly` targeting the existing `aws_lambda_function.scheduled_agent_dispatcher` ARN with `input = jsonencode({agent_name = "rec-curator"})`
   - `aws_lambda_permission.allow_eventbridge_rec_curator` allowing the new rule to invoke the dispatcher Lambda
   - Use ASCII hyphens only in all tag values

**Post-condition:** File contains `BedrockInference` statement and `rec_curator_weekly` resources.

### Step 2: Terraform plan, human review, and apply

**HUMAN GATE -- this step requires human interaction.**

The implementing agent must:
1. Run `terraform plan -out=tfplan` from the `terraform/` directory using `--profile company-aws-profile`:
   ```bash
   cd terraform && terraform plan -out=tfplan -var-file=terraform.tfvars
   ```
2. Summarise the plan output for the human. Present:
   - Number of resources to add/change/destroy
   - The specific IAM policy change (BedrockInference statement)
   - The new EventBridge resources (rec_curator_weekly rule, target, permission)
   - Any unexpected changes
3. **STOP and ask the human:** "Terraform plan shows [N] to add, [N] to change, [N] to destroy. [summary]. Say 'apply' to proceed or describe concerns."
4. **Only after the human says "apply":** Run `terraform apply tfplan`
5. Verify apply succeeded (exit code 0)
6. Clean up: `rm tfplan`

**Post-condition:** `terraform apply` completed successfully. Resources exist in AWS.

### Step 3: copilot-instructions.md -- File Router entry + Known Gotcha (rec-484)

**File:** `.github/copilot-instructions.md`

**Changes:**

1. **File Router:** Add a new row to the File Router table:
   ```
   | Lambda build and deploy | [scripts/build_lambda.py](../scripts/build_lambda.py) |
   ```
   Place it near the existing infrastructure entries (after the "Terraform / infra" row or similar logical position).

2. **Known Gotchas:** Add a new gotcha entry:
   ```
   - **Lambda deployment pipeline (Important):** Any plan modifying Lambda-packaged files (src/data/handlers/, .github/agents/schedule.yaml, .github/prompts/scheduled/, config/, or scripts/ files listed in _LAMBDA_SCRIPTS in build_lambda.py) must include: (1) `python -m scripts.build_lambda` to build the zip, (2) `--deploy` flag to upload to S3 and update Lambda function code for dispatcher and findings-processor, (3) `run_scheduled_agent.py --smoke-test NAME` to verify post-deploy. Bedrock model IDs (e.g., `anthropic.claude-3-5-haiku-20241022-v1:0`) differ from GitHub Models IDs (`gpt-5-mini`) and Copilot Chat model IDs (`claude-opus-4.6`). See `docs/contracts/inference-provider.md` and Decision 47.
   ```

**Post-condition:** File Router contains `build_lambda.py` row. Known Gotchas contains Lambda deployment pipeline entry.

### Step 4: plan.prompt.md -- Lambda Deployment Assessment (rec-480)

**File:** `.github/prompts/plan.prompt.md`

**Changes:** Add a new `## Step 5d: Lambda Deployment Assessment` section immediately after `## Step 5c: Complexity Assessment`. Content:

```markdown
## Step 5d: Lambda Deployment Assessment

If ANY file in the Scope table is Lambda-packaged (check against this list):
- Files under `src/data/handlers/`
- Files under `.github/agents/` (specifically `schedule.yaml`)
- Files under `.github/prompts/scheduled/`
- Files under `config/`
- Scripts listed in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`

Then the plan MUST include these steps in the Ordered Execution Steps:

1. **Lambda rebuild step:** `python -m scripts.build_lambda` to rebuild the zip package
2. **Lambda deploy step:** `python -m scripts.build_lambda --deploy` to upload to S3 and update Lambda function code for both dispatcher and findings-processor
3. **Smoke test step:** `python -m scripts.run_scheduled_agent --smoke-test <agent-name>` to verify the deployed Lambda executes correctly
4. **Model ID validation:** If any model ID is added or changed, verify it matches Bedrock format per `docs/contracts/inference-provider.md` (format: `{provider}.{model-family}-{date}-{revision}:{version}`)

If the Scope includes `.tf` files that add or modify Lambda IAM permissions, the terraform apply MUST precede the Lambda deploy step (IAM must be in place before code that depends on it runs).

Reference: Decision 47 (docs/DECISIONS.md), docs/contracts/inference-provider.md
```

**Post-condition:** plan.prompt.md contains "Lambda Deployment Assessment" section between Step 5c and Step 6.

### Step 5: plan-critique.agent.md -- Lambda deployment critique rule (rec-481)

**File:** `.github/agents/plan-critique.agent.md`

**Changes:** Add a new check to Phase 2 (Strategic Analysis), inserted as item 12b after the existing item 12 (Check Constraints for contradictions). Do NOT renumber existing items 13-14 -- use "12b" to minimise diff churn:

```markdown
12b. **Lambda deployment completeness (IMPLEMENTATION plans only):** If any file in the Scope table is Lambda-packaged (under `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, or in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`), the Ordered Execution Steps MUST include: (a) a `build_lambda.py --deploy` step, (b) a smoke-test step using `run_scheduled_agent.py --smoke-test`, and (c) model ID validation against `docs/contracts/inference-provider.md` if model IDs are changed. If any are missing, recommend REVISE. Reference: Decision 47, Step 5d of plan.prompt.md.
```

Also add to the Phase 3 structured output template, after "Acceptance Criteria Issues", a new line:
```
**Lambda Deployment Completeness:** Complete / Missing [list missing steps]
```

**Post-condition:** plan-critique.agent.md contains Lambda deployment completeness check and structured output field.

### Step 6a: Executor planning prompt -- Lambda Deployment Assessment (rec-482)

**File:** `config/prompts/executor/planning.prompt.md`

**Changes:** Add a new section after the existing "Multi-Call-Site Decomposition Rule" section and before "Acceptance Commands -- CRITICAL":

```markdown
## Lambda Deployment Assessment -- CRITICAL
When the recommendation targets a Lambda-packaged file (under `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, or listed in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`):

1. The plan MUST include a step that runs `python -m scripts.build_lambda --deploy` AFTER all code changes are complete
2. If the recommendation changes model IDs, the plan MUST include validation against `docs/contracts/inference-provider.md`
3. If the recommendation depends on IAM changes (e.g., Bedrock permissions), note in the step description that `terraform apply` must precede deployment

This rule prevents Lambda code changes from being merged without deployment verification. Reference: Decision 47, docs/contracts/inference-provider.md.
```

**Post-condition:** `config/prompts/executor/planning.prompt.md` contains Lambda Deployment Assessment section.

### Step 6b: Executor critique prompt -- Lambda deployment hard-fail rule (rec-483)

**File:** `config/prompts/executor/critique.prompt.md`

**Changes:** Add to the `## Hard-Fail Rules` section, as a new paragraph after the existing external tools sentence:

```markdown
Steps that modify Lambda-packaged files (src/data/handlers/, .github/agents/schedule.yaml, .github/prompts/scheduled/, config/, scripts/_LAMBDA_SCRIPTS) without a `build_lambda.py --deploy` step in the plan are NEEDS_REVISION. Reference: Decision 47, docs/contracts/inference-provider.md.
```

**Post-condition:** `config/prompts/executor/critique.prompt.md` contains Lambda deployment hard-fail rule.

### Step 7: Run validation

Run `python scripts/validate.py` -- must exit 0. This confirms all file edits are syntactically valid and no rules are broken.

### Step 8: Update recommendation statuses

Mark all 7 bundled recs as closed in `logs/.recommendations-log.jsonl`:
- rec-480: status -> closed, execution_result -> success
- rec-481: status -> closed, execution_result -> success
- rec-482: status -> closed, execution_result -> success
- rec-483: status -> closed, execution_result -> success
- rec-484: status -> closed, execution_result -> success
- rec-488: status -> closed, execution_result -> success
- rec-450: status -> closed, execution_result -> success

### Step 9: Report implementation summary

Report what was implemented and any design decisions made during implementation. List any issues encountered and how they were resolved.
