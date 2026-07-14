# Plan

## Intent
Land the keystone governance check for the platform roadmap: a Pydantic `RoadmapDocument` schema that CI enforces against `docs/ROADMAP-PLATFORM.yaml`, so structural drift (dangling `depends_on`, duplicate ids, cycles, unknown gate-rule helpers, invalid `filed_via` unions) fails the build instead of silently degrading the harness. Unblocks T-1.1 (CD ratification) per the architect HIGH-3 "validate before ratify" ordering and lays the dependency-graph helpers that T-1.4 (preflight) and T-1.2 (planning skill) will consume.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/t-1-5-roadmap-document-schema

## Phase
Platform tier T-1 (Governance ratification + harness integration). Specifically tier_item **T-1.5**.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/platform_roadmap.py` | Create | Pydantic `RoadmapDocument` model + `load(path) -> RoadmapDocument` + `PlatformRoadmapState` helper (`eligible_items`, `resolve_depends_on`, `compute_blocked`) for T-1.4 reuse. Includes gate-rule grammar parser (helper-name + arity + field-path validation; NO evaluation). |
| `tests/test_platform_roadmap.py` | Create | V2 unit tests covering every T-1.5 exit criterion: malformed YAML rejection, dangling depends_on, duplicate ids, cycle detection, gate-rule grammar (unknown helper, arity mismatch, malformed item-field path), `filed_via` union validation, tier-name shortcut resolution in depends_on, dependency-graph helper semantics. |
| `scripts/validate.py` | Modify | Add `validate_platform_roadmap(failed: list[str]) -> None` calling into `scripts.platform_roadmap.load`; register call in `run_python_checks()` (full presubmit, not `--pre`). |
| `.claude/commands/implement.md` | Modify (already committed `fdb790d`) | Switch Step 5 code-review trigger from `run_skill.py` to `Agent` tool with `subagent_type=code-review`. Scope-creep per user direction; benefits this branch's `/implement` run. |
| `.claude/skills/implement/SKILL.md` | Modify (already committed `fdb790d`) | Mirror the Step 5 dispatch instruction in the skill's "Code Review Protocol" section + agent prompt template. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify (housekeeping, post-VP) | Mark T-1.5 `status: complete`, `completed_at: "<merge-date>"`. |
| `docs/SESSION_LOG.md` | Modify (housekeeping, post-VP) | Append session entry per repo convention. |

## Bundled Recommendations
None. No open rec in `logs/.recommendations-log.jsonl` aligns with T-1.5 schema-validation scope (verified via preflight rec-curator top-5; closest is rec-429 "SLOC/complexity hard gates in validate.py" which is a sibling but disjoint validator).

## Infrastructure Dependencies
No `.tf` files in scope. **`docs/ROADMAP-PLATFORM.yaml` IS Lambda-packaged** (`scripts/build_lambda.py:96-99` copies both roadmap files into `/var/task/docs/` for scheduled agents to read at runtime). The housekeeping flip to `status: complete` for T-1.5 modifies a Lambda-packaged file. Per CLAUDE.md "Temporary Operational Constraints" (Decision 67), this plan therefore includes a DEFERRED deployment step in lieu of active `build_lambda.py --deploy + smoke-test`. The dispatcher itself is currently disabled, so the deferral is procedurally required but operationally inert until Decision 67 reverses.

`validate.py` is a build-time CI script — no deployment surface for `scripts/platform_roadmap.py` or `scripts/validate.py` themselves.

## Acceptance Criteria
- [ ] `scripts/platform_roadmap.py` exposes `RoadmapDocument` Pydantic model and `load(path)` returning a validated instance against `docs/ROADMAP-PLATFORM.yaml`.
- [ ] `scripts/platform_roadmap.py` exposes a `PlatformRoadmapState` helper class with `eligible_items() -> list[TierItem]`, `resolve_depends_on(item_id) -> list[TierItem]`, and `compute_blocked() -> list[TierItem]` methods. Tier-name shortcuts (e.g. `T0` meaning "all items with `tier == 'T0'`") resolved per `agent_instructions` semantics.
- [ ] `scripts/validate.py` includes `validate_platform_roadmap(failed)` registered in `run_python_checks()`; full presubmit (`bin/venv-python -m scripts.validate`) fails when the YAML is structurally malformed.
- [ ] `tests/test_platform_roadmap.py` covers all T-1.5 exit criteria via pytest fixtures: malformed YAML rejection, dangling depends_on, duplicate ids, cycle detection, gate-rule grammar (unknown helper, arity mismatch), `filed_via` union validation, gate_helpers mini-grammar (item lookups + the four documented helpers).
- [ ] Gate-rule schema rejects unknown helper function names; arity mismatch fails schema validation. Field-path resolution NOT statically checked (runtime concern per document `gate_helpers.item_field_eq.semantics`).
- [ ] All edits to `.claude/commands/implement.md` and `.claude/skills/implement/SKILL.md` already landed in commit `fdb790d` on this branch.
- [ ] `docs/ROADMAP-PLATFORM.yaml` T-1.5 entry shows `status: complete` after merge.
- [ ] `docs/SESSION_LOG.md` has a new entry summarising this work.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Module imports cleanly and validates live YAML | `bin/venv-python -c "from scripts.platform_roadmap import load; doc = load('docs/ROADMAP-PLATFORM.yaml'); print(f'OK: {len(doc.tier_items)} items, {len(doc.candidate_decisions)} CDs')"` | Prints `OK: <N> items, <M> CDs` with no traceback; N >= 30, M >= 20 | Pydantic validation error — fix the model or fix the YAML if it has a genuine defect |
| 2 | [pre-deploy] | Pytest covers each exit criterion | `bin/venv-python -m pytest tests/test_platform_roadmap.py -v` | All test cases pass; output shows distinct cases for malformed-YAML / dangling-depends-on / duplicate-ids / cycle / unknown-helper / arity-mismatch / filed_via-union / tier-shortcut-resolution | Read pytest output, fix code or test as appropriate; max 3 fix attempts per test |
| 3 | [pre-deploy] | Coverage of new module hits 100% | `bin/venv-python -m pytest tests/test_platform_roadmap.py --cov=scripts.platform_roadmap --cov-report=term-missing` | Coverage report shows 100% for `scripts/platform_roadmap.py` (per `test_coverage_checker` policy for new code) | Add missing test cases for uncovered branches |
| 4 | [pre-deploy] | Negative integration: inject a malformed YAML fixture and confirm `validate.py` fails | `bin/venv-python -c "import tempfile, pathlib, shutil, subprocess, sys; tmp=tempfile.mkdtemp(); pathlib.Path(tmp,'docs').mkdir(); shutil.copy('docs/ROADMAP-PLATFORM.yaml', f'{tmp}/docs/ROADMAP-PLATFORM.yaml'); content=pathlib.Path(f'{tmp}/docs/ROADMAP-PLATFORM.yaml').read_text(); pathlib.Path(f'{tmp}/docs/ROADMAP-PLATFORM.yaml').write_text(content.replace('T-1.0', 'T-1.0\\n  - id: T-1.0', 1)); from scripts.platform_roadmap import load; sys.exit(0 if load(f'{tmp}/docs/ROADMAP-PLATFORM.yaml') is None else 1)" 2>&1 \| grep -q "duplicate" && echo PASS \|\| echo FAIL` | Output `PASS` (duplicate-id error raised) | If FAIL: the duplicate-id detector is not firing. Inspect Pydantic model validators. |
| 5 | [pre-deploy] | Full presubmit passes with the new validator wired in | `bin/venv-python -m scripts.validate` | Exit code 0; "platform roadmap" check appears in the output with PASS | Read failure output, fix in priority order (this validator first, then any others) |
| 6 | [post-deploy] **DEFERRED** | Lambda deploy + smoke-test for ROADMAP-PLATFORM.yaml packaging | `DEFERRED: bin/venv-python -m scripts.build_lambda --deploy && bin/venv-python -m scripts.run_scheduled_agent --smoke-test rec-curator` (pending Decision 67 reversal) | When Decision 67 reverses: deployed Lambda finds the updated ROADMAP-PLATFORM.yaml at `/var/task/docs/ROADMAP-PLATFORM.yaml` with T-1.5 marked complete; rec-curator smoke-test exits 0 | If/when this becomes active: investigate `build_lambda.py` packaging output, ensure roadmap file is in the zip |

## Constraints
- No emojis in code, scripts, or documentation; ASCII hyphens only (per `CLAUDE.md`).
- Python 3.12+, type hints required, async for I/O (this work is sync — no I/O constraint relevant).
- Pydantic v2 syntax (`model_validator`, `field_validator`, `Annotated`) — v1 syntax is deprecated.
- No `eval()`/`exec()` anywhere in the gate-rule parser. The parser tokenises the expression and pattern-matches helper names + arity — it never executes.
- No rescue agents or workaround loops (Decision 55). If a verification step fails three times, STOP and surface to human.
- New module must use `bin/venv-python` invocations only — no PowerShell, no hardcoded `.venv/Scripts/python.exe`.
- Test isolation: never spawn `pytest tests/` (full suite) from inside a test (recursion risk per `CLAUDE.md` "Test Isolation Patterns").
- `validate_platform_roadmap` registers in `run_python_checks()` (full presubmit), NOT in `--pre` (edit-loop). YAML edits are rare and parsing is fast; aligning with `validate_invariants`, `check_source_registry`, and the other YAML-structure validators.

## Context
- **Why T-1.5 specifically:** T-1.1 (the CD ratification item) has `depends_on: [T0.7b, T-1.5]`. T0.7b is M-effort and gated by T0.12 + T0.13; T-1.5 is the cheapest unblocker. Architect HIGH-3 finding made the "validate before ratify" ordering explicit.
- **Why a state helper class (`PlatformRoadmapState`):** T-1.4 needs to compute `next_eligible`, `in_progress`, `blocked`, `strategic_pending` for the preflight JSON. Putting the dependency-graph semantics behind a single class in this module gives T-1.4 a thin shim instead of re-implementing the same graph traversal. Identified during scoping as a 30-LOC addition that prevents drift between T-1.5 and T-1.4 semantics.
- **Gate-rule parsing, not evaluation:** Per the YAML's own `gate_helpers.item_field_eq.semantics` field: "The validator does not statically check field_path resolution -- that is a runtime concern handled by T-1.4's preflight computation." T-1.5 validates that gate-rule strings parse to known helpers with correct arity and well-formed item-field paths (`T<N>.<field>[.<field>]*`); it does NOT resolve the field paths against current state. Evaluation is T-1.4.
- **`filed_via` union validation:** Document-level field is a union: `"pending_log_decision_lambda"` (pre-ratification) OR `"ops_decisions:dec-NNN"` (post-ratification). Schema enforces the union literal; rejects malformed forms.
- **Bootstrap clause is data, not validation logic:** The bootstrap exemption in `agent_instructions` lets T-1 and substrate-T0 items reach `status: complete` with their gating CDs still `state: pending`. This is a semantic rule for *consumers* (e.g. T-1.1 ratification logic) -- T-1.5 does NOT enforce it. T-1.5 only enforces structural conformance + dependency-graph hygiene.
- **Pydantic + PyYAML already in `requirements.txt`** (lines 4, 38) -- no dependency additions required.
- **Coexistence with `RoadmapDocument` versioning:** `document.version: 1` is in the YAML; the Pydantic model should reject unknown major versions to prevent silent drift if a v2 doc is introduced without a schema migration.
- **Scope-creep (implement-skill edits):** Already committed as `fdb790d`. Plan acknowledges this explicitly so the plan-critique gate can audit the choice rather than discover it. Rationale captured in commit message.
- **Windows-worktree conflict surface:** User has uncommitted `/bin` setup-script work that may influence `scripts/session_preflight.py` and agent files. T-1.5 touches `scripts/validate.py` only (new function + 1 registration line, no overlap with preflight). Merge-clean expected.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (`agent/t-1-5-roadmap-document-schema`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable (3 modify + 2 create + 2 housekeeping = 7 paths)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Create `scripts/platform_roadmap.py`** with:
   - `RoadmapDocument` Pydantic model mirroring the YAML top-level structure: `document` (with `version`, `status`, `filed_via` union), `north_star`, `cost_projection`, `rebuild_vs_refactor`, `foundation_already_shipped`, `candidate_decisions`, `tier_items`, `cross_tier_gates`, `open_questions`, `known_gaps`, plus `agent_instructions` and `gate_helpers` (both used by validators below).
   - Nested `TierItem`, `CandidateDecision`, `CrossTierGate` Pydantic submodels.
   - `model_validator(mode='after')` cross-field checks: (a) `id` uniqueness across `tier_items`, (b) `depends_on` refs resolve to existing tier_item ids OR tier-name shortcuts, (c) dependency-graph cycle detection (DFS), (d) `gates` refs in `candidate_decisions` resolve to existing tier_item ids or tier-name shortcuts.
   - `GateRuleParser` class: tokenises a rule string, walks the AST shallowly, validates each helper call against the documented `gate_helpers` table (name + arity), validates item-field-path shape (`T<N>.<field>[.<field>]*`), rejects unknown helpers and arity mismatches. NO `eval()` -- pure string parsing.
   - `load(path: str | Path) -> RoadmapDocument` function: opens YAML, parses with PyYAML safe loader, instantiates the Pydantic model.
   - `PlatformRoadmapState(doc: RoadmapDocument)` helper class with `eligible_items()`, `resolve_depends_on(item_id)`, `compute_blocked()`, `tier_complete(tier_name)` methods. Tier-name shortcut resolution per `agent_instructions` semantics. ~30 LOC.
2. **Create `tests/test_platform_roadmap.py`** with one pytest class per concern:
   - `TestLoad`: valid YAML loads; missing file raises; non-YAML content raises.
   - `TestStructuralValidation`: malformed YAML (wrong type for `tier_items`) raises; missing required field raises.
   - `TestIdUniqueness`: fixture with duplicate `T-1.0` raises; passing case.
   - `TestDanglingDependsOn`: fixture with `depends_on: [T999.0]` (non-existent) raises.
   - `TestCycleDetection`: fixture with A->B->A cycle raises; A->B->C linear passes; tier-shortcut cycles (`T0` depending on `T1` which depends on `T0`) raise.
   - `TestGateRuleGrammar`: unknown helper (`bogus_helper(T1.1)`) raises; arity mismatch (`tier_complete()` -- arity 1 expected) raises; valid grammar passes for each of the four documented helpers.
   - `TestFiledViaUnion`: `pending_log_decision_lambda` accepted; `ops_decisions:dec-042` accepted; arbitrary string raises.
   - `TestPlatformRoadmapState`: `eligible_items()` returns items with all deps satisfied; `compute_blocked()` returns items with unmet deps; tier-name shortcut (`T0`) resolves correctly.
3. **Modify `scripts/validate.py`**:
   - Add `validate_platform_roadmap(failed: list[str]) -> None` near the other YAML-structure validators (alphabetically near `validate_prompt_compliance` or grouped near `check_source_registry`).
   - Function calls `scripts.platform_roadmap.load("docs/ROADMAP-PLATFORM.yaml")`; on `pydantic.ValidationError` or `yaml.YAMLError`, prints diagnostic and appends to `failed`.
   - Register the call in `run_python_checks()` after `check_source_registry(failed)` (grouped near other YAML validators).
   - Import `scripts.platform_roadmap` at module top, guarded by the same `sys.path` injection pattern as `validate_imports` if needed (likely not — direct relative import from `scripts/` to `scripts.platform_roadmap` works).
4. **Execute Verification Plan** -- run each step in order. Loop on FAIL with diagnosis. Stop at 3 attempts per step and report.
5. **Trigger code review (MANDATORY)** -- dispatch via `Agent` tool with `subagent_type=code-review` per the freshly-updated `.claude/commands/implement.md` Step 5 protocol. Provide branch + plan path. Fire-and-forget if backgroundable; otherwise await synchronously.
6. **In parallel with code review (latency-saving):** execute the housekeeping commits below while the code-review subagent runs. These are independent file paths and will not conflict with any code-review-driven fixes (which would land in `scripts/platform_roadmap.py`, `tests/test_platform_roadmap.py`, or `scripts/validate.py`).
   - **6a. Update `docs/ROADMAP-PLATFORM.yaml`** -- find the T-1.5 entry, change `status: not_started` to `status: complete`, add `completed_at: "YYYY-MM-DD"` (the merge date). Commit: `chore(t-1-5): mark T-1.5 complete in ROADMAP-PLATFORM.yaml`.
   - **6b. Update `docs/SESSION_LOG.md`** -- prepend (or append per repo convention; check existing entries) a new session entry following the same shape as recent entries (date, branch, summary, files modified, decisions, follow-ups). Commit: `chore(t-1-5): session log entry`.
   - **6c. DEFERRED: Lambda deployment step** -- `bin/venv-python -m scripts.build_lambda --deploy && bin/venv-python -m scripts.run_scheduled_agent --smoke-test rec-curator` is DEFERRED pending Decision 67 reversal. Reason: dispatcher is disabled; the modified `docs/ROADMAP-PLATFORM.yaml` is packaged into Lambda zips at `scripts/build_lambda.py:96-99` so Lambda runtime would otherwise see stale T-1.5 status, but no agent is currently dispatching. When Decision 67 reverses, this step becomes mandatory before subsequent plans that read T-1.5 status from the Lambda-side roadmap. Acknowledge in commit body of the PR; no action this branch.
7. **Synchronise with code review** -- when review returns: implement Critical/High inline (mandatory); file Medium/Low as recs via `bin/venv-python -m scripts.ops_data_portal --file-rec ...`. Re-run `bin/venv-python -m scripts.validate --pre` after any fixes.
8. **Final validation gate** -- `bin/venv-python -m scripts.validate --quick` (or `--pre`; the IMPLEMENTATION skill commit-flow Step 6 specifies `--quick`). Must exit 0.
9. **Commit, PR, merge** per the IMPLEMENTATION Commit Flow in `.claude/skills/implement/SKILL.md`. PR title: `feat(t-1-5): RoadmapDocument Pydantic schema + validate.py gate`. PR body summary references this PLAN file and the housekeeping commits.
10. **Capture friction** per Step 8 of the workflow; emit to `telemetry_process_events` via executor telemetry API. If RCA-triggering, invoke `executor-rca` skill per Decision 55.
11. **Report and close session** per Step 9 of the workflow: list files changed, VP outcomes, code-review findings fixed, recs filed, decisions made. Close telemetry session with `bin/venv-python -m scripts.session_postflight --close-session --outcome success`.
