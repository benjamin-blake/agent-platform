# Plan

## Intent
Optimise the three-tier agent workflow (`/plan` -> `/implement` -> `/develop-executor`) so that complex work is automatically routed through strategic scoping instead of producing monolithic implementation plans, prompts remain concise enough for LLM adherence, the RCA agent catches workarounds before they become recommendations, and relative complexity metrics prevent monolithic files and prompts from forming. This directly advances the North Star by making the self-improving feedback loop structurally resistant to the failure modes that have stalled executor progress.

## Plan Type
STRATEGIC

## Branch
agent/infra-workflow-optimization

## Phase
Phase-infra (infrastructure/tooling work supporting future phases)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/prompts/plan.prompt.md` | Modify | Add complexity routing (Step 5c) to enforce STRATEGIC for large scopes |
| `.github/prompts/implement.prompt.md` | Modify | Add graceful fallback for IMPLEMENTATION plans, quality gates for recs |
| `.github/prompts/develop-executor.prompt.md` | Modify | Remove invalid `applyTo`, extract constraints to instruction files, reduce to workflow-only |
| `.github/instructions/executor-supervisor-workflow.instructions.md` | Create | Extracted failure patterns, escalation protocol from develop-executor prompt |
| `.github/instructions/executor-supervisor-rules.instructions.md` | Create | Extracted core rules, commit policy, status values from develop-executor prompt |
| `.github/agents/rca-analyst.agent.md` | Modify | Add Phase 2b workaround detection with structural root-cause test |
| `scripts/validate.py` | Modify | Add AST-based relative complexity warnings (function count, import fan-out outliers) |
| `scripts/executor/plan.py` | Modify | Add planning-time complexity warning consumption |

## Bundled Recommendations
- **rec-337** (planning.prompt.md: require new dedicated test file when target test file exceeds 2000 lines) -- to be SUPERSEDED by Area E's relative metrics approach. The structural fix (outlier detection) replaces the arbitrary 2000-line threshold.
- **rec-023** (Split copilot_instructions.md into modular files) -- partially addressed by Area C's extraction of develop-executor constraints to instruction files. The broader copilot_instructions.md split remains a separate effort.

## Acceptance Criteria
- [ ] `/plan` produces STRATEGIC plans when scope exceeds 5 files or 8 steps, with explicit complexity assessment visible to the human
- [ ] `/implement` gracefully handles IMPLEMENTATION plans (offers conversion to STRATEGIC) instead of hard-stopping
- [ ] `/develop-executor` prompt is <=200 lines, with constraints in `.instructions.md` files that auto-attach via `applyTo`
- [ ] `/develop-executor` prompt has no `applyTo` in its frontmatter (invalid for `.prompt.md` files)
- [ ] `rca-analyst` output includes `workaround_flag` for each proposed rec, with structural root-cause justification
- [ ] `validate.py` reports relative complexity warnings (outlier detection) for code files, prompt files, and test files
- [ ] `validate.py` complexity check uses no hardcoded thresholds -- all limits derived from per-package statistics
- [ ] `python scripts/validate.py` passes
- [ ] All existing tests pass

## Constraints
- Python 3.12+, type hints required
- No Docker (Windows VM constraint)
- Shell commands must use bash syntax, not PowerShell
- `.prompt.md` files do NOT support `applyTo` -- only `.instructions.md` and `.agent.md` do
- `.instructions.md` `applyTo` triggers on file edits, not during conversational prompt invocation -- prompts that need instruction content during conversation must use explicit markdown links
- Existing JSONL schema must not change
- Decision 42 (Three-Tier Workflow Architecture) is the governing architectural decision
- The recommendations log audit (schema migration, stale rec triage, workaround identification) is a SEPARATE planning session -- not in scope here

## Context
- Decision 42 formalises the three-tier workflow but the prompts don't yet enforce it
- The PLAN-infra-executor-refactor.md (attached earlier) was produced as Plan Type: IMPLEMENTATION with 22 steps because `/plan` has no complexity routing -- it defaulted to IMPLEMENTATION instead of STRATEGIC
- rec-337 is a canonical example of the rca-analyst letting through a workaround (arbitrary 2000-line threshold) instead of identifying the structural cause (monolithic files forming due to lack of decomposition incentives)
- `develop-executor.prompt.md` has an invalid `applyTo` field in its YAML frontmatter that VS Code is ignoring with a warning
- Current prompt sizes: `/plan` 409 lines, `/develop-executor` 358 lines, `/implement` 138 lines, `rca-analyst` 105 lines
- The 4 existing `executor-*.instructions.md` files (217 lines total) demonstrate the extraction pattern already in use

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (Decision 42 in particular -- no conflicts)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Current prompt files read and understood (plan.prompt.md, implement.prompt.md, develop-executor.prompt.md, rca-analyst.agent.md)
- [ ] Current instruction files read (.github/instructions/executor-*.instructions.md)
- [ ] VS Code customisation primitives understood: `.prompt.md` supports `name`, `description`, `agent`, `model`, `tools` only; `.instructions.md` supports `applyTo` and `description`

## Work Areas

| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| **A: `/plan` complexity routing** | `.github/prompts/plan.prompt.md` | Add Step 5c complexity assessment after file identification. When scope exceeds 5 files or 8 estimated steps, the planner MUST use Plan Type: STRATEGIC with Work Areas. When within thresholds, IMPLEMENTATION is permitted but the planner must state the assessment explicitly. Remove IMPLEMENTATION as the default in the Step 7 template -- force an explicit choice referencing the Step 5c assessment. Add guidance on what makes a good Work Area (scope bounded, rationale clear, complexity estimated, dependencies between areas noted). | S |
| **B: `/implement` resilience and quality gates** | `.github/prompts/implement.prompt.md` | (1) When fed an IMPLEMENTATION plan, offer to convert to STRATEGIC by grouping steps into Work Areas instead of hard-stopping. (2) Add a per-rec quality gate before filing: validate acceptance command format (single backtick, no prose, no `python -c`), verify target file exists, check effort is <= M (flag if larger), verify context is self-contained (no references to "the plan" or "as discussed"). (3) Add completion message that references the full pipeline: `/plan` -> `/implement` -> `/develop-executor`. (4) Add step to check whether any scoped recs overlap with existing open recs in the log (dedup gate). | S |
| **C: `/develop-executor` prompt factoring** | `.github/prompts/develop-executor.prompt.md`, `.github/instructions/executor-supervisor-workflow.instructions.md`, `.github/instructions/executor-supervisor-rules.instructions.md` | (1) Remove invalid `applyTo` from prompt frontmatter. (2) Extract to `executor-supervisor-rules.instructions.md` (applyTo: `scripts/executor/**,scripts/execute_recommendation.py`): Core Rules 1-5, Status Values table, Edit Method constraints. (3) Extract to `executor-supervisor-workflow.instructions.md` (applyTo: `scripts/executor/**,scripts/execute_recommendation.py`): Failure Diagnosis table, Common Failure Patterns section, Escalation and Hotfix Protocol, Module Map, Environment Variables. (4) Prompt retains: Intent, Workflow Phases 1-6, Session Close Checklist. Add explicit `Read these instruction files before proceeding:` section with markdown links to the extracted files, so they load during conversational use (not just file-edit context). (5) Target: prompt <=200 lines, each instruction file <=150 lines. (6) Each instruction file must have a keyword-rich `description` field for on-demand discovery. | M |
| **D: `rca-analyst` workaround detection** | `.github/agents/rca-analyst.agent.md` | Add Phase 2b "Workaround Detection" between classification and rec quality review. For EACH proposed rec, apply three structural tests: (1) **Cause-vs-consequence test**: Does this rec address WHY the problematic condition exists, or only its downstream effects? Example: "require new test file when >2000 lines" addresses the consequence of large files, not why they grow large. (2) **Threshold elimination test**: If the rec proposes a numeric threshold or limit, what structural change would make the threshold unnecessary? Example: relative outlier detection eliminates the need for a hardcoded 2000-line limit. (3) **Prompt-vs-code test**: If the rec adds a rule to a prompt file, does the underlying code architecture make that rule necessary? If yes, propose a code-level structural fix instead. Add `workaround_flag: true/false` and `structural_alternative: string|null` fields to each entry in `revised_recs`. When `workaround_flag` is true, the supervisor must present the structural alternative to the human before filing. | S |
| **E: Relative complexity metrics in validate.py** | `scripts/validate.py`, `scripts/executor/plan.py` | (1) Add `validate_complexity()` function to validate.py that uses AST analysis to compute per-package statistics: public function count, import fan-out (distinct module imports), and for test files, `@patch` decorator count. Flag files >2 standard deviations above their package mean as warnings. No hardcoded thresholds -- all limits derived from the codebase itself. (2) For prompt/instruction files (`.prompt.md`, `.instructions.md`, `.agent.md`): count imperative statements (`must`, `never`, `always`, `do not`, `BANNED`, `CRITICAL`) as a proxy for rule density. Flag outliers. (3) Integrate as a WARNING-level check in validate.py (does not block CI, surfaces in preflight and planning). (4) In `scripts/executor/plan.py`: when generating a plan, if the target file has complexity warnings from the most recent validate run, inject a planning constraint: "Target file {path} has elevated complexity ({metric}). The plan should include a decomposition step if adding new functions/rules." (5) Supersede rec-337 with this structural approach. | M |
