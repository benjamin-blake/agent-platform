# REPORT: Evidence as a human-facing analytical presentation layer (hypothesis stress test)

> Stress test / spike note for platform tier items **T2.52** (analytical-semantic layer, the
> prerequisite) and **T2.53** (bounded presentation-layer proof of concept), and candidate decision
> **CD.42**. Not an implementation, and not an adoption. The owner authored a hypothesis that
> Evidence (evidence.dev) should become this repository's standard human-facing analytical
> presentation layer; this report tries to falsify it. The roadmap entries are the canonical forward
> intent and CD.42 is the pattern decision; this report is the design rationale they point back to.

## 1. Verdict of this report

The hypothesis's **architecture is sound and is not what fails**. Separating a governed dataset
boundary from a presentation layer, keeping Git authoritative, and rendering to an authenticated
static artifact are all correct for this repository, and no active decision contradicts that shape.

What fails is **testability today**. Three preconditions block a meaningful proof of concept, and
none of them are about Evidence's quality:

| # | Precondition | Owner |
|---|---|---|
| P1 | No analytical-aggregate dataset exists to present. The `NAMED_READS` registry is 12 operational-lookup verbs over 3 tables, with zero aggregates. | T2.52 |
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
sanctioned, scheduled-for-retirement exception for one internal consumer, not a precedent, and the
hypothesis's constraint states the target invariant correctly.

**The constraint that survives, and that the proof of concept must honour:** an Evidence (or any
presentation-layer) source adapter must consume `named_read` verbs **only**, and must never become
`query_ops`'s second tenant. A presentation layer is a durable, load-bearing consumer; wiring one
to `query_ops` would convert a retiring exception into something that cannot be retired.

### 3.2 Analytical aggregates do not exist yet (this is the prerequisite, not an objection)

The `NAMED_READS` registry (`src/common/ducklake_scd2_schema.py`, `NAMED_READS_VERSION = 3`)
contains **12 verbs over 3 tables** -- `ops_recommendations`, `ops_decisions`,
`ops_priority_queue` -- and every one is an operational lookup (`open_recs`, `rec_by_id`,
`ci_rca_open`, `recs_by_title_prefix`, `count_by_status`, `priority_queue_current`, and so on).
There is **no analytical-aggregate verb of any kind**.

The hypothesis's claim is that named verbs are the *pattern to follow*, which is correct. The
consequence is that the analytical-aggregate verb class is **net-new design work**, which is why it
is scoped as T2.52 and made a prerequisite of T2.53 rather than assumed available.

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

Two honest readings, and the report does not pick one:

- **Charitable:** the project matured. Forty major versions in three years followed by fourteen-plus
  months on a single major is a stabilisation curve, not a death curve.
- **Adverse:** organisation-wide publish silence of roughly five to six months is a liveness
  question for a load-bearing dependency on a security-relevant surface, where security patches for
  a large transitive Node tree depend on upstream responsiveness.

Publish silence is not abandonment -- it can reflect a release-process change or genuine maintenance
mode. The correct treatment is a **gating liveness check** (section 11), not an assumption in
either direction.

### 5.2 Comparative liveness

| Package | Latest | Last publish |
|---|---|---|
| `astro` | 7.1.3 | 2026-07-20 |
| `@astrojs/starlight` | 0.41.4 | 2026-07-22 |
| `@observablehq/framework` | 1.13.4 | 2026-04-06 |
| `@evidence-dev/evidence` | 40.1.8 | 2026-02-06 |

### 5.3 The dependency surface is effectively frozen

`@evidence-dev/evidence@40.1.8` declares 10 dependencies, 6 devDependencies and 13 peer
dependencies, with **exact pins** across the framework tier: `@sveltejs/kit 2.8.4`,
`svelte 4.2.19`, `vite 5.4.21`, `typescript 5.4.2`, `tailwindcss 3.4.18`,
`@sveltejs/adapter-static 3.0.1`. Note Svelte **4**, not 5.

The consequence is concrete: **the transitive tree cannot be independently patched.** A Dependabot
bump to svelte, vite or SvelteKit breaks the exact peer pins, so upgrades are gated on upstream
republishing -- which section 5.1 shows has slowed sharply. This repository's Dependabot
configuration (`.github/dependabot.yml`) currently covers `pip` and `github-actions` only, so
adoption additionally requires a new npm ecosystem entry, which is a governed `.github/` and
`terraform/github/` surface under Decision 83, not a free edit.

### 5.4 Build-time telemetry

