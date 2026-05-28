# Plan

## Intent
Complete Wave 2 of Phase 4 DQ enforcement by making `automatable` a formula-derived field
(never agent-set), installing write-time structural validators for `file`/`context`/`acceptance`,
and resolving open-rec data nulls and prose acceptance commands -- closing the remaining
agent-set error classes that produce structurally-valid but semantically-thin recommendations.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-wave2-capabilities

## Phase
Phase 1: Core Infrastructure (Complete) -- this work continues Phase 4 of the DQ enforcement
arc (docs/INTENT-dq-enforcement.md).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_data_portal.py` | Modify | Refactor `_compute_risk_score()` from `compute_risk`; add `compute_automatable()`, `_validate_file_path()`, `_validate_context_length()`; wire validators + `lint_acceptance_command` + automatable derivation into `file_rec()`; remove `--automatable` CLI arg |
| `config/executor_capabilities.yaml` | Modify | Extend `boundary_patterns` with Terraform/CI/config/prompt boundary files (Lambda-packaged) |
| `config/data_quality/ops.yaml` | Modify | Add `description`, `semantics`, and DQ checks (`not_null` + `LENGTH(TRIM(context)) >= 80` expression) for `file`, `context`, `acceptance` columns; all `enforced: false` initially |
| `config/data_quality/decisions/ops_recommendations.yaml` | Modify | Mark `automatable`, `file`, `context`, `acceptance` as `phase4_session: complete` after data work |
| `docs/INTENT-dq-enforcement.md` | Modify | Wave-2 row: NOT_STARTED -> COMPLETE, add PR reference |
| `docs/DECISIONS.md` | Modify | Extend Decision 66 to explicitly record Tier A/B/C/D semantic-enforcement architecture |
| `tests/test_ops_data_portal_validators.py` | Create | Unit tests for `_validate_file_path`, `_validate_context_length`, `compute_automatable`, and the automatable-override warning |

## Bundled Recommendations
None formally bundled. The following data work is executed within scope:
- Re-derive and update all open recs with null `file`, `context`, or `acceptance` (count from
  fresh DQ run; wave-2 plan estimated ~36 each).
- Convert all open recs with prose acceptance commands to verifiable shell commands (count
  re-derived from fresh Athena query -- original 12 may have changed due to deletions/updates).

## Acceptance Criteria
- [ ] `file_rec({"file": "/absolute/path", ...})` raises `ValueError` (absolute Unix path)
- [ ] `file_rec({"file": "C:\\path.py", ...})` raises `ValueError` (absolute Windows path)
- [ ] `file_rec({"file": "scripts\\module.py", ...})` raises `ValueError` (backslash separator)
- [ ] `file_rec({"context": "fix bug", ...})` raises `ValueError` (< 80 stripped chars)
- [ ] `file_rec({"acceptance": 'python -c "x=1"', ...})` raises `ValueError` (banned pattern from `lint_acceptance_command`)
- [ ] Caller-supplied `automatable` is overridden by formula; WARNING logged
- [ ] `compute_automatable(boundary_file, any_risk)` returns `False`
- [ ] `compute_automatable(normal_file, high_risk_score)` returns `False` (R > maturity_ceiling)
- [ ] `compute_automatable(normal_file, low_risk_score)` returns `True`
- [ ] `--automatable` argparse arg removed; `python -m scripts.ops_data_portal --file-rec --automatable true ...` errors with unrecognized argument
- [ ] `get_rec_write_guidance()` returns non-empty `description` and `semantics` for `file`, `context`, `acceptance` (auto-populated from ops.yaml additions; no code change to rec_write_guidance.py required)
- [ ] `grep -n "enforced: false" config/data_quality/ops.yaml` shows zero wave-2 checks without inline `# data condition` comment
- [ ] `.venv/Scripts/python.exe -m scripts.validate` passes (full presubmit, no flags)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | `_validate_file_path` rejects absolute Unix path | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_file_path_rejects_absolute_unix -v` | PASSED | Validator not raising; check `startswith("/")` logic |
| 2 | pre-deploy | `_validate_file_path` rejects absolute Windows path | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_file_path_rejects_absolute_windows -v` | PASSED | Regex `[A-Za-z]:[/\\]` not matching |
| 3 | pre-deploy | `_validate_file_path` rejects backslash separator | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_file_path_rejects_backslash -v` | PASSED | `"\\"` not caught in path check |
| 4 | pre-deploy | `_validate_context_length` rejects short context | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_context_length_rejects_short -v` | PASSED | Threshold not applied or strip() not called |
| 5 | pre-deploy | `lint_acceptance_command` wired into `file_rec` | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_acceptance_lint_wired_into_file_rec -v` | PASSED | `lint_acceptance_command` not called in `file_rec` |
| 6 | pre-deploy | `compute_automatable` boundary file returns `False` | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_compute_automatable_boundary_file -v` | PASSED | Pattern not matching; check `in` substring logic |
| 7 | pre-deploy | `compute_automatable` high-R rec returns `False` | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_compute_automatable_high_risk_score -v` | PASSED | Ceiling comparison using wrong operator or wrong field |
| 8 | pre-deploy | `compute_automatable` valid rec returns `True` | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_compute_automatable_valid -v` | PASSED | Formula returning False for valid inputs; trace R calculation |
| 9 | pre-deploy | Caller automatable override logs WARNING | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal_validators.py::test_automatable_override_warning -v` | PASSED | Warning not emitted; check logger.warning call |
| 10 | pre-deploy | `--automatable` CLI arg removed | `.venv/Scripts/python.exe -m scripts.ops_data_portal --file-rec --automatable true --title x --file x --context x --acceptance x --effort XS --priority Low --source manual 2>&1 \| grep -q "unrecognized arguments" && echo PASS` | PASS | Argparse still accepts the flag; ensure arg removed from parser |
| 11 | pre-deploy | `get_rec_write_guidance` returns semantics for new fields | `.venv/Scripts/python.exe -c "from scripts.executor.rec_write_guidance import get_rec_write_guidance; g=get_rec_write_guidance(); missing=[f for f in ['file','context','acceptance'] if not g.get(f,{}).get('semantics')]; print('MISSING:',missing) if missing else print('OK')"` | `OK` | Add/fix `semantics` field in ops.yaml for missing columns |
| 12 | pre-deploy | Full presubmit gate | `.venv/Scripts/python.exe -m scripts.validate` | All checks pass (note: remote CI currently failing in separate session -- local presubmit is the gate here) | Fix specific failing check before continuing |
| 13 | post-deploy | Count open recs with null file/context/acceptance | `.venv/Scripts/python.exe -c "import boto3,time; ..."` (full Athena query: `SELECT COUNT(*) FROM trading_formulas_db.ops_recommendations_current WHERE status='open' AND (file IS NULL OR file='' OR context IS NULL OR context='' OR LENGTH(TRIM(context))<80 OR acceptance IS NULL OR acceptance='')`) | Count returned (note for backfill target) | Run backfill steps until count=0 |
| 14 | post-deploy | List open recs with prose acceptance | `.venv/Scripts/python.exe -c "import boto3,json,time; a=boto3.Session(profile_name='company-aws-profile',region_name='eu-west-2').client('athena'); eid=a.start_query_execution(QueryString=\"SELECT id,acceptance FROM trading_formulas_db.ops_recommendations_current WHERE status='open' AND automatable=true AND acceptance IS NOT NULL AND LENGTH(TRIM(acceptance))>0\",WorkGroup='agent-platform-production',ResultConfiguration={'OutputLocation':'s3://bblake-platform-agent-logs/athena-results/'})['QueryExecutionId']; [time.sleep(2) for _ in range(30) if a.get_query_execution(QueryExecutionId=eid)['QueryExecution']['Status']['State'] not in ('SUCCEEDED','FAILED','CANCELLED')]; rows=[r for p in a.get_paginator('get_query_results').paginate(QueryExecutionId=eid) for r in p['ResultSet']['Rows'][1:]]; prose=[(r['Data'][0]['VarCharValue'],r['Data'][1]['VarCharValue']) for r in rows if not any(k in r['Data'][1]['VarCharValue'] for k in ['.py','.yaml','.json','grep','pytest','python -m'])]; print(json.dumps(prose,indent=2))"` | JSON list of `[rec_id, acceptance]` pairs where acceptance appears to be prose; review each and convert | Convert each prose acceptance to a verifiable shell command via `update_rec`; verify each with `lint_acceptance_command()` first |
| 15 | post-deploy | DQ runner confirms wave-2 checks present and reports verdict | `.venv/Scripts/python.exe -m scripts.data_quality_runner 2>&1 \| grep -E "file\|context\|acceptance"` | Lines for `ops_recommendations / file / not_null`, `ops_recommendations / context / not_null`, `ops_recommendations / context / expression`, `ops_recommendations / acceptance / not_null` each appear with a PASS or FAIL verdict. FAIL is expected before backfill is complete; ERROR means Athena unreachable. | If ERROR: check SSO session. If checks missing entirely: verify ops.yaml additions were saved correctly. |
| 16 | post-deploy | Graduate passing wave-2 checks | `grep -n "enforced: false" config/data_quality/ops.yaml \| grep -v "#"` | Zero lines without inline comment | Graduate `enforced: false -> enforced: true` for checks with PASS in step 15; leave failing checks with inline comment |
| 17 | post-deploy | Final presubmit gate | `.venv/Scripts/python.exe -m scripts.validate` | All checks pass | Fix specific failures |

## Constraints
- No STRATEGIC plans (CLAUDE.md temporary constraint, Decision 67).
- **Remote CI currently failing** -- separate session in progress. Local presubmit (`validate` no flags) is the authoritative pre-merge gate for this plan. Do not block on CI green.
- **Lambda deployment deferred (Decision 67):** `config/executor_capabilities.yaml` is Lambda-packaged. Include a DEFERRED execution step; do not run `build_lambda --deploy`.
- Portal writes only via `file_rec`, `update_rec`, `sync` (Single Portal Invariant, Decision 69). Do not call legacy drain/compact/refresh CLIs directly.
- No `eval()` or `exec()` in new code.
- `automatable` must never be agent-set; portal derives from formula. Same pattern as `risk`.
- No existence check on `file` field value -- recs targeting files-to-be-created are valid.
- `--automatable` removal: verify no CI scripts or prompt files reference it before removing.
- `maturity_ceiling` is numeric (float 1.0 in executor_capabilities.yaml). `compute_automatable` compares raw R (from `_compute_risk_score`) against `maturity_ceiling` using `<=`.
- `get_rec_write_guidance()` is already reading `description`+`semantics` from ops.yaml columns. No code change to `scripts/executor/rec_write_guidance.py` is required -- adding the fields to ops.yaml is sufficient.
- Graduation guard in `validate.py` blocks flipping `enforced: false -> enforced: true` unless the check's `(table, column, test)` tuple has verdict PASS in `logs/debug/dq-latest.json`. Always run the DQ runner immediately before graduating.
- Decision 65: ops.yaml extended contract is the canonical field-meaning authority. Do not create companion briefing documents.
- Decision 66: `get_rec_write_guidance()` must surface semantics for wave-2 fields before agents compose. This is satisfied automatically once ops.yaml is extended.
- RCA-before-action constraint (Phase 4): all data changes follow decisions manifest root-cause classifications. Wave-2 fields have pre-approved root cause classes in the manifest.
- `validate.py --pre` is the edit-loop tier (lint/format only). `validate.py` (no flags) is the full presubmit. Do not use `--integration` (removed in Decision 60 / PR #313).

## Context
- **Phases 0-3 complete.** Ratchet (`enforced` field), graduation guard in `validate.py`, DQ runner auto-invoke in presubmit, `covers`-based gate predicate -- all in production.
- **Wave 1 (PR #309) and Wave 3 (PR #307) complete.** In place: `source_registry.yaml`, `validate_source()` in `file_rec()`, Pydantic Literal status guard, `compute_risk()` formula, ops.yaml extended contract for id/title/source/effort/priority/status/automatable/risk.
- **Abandoned branch `origin/agent/dq-wave2-capabilities-write-validation`** has a working implementation (PR not merged). Do not cherry-pick from it -- the architecture has changed enough that the implementation must be re-derived on the current base. Use it as a reference only.
- **`automatable` not_null is already enforced and PASSING** (dq-latest.json from 2026-05-10). The 44-null automatable backfill from the previous wave-2 attempt is complete. No automatable data backfill needed.
- **`executor_capabilities.yaml`** (created in Wave 1) already has boundary_patterns and `maturity_ceiling: 1.0`. Wave 2 extends boundary_patterns with infrastructure-category files.
- **`get_rec_write_guidance()` auto-reads ops.yaml.** Adding `description`+`semantics` for wave-2 fields to ops.yaml is sufficient for Tier-A injection. No code change to `rec_write_guidance.py`.
- **Pipeline consolidation (Decision 69 / PR #314):** `update_rec` now reads from Athena (requires SSO). Data backfill steps in this plan require an active SSO session.
- **`lint_acceptance_command()`** lives at `scripts/executor/acceptance_lint.py:96`. Already imported in the wave-2 context -- confirm it's still at that path before wiring.
- **Decision 70:** Bootstrap records physically deleted from ops_recommendations. Tombstones list is now empty. No impact on wave-2.
- **Decision 71:** cc-scheduled-agents cron mechanism is GitHub Actions. Not relevant to wave-2.
- **CI failure (separate session):** validate.py presubmit runs locally on the self-hosted runner. Local gate is unaffected.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` must return `agent/dq-wave2-capabilities`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (Decisions 44, 55, 60, 65, 66, 67, 69, 70)
- [ ] `docs/INTENT-dq-enforcement.md` Phase 4 section read in full
- [ ] `config/data_quality/decisions/ops_recommendations.yaml` wave-2 fields (`automatable`, `file`, `context`, `acceptance`) read
- [ ] `config/executor_capabilities.yaml` current boundary_patterns and maturity_ceiling read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] SSO session active (`aws sts get-caller-identity --profile company-aws-profile` returns account ID)

