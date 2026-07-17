---
description: >-
  Orchestration meta-layer that composes /plan and /implement subagents to drive an entire platform
  roadmap item or audit to completion largely unattended, narrowing the human to intake,
  decomposition, and completion gates. Not a fifth workflow tier -- composes the existing four-tier
  workflow (Decision 90).
model: opus[1m]
argument-hint: [roadmap tier_item id | audit slug | free-form multi-step intent]
---

# Overseer Workflow

**Intent**: Drive an entire platform roadmap item, audit, or multi-step body of work to completion
by decomposing it into one or more `/plan` + `/implement` cycles and dispatching each as a
fresh-context subagent, largely unattended between the G0/G1/G3 human gates. The overseer never
writes source code itself -- every file change happens inside a dispatched planning or
implementation subagent, each running its own full gate stack (decision-scout, plan-critique,
code-review, live verification) unmodified.

*Note: For the full methodology (read-nothing router discipline, bounded hand-back schema, ledger
schema, overlap-matrix procedure, autonomy-boundary policy, the Fable advice-consult protocol, and
the Decision 67/55/73/90 guardrails), invoke your `overseer` skill via the Skill tool. This command
is a thin lifecycle sequence; the skill owns HOW.*

## Step 1: Intake (Gate G0)

Run preflight:
```bash
bin/venv-python -m scripts.session.preflight
```
Apply the same venv/creds/branch/main-freshness constraints as `/plan` and `/implement`'s Preflight
Constraints (see the `overseer` skill's Behavioural Invariants).

State, in your own words, the roadmap item, audit target, or intent this run will drive to
completion, and the rough shape of work you expect (how many slices, at a glance). Present this to
the human and ask: *"Confirm intake -- should I proceed to recon?"* Wait for explicit confirmation.
This is the **G0 gate**: do not proceed to Step 2 without it.

## Step 2: Recon

Per the `overseer` skill's Read-Nothing Router Discipline: read only the preflight cache and the
relevant roadmap projection (the targeted `docs/ROADMAP-PLATFORM.yaml` tier_item, or the audit
target) to understand scope. Do not read full source files here -- that happens inside the
dispatched planning subagents. Identify the candidate slices (one slice = one eventual
`PLAN-{slug}.yaml`) and their `files_in_scope` / `depends_on` edges.

## Step 3: Advice (Fable Consult)

Apply the skill's Fable Advice-Consult Protocol: dispatch a fresh-context `model: "fable"` subagent
to review the proposed decomposition and flag settled-consensus vs. contested design points, and any
best-practice-vs-repo divergence.

## Step 4: Reconcile

Reconcile each flagged point via adopt / adapt / reject per the skill's protocol. Update the
proposed decomposition accordingly.

## Step 5: Decompose (Gate G1)

Apply the skill's Overlap-Matrix Serial/Parallel Decision Procedure to group slices into waves and
assign each wave a serial or parallel dispatch mode (serial is the default; parallel requires a
clean overlap-matrix result plus per-agent worktree isolation and a fixed merge order, per Decision
25). Write the initial `docs/plans/reports/OVERSEER-{slug}.yaml` ledger per the skill's schema.

Present the wave plan (slices, serial/parallel mode per wave, overlap matrix) to the human and ask:
*"Confirm this decomposition -- should I proceed to dispatch?"* Wait for explicit confirmation.
This is the **G1 gate**: do not dispatch any planning subagent without it.

## Step 6: Dispatch

For each wave (serial across waves; within a parallel wave, all slices dispatch together):
1. **Planning-Subagent Dispatch** per the skill: drive each slice's `PLAN-{slug}.yaml` to a merged
   plan PR.
2. **Implementation-Subagent Dispatch** per the skill: once a slice's plan is merged, drive it to a
   merged implementation PR.

Apply the skill's Autonomy-Boundary Policy for any overseer-level judgment call encountered mid-run
(which subagent to re-dispatch, how to interpret an ambiguous hand-back) -- autonomous only when all
four criteria hold, and always defer to the human on the hard always-ask list (IAM/security/spend/
public-surface/governed-deploy) regardless.

Apply the skill's Lifecycle and Gates exception path: a slice BLOCKED or FAILED twice routes to the
`executor-rca` skill and escalates to the human -- never a third silent retry. Apply the
halt-on-open-ci_rca gate before dispatching any new slice.

## Step 7: Aggregate

After each hand-back, update the ledger (`docs/plans/reports/OVERSEER-{slug}.yaml`) with the slice's
status, PR URL, and Bounded Hand-Back object. Recompute readiness for the next wave (a wave with a
`depends_on` edge on an unmerged slice does not dispatch yet).

## Step 8: Completion (Gate G3)

Once every slice reports `merged` (or a terminal `blocked`/`failed` state with human sign-off
already given), present the final ledger summary: slices merged, PR links, any open questions or
deferred work, and any recommendations filed along the way. Ask: *"All slices are settled -- confirm
completion?"* Wait for explicit confirmation. This is the **G3 gate**.

STOP. The overseer session is complete.
