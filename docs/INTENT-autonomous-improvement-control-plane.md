# Intent: Autonomous Improvement Control Plane

This document captures the target architecture for the repository's autonomous recursive self-improvement loop. It synthesises the workflow architecture review, telemetry gap analysis, programmatic verification strategy, executor improvement roadmap, RCA-first operating model, Antigravity workflow migration, and recommendation governance model.

**Companion documents:**
- `docs/INTENT-telemetry-system.md` defines the telemetry storage model and event taxonomy.
- `docs/INTENT-verification-system.md` defines deterministic verifier harnesses and causal-chain checks.
- `docs/INTENT-recommendation-executor.md` defines executor lifecycle and boundaries.
- `docs/contracts/instruction-architecture.md` defines the instruction layers for Gemini, Antigravity, legacy VS Code, and executor prompts.

---

## Problem Statement

The repository has the building blocks of a recursive self-improvement system, but they are not yet aligned into a fully closed control loop. The current architecture has strong planning, decision logging, recommendation tracking, executor orchestration, scheduled agent scaffolding and manifests, and telemetry schemas. However, the loop is not fully autonomous because the system still relies on human interpretation for the most important transitions:

1. Proving telemetry and ops data actually flow end-to-end.
2. Converting process events and verifier failures into durable recommendations.
3. Prioritising improvement work without losing ordering and dependencies in a flat backlog.
4. Handling unrecoverable executor failures through structured RCA rather than supervisor workarounds.
5. Migrating interactive workflows from VS Code prompts to Antigravity workflows without copying legacy subagent patterns.

The result is a highly instrumented, semi-autonomous improvement loop. The target is a closed control plane where evidence, verification, RCA, recommendation creation, prioritisation, execution, and outcome measurement form one coherent cycle.

---

## North Star

Build an autonomous, recursive improvement loop where the system can:

1. Execute planned work.
2. Observe its own execution through structured telemetry.
3. Verify that real system outcomes occurred, not merely that code or tests exist.
4. Detect failures, process gaps, verifier failures, and workflow drift.
5. Package evidence into RCA-ready failure records.
6. File durable recommendations through the operational data portal.
7. Prioritise recommendations while preserving dependencies and architectural intent.
8. Execute safe improvements through the autonomous executor or interactive workflows.
9. Measure whether each improvement reduced the failure mode or process event that caused it.

A loop is only considered closed when the system can demonstrate the final step: a fix reduced or eliminated the event pattern that motivated it.

---

## Current Maturity Assessment

The workflow architecture is unusually mature for a sole-developer repository. The system ranks in the top tier of solo-developer engineering systems because it has branch-specific planning, explicit decisions, structured recommendations, executor orchestration, scheduled agents, telemetry schemas, and a documented RCA-first philosophy.

However, it is not yet a fully autonomous engineering platform. Its design is stronger than its operational closure. The missing pieces are telemetry trust, programmatic verification, automated process-event analysis, structured RCA writeback, and ordered recommendation governance.

| Area | Current State | Gap |
|------|---------------|-----|
| Workflow design | Strong two-chat plan/implement model and branch-specific plans | Migration to Antigravity creates duplicate workflow sources |
| Observability | 7-table telemetry star schema and process event taxonomy | Causal-chain proof and analysis automation incomplete |
| Verification | V1/V2/V3 concept documented | Deterministic verifier harness and hard gates still being implemented |
| Executor autonomy | Low-risk executor path exists | Failure handling still depends on supervisor diagnosis in some cases |
| RCA model | Decision 55 is architecturally sound | Failure packet generation and portal-based RCA filing need automation |
| Recommendations | Rich backlog and schema | Large flat backlog can lose order, dependencies, and rationale |
| Interactive workflows | `.agents` split is directionally right | Legacy VS Code and Antigravity workflow sources overlap |

---

## Target Control Loop

The target control loop is:

```text
Plan or recommendation
  -> execution
  -> telemetry session/phase/step records
  -> verifier results
  -> process events
  -> failure packet or anomaly cluster
  -> RCA analysis
  -> recommendation filed through ops_data_portal.py
  -> priority queue with dependencies preserved
  -> executor or interactive implementation
  -> verification
  -> telemetry delta proving whether the fix helped
```

