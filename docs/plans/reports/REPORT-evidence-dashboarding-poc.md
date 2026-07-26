# REPORT: Evidence as a human-facing analytical presentation layer (hypothesis stress test)

> Stress test / spike note for platform tier items **T2.52** (analytical-semantic layer, the
> prerequisite) and **T2.53** (bounded presentation-layer proof of concept), and candidate decision
> **CD.42**. Not an implementation, and not an adoption. The owner authored a hypothesis that
> Evidence (evidence.dev) should become this repository's standard human-facing analytical
> presentation layer; this report tries to falsify it. The roadmap entries are the canonical forward
> intent and CD.42 is the pattern decision; this report is the design rationale they point back to.
>
> **Scope note.** "Report-only" means nothing is built, installed or adopted. It does not mean
> nothing changes: the authoring plan also enacts roadmap bookkeeping -- two new deferred tier items,
> one new pending candidate decision, and a surgical amendment to the exit criteria of a third,
> pre-existing item (T2.51, section 3.3). Those edits are forward intent and routing, not
> implementation, and T2.51's criteria were all verified `status: open` first so no provenance was
> re-pointed (Decision 136 / CD.39).
>
> **Evidence base.** npm figures in section 5 were measured during authoring and are explicitly
> point-in-time; section 11.2 converts them into thresholds to be re-measured rather than
> conclusions to be inherited.

## 1. Verdict of this report

The hypothesis's **architecture is sound and is not what fails**. Separating a governed dataset
boundary from a presentation layer, keeping Git authoritative, and rendering to an authenticated
static artifact are all correct for this repository, and no active decision contradicts that shape.

What fails is **testability today**. Three preconditions block a meaningful proof of concept, and
none of them are about Evidence's quality:

| # | Precondition | Owner |
|---|---|---|
| P1 | No dataset at an analytical grain exists to present. The `NAMED_READS` registry is 12 verbs over 3 tables; three use aggregate SQL, but all are single-table operational counters. | T2.52 |
| P2 | Standing human-audience Markdown pages are forbidden as repository artefacts (Decision 127), and the obvious carve-out precedent does not transfer (section 4.1). | CD.42 / T2.53 |
| P3 | Evidence's multi-file static output collides with CD.41 invariant (b), an open question `REPORT-cost-visibility-dashboard.md` section 5.4 deliberately deferred (section 4.2). | T2.53 |

Therefore: **the hypothesis is not rejected and not adopted. It is scoped, sequenced behind a
prerequisite, and given pre-committed falsification criteria** (section 11). Both tier items are
`deferred_post_mvp` (Decision 93): a human-facing analytical layer sits outside the
`rec -> implement -> validate -> merge -> deploy -> observe -> next rec` loop that defines the
Platform MVP boundary, and building a presentation layer before a governed dataset exists to
present is the build-ahead-of-need shape Decision 87 consciously refused.

A secondary finding changes the shape of the eventual test: **Evidence should not be evaluated in
isolation**. Section 8 establishes a three-way comparison (Evidence / Astro-with-charts /
Observable Framework) as the correct experiment.

**One measured result is significant enough to record in the verdict.** Measured on Evidence's
**documented scaffold** (`npx degit evidence-dev/template`, the adoption-relevant artifact --
sections 5.3, 5.5):

- **T3 (install integrity): PASSES.** The scaffold installs cleanly -- exit 0, 1,311 packages, no
  `--legacy-peer-deps`. An earlier draft of this report claimed the opposite from a bare-package
  install; that was measuring the wrong artifact and is corrected here.
- **T1 (unresolvable advisories): FAILS, irreducibly -- but on one advisory, not four.** The scaffold
  carries **78 advisories (10 critical, 26 high, 39 moderate, 3 low)** across **1,387 dependencies**,
  of which **19 report `fixAvailable: false`**. Pruning to the four packages a cost dashboard needs
  cuts the tree to 928 dependencies and 46 advisories, and the unresolvable-critical entries do not
  move. **But those four entries are one CVE counted four times** (section 5.3): the sole
  unresolvable critical *root* advisory is **`vitest`** -- "when the Vitest UI server is listening,
  an arbitrary file can be read and executed" -- which npm audit propagates up the chain
  `vitest -> @evidence-dev/sdk -> @evidence-dev/tailwind -> @evidence-dev/core-components`, since it
  reports severity against every ancestor. Evidence's own packages appear as *ancestors of* the
  vulnerability, not as vulnerable code.
- **T4 (advisory responsiveness): unmeasured.** This report has not inspected the upstream issue
  tracker, which is the only thing T4 measures. Recorded as unmeasured -- an earlier draft inferred
  it from the T1 advisory set, which made the two thresholds the same test (section 11.2).

**What survives, stated at its true weight.** The failure is irreducible for a real reason:
`@evidence-dev/sdk` declares `vitest` in `dependencies` rather than `devDependencies` -- a test
runner shipped as a runtime dependency, which is an upstream **packaging defect**. No consumer-side
pruning removes it.

But the exposure is narrower than "unfixable criticals in Evidence's core": the vulnerable surface
is `vitest --ui`, a test-runner dev server that `evidence build` never executes. **The real cost is
an unresolvable, permanently-open critical Dependabot alert on a public repository** whose security
surface Decision 83 treats as continuously live-verified evidence -- a governance and signal-hygiene
cost, not an exploitable production path. That distinction is load-bearing, and an earlier draft of
this report overstated it.

This is not a final verdict -- thresholds are re-measured at proof-of-concept time, and a failing arm
does not reject the class. But the burden of proof has shifted, and the report says so rather than
deferring an already-visible result.

## 2. What the hypothesis gets right

Recorded explicitly so the stress test is not mistaken for a rejection:

- **Git-authoritative presentation is the correct constraint for this repository.** A
  browser-managed metadata database as the practical authority for charts and layouts is
  incompatible with the agent-first model (NS.4, Decision 86): agents would operate an external UI
  or manipulate exported metadata whose running state drifts from Git.
- **The presentation layer must not become a second semantic authority.** Business aggregation,
  grain, join semantics, actual-versus-estimated classification, authorized columns and stable
  ordering belong server-side. This is the correct reading of the existing boundary.
- **Named verbs are the right precedent to extend.** The registry already binds each verb to a
  table, fixed SQL, named parameters, a description and pagination behaviour, and the response
  stamps `registry_version`, which gives a real basis for build-time compatibility checking.
- **Contract-derived fixtures are the right agent development loop.** Deterministic fixtures that
  exercise adversarial presentation states beat incidental production data, and they keep the
  development loop free of credentials and egress.
- **Asset-oriented transformation with named verbs as serving leaves is correct.** Verb-to-verb
  orchestration would compound Lambda latency, obscure lineage and prevent atomic publication.
  Section 9 confirms the repository has no derived-asset write mode today, so this is a real gap.

## 3. Premise re-grounding

Four premises in the hypothesis were checked against the live repository. Two were owner-corrected
during scoping and are recorded here in their corrected form so the eventual proof of concept is
not built against a misreading in either direction.

### 3.1 Caller SQL at the read boundary (design constraint, not a defect)

`docs/contracts/ducklake_reader.yaml` documents a `query_ops` verb accepting a caller-supplied
single-statement read-only `SELECT`/`WITH`. Decision 84 I-3 **retains it explicitly for the data
quality harness and marks it for restriction or retirement in a follow-up**. It is therefore a
sanctioned, scheduled-for-retirement exception, not a precedent, and the hypothesis's constraint
states the target invariant correctly.

