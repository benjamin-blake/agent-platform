# Contract: Environment / Phase Taxonomy (Two-Axis Model)

Status: canonical. Ratified by Decision 77. Cross-references: Decisions 24, 73 (platform
promotion train); Decision 35 (apply gating, scoped by Decision 77); CDP.6 / CDP.7 (product
config-promotion, single-account); `docs/INTENT-ci-cd-architecture.md` section 6 (the canonical
platform-axis design this contract governs the vocabulary for).

This file is the single source of truth for the vocabulary reservation. Any doc, config, or
workflow that uses the words below must conform. `scripts/validate.py:validate_environment_taxonomy`
enforces the reservation on changed docs.

## 1. Why two axes

Two independent self-improvement loops touch this system, and they were being conflated:

- PLATFORM self-improvement changes infrastructure (Terraform, Lambdas, CI). The risk question
  is "does this break infrastructure / is the money real".
- PRODUCT self-improvement changes trading strategies (formulas, ensembles, capital config). The
  risk question is "does this strategy deserve capital".

Conflating them produced a live contradiction: `docs/INTENT-ci-cd-architecture.md` section 6 and
Decisions 24/73 affirm a platform sandbox -> SIT -> PROD promotion train as future-state, while
`docs/ROADMAP-PRODUCT.yaml` retired_items retired a "sandbox -> staging -> production" model as
overkill. Those are two DIFFERENT axes. The product axis is correctly single-account and
config-only (CDP.6/CDP.7 intact). The platform axis train is affirmed. This contract keeps them
from re-conflating.

## 2. The two axes

### Axis A -- PLATFORM environment axis (infrastructure)

| environment | money real? | code vs infra | apply gating | account |
|-------------|-------------|---------------|--------------|---------|
| bootstrap | N/A (CI/CD own IAM + authority budget) | `terraform/bootstrap/` only | admin-only (`agent_platform_admin`), NEVER auto-apply, out-of-band from CD pipeline (CD.35 Wave 4 / T2.23) | current personal account |
| sandbox | no (mocked) | same code path, mocked externals | auto-apply on push to main behind the deterministic guard (Decision 77); fail-closed set (IAM/trust/destroy) routes to gated-apply job requiring tf-gated-apply Environment reviewer approval (CD.35 Wave 3 / T2.22) | current personal account |
| SIT | no (system-integration, mocked capital) | same code path | manual apply after review | future dedicated account (not yet stood up) |
| PROD | yes (real capital) | same code path | manual apply + second approver | future dedicated account (not yet stood up) |

The platform split is mock-vs-real at ONE code version, not version-skew tiers. The same code path
runs in each environment; only the externals (mocked vs real) and the apply gate differ.

**Sandbox gated-apply path (CD.35 Wave 3 / T2.22 / Decision 92, trust corrected by Decision 94):**
When the deterministic guard exits 2 (IAM/trust/destroy diff), the `apply-sandbox` job sets
`routed=true` and exits green (routing is not a failure). A `gated-apply` job (`needs: apply-sandbox`,
`environment: tf-gated-apply`) then blocks until benjamin-blake approves in GitHub Actions. On
approval, it applies the SAME saved plan.bin the guard inspected (no re-plan, Decision 77 no-TOCTOU)
and writes the convergence record green/red via the T2.20 always-run write. The Environment is the
authorization boundary -- the required reviewer gates JOB EXECUTION. Because the `gated-apply` job
declares `environment: tf-gated-apply`, GitHub sets its OIDC sub to
`repo:OWNER/REPO:environment:tf-gated-apply` (the env claim REPLACES the ref claim), so
`github_ci_apply`'s trust lists BOTH `refs/heads/main` (routine path) and the environment sub
(gated path). Trusting the environment sub is safe: it can only be minted by an approval-gated job
(Decision 94 corrects the original "sub stays refs/heads/main" claim, which VP9 disproved). This
gates the apply JOB, NOT a PR status check (adding it to required checks would wedge autonomous
fix-merges, Decision 83). The bootstrap root (CD.35 Wave 4 / T2.23) owns `github_ci_apply`'s own IAM + authority budget
(permissions boundary + propagation condition keys) in `terraform/bootstrap/`. In-budget IAM
auto-apply (guard-consumption) landed in T2.25 -- see the Guard classification subsection below.

**Guard classification -- in-budget vs out-of-budget (T2.25 / Decision 92 point 5 -- SOLE SoT):**

The deterministic guard (`scripts/terraform_apply_guard.py`) narrows from blocking ALL IAM diffs
to budget-based classification. Evaluation order: delete -> neon -> trust-diff -> IAM ->
resource-policy.

