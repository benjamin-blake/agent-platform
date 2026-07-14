# Plan

## Intent

Migrate all Copilot CLI calls to use `--output-format=json` to eliminate plan parsing ambiguity at the source. This directly improves the self-improving feedback loop by making executor workflows more reliable, reducing friction from duplicate step numbers and inconsistent output parsing.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-cli-json-output

## Phase

Phase 1: Core Infrastructure (infrastructure improvement)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| scripts/copilot_wrapper.py | Modify | Add `output_format` parameter, `parse_jsonl_output()` function, update `CopilotResult` dataclass |
| scripts/executor/plan.py | Modify | Use JSON output in `generate_initial_plan()`, `critique_plan()`, `refine_plan()` |
| scripts/executor/step_runner.py | Modify | Use JSON output in `implement_step()` |
| scripts/executor/postflight.py | Modify | Use JSON output in all 4 `copilot_call()` sites |
| scripts/classify_risk.py | Modify | Use JSON output |
| scripts/run_scheduled_agent.py | Modify | Use JSON output |
| tests/test_copilot_wrapper.py | Modify | Add tests for `parse_jsonl_output()`, update mocks for JSON output |
| tests/test_executor_plan.py | Modify | Update mocks to return JSON-formatted output |
| tests/test_executor_step_runner.py | Modify | Update mocks for JSON output |
| tests/test_executor_postflight.py | Modify | Update mocks for JSON output in all 4 `copilot_call()` sites |
| tests/test_classify_risk.py | Modify | Update mocks for JSON output |
| tests/test_run_scheduled_agent.py | Modify | Update mocks for JSON output |
| logs/.recommendations-log.jsonl | Modify | Update rec-141 status to `"superseded"` |
| docs/contracts/cli-json-output.md | Create | Document the JSON output schema as a boundary contract |

## Bundled Recommendations

- **rec-141**: "plan parser: detect and deduplicate steps with identical sequence numbers" -- this plan supersedes rec-141 by fixing the root cause rather than the symptom. The deduplication heuristic becomes a secondary defense.

## Acceptance Criteria

- [ ] All `copilot_call()` invocations use `--output-format=json` by default
- [ ] `parse_jsonl_output()` extracts `assistant.message` content and `result` metadata from JSONL
- [ ] `CopilotResult` includes `premium_requests` from `result.usage.premiumRequests`
- [ ] JSON parse failures raise `CopilotResponseError` (hard fail, no text fallback)
- [ ] Existing plan parsing logic (`parse_steps_from_plan()`) continues to work on extracted content
- [ ] rec-141 status updated to `"superseded"` with context explaining root-cause fix
- [ ] `docs/contracts/cli-json-output.md` documents the expected JSON schema
- [ ] `python -m pytest tests/test_copilot_wrapper.py tests/test_executor_plan.py tests/test_executor_step_runner.py tests/test_executor_postflight.py tests/test_classify_risk.py tests/test_run_scheduled_agent.py -x -q` passes
- [ ] `python -m scripts.validate` passes

## Constraints

- Forward-fix only: no fallback to text output. This is a fundamentally better infrastructure approach; any issues are fixed by improving the JSON parser, not by reverting to the fragile regex-based approach.
- Windows subprocess encoding: all JSON parsing must use `encoding='utf-8', errors='replace'`
- Keep `parse_steps_from_plan()` as-is for now; it parses markdown content extracted from JSON
- Do not change prompt delivery mechanism (`@file` vs inline) -- that is a separate concern (rec-119)

## Context

- **CLI documentation**: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference confirms `--output-format=json` outputs JSONL (one JSON object per line)
- **Empirical schema** (discovered via planning session tests):
  ```
  assistant.message -> data.content (text), data.toolRequests[], data.outputTokens
  tool.execution_start/complete -> tool call tracking
  result -> sessionId, exitCode, usage.premiumRequests
  ```
- **rec-141 context**: Planner generated duplicate step numbers (analysis prose + implementation steps both numbered from 1). JSON output provides turn boundaries that disambiguate this.
- **rec-113** (closed): Deduplication logic was added as a fix; it remains as secondary defense.
- **rec-119** (open): Prompt delivery mechanism (`@file` vs inline) is orthogonal to this change.
- **Known gotcha**: Windows subprocess must use `encoding='utf-8', errors='replace'`

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create boundary contract document

Create `docs/contracts/cli-json-output.md` documenting the JSON output schema. Include:
- Event types: `session.*`, `user.message`, `assistant.message`, `assistant.turn_start/end`, `tool.execution_start/complete`, `result`
- Key fields for `assistant.message`: `data.content`, `data.toolRequests`, `data.outputTokens`, `data.messageId`
- Key fields for `result`: `sessionId`, `exitCode`, `usage.premiumRequests`, `usage.totalApiDurationMs`
- Filtering guidance: extract only `assistant.message` events for content, use `result` for session metadata

