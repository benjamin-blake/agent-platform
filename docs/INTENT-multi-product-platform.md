# Intent: Multi-Product Platform Separation

This document is the architectural anchor for separating the agent-platform *substrate* from the *trading product* so the substrate can host multiple heterogeneous products -- the trading system, a Reaper music-tooling project, and day-job dbt development -- without forking the repository. It records the separation-of-concerns model (three planes), the repo topology (what lives where), the telemetry/IP boundary rules, and the agent context-management dividend. It generalizes KG.1's platform/product boundary from a single product to N products.

**Status:** Architectural anchor (exploratory). Records intent and the separation model; no migration is committed, no recommendations are filed, no executor work is queued. "Host N products" is a forward-looking direction, not a scheduled change. Authoritative for *vocabulary and boundaries* the moment it lands; authoritative for *implementation* only after the open decisions in the Open Decisions section are ratified as Decision Records.

**Builds on:** NS.1 (storage durable, compute interchangeable -- generalized by Decision 78 to "S3 + open table format at every scale"), NS.2 (account ownership reflects IP ownership), NS.4 (the repo is for agents); Decision 77 + `docs/contracts/environment-taxonomy.md` (the two-axis model -- explicitly NOT altered here); Decision 78 (ratifies CD.31: Iceberg for market-data/product tables, DuckLake for ops/telemetry); Decision 75 (frame-lock anti-pattern -- the dependency inversion below is a conscious frame choice); Decision 67 (REPORT-ONLY framing during the executor freeze); KG.1 (platform/product boundary, here generalized to N products).

**Companion documents:** `docs/contracts/environment-taxonomy.md` (account / blast-radius axis); `docs/INTENT-telemetry-system.md` (the telemetry shape the meta/domain tiering refines); `docs/contracts/instruction-architecture.md` (the 5-layer model that splits per product); `docs/ROADMAP-PLATFORM.yaml` + `docs/ROADMAP-PRODUCT.md`.

**Terminology:** In this document "product" means a distinct application/domain built on the platform substrate (`trading-system`, `reaper-tools`, `dbt-daywork`), each in its own repository. Trading is product #1, not a privileged peer. This is a strict generalization of the existing singular "product" (which referred to trading). It is orthogonal to the Decision-77 product axis (the trading strategy lifecycle, research through full capital allocation), which remains a property of the trading product specifically.

---

## North Star

One move defines this architecture: **invert the dependency.** Today the platform is embedded *in* the trading product -- they are one repository, and the platform's universal rules (AGENTS.md) are trading-flavored. To host N products, the platform must become a *dependency that products import*, not a *repository that products live in*.

"Do not fork" is correct: forking yields N diverging copies of the substrate to maintain. "Do not host everything in one repo" is equally correct: that couples unrelated products' blast radius and -- fatally -- cannot hold day-job IP (see The Forcing Function). The resolution is neither. The substrate is packaged and consumed; products are thin repos that depend on it.

This makes the platform/product seam load-bearing rather than conceptual: the package boundary *is* the seam. The seam already exists in code (`scripts/platform_roadmap.py` vs `scripts/product_roadmap.py`); this document completes the direction it implies.

Treating the platform as a repo rather than an artifact is the frame this document deliberately breaks (Decision 75, frame-lock anti-pattern): the question is not "how do products share this repo" but "why is the platform a repo at all".

---

## What This Changes

Current state (June 2026): one repository, `pyproject.toml` + `src/` already package-shaped, platform and trading intertwined. KG.1 names "the product roadmap" -- singular. One product is assumed everywhere.

Target state: the substrate is a versioned, importable artifact; each product is its own repository depending on it. KG.1 generalizes -- the platform roadmap stays platform-only; *each product* owns its own product roadmap in its own repo.

This is a separation by **concern** (a repo / package boundary). It is NOT a separation by **blast radius** (an account boundary). Account topology -- isolation across accounts, gated by the trading product's capital-allocation trigger -- is a different axis, governed entirely by `docs/contracts/environment-taxonomy.md` and Decision 77. This document does not alter it, does not multiply accounts, and does not touch the reserved environment / phase vocabulary.

