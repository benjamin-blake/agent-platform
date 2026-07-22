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
# Shared refresh-read policy fragments (T2.34 / Decision 104): DRY composition so the
# CI-role refresh-read surface cannot silently drift between peer roles (rec-2363 and
# predecessors rec-2223/2251/2276). Every CI role that invokes the DuckLake reader/writer
# composes ci_ssm_refresh_read via source_policy_documents rather than re-declaring the SSM
# statements inline (validated credential-free by
# scripts/checks/iam_tf/validate_invoke_implies_resolve.py, T2.34:c2); github_ci_plan and
# github_ci_drift additionally compose the shared 20-statement refresh-read surface via
# ci_full_refresh_read (which itself sources ci_ssm_refresh_read). IAM read statements stay
# enumerated with literal ARNs (Decision 35/98) -- composition relocates statements, it never
# collapses them into a wildcard.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ci_ssm_refresh_read" {
  statement {
    # SSM parameter refresh-time reads on /agent-platform/*. Sourced by every CI role that
    # invokes the DuckLake reader/writer (branch, pr, plan via ci_full_refresh_read, drift via
    # ci_full_refresh_read).
    sid       = "SSMParameterRead"
    effect    = "Allow"
    actions   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"]
  }

  statement {
    # ssm:DescribeParameters has no resource-level scoping; Resource: "*" required.
    sid       = "SSMDescribeParameters"
    effect    = "Allow"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "ci_full_refresh_read" {
  # Composes the shared SSM fragment so plan/drift never re-declare it inline.
  source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

  statement {
    # Read tfstate to run a real speculative plan / drift plan. Read-only: NO PutObject /
    # DeleteObject on the state object itself. Byte-identical between plan and drift (verified
    # 2026-06-05); composed here rather than declared per-role.
    sid       = "TfstateRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]
  }

  statement {
    # Bucket-level access + refresh-time bucket-config reads the AWS provider issues on every
    # plan for all managed aws_s3_bucket resources.
    sid    = "DataLakeBucketRead"
    effect = "Allow"
    actions = [
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
      "s3:GetBucketOwnershipControls",
      # T2.43 gap: aws_s3_bucket_notification.data_lake_prod_triggers refresh-reads this.
      "s3:GetBucketNotification"
    ]
    resources = [
      aws_s3_bucket.data_lake.arn,
      aws_s3_bucket.ducklake_catalog_dr.arn,
    ]
  }

  statement {
    # Athena refresh-time reads the provider issues on aws_athena_workgroup every plan.
    # No StartQueryExecution / CreateWorkGroup / UpdateWorkGroup / Tag (write actions).
    sid    = "AthenaRead"
    effect = "Allow"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
      "athena:ListWorkGroups",
      "athena:GetTags",
      "athena:ListTagsForResource"
    ]
    resources = ["*"]
  }

  statement {
    # Glue refresh-time reads the provider issues on aws_glue_catalog_database every plan.
    # No Create/Update/Delete (write actions).
    sid    = "GlueRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
      "glue:GetTags"
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
      "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*"
    ]
  }

  statement {
    # DynamoDB refresh-time reads the provider issues on aws_dynamodb_table every plan.
    # No Create/Update/Put/Delete (write actions).
    sid    = "DynamoDBRead"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource"
    ]
    resources = [aws_dynamodb_table.counters.arn]
  }

  statement {
    # IAM read-quartet the provider issues on each managed aws_iam_role during plan.
    # Scoped to the managed CI roles -- read-only (no PutRolePolicy / UpdateAssumeRolePolicy).
    # Literal ARNs per the IAMPlatformRolesRead convention (refresh-read grants do not create
    # Terraform dependency edges onto the resources they read). Decision 35/98: enumerated,
    # never a service or path wildcard on iam: read actions. ducklake-deploy (T2.38) is listed
    # so github_ci_plan/drift can refresh-read it once it enters terraform/personal state --
    # the github_ci_plan/drift analogue of the bootstrap IAMRolesRead grant github_ci_apply gets
    # (rec-2688; mirrors how github-ci-drift's own ARN was added here when T2.24 landed).
    # prod-deploy (T2.43) is listed the same way for the same reason.
    sid    = "IAMCIRolesRead"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies"
    ]
    resources = [
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-plan",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-drift",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-ducklake-deploy",
      "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-prod-deploy"
    ]
  }

  statement {
    # IAM read-quartet on the platform roles (codified in platform_roles.tf). Decision 35/98:
    # enumerated literal ARNs, never a wildcard.
    sid    = "IAMPlatformRolesRead"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies"
    ]
    resources = [
      "arn:aws:iam::${var.account_id}:role/PlatformDev",
      "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",
      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-writer",
      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-reader",
      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance",
      # T2.18 c9 split gap (same class as rec-2688 for ducklake-deploy): the smoke exec role must be
      # refresh-readable by github_ci_plan/drift once it enters terraform/personal state, or every
      # subsequent plan against this module fails closed with AccessDenied.
      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance-smoke",
      # T2.43 gap (same class as rec-2688 for ducklake-deploy): these three prod-class execution
      # roles must be refresh-readable by github_ci_plan/drift once they enter terraform/personal
      # state, or every subsequent plan against this module fails closed with AccessDenied.
      "arn:aws:iam::${var.account_id}:role/agent-platform-scheduled-agent-dispatcher",
      "arn:aws:iam::${var.account_id}:role/agent-platform-findings-processor",
      "arn:aws:iam::${var.account_id}:role/agent-platform-ops-compaction"
    ]
  }

  statement {
    # OIDC provider refresh-read.
    sid       = "OIDCProviderRead"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = ["arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"]
  }

  statement {
    # Lambda refresh-time reads. Layer ARNs stay enumerated (mixed ducklake-*/data-pipeline-*
    # naming); function ARNs use the account-wide function:agent-platform-* prefix (Decision 129 /
    # T2.43 rec-2702 anti-recurrence) so a future agent-platform-* function auto-covers -- keeps
    # this role's data-plane read surface identical to github_ci_apply's (the parity the
    # validate_ci_refresh_read_coverage verifier relies on).
    sid     = "LambdaRead"
    effect  = "Allow"
    actions = ["lambda:Get*", "lambda:List*"]
    resources = [
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient:*",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps:*",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions:*",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:data-pipeline-deps",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:data-pipeline-deps:*",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-*",
    ]
  }

  statement {
    # EventBridge refresh-time reads. Broadened to the account-wide rule/agent-platform-* prefix
    # (Decision 129 / T2.43 rec-2702 anti-recurrence) -- mirrors the LambdaRead broadening above.
    sid     = "EventBridgeRead"
    effect  = "Allow"
    actions = ["events:Describe*", "events:List*"]
    resources = [
      "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-*",
    ]
  }

  statement {
    # SNS refresh-time reads.
    sid       = "SNSRead"
    effect    = "Allow"
    actions   = ["sns:Get*", "sns:List*"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    # sns:GetSubscriptionAttributes has no resource-level scoping; Resource: "*" required.
    sid       = "SNSSubscriptionRead"
    effect    = "Allow"
    actions   = ["sns:GetSubscriptionAttributes"]
    resources = ["*"]
  }

  statement {
    # CloudWatch refresh-time reads; cloudwatch:DescribeAlarms has no resource-level scoping.
    sid       = "CloudWatchAlarmsRead"
    effect    = "Allow"
    actions   = ["cloudwatch:Describe*", "cloudwatch:List*"]
    resources = ["*"]
  }

  statement {
    # CloudWatch Logs refresh-time reads; logs:DescribeLogGroups has no resource-level scoping.
    sid       = "CloudWatchLogsRead"
    effect    = "Allow"
    actions   = ["logs:Describe*", "logs:List*"]
    resources = ["*"]
  }

  statement {
    # Neon provider API key -- plan-time provider initialisation (read-only).
    sid       = "SecretsManagerNeonAPIKeyRead"
    effect    = "Allow"
    actions   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*"]
  }

  statement {
    # Tfvars sourcing: plan/drift fetch this secret to materialise terraform.personal.tfvars.
    # Read-only -- lifecycle is human-owned.
    sid       = "SecretsManagerTfvarsRead"
    effect    = "Allow"
    actions   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-terraform-personal-tfvars-*"]
  }

  statement {
    # DuckLake Neon catalog DSN -- plan-time provider initialisation (read-only; apply role manages lifecycle).
    sid       = "SecretsManagerDuckLakeNeonDSNRead"
    effect    = "Allow"
    actions   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:ducklake-neon-catalog-dsn-*"]
  }

  statement {
    # T2.43 gap: the scheduled-agent-dispatcher / findings-processor GitHub PAT secret --
    # read-only; the value is set out-of-band (Decision 37), this apply role owns the secret's
    # lifecycle only.
    sid       = "SecretsManagerGithubPatRead"
    effect    = "Allow"
    actions   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-github-pat-*"]
  }

  statement {
    # Inference credential envelopes (DeepSeek + Anthropic) -- plan-time refresh-read so the
    # speculative-plan / drift jobs can DescribeSecret these during the provider refresh walk.
    # Mirrors github_ci_apply's SecretsManagerInferenceCredentialsRead (inference-creds-ci-recovery);
    # read-only -- the apply role owns the secret lifecycle.
    sid     = "SecretsManagerInferenceCredentialsRead"
    effect  = "Allow"
    actions = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
      "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
    ]
  }

  statement {
    # Broker credential envelopes (Alpaca paper + live) -- plan-time refresh-read so the
    # speculative-plan / drift jobs can DescribeSecret these during the provider refresh walk for
    # secrets_manager_brokers.tf (T2.14). Read-only; values are out-of-band (Decision 37).
    sid     = "SecretsManagerBrokerCredentialsRead"
    effect  = "Allow"
    actions = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-*",
    ]
  }
}

