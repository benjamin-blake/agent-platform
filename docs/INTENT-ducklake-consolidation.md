# INTENT: DuckLake Consolidation - Single-Backend Ops Store

Status: RATIFIED as Decision 84 (2026-06-11). Implementation in progress on branch
claude/youthful-fermi-yglm7v (Phases 1-2 full; Phase 3 decisions/queue slice).
Revision 2: incorporates the two zero-context design reviews (adversarial architecture
+ fact-check feasibility, 2026-06-11). Material corrections from review are marked [R].
Consumed by: /plan sessions deriving follow-up plans; decision-scout; plan-critique.

## Ratified premises (stated by the owner, 2026-06-11)

| # | Premise | Consequence |
|---|---------|-------------|
| P1 | All dev sessions run on Claude Code on the web. There is no local dev environment. | "Offline" is not a real client state. Write buffering protects nothing and creates loss windows on ephemeral containers. |
| P2 | All data currently stored in Athena/Iceberg ops tables is discardable. | No reverse-migration or dual-read compatibility work. Tables are recreated on DuckLake, not migrated. [R] P2 EXPIRES at demolition: once the Athena copy is gone, DuckLake is the sole copy and the DR posture below becomes load-bearing. |
| P3 | ops_decisions is recreatable from docs/DECISIONS.md. | Decisions cutover = create table + author-and-run the DECISIONS.md ETL ([R] the previous backfill script was deleted; only the parser survives -- "re-run" was wrong). |
| P4 | The ops store is small (~900 rows recs, ~63 decisions) and single-writer in practice. | Engine-scale concerns do not apply. Market-data engine choice is OUT of scope. |

## Problem statement (verified by review; all six claims held)

1. The Iceberg "rollback" for recs is fictional -- and worse than stated [R]: with
   OPS_STORAGE_BACKEND=iceberg, recs WRITES still routed to DuckLake unconditionally while
   reads flipped to the frozen table: an incoherent read/write split, not a rollback.
2. Half-migrated read semantics caused the rec-2170 silent false zero (preflight open/aging/
   non-automatable counts read 0 since cutover). [R] A SEVENTH affected call site exists
   beyond the six preflight ones: the rec-curator preload in
   src/data/handlers/scheduled_agent_handler.py (same row_filter shape).
3. The offline outbox inverts its purpose on CC-web (gitignored pending files die with the
   container); observed live 2026-06-11 buffering a misconfiguration instead of loud-failing.
4. CI DQ checks error on the DuckLake path (rec-2150/2151/2153). [R] The CI OIDC roles
   ALREADY hold lambda:InvokeFunction + InvokeFunctionUrl + GetFunctionUrlConfig on
   reader+writer (terraform/personal/oidc.tf; applied at cutover), and CI's designed URL
   resolution is the GetFunctionUrlConfig fallback -- so the root cause is NOT missing
   grants and remains genuinely undiagnosed (rec-2153). Phase 1 carries a diagnosis step,
   not an IAM step.
5. Preflight burned ~minutes polling Athena telemetry tables dead since 2026-05-28.
6. The boundary does not own its keyspace: callers allocate rec-NNN via DynamoDB; write_ops
   has no require-absent gate, so a colliding create silently MERGEs.

## Target end-state

One warehouse (DuckLake on Neon catalog + S3 Parquet), one write authority that owns the
rec keyspace, one read boundary on named verbs, zero client-side buffering, zero
Athena/Iceberg in the ops path.

Invariants carried forward unchanged: warehouse-as-source-of-truth; local JSONL files are
read caches only; Single Portal write surface; SCD2 append-only with status=superseded as
the deletion model; loud failure over silent degradation (Decision 55).

New invariants (Decision 84; scoping refined per review [R]):
- **I-1 Single backend.** OPS_STORAGE_BACKEND deleted. DuckDBIcebergReader survives as an
  importable class ONLY for non-ops Iceberg surfaces (schema-integrity drift checks)
  until demolition.
