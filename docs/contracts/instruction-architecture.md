# Instruction Architecture Contract

This document defines the 5 layers of the instruction architecture for agents interacting with this repository. It establishes clear boundary contracts to prevent duplication, reduce context bloat, and ensure consistency across the three agent consumers (executor, Antigravity interactive, legacy VS Code).

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

### Layer 3: `.agents/workflows/` (Antigravity Workflows)
Thin orchestration scripts for Antigravity.
- **What goes here:** Step sequences that reference skills, including required virtual environment activation steps and explicit human confirmation gates.
- **What does NOT go here:** Deep methodology or project context.

### Layer 4: `.agents/skills/` (Antigravity Skills)
Deep methodology for specific tasks.
- **What goes here:** Self-contained skill definitions invocable via `run_skill.py`. Must declare `required-context` in YAML frontmatter.
- **What does NOT go here:** VS Code-specific frontmatter (`model:`, `tools:`, `user-invocable:`).

### Layer 5: `config/agent/executor/prompts/` (Executor Role Prompts)
Executor-specific prompts.
- **What goes here:** Minimal, task-specific context for autonomous execution.
- **What does NOT go here:** Universal rules or project context better suited for layers 1 or 2.

## Consumers

Different agents consume different layers of this architecture:

| Consumer | Consumes | Notes |
|----------|----------|-------|
| **Antigravity Interactive** | Layers 1, 2, 3, 4 | Reads `GEMINI.md` automatically. Workflows load `copilot-instructions.md` and invoke skills. |
| **Executor (Autonomous)** | Layers 1, 5 | Reads `GEMINI.md` automatically. Execution scripts read role prompts and JIT contexts. |
| **Legacy VS Code** | Layers 1, 2, legacy prompts | Uses `.github/prompts/*.prompt.md` and `.github/agents/*.agent.md`. |

## Canonical Source of Truth

`.agents/workflows/` and `.agents/skills/` are the canonical interactive workflow layer. Legacy VS Code files under `.github/prompts/` and `.github/agents/` are compatibility artefacts. Any `.antigravity/workflows/` files are transitional and should either delegate to `.agents` or be removed once Antigravity can consume `.agents` directly.

When behaviour differs between layers, update `.agents` first. Legacy compatibility files may then be updated or reduced to shims. Do not add new methodology to legacy VS Code prompts unless it is also represented in `.agents`.

## What Does NOT Go Where (Anti-Patterns)

| Anti-Pattern | Why it's wrong | Where it should go |
|--------------|----------------|--------------------|
| Routing logic in `GEMINI.md` | `GEMINI.md` is for universal rules only. Routing logic belongs in workflows. | Layer 3 (`.agents/workflows/`) |
| VS Code features in `copilot-instructions.md` | `copilot-instructions.md` is shared; VS Code features are not. | Legacy VS Code prompts only |
| Methodology in `copilot-instructions.md` | Bloats the context window. | Layer 4 (`.agents/skills/`) |
| Project context in `GEMINI.md` | Project context should be loaded on-demand. | Layer 2 (`copilot-instructions.md`) |
| Missing `required-context` in SKILL.md | `run_skill.py` needs to know what context to load. | Layer 4 (`.agents/skills/`) |
| Direct recommendation writes in workflows or skills | Bypasses ID authority, outbox handling, and SCD2 semantics. | Use `scripts/ops_data_portal.py` |
| Migrating legacy retrospective or step-validation subagents as-is | Preserves chat-based reconstruction instead of structured evidence. | Telemetry, verifier results, and state-machine transitions |
| Human-readable companion doc alongside machine-readable source | Creates a second surface that agents must sync; semantic context belongs as metadata fields in the machine-readable source | Extend the existing machine-readable source with description/semantics fields |
