# Plan

## Intent

Audit the data quality enforcement system as it applies to `ops_recommendations`, document its three enforcement layers,
identify gaps that prevent the stated "hard fail" intent from holding, and record the architectural commitments
(intentional decoupling, convergence target, ratchet design) that will guide future work toward a state where
"definition equals enforcement" for all 12 Iceberg tables.

## Plan Type

REPORT-ONLY

## Verification Tier

V1

## Branch

agent/audit-ops-recs-dq-scalability

## Phase

Phase Platform - verification system maturation (parallel to Phase 2 schema backfill).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| docs/plans/PLAN-audit-ops-recs-dq-scalability.md | Create | The audit report itself - this document IS the deliverable. |

## Bundled Recommendations

None. Soft keyword matches in the priority queue (rec-389, rec-549) are orthogonal and were not bundled.

## Acceptance Criteria

- [ ] Report contains a complete inventory of the three enforcement layers for `ops_recommendations`
      (write-side Pydantic, read-side Athena DQ, postflight verifier gate).
- [ ] Report contains a scalability assessment that distinguishes the definition layer (mature),
      compilation layer (mature), and enforcement layer (partial).
- [ ] Report contains an "Intentional Decoupling" section explaining why definition and enforcement
      are deliberately decoupled today, citing the data-condition argument.
- [ ] Report contains a "Convergence Target" section with the proposed `enforced` ratchet, the graduation
      guard, and the explicit commitment to delete the `enforced` field once all checks have graduated.
- [ ] Report contains all six identified enforcement gaps with severity ratings and one-line remediation summaries.
- [ ] Report contains a "Future Direction" section recording the user's intent to migrate validation locally
      and the architect's recommendation to evaluate self-hosted-runner before custom gating.
- [ ] Report contains a candidate-recommendations table with priority and effort for each gap and the
      ratchet adoption work.
