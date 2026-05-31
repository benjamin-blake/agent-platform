# Plan

## Intent
Stand up a scale-honest, engine-agnostic DuckDB-on-Iceberg read layer and route the live
operational read hot-paths through it, dropping Athena from the operational read path (retained
only as escape hatch). The 722-row ops store is the proving ground; the real deliverable is the
**reference read pattern** the product's billions-of-rows market-data path will be modeled on
(NS.1: storage durable, compute interchangeable). Brings roadmap item T2.5 forward and broadens
it from "swap the (stub) query Lambda internals" to "build the shared reader the future T0.7c
query Lambda will import."

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-duckdb-read-path-swap.md

## Phase
Platform roadmap T2 (Full state migration to personal account). T2.5 "DuckDB swap on read paths",
brought forward ahead of the unbuilt query Lambda (T0.7c is a 501 stub).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/common/iceberg_reader.py` | Create | Engine-agnostic `Reader` protocol + `DuckDBIcebergReader` implementation: pyiceberg GlueCatalog resolution, predicate/projection pushdown into `.scan()`, snapshot pinning for reproducibility, and a `current_state()` helper that inlines the SCD2 qualification the `_current` views encode. Designed so the T0.7c query Lambda imports it unchanged. |
| `scripts/sync_ops.py` | Modify | Route `_pull_single_table` (L254) + `_rebuild_local_cache` (L350) reads through `IcebergReader.current_state(table)` instead of `SELECT * FROM agent_platform.<table>_current` via boto3 Athena. Athena retained as fallback. |
| `scripts/ops_data_portal.py` | Modify | Route `_fetch_rec_from_athena` (L363) + `_fetch_decision_from_athena` (L541) fetch-before-update reads through the reader. **Preserve Decision 69**: read source-of-truth (Iceberg snapshot) and raise if unreachable; never read the destructible local cache. The `DELETE`-postmortems DML (L910) is OUT of scope (write path). |
| `scripts/session_preflight.py` | Modify | Route preflight read paths (`_count_recommendations_athena` L435, `read_priority_queue` L592, CI-RCA / recursion / budget reads) through the reader. Priority-queue keeps its correlated-subquery semantics (Decision 70), NOT ROW_NUMBER. Preserve graceful degradation (empty/unreachable tables -> exit 0 + warning). |
| `requirements.txt` | Modify | Add `duckdb` and `pyiceberg[glue,duckdb]` (pin latest stable at implement time). |
| `pyproject.toml` | Modify | Mirror the dependency additions if it pins runtime deps. |
| `docs/contracts/read-engine.yaml` | Create | Engine-choice contract: catalog resolution, current-state qualification, snapshot pinning, predicate pushdown, the Athena escape-hatch policy, the interim direct-engine-exposure note (engine-hiding restored when T0.7c/T0.8 verbs land), and the **materialization escalation trigger** for high-row-version tables (the product-scale path). |
| `tests/test_iceberg_reader.py` | Create | Unit tests (pushdown args, current-state qualification, priority-queue semantics, snapshot pinning) + real-warehouse parity tests (DuckDB vs Athena `_current`, row-for-row, on a pinned snapshot). |
| `tests/test_sync_ops.py` | Modify | Cover the rerouted reader branch in `_pull_single_table` / `_rebuild_local_cache` (required by `test_coverage_checker` per-file 100% on modified lines). |
| `tests/test_ops_data_portal*.py` | Modify | Cover the rerouted reader branch in `_fetch_rec_from_athena` / `_fetch_decision_from_athena`, including the Decision-69 raise-on-unreachable path. |
| `tests/test_session_preflight.py` | Modify | Cover the rerouted reader branches and graceful-degradation path. |

## Bundled Recommendations
None.

## Infrastructure Dependencies (if applicable)
No `.tf` files in scope. No Terraform apply required.

**Lambda note (DEFERRED, Decision 67 / CD.16):** `src/common/iceberg_reader.py` is bundled into
Lambda deploy zips by the current whole-`src/` copytree (`scripts/build_lambda.py`), so a build is
nominally implicated. Per Decision 67 the Lambda-deploy path is frozen; per CD.16 a deploy is only
*required* for Lambdas a plan actually modifies. No currently-deployed Lambda imports this module,
so nothing redeploys. Execution includes a DEFERRED marker in lieu of an active deploy step; the
module is exercised live via the rerouted `scripts/` consumers, not via Lambda, so verification is
complete without a deploy.

## Acceptance Criteria
- [ ] `src/common/iceberg_reader.py` defines an engine-agnostic `Reader` protocol and a
      `DuckDBIcebergReader` implementation; the interface is shaped so an Athena-backed sibling
      implementation could satisfy it without changing call sites (CD.8 engine-interchangeability).
- [ ] Tables resolve through pyiceberg `GlueCatalog` by identifier (`agent_platform.<table>`); no
      hardcoded `metadata.json` paths anywhere in the reader.
- [ ] Predicate + projection pushdown: filtered/column-scoped reads pass `row_filter=` and
      `selected_fields=` into `.scan()` BEFORE Arrow materialization (proven by a unit test on the
      scan arguments, not by post-filtering in DuckDB).
- [ ] `current_state()` inlines the SCD2 qualification for `ops_recommendations` and `ops_decisions`
      (`QUALIFY ROW_NUMBER() OVER (PARTITION BY <pk> ORDER BY last_updated_timestamp DESC) = 1`);
      `ops_priority_queue` reproduces its correlated-subquery semantics (Decision 70), NOT ROW_NUMBER.
- [ ] `snapshot_id` parameter supported; default = latest snapshot; a pinned read returns identical
      bytes across two invocations (reproducibility).
- [ ] Real-warehouse parity: for `ops_recommendations`, `ops_decisions`, and `ops_priority_queue`,
      the DuckDB reader output equals the Athena `_current` view output row-for-row on a pinned
      snapshot (against the live 722-rec / 38-decision warehouse).
- [ ] Decision 69 preserved: `ops_data_portal` fetch-before-update reads the warehouse and raises a
      clear error if the warehouse is unreachable; it never falls back to the local JSONL cache.
- [ ] `session_preflight` degrades gracefully: empty or unreachable ops tables produce exit 0 + a
      surfaced warning (T2.5 exit criterion; required for future Codespace preflight).
- [ ] Athena retained as escape-hatch fallback; `docs/contracts/read-engine.yaml` documents the
      engine choice, escape-hatch policy, interim direct-exposure note, and the materialization
      escalation trigger for high-row-version tables.
- [ ] Reader credential resolution honours the named `agent_platform` profile when present and falls
      back to boto3's default chain under CI OIDC; parity tests pass on the GitHub-hosted runner.
- [ ] `duckdb` + `pyiceberg[glue,duckdb]` added to `requirements.txt`; `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Reader unit tests exercise real code paths (pushdown args, current-state SQL, priority-queue semantics, snapshot pinning) | `bin/venv-python -m pytest tests/test_iceberg_reader.py -v` | All pass; pushdown test asserts `.scan()` received `row_filter`/`selected_fields`; priority-queue test asserts correlated-subquery (not ROW_NUMBER) | Reader materializes full table then filters, or wrong dedup form -> fix scan/qualify logic |
| 2 | [pre-deploy] | Real-warehouse parity: reader output vs Athena `_current` view, row-for-row, on a pinned snapshot | `bin/venv-python -m pytest tests/test_iceberg_reader.py -k parity -v` | For each of the 3 ops tables, DuckDB rows == Athena view rows (count + per-row field equality) | Any mismatch -> dedup/order/timestamp handling diverges from view semantics (check Decision 56/70) |
| 3 | [pre-deploy] | Snapshot-pin reproducibility | `bin/venv-python -c "from src.common.iceberg_reader import DuckDBIcebergReader as R; r=R(); a=r.current_state('ops_recommendations', snapshot_id=(s:=r.latest_snapshot('ops_recommendations'))); b=r.current_state('ops_recommendations', snapshot_id=s); print('REPRODUCIBLE' if a==b else 'NONDETERMINISTIC')"` | Prints `REPRODUCIBLE` | Prints `NONDETERMINISTIC` -> add explicit ORDER BY / fix snapshot pinning |
| 4 | [pre-deploy] | End-to-end ops sync through the rerouted reader | `bin/venv-python -m scripts.sync_ops sync` | Exits 0; pulls expected row counts (722 recs / 38 decisions) into local cache; no Athena view dependency on the read | Non-zero exit or wrong counts -> reroute regression |
| 5 | [pre-deploy] | Preflight smoke through the rerouted reader, including graceful degradation | `bin/venv-python -m scripts.session_preflight && echo PREFLIGHT_OK` | Exits 0; rec counts match warehouse; prints `PREFLIGHT_OK`; with a transiently empty/unreachable table, still exits 0 with a warning | Crashes on empty/unreachable table -> add graceful fallback |
| 6 | [pre-deploy] | Portal fetch-before-update read on a known rec id, asserting source-of-truth-or-raise (Decision 69) | `bin/venv-python -c "from scripts.ops_data_portal import _fetch_rec_from_athena as f; r=f('rec-001'); print('FETCHED' if r else 'NONE')"` (substitute a real open rec id) | Returns the rec from the warehouse via the reader; raises (not silently returns cache) if warehouse unreachable | Returns cached row when warehouse down -> violates Decision 69; fix to raise |
| 7 | [pre-deploy] | Full presubmit identical to CI | `bin/venv-python -m scripts.validate` | PASS (lint/format/schema/tests/coverage) | Any failure -> address before merge |
| 8 | [deferred] | Lambda build/deploy of the shared module | `# DEFERRED: bin/venv-python -m scripts.build_lambda --deploy (pending Decision 67 reversal; no deployed Lambda imports iceberg_reader.py, so no redeploy needed)` | Recorded as deferred; module exercised live via steps 4-6 | N/A |

