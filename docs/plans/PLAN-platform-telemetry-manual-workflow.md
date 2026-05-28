# Plan

## Intent
Instrument manual `/plan` and `/implement` workflows with structured telemetry (Phase D of the telemetry rescue), replacing the legacy 12MB monolithic JSONL files with proper Iceberg-backed star-schema records. This makes both executor and manual sessions queryable from the same `telemetry_sessions` table, closing the observability gap and enabling the autonomous improvement loop to measure ALL work -- not just executor runs.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-telemetry-manual-workflow

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/session_preflight.py | Modify | Add `--open-session` flag that creates a partial `telemetry_sessions` record; replace `check_telemetry_health()` to query Athena `telemetry_sessions_current` view instead of local JSONL |
| scripts/session_postflight.py | Modify | Add `--close-session` flag that finalises the `telemetry_sessions` record; emit process events for key lifecycle points; remove dead `_run_token_budget_script()`, `run_token_budget()`, and `--token-budget` CLI flag |
| scripts/agent_development/run_skill.py | Modify | Accept `--session-id` and `--phase-order` to attach telemetry to parent session instead of creating standalone session |
| scripts/session_metrics.py | Modify | Remove `write_session_envelope` call (replaced by postflight telemetry emission) |
| scripts/execute_recommendation.py | Modify | Remove imports of `write_session_envelope` and `_retro_append`; convert `_capture_executor_telemetry()` to a no-op stub (10+ call sites remain but are harmless); remove `TestCaptureExecutorTelemetry` class in tests |
| scripts/build_lambda.py | Modify | Remove `session_telemetry.py` from `_LAMBDA_SCRIPTS` list (no longer packaged for Lambda) |
| scripts/session_telemetry.py | Delete | Replaced by `scripts/executor/telemetry.py` unified write interface |
| scripts/friction_analysis.py | Delete | Replaced by Athena queries on `telemetry_process_events` |
| scripts/run_retro_lite.py | Delete | Replaced by process event emission within the executor |
| scripts/transcript_index.py | Delete | Replaced by `telemetry_transcripts` records |
| scripts/token_budget.py | Delete | Replaced by per-call `telemetry_model_calls` tracking |
| scripts/metrics_analysis.py | Delete | Replaced by Athena analytical views |
| tests/test_session_telemetry.py | Delete | Tests for deleted module |
| tests/test_friction_analysis.py | Delete | Tests for deleted module |
| tests/test_run_retro_lite.py | Delete | Tests for deleted module |
| tests/test_transcript_index.py | Delete | Tests for deleted module |
| tests/test_token_budget.py | Delete | Tests for deleted module |
| tests/test_metrics_analysis.py | Delete | Tests for deleted module |
| tests/test_session_preflight.py | Modify | Update tests for new Athena-based health check and --open-session |
| tests/test_session_postflight.py | Modify | Add tests for --close-session telemetry emission |
| tests/test_session_metrics.py | Modify | Remove test of write_session_envelope call |
| tests/test_execute_recommendation.py | Modify | Delete `TestCaptureExecutorTelemetry` class; update mocks that patch `_capture_executor_telemetry` (9 locations: lines 485, 4289, 4349, 5113, 5255, 6393, 6480, 6565, 6666) |
| .github/copilot-instructions.md | Modify | Remove file router entries for deleted scripts |
| .agents/workflows/implement.md | Modify | Remove `run_retro_lite` reference (line 63) |
| config/README.md | Modify | Remove references to `run_retro_lite.py`, `friction_analysis.py`, `metrics_analysis.py` (lines 313-314) |
| docs/ARCHITECTURE.md | Modify | Remove `run_retro_lite.py` references (lines 154, 161, 175) |
| docs/AGENT_WORKFLOW.md | Modify | Remove references to `run_retro_lite.py` and `_capture_executor_telemetry()` (line 209) |

## Bundled Recommendations
None. This implements Phase D of the telemetry rescue (docs/INTENT-telemetry-system.md).

