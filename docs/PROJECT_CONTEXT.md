# Machine Learning Trading System - Project Context

Canonical Layer 2 project knowledge base for Claude Code. This file is loaded on demand by workflows; keep rules in `CLAUDE.md` / `AGENTS.md`, workflow method in `.claude/commands/` and `.claude/skills/`, and machine semantics in `docs/contracts/*.yaml`.

Source stamp: ROADMAP-PLATFORM.yaml @ working tree; roadmap_tier_id_set sha256: 5ce59be4136f4c884d0aa427c09f29ed728e5192f41da0f2128fb02a60dc7307

## Operating contract

- Repository visibility: public. Never commit credentials, API keys, AWS account IDs, IAM ExternalIds, account-specific ARNs, internal hostnames, trading alpha, strategy performance, or confidential market research. Safe content is platform engineering, infra patterns, CI/CD design, tooling, and general LLM-agent architecture.
- Runtime surface: Ubuntu 24.04 / bash / Python 3.12+. Invoke Python with `bin/venv-python`, never `python` or `python3`. Do not rely on `source .venv/bin/activate` between shell calls.
- Code and docs style: type hints for Python, async for I/O, ruff formatting, no emojis in code/scripts/docs, plain ASCII hyphens, no `eval()` or `exec()`, and no exceptions during module import.
- Branching: never edit or commit on `main`. Use the harness-assigned `claude/...` session branch. Routine handoff is commit -> PR -> CI -> merge, not direct pushes to `main`.
- Terraform and Lambda deploys: agents do not routinely run `terraform apply` or local Lambda deploy commands. Use `docs/contracts/deploy-paths.yaml` and `docs/contracts/build-lambda.yaml` to choose the governed path. Local apply/deploy is break-glass only after explicit human direction.
- External integrations: when a plan step relies on an external API/tool, cite the source defining its input semantics, explain why the delivery mechanism is correct, and describe what breaks if the assumed semantics are wrong.

## North star

Build a self-improving automated trading system. Product work creates the trading stack; platform work creates the governed agent/warehouse/CI substrate that lets the repository improve itself without losing safety, provenance, or human auditability.

The platform end-state is a public, agent-first automation platform with:

1. durable data as the source of truth;
2. compute that is swappable by workload;
3. typed HTTPS tool surfaces instead of ad hoc scripts;
4. governed CI/CD and deployment channels;
5. warehouse-backed recommendations, decisions, queue state, and telemetry;
6. a future autonomous improvement loop that can complete one bounded iteration without a human in the critical path.

## Roadmap sources

- Product capability roadmap: `docs/ROADMAP-PRODUCT.yaml` for trading-system phases, market features, alpha/portfolio/execution/operations layers, and environment-as-config bundles.
- Platform roadmap: `docs/ROADMAP-PLATFORM.yaml` for tier_items, platform sequencing, infra governance, candidate decisions, DuckLake/Lambda topology, executor substrate, and bootstrap work.
- Decision rationale: `docs/DECISIONS.md` plus `docs/DECISIONS_ARCHIVE.md`. Pending candidate decisions in the roadmap are binding until ratified or superseded.
- Contracts: `docs/contracts/*.yaml` and selected `.md` contracts are the preferred source for machine semantics. Do not duplicate contract truth in prose.

Roadmap disambiguation: use PRODUCT for trading capabilities, PLATFORM for agent/infrastructure/control-plane capabilities, and both only when a task spans product intent plus platform machinery.

## Platform roadmap end-state map

### Foundation already shipped

The repo has shipped enough foundation that the platform is in convergence and hardening rather than bootstrap: CC-web branch workflow, public-repo boundary, GitHub-hosted CI with OIDC, pre-commit secret guards, two-tier validation, Single Portal Invariant, DuckLake reader/writer functions, schema-as-code, field semantics, CI-RCA, candidate-decision ratification lane, governed code-deploy channels, and Terraform guard classification.

T0 is effectively complete. T-1 has only a small deferred packaging tail. T2 is the active center of gravity because storage, deploy, IAM, and guard hardening are the blocking substrate for telemetry and executor work.

