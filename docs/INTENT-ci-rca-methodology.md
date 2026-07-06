# INTENT: CI Root-Cause Analysis Methodology

## Status
Draft methodology contract. This document is the canonical specification for what the `ci-rca` scheduled agent must produce. Implementation is deferred to the follow-on plans listed in [Follow-on plans](#follow-on-plans).

**DuckLake retarget (Decision 84/81, 2026-06-15):** Sections 1, 3, and 7 were written against the pre-Decision-84 Iceberg/Athena surface. Decision 84 moved `ops_*` to DuckLake-on-Neon as the sole backend; the Iceberg ALTER TABLE, Athena `_current` views, and Athena `ops_ci_rca_telemetry` wording below is STALE. Implementation targets the live DuckLake closed reader/writer boundary. Stale passages are annotated inline.

**Phase-1 core slice (PLAN-ci-rca-schema-enforcement, landed 2026-06-15):** Shipped CI_RCA_STRICT_MODE flag (config/feature_flags.yaml), CiRcaContext Pydantic model, get_rec_write_guidance('ci_rca') write-time guidance, warn-mode file_rec() validation, context_v2_json column (field_semantics.yaml + production migration via maintenance Lambda), and reconcile_table_columns. Deferred to named follow-on plans: citation-existence lookup, evidence-bundle SHA-256 S3 verification, cross-check enforcement (earliest_viable_gate vs actual_gate), and Section 7 observability emission.

## Purpose
Define a **deterministic methodology contract** for `source=ci_rca` recommendations that structurally prevents the agent from filing rescue-style remediation in place of root-cause analysis. The contract combines:

1. A **mandatory structured context schema** enforced at portal write time
2. A **deterministic evidence-bundle script** (`scripts/ci_rca_evidence.py`) that pre-computes facts the LLM cannot dispute
3. A **cross-check rule** that adjudicates between the agent's narrative and the evidence bundle, with the bundle authoritative on disagreement

The contract preserves AI judgement for the *content* of each analytical field but eliminates the agent's ability to *skip* analytical fields. Rescue-mode output (proximate cause + remediation) is still required as `corrective_action` -- but it is structurally co-required with detection-gap analysis, why-chain, and preventive-action.

## Why this exists

### Architectural intent (Decision 72)
The `ci-rca` agent was specified by Decision 72 ("RCA-as-Plan-Source for CI Merge Gate Failures"). The decision text mandates that on CI failure the agent "reads the failed run logs ... identifies the root cause with evidence, and files a recommendation ... The agent does NOT propose or execute any autonomous fix. The rec is consumed via the standard `/plan` -> `/implement` flow."

The downstream consumer is `/plan`. `/plan` is a human-in-the-loop architectural review. For that review to be informed, the rec must surface *systemic* information -- not just the proximate failure and a tactical fix. The current methodology does not require this.

### The pattern this extends (Decision 66)
Decision 66 ("Precision Context Injection") established that field semantics must be surfaced to the agent at write time, not stored only in `ops.yaml`. The mechanism is `ops_data_portal.get_rec_write_guidance()`, which returns authoritative field semantics before the agent composes a value. The anti-pattern Decision 66 names is "structurally-valid but semantically-thin content from agents without prior context."

This INTENT extends Decision 66 to `source=ci_rca` specifically. Instead of `context` being a single free-text field whose semantics are advisory, it becomes a **structured object** with mandatory analytical sub-fields. The semantics are surfaced at write time AND enforced at file time.

### The tier vocabulary (Decision 60)
Decision 60 established a two-tier local validation architecture: `--pre` (edit-loop, 5-minute budget, offline-tolerant) and `presubmit` (default, full check suite). Decision 68 added the self-hosted CI runner, which executes the same `presubmit` tier remotely on a workflow event. This contract uses three enum values aligning with that vocabulary:

- `pre` -- `bin/venv-python -m scripts.validate --pre`, the local edit-loop tier
- `presubmit` -- `bin/venv-python -m scripts.validate` (no flags), the local pre-push tier
- `CI` -- the remote `presubmit` invocation triggered by GitHub Actions on the self-hosted runner

`presubmit` and `CI` execute the same validators but on different machines; the distinction matters because developers can skip `presubmit` whereas `CI` is the authoritative merge gate. There is no `IDE` or `manual_review` tier in the enum -- those layers have no current enforcement surface in this repo and including them produces dead enum branches that the bundle's deterministic computation cannot match.

### The observed gap
The current `ci-rca` agent definition at `.claude/agents/scheduled/ci-rca.md` defines a six-step methodology: fetch logs -> classify (5-category taxonomy: IAM gap / schema drift / dependency gap / environment / code regression) -> gather evidence (failing step, error message, resource identifiers) -> load field semantics -> file rec -> report.

This methodology is **diagnosis-shaped**, not RCA-shaped. It collects forensic facts about what happened. It does not require the agent to ask:

- Where in the gating ladder (`--pre` -> `presubmit` -> `CI`) was the earliest viable gate?
- Did that gate fire? If not, why not?
- Is the gate at the right tier, or is the tier-placement itself a defect?
- Is this an instance of a known anti-pattern, or novel?
- Does fixing the proximate cause prevent recurrence, or only restore service?

The five-category classification taxonomy also does not contain a category for "false negative in validate.py" (a check that exists but did not fire at the right tier). This is the exact failure mode of the case study below, and the agent had to coerce it into "code regression" -- a misclassification that propagated downstream.

## Case study: rec-859 / CI run 26286390667

### What happened
PR #354 (`feat(product-roadmap-schema)`) merged commit d02d36d which added `scripts/product_roadmap.py` at over 500 SLOC without a `# complexity-waiver: decision-43` header. CI run 26286390667 on the self-hosted runner caught the violation via `validate_sloc_limits()` in the full validation tier.

### What the ci-rca agent filed (rec-859 context, verbatim from `logs/.recommendations-log.jsonl`)
> CI run 26286390667 (PR #354, feat(product-roadmap-schema)) failed validate_sloc_limits() in scripts/validate.py: scripts/product_roadmap.py is 631 SLOC, exceeding the 500-SLOC hard limit enforced by Decision 43. The file has no complexity-waiver header. Root cause diagnosed by ci-rca run 26299337363 on branch agent/ci-rca-harness-fix. Two remediation paths: (1) add a complexity-waiver decision record and complexity-waiver header, or (2) refactor the module to split validation or schema logic into a submodule below 500 SLOC. This rec is manually filed because the runner IAM policy lacks dynamodb:PutItem, preventing ci-rca from filing directly (see rec-858).

### Apply the why-chain lens

| Layer | rec-859 | What RCA should have surfaced |
|---|---|---|
| What | `validate_sloc_limits()` failed; file is 631 SLOC | (same) |
| Why-1 | "exceeded the 500-SLOC hard limit" (restates the failure as cause) | "the file was added at over 500 SLOC in a single commit, no incremental waypoint forced earlier review" |
| Why-2 | (absent) | "no incremental SLOC check fired during local development" |
| Why-3 | (absent) | "`bin/venv-python -m scripts.validate --pre` does not invoke `validate_sloc_limits()`; the check is `presubmit`-tier only -- gated on `scope in ('python','all')` at `scripts/validate.py:2294`, and the `--pre` branch at `scripts/validate.py:2229` exits at line 2284 via `sys.exit(0)` before falling through" |
| Why-4 | (absent) | "the SLOC check was placed in the slower tier despite being O(lines) and sub-100ms; the tier-placement decision lacks a documented rationale" |
| Why-5 | (absent) | "no policy requires tier-placement of new checks to be defended in the PR that introduces them" |
| Corrective action | "refactor OR add waiver" | (same -- this is the point fix to restore service) |
| Preventive action | (absent) | "promote `validate_sloc_limits` to `--pre`" + "add a tier-placement rationale gate to the validate.py PR review template" |

### Additional findings the RCA missed

- **Failure category conflation.** rec-859 mentions "rec-858 (runner IAM policy lacks `dynamodb:PutItem`) prevented direct filing" as background colour in the same `context` field. This is a **separate failure category** -- a write-path infrastructure gap, not a SLOC enforcement gap. A proper RCA files these as two distinct recs with two distinct detection-gap analyses. Mixing them obscures both signals: rec-859's downstream consumer (`/plan`) cannot tell whether they need to scope (a) a SLOC-promotion plan, (b) an IAM-extension plan, or both.
- **Recurrence class unstated.** rec-859 does not state whether this is novel, an instance of a known pattern, or a regression. It is an **instance of a known pattern**: any check placed in the `presubmit` tier when it could run in `--pre` will produce the same failure mode. The pattern is reusable, and naming it enables the agent (and `/plan`) to identify analogues fast.
- **Empirical confirmation absent.** rec-859 asserts the SLOC limit was violated but does not cite the empirical state of `--pre` against the failing tree. A proper RCA includes the verification command (`bin/venv-python -m scripts.validate --pre`) and the observed result -- the command completes without invoking `validate_sloc_limits`. Without this, `/plan` must re-derive the detection-gap claim from first principles.

These three gaps -- conflation, missing recurrence class, missing empirical confirmation -- are not failures of agent prose. They are failures of agent **structure**. The agent was not asked for them, so it did not provide them. The contract below asks for them.

## The contract

### 1. Mandatory structured context schema for `source=ci_rca`

When called with `source=ci_rca`, `ops_data_portal.get_rec_write_guidance()` returns the schema below as the authoritative field specification. The agent composes a value for each field. `ops_data_portal.file_rec()` rejects writes missing any required field or where any sub-field fails semantic validation (Section 4).

```yaml
# context schema for source=ci_rca
# Implementation note: this YAML form is illustrative;
# the canonical specification is the Pydantic model in scripts/ops_data_portal.py
# (added by PLAN-ci-rca-schema-enforcement).

schema_version:
  type: int
  required: true
  value: 2
  semantics: |
    Monotonic integer. Readers must accept schema_version <= current_version
    (forward-compat). The portal rejects schema_version > 2 (le=2 enforced).
    New recs file at schema_version=2; historical schema_version=1 recs still
    validate (backward compat). Every breaking change to this schema increments
    the version and lands as its own follow-on plan with a documented migration
    for existing recs.
    Deprecation horizon: versions are sunset only by an explicit Decision
    Record + migration plan. All schema_version <= current_portal_version
    are accepted indefinitely (no implicit deprecation by age).

proximate_cause:
  type: str
  required: true
  min_chars: 100
  max_chars: 600
  semantics: |
    What the failing check actually observed -- the observable, not the inference.
    Anti-example (rejected by critique): "file is too big".
    Example (accepted): "validate_sloc_limits() raised: scripts/product_roadmap.py
    is 810 SLOC, exceeds 500 limit (Decision 43, no waiver header found in first
    10 lines)."
    The min_chars floor exists to prevent terse single-noun-phrase placeholders;
    the max_chars ceiling accommodates multi-line tracebacks without unbounded growth.

why_chain:
  type: list[str]
  required: true
  min_length: 3
  max_length: 7
  per_entry_min_chars: 40
  per_entry_max_chars: 250
  semantics: |
    Iterative "but why?" descent from proximate_cause to a systemic gap. Each
    entry MUST be a strict causal antecedent of the previous; an entry that
    rephrases the prior in different words is a known anti-pattern that the
    portal cannot detect deterministically (see Section 5). Quality control
    for causal-antecedence is handed off to /plan-critique and the human
    PR review.
    Entry 1 explains why proximate_cause was true.
    Entry N (final) MUST terminate on a systemic property (policy gap,
    missing gate, tier-placement defect, contract gap). The portal enforces
    this deterministically via TWO layered checks (both must pass):
      (a) Final entry MUST contain at least one of {gate, tier, policy,
          contract, gap, missing, absent, placement, scope, invariant,
          enforcement}.
      (b) Final entry MUST contain a file:line citation matching the
          pattern `[\w./-]+\.(py|yaml|tf|md|sh):\d+` (the same citation
          requirement gap_explanation enforces). This forces the terminus
          to be anchored to a specific artefact, not a wildcard sentence
          containing one of the (a) keywords.
    The two layered checks substantially raise the cost of token-sprinkling
    rescue-mode output: the agent must both terminate on systemic vocabulary
    AND cite a concrete location. Neither check alone is sufficient;
    together they constrain depth meaningfully but do NOT verify causal
    antecedence (see Section 5 -- that remains with /plan-critique and
    human PR review by design).
    Override available via the `why_chain_terminus_override` field below.

why_chain_terminus_override:
  type: object
  required: false
  fields:
    reason:
      type: str
      required: true
      min_chars: 80
      max_chars: 400
    auditable_rec_id:
      type: str
      required: true
      semantics: |
        The agent MUST file a sibling rec with source=ci_rca_terminus_override
        describing why the terminus heuristic did not apply to this case. That
        rec's ID is referenced here. Used sparingly: rate-limited at the
        portal-level (Section 4 check 6) -- the portal rejects new overrides
        if the same agent already has > 2 unresolved sibling override recs
        (status=open) in the last 7 days. "Unresolved" means the sibling rec
        has not yet been reviewed and closed via /plan. This converts the
        override from agent self-attestation into a path that requires human
        catch-up before further use; heavy use is also surfaced in Section
        7 observability.

detection_gap:
  type: object
  required: true
  fields:

    earliest_viable_gate:
      type: enum
      values: [pre, presubmit, CI, undetermined]
      required: true
      semantics: |
        The cheapest tier where this check COULD have run, given its runtime
        characteristics and dependency profile. Aligns with Decision 60's
        two-tier local model plus the CI runner. MUST match the deterministic
        computation in evidence_bundle.json (see Section 3 and Section 2
        cross-check rule). "undetermined" when the deterministic probe abstained
        (AST parse failure, timed probe failure, or sample dispersion too high).
        Agent MUST mirror this value from the bundle (bundle-wins).

    actual_gate_that_caught_it:
      type: enum
      values: [pre, presubmit, CI]
      required: true
      semantics: |
        The tier where the check actually fired. MUST equal the value the
        evidence bundle derives from the triggering workflow_run event via
        the workflow_to_tier map in config/ci_rca_taxonomy.yaml.

    gap_explanation:
      type: str
      required: true
      min_chars: 120
      max_chars: 600
      semantics: |
        Why earliest_viable_gate did not fire. MUST cite at least one concrete
        artefact with file:line.
        Example: "scripts/validate.py:2294 gates SLOC check on scope in
        ('python','all'); the --pre branch at scripts/validate.py:2229 returns
        at line 2284 via sys.exit(0) before falling through to the full tier."
        Generic statements such as "the check wasn't there" fail the min_chars
        floor and a separate critique check rejects entries without a file:line
        token.

recurrence_class:
  type: enum
  values: [novel, instance_of_known_pattern, regression]
  required: true
  semantics: |
    novel: this failure mode has not been seen before in this repo.
    instance_of_known_pattern: there is an existing decision, rec, or doc
      that describes the class. Citation goes in prior_art_citation.
    regression: a previously-resolved rec re-fired. Citation goes in
      prior_art_citation.

prior_art_citation:
  type: list[str]
  required_when: recurrence_class in (instance_of_known_pattern, regression)
  min_length: 1
  max_length: 5
  semantics: |
    Typed citations to prior art (Decision Records, recs, or doc paths)
    that justify the recurrence_class. Each entry MUST match one of:
      ^decision-\d+$        # canonical Decision Record reference
      ^rec-\d+$             # canonical recommendation reference
      ^docs/.*\.md(#[a-z0-9-]+)?$   # doc-path with optional anchor
    The portal verifies each citation EXISTS (not just lexically valid):
      - decision-N looked up against ops_decisions_current  **[STALE: Athena view superseded; DuckLake reader named-verb surface per Decision 84/81. Citation-existence lookup DEFERRED to PLAN-ci-rca-evidence-script Phase 2.]**
      - rec-N looked up against ops_recommendations_current  **[STALE: same -- DuckLake reader; existence lookup DEFERRED.]**
      - docs/... path looked up via filesystem stat
    Citations that do not exist are rejected with a specific diagnostic.

    Existence-only is gameable (an adversarial agent could always cite the
    same evergreen rec-001 or decision-43 for any pattern). The portal
    therefore adds a RELEVANCE constraint that is also deterministic: at
    least one citation in prior_art_citation MUST satisfy ONE of:
      (i)  Appear as an element of evidence_bundle.related_recs_by_category
           (the bundle's deterministically-computed analogues, derived from
           historical recs with the same failure_category)
      (ii) Match the failed_check name as a substring (e.g. citing a
           prior `rec-417` whose title or context contains
           "validate_sloc_limits")
      (iii) Match a Decision Record cited by evidence_bundle.
            decision_records_cited

    Citations that exist but satisfy none of (i)-(iii) are rejected with a
    diagnostic that names the bundle-derived alternatives. Semantic
    relevance beyond this structural intersection (e.g. "is this the
    correct decision to cite for THIS failure mode?") is NOT
    deterministically checked; that review is at /plan-critique.

corrective_action:
  type: str
  required: true
  min_chars: 100
  max_chars: 600
  semantics: |
    The point fix that restores green CI on the failing branch. Tactical,
    scoped. This is the rescue-mode output and is required, not optional.

preventive_action:
  type: str
  required: true
  min_chars: 100
  max_chars: 800
  semantics: |
    The class fix that prevents recurrence. State "N/A -- corrective is
    sufficient" only when recurrence_class is novel AND corrective_action
    is itself a structural change (e.g. a Decision Record). Otherwise this
    field MUST cite a systemic change.

evidence_bundle_ref:
  type: object
  required: true
  fields:
    sha256:
      type: str
      required: true
      pattern: '^[0-9a-f]{64}$'
    s3_uri:
      type: str
      required: true
      pattern: '^s3://agent-platform-data-lake/ci-rca-evidence/[0-9a-f]{64}\.json$'
    upload_status:
      type: enum
      values: [ok, upload_failed]
      required: true
      semantics: |
        upload_failed indicates the bundle was generated locally but could
        not be persisted to S3 (e.g. S3 degraded). Section 4 check 7 has a
        degraded-path branch in this case (rec accepted, staleness flagged
        in Section 7 observability).

escape_mode:
  type: enum
  values: [check_absent, check_ran_vacuously, tier_misplaced, no_premerge_gate_by_design, undetermined]
  required: false
  semantics: |
    Bundle-derived, agent-mirrored gate-escape mode (bundle-wins). Set by compute_escape_mode()
    in scripts/ci_rca_vacuous_pass.py and emitted in the evidence bundle. MIRROR from bundle;
    do not free-choose. "undetermined" when the bundle abstained.

rca_confidence:
  type: enum
  values: [high, medium, low, undetermined]
  required: false
  semantics: |
    Agent-assessed confidence in the RCA. Set "undetermined" when bundle.earliest_viable_gate
    == "undetermined" (probe abstained). Surfaces the rec for mandatory human review in
    session_preflight. Added by PLAN-ci-rca-abstention-and-gate-escape.
```

The full structured object is serialised as JSON and written to a NEW sibling column `context_v2_json` on `ops_recommendations`. **[STALE: "via an Iceberg ALTER TABLE ADD COLUMNS context_v2_json string" superseded -- column added via DuckLake reconcile_table_columns (maintenance Lambda action_reconcile_columns against the production ducklake_ops catalog), Decision 84/81. Athena LIKE queries superseded by DuckLake reader named-verb reads.]** The legacy `context` column receives a short human-readable summary (one paragraph, satisfies the existing `_validate_context_length` 80-character floor at `scripts/ops_data_portal.py:160`) so existing free-text consumers (`/plan` preflight render, audit dashboards) keep working. This sibling-column approach is the migration-safe alternative to overloading the existing `context` field with JSON, which the adversarial critique flagged as a breaking change for current readers.

**Migration ordering.** **[STALE: "The Iceberg schema migration (ALTER TABLE ADD COLUMNS) MUST complete and be observable from Athena" superseded by DuckLake -- the column migration runs via maintenance Lambda (reconcile_table_columns, Decision 84/81) and is confirmed by ducklake_neon_smoke_test --migrate-ops-recs-columns BEFORE Phase 4 strict-mode flip (Section 6).]** PLAN-ci-rca-schema-enforcement enforces this ordering: the strict-mode flip is gated on a verification step that confirms the new column is present in the live table schema.

### 2. Cross-check rule

The agent's `detection_gap.earliest_viable_gate` MUST equal the deterministic computation from `scripts/ci_rca_evidence.py` (Section 3). On disagreement, `ops_data_portal.file_rec()` rejects with a message of the form:

```
RecWriteRejected: detection_gap.earliest_viable_gate=<agent_value>
disagrees with evidence_bundle.earliest_viable_gate=<bundle_value>.
The bundle is authoritative. Either accept the bundle's value and revise
gap_explanation accordingly, or file a separate rec questioning the
bundle's classification using source=ci_rca_evidence_dispute (see
PLAN-ci-rca-evidence-dispute for the dispute path's own schema and
review flow).
```

The agent's `detection_gap.actual_gate_that_caught_it` MUST equal the bundle's value. The bundle derives the tier from the triggering `workflow_run` event payload via the `workflow_to_tier` map in `config/ci_rca_taxonomy.yaml` (Section 3.2 step 2). The map is the explicit boundary between workflow names (mutable strings) and tier enum values (typed contract); a workflow rename without a map update is a deterministic mismatch the bundle catches.

The bundle's `evidence_bundle.json` content is referenced from the rec by SHA-256 hash (Section 1, `evidence_bundle_ref`). The portal verifies the hash exists in `s3://agent-platform-data-lake/ci-rca-evidence/<sha>.json` UNLESS `upload_status=upload_failed` (degraded path -- see Section 4 check 7). The hash anchors the bundle so the rec cannot drift from the evidence post-hoc.

**Design rationale.** The bundle wins on disagreement because the bundle is generated by deterministic code over repo state; the agent is generated by an LLM over the same repo state. When they disagree, the more reproducible signal must win. The dispute escape hatch (`source=ci_rca_evidence_dispute`) is itself a typed, schema-validated path (see follow-on plan), not a free-form override -- it routes through normal `/plan` review and feeds back into bundle-script bug fixes when the bundle's logic is itself the defect.

**escape_mode bundle-wins.** The agent's `detection_gap.escape_mode` MUST equal the bundle's `escape_mode` when the bundle's value is non-null and non-undetermined. Same reject message shape as earliest_viable_gate.

**vacuous_pass author-discipline rejection.** When the bundle's `vacuous_pass=true`, the failure was a test collection defect. A rec whose `gap_explanation` or `why_chain` attributes the failure to author discipline (e.g. "did not run --pre", "author skipped") is rejected UNLESS `escape_mode=check_ran_vacuously` or a typed `failure_category` dispute is filed. This rejects the rec-2423/rec-2424 pattern deterministically.

**Cross-check spine is code.** The spine is implemented in `file_rec()` in `scripts/ops_data_portal.py`. It loads the local canonical bundle (Decision 88: local path, not S3), verifies SHA-256, compares `earliest_viable_gate` and `escape_mode` (bundle-wins), enforces the undetermined mirror rule, and applies the vacuous_pass rejection. All enforcement is gated by `CI_RCA_STRICT_MODE` (warn logs / strict raises); SHA-256 mismatch is always loud-fail.

### 3. The `scripts/ci_rca_evidence.py` script contract

This script runs as a deterministic preprocessing step before the LLM agent is invoked. Its output (`evidence_bundle.json`) is uploaded to S3 and surfaced to the agent as required reading; the agent's structured-context output must align with it (Section 2).

#### 3.1 Invocation
```bash
bin/venv-python -m scripts.ci_rca_evidence \
  --workflow-run-id <int> \
  --repo <owner/name>          # defaults to current git remote
  --validate-path scripts/validate.py
```

#### 3.2 Computation

1. **Fetch failure log and structured failed-checks list.** `gh run view <id> --log-failed` retrieves the raw log; `gh run view <id> --json jobs` retrieves the structured job/step list. Both are persisted in the bundle.
2. **Classify failure by structured function-name match (primary), regex on logs (fallback).** Read `config/ci_rca_taxonomy.yaml` which provides:
   - `function_to_category`: a map from validator function name to failure category. Example: `validate_sloc_limits: sloc_violation`. This is the primary classifier -- because validate.py is the single source of truth (`AGENTS.md`) and CI step output structurally references the failing validator, the function-name match is deterministic and robust to error-message wording changes.
   - `log_pattern_to_category`: a regex map applied to the raw log as fallback when function-name match yields no result (e.g. failures outside `validate.py` such as `pytest` collection errors or runner-level errors).
   - `workflow_to_tier`: a map from GitHub Actions workflow name to tier enum value. Example: `CI: CI`, `validate-presubmit: presubmit`. This is the authoritative mapping for Section 2's `actual_gate_that_caught_it` derivation.
     - **Coverage validator.** `scripts/validate.py` adds a check (`validate_ci_rca_taxonomy`) that fails if any `.github/workflows/*.yml` workflow name is absent from the `workflow_to_tier` map. This forces map maintenance on every workflow add/rename PR. The check runs in `--pre` (sub-100ms, deterministic file glob + YAML parse). PLAN-ci-rca-evidence-script lands the check alongside the script itself.
     - **Miss behaviour.** If the bundle script encounters a workflow name not in the map at runtime (despite the coverage validator -- e.g. a race during a workflow rename), it sets `workflow_to_tier_resolution=unknown`, `actual_gate_that_caught_it=null`, AND emits a secondary rec via `source=ci_rca_taxonomy_extension` flagging the missing entry. Cross-check is skipped (Section 2 explicit). This is the same shape as the taxonomy-fallback failure mode in Section 3.4 -- a known degradation path, not a crash.
   - The initial taxonomy and the maintenance protocol are defined in PLAN-ci-rca-evidence-script. Categories are extensible via separate recs of `source=ci_rca_taxonomy_extension`.
3. **Compute tier-membership matrix.** Parse `scripts/validate.py` via AST (`ast.parse`). The walker MUST handle the real control-flow structure of `validate.py`, not a simplified model:
   - **Direct calls from `main()`.** The `--pre` branch (currently `scripts/validate.py:2229-2290`) calls validators directly (e.g. `validate_iam_runner_policy`, `validate_product_roadmap`); these are NOT routed through `run_python_checks`. The walker records every `Call` node whose function-name matches `validate_*` at any descendant of the `if args.pre:` block.
   - **Calls through aggregator functions.** `run_python_checks` and `run_terraform_checks` are aggregators called from the `presubmit/full` tier. The walker resolves these one level of indirection: it visits each aggregator function definition and records the `validate_*` calls inside.
   - **Early returns and `sys.exit` short-circuits.** The walker must detect when a tier branch contains a `sys.exit` or `return` statement BEFORE a `validate_*` call site -- such a call is unreachable from that branch. Concretely: the `--pre` branch at `scripts/validate.py:2229-2290` exits via `sys.exit(0)` at line 2284 (success path) and `sys.exit(1)` at line 2290 (failure path) BEFORE falling through to the full tier at line 2292. Validators called only at or after line 2292 are NOT reachable from `--pre`, even though they appear in the same `main()` body.
   - **Duplicate registration.** A validator registered in BOTH `--pre` direct-call list AND `presubmit/full` aggregator emits `["pre", "presubmit"]`. Example: `validate_product_roadmap` is called at line 2263 (--pre branch) AND at line 1948 (inside `run_python_checks`). The walker must catch both registrations.
   - **CI tier is derived, not parsed.** The `CI` enum value is assigned by the `workflow_to_tier` map (step 2 above), not by AST parse -- because CI runs `validate.py` without flags, the same membership matrix that classifies `presubmit` also classifies `CI`. A validator in `tier_membership["validate_X"] = ["presubmit"]` is also reachable from CI (the workflow_to_tier map handles the workflow-name -> tier mapping).
   - Emit a map: `{"validate_sloc_limits": ["presubmit"], "validate_product_roadmap": ["pre", "presubmit"], ...}`.
   - The matrix is recomputed every run -- it is not cached. Freshness matters more than speed because tier placement can drift.
   - **Contract test required.** PLAN-ci-rca-evidence-script lands a contract test (`tests/test_ci_rca_evidence_ast.py`) that asserts the walker's output against a fixture mirror of the current `validate.py` structure, including the four control-flow cases above. Walker changes that break the fixture are rejected at CI; fixture updates require Decision-Record-class review because they encode the contract's understanding of `validate.py`'s shape.
4. **Compute `earliest_viable_gate` recommendation.** Deterministic decision tree, applied in order:
   - If the failing check has external dependencies (Athena, Lambda invocation, network access, AWS profile), recommend `presubmit`. `--pre` is offline-tolerant by contract (Decision 60).
   - Otherwise, measure runtime via N=5 timed invocations of the check against the failing tree, drop the highest and lowest samples, take the median of the remaining 3. Emit `runtime_confidence` in the bundle (Section 3.3) describing sample dispersion across all 5 raw samples (e.g. `runtime_confidence: "median=47ms n=5 trimmed_n=3 raw=[44, 46, 47, 49, 89] dispersion=15%"`). The N=5 + drop-extremes pattern reduces variance under self-hosted-runner load (which the adversarial critique flagged as flipping `pre` vs `presubmit` recommendations under contention).
   - If the failing check is currently in `presubmit` only AND median runtime is under the headroom available in `--pre` (the difference between `_FAST_TIER_BUDGET_SECONDS=300` and the current measured `--pre` runtime), recommend `pre`.
   - If currently in `--pre` already, the gate is correctly placed; `earliest_viable_gate = pre`.
   - If runtime exceeds available headroom, recommend `presubmit`.
   - If the timed probe fails or sample dispersion exceeds 50% of the median, set `earliest_viable_gate = "undetermined"` and surface the failure in Section 3.4. The cross-check requires the agent to mirror "undetermined" (not free-choose a gate value).

#### 3.3 Output: `evidence_bundle.json`

```json
{
  "schema_version": 3,
  "workflow_run_id": 26286390667,
  "workflow_name": "CI",
  "workflow_to_tier_resolution": "CI",
  "failed_check": "validate_sloc_limits",
  "failure_category": "sloc_violation",
  "classification_source": "function_to_category",
  "tier_membership": {
    "validate_sloc_limits": ["presubmit"]
  },
  "earliest_viable_gate": "pre",
  "earliest_viable_gate_rationale": "validate_sloc_limits is in presubmit tier only (scripts/validate.py:2294 gates run_python_checks; aggregator at line 1945 calls validate_sloc_limits). The --pre branch (scripts/validate.py:2229) exits via sys.exit at lines 2284/2290 before fallthrough. Runtime: median 47ms (range 44-51ms) against current tree. Current --pre runtime: 12.3s. _FAST_TIER_BUDGET_SECONDS=300; headroom is ample. Recommend promotion to --pre.",
  "runtime_confidence": "median=47ms n=3 range=[44ms, 51ms] dispersion=15%",
  "actual_gate_that_caught_it": "CI",
  "related_recs_by_category": ["rec-417", "rec-589"],
  "decision_records_cited": ["Decision 43", "Decision 60", "Decision 68"],
  "ast_walker_version": 1,
  "taxonomy_version": 1,
  "gate_is_postmerge_canary": true,
  "vacuous_pass": "undetermined",
  "merge_gate_test_coverage": "not_selected",
  "coverage_regression": "undetermined",
  "escape_mode": "<computed>",
  "sha256": "<computed at write time>"
}
```

The SHA-256 hash is computed over the canonical-JSON serialisation of all fields except `sha256` itself, then inserted as `sha256`. The same hash is referenced from the rec's `evidence_bundle_ref` field (Section 1). The hash anchors the bundle so the rec cannot drift from the evidence post-hoc.

**Canonical JSON specification.** Implementations MUST use Python's `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)` or an RFC 8785 (JSON Canonicalisation Scheme) equivalent. This pins key ordering, whitespace, and number formatting so two implementations produce identical hashes for the same logical bundle. PLAN-ci-rca-evidence-script lands a unit test asserting hash stability across a fixture set.

**Multi-failure example (N=2 failed checks in one workflow run).** When CI run 26286390667 fails BOTH `validate_sloc_limits` AND `validate_iam_runner_policy`, the bundle script emits TWO separate `evidence_bundle.json` objects with shared `workflow_run_id=26286390667` and distinct `sha256` hashes. The agent then files TWO `source=ci_rca` recs (one per failed check) via two sequential `file_rec()` calls. Each rec references its own bundle by SHA-256. The recs share `actual_gate_that_caught_it` (both `CI`) but differ in `proximate_cause`, `failed_check`, and `failure_category`. Filing is sequential, not transactional -- the portal does not provide cross-rec atomicity, and the prompt-rewrite step (PLAN-ci-rca-prompt-rewrite) handles the loop. If the first `file_rec` succeeds and the second fails, the human reviews via `/plan` the partial state. N-bundle enumeration implemented by PLAN-ci-rca-vacuous-pass-evidence (landed 2026-06-30): `classify_failures()` in `scripts/ci_rca_taxonomy.py` matches all named functions in one log scan and `generate_bundles()` emits one bundle per (category, check) tuple with a distinct sha256 per bundle and shared workflow_run_id.

#### 3.4 Failure modes

- **Taxonomy fallback (`unknown` category).** Function-name match fails AND log-pattern match fails. Bundle is emitted with `failure_category=unknown`, `classification_source="taxonomy_fallback"`, `earliest_viable_gate="undetermined"`. Agent files the main rec normally (with `recurrence_class=novel` and explicit acknowledgement of the unknown category in `gap_explanation`). Script ALSO emits a secondary rec via `source=ci_rca_taxonomy_extension` recommending taxonomy extension. The cross-check requires the agent to mirror "undetermined" (not skip).
- **AST parse failure on `validate.py`.** Bundle is emitted with `tier_membership=null`, `ast_walker_error=<parse error string>`, and `earliest_viable_gate="undetermined"`. Agent MUST mirror "undetermined" and set `rca_confidence="undetermined"`. Script emits a secondary rec via `source=ci_rca_static_analysis_failure` flagging the AST defect.
- **Timed runtime probe fails** (e.g. the check needs SSO and SSO is unavailable on the runner). Bundle reports `runtime_confidence="probe_failed: <error>"` and `earliest_viable_gate="undetermined"`. Agent MUST mirror "undetermined" from the bundle. Decision-tree skips the runtime branch; the recommendation is based on dependency analysis only when dependency analysis is definitive (e.g. the check has external deps -> presubmit). Agent's `gap_explanation` field is still required.
- **Sample dispersion too high.** When dispersion exceeds 50% of median, `earliest_viable_gate="undetermined"` and the bundle records `runtime_confidence="dispersion_too_high: <details>"`. Agent MUST mirror "undetermined" and set `rca_confidence="undetermined"`. The cross-check requires the agent to mirror "undetermined" rather than free-choose a gate value; the dispersion is surfaced in Section 7 observability so the contract can detect systemic flakiness in the probe.
- **S3 upload fails.** Bundle is generated locally but cannot be persisted to S3. Script writes the bundle to a local staging directory (`logs/.ci-rca-evidence-pending/<sha>.json`) and emits a marker file. The rec is filed with `evidence_bundle_ref.upload_status=upload_failed`. Portal accepts the rec (Section 4 check 7 degraded path) and queues the bundle for retry. Section 7 observability surfaces a "pending bundle upload" gauge.
- **Evidence bundle absent entirely (fail-loud, T1.13 c12(ii)).** The `.github/workflows/ci-rca.yml` evidence step runs `continue-on-error: true`, so a hard failure in `scripts/ci_rca_evidence.py` can produce neither a `BUNDLE_SHA` nor any emit-dir bundle file. The workflow computes `bundle_absent=true` when both are missing and injects an explicit instruction into the agent prompt: set `detection_gap.earliest_viable_gate="undetermined"` and `rca_confidence="undetermined"` so the rec is filed anyway but routes to mandatory human review. Portal-side, `ops_data_portal._run_ci_rca_cross_check` enforces this: a rec with `evidence_bundle_ref` absent/empty is REJECTED in strict mode unless `rca_confidence="undetermined"`; warn mode accepts it while logging a `CI_RCA_BUNDLE_ABSENT` structured-log gauge. This closes the previous silent-accept gap (a bundle-absent rec used to return from the cross-check with no marker at all, so a confidently-wrong RCA with zero deterministic evidence could pass through unchecked).
- **Taxonomy file missing or malformed.** If `config/ci_rca_taxonomy.yaml` does not exist or fails YAML parse, the bundle script exits non-zero before generating any bundle. The agent harness catches the non-zero exit and files a fall-back rec via `source=ci_rca_taxonomy_missing` (its own minimal schema -- run ID, error string, no main rec is filed against the original CI failure until taxonomy is restored). The harness ALSO surfaces this as a P0 alert in Section 7 observability because it represents a complete RCA pipeline outage. The `validate_ci_rca_taxonomy` check in `--pre` (Section 3.2 step 2 coverage validator) is intended to catch this BEFORE it reaches CI, so a runtime missing-taxonomy is itself a `--pre` false-negative analogous to the rec-859 case study.

### 4. Portal-level enforcement

`ops_data_portal.file_rec()` adds the following checks when `source=ci_rca`. All are hard rejections unless explicitly labelled "degraded path":

1. The `context_v2_json` argument MUST parse as the structured schema in Section 1 with `schema_version<=2`. Schema versions greater than 2 are rejected (le=2). New recs file at schema_version=2; historical schema_version=1 recs still validate. Missing the `context_v2_json` argument while `source=ci_rca` is a hard reject in strict mode (CIRCA-02, `ops_data_portal.py:1240-1252`); warn mode still accepts the legacy free-text-only write during the rollout window, logging a deprecation warning.
2. Each required sub-field MUST be present and pass per-field validation (length bounds, enum membership, pattern match).
3. `detection_gap.earliest_viable_gate` MUST equal the bundle's value when the bundle's value is non-null. On disagreement: reject with the diagnostic in Section 2.
4. `detection_gap.actual_gate_that_caught_it` MUST equal `evidence_bundle.actual_gate_that_caught_it`. The bundle derives the value via the `workflow_to_tier` map (Section 3.2 step 2). For multi-failure runs producing N recs, all N share the same `actual_gate_that_caught_it`; the multiplexing is on `failed_check` (Section 4 check 9). **[UNBUILT: actual_gate bundle comparison not performed by `_run_ci_rca_cross_check`; the 'unknown' enum reconciliation for not_a_gate workflows landed but the equality check did not -- owner: strict-flip enforcement follow-on]**
5. `recurrence_class in (instance_of_known_pattern, regression)` requires `prior_art_citation` to be present and non-empty. Each citation MUST match the patterns in the schema AND be verified to EXIST via lookup (Decision Records and recs via DuckLake reader named-verb surface **[STALE: "ops_decisions_current / ops_recommendations_current" as Athena views superseded by DuckLake closed boundary, Decision 84/81; existence lookup DEFERRED to PLAN-ci-rca-evidence-script Phase 2]**, doc paths via filesystem stat). Additionally, at least one citation MUST satisfy the relevance intersection rule in Section 1's `prior_art_citation.semantics`: appear in `evidence_bundle.related_recs_by_category` OR substring-match `failed_check` name OR match a Decision Record in `evidence_bundle.decision_records_cited`. Lexically-valid-but-non-existent citations are rejected with a specific diagnostic; existent-but-irrelevant citations (zero entries satisfying the intersection) are rejected with a diagnostic that lists the bundle-derived alternatives. **[DEFERRED: required_when presence + relevance-intersection unenforced -- `prior_art_citation` is shape-only `Optional[str]`; existence lookup already deferred to PLAN-ci-rca-evidence-script Phase 2]**
6. `why_chain` MUST satisfy structural floor: `min_length=3`, `per_entry_min_chars=40`, and the final entry MUST satisfy BOTH layered checks: (a) contain at least one of {gate, tier, policy, contract, gap, missing, absent, placement, scope, invariant, enforcement}, AND (b) contain a file:line citation matching the pattern `[\w./-]+\.(py|yaml|tf|md|sh):\d+`. On either check missing: reject. The agent may override the terminus check by populating `why_chain_terminus_override` (Section 1) and filing a sibling rec with `source=ci_rca_terminus_override`. Rate limit: the portal rejects new overrides if the same agent has more than 2 unresolved (`status=open`) override sibling recs in the last 7 days; this requires the human to resolve overrides via `/plan` before further overrides land. Heavy use is also surfaced in Section 7 observability. **[PARTIALLY-DEFERRED: structural floor + typed `_WhyChainTerminusOverride` (reason 80-400 chars, CIRCA-08) built (`ops_data_portal.py:160-164,243`); the >2-unresolved-in-7d rate limit and the `ci_rca_terminus_override` sibling rec filing are UNBUILT -- owner: strict-flip enforcement follow-on]**
7. **Bundle-absent fail-loud (implemented, T1.13 c12(ii)).** If `evidence_bundle_ref` is absent/empty entirely, the rec is REJECTED in strict mode unless `rca_confidence="undetermined"` (routing it to mandatory human review); warn mode accepts while logging `CI_RCA_BUNDLE_ABSENT`. When `evidence_bundle_ref` IS present: the `sha256` MUST be present and pattern-valid. **S3-object-existence verification is implemented** (no longer deferred to Phase 2): if `upload_status=ok`, the portal performs a `head_object` call against `evidence_bundle_ref.s3_uri` (reusing the `scripts/ci_rca_evidence.py` boto3 session/region pattern); a missing object is rejected in strict mode / warned in warn mode. If `upload_status=upload_failed`, this check takes the degraded path: accept the rec, do NOT verify S3 existence, queue the bundle for retry, surface the staleness in Section 7 observability. Recs with `upload_status=upload_failed` are flagged for /plan attention. If the S3 read itself cannot be evaluated (missing credentials, denied permission, or a malformed `s3_uri`), the check fails OPEN with a warning -- filing is never wedged by a runner lacking S3 read access (the IAM grant for CI read access rides with c2 / the strict-mode flip).
7a. **vacuous_pass author-discipline rejection.** When `bundle.vacuous_pass=true` and the rec attributes the failure to author discipline (see Section 2 vacuous_pass rule), reject unless `escape_mode=check_ran_vacuously` or a typed `failure_category` dispute is filed via `source=ci_rca_evidence_dispute`.
8. **`source=ci_rca_evidence_dispute` carve-out.** Recs filed against this contract's dispute path use their own schema (defined in PLAN-ci-rca-evidence-dispute) and are NOT subject to checks 1-7 above. They reference the parent ci_rca rec being disputed via a `parent_rec_id` field and follow the dispute schema's own validation. `disputed_field` enum is: `earliest_viable_gate | actual_gate_that_caught_it | failure_category`. This carve-out is the only legitimate escape from the cross-check spine.
9. **Multi-failure runs.** A single CI workflow run can produce N independent failed checks. The contract is one rec per failed check. The bundle script emits one bundle per failed check (multiple SHA-256s for the same workflow_run_id), and the agent files N recs (each with a distinct `failed_check` and `proximate_cause`). All N recs share the same `actual_gate_that_caught_it`. Aggregating multiple categories into one rec (the conflation anti-pattern from rec-859) is rejected at check 5 (`prior_art_citation` will not lexically match a non-citation) and at the schema level (`proximate_cause` references one failed check).

**Decision 86 note (accuracy-preservation, CIRCA-09):** the `[UNBUILT]` / `[DEFERRED]` / `[PARTIALLY-DEFERRED]` annotations added to checks 4, 5, and 6 above are an accuracy-preservation pass on this grandfathered doc -- they correct enforcement claims to match current code, nothing more. They do NOT discharge this section's Wave-3 extraction to `docs/contracts/` (tracked in `docs/intent-migration/MANIFEST.yaml`); that extraction remains the owner of this section's long-term structural form.

### 5. What this contract DOES NOT do

- It does NOT police the *quality* of the agent's prose within each free-text field. That review remains with `/plan-critique`, code review, and human PR review.
- It does NOT prevent the agent from filing a rec with a *wrong* `why_chain` *in content*. It prevents the agent from filing a rec with NO `why_chain`, with `why_chain` shorter than 3 entries, with vapid one-liner entries (per-entry minimum 40 chars), or with a terminus failing BOTH the systemic-terminology heuristic AND the file:line citation requirement. The structural floor is "the analysis was attempted, reaches a systemic terminus by terminology, AND anchors that terminus to a concrete artefact". The two-layer terminus check substantially raises the cost of token-sprinkling adversarial output: an agent must both terminate on systemic vocabulary AND identify a specific file:line. This is a depth SIGNAL, not a depth GUARANTEE -- a determined agent can still write a chain whose terminus contains "scope is missing at scripts/foo.py:1" without that terminus actually being a causal antecedent of the prior entry. The semantic ceiling -- "is each entry actually a causal antecedent of the previous, and does the terminus citation actually correspond to the gap?" -- is unenforceable deterministically. That review explicitly stays with `/plan-critique` (which sees every rec before consumption) and human PR review of the resulting `/plan` and `/implement` artefacts. Section 7 observability is the at-scale signal: sustained patterns of the same terminus citation, sustained override usage, or sustained citation diversity below a threshold indicate adversarial drift that requires methodology revision (not just per-rec rejection).
- It does NOT replace `corrective_action` with `preventive_action`. Both are required. The rescue output is still emitted; the RCA output is structurally co-required.
- It does NOT modify Decision 43 (the SLOC limit). The limit is a policy. The gap is in *where the policy is enforced*, not in the policy.
- It does NOT extend the failure taxonomy. The initial set in Section 3.2 step 2 is a starting point. Taxonomy growth is governed by `source=ci_rca_taxonomy_extension` recs, which feed into normal `/plan` review.
- It does NOT prescribe the exact agent prompt. The prompt rewrite is `PLAN-ci-rca-prompt-rewrite`, which must conform to this contract but is free to choose its phrasing, step structure, and worked examples.
- It does NOT add `IDE` or `manual_review` as enforceable tiers. Those layers have no current enforcement surface in this repo; including them would create dead enum branches that the deterministic computation cannot match. Future additions go via Decision Record + schema_version bump.

### 6. Migration and rollout

This document is the methodology contract. Operationalisation is split across follow-on plans (next section). The rollout uses a feature flag `CI_RCA_STRICT_MODE` to avoid stuck-rec failure modes during phased delivery.

- **Phase 0 -- Feature flag default `warn`.** Before any follow-on plan lands, add `CI_RCA_STRICT_MODE` to `config/feature_flags.yaml` defaulting to `warn`. The flag is terraformed via `terraform/feature_flags.tf` and surfaced to the portal at process start (no hot-reload). Promotion to `strict` requires (a) a Decision Record explicitly approving the flip, (b) a `terraform plan` output presented to a human, and (c) `terraform apply`. Any committer can OPEN the PR proposing the flip, but the Decision-Record review gate ensures the flip is a deliberate architectural action. Demotion back from `strict` to `warn` (the circuit breaker) is permitted without a Decision Record because it is a safety action, but it AUTO-FILES a high-priority rec via `source=ci_rca_strict_mode_demotion` summarising why; the rec is consumed by `/plan` in the next session so the team must explicitly diagnose and re-promote rather than letting the system idle in `warn` indefinitely. In `warn` mode, the portal accepts any `source=ci_rca` write (legacy free-text or new schema), logs a structural-deficiency warning for non-compliant writes to Section 7 observability, and does NOT reject. This guarantees that no phase of the rollout produces a stuck-rec window where CI failures are unfilable.
- **Phase 1 -- Schema + portal enforcement (warn).** PLAN-ci-rca-schema-enforcement lands the Pydantic model in `scripts/ops_data_portal.py`, the new `context_v2_json` sibling column, and the portal-level validation. Behaviour with `CI_RCA_STRICT_MODE=warn`: writes that include `context_v2_json` are validated and structural deficiencies logged; legacy writes (free-text `context` only) pass with a deprecation warning. Rejections do not happen yet.
- **Phase 2 -- Evidence script (warn).** PLAN-ci-rca-evidence-script lands `scripts/ci_rca_evidence.py` and the S3 bucket prefix lifecycle policy. Cross-check is computed but not enforced until Phase 4.
- **Phase 3 -- Agent prompt (warn).** PLAN-ci-rca-prompt-rewrite rewrites `.claude/agents/scheduled/ci-rca.md` to invoke the evidence script and compose against the schema. At this point all three implementation surfaces exist and the agent produces conformant output. `CI_RCA_STRICT_MODE` is still `warn` for one full week of CI cycles to validate end-to-end with real failures.
- **Phase 4 -- Back-validation (implemented, landed via PLAN-ci-rca-back-validate), then flip to `strict`.** Once Section 7 observability shows the warn-mode rejection rate is consistently low (e.g. < 5% over 7 days of CI failures), run a back-validation step BEFORE flipping the flag: `bin/venv-python -m scripts.ops_data_portal --back-validate --since <phase-1-landing-date>` (shipped flat-action CLI signature, distinct from the `find_preventive_regressions` sensor in `scripts/ci_rca_back_validation.py`) that re-validates every `source=ci_rca` rec written during the warn-period against the CURRENT strict-mode schema, reading only the warm cache (Decision 88, zero new reader egress). A rec with no `context_v2_json` is bucketed `legacy_no_schema` and is never counted non-conformant (strict-mode `file_rec()` accepts it). With `--refile-audit`, each non-conformant rec is re-filed as a re-audit rec via `source=ci_rca_warn_period_audit` (capped at 20/day) with the parent rec ID and a list of failing checks; the default invocation is report-only. This prevents adversarial behaviour entrenchment: any structurally-thin rec that shaped `/plan` architecture during the warn window is surfaced for human review before strict mode forecloses similar future filings. Only after back-validation completes AND its output is reviewed at `/plan` does the Decision Record approving the flip get authored. Then promote `CI_RCA_STRICT_MODE` to `strict` via the terraform path in Phase 0. Hard rejections fire.
- **Phase 5 -- Concrete consumer (canonical exercise).** PLAN-sloc-promotion-to-pre exercises the new methodology by acting on the case study's preventive_action: promote `validate_sloc_limits` from presubmit to `--pre`. This validates the methodology end-to-end against the failure mode that motivated it.

This phased rollout addresses the adversarial critique's "stuck rec" concern: the contract is enforced lazily (warn -> strict) rather than eagerly, and the feature flag is the rollback path. If Phase 4 reveals systemic friction, flip back to `warn` while issues are diagnosed; no CI failures are lost.

### 7. Observability

The contract is only as good as our ability to measure whether it actually deepens RCA over time. Without observability, this becomes a write-only methodology where the team cannot tell rescue-style filings from real RCAs at scale. PLAN-ci-rca-schema-enforcement lands the observability hooks; PLAN-ci-rca-observability-dashboard lands the surfacing surfaces.

#### 7.1 Re-grounded design: DuckLake/warm-cache surfacing (implemented, T1.13 c1/c3)

**[RE-GROUNDED 2026-07 by PLAN-ci-rca-observability-dashboard.]** The original design in this section called for a new Athena table `ops_ci_rca_telemetry` and a `ci_rca_health` view. Both are superseded by the DuckLake closed boundary (Decision 84/81): `ops_recommendations` moved to DuckLake-on-Neon behind the closed `ducklake_reader`/`ducklake_writer` verb surface, and no new NAMED_READS verb or Class-A column is warranted for observability that the already-loaded warm cache can answer (Decision 88 zero-egress; Decision 103/84 no new SCD2 column). The metrics below are instead computed client-side, in `scripts/session_preflight.py`'s `_compute_ci_rca_telemetry()`, by parsing `context_v2_json` off the warm `recs_cache` rows preflight already pulls -- no new reader call, no Lambda redeploy.

**Cache-derivable now:**
- **Recurrence-class distribution.** Count of `recurrence_class` (`novel` / `instance_of_known_pattern` / `regression`) across `source=ci_rca` recs in the trailing window, parsed from `context_v2_json`.
- **Warn-mode reject rate (c3's load-bearing metric).** Numerator: `source=ci_rca` recs in-window whose `context_v2_json.warn_mode_reject` marker is present. Denominator: total `source=ci_rca` recs in-window. The marker is new in this plan -- see "Warn-mode reject marker" below; before it existed, warn-would-reject writes left NO persisted trace (only a `logger.warning()` line), so this rate was underivable from the cache.
- **Dispute-path traffic.** Count of `source=ci_rca_evidence_dispute` writes in-window (satisfies rec-2415's gate; the throttle itself is a follow-on once traffic data exists).
- **Bundle-upload backlog.** Count of `source=ci_rca` recs in-window whose `context_v2_json.evidence_bundle_ref.upload_status != "ok"`.
- **why_chain_terminus_override usage.** Count of `source=ci_rca` recs in-window whose `context_v2_json.why_chain_terminus_override` is set.

**DEFERRED to telemetry Phase 4 (T2.36) -- NOT cache-derivable:**
- **Strict-mode rejection-by-reason counts.** A strict-mode rejection raises in `file_rec()`/`_run_ci_rca_cross_check()` before any write happens, so no rec is ever created and nothing lands in the cache. This requires structured-log emission into the (not-yet-rebuilt) telemetry pipeline, not a cache read.
- **Cross-check disagreement rate on REJECTED writes.** Same reasoning: a strict-mode cross-check disagreement raises before write. (Cross-check disagreement on ACCEPTED warn-mode writes IS cache-derivable today via the warn-mode reject marker's `cross_check_check_N` reasons, folded into the warn-mode reject rate above.)

**Warn-mode reject marker (implemented, c3 enabler).** `scripts/ops_data_portal.py` stamps `context_v2_json.warn_mode_reject = {"reasons": [...], "mode_at_write": "warn"}` in place, via `_stamp_warn_mode_reject()`, on every warn-mode branch that would have rejected the write in strict mode: schema-deficiency (`file_rec`'s `_validate_ci_rca_context_v2` check), bundle-absent, S3-missing, and cross-check disagreement (checks 1-4, tagged `cross_check_check_1`..`cross_check_check_4`). Strict mode raises before any write, so it never stamps. A fully-conformant warn-mode write carries NO `warn_mode_reject` key (absent, not an empty marker). The field is Tier-B portal-derived (Decision 66): the ci-rca agent prompt is unchanged and never sets this field itself. It rides the existing `context_v2_json` blob as an explicit `CiRcaContext.warn_mode_reject: Optional[dict]` model field -- not a new SCD2 column (Decision 103/84) -- and `schema_version` stays at 1 (the field's `le=2` bound already permits future use; this is an additive optional field, no bump needed). It is declared explicitly (not left to pydantic's default `extra='ignore'`) so it survives a `CiRcaContext` round-trip parse.

#### 7.2 Preflight surfacing (implemented, T1.13 c1/c3)

`scripts/session_preflight.py` prints a `CI-RCA Telemetry (last 7d)` section (`print_ci_rca_telemetry()`) showing:
- Recurrence-class distribution (novel / instance_of_known_pattern / regression counts)
- Warn-mode reject rate: `<count>/<total>` (`<rate>%`), with a threshold note when it fires
- Dispute-path traffic
- Bundle-upload backlog
- why_chain_terminus_override usage

The gauge is also written into the preflight report JSON under `ci_rca_telemetry` (`_compute_ci_rca_telemetry()`), computed entirely from the warm cache with zero new reader egress (Decision 88).

**Threshold status.** Of the three original thresholds: the 25% warn-mode-reject-rate alert ("ci_rca enforcement may need tuning") and the <=5% Phase-4-promotion-gate note are BOTH cache-derivable from the warn-mode reject rate above and are surfaced by `print_ci_rca_telemetry()`. The 10% strict-mode-rejection alert is DEFERRED to telemetry Phase 4 (T2.36) alongside the strict-mode rejection-by-reason counts in 7.1 -- there is no rec created on a strict rejection, so this threshold cannot be evaluated from the cache today; it is not silently dropped, just gated on the same Phase-4 telemetry-pipeline rebuild.

**Threshold provenance.** The 25% / 10% / 5% values remain starting heuristics with no empirical grounding. The mandated first threshold-tuning follow-on (revisit after a full week of Phase-4 data) is tracked as a FILED REC rather than standing prose here (Decision 86 forward-intent routing) -- see the rec filed alongside this plan's landing.

**Probe abstention gauge (implemented, T1.13 c12(i)).** `scripts/session_preflight.py` prints a `CI-RCA probe abstention (last Nd): K/M undetermined (R%)` line, computed via `scripts/ci_rca_probe_health.compute_abstention_rate` from the already-warmed recommendation cache (zero new reader egress, Decision 88) -- the count of `source=ci_rca` recs with `rca_confidence="undetermined"` over the trailing window against the total `source=ci_rca` recs in that window. The gauge fields (`undetermined_count`, `total_count`, `rate`, `window_days`) are also written into the preflight report JSON under `ci_rca_abstention_gauge`. When the rate meets or exceeds `ci_rca_probe_health.ABSTENTION_RATE_THRESHOLD` (0.3) with at least `ABSTENTION_MIN_SAMPLE` (5) samples, preflight idempotently files/updates/closes exactly one `source=ci_rca_probe_health` rec via `escalate()` (mirroring `scripts/convergence_health.py`'s file/update/close pattern) -- deduped so a sustained-abstention episode produces one rec, not one per session. This substitutes for a cron trigger until Lambda scheduled agents re-enable (see the AGENTS.md runbook); it is skipped entirely in degraded/offline sessions (no creds, or the warm-cache pull failed) so it never attempts a portal write without connectivity. Sustained abstention means the deterministic evidence bundle is systematically unable to classify `earliest_viable_gate`/`escape_mode` -- the probe's depth-enforcement gate is silently degrading to a pass-through, which is exactly the class of regression this sensor exists to catch loudly rather than let compound quietly.

**Bundle-absent gauge.** The `CI_RCA_BUNDLE_ABSENT` structured-log line (Section 4 check 7) is the write-time signal for a rec filed with no evidence bundle at all. This is now fully cache-derivable: a bundle-absent warn-mode write is stamped with `warn_mode_reject.reasons=["bundle_absent"]` (7.1) and rolls into the warn-mode reject rate above; the preflight "CI-RCA Mandatory Human Review" section separately lists open `rca_confidence=undetermined` recs, the route every bundle-absent rec without a marker is forced onto.

**Preventive-action back-validation (implemented, T1.13 c12(iii)).** `scripts/session_preflight.py` prints a `CI-RCA Back-Validation (preventive_action did not hold)` section (`print_ci_rca_back_validation()`), backed by `scripts/ci_rca_back_validation.find_preventive_regressions()`. It flags an OPEN `source=ci_rca` rec that recurs on a file whose prior CLOSED `source=ci_rca` rec on that SAME file claimed a `preventive_action` -- surfacing-only (Decision 55: never remediates, never files/updates/closes a rec) and linking the prior rec so `/plan` can cross-check whether the claimed prevention actually held (Decision 57 control-plane loop-closure: "proof a fix reduced the failure mode"). The gauge is written into the preflight report JSON under `ci_rca_back_validation`, computed entirely from the warm cache (zero new reader egress, Decision 88; no new NAMED_READS verb, no Lambda redeploy). **Match key is FILE-ONLY** (`rec.file`) plus the closed prior rec carrying a non-empty `preventive_action` -- this is a materially WEAKER heuristic than the originally-scoped `docs/ROADMAP-PLATFORM.yaml` c12(iii) spec ("failed_check + failure_category, bundle-derived"), which is DEFERRED until a `failure_category` field lands in `context_v2_json` (a c9-style enrichment this plan does not implement). File-only matching over-pairs on high-churn files (e.g. `scripts/validate.py`, which accumulates many unrelated `ci_rca` recs over time) -- callers (`/plan`) MUST treat every flag as a CANDIDATE for investigation, never a confirmed regression.

#### 7.3 View -- retired, no cache-side successor needed

**[RE-GROUNDED 2026-07: this view is retired, not migrated.]** The originally-scoped Athena view `ci_rca_health` (joining `ops_recommendations_current` with `ops_ci_rca_telemetry`) is superseded by the DuckLake closed boundary (Decision 84/81) and was never implemented (no code references either surface). Its ad-hoc-query use case ("which validators produce the most ci_rca recs?", "average why_chain length?", "are instance_of_known_pattern recs concentrated in a few files?") is not reproduced by the 7.1/7.2 preflight surfacing above, which is deliberately scoped to the specific gauges this contract's self-improvement loop needs (warn-mode reject rate, recurrence-class distribution, back-validation), not general-purpose ad-hoc analytics. A DuckLake-native ad-hoc view remains a candidate for telemetry Phase 4 (T2.36) if a concrete analytics need emerges; none is scoped today.

## Follow-on plans

The following IMPLEMENTATION-type plans should be authored as separate `/plan` sessions to operationalise this methodology. Each is intended to be self-contained. These follow-on plans roll up under `T1.13` in `docs/ROADMAP-PLATFORM.yaml` ("CI-RCA methodology contract -- deterministic depth via structured schema + evidence bundle"). T1.13 is a prerequisite of T3.4 (control-plane loop closure) -- the loop closure consumes well-formed RCA signals that this contract enforces. Soft coupling with T1.5 (ops_decisions graduation): if T1.5 lands first, PLAN-ci-rca-schema-enforcement migrates its implementation surface from `ops_data_portal.file_rec()` to the `log_rec` agent_sdk verb; not blocking but worth noting at plan-authoring time.

- PLAN-ci-rca-schema-enforcement -- implement Section 1 (structured context schema, with `schema_version`, `prior_art_citation`, `why_chain_terminus_override`, `evidence_bundle_ref` fields) and Section 4 (portal-level enforcement) in `scripts/ops_data_portal.py`. Includes the new `context_v2_json` sibling column on `ops_recommendations`, `get_rec_write_guidance("ci_rca")` returning the schema, Pydantic validation in `file_rec()`, citation-existence lookup against `ops_decisions_current` / `ops_recommendations_current`, and evidence-bundle SHA-256 verification against S3 with `upload_status=upload_failed` degraded path. Also lands `CI_RCA_STRICT_MODE` config flag (defaults `warn`).
- PLAN-ci-rca-evidence-script -- implement `scripts/ci_rca_evidence.py` per Section 3: AST walker over `scripts/validate.py` with explicit handling of direct calls from main(), aggregator indirection, `sys.exit`/`return` early termination, and duplicate registration; N=3 median runtime probe with `runtime_confidence` field; taxonomy classifier reading `config/ci_rca_taxonomy.yaml` (with `function_to_category`, `log_pattern_to_category`, `workflow_to_tier` maps); S3 upload to `s3://agent-platform-agent-logs/ci-rca-evidence/<sha>.json` with `logs/.ci-rca-evidence-pending/` fallback. Includes the contract test `tests/test_ci_rca_evidence_ast.py` asserting walker output against a `validate.py` fixture.
- PLAN-ci-rca-prompt-rewrite -- rewrite `.claude/agents/scheduled/ci-rca.md` against the new schema. Inserts the evidence-bundle injection step before classification; replaces the existing 5-category Step 2 taxonomy with the deterministic classifier output; restructures the `file_rec` invocation around the structured context object; removes the existing free-form "synthesise context" step; explicitly handles multi-failure runs by filing one rec per failed check.
- PLAN-ci-rca-evidence-dispute -- implement the `source=ci_rca_evidence_dispute` path: register the source in `config/agent/data_quality/source_registry.yaml`, define a typed dispute schema (parent_rec_id, disputed_field, agent_value, bundle_value, evidence_for_dispute), add a `/plan` preflight section surfacing open dispute recs, and define the review-resolution flow that feeds defects back into PLAN-ci-rca-evidence-script. Prevents dispute-as-bypass by routing all disputes through `/plan` rather than allowing silent agent override.
- PLAN-ci-rca-observability-dashboard -- implement Section 7: `ops_ci_rca_telemetry` table schema, structured-log emission from `ops_data_portal.file_rec()`, preflight section update, and Athena `ci_rca_health` view. Includes the warn-mode rejection-rate alerting threshold (25% / 10% from Section 7.2).
- PLAN-sloc-promotion-to-pre -- promote `validate_sloc_limits` from presubmit to `--pre` in `scripts/validate.py`. Concrete consumer of the methodology -- exercises the why-chain conclusion in the rec-859 case study. This plan does NOT subsume rec-859 (which addresses the specific file at over 500 SLOC); it addresses the tier-placement defect that allowed the violation to escape `--pre`.
- PLAN-ci-rca-recurrence-index (deferred, optional) -- build a categorical clustering of historical recs so the agent can look up `recurrence_class=instance_of_known_pattern` against actual data rather than self-classification. Lower priority than the six above; the contract works without it but is strengthened by it.
- PLAN-ci-rca-workflow-correctness (landed) -- workflow correctness, distinct from the six depth plans above and NOT part of that set. Scope: (1) main-branch trigger gate -- adds `head_branch==default_branch` to the `rca` job `if:` so the workflow fires only on main-CI/Canary failures, not PR fast-tier failures; (2) deterministic `FILED:` filing signal -- replaces the lossy `grep -qE 'rec-[0-9]+'` gate with `scripts/ci_rca_filing.py` which matches only the explicit `FILED: rec-NNN` terminal marker from the agent's Step 6 output; (3) `ci-rca-filter` guard wired into `scripts/validate.py` presubmit tier so the trigger gate cannot silently regress. The `PLAN-ci-rca-prompt-rewrite` plan MUST preserve the `FILED:` marker contract in its rewrite of `.claude/agents/scheduled/ci-rca.md`.

## Known gaps and open questions

- **Tier-placement runtime heuristic is a snapshot.** Section 3.2 step 4 uses median runtime against the failing tree (N=3) as the proxy for "--pre eligible". A check that is fast today may be slow tomorrow; a budget regression for any `--pre` check should re-open the tier placement. The re-opening protocol is out of scope for this INTENT and should be addressed in a follow-on plan (provisional name: PLAN-tier-placement-budget-monitor).
- **Dispute path could itself become a workaround vector.** PLAN-ci-rca-evidence-dispute carves out a typed dispute schema but cannot prevent an agent from disputing routinely as an enforcement-bypass behaviour. Section 7.1 surfaces dispute-path traffic so sustained traffic produces planning context. Hard gating on dispute frequency (e.g. throttle the agent to N disputes per week) is deferred until empirical traffic data justifies it.
- **Causal-antecedence is unenforceable deterministically.** Section 5 names this explicitly. The contract enforces structural why-chain shape (length, per-entry length, terminus terminology) but cannot verify that entry K+1 is actually a causal antecedent of entry K. Quality review for causal-antecedence is handed off to `/plan-critique` and the human PR review.
- **Conflation guard is structural, not semantic.** The schema in Section 1 makes failure-category conflation harder (each rec has its own `proximate_cause` matching one failed check, and `prior_art_citation` must exist as a typed citation) but does not strictly prevent cross-references in `gap_explanation`. A separate validator that detects mention of multiple failure categories in a single rec's context object is a follow-on if Section 7 data shows conflation is still happening.
- **Evidence script S3 prefix governance.** The `s3://agent-platform-agent-logs/ci-rca-evidence/` prefix needs a lifecycle policy (retention horizon for evidence bundles), an IAM policy granting the runner write access, and a query interface so `/plan` can re-fetch bundles. These details belong in PLAN-ci-rca-evidence-script.
- **Decision 60 alignment.** The contract uses the existing two-tier vocabulary from Decision 60 (`pre`, `presubmit`) plus the CI runner from Decision 68. If Decision 60 is ever revised (e.g. introducing a third tier or merging the two), the `earliest_viable_gate` enum needs updating, the `workflow_to_tier` map needs updating, and existing evidence bundles need re-validation. The migration protocol is out of scope here; a Decision 60 revision plan would include it.
- **DECISIONS.md previously had two entries numbered Decision 72.** The duplicate was a doc-hygiene defect, now resolved (2026-06-19, decision-taxonomy-hygiene change): the "RCA-as-Plan-Source for CI Merge Gate Failures" entry retains Decision 72; the "GitHub Branch Protection Not Available" entry was renumbered to Decision 89. Cross-references in this document mean Decision 72 (RCA-as-Plan-Source for CI Merge Gate Failures) throughout.

### Residual findings from convergence-round critique (deferred to follow-on tightening)

The methodology converged across two critique rounds (architect + adversarial each, on each round). The following residual findings were surfaced in the convergence round and are documented here as planned tightening for the relevant follow-on plans rather than blockers for this INTENT.

**Tighten in PLAN-ci-rca-schema-enforcement:**

- **Override rate-limit back-pressure.** The "max 2 unresolved sibling override recs in 7 days" rate limit transfers latency onto the main filing path when `/plan` triage slips. For legitimate edge cases that genuinely need terminus overrides, this could itself become a stuck-rec failure mode -- the same anti-pattern the warn->strict feature flag was designed to prevent. The follow-on plan should add an explicit degraded-path branch: if rate limit blocks an otherwise-legitimate override, the main rec is filed WITHOUT the override AND tagged with `terminus_override_blocked=true`, surfaced as a P0 in Section 7.2.
- **`prior_art_citation` clause (ii) is the soft door.** Substring-match on `failed_check` name alone can be satisfied by always-re-citing the first historical rec for a popular validator (e.g. evergreen `rec-417` for any future `validate_sloc_limits` failure). Follow-on tightening: require clause (ii) citations to additionally be classified as non-novel themselves (i.e. cite a prior rec whose own `recurrence_class != novel`), OR drop clause (ii) entirely and rely on the bundle's deterministic `related_recs_by_category` (clause i).
- **Back-validation cost discipline.** Phase 4 back-validation may produce a large flood of audit recs if the warn-period non-conformance rate is high. Follow-on should cap audit recs at `priority=low` and at K recs per day (provisional K=20) so `/plan` queue saturation is bounded.
- **`_current` view dependency.** Citation existence lookup against `ops_recommendations_current` and `ops_decisions_current` requires those Athena views to reflect the latest Iceberg state. If the `_current` view rebuild lags `ALTER TABLE`, the existence lookup may transiently miss. Follow-on should pin the view-refresh dependency in the migration ordering.

**Tighten in PLAN-ci-rca-evidence-script:**

- **`workflow_to_tier` validator scope.** Coverage validator runs in `--pre` (sub-100ms cost), but per AGENTS.md `--pre` is advisory only; the merge gate is `presubmit`/CI. A workflow rename PR that skips local checks could land with the map out of sync, relying on the runtime miss-behaviour to degrade gracefully. Follow-on: also include `validate_ci_rca_taxonomy` in the `presubmit` tier (still trivial cost) so the merge gate covers it.
- **Sample dispersion threshold provenance.** N=5 + drop-extremes + 50% dispersion threshold has the same lack of empirical calibration as Section 7.2's rejection-rate thresholds. The tuning rec mandated by PLAN-ci-rca-observability-dashboard should revisit dispersion alongside rejection rates.
- **Multi-platform hash drift.** Canonical JSON spec is robust for Python-only implementations but does not cover float-formatting edge cases (NaN, Infinity, integer-vs-float) or Unicode normalisation. Follow-on plan should land a fixture-based hash-stability test asserting identical hashes across edge-case values. RFC 8785 (JCS) is the formal reference; Python `json.dumps` with the specified flags approximates it but is not a strict equivalent.
- **Multi-failure forward-progress.** "Sequential, not transactional" multi-failure filing means partial-failure state must be visible to the next agent invocation. Follow-on: add `expected_sibling_count` field to each multi-failure rec, plus a Section 7 gauge "recs with sibling-count mismatch", so partially-filed batches are surfaced for human reconciliation.

**Tighten in PLAN-ci-rca-observability-dashboard:**

- **Phase 4 promotion-gate threshold (5%) is also empirically ungrounded.** Section 7.2 acknowledges the 25%/10% alert thresholds are starting heuristics, but the Phase-4 promotion gate at <5% inherits the same lack of calibration data. The first tuning rec must include the promotion gate alongside the alert thresholds.
- **Demotion-rec silencing guard.** Section 6 auto-files a `ci_rca_strict_mode_demotion` rec when the flag is flipped back to warn, but nothing prevents a future agent from filing a counter-rec proposing to silence the demotion-rec class, or a human from closing it without acting. Follow-on: add `validate_ci_rca_strict_mode_demotion_history` check that fails CI if `CI_RCA_STRICT_MODE=warn` AND an open `source=ci_rca_strict_mode_demotion` rec is older than 30 days.

**Operational notes (no follow-on plan required):**

- **CI_RCA_STRICT_MODE restart implication.** The flag is read at portal process start with no hot-reload. After flipping in `terraform apply`, the portal process must be restarted to observe the new value. Decision Record reviewers should be aware of this operational step.
- **schema_version zoo growth.** "All schema_version <= current_portal_version are accepted indefinitely" prevents implicit deprecation but allows long-tail version coexistence. Expectation: schema bumps no more often than once per quarter; if cadence accelerates, audit the schema design for stability.
- **ASCII-only canonical JSON.** The `ensure_ascii=True` flag in the canonical JSON spec rules out non-ASCII content in future bundle fields. Field additions that need Unicode (rare, but possible) require a schema_version bump and a migration to a Unicode-safe canonicalisation.
