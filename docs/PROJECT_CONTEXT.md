# Machine Learning Trading System - Project Context

> **Canonical project knowledge base for Claude Code.** Update this file only.

You are a Lead Software Developer writing production-quality Python. You are operating on a Linux container (Ubuntu 24.04) with bash; use `bin/venv-python` for all Python invocations (Python 3.12+).
See docs/contracts/instruction-architecture.yaml for the full information architecture.

## Rules

- **PUBLIC repository (Decisions 73, 83, 101):** This repo is public. Never commit AWS account IDs, IAM ExternalIds, credentials/keys, trading alpha/performance data, or internal hostnames. Confidential data lives only in the personal AWS account (Secrets Manager, gitignored tfvars) and gitignored local files. Market platform engineering, not trading alpha.
- **AWS Credentials:** A lack of AWS Credentials IS NOT A VALID REASON to bypass a task. The static-key assume-role chain auto-refreshes; verify it with `aws sts get-caller-identity --profile agent_platform` (refresh `~/.aws/credentials` if the `agent_static` key was rotated).
- No emojis in code, scripts, or documentation
- Python 3.12+, type hints required, async for I/O
- **Shell:** Python scripts only for automation. Use subprocess for git/terraform commands. Bash syntax only -- never emit PowerShell commands.
- Formula evaluation: `sympy.sympify()` + `sympy.lambdify()` only -- never `eval()`/`exec()`
- No Docker in this environment -- Lambdas use zip packaging via S3
- **Branching:** On Claude Code on the web the harness auto-creates a per-session branch (e.g. `claude/...`); agents work on that branch. Do NOT create `agent/{slug}` branches. Never commit directly to `main`. Plans are merged to `main` via a GitHub MCP PR and handed off to `/implement` by explicit path.
- **Context budget:** Files loaded at session start must stay concise. `ROADMAP.md` keeps only current and adjacent phases (completed phases archived to `ROADMAP_ARCHIVE.md`). `SESSION_LOG.md` keeps only the last 5 entries. `DECISIONS.md` keeps only open decisions (resolved decisions archived to `DECISIONS_ARCHIVE.md`). `strategic_review` enforces this during periodic checks.
- **Refactoring Protocol:** When performing complex, non-contiguous edits, verify structural integrity immediately after. Never proceed to logic verification (e.g., merge or test) until the structural integrity of the edit is confirmed.
- **Agent-First:** This repository is designed for agent consumption. Artefacts at all
  layers are optimised for agent loading efficiency. Full principle and anti-patterns:
  `CLAUDE.md` section "Agent-First Repository".

## External Integration Check

When a plan step calls an external tool (Copilot CLI, gh CLI, AWS SDK, Lambda invocation, subprocess call):
1. Cite the doc page defining the input semantics
2. State WHY this delivery mechanism is correct for the use case
3. State what would go wrong if the semantics differ from what the code assumes

If a boundary contract exists in `docs/contracts/`, reference it. Both `/plan` and `/develop-executor` workflows read this file, so this rule applies to all agent work.

## Operational Data Governance

