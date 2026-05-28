# ops_recommendations DQ Remediation Briefing

Field-by-field analysis for the `ops_recommendations` Iceberg table.
Use this document in interactive remediation sessions alongside the decision manifest
(`config/agent/data_quality/decisions/ops_recommendations.yaml`) and the protocol
(`docs/dq/DQ_REMEDIATION_METHODOLOGY.md`).

DQ run reference: 2026-05-06T13:54Z -- 11 FAIL + 1 WARN + 1 ERROR + 2 PASS (16 checks).
Note: dq-latest.json (14:16Z) shows 16 ERROR because Athena was unreachable at that run.
Local cache: n=630 records sourced from logs/.recommendations-log.jsonl.

---

## Prerequisites

**HARD BLOCKERS for any follow-on IMPLEMENTATION session that re-runs the live DQ runner:**

**rec-609 (Critical/M)** -- The `ops_recommendations_current` Athena view returns
string-typed lists for `array<string>` columns (dependencies, tags). This breaks Pydantic
validation when the portal reads back records. Until rec-609 is resolved, any attempt to
run live acceptance checks against the Athena view will produce type errors in downstream
tooling, not DQ verdicts.

**rec-605 (Critical/L)** -- Pending Terraform fix for the `_rn` ambiguity in the
`ops_recommendations_current` view. The current view definition has a column naming
conflict that can cause incorrect deduplication results under some query engines. Until
rec-605 is resolved, DQ checks run against the `_current` view may return unexpected row
sets.

Until both prerequisites are resolved, DQ checks should be run against the base table
(`ops_recommendations`, not `ops_recommendations_current`) or treated as informational
only.

---

## Preamble

### Bootstrap Anchor

Records created before `2026-05-01` are the bootstrap cohort. Many null-field failures
trace to this cohort, which was written before the enforcement regime was established.
These records are not corrupt -- they simply predate field requirements. The remediation
strategy for bootstrap records is a temporal gate (`exclude_before: '2026-05-01'`) on
individual checks, not backfill.

### The 4 Root Cause Classes

- **Class A - Config Mismatch**: The YAML is wrong, not the data. Fix the check config.
- **Class B - Bootstrap Artifact**: Data predates the rule. Apply a temporal gate.
- **Class C - Write Path Gap**: Code never set the field. Fix the write path; gate on fix.
- **Class D - True Corruption**: Wrong value domain. Correct the data + add write-path guard.

### How to Use This Document

For each field: review the schema definition, current test coverage, violation count,
root cause reasoning, and proposed action. Record your decision in the manifest's
`human_decision` field (`approved`, `deferred`, or `declined`). When `approved`, the
agent generating the follow-on IMPLEMENTATION plan copies the proposed action into the
plan's Ordered Execution Steps.

Fields are presented in Terraform schema order. Tested fields (covered by ops.yaml) are
presented first, then untested candidate fields.

---

## Tested Fields

### `id`

**(a) Schema**: `id string COMMENT 'Recommendation ID (e.g., rec-001)'`

**(b) Current test coverage**: `not_null` (enforced: false)
Last verdict: FAIL

**(c) Violation count**: ~1-2 records (0.2% null rate, n=630).
No sample bad values; these are null/empty-string entries without an ID.

**(d) Root cause**: Class B - Bootstrap Artifact.
The DynamoDB ID allocator is the authoritative write path and has been required since
early in the project. The 1-2 null records are almost certainly pre-enforcement bootstrap
entries or migration edge cases.

**(e) Proposed action**: Once `exclude_before` is implemented in the DQ runner, add:
```yaml
id:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'
```
No data backfill needed. The 1-2 bootstrap records are not worth correcting individually.

**(f) Enforcement readiness**: NEEDS_TEMPORAL_GATE

**Decision**: <!-- pending -->

---

### `date` (dropped column)

**(a) Schema**: Column no longer exists. Was previously `date string` (creation date, now
replaced by `created_timestamp timestamp` per Decision 56, April 2026).

**(b) Current test coverage**: `not_null` (enforced: false)
Last verdict: ERROR (DQ runner cannot query a non-existent column)

**(c) Violation count**: N/A -- the check itself is invalid. The column was removed from
the Iceberg schema during the SCD2 migration. The DQ runner returns an Athena query error
when it tries to reference the dropped column, not a data quality verdict.

**(d) Root cause**: Class A - Config Mismatch. The ops.yaml check references a column
that no longer exists. The YAML is wrong; there is no data problem.

