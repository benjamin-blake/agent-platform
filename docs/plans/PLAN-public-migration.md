# Plan

## Intent

Migrate the repository to public visibility under the name `agent-platform`, cut over CI to
GitHub-hosted runners with OIDC to the personal AWS account (REDACTED-PERSONAL-ACCOUNT, profile
`agent_platform`), and migrate only `ops_recommendations` + `ops_decisions` operational data to
the personal account. All telemetry tables are intentionally dropped. The self-hosted EC2 runner
is terminated. This plan does not implement the full INTENT-aws-migration-platform-evolution.md
naming-convention overhaul; resource name decoupling (T0.15, T2.0) and Glue DB split (T2.16)
are deferred as follow-on debt.

## Plan Type

IMPLEMENTATION

## Verification Tier

V3 (Integration) -- creates live AWS resources in personal account, verifies cross-account data
migration, and validates CI on GitHub-hosted runners.

## Branch

agent/public-migration

## Phase

user_explicit_out_of_scope -- implements T2.10 (OIDC + hosted-runner migration) and T2.13
(public flip) from the platform roadmap, which have unfulfilled tier-item dependencies but are
explicitly requested. Soft-warn applies; proceed. T2.12 (GHAS, branch protection, CodeQL) is
not implemented; a DEFERRED step (Step 33) records this debt.

## Model Note

**This implementation MUST be executed using Claude Opus, not Sonnet.** The cross-account
infrastructure coordination, history rewrite sequencing, multi-file constant sweep, and V3
verification are beyond Sonnet's reliable execution depth for a plan of this scope. When opening
the /implement chat, verify the active model is Opus before proceeding.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `.gitignore` | Modify | Add `.claude/scheduled_tasks.lock`, `substitutions.txt`, `terraform/**/terraform.personal.tfvars` |
| `terraform/personal/` (NEW root module) | Create | SEPARATE Terraform root module with its OWN provider (personal account/profile) + state. Holds ALL personal-account infra: `main.tf` (provider + S3 data-lake, Glue DB, Athena workgroup, DynamoDB counters, the `ops_recommendations`/`ops_decisions`/`ops_priority_queue` Iceberg TABLES + their `_current` views -- preflight hard-exits if the priority-queue view is absent, Decision 61), `oidc.tf` (GitHub OIDC provider + branch role `ref:refs/heads/main`+`agent/*` + read-only PR role `ref:refs/pull/*`), `variables.tf` (`account_id` etc., NO committed default), `terraform.personal.tfvars` (gitignored). Rationale: the existing root repoints the DEFAULT `aws` provider via tfvars, so applying it against the personal account would try to CREATE ~120 work-account resources. A separate module is the only safe isolation |
| `terraform/ec2_runner.tf` | Modify | Add deprecation header comment (CD.21) ONLY. No `count` guard needed -- this file lives in the WORK-account root module, which is no longer applied (the personal module is separate). Resource definitions retained per CD.21 |
| `scripts/migrate_ops_data.py` | Create | One-time migration: READS source rows via a separate read-only boto3 work-profile Athena query against the `*_current` views (latest-per-id); WRITES exclusively through `ops_data_portal.file_rec` / `file_decision` (NO direct `OpsWriter`). Preserves IDs (`_migration_int_id`), `created_timestamp`, and `source` verbatim. Idempotency guard; `--skip-sync` bulk write |
| `tests/test_migrate_ops_data.py` | Create | Unit tests: mock Athena source, assert writes go via portal (not `OpsWriter.write`), assert migration never *reads* any `logs/` path as input, assert `_migration_int_id` set for BOTH recs and decisions, assert idempotency guard refuses on non-empty dest |
| `scripts/sync_recommendations.py` | Modify | Update `_DYNAMODB_TABLE` -> `"bblake-platform-counters"`. Add a MONOTONIC `reseed_recommendations_counter` (conditional UpdateItem that only raises) -- none exists today; `seed_counters` can LOWER a counter (Decision-50 collision risk). Needed by Step 13c |
| `config/agent/data_quality/source_registry.yaml` | Modify | Register any source values present in the migrated data but missing from the registry (known: `implement-session`, `Autonomous Postflight Cleanup`) as legacy entries -- else `validate_source` rejects those rows mid-migration. Reconciled in Step 13b dry-run |
| `scripts/ops_data_portal.py` | Modify | Update `_SSO_PROFILE`, `_ATHENA_DATABASE`, `_ATHENA_WORKGROUP` constants. Add a PRIVATE `_migration_int_id` param to `file_rec` (symmetric with the existing one on `file_decision`; bypasses `_next_id` when set). Add a `_skip_sync` flag to `file_rec`/`file_decision` so per-row `_sync_table()` is suppressed during bulk import (one `sync()` at end) |
| `scripts/ops_writer.py` | Modify | Update `DATABASE`, `ATHENA_WORKGROUP` constants; update any hardcoded `bblake-platform-agent-logs` S3 bucket references to `bblake-platform-data-lake` (Lambda-packaged -- deploy deferred) |
| `scripts/sync_ops.py` | Modify | Update constants; remove all `telemetry_*` entries AND `ops_session_log` / `ops_execution_plans` entries from `_TABLE_TO_LOCAL` / `_TABLE_TO_VIEW` |
| `scripts/session_preflight.py` | Modify | Update constants; remove / wrap telemetry SQL queries; fix `check_telemetry_health()` hardcoded `"trading_formulas_db"` literal; fix `ROOT.name` venv detection for rename |
| `scripts/data_quality_runner.py` | Modify | Update `_ATHENA_DATABASE`, `_ATHENA_WORKGROUP` constants |
| `config/agent/data_quality/telemetry.yaml` | Modify | Disable all DQ checks (telemetry tables not migrated) |
| `config/agent/data_quality/ops.yaml` | Modify | Update `database` and `athena_workgroup` fields |
| `config/config.personal.yaml` | Modify | Update `aws_profile` and bucket names to personal account values |
| `docs/GETTING_STARTED.md` | Modify | Remove / replace work account ID, SSO profile names, employer SSO portal URL |
| `README.md` | Modify | Remove / replace work account ID, employer SSO portal URL, any company-specific references |
| `config/config.company.yaml` | Modify | Add deprecation notice; no functional change (file describes the legacy environment accurately) |
| `config/README.md` | Modify | Replace `REDACTED-ACCOUNT-ID` and `company-aws-profile` references |
| `src/main.py` | Modify | Remove hardcoded `print("AWS Account: REDACTED-ACCOUNT-ID")` and any equivalent disclosures |
| `.github/prompts/build_cv_refactored.prompt.md` | Delete | Personal CV generation file; not a trading-system artefact; must not be in a public repo |
| `.github/agents/cv-reviewer.agent.md` | Delete | Same -- personal file with explicit employer references |
| `LICENCE` | Modify | Rewrite `Copyright (C) 2026 REDACTED-COPYRIGHT (The REDACTED-EMPLOYER)` (da-template boilerplate) to the author's own attribution (e.g. MIT, `Copyright (c) 2026 Benjamin Blake`). User confirmed this is their own work; the REDACTED-COPYRIGHT header was copied template scaffolding |
| `.github/copilot-instructions.md` | Modify | Public-facing instruction file: scrub `REDACTED-PERSONAL-ACCOUNT` (-> use placeholder / GH variable reference) and `personal-bedrock-profile`; also carries `REDACTED-ACCOUNT-ID`/`company-aws-profile` (handled by substitutions) |
| `docs/platform/agent-platform-bootstrap-record.yaml` | Delete | Operational secret: publishes personal account ID + breakglass/service-account ARNs. Purge from history (`--invert-paths`), not just HEAD |
| `docs/runbooks/policies/*.json` + `*.json.tmpl` | Delete | Operational secrets: full IAM trust/permission policy documents + ARNs (`platform-dev-daily-ops.json`, `platform-dev-trust.json.tmpl`, `platform-admin-trust.json.tmpl`, `agent-service-account-assume-role.json`). Purge from history |
| `docs/runbooks/platform-account-bootstrap.md` | Delete | Bootstrap runbook exposing account-id + IAM/breakglass bootstrap detail. Purge from history |
| `terraform/variables.tf` | Modify | Remove the committed DEFAULT for `platform_account_id` (`REDACTED-PERSONAL-ACCOUNT`); supply it via the gitignored `terraform.personal.tfvars` so no account-id literal is committed |
| `scripts/verify_platform_account.py` (+ `tests/test_verify_platform_account.py`) | Delete | One-time T0.3 verifier that hardcodes the LIVE breakglass IAM UserId (`REDACTED-IAM-USERIDE`) + account ID + role names; the `REDACTED-PERSONAL-ACCOUNT` substitution would also break its `_check_account_id` constant. Purge from ALL history via `--invert-paths` (same class as the secrets docs) |
| `terraform/agent_auth.tf`, `terraform/lambda_tooling_iam.tf`, `terraform/lambda_tooling_platform.tf`, `terraform/lambda_tooling_outputs.tf` | Modify | Personal-account IAM infra (functional -- KEEP). Parameterize the account ID via `var` (no committed literal); scrub any LIVE principal-ID literals (IAM UserIds). The architecture stays visible (consistent with publishing the journal); only live identifiers are scrubbed |
| `src/data/handlers/scheduled_agent_handler.py` | Modify | Scrub the `REDACTED-PERSONAL-ACCOUNT` docstring literal. NOTE: Lambda-packaged -- the actual deploy is DEFERRED (Decision 67 / CD.17), but the literal scrub lands now |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Line ~1738 hardcodes `arn:aws:iam::REDACTED-PERSONAL-ACCOUNT:role/PlatformAdmin` -- a live ARN in a published roadmap. Parameterize/redact the account segment |
| `logs/.customizations-manifest.json` | Modify | Remove the CV-generation entry that names "Benjamin Blake" tied to personal CV scripts (the CV files themselves are deleted; this manifest still points at them by full name) |
| `scripts/session_postflight.py` | Modify | `_SSO_PROFILE = "company-aws-profile"` -> `agent_platform`. RUNTIME PATH: postflight runs at every session close and calls `drain_pending(profile=_SSO_PROFILE)` / `drain_pending_decisions(...)` -- post-migration this would allocate IDs from the WORK DynamoDB counter and SSO-login to the employer account |
| `scripts/verifiers/data_quality.py` | Modify | `AWS_PROFILE` default `company-aws-profile` -> `agent_platform` (the DQ verifier inside `validate.py` / the V3 gate) |
| `scripts/cleanup_ops_rec_orphans.py` | Modify | Sweep the same hardcoded `company-aws-profile` profile literal -> `agent_platform` |
| `.github/workflows/ci.yml` | Modify | Switch `runs-on` ([self-hosted, linux]) to `ubuntu-latest` on all 3 jobs; add `permissions: {id-token: write, contents: read}` + OIDC credential step on the AWS-using job(s) only |
| `.github/workflows/ci-rca.yml` | Modify | Switch `runs-on` to `ubuntu-latest`; add `id-token: write` + OIDC branch-role step; preserve Decision 74 additions (workflow_dispatch + pinned Claude CLI) |
| `.github/workflows/main-canary.yml` | Modify | Switch `runs-on` to `ubuntu-latest`; add `id-token: write` + OIDC step where AWS access is needed |
| `.github/workflows/deploy.yml` | Modify | ALREADY `ubuntu-latest` -- no `runs-on` change. Add `id-token: write` + OIDC step only where AWS is called |
| `.github/workflows/claude.yml` | Modify | ALREADY `ubuntu-latest` -- no `runs-on` change. Add `id-token: write` + OIDC step where AWS is called; add comment noting Decision 71 self-hosted rationale superseded by CD.21 |
| `.github/workflows/pre_commit.yml` | Modify | ALREADY `ubuntu-latest` -- no `runs-on` change. Add OIDC step only if it makes AWS calls (verify; likely none) |
| `.github/workflows/refresh-copilot-multipliers.yml` | Modify | ALREADY `ubuntu-latest` -- no `runs-on` change. Add OIDC step only if it makes AWS calls (verify) |
| `AGENTS.md` | Modify | Update profile, account, repo name; remove EC2 runner runbook; add T2.12 deferral note |
| `docs/PROJECT_CONTEXT.md` | Modify | Update AWS section: account ID, profile, resource names, repo name |
| `terraform/CLAUDE.md` | Modify | Update account ID and profile name |
| `tests/test_session_preflight.py` | Modify | Replace `"agent-platform"` fixture strings (search by grep -- do not rely on specific line numbers) |

## Bundled Recommendations

- rec-403 (incidental): `.gitignore` verification -- addressed by Step 1.
- rec-725: Terraform state reconciliation (work account) -- out of scope; personal account Terraform
  starts from a clean state file. Noted in Context.

