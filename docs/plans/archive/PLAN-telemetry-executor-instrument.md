# Plan

## Intent
Instrument the recommendation executor workflow to emit structured telemetry via OpsWriter.emit() into the 7-table star schema established by Phase A. This wires the RSI feedback loop's observation layer so every executor session, phase, step, model call, process event, and transcript is captured as queryable Iceberg data -- enabling the autonomous anomaly detection and cost control capabilities described in the North Star.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/platform-telemetry-executor-instrument

## Phase
Phase Platform (Telemetry System -- Phase B: Executor Instrumentation)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/executor/telemetry.py | Create | TelemetryContext threading + helper functions (open/close session/phase, emit step/model call/process event/transcript). Wraps OpsWriter.emit() with telemetry-specific logic. |
| scripts/execute_recommendation.py | Modify | Wire session lifecycle (open/close) at executor entry/exit, phase lifecycle at each PHASE boundary, process events at decision/rework/exception points. |
| scripts/executor/step_runner.py | Modify | Wire step telemetry after implement_step(), transcript telemetry when transcripts are saved. |
| scripts/copilot_wrapper.py | Modify | Wire model call telemetry after each copilot_call() returns. |
| scripts/executor/postflight.py | Modify | Wire process events for scope drift, code review, CI, and merge outcomes. |
| tests/test_executor_telemetry.py | Create | Unit tests for scripts/executor/telemetry.py (TelemetryContext, all helper functions, edge cases). |
| tests/test_execute_recommendation.py | Modify | Update existing mocks to account for new telemetry.py imports; add tests verifying session/phase emit calls. |
| tests/test_executor_step_runner.py | Modify | Add tests verifying step and transcript telemetry emission. |
| tests/test_copilot_wrapper.py | Modify | Add tests verifying model call telemetry emission. |
| tests/test_executor_postflight.py | Modify | Add tests verifying process event emission for postflight scenarios. |

## Bundled Recommendations
None. (This is Phase B of the telemetry system INTENT, not driven by individual recs.)

## Acceptance Criteria
- [ ] `scripts/executor/telemetry.py` exists with TelemetryContext dataclass and open_session/close_session/open_phase/close_phase/emit_step/emit_model_call/emit_process_event/emit_transcript helpers
- [ ] Running the executor produces `telemetry_sessions` records in the local outbox (`logs/.ops-outbox/telemetry_sessions/`)
- [ ] Running the executor produces `telemetry_phases` records for each phase (preflight, plan_generation, critique, implementation, postflight)
- [ ] Running the executor produces `telemetry_steps` records for each implementation step
- [ ] Running the executor produces `telemetry_model_calls` records for each copilot_call()
- [ ] Running the executor produces `telemetry_process_events` records for decisions, rework, and exceptions
- [ ] Running the executor produces `telemetry_transcripts` records when transcript files are saved
- [ ] Legacy write paths (_capture_executor_telemetry, write_run_summary, emit_failure_summary, _append_step_telemetry, write_session_envelope) continue to function (dual-write, no removals)
- [ ] `python -m pytest tests/test_executor_telemetry.py tests/test_execute_recommendation.py tests/test_executor_step_runner.py tests/test_copilot_wrapper.py tests/test_executor_postflight.py -q` passes
- [ ] `python -m scripts.validate --ci` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Verify session open/close roundtrip produces outbox files | `python -m pytest tests/test_executor_telemetry.py::TestOpenCloseSession -q --tb=short` | All tests pass, exit code 0 | telemetry.py emit path broken -- check OpsWriter.emit imports |
| 2 | pre-deploy | Verify phase open/close produces outbox files | `python -m pytest tests/test_executor_telemetry.py::TestOpenClosePhase -q --tb=short` | All tests pass, exit code 0 | Phase emit path broken |
| 3 | pre-deploy | Run full test suite for all modified files | `python -m pytest tests/test_executor_telemetry.py tests/test_execute_recommendation.py tests/test_executor_step_runner.py tests/test_copilot_wrapper.py tests/test_executor_postflight.py -q --tb=short` | All tests pass, exit code 0 | Fix failing tests |
| 4 | pre-deploy | Run validate.py to confirm no regressions | `python -m scripts.validate --ci` | Exit code 0, no failures | Fix validation errors |

