# CI-RCA Subsystem Audit -- a49db8f

Companion to `audits/ci-rca-system-a49db8f.yaml`. 10 findings: 1 critical, 3 high, 5 medium, 1 low.

## Verdicts

| Q | Verdict |
|---|---|
| Q1 guarantee in force | **not_in_force** |
| Q2 loop closes | **partial** |
| Q3 deterministic/model division | **weak** |
| Q4 contract coherence | **drifting** |
| Q5 frontier benchmark | **weak** (one `missed`: flake/quarantine) |
| Strict flip | **flip_strict_after_fix** |
| Maturity | S1 strong, S2 frontier, S3 solid, S4 strong -- **overall solid** |

## The headline finding (CIRCA-01, critical)

The bundle-wins cross-check -- checks 1-4 plus SHA-256 verification, the mechanism the
roadmap calls "load-bearing" (c8/c10/c11 met) -- **never executes at the production call
site**. `_load_and_verify_bundle` searches only `CI_RCA_BUNDLE_LOCAL_PATH` (set nowhere)
and `logs/.ci-rca-evidence-pending/` (written only on S3 upload *failure*). CI emits
bundles to `/tmp/ci-rca-bundles` and uploads succeed (`bundle_upload_backlog=0`), so the
portal's local load returns None and `_run_ci_rca_cross_check` returns at
`ops_data_portal.py:439` -- in warn *and* strict. The unit tests pass by seeding the
pending dir, i.e. seeding exactly what production never has; one test pins the skip as
intended. Corroboration: zero `cross_check_check_N` stamps across all 125 corpus recs
(consistent with, though not proof of, the dead path -- agents are instructed to mirror,
so the code trace is the dispositive evidence). Consequence: the deterministic-over-LLM
guarantee currently holds by *prompt obedience*, the exact trust model the spine was
built to remove, and **flipping the flag would not change that**. Fix is small: wire the
emit-dir into the portal lookup (env var or search path) plus one integration test.
This is the highest-leverage change in the audit.

## Q1 -- why not_in_force, and why the flip is still reachable

Warn mode accepted 21/48 writes it was designed to reject over the last 7 days (0.4375,
re-derived; 9x the 0.05 promotion gate). The only hard gates that actually fire in
production are peripheral (source-file non-empty, dispute shape, SHA mismatch on a path
never reached). Two further latent holes mean even strict mode under-delivers: the
legacy path -- `source=ci_rca` with no `context_v2_json` -- is accepted in *both* modes
(CIRCA-02, contradicting INTENT Section 4 check 1's "hard reject"), and upload-failed
bundles emit `s3_uri=""` which fails the `^s3://` schema pattern, making evidence-carrying
recs unfilable under strict exactly during S3 degradation (CIRCA-06).

The good news: I decomposed the 21 warn-rejects offline (in-process re-validation, no
portal calls). They are **10x why_chain entry-length overruns (>250 chars), 8x
terminus-keyword misses, 1x missing citation**. This is prompt/schema calibration, not
depth failure -- the agent writes 260-330-char why-entries against a 250 ceiling set
before any empirical data existed. Warn is not a structural trap; it persists because
nothing owns convergence (CIRCA-04): the marker records only "schema_deficiency" with no
per-rule detail, back-validate is report-only and unscheduled, and the INTENT's tuning
rec is gated on Phase-4 data that never arrives while the rate is high.

**Strict-flip decision: flip after four named fixes** -- (1) wire the bundle path
(CIRCA-01, S), (2) close the legacy bypass in strict (CIRCA-02, S), (3) allow empty
`s3_uri` iff `upload_status=upload_failed` (CIRCA-06, XS), (4) calibrate the prompt
against the observed reject decomposition and/or raise the per-entry ceiling via
schema_version bump, then re-measure one 7-day window (CIRCA-04, S). One focused plan,
no new infrastructure. `keep_warn` loses because the rate demonstrably does not converge
on its own; `flip_strict_now` loses because it rejects ~44% of real filings for
mechanical reasons while delivering less enforcement than advertised.

## Q2 -- the loop closes case-by-case but does not prevent

Overturning candidate C3 was the audit's most useful empirical result: the prompt claimed
the test-count storm *continued after* the preventive guard (PR #478) landed. Timing says
otherwise -- the guard merged 2026-07-05T20:42Z; the newest rec on that file is 19:30Z the
same day, with zero recurrence since. The preventive_action pathway *worked*. What the
storm actually demonstrates is CIRCA-03: no write-time dedup anywhere -- the workflow
dedup anchors per-commit and per-workflow-slug, so a persistently red main filed 14
duplicate Critical recs in ~6 hours for one root cause, each hard-blocking `/plan`
(Decision 73 L5), all still open and requiring manual closure. The codebase already owns
the right pattern -- terraform-apply-sandbox anchors refusals-while-red to the red
record's commit -- but for one workflow only. Generalising that anchoring (or an open-rec
lookup before dispatch) is the second-highest-leverage change. The missing `concurrency:`
block is real but secondary: the observed storm is per-commit churn, not a dispatch race.

## Q3 -- sound design, instruction-grade enforcement

The division of labour places the right facts on the deterministic side, but (a) the
adjudication layer is dead (CIRCA-01), and (b) the deterministic side itself feeds a
wrong-but-trusted value at DD-B's exact probe point: `compute_earliest_viable_gate` always
runs with `current_pre_runtime=0.0`, so any check with median <=300s is recommended for
`--pre` regardless of actual budget consumption, and the rationale string presents "0.0s"
as measured (CIRCA-05). Bundle-wins as designed would then *force* the agent to mirror the
biased value; the dispute path is the only correction. Mirroring-without-judgment is not a
hypothetical failure mode -- it is the design, which makes bundle input quality the whole
game.

## Q4 -- drifting, in the un-annotated places

The `[STALE]` Athena/DuckLake annotations are disciplined and do not mislead. What
misleads is INTENT Section 4's enforcement list: check 1 (hard reject on missing
context_v2) is false in code, check 4 (actual_gate comparison) is unimplemented, check 5's
presence/relevance clauses are unenforced beyond the annotated existence-lookup deferral,
and check 6's override rate limit does not exist -- the override is an unvalidated
`Optional[dict]` where any truthy value disables the terminus floor (CIRCA-08). This
audit's own dossier inherited one of these false claims ("typed and rate-limited" --
fact-checked in `meta.dossier_fact_check`). No mechanism ties Section 4 prose to
`file_rec`. A one-pass status annotation (CIRCA-09, XS) closes the reader hazard until the
Wave-3 contract extraction.

