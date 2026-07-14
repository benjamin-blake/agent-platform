# Plan

## Intent
Stand up the Phase 1 substrate for the cc-scheduled-agents migration: file the architectural decision that scheduled-agent findings flow through the existing `ops_recommendations` table (via the `source` field) and the existing outbox drain, then build the `ops_data_portal --enqueue-findings <path>` interface that lets a Claude Code scheduled agent commit a per-run findings JSONL whose entries are later drained to canonical recs by SSO-enabled sessions. Advances the North Star by replacing the brittle Lambda findings-processor pipeline with one consistent ingestion path through the existing portal + outbox + Iceberg + Athena view stack.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/cc-scheduled-agents-phase-1

## Phase
Platform (parallel with the schema-backfill workstream); Phase 1 of the strategic plan at `docs/plans/PLAN-cc-scheduled-agents.md`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/DECISIONS.md` | Modify | File the architectural decision FIRST: scheduled-agent findings flow through `ops_recommendations` (via `source` field) and the existing outbox drain (no new table); `ops_priority_queue_current` is the canonical priority-queue read view; findings-processor Lambda will be retired in Phase 5 (decision recorded now, action in Phase 5). |
| `.gitignore` | Modify | Add carve-out exception so `logs/.ops-outbox/**/*.json` files are tracked. The agent's PR commit must include any pending outbox entries it produced; the next SSO-enabled session drains them. Keep the carve-out tight to avoid tracking lockfiles or scratch files. |
| `scripts/ops_data_portal.py` | Modify | Add `enqueue_findings(path: Path) -> dict` Python function and `--enqueue-findings <path>` CLI flag. Reads a JSONL of one finding per line; for each entry, calls the existing `file_rec()` happy path (which transparently routes online -> DynamoDB ID + OpsWriter, offline -> outbox + pending-uuid placeholder). Returns counts: `{enqueued: N, invalid: M, skipped: P}`. MUST NOT raise on per-entry schema failures -- one bad finding must not corrupt a whole run. |
| `tests/test_ops_data_portal.py` | Modify | New tests covering: (a) bulk enqueue in offline mode populates the outbox with one `*.json` per valid entry; (b) schema-invalid entries are reported as `invalid`, not raised; (c) CLI parses the path arg and invokes the function with correct counts; (d) empty / missing input file is reported as `skipped`, not crashed. |
| `docs/plans/PLAN-cc-scheduled-agents.md` | Modify | Append a "Phase 1 Implementation Summary" section: what was built, design adjustments made during implementation (including the strategic-plan correction that no new Iceberg table or new view was needed), gotchas encountered (e.g. the `_rn` ambiguity in `ops_recommendations_current` surfaced at preflight; the dual view definition in Terraform vs `ops_writer.py:553`), commit references, and an explicit pointer to which Open Questions are now closed. Future Phase 2-5 planning agents read this section in their `## Context`. |

Plus two single-step CLI actions (no scope file):
- Mark rec-589 (`Monitor or optimize Athena polling bottleneck in Lambda dispatcher`) as `superseded` via `python -m scripts.ops_data_portal --update-rec rec-589 --status superseded --resolution "superseded by cc-scheduled-agents migration"`.
- Probe-test the `.gitignore` exception by creating then removing a probe file under `logs/.ops-outbox/ops_recommendations_pending/`.

## Bundled Recommendations
- **rec-589** (Monitor or optimize Athena polling bottleneck in Lambda dispatcher) -- closed as `superseded` during this plan's execution. The Lambda dispatcher whose polling this rec called out is being retired through this migration; the rec is moot.
- **rec-595** (Document `_delete_postmortems_from_iceberg` 120s blocking poll) -- NOT bundled. Lives in `ops_data_portal.py`, independent of this migration. Stays open.

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda code in scope. The decision to drop the originally-planned `ops_agent_findings` Iceberg table and the redundant `ops_priority_queue_latest_run` view (already exists as `ops_priority_queue_current`) is captured in DECISIONS.md.