| classification | criteria | guard verdict |
|----------------|----------|---------------|
| in-budget | resource type in `in_budget_resource_types`, action set == `in_budget_actions` (["update"]), target role name in `in_budget_managed_roles` | exit 0 (auto-apply, still subject to subagent review) |
| out-of-budget | any IAM-sensitive type+action not matching all three in-budget criteria | exit 2 -> tf-gated-apply Environment |
| trust-diff | `assume_role_policy` differs on ANY resource (checked BEFORE IAM) | exit 2 always, even on in-budget resource types |
| destroy/replace | "delete" in actions | exit 2 always |
| neon update/delete | non-create neon_* action | exit 2 always |
| resource-policy safe shape | `aws_lambda_permission` change whose principal == `events.amazonaws.com` (exact) AND action == `lambda:InvokeFunction` (exact) AND `function_name` starts with `agent-platform-`, ALL THREE conjunctively -- the routine EventBridge-rule-invokes-Lambda wiring pattern | exit 0 (auto-apply, still subject to subagent review) |
| resource-policy blocked | any non-inert change on `aws_lambda_permission`, `aws_s3_bucket_policy`, `aws_sns_topic_policy`, `aws_secretsmanager_secret_policy`, `aws_glue_resource_policy`, or `aws_lambda_function_url` that does not match the safe shape above (evaluated LAST, after IAM, so a delete or trust diff on one of these types is still caught by the earlier rows) | exit 2 -> tf-gated-apply Environment |

The machine-readable budget table lives at `terraform/bootstrap/authority_budget.json`
(override via `TF_AUTHORITY_BUDGET` env var for testing). Missing or unparseable table = fail
closed (all IAM treated as out-of-budget, Decision 77). `scripts/validate.py:validate_authority_budget`
asserts the table stays in sync with the IAMRoleWriteBounded SCP in `terraform/bootstrap/github_ci_apply.tf`.

Conservative v1 narrowing: role CREATES stay gated (new trust surface). The ratchet widens
on track record (Decision 92 point 5): budget amendments via the bootstrap tier only; subagent
review advises, never locks.

**Resource-based-policy classification (T2.45 / DEP-06):** the six types above -- Lambda
permissions and the S3/SNS/Secrets-Manager/Glue resource policies plus Lambda function URLs --
attach a policy directly to a non-IAM resource, so a wildcard or external-principal grant on one
of them could previously guard-PASS unreviewed without ever touching an `aws_iam_*` type. The
guard now fails closed on all six except the one known-safe `aws_lambda_permission` shape.

- **Intentional over-block, expected to be a steady-state no-op (surfaced so a reviewer isn't
  surprised):** a NEW S3-trigger `aws_lambda_permission` (principal `s3.amazonaws.com`, e.g. the
  existing `aws_lambda_permission.s3_invoke_findings_processor` /
  `s3_invoke_ops_compaction` pattern in `terraform/personal/prod_lambdas.tf`) or a NEW
  `aws_lambda_function_url` now routes to `tf-gated-apply` on any non-inert change, since neither
  matches the EventBridge safe shape and neither has an allowlisted shape of its own. This is a
  deliberate over-block, not a bug: once such a resource is applied, the Lambda code/infra
  decoupling principle (section 5 above, `ignore_changes = [source_code_hash]`) means a routine
  code-only redeploy never produces a Terraform diff on it again -- so in steady state this gate
  is a one-time review, not recurring friction.
- **Known-incomplete allowlist:** the six `RESOURCE_POLICY_TYPES` are the resource-based-policy
  types this repo has needed to date, not an exhaustive enumeration of every such AWS resource
  type -- e.g. `aws_sqs_queue_policy` and `aws_kms_key_policy` are resource-based-policy types
  outside this list today. Introducing one of those (or any other resource-based-policy type) in
  `terraform/personal/` requires a deliberate guard extension (add it to `RESOURCE_POLICY_TYPES`
  plus, if it needs one, its own allow-shape) -- it does NOT auto-inherit coverage, and until
  extended, the guard's `IAM_SENSITIVE_TYPES`/resource-policy stages simply do not see it (fails
  open to whatever the pre-T2.45 posture was for an unclassified type, i.e. auto-apply on a
  non-IAM, non-neon, non-trust-diff change) -- the gap this contract note exists to flag.

### Axis B -- PRODUCT phase axis (strategy lifecycle)

| phase | meaning |
|-------|---------|
| research | hypothesis / formula discovery |
| backtest_canonical | canonical historical backtest |
| paper | forward paper trading, no capital |
| live_small | live with capped real capital |
| live_full | live at full capital allocation |

Product phase advancement is a `capital_allocation` config change (CDP.6/CDP.7), single-account,
NOT a deploy. It never spins up infrastructure.

## 3. Vocabulary reservation (RESERVED -- enforced by lint)

| term | reserved meaning | do NOT use for |
|------|------------------|----------------|
| environment | a PLATFORM-axis tier (sandbox / SIT / PROD) | a product strategy state |
| phase | a PRODUCT-axis strategy state (research .. live_full) | a platform deploy tier |
| promotion | MUST be axis-qualified: "platform promotion" (a gated deploy) or "product promotion" (a capital_allocation config change) | a bare unqualified "promotion" |
| sandbox / SIT / PROD | platform environments | product phases |
| staging | RETIRED. Renamed to SIT on the platform axis. Never a product term. | any new use as a live tier |

Allowlisted compound tokens (legitimate, not violations): `research_sandbox` (a telemetry
destination, not the platform sandbox), `production_ensemble` (a product model name, not PROD).

