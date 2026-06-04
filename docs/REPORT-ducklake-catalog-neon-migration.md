# REPORT: DuckLake catalog migration RDS -> Neon -- platform-roadmap change-set

**Status:** Draft for zero-context review (REPORT-ONLY)
**Date:** 2026-06-04
**Slug:** ducklake-catalog-neon-migration
**Plan:** docs/plans/PLAN-ducklake-catalog-neon-migration.md
**Scope of this report:** enumerate exactly what changes in `docs/ROADMAP-PLATFORM.yaml` (and the
one new candidate decision) if the DuckLake operational-lakehouse *catalog backend* moves from the
just-provisioned AWS RDS PostgreSQL instance (T2.16) to Neon serverless Postgres, and justify each
change. This report does NOT edit the roadmap; it is the proposal that, once consensus is reached,
gets folded into the roadmap and opened as a PR.

---

## 1. Executive summary

T2.16 stood up a `db.t4g.micro` RDS PostgreSQL instance on 2026-06-03 as the DuckLake catalog
(metadata) backend. It is the single largest *live* AWS line item now that the EC2 runner retired
(CD.21). The proposal is to replace it with Neon serverless Postgres (free tier, $0) before the
DuckLake Lambda runtime (T2.17) gets built around an RDS-in-a-VPC posture.