## Q5 -- weak by the rollup rule; strong at shift-left

Shift-left is genuinely **met**: earliest-viable-gate computation exists, runs, and drove
a real promotion (SLOC to `--pre`, c4). Blameless discipline, five-whys, error-budget
gating, and deterministic-adjudication are all **partial** -- in each case the mechanism
exists but is inert or consequence-free in the deployed config. Flake/quarantine is
**missed** (no detection, quarantine, or reproduction probe; the roadmap lists a
flake-reproduction probe as an unpromoted candidate), which pins the rollup to weak.

## Q6 highlights beyond the seeds

- **(iii)** Post-flip, same-shape future writes fail loudly at the `FILED:` check -- a
  persistent composition defect becomes a persistent filing outage; plus the CIRCA-06
  unfilable class under S3 degradation.
- **(vi)** The duplicate storm decomposes as per-commit anchoring (dominant) >
  per-workflow-slug context separation > the theoretical dispatch race. A `concurrency:`
  block alone would not have prevented it.
- **(vii, new)** `FILED:` last-marker-wins means a genuinely multi-filing run surfaces
  only one rec id to the workflow, and `mark_rca` then marks *every* enumerated category
  as RCA'd off that single signal -- combined with the agent prompt's "file for the
  primary cause only" sentence (which contradicts both the INTENT and the workflow
  prompt), co-occurring failures silently lose RCA coverage within a commit (CIRCA-07).
- **(v)** The untrusted-log injection surface is well-gated for privilege (same-repo +
  default-branch + restricted tools); the residual is misleading rec *content*, which
  terminates in the human-reviewed `/plan` queue by design.

## Maturity defence

S2 reaches **frontier** (its one finding is medium; canonical hashing, registry-sourced
tier membership, tri-state abstention, and N-bundle enumeration are genuinely strong
engineering). S1 and S4 are **strong** (one high each: dedup, flip-convergence). S3 is
**solid** -- it carries the critical finding plus one high, and that is the honest
centre of gravity: the enforcement spine is well-designed, well-tested against seeded
fixtures, and not wired to reality. Overall **solid**: 1 critical + 3 high across the
system, all with small, named, sequenced fixes -- this is a wiring-and-calibration
deficit on a sound architecture, not a redesign case.
