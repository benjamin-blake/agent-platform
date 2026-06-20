> **PARTIALLY SUPERSEDED by Decision 84 (2026-06-11):** the storage/transport mechanics described
> below (DynamoDB `decisions` counter, `logs/.ops-outbox/ops_decisions_pending/` +
> `drain_pending_decisions`, `OpsWriter().write("ops_decisions", ...)`, Athena
> `ops_decisions_current` reads) are RETIRED. ops_decisions lives on the DuckLake closed boundary:
> ids follow DECISIONS.md numbering via `fields['decision_id']`, writes transit `ducklake_writer`,
> reads transit the `decision_by_id`/`decisions_max_updated` verbs, and the backfill is
> `ops_data_portal --backfill-decisions-md`. SURVIVING SCOPE: the DQ graduation arc and the
> DECISIONS.md decommission question. See docs/INTENT-ducklake-consolidation.md.

# Intent: ops_decisions Graduation

This document is the single strategic anchor for the `ops_decisions` graduation
arc. Every agent planning or implementing work on the decisions data plane reads
this document first, checks the current phase status, and follows the agent
instructions before scoping anything new.

**Why this document exists:** `ops_decisions` lives one architectural generation
behind `ops_recommendations`. The portal functions exist only as skeletons; the
canonical ETL writes bypass the portal entirely; DQ checks are nearly all
`enforced: false`; there is no decision manifest; the local JSONL cache has no
write-through; the DynamoDB `decisions` counter is stale; a postflight ETL hook
silently re-stages markdown-parsed rows on every session close. Each gap is small
in isolation; their interaction produces silent data drift. This arc removes the
drift by migrating decisions onto the same architecture that already governs
recommendations, then decommissioning `docs/DECISIONS.md` so structured data is
the only source of truth.

**Builds on:**
- `docs/INTENT-dq-enforcement.md` -- the DQ enforcement maturity arc. Phase 4
  (Data Correction) of this arc is a HARD prerequisite for that arc's Phase 5
  (`enforced` field deletion); see Decision Registry below.
- `docs/INTENT-verification-system.md` -- the verifier `covers` list and harness
  apply to the enriched portal entrypoints.
- Decision 50 (Append-Only Ops Data Store via Iceberg) -- ops_decisions is
  already an Iceberg table; this arc completes the portal-first invariant that
  Decision 50 implies but did not enforce for decisions.
- Agent-First Repository principle in repo-root `CLAUDE.md` -- structured
  queryable data is preferred over narrative markdown for primary artefacts.

**Supersedes:** the implicit deferral comment at `scripts/s3_log_store.py:31`
("ops_decisions has no automated write-through -- deferred to Phase 2"). That
deferral is resolved by Phase 0+1 of this arc.

**Cross-references:** `docs/INTENT-dq-enforcement.md` Phase 4 Session Map
previously listed `ops_decisions` as a 1-session graduation. After this arc
starts, `ops_decisions` is scoped out of that map. Phase 4 of this arc is a
hard prerequisite for Phase 5 (`enforced` field deletion) of the
dq-enforcement arc.

---

## Live State at Planning Time (2026-05-12)

These figures are the basis for the sequencing and counter-reseed decisions
below. Recorded so future agents can re-derive divergence at session start.

- Athena `ops_decisions_current` rows: 37
- `docs/DECISIONS.md` + `docs/DECISIONS_ARCHIVE.md` parsed entries: 52
  (decision IDs span 21-72 with gaps)
- DynamoDB `decisions` counter at table `agent-platform-counters`: 58
- Max parsed decision ID: 72
- Gap between counter and max parsed ID: 14
  (the counter is BEHIND historical IDs; next allocation would collide)
- `grep -r 'DECISIONS\.md' .` hit count across the repo: 179
- Current `ops_decisions` DQ checks all `enforced: false` except `row_count`
- Live `_stage_document_derived_tables` postflight ETL bypass writes
  `OpsWriter().write("ops_decisions", entry)` on every `--close-session`

These are snapshots. Re-run the equivalent queries at the start of any phase
to refresh them; phase plans must not rely on the snapshots above as authoritative.

---

## North Star

**Append-only, agent-queryable decision history.** Every architectural decision
in the project is a row in `ops_decisions` accessible via Athena SQL or the
local JSONL cache. `docs/DECISIONS.md` is decommissioned. Agents query decisions
instead of parsing markdown.

The portal-first invariant matches `ops_recommendations`: all writes go through
`scripts/ops_data_portal.py`; the local JSONL cache is a downstream read
projection, never a write source. Bypass attempts are caught by a dedicated
audit in `scripts/validate.py`.

---

## Phase Overview

| # | Phase | Status | Plan | PR |
|---|-------|--------|------|----|
| 0+1 | Portal Foundation and DQ Infrastructure | COMPLETE | docs/plans/PLAN-ops-decisions-phase-0-1.md | (fill in after merge) |
| 2 | Semantic Definition Session | NOT_STARTED | (fill in) | (fill in) |
| 3a | Migration and Reader-Port | NOT_STARTED | (fill in) | (fill in) |
| 3b | Markdown Delete | NOT_STARTED | (fill in) | (fill in) |
| 4 | Data Correction | NOT_STARTED | (fill in) | (fill in) |
| 5 | DQ Graduation | NOT_STARTED | (fill in) | (fill in) |
| 6 | Convergence | NOT_STARTED | (folds into INTENT-dq-enforcement Phase 5) | (folds in) |

**Phase 2 is a blocking gate on Phase 3a.** Migration runs against the schema
and semantic rules ratified in Phase 2. Migrating with placeholder rules
invites a second migration when Phase 2 narrows the rules.

**Phase 3a is a blocking gate on Phase 3b.** The markdown delete commits only
after Phase 3a's verification gate has passed on main. Splitting into two PRs
preserves a clean rollback path: if any reader regression surfaces after
migration, the markdown file is still present in main-branch git.

**Phase 3a is a blocking gate on Phase 4.** Data corrections route through the
new portal; running corrections before portal foundation and migration land is
impossible.

**Phase 4 is a HARD prerequisite for `INTENT-dq-enforcement.md` Phase 5.** Not
best-effort. If that arc's `enforced` field deletion lands before this arc's
Phase 4 data correction completes, every `enforced: false` check on
`ops_decisions` becomes unconditionally blocking on every CI run while still
failing against uncorrected data. The cross-arc sequencing is enforced by
cross-references in both docs and by agent instructions; do not begin
INTENT-dq-enforcement Phase 5 until this arc's Phase 5 completes.

---

## Phase 0+1: Portal Foundation and DQ Infrastructure

**Status:** COMPLETE

**PR:** agent/ops-decisions-phase-0-1 (fill in URL after merge)