**(e) Proposed action**: Delete the `date` column section from ops_recommendations in
`config/agent/data_quality/ops.yaml`. Literal YAML diff:
```yaml
# Remove this entire block:
      date:
        tests:
          - not_null:
              enforced: false  # query error, column may not exist post-schema-migration
```

**(f) Enforcement readiness**: REMOVE_TEST

**Decision**: <!-- pending -->

---

### `title`

**(a) Schema**: `title string COMMENT 'Concise description'`

**(b) Current test coverage**: `not_null` (enforced: false)
Last verdict: FAIL

**(c) Violation count**: ~2 records (0.3% null rate, n=630).
Sample: bad-status records also lack titles -- these appear to be dec-XXX records (Decision
index entries) that were written to the ops_recommendations table during the early
migration period. They have IDs like `dec-002`, `dec-004`, etc.

**(d) Root cause**: Class B - Bootstrap Artifact. The 2 null records are migration
artefacts from the period before ops_recommendations and ops_decisions were cleanly
separated.

**(e) Proposed action**: Temporal gate once `exclude_before` is supported:
```yaml
title:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'
```
The 2 bootstrap records can be corrected via ops_data_portal as part of a broader
migration cleanup, but it is not blocking.

**(f) Enforcement readiness**: NEEDS_TEMPORAL_GATE

**Decision**: <!-- pending -->

---

### `source`

**(a) Schema**: `source string COMMENT 'Origin: executor-supervision, code-review, planning, brainstorm'`

**(b) Current test coverage**:
- `not_null` (enforced: false)
- `accepted_values`: values=[executor-supervision, code-review, planning, brainstorm,
  scheduled_verification, cron-review], severity: warn
Last verdict: FAIL (not_null) + WARN (accepted_values)

**(c) Violation count**: Two separate violation groups.

Not-null violations: ~35 records (5.6% empty string, n=630). Same bootstrap cohort as
effort and priority.

Accepted-values violations: ~120 records with source values not in the YAML list.
Distribution of unlisted sources:
- executor-postmortem: 41
- cli-migration-analysis: 27
- telemetry-audit: 15
- executor-gap-analysis: 11
- architectural-review: 10
- implement-agent: 5
- cc-scheduled-agent-test: 3
- Autonomous Postflight Cleanup: 2 (spaces and capitalisation -- format violation)
- manual: 2
- workflow-audit: 1
- tech-debt: 1
- delegate-investigation: 1
- infra-recommendation-executor: 1

**(d) Root cause**: Three classes apply.
- Class A (primary): The accepted_values list has not been updated as new source identifiers
  were introduced. 117+ records have legitimate source values that the YAML simply does not
  list yet.
- Class B: The 35 empty-string records are bootstrap artifacts from the pre-enforcement
  cohort. Empty strings, not nulls.
- Class D (2 records): "Autonomous Postflight Cleanup" uses spaces and capitalisation
  inconsistent with the kebab-case convention. Should be `autonomous-postflight-cleanup`.

**(e) Proposed action**:
1. (Class A fix) Expand the accepted_values list in ops.yaml. Proposed new list:
   ```yaml
   source:
     tests:
       - not_null:
           enforced: false  # ~35 bootstrap empty-string records remain
       - accepted_values:
           values:
             - executor-supervision
             - executor-postmortem
             - executor-gap-analysis
             - code-review
             - planning
             - brainstorm
             - scheduled_verification
             - cron-review
             - cli-migration-analysis
             - telemetry-audit
             - architectural-review
             - implement-agent
             - cc-scheduled-agent-test
             - autonomous-postflight-cleanup
             - manual
             - workflow-audit
             - tech-debt
             - delegate-investigation
             - infra-recommendation-executor
           severity: warn
   ```
2. (Class D fix) Correct the 2 "Autonomous Postflight Cleanup" records via ops_data_portal:
   set source to `autonomous-postflight-cleanup`.
3. (Class B) Apply temporal gate on not_null once exclude_before is supported.
4. After Class A and D fixes are deployed and the accepted_values list covers all known
   sources, upgrade accepted_values severity from warn to enforced: true.

**(f) Enforcement readiness**: NEEDS_WRITE_FIX (Class A YAML fix is required first; then
NEEDS_TEMPORAL_GATE for not_null after bootstrap cohort is gated)

**Decision**: <!-- pending -->

---

### `effort`

**(a) Schema**: `effort string COMMENT 'XS, S, M, L, or XL'`

