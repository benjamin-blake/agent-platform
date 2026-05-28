# Behavioral Invariants Reference

This document defines behavioral invariants as reusable patterns for agent customization.
These invariants are declared in `## Behavioural Invariants` sections of prompt files
and validated by `scripts/prompt_compliance.py` against execution state.

## no_code_changes

**Purpose**: Constrains an agent to perform analysis or planning only, without making
any file modifications.

**Usage**: Add this invariant to agents that generate plans, perform audits, or conduct
reviews but should never edit code.

**Validation**: Currently enforced by the agent's system instructions only.
No automated post-session validation exists for this invariant.

**Example Declaration**:

```yaml
## Behavioural Invariants

no_code_changes: true
```

**Applies To**:
- Planning agents (`.github/prompts/plan.prompt.md`)
- Code review agents (`.github/agents/code-review.agent.md`)
- Plan critique agents (`.github/agents/plan-critique.agent.md`)
- Audit agents (`.github/prompts/scheduled/doc-freshness.prompt.md`)
- RCA analysts (`.github/agents/rca-analyst.agent.md`)
- Any agent whose role is purely analytical or advisory

**Enforcement**: When `no_code_changes: true` is set, the agent's system instructions
explicitly prohibit file edits. Compliance relies on the agent following instructions.
