# AUDIT: validate.py, the check corpus, the test suite, the fast-tier selection, and the dependency-declaration set

You are a staff-level CI/build-systems reviewer. Execute this brief verbatim in a fresh session.
It is self-contained: do not ask clarifying questions, do not wait for input. Everything you need
is below or in the repository you are sitting in.

## TASK

Audit the repository's test-and-validation CI path at `origin/main` and produce a design review.
The surfaces in scope are: `scripts/validate.py` (the presubmit orchestrator); its registered
checks under `scripts/checks/**` and their tier registry `scripts/checks/registry.py`; the pytest
suite under `tests/**` and how each validation tier invokes it; the live affected-set selection
that drives the fast (`--pre`) tier (`scripts/checks/deps/affected_tests.py` +
`scripts/dependency_graph.py`); the CI workflows that run validation (`.github/workflows/ci.yml`,
`.github/workflows/main-canary.yml`) plus `.pre-commit-config.yaml` and CI caching; and the
dependency-declaration set (`requirements.txt`, `requirements-fast.txt`, `requirements-dev.txt`,
`requirements.lock`, `pyproject.toml`, `setup.py`, `.github/dependabot.yml`, `.importlinter`).

Answer Q1..Q8 (THE QUESTIONS). Rate every surface against the rubric. File findings per the
OUTPUT contract. The deliverables are exactly two files: `audits/validate-test-suite-<sha>.yaml`
and `audits/validate-test-suite-<sha>.md`, where `<sha>` is the short SHA of the audited
`origin/main` tip (see COMMIT / PR MECHANICS). You draft; a human disposes of the PR. The ONLY
files you create or modify in the repository tree are those two deliverables; regenerating
gitignored local caches per SETUP is expected and is not a breach (never commit them).

## CANDIDATE OBSERVATIONS ARE NOT VERDICTS

This brief hands you FACTS and CANDIDATE hypotheses. It never hands you verdicts. ASSUME NO
CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT to file:line or to an observed artifact. A run that
merely confirms the candidates below has failed. Several candidates will turn out to be
deliberate, already-owned by a roadmap item, or covered by a compensating control; your job is to
find those and reject them with the control named.

Per-candidate adjudication, and how each maps to the output:
- CONFIRMED defect, not owned by any planned item -> `findings`, classification `novel`.
- Real gap whose owning roadmap item / decision exists but whose remedy is insufficient or unbuilt
  -> `findings`, classification `planned-insufficient` (remedy exists on paper but is inadequate)
  or `planned-unbuilt` (adequate remedy, not yet built).
- Fully covered by an existing decision/item/control, or not a defect -> `rejected_candidates`,
  naming the compensating control and how it property-matches.

Severity is never inherited from how a candidate is phrased here. You assign it after judgment.

## READ FIRST -- DISAMBIGUATION

Two naming collisions in this codebase will misdirect you if you do not hold them straight. They
are BOTH (a) navigation hazards for this audit AND (b) a first-class audit subject under Q6. Use
the disambiguation below to avoid MISreading a surface during recon; answer Q6 on whether the
collision itself should be reconciled. Keep those two roles distinct.

- "coverage" names TWO unrelated mechanisms. (1) pytest-cov CODE coverage: `[tool.coverage.*]` in
  `pyproject.toml`, driven by the full-tier `pytest --cov=src`. (2) VERIFIER coverage: the
  `--coverage` CLI flag, `run_coverage_check()` in `scripts/checks/_scaffolding.py`,
  `validate_test_coverage` in the check corpus, and `scripts/verifiers/` -- an advisory report of
  scope files lacking a registered verifier. These are different subsystems; a claim about one is
  not a claim about the other.
- "validate" names FOUR things. (1) `scripts/validate.py` -- the presubmit gate, IN SCOPE. (2) the
  `validate_*` / `check_*` modules under `scripts/checks/**` -- the checks, IN SCOPE. (3)
  `scripts/validate_telemetry.py` -- a standalone Athena telemetry-schema script, NOT wired into
  the presubmit gate. (4) `scripts/verifiers/` -- the exit-code verifier harness, a SEPARATE
  subsystem; a prior audit owns its internals (see DEDUP DISCIPLINE), so treat it as context, not
  an audit target.