Two precisions matter for adapter design, because the boundary is more permeable than "one
scheduled-for-retirement exception" suggests:

- **`query_ops` has two live call sites, not one.** The DQ harness
  (`scripts/data_quality_execute.py`) is the sanctioned consumer, but
  `src/common/iceberg_reader.py` also exposes it through a **generic `reader.query()` path**
  available to any caller of that module. The second is the one that matters for adapter design: it
  is a general-purpose door, not a harness-specific one.
- **The FROM target is caller-controlled.** `docs/contracts/ducklake_reader.yaml` states plainly
  that `_history` and other `ops_*` tables **are** reachable, and that the boundary is "read-only
  SELECT plus the S3-read-only IAM role", *not* current-projection-only. It also warns that the
  handler docstrings claiming otherwise are stale.

**The constraint that survives, and that the proof of concept must honour:** a presentation-layer
source adapter binds to `named_read` verbs **only**. It must not become `query_ops`'s next tenant --
a presentation layer is a durable, load-bearing consumer, and wiring one there would convert a
retiring exception into something that cannot be retired.

**And it must not bind to `read_ops_current` either.** That verb takes a structural
`{column, value}` filter rather than SQL, so an adapter using it would satisfy the *letter* of "no
caller SQL crosses the boundary" while bypassing named verbs entirely and re-acquiring exactly the
freeform-query semantics the constraint exists to prevent. The invariant is **"named verbs only"**,
not "no SQL"; section 11.1 states it in that stronger form deliberately.

### 3.2 No dataset at an analytical grain exists yet (the prerequisite, not an objection)

The `NAMED_READS` registry (`src/common/ducklake_scd2_schema.py`, `NAMED_READS_VERSION = 3`)
contains **12 verbs over 3 tables** -- `ops_recommendations`, `ops_decisions`,
`ops_priority_queue`.

Precisely: **three of those verbs already use aggregate SQL** -- `count_by_status`
(`GROUP BY status`), `forward_fix_recursion` (`GROUP BY file HAVING COUNT(*) >= 3`) and
`decisions_max_updated` (`max(last_updated_timestamp)`). What none of them does is aggregate at an
**analytical/business grain**: there is no time bucketing, no dimensional breakdown, no cross-table
join, no actual-versus-estimated classification, and no versioned analytical response schema. They
are single-table operational counters and scalars that feed preflight gauges.

This *strengthens* rather than weakens the case for T2.52: the registry pattern already
accommodates aggregate SQL behind a named verb, so T2.52 is an **extension of a proven pattern**,
not the invention of a new one. The hypothesis's claim that named verbs are the pattern to follow is
correct. What is genuinely absent is the analytical grain, which is why T2.52 is scoped as a
prerequisite of T2.53 rather than assumed available.

### 3.3 Cost data and DuckLake (routing amendment, not a re-scope)

DuckLake is Parquet-in-S3 with catalog metadata in Neon. T2.51's specified snapshot grain -- one
row per vendor per cost-date per as-of/pull-date, append-only, event-time-partitioned -- is already
DuckLake-shaped. The only real finding is that **T2.51 as written** specifies a bespoke private-S3
snapshot plus a script renderer, with no governed table and no verbs.

T2.51's exit criteria c2/c3 are therefore amended to route the snapshot into DuckLake as a governed
table served by named verbs. All of T2.51's criteria were `status: open` at amendment time, so no
`met_by` provenance is re-pointed (Decision 136 / CD.39).

### 3.4 Telemetry and data quality have no live data (dependency mapping)

Preflight reports the telemetry store as `not migrated (Phase 4)` (Decision 84 Phase 4 / T2.36) and
data quality coverage as **0 tables, 0 checks, no run recorded**. Both are named in the hypothesis
as extension targets. This is not an objection -- establishing those dependencies is what roadmap
placement is for -- but it does mean **no candidate tenant has a live governed dataset today**,
which is the substantive reason both items are deferred rather than eligible.

## 4. Structural collisions (blocking preconditions)

These are the two findings that make adoption materially more expensive than the hypothesis
assumes. Neither is a quality judgement about Evidence.

### 4.1 Decision 127 -- standing human-audience prose (P2)

Decision 127 clause 1: the only prose sanctioned for permanent storage in this repository is
content whose audience-of-record is an agent; no document whose audience-of-record is a human may
be stored as a standing repository artefact. It is enforced repository-wide by
`validate_prose_allowlist` over every tracked `.md` file, in both presubmit tiers.

Evidence's native authoring idiom is **standing Markdown pages whose audience-of-record is a human
dashboard viewer**. Every committed dashboard page is exactly the artefact class Decision 127
forbids. This report and the plan are unaffected (`docs/plans/**/*.md` is sanctioned class (d)); the
**adoption** is what collides.

**The obvious remedy does not work.** The apparent precedent is Decision 101(c)'s `marketing/**`
carve-out, and the temptation is to mirror it. But 101(c) rests entirely on **one-way
downstream-ness**: marketing prose is authored for a human audience outside the agent loop and is
never fed back into any agent's context, which is why it is not "prose whose audience-of-record is
a human" in the sense Decision 127 forbids storing. An **internal analytical dashboard fails that
test by construction** -- it exists to inform how the operator directs agents, so it feeds back into
the loop. The mirror analogy does not carry the exception's load-bearing property.

**Consequence:** a Decision-127 amendment must be argued on its own grounds, and "the amendment is
unobtainable" is a legitimate outcome. This is a pre-committed **reject** criterion (section 11),
not a checkbox to be ticked during implementation.

#### 4.1.1 Principle versus enforcement mechanism -- and why it decides the comparison

The guard's *enforcement* is narrower than the decision's *principle*, and the gap is load-bearing.
`validate_prose_allowlist` enumerates its corpus via `git ls-files '*.md'`
(`scripts/checks/hygiene/validate_prose_allowlist.py`, `_tracked_md_files`). It therefore inspects
tracked **`.md` files only**. Applied to the comparison set:

| Candidate | Page file type | Trips the guard as written |
|---|---|---|
| Evidence | `.md` | Yes |
| Observable Framework | `.md` | Yes |
| Astro (+ charting library) | `.astro` (and `.mdx` if used) | **No** -- passes trivially |

Two readings, and the report deliberately does **not** pick one, because picking one is T2.53's job:

- **Principled reading.** Decision 127's rule is about *audience-of-record*, not file extension. A
  human-audience dashboard page written in `.astro` is the same artefact class as one written in
  `.md`; the guard simply does not reach it yet. Under this reading the precondition binds **all
  three candidates equally**, and "choose Astro instead" is **not** an escape from P2.
- **Mechanical reading.** The guard is the operative control, and `.astro` files are outside it.
  Under this reading Astro sidesteps P2 today -- but only as an artifact of enforcement scope, which
  is exactly the kind of accidental exemption that gets closed the moment someone notices. The
  mechanical reading is further weakened by the guard **failing open**: it skips silently when the
  `prose_allowlist` key is absent from the file router, so "the guard is the operative control" is
  a weaker claim than it first appears.

**This must be resolved before, not during, the proof of concept**, because it changes what the
experiment is measuring. If the principled reading holds, P2 is a property of the whole
code-defined-dashboard class and an unobtainable amendment rejects all three arms. If the mechanical
reading holds, Astro enjoys an advantage that the repository would probably want to remove on
sight -- which makes it an unsound basis for a durable platform choice. Resolving it is criterion
c5's real content (section 11.2 item 1), and section 13 records it as the question that gates the
rest.