## Ordered Execution Steps

1. **Read cold-start context set:**
   - `docs/INTENT-dq-enforcement.md` Phase 4 section
   - `config/data_quality/decisions/ops_recommendations.yaml` (wave-2 fields)
   - `config/executor_capabilities.yaml` (current boundary_patterns + maturity_ceiling)
   - `config/data_quality/ops.yaml` (current column definitions)
   - Run `.venv/Scripts/python.exe -m scripts.data_quality_runner` to get current per-check
     verdicts. Note which wave-2 checks exist vs which are new. Do not rely on the cached
     result in `logs/debug/dq-latest.json`.

2. **Verify `--automatable` has no external callers:**
   Search for `--automatable` in all shell scripts, prompt files, CI configs, and agent
   definitions: `grep -rn "\-\-automatable" .github/ .claude/ config/prompts/ scripts/`.
   If any external caller is found, file a rec and convert the caller before removing the flag.

3. **Refactor `compute_risk` in `scripts/ops_data_portal.py`:**
   - Extract `_compute_risk_score(file_path: str, effort: str) -> float` that returns raw
     R = (C x S) / M (same formula, no threshold bucketing).
   - Update `compute_risk` to call `_compute_risk_score` and apply the thresholds
     (R <= 5 -> "low", R <= 15 -> "medium", else "high").
   - Verify no test regressions: `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py -q`.

