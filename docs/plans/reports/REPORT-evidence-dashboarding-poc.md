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

**One measured result is significant enough to record in the verdict.** On figures taken during
authoring, Evidence's resolved tree carries **3 critical and 21 high advisories, roughly 18 of them
with no forward fix** (npm's only remediation is a major *downgrade*), and the bare package **fails
to install** without `--legacy-peer-deps` (sections 5.3, 5.5). Against the thresholds this report
commits to in section 11.2, **Evidence fails T1 and T3 as measured today**. That is not a verdict --
the thresholds are to be re-measured at proof-of-concept time, the template scaffold is untested,
and a failing arm does not reject the class -- but it does mean the burden of proof has shifted, and
the report says so rather than deferring an already-visible result. It is also why section 11.2
states thresholds numerically: they were written after the measurement, so they must be falsifiable
rather than tuned to pass.

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
  is exactly the kind of accidental exemption that gets closed the moment someone notices.

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
assessed on advisory response rather than publish frequency. Note also that the package carries
live `next` and `features-a` dist-tags, which this report has not examined.

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

**Measured, not inferred.** Resolving the tree in this container yields **641 total dependencies**
(592 production, 50 optional; 593 packages installed), and `npm audit --json` reports **30
vulnerabilities: 3 critical, 21 high, 5 moderate, 1 low**.

The decisive figure is not the count but the **fix path**. Of those advisories, **18 report
`fixAvailable` as a major *downgrade* to `@evidence-dev/evidence@29.0.3`** -- including
`@evidence-dev/sdk` (critical), `@sveltejs/kit` (high) and `@evidence-dev/preprocess` (high). npm
cannot fix these forward at all. Only 12 are in-range fixable, and those are peripheral tooling
(eslint, vitest). So the accurate statement is not "upgrades are gated on upstream republishing" but
**"a substantial share of the advisory surface is unresolvable at adoption time, in either
direction."**

**Why that lands harder in this repository than in most.** This repo is PUBLIC, with GHAS,
Dependabot alerts and a standing `ghas-probe` monitor whose dated evidence is recorded against
Decision 83. Two things follow that are easy to conflate and must not be:

- **Dependabot *version updates*** are configured per-ecosystem in `.github/dependabot.yml`
  (currently `pip` and `github-actions` only). Adding an npm entry is a governed `.github/` and
  `terraform/github/` surface change under Decision 83.
- **Dependabot *alerts* are repository-wide and automatic.** They fire on any manifest in the repo
  **regardless of `dependabot.yml`**, and on a public repository they are visible security signal.

Adoption therefore injects roughly two dozen high-and-critical advisories that **cannot be
remediated forward** onto a public security surface that Decision 83 treats as continuously
live-verified. Declining to add the npm ecosystem entry does not avoid this; it only removes the
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

**The install is not.** A bare `npm install @evidence-dev/evidence@40.1.8` **fails** in this
container with `ERESOLVE unable to resolve dependency tree`. The conflict is intrinsic to the pinned
tree rather than environmental: `ts-node@10.9.2` (pulled in transitively via
`postcss-load-config@4.0.2`, itself a pinned peer of Evidence) declares a loose
`peer typescript ">=2.7"`, so npm hoists `typescript@7.0.2`; that violates `svelte-preprocess@5.1.3`'s
`peerOptional typescript ">=3.9.5 || ^4.0.0 || ^5.0.0"`, and `svelte-preprocess@5.1.3` is itself an
exact peer pin of Evidence.

The install succeeds **only** under `--legacy-peer-deps`, which is npm's explicit instruction to
accept a resolution it considers incorrect and potentially broken. This is section 5.3's frozen-pin
thesis **already materialised**, not a future risk.

**Install path validated (stated precisely, because it bounds the claim).** The measurement above is
a **bare install of the `@evidence-dev/evidence` package** into an empty project. Evidence's
documented scaffold path is a project template (`npx degit evidence-dev/template`), which ships its
own `package.json` supplying the peer versions and may well resolve cleanly. **That path was not
tested here.** So the honest finding is narrower than "Evidence cannot be installed": it is that the
**package's declared peer graph does not self-resolve under current npm**, and any adoption must
therefore pin its own resolution -- which is itself the maintenance burden under evaluation. Testing
the template scaffold is the first task of the proof of concept, not a settled matter.

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
moment one runs an install. Section 5.3 measured that first install at **593 packages**, and a
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
9. A **working prototype** of a CD.41-invariant-(b)-compliant serving mechanism exists -- not a
   sketch, and not merely "identified and costed". Section 4.2's TTL analysis means this is
   realistically edge-JWT or signed cookies, so a design note does not discharge it.
10. The QuickSight rejection is **re-adjudicated** against measured build and carry cost, and still
    holds (section 8.1).

### 11.2 Supply-chain thresholds -- numeric, applied per candidate

Measured on the resolved tree at proof-of-concept time, not inherited from section 5:

- T1 **Unresolvable advisories:** zero `critical` and no more than **3 `high`** advisories for which
  no forward fix exists. Evidence measured **3 critical and roughly 18 fix-forward-unavailable**
  today (section 5.3), so on current figures Evidence **fails T1** -- which is precisely why the
  threshold is stated in advance.
- T2 **Tree size:** transitive dependency count recorded, with anything above **750** requiring an
  explicit written justification rather than an automatic pass.
- T3 **Install integrity:** the project installs **without `--legacy-peer-deps`** or any equivalent
  resolution override. Evidence's bare package currently fails this; the template scaffold is
  untested (section 5.5).
- T4 **Liveness:** a security-relevant publish or a documented advisory response within the
  preceding **9 months** (chosen to sit above this project's own observed ~7-month quiet period, so
  the threshold measures responsiveness rather than cadence -- section 5.1).

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

6. It fails any threshold in 11.2.
7. Useful dashboards require arbitrary SQL in its page files, or its local query behaviour creates
   an unavoidable second semantic layer (section 6).
8. Its data-source plugin interface cannot cleanly express the named-verb model.
9. Agents cannot render and debug it reliably in the standard ephemeral environment.
10. Acceptable results require extensive custom components, turning it into a bespoke frontend
    framework by another name.
11. Its accessibility, responsiveness or visual-testing standards cannot be met.
12. Its static output is too large or slow for expected datasets.
13. Another arm meets the validated requirements at materially lower long-term complexity.

### 11.5 Constrain

Adoption limited to a narrow reporting use case (for example the private cost dashboard alone), with
no commitment to telemetry, data quality, operational governance or product analytics. Constrain is
the expected outcome if 11.0-11.1 hold for some arm but its 11.2 supply-chain thresholds remain
uncomfortable at a level short of outright failure -- a bounded, single-tenant blast radius being an
acceptable way to carry a dependency one would not want platform-wide.

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
- Whether Evidence's **template scaffold** resolves cleanly where the bare package does not
  (section 5.5) is untested and is the proof of concept's first task.
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
