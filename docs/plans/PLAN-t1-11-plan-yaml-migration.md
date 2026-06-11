# Plan

## Intent
Implement T1.11 / CD.22: migrate planning artefacts from `docs/plans/PLAN-*.md` to `docs/plans/PLAN-*.yaml`
with a Pydantic `PlanDocument` schema enforced by `validate.py`, and update the plan-consuming skills and
tooling to read PLAN-*.yaml with a deprecation warning on the .md path. This retires the last
narrative-markdown artefact class in the planning pipeline (CD.13 agent-first alignment) and gives every
future plan structural validation identical in kind to the RoadmapDocument gate (T-1.5).

NOTE: this file is intentionally the LAST PLAN-*.md authored in this repository. It is itself the only
in-flight plan at implementation time, and porting it to `PLAN-t1-11-plan-yaml-migration.yaml` is the
demonstration conversion required by the T1.11 exit criteria.

## Plan Type
IMPLEMENTATION

(Scope exceeds the 5-file heuristic; the STRATEGIC classification is suspended per the active executor
freeze -- AGENTS.md Temporary Operational Constraints / Decision 67 STRATEGIC clause -- so this is authored
as a single larger IMPLEMENTATION plan, as that constraint explicitly sanctions.)

## Verification Tier
V2

(Python source with no external integration: Pydantic schema + validate.py wiring + pure-file tooling.
Skill edits are V1 docs; highest tier wins -> V2. Decision-scout grounding: no scope file appears in any
`src/lambdas/*/manifest.yaml`, so no per-Lambda build/deploy/smoke-test steps apply (Decision 79). No .tf
files in scope, so no Infrastructure Assessment.)

## Plan Path
docs/plans/PLAN-t1-11-plan-yaml-migration.md