**(b) Current test coverage**:
- `not_null` (enforced: false)
- `accepted_values`: values=[XS, S, M, L, XL], enforced: true
Last verdict: FAIL

**(c) Violation count**: ~35 records (5.6% null/empty-string rate, n=630).
Same bootstrap cohort as source/priority. For non-null records, all values are valid
(XS/S/M/L/XL). The accepted_values check (enforced: true) may also produce FAILs if the
DQ runner evaluates empty strings as invalid values.

**(d) Root cause**: Class B - Bootstrap Artifact. The 35 empty-string records are from the
pre-enforcement cohort. No ongoing write-path gap -- ops_data_portal validates effort for
new records.

**(e) Proposed action**: Apply temporal gate once `exclude_before` is supported:
```yaml
effort:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'
    - accepted_values:
        values: [XS, S, M, L, XL]
        enforced: true
        exclude_before: '2026-05-01'
```
The temporal gate on accepted_values ensures empty strings from the bootstrap cohort do
not block the enforcement gate.

**(f) Enforcement readiness**: NEEDS_TEMPORAL_GATE

**Decision**: <!-- pending -->

---

### `priority`

**(a) Schema**: `priority string COMMENT 'Critical, High, Medium, or Low'`

**(b) Current test coverage**:
- `not_null` (enforced: false)
- `accepted_values`: values=[Critical, High, Medium, Low], enforced: true
Last verdict: FAIL

**(c) Violation count**: ~35 records (5.6% null/empty-string rate, n=630).
Same bootstrap cohort as source/effort. For non-null records, all values are valid.

**(d) Root cause**: Class B - Bootstrap Artifact. Same pattern as effort.

**(e) Proposed action**: Same temporal gate strategy as effort:
```yaml
priority:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'
    - accepted_values:
        values: [Critical, High, Medium, Low]
        enforced: true
        exclude_before: '2026-05-01'
```

**(f) Enforcement readiness**: NEEDS_TEMPORAL_GATE

**Decision**: <!-- pending -->

---

### `status`

**(a) Schema**: `status string COMMENT 'open, closed, failed, declined, or superseded'`

**(b) Current test coverage**:
- `not_null` (enforced: false)
- `accepted_values`: values=[open, closed, failed, declined, superseded], enforced: false
Last verdict: FAIL

**(c) Violation count**: 33 records with invalid status values:
- 'Decided' x22 -- these carry `dec-XXX` IDs; they are ops_decisions entries written to
  the ops_recommendations table during early migration. 'Decided' is valid for ops_decisions
  but not for recommendations.
- 'Unknown' x9 -- migration artifact from before status was normalised
- '' x2 -- empty string (bootstrap artifact)
Sample IDs with bad status: dec-004, dec-002, dec-019, dec-027, dec-028, dec-008, dec-018,
dec-026, dec-014, dec-017 (all dec-XXX prefix).

**(d) Root cause**: Class D - True Corruption (primary) + Class B (2 empty strings).
The 22 'Decided' records are domain pollution: ops_decisions entries written into the
ops_recommendations table, likely during the initial migration when both tables shared a
write path. The 9 'Unknown' records are migration artifacts from before status values were
enumerated.

**(e) Proposed action**:
1. (Data correction) Use ops_data_portal to correct status on the 31 bad-domain records:
   - Records with 'Decided' status and dec-XXX IDs: these should likely be CLOSED or
     migrated to ops_decisions. INVESTIGATE FIRST: check if these records are duplicates
     of ops_decisions entries or unique information before deciding whether to close them
     or migrate them.
   - Records with 'Unknown' status: set to 'declined' or 'superseded' with an explanatory
     resolution note. INVESTIGATE FIRST: review each record's content to assign the
     appropriate terminal state.
2. (Write-path guard) rec-594 (Medium/XS, open): Add Pydantic Literal validation for
   the status field in ops_data_portal so future writes cannot set invalid status values.
   This is the primary prevention mechanism -- note rec-594 in the implementation plan.
3. (Enforcement) After correction and rec-594 is merged, enable the accepted_values check:
   ```yaml
   status:
     tests:
       - not_null:
           enforced: true
           exclude_before: '2026-05-01'
       - accepted_values:
           values: [open, closed, failed, declined, superseded]
           enforced: true
   ```

**(f) Enforcement readiness**: NEEDS_DATA_CORRECTION (correction must precede enforcement)

**Decision**: <!-- pending -->

---

### `automatable`

**(a) Schema**: `automatable boolean COMMENT 'Whether the executor can handle this'`

