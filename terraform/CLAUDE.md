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

## Running terraform/personal/ on CC-web (no local machine; vars come from remote state)
**This project runs ONLY on Claude Code on the web. There is no operator local machine.** The agent
itself runs `terraform plan`/`apply` for `terraform/personal/` inside the CC-web container.

`terraform/personal/terraform.personal.tfvars` is **gitignored** (`.gitignore`:
`terraform/**/terraform.personal.tfvars`), so it is NOT in the fresh clone and there is no standalone
`s3://.../terraform.personal.tfvars` object to fetch -- do not go looking for that file. The four
no-default vars (`account_id`, `owner_email`, `platform_dev_external_id`, `platform_admin_external_id`)
are recoverable from the **remote Terraform state in S3**, which IS the source of truth:
- State: `s3://agent-platform-data-lake/tfstate/personal/sandbox/terraform.tfstate` (region `eu-west-2`),
  wired via `terraform -chdir=terraform/personal init -backend-config=backend-sandbox.hcl`.
- The values live as resource attributes in that state: `account_id` in every resource ARN;
  the two ExternalIds in the IAM roles' `assume_role_policy` trust documents (`sts:ExternalId` condition);
  `owner_email` in resource tags / the SNS subscription endpoint. `account_id` is also obtainable from
  `aws sts get-caller-identity`.
- After `init`, recover them with `terraform state show` / a parse of the state JSON, then pass via `-var`
  (or a regenerated, still-gitignored tfvars) for `plan`.
- **Never paste these values into chat, a PR, or any committed file** -- the ExternalIds are AssumeRole
  trust secrets and the account id is shape-blocked by the pre-commit `never-commit` hook.

**Apply posture (current):** the planned CD auto-apply path is the FUTURE state but has issues right now,
so for now the CC-web agent works the loop **iteratively: run `terraform plan` -> PRESENT it -> the human
accepts the presented plan (this acceptance IS the human gate, Decision 77/35) -> agent runs `terraform
apply`.** The deterministic `scripts/terraform_apply_guard.py` (fail-closed on any destroy/IAM/trust change)
still runs as the safety net. Do not apply without presenting the plan and getting acceptance first.

**Apply posture (record-backed sandbox CD, CD.35 / T2.20 Wave 1):** sandbox CD auto-apply
(`.github/workflows/terraform-apply-sandbox.yml`; push-to-main touching `terraform/personal/**` auto-applies
behind the guard + subagent plan review). It sources all no-default root-module variables from the
`agent-platform-terraform-personal-tfvars` Secrets Manager secret: the apply role's `SecretsManagerTfvarsRead`
grant fetches the secret body to `terraform.personal.tfvars`, which is passed to `terraform plan` via
`-var-file`. New no-default variables only require updating that secret -- no per-variable workflow edit.
`TF_VAR_aws_profile=""` is the sole remaining env override (blanks the named-profile default so the OIDC
credential env vars take effect). Wave 1 made the apply outcome **sticky and observed**: the apply
job reads a durable convergence record as a precondition and refuses on red, writes the record green/red
(always-run) after apply, and apply failures wire into `ci-rca` -- so a later green run can no longer mask
an earlier apply failure. The interactive human-gated loop above remains the path for **IAM/trust/destroy**
changes (the guard fail-closes them; they never auto-apply) and is still valid for any change you want to
apply by hand. Routine (guard-PASS, non-IAM) changes are designed to ride the record-backed pipeline.

### Convergence anchor (CD.35 / T2.20 Wave 1)

The server-side anti-masking anchor. All four pieces live in `terraform-apply-sandbox.yml` + `oidc.tf`:

- **Durable record:** `s3://agent-platform-data-lake/convergence/personal/sandbox.json`
  (`{status, commit_sha, run_id, run_url, timestamp, plan_sha}`; `plan_sha` is null until Wave 2 saved
  plans). Its OWN S3 prefix, **outside `tfstate/`**, so the read-only PR role reads it without ever seeing
  tfstate. Write-IAM is **apply-identity-only among the CI roles** -- enforced in `oidc.tf` by
  `ConvergenceRecordWrite` on `github_ci_apply` (the writer), the explicit `DenyConvergenceRecordWrite` on
  `github_ci_branch` (ci-rca / `agent/*` CI keep read, never write/delete the record), and the PR role's
  read-only `S3ReadConvergenceRecord`. This is the integrity anchor -- a commit status alone is spoofable.
  (The residual admin / `platform_breakglass` write path is not yet IAM-fenced; full privilege-tiering --
  the pipeline's own IAM to a bootstrap root -- lands at Wave 4 / T2.23. "Unbypassable" is scoped to
  merge-path CI actors, per CD.35 5.5d.)
