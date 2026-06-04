# REPORT: DuckLake catalog migration RDS -> Neon -- platform-roadmap change-set

**Status:** Draft v3 for zero-context review (REPORT-ONLY)
**Date:** 2026-06-04
**Slug:** ducklake-catalog-neon-migration
**Plan:** docs/plans/PLAN-ducklake-catalog-neon-migration.md
**Scope of this report:** enumerate exactly what changes in `docs/ROADMAP-PLATFORM.yaml` (and the one new
candidate decision) if the DuckLake operational-lakehouse *catalog backend* moves from the just-provisioned
AWS RDS PostgreSQL instance (T2.16) to Neon serverless Postgres, and justify each change. This report does
NOT edit the roadmap; it is the proposal that, once consensus is reached, gets folded into the roadmap and
opened as a PR.

## Revision log

### v2 -> v3 (second review round: both lenses converged on one shared blocker + secondary fixes)
- **Inlining override now landed in the enforcement surfaces (the v2 blocker, both lenses):** v2 disabled
  inlining for all tables in prose + the OQ.11 note + a CD.33 discipline point, but left the telemetry
  carve-out intact where it is actually enforced (CD.33 clause (5) `:1346`; OQ.11 resolution `:4017`;
  T2.17 exit `:3323`; T2.18 exit `:3348`) and even claimed "clause 5 stands verbatim". v3 adds those four
  edits to the change-set (4.1/4.3/4.4/4.6/4.7) and reworks the CD.33 framing so it no longer claims the
  carve-out is untouched -- the GC/merge *cadences* are unchanged; the clause-5 telemetry-inlining carve-out
  is explicitly overridden.
- **rec-2063 RDS-side action dispositioned** (4.2/7): the catalog is provably unused at T2.16b, so
  single-final-snapshot recovery on destroy is explicitly accepted; the contingency (flip
  `delete_automated_backups=false` first) applies only if retirement is ever deferred past the T2.19 cutover.
- **Connection-churn promoted to a measured gate** (4.2/4.3/6 R2): the direct-endpoint default reintroduces
  the OQ.8 churn->OCC-collision risk; v3 makes "direct-endpoint churn + commit latency within CD.33's OCC
  budget OR an app-side pool implemented" a hard T2.16b/T2.17 exit-criterion, not a non-binding "consider".
- **Telemetry small-file load sized** (4.1/4.4/6): disabling telemetry inlining shifts small-file load onto
  compaction; v3 requires a higher-frequency `merge_adjacent_files` cadence for high-write-rate tables (or a
  sized inter-merge accumulation justification) at T2.18 -- honouring the disable-everywhere decision.
- **Dump-freshness alarm + version-drift note** (4.4/6 R1): a silently-failed daily dump widens RPO; v3 adds
  a CloudWatch freshness alarm (page if no new dump object >25h) and a re-baseline note on engine bumps.
- **Schema DDL captured in-repo** (4.2/7): the out-of-band `ducklake_ops` schema-creation DDL is captured as
  a versioned migration so the Neon database creation (T2.16b) and any fresh-provision rollback are
  reproducible, not tribal.
- **Citation-precision fixes:** OQ.11 anchor corrected to `:4017`; the maintenance-cadence figures
  (weekly GC, expire 30d/7d) re-attributed to CD.33 `enforcement_mechanism` (`:1379`) + T2.18 exit (`:3353`),
  not clause (5); rec-2064's concern dispositioned (logical `pg_dump` tolerates Neon Postgres-minor drift).

### v1 -> v2 (first review round)
v2 incorporates the two zero-context report-critique gates (architect/correctness + adversarial ops-risk)
and three human judgment calls. Material changes from v1:
- **Inlining decided (human):** `inlined_rows=0` for ALL Neon tables, including telemetry (overrides OQ.11's
  telemetry carve-out). This closes the catalog-only durability window entirely -- the v1 "catalog holds
  only pointers" premise is now actually true for every table (it was false in v1 for inlined telemetry).
- **Backup decided (human):** daily `pg_dump` -> dedicated versioned S3 bucket, explicit daily schedule +
  30-day retention. RPO stated honestly (catastrophic-case ~24h; intra-6h recovery via Neon PITR).
- **IaC decided (human):** provision Neon via the Terraform Neon provider, human-gated (carved out of the
  Decision-77 auto-apply guard) -- NOT manual/console.
- **Cost corrected:** RDS Proxy is *deferrable* (OQ.8/T2.16), not mandated; realized RDS baseline is
  ~$12-15/mo, not the $22-27 v1 implied.
- **CD.33 edit-set corrected:** v1 fabricated a "clause (6)" before-quote and mis-modelled O-2/O-5/T2-e as
  CD.33 sub-clauses. CD.33's *body* needs only clause (3) + `enforcement_mechanism` edits (+ one additive
  discipline point); O-2/O-5/T2-e are tier-item back-references handled in 4.3-4.5.
- **Feasibility honesty:** the in-repo spike is SQLite-file only; Postgres/Neon ATTACH is documented
  externally and gated on the smoke test (v1 over-claimed "demonstrated, not speculative").
- **Added missed touch-points:** OQ.7 + OQ.11 amendments, and a non-destructive `[Amendment -- CD.34]`
  annotation on the CD.31 record itself.
- **Hardened DR/rollback:** consistent-dump flags + engine-version-pinned artifact; tested restore moved to
  T2.16b (before any production write); fixed-`final_snapshot_identifier` collision handled; rec-2063
  reframed (it is a warning, not supporting evidence); pooler/Proxy removal made conditional on the smoke
  test; blast-radius framing split into "now" vs "at T2.19 cutover".

---

## 1. Executive summary

T2.16 stood up a `db.t4g.micro` RDS PostgreSQL instance on 2026-06-03 as the DuckLake catalog (metadata)
backend. It is the largest *live* AWS line item now that the EC2 runner retired (CD.21). The proposal is to
replace it with Neon serverless Postgres (free tier, $0) **before** the DuckLake Lambda runtime (T2.17) gets
built around an RDS-in-a-VPC posture.