Each transition should have one owning mechanism:

| Transition | Owning Mechanism |
|------------|------------------|
| Work definition -> execution | PLAN files or recommendation records |
| Execution -> evidence | telemetry API and process events |
| Code landed -> system works | verifier harness |
| Failure -> diagnosis input | failure packet builder |
| Diagnosis -> durable work | RCA skill plus ops data portal |
| Backlog -> ordered execution | priority queue and dependency graph |
| Fix -> measured improvement | telemetry trend analysis |

---

## Architectural Principles

1. **Scripts enforce; agents reason.** Deterministic checks, state transitions, verifier gates, and write paths belong in scripts. Agents reason about plans, architecture, RCA, and trade-offs.
2. **Workflows orchestrate; skills encode methodology.** Antigravity workflows should be thin step sequences. Deep rules belong in `.agents/skills/` or scripts.
3. **Verification is programmatic.** LLM self-evaluation is advisory only. Registered verifiers and exit codes decide whether integration work passes.
4. **Operational writes go through portals.** Recommendations and decisions must be created or updated through `scripts/ops_data_portal.py`, not direct JSONL edits.
5. **RCA stops and files.** Unrecoverable executor failures produce evidence and recommendations. They do not trigger LLM rescue, prompt hotfixes, or workaround retries.
6. **Telemetry replaces retrospective reconstruction.** Step validation, scope drift, friction capture, and retrospectives should become telemetry events, verifier outputs, and state-machine transitions rather than migrated LLM subagents.
7. **`.agents` is the canonical interactive layer.** Legacy VS Code prompts are compatibility artefacts. Duplicate Antigravity workflow sources should be shimmed or removed.
8. **Recommendations are execution units, not architecture memory.** Architecture and sequencing live in intent documents, roadmap waves, and strategic plans. Recommendations execute scoped work derived from those artefacts.
9. **Autonomy increases only after trust increases.** Do not scale unattended executor batches before telemetry, verifiers, RCA packets, and killswitches are reliable.
10. **Every improvement should be measurable.** A process improvement is not complete until the system can observe whether the original failure pattern decreased.
11. **The control plane serves the product.** Track the product/platform work ratio over a trailing 30-day window. If platform or control-plane work exceeds an agreed threshold, strategic review should surface a warning. The control plane exists to accelerate the trading system, not become the product.

---

## Workstream 1: Telemetry Trust

### Intent
Make telemetry trustworthy enough to drive autonomous analysis and recommendation generation.

### Current Gap
Telemetry schemas and write helpers exist, but observed failures showed tables could remain empty while implementation sessions claimed success. This means the system cannot yet rely on telemetry as a sensor for self-improvement.

### Target State
- Telemetry sessions, phases, steps, model calls, process events, transcripts, and scheduled agent invocations are populated by real workflows.
- Local outbox, S3 staging, Iceberg compaction, and Athena queryability are proven by causal-chain verifiers.
- Data quality checks run as scheduled health signals.
- Telemetry health is visible in preflight and should become a first-class strategic review input.

### Priority Actions
1. Implement causal-chain telemetry verification from PRODUCE through ASSERT.
2. Ensure all telemetry tables have recent, queryable rows or clear documented reasons for no rows.
3. Emit process events for verification pass/fail, RCA filed, workflow drift, and skipped gates.
4. Add scheduled health checks that file recommendations when telemetry regressions appear.

---

## Workstream 2: Programmatic Verification

### Intent
Move verification from LLM interpretation to deterministic harness execution.

### Current Gap
Verification tiers exist, but plans and agents can still treat diagnostic output, structural checks, or passing unit tests as proof of system behavior.

### Target State
- `scripts/verifiers/` provides a filesystem registry of deterministic verifiers.
- `scripts/verifiers/harness.py` runs verifiers by name, scope, plan, or tier.
- V3 work uses causal-chain or query verifiers where available.
- Executor postflight blocks merges when required verifiers fail.
- SKIPPED verifier results are allowed only for missing credentials or unavailable external environments. They must emit warning process events and be followed by scheduled health checks that catch regressions within 24 hours.