## Infrastructure Dependencies

| Resource | Account | Provider | Action |
|----------|---------|----------|--------|
All personal-account resources live in the NEW `terraform/personal/` root module with its own
`aws` provider (profile `agent_platform`, account REDACTED-PERSONAL-ACCOUNT) and its own state -- NOT the
existing work-account root (which uses the default + `aws.platform` aliased providers).

| Resource | Account | Module | Action |
|----------|---------|--------|--------|
| Glue DB `bblake_platform` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create |
| Athena workgroup `bblake-platform-production` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create |
| S3 bucket `bblake-platform-data-lake` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create |
| DynamoDB table `bblake-platform-counters` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create (seeded -- Step 7) |
| Iceberg tables `ops_recommendations` / `ops_decisions` / `ops_priority_queue` + their `_current` views | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create (views needed before migration writes + preflight) |
| OIDC provider `token.actions.githubusercontent.com` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create |
| IAM role `bblake-platform-github-ci-branch` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create (CI write perms; `refs/heads/main`+`agent/*`) |
| IAM role `bblake-platform-github-ci-pr` | REDACTED-PERSONAL-ACCOUNT | `terraform/personal/` | Create (read-only; `refs/pull/*`) |
| EC2 runner `agent-platform-runner` | REDACTED-ACCOUNT-ID | AWS CLI (not Terraform) | Terminate pre-deploy |

**terraform apply gating:** Step 12 produces a `terraform plan` output (run INSIDE
`terraform/personal/`) that must be reviewed by the human before `terraform apply`. Apply is never
automatic. Because the personal module is isolated, the plan shows ONLY the rows above -- never any
work-account resource.

**CD.21 / ec2_runner.tf:** CD.21 mandates retaining `terraform/ec2_runner.tf` (work-account root)
as an architectural-evolution artefact. Only a deprecation header comment is added; the work root is
no longer applied, so no `count` guard is required.

## Acceptance Criteria

- [ ] `bin/venv-python -m scripts.session_preflight` completes with "Preflight OK" and no Athena
  errors, connecting to personal account (requires `ops_priority_queue_current` to exist)
- [ ] Migrated `ops_recommendations` count in personal account equals `source - skipped_invalid`,
  verified by a LIVE Athena query against the destination (not the local cache):
  `SELECT count(*) FROM bblake_platform.ops_recommendations_current` equals
  source `count(*)` minus the `skipped_invalid` rows (legacy rows missing required fields), all
  recorded in `logs/debug/migration-summary.json`. `skipped_invalid` must be a SHORT, explainable
  list -- a large count means the validator pre-check is wrong, not that the data is bad
- [ ] Migrated `ops_decisions` count in personal account EQUALS source count, verified the same way
  via a LIVE Athena query against `bblake_platform.ops_decisions_current`
- [ ] Decision integer IDs preserved: `SELECT count(*) FROM bblake_platform.ops_decisions_current`
  grouped by `id` shows the SAME `dec-NNN` set as source (via `_migration_int_id` on `file_decision`)
- [ ] Recommendation IDs preserved: the `rec-NNN` set in `bblake_platform.ops_recommendations_current`
  matches source (via the NEW `_migration_int_id` on `file_rec`); no renumbering
- [ ] `source` field preserved verbatim on every migrated row (already-registered values pass
  `validate_source`); `created_timestamp` preserved; `last_updated_timestamp` = import time (portal default)
- [ ] DynamoDB counters are seeded ABOVE the migrated max (HARD gate, Decision 50): `recommendations`
  and `decisions` counters each `>= max(migrated_id) + margin` -- assert before declaring success
- [ ] Migration is idempotent: re-running against a non-empty destination is REFUSED (guard), so no
  duplicate appends / SCD2 resurrection
- [ ] `migrate_ops_data.py` writes ONLY through the portal (`file_rec`/`file_decision`), never
  `OpsWriter.write()` directly, and never *reads* any `logs/` path as input (unit-test asserted)
- [ ] History scrub VERIFIED across ALL blobs in ALL refs (not by file extension): zero hits for
  every sensitive token (`REDACTED-ACCOUNT-ID`, `REDACTED-EMPLOYER`, `REDACTED-EMPLOYER` (case-insensitive),
  `agent-platform`, `bblake-platform`, the work email, `company-aws-profile`) via
  `git grep <token> $(git rev-list --all)` AND `gitleaks detect --log-opts="--all"`
- [ ] `git log --all --format="%ae" | sort -u` no longer contains the work-account email; the
  human author identity is the GitHub no-reply (`217728084+benjamin-blake@users.noreply.github.com`).
  Bot author identities (Copilot, github-actions, anthropic) are intentionally retained
- [ ] CV files (`build_cv_refactored.prompt.md`, `cv-reviewer.agent.md`) are absent from ALL history
  (`git log --all -- <path>` returns nothing), not just HEAD
- [ ] Repo remains PRIVATE until the full-history scrub is verified on the merged `main`; only then flipped public
- [ ] CI passes on a PR against `agent-platform` using `ubuntu-latest` runner with OIDC to
  personal account
- [ ] Repo is publicly accessible at `github.com/benjamin-blake/agent-platform` without authentication

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | OIDC feasibility probe (BEFORE any irreversible action) | `aws iam list-open-id-connect-providers --profile agent_platform 2>&1; echo "exit=$?"` | `exit=0` (call permitted -- no SCP denial in personal account). `simulate-principal-policy` is NOT used: it evaluates identity policy, not SCPs | `AccessDenied` -> OIDC blocked in personal account; STOP before history rewrite / runner termination; escalate (CD.21 must be revisited) |
| 2 | pre-deploy | Scan full git history for secrets (ALL refs) | `gitleaks detect --source . --log-opts="--all" 2>&1 \| tail -20` | 0 findings, or only tokens already in substitutions.txt | Add unaddressed patterns to substitutions.txt; rerun filter-repo |
| 3 | pre-deploy | truffleHog verified-secret scan | `trufflehog git file://. --only-verified 2>&1 \| tail -20` | 0 verified findings | Rotate any live credential found; rewrite history |
| 4 | pre-deploy | AUTHORITATIVE GATE: EVERY sensitive token gone from ALL blobs in ALL refs | `for t in REDACTED-ACCOUNT-ID REDACTED-PERSONAL-ACCOUNT REDACTED-EMPLOYER agent-platform agent-platform-svc bblake-platform company-aws-profile personal-bedrock-profile company-admin-profile company-static-profile; do echo "== $t =="; git grep -I -i "$t" $(git rev-list --all) -- 2>/dev/null \| head -3; done` | No output under any token (REDACTED-PERSONAL-ACCOUNT only after Step 11b parameterisation) | Add token to substitutions.txt (longest-first); rerun filter-repo; re-verify. THIS gate -- not the enumerated file list -- is authoritative |
| 5 | pre-deploy | Employer name + REDACTED-COPYRIGHT + live IAM UserIds + home-rig topology across history (ZERO-gate); full name (REVIEW) | `git grep -I -i "REDACTED-EMPLOYER" $(git rev-list --all) 2>/dev/null \| head; git grep -I -i "REDACTED-COPYRIGHT" $(git rev-list --all) 2>/dev/null \| head; git grep -I -E "AIDA[A-Z0-9]{16}" $(git rev-list --all) 2>/dev/null \| head; git grep -I -i -e REDACTED-VPN -e "windows SSH" -e "compute node" -e "home REDACTED-CPU" $(git rev-list --all) 2>/dev/null \| head; git grep -I -i "benjamin blake" $(git rev-list --all) 2>/dev/null \| head` | ZERO output for national-archives/crown-copyright/AIDA/home-rig. The `benjamin blake` results are REVIEWED (name is intentionally public in LICENCE/attribution) -- confirm none tie the author to the deleted CV tooling or the employer | Add the missing `regex:` entry to substitutions.txt and rerun filter-repo; for a stray name-tie, scrub the phrase or purge the file |
| 6 | pre-deploy | Verify CV files + secrets docs + account verifier purged from ALL history | `git log --all --oneline -- .github/prompts/build_cv_refactored.prompt.md .github/agents/cv-reviewer.agent.md docs/platform/agent-platform-bootstrap-record.yaml docs/runbooks/policies docs/runbooks/platform-account-bootstrap.md scripts/verify_platform_account.py tests/test_verify_platform_account.py \| head` | No output (no commits touch these paths) | Add `--invert-paths --path <each>` to the Pass-1 filter-repo; re-verify |
| 7 | pre-deploy | Verify commit metadata email | `git log --all --format="%ae" \| sort -u` | Work-account email ABSENT; human identity = GH no-reply; bot authors (Copilot/github-actions/anthropic) retained | Rerun filter-repo with `--mailmap`; force-push |
| 8 | pre-deploy | Terraform validate (personal module) | `cd terraform/personal && terraform init && terraform validate 2>&1` | "Success! The configuration is valid." | Fix Terraform syntax |
| 9 | pre-deploy | Terraform plan (human gate, personal module) | `cd terraform/personal && terraform plan -var-file=terraform.personal.tfvars 2>&1 \| tail -40` | ONLY the personal-account ADDs from the Infra-Dependencies table (Glue DB, workgroup, S3, DynamoDB, 3 Iceberg tables + 3 `_current` views, OIDC provider, 2 roles). ZERO work-account resources (no Step Functions, Lambdas, EC2, monitoring) | If ANY work-account resource appears -> the personal module is not isolated; do not apply |
| 10 | post-deploy | Verify Glue DB | `aws glue get-database --name bblake_platform --profile agent_platform --query 'Database.Name'` | `"bblake_platform"` | Rerun `terraform apply` |
| 11 | post-deploy | Verify Athena workgroup | `aws athena get-work-group --work-group bblake-platform-production --profile agent_platform --query 'WorkGroup.Name'` | `"bblake-platform-production"` | Rerun `terraform apply` |
| 12 | post-deploy | Verify priority-queue view exists (preflight depends on it) | `aws athena start-query-execution --query-string "SELECT count(*) FROM bblake_platform.ops_priority_queue_current" --work-group bblake-platform-production --profile agent_platform 2>&1` | Query SUCCEEDS (0 rows OK; TABLE/VIEW must exist) | Create the `ops_priority_queue` table + view in `terraform/personal/main.tf`; re-apply |
| 13 | post-deploy | Migration dry-run (source connectivity) | `bin/venv-python -m scripts.migrate_ops_data --dry-run 2>&1 \| tail -15` | Reports source row counts; 0 writes; writes `logs/debug/migration-summary.json` | Fix profile/workgroup/database resolution |
| 14 | post-deploy | Run full migration | `bin/venv-python -m scripts.migrate_ops_data 2>&1 \| tail -20` | N recs + M decisions imported via portal; one final sync; exit 0 | Fix import errors; inspect outbox for `pending-` sentinels |
| 15 | post-deploy | Verify migrated counts via LIVE dest Athena (not summary) | `aws athena ...` query `SELECT count(*) FROM bblake_platform.ops_recommendations_current` and `..._decisions_current` (see Step 31) | dest counts EQUAL source counts in migration-summary.json | Investigate dropped rows / outbox stuck entries; re-run is refused by guard, so fix root cause |
| 16 | post-deploy | Verify ID preservation (no renumbering) | Athena: dest `rec-NNN`/`dec-NNN` id sets equal source id sets (diff the two) | Identical id sets | `_migration_int_id` not threaded on `file_rec`/`file_decision`; fix portal |
| 17 | post-deploy | Verify counter seed HARD gate (Decision 50) | `aws dynamodb get-item --table-name bblake-platform-counters --key '{"counter_name":{"S":"recommendations"}}' --profile agent_platform --query 'Item.current_value.N' --output text` (repeat for decisions) | each `>= max(migrated_id) + margin` | Re-seed via terraform/CLI before any new portal write |
| 18 | post-deploy | Verify idempotency guard | `bin/venv-python -m scripts.migrate_ops_data 2>&1 \| tail -5` (run a SECOND time) | REFUSES (dest non-empty); 0 new writes; non-zero or explicit "already migrated" exit | Add the non-empty-dest guard before writes |
| 19 | post-deploy | Verify preflight connects to personal account | `bin/venv-python -m scripts.session_preflight 2>&1 \| tail -5` | "Preflight OK", no Athena errors | Fix session_preflight constants / telemetry guards |
| 20 | post-deploy | Verify CI on ubuntu-latest + OIDC (on the POST-MERGE main push, not a PR) | After merge, observe the `main-validate` run on the `main` push event (it is `if: push`); a PR does NOT exercise OIDC since `main-validate`/AWS jobs are push-gated | `main-validate` passes; OIDC step assumes `bblake-platform-github-ci-branch` (ARN via `vars.AWS_ACCOUNT_ID`); job has `id-token: write` | Add `id-token: write`; set `vars.AWS_ACCOUNT_ID`; fix IAM trust policy / thumbprint |
| 21 | post-deploy | Verify repo is public (LAST, only after scrub verified) | `curl -s https://api.github.com/repos/benjamin-blake/agent-platform --max-time 10 \| python -c "import sys,json; print(json.load(sys.stdin).get('private','unknown'))"` | `false` | Complete the visibility change in GitHub Settings |

