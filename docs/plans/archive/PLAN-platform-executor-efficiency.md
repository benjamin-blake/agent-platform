# Plan

## Intent
Make the executor observable and diagnosable by populating the telemetry Iceberg star schema with real data, backfilling decisions into their queryable Athena view, and recording the architectural shift from recovery agents to root-cause-analysis agents. This closes the feedback loop: the executor already emits structured telemetry (Phase B), but the data is trapped in local JSONL files. Once queryable via Athena, any agent or human can diagnose executor efficiency problems (token waste, critique cycling, scope deadlocks) with SQL instead of grepping 12 MB of append-only JSONL.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (Integration)

## Branch
agent/platform-executor-efficiency

## Phase
Phase Platform -- Wave 2 (Telemetry Root Cause Fix) + Wave 4 architecture decision

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/backfill_ops_tables.py | Modify | Add `_parse_decisions_md()` parser, `--parse-decisions` CLI flag, `--tables` filter flag, and `telemetry_sessions` entry in `_TABLE_FILE_MAP` |
| logs/.decisions-index.jsonl | Modify | Overwritten by the parser with all decisions from DECISIONS.md (currently 1 placeholder record; expect >= 34 unique decisions) |
| docs/DECISIONS.md | Modify | Append Decision 55 (RCA-first autonomous executor architecture, supersedes Decision 46). Mark Decision 46 status as "Superseded by Decision 55". |
| docs/ROADMAP.md | Modify | Update Wave 4 deliverables to reflect the RCA agent shift and add a note to Wave 2 that Phase D data pipeline is complete |
| tests/test_backfill_ops_tables.py | Modify | Extend existing test file (162 lines, 3 test classes) with tests for `_parse_decisions_md()` and `--tables` filtering. Existing tests mock `_TABLE_FILE_MAP` -- new tests must follow the same pattern. |

## Bundled Recommendations
None. This is prerequisite infrastructure that unblocks diagnosis of multiple open executor recs (rec-519, rec-520, rec-518, and the broader token optimisation validation).

## Infrastructure Dependencies
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| telemetry_sessions (Iceberg) | No change (exists) | Yes -- OpsWriter.compact() writes to it | N/A | `SELECT COUNT(*) FROM telemetry_sessions` > 0 |
| telemetry_* views (Athena) | No change (exists) | Yes -- analytical queries read from them | N/A | `SELECT * FROM telemetry_sessions_current LIMIT 5` returns rows |
| ops_decisions (Iceberg) | No change (exists) | Yes -- backfill writes to it | N/A | `SELECT COUNT(*) FROM ops_decisions_current` >= 34 |

