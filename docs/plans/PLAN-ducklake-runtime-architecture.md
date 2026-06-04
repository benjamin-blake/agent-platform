# Plan

## Intent
Formalise the DuckLake ops *runtime* architecture that Decision 78 deliberately deferred to T2.16-T2.19.
Decision 78 adopted DuckLake (ratified CD.31; superseded Decisions 50/51/56/69; preserved the Decision 69
Single-Portal invariant) but left the implementation architecture and four open questions (OQ.7, OQ.10,
OQ.11, OQ.12) for the tier items to settle. This plan persists the settled architecture as a
`state: pending` candidate decision (**CD.33**), resolves OQ.7/OQ.10/OQ.11 in the roadmap's native
structures, enriches tier_items T2.17/T2.18/T2.19, and corrects the now-stale Decision-67 deferral markers
per Decision 79. The formal ratification (**Decision 81**) is drafted here for zero-context review and is
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
V1 (roadmap YAML is non-handler config with no runtime effect; Decision 48). The Decision 81 filing is a
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
| T3-c | decision-scout | OQ annotation wording must be precise about "resolved direction vs. stays open until implemented". | RESOLVED | OQ annotations below use the established "Resolved direction (CD.33, pending Decision 81) ... Enacted at Tn" pattern. | HIGH |
| **WRITE-ID** | user+dist-sys | **Write-id tiebreaker.** `_prepare_record` re-stamps `last_updated_timestamp = now()` on every attempt, breaking grain uniqueness, OCC-safe retries, and append idempotency -- all three want one stable write identity. | **RESOLVED** | **User decision: auto-generate a monotonic ULID as the `history` PK, AND keep a high-precision stable timestamp.** ULID (minted once, reused across retries) = PK + OCC idempotency key + append idempotency key (`INSERT IF NOT EXISTS`); timestamp = SCD2 ordering with ULID as monotonic tiebreaker. Closes D-2 (idempotency), D-4 (uniqueness without timestamp collision), D-12 (deterministic DR). `_prepare_record` `now()` re-stamp moves out of the retry loop. (Clauses 2, 7, 8.) | HIGH |

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add `state: pending` candidate_decision **CD.33** ("DuckLake ops runtime architecture"); annotate **OQ.7 / OQ.10 / OQ.11** with resolved directions citing CD.33 (questions stay open until the implementing tier item lands, per the established OQ-stays-open-until-implemented pattern); enrich **tier_items T2.17 / T2.18 / T2.19** (add CD.33 to `related_candidate_decisions`; pin the split, schema gate, OCC-retry, closed boundary, `current` projection, partition split, guarded GC, partition-prune smoke test); correct the stale `DEFERRED ... pending Decision 67 / CD.16 reversal` exit-criteria lines in T2.17/T2.18/T2.19 to active per-Lambda build/deploy/smoke-test steps per Decision 79 (CD.16 ratified). |
| `docs/DECISIONS.md` | Modify (ratification step only) | Append **Decision 81** ratifying CD.33 and resolving OQ.7/OQ.10/OQ.11. **Drafted below for review; applied only after approval**, alongside `ops_data_portal.file_decision` to allocate the `dec-XXXX` warehouse id. |

## Bundled Recommendations
None.

