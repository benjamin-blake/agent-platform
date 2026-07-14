# Plan

## Intent
Reshape the `--pre` validation tier into the diff-aware fast tier specified in `docs/INTENT-ci-cd-architecture.md` Section 2: changed-files-only ruff/mypy, `pytest --picked -m "not integration"`, hard 5-minute budget assertion with breach/bypass rec filing via `ops_data_portal`, and a CI-guarded `--ignore-budget` escape hatch. This is the second of three follow-on IMPLEMENTATION plans queued by Decision 73; landing it makes the fast-tier contract real before `ci-workflow-restructure` flips PR CI to `--pre`.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/validate-fast-tier-reshape

## Phase
Phase Platform (automation infrastructure) -- runs in parallel with trading-system phases per `docs/ROADMAP.md`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/validate.py` | Modify | (1) Repurpose `get_changed_files()` to compare against `origin/main` with HEAD fallback (aligning with `scripts/plan_audit.py:51` precedent). (2) Reshape `--pre` body: diff-aware ruff/mypy on changed files, `pytest --picked --mode=branch -m "not integration"` (skip when no test files changed). (3) Add `_FAST_TIER_BUDGET_SECONDS = 300` module constant, wall-clock timer wrapping `--pre` body, post-work budget assertion with documented diagnostic. (4) Add `--ignore-budget` flag with CI guard (refuses when `os.environ.get("CI") == "true"`) and optional `--ignore-budget-reason "<text>"`. (5) Add `_file_budget_breach_rec()` and `_file_budget_bypass_rec()` helpers calling `ops_data_portal.file_rec()` with function-local imports and outbox fallback (Decision 51). |
| `requirements.txt` | Modify | Add `pytest-picked>=0.5.0`. |
| `config/data_quality/source_registry.yaml` | Modify | Register `budget_breach` and `budget_bypass` canonical_ids so `check_source_registry` accepts new sources. |
| `scripts/session_preflight.py` | Modify | Add `_check_budget_bypass_alert() -> dict \| None` helper (Athena query against `ops_recommendations_current` filtering `source='budget_bypass' AND created_timestamp > current_timestamp - INTERVAL '7' DAY`; returns dict with count + entries when count >= 3, else None). Add `report["budget_bypass_alert"]` top-level field; print informational note when non-None. |
| `.claude/skills/planning/SKILL.md` | Modify | Add new Preflight Constraints bullet for `budget_bypass_alert` field (informational; surface count + recent reasons as planning context). |
| `tests/test_validate.py` | Modify | Add six new test classes: `TestGetChangedFilesOriginMain`, `TestPreModeDiffAware`, `TestBudgetAssertion`, `TestIgnoreBudgetFlag`, `TestIgnoreBudgetCIGuard`, `TestBudgetBreachRecFiling`. |
| `tests/test_session_preflight.py` | Modify | Add `TestBudgetBypassAlert` class with three sub-tests (under threshold, at/over threshold, Athena query failure degrades gracefully). |
| `tests/test_*.py` (marker audit batch) | Modify | Surgical pass over the 14 AWS-importing test modules surfaced in planning preflight: add module-level `pytestmark = pytest.mark.integration` to modules that exercise real (un-mocked) AWS calls; leave mocks-only modules unmarked. Expected count: 5-10 modules. |
| `docs/INTENT-ci-cd-architecture.md` | Modify | Persist design state: Section 2 budget breach durability + escape hatch (replace `logs/.budget-breaches.jsonl` references with `source="budget_bypass"` warehouse path; document `--ignore-budget-reason`); Section 2.5 escape-hatch row file reference; Section 9 known-gaps mentioning JSONL; Section 10 sequencing note acknowledging planning-queue-governance (commit a124c04) merged on 2026-05-13. |

Scope is 9 entries. Five are mechanical or single-file (`requirements.txt`, `source_registry.yaml`, the SKILL.md bullet, INTENT updates, marker audit batch); the load-bearing work is concentrated in `scripts/validate.py` and the two test files. Decision 67 forbids STRATEGIC plans until executor returns, so this stays IMPLEMENTATION; the same calculus applied to Section 1 (planning-queue-governance, 6 entries).

## Bundled Recommendations
None. The five priority-queue recs (rec-429, rec-027, rec-457, rec-468, rec-296) are orthogonal. Adjacent validate.py recs found in the open queue (rec-616, rec-618, rec-715) are cosmetic; bundling would dilute scope.

## Acceptance Criteria
- [ ] `scripts/validate.py:get_changed_files()` body runs `git diff --name-only origin/main`; on returncode != 0 falls back to `git diff --name-only HEAD`. Signature unchanged.
- [ ] `scripts/validate.py:_FAST_TIER_BUDGET_SECONDS` declared at module level with value `300`.
- [ ] `scripts/validate.py:main()` exits non-zero with the documented diagnostic (contains the literal phrase "Fast tier exceeded budget") when `--pre` elapsed > `_FAST_TIER_BUDGET_SECONDS` and `--ignore-budget` was not passed.
- [ ] `scripts/validate.py:main()` exits non-zero with a CI-guard message (contains the literal phrase "cannot be used in CI") when `--ignore-budget` is passed and `os.environ.get("CI") == "true"`.
- [ ] `--pre` mode passes only changed-file paths to `ruff check`, `ruff format --check`, and `mypy` (verified via mock subprocess argv inspection in `TestPreModeDiffAware`).
- [ ] `--pre` mode invokes `pytest --picked --mode=branch -m "not integration"` when at least one test file is in the changed set; skips the invocation when no test files changed.
- [ ] On budget breach with `--ignore-budget` NOT set: `ops_data_portal.file_rec()` is called with `source="budget_breach"` and a body containing elapsed seconds, branch, diff manifest (verified via mock).
- [ ] On `--ignore-budget` usage (any outcome): `ops_data_portal.file_rec()` is called with `source="budget_bypass"`; body includes the optional `reason` (or null), branch, elapsed seconds (if measured), diff manifest (verified via mock).
- [ ] `logs/.budget-breaches.jsonl` is NOT created by any `--pre` invocation -- verified by absence after `--pre --ignore-budget` run.
- [ ] `config/data_quality/source_registry.yaml` contains entries for `budget_breach` and `budget_bypass`; `scripts/validate.py:check_source_registry()` does not surface either as a new violation.
- [ ] `scripts/session_preflight.py` report JSON gains a `budget_bypass_alert` top-level field whose value is either a dict (count >= 3 bypass recs in 7d) or null.
- [ ] `.claude/skills/planning/SKILL.md` Preflight Constraints section documents the `budget_bypass_alert` field.
- [ ] All new test classes pass; existing `tests/test_validate.py` and `tests/test_session_preflight.py` suites still pass.
- [ ] Marker audit decisions documented per file in the implementation report (which modules gained `pytestmark = pytest.mark.integration`, which were left unmarked, and the classification reason).
- [ ] `docs/INTENT-ci-cd-architecture.md` Sections 2, 2.5, 9 reflect the warehouse-routed audit design (no remaining references to `logs/.budget-breaches.jsonl`); Section 10 acknowledges planning-queue-governance landed as commit a124c04 on 2026-05-13.
- [ ] `requirements.txt` includes `pytest-picked>=0.5.0`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Confirm pytest-picked installs and imports | `.venv/Scripts/python.exe -m pip install -r requirements.txt && .venv/Scripts/python.exe -c "import pytest_picked"` | Both commands exit 0. | Adjust pinned version in requirements.txt to one available on PyPI; check `pip search pytest-picked` or PyPI page. |
| 2 | [pre-deploy] | get_changed_files semantics test | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestGetChangedFilesOriginMain -v` | All sub-tests pass; mocked subprocess argv shows first call references `origin/main`, fallback uses `HEAD`. | Inspect new function body; first subprocess.run argv must include `origin/main`. |
| 3 | [pre-deploy] | Budget constant value | `.venv/Scripts/python.exe -c "from scripts.validate import _FAST_TIER_BUDGET_SECONDS; assert _FAST_TIER_BUDGET_SECONDS == 300, f'got {_FAST_TIER_BUDGET_SECONDS}'"` | Exits 0. | Set module-level constant to 300. |
| 4 | [pre-deploy] | Diff-aware --pre tests | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestPreModeDiffAware -v` | All sub-tests pass; mocked argv shows changed-files scope passed to ruff/mypy, picked pytest invocation present. | Refactor `run_lint_checks` to accept and forward a files list; ensure `--pre` branch calls `get_changed_files()` before the lint pass. |
| 5 | [pre-deploy] | Budget assertion fires above threshold | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestBudgetAssertion -v` | Test asserts non-zero exit and "Fast tier exceeded budget" diagnostic when mocked elapsed > 300. | Ensure timer wraps the work and assertion fires AFTER work completes; do not pre-empt. |
| 6 | [pre-deploy] | Ignore-budget flag end-to-end | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestIgnoreBudgetFlag -v` | Mock asserts `file_rec` called with `source="budget_bypass"`; reason captured when supplied, null when omitted; assertion skipped. | Verify the bypass code path runs the bypass-rec helper BEFORE the budget-assertion branch. |
| 7 | [pre-deploy] | CI guard refuses --ignore-budget | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestIgnoreBudgetCIGuard -v` | Test asserts non-zero exit + "cannot be used in CI" message when CI=true env var set. | Order the CI guard check BEFORE the budget timer starts; never let bypass succeed under CI. |
| 8 | [pre-deploy] | Breach rec filing path + outbox fallback | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestBudgetBreachRecFiling -v` | Mock asserts `ops_data_portal.file_rec` called with `source="budget_breach"`; outbox-fallback path exercised when portal raises. | Wire the breach-filing helper into the post-assertion path; helper must catch portal exceptions and not re-raise. |
| 9 | [pre-deploy] | No local JSONL file is created | `rm -f logs/.budget-breaches.jsonl && .venv/Scripts/python.exe -m scripts.validate --pre --ignore-budget --ignore-budget-reason "VP step 9 test" 2>&1 \| tail -5 && test ! -f logs/.budget-breaches.jsonl` | Final `test ! -f` exits 0 (file does not exist). | Remove any residual code paths that write `.budget-breaches.jsonl`; verify no leftover writes from intermediate refactors. |
| 10 | [pre-deploy] | Source registry validates new sources | `.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); from scripts.validate import check_source_registry; failed=[]; check_source_registry(failed); print(repr(failed)); assert 'Source registry CI guard' not in failed"` | Prints `[]` (or any list NOT containing the registry CI guard); assertion passes. | Add `budget_breach` and `budget_bypass` entries to `source_registry.yaml` with description/owner per existing entry shape. |
| 11 | [pre-deploy] | Preflight surfaces budget_bypass_alert field | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py::TestBudgetBypassAlert -v` | All sub-tests pass; mocked Athena returns drive the dict-or-None decision; query failure degrades to None with a warning log. | Wire the helper into `session_preflight.py:main()` report assembly; reuse existing `_run_athena_query` helper. |
| 12 | [pre-deploy] | Marker audit -- pre tier does not invoke real AWS | `.venv/Scripts/python.exe -m scripts.validate --pre 2>&1 \| grep -E "(boto3\|athena\|s3\|STS)" \| head -5` | No matches (or only matches that are CLI tool path checks, not real client calls). Empty grep output is success. | Apply marker audit pass; re-mark any test module surfaced by the grep that exercises real AWS calls. |
| 13 | [pre-deploy] | Ruff/format check on the modified files | `.venv/Scripts/python.exe -m ruff check scripts/validate.py scripts/session_preflight.py tests/test_validate.py tests/test_session_preflight.py && .venv/Scripts/python.exe -m ruff format --check scripts/validate.py scripts/session_preflight.py tests/test_validate.py tests/test_session_preflight.py` | Both commands exit 0. | Run `ruff check --fix` and `ruff format`; re-run. |
| 14 | [pre-deploy] | Full existing test suites still green | `.venv/Scripts/python.exe -m pytest tests/test_validate.py tests/test_session_preflight.py tests/test_ops_data_portal.py -v` | All tests pass (existing + new). | Read failing tests; identify what broke; fix without regressing scope. |
| 15 | [pre-deploy] | INTENT doc references warehouse path, not JSONL | `grep -cE "budget-breaches\\.jsonl" docs/INTENT-ci-cd-architecture.md && grep -cE "source=\"budget_bypass\"\|source='budget_bypass'" docs/INTENT-ci-cd-architecture.md` | First grep prints `0`; second grep prints `>= 1`. | Edit INTENT Sections 2, 2.5, 9 to remove JSONL references and add `budget_bypass` source language. |
| 16 | [pre-deploy] | End-to-end `--pre` runs under budget | `time .venv/Scripts/python.exe -m scripts.validate --pre` | Exits 0; wall-clock measured by `time` shows < 5 min on typical local diff. | If breach fires unexpectedly, inspect the diagnostic for dominant phase; consider further `--pre` slimming via subsequent rec. |
| 17 | [pre-deploy] | Full presubmit still green | `.venv/Scripts/python.exe -m scripts.validate` | Exits 0. | Triage any failure surfaced by changes; the full tier should still pass after this plan. |

## Constraints
- No edits to `.github/workflows/*.yml` -- that is `ci-workflow-restructure` scope.
- No edits to `scripts/session_postflight.py` -- that is `ci-workflow-restructure` scope.
- No edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly (Single Portal Invariant).
- No new local-file write paths. The warehouse-as-truth invariant requires audit trail to land in Athena via `ops_data_portal`; the outbox handles offline-emergency persistence.
- No rescue agents or workaround loops (Decision 55).
- Branch protection is permanently unavailable (Decision 72); the gates introduced here are convention + tooling.
- Lambda deployment deferred (Decision 67). `scripts/validate.py`, `scripts/session_preflight.py`, and the test files are not Lambda-packaged. However, `config/data_quality/source_registry.yaml` IS packaged (`scripts/build_lambda.py:71` does `shutil.copytree(ROOT / "config", app_dir / "config")`), so the registry edit triggers the standard DEFERRED step instead of an active Lambda deploy. The Lambda dispatcher is currently disabled (Decision 67), so the local-vs-Lambda registry drift is acceptable until Decision 67 reverses.

## Context

### Why this plan is the second in the sequence
The Decision 73 follow-on queue has three plans: `planning-queue-governance`, `validate-fast-tier-reshape`, `ci-workflow-restructure`. Section 1 merged as commit a124c04 on 2026-05-13. Of the remaining two, this plan must land before `ci-workflow-restructure` because:

- `ci-workflow-restructure` flips PR CI from full tier to `--pre`. That flip only delivers value once `--pre` is actually diff-aware, picked, and budget-gated -- otherwise PR CI just runs the same slow exclusion-based work under a faster-sounding flag.
- The `--ignore-budget` escape hatch is the emergency-revert mechanism INTENT Section 9 requires before `ci-workflow-restructure` lands. The chicken-and-egg risk (faulty `validate.py` on main blocks all merges including its own revert) is mitigated by the bypass flag living in this plan.
- INTENT Section 9 lists `validate-fast-tier-reshape` ahead of `ci-workflow-restructure`.

### Design deviation 1: warehouse-routed bypass audit (replaces local JSONL)
INTENT Section 2 originally specified `logs/.budget-breaches.jsonl` as the audit log for `--ignore-budget` usage, with the soft alert (3+ uses in 7 days) read from that local file. This plan deviates: both budget breach AND ignore-budget bypass events file recs via `ops_data_portal.file_rec` (sources `budget_breach` and `budget_bypass`), and the soft alert is read from Athena. Rationale:

- Aligns with the warehouse-as-source-of-truth invariant in `CLAUDE.md`. Local files have exactly two valid roles (outbox / read cache); a third "local audit log" role weakens that invariant.
- Outbox (Decision 51) handles the offline-emergency case, so the local JSONL adds no resilience over the warehouse path.
- Cross-machine consistency: solo developer runs `--ignore-budget` on laptop + EC2 runner. Local-file approach fragments history per clone; Athena unifies it.
- Pattern precedented by Section 1 (planning-queue-governance), which chose Design B (state-driven L5 detection) over INTENT-literal rec-status-driven detection. INTENT updates ratify the deviation as part of this plan's Step 18 (Ordered Execution Steps).

### Design deviation 2: optional `--ignore-budget-reason`
INTENT Section 2 does not specify a reason field. This plan adds one as optional. Required would add friction to legitimate emergency use; optional preserves the soft alert at 3-in-7d as the discipline mechanism while letting operators capture intent when convenient. The bypass rec records `reason=null` when omitted.

### get_changed_files() consolidation
The plan repurposes `validate.py:get_changed_files()` from "uncommitted edits" semantics (`git diff --cached` + `HEAD` fallback) to "branch vs origin/main" semantics with HEAD fallback. This aligns the function with `scripts/plan_audit.py:51`, which already implements the same pattern. The only existing in-validate.py caller is `run_coverage_check()` at line 1771 -- the broader scope makes the advisory verifier-coverage report more comprehensive, not less.

Three test cases in `tests/test_validate.py` mock `validate.get_changed_files` wholesale; the semantic change does not break them. New `TestGetChangedFilesOriginMain` class covers the new behaviour.

Downstream hand-off: when `ci-workflow-restructure` lands and switches PR CI to `--pre`, that workflow MUST set `actions/checkout@v4` `fetch-depth: 0` (or sufficient depth) so origin/main is in the clone. Without it, `get_changed_files()` falls back to HEAD and `--pre` effectively scans the full repo via the fallback path. Flagged here so ci-workflow-restructure picks it up.

### Marker audit philosophy
Surgical, not aggressive. A test file that imports boto3 only to mock it should NOT carry `pytestmark = pytest.mark.integration` -- marking would exclude it from the fast tier even though it has no AWS dependency. The audit pass classifies each AWS-importing module by manual code reading: does at least one test exercise a real `boto3.client(...)`, `awswrangler.athena.read_sql_query(...)`, or equivalent un-mocked call? Mark only the real-AWS callers. Document the decision per file in the implementation report so future audits can verify.

### Why marker audit matters here (not deferred)
Per INTENT Section 1, the full tier's `-m "not integration"` exclusion is empty by construction today (only 2 tests carry the marker out of ~52 AWS-touching files). This plan removes the `-m "not integration"` filter from the FULL tier (which now runs unfiltered per INTENT Section 2 target state), and ADDS it to the FAST tier (`--pre` runs `pytest --picked -m "not integration"`). For the fast-tier filter to be meaningful, AWS-touching tests must carry the marker. Without the audit, the fast tier would skip almost no tests and the budget assertion would fire on every run.

### Related decisions
- **Decision 73**: the umbrella decision this plan implements a slice of (two-tier diff-aware CI with forward-fix).
- **Decision 60**: two-tier validation. This plan preserves the abstraction; the 5-minute budget moves from documentation to enforced assertion (the failure mode Decision 60 documented).
- **Decision 51**: outbox-as-write-ahead. The breach + bypass rec filing paths reuse this pattern for transient AWS unavailability.
- **Decision 57**: SSO recovery on auth expiry. The breach-filing path attempts interactive SSO refresh in local sessions and skips it under `CI=true`.
- **Decision 67**: Lambda + STRATEGIC plans deferred. This plan is IMPLEMENTATION despite touching 9 scope rows; rationale: most rows are mechanical or single-file edits, with load-bearing work concentrated in `scripts/validate.py`.
- **Decision 68**: self-hosted runner. The full tier (unchanged by this plan) continues to run on EC2; the fast tier moving to `--picked` will reduce per-PR runtime once `ci-workflow-restructure` flips PR CI to `--pre`.

### Open ci-rca recs at planning time
Preflight on 2026-05-13 showed **zero** open ci-rca recs (`ci_rca_recs: []` in the report). The Section 1 HARD BLOCK is therefore inert, and this plan's Related-Work Check is satisfied vacuously. Planning skill writes the PLAN file without deferral rationale needed.

### Known gotchas
- `pytest-picked` selects tests based on `git status` by default. The `--mode=branch` flag uses branch-vs-main diff (matching the new `get_changed_files()` semantics). When the picked set is empty, `pytest --picked` exits 5 (no tests collected); the fast tier must treat exit 5 as success, not failure.
- `subprocess.run` calls in `validate.py` already follow the Windows encoding convention (`encoding="utf-8", errors="replace"`); preserve this pattern for any new subprocess calls.
- `_VALIDATE_DEPTH` recursion guard exists at the top of `main()`. The budget timer must respect this guard; do not start the timer when depth >= 1.
- The `ops_data_portal.file_rec()` import is local to the breach/bypass helpers (NOT module-level) so that `validate.py` never raises during import even if `ops_data_portal` itself has a transient init issue. Pattern matches INTENT Section 2 connectivity fallback design.
- Stash drawer has 10 entries; do NOT run `git stash pop` during this plan's execution -- they belong to unrelated prior sessions.
- The `ops_recommendations_current` view was flagged stale during planning preflight (`VIEW_IS_STALE` for `telemetry_agent_invocations_current` -- a different view, but worth noting). If the bypass-alert Athena query returns view-stale errors, the helper should degrade to None with a warning log, not raise.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` (Decisions 51, 57, 60, 67, 68, 72, 73) read
- [ ] `docs/INTENT-ci-cd-architecture.md` Sections 2, 2.5, 9, 10 read
- [ ] `scripts/plan_audit.py:51` `get_changed_files` precedent reviewed
- [ ] `scripts/ops_data_portal.py:file_rec` API surface confirmed
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Modify `scripts/validate.py:get_changed_files()`** -- replace body with `git diff --name-only origin/main` first, fallback to `git diff --name-only HEAD` on returncode != 0. Keep signature. Update docstring to reflect new semantics. Behaviour matches `scripts/plan_audit.py:51`.

2. **Modify `requirements.txt`** -- add `pytest-picked>=0.5.0` under the `# Development` block. Install locally: `.venv/Scripts/python.exe -m pip install -r requirements.txt`.

3. **Modify `config/data_quality/source_registry.yaml`** -- add two new entries with `canonical_id: budget_breach` and `canonical_id: budget_bypass`, each with description and owner fields matching the existing entry shape.

4. **Modify `scripts/validate.py`** -- add module-level constant `_FAST_TIER_BUDGET_SECONDS = 300`.

5. **Modify `scripts/validate.py`** -- add `_file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None` helper. Body uses a function-local `from scripts.ops_data_portal import file_rec` import. On any exception, log a warning to stderr and suppress (outbox handles durable persistence; never re-raise from the breach-filing path).

6. **Modify `scripts/validate.py`** -- add `_file_budget_bypass_rec(elapsed_s: float | None, diff_manifest: list[str], reason: str | None) -> None` helper. Same connectivity-fallback pattern as `_file_budget_breach_rec`. `elapsed_s` may be None if the bypass fires before any work runs.

7. **Modify `scripts/validate.py:main()`** -- add two new argparse args:
   - `--ignore-budget` (action=store_true, help text explains the escape-hatch role and CI restriction)
   - `--ignore-budget-reason` (optional string, default=None, help text explains it is for the bypass audit rec)

8. **Modify `scripts/validate.py:main()`** -- add CI guard check immediately after `args = parser.parse_args()`: if `args.ignore_budget and os.environ.get("CI") == "true"`, print error containing the literal phrase "cannot be used in CI" and exit 1.

9. **Modify `scripts/validate.py:main()`** -- in the `if args.pre:` branch, wrap the existing body with `time.monotonic()` timer. After the work completes, check elapsed and dispatch:
   - If `args.ignore_budget`: call `_file_budget_bypass_rec(elapsed, diff_manifest, args.ignore_budget_reason)`; print a notice; exit per `failed` list.
   - Else if `elapsed > _FAST_TIER_BUDGET_SECONDS`: call `_file_budget_breach_rec(elapsed, diff_manifest, dominant_phase)`; print the documented diagnostic ("Fast tier exceeded budget (5 min). Elapsed: X min."); exit 1.
   - Else: existing summary + exit logic.

10. **Modify `scripts/validate.py:main()`** -- reshape the `if args.pre:` body to use changed-files scope:
    - Call `get_changed_files()` once at the top of the pre branch.
    - Pass the file list to a refactored `run_lint_checks(failed, files=changed)`.
    - Add a `mypy` invocation restricted to changed `.py` modules.
    - Add `pytest --picked --mode=branch -m "not integration"` invocation, but only when at least one path in `changed` matches `tests/test_*.py` or `tests/**/test_*.py`. Treat pytest exit code 5 (no tests collected) as success.
    - Keep existing static checks (`validate_iam_runner_policy`, `validate_copilot_multipliers`, `validate_prompt_files`, `validate_cli_tools_in_prompts`) -- these are fast and operate on fixed paths.

11. **Modify `scripts/validate.py:run_lint_checks(failed, files=None)`** -- update signature to accept optional `files: list[str] | None`. When None: retain current full-scope behaviour. When non-empty: restrict ruff/format invocation to those files. When empty list: skip lint entirely (nothing changed in scope).

12. **Modify `scripts/session_preflight.py`** -- add `_check_budget_bypass_alert() -> dict | None` helper. Athena query (via existing `_run_athena_query`): `SELECT id, reason, created_timestamp FROM ops_recommendations_current WHERE source='budget_bypass' AND created_timestamp > (current_timestamp - INTERVAL '7' DAY) ORDER BY created_timestamp DESC LIMIT 10`. If row count >= 3, return dict `{"count": N, "entries": [...]}`. Else return None. Wrap the query call in try/except; on failure log warning and return None.

13. **Modify `scripts/session_preflight.py:main()`** -- assemble `report["budget_bypass_alert"] = _check_budget_bypass_alert()`. Print an informational note ("Budget bypass alert: N invocations in 7 days") when non-None; do not print when None.

14. **Modify `.claude/skills/planning/SKILL.md`** -- add new Preflight Constraints bullet (alphabetically/ordinally placed adjacent to the other alert bullets added by Section 1):
    > "**`budget_bypass_alert` non-null** -- Informational. Surface count and recent reasons; note to operator that repeated `--ignore-budget` use indicates fast-tier drift and likely warrants a planning session to revisit the budget or the slow check."

15. **Modify `tests/test_validate.py`** -- add six new test classes, each with multiple sub-tests where helpful:
    - `TestGetChangedFilesOriginMain`: origin-main happy path, HEAD fallback on non-zero returncode, empty result handling.
    - `TestPreModeDiffAware`: mocked argv inspection for ruff/format/mypy/pytest invocations carry changed-files scope; empty changed set triggers expected skip behaviour.
    - `TestBudgetAssertion`: mocked `time.monotonic` returns simulate breach (> 300s) and within-budget runs; assert exit codes + diagnostic text.
    - `TestIgnoreBudgetFlag`: mocked `file_rec` asserted with `source="budget_bypass"`; reason captured when provided; reason null when omitted; assertion skipped.
    - `TestIgnoreBudgetCIGuard`: `monkeypatch.setenv("CI", "true")`; `--ignore-budget` invocation exits 1 with the documented message.
    - `TestBudgetBreachRecFiling`: mocked `file_rec` asserted with `source="budget_breach"` body fields; portal-raises path exercises the suppress-and-log fallback.

16. **Modify `tests/test_session_preflight.py`** -- add `TestBudgetBypassAlert` class:
    - `test_returns_none_under_threshold`: mocked Athena returns 2 rows; helper returns None.
    - `test_returns_dict_at_threshold`: mocked Athena returns 3 rows; helper returns dict with count=3 and entries.
    - `test_returns_none_on_query_failure`: mocked Athena raises; helper returns None and logs warning (assert via captured logging or stderr).

17. **Marker audit batch** -- inspect the 14 AWS-importing test files identified in planning preflight:
    - `tests/test_session_preflight.py`, `tests/test_ops_data_portal.py`, `tests/test_verifiers/test_schema_integrity.py`, `tests/test_data_quality_runner.py`, `tests/test_cleanup_ops_rec_orphans.py`, `tests/test_verifiers/test_data_quality.py`, `tests/test_ops_writer.py`, `tests/test_verifiers/test_causal_chain.py`, `tests/test_sensors.py`, `tests/test_sync_ops.py`, `tests/test_verifiers/test_athena_views.py`, `tests/test_validate_telemetry.py`, `tests/test_telemetry_schemas.py`, `tests/test_pysr_factory.py`.
    - For each: classify (real-AWS call un-mocked vs mocks-only). Mark with `pytestmark = pytest.mark.integration` at module level if real-AWS. Leave unmarked if mocks-only.
    - Document each decision in the implementation report.

18. **Modify `docs/INTENT-ci-cd-architecture.md`** -- persist design state:
    - Section 2 "Budget breach durability" subsection: augment to note that `--ignore-budget` invocations also route through `ops_data_portal.file_rec` as `source="budget_bypass"` with the same outbox fallback; both events share the connectivity-recovery chain.
    - Section 2 "Budget breach escape hatch" subsection: replace `logs/.budget-breaches.jsonl` references with the `source="budget_bypass"` rec filing path; document the optional `--ignore-budget-reason` flag.
    - Section 2.5 row "Budget assertion escape hatch": update enforcement file reference (still `scripts/validate.py`) and replace audit-log description with warehouse path.
    - Section 9 known gaps: update the bullet that mentions `logs/.budget-breaches.jsonl`; cross-reference the warehouse path and outbox fallback.
    - Section 10 sequencing constraint: append a note that `planning-queue-governance` landed as commit a124c04 on 2026-05-13; L5 enforcement (HARD BLOCK + relatedness check + observability surfaces) is therefore in force; `validate-fast-tier-reshape` and `ci-workflow-restructure` may now cite this INTENT as in-force design.

19. **DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal).** The `config/data_quality/source_registry.yaml` edit in Step 3 lands in a Lambda-packaged directory (`scripts/build_lambda.py:71` copies all of `config/` into `data-pipeline.zip`). Per CLAUDE.md and Decision 67, active deployment is suspended; the local registry edit is canonical for non-Lambda paths (validate.py `check_source_registry`, session_preflight Athena query) until Decision 67 reverses and Lambda is re-deployed via the runbook in CLAUDE.md.

20. **Execute Verification Plan** -- run each VP step in order. Loop until pass. If a V3-equivalent step fails unrecoverably, stop and analyze root cause (Decision 55).

21. **Report** -- summarize what was implemented, verification results, marker audit decisions (per-file), any deviations from this plan, and a one-line confirmation that `ci-workflow-restructure` may now flip PR CI to `--pre`.

## Known Gaps
- **CI fetch-depth dependency**: `ci-workflow-restructure` must set `fetch-depth: 0` on `actions/checkout` when switching PR CI to `--pre`. Without it, `get_changed_files()` falls back to HEAD and `--pre` effectively scans the full repo. Documented in Context; flagged for hand-off.
- **Marker audit completeness**: surgical classification depends on manual code reading. Tests may mock AWS imperfectly (e.g., partial mock leaks a real call). Future hardening could mechanize via a conftest-time fixture that fails any test reaching `boto3.client(...)` without an integration marker; deferred to a follow-on rec.
- **`pytest --picked` false-negatives**: git-status-based selection can miss tests whose coverage is implicit (e.g., parametrize fixtures defined elsewhere). INTENT Section 9 notes a possible future upgrade to `pytest-testmon`; not in scope here.
- **INTENT amendment formality**: The deviations from INTENT Section 2 (warehouse-routed bypass audit, `--ignore-budget-reason`) are applied to the INTENT file as part of Step 18. No separate Decision Record is filed; if formal ratification is desired later, it can land as a small follow-up.
- **Dominant-phase identification**: the breach diagnostic mentions "dominant phase identified from phase timing" (INTENT Section 2). The first implementation uses a coarse heuristic (longest single step in the `--pre` body). Refinement is deferred to a future rec if the heuristic produces unhelpful diagnostics in practice.
- **Cross-harness SKILL.md drift**: per Decision 58, `.agents/skills/planning/SKILL.md` is the canonical interactive workflow layer for Antigravity. This plan updates only `.claude/skills/planning/SKILL.md` (the Claude Code path) -- the same scope Section 1 (commit a124c04) chose. The Antigravity copy is therefore stale relative to both Section 1's changes and this plan's. Resolving the drift is its own follow-up, not in this plan's scope, because syncing the Antigravity copy requires re-validating every Section 1 change (HARD BLOCK semantics, Related-Work Check, three new preflight alert bullets) plus this plan's new bullet, against the slightly different Antigravity skill structure.
