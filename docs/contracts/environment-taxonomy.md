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
to budget-based classification. Evaluation order: delete -> neon -> trust-diff -> IAM.

| classification | criteria | guard verdict |
|----------------|----------|---------------|
| in-budget | resource type in `in_budget_resource_types`, action set == `in_budget_actions` (["update"]), target role name in `in_budget_managed_roles` | exit 0 (auto-apply, still subject to subagent review) |
| out-of-budget | any IAM-sensitive type+action not matching all three in-budget criteria | exit 2 -> tf-gated-apply Environment |
| trust-diff | `assume_role_policy` differs on ANY resource (checked BEFORE IAM) | exit 2 always, even on in-budget resource types |
| destroy/replace | "delete" in actions | exit 2 always |
| neon update/delete | non-create neon_* action | exit 2 always |

The machine-readable budget table lives at `terraform/bootstrap/authority_budget.json`
(override via `TF_AUTHORITY_BUDGET` env var for testing). Missing or unparseable table = fail
closed (all IAM treated as out-of-budget, Decision 77). `scripts/validate.py:validate_authority_budget`
asserts the table stays in sync with the IAMRoleWriteBounded SCP in `terraform/bootstrap/github_ci_apply.tf`.

Conservative v1 narrowing: role CREATES stay gated (new trust surface). The ratchet widens
on track record (Decision 92 point 5): budget amendments via the bootstrap tier only; subagent
review advises, never locks.

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

**Conformance status (Decision 125):** the four DuckLake Lambdas (writer, reader, maintenance,
catalog-dr; T2.17/T2.18, Decision 81/82) are the first personal-account Lambdas and are currently
COUPLED, not conformant: every `aws_lambda_function` resource in `terraform/personal/
ducklake_lambdas.tf`, `ducklake_catalog_dr.tf`, and `ducklake_maintenance.tf` still sets
`source_code_hash = try(filemd5(zip), null)` with no `ignore_changes` lifecycle block. Decision 125
ratifies conformance to this principle as direction (target channel = a dedicated code-deploy CD
path; local `build_lambda --ducklake-only --deploy` demoted to break-glass) without performing the
physical decoupling, which is sequenced as a follow-on (blocked on clearing a pending out-of-budget
IAM delta that would otherwise route the decoupling change's own apply). This file remains the sole
SoT for the apply-model / guard classification -- the interim/target state recorded above extends
that SoT, it does not compete with it.

## 6. Provider lock file consideration (apply-path supply chain)

`.gitignore` currently ignores `.terraform.lock.hcl` (and `terraform/**/.terraform.lock.hcl`), so
the GitHub-hosted apply runner resolves AWS provider versions fresh on every run. On the
highest-privilege workflow (sandbox auto-apply) this is a version-drift / supply-chain surface.

RECOMMENDED (non-blocking, follow-on): un-ignore and commit
`terraform/personal/.terraform.lock.hcl` so the apply runner pins provider versions to a reviewed
lock. Until then, the deterministic guard plus subagent review are the compensating controls.

## 7. Conformance

- New docs/configs MUST follow the reservation in section 3.
- "promotion" MUST be axis-qualified.
- Do not describe product phases as "environments" or platform environments as "phases".
- Platform stays single-account until the live_full trigger (section 4); do not author multi-account
  platform infrastructure before then.