Also plausible-but-wrong targets: the CI-RCA machinery (`.github/workflows/ci-rca.yml` and
`scripts/ci_rca/**`) is OUT of scope -- it is the post-merge failure CONSUMER, referenced only as
context for Q4. The terraform/deploy/reconcile/drift workflows are OUT of scope entirely.

## SCOPE

Surfaces (rate each; state built vs partial):
- S1 -- `scripts/validate.py`: the argparse CLI, the `--pre` / full / `--terraform-only` /
  `--coverage` / `--update-sloc-budgets` modes, the recursion + branch guards, the fast-tier
  budget assertion, and the facade re-export block that makes every check a module-level global.
- S2 -- the check corpus: the `validate_*` / `check_*` functions under `scripts/checks/**`,
  registered via `@registry.register(...)` and dispatched by name.
- S3 -- the pytest suite: `tests/**` (structure, conftest hierarchy, markers, fixtures) and the
  two distinct pytest invocations (fast-tier diff-run vs full-tier suite run).
- S4 -- the affected-set selection: `scripts/checks/deps/affected_tests.py` (four channels + cap)
  and its inputs `scripts/dependency_graph.py`, `scripts/test_coverage_checker.py`, and the
  batched collect-only partitioning in `scripts/checks/_scaffolding.py`.
- S5 -- the validation CI path: `.github/workflows/ci.yml` (jobs `pr-validate`, `main-validate`,
  `terraform-validate`, `signal-green`), `.github/workflows/main-canary.yml`,
  `.pre-commit-config.yaml`, and the pip / pre-commit caches.
- S6 -- dependency declaration: `requirements.txt`, `requirements-fast.txt`,
  `requirements-dev.txt`, `requirements.lock`, `pyproject.toml`, `setup.py`,
  `.github/dependabot.yml`, `.importlinter`.

Vocabulary and mechanics you must hold precisely (re-derive each from the repo, do not trust these
sentences):
- Two presubmit tiers (Decision 60/73). The FAST tier is `python -m scripts.validate --pre`:
  diff-aware, subject to a wall-clock budget, the authoritative gate on PR CI. The FULL tier is
  `python -m scripts.validate` (no flag): the whole check corpus + the entire pytest suite, run on
  push-to-main and on a schedule. The full pytest suite does NOT run on pull requests.
- The affected-set derivation (Decision 135) upgrades the fast tier from an "edited-set" (test
  files literally in the diff) to tests AFFECTED by the diff, unioned strictly-additively over
  four channels, with a module cap on the transitive residue; overflow defers to the full
  post-merge tier. The emitted selection manifest is output-only and is never read back as a
  selection input.
- Tier order is declared in `scripts/checks/registry.py` as `pre_sequence()` and
  `full_sequence()`; `scripts/validate.py` iterates them and dispatches each check by
  `globals()[name](failed)`.

Out of scope, one line each: trading/product code; terraform and all deploy/reconcile/drift
workflows; the CI-RCA subsystem internals; the verifier-harness internals (`scripts/verifiers/`);
ops-portal / warehouse internals; the CONTENT of `.importlinter` contracts (Decision 80
architecture) -- the check's wiring/tier/cost is in scope, the contract graph is not; the security
CONTENT of detect-secrets / the shape denylist -- their runtime cost in the tier is in scope.

TRUST-NOTHING: obtain every file, line number, count, and size by reading the repository at your
audited commit. Every anchor in the GROUNDING MAP is a lead, not evidence -- re-derive it. Record
any anchor that does not resolve in `meta.stale_anchors` and downgrade any finding that depended on
it. Line numbers below are approximate and WILL drift; resolve by symbol/content, not by trusting
the number.

## SETUP

Run these once, from the repo root, before auditing. They are read-only or cache-regenerating.

1. `git fetch origin main` and derive the audited base (see COMMIT / PR MECHANICS). Audit that
   tree.
2. `bin/venv-python -m scripts.session.preflight` -- populates `logs/.preflight-report.json` and
   refreshes `logs/.recommendations-log.jsonl` (the recommendations read cache) from the
   warehouse. DEDUP DISCIPLINE depends on that cache being present.
   - Degraded path: IF this fails on credentials/egress, do NOT abort. Set
     `meta.degraded_dedup=true`, mark every finding's `roadmap_crossref.confidence=HYPOTHESIS`
     with `dedup_hit_count=null`, and proceed using only the on-disk `docs/DECISIONS.md`,
     `docs/ROADMAP-PLATFORM.yaml`, and `audits/*.yaml` for dedup.