**Prerequisite:** None.

This phase batches what would otherwise be two phases (portal foundation and
DQ infrastructure) because the portal's write-time validators depend on the
DQ manifest annotations being present. They land together or not at all.

### Deliverable 1 (FIRST, MANDATORY): Neuter the postflight ETL bypass

Before any other Phase 0+1 work begins, neuter
`scripts/session_postflight.py::_stage_document_derived_tables` and remove the
`--stage-documents` CLI flag (replace the function body with a single
`logger.warning` noting deferred-decommission state).

Reason: this function runs on every `--close-session` postflight, re-parses
DECISIONS.md, and writes to `ops_decisions` via direct `OpsWriter.write`
(bypassing the portal). If left active during Phases 0+1 through 3a, every
session close re-injects markdown-parsed rows on top of portal-written rows;
SCD2 dedupe on `last_updated_timestamp DESC` resolves to the postflight write
because it runs *after* the portal write. This is the CLAUDE.md-warned
resurrection anti-pattern weaponised against this arc.

`scripts/session_postflight.py` remains on the `validate_warehouse_write_sources`
whitelist until Phase 3a (some tests still import it); the actual write path
is neutered immediately.

### Deliverable 2: DynamoDB counter reconciliation

Current state at planning time: `decisions` counter at 58; max decision ID in
DECISIONS.md is 72. The next `_next_id("decisions")` would allocate 59, an ID
already in use by historical decisions. Re-seed:

1. Parse `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` via
   `decisions_md.parse_decisions_md` (one-shot; the parser is deleted in
   Phase 3a alongside DECISIONS.md).
2. Compute `MAX(decision_id)` across the parsed entries.
3. Implement a NEW helper `reseed_decisions_counter(max_id: int)` in
   `scripts/sync_recommendations.py`. It MUST use:
   `UpdateExpression="SET current_value = :max"`,
   `ConditionExpression="attribute_not_exists(current_value) OR current_value < :max"`,
   `ExpressionAttributeValues={":max": max_id}`.
   This is idempotent (re-running with the same max_id is a no-op via the
   ConditionExpression). Re-running with a HIGHER max_id advances the
   counter. Re-running with a LOWER max_id is rejected by the
   ConditionExpression -- the counter never decreases.
4. DO NOT reuse the existing `seed_counters()` function. That function uses
   unconditional `put_item` which CAN decrease the counter; it is for
   bootstrap of new counter rows only, not re-seeding an existing counter.
   Annotate `seed_counters` with a docstring note to make the distinction
   explicit.
5. After Phase 0+1 lands, running `python -m scripts.sync_recommendations
   --seed` against `decisions` is rejected if it would lower the counter
   (the ConditionExpression in `reseed_decisions_counter` is the gate).

Migration in Phase 3a preserves historical integer IDs verbatim (formatted as
`f"dec-{n:03d}"`); only NEW post-migration decisions consume counter
allocations beyond `MAX(parsed_id)`. The migration script is the single
documented exception to the "file_decision uses the allocator" rule.

### Deliverable 3: Schema evolution -- add new columns (no Iceberg partition spec change)

This deliverable adds two new top-level columns to the `ops_decisions`
Iceberg base table. The Iceberg partition spec
(`day(last_updated_timestamp)`, terraform line 916) is UNCHANGED -- only
the columns are added. The view's window-function `PARTITION BY` (rewritten
in Deliverable 5 below) is a separate concept; do not confuse the two.

- **Columns to add:**
  - `id string` (canonical key post-Phase-5; matches `^dec-\d+$`)
  - `related_decisions_v2 array<string>` (replaces `related_decisions
    array<int>` in Phase 6)
- **Mechanism:** issue `ALTER TABLE` DDL via Athena (workgroup
  `agent-platform-production`, engine v3 required). Per
  `terraform/CLAUDE.md`, `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS`;
  issue one column per statement and ignore "already exists" errors on
  re-run:
  ```sql
  ALTER TABLE trading_formulas_db.ops_decisions ADD COLUMNS (id string);
  ALTER TABLE trading_formulas_db.ops_decisions ADD COLUMNS (related_decisions_v2 array<string>);
  ```
  Terraform CREATE TABLE DDL (lines 903-923) is updated in the same PR so
  fresh deployments include the new columns from the start, but the live-
  table change is via the explicit ALTER above.
- **DO NOT rely on `awswrangler.to_iceberg(schema_evolution=True)` to
  auto-evolve the column on first write.** That path works but couples
  column existence to the first portal write, which couples to Deliverable
  4 backfill -- creating ordering ambiguity. Explicit ALTER decouples.
- **Legacy retention:** `decision_id int` and `related_decisions
  array<int>` remain on the base table through Phase 5. Deprecation lands
  in Phase 6 after the 14-day clean-data window post-Phase-5.
- **Local cache:** `logs/.decisions-index.jsonl` rows carry BOTH the new
  `id` field AND the legacy `decision_id` int until Phase 6. Readers may
  use either key during Phases 3a through 5; the canonical post-Phase-4
  key is `id`.

### Deliverable 4: Backfill id on historical rows (BEFORE the view rewrite)

After Deliverable 3's ALTER TABLE lands, and BEFORE the view rewrite
(Deliverable 5), run a one-shot Iceberg DML to populate `id` on every
historical row:

```sql
UPDATE trading_formulas_db.ops_decisions
SET id = 'dec-' || lpad(CAST(decision_id AS varchar), 3, '0')
WHERE id IS NULL AND decision_id IS NOT NULL;
```

Workgroup `agent-platform-production` (engine v3 required for Iceberg
DML). Verify with `SELECT COUNT(*) FROM ops_decisions WHERE id IS NULL`
returns 0 before proceeding to Deliverable 5.

**Why before the view rewrite:** Deliverable 5 partitions the view by
`id`. If `id IS NULL` on any historical row at the time of view rewrite,
the `ROW_NUMBER() OVER (PARTITION BY id)` window collapses ALL NULL-id
rows into a single winner -- silently hiding ~37 historical decisions
behind one row. Backfilling first ensures every row has a unique `id`
before the view partitions by it.

Optional follow-up (advisory, not a correctness gate):

```sql
OPTIMIZE trading_formulas_db.ops_decisions REWRITE DATA USING BIN_PACK;
VACUUM trading_formulas_db.ops_decisions;
```

Iceberg `UPDATE` produces MERGE-on-read delete files plus new data files;
`OPTIMIZE` compacts them into a single read-optimised data file. `VACUUM`
removes stale snapshots per the table's retention policy. These are
housekeeping, not correctness gates -- skip if Phase 0+1 is time-bound.