## Constraints
- **Executor boundary files (Decision 44):** All scope files are executor boundary files. This plan is implemented via /plan -> /implement, NOT the executor. The executor must not modify its own code.
- **Dual-write (INTENT doc constraint 6):** Legacy write paths (JSONL files, run summaries, failure summaries) must continue to function. No removals until Phase F.
- **Test isolation (INTENT doc constraint 7):** Telemetry writes are no-ops when PYTEST_CURRENT_TEST is set, consistent with OpsWriter behaviour. Tests mock OpsWriter.emit() directly.
- **Windows compatibility (INTENT doc constraint 8):** All outbox paths use pathlib.Path. No shell-specific operations.
- **Import safety (copilot-instructions.md):** Never raise during module import. Defer validation to explicit calls.
- **ruff compliance:** Run ruff check --fix after each file modification. Lines under 127 chars (E501).
- **Test coverage:** test_coverage_checker requires test files for ALL modified source files with 100% coverage.

## Context
- **Phase A complete:** OpsWriter.emit() exists and supports all 7 telemetry tables. TelemetrySessions/Phases/Steps/etc. dataclasses defined in scripts/telemetry_schemas.py. Iceberg tables defined in terraform/iceberg_tables.tf. _current Athena views exist.
- **Decision 51:** Local-first outbox + bidirectional sync. The write path is: emit() -> local outbox (synchronous, never fails) -> S3 staging (best-effort) -> Iceberg compaction at session close.
- **Two-write pattern:** Sessions and phases use open/close semantics (partial record at start with ended_at=None, complete record at end). Steps and model calls use single-write (they complete quickly). The ROW_NUMBER() OVER (PARTITION BY id ORDER BY ingested_at DESC) views in Athena return the latest version of each record.
- **Wave 3 alignment:** This creates scripts/executor/telemetry.py, matching the ROADMAP Wave 3 deliverable name. It extracts telemetry logic from execute_recommendation.py.
- **10 _capture_executor_telemetry call sites** in execute_recommendation.py currently handle all exit paths. Each will gain a corresponding close_session() call alongside the legacy write.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create scripts/executor/telemetry.py -- TelemetryContext and lifecycle helpers

Create `scripts/executor/telemetry.py` with:

**TelemetryContext dataclass** (module-level `_ctx` instance):
- Fields: `session_id: str | None`, `phase_id: str | None`, `phase_order: int`, `step_id: str | None`, `rec_id: str | None`, `branch: str | None`, `session_started_at: str | None`, `phase_started_at: str | None`
- `reset()` method clears all fields

**Session lifecycle:**
- `open_session(*, workflow: str, rec_ids: list[str] | None, branch: str | None, model_primary: str | None = None, execution_attempt: int = 1, parent_session_id: str | None = None) -> str`: Generates UUID session_id, stores in _ctx, emits partial TelemetrySessions record (outcome="running", ended_at=None, premium_requests_total=0.0, process_event_count=0, rework_count=0, exception_count=0), returns session_id.
- `close_session(*, outcome: str, premium_requests_total: float, failure_reason: str | None = None, failure_phase: str | None = None, steps_total: int | None = None, steps_completed: int | None = None, files_changed: int | None = None, lines_added: int | None = None, lines_removed: int | None = None, scope_drift_files: list[str] | None = None, pr_url: str | None = None, ci_outcome: str | None = None, process_event_count: int = 0, rework_count: int = 0, exception_count: int = 0) -> None`: Emits complete TelemetrySessions record with ended_at, duration_seconds computed from started_at. Calls _ctx.reset().
- `get_context() -> TelemetryContext`: Returns the current _ctx (for passing IDs to other functions).

**Phase lifecycle:**
- `open_phase(*, phase: str, phase_order: int, attempt_number: int = 1, max_attempts: int | None = None, model_used: str | None = None) -> str`: Generates UUID phase_id, stores in _ctx, emits partial TelemetryPhases record (outcome="running").
- `close_phase(*, outcome: str, premium_requests: float = 0.0, tokens_input: int | None = None, tokens_output: int | None = None, revision_count: int | None = None, blocking_findings_count: int | None = None, plan_steps_json: str | None = None, metadata_json: str | None = None) -> None`: Emits complete TelemetryPhases record with ended_at, duration_seconds.

