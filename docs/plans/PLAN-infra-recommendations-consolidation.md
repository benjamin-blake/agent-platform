# Plan

## Intent

Establish a single source of truth for recommendations by consolidating on JSONL and completing telemetry capture infrastructure. This directly serves the North Star by enabling reliable, auditable automation of the self-improvement loop — prerequisite for autonomous low-risk recommendation execution.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-recommendations-consolidation

## Phase

Infra (workflow infrastructure)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| tests/test_copilot_wrapper.py | Modify | Add test for transcript_path parameter |
| scripts/copilot_wrapper.py | Modify | Add `--share` flag for transcript capture |
| scripts/execute_recommendation.py | Modify | Pass transcript paths to copilot_call() |
| scripts/migrate_recommendations.py | Delete | No longer needed (MD files removed) |
| tests/test_migrate_recommendations.py | Delete | Tests for removed script |
| docs/RECOMMENDATIONS.md | Delete | JSONL is now single source of truth |
| docs/RECOMMENDATIONS_ARCHIVE.md | Delete | JSONL tracks status field |
| .gitignore | Modify | Track .copilot-otel.jsonl (remove from ignore) |
| .github/copilot-instructions.md | Modify | Update File Router (remove MD refs, add OTel) |
| .github/agents/code-review.agent.md | Modify | Write findings to JSONL not MD |
| .github/agents/retrospective.agent.md | Modify | Reference JSONL not MD |
| .github/agents/prompt-reviewer.agent.md | Modify | Reference JSONL not MD |
| .github/prompts/cron_review.prompt.md | Modify | Read/write JSONL not MD |
| .github/prompts/plan.prompt.md | Modify | Surface recommendations from JSONL only |
| .github/prompts/strategic_review.prompt.md | Modify | Review JSONL not MD |
| scripts/run_cron_review.py | Modify | Remove MD file references |
| scripts/session_preflight.py | Modify | Remove MD file references |
| scripts/token_budget.py | Modify | Remove MD from context file list |
| docs/AGENT_WORKFLOW.md | Modify | Update recommendation references |
| docs/ARCHITECTURE.md | Modify | Update recommendation references |
| docs/GETTING_STARTED.md | Modify | Update recommendation references |
| docs/CHANGELOG.md | Modify | Document removal of RECOMMENDATIONS.md files |

## Acceptance Criteria

### Telemetry Capture (rec-006, rec-029)
- [ ] copilot_wrapper.py accepts `transcript_path` parameter
- [ ] copilot_wrapper.py passes `--share=<path>` to CLI when transcript_path provided
- [ ] execute_recommendation.py generates transcript paths like `logs/transcripts/session-{rec_id}-{timestamp}.md`
- [ ] .copilot-otel.jsonl is tracked (not gitignored)

### Single Source of Truth (rec-021)
- [ ] docs/RECOMMENDATIONS.md deleted
- [ ] docs/RECOMMENDATIONS_ARCHIVE.md deleted
- [ ] scripts/migrate_recommendations.py deleted
- [ ] tests/test_migrate_recommendations.py deleted
- [ ] No remaining references to RECOMMENDATIONS.md or RECOMMENDATIONS_ARCHIVE.md in codebase

### Reference Updates
- [ ] All prompt/agent files reference logs/.recommendations-log.jsonl
- [ ] copilot-instructions.md File Router updated (no MD refs, OTel file documented)
- [ ] Documentation files updated to reference JSONL

### Tests
- [ ] Existing tests for copilot_wrapper.py updated for transcript_path parameter
- [ ] pytest tests/ passes (no broken imports from deleted files)
- [ ] python scripts/validate.py exits 0

## Constraints

- Windows-compatible: All file operations must work in Git Bash
- No data loss: JSONL already contains all recommendation data (MD was derived from it)
- Backwards compatible: Scripts reading JSONL continue to work unchanged

## Context

