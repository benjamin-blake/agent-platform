# Intent: Bazel Feasibility Assessment and Build-Tooling Direction

**Status:** Assessment (decision-input). Verdict graduates to Decision 80.
**Date:** 2026-06-03
**Plan:** `docs/plans/PLAN-bazel-feasibility.md` (REPORT-ONLY)
**Method:** Falsification of ten load-bearing claims (C1-C10) carried over from a
prior first-principles Bazel design conversation that reasoned without seeing this
repo. Evidence is repo-grounded (paths and numbers, measured at commit `ddb85a0`).
General Bazel knowledge is not admissible as evidence for or against a claim.

---

## Verdict

**NOT RECOMMENDED for whole-repo adoption. Feasible-with-conditions only as a
narrow, evidence-gated future spike on the greenfield Lambda/executor subtree --
and even there, Pants dominates Bazel.**

Single most important reason: every benefit the design rests on is either already
obtainable with tooling the repo has or can pip-install trivially (the
dependency-closure "oracle" is ~200 lines of `ast`+Tarjan and `networkx` is already
installed; `pytest --picked` plus ruff-on-changed already perform affected-set
selection per Decision 73; `--disable-socket` already enforces test network
hermeticity), or it is blocked by preconditions the repo fails (three live import
cycles plus 96 function-local imports masking more; no dependency lockfile; Python
3.12 vs durable-functions' 3.13+). The headline Bazel advantage -- a polyglot
monorepo at scale -- is absent: this is a ~36.5k-SLOC single-developer
Python+Markdown repo with no compiled build step, whose only build artifact is a
Lambda zip that Decision 79 (ratified today) chose to package via explicit
per-artifact manifests with "no transitive resolution" -- deliberately the opposite
of Bazel's automatic-closure model.

---

## Claims-Verification Matrix (C1-C10)

| # | Claim (as the design assumed it) | Verdict | Decisive repo evidence |
|---|---|---|---|
| C1 | Bazel's benefits (polyglot monorepo at scale) justify its cost | **FAILS** | Python + Markdown only; 120 first-party modules / ~36.5k SLOC; single developer; no compiled build; only artifact is a Lambda zip |
| C1b | Bazel is the right tool vs lighter alternatives | **FAILS (for Bazel)** | Pants (auto dep-inference, far less ceremony) dominates for pure-Python; the do-less baseline already delivers the valuable subset |
| C2 | Gazelle bulk-generates BUILD files via static import analysis | **PARTIAL / mostly holds** | 0 star-imports, 0 `__import__`, only **1 file** uses `importlib`/`spec_from_file_location` -- and it is `validate.py` itself |
| C3 | import-name -> distribution-name mapping is manageable | **PARTIAL** | ~4-5 mismatches (pyyaml->yaml etc.) = trivial; but **no lockfile** (unpinned `>=`); torch 1.1 GB + pysr->Julia break a hermetic closure |
| C4 | Dependency closure is a sound scope/permission oracle | **HOLDS -- but not via Bazel** | Sparse graph; closure median **0.8%**, p90 25%, max **33.3%** (validate.py). Computable in 200 lines of `ast`; `networkx` already present |
| C5 | No dependency cycles (Bazel forbids them) | **FAILS (hard blocker)** | **3 module-level cycles** incl. the entire `verifiers` package (6) and an `ops_data_portal`+executor cycle (5); 96 `noqa: PLC0415` imports mask more |
| C6 | Agent-file edges expressible via frontmatter + generator | **UNBUILT / Bazel-irrelevant** | 43 agent files; cross-refs are free-form prose; 0 declare `responsibilities:`, 1 declares `depends_on`; Bazel cannot see the 284-file doc surface |
| C7 | Incremental hybrid subtree adoption is low-friction | **PARTIAL** | No build system exists (`setup.py` = env bootstrap; no `[build-system]`, no lockfile); shared god-modules (fan-in 11-12) resist a clean cut |
| C8 | CodeBuild + S3 disk cache = zero-infra serverless build | **PARTIAL** | **0 CodeBuild today** (net-new); CI = GH Actions `ubuntu-latest` + OIDC (CD.21); torch 1.1 GB -> multi-GB cache blobs for ML targets |
| C9 | Lambda durable functions orchestrate the recursive loop | **FAILS (version gap + retrofit)** | Python **3.12** everywhere (durable fns need 3.13+); current loop = **172 subprocess + 97 git + 21 LLM** calls to make replay-safe |
| C10 | A working "tests-with-teeth" + monitor baseline exists | **FAILS (weak baseline)** | coverage `fail_under=37`, `source=["src"]` only (**excludes all of scripts/**, incl. validate.py); **no** mutation/property testing; oracle not isolated |

### Per-claim evidence

**C1 -- FAILS.** *Assumed:* Bazel pays off because it manages polyglot builds at
scale. *Found:* Python 228 files / 79.7k LOC (120 first-party modules / ~36.5k SLOC;
104 test files / 42.6k LOC) and Markdown 284 files / ~70k LOC dominate; Terraform is
22 files / ~7k LOC and is not "built." There is no compiled language and no compile
step -- "build" for Python is essentially a no-op. *Implication:* the single
property that makes Bazel worth its ceremony (one cache/graph across many languages
and teams) does not exist here. One language, one developer, one real artifact.

**C1b -- FAILS for Bazel.** *Assumed:* the choice is "Bazel yes/no." *Found:* the
real comparison is Bazel vs Pants vs do-less. For a pure-Python tree, Pants infers
dependencies automatically (no Gazelle BUILD-authoring toil) at a fraction of
Bazel's ceremony. And the do-less baseline already exists in part (Decision 73
diff-aware CI). *Implication:* even if a build orchestrator were wanted, Bazel is
the wrong one; see Tool-Choice Assessment.

**C2 -- PARTIAL (mostly holds).** *Assumed:* dynamic imports will defeat Gazelle.
*Found:* the tree is overwhelmingly statically analyzable -- **0** star-imports,
**0** `__import__`, and only **1 file** (`scripts/validate.py`) uses
`importlib`/`spec_from_file_location`. The 45 files with imports nested in `try`/`if`
are predominantly the mandated `try/except ImportError` optional-dependency pattern
plus `noqa: PLC0415` cycle-breakers -- Gazelle reads the import node regardless of
the guard, so it resolves them. *Implication:* Gazelle would work repo-wide; the
single exception is `validate.py` -- the exact file the originating refactor targets,
and the one whose test must load it by file path.

**C3 -- PARTIAL.** *Assumed:* the import-to-distribution manifest is the friction.
*Found:* only ~4-5 genuine mismatches among ~27 deps (`pyyaml`->`yaml`,
`psycopg2-binary`->`psycopg2`, `scikit-learn`->`sklearn`, `beautifulsoup4`->`bs4`) --
a trivial one-time map. The real friction is elsewhere: **no lockfile exists**
(`requirements.txt` pins floors with `>=`; no `poetry.lock`/`uv.lock`/`*_lock.txt`),
and two deps defeat a hermetic pinned closure -- `torch` is **1.1 GB** on disk and
`pysr` shells out to a Julia runtime that `rules_python` does not manage (PySR runs
on a separate compute node per project context). *Implication:* the manifest is easy;
the lockfile and the Julia/torch hermeticity are the actual prerequisite work.

**C4 -- HOLDS, but not because of Bazel.** *Assumed (skeptically):* if most targets
transitively depend on most of the repo, the scope/permission oracle collapses.
*Found:* the opposite -- the first-party graph is sparse (120 nodes, 213 edges, avg
fan-out 1.77) and partitions well: dependency-closure **median = 1 module (0.8%)**,
p90 = 30 (25%), **max = 40 (33.3%)** for `scripts.validate`. So the closure-as-scope
idea is sound for this repo. *Implication:* the benefit is real but Bazel is not what
unlocks it -- this matrix's own closure numbers were computed in ~200 lines of `ast`
+ Tarjan, and `networkx 3.6.1` is already installed. The same reverse-closure already
drives `pytest --picked`. Bazel would be paying a large fixed cost to re-expose a
graph the repo can already compute.

**C5 -- FAILS (hard blocker).** *Assumed:* the import graph is acyclic (Bazel
forbids cycles between targets). *Found:* **three** module-level cycles:
(1) the entire `scripts/verifiers` package as one 6-node SCC
(`verifiers <-> athena_views <-> data_quality <-> harness <-> outbox_health <->
schema_integrity`); (2) a 5-node `acceptance_lint <-> jsonl_store <-> plan <->
step_runner <-> ops_data_portal`; (3) `execute_recommendation <-> executor.batch`.
The `verifiers` cycle is caused by a single back-edge -- `scripts/verifiers/harness.py:151`
does `from scripts.verifiers import run_all_verifiers`, reaching back into the
`__init__` that imports it. Worse, there are **96 `noqa: PLC0415` function-local
imports** repo-wide, deliberately deferred to dodge Python runtime cycles; Gazelle
would declare them as deps anyway, so Bazel would **resurface every cycle they hide**.
*Implication:* the 3 visible cycles are a floor, not a ceiling. Adoption requires a
real decoupling pass first. (Note: two cycles touch executor files now being rebuilt,
but the `verifiers`/`ops_data_portal` cycle is live infra and survives that rebuild.)

**C6 -- UNBUILT and Bazel-irrelevant.** *Assumed:* semantic/agent-file edges can be
captured with `depends_on` frontmatter + a generator + a validation rule. *Found:*
43 agent files (20 `.prompt.md`, 9 `.agent.md`, 11 `SKILL.md`, 3 commands). Their
cross-references are entirely free-form prose (e.g. a `.agent.md` description naming
"implement.prompt.md or the invoking agent"); **0** declare `responsibilities:`, **1**
declares `depends_on`. The proposed schema is net-new and unbuilt. *Implication:*
Bazel provides zero leverage here -- these are not Python imports, and the 284-file /
~70k-LOC Markdown surface is invisible to any build graph. This is a custom-tooling
problem the build tool does not touch.

**C7 -- PARTIAL.** *Assumed:* a subtree can be carved onto Bazel while the rest keeps
its existing build. *Found:* there is no existing build system to integrate with --
`setup.py` is an environment bootstrap (`create_venv`, Git-Bash activate patching;
no `setuptools.setup()`, no `find_packages`, no `entry_points`), there is no
`[build-system]`/`[project]` table, and no lockfile. The only real artifact is the
Lambda zip (now manifest-driven, Decision 79). A clean subtree cut is further
resisted by shared god-modules every side would import: `scripts.ops_writer` and
`scripts.s3_log_store` (fan-in 12 each), `scripts.aws_profile` and `src.common.config`
(fan-in 11 each). *Implication:* "hybrid" means Bazel-building a leaf while the
shared substrate stays venv+pytest -- and the substrate is exactly what both sides
need, so the boundary is not clean.

**C8 -- PARTIAL.** *Assumed:* CodeBuild + an S3 disk cache is a zero-infra serverless
build path. *Found:* there is **0** CodeBuild in `terraform/` today -- it is net-new
infrastructure, not "zero." Current CI is GitHub Actions `ubuntu-latest` with OIDC
(Decision 68 / CD.21; the EC2 runner is retired, `terraform/ec2_runner.tf` is a
non-applied artifact). Artifact/cache sizing is bimodal: most `scripts/` targets have
tiny closures, but any ML target pulls `torch` (1.1 GB), so its cache blob is
multi-GB and the S3 save/restore overhead is significant. *Implication:* "serverless"
is true; "zero-infra" is not, and the disk-cache economics are poor precisely for the
heavy ML targets. (The previously-rejected Lambda-shim-over-S3 cache is not
re-proposed.)

**C9 -- FAILS (version gap + retrofit).** *Assumed:* Lambda durable functions are a
clean fit for the recursive loop, with every side effect wrapped in a checkpointed
step. *Found:* durable functions require Python 3.13/3.14, but the repo is **3.12**
everywhere (CI matrix, ruff `target-version`, and the Lambda runtime in
`terraform/data_pipeline.tf`). And the current loop (`execute_recommendation.py` +
`executor/`) is side-effect-dense: **172** `subprocess` calls, **97** git
invocations, **21** LLM/model calls. *Implication:* two gaps -- a runtime bump
(bridgeable: Lambda supports 3.13, and Decision 79 just unblocked Lambda deploys) and
a ~290-side-effect retrofit to replay-safe steps. A greenfield executor rebuild could
bake step-wrapping in from day one, but the version bump is still a hard prerequisite.
Note: durable functions are not the problem -- they are the ratified executor substrate
(ROADMAP-PLATFORM "Executor compute substrate = Step Functions + Lambda Durable Functions
+ Lambda", CD.27); C9 fails purely on the unmet 3.12 -> 3.13 prerequisite plus the
side-effect retrofit, not on the orchestration choice.

**C10 -- FAILS (weak baseline).** *Assumed:* a working "tests-with-teeth"
(mutation/property testing, tamper-resistant oracle) and a telemetry monitor already
exist as the layer the design builds on. *Found:* coverage gate is `fail_under = 37`
and `source = ["src"]` only -- **all of `scripts/` is excluded from coverage**,
including `validate.py` and the executor. There is **no** property testing
(`hypothesis` absent) and **no** mutation testing (`mutmut`/`cosmic-ray` absent). The
validation oracle (`validate.py`) lives in `scripts/`, which agents edit, so it is
not architecturally isolated from the code under test. The one genuine strength is
already non-Bazel: `pytest` runs with `--disable-socket` + `--randomly-seed=last`,
enforcing network hermeticity and order-independence today. *Implication:* the
"verifier baseline" the design assumed is largely aspirational; this is a gap to
close regardless of build tooling.

---

## Blockers (must be true before any Bazel adoption)

1. **Acyclic import graph (C5).** Remove the 3 cycles (start with the single
   `harness.py` -> `__init__` back-edge in `verifiers`) and reconcile the 96
   `noqa: PLC0415` deferred imports, which Bazel would resurface as declared-dep
   cycles. This is real architectural work, not configuration.
2. **A dependency lockfile (C3).** `rules_python`/`pip_parse` requires a fully-pinned
   lock; the repo has unpinned `>=` floors and no lock artifact.
3. **A hermetic-closure story for `torch` and `pysr`/Julia (C3/C8).** `rules_python`
   does not manage a Julia toolchain; `torch` at 1.1 GB makes ML cache blobs and any
   Lambda packaging fight the artifact-size ceiling.
4. **Python 3.13+ if durable functions are wanted (C9).** The loop orchestrator
   premise needs a runtime bump from the current 3.12.

Blockers 1 and 2 are exactly the prerequisites the do-less baseline addresses -- which
is why do-less is the correct first move whether or not a build tool is ever adopted.

---

## Quantified Findings

| Metric | Value | Source |
|---|---|---|
| First-party Python | 120 modules / ~36.5k SLOC (scripts 71 / 30.3k, src 49 / 6.2k) | `find`/`wc` |
| Tests | 104 files / 42.6k LOC (more test LOC than source) | `find`/`wc` |
| Markdown / Terraform / JSON | 284 / ~70k LOC ; 22 / ~7k LOC ; 571 files | `find`/`wc` |
| Import graph | 120 nodes, 213 edges, avg fan-out 1.77, 19 packages | `ast`+Tarjan analyzer |
| Dependency-closure size | mean 6.9 (5.7%), median 1 (0.8%), p90 30 (25%), max 40 (33.3%) | analyzer |
| Highest-closure module | `scripts.validate` = 40 modules (33.3%) | analyzer |
| God-modules (fan-in) | ops_writer 12, s3_log_store 12, aws_profile 11, src.common.config 11 | analyzer |
| Import cycles | 3 (verifiers 6-node, ops_data_portal/executor 5-node, exec_rec/batch 2-node) | analyzer |
| Function-local imports (`noqa: PLC0415`) | 96 | grep |
| Dynamic imports | importlib/spec_from_file_location in 1 file; `__import__` 0; star 0 | analyzer |
| Third-party deps / pinned | ~27 / unpinned (`>=`), no lockfile | `requirements*.txt` |
| Heaviest deps | torch 1.1 GB; pysr -> Julia runtime | `du`, `requirements.txt` |
| `validate.py` | 2604 lines (Decision 43 waiver records 1198), ~25 `validate_*` fns, no registry | `wc`, grep |
| `test_validate.py` | 2786 lines, 319 patch sites, 85 subprocess mocks | `wc`, grep |
| Python version | 3.12 (CI, ruff target, Lambda runtime) | pyproject, workflows, terraform |
| Coverage gate | `fail_under=37`, `source=["src"]` (scripts/ excluded) | pyproject |
| Mutation / property testing | none (`mutmut`/`cosmic-ray`/`hypothesis` absent) | `pip show` |
| Agent loop side effects | 172 subprocess + 97 git + 21 LLM | grep |
| CodeBuild today | 0 (CI = GH Actions + OIDC, CD.21) | terraform grep |

---

## Design Assumptions vs Repo Reality (highest-impact divergences)

| The conversation assumed... | The repo shows... |
|---|---|
| A polyglot codebase where Bazel's cross-language graph pays off | One language (Python) + Markdown; no compile step |
| Gazelle toil is the adoption risk | The graph is static-clean; the real risk is **cycles** Bazel refuses to build |
| The dependency closure is the thing only Bazel gives you | The closure is already computable (`ast`/`networkx`) and already drives `pytest --picked` |
| A clean acyclic graph to slice into targets | 3 cycles + 96 deferred imports hiding more |
| A working build/packaging system to carve a subtree from | No build system; `setup.py` is an env bootstrap; no lockfile |
| A tests-with-teeth + monitor baseline to build on | 37% coverage scoped away from `scripts/`; no mutation/property testing |
| Durable functions slot onto the loop | Python 3.12 (need 3.13+) and ~290 side effects to wrap |
| The repo wants automatic transitive dependency resolution | Decision 79 (today) explicitly chose per-Lambda manifests with **"no transitive resolution"** |

---

## Tool-Choice Assessment

| Dimension | Bazel | Pants | Do-less baseline (recommended) |
|---|---|---|---|
| Fit for single-language Python | Poor (built for polyglot scale) | Good (Python-native) | Excellent |
| BUILD-authoring ceremony | High (Gazelle + manual annotation of dynamic edges) | Low (automatic dep inference) | None |
| Requires acyclic graph | Yes (hard) | Yes (hard) | `import-linter` *enforces* it -- turns the blocker into a guardrail |
| Requires lockfile | Yes | Yes | Yes (`uv`/`pip-tools`) -- and useful on its own |
| Handles torch/Julia hermetically | No (Julia outside rules_python) | Partially | N/A (keeps venv) |
| Delivers affected-set test selection | Yes | Yes | Already present (`pytest --picked`, Decision 73) |
| Delivers the dependency-closure "oracle" | Yes | Yes | Yes (`ast`/`networkx`, already installed) |
| Ongoing agent-maintained cost | High (BUILD files per target, per change) | Medium | ~Zero |
| One-time human setup | Very high | High | Low (two pip installs + contracts) |

**Conclusion:** the do-less baseline delivers the genuinely valuable subset of the
Bazel promise (cycle prevention, layered-architecture enforcement, affected-set
selection, a pinned closure) at near-zero adoption and ~zero ongoing cost. If a build
orchestrator is ever truly needed, **Pants** -- not Bazel -- is the candidate, because
the codebase is pure-Python and Pants removes the Gazelle ceremony that is Bazel's
dominant cost here.

---

## Recommendation (phased)

**Phase 0 -- do-less, now (one-time human setup, then ~zero ongoing).**
- Add **`import-linter`** contracts: forbid import cycles and declare a layered
  architecture. This converts the C5 blocker into a standing guardrail and -- crucially
  -- prevents the validate.py registry refactor from regressing into another
  `verifiers`-style cycle. *Telemetry signal it addresses:* the recurring
  cycle/coupling debt that 96 deferred imports already evidence.
- Generate a **lockfile** (`uv pip compile` or `pip-tools`). Delivers the C3
  hermeticity, removes the unpinned-floor risk, and is the prerequisite any future
  build tool would need anyway.
- Keep the existing Decision 73 diff-aware CI (`pytest --picked`, ruff-on-changed) and
  `--disable-socket` hermeticity. They already are the "incrementality + hermeticity"
  Bazel was being considered for.
- (Independent of build tooling) raise the C10 baseline: widen coverage `source` to
  include `scripts/`, and pilot property tests (`hypothesis`) on the highest-closure
  modules. (A diff-line-coverage ratchet for this gate is already a ROADMAP-PLATFORM
  item, so this aligns with planned work rather than introducing a new gate.)

**Phase 1 -- narrow Pants spike, only on a measured signal (deferred).**
Reconsider a build orchestrator *only if* one of these telemetry signals appears:
(a) CI wall-clock regresses in a way `pytest --picked` cannot address (measure: PR
`--pre` tier p50/p95 duration vs the 5-minute budget already tracked by
`_FAST_TIER_BUDGET_SECONDS`); or (b) the greenfield Lambda/executor rebuild needs
reproducible, dependency-pinned multi-artifact builds that the Decision-79 manifest
flow cannot satisfy. If triggered, time-box a **Pants** spike scoped to the *new*
executor subtree only -- never a whole-repo migration. *One-time human setup; not
agent-maintained until proven.*

**Not recommended at any phase:** a whole-repo Bazel migration; a Lambda-hosted
validator registry (see Linkage); authoring the above as a STRATEGIC plan or executor
recommendations while the Decision 67/79 STRATEGIC freeze holds.

---

## Linkage: `validate.py` Decomposition (the originating question)

The Bazel question arose as a deviation from decomposing the `validate.py` monolith.
The two are the **same problem at two altitudes**: the refactor's real goal is
modularization + import hygiene; Bazel/Pants are tools that *reward* good
modularization and *refuse to build* bad modularization -- they do not *perform* the
decomposition, they presuppose it. validate.py is the worst-precondition file in the
repo (2604 lines vs its 1198 waiver; highest closure at 33.3%; the lone `importlib`
user; a 2786-line / 319-patch test). So adopting a build tool first walks straight
into the cycle wall, while decomposing needs no build tool at all.

**Decompose tool-free, as a separate IMPLEMENTATION plan** (not STRATEGIC -- the
freeze holds), using the acyclic check-plugin registry pattern, learning from the
`verifiers` cycle which is *exactly* this pattern done wrong:

1. A `scripts/validators/` package; normal imports replace the
   `spec_from_file_location` path-loading.
2. `validators/base.py` (leaf): a `Check` protocol -- `name`, `inputs`, `run(ctx)`.
   Imports no checks. (Mirrors the clean `Verifier` ABC in `verifiers/harness.py`.)
3. `validators/checks/*.py`: one module per check (~25), each importing only `base`.
4. `validators/registry.py`: imports each check, builds the canonical list.
   `registry -> checks -> base`, one-directional, **acyclic** -- and the single source
   of truth the CLAUDE.md invariant requires (validate.py becomes a thin entrypoint).
5. `import-linter` enforces `checks -/-> registry` and the layering.
6. Fix the `verifiers` back-edge first as the smaller reference refactor.

**Check selection is affected-set, not a static tier.** A per-check `tier="fast"`
label is a hand-maintained latency partition -- the `_FAST_TIER_BUDGET_SECONDS=300` +
breach/bypass-rec + `--ignore-budget` machinery in validate.py exists only to police
it. Instead, each `Check` declares its **inputs** (globs) or `always`; the runner runs
a check iff its inputs intersect the diff. `--pre` is *already* diff-aware in its lint
scope (ruff/mypy on changed files via `get_changed_files()`); this extends that
diff-awareness from lint scope to check selection, generalizing what `pytest --picked`
and ruff-on-changed already do (Decision 73). Two guardrails: (a) global/stateful
invariants (outbox staleness, schema-of-record, warehouse-write scan) declare
`always`, since no code change triggers them; (b) plain-Python affected-selection is
not hermetic, so an under-declared input silently skips a check -- therefore the
**PR/edit tier is affected-derived (fast, advisory) while the main/full tier runs
everything (authoritative)**, exactly the existing PR-vs-main split. The per-check
fast/full *label* disappears; "fast" becomes an emergent property of diff size.

**The validator registry stays a local importable package -- it is not a Lambda.**
Validation reads the working tree/diff (data gravity is local), is latency-sensitive
(the edit loop), deterministic, and offline-capable. A Lambda would invert data
gravity (ship code to the function), hit the 262 MB artifact ceiling (the import-smoke
check needs the dep closure; torch is 1.1 GB), add cold-start latency to `--pre`, and
create a second execution surface that breaks the single-source-of-truth invariant
(CI and the edit loop must run the same checks). The Lambda execution model belongs to
the **executor/agent-loop/artifact-build** layer (C8/C9) that Decision 79 unblocked --
a different layer with a long-running, side-effectful profile. Do not conflate the
synchronous, local *check registry* with the asynchronous, remote *executor*.

Notably, the validator design (each unit declares its inputs; a coverage check
enforces completeness) is the same shape Decision 79 just ratified for Lambdas
(`src/lambdas/<slug>/manifest.yaml` + `validate_lambda_manifest_coverage`). The repo's
own chosen direction is explicit, declared, non-transitive manifests -- not an
automatically-inferred build graph.

---

## Unverifiable Claims (and what would settle each)

| Claim | Why unverifiable from the repo | What would settle it |
|---|---|---|
| Bazel/Pants yields a net CI wall-clock win at this scale | No build-tool run exists to benchmark; depends on cache hit-rate | A time-boxed spike measuring PR p50/p95 vs the current `--picked` baseline |
| Agents will reliably maintain BUILD files without toil-avoidance | No BUILD files exist; behavioural claim | A trial subtree observed over several agent edit cycles |
| Concurrent agents redundantly rebuild enough to justify bazel-remote on Fargate (C8) | No concurrency telemetry for builds today | Production build telemetry after any Phase-1 spike |
| Pants handles the torch/Julia closure acceptably | Not installed; depends on Pants' Python backend behaviour with native/Julia deps | A scoped Pants spike on an ML target |

---

## Relationship to Existing Decisions

- **Decision 43** (Directed Growth): validate.py is a named complexity waiver (1198
  SLOC) now at 2604; this assessment's recommended decomposition is the remediation.
- **Decision 60 / Decision 73** (two-tier + diff-aware CI): the do-less baseline
  extends, rather than replaces, the existing PR-vs-main, `pytest --picked` model.
- **Decision 75** (Frame-Lock Anti-Pattern): this assessment is the frame-challenge --
  the verdict is "do-less + decompose," reached by falsification, not by frame-locking
  toward "adopt Bazel."
- **Decision 67 / Decision 79**: the Lambda-deploy clause is lifted (per-Lambda
  manifests, today); the **STRATEGIC-plan freeze is retained**, so the phased
  recommendation is narrative-only and no executor recs are minted.
- **Decision 68 / CD.21**: CI is GitHub-hosted + OIDC; the EC2 runner is retired -- the
  C8 baseline targets that substrate.
- **Decision 65** (agent-first / no transient briefing docs): this is a durable
  decision-input artefact graduating to Decision 80, not a stored narrative summary.
- **Decision 48**: V1 is the correct verification tier for this docs-only deliverable.

---

## Constraints

- Read-only assessment: no code, config, or BUILD/WORKSPACE/`pants.toml` files written.
- STRATEGIC freeze (Decision 67, retained by Decision 79): no STRATEGIC plan; no
  executor recommendations from the phased recommendation.
- Negatives are stated plainly: the cycles, the 3.12-vs-3.13 gap, and the 37%/`src`-only
  coverage baseline are blockers, not caveats.
- The verdict graduates to Decision 80 after the report-critique gate passes.