### Recommendation & Decision Logging
- **Single Portal Invariant:** All creation, updates, or status changes to recommendations and decisions MUST go through `scripts/ops_data_portal.py`. Never use `write_to_file` to modify `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly.
- **Storage backend (Decision 84 consolidation, 2026-06-11):** `ops_recommendations`, `ops_decisions`, `ops_priority_queue` source of truth = **DuckLake-on-Neon, SOLE backend** (the `OPS_STORAGE_BACKEND` rollback flag is RETIRED). Reads transit the closed `ducklake_reader` boundary via named verbs; writes transit `ducklake_writer` (`file_ops` allocates rec-NNN in-transaction; decisions follow DECISIONS.md numbering and rebuild via `ops_data_portal --backfill-decisions-md`). `ops_session_log` / `ops_execution_plans` remain on Athena/Iceberg pending their T2.26 disposition (`ops_compaction` stays live for those two only). See `docs/INTENT-ducklake-consolidation.md`.
- **ID Authority (Decision 84 I-2):** Recommendation IDs are allocated BY THE WRITER atomically with the insert (`file_ops`); decision numbering authority is DECISIONS.md (callers supply `decision_id`). The local JSONL files are read-only caches, not the source of truth.
- **Agent surface:** Three functions only -- `file_rec`, `update_rec`, `sync`. Do not call `sync_ops`, `ops_writer`, or any drain/compact/pull CLIs directly. Reads and writes transit the closed DuckLake reader/writer boundary via the agent_platform static-key chain; raises `RuntimeError` if unreachable.
- **Failure mode (Decision 84 I-4):** there is NO offline outbox. A write that cannot complete FAILS LOUDLY at the call site (after an idempotent transient-5xx retry); re-file after restoring connectivity (verify with `aws sts get-caller-identity --profile agent_platform`). `sync()` only refreshes the local read cache and returns `{"pulled": ...}`.
- **SCD Type 2:** Append-only SCD2 semantics; the DuckLake reader serves the current-state projection directly (no query-time view dedup).

### Data Quality Enforcement

DQ checks for all ops and telemetry tables are defined in `config/agent/data_quality/ops.yaml`
and `config/agent/data_quality/telemetry.yaml`. The DQ runner is invoked by `scripts/validate.py`
presubmit tier; results land in `logs/debug/dq-latest.json`.

The remediation arc uses a shared protocol and per-table decision manifests:
- Protocol and root cause taxonomy: `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`
- Per-table decision manifests: `config/agent/data_quality/decisions/{table}.yaml`

Each manifest records root cause class, enforcement readiness, and human decision (pending /
approved / deferred / declined) for every field. Load the manifest and briefing at the start
of any remediation session; walk only `human_decision: pending` fields one at a time.

### Field Architecture Decisions

The following decisions apply across the ops table schema and were established during the
2026-05-06 remediation session for `ops_recommendations`.

**source as lineage key, not routing enum**

The `source` field identifies the agent type that filed a recommendation. It is a first-class
lineage key -- equivalent in importance to `session_id` for future cross-table telemetry joins
(e.g., correlating recommendation origin with execution outcomes). `source` must be
harness-injected as `AGENT_TYPE`; agents must not self-assign or guess this value. New agent
types must register in `config/agent/data_quality/source_registry.yaml` and pass a CI gate before
their first production invocation.

**execution fields pending normalisation**

The fields `execution_result`, `execution_date`, `execution_branch`, `execution_pr_url`, and
`execution_steps` are deferred pending an architectural review: do they belong in
`ops_recommendations` (current location) or normalised to telemetry tables where `session_id`
already provides the joining key? The `resolution` field semantics depend on this decision.
Do not add DQ enforcement for these fields until the review is complete.

## Project

**North Star:** Build a self-improving automated trading system. This is achieved through an iterative feedback loop where every aspect of the repository -- code, workflow, tooling, documentation, and the agents themselves -- continuously improves based on captured lessons and friction points.

Dual-environment trading system: AWS (formula discovery) + Docker (live trading).
Phase 1 complete. Phase 2 (schema backfill) next. Phases 3-7 planned. Phase Platform (automation infrastructure) runs in parallel.
See [docs/ROADMAP-PRODUCT.yaml](../docs/ROADMAP-PRODUCT.yaml) for product phases and [docs/ROADMAP-PLATFORM.yaml](../docs/ROADMAP-PLATFORM.yaml) for platform tier items. See [docs/DECISIONS.md](../docs/DECISIONS.md) for rationale.

## Roadmap reference disambiguation

Two roadmap files exist since PR #335. Apply this rule per call site:

- **Product context** (phases, milestones, market features, trading capabilities, Phase 1-7 progress) -- reference `docs/ROADMAP-PRODUCT.yaml`
- **Platform context** (tier_items, infrastructure governance, candidate_decisions, AWS/Lambda topology, T-0 / T-1 / T-N bootstrap work) -- reference `docs/ROADMAP-PLATFORM.yaml`
- **Both** (e.g. doc-freshness checking all roadmap content; documentation_update authoring across both; plan-critique checking phase AND tier alignment) -- reference both explicitly, with a short note explaining which dimension each addresses

## AWS

- **Region**: eu-west-2
- **Account**: personal platform account (ID supplied via gitignored `terraform/personal/terraform.personal.tfvars`; never committed)
- **Profile**: `agent_platform` (PlatformDev, runtime; static-key assume-role) -- agents use this profile for all operations. `agent_platform_admin` (PlatformAdmin) is used for provisioning (IAM + OIDC) only.
  - Environment promotion is human-triggered via GitHub Actions, not agent-initiated
  - **Credential model (static-key, supersedes Decision 57's SSO-recovery semantics):** the near-powerless `agent_static` IAM key assumes `PlatformDev`/`PlatformAdmin` via STS; sessions auto-refresh and there is no interactive login. Autonomous executors (Lambda) skip credential-dependent verifiers (emitting SKIPPED) to prevent pipeline deadlocks; they never attempt recovery.
  - `creds_status: "unavailable"` -- **Static-key recovery (non-fatal, Decision 60):** verify the chain with `aws sts get-caller-identity --profile agent_platform`; refresh `~/.aws/credentials` if `agent_static` was rotated. Do NOT block -- preflight continues in degraded mode (warehouse reads degrade loudly (recs_read_status / verb failures), cache fallback where designed).
  - See Decision 24 in `docs/DECISIONS.md` for rationale
- **Glue database**: agent_platform
- **Athena workgroups**:
  - `agent-platform-production` (engine v3) -- used for OPTIMIZE, MERGE writes, and all production queries
  - `agent-platform-lab` (engine v3) -- used for PySR formula discovery queries
  - `primary` (engine v2, default) -- **do not use** for Iceberg operations; does not support `VACUUM` or full Iceberg DML
- **S3 bucket**: `agent-platform-data-lake` -- Iceberg data lake, Athena query results, and agent/cron log storage (set as `s3_agent_logs_bucket` in `config.personal.yaml`; see `scripts/s3_log_store.py`).
- **Lambda runtime**: Python 3.12
- **Lambda layers**: AWSSDKPandas-Python312:22 (managed) + extras (yfinance/pyyaml, ~11 MB)
- **LLM substrate**: DeepSeek-direct via LiteLLM (Tier 1) + Anthropic-direct Claude (Tier 2 escape hatch); Bedrock is fully retired for the dev surface (CD.28). Executor is FROZEN (Decision 67); when unfrozen it will consume this substrate, not Gemini CLI or Bedrock.
- **CI runner**: GitHub-hosted `ubuntu-latest` with OIDC to the personal account (CD.21; superseded Decision 68). Branch role `agent-platform-github-ci-branch`, PR role `agent-platform-github-ci-pr`. See `terraform/personal/oidc.tf`.

## File Router

| Topic | Look here |
|-------|-----------|
| Trading system design / data flow | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) |
| Development workflow / CI / telemetry | [docs/ARCHITECTURE-WORKFLOW.md](../docs/ARCHITECTURE-WORKFLOW.md) |
| Product roadmap (phases, milestones) | [docs/ROADMAP-PRODUCT.yaml](../docs/ROADMAP-PRODUCT.yaml) |
| Platform roadmap (tier_items, infra, governance) | [docs/ROADMAP-PLATFORM.yaml](../docs/ROADMAP-PLATFORM.yaml) |
| Technical decisions | [docs/DECISIONS.md](../docs/DECISIONS.md) |
| Setup / deploy / troubleshoot | [docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md) |
| Config reference | [config/README.md](../config/README.md) |
| Terraform / infra | [terraform/README.md](../terraform/README.md) |
| Data pipeline code | [src/data/](../src/data/) -- pipeline.py, feature_engine.py, writer.py |
| Lambda handlers | [src/data/handlers/](../src/data/handlers/) -- fetch, features, write, maintenance, discovery |
| Table maintenance | [src/data/handlers/maintenance_handler.py](../src/data/handlers/maintenance_handler.py) |
| Iceberg table schemas | [terraform/iceberg_tables.tf](../terraform/iceberg_tables.tf) |
| Step Functions / IAM | [terraform/data_pipeline.tf](../terraform/data_pipeline.tf) |
| Formula discovery | [src/lab/pysr_factory.py](../src/lab/pysr_factory.py) |
| Live trading | [src/live/rat_ensemble.py](../src/live/rat_ensemble.py) |
| Execution engine | [src/execution/async_engine.py](../src/execution/async_engine.py) |
| Meta-learner | [src/meta_learner/gating_network.py](../src/meta_learner/gating_network.py) |
| Cost / budgets | [terraform/cost_monitoring.tf](../terraform/cost_monitoring.tf) |
| Local CI / validation | [scripts/validate.py](../scripts/validate.py) |
| Lambda build and deploy | [scripts/build_lambda.py](../scripts/build_lambda.py) |
| S3 log store (agent logs) | [scripts/s3_log_store.py](../scripts/s3_log_store.py) |
| Rec/Decision write portal | [scripts/ops_data_portal.py](../scripts/ops_data_portal.py) |
| LLM client (LiteLLM / provider-agnostic) | [scripts/llm_client.py](../scripts/llm_client.py) |
| LLM utilities (parsing/errors) | [scripts/llm_utils.py](../scripts/llm_utils.py) |
| Bedrock Converse API client (retired; retained as architectural artefact) | [scripts/bedrock_client.py](../scripts/bedrock_client.py) |
| Tool runtime (agentic tools) | [scripts/tool_runtime.py](../scripts/tool_runtime.py) |
| Model routing config (provider + tier mapping) | [config/agent/copilot/model_routing.yaml](../config/agent/copilot/model_routing.yaml) |
| Model registry (resolver, escalation) | [scripts/model_registry.py](../scripts/model_registry.py) |
| Gemini CLI context file | [GEMINI.md](../GEMINI.md) |
| Instruction architecture contract | [docs/contracts/instruction-architecture.yaml](../docs/contracts/instruction-architecture.yaml) |
| Interactive orientation workflow | [.claude/commands/orient.md](../.claude/commands/orient.md) (canonical). Read-only; run before `/plan` to choose what to work on. |
| Interactive planning workflow | [.claude/commands/plan.md](../.claude/commands/plan.md) (canonical) |
| Interactive implementation workflow | [.claude/commands/implement.md](../.claude/commands/implement.md) (canonical) |
| Interactive workflow skills (methodology) | [.claude/skills/](../.claude/skills/) (canonical) |
| Planning / entry point (Opus) | [.claude/commands/plan.md](../.claude/commands/plan.md) (canonical) |
| Branch-specific plan files | `docs/plans/PLAN-{slug}.md` (merged to main; handed off to `/implement` by path) |
| Implementation entry point | [.claude/commands/implement.md](../.claude/commands/implement.md) (canonical) |
| Pre-session checks (env, recs, friction) | [scripts/session_preflight.py](../scripts/session_preflight.py) |
| Post-session automation (validate, commit, push) | [scripts/session_postflight.py](../scripts/session_postflight.py) |
| Subagents and Reviewers | [.claude/skills/](../.claude/skills/) (canonical) |
| Plan execution audit | [scripts/plan_audit.py](../scripts/plan_audit.py) |
| Session metrics | [scripts/session_metrics.py](../scripts/session_metrics.py) |
| Test coverage enforcement | [scripts/test_coverage_checker.py](../scripts/test_coverage_checker.py) -- AST-based; validates test file existence and per-file 100% coverage for new code |
| Prompt compliance verification | [scripts/prompt_compliance.py](../scripts/prompt_compliance.py) -- Parses `## Behavioural Invariants` YAML from prompts; validates against retro-lite log and execution state |
| North Star tracker | [scripts/north_star_tracker.py](../scripts/north_star_tracker.py) |
| Human workflow guide | [docs/AGENT_WORKFLOW.md](../docs/AGENT_WORKFLOW.md) |
| CI triage | [.claude/skills/orient/SKILL.md](../.claude/skills/orient/SKILL.md) -- CI RCA Recs surfaced in orient |
| GitHub MCP config | [.mcp.json](../.mcp.json) |
| Session continuity log | [docs/SESSION_LOG.md](../docs/SESSION_LOG.md) |
| Scheduled agent manifest | [.github/agents/schedule.yaml](../.github/agents/schedule.yaml) |
| Scheduled agent dispatcher (Lambda) | [src/data/handlers/scheduled_agent_handler.py](../src/data/handlers/scheduled_agent_handler.py) |
| Findings processor (Lambda) | [src/data/handlers/findings_processor_handler.py](../src/data/handlers/findings_processor_handler.py) |
| GitHub Models API client | [scripts/github_models_client.py](../scripts/github_models_client.py) |
| Copilot SDK client (Lambda) | [scripts/copilot_sdk_client.py](../scripts/copilot_sdk_client.py) |
| Scheduled agent local runner | [scripts/run_scheduled_agent.py](../scripts/run_scheduled_agent.py) |
| Scheduled agent prompts | [.github/prompts/scheduled/](../.github/prompts/scheduled/) -- doc-freshness, orphan-code, transcript-review, code-smell, findings-compare |
| Scheduled agent infrastructure | [terraform/scheduled_agents.tf](../terraform/scheduled_agents.tf) -- Lambda dispatcher for scheduled agents; deploy per-Lambda via manifest-derived gating (Decision 79, CD.16) |
| CI runner infrastructure | [terraform/personal/oidc.tf](../terraform/personal/oidc.tf) -- GitHub-hosted runners + OIDC roles (CD.21). [terraform/ec2_runner.tf](../terraform/ec2_runner.tf) retained as a retired-runner artefact |
| Customisations manifest script | [scripts/list_customizations.py](../scripts/list_customizations.py) |
| Recommendations migration script | [scripts/migrate_recommendations.py](../scripts/migrate_recommendations.py) |
| Friction analysis JSONL log | [logs/.friction-analysis-log.jsonl](../logs/.friction-analysis-log.jsonl) |
| Metrics analysis JSONL log | [logs/.session-metrics-log.jsonl](../logs/.session-metrics-log.jsonl) |
| Plan audit JSONL log | [logs/.plan-audit-log.jsonl](../logs/.plan-audit-log.jsonl) |
| North Star JSONL log | [logs/.north-star-log.jsonl](../logs/.north-star-log.jsonl) |
| Machine-readable recommendations | [logs/.recommendations-log.jsonl](../logs/.recommendations-log.jsonl) |
| Cron rejection memory | [logs/.rejected-suggestions.jsonl](../logs/.rejected-suggestions.jsonl) |
| Decision index | [logs/.decisions-index.jsonl](../logs/.decisions-index.jsonl) |
| Execution checkpoint state | [logs/.execution-state.json](../logs/.execution-state.json) |
| Execution state management | [scripts/execution_state.py](../scripts/execution_state.py) |
| Session telemetry (executor) | [scripts/executor/telemetry.py](../scripts/executor/telemetry.py) |
| PR template | [.github/pull_request_template.md](../.github/pull_request_template.md) |

