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
| docs/contracts/environment-taxonomy.md | Create | Canonical two-axis contract: PLATFORM environment axis (sandbox/SIT/PROD) vs PRODUCT phase axis (research/backtest_canonical/paper/live_small/live_full). Reserves vocabulary: "environment" = platform axis only; product states are "phases"; "promotion" must be axis-qualified. States explicitly that the platform stays SINGLE-ACCOUNT until product live_full approaches real capital (the named PROD-account trigger), so the contract does not re-introduce the multi-account posture CDP.7 retired. Records the lambda code/infra decoupling principle (ignore_changes on source_code_hash) for future personal-account Lambdas, and the provider-lock-file consideration (see Context). |
| docs/DECISIONS.md | Modify | Add Decision 76 (two-axis model). Affirms the platform promotion train (cite Decisions 24, 73); scopes Decision 35's "apply is never automatic" to permit sandbox auto-apply behind the deterministic guard while PROD stays human-gated; re-bases Decision 24 vocabulary (staging -> SIT; reconciles its `envs/sandbox.tfvars` reference to the personal-module reality); names the trigger to stand up a separate PROD account (product live_full approaching real capital) and states platform stays single-account until then. |
| docs/ROADMAP-PRODUCT.yaml | Modify | Scope the `retired_items` "Phase Infra-Env / Multi-account staging+production model" entry (line 4333) to the PRODUCT config-promotion axis ONLY. Add a cross-reference clarifying the PLATFORM promotion train is NOT retired -- it lives in INTENT-ci-cd-architecture.md section 6 and Decisions 24/73. Leave CDP.6 and CDP.7 valid for the product axis. |
| docs/INTENT-ci-cd-architecture.md | Modify | Affirm section 6 as the canonical platform-axis design. Replace ALL stale pre-CD.21 `company-aws-profile*` tokens (currently lines 366, 379, 380, 381 -- verify with `grep -n "company-aws-profile"`) with personal-account-family targets: sandbox = the current personal account; SIT/PROD = future dedicated accounts per Decision 76, gated on the live_full trigger. Cross-reference docs/contracts/environment-taxonomy.md. Reconcile any L9/L10 enforcement-surface rows that still imply company-account profiles. |
| terraform/personal/main.tf | Modify | Migrate `backend "local" {}` to `backend "s3" {}` (partial config) with native state locking (`use_lockfile = true`). Bump `required_version` from ">= 1.0" to ">= 1.10" (use_lockfile requires TF 1.10+). Account-agnostic: backend block left partial, filled via `-backend-config`. |
| terraform/personal/backend-sandbox.hcl | Create | Account-agnostic partial backend config for the sandbox environment: `bucket = "agent-platform-data-lake"`, `key = "tfstate/personal/sandbox/terraform.tfstate"`, `region = "eu-west-2"`, `use_lockfile = true`, `encrypt = true`. A future `backend-production.hcl` is then a config addition. Confirmed NOT gitignored (commits cleanly). |
| config/terraform-version | Modify | Bump the pinned Terraform version from `1.5.0` to a 1.10+ release (e.g. `1.10.5`). REQUIRED: 1.5.0 hard-fails on `required_version >= 1.10` and does not recognise `use_lockfile`. |
| .github/workflows/ci.yml | Modify | Update the hardcoded `terraform_version: 1.5.0` (line ~57) to match the new 1.10+ pin so the terraform fmt/validate CI steps install a TF that accepts `required_version >= 1.10` + `use_lockfile`. (Do NOT add a CI check without it existing in validate.py first; this is a version-pin edit only.) |
| .github/workflows/deploy.yml | Modify | Update `TF_VERSION: "1.5.0"` (line 12) to the new 1.10+ pin to keep the deploy workflow consistent. |
| terraform/personal/oidc.tf | Modify | Add a third OIDC role `agent-platform-github-ci-apply` trusted ONLY for `refs/heads/main` (NOT agent/*, NOT pull/*). Its policy MUST be an ENUMERATED least-privilege set scoped to what terraform/personal actually manages: glue + athena (the workgroup/db), s3 on the data-lake bucket + the tfstate key, dynamodb on the counters table, and IAM write actions scoped to the module's role/provider ARNs (PlatformDev, PlatformAdmin, github_ci_*, the OIDC provider). If a genuine `iam:*` is required to manage the OIDC provider + roles, it MUST be annotated with a `# REVIEWED:` comment justifying the deliberate grant -- NOT a silent wildcard admin copy. The deterministic guard (no IAM/trust diffs) is the compensating control on this role's blast radius. |
| .github/workflows/terraform-apply-sandbox.yml | Create | On `push` to `main` touching `terraform/personal/**`: assume the apply role via OIDC (GitHub-hosted ubuntu-latest), `terraform init -backend-config=backend-sandbox.hcl`, `terraform plan -out=plan.bin`, `terraform show -json plan.bin > plan.json`, run `scripts/terraform_apply_guard.py plan.json`, then a subagent plan review, then `terraform apply plan.bin` (the SAME plan file the guard inspected -- no re-plan between guard and apply). FAIL-CLOSED: the apply step runs only on guard `success()`; the guard step must NOT use `continue-on-error`; ANY non-zero guard exit (tripped OR internal error) aborts before apply. |
| scripts/terraform_apply_guard.py | Create | Deterministic guard parsing `terraform show -json`. See the "Guard detection contract" in Context for exact field paths. Exits 2 (tripped) on any destroy or IAM/trust change; exits 1 on internal/parse error; exits 0 only on create/update/no-op/read on non-IAM resources with no trust changes. Prints a structured report (address, type, actions) for each blocking change. |
| tests/test_terraform_apply_guard.py | Create | Unit tests: (a) delete action -> exit 2; (b) replacement pair `["delete","create"]` -> exit 2; (c) IAM role/policy change -> exit 2; (d) assume_role_policy/trust diff on any resource -> exit 2; (e) malformed JSON -> exit 1; (f) clean create/update/no-op plan -> exit 0. At least ONE fixture is captured from a REAL `terraform show -json` run (even a trivial no-op plan) so field paths are validated against the actual schema, not hand-authored guesses. |
| scripts/validate.py | Modify | Add `validate_environment_taxonomy(failed)` and register it in the lint pass. Flags platform-tier vocabulary (sandbox/SIT/staging/prod used AS deploy tiers) appearing in product-axis contexts and product-phase vocabulary in platform contexts, in changed docs. Allowlist legitimate uses (research_sandbox telemetry destination; production_ensemble; etc.). |
| tests/test_validate.py | Modify | Tests for `validate_environment_taxonomy` (bad usage fails, qualified usage passes). 100% coverage of the new function (test_coverage_checker requirement). |
| docs/PROJECT_CONTEXT.md | Modify | Re-word the "Terraform workflow integration" gotcha (line ~280): apply is human-gated EXCEPT sandbox auto-apply behind the deterministic guard, per Decision 76. |
| terraform/CLAUDE.md | Modify | Re-word the "Plan before apply" hard rule (line ~10) to the sandbox-scoped exception, pointing at Decision 76. |
| AGENTS.md | Modify | Re-word/qualify any unconditional "apply is never automatic" assertion to reference Decision 76's sandbox-scoped exception. |

## Bundled Recommendations
None. (Open-rec scan surfaced no aligned automatable recs targeting these files; the work originates
from an architecture session, an `ad_hoc` platform-governance exception per the planning skill.)

## Infrastructure Dependencies
| Item | Depends on | Timing |
|------|-----------|--------|
| TF version bump (config/terraform-version, ci.yml, deploy.yml) | none | Pre-merge: must land WITH main.tf's `required_version >= 1.10` or CI terraform-validate fails on 1.5.0. |
| S3 backend (main.tf + backend-sandbox.hcl) | `agent-platform-data-lake` bucket (already exists) | Pre-merge: `terraform validate`, `plan`. Post-deploy: one-time `terraform init -migrate-state -backend-config=backend-sandbox.hcl -input=false -force-copy`. |
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
- [ ] `docs/contracts/environment-taxonomy.md` exists, defines both axes + the vocabulary-reservation table (SIT named), and states the platform-stays-single-account-until-live_full rule.
- [ ] `docs/DECISIONS.md` contains "Decision 76", filed to the warehouse via the ops portal decision path (dec-NNN allocated atomically, not hand-written).
- [ ] The `retired_items` "Phase Infra-Env" entry in `docs/ROADMAP-PRODUCT.yaml` is scoped to the product axis and cross-references INTENT-ci-cd section 6 + Decisions 24/73.
- [ ] `docs/INTENT-ci-cd-architecture.md` contains NO `company-aws-profile` token; targets are personal-account-family; the taxonomy contract is cross-referenced.
- [ ] `terraform/personal/main.tf` declares `backend "s3"`, `use_lockfile`, and `required_version >= 1.10`; `terraform validate` passes under a 1.10+ TF.
- [ ] `config/terraform-version`, `.github/workflows/ci.yml`, and `.github/workflows/deploy.yml` all pin a TF >= 1.10 (no `1.5.0` remains).
- [ ] `terraform/personal/backend-sandbox.hcl` exists with bucket/key/region/use_lockfile/encrypt.
- [ ] `terraform/personal/oidc.tf` defines `agent-platform-github-ci-apply` trusted only for `refs/heads/main`, with an ENUMERATED policy (no unannotated `iam:*` + `Resource: "*"`; any wildcard carries a `# REVIEWED:` justification).
- [ ] `.github/workflows/terraform-apply-sandbox.yml` triggers on push to main + `terraform/personal/**`, runs the guard before apply, is fail-closed (apply gated on guard `success()`, no `continue-on-error` on the guard, any non-zero guard exit blocks apply), and applies the same plan file the guard inspected.
- [ ] `scripts/terraform_apply_guard.py` blocks destroys, replacements, IAM changes, and trust-policy diffs, and passes clean plans -- proven by `tests/test_terraform_apply_guard.py`, including >=1 fixture captured from real `terraform show -json`.
- [ ] `validate_environment_taxonomy` is registered and tested with 100% coverage; `bin/venv-python -m scripts.validate` passes.
- [ ] The "apply is never automatic" wording in `docs/PROJECT_CONTEXT.md`, `terraform/CLAUDE.md`, and `AGENTS.md` references Decision 76's sandbox-scoped exception.
- [ ] Full presubmit green: `bin/venv-python -m scripts.validate`; `bin/venv-python -m pytest tests/ -q`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Taxonomy contract: axes + SIT + single-account rule | `grep -qiE "platform" docs/contracts/environment-taxonomy.md && grep -q "SIT" docs/contracts/environment-taxonomy.md && grep -qiE "single-account\|live_full" docs/contracts/environment-taxonomy.md` | exit 0 | Add missing axis/section/rule |
| 2 | [pre-deploy] | Taxonomy lint catches misuse | `bin/venv-python -m pytest tests/test_validate.py -k taxonomy -q` | pass (bad fixture fails lint, good passes) | Strengthen regex/allowlist |
| 3 | [pre-deploy] | Decision 76 present | `grep -q "Decision 76" docs/DECISIONS.md` | exit 0 | Author Decision 76 |
| 4 | [pre-deploy] | retired_items scoped to product axis | `grep -A10 "Phase Infra-Env" docs/ROADMAP-PRODUCT.yaml \| grep -qiE "product\|Decision 24\|Decision 73\|section 6"` | exit 0 | Add scoping/cross-ref |
| 5 | [pre-deploy] | INTENT fully reconciled (no stale profile token) | `! grep -q "company-aws-profile" docs/INTENT-ci-cd-architecture.md` | exit 0 | Replace ALL occurrences |
| 6 | [pre-deploy] | main.tf backend + version | `grep -q 'backend "s3"' terraform/personal/main.tf && grep -q "use_lockfile" terraform/personal/main.tf && grep -q '>= 1.10' terraform/personal/main.tf` | exit 0 | Fix backend/version |
| 7 | [pre-deploy] | No stale 1.5.0 TF pin anywhere | `! grep -rn "1\.5\.0" config/terraform-version .github/workflows/ci.yml .github/workflows/deploy.yml` and `grep -qE "1\.(1[0-9]\|[2-9][0-9])" config/terraform-version` | first exits 0 (no 1.5.0), second exits 0 (>=1.10) | Bump all three pins |
| 8 | [pre-deploy] | Terraform validates (under 1.10+) | `cd terraform/personal && terraform init -backend=false -input=false && terraform validate` | "Success! The configuration is valid." | Fix HCL / install TF >=1.10 |
| 9 | [pre-deploy] | Apply role main-only trust | `grep -n "refs/heads/main" terraform/personal/oidc.tf` shows the github_ci_apply trust; manual confirm the role's StringLike sub has NO `agent/*` or `pull/*` | trust = main only | Tighten trust |
| 10 | [pre-deploy] | Apply policy bounded (no unannotated admin) | `! grep -q '"iam:\*"' terraform/personal/oidc.tf \|\| grep -q "# REVIEWED" terraform/personal/oidc.tf` | exit 0 (no iam:* OR it is annotated) | Enumerate or annotate |
| 11 | [pre-deploy] | Guard: destroy/replace/IAM/trust block, clean passes, bad-json errors | `bin/venv-python -m pytest tests/test_terraform_apply_guard.py -q` | all pass | Fix guard logic/fixtures |
| 12 | [pre-deploy] | Workflow wires guard before apply, fail-closed, same plan file | `grep -q "terraform_apply_guard" .github/workflows/terraform-apply-sandbox.yml && grep -q "terraform/personal/\*\*" .github/workflows/terraform-apply-sandbox.yml && ! grep -q "continue-on-error: true" .github/workflows/terraform-apply-sandbox.yml && grep -q "apply.*plan.bin\|apply plan" .github/workflows/terraform-apply-sandbox.yml` | exit 0 | Wire guard/trigger/gating |
| 13 | [pre-deploy] | Doc rule references Decision 76 | `grep -q "Decision 76" docs/PROJECT_CONTEXT.md terraform/CLAUDE.md AGENTS.md` | exit 0 | Update wording |
| 14 | [pre-deploy] | Full presubmit | `bin/venv-python -m scripts.validate` | exit 0 | Fix reported failures |
| 15 | [pre-deploy] | Full tests | `bin/venv-python -m pytest tests/ -q` | exit 0 | Fix failing tests |
| 16 | [post-deploy] | State migrates to S3 + native lock (non-interactive) | `cd terraform/personal && terraform init -migrate-state -backend-config=backend-sandbox.hcl -input=false -force-copy` then `aws s3 ls s3://agent-platform-data-lake/tfstate/personal/sandbox/ --profile agent_platform_admin` | state object listed; no DynamoDB lock table required | Re-check bucket/key/creds/`-force-copy` |
| 17 | [post-deploy] | Apply role exists after admin apply | `aws iam get-role --role-name agent-platform-github-ci-apply --profile agent_platform_admin` | role returned, trust = refs/heads/main | Re-apply oidc.tf under admin |
| 18 | [post-deploy] | Guard blocks a real destructive plan | Craft a trivial change that forces a destroy/IAM diff; run `terraform plan -out=p && terraform show -json p > p.json && bin/venv-python scripts/terraform_apply_guard.py p.json` | exit 2; report names the offending resource | Fix guard field paths against real schema |
| 19 | [post-deploy] | End-to-end: guarded auto-apply on a no-op | Merge a no-op `terraform/personal/**` change to main (or `workflow_dispatch`); watch the Actions run | guard passes, plan applies, run green | Inspect guard output / role perms |

## Constraints
- ASCII only; no emojis; ASCII hyphens, never em dashes (Windows console encoding).
- Terraform optional-artifact calls must wrap `filemd5()`/`file()` in `try()`.
- Never `eval`/`exec`; no exceptions raised at module import (guard + validate additions).
- IAM precedence: terraform apply (oidc.tf role) must precede any consumer relying on it.
- TF version pin (config/terraform-version + ci.yml + deploy.yml) MUST be bumped in the same change as `required_version >= 1.10`, or CI terraform-validate breaks on 1.5.0.
- No rescue agents or workaround loops (Decision 55). If a V3 step fails unrecoverably, stop and root-cause; do not paper over.
- Single Portal Invariant: Decision 76 is filed via `scripts.ops_data_portal` decision path; never hand-write the `dec-NNN` warehouse id or edit `.decisions-index.jsonl` directly.
- STRATEGIC suspended (CD.17): this is one larger IMPLEMENTATION plan by design.
- Decision 72 / CD.20: branch protection and required status checks are NOT available; the deterministic guard + subagent review ARE the apply gate. The guard AND the workflow must fail closed.
- Never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first; the ci.yml edit here is a version-pin change only, not a new check.

## Context
- Decisions to cite: 24 (Multi-Environment Deployment Strategy -- already specifies sandbox auto-apply on push-to-main, staging/PROD manual), 35 (Terraform Workflow Integration -- "no auto-apply"; this plan scopes it), 73 (Two-Tier CI + promotion train -- ratifies sandbox -> SIT -> PROD), 67 (Lambda + STRATEGIC deferral -- justifies principle-only lambda treatment). Related: 72 (branch protection unavailable -> guard is the gate), 36/68 (old no-OIDC / self-hosted runner, superseded by CD.21 -- the new OIDC role is consistent).
- The contradiction this resolves: INTENT-ci-cd-architecture.md section 6 + Decisions 24/73 affirm a platform sandbox -> SIT -> PROD promotion train as future-state; ROADMAP-PRODUCT.yaml retired_items (line 4333) retired the same "sandbox -> staging -> production" model as overkill, conflating the PLATFORM deploy axis with the PRODUCT config-promotion axis. Decision 76 disentangles them: product promotion stays config-only (CDP.6/CDP.7 intact, single-account); the platform train is affirmed, and the platform also stays single-account until product live_full approaches real capital.
- Two-axis taxonomy (the durable fix): PLATFORM environment axis answers "does this break infrastructure / is the money real" (sandbox mocked -> SIT -> PROD real; promotion = a gated deploy). PRODUCT phase axis answers "does this strategy deserve capital" (research..live_full; promotion = a capital_allocation config change). Same code path within each environment is preserved; the platform split is mock-vs-real at one version, not version-skew tiers.
- Guard detection contract (scripts/terraform_apply_guard.py), against `terraform show -json` output:
  - Input: JSON from `terraform show -json <planfile>`; iterate `.resource_changes[]`.
  - BLOCK if any element's `.change.actions` array contains `"delete"` (covers `["delete"]` destroys and replacement pairs `["delete","create"]` / `["create","delete"]`).
  - BLOCK if `.type` is in the IAM-sensitive set {aws_iam_role, aws_iam_role_policy, aws_iam_policy, aws_iam_role_policy_attachment, aws_iam_openid_connect_provider, aws_iam_user, aws_iam_group} AND `.change.actions` is not `["no-op"]`/`["read"]`.
  - BLOCK if `.change.before` vs `.change.after` differs on an `assume_role_policy` / trust attribute on ANY resource (even otherwise-allowed types).
  - PASS (exit 0) only when all changes are create/update/no-op/read on non-IAM resources with no trust diffs. Tripped -> exit 2; internal/parse error -> exit 1 (both block apply at the workflow level).
- Workflow fail-closed (.github/workflows/terraform-apply-sandbox.yml): apply step runs only on guard `success()`; guard step has no `continue-on-error`; ANY non-zero guard exit aborts before apply; apply consumes the SAME `plan.bin` the guard inspected (no re-plan between guard and apply -- avoids TOCTOU).
- Provider lock file: `.gitignore` ignores `.terraform.lock.hcl` and `terraform/**/.terraform.lock.hcl`, so the GitHub-hosted apply runner resolves providers fresh each run -- a version-drift/supply-chain surface on the highest-privilege workflow. RECOMMENDED (non-blocking): un-ignore `terraform/personal/.terraform.lock.hcl` and commit it so the apply pins provider versions. Note in the taxonomy contract.
- Branch nuance: this session runs on `claude/zealous-turing-RnfJJ` (harness-assigned), not `agent/{slug}`, so `find_plan.py` will not auto-resolve this plan; `/implement` must be given the path.
- Known gotchas in play: Terraform `try()` on optional artifacts; `bin/venv-python` wrapper (never bare python); ruff line length 127; test_coverage_checker requires a test file with 100% coverage for every new/modified source file (terraform_apply_guard.py and validate.py changes both need tests); tests must mock BOTH subprocess.Popen and subprocess.run for subprocess-spawning code.

## Pre-Implementation Checklist
- [ ] Branch confirmed not `main` (on `claude/zealous-turing-RnfJJ`).
- [ ] docs/PROJECT_CONTEXT.md read.
- [ ] DECISIONS.md read (at least Decisions 24, 35, 73 bodies for accurate citation/vocabulary re-basing).
- [ ] All existing files in Scope located and readable.
- [ ] Acceptance Criteria understood and verifiable.
- [ ] A TF >= 1.10 binary is available locally for VP steps 8/16/18 (or they are run in CI/post-deploy).

## Ordered Execution Steps
1. Create `docs/contracts/environment-taxonomy.md` -- the two-axis contract + vocabulary-reservation table + single-account-until-live_full rule + lambda-decoupling principle + provider-lock note. This is the conceptual anchor every other edit cites.
2. Modify `scripts/validate.py`: add `validate_environment_taxonomy(failed)` and register it. Add `tests/test_validate.py` coverage (bad usage fails, qualified usage passes). Run `ruff check --fix` immediately after.
3. Author Decision 76 in `docs/DECISIONS.md` (Decision 75 format: Status/Date/Warehouse ID/Problem/Decision); file it via the ops portal decision path so the warehouse id is allocated atomically.
4. Scope the `retired_items` "Phase Infra-Env" entry in `docs/ROADMAP-PRODUCT.yaml` to the product axis with the platform-train cross-reference.
5. Reconcile `docs/INTENT-ci-cd-architecture.md`: replace ALL `company-aws-profile*` tokens with personal-account-family targets; cross-ref the taxonomy contract.
6. Update the "apply is never automatic" wording in `docs/PROJECT_CONTEXT.md`, `terraform/CLAUDE.md`, and `AGENTS.md` to the Decision-76 sandbox-scoped exception.
7. Create `scripts/terraform_apply_guard.py` per the Guard detection contract (fail-closed: exit 2 tripped, exit 1 error, exit 0 clean) + `tests/test_terraform_apply_guard.py` (incl. a real `terraform show -json` fixture). Run `ruff check --fix`.
8. Bump the Terraform version pin to >= 1.10 in `config/terraform-version`, `.github/workflows/ci.yml`, and `.github/workflows/deploy.yml`.
9. Modify `terraform/personal/main.tf` (S3 backend partial + use_lockfile + required_version >= 1.10) and create `terraform/personal/backend-sandbox.hcl`.
10. Modify `terraform/personal/oidc.tf`: add the main-only `github_ci_apply` role with an ENUMERATED least-privilege policy (annotate any wildcard).
11. Create `.github/workflows/terraform-apply-sandbox.yml` (OIDC assume -> init -> plan -out -> show -json -> guard -> subagent review -> apply same plan; fail-closed).
12. **Execute Verification Plan** -- run each [pre-deploy] step; loop until all pass. Then perform the bootstrap apply (manual, under `agent_platform_admin`) and run the [post-deploy] steps. If a V3 step fails unrecoverably, stop and analyze root cause (Decision 55) -- do not work around.
13. Report: what was implemented, pre-deploy verification results, and post-deploy bootstrap/auto-apply results.
