# Plan

## Intent
Rewrite the project roadmap to reflect the current reality: the automation platform is the force multiplier that compounds across all product phases. By formalising it as a parallel infrastructure track ("Phase Platform") with explicit waves and gating relationships, the system can prioritise work that accelerates everything downstream -- directly advancing the North Star of a self-improving automated trading system.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-roadmap-v2

## Phase
Phase Platform (infrastructure governance -- prerequisite to all product phases)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP.md` | Modify | Rewrite phase structure: add Phase Platform (5 waves), renumber product phases (1.5 becomes 2, 2 becomes 3, etc.), update critical path and dependency graph |
| `.github/copilot-instructions.md` | Modify | Update "Phase 1.5 next. Phases 2-6 planned" to reflect new numbering |
| `docs/ARCHITECTURE.md` | Modify | Update phase number references |
| `docs/DECISIONS.md` | Modify | Update phase number references in decisions that cite Phase 1.5, Phase 2, etc. |

## Bundled Recommendations
- **rec-021** (XS, open): Archive resolved recommendations to RECOMMENDATIONS_ARCHIVE.md -- the curator (Wave 1) should handle this as its first triage action, but the roadmap should reference the intent

## Acceptance Criteria
- [ ] `docs/ROADMAP.md` contains a `## Phase Platform: Automation Platform` section with 5 waves
- [ ] Wave 1 (Priority Queue Pipeline) references recs 455-460 and PLAN-infra-curator-pipeline
- [ ] Wave 2 (Telemetry Root Cause Fix) is scoped to root cause identification and write-path fix only -- no historical cleanup
- [ ] Wave 3 (Executor Decomposition) references recs 443-447
- [ ] Wave 4 (Autonomous Executor) references PLAN-infra-autonomous-executor and rescue agent architecture
- [ ] Wave 5 (Repo Consolidation) references recs 023, 164, 031
- [ ] Former Phase 1.5 is renumbered to Phase 2
- [ ] Former Phase 2 (Formula Integration) is renumbered to Phase 3
- [ ] Former Phase 3-6 are renumbered to Phase 4-7
- [ ] Phase 2 (Schema Backfill) lists Wave 1 as an advisory soft dependency (recommended, not blocking)
- [ ] Critical path diagram updated to show Phase Infra as parallel track with wave-to-phase gate dependencies
- [ ] Phase Infra-Env (Multi-Environment CI/CD) remains as a separate infrastructure track (distinct naming avoids ambiguity)
- [ ] `.github/copilot-instructions.md` phase references updated to match new numbering
- [ ] `docs/ARCHITECTURE.md` phase references updated to match new numbering
- [ ] `docs/DECISIONS.md` phase references updated to match new numbering
- [ ] Decision 41 (Three-Layer Data Pipeline) implementation path noted in Phase 2 or Phase 3 section
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Phase Platform is a PARALLEL track -- it must not create false sequencing that blocks product phases unnecessarily
- Each wave gates the next, but product phases gate only on specific waves (not "all of Phase Infra")
- The roadmap must remain a single readable document (no splitting into multiple files)
- Completed phases (Phase 1) retain their content for historical reference
- Existing plan files (PLAN-infra-curator-pipeline, PLAN-infra-autonomous-executor) are referenced, not duplicated
- No time estimates on Phase Infra waves -- they are ongoing and overlapping with product phases