3. For any empirical timing (EMPIRICAL PASS), use `bin/venv-python` for all Python invocations,
   never bare `python`. If a heavy dependency is missing in your environment and blocks a timing
   run, record it in `meta.contract_notes` and fall back to static reasoning for that item -- do
   not install heavy wheels or mutate the environment beyond what SETUP specifies.

You have AWS credentials available in this session and may read GitHub Actions run history. GH
Actions logs are large: sample step summaries / the uploaded junit + selection-manifest artifacts,
never whole logs. Honor the EMPIRICAL PASS caps.

## NORTH STAR

The bar each surface is judged against. These are principles you argue a surface toward, not
pass/fail templates -- reason about degree.

- NS-A Single source of truth. `scripts/validate.py` is the sole CI gate; a check is added there
  before it can gate anywhere (AGENTS.md). Config and enforcement do not drift; every registered
  check is dispatched, every dispatched name is registered, every declared role is enforced.
- NS-B Curated, non-redundant validation. The check corpus is a graduated, deduplicated asset
  (CD.29): each check earns its place; no two checks assert the same property; no check is dead or
  superseded.
- NS-C Right-tier, non-wedging speed. The fast tier stays diff-aware and under budget; the
  presubmit/postsubmit split catches each defect as early as it can be caught cheaply, without
  running redundant work in the wrong tier (Decision 60/73).
- NS-D Sound blast-radius selection. The affected-set never silently under-selects below the true
  blast radius; it is additive-only, fails loud on error, and its miss rate is observable, not
  assumed (Decision 135/55).
- NS-E Real defect-catching. A defect cannot merge trusted-but-wrong. Coverage, type, flake, and
  integration gates block rather than merely report -- or, where they are advisory by deliberate
  design, that choice is explicit and owned.
- NS-F Coherent dependency declaration. One non-redundant, drift-resistant set of dependency files
  whose stated roles match how CI actually installs and enforces them.
- NS-G Collision-free vocabulary. A term in the validation surface names one thing; where a name is
  overloaded, the overload is a deliberate, documented choice rather than an accident that has
  accreted.

## THE QUESTIONS

Answer each with the pinned enum and a short prose basis citing finding ids. Judgment-bearing; do
not pattern-match.

- Q1 -- Bloat and redundancy. Are any of the registered checks redundant (another check already
  asserts the property), dead/superseded (by a decision or a newer mechanism), miscategorized, or
  otherwise not earning their place against CD.29's curated-asset bar? Same question for the test
  suite: redundant, tautological, or dead tests. Verdict: `sufficient | partial | insufficient`
  (is the corpus curated?). For every check you would change, emit a row in the `check_disposition`
  block with verdict `keep | merge | delete | rescope`.

- Q2 -- Tier placement. Is each check and each pytest invocation in the correct tier(s)? Examine
  specifically: checks that run in BOTH `pre_sequence()` and `full_sequence()` (double execution --
  justified or waste, especially for checks that scan the whole tree regardless of the diff);
  checks that run in the FULL tier only (a PR that breaks one is caught only post-merge -- which are
  cheap and deterministic enough to shift into `--pre`?); checks that run in the FAST tier only
  (absent from the authoritative post-merge tier -- is that intended?); and any check dispatched
  more than once in a sequence. Verdict: `sufficient | partial | insufficient`. For every check you
  would move, emit a `check_disposition` row with verdict
  `keep-tier | promote-to-pre | demote-to-full | add-to-full | dedupe`.

- Q3 -- CI wall-clock. Where does CI wall-clock time actually go across the two tiers, and what are
  the highest-leverage reductions that do NOT lose coverage? Ground this in measured or sampled
  timing (EMPIRICAL PASS), not intuition. Consider at least: the full-tier pytest invocation's
  parallelism vs the fast-tier's; non-diff-aware checks executing in full during `--pre`; any check
  that makes network calls; and CI cache effectiveness (key vs installed set). Verdict:
  `sufficient | partial | insufficient` on current time-efficiency; put the specific reductions in
  findings with measured evidence where you have it.