**Single-write emitters:**
- `emit_step(*, step_number: int, total_steps: int, title: str, outcome: str, premium_requests: float, retry_count: int = 0, target_file: str | None = None, action: str | None = None, started_at: str, ended_at: str | None = None, model_used: str | None = None, tokens_input: int | None = None, tokens_output: int | None = None, acceptance_command: str | None = None, acceptance_passed: bool | None = None, diff_stat: str | None = None, lines_added: int | None = None, lines_removed: int | None = None, prompt_hash: str | None = None, transcript_path: str | None = None) -> str`: Generates step_id, emits TelemetrySteps using session_id and phase_id from _ctx.
- `emit_model_call(*, provider: str, model: str, purpose: str, premium_requests: float, timestamp: str | None = None, duration_seconds: int | None = None, tokens_input: int | None = None, tokens_output: int | None = None, exit_code: int | None = None, copilot_session_id: str | None = None, prompt_hash: str | None = None, error: str | None = None, step_id: str | None = None, invocation_id: str | None = None) -> str`: Generates call_id, emits TelemetryModelCalls.
- `emit_process_event(*, tier: str, category: str, severity: str, description: str, detected_by: str = "executor_script", rec_id: str | None = None, root_cause: str | None = None, resolution: str | None = None, time_lost_seconds: int | None = None, rec_filed: str | None = None, step_id: str | None = None) -> str`: Generates event_id, emits TelemetryProcessEvents.
- `emit_transcript(*, purpose: str, local_path: str, size_bytes: int, model_used: str | None = None, rec_id: str | None = None, token_count: int | None = None, s3_key: str | None = None, step_id: str | None = None) -> str`: Generates transcript_id, emits TelemetryTranscripts.

**All emit functions:**
- Use `OpsWriter().emit(table, record.to_dict())` under the hood
- Are wrapped in try/except that logs warnings and never raises
- Are no-ops when `os.environ.get("PYTEST_CURRENT_TEST")` is set (unless explicitly overridden for testing)
- Auto-populate session_id, phase_id from _ctx when not passed explicitly

**Acceptance:** `grep -q "class TelemetryContext" scripts/executor/telemetry.py && grep -q "def open_session" scripts/executor/telemetry.py && grep -q "def close_session" scripts/executor/telemetry.py && grep -q "def emit_step" scripts/executor/telemetry.py && grep -q "def emit_model_call" scripts/executor/telemetry.py && grep -q "def emit_process_event" scripts/executor/telemetry.py && grep -q "def emit_transcript" scripts/executor/telemetry.py`

---

### Step 2: Create tests/test_executor_telemetry.py -- Comprehensive tests for telemetry module

Create `tests/test_executor_telemetry.py` with tests covering:

- **TestTelemetryContext:** reset() clears all fields, get_context() returns the singleton
- **TestOpenCloseSession:** open_session generates UUID, emits to OpsWriter.emit with table='telemetry_sessions' and outcome='running'; close_session emits with outcome and duration_seconds computed correctly; close_session resets context
- **TestOpenClosePhase:** open_phase generates UUID, emits partial phase; close_phase emits complete phase with duration; close_phase without open_phase logs warning
- **TestEmitStep:** emit_step generates UUID, populates session_id/phase_id from context, calls OpsWriter.emit with correct table and record
- **TestEmitModelCall:** emit_model_call populates FKs from context, emits correct record
- **TestEmitProcessEvent:** emit_process_event with all tiers (decision, rework, exception, anomaly), verifies record structure
- **TestEmitTranscript:** emit_transcript populates FKs, emits correct record
- **TestNoOpInPytest:** When PYTEST_CURRENT_TEST is set, emit functions skip OpsWriter.emit (verify mock not called). Test the override mechanism for testing.
- **TestErrorHandling:** When OpsWriter.emit raises, the helper catches the exception and logs a warning (never propagates)

All tests must mock `OpsWriter.emit` via `@patch("scripts.executor.telemetry.OpsWriter")` and verify call args. Use `monkeypatch` for env vars.

**Acceptance:** `python -m pytest tests/test_executor_telemetry.py -q --tb=short`

---

### Step 3: Wire session and phase telemetry into execute_recommendation.py

Modify `scripts/execute_recommendation.py`:

**Imports:** Add `from scripts.executor.telemetry import open_session, close_session, open_phase, close_phase, emit_process_event, get_context`

**Session open:** At the start of `_execute_recommendation_inner()`, immediately after `branch = f"agent/{rec_id}"` (around line 1406), call:
```python
open_session(
    workflow="executor",
    rec_ids=[rec_id],
    branch=branch,
    execution_attempt=1,  # TODO: increment for retries
)
```

