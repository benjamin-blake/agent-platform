# Plan

## Intent

Build the foundation for script-driven workflow automation - replacing LLM-as-orchestrator with deterministic Python orchestration that makes surgical LLM calls. This directly serves the North Star by enabling lower-cost, more reliable, testable, and CI-executable self-improvement cycles.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-recommendation-executor

## Phase

Infra (workflow infrastructure)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| scripts/copilot_wrapper.py | Create | Subprocess abstraction for copilot -p with OTel capture |
| scripts/execute_recommendation.py | Create | Single-recommendation executor with plan/critique/execute loop |
| scripts/classify_risk.py | Create | LLM-based risk classification for recommendations |
| logs/.recommendations-log.jsonl | Modify | Add automatable and risk fields to schema, existing entries, and rec-030 |
| tests/test_copilot_wrapper.py | Create | Unit tests for copilot_wrapper |
| tests/test_execute_recommendation.py | Create | Unit tests for execute_recommendation |
| tests/test_classify_risk.py | Create | Unit tests for classify_risk |
| scripts/validate.py | Modify | Add import validation for new executor scripts |
| docs/GETTING_STARTED.md | Modify | Document new scripts and usage |

## Acceptance Criteria

### rec-010: JSONL Schema Update
- [ ] logs/.recommendations-log.jsonl schema comment includes automatable and risk fields
- [ ] All existing recommendations have automatable: false (conservative default)
- [ ] All existing recommendations have risk: unclassified (to be classified later)

### rec-009: Recommendation Executor
- [ ] scripts/copilot_wrapper.py exists with copilot_call() function
- [ ] copilot_call() captures OTel metrics (tokens, cost) from JSONL export
- [ ] copilot_call() supports model selection, tool permissions, timeout
- [ ] scripts/execute_recommendation.py can load a recommendation by ID
- [ ] Executor generates plan via CLI, runs critique loop (max 3 iterations)
- [ ] Executor executes steps via CLI with Haiku model
- [ ] Executor runs validate.py after each step
- [ ] Executor creates git commit, push, and opens PR (no auto-merge)
- [ ] scripts/classify_risk.py classifies risk as low/medium/high via LLM
- [ ] Executor filters by risk == low and automatable == true

### Documentation
- [ ] docs/GETTING_STARTED.md includes Automated Recommendation Execution section

### Tests
- [ ] test_copilot_wrapper.py has 5+ tests covering success, timeout, error cases
- [ ] test_execute_recommendation.py has 5+ tests covering load, filter, execute flow
- [ ] test_classify_risk.py has 3+ tests covering classification logic
- [ ] All tests pass with pytest tests/

## Constraints

- No auto-merge: PRs require human review (rec-030 will evaluate auto-merge criteria later)
- Low-risk only: Initial executor only processes risk == low recommendations
- OTel required: CLI must export telemetry; fail if COPILOT_OTEL_FILE_EXPORTER_PATH not set
- Windows-compatible: All subprocess calls must work in Git Bash on Windows
- No eval/exec: Risk classification uses LLM judgment, not code execution

## Context

- Decision 30: OTel telemetry validated working - github.copilot.cost in invoke_agent spans
- Decision 31: Subagents cannot invoke CLI - script must run in parent shell context
- Decision 29: Friction-Free Implementation Pattern - use tight step scopes
- rec-010: Dependency for schema fields (absorbed into this plan)
- rec-030: Future recommendation for auto-merge evaluation (created but not implemented)

## Pre-Implementation Checklist

The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on main
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Update JSONL Schema (rec-010)

File: logs/.recommendations-log.jsonl

Action: Update the schema comment at line 1 to include new fields. Then run a Python script to add default fields to all existing entries (automatable: false, risk: unclassified).

Acceptance: grep -c automatable logs/.recommendations-log.jsonl returns count equal to total entries.

### Step 2: Create copilot_wrapper.py

File: scripts/copilot_wrapper.py

