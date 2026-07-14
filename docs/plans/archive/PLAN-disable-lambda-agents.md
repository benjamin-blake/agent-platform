# PLAN-disable-lambda-agents

**Type:** IMPLEMENTATION
**Branch:** `agent/disable-lambda-agents`
**Scope:** Disable AWS Lambda-based scheduled agent dispatchers in preparation for migration to Claude Code scheduled agents.

---

## Summary

Disable all six scheduled agents (doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, rec-curator) that currently dispatch via the Lambda `scheduled_agent_dispatcher`. The `findings_processor` and `ops_compaction` handlers remain active and unaffected.

**Key design decision:** Use a **two-layer disable** (code + infrastructure) to enable rapid rollback and testing:
1. **Code-level kill-switch:** Add `SCHEDULED_AGENTS_ENABLED` environment variable to the dispatcher handler.
2. **Infrastructure-level disable:** Disable the EventBridge rule in Terraform so Lambda never invokes.

This approach trades a small Terraform change for operational simplicity: rollback requires re-enabling the rule and env var, but the Lambda zip never changes.

---

## Acceptance Criteria

1. ✅ The EventBridge hourly rule (`agent-platform-hourly-scheduled-agents`) is disabled in Terraform.
2. ✅ The `scheduled_agent_handler.py` checks `SCHEDULED_AGENTS_ENABLED` and returns early if disabled.
3. ✅ The Terraform `aws_lambda_function.scheduled_agent_dispatcher` has `environment.variables.SCHEDULED_AGENTS_ENABLED = "false"`.
4. ✅ The weekly rec-curator rule remains unchanged (already disabled).
5. ✅ Findings processor and ops compaction remain active.
6. ✅ Rollback documentation is added to `docs/DECISIONS.md` as a new open decision or to `CLAUDE.md` as a section.
7. ✅ All changes are committed on `agent/disable-lambda-agents` and PR is created.

---

## Affected Areas

| File | Change | Reason |
|------|--------|--------|
| `src/data/handlers/scheduled_agent_handler.py` | Add `SCHEDULED_AGENTS_ENABLED` check at handler entry | Code-level kill-switch |
| `terraform/scheduled_agents.tf` | Disable `aws_cloudwatch_event_rule.hourly_agents` state | Prevent hourly invocations |
| `terraform/scheduled_agents.tf` | Add `SCHEDULED_AGENTS_ENABLED = "false"` to dispatcher env vars | Redundant safety; backup to Terraform rule |
| `docs/DECISIONS.md` or `CLAUDE.md` | Add rollback procedure documentation | Operational runbook for re-enabling |

**Unaffected:**
- `findings_processor_handler.py` — no changes
- `ops_compaction_handler.py` — no changes
- `.github/agents/schedule.yaml` — no changes (agents remain defined, just not dispatched)
- Lambda layers, IAM roles, S3 bucket configuration

---

## Implementation Steps

### Step 1: Modify `scheduled_agent_handler.py`

Add a kill-switch check at the handler entry point. If `SCHEDULED_AGENTS_ENABLED` is not `"true"`, return early with a log message.

**Location:** `src/data/handlers/scheduled_agent_handler.py`, at the start of the `handler()` function.

```python
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler: Scheduled agent dispatcher."""

    # Kill-switch: if SCHEDULED_AGENTS_ENABLED is not explicitly "true", return early.
    if os.environ.get("SCHEDULED_AGENTS_ENABLED", "false").lower() != "true":
        logger.info("Scheduled agents are disabled (SCHEDULED_AGENTS_ENABLED not set to 'true')")
        return {"status": "disabled", "message": "Scheduled agents dispatcher is disabled"}

    # ... rest of handler logic
```

### Step 2: Disable EventBridge Rule in Terraform

Modify `terraform/scheduled_agents.tf` to set the hourly rule state to `"DISABLED"`.

**Location:** `terraform/scheduled_agents.tf`, `aws_cloudwatch_event_rule.hourly_agents` resource (around line 299).

