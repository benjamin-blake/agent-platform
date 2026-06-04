# Plan

## Intent
Formalise the DuckLake ops *runtime* architecture that Decision 78 deliberately deferred to T2.16-T2.19.
Decision 78 adopted DuckLake (ratified CD.31; superseded Decisions 50/51/56/69; preserved the Decision 69
Single-Portal invariant) but left the implementation architecture and four open questions (OQ.7, OQ.10,
OQ.11, OQ.12) for the tier items to settle. This plan persists the settled architecture as a
`state: pending` candidate decision (**CD.33**), resolves OQ.7/OQ.10/OQ.11 in the roadmap's native
structures, enriches tier_items T2.17/T2.18/T2.19, and corrects the now-stale Decision-67 deferral markers
per Decision 79. The formal ratification (**Decision 80**) is drafted here for zero-context review and is
filed via the log-decision path only after approval -- mirroring the CD.31 -> Decision 78 rhythm.

**Revision status (v2):** A first zero-context review pass (decision-scout + distributed-systems
correctness lens + adversarial ops-risk lens) returned findings that overturned two of the original
clauses (inlining, partitioning) and added a major read-path clause (the `current` projection). Those
resolutions, plus the SCD2 grain clarification, are folded into the clauses below and tracked durably in
the **Review-findings ledger**. This v2 draft re-enters the same zero-context review before ratification.
The ledger is the canonical record of what each review raised and how it was resolved -- it exists so the
resolutions survive context compaction and are correctable, not held only in conversation.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1 (roadmap YAML is non-handler config with no runtime effect; Decision 48). The Decision 80 filing is a
log-decision-path write, not a code change.

## Plan Path
docs/plans/PLAN-ducklake-runtime-architecture.md

## Phase
Platform roadmap T2 (full state migration to personal account). Governance ratification of the DuckLake
ops runtime architecture, gating the T2.17 (Lambda runtime), T2.18 (maintenance pipeline), and T2.19
(write/read migration = FP-B) implementation work. T2.16 (RDS catalog) is already complete (2026-06-03).

## Review-findings ledger (reconstructed v1 -> v2)
Canonical, durable record of the first-pass zero-context review and its resolutions. Confidence flags mark
reconstruction certainty (HIGH = worked in detail this session; MED = named in review but detail partly
reconstructed from compacted context -- verify wording before ratification). Status: RESOLVED (folded into
clauses below) / ACCEPT-ENCODE (agreed in principle, to be written into T2.17-T2.19 implementation steps) /
HELD-OPEN (decision pending). Finding IDs (Cn/Hn/Rn) are the review lenses' own labels as reconstructed;
treat them as handles, not a frozen taxonomy.

