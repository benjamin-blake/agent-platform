# Plan

## Intent
Graduate `ops_recommendations` status and risk domain-corruption violations to clean Athena
state: tombstone 33 bad-status records (22 'Decided' + 9 'Unknown' + 2 empty-string), implement
the deterministic risk derivation formula in `ops_data_portal`, backfill ~34 invalid-domain risk
records, and land two write-path guards (rec-594 Pydantic Literal for status; `compute_risk()`
derivation). Persists Precision Context Injection as Decision 66 and ambient CLAUDE.md principle.
Advances Wave 3 of the Phase 4 DQ resolution arc (`docs/INTENT-dq-enforcement.md`).

## Plan Type
IMPLEMENTATION
(Step count is 9 -- boundary case; scope is coherent, bounded, and executable in one session.)

## Verification Tier
V3

## Branch
agent/dq-wave3-domain-corruption

## Phase
Platform: Phase 4 Wave 3 (domain corruption -- `docs/INTENT-dq-enforcement.md` Session Map)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/executor/jsonl_store.py` | Modify | Add `Literal[...]` to `status`; fix stale `risk` description |
| `scripts/ops_data_portal.py` | Modify | Add `compute_risk(file, effort) -> str`; derive risk in `file_rec()` |
| `config/data_quality/ops.yaml` | Modify | Graduate `status.accepted_values` from `enforced: false` to `enforced: true` after live DQ PASS |
| `docs/DECISIONS.md` | Modify | Add Decision 66: Precision Context Injection |
| `CLAUDE.md` | Modify | Add Precision Context Injection to Agent-First section |
| `requirements.txt` | Modify if absent | Add `radon` if not already present (production dep -- runs in portal) |

## Bundled Recommendations
- **rec-594** (High/XS, open): Pydantic Literal validation for status -- write-path guard preventing
  recurrence of 'Decided'/'Unknown' domain pollution after tombstone.

## Infrastructure Dependencies
None. Portal writes go through `OpsWriter` to Iceberg via the existing outbox drain path.
No Terraform or Lambda changes.

## Acceptance Criteria
- [ ] `Recommendation(id="rec-001", status="Decided")` raises `ValidationError`
- [ ] `compute_risk("scripts/ops_data_portal.py", "M")` returns one of `low|medium|high`
- [ ] 0 records with `status NOT IN ('open','closed','failed','declined','superseded')` in
      synced local JSONL (sourced from Athena `_current` view via `sync_ops pull`)
- [ ] 0 records with `risk NOT IN ('low','medium','high')` AND `risk IS NOT NULL` in synced
      local JSONL
- [ ] `status.accepted_values` check shows PASS in a live DQ run (SSO-conditional; if SSO
      unavailable, defer graduation with inline comment)
- [ ] `DECISIONS.md` contains "Decision 66" and "Precision Context Injection"
- [ ] `CLAUDE.md` Agent-First section contains `get_rec_write_guidance` and
      "Precision Context Injection"

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Status Literal guard rejects invalid value | `.venv/Scripts/python.exe -c "from scripts.executor.jsonl_store import Recommendation; Recommendation(id='rec-001', status='Decided')"` | `ValidationError` printed to stderr | Literal guard not applied; check import and field annotation |
| 2 | pre-deploy | `compute_risk()` returns valid tier | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import compute_risk; r=compute_risk('scripts/ops_data_portal.py','M'); assert r in ('low','medium','high'), f'unexpected: {r}'"` | No AssertionError | Formula or threshold logic incorrect; check radon subprocess call and S-mapping |
| 3 | pre-deploy | Count bad-status candidates before tombstone | `.venv/Scripts/python.exe -c "import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip()]; bad=[r['id'] for r in recs if r.get('status','') not in ('open','closed','failed','declined','superseded','') or r.get('status','')==''];  print(len(bad),'bad-domain or empty-string records')"` | Prints count confirming targets exist (expect ~33) | If 0, data already clean -- skip Step 3, proceed to risk backfill |
| 4 | post-deploy | 0 bad-status records after tombstone + sync | `.venv/Scripts/python.exe -m scripts.sync_ops pull && .venv/Scripts/python.exe -c "import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip()]; bad=[r['id'] for r in recs if r.get('status','') not in ('open','closed','failed','declined','superseded')]; assert not bad, f'still bad: {bad}'"` | No AssertionError | Tombstone incomplete; check portal write succeeded and sync pulled latest Athena state |
| 5 | post-deploy | 0 invalid-domain risk records after backfill + sync | `.venv/Scripts/python.exe -m scripts.sync_ops pull && .venv/Scripts/python.exe -c "import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip()]; bad=[r['id'] for r in recs if r.get('risk') and r['risk'] not in ('low','medium','high')]; assert not bad, f'still invalid: {bad}'"` | No AssertionError | Backfill incomplete; check records with null file or effort were skipped intentionally |
| 6 | post-deploy | DQ runner: `status.accepted_values` PASS | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml 2>&1 \| grep -i "accepted_values\|status"` | Line containing `status` shows `PASS` | Data correction incomplete or SSO unavailable; if SSO unavailable defer graduation |
| 7 | pre-deploy | Decision 66 present in DECISIONS.md | `.venv/Scripts/python.exe -c "c=open('docs/DECISIONS.md').read(); assert 'Decision 66' in c and 'Precision Context Injection' in c"` | No AssertionError | Add Decision 66 to DECISIONS.md |
| 8 | pre-deploy | CLAUDE.md principle present | `.venv/Scripts/python.exe -c "c=open('CLAUDE.md').read(); assert 'get_rec_write_guidance' in c and 'Precision Context Injection' in c"` | No AssertionError | Add principle to Agent-First section in CLAUDE.md |

## Constraints
- **Never direct-edit `logs/.recommendations-log.jsonl`** -- all corrections go through
  `scripts/ops_data_portal.py` (Single Portal Invariant, CLAUDE.md).
- **Tombstone, never hard-delete.** All bad-status records get `status=superseded` via
  `update_rec()` with a `resolution` field. Resolution text by category:
  - 22 'Decided' dec-XXX records: `"domain-pollution: ops_decisions entry written to ops_recommendations during early migration -- tombstoned wave-3"`
  - 9 'Unknown' records: `"migration-artifact: status normalised post-migration -- tombstoned wave-3"`
  - 2 empty-string status records: `"bootstrap-artifact: pre-enforcement empty status -- tombstoned wave-3"`
  - rec-001/rec-002 stubs: `"stub-record: bootstrap artifact with no content -- tombstoned wave-3"`
- **`compute_risk()` always overrides caller-provided risk.** Portal derives risk; agents never
  set it. Log a WARNING if caller passes a risk value that differs from the formula result.
- **radon dependency check (Step 2 pre-condition):** `.venv/Scripts/python.exe -c "import radon"`.
  If `ImportError`: add `radon` to `requirements.txt` and run
  `.venv/Scripts/python.exe -m pip install radon`. radon is a production dep (runs in portal,
  not dev-only).
- **coverage baseline:** If `coverage.xml` is absent or does not contain the target file, use
  `M = 0.1` (minimum). Do not block rec filing on missing coverage data.
- **YAML graduation is SSO-conditional.** The graduation guard in `validate.py` blocks flipping
  `status.accepted_values enforced: false -> true` unless `dq-latest.json` shows PASS. If SSO
  unavailable after tombstone, leave as `enforced: false  # pending graduation: tombstone done,
  awaiting live DQ PASS` and do not flip.
- **Wave 3 scope only.** Do not touch `file`, `context`, `acceptance` validation (Wave 2) or
  `source_registry.yaml` (Wave 1).
- **Lambda rebuild deferred.** `config/data_quality/ops.yaml` is bundled in the Lambda zip by
  `scripts/build_lambda.py`. The scheduled agent dispatcher is currently disabled (May 2026
  per CLAUDE.md operational runbook). Lambda rebuild and smoke-test (`scripts.run_scheduled_agent
  --smoke-test doc-freshness`) must be executed when the dispatcher is re-enabled -- not part
  of this plan's verification scope.
- No rescue agents or workaround loops (Decision 55).

## Context
- **Wave 3 routing:** `config/data_quality/decisions/ops_recommendations.yaml` -- fields
  `status.phase4_session: wave-3` and `risk.phase4_session: wave-3`. Decided actions are the
  spec for Steps 3-5.
- **Status violations:** 22 'Decided' (dec-XXX IDs -- ops_decisions domain pollution from early
  migration), 9 'Unknown' (migration artifacts), 2 empty-string (Class B bootstrap), plus
  rec-001/rec-002 stubs. Decision manifest confirms zero dependency references -- safe to
  tombstone all. After tombstone the 35-record bootstrap null cohort in source/effort/priority
  will partially self-resolve.
- **Risk checks are already `enforced: true`** (graduated in PR #303). The DQ runner is failing
  on risk because the *data* is wrong, not the check. No YAML graduation needed for risk -- the
  backfill alone produces PASS. The ~36 empty-string risk records are the dec-XXX bootstrap
  cohort and resolve automatically when those records are tombstoned in Step 3.
- **rec-594 scope clarification:** rec-594 originally targeted Pydantic Literal for status.
  This plan delivers exactly that: `status: Literal["open","closed","failed","declined","superseded"]`
  in `Recommendation`. Close rec-594 with `execution_result=success` after Step 1 VP passes.
- **Formula inputs:** C from `radon cc -n --max <file>` (subprocess); S from hardcoded dict;
  M from `coverage.xml` line-rate for the target file + 0.1 baseline. If file does not exist
  (rec targeting a file to be created), use C=1.
- **Decision 66 is a pre-implementation of the Wave 2 pattern.** `get_rec_write_guidance()`
  (the implementation) ships in Wave 2. Decision 66 locks the principle *before* the
  implementation so Wave 2 has a decided contract to implement against, not a proposal.
- **No live DQ run during planning** (dq-latest.json shows verdict FAIL with 0/0/0 counts --
  Athena was unreachable at planning time). Violation counts sourced from decision manifest
  (2026-05-07 snapshot). Run DQ runner at session start before Step 3 to get current verdicts.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (last decision is 65; add Decision 66 before it)
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` read
- [ ] `config/data_quality/ops.yaml` read (confirm `risk` enforced: true; `status.accepted_values`
      enforced: false)
