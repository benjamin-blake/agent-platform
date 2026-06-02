# Intent: Multi-Product Platform Topology

This document is the architectural anchor for how the agent-platform hosts multiple products -- the trading system, a Reaper music-tooling project, and day-job dbt development -- on a SINGLE platform operational data plane distinguished by a `project_id` origin dimension, reserving repo/package separation for the one case an IP boundary forces it (the day job). It **extends, and does not supersede,** the monorepo + `project_id` commitment in `docs/INTENT-aws-migration-platform-evolution.md` Part 2: that document established the model for same-owner products; this one carries it across the cross-employer IP boundary.

**Status:** Architectural anchor (exploratory). Records intent and boundaries; no migration committed, no recommendations filed, no executor work queued. Authoritative for vocabulary and boundaries on landing; authoritative for implementation only after the Open Decisions are ratified.

**Builds on:** NS.1 (storage durable, compute interchangeable -- generalized by Decision 78 to "S3 + open table format at every scale"), NS.2 (account ownership reflects IP ownership), NS.4 (the repo is for agents); Decision 78 (ratifies CD.31: Iceberg for market-data/product tables, DuckLake for ops/telemetry); Decision 77 + `docs/contracts/environment-taxonomy.md` (the two-axis account model -- NOT altered here); Decision 75 (frame-lock anti-pattern -- the two-axis framing below is a conscious frame choice); Decision 67 (REPORT-ONLY framing during the executor freeze); KG.1 (platform/product boundary, generalized to N products via `project_id`).

**Companion documents (load-bearing):**
- `docs/INTENT-aws-migration-platform-evolution.md` Part 2 -- the monorepo + `project_id` commitment this document extends. The `project_id` dimension, the `config/project_registry.yaml` registry, the reserved `platform` value, and the two-phase `RecPayload`/`DecisionPayload` rollout originate there; this document adopts them and does NOT redesign them.
- `docs/INTENT-telemetry-system.md` -- the telemetry shape the meta/domain tiering refines.
- `docs/contracts/environment-taxonomy.md` -- the account / blast-radius axis (a separate concern, not altered here).

**Terminology:** "product" = a distinct application/domain the platform operates on (`trading-system`, `reaper-tools`, `dbt-daywork`), identified by `project_id`. Trading is product #1, not a privileged peer. Orthogonal to the Decision-77 product axis (the trading strategy lifecycle).

---

## North Star: two orthogonal axes, not one choice

Hosting a second product was being framed as a single either/or -- monorepo vs split-repo. It is two independent axes:

1. **Data / identity axis -- unified.** The platform's operational data (ops, telemetry, recommendations, logs) lives in ONE store -- DuckLake per Decision 78 -- and every row carries a `project_id` **origin identity** naming the product the platform was operating on when it produced that row. Products are distinguished by a column, not by separate stores. Cross-product meta-learning is a query across `project_id` in one warehouse; this is what makes "benefit from every product's telemetry" hold by construction.

2. **Code / repo axis -- separated only where an IP boundary forces it.** Where the product's IP is the same owner's (trading, reaper), its code lives in the monorepo and is distinguished by `project_id` -- split-repo extraction stays deferred (`docs/plans/PLAN-platform-extraction-strategy.md`). Only the cross-employer case (day-job dbt) forces an external repo and a packaged, importable substrate, because employer IP cannot enter the personal repo or the personal data plane (NS.2 in reverse).

The earlier instinct "the platform must be a dependency products import, not a repo they live in" was right for exactly one case (the day job) and wrong as a universal rule. The frame this document fixes (Decision 75, frame-lock): the question is not "monorepo or split" but "which axis are we on -- shared data identity, or IP-forced code separation?". The seam already exists in code (`scripts/platform_roadmap.py` vs `scripts/product_roadmap.py`); `project_id` makes it a data dimension, not a repo boundary.

---

## The platform data plane: one store, `project_id` origin

Axis 1 in detail. The platform operational store is a single DuckLake catalog (Decision 78) in the personal account; ops, telemetry, and recommendation rows carry a `project_id` column. This is the migration INTENT's design, adopted wholesale:

- Default `project_id` is `trading-system`, injected at write time from `config/project_registry.yaml`'s `default_project_id` (never a literal in Lambda code).
- `platform` is a **reserved** `project_id` (the registry loader refuses it) for platform-origin rows.
- Two-phase rollout on `RecPayload`/`DecisionPayload` per T0.12; all six platform Lambdas persist `project_id`; the `query` verb filters by it, defaulting to the caller's bound project; cross-`project_id` reads are restricted to `PlatformAdmin`.
- Principal-to-project binding lives in IAM session tags plus `src/lambdas/_shared/principal_binding.py`.