## Constraints

- **Opus required:** This implementation MUST be executed with Claude Opus (see Model Note above).
- No STRATEGIC plan type (executor freeze -- Decision 67 / CD.17).
- Lambda deployment deferred: `scripts/ops_writer.py` is Lambda-packaged (`_LAMBDA_SCRIPTS` in
  `build_lambda.py`). Code changes land in this plan; deploy is deferred until CD.17 reverses.
- `terraform/ec2_runner.tf` is NOT modified to remove resource definitions. CD.21 mandates
  retention as an architectural-evolution artefact. Only a deprecation header comment is added.
- **Single Portal Invariant (Decision 69):** the migration WRITES exclusively through
  `ops_data_portal.file_rec` / `file_decision`. It MUST NOT call `OpsWriter().write()` directly.
  The earlier "Direct-OpsWriter ETL" idea was BLOCKED by decision-scout as a Decision-75 frame-lock
  ("foreign warehouse" is still a warehouse -> warehouse->warehouse replay is the exact path the
  invariant guards). The READ side is a separate, read-only boto3 work-profile Athena query
  against the `*_current` views; reading a foreign warehouse is not a portal-write concern.
- **No local cache as a write source:** the migration MUST NOT *read* `logs/.recommendations-log.jsonl`
  or any `logs/` file as INPUT (Decision 69, warehouse-as-source-of-truth). Note the portal's own
  write-through to the local cache (downstream of the write) is allowed and expected -- the
  acceptance test asserts the migration never *reads* `logs/` as input, NOT that the portal never
  touches it.
- **Cross-account targeting via env/constants, not a `profile=` kwarg.** The portal resolves its
  target account from module constants + `AWS_PROFILE`, NOT from a per-call `profile=` argument
  (which only redirects the DynamoDB id allocator). The write phase therefore runs with the
  repointed constants AND `AWS_PROFILE=agent_platform`. Do NOT call `ops_data_portal.sync(profile=...)`
  -- that signature does not exist (`sync(tables=None)` only). Drain the SOURCE outbox BEFORE the
  constant flip while constants still point at the work account.
- **ID preservation for BOTH tables.** `file_decision` already has `_migration_int_id`; a symmetric
  `_migration_int_id` is added to `file_rec`. Both bypass `_next_id` so original `rec-NNN` / `dec-NNN`
  IDs survive (keeps `dependencies` / `related_decisions` / priority-queue FKs intact). Counters are
  then seeded above the migrated max (HARD gate) so future allocations cannot collide.
- **Per-row sync suppressed during bulk import.** A `_skip_sync` flag on `file_rec`/`file_decision`
  defers the per-row `_sync_table()` (compact+refresh+pull); the migration calls `sync()` exactly
  ONCE at the end. Still 100% through the portal.
- **CD.19 (import timestamp/provenance) consciously NOT implemented (greenfield).** `source` is
  PRESERVED verbatim (every migrated value is already in `source_registry.yaml`, so `validate_source`
  passes -- overwriting to `import-bootstrap` would instead REQUIRE a registry entry and is the
  harder path). `created_timestamp` preserved; `last_updated_timestamp` = import time (portal default).
  The freshness-flood CD.19 guards against has no baseline to pollute in an empty personal warehouse;
  if a staleness curator later needs true age it can read the preserved `created_timestamp`. CD.19 is
  unratified and T2.2-scoped; we are explicitly out of that sequence.
- **Idempotency:** the migration REFUSES to run if the destination `_current` view is non-empty
  (or skips ids already present), so a second run cannot append duplicates / trigger SCD2 resurrection.
- Telemetry tables and `ops_session_log` / `ops_execution_plans` are NOT migrated. Entries for
  these in `sync_ops._TABLE_TO_VIEW` and `_TABLE_TO_LOCAL` must be removed to prevent
  silent query failures on every `sync_ops.pull`.
- rec-725 (Terraform state misalignment in work account) is not addressed here. EC2 runner is
  terminated via AWS CLI, not `terraform destroy`.
- No rescue agents or workaround loops (Decision 55).

## Context

- **Decision 67**: Lambda deployment and STRATEGIC plan execution deferred pending CD.17 reversal.
  `ops_writer.py` changes require a DEFERRED deploy step.
- **Decision 68**: Self-hosted EC2 runner as canonical CI environment -- superseded by this plan.
  CD.21 ratifies the retirement and mandates retaining `ec2_runner.tf` as an artefact.
- **Decision 69**: Single Portal Invariant -- all ops writes go through `ops_data_portal`.
  Migration writes via `file_rec` / `file_decision` exclusively; never `OpsWriter.write()` directly.
  Re-confirmed by decision-scout (2026-05-28): the portal approach COMPLIES; the alternative
  direct-`OpsWriter` ETL was BLOCKED as a Decision-75 frame-lock.
- **Decision 75 (frame-lock)**: the rejected "foreign-warehouse ETL" rationale is the textbook
  case Decision 75 names. Recorded here so the reversal is legible: we consciously challenged the
  frame and returned to the Single Portal.
- **Decision 50**: Append-only Iceberg ops store. Migration imports as fresh inserts (one per id);
  preserves `created_timestamp`; `last_updated_timestamp = now`. Counter-seed-above-max is a HARD
  acceptance gate (a too-low seed could later collide with a preserved id and SCD2-merge two recs).
- **Decision 56**: SCD2 schema. `last_updated_timestamp` (PARTITION BY id ORDER BY ... DESC) is the
  version key; reading the source `*_current` views already gives latest-per-id. Migration preserves
  `created_timestamp` and lets the portal stamp `last_updated_timestamp`.
- **CD.19 (unratified, T2.2-scoped)**: import timestamp/provenance policy. Consciously NOT
  implemented -- `source` preserved verbatim, no `import-bootstrap` tag, no freshness-exclusion
  wiring. Rationale in Constraints (greenfield, no baseline). Revisit if CD.19 ratifies and a
  staleness curator is built.
- **CD.16 / Decision 67**: `ops_writer.py` is Lambda-packaged -> its constant change carries the
  `DEFERRED: build_lambda.py --deploy` marker (Step 33). `ops_data_portal.py` is the agent-side
  surface, NOT Lambda-packaged, so adding `_migration_int_id`/`_skip_sync` there does NOT trigger
  per-Lambda deploy gating.
- **Decision 36 vs `terraform/personal/oidc.tf`**: Decision 36's "no IAM users / no external OIDC" was
  scoped to the WORK account's SCPs. The personal account (REDACTED-PERSONAL-ACCOUNT) has no such SCP. CD.21
  ratifies the OIDC + hosted-runner migration. `oidc.tf` is CD.21 groundwork, NOT a Decision 36
  violation -- but VP step 1 actively probes the personal account first (before any irreversible
  action) to confirm the assumption.
- **Decision 60**: Two-tier validation architecture. The OIDC credential step added to CI YAML
  must NOT be added to the fast tier (`--pre`). Fast tier remains lint/format/mypy only.
- **Decision 71**: cc-scheduled-agents ratified `[self-hosted, linux]` as runner. This plan
  supersedes that rationale for the public-repo GitHub-hosted runner; note in AGENTS.md.
- **Decision 72**: Branch protection note -- public repo with GitHub-hosted runners unblocks
  native GitHub branch protection. Consider enabling in a follow-on session (T2.12).
- **Decision 74**: `ci-rca.yml` contains a pinned Claude Code CLI install and `workflow_dispatch`
  input. Both MUST be preserved when changing `runs-on`.
- **CD.21**: Ratifies self-hosted runner retirement. Mandates `ec2_runner.tf` retained as an
  architectural-evolution artefact -- a deprecation header comment ONLY, no resource removal and NO
  `count` guard. (Under the separate-module architecture the personal infra lives in
  `terraform/personal/`; the work-account root holding `ec2_runner.tf` is no longer applied, so its
  unconditional resources are never planned against the personal account. The earlier `count=0`
  rationale was a leftover from a single-module draft and is void.) This matches the Scope table and
  Step 9.
- **CD.20**: Gates the public flip (T2.13) on T2.12 (GHAS, branch protection, CodeQL, fork-PR
  policy, Dependabot). This plan bypasses T2.12 via `user_explicit_out_of_scope`. A DEFERRED
  step (Step 33) records this security debt. The human explicitly accepts this tradeoff.
- **CD.20 curated-surface deviation (human-accepted)**: CD.20 also envisions the public surface as a
  CURATED set with operational data NOT exported. The human has explicitly chosen to PUBLISH the full
  operational journal (`docs/DECISIONS.md`, `SESSION_LOG*`, `logs/*.jsonl`, ~80 `docs/plans/PLAN-*.md`)
  as the portfolio's substance. This is a conscious deviation from CD.20's curated-surface intent,
  accepted for the showcase value. The journal is still subject to the full PII/secret scrub
  (Phase A) -- publishing the journal does NOT mean publishing secrets; the breakglass/IAM docs are
  purged regardless (Step 3 Pass 1).
- **rec-725**: Work-account Terraform state misalignment (113 missing resources). Out of scope.
  Personal account Terraform starts from a clean state.
- **INTENT-aws-migration-platform-evolution.md**: The full naming-convention overhaul (T0.15,
  T2.0, T2.15, T2.16) is deferred. Resource names chosen here (`bblake_platform` Glue DB,
  `bblake-platform-production` workgroup) are aligned with the INTENT's Part 3 naming convention.
- **Personal account setup**: Account REDACTED-PERSONAL-ACCOUNT, SSO profile `agent_platform`, region
  `eu-west-2`. Personal-account infra lives in the NEW isolated `terraform/personal/` root module
  with its OWN `aws` provider + state (NOT the work-account root's default/`aws.platform`
  providers). `terraform/personal/terraform.personal.tfvars` (gitignored) supplies the account ID
  and profile for apply (see Steps 7-12).
- **OIDC trust policy timing**: OIDC is created fresh in the personal account after the GitHub
  repo rename to `agent-platform`. The branch-role sub claim is scoped to
  `ref:refs/heads/main` + `ref:refs/heads/agent/*` (NOT a bare `refs/heads/*`), with
  `StringEquals` on `aud=sts.amazonaws.com`. A separate read-only role covers PR
  (`ref:refs/pull/*`) workflows. Every CI job that assumes a role also needs `id-token: write`
  (ci.yml currently has only `contents: read`). VP step 1 probes OIDC feasibility BEFORE any
  irreversible action.
- **History rewrite sequencing**: Steps 1-6 (manual, pre-branch) rewrite history and force-push
  before any branch-based code changes. After force-push, re-checkout the branch:
  `git checkout agent/public-migration`.
- **Split-brain window (Decision 67)**: After this plan merges, local code references
  `agent_platform` / `bblake_platform` but the work-account Lambda continues running with old
  constants until CD.17 reverses. No risk: work-account Lambda scheduled agents are already
  disabled (AGENTS.md runbook, May 2026).
- **CI gap during migration**: The EC2 runner is terminated in Step 4 (pre-branch) but CI
  workflows still reference `[self-hosted, linux]` until Step 30 merges. The migration PR's own
  CI jobs will fail due to missing runner. This is expected and acceptable. Merge the PR via
  GitHub UI (bypassing the failed runner check) or via `gh pr merge --admin`.
