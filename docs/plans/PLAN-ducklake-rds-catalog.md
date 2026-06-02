# Plan

## Intent
Provision the RDS PostgreSQL catalog that backs the DuckLake operational lakehouse (Decision 78 /
CD.31). This is the foundation gate (T2.16) for the DuckLake workstream that replaces the brittle,
slow Iceberg-on-S3 read path for ops/telemetry data - a direct enabler of the self-improvement
loop's ability to read its own history quickly. It un-blocks T2.17-T2.19.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-rds-catalog.md

## Phase
Platform-axis tier T2, roadmap item **T2.16** (RDS PostgreSQL DuckLake catalog provisioning),
sandbox environment, single personal account (Decision 77). Product roadmap_phase "Phase 1: Core
Infrastructure" is complete and orthogonal to this platform-axis infra.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `terraform/personal/rds_ducklake_catalog.tf` | Create | RDS PostgreSQL `db.t4g.micro` (single-AZ, gp3, PITR) DuckLake catalog + DB subnet group + security group (5432 from a variable CIDR allow-list) + RDS-managed master-password secret; `data` sources for the default VPC/subnets; outputs (endpoint, port, db name, master-secret ARN) for T2.17 |
| `terraform/personal/variables.tf` | Modify | Add `ducklake_catalog_ingress_cidrs` (no default - supplied via gitignored `terraform.personal.tfvars`) and optional `ducklake_catalog_db_name` / `ducklake_catalog_instance_class` knobs |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Justify T2.16 `depends_on: [T2.1]` in exit criteria (closes rec-2050); flip T2.16 `status: not_started -> complete` on completion |
| `terraform/personal/platform_roles.tf` | Modify (conditional, near-certain) | If the VP-3 admin IAM preflight fails - which is expected, since `platform_admin_ops` grants no `rds:*`/`ec2:*` - extend that policy with scoped RDS + EC2-networking actions; apply via `platform_breakglass` (human-gated) BEFORE the RDS apply, per the IAM-precedence rule |

Active module is `terraform/personal/` (the root `terraform/*.tf` is retired work-account infra per
`terraform/CLAUDE.md`). The roadmap's `files_in_scope: terraform/rds_ducklake_catalog.tf` names the
wrong root; the corrected path is `terraform/personal/rds_ducklake_catalog.tf`.

## Bundled Recommendations
- **rec-2050** (XS): justify T2.16's `depends_on: [T2.1]` anchor - addressed by the roadmap edit
  above plus the Context note (T2.1 stood up the `terraform/personal/` root module this RDS resource
  is added to). Close on completion.
- **rec-2059** (XS, Decision 36 reference hygiene): filed this session, intentionally **out of
  scope** here (targets `docs/DECISIONS.md`, unrelated to the RDS provisioning).

## Infrastructure Dependencies
| Item | Detail | Timing |
|------|--------|--------|
| Default VPC + subnets | Used via `data.aws_vpc {default=true}` + `data.aws_subnets`. No VPC is provisioned in T2.16; T2.17 re-homes the catalog into a dedicated, private, controlled-egress VPC. | Pre-apply (read) |
| `agent_platform_admin` (PlatformAdmin) IAM grant | `AdminOps` grants `iam:*` + Lambda + `secretsmanager` but is NOT documented to grant `rds:*` or `ec2:*` (SG/subnet). May need extension in `terraform/personal/platform_roles.tf` (an IAM change, human-gated, applied via `platform_breakglass`) BEFORE the RDS apply. | Pre-apply (IAM precedence, Decision 35 / terraform CLAUDE.md) |
| Terraform apply | **Human-gated manual apply** via `agent_platform_admin` from the branch, BEFORE merge. Do NOT rely on the Decision-77 sandbox auto-apply: the guard (`scripts/terraform_apply_guard.py`) is permissive for create-only non-IAM resources, so a merge would otherwise auto-provision a billed RDS with no human in the loop (see Constraints). | Pre-merge |
| Cost | ~$12-15/mo (single-AZ `db.t4g.micro` + gp3 + PITR). Net platform spend is roughly flat - the ~$35/mo EC2 runner retired (CD.21). | Ongoing |

## Acceptance Criteria
- [ ] `terraform/personal/rds_ducklake_catalog.tf` declares a PostgreSQL `db.t4g.micro` (single-AZ,
      gp3 >= 20GB), a DB subnet group over the default VPC subnets, a security group allowing 5432
      ONLY from `var.ducklake_catalog_ingress_cidrs`, `manage_master_user_password = true` (RDS-managed
      Secrets Manager secret; no password in TF state), `backup_retention_period >= 7` (PITR), and
      `publicly_accessible = true` (so local DuckDB can ATTACH under the Decision-67 Lambda freeze).