### 4.2 CD.41 invariant (b) -- multi-file static serving (P3)

CD.41 invariant (b): the confidential payload never transits Cloudflare; it flows AWS to browser
via an in-AWS-minted, TTL-bounded, single-object presigned GET, or a direct-from-AWS origin.

Evidence's template depends on `@sveltejs/adapter-static` and emits a multi-file SvelteKit
application, including per-query prerendered result files under
`template/src/pages/api/prerendered_queries/[query_hash].arrow`. A multi-asset site is precisely
the case the single-object presigned redirect does not cover.

`REPORT-cost-visibility-dashboard.md` section 5.4 already recorded this as an unresolved open
question and deliberately deferred it. Adopting any multi-file static renderer **forces** its
resolution, and the tension is real rather than merely deferred:

- CloudFront/OAC placed **behind** Cloudflare Access **breaks (b)** -- Cloudflare would proxy every
  asset byte.
- Preserving (b) forces the asset origin onto a **non-Cloudflare-proxied** hostname, which loses the
  Access gate and requires re-implementing authentication at the edge (a CloudFront Function JWT
  check, or signed cookies).

**The TTL dimension is the harder half, and it is not about file count at all.** CD.41 fixes the
presigned GET at **<= 5 minutes** and explicitly characterises it as a replayable bearer capability.
A dashboard is not a single load: Evidence fetches `[query_hash].arrow` files **lazily, at
interaction time**, so a session lasting longer than five minutes hits link expiry **mid-session**
rather than at page load. Every subsequent interaction needs a freshly minted capability.

That collapses the option space. A one-shot 302-to-presigned-URL redirect cannot serve an
interactive session under a five-minute TTL, so the compliant mechanisms reduce to **edge-side JWT
verification or signed cookies** at a non-Cloudflare-proxied origin -- not one of three roughly
equal options, but effectively mandatory. Single-object bundling survives only for a genuinely
static, non-interactive artifact, which is the MVP instance T2.51 already contemplates.

CD.41 fixes the invariant, not the mechanism, so a compliant answer exists. It is engineering work
that the hypothesis does not account for, and ownership of the question moves to T2.53.

## 5. Upstream and supply-chain evidence

All figures below were read from the npm registry during this session and are reproducible with
`npm view <package> time --json`. They are point-in-time and must be **re-verified at proof-of-
concept time**, not carried forward as settled.

### 5.1 Release cadence

`@evidence-dev/evidence` publish counts per year: **2021: 11, 2022: 64, 2023: 406, 2024: 179,
2025: 13, 2026: 1**. Latest is `40.1.8`, published **2026-02-06**. The major version has been
frozen at 40 since **2024-12-10**. Sibling packages `@evidence-dev/core-components` (5.4.2),
`@evidence-dev/sdk` (4.0.2) and `@evidence-dev/duckdb` (2.0.1) all last published on that same
**2026-02-06** date.

**The obvious readings are both wrong, and the timeline is why.** Within the v40 line, `40.1.2`
shipped 2025-04-11 and `40.1.3` did not arrive until 2025-11-03 -- a **prior gap of roughly seven
months that subsequently resolved**. That single fact retires both tempting narratives:

- It **weakens the adverse reading**: the current gap of roughly five to six months is *within this
  project's own observed normal*, so silence of this length is not evidence of abandonment.
- It **also destroys the charitable "stabilisation curve" reading**: a project that has already gone
  quiet for seven months and come back is not on a smooth maturation glide path; it is a project
  with irregular, bursty maintenance.

The honest conclusion is that **publish cadence alone cannot answer the liveness question here**,
in either direction. What actually matters for a load-bearing dependency is responsiveness *to
security advisories* (section 5.3 shows why that is the binding constraint), which cadence does not
measure. The correct treatment is a **gating liveness check with a stated threshold** (section 11),
assessed on advisory response rather than publish frequency.

**Dist-tags, examined (they are not a live release train).** The package publishes `legacy@23.0.4`,
`features-a@27.0.0-features-a.8`, `features-b@36.0.0-features-b.6`,
`dropdown-preview@39.1.4-dropdown-preview.0` and `next@0.0.0-52469075` alongside `latest@40.1.8`.
Every one trails the current major, several by more than a decade of major versions. These are
**stale branch tags, not maintained channels** -- so there is no parallel active development stream
that the `latest` cadence is failing to capture, and examining them mildly **strengthens** the
adverse reading rather than qualifying it.

### 5.2 Comparative liveness

| Package | Latest | Last publish |
|---|---|---|
| `astro` | 7.1.3 | 2026-07-20 |
| `@astrojs/starlight` | 0.41.4 | 2026-07-22 |
| `@observablehq/framework` | 1.13.4 | 2026-04-06 |
| `@evidence-dev/evidence` | 40.1.8 | 2026-02-06 |

### 5.3 The dependency surface is frozen, and that is a security posture rather than upgrade friction

`@evidence-dev/evidence@40.1.8` declares **10 dependencies, 6 devDependencies and 13 peer
dependencies**, with exact pins across the framework tier. The split matters: `@sveltejs/kit 2.8.4`
and `@sveltejs/adapter-static 3.0.1` are **direct dependencies**, while `svelte 4.2.19`,
`vite 5.4.21`, `typescript 5.4.2` and `tailwindcss 3.4.18` are **peer dependencies** the consuming
project must supply at those exact versions. Note Svelte **4**, not 5.

**Measured on the adoption-relevant artifact.** The figures that matter are the **scaffold's**, not
the bare package's: a bare `npm install @evidence-dev/evidence` produces a tree nobody would ship
(section 5.5 explains why it is only a diagnostic). Three measurements, all reproducible:

| Install | Dependencies | Advisories (C/H/M/L) | `fixAvailable: false` |
|---|---|---|---|
| Scaffold, as shipped (14 connectors) | **1,387** | **78** (10 / 26 / 39 / 3) | **19** (4C, 2H, 13M) |
| Scaffold, pruned to 4 needed packages | **928** | **46** (7 / 15 / 23 / 1) | **12** (4C, 1H, 7M) |
| Bare package (diagnostic only) | 641 | 30 (3 / 21 / 5 / 1) | 0 |

**The decisive finding is what pruning does not fix.** The template ships 14 `@evidence-dev/*`
dependencies by default, of which ten are datasource connectors a cost dashboard has no use for
(BigQuery, Databricks, Snowflake, MSSQL, MySQL, Postgres, Trino, MotherDuck, SQLite, source-
javascript). Removing them cuts a third of the tree and 41 percent of the advisories -- but the
unresolvable-critical entries are identical in both rows.

**Those entries are one CVE, not four.** npm audit reports severity against every *ancestor* of a
vulnerable package, so tree depth manufactures entries. Reading the `via` chains:

| Entry (`fixAvailable: false`, critical) | Root advisory? | Reached via |
|---|---|---|
| `vitest` | **yes** | the CVE itself |
| `@evidence-dev/sdk` | no | `@vitest/coverage-v8` -> `vitest` |
| `@evidence-dev/tailwind` | no | `@evidence-dev/sdk` |
| `@evidence-dev/core-components` | no | `@evidence-dev/tailwind` |

Enumerating distinct root advisories across the pruned tree yields **exactly one unresolvable
critical**: `vitest`, "when the Vitest UI server is listening, an arbitrary file can be read and
executed."

