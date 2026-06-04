# Plan

## Intent
Produce a zero-context-reviewable REPORT enumerating exactly what changes in `docs/ROADMAP-PLATFORM.yaml`
(plus one new candidate decision) if the DuckLake operational-lakehouse *catalog backend* migrates from
the just-provisioned AWS RDS PostgreSQL instance (T2.16, complete 2026-06-03) to Neon serverless Postgres
(free tier), and why. The report is the proposal artefact; after it passes the REPORT-ONLY zero-context
review gates and the human reaches consensus, the change-set is folded into the roadmap and opened as a PR.
This plan ENACTS no roadmap or DECISIONS.md change.

## Plan Type
REPORT-ONLY

## Verification Tier
V1 (documentation deliverable; no code, no handler config, no runtime effect -- Decision 48).

## Plan Path
docs/plans/PLAN-ducklake-catalog-neon-migration.md

## Phase
Platform roadmap T2 (full state migration to personal account). Re-prices the DuckLake catalog backend
chosen at T2.16 / Decision 78 (CD.31) before the T2.17-T2.19 runtime work builds an RDS-in-a-VPC posture
around it. Adjacent to the just-ratified CD.33 (Decision 81 / dec-1089) runtime architecture; touches it only
via consequential backend amendments staged as an additive `[Amendment -- CD.34]` annotation (CD.33's ratified
body is unchanged).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/REPORT-ducklake-catalog-neon-migration.md` | Create | The deliverable: the RDS->Neon roadmap change-set + rationale, risks, rollback, alternatives, recommendation. The substantive output. |
| `docs/plans/PLAN-ducklake-catalog-neon-migration.md` | Create | This planning artefact. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify (Phase 2 fold-in, this PR) | Enact the change-set below after review consensus. |

**Two phases:** Phase 1 (REPORT-ONLY) authored the report + this plan with the roadmap UNTOUCHED. Phase 2
(this same PR, post-consensus) ENACTS the change-set in `docs/ROADMAP-PLATFORM.yaml`. DECISIONS.md remains
untouched in both phases (CD.34 stages pending). CD.33, ratified mid-session by Decision 81, is amended via an
additive annotation only (its ratified body is unchanged). The Verification Plan below is annotated per phase.

The report PROPOSES (and Phase 2 enacts) the following roadmap change-set:
new candidate decision **CD.34** (pending; narrowly amends the CD.31 catalog-backend paragraph / Decision 78
item; mandates inlining disabled for ALL Neon tables; Terraform Neon provider, human-gated); new tier item
**T2.16b** (Terraform-Neon provisioning + Secrets Manager DSN + smoke test + tested restore + RDS retirement);
surgical amendments to **T2.17** (drop VPC-attach; pooler choice conditional on the smoke test), **T2.18**
(catalog DR = daily `pg_dump`-to-S3, `cron(0 3 * * ? *)`, 30-day retention; maintenance cadences unchanged),
**T2.19** (rebuild-from-`pg_dump` + Neon break-glass), **CD.33** (RATIFIED mid-session by Decision 81 -- amended
via an additive `[Amendment -- CD.34]` annotation only; the ratified clause 3/5/enforcement bodies are
UNCHANGED, the split/OCC/projection/keys + GC/merge cadences unaffected), **OQ.7 / OQ.8 / OQ.9 / OQ.11 / OQ.14**
(annotate), a non-destructive **`[Amendment -- CD.34]`** annotation on the **CD.31 record**, and the **cost
model** (replace the RDS line with the Neon $0 line; flag the stale EC2-runner `dominant_cost` field).

## Bundled Recommendations
None. (The report notes the migration closes rec-2062/2064/2068/2069 by file deletion and rec-2065/2066 when
the RDS IAM policy is removed; the transferable concerns rec-2063 [single-copy backup on destroy] and rec-2067
[egress least-privilege] are RE-FILED against the Neon posture, not silently closed; the stale `dominant_cost`
EC2-runner line is flagged for same-PR correction or a freshness rec. None are enacted here.)

## Acceptance Criteria
- [ ] `docs/REPORT-ducklake-catalog-neon-migration.md` exists with: architecture background (catalog =
      SPOF); the why-now rationale; the full Section-4 change-set (CD.34, T2.16b, and the T2.17/T2.18/T2.19/
      CD.33/OQ.8/OQ.9/OQ.14/cost amendments) each with before -> after; the Lambda auth model (Secrets
      Manager); risks + mitigations; rollback; alternatives; decisions-to-cite; a conditional recommendation.
- [ ] The report is grounded in the live roadmap (CD.33 ratified mid-session by Decision 81; T2.17-T2.19
      not_started; T2.16 complete) and cites Neon facts with sources.
- [ ] **DECISIONS.md and ROADMAP-PLATFORM.yaml are UNCHANGED** by this plan
      (`git diff origin/main -- docs/DECISIONS.md docs/ROADMAP-PLATFORM.yaml` empty).
- [ ] Numbering: CD.34 is the next candidate decision; the eventual ratifying Decision is 82
      (after Decision 81 ratified CD.33 as dec-1089).
- [ ] `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected | Fix If |
|---|-------|--------|---------|----------|--------|
| 1 | pre | Report deliverable present | `test -f docs/REPORT-ducklake-catalog-neon-migration.md && echo REPORT_OK` | prints `REPORT_OK` | create the report |
| 2 | pre | Change-set sections present | `grep -qE "CD\.34" docs/REPORT-ducklake-catalog-neon-migration.md && grep -qE "T2\.16b" docs/REPORT-ducklake-catalog-neon-migration.md && grep -q "pg_dump" docs/REPORT-ducklake-catalog-neon-migration.md && echo SECTIONS_OK` | prints `SECTIONS_OK` | add the missing section |
| 3 | post | Phase 2 fold-in: roadmap change-set applied + schema validates | `bin/venv-python -m scripts.platform_roadmap` | `PASS` (CD.34 + T2.16b resolve) | fix the schema/referential error |
| 4 | pre | DECISIONS.md untouched | `git diff --quiet origin/main -- docs/DECISIONS.md && echo DECISIONS_UNTOUCHED` | prints `DECISIONS_UNTOUCHED` | revert; CD.34 stages pending |
| 5 | post | Phase 2: CD.34 present + DECISIONS.md untouched | `grep -qE "^  - id: CD\.34" docs/ROADMAP-PLATFORM.yaml && git diff --quiet origin/main -- docs/DECISIONS.md && echo CD34_PRESENT_DECISIONS_CLEAN` | prints `CD34_PRESENT_DECISIONS_CLEAN` | add CD.34 / revert DECISIONS.md |
| 6 | pre | Full presubmit | `bin/venv-python -m scripts.validate` | PASS | address before merge |

