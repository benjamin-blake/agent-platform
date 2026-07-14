# Plan

## Intent
Make scheduled agent Lambda invocations and their local-runner equivalents fully observable in the telemetry star schema, closing the last major gap in autonomous feedback-loop visibility.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-telemetry-scheduled-agents

## Phase
Phase Platform (automation infrastructure) -- Telemetry System Phase C per `docs/INTENT-telemetry-system.md`

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/data/handlers/agent_telemetry.py` | Create | Shared telemetry helper for Lambda handlers: `open_invocation()`, `close_invocation()`, `record_model_call()`. Wraps `OpsWriter.emit()` with S3-direct write path (Lambda) vs local outbox (non-Lambda). |
| `src/data/handlers/scheduled_agent_handler.py` | Modify | Import and call `open_invocation()` before each agent run, `record_model_call()` after each `_invoke_*` call, `close_invocation()` after each agent completes. Thread `invocation_id` through the loop. |
| `src/data/handlers/findings_processor_handler.py` | Modify | Import and call `open_invocation()` at handler start, `record_model_call()` around the GitHub Models comparison call, `close_invocation()` at handler return. |
| `scripts/run_scheduled_agent.py` | Modify | Replace `write_session_envelope()` call with `open_invocation()` / `close_invocation()` from agent_telemetry. Add `record_model_call()` around `copilot_sdk_inference_sync()` and `copilot_call()` invocations. |
| `tests/test_agent_telemetry.py` | Create | Unit tests for `agent_telemetry.py`: verify record schema, invocation_id threading, Lambda vs local write path selection, error safety (never raises), no-op under pytest. |
| `tests/test_scheduled_agent_handler.py` | Modify | Add assertions that `OpsWriter.emit()` is called with correct `telemetry_agent_invocations` and `telemetry_model_calls` table names and record shapes. |
| `tests/test_findings_processor_handler.py` | Modify | Add assertions that telemetry records are emitted for the processor invocation and comparison model call. |
| `scripts/build_lambda.py` | Modify | No change needed -- `ops_writer.py` and `telemetry_schemas.py` are already in `_LAMBDA_SCRIPTS`. The new `agent_telemetry.py` lives under `src/data/handlers/` which is already packaged. Verify this holds. |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] Every `scheduled_agent_handler.handler()` invocation emits one partial `telemetry_agent_invocations` record (`outcome="running"`) at start and one final record (`outcome` in `{success, failed, timeout, throttled}`) at end per agent run. The `_current` Athena view deduplicates to the latest record. Fields: `invocation_id`, `agent_name`, `trigger`, `outcome`, `model_used`, `provider`, `premium_requests`, `started_at`, `ended_at`, `duration_seconds`, `findings_count`.
- [ ] Every LLM call in both handlers emits a `telemetry_model_calls` record with `invocation_id` FK populated
- [ ] `run_scheduled_agent.py` local runs emit `telemetry_agent_invocations` via `OpsWriter.emit()` (local outbox) instead of legacy `write_session_envelope()`
- [ ] `findings_processor_handler.handler()` emits a `telemetry_agent_invocations` record for its own invocation, plus a `telemetry_model_calls` record for the comparison LLM call
- [ ] All telemetry emission is error-safe: exceptions are caught and logged, never propagated to callers
- [ ] Telemetry is suppressed when `PYTEST_CURRENT_TEST` is set (consistent with executor telemetry)
- [ ] `premium_requests` is `0.0` for Gemini BYOK calls (billed via Google API key, not GitHub)
- [ ] `pytest tests/test_agent_telemetry.py tests/test_scheduled_agent_handler.py tests/test_findings_processor_handler.py` passes
- [ ] `python -m scripts.validate` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Run new + modified unit tests | `python -m pytest tests/test_agent_telemetry.py tests/test_scheduled_agent_handler.py tests/test_findings_processor_handler.py -v` | All tests pass, 0 failures | Fix test code or implementation |
| 2 | [pre-deploy] | Run full test suite to check no regressions | `python -m pytest tests/ -v` | All tests pass | Fix regressions |
| 3 | [pre-deploy] | Validate imports and lint | `python -m scripts.validate` | Exit code 0 | Fix lint/import errors |
| 4 | [pre-deploy] | Verify agent_telemetry.py is importable in Lambda package context | `python -c "from src.data.handlers.agent_telemetry import open_invocation, close_invocation, record_model_call; print('OK')"` | Prints OK | Fix import paths |
| 5 | [pre-deploy] | Run local agent with telemetry and verify outbox file created | `python -m scripts.run_scheduled_agent --agent doc-freshness --dry-run 2>&1; ls -la logs/.ops-outbox/telemetry_agent_invocations/ 2>/dev/null; echo "exit: $?"` | Dry-run completes. If outbox dir exists (from a real run), files have correct JSON structure. Dry-run may not emit telemetry (acceptable). | Fix write path |
| 6 | [post-deploy] | Build and deploy Lambda zip | `python -m scripts.build_lambda --deploy` | Lambda updated, zip includes agent_telemetry.py | Fix build_lambda packaging if agent_telemetry.py missing |
| 7 | [post-deploy] | Invoke dispatcher Lambda with force_agent and verify telemetry in S3 staging | `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{"force_agent":"doc-freshness"}' --profile company-aws-profile --cli-binary-format raw-in-base64-out /tmp/dispatch-out.json && cat /tmp/dispatch-out.json` | Lambda returns success. Check S3: `aws s3 ls s3://agent-platform-agent-logs/staging/telemetry_agent_invocations/ --profile company-aws-profile` shows new batch file. | Fix Lambda handler telemetry emission |
| 8 | [post-deploy] | Query Athena for the telemetry_agent_invocations record | `python -c "import boto3; c=boto3.client('athena',region_name='eu-west-2'); r=c.start_query_execution(QueryString=\"SELECT invocation_id, agent_name, outcome, provider FROM trading_formulas_db.telemetry_agent_invocations WHERE trade_date = CAST(CURRENT_DATE AS VARCHAR) LIMIT 5\", WorkGroup='agent-platform-production'); print('query started:', r['QueryExecutionId'])"` | Query starts successfully. After compaction, records appear with correct agent_name, provider, outcome fields. | Fix S3 staging path or schema mismatch |