The "product dimension in the ops portal" floated in earlier drafts of this document **is** this `project_id` -- it is already designed, not net-new. No second mechanism is introduced.

---

## The forcing function: the IP wall (why a second axis exists at all)

NS.2 binds your IP to your account. Run in reverse: day-job dbt is the employer's IP, so it must not enter the personal account, the personal DuckLake, or a personal repository. Two hard walls:

1. **No shared data plane for the day job.** Employer data lives in the employer's warehouse; it never lands in the personal DuckLake.
2. **Data-egress wall.** The agent loop feeds code and data to *your* inference credentials (DeepSeek / Anthropic, CD.28). Employer code/data must use employer-sanctioned credentials inside the employer boundary.

The monorepo + `project_id` model deliberately scoped the day job OUT (Part 2: "Cross-employer security boundary: irrelevant under monorepo"). This document takes the day job IN as a hosted product -- which is precisely what forces the second (code/repo) axis and the packaged substrate. For same-owner products there is no such wall, so no second axis: they stay monorepo + `project_id`.

---

## The three-plane model (corrected)

| Plane | What it is | How products share it |
|---|---|---|
| **Substrate** | Portable dev-time paved road: reusable CI workflow, Terraform modules, the `.claude/` harness, the plan/implement/code-review methodology. | Same-owner products use it in-repo. The day job IMPORTS it (the only consumer that needs packaging). |
| **Automation** | Ops portal, executor, scheduled agents, telemetry/meta-learning. | ONE shared DuckLake store, `project_id`-tagged -- NOT per-product instances. Exception: the day job runs its own local Automation in the employer boundary; only content-free meta-tier rows egress (see Telemetry Tiering). |
| **Data** | Domain lakehouse tables. Per Decision 78 (ratifying CD.31): Iceberg for market-data/product tables, DuckLake for ops/telemetry; `project_id` origin on ops/telemetry. | Shared store, distinguished by `project_id`; genuinely-separate product/market data uses per-product prefixes/namespaces. |

Per-product opt-in:

| Product | `project_id` | Repo | Automation | Data |
|---|---|---|---|---|
| trading-system | `trading-system` (default) | monorepo | shared store | shared + Iceberg market-data |
| reaper-tools | `reaper-tools` | monorepo | shared store | shared + its own namespaces |
| dbt-daywork | `dbt-daywork` | **external (employer org)** | own local instance; meta-only egress | employer warehouse, never the personal account |

---

## Telemetry tiering (how the day job benefits the shared store without IP leak)

This is the reconciliation of "Automation should be cross-tenant" with the IP wall. Split every telemetry/ops field into two tiers:

| Tier | Contents | Crosses into the shared `project_id` store? |
|---|---|---|
| **Meta** | Content-free: token counts, retry counts, latency, failure taxonomy, rec lifecycle state transitions, skill/tool success rates. | Yes -- `project_id`-tagged rows in the ONE shared DuckLake. Same-owner products write here fully; the day job MAY replicate meta-only rows (`project_id=dbt-daywork`), employer policy permitting. |
| **Domain** | IP-bearing: dbt SQL, employer table/column names, data values, recommendation free-text titles that name employer schema. | No -- stays in the product's boundary, always. |

So "Automation is cross-tenant" is true for the **meta tier** (one store, query across `project_id`) and false for the **domain tier**. Same-owner recs land in the shared store in full; day-job recs whose titles name employer schema are domain-tier -- they live in the day-job local Automation, and only their content-free lifecycle/counts cross. **Default-deny:** a field crosses the wall only if provably content-free and allowlisted; the system must be correct even if no day-job meta ever flows.

---

## Repo topology

| Repo | `project_id`(s) | Owns | Boundary |
|---|---|---|---|
| `agent-platform` (this repo, the monorepo) | `platform` (reserved), `trading-system`, `reaper-tools` | Platform substrate + trading + reaper code, distinguished by `project_id`; the shared DuckLake store; platform roadmap | personal |
| `dbt-daywork` | `dbt-daywork` | dbt models + day-job layer-1 rules; its own local Automation | employer org + employer warehouse |

- **Split-repo extraction for same-owner products stays deferred** (`docs/plans/PLAN-platform-extraction-strategy.md`), per the migration INTENT. Revisit only on a concrete trigger -- e.g. independent release cadence becomes load-bearing (OD-3).
- **Right-sizing:** the packaged substrate (git+pip / git-tagged module sources / a template repo) is built only when the external consumer (the day job) is actually onboarded. Same-owner products need no packaging.

---

## Tenancy mechanics