| ID | Lens | Finding | Status | Resolution | Conf |
|----|------|---------|--------|------------|------|
| C2 | dist-sys | Inlining keeps a catalog-only durability window between flushes; for irreplaceable governance data that is a data-loss exposure backed only by RDS PITR. | RESOLVED | OQ.11 -> **option (c)**: disable inlining (`inlined_rows = 0`) for governance tables -- every write lands in S3 immediately. Per-table policy: high-cardinality telemetry tables MAY keep inlining. (Clause 5.) | HIGH |
| R-4 | dist-sys | "Latest version per id" is unprunable -- a `current` row can live in any partition -- so deriving `current` at read time forces a full-table scan. | RESOLVED | Maintain `current` as a write-through Type-1 projection; dual-write `history` (append) + `current` (MERGE upsert) in **one DuckLake catalog transaction**; reads hit `current`. (Clause 7.) | HIGH |
| H1/R-3 | ops-risk | Maintenance lumps destructive GC (expire/cleanup/delete_orphaned) with non-destructive compaction on one cadence, with no retention floor or circuit breaker. | RESOLVED | Decompose: **daily non-destructive `merge_adjacent_files`** + a **separately-cadenced, guarded destructive GC** (retention floor, `older_than` grace window, circuit breaker, independent alarm). (Clause 5.) | HIGH |
| R-1 | ops-risk | "Two-phase / sequencing" wording implied external orchestration (Step Functions) was needed for cross-table atomicity, and left orphan-Parquet handling vague. | RESOLVED | Single DuckLake catalog-snapshot transaction is atomic across `history`+`current`; no external sequencing. Atomicity is scoped to the **catalog-snapshot commit**; aborted-commit Parquet is GC residue reclaimed by `delete_orphaned_files`. (Clauses 3, 5, 7.) | HIGH |
| -- | user | SCD2 grain was mis-stated as `rec_id`. Engine enforces no PK/FK (BigQuery discipline -- enforced in app + DQ). | RESOLVED | Grain is the composite `(rec_id, last_updated_timestamp)`; `rec_id` is the natural key. Three DQ invariants: (i) grain uniqueness, (ii) one current row per `rec_id` (now **structural** via the `current` MERGE key), (iii) `update_rec` referential-existence check (now a **point-lookup on `current`**). (Clause 8.) | HIGH |
| C1 | dist-sys | Writes that fail the schema gate or exhaust OCC retries must fail **loudly** (surface the error), never silently drop or swallow. | ACCEPT-ENCODE | `ducklake_writer` raises on schema-gate rejection and on OCC-retry exhaustion; no silent drop. Consistent with the CLAUDE.md "never raise at import; raise on explicit calls" rule. To be pinned in T2.17 exit criteria. | MED |
| H2 | ops-risk | The closed boundary (no Athena escape hatch) means a broken reader/writer leaves no way to inspect or repair the warehouse -- no break-glass path for DR. | ACCEPT-ENCODE | Define an **admin-account break-glass** role/path for emergency direct catalog+S3 access (DuckDB attach), audited and alarmed, distinct from the routine closed boundary. To be pinned in T2.19 / DR runbook. | MED |
| T2-a | dist-sys | `day(last_updated_timestamp)` does not prune current-state reads because updates re-stamp the timestamp, scattering an id's versions across partitions. | RESOLVED | `history` partitions by **`day(created_timestamp)`** (stable per rec); `current` partitions/buckets by **`id`**. (Clauses 6, 7.) | HIGH |
| T2-b | dist-sys | OCC-retry description under-specified: needs bounded retries, backoff+jitter, a stable idempotency key across retries, and loud failure on exhaustion. | PARTIAL/HELD | Bounded retry + backoff/jitter + loud-fail: ACCEPT-ENCODE. The stable idempotency key depends on the HELD write-id decision below. (Clause 2.) | MED |
| T2-c | dist-sys | Schema-gate evolution path unspecified (how schema changes roll out vs. the writer validating against current schema). | ACCEPT-ENCODE | Writer validates against the live table schema; schema migration is a maintenance-path DDL step, versioned. To be detailed in T2.17. | MED |
| T2-d | ops-risk | Observability unspecified: no metrics/alarms for OCC-retry rate, commit latency, maintenance outcomes, or durability lag. | ACCEPT-ENCODE | Emit CloudWatch metrics for OCC-retry count/rate, commit latency, per-stage maintenance success, and (if any inlining retained) flush lag; alarm the destructive-GC circuit breaker independently. To be pinned in T2.17/T2.18. | MED |
| T2-e | ops-risk | Lambda concurrency can exhaust the RDS Postgres catalog connection pool. | ACCEPT-ENCODE | Front the catalog with **RDS Proxy** for connection pooling from `ducklake_writer`/`ducklake_reader`. To be pinned in T2.17. | MED |
| T3-a | decision-scout | CD.10 supersession should be machine-readable (structured), not only prose. | ACCEPT-ENCODE | Encode the supersession in CD.33's structured `supersedes`/`discipline_points` fields, not just narrative. (CD.33 YAML below.) | MED |
| T3-b | decision-scout | Lambda manifest paths referenced must match actual `src/lambdas/<slug>/manifest.yaml` locations. | ACCEPT-ENCODE | Verify the three artifact slugs against the manifest registry before tier-item edits land. | MED |
| T3-c | decision-scout | OQ annotation wording must be precise about "resolved direction vs. stays open until implemented". | RESOLVED | OQ annotations below use the established "Resolved direction (CD.33, pending Decision 80) ... Enacted at Tn" pattern. | HIGH |
| **HELD** | user+dist-sys | **Write-id tiebreaker.** `_prepare_record` re-stamps `last_updated_timestamp = now()` on every attempt. That breaks (a) grain uniqueness under coarse clock resolution, (b) OCC-safe retries, and (c) append idempotency -- all three want **one write identifier minted once at operation start and reused across retries**. Options: high-precision timestamp held stable, or a monotonic per-rec version counter as the true grain tiebreaker. | HELD-OPEN | **DECISION PENDING** -- load-bearing for clause 2 (idempotency key), clause 7 (append idempotency), and clause 8 (grain uniqueness). Do not ratify these clauses' idempotency wording until resolved. | HIGH |

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add `state: pending` candidate_decision **CD.33** ("DuckLake ops runtime architecture"); annotate **OQ.7 / OQ.10 / OQ.11** with resolved directions citing CD.33 (questions stay open until the implementing tier item lands, per the established OQ-stays-open-until-implemented pattern); enrich **tier_items T2.17 / T2.18 / T2.19** (add CD.33 to `related_candidate_decisions`; pin the split, schema gate, OCC-retry, closed boundary, `current` projection, partition split, guarded GC, partition-prune smoke test); correct the stale `DEFERRED ... pending Decision 67 / CD.16 reversal` exit-criteria lines in T2.17/T2.18/T2.19 to active per-Lambda build/deploy/smoke-test steps per Decision 79 (CD.16 ratified). |
| `docs/DECISIONS.md` | Modify (ratification step only) | Append **Decision 80** ratifying CD.33 and resolving OQ.7/OQ.10/OQ.11. **Drafted below for review; applied only after approval**, alongside `ops_data_portal.file_decision` to allocate the `dec-XXXX` warehouse id. |