**Feasibility is high but not yet proven in-repo** -- Neon is Postgres 14-17 (satisfies DuckLake's
PG12+/SQL-92/PK-OCC catalog contract) and DuckLake-on-Neon is documented externally, but the only in-repo
DuckLake ATTACH proof-of-concept uses a *local SQLite catalog file*; the Postgres/Neon ATTACH is gated on a
T2.16b smoke test. **Timing is optimal** -- nothing consumes the catalog yet (T2.17-T2.19 `not_started`;
live ops are still Iceberg/Athena), so the blast radius of switching *now* is zero. The change is
**governance-clean** because Neon, like RDS, is "a small managed cloud state-store" -- the NS.3 framing
Decision 78 used to justify the catalog -- so this re-prices an instantiation, not reverses a decision.

**Two-state framing (a v2 correction):** "safe to provision Neon + retire the unused RDS *now*" is genuinely
low-risk and supportable on the present evidence. "Neon is an acceptable *production* catalog backend at the
T2.19 cutover" is a higher bar -- at cutover the catalog becomes the lakehouse's single point of total
failure -- so the DR gates below are sized for the T2.19 state, not the zero-blast-radius present.

**Recommendation: conditional GO**, gated on (a) a connection-compatibility smoke test and (b) a *tested*
catalog backup/restore -- both as T2.16b preconditions (section 6/10).

The roadmap change-set is **one new candidate decision (CD.34)**, **one new tier item (T2.16b)**, and
**surgical amendments to T2.17, T2.18, T2.19, CD.33, the CD.31 record, OQ.7/8/9/11/14, and the cost model**.
None touch `docs/DECISIONS.md` (CD.34 stages pending, mirroring the CD.33 -> Decision 81 rhythm).

---

## 2. Background: how DuckDB / DuckLake / the catalog fit together

| Layer | Role | Where it lives |
|-------|------|----------------|
| **DuckDB** | Embedded compute engine; executes every query | In-process (Lambda) |
| **DuckLake** | Open table format; splits a table into metadata + data | n/a (format) |
| **Data** | Parquet files | S3 (`agent-platform-data-lake`) |
| **Catalog** | Table/snapshot/version pointers (+ optionally sub-threshold "inlined" rows) | **A transactional SQL database -- today the RDS instance** |

The catalog is **a Glue-analog metadata store, not a query engine** (Decision 78 / CD.31). The load-bearing
property: **the catalog is the lakehouse's single point of total failure.** DuckLake v1.0 has no Iceberg
metadata export and no external-engine reader (OQ.7), so the S3 Parquet is unreadable without the catalog --
snapshots ARE catalog rows. Lose the catalog without a backup and the entire ops/telemetry lakehouse is
unrecoverable. This dominates the risk section.

