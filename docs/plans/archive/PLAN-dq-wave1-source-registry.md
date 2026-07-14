# Plan

## Intent
Establish `source` as a governed lineage key by creating `source_registry.yaml` (the canonical agent-type taxonomy), wiring write-time registry validation into the portal, standing up the `get_rec_write_guidance()` v1 skeleton (Decision 66 mechanism, pulled forward from Wave 2), and adding a CI guard that prevents unregistered agent types from reaching production. This is Wave 1 of the Phase 4 DQ resolution arc (`docs/INTENT-dq-enforcement.md`).

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-wave1-source-registry

## Phase
DQ Arc Phase 4 (Data Quality Resolution, IN_PROGRESS) - `docs/INTENT-dq-enforcement.md`

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `config/data_quality/source_registry.yaml` | Create | Canonical agent-type taxonomy; 25 entries (see Context for full list); each carries `canonical_id`, `description`, `signal_interpretation`, `added_date` |
| `scripts/executor/rec_write_guidance.py` | Create | `load_source_registry()`, `validate_source()`, `get_rec_write_guidance()` — Decision 66 v1 skeleton; reads ops.yaml semantics + registry; surfaces both to agent before write |
| `scripts/ops_data_portal.py` | Modify | Import `validate_source` from `rec_write_guidance`; call it in `file_rec()` and `drain_pending()` at write time; expose `--guidance` CLI flag that prints `get_rec_write_guidance()` output |
| `config/data_quality/ops.yaml` | Modify | Drop `source.accepted_values` check (validation now lives in portal — no runtime DQ needed); update `source.semantics` to reference `source_registry.yaml`; keep `source.not_null enforced=true` |
| `scripts/validate.py` | Modify | Add `check_source_registry()` CI guard: load `source_registry.yaml`; parse `.github/agents/schedule.yaml` agent `name` fields; verify each `name` is a registered `canonical_id`; also grep `scripts/ops_data_portal.py` for hardcoded source strings and verify each is registered; fail CI with list of unregistered values |
| `tests/test_ops_data_portal.py` | Modify | Add tests: `test_file_rec_rejects_unregistered_source`, `test_file_rec_accepts_registered_source`, `test_drain_pending_rejects_unregistered_source` |
| `tests/test_rec_write_guidance.py` | Create | Tests: registry loads cleanly, `validate_source` raises for unknown, passes for registered, `get_rec_write_guidance` returns dict with `source` key carrying semantics text + registry list |
| `tests/test_validate.py` | Modify | Add tests: `test_source_registry_ci_guard_rejects_unregistered`, `test_source_registry_ci_guard_accepts_registered` |

**Data corrections (via portal API — no file edits):**
- Correct rec-553: `source='Autonomous Postflight Cleanup'` -> `'autonomous-postflight-cleanup'` via `ops_data_portal update_rec`
- Correct rec-564: `source='Autonomous Postflight Cleanup'` -> `'autonomous-postflight-cleanup'` via `ops_data_portal update_rec`
- Register `autonomous-postflight-cleanup` in `source_registry.yaml`

## Bundled Recommendations
None with explicit rec IDs. The source registry creation is the directly-scoped Wave 1 deliverable from the decision manifest at `config/data_quality/decisions/ops_recommendations.yaml` (field: `source`, `phase4_session: wave-1`).