`@evidence-dev/telemetry` is a **direct dependency** of the Evidence package. A build-time
phone-home is a governance item under the confidential-data boundary (Decisions 73/83/101), not a
footnote. It must be **explicitly disabled and the disablement verified**, and that verification is
a pre-committed exit criterion rather than a configuration note.

### 5.5 Container feasibility (favourable)

The standard ephemeral development container carries Node **v22.22.2**, npm **10.9.7**, a
pre-installed Chromium under `PLAYWRIGHT_BROWSERS_PATH`, and reachable npm registry access through
the agent proxy (verified by live `npm view` and `npm pack` calls this session). The agent-side
render-and-inspect loop the hypothesis describes is therefore **feasible in principle**; nothing in
the environment blocks it. The repository currently tracks **zero** JavaScript or TypeScript files
and has no `package.json`, so any adoption introduces the repository's first Node dependency
surface.

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

Committed now, before the experiment, so the verdict is not rationalised afterwards.

### 11.1 Adopt requires all of

1. An agent scaffolds, renders, inspects and iterates the dashboard entirely within an ephemeral
   container, from contract-derived fixtures, with no live data and no credentials.
2. The source adapter consumes `named_read` verbs only; no caller SQL crosses the read boundary and
   `query_ops` gains no second tenant (section 3.1).
3. Fixture and live adapters expose **identical** schemas.
4. A strict build detects broken queries, schemas and components (it fails, rather than rendering an
   error component).
5. Browser tests detect material layout and accessibility failures on deliberately broken fixtures.
6. An acceptable result is reached **without substantial custom framework components** -- built-in
   components plus chart configuration suffice.
7. A **scoped Decision-127 amendment is obtained on its own grounds** (section 4.1).
8. A compliant answer to CD.41 invariant (b) for multi-file serving is identified and costed
   (section 4.2).
9. A **deterministic guard** (registered `validate.py` check or `never-commit` extension) asserts no
   build artifact is tracked (section 7).
10. Upstream telemetry is disabled and the disablement is verified.
11. An upstream-liveness check passes at proof-of-concept time (section 5.1 re-verified, plus
    repository commit activity and security-advisory responsiveness).
12. The egress budget (Decision 88) and partition-every-table (Decision 137) constraints are
    satisfied by the T2.52 datasets the proof of concept consumes.
13. The QuickSight rejection is **re-adjudicated** against the proof of concept's measured build and
    carry cost, and still holds (section 8.1).
14. Moving a semantic asset from a virtual query to a persisted materialization does not require
    changing the page contract.
15. The operating and dependency burden is proportionate for a sole-operator platform.

### 11.2 Reject if any of

1. The Decision-127 amendment is **unobtainable** on its own grounds.
2. Useful dashboards require arbitrary SQL in page files, or the local query behaviour creates an
   unavoidable second semantic layer (section 6).
3. The data-source plugin interface cannot cleanly express the named-verb model.
4. Agents cannot render and debug reliably in the standard ephemeral environment.
5. Acceptable results require extensive custom Svelte components, turning the tool into a custom
   frontend framework by another name.
6. Accessibility, responsiveness or visual-testing standards cannot be met.
7. Static output becomes too large or slow for expected datasets.
8. Upstream liveness or plugin compatibility is inadequate for a load-bearing dependency
   (section 5.1, 5.3).
9. The supply-chain and upgrade burden exceeds the value of the reporting components -- specifically
   including the frozen-pin problem, which cannot be mitigated by Dependabot.
10. Astro or Observable Framework meets the validated requirements at materially lower long-term
    complexity.
11. Required interactions turn out to be transactional, write-oriented, highly stateful or
    operational rather than analytical.
12. Per-user row-level authorization must be enforced inside the application rather than before
    dataset publication.
13. Data must be continuously live at a latency incompatible with scheduled or event-driven builds.

### 11.3 Constrain

Adoption limited to a narrow reporting use case (for example the private cost dashboard alone), with
no commitment to telemetry, data quality, operational governance or product analytics. Constrain is
the expected outcome if section 11.1 largely holds but 11.2 items 8 or 9 (upstream and supply chain)
remain uncomfortable.

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
  everything else. It is worth settling **before** the proof of concept spends effort, since a
  negative answer rejects the whole class of code-defined Markdown dashboards, not just Evidence.
- The compliant CD.41 invariant (b) mechanism for multi-file serving is unresolved (edge JWT
  verification versus signed cookies versus a single-object bundling strategy).
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
