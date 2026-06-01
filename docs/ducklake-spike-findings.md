# DuckLake Spike Findings

Date: 2026-06-01
Plan: docs/plans/PLAN-ducklake-spike.md
Branch: claude/compassionate-euler-G8M0m

---

## Verdict

**Recommendation: PROCEED**

DuckLake v1.0 works end-to-end on the real stack (DuckDB 1.5.3 + ducklake extension +
S3 + local SQLite catalog). All verification-plan acceptance criteria were met. The
findings below document the metrics, constraints, and open questions for FP-A.

---

## Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| DuckDB version | 1.5.3 | Already installed; install-gap pre-closed by PLAN-duckdb-read-path-swap |
| ducklake extension | 1.0 | Loaded successfully from extensions.duckdb.org |
| Connection setup (extensions cached) | ~124ms | Includes INSTALL/LOAD ducklake + httpfs + ATTACH catalog |
| Write 50 rows (batch, established conn) | ~863ms | SQLite catalog + S3 data path overhead; see note below |
| Read 50 rows (established conn) | ~8ms | In-memory after catalog lookup |
| Write 200 rows (batch, established conn) | ~2580ms (total including setup) | Scaling roughly linear with row count |
| Inlining threshold | >200 rows | Both 50- and 200-row writes produced 0 S3 Parquet files |
| S3 data files after 50 rows | 0 | Data fully inlined in catalog SQLite file |
| S3 data files after 200 rows | 0 | Still inlined; flush required to materialise Parquet |
| S3 prefix after clean run | Empty | All catalog-tracked data is inlined until explicit flush |

**Write latency note:** The ~863ms write time for 50 rows (after connection) is higher
than expected for a local SQLite catalog. This is likely caused by DuckLake committing
each INSERT batch to the SQLite WAL and potentially confirming the S3 DATA_PATH
reachability on each attach. Investigation for FP-A: benchmark with `BEGIN; ... COMMIT`
explicit transactions and check whether the DATA_PATH confirmation adds overhead.

---

## Catalog Approach and Cost

- **Catalog type used:** Local DuckDB/SQLite file (`.db` file, in `/tmp/` for the spike).
- **Cost:** Effectively $0 for the spike. The catalog is a local file; S3 costs only apply
  when data is flushed from inline storage to Parquet (not triggered in 50-200 row writes).
- **Production consideration:** The local SQLite catalog must be co-located with the writer.
  For a single-writer Lambda this is acceptable (ephemeral `/tmp`), but catalog durability
  requires an EFS mount or a managed catalog store.
- **Aurora DSQL future-migration aim:** When serialised writes become a bottleneck AND
  Aurora DSQL's Postgres-protocol compatibility matures enough to back a DuckLake catalog,
  the SQLite file can be replaced with a DSQL endpoint. This is a named FP-A obligation;
  NOT built in this spike. The DuckLake extension supports pluggable catalog backends.

---

## Inlining Behaviour

- DuckLake v1.0 inlines small writes in the catalog (SQLite) rather than creating
  sub-threshold Parquet files. In the spike, ALL writes (5 rows through 200 rows) were
  inlined -- `ducklake_data_file` count remained 0 for all tested write sizes.
- Inlined data IS readable via normal `SELECT` -- DuckLake transparently merges inline
  and file storage.
- `ducklake_flush_inlined_data(spike_lake)` materialises inlined data to a single
  Parquet on S3 on demand (tested: 5 inline rows -> 1 Parquet at 1447 bytes).
- S3 file path format: `s3://{bucket}/{data_path}/main/{table}/{uuid}.parquet`
- **FP-A implication:** For the 722-row ops store, ALL operational data would be inlined
  (sub-threshold). The practical behavior is: catalog (SQLite) as the hot path, with
  explicit `flush_inlined_data` required to produce S3 Parquet for durability. FP-A
  must decide the flush policy (on-commit vs scheduled vs size-triggered).

---

## Serialised Concurrency Result

