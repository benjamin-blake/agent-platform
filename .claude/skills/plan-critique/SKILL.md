---
name: plan-critique
description: "Use when: critique a plan, challenge assumptions, review docs/plans/PLAN-{slug}.yaml before implementation. Mandatory gate between planning and implementation."
required-context:
  - docs/PROJECT_CONTEXT.md
---

## Intent

Challenge PLAN-*.yaml from a different perspective than the model that wrote it. Evaluate strategic alignment, decision consistency, and work area scoping before implementation begins. (Plans are YAML documents validated against the `PlanDocument` schema in `scripts/roadmap/plan_document.py` per T1.11 / CD.22; the legacy PLAN-*.md form is deprecated -- if handed a .md path, emit a deprecation warning in your output and critique it anyway for one release cycle.)

This is a BLOCKING gate. The critique must assess whether the plan is strategically sound, well-bounded, and aligned with the North Star. A superficial review that only checks formatting is unacceptable.

---

## Steps

### Phase 1: Load Context (MANDATORY - Do Not Skip)

1. Read the ENTIRE plan file path provided by the caller (e.g., `docs/plans/PLAN-infra-parallel-workflow.yaml`). The caller passes this path explicitly — do not default to `docs/plans/PLAN.md`. If no path was provided, search `docs/plans/` for files matching `PLAN-*.yaml` and read the most recently modified one (fall back to `PLAN-*.md` only if no .yaml exists, and note the deprecation in your output).

2. Read `docs/PROJECT_CONTEXT.md` in full (for North Star and rules).

3. **Targeted roadmap extraction, not a full-file read:** extract only the `tier_items[]` (from `docs/ROADMAP-PLATFORM.yaml`) and product-phase entries (from `docs/ROADMAP-PRODUCT.yaml`) the plan's `phase` and `context` fields name, via a `bin/venv-python -c` yaml.safe_load projection -- do not `Read` either file in full (ROADMAP-PLATFORM.yaml alone is >600KB).

4. **Targeted decision extraction + conflict-sweep, not a full-file read:** read only the decision sections named in the plan's context `Decision-scout verdict + CITE list` (locate each via `rg "^## Decision N:" docs/DECISIONS.md`), plus a conflict-sweep: `rg` 2-3 keywords drawn from the plan's approach over `^## Decision` headers in `docs/DECISIONS.md` to catch a contradiction the scout's CITE list omitted. Do not Read the full ~230KB file -- the decision-scout gate already paid that cost minutes earlier in the same workflow.

5. **For IMPLEMENTATION plans:** Read the files listed in the plan's `scope` list (the `## Scope` table in legacy .md plans) to verify the plan's accuracy. For STRATEGIC plans, this is not required — work areas are high-level and do not require file-level verification.

### Phase 2: Strategic Analysis

6. **Check for decision conflicts:** Does the plan contradict or re-decide anything already resolved in `docs/DECISIONS.md`? Cite specific decision numbers and the conflicting plan section.

7. **Score North Star alignment (1-5):** Does the `## Intent` section directly serve the North Star ("Build a self-improving automated trading system")? A score of 1 means no discernible connection; 5 means it directly advances the goal. Provide a 1-2 sentence justification.

8. **Evaluate Work Area scoping (STRATEGIC plans) or Scope breadth (IMPLEMENTATION plans):**
   - For STRATEGIC: Are Work Areas well-bounded (one logical concern per area)? Too large (suggest split)? Too small (merge with adjacent area)?
   - For IMPLEMENTATION: Are all scope entries necessary? Does the Scope extend beyond the stated phase?

9. **Check phase dependencies:** Does this plan depend on work from a prior phase that is not yet complete? Cite specific ROADMAP phase entries.

10. **Assess strategic risks:** Are there risks that could invalidate the approach without execution? Examples: external dependency not yet available, contradicts a pending decision, architectural assumption that hasn't been verified.

11. **Check Acceptance Criteria (IMPLEMENTATION plans only):** Are all criteria verifiable and testable? Flag any that are vague, subjective, or untestable (e.g., "improved performance" without a metric).

12. **Check Constraints for contradictions:** Do the Constraints conflict with rules in `docs/PROJECT_CONTEXT.md` or prior decisions in `docs/DECISIONS.md`?