**Phase opens/closes:** At each `# ========== PHASE N:` boundary:
- PHASE 1 PREFLIGHT: `open_phase(phase="preflight", phase_order=1)` at start, `close_phase(outcome="success")` before Phase 2 (or outcome="failed" at each preflight failure return). Every preflight failure `return False` must have a `close_phase(outcome="failed")` and `close_session(outcome="failed", ...)` call before returning.
- PHASE 2 PLAN GENERATION: `open_phase(phase="plan_generation", phase_order=2)`, close with outcome based on plan result.
- PHASE 3 CRITIQUE LOOP: `open_phase(phase="critique", phase_order=3)`, close with outcome.
- PHASE 4 IMPLEMENTATION: `open_phase(phase="implementation", phase_order=4)`, close with outcome.
- PHASE 5 POSTFLIGHT: `open_phase(phase="postflight", phase_order=5)`, close with outcome.

**Session close:** At every `return True` and `return False` in `_execute_recommendation_inner()`, call `close_session()` with the appropriate outcome, premium_requests_total, failure_reason, etc. This means placing close_session() alongside each existing `_capture_executor_telemetry()` call and at the `return True` at end.

**Process events (Tier 1 -- decisions):**
- After acceptance-on-main check (already_implemented): `emit_process_event(tier="decision", category="already_implemented", severity="info", description=f"Acceptance passes on main for {rec_id}")`
- After no_changes_needed classification: `emit_process_event(tier="decision", category="no_changes_needed", severity="info", description="Model determined no changes needed")`
- After skip_to_postflight detection: `emit_process_event(tier="decision", category="skip_to_postflight", severity="info", description=f"Branch has {commits_ahead} commits ahead, skipping to postflight")`
- After model escalation in planning: `emit_process_event(tier="decision", category="model_escalation_plan", severity="warning", description=f"Escalating planning model to {_next_model}")`

**Process events (Tier 2 -- rework):**
- Inside critique loop iteration (when verdict != "approved"): `emit_process_event(tier="rework", category="critique_needs_revision", severity="info", description=f"Critique iteration {iteration+1}")`

**Process events (Tier 3 -- exceptions):**
- Critique cycling detected: `emit_process_event(tier="exception", category="critique_cycling_detected", severity="warning", description="Cycling detected, auto-approving")`
- Escalation exhausted: `emit_process_event(tier="exception", category="escalation_exhausted_plan", severity="error", description="Planning model escalation exhausted")`

**Critical constraint:** The existing `_capture_executor_telemetry()` and `write_run_summary()` calls remain unchanged. The new telemetry calls are ADDITIONS alongside the existing code, not replacements.

**Acceptance:** `grep -q "from scripts.executor.telemetry import" scripts/execute_recommendation.py && grep -q "open_session" scripts/execute_recommendation.py && grep -q "close_session" scripts/execute_recommendation.py && grep -q "open_phase" scripts/execute_recommendation.py && grep -q "close_phase" scripts/execute_recommendation.py`

---

### Step 4: Wire step and transcript telemetry into step_runner.py

Modify `scripts/executor/step_runner.py`:

**Imports:** Add `from scripts.executor.telemetry import emit_step, emit_transcript, emit_process_event, get_context`

**Step telemetry in implement_step():** After `_append_step_telemetry()` is called in `execute_recommendation.py` (after the implement_step() return), add an `emit_step()` call. However, since `implement_step()` is called from execute_recommendation.py, the cleanest approach is to emit inside `implement_step()` itself, right before the final return statement, using the data available there:

```python
# At the end of implement_step(), before return:
_step_ended = datetime.now(timezone.utc).isoformat()
emit_step(
    step_number=step_n,
    total_steps=total_steps,
    title=step.get("title", f"Step {step_n}"),
    outcome=outcome.value,
    premium_requests=result.premium_requests if result else 0.0,
    target_file=step.get("file"),
    action=step.get("action"),
    started_at=_step_started,  # captured at function entry
    ended_at=_step_ended,
    model_used=result.model if result else None,
    tokens_input=result.tokens_used if result else None,
    acceptance_command=step.get("acceptance"),
    acceptance_passed=acceptance_passed,
    diff_stat=diff_stat,
    prompt_hash=prompt_hash,
    transcript_path=result.transcript_path if result else None,
)
```

