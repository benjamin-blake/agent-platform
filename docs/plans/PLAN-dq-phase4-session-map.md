# Plan

## Intent
Expand Phase 4 of `docs/INTENT-dq-enforcement.md` from a stub into an actionable session
map for ops_recommendations DQ remediation, wire the ops.yaml extended contract pattern
(`description` + `semantics` per column) as the field semantic authority, add `phase4_session`
pointers to the decision manifest, and file three decisions that lock in architectural choices
deferred from prior sessions. Establishes the cold-start protocol that caps each future
Phase 4 session at a defined minimum context load.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Branch
agent/dq-phase4-session-map

## Phase
Platform: Phase 4 of the DQ enforcement maturity arc (`docs/INTENT-dq-enforcement.md`)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-dq-enforcement.md` | Modify | Replace Phase 4 stub with session map, cold-start protocol, bootstrapping causal chain, RCA constraint |
| `config/data_quality/ops.yaml` | Modify | Add description + semantics metadata to all ops_recommendations column entries |
| `config/data_quality/decisions/ops_recommendations.yaml` | Modify | Add phase4_session field per entry linking to session map |
| `docs/DECISIONS.md` | Modify | File Decision 63 (execution fields excluded), Decision 64 (bootstrap anchor), Decision 65 (ops.yaml field contract authority) |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] INTENT doc Phase 4 section contains keywords: `wave-1`, `wave-2`, `wave-3`,
      `wave-4-deferred`, `wave-5-deferred`, `cold-start`, `source_registry`, `phase4_session`,
      `RCA-before-action`
- [ ] `ops.yaml` has `description` and `semantics` on all 10 ops_recommendations column entries
      (id, title, source, effort, priority, status, automatable, risk, created_timestamp,
      last_updated_timestamp); `date` column entry absent
- [ ] Decision manifest has `phase4_session` on every field entry
- [ ] `DECISIONS.md` contains Decision 63, Decision 64, Decision 65

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | static | INTENT doc has session map keywords | `.venv/Scripts/python.exe -c "c=open('docs/INTENT-dq-enforcement.md').read(); needed=['wave-1','wave-2','wave-3','wave-4-deferred','wave-5-deferred','cold-start','source_registry','phase4_session','RCA-before-action']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add missing keywords to Phase 4 section |
| 2 | static | ops.yaml has description+semantics on all ops_recommendations columns | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('config/data_quality/ops.yaml')); cols=d['tables']['ops_recommendations']['columns']; bad=[k for k in cols if 'description' not in cols[k] or 'semantics' not in cols[k]]; assert not bad, f'Missing metadata in: {bad}'"` | No AssertionError | Add description/semantics to failing columns |
| 3 | static | date column absent from ops.yaml | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('config/data_quality/ops.yaml')); cols=d['tables']['ops_recommendations']['columns']; assert 'date' not in cols, 'date column still present -- REMOVE_TEST not complete'"` | No AssertionError | Remove date column entry if still present |
| 4 | static | decision manifest has phase4_session per field | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('config/data_quality/decisions/ops_recommendations.yaml')); bad=[k for k,v in d['fields'].items() if 'phase4_session' not in v]; assert not bad, f'Missing phase4_session in: {bad}'"` | No AssertionError | Add phase4_session to failing entries |
| 5 | static | DECISIONS.md contains Decision 63, 64, 65 | `.venv/Scripts/python.exe -c "c=open('docs/DECISIONS.md').read(); needed=['Decision 63','Decision 64','Decision 65']; missing=[k for k in needed if k not in c]; assert not missing, f'Missing: {missing}'"` | No AssertionError | Add missing decisions |

