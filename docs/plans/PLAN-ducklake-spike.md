# Plan

## Intent
De-risk a candidate DuckLake adoption with a narrow, ISOLATED end-to-end spike on one throwaway
table (DuckDB + the `ducklake` extension writing to a dedicated S3 prefix behind a file catalog,
under serialised/competing writers), and in the same stroke close the verification gap that
`duckdb` is declared but not installed -- so today's DuckDB-on-Iceberg read path silently degrades
to Athena every session. Spike-then-commit: prove the format on the real stack BEFORE the roadmap
commits to it (NS.1: storage durable, compute interchangeable). The 722-row ops store's format is
the question; this isolated table is the proving ground.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-spike.md

## Phase
Platform roadmap T2 (Full state migration to personal account). A pre-cursor de-risking spike for a
candidate DuckLake adoption: it EXTENDS T2.5 (the DuckDB read path) and, ONLY IF the spike returns
PROCEED, would inform a later supersession of the Iceberg/Glue + staging write path via the named
FP-A/FP-B follow-ons. This plan itself supersedes nothing and commits no format change. Builds
directly on `PLAN-duckdb-read-path-swap.md`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Modify | Fix the declared-but-uninstalled gap: pin `duckdb` to a known-good stable that supports the `ducklake` extension and ensure it actually installs into the venv (`import duckdb` currently raises `ModuleNotFoundError` despite `requirements.txt:13`). Investigate WHY it is absent in the CC-web container (stale venv / bootstrap not run / platform wheel). Scope-limited to `duckdb`; rec-1997's `pyiceberg` upper-bound pin is left to its own follow-up (tight-scope directive). |
| `src/common/ducklake_spike.py` | Create | A self-contained, Lambda-ready-but-locally-executed writer/reader: connect via DuckDB, `INSTALL ducklake; LOAD ducklake`, `ATTACH` a DuckLake catalog (DuckDB/SQLite file) whose `DATA_PATH` is the isolated S3 prefix `s3://agent-platform-data-lake/ducklake-spike/`; serialised single-writer append + read-back; a loud-fail guard that RAISES if `duckdb` is unavailable (never silent fallback). Imports NOTHING from `OpsWriter`/outbox/`ops_data_portal`; reads no `logs/` cache. Exposes a `handler`-shaped entrypoint for future FP-B reuse but is invoked via `bin/venv-python` for the spike. |
| `tests/test_ducklake_spike.py` | Create | V3 behavioural verification. Creds-free always-run: `TestDuckLakeGuard` (forced-missing `duckdb` raises, no silent fallback), `TestDuckLakeIsolation` (module touches only the spike prefix + dedicated catalog; imports no `OpsWriter`/outbox symbols). `@pytest.mark.integration` (real S3, mirror `TestWarehouseParity` skip): `TestDuckLakeSpikeE2E` (write >=50 throwaway rows, read back row-for-row), `TestDuckLakeSerialisedWrites` (two writers; final count == sum, no corruption), `TestDuckLakeInlining` (a small write leaves no orphan sub-threshold parquet). |
| `docs/ducklake-spike-findings.md` | Create | The spike's actual deliverable: a structured metrics block (works, write/read latency, catalog approach + cost, inlining behaviour, serialised-concurrency result, SCD2-reproduction observation, extension-install network risk) + an explicit `Recommendation: PROCEED` / `Recommendation: REVISE` verdict for the FP-A roadmap reconciliation, plus the documented Aurora DSQL future-migration aim. |

## Bundled Recommendations
None. (rec-1997 -- `duckdb`/`pyiceberg` upper-bound pins -- is adjacent because this plan pins
`duckdb` as part of its own install-fix work, but full resolution of rec-1997, including the
`pyiceberg` pin tied to the existing Iceberg reader, is left to a separate follow-up to honour the
tight-scope directive.)

## Infrastructure Dependencies (if applicable)
No `.tf` files in scope. No Terraform apply required. The isolated data prefix
(`s3://agent-platform-data-lake/ducklake-spike/`) lives under the EXISTING data-lake bucket and is
created on first write -- no new bucket/IAM. The spike catalog is a local DuckDB/SQLite file -- no
managed catalog DB is provisioned (that is the deferred Aurora DSQL aim, FP-A).