- **Phase A execution record (2026-05-28) -- OIDC gate + provisioning-profile correction:**
  - OIDC feasibility gate PASSED. VP step 1 / Step 4a as written probes `--profile agent_platform`
    (the runtime `PlatformDev` role), which has NO IAM permissions and returns an *identity-based*
    AccessDenied (NOT an SCP explicit-deny) -- a false abort. Re-probed with `agent_platform_admin`
    (assumes role `PlatformAdmin`, account REDACTED-PERSONAL-ACCOUNT): `list-open-id-connect-providers` returns
    `[]`, exit 0. OIDC is creatable; the catastrophic STOP condition does not apply. Correct the
    probe profile to `agent_platform_admin` if VP step 1 is re-run.
  - **Terraform provisioning profile:** Phase B `terraform apply` creates IAM roles + the OIDC
    provider, so it MUST run under `agent_platform_admin`, NOT `agent_platform`. In Step 11
    `terraform.personal.tfvars`, set `aws_profile = "agent_platform_admin"` (provisioning). The
    RUNTIME profile stays `agent_platform` (constant sweep Step 15; migration Step 31 via
    `AWS_PROFILE=agent_platform`). OPEN for Phase C: confirm `PlatformDev` has Athena query /
    S3 read-write / DynamoDB get-update / Glue get runtime perms before the migration runs.
  - **Step 5 counter maxes (read 2026-05-28, work account `agent-platform-counters`):**
    recommendations=944, decisions=81. Step 7 seed (floor, +1000): recommendations=1944,
    decisions=1081. Step 13c re-asserts counter >= max(migrated_id)+margin post-migration.
  - **Phase A EXECUTED VIA SCORCHED EARTH (2026-05-28) -- supersedes Steps 1-6 below:**
    The filter-repo-on-history approach (Steps 2-3) was attempted and ABANDONED. Regex
    substitutions had case-sensitivity gaps (e.g. `[Tt]ailscale` missed `TAILSCALE_AUTHKEY` and
    `Tailnet`), and the history (919 commits, 24 branches) was too dense with personal / topology /
    employer prose for reliable token-scrubbing ("music production" and "Ryzen 9 9950X" had no
    patterns at all). Instead the repo was collapsed to a SINGLE orphan commit:
    - `git checkout --orphan` -> one "Initial commit" (`4bd5850`); author = committer =
      `217728084+benjamin-blake@users.noreply.github.com` (human identity; bot authorships dropped
      with the deleted history; AI involvement kept via a `Co-Authored-By: Claude` trailer).
    - DELETED from the tree entirely (43 files): `docs/plans/briefings/`, `docs/audit-reports/`,
      `docs/plans/PLAN-platform-extraction-strategy.md`, `docs/plans/PLAN-t03-pattern-b-agent-auth.md`,
      `docs/plans/PLAN-bedrock-migration.md`.
    - `substitutions.txt` (gitignored) expanded to case-insensitive employer/copyright/tailscale/
      openssh/home-rig rules + a broad `regex:ml-trading-[A-Za-z0-9_-]+` + Tailnet / Ryzen / "music
      production" / gmail->no-reply, applied via `git filter-repo --replace-text` over the one commit.
    - VERIFIED clean (whole-tree `git grep`): zero hits for employer name, account IDs, work
      profiles, every `ml-trading-*` variant, Tailscale/Tailnet/Ryzen/OpenSSH/home-rig, "music
      production", emails, and live access keys (AKIA/AIDA/ASIA). `git log --format=%ae` = only the
      no-reply. Pre-scrub backup kept at `../mlsbx-prescrub-backup.git` (local, off-repo).
  - **Step 4b DONE:** EC2 runner `ml-trading-system-runner` (`i-04b1aff54bd174f68`) terminated
    2026-05-28.
  - **Step 6 REPLACED by repo recreate (2026-05-28):** force-push + rename was replaced by
    delete-and-recreate -- safer, because GitHub keeps old `refs/pull/*` commits fetchable after a
    force-push. A fresh PRIVATE repo `benjamin-blake/agent-platform` was created and the single clean
    commit pushed (`main` + `agent/public-migration` both at `4bd5850`); the old
    `machine-learning-sandbox` repo is deleted. OIDC sub claims already target `agent-platform`, so
    NO rename step remains anywhere in the plan.
  - **PHASE A IS COMPLETE.** The next `/implement` session starts at Phase B (Step 7). The repo stays
    PRIVATE until Phase G / Step 32. OPEN prerequisite before the Step 31 migration: confirm
    `agent_platform`/PlatformDev has Athena query / S3 read-write / DynamoDB get-update / Glue get
    runtime perms (provisioning still uses `agent_platform_admin`).

## Pre-Implementation Checklist

- [ ] Branch confirmed not on `main` (branch: `agent/public-migration`)
- [ ] Claude Opus confirmed as active model
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (focus: Decisions 36, 50, 56, 60, 61, 67, 68, 69, 71, 72, 74, 75)
- [ ] `docs/ROADMAP-PLATFORM.yaml` CD-series read (focus: CD.16, CD.19, CD.20, CD.21)
- [ ] All files in Scope table located and readable
- [ ] `agent_platform` SSO profile working: `aws sts get-caller-identity --profile agent_platform`
- [ ] `company-aws-profile` SSO profile working: `aws sts get-caller-identity --profile company-aws-profile`
- [ ] Acceptance Criteria understood and verifiable
- [ ] Steps H1-H6 (pre-branch manual steps) confirmed completed by human before Step 7
- [ ] GitHub user/org slug confirmed: the plan hardcodes `benjamin-blake` in `gh api` calls, the
  OIDC sub claims, and the public URL -- verify it matches the actual GitHub login before the
  irreversible rename/force-push

## Ordered Execution Steps

### Phase A: Pre-Branch History Scrub -- COMPLETE 2026-05-28 (DO NOT RE-RUN)

> **Phase A was executed via a SCORCHED-EARTH squash, not the filter-repo-on-history steps below.**
> See "Phase A EXECUTED VIA SCORCHED EARTH" in the Context section above for what actually happened.
> Steps 1-6 in this subsection are SUPERSEDED and retained only for historical context. A fresh
> `/implement` session should START AT PHASE B (Step 7).

**Step 1 -- Prepare `substitutions.txt` and update `.gitignore`**

Create `substitutions.txt` in the repo root with the patterns below. Add `substitutions.txt` to
`.gitignore` (it contains a live email address; must never be committed). Also add
`.claude/scheduled_tasks.lock` and `terraform/**/terraform.personal.tfvars` to `.gitignore`.

`substitutions.txt` patterns (`literal==>replacement`, one per line). **Order matters: longest /
most-specific patterns FIRST** so e.g. `agent-platform-production` is consumed before a bare
`agent-platform` rule. `git filter-repo --replace-text` supports `literal:`/`regex:` prefixes;
bare lines are literal:

```
REDACTED-ACCOUNT-ID==>REDACTED-ACCOUNT-ID
REDACTED-PERSONAL-ACCOUNT==>REDACTED-PERSONAL-ACCOUNT
REDACTED-EMPLOYER==>REDACTED-EMPLOYER
agent-platform==>agent-platform
agent-platform-svc==>agent-platform-svc
bblake-platform==>bblake-platform
agent-platform==>agent-platform
company-aws-profile==>company-aws-profile
company-aws-profile-staging==>company-aws-profile-staging
company-aws-profile-production==>company-aws-profile-production
personal-bedrock-profile==>personal-bedrock-profile
company-admin-profile==>company-admin-profile
company-static-profile==>company-static-profile
REDACTED-EMPLOYER==>REDACTED-EMPLOYER
regex:[Nn]ational [Aa]rchives==>REDACTED-EMPLOYER
regex:Crown [Cc]opyright==>REDACTED-COPYRIGHT
regex:AIDA[A-Z0-9]{16}==>REDACTED-IAM-USERID
regex:[Tt]ailscale==>REDACTED-VPN
regex:SSH==>SSH
regex:[Hh]ome (Windows |REDACTED-CPU[^ ]* |REDACTED-CPU )?[Rr]ig==>compute node
INSERT_WORK_EMAIL_HERE==>217728084+benjamin-blake@users.noreply.github.com
```

Notes:
- `REDACTED-EMPLOYER` (bare host, NOT `REDACTED-EMPLOYER.awsapps.com/start`) so the partial-path
  form `REDACTED-EMPLOYER.awsapps.com/start/#/?tab=accounts` is fully caught and the verification
  grep for `REDACTED-EMPLOYER` can actually reach zero.
- `agent-platform` and `bblake-platform` are employer-account RESOURCE names (164+ occurrences
  across 40+ tracked files, incl. `logs/runs/*.json`); they MUST be in the rewrite, not just HEAD.
- `REDACTED-EMPLOYER` plus the regex catch the plain-English employer name in prose (README,
  GETTING_STARTED) that the underscore form misses. `Crown [Cc]opyright` catches the `LICENCE`
  da-template header (user confirmed this is their own work, not REDACTED-COPYRIGHT).
- `agent-platform-svc` is a SEPARATE employer IAM-user name -- it is NOT a substring of
  `agent-platform`, so it needs its own rule (it appears in published `docs/plans/PLAN-*.md`).
  `company-admin-profile` and `company-static-profile` are personal AWS profile names (siblings of `personal-bedrock-profile`).
  `AIDA[A-Z0-9]{16}` redacts LIVE IAM UserIds (e.g. the breakglass user) wherever they appear.
- `regex:[Nn]ational [Aa]rchives` (no required "the") catches the titlecase, lowercase, AND
  "The REDACTED-EMPLOYER" forms in ONE rule -- including `GETTING_STARTED.md:125` ("To National
  Archives AWS account") that a "the"-requiring regex or a case-sensitive literal would miss.
- **Home-rig / private-network topology** (`REDACTED-VPN`, `SSH`, "Home Windows/REDACTED-CPU rig")
  appears in `AGENTS.md`, `docs/ROADMAP-PLATFORM.yaml` (CD.3/OQ.3), and several
  `docs/plans/briefings/*` + `docs/audit-reports/*` files. The three home-rig regexes scrub it across
  ALL of them in BOTH history and HEAD (`filter-repo --replace-text` rewrites the tip tree too), so
  no per-file edit is needed beyond the AGENTS.md sentence rewrite (Step 25) for readability.
- **The author's full name is NOT a token** and is intentionally KEPT (LICENCE attribution, README
  author). The verification name-grep is therefore a REVIEW check, not a zero-gate: ensure no
  occurrence ties the author to the DELETED CV tooling or the employer. The
  `logs/.customizations-manifest.json` CV entry is edited at HEAD (scope) and its history blob's
  "bespoke CVs" phrasing is neutralised by a targeted substitution if it survives.
- **Scope-discovery grep (run BEFORE finalising substitutions).** Do not rely on the enumerated file
  list -- run `grep -rIn -e REDACTED-ACCOUNT-ID -e REDACTED-PERSONAL-ACCOUNT -e agent-platform -e agent-platform-svc
  -e bblake-platform -e company-aws-profile -e personal-bedrock-profile -e company-admin-profile -e company-static-profile
  -e REDACTED-EMPLOYER -e "AIDA" .` over the working tree and reconcile EVERY hit: either it is a
  doc/history blob the substitution scrubs, a functional file parameterised in Step 11b, or a file
  added to scope. The all-refs verification gate (Step 3 / VP step 4) is the authoritative check.
- **`REDACTED-PERSONAL-ACCOUNT` (personal account) is the LIVE target** -- Terraform, OIDC, and CI must still
  reference it. To scrub the literal WITHOUT breaking functionality, the functional files are
  PARAMETERISED in Step 11b BEFORE relying on substitution: Terraform reads `platform_account_id`
  from the gitignored `terraform.personal.tfvars`; workflows read a GitHub repo variable
  `vars.AWS_ACCOUNT_ID`. After parameterisation no tracked file contains the literal in a
  load-bearing way, so this substitution safely scrubs the remaining doc/history occurrences.
  `personal-bedrock-profile` is scrubbed in docs; the active profile name lives in gitignored config.
- The CV files AND the operational-secret docs (`docs/platform/agent-platform-bootstrap-record.yaml`,
  `docs/runbooks/policies/*`, `docs/runbooks/platform-account-bootstrap.md`) are NOT scrubbed by
  substitution -- they are DELETED FROM ALL HISTORY via the `--invert-paths` pass in Step 3 (their
  breakglass ARNs / employer content would otherwise remain recoverable in history).

The human must replace `INSERT_WORK_EMAIL_HERE` with their actual work email address before
running filter-repo.

Create `~/.gitconfig-mailmap` with contents:
```
Benjamin Blake <217728084+benjamin-blake@users.noreply.github.com> <INSERT_WORK_EMAIL_HERE>
```
(Replace `INSERT_WORK_EMAIL_HERE` with actual work email.)

**Step 2 -- (Human) Scan history**

Install tools if needed:
```bash
# gitleaks (Go binary -- NOT pip)
# Linux/WSL: wget https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz && tar -xzf gitleaks*.tar.gz && sudo mv gitleaks /usr/local/bin/
# Windows: winget install gitleaks

# truffleHog
pip install trufflehog3   # or: brew install truffleHog
```

Run scans:
```bash
gitleaks detect --source . --log-opts="--all" 2>&1 | tee gitleaks-report.txt
trufflehog git file://. --only-verified 2>&1 | tee trufflehog-report.txt
```

