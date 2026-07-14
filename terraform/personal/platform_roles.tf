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
      {
        # T2.19 recs cutover: the ops portal runs as PlatformDev at RUNTIME and reaches the closed
        # DuckLake boundary by SigV4-invoking the writer/reader AWS_IAM Function URLs (file_rec /
        # update_rec -> writer; recs reads -> reader). Without this grant every post-cutover recs op
        # fails 403 AccessDenied at the Function-URL auth layer. Scoped to the two function ARNs.
        #
        # ACTION: lambda:InvokeFunction is the action the Function-URL IAM authorizer actually checks.
        # Verified live 2026-06-09: InvokeFunction alone, scoped to these ARNs, authorizes the URL invoke
        # (stable past propagation), while lambda:InvokeFunctionUrl alone is INSUFFICIENT -- reproducible
        # 403 over 3 min, even at Resource:"*" and even with a resource-based aws_lambda_permission added.
        # PlatformAdmin works only because its AdminOps lambda statement (below) includes InvokeFunction.
        # The IAM policy simulator reports InvokeFunctionUrl as "allowed" but the live URL denies it -- do
        # not trust the simulator for Function-URL authorization. InvokeFunctionUrl is retained alongside
        # InvokeFunction for AWS-doc alignment / forward-compat (harmless, not sufficient on its own; this
        # matches the two-action grant in lambda_tooling_iam.tf). Maintenance ops stay break-glass on PlatformAdmin.
        Sid    = "DuckLakeInvokeRuntime"
        Effect = "Allow"
        Action = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"]
        # Scoped to writer + reader, both the unqualified ARN and the :* qualified form (the URLs are on
        # $LATEST/unqualified; the :* form covers any future qualifier/alias). Verified live with this
        # exact 4-ARN scoping.
        Resource = [
          aws_lambda_function.ducklake_writer.arn,
          "${aws_lambda_function.ducklake_writer.arn}:*",
          aws_lambda_function.ducklake_reader.arn,
          "${aws_lambda_function.ducklake_reader.arn}:*",
        ]
      },
      {
        # DuckLake endpoint-discovery: SSM GetParameter on the /agent-platform/ducklake/* path so
        # the runtime client can resolve the Function URLs without an env var or terraform binary.
        # Decision 81 (endpoint-discovery only -- not a data-plane expansion; write/read transit the
        # InvokeFunction grant above). MANUAL admin-apply required (IAM change, Decision 77 guard).
        Sid    = "DuckLakeEndpointDiscovery"
        Effect = "Allow"
        Action = ["ssm:GetParameter"]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/ducklake/*",
        ]
      },
      {
        # Inference-credential read for CD.28 T0.4: the PlatformDev runtime (smoke-test CLI,
        # future T4.2 LiteLLM transport) fetches the DeepSeek and Anthropic API keys via
        # get_secret_value. Scoped to exactly the two inference-credential secret ARNs defined
        # in inference_credentials.tf -- no wildcard (least-privilege per the IAM grant pattern
        # established by DuckLakeEndpointDiscovery and DuckLakeInvokeRuntime above).
        # MANUAL admin-apply required (IAM change, Decision 77 guard fail-closes). # pragma: allowlist secret
        Sid    = "InferenceCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.deepseek_api_key.arn,
          aws_secretsmanager_secret.anthropic_api_key.arn,
        ]
      },
      {
        # Broker-credential read for T2.14 / credential-routing contract: the PlatformDev runtime
        # resolves Alpaca paper + live API keys via scripts/broker_secrets.py::resolve(), which
        # calls GetSecretValue on the secret_name returned by the routing-key lookup.
        # ARN-scoped to exactly the two broker secret ARNs (no wildcard) -- mirrors InferenceCredentialsRead.
        # MANUAL admin-apply required (IAM change, Decision 77 guard fail-closes). # pragma: allowlist secret
        Sid    = "BrokerCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.alpaca_paper.arn,
          aws_secretsmanager_secret.alpaca_live.arn,
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
        # Full create+manage lifecycle so AdminOps can provision NEW Lambda infrastructure from
        # terraform/personal (T2.17 ducklake_writer/reader are the first Lambdas created via this
        # module): function + layer-version + function-URL create/read/update/delete + tagging. The
        # prior set was deploy-only (UpdateFunctionCode/Invoke/Get) and could not create functions,
        # publish layer versions, or create Function URLs.
        Sid    = "LambdaAdminManagement"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:GetRuntimeManagementConfig",
          "lambda:GetPolicy",
          # Resource-based-policy lifecycle: T2.18 ducklake_maintenance is the first module Lambda
          # invoked by EventBridge, which requires an AddPermission grant for principal
          # events.amazonaws.com. T2.17 writer/reader used Function URLs (AWS_IAM) only, so the
          # resource-policy actions were never needed. GetPolicy (above) was already present.
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:ListFunctions",
          "lambda:ListVersionsByFunction",
          "lambda:InvokeFunction",
          "lambda:InvokeFunctionUrl",
          "lambda:CreateFunctionUrlConfig",
          "lambda:GetFunctionUrlConfig",
          "lambda:UpdateFunctionUrlConfig",
          "lambda:DeleteFunctionUrlConfig",
          "lambda:PublishLayerVersion",
          "lambda:GetLayerVersion",
          "lambda:DeleteLayerVersion",
          "lambda:ListLayerVersions",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags",
          # Reserved-concurrency lifecycle: T2.18 ducklake_maintenance is the first Lambda in this
          # module to pin reserved_concurrent_executions (singleton, Decision 81 clause 6). The
          # prior set (T2.17 writer/reader) set no concurrency, so these were never needed.
          "lambda:PutFunctionConcurrency",
          "lambda:DeleteFunctionConcurrency",
          "lambda:GetFunctionConcurrency",
        ]
        Resource = "*"
      },
      {
        # EventBridge schedule-rule lifecycle: T2.18 ducklake_maintenance is the first module
        # resource to use EventBridge (two scheduled cadences: daily merge + weekly GC). Scoped to
        # the agent-platform rule namespace. PutRule with inline tags requires events:TagResource.
        Sid    = "EventBridgeScheduleManagement"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:TagResource",
          "events:UntagResource",
          "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-*"
      },
      {
        # CloudWatch metric-alarm lifecycle: T2.18 ducklake_maintenance is the first module resource
        # to create an alarm (the circuit-breaker alarm on the DuckLakeMaintenance namespace).
        # PutMetricAlarm/DeleteAlarms support alarm-ARN scoping; DescribeAlarms is a list op that
        # does not support resource scoping, so it sits on "*".
        Sid    = "CloudWatchAlarmManagement"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
          "cloudwatch:ListTagsForResource",
        ]
        Resource = "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:*"
      },
      {
        Sid      = "CloudWatchAlarmDescribe"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarms"]
        Resource = "*"
      },
      {
        # CloudWatch Logs lifecycle for the Lambda log groups this module creates
        # (/aws/lambda/agent-platform-*). DescribeLogGroups does not support resource scoping (it is
        # a list operation), so it sits on "*"; the mutating actions are scoped to the agent-platform
        # Lambda log-group prefix.
        Sid    = "LambdaLogGroupManagement"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
          "logs:ListTagsLogGroup",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*"
      },
      {
        Sid      = "LambdaLogGroupDescribe"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
      {
        # Read access to the Lambda log groups + their streams so AdminOps can diagnose runtime
        # failures (post-deploy smoke-gate RCA) without escalating to break-glass.
        Sid    = "LambdaLogGroupRead"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*",
          "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*:log-stream:*",
        ]
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
      {
        # Service Quotas: raise the account Lambda concurrent-executions ceiling so
        # ducklake_maintenance can reserve 1 (singleton, Decision 81 clause 6) without breaching
        # AWS's 10-unreserved floor. The unverified-account default (10) leaves no room to reserve.
        # Service Quotas actions do not support resource-level scoping, so they sit on "*"; read
        # actions are needed to confirm the new value applied before re-running PutFunctionConcurrency.
        Sid    = "ServiceQuotasManagement"
        Effect = "Allow"
        Action = [
          "servicequotas:GetServiceQuota",
          "servicequotas:GetAWSDefaultServiceQuota",
          "servicequotas:ListServiceQuotas",
          "servicequotas:RequestServiceQuotaIncrease",
          "servicequotas:GetRequestedServiceQuotaChange",
          "servicequotas:ListRequestedServiceQuotaChangeHistory",
          "servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota",
        ]
        Resource = "*"
      },
      {
        # SSM Parameter Store lifecycle for the DuckLake endpoint-discovery parameters
        # (/agent-platform/ducklake/{reader,writer}_url, T2.19 / Decision 81 cl.7). PlatformDev reads
        # them at runtime (DuckLakeEndpointDiscovery, below); AdminOps must create + tag + manage them
        # at apply time. PutParameter with inline tags requires ssm:AddTagsToResource; the read actions
        # back the AWS provider's plan-time GetParameter + ListTagsForResource refresh. Scoped to the
        # agent-platform parameter namespace -- all listed actions support parameter-ARN scoping.
        Sid    = "SSMParameterProvisioning"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"
      },
      {
        # ssm:DescribeParameters is the list/metadata API the AWS provider issues during the
        # aws_ssm_parameter create read-back and on every plan-time refresh. Like other AWS list
        # operations (see LambdaLogGroupDescribe / CloudWatchAlarmDescribe above) it does NOT support
        # resource-level scoping, so it must sit on "*". Without it, PutParameter succeeds but the
        # provider's read-back fails with AccessDenied on ssm:DescribeParameters.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
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
          "glue:TagResource",
          "glue:UntagResource",
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
          # T2.43 gap: aws_s3_bucket_notification.data_lake_prod_triggers is provisioned by
          # PlatformAdmin directly (admin-apply), so the admin role itself needs the write action
          # too, not just the CI roles' refresh-read grant.
          "s3:GetBucketNotification",
          "s3:PutBucketNotification",
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
      {
        # T2.18 FP-B: provision the dedicated catalog-DR bucket (versioning, SSE, public-access-block,
        # lifecycle, tagging). Scoped to the DR bucket ARN ONLY -- object IO is the DR Lambda role's
        # domain, not the provisioning role's. Mirrors DataLakeBucketManage for the new bucket.
        Sid    = "CatalogDrBucketManage"
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
          "s3:GetLifecycleConfiguration",
          "s3:PutLifecycleConfiguration",
          "s3:GetBucketOwnershipControls",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
        ]
        Resource = ["arn:aws:s3:::agent-platform-ducklake-catalog-dr"]
      },
      {
        # T2.18 FP-B: read DR dump objects (smoke-gate head_object verification + restore-drill
        # readback). Object-level read on the DR bucket only; the DR Lambda's own role writes them.
        Sid    = "CatalogDrObjectRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectTagging",
          "s3:GetObjectVersion",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr",
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr/*",
        ]
      },
      {
        # T2.18 FP-B: manage the shared SNS alerts topic + its email subscription (Decision 39).
        # Scoped to the alerts topic ARN and its subscription ARNs. The provisioning role creates
        # and configures the topic; alarms publish to it at runtime (no publish grant needed here).
        Sid    = "AlertsTopicManage"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:GetSubscriptionAttributes",
          "sns:SetSubscriptionAttributes",
          "sns:ListSubscriptionsByTopic",
        ]
        Resource = [
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts",
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts:*",
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Bootstrap state backend (PLAN-terraform-cicd-bootstrap-root / T2.23): PlatformAdmin provisions and
# uses the terraform/bootstrap root's S3 state backend. The bucket (agent-platform-bootstrap-tfstate)
# is created out-of-band by the documented runbook (terraform/bootstrap/CLAUDE.md) and is NOT a
# Terraform resource in any root -- codifying it would be circular (the bootstrap root's own state
# lives in it). This is the admin provisioning path; it does NOT weaken the bootstrap isolation, which
# fences the github_ci_apply CI role (the pipeline) out of bootstrap state. PlatformAdmin is the admin
# tier. Scoped to the one bucket; no provider refresh-read set (the bucket is not Terraform-managed).
# Provenance: applied out-of-band under agent_platform_admin (terraform -target) during the T2.23
# bootstrap provisioning ahead of this PR's merge; the merge-time CD apply reconciles it to a no-op.
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy" "platform_admin_bootstrap_state" {
  name = "BootstrapStateProvisioning"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # One-time CLI provisioning (CreateBucket + versioning/SSE/public-access-block) and the
        # backend's bucket-level reads (ListBucket for state discovery). Get* variants cover
        # idempotent re-runs + post-provision verification. Scoped to the bootstrap bucket ARN only.
        Sid    = "BootstrapStateBucketManage"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:PutBucketVersioning",
          "s3:GetBucketVersioning",
          "s3:PutEncryptionConfiguration",
          "s3:GetEncryptionConfiguration",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPublicAccessBlock",
        ]
        Resource = ["arn:aws:s3:::agent-platform-bootstrap-tfstate"]
      },
      {
        # Terraform S3 backend object IO: the state object + the use_lockfile=true native lock object
        # (terraform.tfstate.tflock). Get/Put/Delete cover read, write, and lock acquire/release.
        # Scoped to objects under the bootstrap bucket only.
        Sid    = "BootstrapStateObjectIO"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = ["arn:aws:s3:::agent-platform-bootstrap-tfstate/*"]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# DuckLake break-glass (CD.33 O-1 / Decision 81): an EXPLICIT, auditable PlatformAdmin grant to
# attach the DuckLake catalog read-only for inspect/repair -- the Neon DSN secret + S3 read on the
# ducklake-* data prefixes. AdminOps (secretsmanager GetSecretValue *) and PlatformDataLakeProvisioning
# (s3 GetObject on the bucket) already cover these capabilities broadly; this dedicated, narrowly-scoped
# policy is the NAMED surface the catalog-operations runbook (Section 1) points to so the break-glass
# read is auditable rather than implicit. See docs/runbooks/ducklake-catalog-operations.md.
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy" "platform_admin_ducklake_breakglass" {
  name = "DuckLakeBreakGlass"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "NeonCatalogDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        # Read the DuckLake Parquet data files for catalog inspect/repair (smoke + future ops prefixes).
        Sid      = "DuckLakeDataRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/ducklake-*"]
      },
      {
        Sid      = "DuckLakeDataList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["ducklake-*"]
          }
        }
      },
    ]
  })
}
