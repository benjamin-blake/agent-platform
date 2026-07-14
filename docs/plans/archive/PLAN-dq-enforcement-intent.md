# Plan

## Intent

Create the authoritative strategic anchor for data quality enforcement maturity. The
executor is currently non-functional, and the five-session DQ arc spans too many
implementation sessions to rely on individual PLAN files for context continuity. The
INTENT document gives every future agent a single place to determine phase status,
read the decisions already made, and understand what not to do.

## Plan Type

REPORT-ONLY

## Verification Tier

V1

## Branch

agent/dq-enforcement-intent

## Phase

Phase Platform - verification system maturation (parallel to Phase 2 schema backfill).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| docs/INTENT-dq-enforcement.md | Create | Strategic anchor for the DQ enforcement maturity arc - the actual deliverable of this session. |

## Bundled Recommendations

None.

## Acceptance Criteria

- [ ] `docs/INTENT-dq-enforcement.md` exists with a Phase Overview table covering Phases 0-5.
- [ ] Each phase entry has a `Status:`, `Plan:`, and `PR:` field for in-place updates.
- [ ] A Decision Registry section records all `[DECIDED]` items with rationale.
- [ ] An Agent Instructions section gives explicit guidance on how to update the document and what NOT to do.
- [ ] Phase 4 is explicitly marked as a blocking gate on Phase 5.
- [ ] The narrow-covers constraint for `DataQualityVerifier` in Phase 2 is explicitly documented.
- [ ] The document states that Session E (scheduled DQ routine) is eliminated.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | report | Confirm INTENT document exists and is non-trivial | `.venv/Scripts/python.exe -c "import pathlib; p=pathlib.Path('docs/INTENT-dq-enforcement.md'); assert p.exists(),'missing'; n=len(p.read_text().splitlines()); assert n>150,f'too short: {n} lines'; print('OK lines:',n)"` | Prints `OK lines: N` where N > 150 | Create or extend the file |
| 2 | report | Confirm phase status fields present on each phase | `.venv/Scripts/python.exe -c "import pathlib; t=pathlib.Path('docs/INTENT-dq-enforcement.md').read_text(); n=t.count('**Status:**'); assert n>=6,f'expected >=6 status fields, got {n}'; print('OK status fields:',n)"` | Prints `OK status fields: N` where N >= 6 | Add Status fields to each phase section |
| 3 | report | Confirm Decision Registry has at least 6 entries | `.venv/Scripts/python.exe -c "import pathlib; t=pathlib.Path('docs/INTENT-dq-enforcement.md').read_text(); n=t.count('[DECIDED]'); assert n>=6,f'expected >=6 decided entries, got {n}'; print('OK decided:',n)"` | Prints `OK decided: N` where N >= 6 | Add missing decision entries |
| 4 | report | Confirm Agent Instructions section exists | `.venv/Scripts/python.exe -c "import pathlib; t=pathlib.Path('docs/INTENT-dq-enforcement.md').read_text(); assert 'Agent Instructions' in t,'missing section'; print('OK')"` | Prints `OK` | Add the Agent Instructions section |
| 5 | report | Confirm Phase 4 blocking gate is documented | `.venv/Scripts/python.exe -c "import pathlib; t=pathlib.Path('docs/INTENT-dq-enforcement.md').read_text(); assert any(w in t for w in ['BLOCKS','blocking gate','blocks Phase 5']),'missing blocking gate doc'; print('OK')"` | Prints `OK` | Document the Phase 4 blocking condition |

## Constraints

- This plan creates a document only. No code changes.
- No rescue agents or workaround loops (Decision 55).

## Context

- Supersedes: `docs/plans/PLAN-dq-gate-predicate.md`. Its scope is absorbed by Phase 2
  of the INTENT. Do not use that plan as the basis for a new /implement session.
- Source analysis: `docs/plans/PLAN-audit-ops-recs-dq-scalability.md`
- Phase 0 complete: `docs/plans/PLAN-dq-harden-gaps-1-4-5.md` / PR #285
- Phase 1 complete: `docs/plans/PLAN-dq-validate-integration.md` / PR #289
- Executor non-functional; all work proceeds via human-supervised /plan -> /implement.
- Session E (Claude Code cron + EC2 DQ scheduled routine) is eliminated. DQ runs as
  part of `validate.py`'s presubmit tier on the EC2 self-hosted runner.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main`
- [x] `docs/PROJECT_CONTEXT.md` read
- [x] `docs/DECISIONS.md` consulted (Decisions 48, 51, 55, 57)
- [x] `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` read end-to-end
- [x] `docs/plans/PLAN-dq-gate-predicate.md` read end-to-end
- [x] `docs/INTENT-verification-system.md` read end-to-end
- [x] `docs/INTENT-validation-architecture.md` read end-to-end

## Ordered Execution Steps

1. Write `docs/INTENT-dq-enforcement.md` per the structure agreed in the planning session.
2. Execute Verification Plan - run all five VP steps.
3. Report: confirm all five pass. Note any structural gaps and fix inline.