Review both reports. Add any unaddressed sensitive patterns to `substitutions.txt`.

**Step 3 -- (Human) Rewrite history with git filter-repo**

```bash
# Install if needed: pip install git-filter-repo

# Pass 1: purge CV files, operational-secret docs, AND the one-time account verifier (carries the
# live breakglass IAM UserId) from ALL history (blob deletion)
git filter-repo \
  --path .github/prompts/build_cv_refactored.prompt.md \
  --path .github/agents/cv-reviewer.agent.md \
  --path docs/platform/agent-platform-bootstrap-record.yaml \
  --path docs/runbooks/policies \
  --path docs/runbooks/platform-account-bootstrap.md \
  --path scripts/verify_platform_account.py \
  --path tests/test_verify_platform_account.py \
  --invert-paths --force

# Pass 2: scrub blob content + rewrite commit author/committer identity
git filter-repo \
  --replace-text substitutions.txt \
  --mailmap ~/.gitconfig-mailmap \
  --force
```

Verify the rewrite -- scan ALL blobs in ALL refs, NOT by file extension (the repo tracks 565+
`logs/runs/*.json` and `.jsonl` cache files that an extension filter would miss):
```bash
# AUTHORITATIVE GATE: every sensitive token must be absent from every blob in every ref.
for t in REDACTED-ACCOUNT-ID REDACTED-PERSONAL-ACCOUNT REDACTED-EMPLOYER agent-platform agent-platform-svc \
         bblake-platform company-aws-profile personal-bedrock-profile company-admin-profile company-static-profile; do
  echo "== $t =="
  git grep -I -i "$t" $(git rev-list --all) -- 2>/dev/null | head -3
done
# Case-insensitive employer name + REDACTED-COPYRIGHT + live IAM UserIds
git grep -I -i "REDACTED-EMPLOYER" $(git rev-list --all) -- 2>/dev/null | head -5
git grep -I -i "REDACTED-COPYRIGHT" $(git rev-list --all) -- 2>/dev/null | head -5
git grep -I -E "AIDA[A-Z0-9]{16}" $(git rev-list --all) -- 2>/dev/null | head -5
# Home-rig / private-network topology (ZERO-gate)
git grep -I -i -e "REDACTED-VPN" -e "windows SSH" -e "compute node" -e "home REDACTED-CPU" \
  $(git rev-list --all) -- 2>/dev/null | head -5
# Full name (REVIEW, not zero-gate): name is intentionally public in LICENCE/attribution.
# Confirm no occurrence ties the author to the deleted CV tooling or the employer.
git grep -I -i "benjamin blake" $(git rev-list --all) -- 2>/dev/null | head -10
# The token loop + national-archives/crown-copyright/AIDA/home-rig checks above must be EMPTY.

# CV files, secrets docs, AND the account verifier gone from all history
git log --all --oneline -- .github/prompts/build_cv_refactored.prompt.md \
  .github/agents/cv-reviewer.agent.md docs/platform/agent-platform-bootstrap-record.yaml \
  docs/runbooks/policies docs/runbooks/platform-account-bootstrap.md \
  scripts/verify_platform_account.py tests/test_verify_platform_account.py   # should be empty

# Commit metadata
git log --all --format="%ae" | sort -u   # work email gone; expect GH no-reply + retained bot authors

# Belt-and-braces secret scan over all refs
gitleaks detect --source . --log-opts="--all" 2>&1 | tail -20
```
If ANY token still matches, add it to `substitutions.txt` (longest-first) and re-run Pass 2.

**Step 4 -- (Human) OIDC feasibility gate, THEN terminate EC2 runner**

**4a -- OIDC probe (MUST pass before anything irreversible).** The whole hosted-runner approach
depends on OIDC being creatable in the personal account. Probe it BEFORE terminating the runner so
we can still fall back if it is denied. Note: do NOT use `iam:simulate-principal-policy` -- it
evaluates the caller's IAM identity policy, not the account SCP, and would give false confidence.

```bash
aws iam list-open-id-connect-providers --profile agent_platform; echo "exit=$?"
# exit=0 -> the IAM/OIDC surface is reachable and not SCP-denied. Proceed.
# AccessDenied / non-zero -> STOP. Do NOT rewrite history or terminate the runner.
#   Escalate: CD.21's OIDC assumption is invalid for this account.
```

History rewrite (Step 3) and runner termination (4b) are effectively irreversible; both are gated on
4a passing.

**4b -- Terminate EC2 runner and cancel GitHub registration**

```bash
# Get instance ID
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=agent-platform-runner" \
  --profile company-aws-profile \
  --query "Reservations[].Instances[].InstanceId" \
  --output text

# Terminate
aws ec2 terminate-instances --instance-ids <INSTANCE_ID> --profile company-aws-profile

# Get runner ID (note: repo name is still agent-platform at this point)
gh api repos/benjamin-blake/agent-platform/actions/runners \
  --jq '.runners[] | "\(.id) \(.name)"'

gh api --method DELETE \
  repos/benjamin-blake/agent-platform/actions/runners/<RUNNER_ID>
```

**Step 5 -- (Human) Read work-account DynamoDB counter max values (required for Step 7)**

```bash
# Get current max for recommendations counter
aws dynamodb get-item \
  --table-name agent-platform-counters \
  --key '{"counter_name":{"S":"recommendations"}}' \
  --profile company-aws-profile \
  --query 'Item.current_value.N' \
  --output text

# Get current max for decisions counter
aws dynamodb get-item \
  --table-name agent-platform-counters \
  --key '{"counter_name":{"S":"decisions"}}' \
  --profile company-aws-profile \
  --query 'Item.current_value.N' \
  --output text
```

Record these values -- they are required inputs for the Terraform seed in Step 7. The personal
account table must be seeded at `(work_account_max + 1000)` for each counter. This ensures the
next personal-account ID allocation is at least 1000 above any ID that could be allocated in
the work account during the migration window.

**Step 6 -- (Human) Reduce force-push blast radius, force-push, rename (repo stays PRIVATE)**

History rewrite invalidates every existing ref SHA. Old objects can linger on GitHub via open-PR
refs and cached views, so close/delete them BEFORE force-pushing:

```bash
# Close all open PRs (their refs/pull/* pin pre-scrub SHAs) and delete stale remote branches
gh pr list --state open --json number --jq '.[].number' | while read n; do gh pr close "$n"; done
git push origin --delete $(git branch -r | grep -v 'origin/main\|origin/HEAD' | sed 's#origin/##') 2>/dev/null || true

# Force-push the rewritten history
git push origin main --force
git push origin agent/public-migration --force

# Rename on GitHub: Settings > General > Repository name > agent-platform > Rename.
# Update remote URL after rename
git remote set-url origin https://github.com/benjamin-blake/agent-platform.git
git fetch origin
git checkout agent/public-migration

# Confirm there are no forks holding pre-scrub history (private repos can't be forked externally,
# so this should be zero if the repo was always private):
gh api repos/benjamin-blake/agent-platform --jq '.forks_count'   # expect 0
```

**CRITICAL: the repo MUST remain PRIVATE through the rename and until the full-history scrub is
verified on the merged `main` (Step 32 is the ONLY place visibility flips).** The rename does NOT
change visibility; do not treat it as the public milestone.

Verify: `git remote -v` shows `agent-platform`; repo is still private
(`gh api repos/benjamin-blake/agent-platform --jq '.private'` -> `true`).

---

### Phase B: Terraform -- Personal Account Infrastructure (SEPARATE root module)

**Why a separate module:** the existing `terraform/` root repoints its DEFAULT `aws` provider via
`terraform.personal.tfvars`, and only ~8 of ~137 resources use the `aws.platform` alias -- the rest
(S3, Step Functions, Lambdas, monitoring, iceberg_tables, dynamodb, cost_monitoring) use the default
provider. Applying that root against the personal account would try to CREATE ~120 work-account
resources there. So ALL personal-account infra goes in a NEW, isolated root module `terraform/personal/`
with its own provider + state; the work-account root is left untouched (and no longer applied).

**Step 7 -- Create `terraform/personal/main.tf`**

Own provider: `provider "aws" { region = var.aws_region, profile = var.aws_profile }` (personal
account REDACTED-PERSONAL-ACCOUNT, profile `agent_platform_admin` -- PROVISIONING profile; apply creates IAM
roles + the OIDC provider, which needs PlatformAdmin, NOT the permissionless PlatformDev runtime
role) and `terraform { backend "local" {} }` (or an S3
backend in the personal data-lake bucket). Create:

- `aws_glue_catalog_database.bblake_platform` -- name `bblake_platform`
- `aws_athena_workgroup.bblake_platform_production` -- name `bblake-platform-production`,
  engine v3, S3 output `s3://bblake-platform-data-lake/athena/prod-results/`
- `aws_s3_bucket.bblake_platform_data_lake` -- name `bblake-platform-data-lake`; versioning
  enabled, AES256 encryption, public access blocked
- `aws_dynamodb_table.bblake_platform_counters` -- name `bblake-platform-counters`,
  `PAY_PER_REQUEST`, hash key `counter_name` (String). Seed via `aws_dynamodb_table_item`
  (create-only, so it cannot LOWER an existing counter):
  - `recommendations` = (work recs max from Step 5) + 1000
  - `decisions` = (work decisions max from Step 5) + 1000
  Record seed values in a comment. NOTE: this is a floor; Step 13c re-asserts `counter >=
  max(migrated_id)+margin` AFTER the migration in case the actual migrated max exceeds the Step-5 read.
- Iceberg TABLES `ops_recommendations`, `ops_decisions`, `ops_priority_queue` (mirror the work-account
  `iceberg_tables.tf` schemas) AND their `_current` views (`ops_recommendations_current`,
  `ops_decisions_current`, `ops_priority_queue_current`). Create the views in Terraform explicitly --
  do NOT rely on the first portal write to create them, because the migration's idempotency guard
  (Step 13b) queries `ops_recommendations_current` BEFORE the first write; on a greenfield account
  that view must already exist (returning 0 rows) or the guard query errors. `read_priority_queue()`
  also hard-exits (Decision 61) if `ops_priority_queue_current` is absent. Use the
  `ops_writer._refresh_view` SQL verbatim, retargeted to `bblake_platform`; the priority-queue view
  selects from the `ops_priority_queue` TABLE (NOT `ops_recommendations`).

**Step 8 -- Create `terraform/personal/oidc.tf`**

- `aws_iam_openid_connect_provider.github_actions` -- URL
  `https://token.actions.githubusercontent.com`, thumbprint
  `6938fd4d98bab03faadb97b34396831e3780aea1`, client_id_list `["sts.amazonaws.com"]`
- `aws_iam_role.github_ci_branch` -- name `bblake-platform-github-ci-branch`. Trust policy:
  `sts:AssumeRoleWithWebIdentity` with `StringEquals` on `aud = sts.amazonaws.com` AND `StringLike`
  on `:sub` matching ONLY `repo:benjamin-blake/agent-platform:ref:refs/heads/main` and
  `...:ref:refs/heads/agent/*` (a list, NOT a bare `refs/heads/*`). Used by branch/push workflows.
  Also set the repo fork-PR-approval policy ("require approval for all outside collaborators").
- `aws_iam_role.github_ci_pr` -- name `bblake-platform-github-ci-pr`. Sub matches
  `...:ref:refs/pull/*`. READ-ONLY perms (S3:GetObject, Athena read, Glue GetDatabase/GetTable).
- `aws_iam_role_policy.github_ci_branch` -- inline least-privilege policy (use the work-account
  `aws_iam_policy.github_runner_ci` as a template, retargeted to personal-account ARNs):
  `athena:StartQueryExecution/GetQueryExecution/GetQueryResults/GetWorkGroup` on
  `bblake-platform-production`; `s3:GetObject/PutObject/ListBucket` on `bblake-platform-data-lake`;
  `dynamodb:GetItem/UpdateItem` on `bblake-platform-counters`;
  `glue:GetDatabase/GetTable/GetPartitions`. NO AdministratorAccess / wildcards.
- `aws_iam_role.github_ci_branch` ARN is referenced by workflows via the GitHub repo variable
  `vars.AWS_ACCOUNT_ID` (Step 11b), NOT a committed literal.

**Step 9 -- Modify `terraform/ec2_runner.tf` (work root) + remove personal-account default**

- `terraform/ec2_runner.tf`: add ONLY a deprecation header (CD.21). No `count` guard is needed --
  this file is in the WORK-account root, which is no longer applied (the personal module is separate).
  ```hcl
  # DEPRECATED 2026-05-28 -- CD.21
  # Self-hosted EC2 runner retired; CI now uses GitHub-hosted runners + OIDC (personal account).
  # Retained as an architectural-evolution artefact per CD.21. The work-account root is no longer
  # applied; to fully decommission run terraform destroy against the work-account state later.
  ```
