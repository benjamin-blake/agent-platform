# Plan

## Intent
Complete cc-scheduled-agents Phase 2 (Reader Migration): shift `session_preflight.read_priority_queue()` from a local-JSONL read to a direct `ops_priority_queue_current` Athena view query, add automatic SSO login recovery so infrastructure errors surface immediately rather than silently falling back, and update `docs/contracts/log-storage.md` to reflect the post-Phase-1 write path. Closes the gap between the documented architecture (view-as-canonical) and the actual implementation (file-as-primary), advancing the North Star by eliminating silent error masking and establishing the Athena view as the unambiguous single source of truth.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/cc-scheduled-agents-phase-2

## Phase
Platform (parallel with Phase 2 schema backfill)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/session_preflight.py` | Modify | (a) Auto-invoke `aws sso login --profile company-aws-profile` when `check_sso_status()` returns `"expired"`, then re-verify; hard-exit if still expired or `"unavailable"`. (b) Refactor `read_priority_queue()`: query `ops_priority_queue_current` via `_run_athena_query`; hard-exit on `None` (query failure). Remove JSONL fallback entirely. (c) Add `priority_queue_source` field (`"athena"`) to the preflight report JSON. |
| `docs/contracts/log-storage.md` | Modify | Replace the Priority Queue producer description (legacy rec-curator → findings_processor → S3 overwrite) with the cc-scheduled-agent flow (agent → `enqueue_findings` → outbox → `ops_priority_queue` Iceberg → `ops_priority_queue_current` view). Declare `ops_priority_queue_current` as the canonical read source. Mark local JSONL as a write-only outbox buffer -- no longer a read source for any consumer. |
| `tests/test_session_preflight.py` | Modify | Add `TestReadPriorityQueueAthena`: Athena-success path returns correctly shaped dicts; `_run_athena_query` returning `None` triggers `SystemExit`; `check_sso_status` returning `"expired"` triggers the SSO login subprocess before retry. Remove or update existing `TestReadPriorityQueue` file-based tests that exercise the now-deleted JSONL path. |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `read_priority_queue()` no longer contains any JSONL file-read branch; all reads go through `_run_athena_query("SELECT ... FROM trading_formulas_db.ops_priority_queue_current ...")`.
- [ ] `_run_athena_query` returning `None` from inside `read_priority_queue()` causes `session_preflight` to print a clear diagnostic and exit with code 1.
- [ ] When `check_sso_status()` returns `"expired"` at preflight startup, `aws sso login --profile company-aws-profile` is automatically invoked before any Athena calls proceed; if the subsequent re-check returns anything other than `"ok"`, preflight hard-exits with code 1.
- [ ] `check_sso_status()` returning `"unavailable"` (CLI missing / unknown profile) triggers an immediate hard-exit with a distinct error message -- no login attempt.
- [ ] Preflight report JSON contains `"priority_queue_source": "athena"` when the view path is taken.
- [ ] `docs/contracts/log-storage.md` names `ops_priority_queue_current` as the canonical read source and accurately describes the cc-scheduled-agent write path. The findings_processor description is moved to a "Legacy (deprecated)" subsection, not deleted (strangler-fig: it is still operational).
- [ ] All new `TestReadPriorityQueueAthena` tests pass; `python -m scripts.validate --quick` is clean.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Unit tests: Athena success path | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py::TestReadPriorityQueueAthena -v` | All pass | Fix implementation |
| 2 | [pre-deploy] | Unit tests: hard-fail on None | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py -k "hard_fail or sso_login" -v` | All pass | Fix implementation |
| 3 | [pre-deploy] | Static check: JSONL path removed | `grep -n "PRIORITY_QUEUE_FILE" scripts/session_preflight.py` | Zero matches (constant definition may remain but no read site) -- if matches remain, trace caller | Remove any remaining file-read branch from `read_priority_queue()` |
| 4 | [pre-deploy] | Live Athena query reaches view | `.venv/Scripts/python.exe -c "import scripts.session_preflight as sp; r=sp._run_athena_query('SELECT rec_id, rank FROM trading_formulas_db.ops_priority_queue_current LIMIT 5'); print('OK rows:', len(r)) if r is not None else print('FAIL: None')"` | Prints `OK rows: N` (N may be 0 if queue is empty; None is a failure) | View unavailable -- check Athena / Terraform; do NOT mask with fallback |
| 5 | [pre-deploy] | Full preflight uses Athena path | `.venv/Scripts/python.exe -m scripts.session_preflight && .venv/Scripts/python.exe -c "import json; d=json.load(open('logs/.preflight-report.json')); print(d.get('priority_queue_source', 'MISSING'))"` | Prints `athena` | `priority_queue_source` not set -- add field to report construction |
| 6 | [pre-deploy] | Contract updated | `grep -c "ops_priority_queue_current" docs/contracts/log-storage.md` | `>= 1` | Update contract file |
| 7 | [pre-deploy] | validate clean | `.venv/Scripts/python.exe -m scripts.validate --quick` | 0 failures | Fix lint/test errors |

## Constraints
- Context document: `docs/plans/PLAN-cc-scheduled-agents.md`. This plan is Phase 2 of 5.
- Decision 61: scheduled-agent findings flow through `ops_recommendations` via `source` field. Unchanged by this plan.
- Decision 57: SSO-unavailable fallback is an explicit architectural decision. Hard-fail replaces the prior "warn and continue" posture for the priority-queue read specifically. For other preflight checks (telemetry health, rec count) the existing Athena-or-degrade posture is preserved -- this plan does not change those.
- No JSONL dedup workaround in `count_recommendations()`. The `ops_recommendations_current` `_rn` ambiguity is tracked as a separate RCA rec (filed this session). Fix the root cause, not the symptom.
- Auto-SSO-login is only triggered on `"expired"` -- not `"unavailable"`. `"unavailable"` indicates a different failure class (CLI missing, wrong profile) that requires human investigation, not a login prompt.
- `aws sso login` is intentionally interactive (opens a browser tab). Add a comment in code noting this; no silent assumption of a headless terminal.
- The local JSONL `logs/priority-queue/.priority-queue.jsonl` is NOT deleted by this plan. It remains as a write-only outbox drain buffer. No consumer should read it after this migration.
- Q3/Q6/Q7/Q8/Q9/Q10 from the parent plan remain deferred to Phases 3-5.
- No rescue agents or workaround loops (Decision 55).

## Context
- Phase 1 merged as PR #292 (commit 054ff76). Established: `enqueue_findings()` in `ops_data_portal.py`; `.gitignore` carve-out for `logs/.ops-outbox/ops_recommendations_pending/`; Decision 61.
- Canonical priority-queue read view: `ops_priority_queue_current` (`terraform/iceberg_tables.tf:1042-1051`). Filters by latest `queue_run_id` via correlated subquery. No `_rn` ambiguity (uses correlated subquery, not ROW_NUMBER).
- `_run_athena_query(sql)` (`session_preflight.py:175-289`): returns `list[dict]` on success, `None` on any failure. Already used at lines 299 and 618. `read_priority_queue()` becomes the third call site.
- `check_sso_status()` (`session_preflight.py:144`): returns `"ok"`, `"expired"`, or `"unavailable"`.
- `read_priority_queue()` (`session_preflight.py:396-438`): current implementation branches on `get_backend() == "s3"` (S3 Lambda path) then falls back to local JSONL. Both branches are replaced by the Athena query.
- RCA rec filed this session: `_rn`/`row_num` dual-column ambiguity in `ops_recommendations_current` -- Terraform view DDL not applied to live Glue catalog; schema evolution re-injection risk to be assessed. This rec is separate from Phase 2 and must NOT be addressed inline here.
- `docs/contracts/log-storage.md:67-77` still describes the legacy findings_processor pipeline. Phase 1's write-path change must be reflected there without deleting the legacy section (strangler-fig: findings_processor still active until Phase 5).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read in full
- [ ] `docs/DECISIONS.md` read (especially Decision 57, 61)
- [ ] `scripts/session_preflight.py` read in full (lines 144-290, 396-438, and the `run_preflight()` or `main()` entry point to understand where `check_sso_status()` is called)
- [ ] `tests/test_session_preflight.py` `TestReadPriorityQueue` class read in full
- [ ] `docs/contracts/log-storage.md` read in full
- [ ] Confirm `ops_priority_queue_current` view returns expected columns by running VP step 4 before writing code
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Run VP step 4 first (pre-code)**: confirm `_run_athena_query("SELECT ... FROM trading_formulas_db.ops_priority_queue_current LIMIT 5")` returns rows (not None) against live Athena. Record the actual column names returned -- use these when writing the parser in step 2. If it returns None, stop; the view has an infrastructure problem that must be resolved before writing code.
2. **`scripts/session_preflight.py` -- SSO auto-login**: locate where `check_sso_status()` is called in the preflight entry point. Add logic: if status is `"expired"`, print a message, invoke `subprocess.run(["aws", "sso", "login", "--profile", _ATHENA_PROFILE], check=False, timeout=300)`, re-call `check_sso_status()`, and if still not `"ok"`, print error and `sys.exit(1)`. If original status was `"unavailable"`, print distinct error and `sys.exit(1)` immediately (no login attempt). Add an inline comment that `aws sso login` is interactive and opens a browser.
3. **`scripts/session_preflight.py` -- `read_priority_queue()`**: replace the current function body with: call `_run_athena_query("SELECT rec_id, rank, rationale, north_star_impact FROM trading_formulas_db.ops_priority_queue_current ORDER BY CAST(rank AS INTEGER)")`. If result is `None`, print a clear error (`"[ERROR] ops_priority_queue_current Athena query failed -- infrastructure problem, not masking with fallback"`) and `sys.exit(1)`. Otherwise parse and return the top `max_items` entries as `{rank, rec_id, rationale, north_star_impact}` dicts. Handle Athena's string-typed returns (`rank` will arrive as a string). Add `"priority_queue_source": "athena"` to the preflight JSON report dict at the point where the priority queue result is stored.
4. **`tests/test_session_preflight.py`**: add `TestReadPriorityQueueAthena` with at least: (a) `_run_athena_query` mocked to return valid row dicts -- confirm correct output shape and rank ordering; (b) `_run_athena_query` mocked to return `None` -- confirm `SystemExit` is raised; (c) `check_sso_status` mocked to return `"expired"` -- confirm `subprocess.run` is called with `["aws", "sso", "login", "--profile", ...]`. Review existing `TestReadPriorityQueue` tests and remove any that exercise the now-deleted JSONL path; update surviving tests if needed.
5. **`docs/contracts/log-storage.md`**: in the Priority Queue section, add a new "Canonical Producer (Phase 1+)" subsection above "Cross-References" describing the cc-scheduled-agent write path. Move the existing "Cross-References" producer description under a "Legacy Producer (deprecated, active until Phase 5)" subsection. Update the Consumer line to reference `ops_priority_queue_current` directly. Update "Date Last Verified" to today (2026-05-05).
6. **Execute Verification Plan** -- run steps 1-7 in order. Loop until all pass. If VP step 4 returns `None`, stop: the view is broken and must be fixed before this migration can proceed -- do not write a fallback.
7. Report: what was implemented, VP results, any new recs filed during implementation.