Change:
```hcl
resource "aws_cloudwatch_event_rule" "hourly_agents" {
  name                = "${var.project_name}-hourly-scheduled-agents"
  description         = "Invoke scheduled agent dispatcher every hour"
  schedule_expression = "cron(0 * * * ? *)"
  # ADD THIS LINE:
  state               = "DISABLED"

  tags = {
    Project = var.project_name
  }
}
```

### Step 3: Add Environment Variable to Lambda Function

Modify `terraform/scheduled_agents.tf` to add `SCHEDULED_AGENTS_ENABLED = "false"` to the dispatcher's environment variables.

**Location:** `terraform/scheduled_agents.tf`, `aws_lambda_function.scheduled_agent_dispatcher` resource (around line 247).

Change the `environment` block:
```hcl
environment {
  variables = {
    GITHUB_PAT_SECRET_ARN     = aws_secretsmanager_secret.github_pat.arn
    S3_LOG_BUCKET             = aws_s3_bucket.agent_logs.id
    GEMINI_API_KEY_SECRET_ARN = aws_secretsmanager_secret.gemini_api_key.arn
    SCHEDULED_AGENTS_ENABLED  = "false"  # ADD THIS LINE
  }
}
```

### Step 4: Add Rollback Documentation

Create a rollback procedure in `CLAUDE.md` (or as a new decision in `DECISIONS.md`). Suggested location: root `CLAUDE.md` under a new section "Operational Runbooks".

**Content:**

```markdown
## Rollback: Re-enable Lambda Scheduled Agents

If the Claude Code scheduled agent migration is rolled back, re-enable Lambda dispatchers:

1. **Re-enable EventBridge rule:**
   ```bash
   aws events enable-rule --name agent-platform-hourly-scheduled-agents --profile company-aws-profile
   ```

2. **Enable in Terraform (permanent):**
   - Edit `terraform/scheduled_agents.tf`, remove or comment out `state = "DISABLED"` from `aws_cloudwatch_event_rule.hourly_agents`
   - Edit `terraform/scheduled_agents.tf`, change `SCHEDULED_AGENTS_ENABLED = "false"` to `SCHEDULED_AGENTS_ENABLED = "true"` in the dispatcher's environment variables
   - Run `terraform plan` to verify changes
   - Run `terraform apply` to deploy

3. **Verify:**
   - Check CloudWatch logs for `/aws/lambda/agent-platform-scheduled-agent-dispatcher` — should show agents dispatching within the next hour
   - Verify S3 bucket `agent-platform-agent-logs` receives new agent findings files
```

---

## Verification Plan

| Step | Command | Expected Outcome | Tag | Tier |
|------|---------|---|---|---|
| 1 (structural) | `grep -n "SCHEDULED_AGENTS_ENABLED" src/data/handlers/scheduled_agent_handler.py` | Pattern found; exit early logic present | [pre-deploy] | V1 |
| 2 (structural) | `grep "state.*=.*\"DISABLED\"" terraform/scheduled_agents.tf \| grep -A5 hourly_agents` | EventBridge rule has `state = "DISABLED"` | [pre-deploy] | V1 |
| 3 (structural) | `terraform plan -target=aws_cloudwatch_event_rule.hourly_agents -target=aws_lambda_function.scheduled_agent_dispatcher \| grep -E "(DISABLED\|SCHEDULED_AGENTS_ENABLED)"` | Plan shows rule disabled + env var added | [pre-deploy] | V1 |
| 4 (deployment) | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` | Exit code 0; zip uploaded to S3 | [pre-deploy] | V1 |
| 5 (behavioral) | `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{}' --profile company-aws-profile /tmp/response.json && cat /tmp/response.json` | Response contains `"status": "disabled"` | [post-deploy] | V3 |
| 6 (behavioral) | `aws logs tail /aws/lambda/agent-platform-scheduled-agent-dispatcher --follow --profile company-aws-profile --since 5m` | Log shows "Scheduled agents are disabled" message on invocation | [post-deploy] | V3 |
| 7 (negative) | `aws events list-rules --name-prefix agent-platform-hourly --profile company-aws-profile \| grep -i state` | Rule state shows `"DISABLED"` or not present in active list | [post-deploy] | V2 |
| 8 (integration) | `aws s3 ls s3://agent-platform-agent-logs/agents/ --profile company-aws-profile \| wc -l` | No new findings files appear after 10 minutes (compared to baseline at step start) | [post-deploy] | V2 |

