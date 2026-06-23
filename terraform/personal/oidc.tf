# GitHub Actions OIDC -> personal-account IAM roles (PLAN-public-migration Step 8, CD.21).
#
# Replaces the retired self-hosted EC2 runner (Decision 68 -> CD.21). CI on GitHub-hosted
# ubuntu-latest assumes these roles via OIDC -- no static credentials, no IAM users (Decision 36/37
# scoped to the work account; the personal account has no such SCP, confirmed by the Phase A OIDC
# feasibility probe under agent_platform_admin).
#
# Two roles, split by trust:
#   branch (write) -- refs/heads/main + refs/heads/agent/*  -> main-validate / ci-rca portal writes
#   pr (read-only)  -- refs/pull/*                          -> PR-context read queries
# The account ID in ARNs comes from var.account_id (gitignored tfvars); never a committed literal.

locals {
  github_repo = "benjamin-blake/agent-platform"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub Actions OIDC root CA thumbprint -- a public, well-known value (not a secret).
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"] # pragma: allowlist secret
}

# ---------------------------------------------------------------------------
# Branch role (write): main + agent/* push/workflow_run context
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_branch" {
  name        = "agent-platform-github-ci-branch"
  description = "GitHub Actions CI (write): main + agent/* branches via OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${local.github_repo}:ref:refs/heads/main",
              "repo:${local.github_repo}:ref:refs/heads/agent/*"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_branch" {
  name = "agent-platform-github-ci-branch"
  role = aws_iam_role.github_ci_branch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AthenaStartQuery"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution"]
        Resource = [aws_athena_workgroup.production.arn]
      },
      {
        # GetQueryExecution/GetQueryResults/ListWorkGroups/GetWorkGroup do not support
        # workgroup-level resource constraints in IAM.
        Sid    = "AthenaQueryStatus"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:ListWorkGroups",
          "athena:GetWorkGroup"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3ReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        # CD.35 / T2.20 single-writer enforcement: the convergence record is written ONLY by the
        # apply identity (github_ci_apply). This branch role (ci-rca, agent/* CI) MUST be able to
        # READ the record (ci-rca anchors its refusal dedup on the red record's commit) but must NOT
        # write or delete it -- an explicit Deny makes the "apply-identity-alone writes the record"
        # integrity claim true at the IAM layer (explicit Deny overrides the bucket-wide S3ReadWrite
        # Allow above; GetObject is untouched). Full privilege-tiering lands at Wave 4 (bootstrap
        # root); this Deny is the Wave-1 enforcement among CI roles.
        Sid    = "DenyConvergenceRecordWrite"
        Effect = "Deny"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
      },
      {
        Sid    = "S3List"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        Sid    = "DynamoDBCounters"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem"
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        Sid    = "GlueRead"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions"
        ]
        Resource = "*"
      },
      {
        # SchemaIntegrityVerifier / IcebergCompactionVerifier call these during OPTIMIZE and VACUUM.
        # Three ARNs required: catalog, database, table.
        Sid    = "GlueTableMutations"
        Effect = "Allow"
        Action = ["glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*"
        ]
      },
      {
        # T2.19 recs cutover (rec-2111): CI/DQ reads recs over the DuckLake reader Function URL and
        # may write recs via the writer. lambda:InvokeFunction is the action the Function-URL IAM
        # authorizer actually checks (InvokeFunctionUrl alone is INSUFFICIENT -- live-verified).
        # InvokeFunctionUrl retained alongside for AWS-doc alignment; not sufficient on its own.
        # lambda:GetFunctionUrlConfig lets the runner RESOLVE the reader/writer URL via the AWS API
        # when neither DUCKLAKE_*_URL env nor a terraform-init'd checkout is present (the CI case) --
        # iceberg_reader / ops_data_portal fall back to get_function_url_config (post-cutover DQ).
        Sid    = "DuckLakeInvokeCI"
        Effect = "Allow"
        Action = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
        Resource = [
          aws_lambda_function.ducklake_writer.arn,
          "${aws_lambda_function.ducklake_writer.arn}:*",
          aws_lambda_function.ducklake_reader.arn,
          "${aws_lambda_function.ducklake_reader.arn}:*",
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# PR role (read-only): refs/pull/* context
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_pr" {
  name        = "agent-platform-github-ci-pr"
  description = "GitHub Actions CI (read-only): PR context via OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            # A pull_request-triggered job presents sub = repo:OWNER/REPO:pull_request -- NOT
            # refs/pull/* (that is the `ref` claim, not `sub`). The advisory terraform-converged
            # status job (terraform-apply-sandbox.yml, pull_request) assumes this read-only role, so
            # the pull_request sub MUST be trusted. refs/pull/* is retained for any ref-scoped or
            # customized-sub consumer. This role stays read-only (athena/iceberg/convergence reads,
            # no tfstate, no writes), so trusting the PR sub does not widen blast radius.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${local.github_repo}:pull_request",
              "repo:${local.github_repo}:ref:refs/pull/*"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_pr" {
  name = "agent-platform-github-ci-pr"
  role = aws_iam_role.github_ci_pr.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AthenaStartQuery"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution"]
        Resource = [aws_athena_workgroup.production.arn]
      },
      {
        Sid    = "AthenaQueryStatus"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:ListWorkGroups",
          "athena:GetWorkGroup"
        ]
        Resource = "*"
      },
      {
        # Read queries still write result sets to the athena/ results prefix only -- not to the
        # iceberg/ table data. No DynamoDB, no Glue mutations: this role cannot mutate ops data.
        Sid    = "S3ReadResults"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/athena/*"]
      },
      {
        Sid      = "S3ReadTables"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/iceberg/*"]
      },
      {
        # CD.35 / T2.20 advisory terraform-converged PR status. The read-only PR role reads the
        # convergence record at PR time to derive the advisory status. Granted on the record prefix
        # ONLY (convergence/personal/*) -- NOT tfstate/: the "github_ci_pr cannot read tfstate"
        # invariant must stay cleanly auditable, which is precisely why the record lives in its own
        # prefix outside tfstate/. Read-only (GetObject); this role never writes the record.
        Sid      = "S3ReadConvergenceRecord"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
      },
      {
        Sid    = "S3List"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        Sid    = "GlueRead"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions"
        ]
        Resource = "*"
      },
      {
        # T2.19 recs cutover (rec-2111): PR CI reads recs over the DuckLake reader Function URL.
        # lambda:InvokeFunction is the action the Function-URL IAM authorizer actually checks.
        # InvokeFunctionUrl retained for AWS-doc alignment; not sufficient alone. PR CI is
        # read-only (no rec writes) but scoped to writer ARNs for consistency / future-compat.
        # lambda:GetFunctionUrlConfig lets the runner resolve the URL via the AWS API (no env / no
        # terraform-init'd checkout) -- mirrors the branch role's DuckLakeInvokeCI grant.
        Sid    = "DuckLakeInvokeCI"
        Effect = "Allow"
        Action = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
        Resource = [
          aws_lambda_function.ducklake_writer.arn,
          "${aws_lambda_function.ducklake_writer.arn}:*",
          aws_lambda_function.ducklake_reader.arn,
          "${aws_lambda_function.ducklake_reader.arn}:*",
        ]
      }
    ]
  })
}

# github_ci_apply role and policy migrated to terraform/bootstrap/ (CD.35 Wave 4 / T2.23).

# ---------------------------------------------------------------------------
# Plan role (speculative-plan PR job, CD.35 Wave 2 / T2.21): pull_request sub.
#
# This role is IAM-SENSITIVE -- the deterministic guard (scripts/terraform_apply_guard.py)
# BLOCKS its creation (exit 2) and it lands via the human-gated agent_platform_admin apply
# (Decision 77). Auto-apply is only possible AFTER the role exists; speculative-plan jobs
# opened before the admin apply carry continue-on-error on the assume-role step.
#
# Capability split vs github_ci_pr:
#   github_ci_pr  -- athena/iceberg read, convergence record read, DuckLake invoke. NO tfstate.
#   github_ci_plan -- tfstate READ (real plan), tfplan WRITE (persist saved plan), same refresh-
#                     read surface as github_ci_apply during plan. No convergence write. No
#                     tfstate write or delete. Fork-gated at the WORKFLOW JOB level (if: guard),
#                     not the trust condition -- trust mirrors github_ci_pr (pull_request sub).
#
# The plan role is the ONLY PR-context tfstate-read path (fork isolation: the guard at the job
# level + same-repo if: block fork access; github_ci_pr is explicitly denied tfstate by design).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_plan" {
  name        = "agent-platform-github-ci-plan"
  description = "GitHub Actions speculative-plan (CD.35 Wave 2 / T2.21): PR context, tfstate-read + tfplan-write via OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            # Trust mirrors github_ci_pr (pull_request sub). Fork gating is enforced at the
            # workflow JOB level (speculative-plan if: head.repo.full_name == github.repository),
            # not the trust condition -- consistent with how advisory-status is fork-gated.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${local.github_repo}:pull_request",
              "repo:${local.github_repo}:ref:refs/pull/*"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name = "agent-platform-github-ci-plan"
  role = aws_iam_role.github_ci_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read tfstate to run a real speculative plan. This is the capability github_ci_pr
        # deliberately lacks. Read-only: NO PutObject / DeleteObject on tfstate.
        Sid      = "TfstateRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]
      },
      {
        # Persist plan.bin keyed by PR head SHA for the apply-the-saved-plan merge path (T2.21).
        # github_ci_apply's existing DataLakeObjectIO grant covers the read at merge time.
        # No convergence/personal/* grant -- the plan role never touches the convergence record.
        # No DeleteObject anywhere.
        Sid      = "TfplanWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/tfplan/personal/*"]
      },
      {
        # Bucket-level access + refresh-time bucket-config reads the AWS provider issues on
        # every plan for all managed aws_s3_bucket resources. Mirrors github_ci_apply DataLakeBucketManage.
        Sid    = "DataLakeBucketRead"
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
          aws_s3_bucket.data_lake.arn,
          aws_s3_bucket.ducklake_catalog_dr.arn,
        ]
      },
      {
        # Athena refresh-time reads the provider issues on aws_athena_workgroup every plan.
        # No StartQueryExecution / CreateWorkGroup / UpdateWorkGroup / Tag (write actions).
        Sid    = "AthenaRead"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetWorkGroup",
          "athena:ListWorkGroups",
          "athena:GetTags",
          "athena:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        # Glue refresh-time reads the provider issues on aws_glue_catalog_database every plan.
        # No Create/Update/Delete (write actions).
        Sid    = "GlueRead"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartitions",
          "glue:GetTags"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*"
        ]
      },
      {
        # DynamoDB refresh-time reads the provider issues on aws_dynamodb_table every plan.
        # No Create/Update/Put/Delete (write actions).
        Sid    = "DynamoDBRead"
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:ListTagsOfResource"
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        # IAM read-quartet the provider issues on each managed aws_iam_role during plan.
        # Scoped to the four CI roles -- read-only (no PutRolePolicy / UpdateAssumeRolePolicy).
        # Literal ARNs per the IAMPlatformRolesRead convention (refresh-read grants do not create
        # Terraform dependency edges onto the resources they read).
        Sid    = "IAMCIRolesRead"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-plan"
        ]
      },
      {
        # IAM read-quartet on the platform roles (codified in platform_roles.tf).
        # Mirrors github_ci_apply's IAMPlatformRolesRead.
        Sid    = "IAMPlatformRolesRead"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/PlatformDev",
          "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-writer",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-reader",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance"
        ]
      },
      {
        # OIDC provider refresh-read.
        Sid      = "OIDCProviderRead"
        Effect   = "Allow"
        Action   = ["iam:GetOpenIDConnectProvider"]
        Resource = ["arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"]
      },
      {
        # Lambda refresh-time reads. Literal ARNs (no Terraform dependency edges).
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
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-ducklake-maintenance"
        ]
      },
      {
        # EventBridge refresh-time reads. Literal ARNs.
        Sid    = "EventBridgeRead"
        Effect = "Allow"
        Action = ["events:Describe*", "events:List*"]
        Resource = [
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-catalog-dr",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-gc",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-hot-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge-ops"
        ]
      },
      {
        # SNS refresh-time reads.
        Sid      = "SNSRead"
        Effect   = "Allow"
        Action   = ["sns:Get*", "sns:List*"]
        Resource = [aws_sns_topic.alerts.arn]
      },
      {
        # sns:GetSubscriptionAttributes has no resource-level scoping; Resource: "*" required.
        Sid      = "SNSSubscriptionRead"
        Effect   = "Allow"
        Action   = ["sns:GetSubscriptionAttributes"]
        Resource = ["*"]
      },
      {
        # CloudWatch refresh-time reads; cloudwatch:DescribeAlarms has no resource-level scoping.
        Sid      = "CloudWatchAlarmsRead"
        Effect   = "Allow"
        Action   = ["cloudwatch:Describe*", "cloudwatch:List*"]
        Resource = ["*"]
      },
      {
        # CloudWatch Logs refresh-time reads; logs:DescribeLogGroups has no resource-level scoping.
        Sid      = "CloudWatchLogsRead"
        Effect   = "Allow"
        Action   = ["logs:Describe*", "logs:List*"]
        Resource = ["*"]
      },
      {
        # SSM parameter refresh-time reads on /agent-platform/*. Mirrors github_ci_apply SSMParameterRead.
        Sid      = "SSMParameterRead"
        Effect   = "Allow"
        Action   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
        Resource = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"]
      },
      {
        # ssm:DescribeParameters has no resource-level scoping; Resource: "*" required.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters"]
        Resource = ["*"]
      },
      {
        # Neon provider API key -- plan-time provider initialisation (read-only).
        Sid      = "SecretsManagerNeonAPIKeyRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*"]
      },
      {
        # Tfvars sourcing: speculative-plan fetches this secret to materialise terraform.personal.tfvars.
        # Read-only -- lifecycle is human-owned.
        Sid      = "SecretsManagerTfvarsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-terraform-personal-tfvars-*"]
      },
      {
        # DuckLake Neon catalog DSN -- plan-time provider initialisation (read-only; apply role manages lifecycle).
        Sid      = "SecretsManagerDuckLakeNeonDSNRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:ducklake-neon-catalog-dsn-*"]
      },
      {
        # Inference credential envelopes (DeepSeek + Anthropic) -- plan-time refresh-read so the
        # speculative-plan job can DescribeSecret these during the provider refresh walk. Mirrors
        # github_ci_apply's SecretsManagerInferenceCredentialsRead (inference-creds-ci-recovery);
        # read-only -- the apply role owns the secret lifecycle.
        Sid    = "SecretsManagerInferenceCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
        ]
      },
      {
        # Broker credential envelopes (Alpaca paper + live) -- plan-time refresh-read so the
        # speculative-plan job can DescribeSecret these during the provider refresh walk for
        # secrets_manager_brokers.tf (T2.14). Mirrors github_ci_apply's
        # SecretsManagerBrokerCredentialsRead. Read-only; values are out-of-band (Decision 37).
        Sid    = "SecretsManagerBrokerCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-*",
        ]
      }
    ]
  })
}