**Lambda note (DEFERRED, Decision 67 / CD.16):** `src/common/ducklake_spike.py` is swept into Lambda
deploy zips by the current whole-`src/` copytree (`scripts/build_lambda.py`), so a build is nominally
implicated. Per Decision 67 the Lambda-deploy path is frozen; per CD.16 a deploy is only *required*
for Lambdas a plan actually modifies. No currently-deployed Lambda imports this module and the spike
runs LOCALLY via `bin/venv-python`, so nothing redeploys. Execution carries a DEFERRED marker in lieu
of an active deploy step; the module is exercised live via the integration tests, not via Lambda.

## Acceptance Criteria
- [ ] `bin/venv-python -c "import duckdb; print(duckdb.__version__)"` succeeds and prints the resolved
      version -- the declared-but-uninstalled gap (`requirements.txt:13`, currently `duckdb>=1.5.3`) is
      closed and the cause of its absence in the container is fixed. (Step 1 decides whether to keep the
      `>=1.5.3` floor or tighten to an exact ducklake-capable pin; either choice satisfies this criterion.)
- [ ] `INSTALL ducklake; LOAD ducklake` succeeds in a DuckDB connection (extension available under the
      session's network policy; if not, that is itself a recorded blocking finding for FP-A).
- [ ] Loud-fail guard: the read path RAISES a clear error when `duckdb` is unavailable -- proven by a
      test that forces the import to fail and asserts a raise, NOT a `None`/silent Athena fallback.
- [ ] `ducklake_spike` writes >=50 throwaway records to the isolated DuckLake table and reads them back
      row-for-row identical (count + per-field).
- [ ] Isolation proven: data lands ONLY under the `ducklake-spike/` S3 prefix + the dedicated catalog
      file; no write to `ops_recommendations`/`ops_decisions`/any Glue ops table; no `OpsWriter`/outbox
      call; no `logs/` cache read.
- [ ] Serialised concurrency: two competing writers append without catalog corruption or row loss
      (final row count == sum of both writers' appends).
- [ ] Data inlining observed: a small write leaves no orphan sub-threshold parquet (DuckLake inlines
      small changes), recorded in findings.
- [ ] `docs/ducklake-spike-findings.md` records works/latency/catalog-cost/inlining/concurrency/
      SCD2-repro/extension-network-risk AND an explicit `Recommendation: PROCEED` or
      `Recommendation: REVISE` for FP-A, plus the Aurora DSQL future-migration aim.
- [ ] `bin/venv-python -m scripts.validate` passes (lint/format/schema/tests/coverage).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | `duckdb` imports in the venv (closes the install gap) | `bin/venv-python -c "import duckdb; print(duckdb.__version__)"` | Prints a version; exit 0 | `ModuleNotFoundError` -> requirements/venv bootstrap did not install duckdb; fix install + investigate why declared-but-absent |
| 2 | [pre-deploy] | `ducklake` extension loads | `bin/venv-python -c "import duckdb; c=duckdb.connect(); c.execute('INSTALL ducklake'); c.execute('LOAD ducklake'); print('DUCKLAKE_OK')"` | Prints `DUCKLAKE_OK` | Extension missing/incompatible or download blocked by network policy -> pin duckdb to a ducklake-capable version; if network-blocked, record as a BLOCKING finding for FP-A (bundle the extension / allowlist `extensions.duckdb.org`) |
| 3 | [pre-deploy] | Loud-fail guard: missing `duckdb` raises, no silent fallback | `bin/venv-python -m pytest tests/test_ducklake_spike.py::TestDuckLakeGuard -v` | Pass; a clear `RuntimeError` is raised when the import is forced to fail (monkeypatched), not `None`/fallback | Silent degradation -> add an explicit raise at the read/connect boundary |
| 4 | [pre-deploy] | Isolation audit: no ops-table / `OpsWriter` / outbox / `logs/` contact | `bin/venv-python -m pytest tests/test_ducklake_spike.py::TestDuckLakeIsolation -v` | Pass; asserts the module imports no `OpsWriter`/outbox symbols and references only the `ducklake-spike/` prefix + dedicated catalog | Any ops-store contact -> isolation breach; fix before proceeding (Decision 50 / warehouse-as-source-of-truth) |
| 5 | [pre-deploy] | E2E write+read round-trip on the isolated table (real S3) | `bin/venv-python -m pytest tests/test_ducklake_spike.py::TestDuckLakeSpikeE2E -v` | Pass; >=50 records written then read back row-for-row identical; data under the spike prefix only | Mismatch -> writer/reader or catalog attach wrong; isolation breach -> fix prefix/catalog wiring |
| 6 | [pre-deploy] | Serialised concurrency: two writers append without loss/corruption | `bin/venv-python -m pytest tests/test_ducklake_spike.py::TestDuckLakeSerialisedWrites -v` | Pass; final count == sum of both writers' rows; no partial/corrupt snapshot | Lost rows/corruption -> serialisation not enforced; record as a finding + tighten the single-writer lock |
| 7 | [pre-deploy] | Inlining observation recorded | `bin/venv-python -m pytest tests/test_ducklake_spike.py::TestDuckLakeInlining -v` | Pass; a small write produces no orphan sub-threshold parquet (asserted by listing the prefix) | Tiny files proliferate -> record as a finding (inlining threshold tuning is an FP-A concern) |
| 8 | [pre-deploy] | Findings artefact present + carries a verdict | `test -f docs/ducklake-spike-findings.md && grep -Eq "Recommendation: (PROCEED\|REVISE)" docs/ducklake-spike-findings.md && echo FINDINGS_OK` | Prints `FINDINGS_OK` | Missing/empty -> author the findings from the VP results before completion |
| 9 | [pre-deploy] | Full presubmit identical to CI | `bin/venv-python -m scripts.validate` | PASS (lint/format/schema/tests/coverage) | Any failure -> address before merge |
| 10 | [deferred] | Lambda build/deploy of the bundled module | `# DEFERRED: bin/venv-python -m scripts.build_lambda --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal; no deployed Lambda imports ducklake_spike.py and the spike runs locally, so no redeploy needed)` | Recorded as deferred; module exercised live via steps 3-7 | N/A |

## Constraints
- **Isolation is the load-bearing constraint.** The spike writes ONLY throwaway test data to
  `s3://agent-platform-data-lake/ducklake-spike/` + a dedicated catalog file. It MUST NOT touch
  `ops_recommendations`/`ops_decisions`/any production Glue table, MUST NOT import or call
  `OpsWriter`/outbox, and MUST NOT read any `logs/` cache. This is what keeps the spike clear of
  Decision 50, the warehouse-as-source-of-truth invariant, and the Single Portal Invariant (Decision 69).
- This plan does NOT amend NS.1, CD.8, or CD.15, does NOT author a candidate decision, and does NOT
  migrate any production table. Roadmap reconciliation -- including the NS.1 "S3 + Iceberg" ->
  "S3 + open table format" generalisation -- is deferred to FP-A.
- Serialised single-writer only. Multi-writer concurrency is explicitly out of scope; the documented
  Aurora DSQL migration aim (findings + FP-A) covers the future multi-writer need.
- **Credentials + network:** the integration tests require the `agent_platform` profile (or CI OIDC)
  AND network access to `extensions.duckdb.org` for the `ducklake` extension. They skip cleanly when
  unavailable (mirror `TestWarehouseParity`); the guard/isolation tests always run. The `/implement`
  session MUST run with creds + extension-download network for the findings to be produced -- a blocked
  extension download is itself a recorded BLOCKING finding for FP-A, not a reason to fake the spike.
- The existing DuckDB-on-Iceberg reader (`PLAN-duckdb-read-path-swap`) is NOT modified except for the
  shared `duckdb` install fix in `requirements.txt`; do not duplicate that reader.
- No rescue agents or workaround loops (Decision 55). On unrecoverable V3 failure (extension won't load,
  catalog corrupts under serialised writes), STOP and record root cause as a finding; do not patch
  around it -- the finding feeds FP-A's go/no-go.
- No emojis; ASCII hyphens; Python 3.12+, type hints, `async` for I/O; ruff line length 127;
  `bin/venv-python` for all Python invocations.

## Context
- **Why now / spike-then-commit:** the human chose DuckLake (the SQL-catalog lakehouse format, v1.0
  April 2026) over a same-table Iceberg compaction or a market-data-first reshape, but de-risk-first:
  prove the format end-to-end on one isolated table before rewriting the roadmap around it. This plan
  is that spike.
- **Gap this also closes (confirmed live):** `duckdb` is declared (`requirements.txt:13`,
  `pyiceberg[glue,duckdb]` at :14) but `import duckdb` raises `ModuleNotFoundError` in the container.
  So `iceberg_reader.py`'s in-method `duckdb` import throws, `sync_ops._pull_via_reader` swallows it
  (returns `None` on any exception), and every session silently falls back to Athena -- with NO gate
  catching it. Steps 1-3 close this independent of DuckLake's outcome.
- **Builds on:** `PLAN-duckdb-read-path-swap.md` (the DuckDB-on-Iceberg reference reader; cite, do not
  duplicate). The spike reuses its engine-agnostic framing (NS.1) on the DuckLake format.
- **Decisions to cite:** Decision 48 (V3 = behavioural acceptance, never structural -- the e2e test
  writes+reads real data); Decision 50 (append-only ops store via Iceberg -- the spike does NOT touch
  this store; isolation keeps it clear; FP-A would supersede the format clause); Decision 56 (SCD2
  `ROW_NUMBER` current-state -- the spike OBSERVES whether DuckLake's append + read-dedup reproduces
  it); Decisions 51/69 (local-first outbox / Single Portal -- the spike explicitly does NOT route
  through `OpsWriter`/outbox); CD.8 (DuckDB default read engine -- DuckLake extends it); CD.15 (Athena
  escape hatch over Iceberg snapshots -- unaffected here; FP-A handles the "Athena cannot read
  DuckLake" tension via a DuckLake->Iceberg export); CD.9 (partition every table -- the throwaway
  table still adopts a partition strategy to stay representative); CD.16 / Decision 67 (Lambda-deploy
  freeze / per-Lambda gating -> DEFERRED marker); CD.24 (per-Lambda manifests will retire the
  whole-`src/` copytree the DEFERRED rationale rests on; still `pending`, so the copytree holds today).
- **Decision flags accepted (from the decision-scout gate -- all NOTE for the spike; the WARN/NOTE
  items concentrate on the FP-A follow-on this plan scopes OUT):**
  1. NS.1 names "S3 + Iceberg" as the durable format; DuckLake is a format change. NOTE for the spike
     (an isolated throwaway probe changes no principle). The NS.1 generalisation is an FP-A obligation,
     explicitly NOT done here.
  2. Decision 50 mandates the ops store IS Iceberg. The spike does not touch the ops store, so no live
     contradiction; the isolation boundary is the mitigation. FP-B (full migration) is BLOCK-class
     until FP-A ratifies a superseding decision.
  3. CD.15's Athena escape hatch cannot read DuckLake. The spike does not touch CD.15; FP-A must plan
     the DuckLake->Iceberg export mitigation.
  4. CD.24 will retire the whole-`src/` copytree the DEFERRED rationale rests on; still `pending`, so
     the copytree holds today. No action.
- **Catalog decision (human):** near-term serialised writes + a DuckDB/SQLite FILE catalog (~$0).
  Documented aim to migrate to AWS Aurora DSQL (serverless, scale-to-zero) when serialised writes
  become a bottleneck AND DSQL's Postgres-protocol compatibility matures enough to back a DuckLake
  catalog. Recorded in the findings artefact; an FP-A obligation; NOT built here.
- **ci-rca related-work deferral (REQUIRED -- rec-2026 is open):** rec-2026 (priority **Low**) proposes
  wiring four `verify_ci_workflow` guards into `validate.py`. This plan satisfies none of the same-file /
  same-Decision / same-failure-category conditions, so per the Related-Work Check a deferral rationale is
  logged. Precise non-block reason: the L5 planning hard-block (Decision 73 clause 4 / F.11) keys on
  `priority="critical"` source=`ci_rca` recs; rec-2026 is Low, so it does not trip the block. It is also
  substantively a CI-hardening follow-up rather than a diagnosis of a red main CI (main CI is green --
  run #94, commit 611ff5c), and the two Critical red-CI ci-rca recs (rec-2023, rec-2024) were verified
  resolved and closed this session. rec-2026 is unrelated to the data-lake spike and is deferred to its
  own follow-up plan (FP-D).
- **Enumerated follow-on plans (named, NOT in this scope):**
  - **FP-A DuckLake roadmap reconciliation** (V1 governance): author a candidate decision adopting
    DuckLake for the operational lakehouse; amend NS.1 (S3 + Iceberg -> S3 + open table format),
    CD.8, CD.15 (add the DuckLake->Iceberg export escape hatch); supersede the JSONL-staging +
    `ops_compaction` + `awswrangler.to_iceberg` write path (Decisions 50/51/56/69); retire the
    `ops_compaction` Lambda (`terraform/scheduled_agents.tf`, `build_lambda.py`,
    `src/data/handlers/ops_compaction_handler.py`) and note small-file compaction is handled by
    DuckLake inlining; document the Aurora DSQL future-migration aim. Gated on this spike's PROCEED.
  - **FP-B full ops/telemetry write-path migration to DuckLake** (V3): replace the `OpsWriter` staging
    path; swap the read path (`DuckDBIcebergReader` -> a DuckLake reader); Lambda deploy carries the
    Decision 67 DEFERRED marker. BLOCKED until FP-A ratifies.
  - **FP-C market_data write-path assessment** (separate; MERGE-upsert semantics differ from
    append-only ops).
  - **FP-D rec-2026** (the deferred CI-hardening) as its own small plan.
- **Branch:** planning on `claude/exciting-galileo-KBn8z`; HEAD 0 behind `origin/main` at planning
  time, no scope-file overlap (clean; no rebase-deferral needed).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (in particular 48, 50, 51, 55, 56, 69; CD.8, CD.9, CD.15, CD.16, CD.24)
- [ ] `PLAN-duckdb-read-path-swap.md` read (prior art -- do not duplicate the Iceberg reader)
- [ ] All files in Scope table located/confirmed-absent and the install gap reproduced
      (`bin/venv-python -c "import duckdb"` currently raises)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`requirements.txt` + venv:** pin `duckdb` to a known-good stable that supports the `ducklake`
   extension; ensure it installs into the venv and confirm `import duckdb` works; investigate and fix
   WHY it was declared-but-absent in the CC-web container. Do NOT broaden to rec-1997's `pyiceberg`
   pin (tight scope).
2. **Create `src/common/ducklake_spike.py`:** connect via DuckDB; `INSTALL ducklake; LOAD ducklake`;
   `ATTACH` a DuckLake catalog (DuckDB/SQLite file) with `DATA_PATH` = the isolated
   `s3://agent-platform-data-lake/ducklake-spike/` prefix; credential resolution mirrors
   `iceberg_reader` (named `agent_platform` profile when present, else boto3 default chain / OIDC);
   a CD.9 partition strategy on the throwaway table; a serialised single-writer `write_records()` and
   a `read_all()`/`current_state()`; a loud-fail guard that RAISES if `duckdb` is unavailable; a
   `handler`-shaped entrypoint for future FP-B reuse. Imports nothing from `OpsWriter`/outbox/
   `ops_data_portal`; reads no `logs/` cache.
3. **Create `tests/test_ducklake_spike.py`:** `TestDuckLakeGuard` + `TestDuckLakeIsolation` (creds-free,
   always run); `TestDuckLakeSpikeE2E`, `TestDuckLakeSerialisedWrites`, `TestDuckLakeInlining`
   (`@pytest.mark.integration`, real S3, skip cleanly without creds/extension-download network, mirror
   `TestWarehouseParity`).
4. **Run the integration tests in this creds-enabled session** and capture metrics (write/read latency,
   prefix file listing for inlining, concurrency result, whether DuckLake append + read-dedup
   reproduces the Decision-56 SCD2 current-state).
5. **Author `docs/ducklake-spike-findings.md`** from the VP results: a structured metrics block +
   an explicit `Recommendation: PROCEED` / `Recommendation: REVISE` verdict for FP-A + the Aurora DSQL
   future-migration aim + any BLOCKING finding (e.g. extension download blocked by network policy).
6. **Execute Verification Plan** -- run each step. Loop until pass. If a V3 step fails unrecoverably,
   STOP and record root cause as a finding (Decision 55); do not patch around it -- the finding feeds
   FP-A's go/no-go.
7. **Report:** what was implemented, verification results (latency, inlining, concurrency, SCD2-repro),
   the findings verdict, and the named follow-on plans (FP-A/B/C/D).