## Context
- **Decision 42**: Three-Tier Workflow Architecture -- the executor, supervisor, and human tiers that Phase Infra Wave 4 aims to compress
- **Decision 44**: Executor Self-Modification Boundary -- rescue agents and orchestrator files are inside the boundary
- **Decision 45**: S3 as authoritative source for cloud-produced logs -- prerequisite for Wave 1
- **PLAN-infra-curator-pipeline**: STRATEGIC plan already produced atomic recs (455-460) for Wave 1
- **PLAN-infra-autonomous-executor**: STRATEGIC plan with 5 Work Areas mapping to Wave 4
- **Telemetry health**: 75% duplicate rate in session-telemetry (root cause unidentified) -- Wave 2 motivation
- **Recommendation landscape**: 488 total (256 closed, 185 unique open, 126 non-automatable) -- Wave 1 curator's first job is triaging these
- **Velocity**: 248 recs closed in April 2026 alone -- the executor works, it just needs better decision-making (priority queue) and reliability (rescue agents)

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add Phase Infra section to ROADMAP.md
**File**: `docs/ROADMAP.md`
**Action**: Insert a new `## Phase Platform: Automation Platform (Parallel Track)` section after the Phase 1 COMPLETE section and before the current Phase 1.5 section. This section must contain:

- A goal statement: "Build the decision-making, observability, and autonomy infrastructure that accelerates all product phases"
- A rationale paragraph explaining why this is a parallel track (not sequential) and how waves gate product phases
- Five subsections, one per wave:

**Wave 1: Priority Queue Pipeline**
- Goal: Give the system a decision-making organ so work is prioritised by impact, not filing order
- Deliverables: S3-backed priority queue, rec-curator Lambda pipeline, preflight display, curator triage of 126 non-automatable recs
- References: `PLAN-infra-curator-pipeline.md`, recs 455-460
- Status: Plan complete, atomic recs ready for execution
- Soft dependency for Product Phase 2 (backfill) -- recommended before, but backfill is a deterministic data-loading task that does not require priority queue orchestration. The gate is advisory: Phase 2 can proceed independently if Wave 1 is delayed

**Wave 2: Telemetry Root Cause Fix**
- Goal: Fix the write-path defect causing 75% duplicate rate in session-telemetry; establish schema contracts for log writes
- Deliverables: Root cause identification and fix for `session_telemetry.py` duplication, `docs/contracts/log-storage.md` schema contract, `scripts/log_writer.py` validated write gateway
- References: recs 386, 387, 364, 462
- Explicit non-goal: Historical data cleanup (current telemetry has low value as the executor is still being developed; once the root cause is fixed, new data will be clean)
- Gates: Wave 4 (autonomous executor) -- telemetry must be trustworthy before rescue agents generate their own telemetry

**Wave 3: Executor Decomposition Pass 2**
- Goal: Extract remaining monolithic functions from `execute_recommendation.py` into the `scripts/executor/` package
- Deliverables: `telemetry.py`, `acceptance_lint.py`, `batch.py`, `model_routing.py`, `formatters.py`
- References: recs 443-447
- Status: Pass 1 complete (plan.py, step_runner.py, postflight.py already extracted)
- Gates: Wave 4 -- rescue agents need well-factored modules to hook into

**Wave 4: Autonomous Executor**
- Goal: Absorb `/develop-executor` supervisor responsibilities into deterministic scripts and rescue agents, enabling unattended batch execution
- Deliverables: Rescue agent contract and dispatcher, acceptance repair agent, failure diagnosis agent, friction capture agent, orchestrator loop with killswitch
- References: `PLAN-infra-autonomous-executor.md`, recs 468-478
- Gate prerequisite: Wave 2 (telemetry duplicate rate below 10% for new data) AND Wave 3 (decomposed executor modules)
- Gates: Product Phase 3 (Formula Integration) -- complex multi-file changes need reliable autonomous execution

**Wave 5: Repo Consolidation**
- Goal: Align repository structure with current workflow reality; eliminate orphaned scripts, agents, and documentation
- Deliverables: `copilot-instructions.md` modularisation, directory restructure, workflow orphan cleanup, agent consolidation
- References: recs 023, 164, 031, 016
- Gate prerequisite: Waves 1-4 stable (consolidation is dangerous while architecture is in flux)

### Step 2: Renumber product phases and add Decision 41 note
**File**: `docs/ROADMAP.md`
**Action**: Rename the following sections. Content stays the same, only the phase numbers and dependency references change:

