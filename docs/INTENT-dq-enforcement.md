# Intent: Data Quality Enforcement Maturity

This document is the single strategic anchor for the data quality enforcement maturity
arc. Every agent planning or implementing work in this area reads this document first,
checks the current phase status, and follows the agent instructions before scoping
anything new.

**Why this document exists:** The arc spans five or more implementation sessions.
Without a persistent anchor, each new agent session re-derives context from individual
PLAN files and risks overriding decisions already made. This document removes that cost.

**Supersedes:** `docs/plans/PLAN-dq-gate-predicate.md`. Its scope was absorbed into
Phase 2. Do not use that plan as the basis for a new /implement session; Phase 2 is
already merged. Note: that plan specified a narrow `DataQualityVerifier.covers` list.
The actual implementation (PR #286) deployed the broader list instead. The narrow-list
decision does not hold.

**References (not superseded):** `docs/plans/PLAN-audit-ops-recs-dq-scalability.md`
(the audit identifying the six gaps), `PLAN-dq-harden-gaps-1-4-5.md` (Phase 0, merged),
`PLAN-dq-validate-integration.md` (Phase 1, merged).

**Builds on:** `docs/INTENT-verification-system.md` (three-layer quality pyramid, Layer 2
is where the DQ framework operates), `docs/INTENT-validation-architecture.md` (two-tier
validate.py and EC2 self-hosted runner substrate; Phase 5 of this arc depends on that
document's migration sequence Step 3).

**Cross-arc:** `docs/INTENT-ops-decisions-graduation.md` is the strategic anchor for
the `ops_decisions` graduation arc (portal-first migration plus DECISIONS.md
decommission). That arc's Phase 5 (DQ Graduation) graduates `ops_decisions` DQ
checks from `enforced: false` to `enforced: true`. That arc's Phase 6 folds into
Phase 5 of this arc (the `enforced` field deletion).

**HARD sequencing constraint:** Phase 5 of THIS arc must NOT begin until Phase 5
of that arc has merged. Reason: if the `enforced` field is deleted globally before
`ops_decisions` data correction (that arc's Phase 4) and check graduation (that
arc's Phase 5) complete, every `enforced: false` check on `ops_decisions` becomes
unconditionally blocking on every CI run while still failing against uncorrected
data. This is a HARD prerequisite enforced by cross-references in both INTENT
docs, not best-effort coordination.

---

## North Star

**Definition equals enforcement.** Every check in a DQ YAML file gates merges. No
`enforced` field, no tier exception, no staleness bypass. If a check exists, it blocks.

The `enforced` ratchet field introduced in Phase 3 is explicitly transitional
infrastructure. It is deleted in Phase 5 when the last unenforced check graduates.
Without that deletion, the field re-creates the decoupling the arc was designed to
eliminate. The deletion is not optional.

---

## Phase Overview

| # | Phase | Status | Plan | PR |
|---|-------|--------|------|----|
| 0 | Foundation Repairs (Gaps 1, 4, 5) | COMPLETE | PLAN-dq-harden-gaps-1-4-5.md | #285 |
| 1 | Validate.py Integration (Gap 2) | COMPLETE | PLAN-dq-validate-integration.md | #289 |
| 2 | Gate Mechanism (Gaps 3, 6 + runner fix) | COMPLETE | PLAN-dq-gate-predicate.md | #286 |
| 3 | Ratchet Implementation | COMPLETE | PLAN-dq-ratchet-phase-3.md | #296 |
| 4 | Data Quality Resolution | IN_PROGRESS | Multiple sessions required | Multiple PRs |
| 5 | Convergence | NOT_STARTED | (fill in when /plan creates it) | (fill in when merged) |

**Phase 4 is a blocking gate on Phase 5.** Phase 5 must not begin until every check in
both YAML files is `enforced: true`. No `enforced: false` entries - commented or
uncommented - may remain at Phase 5 entry. Category B data-condition items must be
resolved and graduated before Phase 5 starts; adding an inline comment is an intermediate
milestone, not a completion condition.

**Phase 3 is urgent.** Phase 2 deployed with broad `DataQualityVerifier.covers`
(including `scripts/ops_data_portal.py` and `src/data/**`). With the current active DQ
failures (run `.venv/Scripts/python.exe -m scripts.data_quality_runner` for the current
count), any executor run against a V2 plan touching those paths will be blocked the
moment the executor is restored. Phase 3 (the ratchet) must land before the executor
is re-enabled.

---

## Phase 0: Foundation Repairs

**Status:** COMPLETE
**Plan:** docs/plans/PLAN-dq-harden-gaps-1-4-5.md
**PR:** #285

Closed Gaps 1, 4, and 5 from the audit: empty-PASS fix (total=0 now returns
`FAIL, HARD_GATE`), recency checks added to all five ops tables, and the verifier
harness fail-open path fixed. The `total == 0 -> FAIL HARD_GATE` short-circuit lives
at `scripts/verifiers/data_quality.py:83-89` and Phase 3 must not regress it.

---

## Phase 1: Validate.py Integration

**Status:** COMPLETE
**Plan:** docs/plans/PLAN-dq-validate-integration.md
**PR:** #289

Closed Gap 2: wired the DQ runner auto-invoke into `validate.py --integration`. Also
landed `docs/INTENT-validation-architecture.md` as an architectural anchor for the
two-tier validate surface and EC2 self-hosted runner substrate.

---

## Phase 2: Gate Mechanism

**Status:** COMPLETE
**Plan:** docs/plans/PLAN-dq-gate-predicate.md
**PR:** #286

Closed Gaps 3 and 6. The following changes landed:

- **Stale-DQ policy (Gap 3):** `scripts/verifiers/data_quality.py` stale path (>1h)
  now returns `FAIL, HARD_GATE` with a remediation message. Missing-file path is
  `SKIPPED, ADVISORY` as of this PR; that gap is closed in Phase 3 (see Known Gaps).
- **Coverage-based gate predicate (Gap 6):** `scripts/executor/postflight.py` now
  blocks based on whether the failing verifier's `covers` intersects the plan's scope
  files, not on the V3 tier alone. `is_v3` is retained as a safe fallback when plan
  scope cannot be loaded.
- **Harness changes:** `scope_intersects_covers()` added to `scripts/verifiers/harness.py`.
  `covers: list[str] = ["**"]` added to the `Verifier` base class.
- **Verifier covers declared:** All four concrete verifiers now declare `covers`.
- **Empty-result guard:** The `if not result.results: return` early exit in
  `_save_latest_result` was already present from Phase 0. No new fix was needed.

**Implementation divergence from the superseded plan:**
`DataQualityVerifier.covers` was implemented as:
```python
covers = [
    "config/agent/data_quality/**",
    "scripts/data_quality_runner.py",
    "scripts/ops_data_portal.py",
    "src/data/**",
]
```
The superseded plan had proposed this same broad list. The planning session for this
INTENT document had suggested a narrower two-item list as a risk mitigation, but the
actual implementation predated that suggestion. The broad list is live. Phase 3
(the ratchet) is therefore urgent - see the Phase Overview warning above.

---

## Phase 3: Ratchet Implementation

**Status:** COMPLETE
**Plan:** docs/plans/PLAN-dq-ratchet-phase-3.md
**PR:** #296

**Prerequisite:** None - Phase 2 is already merged.

Introduces the `enforced` boolean field to the DQ YAML check schema and wires it into
the dataclass, loader, compiler, and graduation guard. This phase makes the broad
`covers` list in Phase 2 safe to leave in place: once the ratchet lands, only
`enforced: true` failures block merges.

**Implementation order constraint:** Steps 1 and 2 (runner infrastructure and compiler
change) must land in a single atomic commit or PR before any YAML annotation begins
(Step 3). The state where YAML has `enforced: false` entries but the compiler does not
yet respect them is dangerous: failures continue blocking as if the ratchet were not in
place, misleading the implementer into thinking their YAML edits had no effect. Steps 1
and 2 are pure Python changes with no YAML dependency and can be landed, tested, and
merged as a unit before Step 3 begins.

### Step 1: Runner infrastructure - dataclass, loader, and per-check output

The following changes form a single unit and must land together. They have no YAML
dependency.

**1a. Check dataclass:** Add `enforced: bool = True` to the `Check` dataclass. The
default `True` preserves backward compatibility: during the window between Steps 1+2
merging and Phase 3 annotation completing (Step 3), checks without an explicit `enforced`
field in the YAML behave identically to today (fully enforced). After Phase 3 annotation,
every `severity: error` check will have an explicit `enforced` value and the default
applies only to newly added checks going forward.

**1b. Loader changes:** Update `load_checks` and all `_compile_column_test` branches
to read `enforced` from the YAML params dict and populate `check.enforced`. The field
lives in different YAML positions depending on the test form; see Step 3 for the schema
for each form. For bare-string tests that cannot carry the field (e.g., `- not_null` as
a plain string), `enforced` defaults to `True` - they were defined before the ratchet
and are assumed enforced unless the entry is converted to dict form with `enforced: false`.

**1c. `_save_latest_result` extension:** Extend to also write a `checks` array alongside
the existing aggregate fields. The schema of each entry must be identical to what
`_print_results --json` already produces (see `scripts/data_quality_runner.py` lines
488-499). The field name is `"test"` (matching `_print_results`; not `"test_type"` from
the dataclass attribute name). Example output:

```json
{
  "verdict": "FAIL",
  "total": 125,
  "passed": 66, "failed": 59, "warned": 0, "errored": 0,
  "timestamp": "...", "duration_seconds": 12.3,
  "checks": [
    {"table": "ops_recommendations", "column": "status", "test": "accepted_values", "verdict": "FAIL"},
    {"table": "ops_recommendations", "column": "id",     "test": "not_null",         "verdict": "PASS"},
    {"table": "ops_recommendations", "column": null,     "test": "row_count",         "verdict": "PASS"}
  ]
}
```

The per-check identifier for the graduation guard is the `(table, column, test)` tuple.
For table-level checks (`row_count`, `recency`) where `column` is `None` in the `Check`
dataclass, serialize as `null` in the JSON.

**Dry-run note:** `_save_latest_result` is called in dry-run mode when `--dry-run` and
`--json` are both passed. In that mode all check verdicts are `"SKIP"`. The graduation
guard (Step 4) must treat `SKIP` as inconclusive, not as `PASS`. Only `"PASS"` from a
live (non-dry-run) DQ run permits graduation.

**Regression guard:** The `total == 0 -> FAIL, HARD_GATE` short-circuit at
`scripts/verifiers/data_quality.py:83-89` must not be regressed.

### Step 2: Compiler change - enforced-aware verdict aggregation

Modify `run_checks` (or the verdict aggregation path) in
`scripts/data_quality_runner.py` so that only `enforced: true` failures contribute to
the `FAIL`/`HARD_GATE` aggregate outcome. Failures on `enforced: false` checks appear
at `ADVISORY` severity in the output: visible but not blocking.

**`severity: warn` interaction:** `enforced` is only relevant for `severity: error`
checks. `severity: warn` checks are always advisory regardless of their `enforced`
value. If a `severity: warn` check has `enforced: true`, the compiler must not treat
it as blocking. This also means: `severity: warn` checks do not require `enforced`
annotation during Phase 3 Step 3. Skip them.

### Step 3: YAML annotation

**Prerequisite: Steps 1 and 2 must be merged before beginning this step.** Once the
runner infrastructure is in place, run the DQ runner to obtain the current per-check
verdict list for both YAML files:

```
.venv/Scripts/python.exe -m scripts.data_quality_runner
```

Run without `--file` to cover both `ops.yaml` and `telemetry.yaml` in a single
invocation (or run once per file with `--file config/agent/data_quality/ops.yaml` then
`--file config/agent/data_quality/telemetry.yaml`). Inspect `logs/debug/dq-latest.json` and
examine the `checks` array. Annotate every `severity: error` check:

- `"verdict": "FAIL"` -> `enforced: false`
- `"verdict": "PASS"` -> `enforced: true`

No `severity: error` check is left without an explicit `enforced` field after this step.

**Schema by test form:**

*Dict-form column tests (e.g., `accepted_values`, `relationships`, `not_null` in dict
form) - `enforced` is a sibling of existing params:*
```yaml
columns:
  status:
    tests:
      - accepted_values:
          values: [open, closed, failed, declined, superseded]
          enforced: false  # data condition known bad - see rec-XXX
      - not_null:
          enforced: true
```

*Bare-string column tests (`- not_null`, `- unique`) that are currently `"PASS"` do not
require conversion - leave as bare strings; the loader defaults them to `enforced: true`.
Bare-string tests that are `"FAIL"` must be converted to dict form to receive
`enforced: false`:*
```yaml
columns:
  id:
    tests:
      - not_null           # bare string; loader treats as enforced: true
      - unique:
          enforced: false  # converted from bare string; current duplicates in data
```

*Table-level checks (`row_count`, `recency`) - `enforced` is a sibling of the
threshold params:*
```yaml
row_count:
  min: 1
  max: 10000000
  enforced: false  # row count anomaly; tracked rec-XXX
recency:
  column: last_updated_timestamp
  error_after_hours: 72
  enforced: true
```

**Handling SSO-unavailable:** If AWS credentials are unavailable, the runner cannot
execute queries and the `checks` array will not be produced. Defaulting all checks to
`enforced: false` in this scenario does NOT achieve Phase 3's safety goal: with all
checks unenforced, the broad `covers` list remains unsafe and the executor cannot be
re-enabled. Phase 3 is only complete when checks provably passing in a live DQ run are
graduated to `enforced: true`. The Phase 3 PR must not be merged until at least the
`ops_recommendations` checks verified clean by PR #285 are graduated to `enforced: true`
based on a live DQ run. If SSO is unavailable, Phase 3 can be scaffolded but not
completed.

### Step 4: Graduation guard in validate.py

`scripts/validate.py` gains a guard that reads the current YAML diff and the most
recent `logs/debug/dq-latest.json`. It rejects any diff that:

1. Flips a check from `enforced: false` to `enforced: true`, AND that check's
   `(table, column, test)` tuple has `verdict != "PASS"` in the `checks` array.
2. Adds a new check directly as `enforced: true` when that check's tuple has
   `verdict != "PASS"` in the `checks` array.

**Diff strategy:** Read YAML changes using `git diff HEAD -- config/agent/data_quality/`. This
covers both staged and unstaged changes against the last commit, ensuring the guard fires
regardless of whether the developer has staged the YAML edits.

**`SKIP` verdicts:** A `SKIP` verdict in `dq-latest.json` (produced by dry-run mode) is
inconclusive and must not allow graduation. Only `"PASS"` permits graduation.

**`--quick` bypass:** The graduation guard fires only on the default presubmit tier.
Running `validate.py --quick` skips it entirely. Document this in the guard's warning
output so developers know that `--quick` does not validate `enforced` flips.

**Missing or stale `dq-latest.json`:** If the file is missing or lacks a `checks` array
(pre-Step-1 state), the guard emits a warning but does not block. If the file is present
but stale (>1h), `DataQualityVerifier` already returns `FAIL, HARD_GATE`, which blocks
before the graduation guard is reached.

### Files in scope

| File | Change |
|------|--------|
| scripts/data_quality_runner.py | Add `enforced: bool = True` to `Check` dataclass; update `load_checks` and `_compile_column_test` branches to read `enforced`; extend `_save_latest_result` to write `checks` array; add `enforced`-aware verdict logic to `run_checks` aggregation |
| config/agent/data_quality/ops.yaml | Add `enforced: false/true` to all `severity: error` checks |
| config/agent/data_quality/telemetry.yaml | Add `enforced: false/true` to all `severity: error` checks |
| scripts/validate.py | Add graduation guard |
| scripts/verifiers/data_quality.py | Change missing-file return from `SKIPPED, ADVISORY` to `FAIL, HARD_GATE` (closes Known Gap) |
| docs/DECISIONS.md | File the "No separate DQ scheduled routine" decision (Session E elimination) |
| tests/ | Tests per specification below |

**Minimum test specification:**

1. `_save_latest_result` writes `checks` array with fields `table`, `column` (null for
   table-level), `test`, `verdict`. Schema matches `_print_results --json` output.
2. YAML parser reads `enforced` from dict-form tests; defaults to `True` for bare-string
   tests and any check with the field absent.
3. `enforced: false` failures appear as ADVISORY, not FAIL, in the aggregate verdict.
   `enforced: true` failures appear as FAIL. `severity: warn` checks remain advisory
   regardless of `enforced` value.
4. Graduation guard: blocks flip from `enforced: false` to `enforced: true` when the
   check's verdict in `dq-latest.json` is `FAIL`. Allows flip when `PASS`. Warns but
   does not block when `dq-latest.json` is missing or has no `checks` array. Does not
   block when verdict is `SKIP`.
5. New check added directly as `enforced: true` is blocked by the guard when verdict
   is FAIL.
6. Running `validate.py --quick` does not invoke the graduation guard.

---

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
- `config/agent/data_quality/ops.yaml` (field contract authority; description + semantics per column)
- `config/agent/data_quality/decisions/{table}.yaml` (decision manifest for the target table)
- `.venv/Scripts/python.exe -m scripts.data_quality_runner` output (if SSO available)

Do NOT load: `docs/dq/ops-recommendations-remediation-briefing.md` (legacy artefact;
superseded by ops.yaml extended contract per DQ_REMEDIATION_METHODOLOGY.md step b2 and
Decision 65). Do not load out-of-scope INTENT docs (INTENT-verification-system.md,
INTENT-validation-architecture.md) unless the session explicitly touches those systems.

### Graduation Retrospective: ops_recommendations

Five event clusters shaped the remediation path for `ops_recommendations`, discovered in
the order below. Each cluster has source PRs documenting the specific issues and solutions.
Future agents starting Phase 4 on `ops_decisions` or other tables should expect similar
discovery patterns and should review these events before planning their session.

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

### Bootstrapping Causal Chain

The table is append-only Iceberg. `sync_ops._rebuild_local_cache()` re-materialises
every Iceberg row into the local JSONL cache on each pull. Records still present in the
base table reappear after every sync.

#### Lifecycle state transition (close or abandon a recommendation)

`update_rec(id, {"status": "superseded"})` or `"declined"` marks a record's business
state. The record remains in the SCD2 base table and `_current` view with its new
status. Use this for recommendations that are closed, abandoned, or superseded by newer
work. `dq_tombstones.yaml` HARD_GATE detects resurrection events when a record that
should stay closed reappears in `_current` -- it does not prevent them; it alerts.

#### Physical deletion protocol (destroy a bootstrap or invalid record)

Use this only when `update_rec` is not viable -- e.g., records with empty or null
`status` that would fail Pydantic `Literal` validation in `update_rec`, or records
injected via the now-closed `append_jsonl -> s3_log_store` path that bypassed ID
allocation entirely. Three steps are required for complete physical removal:

1. `DELETE FROM trading_formulas_db.ops_recommendations WHERE <predicate>`
   - `WHERE id = ''` does NOT match `id IS NULL`. Use
     `WHERE id = '' OR id IS NULL` when targeting missing IDs.
2. `OPTIMIZE trading_formulas_db.ops_recommendations REWRITE DATA USING BIN_PACK`
   - Rewrites S3 data files to remove deleted row bytes. Skipping this step leaves the
     row bytes on S3 even though queries no longer return them.
3. `VACUUM trading_formulas_db.ops_recommendations`
   - Removes unreferenced snapshot and manifest files from S3.

All three steps are required. After completion, remove the corresponding tombstone
entry from `dq_tombstones.yaml` -- physical deletion is the stronger guarantee.

### RCA-Before-Action Constraint

Never correct or delete data without first assigning a root cause class (A/B/C/D per
`docs/dq/DQ_REMEDIATION_METHODOLOGY.md`). This RCA-before-action rule prevents incorrect
remediation paths and avoids repeating the conditions that produced the bootstrap cohort.
Every data action in Phase 4 must have a corresponding decision manifest entry with an
approved root cause.

### Session Map -- ops_recommendations

State drift note: run the DQ runner at the start of each wave session to verify current
verdicts. PRs #301-304 have graduated several checks since the decision manifest was
authored (2026-05-06). The phase4_session field in the manifest provides the routing;
the DQ runner provides current verdicts.

| Wave | Session slug | Fields | Status | Prerequisite |
|------|-------------|--------|--------|-------------|
| 1 | wave-1 | source, source_registry.yaml | COMPLETE (PR #309) | wave-3 |
| 2 | wave-2 | file, context, acceptance, automatable (formula) | COMPLETE (PR #319) (4 checks graduated 2026-05-11; write_time metadata template in ops.yaml) | wave-1 complete |
| 3 | wave-3 | status (dec-XXX deletion), risk (verify backfill) | COMPLETE (PR #307) | None |
| 4 | wave-4-deferred | execution_result, execution_date, execution_branch, execution_pr_url, execution_steps | DEFERRED | Telemetry maturity (Decision 63) |
| 5 | wave-5-deferred | id, title, effort, priority, created_timestamp (temporal gates) | DEFERRED (exclude_before: '2026-05-01' temporal gates deployed PR #299; pending formal session tracking) | exclude_before runner support |

**Recommendation: start with Wave 3.** The dec-XXX status corruption records are the
root cause of the 35-record null cohort in source/effort/priority. Waves 1 and 2 will
partially self-resolve after Wave 3 cleanup. Wave 3 has no prerequisites.

### Session Map -- other ops tables

After all non-deferred waves for ops_recommendations are complete:

| Table | Est. sessions | Prerequisites not yet met | Known blockers |
|-------|--------------|--------------------------|----------------|
| `ops_decisions` | -- | Scoped under `docs/INTENT-ops-decisions-graduation.md` (separate graduation arc covering portal-first migration plus DECISIONS.md decommission). Returns to this map only if that arc is abandoned. | Tracked under that arc's Phase 4 (Data Correction) and Phase 5 (DQ Graduation). |
| `ops_execution_plans` | 1 | Gate 1 (rec-609 array FK blocks `relationships` check for `rec_id`), Gate 2 (no manifest) | `plan_id` nulls and duplicates; `rec_id` FK relationship check blocked on rec-609 |
| `ops_priority_queue` | 1 | Gate 2 (no manifest) | Nulls across `queue_run_id`, `rank`, `rec_id`, `mode`; recency beyond error threshold (`enforced: false`) |
| `ops_session_log` | 1 | Gate 2 (no manifest) | Nulls in `session_id` and `session_type`; `session_id` duplicates (SCD2 behaviour expected) |
| Telemetry tables (7) | 1 per table | Gate 1 (`telemetry_agent_invocations_current` view stale -- column count mismatch confirmed 2026-05-12), Gate 2 (no manifests), Decision 67 block | Deferred until executor restoration and telemetry maturity. Do not begin until Decision 67 is reversed |

For `ops_decisions` through `ops_session_log`: Gate 3 (write gate verification) is
satisfied -- all four tables share the `ops_data_portal` write surface, and the bypass
audit was completed for `ops_recommendations`. Re-run the bypass audit grep before the
first session on each table to confirm no table-specific write path was added since
the original audit.

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
grep -n "enforced: false" config/agent/data_quality/ops.yaml config/agent/data_quality/telemetry.yaml | grep -v "#"
```

Zero lines means every `enforced: false` line has an inline comment. The comment must
be on the same line as `enforced: false` (inline comment). A comment on the next line
is not detected by this grep. The only valid form is: `enforced: false  # reason`.

### Final Completion Condition for Phase 5 Entry

Phase 5 entry requires every check to be `enforced: true` -- no `enforced: false` entries
at all, commented or otherwise. Verify with:

```
grep -n "enforced: false" config/agent/data_quality/ops.yaml config/agent/data_quality/telemetry.yaml
```

Zero lines (all `enforced: false` removed, including any with inline comments) = Phase 4
complete, Phase 5 can begin.

---

## Phase 5: Convergence

**Status:** NOT_STARTED
**Plan:** (fill in)
**PR:** (fill in)

**Prerequisite:** Phase 4 final completion condition met (zero `enforced: false` at all,
per the unfiltered grep above).

### Stale-FAIL reversion

When `INTENT-validation-architecture.md` migration sequence Step 3 (Stand up the EC2
self-hosted runner with SSO substrate) has landed, the stale path in
`scripts/verifiers/data_quality.py` reverts from `FAIL, HARD_GATE` back to
`SKIPPED, ADVISORY` - matching its pre-Phase 2 behaviour. At that point, the presubmit
tier on the self-hosted runner refreshes `dq-latest.json` on every CI run; staleness
between runs is expected and the gate trusts freshness. This reversion is a one-line
change in the verifier.

### Deletion of the `enforced` field

Before deletion, verify the pre-condition:
```
grep -rn "enforced: false" config/agent/data_quality/
```
Must return zero results. Then delete:

- All `enforced: true/false` entries from both YAML files
- `enforced`-field compiler logic from the `run_checks` verdict aggregation path in
  `scripts/data_quality_runner.py`
- `checks` array write from `_save_latest_result` in `scripts/data_quality_runner.py`
- `enforced: bool = True` field from the `Check` dataclass
- `enforced` reading logic from `load_checks` and all `_compile_column_test` branches
- Graduation guard from `scripts/validate.py`
- Tests added in Phase 3: graduation guard tests, ADVISORY-vs-FAIL split tests, SKIP
  verdict inconclusive tests

From this moment the invariant holds: if a check is in the YAML, it gates.

### Covers addition

Add `scripts/verifiers/data_quality.py` to `DataQualityVerifier.covers` in
`scripts/verifiers/data_quality.py`. Changes to the verifier itself must trigger a DQ
gate check.

### Files in scope

| File | Change |
|------|--------|
| scripts/verifiers/data_quality.py | Revert stale-FAIL to SKIPPED/ADVISORY; add `scripts/verifiers/data_quality.py` to `covers` list |
| config/agent/data_quality/ops.yaml | Remove `enforced` field from all checks |
| config/agent/data_quality/telemetry.yaml | Remove `enforced` field from all checks |
| scripts/data_quality_runner.py | Remove `enforced` from `Check` dataclass; remove loader logic; remove verdict-aggregation filter in `run_checks`; remove `checks` array write from `_save_latest_result` |
| scripts/validate.py | Remove graduation guard |
| tests/ | Remove tests specific to `enforced` field: graduation guard tests, ADVISORY split tests, SKIP-inconclusive tests |

---

## Known Gaps

These are unresolved issues from Phase 2 that are not blocking current work but must
be noted to prevent future agents from assuming they are handled.

**Missing-file bypass:** `DataQualityVerifier` returns `SKIPPED, ADVISORY` when
`logs/debug/dq-latest.json` does not exist. This gap is closed in Phase 3: the
missing-file path will be changed to `FAIL, HARD_GATE` as part of Phase 3's files in
scope. After Phase 3 merges, deliberate file deletion no longer bypasses the gate.

---

## Decision Registry

Do not re-litigate any item marked `[DECIDED]`. If circumstances have genuinely
changed, record a new decision in `docs/DECISIONS.md` before overriding.

---

**[DECIDED] Convergence mechanism: `enforced` ratchet field**

Not snapshot baselines - they aggregate away per-check granularity and cannot
distinguish "data is broken in N ways" from "check is wrong in N ways." Not feature
flags - they are environment-based, not data-condition-based. The ratchet is per-check,
explicit in git history as single-line diffs, and has a committed deletion event.

**[DECIDED] `enforced` field is transitional and must be deleted**

When the last check graduates, the field is deleted from the schema and the compiler.
This is non-negotiable. Leaving the field as permanent infrastructure re-creates the
decoupling the arc was designed to eliminate.

**[DECIDED] Stale-DQ policy: FAIL HARD_GATE as a transitional state**

Staleness (>1h) returns `FAIL, HARD_GATE` from `DataQualityVerifier` (landed in
Phase 2, PR #286). This reverts to `SKIPPED, ADVISORY` once `INTENT-validation-architecture.md`
migration sequence Step 3 lands and the presubmit tier guarantees freshness on every CI run.

**[DECIDED] DataQualityVerifier covers: broad from Phase 2, with Phase 5 addition**

Phase 2 deployed `covers = ["config/agent/data_quality/**", "scripts/data_quality_runner.py",
"scripts/ops_data_portal.py", "src/data/**"]`. Phase 5 will add
`scripts/verifiers/data_quality.py` to this list (changes to the verifier itself should
trigger a DQ gate check). No intermediate narrow list was ever active. Phase 3 makes
the broad list safe via the ratchet.

**[DECIDED] No separate DQ scheduled routine**

The original Session E architecture (Claude Code cron -> EC2 runner -> dq-latest.json
PR -> auto-merge) is eliminated. DQ runs as part of `validate.py`'s presubmit tier on
the EC2 self-hosted runner, which has SSO credentials. The presubmit tier auto-invokes
the DQ runner when `dq-latest.json` is stale. No scheduling concern separate from
validation itself. This decision is a Phase 3 deliverable: the Phase 3 PR must include
an entry in `docs/DECISIONS.md` for Session E elimination to prevent future agents from
reviving that architecture from the superseded plan.

**[DECIDED] Phase 4 blocks Phase 5**

No Phase 5 work while any `enforced: false` check exists - commented or uncommented.
The final completion condition is mechanically verifiable via the unfiltered grep in
Phase 4. There is no code gate enforcing this in `validate.py`; it is a process
constraint enforced by this document and human review.

**[DECIDED] EC2 self-hosted runner: t3.small, eu-west-2**

For the substrate referenced by `INTENT-validation-architecture.md` migration
sequence Step 3.

---

## Agent Instructions

**Before scoping any DQ enforcement work:**

1. Read this document in full.
2. Find the first phase with `Status: NOT_STARTED`. That is the current work frontier.
3. If a phase is `IN_PROGRESS`, read its Plan file before adding to its scope.
4. Check all prerequisites for the target phase before planning.

**When a phase's PR merges, update this document:**

Create a branch (e.g., `chore/dq-status-phase-N`), edit the Phase Overview table and
the phase's own `Status` and `PR` fields in-place, and open a PR. Do not commit
directly to `main` - the `never_on_main` hook will block it.

**Do not:**

- Re-litigate any `[DECIDED]` item above.
- Start Phase 5 while any `enforced: false` check exists - commented or uncommented
  (use the Phase 4 final completion grep to verify).
- Graduate a check to `enforced: true` without verifying it passes in a fresh live DQ
  run (the graduation guard in `validate.py` enforces this mechanically after Phase 3).
- Add a new DQ check directly as `enforced: true` without verifying it first passes.
- File atomic recommendations as a substitute for this document's phase structure
  when the executor is unavailable.
- Run `validate.py --quick` as a substitute for the presubmit tier when checking
  `enforced` flips - `--quick` does not invoke the graduation guard.

**If adding a new DQ check to either YAML file before Phase 3 lands:**

Add `enforced: false` explicitly. The graduation guard does not yet exist; the
constraint is manual. Graduate to `enforced: true` only after the check passes a fresh
live DQ run.

**If adding a new DQ check after Phase 3 lands:**

Add `enforced: false` explicitly. The graduation guard will block graduation until the
check passes a live DQ run. Bare-string tests with no `enforced` field default to
`enforced: true` via the loader - if the check is not yet verified, use dict form.

---

## What This Document Does Not Cover

- EC2 self-hosted runner stand-up (`INTENT-validation-architecture.md`)
- The `validate.py` two-tier flag consolidation (`INTENT-validation-architecture.md`)
- The verifier harness and causal chain verifiers (`INTENT-verification-system.md`)
- The `ops_recommendations_current` view `_rn` ambiguity fix (separate recommendation)
- Column-by-column data backfill strategy - each table is its own Phase 4 session

---

**Last updated:** 2026-05-11
**Planning session:** 44a33e18-d937-4db9-8fec-89659d17a807