## Settled architecture (the eight clauses CD.33 / Decision 81 encode)
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
   fixed retry ceiling). On retry exhaustion the writer **fails loudly** (raises; no silent drop -- finding
   C1). Idempotency is now genuinely grounded (resolves the former HELD write-id, and findings D-2/D-4/D-12):
   each logical write **mints a monotonic ULID once, at operation start, and reuses it on every OCC retry**;
   the ULID is the **primary key of the `history` tables**, and the append is `INSERT ... IF NOT EXISTS` on
   that PK, so a committed-but-unacked write that is retried de-duplicates instead of double-appending.
   `last_updated_timestamp` is **high-precision and likewise minted once / held stable across retries** --
   it is the SCD2 version/ordering column, not the uniqueness key. The `_prepare_record` `now()` re-stamp
   therefore moves OUT of the retry loop (both ULID and timestamp are assigned before the loop). No
   reserved-concurrency=1 and no SQS FIFO -- those serialise unnecessarily. `ducklake_maintenance` runs as
   a **singleton** (no overlapping maintenance runs; DDL / `ALTER`-table maintenance ops hard-abort on
   conflict). The singleton serialises maintenance-vs-maintenance only; the **writer-vs-`expire_snapshots`**
   race (finding D-3) is closed separately in clause 5 (GC `older_than` grace strictly greater than the
   max in-flight write/retry duration), pending the snapshot-isolation capability check.
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
     accumulated small files). Merge bounds **file count / scan cost only** -- it rewrites small files into
     large ones but leaves the superseded files for the GC; it does **not** reclaim storage (finding D-6).
     `current` (high-churn upsert) needs its **own faster cadence for both merge AND `expire_snapshots`**,
     because every MERGE supersedes the prior row-version and its dead snapshots accrue quickly.
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
   prune); `current` is **hash-bucketed by `id`** with a fixed bucket count -- NOT partition-per-id, which
   would explode the partition count. This prunes the serving point-lookup; a single-row MERGE prunes too,
   but a **batch** MERGE reads the buckets its delta touches (finding D-7 -- the batch path does not prune to
   one bucket). Applied via CD.9 `ALTER TABLE ... SET PARTITIONED BY` **at table creation** (a partition
   only affects writes after the ALTER). A smoke test must prove a date-filtered query **actually prunes
   partitions** on `history` AND that the `current` lookup/MERGE scan footprint is bounded (not just parses),
   gating T2.17/T2.19.
7. **`current` write-through projection (resolves R-4).** Reads come from a materialised `current` table,
   never from a window over `history`. `history` is the append-only source of truth; `current` is a
   derived Type-1 projection (one row per `id`, latest-wins), rebuildable from `history` as DR only (that
   rebuild is the full scan we are avoiding -- never on the read path). Each write is a single DuckLake
   transaction: `INSERT history` (append the new version) then `MERGE current` (upsert from the **in-hand
   delta -- never read back from `history`**), one atomic snapshot. The MERGE is idempotent (latest-wins
   converges on replay); the `history` append is made idempotent by the **ULID PK + `INSERT IF NOT EXISTS`**
   (clause 2), so a retried dual-write neither double-appends nor diverges. The merge logic is a **shared
   helper** parametrised on `(delta, dest table, key cols, order-by)`, imported in-process so it stays
   inside the transaction, and accepts **one-or-many rows from day one** so a future per-write -> sub-second
   micro-batch switch is a config change, not a rewrite. `current` is a warehouse-resident materialisation
   written transactionally -- it is NOT the `logs/*.jsonl` read-cache anti-pattern; the DR rebuild runs
   through the portal/ETL, never restaged from a local file, and is **deterministic** because latest-per-id
   orders by `(last_updated_timestamp, ULID)` and the ULID is monotonic (resolves D-12). **The single-
   transaction dual-table atomicity and `MERGE`-through-DuckLake are SPIKE-GATED capability claims** (finding
   D-1): if a DuckLake transaction does not wrap multi-table DML into one snapshot, or `MERGE` is unsupported
   through DuckLake's DML layer, the fallback is in-transaction `DELETE WHERE id = ?` + `INSERT` on `current`,
   or eventual-consistency on `current` with a reconciliation pass. Verified in the capability-review below.
8. **SCD2 keys + DQ invariants (no engine-enforced keys).** DuckLake/Iceberg enforces no PK/FK; enforcement
   is application + DQ (BigQuery discipline). Keys (resolves the former HELD write-id and findings D-2/D-4):
   the `history` **primary key is an auto-generated monotonic ULID** (one per write/version row, unique by
   construction -- so two legitimate same-instant updates to one `rec_id` never collide, unlike a timestamp
   grain); `rec_id` is the natural/business key; `last_updated_timestamp` is high-precision and stable-per-
   write, used for SCD2 version ordering with the ULID as the deterministic monotonic tiebreaker. Everything
   in the project is SCD2. Three DQ invariants: (i) **PK uniqueness** -- no two `history` rows share a ULID
   (trivially held by generation + the `INSERT IF NOT EXISTS` append; DQ asserts it); (ii) **current-version
   uniqueness** -- at most one `current` row per `rec_id`, enforced **structurally** by the clause-7 `current`
   MERGE key (`rec_id`) rather than as a post-hoc check; (iii) **referential existence** -- `update_rec`
   confirms the `rec_id` exists via a point-lookup on `current` **executed inside the write transaction's
   snapshot** (finding D-5, closes the TOCTOU window), while `file_rec` requires the freshly DynamoDB-
   allocated `rec_id` to NOT exist.

OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal gate is the
documented default); CD.33 does not pre-empt it.

## v2-review results (round 2 -- three zero-context lenses)
Durable capture of the second review pass (subagent transcripts are ephemeral). Disposition codes:
FIX-NOW (unambiguous, applied in this draft) / SPIKE-GATE (demote from settled to assumption pending a
DuckLake capability spike) / DECISION (needs the user) / ENCODE (into T2.17-T2.19 exit criteria) /
PRESERVE (reviewer confirmed the v2 call is correct). The headline, agreed across all three lenses: **v2
ratifies conclusions whose preconditions are unspecified, unverified, or HELD** -- recovery mechanics
(ops), correctness properties (dist-sys), and the CD.10 framing (scout).

### Governance / contradiction lens
| ID | Sev | Finding | Disposition |
|----|-----|---------|-------------|
| G-1 | CRIT | Manifest path wrong: tier items reference `config/lambda/<slug>/manifest.yaml`; SSOT is `src/lambdas/<slug>/manifest.yaml` (per `scripts/lambda_manifest.py`, CD.24, the coverage gate). Pre-existing T2.17/T2.18 error the draft inherits. | FIX-NOW (correct in ROADMAP edit + Scope) |
| G-2 | HIGH | CD.10's six Lambdas claimed to be **real shipped artifacts**, contradicting the "illustrative" framing. | **DISMISSED (reviewer misread).** Verified on disk: all six (`log_rec`/`update_rec`/`log_decision`/`query`/`list_tools`/`maintenance`) are `status: stub` mock examples -- only `ops-compaction`/`data-pipeline` are `status: active`. The stubs *prove* the illustrative point; clause 1's "illustrative, never canonical" framing stands. (User-confirmed.) Residual: still restate CD.10's two-principal allow-list and note `ducklake_maintenance` is net-new (the `maintenance` stub is illustrative, not a real conflict). |
| G-3 | HIGH | Schema has **no** CD-supersedes-CD field and is `extra=forbid`, so the T3-a "machine-readable structured supersession" resolution is unachievable as written. | FIX-NOW (accept prose-only via discipline_point, OR reuse the existing `narrowly_supersedes` dict shape; strike the impossible T3-a wording) |
| G-4 | HIGH | OQ.11 has a pre-existing internal contradiction: `resolution_tier: T2.18` vs notes-body "Resolve at T2.19". Draft inherits it unflagged. | FIX-NOW (flag + pin the enacting tier authoritatively) |
| G-5 | MED | Decision 69 was **already superseded by Decision 78**; only its invariant survives. Draft treats it as a live, preservable decision. | FIX-NOW (reword "preserves the Decision 69 invariant *as carried forward by Decision 78*" everywhere) |
| G-6 | MED | V1 tier is correct for this YAML-only plan, but the draft doesn't say the V3 deploy/smoke steps are authored *into* T2.17-T2.19 yet executed by those tier items' own future plans. | FIX-NOW (one clarifying sentence) |
| G-7 | LOW | CD.31 discipline_point (ROADMAP ~1244) "FP-B carries Decision 67 / CD.16 deferred-deploy markers" is now collateral-stale post-Decision 79. | ENCODE (note as out-of-scope recommendation) |
| -- | PASS | DECISIONS.md non-edit invariant, schema conformance, HELD-row carriage, and all decision/CD citations (CD.8/9/15/24/30/31/32; Dec 48/67/69/78/79; OQ option letters) verified correct. | PRESERVE |

