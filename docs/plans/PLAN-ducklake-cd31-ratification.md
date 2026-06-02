# Plan

## Intent
Ratify candidate decision CD.31 ("Adopt DuckLake for the operational lakehouse") so the operational
lakehouse can move off Iceberg-on-S3-metadata onto DuckLake, un-gating COMPLETION of the T2.16-T2.19
DuckLake workstream. This is the governance step that lets the self-improving platform record and act on
a durable architecture commitment (North Star: storage durable, compute interchangeable).

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 — the ratification performs live `ops_decisions` warehouse writes (DynamoDB id allocation -> `OpsWriter`
-> S3, with Athena read-back). There is no Lambda/Terraform deploy, so the V3 `[pre-deploy]`/`[post-deploy]`
tags are mapped to `[pre-write]`/`[post-write]` against the ops warehouse as the integration surface. The
binding behavioural check is that Decision 78 lands as a real `dec-NNNN` row in `ops_decisions_current`
(not an outbox stub) and that `dec-050`/`dec-051` show the superseded status.

## Plan Path
docs/plans/PLAN-ducklake-cd31-ratification.md

## Phase
Platform roadmap, tier T2 (DuckLake adoption governance). Ratifies CD.31, whose `gates: [T2.16, T2.17,
T2.18, T2.19]` COMPLETION-gate the entire DuckLake chain (none of those four carry
`bootstrap_completion_exempt`). Product-phase axis: not applicable (this is platform governance, not a
trading-strategy change).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Flip `CD.31` `state: pending -> ratified` and `filed_via: pending_log_decision_lambda -> ops_decisions:dec-NNN` (retain `CD.31` id as the traceability alias per the comment at lines 290-294). Apply the OQ.13 resolution: generalise `NS.1.detail` from "S3 + Iceberg at every scale" to "S3 + open table format at every scale". |
| `docs/DECISIONS.md` | Modify | Add `## Decision 78: Adopt DuckLake for the operational lakehouse (Decided)` at the top (newest-first), carrying the real `**Warehouse ID:** dec-NNNN`. Remove the four superseded decision blocks (50, 51, 56, 69) from this file. |
| `docs/DECISIONS_ARCHIVE.md` | Modify | Receive Decisions 50, 51, 56, 69 with `(Superseded by Decision 78)` in their headings + `**Status:** Superseded by Decision 78` + `**Superseded by:** Decision 78`. |
| `scripts/ops_data_portal.py` | Invoke (NOT edit) | `file_decision()` mints the Decision 78 warehouse row; `update_decision()` marks `dec-050`/`dec-051` superseded. Python API, not the CLI (see Constraints). |