Action: Create module with CopilotResult dataclass and copilot_call() function. Require COPILOT_OTEL_FILE_EXPORTER_PATH env var. Build command with model, tools, timeout, output_file options. Parse OTel JSONL for metrics.

Acceptance: python -c "from scripts.copilot_wrapper import copilot_call, CopilotResult" succeeds.

### Step 3: Create classify_risk.py

File: scripts/classify_risk.py

Action: Create module with RISK_CRITERIA prompt template, classify_risk() function, classify_all_unclassified() batch function, and main() CLI entry point.

Acceptance: python scripts/classify_risk.py --help shows usage.

### Step 4: Create execute_recommendation.py

File: scripts/execute_recommendation.py

Action: Create module with load_recommendation(), is_eligible(), generate_plan(), execute_plan(), finalize(), execute_recommendation(), and main() functions.

Acceptance: python scripts/execute_recommendation.py --help shows usage.

### Step 5: Update validate.py

File: scripts/validate.py

Action: Add import validation for the three new modules (copilot_wrapper, execute_recommendation, classify_risk) to the existing import checks.

Acceptance: python scripts/validate.py passes with new modules included in import validation.

### Step 6: Create test_copilot_wrapper.py

File: tests/test_copilot_wrapper.py

Action: Create 6 tests: test_copilot_call_success, test_copilot_call_timeout, test_copilot_call_missing_otel_path, test_copilot_call_with_tools, test_parse_otel_metrics, test_copilot_call_with_output_file.

Acceptance: pytest tests/test_copilot_wrapper.py -v passes all tests.

### Step 7: Create test_classify_risk.py

File: tests/test_classify_risk.py

Action: Create 3 tests: test_classify_risk_low, test_classify_risk_high, test_classify_all_unclassified.

Acceptance: pytest tests/test_classify_risk.py -v passes all tests.

### Step 8: Create test_execute_recommendation.py

File: tests/test_execute_recommendation.py

Action: Create 6 tests: test_load_recommendation_found, test_load_recommendation_not_found, test_is_eligible_true, test_is_eligible_false_high_risk, test_is_eligible_false_not_automatable, test_generate_plan_with_critique_loop.

Acceptance: pytest tests/test_execute_recommendation.py -v passes all tests.

### Step 9: Scope Guard Check

Action: Run git status --short and verify only expected files are modified/created (7 files expected).

Acceptance: No unexpected files in git status.

### Step 10: Update GETTING_STARTED.md

File: docs/GETTING_STARTED.md

Action: Add Automated Recommendation Execution section with prerequisites, usage examples, risk levels table, and architecture explanation.

Acceptance: grep -c "Automated Recommendation Execution" docs/GETTING_STARTED.md returns 1.

### Step 11: Create rec-030 in JSONL

File: logs/.recommendations-log.jsonl

Action: Append new recommendation for auto-merge evaluation.

Acceptance: grep rec-030 logs/.recommendations-log.jsonl returns the entry.

### Step 12: Run Tests

Action: pytest tests/ -v

Acceptance: All tests pass.

### Step 13: Run Validation

Action: python scripts/validate.py

Acceptance: Exit code 0.

### Step 14: Report Implementation Summary

Action: Summarize implementation: rec-010 schema, rec-009 scripts, rec-030 new rec, tests, documentation.

## Dependencies

- rec-010 (JSONL schema): Absorbed into this plan (Step 1)
- Decision 30 (OTel validation): Provides schema for metrics parsing
- Decision 31 (Subagent limitations): Confirms script must run in shell context

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OTel format changes in future CLI versions | Low | Medium | Pin CLI version; add schema validation |
| LLM risk classification inconsistent | Medium | Low | Conservative default (unclassified = not eligible) |
| Subprocess timeout on slow LLM responses | Medium | Low | Configurable timeout with sensible default (300s) |

## Estimated Effort

Total: M (4-6 hours)
Breakdown: copilot_wrapper (S), execute_recommendation (M), classify_risk (S), tests (S), docs (XS)
