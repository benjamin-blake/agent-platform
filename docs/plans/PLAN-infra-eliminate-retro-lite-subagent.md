# Plan

## Intent

Reduce implementation session token costs and complexity by eliminating redundant subagent calls. This directly serves the North Star ("self-improving automated trading system") by making the workflow feedback loop more efficient — friction is still captured, but without the overhead of reconstructing context for a subagent that adds no information the parent agent doesn't already have.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-eliminate-retro-lite-subagent

## Phase

Infra (workflow infrastructure, not tied to trading system phases)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `.github/prompts/implement.prompt.md` | Modify | Remove interleaved retro-lite todos from Step 5; replace @retro-lite invocation in Step 6 with parent-direct write pattern |
| `.github/agents/retro-lite.agent.md` | Modify | Update "When to Use" section to deprecate per-step usage; clarify agent is optional for manual debugging only |
| `scripts/prompt_compliance.py` | Modify | Update `retro_lite_per_step` invariant check to validate parent-direct writes instead of subagent calls |
| `tests/test_prompt_compliance.py` | Modify | Update tests if prompt_compliance.py validation logic changes |

## Acceptance Criteria

- [ ] `implement.prompt.md` Step 5 no longer creates `(retro-lite)` interleaved todo items
- [ ] `implement.prompt.md` Step 6 contains parent-direct friction capture pattern (no @retro-lite invocation)
- [ ] `retro-lite.agent.md` "When to Use" section states per-step usage is deprecated
- [ ] Behavioural Invariants YAML updated to reflect parent-direct pattern
- [ ] `scripts/prompt_compliance.py` validates the new pattern (or invariant is removed if no longer needed)
- [ ] All existing tests pass (`pytest tests/ -q`)
- [ ] Validation passes (`python scripts/validate.py`)

## Constraints

- Must preserve friction capture — zero information loss
- Existing `run_retro_lite.py --append` script must be the persistence mechanism
- End-of-session friction capture (Step 8) already uses parent-direct pattern — this extends that pattern to per-step
- No changes to JSONL schema or log file format

## Context

- **rec-012** from CLI migration roadmap (PLAN-infra-cli-migration-plan.md)
- **Decision 29** (Friction-Free Implementation Pattern) established the checkpoint-per-step pattern; this extends it
- **Decision 28** (Execution State Checkpoint) defines the checkpoint save_checkpoint call that happens after each step
- Current flow: Step 6 saves checkpoint, invokes @step-validator, invokes @retro-lite
- New flow: Step 6 saves checkpoint, invokes @step-validator, parent writes friction directly
- End-of-session Step 8 already uses parent-direct pattern — this makes per-step consistent

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Modify `.github/prompts/implement.prompt.md` Step 5** — Remove the instruction to create interleaved `(retro-lite)` todo items. The todo list should contain only `Step N: <description>` items (one per Ordered Execution Step), not the paired `Step N (retro-lite)` items.

2. **Modify `.github/prompts/implement.prompt.md` Step 6** — Replace the @retro-lite invocation block (item 7 in the current numbered list) with parent-direct friction capture. The new pattern should:
   - After @step-validator returns, parent evaluates whether friction occurred during the step
   - If friction: build JSON entry with timestamp, session, friction description, missing_context, deviation, suggested_fix
   - Call `python scripts/run_retro_lite.py --append '<json>'` to persist
   - If no friction: skip the call (do not invoke script with "none" fields)
   - Remove the `Mark the Step N (retro-lite) todo` instruction since those todos no longer exist

3. **Update Behavioural Invariants YAML in `implement.prompt.md`** — Change `retro_lite_per_step: true` comment to clarify it means parent-direct writes, not subagent calls. Example: `# retro_lite_per_step: true — parent writes friction directly after each step (not via @retro-lite subagent)`

4. **Modify `.github/agents/retro-lite.agent.md` "When to Use" section** — Add deprecation notice: "**DEPRECATED for per-step capture:** As of rec-012, per-step friction is captured directly by the parent agent. This agent is retained only for manual debugging or if the parent agent wants explicit subagent validation of a complex friction scenario."

5. **Review `scripts/prompt_compliance.py`** — Check how `retro_lite_per_step` is validated. If it checks for @retro-lite invocation patterns, update to check for parent-direct `run_retro_lite.py --append` calls instead. If the check is too brittle to maintain, mark the invariant as deprecated in the YAML and remove the check.

6. Run `pytest tests/ -q` — all tests must pass before proceeding

7. Run `python scripts/validate.py` — must exit 0

8. Report what was implemented and any design decisions made during implementation