## Recommendations Log Schema

The file `logs/.recommendations-log.jsonl` is used in nearly every session. When writing or updating entries, use this schema:

```json
{
  "id": "rec-NNN",           // Required. Format: rec-001 through rec-999+
  "date": "YYYY-MM-DD",      // Required. ISO date of creation
  "title": "...",            // Required. Concise description (< 100 chars)
  "source": "...",           // Required. Origin: executor-supervision, code-review, planning, brainstorm
  "effort": "XS|S|M|L|XL",   // Required. Estimated implementation effort
  "priority": "Critical|High|Medium|Low",  // Required
  "status": "open|closed|failed|declined|superseded",  // Required. See canonical values below
  "automatable": true|false, // Required. Can the executor handle this?
  "risk": "low|medium|high", // Required. Risk level for automated execution
  "file": "path/to/file.py", // Required. Primary target file
  "context": "...",          // Required. Why this rec exists, cite sources
  "acceptance": "command",   // Required. Shell command that returns 0 on success (structural: code landed)
  "verification": "command", // Optional. Shell command for behavioural end-to-end proof (runs post-acceptance, warning-only on failure)
  "verification_tier": "V1|V2|V3",  // Optional. V1=static, V2=unit, V3=integration (deploy+invoke)
  "dependencies": ["rec-XXX"], // Optional. Array of blocking rec IDs
  "tags": ["tag1", "tag2"],  // Optional. Categorisation tags
  "resolution": "...",       // Optional. Why declined/superseded (required if status is declined/superseded)
  "execution_result": "success|failure|manual|already_implemented",  // Set by executor on close
  "execution_date": "ISO-8601",  // Set by executor
  "execution_branch": "agent/rec-NNN",  // Set by executor
  "execution_pr_url": "https://...",    // Set by executor
  "execution_steps": 3                  // Set by executor (step count)
}
```