### Deliverable 5: SCD2 view rewrite across THREE sources of truth (AFTER backfill)

Only after Deliverable 4 backfill completes (verify `id IS NULL` count =
0 before starting this deliverable), rewrite `ops_decisions_current` to
partition by the new `id` column. The view SQL is duplicated in three
places. ALL THREE must be patched in the SAME PR; missing any one
corrupts the view on the next `_sync_table` call.

1. **Terraform** -- `terraform/iceberg_tables.tf` lines around 1031-1040.
   Update `CREATE OR REPLACE VIEW` to
   `ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp
   DESC)`. Run `terraform apply`.
2. **`scripts/ops_writer.py::_refresh_view`** -- lines around 574-583.
   Update the inline SQL to match. This function re-creates the view on
   every `OpsWriter.compact()` call; if not patched, every portal write
   reverts the view back to `PARTITION BY decision_id`.
3. **`scripts/sync_ops.py`** -- the `_TABLE_TO_VIEW` mapping at line 51
   points at `ops_decisions_current`. No SQL change required, but
   `_coerce_ops_decisions_row` (line 155) must populate both `id` and
   legacy `decision_id` from Athena results.

The Phase 0+1 PR description must include a diff-summary explicitly
listing all three patches as confirmation that the foot-cannon was avoided.

### Deliverable 6: Pydantic Decision model

- Add `Decision(BaseModel)` to `scripts/executor/jsonl_store.py`.
- Required: `id: str` matching `^dec-\d+$`; `title: str`; `status` (placeholder
  Literal in Phase 0+1, narrowed in Phase 2); `created_timestamp`,
  `last_updated_timestamp`.
- Optional: `problem`, `decision_text`, `context`, `decided_date`,
  `related_decisions: Optional[list[int]]` (legacy, deprecated in Phase 6),
  `related_decisions_v2: Optional[list[str]]` (new dec-NNN string IDs).
- Legacy: `decision_id: Optional[int]` (deprecated in Phase 6).
- The existing `Recommendation.validate_id` validator forbids `dec-` prefix;
  that constraint stays in place. Recommendation and decision IDs remain
  disjoint namespaces.
- `model_config = ConfigDict(extra="ignore")` mirrors the Recommendation model.
- **Dual-write invariant validator (MANDATORY):** add a Pydantic
  `@model_validator(mode='after')` that enforces, when both `id` and
  `decision_id` are non-null:
  `int(id.split('-')[1]) == decision_id`. A mismatch raises
  `ValidationError` and the write is rejected. Reason: through Phases 0+1
  to 5, every row carries both keys. Phase 6's column drop assumes
  `decision_id` is a redundant projection of `id`; a single off-by-one
  row (e.g. `id="dec-073"` with `decision_id=72`) poisons that assumption.
- **Sync-side invariant check:** `scripts/sync_ops.py::_coerce_ops_decisions_row`
  must log a sync-reject entry to `_DECISIONS_SYNC_REJECTS_LOG`
  (Deliverable 11) when the same divergence is observed in an Athena row.
  The sync continues but the row is flagged for investigation.

### Deliverable 7: Enrich file_decision and update_decision to file_rec parity

**Signature change audit (BREAKING):** `update_decision`'s first arg type
changes from `int` to `str` (must accept `dec-NNN`). The Phase 0+1 PR
includes a call-site audit step (`grep -rn 'update_decision(' scripts/
tests/ .github/`) and updates every call site in the same PR. The current
skeleton has effectively no production callers, so no deprecation window
is needed; the audit ensures none are missed.

- `file_decision(fields, profile=None, _migration_int_id: Optional[int] = None) -> str`:
  - **`_migration_int_id` is a private parameter, used ONLY by the Phase
    3a migration script.** When set, the function SKIPS
    `_next_id("decisions")` and uses the provided integer to format
    `id = f"dec-{_migration_int_id:03d}"` and
    `decision_id = _migration_int_id`. This is the single documented
    exception to the allocator-bypass rule. The bypass audit (Deliverable
    10) whitelists exactly one caller:
    `scripts/migrate_decisions_to_portal.py`.
  - When `_migration_int_id is None` (the standard path):
    - Allocate ID via `_next_id("decisions")`; format as `f"dec-{n:03d}"`.
    - Dual-write the integer to `decision_id` (Phase 6 deprecates this).
  - Run write-time validators loaded from `config/agent/data_quality/ops.yaml`
    (placeholder shape-only in Phase 0+1; domain-narrowed in Phase 2).
  - `Decision.model_validate(merged)` before write. The dual-write
    invariant validator (Deliverable 6) catches `id`/`decision_id`
    mismatches.
  - On DynamoDB unreachable: queue to
    `logs/.ops-outbox/ops_decisions_pending/` with `_migration_int_id`
    preserved in the queued JSON (when set); return `pending-<uuid>`.
    `drain_pending_decisions` re-applies the preserved int on dequeue.
  - On `--dry-run` (script-level flag, propagated to the portal via a
    portal-level context-manager flag): compute the would-be `id` and
    `decision_id`, log the intent, do NOT call OpsWriter or write to
    local JSONL.
  - `OpsWriter().write("ops_decisions", merged)`.
  - `_append_to_local_jsonl(DECISIONS_JSONL, merged)`.
  - `_sync_table("ops_decisions")` after write (suppressed when batch-
    mode flag is set; the migration script issues ONE trailing sync
    after the full cohort).
- `update_decision(decision_id: str, updates, profile=None) -> bool`:
  - **First arg is now `str` (`dec-NNN`)**, not `int`. Call sites
    updated in the same PR per the audit above.
  - Read existing row from `ops_decisions_current` via Athena (new
    `_fetch_decision_from_athena`). Read query selects `WHERE id = ...`.
    After Deliverable 4 backfill, all rows are reachable.
  - **Until Deliverable 4 backfill completes, `update_decision` raises
    `NotImplementedError`** -- a startup assertion in the function body
    short-circuits to prevent the half-built read path from being called
    by accident. The assertion is removed in the SAME commit as
    Deliverable 4 completion (i.e. the assertion existing is the gate
    that Deliverable 4 has not yet run; removing it is the gate that it
    has).
  - Merge updates; preserve both `id` and `decision_id`. The dual-write
    invariant validator catches any drift.
  - `Decision.model_validate(merged)` before write.
  - `OpsWriter().write`, local JSONL write-through, `_sync_table` after.
- `drain_pending_decisions(profile=None) -> dict`:
  - Drain `logs/.ops-outbox/ops_decisions_pending/` on next session-close
    postflight. Honours `_migration_int_id` if present in the queued JSON.

### Deliverable 8: Canonical reader API

