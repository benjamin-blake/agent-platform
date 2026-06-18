# agent-platform

This file is a curated projection of `CLAUDE.md` and `docs/ROADMAP-PLATFORM.yaml` - the canonical sources of truth for this repository. Where this file conflicts with those sources, the canonical sources win. For agent consumption, load those files directly.

## North Star

- **NS.1 - Storage is durable; compute is interchangeable.** S3 + open table format at every scale from GB to PB (Iceberg for market-data; DuckLake for ops/telemetry per Decision 78). Engines are swappable per workload; data is not migrated to swap engines.
- **NS.2 - Account ownership reflects IP ownership.** Personal AWS account, not shared work account. AUP, IP, and business-continuity reasons; cost is a tiebreaker.
- **NS.3 - Compute lives where it economically belongs.** Hybrid by design. Cloud for orchestration and state; local rig for CPU-bound batch where home hardware otherwise idles.
- **NS.4 - The repo is for agents.** Documentation, configuration, and tooling are optimised for agent consumption. Narrative prose is a side effect, not an output.
- **NS.5 - Self-describing typed tools over HTTPS, schema-as-code.** Agent surface is verbs (log, update, query, describe) exposed via Lambda Function URLs with AWS_IAM auth. Schema is Pydantic; YAML is generated where needed.

## What This Repo Is

This is a platform repo, not a product repo. It provides the control plane, automation infrastructure, and governance framework on which products are built. The product roadmap lives in a sibling file: `docs/ROADMAP-PRODUCT.yaml`.

## Hosted Products

The platform hosts one live product: an automated trading system (product #1). The operational data plane is a single lakehouse; products are distinguished by a `project_id` column, not by separate stores. This is the platform multi-tenancy model.

Two prospective tenants are named in the roadmap - reaper-tools and dbt-daywork - but neither is active or under development. Cross-employer code is kept in an external repository to satisfy IP-separation constraints.

## Platform Subsystems

| Subsystem | Status | Notes |
|-----------|--------|-------|
| Recommendation + Decision Governance | [live] | Append-only ops lakehouse; single portal invariant enforced by validate.py |
| CI / OIDC | [live] | GitHub-hosted runners; OIDC to personal AWS account; validate.py is the single gate |
| Instruction Architecture (5-layer) | [live] | CLAUDE.md -> PROJECT_CONTEXT.md -> commands -> skills -> executor prompts |
| Environment Taxonomy | [live] | Two-axis: platform env (sandbox/SIT/PROD) x product phases; defined by Decision 77 |
| Autonomous Executor | [partial] | Step Functions + Lambda recommendation-queue consumer; executor freeze active pending CD.17 / T4.2 reversal |
| Scheduled Agents | [partial] | Lambda dispatcher disabled May 2026; migrating to Claude Code scheduled-agent model |
| Lambda Tooling Platform | [planned - T0.7+] | Per-Lambda manifests, Function URL auth, Step Functions state machine per rec |
| DuckLake Lakehouse | [planned - T2.16+] | DuckDB + DuckLake catalog on Neon replacing the Athena-only ops query path |
| Verification / Validation Kernel | [planned - T3.1+] | Cross-session test harness with VP results tracked in ops telemetry |

## Documentation Model

| Content Type | Current Form | End-state |
|--------------|-------------|-----------|
| Agent-instruction files | Markdown (CLAUDE.md, AGENTS.md) | Stays markdown per CD.20 / CD.23 - canonical agent artefacts |
| Operational decisions, recommendations, session logs | Append-only lakehouse (primary); markdown / JSONL cache (derivative) | Governed lakehouse per T5.4 / T1.5 - local files become read-only snapshots |
| Plans | Markdown (docs/plans/PLAN-*.md) | Schema-validated YAML (docs/plans/PLAN-*.yaml) per T1.11 |
| Briefing and INTENT-* docs | Markdown (docs/INTENT-*.md, docs/contracts/) | Non-authoritative; retiring per T5.5; content migrates to canonical YAML or is deleted |
| Human portal files | Markdown (README.md, AGENTS.md, SECURITY.md) | Stays markdown per CD.20 / CD.23 - portal files declare projection status |

## Repo Layout

| Path | Purpose |
|------|---------|
| `CLAUDE.md` / `AGENTS.md` | Universal agent rules and role definition; ambient-loaded every session |
| `SECURITY.md` | Vulnerability reporting policy |
| `src/` | Lambda handlers, shared Python modules, trading system code |
| `scripts/` | Operational scripts - preflight, ops portal, validate, build-lambda |
| `config/` | Agent-consumed configuration: data quality, executor prompts, lambda manifests |
| `terraform/` | Infrastructure-as-code for personal AWS account |
| `docs/` | ROADMAP-PLATFORM.yaml, ROADMAP-PRODUCT.yaml, plans, decisions, session log |
| `bin/` | Platform helper scripts including venv-python wrapper |
| `tests/` | Pytest test suite |
| `.claude/` | Harness artefacts: commands, skills, hooks, settings |
| `.github/` | CI workflows and OIDC configuration |

## Agent Workflow Entry Points

- `/plan` - defined in `.claude/commands/plan.md`; clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.md` on the harness-assigned session branch
- `/implement` - defined in `.claude/commands/implement.md`; reads a completed plan file and executes all steps through verification, code review, and PR merge

## Canonical Sources

- [CLAUDE.md](CLAUDE.md) - universal agent rules and operational constraints
- [AGENTS.md](AGENTS.md) - role, environment, code style, safety, and branching rules
- [docs/ROADMAP-PLATFORM.yaml](docs/ROADMAP-PLATFORM.yaml) - tier items, candidate decisions, North Star, cost projection
- [docs/ROADMAP-PRODUCT.yaml](docs/ROADMAP-PRODUCT.yaml) - product phases and milestones
- [SECURITY.md](SECURITY.md) - vulnerability reporting
- [EVALUATION-PROMPTS.yaml](EVALUATION-PROMPTS.yaml) - evaluator guided-tour index: 12 architecture/governance questions with answer-loci into canonical sources
