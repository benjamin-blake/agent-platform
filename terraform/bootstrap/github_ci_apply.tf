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

# rec-2793 (DEP-01 anti-recurrence): hoisted out of the aws_iam_role_policy resource's inline
# `policy = jsonencode({...})` attribute so the lifecycle precondition below can self-reference
# the rendered JSON (a precondition cannot reference `self` -- that is postcondition-only).
locals {
  github_ci_apply_policy_json = jsonencode({
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
        # P0-5 (gap sweep): terraform/personal manages the two buckets' CONFIGURATION through six
        # aws_s3_bucket_* resource types (versioning, server_side_encryption_configuration,
        # public_access_block, lifecycle_configuration, policy, notification) plus aws_s3_bucket
        # itself, and the apply role held only the matching refresh READS (DataLakeBucketManage, now
        # in the reads policy) -- every one of these Put verbs AccessDenies today. The write set
        # mirrors, verb for verb, the empirically-validated PlatformAdmin DataLakeBucketManage /
        # CatalogDrBucketManage grants in terraform/personal/platform_roles.tf, which is the identity
        # that has actually applied this module. s3:PutBucketTagging is required because the
        # provider's default_tags block (terraform/personal/main.tf) forces a tag-on-create call on
        # every taggable resource -- the same structural coupling that caused rec-2842 for TagRole.
        # P2 additions: s3:DeleteBucketPolicy (aws_s3_bucket_policy destroy/replace symmetry -- the
        # provider deletes then re-puts on a policy change) and s3:CreateBucket (bucket re-create on
        # a greenfield or replaced bucket). s3:DeleteBucket is DENIED BY DESIGN and stays admin-tier:
        # this bucket holds tfstate, the saved tfplan artifacts AND the convergence record, so a
        # CD-executable bucket delete would let one approved apply destroy the platform's own
        # integrity anchor (recorded in docs/contracts/iam-simulate-fixture.yaml). Scoped to the two
        # literal bucket ARNs -- the same Resource list the read Sid carries (never s3:* on "*").
        Sid    = "DataLakeBucketConfigWrite"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:PutBucketVersioning",
          "s3:PutEncryptionConfiguration",
          "s3:PutBucketPublicAccessBlock",
          "s3:PutLifecycleConfiguration",
          "s3:PutBucketPolicy",
          "s3:DeleteBucketPolicy",
          "s3:PutBucketNotification",
          "s3:PutBucketTagging"
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
        # P2 destroy symmetry (gap sweep): the provider's aws_athena_workgroup destroy calls
        # athena:DeleteWorkGroup, which the AthenaWorkgroup Sid above never granted -- a guard-gated
        # workgroup retirement AccessDenies AFTER human approval. Deliberately a SEPARATE narrow Sid
        # rather than another action in AthenaWorkgroup: that Sid's Resource is "*" (its refresh reads
        # genuinely need it), so folding the delete verb in would grant deletion of ANY workgroup in
        # the account, including `primary`. Narrowing AthenaWorkgroup's own "*" is a pre-existing
        # Decision 143 candidate this plan deliberately does not touch (filed as a follow-on rec).
        Sid      = "AthenaWorkgroupDelete"
        Effect   = "Allow"
        Action   = ["athena:DeleteWorkGroup"]
        Resource = ["arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/agent-platform-production"]
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
          # P2 destroy symmetry (gap sweep): the provider's aws_glue_catalog_database destroy calls
          # glue:DeleteDatabase. CreateDatabase/UpdateDatabase were granted without their delete
          # counterpart, so a guard-gated database retirement AccessDenies AFTER human approval --
          # the same create-without-destroy asymmetry as the rec-2882 class. Scoped to the existing
          # enumerated database ARN (no widening).
          "glue:DeleteDatabase",
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
          # P2 destroy symmetry (gap sweep): the provider's aws_dynamodb_table destroy calls
          # dynamodb:DeleteTable. CreateTable was granted without it, so a guard-gated counters-table
          # retirement AccessDenies AFTER human approval. Scoped to the existing enumerated table ARN.
          "dynamodb:DeleteTable",
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
        # TRUST-ONLY (Decision 143, unchanged by DEP-02 / rec-2842): iam:UpdateAssumeRolePolicy on
        # the two enumerated branch/pr roles ONLY -- the Resource is deliberately NOT widened to
        # role/agent-platform-*. A widened trust Resource would silently grant a fleet-wide trust
        # rewrite (any agent-platform-* role's trust policy), and DEP-05 (a dedicated trust-boundary
        # control) is still open, so this narrow identity grant is the ONLY control against that. The
        # non-trust role metadata/lifecycle verbs that used to share this Sid (TagRole/UntagRole) are
        # split OUT into the prefix-scoped IAMRoleMetadataWrite Sid below -- they are non-escalating
        # role-metadata writes, not trust, so they get the wider agent-platform-* prefix while trust
        # stays fleet-narrow at exactly these two roles.
        Sid    = "IAMRoleReconcile"
        Effect = "Allow"
        Action = [
          "iam:UpdateAssumeRolePolicy"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
        ]
      },
      {
        # DEP-02 (Decision 144, rec-2842): prefix-scoped role metadata/lifecycle risk-class Sid, at
        # the SAME role/agent-platform-* prefix as IAMRoleCreateBounded's iam:CreateRole below (Fable
        # best-practice consult: verb-FAMILY-wildcards-under-boundary -- the identity policy's
        # granularity unit is per-risk-class, not per-verb; Decision 144). TagRole/UntagRole moved
        # here from the (now trust-only) IAMRoleReconcile Sid above: the AWS provider's default_tags
        # block (terraform/personal/main.tf) forces a TagRole call on EVERY taggable resource's
        # create, so iam:CreateRole@role/agent-platform-* structurally REQUIRES iam:TagRole at the
        # SAME prefix, or every new agent-platform-* role's create AccessDenies -- the exact rec-2842
        # recurrence (run 30126122217; the first role ever minted through the gated path). UntagRole
        # covers tag-drift reconcile. UpdateRoleDescription is folded in from the retired
        # IAMRoleDescriptionWrite Sid (DEP-01 / rec-2757) -- same risk class, same prefix, no reason
        # to keep it a separate Sid. UpdateRole is added proactively (Fable's predicted next gap): it
        # covers max_session_duration edits, which AccessDeny at both the identity and boundary layers
        # today with no covering grant. None of these four verbs is trust, inline-policy, or
        # boundary-modifying -- they carry no escalation risk equivalent to IAMRoleReconcile's trust
        # verb, so the prefix-scoped grant is safe (Decision 143: only worst-verb-scoped verbs like
        # iam:UpdateAssumeRolePolicy / iam:PassRole / the boundary-edit verbs stay individually narrow).
        Sid    = "IAMRoleMetadataWrite"
        Effect = "Allow"
        Action = [
          "iam:TagRole",
          "iam:UntagRole",
          "iam:UpdateRole",
          "iam:UpdateRoleDescription"
        ]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-*"]
      },
      {
        # In-budget CreateRole: the pipeline may only create roles that carry the authority budget
        # (T2.23 EC4). iam:PermissionsBoundary propagation condition forces the budget ARN to be
        # specified on every role the pipeline creates. An unbounded role-create is implicitly denied
        # -- no unconditional Allow for iam:CreateRole exists in this policy. DEP-02 / Decision 144:
        # Resource narrowed from role/* to role/agent-platform-* (the pipeline mints only
        # boundary-carrying agent-platform-* roles; PlatformDev/PlatformAdmin are admin-created).
        Sid      = "IAMRoleCreateBounded"
        Effect   = "Allow"
        Action   = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-*"]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        # In-budget PutRolePolicy/AttachRolePolicy. DEP-02 / Decision 144: Resource widened from the
        # two enumerated CI roles (branch + pr) to the boundary-carrying agent-platform-* prefix,
        # extending Decision 129's per-service agent-platform-* read prefix to writes. The apply role's
        # own ARN -- which the widened prefix now matches -- is carved out by the explicit
        # DenySelfInlinePolicyWrite Deny below (retains the T2.23 self-grant break). Condition: target
        # role must carry the authority budget (propagation). The machine-readable mirror of the
        # managed-role prefix + resource types + actions lives in terraform/bootstrap/authority_budget.json
        # v2 (Decision 92 point 5). The guard (scripts/terraform_apply_guard.py) reads that table and
        # auto-applies in-budget inline-policy / attachment CREATE+UPDATE on managed boundary-carrying
        # agent-platform-* roles (self-excluding the apply role); role CREATES, trust diffs, destroys,
        # and out-of-budget changes still route to the gated-apply Environment. Defense-in-depth at the
        # IAM layer (T2.23 EC4).
        Sid    = "IAMRoleWriteBounded"
        Effect = "Allow"
        Action = [
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy",
          "iam:PutRolePermissionsBoundary"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/agent-platform-*",
        ]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        # HAZARD-4 (Fable, load-bearing for slice F): apply-phase iam:DeleteRole / DetachRolePolicy /
        # DeleteRolePolicy on agent-platform-* roles so slice F's guard-gated role RETIREMENTS execute
        # (not AccessDeny) after human approval. Destroys still ROUTE to gated-apply (the guard is
        # unchanged and always gates a delete); this only gives the apply role the VERB. The apply
        # role's own ARN is carved out of DeleteRolePolicy/DetachRolePolicy by DenySelfInlinePolicyWrite
        # below (self-DoS break). Scoped to role/agent-platform-*; the boundary DataPlaneAllow is
        # extended with these three iam verbs (a grant absent from the ceiling is silently denied).
        Sid    = "IAMRoleDeleteBounded"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:DetachRolePolicy",
          "iam:DeleteRolePolicy",
          # rec-2882 (P0-1, the THIRD instance of the headline-verb-granted / companion-verb-missing
          # class; it killed the live gated destroy in run 30264239445 and left the sandbox
          # convergence record red at 99eb274): the AWS provider's resourceAwsIamRoleDelete
          # unconditionally calls deleteRoleInstanceProfiles() BEFORE DeleteRole, and that helper
          # calls iam:ListInstanceProfilesForRole and then iam:RemoveRoleFromInstanceProfile for each
          # profile returned. Neither is optional and neither depends on the role actually having an
          # instance profile -- the List call happens unconditionally -- so iam:DeleteRole without
          # these two is structurally unusable. RemoveRoleFromInstanceProfile is granted alongside
          # the List verb deliberately: it is the second call in the SAME provider loop, and leaving
          # a known companion ungranted is exactly the patch-one-verb-per-production-failure pattern
          # this change exists to end. Both verbs are also added to the boundary DataPlaneAllow
          # ceiling below -- a grant absent from the ceiling is silently denied by the intersection.
          "iam:ListInstanceProfilesForRole",
          "iam:RemoveRoleFromInstanceProfile"
        ]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-*"]
      },
      {
        # rec-2831 (DEP-01 completion, T2.48 c1, PLAN-t248-passrole-liveproof): AWS REQUIRES
        # iam:PassRole on a Lambda's execution role for lambda:CreateFunction to succeed --
        # LambdaFunctionWrite below grants CreateFunction but the enumerated model never paired it
        # with PassRole, so a new agent-platform-* Lambda auto-applies past the guard and then
        # AccessDenies at CreateFunction (the exact recurrence this Sid closes). Worst-verb scoped
        # (Decision 143): Resource is the execution-role prefix role/agent-platform-* (never role/*
        # or PlatformAdmin/PlatformDev), AND Condition requires iam:PassedToService=lambda.amazonaws.com
        # (this identity may pass an agent-platform-* role ONLY to the lambda service, never to ecs,
        # glue, or any other principal). Passing a PRIVILEGED agent-platform-* role (e.g. this apply
        # role itself, or the planner role) to lambda is ALLOWED by this prefix grant BY DESIGN
        # (Decision 143) -- containment is that the apply role holds no broad lambda:InvokeFunction,
        # so it cannot create-then-invoke such a lambda to escalate in-session (verified via the
        # bootstrap simulate-principal-policy gate). The boundary DataPlaneAllow ceiling is extended
        # with the same verb below (a grant absent from the ceiling is silently denied).
        Sid      = "IAMPassRoleForLambda"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-*"]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "lambda.amazonaws.com"
          }
        }
      },
      {
        # T2.23 self-grant break, retained under the widened agent-platform-* prefix (audit Q7). The
        # widened role/agent-platform-* write grants above MATCH the apply role's own ARN
        # (agent-platform-github-ci-apply), so this explicit Deny carves that ARN out of the
        # inline-policy write + attach + boundary-set actions (escalation break) AND -- carry M1 --
        # DeleteRolePolicy/DetachRolePolicy on self (self-DoS break). Explicit Deny in the identity
        # policy overrides the Allow. DeleteRole-on-self is intentionally NOT listed: deleting the apply
        # role is self-destruction (fail-safe, admin-recoverable, and guard-gated), not an escalation.
        # This is the identity-side counterpart to the guard's apply-role self-exclusion
        # (scripts/terraform_apply_guard.py _classify_iam_change) -- two independent layers.
        Sid    = "DenySelfInlinePolicyWrite"
        Effect = "Deny"
        Action = [
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy",
          "iam:PutRolePermissionsBoundary",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy"
        ]
        Resource = ["arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply"]
      },
      {
        # P1-4 (gap sweep): iam:TagOpenIDConnectProvider was granted with no Untag counterpart, so a
        # tag-drift reconcile on aws_iam_openid_connect_provider (default_tags removes a tag -> the
        # provider calls iam:UntagOpenIDConnectProvider) AccessDenies. Non-escalating tag metadata at
        # the same single enumerated provider ARN; also added to the boundary DataPlaneAllow ceiling
        # below, since a grant absent from the ceiling is silently denied by the intersection. The
        # three OIDC-provider LIFECYCLE verbs (Create/Delete/RemoveClientIDFrom) stay DENIED BY DESIGN
        # and admin-tier -- destroying or replacing the provider breaks the very pipeline executing
        # the apply (recorded in docs/contracts/iam-simulate-fixture.yaml).
        Sid    = "OIDCProviderReconcile"
        Effect = "Allow"
        Action = [
          "iam:GetOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider"
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
          "secretsmanager:UntagResource",
          # P2 destroy symmetry (gap sweep): CreateSecret was granted here with no delete counterpart,
          # so a guard-gated retirement or replace of the DSN secret AccessDenies AFTER human
          # approval. DeleteSecret is recoverable by AWS design (7-30 day recovery window), so this
          # is not an irreversible-destroy grant. Same ARN, no widening.
          "secretsmanager:DeleteSecret"
        ]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:ducklake-neon-catalog-dsn-*"]
      },
      {
        # P0-6 (gap sweep), METADATA half of the deliberate two-Sid split. terraform/personal declares
        # five agent-platform-* aws_secretsmanager_secret resources and the apply role could neither
        # create, retire nor tag any of them (only the DSN secret above had a write grant), so any PR
        # adding or retiring a secret AccessDenies. These four verbs are metadata-only: NONE of them
        # can read or overwrite a secret VALUE, which is what makes the agent-platform-* prefix safe
        # here while UpdateSecret below stays enumerated. TagResource is structurally required by the
        # default_tags block (a create with inline tags calls it -- the rec-2842 coupling);
        # UntagResource covers tag-drift reconcile; DeleteSecret has AWS's 7-30 day recovery window.
        # secretsmanager:PutSecretValue is granted NOWHERE new by this change.
        Sid    = "SecretsManagerMetadataWrite"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource"
        ]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-*"]
      },
      {
        # P0-6 (gap sweep), VALUE-CAPABLE half -- ENUMERATED, NEVER PREFIXED (S2). secretsmanager:
        # UpdateSecret accepts a SecretString, so it can overwrite a credential; it has no
        # metadata-only variant and no narrowing condition key, which makes it a worst verb under
        # Decision 143 clause 1. Critically there is NO boundary intersection available to narrow it:
        # the boundary DataPlaneAllow already carries secretsmanager:*, so this identity statement is
        # the SOLE control -- a secret:agent-platform-* prefix here would be fully effective over the
        # anthropic + deepseek API keys, the GitHub PAT, BOTH Alpaca broker envelopes AND every
        # future agent-platform-* secret, with no review. It is therefore held to exactly the five
        # aws_secretsmanager_secret resources terraform/personal actually declares (the DuckLake Neon
        # DSN keeps its own SecretsManagerDuckLakeNeonDSN Sid above). A NEW secret must be added here
        # deliberately. Accepted residual: UpdateSecret can still overwrite a value on these five --
        # marginal rather than a new capability class, since SecretsManagerReadOnly already grants
        # Describe*/Get* on them -- and it is now bounded to a named, reviewable five.
        Sid    = "SecretsManagerUpdateEnumerated"
        Effect = "Allow"
        Action = ["secretsmanager:UpdateSecret"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-github-pat-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-alpaca-paper-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-alpaca-live-*",
        ]
      },
      {
        # DEP-01 (Decision 144, rec-2757): apply-phase CREATE / MODIFY / DESTROY of the agent-platform-*
        # Lambda log groups. The enumerated model lacked logs:CreateLogGroup entirely (log groups were
        # admin-created via PlatformAdmin's LambdaLogGroupManagement), so a PR adding a NEW agent-platform-*
        # Lambda + its log group AccessDenied on CreateLogGroup. Scoped to the /aws/lambda/agent-platform-*
        # log-group prefix (mirrors PlatformAdmin's LambdaLogGroupManagement). logs:* in the boundary
        # DataPlaneAllow already permits these verbs.
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy",
          "logs:TagLogGroup",
          "logs:DeleteLogGroup",
          # P0-4 (gap sweep): logs:TagLogGroup was granted with NO untag counterpart in either
          # tagging family, so a default_tags drift reconcile on any agent-platform-* log group
          # AccessDenies. CloudWatch Logs has TWO tagging families -- the legacy log-group-specific
          # TagLogGroup/UntagLogGroup and the newer resource-generic TagResource/UntagResource -- and
          # which one hashicorp/aws 5.100 calls on create could NOT be determined offline
          # (cloudtrail:LookupEvents is AccessDenied to PlatformAdmin). All four are granted
          # deliberately: that is what the empirically-validated PlatformAdmin
          # LambdaLogGroupManagement grant does (terraform/personal/platform_roles.tf), both families
          # are non-escalating at the same /aws/lambda/agent-platform-* prefix, and UntagLogGroup is
          # missing regardless of which family the provider picks. Blast radius if the provider uses
          # TagResource: EVERY new log group create -- hence every new Lambda -- fails, unexercised
          # only because no new Lambda has landed since logs:CreateLogGroup was added at DEP-01. This
          # over-grant is the concrete case for the CloudTrail observability follow-on.
          "logs:TagResource",
          "logs:UntagResource",
          "logs:UntagLogGroup"
        ]
        Resource = ["arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*"]
      },
      {
        # apply-phase MODIFY needs AddPermission on agent-platform-* functions (EventBridge / S3 grant
        # the trigger invocation right on the function resource policy at apply time). DEP-01 / Decision
        # 144: broadened from the enumerated ducklake ARNs to the account-wide function:agent-platform-*
        # prefix so a future agent-platform-* function auto-covers without a bootstrap out-of-band grant
        # edit (mirrors the LambdaRead resource-axis broadening / rec-2702 anti-recurrence).
        Sid    = "LambdaPermissionWrite"
        Effect = "Allow"
        Action = [
          "lambda:AddPermission",
          "lambda:RemovePermission"
        ]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-*",
        ]
      },
      {
        # DEP-01 (Decision 144, rec-2703): apply-phase CREATE / MODIFY / DESTROY of an agent-platform-*
        # Lambda function. The enumerated model lacked these entirely (functions were admin-created via
        # PlatformAdmin), so a PR adding a NEW agent-platform-* Lambda AccessDenied on CreateFunction.
        # The broad-but-bounded deployer now creates + configures + retires agent-platform-* functions
        # under the MANDATORY boundary. Scoped to function:agent-platform-* (covers agent-platform-*
        # AND the agent-platform-ducklake-* naming). Data-plane wildcard lambda:* in the boundary
        # DataPlaneAllow already permits these verbs (only new iam verbs need adding to the boundary).
        Sid    = "LambdaFunctionWrite"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:UpdateFunctionConfiguration",
          "lambda:DeleteFunction",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:PutFunctionConcurrency",
          "lambda:DeleteFunctionConcurrency",
          # P1-2 (gap sweep): aws_lambda_function's UPDATE path calls lambda:UpdateFunctionCode
          # whenever source_code_hash / s3_key / image_uri changes. The four DuckLake functions
          # currently ignore_changes on source_code_hash (rec-2646/2654) and deploy through the
          # governed code-deploy channel (Decision 125/126), which is the only reason this has not
          # yet AccessDenied -- any function outside that arrangement, or any lift of the
          # ignore_changes, fails at apply. Same function:agent-platform-* prefix, no widening.
          "lambda:UpdateFunctionCode",
          # P0-2 (gap sweep): aws_lambda_function_url is a terraform/personal resource type with NO
          # write grant at all -- the provider calls Create/Update/DeleteFunctionUrlConfig on the
          # FUNCTION resource ARN, so they belong on this prefix rather than a separate Sid. The
          # matching read (lambda:GetFunctionUrlConfig) is already covered by LambdaRead's
          # lambda:Get* wildcard, which is exactly why the gap was invisible until an apply hit it.
          "lambda:CreateFunctionUrlConfig",
          "lambda:UpdateFunctionUrlConfig",
          "lambda:DeleteFunctionUrlConfig"
        ]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-*",
        ]
      },
      {
        # apply-phase MODIFY needs PublishLayerVersion/DeleteLayerVersion on the three ducklake
        # layers. rec-2646/2654 decoupled the FOUR ducklake Lambda FUNCTIONS' source_code_hash from
        # terraform (lifecycle ignore_changes), but the layer resources were out of that fix's scope
        # and still compute source_code_hash live from a freshly-rebuilt local zip -- any CD run that
        # rebuilds before planning (speculative-plan, apply-the-saved-plan, workflow_dispatch) can see
        # a spurious "must be replaced" diff even with no real dependency change (rec-2755 tracks the
        # durable fix: extending the functions' ignore_changes pattern to these layer resources). This
        # grant lets the apply role actually execute that replace when the guard routes it to
        # gated-apply, instead of failing AccessDenied and requiring an admin bailout every time.
        Sid    = "LambdaLayerVersionWrite"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion",
          "lambda:DeleteLayerVersion"
        ]
        Resource = [
          # P1-3 (gap sweep): adopt agent-platform-* as the LAYER naming convention and grant it on
          # the write side too, so a new agent-platform-* layer does not need a fresh out-of-band
          # bootstrap grant edit (the rec-2702 resource-axis anti-recurrence, applied to layers). The
          # three ducklake-* literals are RETAINED -- the existing layers are named ducklake-*, not
          # agent-platform-*, so the prefix does not cover them. Deliberately NOT layer:* (Decision
          # 143 worst-verb scoping): PublishLayerVersion/DeleteLayerVersion on any layer in the
          # account is a materially wider grant than this module needs.
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:agent-platform-*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:agent-platform-*:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions:*",
        ]
      },
      {
        # apply-phase MODIFY/CREATE/DESTROY needs PutRule/PutTargets on agent-platform-* EventBridge
        # rules. DEP-01 / Decision 144: broadened from the five enumerated ducklake rule ARNs to the
        # account-wide rule/agent-platform-* prefix so a future agent-platform-* rule auto-covers
        # without a bootstrap grant edit (mirrors the EventBridgeRead resource-axis broadening).
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
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-*",
        ]
      },
      {
        # apply-phase MODIFY/CREATE/DESTROY needs PutMetricAlarm on the agent-platform alarms.
        # DEP-01 / Decision 144: broadened from the three enumerated ducklake-* alarm ARNs to the
        # agent-platform-* AND ducklake-* alarm namespaces (the current alarms are named ducklake-*,
        # NOT agent-platform-*, so BOTH prefixes are required; a future agent-platform-* alarm
        # auto-covers). cloudwatch:* in the boundary DataPlaneAllow already permits these verbs.
        Sid    = "CloudWatchAlarmsWrite"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource"
        ]
        Resource = [
          "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:agent-platform-*",
          "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:ducklake-*",
        ]
      },
      {
        # P0-3 (gap sweep): aws_sns_topic and aws_sns_topic_subscription (sns_alerts.tf) had refresh
        # READS only (SNSRead / SNSSubscriptionRead) and no write grant at all, so creating,
        # retiring, re-tagging or re-subscribing the alerts topic AccessDenies at apply. The eight
        # verbs are the write half of the empirically-validated PlatformAdmin AlertsTopicManage grant
        # (terraform/personal/platform_roles.tf) -- its four read verbs are already covered by the
        # sns:Get*/List* read closure. SetSubscriptionAttributes covers the subscription's
        # raw_message_delivery / filter-policy updates; TagResource is forced on create by the
        # default_tags block. BOTH Resource entries are required: a subscription's ARN is
        # `<topic-arn>:<subscription-uuid>`, so Subscribe/Unsubscribe/SetSubscriptionAttributes are
        # authorized against agent-platform-alerts:* while the topic verbs match the bare topic ARN.
        Sid    = "SNSTopicWrite"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:SetTopicAttributes",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:SetSubscriptionAttributes"
        ]
        Resource = [
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts",
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts:*",
        ]
      },
      {
        # P0-7 (gap sweep): RESCOPED from the old SSMFeatureFlagsManage Sid, which was pinned to
        # /agent-platform/feature-flags/* while terraform/personal now declares aws_ssm_parameter
        # resources elsewhere under /agent-platform/ (e.g. the T2.19 DuckLake endpoint-discovery
        # parameters) -- those writes AccessDeny today. The prefix is widened to the SAME
        # parameter/agent-platform/* scope the read Sid (SSMParameterRead) already carries, so read
        # and write scope stay at parity, and the Sid is renamed to match the equivalent
        # empirically-validated PlatformAdmin statement (SSMParameterProvisioning in
        # terraform/personal/platform_roles.tf). ssm:DeleteParameter closes the create/destroy
        # asymmetry: PutParameter was granted with no delete counterpart, so a parameter retirement
        # AccessDenies after human approval. The plural ssm:DeleteParameters is deliberately NOT
        # granted -- the provider uses the singular form for aws_ssm_parameter. The three read verbs
        # are retained from the pre-rescope grant (redundant with SSMParameterRead's wildcards, but
        # this statement keeps the shape of its PlatformAdmin counterpart). Still NOT ssm:* and still
        # not all parameters.
        Sid    = "SSMParameterProvisioning"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:PutParameter",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource"
        ]
        Resource = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"]
      }
    ]
  })
}


