# Intent: Autonomous Recommendation Executor

This document defines the intent, vision, and design boundaries for the autonomous recommendation executor and its supporting modules. It exists so that LLM agents working on this system can compare the implementation against the intended design at any point during development.

**Supersedes:** The original version of this document (March 2026). All sections are current as of April 2026.

**Companion document:** `docs/INTENT-telemetry-system.md` defines the telemetry schema, storage architecture, and process event framework that the executor produces data for.

---

## North Star

Build an autonomous, self-improving feedback loop for the repository workflow. Recommendations are scoped, planned, and implemented by agents without human intervention. The system continuously improves both the codebase it operates on and its own workflow infrastructure (prompts, scripts, agents) based on structured, queryable telemetry data.

The telemetry system is a prerequisite for self-improvement, not an afterthought. Without structured observability into every phase of execution -- planning, critique, implementation, validation, merge -- the "self-improving" claim is aspirational. The executor must produce telemetry as a first-class output alongside code changes.

---

## What This Replaces

The executor is evolving toward a **fully autonomous orchestrator with specialized recovery agents**. It replaces both:

1. **The interactive `/plan` + `/implement` workflow** -- where a human starts each session, maintains chat context, and approves transitions in VS Code Copilot Chat.
2. **The `/develop-executor` supervisor prompt** -- where a human monitors executor runs, diagnoses failures, captures friction, and files recommendations. This is an interim step that will be removed once the executor handles its own failure diagnosis and recovery.

The `/plan` and `/implement` prompts remain available for complex or high-risk work that exceeds the executor's autonomous capability. The executor handles the autonomous low-risk pipeline.

### How LLM Calls Work

The executor makes surgical calls to LLM agents for all non-deterministic work (planning, critique, implementation, code review, recovery). Currently this is done via `copilot -p` CLI subprocess calls with prompt file injection -- externalized prompt templates in `config/agent/executor/prompts/` are injected as context. This is functionally equivalent to calling specialized agents: each prompt template defines a role, receives structured context, and returns structured output.

The roadmap includes a migration to the Copilot SDK, at which point these become true bespoke agent calls. The prompt templates are version-controlled code artifacts that evolve based on execution outcomes -- the prompts themselves are part of the self-improvement loop.

| Interactive (VS Code Chat) | Autonomous (Script + LLM) |
|---------------------------|--------------------------|
| `plan.prompt.md` Step 7 (write plan) | Planning agent via `config/agent/executor/prompts/planning.prompt.md` |
| `@plan-critique` agent | Critique agent via `config/agent/executor/prompts/critique.prompt.md` |
| Plan revision after critique | Refinement agent via `config/agent/executor/prompts/refine.prompt.md` |
| `implement.prompt.md` Step 6 (execute steps) | Implementation agent via `config/agent/executor/prompts/implement-step.prompt.md` |
| `@code-review` agent | Code review agent via `config/agent/executor/prompts/code-review.prompt.md` |
| Human failure diagnosis | Recovery agents (merge recovery, CI triage, failure diagnosis) |

---

## Architecture

### Separation of Concerns

The system follows one core principle: **scripts are the nervous system (deterministic reflexes), LLM calls are the prefrontal cortex (judgment and generation).**

| Deterministic (Script) | Non-Deterministic (LLM Agent) |
|------------------------|-------------------------------|
| Load recommendation from JSONL | Generate implementation plan from recommendation |
| Check eligibility (risk, automatable) | Critique the plan for quality |
| Create git branch | Refine plan based on critique |
| Order step execution | Implement each step (write/modify code) |
| Run validation after each step | Review code for quality issues |
| Run acceptance commands | Fix code review findings |
| Commit, push, create PR, merge | Diagnose CI failures |
| Capture and persist telemetry | Recover from merge failures |
| Loop to next recommendation | Classify risk level |
| Enforce budget and safety limits | Diagnose and escalate plan failures |

The number of LLM agent roles is not fixed. The executor is free to optimize itself -- adding, removing, or restructuring agent roles based on what produces the best outcomes. The intent is that the script handles all deterministic orchestration while agents handle all judgment calls, not that there are a specific number of each.

### Module Responsibilities (as of April 2026)