12b. **Lambda deployment completeness (IMPLEMENTATION plans only):** Use `bin/venv-python -m scripts.lambda_manifest --list-patterns` to determine which scope files are Lambda-packaged and `compute_affected_artifacts()` to identify the affected artifact slug(s). For each affected artifact with `status: active` in its `src/lambdas/<slug>/manifest.yaml`, the Ordered Execution Steps MUST include: (a) a per-Lambda build step, (b) a per-Lambda deploy step, (c) a smoke-test step using `run_scheduled_agent.py --smoke-test`, and (d) model ID validation against `docs/contracts/inference-provider.yaml` if model IDs are changed. Blanket `build_lambda.py --deploy` (all artifacts) is acceptable only when the plan modifies all active artifacts; per-Lambda scoping is preferred. If any active-artifact deploy step is missing, recommend REVISE. Exception: stub artifacts (status: stub) require no deploy step -- V1 verification suffices. The blanket `DEFERRED: build_lambda.py --deploy` exception for Decision 67 is withdrawn; Decision 67's Lambda-deploy clause was lifted by Decision 79 (CD.16 + CD.24). Reference: Decision 47, Decision 67 (Lambda-deploy clause lifted), Decision 79, Step 4 (Lambda Deployment Assessment) of plan.prompt.md.

12c. **Verification Plan executable command check (IMPLEMENTATION plans only):** Every `verification_plan` entry MUST have a `command` field containing a literal executable shell command or Python one-liner (the `PlanDocument` schema rejects empty commands; your job is to judge whether the command actually exercises the feature rather than being a structural-only check). FAIL if any VP step is prose-only with no executable command. For V3 plans, every VP step's `phase` must be `pre-deploy` or `post-deploy`. If either check fails, recommend REVISE with the specific VP steps that need commands or tags added.

12d. **STRATEGIC plan gate:** If the plan's `## Plan Type` is `STRATEGIC` AND the executor freeze is still active per AGENTS.md Temporary Operational Constraints (pending CD.17 reversal), recommend REVISE with: "STRATEGIC plans are suspended while the executor freeze holds (CD.17): the autonomous executor has no consumer for STRATEGIC-decomposed recommendations. Convert to an IMPLEMENTATION plan, or split into multiple atomic IMPLEMENTATION plans, or wait for CD.17 reversal."

12k. **Closure obligation check (CONDITIONAL -- IMPLEMENTATION plans only):** This check fires ONLY when the plan meets one of the two trigger conditions below. Additive plans that do neither are explicitly exempt.

Trigger condition 1 -- **Rec-resolving plan**: the plan's `intent`, `context`, `scope`, or `acceptance_criteria` explicitly names one or more open recommendation IDs as the motivation for the work (e.g. "closes rec-2187", "resolves ci_rca recs", "fixes the open rec").
- Required: `bundled_recommendations` in the YAML must be non-empty and list the rec ids.
- Required: at least one VP step must verify each rec closed (grep the local cache after sync, or use `ops_data_portal --sync && grep rec-NNNN logs/.recommendations-log.jsonl`).
- If either is missing, recommend REVISE: "Rec-resolving plan omits closure obligation: add bundled_recommendations list and a VP step to verify each rec closed."

Trigger condition 2 -- **Surface-retiring plan**: the plan's `scope` includes a row with `action: Delete` OR an explicit X->Y migration/cutover (old path deleted, Lambda retired, write path swapped, config flag removed, backend superseded).
- Required: at least one VP step that confirms the old surface is unreachable or deleted (grep for call sites, `test -f` for deleted files, import smoke-test, etc.).
- If missing, recommend REVISE: "Surface-retiring plan omits stale-reference sweep VP step: add a VP step that verifies the old surface is dead."

12l. **closes_criteria check (follow-on plans, IMPLEMENTATION only):** If the plan's phase/context names an `in_progress` tier_item, `closes_criteria` MUST be non-empty; each ref must name a criterion carrying `status: open` in `docs/ROADMAP-PLATFORM.yaml`; and `acceptance_criteria` must map 1:1 onto the chosen open criteria. If any of these fail, recommend REVISE: "Follow-on plan omits or misdeclares closes_criteria: [specifics]." A plan targeting no in_progress tier_item is exempt from this check.

12m. **Tier fitness check:** `verification_tier` must satisfy the planning skill's Verification Tier Guidelines, narrowed by an intentional refinement (Decision 48/79) so comment-only `.tf` or docstring-only Python edits are not force-escalated: a **resource-affecting** `.tf` scope file (not comment-only) OR an **active-manifest** Lambda scope file (`status: active` in its manifest -- Decision 79; `status: stub` does not trigger this) => `V3`; any Python source scope file => `>= V2`. A lower declared tier than the qualifying scope requires => recommend REVISE citing the specific scope file and the tier it demands.

### Phase 2b: Frame Challenge (MANDATORY)

Phase 2 checks the plan's *details* against the existing frame. This phase challenges the *frame itself*. See Decision 75 (Frame-Lock Anti-Pattern in Architectural Planning) for the failure mode this phase is designed to catch.

Ask the following five questions against the plan's chosen approach. For each, write a one-sentence answer. Where the answer surfaces a concrete contradiction with a Decision, a Roadmap item, or a North Star principle, recommend REVISE. Otherwise surface the answer informationally -- the human or downstream planner decides whether to pivot.

