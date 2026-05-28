# DQ Remediation Methodology

Shared protocol for all DQ remediation sessions across ops and telemetry tables.
Load this file at the start of any session that involves DQ check authoring, root cause
analysis, or enforcement gating decisions.

---

## Root Cause Taxonomy

Every DQ failure is assigned one of four root cause classes. The class determines the
remediation path. Assign the class that matches the PRIMARY cause; note secondary causes
in the `notes` field of the decision manifest.

### Class A - Config Mismatch

The YAML check configuration is wrong, not the data.

Examples:
- `date` column listed in ops.yaml but dropped from the Iceberg schema (ERROR verdict)
- `source.accepted_values` list does not include legitimate source identifiers written by
  production code (WARN/FAIL verdict for valid data)
- Recency threshold too tight relative to actual write frequency

Fix: Update `config/agent/data_quality/ops.yaml` or `telemetry.yaml`. No data changes needed.
No `exclude_before` gate needed. Safe to enforce immediately after YAML is corrected.

### Class B - Bootstrap Artifact

Data predates the enforcement regime. The records were written before the field was
required, before the schema was migrated, or before the write path set the field.
The data is not wrong -- it simply predates the rule.

Examples:
- `id`, `title`, `source`, `effort`, `priority` null for the ~35 records written before
  the recommendation schema was standardised
- `created_timestamp` null for records written before Decision 56 (SCD2 migration, May 2026)

Fix: Apply a temporal gate via `exclude_before` so the check applies only to records
created after the enforcement anchor date. The bootstrap cohort is left as-is; it will
age out of the `_current` view naturally as recommendations are closed and superseded.

The bootstrap anchor for ops_recommendations is `2026-05-01` (the date the enforcement
regime was established).

### Class C - Write Path Gap

The code path that writes these records never set the field, or set it inconsistently.
The data is incomplete, not corrupt. The failure is ongoing: new records written today
will also fail the check.

Examples:
- `automatable` null for records from sources that do not go through ops_data_portal
  (early direct-JSONL writes lacked the field)
- `file`, `context`, `acceptance` null for older recs filed via brainstorm or manual entry
- `execution_result`, `execution_date`, etc. null for open recs (intentionally unset until
  the executor closes them -- but for closed records these should be set)

Fix: Identify the write site(s) that omit the field and add the field. After the fix is
deployed, enforce for new records only via a temporal gate anchored to the fix date.
Old records with nulls are left as bootstrap artifacts (Class B post-fix).

### Class D - True Corruption

Wrong value domain leaked into the field. The data is incorrect, not just missing.
This usually traces to a write path that accepted unvalidated input.

Examples:
- `status` field contains 'Decided' (ops_decisions domain) and 'Unknown' (migration
  artifact) -- neither is a valid recommendation status
- `risk` field contains 'unclassified', 'Low', 'Medium', 'High' (wrong case or domain),
  and free-text strings that leaked from code review findings
- `source` field contains 'Autonomous Postflight Cleanup' (spaces, wrong format) written
  by a script that did not normalise its source identifier

Fix: Two-phase remediation:
1. Data correction: use `ops_data_portal` to overwrite the bad records with correct values.
2. Write-path guard: add Pydantic Literal validation (or equivalent) at the write site so
   the corruption cannot recur. This is the primary value of rec-594 for `status`.

### Class E - Cleanup Step Not Executed or Not Asserted

A planned DELETE or data-correction step was approved and scripted but never executed
against the warehouse, or was executed without an assertion that confirmed the rows are
gone from the `_current` view. The local outbox or local cache may have been modified
(creating false confidence), while the Athena table was never touched.

Examples:
- PR #304 deleted the local S3 outbox files for rec-608 and rec-633. Those rows had
  already drained to Athena before the plan ran, so no Athena DML was issued.
  The warehouse rows persisted despite the PR appearing to "delete" them.
- PLAN-dq-write-enforcement-unification VP Step 7 prescribed an inline DELETE for
  `id IS NULL`; the implementation commit contains no evidence it was executed.
  The ghost row (id=NULL) continued to appear in sync rejects on every subsequent pull.

Fix: Execute the DELETE via a dedicated script that:
1. Runs the DELETE against the Athena base table (not the local outbox or cache).
2. Issues a VACUUM to expire deleted snapshots.
3. Queries the `_current` view post-delete and asserts zero matching rows remain.
   Treat a non-zero assertion as a hard failure; do not proceed to merge.

See `scripts/cleanup_ops_rec_orphans.py` as the reference implementation for this pattern.

