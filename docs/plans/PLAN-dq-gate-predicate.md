# Plan

## Intent

Close two of the four remaining enforcement gaps documented in
`PLAN-audit-ops-recs-dq-scalability.md` (Gaps 3 and 6) and repair the
data-quality runner's silent ERROR-on-empty failure mode. After this plan, the
postflight gate fails closed when DQ data is stale or when the plan's scope
intersects any verifier's covered files - removing two of the silent-pass paths
the audit flagged. Carries the DQ enforcement layer from "wired but narrow"
toward the audit's stated convergence target of "definition equals enforcement."

## Plan Type

IMPLEMENTATION

## Verification Tier

V3

## Branch

agent/dq-gate-predicate

## Phase

Phase Platform - verification system maturation (parallel to Phase 2 schema
backfill).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| scripts/data_quality_runner.py | Modify | Diagnose and fix the silent-empty-result path that produced `dq-latest.json` with `total=0`/`verdict=ERROR`. Apply a minimal guard so an empty all_checks list cannot reach `_save_latest_result`, or so `_save_latest_result` cannot be called with zero results except when the runner intentionally errored. |
| scripts/verifiers/harness.py | Modify | Add `covers: list[str]` class attribute on the `Verifier` base class with default `["**"]` (everything). Add a small helper for plan-scope intersection used by postflight. |
| scripts/verifiers/data_quality.py | Modify | Gap 3: change the stale-report path (>1h) from `SKIPPED, ADVISORY` to `FAIL, HARD_GATE`. Declare `covers` enumerating files that warrant a DQ run on change (data_quality YAMLs, the runner itself, write-side modules, ops portal). |
| scripts/verifiers/outbox_health.py | Modify | Declare a `covers` list (ops_data_portal.py and outbox-related code) so the new postflight predicate has signal for this verifier. One-line additions only; behaviour unchanged. |
| scripts/verifiers/schema_integrity.py | Modify | Declare a `covers` list (Pydantic/jsonl_store models, ops_data_portal.py). Behaviour unchanged. |
| scripts/verifiers/causal_chain.py | Modify | Declare a `covers` list (telemetry session/phase/step modules). Behaviour unchanged. |
| scripts/executor/postflight.py | Modify | Gap 6: replace the V3-only gate predicate (`if is_v3 and severity == HARD_GATE`) with a coverage-based predicate ("does any covered glob in the failing verifier intersect the plan's scope?"). Tier-aware behaviour is preserved as a fallback when plan scope is unavailable. |
| tests/test_verifiers/test_harness.py | Modify | Cover the new `covers` attribute and the intersection helper. (`tests/test_verifier_harness.py` is a redirect shim - canonical tests live in the package directory.) |
| tests/test_data_quality_runner.py | Modify | Cover the runner ERROR-on-empty fix and the verifier's stale->FAIL transition. |
| tests/test_executor_postflight.py | Modify | Cover the new coverage-based gate predicate (V2 plan with intersecting scope is gated; V1 plan with non-intersecting scope passes through advisory). |

## Bundled Recommendations

None. The audit's candidate recs (rec-CANDIDATE-3, rec-CANDIDATE-6) were
deliberately not filed via the portal at the human's direction; this plan
references them by audit section heading rather than by rec ID.

## Acceptance Criteria

