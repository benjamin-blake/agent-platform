# Plan

## Intent
Close the feedback loop between recommendation generation and prioritised execution by delivering an operational end-to-end priority queue pipeline -- from rec-curator invocation through S3 storage to preflight display and ad-hoc triggering. This gives the self-improving system a decision-making organ so work is prioritised by impact rather than filing order.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-priority-queue-pipeline

## Phase
Phase Platform -- Wave 1: Priority Queue Pipeline

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/s3_log_store.py` | Modify | Add `overwrite_jsonl()` for full-file replace semantics (priority queue) |
| `tests/test_s3_log_store.py` | Modify | Tests for `overwrite_jsonl()` (local + S3 paths, PYTEST_CURRENT_TEST guard) |
| `src/data/handlers/findings_processor_handler.py` | Modify | Add `priority-queue-entry` type routing -- extract queue entries from curator findings, write to S3 via `overwrite_jsonl()` |
| `tests/test_findings_processor_handler.py` | Modify | Tests for priority-queue-entry extraction and routing |
| `.github/prompts/scheduled/rec-curator.prompt.md` | Modify | Remove Step 5 (local file write); emit queue entries as `type: priority-queue-entry` findings in Step 6 JSON array |
| `scripts/session_preflight.py` | Modify | Fix status filter from `active` to `queued`; fix S3 read key from `.priority-queue.jsonl` to `priority-queue/.priority-queue.jsonl` |
| `tests/test_session_preflight.py` | Modify | Update priority queue filter tests for `queued` status and corrected S3 key |
| `scripts/run_scheduled_agent.py` | Modify | Add `--trigger-lambda` flag for ad-hoc Lambda invocation |
| `tests/test_run_scheduled_agent.py` | Modify | Tests for `--trigger-lambda` flag |
| `.github/agents/rec-curator.agent.md` | Modify | Update description, tools, output contract to reflect pipeline (closes rec-449) |
| `.github/agents/schedule.yaml` | Modify | Change rec-curator cron from `"0 8 * * 1"` (weekly Monday) to `"0 8 * * *"` (daily) |
| `docs/contracts/log-storage.md` | Modify | Update canonical priority queue path to match Decision 45 (`priority-queue/.priority-queue.jsonl`) |

## Bundled Recommendations
- **rec-455** (open, S): Add `overwrite_jsonl()` to `s3_log_store.py`
- **rec-456** (open, Critical): Remove Step 5 local write from rec-curator prompt; emit as findings
- **rec-457** (open, Critical): `findings_processor_handler.py` add priority-queue-entry dispatch
- **rec-458** (open, Critical): Fix status filter `active` -> `queued` and S3 key path in session_preflight
- **rec-459** (open, XS): `run_scheduled_agent.py` add `--trigger-lambda` flag
- **rec-449** (open, XS): Update `rec-curator.agent.md` description

## Acceptance Criteria
- [ ] `overwrite_jsonl()` exists in `scripts/s3_log_store.py` with both S3 and local backends
- [ ] `findings_processor_handler.py` routes `type: priority-queue-entry` findings to S3 key `priority-queue/.priority-queue.jsonl` via `overwrite_jsonl()`
- [ ] `rec-curator.prompt.md` no longer instructs the agent to write `logs/.priority-queue.jsonl` directly; queue entries are emitted as `type: priority-queue-entry` in the Step 6 findings JSON array
- [ ] `session_preflight.py` filters on `queued` status (not `active`) and reads from S3 key `priority-queue/.priority-queue.jsonl`
- [ ] `run_scheduled_agent.py --trigger-lambda rec-curator` invokes the Lambda via `aws lambda invoke` and returns exit 0
- [ ] `rec-curator.agent.md` describes the new finding-based output contract
- [ ] `schedule.yaml` rec-curator cron is `"0 8 * * *"` (daily)
- [ ] `docs/contracts/log-storage.md` reflects the canonical S3 key `priority-queue/.priority-queue.jsonl`
- [ ] All `pytest tests/` pass
- [ ] `python scripts/validate.py` exits 0

## Constraints
- No terraform changes required -- existing infrastructure covers this pipeline
- No Docker -- Lambda uses zip packaging via S3
- Company SCP blocks IAM and OIDC -- Lambda + Secrets Manager only
- S3 `overwrite_jsonl()` uses `put_object` (full replace) -- safe because Lambda dispatcher runs agents sequentially
- Executor self-modification boundary (Decision 44) does not apply -- none of these files are in the boundary list
- `overwrite_jsonl()` must follow the `get_backend()` pattern from existing `append_jsonl()` and `read_jsonl()` for local/S3 switching

## Context
- **Decision 45**: S3 is source of truth for cloud-produced logs. Priority queue canonical S3 key: `priority-queue/.priority-queue.jsonl`
- **Decision 37**: Lambda + Secrets Manager pattern for automation
- **docs/contracts/log-storage.md**: Defines write patterns and status values (`queued`, `open`, `closed`, etc.)
- **Parent plan**: `docs/plans/PLAN-infra-curator-pipeline.md` (STRATEGIC) decomposed Work Areas A-E. This IMPLEMENTATION plan executes Areas B, C, D. Areas A (Decision 45) and partially E are already closed.
- **Bug 1 (rec-458)**: `session_preflight.py` line 256 filters `status == "active"` but `rec-curator.prompt.md` writes `status: "queued"` -- status mismatch means preflight always shows empty queue
- **Bug 2 (rec-456)**: `rec-curator.prompt.md` Step 5 instructs local file write -- impossible in Lambda context
- **Key path alignment (rec-458)**: Decision 45 establishes `priority-queue/.priority-queue.jsonl` as the canonical S3 key; current code and `docs/contracts/log-storage.md` use `.priority-queue.jsonl`. This plan aligns all sources to Decision 45.
- **Known gotcha**: S3 backend + local mocking pattern -- use `get_backend()` switch so local mode preserves original file paths that tests mock
- **Known gotcha**: Import safety -- never raise exceptions during module import

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] docs/contracts/log-storage.md read (status values, write patterns)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Add `overwrite_jsonl()` to `scripts/s3_log_store.py` (rec-455)
Add a new function `overwrite_jsonl(key: str, entries: list[dict]) -> bool` that:
- For S3 backend: serialises `entries` as newline-delimited JSON and calls `s3.put_object()` with the full body (replace semantics, not append)
- For local backend: writes to `_local_path(key)`, creating parent dirs with `mkdir(parents=True, exist_ok=True)`, using `"w"` mode (not `"a"`)
- Skips the write and returns `True` when `PYTEST_CURRENT_TEST` is set and backend is local (same guard as `append_jsonl`)
- Returns `True` on success, `False` on failure
- Follows the same error handling pattern as `append_jsonl()` (catch `Exception`, log, return `False`)

Add tests to `tests/test_s3_log_store.py`:
- Test local write creates file with correct content (multiple entries)
- Test local write overwrites existing file (not appends)
- Test empty entries list writes an empty file
- Test S3 path calls `put_object` with correct key and body
- Test PYTEST_CURRENT_TEST guard skips local write

**Acceptance**: `python -m pytest tests/test_s3_log_store.py -x -q`

### Step 2: Add priority-queue-entry routing to `findings_processor_handler.py` (rec-457)
Modify the `handler()` function in `src/data/handlers/findings_processor_handler.py` to:
1. After Step 1 (union findings), before Step 2 (comparison): scan `all_findings` for entries where `finding.get("type") == "priority-queue-entry"`
2. Extract those entries into a `queue_entries` list
3. If `queue_entries` is non-empty, call `overwrite_jsonl("priority-queue/.priority-queue.jsonl", queue_entries)` (import from `scripts.s3_log_store`)
4. Log: `"Wrote %d priority queue entries to S3"` or `"No priority queue entries found"`
5. Remove queue entries from `all_findings` before passing to Step 2 (comparison) so they are not double-processed as recommendations
6. Include `queue_entries_written: len(queue_entries)` in the return summary dict

Add/update tests in `tests/test_findings_processor_handler.py`:
- Test that findings with `type: priority-queue-entry` are routed to `overwrite_jsonl("priority-queue/.priority-queue.jsonl", ...)`
- Test that priority-queue entries are excluded from the comparison step
- Test that findings without `type: priority-queue-entry` continue through the existing path unchanged
- Test that mixed findings (some queue entries, some normal) are correctly split

**Acceptance**: `python -m pytest tests/test_findings_processor_handler.py -x -q`

### Step 3: Fix rec-curator prompt to emit findings instead of local writes (rec-456)
Edit `.github/prompts/scheduled/rec-curator.prompt.md`:
1. **Remove or rewrite Step 5 entirely** -- delete all instructions about writing to `logs/.priority-queue.jsonl` locally. Do not preserve the local write path.
2. In Step 6 (output JSON array), add instructions that each priority queue entry must be emitted as a finding with `"type": "priority-queue-entry"` and the schema fields: `rank`, `rec_id`, `mode`, `compound_with`, `rationale`, `gates`, `estimated_premium_requests`, `north_star_impact`, `decay_date`, `status` (value: `"queued"`)
3. Ensure the prompt states: "Do NOT write any files. All output goes in the JSON array printed to stdout."

This is a prompt edit only -- no Python code, no tests needed.

**Acceptance**: `grep -qE "priority-queue-entry" .github/prompts/scheduled/rec-curator.prompt.md && ! grep -qE "logs/\.priority-queue\.jsonl" .github/prompts/scheduled/rec-curator.prompt.md`

### Step 4: Fix session_preflight.py status filter and S3 key (rec-458)
Edit `scripts/session_preflight.py` `read_priority_queue()` function:
1. Change the S3 read path from `read_jsonl(".priority-queue.jsonl")` to `read_jsonl("priority-queue/.priority-queue.jsonl")`
2. Change the status filter from `e.get("status", "").lower() == "active"` to `e.get("status", "").lower() == "queued"`
3. Update the local file path constant `PRIORITY_QUEUE_FILE` from `ROOT / "logs" / ".priority-queue.jsonl"` to `ROOT / "logs" / "priority-queue" / ".priority-queue.jsonl"` for consistency

Update tests in `tests/test_session_preflight.py`:
- Update `TestReadPriorityQueue` tests to use `status: "queued"` instead of `status: "active"` in test data
- Update any assertions or mocks that reference the old `.priority-queue.jsonl` key to use `priority-queue/.priority-queue.jsonl`

**Acceptance**: `python -m pytest tests/test_session_preflight.py::TestReadPriorityQueue -x -q`

### Step 4b: Update log-storage contract for canonical key path
Edit `docs/contracts/log-storage.md` to update the priority queue canonical path from `.priority-queue.jsonl` to `priority-queue/.priority-queue.jsonl`, aligning with Decision 45. Ensure all path references in the contract match the new canonical path.

**Acceptance**: `grep -qE "priority-queue/\.priority-queue\.jsonl" docs/contracts/log-storage.md`

### Step 5: Add `--trigger-lambda` flag to `run_scheduled_agent.py` (rec-459)
Add a `--trigger-lambda` CLI argument to `scripts/run_scheduled_agent.py` that:
1. Accepts an agent name as its value (e.g., `--trigger-lambda rec-curator`)
2. Invokes `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{"force_agent":"NAME"}' --cli-binary-format raw-in-base64-out --profile company-aws-profile <outfile>` via `subprocess.run()` with `encoding="utf-8", errors="replace", text=True` and a temp file for the output (use `tempfile.mkstemp()` or `NamedTemporaryFile(delete=False)` -- default `delete=True` causes file locking issues on Windows; clean up the temp file in a `finally` block)
3. Reads the temp file and prints a summary of the Lambda response
4. Returns exit code 0 on success, 1 on failure

