# Plan

## Intent
Create the strategic anchor document `docs/INTENT-ops-decisions-graduation.md`
for the multi-phase arc that migrates `ops_decisions` to portal-first architecture
and decommissions `docs/DECISIONS.md`. This planning session is REPORT-ONLY; no
code changes are produced here. Each phase below becomes its own /plan session.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
agent/ops-decisions-graduation-intent

## Phase
Phase Platform (operational data governance arc, parallel to the existing DQ
enforcement maturity arc tracked in `docs/INTENT-dq-enforcement.md`).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/INTENT-ops-decisions-graduation.md | Create | Strategic anchor for the graduation arc; modelled on `docs/INTENT-dq-enforcement.md` |
| docs/INTENT-dq-enforcement.md | Modify | Cross-link to the new graduation arc; flag in Phase 4 Session Map that `ops_decisions` is now scoped under its own INTENT |
| docs/plans/PLAN-ops-decisions-graduation-intent.md | Create | This plan |

## Bundled Recommendations
None. Open recommendations adjacent to this work (e.g. rec-733 `verify_schema_migration.py`
warehouse-write whitelist cleanup) intersect Phase 0+1 of the graduation arc rather
than this REPORT-ONLY planning session. They will be evaluated for bundling when
the Phase 0+1 plan is scoped.

## Acceptance Criteria
- [ ] `docs/INTENT-ops-decisions-graduation.md` exists on the branch.
- [ ] The new file contains the standard INTENT sections: North Star, Phase Overview,
      per-phase detail (Phases 0+1 through 6), Known Gaps, Decision Registry, Agent
      Instructions, What This Document Does Not Cover.
- [ ] `docs/INTENT-dq-enforcement.md` references the new graduation arc.
- [ ] No code changes (REPORT-ONLY).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [post-impl] | Anchor doc exists | `test -f docs/INTENT-ops-decisions-graduation.md && echo OK` | `OK` | File not written -- write it |
| 2 | [post-impl] | Anchor doc has expected top-level sections | `grep -c '^## ' docs/INTENT-ops-decisions-graduation.md` | Returns at least `10` (North Star, Phase Overview, six phases, Known Gaps, Decision Registry, Agent Instructions, What This Document Does Not Cover) | Section missing -- add it |
| 3 | [post-impl] | Cross-link present in dq-enforcement INTENT | `grep -c 'INTENT-ops-decisions-graduation' docs/INTENT-dq-enforcement.md` | Returns at least `1` | Cross-link missing -- add it |
| 4 | [post-impl] | No code leaked into REPORT-ONLY plan | `git diff --name-only main -- scripts/ src/ config/ terraform/ tests/ | wc -l` | `0` | Out-of-scope changes -- revert |
| 5 | [post-impl] | No em dashes in the new doc (Windows console encoding) | `grep -c $'—' docs/INTENT-ops-decisions-graduation.md` | `0` | Replace em dashes with ASCII hyphens |
| 6 | [post-impl] | No emojis in the new doc | `python -c "import sys, re; s = open('docs/INTENT-ops-decisions-graduation.md', encoding='utf-8').read(); pat = re.compile('[\U0001F300-\U0001FAFF\U00002600-\U000027BF]'); sys.exit(0 if not pat.search(s) else 1)"` | exit 0 | Strip emojis |

## Constraints
- No code changes: this is a REPORT-ONLY plan producing a strategic anchor doc.
  Subsequent IMPLEMENTATION plans (Phase 0+1 onward) carry the code work.
- No rescue agents or workaround loops (Decision 55).
- No emojis or em dashes in the new doc (Windows console encoding mangles em dashes;
  ASCII hyphens only).
- Cross-link in `docs/INTENT-dq-enforcement.md` must not change the phase status of
  that arc; only add a forward reference and update the Phase 4 Session Map row for
  `ops_decisions`.