4. **Add `compute_automatable`, validators to `scripts/ops_data_portal.py`:**
   - Add `_CAPABILITIES_YAML` path constant (if not already present from Wave 1 context).
   - Add `load_capabilities() -> dict` (reads and caches executor_capabilities.yaml).
   - Add `compute_automatable(file_path: str, effort: str) -> bool`:
     - Loads capabilities config.
     - `boundary_patterns: list[str]` from config.
     - `ceiling: float` from `maturity_ceiling`.
     - `in_boundary = any(pat in file_path for pat in boundary_patterns)`. If True: `False`.
     - `R = _compute_risk_score(file_path, effort)`. If `R > ceiling`: `False`. Else: `True`.
     - If `file_path` is None/empty: return `True` (offline fallback; boundary unknown).
   - Add `_validate_file_path(path: str) -> None`:
     - If not path: return (emptiness caught by `_REQUIRED_NONEMPTY` guard).
     - If `path.startswith("/")` or `re.match(r"[A-Za-z]:[/\\]", path)`: raise ValueError.
     - If `"\\"` in path: raise ValueError.
   - Add `_validate_context_length(text: str) -> None`:
     - If not text: return.
     - If `len(text.strip()) < 80`: raise ValueError with length and minimum in message.

5. **Wire validators into `file_rec()` in `scripts/ops_data_portal.py`:**
   Confirm `from scripts.executor.acceptance_lint import lint_acceptance_command` is present
   in the module imports (it is NOT currently in `scripts/ops_data_portal.py` on main).
   After the `_REQUIRED_NONEMPTY` and `validate_source()` checks, add in order:
   1. `_validate_file_path(fields["file"])`
   2. `_validate_context_length(fields["context"])`
   3. `lint_ok, lint_msg = lint_acceptance_command(fields["acceptance"])` -- if not lint_ok: raise ValueError(lint_msg)
   4. After `derived_risk = compute_risk(...)` is set: derive automatable:
      `derived_automatable = compute_automatable(fields["file"], fields["effort"])`
      If caller supplied `"automatable"` in fields and it differs from derived: log WARNING and override.
      Set `fields["automatable"] = derived_automatable`.