- [ ] Human has read the report and chosen which findings to file as recommendations via `ops_data_portal.py`.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | report | Confirm all required headings exist | `grep -c -E "^## (Inventory\|Scalability Assessment\|Intentional Decoupling \(Current State\)\|Convergence Target \(End State\)\|Identified Gaps\|Future Direction\|Candidate Recommendations)" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `7` | Add the missing heading |
| 2 | report | Confirm gap count | `grep -c -E "^### Gap [1-6]:" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `6` | Add the missing gap or renumber |
| 3 | report | Confirm severity rating present on every gap | `grep -c -E "^\\*\\*Severity:\\*\\* (Critical\|High\|Medium\|Low)" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `6` (one per gap) | Add the missing rating |
| 4 | report | Confirm candidate recs table contains 7 rows (6 gaps + 1 ratchet) | `grep -c -E "^\| rec-CANDIDATE-" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `7` | Add the missing row |
| 5 | report | Confirm the ratchet-deletion commitment is recorded verbatim | `grep -c "delete the \`enforced\` field" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns `>= 1` | Restore the commitment line |

## Constraints

- This plan is REPORT-ONLY. No code, configuration, or schema changes are made by the plan or its execution.
- The proposed `enforced` ratchet design is a *proposal* in this report. Adopting it requires a separate
  implementation plan (sized for the column-by-column triage workstream it enables).
- Column-by-column data triage of historical records is explicitly out of scope. Each column is its own
  judgement-call session and will be planned separately.
- The CI/CD migration to local-only validation (and the alternative of self-hosted GitHub Actions runner)
  is explicitly out of scope. Recorded only as Future Direction.
- No rescue agents or workaround loops (Decision 55).

## Context

- Authoritative architecture: `docs/INTENT-verification-system.md` (defines Layer 1/2/3 quality pyramid;
  this audit operates at Layer 2).
- Recent landings that established the current state:
  - PR #267 - Initial portal write gateway (`scripts/ops_data_portal.py`).
  - PR #274 - Programmatic verifier harness and V3 hard gates.
  - PR #275 - Migrate ops data infrastructure to portal.
  - PR #276 - Verifier harness and registry orchestration.
  - 674c842 - DQ framework scaffold and preflight integration.
  - PR #278 - Postflight hard gate (wires harness into postflight; adds `DataQualityVerifier`,
    `OutboxHealthVerifier`, `SchemaIntegrityVerifier`, `CausalChainVerifier`).
  - PR #279 - Hardened recommendation schema (Pydantic v2 with `extra="forbid"`).
- Decision 48 (Verification Tier Design): V1=static, V2=unit, V3=integration.
- Decision 51 (Local-First Outbox + Bidirectional Sync): writes are local-first; sync is bidirectional.
- Decision 55: No rescue agents. Failures must be diagnosed and fixed at root cause.
- Single Portal Invariant: all writes to `logs/.recommendations-log.jsonl` and `logs/.decisions-index.jsonl`
  go through `scripts/ops_data_portal.py`. Direct file edits fail `validate.py`.
- Recommendations log schema (CLAUDE.md / docs/PROJECT_CONTEXT.md): canonical 17-field schema with strict
  enum domains for `source`, `effort`, `priority`, `status`, `risk`, `verification_tier`.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (this plan is on `agent/audit-ops-recs-dq-scalability`).
- [x] docs/PROJECT_CONTEXT.md read.
- [x] docs/DECISIONS.md decisions referenced (48, 51, 55).
- [x] All files in Scope table located and readable.
- [x] Acceptance Criteria understood and verifiable via the Verification Plan commands.

## Ordered Execution Steps

1. Read this report end-to-end.
2. Identify which gaps and which recommendations from the Candidate Recommendations table you want to file.
3. For each chosen item, file a recommendation via `python -m scripts.ops_data_portal --file-rec ...`.
   The candidate rows include suggested title, priority, effort, file, and context fields.
4. Decide whether to commit to the proposed `enforced` ratchet design as the convergence path.
   If yes, file rec-CANDIDATE-RATCHET as a STRATEGIC plan.
5. **Execute Verification Plan** - run each VP step. All five must pass before this plan is considered complete.

---

## Inventory

This section documents *what is enforced today* for `ops_recommendations`. The system has three independent
enforcement layers; each catches a different class of failure.

### Layer 1: Write-side - `scripts/executor/jsonl_store.py:22` (Pydantic v2)

The `Recommendation` BaseModel is the gate for every write that flows through `scripts/ops_data_portal.py`.

- `model_config = ConfigDict(extra="forbid")` - any unknown field on a write raises `ValidationError`.
- `id` field validator: must start with `rec-`, `agent-`, or `test-`. Legacy `dec-` IDs are forbidden.
- `date` field validator: strict `YYYY-MM-DD`; any other format raises `ValueError`.
- Required fields at the model level: `id`, `status`. All others are `Optional`.
- `_VALID_STATUSES = {"open", "closed", "failed", "declined", "superseded"}` enforced at update time
  in `update_recommendation()` before `model_validate` runs.
- Ingress paths are constrained: all writes route through `scripts/ops_data_portal.py`. Direct
  `Edit`/`Write` to `logs/.recommendations-log.jsonl` is caught by `validate.py` per the Single Portal
  Invariant.

Coverage assessment: write-side is **strict for Recommendations**. No equivalent Pydantic model exists for
`Decision`, `ExecutionPlan`, `SessionLog`, `PriorityQueue`, or any of the seven telemetry tables.
Carrying this layer to the other 11 tables is a per-model porting task, sized small per table but eleven
tables wide.

### Layer 2: Read-side - `config/data_quality/ops.yaml` and `scripts/data_quality_runner.py`

The dbt-style declarative DQ system compiles YAML check definitions into Athena SQL. For
`ops_recommendations` (queried via the `_current` view to dedupe SCD2 versions):

| Check type | Column(s) | Severity | Rationale |
|------------|-----------|----------|-----------|
| `row_count` >= 1 | (table) | error | Catches a fully-empty `ops_recommendations`. |
| `not_null` | id | error | Identity invariant. |
| `not_null` | date | error | Required by schema. |
| `not_null` | title | error | Required by schema. |
| `not_null` | source | error | Required by schema. |
| `accepted_values` | source | warn | Enum may grow (new sources accepted). |
| `not_null` | effort | error | Required by schema. |
| `accepted_values` | effort | error | Strict {XS, S, M, L, XL}. |
| `not_null` | priority | error | Required by schema. |
| `accepted_values` | priority | error | Strict {Critical, High, Medium, Low}. |
| `not_null` | status | error | Required by schema. |
| `accepted_values` | status | error | Strict {open, closed, failed, declined, superseded}. |
| `not_null` | automatable | error | Boolean must be set. |
| `not_null` | risk | error | Required by schema. |
| `accepted_values` | risk | error | Strict {low, medium, high}. |
| `not_null` | trade_date | error | Athena partition column. |
| `not_null` | ingested_at | error | Athena audit column. |

Total: ~17 checks for `ops_recommendations` alone. Across the full ops file: ~50 checks across 5 tables.
Across the full repository: 130 checks across 12 tables (per preflight `data_quality.checks_defined`).

The runner supports seven test types (`not_null`, `unique`, `accepted_values`, `relationships`, `row_count`,
`recency`, `expression`). Severity model is binary at the postflight gate level: `error` -> FAIL,
`warn` -> WARN.

Coverage assessment: definition layer is **mature and uniform**. Compilation layer (`data_quality_runner.py`)
is **generic** - new YAML files dropped into `config/data_quality/` are auto-discovered via
`_DQ_DIR.glob("*.yaml")` and adding a new test type is one branch in `_compile_column_test()`.

### Layer 3: Postflight gate - `scripts/executor/postflight.py:969`

`_run_verifiers_gate()` is the executor's merge gate. It calls `run_all_verifiers()` (registry
auto-discovers everything in `scripts/verifiers/`), iterates results, and decides whether to block the
merge.

Block conditions, all required:

1. The plan's verification tier is V3.
2. At least one verifier returned `VerifierStatus.FAIL`.
3. That failing verifier has `severity == VerifierSeverity.HARD_GATE`.

The DQ-specific verifier (`scripts/verifiers/data_quality.py`) reads `logs/debug/dq-latest.json`:

- File missing -> SKIPPED, ADVISORY (does not block).
- File present but >1h old -> SKIPPED, ADVISORY (does not block).
- File present, fresh, `verdict == "PASS"` -> PASS.
- File present, fresh, `verdict != "PASS"` -> FAIL, HARD_GATE.

Coverage assessment: gate layer is **wired but narrow** - only blocks for V3 plans. V1 and V2 plans
bypass the gate entirely. Plus, the gate exists only for *executor* merges; human `/implement` -> PR -> merge
sessions never invoke the harness.

---

## Scalability Assessment

The framework is decomposable into three sub-systems with very different scalability stories. Carrying
the same protections to the other 11 tables is *not* one workstream - it is three, each with different
shape.

### Sub-system A: Definition layer - SCALABLE TODAY

- New tables are added by appending YAML stanzas. The compiler does not need changes.
- All 12 Iceberg tables already have at least skeletal coverage in `ops.yaml` or `telemetry.yaml`.
- Adding new check types (e.g., `range`, `regex`) is a single function in `_compile_column_test()`.

What "scaling to all 12 tables" requires here: review the existing YAML coverage for completeness
(some tables have only `row_count` and `ingested_at` not_null) and beef up where weak. Effort: per
table, XS-S; total across 11 tables, M.

### Sub-system B: Compilation/execution layer - SCALABLE TODAY

- `scripts/data_quality_runner.py` is generic. It does not encode anything table-specific.
- Result emission (`logs/debug/dq-latest.json`) is uniform across tables.
- Filter flags (`--table`, `--file`, `--severity`) compose cleanly.

What scaling requires here: nothing structurally. One known fix needed (see Gap 1 below) but not a
scaling concern.

### Sub-system C: Enforcement layer - LAGGING, INTENTIONALLY

- Only one of three planned integration points (per `INTENT-verification-system.md`) is wired:
  postflight harness call. The other two (`validate.py --integration` and scheduled health checks) are
  not yet implemented.
- The wired one is V3-only. So even when DQ runs, only autonomous V3 executor runs are gated.
- No equivalent Pydantic model exists for the other 4 ops tables or any of the 7 telemetry tables.

What scaling requires here: see Convergence Target. The path is column-by-column data triage to bring
each table's data condition up to the strictness of the YAML checks, then graduate that table's checks
to enforced. This is a multi-month workstream by design.

---

## Intentional Decoupling (Current State)

The definition and enforcement layers are *deliberately* decoupled today. This is a load-bearing
architectural choice, not a defect. Future readers and future agents must not file recommendations to
"close the gap" by wiring enforcement up to definition immediately - doing so would block all merges
indefinitely until the underlying data is repaired.

### Why decoupling is intentional

`ops_recommendations` is the most-curated table in the system. Even there, the data is broadly correct
because it is curated by humans and agents using the strict Pydantic write gate. The other 11 tables
have not received that level of curation. The known issues (per the human's own description) include:

- **Type drift.** Fields that should be dates are currently captured as strings.
- **Coverage gaps.** Some columns are not written at all by current writers.
- **Determinism gaps.** Some columns are populated by LLM judgement when they should be deterministic.
- **Capture inconsistency.** The same logical field is captured from multiple writer paths and has
  different values depending on which writer ran.
- **Schema-vs-capture drift.** Schemas are broadly correct but may need tweaks once the writers and
  the captured semantics are reconciled.

If we flipped the YAML checks for these tables into enforced `error`-severity gates today, every merge
that touches anything connected to those write paths would fail. The system would be unbuildable.

### What "decoupled" does NOT mean

It does not mean the definitions are aspirational decoration. The runner does execute the checks
against Athena and records pass/fail to `logs/debug/dq-latest.json`. The data is *visible*. What is
suppressed is only the *gate consequence* of failures - the merge is not blocked.

This shape (definitions enforced visibly, gate consequences suppressed) is a valid transition state.
What it is not is an end state.

---

## Convergence Target (End State)

The end state is: **definition equals enforcement.** If a check exists in the YAML, it gates merges.
There is no separate enforcement step, no manual wiring, no flag to set.

To get there from here without breaking the system, the recommended ratchet is:

### Move 1: Add an `enforced` field to the YAML check schema

```yaml
columns:
  status:
    tests:
      - not_null
      - accepted_values:
          values: [open, closed, failed, declined, superseded]
          enforced: true   # graduates this check to gate consequence
