# Plan

## Intent
REPORT-ONLY audit of session-log architecture (platform tier_item T-1.9).
Captures the deliberation that converged on a two-tier event/aggregate split
with a new agent-facing Lambda for turn-event ingestion. Substantive
deliverable is `docs/INTENT-session-log-architecture.md`; this PLAN file is
the planning artefact that satisfies the T-1.9 exit criteria and points to
that deliverable.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
agent/session-log-audit

## Phase
Phase Platform -- T-1.9 (docs/ROADMAP-PLATFORM.yaml). Tier T-1; effort: S;
strategic: false; depends_on: []. The audit produces an INTENT that
unblocks design of the eventual write/read Lambdas in the T0.7 family.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/plans/PLAN-session-log-audit.md | Create | This planning artefact. |
| docs/INTENT-session-log-architecture.md | Create | Substantive REPORT-ONLY deliverable: the audit and proposed two-tier event/aggregate design. |

No code changes. Audit-time tooling for any schema-accuracy verification
uses the existing Athena-via-sync_ops path; CD.15 confines DuckDB to
Lambda-internal so the audit deliberately does not exercise DuckDB from
the agent shell.

## Bundled Recommendations
None. The schema-accuracy DQ pass that this INTENT recommends will file
its own recs via `file_rec` in a follow-on session per Section 13 of the
INTENT.

## Infrastructure Dependencies
None. No `.tf` files in scope. The INTENT does propose follow-on plans
that touch `terraform/iceberg_tables.tf` (new tables) and Lambda
infrastructure, but those are explicitly deferred and DEFERRED-marked
per Decision 67.

## Acceptance Criteria
The three T-1.9 exit criteria from docs/ROADMAP-PLATFORM.yaml lines 1297-1300:

- [ ] INTENT deliverable audits both session-log write surfaces
      (docs/SESSION_LOG.md + Athena ops_session_log).
- [ ] INTENT proposes CD(s) governing which surface is authoritative
      and when the markdown surface is retired.
- [ ] INTENT proposes follow-on IMPLEMENTATION plans for migrating
      writes to the T0.7b Lambda target.

Plus:
- [ ] INTENT covers reader side (session_preflight.recent_sessions,
      session_postflight, planning skill Read Context), not just writers,
      per the audit-scope clarification reached during planning.
- [ ] INTENT runs the Decision 75 frame-challenge against the proposed
      verb-shape (Section 2).
- [ ] INTENT settles event-tier design and explicitly defers aggregate-tier
      design, with reasoning for the deferral (Section 9).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | post-write | Confirm both files exist and are non-empty. | `bin/venv-python -c "import pathlib; p1=pathlib.Path('docs/plans/PLAN-session-log-audit.md'); p2=pathlib.Path('docs/INTENT-session-log-architecture.md'); assert p1.is_file() and p1.stat().st_size > 500; assert p2.is_file() and p2.stat().st_size > 5000; print('OK')"` | Prints `OK`. | If files missing or short, re-author. |
| 2 | post-write | Confirm INTENT contains the six required top-level section headings. | `bin/venv-python -c "import pathlib, re; t=pathlib.Path('docs/INTENT-session-log-architecture.md').read_text(); req=['## 1. End-state architecture restatement','## 2. Frame challenge','## 3. Current write-surface inventory','## 4. Current read-surface inventory','## 8. Verb-shape decision','## 12. Named CDs proposed','## 13. Follow-on IMPLEMENTATION plan stubs']; missing=[s for s in req if s not in t]; assert not missing, f'missing sections: {missing}'; print('OK')"` | Prints `OK`. | Add any missing section. |
| 3 | post-write | Confirm INTENT proposes at least one named CD per T-1.9 exit criterion 2. | `bin/venv-python -c "import pathlib, re; t=pathlib.Path('docs/INTENT-session-log-architecture.md').read_text(); cds=re.findall(r'### CD\.NN\.[a-z]', t); assert len(cds) >= 3, f'expected >=3 named CDs, found {len(cds)}: {cds}'; print(f'OK ({len(cds)} CDs)')"` | Prints `OK (5 CDs)`. | Add CD proposals to Section 12 until >=3. |
| 4 | post-write | Confirm INTENT names follow-on stubs per T-1.9 exit criterion 3. | `bin/venv-python -c "import pathlib; t=pathlib.Path('docs/INTENT-session-log-architecture.md').read_text(); assert '## 13. Follow-on IMPLEMENTATION plan stubs' in t and 'Schema-accuracy DQ pass' in t and 'agent-platform-log-turn' in t; print('OK')"` | Prints `OK`. | Add the Section 13 stubs table. |
| 5 | post-write | Confirm planning-queue gate (Decision 73) was not blocked at plan-write time. | `bin/venv-python -c "import json, pathlib; r=json.loads(pathlib.Path('logs/.preflight-report.json').read_text()); assert r.get('ci_rca_recs', []) == [], f'open ci-rca recs at plan-write time: {r[\"ci_rca_recs\"]}'; print('OK')"` | Prints `OK`. | If non-empty, defer audit and address ci-rca recs first per Decision 73. |
| 6 | post-write | Run `validate.py --pre` to confirm no surface drift. | `bin/venv-python -m scripts.validate --pre` | All checks pass. | Diagnose any failure surfaced. |