## Bundled Recommendations
None.

## Settled architecture (the eight clauses CD.33 / Decision 80 encode)
1. **Three-artifact runtime split by access pattern** -- `ducklake_writer`, `ducklake_reader`,
   `ducklake_maintenance` -- justified by IAM-principal isolation (a write-scoped role vs a read-scoped
   role vs a maintenance role), independent scaling, and independent deploy/blast-radius, **NOT** by
   concurrency control (DuckLake's OCC handles that). This **supersedes CD.10's six-Lambda enumeration**
   (`log_rec`/`update_rec`/`log_decision`/`query`/`list_tools`/`maintenance`). CRITICAL framing: CD.10's
   six were *illustrative examples of needed verbs*, never a canonical surface. CD.33 commits **only** to
   the access-pattern split and the closed read/write boundary -- the verb/tool set behind `writer` and
   `reader` is deliberately **left extensible**. The architectural invariant is *path*, not *verb count*.
2. **Concurrency (resolves OQ.10 -> option c).** Concurrent writer invocations are allowed; the writer
   handles DuckLake snapshot-id conflicts via **bounded application-level OCC retry** (backoff + jitter,
   fixed retry ceiling), safe because ops writes are idempotent SCD2 appends keyed by id. On retry
   exhaustion the writer **fails loudly** (raises; no silent drop -- finding C1). The retry's idempotency
   key MUST be stable across attempts (see the **HELD write-id decision** in the ledger -- this is the
   single identifier that also serves clause 7 append-idempotency and clause 8 grain uniqueness; the
   current `_prepare_record` `now()` re-stamp is incompatible and must move out of the retry loop). No
   reserved-concurrency=1 and no SQS FIFO -- those serialise unnecessarily. `ducklake_maintenance` runs as
   a **singleton** (no overlapping maintenance runs; DDL / `ALTER`-table maintenance ops hard-abort on
   conflict, so they must not race).
3. **Portal surface = read + write categories only; sync eliminated.** DuckLake's atomic catalog-commit
   removes the JSONL outbox + drain/`sync` step entirely. A write is atomic **at the catalog-snapshot
   commit**: the writer stages Parquet to S3, then commits the snapshot in the RDS catalog transaction;
   readers never see the data until that commit lands, and Parquet files orphaned by an aborted commit are
   reclaimed by `delete_orphaned_files` (clause 5). Atomicity is scoped to the catalog snapshot, not to the
   filesystem -- there is no external sequencing/Step Functions (finding R-1). The portal keeps its logical
   write verbs (`file_rec`, `update_rec`, `file_decision`) and read verb (`query`) -- "read + write only"
   means the *sync category* is gone, not that the verbs collapse to two functions. Structurally modelled
   on the recommendations portal. **Preserves the Decision 69 Single-Portal invariant**: all writes still
   transit `scripts/ops_data_portal.py`; only the transport beneath it changes (outbox -> DuckLake writer).
4. **Writer owns the schema-enforcement gate.** Every write is validated against the live target-table
   schema before the catalog commit; the writer is the single write chokepoint, with no bypass. Schema
   rejections fail loudly (finding C1). Schema evolution is a versioned maintenance-path DDL step, not a
   writer-side silent coercion (finding T2-c).
5. **Maintenance = two deterministic scheduled cadences, not one pipeline, and not an agent surface**
   (resolves OQ.11 -> **option c**, and findings C2 / H1 / R-3). With inlining disabled (clause, below)
   `flush_inlined_data` is a no-op safety net at most. The remaining work splits by destructiveness:
   - **Daily, non-destructive:** `merge_adjacent_files` compacts the small Parquet files that immediate-S3
     writes produce. Self-correcting: a missed run is caught up by the next (it simply compacts the
     accumulated small files). `current` (high-churn upsert) is compacted on its own, more frequent cadence.
   - **Separately-cadenced, guarded, destructive GC:** `expire_snapshots -> cleanup_old_files ->
     delete_orphaned_files`. Each runs behind a **retention floor**, an `older_than` grace window, and a
     **circuit breaker** (abort + alarm if it would delete more than a threshold), on a slower cadence with
     its own alarm. `expire_snapshots` does NOT delete S3 objects -- `cleanup_old_files` +
     `delete_orphaned_files` must also run or S3 grows unboundedly. No LLM and no agent invocation anywhere.

   **Inlining (OQ.11 -> c):** governance tables set `inlined_rows = 0` -- every write lands in S3
   immediately, eliminating the catalog-only durability window (finding C2). The cost is many small Parquet
   files, paid down by the daily `merge_adjacent_files`. This is a **per-table** policy: high-cardinality
   telemetry tables MAY keep inlining ON where the small-write rate makes the durability window an
   acceptable trade for fewer S3 round-trips.
6. **Closed read/write boundary (resolves OQ.7 -> option a).** Every read transits `ducklake_reader`;
   every write transits `ducklake_writer`; nothing reaches DuckLake out-of-band. There is **no Athena
   escape hatch** -- DuckLake has no Iceberg export and no external-engine reader, and the closed boundary
   is the point: we control and authorise every read and write. Ad-hoc large scans live behind the reader
   (add reader compute if DuckDB single-node memory binds) rather than via a parallel Iceberg mirror. A
   single **admin-account break-glass** path (audited, alarmed, distinct from the routine boundary) exists
   for DR when the reader/writer are themselves broken (finding H2). **Partitioning** is per-role (finding
   T2-a): `history` partitions by **`day(created_timestamp)`** (stable per rec, so date-filtered reads
   prune); `current` partitions/buckets by **`id`** (so the serving point-lookup and the MERGE match-scan
   both prune). Applied via CD.9 `ALTER TABLE ... SET PARTITIONED BY` **at table creation** (a partition
   only affects writes after the ALTER). A smoke test must prove a date-filtered query **actually prunes
   partitions** (not just parses), gating T2.17/T2.19.
7. **`current` write-through projection (resolves R-4).** Reads come from a materialised `current` table,
   never from a window over `history`. `history` is the append-only source of truth; `current` is a
   derived Type-1 projection (one row per `id`, latest-wins), rebuildable from `history` as DR only (that
   rebuild is the full scan we are avoiding -- never on the read path). Each write is a single DuckLake
   transaction: `INSERT history` (append the new version) then `MERGE current` (upsert from the **in-hand
   delta -- never read back from `history`**), one atomic snapshot. The MERGE is idempotent (latest-wins
   converges on replay); the `history` append is not, so it carries the stable write-id idempotency key
   (HELD decision). The merge logic is a **shared helper** parametrised on `(delta, dest table, key cols,
   order-by)`, imported in-process so it stays inside the transaction, and accepts **one-or-many rows from
   day one** so a future per-write -> sub-second micro-batch switch is a config change, not a rewrite.
   `current` is a warehouse-resident materialisation written transactionally -- it is NOT the `logs/*.jsonl`
   read-cache anti-pattern; the DR rebuild runs through the portal/ETL, never restaged from a local file.
8. **SCD2 grain + DQ invariants (no engine-enforced keys).** DuckLake/Iceberg enforces no PK/FK; enforcement
   is application + DQ (BigQuery discipline). The grain is the composite **`(rec_id, last_updated_timestamp)`**
   -- `rec_id` is the natural/business key, not the physical grain. Everything in the project is SCD2. Three
   DQ invariants: (i) **grain uniqueness** -- no two rows share `(rec_id, last_updated_timestamp)`; (ii)
   **current-version uniqueness** -- at most one current row per `rec_id`, now enforced **structurally** by
   the clause-7 `current` MERGE key rather than as a post-hoc check; (iii) **referential existence** --
   `update_rec` confirms the `rec_id` exists (a cheap point-lookup on `current`), while `file_rec` requires
   the freshly DynamoDB-allocated `rec_id` to NOT exist. Invariant (i) is only sound if the grain's second
   column is unique per `rec_id` per write -- the HELD write-id decision governs this.

OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal gate is the
documented default); CD.33 does not pre-empt it.