6. **Remove `--automatable` CLI arg from `scripts/ops_data_portal.py`:**
   - Remove `rec.add_argument("--automatable", ...)` from the argparse group.
   - Remove `"automatable": args.automatable` from the fields dict in the `--file-rec` branch.
   - Note: `file_rec()` derives automatable from formula; CLI callers no longer supply it.

7. **Extend `config/executor_capabilities.yaml` boundary_patterns:**
   Add infrastructure-category boundary files that the executor must not touch:
   - Terraform files: `terraform/`, `.tf`
   - CI/CD: `.github/workflows/`, `.github/actions/`
   - Prompt/agent definitions: `config/prompts/`, `.claude/agents/`, `.github/prompts/`, `.github/agents/`
   - Canonical instruction files: `CLAUDE.md`, `GEMINI.md`, `PLAN-`, `DECISIONS.md`
   - Lambda build artifacts: `build_lambda.py`, `run_scheduled_agent.py`
   Keep existing executor-self-modification patterns. Append new entries under a `# Infrastructure boundary` comment.

8. **Add wave-2 columns to `config/data_quality/ops.yaml`:**
   In the `ops_recommendations` table `columns` section, add after `automatable`:
   - `file:` -- description, semantics, tests: `- not_null: {enforced: false}  # data condition -- open recs with null file; backfilled in wave-2`
   - `context:` -- description, semantics, tests:
     - `- not_null: {enforced: false}  # data condition -- open recs with null context; backfilled in wave-2`
     - `- expression: {sql: "LENGTH(TRIM(context)) >= 80", description: "context must be at least 80 characters", enforced: false}  # data condition -- thin contexts; backfilled in wave-2`
   - `acceptance:` -- description, semantics, tests: `- not_null: {enforced: false}  # data condition -- open recs with null acceptance; backfilled in wave-2`
   Semantics examples (adapt from ops.yaml extended contract pattern):
   - `file`: "Repo-relative path to the primary source file this recommendation targets. Must use forward slashes. Must not be absolute. Validated at write time by ops_data_portal. Recs targeting files-to-be-created are valid -- no existence check applied."
   - `context`: "Why this recommendation exists -- minimum 80 stripped characters. Must answer the question 'what problem does this solve and why now?'. Enforced at write time via ops_data_portal length check."
   - `acceptance`: "Verifiable shell command that proves the recommendation is implemented. Must pass lint_acceptance_command() from scripts/executor/acceptance_lint.py. Prefer grep/pytest commands over prose descriptions."