### Distributed-systems correctness lens
| ID | Sev | Finding | Disposition |
|----|-----|---------|-------------|
| D-1 | CRIT | Clause 7 single-transaction dual-table atomicity (`INSERT history` + `MERGE current` = one snapshot) is an **unverified DuckLake capability** asserted RESOLVED/HIGH. If DuckLake commits per-table, `current` can be permanently stale after a crash between commits. | SPIKE-GATE (prove multi-table single-snapshot txn + `MERGE`-through-DuckLake; write the DELETE+INSERT fallback into the plan explicitly) |
| D-2 | CRIT | Clause 2 "idempotent SCD2 appends keyed by id" is **FALSE under current code** (`ops_writer.py:220` re-stamps `last_updated_timestamp=now()` each attempt) -> a committed-but-unacked write + retry double-appends. Self-contradiction with the HELD row. | **RESOLVED** by the WRITE-ID decision: ULID minted once + `INSERT IF NOT EXISTS` on the ULID PK makes the append genuinely idempotent; re-stamp moves out of the retry loop. Idempotency is now correctly grounded, not asserted-on-faith. (Clauses 2, 7, 8.) |
| D-3 | HIGH | Maintenance singleton serialises maintenance-vs-maintenance only, **not writer-vs-`expire_snapshots`**. GC computing its orphan set from a pre-commit snapshot can delete a Parquet an in-flight commit will reference. | ENCODE + SPIKE-GATE (require `older_than` grace > max in-flight write/retry duration; confirm GC snapshot-isolation against concurrent commits, or quiesce writes during GC) |
| D-4 | HIGH | Grain uniqueness (i) is unsatisfiable under coarse clock + OCC retry; a stable timestamp alone collides with a legitimate same-instant update. | **RESOLVED** by the WRITE-ID decision: the monotonic ULID (not the timestamp) is the PK, unique by construction even for same-instant same-`rec_id` updates; timestamp is ordering-only with ULID tiebreak. (Clause 8.) |
| D-5 | HIGH | Invariant (iii) `update_rec` referential check is a cross-table read gating a write -> TOCTOU unless executed *inside* the write transaction's snapshot; "current-version uniqueness structural via MERGE key" is contingent on D-1's MERGE-under-OCC semantics. | ENCODE (specify check is in-transaction) + SPIKE-GATE (via D-1) |
| D-6 | MED | Clause 5 framing conflates file-COUNT bounding (merge) with STORAGE bounding (GC) -- they are not substitutes. `current`'s high churn may need its **own faster expire cadence**, in tension with the "slower destructive GC". | FIX-NOW (sharpen framing) + ENCODE (current expire cadence) |
| D-7 | MED | `current`-by-`id`: partition-per-id risks explosion; hash-bucketing helps point-lookups but a **batch MERGE scatters across buckets** so "MERGE prunes" is false for the batch path. | FIX-NOW (specify hash(id) fixed bucket count; qualify the MERGE-prune claim) |
| D-8 | MED | Partition-prune smoke test is necessary-not-sufficient: must assert prune on **both** tables and the **MERGE** scan footprint, not just a SELECT. | ENCODE |
| D-9 | MED | Read-your-write is contingent on D-1 + the reader re-resolving the latest catalog snapshot through RDS Proxy; smoke test must be **cross-Lambda via Proxy**, not in-process. | ENCODE |
| D-10 | LOW | VP grep step 3 may miss DEFERRED-line phrasing variants; broaden to grep `DEFERRED` within the tier items. | FIX-NOW |
| D-11 | LOW | Ledger confidence flags conflate "finding worked in detail" with "resolution correct"; R-1/R-4 marked HIGH/RESOLVED actually rest on unverified DuckLake capability. | FIX-NOW (add capability-confidence; downgrade to spike-gated) |
| D-12 | LOW | DR rebuild "latest-per-id" is **non-deterministic** if grain collides -> inherits D-2/D-4. | **RESOLVED** by the WRITE-ID decision: latest-per-id orders by `(last_updated_timestamp, ULID)`; ULID monotonicity makes the rebuild deterministic. (Clause 7.) |
| -- | PRESERVE | Inlining-off durability reasoning (C2), "expire != delete", "ALTER partition before first write", loud-fail-on-exhaustion (C1) confirmed correct. | PRESERVE |