- rec-006 (closed but not implemented): --share flag for transcripts
- rec-021: Archive resolved recommendations (superseded by this plan)
- rec-029: Full session capture structure
- Decision 30: OTel telemetry validated working
- Existing infrastructure: logs/transcripts/ directory and .transcript-index.jsonl exist

## Pre-Implementation Checklist

The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on main
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Update copilot_wrapper.py for transcript capture

File: scripts/copilot_wrapper.py

Action: Add `transcript_path: Optional[str] = None` parameter to `copilot_call()`. When provided, add `--share`, `transcript_path` to the command list. Update CopilotResult dataclass to include `transcript_path: Optional[str] = None` field. Set result.transcript_path after successful execution.

Acceptance: `python -c "from scripts.copilot_wrapper import copilot_call; help(copilot_call)"` shows transcript_path parameter.

### Step 2: Update execute_recommendation.py for transcript paths

File: scripts/execute_recommendation.py

Action: In `generate_plan()` and `execute_plan()`, generate transcript paths using `f"logs/transcripts/session-{rec_id}-{int(time.time())}.md"`. Pass transcript_path to copilot_call(). Import time module.

Acceptance: `grep -c "transcript_path" scripts/execute_recommendation.py` returns 3+.

### Step 3: Update test_copilot_wrapper.py

File: tests/test_copilot_wrapper.py

Action: Add test `test_copilot_call_with_transcript_path` that verifies `--share` is added to command when transcript_path is provided. Update existing mocked command assertions to handle optional transcript_path.

Acceptance: `pytest tests/test_copilot_wrapper.py -v` passes all tests.

### Step 4: Un-gitignore .copilot-otel.jsonl

File: .gitignore

Action: Remove or comment out the line `logs/.copilot-otel.jsonl`. Add comment explaining it's tracked for telemetry analysis.

Acceptance: `grep -c "copilot-otel" .gitignore` returns 0 (or line is commented).

### Step 5: Delete recommendation MD files

Files: docs/RECOMMENDATIONS.md, docs/RECOMMENDATIONS_ARCHIVE.md

Action: Delete both files using `git rm docs/RECOMMENDATIONS.md docs/RECOMMENDATIONS_ARCHIVE.md`.

Acceptance: `python -c "import glob; assert not glob.glob('docs/RECOMMENDATIONS*.md'), 'MD files still exist'"`

### Step 6: Delete migrate_recommendations.py and its tests

Files: scripts/migrate_recommendations.py, tests/test_migrate_recommendations.py

Action: Delete both files using `git rm scripts/migrate_recommendations.py tests/test_migrate_recommendations.py`.

Acceptance: Neither file exists.

### Step 7: Update copilot-instructions.md File Router

File: .github/copilot-instructions.md

Action: In File Router table: (1) Remove row for RECOMMENDATIONS.md, (2) Remove row for RECOMMENDATIONS_ARCHIVE.md, (3) Remove row for migrate_recommendations.py, (4) Update "Machine-readable recommendations" row to clarify it's the single source, (5) Add row for `.copilot-otel.jsonl` explaining it's OTel telemetry export.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/copilot-instructions.md` returns 0.

### Step 8: Update code-review.agent.md

File: .github/agents/code-review.agent.md

Action: Find all references to RECOMMENDATIONS.md and update to reference logs/.recommendations-log.jsonl. Update instructions to append findings as JSONL entries rather than writing to markdown table.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/agents/code-review.agent.md` returns 0.

### Step 9: Update retrospective.agent.md

File: .github/agents/retrospective.agent.md

Action: Find all references to RECOMMENDATIONS.md and update to logs/.recommendations-log.jsonl.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/agents/retrospective.agent.md` returns 0.

### Step 10: Update prompt-reviewer.agent.md

File: .github/agents/prompt-reviewer.agent.md

Action: Update any RECOMMENDATIONS.md references to logs/.recommendations-log.jsonl.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/agents/prompt-reviewer.agent.md` returns 0.

### Step 11: Update cron_review.prompt.md