- Add to `scripts/executor/jsonl_store.py`:
  - `load_decision(decision_id: str | int) -> Optional[dict]` -- accepts
    either `dec-NNN` or stringified int for one cycle; resolves to the same
    row.
  - `load_all_decisions() -> dict[str, dict]` -- keyed by `id` (string),
    value contains both `id` and legacy `decision_id`.
  - Both read from `logs/.decisions-index.jsonl` with last-wins semantics.
- Add `DECISIONS_JSONL = Path("logs/.decisions-index.jsonl")` constant.

### Deliverable 9: DQ manifest and write-time validators

- Create `config/agent/data_quality/decisions/ops_decisions.yaml` -- the per-field
  decision manifest. Every field carries `root_cause_class`,
  `human_decision: pending` (Phase 2 narrows to `approved`),
  `enforcement_ready`, `phase4_session`, `notes`, `current_test`,
  `last_verdict`. Mirrors `ops_recommendations.yaml`.
- Enrich `config/agent/data_quality/ops.yaml` `ops_decisions` block with
  `description` and `semantics` per column (extended contract pattern,
  Decision 65).
- All placeholder validators land as `enforced: false` with a
  `phase4_session: ops-decisions-graduation-phase-5` reference. Phase 5 of
  THIS arc graduates them to `enforced: true`, not the dq-enforcement arc.
- Schema-shape validators (`id` matching `^dec-\d+$` via `expression`) land
  in Phase 0+1; domain validators (status `accepted_values`, `decided_date`
  ISO format) defer to Phase 2.

### Deliverable 10: Bypass audit -- extend existing whitelist, do not duplicate

`scripts/validate.py::validate_warehouse_write_sources` (lines 715-779)
already enforces a single whitelist for ALL
`OpsWriter().write("ops_*", ...)` calls across ops_recommendations,
ops_decisions, ops_priority_queue, and others. Current whitelist:
`ops_data_portal.py`, `session_postflight.py`, `sync_ops.py`,
`ops_writer.py`, `s3_log_store.py`, `verify_schema_migration.py`,
`executor/plan.py`, `validate.py`.

Two changes -- DO NOT create a parallel whitelist:

1. **Phase 0+1**: leave `session_postflight.py` on the existing whitelist
   (its function body is neutered in Deliverable 1 but tests still
   import). No new whitelist function added in Phase 0+1.
2. **Phase 3a**: when the migration script lands, ADD
   `scripts/migrate_decisions_to_portal.py` to the existing whitelist for
   the duration of Phase 3a. REMOVE `scripts/session_postflight.py` in
   the same PR (its function body is gone). Phase 3a ends with the
   migration script deleted; the whitelist entry for it is removed in
   the cleanup commit.

For DIRECT writes to the local cache (`logs/.decisions-index.jsonl`), a
separate audit IS needed -- there is no equivalent in
`validate_warehouse_write_sources`. Add `validate_decisions_local_writes()`
to `scripts/validate.py` mirroring the recommendations-side
`validate_recommendations_write_path` (lines around 670-712). Pattern:
search for `.decisions-index.jsonl` writes outside the portal. Whitelist
exactly: `scripts/ops_data_portal.py` (write-through),
`scripts/sync_ops.py` (cache rebuild).

The Phase 0+1 PR description must include a `grep` audit enumerating
every current `ops_decisions` write site AND every direct
`.decisions-index.jsonl` write site, confirming both audits capture the
right callers before lockdown.

### Deliverable 11: Observability scaffolding

- Add `_DECISIONS_SYNC_REJECTS_LOG = _LOGS_DIR / "debug" / "decisions-sync-rejects.jsonl"`
  to `scripts/sync_ops.py`, mirroring the recommendations reject log at
  line 68.
- Reserve the Phase 3a migration-report artefact path:
  `logs/debug/decisions-migration-report.jsonl`. Phase 0+1 does not write
  to it; Phase 3a does.

### Files in scope

| File | Change |
|------|--------|
| scripts/session_postflight.py | Deliverable 1: neuter `_stage_document_derived_tables`; remove `--stage-documents` CLI |
| terraform/iceberg_tables.tf | Deliverables 3 and 4: add `id`, `related_decisions_v2` columns; rewrite `ops_decisions_current` view |
| scripts/ops_writer.py | Deliverable 4: update inline view SQL in `_refresh_view` |
| scripts/sync_ops.py | Deliverable 4: populate both keys in `_coerce_ops_decisions_row`; Deliverable 11: rejects log |
| scripts/executor/jsonl_store.py | Deliverable 6: Decision model; Deliverable 8: reader API; `DECISIONS_JSONL` constant |
| scripts/ops_data_portal.py | Deliverable 7: enriched file_decision/update_decision/drain_pending_decisions; `_fetch_decision_from_athena` |
| scripts/sync_recommendations.py | Deliverable 2: counter re-seed procedure (idempotent max-set) |
| scripts/validate.py | Deliverable 10: `validate_decisions_write_path` bypass audit |
| config/agent/data_quality/ops.yaml | Deliverable 9: enrich `ops_decisions` block with description, semantics, shape validators (enforced: false) |
| config/agent/data_quality/decisions/ops_decisions.yaml | Deliverable 9: new file, per-field decision manifest |
| tests/ | Tests for Pydantic Decision, enriched portal, reader API, bypass audit, offline drain, counter re-seed, view rewrite |

### Verification gate

- DynamoDB counter for `decisions` >= `MAX(parsed_id)` from DECISIONS.md.
- `OpsWriter._refresh_view` SQL for `ops_decisions_current` partitions by `id`.
- `validate.py` exits 0; bypass audit reports no violations.
- New manifest YAML present; ops.yaml `ops_decisions` block carries
  `description` + `semantics` per column.
- Backfill SQL has run: `SELECT COUNT(*) FROM ops_decisions WHERE id IS NULL`
  returns 0.
- `_stage_document_derived_tables` body is the neutered no-op.

---

## Phase 2: Semantic Definition Session

**Status:** NOT_STARTED

**Prerequisite:** Phase 0+1 merged.

This phase is a human-in-loop session, not an autonomous implementation. The
pattern matches the 2026-05-06 session that produced
`config/agent/data_quality/decisions/ops_recommendations.yaml`: the human and a
planning agent walk each field, classify root cause where relevant, ratify
the accepted-values domain, decide write-time vs query-time enforcement, and
update the decision manifest from `human_decision: pending` to
`human_decision: approved`.

### Where do Phase 2 ratification decisions go?

DECISIONS.md remains the canonical store through end of Phase 2 (decommission
happens at end of Phase 3b, not earlier). Phase 2 ratification decisions are
APPENDED to `docs/DECISIONS.md` as the final markdown entries; they are
re-filed via the portal in Phase 3a along with everything else.