---

## Unified Write Portal

Multiple write surfaces produce inconsistent field validation. When several CLIs can
independently append to Iceberg, each caller has different validation coverage. A single
portal (`scripts/ops_data_portal.py`, three public functions: `file_rec`, `update_rec`,
`sync`) is the prerequisite for any write-time field enforcement.

### How enforcement works at the portal layer

The following mechanisms are deployed for `ops_recommendations` (each is the model for
other tables):

- **Pydantic Literal validation at entry** for domain fields (`status`, `effort`, `priority`,
  `risk`): invalid values raise before reaching Iceberg
- **`source_registry.yaml` CI gate**: any agent setting `source=` must be registered before
  its first production write; unregistered sources fail CI (not just DQ)
- **`lint_acceptance_command()` at write time**: structural validation of `acceptance` field
  rejects banned patterns (prose, python -c one-liners, absolute paths) before they reach
  the table
- **Derived-field computation**: `automatable` and `risk` are never set by agents -- computed
  from `file` + `effort` via formula in `config/agent/executor/capabilities.yaml`
- **`write_time: true` annotation** in ops.yaml/telemetry.yaml is the SIGNAL that a check
  is enforced by the portal, not just the DQ runner. When `write_time: true` and
  `enforced: false` appear together on the same check, the intended state is: new records
  comply (portal validates); old records do not (temporal gate or data correction pending).

### The two-round bypass problem (historical lesson)

PR #314 consolidated five CLIs into the portal. It was not complete: PRs #322 and #323
subsequently closed three additional bypass routes -- a direct JSONL append path, an S3
outbox path that bypassed portal-level field validation, and a legacy CLI wrapper that called
`OpsWriter` directly. Consolidation events close known routes; they do not audit for unknown
ones. The bypass audit below must be run independently as Gate 3 in the prerequisites checklist.

### Bypass audit command (run before declaring the write gate complete)

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

## YAML-Data Drift

### The two drift problems

1. **Write-path drift**: bypass routes allow new records to violate checks enforced in YAML.
   The write gate (previous section) addresses this.
2. **YAML-data drift**: `enforced: false` entries accumulate. The write gate is deployed,
   new data is clean, but the transition from "old data bad / new data clean" to "all data
   clean" is never mechanically completed. `enforced: false` entries become permanent
   exemptions rather than a graduation queue.

### Three-layer defense

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

### The Class E failure mode (drift despite all three layers)

PRs #317 and #324 revealed a fourth failure mode: a DELETE step scripted in a plan VP but
never executed against Athena. The ghost row (`id=NULL`) survived every sync because the
Athena DML never ran -- only local files were modified. The DQ check (enforced: false) was
not blocking; nothing detected that the Athena state did not match the plan's intent.

Fix: post-delete assertions against the `_current` view are mandatory acceptance criteria,
not optional verification. The reference implementation is `scripts/cleanup_ops_rec_orphans.py`:
run DELETE, then OPTIMIZE, then VACUUM, then `SELECT COUNT(*)` from `_current` with the
predicate and assert zero rows. A non-zero assertion is a hard failure; do not merge.

### Monitoring drift accumulation

The intermediate completion grep:

```bash
grep -n "enforced: false" config/agent/data_quality/ops.yaml config/agent/data_quality/telemetry.yaml \
  | grep -v "#"
```

Zero lines means every `enforced: false` check has an inline comment explaining why.
But presence of inline comments is not evidence of progress. After each wave session,
compare the `enforced: false` count to the pre-session count. If the count has not
decreased, the wave did not graduate any check -- investigate before declaring the
session complete.

---

## Table Graduation Prerequisites

Five ordered gates; each gate must be satisfied before the next can begin. Document the
explicit blocker for tables where a gate is not yet satisfied.

### Gate 1: Athena Infrastructure

- SSO active (`sso_status: ok` in preflight)
- `_current` view exists for the table and is not stale: column count in the Glue catalog
  matches the base Iceberg table schema. A stale view returns `VIEW_IS_STALE` from Athena.
  Fix: `ALTER TABLE ... ADD COLUMNS` or recreate the view via Terraform.
- Type coercion inventory complete: identify `array<string>` columns in the table schema.
  Athena's `_current` view may return these as Python strings rather than native lists.
  Test by running `SELECT dependencies FROM ops_recommendations_current LIMIT 1` and
  checking the Python type of the result. If string-typed, array element checks
  (`relationships`, `expression` with `FILTER`) are blocked until rec-609 is resolved.