| Module | Role |
|--------|------|
| `scripts/execute_recommendation.py` | Orchestrator entry point. Thin exception-catching wrapper around `_execute_recommendation_inner()` which contains all orchestration logic: checkpoint management, eligibility checks, phase sequencing, status writeback. |
| `scripts/executor/plan.py` | Plan generation, critique, and refinement loop. Model escalation on failure. Critique cycling detection. |
| `scripts/executor/step_runner.py` | Step implementation via LLM, acceptance command execution, ruff auto-fix, scope enforcement, commit with hook retry. |
| `scripts/executor/postflight.py` | Code review gate with fix-and-recheck loop, validation, CI wait with triage and fix, merge with agent recovery, cleanup. |
| `scripts/executor/ci_triage.py` | Deterministic CI failure classification (lint, import, type, test, unknown) with auto-fix for lint/import categories. |
| `scripts/executor/jsonl_store.py` | Recommendation CRUD with atomic writes, status transitions, acceptance linting, dependency resolution. |
| `scripts/executor/errors.py` | Structured exception types and enums (`StepOutcome`, `CIFailureCategory`). |
| `scripts/copilot_wrapper.py` | Subprocess abstraction for LLM calls. Process guards (killswitch, recursion), OTel capture, transcript management, session reuse. Every LLM interaction goes through this module. |
| `scripts/execution_state.py` | Checkpoint save/load/clear for crash recovery and session resumption. |
| `scripts/classify_risk.py` | Single-purpose LLM call to classify a recommendation as low/medium/high risk. |
| `config/agent/executor/prompts/*.prompt.md` | Externalized prompt templates with `{placeholder}` substitution. Each defines one agent role. |

### Execution Flow

```
                    +---------------------------------+
                    |  Recommendation JSONL Entry     |
                    |  (from code-review agent,       |
                    |   scheduled agent, or human)    |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  PREFLIGHT                      |
                    |  - Load rec by ID               |
                    |  - Check eligibility            |
                    |  - Check acceptance feasibility  |
                    |  - Resume checkpoint or create   |
                    |    agent/{rec-id} branch         |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  PLAN GENERATION                |
                    |  - LLM call: planning agent     |
                    |  - Parse structured steps       |
                    |  - Model escalation on failure  |
                    |  - Save plan to JSONL           |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  CRITIQUE LOOP (max N)          |
                    |  - LLM call: critique agent     |
                    |  - If APPROVED: proceed         |
                    |  - If NEEDS_REVISION:           |
                    |    LLM call: refinement agent   |
                    |    Loop                         |
                    |  - Cycling detection + auto-    |
                    |    approve safety valve         |
                    |  - Escalation agent if >3       |
                    |    revisions (future)           |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  IMPLEMENTATION LOOP            |
                    |  For each step:                 |
                    |  - Gather file context           |
                    |  - LLM call: implementation     |
                    |    agent                        |
                    |  - Ruff auto-fix                |
                    |  - Run validate.py              |
                    |  - Run acceptance command       |
                    |  - Git commit (with hook retry) |
                    |  - Save checkpoint              |
                    |  - Capture step telemetry       |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  POSTFLIGHT                     |
                    |  - Scope drift check            |
                    |  - Code review gate             |
                    |    (fix + recheck loop)         |
                    |  - Validation (with fallbacks)  |
                    |  - Acceptance recheck            |
                    |  - Git push, create PR          |
                    |  - CI wait + triage + fix       |
                    |  - Merge (with agent recovery)  |
                    |  - Cleanup                      |
                    +---------------+-----------------+
                                    |
                                    v
                    +---------------------------------+
                    |  STATUS WRITEBACK               |
                    |  - Update rec: closed/failed    |
                    |  - Write session telemetry      |
                    |  - Loop to next rec             |
                    +---------------------------------+
```

---

## Recovery Mechanisms

The executor has layered recovery for every failure mode. These are not retries in the naive sense -- each layer uses a different strategy.

### Script-Level Recovery (Autonomous)

| Mechanism | Trigger | Strategy |
|-----------|---------|----------|
| **Planning model escalation** | 2 consecutive failures at current tier | Promote: gpt-5-mini -> gpt-5.4 -> claude-opus-4.6 |
| **Implementation model escalation** | Failure at current tier | Promote to higher-capability model |
| **Deterministic CI triage** | CI failure detected | Classify (lint/import/type/test/unknown), run ruff auto-fix |
| **LLM CI fix** | Deterministic fix insufficient | LLM agent with CI error context |
| **Code review fix** | CRITICAL/HIGH findings | LLM agent with findings context, fix-and-recheck loop |
| **Agent merge recovery** | `merge_pr()` fails | Full LLM agent to diagnose and resolve (conflicts, rebase, force) |
| **Postmortem rec creation** | CI or merge exhausted after all retries | Append new `open` rec for investigation |
| **Step file revert** | Step implementation fails | `git checkout -- <file>`, `Path.unlink()` for creates |
| **Compound step rollback** | Step fails in compound mode | `git reset HEAD~N` to undo commits for that rec |
| **Commit hook retry** | Pre-commit hooks modify files | Re-add and retry (3x), final attempt `--no-verify` |
| **Critique cycling detection** | Same violation in 2+ consecutive iterations | Auto-approve to break the loop |
| **Clean slate** | Stale state from prior run | Delete branches, close PRs, clear checkpoint, reset status |