- **I-2 Writer-owned keyspace -- scoped to rec-NNN.** file_ops allocates inside the write
  transaction: counter row updated in the SAME catalog commit (a guaranteed write-write
  OCC conflict is the serialization point; allocation sits INSIDE the retry loop and
  re-reads on retry; the counter is seeded ONLY by the serial create_ops_tables bootstrap
  from the history-table numeric max, scoped to the canonical ^rec-[0-9]+$ keyspace -- the
  hot path NEVER self-seeds, because a concurrent self-seed under snapshot isolation mints
  duplicate counter rows and duplicate ids, observed live 2026-06-11; write_ops advances
  the counter past caller-keyed canonical ids in the same transaction).
  Invocation idempotency: the portal mints a per-call ULID; the writer's in-transaction
  replay check returns the original allocation on a response-lost retry, so retries never
  double-file. Sanctioned exceptions: dec-NNN follows DECISIONS.md numbering (caller
  supplies decision_id; this very document pre-allocated "Decision 84"); test-/probe
  prefixes stay caller-keyed on write_ops.
  [R] Alternatives considered and rejected: max(id)+1 without a counter row (serialization
  depends on unverified MERGE-vs-MERGE same-key conflict detection under snapshot
  isolation); a native Postgres SEQUENCE via the baked postgres extension (separate
  transaction domain from the DuckLake commit -- not atomic, though gap-tolerant);
  moving the DynamoDB call into the writer (smallest protocol change but retains the
  second remote system and its IAM surface).
- **I-3 Named-verb read boundary -- STAGED.** Application reads use server-side registry
  verbs (no caller SQL). [R] query_ops is RETAINED for the DQ harness: its ~20 check
  shapes (including history-table checks that address ops_catalog.<hist> directly) are not
  expressible in the verb set; removal is a follow-up gated on a dq_check verb family or a
  caller-allowlist restriction. Structural {column, value} filters replace SQL-fragment
  row filters everywhere (rec-2170 fix), validated server-side against the table contract.
  Registry responses carry registry_version for skew diagnosis.
- **I-4 No write buffering -- per-table staging [R].** The recs and decisions pending
  outboxes are deleted NOW (their write paths are fully on the boundary). The OpsWriter
  staging outbox survives ONLY for not-yet-migrated writers -- telemetry emit, ops_session_log,
  ops_execution_plans -- and retires with them. "No outbox of any kind" is the Phase 3/4
  end state, not a Phase 1 fact. The deleted buffer is replaced by: transient-5xx retry in
  _ducklake_write (licensed by the idempotency key) + a writer-error CloudWatch alarm so
  loud failures reach a human, not just an unattended caller.

## Deployment protocol [R]

Every phase is additive-then-subtractive: deploy new Lambda actions ALONGSIDE old ones,
merge the client migration, confirm main runs the new clients, THEN remove old actions in
a follow-up deploy. Live consumers on main (ci-rca filing recs from GitHub Actions,
concurrent CC-web sessions) must never meet a Lambda that dropped an action they still
call. Rollback runbook: any revert of the portal to DynamoDB allocation MUST first reseed
the DynamoDB counter from the DuckLake max (reseed_recommendations_counter) or stale ids
will silently overwrite writer-allocated recs.

## Destructive-surface hardening (Phase 1, shipped) [R]

The boundary hardening is asymmetric without this: create_ops_tables(force_recreate) can
DROP a production table pair and ducklake_maintenance catalog_reinit defaulted to the
PRODUCTION meta-schema (a no-arg invoke nuked the live catalog). Both now require explicit
confirm parameters; catalog_reinit has no default schema. The smoke/probe actions operate
on the dedicated smoke tables and stay.

## Phases

### Phase 1 + 2 (implemented together this session)
Recs sole-backend; named verbs (open_recs, rec_by_id, recs_by_title_prefix, ci_rca_open,
ci_rca_since, forward_fix_recursion, budget_bypass_recent, count_by_status, decision_by_id,
decisions_max_updated, priority_queue_current); structural filters; outbox deletion (recs +
decisions); writer-owned rec ids via file_ops; purge-postmortems becomes SCD2 supersede;
telemetry preflight stub; destructive-action guards; DQ checks routed to DuckLake for the
three migrated tables; CI DQ root-cause diagnosis (rec-2150/2151/2153); contracts updated.
Lambda artifacts: ducklake_reader + ducklake_writer + ducklake_maintenance -> build +
deploy + smoke (V3, Decision 79). [R] The bundled-clause matters: these three bundle
src/common/ducklake_runtime.py, which changed.

### Phase 3 -- decisions/queue slice (implemented this session); remainder gated
ops_decisions: created on DuckLake + DECISIONS.md ETL (backfill_decisions_from_md;
idempotent caller-keyed upsert) + portal read/write repointed. ops_priority_queue: created
empty + reads repointed (Decision 70 semantics preserved INSIDE the priority_queue_current
verb -- [R] the generic latest-per-key projection would silently change queue semantics).
[R] NOT migrated here, per review: ops_session_log (T-1.9 proposes retirement -- migrate
OR retire per that decision, do not migrate blindly) and ops_execution_plans (live writers:
scripts/executor/plan.py, scripts/s3_log_store.py routing); OpsWriter itself is the LIVE
TELEMETRY write path (scripts/executor/telemetry.py, src/data/handlers/agent_telemetry.py)
and survives until Phase 4. The queue PRODUCER flow (rec-curator findings -> staging ->
ops_compaction S3 trigger) is dormant (Lambdas disabled) and repoints in T2.26.
GATE [R]: T2.26's hard start gate (rec-2113 pg_restore drill; the pgclient layer ships
pg_dump but NOT pg_restore, and the nightly dump is --format=custom while the drill used
plain SQL) is NOT engaged by this slice because every row written is externally
recreatable (DECISIONS.md) or empty -- but it BINDS the demolition step and any
non-recreatable migration. rec-2113 stays open and gating.