## Proposed CD.33 (state: pending) -- exact YAML to insert after CD.32
```yaml
  - id: CD.33
    title: DuckLake ops runtime architecture -- writer/reader/maintenance split, OCC-retry concurrency, current projection, closed read/write boundary
    detail: |
      Pins the ops DuckLake runtime architecture that Decision 78 (CD.31) deferred to T2.17-T2.19.
      Ratified by Decision 80 (this CD does NOT edit DECISIONS.md while pending; ratification lands via
      the log-decision path = Decision 80, mirroring CD.31 -> Decision 78).
      (1) Three-artifact split by access pattern -- ducklake_writer / ducklake_reader / ducklake_maintenance
          -- justified by IAM-principal + scaling + deploy isolation, NOT concurrency. Supersedes CD.10's
          six-Lambda enumeration, which was illustrative (examples of needed verbs), never canonical. CD.33
          commits ONLY to the access-pattern split + closed boundary; the verb/tool set behind writer and
          reader stays deliberately extensible. The invariant is path, not verb count.
      (2) Concurrency (OQ.10 -> c): concurrent writers + bounded application-level OCC retry (backoff+jitter,
          fixed ceiling, loud-fail on exhaustion) in the writer (safe: ops writes are idempotent SCD2 appends
          keyed by id). The retry idempotency key is the stable per-write id (see write-id decision; the
          _prepare_record now() re-stamp moves out of the retry loop). NOT reserved-concurrency=1, NOT SQS
          FIFO. ducklake_maintenance runs as a singleton (DDL/ALTER ops hard-abort on conflict).
      (3) Portal surface = read + write categories only; the sync category is eliminated because DuckLake's
          atomic catalog-snapshot commit removes the outbox/drain step. A write is atomic at the catalog
          commit (Parquet staged to S3, then snapshot committed in the RDS catalog txn; readers see nothing
          until commit; aborted-commit Parquet reclaimed by delete_orphaned_files). No external sequencing.
          Logical write verbs (file_rec/update_rec/file_decision) + read verb (query) retained. Decision 69
          Single-Portal invariant PRESERVED -- all writes transit scripts/ops_data_portal.py; transport only.
      (4) ducklake_writer owns the schema-enforcement gate: every write validated against the live table
          schema before commit; single un-bypassable write chokepoint; schema rejection fails loudly; schema
          evolution is a versioned maintenance DDL step, not writer-side silent coercion.
      (5) ducklake_maintenance = TWO deterministic scheduled cadences, NO LLM / NO agent: (a) daily
          non-destructive merge_adjacent_files (self-correcting compaction; current compacted more often);
          (b) separately-cadenced GUARDED destructive GC (expire_snapshots -> cleanup_old_files ->
          delete_orphaned_files) behind a retention floor + older_than grace + circuit breaker + own alarm.
          OQ.11 -> c: inlining DISABLED (inlined_rows=0) for governance tables -- writes land in S3
          immediately, removing the catalog-only durability window; small files paid down by daily merge.
          Per-table: telemetry MAY keep inlining. expire != delete: cleanup + delete_orphaned must run.
      (6) Closed read/write boundary (OQ.7 -> a): every read via reader, every write via writer, nothing
          out-of-band. No Athena escape hatch (DuckLake has no Iceberg export / external reader; the closed
          boundary is the design goal). One audited+alarmed admin-account break-glass path for DR only.
          Partitioning per-role: history by day(created_timestamp) (stable -> date reads prune); current by
          id (serving lookup + MERGE prune); applied via CD.9 ALTER at table creation. Partition-prune smoke
          test gates T2.17/T2.19.
      (7) current write-through projection (R-4): reads come from a materialised Type-1 current table (one
          row per id, latest-wins), never a read-time window over history. Each write is one DuckLake txn:
          INSERT history then MERGE current from the in-hand delta (no read-back). history is the append-only
          source of truth; current is rebuildable from history (DR only). Shared idempotent merge helper,
          one-or-many rows from day one (micro-batch is a config flip). current is a warehouse table, NOT the
          logs/*.jsonl read-cache anti-pattern.
      (8) SCD2 grain + DQ (no engine PK/FK; BigQuery discipline): grain = composite (rec_id,
          last_updated_timestamp); rec_id is the natural key. DQ invariants: grain uniqueness; one current
          row per rec_id (structural via the current MERGE key); update_rec referential existence (point-
          lookup on current) while file_rec requires the DynamoDB-allocated rec_id to NOT exist. Grain
          uniqueness depends on the stable write-id decision.
      OQ.12 (version/upgrade policy) is left to T2.17 implementation (clone-rehearsal default); not pre-empted.
    gates: [T2.17, T2.18, T2.19]
    state: pending
    filed_via: pending_log_decision_lambda
    supersedes_decisions: []
    discipline_points:
      - "Supersedes CD.10's six-Lambda enumeration; CD.10 is state:pending so no DECISIONS.md transition. The agent verb/tool surface is explicitly NOT frozen by CD.33 -- only the writer/reader/maintenance path split and the closed boundary are."
      - "Preserves Decision 69 Single-Portal primitive-level invariant (portal abstraction unchanged; transport changes)."
      - "Does NOT edit DECISIONS.md while pending; supersession + OQ.7/OQ.10/OQ.11 resolution land at ratification via the log-decision path = Decision 80."
      - "Refines CD.15 (typed query reader) and CD.8 (DuckDB engine) and applies CD.9 partitioning; does not contradict them."
      - "OQ.11 resolves to option (c) (inlining disabled for governance tables), NOT option (b); the v1 draft's option (b) was overturned by the C2 durability-window finding."
      - "Open dependency: the stable write-id decision (grain tiebreaker = OCC idempotency key = append idempotency key) is load-bearing for clauses 2, 7, 8 and must be resolved before those clauses' idempotency wording is ratified."
    enforcement_mechanism: "ducklake_writer schema gate + closed reader/writer boundary; current write-through projection enforces current-version uniqueness; guarded destructive-GC circuit breaker; partition-prune smoke test in T2.17/T2.19 exit criteria; per-Lambda CD.24 manifests."
```