- Q4 -- Affected-set accuracy. Does the Decision-135 four-channel + capped derivation select the
  right tests -- i.e. is its RECALL sound (does any test affected by a diff go unselected and escape
  to the post-merge tier)? Trace the candidate set each channel draws from, the cap's residue
  ordering, and the fallback path. Separately assess PRECISION (over-selection cost against the fast
  budget). Decisively: is the escape/defer rate that Decision 135's own reversal condition names
  actually MEASURED anywhere, or only assumed? Verdict: `sufficient | partial | insufficient` on
  recall; state precision separately in the prose. This question has a deep-dive (DD-A).

- Q5 -- Coverage and robustness (industry checklist). Where can a defect merge undetected? Assess
  the validation path property-by-property against this EXTERNAL CHECKLIST of established CI/test
  practices, rating each `met | partial | missed` with evidence in the `external_checklist` field
  of this question's answer (this field is the SOLE input to the maturity top tier):
  (a) code-coverage gate exists and is enforced at merge, over the code that matters;
  (b) static type checking gates merges (or its advisory status is a deliberate, owned choice);
  (c) integration-marked tests run in some automated tier;
  (d) presubmit/postsubmit split is sound (what gates a PR vs what only runs post-merge);
  (e) hermeticity / network isolation is enforced in the tests that run;
  (f) flaky-test governance (seed determinism, collection-order stability, timeouts);
  (g) dead-test / redundant-check detection exists;
  (h) mutation or equivalent adequacy signal for the checks themselves.
  A `partial` requires you to name and property-match a compensating control in the evidence.
  Verdict: `sufficient | partial | insufficient`.

- Q6 -- Vocabulary reconciliation. The "coverage" and "validate" collisions (see READ FIRST) reached
  their current state without a deliberate decision on record. For EACH collision, judge whether the
  overload is a defect worth reconciling, weighing the clarity/maintainability benefit against the
  blast radius of any rename (a renamed check name propagates to `registry.py` sequences, the
  `scripts/validate.py` facade re-export, `tests/test_checks_registry.py`, and any `@patch` target;
  a renamed `--coverage` flag or module path has its own callers). Verdict:
  `sufficient | partial | insufficient` on vocabulary hygiene. For each collision emit a row in the
  `naming_reconciliation` block with verdict `reconcile | disambiguate-in-place | leave-as-is` and
  the mechanism + cost.

- Q7 -- Dependency-declaration content and options. Scoped to CONTENT, redundancy, and coupling --
  NOT root placement (a prior audit owns placement; see DEDUP DISCIPLINE). Examine: `requirements.txt`
  mixing runtime and dev/test dependencies; the fast/full split and how it stays in sync; whether
  `requirements.lock` is installed anywhere or only sync-checked; the `requirements-dev.txt` split;
  `pyproject.toml` having no `[project]` table; and `setup.py`'s actual role. Then ENUMERATE two to
  three candidate end-states with trade-offs -- do NOT pick one. Each option MUST state its coupling
  to (i) the fast-tier heavy-dependency deferral, which derives its excluded set from
  `requirements.txt` minus `requirements-fast.txt` (`_excluded_heavy_import_names()` in
  `scripts/checks/_scaffolding.py`), and (ii) the CI pip cache key. Put the options in the
  `requirements_options` block; this question's prose points there. There is no single verdict for
  Q7 beyond a `sufficient | partial | insufficient` rating of the CURRENT declaration's coherence.

- Q8 -- Questions the requester did not think to ask. Answer AND extend this seed list; each answer
  cites finding ids or states "no action". Seeds: (1) the full-tier pytest parallelism vs the
  fast-tier's; (2) the risk profile of gating PRs on the fast tier alone while the full suite runs
  only post-merge; (3) the `registry` owner / product_coupled metadata and whether any runtime path
  consumes it; (4) the maintenance surface of the facade re-export block (a check added without its
  re-export line); (5) `scripts/validate_telemetry.py`'s relationship to the presubmit gate; (6) the
  checks that run in the fast tier but not the post-merge tier; (7) the pip cache key vs the set the
  fast job installs; (8) whether the fast-tier budget assertion, which runs last, can prevent a slow
  run or only report it after the fact.

## RUBRIC

Rate each surface on each applicable dimension: `strong | adequate | weak | absent | n/a`. `n/a` is
correct and costless where a dimension does not structurally apply -- never manufacture a rating or
finding to fill a cell.

- VD1 Redundancy / dedup -- checks and tests are non-overlapping and each load-bearing. (Q1, Q5)
- VD2 Tier-placement correctness -- right check in right tier(s); no unjustified double-run or
  coverage gap. (Q2, Q3)