**Why it is nonetheless irreducible, and what it actually costs.** `@evidence-dev/sdk` declares
`vitest` in `dependencies`, not `devDependencies` -- a test runner shipped as a runtime dependency.
That is an upstream **packaging defect**, and no consumer-side pruning or configuration removes it.
But the vulnerable surface is `vitest --ui`, a test-runner dev server never executed by
`evidence build`. So the cost is **a permanently-open, unresolvable critical Dependabot alert on a
public repository** -- a governance and signal-hygiene problem against Decision 83's continuously
live-verified security surface -- rather than an exploitable production path. Both halves matter:
the alert is real and cannot be closed; the exploit path is not there.

Note also the direction of the earlier error: the bare tree showed **zero** `fixAvailable: false`
advisories, so measuring the wrong artifact simultaneously **over-stated** the install problem and
**under-stated** the security surface by roughly 2.4x. Both corrections point the same way -- the
public-repository alert argument below is stronger than the first draft claimed, not weaker.

**Why that lands harder in this repository than in most.** This repo is PUBLIC, with GHAS,
Dependabot alerts and a standing `ghas-probe` monitor whose dated evidence is recorded against
Decision 83. Two things follow that are easy to conflate and must not be:

- **Dependabot *version updates*** are configured per-ecosystem in `.github/dependabot.yml`
  (currently `pip` and `github-actions` only). Adding an npm entry is a governed `.github/` and
  `terraform/github/` surface change under Decision 83.
- **Dependabot *alerts* are repository-wide and automatic.** They fire on any manifest in the repo
  **regardless of `dependabot.yml`**, and on a public repository they are visible security signal.

Adoption therefore injects advisories that **cannot be remediated forward** onto a public security
surface that Decision 83 treats as continuously live-verified: **6 unresolvable high-and-critical**
as shipped (4 critical + 2 high), or **5** pruned (4 critical + 1 high). The count is smaller than
the headline advisory totals, and that is the point -- these are the ones with no remediation at
all, in either direction. (An earlier draft said "roughly two dozen", conflating the bare tree's 24
*total* high-and-critical with the *unresolvable* subset -- exactly the units error section 11.2's
T1 definition was rewritten to prevent.) Declining to add the npm ecosystem entry does not avoid this; it only removes the
update PRs while leaving the alerts.

### 5.4 Build-time telemetry

`@evidence-dev/telemetry` is a **direct dependency** of the Evidence package. A build-time
phone-home is a governance item under the confidential-data boundary (Decisions 73/83/101), not a
footnote. It must be **explicitly disabled and the disablement verified**, and that verification is
a pre-committed exit criterion rather than a configuration note.

### 5.5 Container feasibility (mixed -- the environment is fine, the install is not)

**The environment is favourable.** The standard ephemeral development container carries Node
**v22.22.2**, npm **10.9.7**, a pre-installed Chromium under `PLAYWRIGHT_BROWSERS_PATH`, and
reachable npm registry access through the agent proxy. The repository currently tracks **zero**
JavaScript or TypeScript files and has no `package.json`, so any adoption introduces the
repository's first Node dependency surface.

**The documented install path works.** `npx degit evidence-dev/template` followed by a plain
`npm install` **succeeds: exit 0, 1,311 packages, no flags**. Evidence therefore **passes T3**.

*(An earlier draft of this report claimed the opposite. It had measured a bare
`npm install @evidence-dev/evidence@40.1.8` into an empty project, which does fail with `ERESOLVE`:
`ts-node@10.9.2` -- pulled in via `postcss-load-config@4.0.2`, a pinned peer of Evidence -- declares
a loose `peer typescript ">=2.7"`, so npm hoists `typescript@7.0.2`, violating
`svelte-preprocess@5.1.3`'s `peerOptional typescript ">=3.9.5 || ^4.0.0 || ^5.0.0"`, itself another
of Evidence's exact peer pins. That draft named the untested scaffold as a bound but wrote the
untested negative into its verdict anyway. Naming a bound is not a substitute for testing something
this cheap.)*

**Why it works is the finding worth keeping, and it is not the reassuring answer.** The template's
`package.json` declares **no** `svelte`, `typescript`, `vite` or `tailwindcss` at all -- only
`@evidence-dev/*` packages. It resolves solely because a **654 KB `package-lock.json` is committed
to the template**. Deleting that lockfile and reinstalling reproduces the identical `ERESOLVE`
(verified).

So the accurate statement is: **Evidence's declared peer graph does not self-resolve under current
npm, and adoption inherits an upstream-authored lockfile as the thing that makes it work.** The
consequences are concrete and belong in the adoption decision:

- The repository does not control its own resolution; it inherits upstream's pinned one.
- Any dependency movement within that tree risks re-entering the unresolved peer graph, which is
  section 5.3's frozen-pin thesis expressed as a lockfile rather than as version ranges.
- Regenerating the lockfile -- something a routine `npm audit fix`, a Dependabot bump, or a
  different package manager may attempt -- is the failure mode to guard against, not an ordinary
  maintenance action.

**Install paths validated:** the shipped scaffold (passes, with lock), the scaffold with the lockfile
removed (fails, `ERESOLVE`), a scaffold pruned to four packages (passes, with lock), and the bare
package (fails). Package managers other than npm were not tested.

## 6. Where the second semantic layer actually lives

The hypothesis lists "its local query behaviour creates an unavoidable second semantic layer" among
its own non-adoption criteria. That risk is **structurally present**, not hypothetical:

- `@evidence-dev/universal-sql` is a direct dependency: Evidence runs its own query engine, with
  build-time materialization and a client-side DuckDB-WASM engine over shipped Parquet/Arrow.
- The template ships `template/src/pages/explore/console/+page.svelte` and
  `template/src/pages/explore/schema/+page.svelte` -- that is, **the deployed artifact carries a
  general-purpose SQL console and schema browser over the shipped data**, not only the curated
  views the author wrote.
- Evidence's authoring idiom places SQL in the page files themselves. Restricting pages to trivial
  passthrough selects over adapter-materialized datasets is possible, but it means **fighting the
  tool's core affordance**, which is a legitimate reason to prefer a different tool rather than a
  detail to be disciplined away.

For a private, single-operator cost dashboard, a shipped query console over one's own data is a
mild concern. As a **standard** presentation layer extended to telemetry, data quality and
eventually product analytics, it is the exact "second semantic authority" the hypothesis says it
wants to avoid. This is the single most likely honest falsifier, and the proof of concept must be
designed to test it rather than to design around it.

## 7. Public-repository exposure

This repository is public. An Evidence build materializes query results to on-disk Parquet/Arrow
artifacts as a normal part of its build.

The exposure is **wider than vendor cost figures**. Decision 111 (ratifying CD.20) holds that the
public surface is a curated portal **rather than an export of operational data**
(`ops_recommendations`, `ops_decisions`, `ops_session_log`, telemetry). A build that materializes
ops-table query results into tracked files is definitionally that export. The existing `never-commit`
hook blocks 12-digit account IDs, secret-shaped strings and ExternalId patterns; it does not cover
cost figures or ops-table extracts.

A `.gitignore` entry is a convention, not a guard. The required control is a **deterministic check**
-- a registered `validate.py` check or a `never-commit` extension following the Decision 104 registry
pattern -- asserting that no build artifact is tracked. Additionally, a production build executed on
a GitHub-hosted runner would transit confidential data through CI; builds against live data belong
in-AWS, or under strict artifact and log discipline.

**There is currently no coverage at all, and the timing is the problem.** `.gitignore` today
contains **no** entry for `node_modules/`, `.svelte-kit/`, `package-lock.json`, `*.parquet` or
`*.arrow` -- unsurprising in a repository that tracks zero JavaScript files, but consequential the
moment one runs an install. Section 5.5 measured that first install at **1,311 packages**, and a
build additionally materialises query results to disk.