**(b) Current test coverage**: `not_null` (enforced: false)
Last verdict: FAIL

**(c) Violation count**: ~39 records (6.2% null rate, n=630).
These are records without an automatable value. The field is boolean, so no invalid-value
issue -- only null.

**(d) Root cause**: Class C - Write Path Gap. Early recommendations were filed via direct
JSONL appends or informal session writes that omitted the automatable field. The
ops_data_portal validates automatable for new records since at least early 2026.

**(e) Proposed action**:
1. (Backfill) Retrieve the ~39 records missing automatable from the local JSONL cache.
   For each open rec, set automatable based on the Executor Boundary rules (Decision 44):
   - Recs targeting executor boundary files: automatable=false
   - All other open recs: evaluate per rec and set true/false via ops_data_portal
   This is a manual task that requires human judgement for each record.
2. (Temporal gate + enforcement) After backfill:
   ```yaml
   automatable:
     tests:
       - not_null:
           enforced: true
           exclude_before: '2026-05-01'  # bootstrap cohort excluded
   ```

**(f) Enforcement readiness**: NEEDS_WRITE_FIX

**Decision**: <!-- pending -->

---

### `risk`

**(a) Schema**: `risk string COMMENT 'low, medium, or high'`

**(b) Current test coverage**:
- `not_null` (enforced: false)
- `accepted_values`: values=[low, medium, high], enforced: false
Last verdict: FAIL

**(c) Violation count**: Two violation groups.

Domain/case violations (Class D):
- 'unclassified' x28 -- predates the low/medium/high enum; used as a placeholder
- 'Low' x1, 'Medium' x1, 'High' x1 -- correct domain, wrong case (should be lowercase)
- 3 free-text strings from code review sessions where the risk field was accidentally
  populated with finding descriptions instead of a severity level. Examples:
  'Duplicate try/except json.loads pattern in 4+ locations; inconsistent error handling'
  'Consumers of --auto output must reverse-engineer JSON schema'
  'Minor style issue; local import inside function inconsistent with PEP 8'

Null/empty-string violations (Class B/C):
- ~36 records (5.7%) with empty-string risk values. Mix of bootstrap cohort (Class B) and
  write path gaps from informal sessions (Class C).

**(d) Root cause**: Class D (primary, 36 records with invalid domain values) + Class B/C
(36 empty-string records).

**(e) Proposed action**:
1. (Data correction -- Class D) Use ops_data_portal to correct known-bad values:
   - 'unclassified' x28: set to 'low' (most unclassified recs are low-risk automation work)
     INVESTIGATE FIRST: spot-check a sample before bulk-correcting; some may warrant medium.
   - 'Low'/'Medium'/'High' x3: normalise to lowercase equivalents.
   - 3 free-text records: set risk based on the actual risk level of each rec
     (inspect the rec content to determine low/medium/high).
2. (Write-path guard) Add Pydantic validation at the risk field write site to enforce
   lowercase low/medium/high. Consider adding this alongside rec-594 (status guard).
3. (Temporal gate + enforcement) After correction and write-path guard:
   ```yaml
   risk:
     tests:
       - not_null:
           enforced: true
           exclude_before: '2026-05-01'
       - accepted_values:
           values: [low, medium, high]
           enforced: true
   ```

**(f) Enforcement readiness**: NEEDS_DATA_CORRECTION

**Decision**: <!-- pending -->

---

### `last_updated_timestamp`

**(a) Schema**: `last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'`

**(b) Current test coverage**: Covered by the table-level `recency` check:
`warn_after_hours: 24, error_after_hours: 168, enforced: true`
Last verdict: PASS (pre-plan DQ run, 2026-05-06T13:54Z)

**(c) Violation count**: 0 violations. The recency check passed, confirming the table
has been written to within the last 24 hours as of the most recent successful DQ run.

**(d) Root cause**: N/A -- check is passing and already enforced.

**(e) Proposed action**: No action needed. This field and its check are in good standing.
The check is already `enforced: true`.

**(f) Enforcement readiness**: READY_NOW (check is already enforced and passing)

**Decision**: <!-- pending -->

---

## Untested Candidate Fields

Fields present in the Terraform schema that have no ops.yaml check yet. Adding a check
is deferred until the `exclude_before` support is available in the DQ runner (for Class B
and C fields) and until the prerequisites (rec-609, rec-605) are resolved.

---

### `created_timestamp`