## Acceptance Criteria
- [ ] DECISIONS.md contains a new dated entry recording: (a) findings flow through `ops_recommendations.source`, (b) `ops_priority_queue_current` is canonical, (c) findings-processor Lambda will be retired in Phase 5. Entry references this plan and its parent strategic plan.
- [ ] `.gitignore` carve-out for `logs/.ops-outbox/**/*.json` is in place; `git check-ignore logs/.ops-outbox/ops_recommendations_pending/probe.json` returns non-zero (i.e. NOT ignored).
- [ ] `scripts/ops_data_portal.py` exposes `enqueue_findings(path)` and the `--enqueue-findings <path>` CLI flag. Function returns a dict with `enqueued`, `invalid`, `skipped` keys (integers).
- [ ] `enqueue_findings` does not raise when given a JSONL containing per-entry schema failures; the failures are counted as `invalid`.
- [ ] `enqueue_findings` does not raise on missing/empty input file; reports `skipped`.
- [ ] New unit tests in `tests/test_ops_data_portal.py` pass.
- [ ] Offline round-trip verified: synthetic JSONL of 3 valid + 1 invalid finding produces 3 `*.json` files in `logs/.ops-outbox/ops_recommendations_pending/` and a returned `{enqueued: 3, invalid: 1, skipped: 0}`.
- [ ] Online drain verified (SSO available): `python -m scripts.ops_data_portal --drain` allocates real `rec-NNN` IDs for the 3 staged entries; Athena query against `ops_recommendations_current` returns the new entries with `source='cc-scheduled-agent-test'` (or whatever sentinel is used for the round-trip).
- [ ] Existing `ops_priority_queue_current` view remains queryable: `SELECT count(*) FROM trading_formulas_db.ops_priority_queue_current` returns a non-error result.
- [ ] rec-589 status is `superseded` in `ops_recommendations_current`.
- [ ] `.venv/Scripts/python.exe -m scripts.validate --quick` passes.
- [ ] `docs/plans/PLAN-cc-scheduled-agents.md` has a "Phase 1 Implementation Summary" section with: what was built, design adjustments, gotchas, closed Open Questions list (Q1, Q2, Q4, Q5 at minimum), and commit references.
- [ ] All work committed on branch `agent/cc-scheduled-agents-phase-1`; PR opened against `main`.
- [ ] Code review (`code-review` skill) returns no Critical or High findings.

## Verification Plan