So the guard cannot be an **adopt** criterion, because adoption happens *after* the proof of concept
has already run installs and builds on a branch of a public repository. Ignore rules plus the
deterministic check are therefore a **precondition of opening any proof-of-concept branch**, not an
exit criterion of finishing one. Section 11 states it in that position.

## 8. Alternatives adjudicated

### 8.1 AWS QuickSight (managed) -- rejected, on the record

Decisions 100/75 hold that managed services own their primitives and that recording a mechanism as
a human decision does not exempt it from that principle. QuickSight is the managed, AWS-native
option and must be adjudicated by name rather than omitted.

**Discriminator: Git-governed definition versus browser-managed metadata.** QuickSight's analyses,
visuals and datasets live in a service-side metadata store mutated through a console. Definitions
can be exported and re-imported through asset bundles, but the **running state is authoritative and
the export is a projection** -- the inverse of this repository's model, in which Git is authoritative
and the deployed artifact is the projection. Under that model an agent cannot read, diff, review or
regression-test the dashboard definition as a first-class repository artefact, which is precisely
the agent-first property (NS.4, Decision 86) the hypothesis is trying to buy.

This rejection is recorded as a **T2.53 exit criterion requiring re-adjudication against the proof
of concept's own findings**, not as a scoping assumption. If the proof of concept shows the
code-defined route costs materially more than its agent-inspectability is worth, the managed option
must be reconsidered on evidence rather than deemed settled by this report.

### 8.2 Astro with a charting library -- promoted into the comparison set

Starlight specifically is a **documentation theme**: sidebar, navigation, prose, search. It has no
chart primitives, no data layer and no query engine. It is the wrong instrument for dashboarding.

Astro **without** Starlight is a serious candidate: Zod-validated content collections, file-based
routing, static output, and islands for interactivity. It is also the most actively maintained
option in the comparison set (section 5.2), and Decision 101(e) already ratifies Astro plus
Starlight on Cloudflare Pages for the marketing surface, so part of the toolchain cost is sunk
regardless of what the internal surface chooses.

**This arm is not yet measured as specified.** The comparison arm is "Astro **plus a charting
library**", and bare `astro` (296 dependencies, 0 advisories) is not that arm. No charting library
has been named, so the arm's real dependency and advisory surface is unknown on both sides of the
trade -- and a charting library is exactly where an Astro arm would acquire its transitive weight.
Naming the library and measuring the combined tree is a T2.53 task; until then, Astro's clean
supply-chain figures should be read as **provisional and flattering**, not as a result.

The trade is genuine in both directions, and the report does not prejudge it:

- **Astro costs more to build:** no build-time SQL over sources, no automatic Parquet
  materialization, no data-aware chart and table component library, no value formatting. The
  repository would own chart integration, layout primitives, formatting and empty/stale/partial
  states -- the work the hypothesis explicitly does not want to own.
- **Evidence costs more to carry:** a frozen 2024-era pinned SvelteKit tree, a slowing upstream, a
  shipped query console, and an authoring model that collides with Decision 127.

### 8.3 Observable Framework -- included

Same category as Evidence (code-defined, Git-governed, Markdown pages, static build, Node toolchain)
with a different data-loader model and materially more recent upstream activity than Evidence
(section 5.2). Including it is what turns the experiment from a yes/no referendum on one tool into
an actual comparison.

### 8.4 Carried forward from the hypothesis

A custom Dash application for stateful analytical workflows; Grafana for live operational telemetry;
a purpose-built web application for transactional product interfaces; and **no UI layer at all**
where direct agent reports and structured outputs suffice. The last of these remains a live option
and should not be treated as a null result -- a sole-operator platform that reads structured agent
output may simply not need a dashboard.

**CD.42 is scoped to the internal analytical surface only and does not amend Decision 101(e).**
Astro plus Starlight remains the ratified marketing stack irrespective of the proof of concept's
verdict.

## 9. The prerequisite: an analytical/semantic layer (T2.52)

`docs/contracts/data-modeling-standard.yaml` defines exactly **two write modes** -- `scd2`
(mutable-entity ops tables) and `append_only` (insert-once event and telemetry tables) -- and has
**no rebuildable-derived-asset mode**. The hypothesis is right that derived aggregates should not be
forced into SCD2, and that the standard should gain explicit materialization behaviour for
rebuildable derived assets (append-only aggregate snapshots, incrementally replaced time
partitions, versioned materialization runs with a current pointer, or complete atomic rebuilds).

Two constraints bind that work:

- **Decision 137 (CD.9), partition-every-table.** The new mode must not open an unpartitioned-table
  path. Decision 137 is absolute: any relaxation is an amendment naming the per-table exception,
  never a loosened uniform rule.
- **Decision 88, Neon catalog egress budget.** Invariant (ii) forbids re-querying data already in
  the local read cache, and invariant (i) requires warm-connection reuse. A presentation layer that
  queries at build time, plus a new family of aggregate verbs, is exactly the amplification shape
  that produced the 2026-06-15 free-tier breach. An egress-budget criterion applies to both items.

The file carries no top-level `contract:`/`class:` key, so `validate_contract_drift` skips it and
the CD.25 pre-codegen ratification ritual (Decision 118) does **not** apply to this amendment.

T2.52 is scoped separately and deliberately. Bundling the transformation-DAG work into the
presentation-layer proof of concept would make the proof of concept unfalsifiable: a failure could
always be attributed to the immature data layer rather than to the tool under test.

**Why T2.53 depends on T2.52 despite being fixture-driven.** The proof of concept uses no live data,
so at first glance the edge looks like an unexamined frame. It is not. Fixtures are
**contract-derived**: the fixture generator emits data conforming to a named verb's declared
response schema. Without the analytical-aggregate **schema contracts** existing, there is nothing to
derive fixtures from, and the proof of concept would instead be testing invented shapes that no
governed dataset will ever produce. The dependency is on the contracts, not on live data or on
materialized aggregates.

## 10. Proof-of-concept design (T2.53)

Bounded, fixture-driven, ephemeral-container-only, three-way. Emits an adopt / constrain / reject
verdict against criteria committed **before** the experiment runs (section 11).

**Sequencing: measure section 11.2 before building anything.** The supply-chain thresholds are cheap
(minutes per arm, no scaffolding) and can eliminate an arm outright. Scaffolding all three arms
first would spend the expensive effort on arms already known to be rejected -- and on present
figures Evidence would be eliminated before section 6's shipped-query-console question is ever
tested, which this report calls the single most likely honest falsifier. So:

1. **Measure 11.2 per arm** (install integrity, root-advisory counts, tree size, upstream
   responsiveness). Record results; eliminate what fails.
2. **Resolve P0.2** -- the section 4.1.1 principle-versus-mechanism question -- which can eliminate
   the whole class and costs no build effort at all.
3. **Then scaffold and compare** the surviving arms against 11.1.

If step 1 or 2 leaves nothing standing, the verdict is reached without building anything, which is
a successful outcome for a proof of concept rather than a curtailed one.

```
analytical-aggregate named-verb response contracts   (from T2.52)
        |
deterministic fixture generator
        |
        +-- Evidence dev source ------+
        +-- Astro + charts ----------+--> local dev server
        +-- Observable Framework ----+        |
                                       headless Chromium
                                             |
                    DOM checks + axe accessibility + viewport + screenshots
                                             |
                                   agent inspection and iteration
```