### Adversarial ops-risk lens
| ID | Sev | Finding | Disposition |
|----|-----|---------|-------------|
| O-1 | CRIT | Break-glass undefined. Only on-disk break-glass is `PlatformAdmin` (provisioning/IAM), **not a data-plane catalog+S3 reader**. Closed boundary -> total inspection blackout if writer+reader both wedge. | DECISION + ENCODE (specify a dedicated read-only break-glass role + VPC attach path + audit + quarterly drill; gate boundary-final on it) |
| O-2 | CRIT | RDS catalog is a **single point of total, irreversible loss** -- DuckLake Parquet is unreadable without it. On disk: single-AZ, 7-day PITR, no cross-region, **no catalog-rebuild-from-Parquet runbook**. "Rebuildable from history" assumes the catalog survives. | DECISION + ENCODE (multi-AZ + cross-region backup + extended retention; author+test a catalog-rebuild runbook; gate T2.19) |
| O-3 | CRIT | Destructive-GC guardrails are slogans -- every value unspecified (retention floor, grace, breaker threshold, pager). Race: GC deletes a slow-reader-pinned or staged-uncommitted Parquet -> silently-incomplete or permanently-corrupt governance data. | ENCODE (pin concrete numbers: floor >= max reader timeout + max writer retry window; breaker = absolute count AND percent; query oldest pinned snapshot before GC) |
| O-4 | HIGH | Observability detects liveness, not **correctness**. Missing: snapshot->S3 object-existence audit, row-count/DQ-drift, history<->current divergence alarm, break-glass-assumption alarm, maintenance deadman. | ENCODE (periodic invariant-auditor, separate from writer; divergence/missing-object alarms page) |
| O-5 | HIGH | RDS Proxy named but **not provisioned** (no `aws_db_proxy` on disk); saturation = borrow-timeout; undefined whether that's a retry (storm risk) or loud fail. | ENCODE (provision Proxy; cap writer concurrency < connection ceiling; classify borrow-timeout retry distinctly; alarm) |
| O-6 | HIGH | No writer rollback story (sole chokepoint -> bad deploy = total write outage); schema-migration DDL vs in-flight writes = torn write (writer validates live schema; commit lands post-ALTER). | ENCODE (versioned-alias/canary + auto-rollback; migration protocol: quiesce/additive-only/version-stamped reject) |
| O-7 | MED | Singleton enforcement mechanism unnamed; no lock TTL vs Lambda timeout; **no maintenance deadman alarm**; a hung run blocks the next or (no lock) overlaps and races GC. | ENCODE (advisory lock w/ lease TTL > timeout; deadman + duration alarms; idempotent/resumable GC) |
| O-8 | MED | HELD write-id is load-bearing for **data-integrity**, not just idempotency nicety; ratifying OCC-retry while it's undefined leaves the safety argument unproven. | DECISION (resolve before writer ships; or hard T2.17 gate) |
| O-9 | LOW | `delete_automated_backups=true` + single fixed `final_snapshot_identifier` widens destroy blast radius for irreplaceable data. | ENCODE (reconsider; destroy-guard the catalog; cross-region logical dumps as backstop) |

### Cross-lens synthesis -- what this means for ratification
Both correctness and ops lenses independently conclude the **ratify-now/specify-later sequencing is the
core flaw**. Three clauses asserted RESOLVED actually rest on unverified DuckLake capabilities (D-1, D-3,
D-5) and must become SPIKE-GATE. The plan is internally self-contradictory on idempotency/uniqueness (D-2,
D-4 vs the HELD row). The CD.10 framing is factually wrong (G-2). And the closed boundary is being ratified
without a tested way back in (O-1, O-2, O-3).

**Decisions taken (this session):**
1. **CD.10 disposition (G-2): DISMISSED.** The six Lambdas are `status: stub` mocks (verified) -- the
   "illustrative, never canonical" framing in clause 1 is correct. No consolidation question; residual is
   only to restate CD.10's two-principal allow-list and note `ducklake_maintenance` is net-new.
2. **Write-id mechanism (D-2/D-4/D-12/O-8): RESOLVED -> monotonic ULID PK + stable high-precision timestamp.**
   ULID is the `history` PK and the single stable write identity across OCC retries (idempotency + uniqueness);
   timestamp is SCD2 ordering with ULID tiebreak. Folded into clauses 2/7/8.
3. **Ratification sequencing (O-1/O-2/O-3 + D-1): resolve the uncertainty rather than gate around it.** The
   load-bearing DuckLake capability claims (D-1 multi-table single-snapshot txn + `MERGE`-through-DuckLake;
   D-3 GC snapshot-isolation / `older_than` semantics; inlining `inlined_rows=0`; `ALTER ... SET PARTITIONED
   BY` write-time semantics; `expire`/`cleanup`/`delete_orphaned` contracts) are **verified against the
   official DuckDB/DuckLake docs by the capability-review below** before ratification, so spike-gated clauses
   are either confirmed (ratify) or fall back (documented). The ops recovery mechanics (break-glass O-1,
   catalog DR O-2, GC thresholds O-3) remain ENCODE into T2.17-T2.19 exit criteria with concrete values.