## Proposed OQ annotations (append to the `notes` of each; questions stay open until implemented)
- **OQ.7** -- append: `Resolved direction (CD.33, pending Decision 80): option (a) -- no Athena escape hatch.
  The closed reader/writer boundary is the design goal; ad-hoc scans live behind ducklake_reader (scale reader
  compute if memory binds), not a parallel Iceberg mirror. One audited admin-account break-glass path for DR.
  Enacted at T2.19.`
- **OQ.10** -- append: `Resolved direction (CD.33, pending Decision 80): option (c) -- concurrent writers +
  bounded application-level OCC retry (backoff+jitter, loud-fail on exhaustion) in ducklake_writer (ops writes
  are idempotent SCD2 appends keyed by id); ducklake_maintenance runs as a singleton. NOT reserved-concurrency=1,
  NOT SQS FIFO. Enacted at T2.19.`
- **OQ.11** -- append: `Resolved direction (CD.33, pending Decision 80): option (c) -- inlining DISABLED
  (inlined_rows=0) for governance tables; writes land in S3 immediately (no catalog-only durability window);
  small files compacted by a daily non-destructive merge_adjacent_files, with destructive GC on a separate
  guarded cadence. Per-table: telemetry may retain inlining. Supersedes the v1 option-(b) direction. Enacted at T2.18.`

