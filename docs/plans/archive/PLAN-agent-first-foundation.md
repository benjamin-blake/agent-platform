# Plan

## Intent
Wire agent-first design as a persistent architectural constraint into every instruction layer
this repository uses -- ambient (CLAUDE.md, GEMINI.md), on-demand (PROJECT_CONTEXT.md,
instruction-architecture.md), and methodology (both .claude/skills/ and .agents/skills/) --
eliminating the pattern of creating separate human-readable companion documents alongside
machine-readable sources, and reducing future planning session context overhead structurally
rather than by convention.

## Plan Type
IMPLEMENTATION

## Classification Override Note
This plan has 9 scope files, which exceeds the 5-file IMPLEMENTATION threshold in the
planning skill. It is classified IMPLEMENTATION by explicit human decision for two reasons:

1. **Executor is unusable.** rec-612 (37 failing tests in tests/test_scheduled_agent_handler.py)
   blocks the executor from running. STRATEGIC plans require the executor to scope Work Areas
   into atomic recommendations before implementation can begin. With the executor down, a
   STRATEGIC classification makes this plan unexecutable on any foreseeable timeline.

2. **Complexity does not warrant STRATEGIC.** The 5-file threshold guards against ambiguity
   and scoping judgment, not raw file count. All 9 changes in this plan are text insertions
   of near-identical content into mirror file pairs (GEMINI.md + CLAUDE.md, four skill files
   two-by-two). No scoping judgment is required from the implementing agent. The exact
   content to insert is fully specified in the Ordered Execution Steps.

The implementing agent must not reclassify this plan as STRATEGIC.

## Verification Tier
V1

## Branch
agent/agent-first-foundation