- `terraform/variables.tf` (work root): REMOVE the committed `default = "REDACTED-PERSONAL-ACCOUNT"` from
  `platform_account_id` so the personal account ID is not a committed literal (it survives only in
  the gitignored personal tfvars). If the var is unused in the work root after the personal split,
  delete it.

**Step 10 -- Modify `terraform/CLAUDE.md`**

Update `Account: REDACTED-ACCOUNT-ID (sandbox)` -> `REDACTED-PERSONAL-ACCOUNT (personal)`, `Profile: company-aws-profile`
-> `agent_platform`. Remove the "Company SCPs block IAM/OIDC" note (work-account-only). Note the new
`terraform/personal/` module as the personal-account root.

**Step 11 -- Create `terraform/personal/terraform.personal.tfvars` (gitignored)**

```hcl
aws_region  = "eu-west-2"
aws_profile = "agent_platform_admin"  # PROVISIONING role (PlatformAdmin); runtime stays agent_platform
account_id  = "REDACTED-PERSONAL-ACCOUNT"
owner_email = "217728084+benjamin-blake@users.noreply.github.com"
```

`terraform/personal/variables.tf` declares these with NO default for `account_id` (so the literal is
never committed). Confirm the tfvars is gitignored: `git check-ignore -v
terraform/personal/terraform.personal.tfvars` (Step 1 added `terraform/**/terraform.personal.tfvars`).

**Step 11b -- Parameterise the account ID in workflow ARNs (GitHub repo variable)**

So no workflow file commits the `REDACTED-PERSONAL-ACCOUNT` literal: in GitHub repo Settings -> Secrets and
variables -> Actions -> Variables, add repository variable `AWS_ACCOUNT_ID = REDACTED-PERSONAL-ACCOUNT`. In every
workflow OIDC step, reference the role as
`arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/bblake-platform-github-ci-branch` (or `-pr`). After
this, the `REDACTED-PERSONAL-ACCOUNT==>REDACTED-PERSONAL-ACCOUNT` substitution (Step 1) can safely scrub all
remaining doc/history occurrences without breaking CI.

**Step 12 -- Run Terraform plan (human gate) and apply -- INSIDE `terraform/personal/`**

```bash
cd terraform/personal
terraform init
terraform validate
terraform plan -var-file=terraform.personal.tfvars 2>&1 | tee /tmp/tf-plan-personal.txt
```

Present the plan to the human. It must show ONLY the Infrastructure-Dependencies-table resources and
NOTHING from the work-account root. Apply only after explicit approval:

```bash
terraform apply -var-file=terraform.personal.tfvars
```

NOTE (deviation 2026-05-28): apply runs under `agent_platform_admin` (resolved from the tfvars
`aws_profile`) because it creates IAM roles + the OIDC provider -- the permissionless `agent_platform`
(PlatformDev) runtime role would AccessDenied. The RUNTIME profile stays `agent_platform` (Step 15
constants, Step 19 config, Step 31 migration `AWS_PROFILE`). OPEN prerequisite for Phase C: confirm
`agent_platform`/PlatformDev has Athena query / S3 read-write / DynamoDB get-update / Glue get perms
BEFORE the Step 31 migration runs, else the migration writes will AccessDenied.

Run Verification Plan steps 8-12 to confirm resources + views exist and counter seeds are correct.

---

### Phase C: Data Migration

**Step 13a -- Extend the portal (`scripts/ops_data_portal.py`) for migration**

Small, symmetric, PRIVATE additions (NOT Lambda-packaged; no deploy gating):

1. Add `_migration_int_id: Optional[int] = None` to `file_rec`, mirroring `file_decision`'s existing
   param: when set, skip `_next_id("recommendations", ...)` and use the supplied integer to form the
   id with the SAME zero-padding as `next_id`/`file_decision`: **`f"rec-{n:03d}"`** (NOT `f"rec-{n}"`).
   Every existing id is 3-digit-padded and `dependencies`/priority-queue FKs reference the padded form;
   an unpadded `rec-5` would not match a referenced `rec-005`. Add a unit test asserting
   `file_rec(..., _migration_int_id=5)` returns `rec-005`.
   **CRITICAL -- thread it through the OFFLINE/outbox path too:** `file_rec`'s offline branch currently
   pops `id` and queues to the outbox WITHOUT the migration id, and `drain_pending` (recs) re-allocates
   a fresh id via `_next_id` -- so a DynamoDB blip would silently RENUMBER a migrated rec. Mirror
   `file_decision`/`drain_pending_decisions`: store `_migration_int_id` in the rec pending payload AND
   teach `drain_pending` (recs) to honour it. Both online and offline paths must preserve the id.
2. Add `_skip_sync: bool = False` to BOTH `file_rec` and `file_decision`: when True, do NOT call
   `_sync_table(...)` at the end of the write. The migration sets this per row and calls a single
   `sync()` once at the end.
3. Add a `_migration_mode: bool = False` bypass for `file_rec`'s WRITE-TIME content validation -- and
   make it cover the FULL validation surface, not just the three explicit calls
   (`_validate_context_length`, `lint_acceptance_command`, `_validate_file_path`). `file_rec` ALSO
   runs the YAML-loaded write-time validator loop (`_load_write_time_validators("ops_recommendations")`
   -> `not_null`, `accepted_values`, `path_syntax`, `acceptance_lint`, context-length `expression`).
   The bypass must suppress that whole loop too, AND the SAME bypass must be threaded into
   `drain_pending` (recs), which re-runs `validate_source` + the full validators + `model_validate` on
   the offline path. NOTE: `_derive_computed_fields` RECOMPUTES `risk`/`automatable` (NOT preserved
   verbatim -- document; acceptable).
4. **`OpsWriter.write()` has an INDEPENDENT, un-bypassable backstop** (`ops_writer.py:~247-259`): it
   RAISES on any empty required field (title/source/effort/priority/file/context/acceptance) and
   SILENTLY drops a row whose `id` does not match `^rec-\d+$`. A portal-level flag cannot disable it.
   Because the migration preserves valid `rec-NNN` ids the silent-drop won't trigger, but the
   empty-required-field RAISE can. So the migration MUST pre-validate each source row against that
   required-field set and EXPLICITLY skip+report unmigratable rows (see Step 13b `skipped_invalid`)
   rather than letting the write raise mid-stream.

All writes stay on the portal path (Decision 69); these only defer the per-row flush, preserve padded
ids end-to-end, and stop content-validation from aborting/dropping historical rows.

**Step 13b -- Create `scripts/migrate_ops_data.py`**

One-time migration. Single Portal Invariant: it WRITES only through `file_rec`/`file_decision`,
never `OpsWriter.write()` directly. Requirements:

- CLI: `--dry-run` (report source counts, write summary JSON, zero writes); `--profile-source`
  (default `company-aws-profile`), `--profile-dest` (default `agent_platform`).
- **SOURCE READ (read-only, own boto3 session):** construct
  `boto3.Session(profile_name=profile_source)` and run, via the work workgroup
  `agent-platform-production`:
  `SELECT * FROM trading_formulas_db.ops_recommendations_current` and
  `... ops_decisions_current`. Reading the `_current` views gives exactly one (latest) row per id.
  This is a plain Athena read; it does NOT go through the portal and does NOT read any `logs/` file.
- **DEST WRITE:** the script runs AFTER the constant flip (Phase D merged) with
  `AWS_PROFILE=agent_platform` set, so `file_rec`/`file_decision` resolve to the personal account
  via constants+env. Do NOT pass a `profile=` kwarg expecting it to redirect the account (it only
  redirects the id allocator). Do NOT call `ops_data_portal.sync(profile=...)` -- no such signature.
- **Startup assertions (fail fast before any write):**
  - `import scripts.ops_writer as ow; assert ow.DATABASE == "bblake_platform"` -- proves the process
    imported the FLIPPED constants (it must start after the merge, not span the flip).
  - Explicitly `os.environ["S3_LOG_BUCKET"] = "bblake-platform-data-lake"` and assert
    `OpsWriter()._bucket() == "bblake-platform-data-lake"`. `OpsWriter` resolves its bucket from the
    `S3_LOG_BUCKET` env var / `config.personal.yaml`, NOT a hardcoded literal -- if it is unset the
    writes stage to the wrong/empty bucket and the final compact finds nothing.
- **Source-registry reconciliation (BEFORE any write; also run in `--dry-run`):** enumerate ALL
  distinct `source` values returned by the source `_current` view and diff against
  `config/agent/data_quality/source_registry.yaml`. The source data is known to contain at least
  `implement-session` and `Autonomous Postflight Cleanup`, which are NOT registered and would make
  `validate_source` raise inside `file_rec`, aborting the migration mid-stream (after which the
  idempotency guard refuses the re-run -> partial, unrecoverable). For every stray value, register it
  as a legacy entry in `source_registry.yaml` (mirror the `agent-cron` "historical/no-new-recs"
  pattern) BEFORE the write phase. Fail loudly in dry-run if any stray remains unregistered.
- **Idempotency guard (FIRST thing after connecting):** query
  `SELECT count(*) FROM bblake_platform.ops_recommendations_current` (+ decisions) in the DEST.
  If either is non-empty, REFUSE to run (print "destination already populated -- aborting" and exit
  non-zero) unless `--force-skip-existing` is passed, in which case skip ids already present.
- **Pre-validation + skip-report (BEFORE writing each rec):** check the row has all required fields
  non-empty (title/source/effort/priority/file/context/acceptance) -- the set `OpsWriter.write()`'s
  un-bypassable backstop RAISES on. Rows that fail are NOT written; record them in
  `migration-summary.json` under `skipped_invalid` (with id + reason) and EXCLUDE them from the
  expected dest count. This converts a mid-stream abort into a clean, accounted-for skip.
- **Per recommendation row (passing pre-validation):** `file_rec(fields,
  _migration_int_id=int(id.split('-')[1]), _skip_sync=True, _migration_mode=True)` where `fields`
  carries the source row's `created_timestamp`, `source` (VERBATIM -- already a registered value),
  and all content fields. Do NOT overwrite `source`. Do NOT set `last_updated_timestamp` (portal
  stamps it = now). `_migration_mode=True` suppresses the full content-validator surface (Step 13a.3).
- **Per decision row:** `file_decision(fields, _migration_int_id=source_decision_int,
  _skip_sync=True)`. Derive `decision_id` SOLELY from `_migration_int_id` -- do NOT also pass a source
  `decision_id` field; if it disagreed with the id integer, `Decision.validate_dual_write` raises.
  `Decision.created_timestamp` / `last_updated_timestamp` are REQUIRED (non-Optional) and `setdefault`
  won't replace an explicit `None`; the `_current` view may surface nulls the local cache dropped. So
  COERCE a falsy `created_timestamp` (drop the key so the portal `setdefault`s it, or substitute a
  sentinel) before calling `file_decision`, else `model_validate` raises.
- **After all rows:** call `ops_data_portal.sync()` exactly once (constants now = personal) to
  compact, refresh `_current` views, and rebuild the local cache.
- **Post-write assertions:** re-query DEST `_current` counts via a fresh Athena query; ASSERT
  `dest == source - skipped_invalid` (fail non-zero on mismatch -- do not merely print; a count match
  alone does not prove content, so also sample a handful of ids and diff title/source/created_timestamp
  source-vs-dest). Assert every `file_rec`/`file_decision` return value is a real id, NOT a
  `pending-<uuid>` outbox sentinel (fail loudly if the outbox swallowed a write).
- Emit `logs/debug/migration-summary.json`: `source_recs`, `source_decisions`, `dest_recs`,
  `dest_decisions`, `imported_recs`, `imported_decisions`, `skipped_invalid` (list of id+reason),
  `timestamp_utc`.
- NEVER open any `logs/` path for READING as input. (The portal's own write-through cache is
  downstream and allowed.)
- Exit 0 only if `dest == source - skipped_invalid` and no `pending-` sentinels.

**Step 13c -- Seed DynamoDB counters above migrated max (HARD gate, MONOTONIC)**

After import, ensure the personal `bblake-platform-counters` `recommendations` and `decisions`
counters are each `>= max(migrated_id) + margin` (e.g. +1000). Use a MONOTONIC reseed (conditional
write that only raises, never lowers). NOTE: `sync_recommendations.reseed_decisions_counter` is
monotonic but there is NO `reseed_recommendations_counter` today -- `seed_counters` uses an
unconditional `put_item` that can LOWER a counter. So either add a symmetric monotonic
`reseed_recommendations_counter` (conditional `UpdateItem` with `current_value < :v`) or compute the
max from the migrated ids and conditionally raise. Do NOT naively re-run `seed_counters` -- lowering
the recommendations counter below the migrated max is exactly the Decision-50 collision risk (a
future `_next_id` would re-issue a migrated id and SCD2-merge two distinct recs).
ASSERT each counter `>= max(migrated_id) + margin` before declaring the migration successful.