**(a) Schema**: `created_timestamp timestamp COMMENT 'When this record was first created (SCD2)'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~23 records (3.7% null rate, n=630).

**(d) Root cause**: Class B - Bootstrap Artifact. The `created_timestamp` field was
introduced by Decision 56 (SCD2 schema simplification, April 2026) to replace the old
`date string` column. Records written before the schema migration may not have this field
set, either because the migration left some records unmapped or because pre-migration
writes used a different schema.

**(e) Proposed action**: Once `exclude_before` is supported in the DQ runner, add:
```yaml
created_timestamp:
  tests:
    - not_null:
        enforced: true
        exclude_before: '2026-05-01'
```
No data backfill for the 23 bootstrap records -- they are historical and the `date` field
covers their creation date in the old schema.

**(f) Enforcement readiness**: NEEDS_TEMPORAL_GATE

**Decision**: <!-- pending -->

---

### `file`

**(a) Schema**: `file string COMMENT 'Primary target file path'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~36 records (5.7% null rate, n=630).

**(d) Root cause**: Class C - Write Path Gap. The `file` field is required by the
recommendation schema (see PROJECT_CONTEXT.md: "Required. Primary target file") but was
omitted from early brainstorm and informal session recs. The ops_data_portal validates
this field for new records. The 36 missing records need to be backfilled manually.

**(e) Proposed action**:
1. (Backfill) For each open rec missing `file`, identify the primary target file and set
   it via ops_data_portal. This is a manual investigation task.
2. (Add check) After backfill:
   ```yaml
   file:
     tests:
       - not_null:
           enforced: true
           exclude_before: '2026-05-01'
   ```

**(f) Enforcement readiness**: NEEDS_WRITE_FIX

**Decision**: <!-- pending -->

---

### `context`

**(a) Schema**: `context string COMMENT 'Why this rec exists'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~36 records (5.7% null rate, n=630). Same cohort as `file`.

**(d) Root cause**: Class C - Write Path Gap. Same pattern as `file`.

**(e) Proposed action**: Same as `file` -- backfill and add not_null check with temporal
gate.

**(f) Enforcement readiness**: NEEDS_WRITE_FIX

**Decision**: <!-- pending -->

---

### `acceptance`

**(a) Schema**: `acceptance string COMMENT 'Shell command returning 0 on success'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~36 records (5.7% null rate, n=630). Same cohort as `file`.

**(d) Root cause**: Class C - Write Path Gap. Same pattern as `file` and `context`.
The acceptance command is required for executor-targetable recs but was not always set in
early brainstorm sessions.

**(e) Proposed action**: Same as `file` -- backfill and add not_null check with temporal
gate. Note: acceptance commands must follow the format rules in PROJECT_CONTEXT.md
(single inline command, no python -c, no trailing prose, no line numbers).

**(f) Enforcement readiness**: NEEDS_WRITE_FIX

**Decision**: <!-- pending -->

---

### `resolution`

**(a) Schema**: `resolution string COMMENT 'Why declined or superseded'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~545 records (86.5% null rate, n=630). High null rate is EXPECTED
and correct: resolution is only set for declined (23), superseded (25), and failed recs.

**(d) Root cause**: Class A - Config Mismatch (if a universal not_null check were added).
The field is intentionally null for 97%+ of records. A universal not_null check would be
semantically wrong.

**(e) Proposed action**: Do not add a universal not_null check. A conditional check
(`resolution IS NOT NULL WHERE status IN ('declined','superseded','failed')`) would be
meaningful, but the DQ runner does not currently support conditional checks. File as a
future enhancement to the runner if this gap becomes a priority.

**(f) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `execution_result`

**(a) Schema**: `execution_result string COMMENT 'success, failure, manual, or already_implemented'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~394 records (62.5% null rate, n=630). Expected: execution_result
is set by the executor on close only. All 262 open recs will have null execution_result.

**(d) Root cause**: Class C write path behavior (intentional). The null is expected for
open recs. For closed recs, execution_result should be set -- a conditional check would
be valuable but is not currently supported by the runner.

**(e) Proposed action**: No universal check. Future work: conditional check on closed recs.
For now, note that executor telemetry tracks execution outcomes independently via
`ops_execution_plans`.

**(f) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `execution_date`

**(a) Schema**: `execution_date string COMMENT 'ISO-8601 timestamp set by executor'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~403 records (64.0% null rate, n=630). Expected: set by executor
on close only.

**(d) Root cause**: Same as execution_result. NO_TEST_NEEDED.

**(e) Proposed action**: No universal check. Same conditional-check future work as
execution_result.

**(f) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `execution_branch`

**(a) Schema**: `execution_branch string COMMENT 'Branch name set by executor'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~421 records (66.8% null rate, n=630). Expected.