This resolves the Phase 2 chicken-and-egg surfaced during the 2026-05-13
critique cycle: with `_stage_document_derived_tables` neutered in Phase 0+1
Deliverable 1, the postflight resurrection vector is closed; Phase 2 markdown
edits remain in DECISIONS.md only (no portal writes); Phase 3a migration
ingests everything in one consistent sweep, Phase 2 entries included.

### Fields requiring semantic ratification

- `status`: current free-text drift includes `"Decided"`,
  `"Decided -- March 2026"`,
  `"Agent-decided -- pending human review. Implementation verified..."`,
  `"Empirical finding from rec-027 validation..."`, `"Accepted Risk"`,
  `"open"`, `"Superseded by Decision 37 (April 2026)"`, and the empty string.
  Narrow to enum. Proposal: `Decided | Superseded | Open | Declined`. Free-text
  colour-commentary either drops on the floor or migrates to `context` /
  a new `decision_notes` field; ratify in session.
- `decided_date`: current drift includes `""`, `"April 2026"`, `"March 2026"`,
  `"2026-04-23"`. Normalise to ISO 8601 date string or null. Ratify.
- `related_decisions_v2`: new column added in Phase 0+1, populated in Phase 4
  from `related_decisions` integers per the int-to-dec-NNN mapping ratified
  in this session.
- `superseded_by`: proposed new field `array<string>` of `dec-NNN`. Curator
  query pattern: "is this decision still valid?". Ratify or defer.
- `problem`, `decision_text`, `context`: today free-text. Ratify minimum
  length, required-or-optional, write-time validators (e.g. >= 80 stripped
  chars for `context`, mirroring recommendations).
- New telemetry-shaped fields (e.g. `decided_by`): ratify which (if any)
  land in this arc vs deferred.

### Deliverables

- `config/agent/data_quality/decisions/ops_decisions.yaml` fully populated: every
  field has `human_decision: approved` with a `decided_action` and a clear
  enforcement rule.
- `config/agent/data_quality/ops.yaml` `ops_decisions` block updated with the
  ratified `accepted_values` lists, `write_time: true` validators, and
  `expression` checks.
- DECISIONS.md gets the Phase 2 ratification decisions appended as the final
  markdown entries before decommission.

### Files in scope

| File | Change |
|------|--------|
| config/agent/data_quality/decisions/ops_decisions.yaml | Populate every field with approved decisions |
| config/agent/data_quality/ops.yaml | Narrow accepted_values, add write_time validators, add expression checks |
| docs/DECISIONS.md | Append ratification decisions (last entries before decommission) |
| docs/dq/DQ_REMEDIATION_METHODOLOGY.md | Cross-link this arc as a second worked example of the per-field manifest pattern |

---

## Phase 3a: Migration and Reader-Port

**Status:** NOT_STARTED

**Prerequisite:** Phase 2 merged.

Single PR. Verification gate gates merge. After this PR lands on main,
`ops_decisions_current` carries all 52+ historical decisions plus the Phase 2
ratifications; all DECISIONS.md readers and writers have been ported;
DECISIONS.md itself remains on disk pending Phase 3b.

### Comprehensive consumer audit (MANDATORY)

`grep -r 'DECISIONS\.md\|DECISIONS_ARCHIVE\.md' .` returned 179 hits at
planning time. Every hit is triaged in this PR; the previous "approximately
20 files" estimate was a gross undercount. Categories:

- **Active writers** (port FIRST, before migration runs):
  `.github/agents/retrospective.agent.md` files new decisions to
  DECISIONS.md. If left unported, it re-creates the file after Phase 3b
  deletes it. Convert to `file_decision()` portal calls.
  `.github/prompts/strategic_review.prompt.md` archives entries to
  DECISIONS_ARCHIVE.md -- also a writer.
- **Active readers** (port DURING migration):
  planning/implement/plan-critique/develop-executor skills,
  `scripts/session_preflight.py` (the `open_decisions_count` metric),
  scheduled-agent prompts under `.github/prompts/scheduled/` (e.g.
  `doc-freshness`, `prompt-quality`).
- **Documentation/runtime references** (update text):
  `.github/copilot-instructions.md`, `GEMINI.md`, `CLAUDE.md` (root),
  `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`,
  `docs/ARCHITECTURE-WORKFLOW.md`, `docs/ROADMAP-PRODUCT.md`, `docs/ROADMAP-PLATFORM.yaml`, `docs/CHANGELOG.md`,
  `docs/contracts/ops-data-store.md`, scheduled-agent Terraform comments
  at `terraform/scheduled_agents.tf`, runtime header comments in
  `scripts/copilot_sdk_client.py`, `.github/workflows/deploy.yml` (header
  comment referencing DECISIONS.md escalation strategy).
- **Divergent agent-harness trees** (update BOTH; they are NOT mirrors):
  `.antigravity/workflows/*` and `.agents/workflows/*` are two separate
  trees with different file contents (e.g. `.antigravity/workflows/`
  includes `build_cv_refactored.md`, `ci_triage.md`, `documentation.md`,
  `documentation_full_audit.md`, `strategic_review.md` that are NOT in
  `.agents/workflows/`). Both trees require independent triage. The Phase
  3a planner enumerates the full file list per tree before scoping the port.
- **Historical references** (leave as-is): roughly 100
  `docs/plans/PLAN-*.md` files contain textual references to "Decision N" or
  "DECISIONS.md". These are immutable historical record and do not need
  updating.
- **Tests** (update assertions): any test that asserts on DECISIONS.md
  content (e.g. `tests/test_session_postflight.py`,
  `tests/test_list_customizations.py`).

The Phase 3a PR description includes the triaged grep audit table. No
category is hand-waved.

### Migration script with idempotency contract

`scripts/migrate_decisions_to_portal.py` (one-shot, deleted at end of phase):

1. Parse `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` via
   `decisions_md.parse_decisions_md`.
2. Query `ops_decisions_current` for every existing `decision_id`. Build the
   set of integers already present.
3. For each parsed entry, branch:
   - If the entry's `decision_id` is already present in
     `ops_decisions_current`: call `update_decision(f"dec-{n:03d}", fields)`.
     The portal merges over the existing row; SCD2 produces a new version;
     `_current` resolves to the new version. No duplicate id.
   - If the entry's `decision_id` is NOT present: call
     `file_decision(fields, _preserve_int_id=n)` with the integer ID
     preserved. The migration is the SINGLE documented exception to the
     allocator-bypass rule. The Phase 0+1 counter re-seed ensures
     post-migration `file_decision` allocations land above `MAX(parsed_id)`.
4. Support `--dry-run`: report parsed count, existing-id count, would-file
   count, would-update count, without writing.