### Gate 2: Contract Definition

- Decision manifest exists: `config/agent/data_quality/decisions/{table}.yaml`, with
  `root_cause_class` and `human_decision` for every failing check
- Field contract authored: `description` + `semantics` metadata fields in
  `ops.yaml`/`telemetry.yaml` for every column (these are the field-level definitions
  consumed by agents -- do not create separate briefing docs)
- Bootstrap anchor date established: the date after which new records are expected to
  comply with the enforcement regime. This is the `exclude_before` value for all Class B
  checks on the table

### Gate 3: Write Gate Verification *(must precede any enforcement)*

- Confirm all writes to this table flow through `ops_data_portal` by running the
  bypass audit grep from the Unified Write Portal section
- Deploy write-time validators in the portal for key domain fields (Pydantic Literal,
  registry lookups, format checks) before any DQ check is graduated to `enforced: true`
- Note: this gate is already satisfied for all `ops_*` tables that share the portal.
  Re-run the bypass audit for each table to confirm no table-specific write paths exist

### Gate 4: Data Cleanup *(must precede enforcement of presence and domain checks)*

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

### Gate 5: Enforcement Infrastructure

- `exclude_before` runner support confirmed working for this table's timestamp column
  (verify by running a test check and confirming the verdict changes with the anchor date)
- Graduation guard in `validate.py` is active; run `validate.py` (not `--quick`) before
  any `enforced: false -> enforced: true` flip

---

## Check Design Principles

Every DQ check falls into one of five categories. When authoring or reviewing checks for a
field, evaluate the field against all five -- even when some categories do not apply.
Deciding a category is irrelevant is different from skipping the evaluation.

### Five Check Categories

| Category | Check Types | What It Answers |
|----------|-------------|-----------------|
| Presence | `not_null` | Does a value exist? |
| Identity | `expression` (regex) | Is the value the right shape? |
| Domain | `accepted_values`, range expression | Does the value belong to the valid set? |
| Cardinality | `unique`, `relationships` | Are count and referential constraints met? |
| Ordering | `expression` (temporal comparison) | Are sequencing invariants preserved? |

### Detection vs. Contract

Presence checks (`not_null`) detect data quality problems -- they fire when something is
missing. The other four categories encode a field's semantic contract -- they define what the
field means, not just whether it exists.

A `not_null` check that passes on an `id` field tells you a value is present. It does not
tell you the value is a valid recommendation ID. Without an identity check
(`id RLIKE '^rec-[0-9]+$'`), an empty string, a decision ID (`dec-001`), or a free-text
label would all pass.

Start with presence. Then ask what shape, domain, cardinality, and ordering constraints the
field's definition implies. Add a check for each constraint that is both meaningful and
testable at the current schema maturity level.

### Array Field Checks

Athena `array<string>` columns require element-level expressions. Use the filter pattern:

```yaml
field:
  tests:
    - expression:
        sql: "CARDINALITY(FILTER(field, x -> NOT REGEXP_LIKE(x, '<pattern>'))) = 0"
        description: "All elements must match <pattern>"
```

Array element checks are blocked until rec-609 (Athena view returns string-typed lists
instead of native `array<string>`) is resolved. Do not activate these checks before
rec-609 is closed.

---

## Temporal Gate Specification

### `exclude_before` Field

An optional key that can be added under any column check configuration in ops.yaml or
telemetry.yaml. When present, the DQ runner appends
`AND created_timestamp >= TIMESTAMP 'YYYY-MM-DD'` to the Athena WHERE clause, scoping
the check to records created on or after the specified date.

```yaml
id:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'   # skip bootstrap cohort
```