```

Default is `false`. The runner reports violations on every check regardless. The postflight gate (and
any future `validate.py --integration` invocation) only fails on `enforced: true` violations.

A check graduates from `enforced: false` to `enforced: true` exactly when its column has been triaged
column-by-column to a clean state. Graduation is a single-line YAML diff per check, traceable in git
history, reviewable in a PR.

### Move 2: Add a graduation guard to `validate.py`

Reject any PR that flips `enforced: true` for a check that has FAILs in the most recent
`logs/debug/dq-latest.json`. The graduation must be earned (the data must already pass) before the
flag flip is allowed.

This is the policy-as-code guard. You cannot edit your way past your own ratchet.

### Move 3: Treat `enforced` as transitional infrastructure

On the day the *last* unenforced check graduates - across all 12 tables, every check `enforced: true` -
the field itself is removed from the YAML schema. The compiler stops reading it. From that moment,
the invariant becomes: *if a check is in the YAML, it gates*. There is no enforcement field because
definition is enforcement.

This is the part that matters. Without explicit deletion, the field becomes permanent infrastructure
and you have re-created the very decoupling you wanted to eliminate. The deletion event is the moment
the convergence is real.

### Optional Move 4: Graduation dashboard

A small reporter that surfaces per-table graduation rate
(e.g., `ops_recommendations: 17/17 enforced (100%)`, `telemetry_phases: 4/12 enforced (33%)`).
Preflight could surface it. Turns "I'll get to it" into a measurable trajectory and makes the ratchet
visible to future-you.

### Why this shape and not alternatives

- *Why not snapshot baselines?* Tools like ESLint use a "violations frozen at N; fail if it grows"
  approach. That works for warning-class tooling but not for hard-fail data quality, because a
  baseline cannot distinguish "data is broken in N ways" from "data is OK and check is wrong in N
  ways." The ratchet flag is per-check and per-decision; baselines are aggregate and lose granularity.
- *Why not hand-port write-side Pydantic to all 11 tables first?* That would catch *new* writes but
  not historical data. The user's stated triage is column-by-column over historical state, not just
  forward-fix. The ratchet supports both directions.
- *Why not move enforcement under feature flags per environment?* Environments are not the issue -
  data condition is. Feature flags would let you enforce in `company-aws-profile-production` and not
  `company-aws-profile`, but the data lives in the same Iceberg tables.

---

## Identified Gaps

The following six gaps were identified during the audit. Each is rated for severity, and one-line
remediation summaries are given. Filing recommendations is left to the human via the Candidate
Recommendations table at the end of this report.

### Gap 1: Empty PASS is indistinguishable from real PASS

**Severity:** Critical

**Evidence:** The current `logs/debug/dq-latest.json` contains:
```json
{ "verdict": "PASS", "total": 0, "passed": 0, "failed": 0, "warned": 0, "errored": 0,
  "duration_seconds": 0.0, "timestamp": "2026-05-04T13:17:59.040945+00:00" }