**Capability-review plan (Q3):** dispatch zero-context subagents to **verify each load-bearing claim against
the official DuckDB + DuckLake documentation** (markdown, agent-friendly), citing the exact doc section per
claim, and to mark each claim CONFIRMED / REFUTED / UNVERIFIABLE with the fallback to apply if refuted. If a
subagent cannot reach the web, the fallback is direct doc fetch/search by the lead. This replaces "assume +
spike-gate later" with "verify now, then ratify what holds."

**Decision numbering:** the draft ratification is **Decision 81** -- `origin/main` already took Decision 80
(Build-Tooling Direction) via another agent; renumbered to avoid collision. Rebased onto `origin/main` after
this commit.

## Proposed CD.33 (state: pending) -- exact YAML to insert after CD.32
```yaml
  - id: CD.33
    title: DuckLake ops runtime architecture -- writer/reader/maintenance split, OCC-retry concurrency, current projection, closed read/write boundary
    detail: |
      Pins the ops DuckLake runtime architecture that Decision 78 (CD.31) deferred to T2.17-T2.19.
      Ratified by Decision 81 (this CD does NOT edit DECISIONS.md while pending; ratification lands via
      the log-decision path = Decision 81, mirroring CD.31 -> Decision 78).
      (1) Three-artifact split by access pattern -- ducklake_writer / ducklake_reader / ducklake_maintenance
          -- justified by IAM-principal + scaling + deploy isolation, NOT concurrency. Supersedes CD.10's
          six-Lambda enumeration, which was illustrative (examples of needed verbs), never canonical. CD.33
          commits ONLY to the access-pattern split + closed boundary; the verb/tool set behind writer and
          reader stays deliberately extensible. The invariant is path, not verb count.
      (2) Concurrency (OQ.10 -> c): concurrent writers + bounded application-level OCC retry (backoff+jitter,
          fixed ceiling, loud-fail on exhaustion) in the writer. Idempotency is grounded: each write mints a
          monotonic ULID once at op start, reused across retries, as the history PK; the append is INSERT IF
          NOT EXISTS on that PK, so a committed-but-unacked retry de-dupes (not double-append). last_updated_
          timestamp is high-precision, stable-per-write, ordering-only. _prepare_record now() re-stamp moves
          out of the retry loop. NOT reserved-concurrency=1, NOT SQS FIFO. ducklake_maintenance is a singleton
          (DDL/ALTER hard-abort on conflict); the writer-vs-expire_snapshots race is closed by the clause-5
          GC older_than grace > max in-flight write/retry duration (pending the GC snapshot-isolation check).
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
          logs/*.jsonl read-cache anti-pattern. SPIKE-GATED: single-txn multi-table atomicity + MERGE-through-
          DuckLake are verified against official docs (capability-review); fallback = in-txn DELETE+INSERT.
      (8) SCD2 keys + DQ (no engine PK/FK; BigQuery discipline): history PK = auto-generated monotonic ULID
          (unique per write row, so same-instant same-rec_id updates never collide); rec_id is the natural
          key; last_updated_timestamp is high-precision, stable-per-write, SCD2 ordering with ULID tiebreak.
          DQ invariants: ULID PK uniqueness; one current row per rec_id (structural via the current MERGE key
          on rec_id); update_rec referential existence (point-lookup on current, in-transaction) while
          file_rec requires the DynamoDB-allocated rec_id to NOT exist.
      OQ.12 (version/upgrade policy) is left to T2.17 implementation (clone-rehearsal default); not pre-empted.
    gates: [T2.17, T2.18, T2.19]
    state: pending
    filed_via: pending_log_decision_lambda
    supersedes_decisions: []
    discipline_points:
      - "Supersedes CD.10's six-Lambda enumeration; CD.10 is state:pending so no DECISIONS.md transition. CD.10's six slugs are status:stub MOCK examples (verified on disk), which confirms they were illustrative, never canonical. The agent verb/tool surface is explicitly NOT frozen by CD.33 -- only the writer/reader/maintenance path split and the closed boundary are. CD.10's PlatformDev/PlatformAdmin two-principal allow-list is retained, not superseded."
      - "Preserves the Decision 69 Single-Portal primitive-level invariant AS CARRIED FORWARD BY Decision 78 (Decision 69 itself was already superseded by Decision 78; only its invariant survives). Portal abstraction unchanged; transport changes."
      - "Does NOT edit DECISIONS.md while pending; supersession + OQ.7/OQ.10/OQ.11 resolution land at ratification via the log-decision path = Decision 81."
      - "Refines CD.15 (typed query reader) and CD.8 (DuckDB engine) and applies CD.9 partitioning; does not contradict them."
      - "OQ.11 resolves to option (c) (inlining disabled for governance tables), NOT option (b); the v1 draft's option (b) was overturned by the C2 durability-window finding."
      - "Write-id RESOLVED: history PK = monotonic ULID (stable across OCC retries) + high-precision stable timestamp (ordering-only). This single mechanism grounds clause-2 idempotency, clause-7 append idempotency, clause-8 PK uniqueness, and deterministic DR rebuild; the _prepare_record now() re-stamp must move out of the retry loop at T2.17."
      - "SPIKE-GATED capability claims verified against official DuckDB/DuckLake docs before ratification: (a) single DuckLake transaction wraps multi-table DML into one snapshot; (b) MERGE supported through DuckLake DML; (c) destructive-GC snapshot-isolation / older_than semantics vs concurrent writers. Documented fallbacks: DELETE+INSERT (a/b), write-quiesce window (c)."
    enforcement_mechanism: "ducklake_writer schema gate + closed reader/writer boundary; ULID PK + INSERT-IF-NOT-EXISTS append idempotency; current write-through projection enforces current-version uniqueness; guarded destructive-GC circuit breaker; partition-prune smoke test in T2.17/T2.19 exit criteria; per-Lambda CD.24 manifests."
```

