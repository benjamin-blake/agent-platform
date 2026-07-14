# Plan

## Intent
Specify the CI/CD architecture for this agent-first repository as a coherent
ten-layer model (L1-L10) that supersedes the implementation mechanism of
Decision 60 (two-tier validation) and extends Decision 72 (RCA-as-plan-source
merge gate) with forward-fix and scheduled-promotion semantics. The substantive
deliverable is `docs/INTENT-ci-cd-architecture.md`; Decision 73 in DECISIONS.md
is the supporting decision record. Subsequent IMPLEMENTATION plans land the
code changes incrementally.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
agent/ci-cd-architecture

## Phase
Phase Platform / Wave Control (Autonomous Improvement Control Plane).
This plan contributes to the control-plane intent: closing the recursive
self-improvement loop by aligning CI, merge gating, RCA, and environment
promotion into one coherent specification.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-ci-cd-architecture.md` | Create | Substantive deliverable. Canonical specification of L1-L10 layered model, two-tier CI, forward-fix merge gate, promotion train design, planning queue governance, and configuration model. |
| `docs/DECISIONS.md` | Modify | Add Decision 73 (Two-Tier Diff-Aware CI with Forward-Fix and Scheduled Promotion Train) at the top, amending Decision 60's implementation mechanism and extending Decision 72b's ci-rca semantics. |
| `docs/plans/PLAN-ci-cd-architecture.md` | Create | This planning artefact. |

## Bundled Recommendations
None bundled into this REPORT-ONLY plan. Follow-on IMPLEMENTATION plans will
consider bundling these open recs:
- **rec-153** [Medium | XS] -- Supervisor must manually reset status after pyenv-induced postflight CI false-negative. Candidate for bundling into `ci-workflow-restructure`.
- **rec-723** [Medium | S] -- test_validate.py: no integration test for main() presubmit path. Candidate for bundling into `validate-fast-tier-reshape`.
- **rec-429** [Critical | S] -- SLOC and cyclomatic complexity hard gates to scripts/validate.py. Adjacent fit for the static fast-tier; candidate for bundling into `validate-fast-tier-reshape`.

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda-packaged files in scope.
Decision 67 (Lambda deployment deferred) is acknowledged in the INTENT
document but does not produce a deferred-deployment step here.

## Acceptance Criteria
- [ ] `docs/INTENT-ci-cd-architecture.md` exists and contains all ten sections defined in the document outline (Intent, Background, Two-Tier CI, L1-L10 Layered Model, Forward-Fix Merge Gate, Planning Queue Governance, Promotion Train, Configuration, Relationship to Existing Decisions, Known Gaps and Deferrals, Acceptance and Convergence).
- [ ] `docs/INTENT-ci-cd-architecture.md` Known Gaps section explicitly enumerates: (a) L9-L10 deferred to Phase Infra-Env, months away minimum; (b) executor priority-queue rule depends on Wave 4 + Decision 67 reversal; (c) telemetry-trust restoration as the revisit trigger for non-automatable rec surfacing.
- [ ] `docs/DECISIONS.md` contains a new `## Decision 73:` heading immediately after the document title, with Status, Date, Problem, Decision, Rationale, Supersedes/Amends, Acknowledges, Consequences, Known Gaps, and Related sections.
- [ ] The INTENT document and Decision 73 are internally consistent on all key claims (tier semantics, layer triggers, forward-fix rationale, promotion-train cadence, configuration model).
- [ ] No markdown links in the INTENT document or in Decision 73 reference files that do not exist in the repository.
- [ ] Step 9 plan-critique gate returns PROCEED on the PLAN artefact.
- [ ] Step 10 multi-perspective report-critique gate returns PROCEED on the INTENT deliverable (clean convergence on a fresh round) OR human explicitly accepts current state with documented deferrals.

## Verification Plan

