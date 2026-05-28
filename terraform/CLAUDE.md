# Terraform — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

Some rules below restate root rules for proximity. Root `CLAUDE.md` is authoritative if they ever drift.

## Hard rules
- **Optional artifacts**: Always wrap `filemd5()` and `file()` calls on optional artifacts with `try()`. Bad: `source_code_hash = filemd5("build/lambda.zip")`. Good: `source_code_hash = try(filemd5("build/lambda.zip"), md5(file("module_file.tf")))`.
- **ASCII tag values**: Plain ASCII hyphens (`-`) only in Lambda tag values. No em dashes — they fail in AWS API serialisation.
- **Plan before apply**: Plans modifying `.tf` files must present `terraform plan` output to the human before any `terraform apply`. Apply is never automatic — see `planning` skill, Step 4 (Infrastructure Assessment).
- **IAM precedence**: If a change modifies IAM (`*.tf` IAM resources or roles attached to Lambdas), `terraform apply` must precede any Lambda code deploy.

## AWS context
- Region: `eu-west-2`
- Account: personal platform account (ID supplied via gitignored `terraform/personal/terraform.personal.tfvars`; never committed).
- Profile: `agent_platform` (PlatformDev, runtime) for agent operations; `agent_platform_admin` (PlatformAdmin) for provisioning (creates IAM + OIDC).
- Glue database: `agent_platform` (personal module). Retained work-root `.tf` files still reference `trading_formulas_db`.
- Personal-account infra lives in the isolated `terraform/personal/` root module (own provider + state). The work-account files in `terraform/` are retained per CD.21 but no longer applied.
- The personal account has no SCP restricting IAM users or external OIDC (the Decisions 36/37 SCP block was work-account-only). OIDC provider + CI roles are created in `terraform/personal/oidc.tf`.

## Out-of-band IAM grants (drift -- not managed by this module)

Applied directly via the `platform_breakglass` IAM user (full admin); NOT codified in
`terraform/personal/`. The `PlatformDev` and `PlatformAdmin` roles pre-exist the module, so
re-creating infra elsewhere will not restore these policies -- reapply manually if needed.

- **`PlatformDataLakeProvisioning`** (inline policy on role `PlatformAdmin`) -- grants the
  data-plane rights `PlatformAdmin`'s base `AdminOps` policy lacks (it is an identity admin:
  `iam:*` + lambda + secretsmanager only). Scope: Glue + Athena `Resource: "*"`; `s3:*` on
  `agent-platform-data-lake`; `dynamodb:*` on `table/agent-platform-*`. Required so `terraform apply`
  under `agent_platform_admin` can create the data lake, workgroup, Glue DB, and counters table.
- **PlatformDev runtime grant (PENDING -- required before the ops-data migration runs):** the
  `agent_platform` (PlatformDev) runtime role is currently permissionless. The migration needs:
  Athena `StartQueryExecution`/`GetQueryExecution`/`GetQueryResults`/`GetWorkGroup`; S3 read-write
  on `agent-platform-data-lake`; DynamoDB `GetItem`/`UpdateItem` on `agent-platform-counters`;
  Glue `GetDatabase`/`GetTable`/`GetPartitions`. Grant via `platform_breakglass`; record here once applied.

Follow-up: codify these (import the roles or attach managed policies) and author a formal Decision
once the migration completes and the ops portal is writable.

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