## Constraints
- Read paths only. All write paths are OUT of scope: `ops_writer` `CREATE OR REPLACE VIEW` refresh,
  the `awswrangler.to_iceberg()` compaction pipeline, and the `ops_data_portal` `DELETE`-postmortems
  DML. These move in a follow-on plan.
- Athena is retained (CD.8/CD.15 escape-hatch clause). No `_current` view deletion in this plan;
  view retirement is roadmap item T2.7 (depends on T2.5).
- Warehouse-as-source-of-truth invariant: the reader reads Iceberg snapshots; it never restages from
  a local cache (CLAUDE.md lakehouse rule). Read caches stay downstream of the warehouse.
- **CI credential chain:** the reader's pyiceberg `GlueCatalog` / boto3 resolution MUST resolve the
  named `agent_platform` profile when present AND fall back to boto3's default chain when it is not
  (GitHub-hosted CI uses OIDC with no named profile). The parity tests must pass on the OIDC runner,
  not only locally (per the CI-runner credential gotcha in PROJECT_CONTEXT).
- Single Portal Invariant (Decision 69): portal reads source-of-truth or raises.
- No rescue agents or workaround loops (Decision 55). On unrecoverable V3 failure, stop and RCA.
- No emojis; ASCII hyphens; Python 3.12+, type hints, ruff line length 127; `bin/venv-python` for all
  Python invocations.