**Current repo state (post-#68 rebase, branch `claude/clever-allen-LE9T0`):**
- T2.16 (RDS catalog) -- `status: complete`, `completed_at: 2026-06-03`. RDS `db.t4g.micro`, single-AZ, gp3,
  PITR=7d (continuous), RDS-managed master secret in Secrets Manager (`manage_master_user_password = true`),
  publicly accessible behind a CIDR allow-list, `rds.force_ssl=1`. `ducklake_ops` schema created out-of-band
  (not a Terraform resource). `terraform/personal/rds_ducklake_catalog.tf` + three `ducklake_catalog_*` vars.
- CD.33 (pending) -- the just-landed DuckLake ops *runtime* architecture (writer/reader/maintenance split,
  OCC retry, `current` projection, SCD2 keys, guarded GC). Ratification (Decision 81) drafted, NOT filed.
- T2.17 / T2.18 / T2.19 -- `not_started`. T2.17's design assumes a private VPC the Lambdas attach to to
  reach the RDS catalog.
- **Nothing reads or writes the catalog yet.** Live ops remain Iceberg/Athena until the T2.19 cutover (FP-B).

---

## 3. The proposal and why now

**Proposal:** retire the RDS catalog and back DuckLake with a Neon serverless Postgres project (free tier);
authenticate the DuckLake Lambdas to Neon via a connection string held in AWS Secrets Manager.

**Why (rationale the roadmap edits encode):**

1. **Cost -- the largest live line.** Cost model (`ROADMAP-PLATFORM.yaml:176`):
   `rds_ducklake_catalog: ~$12-15/mo ... +$10-12 if RDS Proxy added`. **The honest RDS baseline is
   ~$12-15/mo**; RDS Proxy is *deferrable* (OQ.8:3967 and T2.16:3257 both say so -- "worth it only if Lambda
   cold-start connection churn causes catalog OCC collisions"), NOT mandated. Neon free tier is **$0**, so
   the realized-today saving is **~$12-15/mo**, with the avoided RDS-Proxy spend (~$10-12) a *conditional*
   additional saving, not bankable up front. (The cost model's `dominant_cost`/`ec2_runner_24_7` fields
   still name the EC2 runner CD.21 retired -- so the RDS is in fact the largest *live* enumerated AWS cost;
   see section 4.8.)
2. **Feasibility -- documented externally, gated in-repo.** Neon is Postgres 14-17 -> satisfies DuckLake's
   PG12+/SQL-92/PK-OCC catalog contract. A public writeup ATTACHes DuckLake directly to a Neon connection
   string, and Neon's docs cite DuckDB-as-engine against a Neon catalog. **Caveat (v2):** the only in-repo
   DuckLake proof-of-concept (`src/common/ducklake_spike.py`) uses a *local SQLite catalog file*; there is
   no committed Postgres-backed ATTACH (the T2.16 RDS ATTACH was done out-of-band). So feasibility is
   "documented, not yet exercised in our code" -- the T2.16b smoke test (R2) is the proof gate.
3. **Timing is the cheapest it will ever be.** Best done *before* T2.17, because T2.17 otherwise builds VPC
   attach, an RDS Proxy, and IAM/SG posture specifically to reach a private RDS -- all of which Neon (a
   public TLS endpoint) obviates. And since nothing consumes the catalog yet, there is no data to migrate
   and no live path to break.
4. **Governance alignment (NS.3).** Decision 78/CD.31 rest the catalog choice on NS.3 ("supports a small
   managed cloud state-store") and NS.1 (storage durable; engines/compute interchangeable). Neon is also a
   small managed cloud Postgres state-store, so evaluating it is consistent with the ratified frame.

**Grounded Neon facts (researched 2026-06; sources in section 11):**

| Property | Neon free tier | Current RDS |
|----------|----------------|-------------|
| Monthly cost | **$0** (no card) | ~$12-15 (Proxy +$10-12 optional, deferrable) |
| Engine | Postgres 14-17 | Postgres 16 |
| Storage | 0.5 GB / project (ample for metadata-only) | 20 GB gp3 (autoscale 100) |
| Compute | 100 CU-hours/mo, scale-to-zero after 5 min idle | always-on db.t4g.micro |
| Cold resume | ~300-500ms (p99 ~500ms); sub-100ms pooled-after-wake | n/a (always warm) |
| Inactivity | compute suspends (auto-resume); branches >14d-old + >24h-idle auto-archive to cold storage (auto-unarchive). **No project pause/delete for inactivity.** | n/a |
| PITR | **~6 hours / 1 GB changes** (then nothing) | **7 days continuous** (~5-min RPO in-window) |
| Pooling | built-in PgBouncer pooler endpoint | needs separate RDS Proxy (~$10-12/mo) |
| Ownership | Databricks (acquired May 2025) | AWS-native |

The catalog stores only metadata pointers (and, with inlining disabled per section 4.1, *only* pointers), so
0.5 GB and 100 CU-hours are comfortable for an intermittent ops/telemetry write rate. The two columns that
drive risk are **PITR (6h vs 7d continuous)** and **ownership/SLA (free tier, acquired vendor)** -- both
addressed in section 6.

---

## 4. The platform-roadmap change-set (what we are changing)

Each row is a precise before -> after that the post-consensus PR will execute.

### 4.1 NEW candidate decision CD.34 (state: pending) -- the backend swap

A new `candidate_decisions` entry **CD.34**, inserted after CD.33:

- **Title:** "DuckLake catalog backend: migrate RDS PostgreSQL -> Neon serverless Postgres."
- **Substance:** narrowly amends the **CD.31 catalog-backend paragraph (`ROADMAP-PLATFORM.yaml:1176`,
  "a dedicated micro RDS PostgreSQL instance") / Decision 78 item** to "catalog backend = Neon serverless
  Postgres (free tier), provisioned via the Terraform Neon provider (human-gated), connection via Secrets
  Manager." (CD.31/Decision 78 are paragraph-structured, not clause-numbered -- a v2 wording correction.)
  Everything else in Decision 78/CD.31 (DuckLake adoption, S3-Parquet data plane, DuckDB engine, the
  catalog-is-a-metadata-store framing, the closed boundary) is **preserved unchanged**.
- **`state: pending`**, `filed_via: pending_log_decision_lambda`. Does NOT edit `DECISIONS.md` while pending;
  ratified later as a new Decision (provisionally **Decision 82**, sequenced after Decision 81 files CD.33).
- **`gates: [T2.16b, T2.17, T2.18, T2.19]`**.
- **discipline_points:** (i) narrowly amends the CD.31 catalog-backend paragraph; preserves all else;
  (ii) **inlining is disabled for ALL Neon tables (`ducklake_default_data_inlining_row_limit=0`), including
  telemetry** -- this *overrides the telemetry-inlining carve-out wherever it is enforced* (CD.33 clause (5)
  `:1346`, the OQ.11 resolution `:4017`, and the T2.17/T2.18 inlining exit-criteria `:3323`/`:3348` -- all
  edited in 4.3/4.4/4.6/4.7, not just described here) so no table is ever catalog-only-durable on the free
  tier (closes the catalog-only durability window entirely). The small-file load this shifts onto compaction
  is handled by a higher-frequency merge for high-write-rate tables (4.4). Re-enable inlining per-table later
  only if a write-rate need arises; (iii) supersedes OQ.8's "IAM-auth-preferred" note (IAM DB auth is unavailable
  against a non-AWS endpoint -- Secrets Manager DSN is the credential mechanism); (iv) the backend swap
  reframes CD.33's catalog-recovery references (clause 3 + `enforcement_mechanism`) and the T2.17-T2.19
  catalog exit-criteria from RDS-native (snapshot/Proxy) to Neon-native (pg_dump/built-in pooler) --
  consequential to the backend, NOT a reopening of CD.33's runtime architecture.

**Why a new CD rather than editing Decision 78 in place:** Decision 78 is *ratified*; governance requires a
ratified decision be amended by a new ratified decision, not silently rewritten. Staging it as CD.34
(pending) routes it through the same zero-context review ritual the other candidate decisions used.

### 4.2 NEW tier item T2.16b -- Neon provisioning + Secrets Manager auth + RDS retirement

Inserted between T2.16 and T2.17 (the migration must precede the Lambda runtime). Proposed shape:

- **name:** "DuckLake catalog migration to Neon + RDS retirement."
- **depends_on:** `[T2.16]`. **Edits T2.17 `depends_on`** from `[T2.16]` to `[T2.16, T2.16b]` so the runtime
  no longer depends only on the retired item.
- **intent:** Provision a Neon project (AWS region nearest `eu-west-2`) via the Terraform Neon provider;
  create the `ducklake_ops` database; store the Neon DSN in Secrets Manager; validate a DuckDB `ATTACH`
  round-trip (TLS `sslmode=require`, SNI, pooled-vs-direct endpoint decision -- section 5/6); run a
  **one-off tested `pg_dump` + restore-into-scratch-Neon drill** (DR proof before any production write);
  then retire the RDS instance.
- **files_in_scope (proposed):**
  - `terraform/personal/neon_ducklake_catalog.tf` (new) -- Neon project/branch/role/database/IP-allowlist
    via the Terraform Neon provider; provider config; **explicitly excluded from Decision-77 auto-apply
    (human-gated apply)**.
  - Secrets Manager secret for the Neon DSN (the Neon API key for the provider is itself a Secrets Manager
    secret).
  - `terraform/personal/rds_ducklake_catalog.tf` (deleted on retirement); `terraform/personal/variables.tf`
    (`ducklake_catalog_*` vars removed); `terraform/personal/platform_roles.tf` (the
    `PlatformDuckLakeCatalogProvisioning` RDS/snapshot/kms grant removed -> closes rec-2065/2066).
- **exit_criteria (proposed):**
  - Neon project live via Terraform (declarative state); `ducklake_ops` reachable; DuckDB `ATTACH` +
    `SELECT 1` succeeds with `sslmode=require` and SNI on the **pinned DuckDB version** (smoke test, R2).
  - Endpoint decision recorded: **catalog writes use the direct (unpooled) endpoint** (DuckLake commits are
    multi-statement transactions; transaction-mode pooling can break session semantics -- advisory locks,
    prepared statements); the pooled endpoint is used only if proven transaction-safe, else read-paths only.
  - **Connection-churn gate (hard):** the smoke test measures per-invocation connection-establishment
    overhead AND OCC-collision rate under a simulated concurrent-writer burst on the direct endpoint, against
    a scale-to-zero Neon compute. Pass requires **direct-endpoint churn + commit latency within CD.33's
    OCC-retry/backoff budget, OR an app-side connection pool (or a write-safe Neon pooler) implemented**. This
    is the replacement for the removed RDS Proxy (the OQ.8 connection-churn mitigation), not a deferred
    "consider".
  - **Schema reproducibility:** the out-of-band `ducklake_ops` schema-creation DDL (created out-of-band on
    RDS at VP-6, not in version control) is captured as a versioned migration/DDL file in-repo, so the Neon
    `ducklake_ops` database creation here -- and any fresh-provision rollback -- is reproducible, not tribal.
  - Neon DSN in Secrets Manager; runtime-fetch validated (Decision 37 pattern); a rotation cadence defined
    (quarterly, calendar-reminded -- matching the repo's Tier-1/Anthropic secret-rotation cadence) since the
    Neon static password does not auto-rotate like the RDS-managed secret did.
  - **Tested restore (DR proof, before production write):** a `pg_dump` of the freshly-provisioned Neon
    catalog, taken with a single consistent snapshot (`pg_dump --serializable-deferrable` or a single-txn
    dump), tagged with the pinned DuckLake/DuckDB version, restored into a scratch Neon project, and a DuckDB
    `ATTACH` read-your-write verified against it.
  - RDS retired: pre-destroy check that no snapshot named `ducklake-catalog-final-snapshot` already exists
    (else rename/timestamp the identifier); `deletion_protection=false` then destroy; **final snapshot
    retained as the sole RDS recovery artifact** (no automated PITR survives -- `delete_automated_backups=true`);
    `rds_ducklake_catalog.tf` deleted. Terraform apply human-gated (Decision 35); the destroy trips the
    Decision-77 fail-closed guard -> manual `agent_platform_admin` apply. Partial-failure rollback: if the
    destroy aborts mid-apply, re-enable `deletion_protection`.
  - rec disposition: closes rec-2062/2068/2069 by file deletion; **rec-2063's RDS-side action is explicitly
    dispositioned** (not just "transferred") -- its recommendation to flip `delete_automated_backups=false`
    before cutover is **accepted-as-WONTFIX for this retirement** because the catalog is provably unused at
    T2.16b (no ops data has been written; live ops are still Iceberg/Athena), so single-final-snapshot
    recovery loses nothing; the flip applies only if retirement is ever deferred past the T2.19 cutover. Its
    durability *concept* is carried by the Neon 6h-PITR + daily-dump posture. **rec-2064** (engine-minor
    drift) is dispositioned by noting the catalog backup is a logical `pg_dump`, which tolerates Neon
    Postgres-minor drift on restore (unlike a physical RDS snapshot) -- one more reason the logical dump is
    the right DR primitive on a vendor-managed-minor backend. **rec-2067** (egress least-privilege) re-files
    against the public-endpoint posture (R3). **rec-2065/2066** close when the RDS IAM policy is removed.
- **effort:** S-M. **related_candidate_decisions:** `[CD.34]`.

### 4.3 AMEND T2.17 -- drop VPC-attach; pooler choice conditional

| Element | Before (current) | After (proposed) | Why |
|---------|------------------|------------------|-----|
| `name` | "DuckLake Lambda runtime -- **VPC attach** + extension layer + version pin" | "DuckLake Lambda runtime -- extension layer + version pin" | Neon is a public TLS endpoint; no VPC attach to reach it |
| `intent` | "VPC-attached execution so they can reach the **RDS catalog**...VPC egress blocks extensions.duckdb.org, so extensions must be pre-baked" | "...reach the **Neon catalog** over TLS (no VPC attach for catalog reachability). Extensions remain pre-baked for reproducibility + cold-start determinism." | Removes VPC-attach; pre-bake justification shifts from "egress blocked" to "deterministic/reproducible" |
| exit: ATTACH | "VPC-attached and able to reach **RDS catalog**; ATTACH succeeds in Lambda" | "Able to reach the **Neon catalog** over TLS; ATTACH succeeds in Lambda (SNI + sslmode=require verified on the pinned DuckDB)" | vendor + transport correction |
| exit: pooling | "**RDS Proxy** fronts the catalog connection pool for writer/reader (CD.33 T2-e/O-5)" | "Connection pooling resolved per the **T2.16b connection-churn gate (4.2)**: **Neon's built-in pooler if proven transaction-safe, else the direct endpoint** for catalog writes (no separate RDS Proxy), with an app-side pool implemented if direct-endpoint churn exceeds CD.33's OCC budget. NOT a deferred 'consider' (CD.33 T2-e/O-5 as amended by CD.34)." | Makes the pooler choice *conditional on the smoke test* and the churn mitigation a hard gate, not a banked $10-12 saving |
| exit: inlining (`:3323`) | "Inlining disabled: `ducklake_default_data_inlining_row_limit=0` honoured..." (scoped by clause-5 "governance tables") | "Inlining disabled for **ALL tables including telemetry** (`...=0`) honoured on the pinned DuckLake version (CD.34); high-write-rate tables get a higher-frequency merge (4.4)" | lands the inlining-everywhere override where T2.17 enforces it |
| exit: break-glass | "PlatformAdmin break-glass: granted catalog (**RDS**) + S3 read" | "PlatformAdmin break-glass: granted the **Neon catalog credential (Secrets Manager) + S3 read**" | break-glass reads Neon, not an RDS/IAM grant |
| `related_candidate_decisions` | `[CD.31, CD.10, CD.33]` | add `CD.34` | trace |

Also (architect M3): de-VPC-ing moves the **S3 Parquet data-plane** from a potential gateway-endpoint/private
path to the public S3 API path -- acceptable for the sandbox PLATFORM env; flagged for SIT/PROD future-state.

### 4.4 AMEND T2.18 -- catalog DR mechanism (explicit schedule + retention)

| Before | After | Why |
|--------|-------|-----|
| "Catalog DR: daily **PITR/snapshot export of the RDS catalog** to a dedicated versioned S3 bucket (CD.33 O-2)" | "Catalog DR: a **daily `pg_dump` of the Neon catalog** (single consistent snapshot via `--serializable-deferrable`/single-txn; tagged with the pinned DuckLake/DuckDB version) to a dedicated, versioned, lifecycle-managed S3 bucket. **Schedule:** EventBridge `cron(0 3 * * ? *)` (daily 03:00 UTC). **Retention:** 30-day S3 lifecycle expiration (+ noncurrent-version expiry; repo convention; tunable to 7). **Freshness alarm:** a CloudWatch alarm pages if no new dump object lands in >25h (a silently-failed daily dump widens RPO from ~24h to 48h+). **Version drift:** on any DuckLake/DuckDB bump (OQ.12), re-baseline the retention window (oldest valid-restore dump = first on the new engine) or include the intermediate-upgrade path in the restore runbook. (CD.33 O-2 as amended by CD.34.)" | Neon has no RDS snapshot API; `pg_dump` is the export primitive. **More important on Neon** -- free-tier PITR is ~6h, so the daily S3 dump is the real DR floor beyond 6h |
| inlining exit (`:3348`) | "Inlining DISABLED **for governance tables** (OQ.11 -> c: `...=0`)..." | "Inlining DISABLED for **ALL tables including telemetry** (`...=0`; CD.34)" | lands the inlining-everywhere override where T2.18 enforces it |
| maintenance cadences | (the maintenance *cadences* -- daily `merge_adjacent_files`; weekly guarded GC; `expire` 30d history / 7d current) | **cadences unchanged** -- but note these figures are sourced from CD.33 `enforcement_mechanism` (`:1379`) + this T2.18 exit (`:3353`), NOT clause (5). The backend swap does not touch the GC/merge *schedule*; however the clause-(5) telemetry-inlining carve-out IS overridden (4.6/4.1) -- "cadences verbatim" is NOT "clause 5 verbatim" | corrects the v2 mis-attribution; separates schedule (unchanged) from the carve-out (overridden) |
| telemetry small-file load (NEW exit) | (n/a) | "High-write-rate tables (telemetry) that previously relied on inlining now emit standalone small files; a **higher-frequency `merge_adjacent_files` cadence** is applied to them (or the inter-merge file accumulation is sized and the daily cadence justified), so disabling inlining does not degrade reads / inflate catalog metadata-row count (CD.34)" | sizes the consequence of the disable-everywhere decision |
| `related_candidate_decisions: [CD.31, CD.29, CD.33]` | add `CD.34` | trace |

### 4.5 AMEND T2.19 -- catalog rebuild source + break-glass

| Before | After | Why |
|--------|-------|-----|
| "Catalog DR restore drilled: a catalog rebuilt from the daily S3 **PITR export** passes read-your-write before T2.19 sign-off" | "...rebuilt from the daily S3 **`pg_dump`** (version-matched to the pinned engine) passes read-your-write before cutover sign-off (re-drills the T2.16b proof against production-shaped data)" | matches 4.4 mechanism; the *first* tested restore is a T2.16b precondition, this is the cutover re-drill |
| "...audited PlatformAdmin break-glass path" (catalog read = RDS) | break-glass catalog read = **Neon credential via Secrets Manager** | matches 4.3 |
| churn re-drill (NEW exit) | (n/a) | "Connection-churn / OCC-commit-latency headroom **re-validated against production-shaped concurrency** at cutover (CD.34) -- the T2.16b gate proved it on an empty catalog under a synthetic burst; this mirrors the DR re-drill so the live write path's churn/OCC headroom is confirmed with real data volumes" | confirms the churn gate at cutover, not only pre-data |
| `related_candidate_decisions: [CD.31, CD.33]` | add `CD.34` | trace |

### 4.6 AMEND CD.33 (pending) -- two RDS-reference edits + one clause-(5) carve-out override + one discipline point

CD.33 is `state: pending`, so amending is governance-clean. The two RDS *references* in the CD.33 body are
clause (3) + `enforcement_mechanism` (v2 correction: v1 fabricated a "clause (6)" edit and mis-modelled
O-2/O-5/T2-e as CD.33 sub-clauses -- those labels live only in the T2.17-T2.19 exit criteria, handled in
4.3-4.5). **In addition (v3), the inlining-everywhere decision overrides the telemetry-inlining carve-out
that lives in clause (5) (`:1346`)** -- so clause (5) IS edited, but only that carve-out clause; the
maintenance *architecture* (writer/reader/maintenance split, OCC retry, `current` projection, SCD2 keys, and
the GC/merge *cadences*) is unchanged. The "runtime architecture unchanged" claim is therefore scoped to
those, NOT to the clause-(5) carve-out:

| CD.33 location | Before (verbatim) | After |
|----------------|-------------------|-------|
| clause (3) (`:1333`) | "...snapshot committed in the **RDS catalog txn**; readers see nothing until commit..." | "...snapshot committed in the **catalog txn** (Neon Postgres per CD.34); readers see nothing until commit..." |
| **clause (5) (`:1346`)** | "...governance tables ... **Per-table: telemetry MAY keep inlining.** expire != delete..." | "...governance tables ... **inlining is disabled for ALL tables including telemetry per CD.34 (the telemetry carve-out is removed); high-write-rate tables get a higher-frequency merge.** expire != delete..." |
| `enforcement_mechanism` (`:1379`) | "...PlatformAdmin break-glass (**catalog+S3 read**) + **daily catalog PITR-to-S3**; partition-prune smoke test..." | "...PlatformAdmin break-glass (**Neon catalog credential + S3 read**) + **daily catalog pg_dump-to-S3 (30-day retention) + freshness alarm; Neon built-in pooler (no RDS Proxy)**; partition-prune smoke test..." |
| `discipline_points` (ADD) | (none on backend) | "Catalog backend = Neon serverless Postgres per CD.34 (narrowly amends the CD.31 backend paragraph). Consequential mechanics: inlining disabled for ALL tables (overrides the clause-(5) + OQ.11 telemetry carve-out -- a durability decision, not an architecture change); O-2 DR = daily pg_dump-to-S3 with freshness alarm; O-5 pooling = Neon built-in pooler / direct endpoint for catalog writes, app-side pool if churn exceeds OCC budget. The writer/reader/maintenance split, OCC, current projection, SCD2 keys, and GC/merge cadences are unchanged." |

### 4.7 AMEND OQ.7 / OQ.8 / OQ.9 / OQ.11 / OQ.14 (annotate)

- **OQ.7** (`:3957-3958`): the "Resolved direction" carries RDS-specific recovery text ("expanded to
  catalog+S3 read", "daily PITR export"). Append a "Re-resolved (CD.34): break-glass = Neon credential +
  S3 read; catalog DR = daily pg_dump to a dedicated versioned S3 bucket (30-day retention)."
- **OQ.8** ("RDS catalog backend -- sizing, RDS Proxy, credential", resolved T2.16): append "Re-resolved
  (CD.34): backend = Neon serverless Postgres; RDS Proxy -> Neon's built-in pooler (direct endpoint for
  catalog writes); credential = Secrets Manager DSN. The 'IAM-auth-preferred' note is moot (IAM DB auth N/A
  against a non-AWS endpoint)."
- **OQ.9** ("Catalog durability, DR, SPOF", resolved T2.16): append "Re-resolved (CD.34): DR baseline = Neon
  PITR (~6h free tier) **plus a mandatory daily `pg_dump` to a versioned S3 bucket (30-day retention)** --
  the S3 dump is the recovery floor beyond 6h and the only artifact if the whole Neon project is lost.
  Catastrophic-case RPO ~24h (daily cadence); intra-6h recovery via Neon PITR. SPOF property unchanged; the
  mitigation is the independent backup, not the provider."
- **OQ.11** (`:4002-4018`; the carve-out being superseded is at `:4017`): append "Re-resolved (CD.34): on
  Neon, inlining is **disabled for ALL tables** (`inlined_rows=0`), superseding the per-table telemetry
  carve-out (`:4017`) -- every write lands in S3 immediately, so no table is catalog-only-durable behind
  Neon's 6h free-tier PITR. The durability premise shifts from RDS-PITR to Neon-PITR + daily pg_dump-to-S3.
  High-write-rate tables get a higher-frequency merge to absorb the small-file load (4.4)."
- **OQ.14** (catalog multi-tenancy, FP-C): re-map the option wording from RDS terms ("shared ops-RDS-schema
  vs dedicated instance") to Neon primitives ("shared Neon project + separate databases" / "separate Neon
  projects per env"; Neon branching fits per-env catalogs). Question stays open; only wording updates.

### 4.8 AMEND cost model (line 176; + one flagged adjacency)

| Before | After |
|--------|-------|
| `rds_ducklake_catalog: "~$12-15/mo ... +$10-12 if RDS Proxy added..."` | `ducklake_catalog_neon: "$0 (Neon serverless Postgres free tier; scale-to-zero; built-in pooler -- no RDS Proxy). Replaces the retired RDS catalog per CD.34. Realized saving vs the prior ~$12-15/mo RDS line; the deferrable RDS-Proxy ~$10-12 is an additional conditional saving. Daily pg_dump to S3 is a negligible add-on."` |

**Flagged adjacency (out of scope for this PR; file as a rec):** `dominant_cost: EC2 self-hosted runner
(~$35/mo)` and `ec2_runner_24_7: "~$35"` (`:166`,`:171`) are stale -- CD.21 retired that runner. The
executive-summary "largest live line" claim depends on the runner being gone, so the same PR SHOULD at
minimum correct those two fields (or this report files the freshness rec); leaving them while relying on
their corrected value is inconsistent. The full cost-model freshness pass remains a separate rec.

### 4.9 NEW: non-destructive `[Amendment -- CD.34]` annotation on the CD.31 record

The CD.31 record still reads "metadata-in-RDS-PostgreSQL" (`:1170`), "a dedicated micro RDS PostgreSQL
instance" (`:1176`), "the always-on RDS instance contradicts no existing decision" (`:1182`), and the
discipline-point "The RDS catalog is a metadata store" (`:1246`). Rather than rewrite ratified text, add a
non-destructive `[Amendment -- CD.34]` discipline-point on the CD.31 record pointing to CD.34 -- mirroring
how CD.31 itself annotated CD.8/CD.9/CD.15 in-place with `[Amendment -- CD.31]` blocks (`:354,:363,:497`).
Additive, governance-clean, keeps the roadmap self-consistent.

---

## 5. Auth model: Lambda -> Neon via Secrets Manager

- **Secret:** the Neon DSN (host `ep-*.<region>.aws.neon.tech`, db, user, password) in a Secrets Manager
  secret; the Neon API key (for the Terraform provider) in a separate secret. Reuses the **Decision 37**
  "secret in Secrets Manager, Lambda runtime-fetch" precedent. **Rotation regression (noted):** the Neon
  role password does NOT auto-rotate like today's RDS-managed master secret (`manage_master_user_password
  = true`); define a quarterly calendar-reminded rotation (repo convention) or wire Secrets Manager rotation
  against the Neon API.
- **Connection:** DuckDB's `postgres`/`ducklake` extension `ATTACH` takes a libpq DSN/URI. Neon requires TLS
  (`sslmode=require`) and **SNI**. Recent libpq (bundled by DuckDB) sends SNI; the pinned DuckDB version is
  smoke-tested, with the endpoint-ID parameter as the documented fallback. Catalog writes use the **direct
  endpoint** (multi-statement DuckLake transactions vs PgBouncer transaction-mode pooling).
- **Network:** Neon is reached over the public internet on TLS, so the DuckLake Lambdas **no longer need VPC
  attach for catalog reachability**. **Trade-off (section 6 R3):** we lose SG/VPC network privacy and rely
  on TLS + Neon IP allow-listing + a scoped role. Note the S3 data-plane also moves to the public S3 API
  path when the Lambdas leave the VPC (4.3).

---

## 6. Risks and mitigations

| # | Risk | Severity | Mitigation (where it lands) |
|---|------|----------|------------------------------|
| R1 | Catalog is the lakehouse SPOF; Neon free-tier PITR is only ~6h | **High** | Inlining disabled for ALL tables (4.1/4.6) so nothing is catalog-only-durable; **mandatory daily `pg_dump` (consistent snapshot, engine-version-tagged) -> versioned S3, 30-day retention, + a >25h freshness alarm** (a silently-failed dump is the dominant DR risk); **tested restore as a T2.16b precondition** (not deferred to cutover). Catastrophic-case RPO ~24h (accepted); intra-6h recovery via Neon PITR. Gates T2.16b/T2.18/T2.19. |
| R2 | DuckDB<->Neon connection compat: SNI on the pinned DuckDB; PgBouncer transaction-mode pooler may break catalog session semantics; **direct-endpoint default reintroduces the OQ.8 Lambda connection-churn -> OCC-collision risk** | **High** | T2.16b smoke test on the pinned DuckDB: verify ATTACH + a DuckLake write/commit on direct AND pooled endpoints; **default catalog writes to the direct endpoint**. **Hard churn gate (4.2):** the smoke test measures connection-establishment overhead + OCC-collision rate under a concurrent-writer burst; pass requires churn+commit-latency within CD.33's OCC budget OR an app-side pool implemented -- the churn mitigation that replaces RDS Proxy, NOT a deferred "consider". |
| R3 | Public TLS endpoint replaces SG/VPC network privacy for irreplaceable governance metadata | Medium | `sslmode=require`; scoped Neon role (not owner); secret in Secrets Manager; break-glass via Secrets Manager not a standing grant. **Honest caveat:** Neon IP allow-listing needs a stable source IP -- but dropping VPC-attach removes a static egress IP, so the allow-list is only effective if a static egress is arranged; otherwise R3 rests on TLS + scoped-role + secret. Do NOT lean on "sandbox => acceptable": sandbox denotes money-not-real, not data-disposable. |
| R4 | Free tier on an acquired vendor (Databricks) for irreplaceable data | Medium | The independent S3 `pg_dump` (R1) makes us provider-independent; migration is reversible (section 7). **Neon inactivity (researched):** compute scale-to-zero (auto-resume); branches >14d-old + >24h-idle auto-archive to cold storage (auto-unarchive on access, minor first-touch latency); **no project pause/delete for inactivity** -- strictly better than Supabase's ~1-week project pause. **Reevaluation trigger + owner:** the catalog owner re-evaluates if Neon changes free-tier terms or introduces project-inactivity deletion; add this as a roadmap `reevaluation_trigger`. |
| R5 | IaC governance: Decision-77 auto-apply guard covers AWS resources, not a third-party Neon provider | Medium | **Decided (human): Terraform Neon provider**, in `terraform/personal/`, **explicitly carved out of auto-apply (human-gated apply)** -- keeps declarative state/audit/review for the critical dependency (vs console-only). The Neon API key lives in Secrets Manager. |
| R6 | Cold-start (~300-500ms) on the catalog critical path; branch-archive resume for >24h-idle catalog; interaction with OCC commit latency | Low | Acceptable for intermittent ops/telemetry; pin the Neon region nearest `eu-west-2`. Extend the T2.16b smoke test to measure **commit latency including cold-resume** and confirm it sits inside CD.33's OCC-retry/backoff budget. The trading hot-path does NOT use this catalog (DynamoDB + Iceberg per D.fast/D.lake), so latency-sensitive paths are unaffected. |
| R7 | Disabling telemetry inlining (the all-tables decision) shifts small-file load onto compaction -- telemetry was originally carved out for this reason | Low-Med | High-write-rate tables get a **higher-frequency `merge_adjacent_files` cadence** (or the inter-merge file accumulation is sized and daily cadence justified) at T2.18 (4.4). Net catalog-row count stays bounded because inlining-off means rows land as S3 data files, not catalog-inlined rows. Honours the disable-everywhere decision rather than reopening it. **T2.18 must co-tune the guarded-GC circuit breaker:** a higher merge frequency raises the superseded dead-file rate per GC window, which could trip CD.33's `>20%-files` breaker into a false-positive abort+page -- so the breaker threshold / GC cadence is sized for the new dead-file rate (a `>10GB` breaker is S3-data, not Neon-catalog, so free-tier sizing is unaffected). |

---

## 7. Rollback / reversibility

Reversible, and the blast radius **right now is zero** (nothing consumes the catalog):

- **Retirement leaves a final snapshot, but it is the SOLE RDS recovery artifact.** `rds_ducklake_catalog.tf`
  has `skip_final_snapshot = false` + `final_snapshot_identifier = "ducklake-catalog-final-snapshot"`, so
  destroy produces a final snapshot. **But `delete_automated_backups = true` wipes the automated PITR
  backups on destroy** -- so after retirement there is NO PITR fallback; the single final snapshot is the
  only restore point. (This is exactly the concern standing rec-2063 raises; this report does NOT cite
  rec-2063 as *support* for rollback-safety -- it is a warning.) **rec-2063's RDS-side action
  dispositioned (v3):** its recommendation to flip `delete_automated_backups=false` before cutover is
  **accepted-as-WONTFIX for this retirement** because the catalog is provably unused at T2.16b -- there is no
  ops data to lose, so single-snapshot recovery is sufficient. The flip becomes mandatory only if RDS
  retirement is ever deferred past the T2.19 cutover (when real data lives in the catalog).
- **Destroy-time failure mode:** RDS rejects the destroy if a snapshot named `ducklake-catalog-final-snapshot`
  already exists. T2.16b adds a pre-destroy existence check (or timestamps the identifier) and, if the
  two-step destroy aborts mid-apply (e.g. after `deletion_protection` is flipped off), re-enables
  `deletion_protection` to avoid a live-but-unprotected DB.
- **Rollback path:** restore `ducklake-catalog-final-snapshot` into a new `aws_db_instance` (re-add the
  `.tf`), repoint the Secrets Manager secret. The snapshot carries the out-of-band `ducklake_ops` schema, so
  no re-creation is needed; a **fresh-provision** rollback re-creates the schema from the **versioned
  `ducklake_ops` DDL now captured in-repo at T2.16b** (4.2) -- previously this DDL was out-of-band and
  unreproducible. Note the snapshot ages -- a point-in-time artifact, fine while the catalog is unused but
  not a substitute for the Neon S3 dumps once data lands. (The Neon-side backup is a logical `pg_dump`, which
  tolerates Neon Postgres-minor drift on restore -- unlike a physical RDS snapshot -- so a managed-minor bump
  does not break recovery.)
- **Deliberate destroy.** `deletion_protection = true` forces the two-step retire, human-gated under
  `agent_platform_admin` (Decision 35); the destroy trips the Decision-77 guard's fail-closed gate (no
  auto-apply).

---

## 8. Alternatives considered (brief)

| Option | $/mo (free/idle) | DuckLake catalog fit | Verdict |
|--------|------------------|----------------------|---------|
| **Neon serverless Postgres** (proposed) | $0 free | PG14+; OCC/concurrent-writer OK; built-in pooler; DuckLake-on-Neon documented; no project-inactivity pause | **Recommended** |
| Aurora Serverless v2 (provisioned Postgres-compatible) | not free; scale-to-zero added 2024 but bills per ACU-hour + storage (~$40+/mo realistic); ~15s resume | Strong (full Postgres) | Rejected -- not free; this is the *cost* lever. (Distinct from Aurora DSQL, which CD.31 already dropped as unvalidated against DuckLake's catalog contract.) |
| Supabase (managed Postgres) | $0 free | Full Postgres; OK | Viable but free tier **pauses the whole project after ~1 week idle** (manual restore) -- worse availability than Neon's branch-archive-with-auto-unarchive for an intermittent catalog |
| DuckDB/SQLite catalog **file on S3** | $0 (S3 only) | **Breaks CD.33** -- a file catalog has no transactional multi-writer / OCC coordination | Rejected -- incompatible with the just-ratified concurrent-writer + OCC runtime (CD.33 clause 2). Cheapest, but architecturally regressive. (This is what `ducklake_spike.py` uses, which is why the in-repo spike is not evidence for the Postgres path -- section 3.) |

---

## 9. Decisions this report must cite

| Decision | Relationship |
|----------|--------------|
| **Decision 78 / CD.31** | The decision being narrowly amended (catalog-backend paragraph). Revisited, not overturned; CD.34 preserves all else; CD.31 record gets a non-destructive `[Amendment -- CD.34]` annotation (4.9). |
| **Decision 35 + Decision 77** | RDS retirement is a Terraform destroy -> human-gated; trips the fail-closed auto-apply guard onto the manual admin path. The Neon TF provider is likewise carved out of auto-apply. |
| **Decision 37** | Precedent for the "secret in Secrets Manager, Lambda runtime-fetch" auth model reused for the Neon DSN. |
| **CD.21** | EC2 runner retired -- the cost baseline that makes the RDS the largest live line (and the stale `dominant_cost` field, 4.8). |
| **CD.33 / Decision 81 (pending)** | Related; this report makes only consequential backend amendments (clause 3 + `enforcement_mechanism` + one discipline point) and does not reopen its runtime architecture. |
| **NS.1 / NS.3** | The "small managed cloud state-store" framing that already justifies a managed Postgres catalog; Neon fits it. |

---

## 10. Recommendation and sequencing

**Conditional GO.** Proceed, gated on two T2.16b preconditions:
1. **R2 smoke test passes** -- DuckDB (pinned version) ATTACHes and commits a DuckLake transaction against
   the Neon direct endpoint (and the pooled endpoint is either proven transaction-safe or relegated to reads).
2. **Tested backup/restore proven** -- a consistent, engine-version-tagged `pg_dump` restores into a scratch
   Neon project and passes a DuckDB read-your-write, BEFORE the RDS is destroyed and BEFORE any production
   write.

**Sequencing:**
```
CD.34 (decide, pending -> Decision 82)
  -> T2.16b  (Terraform-provision Neon + Secrets Manager DSN + smoke test [R2 + connection-churn gate] + captured ducklake_ops DDL + tested restore + retire RDS w/ final snapshot)
    -> T2.17 (Lambda runtime against Neon: no VPC attach, direct endpoint, Secrets Manager DSN, inlining=0 all tables)
      -> T2.18 (GC/merge cadences [unchanged] + higher-freq merge for telemetry + daily pg_dump-to-S3 DR, 30-day retention + freshness alarm)
        -> T2.19 (write/read cutover; restore re-drill from pg_dump before sign-off)
```
Doing CD.34 + T2.16b before T2.17 is the whole point: it prevents building, then tearing down, the
RDS-in-a-VPC + RDS-Proxy plumbing. The DR gates (R1) are sized for the T2.19 total-blast-radius state, not
the zero-blast-radius present.

---

## 11. Sources (Neon facts, researched 2026-06)

- Neon pricing / free-tier limits (100 CU-hours, 0.5 GB, scale-to-zero, PITR 6h/1GB): https://neon.com/pricing , https://neon.com/docs/introduction/plans
- Neon scale-to-zero / cold-resume latency (~300-500ms; sub-100ms pooled): https://neon.com/docs/introduction/scale-to-zero , https://neon.com/docs/connect/connection-latency
- Neon branch archiving (>14d + >24h idle; auto-unarchive; no project-inactivity delete): https://neon.com/docs/guides/branch-archiving
- Neon connection / SNI / pooling (libpq SNI requirement; PgBouncer pooled endpoint): https://neon.com/docs/connect/connection-pooling , https://neon.com/docs/connect/choose-connection
- DuckDB Postgres extension ATTACH (libpq DSN/URI; pooler notes): https://duckdb.org/docs/lts/core_extensions/postgres
- DuckLake-on-Neon working pattern: https://rvernica.github.io/2025/06/ducklake-with-postgres
- Databricks acquisition of Neon (May 2025; free tier retained, CU-hours doubled): https://www.databricks.com/company/newsroom/press-releases/databricks-agrees-acquire-neon-help-developers-deliver-ai-systems
