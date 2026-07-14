# Plan

## Intent
Wire the telemetry session lifecycle (`--open-session` / `--close-session`) into every interactive workflow prompt, closing the Phase D gate from `docs/INTENT-telemetry-system.md`: "Both manual and executor sessions appear in the same `telemetry_sessions` table." This is the feedback sensor that closes the RSI loop -- without it, the system cannot measure half of all work.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/platform-telemetry-workflow-wiring

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/prompts/plan.prompt.md | Modify | Add `--open-session` after preflight, replace retro-lite override reference with telemetry process event |
| .github/prompts/implement.prompt.md | Modify | Add `--open-session` after preflight, replace deleted `run_retro_lite` friction capture with `emit_process_event` CLI, add `--close-session` at session end |
| .agents/workflows/plan.md | Modify | Add `--open-session` after preflight Step 1, add `--close-session` to Step 10 |
| .agents/workflows/implement.md | Modify | Add `--open-session` after preflight Step 1, update friction capture Step 7 to remove retro-lite fallback, add `--close-session` at session end |
| .agents/skills/planning/SKILL.md | Modify | Remove retro-lite reference from critique override friction logging |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `grep -q "\-\-open-session" .github/prompts/plan.prompt.md` exits 0
- [ ] `grep -q "\-\-open-session" .github/prompts/implement.prompt.md` exits 0
- [ ] `grep -q "\-\-open-session" .agents/workflows/plan.md` exits 0
- [ ] `grep -q "\-\-open-session" .agents/workflows/implement.md` exits 0
- [ ] `grep -q "\-\-close-session" .github/prompts/implement.prompt.md` exits 0
- [ ] `grep -q "\-\-close-session" .agents/workflows/implement.md` exits 0
- [ ] `! grep -q "run_retro_lite" .github/prompts/implement.prompt.md` exits 0 (deleted script reference removed)
- [ ] `! grep -q "retro-lite-log" .github/prompts/plan.prompt.md` exits 0 (replaced with telemetry)
- [ ] `python -m scripts.validate --quick` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Open a telemetry session via the exact command the updated prompts instruct | `source .venv/Scripts/activate && python -m scripts.session_preflight --open-session --workflow plan --branch agent/platform-telemetry-workflow-wiring` | Prints a UUID to stdout; creates `logs/.telemetry-active-session.json` with `session_id`, `workflow`, `branch`, `started_at` fields | If no UUID printed, check `open_telemetry_session` function in `session_preflight.py` |
| 2 | [pre-deploy] | Confirm a telemetry_sessions record was written to the outbox | `python -c "import pathlib, json; files=list(pathlib.Path('logs/.ops-outbox/telemetry_sessions').glob('*.jsonl')); assert len(files)>=1, f'Expected outbox file, found {len(files)}'; rec=json.loads(files[-1].read_text(encoding=\"utf-8\").strip().split(chr(10))[-1]); assert rec['workflow']=='plan', f'Wrong workflow: {rec[\"workflow\"]}'; assert rec['outcome']=='running', f'Wrong outcome: {rec[\"outcome\"]}'; print(f'PASS: session {rec[\"session_id\"]} workflow={rec[\"workflow\"]} outcome={rec[\"outcome\"]}')"` | Prints `PASS: session <uuid> workflow=plan outcome=running` | If no outbox file, check `OpsWriter.emit` is not suppressed by `PYTEST_CURRENT_TEST` |
| 3 | [pre-deploy] | Close the session via the exact command the updated prompts instruct | `python -m scripts.session_postflight --close-session --outcome success` | Prints `[close-session] outcome=success`; `logs/.telemetry-active-session.json` is removed | If state file persists, check `close_telemetry_session` in `session_postflight.py` |
| 4 | [pre-deploy] | Confirm the finalised session record has outcome=success in the outbox | `python -c "import pathlib, json; files=list(pathlib.Path('logs/.ops-outbox/telemetry_sessions').glob('*.jsonl')); lines=[l for f in files for l in f.read_text(encoding='utf-8').strip().split(chr(10)) if l.strip()]; recs=[json.loads(l) for l in lines]; final=[r for r in recs if r.get('outcome')=='success']; assert len(final)>=1, f'No success record found in {len(recs)} total records'; print(f'PASS: found {len(final)} completed session(s)')"` | Prints `PASS: found 1 completed session(s)` | If only `running` records, `close_session` did not emit update |
| 5 | [pre-deploy] | Confirm no references to deleted `run_retro_lite` in any modified file | `grep -r "run_retro_lite" .github/prompts/plan.prompt.md .github/prompts/implement.prompt.md .agents/workflows/plan.md .agents/workflows/implement.md .agents/skills/planning/SKILL.md; echo "exit:$?"` | `exit:1` (no matches found) | Remove any remaining references |
| 6 | [pre-deploy] | Full validation passes | `source .venv/Scripts/activate && python -m scripts.validate --quick` | Exit 0 | Fix whatever validate reports |

