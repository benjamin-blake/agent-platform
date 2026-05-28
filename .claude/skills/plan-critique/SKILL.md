---
name: plan-critique
description: "Use when: critique a plan, challenge assumptions, review docs/plans/PLAN-{slug}.md before implementation. Mandatory gate between planning and implementation."
required-context:
  - docs/PROJECT_CONTEXT.md
  - docs/ROADMAP-PRODUCT.md
  - docs/ROADMAP-PLATFORM.yaml
  - docs/DECISIONS.md
---

## Intent

Challenge PLAN-*.md from a different perspective than the model that wrote it. Evaluate strategic alignment, decision consistency, and work area scoping before implementation begins.

This is a BLOCKING gate. The critique must assess whether the plan is strategically sound, well-bounded, and aligned with the North Star. A superficial review that only checks formatting is unacceptable.

---

## Steps

### Phase 1: Load Context (MANDATORY - Do Not Skip)

1. Read the ENTIRE plan file path provided by the caller (e.g., `docs/plans/PLAN-infra-parallel-workflow.md`). The caller passes this path explicitly — do not default to `docs/plans/PLAN.md`. If no path was provided, search `docs/plans/` for files matching `PLAN-*.md` and read the most recently modified one.

2. Read `docs/PROJECT_CONTEXT.md` (for North Star and rules).

3. Read `docs/ROADMAP-PRODUCT.md` (for product phase alignment) and `docs/ROADMAP-PLATFORM.yaml` (for platform tier item alignment).

4. Read `docs/DECISIONS.md` (for conflicts with prior decisions).

5. **For IMPLEMENTATION plans:** Read the files listed in the `## Scope` table to verify the plan's accuracy. For STRATEGIC plans, this is not required — Work Areas are high-level and do not require file-level verification.

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

12b. **Lambda deployment completeness (IMPLEMENTATION plans only):** If any file in the Scope table is Lambda-packaged (under `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, or in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`), the Ordered Execution Steps MUST include: (a) a `build_lambda.py --deploy` step, (b) a smoke-test step using `run_scheduled_agent.py --smoke-test`, and (c) model ID validation against `docs/contracts/inference-provider.md` if model IDs are changed. If any are missing, recommend REVISE. Exception: if `docs/DECISIONS.md` contains an active Decision 67 (Lambda deployment deferred pending telemetry readiness), a step explicitly marked `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)` is acceptable in lieu of active deployment steps -- output a WARN (not REVISE) noting the deferred deployment debt. Reference: Decision 47, Decision 67, Step 4 (Lambda Deployment Assessment) of plan.prompt.md.

12c. **Verification Plan executable command check (IMPLEMENTATION plans only):** Every row in the `## Verification Plan` table MUST have a `Command` column containing a literal executable shell command or Python one-liner. FAIL if any VP step has only prose in the Action column with no executable Command. For V3 plans, every VP step must be tagged `[pre-deploy]` or `[post-deploy]`. If either check fails, recommend REVISE with the specific VP rows that need commands or tags added.

12d. **STRATEGIC plan gate:** If the plan's `## Plan Type` is `STRATEGIC` AND `docs/DECISIONS.md` contains an active Decision 67, recommend REVISE with: "STRATEGIC plans are blocked while Decision 67 is active (telemetry tables not yet confirmed operational). Convert to an IMPLEMENTATION plan or wait for Decision 67 reversal."

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

**Recommendation:** PROCEED / REVISE [with specific suggestions if REVISE]
```

14. If the recommendation is REVISE, list specific changes needed before implementation should begin.

---


## Quality Gate

Before outputting your critique, verify:
- [ ] You read EVERY file in the Scope table (not just .md files)
- [ ] You can cite line numbers for call sites in source files
- [ ] You can cite line numbers for mocks in test files
- [ ] Your "Files Read" list matches the Scope table count

If any checkbox is false, go back and read the missing files before proceeding.
