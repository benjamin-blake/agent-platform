# Intent: Bazel Feasibility Assessment and Build-Tooling Direction

**Status:** Assessment (decision-input). Verdict graduates to Decision 80.
**Date:** 2026-06-03
**Plan:** `docs/plans/PLAN-bazel-feasibility.md` (REPORT-ONLY)
**Method:** Falsification of ten load-bearing claims (C1-C10) carried over from a
prior first-principles Bazel design conversation that reasoned without seeing this
repo. Evidence is repo-grounded (paths and numbers, measured and independently
re-verified at commit `ddb85a0`). General Bazel knowledge is not admissible as
evidence for or against a claim. Where a number could not be reproduced from the
repo, it is softened or labelled.

---

## Verdict

**NOT RECOMMENDED for now. Revisit a build orchestrator -- Pants before Bazel --
when the concrete triggers the repo has already written down arrive: T4.4 raising
executor concurrency above 1, KG.13's content-addressed test caching becoming
load-bearing, and the CD.27 ~10-artifact persona fleet making per-artifact manifest
toil real.**

Single most important reason: at today's scale (T4.1 concurrency = 1), **most** of
Bazel's value is either already obtained with installed tooling or sequenced ahead of
need in the roadmap, while **all** of its costs are due now. The genuinely
Bazel-*discriminating* findings are narrow -- C1/C1b (one language, sub-scale, and
Pants would beat Bazel for pure-Python anyway). The blockers that first looked
decisive -- import cycles (C5), the missing lockfile (C3), the weak test baseline
(C10) -- **bind the lighter do-less path equally**, so they argue for *sequencing*,
not against build tools per se. The honest move is: adopt the do-less baseline now
(`import-linter` + a lockfile), decompose `validate.py` tool-free, and reopen the
build-orchestrator question against the specific concurrency/fleet triggers below.

### Frame challenge (Decision 75, applied to this assessment)

The outsider question this report must answer about *itself*: **what if the relevant
build surface isn't today's 36.5k-SLOC repo, but the ~10-artifact greenfield executor
fleet (CD.27) about to be built, where reproducibility and remote caching across
concurrent agent personas are first-class?** Answer: that frame is real but
**future-dated**. T4.1 fixes executor concurrency at 1; KG.13 (the repo's own
content-addressed-caching item) is explicitly "NOT a pre-executor blocker" and becomes
load-bearing only at T4.4 (concurrency > 1); AWS Lambda Durable Functions are ~5 months
GA. So the present-repo frame is the correct unit of analysis *today*, and the
fleet frame is precisely the **revisit trigger**, not a reason to adopt now. This
report does not claim immunity from frame-lock by virtue of its method; it claims the
fleet frame has been examined and time-ordered.

---

## Claims-Verification Matrix (C1-C10)

The "Discriminates vs Bazel?" column is the key reframe: several FAILS bind the
recommended do-less path equally and therefore do not argue for or against a build
tool -- they argue for sequencing.