**Status values:** Only `open`, `closed`, `failed`, `declined`, `superseded` are valid. Never use `done`, `complete`, or `implemented`.

**Spacing:** Use `"key": "value"` (space after colon) for consistency.

**Acceptance vs Verification:** `acceptance` checks that the code landed correctly (structural: grep, pytest). `verification` proves the feature works end-to-end (behavioural: invoke the system). The executor runs verification after acceptance passes; verification failure emits a warning but does NOT block the merge. Both fields ban `python -c` one-liners (Windows bash compatibility).

## Known Gotchas

- **Rec/Decision Write Portal (Critical):** Never append to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly. All writes MUST go through `python -m scripts.ops_data_portal` or the Python API.
  - **ID Authority (Decision 84 I-2):** rec-NNN ids are allocated by the ducklake_writer atomically with the insert; decision ids follow DECISIONS.md numbering. The local JSONL is a read-only cache; `ops_data_portal.sync()` only rebuilds it from the reader.
  - **Failure mode (Decision 84 I-4):** there is NO offline outbox. A failed write raises loudly -- re-file after restoring the static-key chain (verify with `aws sts get-caller-identity --profile agent_platform`).
  - **Deduplication:** SCD Type 2 append-only semantics; the DuckLake reader serves the current-state projection.
  Direct file writes are caught by `validate.py` and will fail CI. Status changes (closing recs) must also use the portal.

- **Git branching workflow:** On Claude Code on the web the harness creates the per-session branch; do NOT create `agent/` branches. Never commit directly to `main`. Merge via a GitHub MCP PR (no local `gh`); wait for CI event-driven via `subscribe_pr_activity`, then squash-merge via `merge_pull_request`. See Decision 76.

- **Executor self-modification boundary (Critical):** Recs targeting executor machinery files must have `automatable: false`. The executor must not modify its own code, prompts, instructions, or tests. Boundary files: `scripts/execute_recommendation.py`, `scripts/executor/*.py`, `config/agent/executor/prompts/*.prompt.md`, `.github/instructions/executor-*.instructions.md`, `scripts/copilot_wrapper.py`, `scripts/llm_client.py`, `scripts/llm_utils.py`, `scripts/tool_runtime.py`, `tests/test_execute*`, `tests/test_executor_*`, `tests/test_copilot_wrapper.py`, `tests/test_llm_client*`, `tests/test_llm_utils*`, `tests/test_tool_runtime*`. These recs go through `/plan` -> `/implement` instead. See Decision 44. Enforced by `validate_executor_boundary()` in `validate.py`.

- **Venv and Python:** Python 3.12+ on Linux container. Always invoke via `bin/venv-python` (wrapper auto-resolves the venv). Verify: `bin/venv-python -c "import sys; print(sys.executable)"`. If the venv is missing, run `bin/setup-cloud-env.sh` (canonical CC-web/Linux setup). Do not use `source .venv/bin/activate` -- each Bash tool invocation is independent; the wrapper handles activation.

- **Import Safety Patterns (Critical):** Never raise exceptions during module import -- breaks pytest collection in CI. Defer validation to explicit `validate()` calls. BAD: `if not os.path.exists(f): raise FileNotFoundError`. GOOD: `logger.warning(...); return default`. Import optional external deps at module level with `try/except ImportError` using a sentinel class fallback. Config modules must load successfully even if config files are missing -- use lazy loading with warning logs.

- **Terraform File-Optional Operations (Critical):** Always wrap `filemd5()` and `file()` calls on optional artifacts with `try()`. BAD: `source_code_hash = filemd5("build/lambda.zip")`. GOOD: `source_code_hash = try(filemd5("build/lambda.zip"), md5(file("module_file.tf")))`.

