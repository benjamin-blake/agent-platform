# Plan

## Intent
Preserve the institutional knowledge gained from graduating `ops_recommendations` through
Phase 4 of the DQ enforcement arc. The primary output is a protocol upgrade to
`DQ_REMEDIATION_METHODOLOGY.md` (reusable across all tables) and an arc-specific
retrospective in `INTENT-dq-enforcement.md` so that any future agent starting Phase 4
on `ops_decisions` or any other table has the ordered prerequisite gates, the write portal
architecture, and the YAML-data drift prevention framework already documented -- rather than
re-discovering bypass routes, wave ordering constraints, or Athena coercion issues from scratch.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Branch
agent/dq-graduation-retrospective

## Phase
Phase Platform (parallel track) / DQ Arc Phase 4: Data Quality Resolution (IN_PROGRESS)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | Modify | Fix `exclude_before` staleness; add Unified Write Portal, YAML-Data Drift, and Table Graduation Prerequisites sections |
| `docs/INTENT-dq-enforcement.md` | Modify | Add `ops_recommendations` Graduation Retrospective to Phase 4; update Session Map with Prerequisites column for remaining ops tables |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `DQ_REMEDIATION_METHODOLOGY.md` contains no instance of "NOT YET IMPLEMENTED" in
  the `exclude_before` section
- [ ] `DQ_REMEDIATION_METHODOLOGY.md` contains a `## Unified Write Portal` section that
  names the bypass audit grep and describes `write_time: true` semantics
- [ ] `DQ_REMEDIATION_METHODOLOGY.md` contains a `## YAML-Data Drift` section that covers
  the three-layer defense (graduation guard, `write_time: true`, temporal gate) and the
  Class E post-delete assertion requirement
- [ ] `DQ_REMEDIATION_METHODOLOGY.md` contains a `## Table Graduation Prerequisites`
  section with five ordered gates; Gate 3 includes bypass audit grep; Gate 4 includes
  post-delete assertion
- [ ] `INTENT-dq-enforcement.md` Phase 4 section contains a `### Graduation Retrospective:
  ops_recommendations` subsection covering all five event clusters with source PRs
- [ ] `INTENT-dq-enforcement.md` Session Map for other ops tables has a `Prerequisites`
  column referencing the Gate numbers from the methodology doc

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | post-edit | `exclude_before` staleness removed | `grep -c "NOT YET IMPLEMENTED" docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | `0` | Remove or rewrite the stale "NOT YET IMPLEMENTED" notice |
| 2 | post-edit | Unified Write Portal section present | `grep -c "## Unified Write Portal" docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | `1` | Add the section |
| 3 | post-edit | YAML-Data Drift section present | `grep -c "## YAML-Data Drift" docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | `1` | Add the section |
| 4 | post-edit | Table Graduation Prerequisites section present | `grep -c "## Table Graduation Prerequisites" docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | `1` | Add the section |
| 5 | post-edit | Bypass audit grep documented in methodology | `grep -c "append_jsonl" docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | `1` (inside bypass audit command) | Ensure Gate 3 includes the bypass audit grep |
| 6 | post-edit | Graduation Retrospective present in INTENT | `grep -c "Graduation Retrospective" docs/INTENT-dq-enforcement.md` | `1` | Add the subsection |
| 7 | post-edit | Session Map has Prerequisites column | `grep -c "Prerequisites" docs/INTENT-dq-enforcement.md` | `>= 1` | Update the Session Map table |
| 8 | post-edit | No new `enforced: false` entries introduced | `grep -c "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml` | Same count as before (64: 21 in ops.yaml, 43 in telemetry.yaml) -- this plan adds no YAML check changes | Revert any accidental YAML edits |

## Constraints
- Agent-first: extend existing sources; do not create new companion documents
- Content in `DQ_REMEDIATION_METHODOLOGY.md` must be generalisable across all tables;
  table-specific events belong in `INTENT-dq-enforcement.md`
- Do not re-document invariants already canonical in `CLAUDE.md`
  (`warehouse-as-source-of-truth`, physical deletion protocol steps) -- cross-reference instead