All steps run pre-merge against the agent branch. V3 because the round-trip exercises real DynamoDB ID allocation, real S3/OpsWriter staging, and real Athena query against the operational catalog. Replace `<TS>` with the actual run timestamp where shown.

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Run new unit tests in isolation | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -v -k enqueue_findings` | All `enqueue_findings` tests pass; covers happy-path + invalid + missing-file + CLI dispatch | Failing tests -- read pytest output; if behaviour mismatch, fix the function; if expectation mismatch, fix the test |
| 2 | [pre-deploy] | `.gitignore` carve-out functional | `mkdir -p logs/.ops-outbox/ops_recommendations_pending && echo '{}' > logs/.ops-outbox/ops_recommendations_pending/probe.json && git check-ignore logs/.ops-outbox/ops_recommendations_pending/probe.json; echo "exit=$?"; rm logs/.ops-outbox/ops_recommendations_pending/probe.json` | `git check-ignore` exits non-zero (i.e. NOT ignored), printed `exit=1` | Carve-out wrong -- inspect `.gitignore`; ensure `!logs/.ops-outbox/**/*.json` follows the broader `logs/.ops-outbox/` rule |
| 3 | [pre-deploy] | Offline bulk enqueue round-trip | `printf '%s\n' '{"title":"test rec 1","file":"x.py","status":"open","source":"cc-scheduled-agent-test","effort":"XS","priority":"Low","context":"phase1 verify","acceptance":"n/a","risk":"low"}' '{"title":"test rec 2","file":"y.py","status":"open","source":"cc-scheduled-agent-test","effort":"XS","priority":"Low","context":"phase1 verify","acceptance":"n/a","risk":"low"}' '{"title":"test rec 3","file":"z.py","status":"open","source":"cc-scheduled-agent-test","effort":"XS","priority":"Low","context":"phase1 verify","acceptance":"n/a","risk":"low"}' '{"missing_required_fields":true}' > /tmp/findings_probe.jsonl && AWS_PROFILE= .venv/Scripts/python.exe -m scripts.ops_data_portal --enqueue-findings /tmp/findings_probe.jsonl` | Stdout reports `enqueued: 3, invalid: 1, skipped: 0`; `ls logs/.ops-outbox/ops_recommendations_pending/*.json \| wc -l` shows 3 (or current count + 3) | Counts mismatch -- check enqueue_findings handles both online happy-path and offline outbox path; ensure `AWS_PROFILE=` empty forces offline branch |
| 4 | [pre-deploy] | Online drain allocates real rec IDs | `aws sso login --profile company-aws-profile && AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -m scripts.ops_data_portal --drain` | Stdout reports `drained: 3` (or higher if other pending entries exist); the 3 probe files are deleted from `ops_recommendations_pending/` | DynamoDB unreachable -- confirm SSO; if drain skips, inspect logs for schema validation failure on the probe entries |
| 5 | [pre-deploy] | Athena query confirms drained entries land in canonical view | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -c "import awswrangler as wr; df = wr.athena.read_sql_query(\"SELECT id, title, source FROM ops_recommendations_current WHERE source = 'cc-scheduled-agent-test'\", database='trading_formulas_db', workgroup='agent-platform-production'); print(df)"` | DataFrame contains exactly 3 rows with `source='cc-scheduled-agent-test'` and titles matching the probe entries | View shows 0 rows -- give Iceberg compaction time (postflight may need to run); if still 0 after `python -m scripts.session_postflight --close-session --outcome success`, check OpsWriter staging in S3 |
| 6 | [pre-deploy] | Existing priority-queue view remains healthy | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -c "import awswrangler as wr; df = wr.athena.read_sql_query('SELECT count(*) AS n FROM ops_priority_queue_current', database='trading_formulas_db', workgroup='agent-platform-production'); print(df)"` | Non-error result; row count is whatever today's queue contains (>=1 expected) | View errors -- this would be a regression unrelated to this plan; STOP and report (we did not modify view DDL) |
| 7 | [pre-deploy] | rec-589 marked superseded | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -m scripts.ops_data_portal --update-rec rec-589 --status superseded --resolution "superseded by cc-scheduled-agents migration"` followed by `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -c "import awswrangler as wr; df = wr.athena.read_sql_query(\"SELECT id, status FROM ops_recommendations_current WHERE id = 'rec-589'\", database='trading_formulas_db', workgroup='agent-platform-production'); print(df)"` | Stdout reports update success; Athena query returns one row with `status='superseded'` | Update fails -- confirm rec-589 still exists; if Athena lag, run the query again after a brief wait |
| 8 | [pre-deploy] | Cleanup probe entries from rec log | `AWS_PROFILE=company-aws-profile .venv/Scripts/python.exe -m scripts.ops_data_portal --update-rec <id-N> --status declined --resolution "phase1 verification probe -- not a real rec"` for each of the 3 allocated rec IDs from step 5 | Each probe rec is now `status=declined`; `SELECT count(*) FROM ops_recommendations_current WHERE source='cc-scheduled-agent-test' AND status='open'` returns 0 | Probe recs left in `open` status -- that's a soft-fail; humans can clean up post-merge but the plan should leave the rec log clean |
| 9 | [pre-deploy] | Validate (quick mode) | `.venv/Scripts/python.exe -m scripts.validate --quick` | Exit 0 | Validation failure -- read the report and fix; do not skip |
| 10 | [pre-deploy] | DECISIONS.md entry committed | `git log --oneline -- docs/DECISIONS.md \| head -1 && grep -c "scheduled-agent findings" docs/DECISIONS.md` | Recent commit hash printed; grep returns 1 or higher | Entry missing or wrong wording -- edit the file and recommit |
| 11 | [pre-deploy] | Strategic plan updated with Phase 1 summary | `grep -c "^# Phase 1 Implementation Summary" docs/plans/PLAN-cc-scheduled-agents.md` | Returns 1 or higher | Section missing -- append it as the final ordered execution step |
| 12 | [pre-deploy] | Code review pass | Invoke the `code-review` skill on the branch (per `implement` workflow) | No Critical or High findings; Mediums triaged | Critical/High findings -- address per the implement workflow's review gate |

## Constraints
- **Single Portal Invariant** (CLAUDE.md): all canonical writes go through `ops_data_portal`. The new `enqueue_findings` function is part of the portal -- it does not bypass it. Direct edits to `logs/.recommendations-log.jsonl` are forbidden as always.
- **Never on main** (CLAUDE.md): no edits or commits while on `main`. Hook `.claude/hooks/never_on_main.py` enforces this.
- **No new Iceberg table or new Athena view**: the strategic plan's original Phase 1 spec proposed a new `ops_agent_findings` table and a new `ops_priority_queue_latest_run` view. Both are dropped: the existing `ops_recommendations.source` field discriminates findings, and `ops_priority_queue_current` already implements the latest-run-by-`queue_run_id` semantic. This plan files that decision in DECISIONS.md before implementation begins.
- **`enqueue_findings` must be schema-tolerant**: a single bad finding must not crash a whole run. Per-entry validation failures are counted, not raised. The function MAY log warnings.
- **Outbox carve-out must be tight**: only `logs/.ops-outbox/**/*.json` -- not the directory itself, not other extensions. Avoid tracking scratch files or future lockfiles.
- **No PowerShell in agent-facing scripts**: all commands and tests in this plan use Bash syntax.
- **ASCII only**: no em dashes, no emojis. Plain `-` hyphens.
- **No rescue agents or workaround loops** (Decision 55).

## Context

### Strategic plan
Parent strategic plan at `docs/plans/PLAN-cc-scheduled-agents.md`. Phase 1 substrate, per its Phase Manifest. The strategic plan is REPORT-ONLY and frames 5 phases; this plan implements Phase 1.

### What already exists (verified during this planning session)
- `ops_priority_queue` Iceberg table (`terraform/iceberg_tables.tf:925-947`) with the `queue_run_id`-keyed schema the strategic plan assumed had to be built.
- `ops_priority_queue_current` Athena view (`terraform/iceberg_tables.tf:1042-1051`) implementing `WHERE queue_run_id = (SELECT queue_run_id FROM ops_priority_queue ORDER BY last_updated_timestamp DESC LIMIT 1)`. This is the strategic plan's `ops_priority_queue_latest_run` -- already done, just under a different name. Notably uses a subquery filter, NOT `ROW_NUMBER()`, so it sidesteps the `_rn` ambiguity affecting `ops_recommendations_current`.
- The same view is also created by `OpsWriter.create_views_if_not_exist()` at `scripts/ops_writer.py:553-558` -- duplication is benign (idempotent CREATE OR REPLACE) but worth noting; do not add a third place to maintain.
- `s3_log_store.py:240-252` already auto-enriches priority-queue entries with `queue_run_id` (UUIDv4) and routes via OpsWriter to the Iceberg table.
- `sync_ops.py:47` maps `ops_priority_queue` -> `ops_priority_queue_current` for drain reads.
- `ops_data_portal.file_rec` (`scripts/ops_data_portal.py:51-91`) handles offline DynamoDB by queueing to `logs/.ops-outbox/ops_recommendations_pending/<uuid>.json` with a `pending-<uuid>` placeholder return; `drain_pending` allocates real IDs when SSO is available. The `Recommendation` schema includes a `source` field (used today for `executor-postmortem`). The drain function has source-aware dedup logic.

### What does NOT exist (must be built)
- `enqueue_findings(path)` Python function and `--enqueue-findings <path>` CLI flag in `scripts/ops_data_portal.py`. The CLI today exposes only: `--file-rec`, `--update-rec`, `--file-decision`, `--update-decision`, `--drain`, `--purge-postmortems-for`.

### Open Questions closed by Phase 1 vs deferred
| Strategic plan Q | Status | Where answered |
|------------------|--------|----------------|
| Q1: Is `logs/.ops-outbox/` gitignored? | CLOSED | Confirmed YES at `.gitignore:115`. This plan adds the carve-out. |
| Q2: Exact `ops_data_portal` enqueue interface | CLOSED | New: `enqueue_findings(path) -> dict` Python function + `--enqueue-findings <path>` CLI. |
| Q4: New table OR extend `ops_recommendations`? | CLOSED | Extend (use existing `source` field). No new table. Architectural rationale captured in the new DECISIONS.md entry. |
| Q5: Does the new view risk the same `_rn` ambiguity? | CLOSED | No new view. Existing `ops_priority_queue_current` uses a subquery filter, not `ROW_NUMBER`. The `_rn` bug in `ops_recommendations_current` is a pre-existing issue tracked separately. |
| Q3, Q6, Q7, Q8, Q9, Q10 | DEFERRED to Phase 2/3/4/5 per the strategic plan's manifest. |

### Decisions register implications (relative to the strategic plan's Decisions Register)
- The strategic plan's D4 ("Per-run timestamped findings files at `logs/agents/{name}/{ts}.jsonl`") still holds: the agent's per-run JSONL is the human-readable audit artifact committed in the agent's PR. Phase 1's `enqueue_findings` is the portal entrypoint that routes those entries to the outbox.
- A new implicit decision (filed in DECISIONS.md by step 1 of execution): findings flow through `ops_recommendations` via the existing `source` field; no new Iceberg table; no new Athena view.
- D8 (findings-processor retirement) is recorded in DECISIONS.md but the action is deferred to Phase 5. Recording the decision now anchors the intent.

### Known gotchas (from the codebase and this session)
- **`_rn` ambiguity in `ops_recommendations_current`**: surfaced at preflight in this very session (`INVALID_VIEW: Column '_rn' is ambiguous`). The Terraform definition uses `row_num`, but the stored view in Glue references `_rn` -- likely a stale definition or a column collision. Out of scope here but threatens preflight. Track as a separate rec post-merge; do NOT touch the view in this plan.
- **Iceberg integer promotion** (CLAUDE.md `terraform/CLAUDE.md`): if a column was previously written as `bigint`, redeclaring as `int` fails. Not relevant to this plan since no DDL changes, but Phase 2/3/4 must respect this.
- **`PYTEST_CURRENT_TEST` no-ops OpsWriter** (`scripts/ops_writer.py:178-179`): tests that exercise the portal must be aware that S3 writes are skipped under pytest. Use mocks or assert against the outbox-only path.
- **Telemetry pipeline staleness**: latest preflight reported `latest-session-staleness: 112.8h` (warning). This is plan-time observation; not a blocker for Phase 1 but Phase 2/3 work should keep an eye on whether telemetry is still flowing.
- **The dual view definition** (Terraform AND `ops_writer.py`): if a future plan needs to change `ops_priority_queue_current` semantics, it must be changed in BOTH locations or the runtime-applied definition will overwrite the Terraform one (or vice versa). Either consolidate to one source-of-truth or accept the duplication; out of scope here.

### Why the strategic plan was over-spec'd
The strategic plan was written without a deep audit of `terraform/iceberg_tables.tf` and the existing Athena views. It correctly identified the architectural goals but proposed a new table and new view that already existed in essence. This plan corrects course in the DECISIONS.md entry (a permanent record) and the strategic-plan summary (a back-reference for Phases 2-5).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently on `agent/cc-scheduled-agents-phase-1`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/DECISIONS.md` read (for format and active-decisions context).
- [ ] `docs/plans/PLAN-cc-scheduled-agents.md` (parent strategic plan) read in full.
- [ ] All files in Scope table located and readable: `scripts/ops_data_portal.py`, `tests/test_ops_data_portal.py` (or equivalent), `.gitignore`, `docs/DECISIONS.md`, `docs/plans/PLAN-cc-scheduled-agents.md`.
- [ ] AWS SSO available for V3 verification (`aws sso login --profile company-aws-profile`).
- [ ] Acceptance Criteria understood and verifiable.