- **Athena/Iceberg Limitations:** `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS` -- issue one column per statement, ignore "already exists". `VACUUM` requires engine v3 -- always use `WorkGroup='agent-platform-production'`. `CREATE TABLE IF NOT EXISTS` does not update TBLPROPERTIES -- use `ALTER TABLE SET TBLPROPERTIES` for existing tables.

- **Path Migration Completeness (Medium):** When moving files, grep for ALL references before migrating. Update prompt files, agent files, script path constants. Verify post-migration with grep. Audit both input and output sides of test mocks.

- **File deletion reference sweep (Important):** Grep for all references BEFORE deleting a file. Update all `.prompt.md`, `.agent.md`, and script path constants in the same session. Verify post-deletion with grep.

- **Browser content fetching:** `open_browser_page` opens browser but does not return content. Always follow with `fetch_webpage`.

- **replace_string_in_file context boundary:** Include 3-5 lines of unchanged code before and after target text. Weak boundaries cause wrong-occurrence matches or silent formatting changes.

- **multi_replace_string_in_file anchor uniqueness:** Ensure each `oldString` has unique anchor text. Increase context lines (5-7) or split into single-replacement calls if ambiguous.

- **Git worktrees for parallel development:** Setup: `git worktree add ../agent-platform-{slug} agent/{slug}`. Remove after merge: `git worktree remove ../agent-platform-{slug}`.

- **validate.py: Import validation requires sys.path injection (Medium):** Inject `str(ROOT)` into `sys.path` at start of `validate_imports()` execution; remove in finally block.

- **ruff E501 and multi-line section builders (Medium):** Define intermediate `_header`, `_footer`, `_section` variables for long f-strings to stay under 127 chars.

- **State machine exit path completeness (Important):** Every exit path from a state machine must call the state-clearing function. Test all paths. See Decision 34.

- **Known failure mode documentation lag (Important):** When a documented failure actually occurs, update the prompt/agent file with observed details in the same session.

- **Test Isolation Patterns (Critical):** Never spawn `pytest tests/` (full suite) from a script any test imports -- recursion risk. Three-layer defense: `_VALIDATE_DEPTH` env var in `validate.py`, `_COVERAGE_SUBPROCESS` env var, `tests/conftest.py` sets both. Always mock both `subprocess.Popen` AND `subprocess.run` in tests for subprocess-spawning functions. Mock `pathlib.Path.exists()` for tests that assume files don't exist. Use `missing_ok=True` for `Path.unlink()` in cleanup paths. After removing a test class, run `ruff check --fix` (F401); after adding one, verify all modules used in `side_effect=` or assertions are imported at module scope.

- **test_coverage_checker requires test files for ALL modified source files (Medium):** Every source file modified on a branch must have a corresponding test file with 100% coverage. Plan test stub creation when modifying pre-existing scripts without test files.

- **ruff format duplicate import consolidation (Critical):** Never split the same module's imports across two blocks -- ruff silently drops symbols from the second block during format. Use one consolidated block with `# noqa: F401`.

- **Monolith-to-package refactor: Test namespace migration (Important):** All `@patch("module.symbol")` calls must be updated to new submodule locations. Enumerate via grep before refactoring; use a bulk replacement script for large test suites.

- **Batch file modification + ruff linting cascade (Medium):** Modify 1-2 files, run `ruff check --fix` immediately, then proceed. Never batch-modify multiple files before running ruff.

- **S3 backend + local mocking pattern (Medium):** Use a `get_backend()` switch so local mode preserves original file paths that tests mock. Bypassing mocked paths via absolute paths causes silent test failures.

- **CI runner credential pattern (Important):** GitHub-hosted runners (CD.21) assume the OIDC role `agent-platform-github-ci-branch` (or `-pr` on pull requests) via `aws-actions/configure-aws-credentials`, which exports standard AWS credential env vars. There is no `~/.aws/config` on the runner, so code resolving a named SSO profile (`agent_platform`) must fall back to boto3's default credential chain when those env vars are present. The CC-web container resolves via the named profile.

- **Terraform workflow integration (Important):** Plans with `.tf` files require `terraform plan` output presented to human before applying. Apply is human-gated EXCEPT the sandbox PLATFORM environment, where push-to-main auto-applies behind the deterministic guard (`scripts/terraform_apply_guard.py`, which fails closed on any destroy/IAM/trust change) plus a subagent plan review, per Decision 77 and `docs/contracts/environment-taxonomy.md`. SIT/PROD stay human-gated (and are future-state). See `plan.prompt.md` Step 4 (Infrastructure Assessment).

- **Lambda deployment pipeline -- per-Lambda gating (Important, Decision 79 + CD.16 + CD.24):** Lambda packaging is manifest-driven. Use `bin/venv-python -m scripts.lambda_manifest --list-patterns` to identify Lambda-packaged files and `compute_affected_artifacts(changed_files)` (from `scripts/lambda_manifest`) to determine which active artifact slugs are affected. If any affected artifact is `status: active` (in `src/lambdas/<slug>/manifest.yaml`): (1) build with `bin/venv-python -m scripts.build_lambda` (builds all artifacts; add `--skip-upload` to build without uploading), (2) deploy with the `--deploy` flag (uploads to S3 and updates Lambda function code), (3) post-deploy verification using `run_scheduled_agent.py --smoke-test NAME`. Use `--list-bundle <slug>` to emit a single artifact's staged file list (VP file-list-equivalence diffs). Stub artifacts (`status: stub`) need no deploy step. `config/agent/` is NOT Lambda-packaged. The blanket `build_lambda.py --deploy` for all functions is retired; build only the affected artifact(s). Copilot SDK model IDs (e.g., `claude-haiku-4.5`, `claude-sonnet-4.6`) differ from Bedrock format (revoked) and GitHub Models IDs. See `docs/contracts/inference-provider.md` and Decision 49.

- **Copilot SDK auth requires OAuth token, not PAT (Important):** `SubprocessConfig(github_token=...)` in `scripts/copilot_sdk_client.py` requires a GitHub OAuth token (`gho_` prefix from `gh auth token`), NOT a classic PAT (`ghp_`). The Copilot API rejects PATs with `400 Personal Access Tokens are not supported`. The `agent-platform-github-pat` secret in Secrets Manager must contain the `gho_` token. Refresh by running `gh auth token` and updating the secret: `aws secretsmanager put-secret-value --secret-id agent-platform-github-pat --secret-string "$(gh auth token)"`. Also: the Copilot CLI binary extracts to `$HOME` at startup; Lambda has no home dir for the sandbox user -- `SubprocessConfig(env={"HOME": "/tmp"})` is required.