**Feasibility is high and demonstrated** -- DuckLake-on-Neon is a documented working pattern (Neon is
Postgres 14+, satisfying DuckLake's PG12+/SQL-92/PK-OCC catalog contract). **Timing is optimal** --
nothing consumes the catalog yet (T2.17-T2.19 are `not_started`; live ops are still Iceberg/Athena),
so the blast radius of switching now is zero. The change is **governance-clean** because Neon, like
RDS, is "a small managed cloud state-store," which is exactly the framing NS.3 / Decision 78 used to
justify the catalog in the first place -- we are re-pricing an instantiation, not reversing a decision.

**Recommendation: conditional GO**, gated on two pre-conditions (a connection-compatibility smoke test
and a mandatory independent catalog backup -- both detailed in section 6/10).

The roadmap change-set is **one new candidate decision (CD.34)**, **one new tier item (T2.16b)**, and
**surgical amendments to T2.17, T2.18, T2.19, CD.33, OQ.8, OQ.9, OQ.14, and the cost model**. None of
these touch `docs/DECISIONS.md` (CD.34 stages pending, mirroring the CD.33 -> Decision 81 rhythm).

---

## 2. Background: how DuckDB / DuckLake / the catalog fit together

| Layer | Role | Where it lives |
|-------|------|----------------|
| **DuckDB** | Embedded compute engine; executes every query | In-process (Lambda) |
| **DuckLake** | Open table format; splits a table into metadata + data | n/a (format) |
| **Data** | Parquet files | S3 (`agent-platform-data-lake`) |
| **Catalog** | Table/snapshot/version pointers (and, by default, sub-threshold "inlined" rows) | **A transactional SQL database -- today the RDS instance** |

The catalog is **a Glue-analog metadata store, not a query engine** (Decision 78 / CD.31). The
load-bearing property for this whole assessment: **the catalog is the lakehouse's single point of total
failure.** DuckLake v1.0 has no Iceberg metadata export and no external-engine reader (OQ.7), so the S3
Parquet is unreadable without the catalog -- snapshots ARE catalog rows. Lose the catalog without a
backup and the entire ops/telemetry lakehouse is unrecoverable. This is why the catalog's durability
and DR posture (OQ.9) dominate the risk section.

**Current repo state (post-#68 rebase):**
- T2.16 (RDS catalog) -- `status: complete`, `completed_at: 2026-06-03`. RDS `db.t4g.micro`, single-AZ,
  gp3, PITR=7d, RDS-managed master secret in Secrets Manager, publicly accessible behind a CIDR
  allow-list, `rds.force_ssl=1`. The `ducklake_ops` schema was created out-of-band (not a Terraform
  resource). `terraform/personal/rds_ducklake_catalog.tf` + the three `ducklake_catalog_*` vars.
- CD.33 (pending) -- the just-landed DuckLake ops *runtime* architecture (writer/reader/maintenance
  split, OCC retry, `current` projection, SCD2 keys, guarded GC). Ratification (Decision 81) is drafted
  but NOT filed; CD.33 is `state: pending`.
- T2.17 / T2.18 / T2.19 -- `not_started`. T2.17's design assumes a private VPC the Lambdas attach to in
  order to reach the RDS catalog.
- **Nothing reads or writes the catalog yet.** The live ops warehouse remains Iceberg/Athena until the
  T2.19 cutover (FP-B).

---

## 3. The proposal and why now

**Proposal:** retire the RDS catalog and back DuckLake with a Neon serverless Postgres project on the
free tier; authenticate the DuckLake Lambdas to Neon via a connection string held in AWS Secrets Manager.

**Why (rationale that the roadmap edits encode):**

1. **Cost -- the largest live line.** Roadmap cost line (`ROADMAP-PLATFORM.yaml:176`):
   `rds_ducklake_catalog: ~$12-15/mo ... +$10-12 if RDS Proxy added`. CD.33's `O-5` mandates RDS Proxy,
   so the RDS path realistically lands at **~$22-27/mo**. Neon free tier is **$0**. (Note: the cost
   model's `dominant_cost` field still names the EC2 runner that CD.21 already retired -- so the RDS is
   in fact the largest *live* enumerated AWS cost; see section 4.8.)
2. **Feasibility is demonstrated, not speculative.** Neon is Postgres 14-17 -> satisfies DuckLake's
   PG12+/SQL-92/PK-based-OCC catalog contract. A public practitioner writeup ATTACHes DuckLake directly
   to a Neon connection string (`ATTACH 'ducklake:postgres:' ...`), and Neon's own docs cite DuckDB as
   an engine against a Neon metadata catalog.
3. **Timing is the cheapest it will ever be.** The migration is best done *before* T2.17, because T2.17
   otherwise builds VPC-attach plumbing, an RDS Proxy, and IAM/SG posture specifically to reach a private
   RDS -- all of which Neon (a public TLS endpoint) obviates. And since nothing consumes the catalog yet,
   there is no data to migrate and no live path to break.
4. **Governance alignment (NS.3).** Decision 78 / CD.31 rest the catalog choice on NS.3 ("supports a
   small managed cloud state-store") and NS.1 (storage durable; engines/compute interchangeable). Neon is
   also a small managed cloud Postgres state-store, so evaluating it is consistent with the ratified
   frame; Decision 78 chose one *instantiation*, which an assessment may legitimately re-price.

**Grounded Neon facts (researched 2026-06; sources in section 11):**

| Property | Neon free tier | Current RDS |
|----------|----------------|-------------|
| Monthly cost | **$0** (no card) | ~$12-15 (+$10-12 Proxy) |
| Engine | Postgres 14-17 | Postgres 16 |
| Storage | 0.5 GB / project (ample for metadata-only) | 20 GB gp3 (autoscale 100) |
| Compute | 100 CU-hours/mo, scale-to-zero after 5 min idle | always-on db.t4g.micro |
| Cold resume | ~300-500ms (p99 ~500ms); sub-100ms pooled-after-wake | n/a (always warm) |
| PITR | **~6 hours / 1 GB changes** | **7 days** |
| Pooling | built-in PgBouncer pooler endpoint | needs separate RDS Proxy (~$10-12/mo) |
| Ownership | Databricks (acquired May 2025) | AWS-native |

The catalog stores only metadata (pointers), so 0.5 GB and 100 CU-hours are comfortable for an
intermittent ops/telemetry write rate. The two columns that matter for risk are **PITR (6h vs 7d)** and
**ownership/SLA (free tier on an acquired vendor)** -- both addressed in section 6.

---

## 4. The platform-roadmap change-set (what we are changing)

Nine edits. Each row below is a precise before -> after that the post-consensus PR will execute.

### 4.1 NEW candidate decision CD.34 (state: pending) -- the backend swap

A new `candidate_decisions` entry **CD.34**, inserted after CD.33:

- **Title:** "DuckLake catalog backend: migrate RDS PostgreSQL -> Neon serverless Postgres."
- **Substance:** narrowly amends Decision 78 / CD.31 clause-3 (catalog backend = a dedicated micro RDS
  PostgreSQL) to "catalog backend = Neon serverless Postgres (free tier), connection via Secrets Manager."
  Everything else in Decision 78 / CD.31 (DuckLake adoption, S3-Parquet data plane, DuckDB engine, the
  catalog-is-a-metadata-store framing, the closed boundary) is **preserved unchanged**.
- **`state: pending`**, `filed_via: pending_log_decision_lambda`. Does NOT edit `DECISIONS.md` while
  pending; ratified later via the log-decision path as a new Decision (provisionally **Decision 82**,
  sequenced after Decision 81 files CD.33). This mirrors the CD.31 -> Decision 78 and CD.33 -> Decision 81
  rhythm exactly.
- **`gates: [T2.16b, T2.17, T2.18, T2.19]`** -- the migration tier item plus the three runtime items
  whose RDS-specific clauses it amends.
- **discipline_points:** (i) narrowly amends Decision 78/CD.31 backend clause; preserves all else;
  (ii) supersedes the OQ.8 resolution "RDS + IAM-auth-preferred" (IAM DB auth is not available against a
  non-AWS endpoint; Secrets Manager is the credential mechanism); (iii) reframes CD.33's `O-2`/`O-5`
  catalog-recovery mechanics from RDS-native (snapshot/Proxy) to Neon-native (pg_dump/built-in pooler) --
  consequential to the backend, not a reopening of CD.33's runtime architecture.

**Why a new CD rather than editing Decision 78 in place:** Decision 78 is *ratified*. The Single Portal /
governance model requires a ratified decision to be amended by a new ratified decision, not silently
rewritten. Staging it as CD.34 (pending) routes it through the same zero-context review ritual the other
candidate decisions used.

### 4.2 NEW tier item T2.16b -- Neon provisioning + Secrets Manager auth + RDS retirement

Inserted between T2.16 and T2.17 (the migration must precede the Lambda runtime). Proposed shape:

- **name:** "DuckLake catalog migration to Neon + RDS retirement."
- **depends_on:** `[T2.16]`; **gates / unblocks:** T2.17.
- **intent:** Provision a Neon project in the AWS region nearest `eu-west-2`; create the `ducklake_ops`
  database/schema; store the Neon connection string in a Secrets Manager secret; validate a DuckDB
  `ATTACH` round-trip (TLS `sslmode=require`, SNI, and the pooled-vs-direct endpoint decision -- see
  section 5/6); then retire the RDS instance (flip `deletion_protection`, destroy, retain final snapshot).
- **files_in_scope (proposed):** Neon provisioning (manual or a vetted `terraform/personal/` Neon-provider
  module -- see risk R5), `terraform/personal/rds_ducklake_catalog.tf` (deleted on retirement),
  `terraform/personal/variables.tf` (`ducklake_catalog_*` vars removed), Secrets Manager secret for the
  Neon DSN.
- **exit_criteria (proposed):**
  - Neon project live; `ducklake_ops` reachable; `SELECT 1` via DuckDB `ATTACH` succeeds with
    `sslmode=require` and SNI on the **pinned DuckDB version** (smoke test).
  - Connection-endpoint decision recorded: direct (unpooled) vs pooled (PgBouncer) endpoint, with the
    DuckLake catalog transaction semantics (advisory locks / prepared statements) verified on the chosen
    endpoint.
  - Neon connection string stored in Secrets Manager; runtime-fetch validated (Decision 37 pattern).
  - RDS retired: `deletion_protection=false` then destroy; **final snapshot `ducklake-catalog-final-snapshot`
    retained** for rollback; `rds_ducklake_catalog.tf` deleted; Terraform apply human-gated (Decision 35,
    and the destroy trips the Decision 77 fail-closed guard -> manual `agent_platform_admin` apply).
  - Closes ~6 open RDS-module code-review recs by deletion (rec-2062/2063/2064/2067/2068/2069).
- **effort:** S. **related_candidate_decisions:** `[CD.34]`.

### 4.3 AMEND T2.17 -- drop VPC-attach and RDS Proxy

| Element | Before (current) | After (proposed) | Why |
|---------|------------------|------------------|-----|
| `name` | "DuckLake Lambda runtime -- **VPC attach** + extension layer + version pin" | "DuckLake Lambda runtime -- extension layer + version pin" | Neon is a public TLS endpoint; no VPC attach needed to reach it |
| `intent` | "VPC-attached execution so they can reach the **RDS catalog**...VPC egress blocks extensions.duckdb.org, so extensions must be pre-baked" | "...reach the **Neon catalog** over TLS (no VPC attach for catalog reachability). Extensions remain pre-baked for reproducibility + cold-start determinism" | Removes VPC-attach; the extension-layer pre-bake justification shifts from "egress blocked" to "deterministic/reproducible" (still best practice) |
| exit: RDS Proxy | "**RDS Proxy** fronts the catalog connection pool for writer/reader (CD.33 T2-e/O-5)" | "**Neon's built-in PgBouncer pooler** fronts the catalog connection pool; no separate RDS Proxy (CD.33 O-5 as amended by CD.34)" | Neon's pooler replaces RDS Proxy; removes ~$10-12/mo and NAT complexity |
| exit: ATTACH | "VPC-attached and able to reach **RDS catalog**; ATTACH succeeds in Lambda" | "Able to reach the **Neon catalog** over TLS; ATTACH succeeds in Lambda (SNI + sslmode=require verified)" | Vendor + transport correction |
| exit: break-glass | "PlatformAdmin break-glass: granted catalog (**RDS**) + S3 read" | "PlatformAdmin break-glass: granted the **Neon catalog credential (Secrets Manager) + S3 read**" | Break-glass reads Neon, not an RDS/IAM grant |
| `related_candidate_decisions` | `[CD.31, CD.10, CD.33]` | add `CD.34` | Trace the amendment |

### 4.4 AMEND T2.18 -- catalog DR mechanism

| Before | After | Why |
|--------|-------|-----|
| "Catalog DR: daily **PITR/snapshot export of the RDS catalog** to a dedicated versioned S3 bucket (CD.33 O-2)" | "Catalog DR: daily **`pg_dump` of the Neon catalog** to a dedicated versioned S3 bucket; restore-from-dump runbook (CD.33 O-2 as amended by CD.34)" | Neon has no RDS snapshot API; a logical `pg_dump` is the export primitive. **More important on Neon** -- free-tier PITR is ~6h, so the independent S3 dump is the real DR floor, not a backstop |
| `related_candidate_decisions: [CD.31, CD.29, CD.33]` | add `CD.34` | trace |

### 4.5 AMEND T2.19 -- catalog rebuild source + break-glass

| Before | After | Why |
|--------|-------|-----|
| "Catalog DR restore drilled: a catalog rebuilt from the daily S3 **PITR export**..." | "...rebuilt from the daily S3 **`pg_dump`**..." | matches 4.4 mechanism |
| "...audited PlatformAdmin break-glass path" (catalog read = RDS) | break-glass catalog read = **Neon credential via Secrets Manager** | matches 4.3 |
| `related_candidate_decisions: [CD.31, CD.33]` | add `CD.34` | trace |

### 4.6 AMEND CD.33 (pending) -- vendor-neutralise 3 RDS references (surgical)

CD.33 is `state: pending`, so amending it is governance-clean (no DECISIONS.md transition). These are
**surgical, consequential edits, NOT a reopening of CD.33's runtime architecture** (the writer/reader/
maintenance split, OCC retry, `current` projection, SCD2 keys, guarded GC all stand verbatim):

| CD.33 location | Before | After |
|----------------|--------|-------|
| clause (3) | "...snapshot committed in the **RDS catalog txn**..." | "...snapshot committed in the **catalog txn** (Neon Postgres per CD.34)..." |
| clause (6) | "PlatformAdmin principal (expanded to **catalog+S3 read**)" break-glass | "...expanded to **Neon-catalog-credential + S3 read**..." |
| `enforcement_mechanism` | "...guarded destructive-GC...; **PlatformAdmin break-glass (catalog+S3 read) + daily catalog PITR-to-S3**; partition-prune smoke test..." | "...; **PlatformAdmin break-glass (Neon credential + S3 read) + daily pg_dump-to-S3; Neon built-in pooler (no RDS Proxy)**; partition-prune smoke test..." |
| `discipline_points` | (none on backend) | ADD: "Catalog backend = Neon serverless Postgres per CD.34 (narrowly amends Decision 78/CD.31); O-2 DR = daily pg_dump-to-S3, O-5 pooling = Neon's built-in pooler. CD.33's runtime architecture is unchanged by the backend swap." |

### 4.7 AMEND OQ.8 + OQ.9 -- reopen/annotate

- **OQ.8** ("RDS catalog backend -- sizing, RDS Proxy, credential mechanism", resolved at T2.16): append a
  "Re-resolved (CD.34): backend = Neon serverless Postgres; RDS Proxy -> Neon's built-in pooler;
  credential = Secrets Manager connection string (IAM DB auth N/A against a non-AWS endpoint). The
  original 'IAM-auth-preferred' note is moot." (OQ stays as a record; the annotation pattern matches the
  CD.33 OQ.7/10/11 annotations.)
- **OQ.9** ("Catalog durability, DR, SPOF", resolved at T2.16): append "Re-resolved (CD.34): DR baseline =
  Neon PITR (~6h free tier) **plus a mandatory independent daily pg_dump to a versioned S3 bucket** -- the
  S3 dump is the real recovery floor because free-tier PITR is far shorter than the RDS 7-day window. SPOF
  property is unchanged; the mitigation is the independent backup, not the provider."

### 4.8 AMEND cost model (line 176; + one flagged adjacency)

| Before | After |
|--------|-------|
| `rds_ducklake_catalog: "~$12-15/mo ... +$10-12 if RDS Proxy added..."` | `ducklake_catalog_neon: "$0 (Neon serverless Postgres free tier; scale-to-zero; built-in pooler replaces RDS Proxy). Replaces the retired RDS catalog per CD.34. Independent daily pg_dump to S3 is a negligible add-on."` |

**Flagged adjacency (out of scope for this PR, file as a rec):** `dominant_cost: EC2 self-hosted runner
(~$35/mo)` and `ec2_runner_24_7: "~$35"` are already stale -- CD.21 retired that runner. After this
migration the dominant *live* AWS line becomes CloudWatch logs ($3-8) / DeepSeek inference (~$5). The
cost model deserves a separate freshness pass; this report only zeroes the RDS line.

### 4.9 AMEND OQ.14 (minor) -- separability wording

OQ.14 (catalog multi-tenancy, deferred to FP-C) is phrased in RDS terms ("shared ops-RDS-schema vs
dedicated instance"). Re-map to Neon's primitives: "shared Neon project + separate databases" /
"separate Neon projects per env" (Neon branching is a natural fit for per-environment catalogs). The
question stays open; only the option wording updates. Low priority.

---

## 5. Auth model: Lambda -> Neon via Secrets Manager

Today the RDS path uses an RDS-managed master-user secret in Secrets Manager. The Neon path keeps the
Secrets-Manager shape but the secret content changes:

- **Secret:** a Neon connection DSN (host `ep-*.<region>.aws.neon.tech`, db, user, password) or its
  components, stored in a Secrets Manager secret. Rotation is Neon-side (rotate the role password; update
  the secret) -- manual, low-frequency, acceptable for a metadata catalog. This reuses the **Decision 37**
  "secret in Secrets Manager, Lambda runtime-fetch" precedent.
- **Connection:** DuckDB's `postgres`/`ducklake` extension `ATTACH` takes a libpq DSN/URI. Neon requires
  TLS (`sslmode=require`) and **SNI** to route to the right compute endpoint. Recent libpq (which DuckDB
  bundles) sends SNI; the pinned DuckDB version must be smoke-tested, with the endpoint-ID parameter as
  the documented fallback if SNI is absent.
- **Network:** because Neon is reached over the public internet on TLS, the DuckLake Lambdas **no longer
  need VPC attach for catalog reachability** (they still use an S3 gateway endpoint or default egress for
  Parquet). This is the chief simplification: it removes the private-VPC/NAT/RDS-Proxy stack that T2.17
  was going to build. **Trade-off:** we lose network-level privacy (SG allow-list + private subnet) and
  rely on TLS + Neon's IP allow-listing instead. For metadata pointers behind TLS with a scoped role, this
  is an acceptable posture for a sandbox PLATFORM environment; section 6 R3 covers it.

---

## 6. Risks and mitigations

| # | Risk | Severity | Mitigation (where it lands) |
|---|------|----------|------------------------------|
| R1 | Catalog is the lakehouse SPOF; Neon free-tier PITR is only ~6h | **High** | Mandatory daily `pg_dump` -> versioned, lifecycle-managed S3 bucket + tested restore runbook. Gates T2.18/T2.19 (4.4/4.5). This is non-negotiable before any production write. |
| R2 | DuckDB <-> Neon connection compat: SNI on the pinned DuckDB; pooled (PgBouncer transaction-mode) endpoint may break catalog session semantics (advisory locks, prepared statements) | **High** | Smoke test on the pinned DuckDB at T2.16b: verify `ATTACH` + a DuckLake write/commit on **both** the direct and pooled endpoints; default to the **direct** endpoint for the catalog if pooling breaks transaction semantics. Hard gate on T2.16b. |
| R3 | Public TLS endpoint replaces SG/VPC network privacy | Medium | `sslmode=require` enforced; Neon IP allow-listing; scoped Neon role (not owner); secret in Secrets Manager; break-glass via Secrets Manager not a standing grant. Acceptable for a sandbox PLATFORM env. |
| R4 | Free tier on an acquired vendor (Databricks) -- ToS/longevity/SLA risk for irreplaceable data | Medium | The independent S3 `pg_dump` (R1) makes us provider-independent; the migration is fully reversible (section 7). Re-evaluate if Neon changes free-tier terms (add a roadmap reevaluation trigger). |
| R5 | IaC: the Decision 77 sandbox auto-apply guard covers AWS resources, not a third-party Neon provider | Medium | Option A (recommended): provision Neon manually (console/API) + store the DSN in Secrets Manager, keeping IaC AWS-only. Option B: a vetted `terraform/personal/` Neon-provider module, explicitly excluded from auto-apply (human-gated). Decide at T2.16b. |
| R6 | Cold-start (~300-500ms) on the catalog critical path for every read/write after 5-min idle | Low | Acceptable for intermittent ops/telemetry writes; pin the Neon region nearest `eu-west-2` and measure real round-trip in the smoke test. The trading hot-path does NOT use this catalog (it is DynamoDB + Iceberg per D.fast / D.lake), so latency-sensitive paths are unaffected. |

---

## 7. Rollback / reversibility

The migration is cleanly reversible, and the blast radius **right now is zero** (nothing consumes the
catalog):

- **Retirement is snapshot-safe.** `rds_ducklake_catalog.tf` has `skip_final_snapshot = false` +
  `final_snapshot_identifier = "ducklake-catalog-final-snapshot"`, so destroy produces a final snapshot.
  `delete_automated_backups = true` wipes only the *automated* PITR backups, **not** the final snapshot
  (this nuance is the substance of open rec-2063 -- the report makes it explicit). The final snapshot
  captures the full instance including the out-of-band `ducklake_ops` schema.
- **Rollback path:** restore `ducklake-catalog-final-snapshot` into a new `aws_db_instance` (re-add the
  `.tf`), repoint the Secrets Manager secret. Because the snapshot carries the schema, no out-of-band
  re-creation is needed (a fresh-provision rollback, by contrast, would re-create `ducklake_ops`).
- **Deliberate destroy.** `deletion_protection = true` forces the two-step retire (flip off, then
  destroy), human-gated under `agent_platform_admin` (Decision 35); the destroy trips the Decision 77
  guard's fail-closed gate, so it cannot auto-apply.

---

## 8. Alternatives considered (brief)

| Option | $/mo (free/idle) | DuckLake catalog fit | Verdict |
|--------|------------------|----------------------|---------|
| **Neon serverless Postgres** (proposed) | $0 free | PG14+; OCC/concurrent-writer OK; built-in pooler; demonstrated DuckLake-on-Neon | **Recommended** |
| Aurora Serverless v2 (provisioned Postgres-compatible) | not free; scale-to-zero added 2024 but bills per ACU-hour + storage, ~$40+/mo realistic; ~15s resume | Strong (full Postgres) | Rejected -- not free; this is the *cost* lever. (Distinct from Aurora DSQL, which CD.31 already dropped as unvalidated against DuckLake's catalog contract.) |
| Supabase (managed Postgres) | $0 free | Full Postgres; OK | Viable but free tier **pauses projects after ~1 week idle** -> worse cold/availability story than Neon for an intermittent catalog |
| DuckDB/SQLite catalog **file on S3** | $0 (S3 only) | **Breaks CD.33** -- a file catalog has no transactional multi-writer / OCC coordination | Rejected -- incompatible with the just-ratified concurrent-writer + OCC runtime (CD.33 clause 2). Cheapest, but architecturally regressive |

---

## 9. Decisions this report must cite

| Decision | Relationship |
|----------|--------------|
| **Decision 78 / CD.31** | The decision being narrowly amended (catalog backend). Revisited, not overturned; CD.34 preserves all else. |
| **Decision 35 + Decision 77** | RDS retirement is a Terraform destroy -> human-gated; trips the fail-closed auto-apply guard onto the manual admin path. |
| **Decision 37** | Precedent for the "secret in Secrets Manager, Lambda runtime-fetch" auth model reused for the Neon DSN. |
| **CD.21** | EC2 runner retired -- the cost baseline that makes the RDS the largest live line. |
| **CD.33 / Decision 81 (pending)** | Related; this report makes only *consequential* backend amendments (O-2/O-5 mechanics) and does not reopen its runtime architecture. |
| **NS.1 / NS.3** | The "small managed cloud state-store" framing that already justifies a managed Postgres catalog; Neon fits it. |

---

## 10. Recommendation and sequencing

**Conditional GO.** Proceed with the migration, gated on:
1. **R2 smoke test passes** -- DuckDB (pinned version) ATTACHes and commits a DuckLake transaction against
   the chosen Neon endpoint (direct unless pooled is proven transaction-safe).
2. **R1 backup live** -- the daily `pg_dump` -> versioned S3 + restore runbook is in place before any
   production write transits the Neon catalog.

**Sequencing:**
```
CD.34 (decide, pending -> Decision 82)
  -> T2.16b  (provision Neon + Secrets Manager + R2 smoke test + retire RDS w/ final snapshot)
    -> T2.17 (Lambda runtime built against Neon: no VPC attach, Neon pooler, Secrets Manager DSN)
      -> T2.18 (maintenance + daily pg_dump-to-S3 DR)
        -> T2.19 (write/read cutover; restore drill from pg_dump)
```
Doing CD.34 + T2.16b before T2.17 is the whole point: it prevents building (then tearing down) the
RDS-in-a-VPC plumbing.

---

## 11. Sources (Neon facts, researched 2026-06)

- Neon pricing / free-tier limits (100 CU-hours, 0.5 GB, scale-to-zero, PITR 6h/1GB): https://neon.com/pricing , https://neon.com/docs/introduction/plans
- Neon scale-to-zero / cold-resume latency (~300-500ms; sub-100ms pooled): https://neon.com/docs/introduction/scale-to-zero , https://neon.com/docs/connect/connection-latency
- Neon connection / SNI / pooling (libpq SNI requirement; PgBouncer pooled endpoint): https://neon.com/docs/connect/connection-pooling , https://neon.com/docs/connect/choose-connection
- DuckDB Postgres extension ATTACH (libpq DSN/URI; pooler notes): https://duckdb.org/docs/lts/core_extensions/postgres
- DuckLake-on-Neon working pattern: https://rvernica.github.io/2025/06/ducklake-with-postgres
- Databricks acquisition of Neon (May 2025; free tier retained, CU-hours doubled): https://www.databricks.com/company/newsroom/press-releases/databricks-agrees-acquire-neon-help-developers-deliver-ai-systems