V1 (static, document-only). Steps verify structure, internal consistency, and
absence of dead references. All steps are pre-merge.

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm INTENT deliverable exists | `test -f docs/INTENT-ci-cd-architecture.md && echo OK` | Prints `OK` | File missing -- re-run write step |
| 2 | [pre-deploy] | Confirm Decision 73 is present in DECISIONS.md | `grep -q "^## Decision 73:" docs/DECISIONS.md && echo OK` | Prints `OK` | Heading not at correct format -- edit DECISIONS.md insertion |
| 3 | [pre-deploy] | Confirm all required INTENT sections exist | `.venv/Scripts/python.exe -c "p=open('docs/INTENT-ci-cd-architecture.md',encoding='utf-8').read(); required=['## 1.','## 2.','## 3.','## 4.','## 5.','## 6.','## 7.','## 8.','## 9.','## 10.']; missing=[s for s in required if s not in p]; print('OK' if not missing else f'MISSING: {missing}')"` | Prints `OK` | Section missing -- restructure INTENT doc |
| 4 | [pre-deploy] | Confirm Known Gaps section enumerates the three required deferrals | `.venv/Scripts/python.exe -c "p=open('docs/INTENT-ci-cd-architecture.md',encoding='utf-8').read(); checks=['Layer 9','Layer 10','Wave 4','Decision 67','months away','telemetry']; missing=[c for c in checks if c.lower() not in p.lower()]; print('OK' if not missing else f'MISSING: {missing}')"` | Prints `OK` | Add the missing terms to Known Gaps |
| 5 | [pre-deploy] | Confirm Decision 73 references the INTENT doc | `grep -q "INTENT-ci-cd-architecture.md" docs/DECISIONS.md && echo OK` | Prints `OK` | Add INTENT reference to Related section |
| 6 | [pre-deploy] | Confirm no dead intra-repo markdown links in INTENT | `.venv/Scripts/python.exe -c "import re, pathlib; p=pathlib.Path('docs/INTENT-ci-cd-architecture.md').read_text(encoding='utf-8'); root=pathlib.Path('.'); refs=[m.group(1) for m in re.finditer(r'\]\((\.\.?\/[^\)# ]+)\)', p)]; missing=[r for r in refs if not (pathlib.Path('docs')/r).resolve().exists()]; print('OK' if not missing else f'DEAD LINKS: {missing}')"` | Prints `OK` | Fix link target or remove |
| 7 | [pre-deploy] | Confirm Decision 73 supersedes Decision 60 (mechanism only, not target) | `.venv/Scripts/python.exe -c "p=open('docs/DECISIONS.md',encoding='utf-8').read(); d73=p[p.find('## Decision 73:'):p.find('## Decision 72:')]; print('OK' if ('Decision 60' in d73 and 'mechanism' in d73.lower()) else 'FAIL')"` | Prints `OK` | Edit Decision 73 Supersedes section |
| 8 | [pre-deploy] | Confirm internal consistency on tier budgets | `.venv/Scripts/python.exe -c "p=open('docs/INTENT-ci-cd-architecture.md',encoding='utf-8').read(); d=open('docs/DECISIONS.md',encoding='utf-8').read(); intent_5min=p.count('5 min') + p.count('5-min'); dec_5min=d[d.find('## Decision 73:'):d.find('## Decision 72:')].count('5 min') + d[d.find('## Decision 73:'):d.find('## Decision 72:')].count('5-min'); print('OK' if intent_5min >= 2 and dec_5min >= 1 else f'INCONSISTENT: intent={intent_5min} dec={dec_5min}')"` | Prints `OK` | Align budget statements between INTENT and Decision 73 |
| 9 | [pre-deploy] | Confirm PLAN file references INTENT in Scope | `grep -q "INTENT-ci-cd-architecture.md" docs/plans/PLAN-ci-cd-architecture.md && echo OK` | Prints `OK` | Restore Scope row referencing the deliverable |

## Constraints
- No rescue agents or workaround loops (Decision 55).
- No edits to executor self-modification boundary files (Decision 44).
- No STRATEGIC plans permitted while Decision 67 is active. This is REPORT-ONLY and is permitted.
- No Lambda deployment steps required (no Lambda-packaged files in scope, Decision 67 acknowledged).
- All shell commands in the Verification Plan must work on Windows + Git Bash; Python one-liners via `.venv/Scripts/python.exe -c "..."` are the safe default.
- DECISIONS.md is being separately codified in another worktree; the user has confirmed there is no expected conflict with adding Decision 73 at the top of the existing file.

## Context
- This plan is the architectural response to the user-observed friction:
  Decision 60's 5-minute presubmit budget is being violated by 3-10x because
  V3 verifiers and DQ runner integration were added to the default tier
  on or before the day the decision was ratified, and no enforcement
  mechanism was wired.
