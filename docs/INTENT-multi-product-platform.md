# Intent: Multi-Product Platform Topology

This document is the architectural anchor for how the agent-platform hosts multiple products -- the trading system, a Reaper music-tooling project, and day-job dbt development -- on a SINGLE platform operational data plane distinguished by a `project_id` origin dimension, reserving repo/package separation for the one case an IP boundary forces it (the day job). It **extends, and does not supersede,** the monorepo + `project_id` commitment in `docs/INTENT-aws-migration-platform-evolution.md` Part 2: that document established the model for same-owner products; this one carries it across the cross-employer IP boundary.

**Status:** Architectural anchor (exploratory). Records intent and boundaries; no migration committed, no recommendations filed, no executor work queued. The `project_id` mechanism and the IP-wall enforcement it relies on are **proposed and unbuilt** (see "Build-state reality" below). Authoritative for vocabulary and boundaries on landing; authoritative for implementation only after the Open Decisions are ratified and the enforcement substrate is built.

**Builds on:** NS.1 (storage durable, compute interchangeable -- generalized by Decision 78 to "S3 + open table format at every scale"), NS.2 (account ownership reflects IP ownership), NS.4 (the repo is for agents); Decision 78 (ratifies CD.31: Iceberg for market-data/product tables, DuckLake for ops/telemetry); Decision 77 + `docs/contracts/environment-taxonomy.md` (the two-axis account model -- NOT altered here); Decision 75 (frame-lock anti-pattern -- the two-axis framing below is a conscious frame choice); Decision 67 (REPORT-ONLY framing during the executor freeze); KG.1 (a known-gap note whose singular "product roadmap" wording OD-5 would generalize -- see OD-5 for the dual-sense caveat).

**Companion documents (load-bearing):**
- `docs/INTENT-aws-migration-platform-evolution.md` Part 2 -- the monorepo + `project_id` commitment this document extends. The `project_id` dimension, the registry, the reserved `platform` value, and the two-phase `RecPayload`/`DecisionPayload` rollout are **designed there (a DRAFT) and not yet built**; this document adopts that proposed design rather than inventing a second one.
- `docs/INTENT-telemetry-system.md` -- the meta/domain tiering below is net-new (those terms do not appear there) and is layered on top of it; that INTENT predates Decision 78's DuckLake move and its star schema does not yet support the field-level split the tiering needs. This document does NOT claim to refine it.
- `docs/contracts/environment-taxonomy.md` -- the account / blast-radius axis (a separate concern, not altered here).

**Terminology:** "product" = a distinct application/domain the platform operates on, identified by `project_id`. Trading is product #1 and the only real one today; `reaper-tools` and `dbt-daywork` are prospective and exist nowhere in the repo yet. Orthogonal to the Decision-77 product *phase* axis (the trading strategy lifecycle).

---

## North Star: two orthogonal axes, not one choice

Hosting a second product was being framed as a single either/or -- monorepo vs split-repo. It is two independent axes:

1. **Data / identity axis -- unified.** The platform's operational data (ops, telemetry, recommendations, logs) is intended to live in ONE store -- DuckLake per Decision 78 -- with each *typed* row carrying a `project_id` **origin identity** naming the product the platform was operating on. Products are distinguished by a column, not by separate stores. Cross-product meta-learning would then be a query across `project_id` in one warehouse -- the mechanism by which "benefit from every product's telemetry" is intended to hold. (Proposed, not built, and coverage is partial -- see "Build-state reality".)

2. **Code / repo axis -- separated only where an IP boundary forces it.** Where the product's IP is the same owner's (trading, reaper), its code lives in the monorepo and is distinguished by `project_id` -- split-repo extraction stays deferred (per `INTENT-aws-migration-platform-evolution.md` Part 2; the extraction plan it points to is not yet authored). Only the cross-employer case (day-job dbt) forces an external repo and a packaged, importable substrate, because employer IP cannot enter the personal repo or the personal data plane (NS.2 in reverse).