### Critical path to the autonomous loop

Current critical path from the roadmap and audits:

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

### Current blockers

- Strategic/executor freeze: STRATEGIC plans are suspended. Work continues as IMPLEMENTATION plans, but executor unfreeze requires T4.2 stability, T3.2 PASS evidence, and T3.3 grace.
- T1.5/CD.18: ops_decisions graduation cannot start until its gating candidate decision is ratified.
- Telemetry gap: the improvement loop is still effectively blind until telemetry storage, causal verification, and cloud analysis are rebuilt.
- Queue feed gap: rec-curator/priority-queue production must be repointed to DuckLake before autonomous pick-rec has a reliable source.
- DQ gate shape: live DuckLake-reader checks must move out of the blocking merge gate into scheduled monitoring without weakening write-path structural enforcement.
- Executor substrate evidence: the incumbent Step Functions + Lambda Durable Functions design leads, but workspace/resume and persona contract evidence must stay explicit.

## Operational data architecture

### Source of truth

Warehouse state is authoritative. Local JSONL files under `logs/` are read caches, not write sources.

Current ops substrate:

- `ops_recommendations`: DuckLake-on-Neon, SCD2, written through `ducklake_writer` via `scripts.ops_data_portal`, read through `ducklake_reader`.
- `ops_decisions`: DuckLake-on-Neon, sourced from `DECISIONS.md` / archive ETL and portal decision paths; decision numbering remains `DECISIONS.md` authority.
- `ops_priority_queue`: DuckLake-on-Neon, dormant until executor/scheduled-agent producer work resumes; current-state read uses its named verb semantics.
- `ops_execution_plans`: DuckLake-on-Neon, empty or dormant until executor resumes.
- `ops_session_log`: still Iceberg/Athena pending CD.40/T3.20 disposition.
- telemetry tables: dead Athena/Iceberg draft retired in favor of T2.36 four-table DuckLake rebuild.

### Portal discipline

Agent-facing operations are only:

- `file_rec`
- `update_rec`
- `sync`

All recommendation and decision writes go through `scripts.ops_data_portal`. Never append to `logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`, pending outboxes, or S3 staging as a substitute. Recommendation IDs are allocated by the writer atomically. There is no offline outbox for migrated tables; failed writes fail loudly and must be retried after restoring the `agent_platform` credential chain.

### Data modeling default

For any new table or warehouse write path, state the grain first: one row per what. Then choose write mode:

- SCD2 for mutable operational entities with current/history projections.
- append_only for event/telemetry journals.

Use boundary-minted ULIDs, business-key merges for SCD2, explicit partitioning, and contract-backed field semantics. Never design a table as CRUD by default.

## Telemetry and verification end-state

Telemetry end-state is the canonical four-table DuckLake model:

- `telemetry_sessions`
- `telemetry_observations`
- `telemetry_transcripts`
- `telemetry_agents`

T2.36 creates the storage and write/read paths. T3.2 proves PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT. T3.3 analyzes telemetry for anomalies and cost/failure trends. T3.20 routes agent-turn/session capture into the same model and coordinates retirement or rewiring of legacy session-log surfaces.

Verification doctrine: `scripts.validate` is the single source of truth for CI checks. PRs run the fast `--pre` tier; full validation runs before handoff and on main. New CI checks must be added to `scripts.validate` first.

## Agent and executor architecture

### Interactive workflow today

```text
/orient -> /plan -> /implement
```

- `/orient` is read-only: preflight, roadmap state, CI-RCA triage, ranked work, and plan prompts.
- `/plan` produces `docs/plans/PLAN-{slug}.yaml`, with affected-file analysis, verification-tier selection, decision-scout gate, and critique.
- `/implement` executes an approved plan, runs verification and code review, then validates, commits, opens a PR, and follows the event-driven CI/merge flow.
- `/develop-executor` diagnoses executor failures and files RCA recommendations; it does not patch inline.

### Local executor status

`scripts/execute_recommendation.py` and `config/agent/executor/prompts/*.prompt.md` preserve the older local executor loop: select rec, branch, plan, critique/refine, implement steps, validate, review, PR, CI, merge. This surface is frozen pending Decision 67 reversal and is not the routine development path.

