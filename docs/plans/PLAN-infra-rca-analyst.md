# Plan

## Intent
Ensure the self-improvement loop targets the SYSTEM architecture, not just tactical fixes. Add an Opus-powered RCA subagent that the Sonnet supervisor can invoke to analyze whether friction and filed recs are treating symptoms vs. deeper infrastructure design problems.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-rca-analyst

## Phase
Infra/tooling (cross-phase, supports North Star)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/agents/rca-analyst.agent.md` | Create | New Opus-powered RCA subagent |
| `.github/prompts/develop-executor.prompt.md` | Modify | Add `@rca-analyst` injection points after Phase 4 and after 2nd failure |
| `.github/copilot-instructions.md` | Modify | Add agent to File Router table |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `.github/agents/rca-analyst.agent.md` exists with `## Intent` section (required by validate.py)
- [ ] Agent has mandatory context loading gate (reads transcripts, telemetry, triage summary before analysis)
- [ ] Agent returns structured JSON output (root cause classifications + revised recs)
- [ ] `develop-executor.prompt.md` has `@rca-analyst` invocation after Phase 4 (conditional on friction)
- [ ] `develop-executor.prompt.md` has `@rca-analyst` invocation after 2nd failure (optional, before attempt 3)
- [ ] File Router in `copilot-instructions.md` includes `rca-analyst.agent.md`
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Agent must be Opus (`model: Claude Opus 4.5 (copilot)`) per discussion
- Supervisor stays on Sonnet — only the subagent is upgraded
- Agent is read-only (no file edits) — returns structured findings for supervisor to file
- Agent must not be user-invocable (internal subagent only)
- **Cost control:** Opus is premium. Phase 4b is only invoked when friction occurred (failures or filed friction recs). Zero-friction sessions skip RCA entirely.

## Context
- **Discussion context:** The Sonnet supervisor does triage (what broke) but not RCA (why this class of thing keeps breaking). Friction recs tend to be quick fixes rather than upstream fixes. See transcript excerpt in original request.
- **Pattern reference:** plan-critique.agent.md has a thorough mandatory context loading gate (Phase 1) — use same pattern
- **Free agents:** This is NOT a free agent (Opus is premium). Use judiciously.
- **Model naming:** Use `Claude Opus 4.5 (copilot)` format per existing agents

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Create `.github/agents/rca-analyst.agent.md`** with this structure:
   - YAML frontmatter: `name: rca-analyst`, `description: "Use when: ..."`, `model: Claude Opus 4.5 (copilot)`, `tools: ['read', 'search']`, `user-invocable: false`
   - `## Intent` section: Reflect on whether friction is due to deeper infrastructure design problems. In a recursive self-improvement loop, ensure the SYSTEM is improving, not just the process.
   - `## Phase 1: Load Context (MANDATORY)` — must read:
     - All transcript paths provided by caller
     - `logs/.execution-step-telemetry.jsonl` (per-step executor telemetry)
     - `logs/.session-telemetry.jsonl` (unified session telemetry for broader patterns)
     - `logs/.recommendations-log.jsonl` (to check for duplicates and see filed recs)
     - Triage summary table provided by caller
   - `## Phase 2: Root Cause Classification` — for each failure, classify as:
     - Prompt deficiency (which prompt, what's missing)
     - Architectural gap (executor design, missing hook)
     - Model capability limit (Haiku vs Sonnet vs Opus)
     - One-off / environmental
   - `## Phase 3: Rec Quality Review` — for each filed friction rec:
     - Is it treating a symptom? If yes, propose upstream alternative
     - Cross-reference against historical telemetry for recurrence patterns
   - `## Phase 4: Structured Output` — return JSON object with:
     - `root_cause_classifications`: array of `{failure_id, classification, evidence, upstream_fix}`
     - `revised_recs`: array of rec JSON objects (replacements/additions)
     - `systemic_issues`: array of cross-run patterns warranting higher-priority recs

2. **Modify `.github/prompts/develop-executor.prompt.md`** — add Phase 4b after Phase 4:
   ```markdown
   ### Phase 4b: Root Cause Analysis (Conditional)

   **Skip this phase if:** All recs succeeded AND no friction recs are being filed. In this case, proceed directly to Phase 5.

   **Invoke `@rca-analyst` if:** Any rec failed, OR you are filing one or more friction recs.

   Pass to the subagent:
   - Summary table from Phase 4 (rec ID, outcome, transcript paths)
   - List of friction recs you plan to file
   - Triage observations from Friction Capture

   Wait for the subagent to return.

   **Validate JSON output:** Confirm the response contains `root_cause_classifications`, `revised_recs`, and `systemic_issues` keys. If malformed, note in Phase 6 review and proceed with original recs.

   Review its `root_cause_classifications`:
   - If any classification is "prompt deficiency" or "architectural gap", the subagent's `upstream_fix` takes priority over your symptom-level rec
   - Replace your filed recs with the subagent's `revised_recs` where applicable
   - Add any `systemic_issues` to the Phase 6 Priority Actions list
   ```

3. **Modify `.github/prompts/develop-executor.prompt.md`** — add optional RCA invocation in Escalation section after Attempt 2:
   ```markdown
   2b. **(Optional) If 2nd failure is on the same underlying issue**, invoke `@rca-analyst` with both failure transcripts before Attempt 3. If the subagent identifies an upstream fix (e.g., planning prompt deficiency), apply that fix first rather than retry with `--skip-critique`.
   ```

4. **Modify `.github/copilot-instructions.md`** — add to File Router table after `scope-guard.agent.md`:
   ```markdown
   | RCA analyst agent (Opus) | [.github/agents/rca-analyst.agent.md](./agents/rca-analyst.agent.md) |
   ```

5. Run `python scripts/validate.py` — must exit 0

6. Report what was implemented and confirm all Acceptance Criteria are met