The earlier instinct "the platform must be a dependency products import, not a repo they live in" was right for exactly one case (the day job) and wrong as a universal rule. The frame this document fixes (Decision 75, frame-lock): the question is not "monorepo or split" but "which axis are we on -- shared data identity, or IP-forced code separation?". A partial seam exists in code today only at the roadmap-tooling level (`scripts/platform_roadmap.py` vs `scripts/product_roadmap.py`); the `project_id` data dimension that would carry it further is proposed, not yet built.

---

## The platform data plane: one store, `project_id` origin

Axis 1 in detail. Intended end state: the platform operational store is a single DuckLake catalog (Decision 78) in the personal account, and typed ops/telemetry/recommendation rows carry a `project_id` column identifying origin. As proposed in the migration INTENT (to be implemented, not done): a default `project_id` of `trading-system` injected at write time from a `project_registry.yaml`; a **reserved** `platform` value the registry refuses; a two-phase `RecPayload`/`DecisionPayload` rollout; the platform Lambdas persisting `project_id` and the `query` verb filtering by it, with cross-`project_id` reads restricted to `PlatformAdmin`; principal-to-project binding via IAM session tags plus a shared binding module. This document **adopts that proposed design rather than inventing a second one** -- the "product dimension in the ops portal" from earlier drafts IS that `project_id`, not net-new.

**Per-domain format applies to a product's own data too.** A product's operational data (recs/telemetry/logs) lives in the shared DuckLake store tagged by `project_id`. A product's *domain* data follows the same per-domain rule Decision 78 sets, applied per product: large/analytical/multi-engine data on Iceberg, small operational data on DuckLake. The concrete tables for a second product (e.g. a Reaper asset/render catalogue) are out of scope here -- deferred to that product's own design; this document fixes only the *rule*, not the schema.

---

## Build-state reality (the IP wall is intent; its enforcement is future-state)

Every enforcement mechanism this document leans on is proposed, not built. This section is the honest inventory, because the "absolute" IP wall (Constraint 2) is only as strong as machinery that does not yet exist. **Do not onboard `dbt-daywork` until all of the following land.**

- **`project_id` is entirely unbuilt today.** Zero occurrences across `src/` and `scripts/`; no `config/project_registry.yaml`; no shared principal-binding module; no `project_id` field on `RecPayload`. It is sequenced behind several not-yet-complete tier items and candidate decisions still flagged provisional.
- **Coverage is partial by design.** The migration INTENT adds `project_id` to typed payloads (`RecPayload`/`DecisionPayload`/telemetry) only -- NOT to the generic `OpsWriter.write(table, dict)` primitive (`scripts/ops_data_portal.py`), and raw S3 agent-logs/transcripts have no payload schema at all. Cross-product meta-learning completeness is therefore bounded to typed rows; the "every row carries `project_id`" framing is aspirational.
- **DuckLake weakens the IAM tenancy claim.** Per-`project_id` IAM read-isolation (cross-`project_id` reads `PlatformAdmin`-only) was inherited from the Iceberg-on-S3 + Lambda-verb world. Decision 78 moved ops/telemetry to DuckDB-over-S3-Parquet + an RDS-Postgres catalog, where row/column-value authorization for an embedded engine is a different and weaker surface. Per-`project_id` isolation must be re-derived for that substrate; until then logical tenancy is advisory, reinforcing default-deny.
- **The COALESCE resurrection gate is unbuilt.** The migration INTENT *proposes* to forbid client-side `COALESCE(project_id, ...)` via a presubmit AST gate (T0.15); it is absent from `scripts/validate.py` today. Only prose forbids the anti-pattern now.
- **Rollback is not achievable today.** Ops data is still Iceberg/JSONL-staged (Decision 78: the JSONL-staging path "physically continues until FP-B/T2.19"), and `OPS_WRITER_FROZEN` is specced but absent. Under append-only Iceberg + SCD2, a leaked `dbt-daywork` row deleted by snapshot **resurrects from any stale clone** (the resurrection anti-pattern AGENTS.md warns of). Reliable rollback depends on the DuckLake write-path cutover (FP-B/T2.19) AND a freeze mechanism, both future-state.
- **Vocabulary collision.** The reserved `project_id` value `platform` is distinct from the PLATFORM tier of the Decision-77 account axis; the taxonomy linter (`validate_environment_taxonomy`) policies only `phase`/`environment` adjacency and will NOT catch this overload. Agents deriving `project_id` from context (Constraint 1) must disambiguate the origin value from the account-axis tier.