Anti-patterns the lint flags in changed docs:
- a product-phase token next to the word "environment" (e.g. "live_full environment") -- product
  states are phases, not environments.
- a platform-tier token next to the word "phase" (e.g. "sandbox phase") -- platform tiers are
  environments, not phases.

## 4. Single-account-until-live_full rule (load-bearing)

The PLATFORM stays SINGLE-ACCOUNT (the current personal account, sandbox environment only) until
the PRODUCT axis reaches live_full approaching real capital. That product event -- live_full
nearing full capital allocation -- is the named trigger to stand up a separate PROD account (and,
before it, a SIT account).

This is deliberate: affirming the platform promotion train as future-state does NOT re-introduce
the multi-account posture CDP.7 retired. SIT and PROD are reserved vocabulary and future-state
infrastructure; only sandbox is live today, single-account. The contract names the trigger so the
train can be stood up later without re-litigating the taxonomy.

## 5. Lambda code/infra decoupling principle (personal-account Lambdas)

When personal-account Lambdas are introduced under `terraform/personal/`, decouple code deploys
from infra applies: set `lifecycle { ignore_changes = [source_code_hash] }` (or the equivalent
filename/handler attributes) on the `aws_lambda_function` resource so that a code-only redeploy
does not surface as a Terraform diff on the guarded auto-apply path. Code ships via the build
pipeline; infra ships via Terraform. Keeping them decoupled means the deterministic apply guard
sees only genuine infra changes, not routine code-hash churn.

**Conformance status (Decision 125/126, #544):** the four DuckLake Lambdas (writer, reader,
maintenance, catalog-dr; T2.17/T2.18, Decision 81/82) are the first personal-account Lambdas and
are now DECOUPLED, conformant: every `aws_lambda_function` resource in `terraform/personal/
ducklake_lambdas.tf`, `ducklake_catalog_dr.tf`, and `ducklake_maintenance.tf` carries a
`lifecycle { ignore_changes = [source_code_hash] }` block as of #544 (commit 32a00616), so a
code-only redeploy no longer surfaces as a Terraform diff on the guarded auto-apply path. Layers
(`ducklake-deps-layer`, `ducklake-extensions-layer`, `ducklake-pgclient-layer`) remain coupled --
layer replacement is not yet decoupled (tracked by T2.42). The governed code-deploy channel for
the four functions landed at T2.38: `.github/workflows/deploy-ducklake-lambdas.yml`; local
`build_lambda --ducklake-only --deploy` is now a genuinely non-default break-glass fallback. This
file remains the sole SoT for the apply-model / guard classification -- the interim/target state
recorded above extends that SoT, it does not compete with it.

**Conformance status (prod class, T2.43):** the three prod-class Lambdas (scheduled-agent-
dispatcher, findings-processor, ops-compaction -- the `decoupled_build_pipeline` channel_class)
were provisioned in `terraform/personal/prod_lambdas.tf` DECOUPLED from day one: every
`aws_lambda_function` resource there carries a `lifecycle { ignore_changes = [source_code_hash] }`
block from its first apply, unlike the DuckLake class above (which coupled first and decoupled
later at #544). The governed code-deploy channel for the three functions landed in the same
tier_item: `.github/workflows/deploy-prod-lambdas.yml`; local `build_lambda --deploy` is a
genuinely non-default break-glass fallback (mirrors the DuckLake class's break-glass posture).
This file remains the sole SoT for the apply-model / guard classification -- this paragraph
extends that SoT for the prod class, it does not compete with it.

## 6. Provider lock file consideration (apply-path supply chain)

`terraform/personal/.terraform.lock.hcl` is git-tracked (committed) and load-bearing on the apply
runner (T2.42 c2, DEP-03). `.gitignore` ignores `.terraform.lock.hcl` broadly
(`terraform/**/.terraform.lock.hcl`) but carries an explicit un-ignore for this root
(`!terraform/personal/.terraform.lock.hcl`) -- landed incidentally in commit 0fec964 / PR #605
(T2.16b/CD.34). The committed lock pins the three providers this root depends on
(`hashicorp/aws`, `hashicorp/null`, `kislerdm/neon`).

The pin is load-bearing, not decorative: `terraform init` in all three workflows that touch this
root (`terraform-apply-sandbox.yml`, `reconcile.yml`, `terraform-drift.yml`) carries no `-upgrade`
flag, so every init -- on the highest-privilege sandbox auto-apply path included -- resolves
provider versions from the committed lock rather than re-resolving fresh on every run. A provider
version bump is therefore always an explicit, reviewed lock-file diff (`terraform providers lock`,
committed in a PR), never silent drift picked up mid-run. The deterministic guard plus subagent
review remain the compensating controls for what the lock does not cover (the plan content itself,
not the provider binary supply chain).

## 7. Conformance

- New docs/configs MUST follow the reservation in section 3.
- "promotion" MUST be axis-qualified.
- Do not describe product phases as "environments" or platform environments as "phases".
- Platform stays single-account until the live_full trigger (section 4); do not author multi-account
  platform infrastructure before then.
