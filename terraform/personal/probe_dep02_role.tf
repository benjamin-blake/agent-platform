# DEP-02 live-proof probe (T2.48 c2, PLAN-t248-passrole-liveproof, PR-3).
#
# THROWAWAY: created here, reverted whole in PR-3-revert. Proves the DEP-02 acceptance -- a NEW
# boundary-carrying agent-platform-* role created via the gated path (guard BLOCKs iam:CreateRole
# on aws_iam_role -> routes to the tf-gated-apply GitHub Environment -> HUMAN approval -> apply)
# with 0 AccessDenied and WITHOUT invoking the admin tier. CreateRole is in-budget ONLY because
# this role declares the mandatory permissions_boundary below (IAMRoleCreateBounded's
# PermissionsBoundary condition) -- an unbounded create would AccessDeny.
#
# Referenced by NO workflow / NO CI config (rec-2824 dodge): the bootstrap deadlock only fires
# when a role PR repoints its OWN CI onto the not-yet-existent role; this role is never a trust
# target or job runner for anything, so it structurally cannot trip that deadlock.

resource "aws_iam_role" "probe_dep02" {
  # Decision 144 (T2.48): mandatory broad-but-bounded exec-identity boundary (16/17 roles; PlatformAdmin excluded).
  # Name MUST byte-match the ARN pre-staged in terraform/bootstrap/github_ci_apply.tf's IAMRolesRead
  # list (PR-1) and the entry added to the github_ci_planner IAMPlatformRolesRead list below (PR-3) --
  # any mismatch breaks validate_ci_refresh_read_coverage and the gated CreateRole never resolves.
  name                 = "agent-platform-probe-liveproof-role"
  description          = "DEP-02 live-proof probe (T2.48 c2) -- throwaway, reverted in PR-3-revert"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

  # Inlined (not the shared data.aws_iam_policy_document.lambda_assume from ducklake_lambdas.tf)
  # so this throwaway probe's trust grant is fully self-contained in this one file, cleanly
  # removable in PR-3-revert with no cross-file coupling.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

locals {
  probe_dep02_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Minimal in-boundary grant: its own log group only. The boundary DataPlaneAllow ceiling
        # already grants logs:* broadly, so this stays well within budget.
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-probe-liveproof-role:*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "probe_dep02" {
  name   = "ProbeLiveproofRuntime"
  role   = aws_iam_role.probe_dep02.id
  policy = local.probe_dep02_policy_json

  lifecycle {
    precondition {
      # rec-2793 (DEP-01 anti-recurrence): AWS excludes whitespace from the 10,240 B inline-policy
      # limit, so measure the WHITESPACE-STRIPPED/minified rendering, not the raw (pretty-printed)
      # jsonencode() string (mirrors github_ci_apply / github_ci_planner / github_ci_deploy).
      condition     = length(jsonencode(jsondecode(local.probe_dep02_policy_json))) <= 10240
      error_message = "probe_dep02 inline policy exceeds the 10,240 B IAM inline-policy limit (whitespace-stripped measure, rec-2793)."
    }
  }
}
