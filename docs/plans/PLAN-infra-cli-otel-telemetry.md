# Plan

## Intent

Validate and document the GitHub Copilot CLI session features that will power the repository's self-improvement feedback loop. This directly serves the North Star ("self-improving automated trading system") by establishing the telemetry, transcript, and chronicle infrastructure needed for automated friction capture, instruction refinement, and cost tracking.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-cli-otel-telemetry

## Phase

Infra (workflow infrastructure, not tied to trading system phases)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/GETTING_STARTED.md` | Modify | Add "CLI Telemetry & Session Features" section documenting OTel setup, transcript export, chronicle commands |
| `docs/DECISIONS.md` | Modify | Add Decision 30 documenting CLI session feature validation findings |
| `logs/transcripts/` | Create | Directory for session transcript exports |
| `.gitignore` | Modify | Add patterns for OTel logs and transcripts (track structure, ignore content if large) |

## Acceptance Criteria

- [ ] OTel telemetry validated: `COPILOT_OTEL_FILE_EXPORTER_PATH` produces JSONL with token counts and cost fields
- [ ] Session transcript export validated: `/share file` produces readable Markdown transcript
- [ ] Chronicle standup validated: `/chronicle standup` produces session summary
- [ ] Chronicle tips validated: `/chronicle tips` produces personalized recommendations
- [ ] Chronicle improve validated: `/chronicle improve` proposes instruction changes
- [ ] Session resume validated: `--continue` and `--resume` work as documented
- [ ] Session history queries validated: Free-form questions about past sessions work
- [ ] All working features documented in `docs/GETTING_STARTED.md`
- [ ] All findings (working, broken, limitations) documented in `docs/DECISIONS.md` Decision 30
- [ ] `logs/transcripts/` directory exists with README explaining structure

## Constraints

- Chronicle commands require `--experimental` flag or `/experimental on` — document this requirement
- Must run actual CLI invocations to validate features (no speculation)
- Schema documentation must be based on observed output, not assumed structure
- Do not integrate features into prompts until validated (this plan validates; integration is future work)

## Context

- **rec-005** (OTel export) is the core dependency for rec-006, rec-007, rec-008, rec-026, rec-029
- **rec-006** (--share transcripts) depends on rec-005
- **rec-007** (/chronicle improve) depends on rec-005
- **rec-008** (/chronicle tips replacing friction_analysis.py) depends on rec-005
- This plan validates the foundation; downstream recommendations will integrate validated features
- CLI session data is stored locally — no cloud dependency for these features

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `logs/transcripts/` directory with README** — Create the directory structure for session transcript storage. Add `logs/transcripts/README.md` explaining: purpose (session transcript archive), naming convention (`session-{slug}-{timestamp}.md`), and archival policy placeholder.

2. **Update `.gitignore`** — Add patterns to manage CLI telemetry files:
   - Track `logs/.copilot-otel.jsonl` (small, useful for cost analysis)
   - Track `logs/transcripts/README.md` (structure documentation)
   - Consider ignoring large transcript files with note about S3/LFS archival

3. **Validate OTel telemetry export** — Run a minimal CLI invocation with OTel export enabled:
   ```bash
   COPILOT_OTEL_FILE_EXPORTER_PATH=logs/.copilot-otel.jsonl OTEL_SERVICE_NAME=agent-platform copilot -p "What is 2+2?" -s --no-ask-user
   ```
   Examine `logs/.copilot-otel.jsonl` and document the actual span structure including: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `github.copilot.cost`, tool execution spans.

4. **Validate session transcript export** — Run an interactive session and export transcript:
   ```bash
   copilot --experimental
   # In session: /share file logs/transcripts/test-transcript.md
   # Exit session
   ```
   Verify the Markdown file contains: prompts, responses, timestamps, tool calls.

5. **Validate /chronicle standup** — Run chronicle standup to generate session summary:
   ```bash
   copilot --experimental
   # In session: /chronicle standup
   ```
   Document output format: branches worked on, completion status, PR references.

6. **Validate /chronicle tips** — Run chronicle tips for personalized recommendations:
   ```bash
   copilot --experimental
   # In session: /chronicle tips
   ```
   Document output format: numbered tips, usage pattern analysis, feature suggestions.

7. **Validate /chronicle improve** — Run chronicle improve for instruction suggestions:
   ```bash
   copilot --experimental
   # In session: /chronicle improve
   ```
   Document output format: friction signals found, proposed instruction changes, apply/reject workflow.

8. **Validate session resume** — Test session continuation:
   ```bash
   # Start a session, note session ID, exit
   copilot --experimental
   # In session: /session (note the ID)
   # Exit
   # Resume:
   copilot --continue  # Most recent session
   copilot --resume    # Session picker
   ```
   Document: Does context persist? Can you reference prior conversation?

9. **Validate session history queries** — Test free-form questions about past sessions:
   ```bash
   copilot --experimental
   # In session: "What did I work on yesterday?"
   # In session: "Have I worked on anything related to telemetry recently?"
   ```
   Document: Query accuracy, scope (all repos vs current), response quality.

10. **Document findings in DECISIONS.md** — Add Decision 30: CLI Session Feature Validation. Structure:
    - **Working features:** Each feature with observed behavior and limitations
    - **Experimental requirements:** Which features need `--experimental`
    - **Schema documentation:** OTel span structure, transcript format
    - **Integration recommendations:** Which features to integrate and how

11. **Update docs/GETTING_STARTED.md** — Add "CLI Telemetry & Session Features" section covering:
    - OTel environment variables and setup
    - Session transcript export commands
    - Chronicle commands (with experimental flag note)
    - Session resume/continue commands
    - Schema reference (link to Decision 30 for details)

12. Run `pytest tests/ -q` — all tests must pass before proceeding

13. Run `python scripts/validate.py` — must exit 0

14. Report what was implemented, which features work, which have limitations, and any unexpected findings
