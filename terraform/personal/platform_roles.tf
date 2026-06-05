# Platform agent-auth roles for the personal account.
#
# Codifies the previously out-of-band PlatformDev role (see terraform/CLAUDE.md
# "Out-of-band IAM grants") and closes its PENDING runtime grant. SUPERSEDES the
# work-root terraform/lambda_tooling_iam.tf definitions for the personal account;
# that root is retained per CD.21 but is no longer applied.
#
# Scope: PlatformDev (runtime) and PlatformAdmin (provisioning). PlatformAdmin is the
# higher-blast-radius role used only from the rarely-spun-up admin environment; it is now
# codified here (AdminOps + PlatformDataLakeProvisioning) -- see its own IMPORT BEFORE APPLY
# banner below. Both roles pre-exist (breakglass-created) and MUST be imported before apply.
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

# ---------------------------------------------------------------------------
# PlatformAdmin -- provisioning role (IAM import + admin Lambda/secrets + data-lake provisioning)
# ---------------------------------------------------------------------------
# Codifies the previously out-of-band PlatformAdmin role and its two inline policies
# (AdminOps + PlatformDataLakeProvisioning, see terraform/CLAUDE.md "Out-of-band IAM grants").
# Personal-module idiom: default provider, var.account_id, var.agent_service_account_user_name --
# NOT the work-root aws.platform / var.platform_account_id / aws_iam_user.agent_service_account.
#
# IMPORT BEFORE APPLY
#   terraform -chdir=terraform/personal import aws_iam_role.platform_admin PlatformAdmin
#
# SAFETY -- run `terraform plan` and confirm BEFORE applying:
#   - The trust policy (assume_role_policy) MUST show NO change. PlatformAdmin is the role this
#     very apply assumes (profile agent_platform_admin); a trust-policy diff risks locking the
#     agent_static/breakglass principal out of the assume-role chain. If the trust shows a diff,
#     STOP and reconcile platform_admin_external_id / agent_service_account_user_name against the
#     live role -- do NOT apply.
#   - max_session_duration should already be 3600 on the live role (no change expected).
#   - The expected diff is exactly the ADD of the AdminOps + PlatformDataLakeProvisioning inline
#     policies (the role's inline policies are not imported, only the role).
#
# platform_admin_external_id is required (no default); it lives in the gitignored
# terraform.personal.tfvars, never in a committed file.

resource "aws_iam_role" "platform_admin" {
  name                 = "PlatformAdmin"
  max_session_duration = 3600 # AWS IAM minimum; admin sessions kept short (limit further via duration_seconds in ~/.aws/config)
  description          = "Admin ops (provisioning): iam:* for import, admin Lambda management, secrets, and data-lake provisioning"

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
            "sts:ExternalId" = var.platform_admin_external_id
          }
        }
      }
    ]
  })
}

# AdminOps: identity admin (iam:*) + admin Lambda management + secrets. Policy bodies mirror
# terraform/lambda_tooling_iam.tf (work-root, no longer applied); idiom is personal-module.
resource "aws_iam_role_policy" "platform_admin_ops" {
  name = "AdminOps"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IAMFull"
        Effect   = "Allow"
        Action   = "iam:*"
        Resource = "*"
      },
      {
        Sid    = "LambdaAdminManagement"
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:InvokeFunctionUrl",
          "lambda:InvokeFunction",
          "lambda:GetFunction",
          "lambda:ListFunctions",
        ]
        Resource = "*"
      },
      {
        # Tag/Untag/Update/GetResourcePolicy complete the secret-management set so AdminOps can fully
        # manage TAGGED secrets it creates (e.g. the DuckLake Neon DSN). Creating a secret with tags
        # requires secretsmanager:TagResource even when the tags are passed inline to CreateSecret.
        Sid    = "SecretsManagerAdmin"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:CreateSecret",
          "secretsmanager:UpdateSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
        ]
        Resource = "*"
      },
    ]
  })
}