**(d) Root cause**: Same as execution_result. NO_TEST_NEEDED.

**(e) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `execution_pr_url`

**(a) Schema**: `execution_pr_url string COMMENT 'PR URL set by executor'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~518 records (82.2% null rate, n=630). Expected.

**(d) Root cause**: Same as execution_result. NO_TEST_NEEDED.

**(e) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `execution_steps`

**(a) Schema**: `execution_steps int COMMENT 'Step count set by executor'`

**(b) Current test coverage**: None.

**(c) Violation count**: ~584 records (92.7% null rate, n=630). Expected.

**(d) Root cause**: Same as execution_result. NO_TEST_NEEDED.

**(e) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `dependencies`

**(a) Schema**: `dependencies array<string> COMMENT 'Blocking rec IDs'`

**(b) Current test coverage**: None.

**(c) Violation count**: High null rate expected. Most recommendations have no inter-rec
dependencies -- null is the correct value, not a missing value.

**(d) Root cause**: Class A - Config Mismatch if a not_null check were added. The field is
intentionally optional.

**(e) Proposed action**: No check needed. Dependencies are validated at usage time (the
executor checks dependency status before running a rec).

**(f) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

### `tags`

**(a) Schema**: `tags array<string> COMMENT 'Categorisation tags'`

**(b) Current test coverage**: None.

**(c) Violation count**: High null rate expected. Tags are optional and not currently used
in any workflow.

**(d) Root cause**: Class A - Config Mismatch if a not_null check were added. The field is
intentionally optional.

**(e) Proposed action**: No check needed.

**(f) Enforcement readiness**: NO_TEST_NEEDED

**Decision**: <!-- pending -->

---

## Summary Table

| Field | Tests in ops.yaml | Last Verdict | Root Cause | Enforcement Ready |
|-------|------------------|--------------|-----------|------------------|
| id | not_null | FAIL | B | NEEDS_TEMPORAL_GATE |
| date | not_null | ERROR | A | REMOVE_TEST |
| title | not_null | FAIL | B | NEEDS_TEMPORAL_GATE |
| source | not_null + accepted_values (warn) | FAIL + WARN | A + B + D | NEEDS_WRITE_FIX |
| effort | not_null + accepted_values | FAIL | B | NEEDS_TEMPORAL_GATE |
| priority | not_null + accepted_values | FAIL | B | NEEDS_TEMPORAL_GATE |
| status | not_null + accepted_values | FAIL | D | NEEDS_DATA_CORRECTION |
| automatable | not_null | FAIL | C | NEEDS_WRITE_FIX |
| risk | not_null + accepted_values | FAIL | D | NEEDS_DATA_CORRECTION |
| last_updated_timestamp | recency | PASS | A | READY_NOW |
| created_timestamp | none | no test | B | NEEDS_TEMPORAL_GATE |
| file | none | no test | C | NEEDS_WRITE_FIX |
| context | none | no test | C | NEEDS_WRITE_FIX |
| acceptance | none | no test | C | NEEDS_WRITE_FIX |
| resolution | none | no test | A | NO_TEST_NEEDED |
| execution_result | none | no test | C | NO_TEST_NEEDED |
| execution_date | none | no test | C | NO_TEST_NEEDED |
| execution_branch | none | no test | C | NO_TEST_NEEDED |
| execution_pr_url | none | no test | C | NO_TEST_NEEDED |
| execution_steps | none | no test | C | NO_TEST_NEEDED |
| dependencies | none | no test | A | NO_TEST_NEEDED |
| tags | none | no test | A | NO_TEST_NEEDED |

**Immediately actionable (no runner changes required)**:
1. REMOVE_TEST: delete `date` column check from ops.yaml (Class A, trivial)
2. NEEDS_DATA_CORRECTION: correct status values (31 records) -- rec-594 is the write-path guard
3. NEEDS_DATA_CORRECTION: correct risk values (36 records) -- add Pydantic validation
4. NEEDS_WRITE_FIX: expand source accepted_values list (Class A config fix)

**Require `exclude_before` implementation in DQ runner**:
- id, title, effort, priority, created_timestamp (NEEDS_TEMPORAL_GATE)
- source not_null, file, context, acceptance (after write-path fix + temporal gate)
- automatable (after backfill + temporal gate)