- VD3 Speed / budget discipline -- wall-clock efficiency, diff-awareness, caching. (Q3)
- VD4 Selection recall -- the affected-set catches the true blast radius; misses are observable.
  (Q4)
- VD5 Selection precision / cost -- over-selection is bounded against the budget. (Q4, Q3)
- VD6 Gate strength -- coverage/type/flake/integration gates block rather than merely report, or the
  advisory choice is owned. (Q5)
- VD7 Single-source-of-truth / registration integrity -- config-to-enforcement coherence; no orphan
  checks or write-only metadata; the facade/registry is drift-resistant. (Q1, Q8)
- VD8 Dependency-declaration coherence -- the requirements set is non-redundant, roles match
  enforcement, and it is drift-resistant. (Q7)
- VD9 Vocabulary hygiene -- a term in this surface names one thing, or the overload is deliberate and
  documented. (Q6)

## DEEP-DIVE

DD-A (feeds Q4, Q3-precision). Trace the fast-tier selection end to end for at least two concrete
diff shapes you construct or find in history: (i) a change to a single widely-imported module (e.g.
a `scripts/checks/_common.py`-class hub) and (ii) a change to a non-`.py` config/contract artifact
that some test depends on. For each: which channel(s) select which tests; what the transitive
residue is; whether the cap defers anything and in what order the residue is kept vs deferred;
whether a genuinely-affected test is left unselected. Then determine, by reading the code and
sampling artifacts, whether the deferred/escaped count is recorded anywhere a human or an agent
reads. State recall as: the classes of affected test that CAN be missed, each with a concrete
trace or a reasoned argument that none can.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Every entry is a LEAD -- verify it by reading
the file at your audited commit before you rely on it; anchors carry no verdict, only a neutral
observed fact. Record non-resolving anchors in `meta.stale_anchors`.

Orchestrator (S1):
- `scripts/validate.py` -- thin CLI; opens with a `# complexity-waiver: decision-43` marker; a
  ~180-line block of `from scripts.checks... import <name>  # noqa: F401` facade re-exports;
  `_FAST_TIER_BUDGET_SECONDS = 300`; the `--pre` block lazily imports `affected_tests`; dispatch is
  `globals()[name](failed)`.
- `scripts/checks/registry.py` -- `pre_sequence()` and `full_sequence()` return the ordered `Step`
  lists; `register()` records `owner` and `product_coupled` on each `Check`; observe which names
  appear in one sequence, both, or neither, and whether any name appears twice in a sequence.
- `scripts/checks/_scaffolding.py` -- the non-check scaffold steps. `_PYTEST_FLAGS` (the fast-tier
  pytest flags); `_build_unit_test_cmd()` (the full-tier pytest command); `run_pytest_diff()`;
  `run_dependency_checks()`; `run_coverage_check()` (verifier coverage, advisory);
  `_excluded_heavy_import_names()`.

Check corpus (S2): checks live under `scripts/checks/<domain>/`; `scripts/CLAUDE.md` documents the
three-place add ritual (module + `registry.py` sequence + `validate.py` re-export). Owner/product
metadata is asserted in `tests/test_checks_registry.py`. `scripts/checks/deps/validate_requirements.py`
issues a `pip index versions` call per package. `scripts/checks/deps/validate_lockfile_sync.py`
delegates to `scripts/import_governance.py::check_lockfile_sync()`. `scripts/validate_telemetry.py`
is a standalone module; find its importers.

Test suite (S3): `tests/**` (count the files and functions yourself); `pyproject.toml`
`[tool.pytest.ini_options]` (markers include `slow`, `integration`, `unit`, `aws`; `addopts`
include `--disable-socket`, `--randomly-seed=last`); `tests/conftest.py` and the per-package
conftests; `tests/CLAUDE.md` (mirror-convention, no-cross-test-imports, count-coupling rules).

Selection (S4): `scripts/checks/deps/affected_tests.py` -- `CAP`; the four channels
(`_import_closure_channel`, `_data_edge_channel`, `_mirror_map_channel`, `_conftest_subtree_channel`);
`_is_changed_source_py()` (which paths are candidates for import-closure/mirror channels);
`derive_affected_tests()` (residue ordering, cap application, fallback-on-exception); `emit_manifest()`
(output-only). `scripts/dependency_graph.py`; `scripts/test_coverage_checker.py::map_source_to_test`.