- **Copilot SDK PermissionHandler location (Important):** `PermissionHandler` is in `copilot.session`, not the top-level `copilot` package. Correct import: `from copilot.session import PermissionHandler`. The `create_session()` kwarg is `on_permission_request=PermissionHandler.approve_all` (not `permissions=`).

- **Acceptance command format in executor planning prompts (Important):** Write a SINGLE inline backtick command. No trailing prose after the backtick. Use relative paths from repo root. Write `python -m scripts.MODULE` not `python scripts/MODULE.py`. No fenced code blocks. No `###` inside `grep -E` patterns.

- **Copilot CLI `@file` vs user message (Critical for executor):** `-p @filepath` as a standalone argument injects file contents as **document context**, not as a user instruction. Agentic models receiving context ask "what should I do with this?" and act on it -- they implement the spec instead of planning against it. This is the root cause of agentic planning loops. Correct pattern: put the `@filepath` **inside** the `-p` quoted argument so the CLI expands it inline as user-message content: `copilot -p "Generate a step-by-step plan for the attached spec. Do not write any code. @spec.txt"`. In `copilot_call()`, this means the `-p` arg must be `f"{inline_instruction} @{context_file_path}"`. Using `--share` does NOT inject content (it only sets transcript output path). `_PLAN_EXCLUDED_TOOLS` is a safety net, not the fix. See rec-119, rec-252.

- **postflight.py function mock exhaustion (Important):** When adding `subprocess.run` calls to any function in `scripts/executor/postflight.py` (e.g., `cleanup_after_merge()`, `finalize()`), count the total call sequence and update the mock `side_effect` counts in the corresponding tests in `tests/test_execute_recommendation.py`. A missing mock entry causes silent `StopIteration` failures that only surface in CI. See rec-117, rec-325.

- **Lambda tag values must use ASCII-safe characters (Medium):** Use plain ASCII hyphens (`-`) instead of em dashes in all Terraform tag values.

- **Lambda zipped deployment size limit (Important):** AWS Lambda has a hard zipped package limit (~262144000 bytes). If a built zip plus layers exceeds this, split functionality into a minimal handler zip (small deploy) and separate support zips, or move heavy deps to layers that fit the account limits. Add a build check in `scripts/build_lambda.py` to assert the final zip size and fail with a clear diagnostic early.

- **awswrangler 3.x API rename (Medium):** awswrangler 3.x renamed `temp_s3_dir` → `temp_path`. Verify `awswrangler.__version__` before calling APIs or pin the version in `requirements.txt` and document the expected parameter name in plans involving Iceberg writes.

- **awswrangler `fill_missing_columns_in_df=True` behaviour (Medium):** When True awswrangler will re-add missing Iceberg schema columns as `object`/null-typed columns which can break writes for `array<>` or typed array columns. For Iceberg tables with `array<string>` / `array<int>` types, prefer explicit per-table dtype overrides (e.g., `_TABLE_DTYPES`) or set `fill_missing_columns_in_df=False` and provide the full column set to avoid ambiguous `object` dtypes.

- **Iceberg integer promotion (Medium):** Iceberg/engine writes may have previously promoted `int` columns to `long`/`bigint`. Attempts to re-declare these as `int` will fail with "Cannot change column type: long -> int". When writing schema/dtype overrides, detect and honor existing promoted types (use bigint/long where present).

- **build_lambda S3 bucket vs Terraform bucket (Low):** Ensure `scripts/build_lambda.py` uploads to the same S3 bucket referenced by Terraform (compare against `terraform output` or repo config). A mismatch (e.g., a stale config referencing a retired bucket vs `agent-platform-data-lake`) causes deployed Lambdas to reference the wrong artifact bucket; validate and fail early in the build step.

- **Pytest `-k` selector gotcha (Important):** Avoid using `-k` selectors in acceptance commands for test steps. LLM-generated test names are unpredictable and may change between runs, causing brittle or failing acceptance checks. Instead, use `grep` to verify the test exists, and run tests using the `python -m pytest tests/test_file.py::ClassName` format to ensure robust validation.

- **File rewrite pattern (Important):** To safely rewrite a file's entire contents, use rename-create-delete: rename `file.py` to `file-old.py`, create new `file.py` with desired contents, delete `file-old.py`. This works because `edit` (replace_string_in_file) only replaces matching text (doesn't truncate) and `create` refuses to overwrite. Never use `edit` to replace an entire file's contents in one operation -- partial matches or whitespace differences cause silent failures.

- **Gemini CLI version required (Important):** Stable (0.39.x) runs Gemini 1.5 Pro -- NOT Gemini 3. Preview (0.40.0+) is required for Gemini 3 models (`gemini-3-pro-preview`, `gemini-3-flash-preview`). Install: `npm install -g @google/gemini-cli@preview`. The `--model` flag does NOT override sub-agent model selection in multi-turn mode. Executor uses Auto mode (no `--model` flag) for XS/S/M tasks; explicit `--model gemini-3-pro-preview` for L/XL and executor/prompt files. See Decision 53 and `scripts/model_registry.py`.

- **Executor provider resolution (Important):** `llm_client._resolve_provider()` delegates to `model_registry.resolve_provider()` which defaults to `"gemini"`. `execute_recommendation.py` also sets `os.environ.setdefault("LLM_PROVIDER", "gemini")` as a safety net. Lambda handlers route by `schedule.yaml` provider field, not by `LLM_PROVIDER` env var. To switch the executor to Bedrock: `LLM_PROVIDER=bedrock python -m scripts.execute_recommendation ...`.

---

## Platform End-State (derived from ROADMAP-PLATFORM.yaml)

Derived from ROADMAP-PLATFORM.yaml @ e588678 (2026-06-28). NON-AUTHORITATIVE cache: a materialized query of the roadmap, NOT a source of truth; re-synthesize via a fresh subagent to refresh. roadmap_tier_id_set sha256: f5072e405c65dee3c5cd216d11ef6bf1e9fedfe80bf628b63cf1c4be7db946c6