Executor self-modification boundary is enforced by `config/agent/executor/capabilities.yaml`: executor internals, prompts, LLM/tool runtime, tests, Terraform, workflows, scheduled-agent surfaces, decision/plan docs, and Lambda build/deploy scripts are non-automatable targets.

### Executor end-state

T4 decomposes the interactive workflow into cloud states:

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
  -> autonomy gate ratchet
```

T4.1 owns Step Functions and deterministic glue Lambdas. T4.2 owns Lambda Durable Function personas and LiteLLM transport. T4.9a owns the MVP GitHub Actions callback handshake. T4.10a owns persona contracts. T4.13/T4.14 add prompt-injection threat modeling and offline prompt/model regression tests.

## Scheduled agents and CI-RCA

Scheduled agents are currently disabled. The future split is:

- T4.3 first repoints rec-curator/priority-queue producer writes to DuckLake so generated work is visible to the executor.
- T4.12 then re-enables/repoints doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, and rec-curator surfaces.

CI-RCA is the failure-to-work-item bridge. Red main workflows generate evidence, deduplicate, invoke the CI-RCA agent, and file recommendations through the ops portal. `/orient` surfaces CI-RCA items; `/plan` treats unresolved CI-RCA as a hard planning constraint.

## AWS and deployment facts

- Region: `eu-west-2`.
- Account: personal platform account; account ID and account-specific values remain gitignored or in AWS.
- Agent profile: `agent_platform`. Admin profile is human-gated only for rare break-glass provisioning.
- Credential model: static-key assume-role chain. Verify with `aws sts get-caller-identity --profile agent_platform`; refresh the local static key only if rotated.
- Lambda runtime: Python 3.12.
- CI runner: GitHub-hosted `ubuntu-latest` with OIDC roles.
- LLM substrate for future executor: LiteLLM with DeepSeek-direct Tier 1 and Anthropic-direct Tier 2. Bedrock is retired for this dev surface unless a contract explicitly says otherwise.
- DuckLake/prod Lambda routine deploys go through governed GitHub workflows named by `docs/contracts/build-lambda.yaml`; local `build_lambda --deploy` variants are break-glass only.

## File routing and placement

Use `docs/contracts/file-router.yaml` as the discovery and ownership index. Its validators enforce root docs allowlists and prose placement. Do not create a new standing prose companion document when a contract or existing machine-readable artifact can carry the semantics.

## Recommendation schema quick reference

Recommendations are operational work items, not local JSONL edits. Required conceptual fields include title, source, effort, priority, status, automatable, risk, file, context, acceptance, optional verification, verification tier, dependencies, tags, and resolution/execution metadata when closing.

Canonical status values: `open`, `closed`, `failed`, `declined`, `superseded`. Never use `done`, `complete`, or `implemented`.

Acceptance proves the structural change landed. Verification proves behavior end-to-end and may be warning-only depending on tier. Prefer command scripts or focused pytest targets over opaque one-liners.

## Known gotchas

- Do not write read caches or outboxes as if they were source of truth.
- Do not bypass missing AWS credentials by silently falling back to stale data. Loudly surface degraded warehouse access.
- Do not run routine Terraform apply or local Lambda deploys. Check deploy-path contracts first.
- Do not raise SLOC/prose budgets casually. Decompose or ratchet down unless a Decision-authorized raise exists.
- Terraform optional artifacts need `try(filemd5(...), ...)` or `try(file(...), ...)` wrappers.
- Athena/Iceberg limitations still matter for remaining legacy paths: use engine v3 workgroups for Iceberg DML and avoid assuming `ALTER TABLE ADD COLUMNS IF NOT EXISTS` exists.
- Test isolation: never spawn the full pytest suite from code imported by tests; mock both `subprocess.Popen` and `subprocess.run` for subprocess-spawning functions.
- Path migration and deletion require reference sweeps across prompts, workflows, scripts, docs, tests, and manifests.
- Windows subprocess code must pass `encoding="utf-8", errors="replace"` with `text=True` and use `sys.executable`.