**Step 14 -- Create `tests/test_migrate_ops_data.py`**

Cover:
- `--dry-run`: assert zero portal write calls; source counts written to summary JSON.
- Happy path: mock the boto3 Athena read returning N recs + M decisions; assert `file_rec` called
  N times and `file_decision` M times; assert BOTH are called with `_migration_int_id` set and
  `_skip_sync=True`; assert exactly one `sync()` at the end.
- Source preserved: assert `file_rec` is called with the row's original `source` (NOT
  `import-bootstrap`) and original `created_timestamp`.
- Portal-only: assert `OpsWriter.write` is NEVER called directly by the migration (patch it, assert
  not called -- writes must go via the portal).
- No `logs/` reads: patch `builtins.open`; assert the migration never opens a `logs/` path in read
  mode (portal write-through is out of the unit under test).
- Idempotency: mock DEST count > 0; assert the migration REFUSES (non-zero exit, no write calls).
- Outbox sentinel: mock `file_rec` returning `pending-<uuid>`; assert the migration fails loudly.

---

### Phase D: Python Constant Sweep

**Step 15 -- Update constants + embedded literals across scripts**

For each file, locate the module-level constant definitions and update:

| Script | Constant | Old value | New value |
|--------|----------|-----------|-----------|
| `scripts/ops_data_portal.py` | `_SSO_PROFILE` | `"company-aws-profile"` | `"agent_platform"` |
| `scripts/ops_data_portal.py` | `_ATHENA_DATABASE` | `"trading_formulas_db"` | `"bblake_platform"` |
| `scripts/ops_data_portal.py` | `_ATHENA_WORKGROUP` | `"agent-platform-production"` | `"bblake-platform-production"` |
| `scripts/ops_writer.py` | `DATABASE` | `"trading_formulas_db"` | `"bblake_platform"` |
| `scripts/ops_writer.py` | `ATHENA_WORKGROUP` | `"agent-platform-production"` | `"bblake-platform-production"` |
| `scripts/sync_ops.py` | `_SSO_PROFILE` | `"company-aws-profile"` | `"agent_platform"` |
| `scripts/sync_ops.py` | `_DATABASE` | `"trading_formulas_db"` | `"bblake_platform"` |
| `scripts/sync_ops.py` | `_WORKGROUP` | `"agent-platform-production"` | `"bblake-platform-production"` |
| `scripts/sync_recommendations.py` | `_DYNAMODB_TABLE` | `"agent-platform-counters"` | `"bblake-platform-counters"` |
| `scripts/session_preflight.py` | `_ATHENA_DATABASE` | `"trading_formulas_db"` | `"bblake_platform"` |
| `scripts/session_preflight.py` | `_ATHENA_WORKGROUP` | `"agent-platform-production"` | `"bblake-platform-production"` |
| `scripts/session_preflight.py` | `_ATHENA_OUTPUT_LOCATION` | value contains `bblake-platform-agent-logs` | replace bucket segment with `bblake-platform-data-lake` |
| `scripts/data_quality_runner.py` | various default-arg literals | `trading_formulas_db` / `agent-platform-production` | `bblake_platform` / `bblake-platform-production` |

**IMPORTANT for `ops_writer.py` -- there is NO bucket literal to change here.** `ops_writer.py`
resolves its bucket from the `S3_LOG_BUCKET` env var / `Config().get("aws.s3_agent_logs_bucket")` /
`config.personal.yaml` -- it does NOT contain a hardcoded `"bblake-platform-agent-logs"` string
(an earlier draft wrongly listed one in the table; removed). Do NOT change the env-var NAME string
`"S3_LOG_BUCKET"`. The data-lake bucket cutover therefore happens via env/config
(`config.personal.yaml` Step 19 + the migration's explicit `S3_LOG_BUCKET` export in Step 13b),
NOT via an `ops_writer.py` code edit. The two REAL hardcoded `"bblake-platform-agent-logs"`
literals live in `session_preflight.py:~1226` and `ops_data_portal.py:~893` (see the substring sweep).

**IMPORTANT for `session_preflight.py`**: `_ATHENA_OUTPUT_LOCATION` currently references
`bblake-platform-agent-logs` (not `data-lake`). Verify the actual value by reading the file
before editing; do not rely on the description above.

**Substring sweep (DO THIS -- the named-constant table above is NOT sufficient).** Several
work-account values are EMBEDDED literals inside SQL strings / `os.environ` defaults, not named
constants, so a "find the constant" approach misses them. Grep the WHOLE of `scripts/` by substring
and fix every runtime-path occurrence:

```bash
grep -rn "trading_formulas_db\|agent-platform-production\|bblake-platform\|company-aws-profile" scripts/
```

Known embedded literals that MUST be caught (verify line numbers by grep, do not trust these):
- `scripts/session_preflight.py` ~line 568: `FROM trading_formulas_db.ops_priority_queue_current`
  inside `read_priority_queue()` -- preflight HARD-EXITS on this; the standalone-`"trading_formulas_db"`
  grep used in Step 17a will NOT catch this dotted form. Fix it explicitly.
- `scripts/session_preflight.py` ~line 1226: `os.environ.setdefault("S3_LOG_BUCKET",
  "bblake-platform-agent-logs")` -- change the DEFAULT VALUE to `bblake-platform-data-lake`
  (NOT the env-var name).
- `scripts/session_preflight.py` ~line 263: a hardcoded `"company-aws-profile"` in the SSO
  bootstrap (not `_SSO_PROFILE`).
- `scripts/ops_data_portal.py` ~line 893: `os.environ.get("S3_LOG_BUCKET",
  "bblake-platform-agent-logs")` fallback in `_delete_postmortems_from_iceberg` -- update the value.

The following ARE now in scope (they sit in the post-migration runtime path and would otherwise keep
the employer profile/bucket active -- see the Scope table): `scripts/session_postflight.py`
(`_SSO_PROFILE` -> `agent_platform`; it allocates IDs via `drain_pending(profile=...)` at every
session close), `scripts/verifiers/data_quality.py` (AWS_PROFILE default), and
`scripts/cleanup_ops_rec_orphans.py`. Other files still carrying these literals purely outside the
runtime path (e.g. `build_lambda.py`, `migrate_schema.py`) are NOT in scope unless the V3 acceptance
run (Step 29 `validate.py`) fails on them; if it does, fix the failing file and note it. The all-refs
token gate (VP step 4) is the backstop -- anything it flags must be reconciled regardless.

**Step 16 -- Remove telemetry and non-migrated ops entries from `scripts/sync_ops.py`**

From both `_TABLE_TO_LOCAL` and `_TABLE_TO_VIEW`, remove entries whose key starts with
`telemetry_` AND the following ops-adjacent entries that are not migrated:
`ops_session_log`, `ops_execution_plans`.

Keep: `ops_recommendations`, `ops_decisions`, `ops_priority_queue`.

If any usage site in `sync_ops.py` references a removed constant by name, update or remove.

**Step 17 -- Fix `scripts/session_preflight.py` telemetry queries and venv detection**

**Part a)** In `check_telemetry_health()` (and any other function in `session_preflight.py`
that constructs SQL with a literal `"trading_formulas_db"` string rather than using
`_ATHENA_DATABASE`): replace all literal database-name strings with `_ATHENA_DATABASE`,
all literal workgroup strings with `_ATHENA_WORKGROUP`, and all literal profile strings with
`_SSO_PROFILE`. Search with:
```bash
grep -n '"trading_formulas_db"\|"agent-platform-production"\|"company-aws-profile"' \
  scripts/session_preflight.py
```
Update every occurrence found, including those inside `check_telemetry_health()` at lines
referenced (the grep will find the actual locations).

**Part b)** For each Athena query in `session_preflight.py` that targets a `telemetry_*`
table or view: wrap with `try/except` that catches Athena FAILED state containing
`TABLE_NOT_FOUND` or `DATABASE_NOT_FOUND`, logs a WARNING, and returns an empty result or
zero count rather than raising.

**Part c)** Fix venv detection: `grep -n "ROOT.name" scripts/session_preflight.py` -- there are TWO
occurrences (the venv check near line 79 AND a diagnostic print near line 1231). Replace the
`ROOT.name.lower() in str(sys.executable)` check with `Path(ROOT / ".venv" / "pyvenv.cfg").exists()`,
and fix the line-1231 diagnostic so neither depends on the working-directory name (which may stay
`agent-platform` on disk even after the GitHub rename). Update corresponding tests in
`tests/test_session_preflight.py`.

**Step 18 -- Update DQ YAML configs**

`config/agent/data_quality/ops.yaml`: Update `database: trading_formulas_db` to
`database: bblake_platform`; update `athena_workgroup: agent-platform-production` to
`athena_workgroup: bblake-platform-production`. Do the same in any other ops DQ YAML
(`config/agent/data_quality/decisions/*.yaml`).

`config/agent/data_quality/telemetry.yaml`: **`enabled: false` is a NO-OP** -- `load_checks()` does
not read an `enabled` key, so the checks would still compile and run (and ERROR against the dropped
telemetry tables). Also, `data_quality_runner.main()` ABORTS if two YAMLs declare different
`database`/`athena_workgroup`. Therefore:
1. Empty the `tables:` map in `telemetry.yaml` (set `tables: {}` or `tables: []` so zero checks
   compile) -- OR delete the file entirely. Emptying with a comment is preferred for legibility:
   `# Telemetry tables not migrated (2026-05-28). Checks emptied; re-add if telemetry is reprovisioned.`
2. Regardless of (1), update `telemetry.yaml`'s top-level `database`/`athena_workgroup` to
   `bblake_platform` / `bblake-platform-production` so it does NOT conflict-abort against `ops.yaml`.
   (If the file is deleted instead, this is moot.)

Verify after: `bin/venv-python -m scripts.data_quality_runner` runs without "Conflicting
database/workgroup" and without telemetry TABLE_NOT_FOUND errors.

**Step 19 -- Update `config/config.personal.yaml` + fix the steady-state bucket fallback**

Update `aws_profile: company-aws-profile` to `aws_profile: agent_platform`. Update any bucket names to
personal-account equivalents. ADD an explicit `aws.s3_agent_logs_bucket: bblake-platform-data-lake`.

**Fix the `OpsWriter._bucket()` work-bucket fallback (Finding 4).** `_bucket()` resolves: (1)
`S3_LOG_BUCKET` env; (2) `Config().get("aws.s3_agent_logs_bucket")`; (3) **direct parse of
`config/config.company.yaml`**, which returns the OLD `bblake-platform-agent-logs`. So in ANY
steady-state process where `S3_LOG_BUCKET` is unset (not just the migration), ops writes stage to the
employer bucket. Fix: change `ops_writer._bucket()`'s Fallback-2 to read `config/config.personal.yaml`
(not `config.company.yaml`) AND set the value there. (NOTE: `ops_writer.py` is Lambda-packaged ->
DEFERRED deploy per Decision 67/CD.17; the local steady-state path uses local code, so this takes
effect locally now.) Add `scripts/ops_writer.py` `_bucket()` to the edit set for this step.

**Step 20 -- Public-disclosure scrub of tracked files**

The following files contain employer-identifiable content that will be publicly visible after
the repo goes public. The `git filter-repo` rewrite (Step 3) handles historical blobs, but
the current HEAD versions of these files also need updating:

- `docs/GETTING_STARTED.md`: Remove/replace the employer SSO portal URL, account ID `REDACTED-ACCOUNT-ID`,
  profile name `company-aws-profile`, AND the employer name on line ~125 ("To REDACTED-EMPLOYER AWS
  account ...") from all prose and code blocks.
- `README.md`: Same -- remove account ID and SSO URL from any comments or examples.
- `config/config.company.yaml`: Add deprecation notice at top: `# LEGACY: This file describes
  the work-account (company) environment. It is retained for reference only. The active
  configuration is config/config.personal.yaml.` Do not change the existing content
  (the account ID and profile names accurately describe the legacy env).
- `config/README.md`: Replace `REDACTED-ACCOUNT-ID` and `company-aws-profile` occurrences in
  examples with generic placeholders (e.g., `YOUR_ACCOUNT_ID`, `your-aws-profile`).
- `src/main.py`: Remove any `print("AWS Account: REDACTED-ACCOUNT-ID")` statement or equivalent
  account-ID disclosure.

**Step 21 -- Delete CV prompt files**

```bash
git rm .github/prompts/build_cv_refactored.prompt.md
git rm .github/agents/cv-reviewer.agent.md
```

These are personal CV generation artefacts with explicit employer references. They are not
trading-system code and should not be in a public repository.

---

### Phase E: CI / CD Workflow Changes

**Step 22 -- Update `.github/workflows/ci.yml`**

For EACH job (`pr-validate`, `main-validate`, `terraform-validate`):
a) Change `runs-on: [self-hosted, linux]` to `runs-on: ubuntu-latest`.
b) Remove `concurrency: group: ci-runner` blocks (no longer needed; GitHub-hosted runners
   parallelise freely).