This is the destination: what the platform looks like once the entire ROADMAP-PLATFORM.yaml
work-list is implemented. PLATFORM = the infrastructure/governance/automation substrate
underneath the trading system (ROADMAP-PRODUCT.yaml is the sibling product axis). Present tense
describes the target; "[future]" marks parts not yet live.

North Star (NS.1-NS.5): storage durable / compute interchangeable; personal AWS account (IP
ownership); hybrid compute (cloud orchestration + local rig for CPU-bound batch); the repo is for
agents; the agent surface is self-describing typed verbs over HTTPS with Pydantic schema-as-code.

### 1. Self-improvement / recursive loop
The four-tier workflow (Decision 90) runs end-to-end with no human in the critical path of one
iteration (the Platform-MVP boundary, Decision 93):
- /orient (read-only) surfaces eligible work, CI-RCA triage, and ranked /plan prompts -> /plan
  produces a schema-validated PLAN-{slug}.yaml (PlanDocument, Decision 85/CD.22) -> /implement
  executes or scopes -> /develop-executor supervises the autonomous executor [future].
- Recommendations and decisions are the loop's currency. Findings (code review, scheduled agents,
  CI-RCA, telemetry analysis) become ops_recommendations rows via the portal; architectural
  commitments become ops_decisions rows.
- The autonomous executor (T4) is the end-state consumer of the rec queue. Today it is FROZEN
  (Decision 67 STRATEGIC-plan clause, reversed only by CD.17 when T4.2 is stable +14d, T3.2
  verifier PASS, T3.3 +7d). In the end-state, recs flow queue -> executor -> plan/critique/
  revision -> GitHub Actions verification -> merge, with RCA-on-failure (Decision 55: stop
  cleanly, diagnose, file a permanent-fix rec; never inline-patch).
- Plans, plan-critiques, and revisions graduate to first-class warehouse entities (ops_plans,
  ops_plan_revisions; T4.5/T4.6, Decision 87), with git authoritative until the autonomous
  producer flips authority [future]. Autonomy escalates through maturity gates A0-A5 (T4.4) keyed
  to verifier pass-rates and drift silence.

### 2. Operational data backbone
- ops_recommendations, ops_decisions, ops_priority_queue live on DuckLake-on-Neon as the SOLE
  backend (Decision 84/CD.31/CD.33/CD.34). No Athena path, no rollback flag. Neon serverless
  Postgres is the DuckLake catalog (replaced RDS, ~$0; egress budgeted per Decision 88).
- Closed reader/writer boundary: reads transit ducklake_reader via NAMED VERBS only (no caller
  SQL); writes transit ducklake_writer with OCC-retry, writer-owned rec-ID keyspace (file_ops
  allocates rec-NNNN in-transaction), and a "current" projection replacing SCD2 _current views.
  Append-only/event-journal write mode coexists with SCD2 per table (T1.14).
- Agent surface = typed Lambda verbs (CD.10, shape per Decision 91): the verb set fronts the
  closed boundary (extensible; not a fixed six). Agents call file_rec/update_rec/sync (and query
  verbs) via boto3+sigv4 over Function URLs with AWS_IAM auth, through the agent_platform
  (PlatformDev) role; PlatformAdmin handles import-mode/break-glass. An agent SDK shim (T0.8)
  hides URL discovery, signing, retry, and idempotency (T1.10).
