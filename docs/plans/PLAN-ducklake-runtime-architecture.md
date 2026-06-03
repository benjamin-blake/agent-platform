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

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add `state: pending` candidate_decision **CD.33** ("DuckLake ops runtime architecture"); annotate **OQ.7 / OQ.10 / OQ.11** with resolved directions citing CD.33 (questions stay open until the implementing tier item lands, per the established OQ-stays-open-until-implemented pattern); enrich **tier_items T2.17 / T2.18 / T2.19** (add CD.33 to `related_candidate_decisions`; pin the split, schema gate, OCC-retry, closed boundary, partition-prune smoke test); correct the stale `DEFERRED ... pending Decision 67 / CD.16 reversal` exit-criteria lines in T2.17/T2.18/T2.19 to active per-Lambda build/deploy/smoke-test steps per Decision 79 (CD.16 ratified). |
| `docs/DECISIONS.md` | Modify (ratification step only) | Append **Decision 80** ratifying CD.33 and resolving OQ.7/OQ.10/OQ.11. **Drafted below for review; applied only after approval**, alongside `ops_data_portal.file_decision` to allocate the `dec-XXXX` warehouse id. |

## Bundled Recommendations
None.

## Settled architecture (the six clauses CD.33 / Decision 80 encode)
1. **Three-artifact runtime split by access pattern** -- `ducklake_writer`, `ducklake_reader`,
   `ducklake_maintenance` -- justified by IAM-principal isolation (a write-scoped role vs a read-scoped
   role vs a maintenance role), independent scaling, and independent deploy/blast-radius, **NOT** by
   concurrency control (DuckLake's OCC handles that). This **supersedes CD.10's six-Lambda enumeration**
   (`log_rec`/`update_rec`/`log_decision`/`query`/`list_tools`/`maintenance`). CRITICAL framing: CD.10's
   six were *illustrative examples of needed verbs*, never a canonical surface. CD.33 commits **only** to
   the access-pattern split and the closed read/write boundary -- the verb/tool set behind `writer` and
   `reader` is deliberately **left extensible**. The architectural invariant is *path*, not *verb count*.
2. **Concurrency (resolves OQ.10 -> option c).** Concurrent writer invocations are allowed; the writer
   handles DuckLake snapshot-id conflicts via bounded **application-level OCC retry** (safe because ops
   writes are idempotent SCD2 appends keyed by id). No reserved-concurrency=1 and no SQS FIFO -- those
   serialise unnecessarily. `ducklake_maintenance` runs as a **singleton** (no overlapping maintenance
   runs; DDL / `ALTER`-table maintenance ops hard-abort on conflict, so they must not race).
3. **Portal surface = read + write categories only; sync eliminated.** DuckLake's atomic catalog-commit
   removes the JSONL outbox + drain/`sync` step entirely. A write is atomic **at the catalog-snapshot
   commit**: the writer stages Parquet to S3, then commits the snapshot in the RDS catalog transaction;
   readers never see the data until that commit lands, and Parquet files orphaned by an aborted commit are
   reclaimed by `delete_orphaned_files` (clause 5). The portal keeps its logical write verbs (`file_rec`,
   `update_rec`, `file_decision`) and read verb (`query`) -- "read + write only" means the *sync category*
   is gone, not that the verbs collapse to two functions. Structurally modelled on the recommendations
   portal. **Preserves the Decision 69 Single-Portal invariant**: all writes still transit
   `scripts/ops_data_portal.py`; only the transport beneath it changes (outbox -> DuckLake writer).
4. **Writer owns the schema-enforcement gate.** Every write is validated against the target table schema
   before the catalog commit; the writer is the single write chokepoint. No writer bypass exists.
5. **Maintenance = deterministic scheduled pipeline, not an agent surface.** The full sequence
   `flush_inlined_data -> merge_adjacent_files -> expire_snapshots -> cleanup_old_files ->
   delete_orphaned_files (+ optional rewrite)` runs on a schedule with **no LLM and no agent invocation**.
   Resolves **OQ.11 -> option b**: inlining stays ON (default threshold 10 rows); a **daily scheduled
   flush** via this pipeline moves inlined rows to S3. The catalog-only durability window between flushes
   is accepted and backed by RDS PITR (the catalog's DR baseline, per T2.16). `expire_snapshots` does NOT
   delete S3 objects -- `cleanup_old_files` + `delete_orphaned_files` must also be scheduled or S3 grows
   unboundedly.
6. **Closed read/write boundary (resolves OQ.7 -> option a).** Every read transits `ducklake_reader`;
   every write transits `ducklake_writer`; nothing reaches DuckLake out-of-band. There is **no Athena
   escape hatch** -- DuckLake has no Iceberg export and no external-engine reader, and the closed boundary
   is the point: we control and authorise every read and write. Ad-hoc large scans live behind the reader
   (add reader compute if DuckDB single-node memory binds) rather than via a parallel Iceberg mirror.
   **Partitioning**: ops tables partition by date (`day(last_updated_timestamp)`, per CD.9 via
   `ALTER TABLE ... SET PARTITIONED BY`) and cluster by id; a smoke test must prove a date-filtered query
   **actually prunes partitions** (not just parses), gating T2.17/T2.19.

OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal gate is the
documented default); CD.33 does not pre-empt it.

## Proposed CD.33 (state: pending) -- exact YAML to insert after CD.32
```yaml
  - id: CD.33
    title: DuckLake ops runtime architecture -- writer/reader/maintenance split, OCC-retry concurrency, closed read/write boundary
    detail: |
      Pins the ops DuckLake runtime architecture that Decision 78 (CD.31) deferred to T2.17-T2.19.
      Ratified by Decision 80 (this CD does NOT edit DECISIONS.md while pending; ratification lands via
      the log-decision path = Decision 80, mirroring CD.31 -> Decision 78).
      (1) Three-artifact split by access pattern -- ducklake_writer / ducklake_reader / ducklake_maintenance
          -- justified by IAM-principal + scaling + deploy isolation, NOT concurrency. Supersedes CD.10's
          six-Lambda enumeration, which was illustrative (examples of needed verbs), never canonical. CD.33
          commits ONLY to the access-pattern split + closed boundary; the verb/tool set behind writer and
          reader stays deliberately extensible. The invariant is path, not verb count.
      (2) Concurrency (OQ.10 -> c): concurrent writers + bounded application-level OCC retry in the writer
          (safe: ops writes are idempotent SCD2 appends keyed by id). NOT reserved-concurrency=1, NOT SQS
          FIFO. ducklake_maintenance runs as a singleton (DDL/ALTER ops hard-abort on conflict).
      (3) Portal surface = read + write categories only; the sync category is eliminated because DuckLake's
          atomic catalog-snapshot commit removes the outbox/drain step. A write is atomic at the catalog
          commit (Parquet staged to S3, then snapshot committed in the RDS catalog txn; readers see nothing
          until commit; aborted-commit Parquet is reclaimed by delete_orphaned_files). Logical write verbs
          (file_rec/update_rec/file_decision) + read verb (query) are retained. Decision 69 Single-Portal
          invariant PRESERVED -- all writes transit scripts/ops_data_portal.py; only the transport changes.
      (4) ducklake_writer owns the schema-enforcement gate: every write validated against the table schema
          before commit; single write chokepoint, no bypass.
      (5) ducklake_maintenance is a deterministic scheduled pipeline (flush -> merge -> expire -> cleanup ->
          delete_orphaned [+ rewrite]); NO LLM, NO agent invocation. Resolves OQ.11 -> b: inlining stays ON
          (threshold 10), daily scheduled flush; catalog-only durability window accepted, backed by RDS
          PITR. expire != delete: cleanup + delete_orphaned must be scheduled or S3 grows unboundedly.
      (6) Closed read/write boundary (OQ.7 -> a): every read via reader, every write via writer, nothing
          out-of-band. No Athena escape hatch (DuckLake has no Iceberg export / external reader; the closed
          boundary is the design goal -- every read and write is controlled and authorised). Ops tables
          partition by date (CD.9 via ALTER ... SET PARTITIONED BY) + cluster by id; a partition-prune
          smoke test gates T2.17/T2.19.
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
    enforcement_mechanism: "ducklake_writer schema gate + closed reader/writer boundary; partition-prune smoke test in T2.17/T2.19 exit criteria; per-Lambda CD.24 manifests."
```

## Proposed OQ annotations (append to the `notes` of each; questions stay open until implemented)
- **OQ.7** -- append: `Resolved direction (CD.33, pending Decision 80): option (a) -- no Athena escape hatch.
  The closed reader/writer boundary is the design goal; ad-hoc scans live behind ducklake_reader (scale reader
  compute if memory binds), not a parallel Iceberg mirror. Enacted at T2.19.`
- **OQ.10** -- append: `Resolved direction (CD.33, pending Decision 80): option (c) -- concurrent writers +
  bounded application-level OCC retry in ducklake_writer (ops writes are idempotent SCD2 appends keyed by id);
  ducklake_maintenance runs as a singleton. NOT reserved-concurrency=1, NOT SQS FIFO. Enacted at T2.19.`
- **OQ.11** -- append: `Resolved direction (CD.33, pending Decision 80): option (b) -- inlining ON
  (threshold 10), daily scheduled flush via the T2.18 maintenance pipeline; catalog-only durability window
  accepted, backed by RDS PITR. Enacted at T2.18.`

## Proposed tier-item enrichments
- **T2.17** -- add `CD.33` to `related_candidate_decisions`; add exit criterion
  `"Partition-prune smoke test: a date-filtered query against an ALTER-partitioned ops table demonstrably prunes partitions (CD.9 / CD.33)"`;
  **replace** the stale `"DEFERRED: build_lambda.py --deploy + smoke-test (pending Decision 67 / CD.16 reversal)"`
  with `"Per-Lambda build + deploy + smoke-test for ducklake_writer and ducklake_reader (V3 tier per CD.16; Decision 67 Lambda-deploy clause lifted by Decision 79)"`.
- **T2.18** -- add `CD.33`; tighten the inlining note to cite OQ.11 -> b (inlining ON + daily flush);
  add exit criterion `"Maintenance runs as a deterministic singleton pipeline with no LLM / agent invocation (CD.33 clause 5)"`;
  **replace** the stale DEFERRED line with the active per-Lambda build/deploy/smoke-test line for `ducklake_maintenance` (per Decision 79).
- **T2.19** -- add `CD.33`; add exit criteria
  `"ducklake_writer owns the schema-enforcement gate; no write path bypasses it (CD.33 clause 4)"`,
  `"Closed boundary verified: every ops read transits ducklake_reader, every write ducklake_writer; no out-of-band DuckLake access (CD.33 clause 6 / OQ.7)"`,
  and update the OQ.10 exit criterion to name the chosen mechanism (OCC retry + maintenance singleton);
  **replace** the stale DEFERRED line with active per-Lambda build/deploy/smoke-test (per Decision 79).

## Decision 80 -- DRAFT (filed via the log-decision path only after approval)
```markdown
## Decision 80: Ratify the DuckLake ops runtime architecture (CD.33); resolve OQ.7 / OQ.10 / OQ.11 (Decided)

**Status:** Decided
**Date:** 2026-06-03
**Warehouse ID:** dec-XXXX  (allocated by ops_data_portal.file_decision at filing)

**Problem:**
Decision 78 adopted DuckLake for the operational lakehouse but deferred the runtime architecture and four
open questions to T2.16-T2.19. T2.16 (RDS catalog) is complete; T2.17-T2.19 cannot proceed without a
ratified answer to: how the ops Lambdas are decomposed, how writer concurrency is enforced against
DuckLake's OCC (OQ.10), how inlining is flushed and where durability lives (OQ.11), whether an Athena
escape hatch survives DuckLake's lack of an external reader (OQ.7), and what the agent-facing portal
surface is. CD.10's earlier six-Lambda enumeration was illustrative, not a settled architecture.

**Decision:**
Ratify CD.33 as the authoritative DuckLake ops runtime architecture:
1. Three-artifact runtime split -- ducklake_writer / ducklake_reader / ducklake_maintenance -- partitioned
   by access pattern for IAM-principal, scaling, and deploy/blast-radius isolation, NOT for concurrency.
2. Supersede CD.10's six-Lambda enumeration. CD.10's verbs were illustrative; this decision commits only
   to the writer/reader/maintenance path split and the closed read/write boundary. The verb/tool surface
   behind writer and reader is deliberately left extensible and is NOT frozen by this decision.
3. Concurrency (OQ.10): concurrent writers + bounded application-level OCC retry in ducklake_writer (ops
   writes are idempotent SCD2 appends keyed by id). ducklake_maintenance runs as a singleton. Reserved-
   concurrency=1 and SQS FIFO are rejected as over-serialising.
4. Portal surface = read + write categories; the sync category is eliminated because DuckLake's atomic
   catalog-snapshot commit removes the outbox/drain step. Writes are atomic at the catalog commit; aborted
   commits leave orphan Parquet reclaimed by delete_orphaned_files. The Decision 69 Single-Portal invariant
   is PRESERVED -- all writes transit scripts/ops_data_portal.py; only the transport beneath it changes.
5. ducklake_writer owns the schema-enforcement gate -- the single, un-bypassable write chokepoint.
6. ducklake_maintenance is a deterministic scheduled pipeline (flush -> merge -> expire -> cleanup ->
   delete_orphaned [+ rewrite]) with no LLM / agent invocation. OQ.11 resolved: inlining ON (threshold 10)
   + daily scheduled flush; catalog-only durability window accepted, backed by RDS PITR.
7. Closed read/write boundary. OQ.7 resolved: no Athena escape hatch -- every read via the reader, every
   write via the writer, nothing out-of-band; controlling and authorising every read and write is the goal.
   Ops tables partition by date (CD.9) and cluster by id; a partition-prune smoke test gates T2.17/T2.19.
8. OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal default), not
   pre-empted here.

**Rationale:**
The split is by access pattern because that is what differs operationally -- a write principal that can
mutate the catalog, a read principal that cannot, and a maintenance principal that runs DDL -- so isolating
them isolates IAM blast radius and deploy risk; concurrency is handled by DuckLake's OCC, not by collapsing
the Lambdas. OCC retry beats reserved-concurrency=1 / SQS FIFO because ops writes are idempotent id-keyed
SCD2 appends, so a conflicted snapshot is safe to retry without serialising the whole write path. The
closed boundary (no Athena escape hatch) is not a limitation we tolerate but the design goal: a lakehouse
where every read and write is mediated and authorised. The agent verb surface is left open precisely to
avoid re-committing CD.10's mistake of enumerating a "final" surface prematurely.

**Related:** CD.33 (ratified here), CD.10 (six-Lambda enumeration superseded; was illustrative, state:pending),
Decision 78 (adopted DuckLake; deferred this runtime architecture), Decision 79 (per-Lambda deploy gating --
the DuckLake Lambdas deploy + smoke-test per CD.16), Decision 69 (Single-Portal invariant PRESERVED),
CD.15 (typed query reader -- refined), CD.8 (DuckDB engine -- unchanged), CD.9 (partitioning via ALTER),
CD.24 (per-Lambda manifests), OQ.7 / OQ.10 / OQ.11 (resolved), OQ.12 (left to T2.17).
```

## Acceptance Criteria
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses and loads via `scripts.platform_roadmap` after the edits.
- [ ] **CD.33** exists with `state: pending`, `gates: [T2.17, T2.18, T2.19]`, the six clauses, the
      "supersedes CD.10 (illustrative, not canonical) / agent surface NOT frozen" discipline point, and the
      CD.30-style "does not edit DECISIONS.md while pending; ratified via Decision 80" clause.
- [ ] **OQ.7 / OQ.10 / OQ.11** each carry a "Resolved direction (CD.33, pending Decision 80)" annotation;
      their `resolution_tier` is unchanged; they remain in `open_questions` (enacted at the implementing tier).
- [ ] **T2.17 / T2.18 / T2.19** include `CD.33`; the three stale `DEFERRED ... Decision 67 / CD.16` lines are
      replaced with active per-Lambda build/deploy/smoke-test criteria (Decision 79); the partition-prune,
      schema-gate, and closed-boundary criteria are present.
- [ ] **DECISIONS.md is UNCHANGED** until the ratification step (`git diff origin/main -- docs/DECISIONS.md`
      empty after the roadmap edits); Decision 80 is filed only after approval, via `file_decision`.
- [ ] `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected | Fix If |
|---|-------|--------|---------|----------|--------|
| 1 | pre | Roadmap loader accepts CD.33 + edits | `bin/venv-python -m scripts.platform_roadmap` | exits 0, no CD.33 error | conform to CandidateDecision (extra=forbid) fields |
| 2 | pre | Governance well-formed | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); cds={c['id']:c for c in d['candidate_decisions']}; assert cds['CD.33']['state']=='pending' and set(cds['CD.33']['gates'])=={'T2.17','T2.18','T2.19'}; ti={t['id']:t for t in d['tier_items']}; assert all('CD.33' in ti[x]['related_candidate_decisions'] for x in ('T2.17','T2.18','T2.19')); print('GOV_OK')"` | prints `GOV_OK` | add/fix the named element |
| 3 | pre | Stale DEFERRED markers removed | grep that no `pending Decision 67 / CD.16 reversal` remains in T2.17/T2.18/T2.19 | absent | replace remaining marker |
| 4 | pre | DECISIONS.md untouched by roadmap step | `git diff --quiet origin/main -- docs/DECISIONS.md && echo NOT_ENACTED` | `NOT_ENACTED` | revert; ratification is a separate approved step |
| 5 | pre | Full presubmit | `bin/venv-python -m scripts.validate` | PASS | address before merge |

## Constraints
- Roadmap edits stage CD.33 as `state: pending` and ENACT nothing in DECISIONS.md (CD.30/CD.31 precedent).
- Decision 80 is filed via `ops_data_portal.file_decision` ONLY after explicit approval following the
  zero-context review; it allocates the `dec-XXXX` warehouse id.
- Agent-first artefact design (CD.13/CD.14): edit the roadmap's native structures; no companion narrative doc.
- Conform to the `extra=forbid` CandidateDecision / TierItem schemas (no new top-level keys).
- No emojis; ASCII hyphens; ruff line length 127; `bin/venv-python` for all Python.

## Context
- **Why now:** Decision 78 deferred this runtime architecture to T2.16-T2.19; T2.16 is complete, so
  T2.17-T2.19 are unblocked pending a ratified architecture. The user settled the six clauses; CD.10's
  six-Lambda enumeration was illustrative and is superseded without freezing the agent surface.
- **Stale-marker correction:** Decision 79 lifted Decision 67's Lambda-deploy clause and ratified CD.16, so
  the `DEFERRED ... pending Decision 67 / CD.16 reversal` lines in T2.17/T2.18/T2.19 are factually stale and
  become active per-Lambda V3 build/deploy/smoke-test steps.
- **Single-Portal preservation:** Decision 69's primitive-level invariant is preserved -- the portal
  abstraction (`scripts/ops_data_portal.py`) is unchanged; only the transport beneath it changes (outbox ->
  DuckLake writer) at T2.19/FP-B.
- **Review:** decision-scout (contradiction scan vs DECISIONS.md + candidate_decisions) + a distributed-
  systems correctness lens (OCC retry, catalog-commit atomicity, inlining durability, partition prune) +
  an adversarial ops-risk lens (closed-boundary failure modes, DR, CD.10 supersession cleanliness).