**Fixtures must exercise adversarial presentation states**, not just happy paths: empty datasets;
single and many series; long labels; missing or partial periods; actual versus estimated values;
outliers; zeroes; negative adjustments or credits where valid; stale data; wide tables; and both
mobile and desktop viewports.

**Separate mechanizable gates from aesthetic judgement.** The hypothesis conflates them, and the
distinction matters because only the first half can gate CI:

- **Mechanizable (gates):** strict build exits non-zero on a broken query, dataset or component;
  every declared dataset resolves; dataset schemas match their declared contracts; zero browser
  console errors; zero axe accessibility violations at the agreed conformance level; no horizontal
  overflow at the declared viewports; screenshots captured and diffable.
- **Not mechanizable (human):** whether the result is legible, well-proportioned and actually useful
  to the operator. No browser check substitutes for the human looking at it. The proof of concept
  must present screenshots for a human verdict rather than claiming a passing accessibility run
  means the dashboard is good.

A **machine-readable design contract** should govern semantic colours, number formats,
actual-versus-estimated presentation, chart conventions, responsive viewports and missing-data
behaviour, so that individual agents do not invent inconsistent UI semantics. Authoring it is in
scope for T2.53; it is small, and it is the artefact that makes agent-authored dashboards
consistent.

**A failed data refresh must never publish false zeroes or replace the last known-good artifact.**
Loud-fail, never silent substitution (Decisions 55, 62/CD.12), consistent with T2.51's existing
stale-snapshot handling.

## 11. Pre-committed criteria

Committed now, before the experiment, so the verdict is not rationalised afterwards. The criteria
are deliberately split three ways, because the experiment is three-way: what follows applies to
**every** candidate unless a subsection says otherwise. A single Evidence-shaped checklist would
have made "adopt Astro" unreachable by construction.

Where a criterion can carry a number, it carries one. A criterion that cannot be failed is not a
criterion, and the qualitative form of these gates was the largest weakness of this section's first
draft.

### 11.0 Preconditions -- satisfied BEFORE a proof-of-concept branch is opened

These are not exit criteria. The proof of concept runs installs and builds on a branch of a **public
repository**, so these must hold first (section 7).

- P0.1 `.gitignore` covers `node_modules/`, `.svelte-kit/`, build output directories, `*.parquet`
  and `*.arrow`; and the deterministic tracked-artifact guard (Decision 104 registry pattern) is
  registered and passing.
- P0.2 The section 4.1.1 question is **resolved in writing**: does Decision 127's audience-of-record
  rule bind non-`.md` dashboard pages, or is the `.md` scope of `validate_prose_allowlist` an
  enforcement artifact? The answer determines whether P2 binds one arm or all three, so it must
  precede the comparison rather than emerge from it.

