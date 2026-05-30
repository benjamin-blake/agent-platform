# Development Workflow Architecture

This document describes the development and operational infrastructure of the Lakehouse Trading System repository: the workflow loop, CI/CD strategy, telemetry star schema, executor package, ops data pipeline, and LLM provider architecture. For the trading system design itself (AWS data pipeline, formula lifecycle, live trading), see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Table of Contents

- [Workflow Loop](#workflow-loop)
- [Parallel Workflow Architecture](#parallel-workflow-architecture)
- [CI/CD Strategy](#cicd-strategy)
- [Quantitative Session Monitoring](#quantitative-session-monitoring)
- [Telemetry System](#telemetry-system)
- [Executor Architecture](#executor-architecture)
- [Ops Data Pipeline](#ops-data-pipeline)
- [LLM Provider Architecture](#llm-provider-architecture)
- [Infrastructure as Code](#infrastructure-as-code)
- [Optional Dependencies](#optional-dependencies)
- [Repository Restructuring Patterns](#repository-restructuring-patterns)
- [Related Documents](#related-documents)

---

## Workflow Loop

**Design Principle:** The standard workflow is a 2-chat model with integrated cost optimisation:
- **Chat 1 (Plan):** Clarify intent, create branch, write plan, invoke plan-critique gate
- **Chat 2 (Implement+Close):** Full context available; execute steps with integrated validators, close session, merge, and run retrospective — all in parent context, eliminating subagent serialisation overhead

```
Chat 1: /plan (Opus)
  ├── session_preflight.py (local: env check, recs, friction patterns)
  ├── Clarify intent with human
  ├── git checkout -b agent/{slug}
  ├── Write PLAN-{slug}.md (tracked, committed)
  ├── @plan-critique (Gemini 2.5 Pro — MANDATORY gate)
  └── Ready for Chat 2

Chat 2: /implement (on agent/{slug})
  ├── Read PLAN-{slug}.md
  ├── Ordered Execution Steps with:
  │   ├── @step-validator (GPT-5 mini, after each step)
  │   └── @retro-lite (GPT-5 mini, per-step friction capture)
  ├── @scope-guard (GPT-5 mini, at ~50% complete)
  ├── Optional @code-review (Sonnet)
  ├── Session Close Phase (in parent context):
  │   ├── session_postflight.py --validate
  │   ├── @retrospective (in current context)
  │   ├── session_postflight.py --commit/--push
  │   ├── CI polling + auto-merge
  │   ├── session_postflight.py --log-housekeeping
  │   └── Cleanup local branch
```

**Feedback Loop Closure:**
- Session telemetry is captured to the 7-table Iceberg star schema (see [Telemetry System](#telemetry-system) below)
- Process events replace the legacy `retro-lite-log.jsonl` friction mechanism (deprecated)
- Strategic review (monthly) analyses telemetry patterns and archives resolved decisions
- Repeated process event patterns escalate to recommendations filed via `ops_data_portal.py` for human triage or autonomous executor processing

---

## Parallel Workflow Architecture

**Design Principle:** Enable concurrent feature development by moving branch creation and plan file management into the planning phase. Each feature plan is tracked per-branch, preventing cross-branch contamination and supporting truly concurrent planning.

### The Three-Phase Loop (Sequential per feature, Parallel across features)

1. **Phase 1: Planning** (`/plan` Opus prompt)
   - Clarifies intent with human
   - Creates feature branch: `git checkout -b agent/{slug}`
   - Writes plan file: `PLAN-{slug}.md` (tracked, committed to feature branch)
   - Invokes `@plan-critique` (Gemini) as mandatory gate before handoff
   - Human is now on the feature branch with committed plan

2. **Phase 2: Implementation** (`/implement` prompt)
   - Detects branch-specific plan: derives slug from `git branch --show-current`, searches for `PLAN-{slug}.md`
   - Pre-implementation checklist gate
   - Executes Ordered Execution Steps with per-step validators and mid-point scope-guard
   - Friction capture via process events emitted to telemetry pipeline
   - Final code review offer (optional, external `@code-review` agent)
   - Findings written to `logs/.recommendations-log.jsonl`

3. **Phase 3: Closure** (session close, integrated into Chat 2)
   - Intent verification against `PLAN-{slug}.md`
   - Push, PR creation, CI wait, auto-merge
   - Log housekeeping and local branch cleanup
   - Retrospective in current context

### Plan File Discovery (Canonical Algorithm)

All agents and scripts use this logic to find the plan for the current branch:

```python
def find_plan_file() -> Path | None:
    """Find plan file for current branch or fall back to legacy PLAN.md."""
    branch = git_branch_show_current()

    if branch and branch.startswith("agent/"):
        slug = branch[len("agent/"):]
        branch_plan = ROOT / f"PLAN-{slug}.md"
        if branch_plan.exists():
            return branch_plan

    legacy = ROOT / "PLAN.md"
    return legacy if legacy.exists() else None
```

**Implemented in:** `scripts/plan_audit.py::find_plan_file()`, `code-review.agent.md` Step 0, `scope-guard.agent.md` Step 1, `implement.prompt.md` Step 1.

### Handling Merge Conflicts (Tiered Auto-Resolution)

| Tier | Files | Action | Risk |
|------|-------|--------|------|
| **1** | `SESSION_LOG.md`, `CHANGELOG.md`, `*.jsonl` logs | Auto-resolve: keep both versions (append-only semantics) | Zero |
| **2** | `logs/.recommendations-log.jsonl`, `DECISIONS.md` | Auto-resolve: merge table rows by ID, dedupe on date | Low |
| **3** | `.py`, `.tf`, `.prompt.md`, `.agent.md` | **Escalate to human:** Print conflict, ask for manual resolution | Required |

---

## CI/CD Strategy

**Design Principle:** The agent's terminal is the primary CI loop. GitHub Actions is a thin safety net on PRs, not the primary feedback mechanism.

### Inner Loop (Agent Terminal — primary, SSO-authenticated)

`scripts/validate.py` runs before every commit:
1. Pre-commit hooks (ruff lint+format, detect-secrets, trailing-whitespace)
2. CLI tool verification (scan prompt/agent files for references to `aws`, `gh`, `terraform`, `docker`, etc.; verify presence in PATH)
3. Test coverage enforcement (AST-based: verify new functions have corresponding test files; per-file 100% coverage on changed code)
4. Prompt compliance check (parse `## Behavioural Invariants` YAML from prompts; validate against execution state)
5. Unit tests (`pytest tests/ -m "not integration"`)
6. Coverage ratchet (`pytest --cov=src --cov-fail-under=<threshold>` from pyproject.toml)
7. Type checking (`mypy src/` — informational only until error count reaches zero)
8. Terraform validation (`terraform validate` + `fmt -check`)

For AWS-touching changes, the `--integration` flag adds:
9. Static-key chain check (`aws sts get-caller-identity --profile agent_platform`)
10. Integration tests (`pytest tests/ -m integration`)
11. Terraform plan preview

### Outer Loop (GitHub Actions on PR — safety net only)

`.github/workflows/ci.yml` runs a subset of the same checks (no AWS credentials). Mirrors `validate.py` logic exactly. **Never add checks to `ci.yml` without adding them to `validate.py` first.**

### Single Source of Truth

`scripts/validate.py` is the canonical definition of "validated." If validation logic needs to change, update the script once and both loops inherit the change.

### CI Failure Feedback Loop

When GitHub Actions detects a CI failure that `validate.py` missed locally:
1. **Detection**: session close polls GitHub MCP or `gh` CLI after push
2. **Triage**: `ci_triage.prompt.md` classifies the failure (VALIDATE_GAP, ENV_DIFFERENCE, TEST_FLAKY, WORKFLOW_CONFIG, DEPENDENCY)
3. **Root Cause**: If VALIDATE_GAP, fix `validate.py` FIRST before fixing the code
4. Each triage cycle emits a `process_event` to the telemetry pipeline for pattern detection

---

## Quantitative Session Monitoring

Three deterministic Python scripts provide model-free audit data:

**`scripts/plan_audit.py`** — Drift Detection
- Parses PLAN.md `## Scope` table: extracts file paths and actions
- Runs `git diff --name-only origin/main` to get actual changed files
- Compares planned vs actual (unplanned files, missing files, action mismatches)
- Output: `Planned: X | Changed: X | Unplanned: X | Missing: X` with warnings
- Exit code: Always 0 (informational)

**`scripts/session_metrics.py`** — Quantitative Change Report
- Collects `git diff --stat origin/main` (files changed, lines added/removed)
- Collects pytest results (total tests, passed, failed, test functions added)
- Collects coverage report (current coverage % across src/)
- Output: Key-value format suitable for SESSION_LOG metrics line
- Exit code: Always 0 (informational)

**`scripts/north_star_tracker.py`** — Momentum Analysis
- Reads `SESSION_LOG.md` entries, parses last 30 days
- Categorises sessions by type (Feature, Fix, Refactor, Docs, Infra/Meta, Other)
- Calculates momentum % and infrastructure ratio
- Warns if infra ratio > 40% (product work risk threshold)
- Exit code: Always 0 (informational)

---

## Telemetry System

The telemetry system makes the autonomous self-improving loop observable. Every workflow execution produces structured telemetry that flows into a 7-table Iceberg star schema queryable via Athena. The authoritative schema specification is in [INTENT-telemetry-system.md](./INTENT-telemetry-system.md).

### Purpose

- **Cost control**: per-model, per-phase, per-recommendation cost attribution
- **Process quality**: success rates, rework rates, escalation frequency
- **Autonomous anomaly detection**: cloud agent identifies outlier sessions
- **Prompt performance**: correlate prompt versions with outcomes (via hash)
- **System health**: scheduled agent status, executor improvement trend

### Write Path: Outbox → S3 Staging → Iceberg Compaction

All telemetry follows the same pattern established by Decision 51 (Local-First Outbox):

```
Producer (executor, agent, Lambda)
    |
    v
OpsWriter.emit(table, record)
    |
    +---> Local outbox (synchronous, never fails)
    |     logs/.ops-outbox/{table}/{uuid}.jsonl
    |
    +---> S3 staging (best-effort write-through)
          s3://{bucket}/staging/{table}/trade_date={date}/batch-{uuid}.jsonl

          ... at session close or on schedule ...

Compaction (OpsWriter.compact_all())
    |
    v
Iceberg table in trading_formulas_db
```

**Lambda write path:** Lambda functions (scheduled agents, findings processor) have no persistent filesystem. In Lambda context (`AWS_LAMBDA_FUNCTION_NAME` env var set), writes go directly to S3 staging, bypassing the local outbox.

### 7-Table Star Schema

All telemetry tables live in `trading_formulas_db` with a `telemetry_` prefix. Every table is partitioned by `trade_date` and has `ingested_at` for deduplication.

```
telemetry_sessions (1)
    |-- (N) telemetry_phases
    |       |-- (N) telemetry_steps
    |       |-- (N) telemetry_model_calls
    |       |-- (N) telemetry_process_events
    |       |-- (N) telemetry_transcripts
    |-- (N) telemetry_model_calls
    |-- (N) telemetry_process_events
    |-- (N) telemetry_transcripts

telemetry_agent_invocations (standalone, no FK to sessions)
    |-- (N) telemetry_model_calls (via invocation_id)
    |-- (N) telemetry_transcripts (via invocation_id)
```

| Table | Grain | Key Columns |
|-------|-------|-------------|
| `telemetry_sessions` | One row per workflow invocation | `session_id`, `workflow`, `branch`, `outcome`, `premium_requests_total`, `rework_count` |
| `telemetry_phases` | One row per phase within a session | `phase_id`, `session_id`, `phase` (enum), `outcome`, `attempt_number`, `model_used` |
| `telemetry_steps` | One row per implementation step | `step_id`, `session_id`, `step_number`, `target_file`, `acceptance_passed`, `retry_count` |
| `telemetry_model_calls` | One row per LLM invocation | `call_id`, `session_id`, `provider`, `model`, `purpose`, `tokens_input`, `tokens_output` |
| `telemetry_process_events` | One row per notable event | `event_id`, `session_id`, `tier` (decision/rework/exception/anomaly), `category`, `severity` |
| `telemetry_transcripts` | One row per LLM conversation transcript | `transcript_id`, `session_id`, `provider`, `model`, `s3_path` |
| `telemetry_agent_invocations` | One row per Lambda scheduled agent run | `invocation_id`, `agent_name`, `provider`, `outcome`, `finding_count` |

**Process Event Tiers:**
- `decision` — System chose one path at a branching point (normal operation, recorded for heuristic tuning)
- `rework` — System looped back to a prior phase (expected sometimes; frequency is the signal)
- `exception` — System invoked an exceptional/escalation path (should be investigated)
- `anomaly` — Statistical outlier detected post-hoc by cloud analysis agent

For full column schemas, canonical category enums, and design rationale, see [INTENT-telemetry-system.md](./INTENT-telemetry-system.md).

---

## Executor Architecture

The autonomous recommendation executor handles the low-risk, automatable pipeline: it reads and updates recommendations via the `ops_data_portal.py` gateway, ensuring ID authority and persistent storage. It plans and implements them without human intervention, and produces structured telemetry as a first-class output.

**Entry point:** `scripts/execute_recommendation.py` — thin orchestrator that delegates to the `scripts/executor/` package.

### Package Structure (12 Submodules)

| Module | Purpose |
|--------|---------|
| `scripts/executor/plan.py` | Plan generation, critique, and refinement loop. Model escalation on failure. Critique cycling detection. |
| `scripts/executor/step_runner.py` | Step implementation via LLM, acceptance command execution, ruff auto-fix, scope enforcement, commit with hook retry. |
| `scripts/executor/postflight.py` | Code review gate with fix-and-recheck loop, validation, CI wait with triage and fix, merge with agent recovery, cleanup. |
| `scripts/executor/ci_triage.py` | Deterministic CI failure classification (lint, import, type, test, unknown) with auto-fix for lint/import categories. |
| `scripts/executor/jsonl_store.py` | Recommendation CRUD with atomic writes, status transitions, acceptance linting, dependency resolution. |
| `scripts/executor/errors.py` | Structured exception types and enums (`StepOutcome`, `CIFailureCategory`). |
| `scripts/executor/acceptance_lint.py` | Static analysis of acceptance commands before execution to catch common failures early. |
| `scripts/executor/model_routing.py` | Route LLM calls to the appropriate provider and model tier based on task and rec attributes. |
| `scripts/executor/telemetry.py` | Emit structured telemetry records for all executor phases, steps, and model calls. |
| `scripts/executor/formatters.py` | Auto-format test files (`auto_format_test_files`, `_run_ruff_fix`, `_run_ruff_format`). |
| `scripts/executor/batch.py` | Batch execution orchestration: priority queue processing, budget management, session metrics. |
| `scripts/executor/__init__.py` | Package exports and version constants. |

### Execution Flow

```
Recommendation JSONL Entry
    |
    v
PREFLIGHT
  Load rec, check eligibility, check acceptance feasibility
  Resume checkpoint or create agent/{rec-id} branch
    |
    v
PLANNING (plan.py)
  Generate plan via LLM
  Critique (mandatory gate)
  Refine if critique finds issues
    |
    v
IMPLEMENTATION (step_runner.py)
  For each step: LLM call → acceptance check → commit
  Scope enforcement on each file change
    |
    v
POSTFLIGHT (postflight.py)
  Code review gate
  validate.py --quick
  CI wait + triage + fix
  Merge + cleanup
    |
    v
TELEMETRY (telemetry.py)
  Session record written to outbox → S3 staging → Iceberg
```

### Design Principles

**Separation of Concerns:** Scripts are the nervous system (deterministic orchestration). LLM calls are the prefrontal cortex (judgment and code generation).

| Deterministic (Script) | Non-Deterministic (LLM) |
|------------------------|--------------------------|
| Load recommendation, check eligibility | Generate implementation plan |
| Create git branch, order step execution | Critique the plan |
| Run validation, acceptance commands | Implement each step |
| Commit, push, PR, merge | Code review + fix |
| Capture telemetry, enforce budget | CI failure diagnosis |

**RCA-First Architecture (Decision 55):** When the executor hits an unrecoverable failure, it stops cleanly, emits a structured `process_event` with `tier=exception`, and invokes an RCA agent that diagnoses root cause and files a recommendation. No rescue agents, no workaround automation. Deterministic recovery (git retry, ruff fix, CLI timeout) remains unchanged.

**Self-Modification Boundary (Decision 44):** Recs targeting executor machinery files must have `automatable: false`. The executor cannot modify its own code, prompts, or tests. Boundary files include `scripts/execute_recommendation.py`, `scripts/executor/*.py`, `config/agent/executor/prompts/`, and related tests.

**SLOC Gate (Decision 43):** No executor file may exceed 500 SLOC without a waiver. Enforced by `scripts/validate.py`. Prevents context budget overflow for LLM calls operating on these files.

---

## Ops Data Pipeline

The operational data pipeline stores recommendations, decisions, session logs, and plan execution data in Iceberg tables, queryable via Athena. It enforces a **Single Portal Invariant** to ensure data integrity and atomicity.

### Single Portal Invariant

All creation, updates, or status changes to recommendations and decisions MUST go through `scripts/ops_data_portal.py`. Never write to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly.

```
Human/Agent → ops_data_portal.py → DynamoDB (ID Authority)
                                 → OpsWriter (Persistence) → S3 Staging → Iceberg
                                 → Local JSONL (Read-only cache)
```

**ID Authority:** Recommendation and decision IDs are allocated atomically via DynamoDB. The local JSONL files are read-only caches, not the source of truth.

**Offline/Pending Outbox:** If AWS credentials are missing, the portal automatically queues records to `logs/.ops-outbox/`. Drain via: `bin/venv-python -m scripts.ops_data_portal --drain --profile agent_platform`.

### OpsWriter

`scripts/ops_writer.py` is the write gateway for all operational Iceberg tables:
- Follows the same outbox pattern as telemetry (Decision 51)
- Stages entries to S3 as JSONL batches
- Compacts into Iceberg at session close via `session_postflight.compact_all()`
- Never raises exceptions to callers (best-effort with degradation)

### Bidirectional Sync

`scripts/sync_ops.py` provides bidirectional sync between local JSONL caches and Athena/Iceberg:
- `pull()` — refresh local cache from Athena (used at session start)
- Stale outbox entries (>24h) flagged by `validate.py`

### SCD Type 2 Semantics

The authoritative store (Athena/Iceberg) uses append-only semantics. Deduplication to the latest record happens at query time via the `ops_recommendations_current` and `ops_decisions_current` Athena views.

### Operational Tables

| Table | Content |
|-------|---------|
| `ops_recommendations` | Recommendations log (SCD Type 2 append-only) |
| `ops_decisions` | Decision index |
| `ops_session_log` | Session log entries |
| `ops_execution_plans` | Executor plan steps per recommendation |
| `ops_priority_queue` | Ranked recommendation priority queue |

---

## LLM Provider Architecture

The executor and repository agents use multiple LLM providers depending on context. The provider landscape is evolving due to company Copilot cancellation and migration to Google ecosystem.

### Current Provider State (April 2026)

| Context | Provider | Model(s) | Notes |
|---------|----------|---------|-------|
| Executor (local) | Gemini CLI | `gemini-3-pro-preview`, `gemini-3-flash-preview`, auto | Decision 53. Default for XS/S/M tasks is auto mode. L/XL uses pro model explicitly. |
| Lambda scheduled agents | Copilot SDK | `claude-haiku-4.5`, `claude-sonnet-4.6` | Decision 54. Requires GitHub OAuth token (`gho_` prefix), not PAT. |
| Bedrock (personal) | Bedrock Converse API | `deepseek.v3.2` | Decision 52. Dormant — quota throttled after first use. Retained for rollback. |

### Routing Architecture

```
scripts/llm_client.py  ← provider-agnostic interface
    |
    +---> _gemini_call()     (LLM_PROVIDER=gemini or default)
    |        via Gemini CLI subprocess
    |
    +---> _bedrock_call()    (LLM_PROVIDER=bedrock)
             via scripts/bedrock_client.py
```

`scripts/model_registry.py` resolves model IDs and providers:
- Reads `config/agent/copilot/model_routing.yaml` for tier → model mappings
- Defaults to `"gemini"` provider when no `LLM_PROVIDER` env var is set
- Supports model escalation: `escalate_model("planning", "flash")` → `"gemini-3-pro-preview"`
- Lambda handlers route by the `provider` field in `.github/agents/schedule.yaml`, not by `LLM_PROVIDER`

### Gemini CLI Requirements

- Stable Gemini CLI (0.39.x) runs Gemini 1.5 Pro — NOT Gemini 3
- Preview (0.40.0+) required for Gemini 3 models: `npm install -g @google/gemini-cli@preview`
- `--model` flag does NOT override sub-agent model selection in multi-turn mode
- The executor uses auto mode (no `--model` flag) for XS/S/M tasks

### Copilot SDK (Lambda)

- Requires OAuth token (`gho_` prefix from `gh auth token`), not a classic PAT (`ghp_`)
- Lambda requires `env={"HOME": "/tmp"}` — Lambda has no home dir for the `copilot` binary
- `PermissionHandler` is in `copilot.session`, not the top-level `copilot` package
- See `scripts/copilot_sdk_client.py` for the implementation

---

## Infrastructure as Code

Terraform modules in this repository use **graceful error handling** for file operations that may not exist in CI or test environments.

### Pattern: try() with Fallback Hash

```hcl
locals {
  lambda_source_hash = try(
    filemd5("${path.module}/../lambda-packages/data-pipeline.zip"),
    md5(file("${path.module}/data_pipeline.tf"))  # fallback to module hash
  )
}
```

**Rationale:** CI may run `terraform plan` before artifacts are built. The `try()` wrapper allows planning to succeed with a fallback hash; production `apply` uses the actual artifact hash.

### Pattern: Conditional Resource Creation

```hcl
resource "aws_lambda_function" "example" {
  count = fileexists("${path.module}/../lambda.zip") ? 1 : 0
}
```

Use `try()` for hash/change detection on optional files. Use `count`/`for_each` for optional resources.

---

## Optional Dependencies

Modules with optional external dependencies define module-level import guards that create a sentinel type if the import fails:

```python
try:
    import awswrangler as wr
    from awswrangler.exceptions import ServiceApiError as _WranglerServiceApiError
except ImportError:
    wr = None
    class _WranglerServiceApiError(Exception):
        """Sentinel class created when awswrangler is not installed."""
        pass
```

This allows:
- Code using optional services to run on non-AWS infrastructure without crashing on import
- CI to run syntax checks without all optional dependencies installed
- Graceful degradation for non-critical features

**Rule:** Never raise exceptions during module import. Defer validation to explicit `validate()` calls. Config modules must load successfully even if config files are missing — use lazy loading with warning logs.

---

## Repository Restructuring Patterns

Large-scale directory restructuring creates systemic risks: path hardcoding in prompts, agents, scripts, and tests can diverge from actual file locations. These patterns emerged from the March 2026 repo restructure.

### Pre-Migration Validation: Enumeration Completeness

Before migrating files, enumerate ALL affected paths:

```bash
# Find all file references
grep -r "FILENAME\.md" . --include="*.py" --include="*.md" \
  --include="*.prompt.md" --include="*.agent.md" --exclude-dir=.git
```

### Two-Sided Path Update (Input and Output)

When updating mocked or patched path constants in tests, audit BOTH sides — where constants are read AND written. Creating only the write-side path in `tmp_path` setup causes FileNotFoundError at runtime.

### Post-Migration Validation

```bash
# Check for bare uppercase .md file references (should be links after migration)
grep -rE '\b[A-Z_]+\.md\b' README.md .github/prompts/*.prompt.md .github/agents/*.agent.md
```

### Canonical Path Discovery Functions

For prompts/agents that need to locate optional files, use a canonical discovery function in the codebase (`scripts/plan_audit.py::find_plan_file()`) rather than hardcoding multiple fallbacks in multiple places.

---

## Related Documents

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Trading system design: AWS data pipeline, formula lifecycle, live trading engine, RAT ensemble. Start here for trading system questions.
- **[INTENT-autonomous-improvement-control-plane.md](./INTENT-autonomous-improvement-control-plane.md)** — Umbrella architecture for closing the recursive self-improvement loop across telemetry, verification, executor RCA, interactive workflows, and recommendation governance.
- **[INTENT-telemetry-system.md](./INTENT-telemetry-system.md)** — Full telemetry schema specification (authoritative, 7-table star schema column definitions).
- **[INTENT-verification-system.md](./INTENT-verification-system.md)** — Programmatic verification architecture: registered verifiers, causal-chain checks, and V3 hard gates.
- **[INTENT-recommendation-executor.md](./INTENT-recommendation-executor.md)** — Executor lifecycle intent document (authoritative spec for autonomous executor behaviour, execution flow, module responsibilities).
- **[ROADMAP.md](./ROADMAP.md)** — Phase plan and feature priorities.
- **[DECISIONS.md](./DECISIONS.md)** — Key architectural decisions with rationale (Decision 55: RCA-First, Decision 51: Local-First Outbox, Decision 49/54: Copilot SDK, Decision 43: SLOC Gate).