- Temporary constraint (per repo-root `CLAUDE.md`): No STRATEGIC plans until
  Decision 67 is reversed. This plan is REPORT-ONLY so the constraint does not
  apply to it, but subsequent phase plans (0+1, 2, 3, 4, 5) must be IMPLEMENTATION-type.
- Agent-First Repository principle: the new doc is the canonical machine-readable
  arc anchor. Do not produce a human-readable companion document. Future agents
  cold-load this one file.

## Context

The proposal was developed during the 2026-05-12 planning session
(telemetry session `e3d337ad-1673-41ff-ab60-ca893dc87747`). Key findings:

- `scripts/ops_data_portal.py::file_decision` and `update_decision` exist as
  skeletons with no Pydantic validation, no write-time validators, no local JSONL
  write-through, no Athena read on update, no `_sync_table` after write, no
  offline outbox drain. They are not callable in any current ETL path.
- The actual `ops_decisions` ETL bypasses the portal entirely:
  `scripts/session_postflight.py::_stage_document_derived_tables` calls
  `OpsWriter().write("ops_decisions", entry)` directly after parsing
  `docs/DECISIONS.md`. This bypass is currently whitelisted in
  `scripts/validate.py::validate_warehouse_write_sources`.
- DQ checks for `ops_decisions` are nearly all `enforced: false`: recency,
  `decision_id` not_null, `status` accepted_values. No decision manifest exists
  at `config/data_quality/decisions/ops_decisions.yaml` (only `ops_recommendations.yaml`).
- Two competing DECISIONS.md parsers exist:
  `scripts/decisions_md.py::parse_decisions_md` (canonical, used by the ETL) and
  `scripts/list_customizations.py::build_decisions_index` (orphan duplicate, with
  a slightly different schema). Drift hazard.
- 37 rows currently in `ops_decisions_current`. Status field shows severe drift
  ("Decided", "Decided -- March 2026", "Agent-decided -- pending human review.
  Implementation verified: 130/130 tests pass...", "Empirical finding from
  rec-027 validation..."). `decision_id` has null rows. `decided_date` mixes ISO
  dates with prose ("April 2026").
- Architectural fork (portal-first vs ETL-first) resolved in favour of
  **portal-first plus DECISIONS.md decommission** per 2026-05-12 user direction.
  Rationale: Agent-First Repository principle (root `CLAUDE.md`), Decision 50
  (Iceberg as source-of-truth for all ops data), persistent-agent-memory
  advantage of structured queryable data over markdown narrative.

Adjacent state confirmed in preflight: branch `main` clean, SSO ok, outbox
drained, 49,068 Athena rows pulled, DQ last run `FAIL (60P/1F/7W)` where the
single FAIL is the `ops_decisions.recency` check (already `enforced: false`).

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (agent/ops-decisions-graduation-intent)
- [x] docs/PROJECT_CONTEXT.md read
- [x] docs/INTENT-dq-enforcement.md read (cross-arc anchor)
- [x] docs/DECISIONS.md read (current state of decisions data via local cache)
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Write `docs/INTENT-ops-decisions-graduation.md` per the structure ratified in
   the planning session: Intent header, North Star, Phase Overview table, per-phase
   detail for Phases 0+1 through 6, Known Gaps, Decision Registry, Agent
   Instructions, What This Document Does Not Cover. ASCII hyphens only, no
   emojis, no em dashes.
2. Edit `docs/INTENT-dq-enforcement.md`:
   - Add a cross-arc reference near the top references section.
   - Update the Phase 4 Session Map row for `ops_decisions` to redirect agents
     to the new graduation arc, indicating that table is scoped out of this arc
     until graduation Phase 5 completes.
3. **Execute Verification Plan** -- run each step. All six must pass before
   commit. Loop until pass.
4. Commit both files (initial plan commit handled by /plan workflow; final
   approved commit after critique).
5. Report: anchor doc written, cross-link in place, V1 verification passed,
   critique gate clearance.