File: .github/prompts/cron_review.prompt.md

Action: Update all RECOMMENDATIONS.md references to logs/.recommendations-log.jsonl. Update instructions for writing new recommendations to append JSONL entries.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/prompts/cron_review.prompt.md` returns 0.

### Step 12: Update plan.prompt.md

File: .github/prompts/plan.prompt.md

Action: Update recommendation surfacing to read from logs/.recommendations-log.jsonl only. Remove any RECOMMENDATIONS.md references.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/prompts/plan.prompt.md` returns 0.

### Step 13: Update strategic_review.prompt.md

File: .github/prompts/strategic_review.prompt.md

Action: Update to review logs/.recommendations-log.jsonl instead of RECOMMENDATIONS.md.

Acceptance: `grep -c "RECOMMENDATIONS.md" .github/prompts/strategic_review.prompt.md` returns 0.

### Step 14: Update run_cron_review.py

File: scripts/run_cron_review.py

Action: Remove any RECOMMENDATIONS.md file path references. Ensure only JSONL is used.

Acceptance: `grep -c "RECOMMENDATIONS" scripts/run_cron_review.py` returns 0.

### Step 15: Update session_preflight.py

File: scripts/session_preflight.py

Action: Remove RECOMMENDATIONS.md from any file lists or token budget calculations. Keep only JSONL reference.

Acceptance: `grep -c "RECOMMENDATIONS.md" scripts/session_preflight.py` returns 0.

### Step 16: Update token_budget.py

File: scripts/token_budget.py

Action: Remove RECOMMENDATIONS.md and RECOMMENDATIONS_ARCHIVE.md from context file lists.

Acceptance: `grep -c "RECOMMENDATIONS" scripts/token_budget.py` returns 0.

### Step 17: Update documentation files

Files: docs/AGENT_WORKFLOW.md, docs/ARCHITECTURE.md, docs/GETTING_STARTED.md

Action: Update all references to RECOMMENDATIONS.md to point to logs/.recommendations-log.jsonl. Explain that JSONL is the single source of truth for recommendations.

Acceptance: `grep -rn "RECOMMENDATIONS.md" docs/*.md` returns only CHANGELOG.md (historical reference OK).

### Step 18: Update CHANGELOG.md

File: docs/CHANGELOG.md

Action: Add entry documenting the removal of RECOMMENDATIONS.md and RECOMMENDATIONS_ARCHIVE.md, explaining that logs/.recommendations-log.jsonl is now the single source of truth for recommendations.

Acceptance: `grep -c "single source of truth" docs/CHANGELOG.md` returns 1+.

### Step 19: Run pytest

Action: `pytest tests/ -v`

Acceptance: All tests pass (no import errors from deleted migrate_recommendations.py).

### Step 20: Run validate.py

Action: `python scripts/validate.py`

Acceptance: Exit code 0.

### Step 21: Final reference check

Action: Run Python script to verify no stray RECOMMENDATIONS.md references:
```python
import subprocess
result = subprocess.run(
    ['git', 'grep', '-l', 'RECOMMENDATIONS.md', '--', '*.py', '*.md'],
    capture_output=True, text=True
)
files = [f for f in result.stdout.strip().split('\n') if f and 'CHANGELOG' not in f]
assert not files, f"Stray references in: {files}"
```

Acceptance: No files returned except CHANGELOG.md.

## Dependencies

- rec-006: --share flag for transcripts (completing implementation)
- rec-021: Archive resolved recommendations (superseded)
- rec-029: Full session capture structure (completing)
- Decision 30: OTel telemetry validated

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Broken references after deletion | Medium | Medium | Step 20 final check catches stragglers |
| Lost recommendation data | Low | High | JSONL already contains all data; MD was derived |
| Test failures from deleted module | Low | Low | Step 18 catches import errors early |

## Estimated Effort

Total: M (3-4 hours)
Breakdown: copilot_wrapper (XS), deletions (XS), reference updates (S), testing (S)