5. Idempotent re-run: a second invocation observes existing rows in
   `ops_decisions_current` and routes them all to `update_decision`. No
   duplicate `id` values; the only side-effect of re-run is N more SCD2
   versions on rows already present.
6. Batch compaction: suppress per-call `_sync_table` during the script run
   via a context-manager flag in the portal; issue ONE trailing
   `_sync_table("ops_decisions")` + `OpsWriter().compact()` +
   `OPTIMIZE ... REWRITE DATA USING BIN_PACK` + `VACUUM` against workgroup
   `agent-platform-production`.
7. Write a migration report to `logs/debug/decisions-migration-report.jsonl`:
   one line per parsed entry with fields `parsed_decision_id`, `action`
   (`filed` / `updated` / `skipped` / `rejected`), `final_id`, `error`.

### Verification gate (rewritten from the unsatisfiable prior version)

The prior INTENT had `count(_current) == count(parsed)` which is
unsatisfiable today (37 live vs 52 parsed). New gate:

1. **Distinct id parity**: `SELECT COUNT(DISTINCT id) FROM ops_decisions_current`
   equals the parsed-entries count after migration. Exact equality.
2. **Title spot-check**: random sample of at least 10% (>= 6) parsed entries
   -- query each by `id`, assert `title` matches verbatim.
3. **No NULL id**: `SELECT COUNT(*) FROM ops_decisions_current WHERE id IS NULL`
   returns 0.
4. **Counter advanced**: DynamoDB `decisions` counter value
   >= `MAX(parsed_id)`.
5. **DQ runner no regression**: `enforced: true` checks PASS before and
   after migration (Phase 0+1 placeholder validators are all
   `enforced: false`, so this gate verifies the few existing
   `enforced: true` checks like `row_count` did not regress).
6. **Migration report present**: `logs/debug/decisions-migration-report.jsonl`
   exists and contains one entry per parsed decision.

### Reader migration

Update every active reader to:

- Query `ops_decisions_current` via Athena (e.g. session_preflight metric),
  or
- Read `logs/.decisions-index.jsonl` via `load_decision`/`load_all_decisions`
  from `jsonl_store.py` (e.g. skill files that need to enumerate decisions).

Updated readers MUST NOT read `docs/DECISIONS.md`. The bypass audit catches
DECISIONS.md reads in code from this PR forward.

### Writer migration

`.github/agents/retrospective.agent.md` and
`.github/prompts/strategic_review.prompt.md` (plus any other DECISIONS.md
writers discovered in the grep audit) are converted to `file_decision()`
portal calls. Existing DECISIONS.md write paths are removed from the agent
prompts in the same PR.

### Bypass audit lockdown

- Remove `scripts/session_postflight.py` from the
  `validate_warehouse_write_sources` whitelist for ops_decisions calls
  (function body was neutered in Phase 0+1; this PR removes the whitelist
  entry).
- Delete `scripts/decisions_md.py` AFTER the migration script has used it
  one final time.
- Delete `scripts/list_customizations.py::build_decisions_index` (orphan
  duplicate parser).

### Doc updates

- `CLAUDE.md` root: revise the "Memory policy" section. DECISIONS.md is no
  longer canonical persistence; `ops_decisions` is. CLAUDE.md files,
  `docs/SESSION_LOG.md`, and `logs/.recommendations-log.jsonl` remain
  canonical for their respective concerns.
- `docs/PROJECT_CONTEXT.md`: update Single Portal Invariant wording. Remove
  DECISIONS.md references.
- `.github/copilot-instructions.md` and `GEMINI.md`: mirror updates.
- `docs/contracts/ops-data-store.md`: add `ops_decisions` to the canonical
  write-path table; document the migration outcome.
- `docs/SESSION_LOG.md`: add a session entry recording the migration.

### Files in scope

Approximately 30-40 files (precise count produced by the Phase 3a grep audit
at session start). The migration script, all reader and writer consumers,
all documentation updates, plus the `decisions_md.py` and
`build_decisions_index` deletions.

---

## Phase 3b: Markdown Delete

**Status:** NOT_STARTED

**Prerequisite:** Phase 3a merged on main; Phase 3a verification gate still
PASSES on main when re-run at the start of the Phase 3b session (live state
may have drifted in the gap between PRs).

Separate PR, single commit:
`git rm docs/DECISIONS.md docs/DECISIONS_ARCHIVE.md` plus removal of any path
references the grep audit missed. Final-state verification:

- `test ! -f docs/DECISIONS.md && test ! -f docs/DECISIONS_ARCHIVE.md`
- `git log --diff-filter=D --name-only -- docs/DECISIONS.md` returns the
  deletion commit.
- `grep -r 'DECISIONS\.md' . --include='*.py' --include='*.yaml'
  --include='*.tf' --include='*.json' --exclude-dir=.git --exclude-dir=logs
  --exclude='docs/plans/PLAN-*.md'` returns 0 hits in active code paths.
  Historical PLAN-*.md hits are acceptable; they are immutable history.

If any reader regression surfaces in the gap window between Phase 3a merge
and Phase 3b merge, the rollback path is "revert the Phase 3b PR" -- the
markdown is still in main-branch git history.

---

## Phase 4: Data Correction

**Status:** NOT_STARTED

**Prerequisite:** Phase 3a and 3b merged.

Apply the Phase 2 ratified rules to historical data via `update_decision`
calls.

- Normalise `status` free-text to enum values per the Phase 2 mapping table.
- Backfill or `superseded`-mark missing `decision_id` rows per Phase 2
  root-cause class. Records with no recoverable identity are marked declined
  or superseded rather than deleted (append-only invariant).
- Normalise `decided_date` strings to ISO 8601 per Phase 2 rules.
- Populate `related_decisions_v2 array<string>` per the Phase 2
  int-to-dec-NNN mapping table.

Each correction is a portal `update_decision` call. No direct SQL DML. No
JSONL edits. The append-only invariant is preserved.

After this phase, the DQ runner reports PASS on every check in
`ops_decisions` that Phase 5 will graduate.

---

## Phase 5: DQ Graduation

**Status:** NOT_STARTED

**Prerequisite:** Phase 4 merged; DQ runner reports PASS on the targeted
checks.

Flip `enforced: false` to `enforced: true` for the targeted checks in
`config/agent/data_quality/ops.yaml`:

- `recency` on `last_updated_timestamp`
- `id` not_null + regex match
- `status` accepted_values
- Any write-time-enforced checks added in Phase 2 that are not already
  enforced

The graduation guard in `scripts/validate.py` (added by Phase 3 of
`INTENT-dq-enforcement.md`) catches unsafe flips: it rejects any flip from
`enforced: false` to `enforced: true` when the check's verdict in
`logs/debug/dq-latest.json` is not `PASS`.