CI (S5): `.github/workflows/ci.yml` -- `pr-validate` (installs `requirements-fast.txt` +
`requirements-dev.txt`, runs `--pre`; cache key `hashFiles('requirements.txt')`; uploads
`selection-manifest`), `main-validate` (installs `requirements.txt` + `requirements-dev.txt`, runs
full; uploads `pytest-junit`), `terraform-validate`, `signal-green`.
`.github/workflows/main-canary.yml` -- scheduled full `validate`. `.pre-commit-config.yaml` -- the
hook set (observe whether ruff is among them). Full-tier pre-commit runs `--all-files` inside
`validate.py`.

Dependencies (S6): `requirements.txt` (observe whether dev/test tools sit alongside runtime deps);
`requirements-fast.txt` (its header states the sync discipline); `requirements-dev.txt`;
`requirements.lock` (a pip-compile transitive-closure lock); `pyproject.toml` (observe whether a
`[project]`/`[build-system]` table exists; `[tool.coverage.report] fail_under`,
`[tool.coverage.run] source`); `setup.py` (read its module docstring for its stated role);
`.github/dependabot.yml`; `.importlinter`.

Governing decisions / items (cite by id; read the ones your findings touch): Decision 135
(affected-set selection; its reversal conditions and the T2.36 / KG.13 deferrals), Decision 104
(thin-CLI check registry), Decision 80 (build-tooling direction; import-graph oracle; the
live-derivation vs deferred-cache boundary), Decision 60 / 73 (two-tier diff-aware CI), Decision 72
/ 55 (RCA forward-fix; fail-loud fallback), Decisions 43 / 102 / 128 / 130 (SLOC / complexity /
whole-repo size governance), Decision 131 (test mirror convention), Decision 132 / 148 (verification
graduation; VP-replay), Decision 27 (`setup.py`'s git-bash venv role), CD.29 (curated/deduplicated
validation asset), CD.30 (diff-line-coverage ratchet). Roadmap: T3.7 (mutation testing +
deterministic dead-test detection + diff-coverage ratchet), T2.15 (CI verification-coverage
restoration), T3.6 (test-suite hermeticity audit, complete), T2.36 (selection-manifest DuckLake
registration, deferred), KG.13 / T3.11 c5 (Bazel/Pants selection+coverage cache, deferred with an
armed revisit trigger), T-1.24 (`scripts/ops` nesting).

## EMPIRICAL PASS

Observed evidence outranks static reasoning at equal severity; tag each finding
`evidence_kind: static | observed`. Hard caps -- do NOT exceed:
- Time the full pytest suite once with `--durations=25` to identify the slowest tests; record the
  top entries, not the whole output.
- Measure per-tier and, where cheap, per-check wall-clock (e.g. run `--pre` on a representative diff
  and read the printed per-phase timings; run the full tier once). One run each; do not benchmark
  repeatedly.
- Diff the registered check set against the union of `pre_sequence()` + `full_sequence()` to find any
  registered-but-undispatched or dispatched-but-unregistered name (mind that a scaffold may dispatch
  a check outside the sequences).
- Grep `logs/.recommendations-log.jsonl` for at most 20 recent `source=ci_rca` recommendations;
  classify how many trace to a fast-tier escape (a test that failed only post-merge that an affected-set
  channel could have selected). This is your empirical recall signal for Q4.
- Sample at most 10 recent `main-validate` runs and at most 15 recent merged `claude/*` PR
  `pr-validate` runs from Actions history: read step summaries and the uploaded `pytest-junit` /
  `selection-manifest` artifacts, NOT full logs.
- OPTIONAL, only if you judge the recall question unresolved after the above: replay
  `derive_affected_tests` over at most 15 recent merged PR diffs and compare its selection to the
  tests that actually changed status. If you skip this, say so and why.

Apply the counterfactual per sample: for a claimed escape, would the fast tier have selected the
failing test if the channel you credit were working? If not, it is not an escape of that channel.

## METHOD