- [ ] `scripts/executor/jsonl_store.py` Recommendation model read
- [ ] radon available in venv (`.venv/Scripts/python.exe -c "import radon"`)

## Ordered Execution Steps

1. **Update `scripts/executor/jsonl_store.py` -- status Literal + risk description (rec-594)**

   Add `Literal` to the imports from `typing` (or extend existing). Change:
   ```python
   status: str = Field(..., description="Status (open, closed, failed, etc.)")
   ```
   to:
   ```python
   status: Literal["open", "closed", "failed", "declined", "superseded"] = Field(
       ..., description="Lifecycle state; portal-enforced domain"
   )
   ```
   Also update the `risk` field description from `"Risk level: unclassified, low, medium, high"`
   to `"Risk level: low, medium, or high (portal-derived from file + effort)"`.
   Run `ruff check --fix scripts/executor/jsonl_store.py && ruff format scripts/executor/jsonl_store.py`.
   Run VP step 1 to confirm guard fires.

2. **Add `compute_risk()` to `scripts/ops_data_portal.py` and wire into `file_rec()`**

   Add the function immediately before `file_rec()`. Signature:
   ```python
   def compute_risk(file_path: str, effort: str) -> str:
   ```
   Implementation:
   - `_EFFORT_SCALE = {"XS": 0.1, "S": 0.5, "M": 1.0, "L": 3.0, "XL": 5.0}`
   - C: call `subprocess.run([sys.executable, "-m", "radon", "cc", "-n", "--max", file_path], ...)`.
     Parse the integer from stdout. If file does not exist or radon returns empty, C = 1.
   - S: `_EFFORT_SCALE.get(effort, 1.0)` (fallback 1.0 for unknown effort labels).
   - M: parse `coverage.xml` for the file's `line-rate` attribute + 0.1. If `coverage.xml`
     absent or file not in it, M = 0.1.
   - R = (C * S) / M. Thresholds: R <= 5 -> "low", R <= 15 -> "medium", R > 15 -> "high".

   Wire into `file_rec()`: after the `_REQUIRED_NONEMPTY` check, add:
   ```python
   derived_risk = compute_risk(fields["file"], fields["effort"])
   if fields.get("risk") and fields["risk"] != derived_risk:
       logger.warning("[PORTAL] caller risk %s overridden by formula %s for %s",
                      fields["risk"], derived_risk, fields.get("title",""))
   fields["risk"] = derived_risk
   ```
   Run `ruff check --fix scripts/ops_data_portal.py && ruff format scripts/ops_data_portal.py`.
   Run VP step 2 to confirm formula returns a valid tier.