## Proposed tier-item enrichments
- **T2.17** -- add `CD.33` to `related_candidate_decisions`; add exit criteria
  `"Partition-prune smoke test: a date-filtered query against an ALTER-partitioned history table demonstrably prunes partitions (CD.9 / CD.33)"`,
  `"ducklake_writer fails loudly on schema-gate rejection and OCC-retry exhaustion; no silent drop (CD.33 C1)"`,
  `"RDS Proxy fronts the catalog connection pool for writer/reader (CD.33 T2-e)"`,
  `"OCC-retry + maintenance-singleton + commit-latency metrics emitted to CloudWatch (CD.33 T2-d)"`;
  **replace** the stale `"DEFERRED: build_lambda.py --deploy + smoke-test (pending Decision 67 / CD.16 reversal)"`
  with `"Per-Lambda build + deploy + smoke-test for ducklake_writer and ducklake_reader (V3 tier per CD.16; Decision 67 Lambda-deploy clause lifted by Decision 79)"`.
- **T2.18** -- add `CD.33`; **replace** the inlining note to cite OQ.11 -> c (inlining DISABLED for governance
  tables; daily non-destructive merge); add exit criteria
  `"Maintenance runs as two deterministic singleton cadences (daily non-destructive merge; separately-cadenced guarded destructive GC) with no LLM / agent invocation (CD.33 clause 5)"`,
  `"Destructive GC behind retention floor + older_than grace + circuit breaker + independent alarm (CD.33 H1/R-3)"`;
  **replace** the stale DEFERRED line with the active per-Lambda build/deploy/smoke-test line for `ducklake_maintenance` (per Decision 79).
- **T2.19** -- add `CD.33`; add exit criteria
  `"ducklake_writer owns the schema-enforcement gate; no write path bypasses it (CD.33 clause 4)"`,
  `"Closed boundary verified: every ops read transits ducklake_reader, every write ducklake_writer; no out-of-band DuckLake access; one audited admin break-glass path (CD.33 clause 6 / OQ.7 / H2)"`,
  `"current write-through projection live: reads hit current; each write is one DuckLake txn (INSERT history + MERGE current from in-hand delta); read-your-write verified in smoke test (CD.33 clause 7 / R-4)"`,
  `"SCD2 DQ checks enforce grain uniqueness (rec_id, last_updated_timestamp), current-version uniqueness via current, and update_rec referential existence (CD.33 clause 8)"`,
  and update the OQ.10 exit criterion to name the chosen mechanism (OCC retry + maintenance singleton);
  **replace** the stale DEFERRED line with active per-Lambda build/deploy/smoke-test (per Decision 79).