## Constraints
- No Python code changes -- all edits are to `.md` prompt/workflow files
- Both VS Code (`.github/prompts/`) and Antigravity (`.agents/`) must be updated in parallel until migration is complete
- `run_retro_lite.py` was deleted in Phase D (PR #266) -- all references must be replaced, not left as dead links
- `session_postflight.py --close-session` is best-effort by design (never crashes session close) -- prompts should reflect this
- Windows compatibility: all VP commands use `source .venv/Scripts/activate` (Git Bash) since this is a Windows host
- The develop-executor workflow (`.agents/workflows/develop-executor.md`) is out of scope -- it's a short RCA flow without a session lifecycle

## Context
- Phase A (Foundation) deployed all 7 `telemetry_*` Iceberg tables in `trading_formulas_db`
- Phase B (Executor Instrumentation) implemented `scripts/executor/telemetry.py` with `open_session`, `close_session`, `open_phase`, `close_phase`, `emit_step`, `emit_model_call`, `emit_process_event`, `emit_transcript`
- Phase C (Scheduled Agents) instrumented Lambda handlers
- Phase D (Manual Workflow) added `--open-session` to `session_preflight.py`, `--close-session` to `session_postflight.py`, and `--session-id` to `run_skill.py` -- but never updated the prompts that call them
- The example session on `agent/platform-architecture-split` confirmed zero telemetry was captured: no outbox entries, no active session file, and the agent fell back to directly writing `.retro-lite-log.jsonl` because `run_retro_lite.py` no longer exists
- Decision 51 (Local-First Outbox) governs the write path: OpsWriter -> local outbox -> S3 staging -> Iceberg compaction
- `run_skill.py` already accepts `--session-id` and `--phase-order` for attaching to a parent session (Phase D)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Update `.agents/workflows/plan.md` (Antigravity)

After the preflight `python scripts/session_preflight.py` block in Step 1, add a new sub-step that opens the telemetry session:

```
After preflight completes successfully, open a telemetry session:
\```bash
python -m scripts.session_preflight --open-session --workflow plan
\```
Save the printed UUID -- if you later invoke `run_skill` (e.g., for the critique gate), pass `--session-id <UUID>` to attach its telemetry to this session.
```

In Step 10 (Confirm), after outputting the confirmation message, add a session-close step:

```
Finally, close the telemetry session:
\```bash
python -m scripts.session_postflight --close-session --outcome success
\```
If the session was abandoned or the plan was not written, use `--outcome cancelled` instead.
```

### Step 2: Update `.agents/workflows/implement.md` (Antigravity)

After the preflight block in Step 1, add the same `--open-session` sub-step but with `--workflow implement`:

```
After preflight completes successfully, open a telemetry session:
\```bash
python -m scripts.session_preflight --open-session --workflow implement
\```
Save the printed UUID for use with `--session-id` in any `run_skill` invocations during this session.
```

In Step 7 (Capture Friction), replace the retro-lite fallback. The current text says "or append to `logs/.retro-lite-log.jsonl` if telemetry is unavailable". Remove that fallback clause -- `run_retro_lite.py` no longer exists. The step should exclusively reference the telemetry API:

```
Record friction as a process event via the executor telemetry API:
\```bash
python -c "
from scripts.executor.telemetry import emit_process_event
emit_process_event(tier='rework', category='<category>', severity='warning', description='<description>', detected_by='manual')
"
\```
If no friction occurred, this step is a no-op.
```

After Step 8 (Report), add a session-close step (or append to Step 8):

```
Finally, close the telemetry session:
\```bash
python -m scripts.session_postflight --close-session --outcome success
\```
Use `--outcome failure` if the session ended with unresolved errors. Use `--outcome cancelled` if abandoned.
```

### Step 3: Update `.github/prompts/plan.prompt.md` (VS Code)

After the Step 1 preflight section (after the condition-based responses), add:

```
After all preflight conditions are handled, open a telemetry session:
\```bash
python -m scripts.session_preflight --open-session --workflow plan
\```
Save the printed UUID. Pass `--session-id <UUID>` to any `run_skill` invocations (e.g., critique gate in Step 9).
```

In Step 9, replace the retro-lite friction reference. The current text at line 351 says: `log the override as friction in .retro-lite-log.jsonl`. Replace with: `emit the override as a process event via 'python -c "from scripts.executor.telemetry import emit_process_event; emit_process_event(tier='decision', category='critique_skip', severity='info', description='Human overrode critique gate', detected_by='manual')"'`.

In Step 10 (Confirm), after the confirmation messages, add:

```
Finally, close the telemetry session:
\```bash
python -m scripts.session_postflight --close-session --outcome success
\```
```

### Step 4: Update `.github/prompts/implement.prompt.md` (VS Code)

After the Step 0 preflight section, add:

```
After preflight completes, open a telemetry session:
\```bash
python -m scripts.session_preflight --open-session --workflow implement
\```
Save the printed UUID for `--session-id` in any `run_skill` invocations.
```

In Step 7 (Capture Friction), replace the entire `run_retro_lite` block (lines 246-260). The deleted script `scripts/run_retro_lite.py` must be replaced with the telemetry API:

```
Record friction as a structured process event:
\```bash
python -c "
from scripts.executor.telemetry import emit_process_event
emit_process_event(tier='rework', category='<CATEGORY>', severity='warning', description='<DESCRIPTION>', detected_by='manual')
"
\```
Use a category from the canonical enum in `docs/INTENT-telemetry-system.md`. If no friction, this step is a no-op.
```

Remove the `git add logs/.retro-lite-log.jsonl` / `git commit` / `git push` block that follows -- friction is now captured in the outbox, not in a git-tracked JSONL file.

After Step 8 (Report), add:

```
Finally, close the telemetry session:
\```bash
python -m scripts.session_postflight --close-session --outcome success
\```
```

### Step 5: Update `.agents/skills/planning/SKILL.md` (Antigravity)

This file does not currently contain explicit retro-lite references (the critique override friction logging is in the workflow file, not the skill). Confirm by grepping -- if no retro-lite references exist, this step is a no-op.

### Step 6: Run `python -m pytest tests/ -x -q --tb=short` -- all tests must pass

### Step 7: Run `python -m scripts.validate --quick` -- must exit 0

### Step 8: **Execute Verification Plan** -- run each step from the VP table above. The implementing agent should use the commands verbatim. VP1 and VP3 will exercise the exact lifecycle that the updated prompts describe, bootstrapping telemetry usage as verification. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

### Step 9: Clean up outbox test data. After VP passes, remove the test telemetry records from the outbox so they don't pollute production data:
```bash
rm -rf logs/.ops-outbox/telemetry_sessions/
```

### Step 10: Report: what was implemented, verification results (actual outcomes), bugs found and fixed