Note: `get_rec_write_guidance()` is tagged as a Wave 2 deliverable in Decision 66 but is pulled forward here as a low-risk bonus (read-only function, solves the user-raised semantic enforcement question, makes Wave 2's LLM-judgment field validation trivial because the mechanism is already proven). This diverges from the literal Decision 66 placement but does not violate it — Decision 66 commits to the pattern, not the wave. Record this scoping decision in the session log.

## Infrastructure Dependencies
| Component | Change | Timing |
|-----------|--------|--------|
| `data-pipeline.zip` Lambda package | `config/data_quality/source_registry.yaml` added; `config/data_quality/ops.yaml` `accepted_values` block removed. No Lambda handler reads DQ config — behavioural change is zero. Redeploy required for package currency. | post-code, pre-data-correction (Step 7) |
| Lambda smoke test | Confirm `run_scheduled_agent --smoke-test doc-freshness` exits 0 after redeploy. Verifies packaging integrity, not new feature behaviour. | immediately after Step 7 deploy |

## Acceptance Criteria
- [ ] `config/data_quality/source_registry.yaml` exists with all 25 canonical agent-type entries
- [ ] `scripts/ops_data_portal.py` `file_rec()` raises `ValueError` for any source value not in the registry
- [ ] `scripts/ops_data_portal.py` `drain_pending()` also validates source (prevents old outbox entries with bad source from materialising)
- [ ] `get_rec_write_guidance()` returns a dict containing a `'source'` key; its value includes the `semantics` text from ops.yaml AND the current list of valid canonical_ids from the registry
- [ ] `validate.py` CI guard `check_source_registry()` runs on every `--ci` / presubmit invocation and fails if any `.github/agents/schedule.yaml` agent `name` is not a registered canonical_id
- [ ] `ops.yaml` `source.accepted_values` check is removed; `source.not_null enforced=true` remains
- [ ] rec-553 and rec-564 `source` field is `'autonomous-postflight-cleanup'` in the Athena `_current` view (confirmed via sync + JSONL cache query)
- [ ] Full test suite (1780+ tests) passes with no regressions
- [ ] File a rec for granular AGENT_TYPE injection in `findings_processor_handler.py` (currently hardcodes `"source": "agent-cron"` for all Lambda-invoked scheduled agents; the Lambda path is disabled but the value remains in code)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Portal rejects unregistered source | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py::test_file_rec_rejects_unregistered_source -v` | PASSED | Validation not wired in `file_rec()` |
| 2 | pre-deploy | Portal accepts registered source | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py::test_file_rec_accepts_registered_source -v` | PASSED | Registry path misconfigured |
| 3 | pre-deploy | Guidance function returns semantics + registry list | `.venv/Scripts/python.exe -m pytest tests/test_rec_write_guidance.py -v` | all PASSED | `get_rec_write_guidance()` not reading ops.yaml or registry |
| 4 | pre-deploy | CI guard rejects unregistered agent type | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::test_source_registry_ci_guard_rejects_unregistered -v` | PASSED | Guard not scanning schedule.yaml |
| 5 | pre-deploy | CI guard accepts fully-registered schedule.yaml | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::test_source_registry_ci_guard_accepts_registered -v` | PASSED | Registry missing an agent name |
| 6 | pre-deploy | `ops.yaml` source.accepted_values removed | `grep -A 20 "source:" config/data_quality/ops.yaml \| grep "accepted_values"` | zero lines | Residual check still present — remove the block and re-check |
| 7 | pre-deploy | Full test suite passes | `.venv/Scripts/python.exe -m pytest tests/ -x -q 2>&1 \| tail -5` | N passed, 0 failed (N >= 1780) | Fix any regressions before proceeding |
| 8 | pre-deploy | Lambda package builds with new config files | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy 2>&1 \| tail -10` | Build succeeds; Lambda function code updated | Fix packaging error; check config/ for syntax errors |
| 9 | pre-deploy | Smoke test confirms Lambda dispatcher still routes correctly | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness 2>&1 \| tail -10` | Smoke test exits 0; no import or packaging errors | Check Lambda logs; verify source_registry.yaml YAML is valid |
| 10 | post-deploy | rec-553 and rec-564 corrections visible in local cache | `.venv/Scripts/python.exe -m scripts.sync_ops pull 2>&1 \| tail -2 && .venv/Scripts/python.exe -c "import json; d={json.loads(l)['id']:json.loads(l)['source'] for l in open('logs/.recommendations-log.jsonl') if json.loads(l).get('id') in ['rec-553','rec-564']}; print(d)"` | `{'rec-553': 'autonomous-postflight-cleanup', 'rec-564': 'autonomous-postflight-cleanup'}` | Data correction not persisted or not synced |
| 11 | post-deploy | DQ runner: source.not_null passes, accepted_values absent | `.venv/Scripts/python.exe -m scripts.data_quality_runner --file config/data_quality/ops.yaml 2>&1 \| grep -E "source\|PASS\|FAIL" \| head -20` | `source not_null PASS`; no `accepted_values` row for source | ops.yaml still has accepted_values or not_null regressed |

## Constraints
- Single Portal Invariant: rec-553 and rec-564 corrections MUST go through `scripts/ops_data_portal.py` — never direct JSONL edits
- `findings_processor_handler.py` Lambda is out of scope — it is disabled (CLAUDE.md runbook, May 2026 migration) and any handler changes require build + deploy + smoke-test sequence per `src/data/handlers/CLAUDE.md`. Register `agent-cron` in the registry instead and file a rec for the granular injection fix.
- `scripts/ops_data_portal.py` is at 795 SLOC against a 500-line cap (rec-607 open for waiver). Do NOT add functions directly to the portal. Factor `validate_source`, `load_source_registry`, and `get_rec_write_guidance` into `scripts/executor/rec_write_guidance.py`; portal imports from there. This keeps portal SLOC growth to a single import line + call sites.
- No rescue agents or workaround loops (Decision 55)
- The `source.accepted_values` DQ check is being dropped entirely, not graduated to `enforced: false`. Rationale: once write-time registry validation is live, the DQ check is redundant by construction. Dropping it (vs. annotating it) removes a maintenance surface that would otherwise need to be kept in sync with the registry. Document this in the commit message.
- The `ops.yaml` `source.not_null` check stays `enforced: true` — null source means AGENT_TYPE injection failed on some invocation path, which is a harness health signal.

## Context
- Wave 1 of `docs/INTENT-dq-enforcement.md` Phase 4 session map. Prerequisite (wave-3) completed in PR #307.
- Decision 65: `config/data_quality/ops.yaml` is the canonical field semantic authority (`description` + `semantics` per column)
- Decision 66: `get_rec_write_guidance()` is the Decision 66 delivery mechanism (Precision Context Injection). Decision 66 originally tagged it as a Wave 2 deliverable; it is pulled forward here as a read-only function with no write-path risk.
- `source` is a lineage key (per `docs/PROJECT_CONTEXT.md` Field Architecture Decisions): equivalent to `session_id` for future cross-table telemetry joins. Never agent-set — harness-injected.
- Current `source.accepted_values` in ops.yaml is stale: 11+ legitimate source values are missing (manifest `notes` field). Dropping the DQ check and moving to write-time registry validation eliminates the staleness-by-design problem.
- `findings_processor_handler.py` hardcodes `"source": "agent-cron"` at line 314. This is the disabled Lambda path (schedule.yaml agents now run as Claude Code scheduled agents). Register `agent-cron` in the registry; file a rec for granular per-agent injection.
- `rec-553` and `rec-564` have `source='Autonomous Postflight Cleanup'` (spaces + capital letters) — Class D format violation. Correct to `'autonomous-postflight-cleanup'` via portal.
- **Source registry canonical_id list (25 entries)** — all must appear in the registry. Implementation agent resolves `description` + `signal_interpretation` per entry; use the `notes` field in the decision manifest for signal context:
  1. executor-postmortem
  2. executor-supervision
  3. code-review
  4. planning
  5. brainstorm
  6. doc-freshness
  7. orphan-code
  8. transcript-review
  9. code-smell
  10. prompt-quality
  11. rec-curator
  12. manual
  13. scoping
  14. cli-migration-analysis
  15. telemetry-audit
  16. executor-gap-analysis
  17. architectural-review
  18. implement-agent
  19. cc-scheduled-agent-test
  20. workflow-audit
  21. tech-debt
  22. delegate-investigation
  23. infra-recommendation-executor
  24. autonomous-postflight-cleanup
  25. agent-cron (legacy Lambda catch-all; disabled path; registered for JSONL cache compatibility)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` Decisions 63-66 read
- [ ] `docs/INTENT-dq-enforcement.md` Phase 4 section read
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` field `source` section read
- [ ] `config/data_quality/ops.yaml` source column section read (current tests to remove/keep)
- [ ] `scripts/ops_data_portal.py` `file_rec()` and `drain_pending()` signatures read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Create `config/data_quality/source_registry.yaml` — YAML list of 25 entries; each entry has `canonical_id`, `description`, `signal_interpretation`, `added_date: '2026-05-08'`. See Context for the full canonical_id list; compose `description` and `signal_interpretation` from the decision manifest notes and the analytical role of each agent type.
2. Create `scripts/executor/rec_write_guidance.py` — three public functions:
   - `load_source_registry(registry_path: Path | None = None) -> list[dict]`: reads `source_registry.yaml`, returns entries; caches in module-level dict so repeated calls are cheap
   - `validate_source(value: str, registry_path: Path | None = None) -> None`: raises `ValueError(f"Unknown source '{value}'. Register in config/data_quality/source_registry.yaml before filing.")` for any value not in the registry's canonical_id list
   - `get_rec_write_guidance(ops_yaml_path: Path | None = None, registry_path: Path | None = None) -> dict[str, dict]`: reads `ops.yaml` semantics fields + source registry; returns `{column_name: {"semantics": str, ...}}` with `"source"` entry additionally carrying `"registered_values": [list of canonical_ids]`
3. Modify `scripts/ops_data_portal.py`:
   - Add `from scripts.executor.rec_write_guidance import validate_source` (top of imports)
   - In `file_rec()`: call `validate_source(fields["source"])` before the Iceberg write (raise propagates to caller)
   - In `drain_pending()`: call `validate_source(rec["source"])` when processing each outbox entry; on failure, log the invalid entry and skip it (do not abort the full drain)
   - Add `--guidance` CLI flag to the argparse block: when set, print `get_rec_write_guidance()` output as YAML and exit 0 (agents invoke this before filing)
4. Modify `config/data_quality/ops.yaml`:
   - Remove the entire `accepted_values` block under `source` columns tests (the `enforced: false` accepted_values check and all its params)
   - Update `source.semantics` text to add: "Validated against `config/data_quality/source_registry.yaml` at write time in ops_data_portal — unregistered values are rejected before reaching Iceberg."
   - `source.not_null enforced: true` remains unchanged
5. Modify `scripts/validate.py` — add `check_source_registry()`:
   - Load `config/data_quality/source_registry.yaml`; extract `canonical_id` set
   - Parse `.github/agents/schedule.yaml` agent `name` fields
   - Verify each `name` is in the canonical_id set; collect violations
   - Grep `scripts/ops_data_portal.py` for hardcoded source strings matching pattern `source\s*==\s*['"]([^'"]+)['"]` and `"source":\s*"([^"]+)"`; extract string values; verify each is in canonical_id set (excluding format strings and variable references); collect violations
   - If any violations: print list and return failure; else return success
   - Wire `check_source_registry()` into the existing presubmit/CI check dispatch (NOT into `--quick`)
6. Write tests:
   - `tests/test_rec_write_guidance.py`: (a) `load_source_registry` returns list with 25 entries, all have required keys; (b) `validate_source("planning")` raises no exception; (c) `validate_source("ghost-agent")` raises `ValueError`; (d) `get_rec_write_guidance()` returns dict, `"source"` key present, `"semantics"` is a non-empty string, `"registered_values"` is a list containing `"planning"`
   - `tests/test_ops_data_portal.py`: add `test_file_rec_rejects_unregistered_source` (mock write path, verify ValueError on source='ghost-agent'), `test_file_rec_accepts_registered_source` (verify no exception on source='planning'), `test_drain_pending_rejects_unregistered_source` (verify invalid entry is skipped, valid entries are processed)
   - `tests/test_validate.py`: add `test_source_registry_ci_guard_rejects_unregistered` (use a temp schedule.yaml with an unregistered agent name; verify check_source_registry returns failure), `test_source_registry_ci_guard_accepts_registered` (all names registered; verify passes)
7. Build and deploy Lambda — `config/` is packaged into `data-pipeline.zip` by `scripts/build_lambda.py` (line 71: `shutil.copytree(ROOT / "config", app_dir / "config")`). No Lambda handler reads `source_registry.yaml` or the DQ config files, so Lambda behaviour is unchanged, but the package must be redeployed to remain current. Run: `.venv/Scripts/python.exe -m scripts.build_lambda --deploy`. Then smoke-test: `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness`. The smoke test confirms the dispatcher routes and the Lambda package loads without import errors introduced by the config change.
8. Correct rec-553 and rec-564 via portal:
   - `.venv/Scripts/python.exe -m scripts.ops_data_portal update_rec --id rec-553 --source autonomous-postflight-cleanup`
   - `.venv/Scripts/python.exe -m scripts.ops_data_portal update_rec --id rec-564 --source autonomous-postflight-cleanup`
   - (Verify the exact CLI syntax for update_rec from `scripts/ops_data_portal.py --help` before executing)
9. **Execute Verification Plan** — run each VP step in order. All 11 steps must pass before merge. If VP step 7 (full test suite) fails, fix regressions before proceeding.
10. File a rec via portal: "Granular AGENT_TYPE injection in `findings_processor_handler.py` — replace hardcoded `source: 'agent-cron'` with per-agent type injection from the Lambda event payload so each scheduled agent's recs carry their specific canonical_id instead of the catch-all."
11. Report: what was implemented, VP results, any findings filed.