## Constraints
- Lambda handlers are stateless: no local outbox, write directly to S3 staging via `OpsWriter` (which detects `AWS_LAMBDA_FUNCTION_NAME` env var)
- `premium_requests` for Gemini BYOK calls must be `0.0` -- Gemini is billed via Google API key, not GitHub premium requests
- Copilot SDK response object does not expose `tokens_input` / `tokens_output` -- these fields will be null. Cost attribution for Gemini uses Google billing, not token-based estimation.
- The `copilot_sdk_client.py` response dict contains only `content`, `error`, `message` -- no timing metadata. Timing must be measured by the caller (start/end timestamps around the call).
- `src/data/handlers/agent_telemetry.py` must import `OpsWriter` and `telemetry_schemas` with a `try/except ImportError` guard (same pattern as `scripts/executor/telemetry.py`) so the module loads even if dependencies are missing.
- All telemetry functions must be no-ops when `PYTEST_CURRENT_TEST` is set, unless `_TELEMETRY_FORCE_EMIT` is also set.
- Windows path compatibility: use `pathlib.Path` for all paths.
- `build_lambda.py` already packages `src/data/handlers/` directory contents -- verify `agent_telemetry.py` is included automatically.
- **Provider enum standardisation:** The `provider` field in `telemetry_model_calls` and `telemetry_agent_invocations` uses underscored values matching the INTENT doc schema: `copilot_cli`, `copilot_sdk`, `github_models`, plus `gemini` (new enum value for BYOK). The `record_model_call()` helper normalises hyphens to underscores (e.g. `"copilot-sdk"` -> `"copilot_sdk"`). `gemini` is passed through as-is since it is already underscore-free. This enum extension will be back-ported to the INTENT doc in the PR description.
- **`outcome="running"` is a transient state:** The `open_invocation()` call emits a partial record with `outcome="running"` (not in the INTENT doc enum) to provide crash recovery: if Lambda crashes mid-invocation, Athena shows a record with `outcome="running"` rather than no record at all. This matches the Phase B executor telemetry pattern.