After this phase, all `ops_decisions` checks are `enforced: true` or
removed. **Only after this phase lands may `INTENT-dq-enforcement.md` Phase 5
begin.**

This arc -- not `INTENT-dq-enforcement.md` -- is responsible for graduating
`ops_decisions` checks. See Decision Registry.

---

## Phase 6: Convergence

**Status:** NOT_STARTED

This phase has no plan of its own. It folds into Phase 5 of
`docs/INTENT-dq-enforcement.md` (the `enforced` field deletion). Once that
arc reaches convergence, the `enforced: true/false` annotations on
`ops_decisions` are deleted along with the rest.

Additionally, after a 14-day clean-data window post-Phase-5, this phase
removes the legacy schema (a separate PR within the convergence arc's
session):

- Drop `decision_id int` column from the Iceberg base table.
- Drop `related_decisions array<int>` column from the Iceberg base table.
- Remove the legacy keys from local cache schema, `Decision` Pydantic model,
  and reader API.
- Remove dual-write logic from `file_decision`/`update_decision`.

A `terraform apply` is required for the column drops.

---

## Known Gaps

These are unresolved issues that are not blocking current work but must be
documented so future agents do not assume they are handled.

**Legacy `decision_id int` column retention through Phase 5:** Through Phases
0+1 to 5 the integer column lives alongside the new `dec-NNN` string `id`.
Readers must not assume the int column is current after Phase 4 (the
post-correction `id` is canonical). Deprecation lands in Phase 6 after the
14-day clean-data window.

**Phase 0+1 placeholder validators:** The write-time validators shipped in
Phase 0+1 enforce schema shape (id regex, required not-null) but not domain
(status accepted_values, decided_date ISO format). All placeholder validators
land as `enforced: false`. Sessions between Phase 0+1 and Phase 2 must not
rely on placeholder accepted_values lists as authoritative.

**Historical PLAN-*.md DECISIONS.md textual references:** The grep audit in
Phase 3a returns roughly 100 textual references in immutable historical PLAN
files (e.g. "per Decision 50"). These are not ported; they are immutable
history. Active code, skill, and agent paths must be ported; historical
narrative records are left as-is.

**Live state numbers in this doc are 2026-05-12 snapshots.** Agents starting
any phase must re-query Athena, DynamoDB, and grep at session start. Numbers
above are illustrative of the planning context, not authoritative for
execution.

---

## Decision Registry

These design decisions were ratified during the 2026-05-12 planning session
and the 2026-05-13 multi-perspective critique cycle. They must be
re-litigated only with a new decision filed via `file_decision()` (post Phase
3a) or via DECISIONS.md (Phase 2 and earlier).

**[DECIDED] DECISIONS.md is decommissioned**

Markdown narrative for architectural decisions is replaced by structured
append-only records in `ops_decisions`. Decommission is the final step of
Phase 3b. Rationale: Agent-First Repository principle, Decision 50, persistent-
agent-memory advantage of structured queryable data.

**[DECIDED] dec-NNN string ID format with dual-write transition**

`ops_decisions.id` is `string` matching `^dec-\d+$`. Both `id` and legacy
`decision_id int` are populated through Phase 5; the legacy int is
deprecated in Phase 6. Local cache rows carry both keys; readers may use
either during the transition. Canonical post-Phase-4 key is `id`.

**[DECIDED] Historical integer decision IDs preserved verbatim during migration**

The migration script in Phase 3a does NOT re-allocate IDs through the
DynamoDB counter. Existing integer IDs become `dec-NNN` directly. The
counter is re-seeded to `MAX(parsed_id)` in Phase 0+1 (Deliverable 2) so
post-migration portal calls allocate from above the historical range. The
migration script is the single documented exception to the
"file_decision uses the allocator" rule.

**[DECIDED] `_stage_document_derived_tables` neutered at START of Phase 0+1**

The postflight ETL bypass is neutered on Phase 0+1 day one
(Deliverable 1), not at the end of Phase 3a. Reason: the function runs every
session-close and re-stages markdown-parsed rows over portal-written rows;
leaving it active during the transition window creates the resurrection
vector CLAUDE.md warns against.

**[DECIDED] Semantic Definition Session before migration**

Phase 2 is a human-in-loop ratification phase that runs before Phase 3a
migration. Ratifying semantic rules first prevents the bootstrap-cohort
drift that bit `ops_recommendations` (where rules were narrowed after
migration, producing FAIL verdicts on legacy data).

**[DECIDED] Phase 2 ratification decisions append to DECISIONS.md**

DECISIONS.md remains the canonical store through end of Phase 2. Phase 2
ratification decisions are appended as the final markdown entries and
re-filed via portal in Phase 3a along with everything else. With Phase 0+1
Deliverable 1 closing the resurrection vector, this is safe; the alternative
(filing Phase 2 decisions through the half-built portal before migration)
creates an asymmetric state across DECISIONS.md and `ops_decisions`.

**[DECIDED] Phase 3 split into 3a (migration + reader/writer port) and 3b (markdown delete)**

Separate PRs. The markdown delete commits only after Phase 3a's verification
gate has passed on main. This preserves a clean rollback path if reader
regressions surface in the grace window between PRs.

**[DECIDED] Phase 4 is a HARD prerequisite for INTENT-dq-enforcement Phase 5**

Not best-effort -- a hard sequencing constraint. If `enforced` is deleted
globally before this arc's Phase 4 data correction completes, every
`enforced: false` check on `ops_decisions` becomes unconditionally blocking
on every CI run while still failing against uncorrected data. Cross-arc PRs
do not begin until this arc's Phase 5 lands. The constraint is enforced by
agent instructions in both INTENT docs.

**[DECIDED] ops_decisions DQ check graduation owned by this arc**

This arc's Phase 5 graduates `ops_decisions` checks from
`enforced: false` to `enforced: true`. The dq-enforcement arc's Phase 4
Session Map redirects `ops_decisions` here. The dq-enforcement arc's Phase 5
deletes the `enforced` field globally, including from `ops_decisions`, only
after this arc completes.

**[DECIDED] SCD2 view rewrite must patch THREE sources of truth in one PR**

Terraform, `OpsWriter._refresh_view`, and `sync_ops` coercion must all
update in the same PR. Missing any one corrupts the view on the next
`_sync_table` call. The Phase 0+1 PR description must include a diff-summary
confirming all three patches landed.

**[DECIDED] No source registry for decisions**

Unlike `ops_recommendations.source`, decisions do not get a source-registry-
validated lineage key in Phase 0+1. Deferred unless Phase 2 surfaces a
strong case.