## Ordered Execution Steps

1. **File the architectural decision in `docs/DECISIONS.md` FIRST** (decision precedes implementation). Append a new Decision entry with: title (e.g. "Scheduled-agent findings flow through ops_recommendations via the source field"); rationale (existing offline-resilient outbox + existing source discriminator + existing dedup logic + no new table to maintain); references (parent strategic plan, this plan, the Open Questions Q4 closure); status `closed`. Use existing DECISIONS.md format conventions (read the file to confirm).

2. **Update `.gitignore`** to add the carve-out: a line `!logs/.ops-outbox/**/*.json` placed AFTER the existing `logs/.ops-outbox/` ignore line so the negation takes effect. Verify with `git check-ignore` against a probe path (Verification step 2 covers this).

3. **Implement `enqueue_findings` in `scripts/ops_data_portal.py`**:
   - Function signature: `def enqueue_findings(path: Path, profile: Optional[str] = None) -> dict`.
   - Reads the JSONL one line at a time. Skips blank lines and lines starting with `#`.
   - For each parsed entry: call `file_rec(entry, profile=profile)` inside a try/except. Catch `ValidationError` (count as `invalid`) and `OSError`/`json.JSONDecodeError` per line (count as `skipped`).
   - Returns `{"enqueued": int, "invalid": int, "skipped": int}`.
   - If `path` does not exist or is empty, return `{"enqueued": 0, "invalid": 0, "skipped": 0}` -- no raise.