- **Logical tenancy via `project_id`** (the migration INTENT's design) -- not physical store fragmentation. IAM is scoped per `project_id` for blast radius; cross-`project_id` reads are `PlatformAdmin`-only.
- **Physical separation only where IP forces it** (the day job) or where data is genuinely separate (per-product market-data Iceberg via prefixes/namespaces).
- **Single-Portal invariant preserved** (Decision 69 / 78): all writes go through `scripts/ops_data_portal.py`; `project_id` is set at write time from the registry. No client-side `COALESCE(project_id, ...)` in any writer -- the resurrection anti-pattern the migration INTENT forbids via a presubmit AST gate.

---

## Instruction architecture and the context-management dividend

Layer 1 (universal rules) splits into platform-universal (shipped in the harness, identical everywhere) and per-product layer-1 (trading's formula/PySR rules, Reaper's ReaScript rules, dbt's modeling conventions). In the monorepo, per-product layer-1 is selected by `project_id` context; the external day-job repo carries its own.

The dividend: a session working on Reaper loads platform-universal + Reaper layer-1, and NOT the trading product's context. Ambient context shrinks to what the task needs -- a direct advance of NS.4 (the repo is for agents). This is one of the strongest reasons to pursue the `project_id`-scoped split even before a second product is real.

---

## Relationship to `INTENT-aws-migration-platform-evolution.md` (explicit)

That document (Part 2) committed to monorepo + `project_id` for same-owner products and DEFERRED split-repo. This document does NOT reopen that. Its only additions are:

1. The cross-employer IP boundary (the day job) as a hosted product, which the monorepo model explicitly scoped out.
2. The packaged-substrate path forced by that boundary (and only that boundary).
3. The meta/domain telemetry tiering that lets the day job feed the shared `project_id` store without IP leak.

No contradiction remains: same-owner = monorepo + `project_id` (their model); cross-employer = external repo + packaged substrate + meta-only egress (this extension). The `project_id` machinery is shared, not duplicated.

---

## Open Decisions (require ratification before implementation)

1. **OD-1: day-job meta-egress policy.** Default siloed; opt-in content-free aggregate meta only (`project_id=dbt-daywork`); gated by employer policy. Until ratified, assume zero egress.
2. **OD-2: licence permits day-job use** of the substrate without entangling personal IP or violating employer terms. Gates `dbt-daywork` entirely.
3. **OD-3: trigger to revisit split-repo for same-owner products.** Currently deferred per the migration INTENT; default is to stay monorepo + `project_id`. Name the trigger (e.g. independent release cadence) if/when it arises.
4. **OD-4: substrate versioning model.** Only load-bearing once the external (day-job) consumer exists; define semver + deprecation policy then.
5. **OD-5: KG.1 wording.** `project_id` already generalizes "which product" in the data plane; KG.1's singular "the product roadmap" wording could be generalized to N. Small roadmap edit, deferred.

## Non-Goals

- **Not split-repo for same-owner products.** Deferred per the migration INTENT; only the day-job IP boundary forces an external repo.
- **Not fragmenting the platform operational data store per product.** It is ONE DuckLake + `project_id` origin.
- **Not superseding `INTENT-aws-migration-platform-evolution.md`.** This extends it to the cross-boundary case.
- **Not multiplying AWS accounts by product.** Account / blast-radius topology is the other axis, governed by Decision 77 / `environment-taxonomy.md`.
- **Not re-opening the per-domain table-format choice.** Ratified as Decision 78 (originating proposal CD.31).
- **Not building an internal developer platform.** No portal framework, private index, or module registry until solo-developer scale forces it.

## Constraints

1. **Agent-first.** A session derives its `project_id`, the planes it uses, and its account binding from the harness plus this document, without asking a human.
2. **The IP wall is absolute.** No employer code, data, or domain-tier telemetry enters the personal account, the personal DuckLake, or a personal repository -- ever. Correct even if no day-job meta ever flows.
3. **One data identity, not many stores.** Products are distinguished by `project_id`, not by fragmenting the platform store. No client-side `COALESCE(project_id, ...)` (resurrection anti-pattern).
4. **Concern-/IP-separation only.** Does not alter account topology, the Decision-77 two-axis taxonomy, or its reserved vocabulary.
5. **Default-deny egress.** A telemetry field crosses the IP wall only if provably content-free and explicitly allowlisted.
6. **Single Portal preserved** (Decision 69 / 78). Writes go through `scripts/ops_data_portal.py`; `project_id` is set from the registry at write time.
7. **Right-sized for one developer.** Packaging is built only when the external consumer is onboarded.
8. **No emojis, no em-dashes.** Plain ASCII throughout (AGENTS.md).