## Constraints
- AGENTS.md memory policy: no auto-memory writes. Durable findings land
  in CLAUDE.md or this INTENT, not `~/.claude/projects/.../memory/`.
- Decision 67: Lambda deployment deferred. The audit proposes Lambda work
  in follow-on stubs (Section 13 of INTENT); each carries the DEFERRED
  marker. This REPORT-ONLY plan itself touches no Lambda-packaged files.
- CD.17 / Decision 67 (STRATEGIC plan freeze): this plan is REPORT-ONLY,
  not STRATEGIC -- freeze does not apply.
- CD.15: audit-time tooling must not exercise DuckDB from the agent
  shell. Schema-accuracy verification (Section 5 of INTENT) uses the
  existing Athena/sync_ops path.
- CD.20 / CD.23: ops_session_log + future turn-event tables are private
  operational data. No follow-on stub in the INTENT proposes export
  outside the private repo.
- Decision 55: no rescue agents or workaround loops; on critique
  failure, revise and re-run rather than patching around.

## Context
- T-1.9 tier item: docs/ROADMAP-PLATFORM.yaml lines 1284-1304.
- T0.7b (log-decision Lambda) is the eventual migration target named in
  T-1.9's intent prose; follow-on stubs are gated on its deployment.
- Decisions and CDs cited by the INTENT: NS.4, NS.5, CD.9, CD.10, CD.12,
  CD.13, CD.15, CD.20, CD.23, CD.25, CD.26; Decisions 50, 51, 56, 61, 62,
  63, 65, 67, 69, 75. (Cite list converged from two decision-scout gate
  runs during planning.)
- Prior PRs that motivate the audit: #361 (T0.6 Terraform skeleton +
  agent_platform ratification), #362 (T0.3 Pattern B agent-auth) -- the
  AWS substrate that the proposed Lambda will land on.
- Naming convention: new Lambdas use `agent-platform-{purpose}` prefix
  for open-source-readiness; existing roadmap-planned Lambdas keep their
  `bblake-platform-{purpose}` names until a separate roadmap-renaming
  item addresses them.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (`agent/session-log-audit`).
- [x] docs/PROJECT_CONTEXT.md read during planning (via end-state-summary subagent).
- [x] DECISIONS.md read during planning (via decision-scout subagent, full file).
- [x] docs/ROADMAP-PLATFORM.yaml T-1.9 entry read.
- [x] All files in Scope table will be created by this plan (none pre-existing).
- [x] Acceptance Criteria understood and verifiable per Verification Plan.
- [x] Decision 73 planning-queue gate clear (`ci_rca_recs == []` at preflight).

## Ordered Execution Steps

The substantive work of this REPORT-ONLY plan was performed during the
planning session itself; the INTENT deliverable was authored as part of
Step 8 of the /plan workflow. The "execution" here is verification +
critique gates.

1. **Write `docs/INTENT-session-log-architecture.md`** -- substantive
   audit deliverable per Scope table. Done as part of Step 8 of /plan
   workflow. Body structured per the 14 sections enumerated in the
   INTENT itself.
2. **Write `docs/plans/PLAN-session-log-audit.md`** -- this planning
   artefact. Done as part of Step 8 of /plan workflow.
3. **Initial commit** -- both files in one commit on
   `agent/session-log-audit` branch.
4. **Plan-critique gate (Step 9)** -- zero-context subagent invokes the
   `plan-critique` skill against this PLAN. Iterate on REVISE; proceed
   on PROCEED.
5. **Multi-perspective report-critique gate (Step 10, REPORT-ONLY)** --
   at least two zero-context subagents in parallel critique the INTENT
   deliverable from distinct perspectives (architect + risk reviewer).
   Iterate on revisions until convergence; each material revision lands
   as its own commit on the branch.
6. **Execute Verification Plan** -- run each Verification Plan step
   above; confirm all pass.
7. **Final commit (Step 11)** -- if any incremental revisions landed
   during critique iteration, this commit is for any remaining
   adjustments; otherwise empty and skipped.
8. **Close telemetry session (Step 12)** -- run
   `bin/venv-python -m scripts.session_postflight --close-session --outcome success`.

## Work Areas (STRATEGIC plans only)
N/A. This is a REPORT-ONLY plan.