---

## The forcing function: the IP wall (why a second axis exists at all)

NS.2 binds your IP to your account. Run in reverse: day-job dbt is the employer's IP, so it must not enter the personal account, the personal DuckLake, or a personal repository. Two hard walls:

1. **No shared data plane for the day job.** Employer data lives in the employer's warehouse; it never lands in the personal DuckLake.
2. **Data-egress wall.** The agent loop feeds code and data to *your* personal inference credentials (the provider-agnostic executor's DeepSeek/Anthropic tier). Employer code/data must use employer-sanctioned credentials inside the employer boundary.

The monorepo + `project_id` model deliberately scoped the day job OUT (Part 2: "Cross-employer security boundary: irrelevant under monorepo"). This document takes the day job IN as a hosted product -- which is precisely what forces the second (code/repo) axis and the packaged substrate. For same-owner products there is no such wall, so no second axis: they stay monorepo + `project_id`.

---

## The three-plane model

| Plane | What it is | How products share it |
|---|---|---|
| **Substrate** | Portable dev-time paved road: reusable CI workflow, Terraform modules, the `.claude/` harness, the plan/implement/code-review methodology. | Same-owner products use it in-repo. The day job IMPORTS it (the only consumer that needs packaging). |
| **Automation** | Ops portal, executor, scheduled agents, telemetry/meta-learning. | Intended (mechanism unbuilt): ONE shared DuckLake store, `project_id`-tagged on typed rows -- NOT per-product instances. Exception: the day job runs its own local Automation in the employer boundary; only content-free meta-tier rows may egress (see Telemetry Tiering). |
| **Data** | Domain lakehouse tables. Per Decision 78 (ratifying CD.31): Iceberg for market-data/product tables, DuckLake for ops/telemetry; `project_id` origin on typed ops/telemetry. | Shared store, distinguished by `project_id`; a product's genuinely-separate domain data follows the same per-domain format rule (Iceberg for large/analytical, DuckLake for operational). |

Per-product opt-in (the "shared store" cells describe the intended end state; the `project_id` mechanism is unbuilt -- see Build-state reality):

| Product | `project_id` | Repo | Automation | Data |
|---|---|---|---|---|
| trading-system | `trading-system` (default) | monorepo | shared store* | shared* + Iceberg market-data |
| reaper-tools | `reaper-tools` | monorepo | shared store* | shared* + its own per-domain tables (format per the rule above) |
| dbt-daywork | `dbt-daywork` | **external (employer org)** | own local instance; meta-only egress | employer warehouse, never the personal account |

\* intended end state; depends on the unbuilt `project_id` mechanism.

---

## Telemetry tiering (how the day job could benefit the shared store without IP leak)

This is the intended reconciliation of "Automation should be cross-tenant" with the IP wall. Split every telemetry/ops field into two tiers:

| Tier | Contents | Intended to cross into the shared `project_id` store? |
|---|---|---|
| **Meta** | Content-free: token counts, retry counts, latency, failure taxonomy, rec lifecycle state transitions, skill/tool success rates. | Yes -- `project_id`-tagged rows in the ONE shared DuckLake. Same-owner products write here fully; the day job MAY replicate meta-only rows (`project_id=dbt-daywork`), employer policy AND the enforcement gate (below) permitting. |
| **Domain** | IP-bearing: dbt SQL, employer table/column names, data values, recommendation free-text titles that name employer schema. | No -- stays in the product's boundary, always. |

**OPEN RISK -- "content-free" is neither solved nor enforced, and the current telemetry schema is not field-separable.** There is no egress classifier, allowlist, or gate today. Worse, the split presumes field-level partitionability that `INTENT-telemetry-system.md`'s star schema does not provide: domain-bearing free-text (`transcript_path`, `local_path`, `description` NotNull, `error`) is structurally interleaved into the same tables as meta fields, so a clean column-filter does not separate the tiers. Concrete leak vectors in the rec schema: a recommendation's `file` path and `title` (both NotNull free-text -- the strong vectors); `source` is also NotNull but is a closed enum, so a weaker vector. Achieving the meta/domain split requires per-table field reclassification of the telemetry schema -- a **precondition** of any day-job egress, not a follow-up. Until a classifier + allowlist exist and are CI-enforced, the only safe posture is **default-deny: no day-job rows cross at all.**

---

## Repo topology

| Repo | `project_id`(s) | Owns | Boundary |
|---|---|---|---|
| `agent-platform` (this repo, the monorepo) | `platform` (reserved), `trading-system`, `reaper-tools` | Platform substrate + trading + reaper code, distinguished by `project_id`; the shared DuckLake store; platform roadmap | personal |
| `dbt-daywork` | `dbt-daywork` | dbt models + day-job layer-1 rules; its own local Automation | employer org + employer warehouse |

- **Split-repo extraction for same-owner products stays deferred** per `INTENT-aws-migration-platform-evolution.md` Part 2 (the extraction plan it references is not yet authored). Revisit only on a concrete trigger -- e.g. independent release cadence becomes load-bearing (OD-3).
- **Right-sizing:** the packaged substrate (git+pip / git-tagged module sources / a template repo) is built only when the external consumer (the day job) is actually onboarded. Same-owner products need no packaging.

---

## Tenancy mechanics

- **Logical tenancy via `project_id`** (the migration INTENT's proposed design) -- not physical store fragmentation. Per-`project_id` IAM isolation is intended for blast radius, but its enforcement surface must be re-derived for the DuckLake substrate (see Build-state reality) and is unbuilt; treat it as advisory today.
- **Physical separation only where IP forces it** (the day job) or where data is genuinely separate (per-product market-data Iceberg via prefixes/namespaces).
- **Single-Portal invariant preserved** (Decision 78 keeps it at the primitive level): all writes go through `scripts/ops_data_portal.py`; `project_id` is set at write time from the registry. Client-side `COALESCE(project_id, ...)` is the resurrection anti-pattern the migration INTENT proposes to forbid via a not-yet-built AST gate (T0.15; absent from `validate.py` today).

---

## Instruction architecture and the context-management dividend

Layer 1 (universal rules) splits into platform-universal (shipped in the harness, identical everywhere) and per-product layer-1 (trading's formula/PySR rules, Reaper's ReaScript rules, dbt's modeling conventions). In the monorepo, per-product layer-1 is selected by `project_id` context; the external day-job repo carries its own.

The dividend: a session working on Reaper loads platform-universal + Reaper layer-1, and NOT the trading product's context. Ambient context shrinks to what the task needs -- a direct advance of NS.4 (the repo is for agents). This is one of the strongest reasons to pursue the `project_id`-scoped split even before a second product is real.

---

## Relationship to `INTENT-aws-migration-platform-evolution.md` (explicit)

That document (Part 2) committed to monorepo + `project_id` for same-owner products and DEFERRED split-repo. This document does NOT reopen that. Its only additions are:

1. The cross-employer IP boundary (the day job) as a hosted product, which the monorepo model explicitly scoped out.
2. The packaged-substrate path forced by that boundary (and only that boundary).
3. The meta/domain telemetry tiering that *would* let the day job feed the shared `project_id` store without IP leak -- contingent on the unbuilt enforcement gate and a field-separable telemetry schema (Telemetry Tiering OPEN RISK).

No contradiction remains: same-owner = monorepo + `project_id` (their model); cross-employer = external repo + packaged substrate + meta-only egress (this extension). The `project_id` mechanism is shared, not duplicated -- and is unbuilt in both documents.

---

## Open Decisions (require ratification before implementation)

1. **OD-1: day-job meta-egress policy AND its enforcement interlock.** Default siloed; opt-in content-free aggregate meta only (`project_id=dbt-daywork`); gated by employer policy. Requires a *technical* interlock pinned to a gate file / tier-item (matching the migration INTENT's gate-pinning discipline), not prose: a registry/CI gate that refuses any `project_id=dbt-daywork` row into the personal store, plus the egress classifier/allowlist named in the Telemetry Tiering OPEN RISK. **`dbt-daywork` must not be onboarded until OD-1, OD-2, the egress gate, the DuckLake write-path cutover (FP-B/T2.19), AND a rollback/freeze mechanism all land** -- until then a leaked row is not cleanly reversible (resurrection risk; see Build-state reality).
2. **OD-2: licence permits day-job use** of the substrate without entangling personal IP or violating employer terms. Gates `dbt-daywork` entirely.
3. **OD-3: trigger to revisit split-repo for same-owner products.** Currently deferred per the migration INTENT; default is to stay monorepo + `project_id`. Name the trigger (e.g. independent release cadence) if/when it arises.
4. **OD-4: substrate versioning model.** Only load-bearing once the external (day-job) consumer exists; define semver + deprecation policy then.
5. **OD-5: KG.1 wording (dual-sense caveat).** KG.1 (`docs/ROADMAP-PLATFORM.yaml:3866`) is cited in two senses: its literal text is a known-gap note that the trading product roadmap lives in a sibling document (singular wording), but Decision 78 also invokes "the KG.1 platform/product boundary" as the Iceberg-vs-DuckLake split. Generalizing the roadmap to N products is therefore more than a cosmetic wording edit -- it touches a boundary other decisions lean on. Deferred; pin the exact sense when edited.

## Non-Goals

- **Not split-repo for same-owner products.** Deferred per the migration INTENT; only the day-job IP boundary forces an external repo.
- **Not fragmenting the platform operational data store per product.** It is ONE DuckLake + `project_id` origin.
- **Not superseding `INTENT-aws-migration-platform-evolution.md`.** This extends it to the cross-boundary case.
- **Not asserting any mechanism is built.** `project_id`, the registry, the egress gate, the COALESCE gate, and the rollback/freeze path are all proposed and unbuilt; this is a design record, not an implementation claim.
- **Not multiplying AWS accounts by product.** Account / blast-radius topology is the other axis, governed by Decision 77 / `environment-taxonomy.md`.
- **Not re-opening the per-domain table-format choice.** Ratified as Decision 78 (originating proposal CD.31).
- **Not building an internal developer platform.** No portal framework, private index, or module registry until solo-developer scale forces it.

## Constraints

1. **Agent-first.** A session derives its `project_id`, the planes it uses, and its account binding from the harness plus this document, without asking a human -- disambiguating the reserved `project_id=platform` from the PLATFORM account-axis tier (Build-state reality).
2. **The IP wall is absolute in intent; its enforcement is future-state.** No employer code, data, or domain-tier telemetry may enter the personal account, the personal DuckLake, or a personal repository -- ever. Because the enforcement + rollback substrate is unbuilt (Build-state reality), the operative posture is do-not-onboard the day job until that substrate lands. Correct even if no day-job meta ever flows.
3. **One data identity, not many stores.** Products are distinguished by `project_id`, not by fragmenting the platform store. No client-side `COALESCE(project_id, ...)` (resurrection anti-pattern).
4. **Concern-/IP-separation only.** Does not alter account topology, the Decision-77 two-axis taxonomy, or its reserved vocabulary.
5. **Default-deny egress (enforcement is unbuilt).** No field crosses the IP wall until a concrete egress classifier + allowlist exists, is CI-enforced, and the telemetry schema is field-separable; "content-free" is an unsolved property today, so the operative default is zero cross-flow.
6. **Single Portal preserved** (Decision 78). Writes go through `scripts/ops_data_portal.py`; `project_id` is set from the registry at write time.
7. **Right-sized for one developer.** Packaging is built only when the external consumer is onboarded.
8. **No emojis, no em-dashes.** Plain ASCII throughout (AGENTS.md).
