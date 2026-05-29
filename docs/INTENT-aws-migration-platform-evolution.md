# INTENT — AWS Migration as Platform Evolution Inflection Point

> This is a projection of canonical platform-architecture content for the personal-account migration moment. The authoritative source for tier sequencing remains [docs/ROADMAP-PLATFORM.yaml](./ROADMAP-PLATFORM.yaml); this INTENT proposes specific CDs and tier_items to add there in a follow-on IMPLEMENTATION plan.

## Application Status

- 2026-05-24 -- Open Question #2 resolved: `agent_platform` supersedes the `agent_platform` recommendation; account `REDACTED-PERSONAL-ACCOUNT` confirmed as migration destination (PR for agent/migration-t03-t06-prep).
- 2026-05-29 -- Credential model changed: the runtime/dev surface uses a **static-key + assume-role** chain (`agent_static` IAM key -> `PlatformDev`/`PlatformAdmin`), NOT AWS SSO. Claude Code on the web is the primary dev surface; `~/.aws` is materialised by the cloud-env Setup script (see `bin/setup-cloud-env.sh`). The SSO references in Part 3 ("IAM identity surface", "SSO profile decision") are superseded for the personal account. PlatformDev `max_session_duration` raised to 36000s and its runtime grant codified in `terraform/personal/platform_roles.tf`.

## Status
DRAFT v5 — addresses round-3 critique findings (architect REVISE 13 issues; adversarial REVISE 12 risk findings) and round-4 framing-fix findings on the STRATEGIC-suspension scope (architect REVISE 10 issues; adversarial REVISE 6 risk findings). The STRATEGIC-suspension rule is consistent across all four governance surfaces (AGENTS.md, planning skill, CD.17, this INTENT): STRATEGIC plan-artefact authoring is **blocked at planning time** (`/plan` Step 12d, planning skill Complexity Assessment, plan-critique skill) because the downstream consumer of STRATEGIC plans — `/implement`'s decomposition into atomic recommendations queued for the autonomous executor (`scripts/execute_recommendation.py`) — has a paused executor at the end of the chain. `tier_item.strategic: true` flags in ROADMAP-PLATFORM.yaml remain valid as YAML data; they signal "decompose into a tree of atomic IMPLEMENTATION plans at `/plan` time" per CD.17, NOT "file a STRATEGIC plan-artefact with Work Areas." Other round-3 and round-4 findings resolved inline or explicitly logged in Known Gaps below.

## Intent

The pending AWS migration from the work account (`company-aws-profile`, AWS account `REDACTED-ACCOUNT-ID`) to a personal account is more than an account swap. It is the once-per-platform-lifetime moment to resolve four entangled architectural threads:

1. **AWS resource naming convention.** Current names mix owner-prefix (`bblake-*`), legacy product label (`agent-platform-*`, `ml-testing-*`), and accidental conflations. The migration is the only cheap moment to land a clean, machine-parseable naming scheme that distinguishes shared platform resources from per-project resources.

2. **Platform-vs-product separation as a load-bearing distinction.** The user has chosen the **monorepo + `project_id` dimension** model: platform code stays in this repo and gains a `project_id` field across the agent-tooling Lambda contracts so a second project can be onboarded without architectural change. The earlier split-repo proposal in [`docs/plans/PLAN-platform-extraction-strategy.md`](./plans/PLAN-platform-extraction-strategy.md) is explicitly deferred (not superseded).

3. **Repo rename.** `agent-platform` is doubly misleading; the AWS rename moment is the natural alignment opportunity.

4. **Lambda dependency ordering for `project_id` awareness.** The existing T0/T1 tier_items already encode the dependency graph for CD.10's six Lambdas; the question is whether adding `project_id` reshapes it (answer: no — additive only).

## Migration model (resolves round-2 adversarial #1 prevent_destroy concern)

The personal-account migration is a **fresh deploy in a new AWS account**, not a rename of existing resources in the work account. Operating model:

- The work account (`company-aws-profile`, REDACTED-ACCOUNT-ID) keeps its current Terraform state and existing resources through the migration window. `terraform/main.tf:48-79`'s `prevent_destroy = true` lifecycle blocks on the `formulas_staging`, `formulas_production`, and `data_lake` buckets remain in force and are correct for the work-account state.
- The personal account uses a **separate Terraform state file** pointing at the new account id. T2.1's `terraform apply` runs against this new state file and creates all resources fresh — under the new naming convention from the start. Nothing is destroyed; nothing is renamed in-place.
- After the personal account is operational and T2.2 completes the ops/decisions import, the work-account resources may be decommissioned in a separate follow-on plan (out of scope for this INTENT). Until then, the work-account `prevent_destroy` blocks protect the source-of-truth data.

This sequencing avoids the in-place-rename hazard entirely. S3 buckets are not renamed; new buckets are created.

## How this document relates to existing artefacts

- **`docs/ROADMAP-PLATFORM.yaml`** is canonical for platform sequencing. This INTENT proposes additions to its `candidate_decisions[]` and `tier_items[]` arrays.
- **`docs/ROADMAP-PRODUCT.md`** is canonical for trading-product sequencing. `Phase Infra-Env` interacts with this INTENT's naming convention (Part 3 resolves the env axis: env = account, not name segment).
- **`docs/plans/PLAN-platform-extraction-strategy.md`** is the prior REPORT-ONLY proposing split-repo + submodule. This INTENT formally **defers** that path: retain the document, prepend a leading comment "DEFERRED — see INTENT-aws-migration-platform-evolution for the chosen monorepo+project_id path."
- **CLAUDE.md** documents the Single Portal Invariant and warehouse-as-source-of-truth invariants. Nothing here violates them; Part 5 explicitly forbids client-side COALESCE patterns that would violate them.

## Decision 67 freeze interaction (two distinct concerns)

Decision 67 governs two distinct freezes that this INTENT must navigate:

**1. STRATEGIC-plan-artefact freeze (planning-time gate).** STRATEGIC plan artefacts are blocked at planning time via `/plan` Step 12d, the planning skill's Complexity Assessment, and the plan-critique skill. The rationale is that STRATEGIC plans are decomposed by `/implement` into atomic recommendations, which are queued for the autonomous executor (`scripts/execute_recommendation.py`); the executor is paused pending CD.17 reversal, so authoring STRATEGIC plans produces dead work. Operational consequence for this INTENT: every follow-on plan it spawns is IMPLEMENTATION type. Tier_items with `strategic: true` (e.g. T2.1) get decomposed into a tree of atomic IMPLEMENTATION plans during `/plan` sessions, NOT filed as a single STRATEGIC plan-artefact with Work Areas. The `strategic: true` YAML flag stays in ROADMAP-PLATFORM.yaml because it correctly signals "this work was originally scoped as strategic"; under freeze it just changes the decomposition path.

**2. Lambda-deploy freeze (deploy-time gate, governed by CD.16 + CD.17).** `aws lambda update-function-code` is deferred for Lambda-packaged files until CD.17 reverses. The build-and-validate work proceeds normally; the deploy step carries a `DEFERRED:` stanza in tier_items that touch Lambda-packaged surfaces (T0.12a, T0.15, T0.7a/b/c, T1.1, T1.3). T2.1's Terraform apply may provision Lambda resources in the personal account with stub code; live cutover from work-account Lambdas to personal-account Lambdas happens after CD.17 reverses. Until then, the work-account Lambdas continue to serve.

The two freezes are linked (same triggering decision, same reversal trigger via CD.17) but operate at different gates. This INTENT respects both unconditionally.

---

## Part 1 — Current State Inventory

### 1A — Terraform-side AWS resources