4. **Wire the CLI flag in `scripts/ops_data_portal.py`**:
   - Add `--enqueue-findings PATH` to the mutually-exclusive action group alongside `--drain` etc.
   - In `main()` dispatch: when set, call `enqueue_findings(Path(args.enqueue_findings), profile=args.profile)` and print the returned counts as JSON or as `enqueued: N, invalid: M, skipped: P`.

5. **Add unit tests in `tests/test_ops_data_portal.py`**:
   - `test_enqueue_findings_offline_bulk`: tmp dir, valid 3-entry JSONL, monkeypatch `_next_id` to raise (force offline path), assert `{enqueued: 3, invalid: 0, skipped: 0}` and 3 files in `_PENDING_OUTBOX`.
   - `test_enqueue_findings_invalid_entries_counted_not_raised`: mixed JSONL (2 valid + 1 missing-required-field + 1 malformed JSON), assert `{enqueued: 2, invalid: 1, skipped: 1}` and no exception escapes.
   - `test_enqueue_findings_missing_path`: pass non-existent path, assert `{enqueued: 0, invalid: 0, skipped: 0}` and no raise.
   - `test_cli_enqueue_findings_dispatches`: invoke `main()` with `--enqueue-findings <path>`, assert function called once with that path.

6. **Run unit tests** (Verification step 1). Loop on failures.