## Acceptance Criteria
- [ ] `logs/.decisions-index.jsonl` contains >= 34 valid JSON records (one per unique decision ID across DECISIONS.md), with all schema fields populated (decision_id, title, status, problem, decision_text, context, decided_date, related_decisions)
- [ ] `python -m scripts.backfill_ops_tables --tables ops_decisions --profile company-aws-profile --bucket agent-platform-agent-logs` succeeds and reports rows compacted > 0
- [ ] `python -m scripts.backfill_ops_tables --tables telemetry_sessions --profile company-aws-profile --bucket agent-platform-agent-logs` succeeds and reports rows compacted > 0
- [ ] Decision 55 exists in DECISIONS.md with status "Decided" and Decision 46 is marked as "Superseded by Decision 55"
- [ ] Wave 4 deliverables in ROADMAP.md reflect the RCA-first architecture
- [ ] `pytest tests/test_backfill_ops_tables.py` passes
- [ ] `python -m scripts.validate` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Validate decisions parser produces correct output | `python -m pytest tests/test_backfill_ops_tables.py::TestParseDecisionsMd -x -q` | All parser tests pass | Parser regex does not match DECISIONS.md heading format |
| 2 | [pre-deploy] | Validate decisions-index.jsonl has correct count and schema | `python -m pytest tests/test_backfill_ops_tables.py::TestParseDecisionsMd::test_real_decisions_md -x -q` | Test asserts >= 34 records with populated decision_id | Parser not extracting decision_id |
| 3 | [pre-deploy] | Run unit tests | `python -m pytest tests/test_backfill_ops_tables.py -x -q` | All tests pass | Fix test or parser logic |
| 4 | [pre-deploy] | Run full validation | `python -m scripts.validate` | Exit 0 | Fix lint/import/test failures |
| 5 | [post-deploy] | Backfill decisions to Iceberg via OpsWriter | `python -m scripts.backfill_ops_tables --tables ops_decisions --profile company-aws-profile --bucket agent-platform-agent-logs` | Reports staged > 0 and compacted > 0 | SSO expired (re-login) or S3 permission issue |
| 6 | [post-deploy] | Backfill session telemetry JSONL to telemetry_sessions Iceberg | `python -m scripts.backfill_ops_tables --tables telemetry_sessions --profile company-aws-profile --bucket agent-platform-agent-logs` | Reports staged > 0 and compacted > 0 | telemetry_sessions not in backfill table map (add if missing) |
| 7 | [post-deploy] | Query ops_decisions_current view | `aws athena start-query-execution --query-string "SELECT decision_id, title, status FROM trading_formulas_db.ops_decisions_current ORDER BY decision_id LIMIT 10" --work-group agent-platform-production --result-configuration OutputLocation=s3://agent-platform-formulas-discovery/athena-results/ --profile company-aws-profile` | Returns 10 rows with decision_id, title, status populated | Compaction failed or view definition wrong |
| 8 | [post-deploy] | Query telemetry_sessions_current view | `aws athena start-query-execution --query-string "SELECT session_id, workflow, outcome, premium_requests_total FROM trading_formulas_db.telemetry_sessions_current LIMIT 5" --work-group agent-platform-production --result-configuration OutputLocation=s3://agent-platform-formulas-discovery/athena-results/ --profile company-aws-profile` | Returns rows with session data | No telemetry data compacted yet |

## Constraints
- SSO must be active for post-deploy verification steps (aws sso login --profile company-aws-profile)
- Athena queries require the agent-platform-production workgroup (engine v3) per copilot-instructions.md
- `backfill_ops_tables.py` is NOT an executor boundary file -- safe for automated modification
- The decisions parser must handle both `## Decision N:` and `### Decision N:` heading formats (DECISIONS.md uses both)
- Parser must handle decisions in DECISIONS_ARCHIVE.md if it exists (for completeness), but core acceptance is 34 unique decisions from DECISIONS.md
- DECISIONS.md context budget rules: only open decisions stay in main file, resolved archived. Decision 55 starts as "Decided" so it will be archived in due course by strategic_review

