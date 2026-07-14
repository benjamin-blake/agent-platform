# Plan

## Intent
Produce the decision-support artifacts that enable systematic resolution of the 69 DQ failures
across 12 tables, starting with `ops_recommendations`. This work advances the DQ enforcement
maturity arc by giving human+agent sessions a shared protocol, per-field root cause analysis,
and a machine-readable decision manifest -- so each session can walk the ratchet one field at
a time without re-investigating from scratch.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
agent/dq-recs-remediation-context

## Phase
Post-Phase 1: DQ Enforcement Maturity Arc (strategic anchor: docs/plans/PLAN-dq-enforcement-intent.md)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | Create | Reusable protocol: root cause taxonomy, temporal gate design, enforcement readiness taxonomy, agent session workflow |
| `config/data_quality/decisions/ops_recommendations.yaml` | Create | Machine-readable per-field decision manifest; all fields `human_decision: pending` |
| `docs/dq/ops-recommendations-remediation-briefing.md` | Create | Human-readable field-by-field analysis: violation counts, root cause class, proposed action, readiness verdict |
| `docs/PROJECT_CONTEXT.md` | Modify | Add one-line reference to `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` so future agents discover the protocol on demand |

## Bundled Recommendations
- **rec-594** (Medium/XS): Enforce Recommendation `status` via Pydantic Literal -- Class D prevention
  for the `status='Decided'` / `status='Unknown'` corruption identified in the briefing. Noted in
  the briefing's `status` section as a follow-on IMPLEMENTATION task.

## Acceptance Criteria
- [ ] `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` covers all 4 root cause classes, the `exclude_before`
      temporal gate field spec, the `enforcement_ready` taxonomy, and the agent session protocol
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` contains entries for all 13 tested +
      untested-candidate fields; every entry has `root_cause_class`, `human_decision: pending`, and
      `enforcement_ready` keys
- [ ] `docs/dq/ops-recommendations-remediation-briefing.md` covers every field in the Terraform
      schema with: violation count, sample bad values, root cause class with reasoning, proposed
      action, and enforcement readiness verdict
- [ ] `docs/PROJECT_CONTEXT.md` contains a reference to `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`
- [ ] No source code changes, no data writes, no YAML check modifications in this session

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | static | Methodology covers 4 classes + temporal gate spec | `.venv/Scripts/python.exe -c "c=open('docs/dq/DQ_REMEDIATION_METHODOLOGY.md').read(); needed=['Class A','Class B','Class C','Class D','exclude_before','enforcement_ready','human_decision']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add missing section to methodology doc |
| 2 | static | Decision manifest covers all required fields | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('config/data_quality/decisions/ops_recommendations.yaml')); f=d['fields']; required=['id','title','source','effort','priority','status','automatable','risk','last_updated_timestamp','created_timestamp','file','context','acceptance']; missing=[x for x in required if x not in f]; assert not missing, f'Missing fields: {missing}'"` | No AssertionError | Add missing fields to manifest |
| 3 | static | All manifest entries have required structural keys | `.venv/Scripts/python.exe -c "import yaml,sys; d=yaml.safe_load(open('config/data_quality/decisions/ops_recommendations.yaml')); keys=['root_cause_class','human_decision','enforcement_ready']; bad=[k for k,v in d['fields'].items() if not all(x in v for x in keys)]; print(f'Incomplete entries: {bad}') if bad else None; sys.exit(1 if bad else 0)"` | Exit 0, no output | Fix missing keys in named entries |
| 4 | static | Briefing covers all Terraform schema fields | `.venv/Scripts/python.exe -c "c=open('docs/dq/ops-recommendations-remediation-briefing.md').read(); fields=['id','title','source','effort','priority','status','automatable','risk','created_timestamp','file','context','acceptance','resolution','execution_result']; missing=[f for f in fields if f not in c]; assert not missing, f'Missing field sections: {missing}'"` | No AssertionError | Add missing field section to briefing |
| 5 | static | PROJECT_CONTEXT.md references methodology doc | `.venv/Scripts/python.exe -c "assert 'DQ_REMEDIATION_METHODOLOGY' in open('docs/PROJECT_CONTEXT.md').read(), 'Reference missing'"` | No AssertionError | Add reference to PROJECT_CONTEXT.md |

## Constraints
- No source code changes, data writes, or YAML check modifications in this session (REPORT-ONLY)
- `human_decision` fields must remain `pending` -- decisions are made interactively in follow-on sessions
- Do NOT add `exclude_before` to `ops.yaml` yet: the DQ runner does not support the key; adding it
  now would silently no-op and create a false sense of enforcement
- `date` column no-longer exists in the Athena schema; the `date` not_null check in `ops.yaml` is
  confirmed dead (ERROR verdict, not FAIL) -- briefing notes this as REMOVE_TEST but the YAML edit
  is deferred to the implementation session
- rec-609 (Critical/M) and rec-605 (Critical/L) both affect the live DQ runner's ability to validate
  ops_recommendations against Athena; flag them in the briefing as prerequisites for VP verification
  in follow-on sessions

