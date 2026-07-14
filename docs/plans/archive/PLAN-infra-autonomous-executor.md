# Plan

## Intent
Transition the recommendation executor from supervised autonomy to full autonomy by progressively absorbing `/develop-executor` supervisor responsibilities into deterministic scripts and rescue agents, enabling unattended overnight batch execution on the local VM. This directly advances the North Star: every supervisor intervention that becomes a script or rescue agent is one more aspect of the system that continuously self-improves without human presence.

## Plan Type
STRATEGIC

## Branch
agent/infra-autonomous-executor

## Phase
Infra (phase-independent governance -- extends Decisions 42, 44)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/DECISIONS.md` | Modify | Add Decision 46: Rescue Agent Architecture |
| `docs/contracts/rescue-agent.md` | Create | Define the RESOLVED/CANNOT_RESOLVE/TIMEOUT contract and JSON I/O schema |
| `scripts/executor/rescue.py` | Create | RescueDispatcher and base RescueOutcome types |
| `scripts/executor/rescue_agents/` | Create | Directory for rescue agent prompt templates and dispatch logic |
| `scripts/executor/orchestrator.py` | Create | Top-level autonomous loop (Phase E -- trivial wiring) |
| `scripts/executor/postflight.py` | Modify | Wire existing recovery functions through rescue dispatch |
| `scripts/executor/step_runner.py` | Modify | Wire step failure handling through rescue dispatch |
| `scripts/executor/plan.py` | Modify | Wire planning failure handling through rescue dispatch |
| `scripts/execute_recommendation.py` | Modify | Add orchestrator-level killswitch and rescue dispatch |
| `.github/prompts/develop-executor.prompt.md` | Modify | Progressive responsibility removal as rescue agents prove out |
| `.github/instructions/executor-supervisor-workflow.instructions.md` | Modify | Document which responsibilities are scripted vs still supervised |
| `config/prompts/executor/rescue/*.prompt.md` | Create | Rescue agent prompt templates (one per failure class) |
| `tests/test_executor_rescue.py` | Create | Tests for rescue dispatcher and outcome handling |
| `tests/test_executor_orchestrator.py` | Create | Tests for autonomous loop |
| `scripts/validate.py` | Modify | Add `scripts/executor/rescue.py` and `scripts/executor/rescue_agents/` to `_EXECUTOR_BOUNDARY_PATTERNS` tuple (existing patterns already cover `config/prompts/executor/rescue/`) |

## Bundled Recommendations
None -- this plan produces NEW recommendations for each Work Area. Existing open recs are referenced below for the implementation agent's context.

## Related Recommendations (not bundled -- context for implementation agent)
The following open recs are closely related to the architectural direction of this plan. The implementation agent should review these when researching each Work Area and determine whether they should be updated, superseded, or have new recs filed:

- **rec-354** (M, open): Phase Infra-Platform: structured plan output via Bedrock JSON schema (replaces regex parsing). Foundational for rescue agent structured I/O -- rescue agents consuming CLI output need the same JSON transition.
- **rec-386** (M, open): Create `scripts/log_writer.py` -- standardized CLI for all JSONL log inserts with schema validation. Rescue agent telemetry writes should route through this once it exists.
- **rec-368** (M, open): develop-executor: add infra-stabilize mode. Superseded by this plan -- once all supervisor responsibilities are absorbed, `/develop-executor` returns to pure development mode permanently, which is what infra-stabilize becomes.
- **rec-388** (L, open): Executor end-to-end integration test. The orchestrator loop (Area E) will need integration tests; this rec's design approach is directly relevant.
- **rec-013** (M, open): Replace @step-validator with deterministic Python + LLM fallback. Same pattern as rescue agents: deterministic first, LLM escalation second.
- **rec-370** (M, open): Executor preflight: synthetic canary when rec modifies executor modules. Relevant to self-modification boundary enforcement in rescue agent context.
- **rec-383** (M, open): Per-invocation model telemetry. Required for observability of rescue agent invocations (Area A dependency).
- **rec-390** (S, open): Track supervision cost. Becomes the metric that proves rescue agents are eliminating supervisor time.
- **rec-417** (M, open): Restructure develop-executor.prompt.md around Observe-Decide-Delegate-Verify loop. Relevant to Area D -- the supervisor prompt simplification.
- **rec-423** (M, open): postflight.py: decouple merge success from local main checkout and cleanup. Relevant to Area C -- merge recovery rescue agent.
- **rec-408** (XS, open): develop-executor: make Phase 4b skip explicit. Relevant to Area D -- the RCA invocation absorption.

## Supersession Actions
When this plan is committed, the following rec should be marked superseded:
- **rec-368**: Resolution: "Superseded by PLAN-infra-autonomous-executor. The infra-stabilize concept is absorbed: once all supervisor responsibilities are handled by rescue agents and the orchestrator loop, /develop-executor returns to pure development mode permanently."

## Acceptance Criteria
- [ ] Decision 46 (Rescue Agent Architecture) recorded in `docs/DECISIONS.md`
- [ ] `docs/contracts/rescue-agent.md` defines the three-outcome contract with JSON schemas
- [ ] `RescueOutcome` dataclass exists with RESOLVED/CANNOT_RESOLVE/TIMEOUT variants
- [ ] `RescueDispatcher` exists, routing failure classes to appropriate rescue logic
- [ ] Every existing LLM recovery call (`_fix_ci_failure`, `_fix_code_review_findings`, `_agent_merge_recovery`) routes through rescue dispatch
- [ ] At least one new rescue agent exists for a currently-supervisor-only responsibility (e.g., friction capture or acceptance repair)
- [ ] `scripts/executor/rescue.py` and `scripts/executor/rescue_agents/` added to `_EXECUTOR_BOUNDARY_PATTERNS` in `validate.py`
- [ ] Orchestrator-level killswitch (`logs/.executor-killswitch`) checked at every phase boundary
- [ ] Orchestrator loop (`scripts/executor/orchestrator.py`) can run unattended: select recs, execute batch, checkpoint, repeat
- [ ] Graceful degradation: CANNOT_RESOLVE triggers draft-PR-and-move-on, never recursive rescue
- [ ] `RescueDispatcher._in_rescue` context flag raises `ExecutorError` on re-entrant calls (structural recursion prevention)
- [ ] Graduated autonomy metric defined: >= 80% RESOLVED rate across >= 5 observed runs before supervisor responsibility removal
- [ ] `/develop-executor` prompt documents which responsibilities are now scripted/rescued
- [ ] `python scripts/validate.py --scope all` exits 0

## Constraints
- Windows Git Bash (no PowerShell)
- Python 3.12+, type hints required
- Decision 44 boundary: rescue agent prompts and `scripts/executor/rescue.py` are inside the boundary -- changes go through `/plan` -> `/implement`, not the executor
- Decision 43 structural limits: each new file must stay under 500 SLOC
- Three-level graceful degradation maximum: deterministic fix -> rescue agent -> draft PR + file rec -> stop. Never four levels. Never recursive rescue. Structural enforcement: `RescueDispatcher` tracks a `_in_rescue` context flag and raises `ExecutorError` on re-entrant calls. This makes the no-recursion constraint testable.
- Rescue agent budget: each rescue invocation has a hard token/time cap. Exceeding it triggers TIMEOUT outcome, not retry
- Telemetry gate: session-telemetry duplicate rate must be below 10% before Area C (new rescue agents) begins. Areas A and B may proceed with degraded telemetry since they are contract definition and refactoring respectively.
- Graduated autonomy success metric: a rescue agent is "proven" when it achieves >= 80% RESOLVED rate across >= 5 consecutive `/develop-executor` observed runs. Only after this threshold is met should the corresponding supervisor responsibility be marked as absorbed in the prompt.
- Check `check_process_killswitch()` pattern in `copilot_wrapper.py` (already exists) -- extend, don't duplicate
- The VM runs overnight unattended. Rescue agents that cannot resolve must terminate cleanly with logs, not hang

## Context
- **Decision 42** (Three-Tier Workflow Architecture): This plan extends the three-tier model. `/develop-executor` progressively loses supervisory responsibilities as they move into scripts/rescue agents. Eventually it handles only development of the executor itself.
- **Decision 44** (Executor Self-Modification Boundary): Rescue agent prompts MUST be added to the boundary table. The executor cannot modify its own rescue logic.
- **Decision 43** (Directed Growth Governance): All new files must respect SLOC limits and tool tier taxonomy.
- **Existing recovery patterns**: `_fix_ci_failure()` (deterministic triage + LLM escalation), `_fix_code_review_findings()` (LLM-driven), `_agent_merge_recovery()` (LLM-driven). These are the proven patterns that the rescue dispatcher will generalize.
- **Graduated autonomy principle**: Each rescue agent is proven under `/develop-executor` supervisor observation before the supervisor responsibility is removed. The supervisor prompt is the integration test harness -- remove it last, not first.
- **Unattended execution model**: The local VM runs overnight. The correct efficiency metric is total throughput per human-hour, not time-per-incident. A rescue agent that takes 15 minutes unattended at 3am is infinitely more efficient than a 10-minute manual fix requiring human presence.
- **Telemetry prerequisites**: Session-telemetry duplicate rate is at 75% (critical). Telemetry fixes are in-flight and are a prerequisite for meaningful observability of rescue agent performance.
- **Known killswitch pattern**: `check_process_killswitch()` in `copilot_wrapper.py` already exists. The orchestrator-level killswitch extends this pattern to the batch loop level.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (Decisions 42, 43, 44 -- no conflicts)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Existing recovery patterns read: `postflight.py` (`_fix_ci_failure`, `_fix_code_review_findings`, `_agent_merge_recovery`), `step_runner.py` (step failure handling), `plan.py` (planning escalation)
- [ ] `copilot_wrapper.py` `check_process_killswitch()` and `copilot_call()` signatures read
- [ ] `errors.py` exception hierarchy read

## Work Areas

| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| A: Rescue Agent Contract and Types | `docs/DECISIONS.md`, `docs/contracts/rescue-agent.md`, `scripts/executor/rescue.py`, `scripts/executor/errors.py`, `tests/test_executor_rescue.py` | Foundation: defines the three-outcome contract (RESOLVED/CANNOT_RESOLVE/TIMEOUT), JSON I/O schemas, `RescueOutcome` dataclass, and `RescueDispatcher` class. Every subsequent area depends on this. The contract must be schema-validated at runtime -- malformed rescue agent output triggers CANNOT_RESOLVE, not a crash. | M |
| B: Wire Existing Recovery Through Rescue Dispatch | `scripts/executor/postflight.py`, `scripts/executor/step_runner.py`, `scripts/executor/plan.py`, `scripts/execute_recommendation.py`, `tests/test_executor_postflight.py`, `tests/test_executor_step_runner.py`, `tests/test_executor_plan.py` | Refactor: `_fix_ci_failure()`, `_fix_code_review_findings()`, `_agent_merge_recovery()`, and planning model escalation are already LLM-dispatched recovery. Wrap each in the rescue dispatcher so they return `RescueOutcome` instead of ad-hoc booleans. This is a pure refactor -- no new capability, but establishes the pattern that all future rescue agents follow. Proves the contract under the existing `/develop-executor` test harness before adding new agents. | L |
| C1: Rescue Agent -- Acceptance Command Repair | `scripts/executor/rescue_agents/acceptance_repair.py`, `config/prompts/executor/rescue/acceptance-repair.prompt.md`, `scripts/executor/rescue.py`, `scripts/validate.py`, `tests/test_executor_rescue.py` | New capability: rescue agent for the highest-frequency supervisor intervention -- acceptance command is wrong but implementation code is correct. The agent reads the acceptance command, the rec context, the implementation diff, and proposes a corrected acceptance command. Returns RESOLVED with the new command, or CANNOT_RESOLVE with diagnosis. Prompt added to Decision 44 boundary. First rescue agent to be proven under graduated autonomy (>= 80% RESOLVED across >= 5 observed runs). | M |
| C2: Rescue Agent -- Failure Diagnosis and Classification | `scripts/executor/rescue_agents/failure_diagnosis.py`, `config/prompts/executor/rescue/failure-diagnosis.prompt.md`, `tests/test_executor_rescue.py` | New capability: rescue agent that classifies executor failures into actionable categories (acceptance mismatch, scope creep, test failure, CLI timeout, environment issue). Currently done manually by the supervisor reading transcripts and telemetry. The agent receives structured failure context (failure summary JSON, transcript excerpt, diff stat) and returns a classification with recommended action. CANNOT_RESOLVE when the failure is ambiguous or multi-causal. | M |
| C3: Rescue Agent -- Friction Capture | `scripts/executor/rescue_agents/friction_capture.py`, `config/prompts/executor/rescue/friction-capture.prompt.md`, `tests/test_executor_rescue.py` | New capability: rescue agent that analyzes transcripts after each rec (success or failure) and drafts friction recs. Currently the supervisor's Friction Capture procedure (Phase 4 in develop-executor). The agent reads plan and implementation transcripts, step telemetry, and diff stats, then produces structured draft recs in the recommendations JSONL schema. CANNOT_RESOLVE when transcripts are empty or unparseable. Output feeds into RCA invocation (Area D). | M |
| D: Absorb Session Lifecycle | `scripts/executor/orchestrator.py` (partial), `scripts/execute_recommendation.py`, `.github/prompts/develop-executor.prompt.md`, `.github/instructions/executor-supervisor-workflow.instructions.md` | Absorption: move between-rec checkpoints, RCA invocation (currently `@rca-analyst`), and session review from the supervisor prompt into deterministic scripts. Between-rec checkpoints are trivial (`git add` + `git commit`). RCA invocation becomes a conditional rescue dispatch (if friction detected, invoke RCA agent). Session review becomes a template-driven summary from run artifacts. After this area, `/develop-executor` only handles: rec selection strategy, ad-hoc debugging, and development of the executor itself. | L |
| E: Autonomous Orchestrator Loop | `scripts/executor/orchestrator.py`, `tests/test_executor_orchestrator.py`, `scripts/execute_recommendation.py` | Wiring: the trivially simple `while` loop. Select recs (existing CLI), execute batch (existing function), rescue on failure (rescue dispatcher), checkpoint (deterministic), repeat until killswitch, budget exhaustion, or empty queue. The killswitch is a file sentinel (`logs/.executor-killswitch`) checked at every phase boundary, extending `check_process_killswitch()` pattern. Budget tracking uses existing `print_session_status()` with a configurable ceiling. This should be ~100 lines of Python. If it needs more, logic belongs in another area. | S |
| F: CLI-to-JSON Agent Output Migration | `scripts/copilot_wrapper.py`, `scripts/executor/plan.py`, `scripts/executor/step_runner.py`, `scripts/executor/postflight.py` | Foundation (deferred): audit all `copilot_call()` invocations that currently parse LLM output via regex, identify which can be migrated to structured JSON output (Bedrock schema or prompt-enforced JSON), and produce recs for each migration. This is a scoping area, not an implementation area -- the deep regex refactoring is subsequent work. Recs produced here should be low priority. References rec-354 (structured plan output). | M |

### Work Area Dependency Graph

```
A (Contract) --> B (Wire Existing) --> C1 (Acceptance Repair) --> C2 (Failure Diagnosis) --> C3 (Friction Capture)
                                   \-> D (Absorb Lifecycle) --> E (Orchestrator Loop)
A (Contract) --> F (CLI-to-JSON Audit) [independent, can run in parallel with B-E]

Note: C1/C2/C3 are ordered by priority but each is independently shippable.
C1 must be proven (graduated autonomy metric) before C2 begins.
D depends on at least C1 and C2 being proven.
Telemetry gate: session-telemetry duplicate rate < 10% before C1 begins.
```

### Work Area Quality Notes

- **Area A** is the keystone. If the contract is wrong, everything built on it is wrong. The implementation agent should study the existing `CopilotResponseError` and `StepOutcome` patterns to ensure `RescueOutcome` is consistent with the existing type system.
- **Area B** is a pure refactor with no new capability. It must not change any observable behavior. Every existing test must pass without modification (tests may need new assertions for rescue dispatch, but existing assertions must not break).
- **Areas C1/C2/C3** are independent rescue agents, each proven under graduated autonomy (>= 80% RESOLVED across >= 5 observed `/develop-executor` runs) before the corresponding supervisor responsibility is removed. C1 (acceptance repair) is highest priority because it's the most frequent supervisor intervention. C2 (failure diagnosis) enables C3 (friction capture) to produce better-categorized recs. Each area produces independently testable, independently deployable recs.
- **Area D** depends on at least C1 and C2 proving that rescue dispatch works for judgment tasks, not just mechanical recovery. If C1/C2 agents frequently return CANNOT_RESOLVE, Area D's RCA absorption should be deferred until the root cause is addressed.
- **Area E** is intentionally last and intentionally trivial. If it's not trivial, Areas A-D haven't done their job.
- **Area F** is explicitly low priority and produces recs only, not implementations. It can be time-boxed or deferred without affecting the other areas.