## Context
- **Phase B complete (2026-04-22):** Executor instrumentation landed in PR #255. `scripts/executor/telemetry.py` emits structured records to OpsWriter for sessions, phases, steps, model calls, process events, and transcripts.
- **Phase C complete (2026-04-21):** Ops pipeline fix in PR #246. OpsWriter, S3 staging, and Iceberg compaction all proven working for ops_recommendations, ops_execution_plans, ops_session_log.
- **Terraform applied:** All 7 telemetry Iceberg tables + 4 current-state views + 3 analytical views exist in Athena. Created via null_resource provisioners in terraform state.
- **Data gap:** The telemetry tables are empty. Session telemetry exists only in `logs/.session-telemetry.jsonl` (20,653 append-only SCD2 records, 392 unique sessions). The decisions table has 1 placeholder record in `logs/.decisions-index.jsonl`. DECISIONS.md has 34 unique decisions (IDs 21-54, with some duplicates due to supersession headings; 35 total headings, 34 unique IDs).
- **SCD2 pattern:** The append-only write pattern is intentional (Decision 50). Each state change appends a new record with the same PK and a later `ingested_at`. The `_current` views deduplicate via `ROW_NUMBER() OVER (PARTITION BY pk ORDER BY ingested_at DESC)`. This preserves point-in-time history.
- **Token optimisation already landed:** PR #262 (2026-04-27) implemented effort-based model routing (XS/S -> Flash, M -> auto, L/XL -> Pro), session resume skip for XS/S, and warm_base skip. Config is in `config/copilot_model_routing.yaml`. The post-deploy VP steps here will confirm the optimisation works in practice by checking telemetry data from subsequent executor runs.
- **Copilot access ending April 30:** GitHub Copilot (Chat, CLI, SDK) will be severely rate-limited. Scheduled agents on Copilot SDK (claude-haiku-4.5) should continue within meagre budget. June 1 brings usage-based billing with steep multiplier increases (Opus 4.6: 3x -> 27x, Sonnet 4.6: 1x -> 9x). Gemini Flash stays cheapest at 0.33x.
- **RCA architecture shift (supersedes Decision 46):** The `/develop-executor` supervisor prompt hides executor infrastructure gaps by allowing human judgement to route around failures. The rec-449 transcript demonstrates this: a V3 misclassification in planning.prompt.md caused an unresolvable critique cycling deadlock, but the supervisor's instinct was to `--skip-critique` (workaround) rather than diagnose the root cause. Recovery agents (Decision 46's rescue agent layer) would compound this by automating workarounds. RCA agents instead diagnose WHY the happy path failed and file recommendations to fix the gap permanently. This is the SRE "blameless postmortem" pattern applied to autonomous systems. Deterministic pattern-matched recovery (git retry, ruff fix, CLI timeout retry) remains valid; LLM-powered "judgement" recovery is replaced by structured RCA. Decision 46 (Rescue Agent Architecture) is superseded: the three-outcome contract (RESOLVED/CANNOT_RESOLVE/TIMEOUT) and graduated autonomy gates are replaced by a simpler model where the executor stops cleanly and the RCA agent diagnoses without attempting repair.
- **Decision 55 rationale:** When the executor hits an unrecoverable failure, the correct response is: stop cleanly, emit a structured process event (tier=exception), and invoke an RCA agent that diagnoses the root cause and files a recommendation. This is cheaper (one diagnosis call vs N recovery attempts), simpler to test, and improvements compound permanently because each failure class is fixed once.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Add `_parse_decisions_md()`, `--parse-decisions`, `--tables` to `scripts/backfill_ops_tables.py`**
   - Add `_parse_decisions_md()` function:
     - Parse `docs/DECISIONS.md` (and `docs/DECISIONS_ARCHIVE.md` if it exists) using regex to extract decision blocks
     - Each decision block starts with `## Decision N:` or `### Decision N:` heading
     - Extract fields: `decision_id` (int), `title` (heading text after colon), `status` (from **Status:** line), `problem` (from **Problem:** section), `decision_text` (from **Decision:** section), `context` (from **Context:**/**Rationale:** section), `decided_date` (from status line or empty), `related_decisions` (from **Related:** lines, as `array<int>`)
     - Populate `ingested_at` (current UTC timestamp) and `trade_date` (today's date) per OpsWriter convention
     - Deduplicate by `decision_id` (keep latest heading if duplicates exist)
   - Add `--parse-decisions` CLI flag that calls `_parse_decisions_md()` and writes the result to `logs/.decisions-index.jsonl`, then exits
   - Add `--tables` CLI flag (comma-separated list of table names) that filters which tables are backfilled. When omitted, all tables are backfilled (existing behaviour)
   - Add `telemetry_sessions` to the `_TABLE_FILE_MAP` dict pointing to `logs/.session-telemetry.jsonl` (note: `ops_session_log` also sources from this file but writes to a different Iceberg table with a different schema/view; this is intentional)
   - Acceptance: `python -c "from scripts.backfill_ops_tables import _parse_decisions_md; print(len(_parse_decisions_md()))"` prints >= 34

2. **Run the parser to populate `logs/.decisions-index.jsonl`**
   - Execute: `python -m scripts.backfill_ops_tables --parse-decisions`
   - Verify the output file contains 34+ records with populated fields
   - Commit the updated JSONL file
   - Acceptance: `python -c "import json; lines=[json.loads(l) for l in open('logs/.decisions-index.jsonl') if l.strip()]; assert len(lines)>=34, f'Got {len(lines)}'; print('OK:', len(lines))"`

3. **Write Decision 55 in `docs/DECISIONS.md` and supersede Decision 46**
   - Title: "RCA-First Autonomous Executor Architecture (Supersedes Decision 46)"
   - Content: Document the shift from recovery agents to RCA agents for Wave 4. Key points: (a) when the executor hits an unrecoverable failure, stop cleanly + emit process event + invoke RCA agent, (b) RCA agent diagnoses root cause and files a rec, (c) deterministic pattern-matched recovery remains valid (git retry, ruff fix, CLI timeout), (d) LLM-powered judgement recovery is eliminated, (e) improvements compound because each failure class is fixed once. Reference the rec-449 transcript as the motivating case study.
   - Supersedes: Decision 46 (Rescue Agent Architecture). The three-outcome contract (RESOLVED/CANNOT_RESOLVE/TIMEOUT), graduated autonomy gates, and recursive rescue prevention are replaced by a simpler model: stop cleanly + diagnose + file rec.
   - Update Decision 46 heading to include "(Superseded by Decision 55)" and add a note at the top of its section.
   - Related: Decision 34 (state machine exit paths), Decision 46 (superseded), Decision 51 (outbox pattern).
   - Acceptance: `grep -q "Decision 55" docs/DECISIONS.md && grep -q "Superseded by Decision 55" docs/DECISIONS.md`

4. **Update Wave 4 deliverables in `docs/ROADMAP.md`**
   - Under Wave 4 (Autonomous Executor), change the deliverables list to reflect RCA-first architecture:
     - ~~Rescue agent contract and dispatcher~~ -> "RCA agent contract: diagnoses failure root cause, files recommendation"
     - ~~Acceptance repair agent~~ -> "Acceptance failure RCA agent (diagnoses why acceptance fails, files rec to fix prompt/scope rules)"
     - Keep "Failure diagnosis agent" (this IS RCA)
     - ~~Friction capture agent~~ -> "Replaced by structured process events (Phase B telemetry)"
     - Keep "Orchestrator loop with killswitch"
   - Add a note under Wave 2 that Phase D data pipeline (decisions backfill + telemetry compaction) is addressed by this plan
   - Acceptance: `grep -q "RCA" docs/ROADMAP.md`

5. **Extend `tests/test_backfill_ops_tables.py` with parser and filter tests**
   - Add `TestParseDecisionsMd` class with tests:
     - Test `_parse_decisions_md()` with a mock DECISIONS.md (tmp_path) containing 2-3 sample decisions in both `##` and `###` heading formats
     - Test that `decision_id` is extracted as int, `related_decisions` as list of ints, `status` is extracted correctly
     - Test edge cases: decision with no Problem section (should use empty string), decision with no Related line (empty list)
     - `test_real_decisions_md`: test that the parser handles the real `docs/DECISIONS.md` (assert count >= 34, all records have populated `decision_id`)
   - Add `TestTablesFilter` class to verify `--tables` flag filters correctly (mock `_stage_and_compact` and assert only the specified table is processed)
   - Follow the existing test pattern: mock `_TABLE_FILE_MAP` and `OpsWriter` where needed
   - Acceptance: `python -m pytest tests/test_backfill_ops_tables.py -x -q`

6. Run `python -m pytest tests/` -- all tests must pass

7. Run `python -m scripts.validate` -- must exit 0

8. **Execute Verification Plan** -- run each step from the table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification. Note: VP steps 5-8 are post-deploy and require active SSO session (`aws sso login --profile company-aws-profile`). VP step 6 (telemetry_sessions backfill) may require adding `telemetry_sessions` to the backfill script's table map -- if so, implement and re-test before proceeding.

9. Report: what was implemented, verification results (actual outcomes), bugs found and fixed