# PlatformDataLakeProvisioning: the data-plane rights AdminOps (iam:*/lambda/secrets) lacks, so
# `terraform apply` under agent_platform_admin can provision + manage terraform/personal's data lake.
# Least-privilege: ENUMERATED actions (no glue:*/athena:*/s3:*/dynamodb:*) scoped to the agent-platform
# data lake -- no Resource "*" where the action supports a resource, no legacy bblake-* ARNs. This is
# the surface terraform apply of THIS module actually exercises: the same data-plane action set as the
# github_ci_apply CI role (oidc.tf), minus the IAM/OIDC reconcile statements (those come from iam:* in
# AdminOps) and minus item-level DynamoDB (counter VALUES are PlatformDev runtime's domain).
resource "aws_iam_role_policy" "platform_admin_datalake" {
  name = "PlatformDataLakeProvisioning"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Glue catalog: create/read/update the ops database + its Iceberg tables and _current views
        # (the null_resource Athena DDL creates them; CREATE OR REPLACE VIEW + schema evolution edit
        # the table objects). Scoped to the catalog + the agent_platform DB + its tables. glue:GetTags
        # is a refresh-time read the provider issues on aws_glue_catalog_database every plan.
        Sid    = "GlueCatalog"
        Effect = "Allow"
        Action = [
          "glue:CreateDatabase",
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:UpdateDatabase",
          "glue:CreateTable",
          "glue:GetTable",
          "glue:GetTables",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:GetPartitions",
          "glue:BatchCreatePartition",
          "glue:GetTags",
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*",
        ]
      },
      {
        # Athena: manage the production workgroup + run the provisioning DDL queries. Scoped to the
        # one workgroup ARN.
        Sid    = "AthenaWorkgroupManage"
        Effect = "Allow"
        Action = [
          "athena:CreateWorkGroup",
          "athena:GetWorkGroup",
          "athena:UpdateWorkGroup",
          "athena:TagResource",
          "athena:UntagResource",
          "athena:ListTagsForResource",
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
        ]
        Resource = ["arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${aws_athena_workgroup.production.name}"]
      },
      {
        # Query status/list actions do not support workgroup-level resource constraints in IAM.
        Sid    = "AthenaQueryStatus"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:ListWorkGroups",
        ]
        Resource = "*"
      },
      {
        # S3 bucket configuration terraform manages (versioning, encryption, public-access-block,
        # policy, tagging) -- read + write variants. CreateBucket included for greenfield provisioning.
        Sid    = "DataLakeBucketManage"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetBucketAcl",
          "s3:GetBucketVersioning",
          "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:GetBucketTagging",
          "s3:PutBucketTagging",
          "s3:GetBucketOwnershipControls",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
        ]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        # S3 object IO: Iceberg table data + Athena query results + the terraform state object (all
        # under this one bucket). Multipart actions cover large Athena result writes.
        Sid    = "DataLakeObjectIO"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        # DynamoDB: manage the counters TABLE only, scoped to the single table. NOT item-level
        # (GetItem/PutItem/UpdateItem) -- counter VALUES are PlatformDev runtime's domain and the seed
        # items are no longer Terraform-managed. The Describe* reads (continuous-backups/TTL/SSE) are
        # refresh-time reads the provider issues on aws_dynamodb_table every plan; omitting any one
        # breaks `terraform plan` (and therefore CD) even though apply succeeds.
        Sid    = "DynamoDBCountersTable"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:DescribeTable",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTable",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
          "dynamodb:ListTagsOfResource",
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# PlatformDuckLakeCatalogProvisioning -- RDS + EC2-networking rights required to provision and
# manage the DuckLake catalog (T2.16 / CD.31 / Decision 78). AdminOps grants iam:*/lambda/secrets
# but NOT rds:*/ec2:*; this policy fills that gap, enumerated and scoped per the same idiom as
# platform_admin_datalake.
#
# Scope-shape rationale:
#   - RDS resource-level scoping is supported for the named instance + subnet group ARN. The
#     "snapshot:*" wildcard covers RDS-managed automated snapshots (PITR) and any future
#     migration-cutover manual snapshots; resource ARNs for those are unstable.
#   - RDS Describe* actions DO NOT support resource-level scoping (account-wide describe APIs).
#   - EC2 Describe* (Vpcs/Subnets/SecurityGroups/...) likewise do not support resource-level scoping.
#   - EC2 security-group-mutating actions are scoped to "*" because CreateSecurityGroup has no
#     pre-existing SG ARN, and the apply-time SG is the only one this role will ever touch in this
#     account anyway (the work-account SCPs that motivated narrower scoping do not apply here per
#     terraform/CLAUDE.md). CreateTags / DeleteTags are unscoped for the same reason.
#
# IMPORT NOT REQUIRED -- this is a NEW inline policy on the already-imported PlatformAdmin role.
#
# IMPORTANT: This policy must be APPLIED via `platform_breakglass` BEFORE the dependent RDS apply
# under agent_platform_admin (Decision 35 IAM-precedence rule, terraform/CLAUDE.md "IAM precedence":
# IAM changes precede any apply that depends on them).
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "platform_admin_ducklake_catalog" {
  name = "PlatformDuckLakeCatalogProvisioning"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # RDS refresh-time + creation reads. None of these support resource-level scoping.
        Sid    = "RDSDescribe"
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
        # RDS lifecycle on the named instance + subnet group + parameter group. Includes snapshot
        # lifecycle so the destroy path (eventual T2.17/T2.19 cutover) can clean up automated
        # snapshots and create the final snapshot (skip_final_snapshot=false).
        Sid    = "RDSDuckLakeCatalogManage"
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance",
          "rds:ModifyDBInstance",
          "rds:RebootDBInstance",
          "rds:StartDBInstance",
          "rds:StopDBInstance",
          "rds:DeleteDBInstance",
          "rds:CreateDBSubnetGroup",
          "rds:ModifyDBSubnetGroup",
          "rds:DeleteDBSubnetGroup",
          "rds:CreateDBParameterGroup",
          "rds:ModifyDBParameterGroup",
          "rds:DeleteDBParameterGroup",
          "rds:CreateDBSnapshot",
          "rds:DeleteDBSnapshot",
          "rds:CopyDBSnapshot",
          "rds:AddTagsToResource",
          "rds:RemoveTagsFromResource",
        ]
        Resource = [
          "arn:aws:rds:${var.aws_region}:${var.account_id}:db:ducklake-catalog",
          "arn:aws:rds:${var.aws_region}:${var.account_id}:subgrp:ducklake-catalog",
          "arn:aws:rds:${var.aws_region}:${var.account_id}:pg:ducklake-catalog-pg16",
          "arn:aws:rds:${var.aws_region}:${var.account_id}:snapshot:*",
        ]
      },
      {
        # EC2 networking describes. data.aws_vpc / data.aws_subnets / aws_security_group all call
        # these on every plan; DescribeAvailabilityZones is required for RDS multi-AZ readiness
        # checks (a refresh-time read even when multi_az = false). DescribeVpcAttribute is a
        # refresh-time read aws_vpc data source issues per VPC (enableDnsHostnames, etc.) -- AWS
        # provider v5.100 mirrors the pattern noted for glue:GetTags in platform_admin_datalake.
        Sid    = "EC2NetworkingDescribe"
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
        # EC2 security-group lifecycle. Resource-level scoping doesn't help on CreateSecurityGroup
        # (no pre-existing ARN) and CreateTags is multi-resource by nature. The DuckLake catalog SG
        # is the only SG this role will provision in this module.
        Sid    = "EC2SecurityGroupManage"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
          "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
          "ec2:ModifySecurityGroupRules",
          "ec2:CreateTags",
          "ec2:DeleteTags",
        ]
        Resource = "*"
      },
      {
        # Secrets Manager TagResource is required for manage_master_user_password = true at
        # CreateDBInstance time (RDS tags the auto-created secret on behalf of the caller).
        # CreateSecret/Get/Put/Describe are already covered by AdminOps; TagResource is the gap.
        Sid      = "SecretsManagerTagForRDS"
        Effect   = "Allow"
        Action   = ["secretsmanager:TagResource"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:rds!*"
      },
      {
        # KMS metadata ops -- DescribeKey/CreateGrant are called DIRECTLY by the RDS provider at
        # plan + create time to validate the AWS-managed keys aws/rds (storage encryption) and
        # aws/secretsmanager (managed master-user secret). The kms:ViaService condition CANNOT be
        # applied here because these calls don't go through a service principal. Resource-level
        # scoping to specific key ARNs would require ARN-pinning the per-account key UUIDs (drifty);
        # widening to "*" is acceptable because (a) AdminOps already has iam:*, so KMS metadata is
        # not a blast-radius expansion, and (b) these are read/grant ops on AWS-managed keys.
        Sid    = "KMSMetadataForRDS"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
          "kms:CreateGrant",
        ]
        Resource = "*"
      },
      {
        # KMS data-plane ops -- gated by kms:ViaService so encrypt/decrypt/data-key calls are only
        # permitted when initiated by the rds or secretsmanager service in this region. This is the
        # AWS-recommended scoping pattern for default-key access (key-policy + IAM-condition
        # double gate).
        Sid    = "KMSDataPlaneForRDSSecrets"
        Effect = "Allow"
        Action = [
          "kms:GenerateDataKey",
          "kms:Decrypt",
          "kms:Encrypt",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = [
              "rds.${var.aws_region}.amazonaws.com",
              "secretsmanager.${var.aws_region}.amazonaws.com",
            ]
          }
        }
      },
    ]
  })
}