### Priority Actions
1. Build the verifier registry and harness.
2. Add `outbox_health`, `schema_integrity`, `athena_views`, `telemetry_pipeline`, and `ops_pipeline` verifiers.
3. Wire verifier coverage into planning and critique.
4. Wire verifier execution into implementation and executor postflight.
5. Add a same-PR guard so code and the verifier covering that code cannot be weakened together except for initial verifier creation.

---

## Workstream 3: Executor Evolution

### Intent
Improve the executor in an ordered way that increases reliability before increasing autonomy.

### Current Gap
The executor can plan, implement, validate, and merge low-risk recommendations, but failure diagnosis and cross-run learning still depend on supervisor behavior. Some legacy supervisor flows still encourage retries, hotfixes, or workaround routing.

### Target State
- The executor emits structured failure packets for unrecoverable failures.
- RCA agents diagnose from failure packets and file permanent-fix recommendations through the portal.
- `/develop-executor` is RCA-only and no longer repairs, hotfixes, or works around failures.
- Autonomy is governed by maturity gates, verification coverage, dependency safety, and failure budgets.
- Batch execution is limited to recommendations that meet explicit autonomy and verification criteria.

### Ordered Improvement Roadmap
1. Stabilise telemetry and verification before expanding autonomy.
2. Remove workaround authority from `/develop-executor`.
3. Add deterministic failure packet generation.
4. Automate RCA invocation and portal-based recommendation filing.
5. Add autonomy maturity gates for recommendations.
6. Add batch killswitches and dependency deadlock detection.
7. Add prompt and workflow performance telemetry only after telemetry is reliable.

### Autonomy Maturity Gates

Every recommendation should be assigned an autonomy maturity level before autonomous execution. The gate controls how much authority the executor has.

| Gate | Meaning | Typical Route |
|------|---------|---------------|
| A0 | Human-only | Human design or manual implementation |
| A1 | Agent can plan, human implements | `/plan` produces a plan; human or supervised agent executes |
| A2 | Agent can implement, human reviews | Interactive `/implement`, PR remains human-reviewed |
| A3 | Executor can run, but PR remains open | Autonomous implementation with manual merge |
| A4 | Executor can run and merge after CI and verifiers pass | Single-rec autonomous execution |
| A5 | Batch executor can run unattended | Batch mode with dependency, verifier, and failure-budget gates |

Unattended batch execution should require A5, passing verifier coverage checks, no unresolved dependencies, and an active killswitch.

### Failure Packet Schema

Unrecoverable executor failures should produce a structured failure packet before RCA is invoked. The packet is the bridge between deterministic execution and LLM RCA.

| Field | Purpose |
|-------|---------|
| `rec_id` | Recommendation being executed |
| `branch` | Executor branch at failure time |
| `phase` | Failed phase: preflight, planning, critique, implementation, acceptance, validation, code_review, ci, merge, cleanup |
| `step_number` | Plan step number if applicable |
| `failure_category` | Deterministic initial classification |
| `exit_code` | Failed command or process exit code |
| `command` | Command that failed, if any |
| `acceptance_command` | Recommendation acceptance command when relevant |
| `verification_tier` | V1, V2, or V3 |
| `verifier_results` | Registered verifier outputs when available |
| `changed_files` | Files changed by the failed run |
| `scope_drift_files` | Changed files not present in plan/recommendation scope |
| `transcript_paths` | Relevant model transcript paths |
| `recent_process_events` | Recent process events for context |
| `retry_count` | Number of retries already attempted |
| `model_used` | Model/provider active at failure point |
| `suggested_rca_scope` | Initial scope hint: prompt, script, verifier, environment, rec metadata, external service |

RCA agents diagnose from this packet and file permanent-fix recommendations. They do not repair inline.

