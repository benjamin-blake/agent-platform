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
            "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/pull/*"
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
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Apply role (sandbox auto-apply): refs/heads/main ONLY (Decision 77, CD.21).
#
# This is the role the .github/workflows/terraform-apply-sandbox.yml workflow assumes to run
# `terraform apply` against terraform/personal on push to main. Its blast radius is the highest of
# any CI role, so two compensating controls bound it (Decision 72 / CD.20 -- branch protection and
# required status checks are NOT available):
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
            # Trust is pinned to the exact main ref -- NOT a StringLike wildcard. agent/* and
            # pull/* cannot assume this role; only a merge to main can trigger auto-apply.
            "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/main"
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
        Resource = [aws_s3_bucket.data_lake.arn]
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
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply"
        ]
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
        ]
      },
      {
        # PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion).
        # Refresh-time RDS reads required while the RDS-backed DuckLake catalog stack exists. Mirrors
        # platform_admin_ducklake_catalog Sid RDSDescribe (platform_roles.tf:400-417) byte-for-byte;
        # the mirror is authoritative. Resource "*" because Describe-class RDS APIs do not support
        # resource-level scoping. Do not prune as "unused" -- apply does not exercise these but plan
        # (and therefore CD) does. When T2.16b Phase 2 deletes rds_ducklake_catalog.tf, delete this Sid.
        Sid    = "RDSDuckLakeCatalogRead"
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "rds:DescribeDBSubnetGroups",
          "rds:DescribeDBSnapshots",
          "rds:DescribeDBClusterSnapshots",
          "rds:DescribeDBParameterGroups",
          "rds:DescribeDBParameters",
          "rds:DescribeDBClusterParameterGroups",
          "rds:DescribeDBClusters",
          "rds:DescribeOptionGroups",
          "rds:DescribeDBInstanceAutomatedBackups",
          "rds:DescribeDBLogFiles",
          "rds:ListTagsForResource",
        ]
        Resource = "*"
      },
      {
        # PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion).
        # Apply-time write on the DuckLake-catalog RDS parameter group only. Iterative-discovery
        # round 2 after PR #75/#76: the post-PR-#76 sandbox-apply dispatch surfaced a codified
        # apply_method flip (pending-reboot -> immediate) on the rds.force_ssl parameter --
        # provider issues rds:ModifyDBParameterGroup which this role lacked. Scoped to the exact
        # parameter-group ARN. Mirrors the ModifyDBParameterGroup action from
        # platform_admin_ducklake_catalog Sid RDSDuckLakeCatalogManage (platform_roles.tf:423-450)
        # restricted to this single action + this single ARN; the broader CreateDBInstance /
        # DeleteDBInstance lifecycle remains AdminOps-only per Decision 35. Do not prune as
        # "unused" -- post-T2.16b Phase 2, drop this whole Sid (the parameter group is gone).
        Sid    = "RDSDuckLakeCatalogParameterGroupModify"
        Effect = "Allow"
        Action = [
          "rds:ModifyDBParameterGroup",
        ]
        Resource = [
          "arn:aws:rds:${var.aws_region}:${var.account_id}:pg:ducklake-catalog-pg16",
        ]
      },
      {
        # PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion).
        # Refresh-time EC2 networking reads issued by data.aws_vpc / data.aws_subnets /
        # aws_security_group for the RDS catalog stack. Mirrors platform_admin_ducklake_catalog Sid
        # EC2NetworkingDescribe (platform_roles.tf:452-469) byte-for-byte. DescribeVpcAttribute +
        # DescribeAvailabilityZones are refresh-time reads even with multi_az = false (AWS provider
        # 5.100). Resource "*" because Describe-class EC2 APIs do not support resource-level scoping.
        # Do not prune as "unused".
        Sid    = "EC2NetworkingDescribeForRDS"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeVpcAttribute",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSecurityGroupRules",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeTags",
        ]
        Resource = "*"
      },
      {
        # PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion).
        # Refresh-time kms:DescribeKey on the AWS-managed aws/rds + aws/secretsmanager keys (the RDS
        # provider calls DescribeKey directly at plan time to validate encryption). Mirrors the READ
        # subset of platform_admin_ducklake_catalog Sid KMSMetadataForRDS (platform_roles.tf:500-515);
        # explicitly EXCLUDES kms:CreateGrant -- the CI apply role refresh-reads catalog metadata,
        # it does not provision new grants (that goes via agent_platform_admin per Decision 35).
        # Resource "*" because pinning per-account key UUIDs drifts; widening is acceptable here
        # because the only granted action is read-only metadata. Do not prune as "unused".
        Sid    = "KMSDescribeForRDS"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
        ]
        Resource = "*"
      },
      {
        # PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion).
        # Refresh-time DescribeSecret on the RDS-managed master-user secret. manage_master_user_password
        # = true on the catalog DB instance (rds_ducklake_catalog.tf:166) auto-creates a secret under
        # the `rds!` name prefix; the provider DescribeSecret-reads it on every plan. Read-only by
        # design: GetSecretValue is NOT granted -- the master credential is not a CI input. Mirrors
        # the SecretsManagerNeonAPIKeyRead Sid below for the read-only-secret pattern (single
        # DescribeSecret action, ARN-pinned, no value access). Do not prune as "unused".
        Sid      = "SecretsManagerRDSMasterSecretRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:DescribeSecret"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:rds!*"]
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
        Sid    = "SecretsManagerNeonAPIKeyRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*"]
      }
    ]
  })
}