Add tests to `tests/test_run_scheduled_agent.py`:
- Test that `--trigger-lambda` constructs the correct subprocess command
- Test error handling when Lambda invocation fails
- Mock `subprocess.run` -- do not call AWS

**Acceptance**: `python -m pytest tests/test_run_scheduled_agent.py -x -q`

### Step 6: Update `rec-curator.agent.md` (rec-449) and `schedule.yaml`
Edit `.github/agents/rec-curator.agent.md`:
1. Update description to state the agent outputs a JSON array of findings to stdout, including `type: priority-queue-entry` entries
2. Remove any references to direct file writes or `logs/.priority-queue.jsonl`
3. Note that queue entries reach S3 via the findings processor pipeline, not direct writes

Edit `.github/agents/schedule.yaml`:
1. Change rec-curator cron from `"0 8 * * 1"` to `"0 8 * * *"` (daily 8am UTC)

No tests needed -- documentation and config only.

**Acceptance**: `grep -qE "priority-queue-entry" .github/agents/rec-curator.agent.md && grep -qE '"0 8 \* \* \*"' .github/agents/schedule.yaml`

### Step 7: Run full test suite
Run `pytest tests/` -- all tests must pass before proceeding.

**Acceptance**: `python -m pytest tests/ -x -q`

### Step 8: Run validation
Run `python scripts/validate.py` -- must exit 0.

**Acceptance**: `python -m scripts.validate`

### Step 9: Report
Report what was implemented and any design decisions made during implementation.