### Supervisor-Level Recovery (Being Automated)

These events are currently handled by the human supervisor via `develop-executor.prompt.md`. The intent is for each to be automated as a callable recovery agent:

| Event | Current | Target |
|-------|---------|--------|
| Failure diagnosis and classification | Human reads transcripts | Automated transcript parser + classifier agent |
| Acceptance field correction | Human edits JSONL | Acceptance-rewrite agent |
| Filing process improvement recs | Human drafts after RCA | Cloud analysis agent detects patterns, auto-files |
| RCA analysis | Human invokes `@rca-analyst` | Callable agent invoked by script |
| Session failure budget enforcement | Human tracks ratio | Counter in executor state, abort batch when exceeded |
| Cross-run pattern analysis | Human compares across runs | Cloud analysis agent over telemetry tables |

---

## Recommendation Lifecycle

### State Machine (Work in Progress)

The recommendation lifecycle is being formalized as a state machine. The current implementation supports the core transitions; edge cases (blocked_on, unblocking depth) are under development.

```
                 +----------------------------------------------+
                 |                                              |
                 v                                              |
  +----------+     +-----------+     +--------+     +-----------+
  |  open    |---->| eligible  |---->|executing|---->|  merged   |
  |          |     |           |     |         |     | (success) |
  +----------+     +-----------+     +----+----+     +-----------+
                                          |
                          +---------------+----------------+
                          |               |                |
                          v               v                v
                   +----------+   +-------------+   +---------------+
                   |  failed  |   | already_    |   | no_changes_   |
                   |          |   | implemented |   | needed        |
                   +----+-----+   +-------------+   +---------------+
                        |
                        v
                 +-------------+
                 | blocked_on: |
                 | [rec-X,     |----> (unblocking recs execute
                 |  rec-Y]     |      first, then retry)
                 +------+------+
                        |
                        v
                  back to eligible
                  (max 2 unblock levels)
```

**Implemented transitions:**
- `open -> eligible`: Risk classified as low + marked automatable
- `eligible -> executing`: Executor picks it up
- `executing -> merged`: All steps pass, PR merged
- `executing -> failed`: Any step fails validation
- `executing -> already_implemented`: Acceptance passes on main without changes
- `executing -> no_changes_needed`: LLM determines no code changes required
- `executing -> acceptance_challenged`: Plan determines acceptance criteria are wrong
- `failed -> ci_failed_3_times`: CI fix exhausted after max retries

**Planned transitions:**
- `failed -> blocked_on`: Executor creates unblocking recs
- `blocked_on -> eligible`: All blocking recs reach `merged`
- `failed (2x with different approaches) -> escalated`: Circuit breaker, requires human

---

## Self-Modification Boundary

The executor **cannot modify its own machinery** (Decision 44). This includes:

- `scripts/execute_recommendation.py`
- `scripts/executor/*.py`
- `scripts/copilot_wrapper.py`
- `config/agent/executor/prompts/*.prompt.md`
- `.github/prompts/develop-executor.prompt.md`
- `.github/instructions/executor-*.instructions.md`
- `tests/test_execute*`, `tests/test_executor_*`, `tests/test_copilot_wrapper.py`

The executor **can**, however, generate recommendations targeting these files with `automatable: false`. These recommendations are actioned through the interactive `/plan` + `/implement` workflow, where a human reviews and approves the changes. This preserves the self-improvement loop while preventing the executor from breaking its own control plane.

Enforcement: `validate_executor_boundary()` in `scripts/validate.py` checks `_EXECUTOR_BOUNDARY_PATTERNS` and rejects any executor run that attempts to modify boundary files.

---

## Telemetry

All telemetry requirements, schemas, storage architecture, and the process event framework are defined in `docs/INTENT-telemetry-system.md`.