- The user's initial proposal was "local CI only, scheduled remote CI twice
  a day." This plan supersedes that proposal with an architecture that
  preserves remote CI as the authoritative merge gate (required by
  Decision 72b: branch protection is unavailable) while moving the slow
  end-to-end work off the per-PR critical path via diff-aware fast-tier
  selection.
- The user has explicitly endorsed forward-fix over auto-revert because the
  repository uses many worktrees in parallel; auto-revert is structurally
  hostile to worktree-based development.
- The user has explicitly endorsed the sandbox/SIT/PROD promotion model with
  time + green-streak gates. Both SIT and PROD environments are months-away
  future work; only sandbox exists today.
- The user has explicitly endorsed stricter enforcement of the ci-rca
  hard-block in the planning queue, coupled with suspension of the existing
  mandatory-discussion rule for the 178 non-automatable recommendations
  (revisited when Decision 67 reverses).
- The user has agreed that merge-mode should be derived from the diff (not
  stored per-rec) and should not be conflated with the `automatable` field.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (currently on `agent/ci-cd-architecture`).
- [x] `docs/PROJECT_CONTEXT.md` read.
- [x] `docs/DECISIONS.md` read (relevant decisions: 44, 55, 60, 67, 68, 71, 72, 72b).
- [x] `docs/ROADMAP.md` read (Phase Infra-Env, Phase Platform Waves).
- [x] `docs/ARCHITECTURE-WORKFLOW.md` CI/CD Strategy section read.
- [x] `scripts/validate.py` reviewed for tier-relevant functions.
- [x] `.github/workflows/ci.yml`, `ci-rca.yml`, `deploy.yml`, `pre_commit.yml` read.
- [x] Recent CI run timing data collected (median 18 min, max 50 min, queue ~0).
- [x] CI run log inspected to identify time-dominant phases (V3 verifier 5 min, AWS pytest fixtures 5 min).
- [x] All files in Scope table located and writable.
- [x] Acceptance Criteria understood and verifiable via the Verification Plan.

## Ordered Execution Steps

1. **Create `docs/INTENT-ci-cd-architecture.md`** with the full ten-section
   structure: Intent, Background and Deviation Analysis, Two-Tier CI, L1-L10
   Layered Model, Forward-Fix Merge Gate, Planning Queue Governance, Promotion
   Train, Configuration as Derived Property, Relationship to Existing Decisions,
   Known Gaps and Deferrals, Acceptance and Convergence. Each section must
   include the tables and explicit decisions documented in the conversation
   that produced this plan. [DONE]

2. **Insert Decision 73 in `docs/DECISIONS.md`** at the top of the document,
   immediately after the title and intro paragraph and before Decision 72. Use
   the standard decision-record format: Status, Date, Problem, Decision,
   Rationale, Supersedes/Amends, Acknowledges, Consequences, Known Gaps,
   Related. Decision 73 must reference the INTENT document and be internally
   consistent with it on all key claims. [DONE]

3. **Create `docs/plans/PLAN-ci-cd-architecture.md`** (this file) capturing
   Plan Type REPORT-ONLY, V1 verification tier, the Scope table, the
   Verification Plan, and a full Context section so the plan is self-contained
   for the critique gates. [DONE]

4. **Execute Verification Plan** -- run each step. Loop until pass. Static V1
   tier; failures are document structural issues (missing sections, dead
   links, inconsistencies between INTENT and Decision 73).

5. **Step 9 plan-critique gate.** Run the headless plan-critique skill against
   the PLAN artefact. Loop on REVISE; proceed on PROCEED.

6. **Step 10 multi-perspective report-critique gate (MANDATORY for REPORT-ONLY).**
   Launch two zero-context subagents in parallel via the `Agent` tool: one
   senior-architect perspective (design soundness, internal consistency,
   coverage gaps), one adversarial-risk perspective (blast radius, hidden
   state, divergence from live repo state). Synthesize findings; present to
   human; iterate based on direction. Converge when both agents return PROCEED
   on a fresh round OR the human explicitly accepts current state with
   documented deferrals.

7. **Commit approved deliverables** to the branch (this commit may be empty
   if revisions landed incrementally during Step 6 iteration).

8. **Report:** what was written, where the critique gates landed, what
   follow-on plans are queued.

## Constraints (post-merge)
None applicable. This is a REPORT-ONLY plan; the deliverable is documentation.
No deployment, no runtime behaviour change. Follow-on IMPLEMENTATION plans
carry their own constraints and verification tiers.
