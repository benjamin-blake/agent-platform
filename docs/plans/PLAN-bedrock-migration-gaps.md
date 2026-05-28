# Plan

## Intent
Close the remaining gaps from PLAN-bedrock-migration.md implementation. The core migration (33 files, 1532 tests passing, validation clean) is complete but several operational steps, missing tests, subagent invocations, and deployment steps were skipped. This plan covers only the delta -- no re-implementation of already-working code.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/platform-bedrock-migration (same branch -- uncommitted work exists)

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `tests/test_execute_recommendation.py` | Modify | Add 3 missing is_eligible test methods specified in original plan Step 37 |
| `docs/plans/PLAN-bedrock-migration.md` | Modify | Mark completed steps, annotate skipped steps with rationale |

## Context
- Branch: `agent/platform-bedrock-migration`, HEAD at `4613058`
- All 40 modified/created files are unstaged (no commits since implementation started)
- 1532 tests pass, 40 skipped (deprecated copilot_wrapper), 0 failed
- `python -m scripts.validate` exits 0
- Bedrock API confirmed working but currently rate-limited (ThrottlingException on converse calls)
- Original plan had 51 steps across 9 phases. Phases 0-8 code changes are complete. Gaps are operational/process steps.

## Pre-Implementation Checklist
- [x] Branch confirmed: `agent/platform-bedrock-migration`
- [x] Tests pass: 1532 passed, 40 skipped
- [x] Validation clean

## Ordered Execution Steps

### Phase A: Missing Tests (from original Step 37)

1. **Add `test_is_eligible_rejects_m_effort` to `tests/test_execute_recommendation.py`.** Create a test in `TestIsEligibleStatus` (or adjacent class) that constructs a rec with `effort: "M"`, `risk: "low"`, `automatable: True`, targeting a small file. Assert `is_eligible(rec) is False`. This verifies the effort gate added during the migration.

2. **Add `test_is_eligible_rejects_large_file` to `tests/test_execute_recommendation.py`.** Create a test that constructs a rec with `effort: "S"`, `risk: "low"`, `automatable: True`, targeting a file with >800 SLOC (use `tmp_path` to create a file with 801 non-blank lines). Assert `is_eligible(rec) is False`. This verifies the SLOC gate.

3. **Add `test_is_eligible_accepts_xs_small_file` to `tests/test_execute_recommendation.py`.** Create a test that constructs a rec with `effort: "XS"`, `risk: "low"`, `automatable: True`, targeting a file with <800 SLOC (use `tmp_path` to create a 50-line file). Assert `is_eligible(rec) is True`. This is the positive case for the new gates.

4. **Run tests:** `python -m pytest tests/test_execute_recommendation.py -k "test_is_eligible" -v` -- all must pass including new tests.

5. **Run full validation:** `python -m scripts.validate` -- must exit 0.

### Phase B: Code Review

6. **Invoke `code-review` subagent.** The subagent performs a full repository code review of changes on the branch and returns structured findings. Any CRITICAL or HIGH findings must be fixed before proceeding. Medium/Low findings get logged as recommendations.

### Phase C: Commit and Push

7. **Stage all changes:** `git add -A` to stage all 40 modified/new files.

8. **Commit:** `git commit -m "feat(platform-bedrock-migration): migrate LLM inference to Bedrock DeepSeek V3.2"` with a body summarizing: 33 files in scope, new modules (llm_client, llm_utils, tool_runtime, bedrock_client extensions, classify_automatable), deprecated modules (copilot_wrapper, copilot_sdk_client), Decision 52, 1532 tests passing.

9. **Push:** `git push -u origin agent/platform-bedrock-migration`.

### Phase D: Verification Plan Execution

10. **VP Step 1 -- Disabled agents:** `python -m pytest tests/test_run_scheduled_agent.py -k "test_disabled_agents_skipped" -v`. Expected: passes.

11. **VP Step 2 -- LLMResult shape:** `python -m pytest tests/test_llm_client.py -k "TestImports" -v`. Expected: import succeeds, LLMResult has required fields.

12. **VP Step 3 -- Tool schemas:** `python -m pytest tests/test_tool_runtime.py -k "TestToolSchemas" -v`. Expected: 6+ tools with valid Bedrock toolSpec format.

13. **VP Step 4 -- New module tests:** `python -m pytest tests/test_llm_client.py tests/test_tool_runtime.py tests/test_llm_utils.py tests/test_classify_automatable.py -v`. Expected: all pass.

14. **VP Step 5 -- Eligibility gates:** `python -m pytest tests/test_execute_recommendation.py -k "test_is_eligible" -v`. Expected: all pass including new effort/SLOC tests.

15. **VP Step 6 -- Full test suite:** `python -m pytest tests/ -v`. Expected: 1535+ passed, 40 skipped.

16. **VP Step 7 -- Validation:** `python -m scripts.validate`. Expected: exit 0.

17. **VP Steps 8-9 -- Lambda deploy (DEFER).** Lambda deployment requires the Bedrock rate limit to clear and a human decision on when to propagate disabled agents to the live Lambda. File a follow-up rec in `logs/.recommendations-log.jsonl` or add a SESSION_LOG entry so this is not silently dropped. Do not execute in this session.

18. **VP Step 10 -- Tool use support:** `python -m pytest tests/test_bedrock_client.py -k "test_strips_think_blocks" -v`. Expected: passes (verifies DeepSeek response handling). Live tool_use was confirmed by the user's manual test.

19. **VP Step 11 -- E2E rec execution (DEFER).** Requires Bedrock rate limit to clear. File alongside the Lambda deploy deferral (Step 17) in the same tracking artifact.

20. **VP Step 12 -- Data residency:** `python -m pytest tests/test_llm_client.py -k "TestDataResidency" -v`. Expected: eu-west-2 confirmed.

### Phase E: Batch Classification

21. **Run classify_automatable:** `python -m scripts.classify_automatable`. Capture output showing N automatable, M non-automatable. Do NOT commit the JSONL changes on this branch -- they belong on main after merge.

### Phase F: Retrospective

22. **Invoke `retrospective` subagent** with `--mode=workflow`. This session had significant friction: the previous session's bulk `.stdout` -> `.content` replacement damaged subprocess references in both source and test files, causing cascading failures across 6 test files. The retrospective should capture this as a lesson.

## Acceptance Criteria
- [ ] 3 new is_eligible tests exist and pass
- [ ] code-review subagent invoked, CRITICAL/HIGH findings resolved
- [ ] All changes committed and pushed to `agent/platform-bedrock-migration`
- [ ] VP steps 1-7, 10, 12 executed with passing results
- [ ] VP steps 8-9, 11 logged as deferred with follow-up rec or SESSION_LOG entry
- [ ] classify_automatable run with output captured
- [ ] Retrospective invoked

## Constraints
- Bedrock API is rate-limited (ThrottlingException). VP steps requiring live API calls (8, 9, 11) must be deferred.
- Do not merge to main in this plan. Merge is a separate human-triggered action after PR review.
- Do not modify JSONL recommendations on this branch (classify_automatable output is informational only).
