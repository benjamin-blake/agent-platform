# Theseus - Agentic Software Engineering Platform

Canonical Layer 2 project knowledge base for Claude Code. This file is loaded on demand by workflows; keep rules in `CLAUDE.md` / `AGENTS.md`, workflow method in `.claude/commands/` and `.claude/skills/`, and machine semantics in `docs/contracts/*.yaml`.

Source stamp: ROADMAP-PLATFORM.yaml @ working tree; roadmap_tier_id_set sha256: 5ce59be4136f4c884d0aa427c09f29ed728e5192f41da0f2128fb02a60dc7307

## Operating contract

- Repository visibility: public. Never commit credentials, API keys, AWS account IDs, IAM ExternalIds, account-specific ARNs, internal hostnames, trading alpha, strategy performance, or confidential market research. Safe content is platform engineering, infrastructure patterns, CI/CD design, tooling, and general LLM-agent architecture.
- Runtime surface: Ubuntu 24.04 / bash / Python 3.12+. Invoke Python with `bin/venv-python`, never `python` or `python3`. Do not rely on `source .venv/bin/activate` between shell calls.
- Branching: never edit or commit on `main`. Routine handoff is commit -> PR -> CI -> merge.
- Terraform and Lambda deploys: agents do not routinely run `terraform apply` or local Lambda deploy commands. Use `docs/contracts/deploy-paths.yaml` and `docs/contracts/build-lambda.yaml` to choose the governed path. Local apply/deploy is break-glass only after explicit human direction.

## Platform thesis

This repository is primarily an agentic software-engineering platform. Its purpose is to let LLM agents plan, build, verify, deploy, monitor, and improve software safely and reliably with minimal human oversight. Trading is an initial hosted product and proving ground, not the identity or commercial boundary of the platform.

The platform is the governed harness around model intelligence. Models, compute providers, tools, and hosted products are replaceable. The durable product is the control plane that gives agents bounded authority, typed capabilities, reliable state, independent verification, deployment controls, operational memory, and evidence-backed feedback loops.

The platform end-state is a public, agent-first automation platform with:

1. durable operational data as the source of truth;
2. swappable models and compute selected by workload;
3. typed tool and agent surfaces instead of ad hoc scripts;
4. specialised planning, critique, implementation, review, and analysis personas;
5. governed CI/CD, deployment, and progressive authority controls;
6. warehouse-backed recommendations, decisions, queue state, execution evidence, and telemetry;
7. causal verification connecting an agent action to its persisted and observed outcome;
8. a closed improvement loop that can complete one bounded iteration without a human in the critical path;
9. portability across repositories, products, infrastructure, and regulated domains.

## Recursive self-improvement model

The platform is a governed, recursively self-improving software-engineering system. Verification recursively improves, but verification is not the only improvement target.

The complete loop is:

```text
observe development and runtime behavior
  -> identify defects, friction, cost, latency, risk, and opportunity
  -> create a bounded, evidence-linked recommendation
  -> prioritise and admit work under explicit policy
  -> plan, critique, implement, and review the change
  -> obtain an independent CI/CD verdict
  -> deploy through the governed channel
  -> measure the resulting behavior
  -> retain evidence and improve the next iteration
```

Telemetry provides learning signals about the whole engineering system: agent behavior, planning quality, review churn, tool failures, context quality, model cost and latency, CI performance, deployment outcomes, monitoring gaps, incidents, and hosted-product behavior. Analysis agents convert those signals into bounded recommendations that may improve:

- tests, invariants, monitors, and verification gates;
- prompts, personas, context selection, and model routing;
- planning, critique, decomposition, prioritisation, and review;
- tool contracts, orchestration, workspace handling, and recovery;
- CI/CD, deployment controls, observability, and incident diagnosis;
- data architecture, platform implementation, and hosted products.

At maturity, outcome telemetry and product metrics also drive changes to the system itself. The platform can therefore improve both the process that produces software and the software produced by that process.

Recursive improvement remains bounded. A signal is not proof, a recommendation is not authority, and a metric movement is not automatically a beneficial outcome. Observation, analysis, recommendation, implementation, verification, admission, and post-deployment evaluation are distinct stages. Agents may propose and implement changes, but changes gain authority only through explicit policy and independent evidence. Verification is the safety envelope and admission mechanism for recursive self-improvement, not its scope limit.