9. **Create `tests/test_ops_data_portal_validators.py`:**
   Minimum test specification (write all before running):
   - `test_file_path_rejects_absolute_unix`: `_validate_file_path("/abs/path")` raises ValueError
   - `test_file_path_rejects_absolute_windows`: `_validate_file_path("C:\\path.py")` raises ValueError
   - `test_file_path_rejects_backslash_separator`: `_validate_file_path("scripts\\module.py")` raises ValueError
   - `test_file_path_accepts_relative`: `_validate_file_path("scripts/module.py")` does not raise
   - `test_file_path_accepts_nonexistent_relative`: `_validate_file_path("scripts/future_file.py")` does not raise
   - `test_context_length_rejects_short`: `_validate_context_length("fix bug")` raises ValueError
   - `test_context_length_accepts_80_chars`: exactly 80-char string does not raise
   - `test_acceptance_lint_wired_into_file_rec`: `file_rec({..., "acceptance": 'python -c "x=1"'})` raises ValueError
   - `test_compute_automatable_boundary_file`: file matching a boundary pattern -> False
   - `test_compute_automatable_high_risk_score`: R > maturity_ceiling -> False
   - `test_compute_automatable_valid`: normal file + low R -> True
   - `test_automatable_override_warning`: caller-supplied automatable=True with formula=False: warning logged, result=False