This requires capturing `_step_started = datetime.now(timezone.utc).isoformat()` at the top of `implement_step()`.

**IMPORTANT (critique warning):** `implement_step()` has multiple return paths (success, CLI error, ghost step, format error, ruff error, validate timeout, validate failed, acceptance failed). The `emit_step()` call must precede EVERY return. The recommended pattern is to use a local `_step_outcome` / `_step_reqs` variable that gets set before each return, with the emit_step() placed in a helper called at each exit point. Alternatively, use a try/finally structure where finally emits with whatever outcome was set. Missing an exit path causes a silent telemetry coverage gap for that step failure mode.

**Transcript telemetry:** When a transcript file is produced (detected by `result.transcript_path` being non-None), emit a transcript record:
```python
if result and result.transcript_path and Path(result.transcript_path).exists():
    emit_transcript(
        purpose="implementation",
        local_path=result.transcript_path,
        size_bytes=Path(result.transcript_path).stat().st_size,
        model_used=result.model,
        rec_id=rec_id,
    )
```

**Process events for step outcomes:**
- Ghost step detected: `emit_process_event(tier="decision", category="ghost_step", severity="info", description=f"Step {step_n} produced no changes")`
- Validation failure: `emit_process_event(tier="rework", category="validate_failed", severity="warning", description=f"Step {step_n} validation failed")`
- Acceptance failure: `emit_process_event(tier="rework", category="acceptance_failed", severity="warning", description=f"Step {step_n} acceptance failed")`

**Acceptance:** `grep -q "from scripts.executor.telemetry import" scripts/executor/step_runner.py && grep -q "emit_step" scripts/executor/step_runner.py && grep -q "emit_transcript" scripts/executor/step_runner.py`

---

### Step 5: Wire model call telemetry into copilot_wrapper.py

Modify `scripts/copilot_wrapper.py`:

