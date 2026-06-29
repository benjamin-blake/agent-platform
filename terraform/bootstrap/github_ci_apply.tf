# github_ci_apply role + authority budget (CD.35 Wave 4 / T2.23 / Decisions 92, 94).
#
# Migrated from terraform/personal/oidc.tf:
#   - aws_iam_role.github_ci_apply (permissions_boundary now attached)
#   - aws_iam_role_policy.github_ci_apply (self-grant break + rec-2079 consolidation + rec-2305 style)
#
# New in this root:
#   - aws_iam_policy.github_ci_apply_boundary (the authority budget)
#
# The OIDC provider and branch/pr/plan roles stay in terraform/personal/oidc.tf.
# The trust references the OIDC provider as a literal ARN (no cross-root resource reference).

locals {
  github_repo = "benjamin-blake/agent-platform"
}

# Adopt the live role + inline policy without recreate.
import {
  id = "agent-platform-github-ci-apply"
  to = aws_iam_role.github_ci_apply
}

import {
  id = "agent-platform-github-ci-apply:agent-platform-github-ci-apply"
  to = aws_iam_role_policy.github_ci_apply
}

resource "aws_iam_role" "github_ci_apply" {
  name                 = "agent-platform-github-ci-apply"
  description          = "GitHub Actions sandbox auto-apply (Decision 77): refs/heads/main ONLY via OIDC"
  permissions_boundary = aws_iam_policy.github_ci_apply_boundary.arn

  # CD.35 Wave 3 / T2.22 (Decision 92, CORRECTED post-VP9):
  # This role is assumed by TWO apply paths in terraform-apply-sandbox.yml:
  #   1. Routine auto-apply (apply-sandbox job, guard PASS): no job-level environment, so GitHub
  #      mints sub = repo:OWNER/REPO:ref:refs/heads/main.
  #   2. Gated apply (gated-apply job, guard fail-closed set: IAM/trust/destroy): the job declares
  #      environment: tf-gated-apply, and GitHub then OVERRIDES the sub to
  #      repo:OWNER/REPO:environment:tf-gated-apply (the env claim REPLACES the ref claim in sub).
  # Decision 94 (VP9 regression guard): trust MUST keep BOTH subs or the gated-apply path breaks.
  # The OIDC provider stays in terraform/personal/; trust references its ARN as a literal
  # (no cross-root resource reference).
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            # Exact-match list (StringEquals with an array = OR of exact values; NOT a wildcard).
            # agent/* and pull/* still cannot assume this role.
            #   - refs/heads/main          : the routine auto-apply path (no job environment).
            #   - environment:tf-gated-apply: the gated-apply job (GitHub overrides sub to the env
            #     claim when a job declares environment:; approval-gated by the required reviewer).
            "token.actions.githubusercontent.com:sub" = [
              "repo:${local.github_repo}:ref:refs/heads/main",
              "repo:${local.github_repo}:environment:tf-gated-apply"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_apply" {
  name = "agent-platform-github-ci-apply"
  role = aws_iam_role.github_ci_apply.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Terraform S3 backend: read/write the sandbox state object + native lock file (use_lockfile
        # writes a sibling .tflock object under the same key prefix). Scoped to the tfstate prefix.
        Sid    = "TerraformStateBackend"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = ["arn:aws:s3:::agent-platform-data-lake/tfstate/personal/*"]
      },
      {
        # Data-plane object IO the module's resources require during apply (Athena results, Iceberg).
        Sid    = "DataLakeObjectIO"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = ["arn:aws:s3:::agent-platform-data-lake/*"]
      },
      {
        # CD.35 / T2.20 convergence record (the server-side anti-masking anchor). Among the CI roles
        # the apply identity is A writer of the durable convergence record -- the integrity anchor the
        # design rests on (a commit status alone is spoofable). The T2.24 drift identity
        # github_ci_drift joins the sanctioned writer set at Wave 5 (its own inline
        # ConvergenceRecordWrite in terraform/personal/oidc.tf). Enforced at the IAM layer:
        # this grant + the drift identity's grant + the explicit DenyConvergenceRecordWrite on
        # github_ci_branch + the PR role's read-only S3ReadConvergenceRecord = the two-member
        # {apply, drift} writer set among CI roles.
        Sid    = "ConvergenceRecordWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = ["arn:aws:s3:::agent-platform-data-lake/convergence/personal/*"]
      },
      {
        # s3:GetBucketAcl + s3:GetBucketOwnershipControls are refresh-time reads the AWS provider
        # issues on aws_s3_bucket every plan; without them `terraform plan` fails AccessDenied
        # before the guard runs. Do not prune as "unused".
        Sid    = "DataLakeBucketManage"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetBucketVersioning",
          "s3:GetBucketPolicy",
          "s3:GetEncryptionConfiguration",
          "s3:GetBucketPublicAccessBlock",
          "s3:GetBucketTagging",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
          "s3:GetBucketAcl",
          "s3:GetBucketOwnershipControls"
        ]
        Resource = [
          "arn:aws:s3:::agent-platform-data-lake",
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr",
        ]
      },
      {
        # athena:ListTagsForResource is the canonical (provider 5.x) refresh-time tag-read on
        # aws_athena_workgroup; without it `terraform plan` fails AccessDenied before the guard runs.
        # Do not prune as "unused" -- apply does not exercise it but plan does.
        Sid    = "AthenaWorkgroup"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetWorkGroup",
          "athena:ListWorkGroups",
          "athena:CreateWorkGroup",
          "athena:UpdateWorkGroup",
          "athena:TagResource",
          "athena:GetTags",
          "athena:ListTagsForResource",
          "athena:UntagResource"
        ]
        Resource = "*"
      },
      {
        # glue:GetTags is a refresh-time read the provider issues on aws_glue_catalog_database every
        # plan; without it `terraform plan` fails AccessDenied before the guard runs. Do not prune.
        Sid    = "GlueCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:CreateDatabase",
          "glue:UpdateDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartitions",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:GetTags"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/agent_platform",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/agent_platform/*"
        ]
      },
      {
        # DescribeContinuousBackups/DescribeTimeToLive are refresh-time reads the provider issues on
        # aws_dynamodb_table every plan (PITR + TTL status); without them `terraform plan` fails
        # AccessDenied before the guard runs. Do not prune as "unused".
        Sid    = "DynamoDBCounters"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:CreateTable",
          "dynamodb:UpdateTable",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
          "dynamodb:ListTagsOfResource",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem"
        ]
        Resource = ["arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/agent-platform-counters"]
      },
      {
        # Consolidated IAM read-quartet for all roles terraform/personal references during plan:
        # branch, pr, plan, drift, platform, ducklake roles. Separated from write actions
        # (IAMRoleReconcile, IAMRoleCreateBounded, IAMRoleWriteBounded) to keep the write-scope
        # auditable. Literal ARNs per the refresh-read convention (no cross-root dependency edges).
        # rec-2079: IAMCIPlanRoleRead + IAMPlatformRolesRead merged here; no separate Sid for each.
        # Decision 98 (GAP 3 fix): drift added as READ-ONLY refresh grant; the IAM-WRITE budget
        # (IAMRoleWriteBounded / IAMRoleCreateBounded) is unchanged -- in-budget role-create remains
        # gated to T2.25. New peer CI roles are admin-provisioned in terraform/personal and added
        # here as read-only grants; the pipeline does not mint them.
        Sid    = "IAMRolesRead"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-plan",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-drift",
          "arn:aws:iam::${var.account_id}:role/PlatformDev",
          "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-writer",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-reader",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance",
        ]
      },
      {
        # Non-policy write actions for pipeline-managed CI roles (branch + pr only).
        # The apply role's own ARN is excluded (self-grant break, T2.23): github_ci_apply can no
        # longer PutRolePolicy on itself. UpdateAssumeRolePolicy/TagRole/UntagRole do not widen the
        # inline-policy scope and do not require a PermissionsBoundary propagation condition (trust
        # and tag changes carry no escalation risk equivalent to inline-policy mutations; the guard
        # still blocks these from auto-applying).
        Sid    = "IAMRoleReconcile"
        Effect = "Allow"
        Action = [
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
        ]
      },
      {
        # In-budget CreateRole: the pipeline may only create roles that carry the authority budget
        # (T2.23 EC4). iam:PermissionsBoundary propagation condition forces the budget ARN to be
        # specified on every role the pipeline creates. An unbounded role-create is implicitly denied
        # -- no unconditional Allow for iam:CreateRole exists in this policy.
        Sid      = "IAMRoleCreateBounded"
        Effect   = "Allow"
        Action   = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::${var.account_id}:role/*"]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        # In-budget PutRolePolicy/AttachRolePolicy: scoped to pipeline-managed CI roles (branch + pr).
        # The apply role's own ARN is excluded (self-grant break). Condition: target role must carry
        # the authority budget. The machine-readable mirror of these roles + resource types lives in
        # terraform/bootstrap/authority_budget.json (T2.25 / Decision 92 point 5). The guard
        # (scripts/terraform_apply_guard.py) reads that table and auto-applies in-budget inline-policy
        # / attachment UPDATEs on these managed roles; role CREATES and out-of-budget changes still
        # route to the gated-apply Environment. Defense-in-depth at the IAM layer (T2.23 EC4).
        Sid    = "IAMRoleWriteBounded"
        Effect = "Allow"
        Action = [
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
        ]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        Sid    = "OIDCProviderReconcile"
        Effect = "Allow"
        Action = [
          "iam:GetOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider"
        ]
        Resource = ["arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"]
      },
      {
        # DuckLake Neon catalog DSN secret (T2.16b / CD.34): the apply role creates + manages the
        # Secrets Manager secret holding the assembled Neon DSN (neon_ducklake_catalog.tf). NOTE the
        # "-*" suffix -- Secrets Manager appends a random 6-char suffix to every secret ARN.
        # DescribeSecret / GetResourcePolicy are refresh-time reads the AWS provider issues on every
        # plan -- do not prune them as "unused" (glue:GetTags / dynamodb:Describe* convention).
        Sid    = "SecretsManagerDuckLakeNeonDSN"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource"
        ]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:ducklake-neon-catalog-dsn-*"]
      },
      {
        # Neon provider API key secret (created out-of-band in Phase 0). Read-only -- lifecycle is
        # human-owned. Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # Describe*/Get* closes the iterative-discovery anti-pattern. ARN-scoped to this one secret.
        Sid      = "SecretsManagerNeonAPIKeyRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*"]
      },
      {
        # Tfvars sourcing: the apply job fetches terraform.personal.tfvars from this secret at apply
        # time. Read-only -- lifecycle is human-owned.
        # Per-service read-wildcard closure: Describe*/Get* closes the iterative-discovery anti-pattern.
        Sid      = "SecretsManagerTfvarsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-terraform-personal-tfvars-*"]
      },
      {
        # Inference credential envelopes (DeepSeek + Anthropic) -- plan + apply time refresh-read.
        # Read-only -- envelopes are admin-applied (inference_credentials.tf); CI must never write.
        # Mirrors SecretsManagerNeonAPIKeyRead and SecretsManagerTfvarsRead precedents (rec-2305).
        Sid    = "SecretsManagerInferenceCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
        ]
      },
      {
        # Broker credential envelopes (Alpaca paper + live) -- plan + apply time refresh-read for
        # secrets_manager_brokers.tf (T2.14). Mirrors SecretsManagerInferenceCredentialsRead.
        # Read-only; values are out-of-band (Decision 37).
        Sid    = "SecretsManagerBrokerCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-*",
        ]
      },
      {
        # Per-service read-wildcard closure: logs:Describe*/List* on * closes the iterative-discovery
        # anti-pattern for CloudWatch Logs refresh reads. Resource: "*" required (logs:DescribeLogGroups
        # has no resource-level scoping).
        Sid      = "CloudWatchLogsRead"
        Effect   = "Allow"
        Action   = ["logs:Describe*", "logs:List*"]
        Resource = ["*"]
      },
      {
        # Per-service read-wildcard closure: lambda:Get*/List* covers the full refresh-read set
        # incl. GetFunctionConcurrency / GetRuntimeManagementConfig. Do not prune.
        # Literal ARNs: a refresh-read grant should not create a Terraform dependency edge.
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-catalog-dr",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-writer",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-reader",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-maintenance",
        ]
      },
      {
        # apply-phase MODIFY needs AddPermission on the four ducklake functions (EventBridge grants
        # the rule trigger invocation right on the function resource policy at apply time).
        Sid    = "LambdaPermissionWrite"
        Effect = "Allow"
        Action = [
          "lambda:AddPermission",
          "lambda:RemovePermission"
        ]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-catalog-dr",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-writer",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-reader",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-maintenance",
        ]
      },
      {
        # Refresh-time reads the provider issues on aws_cloudwatch_event_rule every plan.
        # Per-service read-wildcard closure: events:Describe*/List* closes the anti-pattern.
        # Literal ARNs: merge-ops is not yet in state; a resource reference would force its creation.
        Sid    = "EventBridgeRead"
        Effect = "Allow"
        Action = ["events:Describe*", "events:List*"]
        Resource = [
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-catalog-dr",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-gc",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-hot-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge-ops",
        ]
      },
      {
        # apply-phase MODIFY/CREATE needs PutRule/PutTargets on ducklake EventBridge rules.
        Sid    = "EventBridgeWrite"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:TagResource",
          "events:UntagResource",
          "events:EnableRule",
          "events:DisableRule"
        ]
        Resource = [
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-catalog-dr",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-gc",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-hot-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge-ops",
        ]
      },
      {
        # Refresh-time reads the provider issues on aws_sns_topic every plan.
        # Per-service read-wildcard closure: sns:Get*/List* closes the anti-pattern.
        Sid      = "SNSRead"
        Effect   = "Allow"
        Action   = ["sns:Get*", "sns:List*"]
        Resource = ["arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts"]
      },
      {
        # sns:GetSubscriptionAttributes does NOT support resource-level permissions (SNS defines no
        # subscription IAM resource type); Resource: "*" is required. The provider issues it as a
        # refresh-read on aws_sns_topic_subscription every plan. Do not prune.
        Sid      = "SNSSubscriptionRead"
        Effect   = "Allow"
        Action   = ["sns:GetSubscriptionAttributes"]
        Resource = ["*"]
      },
      {
        # cloudwatch:DescribeAlarms has no resource-level scoping; Resource: "*" is required.
        # Per-service read-wildcard closure: cloudwatch:Describe*/List* closes the anti-pattern.
        Sid      = "CloudWatchAlarmsRead"
        Effect   = "Allow"
        Action   = ["cloudwatch:Describe*", "cloudwatch:List*"]
        Resource = ["*"]
      },
      {
        # apply-phase MODIFY needs PutMetricAlarm on the three ducklake alarms.
        Sid    = "CloudWatchAlarmsWrite"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource"
        ]
        Resource = [
          "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:ducklake-catalog-dr-freshness",
          "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:ducklake-maintenance-circuit-breaker",
          "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:ducklake-writer-errors",
        ]
      },
      {
        # T1.13 feature-flag SSM parameters auto-apply under terraform/personal (feature_flags.tf).
        # Scoped to /agent-platform/feature-flags/*, NOT ssm:* and NOT all parameters.
        Sid    = "SSMFeatureFlagsManage"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:PutParameter",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource"
        ]
        Resource = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/feature-flags/*"]
      },
      {
        # Refresh-time READ on every agent-platform SSM parameter the provider issues on each plan.
        # Per-service read-wildcard closure + rec-2276 SSM List* completion: Get*/Describe*/List*
        # scoped to /agent-platform/* (not ssm:* and not all parameters).
        Sid      = "SSMParameterRead"
        Effect   = "Allow"
        Action   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
        Resource = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"]
      },
      {
        # ssm:DescribeParameters has no resource-level scoping -- Resource: "*" is required (a
        # parameter-ARN scope evaluates as implicitDeny). Mirrors the cloudwatch:DescribeAlarms /
        # logs:DescribeLogGroups Resource: "*" convention. Do not prune.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters"]
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_iam_policy" "github_ci_apply_boundary" {
  name        = "agent-platform-github-ci-apply-boundary"
  description = "Authority budget for github_ci_apply: permissive data-plane Allow + IAM escalation Deny (CD.35 Wave 4 / T2.23)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Permissive Allow on all data-plane services github_ci_apply uses. A boundary is a ceiling
        # -- it cannot grant more than the identity policy allows. This broad Allow ensures legitimate
        # data-plane capabilities are not silently capped by the boundary (boundary-too-tight silently
        # breaks the pipeline; verified via simulate-principal-policy VP11 "dataplane: allowed").
        # Includes IAM read/OIDC/tag actions and the bounded IAM write actions; DenyIAMEscalation
        # below narrows the write actions at the call site.
        Sid    = "DataPlaneAllow"
        Effect = "Allow"
        Action = [
          "s3:*",
          "athena:*",
          "glue:*",
          "dynamodb:*",
          "lambda:*",
          "logs:*",
          "events:*",
          "sns:*",
          "cloudwatch:*",
          "secretsmanager:*",
          "ssm:*",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:GetOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:CreateRole",
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy"
        ]
        Resource = ["*"]
      },
      {
        # Deny IAM escalation: CreateRole/PutRolePolicy/AttachRolePolicy without the authority budget.
        # StringNotEquals on iam:PermissionsBoundary: if the key is absent from the request context
        # (unbounded create/put), StringNotEquals evaluates to true -> Deny applies. Belt-and-suspenders
        # with the identity policy's conditional Allow (IAMRoleCreateBounded / IAMRoleWriteBounded).
        Sid    = "DenyIAMEscalation"
        Effect = "Deny"
        Action = [
          "iam:CreateRole",
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy"
        ]
        Resource = ["*"]
        Condition = {
          StringNotEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        # Deny boundary removal from any role: prevents the pipeline from stripping the authority
        # budget from itself or from any role it manages.
        Sid      = "DenyBoundaryRemoval"
        Effect   = "Deny"
        Action   = ["iam:DeleteRolePermissionsBoundary"]
        Resource = ["*"]
      },
      {
        # Deny boundary self-modification: the pipeline cannot edit or delete the authority budget
        # policy document that constrains it. The boundary policy ARN is a literal to avoid a
        # circular resource reference.
        Sid    = "DenyBoundaryPolicyModification"
        Effect = "Deny"
        Action = [
          "iam:CreatePolicyVersion",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:SetDefaultPolicyVersion"
        ]
        Resource = ["arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"]
      }
    ]
  })
}