### Step 2: Add JSON output support to copilot_wrapper.py

Modify `scripts/copilot_wrapper.py`:

1. Add `output_format: Literal["text", "json"] = "json"` parameter to `copilot_call()`
2. When `output_format == "json"`, add `--output-format`, `json` to the command list
3. Add `parse_jsonl_output(raw: str) -> dict` function that:
   - Parses each line as JSON
   - Collects all `assistant.message` events, concatenating `data.content` fields
   - Extracts `result` event for `sessionId`, `exitCode`, `usage.premiumRequests`
   - Raises `CopilotResponseError` on JSON parse failure (no fallback)
4. Update `CopilotResult` dataclass to include `premium_requests: float = 0.0`
5. When JSON output is used, call `parse_jsonl_output()` and populate `CopilotResult` from parsed data
6. Update `validate_response()` to work on extracted content (not raw JSONL)

### Step 3: Add tests for JSON output parsing

Add tests to `tests/test_copilot_wrapper.py`:
- `test_parse_jsonl_output_extracts_content`: Verify content extraction from multiple `assistant.message` events
- `test_parse_jsonl_output_extracts_result_metadata`: Verify `sessionId`, `exitCode`, `premium_requests` extraction
- `test_parse_jsonl_output_raises_on_malformed_json`: Verify `CopilotResponseError` on parse failure
- `test_copilot_call_json_output_flag`: Verify `--output-format json` is added to command
- Update existing `copilot_call` tests to mock JSON output format

### Step 4: Update executor plan.py for JSON output

Modify `scripts/executor/plan.py`:
- In `generate_initial_plan()`: ensure `copilot_call()` uses JSON output (default)
- In `critique_plan()`: ensure `copilot_call()` uses JSON output
- In `refine_plan()`: ensure `copilot_call()` uses JSON output
- The returned `result.stdout` is now the extracted content (not raw JSONL)
- Use `result.premium_requests` instead of `requests_for_model()` calculation

### Step 5: Update test_executor_plan.py mocks

Modify `tests/test_executor_plan.py`:
- Update all `copilot_call` mocks to return extracted content (simulating post-JSON-parsing)
- The mocks don't need to return raw JSONL since `copilot_call()` handles parsing internally

### Step 6: Update executor step_runner.py for JSON output

Modify `scripts/executor/step_runner.py`:
- In `implement_step()`: ensure `copilot_call()` uses JSON output (default)
- Use `result.premium_requests` for cost tracking

### Step 7: Update test_executor_step_runner.py mocks

Modify `tests/test_executor_step_runner.py`:
- Update `copilot_call` mocks to return extracted content format

### Step 8: Update executor postflight.py for JSON output

Modify `scripts/executor/postflight.py`:
- Update all 4 `copilot_call()` sites to use JSON output (default)
- Sites: `_code_review_gate()`, `_attempt_merge_recovery()`, `_attempt_review_fix()`, `_attempt_ci_fix()`

### Step 8b: Update test_executor_postflight.py mocks

Modify `tests/test_executor_postflight.py`:
- Update all `copilot_call` mocks to return extracted content format
- Ensure mocks align with the 4 call sites in postflight.py

### Step 9: Update classify_risk.py for JSON output

Modify `scripts/classify_risk.py`:
- Ensure `copilot_call()` uses JSON output (default)

### Step 9b: Update test_classify_risk.py mocks

Modify `tests/test_classify_risk.py`:
- Update `copilot_call` mocks to return extracted content format

### Step 10: Update run_scheduled_agent.py for JSON output

Modify `scripts/run_scheduled_agent.py`:
- Ensure `copilot_call()` uses JSON output (default)

### Step 10b: Update test_run_scheduled_agent.py mocks

Modify `tests/test_run_scheduled_agent.py`:
- Update `copilot_call` mocks to return extracted content format

### Step 11: Update rec-141 status to superseded

Modify `logs/.recommendations-log.jsonl`:
- Find rec-141 entry
- Update `status` to `"superseded"`
- Add `superseded_by` field: `"PLAN-infra-cli-json-output"`
- Update `context` to note: `"Root-cause fix implemented: --output-format=json eliminates duplicate step number ambiguity at the source."`

### Step 12: Run tests

```bash
python -m pytest tests/test_copilot_wrapper.py tests/test_executor_plan.py tests/test_executor_step_runner.py tests/test_executor_postflight.py tests/test_classify_risk.py tests/test_run_scheduled_agent.py -x -q
```

All tests must pass before proceeding.

### Step 13: Run full validation

```bash
python -m scripts.validate
```

Must exit 0.

### Step 14: Report implementation summary

Report what was implemented, any design decisions made, and confirm all acceptance criteria are met.
