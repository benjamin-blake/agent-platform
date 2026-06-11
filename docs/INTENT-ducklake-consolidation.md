# INTENT: DuckLake Consolidation - Single-Backend Ops Store

Status: PROPOSED (architecture ratified in session 2026-06-11; Decision entry pending human sign-off)
Author: architecture session 2026-06-11 (Claude Code on the web)
Consumed by: /plan sessions deriving the phase plans below; decision-scout; plan-critique.

## Ratified premises (stated by the owner, 2026-06-11)

| # | Premise | Consequence |
|---|---------|-------------|
| P1 | All dev sessions run on Claude Code on the web. There is no local dev environment. | "Offline" is not a real client state. Write buffering for offline survival protects nothing and creates loss windows on ephemeral containers. |
| P2 | All data currently stored in Athena/Iceberg ops tables is discardable. | No reverse-migration or dual-read compatibility work is needed. Tables are recreated on DuckLake, not migrated. |
| P3 | ops_decisions is recreatable from docs/DECISIONS.md (existing ETL pattern). | Decisions cutover = create table + re-run ETL. Zero data-migration risk. |
| P4 | The ops store is small (~900 rows recs, ~44 decisions) and single-writer in practice. | Engine-scale concerns (Athena large-scan escape hatch) do not apply to the ops store. Market-data engine choice is explicitly OUT of scope here. |

## Problem statement

The T2.19 recs cutover left the platform straddling two warehouses. The dual state is
now producing live faults, not just maintenance cost:

1. **The Iceberg "rollback" for recs is already fictional.** The retained copy is frozen
   at the 2026-06-09 cutover; DuckLake has accrued every write since (rec-2120..rec-2170+).
   Setting OPS_STORAGE_BACKEND=iceberg today silently time-travels the rec queue back two
   days. An insurance policy that can no longer pay out costs premiums AND blocks demolition.
2. **Half-migrated read semantics caused a silent false zero** (rec-2170): the preflight
   open/aging/non-automatable counts have read 0 on every session since cutover because
   current_state's row_filter parameterisation drops the column name and the reader binds
   the value against the merge key (WHERE id = 'open').
3. **The offline outbox inverts its purpose on CC-web** (premise P1): logs/.ops-outbox/ is
   gitignored, so a pending rec queued in an ephemeral container is LOST when the container
   is reclaimed unless drained in-session. Observed live 2026-06-11: a file_rec under the
   admin profile (no dynamodb:UpdateItem) buffered a misconfiguration instead of loud-failing.
4. **CI DQ checks error on the DuckLake path** (rec-2150/2151/2153): 20 errored checks on
   main while Athena verifiers pass in the same run. The recs checks route to the DuckLake
   reader (apply_backend_routing) but CI defines no DUCKLAKE_READER_URL and the OIDC CI
   roles' reader access (ssm:GetParameter + lambda:InvokeFunctionUrl) is unverified.
5. **Preflight burns minutes on a dead estate**: telemetry Athena queries poll tables that
   have not existed since the 2026-05-28 account migration (TABLE_NOT_FOUND every session);
   decisions/priority-queue reads walk a reader-fallback-Athena chain with VarChar
   re-coercion. Observed wall time 2026-06-11: 4m40s.
6. **The boundary does not own its keyspace**: callers allocate rec-NNN client-side from a
   DynamoDB counter and the writer accepts any id (write_ops has no require-absent gate), so
   entity-id integrity depends on every caller's correctness rather than on the boundary.

## Target end-state

One warehouse (DuckLake on Neon catalog + S3 Parquet), one write authority that owns its
keyspace, one read boundary that accepts named verbs rather than SQL, zero client-side
buffering, zero Athena/Iceberg in the ops path.