---

## The Forcing Function: IP Boundaries

The architecture is decided by one constraint, and it is NS.2 running in reverse. NS.2 binds *your* IP to *your* account: the trading IP is yours, so it lives in the personal account. The inverse binds equally: **day-job dbt work is the employer's IP, so it must not enter the personal account or a personal repository.** Two hard walls follow:

1. **No shared data plane for the day job.** Employer data lives in the employer's warehouse. It never lands in the personal lakehouse.
2. **Data-egress wall.** The agent loop feeds code and data to *your* inference credentials (DeepSeek / Anthropic, per CD.28). Pointing that at employer code or data likely violates the employer's data-handling policy and entangles work-for-hire IP. The day-job product must use employer-sanctioned credentials inside the employer boundary.

This is what forces *portable artifact* over *shared host*. The payoff: once the substrate is portable enough for the day job, it serves Reaper -- and any future product -- for free. The hardest-boundary consumer defines the interface; the easy ones inherit it.

---

## The Three-Plane Model

The substrate decomposes into three planes. Each product opts into only the planes it needs.

| Plane | What it is | Bound to |
|---|---|---|
| **Substrate** | Dev-time paved road: reusable CI workflow (`validate.py` two-tier), Terraform modules, the `.claude/` harness (skills, slash commands, hooks), the AGENTS.md scaffold, the plan / implement / code-review methodology. | Nothing -- fully portable. |
| **Automation** | Runtime services: the ops portal (`file_rec` / `update_rec`), recommendation queue, autonomous executor, scheduled agents, telemetry / meta-learning. | An account + the meta / domain egress policy (see Telemetry Tiering). |
| **Data** | Domain lakehouse tables. Per Decision 78 (ratifying CD.31): Iceberg for market-data/product tables, DuckLake for ops/telemetry; each product's data plane inherits this per-domain choice. | An account + IP ownership (NS.2). |

Per-product opt-in:

| Plane | trading-system | reaper-tools | dbt-daywork |
|---|---|---|---|
| Substrate | adopts | adopts | **adopts -- the only shared layer** |
| Automation | tenant (personal account) | tenant (personal account) | own instance in employer boundary; meta-tier only may cross (see Telemetry Tiering) |
| Data | tenant, then dedicated account at the capital trigger | tenant (personal account) | employer warehouse, never the personal account |

The Substrate plane is the crown jewel: most reusable, least product-specific, and the only thing the day job can legally take. Extract it first.

---

## Telemetry Tiering (Automation across the IP wall)

The goal is a cross-product Automation plane -- one meta-learning surface that improves from *all* products' signal, including the day job. This collides with the egress wall. The resolution is a **two-tier telemetry split**:

| Tier | Contents | Examples | Crosses the IP wall? |
|---|---|---|---|
| **Meta** | How the agent behaved. Product-agnostic. Content-free. | token counts, retry counts, latency, failure taxonomy, rec lifecycle state transitions, skill / tool success rates | Yes -- *may* feed a shared cross-product meta-store, subject to per-product egress policy |
| **Domain** | What the agent worked on. IP-bearing. | dbt model SQL, employer table / column names, data values, rec *titles* that name employer schema | No -- stays in the product's boundary, always |

So "Automation is fully tenant" is true for the **meta tier** and false for the **domain tier**. For trading + reaper (same owner, same account) there is no wall: share both tiers freely. For the day job:

- **Default is siloed.** The day-job Automation instance runs entirely inside the employer boundary. The system must be *correct even if no day-job telemetry ever reaches the personal meta-store.*
- **Opt-in, content-free aggregates only.** Any cross-flow is allowlisted, numeric / enumerated, and stripped of domain content (no free-text titles, no identifiers) -- and only if employer policy permits. The safe default assumption is that it permits none.
- **Scrubbing is non-trivial.** A rec title like "fix the join in customer_revenue" leaks schema. Meta-tier egress therefore carries no free text -- only enumerated taxonomies and numbers. If a field cannot be proven content-free, it is domain-tier by default.

