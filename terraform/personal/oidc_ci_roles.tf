# GitHub Actions OIDC CI roles (branch write + PR read-only) -- split from oidc.tf
# (Decision 166 terraform-class grandfather drain, PLAN-terraform-decompose-oidc-rename).
#
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
            # Dual-slug transition (Decision 171): flatten over local.github_repos so both the
            # pre- and post-rename slugs are trusted for each ref pattern during the window.
            "token.actions.githubusercontent.com:sub" = flatten([
              for repo in local.github_repos : [
                "repo:${repo}:ref:refs/heads/main",
                "repo:${repo}:ref:refs/heads/agent/*"
              ]
            ])
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
    # ONLY by the sanctioned writer set {github_ci_apply (Wave 1), github_ci_planner main-sub
    # (T2.49 / DEP-12, reserved session only)}. This branch role (ci-rca, agent/* CI) MUST be
    # able to READ the record (ci-rca
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
            # Dual-slug transition (Decision 171): flatten over local.github_repos so both the
            # pre- and post-rename slugs are trusted for each PR-context sub pattern.
            "token.actions.githubusercontent.com:sub" = flatten([
              for repo in local.github_repos : [
                "repo:${repo}:pull_request",
                "repo:${repo}:ref:refs/pull/*"
              ]
            ])
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
    # PLAN-ci-provider-mirror-terraform-init-hardening (rec-2836): read-only, path-scoped grant
    # so the terraform-validate job's pull_request leg can consume the Decision 120 S3-backed
    # provider filesystem_mirror instead of a direct github.com checksum fetch. GetObject only --
    # no write action, no wider resource. Mirrors S3ReadConvergenceRecord's shape immediately
    # above (single-purpose, prefix-scoped read grant on this same bucket).
    sid       = "S3ReadProviderMirror"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/tf-provider-mirror/*"]
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
# github_ci_planner (T2.49 / DEP-12: the merged dual-sub speculative-plan + drift role) lives in
# oidc_pipeline_roles.tf, alongside github_ci_deploy.
