# Plan

## Intent
Land the planning-queue-governance contract from `docs/INTENT-ci-cd-architecture.md` Section 2.5 so the INTENT becomes citable as in-force per Section 10's sequencing constraint. This unblocks the two queued follow-on plans (`validate-fast-tier-reshape`, `ci-workflow-restructure`) and anchors L5 enforcement (planning hard-block on open ci-rca recs) plus the supporting observability surfaces (liveness fallback, forward-fix recursion alert, non-automatable soft-cap).

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/planning-queue-governance

## Phase
Phase Platform (automation infrastructure) -- runs in parallel with trading-system phases per `docs/ROADMAP.md`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.claude/skills/planning/SKILL.md` | Modify | Invert ci-rca preflight conditional from "Non-blocking but high priority" to HARD BLOCK; drop MANDATORY treatment of `non_automatable_recommendations`; add new "Related-Work Check" sub-step in workflow Step 8 with the three relatedness conditions and deferral-rationale fallback. |
| `scripts/session_preflight.py` | Modify | Promote ci-rca section to top of report with HARD BLOCK banner when open ci-rca recs exist; add three new report fields (`non_automatable_softcap_breached`, `ci_rca_liveness_alert`, `forward_fix_recursion_alert`) backed by Athena and `gh` queries; emit informational alerts when thresholds breach. Design B for L5: query main CI state directly (no rec status mutation). |
| `scripts/ops_data_portal.py` | Modify | Add explicit gate inside `file_rec()`: when `source == "ci_rca"` and `file` is empty/missing, raise `ValueError` with a directive message. Defense-in-depth on top of the existing `not_null` write-time validator; survives any future relaxation of the global path-syntax check. |
| `.claude/agents/scheduled/ci-rca.md` | Modify | Update the agent contract template's `file_rec` example to include `--file` populated with the primary file implicated by the diagnosis; add a Hard Rule entry stating that `--file` is contract-required for `source="ci_rca"`. |
| `tests/test_session_preflight.py` | Modify | Add unit tests for: HARD BLOCK ordering when ci-rca recs exist, non-automatable soft-cap field emission, liveness fallback alert under red-main-no-rec conditions, forward-fix recursion counter at threshold. All AWS/`gh` calls mocked. |
| `tests/test_ops_data_portal.py` | Modify | Add unit tests for the ci-rca source-file gate: `file_rec({"source": "ci_rca", "file": ""})` raises `ValueError`; same call with `file="scripts/foo.py"` succeeds (or returns `pending-` when DynamoDB is mocked-unreachable). |

## Bundled Recommendations
None. The 5 priority queue items (rec-429, rec-027, rec-457, rec-468, rec-296) are orthogonal to planning-queue-governance.

## Acceptance Criteria
- [ ] `.claude/skills/planning/SKILL.md` line for `ci_rca_recs` reads as a HARD BLOCK (contains the literal word "HARD BLOCK" and the phrase "cannot scope unrelated work") and no longer carries the "Non-blocking but high priority" language.
- [ ] `.claude/skills/planning/SKILL.md` `non_automatable_recommendations` conditional drops MANDATORY discussion language; replaced with informational surfacing.
- [ ] `.claude/skills/planning/SKILL.md` workflow Step 8 (Write PLAN) gains a "Related-Work Check" sub-section enumerating the three relatedness conditions (same `file`, same Decision Record, same failure category) and the deferral-rationale fallback in the new plan's Context section.
- [ ] `scripts/session_preflight.py` `print_ci_rca_recs()` prints a HARD BLOCK banner header line when the input list is non-empty; the section is printed before the priority queue when recs are present.
- [ ] Preflight report JSON gains three new top-level fields: `non_automatable_softcap_breached: bool`, `ci_rca_liveness_alert: dict | None`, `forward_fix_recursion_alert: dict | None` (the dict shapes include enough detail for the planning agent to surface the alert clearly).
- [ ] Soft-cap constant `_NON_AUTOMATABLE_SOFTCAP = 250` declared at module level in `scripts/session_preflight.py`; preflight emits the breach field when `non_automatable_recommendations > _NON_AUTOMATABLE_SOFTCAP`.
- [ ] Liveness fallback: when `gh` reports the most recent push-to-main `ci.yml` run has `conclusion="failure"`, the run is older than 30 minutes, AND no `source="ci_rca"` rec has `created_timestamp` after that run's `createdAt`, preflight sets `ci_rca_liveness_alert` non-None with the failing run URL and elapsed time.
- [ ] Forward-fix recursion: when `>=3` ci-rca recs created within the last 24 hours share any `file` value, preflight sets `forward_fix_recursion_alert` non-None with the overlapping file and rec IDs.
- [ ] `scripts/ops_data_portal.file_rec({"source": "ci_rca", "file": ""})` raises `ValueError` whose message contains `source_file` (or equivalent directive).
- [ ] `.claude/agents/scheduled/ci-rca.md` Step 5 file_rec example includes `--file <path>` populated with the file implicated by the diagnosis; the Constraints/Hard Rule section states `--file` is mandatory for ci-rca recs.
- [ ] New unit tests in `tests/test_session_preflight.py` cover the four new behaviours, all passing.
- [ ] New unit tests in `tests/test_ops_data_portal.py` cover both the empty-file rejection path and the populated-file success path for `source="ci_rca"`, all passing.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm SKILL.md HARD BLOCK language present | `grep -E "HARD BLOCK\|cannot scope unrelated work" .claude/skills/planning/SKILL.md` | Both phrases appear at least once. | Edit SKILL.md to include the missing phrase. |
| 2 | [pre-deploy] | Confirm SKILL.md MANDATORY language removed for non-automatable | `grep "non_automatable.*MANDATORY" .claude/skills/planning/SKILL.md && echo FOUND \|\| echo CLEAN` | Prints `CLEAN`. | Edit SKILL.md to remove the MANDATORY discussion line for non-automatable recs. |
| 3 | [pre-deploy] | Confirm SKILL.md Related-Work Check section is present and enumerates all three conditions | `grep -c -E "same.*file\|same Decision Record\|same failure category" .claude/skills/planning/SKILL.md` | Count >= 3. | Edit SKILL.md to add the missing condition(s). |
| 4 | [pre-deploy] | Run the existing preflight test suite to confirm no regressions | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py -v` | All tests pass (existing + new). | Read the failing test, identify what broke, fix the implementation. |
| 5 | [pre-deploy] | Exercise the new HARD BLOCK banner with a mocked ci-rca rec list | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py::TestCiRcaHardBlock -v` | New test class exists and passes; output of `print_ci_rca_recs` with one mock rec contains "HARD BLOCK". | Implement the banner in `print_ci_rca_recs` and re-run. |
| 6 | [pre-deploy] | Exercise the soft-cap field emission | `.venv/Scripts/python.exe -c "import json,sys; sys.path.insert(0, '.'); from scripts.session_preflight import _NON_AUTOMATABLE_SOFTCAP; print(_NON_AUTOMATABLE_SOFTCAP)"` | Prints `250`. | Add `_NON_AUTOMATABLE_SOFTCAP = 250` at module level. |
| 7 | [pre-deploy] | Exercise the liveness fallback alert builder with mocked gh + Athena returns | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py::TestCiRcaLivenessAlert -v` | Test asserts alert dict is set under red-main-no-rec conditions and is None otherwise. | Implement the alert builder; ensure mock branches cover both states. |
| 8 | [pre-deploy] | Exercise the forward-fix recursion alert builder | `.venv/Scripts/python.exe -m pytest tests/test_session_preflight.py::TestForwardFixRecursion -v` | Test asserts alert triggers at count >= 3 over rolling 24h, does not trigger below threshold. | Implement the counter; verify threshold comparison is `>=`. |
| 9 | [pre-deploy] | Exercise the ci-rca source-file gate (rejection) | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py::TestCiRcaSourceFileGate::test_rejects_empty_file -v` | Test passes; `ValueError` raised with `source_file` in message. | Add the gate inside `file_rec()` before the existing validators. |
| 10 | [pre-deploy] | Exercise the ci-rca source-file gate (success) | `.venv/Scripts/python.exe -m pytest tests/test_ops_data_portal.py::TestCiRcaSourceFileGate::test_accepts_populated_file -v` | Test passes; non-empty `file` proceeds past the gate. | Ensure the gate's condition is `not fields.get("file")`, not a stricter check. |
| 11 | [pre-deploy] | Confirm ci-rca.md agent contract requires `--file` | `grep -E "\\-\\-file" .claude/agents/scheduled/ci-rca.md` | At least one match in the Step 5 file_rec example. | Add `--file <path>` to the file_rec example and a Hard Rule note. |
| 12 | [pre-deploy] | Run the full lint + format check before committing | `.venv/Scripts/python.exe -m ruff check scripts/session_preflight.py scripts/ops_data_portal.py tests/test_session_preflight.py tests/test_ops_data_portal.py && .venv/Scripts/python.exe -m ruff format --check scripts/session_preflight.py scripts/ops_data_portal.py tests/test_session_preflight.py tests/test_ops_data_portal.py` | Both commands exit 0. | Run `ruff check --fix` and `ruff format`; re-run. |
| 13 | [pre-deploy] | Exercise preflight end-to-end (real Athena, sandbox account) | `.venv/Scripts/python.exe -m scripts.session_preflight 2>&1 \| head -50` | Runs to completion; JSON output contains the three new top-level fields. With 0 open ci-rca recs today, the liveness alert may fire if main is currently red without a rec; otherwise all three new fields are False/None. | If a query fails, inspect stderr; if a field is missing from JSON, ensure `report` dict in `main()` is updated to include them. |
| 14 | [pre-deploy] | Confirm the existing presubmit (validate.py) still passes locally | `.venv/Scripts/python.exe -m scripts.validate --pre` | Exits 0. | Address any lint/format/prompt-compliance failures the fast tier surfaces. |

## Constraints
- No edits to `scripts/validate.py` -- that is `validate-fast-tier-reshape` scope.
- No edits to `.github/workflows/*.yml` -- that is `ci-workflow-restructure` scope.
- No edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly (Single Portal Invariant).
- No rescue agents or workaround loops (Decision 55).
- Branch protection is permanently unavailable (Decision 72); the gates introduced here are convention + tooling, not GitHub API enforced.
- Lambda deployment deferred (Decision 67); none of the in-scope files are Lambda-packaged.

## Context

### Why this plan is the first in the sequence
INTENT Section 10 ("Sequencing constraint"): the INTENT cannot be cited as in-force until `planning-queue-governance` lands. The reason is that the INTENT promises planning-skill enforcement of L5 hard-block and the suspension of mandatory non-automatable surfacing, but the INTENT itself does not edit `.claude/skills/planning/SKILL.md`. This plan is the artefact that makes those SKILL.md changes. Citation from `validate-fast-tier-reshape` and `ci-workflow-restructure` would otherwise produce contradictory behaviour between the documented INTENT and the SKILL.md rules actually in force.

### Design B chosen for L5 enforcement (Decision Record)
Two design options were considered for how L5/L6 detect "the block is active":

- **Design A (rec-status-driven, per INTENT literal):** L5 queries `source="ci_rca" AND status="open"` recs. Requires an L7 closer (workflow step or watcher) that calls `update_rec(status="closed")` when main goes green. Produces a clean queryable lifecycle history.
- **Design B (main-state-driven, chosen):** L5 queries main CI state directly (`gh run list --branch main --workflow ci.yml --event push --limit 1`). The rec's `status` is observational, not a gate. No L7 closer needed; the block evaporates automatically when main goes green.

Trade-off summary: Design B removes the L7 closer requirement entirely, sidesteps the question of whether the closer belongs in `planning-queue-governance` or `ci-workflow-restructure`, and is purely state-driven (no maintenance writes to ops_recommendations from automated processes). Design A produces cleaner historical audit data per rec but requires a second write path and arbitrary close lag if the closer is a polling watcher.

Choice rationale (recorded here so future sessions know the deviation from INTENT literal):
- L7's INTENT Section 2.5 row names "the full-tier workflow on the forward-fix PR's merge to main" as the enforcement file. Removing the L7 closer simplifies `ci-workflow-restructure` -- the post-merge workflow only needs to re-fire queued auto-merges (which it has to do anyway) and does not need a separate `update_rec` step.
- Zero open ci-rca recs exist today (preflight observed 2026-05-13), so the lifecycle gap (recs stay open forever) is unprovable in production until the first ci-rca rec is filed.
- Design B aligns with the "deterministic preflight check" instinct surfaced during planning clarification.

INTENT amendment required: Section 4 step 6 reads "ci-rca rec closes on green; unblocks L5/L6". Under Design B this becomes "L5/L6 unblock on green; rec stays open as historical record". Section 2.5 row L7 becomes a no-op under Design B. This amendment is **not** in scope for this plan (would be out of charter -- a STRATEGIC-level redirect); it is recorded in this plan's Context section and the implementation reflects Design B. A follow-on Decision Record can ratify the amendment after the implementation lands.

### Auto-merge re-firing is out of scope
INTENT Section 5 specifies that queued PRs "flush in FIFO order through the standard auto-merge flow" when main returns to green. The flush mechanism is a `workflow_run`-triggered workflow on `ci.yml` `conclusion=success`. That workflow lives in `.github/workflows/` and is owned by `ci-workflow-restructure`. This plan does not implement it. Until `ci-workflow-restructure` lands, paused PRs require a manual re-trigger of postflight or a manual `gh pr merge --auto` after main recovers.

### Related decisions
- **Decision 73** (the umbrella decision this plan implements a slice of): two-tier diff-aware CI with forward-fix.
- **Decision 72** (RCA-as-plan-source for CI): defines the ci-rca agent and its rec contract. This plan tightens that contract by elevating `file` to mandatory for `source="ci_rca"`.
- **Decision 72** (branch protection unavailable, same date, separately numbered): the reason gates here are convention + tooling.
- **Decision 67** (Lambda + STRATEGIC plans deferred): the reason non-automatable backlog surfacing is suspended (rather than removed permanently). When Decision 67 reverses and the executor returns to service, the non-automatable rule needs revisiting; the 250 soft-cap provides a forcing function in the interim.
- **Decision 60** (two-tier validation): preserved unchanged by this plan. The budget-assertion piece of Decision 60's redesign is owned by `validate-fast-tier-reshape`.

### Known gotchas
- `gh` CLI is the source of truth for "is main currently red". Adding a `gh` subprocess call to `session_preflight.py` is new for that file but consistent with existing repo conventions (CLAUDE.md runbook, `.claude/agents/scheduled/ci-rca.md`). The call must use `capture_output=True, text=True, encoding="utf-8", errors="replace"` per Windows subprocess gotcha.
- `_run_athena_query` is already wired in `session_preflight.py`. New queries reuse it; no boto3 import additions needed at module scope.
- The Pydantic gate on `source="ci_rca"` is **explicit** (`if fields.get("source") == "ci_rca" and not fields.get("file"): raise ValueError(...)`) placed before `_load_write_time_validators` runs in `file_rec()`. This produces a clearer error message than waiting for the generic `not_null` validator and survives any future relaxation of that validator. Defense-in-depth, not duplication.
- `source_file` in INTENT Section 5 is a semantic re-labeling of the existing `file` field; no schema extension is performed. The ci-rca contract requirement is on populating `file` with the file implicated by the diagnosis.

### Open ci-rca recs status at planning time
Preflight on `2026-05-13` showed **zero** open ci-rca recs. This means:
- The HARD BLOCK is well-defined but inert today; first proof-in-production is when ci-rca next fires.
- The liveness fallback alert will fire if main is red without a rec; preflight already shows main green at planning time.
- The forward-fix recursion alert will not fire today (no recs to count).
- Tests must cover all three states via mocks; production observation is not a verification surrogate.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md (Decision 73, Decision 72, Decision 67) read
- [ ] `docs/INTENT-ci-cd-architecture.md` Sections 2.5, 4, 5, 9, 10 read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Design B trade-off (no L7 closer) acknowledged

## Ordered Execution Steps

1. **Modify `scripts/ops_data_portal.py`** -- add the explicit ci-rca source-file gate inside `file_rec()` before line 287 (the `_derive_computed_fields` call): when `fields.get("source") == "ci_rca" and not (fields.get("file") or "").strip()`, raise `ValueError` with message starting "source='ci_rca' requires non-empty source_file (the file implicated by the failure diagnosis); see .claude/agents/scheduled/ci-rca.md". Defense-in-depth on top of the existing write-time validators.

2. **Modify `.claude/agents/scheduled/ci-rca.md`** -- update Step 5 (File the recommendation) to include `--file <repo-relative-path>` in the example command; document that the file is the primary file implicated by the diagnosis. Add a bullet in the Hard Rule section: "`--file` is contract-required for `source=ci_rca`; the portal rejects writes with empty `file`."

3. **Modify `scripts/session_preflight.py`** -- add module-level constant `_NON_AUTOMATABLE_SOFTCAP = 250`. Add three new helper functions:
   - `_check_non_automatable_softcap(non_auto_count: int) -> bool` returns `non_auto_count > _NON_AUTOMATABLE_SOFTCAP`.
   - `_check_ci_rca_liveness(sso_status: str) -> dict | None` shells out to `gh run list --branch main --workflow ci.yml --event push --limit 1 --json conclusion,createdAt,url`; if conclusion is `failure` AND elapsed since `createdAt` > 30 min AND `_fetch_ci_rca_recs_since(timestamp)` returns empty, returns a dict `{"run_url": ..., "elapsed_minutes": ...}`; otherwise None. New helper `_fetch_ci_rca_recs_since(ts: str)` runs an Athena query `SELECT id FROM ops_recommendations_current WHERE source='ci_rca' AND created_timestamp > '<ts>'`.
   - `_check_forward_fix_recursion() -> dict | None`: Athena query `SELECT file, COUNT(*) AS cnt FROM ops_recommendations_current WHERE source='ci_rca' AND created_timestamp > <24h ago> GROUP BY file HAVING COUNT(*) >= 3`; returns first overlapping group as `{"file": ..., "count": ..., "threshold": 3}` or None.

4. **Modify `scripts/session_preflight.py`** -- update `print_ci_rca_recs(recs)` to emit a banner header line `"  [HARD BLOCK] /plan cannot scope unrelated work while these recs are open."` immediately after the section header when `recs` is non-empty. Also update `main()` to call `print_ci_rca_recs` BEFORE `print_priority_queue` when `ci_rca_recs` is non-empty (re-order conditionally).

5. **Modify `scripts/session_preflight.py`** -- in `main()`, after the existing report dict assembly, add three fields:
   - `report["non_automatable_softcap_breached"] = _check_non_automatable_softcap(non_automatable_count)`
   - `report["ci_rca_liveness_alert"] = _check_ci_rca_liveness(sso_status)`
   - `report["forward_fix_recursion_alert"] = _check_forward_fix_recursion()`

6. **Modify `.claude/skills/planning/SKILL.md`** Preflight Constraints section:
   - Change the `ci_rca_recs` bullet from "Non-blocking but high priority" to "**HARD BLOCK**. `/plan` cannot scope unrelated work while any open ci-rca rec exists. Surface the list at the top of the planning context. Proceed only to scope work that satisfies one of the three Related-Work conditions (see Step 8) OR has a logged deferral rationale in the new plan's Context section."
   - Change the `non_automatable_recommendations` bullet from "MANDATORY discussion. Present each and require human decision..." to "Informational. Surface counts; do not require per-rec discussion. MANDATORY treatment is suspended per Decision 73 until Decision 67 reverses." Add a sub-bullet for the new `non_automatable_softcap_breached` field: "If true (count > 250), surface as a planning context note."
   - Add new bullets for the two new alert fields: "**`ci_rca_liveness_alert` non-null**" and "**`forward_fix_recursion_alert` non-null**" both labelled as HARD ALERTs requiring human triage before continuing.

7. **Modify `.claude/skills/planning/SKILL.md`** workflow Step 8 (Write PLAN-{slug}.md) section: add a sub-section "Related-Work Check (when ci-rca recs are open)" that enumerates the three relatedness conditions verbatim from INTENT Section 5 (same `file` as the ci-rca rec, same Decision Record cited, same failure category from the canonical list of 8 categories) and states that a plan failing all three conditions must include a logged deferral rationale in its Context section. The planning agent self-enforces this check at PLAN-file write time.

8. **Modify `tests/test_session_preflight.py`** -- add new test classes:
   - `TestCiRcaHardBlock`: assert `print_ci_rca_recs([{"id": "rec-999", ...}])` output contains "HARD BLOCK"; assert `print_ci_rca_recs([])` output does not.
   - `TestNonAutomatableSoftcap`: assert `_check_non_automatable_softcap(249)` is False, `_check_non_automatable_softcap(251)` is True; assert the constant equals `250`.
   - `TestCiRcaLivenessAlert`: mock `subprocess.run` for the `gh` call to return a failed run from 45 min ago; mock `_fetch_ci_rca_recs_since` to return `[]`; assert alert dict is set. Second test: mock the same `gh` returns but `_fetch_ci_rca_recs_since` returns `[{"id": "rec-1"}]`; assert alert is None. Third test: mock `gh` to return a success conclusion; assert alert is None.
   - `TestForwardFixRecursion`: mock `_run_athena_query` to return three rows for the same file; assert alert dict is set with `count=3`. Second test: mock to return two rows; assert alert is None.

9. **Modify `tests/test_ops_data_portal.py`** -- add new test class `TestCiRcaSourceFileGate`:
   - `test_rejects_empty_file`: call `file_rec({"source": "ci_rca", "file": "", ...minimal_other_fields})` and assert `ValueError` is raised with `source_file` in `str(exc)`.
   - `test_rejects_missing_file_key`: call `file_rec({"source": "ci_rca", ...minimal_other_fields})` (no `file` key); assert `ValueError`.
   - `test_accepts_populated_file`: call `file_rec({"source": "ci_rca", "file": "scripts/foo.py", ...minimal_other_fields})` with `_next_id` mocked to raise `RuntimeError` (forcing the pending-outbox path); assert the call returns a `pending-` string and does not raise.

10. **Execute Verification Plan** -- run each step. Loop until pass. If V3 fails unrecoverably, stop and analyze root cause (Decision 55).

11. **Report** -- what was implemented, verification results, any deviations from this plan, and a one-line confirmation that the SKILL.md changes can now be cited from `validate-fast-tier-reshape` and `ci-workflow-restructure`.

## Known Gaps
- **No L7 closer.** Design B chosen; INTENT Section 4 step 6 and Section 2.5 row L7 require amendment to match. Amendment is out of scope here; recorded in this plan's Context section. A follow-on Decision Record may ratify the amendment after this plan and the next two land.
- **Auto-merge re-firing on green main.** Out of scope per INTENT Section 2.5. Owned by `ci-workflow-restructure`. Until that lands, paused PRs may require manual re-trigger.
- **Soft-cap revisit when Decision 67 reverses.** When the executor returns to service, the non-automatable surfacing rule needs revisiting per INTENT Section 5. The 250 cap is a forcing function for that conversation. No automatic enforcement; informational only.
- **Planning skill self-enforcement.** The Related-Work Check is an agent-level rule, not a hook or validate.py gate. A future hardening could add a `validate.py` static check on PLAN file content, but that is `validate-fast-tier-reshape` territory.
- **`gh` CLI dependency at preflight.** Adding `gh run list` to preflight is a new external call; failure modes (rate limit, auth) must degrade gracefully (return None from the liveness builder, log warning).
