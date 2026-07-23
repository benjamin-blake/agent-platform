# Audit: validate.py, check corpus, test suite, fast-tier selection, dependency declarations

Audited commit: `origin/main` @ `4df4d48` (2026-07-23). System of record:
`audits/validate-test-suite-4df4d48.yaml` (23 findings: 15 novel, 2 planned-insufficient,
6 planned-unbuilt; 11 rejected candidates with named controls). This file is the executive layer.

## Verdict in one paragraph

This validation path is genuinely strong for a sole-developer platform: the single-source-of-truth
invariant is real in both directions (workflows call `validate.py`; `validate.py` checks guard the
workflows' shape), registration coherence is machine-verified, hermeticity is layered and
meta-checked, and the Decision-135 affected-set upgrade demonstrably closed the escape classes that
motivated it - of 20 recent `ci_rca` recs, exactly one is a post-135 selection escape, and it was a
LOUD cap deferral, not silence. The PR gate is fast in production (median 1.8 min over 15 sampled
runs, budget 5 min). The residual weaknesses concentrate in three places: two SILENT recall holes in
the selection's candidate admission (the critical one: `tests/fixtures/**` edits select zero tests),
a set of gates that are believed to assert but structurally cannot (the per-changed-file coverage
gate is inert in every CI context; two prompt checks glob paths deleted at T-1.13), and a
28-33-minute post-merge tier whose dominant cost (serial pytest) is a one-line fix away from roughly
half its latency.

Maturities: S1 validate.py **strong** | S2 check corpus **strong** | S3 test suite **strong** |
S4 affected-set selection **solid** | S5 CI path **strong** | S6 dependency declarations **strong**.
No surface reaches frontier: the global Q5 checklist has three missed properties (coverage-at-merge,
type gating, dead-test detection) - all three are known-territory (CD.30/T3.7, VTS-15) rather than
surprises.

## The five highest-leverage changes

1. **VTS-01 (critical, novel) - admit tests-tree helper modules to the import-closure channel.**
   `_is_changed_source_py()` admits only `src/`+`scripts/` paths, so a PR that only edits
   `tests/fixtures/ducklake_fakes.py` (the repo's *sanctioned* shared-helper home, imported by 8+
   test files) selects ZERO tests - traced live: no selection, no deferral, no warning. This is the
   one silent under-selection below the true blast radius in the system, the exact property NS-D
   rules out. One-line candidate-class widening; strictly additive; effort S.

2. **VTS-03/VTS-04 (high/medium, owned by rec-2731/rec-2737) - root-conftest scope forcing +
   channel-priority residue ordering.** A `tests/conftest.py` edit correctly hits all 363 test
   modules but the cap keeps the first 35 *alphabetically* and defers 328 - rec-2725 is the realized
   escape (canary red from an autouse-fixture change). This audit supplies the verification
   rec-2731 asked for: the channel covers the root, the cap truncates it to 9.6%. Force full-suite
   scope on root-conftest diffs; order residue mirror>conftest>transitive before truncating.

3. **VTS-07 (high, planned-insufficient: CD.30/T3.7 + rec-2791) - the per-changed-file coverage
   gate cannot fire in CI.** `validate_test_coverage` is registered only in the full tier, where
   every CI checkout has an empty merge-base diff ("No source file changes to check", every run);
   it is absent from `--pre` where the diff exists; and its per-file leg is separately vacuous for
   all `scripts/` files (rec-2791's slash-form `--cov` defect). CD.30 *premises* this gate as
   operating while planning to replace it. Sequence: fix slash-form, land the CD.30 diff-line
   ratchet, register it in `--pre`, drop the inert full-tier dispatch. Until then, the only
   operating coverage gate is the global `fail_under=37` over `src/` only - `scripts/`, the
   platform machinery, has no coverage measurement at all.

4. **VTS-10 + VTS-13 (medium, novel) - parallelize and time-bound the full-tier pytest.** The
   fast tier runs xdist with a fixed seed and `--timeout 60`; the full tier runs serial, unseeded
   (fresh random order every CI run - no cache persists), untimed. The full validate step is 27.7
   min observed; the suite is the dominant share. `-n auto` + fixed seed (rec-2653's proven
   pattern) + `--timeout 120` is a one-command-line change with `validate_hermeticity_flags`
   updated in lockstep. Post-merge signal latency roughly halves; ~18-20 full-tier runs/day
   benefit.

5. **VTS-05 + VTS-06 (medium) - make the selection's miss rate observable and its record
   trustworthy.** Decision 135's reversal condition (a) keys on a defer/escape rate that nothing
   measures: the manifest records deferrals per-run, but its consumer is deferred to T2.36 behind a
   trigger ("first written cross-run query") that presupposes the very query the condition needs.
   Cheapest standing fix: have ci-rca stamp post-merge pytest failures with whether the failing
   module sat in the merge's `deferred[]` (escape attribution from the recs cache alone). And
   first, VTS-06: orchestrator tests currently CLOBBER the real
   `logs/debug/selection-manifest.json` with fixture data (observed artifact: `sha:
   "agent/test-branch"` on a real feat PR) - exactly on selector-touching PRs. Fix is the existing
   `_isolate_plans_jsonl` autouse-fixture pattern applied to the manifest path; effort XS.

## What was checked and held up

The tier split (Decision 60/73) is deliberate and healthy; both-tier double execution of whole-tree
checks is *justified* - rec-2749/2762 show the full tier catching merge unions that per-PR runs
cannot see. The facade/three-place add ritual is machine-guarded pre-merge (its historical churn
mode was already redesigned away via growth-safe floors). The batched collect-only partitioning,
heavy-dep deferral classifier, loud fallback-to-edited-set, and manifest output-only invariant all
verified as designed. The pip cache works (89s full install observed - the "torch never cached"
hypothesis was tested and rejected). Eleven candidates were dismissed with named compensating
controls, including canary same-SHA reruns (that IS the drift canary's purpose) and the
live/cacheless selection design (KG.13's deferral, undisturbed).

Corpus hygiene findings beyond the top five: two prompt checks are permanent no-ops globbing paths
T-1.13 deleted while five live prompts in `.github/prompts/scheduled/` go unvalidated - one of the
two is dispatched twice in the full tier with a test pinning the duplication (VTS-08, rec-2396);
`validate_requirements` spends a measured 35.4s on 32 serial PyPI calls inside the blocking
post-merge gate - a PyPI outage reds main (VTS-14); `validate_imports` spends 16.1s re-proving what
pytest collection proves (VTS-23); the full-tier ruff sweep omits `scripts/` entirely (VTS-18,
rec-2342); ~28s of every `--pre` is whole-tree governance checks that ignore the diff (VTS-09); the
23 open budget-breach recs (all local, dominant phase `pytest_diff`) accumulate with no consumer
(VTS-20); and mypy is advisory in both tiers with 143 standing errors and no decision owning that
status (VTS-15).

## Q6 - vocabulary recommendation

**"coverage": disambiguate in place; do not wholesale-rename.** Three semantics share the word:
pytest-cov CODE coverage, VERIFIER coverage (`--coverage`, `run_coverage_check`, the
`coverage_report` scaffold), and per-changed-file TEST coverage (`validate_test_coverage`). The
sharpest hazard is that the *selection mirror-map* (`map_source_to_test`, Decision 135 channel 3)
lives inside coverage-named `test_coverage_checker.py`. Rename only the verifier-coverage surfaces
(`--coverage` -> `--verifier-coverage` with an alias; scaffold -> `verifier_coverage_report`; blast
radius grepped: validate.py + one docstring + two one-line test tuples), and relocate the mirror map
when CD.30 rewrites `test_coverage_checker.py` anyway. **"validate": leave as is** - the
`validate.py` + `validate_*` corpus is one subsystem whose prefix is the convention; the single
stray, `scripts/validate_telemetry.py` (zero importers, dormant Athena-era tool), takes its
disposition with the T2.36 telemetry rebuild.

## Q7 - dependency-declaration options (deliberately not chosen)

Current state is more coherent than it looks: roles documented in-file, Dependabot grouped sync,
lockfile membership gated, and the fast-tier heavy-set *derived at runtime* from
(requirements.txt - requirements-fast.txt), so membership drift self-corrects loudly. Warts: dev
tools live in `requirements.txt` while `requirements-dev.txt` holds CI extras; the lock is
sync-checked but installed by nothing; `pytest-picked` is dead in both files (VTS-16).

- **Option A - role-true four-file set (S):** move dev tools to the dev file; runtime-only
  `requirements.txt`. Excluded-set derivation is UNAFFECTED (dev tools are in the fast file, so
  they never contributed to full-minus-fast); pip cache keys must add the dev/fast hashes
  (subsumes rec-2304) or the stale-layer class persists.
- **Option B - pyproject `[project]` + extras (M):** single standard SoT; highest coupling -
  `_excluded_heavy_import_names`/`_parse_requirement_dist_names` read the two .txt PATHS and must
  be rewritten against extras; all three workflows and the lockfile-sync check re-point; Dependabot
  follows pyproject.
- **Option C - lock-driven CI installs (S-M):** main/canary install from `requirements.lock`
  (giving the lock a live role); cache key becomes content-correct automatically; excluded-set
  derivation unchanged (the lock is an install source, not a declaration surface). COST: the
  canary's fresh-resolution drift detection inverts onto Dependabot PRs - a semantic change to
  Decision 73's L8 role that needs its own decision.

## Empirical basis

Per-check wall-clock measured for all 81 dispatchable checks (one in-process run each; two
live-AWS/network checks timed separately); five derive-level selection traces + two deletion traces
executed against the real tree; two production selection manifests sampled (one healthy: 31
selected across all four channels in 4.5s; one clobbered: VTS-06); 15 pr-validate runs (median 1.8
min) and 10 main-validate/canary runs (28-33 min; validate step 27.7 min; install 89s) sampled from
Actions; 20 recent ci_rca recs classified against the selection counterfactual (1 post-135 escape,
loud-deferral class); full suite timed once with `--durations=25`
(6885 passed / 2 skipped / 17 deselected in 35:14 serial; top durations are independent 24-40s
tests - a ~27s-each preflight cluster alone is ~7 min serial; "Required test coverage of 37.0%
reached. Total coverage: 74.59%" - the floor enforces but never binds); `validate --pre` timed
once on a near-empty diff (31.0s, all check-block). Container timings are used for ranking only;
CI-observed numbers are authoritative (see `meta.contract_notes`).