### Roles to Remove from `/develop-executor`
1. Workaround operator (`--skip-critique`, prompt hotfixes, ad hoc retries).
2. Direct recommendation log editor.
3. Manual transcript scanner.
4. Checkpoint clerk.
5. Recommendation selector.
6. Cross-run analyst.

Those roles should move to deterministic scripts, telemetry analysis, priority queue logic, or RCA packet generation.

---

## Workstream 4: Interactive Workflow Migration

### Intent
Use the migration from VS Code to Antigravity as an architectural improvement, not a one-for-one prompt port.

### Current Gap
The repository currently has legacy `.github` prompts and agents, `.agents` workflows and skills, and `.antigravity` workflows. This creates source-of-truth ambiguity and risk of workflow drift.

### Target State
- `.agents/workflows/` and `.agents/skills/` are canonical for interactive workflows.
- `.github/prompts/` and `.github/agents/` are legacy VS Code compatibility only.
- `.antigravity/workflows/` is either removed or reduced to shims that delegate to `.agents`.
- Workflows are thin orchestration files.
- Skills have required context and contain methodology, not project routing or operational writes.
- Operational writes use portals.
- Verification and code review are explicit workflow gates.

### What Not To Migrate As LLM Agents
- `step-validator` should become execution state and verifier telemetry.
- `scope-guard` should become a deterministic diff-vs-plan check.
- `retro-lite` should become process events.
- `retrospective` should become scheduled telemetry analysis and decision/recommendation governance.

---

## Workstream 5: State Machine and Process Events

### Intent
Replace chat-based supervision with explicit execution states and process events.

### Current Gap
Some workflow guarantees are still phrased as agent instructions: validate each step, check scope drift, capture friction, run retrospective. These are useful concepts but weak control mechanisms.

### Target State
- Every workflow run has explicit session, phase, and step states.
- Every planned step records start, completion, failure, retry count, changed files, acceptance result, verifier result, and scope drift.
- Every exit path clears or persists state deterministically.
- Session summaries are generated from telemetry, not reconstructed from chat history.
- Process events use canonical categories and drive trend analysis.

### Priority Actions
1. Define the workflow state machine for plan, implement, executor, verification, RCA, and close.
2. Ensure every state transition emits telemetry.
3. Add deterministic scope-drift checks against plan scope.
4. Replace manual friction capture with process-event emission.
5. Generate session close summaries from telemetry records.

### Prompt and Workflow Performance Telemetry

Prompt and workflow changes should be measured rather than judged by anecdote. Once telemetry is reliable, correlate `prompt_hash`, model, provider, task type, retry count, critique revision count, verifier failure rate, post-merge defect rate, duration, and cost. A prompt or workflow change is not considered a proven improvement until telemetry shows better outcomes for comparable work.

---

## Workstream 6: Recommendation Governance

### Intent
Prevent major architecture work from being flattened into an unordered backlog.

### Current Gap
The recommendation backlog is large. Filing many atomic recommendations for a broad architectural programme would preserve tasks but lose rationale, ordering, and dependency context.

### Target State
Use a layered governance structure:

```text
Intent document
  -> roadmap wave
  -> strategic plan
  -> parent recommendations
  -> atomic child recommendations
```

### Rules
- Intent documents preserve why and target architecture.
- Roadmap waves reserve workstreams and show dependencies.
- Strategic plans decompose work into ordered areas.
- Parent recommendations represent major deliverables.
- Atomic recommendations are created only when a work area is ready for execution.
- All recommendation writes go through `scripts/ops_data_portal.py`.
- Priority queue health is itself a control-plane signal: track last successful curator run, queue age, active entry count, downstream consumption, and skipped or dependency-blocked reasons.
- Verifier failures, telemetry regressions, and RCA-filed events should be visible in preflight and strategic review before building dashboards or alerting.

### Suggested Parent Recommendations
1. Implement verification harness foundation.
2. Create telemetry causal-chain verifier.
3. Wire verifier harness into V3 workflow gates.
4. Create executor failure packet mechanism.
5. Refactor `/develop-executor` to RCA-only workflow.
6. Make `.agents` canonical and retire duplicate workflow sources.
7. Replace direct JSONL workflow writes with portal calls.
8. Design executor state machine for step, session, and process events.
9. Create telemetry analysis agent for process-event-to-recommendation conversion.
10. Add workflow and skill contract validation to `validate.py`.