## Context
- **Phase A complete:** `OpsWriter.emit()`, all 7 telemetry schemas (`scripts/telemetry_schemas.py`), Iceberg tables + `_current` views in `terraform/iceberg_tables.tf` -- all deployed and working.
- **Phase B complete (PR #255):** `scripts/executor/telemetry.py` provides session/phase/step/model_call/process_event/transcript emission for the executor workflow. Wired into `execute_recommendation.py`, `step_runner.py`, `copilot_wrapper.py`, `postflight.py`.
- **Gemini BYOK migration (PR #256):** All 6 scheduled agents now use `provider: gemini` with Copilot SDK BYOK. Pattern: `copilot_sdk_inference_sync(prompt, model, pat, provider_config={"type":"openai","base_url":"https://generativelanguage.googleapis.com/v1beta/openai/","api_key":gemini_key})`.
- **Decision 49:** Copilot SDK as Lambda inference provider. Gemini BYOK is the active path.
- **Decision 51:** Local-first outbox + bidirectional sync. OpsWriter handles Lambda vs local detection internally.
- **Intent doc:** `docs/INTENT-telemetry-system.md` Phase C specification.
- **Existing tests:** `tests/test_scheduled_agent_handler.py` (830 lines), `tests/test_findings_processor_handler.py` (326 lines) -- both will need mock updates for telemetry emission.
- **Legacy dual-write:** `run_scheduled_agent.py` currently calls `write_session_envelope()` from `scripts/session_telemetry.py`. This writes to the deprecated `.session-telemetry.jsonl`. Phase C replaces this with the new telemetry path. The legacy call is removed in this plan (no dual-write needed -- Phase F cleanup will remove the entire `session_telemetry.py` module later).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create `src/data/handlers/agent_telemetry.py`

Create the shared telemetry helper module with these public functions:

**`open_invocation(agent_name, trigger, model, provider) -> str`**
- Generate a UUID `invocation_id`
- Record `started_at = datetime.now(UTC).isoformat()`
- Store `invocation_id`, `started_at`, `agent_name`, `model`, `provider` in a module-level `_InvocationContext` dataclass (similar to `TelemetryContext` in `scripts/executor/telemetry.py`)
- Emit a partial `telemetry_agent_invocations` record via `OpsWriter().emit("telemetry_agent_invocations", {...})` with `outcome="running"`, `premium_requests=0.0`
- Return the `invocation_id`

**`close_invocation(outcome, findings_count=0, recs_created=0, queue_entries_written=0, error=None, lambda_request_id=None) -> None`**
- Read `invocation_id` and `started_at` from `_InvocationContext`
- Compute `ended_at`, `duration_seconds`
- Emit a complete `telemetry_agent_invocations` record via `OpsWriter().emit()`
- Reset the context

**`record_model_call(provider, model, purpose, premium_requests=0.0, error=None, duration_seconds=None, tokens_input=None, tokens_output=None) -> None`**
- Generate a UUID `call_id`
- Read `invocation_id` from `_InvocationContext` (populate FK)
- Normalise `provider` string: replace hyphens with underscores (e.g. `"copilot-sdk"` -> `"copilot_sdk"`) for schema consistency
- Emit a `telemetry_model_calls` record via `OpsWriter().emit()`
- Both `session_id` and `phase_id` are `None` (scheduled agents are not sessions)

**Error safety:** Every public function is wrapped in `try/except Exception` -- catches and logs, never raises.

**No-op guard:** Return immediately if `PYTEST_CURRENT_TEST` is set and `_TELEMETRY_FORCE_EMIT` is not set (same pattern as `scripts/executor/telemetry.py`).

**Import safety:** Wrap `OpsWriter` and schema imports in `try/except ImportError` with a `_SCHEMAS_AVAILABLE` sentinel. Functions return early if schemas are unavailable.

**Acceptance:** `python -c "from src.data.handlers.agent_telemetry import open_invocation, close_invocation, record_model_call; print('OK')"`

---

### Step 2: Create `tests/test_agent_telemetry.py`

Write unit tests covering:

1. **`test_open_invocation_emits_record`** -- Mock `OpsWriter.emit()`, call `open_invocation()`, assert it was called with table `"telemetry_agent_invocations"` and a record dict containing `invocation_id`, `agent_name`, `trigger`, `outcome="running"`, `started_at`, `premium_requests=0.0`.
2. **`test_close_invocation_emits_complete_record`** -- Call `open_invocation()` then `close_invocation(outcome="success", findings_count=3)`. Assert second `emit()` call has `outcome="success"`, `findings_count=3`, `ended_at` is set, `duration_seconds` >= 0.
3. **`test_record_model_call_with_invocation_id`** -- Call `open_invocation()` then `record_model_call(provider="gemini", model="gemini-2.5-flash", purpose="findings")`. Assert emit was called with table `"telemetry_model_calls"` and record has `invocation_id` matching the one from `open_invocation()`.
4. **`test_record_model_call_without_invocation`** -- Call `record_model_call()` without a prior `open_invocation()`. Assert `invocation_id` is `None` in the emitted record (not an error).
5. **`test_noop_under_pytest`** -- Set `PYTEST_CURRENT_TEST` env var, unset `_TELEMETRY_FORCE_EMIT`. Call `open_invocation()`. Assert `OpsWriter.emit()` was NOT called.
6. **`test_error_safety`** -- Mock `OpsWriter.emit()` to raise `RuntimeError`. Call `open_invocation()`. Assert no exception propagates.
7. **`test_context_reset_after_close`** -- Call `open_invocation()`, `close_invocation()`. Assert internal context `invocation_id` is `None`.
8. **`test_gemini_premium_requests_zero`** -- Call `record_model_call(provider="gemini", ...)`. Assert `premium_requests=0.0` in the emitted record.

All tests must set `_TELEMETRY_FORCE_EMIT=1` in their setup (except `test_noop_under_pytest`) so the no-op guard does not suppress emission during test execution.

**Acceptance:** `python -m pytest tests/test_agent_telemetry.py -v`

---

### Step 3: Instrument `scheduled_agent_handler.py`

Modify `handler()` in `src/data/handlers/scheduled_agent_handler.py`:

1. At the top of the per-agent loop (after resolving `name`, `model`, `provider`), call:
   ```python
   from src.data.handlers.agent_telemetry import open_invocation, close_invocation, record_model_call
   invocation_id = open_invocation(
       agent_name=name, trigger="eventbridge" if not force_agent else "manual",
       model=model, provider=provider,
   )
   ```

2. After each `_invoke_*` call returns `(output, has_error, err_msg)`, measure timing and call:
   ```python
   record_model_call(
       provider=provider, model=model, purpose="findings",
       premium_requests=0.0 if provider == "gemini" else 1.0,
       error=err_msg if has_error else None,
       duration_seconds=<measured>,
   )
   ```

3. Before each `continue` (on error) or after successful write, call:
   ```python
   close_invocation(
       outcome="success" if not has_error else "failed",
       findings_count=len(findings) if not has_error else 0,
       error=err_msg if has_error else None,
       lambda_request_id=getattr(context, "aws_request_id", None),
   )
   ```

4. Ensure every exit path from the per-agent loop calls `close_invocation()` (including prompt-not-found, PAT-not-available, S3 write failure). This is critical per the "State machine exit path completeness" gotcha.

**Acceptance:** `python -m pytest tests/test_scheduled_agent_handler.py -v`

---

### Step 4: Instrument `findings_processor_handler.py`

Modify `handler()` in `src/data/handlers/findings_processor_handler.py`:

1. At the top of `handler()`, after imports, call `open_invocation(agent_name="findings-processor", trigger="s3_event", model=model, provider="github-models")`.

2. After the `chat_completion()` call for comparison, call `record_model_call(provider="github-models", model=model, purpose="comparison", premium_requests=0.0, ...)`.

3. Before each early return and at the end function, call `close_invocation(outcome=..., findings_count=len(all_findings), recs_created=appended, queue_entries_written=len(queue_entries), ...)`.

4. Handle the `skipped_comparison=True` case: still call `close_invocation(outcome="success")` -- the comparison skip is a normal path, not a failure.

**Acceptance:** `python -m pytest tests/test_findings_processor_handler.py -v`

---

### Step 5: Instrument `run_scheduled_agent.py`

Modify `run_agent()` in `scripts/run_scheduled_agent.py`:

1. Replace the `write_session_envelope()` call (around line 275) with:
   ```python
   from src.data.handlers.agent_telemetry import open_invocation, close_invocation, record_model_call
   ```
   Call `open_invocation()` at the start of `run_agent()` (after `start_time` is set), with `trigger="manual"`.

2. After the Gemini BYOK `copilot_sdk_inference_sync()` call, add `record_model_call(provider="gemini", model=model, purpose="findings", premium_requests=0.0, ...)`.

3. After the non-Gemini `copilot_call()` path, add `record_model_call(provider="copilot_cli", model=model, purpose="findings", ...)`.

4. Replace `write_session_envelope(...)` with `close_invocation(outcome=outcome, findings_count=len(findings))`.

5. Remove the `from scripts.session_telemetry import write_session_envelope` import (if it becomes unused after this change -- check if other functions in the module still use it). Remove `_TELEMETRY_KEY = ".session-telemetry.jsonl"` constant at the top of the file if also unused.

**Acceptance:** `python -m pytest tests/ -k "scheduled" -v`

---

### Step 6: Update existing handler tests

**`tests/test_scheduled_agent_handler.py`:**
- Mock `src.data.handlers.agent_telemetry.open_invocation` and `close_invocation` and `record_model_call` in all existing test classes/methods.
- Add one test verifying telemetry records are emitted with correct `agent_name`, `provider`, and `outcome` for a successful Gemini agent run.
- Add one test verifying `close_invocation(outcome="failed")` is called when an agent's API call fails.

**`tests/test_findings_processor_handler.py`:**
- Mock the three telemetry functions.
- Assert `record_model_call()` is called when comparison runs, and NOT called when comparison is skipped.

**Acceptance:** `python -m pytest tests/test_scheduled_agent_handler.py tests/test_findings_processor_handler.py -v`

---

### Step 7: Run full test suite and validate

1. Run `python -m pytest tests/ -v` -- all tests must pass.
2. Run `python -m scripts.validate` -- must exit 0.
3. Fix any ruff lint errors immediately after each file modification (batch 1-2 files, then lint).

**Acceptance:** `python -m scripts.validate`

---

### Step 8: **Execute Verification Plan**

Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

---

### Step 9: Report

Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