## Constraints
- REPORT-ONLY: this plan creates only the two docs; it ENACTS no roadmap or DECISIONS.md change. The
  roadmap fold-in is a separate, human-greenlit PR after review consensus.
- CD.34 stages `state: pending` and does NOT edit DECISIONS.md (CD.30/CD.31/CD.33 precedent); ratification
  is a future log-decision Decision (provisionally Decision 82, after Decision 81 ratified CD.33 as dec-1089).
- CD.33 ratified mid-session (Decision 81 / dec-1089), so its CD.33-level changes are staged as a single
  additive `[Amendment -- CD.34]` discipline point (the ratified clause 3/5/enforcement bodies are UNCHANGED);
  the inlining override is ENFORCED in the not_started T2.17/T2.18 exit criteria + the OQ.11 re-resolution. The
  architecture (split/OCC/projection/SCD2 keys/GC+merge cadences) is NOT reopened.
- Human-decided posture (v2): (a) inlining disabled for ALL Neon tables (`inlined_rows=0`), overriding the
  telemetry carve-out in CD.33 clause (5) + OQ.11 (high-write-rate tables get a higher-frequency merge); (b) catalog DR = daily `pg_dump` to a versioned S3 bucket, 30-day retention,
  with the FIRST tested restore as a T2.16b precondition (before any production write); (c) Neon provisioned
  via the Terraform Neon provider, human-gated (carved out of the Decision-77 auto-apply guard).
- Any eventual RDS retirement Terraform apply is human-gated (Decision 35) and trips the Decision 77
  fail-closed guard (destroy) onto the manual `agent_platform_admin` path -- documented, not executed here.
- Agent-first artefact design: the report uses machine-parseable before->after tables; no second narrative
  companion doc.
- No emojis; ASCII hyphens; ruff line length 127; `bin/venv-python` for all Python.

## Context
- **Why now:** T2.16 provisioned the RDS on 2026-06-03; T2.17-T2.19 are `not_started`; nothing consumes the
  catalog yet (live ops remain Iceberg/Athena). Migrating before T2.17 avoids building, then tearing down,
  an RDS-in-a-VPC + RDS-Proxy posture. The RDS is the largest live AWS line post-CD.21 runner retirement.
- **Feasibility:** Neon is Postgres 14+ (satisfies DuckLake's PG12+/SQL-92/PK-OCC catalog contract);
  DuckLake-on-Neon is a documented working pattern. Free tier $0 / 0.5GB / 100 CU-hrs / scale-to-zero.
- **Governance:** decision-scout returned NO_FLAGS. The backend swap narrowly amends ratified Decision 78 /
  CD.31 (hence new CD.34), consistent with the NS.3 "small managed cloud state-store" framing.
- **Review:** REPORT-ONLY zero-context gates -- a plan-critique pass on this artefact, then a
  multi-perspective (architect + ops-risk) critique of the report deliverable, iterated to consensus before
  the roadmap fold-in PR.
