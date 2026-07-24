# DEP-01 live-proof probe (T2.48 c1, PLAN-t248-passrole-liveproof, PR-2 of 6). Proves a PR adding
# a NEW agent-platform-* Lambda auto-applies end-to-end via terraform-apply-sandbox with zero
# AccessDenied and zero bootstrap edit, now that iam:PassRole is live on github_ci_apply (PR-1 +
# the human-gated bootstrap admin apply). Created here, reverted in the immediately-following
# PR-2-revert PR -- see rollback in docs/plans/PLAN-t248-passrole-liveproof.yaml. THROWAWAY: never
# invoked (no aws_lambda_permission, no EventBridge target, no Function URL); it only needs to
# CREATE cleanly.
#
# NON-IAM BY DESIGN (keeps the guard PASS -> auto-apply, no gated-apply detour): REUSES the
# existing aws_iam_role.ops_compaction (prod_lambdas.tf) as its execution role. This file declares
# NO aws_iam_role / aws_iam_role_policy resource -- adding one would flip
# scripts/terraform_apply_guard.py's deterministic classification to BLOCK (IAM-sensitive).
#
# GO-WRONG TRAP AVOIDED (rec-2831 plan constraint): code is S3-sourced at an EXISTING
# lambda-packages object (lambda-packages/ops-compaction.zip -- already live, same family as the
# reused execution role) with source_code_hash deliberately OMITTED. No Terraform data source or
# hash function that reads a LOCAL zip on disk is used: a zip built in this session's working tree
# at PR-plan time does not exist in the separate apply job's fresh checkout, so the saved plan.bin
# would apply verbatim and then fail to read the file -- a failure that masquerades as an IAM
# problem when it is really a missing artifact. Read+write coverage for the Lambda/log-group/alarm
# is already satisfied by the existing agent-platform-* prefixes (function:agent-platform-*,
# logs:*/cloudwatch:* wildcards, alarm:agent-platform-*) -- zero bootstrap edit required for this
# probe.

locals {
  probe_dep01_function = "agent-platform-probe-liveproof"
}

resource "aws_cloudwatch_log_group" "probe_dep01_liveproof" {
  name              = "/aws/lambda/${local.probe_dep01_function}"
  retention_in_days = 1 # throwaway -- reverted within this plan's PR-2-revert

  tags = {
    Name    = "DEP-01 Live-Proof Probe Logs"
    Purpose = "T2.48 c1 DEP-01 live-proof PLAN-t248-passrole-liveproof PR-2 - throwaway reverted in PR-2-revert"
  }
}

resource "aws_lambda_function" "probe_dep01_liveproof" {
  function_name = local.probe_dep01_function
  description   = "T2.48 c1 DEP-01 live-proof probe PLAN-t248-passrole-liveproof. Throwaway -- reuses the ops_compaction execution role + code; proves CreateFunction succeeds now that PassRole is live. Never invoked."
  role          = aws_iam_role.ops_compaction.arn
  handler       = "src.data.handlers.ops_compaction_handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 30
  memory_size   = 128

  s3_bucket = aws_s3_bucket.data_lake.id
  s3_key    = "lambda-packages/ops-compaction.zip"
  # source_code_hash deliberately OMITTED (GO-WRONG TRAP, see file header): this probe is never
  # invoked or code-updated in place -- DEP-01 only needs lambda:CreateFunction to succeed, not
  # drift-tracked code content.

  depends_on = [
    aws_cloudwatch_log_group.probe_dep01_liveproof,
  ]

  tags = {
    Name    = "DEP-01 Live-Proof Probe"
    Purpose = "T2.48 c1 DEP-01 live-proof PLAN-t248-passrole-liveproof PR-2 - throwaway reverted in PR-2-revert"
  }
}

# CloudWatch alarm satisfying the plan's "one agent-platform-probe-* CloudWatch alarm" scope item.
# Never expected to fire (the probe is never invoked); treat_missing_data=notBreaching keeps it
# quiet in the absence of any Errors datapoints.
resource "aws_cloudwatch_metric_alarm" "probe_dep01_liveproof_errors" {
  alarm_name          = "agent-platform-probe-liveproof-errors"
  alarm_description   = "T2.48 c1 DEP-01 live-proof probe error alarm PLAN-t248-passrole-liveproof PR-2. Throwaway -- reverted in PR-2-revert; the probe is never invoked so this should never fire."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1

  dimensions = {
    FunctionName = aws_lambda_function.probe_dep01_liveproof.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name    = "DEP-01 Live-Proof Probe Alarm"
    Purpose = "T2.48 c1 DEP-01 live-proof PLAN-t248-passrole-liveproof PR-2 - throwaway reverted in PR-2-revert"
  }
}
