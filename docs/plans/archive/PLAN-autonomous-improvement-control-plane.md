# Plan

## Intent
Preserve the architectural review of the autonomous improvement loop and decompose it into ordered work areas that can later become parent recommendations and atomic implementation plans. This plan advances the North Star by making the self-improvement system observable, verifiable, RCA-driven, and governable.

## Plan Type
STRATEGIC

## Verification Tier
V1

## Branch
agent/autonomous-improvement-control-plane

## Phase
Phase Platform: Automation Platform — Wave Control Autonomous Improvement Control Plane

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-autonomous-improvement-control-plane.md` | Create | Preserve target architecture, principles, roadmap, and anti-patterns from the workflow architecture review |
| `docs/ROADMAP.md` | Modify | Add the cross-cutting Wave Control workstream without bloating the roadmap |
| `docs/DECISIONS.md` | Modify | Record binding decisions for the control-plane umbrella, `.agents` canonical workflow layer, and telemetry/state-machine replacement of legacy subagents |
| `docs/ARCHITECTURE-WORKFLOW.md` | Modify | Link the workflow architecture to the new control-plane intent and verification intent |
| `docs/contracts/instruction-architecture.md` | Modify | Clarify `.agents` as canonical and add anti-patterns discovered during the migration review |
| `docs/plans/PLAN-autonomous-improvement-control-plane.md` | Create | Strategic decomposition for future implementation sessions |

## Bundled Recommendations
None. Parent recommendations should be filed later through `scripts/ops_data_portal.py` after this strategic plan is reviewed.

## Acceptance Criteria
- [ ] `docs/INTENT-autonomous-improvement-control-plane.md` exists and captures the full architecture review: telemetry, verification, executor RCA, interactive workflows, state machine direction, and recommendation governance.
- [ ] `docs/ROADMAP.md` includes Wave Control with dependencies and deliverables.
- [ ] `docs/DECISIONS.md` records decisions for the control-plane umbrella, `.agents` canonical workflow layer, and replacing legacy retrospective/step-validation subagents with telemetry/state-machine mechanisms.
- [ ] `docs/ARCHITECTURE-WORKFLOW.md` references the new control-plane and verification intent documents.
- [ ] `docs/contracts/instruction-architecture.md` clarifies source-of-truth rules and anti-patterns.
- [ ] No recommendations are filed directly to JSONL in this documentation session.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm new intent document exists | `test -f docs/INTENT-autonomous-improvement-control-plane.md` | Exit 0 | Create the intent document |
| 2 | [pre-deploy] | Confirm roadmap references Wave Control | `grep -q "Wave Control: Autonomous Improvement Control Plane" docs/ROADMAP.md` | Exit 0 | Add or correct the Wave Control entry |
| 3 | [pre-deploy] | Confirm decisions were recorded | `grep -q "Decision 57: Autonomous Improvement Control Plane" docs/DECISIONS.md && grep -q "Decision 58: .*agents.*Canonical" docs/DECISIONS.md && grep -q "Decision 59: Retrospective and Step Validation" docs/DECISIONS.md` | Exit 0 | Add or correct the decision entries |
| 4 | [pre-deploy] | Confirm architecture links include the new intents | `grep -q "INTENT-autonomous-improvement-control-plane.md" docs/ARCHITECTURE-WORKFLOW.md && grep -q "INTENT-verification-system.md" docs/ARCHITECTURE-WORKFLOW.md` | Exit 0 | Add missing related-document links |
| 5 | [pre-deploy] | Confirm instruction contract defines canonical `.agents` source | `grep -q "Canonical Source of Truth" docs/contracts/instruction-architecture.md && grep -q "Direct recommendation writes" docs/contracts/instruction-architecture.md` | Exit 0 | Add source-of-truth and anti-pattern text |

## Constraints
- No code changes in this documentation preservation session.
- Do not file recommendations directly to `logs/.recommendations-log.jsonl`; future recs must use `scripts/ops_data_portal.py`.
- Use `agent/autonomous-improvement-control-plane` for future implementation work derived from this strategic plan. This document was initially authored during a documentation preservation session on an existing feature branch.
- This is V1 documentation work. Future implementation work that touches telemetry, verifier harnesses, executor code, Lambda, or Terraform must be reclassified as V2/V3 as appropriate.

## Context
- `docs/INTENT-verification-system.md` explains why telemetry cannot currently be trusted and why deterministic verifiers must precede further autonomy.
- Decision 55 establishes the RCA-first model: unrecoverable executor failures stop, emit evidence, file a permanent-fix recommendation, and do not attempt LLM rescue.
- The migration from VS Code to Antigravity is a chance to improve workflow architecture rather than port legacy prompts verbatim.
- Retrospective, retro-lite, step-validator, and scope-guard concepts should move into telemetry, verifier results, deterministic diff checks, and state-machine transitions rather than being migrated as LLM subagents by default.
- The recommendation backlog is already large; preserving architecture in intent and plan documents prevents ordering and rationale from being lost in a flat backlog.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Create `docs/INTENT-autonomous-improvement-control-plane.md` with problem statement, North Star, maturity assessment, target control loop, architectural principles, workstreams, ordered roadmap, anti-patterns, and success criteria.
2. Update `docs/ROADMAP.md` with Wave Control: Autonomous Improvement Control Plane, including deliverables, dependencies, and gate relationship.
3. Update `docs/DECISIONS.md` with decisions for the umbrella control-plane architecture, `.agents` canonical workflow layer, and replacing legacy retrospective/step-validation subagents with telemetry/state-machine mechanisms.
4. Update `docs/ARCHITECTURE-WORKFLOW.md` related documents to include the new control-plane intent and verification intent.
5. Update `docs/contracts/instruction-architecture.md` to clarify canonical workflow sources and anti-patterns discovered during the migration review.
6. Execute the Verification Plan commands. Fix documentation until all V1 checks pass.
7. Report changed files and verification results.

## Session Note
This strategic plan was created to preserve an architecture review during an existing feature branch session. The human explicitly requested no commit or push during that preservation session. Future implementation sessions should use the canonical branch listed above and normal commit/PR workflow.

## Work Areas (STRATEGIC plans only)
| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| Telemetry Trust | `scripts/ops_writer.py`, telemetry schemas, data quality configs, telemetry docs | Make telemetry reliable enough to drive autonomous analysis | L |
| Programmatic Verification | `scripts/verifiers/`, `scripts/validate.py`, executor postflight, planning/implement workflows | Replace LLM self-assessment with deterministic hard gates | L |
| Executor RCA | executor failure handling, RCA skill, failure packets, portal filing | Stop, diagnose, and file permanent fixes without rescue behavior | M |
| Interactive Workflow Canonicalization | `.agents/`, `.antigravity/`, `.github/prompts/`, `.github/agents/`, instruction contract | Make `.agents` canonical and remove source-of-truth ambiguity | M |
| State Machine and Process Events | `scripts/execution_state.py`, executor telemetry, workflow close paths | Replace step validators and retrospectives with structured state and events | L |
| Recommendation Governance | `scripts/ops_data_portal.py`, priority queue, roadmap, plans | Preserve ordering and dependencies with parent/child recommendations | M |
| Workflow Contract Validation | `scripts/validate.py`, `.agents/skills/`, `.agents/workflows/` | Prevent future drift in instruction architecture | M |