## Proposed OQ annotations (append to the `notes` of each; questions stay open until implemented)
- **OQ.7** -- append: `Resolved direction (CD.33, pending Decision 81): option (a) -- no Athena escape hatch.
  The closed reader/writer boundary is the design goal; ad-hoc scans live behind ducklake_reader (scale reader
  compute if memory binds), not a parallel Iceberg mirror. One audited admin-account break-glass path for DR.
  Enacted at T2.19.`
- **OQ.10** -- append: `Resolved direction (CD.33, pending Decision 81): option (c) -- concurrent writers +
  bounded application-level OCC retry (backoff+jitter, loud-fail on exhaustion) in ducklake_writer (ops writes
  are idempotent SCD2 appends keyed by id); ducklake_maintenance runs as a singleton. NOT reserved-concurrency=1,
  NOT SQS FIFO. Enacted at T2.19.`
- **OQ.11** -- append: `Resolved direction (CD.33, pending Decision 81): option (c) -- inlining DISABLED
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

## Decision 81 -- DRAFT (filed via the log-decision path only after approval)
```markdown
## Decision 81: Ratify the DuckLake ops runtime architecture (CD.33); resolve OQ.7 / OQ.10 / OQ.11 (Decided)

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
   ceiling, loud-fail on exhaustion) in ducklake_writer. Idempotency is grounded by the write-id mechanism
   (below): a monotonic ULID minted once and reused across retries is the history PK, and the append is
   INSERT-IF-NOT-EXISTS on it, so retries de-duplicate. ducklake_maintenance runs as a singleton; the
   writer-vs-expire_snapshots race is closed by a GC older_than grace exceeding max in-flight write
   duration. Reserved-concurrency=1 and SQS FIFO are rejected as over-serialising.
4. Portal surface = read + write categories; the sync category is eliminated because DuckLake's atomic
   catalog-snapshot commit removes the outbox/drain step. Writes are atomic at the catalog commit (no
   external sequencing); aborted commits leave orphan Parquet reclaimed by delete_orphaned_files. The
   Decision 69 Single-Portal invariant -- as carried forward by Decision 78 (which already superseded
   Decision 69) -- is PRESERVED: all writes transit scripts/ops_data_portal.py; only the transport changes.
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
   source of truth; current is rebuildable from history for DR (deterministically, ordering by
   last_updated_timestamp then ULID). Keys (no engine-enforced PK/FK): history PK = auto-generated monotonic
   ULID; rec_id is the natural key; last_updated_timestamp is high-precision, stable-per-write, ordering-only.
   DQ enforces ULID PK uniqueness, current-version uniqueness (structural via the current MERGE key on
   rec_id), and update_rec in-transaction referential existence.
9. OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal default), not
   pre-empted here.

**Capability dependency:** clauses 4(atomicity)/6(partition prune)/7(single-txn multi-table + MERGE)/8 rest
on DuckLake behaviours verified against the official DuckDB/DuckLake documentation by the pre-ratification
capability-review (single-snapshot multi-table transaction; MERGE-through-DuckLake; GC snapshot-isolation /
older_than semantics; inlined_rows=0; ALTER...SET PARTITIONED BY write-time semantics). Documented fallbacks
apply if any claim is refuted (DELETE+INSERT for MERGE; write-quiesce window for GC). The write-id is
RESOLVED in-design (ULID PK + stable timestamp); only the code change (move the now() re-stamp out of the
retry loop) is a T2.17 implementation task.

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

**Related:** CD.33 (ratified here), CD.10 (six-Lambda enumeration superseded; the six are status:stub mocks,
confirming illustrative; two-principal allow-list retained; state:pending),
Decision 78 (adopted DuckLake; deferred this runtime architecture; superseded Decision 69), Decision 79
(per-Lambda deploy gating -- the DuckLake Lambdas deploy + smoke-test per CD.16), Decision 69 (Single-Portal
invariant preserved as carried forward by Decision 78),
CD.15 (typed query reader -- refined), CD.8 (DuckDB engine -- unchanged), CD.9 (partitioning via ALTER),
CD.24 (per-Lambda manifests), OQ.7 / OQ.10 / OQ.11 (resolved), OQ.12 (left to T2.17).
```

## Acceptance Criteria
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses and loads via `scripts.platform_roadmap` after the edits.
- [ ] **CD.33** exists with `state: pending`, `gates: [T2.17, T2.18, T2.19]`, the eight clauses, the
      "supersedes CD.10 (status:stub mocks, illustrative, not canonical; two-principal allow-list retained) /
      agent surface NOT frozen" discipline point, the OQ.11 -> (c) discipline point, the write-id-RESOLVED
      (ULID PK + stable timestamp) discipline point, the capability-spike discipline point, and the CD.30-style
      "does not edit DECISIONS.md while pending; ratified via Decision 81" clause.
- [ ] **OQ.7 / OQ.10 / OQ.11** each carry a "Resolved direction (CD.33, pending Decision 81)" annotation
      (OQ.11 cites option **c**, not b); their `resolution_tier` is unchanged; they remain in `open_questions`.
- [ ] **T2.17 / T2.18 / T2.19** include `CD.33`; the three stale `DEFERRED ... Decision 67 / CD.16` lines are
      replaced with active per-Lambda build/deploy/smoke-test criteria (Decision 79); the partition-prune,
      schema-gate/loud-fail, closed-boundary/break-glass, `current`-projection, guarded-GC, and SCD2-DQ
      criteria are present.
- [ ] **DECISIONS.md is UNCHANGED** until the ratification step (`git diff origin/main -- docs/DECISIONS.md`
      empty after the roadmap edits); Decision 81 is filed only after approval, via `file_decision`.
- [ ] The **write-id decision** is recorded as RESOLVED (ULID PK + stable high-precision timestamp) in the
      ledger and the CD.33 discipline points, with the `_prepare_record` re-stamp fix flagged as a T2.17 task.
- [ ] The **capability-review** has marked each load-bearing DuckLake claim CONFIRMED / REFUTED / UNVERIFIABLE
      with a cited doc section, and any REFUTED claim has its fallback folded into the relevant clause.
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
- Decision 81 is filed via `ops_data_portal.file_decision` ONLY after explicit approval following the
  zero-context review; it allocates the `dec-XXXX` warehouse id.
- The write-id decision is RESOLVED (ULID PK + stable high-precision timestamp); the only remaining work is
  the T2.17 code change to move the `_prepare_record` `now()` re-stamp out of the OCC-retry loop.
- The load-bearing DuckLake capability claims (clauses 4/6/7/8) must be verified against official docs by the
  capability-review before Decision 81 is filed; refuted claims trigger their documented fallback.
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
