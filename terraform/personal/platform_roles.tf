# Platform agent-auth roles for the personal account.
#
# Codifies the previously out-of-band PlatformDev role (see terraform/CLAUDE.md
# "Out-of-band IAM grants") and closes its PENDING runtime grant. SUPERSEDES the
# work-root terraform/lambda_tooling_iam.tf definitions for the personal account;
# that root is retained per CD.21 but is no longer applied.
#
# Scope: PlatformDev only. PlatformAdmin remains out-of-band (created via the
# platform_breakglass admin) and is intentionally NOT codified here yet -- it is a
# higher-blast-radius role used only from the rarely-spun-up admin environment.
#
# ---------------------------------------------------------------------------
# IMPORT BEFORE APPLY
# ---------------------------------------------------------------------------
# The PlatformDev role already exists in the account (console/breakglass-created).
# Import it so `terraform apply` MODIFIES it rather than trying to re-create it:
#
#   terraform -chdir=terraform/personal import aws_iam_role.platform_dev PlatformDev
#
# SAFETY -- run `terraform plan` and confirm BEFORE applying:
#   - The trust policy (assume_role_policy) shows NO change. If it does, your
#     agent_service_account_user_name or platform_dev_external_id differs from the
#     supplied values -- fix the variable. Do NOT apply a trust-policy change that
#     could lock your agent_static key out of the assume-role chain.
#   - The expected diff is exactly: max_session_duration 3600 -> 36000, plus the
#     ADD of the DailyOps inline policy below (the role is currently permissionless).
#
# platform_dev_external_id is required (no default) and must live in the gitignored
# terraform.personal.tfvars, never in a committed file.

resource "aws_iam_role" "platform_dev" {
  name                 = "PlatformDev"
  max_session_duration = 36000 # 10h; matches duration_seconds in ~/.aws/config so CC-web sessions run unattended
  description          = "Daily agent ops (runtime): Athena query, S3 read/write on the data lake, DynamoDB counters, Glue read"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${var.account_id}:user/${var.agent_service_account_user_name}"
        }
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.platform_dev_external_id
          }
        }
      }
    ]
  })
}

# Runtime grant. Mirrors the github_ci_branch policy (oidc.tf) -- the proven,
# write-capable permission set scoped to this account's actual resources -- so the
# runtime role can do exactly what CI's branch role does (ops portal MERGE writes,
# OPTIMIZE/VACUUM). This is the grant flagged PENDING in terraform/CLAUDE.md.
resource "aws_iam_role_policy" "platform_dev_runtime" {
  name = "DailyOps"
  role = aws_iam_role.platform_dev.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AthenaStartQuery"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:StopQueryExecution"]
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
          "athena:GetWorkGroup",
        ]
        Resource = "*"
      },
      {
        Sid      = "S3ReadWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        Sid      = "S3List"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
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
          "dynamodb:UpdateItem",
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        Sid      = "GlueRead"
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
        Resource = "*"
      },
      {
        # SchemaIntegrityVerifier / IcebergCompactionVerifier call these during OPTIMIZE/VACUUM.
        Sid    = "GlueTableMutations"
        Effect = "Allow"
        Action = ["glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*",
        ]
      },
    ]
  })
}