7. **Run offline round-trip** (Verification step 3). Loop on failures.

8. **Online drain + Athena verification** (Verification steps 4-5). Requires SSO; loop on failures. If repeated drain failures and root cause cannot be diagnosed, stop and analyse (Decision 55).

9. **Mark rec-589 superseded** (Verification step 7).

10. **Run remaining verification steps 6, 8, 9** (priority-queue view health, cleanup probe recs, validate --quick).

11. **Update `docs/plans/PLAN-cc-scheduled-agents.md`**: append a "Phase 1 Implementation Summary" section near the end of the file (before any final critique-outcome marker). The section MUST contain:
    - **What was built**: the `enqueue_findings` function and CLI; the `.gitignore` carve-out; the DECISIONS.md entry; the rec-589 supersede.
    - **What was NOT built (and why)**: the originally-spec'd `ops_agent_findings` table and `ops_priority_queue_latest_run` view -- both unnecessary; explain that the existing `source` field and the existing `ops_priority_queue_current` view satisfy the architectural intent.
    - **Open Questions closed**: Q1, Q2, Q4, Q5 (with one-line answers each).
    - **Gotchas observed**: `_rn` ambiguity in `ops_recommendations_current` (out of scope, separate rec recommended); dual definition of `ops_priority_queue_current` in Terraform vs `ops_writer.py:553` (consolidation deferred).
    - **Commit references**: the squashed-merge SHA of this PR (to be filled in at merge time).
    - **For Phases 2-5**: a one-paragraph orientation pointing to the new Decisions register entry and noting that the substrate is now the existing `ops_recommendations` table + `ops_priority_queue_current` view -- no further substrate work.
    Verification step 11 confirms section presence.

12. **Code review pass** (Verification step 12). Address Critical/High findings before merge.

13. **Execute Verification Plan** end-to-end -- run each step. Loop until pass. If V3 fails unrecoverably (e.g. drain repeatedly skips with no diagnosable cause), stop and run RCA per Decision 55.

14. **Report**: in the PR description, summarise what was implemented, link to the DECISIONS.md entry, and reference the Phase 1 Implementation Summary in the strategic plan.