| # | Claim (as the design assumed it) | Verdict | Discriminates vs Bazel? | Decisive repo evidence |
|---|---|---|---|---|
| C1 | Polyglot monorepo at scale justifies the cost | **FAILS** | **YES** (Bazel's core premise) | Python + Markdown only; 121 first-party modules / ~36.5k SLOC; one developer; no compiled build; only artifact is a Lambda zip |
| C1b | Bazel is the right tool vs lighter alternatives | **FAILS (for Bazel)** | **YES** | Pure-Python -> Pants (auto dep-inference, less ceremony) dominates; do-less delivers the valuable subset |
| C2 | Gazelle bulk-generates BUILD files statically | **PARTIAL (mostly holds)** | n/a (feasibility) | 0 star-imports, 0 `__import__`, only **1 file** with a real `importlib`/`spec_from_file_location` import (`validate.py`) |
| C3 | import->distribution mapping is manageable | **PARTIAL** | **NO** (lockfile binds do-less too) | ~4-5 name mismatches = trivial; but **no lockfile**; torch 1.1 GB + pysr->Julia defeat a hermetic closure |
| C4 | Dependency closure is a sound scope oracle | **HOLDS** | **PARTIAL** (enforced sandbox is Bazel-only; matters at concurrency > 1) | Sparse graph; closure median **0.8%**, p90 23.1%, max **33.9%** (`validate.py`). Computable with `ast`/`networkx` (installed) |
| C5 | No dependency cycles (Bazel forbids them) | **PARTIAL (deferred-import friction, not a module-load wall)** | **NO** (`import-linter` binds do-less equally) | Module-import graph is **acyclic**; 3 cycles appear only in the static graph via function-local deferred imports (a pervasive style; 104 imports carry inert `noqa: PLC0415` markers) |
| C6 | Agent-file edges via frontmatter + generator | **UNBUILT / Bazel-irrelevant** | n/a | 43 agent files; cross-refs are free-form prose; 0 `responsibilities:`, 1 `depends_on`; Bazel cannot see the 287-file doc surface |
| C7 | Incremental hybrid subtree adoption | **PARTIAL** | **YES** (Bazel-specific integration cost) | No build system exists (`setup.py` = env bootstrap; no lockfile); shared god-modules (fan-in 11-12) resist a clean cut |
| C8 | CodeBuild + S3 cache = zero-infra serverless | **PARTIAL** | **YES** (net-new infra) | **0 CodeBuild today**; CI = GH Actions + OIDC (CD.21); torch 1.1 GB -> multi-GB ML cache blobs |
| C9 | Lambda durable functions orchestrate the loop | **FAILS as stated** | **NO** (CD.27 loop-readiness, orthogonal to build tool) | Repo is Python **3.12** everywhere (design's stated 3.13+ prerequisite unmet); loop = **107 subprocess + 85 git** call sites to make replay-safe |
| C10 | A working tests-with-teeth + monitor baseline | **FAILS (weak baseline)** | **NO** (a gap regardless of build tooling; T3.6/T3.7 in progress) | coverage `fail_under=37`, `source=["src"]` (**excludes scripts/**); no mutation/property testing |

**Discriminating vs shared, stated plainly:** only **C1, C1b** argue against *Bazel
specifically*; **C7, C8** are Bazel-specific *costs*. **C3, C5, C10** bind the
do-less path equally (do-less also needs a lockfile, also forbids cycles via
`import-linter`, also wants better tests). **C9** is a readiness fact about the CD.27
durable-functions loop, independent of any build tool. **C4** mostly holds and is the
one place a future, concurrency-driven Bazel/Pants benefit is real (enforced sandbox).

### Per-claim evidence

**C1 -- FAILS.** Python 228 files / 79.7k LOC (121 first-party modules / ~36.5k SLOC;
101 test files / 43.5k LOC) and Markdown 287 files / ~70k LOC dominate; Terraform is
22 files and is not "built." No compiled language, no compile step. The single
property that makes Bazel worth its ceremony -- one cache/graph across many languages
and teams -- does not exist here.

**C1b -- FAILS for Bazel.** The real comparison is Bazel vs Pants vs do-less. For a
pure-Python tree, Pants infers dependencies automatically (no Gazelle BUILD-authoring
toil) at a fraction of Bazel's ceremony; see Tool-Choice Assessment.

**C2 -- PARTIAL (mostly holds).** The tree is overwhelmingly statically analyzable:
**0** star-imports, **0** `__import__`, only **1 file** (`scripts/validate.py`) with a
real `importlib`/`spec_from_file_location` import. (`scripts/lambda_manifest.py`
mentions `importlib` only inside a string literal passed to `subprocess.run([...,"-c",
"import importlib; ..."])` -- invisible to an AST analyzer/Gazelle, so it does not
refute the claim; independently verified.) Gazelle would work repo-wide; the lone
exception is the exact file the originating refactor targets.

**C3 -- PARTIAL (and not Bazel-discriminating).** Only ~4-5 genuine name mismatches
among ~27 deps (`pyyaml`->`yaml`, `psycopg2-binary`->`psycopg2`,
`scikit-learn`->`sklearn`, `beautifulsoup4`->`bs4`) -- a trivial map. The real friction
is the **missing lockfile** (`requirements.txt` pins floors with `>=`; only 1 `==`; no
`poetry.lock`/`uv.lock`/`*_lock.txt`) and two non-hermetic deps -- `torch` at **1.1 GB**
and `pysr`, which shells out to a Julia runtime `rules_python` does not manage. Note
the lockfile is a do-less prerequisite too, so this is sequencing, not a Bazel
argument.

**C4 -- HOLDS; one Bazel-only edge at concurrency > 1.** The first-party graph is
sparse (121 nodes, 215 edges, avg fan-out 1.78): closure **median = 1 module (0.8%)**,
p90 = 28 (23.1%), **max = 41 (33.9%)** for `scripts.validate` (absolute closure counts
are import-resolution-dependent -- independent analyzers landed the max at 33.1% and
28.9%; the sparse shape, the 0.8% median, and validate.py-as-max are stable across all
three). The closure-as-scope
idea is sound. The report's own closure numbers were computed in ~200 lines of `ast` +
Tarjan, and `networkx 3.6.1` is already installed, so an *advisory* oracle needs no
Bazel. The honest caveat the first draft missed: an advisory oracle is not the same as
a **fail-closed sandbox**. A Bazel target physically cannot read files outside its
declared deps; a hand-rolled oracle only advises. For a *fleet of concurrent
autonomous editors* (CD.27 personas), an enforced sandbox is a real scope boundary
that Python conventions (the very `noqa: PLC0415` discipline) cannot guarantee. At
T4.1 concurrency = 1 the advisory oracle suffices; the enforced-sandbox benefit is
exactly a T4.4 (concurrency > 1) consideration -- a revisit trigger, not a present
gap.

**C5 -- PARTIAL (re-graded; the first draft's "module-level cycles, hard blocker" was
wrong).** The **module-import graph of all three reported cycles is acyclic.** They
appear as cycles only in the static AST graph because that graph counts
**function-local deferred imports** as edges. This deferred-import style is pervasive
(104 imports carry `noqa: PLC0415` markers repo-wide -- inert markers, since ruff
enables only `E/F/W/I`), but the specific cycle back-edges are a distinct,
overlapping population, mostly unmarked -- the first draft wrongly equated the two.
Verified: the entire 6-node `verifiers` SCC collapses by removing one late import,
`scripts/verifiers/harness.py:151` (`from scripts.verifiers import run_all_verifiers`,
inside `async def main()`, commented "Late import to avoid circular dependency" -- no
noqa; `verifiers/` carries zero PLC0415 markers); the `ops_data_portal`/executor
cycle's back-edges are likewise function-local deferred imports
(`jsonl_store.py:195,207,257,279`, marked `noqa: PLC0415`; `plan.py:474`, commented
"local import to avoid circularity", unmarked); likewise `execute_recommendation`.
So the runtime imports are a DAG. What this means for Bazel is a genuine but bounded
friction, not a wall: if Gazelle declares the deferred imports as deps (its default,
since it parses all import statements regardless of scope) Bazel sees a cycle; if it
does not, the runtime import fails in the sandbox because the dep was not staged. That
**declare-and-cycle vs omit-and-ImportError dilemma** is real Bazel adoption work --
but `import-linter` (the do-less pick) forbids cycles too, so this finding does not
discriminate between the two paths; it is decoupling work owed either way. (Whether
Gazelle resurfaces these in *this* repo is a configuration question this report did
not run, so it is stated as Gazelle's documented default behaviour, not as verified
here.)

**C6 -- UNBUILT and Bazel-irrelevant.** 43 agent files (20 `.prompt.md`, 9 `.agent.md`,
11 `SKILL.md`, 3 commands); cross-references are entirely free-form prose; **0** declare
`responsibilities:`, **1** declares `depends_on`. The proposed schema is net-new.
Bazel provides zero leverage -- these are not Python imports, and the 287-file
Markdown surface is invisible to any build graph.

**C7 -- PARTIAL.** There is no existing build system to integrate with: `setup.py` is
an environment bootstrap (`create_venv`, Git-Bash activate patching; no
`setuptools.setup()`, no `find_packages`, no `entry_points`), no `[build-system]`/
`[project]`, no lockfile. The only real artifact is the Lambda zip (manifest-driven,
Decision 79). A clean subtree cut is resisted by shared god-modules every side would
import: `scripts.ops_writer`/`scripts.s3_log_store` (fan-in 12 each),
`scripts.aws_profile`/`src.common.config` (fan-in 11 each).

**C8 -- PARTIAL.** **0** CodeBuild in `terraform/` today -- net-new infrastructure, not
"zero." Current CI is GitHub Actions `ubuntu-latest` + OIDC (Decision 68 / CD.21; the
EC2 runner is retired, `terraform/ec2_runner.tf` is non-applied). Cache sizing is
bimodal: most `scripts/` targets have tiny closures, but any ML target pulls `torch`
(1.1 GB), so its cache blob is multi-GB. (The previously-rejected
Lambda-shim-over-S3 cache is not re-proposed.)

**C9 -- FAILS as stated, but orthogonal to the build-tool decision.** The design's own
stated prerequisite is durable functions on Python 3.13+; the repo is **3.12**
everywhere (CI matrix, ruff `target-version`, the Lambda runtime in
`terraform/data_pipeline.tf`) -- verified; the 3.13+ requirement itself is the design's
premise, not re-verified against AWS docs here. The current loop
(`execute_recommendation.py` + `executor/`) is side-effect-dense: **107**
`subprocess.(run|Popen|...)` call sites and **85** git command invocations to make
replay-safe. Both gaps bind the **CD.27 durable-functions executor regardless of any
build tool** -- C9 is loop-readiness, not a Bazel discriminator. (Durable functions are
the *ratified* substrate, CD.27; the version bump is bridgeable -- Lambda supports
3.13 and Decision 79 unblocked Lambda deploys.)

**C10 -- FAILS (weak baseline), and not Bazel-discriminating.** Coverage gate is
`fail_under = 37` with `source = ["src"]` -- **all of `scripts/` is excluded**,
including `validate.py`. There is no property testing (`hypothesis` absent) and no
mutation testing (`mutmut`/`cosmic-ray` absent). The validation oracle (`validate.py`)
lives in `scripts/`, which agents edit, so it is not isolated. The one genuine
strength is already non-Bazel and already in-flight: `pytest` runs with
`--disable-socket` + `--randomly-seed=last` -- the half-shipped **T3.6** hermeticity
work, and mutation/diff-coverage is **T3.7**. This is a gap to close regardless of
build tooling.

---

## Blockers (what must be true before any Bazel adoption -- mostly shared with do-less)

1. **Resolve the deferred-import dilemma (C5).** The codebase stays module-acyclic via
   function-local deferred imports (104 carry `noqa: PLC0415` markers); under Bazel each
   must be declared (-> static cycle) or
   omitted (-> sandbox ImportError). This decoupling is owed to `import-linter` under
   do-less as well, so do it first either way.
2. **A dependency lockfile (C3).** Needed by `rules_python`/`pip_parse` *and* by the
   do-less baseline.
3. **A hermetic-closure story for `torch`/`pysr`/Julia (C3/C8).** `rules_python` does
   not manage a Julia toolchain; torch at 1.1 GB fights every artifact-size ceiling.
   This one is genuinely Bazel/Pants-specific.
4. **Python 3.13+ if durable functions are wanted (C9).** A CD.27 prerequisite,
   independent of the build tool.

---

## Quantified Findings

All re-measured at `ddb85a0`.

| Metric | Value | Source |
|---|---|---|
| First-party Python | 121 modules / ~36.5k SLOC (scripts 72, src 49) | `ast` analyzer |
| Tests | 101 `test_*.py` / 43.5k LOC | `find`/`wc` |
| Markdown / Terraform / JSON | 287 / 22 / 571 files | `git ls-files`/`find` |
| Import graph | 121 nodes, 215 edges, avg fan-out 1.78, 19 packages | analyzer |
| Dependency-closure | mean 6.8 (5.6%), median 1 (0.8%), p90 28 (23.1%), max 41 (33.9%) | analyzer |
| Highest-closure module | `scripts.validate` = 41 modules (33.9%) | analyzer |
| God-modules (fan-in) | ops_writer 12, s3_log_store 12, aws_profile 11, src.common.config 11 | analyzer |
| Static-graph cycles | 3 (all module-acyclic; deferred-import artifacts) | analyzer + back-edge trace |
| Function-local imports (`noqa: PLC0415`) | 104 (scripts 95, src 9) | grep |
| Real dynamic imports | `importlib`/`spec_from_file_location` in 1 file; `__import__` 0; star 0 | analyzer |
| Third-party deps / pinned | ~27 / 1 pinned (`==`), no lockfile | `requirements*.txt` |
| Heaviest deps | torch 1.1 GB; pysr -> Julia | `du`, `requirements.txt` |
| `validate.py` | **2744** lines (Decision 43 waiver records 1198), 38 `validate_` + 2 `check_` fns, no registry | `wc`, grep |
| `test_validate.py` | **2950** lines; 262 `patch(` sites + 62 `monkeypatch`; loads via 1 `spec_from_file_location` | `wc`, grep |
| Python version | 3.12 (CI, ruff target, Lambda runtime) | pyproject, workflows, terraform |
| Coverage gate | `fail_under=37`, `source=["src"]` (scripts/ excluded) | pyproject |
| Mutation / property testing | none (`mutmut`/`cosmic-ray`/`hypothesis` absent) | `pip show` |
| Agent loop side effects | 107 subprocess + 85 git call sites | grep |
| CodeBuild today | 0 (CI = GH Actions + OIDC, CD.21) | terraform grep |
| `src/lambdas` manifests | 8 (Decision 79; "no transitive resolution") | `find` |

---

## Design Assumptions vs Repo Reality (highest-impact divergences)

| The conversation assumed... | The repo shows... |
|---|---|
| A polyglot codebase where Bazel's cross-language graph pays off | One language (Python) + Markdown; no compile step |
| The import graph has hard module-load cycles Bazel must refuse | The module graph is acyclic; "cycles" are function-local deferred-import artifacts (a style; 104 imports carry inert PLC0415 markers) |
| Bazel uniquely provides the dependency-closure oracle | The closure is already computable (`ast`/`networkx`); Bazel adds an *enforced* sandbox only, valuable at concurrency > 1 |
| Affected-set test selection is the thing to gain | `pytest --picked` selects changed *test files*, not a reverse-closure; true TIA is roadmapped at KG.13 |
| A clean build/packaging system to carve a subtree from | No build system; `setup.py` is an env bootstrap; no lockfile |
| A tests-with-teeth + monitor baseline to build on | 37% coverage scoped away from `scripts/`; no mutation/property testing (T3.6/T3.7 in flight) |
| Durable functions slot onto the loop now | Python 3.12 (design needs 3.13+) and 107 subprocess + 85 git side effects to wrap |
| The repo wants automatic transitive dependency resolution | Decision 79 (today) explicitly chose per-Lambda manifests with **"no transitive resolution"** |

---

## Tool-Choice Assessment

| Dimension | Bazel | Pants | Do-less baseline (recommended now) |
|---|---|---|---|
| Fit for single-language Python | Poor (built for polyglot scale) | Good (Python-native) | Excellent |
| BUILD-authoring ceremony | High (Gazelle + manual dynamic-edge annotation) | Low (auto dep inference) | None |
| Requires acyclic graph | Yes | Yes | `import-linter` *enforces* it (same decoupling either way) |
| Requires lockfile | Yes | Yes | Yes (`uv`/`pip-tools`) -- useful on its own |
| Handles torch/Julia hermetically | No (Julia outside rules_python) | Partially | N/A (keeps venv) |
| Reverse-closure test selection (TIA) | Yes | Yes | Not today; roadmapped at KG.13 (pytest-testmon) |
| Enforced (fail-closed) scope sandbox for agents | Yes | Yes | No (advisory only) -- matters at T4.4 concurrency > 1 |
| Content-addressed remote cache for a fleet | Yes | Yes | No -- the KG.13 value, load-bearing at concurrency > 1 |
| Ongoing agent-maintained cost | High | Medium | ~Zero |

**Conclusion:** at concurrency = 1, do-less delivers the subset that pays off now
(cycle prevention, layering, a pinned closure) at ~zero ongoing cost. The two benefits
that are genuinely build-tool-only -- a fail-closed sandbox and content-addressed
fleet caching -- are the ones the roadmap itself time-orders to T4.4/KG.13. If a build
orchestrator is then wanted, **Pants** (pure-Python, low ceremony) is the candidate,
not Bazel.

---

## Recommendation (phased)

**Phase 0 -- do-less, now (one-time human setup, then ~zero ongoing).**
- Add **`import-linter`** contracts: forbid cycles, declare a layered architecture.
  This is the decoupling the C5 deferred-import dilemma needs anyway, and it prevents
  the validate.py registry from regressing into a `verifiers`-style deferred cycle.
- Generate a **lockfile** (`uv pip compile` / `pip-tools`): the C3 hermeticity, and a
  prerequisite for any future build tool.
- Keep the Decision 73 diff-aware CI (`pytest --picked`, ruff-on-changed) and the
  T3.6 `--disable-socket` hermeticity. (Note: `pytest --picked` is changed-test-file
  selection, *not* reverse-closure -- see Unverifiable/roadmap below.)
- (Independent of build tooling, already roadmapped at T3.6/T3.7) raise the C10
  baseline: widen coverage `source` to include `scripts/`, pilot `hypothesis`.

**Phase 1 -- reconsider a build orchestrator (Pants first) on a roadmap-defined
trigger.** Reopen the question when any of these -- all already written in the repo --
arrives:
- **T4.4 raises executor concurrency above 1.** This is the documented load-bearing
  point for **KG.13** (content-addressed result caching + input-closure test
  selection) and for an enforced per-agent scope sandbox (C4). At concurrency = 1
  neither pays for itself.
- **The CD.27 fleet (~10 persona/deterministic Lambda artifacts; 8 manifests exist
  today) makes per-artifact manifest toil real.** Decision 79's deliberate "no
  transitive resolution" means each artifact hand-maintains its pip list -- exactly the
  toil a Python build tool's dep-inference removes. (Counter-weight: Decision 79 chose
  explicit manifests *on purpose*; a build tool would be re-litigating a fresh
  decision, so treat this as a signal to watch, not a mandate.)
- **A measured CI wall-clock regression** that `pytest --picked` cannot address
  (measure against the existing `_FAST_TIER_BUDGET_SECONDS = 300` budget).

If triggered, time-box a **Pants** spike scoped to the *new* executor subtree only --
never a whole-repo migration. One-time human setup; not agent-maintained until proven.

**Not recommended at any phase:** a whole-repo Bazel migration; a Lambda-hosted
validator registry (see Linkage); authoring the above as a STRATEGIC plan or executor
recommendations while the Decision 67/79 STRATEGIC freeze holds.

---

## Linkage: `validate.py` Decomposition (the originating question)

The Bazel question arose as a deviation from decomposing the `validate.py` monolith.
The two are the **same problem at two altitudes**: the refactor's goal is
modularization + import hygiene; a build tool *rewards* good modularization and
*refuses* bad modularization -- it does not perform the decomposition. `validate.py` is
the worst-precondition file in the repo (**2744** lines vs its 1198 waiver -- and it
grew during this very assessment when the rebase pulled in Decision 79's
`validate_lambda_manifest_coverage`; highest closure at 33.9%; the lone real
`importlib` user; **38** `validate_` functions invoked imperatively with no registry).
So decompose tool-free, as a separate **IMPLEMENTATION** plan (the freeze holds):

1. A `scripts/validators/` package; normal imports replace the
   `spec_from_file_location` path-loading.
2. **`validators/base.py` (leaf): the `Check` protocol ONLY** -- `name`, `inputs`,
   `run(ctx)`. No CLI. (The `verifiers` package put the CLI *and* the base protocol in
   `harness.py`, which is exactly why it needed the deferred back-edge; do not repeat
   that.)
3. **`validators/_helpers.py` (a second leaf tier):** the shared, non-protocol helpers
   every check needs -- `run()`/`invoke_step()`, `get_changed_files()`, `ROOT`,
   `_ensure_root_on_path()`, etc. "Checks import only `base`" is not literally
   implementable without this; declare `base` and `_helpers` as sibling leaves in the
   import-linter layering.
4. `validators/checks/*.py`: one module per check (~38 + helpers), each importing only
   `base`/`_helpers`.
5. `validators/registry.py` (and the `__main__`/CLI entrypoint): imports each check,
   builds the canonical list. `registry -> checks -> {base, _helpers}`, acyclic. This
   is the single source of truth; `validate.py` stays the thin entrypoint CI calls
   (`python -m scripts.validate`), preserving the CLAUDE.md "ci.yml first" invariant.
6. `import-linter` enforces `checks -/-> registry` and the layering.
7. Fix the `verifiers` deferred back-edge first as the smaller reference refactor
   (move `run_all_verifiers` out of `harness.py`).

**Selection is affected-set, not a static tier.** Each `Check` declares `inputs`
(globs) or `always`; the runner runs a check iff its inputs intersect the diff.
`--pre` is *already* diff-aware in its lint scope (ruff/mypy on changed files via
`get_changed_files()`); this extends that to check selection. Guardrails:
(a) **cross-tree drift detectors must declare every input tree** -- e.g. the
`validate_invariants` mock-count check compares `executor/postflight.py` against
`tests/test_execute_recommendation.py`; `check_source_registry` and the
pydantic-vs-yaml drift checks span `scripts/`+`config/`; the CI-workflow guards read
`.github/workflows/ci.yml`, not `scripts/`. A drift check declaring only one side
passes green on the PR tier when the other side changes. These belong in `always` or
must list all trees; do not assume single-glob coverage.
(b) plain-Python selection is not hermetic, so the **PR/edit tier is affected-derived
(advisory) while the main tier runs everything (authoritative)** -- the existing
PR-vs-main split. The per-check fast/full *label* disappears; latency becomes emergent.
(c) **the 5-minute fast-tier budget assertion (`_FAST_TIER_BUDGET_SECONDS`, Decision
73) survives** as an orthogonal wall-clock guard -- a large diff can still breach it;
the refactor removes the *label*, not the budget.
(d) the registry runner must preserve `validate.py`'s recursion guards
(`_VALIDATE_DEPTH`, `_COVERAGE_SUBPROCESS`) that break the validate -> pytest ->
validate fork-bomb.

The real cost driver is **not** the source split: it is the **test migration**.
`tests/test_validate.py` (2950 lines, 262 `patch(` sites) loads the monolith via
`spec_from_file_location` and rebinds symbols off `validate.<name>`; moving each check
to `validators/checks/X.py` invalidates every patch target. Budget the decomposition
plan around the test rewrite.

**The validator registry stays a local importable package -- it is not a Lambda.**
Validation reads the working tree/diff (local data gravity), is latency-sensitive (the
edit loop), deterministic, and offline-capable. A Lambda would invert data gravity,
hit the 262 MB artifact ceiling (the import-smoke and bundle-completeness checks need
the dep closure; torch is 1.1 GB), add cold-start latency to `--pre`, and create a
second execution surface that breaks the single-source-of-truth invariant (CI and the
edit loop must run the same checks). The Lambda execution model belongs to the
**executor/agent-loop** layer (CD.27) -- a different layer, long-running and
side-effectful. Do not conflate the synchronous, local *check registry* with the
asynchronous, remote *executor*. (Independently confirmed sound by adversarial review.)

The validator design (each unit declares inputs; a coverage check enforces
completeness) is the same shape Decision 79 ratified for Lambdas
(`src/lambdas/<slug>/manifest.yaml` + `validate_lambda_manifest_coverage`): the repo's
own direction is explicit, declared, non-transitive manifests.

---

## Unverifiable Claims (and what would settle each)

| Claim | Why unverifiable from the repo | What would settle it |
|---|---|---|
| Bazel/Pants yields a net CI wall-clock win at this scale | No build-tool run exists; depends on cache hit-rate | A time-boxed Pants spike vs the current `--picked` baseline |
| Gazelle resurfaces this repo's deferred-import cycles | Gazelle not run here; it is a config question | Running Gazelle on a trial subtree |
| Durable functions require Python 3.13+ | External AWS fact, not a repo fact | AWS Lambda Durable Functions runtime docs |
| Agents maintain BUILD files without toil-avoidance | Behavioural; no BUILD files exist | A trial subtree over several agent edit cycles |
| Concurrent agents redundantly rebuild enough to justify a remote cache | No build concurrency telemetry; T4.1 sets concurrency = 1 | Build telemetry after T4.4 raises concurrency (this is KG.13) |

---

## Relationship to Existing Decisions / Roadmap

- **Decision 43** (Directed Growth): `validate.py` is a named waiver (1198 SLOC) now at
  2744; the recommended decomposition is the remediation.
- **Decision 60 / Decision 73** (two-tier + diff-aware CI): the do-less baseline
  *extends* the PR-vs-main, `pytest --picked` model; it does not replace it.
- **KG.13** (ROADMAP-PLATFORM.yaml): Test Impact Analysis (input-closure test
  selection, pytest-testmon) + content-addressed result caching -- the repo's own
  build-tool-adjacent capability, explicitly "NOT a pre-executor blocker," load-bearing
  at **T4.4** (concurrency > 1). The single most important deferred signal for Phase 1.
- **T4.1 / T4.4 / CD.27**: T4.1 fixes executor concurrency = 1; T4.4 raises it; CD.27
  is the Step Functions + Lambda Durable Functions persona fleet (~10 artifacts). These
  define "when it's appropriate" to revisit.
- **T3.6 / T3.7**: hermeticity (half-shipped: `--disable-socket`/`--randomly-seed`) and
  mutation/diff-coverage -- the C10 remediation, already roadmapped.
- **Decision 75** (Frame-Lock): engaged explicitly in the Frame Challenge above (the
  CD.27-fleet outsider question), time-ordered rather than dismissed.
- **Decision 67 / Decision 79**: Lambda-deploy clause lifted (per-Lambda manifests);
  the **STRATEGIC-plan freeze is retained**, so the phased recommendation is
  narrative-only and no executor recs are minted.
- **Decision 68 / CD.21**: CI is GitHub-hosted + OIDC; the EC2 runner is retired.
- **Decision 65** (agent-first): this is a durable decision-input artefact graduating
  to Decision 80, not a transient summary.
- **Decision 48**: V1 is the correct verification tier for this docs-only deliverable.

---

## Constraints

- Read-only assessment: no code, config, or BUILD/WORKSPACE/`pants.toml` files written.
- STRATEGIC freeze (Decision 67, retained by Decision 79): no STRATEGIC plan; no
  executor recommendations from the phased recommendation.
- Negatives stated plainly; numbers re-verified at `ddb85a0`; the one re-grade (C5,
  from "hard blocker" to "deferred-import friction") corrects a first-draft error
  surfaced by adversarial review.
- The verdict graduates to Decision 80 after the report-critique gate converges.