This tiering refines `docs/INTENT-telemetry-system.md`: every telemetry field gains a `tier: meta | domain` classification, and the egress boundary is drawn at that classification, not at the product boundary.

---

## Repo Topology (what lives where)

| Repo | Owns | Consumes | Account / boundary |
|---|---|---|---|
| `agent-platform` (this repo, refactored) | The three planes as publishable artifacts: `agent-platform-core` (pip-installable -- ops portal, executor, lakehouse client, agent glue), `terraform-agent-platform/*` (TF modules, git-tagged), `.claude/` harness template + reusable CI workflow. Platform roadmap. Platform-universal layer-1 rules. | -- | personal |
| `trading-system` | The trading product: formulas, ensembles, capital config, its product roadmap, trading layer-1 rules. | platform artifacts | personal; dedicated account at the capital trigger (per the taxonomy contract) |
| `reaper-tools` | The Reaper product: ReaScript automation, asset catalog, render pipelines, its product roadmap + layer-1 rules. | platform artifacts | personal (tenant) |
| `dbt-daywork` | The dbt product: models, day-job layer-1 rules. | Substrate plane only | employer org + employer warehouse |

Transitional intermediate (optional): trading may remain in this repo as `products/trading/` while the substrate is extracted in place, splitting out once the package boundary is proven. The day job is external from day one -- it cannot pass through a personal repo even transiently.

Right-sizing (this is a solo developer, not a platform org): `pip install git+https://...@vX` over a private package index; git-tagged module `source =` over a Terraform registry; a template repo over a developer-portal framework. Adopt the heavier form only when the lighter one demonstrably hurts.

---

## Tenancy Mechanics (products that share the personal account)

For trading + reaper co-tenanting one account (until the trading capital trigger graduates trading to its own account):

- **Namespace isolation, not account isolation.** One Glue catalog; per-product databases (`trading`, `reaper`); S3 prefixes `s3://.../<product>/...`; separate DuckLake catalogs (separate Postgres schemas) for ops.
- **IAM role per product** (`agent-platform-<product>-exec`), scoped to that product's prefixes and databases. The executor assumes the product's role. Per-product blast radius even inside one account.
- **A `product` dimension in the ops warehouse.** `file_rec(product="reaper", ...)`; IDs remain atomic but namespaced; scheduled agents run per-product. This is the one substantive Automation-plane code change -- the portal is single-tenant today (`scripts/ops_data_portal.py` carries no product key).

---

## Instruction Architecture and the Context-Management Dividend

The 5-layer instruction contract (`docs/contracts/instruction-architecture.md`) absorbs multi-product cleanly, and doing so is itself a primary benefit.

Today layer 1 (universal rules, AGENTS.md) is loaded ambiently into *every* session and is trading-flavored. Under separation it splits:

- **Platform-universal layer 1** (branching, the lakehouse-as-source-of-truth invariant, ops governance, safety, shell conventions) ships in the harness template and is identical across products.
- **Product layer 1** is authored per repo: trading's formula / PySR rules, Reaper's ReaScript rules, dbt's modeling conventions.

The dividend: a session working on Reaper loads platform-universal + Reaper layer 1, and *not* the trading product's context. Ambient context shrinks to what the task needs. This directly serves NS.4 (the repo is for agents): smaller, sharper per-product context is a context-management win, not merely an organizational one. It is one of the strongest reasons to pursue the split even before a second product is real.

---

## Open Decisions (require ratification before implementation)

