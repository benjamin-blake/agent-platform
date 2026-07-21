---
name: overseer
description: >-
  Deep methodology for the orchestration meta-layer that composes /plan and /implement subagents
  to drive an entire platform roadmap item or audit to completion largely unattended -- read-nothing
  router discipline, bounded hand-back schema, YAML ledger schema, overlap-matrix serial/parallel
  dispatch, autonomy-boundary policy, and the Fable advice-consult protocol. Use when running the
  /overseer workflow.
model: opus[1m]
---

# Overseer Methodology & Rules

You are using this skill to augment the `/overseer` workflow (Layer 3 command; this skill is its
Layer 4 methodology). The overseer is an orchestration meta-layer, NOT a fifth workflow tier
(Decision 90): it composes the existing `/plan` and `/implement` subagents -- each running its own
full gate stack (decision-scout, plan-critique, code-review, live verification) unmodified -- to
drive an entire roadmap item, audit, or multi-slice body of work to completion, narrowing the human
to the intake (G0), decomposition (G1), and completion (G3) gates. The overseer session itself never
edits source code, terraform, or Python; every file change happens inside a dispatched subagent.

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true              # session_preflight.py must run at intake (G0)
never_on_main: true              # no file edits while on main branch
no_code_changes: true            # the overseer itself never edits source; writes happen only inside dispatched /plan and /implement subagents
meta_layer_not_tier: true        # composes the existing four-tier workflow (Decision 90); introduces no fifth tier
no_rescue_loops: true            # CI failures route to ci_rca + human escalation, never inline-patched (Decision 55/72)
halt_on_open_ci_rca: true        # halts new dispatch while any open source=ci_rca critical rec exists (Decision 73)
```

## Read-Nothing Router Discipline

The overseer's own context must stay cheap enough to drive a multi-wave, multi-slice run without
exhausting its window. It reads only: the preflight cache, the targeted roadmap projection (a single
tier_item or audit slug), and the Bounded Hand-Back objects returned by its own dispatched subagents.
It never reads full source files, `docs/DECISIONS.md`, or a subagent's raw transcript directly --
those reads happen inside the dispatched subagent's own fresh context, and only the bounded summary
returns. The overseer acts as router and reconciler, not as a doer: if a judgment call requires
reading a file to resolve, that read belongs inside a subagent dispatch, not in this session.

## Bounded Hand-Back Schema

Every subagent the overseer dispatches (planning, implementation, Fable advice, RCA) returns exactly
this shape and nothing more:
```yaml
status: PROCEED | REVISE | BLOCKED | FAILED
summary: <=150 words, prose synthesis of what happened
artifacts: [file paths touched/created, e.g. docs/plans/PLAN-{slug}.yaml, or a PR URL]
evidence: [verifiable proof pointers -- VP compliance table, PR number, commit sha]
decisions: [decision ids cited or newly ratified]
open_questions: [unresolved items requiring human input, or empty]
```
Do not ask a subagent to paste back file contents, full diffs, or raw transcripts -- only this
bounded object. If a subagent returns output missing `status` or otherwise not shaped like this, the
dispatch has NOT completed -- re-dispatch; never proceed on an incomplete hand-back (mirrors the
planning skill's "missing Verdict line" precedent for the decision-scout and plan-critique gates).

## Overseer Ledger Schema

Runtime artefact: `docs/plans/reports/OVERSEER-{slug}.yaml`, created by the overseer AT EXECUTION
TIME (not shipped by any plan that merely stands up this skill/command). Machine-parseable YAML per
the Agent-First Repository rule -- no narrative companion document.
```yaml
schema_version: 1
slug: "{slug}"
intent: >-
  1-2 sentences: the roadmap item, audit, or body of work this run is driving to completion.
wave_plan:
  - wave: 1
    slices: ["{slug-a}", "{slug-b}"]
    dispatch: serial | parallel
    rationale: why this grouping (overlap-matrix result)