**Resolving the ownership circularity (important, and a defect in this section's second draft).**
P0.1 is registered in the ledger as T2.53 exit criterion c7, but T2.53 is `deferred_post_mvp` -- so
as written, the guard that must exist *before* a proof-of-concept branch opens is owned solely by
the deferred item whose branch it gates, and no active item owns it. Two things break the loop:

1. **P0.1 is independently landable.** It is ordinary repository hygiene -- ignore rules plus a
   registered check -- with no dependency on T2.52, T2.53 or any adoption decision. Any session may
   land it as standalone work; it does not require T2.53 to reactivate, and registering it as c7
   records the *obligation*, not a scheduling constraint.
2. **Until it lands, the binding rule is simpler and absolute: no `npm install` may be run inside the
   repository tree.** Scratch-directory installs (as used to gather section 5's figures) are
   unaffected, because nothing there is ever tracked. This is the operative control in the interim,
   and it needs no roadmap item to take effect.

### 11.1 Tool-neutral criteria -- all candidates must satisfy all of

1. An agent scaffolds, renders, inspects and iterates the dashboard entirely within an ephemeral
   container, from contract-derived fixtures, with no live data and no credentials.
2. The source adapter binds to `named_read` verbs **only** -- not `query_ops`, and not
   `read_ops_current` (section 3.1). "Named verbs only" is the invariant; "no caller SQL" is too
   weak, because a structural-filter verb satisfies the latter while defeating the former.
3. Fixture and live adapters expose **identical** schemas.
4. A strict build **fails** (non-zero exit) on a broken query, a schema mismatch or an unresolvable
   dataset -- it does not render an error component and exit zero.
5. Browser tests detect material layout and accessibility failures **on deliberately broken
   fixtures** -- demonstrated, not asserted.
6. Upstream build-time telemetry, if any, is disabled and the disablement is **verified**.
7. The egress budget (Decision 88) and partition-every-table (Decision 137) constraints are
   satisfied by the T2.52 datasets consumed.
8. Moving a semantic asset from a virtual query to a persisted materialization requires **no change**
   to the page contract.
9. The QuickSight rejection is **re-adjudicated** against measured build and carry cost, and still
   holds (section 8.1).

**Deliberately NOT in 11.1: the serving prototype.** An earlier draft required a working
edge-JWT-or-signed-cookie prototype as an all-candidates criterion, which **contradicted criterion 1**
-- a run that is credential-free and confined to an ephemeral container cannot stand up an AWS
origin and a Cloudflare Access application. It also depends on **CD.41, which is itself unratified
and gated on the deferred T2.51**, so it could not be discharged at proof-of-concept time regardless
of effort.

The serving question is therefore a **separate, credentialed, CD.41-gated sub-task** (roadmap T2.53
c6, whose surfaces are declared in that item's `files_in_scope`), sequenced after the in-container
comparison and after CD.41 ratifies. Its failure mode is preserved as a **class-level reject**
(section 11.4 item 5) rather than a per-arm criterion, because an unsolvable serving problem defeats
every code-defined renderer equally -- it is not a discriminator between arms.

### 11.2 Supply-chain thresholds -- numeric, applied per candidate

Measured on the resolved tree at proof-of-concept time, not inherited from section 5. Each entry is
either a **threshold** (has a defined fail state and can reject an arm) or a **recorded metric**
(informs judgement, never rejects). Mixing the two was a defect in this section's second draft and
is called out explicitly here so the distinction is not lost again.

- **T1 -- Unresolvable advisories (THRESHOLD).** Defined in **npm's own terms**, because "no forward
  fix" is ambiguous across two distinct `npm audit` states and conflating them flips the verdict:
  T1 counts **only advisories reporting `fixAvailable: false`** (genuinely unresolvable). Advisories
  whose `fixAvailable` is a dict requiring a major change are **recorded separately** and do not
  count toward T1 -- a major upgrade is disruptive, not impossible.

  **The unit is a distinct root advisory, not an npm-audit entry.** npm reports severity against
  every ancestor of a vulnerable package, so a single CVE in a deep tree produces many entries and
  the same CVE in a shallow tree produces one (section 5.3: four Evidence entries, one `vitest`
  CVE). Counting entries would let tree depth reject an arm through T1 -- reintroducing exactly the
  size-based rejection T2 was deliberately demoted to avoid. **Deduplicate by root advisory before
  applying the limits.**

  An arm fails T1 on **any unresolvable `critical` root advisory**, or on **more than 3 unresolvable
  `high`**. Record alongside, without it affecting the verdict, whether each is **runtime-reachable**
  or confined to **build/test tooling** -- the two are not equivalent risk, and the distinction is
  what separates a real exposure from an unclosable alert.

  Measured on the adoption-relevant artifact for each arm:

  | Arm | Deps | Advisories | Unresolvable root advisories | T1 |
  |---|---|---|---|---|
  | Evidence (scaffold, pruned) | 928 | 46 | **1 critical** (`vitest`, build/test tooling), 1 high, 7 moderate | **FAIL** |
  | Observable Framework | 334 | 6 | **0** (all six offer a downgrade-only fix) | pass |
  | Astro (bare -- *not* the specified arm) | 296 | 0 | 0 | n/a |
  | Astro **+ charting library** | not measured | not measured | not measured | **unmeasured -- no library named** |

  Evidence fails on **one** unresolvable critical root advisory that survives pruning to the minimum
  surface, because `@evidence-dev/sdk` ships `vitest` as a runtime dependency (section 5.3). It is
  build/test tooling, so the cost is an unclosable public alert rather than an exploitable path --
  a genuine T1 failure at its true weight, neither dismissed nor inflated.

  The Astro **arm as specified** remains unmeasured: bare `astro` is not that arm (section 8.2), and
  a charting library is precisely where it would acquire transitive weight. Its clean bare figures
  must not be read as an arm-level result.
- **T2 -- Tree size (RECORDED METRIC, not a threshold).** The transitive dependency count is recorded
  and reported on the adoption-relevant artifact (Evidence: **1,387** as shipped, **928** pruned;
  the bare package's 641 is a diagnostic, not an adoption figure). It carries **no numeric cap**:
  any cap this report could name would be calibrated against the one tree it has measured, which is
  threshold-tuning rather than measurement. Size informs the section 11.3 per-arm judgement and the
  Constrain disposition; **it never rejects an arm on its own.**
- **T3 -- Install integrity (THRESHOLD).** The project installs **without `--legacy-peer-deps`** or
  any equivalent resolution override, **using the install path adoption would actually use**.
  Evidence **passes T3** via its documented scaffold (section 5.5). Recorded alongside, because it
  bears on maintenance rather than on T3: that pass depends on an upstream-committed lockfile, and
  the declared peer graph does not self-resolve without it.
- **T4 -- Advisory responsiveness (THRESHOLD).** Assessed on **response to security advisories
  alone**, not publish cadence -- section 5.1 establishes that cadence cannot settle liveness in
  either direction, so a cadence-derived window would re-import the measure that section rejects.
  **T4 is measured on the upstream project, not on the advisory set** -- this independence is
  deliberate and was got wrong twice. An arm fails T4 if, for its open advisories, the upstream
  repository shows **no maintainer engagement** (no issue or pull request acknowledging them, no
  documented mitigation, no security-policy response) within a **6-month** window preceding
  measurement.

  Two failure modes this phrasing exists to avoid:

  - **Collinearity with T1.** A previous draft defined T4 over T1's own `fixAvailable: false` set,
    which made the two thresholds the same test: an arm failing T1 would near-automatically fail T4,
    and §11.4 item 6 would reject it twice over on one measurement while presenting two independent
    findings. Whether an advisory is *fixable* (T1) and whether maintainers are *responsive* (T4)
    are different questions and must be measured on different evidence.
  - **Vacuity at zero.** An arm with no open advisories passes T4 by having nothing to respond to,
    which is not evidence of responsiveness. Record such an arm as **T4 not applicable**, never as a
    T4 pass, so a clean supply chain cannot be laundered into a liveness finding.

  **Evidence's T4 result is UNMEASURED.** This report has not inspected Evidence's issue tracker,
  and every prior attempt to infer T4 from advisory data was an instance of the collinearity error
  above. Measuring it is a proof-of-concept task, and its outcome is genuinely open.

**Threshold-tuning disclosure.** T1's numbers were chosen after measuring Evidence. That ordering is
unavoidable here -- the measurement is what prompted the thresholds -- so the mitigation is
disclosure plus units that do not flatter the incumbent, not a pretence of blindness. T2 was
demoted to a metric precisely because no honest cap could be derived from a single measured tree.
An earlier draft's T4 window was calibrated to sit *above* Evidence's own observed quiet period,
which is threshold-tuning in the incumbent's favour; it has been re-derived from advisory response.

**One-survivor disclosure (the inverse risk, stated because it is easy to miss).** This report
opened by worrying that Evidence-shaped criteria would make "adopt Astro" unreachable. The corrected
measurements create the **opposite** hazard: on present figures T1 fails Evidence, and Astro is also
the one arm that escapes `validate_prose_allowlist` under section 4.1.1's mechanical reading. A
criteria set that eliminates two of three arms **and** happens to favour the arm the repository has
already ratified elsewhere (Decision 101(e)) deserves suspicion, not satisfaction.

Three guards against rubber-stamping that outcome:

1. T1 is defined on `fixAvailable: false` rather than the looser major-change reading, and
   deduplicated to root advisories. Both choices matter: under the looser reading **Observable
   Framework also fails T1** (all six of its advisories are downgrade-only, five of them high,
   exceeding the limit of 3), which would leave exactly one survivor; and counting entries rather
   than root advisories would inflate Evidence's single `vitest` CVE into four. A threshold that
   eliminates arms by *measurement convention* rather than by substance is not a threshold.
2. **The Astro arm as specified is still unmeasured**, so no complete comparison exists yet. Bare
   `astro` (296 deps, 0 advisories) is not the arm; a charting library is where that arm acquires
   its weight. A single measured failure alongside an unmeasured favourite is not a result.
3. If the proof of concept does find only one arm standing, it must state **which criterion did the
   eliminating and whether that criterion is load-bearing or incidental** before recommending
   adoption. Applied to today's figures, that test bites immediately: Evidence's T1 failure is one
   build/test-tooling CVE producing an unclosable public alert -- load-bearing for a public
   repository's security hygiene, but not an exploitable production path, and a reader who saw only
   "fails T1" would badly misjudge it. An uncontested winner is a weaker result than a contested one,
   and should be reported as such.

### 11.3 Per-arm adopt bar

- **Evidence adopts** if 11.0-11.2 hold, a scoped Decision-127 amendment is obtained on its own
  grounds (section 4.1), and an acceptable result needs **no substantial custom Svelte components**
  -- built-in components plus chart configuration suffice.
- **Observable Framework adopts** if 11.0-11.2 hold and the same Decision-127 amendment is obtained
  (its pages are `.md`, so it collides identically -- section 4.1.1).
- **Astro adopts** if 11.0-11.2 hold **and** the repository accepts owning chart integration, layout
  primitives, formatting and empty/stale/partial states directly (section 8.2) -- costed in
  estimated build effort, not waved through. If section 4.1.1 resolves to the *principled* reading,
  Astro needs the Decision-127 amendment too and gains no exemption from `.astro` file extensions.
- **No candidate adopts** if none clears its bar. "No UI layer -- structured agent reports suffice"
  is then the verdict, and it is a real outcome rather than a failure to decide.

### 11.4 Reject -- whole class, or a single arm

**Whole class** (no candidate adopts) if any of:

1. The section 4.1.1 question resolves to the **principled** reading AND a Decision-127 amendment is
   **unobtainable** on its own grounds -- this rejects every code-defined dashboard, `.md` or
   `.astro`.
2. Required interactions turn out to be transactional, write-oriented, highly stateful or
   operational rather than analytical.
3. Per-user row-level authorization must be enforced inside the application rather than before
   dataset publication.
4. Data must be continuously live at a latency incompatible with scheduled or event-driven builds.
5. No compliant CD.41 invariant (b) serving mechanism can be prototyped (section 4.2).

**A single arm** is rejected if any of:

6. It fails any **threshold** in 11.2 -- that is T1, T3 or T4. T2 is a recorded metric and cannot
   reject an arm.
7. Useful dashboards require arbitrary SQL in its page files, or its local query behaviour creates
   an unavoidable second semantic layer (section 6).
8. Its data-source plugin interface cannot cleanly express the named-verb model.
9. Agents cannot render and debug it reliably in the standard ephemeral environment.
10. Acceptable results require extensive custom components, turning it into a bespoke frontend
    framework by another name.
11. Its accessibility, responsiveness or visual-testing standards cannot be met.
12. Its static output is too large or slow for expected datasets.
13. Another arm meets the validated requirements at materially lower long-term complexity.
14. **Astro-specific:** the repository declines to own chart integration, layout primitives,
    formatting and empty/stale/partial states directly, having costed them (section 11.3). Recorded
    explicitly so that failing an arm's own §11.3 bar has a defined disposition for every arm, not
    only for Evidence via item 10.

### 11.5 Constrain

Adoption limited to a narrow reporting use case (for example the private cost dashboard alone), with
no commitment to telemetry, data quality, operational governance or product analytics.

**Constrain is defined against the qualitative findings, not against 11.2.** This matters, because
11.2's thresholds are binary and 11.4 item 6 makes any threshold failure a reject -- so a Constrain
disposition keyed to "thresholds uncomfortable but short of failure" would be structurally
unreachable. It is reachable on exactly these paths:

- An arm clears 11.0, 11.1 and every 11.2 **threshold** (T1, T3, T4), but its recorded **T2** tree
  size, custom-component burden, or measured build-and-carry cost under 11.3 makes platform-wide
  standardisation unattractive.
- An arm clears everything but the Decision-127 amendment is obtained only in a **narrowed** form
  (for example scoped to one dashboard surface rather than to a general dashboard-page class).
- Section 6's second-semantic-layer concern (a shipped query console) is judged tolerable for a
  single private, single-operator tenant but not as a platform-wide default.

A bounded, single-tenant blast radius is an acceptable way to carry a dependency one would not want
platform-wide -- but only where a threshold has actually been met, never as a softer landing for one
that was failed.

## 12. Roadmap placement and sequencing

- **T2.52** (analytical/semantic layer) and **T2.53** (presentation-layer proof of concept), both
  `deferred_post_mvp` with `T2.53 depends_on: [T2.52]`. Both deferred, so Decision 93's no-live-dep
  invariant holds.
- **Deferral rationale (Decision 93 conscious-deferral rule).** A human-facing analytical layer is
  outside the MVP loop; and every candidate tenant currently lacks a live governed dataset
  (section 3.4), so the work would be build-ahead-of-need (Decision 87).
- **Activation trigger.** A governed named dataset exists that a human actually needs to read --
  concretely, T2.51 reactivates (its own trigger being material variable spend), or telemetry lands
  on DuckLake (T2.36), or data-quality coverage becomes non-zero. **T2.52 is triggered by a real
  tenant, not scheduled ahead of one.**
- **T2.51 amendment.** Exit criteria c2/c3 route the cost snapshot into DuckLake as a governed table
  served by named verbs (section 3.3); the renderer choice and the CD.41 invariant (b) multi-file
  serving question are rehomed to T2.53.
- **CD.42** (pending, gates T2.53) records the presentation-layer boundary and ratifies to a
  numbered Decision on the proof-of-concept verdict (Decisions 105/150).

## 13. Known gaps and open questions

- Section 5 figures are point-in-time and **must be re-verified** at proof-of-concept time.
- Whether a Decision-127 amendment is obtainable on its own grounds is genuinely open, and it gates
  everything else. Settle it **before** the proof of concept spends effort: a negative answer under
  the principled reading rejects the whole class of code-defined dashboards, not just Evidence.
  Section 4.1.1's principle-versus-mechanism question is part of this and must be answered first.
- The compliant CD.41 invariant (b) mechanism is unresolved, though section 4.2's TTL analysis
  narrows it to **edge JWT verification or signed cookies**; single-object bundling survives only
  for a non-interactive artifact.
- **Named-verb payload feasibility for analytical extracts is unexamined.** Only 2 of the 12 current
  verbs (`open_recs`, `recs_by_title_prefix`) are `paginable`, and `named_read` returns JSON rows
  over a Lambda Function URL with a response-size ceiling this report has not measured. A
  build-time-materializing renderer pulls whole datasets, so if the boundary cannot physically carry
  an analytical extract within its limits, T2.52 needs a **bulk-extract verb class** (paginated or
  streamed) in addition to aggregate verbs, and criterion 11.1.2 is otherwise unsatisfiable. Measure
  the ceiling before designing the verbs, and weigh the result against the Decision 88 egress
  budget.
- The Decision 88 egress criterion is stated without a numeric budget, unlike section 11.2's
  supply-chain thresholds. Quantifying it is T2.52's work.
- **Lockfile ownership.** The scaffold's clean install depends on an upstream-authored
  `package-lock.json`, not on a self-resolving peer graph (section 5.5). The open question is not
  *whether* it installs -- it does -- but how to guard the failure mode: any action that regenerates
  the lock (`npm audit fix`, a Dependabot bump, a different package manager) re-enters the
  unresolved graph. Whether that is manageable is a T2.53 finding.
- **Observable Framework and the Astro arm are unmeasured.** Section 11.2's T1 table records them as
  provisional, and the Astro arm as specified (Astro *plus a charting library*) has never been
  measured at all -- no library is named. Both must be measured before any comparative claim.
- The analytical-aggregate verb set itself is unenumerated; T2.52 owns naming the grains.
- Whether an npm ecosystem entry in Dependabot is even useful given the exact-pin problem
  (section 5.3) is open -- it may produce only unmergeable pull requests.
- Node toolchain count: whether the internal analytical surface should share Astro with the ratified
  marketing surface (Decision 101(e)) or carry a second stack is a cost question the three-way
  comparison is designed to answer.

## 14. Decisions honoured

Read boundary and named verbs: **84** (I-3, `query_ops` retained for the DQ harness and marked for
restriction/retirement), **81** (closed reader/writer boundary), **88** (Neon egress budget).
Data modeling: **137/CD.9** (partition-every-table), **136/CD.39** (exit-criteria ledger; T2.51's
criteria confirmed `open` before amendment), **118/CD.25** (not applicable -- no `contract:`/`class:`
key in `data-modeling-standard.yaml`). Prose and agent-first: **86** (this report is the sanctioned
REPORT-ONLY deliverable class; forward intent lives in T2.52/T2.53, not restated here), **127**
(collision, section 4.1), **101** (c/d/e -- public-content boundary, and CD.42 does not amend the
ratified marketing stack), **111/CD.20** (curated portal, not an export of operational data).
Managed-native: **100/75** (QuickSight adjudicated by name, section 8.1). Sequencing and lifecycle:
**93** (MVP boundary, conscious deferral, no-live-dep), **87** (build-ahead-of-need), **133**
(platform-first capacity). Governance vehicles: **105/150** (CD.42 pending, ratifies on verdict),
**85** (plan schema), **132** (graduation dispositions), **104** (deterministic-guard registry
pattern), **114/147** (roadmap ceiling and compaction norm), **83** (Dependabot and branch-protection
surface). Loud-fail: **55**, **62/CD.12**. STRATEGIC freeze: **67/CD.17** (`strategic: false`;
realization decomposes into IMPLEMENTATION plans).
