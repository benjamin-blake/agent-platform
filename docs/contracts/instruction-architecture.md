# Instruction Architecture Contract

This document defines the 5 layers of the instruction architecture for agents interacting with this repository. It establishes clear boundary contracts to prevent duplication, reduce context bloat, and ensure consistency across the agent consumers (Claude Code interactive, executor, and legacy surfaces).

## Cross-Cutting Principle: Agent-First

All artefacts at all 5 layers are designed for agent loading efficiency, not human
readability. This constraint applies regardless of the layer or consumer.

- Prefer machine-parseable formats (YAML, structured tables) over narrative prose.
- Collocate semantic definitions with their enforcement counterparts -- one file is better
  than a machine-readable source plus a human-readable companion.
- A new file is warranted only when it has a distinct machine-parseable role that cannot
  be served by extending an existing source.

## The 5 Layers

### Layer 1: `GEMINI.md`
Universal rules shared by all consumers.
- **What goes here:** Code style, safety constraints, merge protocol, and operational data governance rules (e.g., Single Portal Invariant, ID Authority).
- **What does NOT go here:** Routing logic, project context, agent methodology, or the file router.

### Layer 2: `copilot-instructions.md` (Project Knowledge Base)
Project-specific knowledge loaded on-demand by interactive agents.
- **What goes here:** North Star goals, AWS configuration, the file router, recommendation schemas, and known gotchas.
- **What does NOT go here:** Workflow steps, agent methodology, or VS Code-specific features.

### Layer 3: `.claude/commands/` (Claude Code Slash Commands)
Thin orchestration scripts for the interactive workflows (canonical).
- **What goes here:** Step sequences that reference skills, including required virtual environment activation steps and explicit human confirmation gates.
- **What does NOT go here:** Deep methodology or project context.
- **Legacy mirror:** `.agents/workflows/` (Antigravity) is demoted to legacy alongside `.github/prompts/`; not synced, may be stale.

### Layer 4: `.claude/skills/` (Claude Code Skills)
Deep methodology for specific tasks (canonical).
- **What goes here:** Self-contained skill definitions invocable via the `Skill` tool. Must declare `required-context` in YAML frontmatter.
- **What does NOT go here:** Project context better suited for Layer 2.
- **Legacy mirror:** `.agents/skills/` (Antigravity) is demoted to legacy alongside `.github/agents/`; not synced, may be stale.

### Layer 5: `config/agent/executor/prompts/` (Executor Role Prompts)
Executor-specific prompts.
- **What goes here:** Minimal, task-specific context for autonomous execution.
- **What does NOT go here:** Universal rules or project context better suited for layers 1 or 2.

## Consumers

Different agents consume different layers of this architecture:

| Consumer | Consumes | Notes |
|----------|----------|-------|
| **Claude Code (Interactive)** | Layers 1, 2, 3, 4 | Reads `CLAUDE.md`/`AGENTS.md` automatically. Slash commands (`.claude/commands/`) load `docs/PROJECT_CONTEXT.md` and invoke skills (`.claude/skills/`) via the `Skill` tool. Canonical interactive surface. |
| **Antigravity Interactive (legacy)** | Layers 1, 2, legacy `.agents/` | Legacy. `.agents/workflows/` + `.agents/skills/` are no longer synced. |
| **Executor (Autonomous)** | Layers 1, 5 | Reads universal rules automatically. Execution scripts read role prompts and JIT contexts. |
| **Legacy VS Code** | Layers 1, 2, legacy prompts | Uses `.github/prompts/*.prompt.md` and `.github/agents/*.agent.md`. |

## Canonical Source of Truth

`.claude/commands/` and `.claude/skills/` are the canonical interactive workflow layer (Decision 76). Legacy files under `.agents/workflows/`, `.agents/skills/`, `.github/prompts/`, and `.github/agents/` are compatibility artefacts -- not synced and may remain stale by design.

When behaviour differs between layers, update `.claude/` first. Legacy compatibility files may then be updated or reduced to shims. Do not add new methodology to legacy `.agents/` or VS Code prompts unless it is also represented in `.claude/`.

## What Does NOT Go Where (Anti-Patterns)

| Anti-Pattern | Why it's wrong | Where it should go |
|--------------|----------------|--------------------|
| Routing logic in `GEMINI.md` | `GEMINI.md` is for universal rules only. Routing logic belongs in workflows. | Layer 3 (`.claude/commands/`) |
| VS Code features in `copilot-instructions.md` | `copilot-instructions.md` is shared; VS Code features are not. | Legacy VS Code prompts only |
| Methodology in `copilot-instructions.md` | Bloats the context window. | Layer 4 (`.claude/skills/`) |
| Project context in `GEMINI.md` | Project context should be loaded on-demand. | Layer 2 (`copilot-instructions.md`) |
| Missing `required-context` in SKILL.md | the skill loader needs to know what context to load. | Layer 4 (`.claude/skills/`) |
| Direct recommendation writes in workflows or skills | Bypasses ID authority, outbox handling, and SCD2 semantics. | Use `scripts/ops_data_portal.py` |
| Migrating legacy retrospective or step-validation subagents as-is | Preserves chat-based reconstruction instead of structured evidence. | Telemetry, verifier results, and state-machine transitions |
| Human-readable companion doc alongside machine-readable source | Creates a second surface that agents must sync; semantic context belongs as metadata fields in the machine-readable source | Extend the existing machine-readable source with description/semantics fields |