**[DECIDED] Portal-first; ETL bypass functions deleted**

`session_postflight._stage_document_derived_tables` is neutered in Phase 0+1
and removed from the warehouse-write whitelist in Phase 3a.
`scripts/decisions_md.py` and `list_customizations.build_decisions_index`
are deleted in Phase 3a (after the one-shot migration script uses the
parser for the final time).

**[DECIDED] Phase 0+1 batches portal foundation with DQ infrastructure**

Splitting them would ship a portal whose write-time validators have nothing
to validate against. They land together.

**[DECIDED] Phase 0+1 internal deliverable ordering: D3 -> D4 -> D5**

Schema evolution (D3, `ALTER TABLE`) precedes backfill (D4, `UPDATE`)
precedes view rewrite (D5, `PARTITION BY id`). Reason: the view rewrite
assumes every row has a non-NULL `id`. Running it before backfill collapses
all NULL-id rows into a single winner in the `_current` view, silently
hiding history. Reversing D4 and D5 relative to the 2026-05-12 first draft
closes this window.

**[DECIDED] Dual-write invariant enforced by Pydantic root-validator**

The `Decision` model includes a `@model_validator(mode='after')` that
enforces `int(id.split('-')[1]) == decision_id` when both are set.
`_coerce_ops_decisions_row` logs sync-rejects on divergence. Phase 6's
column drop depends on this invariant holding for every row.

**[DECIDED] `_migration_int_id` is a private portal parameter**

A single private kwarg on `file_decision`
(`_migration_int_id: Optional[int] = None`) implements the migration's
allocator-bypass. Whitelisted to exactly one caller
(`scripts/migrate_decisions_to_portal.py`). The pending outbox carries
the preserved int through offline-drain. `--dry-run` propagates via a
portal-level context-manager flag.

**[DECIDED] Counter re-seed uses SET + ConditionExpression, not put_item**

A new helper `reseed_decisions_counter(max_id)` in
`sync_recommendations.py` uses `UpdateExpression="SET current_value =
:max"` with
`ConditionExpression="attribute_not_exists(current_value) OR
current_value < :max"`. Idempotent and monotonic. Distinct from the
existing `seed_counters` which is unconditional `put_item` (bootstrap
only, not re-seed).

**[DECIDED] Column-add via Athena ALTER TABLE, not awswrangler schema-evolution**

The `id string` and `related_decisions_v2 array<string>` columns are
added explicitly via Athena DDL `ALTER TABLE ADD COLUMNS` in Phase 0+1
Deliverable 3. The `awswrangler.to_iceberg(schema_evolution=True)` path
is NOT relied upon because it couples column existence to the first
portal write, creating ordering ambiguity with Deliverable 4 backfill.
Terraform CREATE TABLE DDL is updated in the same PR for fresh-deployment
consistency, but the live-table change is via explicit ALTER.

**[DECIDED] Single whitelist via extension; no parallel write-source audits**

`validate_warehouse_write_sources` is extended (not duplicated) to govern
`ops_decisions` write sources. A separate `validate_decisions_local_writes`
audit guards the local cache (`.decisions-index.jsonl`); this mirrors the
recommendations-side pattern at lines around 670-712 and avoids
dual-whitelist drift.

**[DECIDED] update_decision raises NotImplementedError until Deliverable 4 lands**

The first arg of `update_decision` changes from `int` to `str` and reads
by `id`. Until Deliverable 4 backfill completes, the read path returns
empty for historical rows. The function raises `NotImplementedError` in
the interim; the startup assertion is removed in the same commit as
Deliverable 4 completion. This ensures the half-built read path is never
called by accident.

---

## Agent Instructions

**Before scoping any ops_decisions work:**

1. Read this document in full.
2. Find the first phase with `Status: NOT_STARTED`. That is the current work
   frontier.
3. If a phase is `IN_PROGRESS`, read its Plan file before adding to its
   scope.
4. Check all prerequisites for the target phase before planning.
5. Cross-check `docs/INTENT-dq-enforcement.md` for any phase-status updates
   that affect this arc.
6. Refresh the "Live State at Planning Time" numbers by re-querying: Athena
   `ops_decisions_current` row count; DynamoDB `decisions` counter value;
   `grep -rc 'DECISIONS\.md' .`; max parsed decision ID.

**When a phase's PR merges, update this document:**

Create a branch (e.g. `chore/ops-decisions-status-phase-N`), edit the Phase
Overview table and the phase's own Status and PR fields in-place, and open a
PR. Do not commit directly to `main` -- the `never_on_main` hook will block
it.

**Do not:**

- Bypass the portal once Phase 0+1 lands. Every write to `ops_decisions`
  must originate from `file_decision`, `update_decision`,
  `drain_pending_decisions`, or the one-shot Phase 3a migration script.
- Edit `docs/DECISIONS.md` once Phase 3b lands. The file does not exist
  after that point.
- Skip Phase 2. Migration into an unratified schema produces a second
  migration when Phase 2 narrows the rules.
- Begin `INTENT-dq-enforcement.md` Phase 5 until this arc's Phase 5 has
  merged. The cross-arc sequencing is HARD.
- Allocate decision IDs through the migration script outside Phase 3a. The
  script is the single documented allocator-bypass.
- Patch the `ops_decisions_current` view SQL in only one of the three
  source-of-truth locations. All three must update atomically in the same
  PR; the Phase 0+1 PR description must confirm.

**When filing a new decision (post Phase 3a):**

Call `file_decision()`. The portal handles ID allocation, Pydantic
validation, write-time validators, local JSONL write-through, and Athena
sync. Do not edit `logs/.decisions-index.jsonl` directly.

**When superseding a decision (post Phase 3a):**

Call `update_decision(decision_id, {"status": "Superseded", ...})`. Do not
manually rewrite the prior decision's row; SCD2 append-only handles the
version history.

---

## What This Document Does Not Cover

- Per-phase implementation detail. Each phase has its own `PLAN-{slug}.md`
  once /plan opens for that phase.
- The `enforced` field deletion -- folded into
  `docs/INTENT-dq-enforcement.md` Phase 5 (gated on this arc's Phase 5
  completing first).
- Telemetry-shaped extensions of the Decision schema (e.g. `decided_by`) --
  deferred to Phase 2 ratification.
- Other ops tables (`ops_priority_queue`, `ops_session_log`,
  `ops_execution_plans`). Those tables graduate under their own INTENT docs
  when started.
- Historical PLAN-*.md textual references to DECISIONS.md. These are not
  ported; they are immutable history.

---

**Last updated:** 2026-05-13
**Planning sessions:** e3d337ad-1673-41ff-ab60-ca893dc87747 (initial),
2026-05-13 critique-cycle revision