slices:
  - plan_slug: "{slug-a}"
    status: pending | planning | plan_merged | implementing | verifying | merged | blocked | failed
    pr_url: null  # or the merged PR URL once known
    hand_back: null  # most recent Bounded Hand-Back object from this slice's subagent
autonomous_decision_log:
  - timestamp: "<ISO date>"
    decision: what was decided without asking the human
    rationale: which autonomy-boundary criterion applied
gates:
  g0_intake: pending
  g1_decomposition: pending
  g3_completion: pending
```
Update the ledger after every subagent hand-back and every gate confirmation. This is the single
source of truth for "where is this run" -- on resume, the overseer reconstructs state from this file,
never from chat history (cold-start discipline, mirroring the `implement` skill's
treat-every-turn-as-cold-start rule).

## Lifecycle and Gates

- **G0 Intake (human-gated):** the human states the roadmap item, audit target, or intent; the
  overseer runs preflight and confirms scope, then gets explicit human go-ahead before any subagent
  dispatch.
- **G1 Decomposition (human-gated):** after recon and the Fable advice-consult, the overseer presents
  the proposed wave plan (slices, overlap matrix, serial/parallel split per wave) and gets explicit
  human confirmation before dispatching any planning subagent.
- **G3 Completion (human-gated):** once every slice reports a terminal state (merged, or
  blocked/failed with prior human sign-off), the overseer presents the final ledger summary and gets
  explicit human sign-off before closing the run. There is no separately numbered G2 -- G1 and G3
  bracket the unattended dispatch/aggregate loop, which runs without its own numbered gate.

**Blocked/failed-twice exception path:** a slice that comes back BLOCKED or FAILED twice (two
dispatch attempts) never gets a silent third retry. It routes to the `executor-rca` skill for
root-cause diagnosis, and the overseer escalates that slice to the human with the RCA findings --
the same Decision 55 RCA-first pattern the rest of the platform uses, applied one level up the stack.

**Halt-on-open-ci_rca gate (Decision 73):** before dispatching any new slice -- at G1 or mid-run --
the overseer checks `ci_rca_unresolved_recs` in the preflight cache. If any open `source=ci_rca`
critical rec exists, the overseer halts new dispatch and escalates to the human; it does not
dispatch unrelated slices past the hard block.

## Overlap-Matrix Serial/Parallel Decision Procedure

At G1, decompose the target into slices (each slice = one eventual `PLAN-{slug}.yaml`). For every
pair of slices, compare `files_in_scope` and `depends_on` edges to build an overlap matrix (same
shape as the `orient` skill's overlap matrix):
- Disjoint `files_in_scope` and no `depends_on` edge between a pair -> eligible for the SAME wave,
  dispatched in PARALLEL.
- Any file overlap, or a `depends_on` edge -> different waves, SERIAL (the dependency's wave runs
  and merges first).

Serial is the default. Parallel dispatch is chosen only when the matrix affirmatively clears a pair
-- never as a default optimization. Any parallel wave of code-writing subagents requires (Decision
25): one dedicated git worktree per agent, disjoint file scopes enforced by each slice's own plan
Scope table, and a FIXED merge order declared in the wave_plan entry before dispatch, not decided
after the fact.

## Autonomy-Boundary Policy

An overseer-level judgment call (which slice to dispatch next, how to reconcile a Fable divergence
flag, whether a hand-back's `open_questions` blocks the wave) is made AUTONOMOUSLY only when ALL
four criteria hold:
1. **Settled-consensus** -- the Fable advice-consult and the repo's existing decisions agree; no
   contested-practice flag applies to this point.
2. **Convention-fit** -- the choice matches an existing repo pattern (a precedent skill, command, or
   decision already resolves it this way).
3. **Reversible** -- a wrong call costs at most a re-dispatch, never a merged artefact that must be
   unwound.
4. **No-credible-alternative** -- there is no second reasonable design the human would plausibly
   prefer.

If any criterion fails, the overseer does not decide alone: it presents 2-3 concrete options with a
recommendation and waits for the human. Every autonomous decision (and which criteria it satisfied)
is logged to the ledger's `autonomous_decision_log`.

**Hard always-ask list (no autonomy-boundary override, ever):** IAM/security-relevant changes,
anything with real spend impact, any change to a public-surface artefact (the PUBLIC-repository
confidentiality boundary, per AGENTS.md), and any governed-deploy action (terraform apply routing,
Lambda deploy channel, gated-apply approval). These always route to a human gate regardless of how
settled the four autonomy criteria look.

## Fable Advice-Consult Protocol

Before each major design decision (the G1 decomposition shape; any point where the overseer itself
must choose an architecture rather than sequence already-known work), dispatch a fresh-context
subagent via the `Agent` tool with `model: "fable"` (Fable 5). The Fable subagent:
- Is free to read the repo (Read/Grep/Glob) for grounding, but edits nothing.
- Separates its advice into "settled consensus" (industry-standard practice, low-risk to adopt
  as-is) versus "contested" (multiple valid approaches, where the repo's existing convention should
  usually win).
- Explicitly flags any point where general best practice diverges from this repo's existing
  pattern, stating which side it recommends and why.

Reconcile each flagged point via one of three verdicts: **adopt** (take the Fable suggestion as-is),
**adapt** (blend it with the existing repo convention), or **reject** (keep the repo convention, log
why). Record the reconciliation in the ledger's context. Invoke once per major design decision --
not once per slice and not on every wave; re-consulting on already-settled operational sequencing
wastes a dispatch for no new judgment.

## Planning-Subagent Dispatch

Per slice: dispatch via the `Agent` tool with `model: "opus"` (matches the `planning` skill's
`opus[1m]` pin), instructing the subagent to invoke the `planning` skill via the `Skill` tool exactly
as `/plan` would, running the FULL `/plan` lifecycle itself (decision-scout gate, plan-critique gate)
to produce a merged `docs/plans/PLAN-{slug}.yaml`. This is not a shortcut around planning rigor --
the human's G1 confirmation authorizes the decomposition, not a skipped critique. The subagent
returns the Bounded Hand-Back once its plan PR is merged to main (or BLOCKED/FAILED with the
convergence-rule escalation already applied inside its own gate loop).

## Implementation-Subagent Dispatch

Per slice, once its plan is merged: dispatch via the `Agent` tool with `model: "sonnet"` (matches the
`implement` skill's pin), instructing the subagent to invoke the `implement` skill via the `Skill`
tool against the merged `docs/plans/PLAN-{slug}.yaml`, running the full Live Verification Protocol,
the code-review gate, and the Decision 76 event-driven GitHub MCP commit flow (`subscribe_pr_activity`,
wait for the CI-green signal, squash-merge) -- never a sleep/poll loop. The subagent returns the
Bounded Hand-Back once the slice's PR is merged, or with status BLOCKED/FAILED and an RCA pointer if
it could not complete.

## Decision Guardrails

- **Decision 67 (executor freeze):** the overseer is an interactive, human-gated CC-web
  orchestration meta-layer -- NOT `scripts/execute_recommendation.py`. It never consumes the
  recommendation queue and dispatches only IMPLEMENTATION-type plans, staying within the freeze's
  scope (the freeze targets the autonomous Lambda executor, not this interactive surface).
- **Decision 55/72 (RCA-first, no rescue loops):** a red build, or a slice BLOCKED/FAILED twice,
  never gets an inline patch or a silent retry from the overseer -- it routes to `executor-rca` and
  escalates to the human.
- **Decision 73 (halt-on-open-ci_rca):** see Lifecycle and Gates above -- an open critical ci_rca
  rec is a hard dispatch block, not a soft warning.
- **Decision 90 (four-tier workflow; meta-layer, not a fifth tier):** the overseer composes `/plan`
  and `/implement` exactly as they already exist; it introduces no new workflow tier, no new plan
  type, and no bypass of either subagent's own gates. AGENTS.md's "Skills and slash commands" section
  registers `/overseer` explicitly as a meta-layer for this reason.