| Current name | Parameterised? | Source | Role |
|--------------|----------------|--------|------|
| `agent-platform-data-lake` | Yes — `${var.s3_bucket_prefix}-data-lake` | `terraform/main.tf:76` (lifecycle prevent_destroy at 78-79) | Product |
| `agent-platform-formulas-discovery` | Yes — same pattern | `terraform/main.tf:35` | Product |
| `agent-platform-formulas-staging` | Yes — same pattern | `terraform/main.tf:46` (lifecycle prevent_destroy at 48-49) | Product |
| `agent-platform-formulas-production` | Yes — same pattern | `terraform/main.tf:61` (lifecycle prevent_destroy at 63-64) | Product |
| `agent-platform-agent-logs` | **No — HARDCODED** | `terraform/main.tf:308`, `terraform/ec2_runner.tf:25` | **Platform** |
| `agent-platform-counters` (DynamoDB) | **No — HARDCODED** | `terraform/dynamodb.tf:7` | Platform: id allocator |
| `${var.project_name}-{handler}` Lambda log groups | Yes | `terraform/data_pipeline.tf:161-201` | Mixed |
| `trading_formulas_db` (Glue database) | Hardcoded literal + var mismatch | `terraform/ec2_runner.tf:181-182`; `var.glue_database_name` default is `formulas_db` | Mixed |
| `agent-platform-production` (Athena workgroup) | Hardcoded in DDL | `terraform/iceberg_tables.tf` (10 view definitions, by view name not line: `ops_recommendations_current`, `ops_decisions_current`, `ops_priority_queue_current`, `telemetry_sessions_current`, `telemetry_phases_current`, `telemetry_steps_current`, `telemetry_agent_invocations_current`, `telemetry_session_summary_30d`, `telemetry_phase_time_distribution`, `telemetry_event_frequency_30d`) | Mixed |
| `agent-platform-lab` (Athena workgroup) | Yes — `var.athena_lab_workgroup` | `terraform/variables.tf:109` | Product |
| `agent-platform-runner` (EC2 tag) | **No — HARDCODED** | `terraform/ec2_runner.tf:242` | Platform (retired in T2.10 per CD.21) |
| `${var.project_name}-github-pat` (Secrets Manager secret) | Yes via var.project_name | `terraform/scheduled_agents.tf:37` (resolves to `agent-platform-github-pat`) | Platform: GitHub OAuth token for Copilot SDK |

### 1B — Non-Terraform hardcoded references

100+ literal references to the legacy names live in code, configs, and runbooks. These are load-bearing — Python module constants, config defaults, prod-path SQL literals, and operational runbook recipes.

#### Python module-level constants and inline SQL

| File:line | Site | Current value |
|-----------|------|---------------|
| `scripts/ops_data_portal.py:53-54` | `_ATHENA_DATABASE`, `_ATHENA_WORKGROUP` | `trading_formulas_db`, `agent-platform-production` |
| `scripts/ops_data_portal.py:893` | `S3_LOG_BUCKET` fallback | `agent-platform-agent-logs` |
| `scripts/ops_writer.py:83-84` | `DATABASE`, `ATHENA_WORKGROUP` | same |
| `scripts/sync_ops.py:65-66` | `_DATABASE`, `_WORKGROUP` | same |
| `scripts/sync_recommendations.py:31` | `_DYNAMODB_TABLE` | `agent-platform-counters` |
| `scripts/session_preflight.py:41-43` | `_ATHENA_DATABASE`, `_ATHENA_WORKGROUP`, `_ATHENA_OUTPUT_LOCATION` | same trio |
| `scripts/session_preflight.py:68` | **Semantic dependency** — `repo_name = ROOT.name; repo_name.lower() in str(sys.executable).lower()` (venv detection keyed off repo directory name) | `agent-platform` (literal not in source, but assumed by the directory-name match) |
| `scripts/session_preflight.py:460,911,936,990,1109` | Inline `FROM trading_formulas_db.{view}` SQL + `S3_LOG_BUCKET` setdefault | hardcoded |
| `scripts/data_quality_runner.py:131,174-175,721-722,738-739` | Default-arg literals + spec fallbacks | same |
| `scripts/cleanup_ops_rec_orphans.py`, `verify_schema_migration.py`, `migrate_schema.py`, `validate_telemetry.py`, `telemetry_schemas.py`, `verifiers/data_quality.py`, `verifiers/causal_chain.py`, `build_lambda.py`, `run_scheduled_agent.py` | Various default args and inline SQL | mix |

#### Lambda-deployed handlers

| File:line | Issue |
|-----------|-------|
| `src/data/handlers/scheduled_agent_handler.py:240` | `workgroup = "agent-platform-production"` |
| `src/data/handlers/scheduled_agent_handler.py:302` | `"SELECT * FROM trading_formulas_db.ops_recommendations_current WHERE status = 'open'"` |
| `src/data/handlers/maintenance_handler.py:60` | Config fallback to `agent-platform-production` |
| `src/data/handlers/feature_handler.py:109` | Config fallback to `trading_formulas_db` |
| `src/common/config.py:137,142,147` | Config-getter fallback defaults |

#### Tests (semantic, not just literal)