| Current | New | Title Change |
|---------|-----|-------------|
| `## Phase 1.5` | `## Phase 2` | "Schema Flattening, Deltas & Backfill" (unchanged) |
| `## Phase 2` | `## Phase 3` | "Formula Integration" (unchanged) |
| `## Phase 3` | `## Phase 4` | "A/B Testing Framework" (unchanged) |
| `## Phase 4` | `## Phase 5` | "Circuit Breakers" (unchanged) |
| `## Phase 5` | `## Phase 6` | "Monitoring & Observability" (unchanged) |
| `## Phase 6` | `## Phase 7` | "Automated Weighting & Decay" (unchanged) |

Update all `Dependencies:` lines within each phase to reference the new phase numbers. Update all prose references (e.g., "Phase 2 complete" becomes "Phase 3 complete").

Add a note to the new Phase 2 (Backfill) or Phase 3 (Formula Integration) section: "Decision 41 (Three-Layer Data Pipeline) introduces a three-layer architecture (RAW, Encoder, Discovery) with implementation recs 201-209. The encoder and attention layer work lands in Phase 3 as a prerequisite for formula discovery at scale."

### Step 3: Update cross-file phase references
**Files**: `.github/copilot-instructions.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`
**Action**: Search each file for references to "Phase 1.5", "Phase 2", "Phase 3", "Phase 4", "Phase 5", "Phase 6" and update to the new numbering (1.5->2, 2->3, 3->4, 4->5, 5->6, 6->7). Use `grep -n "Phase [1-6]" <file>` to locate all references before editing. Be careful to preserve "Phase 1" (complete, unchanged) and "Phase Infra-Env" (unchanged).

**Critical exclusion for ARCHITECTURE.md**: The file contains workflow step labels -- "Phase 1: Planning", "Phase 2: Implementation", "Phase 3: Closure" (approximately lines 149-165) -- that describe the agent workflow loop, NOT product phases. Do NOT renumber these. Only renumber references that clearly refer to product roadmap phases (e.g., "Phase 1.5 (schema flattening)", "Phase 2 (Formula Integration)").

### Step 4: Add Phase Platform wave gates to product phase dependencies
**File**: `docs/ROADMAP.md`
**Action**: Update the `Dependencies:` line for each product phase:

- Phase 2 (Backfill): Add "Phase Platform Wave 1 recommended before (priority queue for execution prioritisation) -- soft dependency, not blocking"
- Phase 3 (Formula Integration): Add "Phase Platform Wave 4 (autonomous executor for complex multi-file changes)"
- Phases 4-7: Retain existing product phase dependencies, do not add Phase Platform gates (these phases benefit from but do not require automation platform maturity)

### Step 5: Rewrite the critical path diagram
**File**: `docs/ROADMAP.md`
**Action**: Replace the existing `Total Timeline` / `Critical Path` section at the bottom with an updated diagram that shows Phase Platform as a parallel track. Use ASCII art:

```
Phase 1 (COMPLETE)
  |
  +-- Phase Platform (parallel) ----+------+------+------+
  |   Wave 1 -> Wave 2 -> Wave 3 -> Wave 4 -> Wave 5   |
  |     :                            |                   |
  |     v (soft)                      v (hard)            |
  +-- Phase 2 (Backfill) -----> Phase 3 (Formulas) -----+
                                   |
                              Phase 4 + Phase 5 (parallel)
                                   |
                              Phase 6 -> Phase 7
```

Note: `:` denotes a soft (advisory) dependency; `|` denotes a hard gate.

Remove the old time estimates ("14-17 weeks"). Add a note: "Phase Platform waves have no fixed timeline -- they are ongoing infrastructure investment that runs parallel to product development. Product phases gate on specific waves, not on Phase Platform completion."

### Step 6: Run validation
**Command**: `python -m pytest tests/ -x -q` then `python scripts/validate.py`
**Expected**: Both exit 0 (ROADMAP.md changes are documentation-only, should not break any tests or validation)

### Step 7: Report implementation summary
Report what was changed and confirm all acceptance criteria are met.