```
agent/skill/script (CC-web, CI)
        |            SigV4 Function URL (AWS_IAM)
        v
ducklake_reader  -- named verbs only: no caller SQL crosses the boundary
ducklake_writer  -- file_ops allocates id atomically with the insert; update_ops
        |           require-exists; create collisions rejected (require-absent)
        v
Neon catalog (DuckLake metadata) + S3 Parquet (data) -- atomic commit, no compaction,
                                                        no views, no staging, no outbox
```

Invariants (carry forward unchanged): warehouse-as-source-of-truth; local JSONL files are
read caches only; single portal write surface (file_rec / update_rec / sync); SCD2
append-only with status=superseded as the deletion model; loud failure over silent
degradation (Decision 55).

New invariants (introduced by this program):
- **I-1 Single backend**: OPS_STORAGE_BACKEND flag deleted; there is no second path to keep honest.
- **I-2 Keyspace ownership**: only the writer mints entity ids (rec-NNN, dec-NNN), allocated
  in the same Neon transaction as the insert. No DynamoDB counter, no client-side ids.
- **I-3 No SQL across the read boundary**: query_ops (caller-supplied SELECT) is removed;
  reads are named verbs with typed params, registered server-side in the reader Lambda.
- **I-4 No write buffering**: a failed write fails loudly at the call site. There is no
  outbox of any kind. (Premise P1 makes the buffered case worthless; the rec text always
  survives in the session transcript.)

## Phases (each = one IMPLEMENTATION plan via /plan; STRATEGIC remains suspended)

### Phase 1 - recs sole-backend + read-boundary hardening
Bundles: rec-2170, rec-2150, rec-2151, rec-2153 (and rec-2120/2121 if investigation shows
the ci-rca log-fetch guard from PLAN-ducklake-recs-cutover-completion did not land/work).
- Delete the pending outbox + drain_pending; file_rec loud-fails when it cannot complete.
- Delete OPS_STORAGE_BACKEND and every iceberg-backend branch for recs (make_reader
  simplification; DuckDBIcebergReader remains ONLY for the deferred tables until Phase 3).
- Replace purge_postmortems_for's Athena DML with status=superseded via the portal
  (SCD2 deletion model); archive scripts/cleanup_ops_rec_orphans.py (targets a dropped view).
- Read verbs (fixes rec-2170): reader Lambda gains a named-verb registry replacing
  query_ops; initial verbs: open_recs, rec_by_id, ci_rca_open, ci_rca_since,
  forward_fix_recursion, budget_bypass_recent, count_by_status. current_state row_filter
  either passes {column, value} structurally or is removed in favour of verbs. Client
  call sites (preflight x6, portal, sync_ops, DQ runner) move onto verbs.
