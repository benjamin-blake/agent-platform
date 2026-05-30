# Plan

## Intent
Make the self-improving loop safe to extend to infrastructure: give the sandbox platform
environment shared, lockable Terraform state and a guarded auto-apply-on-merge pipeline, and
formalize the platform-environment vs product-phase taxonomy so platform self-improvement (infra)
and product self-improvement (strategies) never re-conflate. This resolves a live contradiction
between two active decisions and an over-broad roadmap retirement, unblocking the autonomous
infra-improvement substrate the North Star depends on.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
claude/zealous-turing-RnfJJ

(Harness-assigned branch. NOTE: `scripts/find_plan.py` only auto-resolves plans on `agent/*`
branches, so `/implement` on this branch will not locate this file by branch name -- pass the
path explicitly: `docs/plans/PLAN-platform-env-and-sandbox-cd.md`.)

## Phase
Phase Platform -- CI/CD architecture. Lays the foundational governance for Phase Infra-Env
(the sandbox -> SIT -> PROD promotion train, INTENT-ci-cd-architecture.md section 6, ratified by
Decision 73) and builds the sandbox-tier CD now. SIT/PROD remain future-state per Decision 73.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/contracts/environment-taxonomy.md | Create | Canonical two-axis contract: PLATFORM environment axis (sandbox/SIT/PROD) vs PRODUCT phase axis (research/backtest_canonical/paper/live_small/live_full). Reserves vocabulary: "environment" = platform axis only; product states are "phases"; "promotion" must be axis-qualified. Records the lambda code/infra decoupling principle (ignore_changes on source_code_hash) for future personal-account Lambdas. |
| docs/DECISIONS.md | Modify | Add Decision 76 (two-axis model). Affirms the platform promotion train (cite Decisions 24, 73); scopes Decision 35's "apply is never automatic" to permit sandbox auto-apply behind the deterministic guard while PROD stays human-gated; re-bases Decision 24 vocabulary (staging -> SIT; reconciles its `envs/sandbox.tfvars` reference to the personal-module reality); names the trigger to stand up a separate PROD account (approaching real capital in product live_full). |
| docs/ROADMAP-PRODUCT.yaml | Modify | Scope the `retired_items` "Phase Infra-Env / Multi-account staging+production model" entry (line 4333) to the PRODUCT config-promotion axis ONLY. Add a cross-reference clarifying the PLATFORM promotion train is NOT retired -- it lives in INTENT-ci-cd-architecture.md section 6 and Decisions 24/73. Leave CDP.6 and CDP.7 valid for the product axis. |
| docs/INTENT-ci-cd-architecture.md | Modify | Affirm section 6 as the canonical platform-axis design. Replace the stale pre-CD.21 `company-aws-profile` / `company-aws-profile-staging` / `company-aws-profile-production` entries (lines 379-381) with personal-account-family targets (sandbox = the current personal account; SIT/PROD = future dedicated accounts per Decision 76). Cross-reference docs/contracts/environment-taxonomy.md. |
| terraform/personal/main.tf | Modify | Migrate `backend "local" {}` to `backend "s3" {}` (partial config) with native state locking (`use_lockfile = true`). Bump `required_version` from ">= 1.0" to ">= 1.10" (use_lockfile requires TF 1.10+). Account-agnostic: backend block left partial, filled via `-backend-config`. |
| terraform/personal/backend-sandbox.hcl | Create | Account-agnostic partial backend config for the sandbox environment: `bucket = "agent-platform-data-lake"`, `key = "tfstate/personal/sandbox/terraform.tfstate"`, `region = "eu-west-2"`, `use_lockfile = true`, `encrypt = true`. A future `backend-production.hcl` is then a config addition, not a rewrite. |
| terraform/personal/oidc.tf | Modify | Add a third OIDC role `agent-platform-github-ci-apply` trusted ONLY for `refs/heads/main` (NOT agent/*, NOT pull/*), with terraform-apply/provisioning permissions (mirror PlatformAdmin's AdminOps + PlatformDataLakeProvisioning policy set, plus S3 read/write on the state key). This is the high-blast-radius apply capability, OIDC-gated to main-branch GitHub Actions only. |
| .github/workflows/terraform-apply-sandbox.yml | Create | On `push` to `main` touching `terraform/personal/**`: assume the apply role via OIDC (GitHub-hosted ubuntu-latest), `terraform init -backend-config=backend-sandbox.hcl`, `terraform plan -out=plan.bin`, `terraform show -json plan.bin > plan.json`, run `scripts/terraform_apply_guard.py plan.json`, then a subagent plan review, then `terraform apply plan.bin`. Guard failure or review rejection aborts before apply. |
| scripts/terraform_apply_guard.py | Create | Deterministic guard. Parses `terraform show -json` plan output; exits non-zero (blocking apply) if ANY resource_change action contains `delete` OR if any change touches an IAM resource type (aws_iam_role, aws_iam_role_policy, aws_iam_policy, *_trust*, assume_role_policy). Prints a structured report of what tripped it. This is the compensating control that replaces the removed human gate (Decision 72: no branch protection). |
| tests/test_terraform_apply_guard.py | Create | Unit tests: (a) plan with a delete action -> exit non-zero; (b) plan with an IAM role/trust change -> exit non-zero; (c) clean create/update-only plan -> exit 0. Uses fixture plan JSON; no AWS. |
| scripts/validate.py | Modify | Add `validate_environment_taxonomy(failed)` and register it in the lint pass. Flags platform-tier vocabulary (sandbox/SIT/staging/prod used AS deploy tiers) appearing in product-axis contexts and product-phase vocabulary in platform contexts, in changed docs. Allowlist legitimate uses (e.g. research_sandbox telemetry destination; production_ensemble). |
| tests/test_validate.py | Modify | Tests for `validate_environment_taxonomy`: a doc misusing "production" as a deploy tier in a product context fails; correctly-qualified usage passes. |
| docs/PROJECT_CONTEXT.md | Modify | Re-word the "Terraform workflow integration" gotcha (line ~280): apply is human-gated EXCEPT sandbox auto-apply behind the deterministic guard, per Decision 76. |
| terraform/CLAUDE.md | Modify | Re-word the "Plan before apply" hard rule to the sandbox-scoped exception, pointing at Decision 76. |
| AGENTS.md | Modify | Re-word/qualify any unconditional "apply is never automatic" assertion to reference Decision 76's sandbox-scoped exception. |

## Bundled Recommendations
None. (Open-rec scan surfaced no aligned automatable recs targeting these files; the work originates
from an architecture session, an `ad_hoc` platform-governance exception per the planning skill.)

## Infrastructure Dependencies
| Item | Depends on | Timing |
|------|-----------|--------|
| S3 backend (main.tf + backend-sandbox.hcl) | `agent-platform-data-lake` bucket (already exists) | Pre-merge: `terraform validate`, `plan`. Post-deploy: one-time `terraform init -migrate-state -backend-config=backend-sandbox.hcl` (migrates current local state to S3). |
| `github_ci_apply` OIDC role (oidc.tf) | GitHub OIDC provider (exists); applied under `agent_platform_admin` | IAM change -> must be applied (manually, under admin) BEFORE the workflow can assume it. |
| terraform-apply-sandbox.yml | apply role + S3 state backend both live | Activates only after the bootstrap apply below. |

Bootstrap ordering (the CD chicken-and-egg): the FIRST application of the backend migration and the
apply role is performed MANUALLY by a human under `agent_platform_admin` (establishing S3 state +
the apply role). Only AFTER that does the workflow take over auto-apply for subsequent merges. This
is expected and called out so the implementer does not attempt to bootstrap auto-apply via the
not-yet-existing apply role.

Lambda Deployment Assessment: NO Lambda-packaged files are in scope (terraform/personal has no
Lambda resources; root terraform/ Lambda files are retained-not-applied per CD.21 and deferred per
Decision 67). Therefore NO `build_lambda.py --deploy` / `run_scheduled_agent.py --smoke-test` step is
owed. The lambda code/infra decoupling is captured as a principle in the taxonomy contract only.

## Acceptance Criteria
- [ ] `docs/contracts/environment-taxonomy.md` exists and defines both axes plus the vocabulary-reservation table (platform = environment; product = phase; SIT named as the middle tier).
- [ ] `docs/DECISIONS.md` contains "Decision 76", filed to the warehouse via the ops portal decision path (warehouse dec-NNN allocated atomically, not hand-written).
- [ ] The `retired_items` "Phase Infra-Env" entry in `docs/ROADMAP-PRODUCT.yaml` is scoped to the product axis and cross-references INTENT-ci-cd section 6 + Decisions 24/73.
- [ ] `docs/INTENT-ci-cd-architecture.md` section 6 no longer contains `company-aws-profile-staging`/`-production`; targets are personal-account-family; the taxonomy contract is cross-referenced.
- [ ] `terraform/personal/main.tf` declares `backend "s3"`, `use_lockfile`, and `required_version >= 1.10`; `terraform validate` passes.
- [ ] `terraform/personal/backend-sandbox.hcl` exists with bucket/key/region/use_lockfile/encrypt.
- [ ] `terraform/personal/oidc.tf` defines `agent-platform-github-ci-apply` trusted only for `refs/heads/main`.
- [ ] `.github/workflows/terraform-apply-sandbox.yml` triggers on push to main + `terraform/personal/**` and invokes the guard before apply.
- [ ] `scripts/terraform_apply_guard.py` blocks destroys and IAM/trust diffs and passes clean plans, proven by `tests/test_terraform_apply_guard.py`.
- [ ] `validate_environment_taxonomy` is registered and tested; `bin/venv-python -m scripts.validate` passes.
- [ ] The "apply is never automatic" wording in `docs/PROJECT_CONTEXT.md`, `terraform/CLAUDE.md`, and `AGENTS.md` references Decision 76's sandbox-scoped exception.
- [ ] Full presubmit green: `bin/venv-python -m scripts.validate`; `bin/venv-python -m pytest tests/ -q`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Taxonomy contract has both axes + SIT | `grep -qiE "platform" docs/contracts/environment-taxonomy.md && grep -q "SIT" docs/contracts/environment-taxonomy.md && grep -qiE "phase" docs/contracts/environment-taxonomy.md` | exit 0 | Add the missing axis/section |
| 2 | [pre-deploy] | Taxonomy lint catches misuse | `bin/venv-python -m pytest tests/test_validate.py -k taxonomy -q` | pass (bad-usage fixture fails lint, good passes) | Strengthen the regex/allowlist |
| 3 | [pre-deploy] | Decision 76 present | `grep -q "Decision 76" docs/DECISIONS.md` | exit 0 | Author Decision 76 |
| 4 | [pre-deploy] | retired_items scoped to product axis | `grep -A10 "Phase Infra-Env" docs/ROADMAP-PRODUCT.yaml \| grep -qiE "product|Decision 24\|Decision 73\|section 6"` | exit 0 | Add the scoping/cross-ref |
| 5 | [pre-deploy] | INTENT section 6 reconciled | `! grep -q "company-aws-profile-staging" docs/INTENT-ci-cd-architecture.md` | exit 0 (stale profile gone) | Replace stale profiles |
| 6 | [pre-deploy] | main.tf backend + version | `grep -q 'backend "s3"' terraform/personal/main.tf && grep -q "use_lockfile" terraform/personal/main.tf && grep -q '>= 1.10' terraform/personal/main.tf` | exit 0 | Fix backend/version |
| 7 | [pre-deploy] | Terraform validates | `cd terraform/personal && terraform init -backend=false -input=false && terraform validate` | "Success! The configuration is valid." | Fix HCL errors |
| 8 | [pre-deploy] | Apply role is main-only | `awk '/github_ci_apply/,/^}/' terraform/personal/oidc.tf \| grep -q "refs/heads/main" && ! (awk '/github_ci_apply/,/^}/' terraform/personal/oidc.tf \| grep -q "agent/\*")` | exit 0 | Tighten trust |
| 9 | [pre-deploy] | Guard blocks destroy + IAM diff, passes clean | `bin/venv-python -m pytest tests/test_terraform_apply_guard.py -q` | all pass | Fix guard logic |
| 10 | [pre-deploy] | Workflow wires guard before apply | `grep -q "terraform_apply_guard" .github/workflows/terraform-apply-sandbox.yml && grep -q "terraform/personal/\*\*" .github/workflows/terraform-apply-sandbox.yml` | exit 0 | Wire the guard/trigger |
| 11 | [pre-deploy] | Doc rule references Decision 76 | `grep -q "Decision 76" docs/PROJECT_CONTEXT.md terraform/CLAUDE.md AGENTS.md` | exit 0 | Update wording |
| 12 | [pre-deploy] | Full presubmit | `bin/venv-python -m scripts.validate` | exit 0 | Fix reported failures |
| 13 | [pre-deploy] | Full tests | `bin/venv-python -m pytest tests/ -q` | exit 0 | Fix failing tests |
| 14 | [post-deploy] | State migrates to S3 + native lock | `cd terraform/personal && terraform init -migrate-state -backend-config=backend-sandbox.hcl -input=false` then `aws s3 ls s3://agent-platform-data-lake/tfstate/personal/sandbox/ --profile agent_platform_admin` | state object listed; no DynamoDB lock table required | Re-check bucket/key + creds |
| 15 | [post-deploy] | Apply role exists after admin apply | `aws iam get-role --role-name agent-platform-github-ci-apply --profile agent_platform_admin` | role returned, trust = refs/heads/main | Re-apply oidc.tf under admin |
| 16 | [post-deploy] | End-to-end: guarded auto-apply on a no-op | Merge a no-op `terraform/personal/**` change to main (or `workflow_dispatch`); watch the Actions run | guard passes, plan applies, run green | Inspect guard output / role perms |

## Constraints
- ASCII only; no emojis; ASCII hyphens, never em dashes (Windows console encoding).
- Terraform optional-artifact calls must wrap `filemd5()`/`file()` in `try()`.
- Never `eval`/`exec`; no exceptions raised at module import (guard + validate additions).
- IAM precedence: terraform apply (oidc.tf role) must precede any consumer relying on it.
- No rescue agents or workaround loops (Decision 55). If a V3 step fails unrecoverably, stop and root-cause; do not paper over.
- Single Portal Invariant: Decision 76 is filed via `scripts.ops_data_portal` decision path; never hand-write the `dec-NNN` warehouse id or edit `.decisions-index.jsonl` directly.
- STRATEGIC suspended (CD.17): this is one larger IMPLEMENTATION plan by design.
- Decision 72 / CD.20: branch protection and required status checks are NOT available; the deterministic guard + subagent review ARE the apply gate. The guard must fail-closed.

## Context
- Decisions to cite: 24 (Multi-Environment Deployment Strategy -- already specifies sandbox auto-apply on push-to-main, staging/PROD manual), 35 (Terraform Workflow Integration -- "no auto-apply"; this plan scopes it), 73 (Two-Tier CI + promotion train -- ratifies sandbox -> SIT -> PROD), 67 (Lambda + STRATEGIC deferral -- justifies principle-only lambda treatment). Related: 72 (branch protection unavailable -> guard is the gate), 36/68 (old no-OIDC / self-hosted runner, superseded by CD.21 -- the new OIDC role is consistent).
- The contradiction this resolves: INTENT-ci-cd-architecture.md section 6 + Decisions 24/73 affirm a platform sandbox -> SIT -> PROD promotion train as future-state; ROADMAP-PRODUCT.yaml retired_items (line 4333) retired the same "sandbox -> staging -> production" model as overkill, conflating the PLATFORM deploy axis with the PRODUCT config-promotion axis. Decision 76 disentangles them: product promotion stays config-only (CDP.6/CDP.7 intact); the platform train is affirmed.
- Two-axis taxonomy (the durable fix): PLATFORM environment axis answers "does this break infrastructure / is the money real" (sandbox mocked -> SIT -> PROD real; promotion = a gated deploy). PRODUCT phase axis answers "does this strategy deserve capital" (research..live_full; promotion = a capital_allocation config change). Same code path within each environment is preserved; the platform split is mock-vs-real at one version, not version-skew tiers.
- Branch nuance: this session runs on `claude/zealous-turing-RnfJJ` (harness-assigned), not `agent/{slug}`, so `find_plan.py` will not auto-resolve this plan; `/implement` must be given the path.
- Known gotchas in play: Terraform `try()` on optional artifacts; `bin/venv-python` wrapper (never bare python); ruff line length 127; test_coverage_checker requires a test file with 100% coverage for every new/modified source file (terraform_apply_guard.py and validate.py changes both need tests).

## Pre-Implementation Checklist
- [ ] Branch confirmed not `main` (on `claude/zealous-turing-RnfJJ`).
- [ ] docs/PROJECT_CONTEXT.md read.
- [ ] DECISIONS.md read (at least Decisions 24, 35, 73 bodies for accurate citation/vocabulary re-basing).
- [ ] All files in Scope located and readable.
- [ ] Acceptance Criteria understood and verifiable.

## Ordered Execution Steps
1. Create `docs/contracts/environment-taxonomy.md` -- the two-axis contract + vocabulary-reservation table + lambda-decoupling principle. This is the conceptual anchor every other edit cites.
2. Modify `scripts/validate.py`: add `validate_environment_taxonomy(failed)` and register it in the lint pass. Add `tests/test_validate.py` coverage (bad usage fails, qualified usage passes). Run `ruff check --fix` immediately after.
3. Author Decision 76 in `docs/DECISIONS.md` (Decision 75 format: Status/Date/Warehouse ID/Problem/Decision); file it via the ops portal decision path so the warehouse id is allocated atomically.
4. Scope the `retired_items` "Phase Infra-Env" entry in `docs/ROADMAP-PRODUCT.yaml` to the product axis with the platform-train cross-reference.
5. Reconcile `docs/INTENT-ci-cd-architecture.md` section 6 (personal-account-family targets; cross-ref the taxonomy contract).
6. Update the "apply is never automatic" wording in `docs/PROJECT_CONTEXT.md`, `terraform/CLAUDE.md`, and `AGENTS.md` to the Decision-76 sandbox-scoped exception.
7. Create `scripts/terraform_apply_guard.py` (fail-closed on delete actions and IAM/trust diffs) + `tests/test_terraform_apply_guard.py`. Run `ruff check --fix`.
8. Modify `terraform/personal/main.tf` (S3 backend partial + use_lockfile + required_version >= 1.10) and create `terraform/personal/backend-sandbox.hcl`.
9. Modify `terraform/personal/oidc.tf`: add the main-only `github_ci_apply` role.
10. Create `.github/workflows/terraform-apply-sandbox.yml` (OIDC assume -> init -> plan -> guard -> subagent review -> apply).
11. **Execute Verification Plan** -- run each [pre-deploy] step; loop until all pass. Then perform the bootstrap apply (manual, under `agent_platform_admin`) and run the [post-deploy] steps. If a V3 step fails unrecoverably, stop and analyze root cause (Decision 55) -- do not work around.
12. Report: what was implemented, pre-deploy verification results, and post-deploy bootstrap/auto-apply results.