- [ ] `terraform fmt -check` and `terraform validate` pass.
- [ ] `terraform plan` presented to the human; apply executed **manually** via `agent_platform_admin`
      (human-gated, before merge); plan shows creates only - 0 destroy, 0 replace, no IAM resources.
- [ ] DuckDB `ATTACH 'ducklake:postgres:...'` against the RDS PostgreSQL catalog succeeds from local
      DuckDB and a CREATE/INSERT/SELECT round-trip works, with the catalog metadata living in a
      dedicated PostgreSQL schema (separability for a future market-data catalog, OQ.14). (The exact
      DuckLake v1.0 postgres-catalog ATTACH option name is resolved during VP-6 - see its note.)
- [ ] Catalog endpoint + master-secret ARN exported as Terraform outputs (consumed by T2.17).
- [ ] Roadmap: T2.16 `depends_on: [T2.1]` justified (rec-2050) and `status` flipped to `complete`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Format check | `cd terraform/personal && terraform fmt -check -diff rds_ducklake_catalog.tf` | No diff | Run `terraform fmt` |
| 2 | [pre-deploy] | HCL validate | `cd terraform/personal && terraform init -backend=false -input=false && terraform validate` | "The configuration is valid." | Fix HCL / provider-schema errors |
| 3 | [pre-deploy] | Admin IAM preflight | `aws rds describe-db-instances --profile agent_platform_admin --region eu-west-2 >/dev/null && aws ec2 describe-security-groups --max-results 5 --profile agent_platform_admin --region eu-west-2 >/dev/null && echo IAM_OK` | Prints `IAM_OK` (admin can read RDS + EC2 -> create likely permitted) | On AccessDenied, extend `PlatformAdmin` in `platform_roles.tf` with scoped `rds:*` + `ec2:*` (networking) actions and apply that IAM change via `platform_breakglass` first |
| 4 | [pre-deploy] | Plan + guard demonstration | `cd terraform/personal && terraform plan -var-file=terraform.personal.tfvars -out=ducklake.tfplan && terraform show -json ducklake.tfplan > /tmp/ducklake_plan.json && bin/venv-python scripts/terraform_apply_guard.py /tmp/ducklake_plan.json; echo "guard_exit=$?"` | Plan creates `aws_db_instance` + `aws_db_subnet_group` + `aws_security_group` (+ rules); 0 destroy/replace; 0 IAM resources. Guard prints `guard_exit=0` - **demonstrating the Decision-77 WARN** (it would auto-apply). Present plan to human. | If plan shows destroy/replace or an IAM resource, stop and investigate |
| 5 | [post-deploy] | Human-gated apply | `cd terraform/personal && terraform apply ducklake.tfplan` (run by the human under `agent_platform_admin`) | Apply completes; `aws_db_instance` reaches `available` | Resolve AccessDenied / quota / subnet-AZ-count errors |
| 6 | [post-deploy] | DuckLake ATTACH round-trip (the V3 proof) | `bin/venv-python - < scripts/verify snippet` (literal heredoc below the table) | Prints `ATTACH OK rows=1`; a Parquet file appears under `s3://agent-platform-data-lake/ducklake/` | SG ingress CIDR vs egress IP mismatch; `publicly_accessible`; wrong secret; ducklake/httpfs not loaded; META_SCHEMA option name (confirm against pinned DuckLake v1.0) |
| 7 | [post-deploy] | Outputs for T2.17 | `cd terraform/personal && terraform output -raw ducklake_catalog_endpoint && echo && terraform output -raw ducklake_catalog_master_secret_arn` | Non-empty `host:port` and a `arn:aws:secretsmanager:...` value | Add the missing `output` blocks to the `.tf` file |