## Context
- DQ ratchet (`enforced: true|false`) established in commit 6ad2147 (PR #296). All current
  `ops_recommendations` failures are `enforced: false` baseline -- they are visible and recorded but
  non-blocking. The goal of the remediation arc is to flip each check to `enforced: true` by
  resolving its root cause.
- Last DQ run: 2026-05-06T13:54Z -- 46P / 69F / 8W across 12 tables; ops_recommendations
  specifically: 11 FAIL + 1 WARN + 1 ERROR + 2 PASS (16 checks total)
- Bootstrap period anchor: `created_timestamp < '2026-05-01'` -- records written before the
  enforcement regime was established. Many null-field failures trace to this cohort.
- Local JSONL cache (630 records) used for null-rate analysis. Canonical source is Athena
  ops_recommendations_current view (SSO-required). rec-609 notes the view returns string-typed
  lists for array columns, affecting Pydantic validation downstream.
- Field null rates from the pre-plan investigation (n=630):
    execution_steps: 92.7% | resolution: 86.5% | execution_pr_url: 82.2%
    execution_branch: 66.8% | execution_date: 64.0% | execution_result: 62.5%
    automatable: 6.2% | risk: 5.7% | file: 5.7% | context: 5.7% | acceptance: 5.7%
    source/effort/priority: 5.6% | created_timestamp: 3.7% | title/status: 0.3% | id: 0.2%
- Invalid values found:
    status: 'Decided' x22 (domain pollution from ops_decisions), 'Unknown' x9 (migration artifact)
    risk: 'unclassified' x28, capitalised 'Low/Medium/High' x5, free-text leak strings x3
    source: 11 values not in accepted_values YAML list (executor-postmortem, cli-migration-analysis,
            telemetry-audit, architectural-review, implement-agent, cc-scheduled-agent-test,
            Autonomous Postflight Cleanup, manual, infra-recommendation-executor, workflow-audit,
            tech-debt, delegate-investigation)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable (PROJECT_CONTEXT.md exists; target docs/dq/ and
      config/data_quality/decisions/ dirs created)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`**
   Define the shared protocol all future DQ remediation sessions will use:
   - Root cause taxonomy (4 classes):
       Class A -- Config mismatch: YAML is wrong, not the data. Fix: update ops.yaml.
       Class B -- Bootstrap artifact: data predates the rule. Fix: temporal gate via `exclude_before`.
       Class C -- Write path gap: code never set the field. Fix: fix write path; enforce for new records only.
       Class D -- True corruption: wrong value domain leaked in. Fix: data correction via ops_data_portal + write-path guard.
   - `exclude_before` field spec: optional key under any check config; the DQ runner translates it
     to `AND created_timestamp >= TIMESTAMP 'YYYY-MM-DD'` in the Athena WHERE clause. Not yet
     implemented in the runner -- flag as requiring a prerequisite IMPLEMENTATION plan.
   - `enforcement_ready` taxonomy (7 states):
       READY_NOW | NEEDS_TEMPORAL_GATE | NEEDS_WRITE_FIX | NEEDS_DATA_CORRECTION
       NEEDS_PROTOTYPE | REMOVE_TEST | NO_TEST_NEEDED
   - `human_decision` states: pending | approved | deferred | declined
   - Agent session protocol:
       (a) Load this file; (b) load table's `config/data_quality/decisions/{table}.yaml`;
       (c) load `config/data_quality/{ops|telemetry}.yaml`; (d) load `logs/debug/dq-latest.json`;
       (e) walk only `human_decision: pending` fields one at a time; (f) present analysis from
       briefing doc; (g) record decision and decided_date; (h) if approved, generate the specific
       YAML diff or ops_data_portal command for the next IMPLEMENTATION session.
   - Multi-table directory layout: `config/data_quality/decisions/{table}.yaml` for each of the
     12 tables covered by ops.yaml and telemetry.yaml.

2. **Create `config/data_quality/decisions/ops_recommendations.yaml`**
   One entry per field using the pre-plan investigation findings. Include `notes` with violation
   counts and sample bad values. All `human_decision: pending`. Pre-classify the `date` entry as
   `enforcement_ready: REMOVE_TEST` (only field with a pre-confirmed class -- ERROR verdict from
   a dropped column). Classification for all other fields per the analysis in Context above.
   Fields to include:
   Tested (from ops.yaml): id, date, title, source, effort, priority, status, automatable, risk,
                            last_updated_timestamp
   Untested candidates:     file, context, acceptance, resolution, execution_result, execution_date,
                            execution_branch, execution_pr_url, execution_steps, created_timestamp,
                            dependencies, tags

3. **Create `docs/dq/ops-recommendations-remediation-briefing.md`**
   Per-field sections. Each section contains:
   (a) Schema definition (type + Terraform comment)
   (b) Current test coverage (from ops.yaml) and last verdict
   (c) Violation count and sample bad values (from Context above)
   (d) Root cause class with reasoning
   (e) Proposed action -- literal YAML diff or ops_data_portal command where deterministic;
       "INVESTIGATE FIRST" where the root cause is ambiguous
   (f) Enforcement readiness verdict
   (g) Decision slot: `**Decision**: <!-- pending -->` for human fill-in
   Include a preamble summarising: bootstrap anchor date, the 4 classes, how to use the document.
   Call out rec-594 in the `status` section as the write-path guard for Class D status corruption.
   Open the document with a prominent **Prerequisites** callout block listing rec-609 and rec-605
   as hard blockers for any follow-on IMPLEMENTATION session that re-runs the live DQ runner:
   rec-609 causes the Athena view to return string-typed lists (breaking validation); rec-605 is the
   pending Terraform fix for the `_rn` ambiguity in `ops_recommendations_current`.

4. **Modify `docs/PROJECT_CONTEXT.md`**
   Create a new `### Data Quality Enforcement` subsection under the existing
   `## Operational Data Governance` section. Add a reference line pointing to
   `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` and a one-line note that per-table decision
   manifests live at `config/data_quality/decisions/{table}.yaml`. This ensures any agent
   loading PROJECT_CONTEXT.md on demand discovers the remediation protocol without ambient
   overhead.

5. **Execute Verification Plan** -- run all 5 VP steps. Loop until all pass.

6. **Report**: confirm 3 files created, 1 file modified, 19 field classifications recorded
   (10 tested + 9 untested candidates), 0 source code changes.

## Work Areas
N/A -- REPORT-ONLY, single deliverable set.