3. **Tombstone bad-status records via `ops_data_portal.update_rec()`**

   Run VP step 3 first to confirm candidate count (~33 expected).

   Write a one-off script or inline loop that:
   - Loads `logs/.recommendations-log.jsonl` and identifies records where `status NOT IN`
     the valid set or `status == ""` or `id` is `rec-001`/`rec-002`.
   - For each, calls `update_rec(rec_id, {"status": "superseded", "resolution": "<category text>"})`.
   - Logs each tombstoned ID.

   After all updates, run `.venv/Scripts/python.exe -m scripts.sync_ops pull`.
   Run VP step 4 to confirm 0 bad-status records remain.

4. **Backfill invalid-domain risk records via `compute_risk()`**

   Load `logs/.recommendations-log.jsonl` and identify records where `risk` is not in
   `('low','medium','high')` and `risk` is not null/empty. This captures: 'unclassified' x28,
   wrong-case ('Low','Medium','High') x3, free-text strings x3.

   For each record:
   - Skip if `file` or `effort` is null/empty (cannot compute formula).
   - Call `compute_risk(rec['file'], rec['effort'])` and `update_rec(rec_id, {"risk": result})`.

   After all updates, run `.venv/Scripts/python.exe -m scripts.sync_ops pull`.
   Run VP step 5 to confirm 0 invalid-domain risk records remain.