12e. **Question 1 -- Is the chosen primitive the right primitive?** What if the orchestrator / runtime / data store / interface in this plan wasn't this kind of thing? Could the role be filled by a platform-native primitive (Step Functions, EventBridge, SQS, DynamoDB Streams, Lambda, Athena) already in production in this codebase? If the plan introduces a custom orchestrator, scheduler, retry loop, state machine, or queue, name the platform primitive it could be replaced by and explain why it isn't.

12f. **Question 2 -- Is the decomposition boundary right?** If the plan treats X as a single unit, could X be decomposed into smaller independently-deployable, independently-observable, independently-retryable units? If the plan proposes N independent units, should they collapse into one? The frame-lock case (Decision 75) was a monolithic Python loop that should have been decomposed into per-step Lambdas orchestrated by Step Functions; the corresponding question would have caught it.

12g. **Question 3 -- What existing capability could absorb this custom code?** Enumerate the platform capabilities ratified in `docs/DECISIONS.md` and shipped in `terraform/` that are conceptually adjacent to what the plan proposes. For each, ask why the plan is not using it. Plans that propose custom logic where AWS-native or codebase-native primitives exist must justify the divergence explicitly.

12h. **Question 4 -- Are inherited assumptions still valid?** When the plan cites a constraint of the form "we can't do X because Y," and Y references a Decision older than 30 days (or one that predates a more recent capability-ratifying Decision), surface that Decision and ask whether its premise still holds. CD.11's premise ("Fargate replaces Lambda dispatcher because executor exceeds 15 min") is the canonical example -- it carried forward an assumption that newer decomposition options invalidate.

12i. **Question 5 -- What tools have been acquired since this approach was conceived?** When the plan extends, refactors, or revives an existing approach, enumerate the Decisions, infrastructure primitives, and skills added to the codebase since the approach's original design. Ask whether any of them retroactively change the right shape of the work. Decision 39 (Step Functions over Airflow) is the canonical retroactive trigger that was not applied to the executor architecture; this question would have caught the gap.

12j. **Recommendation impact:** If any of 12e-12i surfaced a concrete contradiction with a Decision, a Roadmap item, or a North Star principle, recommend REVISE and cite the contradiction. If the challenges surface real questions but no concrete contradiction, surface them in the Frame Challenge output field for human consideration and do not, on this basis alone, recommend REVISE.

### Phase 3: Structured Output

13. Produce this structured output:

```
## Plan Critique

**Files Read:** [plan path; docs/PROJECT_CONTEXT.md; targeted roadmap items: <ids>; targeted decision sections: <ids>; scope files (IMPLEMENTATION only)] -- count must match the scope entry count

**Plan Type:** STRATEGIC / IMPLEMENTATION / REPORT-ONLY

**Decision Conflicts:** None / [list with decision numbers]

**Frame Challenge (Decision 75):**
- Q1 (right primitive?): [one-sentence answer, or "no frame issue"]
- Q2 (right decomposition?): [one-sentence answer, or "no frame issue"]
- Q3 (existing capability could absorb?): [one-sentence answer, or "no frame issue"]
- Q4 (inherited assumptions still valid?): [one-sentence answer, or "no frame issue"]
- Q5 (tools acquired since approach was conceived?): [one-sentence answer, or "no frame issue"]
- Concrete contradiction surfaced: yes / no
  [if yes, cite the contradiction]

**North Star Alignment:** X/5 -- [1-2 sentence justification]

**Work Area / Scope Evaluation:**
- [Area or file 1]: appropriately scoped / too large (suggest split into: X, Y) / too small (merge with: Z)
- [Area or file 2]: ...

**Phase Dependencies:** Aligned / [describe issue and which phase must complete first]

**Strategic Risks:** [list or "none identified"]

**Acceptance Criteria Issues (IMPLEMENTATION only):** [list or "none"]

**Lambda Deployment Completeness:** Complete / Missing [list missing steps]

**VP Executable Commands:** Complete / Missing commands for VP rows [list] / Missing pre/post-deploy tags [list]

**Closure Obligation (12l, follow-on plans):** N/A (not a follow-on) / Compliant / Missing [specifics]

**Tier Fitness (12m):** Compliant / REVISE -- [scope file] requires [tier] but plan declares [lower tier]

**Recommendation:** PROCEED / REVISE [with specific suggestions if REVISE]
```

14. If the recommendation is REVISE, list specific changes needed before implementation should begin.

---


## Quality Gate

Before outputting your critique, verify:
- [ ] You read EVERY file in the plan's scope (not just .md files)
- [ ] You can cite line numbers for call sites in source files
- [ ] You can cite line numbers for mocks in test files
- [ ] Your "Files Read" list matches the scope entry count

If any checkbox is false, go back and read the missing files before proceeding.