```
The most recent run executed zero checks. The verifier (`scripts/verifiers/data_quality.py`) reads
`verdict == "PASS"` and reports PASS to the harness. The empty-no-op outcome is identical to a real
clean run from the gate's perspective.

**Why it matters:** Regression detection is currently disabled and the system cannot tell. Any code path
that breaks every check would still pass through the gate.

**Remediation summary:** The runner should refuse to write `verdict: "PASS"` when `total == 0`. The
verifier should fail closed when `total == 0` (treat as ERROR, not PASS). Both ends of the chain need
to harden.

### Gap 2: DQ runner is not in `validate.py` or any GitHub Actions workflow

**Severity:** High

**Evidence:** `grep data_quality scripts/validate.py` returns nothing. `grep -r data_quality
.github/workflows/` returns nothing. The only call site of the runner is the postflight verifier
chain, executed only during autonomous executor runs.

**Why it matters:** Human `/implement` -> PR -> merge sessions do not run DQ at all. The hard fail you
intended fires only for autonomous V3 plans. The vast majority of merges (human implementation work)
bypass DQ entirely.

**Remediation summary:** Add `--integration` flag to `validate.py` per `INTENT-verification-system.md`
Wave 1 spec. Once stable, add a fast subset to CI workflow (or self-hosted runner per Future
Direction).

### Gap 3: Stale DQ result silently SKIPS rather than FAILing

**Severity:** High

**Evidence:** `scripts/verifiers/data_quality.py:55-62` - if `dq-latest.json` is older than 1 hour, the
verifier returns `SKIPPED, ADVISORY`. Combined with Gap 1 (no-op writes a stale-fresh PASS) and Gap 2
(no scheduled run), the gate has multiple silent-pass paths.

**Why it matters:** The gate fails open across multiple failure modes. Operationally, you can break
the runner, leave the system for a week, and never know.

**Remediation summary:** Decide a freshness policy. Options: (a) treat stale as FAIL HARD_GATE, forcing
runs to happen; (b) trigger a fresh run from the verifier itself; (c) require freshness to be ensured
by a scheduled health check (Wave 4b in INTENT spec). Option (c) is the cleanest if the scheduled
infra exists.

### Gap 4: No `recency` check on `ops_recommendations` (or any ops table)

**Severity:** Medium

**Evidence:** Only `telemetry_sessions` has a `recency` test in the YAMLs (48h warn, 168h error). All
five ops tables rely solely on `row_count >= 1` for liveness, which passes on stale data because old
rows persist.

**Why it matters:** If the portal silently stops writing to Iceberg (e.g., outbox drain fails for
days), `row_count >= 1` still passes. A recency check on `ingested_at` would catch this within hours.

**Remediation summary:** Add `recency` blocks to each ops table with appropriate thresholds. Suggest
24h warn / 168h error for `ops_recommendations` and `ops_decisions`; lower thresholds for
`ops_priority_queue` (curator runs daily).

### Gap 5: Verifier harness fails open

**Severity:** Medium

**Evidence:** `scripts/executor/postflight.py:1007-1009` - the harness call is wrapped in a broad
`except Exception` that logs a warning and returns `True` (allow merge). A bug inside any verifier
means the gate goes green.

**Why it matters:** "Verifier harness failed to run" is a worse outcome than "verifier reported FAIL"
- the former is invisible at the gate layer.

**Remediation summary:** Distinguish "harness threw" from "harness reported FAIL." The former should
emit a `verification_gate_error` process event with severity `error` and probably block (with an
override mechanism for known transient infra failures).

### Gap 6: V1 and V2 plans bypass DQ entirely

**Severity:** Medium (V2 portion); V1 portion deferred to CI/CD discussion

**Evidence:** `scripts/executor/postflight.py:998` - `if is_v3 and res.severity ==
VerifierSeverity.HARD_GATE`. The `is_v3` precondition means a V2 implementation that breaks an Iceberg
write path can merge while DQ is failing. V1 (docs/config) bypassing is plausibly intentional but
worth recording.

**Why it matters (V2):** A V2 plan that modifies any code touching the recommendation, telemetry, or
ops write path can land while data quality is broken. The V2/V3 boundary is a verification *strategy*
distinction, not a "do you write data" distinction. Many V2-classified plans do affect the data path.

**Remediation summary (V2):** Either drop the `is_v3` precondition (always run DQ as a hard gate when
the verifier reports FAIL) or refine the gating predicate to "does this plan's scope intersect any
file in any verifier's COVERS list" - a coverage-based test rather than a tier-based test.

**V1 disposition:** Deferred to the broader CI/CD discussion (Future Direction, below). A V1 plan
modifying e.g. `config/data_quality/ops.yaml` itself absolutely *should* trigger a DQ run. The
predicate refinement above (coverage-based) handles this naturally.

---

## Future Direction

This section records direction the human has stated as long-term intent, and the architect's
recommendation, *to prevent future agents from filing recommendations that pre-empt the discussion*.
This direction is **out of scope for the current audit** and out of scope for any plan derived from
the candidate recommendations below.

### Direction (human-stated): Migrate validation and verification to local-only

**Motivation:** GitHub Actions billed minutes are constrained (~2000/month). Validation runs are slow
enough that the cap is reached. The proposed migration: run all validation locally; the merge gate
in GitHub becomes "did the local validation pass."

### Architect's assessment

The proposed shape is structurally weak for three reasons, recorded in summary:

1. *Loses determinism.* Local environments carry cached state, env vars, and stale deps. Local
   validation passing while a clean checkout in CI fails is exactly the failure mode that
   `INTENT-verification-system.md` was written to prevent.
2. *Signalling problem.* GitHub branch protection requires a verifiable status check. "I ran the
   validator locally" is not verifiable. Workable proofs (signed manifests, custom webhooks) cost
   more engineering than they save.
3. *Discretion creep.* Even with a sole developer, removing the gate's external authority creates a
   path for tired-self overrides. INTENT-verification-system.md exists specifically to remove
   discretion from the verifier path.

### Architect's recommendation

Evaluate **self-hosted GitHub Actions runner** as a strictly cheaper, structurally equivalent
alternative *first*. A single binary registered against the repository, run on the dev machine,
zero billed minutes, all existing workflows unchanged, branch protection still functional. Reversible
in 30 seconds. This solves the cost problem without reintroducing the discretion problem.

If self-hosted runner is rejected for reasons not covered above, then the local-only path needs a
separate STRATEGIC plan that addresses the determinism, signalling, and discretion concerns explicitly
before any work begins.

---

## Future Direction (Validation Architecture)

The audit's "Future Direction" above records the *user-stated intent* (move validation local) and the
architect's recommendation (evaluate self-hosted runner first). Subsequent work has crystallised that
recommendation into an architectural anchor: `docs/INTENT-validation-architecture.md`.

That INTENT document defines the end-state for `validate.py` itself:

- A two-tier surface (presubmit default + `--quick` edit-loop), replacing the current four-flag world.
- An EC2 self-hosted GitHub Actions runner with SSO substrate as the substrate that makes the default
  tier cheap to run on every PR.
- Bounded execution constraints (presubmit <= 5 min, edit-loop <= 30 s, per-verifier <= 120 s).
- A migration sequence that is reversible step-by-step and ends with the deletion of the legacy flags.

**Sequencing.** The validation flag refactor and the EC2 runner stand-up are filed as separate
forward-looking recommendations, blocked on each other where appropriate:

- Stand up self-hosted GitHub Actions runner on EC2 with SSO substrate -- prerequisite.
- Consolidate validate.py flags to two-tier model -- blocked on the runner.
- Add scheduled postsubmit health checks -- Wave 4b of `INTENT-verification-system.md`, runs on the
  same substrate.

Filed alongside `PLAN-dq-validate-integration.md` (the plan that closes Gap 2 by wiring the DQ runner
auto-invoke into `validate.py --integration`). See `docs/INTENT-validation-architecture.md` for the
authoritative architecture; the rec IDs allocated by the portal are recorded in
`logs/.recommendations-log.jsonl` after that plan executes.

---

## Candidate Recommendations

To be filed via `python -m scripts.ops_data_portal --file-rec` if the human chooses. The IDs below are
placeholders (`rec-CANDIDATE-N`); real IDs are allocated by the portal at file time.

| ID | Title | Priority | Effort | File | Source | Brief context |
|----|-------|----------|--------|------|--------|----------------|
| rec-CANDIDATE-1 | Runner must refuse PASS when total==0; verifier must FAIL on empty result | Critical | S | scripts/data_quality_runner.py | planning | Gap 1: empty PASS is indistinguishable from real PASS today; this disables regression detection silently. |
| rec-CANDIDATE-2 | Add `--integration` flag to validate.py and wire DQ runner subset into CI | High | M | scripts/validate.py | planning | Gap 2: DQ only runs in postflight; human PR merges bypass it entirely. |
| rec-CANDIDATE-3 | Decide stale-DQ policy (fail closed, auto-rerun, or scheduled health check) | High | S | scripts/verifiers/data_quality.py | planning | Gap 3: stale `dq-latest.json` silently SKIPS rather than FAILs. |
| rec-CANDIDATE-4 | Add `recency` checks to all five ops tables in config/data_quality/ops.yaml | Medium | XS | config/data_quality/ops.yaml | planning | Gap 4: row_count passes on stale data; recency on `ingested_at` would catch silent write halts. |
| rec-CANDIDATE-5 | Distinguish harness-threw from verifier-reported-FAIL in postflight gate | Medium | S | scripts/executor/postflight.py | planning | Gap 5: harness fails open on any internal exception, masking real verifier failures. |
| rec-CANDIDATE-6 | Replace V3-only gate predicate with coverage-based predicate in postflight | Medium | M | scripts/executor/postflight.py | planning | Gap 6: V2 plans that modify data write paths currently bypass DQ. |
| rec-CANDIDATE-RATCHET | Adopt `enforced` field ratchet design for definition-equals-enforcement convergence | High | L | config/data_quality/ops.yaml | planning | Convergence Target: introduces `enforced: true|false` flag, graduation guard in validate.py, and explicit commitment to delete the field once all checks have graduated. STRATEGIC plan. |

The ratchet recommendation should be filed as STRATEGIC because it touches the YAML schema, the
runner, validate.py, and (eventually) the deletion event. Sequencing matters - graduation guard must
land before any check is graduated.

---

## Implementation Progress

### Session A - Gaps 1, 4, 5 (PLAN-dq-harden-gaps-1-4-5.md / agent/dq-harden-gaps-1-4-5)
- Gaps closed: Gap 1 (empty PASS), Gap 4 (recency checks), Gap 5 (harness fail-open)
- PR: [fill in PR number after merge]
- Status: COMPLETE

### Remaining stages
- **Session B** (PLAN-dq-gate-predicate.md): Gaps 3 + 6 -- stale DQ policy and
  coverage-based gate predicate.
- **Session C** (PLAN-dq-validate-integration.md): Gap 2 -- `validate.py --integration`
  flag and CI wiring.
- **Session D** (PLAN-dq-enforced-ratchet.md): RATCHET -- `enforced` field design,
  graduation guard in `validate.py`, deletion commitment. STRATEGIC plan.