---

## Ordered Roadmap

### Phase 1: Telemetry and Verification Foundation
- Implement verifier registry and harness.
- Add first local and Athena verifiers.
- Prove telemetry and ops write paths end-to-end.
- Make V3 verification executable and non-interpretable.

### Phase 2: Workflow and Portal Compliance
- Declare `.agents` canonical.
- Remove direct JSONL writes from workflows and skills.
- Add required context to skills.
- Integrate verifier coverage into plan and critique.

### Phase 3: Executor Failure Packets and RCA Queue
- Generate failure packets on unrecoverable executor failures.
- Invoke RCA skill from structured evidence.
- File RCA recommendations through the portal.
- Stop cleanly without repair or workaround.

### Phase 4: State Machine and Process Event Completeness
- Model plan, implement, executor, verification, RCA, and close as explicit state transitions.
- Replace step-validator and retrospective subagents with telemetry and deterministic checks.
- Generate session summaries from telemetry.

### Phase 5: Telemetry Analysis Agent
- Cluster repeated process events.
- Detect verifier regressions and prompt/workflow failure patterns.
- File deduplicated recommendations.
- Measure whether closed recommendations reduced the original event pattern.

### Phase 6: Safe Autonomous Batch Execution
- Run only recommendations that meet autonomy maturity and verification coverage gates.
- Enforce dependency ordering and deadlock detection.
- Abort batches on failure budgets.
- Use priority queue output as the executor's primary work selection input.

---

## What Not To Do

- Do not scale executor autonomy before telemetry and verification work.
- Do not migrate retrospective, retro-lite, step-validator, or scope-guard as LLM agents by default.
- Do not use direct JSONL writes for recommendations or decisions.
- Do not introduce LLM rescue agents under a different name.
- Do not use `--skip-critique` or prompt hotfixes as normal executor recovery paths.
- Do not file dozens of disconnected recommendations before preserving architectural intent.
- Do not treat ad hoc verification plan commands as sufficient for V3 once registered verifiers exist.
- Do not let `.agents`, `.antigravity`, and `.github` all act as independent workflow sources.

---

## Success Criteria

- A causal-chain verifier proves telemetry records reach Athena and match produced values.
- V3 plans cannot merge without passing registered verifiers or emitting explicit SKIPPED process events; SKIPPED is only acceptable for missing credentials or unavailable environments and must be followed by scheduled health checks.
- Executor failures produce failure packets with the schema defined in this document.
- RCA recommendations are filed through `scripts/ops_data_portal.py` and link back to the failure packet.
- `/develop-executor` no longer repairs, hotfixes, retries around, or manually edits recommendations.
- `.agents` is the canonical interactive workflow layer.
- Step validation and retrospectives are represented by state-machine transitions, verifier outputs, and telemetry analysis.
- The priority queue preserves parent/child recommendation ordering and dependency context.
- Strategic review surfaces product/platform work ratio, priority queue freshness, verifier health, and prompt/workflow performance trends.
- The system can show that a fix reduced the event pattern that caused it.

---

## Relationship to Existing Documents

| Document | Relationship |
|----------|--------------|
| `docs/INTENT-telemetry-system.md` | Defines the telemetry data model used by this control plane. |
| `docs/INTENT-verification-system.md` | Defines the verifier layer required before telemetry can be trusted. |
| `docs/INTENT-recommendation-executor.md` | Defines executor lifecycle and self-modification boundaries. |
| `docs/contracts/instruction-architecture.md` | Defines instruction layering for Gemini, Antigravity, VS Code legacy, and executor prompts. |
| `docs/ARCHITECTURE-WORKFLOW.md` | Describes the current workflow architecture; should reference this document for target-state evolution. |
| `docs/ROADMAP-PLATFORM.yaml` | Tracks this work as a platform wave, not as product phase scope. |

---

**Last Updated:** May 1, 2026