## Phase
Platform: cross-cutting instruction architecture (no roadmap phase dependency)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `GEMINI.md` | Modify | Add Agent-First Repository section to universal Layer 1 (Antigravity consumer) |
| `CLAUDE.md` (root) | Modify | Add Agent-First Repository section to ambient Layer 1 (Claude Code consumer) |
| `docs/PROJECT_CONTEXT.md` | Modify | Add agent-first bullet to Rules section |
| `docs/contracts/instruction-architecture.md` | Modify | Add cross-cutting principle section and anti-pattern table entry |
| `.claude/skills/planning/SKILL.md` | Modify | Add Documentation Artefact Design rule (Claude Code planning methodology) |
| `.claude/skills/implement/SKILL.md` | Modify | Add Documentation Artefact Design rule (Claude Code implement methodology) |
| `.agents/skills/planning/SKILL.md` | Modify | Add Documentation Artefact Design rule (canonical Antigravity planning methodology) |
| `.agents/skills/implement/SKILL.md` | Modify | Add Documentation Artefact Design rule (canonical Antigravity implement methodology) |
| `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | Modify | Deprecate human-readable briefing doc pattern; name ops.yaml extended contract as standard |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] GEMINI.md and CLAUDE.md each contain "Agent-First Repository" section with all four
      mandated keywords: machine-parseable, human-readable, query an agent, companion
- [ ] PROJECT_CONTEXT.md Rules section contains "Agent-First" and references CLAUDE.md
- [ ] instruction-architecture.md has a cross-cutting principle section before "The 5 Layers"
      containing the anti-pattern entry for human-readable companion documents
- [ ] All four skill files (.claude and .agents, planning and implement) contain a
      "Documentation Artefact Design" section naming ops.yaml extended contract as canonical
- [ ] DQ_REMEDIATION_METHODOLOGY.md Agent Session Protocol contains a legacy-artefact note
      deprecating the briefing doc pattern and naming ops.yaml extended contract as standard

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | static | CLAUDE.md encodes all required agent-first keywords | `.venv/Scripts/python.exe -c "c=open('CLAUDE.md').read(); needed=['Agent-First Repository','machine-parseable','query an agent','companion']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add missing keywords to Agent-First Repository section |
| 2 | static | GEMINI.md encodes all required agent-first keywords | `.venv/Scripts/python.exe -c "c=open('GEMINI.md').read(); needed=['Agent-First Repository','machine-parseable','query an agent','companion']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add Agent-First Repository section to GEMINI.md |
| 3 | static | PROJECT_CONTEXT.md references agent-first | `.venv/Scripts/python.exe -c "c=open('docs/PROJECT_CONTEXT.md').read(); assert 'Agent-First' in c and 'CLAUDE.md' in c, 'Missing agent-first reference or CLAUDE.md pointer'"` | No AssertionError | Add agent-first bullet to Rules section |
| 4 | static | instruction-architecture.md has cross-cutting principle | `.venv/Scripts/python.exe -c "c=open('docs/contracts/instruction-architecture.md').read(); needed=['Agent-First','machine-parseable','companion']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add cross-cutting principle section |
| 5 | static | All four skill files contain Documentation Artefact Design section | `.venv/Scripts/python.exe -c "files=['.claude/skills/planning/SKILL.md','.claude/skills/implement/SKILL.md','.agents/skills/planning/SKILL.md','.agents/skills/implement/SKILL.md']; needed=['Documentation Artefact Design','machine-parseable','companion','ops.yaml extended']; bad=[f for f in files if any(k not in open(f).read() for k in needed)]; assert not bad, f'Missing content in: {bad}'"` | No AssertionError | Add Documentation Artefact Design section to each failing skill file |
| 6 | static | DQ methodology deprecates briefing doc pattern | `.venv/Scripts/python.exe -c "c=open('docs/dq/DQ_REMEDIATION_METHODOLOGY.md').read(); needed=['ops.yaml extended','legacy artefact','description','semantics']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Update Agent Session Protocol to reference new pattern |

## Constraints
- No source code changes, data writes, or YAML check modifications in this plan
- No new files created -- this plan only modifies existing ones
- The agent-first principle must itself be expressed concisely without narrative padding;
  additions to each file must be terse and structured, not explanatory prose
- Skill modifications must slot into existing section structure -- do not restructure skill files
- The content added to GEMINI.md and CLAUDE.md must be identical (both are Layer 1)
- The content added to all four skill files must be identical except for one sentence adapted
  to the implementation phase context in the implement skill files
- This plan does not apply the ops.yaml extended contract pattern to any specific fields;
  that is the follow-on plan (dq-phase4-session-map)
- Do not reclassify this plan as STRATEGIC -- see Classification Override Note above

## Context
- Root cause: 134,927-token planning session discovery overhead traced to semantic definitions
  scattered across narrative docs (remediation briefing, PROJECT_CONTEXT.md field sections)
  with no stated agent-first design constraint to prevent new narrative docs accumulating
- Decision 58 (2026-05-01): .agents/skills/ is the canonical interactive workflow layer for
  Antigravity; .claude/skills/ serves Claude Code. Both sets must carry the same methodology
  to avoid consumer drift. Both sets are in scope.
- GEMINI.md is Layer 1 for Antigravity + executor consumers per instruction-architecture.md.
  CLAUDE.md is Layer 1 for Claude Code. Both require the principle; content is identical.
- The follow-on plan (dq-phase4-session-map) applies the ops.yaml extended contract pattern
  to ops_recommendations fields; that plan depends on this one being merged first
- DQ_REMEDIATION_METHODOLOGY.md deprecation note applies to NEW tables only; the existing
  ops-recommendations-remediation-briefing.md is a legacy artefact superseded by the ops.yaml
  extension in the follow-on plan -- do not delete it in this session
- rec-612 (executor unusable): 37 tests failing in tests/test_scheduled_agent_handler.py;
  this is the blocker that necessitates IMPLEMENTATION classification for this plan

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Modify `GEMINI.md` -- add Agent-First Repository section**

   Insert a new section immediately after the memory or branching rules section (whichever
   appears last before any operational runbooks). Exact content:

   ```
   ## Agent-First Repository

   This repository is designed for agent consumption. All artefacts -- docs, configs, YAMLs,
   skills, slash commands -- are optimised for agent loading efficiency, not human readability.

   - Prefer machine-parseable formats (YAML, structured tables) over narrative prose.
   - Collocate semantic definitions with their enforcement counterparts in a single file.
     One file is better than two files covering the same subject from different angles.
   - Narrative summaries are query results, not stored artefacts. When a human wants a
     summary, they ask an agent -- do not store human-readable summaries as primary artefacts.
   - Anti-pattern: creating a human-readable companion document alongside a machine-readable
     source. This produces a second surface that agents must sync, which is drift by design.
   - When two design approaches are equally valid and one is more machine-parseable, choose
     machine-parseable.
   ```

2. **Modify `CLAUDE.md` (root) -- add Agent-First Repository section**

   Insert the identical section (same content as Step 1) immediately after the
   `## Memory policy` section.