**VP-6 connectivity snippet** (run from repo root; reuses the extension-load + S3-credential pattern
from `src/common/ducklake_spike.py` `_open_connection` / `_set_s3_credentials` - prefer importing that
helper over the hand-rolled `SET s3_*` block below). **NOTE - unverified ATTACH form:** the spike
validated only the SQLite-catalog `(TYPE DUCKLAKE)` form; the `ducklake:postgres:` data-source prefix
and the `META_SCHEMA` metadata-schema option below are NOT yet exercised anywhere in the repo. Resolve
the exact DuckLake v1.0 postgres-catalog option (`META_SCHEMA` vs `METADATA_SCHEMA` vs a pre-created
schema) against the pinned docs before asserting; the round-trip assertion is genuinely behavioural
and will fail loudly if the option is wrong:
```bash
bin/venv-python - <<'PY'
import json, subprocess, boto3, duckdb
REGION = "eu-west-2"
def tf(k): return subprocess.check_output(
    ["terraform", "-chdir=terraform/personal", "output", "-raw", k]).decode().strip()
endpoint, secret_arn = tf("ducklake_catalog_endpoint"), tf("ducklake_catalog_master_secret_arn")
host, port = endpoint.split(":")
sm = boto3.session.Session(profile_name="agent_platform_admin", region_name=REGION).client("secretsmanager")
sec = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
con = duckdb.connect()
con.execute("INSTALL ducklake; LOAD ducklake; INSTALL httpfs; LOAD httpfs;")
c = boto3.session.Session(profile_name="agent_platform").get_credentials().get_frozen_credentials()
con.execute(f"SET s3_region='{REGION}'")
con.execute(f"SET s3_access_key_id='{c.access_key}'")
con.execute(f"SET s3_secret_access_key='{c.secret_key}'")
if c.token:
    con.execute(f"SET s3_session_token='{c.token}'")
dbname = sec.get("dbname", "ducklake_catalog")
pg = f"ducklake:postgres:host={host} port={port} dbname={dbname} user={sec['username']} password={sec['password']}"
con.execute(f"ATTACH '{pg}' AS ops_lake "
            f"(DATA_PATH 's3://agent-platform-data-lake/ducklake/', META_SCHEMA 'ducklake_ops')")
con.execute("CREATE TABLE IF NOT EXISTS ops_lake.t2_16_probe(id INTEGER, note VARCHAR)")
con.execute("INSERT INTO ops_lake.t2_16_probe VALUES (1, 'attach-ok')")
n = con.execute("SELECT count(*) FROM ops_lake.t2_16_probe").fetchone()[0]
con.execute("DROP TABLE ops_lake.t2_16_probe")
print(f"ATTACH OK rows={n}")
PY
```
If `META_SCHEMA` is not the correct DuckLake v1.0 option for a dedicated PostgreSQL metadata schema,
pre-create the schema (`psql ... -c 'CREATE SCHEMA IF NOT EXISTS ducklake_ops'`) and resolve the
exact ATTACH option against the pinned DuckLake v1.0 docs; the round-trip assertion is unchanged.

## Constraints
- **Terraform apply is human-gated (Decision 35).** The first paid-RDS apply is a deliberate manual
  `agent_platform_admin` apply from the branch, BEFORE merge. **Do NOT rely on the Decision-77 sandbox
  auto-apply:** `terraform_apply_guard.py`'s `IAM_SENSITIVE_TYPES` covers only `aws_iam_*` + trust +
  destroy/replace, so a create-only `aws_db_instance` + `aws_security_group` + secret returns guard
  exit 0 (auto-apply eligible). Applying manually first updates the shared S3 state, so the post-merge
  main CD plan is a no-op.
- **Single-account-until-live_full (Decision 77 section 4).** Lands in the single personal/sandbox
  account; provisions no multi-account infra and no SIT/PROD resources.
- **No Lambda is deployed (Decision 67 freeze).** T2.16 is Terraform-only; connectivity is verified
  from local DuckDB, not a test Lambda. No Lambda-packaged file is in scope, so no `--deploy` step.
- **Credentials: RDS-managed master password in Secrets Manager** (`manage_master_user_password = true`)
  - no password literal in Terraform state. IAM database auth is deliberately NOT used (it would add
  `aws_iam_*` resources and add 15-minute token-refresh plumbing to every DuckDB ATTACH). The
  no-IAM-users posture once attributed to Decision 36 is work-account-only and not binding here
  (`terraform/CLAUDE.md`); the choice rests purely on DuckDB ergonomics + rotation-readiness (ties to
  T2.9).
- **Secrets / IDs never committed.** `account_id`, external IDs, and `ducklake_catalog_ingress_cidrs`
  are supplied via gitignored `terraform.personal.tfvars` (parameterisation invariant). The ingress
  CIDR has NO default - it must be an explicit allow-list (never `0.0.0.0/0`).
- `terraform/CLAUDE.md`: ASCII-only tag values; plan-before-apply; IAM-change-precedes-dependent-apply.
- No rescue agents or workaround loops (Decision 55). If apply or ATTACH fails unrecoverably, stop and
  root-cause; do not paper over with retries.
- Python in verification: `bin/venv-python`, type-hint-clean, ruff line length 127, no emojis.