- P1 Read S1..S6 at the audited commit; build the tier map (which check in which tier) yourself.
- P2 Trace each candidate observation to file:line; discard the ones that do not hold.
- P3 DD-A: trace selection end to end for the two diff shapes.
- P4 EMPIRICAL PASS within the caps; tag observed findings.
- P5 Rate the rubric per surface.
- P6 DEDUP DISCIPLINE on every surviving finding.
- P7 Synthesize: answer Q1..Q8, fill the decision blocks, compute maturity LAST.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the search on the finding
(`roadmap_crossref.dedup_search_terms`, `dedup_hit_count`). A finding with no recorded negative
search is a HYPOTHESIS, not CONFIRMED. Surfaces to grep: `logs/.recommendations-log.jsonl` (open
recs -- there are many touching `validate.py`/CI/tests; a keyword hit is likely), `docs/DECISIONS.md`,
`docs/ROADMAP-PLATFORM.yaml` (`tier_items[]` + `candidate_decisions[]`), and `audits/*.yaml`. A hit
means the territory is owned: classify `planned-insufficient` / `planned-unbuilt` or move the item to
`rejected_candidates` -- never file it as a novel discovery.

Prior audits that own adjacent territory (read their summaries; dedup against them):
- `audits/repository-structure-cb02572.yaml` -- assessed ROOT PLACEMENT of the six dependency files
  and dismissed the "too many root requirements files" candidate (documented, mechanically-synced
  roles); it also noted `setup.py`'s misleading name. Your Q7 is content/coupling, NOT placement --
  do not re-litigate placement; reference this audit when the placement angle arises.
- `audits/verification-system-review-f80508b.yaml` -- owns the verifier-harness internals
  (`scripts/verifiers/`, VP-replay, graduation). You assess only how the verification CHECKS sit in
  the tiers, not the harness design.
- `audits/legacy/AUDIT-test-hermeticity.yaml` -- the T3.6 hermeticity audit. Hermeticity findings
  are covered here; treat Q5(e) as a re-confirmation against current state, not a fresh discovery.
- `audits/ci-rca-system-a49db8f.yaml` -- owns the CI-RCA subsystem (out of scope here).

DELIBERATE CONSTRAINTS -- do NOT flag as novel defects (name the id if you touch them):
- The selection is deliberately live/cacheless/tool-free (Decision 135 / Decision 80 pt3). A
  selection or coverage cache is KG.13 (T3.11 c5), deferred with an armed revisit trigger. Do not
  recommend "add a cache" as a novel finding.
- The selection manifest is deliberately never read back as a selection input; its CI-RCA
  consumption is deferred to T2.36 (Decision 135). "The manifest has no consumer" is that deferral,
  not a gap.
- The full pytest suite running only post-merge is the deliberate presubmit/postsubmit split
  (Decision 60/73). The live question is recall, not "make the full suite gate PRs".
- CI-RCA forward-fix, never inline-patch, never auto-revert (Decision 55/72).
- `validate.py` as single source of truth; the three-place add ritual and facade re-export are the
  chosen Decision-104 pattern -- their maintenance cost is a legitimate finding, but "this pattern
  is wrong" is not.
- SLOC / complexity / whole-repo size governance (Decisions 43/102/128/130).
- Mutation testing, deterministic dead-test detection, and the diff-line-coverage ratchet are
  planned (T3.7 / CD.30). Findings here are `planned-unbuilt`, not novel.
- `setup.py`'s env-bootstrap role (Decision 27) is deliberate; its identity is a Q6/Q7 subject, but
  its existence is not a defect.

## OUTPUT