- Two sequential writers on the same catalog file write without row loss or corruption.
- Final row count equals the sum of both writers' appends (verified: 30 + 25 = 55).
- The module-level `threading.Lock` provides serialisation within a single process.
- **Single-writer constraint confirmed:** DuckLake with a local SQLite catalog is
  effectively single-writer (SQLite WAL). Multi-writer concurrency is NOT supported
  without an external catalog (e.g., Aurora DSQL) -- this was in-scope as an accepted
  constraint. Documented for FP-A.

---

## SCD2 Reproduction Observation (Decision 56)

- DuckLake's append + read-dedup reproduces the Decision-56 SCD2 current-state pattern.
- Verified: writing id `"scd2-0"` twice (with different `event_type`) produces 2 rows
  in `read_all()` but 1 row in `current_state()` (latest `inserted_at` wins), matching
  `ROW_NUMBER() OVER (PARTITION BY id ORDER BY inserted_at DESC) = 1`.
- The ops store's SCD2 dedup pattern is reproducible in DuckLake with the same SQL.

---

## CD.9 Partitioning (Constraint Finding)

- DuckLake v1.0 does NOT support `PARTITION BY` in `CREATE TABLE` DDL.
- Attempted: `CREATE TABLE ... (id INT, dt DATE) PARTITION BY (dt)` -> Parser Error.
- Mitigation: a `part_date DATE` column serves as a logical partition key in the spike
  schema. Physical partitioning (for efficient S3 prefix pruning on large tables) is
  an FP-A concern. DuckLake's own file organisation and `ducklake_merge_adjacent_files`
  may provide equivalent pruning through file-level metadata.

---

## Extension Network Risk

- The `ducklake` and `httpfs` extensions are downloaded from `extensions.duckdb.org`
  on first use (per DuckDB connection without a local cache).
- In this container environment, both extensions were available and downloaded successfully.
- **Risk for FP-A / Lambda:** Lambda execution environments have restricted egress in
  VPC configurations. The extensions must be pre-installed in the Lambda image or bundled
  explicitly. This is a BLOCKING consideration for FP-B (full Lambda deployment).
- **Mitigation path:** Bundle extensions in the Lambda image build (`build_lambda.py` step)
  using `COPY (SELECT * FROM duckdb_extensions() ...) TO ...` or the DuckDB extension
  autoload local path setting. FP-A must document this as a Lambda-packaging obligation.

---

## Aurora DSQL Future-Migration Aim

As decided during planning (see plan Context section), the intended long-term catalog path is:

1. **Now (spike):** Local SQLite file catalog in `/tmp/`. Single-writer, ephemeral.
2. **FP-A:** Evaluate durable local SQLite backed by EFS for Lambda persistence, OR a
   managed catalog using a Postgres-compatible endpoint (Aurora DSQL or RDS Aurora).
3. **Future (when DSQL matures):** Replace the SQLite file with an Aurora DSQL endpoint
   in the DuckLake ATTACH string, enabling serverless scale-to-zero + eventual
   multi-writer support as DSQL's Postgres-protocol compatibility stabilises.

This migration path preserves the single-writer serialisation invariant in the interim
while providing a concrete upgrade path when the bottleneck is encountered.

---

## Follow-On Plans (Named, Not In This Scope)

- **FP-A DuckLake roadmap reconciliation** (V1 governance): author a candidate decision
  adopting DuckLake for the operational lakehouse; amend NS.1, CD.8, CD.15; supersede
  the JSONL-staging + ops_compaction + awswrangler.to_iceberg write path; retire
  ops_compaction Lambda; document Aurora DSQL migration aim. Gated on this PROCEED.
- **FP-B full ops/telemetry write-path migration to DuckLake** (V3): replace OpsWriter
  staging path; swap DuckDBIcebergReader -> DuckLake reader; Lambda deploy carries
  Decision 67 DEFERRED marker. BLOCKED until FP-A ratifies.
- **FP-C market_data write-path assessment** (separate; MERGE-upsert semantics differ
  from append-only ops).
- **FP-D rec-2026** (CI-hardening: wire verify_ci_workflow guards into validate.py).