**Status**: IMPLEMENTED (PR #299). The runner appends
`AND created_timestamp >= TIMESTAMP 'YYYY-MM-DD'` to the Athena WHERE clause, scoping
the check to records created on or after the specified date.

**Verification before use**: Always confirm the runner recognises the field for the
target table's timestamp column by running a test check and confirming the verdict
changes when you vary the anchor date. Documents can lag implementations -- verify
against the runner, not the docs.

**Anchor date for ops_recommendations**: `2026-05-01`. Records created before this date
are the bootstrap cohort. All Class B temporal gates for this table should use this anchor.

---

## Enforcement Readiness Taxonomy

Each field in a decision manifest is assigned one `enforcement_ready` state from this list.

| State | Meaning |
|-------|---------|
| `READY_NOW` | Check can be flipped to `enforced: true` with no other changes. The check already passes or the YAML fix is trivial. |
| `NEEDS_TEMPORAL_GATE` | Check should be enforced once `exclude_before` is implemented in the runner. Root cause is Class B. |
| `NEEDS_WRITE_FIX` | A write path gap (Class C) must be resolved and deployed before enforcement. Enforce with temporal gate anchored to the fix date. |
| `NEEDS_DATA_CORRECTION` | Corrupt values (Class D) must be fixed in the Iceberg table via `ops_data_portal` before enforcement. May also need a write-path guard. |
| `NEEDS_PROTOTYPE` | Insufficient data to classify. Requires a live Athena query or investigation before a remediation path can be chosen. |
| `REMOVE_TEST` | The check is invalid and should be deleted from ops.yaml / telemetry.yaml. Common cause: column dropped from schema. |
| `NO_TEST_NEEDED` | A null check would be semantically wrong for this field. The field is intentionally null for most records (e.g., execution fields for open recs, optional array fields). A conditional check may be appropriate in a future session. |

---

## Human Decision States

Each field entry in a decision manifest carries a `human_decision` key. The human reviews
the analysis in the briefing doc and records their decision interactively.

| State | Meaning |
|-------|---------|
| `pending` | Not yet reviewed. Initial state for all entries. |
| `approved` | Human has reviewed the root cause class and enforcement_ready verdict and agrees. The implementation steps in the briefing's proposed action section can proceed. |
| `deferred` | Analysis is correct but the remediation is intentionally postponed. Add a `deferred_reason` note. |
| `declined` | The proposed action is rejected. Add a `declined_reason` note explaining the alternative. |

When a decision is `approved`, the agent generating the follow-on IMPLEMENTATION plan
should copy the proposed action from the briefing into the plan's Ordered Execution Steps.

---

## Agent Session Protocol

A remediation session for a single table follows this sequence:

(a) Load `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` (this file).

(b) Load `config/agent/data_quality/decisions/{table}.yaml` (the decision manifest for the
    target table).

(b2) Field contract authority: `config/agent/data_quality/ops.yaml` (or `telemetry.yaml`) is
     the canonical field contract -- this is the ops.yaml extended contract. The `description`
     and `semantics` metadata fields within each column entry are the field's semantic
     definition -- consumed by agents, ignored by the DQ runner. The separate human-readable
     briefing doc pattern (e.g., `docs/dq/ops-recommendations-remediation-briefing.md`) is
     a legacy artefact created before the agent-first contract was established. Do not create
     new briefing docs for new tables. Add field context as `description` + `semantics`
     fields in the YAML directly. The decision manifest YAML remains the remediation state
     authority.

(c) Load `config/agent/data_quality/{ops|telemetry}.yaml` (the DQ check configuration).

(d) Load `logs/debug/dq-latest.json` (latest DQ run results, if available).

(e) Walk only the fields where `human_decision: pending`. Present one field at a time:
    - Show the briefing section for the field
    - Show current DQ verdict and violation count
    - Ask the human to confirm the root cause class and enforcement_ready verdict
    - Record `human_decision` and `decided_date` in the manifest

(f) Once a field is `approved`, generate the specific remediation artifact:
    - Class A: YAML diff for ops.yaml (show the exact change)
    - Class B: Note that this requires exclude_before implementation as a prerequisite
    - Class C: Identify the write site and draft the IMPLEMENTATION plan step
    - Class D: Draft the `ops_data_portal` command(s) and the write-path guard rec
    - REMOVE_TEST: YAML diff removing the column section

(g) File each approved Class D correction or write-path guard as a new rec via
    `ops_data_portal` if not already tracked.

---

## Multi-Table Directory Layout

Decision manifests live at `config/agent/data_quality/decisions/{table}.yaml`, one file per
table. The table name matches the key used in ops.yaml or telemetry.yaml.

Tables covered by `config/agent/data_quality/ops.yaml`:
- `ops_recommendations` -- this manifest
- `ops_decisions`
- `ops_execution_plans`
- `ops_session_log`
- `ops_priority_queue`

Tables covered by `config/agent/data_quality/telemetry.yaml`:
- `telemetry_sessions`
- `telemetry_phases`
- `telemetry_steps`
- `telemetry_process_events`
- `telemetry_model_calls`
- `telemetry_transcripts`
- `telemetry_agent_invocations`

Create the manifest for a table when beginning remediation work on that table. Use
`config/agent/data_quality/decisions/ops_recommendations.yaml` as the template.