- CI reader access: grant/verify ssm:GetParameter (/agent-platform/ducklake/*) and
  lambda:InvokeFunctionUrl on the reader for agent-platform-github-ci-branch/-pr roles;
  DQ recs checks then execute in CI (closes rec-2150/2151/2153 at root cause).
- Preflight: remove the telemetry Athena health check (stub returning "not-migrated" with
  zero queries) until Phase 4; reclaim the dead polling minutes.
- Drop the frozen Iceberg recs table + Glue entries + remaining recs references in
  schema_integrity / validate lints (recs-specific OpsWriter guards become dead and are
  removed WITH the OpsWriter recs path itself).
- Contracts: AGENTS.md (rollback clause, outbox role), read-engine.yaml, ops-data-store.md.
- Lambda artifacts affected: ducklake_reader (verb registry) -> build + deploy + smoke (V3).
  Terraform: Iceberg recs table drop is a DESTROY -> human-gated manual apply.

### Phase 2 - writer-owned ID allocation
- ducklake_writer gains file_ops: allocate next id from a counters table in the Neon meta
  schema INSIDE the insert transaction; return the id. Seed counter from
  max(DynamoDB counter value, max id in DuckLake current) with a one-shot migration step.
- write_ops gains require-absent semantics for creates (or file_ops becomes the only
  create path and write_ops is demoted to backfill-only).
- Portal file_rec: drop _next_id; one remote call; id comes back in the response.
- update_rec unchanged (already require-exists).
- The recommendations DynamoDB counter is retired logically (table destroy waits for
  Phase 3 when the decisions counter also moves).
- Lambda artifacts: ducklake_writer -> build + deploy + smoke (V3). EC8/churn smoke
  re-run (single-write unit now includes allocation).

### Phase 3 - remaining ops tables + Athena ops estate demolition
- field_semantics.yaml already declares ops_decisions, ops_priority_queue,
  ops_session_log, ops_execution_plans: create them on DuckLake (create_ops_tables),
  re-run the DECISIONS.md -> ops_decisions ETL (premise P3), start priority_queue /
  session_log / execution_plans EMPTY (premise P2; executor is paused per CD.17).
- Repoint every deferred-table read: sync_ops pull, portal decisions fetch/update,
  preflight priority-queue + _get_latest_decision_ts, rec-curator preload.
- Decisions id allocation moves into the writer (completes I-2); DynamoDB counters
  table destroyed.
- Demolish: OpsWriter, sync_ops Athena fallback + ALL _coerce_athena_* VarChar coercion,
  ops_compaction Lambda + schedule, ops_decisions_current / ops_priority_queue_current
  views (T2.7 completion), iceberg_tables.tf, AthenaViewsVerifier, the
  warehouse-write-source validate lints that police the now-impossible split-brain.
- Terraform: multiple DESTROYs -> human-gated manual apply session.

### Phase 4 - telemetry on DuckLake (clean slate)
- New telemetry tables defined in field_semantics.yaml; writes via ducklake_writer from
  the telemetry hooks; preflight health check re-enabled against the reader.
- No migration: the work-account Athena telemetry data is unreachable/dead (premise P2).
- Scope intentionally thin here; Phase 4 gets its own intent refinement once Phases 1-3
  land and observed write volumes are known.

## Decision entry (DRAFT for DECISIONS.md - requires owner ratification)

> Decision 84: DuckLake is the sole ops-store backend; the Athena/Iceberg ops estate is
> retired without data migration (all Athena-resident ops data declared discardable;
> ops_decisions re-created from DECISIONS.md). The offline outbox and OPS_STORAGE_BACKEND
> rollback flag are removed (CC-web-only operation; loud failure replaces buffering).
> Entity ids are allocated by the ducklake_writer atomically with the insert, retiring the
> DynamoDB counters table. The read boundary accepts named verbs only; caller-supplied SQL
> (query_ops) is removed. Supersedes the Decision 81 cl.7 rollback clause and the CD.8/
> CD.15 Athena escape hatch FOR OPS TABLES (market-data engine choice unaffected).

## Risk register

| Risk | Mitigation |
|------|------------|
| Neon catalog is the single metadata authority (free tier, scale-to-zero). | Already mitigated for reads (cold-resume retry). Add a catalog backup step to ducklake_maintenance (nightly pg_dump or Neon branch snapshot) in Phase 1; data files are already durable in S3. |
| Loud-fail with no buffer: a writer outage blocks rec filing. | Acceptable for a sole-dev platform; the rec content survives in the session transcript and can be re-filed. Outage visibility is the point (Decision 55). |
| Counter seed race during Phase 2 cutover. | One-shot seed = max(DynamoDB, DuckLake max id) executed inside the writer deploy window; write_ops require-absent makes a double-issue loud, not silent. |
| Named-verb registry too rigid for future reads. | Verbs are data (registry in the reader), adding one is a small PR + redeploy; this friction is the feature (pre-established queries are reviewable). |
| ci-rca volume during the transition. | Phase plans bundle the open DQ recs; the ci-rca hard block does not bind because the work is directly related to the open recs. |

## Out of scope

- Market-data lakehouse engine choice (future; the Athena retirement here is ops-tables only).
- Executor re-enable (CD.17) and STRATEGIC plan re-enable (T4.2) - unchanged by this program.
- The deep-frozen .github/prompts/ and .github/agents/ artefacts.
