# Terraform — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

Some rules below restate root rules for proximity. Root `CLAUDE.md` is authoritative if they ever drift.

## Hard rules
- **Optional artifacts**: Always wrap `filemd5()` and `file()` calls on optional artifacts with `try()`. Bad: `source_code_hash = filemd5("build/lambda.zip")`. Good: `source_code_hash = try(filemd5("build/lambda.zip"), md5(file("module_file.tf")))`.
- **ASCII tag values**: Plain ASCII hyphens (`-`) only in Lambda tag values. No em dashes — they fail in AWS API serialisation.
- **Plan before apply**: Plans modifying `.tf` files must present `terraform plan` output to the human before any `terraform apply`. Apply is human-gated EXCEPT the sandbox PLATFORM environment (`terraform/personal/**`), where push-to-main auto-applies behind the deterministic guard (`scripts/terraform_apply_guard.py`, fail-closed on any destroy/IAM/trust change) plus a subagent plan review, per Decision 77 and `docs/contracts/environment-taxonomy.md`. SIT/PROD remain human-gated and are future-state. See `planning` skill, Step 4 (Infrastructure Assessment).
- **IAM precedence**: If a change modifies IAM (`*.tf` IAM resources or roles attached to Lambdas), `terraform apply` must precede any Lambda code deploy.

## AWS context
- Region: `eu-west-2`
- Account: personal platform account (ID supplied via gitignored `terraform/personal/terraform.personal.tfvars`; never committed).
- Profile: `agent_platform` (PlatformDev, runtime) for agent operations; `agent_platform_admin` (PlatformAdmin) for provisioning (creates IAM + OIDC).
- Glue database: `agent_platform` (personal module). Retained work-root `.tf` files still reference `trading_formulas_db`.
- Personal-account infra lives in the isolated `terraform/personal/` root module (own provider + state). The work-account files in `terraform/` are retained per CD.21 but no longer applied.
- The personal account has no SCP restricting IAM users or external OIDC (the Decisions 36/37 SCP block was work-account-only). OIDC provider + CI roles are created in `terraform/personal/oidc.tf`.

## Out-of-band IAM grants (drift -- not managed by this module)

The `PlatformDev` and `PlatformAdmin` roles pre-exist the module and are now BOTH codified (see the
CODIFIED bullets below). The only item still applied out-of-band via the `platform_breakglass` IAM
user (full admin) and NOT codified in `terraform/personal/` is the redundant `AgentPlatformRuntime`
inline policy (slated for removal) -- re-creating infra elsewhere will not restore it; reapply manually if needed.