## Bundled Recommendations
None. (One follow-up rec should be FILED by the implementer — see Context "Tooling gap" — but it is not
bundled into this plan's scope.)

## Infrastructure Dependencies
Not applicable. No `.tf` files are in scope. The RDS PostgreSQL DuckLake catalog (T2.16) is the FIRST
downstream consumer of this ratification but is a separate plan; this plan provisions no infrastructure
and spends no money. It only records the decision that un-gates that work.

## Acceptance Criteria
- [ ] `CD.31` in `docs/ROADMAP-PLATFORM.yaml` reads `state: ratified` and `filed_via: ops_decisions:dec-NNN` (matching `^ops_decisions:dec-\d+$`), `id: CD.31` retained, `supersedes_decisions: [50, 56, 51, 69]` unchanged.
- [ ] `NS.1.detail` no longer names "Iceberg" exclusively; it reads "S3 + open table format ...".
- [ ] `docs/DECISIONS.md` contains a well-formed `## Decision 78: Adopt DuckLake for the operational lakehouse (Decided)` block with `**Status:** Decided`, `**Date:**`, `**Warehouse ID:** dec-NNNN`, `**Problem:**`, `**Decision:**`, `**Rationale:**`, `**Related:**` (citing CD.31, Decisions 50/51/56/69, 67, 69).
- [ ] Decisions 50, 51, 56, 69 are no longer present as headings in `docs/DECISIONS.md` and ARE present in `docs/DECISIONS_ARCHIVE.md` marked superseded by Decision 78.
- [ ] A real `dec-NNNN` row for Decision 78 exists in `ops_decisions` (status `Decided`); `dec-050` and `dec-051` show status `Superseded`. (Decisions 56 and 69 have no warehouse row and are superseded in docs only — see Context.)
- [ ] `bin/venv-python -m scripts.validate` passes (RoadmapDocument schema incl. `filed_via` regex; `validate_decisions_local_writes`; `validate_warehouse_write_sources`).
- [ ] No direct writes to `logs/.decisions-index.jsonl`; the cache is rebuilt only via the portal/preflight pull (Decision 69 / warehouse-as-source-of-truth).

## Verification Plan
> `<N78>` = the integer Decision 78 maps to in the warehouse (returned by `file_decision`, e.g. `dec-1085` -> `1085`). Substitute at implement time.

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | static | CD.31 flipped to ratified | `awk '/- id: CD.31/{f=1} f&&/state:/{print; exit}' docs/ROADMAP-PLATFORM.yaml` | prints `    state: ratified` | still `pending` -> edit not applied |
| 2 | static | CD.31 filed_via points at the warehouse row | `awk '/- id: CD.31/{f=1} f&&/filed_via:/{print; exit}' docs/ROADMAP-PLATFORM.yaml` | prints `    filed_via: ops_decisions:dec-<N78>` | still `pending_log_decision_lambda`, or fails `^ops_decisions:dec-\d+$` |
| 3 | static | NS.1 generalised (OQ.13) | `grep -A2 "id: NS.1" docs/ROADMAP-PLATFORM.yaml \| grep -ic "open table format"` | `1` | `0` -> NS.1 still names Iceberg exclusively |
| 4 | static | Decision 78 authored, newest-first | `grep -nE "^## Decision 78: Adopt DuckLake" docs/DECISIONS.md` | one match, above the Decision 77 line | no match -> block not added |
| 5 | static | Warehouse ID line present and real | `grep -E "^\*\*Warehouse ID:\*\* dec-[0-9]+" docs/DECISIONS.md \| head -1` | matches `dec-<N78>` | placeholder/missing -> Decision 78 minted incorrectly |
| 6 | static | Four superseded removed from open file | `grep -cE "^## Decision (50\|51\|56\|69):" docs/DECISIONS.md` | `0` | non-zero -> a block was not moved |
| 7 | static | Four superseded landed in archive | `grep -cE "^## Decision (50\|51\|56\|69):.*Superseded by Decision 78" docs/DECISIONS_ARCHIVE.md` | `4` | `<4` -> a heading not rewritten |
| 8 | [pre-write] | Athena/warehouse reachable BEFORE any portal write | `aws sts get-caller-identity --profile agent_platform` | returns the assumed PlatformDev ARN, exit 0 | unreachable -> STOP; do NOT mint with a stale/offline chain (Decision 69 NOTE) |
| 9 | [post-write] | Decision 78 LANDED in the warehouse (not an outbox stub) | `bin/venv-python -m scripts.session_preflight && grep -E '"decision_id": <N78>,' logs/.decisions-index.jsonl` | one row, `"status": "Decided"` | absent -> file_decision queued to outbox (returned `pending-...`) instead of landing |
| 10 | [post-write] | dec-050 / dec-051 superseded in the warehouse | `grep -E '"decision_id": (50\|51),' logs/.decisions-index.jsonl` | both rows show `"status": "Superseded"` | still `Decided` -> update_decision did not run/commit |
| 11 | gate | Full presubmit passes | `bin/venv-python -m scripts.validate` | exit 0 (validate_platform_roadmap + validate_decisions_local_writes + validate_warehouse_write_sources green) | schema/regex/local-write failure -> fix per the failing check |

## Constraints
- **Single-Portal Invariant (Decision 69):** every `ops_decisions` write goes through `scripts/ops_data_portal.py` (`file_decision`/`update_decision`). NEVER edit `logs/.decisions-index.jsonl` directly (`validate_decisions_local_writes` fails CI). NEVER restage a warehouse row from a local file (CRUD-in-lakehouse anti-pattern). `docs/DECISIONS.md` / `DECISIONS_ARCHIVE.md` are the human decision record, NOT a warehouse write source.
- **Portal CLI cannot express the decision-status convention:** `ops_data_portal` CLI `--decision-status` choices are `{open,closed,superseded}` and `--update-decision --status` are the recommendation enum; neither can pass the `ops_decisions` free-text convention `[Decided, Superseded, Open]` (ops.yaml:194-196, `enforced: false`, no `write_time`). Use the portal **Python API** (`file_decision({..., "status": "Decided"})`, `update_decision("dec-050", {"status": "Superseded"})`), which `extra="ignore"` accepts. Do NOT use the CLI for these writes.
- **Athena required for supersession (Decision 69 NOTE):** `update_decision` reads the current row from Athena and raises if unreachable (no outbox fallback, unlike `file_decision`). Step 8 gates all writes on a live chain.
- **No Lambda deploy (Decision 67):** the canonical ratification vehicle (T-1.1 -> log-decision Lambda T0.7b) is `not_started`/deferred and is a 501 stub. This plan deploys nothing and uses the interim portal path. This is IMPLEMENTATION, not a Lambda change.
- **Append-only / irreversibility:** `file_decision` is the point of no easy return (Iceberg append; no clean delete). If a later step fails, FORWARD-FIX (complete the docs / re-run update_decision); do NOT attempt to delete the row or build a rescue loop (Decision 55).
- **Supersession is "proposed-at-ratification" being enacted now:** per the human's "full ratification now" choice, the four supersessions are enacted in this plan rather than deferred to FP-B/T2.19. The new Decision 78 text MUST state that Decision 69's Single-Portal primitive-level invariant is PRESERVED (only the staging mechanism changes, and only when FP-B/T2.19 migrates the write path; the JSONL-staging path physically continues until then).
- No emojis; ASCII hyphens only; `bin/venv-python` for all Python; bash syntax.

## Context
- **Decision-scout verdict: FLAGS_FOUND** (not BLOCK). No numbered Decision forbids manual portal ratification or out-of-order CD ratification. CITE list: Decision 69 (Single-Portal — preserve), Decisions 50/56/51 (superseded set), Decision 67 (why the canonical vehicle is unavailable -> interim path), Decision 48 (verification tier). Two NOTE flags folded into this plan: (a) Decision 69 — `update_decision` needs live Athena + rows minted by the portal allocator, never derived from doc edits (handled by Step 8 + the Python-API write path); (b) Decision 48 — tier wording reconciled by declaring V3 with the warehouse as the integration surface and the warehouse-landing check (Steps 9-10) as binding.
- **First-ever CD ratification in this repo.** All 31 candidate decisions are `state: pending`; T-1.1 (the canonical ratification vehicle) is `not_started`; there is no precedent commit. This plan establishes the procedure. The roadmap's governing language (`agent_instructions` lines 33-86; CD.31 lines 1162-1165, 1224-1246) says supersessions are "proposed-at-ratification only" and "land via the log-decision path and the FP-B follow-on, exactly mirroring CD.30"; the human has explicitly chosen to enact the full ratification (including supersessions) now rather than defer the DECISIONS.md edits to FP-B.
- **OQ.13 is the only ratification-blocking open question** (`resolution_tier: CD.31`); resolved here by generalising NS.1. OQ.7 (Athena/Trino can no longer read DuckLake ops tables — regression of the CD.15 escape hatch), OQ.8/9 (RDS sizing/DR), OQ.10/11 (OCC/inlining), OQ.12 (version pin), OQ.14 (multi-tenancy) are deferred to T2.16-T2.19/FP-C by design and are NOT in scope.
- **Warehouse is a partial projection.** Confirmed against this session's Athena-rebuilt cache: `dec-050` (Decision 50) and `dec-051` (Decision 51) exist (`status='Decided'`); Decisions 56 and 69 have NO `ops_decisions` row (only 39 of 77 human decisions are in the warehouse). So warehouse supersession is asymmetric: `update_decision` for 50/51 only; 56/69 are superseded in `DECISIONS.md`/archive only (do NOT fabricate `dec-056`/`dec-069` rows — that would mint NEW ids, not retroactively create the originals).
- **Decision numbering:** highest human decision is 77, so the new one is Decision 78 (insert newest-first at the top of `DECISIONS.md`). The human number (78) is independent of the warehouse id (`dec-NNNN`, counter currently at 1084 -> next ~`dec-1085`); Decision 77 maps to `dec-1083`, so DO NOT assume alignment.
- **Tooling gap (file a follow-up rec at implement time):** the portal CLI's `--decision-status`/`--update-decision --status` choices are misaligned with `ops_decisions` accepted_values `[Decided, Superseded, Open]`. File a `source=planning` rec (effort XS) to either align the CLI choices or complete the Phase-2 narrowing of `ops_decisions.status` to a single enforced enum. Not fixed here (out of scope; docs-only ratification).
- **No main divergence / no open ci-rca recs** at planning time (preflight: 0 behind, 0 ahead; `ci_rca: 0`).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (esp. current text/status of Decisions 50, 51, 56, 69, and the Decision 77 template)
- [ ] CD.31 block (`docs/ROADMAP-PLATFORM.yaml` ~lines 1159-1246) and NS.1 (line ~138-140) read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Confirm "Decision 78" is unused in BOTH `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` (`grep -E "^## Decision 78:" docs/DECISIONS.md docs/DECISIONS_ARCHIVE.md` returns nothing) — guards against a parallel-authoring collision (cf. Decision 77's renumber note)

## Ordered Execution Steps
1. **Preconditions.** Verify branch is not `main`. Run `aws sts get-caller-identity --profile agent_platform` (VP Step 8) — the warehouse must be reachable before any write. Confirm Decision 78 is unused (checklist). Re-confirm the warehouse projection: `grep -E '"decision_id": (50|51|56|69),' logs/.decisions-index.jsonl` (expect 50 and 51 present as `Decided`; 56 and 69 absent). If `creds_status` is unavailable, STOP and restore the static-key chain — do NOT mint offline.
2. **Mint Decision 78 in the warehouse (irreversible commit point).** Via the portal **Python API** (CLI cannot pass `status: "Decided"`): call `file_decision({"title": "Adopt DuckLake for the operational lakehouse (ops + telemetry tables)", "status": "Decided", "problem": "<why: Iceberg-on-S3-metadata read path + the staged CD.31 proposal>", "decision_text": "<the adoption: DuckLake v1.0 for ops/telemetry; RDS PG catalog; product tables stay Iceberg; supersedes 50/51/56/69; preserves Decision 69 primitive-level Single-Portal invariant; generalises NS.1>", "context": "<cite CD.31, OQ.13, Decision 67 interim path>", "decided_date": "2026-06-02", "related_decisions": [50, 51, 56, 69, 67]})`. Capture the returned id. **If it returns `pending-<uuid>` (not `dec-NNNN`), Athena was unreachable — STOP and fix connectivity; do not proceed.** Record `<N78>` (the integer) for the YAML/doc edits.
3. **Edit `docs/ROADMAP-PLATFORM.yaml`.** On the `CD.31` entry: `state: pending -> state: ratified`; `filed_via: pending_log_decision_lambda -> filed_via: ops_decisions:dec-<N78>`. Leave `id: CD.31` and `supersedes_decisions: [50, 56, 51, 69]` unchanged. On `NS.1`: change `detail:` from "S3 + Iceberg at every scale from GB to PB. ..." to "S3 + open table format at every scale from GB to PB (Iceberg for market-data; DuckLake for ops/telemetry per Decision 78). ..." (preserve the rest of the sentence and the `principle:` line, which is already format-agnostic).
4. **Author Decision 78 in `docs/DECISIONS.md`.** Insert a `## Decision 78: Adopt DuckLake for the operational lakehouse (Decided)` block at the TOP (immediately under the `# Open Decisions` intro, above Decision 77), following the Decision 77 field template: `**Status:** Decided`, `**Date:** 2026-06-02`, `**Warehouse ID:** dec-<N78>`, `**Problem:**`, `**Decision:**` (numbered list mirroring CD.31's scope: DuckLake v1.0 for ops/telemetry only; product/market-data tables remain Iceberg per KG.1; RDS PG catalog as a metadata store, not a query engine; supersession of 50/51/56/69 enacted now with physical write-path migration in FP-B/T2.19), `**Rationale:**`, and `**Related:**` citing CD.31 (ratified), Decisions 50/51/56/69 (superseded), Decision 67 (interim path), Decision 69 (primitive-level invariant PRESERVED). Explicitly state the Decision 69 preservation distinction.
5. **Supersede 50/51/56/69 in the docs.** For each of Decisions 50, 51, 56, 69: cut the block from `docs/DECISIONS.md` and paste into `docs/DECISIONS_ARCHIVE.md`, appending `(Superseded by Decision 78)` to the heading, setting/adding `**Status:** Superseded by Decision 78`, and adding a `**Superseded by:** Decision 78` field. Use the rename/careful-cut discipline (PROJECT_CONTEXT "File deletion reference sweep" / refactoring protocol) — verify each block moved intact (VP Steps 6-7) before proceeding.
6. **Mark 50/51 superseded in the warehouse.** Via the portal Python API (Athena confirmed live in Step 1): `update_decision("dec-050", {"status": "Superseded"})` and `update_decision("dec-051", {"status": "Superseded"})`. Decisions 56 and 69 have no warehouse row — record nothing in the warehouse for them (doc-only supersession, per Context). Do NOT call `file_decision` for 56/69.
7. **Rebuild the read cache from Athena and run the warehouse read-back.** `bin/venv-python -m scripts.session_preflight` (pulls `ops_decisions` from Athena, overwriting the local cache), then VP Steps 9-10 (Decision 78 present as `Decided`; `dec-050`/`dec-051` show `Superseded`). This proves real warehouse landings, not outbox stubs.
8. **Execute the full Verification Plan** — run VP Steps 1-11. `bin/venv-python -m scripts.validate` (Step 11) is the authoritative gate; confirm `validate_platform_roadmap` accepts the new `filed_via` and `validate_decisions_local_writes`/`validate_warehouse_write_sources` are green. Loop on failure (forward-fix; no rescue loops, Decision 55). If a V3 read-back step fails unrecoverably, stop and root-cause.
9. **Report:** what was ratified (Decision 78 = `dec-<N78>`), the four supersessions (50/51 in warehouse + docs; 56/69 docs-only), the NS.1 generalisation, and that CD.31 is now `ratified` (un-gating T2.16-T2.19 completion). Note the follow-up tooling-gap rec (Context) and that T2.16 (RDS provisioning) is the natural next plan.