The executor is a primary telemetry producer. It emits structured events at every phase of execution through a unified write path. Telemetry is stored as local JSONL write-ahead logs that are compacted to Iceberg tables in Athena for analytical queries.

---

## Self-Improvement Loop

The self-improvement loop is closed by scheduled agents that run on daily cron via Lambda + EventBridge. These agents query the telemetry tables and codebase to detect issues and opportunities:

- **Code quality agents** (doc-freshness, orphan-code, code-smell, prompt-quality) review the codebase for staleness, dead code, and quality issues.
- **Transcript review agent** analyzes executor transcripts for patterns of LLM confusion or prompt inefficiency.
- **Recommendation curator agent** clusters open recommendations, detects workaround patterns, and produces a prioritized execution queue.
- **Cloud analysis agent** (planned) performs statistical anomaly detection on telemetry data -- flagging sessions that deviate from rolling baselines in cost, duration, or failure rate.

These agents produce findings. The findings processor auto-compares against existing recommendations and files new ones when novel issues are detected. The executor then picks up and implements those recommendations, completing the loop:

```
Executor runs -> Telemetry captured -> Scheduled agents analyze ->
Findings produced -> New recs filed -> Executor implements recs ->
Codebase/workflow improves -> Next executor run is better
```

The system improves two things through this loop:

1. **The codebase** -- trading system code, infrastructure, tests, documentation
2. **Its own workflow** -- prompts, agents, telemetry, review processes (subject to the self-modification boundary above)

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Subprocess CLI calls, not API (current) | Decision 31: The `copilot -p` command runs in the parent shell context with OTel telemetry capture. Migration to Copilot SDK is planned (see ROADMAP). |
| Externalized prompts in `config/agent/executor/prompts/` | Prompts are code. Version-controlled, diffable, iterable independently of script logic. Changes show up cleanly in git history. |
| Layered recovery, not fail-fast | Model escalation, CI fix retries, merge recovery, code review fix loops, commit hook retries -- each with bounded attempt counts and circuit breakers. |
| Auto-merge for low-risk | Human review is a temporary gate. Once reliability is proven, low-risk recs flow through without human intervention. |
| Local JSONL as write-ahead log, Iceberg as analytical store | JSONL provides offline resilience and fast append. Iceberg (via Athena) provides SQL-queryable analytics. OpsWriter handles the staging + compaction path. See Decision 50/51. |
| Conservative eligibility defaults | `risk: unclassified` and `automatable: false` mean new recs are never automatically executed until explicitly classified and marked. |
| Per-step telemetry granularity | More granular data can always be rolled up; less granular cannot be disaggregated. Sessions, phases, steps, and individual model calls are all captured. |
| Self-modification boundary | The executor cannot modify its own machinery (Decision 44). It can file `automatable: false` recs that go through the interactive workflow. |

---

## Recommendation Sources

Recommendations enter the system from three sources:

1. **Scheduled cron agents:** Periodically review the codebase and telemetry, writing findings that the findings processor converts to recommendations. These start as `risk: unclassified, automatable: false`.
2. **Human:** Manually adds recommendations for work they want the system to handle.
3. **Executor itself:** Creates postmortem recommendations when execution fails (CI exhausted, merge exhausted). These document the failure for later investigation.

All sources feed the same pipeline. The executor does not distinguish between them.

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/execute_recommendation.py` | Main orchestrator |
| `scripts/executor/plan.py` | Plan generation, critique, refinement |
| `scripts/executor/step_runner.py` | Step implementation, acceptance, formatting |
| `scripts/executor/postflight.py` | CI wait, merge, cleanup, code review gate |
| `scripts/executor/ci_triage.py` | Deterministic CI failure classification |
| `scripts/executor/jsonl_store.py` | Recommendation CRUD, atomic writes |
| `scripts/executor/errors.py` | Structured exception types and enums |
| `scripts/copilot_wrapper.py` | CLI subprocess abstraction with OTel capture |
| `scripts/execution_state.py` | Checkpoint save/load/clear |
| `scripts/classify_risk.py` | LLM-based risk classification |
| `config/agent/executor/prompts/*.prompt.md` | Externalized prompt templates (one per agent role) |
| `logs/.recommendations-log.jsonl` | Recommendation entries with status, risk, automatable |
| `logs/.execution-plans.jsonl` | Plan revisions with step details |
| `logs/transcripts/` | Full prompt+response transcripts per LLM call |
| `docs/INTENT-telemetry-system.md` | Telemetry schema and storage architecture |
| `docs/INTENT-recommendation-executor.md` | This document |