**Verification Plan Notes:**

- **V1 (structural):** Confirm code and Terraform changes landed correctly via grep and plan inspection.
- **V3 (behavioral, steps 5–6):** Manually invoke the dispatcher Lambda with an empty event payload. Verify the handler returns the `"status": "disabled"` response and logs the disable message. This confirms the kill-switch logic executes correctly.
- **V2 (integration, steps 7–8):** Verify the EventBridge rule is disabled and no new agent findings appear in S3. This confirms the Lambda is not auto-invoked.
- **Findings processor & ops_compaction:** Not tested here as they are unaffected. No changes to these handlers; they remain active and triggered by S3 events. If needed for regression testing, inspect their log groups at `/aws/lambda/agent-platform-findings-processor` and `/aws/lambda/agent-platform-ops-compaction`.

---

## Rollback Procedure

**If re-enabling is needed:**

1. **Quick (code-level only, no Terraform apply):**
   ```bash
   aws lambda update-function-configuration \
     --function-name agent-platform-scheduled-agent-dispatcher \
     --environment Variables={SCHEDULED_AGENTS_ENABLED=true,GITHUB_PAT_SECRET_ARN=...,S3_LOG_BUCKET=...,GEMINI_API_KEY_SECRET_ARN=...} \
     --profile company-aws-profile
   ```
   Then re-enable the EventBridge rule:
   ```bash
   aws events enable-rule --name agent-platform-hourly-scheduled-agents --profile company-aws-profile
   ```

2. **Permanent (via Terraform):**
   - Revert changes to `terraform/scheduled_agents.tf` (remove `state = "DISABLED"`, change env var to `"true"`)
   - Run `terraform plan` and `terraform apply`
   - Rebuild and deploy Lambda: `python -m scripts.build_lambda --deploy`

**Verification after rollback:**
- Check CloudWatch logs within 1 hour — should see agent dispatcher invocations
- Verify agent findings files appear in S3 under `agents/` prefix

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| EventBridge rule already disabled | Low | Check current state: `aws events describe-rule --name agent-platform-hourly-scheduled-agents --profile company-aws-profile` |
| Findings processor broken by env var | Low | Findings processor is a separate handler; no env var changes affect it |
| Terraform apply fails | Medium | Run `terraform plan` first; validate no other infra changes are pending |
| rollback blocked by git history | Low | Documented procedure uses AWS CLI, not git revert |

---

## Design Rationale

**Why two layers (code + infrastructure)?**
- **Code kill-switch alone** (env var): Lambda invokes hourly, reads env var, exits early. Minimal cost but not zero.
- **Infrastructure disable alone** (Terraform): Requires reapplying Terraform to re-enable; potential drift if manual CLI changes made.
- **Both together**: EventBridge never invokes Lambda (infrastructure-level); if it does (rule accidentally re-enabled), the handler exits gracefully (code-level). Fastest rollback path: toggle env var (CLI) or re-enable rule (CLI), then redeploy Lambda only if needed.

**Why not just delete the EventBridge rule?**
- Deletion is harder to reverse; keeping the rule disabled preserves the option to re-enable with zero code changes.
- The rule definition is documentation of the intended schedule; deletion hides operational intent.

---

## Notes

- The weekly `rec_curator_weekly` rule remains disabled (it was already disabled in Terraform).
- `.github/agents/schedule.yaml` is not modified; agents remain defined and can be re-dispatched by Claude Code scheduled agents or re-enabled here.
- Telemetry refactor ongoing in parallel; this cutover aligns with that timeline.
