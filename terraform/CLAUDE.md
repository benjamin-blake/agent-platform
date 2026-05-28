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
- Account: REDACTED-ACCOUNT-ID (sandbox)
- Profile: `company-aws-profile` (SSO) for agent operations.
- Glue database: `trading_formulas_db`.
- Company SCPs block IAM user creation and external OIDC provider registration. Do not propose either — see Decisions 36 and 37.

## Athena workgroup rules
- `agent-platform-production` (engine v3) — OPTIMIZE, MERGE writes, all production queries.
- `agent-platform-lab` (engine v3) — PySR formula discovery.
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