## Context
- **Why now (product framing):** This reader is the reference implementation for the product's
  billions-of-rows market-data read path, not just the 722-row ops store. Scale-honesty (engine-
  agnostic interface, predicate/projection pushdown, catalog resolution, snapshot-pinned
  reproducibility, a documented materialization-escalation trigger) is the actual deliverable; the
  ops store is the proving ground.
- **Live state:** T2.1 (full TF re-deploy) and T2.2 (data import) are already complete out-of-order;
  the personal account holds 722 recs + 38 decisions in Athena/Iceberg. The query Lambda
  (`src/lambdas/query/handler.py`) is a 501 stub (T0.7c unbuilt), so today's reads go through ~8
  scattered direct-boto3/subprocess Athena call sites, not through any Lambda.
- **Decisions to cite:** CD.8 (DuckDB = default read engine; engine hidden behind verbs),
  CD.15 (typed query Lambda; Athena `_current` views retired in new account; SCD2 dedup is
  reader-internal; Athena escape hatch for large scans), CD.16 / Decision 67 (Lambda-deploy freeze /
  per-Lambda gating -> DEFERRED step), Decision 48 (V3 = behavioural acceptance, never structural),
  Decision 56 (SCD2 `ROW_NUMBER` current-state semantics), Decision 70 (`ops_priority_queue_current`
  uses a correlated subquery, NOT ROW_NUMBER), Decision 69 (Single Portal Invariant: read
  source-of-truth or raise). Downstream consumer: T2.7 (view retirement).