- Single Portal Invariant + warehouse-as-source-of-truth: all ops writes go through the portal;
  local logs/*.jsonl are read-only caches rebuilt downstream via sync. Writes FAIL LOUDLY (no
  offline outbox, Decision 84 I-4).
- Telemetry: canonical 4-table trace/observation model (Decisions 95-97: ULID keys minted at the
  boundary, event-time day(started_at) UTC partitioning, no downstream re-derivation). Telemetry
  tables migrate onto DuckLake; Phase E (cloud analysis agent, T3.3) reads them. ops_session_log
  / ops_execution_plans are the last Athena/Iceberg holdouts, retired/migrated by T2.26
  (ops_compaction retires with them); docs/DECISIONS.md (T5.4) and docs/SESSION_LOG.md retire
  once ops_decisions is canonical.
- DQ-as-code (CD.12): Annotated-Pydantic models (DqNotNull, DqUnique, ...) are the single source
  of schema + DQ; Iceberg DDL is generated by walking model_fields (T0.13). The DQ runner is a
  SCHEDULED DRIFT ALARM that files recs (T1.6), NOT a merge gate; stateful invariants
  (uniqueness/FK/status-DAG) run in-handler pre-commit and return typed 4xx.

### 3. Trading data / compute pipeline and lakehouse
- S3 + open table formats at every scale (NS.1): Iceberg for market-data/product tables; DuckLake
  for ops/telemetry (Decision 78). Every table is partitioned (CD.9: day(trade_date) market
  data, day(...) event-time ops/telemetry). No unpartitioned-table path.
- DuckDB is the default operational read engine (CD.8, CD.15): embedded, sub-second, queries
  snapshots/DuckLake directly inside the query Lambda; agents see verbs, not SQL or the engine.
  Athena _current views are retired in the personal account; in the DuckLake end-state there is
  no Athena escape hatch (OQ.7 option a) -- ad-hoc scans live behind ducklake_reader; break-glass
  = the audited PlatformAdmin / Neon credential.
- Compute is hybrid (NS.3): PySR formula discovery runs overnight on the local compute node
  (VPN+SSH; T2.6, deferred post-MVP), writing to S3; cloud holds orchestration and state.
- Workflow orchestration is Step Functions (Decision 39), with TCA/cost-curve aggregation Lambdas
  (T3.5) feeding product cost models. Glue database agent_platform, bucket agent-platform-data-lake,
  region eu-west-2.

### 4. Environments and promotion (two-axis taxonomy, Decision 77)
- Platform axis (infrastructure): bootstrap (admin-only, owns the CI/CD role's own IAM, never
  auto-applies) -> sandbox (current personal account, mocked externals, auto-apply on
  push-to-main behind the deterministic guard) -> SIT [future account, manual apply] -> PROD
  [future account, real capital, second approver]. Same code path everywhere; only externals
  (mocked vs real) and apply-gate differ. Single-account until the product axis reaches live_full
  nearing full capital -- that event triggers standing up SIT then PROD.
- Product axis (strategy lifecycle): research -> backtest_canonical -> paper -> live_small ->
  live_full. Advancement is a capital_allocation config change (single-account, never a
  deploy/infra spin-up).
- "promotion" is always axis-qualified; environment and phase are reserved, lint-enforced vocabulary.

### 5. Infrastructure-as-code and convergence (CD.35 waves, Decision 92/94)
- All infra is Terraform under terraform/personal/ (full re-deploy in personal account, not state
  migration; CD.6). Apply is agent-native CI/CD, never from a laptop:
  - PRs run a speculative terraform plan under a least-privilege github_ci_plan role (refs/pull/*
    trust, read-only state, fork-safe).
  - Routine merges to main auto-apply the SAVED plan.bin behind a deterministic guard
    (scripts/terraform_apply_guard.py, fail-closed on any IAM/trust/destroy diff) plus
    subagent plan review.
  - Guard-flagged (fail-closed) applies route to a gated-apply job under the tf-gated-apply GitHub
    Environment, blocking on a required reviewer; on approval it applies the same reviewed plan
    (no re-plan, no TOCTOU).
  - A durable S3 convergence record (green/red, always-written, pipeline-identity-only) makes
    apply outcomes sticky and observed; a scheduled drift detector runs terraform plan
    (alarm-only, exit-code-typed); a convergence-health staleness sensor (T2.35) re-fires if the
    latch goes quiet.
  - Privilege tiering / bootstrap root (T2.23): the CI/CD role's OWN IAM (permissions boundary +
    authority budget) lives in terraform/bootstrap/, breaking the self-grant; in-budget IAM
    auto-apply (guard-consumption) is pending T2.25. CI-role IAM is DRY-composed with
    invoke-implies-permission to prevent drift (T2.34).
- IAM/OIDC roles: runtime agent_platform / agent_platform_admin; CI agent-platform-github-ci-branch
  / -pr; apply-path github_ci_plan / github_ci_apply / convergence-writer (admin-created per
  Decision 98). Lambda code deploys are decoupled from infra applies (ignore_changes =
  [source_code_hash]).

### 6. CI/CD and governance
- Two-tier presubmit (Decision 60/73): validate.py --pre (diff-aware, authoritative on PR CI) +
  full validate.py post-merge. validate.py is the single source of truth -- no CI check exists
  without it.
- CI runs on GitHub-hosted ubuntu-latest + OIDC (self-hosted EC2 runner retired, CD.21). Branch
  protection is live (Decision 83): main-protection ruleset (required: pr-validate +
  terraform-validate), Dependabot, GHAS secret-scanning/push-protection/CodeQL.
- CI-RCA forward-fix (Decision 72): a failed main CI auto-files a source=ci_rca, priority=critical
  rec and hard-blocks /plan until reviewed; fixes are forward-only, never auto-revert, never
  inline-patched ahead of architectural review.
- Merge flow: harness claude/* branch -> push -> GitHub MCP create_pull_request ->
  subscribe_pr_activity + end turn -> CI-green-comment wake -> confirm check runs -> squash-merge
  with Resolves: rec-NNNN trailer (triggers rec-autoclose).
- Validation is a curated asset (CD.29/CD.30): graduated/deduplicated, hard-gate behind a
  hermeticity precondition (T3.6 audit), diff-line-coverage ratchet (CD.30), and meta-validated by
  scheduled mutation testing + deterministic dead-test detection (T3.7).

### 7. Verifier harness / typed checks / graduation registry (T3)
- Filesystem-as-registry verifiers in scripts/verifiers/, exit-code-as-verdict, with a same-PR
  guard (an author cannot weaken their own verifier) and a graduation registry where proven
  verifiers graduate into validation (T3.1, CD.29).
- A causal-chain verifier (T3.2) proves a telemetry record flows PRODUCE -> TRANSPORT -> PERSIST
  -> QUERY -> ASSERT atomically; its latest-run PASS is the gate (G.8) that unblocks the Phase E
  cloud analysis agent (T3.3) and is a precondition for executor autonomy (CD.17).
- Recommendation relevance is a governed lifecycle state (CD.36): a freshness/relevance gate
  prevents starting stale recs (T3.8) and post-merge reconciliation prevents stale recs
  accumulating (T3.9).

### 8. Agent / instruction architecture end-state
- 5-layer instruction model (docs/contracts/instruction-architecture.yaml): L1 universal rules
  (AGENTS.md/CLAUDE.md, ambient) / L2 project knowledge (docs/PROJECT_CONTEXT.md, on-demand) / L3
  slash commands (.claude/commands/) / L4 skills (.claude/skills/) / L5 executor prompts
  (config/agent/executor/prompts/). .claude/ is canonical (Decision 76); legacy top-level
  .github/prompts/*.prompt.md + .github/agents/*.agent.md + .agents/ were deleted at T-1.13;
  .github/prompts/scheduled/ + .github/agents/schedule.yaml survive for scheduled agents;
  full directory deletion remains owned by T5.3 pending scheduled-agent decoupling.
- Agent-first repository (NS.4, CD.13): all artefacts machine-parseable. Standing
  prose-architecture docs are forbidden (Decision 86) -- intent routes to tier_items, rationale to
  Decisions, field semantics to contracts (Class A data schemas, Class B Lambda-verb, Class C
  cross-system). INTENT-*.md docs are fully extracted and deleted (T5.5). Contracts are converted
  to .yaml and wired to their code consumers (T-1.13..T-1.19).
- LLM substrate (CD.28): DeepSeek-direct via LiteLLM (Tier 1) + Anthropic-direct Claude (Tier 2
  warm-fetched escape hatch); Bedrock fully retired. Keys in Secrets Manager (T0.4). Precision
  Context Injection (Decision 66): field semantics surfaced at agent write time.
- Multi-product topology (CD.32): a unified project_id data plane with an IP-boundary-only repo
  axis [future]. Dev surface is Claude Code on the web only (CD.2; Windows VM decommissioned at
  T5.1, legacy dev account retired at T5.2 after 30d grace).

---

**Last Updated**: June 28, 2026