## Commercial and product boundary

The primary category is agentic software-engineering infrastructure, adjacent to AI assurance, autonomous operations, and regulated AI control planes.

The core value proposition is not an agent that writes code. It is the harness that makes code-writing and operations agents governable, inspectable, testable, portable, and safe enough for production-adjacent work. It provides traceability from work selection and authority through agent action, independent verification, deployment, observed outcome, and the next improvement.

Hosted products consume but do not define the platform. Trading exercises high-consequence data, operations, and verification. Other products reuse the substrate without inheriting trading logic. Product-specific IP, data, and risk controls stay behind their product boundary.

## Roadmap sources

- Platform roadmap: `docs/ROADMAP-PLATFORM.yaml` for platform sequencing, governance, data, telemetry, and executor work.
- Hosted-product roadmap: `docs/ROADMAP-PRODUCT.yaml` for the initial trading product. It is a consumer and proving ground.
- Decision rationale: `docs/DECISIONS.md` plus `docs/DECISIONS_ARCHIVE.md`. Pending candidate decisions in the roadmap are binding until ratified or superseded.
- Contracts: `docs/contracts/*.yaml` and selected `.md` contracts are the preferred source for machine semantics. Do not duplicate contract truth in prose.

Use PLATFORM for the harness and PRODUCT for hosted-domain capabilities; use both only when product intent requires platform machinery.

## Platform roadmap end-state map

### Foundation already shipped

The platform is in convergence and hardening rather than bootstrap. Its foundation includes the agent branch workflow, public-repo boundary, GitHub-hosted CI, secret guards, two-tier validation, the Single Portal Invariant, DuckLake reader/writer functions, schema-as-code, CI-RCA, governed deployment, and infrastructure guard classification. T2 is the active center of gravity because durable state and guard hardening block telemetry and executor work.

### Critical path to the autonomous loop

```text
T2.18 DuckLake maintenance
  -> T2.19/T2.26 ops-table migration tail
  -> T2.36 telemetry rebuild on DuckLake
  -> T3.2 telemetry causal-chain verifier
  -> T3.3 telemetry cloud analysis
  -> T3.4 control-plane loop closure
  -> T4.1 Step Functions executor substrate
  -> T4.2 Lambda Durable Function agent personas
```

Parallel governance path:

```text
T1.5 ops_decisions graduation
  -> T1.6 move live-reader DQ from merge gate to monitor
  -> T4.2 executor persona readiness
```

Queue-feed path:

```text
T2.26 migrated ops queue substrate
  -> T4.3 priority-queue producer repoint to DuckLake
  -> T4.12 scheduled-agent re-enable/repoint
```

Current constraints are the temporary strategic/executor freeze, telemetry blindness before T2.36/T3.2/T3.3, the queue producer gap before T4.3, and missing executor evidence. Work remains IMPLEMENTATION-only until the documented reversal conditions hold.

## Operational data architecture

### Source of truth

Warehouse state is authoritative. Local JSONL files under `logs/` are read caches, not write sources. Recommendations, decisions, priority queue, and execution plans use DuckLake-on-Neon. Session log remains on its legacy path pending disposition; telemetry re-lands as the T2.36 four-table DuckLake model. Mutable operational entities use SCD2; event journals are append-only.

### Portal discipline

Agent-facing operations are only `file_rec`, `update_rec`, and `sync`. All recommendation and decision writes go through `scripts.ops_data_portal`. Never append to `logs/.recommendations-log.jsonl` or other read caches, pending outboxes, or S3 staging as a substitute. IDs are writer-allocated. Migrated tables have no offline outbox; failed writes fail loudly.

### Data modeling default

For any table, state the grain first. Use SCD2 for mutable entities and append_only for events. Use boundary-minted ULIDs, business-key merges, explicit partitioning, and contract-backed field semantics. Never default to CRUD.

## Telemetry, learning, and verification

The canonical telemetry model is:

- `telemetry_sessions`
- `telemetry_observations`
- `telemetry_transcripts`
- `telemetry_agents`

T2.36 creates storage and write/read paths. T3.2 proves PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT. T3.3 analyzes anomalies, friction, cost, and failure trends. T3.4 turns verified analysis into control-plane work. T3.20 routes agent-turn/session capture into the same model and coordinates retirement or rewiring of legacy session-log surfaces.

Telemetry is evidence, not merely logging. Every meaningful stage should emit enough identity and lineage to connect recommendation, plan, agent invocation, code change, CI verdict, deployment, observation, and measured outcome. Analysis must distinguish correlation from causal evidence and preserve uncertainty rather than converting every anomaly into an automatic change.

Verification is recursively improvable. Escaped defects, weak tests, missing guards, and monitoring gaps can generate recommendations for stronger verifiers. A proposed verifier must itself demonstrate useful discrimination before becoming authoritative, including differential or mutation evidence where appropriate. `scripts.validate` remains the single source of truth for CI checks: PRs run `--pre`; full validation runs before handoff and on main; new CI checks enter `scripts.validate` first.

## Agent and executor architecture

### Interactive workflow today

`/orient -> /plan -> /implement`: orient ranks work read-only; plan creates a schema-validated implementation plan with decision and critique gates; implement changes, verifies, reviews, validates, and hands off through PR/CI. `/develop-executor` diagnoses executor failures and files RCA recommendations.

### Local executor status

The older local executor is frozen pending Decision 67 reversal. `config/agent/executor/capabilities.yaml` prevents unrestricted self-modification: sensitive runtime, verification, infrastructure, workflow, governance, and deployment targets remain protected until policy delegates them.

### Executor end-state

```text
DuckLake queue
  -> pick_rec admission guard
  -> Step Functions orchestration
  -> prepare_workspace
  -> plan_agent
  -> plan_critic + decision_scout
  -> critique_gate
  -> implement_agent
  -> code_reviewer
  -> file_pr
  -> GitHub Actions verdict callback
  -> merge
  -> deploy_dispatch
  -> emit_telemetry
  -> analyze outcome
  -> autonomy gate ratchet
```

T4.1 owns Step Functions and deterministic glue Lambdas. T4.2 owns Lambda Durable Function personas and LiteLLM transport. T4.9a owns the MVP GitHub Actions callback handshake. T4.10a owns persona contracts. T4.13/T4.14 add prompt-injection threat modeling and offline prompt/model regression tests.

Authority increases only when evidence supports it. The end-state minimises routine oversight while preserving human policy control, auditability, escape hatches, and explicit boundaries for high-consequence actions.

## Scheduled analysis and CI-RCA

Scheduled agents are currently disabled. T4.3 first repoints rec-curator/priority-queue writes to DuckLake so generated work is visible to the executor. T4.12 then re-enables or repoints doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, and rec-curator surfaces.

CI-RCA is one failure-to-work bridge. Red main workflows generate evidence, deduplicate, analyze the failure, and file recommendations through the ops portal. More generally, telemetry analysis should turn recurring friction and outcome evidence into prioritised work rather than only reacting to CI failures. `/orient` surfaces CI-RCA items; `/plan` treats unresolved CI-RCA as a hard planning constraint.

## Infrastructure and deployment

The platform currently uses AWS `eu-west-2`, Python 3.12 Lambdas, GitHub-hosted CI with OIDC, DuckLake-on-Neon, and LiteLLM transport. These are replaceable implementation choices, not product identity. Routine production changes use governed GitHub workflows; admin access and local deployment are human-gated, break-glass only.

## File routing and operational quick reference

Use `docs/contracts/file-router.yaml` as the discovery and ownership index. Do not create a standing prose companion when a contract or existing machine-readable artifact can carry the semantics.

Recommendations are operational work items, not local JSONL edits. Required concepts include title, source, effort, priority, status, automatable, risk, file, context, acceptance, optional verification, verification tier, dependencies, tags, and resolution/execution metadata when closing. Canonical status values are `open`, `closed`, `failed`, `declined`, and `superseded`. Acceptance proves structural change; verification proves behavior and may be warning-only depending on tier.