## Phase
Platform tier item **T1.11** ("PLAN-*.md to PLAN-*.yaml migration with Pydantic schema", effort M,
`next_eligible` per preflight 2026-06-11). Gated by candidate decision **CD.22** (state: pending);
related: **CD.13**. depends_on [T-1.2, T-1.5] both complete (eligibility confirmed by preflight).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/plan_document.py` | Create | Pydantic `PlanDocument` model + `load(path)` + CLI (PASS/FAIL per file, exit 1 on failure). Mirrors `scripts/platform_roadmap.py` (T-1.5 pattern). Registry-friendly self-contained check function per Decision 80 direction. |
| `scripts/validate.py` | Modify | Add `validate_plan_documents(failed, plans_dir=None)`: validate every `docs/plans/PLAN-*.yaml` against `PlanDocument`. Wire into full presubmit tier AND `--pre` tier (pure-Python, no AWS, sub-second -- fits the Decision 60 `--pre` budget; mirrors `validate_product_roadmap` placement). |
| `tests/test_plan_document.py` | Create | Schema unit tests: valid document passes; malformed fixtures fail (bad enum, missing VP command, duplicate VP step ids, empty scope, extra/unknown key, work_areas on non-STRATEGIC, slug/plan_path mismatch). Includes a test that `validate_plan_documents` FAILS on a malformed PLAN-*.yaml via the `plans_dir` override (tmp dir) -- the malformed fixture never lives in `docs/plans/`. |
| `scripts/find_plan.py` | Modify | Resolve `PLAN-{slug}.yaml` first; fall back to `PLAN-{slug}.md` (and legacy `PLAN.md`) with a logged deprecation warning. Explicit-path resolution unchanged (caller's path wins), but resolving an explicit .md path logs the same deprecation warning. |
| `scripts/plan_audit.py` | Modify | Parse Scope from YAML plans (`scope[].file` / `scope[].action`); retain markdown Scope-table parsing as the deprecated fallback with a logged warning. |
| `tests/test_find_plan.py` | Modify | Cover .yaml-first resolution, .md fallback + deprecation warning. |
| `tests/test_plan_audit.py` | Modify | Cover YAML scope parsing + markdown fallback warning. |
| `.claude/skills/planning/SKILL.md` | Modify | Replace the `PLAN-{slug}.md Template` section with a `PLAN-{slug}.yaml Template` (YAML example mirroring the schema, field semantics as comments per Decision 66 precision-context-injection); switch authored-artefact references to .yaml; add deprecation note for the .md path (one release cycle). |
| `.claude/skills/implement/SKILL.md` | Modify | Read PLAN-*.yaml; on being handed a PLAN-*.md path, emit a deprecation warning and proceed (one release cycle). Preserve all gates/flows otherwise. |
| `.claude/skills/plan-critique/SKILL.md` | Modify | Critique PLAN-*.yaml structure (sections map to schema fields); .md path deprecated with warning. Preserve the Decision 75 Frame Challenge phase and the Step 12d STRATEGIC block untouched. |
| `.agents/skills/planning/SKILL.md` | Modify | Same as .claude counterpart. VOLUNTARY legacy hygiene: Decision 76 demoted `.agents/` to legacy with NO sync obligation (supersedes Decision 58's mirror rule); updated here only because the T1.11 roadmap entry and the user brief explicitly list these files. |
| `.agents/skills/implement/SKILL.md` | Modify | Same as .claude counterpart (voluntary legacy hygiene, per above). |
| `.agents/skills/plan-critique/SKILL.md` | Modify | Same as .claude counterpart (voluntary legacy hygiene, per above). |
| `docs/plans/PLAN-t1-11-plan-yaml-migration.yaml` | Create | The ported YAML form of THIS plan -- the in-flight conversion demonstrating the migration. Structure-only port: no content rewrites. |
| `docs/plans/PLAN-t1-11-plan-yaml-migration.md` | Delete | Removed in the same commit that lands the .yaml port (one-way, non-rolling migration per CD.22). All OTHER PLAN-*.md files are historical and remain untouched. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | T1.11 `status: complete` + `completed_at`; CD.22 `state: pending -> ratified` with ratification note. |
| `docs/DECISIONS.md` | Modify | Mint the Decision ratifying CD.22 (mirrors the Decision 79 ratify-in-implementing-PR precedent). Per decision-scout: the entry explicitly records an amendment to Decision 76 clause 3's artefact reference (`PLAN-{slug}.md` -> `PLAN-{slug}.yaml`), naming the find_plan.py deprecation fallback as the transition bridge until the commands follow-up rec lands. Decisions propagate to the warehouse via the DECISIONS.md ETL path (legitimate write path (b)); no direct warehouse write. |
| `docs/SESSION_LOG.md` | Modify | Session entry recording the migration, the in-flight enumeration, and verification results. |

## Bundled Recommendations
None. (Preflight 2026-06-11: open_recommendations=0, ci_rca_recs=[] -- recs_read_status was
`reader_unreachable` so the count derives from the synced local cache; Decision 73 L5 check recorded with
that caveat. No open ci-rca rec blocks scoping this work.)

Follow-up rec to FILE during implementation (out-of-scope surface, per "out-of-scope bugs become
recommendations"): `.claude/commands/plan.md` + `.claude/commands/implement.md` (and the Decision 76
clause-3 handoff text they embed) still reference `PLAN-{slug}.md`; reconcile to .yaml once this lands.
Portal call: `file_rec` (queues to outbox if the DuckLake writer is unreachable locally).

## Infrastructure Dependencies (if applicable)
None. No `.tf` files in scope; no Lambda-packaged files in scope (`config/agent/` not touched;
decision-scout verified no scope file is named in any Lambda manifest).

## In-flight plan enumeration (T1.11 exit criterion 3)
Audit method: the repo's public history begins at the initial commit (2026-05-28). Every PLAN-*.md present
in that initial commit is historical by definition (pre-dating the current pipeline; untouched since).
All 41 PLAN-*.md files added after the initial commit were cross-referenced against subsequent
implementation merges on main (`git log --grep={slug}` for feat/fix/docs implementation commits, plus
REPORT-ONLY deliverables landing in the authoring PR itself, plus roadmap tier status):
every one has its implementation landed, its REPORT-ONLY deliverable merged, or its remaining phases
superseded (PLAN-ducklake-churn-latency-rca: Phase 2 superseded by the Decision 82 EC8 frame correction,
T2.17 complete).

**In-flight set at implementation time (the complete conversion list):**
1. `docs/plans/PLAN-t1-11-plan-yaml-migration.md` (this plan) -> `docs/plans/PLAN-t1-11-plan-yaml-migration.yaml`

This matches CD.22's "typically 1-3" expectation. Historical PLAN-*.md files (all others) remain untouched
in the working tree and in commit history; none are retroactively converted.

## Acceptance Criteria
- [ ] `scripts/plan_document.py` defines `PlanDocument`; `bin/venv-python -m scripts.plan_document` validates every `docs/plans/PLAN-*.yaml` and exits 0.
- [ ] `validate.py` full presubmit AND `--pre` run the plan-document check; a malformed PLAN-*.yaml makes it FAIL (demonstrated via the `plans_dir`-override test in `tests/test_plan_document.py`, plus a live one-shot demonstration during implementation).
- [ ] The in-flight conversion list (exactly: this plan) is enumerated in this plan doc; the .yaml port exists; this .md is deleted in the same commit; no other PLAN-*.md is touched.
- [ ] All six SKILL.md files (planning/implement/plan-critique in `.claude/skills/` and `.agents/skills/`) read PLAN-*.yaml; the .md path is documented as deprecated (one release cycle) with a warning; `find_plan.py`/`plan_audit.py` emit the runtime deprecation warning on the .md fallback.
- [ ] `bin/venv-python -m scripts.validate --pre` passes on the branch.
- [ ] PR merged to main with pr-validate green (Decision 76 squash-merge flow).
- [ ] T1.11 `status: complete` in `docs/ROADMAP-PLATFORM.yaml`; CD.22 `state: ratified`; ratifying Decision minted in `docs/DECISIONS.md` (with the Decision 76 clause-3 amendment note); `scripts/platform_roadmap` still validates the roadmap.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Schema validates the ported plan | `bin/venv-python -m scripts.plan_document docs/plans/PLAN-t1-11-plan-yaml-migration.yaml` | `PASS` line, exit 0 | Schema/port mismatch: fix the port (structure only), not by loosening validators |
| 2 | pre-deploy | Schema validates ALL PLAN-*.yaml (goal criterion 1) | `bin/venv-python -m scripts.plan_document` | `PASS` for every docs/plans/PLAN-*.yaml, exit 0 | Any FAIL: fix that file or the loader bug |
| 3 | pre-deploy | Malformed plan fails validate.py (one-shot live demo) | `cp tests/fixtures/plan_documents/malformed_missing_command.yaml docs/plans/PLAN-zz-malformed-demo.yaml && bin/venv-python -m scripts.validate --pre; rc=$?; rm docs/plans/PLAN-zz-malformed-demo.yaml; test $rc -ne 0` | validate FAILs while the malformed file is present; exit 0 after cleanup test | Check did not fire: glob/wiring bug in `validate_plan_documents` |
| 4 | pre-deploy | Unit suite incl. malformed fixtures + plans_dir override | `bin/venv-python -m pytest tests/test_plan_document.py tests/test_find_plan.py tests/test_plan_audit.py -q` | all pass | Fix code, not tests, unless a test asserts the old .md-only behaviour |
| 5 | pre-deploy | find_plan resolves .yaml first, warns on .md fallback | `bin/venv-python scripts/find_plan.py docs/plans/PLAN-t1-11-plan-yaml-migration.yaml` | prints the .yaml path | NOT_FOUND: resolution order bug |
| 6 | pre-deploy | All six skills reference the YAML path + deprecation | `grep -l "PLAN-\*\.yaml\|PLAN-{slug}.yaml" .claude/skills/planning/SKILL.md .claude/skills/implement/SKILL.md .claude/skills/plan-critique/SKILL.md .agents/skills/planning/SKILL.md .agents/skills/implement/SKILL.md .agents/skills/plan-critique/SKILL.md \| wc -l` | `6` | A skill root was missed |
| 7 | pre-deploy | Deprecation language present in all six skills | `grep -lc "deprecat" .claude/skills/planning/SKILL.md .claude/skills/implement/SKILL.md .claude/skills/plan-critique/SKILL.md .agents/skills/planning/SKILL.md .agents/skills/implement/SKILL.md .agents/skills/plan-critique/SKILL.md \| wc -l` | `6` | Add the .md deprecation note where missing |
| 8 | pre-deploy | Roadmap still validates after T1.11/CD.22 edits | `bin/venv-python -m scripts.platform_roadmap` | `PASS: docs/ROADMAP-PLATFORM.yaml validates...` | Roadmap edit broke schema: fix the YAML edit |
| 9 | pre-deploy | Full --pre gate (goal criterion 6) | `bin/venv-python -m scripts.validate --pre` | exit 0 | Fix the reported check; no workarounds (Decision 55) |
| 10 | pre-deploy | Full presubmit parity before push | `bin/venv-python -m scripts.validate` | exit 0 (credential-dependent verifiers may SKIP in degraded mode) | RCA the failing check; CI remains authoritative |

## Constraints
- Structure-only migration: do NOT rewrite plan content while porting this plan to YAML.
- Only the files in Scope are modified. `.claude/commands/*.md` references to PLAN-{slug}.md are explicitly OUT of scope -> follow-up rec (see Bundled Recommendations).
- Historical PLAN-*.md files: untouched (no deletion, no conversion, no edits).
- Main-validate DQ red and the alerts_email pipeline are owned elsewhere -- out of scope.
- No `eval()`/`exec()`; type hints; ruff line length 127; no emojis; ASCII hyphens.
- Never edit/commit on `main` (work happens on `agent/t1-11-plan-yaml-migration`).
- No rescue agents or workaround loops (Decision 55). On CI failure, the ci-rca rec path owns triage.
- `validate.py` is the single source of truth for checks: the new check lands there; ci.yml is untouched.
- Decision 67 STRATEGIC clause: this plan is IMPLEMENTATION; the PlanDocument schema still encodes
  STRATEGIC in the `plan_type` enum (authoring is blocked at planning time, not schema time) and the
  plan-critique skill's STRATEGIC refusal is preserved verbatim.
- Decision 43: `scripts/plan_document.py` stays under the 500-SLOC / complexity gates.
- Windows-host caveat: this session runs on local Windows; all commands must also be Linux/bash compatible
  (`bin/venv-python` wrapper resolves per-platform).

## Context
- CD.22 detail (ROADMAP-PLATFORM.yaml): one-way, non-rolling migration; schema + port in-flight plans
  (typically 1-3) + update the three skills. Scope is planning-skill OUTPUT artefacts only -- CLAUDE.md,
  README.md, AGENTS.md and other narrative-md stay (CD.20/CD.23 human-portal carve-out).
- Decision flags from the decision-scout gate (2026-06-11), with resolutions adopted in this plan:
  - WARN Decision 76 vs `.agents/skills/` mirror premise -> retained as VOLUNTARY legacy hygiene with the
    supersession (of Decision 58) cited; no sync obligation claimed.
  - NOTE Decision 76 clause 3 names `PLAN-{slug}.md` -> the ratifying Decision records the clause-3
    artefact amendment (.md -> .yaml) and the deprecation bridge.
  - NOTE Decision 73 L5 ci-rca hard-block -> preflight showed `ci_rca_recs: []`; recorded with the
    degraded-reader caveat (recs_read_status=reader_unreachable; local cache source).
- Preflight 2026-06-11: branch fresh vs main (0/0), creds ok, DQ last run FAIL (out-of-scope, owned
  elsewhere), telemetry sessions-query WARN (Athena table missing -- pre-existing), ops outbox holds 6
  pending ops_recommendations entries (anomaly noted by sync_ops; not consumed by this plan).
- T-1.5 precedent: `scripts/platform_roadmap.py` RoadmapDocument + `validate_platform_roadmap` wiring;
  the product-roadmap check additionally runs in `--pre` -- this plan mirrors the product-roadmap placement.
- The `verification_plan[].command` requirement encodes the planning skill's "every VP step MUST include a
  Command" rule at schema level -- the schema is the enforcement counterpart collocated with the semantics.
- Schema design (authoritative for the implementer):
  - Top-level fields: `schema_version` (int, =1), `slug`, `intent`, `plan_type`
    (IMPLEMENTATION|STRATEGIC|REPORT-ONLY), `verification_tier` (V1|V2|V3), `plan_path`, `phase`,
    `scope` (list, min 1, of {file, action: Create|Modify|Delete, purpose}),
    `bundled_recommendations` (list of str, default []), `infrastructure_dependencies` (list of str,
    default []), `acceptance_criteria` (list of str, min 1), `verification_plan` (list, min 1, of
    {step: int, phase: str, action, command, expected, fix_if}), `constraints` (list of str),
    `context` (list of str), `pre_implementation_checklist` (list of str),
    `execution_steps` (list of str), `work_areas` (list of {area, scope, rationale, complexity:
    XS|S|M|L|XL}, default []), `rollback` (str, optional).
  - `model_config = ConfigDict(extra="forbid")` -- unknown keys are schema drift and must fail.
  - Validators: VP `step` ids unique; every `command` non-empty after strip; STRATEGIC requires
    non-empty `work_areas`, non-STRATEGIC forbids them; IMPLEMENTATION requires non-empty
    `execution_steps`; `plan_path == f"docs/plans/PLAN-{slug}.yaml"`; `load(path)` additionally checks
    the actual filename equals `PLAN-{slug}.yaml` (dangling-reference guard).
  - `load(path)` uses `yaml.safe_load`; module imports must not raise (Import Safety pattern).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md consulted via the decision-scout gate (CITE list above); read the cited entries
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Create `scripts/plan_document.py` per the schema design in Context (model + `load` + CLI main; PASS/FAIL
   output and exit codes mirroring `scripts/platform_roadmap.py`).
2. Create `tests/test_plan_document.py` + `tests/fixtures/plan_documents/` (one valid document; malformed
   fixtures: bad enum, missing VP command, duplicate VP step ids, empty scope, unknown key, work_areas on
   IMPLEMENTATION, slug/plan_path mismatch). Include the `validate_plan_documents(plans_dir=tmp)` failure
   test against `scripts.validate`.
3. Add `validate_plan_documents(failed, plans_dir=None)` to `scripts/validate.py`; register in the full
   presubmit sequence next to `validate_platform_roadmap` and in the `--pre` tier next to
   `validate_product_roadmap`.
4. Port THIS plan to `docs/plans/PLAN-t1-11-plan-yaml-migration.yaml` (structure-only; sections map to
   schema fields; this .md is deleted in the same commit). Run VP 1.
5. Update `scripts/find_plan.py` (.yaml-first resolution; deprecation warning on .md fallback) and
   `scripts/plan_audit.py` (YAML scope parsing; deprecated markdown fallback); update their tests.
6. Update the three SKILL.md files under `.claude/skills/` (template -> YAML, read-path -> .yaml,
   deprecation note), preserving the plan-critique Frame Challenge phase and STRATEGIC refusal verbatim.
7. Mirror the same edits into `.agents/skills/` with the voluntary-legacy-hygiene framing.
8. Roadmap + decision bookkeeping: T1.11 status complete; CD.22 state ratified; mint the ratifying
   Decision in DECISIONS.md (with the Decision 76 clause-3 amendment note); session log entry.
9. File the commands-reconciliation follow-up rec via `scripts.ops_data_portal.file_rec` (call
   `get_rec_write_guidance()` first; outbox fallback acceptable offline).
10. **Execute Verification Plan** -- run each step. Loop until pass. If a step fails unrecoverably, stop
    and analyze root cause (Decision 55).
11. Report: what was implemented, verification results, the in-flight conversion list as executed.