## Decision 80 -- DRAFT (filed via the log-decision path only after approval)
```markdown
## Decision 80: Ratify the DuckLake ops runtime architecture (CD.33); resolve OQ.7 / OQ.10 / OQ.11 (Decided)

**Status:** Decided
**Date:** 2026-06-04
**Warehouse ID:** dec-XXXX  (allocated by ops_data_portal.file_decision at filing)

**Problem:**
Decision 78 adopted DuckLake for the operational lakehouse but deferred the runtime architecture and four
open questions to T2.16-T2.19. T2.16 (RDS catalog) is complete; T2.17-T2.19 cannot proceed without a
ratified answer to: how the ops Lambdas are decomposed, how writer concurrency is enforced against
DuckLake's OCC (OQ.10), how inlining is flushed and where durability lives (OQ.11), whether an Athena
escape hatch survives DuckLake's lack of an external reader (OQ.7), how current-state reads avoid full
scans, and what the agent-facing portal surface is. CD.10's earlier six-Lambda enumeration was
illustrative, not a settled architecture.

**Decision:**
Ratify CD.33 as the authoritative DuckLake ops runtime architecture:
1. Three-artifact runtime split -- ducklake_writer / ducklake_reader / ducklake_maintenance -- partitioned
   by access pattern for IAM-principal, scaling, and deploy/blast-radius isolation, NOT for concurrency.
2. Supersede CD.10's six-Lambda enumeration. CD.10's verbs were illustrative; this decision commits only
   to the writer/reader/maintenance path split and the closed read/write boundary. The verb/tool surface
   behind writer and reader is deliberately left extensible and is NOT frozen by this decision.
3. Concurrency (OQ.10): concurrent writers + bounded application-level OCC retry (backoff+jitter, fixed
   ceiling, loud-fail on exhaustion) in ducklake_writer (ops writes are idempotent SCD2 appends keyed by
   id). ducklake_maintenance runs as a singleton. Reserved-concurrency=1 and SQS FIFO are rejected as
   over-serialising.
4. Portal surface = read + write categories; the sync category is eliminated because DuckLake's atomic
   catalog-snapshot commit removes the outbox/drain step. Writes are atomic at the catalog commit (no
   external sequencing); aborted commits leave orphan Parquet reclaimed by delete_orphaned_files. The
   Decision 69 Single-Portal invariant is PRESERVED -- all writes transit scripts/ops_data_portal.py; only
   the transport beneath it changes.
5. ducklake_writer owns the schema-enforcement gate -- the single, un-bypassable write chokepoint; schema
   rejection and OCC-retry exhaustion fail loudly.
6. ducklake_maintenance is two deterministic scheduled cadences with no LLM / agent invocation: a daily
   non-destructive merge_adjacent_files (compaction; self-correcting) and a separately-cadenced GUARDED
   destructive GC (expire_snapshots -> cleanup_old_files -> delete_orphaned_files) behind a retention floor,
   older_than grace, and circuit breaker. OQ.11 resolved to option (c): inlining DISABLED (inlined_rows=0)
   for governance tables so writes land in S3 immediately, eliminating the catalog-only durability window;
   per-table, telemetry may retain inlining.
7. Closed read/write boundary. OQ.7 resolved: no Athena escape hatch -- every read via the reader, every
   write via the writer, nothing out-of-band; one audited admin-account break-glass path for DR. History
   partitions by day(created_timestamp), current by id (CD.9 ALTER at creation); a partition-prune smoke
   test gates T2.17/T2.19.
8. current write-through projection: reads come from a materialised Type-1 current table; each write is one
   DuckLake transaction (INSERT history + MERGE current from the in-hand delta). history is the append-only
   source of truth; current is rebuildable from history for DR. SCD2 grain is the composite
   (rec_id, last_updated_timestamp) with no engine-enforced keys; DQ enforces grain uniqueness, current-
   version uniqueness (structural via current), and update_rec referential existence.
9. OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal default), not
   pre-empted here.

**Open dependency:** the stable write-id (grain tiebreaker = OCC idempotency key = append idempotency key)
is resolved at T2.17 implementation; the _prepare_record now() re-stamp moves out of the retry loop. The
ratified clauses stand; only the concrete write-id mechanism (high-precision timestamp vs monotonic version
counter) is deferred to implementation.

**Rationale:**
The split is by access pattern because that is what differs operationally -- a write principal that can
mutate the catalog, a read principal that cannot, and a maintenance principal that runs DDL -- so isolating
them isolates IAM blast radius and deploy risk; concurrency is handled by DuckLake's OCC, not by collapsing
the Lambdas. OCC retry beats reserved-concurrency=1 / SQS FIFO because ops writes are idempotent id-keyed
SCD2 appends, so a conflicted snapshot is safe to retry without serialising the whole write path. Inlining
is disabled for governance tables because the catalog-only durability window is an unacceptable data-loss
exposure for irreplaceable records; the resulting small files are a cheap, self-correcting cost paid down by
daily compaction, while destructive GC is decoupled onto a slower guarded cadence so it can never race a
slow reader or runaway a delete. current is materialised as a write-through Type-1 projection because
"latest per id" is unprunable, so deriving it at read time forces a full scan; a single atomic DuckLake
transaction across history+current keeps them from drifting without external orchestration. The closed
boundary (no Athena escape hatch) is not a limitation we tolerate but the design goal: a lakehouse where
every read and write is mediated and authorised, with one audited break-glass path for DR. The agent verb
surface is left open precisely to avoid re-committing CD.10's mistake of enumerating a "final" surface
prematurely.

**Related:** CD.33 (ratified here), CD.10 (six-Lambda enumeration superseded; was illustrative, state:pending),
Decision 78 (adopted DuckLake; deferred this runtime architecture), Decision 79 (per-Lambda deploy gating --
the DuckLake Lambdas deploy + smoke-test per CD.16), Decision 69 (Single-Portal invariant PRESERVED),
CD.15 (typed query reader -- refined), CD.8 (DuckDB engine -- unchanged), CD.9 (partitioning via ALTER),
CD.24 (per-Lambda manifests), OQ.7 / OQ.10 / OQ.11 (resolved), OQ.12 (left to T2.17).
```

## Acceptance Criteria
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses and loads via `scripts.platform_roadmap` after the edits.
- [ ] **CD.33** exists with `state: pending`, `gates: [T2.17, T2.18, T2.19]`, the eight clauses, the
      "supersedes CD.10 (illustrative, not canonical) / agent surface NOT frozen" discipline point, the
      OQ.11 -> (c) discipline point, the stable-write-id open-dependency discipline point, and the CD.30-style
      "does not edit DECISIONS.md while pending; ratified via Decision 80" clause.