### Phase 3-demolition (post-merge, human-gated)
Athena DDL drops + null_resource removal in terraform/personal/main.tf ([R] NOT
terraform/iceberg_tables.tf -- that file is the retired work-account root; the live ops
estate is null_resource Athena DDL, and the live ops_compaction deployment is
terraform-managed in the retired work root, audit F-038); ops_compaction retirement
(manifest flip + runbook Section 5); DynamoDB counters table destroy (AFTER confirming no
rollback window is wanted: the reseed CLIs in scripts/sync_recommendations.py are the
rollback tool and retire last); schema_integrity Athena map prune; AthenaViewsVerifier
retire/repoint; sync_athena_to_pgvector.py delete (audit F-037). All destroys human-gated
(Decision 77 fail-closed guard).

### Phase 4 -- telemetry on DuckLake (own intent refinement)
New telemetry tables in field_semantics.yaml; OpsWriter.emit replaced by writer-boundary
writes; preflight health check re-enabled against the reader; the OpsWriter staging outbox
and the remaining VarChar coercion retire here. [R] Maintenance cadence: "no compaction"
in the end-state means no SCD2-dedup compaction JOB -- DuckLake file merge / snapshot
expiry (the existing ducklake_maintenance merge/GC with its circuit breaker) must be
POINTED AT the production catalog before telemetry's write volume lands; Neon storage and
S3 small-file growth get measured thresholds then.

## Risk register (corrected per review [R])

| Risk | Mitigation |
|------|------------|
| Neon catalog is the single metadata authority. | EXISTING ducklake_catalog_dr (nightly pg_dump --format=custom to a versioned DR bucket + >25h freshness alarm) -- the intent's earlier "add a backup step" was stale. The REAL gap is restore-side: rec-2113 (pg_restore missing from the layer; dump-format mismatch with the old drill). Fix gates demolition. |
| Loud-fail with no buffer: a writer outage blocks rec filing. | Transient-5xx retry (idempotent), CloudWatch alarm on writer errors, and for headless ci-rca the failure surfaces in the workflow log; acceptable for a sole-dev platform. "The rec text survives in the transcript" holds for interactive sessions only. |
| Counter seed/rollback races during the id-ownership cutover. | Serial bootstrap seeding via create_ops_tables (hot path never self-seeds); write_ops advances the counter past caller-keyed ids; require-absent belt check is terminal (never retried past); rollback requires reseed-from-DuckLake first (runbook step above). Main-branch writers continue on DynamoDB+write_ops until merge -- the residual same-second collision window is accepted (P4, sole writer in practice). |
| Named-verb registry rigidity / version skew. | Verbs are data in the schema module; adding one is a small PR + reader redeploy; responses carry registry_version; verb-consumer call sites distinguish unreachable (degraded signal) from empty. |
| Destructive actions on the write/maintenance surface (P2 expiry). | Explicit-confirm guards shipped (Phase 1); smoke actions are smoke-table-scoped. |
| ci-rca volume during transition. | The open DQ recs are bundled as this program's Phase 1 diagnosis; the ci-rca hard block does not bind related work. |

## Contract/doc surfaces updated (Phase 1-3 slice) [R: expanded per review]
AGENTS.md (source-of-truth section, Single Portal Invariant's DynamoDB sentence, outbox
roles, merge protocol untouched); docs/contracts/read-engine.yaml; docs/contracts/
ops-data-store.md; docs/PROJECT_CONTEXT.md (rollback-flag mentions); docs/runbooks/
ducklake-catalog-operations.md (flag mentions); ROADMAP-PLATFORM.yaml (T2.26 progress +
gate note; T2.27 closure; new T2.28 named-verb/id-ownership carrier); stale docstrings
(ops_storage_backend was claiming "default iceberg"). Deep-frozen .github/copilot-*.md
files are NOT edited (AGENTS.md freeze) -- [R] they still teach DynamoDB id authority and
outbox draining; the freeze exemption decision is left to the owner, flagged here.

## Out of scope
Market-data lakehouse engine choice; executor re-enable (CD.17); STRATEGIC plan re-enable
(T4.2); deep-frozen .github/prompts|agents artefacts.