# rec-2793 / policy-architecture split (Decision NNN_PLACEHOLDER): the 11 READ-ONLY Sids below were
# MOVED verbatim out of local.github_ci_apply_policy_json into this customer-managed policy. The
# inline identity policy was at 10,156 B of the 10,240 B AWS hard limit (84 B of headroom), and the
# write-surface remediation adds ~2,384 B -- so the relocation is a PREREQUISITE for the fix, not an
# optimisation. A LimitExceeded on an inline policy is INVISIBLE to `terraform plan`; it surfaces only
# at apply. Governing principle: READS MOVE, AUTHORITY STAYS -- every iam: write Sid and BOTH Deny
# statements remain inline. Hoisted into a local so the lifecycle precondition below can
# self-reference the rendered JSON (a precondition cannot reference `self`).
locals {
  github_ci_apply_reads_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
          "s3:GetBucketOwnershipControls",
          # T2.43 gap: aws_s3_bucket_notification.data_lake_prod_triggers refresh-reads this.
          "s3:GetBucketNotification"
        ]
        Resource = [
          "arn:aws:s3:::agent-platform-data-lake",
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr",
        ]
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
        # RETIREMENT ORDERING RULE (by design -- do not "tidy" this list ahead of a destroy): when a
        # role is retired, prune its ARN from this list ONLY AFTER its destroy has actually applied.
        # The two obligations are asymmetric in time. validate_ci_refresh_read_coverage stops
        # REQUIRING the ARN the moment the resource leaves terraform/personal -- i.e. in the very PR
        # that deletes it -- but the destroy itself still issues a refresh iam:GetRole against the
        # live role before deleting it. Pruning in the same PR therefore removes the grant the
        # pending destroy needs, and the apply AccessDenies before the guard runs. Two PRs, in this
        # order: (1) delete the resource, keep the ARN here; (2) after the destroy has applied,
        # prune the ARN. The agent-platform-probe-liveproof-role entry below is a live instance of
        # exactly this ordering.
        # T2.49 / DEP-12 (Decision 144): the four retired CI roles (plan, drift, ducklake-deploy,
        # prod-deploy) are replaced by two merged roles -- planner (plan+drift) and deploy
        # (ducklake-deploy+prod-deploy) -- so this list shrinks by two entries (net -2, helps the
        # rec-2793 headroom). Same read-only refresh-grant class as the retired roles had; the
        # pipeline does not mint them (admin-provisioned in terraform/personal/oidc.tf).
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
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-planner",
          "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-deploy",
          "arn:aws:iam::${var.account_id}:role/PlatformDev",
          "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-writer",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-reader",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance",
          # T2.18 c9 split (same class as ducklake-deploy/prod-deploy above): the smoke exec role
          # must be refresh-readable, or every subsequent apply plan fails closed with AccessDenied.
          "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-maintenance-smoke",
          "arn:aws:iam::${var.account_id}:role/agent-platform-scheduled-agent-dispatcher",
          "arn:aws:iam::${var.account_id}:role/agent-platform-findings-processor",
          "arn:aws:iam::${var.account_id}:role/agent-platform-ops-compaction",
          # rec-2831 / DEP-02 (T2.48 c2, PLAN-t248-passrole-liveproof): pre-staged ahead of the
          # role's own creation, the established planner/deploy pre-add pattern (rec-2688; mirrors
          # how github-ci-drift's own ARN was added here at T2.24) -- so github_ci_apply can
          # refresh-read the throwaway DEP-02 live-proof role once its create PR lands. Added here
          # in the PassRole-completion PR; the matching oidc.tf planner-read entry is added in the
          # DEP-02 create PR and both entries are removed together in the DEP-02 revert PR.
          "arn:aws:iam::${var.account_id}:role/agent-platform-probe-liveproof-role",
        ]
      },
      {
        # Consolidated read-only Secrets Manager refresh-reads (Describe*/Get*) for every secret the
        # apply role sources at plan/apply time. Merged from five per-secret statements into one
        # (DEP-01 apply-inline-policy-size fix): the IAM inline-policy hard limit is 10,240 bytes and
        # the enumerated five pushed the rendered policy to 10,534 B (LimitExceeded at apply, invisible
        # to `terraform plan`). The grant set is UNCHANGED -- identical secretsmanager:Describe*/Get*
        # actions over the union of the same ARNs, so IAM evaluates every request identically (a
        # request is allowed iff its action is Describe*/Get* and its resource matches one ARN, in
        # both forms). Each ARN's lifecycle is human-owned / out-of-band (Decision 37); CI reads
        # these, never writes them. The writable DuckLake Neon DSN secret keeps its own statement
        # above (it is not read-only). Per-service read-wildcard closure (rec-2305) is preserved.
        #   neon-api-key-*                              : Neon provider API key (Phase 0 out-of-band).
        #   agent-platform-terraform-personal-tfvars-* : tfvars sourcing at apply time.
        #   agent-platform-deepseek/anthropic-api-key-*: inference credential envelopes (admin-applied).
        #   agent-platform-broker-*                    : Alpaca paper+live broker envelopes (T2.14).
        #   agent-platform-github-pat-*                : dispatcher/findings-processor PAT (T2.43).
        Sid    = "SecretsManagerReadOnly"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:neon-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-terraform-personal-tfvars-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-deepseek-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-anthropic-api-key-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-broker-*",
          "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:agent-platform-github-pat-*",
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
        # Resource axis (Decision 129 / T2.43 rec-2702 anti-recurrence): the function
        # ARN is broadened from four enumerated ducklake-* entries to the account-wide
        # function:agent-platform-* prefix so a future agent-platform-* Lambda auto-covers without
        # a bootstrap out-of-band grant edit.
        # P1-3 (gap sweep): the layer axis gets the SAME treatment -- layer:agent-platform-* (and its
        # :* version suffix) is added and agent-platform-* adopted as the layer naming convention,
        # with the three ducklake-* literals RETAINED because the existing layers carry those names.
        # This matters on the READ side too, not just the write side: _literal_or_prefix_match would
        # let a new layer named agent-platform-mylayer match the FUNCTION prefix
        # function:agent-platform-* and pass read coverage, so a new layer would be a SILENT read gap
        # that surfaces only as an apply-time AccessDenied. Deliberately not layer:* (Decision 143).
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:agent-platform-*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:agent-platform-*:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-pgclient:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-deps:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:ducklake-extensions:*",
          "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:agent-platform-*",
        ]
      },
      {
        # Refresh-time reads the provider issues on aws_cloudwatch_event_rule every plan.
        # Per-service read-wildcard closure: events:Describe*/List* closes the anti-pattern.
        # Resource axis (Decision 129 / T2.43 rec-2702 anti-recurrence): broadened from five
        # enumerated ducklake-* rule ARNs to the account-wide rule/agent-platform-* prefix so a
        # future agent-platform-* EventBridge rule auto-covers without a bootstrap grant edit.
        Sid    = "EventBridgeRead"
        Effect = "Allow"
        Action = ["events:Describe*", "events:List*"]
        Resource = [
          "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-*",
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

resource "aws_iam_policy" "github_ci_apply_reads" {
  name        = "agent-platform-github-ci-apply-reads"
  description = "Refresh-time read surface for the CD apply role (relocated from the inline policy; reads move, authority stays)"
  policy      = local.github_ci_apply_reads_policy_json

  lifecycle {
    precondition {
      # Managed-policy hard limit is 6,144 B (distinct from the 10,240 B inline-policy limit).
      # A LimitExceeded here is invisible to `terraform plan` and surfaces only at apply.
      condition     = length(jsonencode(jsondecode(local.github_ci_apply_reads_policy_json))) <= 6144
      error_message = "github_ci_apply reads policy exceeds the 6,144 B managed-policy limit."
    }
  }
}

resource "aws_iam_role_policy_attachment" "github_ci_apply_reads" {
  role       = aws_iam_role.github_ci_apply.name
  policy_arn = aws_iam_policy.github_ci_apply_reads.arn
}

resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "agent-platform-github-ci-apply"
  role   = aws_iam_role.github_ci_apply.id
  policy = local.github_ci_apply_policy_json

  # FORWARD-APPLY ORDERING (policy-architecture split): the reads policy and this inline policy are
  # ONE logical read surface split across two resources, and terraform has no implicit dependency
  # between them -- both target the same role, neither references the other. Without this edge a
  # forward apply is free to SHRINK the inline policy first; if the create-or-attach then fails, the
  # role holds ZERO refresh-read surface and every subsequent CD plan dies AccessDenied BEFORE the
  # guard runs, including any reconcile. With it, the worst case is the reads being granted twice
  # for one step -- an identical allow-union, harmless. The ROLLBACK direction is the mirror image
  # and is NOT expressible in HCL: restore the inline read Sids FIRST, then detach; never detach the
  # reads policy alone.
  depends_on = [aws_iam_role_policy_attachment.github_ci_apply_reads]

  lifecycle {
    precondition {
      # rec-2793 (DEP-01 anti-recurrence): AWS excludes whitespace from the 10,240 B inline-
      # policy limit, so measure the WHITESPACE-STRIPPED/minified rendering (a raw
      # whitespace-inclusive length() false-fails here: ~10,534 B raw, deploys fine minified).
      condition     = length(jsonencode(jsondecode(local.github_ci_apply_policy_json))) <= 10240
      error_message = "github_ci_apply inline policy exceeds the 10,240 B IAM inline-policy limit (whitespace-stripped measure, rec-2793). Move a statement to a customer-managed policy or trim grants."
    }
  }
}

# rec-2793 (DEP-01 anti-recurrence), extended to the boundary document: hoisted out of the
# aws_iam_policy resource's inline `policy = jsonencode({...})` attribute so the lifecycle
# precondition below can self-reference the rendered JSON (a precondition cannot reference `self` --
# that is postcondition-only).
locals {
  github_ci_apply_boundary_policy_json = jsonencode({
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
          "iam:AttachRolePolicy",
          "iam:PutRolePermissionsBoundary",
          # DEP-01 / HAZARD-4 (Decision 144): the boundary is a CEILING -- the 4 new iam verbs the
          # widened identity policy grants (IAMRoleDeleteBounded's three destroy verbs +
          # IAMRoleDescriptionWrite's UpdateRoleDescription) must ALSO be permitted here, or they are
          # silently denied by the intersection. DenyIAMEscalation below still narrows the
          # create/put/attach write actions at the call site; the destroy verbs are gated by the guard.
          "iam:DeleteRole",
          "iam:DetachRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:UpdateRoleDescription",
          # DEP-02 (Decision 144, rec-2842): the boundary ceiling for the new IAMRoleMetadataWrite
          # identity Sid above. iam:TagRole / iam:UntagRole are already ceiling-covered by the
          # pre-existing entries above (moved here unchanged from the old IAMRoleReconcile grant);
          # iam:UpdateRole is the one NEW verb this Sid adds (Fable's predicted next gap --
          # max_session_duration edits AccessDeny at both layers today with no covering grant). A
          # grant absent from the boundary ceiling is silently denied by the identity/boundary
          # intersection.
          "iam:UpdateRole",
          # rec-2831 (DEP-01 completion, T2.48 c1, PLAN-t248-passrole-liveproof): the boundary
          # ceiling for the IAMPassRoleForLambda identity grant above. The identity policy already
          # worst-verb-scopes PassRole (role/agent-platform-* + PassedToService=lambda.amazonaws.com);
          # the boundary Allow itself stays unconditioned here, matching the existing pattern for
          # every other IAM write verb in this same list (CreateRole/PutRolePolicy/AttachRolePolicy
          # are narrowed by the separate DenyIAMEscalation Deny below, not by a Condition on this
          # Allow) -- a boundary is a ceiling, not a second copy of the identity-side scoping.
          # DenyIAMEscalation / DenyBoundaryRemoval / DenyBoundaryPolicyModification below stay
          # non-intersecting with PassRole (verified live by the bootstrap simulate-gate, VP step 10).
          "iam:PassRole",
          # rec-2882 (P0-1) + P1-4: the ceiling half of the three new iam verbs the identity policy
          # grants above -- IAMRoleDeleteBounded's iam:ListInstanceProfilesForRole and
          # iam:RemoveRoleFromInstanceProfile (the provider's deleteRole() unconditionally calls
          # deleteRoleInstanceProfiles(), which issues both) and OIDCProviderReconcile's
          # iam:UntagOpenIDConnectProvider (tag-drift reconcile). A grant present in only ONE layer
          # is silently denied by the identity/boundary intersection -- that single-layer silence is
          # the failure mode this whole change exists to end, so these are added in the same edit as
          # the identity grants, never afterwards. None is escalation-relevant: the two role verbs
          # only detach a role from an instance profile (this account provisions no EC2 instance
          # profiles at all, so they are inert outside the destroy path) and the third is tag
          # metadata. Destroys still ROUTE to gated-apply -- the guard is unchanged.
          "iam:ListInstanceProfilesForRole",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:UntagOpenIDConnectProvider"
        ]
        Resource = ["*"]
      },
      {
        # Deny IAM escalation: CreateRole/PutRolePolicy/AttachRolePolicy without the authority budget.
        # StringNotEquals on iam:PermissionsBoundary: if the key is absent from the request context
        # (unbounded create/put), StringNotEquals evaluates to true -> Deny applies. Belt-and-suspenders
        # with the identity policy's conditional Allow (IAMRoleCreateBounded / IAMRoleWriteBounded).
        # SIMULATE ARTIFACT -- NOT A GAP, DO NOT "FIX" IT (recorded so a future auditor does not
        # chase a false positive): iam:simulate-principal-policy returns explicitDeny/implicitDeny
        # for iam:CreateRole / iam:PutRolePolicy / iam:AttachRolePolicy / iam:PutRolePermissionsBoundary
        # ONLY when the iam:PermissionsBoundary context entry is OMITTED from the simulate call --
        # which is precisely this statement working as designed, because an omitted key makes
        # StringNotEquals true. Supply the boundary ARN as a context entry and the same four verbs
        # come back allowed. Any "completion" of these verbs based on a context-free simulate would
        # be granting against a control that is functioning correctly.
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
        Resource = [
          "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary",
          # Policy-architecture split: the 11 relocated read Sids now live in the customer-managed
          # agent-platform-github-ci-apply-reads document. Naming it HERE is what keeps those grants
          # behind the same EXPLICIT Deny that protects the boundary document. Without this entry the
          # relocation would silently downgrade their protection in KIND -- from an explicit Deny to
          # the mere ABSENCE of an iam:CreatePolicy* grant, which any later grant edit (or a widened
          # iam verb family) could re-enable with nothing failing loudly. An explicit Deny cannot be
          # overridden by any Allow, so a version of the reads document rewritten by the pipeline
          # itself is impossible rather than merely un-granted. Literal ARN for the same reason as
          # the boundary's (no circular resource reference).
          "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-reads",
        ]
      }
    ]
  })
}

resource "aws_iam_policy" "github_ci_apply_boundary" {
  name        = "agent-platform-github-ci-apply-boundary"
  description = "Authority budget for github_ci_apply: permissive data-plane Allow + IAM escalation Deny (CD.35 Wave 4 / T2.23)."
  policy      = local.github_ci_apply_boundary_policy_json

  lifecycle {
    precondition {
      # rec-2793, applied to the boundary document: AWS excludes whitespace from the 6,144 B
      # customer-managed-policy limit (distinct from the 10,240 B inline-policy limit), so measure
      # the WHITESPACE-STRIPPED/minified rendering -- a raw whitespace-inclusive length() here
      # false-fails on the indented HCL rendering of a document that deploys fine minified. A
      # LimitExceeded is invisible to `terraform plan` and surfaces only at apply.
      condition     = length(jsonencode(jsondecode(local.github_ci_apply_boundary_policy_json))) <= 6144
      error_message = "github_ci_apply boundary policy exceeds the 6,144 B managed-policy limit (whitespace-stripped measure, rec-2793). Trim grants -- never raise the constant; it is an AWS hard limit."
    }
  }
}