## Constraints
- No source code changes, data writes, or DQ check enforcement changes in this plan;
  exception: removal of the `date` column entry from ops.yaml (REMOVE_TEST per decision
  manifest -- column dropped from Iceberg schema per Decision 56, already absent as of
  PRs #301-304; VP step 3 verifies)
- No new files created -- this plan only modifies existing ones
- `ops.yaml` description/semantics additions must not alter any existing check configuration
  (values, enforced flags, exclude_before dates, severity settings)
- The session map in the INTENT doc is a planning artefact only -- specific implementation
  plans for each wave are authored in their own `/plan` sessions
- `phase4_session` values must reference the wave labels defined in the INTENT doc update
- Do not update `enforcement_ready` or `human_decision` fields in the decision manifest;
  those are updated by the wave sessions as checks graduate
- Lambda deploy deferred: `config/data_quality/` is packaged into the Lambda zip by
  `scripts/build_lambda.py`, but the scheduled agent dispatcher is currently disabled
  (disabled May 2026 per CLAUDE.md operational runbook). Lambda rebuild and smoke test
  (`scripts.run_scheduled_agent --smoke-test doc-freshness`) must be executed when the
  dispatcher is re-enabled -- not part of this plan's verification scope
- `telemetry.yaml` extended contract (description + semantics per column) is deferred;
  telemetry table metadata will be added as part of the telemetry table sessions at the
  end of Phase 4. Decision 65 names telemetry.yaml as an authority; that mandate is
  fulfilled per-table as each telemetry session runs

## Context
- Root cause: Phase 4 stub has no actionable session structure; each new agent session
  re-derives context from the briefing doc (134,927 tokens) because no session map or
  cold-start protocol exists. Plan A (agent-first-foundation, PR #305) deprecated the
  briefing doc pattern and established ops.yaml extended contract as the field semantic
  authority. This plan operationalises that pattern for ops_recommendations.
- State drift from planning conversation (2026-05-06): PRs #301-304 have graduated
  automatable and risk checks to enforced: true and removed the date column. The session
  map must reflect current ops.yaml state, not the briefing doc state. Wave sessions must
  run the DQ runner at session start to verify current verdicts before acting.
- Five-wave breakdown derived from decision manifest approved/deferred decisions:
  Wave 1 (source-lineage): source field write-fix + source_registry.yaml
  Wave 2 (impl-pointers): file/context/acceptance adds + automatable formula
  Wave 3 (domain-corruption): status dec-XXX deletion + risk verification + remaining unenforced
  Wave 4 (DEFERRED): execution fields excluded per Decision 63
  Wave 5 (DEFERRED): bootstrap closure via exclude_before, pending runner support
- Recommendation: start with Wave 3. The 31 dec-XXX records are root cause of the 35-record
  bootstrap null cohort in source/effort/priority. Waves 1 and 2 will partially self-resolve
  once Wave 3 status cleanup runs. Wave 3 has no prerequisites.
- Live verification blockers as of 2026-05-07: rec-609 (Athena returns string for
  array<string>; blocks element-level checks on dependencies/tags), rec-605 (_rn ambiguity
  in _current view). Neither affects the metadata-only changes in this plan.
- Decision 58 (2026-05-01): .agents/skills/ is canonical. This plan targets no skill files.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `DECISIONS.md` read (confirm last decision is 62 before adding 63-65)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Modify `docs/INTENT-dq-enforcement.md` -- expand Phase 4 section**

   Locate the Phase 4 section. Replace everything between the `## Phase 4: Data Quality
   Resolution` header and the `## Phase 5: Convergence` header with the content below.
   Preserve the header line itself unchanged.

   Exact replacement content:

   ```
   ## Phase 4: Data Quality Resolution

   **Status:** IN_PROGRESS
   **Plans:** Multiple /plan sessions per wave (see Session Map below)
   **PRs:** Multiple

   **Prerequisite:** Phase 3 merged.
   **Blocks:** Phase 5. Phase 5 does not begin until this phase's final completion
   condition is satisfied.

   ### Cold-Start Protocol

   Each Phase 4 planning or implementation session loads exactly:
   - `docs/INTENT-dq-enforcement.md` (this document, Phase 4 section)
   - `config/data_quality/ops.yaml` (field contract authority; description + semantics per column)
   - `config/data_quality/decisions/{table}.yaml` (decision manifest for the target table)
   - `.venv/Scripts/python.exe -m scripts.data_quality_runner` output (if SSO available)

   Do NOT load: `docs/dq/ops-recommendations-remediation-briefing.md` (legacy artefact;
   superseded by ops.yaml extended contract per DQ_REMEDIATION_METHODOLOGY.md step b2 and
   Decision 65). Do not load out-of-scope INTENT docs (INTENT-verification-system.md,
   INTENT-validation-architecture.md) unless the session explicitly touches those systems.

   ### Bootstrapping Causal Chain

   The table is append-only Iceberg. Records marked for deletion by an agent are NOT
   physically deleted. `sync_ops.pull()` re-materialises every Iceberg row into the local
   JSONL cache on each pull. "Deleted" records reappear after every sync unless tombstoned
   upstream via `scripts/ops_data_portal.py` (sets status=superseded or status=declined).
   The `dq_tombstones.yaml` HARD_GATE detects resurrection events after the fact -- it
   does not prevent them. Correct deletion sequence:
   1. Identify the record's SCD2 version history (all rows with the same id in the base table).
   2. Set the final version status to 'superseded' or 'declined' via ops_data_portal.
   3. Confirm the _current view no longer returns the record.
   Never use direct JSONL edits or Iceberg DELETE statements -- both bypass SCD2 consistency
   and the ID authority.

   ### RCA-Before-Action Constraint

   Never correct or delete data without first assigning a root cause class (A/B/C/D per
   `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`). Skipping this step creates incorrect remediation
   paths and repeats the conditions that produced the bootstrap cohort. Every data action in
   Phase 4 must have a corresponding decision manifest entry with an approved root cause.

   ### Session Map -- ops_recommendations

   State drift note: run the DQ runner at the start of each wave session to verify current
   verdicts. PRs #301-304 have graduated several checks since the decision manifest was
   authored (2026-05-06). The phase4_session field in the manifest provides the routing;
   the DQ runner provides current verdicts.

   | Wave | Session slug | Fields | Status | Prerequisite |
   |------|-------------|--------|--------|-------------|
   | 1 | 4.1-source-lineage | source | NOT_STARTED | Wave 3 (status cleanup resolves bootstrap null cohort) |
   | 2 | 4.2-impl-pointers | file, context, acceptance, automatable (formula) | NOT_STARTED | Wave 1 complete |
   | 3 | 4.3-domain-corruption | status (dec-XXX deletion), risk (verify backfill) | NOT_STARTED | None |
   | 4 | wave-4-deferred | execution_result, execution_date, execution_branch, execution_pr_url, execution_steps | DEFERRED | Telemetry maturity (Decision 63) |
   | 5 | wave-5-deferred | id, title, effort, priority, created_timestamp (temporal gates) | DEFERRED | exclude_before runner support |

   **Recommendation: start with Wave 3.** The dec-XXX status corruption records are the
   root cause of the 35-record null cohort in source/effort/priority. Waves 1 and 2 will
   partially self-resolve after Wave 3 cleanup. Wave 3 has no prerequisites.

   ### Session Map -- other ops tables

   After all non-deferred waves for ops_recommendations are complete:
   - ops_decisions -- single session (few checks, smaller table)
   - ops_execution_plans -- single session
   - ops_session_log, ops_priority_queue -- single session each
   - Telemetry tables -- deferred; require executor restoration and telemetry bootstrap

   ### Protocol for Each Wave Session

   1. Load the cold-start context set above.
   2. Run the DQ runner to get current per-check verdicts (do not rely on manifest's
      last_verdict; it reflects the 2026-05-06 snapshot).
   3. For each field in this wave's scope, read `phase4_session` in the manifest to confirm
      this is the right session, then read `root_cause_class` and `decided_action`.
   4. Execute per decided_action. No out-of-scope data changes.
   5. After each data or YAML change, rerun the DQ runner and verify the check no longer
      fails before graduating enforced: false -> enforced: true.
   6. File any new recommendations discovered during remediation via ops_data_portal --
      do not inline-fix out-of-scope issues.

   ### Intermediate Completion Check (progress gate -- not the Phase 5 gate)

   After each session, verify all processed checks have inline comments:

   ```
   grep -n "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml | grep -v "#"
   ```

   Zero lines means every `enforced: false` line has an inline comment. The comment must
   be on the same line as `enforced: false` (inline comment). A comment on the next line
   is not detected by this grep. The only valid form is: `enforced: false  # reason`.

   ### Final Completion Condition for Phase 5 Entry

   Phase 5 entry requires every check to be `enforced: true` -- no `enforced: false` entries
   at all, commented or otherwise. Verify with:

   ```
   grep -n "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml
   ```

   Zero lines (all `enforced: false` removed, including any with inline comments) = Phase 4
   complete, Phase 5 can begin.
   ```

2. **Modify `config/data_quality/ops.yaml` -- add description + semantics to ops_recommendations columns**

   For each column listed below, insert `description` and `semantics` keys immediately before
   the `tests:` key. Do not alter any existing check configuration (values, enforced flags,
   exclude_before dates, severity, comments). The date column should already be absent; if
   present, remove it (REMOVE_TEST per Decision manifest).

   **id** -- insert before `tests:`:
   ```yaml
   description: "Recommendation unique identifier, format rec-NNN"
   semantics: "DynamoDB-allocated; never set directly by agents. SCD2: multiple rows per id in base table; uniqueness enforced at _current view level only."
   ```

   **title** -- insert before `tests:`:
   ```yaml
   description: "Concise one-line description of the recommendation"
   semantics: "Minimum 10 characters enforced at write time in ops_data_portal. Near-duplicate titles across different file targets are legitimate."
   ```

   **source** -- insert before `tests:`:
   ```yaml
   description: "Agent type that filed this recommendation; harness-injected AGENT_TYPE identifier"
   semantics: "Lineage key: analytically equivalent to session_id for cross-table joins to telemetry on agent type. Never set by agents -- injected from AGENT_TYPE env var by the invocation harness. Validated against source_registry.yaml at write time. Human-initiated portal calls use source=manual."
   ```

   **effort** -- insert before `tests:`:
   ```yaml
   description: "Estimated implementation size (t-shirt: XS/S/M/L/XL)"
   semantics: "Interim string label. Migration rec-627: convert to LOC-weighted integer; t-shirt labels derived in _current view from integer thresholds. Weights defined in config/executor_capabilities.yaml."
   ```

   **priority** -- insert before `tests:`:
   ```yaml
   description: "Business urgency tier (Critical/High/Medium/Low)"
   semantics: "Interim string label. Migration rec-628: convert to int 1-4 (1=Critical, 4=Low); ORDER BY priority ASC gives urgency sort. Labels derived in _current view via CASE. Source-informed defaults at portal write time."
   ```

   **status** -- insert before `tests:`:
   ```yaml
   description: "Recommendation lifecycle state"
   semantics: "Valid domain: open | closed | failed | declined | superseded. Pydantic Literal guard at write time (rec-594). SCD2 append-only: deletion requires setting status=superseded via ops_data_portal -- never direct JSONL edits."
   ```

   **automatable** -- insert before `tests:`:
   ```yaml
   description: "Whether this recommendation is within the executor's current capability boundary"
   semantics: "Derived, never agent-set. Formula: (file NOT IN executor_boundary) AND (risk_score <= executor_maturity_ceiling). Both inputs from config/executor_capabilities.yaml. Recomputed only when the maturity ceiling is raised."
   ```

   **risk** -- insert before `tests:`:
   ```yaml
   description: "Implementation risk tier (low/medium/high)"
   semantics: "Derived, never agent-set. Formula: R = (C x S) / M where C=max cyclomatic complexity of target file, S=effort scale factor, M=coverage% + 0.1 baseline. Thresholds: 0-5=low, 6-15=medium, 15+=high. Portal derives at write time from file + effort."
   ```

   **created_timestamp** -- insert before `tests:`:
   ```yaml
   description: "Timestamp when this recommendation was first filed"
   semantics: "SCD2 invariant: identical across all versions of a given rec id; does not change on update. Enforced constraint: created_timestamp <= last_updated_timestamp."
   ```

   **last_updated_timestamp** -- add as a new column entry (no `tests:` block; covered by
   the table-level `recency:` check which references this column):
   ```yaml
   last_updated_timestamp:
     description: "Timestamp of the most recent write to this SCD2 row"
     semantics: "Advances on every SCD2 append (open->closed, field update, etc.). Covered by table-level recency check (warn_after_hours: 24, error_after_hours: 168). Enforced constraint: created_timestamp <= last_updated_timestamp."
   ```

3. **Modify `config/data_quality/decisions/ops_recommendations.yaml` -- add phase4_session per field**

   Add `phase4_session` immediately after the `enforcement_ready` key in each field entry.
   Use the values from this table:

   | Field | phase4_session |
   |-------|----------------|
   | id | wave-5-deferred |
   | date | complete |
   | title | wave-5-deferred |
   | source | wave-1 |
   | effort | wave-5-deferred |
   | priority | wave-5-deferred |
   | status | wave-3 |
   | automatable | wave-2 |
   | risk | wave-3 |
   | last_updated_timestamp | complete |
   | created_timestamp | wave-5-deferred |
   | file | wave-2 |
   | context | wave-2 |
   | acceptance | wave-2 |
   | resolution | deferred |
   | execution_result | wave-4-deferred |
   | execution_date | wave-4-deferred |
   | execution_branch | wave-4-deferred |
   | execution_pr_url | wave-4-deferred |
   | execution_steps | wave-4-deferred |
   | dependencies | deferred-rec-609 |
   | tags | deferred-rec-609 |

4. **Modify `docs/DECISIONS.md` -- add Decision 63, 64, 65**

   Insert three new decision entries at the very top of the decisions list -- immediately
   before the `## Decision 62` entry (currently the first decision in the file, at roughly
   line 5). The file uses most-recent-first ordering for new decisions; existing entries
   below Decision 55 are in mixed order but that is pre-existing. Do not reorder existing
   entries. Exact content to insert:

   ```
   ## Decision 65: ops.yaml Extended Contract is the Canonical Field Semantic Authority (Decided)

   `config/data_quality/ops.yaml` (and `telemetry.yaml`) is the canonical field contract for
   all DQ-governed tables. The `description` and `semantics` metadata fields within each column
   entry define the field's semantic contract -- consumed by agents, ignored by the DQ runner.
   This supersedes the separate human-readable briefing doc pattern (e.g.,
   `docs/dq/ops-recommendations-remediation-briefing.md`). Do not create new briefing docs for
   new tables. Add field context as `description` + `semantics` in the YAML directly. The briefing
   doc for ops_recommendations is a legacy artefact; it is not maintained going forward. The
   decision manifest YAML (`config/data_quality/decisions/{table}.yaml`) remains the remediation
   state authority.

   ## Decision 64: Bootstrap Cohort Anchor for ops_recommendations is 2026-05-01 (Decided)

   The bootstrap cohort for ops_recommendations consists of all records created before 2026-05-01
   (the date the enforcement regime was established via Phase 3 ratchet PR #296 and formalised in
   `docs/dq/DQ_REMEDIATION_METHODOLOGY.md`). All Class B (bootstrap artifact) temporal gates for
   this table use `exclude_before: '2026-05-01'`. This anchor is fixed and must not be changed
   retroactively. Bootstrap records are not corrupt -- they predate the rules. They age out of the
   _current view as recommendations are closed or superseded.

   ## Decision 63: Execution Fields Excluded from ops_recommendations DQ Scope (Decided)

   Execution fields (`execution_result`, `execution_date`, `execution_branch`, `execution_pr_url`,
   `execution_steps`) are excluded from Phase 4 DQ remediation scope for ops_recommendations.
   These fields record how a recommendation was executed, not its lifecycle state -- they are
   telemetry, not ops state. They belong in `ops_execution_plans` or the telemetry tables.
   Denormalising execution state into ops_recommendations creates two sources of truth that can
   drift (rec says success, execution plan says failed). DQ enforcement for these fields is
   deferred until execution state is normalised to the appropriate table (pending telemetry
   maturity). Phase 4 decision manifest: `phase4_session: wave-4-deferred` for all five fields.
   ```

5. **Execute Verification Plan** -- run all 5 VP steps in order. Loop until all pass.

6. **Report**: 4 files modified, 0 files created. Phase 4 session map established with 5-wave
   structure and cold-start protocol. ops.yaml extended contract populated for all 9
   ops_recommendations columns. Decision manifest linked to session map via phase4_session field.
   3 architectural decisions filed (Dec-63: execution fields excluded, Dec-64: bootstrap anchor
   locked, Dec-65: ops.yaml as field contract authority).