- [ ] Running `python -m scripts.data_quality_runner --file config/data_quality/ops.yaml --json` against existing YAML produces a result with `total > 0` and writes `logs/debug/dq-latest.json` matching that count.
- [ ] When `logs/debug/dq-latest.json` is absent or older than 1 hour, `DataQualityVerifier.verify()` returns `status == FAIL` and `severity == HARD_GATE` (not SKIPPED/ADVISORY).
- [ ] When `logs/debug/dq-latest.json` has `total == 0`, `DataQualityVerifier.verify()` returns `status == FAIL` and `severity == HARD_GATE` (preserves the Gap 1 fix from PR #285).
- [ ] `Verifier` base class exposes a `covers: list[str]` class attribute with default `["**"]`.
- [ ] `DataQualityVerifier.covers`, `OutboxHealthVerifier.covers`, `SchemaIntegrityVerifier.covers`, and `CausalChainVerifier.covers` each declare a non-default glob list.
- [ ] `_run_verifiers_gate()` in `scripts/executor/postflight.py` no longer references `is_v3` as a precondition for blocking. The blocking decision is now based on whether the failing verifier's `covers` intersects the plan's `Scope` table file paths.
- [ ] A V2 plan whose Scope contains `scripts/ops_data_portal.py` produces a blocking gate result when `DataQualityVerifier` returns FAIL.
- [ ] A V1 plan whose Scope contains only `docs/foo.md` produces a non-blocking gate result when `DataQualityVerifier` returns FAIL (advisory).
- [ ] `python -m scripts.validate --ci` returns exit code 0.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm DQ runner produces a non-empty result against a real YAML file | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml --dry-run --json` | JSON output contains `"total"` field with value > 0 (dry-run prints planned checks; real run requires SSO) | Runner still emits `total=0`. Trace the path in `main()` between `load_checks` and `_save_latest_result` and apply a guard. |
| 2 | [pre-deploy] | Confirm `dq-latest.json` written by the dry run reflects non-zero check count | `.venv/Scripts/python.exe -c "import json,pathlib;d=json.loads(pathlib.Path('logs/debug/dq-latest.json').read_text());print('total=',d['total'],'verdict=',d['verdict']);assert d['total']>0,'expected non-zero total'"` | Prints e.g. `total= 17 verdict= SKIP` and exits 0 | Fix `_save_latest_result` so it cannot persist a misleading total/verdict combination. |
| 3 | [pre-deploy] | Verify `Verifier` base class exposes `covers` with default `["**"]` | `.venv/Scripts/python.exe -c "from scripts.verifiers.harness import Verifier;assert getattr(Verifier,'covers',None)==['**'],f'covers default wrong: {getattr(Verifier,chr(34)+chr(99)+chr(111)+chr(118)+chr(101)+chr(114)+chr(115)+chr(34),None)}';print('OK Verifier.covers default present')"` | Prints `OK Verifier.covers default present` | Add the class attribute on `Verifier` in `scripts/verifiers/harness.py`. |
| 4 | [pre-deploy] | Verify `DataQualityVerifier` declares a non-default `covers` list | `.venv/Scripts/python.exe -c "from scripts.verifiers.data_quality import DataQualityVerifier;c=DataQualityVerifier.covers;assert c!=['**'] and 'config/data_quality/**' in c,f'unexpected covers: {c}';print('OK DQ covers:',c)"` | Prints `OK DQ covers: [...]` listing data_quality globs | Override the `covers` attribute on `DataQualityVerifier`. |
| 5 | [pre-deploy] | Verify stale `dq-latest.json` returns FAIL HARD_GATE (Gap 3) | Run the targeted test: `.venv/Scripts/python.exe -m pytest tests/test_data_quality_runner.py::TestVerifierStalePolicy::test_stale_dq_returns_fail_hard_gate -v` | `1 passed` | Stale path in `scripts/verifiers/data_quality.py` still returns SKIPPED/ADVISORY. Update the >1h branch. |
| 6 | [pre-deploy] | Verify empty `dq-latest.json` (total=0) still returns FAIL HARD_GATE (Gap 1 regression check) | `.venv/Scripts/python.exe -m pytest tests/test_data_quality_runner.py::TestVerifierStalePolicy::test_empty_total_returns_fail_hard_gate -v` | `1 passed` | The Gap 1 short-circuit at line 71-77 has regressed; restore. |
| 7 | [pre-deploy] | Verify postflight gate uses coverage predicate, not is_v3 (Gap 6) | `.venv/Scripts/python.exe -m pytest tests/test_executor_postflight.py::TestCoveragePredicate::test_v2_intersecting_scope_is_gated -v tests/test_executor_postflight.py::TestCoveragePredicate::test_v1_non_intersecting_scope_passes -v` | `2 passed` | The predicate in `_run_verifiers_gate` still references `is_v3`. Replace with the intersection helper. |
| 8 | [pre-deploy] | Confirm full local validation suite passes | `.venv/Scripts/python.exe -m scripts.validate --ci` | Exit code 0 | Address whatever validate.py reports (lint, type, tests, boundary checks). |
| 9 | [pre-deploy] | Behavioural integration: synthetic V2 plan with covered scope is blocked when DQ FAILs | `.venv/Scripts/python.exe -m scripts.verifiers.harness --json` against a fixture where `dq-latest.json` is stale and a temporary plan file declares `verification_tier: V2` and `Scope` listing `scripts/ops_data_portal.py`. Wrap in a single test: `.venv/Scripts/python.exe -m pytest tests/test_executor_postflight.py::TestCoveragePredicate::test_integration_v2_blocked -v` | `1 passed` (the integration test asserts `_run_verifiers_gate` returns False) | Predicate is firing on intersection but the wiring into `_run_verifiers_gate` did not pick up the result. Trace the result-iteration loop. |

VP rationale: each step exercises a real code path. Step 1 catches the runner
silently no-op'ing. Step 2 catches `_save_latest_result` writing misleading
metadata. Steps 3-4 catch the new attribute being absent or wrongly defaulted.
Steps 5-6 catch regressions in the verifier's branch logic. Step 7 catches the
predicate replacement. Step 8 catches anything else validate.py covers
(coverage, boundary, ruff, pyright, etc.). Step 9 is the end-to-end behavioural
proof that ties the predicate to the gate.

## Constraints

- This plan does not modify any `.tf` files or Lambda-packaged files; no
  Infrastructure or Lambda Deployment workflow steps required.
- Stale-DQ policy is option (a) from the audit (FAIL HARD_GATE on stale).
  Option (c) (trust a scheduled routine) is recorded as Future Direction
  below and is explicitly Session E scope.
- Recommendation: file no portal recommendations from this plan. The audit's
  candidate rows are referenced by section heading rather than rec ID, per
  the human's direction.
- No rescue agents or workaround loops (Decision 55).
- Single Portal Invariant: any persistence touched here writes through
  `scripts/ops_data_portal.py` only. This plan does not touch the
  `.recommendations-log.jsonl` or `.decisions-index.jsonl` files.
- DataQualityVerifier remains the only authority on stale/empty policy;
  postflight does not duplicate the freshness check. Postflight only
  decides whether a FAIL result is blocking based on coverage intersection.

## Context

### Source documents and prior landings

- Audit: `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (this plan
  closes the Session B portion: Gaps 3 + 6).
- Session A (Gaps 1, 4, 5): `docs/plans/PLAN-dq-harden-gaps-1-4-5.md`,
  PR #285, commit f9be47d. Established the `total == 0 -> FAIL HARD_GATE`
  short-circuit at `scripts/verifiers/data_quality.py:71-77`. This plan
  preserves that behaviour and tests for its presence.
- `docs/INTENT-verification-system.md`: Layer 1/2/3 quality pyramid; this
  work operates at Layer 2 (read-side YAML checks compiled to Athena SQL).
- Decision 48 (Verification Tier Design): V1 static, V2 unit, V3 integration.
  This plan is V3 because the gate predicate must be proven against
  synthetic plan scopes, not by mocked unit logic alone.
- Decision 51 (Local-First Outbox + Bidirectional Sync): the persistence
  pattern referenced in the Future Direction below.
- Decision 55: No rescue agents; failures must be diagnosed at root cause.
- Decisions 36, 37: Company SCP blocks IAM users and external OIDC.
  Constraint that drives the Future Direction architecture below.

### Current observed state

`logs/debug/dq-latest.json` at session start (2026-05-04T19:01):
`{"verdict":"ERROR","total":0,...}`. The runner main() either filtered all
checks to empty or `_save_latest_result` was called from a path that had no
results. This is the silent-pass path Gap 1 was meant to detect, and after
the Gap 3 fix the same state will trip the stale or empty gate. Diagnosis
is the first ordered execution step.

### Future Direction (Session E preview - OUT OF SCOPE for this plan)

The audit's preferred end-state for stale-DQ policy is option (c): a
scheduled routine keeps `dq-latest.json` fresh, and the verifier trusts
freshness without forcing operator action. Session B uses option (a)
(stale -> FAIL HARD_GATE) as a transitional state. Session E will
implement option (c).

The architecture recorded for Session E planning:

```
Claude Code routine (cron, Anthropic-hosted)
    -> gh workflow run dq-check.yml
        -> AWS-hosted self-hosted GitHub Actions runner
           (small EC2: t3.small or t3a.small, one tier above micro;
            IAM ROLE attached via instance profile - SCP-compliant
            because it is a role not a user, same legal pattern as
            Lambda execution roles per Decisions 36 and 37)
            -> .venv/Scripts/python.exe -m scripts.data_quality_runner
            -> git commit logs/debug/dq-latest.json
            -> gh pr create
    -> routine auto-merges the PR
    -> existing main-branch drain syncs result to S3
       (Decision 51 Local-First Outbox + Bidirectional Sync,
        analogous to scripts/ops_data_portal.py)
    -> DataQualityVerifier reads via the cached path
```

Constraints driving this shape:

1. SCP blocks IAM user creation (Decisions 36, 37). EC2 instance profiles
   use IAM **roles**, not users, and are therefore allowed - the same legal
   model that Lambda execution already rides on.
2. SCP also blocks external OIDC providers, ruling out GitHub Actions
   OIDC-to-AWS federation. Instance profile is the cleanest remaining path.
3. Lambda-based scheduled agents disabled May 2026 (commit bf88fd0). Path
   forward is Claude Code scheduled routines for orchestration; an EC2
   runner replaces the Lambda dispatcher as the AWS-side execution surface.
4. Claude Code routines run in Anthropic's cloud with no AWS credentials of
   their own. They have GitHub auth and can trigger workflows via `gh
   workflow run`, then auto-merge mechanical PRs.
5. Auto-merge of a single mechanical JSON file is bounded-blast-radius
   (a bad `dq-latest.json` produces a spuriously red gate, easily reverted).
   Code-changing routines require separate authorisation gates and must
   not piggyback on this lane.

Cutover from Session B (a) to Session E (c) is one diff in
`scripts/verifiers/data_quality.py`: when the routine is proven to keep
`dq-latest.json` fresh, change the stale-path return from
`FAIL/HARD_GATE` back to `PASS` (or skip with non-blocking advisory). Tracked
as a graduation step in the Session E plan.

Decisions still to be made in Session E planning (not in this plan):

- EC2 instance class confirmation (t3.small vs t3a.small, region eu-west-2,
  AZ).
- Runner registration token rotation strategy.
- PR auto-merge guardrails (require GH check status? require single-file
  diff scope? require `dq-latest.json`-only allowlist?).
- DQ run frequency (hourly? every 4h? aligned with priority queue curator?).
- Drain mechanism specifics: reuse `scripts/ops_data_portal.py` outbox
  pattern verbatim, or carve out a sibling drainer for telemetry-style
  artefacts.

### Sibling sessions (not bundled here)

- Session C (PLAN-dq-validate-integration.md): Gap 2 - `validate.py
  --integration` flag and CI wiring.
- Session D (PLAN-dq-enforced-ratchet.md): RATCHET - `enforced` field
  schema, graduation guard in validate.py, eventual deletion of the
  `enforced` field. STRATEGIC plan.
- Session E (PLAN-dq-scheduled-routine.md): Future Direction above.
  Likely STRATEGIC because it spans Terraform, runner registration,
  Claude Code routine config, and PR auto-merge guardrails.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (this plan is on `agent/dq-gate-predicate`).
- [x] docs/PROJECT_CONTEXT.md read (during planning session).
- [x] DECISIONS referenced (36, 37, 48, 51, 55).
- [x] All files in Scope table located and readable.
- [x] Acceptance Criteria understood and verifiable via the Verification Plan commands.
- [x] Audit (`PLAN-audit-ops-recs-dq-scalability.md`) read end-to-end.
- [x] Session A artifact (`scripts/verifiers/data_quality.py:71-77`) inspected to confirm Gap 1 fix is preserved.

## Ordered Execution Steps

1. **Diagnose DQ runner ERROR root cause.** Read `scripts/data_quality_runner.py`
   `main()` end-to-end. Trace every path that can lead to `_save_latest_result`
   being called with `len(result.results) == 0`. Identify whether the trigger
   was the early-return path, a filter that emptied `all_checks`, the boto3
   import-fallback path, or some other route. Record the diagnosis (one or
   two lines) in the commit message of the fix.

2. **Apply minimal fix to `scripts/data_quality_runner.py`.** Add a guard so
   the runner cannot persist a misleading `total=0/verdict=ERROR` summary
   without making clear *why* the run produced zero results. Acceptable
   shapes: refuse to write the file at all when no checks were attempted;
   distinguish "no YAMLs loaded" from "all YAMLs loaded but filters excluded
   all checks" from "boto3 unavailable so checks were skipped"; or write
   a `verdict` value that the verifier interprets unambiguously. Update
   `tests/test_data_quality_runner.py` with at least one regression test.

3. **Add `covers` attribute to `Verifier` base class.** In
   `scripts/verifiers/harness.py`, add a class-level `covers: list[str]`
   defaulting to `["**"]`. Add a small intersection helper (a static method
   or module-level function) that takes a list of `covers` globs and a list
   of plan-scope file paths and returns True iff any glob matches any
   path. Use `fnmatch.fnmatch` (stdlib) for glob matching to avoid a new
   dependency. Update `tests/test_verifiers/test_harness.py` (canonical;
   `tests/test_verifier_harness.py` is a redirect shim).

4. **Declare `covers` on existing concrete verifiers.** In each of
   `scripts/verifiers/data_quality.py`, `outbox_health.py`,
   `schema_integrity.py`, `causal_chain.py`, declare a non-default `covers`
   list of file globs the verifier cares about. Suggested initial values:
   - DataQualityVerifier: `["config/data_quality/**", "scripts/data_quality_runner.py", "scripts/ops_data_portal.py", "src/data/**"]`.
   - OutboxHealthVerifier: `["scripts/ops_data_portal.py", "logs/.ops-outbox/**", "scripts/sync_ops.py"]`.
   - SchemaIntegrityVerifier: `["scripts/executor/jsonl_store.py", "scripts/ops_data_portal.py", "config/data_quality/**"]`.
   - CausalChainVerifier: `["scripts/executor/telemetry.py", "scripts/executor/postflight.py", "logs/.telemetry-active-session.json"]`.

5. **Modify `DataQualityVerifier.verify()` stale-path return value.** In
   `scripts/verifiers/data_quality.py` lines 56-62, change the >1h branch
   from `status=SKIPPED, severity=ADVISORY` to `status=FAIL,
   severity=HARD_GATE`. Update the message to make the remediation explicit
   (e.g., "Run `.venv/Scripts/python.exe -m scripts.data_quality_runner` to
   refresh `logs/debug/dq-latest.json`."). Update
   `tests/test_data_quality_runner.py` with `TestVerifierStalePolicy::test_stale_dq_returns_fail_hard_gate`
   and `TestVerifierStalePolicy::test_empty_total_returns_fail_hard_gate`.

6. **Replace the gate predicate in `scripts/executor/postflight.py`.** In
   `_run_verifiers_gate()` lines 982-1006, replace the `if is_v3 and
   res.severity == VerifierSeverity.HARD_GATE` branch with a coverage-based
   predicate. Read the plan's Scope table file paths via the existing
   `ExecutionPlan` loader (or a small helper that parses the markdown Scope
   table; see `_extract_scope_files` in `scripts/executor/plan.py:756` for
   the existing parser). Block iff the verifier's `covers` intersects the
   plan's scope. When the plan or its scope cannot be loaded, fall back to
   the previous V3-only behaviour so the gate degrades safely rather than
   over- or under-blocking. Preserve the broad-`except Exception` outer
   wrapper but ensure the `verification_gate_error` process event still
   fires.

7. **Update postflight tests.** In `tests/test_executor_postflight.py`, add
   `TestCoveragePredicate` with at least three cases:
   - `test_v2_intersecting_scope_is_gated`: V2 plan whose Scope contains a
     covered path; DQ FAILs; gate returns False.
   - `test_v1_non_intersecting_scope_passes`: V1 plan whose Scope contains
     only a non-covered path (e.g., `docs/foo.md`); DQ FAILs; gate returns
     True.
   - `test_integration_v2_blocked`: end-to-end synthetic plan + stale
     `dq-latest.json` fixture; assert `_run_verifiers_gate` returns False.

8. **Run `python -m scripts.validate --ci`.** Address any failures (lint,
   typing, coverage, boundary, etc.) before proceeding.

9. **Execute Verification Plan.** Run each VP step. Loop on failures until
   each passes. If a step fails unrecoverably, stop and analyse root cause
   per Decision 55 (no workaround loops).

10. **Report.** Summarise: which file changes landed, which acceptance
    criteria pass, the runner diagnosis from step 1, and which VP steps
    passed. Do not modify the audit's Implementation Progress section in
    this plan; the audit itself will be updated in a follow-up commit when
    the PR merges.