5. **Graduate `status.accepted_values` in `config/data_quality/ops.yaml`**

   Pre-condition: VP step 4 must show 0 bad-status records AND a live DQ run must show
   `status.accepted_values PASS`. Run the DQ runner:
   `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml`

   If PASS: change in `ops.yaml`:
   ```yaml
   - accepted_values:
       values: [open, closed, failed, declined, superseded]
       enforced: false  # invalid values present
   ```
   to:
   ```yaml
   - accepted_values:
       values: [open, closed, failed, declined, superseded]
       enforced: true
   ```
   If SSO unavailable (DQ runner cannot reach Athena): add inline comment and defer:
   ```yaml
       enforced: false  # pending graduation: tombstone done, awaiting live DQ PASS
   ```
   Run VP step 6.

6. **Add Decision 66 to `docs/DECISIONS.md`**

   Insert immediately before `## Decision 65` (most-recent-first ordering). Exact content:

   ```
   ## Decision 66: Precision Context Injection as Agent-First Design Principle (Decided)

   **Status:** Decided
   **Date:** 2026-05-08

   **Problem:**
   Agents composing fields that require LLM judgment (title, context, acceptance) frequently
   produce thin or structurally-valid-but-semantically-empty values when they lack field
   semantics in their context window. Storing semantics in ops.yaml (per Decision 65) solves
   the documentation problem but not the runtime problem: an agent that never loaded ops.yaml
   has no basis for producing a high-quality value.

   **Decision:**
   In an agent-first repository, the authoritative field semantics must be surfaced at the
   moment the agent *composes* the value -- not stored passively in config, and not injected
   as a post-rejection error message. Pre-composition context injection is categorically more
   effective for LLM agents than post-failure correction: the agent self-evaluates against the
   spec before writing rather than re-attempting after rejection.

   The canonical implementation pattern is `get_rec_write_guidance()` (Wave 2 deliverable in
   ops_data_portal): called before `file_rec()`, it returns the `semantics` text for each
   LLM-judgment field from ops.yaml, forcing the spec into the agent's context before value
   composition. Any portal function that writes agent-authored content must expose its semantic
   contract proactively via this pattern.

   This principle applies at all 5 instruction layers (docs/contracts/instruction-architecture.md).
   The pattern generalises beyond ops_data_portal: any write gateway for agent-authored content
   should expose field semantics before accepting a write, not only after rejecting one.
   ```

7. **Update `CLAUDE.md` -- add Precision Context Injection to Agent-First section**

   Locate the Agent-First Repository section. After the last existing bullet point, add:

   ```
   - Precision context injection: for fields requiring LLM judgment (title, context, acceptance),
     surface the authoritative field semantics before the agent composes the value -- not as a
     post-rejection error. Call `get_rec_write_guidance()` before `file_rec()`. Anti-pattern:
     storing semantics only in ops.yaml without surfacing them at agent write time produces
     structurally-valid but semantically-thin content from agents without prior context.
   ```

8. **Execute Verification Plan** -- run VP steps 1-8 in order. Loop on any failure until all
   pass. VP steps 4, 5, 6 require SSO (Athena-backed sync + DQ runner). If SSO unavailable:
   complete all other VP steps, note SSO blocker in report, and leave `status.accepted_values`
   at `enforced: false` with the inline comment from Step 5.

9. **Close rec-594 via portal:**
   ```
   .venv/Scripts/python.exe -m scripts.ops_data_portal --update-rec rec-594 \
     --status closed --execution-result success
   ```
   Then report: files modified, records tombstoned, records backfilled, risk formula
   implementation summary, graduation status of `status.accepted_values`, VP results.