For the `main-validate` job ONLY (full tier), add the OIDC credential step BEFORE any AWS-
dependent validate step. **CRITICAL: the job MUST also declare `id-token: write`** -- without it
GitHub will not mint the OIDC JWT and `AssumeRoleWithWebIdentity` fails. `ci.yml`'s current
top-level `permissions: contents: read` is NOT sufficient. Add a job-level permissions block:
```yaml
  main-validate:
    runs-on: ubuntu-latest
    permissions:
      id-token: write      # REQUIRED for OIDC token minting
      contents: read
    steps:
      - name: Configure AWS credentials (OIDC -- branch role)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/bblake-platform-github-ci-branch
          aws-region: eu-west-2
      # ... existing validate steps ...
```
(The account ID comes from the GitHub repo variable `vars.AWS_ACCOUNT_ID` set in Step 11b -- NOT a
committed literal, so the `REDACTED-PERSONAL-ACCOUNT` scrub does not break CI.)

Do NOT add the OIDC step to `pr-validate` (fast tier -- lint only, no AWS); leave its permissions at
`contents: read`. **Do NOT add OIDC to `terraform-validate` either** -- that job runs only
`terraform init -backend=false` + `validate` + `fmt -check`, makes ZERO AWS calls, and (having no
`if:` guard) also fires on `push`, where the PR-role's `refs/pull/*` trust would REJECT the
`refs/heads/main` sub and produce a spurious failure. Rule: add `permissions: { id-token: write,
contents: read }` + the OIDC step ONLY to jobs that actually call AWS (here: just `main-validate`).

**Step 23 -- Update `.github/workflows/ci-rca.yml`**

a) Change `runs-on` to `ubuntu-latest`.
b) Add `permissions: { id-token: write, contents: read }` + OIDC credential step using the BRANCH
   role (this workflow is `workflow_run` triggered on `main`; it writes recs via the portal so it
   needs the write-capable branch role).
c) **Fork privilege gate (public-repo CRITICAL).** Because `ci-rca` runs in the base-repo context
   with the WRITE-capable branch role, a fork PR that merely fails CI would otherwise trigger it
   with privileged creds. Gate the job to skip forks:
   ```yaml
   if: github.event.workflow_run.head_repository.full_name == github.repository
   ```
   This is in ADDITION to setting the repo fork-PR-approval policy in Step 8; do not rely on the
   deferred T2.12 work for this.
d) **Preserve Decision 74 additions verbatim:**
   - `workflow_dispatch` trigger block (including all input fields)
   - `sudo npm install -g @anthropic-ai/claude-code@2.1.148` step
e) Update `AWS_PROFILE: company-aws-profile` env var to `AWS_PROFILE: agent_platform`.

**Step 24 -- Update remaining workflow files**

First confirm current `runs-on` by grep (the four below were verified ALREADY `ubuntu-latest`; only
`main-canary.yml` still needs the runner switch):
```bash
grep -rn "runs-on" .github/workflows/
```

- `.github/workflows/main-canary.yml`: change `runs-on: [self-hosted, linux]` to `ubuntu-latest`;
  if it makes AWS calls, add `permissions: { id-token: write, contents: read }` + OIDC step
  (branch role -- it is main-triggered).
- `.github/workflows/deploy.yml`, `claude.yml`, `pre_commit.yml`, `refresh-copilot-multipliers.yml`:
  these are ALREADY `ubuntu-latest` -- do NOT change `runs-on`. For each, ONLY if it actually calls
  AWS, add `permissions: { id-token: write, contents: read }` + the OIDC step (branch role for
  main/push-triggered, PR role for pull_request-triggered). `pre_commit.yml` and
  `refresh-copilot-multipliers.yml` likely make no AWS calls -- verify and add nothing if so.
- For `claude.yml`: add a comment noting Decision 71's self-hosted runner rationale is superseded
  by CD.21.

---

### Phase F: Documentation and Reference Sweep

**Step 25 -- Update `AGENTS.md`**

- Replace `company-aws-profile` with `agent_platform` throughout.
- Replace `REDACTED-ACCOUNT-ID` with the personal account reference (the `REDACTED-PERSONAL-ACCOUNT` substitution then
  redacts the literal in both history and HEAD).
- Replace `agent-platform` with `agent-platform` throughout.
- **Rewrite the home-rig sentence** (`AGENTS.md:~7`, "compute node is the PySR compute node,
  reached via REDACTED-VPN + SSH"): drop the REDACTED-VPN/SSH/home-rig specifics --
  e.g. "PySR formula discovery runs on a separate compute node." (The substitution regexes also
  scrub these terms, but rewrite the sentence so HEAD reads cleanly rather than as "reached via
  REDACTED-VPN + SSH".)
- In the "Self-hosted GitHub Actions runner" runbook section: replace the entire runbook
  body with: `Runner retired 2026-05-28 per CD.21. CI now uses GitHub-hosted runners
  (ubuntu-latest) with OIDC to personal account REDACTED-PERSONAL-ACCOUNT (role:
  bblake-platform-github-ci-branch). See terraform/personal/oidc.tf.`
- In the "Re-enable Lambda scheduled agents" runbook: update bucket name
  `bblake-platform-agent-logs` to `bblake-platform-data-lake`.
- Add a note under Temporary Operational Constraints:
  `T2.12 security gate deferred (CD.20): GHAS secret scanning, branch protection, CodeQL,
  and fork-PR approval policy are not yet enabled. To be addressed in a follow-on session.`

**Step 26 -- Update `docs/PROJECT_CONTEXT.md`**

In the AWS section: account to `REDACTED-PERSONAL-ACCOUNT`, profile to `agent_platform`, Glue database to
`bblake_platform`, Athena workgroups to `bblake-platform-production` / `bblake-platform-lab`,
S3 buckets to `bblake-platform-*` equivalents. Update GitHub Actions runner reference to
"GitHub-hosted ubuntu-latest with OIDC". Remove company SCP gotcha note (applies to work
account only; personal account is not SCP-restricted).

**Step 27 -- Update `tests/test_session_preflight.py`**

Search for ALL occurrences of `"agent-platform"` in the file using grep:
```bash
grep -n "agent-platform" tests/test_session_preflight.py
```
Replace each occurrence with `"agent-platform"`. If Step 17c replaced the ROOT.name venv
detection with a `pyvenv.cfg` check, update the corresponding test fixtures to mock
`Path.exists()` returning True for `.venv/pyvenv.cfg` rather than checking the directory name.
Do NOT use hardcoded line numbers -- use the grep output to find actual locations.

---

### Phase G: Verification and Go-Live

**Step 28 -- Pre-migration SOURCE outbox quiescence and dry-run**

This step runs on the branch BEFORE the constant flip merges (Step 30), so the constants still point
at the WORK account -- a no-arg `sync()` therefore drains/pulls against the source, making the source
`_current` views current before we read them. Do NOT use `sync(profile=...)` -- that signature does
not exist on `ops_data_portal`.

```bash
# 1. Drain any pending SOURCE outbox entries (constants still = work account here)
bin/venv-python -c "from scripts.ops_data_portal import sync; print(sync())"

# 2. HARD GATE: assert the outbox is EMPTY across BOTH tables (not just a printed count).
#    A non-empty outbox at flip time means cache-sourced update_rec calls could fire against the
#    NEW warehouse on the next preflight drain_pending (session_preflight calls it unconditionally).
bin/venv-python -c "
import sys; from pathlib import Path
pend = list(Path('logs/.ops-outbox').rglob('*.json'))
print(len(pend), 'pending entries:', [p.name for p in pend])
sys.exit(1 if pend else 0)
"
# This MUST exit 0 (zero pending across ops_recommendations_pending AND ops_decisions_pending)
# before proceeding. If non-zero, drain again / investigate; do NOT flip constants with a dirty outbox.

# 3. Dry-run the migration (reads source via boto3 work-profile; zero writes)
bin/venv-python -m scripts.migrate_ops_data --dry-run

# 4. Review logs/debug/migration-summary.json source counts
```

Do NOT run the full migration yet. Confirm source counts look correct.

**Step 29 -- Run full local validation**

```bash
bin/venv-python -m scripts.validate 2>&1 | tail -20
```

All checks must pass. If DQ checks fail due to telemetry table removal, verify
`config/agent/data_quality/telemetry.yaml` is correctly disabled.

**Step 30 -- Commit, push, open PR; verify CI**

```bash
git add -A
git commit -m "feat(public-migration): personal AWS, OIDC runner, ops-only data migration"
git push -u origin agent/public-migration
gh pr create \
  --title "feat(public-migration): personal AWS + GitHub runner + repo public" \
  --body "Implements T2.10 + T2.13. See docs/plans/PLAN-public-migration.md."
```

**Note:** CI will fail on this PR because the EC2 runner was terminated in Step 4 but the old
`runs-on: [self-hosted, linux]` workflows are still live on main. This is expected. Merge via
GitHub UI after reviewing the diff, or via `gh pr merge --admin`.

After merge, confirm the new CI workflows fire successfully on the `main` push event.

**Step 31 -- Run full migration (constants now = personal)**

After the PR merges and constants are live on main, with `AWS_PROFILE=agent_platform` exported:

```bash
export AWS_PROFILE=agent_platform

# Idempotency guard runs first; refuses if dest already populated.
bin/venv-python -m scripts.migrate_ops_data

# Verify counts against the LIVE destination warehouse (authoritative), not just the summary file.
# (migration-summary.json records dest_recs/dest_decisions from these same queries.)
bin/venv-python -c "
import json; s = json.load(open('logs/debug/migration-summary.json'))
print('recs   source:', s['source_recs'], 'dest:', s['dest_recs'])
print('decis  source:', s['source_decisions'], 'dest:', s['dest_decisions'])
assert s['dest_recs'] == s['source_recs'], 'rec count mismatch'
assert s['dest_decisions'] == s['source_decisions'], 'decision count mismatch'
print('OK: dest == source')
"

# Independent cross-check straight from Athena (does not trust the summary file):
aws athena start-query-execution \
  --query-string "SELECT count(*) FROM bblake_platform.ops_recommendations_current" \
  --work-group bblake-platform-production --profile agent_platform

# Seed/verify counters above migrated max (HARD gate, Step 13c)
bin/venv-python -c "
import boto3
ddb = boto3.Session(profile_name='agent_platform').client('dynamodb')
for c in ('recommendations','decisions'):
    v = ddb.get_item(TableName='bblake-platform-counters',
                     Key={'counter_name':{'S':c}})['Item']['current_value']['N']
    print(c, 'counter =', v)
"

# Verify personal-account preflight (needs ops_priority_queue_current to exist)
bin/venv-python -m scripts.session_preflight
```

**Step 32 -- Make repo public**

**Human action**: GitHub repo Settings -> Danger Zone -> Change visibility -> Make public.
Confirm at `https://github.com/benjamin-blake/agent-platform`.

Run Verification Plan step 21 to confirm.

**Step 33 -- DEFERRED items**

```
DEFERRED (Lambda): bin/venv-python -m scripts.build_lambda --deploy +
                   bin/venv-python -m scripts.run_scheduled_agent --smoke-test <agent-name>
(scripts/ops_writer.py modified -- pending Decision 67 / CD.17 reversal)

DEFERRED (T2.12 -- CD.20 security gate): Enable GHAS secret scanning + push protection,
GitHub branch protection with required_status_checks, CodeQL analysis, Dependabot
version and security alerts, fork-PR approval policy.
(bypassed in this plan per user_explicit_out_of_scope; must be addressed before the repo
is treated as "fully public-ready" from a security posture standpoint)
```

**Step 34 -- Execute Verification Plan** -- run all remaining steps. Loop until pass. If V3
fails unrecoverably, stop and analyse root cause (Decision 55).

**Step 35 -- Report** -- what was implemented, verification results, deferred items.

## Work Areas

N/A (IMPLEMENTATION plan type).