- [ ] **OQ.7 / OQ.10 / OQ.11** each carry a "Resolved direction (CD.33, pending Decision 80)" annotation
      (OQ.11 cites option **c**, not b); their `resolution_tier` is unchanged; they remain in `open_questions`.
- [ ] **T2.17 / T2.18 / T2.19** include `CD.33`; the three stale `DEFERRED ... Decision 67 / CD.16` lines are
      replaced with active per-Lambda build/deploy/smoke-test criteria (Decision 79); the partition-prune,
      schema-gate/loud-fail, closed-boundary/break-glass, `current`-projection, guarded-GC, and SCD2-DQ
      criteria are present.
- [ ] **DECISIONS.md is UNCHANGED** until the ratification step (`git diff origin/main -- docs/DECISIONS.md`
      empty after the roadmap edits); Decision 80 is filed only after approval, via `file_decision`.
- [ ] The **HELD write-id decision** is recorded (ledger + CD.33 open-dependency discipline point) and is NOT
      silently resolved in this plan.
- [ ] `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected | Fix If |
|---|-------|--------|---------|----------|--------|
| 1 | pre | Roadmap loader accepts CD.33 + edits | `bin/venv-python -m scripts.platform_roadmap` | exits 0, no CD.33 error | conform to CandidateDecision (extra=forbid) fields |
| 2 | pre | Governance well-formed | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); cds={c['id']:c for c in d['candidate_decisions']}; assert cds['CD.33']['state']=='pending' and set(cds['CD.33']['gates'])=={'T2.17','T2.18','T2.19'}; ti={t['id']:t for t in d['tier_items']}; assert all('CD.33' in ti[x]['related_candidate_decisions'] for x in ('T2.17','T2.18','T2.19')); print('GOV_OK')"` | prints `GOV_OK` | add/fix the named element |
| 3 | pre | Stale DEFERRED markers removed | grep that no `pending Decision 67 / CD.16 reversal` remains in T2.17/T2.18/T2.19 | absent | replace remaining marker |
| 4 | pre | OQ.11 cites option c, not b | grep OQ.11 annotation for `option (c)` and absence of `option (b)` | option (c) present | correct the annotation |
| 5 | pre | DECISIONS.md untouched by roadmap step | `git diff --quiet origin/main -- docs/DECISIONS.md && echo NOT_ENACTED` | `NOT_ENACTED` | revert; ratification is a separate approved step |
| 6 | pre | Full presubmit | `bin/venv-python -m scripts.validate` | PASS | address before merge |

## Constraints
- Roadmap edits stage CD.33 as `state: pending` and ENACT nothing in DECISIONS.md (CD.30/CD.31 precedent).
- Decision 80 is filed via `ops_data_portal.file_decision` ONLY after explicit approval following the
  zero-context review; it allocates the `dec-XXXX` warehouse id.
- The HELD write-id decision must be resolved (or explicitly deferred to T2.17 implementation, as drafted)
  before the clause-2/7/8 idempotency wording is treated as final.
- Agent-first artefact design (CD.13/CD.14): edit the roadmap's native structures; no companion narrative doc.
- Conform to the `extra=forbid` CandidateDecision / TierItem schemas (no new top-level keys).
- No emojis; ASCII hyphens; ruff line length 127; `bin/venv-python` for all Python.

## Context
- **Why now:** Decision 78 deferred this runtime architecture to T2.16-T2.19; T2.16 is complete, so
  T2.17-T2.19 are unblocked pending a ratified architecture. The user settled the clauses; CD.10's
  six-Lambda enumeration was illustrative and is superseded without freezing the agent surface.
- **v1 -> v2:** the first zero-context review overturned the inlining (OQ.11 b -> c) and partitioning
  (`day(last_updated_timestamp)` -> `day(created_timestamp)` for history; id for current) clauses, added the
  `current` write-through projection (R-4), decoupled maintenance into non-destructive + guarded-destructive
  cadences (H1/R-3), and the user corrected the SCD2 grain. The Review-findings ledger is the durable record.
- **Stale-marker correction:** Decision 79 lifted Decision 67's Lambda-deploy clause and ratified CD.16, so
  the `DEFERRED ... pending Decision 67 / CD.16 reversal` lines in T2.17/T2.18/T2.19 are factually stale and
  become active per-Lambda V3 build/deploy/smoke-test steps.
- **Single-Portal preservation:** Decision 69's primitive-level invariant is preserved -- the portal
  abstraction (`scripts/ops_data_portal.py`) is unchanged; only the transport beneath it changes (outbox ->
  DuckLake writer) at T2.19/FP-B.
- **Review:** decision-scout (contradiction scan vs DECISIONS.md + candidate_decisions) + a distributed-
  systems correctness lens (OCC retry, catalog-commit atomicity, inlining durability, `current` projection,
  partition prune, SCD2 grain) + an adversarial ops-risk lens (closed-boundary failure modes, break-glass DR,
  guarded destructive GC, CD.10 supersession cleanliness). v2 re-review precedes ratification.