10. **Run VP steps 1-12** (pre-deploy checks). All must pass before proceeding to data work.
    Fix any failures before continuing.

11. **Backfill null `file`/`context`/`acceptance` on open recs:**
    a. Run VP step 13 (Athena query) to get current null counts and rec IDs.
    b. For each rec with null/empty `file`: inspect title+context, identify target file, update
       via `update_rec(id, {"file": "path/to/file.py"})`. If unable to determine: close rec
       with `update_rec(id, {"status": "declined", "resolution": "..."})` as per manifest.
    c. For each rec with null/empty `context`: compose >= 80 char context explaining why rec
       exists. Update via `update_rec`.
    d. For each rec with null/empty `context` length < 80 chars: extend to >= 80 chars or close.
    e. For each rec with null/empty `acceptance`: compose verifiable shell command. Update.

12. **Convert prose acceptance commands:**
    a. Run VP step 14 (Athena query) to get current list of open automatable recs with
       non-command acceptance text.
    b. For each rec: read title/file/context to understand what should be verified. Compose
       a verifiable shell command (`grep -q 'pattern' file` for code changes; `pytest tests/... -k name`
       for test additions). Before updating:
       `.venv/Scripts/python.exe -c "from scripts.executor.acceptance_lint import lint_acceptance_command; ok,msg=lint_acceptance_command('<command>'); print('OK' if ok else msg)"`
       Must print `OK`. Do NOT call `update_rec` until the command passes lint.
    c. Update via `update_rec(id, {"acceptance": "..."})`.
    d. Do NOT guess -- derive from the rec's stated intent, not the current repo state.

13. **Update `config/data_quality/decisions/ops_recommendations.yaml`:**
    For `automatable`, `file`, `context`, `acceptance` fields:
    - Set `phase4_session: complete`
    - Add `resolved_date: '<today>'`
    - Add `resolution_pr: '<PR number once merged>'` (fill after merge).

14. **Update `docs/DECISIONS.md`:**
    Extend Decision 66 to explicitly record the 3-tier semantic enforcement architecture:
    - Tier A: Pre-write injection -- `get_rec_write_guidance()` surfaces ops.yaml `description`+`semantics`+registry to the agent before composition
    - Tier B: Write-time deterministic rejection -- `file_rec()` validators (path format, length, banned acceptance patterns, registry membership, derived fields automatable+risk)
    - Tier C: Execution-time feasibility -- `validate_acceptance_feasibility()` at executor run time (file existence, module availability)
    - Tier D: LLM semantic judge -- not yet implemented; filed as rec for future session

15. **Run VP steps 15-16** (post-deploy DQ checks):
    - Run the DQ runner to get current per-check verdicts for wave-2 checks.
    - Graduate `enforced: false -> enforced: true` for any wave-2 check whose
      `(table, column, test)` tuple has `verdict: PASS` in the freshly-written
      `logs/debug/dq-latest.json`. The graduation guard in `validate.py` enforces this
      mechanically -- if it blocks, the check is not yet passing and must not be graduated.
    - Confirm all remaining `enforced: false` entries have inline `# data condition` comment.

16. **Update `docs/INTENT-dq-enforcement.md`:**
    - Session Map wave-2 row: change `NOT_STARTED` -> `COMPLETE (PR #NNN)` (fill PR after merge).
    - Update `Last updated` date.

17. **Run VP step 17** (final full presubmit gate):
    `.venv/Scripts/python.exe -m scripts.validate`
    Must pass before opening PR.

18. **DEFERRED** (Decision 67 -- Lambda deployment blocked):
    `DEFERRED: .venv/Scripts/python.exe -m scripts.build_lambda --deploy &&`
    `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness`
    `(pending Decision 67 reversal -- config/executor_capabilities.yaml is Lambda-packaged)`

19. Report: what was implemented, VP results, recs updated, checks graduated, PR link.