| File:line | Site |
|-----------|------|
| `tests/test_session_preflight.py:481,493,505` | Hardcoded `"agent-platform"` as the directory name in venv-detection test fixtures (round-2 adversarial #3) |
| `tests/test_session_preflight.py:51,53,61` | Hardcoded Windows path containing `agent-platform` — same venv-detection fixture surface, NOT SSO-profile fixtures (round-3 adversarial #4 correction) |

#### YAML configs

| File:line | Field |
|-----------|-------|
| `config/agent/data_quality/ops.yaml:4-5` | `database`, `athena_workgroup` |
| `config/agent/data_quality/telemetry.yaml:18-19` | same pair |
| `config/config.company.yaml:13-26` | full set of legacy bucket / db / workgroup names |
| `config/config.yaml.example`, `config/README.md` | template + docs |

#### IAM and trust policies (round-2 adversarial #2)

| File:line | Reference | Round-2 risk |
|-----------|-----------|--------------|
| `terraform/ec2_runner.tf:181-182` | `arn:aws:glue:...:database/trading_formulas_db` + `table/trading_formulas_db/*` | Personal-account IAM needs new ARN basis |
| `terraform/ec2_runner.tf:236` | user_data writes `[profile company-aws-profile]` | Personal-account user_data uses new profile |
| `terraform/oidc.tf` (NEW per T2.10) — not yet authored | GitHub OIDC trust policy `sub` claim of form `repo:benjamin-blake/agent-platform:*` | **`sub` claim is NOT URL-based**: GitHub URL redirects do NOT update the OIDC sub. After repo rename, every CI `AssumeRoleWithWebIdentity` fails until the trust policy is updated atomically. T2.15 must update trust policy in the same change as the rename. |

#### Secrets Manager

| File:line | Reference |
|-----------|-----------|
| `terraform/scheduled_agents.tf:37` | `name = "${var.project_name}-github-pat"` → resolves to `agent-platform-github-pat` |
| `CLAUDE.md` "Copilot SDK auth" gotcha (and `docs/PROJECT_CONTEXT.md`, `docs/GETTING_STARTED.md:893`, `src/data/handlers/CLAUDE.md:25`) | Hardcoded secret name in operational recipe (`aws secretsmanager put-secret-value --secret-id agent-platform-github-pat ...`) |

Secrets Manager secrets cannot be renamed — only deleted (with 7-30 day deletion window) and re-created. T2.15 sweep must update the secret-name references AND the migration plan must create a new secret in the personal account, not rename. (Round-2 adversarial #9.)

#### Operational runbooks

| File | Content |
|------|---------|
| `CLAUDE.md` "Re-enable Lambda scheduled agents" | Hardcodes `agent-platform-hourly-scheduled-agents`, `agent-platform-scheduled-agent-dispatcher`, `agent-platform-agent-logs` |
| `CLAUDE.md` "Self-hosted GitHub Actions runner" | Hardcodes `agent-platform-runner` |
| `CLAUDE.md` "Copilot SDK auth requires OAuth token" gotcha | Hardcodes `agent-platform-github-pat` |

#### Documentation, tests, setup scripts (sweep targets)

`bin/setup-cloud-env.sh`, `setup.py`, `tests/test_setup.py`, `README.md`, `docs/GETTING_STARTED.md`, `.github/copilot-instructions.md`, `.github/prompts/`, `.claude/skills/`, `.agents/skills/`.

### 1C — Summary of category errors

1. The `agent-logs` bucket carries the product bucket prefix despite being platform.
2. The `var.project_name` indirection compresses platform and product Lambdas into one namespace.
3. The Glue database name (`trading_formulas_db`) suggests product-only but houses platform ops tables too.
4. The `agent-platform-production` Athena workgroup is used for both platform ops writes and product market-data writes.
5. Resource names are duplicated in Python module constants, YAML configs, and Terraform — none reference a shared source.
6. Repo name `agent-platform` leaks into semantic checks (venv detection in `session_preflight.py:68`) and test fixtures, not just literal strings.
7. GitHub OIDC trust policy `sub` claim is repo-name-bound; URL redirects do not update it.

---

## Part 2 — Architectural Commitment: Monorepo + `project_id`

### What we are committing to

**Code:** all platform code and trading-product code remain in this repository. CD.10's six Lambdas are platform-shared and live under `src/lambdas/`. Product Lambdas live under `src/data/handlers/`.

**Schemas:** `RecPayload` and `DecisionPayload` (per T0.12) gain a `project_id` field via **two-phase rollout** (Part 5):
- Phase A: `Optional[str] = None` ships in T0.12a; default `"trading-system"` injected at write time, sourced from `config/project_registry.yaml`'s `default_project_id` attribute (not a literal in Lambda code — round-2 architect #14).
- Phase B: flipped to `Annotated[str, DqNotNull()]` in T2.17, after T2.2 backfill.

Allowed values live in a runtime-loaded YAML registry; **`platform` is a reserved project_id** that the registry loader refuses (round-2 adversarial #6).

**Lambdas:** all six platform Lambdas accept and persist `project_id`. The `query` Lambda's verbs filter by `project_id`, defaulting to the calling principal's bound project. Cross-project queries are restricted to `PlatformAdmin`.

**IAM:** `PlatformDev` and `PlatformAdmin` permission sets per T0.3 exit criteria. Principal-to-project binding lives in IAM session tags AND in a small lookup in `src/lambdas/_shared/principal_binding.py` (consumed by all Lambda handlers); T0.7c's amendment (Part 8) and T1.2's verb expansion together implement the binding enforcement.

**Storage:** Iceberg ops tables gain a `project_id` column. SCD2 partitioning continues to use `day(last_updated_timestamp)` per CD.9; `project_id` is NOT a partition key.

### What we are explicitly NOT committing to

- **Split repo extraction.** PLAN-platform-extraction-strategy.md deferred.
- **Cross-employer security boundary.** Irrelevant under monorepo.
- **`rec_project_dim` star-schema dimension.** Direct column suffices.
- **Client-side `COALESCE(project_id, ...)` in any writer.** Resurrection anti-pattern. Forbidden by a presubmit AST gate (not just grep — round-2 adversarial #8) in `validate.py` that walks `scripts/ops_*.py`, `src/lambdas/`, and the agent SDK for any `COALESCE` call where the first argument resolves to a `project_id` symbol.

### Fate of `docs/plans/PLAN-platform-extraction-strategy.md`

Marked DEFERRED, not superseded; retains analytical value. Leading comment prepended in the follow-on implementing plan.

---

## Part 3 — AWS Resource Naming Convention

### The rule

Two categories. Each has one naming pattern. **`platform` is a reserved value of `project_id`** — registry loader refuses it; CI gate confirms (round-2 adversarial #6).

**Category 1 — Platform-shared resources:**

```
Pattern:  {owner}-platform-{purpose}     (Lambda, S3, DynamoDB, Athena workgroup, EC2 tag)
          {owner}_platform               (Glue database — underscores for SQL)
Examples: agent-platform-agent-logs           agent-platform-counters
          agent-platform-log-rec              agent-platform-query
          agent-platform-update-rec           agent-platform-log-decision
          agent-platform-list-tools           agent-platform-maintenance
          agent-platform-ops-compaction       agent-platform-scheduled-agent
          agent-platform-github-pat (Secrets Manager — newly created, not renamed)
          agent-platform-production           (Athena workgroup for ops + telemetry writes)
          agent_platform                       (Glue database for ops_* and telemetry_* tables)
```

**Category 2 — Project-scoped resources:**

```
Pattern:  {owner}-{project_id}-{purpose}
          {owner}_{project_id}
Examples: bblake-trading-system-data-lake             bblake-trading-system-formulas-discovery
          bblake-trading-system-formulas-staging      bblake-trading-system-formulas-production
          bblake-trading-system-fetch-market-data     (Lambda)
          bblake-trading-system-compute-features      (Lambda)
          bblake-trading-system-lab                   (Athena workgroup for PySR)
          bblake-trading-system-production            (Athena workgroup for product writes)
          bblake_trading_system                        (Glue database for market_data, formula_lineage, etc.)
```

### Telemetry table routing (resolves round-2 adversarial #4 + architect #3)

**All `telemetry_*` tables live in `agent_platform` Glue database** alongside the `ops_*` tables. They are operational/platform observability data, not product business data. Both ops and telemetry writes go through `agent-platform-production` Athena workgroup. The 10 enumerated views (Part 1A) all land in `agent_platform`:

| View | Database | Workgroup |
|------|----------|-----------|
| `ops_recommendations_current` | `agent_platform` | `agent-platform-production` |
| `ops_decisions_current` | `agent_platform` | `agent-platform-production` |
| `ops_priority_queue_current` | `agent_platform` | `agent-platform-production` |
| `telemetry_sessions_current` | `agent_platform` | `agent-platform-production` |
| `telemetry_phases_current` | `agent_platform` | `agent-platform-production` |
| `telemetry_steps_current` | `agent_platform` | `agent-platform-production` |
| `telemetry_agent_invocations_current` | `agent_platform` | `agent-platform-production` |
| `telemetry_session_summary_30d` | `agent_platform` | `agent-platform-production` |
| `telemetry_phase_time_distribution` | `agent_platform` | `agent-platform-production` |
| `telemetry_event_frequency_30d` | `agent_platform` | `agent-platform-production` |

### Environment axis (resolves round-1 architect #9)

`Phase Infra-Env` (ROADMAP-PRODUCT.md:640-720): environment is encoded by **account isolation**, not name suffix. Each environment account uses the same two-pattern rule.

### Why `{owner}` prefix, why `platform` literal, hyphen vs underscore discipline

(Unchanged from v2.) Single source of truth in Terraform locals + Python helper `src/common/aws_naming.py`.

```hcl
locals {
  platform_prefix   = "${var.owner_prefix}-platform"
  project_prefix    = "${var.owner_prefix}-${var.project_id}"
  glue_platform_db  = replace(local.platform_prefix, "-", "_")
  glue_project_db   = replace(local.project_prefix,  "-", "_")
}
```

### Migration mapping (current → proposed)

| Current name | Category | Proposed name |
|--------------|----------|---------------|
| `agent-platform-data-lake` | Project | `bblake-trading-system-data-lake` |
| `agent-platform-formulas-discovery` | Project | `bblake-trading-system-formulas-discovery` |
| `agent-platform-formulas-staging` | Project | `bblake-trading-system-formulas-staging` |
| `agent-platform-formulas-production` | Project | `bblake-trading-system-formulas-production` |
| `agent-platform-agent-logs` | **Platform** | `agent-platform-agent-logs` |
| `agent-platform-counters` | Platform | `agent-platform-counters` |
| `agent-platform-github-pat` (Secrets Manager) | Platform | `agent-platform-github-pat` (newly created in personal account; secret rotation procedure in CLAUDE.md updated) |
| `trading_formulas_db` (Glue) | **Split** | `agent_platform` (ops_* + telemetry_*) + `bblake_trading_system` (market_data, formula_lineage) |
| `agent-platform-production` (Athena workgroup) | **Split** | `agent-platform-production` (ops + telemetry) + `bblake-trading-system-production` (product) |
| `agent-platform-lab` (Athena workgroup) | Project | `bblake-trading-system-lab` |
| `agent-platform-fetch-market-data` (Lambda) | Project | `bblake-trading-system-fetch-market-data` |
| `agent-platform-scheduled-agent-dispatcher` (Lambda) | Platform | `agent-platform-scheduled-agent-dispatcher` |
| `agent-platform-findings-processor` (Lambda) | Platform | `agent-platform-findings-processor` |
| `agent-platform-ops-compaction` (Lambda) | Platform | `agent-platform-ops-compaction` |
| CD.10 future Lambdas | Platform | `agent-platform-{log-rec,log-decision,query,update-rec,list-tools,maintenance}` |
| `agent-platform-runner` (EC2 tag, work account) | n/a | **No rename.** Retired in T2.10 per CD.21. |

### Cross-database query policy

After the split, cross-DB queries use fully-qualified table names (`agent_platform.ops_recommendations` JOIN `bblake_trading_system.formula_lineage`). Workgroup routing per verb category: ops + telemetry verbs → `agent-platform-production`; product verbs → `bblake-trading-system-production`; cross-DB joins use the platform workgroup by default (cost attribution lands on platform side, reflecting that the join is operational analytics). T0.7c amendment (Part 8) implements this routing.

### IAM identity surface (three distinct concerns)

| Surface | Current value | Proposed value |
|---------|---------------|----------------|
| SSO CLI profile (`~/.aws/config`) | `company-aws-profile` | See "SSO profile decision" below — conditional on Known Gap #2 closure |
| IAM Identity Center permission set | n/a (work account differs) | `PlatformDev`, `PlatformAdmin` (per T0.3 exit criteria) |
| IAM role policies embedding resource names | `arn:aws:glue:...:database/trading_formulas_db` etc. (`terraform/ec2_runner.tf:181-182`) | Derived from Terraform locals; T0.16 produces IAM translation table |
| **GitHub OIDC trust policy `sub` claim** | `repo:benjamin-blake/agent-platform:*` (planned by T2.10) | `repo:benjamin-blake/agent-platform:*` — **MUST update atomically with T2.15 rename**. URL redirects do NOT update OIDC subs (round-2 adversarial #2). |

### Pre-T2.1 freeze on legacy `agent-logs` bucket writes (resolves round-2 architect #6)

The current `agent-platform-agent-logs` bucket is the active outbox drain target for `OpsWriter`. Between T0.15 (code-side decoupling lands a config-driven bucket name) and T2.1 (personal-account bucket exists), writes must continue against the legacy bucket. After T2.1 succeeds and T2.2 imports complete, a new tier item **T2.18b** (Part 8) flips the active bucket to `agent-platform-agent-logs` and freezes the legacy bucket as read-only via S3 Bucket Policy. The legacy bucket stays read-only for one drain cycle (so any in-flight outbox can be read but not appended) then is decommissioned with the work account.

### SSO profile decision (conditional on Known Gap #2)

> SUPERSEDED 2026-05-29 (see Application Status): the runtime/dev surface no longer uses AWS SSO. The profile name `agent_platform` is retained, but it is now a **static-key + assume-role** profile (source `agent_static` -> role `PlatformDev`), not an SSO profile. The profile-name decoupling reasoning below still holds; only the SSO mechanism is replaced.

Resolved 2026-05-24 (PR for agent/migration-t03-t06-prep): the SSO profile name is `agent_platform`. The personal account `REDACTED-PERSONAL-ACCOUNT` (current `personal-bedrock-profile` profile target) is confirmed as the migration destination -- `personal-bedrock-profile` is folded into `agent_platform` during the T0.3 cleanup. The profile name `agent_platform` is intentionally decoupled from the `agent-platform-*` resource prefix: profile names live on the developer machine and need to admit non-bblake-owned or assumed-CI-role profiles cleanly, while resource names live in AWS-global namespace and benefit from owner-coupling. Known Gap #2 closed.

---

## Part 4 — Repo Rename

### Why rename

`agent-platform` was an honest name in 2023; today the repo is an agentic platform + trading product, neither machine-learning-in-the-classical-sense nor sandbox.

### Candidates

| Candidate | Pros | Cons |
|-----------|------|------|
| **`agent-platform`** (recommended) | Matches AWS naming convention; clearest ownership; project-agnostic | Less descriptive |
| `agentic-platform` | Descriptive of methodology | Generic-enough to collide |
| `self-improving-platform` | Captures North Star | Long; aspirational tone |
| `recursive-agents` | Memorable | Vague substrate |

Recommendation: **`agent-platform`**.

### Naming-collision note (round-2 architect #12)

The repo name `agent-platform` and the AWS resource prefix `agent-platform-*` share spelling. This is deliberate (single identifier across surfaces) and unproblematic when the directory hierarchy ever introduces project subtrees (e.g. `projects/trading-system/`): the repo name remains platform-scoped because the platform code spans the repo root and the project subtree is just one consumer. If the directory restructure ever happens (Open Question #5), the convention is preserved.

### Migration mechanics (revised — round-2 adversarial #2 + #3 + architect #10)

GitHub integration survivability categorised:

| Surface | Survives rename? | Action required |
|---------|------------------|-----------------|
| HTTPS clone URLs (HTTP 301 redirect) | Yes | None |
| SSH clone URLs (HTTP 301 redirect) | Yes | None |
| Webhooks (repo-id bound) | Yes | None |
| OAuth Apps / GitHub Apps (repo-id bound) | Yes | None |
| GitHub Actions secrets (repo-id bound) | Yes | None |
| Branch protection rulesets | Yes | None |
| GHAS settings (secret scan, push protection, CodeQL, Dependabot) | Yes | None |
| Self-hosted runner registration (repo-id bound) | Yes | None |
| **GitHub OIDC trust policy `sub` claim** | **NO — sub claim is repo-name-bound, not URL-redirected** | **Update IAM trust policy atomically with rename — T2.15 includes this step** |
| `raw.githubusercontent.com` URL embeds (README badges etc.) | Partial — redirects work but cached CDN paths may break | One-time CDN cache flush via direct push to renamed repo |
| Third-party CI badges (Codecov, etc.) | Partial — service-specific | Update each service's repo configuration |
| Local clone directory names (`~/Git Repos/agent-platform/`) | Operator must rename manually | Document one-time `git remote set-url` + directory rename procedure in CLAUDE.md |

**Semantic dependency on repo directory name** (round-2 adversarial #3): `scripts/session_preflight.py:68` keys venv-detection off `ROOT.name.lower()`. After repo rename + local directory rename, `ROOT.name = "agent-platform"` and the existing venv at `.venv/Scripts/python.exe` resolves because the new name is also `in` the executable path. But mixed-state operators (renamed remote, unrenamed local) would have `ROOT.name = "agent-platform"` while venv path includes neither (if they re-cloned to a fresh path). T0.15 includes a semantic refactor: replace the `ROOT.name` heuristic with an explicit `VENV_PATH` env var (set by T0.5 session-start hook) OR with a check that the venv directory contains a marker file written by the setup script. Tests at `tests/test_session_preflight.py:481,493,505` are updated to use the new mechanism. (Listed in T0.15's files_in_scope below.)

### Sequencing

Rename happens BEFORE T2.1 and is itself preceded by:
- T0.16 (IAM translation table — needs old-account audit done while old account is live)
- T0.17 (pre-T2.1 name reservation — needs personal account existing per T0.3)

Within T2.15 the rename and OIDC trust-policy update are a single atomic operation (Terraform applied at the same time as the GitHub setting change). Reference sweep follows immediately to flush any stale literals.

---

## Part 5 — `project_id` Schema Extension — Two-Phase Rollout

### The gap

T0.12 (Annotated-Pydantic schema-as-code foundation) was completed 2026-05-19. Verified: `grep -c "project_id" src/schemas/rec.py src/schemas/decision.py` returns `0` and `0`.

### Phase A — Optional with default sourced from registry (T0.12a)

```python
# src/schemas/rec.py (and decision.py, telemetry payloads where applicable)
project_id: Annotated[
    str | None,
    Field(default=None, description="Project identifier; None on legacy rows pre-T2.2 backfill"),
] = None
```

At write time inside `log-rec` / `log-decision` Lambda handlers, the handler reads `default_project_id` from `config/project_registry.yaml` (loaded once at cold-start) and injects it if `payload.project_id is None`. **The default literal `"trading-system"` does not appear in handler code** — it lives once in `config/project_registry.yaml` (round-2 architect #14).

```yaml
# config/project_registry.yaml
default_project_id: trading-system
reserved_project_ids: [platform]      # forbidden values — registry loader refuses (round-2 adversarial #6)
projects:
  - id: trading-system
    name: ML Trading System
    onboarded: "2026-05-19"
    principal_bindings:
      - PlatformDev
```

Legacy outbox files drain because the field is Optional. New writes carry the value.

### Backfill — one-off server-side ETL inside T2.2's window

After T2.1 deploys the personal-account infrastructure and T2.2 imports ops + decisions via `log-rec` / `log-decision` in `import_mode=true`, a one-off ETL job (inside T2.2's exit criteria) sets `project_id = "trading-system"` on every imported row by re-issuing the writes through the same Lambdas with admin-scoped `import_mode=true`. Preserves Single Portal Invariant. Tagged with `source = "project-id-backfill"`.

### Phase B — Flip to DqNotNull (T2.17)

After backfill confirms zero NULL, T2.17 changes schema to `Annotated[str, DqNotNull()]`. Iceberg DDL generator emits NOT NULL on next run. DQ runner flags any NULL writes.

### BackfillRequiredError is scoped to T2.2 window only (resolves round-2 architect #4)

In v2 this was framed as a general handler contract. Corrected: `update-rec` returns `BackfillRequiredError` (409) ONLY during T2.2's import window, for the narrow case where an `update-rec` call lands against a row that was imported with `project_id` still NULL (the backfill ETL has not yet run for that specific row). The error is a transient guard, not an operating-mode behaviour. After T2.2 completes (zero NULL rows), the code path is unreachable; T2.17 may delete it.

### Why a runtime YAML registry, not `DqAcceptedValues`

`DqAcceptedValues` compiles the allowed-values set into the Pydantic model; adding a project requires redeploy. Runtime YAML registry loaded at Lambda cold-start lets new projects onboard via YAML edit + config reload. Reserved-id check (`platform`) and principal-binding lookup live in the same registry.

### Lambda-handler impact

- T0.7a/b: handlers accept `project_id`; default from registry.
- T0.7c: every list_* verb gains optional `project_id` filter; routing to workgroup per verb category (Part 3 cross-DB policy). Cross-project queries restricted to `PlatformAdmin` via principal-binding lookup in `src/lambdas/_shared/principal_binding.py`.
- T1.1 (update-rec): preserves existing `project_id`. Returns `BackfillRequiredError` only for the narrow T2.2-window case.
- T1.3 (list-tools): `model_json_schema()` reflects new field automatically.
- Agent SDK (T0.8): accepts `project_id` kwarg.

### Iceberg table impact

T0.13 emits the nullable column. Phase-B flip is a separate DDL change in T2.17. Read paths use `project_id IS NULL OR project_id = :principal_project`, NOT `COALESCE`.

---

## Part 6 — Lambda Migration Ordering — Validation and Deltas

### Live YAML state of T0.7a/b/c (round-2 architect #1)

The live YAML at `ROADMAP-PLATFORM.yaml:1000,1022,1040` has:

```yaml
- id: T0.7a
  depends_on: [T0.6, T0.12, T0.13]
- id: T0.7b
  depends_on: [T0.6, T0.12, T0.13]
- id: T0.7c
  depends_on: [T0.6, T0.12, T0.13]
```

For T0.12a to actually gate T0.7a/b/c, **the follow-on implementing plan must amend each of T0.7a's, T0.7b's, and T0.7c's depends_on list to insert `T0.12a`**. This is captured in the Part 8 amendments table.

### Depends_on graph after amendments

| Lambda | Tier item | Depends on |
|--------|-----------|------------|
| Pydantic schemas | T0.12 (complete) | — |
| `project_id` schema amendment | T0.12a (new) | T0.12 |
| Iceberg DDL gen | T0.13 | T0.12, T0.12a |
| Lambda skeleton + IAM | T0.6 | T0.3 |
| log-rec | T0.7a | T0.6, T0.12, T0.12a, T0.13 |
| log-decision | T0.7b | T0.6, T0.12, T0.12a, T0.13 |
| query | T0.7c | T0.6, T0.12, T0.12a, T0.13 |
| Agent SDK shim | T0.8 | T0.7a, T0.7b, T0.7c |
| update-rec | T1.1 | T0.7a, T0.7c, T0.8 |
| query verb expansion | T1.2 | T0.7c, T0.8 |
| list-tools | T1.3 | T0.7a, T0.7b, T0.7c, T1.1 |
| maintenance | T1.4 | T0.6 |
| SLOs + alarms | T1.9 | T0.7a/b/c, T1.1, T1.3, T1.4 |

### Validation answer

Yes — ordering is correctly planned. Adding `project_id` is additive. The amendments below to T0.7a/b/c and CD.10/CD.16 gate lists complete the contract.

---

## Part 7 — Proposed Candidate Decisions (CDs)

### CD.25 — AWS resource naming convention

(Detail unchanged from v2.) **Gates:** [T0.15, T2.0, T2.1, T2.4, T2.16, T2.18b].

### CD.26 — Monorepo + `project_id` dimension; split-repo extraction deferred

(Detail unchanged from v2; adds reserved-id `platform`.) **Gates:** [T0.12a, T0.7a, T0.7b, T0.7c].

### CD.27 — Repo rename to `agent-platform`

**Detail:** Rename precedes T2.1. Self-hosted runner registration survives. **GitHub OIDC trust policy MUST be updated atomically with the rename** — `sub` claim changes from `repo:benjamin-blake/agent-platform:*` to `repo:benjamin-blake/agent-platform:*`. URL redirects do not propagate to OIDC subs. Reference sweep covers the broad surface including legacy resource names in operational runbooks AND the semantic `session_preflight.py:68` directory-name dependency AND test fixtures. Sweep dedups with T-1.0 (ROADMAP.md sweep — already complete) by re-running the same grep patterns against new targets.

**Gates:** [T2.15, T2.1]. (T2.13 is a downstream consumer that *uses* the renamed repo for the public flip but does not *establish* the rename, so per CD-gate semantics it is not a gate of CD.27 — round-3 architect #12.)

### CD.28 — `project_id` required on all platform Lambda writes (two-phase)

(Detail unchanged from v2; Phase A reads default from registry, not handler literal; reserved-id `platform` enforced at BOTH (a) the registry loader (runtime) AND (b) a Pydantic `field_validator` on `project_id` that consults the same registry (round-3 adversarial #11 + architect #7). Defense in depth: registry-bypass paths like tests, import-mode T2.2 writes, and direct Pydantic instantiation cannot land `project_id = "platform"`.)

**Gates:** [T0.12a, T0.7a, T0.7b, T1.1, T2.2, T2.17].

### CD.10 and CD.16 amendments

CD.10 currently lists gates `[T0.6, T0.7a, T0.7b, T0.7c, T1.1, T1.2, T1.3, T1.4]`. Both CD.10 AND CD.16 (per-Lambda deploy gating) must add `T0.12a` AND `T2.17` to their gates so both the Phase-A field-addition AND the Phase-B DqNotNull flip are treated as gate dependencies (round-2 architect #2 + round-3 architect #8). T2.17 changes the Pydantic model in a way that requires Lambda redeploy (DqNotNull → 4xx on null), which is exactly the per-Lambda-redeploy trigger CD.16 governs.

---

## Part 8 — Proposed Tier Items

### T0.12a — `project_id` Phase A schema amendment + runtime registry

**Intent:** Add `project_id: Optional[str] = None` to `RecPayload`, `DecisionPayload`, telemetry payloads. Create `config/project_registry.yaml` with `default_project_id: trading-system`, `reserved_project_ids: [platform]`, and `projects: [...]` list. Add registry loader at `src/common/project_registry.py` that refuses reserved ids and exposes `default_project_id`. Lambda handlers in T0.7a/T0.7b inject the default from registry at write time (no literal in handler code).

**depends_on:** [T0.12]
**files_in_scope:** `src/schemas/rec.py`, `src/schemas/decision.py`, `src/schemas/telemetry.py` (if exists), `config/project_registry.yaml` (new), `src/common/project_registry.py` (new)
**effort:** S
**strategic:** false
**related_candidate_decisions:** [CD.26, CD.28]

### T0.15 — Code-side resource name decoupling + semantic refactor + AST gate

**Intent:** Per CD.25 and the Part 1B inventory. Refactor Python module-level constants and inline SQL to consume `src/common/aws_naming.py` rather than literals. Update YAML configs and Lambda handlers. **Semantic refactor of `scripts/session_preflight.py:68`**: replace `ROOT.name`-based venv detection with explicit `VENV_PATH` env var (sourced from T0.5's session-start hook), with fallback to a marker-file check at `.venv/.platform-marker` for environments not running the session-start hook (round-2 adversarial #3). The refactor must work BOTH pre- and post-rename so it can ship independently of T2.15 timing (round-3 architect #1). Update `tests/test_session_preflight.py:51,53,61,481,493,505` accordingly (all six lines are venv-detection fixtures per round-3 adversarial #4 correction; lines 51/53/61 are NOT SSO-profile fixtures despite earlier mis-categorisation). Add presubmit gate in `validate.py` combining: (a) literal-grep for `trading_formulas_db|agent-platform-*|agent-platform-*|agent-platform` outside the helper, (b) **AST-based check** that walks `scripts/ops_*.py`, `src/lambdas/`, `scripts/agent_sdk/` for any `COALESCE(project_id, ...)` call (round-2 adversarial #8). AST check uses `ast.NodeVisitor` over Python source. For SQL literals inside string arguments, the gate vendors `sqlglot` (small, well-maintained SQL AST library — round-3 adversarial #8) rather than rolling a bespoke parser; falls back to substring match when `sqlglot` cannot parse. Operational runbooks in CLAUDE.md are NOT swept here — they live in T2.15.

**depends_on:** [T0.12a, T0.5]
**files_in_scope:** All Part 1B Python module-level constants + YAML config files + `src/common/aws_naming.py` (new) + `scripts/session_preflight.py:68` (semantic refactor) + `tests/test_session_preflight.py` (lines 51,53,61,481,493,505) + `scripts/validate.py` (grep + AST gates) + `requirements.txt` (vendor `sqlglot`) + `src/data/handlers/*.py` (Lambda handler defaults)
**effort:** M
**strategic:** false
**related_candidate_decisions:** [CD.25, CD.26]

### T0.16 — Personal-account IAM audit and policy translation

(Unchanged from v2.) **depends_on:** [T0.3]. **effort:** XS.

### T0.17 — Pre-T2.1 name reservation (actual bucket creation, not just describe)

**Intent:** S3 bucket names are globally unique; the only mechanism that reserves a name is `aws s3api create-bucket` (round-3 adversarial #3 correction). The reservation script `scripts/aws_name_reservation.py` calls `head-bucket` first (probe), then `create-bucket` against every target name to claim it, then verifies ownership. DynamoDB / Glue / Secrets Manager names are account-scoped; `describe-table` / `get-database` probe suffices. If any S3 name is taken globally, the script exits non-zero with the conflict list and the operator chooses to suffix-disambiguate or change `project_id`. The script is idempotent — re-runs against already-reserved buckets succeed silently.

**depends_on:** [T0.3]
**files_in_scope:** `scripts/aws_name_reservation.py` (new), `docs/contracts/aws-name-reservation-report.md` (output)
**effort:** XS
**strategic:** false
**related_candidate_decisions:** [CD.25]

### T2.0 — Terraform variable + locals refactor

**Intent:** Refactor `terraform/variables.tf`: retire `var.project_name`, `var.s3_bucket_prefix`. Introduce `var.owner_prefix`, `var.project_id`. Introduce `terraform/locals.tf`. **Does NOT include the runner-tag rename** (work-account resource retired in T2.10). **Does NOT touch the work-account `prevent_destroy` lifecycle blocks** — those protect work-account state during migration window (Migration Model section). The personal-account Terraform uses a fresh state file and creates new resources; no in-place rename occurs.

**depends_on:** [T0.3]
**files_in_scope:** `terraform/variables.tf`, `terraform/main.tf`, `terraform/data_pipeline.tf`, `terraform/dynamodb.tf`, `terraform/scheduled_agents.tf`, `terraform/cost_monitoring.tf`, `terraform/monitoring.tf`, `terraform/locals.tf` (new)
**effort:** S
**strategic:** false
**related_candidate_decisions:** [CD.25]

### T2.15 — Repo rename + atomic OIDC trust update + full reference sweep

**Intent:** Per CD.27. GitHub rename and IAM trust-policy update happen in different control planes (GitHub Settings API vs `aws iam update-assume-role-policy`), so true atomicity is impossible. Procedure that achieves equivalent safety via both-subs-present overlap (round-3 adversarial #10):

(a) Pre-step: Update GitHub OIDC trust policy to include BOTH `sub` values via a wildcard or two-element list — `repo:benjamin-blake/agent-platform:*` AND `repo:benjamin-blake/agent-platform:*` — before rename. CI runs continue under the old name's sub.
(b) Disable any in-flight scheduled workflows (`gh workflow disable` for the cron-driven ones) to minimise the rename window's CI traffic.
(c) Rename GitHub repo `agent-platform` → `agent-platform` via GitHub settings API.
(d) Verify a CI run on the renamed repo succeeds with OIDC under the new sub.
(e) Post-step: Remove the old `repo:benjamin-blake/agent-platform:*` sub from trust policy (no longer reachable).
(f) Re-enable disabled workflows.
(g) Verify self-hosted runner registration survives (`gh api repos/benjamin-blake/agent-platform/actions/runners` returns the existing runner without re-registration; if absent, re-register per CLAUDE.md — round-3 architect #11).
(h) Reference sweep across: `CLAUDE.md` (entire file plus operational runbooks for re-enabling Lambda scheduled agents, self-hosted runner, and Copilot SDK OAuth token rotation — last hardcodes `agent-platform-github-pat`), `AGENTS.md`, all `docs/`, all `scripts/`, all `terraform/` (comments AND `ec2_runner.tf:236` user_data — round-3 architect #9), `README.md`, `setup.py`, `bin/`, `tests/`, `.github/copilot-instructions.md`, `.github/prompts/`, `.claude/skills/`, `.claude/commands/`, `.agents/skills/`, `.agents/workflows/`. Sweep dedups against T-1.0 (already complete): re-runs the same grep predicates with new search strings; T-1.0's swept-file inventory is a starting set, not authoritative for new patterns.

**depends_on:** [T-1.0, T0.15, T0.16]
**files_in_scope:** repo-wide grep targets; `terraform/oidc.tf` (atomic trust-policy update)
**effort:** S
**strategic:** false
**related_candidate_decisions:** [CD.27]

### T2.16 — Glue database split + Athena workgroup split (atomic)

**Intent:** Per CD.25 and the Part 3 telemetry-routing table. The single `trading_formulas_db` Glue database splits into `agent_platform` (ops_recommendations, ops_decisions, ops_session_log, AND all telemetry_* tables — Part 3 routing) and `bblake_trading_system` (market_data, formula_lineage, formula_outcomes, ab_tests). The single `agent-platform-production` Athena workgroup splits into `agent-platform-production` (ops + telemetry writes) and `bblake-trading-system-production` (product writes). schema_to_iceberg generator (T0.13) consumes a class-level `@target_database` annotation with semantic values (`platform` or `project`), NOT physical DB names (round-2 architect #8) — generator resolves to physical name via `local.glue_platform_db` / `local.glue_project_db`.

**Atomic view re-creation:** All 10 views (enumerated by name in Part 3 telemetry routing table) re-created in one `null_resource` with `create_before_destroy = true`. View names (not line numbers, round-2 architect #13): `ops_recommendations_current`, `ops_decisions_current`, `ops_priority_queue_current`, `telemetry_sessions_current`, `telemetry_phases_current`, `telemetry_steps_current`, `telemetry_agent_invocations_current`, `telemetry_session_summary_30d`, `telemetry_phase_time_distribution`, `telemetry_event_frequency_30d`. CI gate verifies all 10 views resolve before declaring T2.16 complete.

**depends_on:** [T0.13, T0.15, T2.0]

T0.15 dependency added per round-3 adversarial #7: Lambda handlers (`scheduled_agent_handler.py:240,302`, `feature_handler.py:109`, `maintenance_handler.py:60`) hardcode the legacy DB / workgroup. If T2.16 ships before T0.15 decouples those references, deployed Lambdas query a non-existent DB after the split.

**files_in_scope:** `terraform/iceberg_tables.tf` (10 named views above), `scripts/schema_to_iceberg.py` (new file — created in T0.13 per round-3 adversarial #12; this T2.16 amendment extends it with the semantic @target_database annotation), Pydantic schemas (per-model annotation)
**effort:** M
**strategic:** false
**related_candidate_decisions:** [CD.25]

### T2.17 — `project_id` Phase B (DqNotNull flip)

**Intent:** After T2.2 import + backfill, change schema from `Optional` to `Annotated[str, DqNotNull()]`. T0.13 regenerates DDL with NOT NULL. Add DQ check for new constraint. **Reversibility:** within a small window before NOT NULL propagates to deployed Iceberg table, a revert is purely a schema-change + redeploy. After propagation, a revert needs an explicit `ALTER TABLE` (Open Question #7 — deferred to T2.17 implementing plan).

**depends_on:** [T2.2]
**files_in_scope:** Pydantic schemas, `scripts/schema_to_iceberg.py`, DQ YAMLs (drift check for project_id NULL)
**effort:** XS
**strategic:** false
**related_candidate_decisions:** [CD.28]

### T2.18 — DynamoDB counters table migration with concrete quiescence mechanism

**Intent:** Per round-2 adversarial #5. Counter race-window mitigation requires an explicit quiescence mechanism — `OpsWriter` has no native lock. Procedure (T2.18 strictly precedes T2.2; T2.2's depends_on extends to include T2.18):

1. Add a feature flag `OPS_WRITER_FROZEN=true` env var support to `scripts/ops_writer.py` that causes BOTH `write()` AND `compact()` to return `403 Frozen` immediately, with no DynamoDB call and no S3 write (round-3 adversarial #2: `compact()` is the path that drains the outbox into Iceberg, and freezing only `write()` leaves the resurrection path open). Add this support in T2.18's first commit. The freeze flag itself is a code change to a Lambda-bundled module; per the standard Decision-67 DEFERRED-deploy rule, the work-account Lambda continues running the un-frozen code while the personal-account Lambda picks up the frozen code on its first cold-start in the new account. Quiescence in the WORK account is therefore enforced via an alternative mechanism: an IAM-policy deny rule attached to the work-account Lambda's role that blocks `dynamodb:UpdateItem` on the counters table — a Terraform-only change, no Lambda redeploy needed (round-3 architect #3).
2. Apply the IAM deny rule on the work-account Lambda counters access. Verify next `file_rec` against work account returns 403.
3. Verify quiescence on BOTH write AND drain paths: `aws dynamodb scan --table-name agent-platform-counters --select COUNT` returns stable count across 30 seconds AND `aws s3 ls s3://agent-platform-agent-logs/outbox/ --recursive` returns the same listing across two 60s-apart samples (round-3 adversarial #2 — confirms no in-flight drain is moving data).
4. Dump current max value per counter: `aws dynamodb scan --table-name agent-platform-counters --projection-expression "counter_name,current_value"`.
5. Seed personal-account `agent-platform-counters` table with `current_value + 1000` (safety margin against any late writes that snuck through, round-2 adversarial #5) for each counter.
6. Verify: a test `file_rec` via the new `log-rec` Lambda allocates the next id (work-account max + 1001).
7. Flip writers in the new account: unset `OPS_WRITER_FROZEN` on personal-account Lambdas.
8. Legacy `OpsWriter` in work account remains frozen permanently (the work account is being decommissioned).

**depends_on:** [T2.0, T2.1]
**Sequencing relative to T2.2:** T2.18 strictly precedes T2.2 (T2.2's depends_on extends to include T2.18 — see amendments table). Previous "peer of T2.2" language was inaccurate (round-3 architect #2).
**files_in_scope:** `scripts/ops_writer.py` (OPS_WRITER_FROZEN flag), `scripts/migrate_counters.py` (new), `docs/contracts/counters-migration.md` (procedure)
**effort:** S
**strategic:** false
**related_candidate_decisions:** [CD.25]

### T2.18b — Legacy `agent-logs` bucket write-freeze + cutover

**Intent:** Per round-2 architect #6. After T2.1 creates `agent-platform-agent-logs` and T0.15's config-driven bucket plumbing is in place, but before T2.2 imports, flip the active bucket to the new name and apply a read-only Bucket Policy to the legacy bucket. Procedure: (1) T0.15 ships the `S3_LOG_BUCKET` env var as the source-of-truth for bucket selection (already standard in handlers, just verify). (2) Update active deployments to set `S3_LOG_BUCKET=agent-platform-agent-logs`. (3) Wait for one drain cycle so any in-flight outbox writes against the legacy bucket complete. (4) Apply Bucket Policy on `agent-platform-agent-logs` denying `s3:PutObject` from all principals except a one-time-cleanup admin role. (5) Verify drain via `aws s3 ls s3://agent-platform-agent-logs/outbox/` returns expected residual files.

**depends_on:** [T2.1, T0.15]
**files_in_scope:** `terraform/legacy_bucket_freeze.tf` (new — work-account Terraform applies the Bucket Policy)
**effort:** XS
**strategic:** false
**related_candidate_decisions:** [CD.25]

### Amendments to existing tier_items

| Existing item | Amendment |
|---------------|-----------|
| **T0.7a** (log-rec) | `depends_on` insert: `T0.12a` between `T0.12` and `T0.13` → `[T0.6, T0.12, T0.12a, T0.13]` (round-2 architect #1) |
| **T0.7b** (log-decision) | Same: `[T0.6, T0.12, T0.12a, T0.13]` |
| **T0.7c** (query) | Same `depends_on` insertion AND new exit-criterion: every list_* verb's workgroup routing follows Part 3 cross-DB policy (ops + telemetry → `agent-platform-production`; product → `bblake-trading-system-production`; cross-DB → platform workgroup). T0.7c is authored against the two-workgroup world from the start (round-2 architect #3). Workgroup name comes from `src/common/aws_naming.py`. |
| **T0.13** (Iceberg DDL generator) | Consume class-level `@target_database` annotation with **semantic values** (`platform` or `project`) not physical names. Generator resolves to physical DB via `local.glue_platform_db` / `local.glue_project_db` (round-2 architect #8). Emit NOT NULL when `DqNotNull` present. |
| **T2.1** (full Terraform re-deploy) | Depends on T0.15, T0.16, T0.17, T2.0, T2.15, T2.16. |
| **T2.2** (ops + decisions import) | Depends_on extended to include `T2.18`. T2.18 is a strict precondition, not a peer (round-3 architect #2 correction). After import, one-off ETL backfills `project_id = "trading-system"`. `BackfillRequiredError` from `update-rec` is the transient guard inside this window only and is capped: T2.2 declares a hard wall-clock budget (default 24h) after which the implementing plan escalates rather than letting the window stay open indefinitely (round-3 adversarial #5). Exit criterion: `count(*) FROM agent_platform.ops_recommendations_current WHERE project_id IS NULL == 0`. |
| **T2.3** (company-aws-profile sweep) | Sweep scoped to SSO profile only; legacy resource-name sweep lives in T0.15 (production code) and T2.15 (runbooks + docs). NOTE: `tests/test_session_preflight.py:51,53,61` are venv-detection fixtures keyed on the `agent-platform` directory name (NOT SSO-profile fixtures, per round-3 correction); they belong in T0.15's semantic-refactor scope alongside the lines at 481/493/505, NOT in T2.3. Test fixtures may still have semantic assumptions about the work-account profile beyond literal string — implementing plan investigates SSO-related fixtures separately. |
| **T2.10** (OIDC + hosted-runner migration) | Trust policy `sub` claim uses `agent-platform`, not `agent-platform`. T2.10 runs concurrently with or after T2.15; if T2.10 ships first, its trust policy uses the new repo name (since T2.15's rename precedes); if after, no impact. |
| **T2.13** (public flip) | Depends_on gains T2.15. Public surface debuts under `agent-platform`. |
| **CD.10** (Agent Tooling Platform) | Gates list extends to include T0.12a. |
| **CD.16** (per-Lambda deploy gating) | Gates list extends to include T0.12a (round-2 architect #2). |

### Tier-item home for cross-project query principal binding (round-2 architect #11)

Cross-project query restriction (CD.28: "Cross-project queries via `query` Lambda restricted to `PlatformAdmin` principal") is implemented in:
- T0.7c (initial implementation of principal-binding lookup via `src/lambdas/_shared/principal_binding.py`)
- T1.2 (verb expansion — adds the `cross_project=True` admin-only verbs)

Both are listed in CD.28's gates; the principal-binding helper module is in T0.7c's files_in_scope.

---

## Part 9 — Open Questions for Step 10 Critique

1. **Final repo name.** Recommendation `agent-platform`.
2. **Final SSO profile name + personal account id.** **RESOLVED 2026-05-24** (PR for agent/migration-t03-t06-prep). SSO profile name: `agent_platform`. Personal account: `REDACTED-PERSONAL-ACCOUNT` (same as `personal-bedrock-profile`'s target). Profile decoupled from `agent-platform-*` resource prefix by design.
3. **`project_id` allowed value for the trading project.** Recommendation `"trading-system"`. Alternatives `"trading"`, `"ftse100-formulas"`.
4. **PLAN-platform-extraction-strategy.md fate.** Recommendation DEFERRED.
5. **Directory restructure** (`projects/trading-system/src/` vs flat with directory-name split). Deferred — AWS migration does not require this.
6. **CD numbering.** Provisional CD.25-CD.28; follow-on plan re-allocates.
7. **T2.17 Phase B rollback window.** Whether to author rollback DDL up front.
8. **GitHub Apps repo-id rebinding.** No GitHub Apps are currently installed on the repo; if any are added before T2.15, verify they survive the rename.

---

## Part 10 — Out-of-Scope Deferrals

- Methodology DNA leakage.
- Verification tier taxonomy for non-deterministic domains.
- Star-schema dimension `rec_project_dim`.
- GitHub Actions OIDC trust policy `project_id` claim (T2.10 — distinct from the `sub`-claim repo-name fix, which IS in scope for T2.15).
- Bedrock model access in personal account (T0.4).
- Phase Infra-Env multi-environment provisioning (env-by-account model documented in Part 3).

---

## Part 11 — Follow-on Implementation Plan Outline

After Step 10 convergence and CD ratification (long timeline, gated on T0.7b landing), a follow-on IMPLEMENTATION plan should:

1. Edit `docs/ROADMAP-PLATFORM.yaml`:
   - Append CD.25-CD.28 to `candidate_decisions[]`.
   - Append T0.12a, T0.15, T0.16, T0.17, T2.0, T2.15, T2.16, T2.17, T2.18, T2.18b to `tier_items[]`.
   - Apply amendments to T0.7a, T0.7b, T0.7c, T0.13, T2.1, T2.2, T2.3, T2.10, T2.13 entries per Part 8.
   - Extend CD.10 AND CD.16 gates lists to include T0.12a.
2. Prepend DEFERRED comment on `docs/plans/PLAN-platform-extraction-strategy.md`.
3. Pass RoadmapDocument Pydantic schema validation (T-1.5).
4. Run validate.py green.
5. Open PR.

V1, single IMPLEMENTATION plan.

---

## Known Gaps (explicitly deferred items — each is a known-but-not-resolved concern that the follow-on implementing plans are expected to handle)

1. **Cross-DB workgroup query policy detail** — Part 3 routing rules stated; per-verb implementation lives in T0.7c amendment. The cost-attribution choice ("cross-DB joins use platform workgroup by default") is a load-bearing policy; T0.7c implementing plan should surface this explicitly rather than treat as an aside (round-3 architect #6).
2. **Personal account id confirmation** — Open Question #2. Operator confirms before T2.1; if it equals `REDACTED-PERSONAL-ACCOUNT` (current `personal-bedrock-profile` target), the SSO cache clear procedure (`rm -rf ~/.aws/sso/cache`) must run before first device-code login under new profile name.
3. **Personal-account SCP verification before T2.10** (round-3 adversarial #1) — Decision 36 records the work account's SCP denies `sts:AssumeRoleWithWebIdentity` and `iam:CreateUser`. The personal account's SCP status is unknown. T0.16 (IAM audit) is the natural home to add a probe step: `aws iam create-open-id-connect-provider --dry-run` (or equivalent) against the personal account. If SCP denies OIDC, T2.10's hosted-runner migration is not viable and CD.21 must be revisited.
4. **Function URL identity changes on fresh deploy; agent SDK cutover** (round-3 architect #10) — Lambda Function URLs are created with new identifiers in the personal account. `scripts/agent_sdk/client.py` discovers URLs via Terraform outputs or SSM. T0.8 implementing plan must specify URL discovery mechanism and a cutover step where the SDK is repointed from work-account URLs to personal-account URLs. Recommendation: SSM Parameter Store at `/{owner}-platform/lambda-urls/{name}` consumed by the SDK at startup; cutover is a parameter update, not an SDK redeploy.
5. **Work-account decommissioning is unscheduled** (round-3 adversarial #9) — `prevent_destroy = true` lifecycle blocks on three work-account buckets persist indefinitely under the chosen "fresh deploy in new account" model. A follow-on tier item (T2.19 or equivalent) is needed with a concrete trigger (e.g. "30 days after personal-account live-cutover succeeds AND verified PASS") and exit criteria (`terraform destroy` succeeds on work-account state, buckets fully removed, state file archived). Add to ROADMAP-PLATFORM.yaml in the same follow-on implementing plan that lands the rest of this INTENT's tier_items.
6. **T2.18b sequencing relative to T2.2 outbox drain** (round-3 architect #5) — T2.18b's Bucket-Policy step must depend on T2.2's outbox-drain exit criterion. The implementing plan must thread this dependency explicitly rather than leaving "wait for one drain cycle" as prose.
7. **`project_registry.yaml` reload mechanism under Decision 67 freeze** (round-3 adversarial #6) — Onboarding a new project via YAML edit requires either a Lambda config-reload mechanism (not currently implemented) OR a Lambda redeploy (currently frozen per Decision 67). Until reload is implemented, "YAML edit + config reload" is only operational post-CD.17. Implementing plan for T0.12a notes this; alternative path is a scheduled file-watcher Lambda that emits SIGHUP equivalents.
8. **AST gate SQL parser robustness** — round-3 adversarial #8: `sqlglot` (now vendored per T0.15 amendment) handles standard SQL but f-string-constructed SQL evades static AST analysis. The gate is best-effort, not exhaustive. Acceptable tradeoff: the COALESCE invariant is also documented in code review checklists and in the writer-side architecture (the writer itself does not call COALESCE on `project_id`).
9. **Hyphen/underscore long-form explainer** — opportunistically authored in T2.15 if scope allows.
10. **T2.17 Phase B rollback DDL** — deferred to T2.17 implementing plan (Open Question #7).
11. **OIDC trust policy `project_id` claim** — T2.10's deferred future-work. Distinct from the `sub`-claim fix.
12. **AST gate vocabulary growth** — initial gate covers `COALESCE(project_id, ...)`; adding more anti-patterns is opportunistic.
13. **Webhook / GitHub App rebinding** — Open Question #8; verify before rename if any new apps land.
14. **CD numbering reconciliation** — CD.25-CD.28 provisional; follow-on implementing plan re-allocates against live YAML at write time.
15. **`ROADMAP-PLATFORM.yaml:52-53` prologue contradicts CD.17** (round-4 architect HIGH #1) — prologue says strategic items "require their own STRATEGIC plan tree before implementation"; CD.17:450 says they "CANNOT be filed as a single STRATEGIC plan with Work Areas." Real internal contradiction in the live roadmap. Follow-on implementing plan should rewrite the prologue line to cross-reference CD.17, OR a sibling CD reconciles. Outside this INTENT's scope but documented here so it doesn't get lost.
16. **Follow-on implementing plan size vs complexity heuristic** (round-4 adversarial #3) — the plan that edits ROADMAP-PLATFORM.yaml will touch >5 files and >8 steps (CD additions + tier_item additions + amendments to T0.7a/b/c/T0.13/T2.1/T2.2/T2.3/T2.10/T2.13/CD.10/CD.16). Under freeze, this is fine — author as single larger IMPLEMENTATION plan OR split into ~3-4 atomic plans (CD additions, tier_item additions, existing-item amendments). Implementing-plan authoring session decides at /plan time.
17. **T2.18 OPS_WRITER_FROZEN code-vs-IAM-deny disambiguation** (round-4 adversarial #4) — step (1)'s code change is dead weight in the work account because Decision 67's Lambda-deploy freeze prevents redeploying `ops_writer.py` there. The IAM-deny rule is the only active quiescence mechanism in the work account during the migration window. The code change is included for post-CD.17 use on the personal-account Lambdas (which are deployed fresh in T2.1 with the flag-bearing code from the start, sidestepping the redeploy constraint). Step (7) "unset OPS_WRITER_FROZEN on personal-account Lambdas" is therefore an env-var update on a Lambda that already has the flag code, not a redeploy. The implementing plan must verify this sequencing explicitly.
18. **CD.21 reference verification** (round-4 adversarial #5) — INTENT Part 1A references "CD.21" for the self-hosted runner retirement. Verify CD.21 exists in ROADMAP-PLATFORM.yaml at implementing-plan write time; if it does not, replace with the correct CD id covering self-hosted-runner retirement.
19. **T2.15 `terraform/oidc.tf` dependency on T2.10** (round-4 adversarial #6) — T2.15's files_in_scope references `terraform/oidc.tf` which is created by T2.10. T2.15's depends_on must include T2.10 OR T0.16 must author the initial oidc.tf skeleton. Implementing plan resolves.
20. **T0.15 file-scope alignment with COALESCE policy** (round-4 architect #5) — Part 2 forbids COALESCE in `scripts/ops_*.py`, `src/lambdas/`, `scripts/agent_sdk/`; T0.15 files_in_scope cites `src/data/handlers/*.py` for Lambda handler defaults but doesn't explicitly enumerate `scripts/agent_sdk/`. Implementing plan reconciles — the AST gate must walk all three policy-target directories regardless of files_in_scope.
21. **`sqlglot` dependency scoping** (round-4 architect #6) — `sqlglot` is vendored only as a validate-time dependency, NOT bundled into Lambda zips. Add to `requirements-dev.txt` rather than `requirements.txt`. Implementing plan respects this.

---

## References

- `docs/ROADMAP-PLATFORM.yaml`, `docs/ROADMAP-PRODUCT.md`, `docs/PROJECT_CONTEXT.md`, `docs/DECISIONS.md`
- `docs/plans/PLAN-platform-extraction-strategy.md` (deferred under CD.26)
- Terraform files cited in Part 1A
- Python module-level constants cited in Part 1B
- CLAUDE.md — Single Portal Invariant, warehouse-as-source-of-truth, Decision 67 freeze