## Acceptance Criteria
- [ ] `python -m scripts.session_preflight --open-session --workflow plan --branch agent/test` prints a session UUID and writes state to `logs/.telemetry-active-session.json`
- [ ] `python -m scripts.session_postflight --close-session --outcome success` reads the state file, emits a complete `telemetry_sessions` record, and removes the state file
- [ ] `python -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-platform-telemetry-manual-workflow.md --session-id <uuid> --phase-order 2` attaches its telemetry to the parent session (no standalone session created)
- [ ] Preflight `check_telemetry_health()` queries Athena and returns health metrics (or graceful degradation if SSO expired)
- [ ] `grep -r "from scripts.session_telemetry" scripts/ tests/` returns zero matches
- [ ] `grep -r "from scripts.friction_analysis\|from scripts.run_retro_lite\|from scripts.transcript_index\|from scripts.token_budget\|from scripts.metrics_analysis" scripts/ tests/` returns zero matches
- [ ] `python -m scripts.validate` exits 0
- [ ] `grep -q "_capture_executor_telemetry" scripts/execute_recommendation.py && ! grep -q "write_session_envelope\|_retro_append" scripts/execute_recommendation.py` confirms function exists as no-op but legacy imports are gone
- [ ] All tests pass: `python -m pytest tests/test_session_preflight.py tests/test_session_postflight.py tests/test_session_metrics.py tests/test_execute_recommendation.py -x -q`
- [ ] `grep -q "session_telemetry" scripts/build_lambda.py` returns exit code 1 (removed from Lambda packaging)
- [ ] `python -m scripts.build_lambda` builds successfully without the deleted script
- [ ] Preflight report includes a "Friction Patterns" section querying `telemetry_process_events` for top-N recent events

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit tests pass for modified preflight | `python -m pytest tests/test_session_preflight.py -x -q` | All tests pass, 0 exit code | Fix mock setup for Athena query |
| 2 | [pre-deploy] | Unit tests pass for modified postflight | `python -m pytest tests/test_session_postflight.py -x -q` | All tests pass, 0 exit code | Fix telemetry emission logic |
| 3 | [pre-deploy] | Unit tests pass for modified session_metrics | `python -m pytest tests/test_session_metrics.py -x -q` | All tests pass, 0 exit code | Fix import removal |
| 4 | [pre-deploy] | No references to deleted modules remain | `grep -r "from scripts.session_telemetry\|from scripts.friction_analysis\|from scripts.run_retro_lite\|from scripts.transcript_index\|from scripts.token_budget\|from scripts.metrics_analysis" scripts/ tests/ --include="*.py"` | Zero matches (exit code 1) | Remove missed import |
| 5 | [pre-deploy] | Validate passes (imports, lint, tests) | `python -m scripts.validate` | Exit 0 | Fix whatever validate reports |
| 6 | [pre-deploy] | Open session via preflight CLI | `python -m scripts.session_preflight --open-session --workflow plan --branch agent/test-telemetry` | Prints UUID, creates logs/.telemetry-active-session.json | Fix argparse or state file logic |
| 7 | [pre-deploy] | Close session via postflight CLI | `python -m scripts.session_postflight --close-session --outcome success` | Prints confirmation, removes state file, OpsWriter outbox has telemetry_sessions entry | Fix close logic or OpsWriter call |
| 8 | [pre-deploy] | run_skill with --session-id attaches to parent | `python -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-platform-telemetry-manual-workflow.md --session-id 00000000-0000-0000-0000-000000000001 --phase-order 2 --model gemini-3-flash-preview 2>&1 ; echo "exit:$?"` | Skill runs and telemetry phase/model_call records reference the supplied session_id (check outbox files) | Fix session_id threading in run_skill |
| 9 | [post-deploy] | Compact outbox to Iceberg and query Athena | `AWS_PROFILE=company-aws-profile S3_LOG_BUCKET=bblake-platform-agent-logs python -c "from scripts.ops_writer import OpsWriter; print(OpsWriter().compact_all())"` | Compaction reports telemetry_sessions records written | Fix OpsWriter config or S3 permissions |
| 10 | [post-deploy] | Query telemetry_sessions_current view via Athena | `AWS_PROFILE=company-aws-profile python -c "import boto3; s=boto3.Session(profile_name='company-aws-profile'); c=s.client('athena',region_name='eu-west-2'); r=c.start_query_execution(QueryString='SELECT session_id, workflow, outcome FROM trading_formulas_db.telemetry_sessions_current LIMIT 5',WorkGroup='agent-platform-production',QueryExecutionContext={'Database':'trading_formulas_db'}); print('QueryExecutionId:', r['QueryExecutionId'])"` | Query submits successfully (returns QueryExecutionId) | Fix table name, workgroup, or IAM permissions |
| 11 | [post-deploy] | Preflight health check queries Athena successfully | `AWS_PROFILE=company-aws-profile python -c "from scripts.session_preflight import check_telemetry_health; h=check_telemetry_health(); print(h)"` | Returns dict with health metrics (may show 0 sessions if first run, but no exceptions) | Fix Athena query or error handling |
| 12 | [pre-deploy] | Lambda build succeeds without deleted script | `python -m scripts.build_lambda` | Build completes, zip created without session_telemetry.py | Fix _LAMBDA_SCRIPTS list |
| 13 | [post-deploy] | Lambda deploy and smoke test | `python -m scripts.build_lambda --deploy && python -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Deploy succeeds, smoke test passes | Fix Lambda packaging or handler imports |

## Constraints
- No IAM users (Decision 36/37) -- Athena queries use SSO profile
- Athena engine v3 workgroup (`agent-platform-production`) required for Iceberg queries
- Preflight Athena queries must degrade gracefully when SSO is expired (return "unknown" severity, never crash)
- Postflight telemetry emission must be best-effort (never fail session close)
- Legacy file deletion must not break any remaining import -- sweep ALL references first
- Windows-compatible: no bash-specific operations in the write paths
- `run_skill.py` is at `scripts/agent_development/run_skill.py` -- it is NOT in the executor self-modification boundary (Decision 44 defines the boundary as `scripts/executor/*.py`). We are only adding CLI args; the telemetry functions it already imports are unchanged.

## Context
- Phase A (Foundation) is deployed: all 7 `telemetry_*` Iceberg tables exist in `trading_formulas_db`, Athena views are created
- Phase B (Executor Instrumentation) is implemented: `scripts/executor/telemetry.py` has the full lifecycle API (`open_session`, `close_session`, `open_phase`, `close_phase`, `emit_step`, `emit_model_call`, etc.)
- The executor has NOT yet run against the new tables (executor is cost-prohibitive until token optimisation lands), so `telemetry_sessions` is empty. The VP for this plan will populate it via manual CLI invocations.
- The `.session-telemetry.jsonl` file is 12MB with 37% duplicates (shown by preflight CRIT). Replacing it with the Iceberg pipeline eliminates both the size and duplicate problems.
- `run_skill.py` already imports from `scripts.executor.telemetry` and calls `open_session/close_session` -- we just need to make it accept a parent session_id from the caller.
- Migration to Antigravity (Google's VS Code fork) means workflows are now in `.agents/workflows/`. The plan/implement workflows call `run_skill.py` for the critique gate. The session lifecycle is: preflight opens -> interactive work -> run_skill (critique) -> postflight closes.
- Decision 51 (Local-First Outbox + Bidirectional Sync) governs the write path: OpsWriter -> local outbox -> S3 staging -> Iceberg compaction.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Part 1: Session Lifecycle CLI

1. **Add state file mechanism** -- Create a helper in `scripts/session_preflight.py`:
   - New function `open_telemetry_session(workflow: str, branch: str) -> str` that:
     - Calls `from scripts.executor.telemetry import open_session`
     - Opens a session with `workflow=workflow, branch=branch`
     - Writes `{"session_id": "<uuid>", "workflow": "<workflow>", "branch": "<branch>", "started_at": "<iso>"}` to `logs/.telemetry-active-session.json`
     - Returns the session_id
   - New argparse flag `--open-session` with required `--workflow` and `--branch` args
   - When `--open-session` is passed: call `open_telemetry_session()`, print the UUID to stdout, and exit (do NOT run the normal preflight report)

2. **Add close-session to postflight** -- In `scripts/session_postflight.py`:
   - New function `close_telemetry_session(outcome: str, files_changed: int = 0, lines_added: int = 0, lines_removed: int = 0) -> None` that:
     - Reads `logs/.telemetry-active-session.json` (if missing, log warning and return)
     - Calls `from scripts.executor.telemetry import close_session`
     - Calls `close_session(outcome=outcome, premium_requests_total=0.0, files_changed=files_changed, lines_added=lines_added, lines_removed=lines_removed)`
     - Deletes the state file
   - New argparse flag `--close-session` with required `--outcome` arg
   - When `--close-session` is passed: call `close_telemetry_session()`, print confirmation, and exit
   - Remove dead `token_budget.py` references: delete `_run_token_budget_script()` (line 321), `run_token_budget()` (line 327), `--token-budget` CLI flag (line 763), and the `_run_token_budget_script()` call in `run_metrics()` (line 448)

3. **Wire run_skill.py to accept parent session context** -- In `scripts/agent_development/run_skill.py`:
   - Add `--session-id` and `--phase-order` optional args to argparse
   - If `--session-id` is provided: instead of calling `open_session()`, set `_ctx.session_id = args.session_id` directly (import `get_context` from `scripts.executor.telemetry`)
   - If `--phase-order` is provided: pass it to `open_phase(phase_order=args.phase_order)` instead of hardcoded `1`
   - If `--session-id` is provided: skip `close_session()` call (parent owns the session lifecycle)

### Part 2: Preflight Health Check Migration

4. **Replace `check_telemetry_health()` in `scripts/session_preflight.py`** -- Rewrite to query Athena:
   - Remove all code that reads `TELEMETRY_FILE` (`.session-telemetry.jsonl`) and `RETRO_LITE_FILE`
   - New implementation queries `telemetry_sessions_current` via `boto3.client('athena')`:
     - Query: `SELECT COUNT(*) as total, SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as success_count, MAX(started_at) as latest FROM trading_formulas_db.telemetry_sessions_current WHERE trade_date >= CURRENT_DATE - INTERVAL '7' DAY`
     - Use workgroup `agent-platform-production`
     - Poll for query completion (max 10 seconds)
     - If SSO expired or Athena unreachable: return `{"overall": "unknown", "checks": [{"check": "athena-query", "value": "unavailable", "severity": "unknown"}]}`
   - Return health dict with: session count, success rate, latest session staleness
   - Add a "Friction Patterns" sub-query on `telemetry_process_events`: `SELECT category, description, COUNT(*) as occurrences FROM trading_formulas_db.telemetry_process_events WHERE trade_date >= CURRENT_DATE - INTERVAL '7' DAY GROUP BY category, description ORDER BY occurrences DESC LIMIT 5` -- include results in the health dict under key `friction_patterns` (empty list if no events or SSO expired)
   - Remove `TELEMETRY_FILE` and `RETRO_LITE_FILE` constants
   - Remove `run_friction_analysis()` and `run_token_budget()` functions (and their subprocess calls in the main report generation)
   - Remove `FRICTION_ANALYSIS_SCRIPT`, `TOKEN_BUDGET_SCRIPT`, and `METRICS_ANALYSIS_SCRIPT` constants
   - Remove `run_metrics_analysis()` function (line 483) and its call site at line 1005
   - Remove or replace report dict keys that reference deleted variables: `friction_patterns` (line ~1024), `metrics_anomalies` (line ~1025), `token_anomalies` (line ~1026) -- either remove these keys entirely or source `friction_patterns` from the new Athena health check's `friction_patterns` key; `metrics_anomalies` and `token_anomalies` have no replacement and should be removed

### Part 3: Legacy Removal

5. **Gut `_capture_executor_telemetry()` in `scripts/execute_recommendation.py`** -- The executor already writes telemetry via `scripts/executor/telemetry.py` (Phase B), making this function dead code. Changes:
   - Delete the import `from scripts.session_telemetry import write_session_envelope` (line 94)
   - Delete the import `from scripts.run_retro_lite import run_append as _retro_append` (line 93)
   - Replace the function body of `_capture_executor_telemetry()` (line 256) with a single `return` statement (no-op stub) -- keep the function signature so the 10+ call sites don't need changes
   - Do NOT touch the 10+ call sites (they call a harmless no-op; full removal is a follow-up refactor)

6. **Remove `write_session_envelope` from `scripts/session_metrics.py`** -- Delete the import and the call to `write_session_envelope(...)` near line 268. The postflight `--close-session` now handles this.

7. **Delete legacy scripts** -- Remove these files:
   - `scripts/session_telemetry.py`
   - `scripts/friction_analysis.py`
   - `scripts/run_retro_lite.py`
   - `scripts/transcript_index.py`
   - `scripts/token_budget.py`
   - `scripts/metrics_analysis.py`

8. **Delete legacy test files** -- Remove these files:
   - `tests/test_session_telemetry.py`
   - `tests/test_friction_analysis.py`
   - `tests/test_run_retro_lite.py`
   - `tests/test_transcript_index.py`
   - `tests/test_token_budget.py`
   - `tests/test_metrics_analysis.py`

9. **Sweep all remaining references** -- Search and fix:
    - `grep -rn "session_telemetry\|friction_analysis\|run_retro_lite\|transcript_index\|token_budget\|metrics_analysis" scripts/ tests/ .github/ .agents/ --include="*.py" --include="*.md" --include="*.yaml"`
    - Update `copilot-instructions.md` file router table (remove entries for deleted scripts)
    - **Remove `"session_telemetry.py"` from `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py` (line 48)** -- this is required because the deleted script was Lambda-packaged; failing to remove it will break `build_lambda.py`
    - Update `scripts/session_preflight.py` to remove subprocess calls to deleted scripts
    - Update `.agents/workflows/implement.md` -- remove `run_retro_lite` reference (line 63)
    - Update `config/README.md` -- remove references to deleted scripts (lines 313-314)
    - Update `docs/ARCHITECTURE.md` -- remove `run_retro_lite.py` references (lines 154, 161, 175)
    - Update `docs/AGENT_WORKFLOW.md` -- remove references to `run_retro_lite.py` and `_capture_executor_telemetry()` (line 209)
    - Do NOT modify `docs/CHANGELOG.md` -- historical references should be left untouched
    - Run `python -m scripts.build_lambda` to confirm the zip builds without the deleted script

### Part 4: Test Updates

10. **Update `tests/test_session_preflight.py`** -- Replace tests for old `check_telemetry_health()`:
    - Mock `boto3.Session` and Athena client for the new Athena-based health check
    - Test: Athena returns session data -> health metrics computed correctly
    - Test: Athena unreachable (ClientError) -> returns `overall: "unknown"` gracefully
    - Test: `--open-session` flag creates state file with correct schema
    - Remove all tests that reference `TELEMETRY_FILE`, `RETRO_LITE_FILE`, `run_friction_analysis`, `run_token_budget`, or `run_metrics_analysis`

11. **Update `tests/test_session_postflight.py`** -- Add `--close-session` tests:
    - Mock `scripts.executor.telemetry.close_session`
    - Test: state file exists -> close_session called with correct args, state file removed
    - Test: state file missing -> warning logged, no crash
    - Remove tests for `_run_token_budget_script()` and `run_token_budget()` and `--token-budget` flag

12. **Update `tests/test_session_metrics.py`** -- Verify no test explicitly asserts `write_session_envelope` is called (none exists -- the function was exercised as an unasserted side effect via `_run_main_with_steps`). After Step 6 removes the call from source, tests pass without changes. This step is effectively a no-op but should be confirmed by running the tests.

13. **Update `tests/test_execute_recommendation.py`** -- Remove dead telemetry tests:
    - Delete `TestCaptureExecutorTelemetry` class (line 2842) -- tests old behaviour that no longer exists
    - Update **9** mock locations that `patch("scripts.execute_recommendation._capture_executor_telemetry")` (lines 485, 4289, 4349, 5113, 5255, 6393, 6480, 6565, 6666) -- these mocks are still valid (patching the no-op) but verify they don't assert specific call args from the old implementation. Use `grep -n` rather than relying on this count.

### Part 5: Validation

14. Run `python -m pytest tests/test_session_preflight.py tests/test_session_postflight.py tests/test_session_metrics.py tests/test_execute_recommendation.py -x -q --tb=short` -- all tests must pass

15. Run `python -m scripts.validate` -- must exit 0

16. **Execute Verification Plan** -- run each step from the VP table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

17. Report: what was implemented, verification results (actual outcomes), bugs found and fixed