- **Red-record refusal = the SOLE hard block.** The apply job's read-precondition refuses (emits the
  distinguishable marker `CONVERGENCE_RED`, exits non-zero, and does **NOT** overwrite the record) when the
  record is red. Unbypassable by any merge-path actor. An **absent** record = first-apply-allowed
  (pass-on-absent); the first apply writes the first record (no human seed -- preserves apply-only write-IAM).
- **Advisory `terraform-converged` PR status (NOT a required check).** A read-only `pull_request` job
  (`github_ci_pr` role, `S3ReadConvergenceRecord`) posts it for visibility. Deliberately advisory: a required
  check would wedge the autonomous fix-merge once a record is red, or be admin-bypassed anyway
  (`main-protection` `strict=false`, admin `bypass_mode=always`, Decision 83). Do **not** add it to the
  ruleset's `required_status_checks`.
- **Dispatch-ack unlatch = the ONLY way to clear red.** A red record clears **only** when an apply from a
  `workflow_dispatch` acknowledge-and-retry run succeeds; its `acknowledge_red_commit` input names the red
  commit SHA (or the open rec id). A plain push never clears red (auto-allow-descendants is rejected -- on
  linear-history main every commit is a descendant). The dispatch actor + input are the audit trail; the
  agent may dispatch via the GitHub MCP actions trigger **after** the `ci-rca` rec is reviewed (Decision
  55/72) -- nothing auto-remediates. Refusals-while-red dedupe to the one open red-record rec (ci-rca anchors
  on the record's commit). Serialisation is the existing workflow `concurrency` group
  (`cancel-in-progress: false`).

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
    - A stale pre-rename `DailyOps` (dead `bblake-*` targets + a live Bedrock invoke-model grant) already
      existed and was imported; the apply overwrote it with the agent-platform grant. Net live capability
      dropped: the Bedrock invoke-model grant (treated as unused -- `AgentPlatformRuntime` never granted Bedrock
      and ops works without it; no Bedrock consumer was found for this role, but no exhaustive audit was run).
    - A separate out-of-band `AgentPlatformRuntime` inline policy already granted the same agent-platform
      ops set, so ops calls succeeded both before and after this change. It is now a redundant duplicate of
      the codified `DailyOps`. FOLLOW-UP: remove `AgentPlatformRuntime` via `platform_breakglass`.

Follow-up (remaining): remove the now-redundant `AgentPlatformRuntime` inline policy via `platform_breakglass`
(its grants are fully covered by the codified `DailyOps`). A formal Decision recording the static-key credential
model (PlatformDev + PlatformAdmin codification, Decision-57 SSO-recovery supersession) is filed via the ops portal.

- **DuckLake IAM read-wildcard closure (PLAN-terraform-sandbox-convergence-closure, 2026-06-18, `github_ci_apply` inline policy, out-of-band admin apply):**
  The iterative-discovery anti-pattern for `github_ci_apply` refresh-READ grants (rec-2223 round, rec-2251 round) is
  permanently closed. Six READ-only Sids now use per-service wildcards (`Describe*/List*` or `Get*/List*`) scoped to the
  same resource ARNs as before: `CloudWatchLogsRead`, `LambdaRead`, `EventBridgeRead`, `SNSRead`, `CloudWatchAlarmsRead`,
  `SecretsManagerNeonAPIKeyRead`, `SecretsManagerTfvarsRead`, `SSMParameterRead`. WRITE Sids (`EventBridgeWrite`,
  `CloudWatchAlarmsWrite`, `LambdaPermissionWrite`, `SSMFeatureFlagsManage`, `ConvergenceRecordWrite`,
  `IAMRoleReconcile`, `OIDCProviderReconcile`) remain enumerated and ARN-scoped (no wildcards). IAM read Sids
  (`IAMPlatformRolesRead`) remain enumerated per Decision 35. Future refresh-read gaps for these services are
  covered structurally; no further iterative-discovery rounds are expected.

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
