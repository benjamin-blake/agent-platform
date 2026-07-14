# Plan

## Intent
Improve automated recommendation execution reliability by ensuring the executor respects dependency ordering and provides sufficient context to CLI agents implementing changes — directly advancing the North Star of a self-improving system that can autonomously process its own improvement backlog.

## Plan Type
IMPLEMENTATION

## Branch
agent/exec-deps-context

## Phase
Phase E: Executor Completeness (rec-034, rec-035)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/execute_recommendation.py | Modify | Add load_all_recommendations() helper; update is_eligible() to check dependency status; add gather_step_context() for file content injection; update implement_step() to inject context |
| config/prompts/executor/implement-step.prompt.md | Modify | Add {file_content}, {test_content}, {pattern_content} placeholders |
| tests/test_execute_recommendation.py | Modify | Add tests for dependency resolution and context gathering |

## Acceptance Criteria
- [ ] is_eligible() returns False when any dependency has status != "closed"
- [ ] is_eligible() returns True when dependencies is empty or all deps are closed
- [ ] Missing dependency IDs (not found in JSONL) are treated as unresolved (conservative)
- [ ] implement_step() reads target file content before CLI call for modify actions
- [ ] implement_step() finds and includes similar files for create actions
- [ ] File content injected into prompt via {file_content} placeholder
- [ ] Content capped at 50K characters with truncation markers
- [ ] Test covers: no deps, all deps closed, one dep open, missing dep ID
- [ ] Test covers: modify with existing file, create with pattern file, file not found (graceful), large file truncation

## Constraints
- Python 3.12+, type hints required
- Windows subprocess encoding: always use encoding="utf-8", errors="replace"
- No Docker; this is local script execution
- Content cap at 50K characters to stay within CLI context limits

## Context
- rec-009 (executor script) is now closed — rec-034/035 are gap-fills
- rec-034: XS effort, High priority — ~10 lines of code for dependency check
- rec-035: M effort, Critical priority — largest single improvement to execution success rate
- Briefings at docs/plans/briefings/BRIEFING-rec-034.md and BRIEFING-rec-035.md define detailed requirements
- is_eligible() currently only checks risk == "low" and automatable == True
- implement_step() currently passes only step description to CLI, no file content

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on main
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Part 1: Dependency Resolution (rec-034)

1. **Add load_all_recommendations() helper** in scripts/execute_recommendation.py
   - Read all entries from JSONL into a dict keyed by id
   - Skip schema lines and empty lines
   - Return dict[str, dict] where key is rec ID, value is full entry
   - Place after existing load_recommendation() function

2. **Update is_eligible() signature and logic**
   - Change signature to is_eligible(rec: dict, recs_by_id: dict | None = None) -> bool
   - If recs_by_id is None, call load_all_recommendations() internally (for backward compatibility)
   - For each ID in rec.get("dependencies", []), check if recs_by_id.get(dep_id, {}).get("status") == "closed"
   - If any dependency is missing or not closed, return False
   - Preserve existing risk and automatable checks

3. **Add dependency resolution tests** in tests/test_execute_recommendation.py
   - Test: no dependencies field -> eligible (if other conditions met)
   - Test: empty dependencies list -> eligible
   - Test: all dependencies closed -> eligible
   - Test: one dependency open -> ineligible
   - Test: dependency ID not found in JSONL -> ineligible (conservative)

### Part 2: Context Injection (rec-035)

4. **Add gather_step_context() function** in scripts/execute_recommendation.py
   - Signature: gather_step_context(step: dict, max_chars: int = 50000) -> dict
   - For action == "modify": read step["file"] content if it exists
   - For action == "create": find a pattern file in the same directory using this heuristic:
     - Glob for files with the same extension (e.g., `*.py` for a `.py` file)
     - Prefer the most recently modified file as the pattern
     - Example: creating `tests/test_new_feature.py` → use most recent `tests/test_*.py` as pattern
     - Example: creating `scripts/new_script.py` → use most recent `scripts/*.py` as pattern
   - Look for corresponding test file: tests/test_{filename}.py
   - Return dict with keys: file_content, test_content, pattern_content
   - Apply truncation: if total > max_chars, truncate with "
# ... (N lines omitted)
" marker
   - Handle file not found gracefully (return empty strings)

5. **Update implement_step() to inject context**
   - Call gather_step_context(step) before building prompt
   - Pass context dict values to template.format() as file_content, test_content, pattern_content
   - Log injected context size for telemetry

6. **Update prompt template** at config/prompts/executor/implement-step.prompt.md
   - Add sections for {file_content}, {test_content}, {pattern_content}
   - Keep sections conditional: only show if content is non-empty
   - Add guidance for how agent should use the context

7. **Add context injection tests** in tests/test_execute_recommendation.py
   - Test: modify action with existing file -> file_content populated
   - Test: create action -> pattern_content from similar file
   - Test: file not found -> empty string, no error
   - Test: large file (>50K chars) -> truncated with marker
   - Test: test file found -> test_content populated

### Part 3: Validation

8. Run pytest tests/test_execute_recommendation.py -v — all tests must pass

9. Run python scripts/validate.py — must exit 0

10. Report what was implemented and any design decisions made during implementation