- No code changes; no YAML enforcement changes; no DQ check graduation in this PR
- No STRATEGIC plans per current temporary constraint (Decision 67 block on executor)

## Context
- Phase 3 (ratchet) is COMPLETE (PR #296). `enforced: false` entries are the graduation queue
- `ops_recommendations` Phase 4 required 15 PRs (#299-#325) and discovered patterns not
  captured in any single document: two-round bypass discovery, write-time/DQ-runtime split,
  wave ordering constraint, Class E root cause added mid-arc, Athena coercion surprise
- `DQ_REMEDIATION_METHODOLOGY.md` currently has a stale "NOT YET IMPLEMENTED" for
  `exclude_before` -- it was implemented in PR #299
- No decision manifests exist yet for `ops_decisions`, `ops_execution_plans`,
  `ops_session_log`, or `ops_priority_queue`
- `telemetry_agent_invocations_current` view is stale (column count mismatch confirmed
  in today's preflight sync -- blocks DQ runner for that table)
- Session UUID: 90238680-cf57-4711-b760-460ca01442fb

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` read in full before editing
- [ ] `docs/INTENT-dq-enforcement.md` read in full before editing
- [ ] Both files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1 -- Fix `exclude_before` staleness in DQ_REMEDIATION_METHODOLOGY.md

Locate the `### exclude_before Field` subsection in the `## Temporal Gate Specification`
section. Replace the block that reads:

```
**Status**: NOT YET IMPLEMENTED in the DQ runner. Adding this key to ops.yaml before
the runner supports it will silently no-op and create a false sense of enforcement.
A prerequisite IMPLEMENTATION plan is required before any Class B or Class C temporal
gate can be activated. Do not add `exclude_before` to any check config until the runner
supports it.
```

With:

```
**Status**: IMPLEMENTED (PR #299). The runner appends
`AND created_timestamp >= TIMESTAMP 'YYYY-MM-DD'` to the Athena WHERE clause, scoping
the check to records created on or after the specified date.

**Verification before use**: Always confirm the runner recognises the field for the
target table's timestamp column by running a test check and confirming the verdict
changes when you vary the anchor date. Documents can lag implementations -- verify
against the runner, not the docs.
```

---

### Step 2 -- Add `## Unified Write Portal` section to DQ_REMEDIATION_METHODOLOGY.md

Insert immediately after the Root Cause Taxonomy section (before `## Check Design Principles`).
The section must cover:

**Why a unified portal is required**
Multiple write surfaces produce inconsistent field validation. When several CLIs can
independently append to Iceberg, each caller has different validation coverage. A single
portal (`scripts/ops_data_portal.py`, three public functions: `file_rec`, `update_rec`,
`sync`) is the prerequisite for any write-time field enforcement.

**How enforcement works at the portal layer**
List the specific mechanisms deployed for `ops_recommendations` (each is the model for
other tables):
- Pydantic `Literal` validation at entry for domain fields (`status`, `effort`, `priority`,
  `risk`): invalid values raise before reaching Iceberg
- `source_registry.yaml` CI gate: any agent setting `source=` must be registered before
  its first production write; unregistered sources fail CI (not just DQ)
- `lint_acceptance_command()` at write time: structural validation of `acceptance` field
  rejects banned patterns (prose, python -c one-liners, absolute paths) before they reach
  the table
- Derived-field computation: `automatable` and `risk` are never set by agents -- computed
  from `file` + `effort` via formula in `config/executor_capabilities.yaml`
- The `write_time: true` annotation in ops.yaml/telemetry.yaml is the SIGNAL that a check
  is enforced by the portal, not just the DQ runner. When `write_time: true` and
  `enforced: false` appear together on the same check, the intended state is: new records
  comply (portal validates); old records do not (temporal gate or data correction pending).

**The two-round bypass problem (historical lesson)**
PR #314 consolidated five CLIs into the portal. It was not complete: PRs #322 and #323
subsequently closed three additional bypass routes -- a direct JSONL append path, an S3
outbox path that bypassed portal-level field validation, and a legacy CLI wrapper that called
`OpsWriter` directly. Consolidation events close known routes; they do not audit for unknown
ones. The bypass audit below must be run independently as Gate 3 in the prerequisites checklist.

**Bypass audit command (run before declaring the write gate complete)**
```bash
grep -rn "OpsWriter\|append_jsonl\|ops_writer\|sync_ops\.write\|drain\|s3_log_store" \
  scripts/ src/ .github/ .claude/ \
  --include="*.py" \
  | grep -v "ops_data_portal.py" \
  | grep -v "test_" \
  | grep -v "#"
```
Any match outside `scripts/ops_data_portal.py` is a potential bypass route. Review each hit
and confirm it does not write to the ops Iceberg tables without going through the portal.

---

### Step 3 -- Add `## YAML-Data Drift` section to DQ_REMEDIATION_METHODOLOGY.md

Insert immediately after the `## Unified Write Portal` section. The section must cover:

**The two drift problems**
1. **Write-path drift**: bypass routes allow new records to violate checks enforced in YAML.
   The write gate (Step 2) addresses this.
2. **YAML-data drift**: `enforced: false` entries accumulate. The write gate is deployed,
   new data is clean, but the transition from "old data bad / new data clean" to "all data
   clean" is never mechanically completed. `enforced: false` entries become permanent
   exemptions rather than a graduation queue.

**Three-layer defense**

*Layer 1 -- Graduation guard in validate.py (mechanical)*
Blocks flipping `enforced: false -> enforced: true` when the check's verdict in
`dq-latest.json` is `FAIL`. Run `validate.py` (not `--quick`) before any graduation flip.
The guard does not diagnose why the check fails -- that is the agent's job.

*Layer 2 -- `write_time: true` annotation (semantic signal)*
When this annotation is present and `enforced: false` is also present on the same check,
the meaning is: portal enforces for new writes; old records are the outstanding graduation
work. This pairing is the correct intermediate state. An `enforced: false` check WITHOUT
`write_time: true` means the write path has not yet been fixed -- both the data and the
portal need attention before this check can graduate.

*Layer 3 -- Temporal gate (`exclude_before`) (population isolation)*
Splits the population so old violations cannot block enforcement of new records.
Once deployed, graduation to `enforced: true` scopes only to post-anchor records.
The old population is no longer part of the check's target set.

**The Class E failure mode (drift despite all three layers)**
PRs #317 and #324 revealed a fourth failure mode: a DELETE step scripted in a plan VP but
never executed against Athena. The ghost row (`id=NULL`) survived every sync because the
Athena DML never ran -- only local files were modified. The DQ check (enforced: false) was
not blocking; nothing detected that the Athena state did not match the plan's intent.

Fix: post-delete assertions against the `_current` view are mandatory acceptance criteria,
not optional verification. The reference implementation is `scripts/cleanup_ops_rec_orphans.py`:
run DELETE, then OPTIMIZE, then VACUUM, then `SELECT COUNT(*)` from `_current` with the
predicate and assert zero rows. A non-zero assertion is a hard failure; do not merge.

**Monitoring drift accumulation**
The intermediate completion grep:
```bash
grep -n "enforced: false" config/data_quality/ops.yaml config/data_quality/telemetry.yaml \
  | grep -v "#"
```
Zero lines means every `enforced: false` check has an inline comment explaining why.
But presence of inline comments is not evidence of progress. After each wave session,
compare the `enforced: false` count to the pre-session count. If the count has not
decreased, the wave did not graduate any check -- investigate before declaring the
session complete.

---

### Step 4 -- Add `## Table Graduation Prerequisites` section to DQ_REMEDIATION_METHODOLOGY.md

Insert after `## YAML-Data Drift` and before `## Check Design Principles`. Five ordered
gates; each gate must be satisfied before the next can begin. Document the explicit
blocker for tables where a gate is not yet satisfied.

**Gate 1: Athena Infrastructure**
- SSO active (`sso_status: ok` in preflight)
- `_current` view exists for the table and is not stale: column count in the Glue catalog
  matches the base Iceberg table schema. A stale view returns `VIEW_IS_STALE` from Athena.
  Fix: `ALTER TABLE ... ADD COLUMNS` or recreate the view via Terraform.
- Type coercion inventory complete: identify `array<string>` columns in the table schema.
  Athena's `_current` view may return these as Python strings rather than native lists.
  Test by running `SELECT dependencies FROM ops_recommendations_current LIMIT 1` and
  checking the Python type of the result. If string-typed, array element checks
  (`relationships`, `expression` with `FILTER`) are blocked until rec-609 is resolved.

**Gate 2: Contract Definition**
- Decision manifest exists: `config/data_quality/decisions/{table}.yaml`, with
  `root_cause_class` and `human_decision` for every failing check
- Field contract authored: `description` + `semantics` metadata fields in
  `ops.yaml`/`telemetry.yaml` for every column (these are the field-level definitions
  consumed by agents -- do not create separate briefing docs)
- Bootstrap anchor date established: the date after which new records are expected to
  comply with the enforcement regime. This is the `exclude_before` value for all Class B
  checks on the table

**Gate 3: Write Gate Verification** *(must precede any enforcement)*
- Confirm all writes to this table flow through `ops_data_portal` by running the
  bypass audit grep from `## Unified Write Portal`
- Deploy write-time validators in the portal for key domain fields (Pydantic Literal,
  registry lookups, format checks) before any DQ check is graduated to `enforced: true`
- Note: this gate is already satisfied for all `ops_*` tables that share the portal.
  Re-run the bypass audit for each table to confirm no table-specific write paths exist

**Gate 4: Data Cleanup** *(must precede enforcement of presence and domain checks)*
- Class D and E records identified and wave ordering established: data cleanup and
  pollution deletion must complete before presence/domain check enforcement begins.
  The canonical example: dec-XXX status contamination (wave 3) had to be deleted before
  source/effort/priority presence checks (waves 1, 2) could be meaningful
- For any DELETE operation, script the full sequence before executing:
  1. DELETE from the Athena base table (not local outbox or cache)
  2. OPTIMIZE (rewrite data files to remove deleted row bytes)
  3. VACUUM (remove unreferenced snapshot files)
  4. SELECT COUNT(*) from `_current` with the delete predicate and assert zero rows
  Treat a non-zero assertion as a hard failure; do not merge. Use
  `scripts/cleanup_ops_rec_orphans.py` as the reference implementation

**Gate 5: Enforcement Infrastructure**
- `exclude_before` runner support confirmed working for this table's timestamp column
  (verify by running a test check and confirming the verdict changes with the anchor date)
- Graduation guard in `validate.py` is active; run `validate.py` (not `--quick`) before
  any `enforced: false -> enforced: true` flip

---

### Step 5 -- Add `### Graduation Retrospective: ops_recommendations` to INTENT-dq-enforcement.md

Insert as a new subsection within `## Phase 4: Data Quality Resolution`, immediately after
the `### Protocol for Each Wave Session` subsection. The subsection covers five event
clusters in the order they were discovered, each with source PRs:

**Event 1: The write gate required two consolidation rounds (PRs #314, #322, #323)**
PR #314 collapsed five CLIs into the portal (three public functions). At the time, this
was believed to be complete. PRs #322 and #323 subsequently closed three additional bypass
routes: a direct `append_jsonl` path that wrote to the S3 outbox without portal validation,
a legacy CLI wrapper calling `OpsWriter` directly, and an S3 staging path that bypassed
`_validate_field_constraints`. The lesson is that "consolidation" is not "complete" --
bypass routes are not always visible from the portal's perspective. The bypass audit in Gate 3
of the prerequisites checklist must be run as a distinct step, not assumed complete because
the portal exists.

**Event 2: `source` changed from a domain check to a lineage key with a CI gate (PR #309)**
`source` was initially modelled as an `accepted_values` DQ check with an enumerated list.
The accepted_values list had 11+ undocumented legitimate values missing from it (Class A).
Correcting the list was not the right fix. The correct model is: `source` is a harness-injected
lineage key (analytically equivalent to `session_id` for cross-table telemetry joins), never
set by agents. Enforcement moved from a DQ accepted_values check (discovered after the fact)
to a `source_registry.yaml` CI gate (rejected before the write reaches Iceberg). The DQ
check was dropped; the CI gate replaced it. This is the model for fields that are structural
system primitives: registry-backed CI gate, not DQ domain validation.

**Event 3: Wave ordering -- status deletion had to precede presence checks (PR #307 before #309, #320)**
35 records had null `source`, `effort`, and `priority`. These appeared to be Class B
bootstrap artifacts but were in fact `dec-XXX` ops_decisions records that had been written
to the wrong table during an early migration (Class D contamination). Until these were
physically deleted (wave 3, PR #307), the null cohort size was inflated, making waves 1
and 2's temporal gate analysis unreliable. The lesson: identify cross-table contamination
(wrong-table IDs like `dec-XXX` in `id`) and delete them before applying presence or
domain checks to the surviving population. Check `id` format before classifying null rates.

**Event 4: Class E root cause added mid-arc -- planned deletes not executed (PRs #317, #324)**
Two records, `rec-608` (hollow, written via the `append_jsonl` bypass path before PR #304
closed it) and a ghost row (`id=NULL`, a `compact()` artifact), survived multiple PRs that
claimed to delete them. PR #304 deleted the local S3 outbox files; those rows had already
drained to Athena so no Athena DML ran. A plan VP step for the `id=NULL` ghost row was
scripted but never executed. The Class E root cause class (cleanup step not executed or
not asserted) was added in PR #324 to the RCA taxonomy. The post-delete assertion pattern
(`scripts/cleanup_ops_rec_orphans.py`) is mandatory for all deletion operations.

**Event 5: Athena coercion -- `array<string>` from `_current` view is a Python string (PR #301)**
The Pydantic schema validator in `validate.py` failed on `dependencies` and `tags` fields
because `ops_recommendations_current` returns `array<string>` columns as Python strings
(e.g. `'["rec-001","rec-002"]'`) rather than native lists. This affects: Pydantic
validation, FK `relationships` checks in the DQ runner, and array element `expression`
checks. All array field checks are blocked until rec-609 resolves the `_current` view
type coercion. Check the type coercion inventory (Gate 1) for every table before authoring
array-field checks.

---

### Step 6 -- Update Phase 4 Session Map for other ops tables in INTENT-dq-enforcement.md

Replace the existing `### Session Map -- other ops tables` subsection. The new version
adds a `Prerequisites` column referencing the Gate numbers from DQ_REMEDIATION_METHODOLOGY.md
and states the concrete blocker for each table:

| Table | Est. sessions | Prerequisites not yet met | Known blockers |
|-------|--------------|--------------------------|----------------|
| `ops_decisions` | 1 | Gate 2 (no manifest), Gate 4 (nulls in `decision_id`, invalid `status` values) | Recency check FAIL in last DQ run (advisory: `enforced: false`); `decision_id` nulls need Class B temporal gate |
| `ops_execution_plans` | 1 | Gate 1 (rec-609 array FK blocks `relationships` check for `rec_id`), Gate 2 (no manifest) | `plan_id` nulls and duplicates; `rec_id` FK relationship check blocked on rec-609 |
| `ops_priority_queue` | 1 | Gate 2 (no manifest) | Nulls across `queue_run_id`, `rank`, `rec_id`, `mode`; recency beyond error threshold (`enforced: false`) |
| `ops_session_log` | 1 | Gate 2 (no manifest) | Nulls in `session_id` and `session_type`; `session_id` duplicates (SCD2 behaviour expected) |
| Telemetry tables (7) | 1 per table | Gate 1 (`telemetry_agent_invocations_current` view stale -- column count mismatch confirmed 2026-05-12), Gate 2 (no manifests), Decision 67 block | Deferred until executor restoration and telemetry maturity. Do not begin until Decision 67 is reversed |

Add a note after the table:

> For `ops_decisions` through `ops_session_log`: Gate 3 (write gate verification) is
> satisfied -- all four tables share the `ops_data_portal` write surface, and the bypass
> audit was completed for `ops_recommendations`. Re-run the bypass audit grep before the
> first session on each table to confirm no table-specific write path was added since
> the original audit.

---

### Step 7 -- Execute Verification Plan

Run each command from the Verification Plan table. All eight checks must pass.
Fix any failures before proceeding.

---

### Step 8 -- Report

State: which sections were added or modified in each file, verification results for all
eight VP steps, and any content decisions made during implementation that deviated from
this plan.
