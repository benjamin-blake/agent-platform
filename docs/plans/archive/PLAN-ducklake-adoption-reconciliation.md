# Plan

## Intent
Persist a DuckLake adoption PROPOSAL and its unresolved decisions into the platform roadmap's native
structures, so the human can ratify a high-blast-radius storage-format pivot deliberately. Builds on
the merged DuckLake spike (PROCEED, PR #47) plus a deep read of the DuckLake v1.0 + DuckDB-Python docs
that surfaced adoption considerations the spike did not weigh. Advances NS.1 (storage durable, compute
interchangeable) by interrogating whether "Iceberg" should generalise to "open table format" for the
operational lakehouse, without presuming the answer.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-ducklake-adoption-reconciliation.md

## Phase
Platform roadmap T2 (Full state migration to personal account). Governance reconciliation triggered by
the T2.5 DuckDB read path + the DuckLake spike; scopes the proposed DuckLake adoption to the operational
lakehouse and stages the migration work (a future FP-B IMPLEMENTATION plan) behind ratification.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add a `state: pending` candidate_decision **CD.31** ("Adopt DuckLake for the operational lakehouse"), add **open_questions OQ.7-OQ.14** for the unresolved decisions, add **tier_items T2.16-T2.19** for the mechanical DuckLake work (all gated on CD.31), apply factual reconciliations to **CD.8 / CD.9 / CD.15**, add a `cost_projection.current_scale.breakdown` RDS line, and add a one-line CD.31 cross-reference note to **T2.4**. NS.1 text and DECISIONS.md are deliberately left UNCHANGED. |

## Bundled Recommendations
None. (The lone open ci-rca rec at session start, rec-2026, had its `verify_ci_workflow` wiring merged to
`main` via PR #49 / commit `a50e0e7`; it is unrelated to this governance scope -- see Context deferral.)

## Infrastructure Dependencies (if applicable)
No `.tf` files in scope; no Terraform apply in this plan. The RDS PostgreSQL catalog instance is provisioned
by a FUTURE tier_item (T2.16), not here. When that tier_item is implemented its `.tf` apply is governed by
Decision 35 (Terraform human-gate) as scoped by Decision 77 (PLATFORM-sandbox push-to-main auto-apply behind
the deterministic `scripts/terraform_apply_guard.py`, which fails closed on any destroy/IAM/trust change --
relevant to the RDS security-group + DB-credential/IAM-auth choices). No Lambda is built or deployed in this
plan; the future DuckLake Lambdas (T2.17-T2.19) carry Decision 67 / CD.16 deferred-deploy markers when authored.

## Acceptance Criteria
- [ ] `docs/ROADMAP-PLATFORM.yaml` still parses and loads through its roadmap loader after the edits
      (`scripts.platform_roadmap` enumerates tier_items + candidate_decisions without error).
- [ ] **CD.31** exists with `state: pending`, `filed_via: pending_log_decision_lambda`, a
      `supersedes_decisions` list naming Decisions [50, 56, 51, 69] (proposed-at-ratification, with per-Decision
      clauses), an "amends CD.8/CD.9/CD.15" note, `gates: [T2.16, T2.17, T2.18, T2.19]`, and -- mirroring CD.30 --
      an explicit statement that this roadmap edit does NOT touch DECISIONS.md and that the supersession + the
      NS.1 generalisation land at ratification via the log-decision path + the named FP-B follow-on. Scope is
      stated as ops/telemetry only, explicitly NOT the product `D.lake.*` / market-data Iceberg tier.
- [ ] CD.31 frames the RDS catalog as a durable **metadata store (Glue-analog), explicitly NOT a query engine**,
      so it reads as NS.1-consistent, and names **micro RDS PostgreSQL** as the chosen catalog backend with the
      Aurora DSQL aim dropped (unvalidated against DuckLake's PG12+/SQL-92/PK-based-OCC contract).
- [ ] **open_questions OQ.7-OQ.14** exist, each conforming to the existing flat schema
      (`{id, question, resolution_tier, notes}`), covering: Athena-hatch-with-no-Iceberg-export (OQ.7),
      catalog-backend confirmation/sizing/RDS-Proxy/credential (OQ.8), catalog durability/DR + SPOF (OQ.9),
      OCC writer-concurrency enforcement (OQ.10), inlining flush policy (OQ.11), version/upgrade policy (OQ.12),
      NS.1 generalisation (OQ.13), and catalog multi-tenancy with the future market-data catalog (OQ.14).
- [ ] **tier_items T2.16-T2.19** exist, schema-conformant, `status: not_started`, each `related_candidate_decisions`
      including CD.31: T2.16 RDS catalog provisioning (cites Decision 35 + Decision 77), T2.17 DuckLake Lambda
      runtime = VPC attach + extension bundling + egress lockdown + version pin (cites CD.10; asserts Function-URL/
      AWS_IAM ingress is unaffected by VPC egress), T2.18 DuckLake maintenance pipeline replacing ops_compaction
      (cites CD.29 for the cadence-mechanism choice; notes expire != delete), T2.19 DuckLake ops write/read
      migration = the FP-B plan (preserves Decision 69 Single-Portal invariant; Lambda-deploy DEFERRED per
      Decision 67 / CD.16; depends_on T2.16/T2.17/T2.18).
- [ ] **CD.8** detail notes DuckDB's native format becomes DuckLake; **CD.9** detail notes partitioning IS
      available but via `ALTER TABLE ... SET PARTITIONED BY` (metadata op), not `CREATE TABLE` DDL, and reconciles
      the "No unpartitioned-table path" absolute for the ops DuckLake tables; **CD.15** detail notes Athena cannot
      read DuckLake so the escape hatch becomes OQ.7. A one-line CD.31 cross-reference is added to T2.4.
- [ ] `cost_projection.current_scale.breakdown` gains an `rds_ducklake_catalog` line, flagged envelope-consistent
      with `line_items_not_enumerated` (which already names VPC/NAT) and net-cost-falling as the EC2 runner retires.
- [ ] **NS.1 text is UNCHANGED** and **DECISIONS.md is UNCHANGED** (`git diff origin/main -- docs/DECISIONS.md`
      is empty) -- nothing is enacted; everything consequential is staged as pending/open.
- [ ] `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Roadmap loader accepts the new candidate_decision + tier_items | `bin/venv-python -m scripts.platform_roadmap` | Exits 0; output enumerates tier_items incl. T2.16-T2.19 and does not error on CD.31 | Schema/parse rejection -> conform the entry to the existing CD/tier_item shape |
| 2 | [pre-deploy] | New governance entries are present + well-formed (behavioural load, not grep) | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); cds={c['id']:c for c in d['candidate_decisions']}; assert cds['CD.31']['state']=='pending' and set(cds['CD.31']['supersedes_decisions'])>={50,56,51,69}; oq={q['id'] for q in d['open_questions']}; assert {'OQ.7','OQ.8','OQ.9','OQ.10','OQ.11','OQ.12','OQ.13','OQ.14'}<=oq; ti={t['id'] for t in d['tier_items']}; assert {'T2.16','T2.17','T2.18','T2.19'}<=ti; assert 'rds_ducklake_catalog' in d['cost_projection']['current_scale']['breakdown']; print('GOVERNANCE_OK')"` | Prints `GOVERNANCE_OK` | AssertionError/KeyError -> the named element is missing or misshapen; add/fix it |
| 3 | [pre-deploy] | Nothing is enacted: NS.1 text + DECISIONS.md untouched | `git diff --quiet origin/main -- docs/DECISIONS.md && grep -q "S3 + Iceberg at every scale" docs/ROADMAP-PLATFORM.yaml && echo NOT_ENACTED` | Prints `NOT_ENACTED` (DECISIONS.md unchanged; NS.1 detail still reads "S3 + Iceberg at every scale") | DECISIONS.md changed or NS.1 reworded -> revert; this plan stages, it does not enact |
| 4 | [pre-deploy] | CD.31 mirrors the CD.30 no-DECISIONS.md-edit pattern | `grep -A40 "id: CD.31" docs/ROADMAP-PLATFORM.yaml \| grep -Eiq "does not touch DECISIONS.md\|via the log-decision" && echo MIRRORS_CD30` | Prints `MIRRORS_CD30` | Missing the explicit not-enacted clause -> add it (mirror CD.30 line 1129) |
| 5 | [pre-deploy] | Full presubmit identical to CI | `bin/venv-python -m scripts.validate` | PASS (lint/format/roadmap-schema/tests/coverage) | Any failure -> address before merge |

## Constraints
- **This plan PERSISTS a proposal; it ENACTS nothing.** CD.31 is `state: pending` (the established
  pre-ratification pattern). NS.1 text is unchanged; DECISIONS.md is untouched; no numbered Decision's status is
  changed. Supersession of Decisions 50/56/51/69 and any NS.1 rewrite land later, at ratification, via the
  log-decision path + the FP-B follow-on -- exactly mirroring CD.30 (line 1129).
- **Scope is `docs/ROADMAP-PLATFORM.yaml` only.** No `.tf`, no source, no Lambda. RDS provisioning + the
  write/read migration are future tier_items (T2.16, T2.19); Lambda-deploy is DEFERRED per Decision 67 / CD.16.
- **Ops-only scope.** The proposed DuckLake adoption covers ops/telemetry tables only. The product `D.lake.*` /
  market-data tier stays Iceberg (KG.1 platform/product boundary; product tables are independently Class-A-gated
  per CD.25); a market-data DuckLake assessment is deferred to FP-C. Do not touch any `D.lake.*` / `L*.alpha`-SCD2
  tier_item.
- **Agent-first artefact design (CD.13 / CD.14):** edit the roadmap's native structures (candidate_decisions,
  open_questions, tier_items). Do NOT create a separate narrative dossier/companion doc -- that is the legacy
  pattern being retired. Conform new entries to the EXISTING schemas (open_questions are flat
  `{id, question, resolution_tier, notes}` -- summarise options inside `notes`).
- **RDS catalog framing:** present the RDS PostgreSQL catalog as durable metadata-about-storage (a Glue-analog),
  explicitly NOT a query engine, so it stays NS.1-consistent (NS.1 governs engine-swappability, not a metastore
  ban; NS.3 actively supports a small managed cloud state-store).
- **VPC framing:** state that VPC-attaching the DuckLake Lambdas (to reach RDS) does NOT alter the
  Function-URL + AWS_IAM agent surface (CD.10 / NS.5) -- VPC config governs egress; the Function URL is ingress.
- No rescue agents or workaround loops (Decision 55).
- No emojis; ASCII hyphens; ruff line length 127; `bin/venv-python` for all Python invocations.

## Context
- **Why now:** the DuckLake spike returned PROCEED on mechanics (PR #47), but the deep doc-read surfaced
  adoption risk the spike did not weigh -- so the right artefact is a staged proposal + a decision surface for
  human ratification, not a unilateral north-star rewrite. The user has decided the catalog backend is a small
  always-on **micro RDS PostgreSQL** instance (~$12-15/mo single-AZ db.t4g.micro + gp3 + PITR), trading
  SQLite-coordination + catalog-durability complexity for VPC/connection complexity -- a net simplification that
  also resolves the two riskiest open questions (backend + durability).
- **Decisive doc-research findings driving the open_questions:** (1) DuckLake v1.0 has **no Iceberg metadata
  export** and **no external-engine reader** -- Athena/Trino cannot read DuckLake, and `ducklake_add_data_files`
  is import-only AND dangerous (registered files' ownership transfers; compaction can delete them) -> the CD.15
  Athena escape hatch has no export-based mitigation today (OQ.7). (2) Partitioning IS available via
  `ALTER TABLE ... SET PARTITIONED BY` (the spike's `CREATE TABLE PARTITION BY` parser error was the wrong
  conclusion) -> CD.9 reconcilable. (3) Aurora DSQL is unvalidated against DuckLake's PG12+/SQL-92/PK-based-OCC
  contract -> standard RDS/Aurora PostgreSQL is the documented-safe target; DSQL aim dropped. (4) The catalog is
  the lakehouse single point of failure (snapshots are catalog rows; un-flushed inlined data lives only in the
  catalog; no catalog-format migration tooling across the lockstep spec+extension+DuckDB version bumps) -> OQ.9 +
  OQ.12. (5) DuckLake is OCC + snapshot-isolation; even single-writer Lambda overlap can collide on snapshot_id
  and DDL/altered-table writes hard-abort -> OQ.10. (6) Inlining default threshold is 10 rows; un-flushed data is
  durable only in the catalog -> OQ.11. (7) Maintenance is in-engine `CALL` functions
  (flush -> merge_adjacent_files -> expire_snapshots -> cleanup_old_files -> delete_orphaned_files, + rewrite);
  expire != delete (S3 grows unless cleanup is also scheduled) -> T2.18.
- **Decisions to cite:** Decision 48 (V1 tier -- non-handler YAML, no runtime effect); Decisions 50/56/51/69
  (supersede-if-ratified; the DuckLake write path MUST preserve Decision 69's primitive-level Single-Portal
  invariant); Decision 67 / CD.16 (freeze: this plan is IMPLEMENTATION and deploys nothing; future Lambda
  tier_items carry deferred-deploy markers); Decision 35 + Decision 77 (RDS-provisioning tier_item Terraform
  apply path + fail-closed-on-IAM guard); CD.8 / CD.9 / CD.15 (amended); CD.10 / NS.5 (VPC orthogonal to
  Function-URL); CD.24 (per-Lambda manifests); CD.29 / Decision 62 (maintenance cadence: prefer a deliberate
  Lambda-vs-GH-Actions-schedule choice); CD.30 (the supersede-by-pending-CD mirror template); NS.1 / NS.3
  (generalisation deferred to OQ.13; NS.3 supports a managed cloud state-store); KG.1 (platform/product boundary).
- **Decision flags accepted (two decision-scout passes, all NOTE, no BLOCK):**
  1. Superseding Decisions 50/56/51/69 via a `state: pending` CD that does not edit DECISIONS.md is the
     documented mechanism (CD.30 precedent). Mirror CD.30's language; transition no numbered Decision.
  2. NS.1 names "Iceberg" and "data is not migrated to swap engines" -- surface as OQ.13, do NOT rewrite NS.1
     (CD.23 precedent for reconciling an NS tension via a pending CD). Frame the RDS catalog as a Glue-analog
     metadata store to keep it NS.1-consistent.
  3. VPC-attaching the Function-URL Lambdas does not conflict with CD.10 / NS.5 (egress vs ingress are
     orthogonal); assert this in T2.17. The only real consequence -- VPC egress kills `extensions.duckdb.org` --
     makes extension bundling mandatory (captured in T2.17).
  4. Always-on RDS contradicts no decision: there is no serverless-first/no-always-on principle; CD.21's
     EC2-runner retirement was CI-security-specific; NS.3 supports a managed cloud state-store; cost lands inside
     the existing `line_items_not_enumerated` envelope and net monthly cost likely falls as the EC2 runner retires.
- **ci-rca related-work deferral (logged):** the lone open ci-rca rec at session start (rec-2026, Low) had its
  `verify_ci_workflow` wiring merged to `main` via PR #49 (`a50e0e7`) by a parallel agent; this plan's scope
  (`docs/ROADMAP-PLATFORM.yaml` governance) shares no file, Decision, or failure category with it. Related-Work
  Check satisfied via this logged rationale; rec-2026 is being handled separately and is not re-scoped here.
- **Named follow-on plans (NOT in this scope):**
  - **FP-B = T2.19** -- the DuckLake ops write/read migration (replace the OpsWriter JSONL-staging path with a
    DuckLake writer preserving Decision 69; swap `DuckDBIcebergReader` -> a DuckLake reader; adopt SCD2 via
    `current_state` + optionally `ducklake_table_changes` CDC / time-travel; resolve OQ.7 + OQ.10). A V3
    IMPLEMENTATION plan, gated on CD.31 ratification + T2.16/T2.17/T2.18; Lambda-deploy DEFERRED per Decision 67.
  - **FP-C** -- market_data / product `D.lake` DuckLake assessment + the catalog multi-tenancy decision (OQ.14:
    shared ops-RDS-schema vs dedicated/larger instance vs per-environment catalog per E.env.2). Gated on a
    billions-of-rows scale-proof; the ops catalog is provisioned in its own schema (T2.16) for clean separability.
- **Branch:** `claude/exciting-galileo-KBn8z`, reset to `origin/main` at `a50e0e7` (0 behind / 0 ahead). The only
  recently-changed main files (`PLAN-ci-workflow-guards-wiring.md`, validate.py wiring) do not overlap this plan's
  single Scope file -- no rebase deferral needed.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`claude/exciting-galileo-KBn8z`)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (48, 50, 51, 56, 69, 67, 35, 77, 62) and ROADMAP-PLATFORM.yaml CDs (8, 9, 10, 15, 16, 24, 29, 30) + NS.1/NS.3/NS.5 + KG.1
- [ ] docs/ducklake-spike-findings.md re-read (the merged spike output this builds on)
- [ ] ROADMAP-PLATFORM.yaml located; CD/OQ/tier-item schemas confirmed (CD.30 mirror template; flat open_questions; tier_item shape per T2.4/T2.5)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Add candidate_decision CD.31** immediately after CD.30 (before the `tier_items:` key). Include: `title`,
   multi-line `detail` (the proposal, ops-only scope, RDS-catalog-as-Glue-analog framing, the doc-research risks,
   proceed-pending-OQ.7-OQ.14, and the explicit CD.30-style "does NOT touch DECISIONS.md; supersession + NS.1
   generalisation land at ratification via the log-decision path + FP-B" clause), `gates: [T2.16, T2.17, T2.18,
   T2.19]`, `state: pending`, `filed_via: pending_log_decision_lambda`, `supersedes_decisions: [50, 56, 51, 69]`
   with per-Decision clauses (50 append-only-Iceberg -> append-only-DuckLake; 56 SCD2 reproduced + extended by
   time-travel/CDC; 51/69 JSONL-staging write path -> DuckLake writer, Decision 69 Single-Portal preserved), an
   "amends: CD.8/CD.9/CD.15" note, and `discipline_points` (NS.1 generalisation = OQ.13; FP-B carries Decision 67/
   CD.16 deferred-deploy; product D.lake stays Iceberg per KG.1).
   **Schema note (avoids a VP step-1 failure):** `CandidateDecision` and `TierItem` are `extra="forbid"` in
   `scripts/platform_roadmap.py`. Author the amends clause, the per-Decision supersession clauses, and the
   not-enacted statement as `detail` prose or inside the existing `discipline_points` list -- do NOT introduce a
   new top-level key (e.g. `amends:`). Only the existing fields are permitted (CD: id/title/detail/gates/state/
   filed_via/supersedes_decisions/narrowly_supersedes/discipline_points; tier_item: id/tier/name/intent/depends_on/
   files_in_scope/exit_criteria/related_candidate_decisions/effort/strategic/status[/gates/note]).
2. **Add open_questions OQ.7-OQ.14** (flat schema; options summarised in `notes`; `resolution_tier` pointing at
   the relevant tier_item / FP-B / FP-C / "CD.31 ratification"): OQ.7 Athena hatch (no Iceberg export / no external
   reader), OQ.8 catalog backend (RDS Postgres confirm; single-AZ db.t4g.micro; RDS Proxy deferrable; IAM-auth vs
   Secrets-Manager; DSQL dropped), OQ.9 catalog durability/DR + SPOF (RDS backups/PITR; backup cadence; ties T2.8),
   OQ.10 OCC writer-concurrency enforcement (reserved-concurrency=1 / SQS FIFO vs OCC retry), OQ.11 inlining flush
   policy (threshold 10; flush-on-write vs scheduled vs catalog-as-durability), OQ.12 version/upgrade policy
   (lockstep v1.0 <-> DuckDB 1.5.2; no in-place migration; clone-rehearsal gate), OQ.13 NS.1 generalisation
   ("S3 + Iceberg" -> "S3 + open table format"; pending CD.31 ratification), OQ.14 catalog multi-tenancy with the
   future market-data catalog (shared ops-RDS-schema vs dedicated/larger instance vs per-env catalog; deferred FP-C).
3. **Add tier_items T2.16-T2.19** (schema-conformant, `tier: T2`, `status: not_started`, `strategic: false`,
   `related_candidate_decisions` including CD.31): T2.16 RDS catalog provisioning (`files_in_scope` a new
   `terraform/*.tf`; own dedicated schema for separability; cite Decision 35 + Decision 77 + the fail-closed-on-IAM
   guard for security-group/credential changes), T2.17 DuckLake Lambda runtime (VPC attach + pre-baked
   ducklake+httpfs extension layer + `extension_directory`/disable-autoinstall-autoload/fail-closed
   `custom_extension_repository` + version pin; assert Function-URL/AWS_IAM unaffected by VPC, cite CD.10),
   T2.18 DuckLake maintenance pipeline (flush -> merge -> expire -> cleanup -> delete_orphaned + rewrite; replaces
   ops_compaction; cadence-mechanism a deliberate Lambda-vs-GH-Actions choice per CD.29/Decision 62; note
   expire != delete), T2.19 DuckLake ops write/read migration = FP-B (preserve Decision 69 Single-Portal; swap
   reader; resolve OQ.7 + OQ.10; `depends_on: [T2.16, T2.17, T2.18]`; Lambda-deploy DEFERRED per Decision 67/CD.16).
4. **Apply factual reconciliations** to existing candidate_decisions (detail text only, additive): CD.8 (DuckDB's
   native operational format becomes DuckLake), CD.9 (partitioning IS available via `ALTER TABLE ... SET
   PARTITIONED BY`, not `CREATE TABLE` DDL; reconcile the "No unpartitioned-table path" absolute for ops DuckLake
   tables -- partition via ALTER when row/file count warrants), CD.15 (Athena cannot read DuckLake -> the escape
   hatch is OQ.7; DuckDB-on-DuckLake replaces DuckDB-on-Iceberg-snapshot for ops). Add a one-line note to **T2.4**
   that ops-table partitioning under DuckLake uses ALTER per CD.31 (Iceberg partition sweep otherwise unchanged).
5. **Add the cost_projection line:** under `cost_projection.current_scale.breakdown` add `rds_ducklake_catalog`
   (~$12-15/mo single-AZ db.t4g.micro + gp3 + PITR; +$10-12 only if RDS Proxy added) with a note that it is
   envelope-consistent with `line_items_not_enumerated` (already names VPC/NAT) and that net monthly cost likely
   falls as the ~$35/mo EC2 runner retires per CD.21.
6. **Leave NS.1 and DECISIONS.md UNCHANGED.** Do not reword NS.1; do not edit any numbered Decision.
7. **Execute Verification Plan** -- run each step; loop until pass. This is V1; if `validate` surfaces a
   roadmap-schema error, conform the entry shape (do not weaken the check).
8. **Report:** what was added (CD.31, OQ.7-OQ.14, T2.16-T2.19, the CD.8/9/15 reconciliations, the cost line),
   verification results, and the named follow-ons (FP-B = T2.19 migration; FP-C = market_data + OQ.14).