1. **OD-1: Telemetry egress policy for the day job.** Default siloed; opt-in content-free aggregate meta only; gated by employer policy. Needs a Decision Record and, before any day-job adoption, written confirmation of employer data-handling and tooling policy. Until ratified, assume zero day-job egress.
2. **OD-2: Platform licence permits day-job use.** Confirm this repo's `LICENCE` allows using the substrate at the day job without entangling personal IP or violating employer terms. Gates `dbt-daywork` entirely.
3. **OD-3: Trading in-repo vs split-out.** Whether trading stays as `products/trading/` here or moves to its own repo, and on what trigger. Affects the migration sequence, not the end-state.
4. **OD-4: Versioning model.** The substrate stops being a moving HEAD and becomes a semver dependency with a changelog and a deprecation policy. Define the cadence and the support window before a second product pins a version.
5. **OD-5: KG.1 generalization.** Update KG.1 (and the planning skill's platform/product assumptions) from "the product roadmap" (singular) to N product roadmaps. A small roadmap edit, deferred until this doc is ratified.

These are candidate decisions, not yet filed. This document is exploratory; filing follows ratification.

---

## Sequencing (non-binding sketch, not yet actioned)

Order is chosen so the cheapest-to-extract layer serves the hardest-boundary consumer first.

1. Finish the platform / product code seam already underway (`platform_roadmap.py` vs `product_roadmap.py` is the leading edge). Prerequisite.
2. Extract the **Substrate plane** (harness template + reusable CI workflow + Terraform modules). Cheapest, highest reuse, and the only layer the day job needs.
3. Add the **`product` dimension** to the Automation plane (ops portal tenancy + per-product scheduled agents) and the `tier: meta | domain` telemetry classification.
4. Onboard **Reaper** as the first full-stack second product -- dogfoods data-plane multi-tenancy in the safe personal-account zone.
5. Onboard **dbt** Substrate-only, in the employer boundary, after OD-1 and OD-2 clear.

No step is filed as a recommendation; per the AGENTS.md Temporary Operational Constraints this is a design record, not a STRATEGIC plan. The sequence is reversible; only the *direction* (toward a packaged, consumed substrate) is asserted.

---

## Non-Goals

- **Not multiplying AWS accounts by product.** Account / blast-radius topology is the other axis, governed by `docs/contracts/environment-taxonomy.md` and Decision 77, gated by the trading capital trigger. This document is concern-separation (repo / package), not account-separation, and does not touch the reserved environment / phase vocabulary.
- **Not a committed migration.** No recommendations filed; no executor work queued (REPORT-ONLY; consistent with Decision 67 and the AGENTS.md Temporary Operational Constraints).
- **Not building an internal developer platform.** No developer-portal framework, no private package index, no module registry until solo-developer scale demonstrably requires them.
- **Not re-opening the per-domain table-format choice.** Ratified as Decision 78 (originating proposal CD.31): Iceberg for market-data/product tables, DuckLake for ops/telemetry. The Data plane inherits it per product.

---

## Constraints

1. **Agent-first.** A session working on any product derives its boundaries (which planes it uses, which telemetry tier a field is, which account it binds to) from the harness template plus this document, without asking a human.
2. **The IP wall is absolute.** No employer code, data, or domain-tier telemetry enters the personal account, the personal lakehouse, or a personal repository -- ever. The system is correct even if day-job meta-telemetry never flows.
3. **Concern-separation only.** This document draws repo / package boundaries. It does not alter account topology, the two-axis taxonomy, or the reserved vocabulary (Decision 77 / `environment-taxonomy.md`).
4. **The portable substrate defines the interface.** The day job -- the hardest-boundary consumer, taking Substrate only -- defines the substrate's public surface. If a capability cannot be taken across that boundary, it belongs in Automation or Data, not Substrate.
5. **Default-deny telemetry egress.** A telemetry field crosses the IP wall only if it is provably content-free and explicitly allowlisted. Unproven fields are domain-tier.
6. **Right-sized for one developer.** Prefer the lightest mechanism (git + pip, tagged module sources, a template repo) until it demonstrably hurts.
7. **No fork.** The substrate is consumed as a versioned dependency, never copied. Divergence is the failure mode this architecture exists to prevent.
8. **No emojis, no em-dashes.** Plain ASCII throughout (repo-wide; AGENTS.md).