# ---------------------------------------------------------------------------
# Branch role (write): main + agent/* push/workflow_run context
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_branch" {
  name                 = "agent-platform-github-ci-branch"
  description          = "GitHub Actions CI (write): main + agent/* branches via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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

data "aws_iam_policy_document" "github_ci_branch" {
  # DRY composition (T2.34): the shared SSM refresh-read fragment, not re-declared inline.
  source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

  statement {
    sid       = "AthenaStartQuery"
    effect    = "Allow"
    actions   = ["athena:StartQueryExecution"]
    resources = [aws_athena_workgroup.production.arn]
  }

  statement {
    # GetQueryExecution/GetQueryResults/ListWorkGroups/GetWorkGroup do not support
    # workgroup-level resource constraints in IAM.
    sid    = "AthenaQueryStatus"
    effect = "Allow"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:ListWorkGroups",
      "athena:GetWorkGroup"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3ReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${aws_s3_bucket.data_lake.arn}/*"]
  }

  statement {
    # CD.35 / T2.20 single-writer enforcement: among CI roles the convergence record is written
    # ONLY by the sanctioned writer set {github_ci_apply (Wave 1), github_ci_drift (T2.24 /
    # Wave 5)}. This branch role (ci-rca, agent/* CI) MUST be able to READ the record (ci-rca
    # anchors its refusal dedup on the red record's commit) but must NOT write or delete it --
    # an explicit Deny makes the two-member writer-set integrity claim true at the IAM layer
    # (explicit Deny overrides the bucket-wide S3ReadWrite Allow above; GetObject is untouched).
    # Full privilege-tiering landed at Wave 4 / T2.23 (bootstrap root); this Deny is the Wave-1
    # enforcement among CI roles.
    sid    = "DenyConvergenceRecordWrite"
    effect = "Deny"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }

  statement {
    sid    = "S3List"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid    = "DynamoDBCounters"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.counters.arn]
  }

  statement {
    sid    = "GlueRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetPartitions"
    ]
    resources = ["*"]
  }

  statement {
    # SchemaIntegrityVerifier / IcebergCompactionVerifier call these during OPTIMIZE and VACUUM.
    # Three ARNs required: catalog, database, table.
    sid     = "GlueTableMutations"
    effect  = "Allow"
    actions = ["glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"]
    resources = [
      "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
      "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*"
    ]
  }

  statement {
    # T2.19 recs cutover (rec-2111): CI/DQ reads recs over the DuckLake reader Function URL and
    # may write recs via the writer. lambda:InvokeFunction is the action the Function-URL IAM
    # authorizer actually checks (InvokeFunctionUrl alone is INSUFFICIENT -- live-verified).
    # InvokeFunctionUrl retained alongside for AWS-doc alignment; not sufficient on its own.
    # lambda:GetFunctionUrlConfig lets the runner RESOLVE the reader/writer URL via the AWS API
    # when neither DUCKLAKE_*_URL env nor a terraform-init'd checkout is present (the CI case) --
    # iceberg_reader / ops_data_portal fall back to get_function_url_config (post-cutover DQ).
    sid     = "DuckLakeInvokeCI"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
    resources = [
      aws_lambda_function.ducklake_writer.arn,
      "${aws_lambda_function.ducklake_writer.arn}:*",
      aws_lambda_function.ducklake_reader.arn,
      "${aws_lambda_function.ducklake_reader.arn}:*",
    ]
  }

  statement {
    # T2.18 c9 split (bundled Decision amending Decision 81 cl.1): deploy-ducklake-lambdas.yml's
    # smoke job invokes the four maintenance smoke gates (--lambda-maintenance-merge/gc/breaker/
    # hot-merge) post-deploy, the autonomous c9 gate. Scoped to the SMOKE function ARN ONLY -- this
    # is the whole point of the split: github_ci_branch (the always-on public-repo CI identity) must
    # NEVER be granted invoke on the admin ducklake_maintenance ARN (see DuckLakeInvokeCI above,
    # which deliberately omits it, and ducklake_maintenance.tf, which grants no CI invoke at all).
    sid     = "MaintenanceSmokeInvokeCI"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
    resources = [
      aws_lambda_function.ducklake_maintenance_smoke.arn,
      "${aws_lambda_function.ducklake_maintenance_smoke.arn}:*",
    ]
  }

  statement {
    # T2.43: the deploy-prod-lambdas.yml smoke job assumes this role to invoke each prod-class
    # function and assert observable output (mirrors the ducklake smoke job reusing this role's
    # DuckLakeInvokeCI grant above -- these three functions have no Function URL, so plain
    # lambda:InvokeFunction is sufficient; no InvokeFunctionUrl/GetFunctionUrlConfig needed).
    sid     = "ProdLambdaInvokeCI"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.scheduled_agent_dispatcher.arn,
      aws_lambda_function.findings_processor.arn,
      aws_lambda_function.ops_compaction.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_ci_branch" {
  name   = "agent-platform-github-ci-branch"
  role   = aws_iam_role.github_ci_branch.id
  policy = data.aws_iam_policy_document.github_ci_branch.json
}

# ---------------------------------------------------------------------------
# PR role (read-only): refs/pull/* context
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_pr" {
  name                 = "agent-platform-github-ci-pr"
  description          = "GitHub Actions CI (read-only): PR context via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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

data "aws_iam_policy_document" "github_ci_pr" {
  # T2.34 / Decision 92 NOTE (INTENTIONAL EXPANSION): github_ci_pr gains read-only
  # ssm:Get*/Describe*/List* on parameter/agent-platform/* via the shared fragment. This is a
  # permission expansion on a role that runs on pull_request events -- accepted deliberately
  # (read-only, path-scoped, mirrors the other invoking roles' DuckLake Function-URL resolution
  # fallback) so the invoke-implies-resolve invariant (T2.34:c2) holds universally, with no
  # exceptions, across every CI role that invokes the DuckLake reader/writer.
  source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

  statement {
    sid       = "AthenaStartQuery"
    effect    = "Allow"
    actions   = ["athena:StartQueryExecution"]
    resources = [aws_athena_workgroup.production.arn]
  }

  statement {
    sid    = "AthenaQueryStatus"
    effect = "Allow"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:ListWorkGroups",
      "athena:GetWorkGroup"
    ]
    resources = ["*"]
  }

  statement {
    # Read queries still write result sets to the athena/ results prefix only -- not to the
    # iceberg/ table data. No DynamoDB, no Glue mutations: this role cannot mutate ops data.
    sid    = "S3ReadResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${aws_s3_bucket.data_lake.arn}/athena/*"]
  }

  statement {
    sid       = "S3ReadTables"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/iceberg/*"]
  }

  statement {
    # CD.35 / T2.20 advisory terraform-converged PR status. The read-only PR role reads the
    # convergence record at PR time to derive the advisory status. Granted on the record prefix
    # ONLY (convergence/personal/*) -- NOT tfstate/: the "github_ci_pr cannot read tfstate"
    # invariant must stay cleanly auditable, which is precisely why the record lives in its own
    # prefix outside tfstate/. Read-only (GetObject); this role never writes the record.
    sid       = "S3ReadConvergenceRecord"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }

  statement {
    sid    = "S3List"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid    = "GlueRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetPartitions"
    ]
    resources = ["*"]
  }

  statement {
    # T2.19 recs cutover (rec-2111): PR CI reads recs over the DuckLake reader Function URL.
    # lambda:InvokeFunction is the action the Function-URL IAM authorizer actually checks.
    # InvokeFunctionUrl retained for AWS-doc alignment; not sufficient alone. PR CI is
    # read-only (no rec writes) but scoped to writer ARNs for consistency / future-compat.
    # lambda:GetFunctionUrlConfig lets the runner resolve the URL via the AWS API (no env / no
    # terraform-init'd checkout) -- mirrors the branch role's DuckLakeInvokeCI grant.
    sid     = "DuckLakeInvokeCI"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
    resources = [
      aws_lambda_function.ducklake_writer.arn,
      "${aws_lambda_function.ducklake_writer.arn}:*",
      aws_lambda_function.ducklake_reader.arn,
      "${aws_lambda_function.ducklake_reader.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "github_ci_pr" {
  name   = "agent-platform-github-ci-pr"
  role   = aws_iam_role.github_ci_pr.id
  policy = data.aws_iam_policy_document.github_ci_pr.json
}

# github_ci_apply role and policy migrated to terraform/bootstrap/ (CD.35 Wave 4 / T2.23).
# github_ci_drift added below (CD.35 Wave 5 / T2.24).

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
  name                 = "agent-platform-github-ci-plan"
  description          = "GitHub Actions speculative-plan (CD.35 Wave 2 / T2.21): PR context, tfstate-read + tfplan-write via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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

data "aws_iam_policy_document" "github_ci_plan" {
  # DRY composition (T2.34): the shared 20-statement refresh-read surface, not re-declared
  # inline. ci_full_refresh_read itself composes ci_ssm_refresh_read.
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]

  statement {
    # Persist plan.bin keyed by PR head SHA for the apply-the-saved-plan merge path (T2.21).
    # github_ci_apply's existing DataLakeObjectIO grant covers the read at merge time.
    # No convergence/personal/* grant -- the plan role never touches the convergence record.
    # No DeleteObject anywhere.
    sid       = "TfplanWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/tfplan/personal/*"]
  }

  statement {
    # rec-2512: fetch the vendored pg_dump/pg_restore bundle + pinned DuckLake extensions at
    # build time (`scripts.build_lambda --ducklake-only`, run before `terraform plan` so
    # filemd5() sees real content instead of resolving to null on lambda-packages/, which is
    # gitignored). Read-only -- these are operator-seeded vendored artefacts, never written by CI.
    sid     = "DucklakeBuildInputsRead"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/ducklake-pgclient/*",
      "${aws_s3_bucket.data_lake.arn}/ducklake-extensions/*"
    ]
  }

  statement {
    # rec-2512: upload the seven rebuilt DuckLake zips so the reviewed plan.bin's filemd5
    # corresponds to real S3 content, and so the apply-sandbox job's byte-identical re-upload at
    # merge time has the PR-job artifact to compare against (Decision 77 no-TOCTOU). No
    # DeleteObject -- mirrors the plan role's no-delete-anywhere posture.
    sid       = "DucklakeLambdaPackagesWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/lambda-packages/*"]
  }
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name   = "agent-platform-github-ci-plan"
  role   = aws_iam_role.github_ci_plan.id
  policy = data.aws_iam_policy_document.github_ci_plan.json
}

# ---------------------------------------------------------------------------
# Drift role (alarm-only scheduled drift detection, CD.35 Wave 5 / T2.24):
# refs/heads/main sub (scheduled + dispatch run on main, same as github_ci_branch).
#
# This role is IAM-SENSITIVE -- the deterministic guard (scripts/terraform_apply_guard.py)
# BLOCKS its creation (exit 2) and it lands via the human-gated apply path (tf-gated-apply
# GitHub Environment or agent_platform_admin, Decision 77/92). The scheduled drift workflow
# carries continue-on-error on the assume-role step to cover the bootstrap window (no role
# exists until the gated apply lands; pre-apply ticks no-op rather than erroring).
#
# Capability split vs github_ci_plan:
#   github_ci_plan  -- tfstate READ + tfplan WRITE + same refresh-read surface. No convergence write.
#   github_ci_drift -- tfstate READ + scoped .tflock write (native-lock coexistence) +
#                      convergence/personal/* read+write (joins apply as sanctioned writer) +
#                      ducklake-WRITER invoke ONLY (not the reader; Decision 84 closed boundary) +
#                      same refresh-read surface as plan during plan. NO tfstate write (state object),
#                      NO tfplan write, NO resource mutation, NO IAM write.
#
# Trust mirrors github_ci_branch: StringEquals aud + StringLike sub refs/heads/main.
# NO environment sub (Decision 94 applies only to github_ci_apply's gated-environment invocation;
# drift is scheduled, not gated-environment-invoked).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_drift" {
  name                 = "agent-platform-github-ci-drift"
  description          = "GitHub Actions drift detector (CD.35 Wave 5 / T2.24): scheduled alarm-only, refs/heads/main via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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
            # Mirrors github_ci_branch (scheduled + dispatch jobs run on main, not in a PR context).
            # NO environment sub: drift is not gated-environment-invoked (Decision 94).
            "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/main"
          }
        }
      }
    ]
  })
}

data "aws_iam_policy_document" "github_ci_drift" {
  # DRY composition (T2.34): the shared 20-statement refresh-read surface, not re-declared
  # inline. ci_full_refresh_read itself composes ci_ssm_refresh_read.
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]

  statement {
    # Native S3 locking coexistence (use_lockfile): terraform plan -lock=true acquires the
    # native lock by writing a sibling .tflock object and releases it on plan completion.
    # Scoped to the EXACT lock object key -- NO write on the state object terraform.tfstate
    # itself. A lock held by an in-flight apply -> plan fails to acquire -> "Error acquiring
    # the state lock" -> skip-this-cycle (exit 0, no alarm).
    sid     = "TfstateNativeLockFile"
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/tfstate/personal/sandbox/terraform.tfstate.tflock"
    ]
  }

  statement {
    # CD.35 / T2.24 convergence record write: drift joins the sanctioned writer set {apply,
    # drift}. On a green->red transition the drift workflow merge-writes the record (preserves
    # all fields; sets status=red + drift reason marker + run_url + detected_at). Read is
    # needed to check prior_status before deciding whether to flip (dedup: one red = one
    # signal). Drift NEVER writes the record green -- green is written solely by a converged
    # apply (T2.20 anti-masking anchor). No DeleteObject on the convergence prefix.
    sid       = "ConvergenceRecordWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }

  statement {
    # Decision 84 closed reader/writer boundary: drift invokes the WRITER ONLY (to file the
    # drift rec via the ops portal). The reader is explicitly excluded -- drift never reads
    # the ops data directly. lambda:InvokeFunction is the action the Function-URL IAM
    # authorizer actually checks; InvokeFunctionUrl retained for AWS-doc alignment.
    # GetFunctionUrlConfig lets the runner resolve the URL via the AWS API when
    # DUCKLAKE_WRITER_URL env is not set (the CI case) -- mirrors the branch role pattern.
    sid     = "DuckLakeWriterInvoke"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl", "lambda:GetFunctionUrlConfig"]
    resources = [
      aws_lambda_function.ducklake_writer.arn,
      "${aws_lambda_function.ducklake_writer.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "github_ci_drift" {
  name   = "agent-platform-github-ci-drift"
  role   = aws_iam_role.github_ci_drift.id
  policy = data.aws_iam_policy_document.github_ci_drift.json
}

# ---------------------------------------------------------------------------
# DuckLake deploy role (governed code-deploy channel, T2.38 / Decision 125/126):
# refs/heads/main sub (push-triggered governed deploy workflow only).
#
# This role is IAM-SENSITIVE -- the deterministic guard (scripts/terraform_apply_guard.py)
# BLOCKS its creation (exit 2) and it lands via the human-gated admin-create path (Decision 98),
# mirroring github_ci_plan / github_ci_drift. The governed deploy workflow
# (.github/workflows/deploy-ducklake-lambdas.yml) carries continue-on-error on the assume-role
# step to cover the bootstrap window (no role exists until the admin-create apply lands;
# pre-apply pushes no-op rather than erroring).
#
# Capability shape (deliberately narrow -- "UpdateFunctionCode-only" is the literal invariant):
#   - lambda:UpdateFunctionCode on the four ducklake function ARNs ONLY. No
#     UpdateFunctionConfiguration, no InvokeFunction*, no PublishVersion, no AddPermission, no
#     other lambda: action.
#   - S3: GetObject/PutObject on lambda-packages/* (build + upload the zips), PutObject on
#     deploy-records/ducklake/* (c3 deploy-record write -- this role never reads its own records
#     back; convergence-health/drift tooling reads via github_ci_branch's existing bucket-wide
#     read grant), and GetObject on the two vendored build-input prefixes (ducklake-pgclient/*,
#     ducklake-extensions/*) that `build_lambda --ducklake-only` reads at build time -- mirrors
#     github_ci_plan's DucklakeBuildInputsRead precedent, needed because build+deploy share one
#     identity here.
#   - No terraform:*, no iam:* of any kind.
#
# Trust mirrors github_ci_branch/github_ci_drift: StringEquals aud + StringLike sub
# refs/heads/main ONLY (no agent/*, no pull/*, no environment sub -- this role is never assumed
# from a PR or a gated Environment).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_ducklake_deploy" {
  name                 = "agent-platform-github-ci-ducklake-deploy"
  description          = "GitHub Actions governed DuckLake Lambda code deploy (T2.38 / Decision 125/126): refs/heads/main via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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
            "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/main"
          }
        }
      }
    ]
  })
}

data "aws_iam_policy_document" "github_ci_ducklake_deploy" {
  statement {
    # c1: the ONLY Lambda action this role grants -- UpdateFunctionCode on the four ducklake
    # function ARNs. No lambda-config (UpdateFunctionConfiguration), no invoke, no
    # publish-version/add-permission. Resource references (not literal ARNs): this role's whole
    # purpose is deploying these functions' code, so a real Terraform dependency edge is correct
    # here (unlike the refresh-read fragments above, which deliberately avoid one).
    sid     = "DucklakeUpdateFunctionCode"
    effect  = "Allow"
    actions = ["lambda:UpdateFunctionCode"]
    resources = [
      aws_lambda_function.ducklake_writer.arn,
      aws_lambda_function.ducklake_reader.arn,
      aws_lambda_function.ducklake_maintenance.arn,
      aws_lambda_function.ducklake_catalog_dr.arn,
      # T2.18 c9 split: the 5th DuckLake function. Without this the governed CD deploy
      # (deploy-ducklake-lambdas.yml) AccessDenies on UpdateFunctionCode for the smoke function.
      aws_lambda_function.ducklake_maintenance_smoke.arn,
    ]
  }

  statement {
    # build_lambda's validate_bucket_exists runs `aws s3api head-bucket` before uploading (the
    # --deploy path does NOT pass --skip-upload), and head-bucket requires bucket-level
    # s3:ListBucket. github_ci_plan gets this via DataLakeBucketRead in ci_full_refresh_read; this
    # role composes no shared fragment, so grant it explicitly. Bucket-level ONLY (resource is the
    # bucket ARN, no /*): head-bucket needs the bucket resource, not object resources. Without it
    # the first governed deploy fails closed with a misleading "bucket does not exist" (rc 1).
    sid       = "DataLakeHeadBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    # Build + upload the four function zips (and three layer zips, when rebuilt) to
    # lambda-packages/. Matches github_ci_plan's DucklakeLambdaPackagesWrite scope.
    sid       = "DucklakeLambdaPackagesReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/lambda-packages/*"]
  }

  statement {
    # c3: write the per-function deployment record (function -> CodeSha256 -> source git SHA).
    sid       = "DeployRecordWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/deploy-records/ducklake/*"]
  }

  statement {
    # Vendored build inputs `build_lambda --ducklake-only` reads at build time (pg_dump/pg_restore
    # bundle + pinned DuckLake extensions). Read-only -- operator-seeded, never written by CI.
    # Mirrors github_ci_plan's DucklakeBuildInputsRead: build+deploy share one identity here, so
    # this role needs the same build-time reads plan does. Do NOT narrow S3 to lambda-packages/*
    # only -- the first governed deploy would fail AccessDenied at build time.
    sid     = "DucklakeBuildInputsRead"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/ducklake-pgclient/*",
      "${aws_s3_bucket.data_lake.arn}/ducklake-extensions/*"
    ]
  }
}

resource "aws_iam_role_policy" "github_ci_ducklake_deploy" {
  name   = "agent-platform-github-ci-ducklake-deploy"
  role   = aws_iam_role.github_ci_ducklake_deploy.id
  policy = data.aws_iam_policy_document.github_ci_ducklake_deploy.json
}

# ---------------------------------------------------------------------------
# Prod-class deploy role (governed code-deploy channel, T2.43 / Decision 125/126):
# refs/heads/main sub (push-triggered governed deploy workflow only). Mirrors
# github_ci_ducklake_deploy exactly, scoped to the three T2.43 prod functions instead.
#
# This role is IAM-SENSITIVE -- the deterministic guard (scripts/terraform_apply_guard.py)
# BLOCKS its creation (exit 2) and it lands via the human-gated admin-create path (Decision 98),
# mirroring github_ci_plan / github_ci_drift / github_ci_ducklake_deploy. The governed deploy
# workflow (.github/workflows/deploy-prod-lambdas.yml) carries continue-on-error on the assume-role
# step to cover the bootstrap window (no role exists until the admin-create apply lands; pre-apply
# pushes no-op rather than erroring).
#
# Capability shape (deliberately narrow -- "UpdateFunctionCode-only" is the literal invariant):
#   - lambda:UpdateFunctionCode on the three prod function ARNs ONLY. No
#     UpdateFunctionConfiguration, no InvokeFunction*, no PublishVersion, no AddPermission, no
#     other lambda: action.
#   - S3: GetObject/PutObject on lambda-packages/* (build + upload the zips) and PutObject on
#     deploy-records/prod/* (deploy-record write -- this role never reads its own records back;
#     convergence-health/drift tooling reads via github_ci_branch's existing bucket-wide read
#     grant).
#   - No terraform:*, no iam:* of any kind.
#
# Trust mirrors github_ci_branch/github_ci_drift/github_ci_ducklake_deploy: StringEquals aud +
# StringLike sub refs/heads/main ONLY (no agent/*, no pull/*, no environment sub -- this role is
# never assumed from a PR or a gated Environment).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_prod_deploy" {
  name                 = "agent-platform-github-ci-prod-deploy"
  description          = "GitHub Actions governed prod-class Lambda code deploy (T2.43 / Decision 125/126): refs/heads/main via OIDC"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"

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
            "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/main"
          }
        }
      }
    ]
  })
}

data "aws_iam_policy_document" "github_ci_prod_deploy" {
  statement {
    # The ONLY Lambda action this role grants -- UpdateFunctionCode on the three prod function
    # ARNs. No lambda-config (UpdateFunctionConfiguration), no invoke, no publish-version/
    # add-permission. Resource references (not literal ARNs): this role's whole purpose is
    # deploying these functions' code, so a real Terraform dependency edge is correct here
    # (unlike the refresh-read fragments above, which deliberately avoid one).
    sid     = "ProdUpdateFunctionCode"
    effect  = "Allow"
    actions = ["lambda:UpdateFunctionCode"]
    resources = [
      aws_lambda_function.scheduled_agent_dispatcher.arn,
      aws_lambda_function.findings_processor.arn,
      aws_lambda_function.ops_compaction.arn,
    ]
  }

  statement {
    # build_lambda's validate_bucket_exists runs `aws s3api head-bucket` before uploading (the
    # --deploy path does NOT pass --skip-upload), and head-bucket requires bucket-level
    # s3:ListBucket. Bucket-level ONLY (resource is the bucket ARN, no /*): head-bucket needs the
    # bucket resource, not object resources. Without it the first governed deploy fails closed
    # with a misleading "bucket does not exist" (rc 1). Mirrors github_ci_ducklake_deploy's
    # DataLakeHeadBucket.
    sid       = "DataLakeHeadBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    # Build + upload the three function zips (and the data-pipeline-deps layer zip, when rebuilt)
    # to lambda-packages/. Matches github_ci_ducklake_deploy's DucklakeLambdaPackagesReadWrite scope.
    sid       = "ProdLambdaPackagesReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/lambda-packages/*"]
  }

  statement {
    # Write the per-function deployment record (function -> CodeSha256 -> source git SHA).
    sid       = "DeployRecordWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/deploy-records/prod/*"]
  }
}

resource "aws_iam_role_policy" "github_ci_prod_deploy" {
  name   = "agent-platform-github-ci-prod-deploy"
  role   = aws_iam_role.github_ci_prod_deploy.id
  policy = data.aws_iam_policy_document.github_ci_prod_deploy.json
}
