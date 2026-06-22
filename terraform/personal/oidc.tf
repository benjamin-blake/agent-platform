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

  # TEMPORARY VP9 re-test marker (proves the OIDC trust fix made the gated-apply path work
  # end-to-end). Tag-only IAM update -> guard exit-2 -> tf-gated-apply gated CD apply. Reverted
  # immediately after the gated apply succeeds.
  tags = {
    vp9_retest = "2026-06-22"
  }

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

# ---------------------------------------------------------------------------
# Apply role (sandbox auto-apply): refs/heads/main ONLY (Decision 77, CD.21).
#
# This is the role the .github/workflows/terraform-apply-sandbox.yml workflow assumes to run
# `terraform apply` against terraform/personal on push to main. Its blast radius is the highest of
# any CI role, so two compensating controls bound it (branch protection is now active via the
# main-protection ruleset, Decision 83 / CD.20, but deliberately non-wedging -- the controls
# below remain the authoritative apply gate):
#   1. Trust is scoped to refs/heads/main ONLY -- NOT agent/*, NOT pull/*. A PR or agent branch
#      cannot assume this role; only a merge to main can.
#   2. scripts/terraform_apply_guard.py runs (fail-closed) before apply and blocks any destroy,
#      replacement, IAM-sensitive change, or trust-policy diff -- so even though this policy can
#      write IAM (it must, to manage the roles + OIDC provider in this module), the guard forces
#      any IAM/trust/destroy change onto the manual admin-apply path.
# The policy is ENUMERATED least-privilege scoped to what terraform/personal actually manages:
# glue + athena (workgroup/db), s3 on the data-lake bucket + the tfstate key, dynamodb on the
# counters table, and IAM/OIDC write actions scoped to the module's own role + provider ARNs.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_ci_apply" {
  name        = "agent-platform-github-ci-apply"
  description = "GitHub Actions sandbox auto-apply (Decision 77): refs/heads/main ONLY via OIDC"

  # CD.35 Wave 3 / T2.22 (Decision 92, CORRECTED post-VP9):
  # This role is assumed by TWO apply paths in terraform-apply-sandbox.yml:
  #   1. Routine auto-apply (apply-sandbox job, guard PASS): no job-level environment, so GitHub
  #      mints sub = repo:OWNER/REPO:ref:refs/heads/main.
  #   2. Gated apply (gated-apply job, guard fail-closed set: IAM/trust/destroy): the job declares
  #      environment: tf-gated-apply, and GitHub then OVERRIDES the sub to
  #      repo:OWNER/REPO:environment:tf-gated-apply (the env claim REPLACES the ref claim in sub).
  # The original Decision 92 note asserted the env claim does NOT change the sub and pinned trust
  # to refs/heads/main only. VP9 (live end-to-end test, 2026-06-22) proved that false: the gated
  # job could never assume this role (sts:AssumeRoleWithWebIdentity AccessDenied) because its sub
  # is the environment sub, which the refs/heads/main-only trust rejected. The sub list below now
  # trusts BOTH. This is SAFE: a token with sub = ...:environment:tf-gated-apply can only be minted
  # by a job declaring that environment, and such a job cannot start until the Environment's
  # required reviewer approves -- so the environment sub is itself approval-gated (belt-and-braces
  # with the guard routing). The residual workflow-self-edit concern (a workflow file editing the
  # guard routing) remains Wave 4 / T2.23 (bootstrap root + authority budget); unchanged here.

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
        Resource = ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]
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
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        # CD.35 / T2.20 convergence record (the server-side anti-masking anchor). Among the CI roles
        # the apply identity is the ONLY writer of the durable convergence record -- the integrity
        # anchor the design rests on (a commit status alone is spoofable). Enforced at the IAM layer:
        # this grant + the explicit DenyConvergenceRecordWrite on github_ci_branch + the PR role's
        # read-only S3ReadConvergenceRecord = apply-identity-alone writes among CI roles (full
        # privilege-tiering, incl. removing the admin/breakglass write path, lands at Wave 4). The
        # record lives in its OWN prefix (convergence/personal/*), OUTSIDE tfstate/, so the read-only
        # PR role can be granted read on it without ever seeing tfstate. Scoped to the record prefix
        # only -- no DeleteObject (the record is overwrite-only; clearing red is a green PutObject
        # from the dispatch-ack path, not a delete). This statement is intentionally explicit so the
        # write-identity invariant is auditable in one Sid. At Wave 5 the T2.24 drift identity joins
        # this shared record-writer grant.
        Sid    = "ConvergenceRecordWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
      },
      {
        # s3:GetBucketAcl + s3:GetBucketOwnershipControls are refresh-time reads the AWS provider
        # issues on aws_s3_bucket every plan; without them `terraform plan` fails AccessDenied
        # before the guard runs. Mirrors the platform_admin_datalake (AdminOps-side) grant, which
        # already includes them. Covers the gap rec-1985 flagged. Do not prune as "unused".
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
        # refresh-time reads the provider issues on every plan for all managed aws_s3_bucket resources;
        # do not prune as unused.
        Resource = [
          aws_s3_bucket.data_lake.arn,
          aws_s3_bucket.ducklake_catalog_dr.arn,
        ]
      },
      {
        # athena:ListTagsForResource is the canonical (provider 5.x) refresh-time tag-read on
        # aws_athena_workgroup; without it `terraform plan` fails AccessDenied before the guard
        # runs. athena:GetTags (legacy alias) is retained for compatibility. Surfaced by the
        # post-PR-#75 iterative-discovery round (terraform/CLAUDE.md "Out-of-band IAM grants").
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
        # plan; without it the workflow's `terraform plan` fails AccessDenied before the guard runs.
        # Do not prune it as "unused" -- apply does not exercise it but plan (and therefore CD) does.
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
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*"
        ]
      },
      {
        # DescribeContinuousBackups/DescribeTimeToLive are refresh-time reads the provider issues on
        # aws_dynamodb_table every plan (PITR + TTL status); without them `terraform plan` fails
        # AccessDenied before the guard runs. Reads only -- the corresponding Update* writes are not
        # granted (the counters table has no PITR/TTL config to manage). Do not prune as "unused".
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
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        # IAM/OIDC write actions, ENUMERATED and scoped to the module's OWN role + provider ARNs --
        # NOT iam:* and NOT Resource: "*". This lets terraform apply reconcile the three CI roles
        # and the OIDC provider in-place (e.g. a policy-document edit). The guard blocks any actual
        # IAM/trust diff from auto-applying, so this grant exists for clean no-op/read reconciliation
        # plus the rare guard-approved non-IAM-adjacent plan; genuine IAM changes go via admin apply.
        # NOTE: github_ci_plan is NOT in this write-scoped block -- it is read-only for github_ci_apply
        # (IAMCIPlanRoleRead below). IAM changes to the plan role are guard-BLOCKED and admin-only, so
        # github_ci_apply never needs write IAM on it in the auto-apply CI path.
        Sid    = "IAMRoleReconcile"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:PutRolePolicy",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply",
        ]
      },
      {
        # Read-only quartet on the new plan role (CD.35 Wave 2 / T2.21). The apply role needs to
        # read github_ci_plan's current state during terraform plan (provider refresh walk), but
        # has no business writing it -- IAM changes to the plan role are guard-BLOCKED and land
        # via admin apply. Separated from IAMRoleReconcile to avoid granting PutRolePolicy /
        # UpdateAssumeRolePolicy on a role whose trust the CI pipeline cannot legitimately mutate.
        Sid    = "IAMCIPlanRoleRead"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
        ]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-plan"]
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
        # Refresh-time IAM reads on the PlatformDev + PlatformAdmin roles (both imported and managed
        # by platform_roles.tf). Without these, the AWS provider's per-aws_iam_role plan walk fails
        # AccessDenied before the guard runs. Read-only by design: the platform roles must NOT be
        # CI-mutable; genuine mutation of these roles goes via agent_platform_admin per Decision 35.
        # The four actions are the IAM read-quartet AWS provider 5.x issues on every aws_iam_role
        # plan. Do not prune as "unused" -- apply does not exercise these but plan (and therefore
        # CD) does (same convention as glue:GetTags and dynamodb:Describe* above).
        Sid    = "IAMPlatformRolesRead"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/PlatformDev",
          "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-writer",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-reader",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance",
        ]
      },
      {
        # DuckLake Neon catalog DSN secret (T2.16b / CD.34): the apply role creates + manages the
        # Secrets Manager secret holding the assembled Neon DSN (neon_ducklake_catalog.tf). NOTE the
        # "-*" suffix -- Secrets Manager appends a random 6-char suffix to every secret ARN, so a
        # name-prefix ARN must end in "-*". aws_secretsmanager_secret is NOT in the guard's
        # IAM_SENSITIVE_TYPES, so this create returns guard exit 0 and auto-applies. DescribeSecret /
        # GetResourcePolicy are refresh-time reads the AWS provider issues on every plan -- do not
        # prune them as "unused" (the glue:GetTags / dynamodb:Describe* convention above).
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
        # Neon provider API key secret (created out-of-band in Phase 0). The apply role reads it at
        # plan + apply time to initialise the Neon provider (the
        # data.aws_secretsmanager_secret_version.neon_api_key data source in neon_ducklake_catalog.tf).
        # Read-only -- the key's lifecycle is human-owned, not Terraform-managed.
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # secretsmanager:Describe*/Get* closes the iterative-discovery anti-pattern. Intentional
        # read-surface expansion: Get* subsumes GetResourcePolicy (read-only metadata, no value
        # exposure beyond the already-granted GetSecretValue) -- ARN-scoped to this one secret.
        Sid      = "SecretsManagerNeonAPIKeyRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*"]
      },
      {
        # Tfvars sourcing: the apply job fetches terraform.personal.tfvars from this secret
        # (terraform-apply-sandbox.yml "Materialise tfvars" step) and passes it via -var-file.
        # Mirrors the SecretsManagerNeonAPIKeyRead precedent. Read-only -- the secret lifecycle
        # is human-owned, not Terraform-managed.
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # secretsmanager:Describe*/Get* closes the iterative-discovery anti-pattern. Intentional
        # read-surface expansion: Get* subsumes GetResourcePolicy (read-only metadata, no value
        # exposure beyond the already-granted GetSecretValue) -- ARN-scoped to this one secret.
        # rec-2219: runtime-read-only -- the workflow fetches this secret at apply time; no terraform data source reads it (unlike the Neon precedent).
        Sid      = "SecretsManagerTfvarsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-terraform-personal-tfvars-*"]
      },
      {
        # Inference credential secrets (CD.28 / T0.4): the apply role issues DescribeSecret at
        # plan + apply time for the DeepSeek and Anthropic API key envelopes. Read-only -- the
        # envelopes are created by the admin apply (inference_credentials.tf) and the secret
        # VALUES are set out-of-band (Decision 37); CI must never write them.
        # Mirrors the SecretsManagerNeonAPIKeyRead and SecretsManagerTfvarsRead precedents.
        # Describe*/Get* closes the iterative-discovery anti-pattern (rec-2302).
        Sid    = "SecretsManagerInferenceCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
        ]
      },
      {
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # logs:Describe*/List* on * closes the iterative-discovery anti-pattern for CloudWatch Logs
        # refresh reads. Resource: "*" required (logs:DescribeLogGroups has no resource-level scoping).
        Sid      = "CloudWatchLogsRead"
        Effect   = "Allow"
        Action   = ["logs:Describe*", "logs:List*"]
        Resource = ["*"]
      },
      {
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # lambda:Get*/List* on the ducklake layer + function ARNs covers the full refresh-read set
        # incl. GetFunctionConcurrency / GetRuntimeManagementConfig (previously missing). Do not prune.
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        # Literal ARNs (not resource references): a refresh-read grant should not create a
        # Terraform dependency edge onto the resource it reads. Mirrors the IAMPlatformRolesRead
        # literal-ARN convention.
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
        # apply-phase MODIFY needs AddPermission on the four ducklake functions (EventBridge grants the
        # rule trigger invocation right on the function resource policy at apply time).
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
        # All FIVE ducklake rules in state are covered (catalog-dr, maintenance-merge, maintenance-gc,
        # maintenance-hot-merge, maintenance-merge-ops) to avoid iterative-discovery rounds.
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # events:Describe*/List* closes the iterative-discovery anti-pattern.
        Sid    = "EventBridgeRead"
        Effect = "Allow"
        Action = ["events:Describe*", "events:List*"]
        # Literal ARNs (not resource references): merge-ops is not yet in state, so a resource
        # reference would force its creation; and a refresh-read grant should not depend on the
        # lifecycle of the resource it reads. Mirrors the IAMPlatformRolesRead literal-ARN convention.
        Resource = [
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-catalog-dr",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-gc",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-hot-merge",
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-ducklake-maintenance-merge-ops",
        ]
      },
      {
        # apply-phase MODIFY/CREATE needs PutRule/PutTargets on ducklake EventBridge rules
        # (catalog-dr cadence daily->weekly, maintenance-merge-ops new rule in #166).
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
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # sns:Get*/List* closes the iterative-discovery anti-pattern.
        Sid      = "SNSRead"
        Effect   = "Allow"
        Action   = ["sns:Get*", "sns:List*"]
        Resource = [aws_sns_topic.alerts.arn]
      },
      {
        # sns:GetSubscriptionAttributes does NOT support resource-level permissions (SNS defines no
        # subscription IAM resource type), so Resource: "*" is required -- a topic- or subscription-ARN
        # scope evaluates as implicitDeny (verified via simulate-principal-policy). The provider issues
        # it as a refresh-read on aws_sns_topic_subscription.alerts_email every plan. Do not prune.
        Sid      = "SNSSubscriptionRead"
        Effect   = "Allow"
        Action   = ["sns:GetSubscriptionAttributes"]
        Resource = ["*"]
      },
      {
        # cloudwatch:DescribeAlarms has no resource-level scoping in IAM (account-wide API) -- Resource:
        # "*" is required; ListTagsForResource is the per-alarm tag refresh-read. Both are refresh-time
        # reads the provider issues on every aws_cloudwatch_metric_alarm plan (ducklake catalog-dr-
        # freshness, maintenance-circuit-breaker, writer-errors).
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure):
        # cloudwatch:Describe*/List* closes the iterative-discovery anti-pattern.
        Sid      = "CloudWatchAlarmsRead"
        Effect   = "Allow"
        Action   = ["cloudwatch:Describe*", "cloudwatch:List*"]
        Resource = ["*"]
      },
      {
        # apply-phase MODIFY needs PutMetricAlarm on the three ducklake alarms
        # (freshness alarm re-cadenced to a 7-day daily window, period 86400, by #166 + rec-2252).
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
        # T1.13 feature-flag SSM parameters auto-apply under terraform/personal (feature_flags.tf:
        # ci_rca_strict_mode is a plain String param, guard-PASS). The apply identity manages them, so it
        # needs create/update + tag + refresh-read on the feature-flags path -- scoped to that path, NOT
        # ssm:* and NOT all parameters. This is the apply-role half the T1.13 param shipped without,
        # which latched the convergence record red.
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
        # Covers the ducklake function-URL params (/agent-platform/ducklake/{writer,reader}_url, managed
        # in ducklake_lambdas.tf, admin-applied) which CD only refreshes -- read-only, since writes to the
        # human-gated ducklake stack go via agent_platform_admin. Scoped to /agent-platform/* (NOT ssm:*
        # and NOT all parameters).
        # Per-service read-wildcard closure (PLAN-terraform-sandbox-convergence-closure + rec-2276):
        # ssm:Get*/Describe*/List* closes the iterative-discovery anti-pattern (resource-scoped to /agent-platform/*).
        # ssm:List* added by PLAN-ci-apply-ssm-list-closure (rec-2276): ssm:ListTagsForResource is a
        # List*-class action the AWS provider calls on every aws_ssm_parameter refresh; the original
        # closure set Get*/Describe* and missed it, surfaced by the first apply-sandbox run under the
        # github_ci_apply CI identity (run 27790838857, main 242178f9).
        # Intentional read-surface expansion: the wildcard subsumes GetParameterHistory,
        # GetParametersByPath, and ListTagsForResource in addition to GetParameter(s) -- all read-only
        # and confined to the /agent-platform/* scope (no write, no cross-path enumeration).
        Sid      = "SSMParameterRead"
        Effect   = "Allow"
        Action   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
        Resource = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"]
      },
      {
        # ssm:DescribeParameters is the parameter-METADATA refresh-read the aws_ssm_parameter resource
        # issues after GetParameter (Type/Tier/LastModified). It is a Describe/List-type action with NO
        # resource-level scoping -- Resource: "*" is required (a parameter-ARN scope evaluates as
        # implicitDeny; the provider calls it against arn:aws:ssm:<region>:<acct>:*). Mirrors the
        # cloudwatch:DescribeAlarms / logs:DescribeLogGroups Resource: "*" convention. Do not prune.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters"]
        Resource = ["*"]
      }
    ]
  })
}

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
      }
    ]
  })
}
