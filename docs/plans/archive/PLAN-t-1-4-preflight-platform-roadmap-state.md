# Plan

## Intent
Wire `platform_roadmap` state into `logs/.preflight-report.json` so future `/plan` sessions discover what is eligible, in-progress, blocked, and strategic-pending without manually walking `docs/ROADMAP-PLATFORM.yaml`. This is the substrate that lets the planning skill (T-1.2) and the `/plan` slash command (T-1.3) surface roadmap state to the agent at intent clarification, retiring the manual archaeology that prompted this very session.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/t-1-4-preflight-platform-roadmap-state

## Phase
Platform roadmap tier T-1 (foundational tooling + ratification layer). Tier item id: **T-1.4 — Add `_platform_roadmap_state` computation to session_preflight**. Eligible per the Bootstrap clause and per `depends_on: [T-1.0]` being complete.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/platform_roadmap.py` | Modify | Extend `PlatformRoadmapState` with `in_progress_items()`, `strategic_pending_items()`, `active_tier()`, and a `to_preflight_dict()` shim that returns the JSON-serialisable dict consumed by session_preflight. Keep all dependency-graph logic in this module so session_preflight stays a thin caller. |
| `scripts/session_preflight.py` | Modify | Load the roadmap YAML via `platform_roadmap.load()`, instantiate `PlatformRoadmapState`, call `to_preflight_dict()`, and emit the result under the new top-level `platform_roadmap` key of the preflight report. Add stale-cache detection: compare YAML mtime against the most-recently-ratified ops_decisions timestamp; surface a "roadmap edits awaiting ratification" note in the dict when YAML is newer. |
| `tests/test_platform_roadmap_state.py` | Create | Fixture-YAML unit tests for the new state methods: eligibility resolution, blocked detection, strategic_pending isolation, tier-name shortcut handling (e.g. `depends_on: [T0]`), and stale-cache marker. |
| `tests/test_session_preflight_platform_roadmap.py` | Create | Integration test that runs the preflight on the real roadmap and asserts the new `platform_roadmap` key has the expected shape and surfaces a plausible eligibility set. |

## Bundled Recommendations
None. The user explicitly chose to keep the plan focused on the T-1.4 exit criteria.

## Infrastructure Dependencies
None. No `.tf` files in scope; no Lambda-packaged files in scope.

## Acceptance Criteria
- [ ] `logs/.preflight-report.json` contains a top-level `platform_roadmap` key whose value is an object with keys: `next_eligible[]`, `in_progress[]`, `blocked[]`, `strategic_pending[]`, `active_tier`.
- [ ] Each entry in `next_eligible[]`, `in_progress[]`, `blocked[]`, and `strategic_pending[]` is an object with at minimum `id`, `tier`, `name`, `effort`, `strategic` fields. `blocked[]` entries additionally include `blocked_on: [<dep-ids>]` listing the unsatisfied deps.
- [ ] `active_tier` resolves to the first (lowest, in canonical tier order T-1 < T0 < T1 < ... < T5) tier whose items are not all `status == complete` or `reserved`. If all tier items are complete, `active_tier` is `null`.
- [ ] Tier-name shortcuts in `depends_on` (e.g. `[T-1]`, `[T0]`) are resolved per `agent_instructions` semantics: a shortcut dep is satisfied iff `tier_complete(tier_name)` returns true for that tier.
- [ ] Stale-cache marker: when the mtime of `docs/ROADMAP-PLATFORM.yaml` is strictly newer than the most-recently-ratified `ops_decisions` timestamp (queried via the existing Athena helpers), the state dict includes a `stale_cache_note` string of the form `"roadmap edits awaiting ratification: YAML mtime <ts> newer than latest decision <ts>"`. When Athena is unreachable (SSO expired or empty result), the note is omitted (non-blocking, do not throw).
- [ ] When the YAML cannot be loaded (parse error, missing file), the preflight does not crash; the `platform_roadmap` key contains an `error` string describing the cause and the other keys are empty lists.
- [ ] No regression: `bin/venv-python -m scripts.validate --pre` still passes, including the `RoadmapDocument` schema check landed by T-1.5.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Unit: `eligible_items` returns the correct id set against a fixture roadmap (T-1 items only, deps satisfied/unsatisfied mixed) | `bin/venv-python -m pytest tests/test_platform_roadmap_state.py::test_eligible_items -xvs` | pytest passes; assertion compares to a known set | Eligibility logic must filter `status == not_started` AND `all(dep satisfied)`. Re-check `_dep_satisfied` against the actual `depends_on` field values. |
| 2 | pre-deploy | Unit: `compute_blocked` returns items with unsatisfied deps and surfaces the `blocked_on` list | `bin/venv-python -m pytest tests/test_platform_roadmap_state.py::test_compute_blocked -xvs` | pytest passes; `blocked_on` includes the specific unsatisfied dep ids | If `blocked_on` is missing or has wrong contents, fix the projection inside `compute_blocked()` to enumerate unsatisfied deps explicitly. |
| 3 | pre-deploy | Unit: `strategic_pending_items` isolates eligible items whose `strategic: true` flag is set | `bin/venv-python -m pytest tests/test_platform_roadmap_state.py::test_strategic_pending -xvs` | pytest passes; strategic-tagged eligibles surface in this list and are absent from `next_eligible` | Verify the implementation partitions eligibles by `item.strategic` and does not double-count. |
| 4 | pre-deploy | Unit: tier-name shortcut `depends_on: [T0]` resolves correctly when all T0 items are complete | `bin/venv-python -m pytest tests/test_platform_roadmap_state.py::test_tier_shortcut_resolution -xvs` | pytest passes; the dependent item moves from blocked to eligible when the last T0 item flips to complete in the fixture | Re-check `_dep_satisfied` shortcut branch and `_TIER_SHORTCUT_RE`. |
| 5 | pre-deploy | Unit: stale-cache note fires when YAML mtime > latest decision ts; absent when older; absent when Athena helper returns None | `bin/venv-python -m pytest tests/test_platform_roadmap_state.py::test_stale_cache_note -xvs` | pytest passes for three branches (newer / older / no-decision) | Inspect the stale-cache implementation; the no-decision branch must not raise. |
| 6 | pre-deploy | E2E: preflight writes the new key with the documented shape | `bin/venv-python -m scripts.session_preflight && bin/venv-python -c "import json,sys; d=json.load(open('logs/.preflight-report.json')); pr=d['platform_roadmap']; required=['next_eligible','in_progress','blocked','strategic_pending','active_tier']; missing=[k for k in required if k not in pr]; assert not missing, f'missing keys: {missing}'; print('ok')"` | prints `ok` | If keys are missing, confirm the wiring path in session_preflight calls `to_preflight_dict()` and merges the result into the report dict. |
| 7 | pre-deploy | E2E: live roadmap surfaces a plausible eligibility set (T-1.4 sibling tier items still eligible since we have not flipped T-1.4 to complete yet) | `bin/venv-python -m scripts.session_preflight && bin/venv-python -c "import json; d=json.load(open('logs/.preflight-report.json')); ids={x['id'] for x in d['platform_roadmap']['next_eligible']}; expected_subset={'T-1.4','T-1.7','T0.13','T0.14','T0.2'}; assert ids & expected_subset, f'expected at least one of {expected_subset}; got {ids}'; print('ok')"` | prints `ok`. Confirms the wiring reads the real roadmap and is not stuck on the fixture | If the live set is empty or wrong, the state computation is mis-reading the live YAML — diff fixture vs live to isolate. |
| 8 | pre-deploy | E2E: `active_tier` resolves to a tier with at least one not_started or in_progress item | `bin/venv-python -m scripts.session_preflight && bin/venv-python -c "import json; d=json.load(open('logs/.preflight-report.json')); at=d['platform_roadmap']['active_tier']; assert at in {'T-1','T0','T1','T2','T3','T4','T5'}, f'unexpected active_tier: {at}'; print('ok')"` | prints `ok`. With the current roadmap state, `active_tier` should be `T-1` or `T0` | If `null` is returned, the all-complete predicate is wrong. If a later tier is returned, the canonical-order traversal is wrong. |
| 9 | pre-deploy | E2E: malformed-YAML branch does not crash preflight (uses `${TMPDIR:-/tmp}` for portability across Linux dev container and any host where `/tmp` is restricted) | `BAK="${TMPDIR:-/tmp}/roadmap.bak" && cp docs/ROADMAP-PLATFORM.yaml "$BAK" && bin/venv-python -c "open('docs/ROADMAP-PLATFORM.yaml','a').write('\\n   bad_top_level: : :\\n')" && bin/venv-python -m scripts.session_preflight 2>&1 | tail -5; cp "$BAK" docs/ROADMAP-PLATFORM.yaml; bin/venv-python -c "import json; d=json.load(open('logs/.preflight-report.json')); pr=d['platform_roadmap']; assert 'error' in pr, pr; print('ok')"` | prints `ok` after restoring the roadmap; preflight exits with its normal exit code during the corrupt run and the report contains `error` instead of a crash trace | Wrap the load call in a try/except that captures the exception message into `platform_roadmap.error`. |
| 10 | pre-deploy | Regression (advisory): edit-loop presubmit including RoadmapDocument schema check still passes | `bin/venv-python -m scripts.validate --pre` | exit 0; T-1.5 schema check passes against the live YAML; ruff format clean | If the schema check fails, check whether new computations mutated the YAML; this plan must not write to the YAML. |
| 11 | pre-deploy | Regression (authoritative locally): full presubmit (no flags) — Decision 68 makes this the local-mirror of CI; catches pytest collection regressions and DQ checks that `--pre` skips | `bin/venv-python -m scripts.validate` | exit 0 | If only `--pre` passes but the full presubmit fails, the failure is in pytest collection, DQ checks, or another non-fast-tier check. Diagnose from the failing check name; do not skip. |

## Constraints
- Decision 55: no rescue agents or workaround-loop patches. If a verification step fails unrecoverably, stop and root-cause; do not invent a retry.
- Decision 67: Lambda dispatcher is disabled. This plan touches **no** Lambda-packaged files (`config/`, `scripts/llm_client.py`, `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`), so no `DEFERRED:` execution step is required.
- Decision 68: CI on the self-hosted runner is the authoritative pre-merge gate. `--pre` here is advisory.
- Bootstrap clause: T-1 items are eligible to START even with CD.1/CD.13 in `state: pending`. This plan exercises that clause.
- No emojis in code, scripts, or comments. ASCII hyphens only.
- Python 3.12+, type hints required for new functions in `platform_roadmap.py`. Ruff line length 127.
- Single Portal Invariant: this plan does NOT write to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly; the only write target is `logs/.preflight-report.json` via the existing preflight writer.

## Context
- T-1.5 (RoadmapDocument Pydantic schema) was completed on 2026-05-19. `scripts/platform_roadmap.PlatformRoadmapState` already provides `tier_complete()`, `resolve_depends_on()`, `_dep_satisfied()`, `eligible_items()`, and `compute_blocked()`. T-1.4 is a thin extension over that scaffold plus the wire-up into `session_preflight.py`.
- T-1.4's named downstream consumers are T-1.2 (planning skill reads `preflight.platform_roadmap`) and T-1.3 (`/plan` slash command surfaces it). Both are XS effort and will land after this plan, in their own /plan sessions.
- `session_preflight.py` already produces a `context.roadmap_phase` string from `docs/ROADMAP-PRODUCT.md`. That stays — `platform_roadmap` is its sibling, not a replacement (the platform and product roadmaps are sibling documents per the `rebuild_vs_refactor` section of ROADMAP-PLATFORM.yaml).
- Stale-cache implementation note: the existing preflight has Athena helpers (`_run_athena_query`, `_athena_run_query`); the SSO-expired path returns `None` cleanly. The stale-cache check must follow the same convention (None means "skip the check, do not raise").
- Round-2 architect note on T-1.4: the exit criteria mention "stale-cache detection" but do not specify the Athena dependency. We interpret it the only sensible way: when Athena is unreachable, the note is omitted, never fabricated.
- Cross-platform: pure Python; YAML loading uses `yaml.safe_load`; pytest fixtures inline-write YAML strings rather than relying on path-specific shell commands. The VP step 9 corrupt-YAML test uses Bash-portable commands (`cp`, no PowerShell-specific syntax).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (statusline / `git branch --show-current`)
- [ ] `docs/PROJECT_CONTEXT.md` read for ambient project state
- [ ] `docs/DECISIONS.md` cross-checked for any open decision affecting `session_preflight.py`, `platform_roadmap.py`, or `validate.py`
- [ ] All files in Scope table located and readable
- [ ] Acceptance criteria understood and verifiable
- [ ] `bin/venv-python` resolves to the project venv (run `bin/venv-python -c "import sys; print(sys.executable)"`)

## Ordered Execution Steps
1. **Extend `scripts/platform_roadmap.py`** — add the missing instance methods on `PlatformRoadmapState`:
   - `in_progress_items(self) -> list[TierItem]` — items with `status == "in_progress"`.
   - `strategic_pending_items(self) -> list[TierItem]` — items in `eligible_items()` whose `strategic` flag is true. These do NOT appear in `next_eligible` (which only contains non-strategic eligibles).
   - `active_tier(self) -> str | None` — first tier in canonical order `["T-1","T0","T1","T2","T3","T4","T5"]` whose items are not all complete-or-reserved. Returns `None` if every tier item is complete or reserved.
   - `_blocked_on(self, item: TierItem) -> list[str]` — internal helper returning the unsatisfied dep ids for an item (used by the dict projection).
2. **Add the `to_preflight_dict()` shim on `PlatformRoadmapState`** that returns:
   ```python
   {
       "next_eligible": [_item_dict(i) for i in self.eligible_items() if not i.strategic],
       "in_progress": [_item_dict(i) for i in self.in_progress_items()],
       "blocked": [{**_item_dict(i), "blocked_on": self._blocked_on(i)} for i in self.compute_blocked()],
       "strategic_pending": [_item_dict(i) for i in self.strategic_pending_items()],
       "active_tier": self.active_tier(),
   }
   ```
   `_item_dict(item)` returns `{"id": item.id, "tier": item.tier, "name": item.name, "effort": item.effort, "strategic": item.strategic}`.
3. **Add a module-level `compute_state_dict(yaml_path: Path, *, latest_decision_ts: str | None = None) -> dict`** in `platform_roadmap.py`. This is the single entry point session_preflight calls. Behaviour:
   - On parse error or missing file: return `{"error": str(exc), "next_eligible": [], "in_progress": [], "blocked": [], "strategic_pending": [], "active_tier": None}`.
   - On success: return `state.to_preflight_dict()` augmented with `stale_cache_note` if YAML mtime > `latest_decision_ts` (when the timestamp is non-None).
4. **Wire into `scripts/session_preflight.py`** — inside the existing `main()` after `read_context_files()` runs, call `platform_roadmap.compute_state_dict(ROADMAP_PLATFORM_PATH, latest_decision_ts=_get_latest_decision_ts())` and set `report["platform_roadmap"] = result`. Add the `ROADMAP_PLATFORM_PATH` constant at the top of the module alongside the existing roadmap-related constants. The Athena lookup helper `_get_latest_decision_ts()` returns `None` on any failure (catches the same exceptions as the existing Athena helpers). The exact SQL the helper runs is pinned: `SELECT max(last_updated_timestamp) FROM ops_decisions_current` — `ops_decisions_current` is the SCD2 _current view, and `last_updated_timestamp` is the column the table's row-update semantics already use (consistent with the warehouse invariant that `_current` rows reflect the latest ratified state, per AGENTS.md). If the result is empty or null-scalar, return `None`. This removes the column-choice ambiguity that the plan-critique gate flagged.
5. **Create `tests/test_platform_roadmap_state.py`** covering exit criteria via fixture YAML strings:
   - `test_eligible_items`: fixture with one item depending on a completed item and one depending on an incomplete item; assert only the satisfiable one is eligible.
   - `test_compute_blocked`: same fixture; assert `compute_blocked` returns the unsatisfiable item with the correct `blocked_on`.
   - `test_strategic_pending`: fixture with a `strategic: true` eligible item; assert it appears in `strategic_pending` and NOT in `next_eligible` (post-`to_preflight_dict()` view).
   - `test_tier_shortcut_resolution`: fixture where item `X.1` has `depends_on: [Y]` with Y being a tier name; assert blocked when not all Y items complete, eligible when all Y items complete.
   - `test_stale_cache_note`: three sub-cases. (a) YAML mtime newer than `latest_decision_ts` → note present. (b) older → note absent. (c) `latest_decision_ts` is None → note absent and no exception.
   - `test_active_tier`: fixture with T-1 partially complete and T0 untouched; assert `active_tier == "T-1"`. Second fixture with everything complete; assert `active_tier is None`.
6. **Create `tests/test_session_preflight_platform_roadmap.py`** — one integration test that imports and calls `compute_state_dict` against the live `docs/ROADMAP-PLATFORM.yaml` and asserts the dict has the required keys and a non-empty `next_eligible` (sanity).
7. **Run the Verification Plan** — execute every step in order. Loop until pass. If any V2 step fails unrecoverably, stop and root-cause per Decision 55.
8. **Run the local regression gate** in this order: `bin/venv-python -m scripts.validate --pre` for the fast edit-loop check, then `bin/venv-python -m scripts.validate` (no flag) for the full presubmit. Per Decision 68 the self-hosted CI runner is the authoritative pre-merge gate; both local steps are about reducing CI round-trips. Then push the branch.
9. **Report** what was implemented, all VP step outcomes, and the final preflight report excerpt showing the new `platform_roadmap` key.