3. **Modify `docs/PROJECT_CONTEXT.md` -- add agent-first bullet to Rules section**

   Append one bullet to the existing `## Rules` list:

   ```
   - **Agent-First:** This repository is designed for agent consumption. Artefacts at all
     layers are optimised for agent loading efficiency. Full principle and anti-patterns:
     `CLAUDE.md` section "Agent-First Repository".
   ```

4. **Modify `docs/contracts/instruction-architecture.md` -- add cross-cutting principle**

   Insert a new section `## Cross-Cutting Principle: Agent-First` immediately before
   `## The 5 Layers`. Exact content:

   ```
   ## Cross-Cutting Principle: Agent-First

   All artefacts at all 5 layers are designed for agent loading efficiency, not human
   readability. This constraint applies regardless of the layer or consumer.

   - Prefer machine-parseable formats (YAML, structured tables) over narrative prose.
   - Collocate semantic definitions with their enforcement counterparts -- one file is better
     than a machine-readable source plus a human-readable companion.
   - A new file is warranted only when it has a distinct machine-parseable role that cannot
     be served by extending an existing source.
   ```

   Also add one row to the Anti-Patterns table at the end of the file:

   ```
   | Human-readable companion doc alongside machine-readable source | Creates a second surface
     that agents must sync; semantic context belongs as metadata fields in the machine-readable
     source | Extend the existing machine-readable source with description/semantics fields |
   ```

5. **Modify `.claude/skills/planning/SKILL.md` -- add Documentation Artefact Design section**

   Insert immediately after the `## Suggest Aligned Recommendations` section:

   ```
   ## Documentation Artefact Design

   This repository is agent-first. When a plan creates or modifies documentation artefacts,
   apply these rules:

   - Prefer extending an existing machine-readable source over creating a new document.
   - A new file is warranted only when it has a distinct machine-parseable role (e.g., a
     decision manifest YAML, a registry YAML). Never create a human-readable companion
     alongside a machine-readable source -- that produces drift by design.
   - Canonical field documentation pattern: ops.yaml extended contract. Add `description`
     and `semantics` metadata fields directly to the column entry in ops.yaml or
     telemetry.yaml. These fields are ignored by the DQ runner and consumed by agents.
     Do not create a separate briefing doc for the same information.
   - When a plan step proposes a new document, ask: "Could this information be a metadata
     field in an existing YAML?" If yes, prefer that over a new file.
   ```

6. **Modify `.claude/skills/implement/SKILL.md` -- add Documentation Artefact Design section**

   Insert immediately after the `## Preflight Constraints` section. Content is identical
   to Step 5 except the opening sentence reads:

   ```
   ## Documentation Artefact Design

   This repository is agent-first. When implementing documentation changes, apply these rules:
   ```

   (remaining bullet points identical to Step 5)

7. **Modify `.agents/skills/planning/SKILL.md` -- add Documentation Artefact Design section**

   Locate the section equivalent to `## Suggest Aligned Recommendations` in this file and
   insert the identical content from Step 5 immediately after it.

8. **Modify `.agents/skills/implement/SKILL.md` -- add Documentation Artefact Design section**

   Locate the section equivalent to `## Preflight Constraints` in this file and insert
   the identical content from Step 6 immediately after it.

9. **Modify `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` -- update Agent Session Protocol**

   In the `## Agent Session Protocol` section, insert the following block immediately
   after step `(b)` (the decision manifest load step):

   ```
   (b2) Field contract authority: `config/data_quality/ops.yaml` (or `telemetry.yaml`) is
        the canonical field contract. The `description` and `semantics` metadata fields within
        each column entry are the field's semantic definition -- consumed by agents, ignored
        by the DQ runner. The separate human-readable briefing doc pattern
        (e.g., `docs/dq/ops-recommendations-remediation-briefing.md`) is a legacy artefact
        created before the agent-first contract was established. Do not create new briefing
        docs for new tables. Add field context as `description` + `semantics` fields in the
        YAML directly. The decision manifest YAML remains the remediation state authority.
   ```

10. **Execute Verification Plan** -- run all 6 VP steps in order. Loop until all pass.

11. **Report**: 9 files modified, 0 files created, agent-first principle wired into Layer 1
    (GEMINI.md + CLAUDE.md), Layer 2 (PROJECT_CONTEXT.md + instruction-architecture.md),
    Layer 4 (all four skill files), and DQ methodology.