Write both deliverables. The YAML is the system of record; the `.md` is a companion report, prose,
<= ~1500 words, the executive layer a human reads first (surface maturities, the highest-leverage
changes, the Q7 requirements options, and the Q6 recommendation).

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>, methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q3, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: "",
       external_checklist: [{property: a|b|c|d|e|f|g|h, rating: met|partial|missed, evidence: ""}]}
    - {q: Q6, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q7, verdict: sufficient|partial|insufficient, basis: [<ids>], prose: ""}
    - {q: Q8, answers: [{question: "", answer: "", basis: [<ids>]}]}
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<ids>]}
    # ... one per surface S1..S6
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
    # ... every applicable surface x dimension cell
  check_disposition:   # Q1 + Q2; one row per check you would change (omit keep/keep-tier no-ops)
    - {check: <name>, verdict: keep|merge|delete|rescope|keep-tier|promote-to-pre|demote-to-full|add-to-full|dedupe,
       target: "<merge-into / new-tier / n/a>", rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  naming_reconciliation:   # Q6; one row per collision
    - {collision: "coverage"|"validate", verdict: reconcile|disambiguate-in-place|leave-as-is,
       mechanism: "", blast_radius: "", cost: "", rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  requirements_options:   # Q7; two or three, do NOT pick one
    - {option: "", changes: "", tradeoffs: "", deferral_coupling: "<excluded-set + pip-cache impact>",
       effort: XS|S|M|L}
  findings:
    - {id: VTS-01, surface: S1..S6|shared, question: Q1..Q8, dimension: VD1..VD9,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate|rename,
       proposed_change: "", acceptance: "",
       severity: critical|high|medium|low, severity_rationale: "",
       confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [<ids>],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [<ids>], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [<ids>], highest_leverage_change: <id>,
            maturity_S1: "", maturity_S2: "", maturity_S3: "", maturity_S4: "",
            maturity_S5: "", maturity_S6: ""}
```

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list.
`total_findings = len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`.
Fully-covered candidates live in `rejected_candidates`, never in `findings`. `rubric_ratings`,
`question_answers`, `check_disposition`, `naming_reconciliation`, and `requirements_options` are
systems-of-record referenced FROM findings, never re-counted. `top_improvements` and
`highest_leverage_change` MUST be finding ids.

`control_property_match` / `compensating_controls_considered`: whenever a compensating control is
your reason to dismiss or downgrade, name the property the control exercises, cite where it operates
(mechanism or file:line), and state why it would FAIL if the defect were real. A control that cannot
catch the break neither lowers severity nor justifies dismissal.

CONFIRMED requires the behavior traced to file:line or an observed sampled artifact; anything less
is HYPOTHESIS.

## SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherit it from this brief's framing:
- critical = a defect can merge trusted-but-wrong: the validation path passes a change that is in
  fact broken (an affected-set recall hole that lets a genuinely-broken test escape the PR gate; a
  gate believed to block that does not).
- high = a weakness that materially reduces the guarantee AND whose compensating controls you judged
  insufficient (e.g. a class of defect that only the post-merge tier catches, with real churn cost).
- medium = redundancy / miscategorization / drift-risk / ambiguity with a clear fix.
- low = clarity / wording / cosmetic naming.

Maturity: compute LAST, per surface, top-down, first match wins. Pin these thresholds:
- frontier = 0 open critical AND 0 open high on that surface AND (for surfaces bearing on Q5) every
  `external_checklist` property rated met or partial, never missed.
- strong = 0 critical AND <= 1 high.
- solid = <= 1 critical.
- nascent = otherwise.
The top rating stays reachable where you argued a property-matched compensating control -- the
framing here must not foreclose it.

## COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main`, then `git rev-parse --short origin/main`. That
   tree IS the audited tree; use its short SHA in the two deliverable filenames, the branch name,
   and `meta.audited_commit`.
2. `git switch -c audit/validate-test-suite-<sha> origin/main` -- a deliberate exception to the
   session-branch convention so the PR diff is exactly the two deliverable files off the audited
   base.
3. Write `audits/validate-test-suite-<sha>.yaml` and `audits/validate-test-suite-<sha>.md`.
   Repo-wide validation is advisory outside CI here: a clean YAML parse of your deliverable is the
   real pre-push gate. If `validate --pre` reports an UNRELATED failure, record it in
   `meta.contract_notes` and do NOT fix it (write boundary).
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing
   is unavailable. `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, title
   `audit: validate.py / check corpus / test suite / fast-tier selection / requirements
   (S1-S6)`, body = the `summary` block in a yaml fence plus a 2-3 sentence lede). Then END THE
   TURN -- do not poll, do not merge, do not subscribe, do not self-approve.

## GUARDRAILS

- Write boundary, closed list: the only files you create or modify in the tree are
  `audits/validate-test-suite-<sha>.yaml` and `.md`. Regenerating gitignored caches per SETUP is
  expected; never commit them. Never edit `validate.py`, a check, a workflow, a requirements file,
  or anything else in scope -- you review, you do not repair.
- Precision over volume. Fewer than ~10 surviving findings is a valid result -- state it plainly; do
  not pad. A rejected candidate with a named property-matched control is worth more than a
  speculative finding.
- Every finding needs file:line-or-artifact evidence, a recorded dedup search, and a severity you
  can defend by defect class. If you cannot trace it, it is a HYPOTHESIS and must say so.
- Stay inside scope. When a thread leads into the verifier harness, CI-RCA, terraform, or root-file
  placement, stop at the boundary and note it -- those are owned elsewhere.