- **`PlatformAdmin` + `PlatformDataLakeProvisioning` (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`;
  datalake policy narrowed to least-privilege 2026-05-30):**
  `aws_iam_role.platform_admin` (import ID `PlatformAdmin`, `max_session_duration = 3600`) plus its two inline
  policies -- `aws_iam_role_policy.platform_admin_ops` (`AdminOps`: identity admin -- `iam:*` + admin Lambda +
  secretsmanager) and `aws_iam_role_policy.platform_admin_datalake` (`PlatformDataLakeProvisioning`: the data-plane
  rights AdminOps lacks). The datalake grant is required so `terraform apply` under `agent_platform_admin` can
  provision + manage the data lake, workgroup, Glue DB, and counters table. It is ENUMERATED least-privilege (no
  `glue:*`/`athena:*`/`s3:*`/`dynamodb:*` service wildcards; no legacy `bblake-platform-*` ARNs), scoped to the
  agent-platform data lake: Glue actions on the catalog + `agent_platform` DB + its tables; Athena manage on the
  `agent-platform-production` workgroup (+ account-level query-status reads that don't support resource scoping);
  `s3` bucket-config + object IO on `agent-platform-data-lake` only; DynamoDB TABLE-level actions (NOT item-level
  -- counter VALUES are PlatformDev runtime's domain) on `agent-platform-counters` only. The action set mirrors the
  `github_ci_apply` CI role's data-plane statements. NOTE: the set includes refresh-time READS the AWS provider
  (v5.100) issues on every `plan` -- `glue:GetTags`, `dynamodb:DescribeContinuousBackups`/`DescribeTimeToLive` --
  which apply does not exercise but `plan` (and therefore CD) requires; do not prune them as "unused". IMPORT the
  role before apply; the trust policy MUST show NO change in `plan` (lockout guard -- this is the role the apply
  assumes). If a future module addition needs a new data-plane action, expect the FIRST `plan` after the apply to
  surface it as an AccessDenied refresh read; add it (scoped) and re-apply with `-refresh=false` (state is fresh
  from the apply), then a full `plan` converges.
- **PlatformDev runtime grant (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`):** the
  `agent_platform` (PlatformDev) runtime role is now Terraform-managed. `aws_iam_role.platform_dev`
  (imported, ID `PlatformDev`) sets `max_session_duration = 36000` (was 3600 -- the 3600 max blocked
  CC-web's 10h unattended sessions); `aws_iam_role_policy.platform_dev_runtime` codifies the `DailyOps`
  inline policy (Athena query on `agent-platform-production`; S3 read-write on `agent-platform-data-lake`;
  DynamoDB on `agent-platform-counters`; Glue read + table mutations). Applied via `platform_breakglass`
  with `-target` on the two role resources (the unrelated `null_resource` Athena-DDL replacements from a
  later main.tf edit were deliberately excluded). Trust policy verified unchanged at apply time.
  Reconciliation at import time (the role was NOT permissionless, contrary to the prior PENDING note):
    - A stale pre-rename `DailyOps` (dead `bblake-*` targets + a live `bedrock:InvokeModel*` grant) already
      existed and was imported; the apply overwrote it with the agent-platform grant. Net live capability
      dropped: `bedrock:InvokeModel*` (treated as unused -- `AgentPlatformRuntime` never granted Bedrock
      and ops works without it; no Bedrock consumer was found for this role, but no exhaustive audit was run).
    - A separate out-of-band `AgentPlatformRuntime` inline policy already granted the same agent-platform
      ops set, so ops calls succeeded both before and after this change. It is now a redundant duplicate of
      the codified `DailyOps`. FOLLOW-UP: remove `AgentPlatformRuntime` via `platform_breakglass`.

Follow-up (remaining): remove the now-redundant `AgentPlatformRuntime` inline policy via `platform_breakglass`
(its grants are fully covered by the codified `DailyOps`). A formal Decision recording the static-key credential
model (PlatformDev + PlatformAdmin codification, Decision-57 SSO-recovery supersession) is filed via the ops portal.

## Athena workgroup rules
- `agent-platform-production` (engine v3) — OPTIMIZE, MERGE writes, all production queries (personal module).
- `primary` (engine v2, default) — **do not use** for Iceberg DML or VACUUM. v2 doesn't support full Iceberg semantics.

## Athena/Iceberg DDL gotchas
- `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS`. Issue one column per statement; ignore "already exists" errors.
- `CREATE TABLE IF NOT EXISTS` does not update TBLPROPERTIES on an existing table. Use `ALTER TABLE SET TBLPROPERTIES` instead.
- `VACUUM` requires engine v3. Always use `WorkGroup='agent-platform-production'`.
- Iceberg integer promotion: prior writes may have promoted `int` → `bigint`. Re-declaring as `int` fails ("Cannot change column type: long -> int"). Detect and honour existing promoted types.

## Lambda interaction
- Lambda zipped deployment limit ~262144000 bytes. `scripts/build_lambda.py` asserts this.
- Lambda runtime: Python 3.12.
- Layer: `AWSSDKPandas-Python312:22` (managed) + extras layer.

For Lambda deployment workflow rules, see `src/data/handlers/CLAUDE.md`.