## Context
- **Decision 78 (governing)** adopts DuckLake v1.0 for ops/telemetry; clause 3 names exactly this
  catalog backend ("RDS PostgreSQL db.t4g.micro, single-AZ, PITR ... a durable Glue-analog, NOT a
  query engine"). **CD.31** is ratified. T2.16 is the physical enactment of clause 3.
- **Decision 77** governs the apply posture (sandbox auto-apply guard + the single-account rule). See
  the WARN in Constraints - the guard does not gate create-only RDS.
- **Decision 35** is the human-gate; **Decision 67** is why verification is local-DuckDB not Lambda;
  **Decision 24** is the single personal-account model; **Decision 48** confirms V3 (terraform with
  runtime effects + behavioural ATTACH round-trip).
- **Decision 69** (Single-Portal invariant, preserved under Decision 78) is untouched here - the
  ops write-path migration is FP-B / T2.19, explicitly out of scope.
- **T2.1 dependency (rec-2050):** T2.1 ("Full Terraform re-deploy in personal account", status
  complete) stood up the isolated `terraform/personal/` root module (own provider + S3 backend) that
  this RDS resource is added to - that is the justification for `depends_on: [T2.1]`.
- **PlatformAdmin IAM gap:** `AdminOps` is documented with `iam:*` + Lambda + `secretsmanager` but not
  `rds:*` / `ec2:*`; VP step 3 preflights this and step's Fix-If extends `platform_roles.tf` (IAM,
  human-gated) before apply if needed.
- **Network posture is intentionally minimal for the foundation step:** default VPC + publicly
  accessible + SG locked to an explicit CIDR allow-list makes the exit-criterion ATTACH test runnable
  now (under the Lambda freeze). T2.17 re-homes the catalog into a dedicated, private, VPC-attached,
  controlled-egress posture - at which point `publicly_accessible` flips to false.
- **Prior art:** `src/common/ducklake_spike.py` (FP-A spike) validated DuckDB 1.5.2 / DuckLake v1.0
  with a local SQLite catalog; VP-6 reuses its extension-load + S3-cred + ATTACH pattern against the
  PostgreSQL catalog.
- `rec-2059` (Decision 36 reference hygiene) filed this session, tracked separately.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`claude/...` harness branch)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (Decisions 78, 77, 35, 67, 24, 48)
- [ ] `terraform/personal/main.tf` + `variables.tf` read (module conventions: S3 backend, `eu-west-2`,
      `agent_platform_admin` provisioning profile, default-tags pattern)
- [ ] `terraform.personal.tfvars` present with `account_id`, external IDs, and a real
      `ducklake_catalog_ingress_cidrs` value (the developer/CI egress CIDR)
- [ ] `terraform`, `duckdb` (python pkg), and AWS profiles `agent_platform` + `agent_platform_admin`
      available
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Read module conventions** - `terraform/personal/main.tf`, `variables.tf`, and `terraform/CLAUDE.md`
   to match provider/tagging/backend idiom.
2. **Add variables** to `terraform/personal/variables.tf`: `ducklake_catalog_ingress_cidrs`
   (`list(string)`, no default, with a `validation` block rejecting `0.0.0.0/0`), and optional
   `ducklake_catalog_db_name` (default `ducklake_catalog`) + `ducklake_catalog_instance_class`
   (default `db.t4g.micro`).
3. **Author `terraform/personal/rds_ducklake_catalog.tf`**: `data.aws_vpc.default` +
   `data.aws_subnets.default`; `aws_db_subnet_group`; `aws_security_group` + ingress 5432 from the CIDR
   allow-list and egress all; `aws_db_instance` (engine `postgres`, `db.t4g.micro`, `gp3`,
   `allocated_storage >= 20`, single-AZ, `manage_master_user_password = true`,
   `backup_retention_period = 7`, `publicly_accessible = true`, `deletion_protection = true`,
   `skip_final_snapshot = true`, ASCII-only tags); `output` blocks for endpoint, port, db name, and
   `master_user_secret[0].secret_arn`. Run `terraform fmt` immediately after writing.
4. **VP steps 1-2** (fmt + validate). Loop until clean.
5. **VP step 3** (admin IAM preflight). If AccessDenied, extend `PlatformAdmin` in
   `terraform/personal/platform_roles.tf` with scoped `rds:*` + `ec2:*` networking actions and apply
   that IAM change via `platform_breakglass` (human-gated) BEFORE proceeding.
6. **VP step 4** (`terraform plan` + apply-guard demonstration). Present the plan output to the human.
7. **VP step 5** - human runs the gated `terraform apply` under `agent_platform_admin` from the branch.
8. **VP step 6** - DuckLake ATTACH round-trip from local DuckDB (the V3 behavioural proof).
9. **VP step 7** - confirm outputs for T2.17.
10. **Roadmap update** - in `docs/ROADMAP-PLATFORM.yaml`, add the `depends_on: [T2.1]` justification to
    T2.16's exit criteria (closes rec-2050) and flip T2.16 `status: not_started -> complete`.
11. **Close recs** - `rec-2050` (status closed) via `python -m scripts.ops_data_portal --update-rec`.
12. **Execute Verification Plan** - run each step; loop until pass. If VP-6 fails unrecoverably after a
    real root-cause pass, stop and analyze (Decision 55) - do not loop on workarounds.
13. **Report** - what was implemented, the `terraform plan` summary, apply result, and VP-6 output.