- **Decision flags accepted (all NOTE, from the decision-scout gate):**
  1. CD.15/T2.5 site the reader in `src/lambdas/query/`; we site it in `src/common/` so the unbuilt
     T0.7c Lambda imports the shared module rather than re-housing it. Interim, intended.
  2. CD.8 says the engine is hidden behind verbs; routing `scripts/` directly at the reader exposes
     it as a pre-Lambda bridge. Engine-hiding is restored when T0.7c/T0.8 verbs land. Documented in
     `read-engine.yaml`.
  3. CD.24 (per-Lambda manifests) will retire the whole-`src/` copytree the DEFERRED rationale rests
     on; CD.24 is still `pending`, so the copytree holds today. No action.
- **Fast-follow plans (named, not in this scope):** (a) write-path swap (view refresh + `to_iceberg`
  compaction + DELETE DML off Athena/awswrangler); (b) T2.7 `_current` view retirement once all reads
  are DuckDB; (c) T0.7c query Lambda wiring that imports this reader.
- **Branch:** planning on `claude/platform-roadmap-planning-W52wx`; main 0 behind / 0 ahead at
  planning time (no Scope-overlap divergence).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (in particular 48, 55, 56, 69, 70; CD.8, CD.15, CD.16)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Add `duckdb` and `pyiceberg[glue,duckdb]` to `requirements.txt` (and mirror in `pyproject.toml`
   if it pins runtime deps); install into the venv. Pin latest stable.
2. Create `src/common/iceberg_reader.py`:
   - A `Reader` `typing.Protocol` (engine-agnostic verbs: `current_state`, `query`, `latest_snapshot`).
   - A `DuckDBIcebergReader` implementation: pyiceberg `GlueCatalog` resolution by `agent_platform.<table>`
     identifier; `.scan(row_filter=, selected_fields=, snapshot_id=)` with predicate/projection
     pushdown; Arrow handed to DuckDB (`pyiceberg.to_duckdb` or `con.register`); SQL executed with
     bound params (no f-string interpolation of values).
   - `current_state(table, partition_by, order_by="last_updated_timestamp")` building the `QUALIFY
     ROW_NUMBER()` query; a priority-queue path reproducing the Decision 70 correlated-subquery form.
   - Graceful behaviour when a table is empty/unreachable (return empty + signal, do not crash) to
     support preflight degradation.
3. Reroute `scripts/sync_ops.py` `_pull_single_table` + `_rebuild_local_cache` to call
   `reader.current_state(table)` instead of the Athena `_current` view query. Keep Athena as a
   fallback path behind a clear branch.
4. Reroute `scripts/ops_data_portal.py` `_fetch_rec_from_athena` + `_fetch_decision_from_athena` to
   the reader, preserving Decision 69 (read warehouse or raise; never the local cache). Leave the
   DELETE DML untouched.
5. Reroute `scripts/session_preflight.py` read paths to the reader, preserving graceful degradation
   and the Decision 70 priority-queue semantics.
6. Create `docs/contracts/read-engine.yaml` documenting engine choice, catalog resolution,
   current-state qualification, snapshot pinning, predicate pushdown, the Athena escape-hatch policy,
   the interim direct-exposure note, and the materialization escalation trigger for high-row-version
   tables.
7. Create `tests/test_iceberg_reader.py` with the unit tests and the real-warehouse parity tests,
   AND update the three existing test modules (`tests/test_sync_ops.py`,
   `tests/test_ops_data_portal*.py`, `tests/test_session_preflight.py`) to cover the rerouted reader
   branches and the Decision-69 raise path, so `test_coverage_checker` (VP step 7) passes.
8. **Execute Verification Plan** -- run each step. Loop until pass. If a V3 step fails unrecoverably,
   stop and analyze root cause (Decision 55); do not patch around it.
9. Report: what was implemented, verification results (including parity row counts), and the named
   fast-follow plans.