**Imports:** Add `from scripts.executor.telemetry import emit_model_call` (use try/except ImportError to avoid breaking imports when telemetry module isn't available in Lambda context or tests).

**Instrumentation point:** At the end of `copilot_call()`, after the CopilotResult is constructed but before returning, add:
```python
try:
    emit_model_call(
        provider="copilot_cli",
        model=result.model or model or "",
        purpose=_infer_purpose(prompt),  # new helper to categorize
        premium_requests=result.premium_requests,
        timestamp=_call_started,  # captured at function entry
        duration_seconds=int((time.time() - _call_start_time)),
        tokens_input=result.tokens_used,  # OTel may split this later
        exit_code=result.exit_code,
        copilot_session_id=result.session_id,
        prompt_hash=_compute_prompt_hash(prompt),
        error=result.stderr[:500] if result.exit_code != 0 else None,
    )
except Exception:
    pass  # telemetry must never break the call path
```

**`purpose` parameter on copilot_call():** Add an optional `purpose: str = "unknown"` parameter to copilot_call() that callers pass. Update ALL callers to pass purpose:
- plan.py: generate_initial_plan -> "planning", critique_plan -> "critique", refine_plan -> "refinement"
- step_runner.py: implement_step -> "implementation"
- postflight.py: _code_review_gate -> "code_review", _fix_code_review_findings -> "code_review_fix", _fix_ci_failure -> "ci_fix"
- execute_recommendation.py: any direct copilot_call for escalation -> "escalation_diagnosis"

**Note (critique warning):** execute_recommendation.py also calls copilot_call() directly for planning/escalation paths -- these callers must also pass the purpose parameter for complete telemetry coverage.

**Timing:** Capture `_call_start_time = time.time()` and `_call_started = datetime.now(timezone.utc).isoformat()` at the top of copilot_call().

**Acceptance:** `grep -q "emit_model_call" scripts/copilot_wrapper.py && grep -q "purpose" scripts/copilot_wrapper.py`

---

### Step 6: Wire process events into postflight.py and execute_recommendation.py PHASE 5

Modify `scripts/executor/postflight.py` and `scripts/execute_recommendation.py`:

**Imports in postflight.py:** Add `from scripts.executor.telemetry import emit_process_event`

**NOTE (critique clarification):** Most postflight orchestration happens in execute_recommendation.py's PHASE 5 block, not inside postflight.py functions. Place emit_process_event() calls at the detection sites where outcomes are known:

**In postflight.py functions:**

Scope drift -- inside `_scope_drift_check()` when unplanned files found:
```python
if unplanned:
    emit_process_event(
        tier="decision",
        category="scope_drift_detected",
        severity="warning",
        description=f"{len(unplanned)} unplanned file(s): {', '.join(unplanned[:5])}",
    )
```

Code review -- inside `_code_review_gate()`:
- On pass: `emit_process_event(tier="decision", category="code_review_pass", severity="info", description="Code review passed")`

CI/merge outcomes -- inside `finalize()`:
- CI pass: `emit_process_event(tier="decision", category="ci_pass", severity="info", ...)`
- CI timeout: `emit_process_event(tier="exception", category="ci_timeout", severity="error", ...)`
- CI failure: `emit_process_event(tier="rework", category="ci_failure", severity="warning", ...)`
- Merge success: `emit_process_event(tier="decision", category="merge_success", severity="info", ...)`
- Merge failure: `emit_process_event(tier="exception", category="merge_fail", severity="error", ...)`

**In execute_recommendation.py PHASE 5 block (orchestration sites):**

- Code review fix attempt: `emit_process_event(tier="rework", category="code_review_fix_attempt", severity="warning", description=f"{len(blocking)} blocking finding(s)")`
- Code review exhausted: `emit_process_event(tier="exception", category="code_review_fail", severity="error", description=f"{len(blocking)} finding(s) remain")`
- Validation quarantine: `emit_process_event(tier="decision", category="validation_quarantine", severity="warning", description=f"Quarantined {len(quarantined_tests)} known baseline-red test(s)")`
- Validation doc-only fallback: `emit_process_event(tier="decision", category="validation_doc_only_fallback", severity="warning", ...)`
- Validation emergency bypass: `emit_process_event(tier="decision", category="validation_emergency_bypass", severity="warning", ...)`

**Acceptance:** `grep -q "emit_process_event" scripts/executor/postflight.py`

---

### Step 7: Update existing test files for new telemetry imports and mock paths

Modify the existing test files to handle the new telemetry imports:

**tests/test_execute_recommendation.py:**
- Add `@patch("scripts.execute_recommendation.open_session")`, `@patch("scripts.execute_recommendation.close_session")`, `@patch("scripts.execute_recommendation.open_phase")`, `@patch("scripts.execute_recommendation.close_phase")`, `@patch("scripts.execute_recommendation.emit_process_event")` to existing test classes that exercise `_execute_recommendation_inner`.
- Add a new test class `TestSessionTelemetry` with tests:
  - `test_session_opened_on_entry`: Verify open_session is called once with workflow="executor"
  - `test_session_closed_on_success`: Verify close_session called with outcome on success path
  - `test_session_closed_on_failure`: Verify close_session called with failure_reason on failure path
  - `test_phases_opened_and_closed`: Verify open_phase/close_phase called for each phase

**tests/test_executor_step_runner.py:**
- Add `@patch("scripts.executor.step_runner.emit_step")`, `@patch("scripts.executor.step_runner.emit_transcript")`, `@patch("scripts.executor.step_runner.emit_process_event")` to relevant test classes.
- Add test verifying emit_step is called after implement_step completes.

**tests/test_copilot_wrapper.py:**
- Add `@patch("scripts.copilot_wrapper.emit_model_call")` to copilot_call tests.
- Add test verifying emit_model_call is called with correct provider/model/purpose.

**tests/test_executor_postflight.py:**
- Add `@patch("scripts.executor.postflight.emit_process_event")` to relevant tests.
- Add test verifying process events for scope drift, review outcomes.

**Acceptance:** `python -m pytest tests/test_execute_recommendation.py tests/test_executor_step_runner.py tests/test_copilot_wrapper.py tests/test_executor_postflight.py tests/test_executor_telemetry.py -q --tb=short`

---

### Step 8: Run pytest -- all tests must pass

```bash
python -m pytest tests/ -q --tb=short
```

All tests must pass. Fix any failures introduced by the telemetry wiring.

**Acceptance:** `python -m pytest tests/ -q --tb=short`

---

### Step 9: Run validate.py -- must exit 0

```bash
python -m scripts.validate --ci
```

Must exit 0. Fix any ruff, coverage, or structural issues.

**Acceptance:** `python -m scripts.validate --ci`

---

### Step 10: Execute Verification Plan

Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

---

### Step 11: Report

Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
