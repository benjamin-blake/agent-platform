# Plan

## Intent
Implement roadmap item T-1.7: split `config/` into `config/lambda/<lambda-name>/` (per-Lambda runtime payloads) and `config/agent/<consumer>/` (Claude Code agent-consumed config). Update `scripts/build_lambda.py`, the planning skill, and `AGENTS.md` so the Lambda Deployment Assessment glob narrows from blanket `config/` to `config/lambda/<name>/` + `config/config.yaml`. Net effect: V3 verification no longer fires on agent-only edits (DQ rules, executor prompts, copilot model registry, IAM runner manifest), eliminating the false-positive Lambda gating that today triggers on every `config/` change. Unblocks T-1.6 and T-1.8 which both depend on this directory structure.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2 (with DEFERRED-deploy step per Decision 67)

## Branch
claude/trusting-hypatia-RcAYw

## Phase
Phase 1: Core Infrastructure -- Tier T-1 (T-1.7)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `config/lambda/README.md` | Create | Document per-Lambda subtree convention |
| `config/lambda/data-pipeline/README.md` | Create | Placeholder for data-pipeline Lambda-only config |
| `config/lambda/ops-compaction/README.md` | Create | Placeholder for ops-compaction Lambda-only config |
| `config/agent/README.md` | Create | Document per-consumer agent subtree convention |
| `config/data_quality/` -> `config/agent/data_quality/` | Move (git mv) | Relocate DQ rules to agent subtree |
| `config/prompts/executor/` -> `config/agent/executor/prompts/` | Move (git mv) | Relocate executor prompts to agent subtree |
| `config/copilot_model_multipliers.yaml` -> `config/agent/copilot/model_multipliers.yaml` | Move | Relocate copilot model registry |
| `config/copilot_model_routing.yaml` -> `config/agent/copilot/model_routing.yaml` | Move | Relocate copilot model registry |
| `config/executor_capabilities.yaml` -> `config/agent/executor/capabilities.yaml` | Move | Relocate executor capability manifest |
| `config/iam_runner_manifest.yaml` -> `config/agent/validate/iam_runner_manifest.yaml` | Move | Relocate runner IAM manifest |
| `config/agent/executor/capabilities.yaml` (post-move) | Modify | Replace `boundary_patterns` entries `config/prompts/executor/` -> `config/agent/executor/prompts/` AND `config/prompts/` -> `config/agent/executor/prompts/`. This is the canonical Decision 44 boundary source consumed by `validate.py:_load_boundary_patterns()` -- not a hardcoded Python string. |
| `config/README.md` | Modify | Document the new lambda/ + agent/ layout |
| `scripts/build_lambda.py` | Modify | Replace blanket `shutil.copytree(ROOT/"config", ...)` with per-Lambda copy-list (`config/config.yaml` + `config/lambda/<name>/`) |
| `scripts/validate.py` | Modify | Update path constants for data_quality, copilot, executor_capabilities (now `config/agent/executor/capabilities.yaml`), iam_runner_manifest. `validate_executor_boundary()` itself is YAML-driven (no path-string edit needed); regression test verifies new boundary pattern in `tests/test_validate.py`. |
| `scripts/data_quality_runner.py` | Modify | DQ config path |
| `scripts/session_preflight.py` | Modify | DQ config path |
| `scripts/executor/rec_write_guidance.py` | Modify | DQ ops.yaml path (preserve Decision 66 Tier-A pre-write semantics) |
| `scripts/executor/plan.py` | Modify | prompts/executor + copilot paths |
| `scripts/executor/model_routing.py` | Modify | Copilot model registry path |
| `scripts/verifiers/data_quality.py` | Modify | DQ config path |
| `scripts/verifiers/schema_integrity.py` | Modify | DQ config path |
| `scripts/classify_automatable.py` | Modify | prompts/executor path |
| `scripts/model_registry.py` | Modify | Copilot model registry path |
| `scripts/copilot_multipliers_refresher.py` | Modify | Copilot model registry path |
| `scripts/ops_data_portal.py` | Modify | executor_capabilities path |
| `tests/test_validate.py` | Modify | Multiple paths + executor boundary regression |
| `tests/test_executor_postflight.py` | Modify | DQ config path |
| `tests/test_verifiers/test_coverage.py` | Modify | DQ config path |
| `tests/test_verifiers/test_harness.py` | Modify | DQ config path |
| `tests/test_ops_data_portal_validators.py` | Modify | executor_capabilities path |
| `tests/test_build_lambda.py` | Modify | Assert per-Lambda zip contents match new structure (no agent/, only config.yaml + lambda/<name>/) |
| `AGENTS.md` | Modify | TWO edit sites: (a) Instruction Architecture Layer 5 table row (line 121) `config/prompts/executor/*.prompt.md` -> `config/agent/executor/prompts/*.prompt.md`; (b) Temporary Operational Constraints Lambda-packaged file list -- replace `config/` with `config/config.yaml`, `config/lambda/<name>/`. |
| `.claude/skills/planning/SKILL.md` | Modify | TWO edit sites: (a) Lambda Deployment Assessment glob (replace `config/` with `config/config.yaml`, `config/lambda/<name>/`); (b) DQ coverage prose at line 53 (`config/data_quality/*.yaml` -> `config/agent/data_quality/*.yaml`). |
| `docs/DECISIONS.md` | Modify | Decision 44 boundary table row: `config/prompts/executor/*.prompt.md` -> `config/agent/executor/prompts/*.prompt.md`. Add one-line amendment note. |
| `docs/INTENT-recommendation-executor.md` | Modify | 9+ live references to `config/prompts/executor/` (lines 30, 36-40, 80, 259, 307, 343) -- update to `config/agent/executor/prompts/`. INTENT docs are live per CD.14 (demoted-but-readable), not archived. |
| `docs/INTENT-dq-enforcement.md` | Modify | 11+ live references to `config/data_quality/` -> `config/agent/data_quality/`. |
| `docs/ARCHITECTURE-WORKFLOW.md` | Modify | Line 335 (`config/prompts/executor/`), line 414 (`config/copilot_model_routing.yaml`) -- update to new paths. |
| `.github/workflows/refresh-copilot-multipliers.yml` | Modify | Line 48 `git add config/copilot_model_multipliers.yaml` -> `git add config/agent/copilot/model_multipliers.yaml`. Workflow breaks if not updated. |
| `.github/copilot-instructions.md` | Modify | TWO edit sites: (a) line ~95 `config/copilot_model_routing.yaml` table row; (b) line ~187 executor-self-modification-boundary file list (`config/prompts/executor/*.prompt.md` and `.github/instructions/executor-*.instructions.md` if path also changes). |
| `.github/instructions/executor-critique.instructions.md` | Modify | `applyTo:` clause: `config/prompts/executor/critique*` -> `config/agent/executor/prompts/critique*`. |
| `.github/instructions/executor-planning.instructions.md` | Modify | `applyTo:` clause: `config/prompts/executor/planning*,config/prompts/executor/refine*` -> `config/agent/executor/prompts/planning*,config/agent/executor/prompts/refine*`. |
| `.github/instructions/executor-implement.instructions.md` | Modify | `applyTo:` clause: `config/prompts/executor/implement*` -> `config/agent/executor/prompts/implement*`. |
| `.github/instructions/executor-review.instructions.md` | Modify | `applyTo:` clause: `config/prompts/executor/code-review*` -> `config/agent/executor/prompts/code-review*`. |
| `.github/instructions/executor-supervisor-rules.instructions.md` | Modify | TWO edit sites: (a) `applyTo:` clause; (b) line 25 table row referencing `config/prompts/executor/*.prompt.md`. |
| `.github/instructions/executor-supervisor-workflow.instructions.md` | Modify | `applyTo:` clause: `config/prompts/executor/*.prompt.md` -> `config/agent/executor/prompts/*.prompt.md`. |
| `config/agent/data_quality/ops.yaml` (post-move) | Modify | Internal ref(s) `config/executor_capabilities.yaml` -> `config/agent/executor/capabilities.yaml`. Critic flagged 2 lines (48, 84) -- update all occurrences. |
| `config/agent/data_quality/decisions/ops_recommendations.yaml` (post-move) | Modify | Internal refs `config/executor_capabilities.yaml` -> `config/agent/executor/capabilities.yaml`. Critic flagged 4 line refs (145, 233, 239, plus 1 historical "Create" mention -- update operational refs, leave historical narrative alone). |
| `docs/PROJECT_CONTEXT.md` | Modify | 6 live refs at lines 43, 44, 49, 66, 145, 238. Canonical project knowledge base loaded by workflows; stale paths poison ambient context. |
| `docs/contracts/instruction-architecture.md` | Modify | Line 38 Layer 5 heading: `### Layer 5: config/prompts/executor/ (Executor Role Prompts)` -> `### Layer 5: config/agent/executor/prompts/ (Executor Role Prompts)`. Architecturally load-bearing reference. |
| `docs/contracts/inference-provider.md` | Modify | Line 73 `config/copilot_model_routing.yaml` -> `config/agent/copilot/model_routing.yaml`. |
| `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` | Modify | ~11 live refs to `config/data_quality/` and `config/executor_capabilities.yaml`. Update via `grep -n` first then per-line Edit. |
| `docs/dq/ops-recommendations-remediation-briefing.md` | Modify | 2 live refs (lines 5, 115). |
| `docs/INTENT-aws-migration-platform-evolution.md` | Modify | 2 refs (lines 108, 109). |
| `docs/INTENT-ci-cd-architecture.md` | Modify | 1 ref (line ~429, `config/executor_capabilities.yaml`). |
| `docs/INTENT-ci-rca-methodology.md` | Modify | 1 ref (line ~486, `config/data_quality/source_registry.yaml`). |
| `docs/INTENT-ops-decisions-graduation.md` | Modify | ~10 refs across lines 321-753. |
| `docs/INTENT-pre-codegen-contract-ratification.md` | Modify | 6 refs (`config/data_quality/ops.yaml`, `config/data_quality/source_registry.yaml`, `config/copilot_model_routing.yaml` mentions). |
| `docs/INTENT-provider-agnostic-executor.md` | Modify | 1 ref (line ~425). |
| `docs/INTENT-verification-system.md` | Modify | 4 refs (lines 496, 497, 658, 659). |
| `.agents/skills/planning/SKILL.md` | Modify | Line 43 `config/data_quality/*.yaml` -> `config/agent/data_quality/*.yaml`. `.agents/` is canonical Antigravity layer per Decision 58 -- mirrors `.claude/skills/planning/SKILL.md` and must stay in sync. |
| `.claude/commands/develop-executor.md` | Modify | Line ~39 `config/executor_capabilities.yaml` -> `config/agent/executor/capabilities.yaml`. |
| `scripts/data_quality_runner.py` (already in scope) | Modify | Also update docstring refs at lines ~15, ~667 (not just code path constants). |
| **DEEP-FREEZE: log finding, DO NOT edit** | -- | `.github/prompts/plan.prompt.md` (line 80), `.github/agents/rca-analyst.agent.md` (line 46) -- AGENTS.md explicitly deep-freezes these directories. File a recommendation per stale ref via `bin/venv-python -m scripts.ops_data_portal --file-rec --source planning` for follow-up post-Decision-67-reversal. |
| **ARCHIVAL: NOT in scope** | -- | `docs/audit-reports/` (wave-1-outputs, wave-2-output, AUDIT-*) are committed audit artefacts capturing past planning state -- treat as historical, do not update. |

## Bundled Recommendations
None. (rec-714, "Deploy planning.prompt.md to Lambda after Decision 67 reversal," depends on Plan B and is intentionally not bundled here.)

## Acceptance Criteria
- [ ] `config/lambda/data-pipeline/` and `config/lambda/ops-compaction/` directories exist with README.md placeholders.
- [ ] `config/agent/{data_quality,executor,copilot,validate}/` subtrees exist; all moves are rename-only (no content diff besides path updates).
- [ ] `config/data_quality/`, `config/prompts/executor/`, `config/copilot_model_*.yaml`, `config/executor_capabilities.yaml`, `config/iam_runner_manifest.yaml` are absent at their old paths.
- [ ] `scripts/build_lambda.py` no longer calls `shutil.copytree(ROOT/"config", ...)`. Lambda zips contain `config/config.yaml` + `config/lambda/<name>/` only (no `config/agent/`, no `config/data_quality/`, no `config/prompts/`).
- [ ] `bin/venv-python -m scripts.validate` passes.
- [ ] `bin/venv-python -m pytest tests/ -q` passes.
- [ ] `bin/venv-python -m scripts.data_quality_runner` reads config from `config/agent/data_quality/` (structural path-resolution success -- always required).
- [ ] DQ baseline outcome recorded in the final report (PASS = clean baseline; FAIL = first-time-real-violations are logged as separate recommendations, not blockers for this plan -- per VP step 10b and Ordered Execution Step 23).
- [ ] `.claude/skills/planning/SKILL.md` Lambda Deployment Assessment uses `config/config.yaml` + `config/lambda/<name>/` glob (no blanket `config/`), AND the DQ coverage prose at line 53 cites `config/agent/data_quality/`.
- [ ] `AGENTS.md` Layer 5 table (line 121) cites `config/agent/executor/prompts/*.prompt.md`, AND Temporary Operational Constraints Lambda-packaged file list updated accordingly.
- [ ] `docs/DECISIONS.md` Decision 44 boundary table cites the new prompts path.
- [ ] `config/agent/executor/capabilities.yaml` `boundary_patterns` lists the new prompt path (`config/agent/executor/prompts/`) -- this is the canonical YAML source for `validate_executor_boundary()`, NOT a Python-string edit.
- [ ] Regression test in `tests/test_validate.py` confirms `validate_executor_boundary()` recognises a file at `config/agent/executor/prompts/*.prompt.md` as a boundary match.
- [ ] All 6 `.github/instructions/executor-*.instructions.md` `applyTo:` clauses cite new prompts path.
- [ ] `.github/workflows/refresh-copilot-multipliers.yml` adds `config/agent/copilot/model_multipliers.yaml`.
- [ ] No stale path strings remain anywhere in the live tree (verified by VP step 5's broadened grep).
- [ ] DEFERRED step note present in the final report referencing Decision 67 reversal.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|---|---|---|---|---|
| 1 | pre-deploy | New Lambda subtrees exist | `test -d config/lambda/data-pipeline && test -d config/lambda/ops-compaction && test -f config/lambda/data-pipeline/README.md` | Exit 0 | Missing dir -- create placeholder + README |
| 2 | pre-deploy | New agent subtrees exist with moved content | `test -f config/agent/data_quality/ops.yaml && test -f config/agent/executor/prompts/planning.prompt.md && test -f config/agent/copilot/model_multipliers.yaml && test -f config/agent/executor/capabilities.yaml && test -f config/agent/validate/iam_runner_manifest.yaml` | Exit 0 | Missing move target -- `git mv` and stage |
| 3 | pre-deploy | Old paths gone | `! test -e config/data_quality && ! test -e config/prompts && ! test -e config/copilot_model_multipliers.yaml && ! test -e config/copilot_model_routing.yaml && ! test -e config/executor_capabilities.yaml && ! test -e config/iam_runner_manifest.yaml` | Exit 0 | Old path lingering -- remove |
| 4 | pre-deploy | Moves were rename-only (file count parity) | `bash -c 'OLD=$(git log --diff-filter=R --follow --name-status HEAD~..HEAD -- config/agent/data_quality/ops.yaml \| grep -c "^R"); test "$OLD" -ge 1'` | Exit 0 (R = rename detected by git) | Content drift -- diff and align |
| 5 | pre-deploy | No stale path strings in live tree (broad scan) | `bash -c 'matches=$(grep -rn -E "config/(data_quality/\|prompts/executor/\|copilot_model_\|executor_capabilities\.yaml\|iam_runner_manifest\.yaml)" scripts/ src/ tests/ .github/ .claude/ .agents/ config/ AGENTS.md CLAUDE.md docs/INTENT-*.md docs/ARCHITECTURE-WORKFLOW.md docs/contracts/ docs/PROJECT_CONTEXT.md docs/dq/ 2>/dev/null \| grep -v "^Binary file" \| grep -v "docs/SESSION_LOG\|docs/CHANGELOG\|docs/DECISIONS_ARCHIVE\|docs/plans/PLAN-\|docs/plans/briefings/\|docs/audit-reports/\|/__pycache__/\|\\.github/prompts/\|\\.github/agents/" \| wc -l); echo "stale_refs=$matches"; test "$matches" -eq 0'` | Output `stale_refs=0` and exit 0 | Update missed consumer. The `grep -v` excludes historical artefacts (PLAN snapshots, SESSION_LOG, DECISIONS_ARCHIVE, CHANGELOG, briefings, audit-reports) AND deep-frozen surfaces (`.github/prompts/`, `.github/agents/` per AGENTS.md). Everything else is treated as live and must be migrated. `docs/DECISIONS.md` is intentionally NOT in the scan -- it's edited via Step 17 only (Decision 44 boundary row), other DECISIONS.md content is historical. |
| 6 | pre-deploy | Lambda zip contents narrow | `bin/venv-python -m scripts.build_lambda 2>&1 \| tail -5 && bash -c 'unzip -l lambda-packages/data-pipeline.zip \| grep -E "^.*config/" \| grep -v -E "config/config\.yaml\|config/config\.yaml\.example\|config/README\.md\|config/lambda/" \| wc -l'` | Output `0` (no agent/DQ/prompts paths in zip) | Trim build_lambda copy-list |
| 7 | pre-deploy | Ops-compaction zip equally narrow | `bash -c 'unzip -l lambda-packages/ops-compaction.zip \| grep -E "^.*config/" \| grep -v -E "config/config\.yaml\|config/config\.yaml\.example\|config/README\.md\|config/lambda/" \| wc -l'` | Output `0` | Trim build_lambda copy-list for ops_compaction package |
| 8 | pre-deploy | Full pytest suite green | `bin/venv-python -m pytest tests/ -q` | All tests pass | Fix path import or test assertion |
| 9 | pre-deploy | validate.py presubmit green | `bin/venv-python -m scripts.validate` | "All checks passed" | Address the specific check failure |
| 10a | pre-deploy | DQ runner reads from new path (structural success) | `bin/venv-python -m scripts.data_quality_runner 2>&1 \| tee /tmp/dq.out; grep -q "config/agent/data_quality" /tmp/dq.out` | Exit 0 (path-resolution works) | Fix DQ runner path constant |
| 10b | pre-deploy | DQ baseline result recorded (informational, NOT blocking) | `tail -20 /tmp/dq.out` then capture verdict in report | PASS or FAIL+findings-list logged | If FAIL: log each failing check as a separate recommendation via `bin/venv-python -m scripts.ops_data_portal --file-rec --source ci_rca`, then continue. Do NOT roll back this plan for DQ-content findings. |
| 11 | pre-deploy | Decision 44 boundary table updated in DECISIONS.md | `grep -q "config/agent/executor/prompts/\*\.prompt\.md" docs/DECISIONS.md` | Match found | Update Decision 44 row in DECISIONS.md |
| 11a | pre-deploy | capabilities.yaml boundary_patterns updated | `bash -c 'grep -q "config/agent/executor/prompts/" config/agent/executor/capabilities.yaml && ! grep -E "^\\s*- config/prompts/" config/agent/executor/capabilities.yaml'` | Both clauses true | Edit `boundary_patterns` entries in `config/agent/executor/capabilities.yaml` |
| 12 | pre-deploy | validate_executor_boundary recognises new prompts path (regression test) | `bash -c 'grep -q "test_executor_boundary_matches_new_prompt_path" tests/test_validate.py && bin/venv-python -m pytest tests/test_validate.py -v 2>&1 \| grep -q "test_executor_boundary_matches_new_prompt_path PASSED"'` | Both clauses true (definition exists AND full-file pytest run passes the named test). PROJECT_CONTEXT.md `Pytest -k selector gotcha` is honoured by using grep+full-file pytest rather than `-k`. | Add the test case OR fix the YAML boundary_patterns update if test is correct but match fails |
| 12a | pre-deploy | All 6 executor instructions applyTo updated | `bash -c 'count=$(grep -l "applyTo.*config/agent/executor/prompts" .github/instructions/executor-*.instructions.md \| wc -l); test "$count" -eq 6'` | Exit 0 (all 6 files updated) | Update the missing instructions file's applyTo clause |
| 12b | pre-deploy | refresh-copilot-multipliers workflow updated | `grep -q "config/agent/copilot/model_multipliers.yaml" .github/workflows/refresh-copilot-multipliers.yml` | Match | Update `git add` path in the workflow |
| 13 | pre-deploy | Planning skill glob narrowed | `bash -c 'grep -E "config/lambda/" .claude/skills/planning/SKILL.md && ! grep -E "Lambda-packaged.*config/[^l]" .claude/skills/planning/SKILL.md'` | Both clauses true | Update Lambda Deployment Assessment glob |
| 14 | pre-deploy | AGENTS.md Lambda-packaged list narrowed | `bash -c 'grep -q "config/config\.yaml" AGENTS.md && grep -q "config/lambda/" AGENTS.md && ! grep -E "Lambda-packaged files .*config/[\\\`,)]" AGENTS.md'` | Match | Update AGENTS.md Temporary Operational Constraints |
| 15 | **DEFERRED** | Lambda deploy + smoke test | `# DEFERRED: bin/venv-python -m scripts.build_lambda --deploy && bin/venv-python -m scripts.run_scheduled_agent --smoke-test doc-freshness (pending Decision 67 reversal)` | n/a -- step is intentionally not executed | Plan B will execute this step after D67 reversal |

## Constraints
- No rescue agents or workaround loops (Decision 55).
- Executor freeze active (Decision 67): plan must be IMPLEMENTATION (not STRATEGIC); Lambda deploy steps are DEFERRED.
- Single Portal Invariant (AGENTS.md): never `Edit` or `Write` `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly.
- Warehouse-as-source-of-truth invariant: do not stage records from local files to Athena (never `OpsWriter.write()` from a read cache).
- SLOC limits (Decision 43): modified scripts must stay <500 SLOC OR preserve existing complexity-waiver headers (notably `scripts/validate.py` already has a waiver -- preserve it; `scripts/executor/plan.py` likewise).
- Decision 66 (Precision Context Injection): `scripts/executor/rec_write_guidance.py` reads ops.yaml semantics for Tier A pre-write injection. The path move must preserve `get_rec_write_guidance()` behaviour.
- Decision 65 (ops.yaml Extended Contract): moved `config/agent/data_quality/ops.yaml` and `telemetry.yaml` remain the canonical field-semantic authority. Content stays byte-identical aside from internal cross-references.
- Decision 44 (Executor Self-Modification Boundary): boundary patterns are sourced from `config/executor_capabilities.yaml` (the canonical YAML, moved to `config/agent/executor/capabilities.yaml` in this plan), not hardcoded in Python. The plan updates THREE artefacts in lockstep: (a) the boundary_patterns YAML entries (Step 5), (b) the DECISIONS.md Decision 44 table row (Step 17), (c) a regression test in `tests/test_validate.py` asserting end-to-end recognition at the new path (Step 12). The copilot-instructions.md boundary file list and the `.github/instructions/executor-*.instructions.md` `applyTo:` clauses are additional consumer surfaces -- also updated (Steps 19, 20).
- No emojis in code/scripts/docs. ASCII hyphens only.
- All file edits go through standard tools; no direct `Edit`/`Write` to `logs/`.

## Context

- **Roadmap alignment:** T-1.7 in `docs/ROADMAP-PLATFORM.yaml`, `depends_on: []`, effort S. Eligible now. Unblocks T-1.6 (CD.16 per-Lambda gating wiring, depends_on [T-1.5, T-1.7]) and T-1.8 (per-Lambda manifest mechanism, depends_on [T-1.5, T-1.7]).
- **V3 narrowing motivator (Decision 73):** the current blanket `config/` Lambda glob in `AGENTS.md` causes V3 verification to fire on every DQ/prompt/copilot edit, conflating L1 fast-tier eligibility with comprehensive validation. T-1.7 is the structural prerequisite for tier-clean diff-aware CI.
- **Branch naming exception:** this session runs on `claude/trusting-hypatia-RcAYw` per the Claude Code on the web container's system instructions, instead of the standard `agent/{slug}` convention. The plan filename `PLAN-config-lambda-split.md` uses a content-derived slug. `find_plan.py`'s slug-from-branch derivation may not match -- the executor should consume this plan by absolute path.
- **Plan B (separate session):** Decision 67 reversal is intentionally NOT in this plan's scope. Plan B handles: telemetry DQ baseline (the DQ runner has "never run" per preflight -- step 10 above establishes that baseline as a side effect), Lambda dispatcher re-enable per AGENTS.md runbook, smoke-test sweep, and amend Decision 67 to mark reversed. Plan B must land AFTER this plan merges.
- **CI RCA queue:** open ci_rca recs at planning time: 0 (rec-859 was marked closed during this planning session after verifying `scripts/product_roadmap.py` is now 451 SLOC, well under the 500-SLOC Decision 43 limit).
- **Lambda packages affected:** `data-pipeline.zip` and `ops-compaction.zip`. Both currently `shutil.copytree(ROOT/"config", ...)` blanket-copy all of `config/`. After this plan, both copy only `config/config.yaml` (loaded by `src.common.config` at runtime, used by handlers via `src.common.config.config`) plus their respective `config/lambda/<name>/` subtree (empty placeholder initially).
- **Shared config files staying at root:** `config/config.yaml`, `config/config.yaml.example`, `config/config.company.yaml`, `config/config.personal.yaml`, `config/README.md`. `src/common/config.py` env_map (lines 56-59) still resolves these by filename within `config_dir`; no path change.
- **Test impact:** `tests/test_executor_postflight.py`, `tests/test_validate.py`, `tests/test_verifiers/{test_coverage,test_harness}.py`, `tests/test_ops_data_portal_validators.py`, `tests/test_build_lambda.py` all reference moved paths and need updates.
- **Documentation note:** the only intentionally-NOT-updated path references are in historical artefacts (`docs/plans/PLAN-*.md`, `docs/plans/briefings/`, `docs/SESSION_LOG.md`, `docs/SESSION_LOG_ARCHIVE.md`, `docs/DECISIONS_ARCHIVE.md`, `docs/CHANGELOG.md`). Everything else -- `AGENTS.md`, `CLAUDE.md`, `docs/INTENT-*.md`, `docs/ARCHITECTURE-WORKFLOW.md`, `docs/contracts/`, `docs/dq/`, `.github/copilot-instructions.md`, `.github/instructions/`, `.github/workflows/`, `.claude/skills/`, `config/README.md` -- is treated as live and updated.
- **`.github/` deep-freeze disambiguation:** `AGENTS.md` deep-freezes `.github/prompts/` and `.github/agents/` ONLY. `.github/instructions/`, `.github/workflows/`, and `.github/copilot-instructions.md` are live consumer surfaces and ARE in scope for this plan. (If during implementation the executor encounters a `.github/prompts/` or `.github/agents/` file with a stale path reference, it should LOG the finding but NOT edit -- the deep-freeze takes precedence.)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (we are on `claude/trusting-hypatia-RcAYw`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/DECISIONS.md` read (especially Decisions 43, 44, 48, 65, 66, 67, 73).
- [ ] `docs/ROADMAP-PLATFORM.yaml` T-1.7 entry read.
- [ ] All files in Scope table located and readable.
- [ ] Acceptance Criteria understood and verifiable.
- [ ] AWS SSO active OR Step 0 below has been completed.

## Ordered Execution Steps

1. **AWS SSO login (web-container requirement).** This plan is intended to run in a Claude Code on the web Linux container; AWS SSO is required for `ops_data_portal` `update_rec` calls and any Athena-backed verifier. Run:
   ```bash
   aws sso login --profile company-aws-profile --use-device-code --no-browser 2>&1 | head -30
   ```
   Surface the printed device-code URL and code to the human, wait for them to authorize, then verify with:
   ```bash
   bin/venv-python -c "import boto3; print(boto3.Session(profile_name='company-aws-profile').client('sts').get_caller_identity()['Arn'])"
   ```
   If SSO is already active (the wrapper above exits with `Successfully logged into Start URL`), no human action is required; proceed.

2. **Pre-flight checklist.** Tick every item in the Pre-Implementation Checklist above. If any item fails, stop and report.

3. **Create new directory skeleton.** Create `config/lambda/{data-pipeline,ops-compaction}/` and `config/agent/{data_quality,executor/prompts,copilot,validate}/` with `README.md` placeholders. Each `config/lambda/<name>/README.md` should state: "Per-Lambda runtime payloads for the `<name>` Lambda function. Files here are bundled into `<name>.zip` by `scripts/build_lambda.py`. Initially empty -- populated as Lambda-specific config emerges." Each `config/agent/<consumer>/README.md` should state: "Agent-consumed config for `<consumer>`. NOT bundled into any Lambda zip."

4. **Move existing config trees with `git mv` (preserves history).** Handle each move group explicitly to avoid wildcard pitfalls with subdirectories. The data_quality tree contains a `decisions/` subdirectory; older Git versions can mis-handle `git mv subdir/*` with mixed file+directory contents, so move the subdirectory separately:
   ```bash
   # data_quality (files + subdirectory)
   for f in config/data_quality/*.yaml; do
     [ -f "$f" ] && git mv "$f" "config/agent/data_quality/$(basename "$f")"
   done
   if [ -d config/data_quality/decisions ]; then
     git mv config/data_quality/decisions config/agent/data_quality/decisions
   fi
   rmdir config/data_quality 2>/dev/null || true

   # executor prompts (files only, no subdirs expected)
   for f in config/prompts/executor/*; do
     [ -f "$f" ] && git mv "$f" "config/agent/executor/prompts/$(basename "$f")"
   done
   rmdir config/prompts/executor && rmdir config/prompts

   # single-file moves
   git mv config/copilot_model_multipliers.yaml config/agent/copilot/model_multipliers.yaml
   git mv config/copilot_model_routing.yaml config/agent/copilot/model_routing.yaml
   git mv config/executor_capabilities.yaml config/agent/executor/capabilities.yaml
   git mv config/iam_runner_manifest.yaml config/agent/validate/iam_runner_manifest.yaml
   ```
   Verify with `git status` -- every entry must appear as `renamed:`, not `deleted` + `new file`. If any appear as delete+add, run `git mv --force` per file OR rebase the staging so git detects the rename.

5. **Update content of `config/agent/executor/capabilities.yaml` (Decision 44 mechanism).** The YAML's `boundary_patterns` list has TWO entries referencing the old prompt path:
   - Line ~7: `- config/prompts/executor/` -> `- config/agent/executor/prompts/`
   - Line ~31: `- config/prompts/` -> `- config/agent/executor/prompts/` (or remove if redundant with the line-7 pattern -- check `_load_boundary_patterns()` semantics first; if both patterns are independently matched, replace both with the new path)
   This is the canonical source consumed by `scripts/validate.py:_load_boundary_patterns()` -- no Python edit is needed if the YAML reload picks up the new patterns. The regression test in step 12 of the VP verifies end-to-end.

6. **Update internal references inside moved data_quality YAMLs.** Each YAML has multiple lines referencing `config/executor_capabilities.yaml`:
   - `config/agent/data_quality/ops.yaml` (operational refs at lines ~48, ~84 -- verify via `grep -n` after the move)
   - `config/agent/data_quality/decisions/ops_recommendations.yaml` (operational refs at lines ~145 and ~233; SKIP line ~239 which is the historical "(1) Create config/executor_capabilities.yaml..." narrative)
   Replace `config/executor_capabilities.yaml` with `config/agent/executor/capabilities.yaml` on the OPERATIONAL refs only. Use `grep -n` first to identify exact lines, then `Edit` each line individually to avoid sweeping the historical narrative.

7. **Update Python consumers (group: DQ path).** In each of the following files, replace `config/data_quality/` with `config/agent/data_quality/`:
   - `scripts/validate.py`
   - `scripts/data_quality_runner.py`
   - `scripts/session_preflight.py`
   - `scripts/executor/rec_write_guidance.py`
   - `scripts/verifiers/data_quality.py`
   - `scripts/verifiers/schema_integrity.py`
   - `tests/test_validate.py`
   - `tests/test_executor_postflight.py`
   - `tests/test_verifiers/test_coverage.py`
   - `tests/test_verifiers/test_harness.py`

8. **Update Python consumers (group: executor prompts path).** Replace `config/prompts/executor/` with `config/agent/executor/prompts/`:
   - `scripts/classify_automatable.py`
   - `scripts/executor/plan.py` (the real path is `PROMPTS_DIR = Path("config/prompts/executor")` near the top of the file; copilot refs elsewhere in this file are docstring-only and need no edit)

9. **Update Python consumers (group: copilot model registry path).** Replace `config/copilot_model_multipliers.yaml` with `config/agent/copilot/model_multipliers.yaml` and `config/copilot_model_routing.yaml` with `config/agent/copilot/model_routing.yaml`:
   - `scripts/copilot_multipliers_refresher.py`
   - `scripts/model_registry.py`
   - `scripts/validate.py` (consolidate edit with step 7)
   - `scripts/executor/model_routing.py`

10. **Update Python consumers (group: executor_capabilities path).** Replace `config/executor_capabilities.yaml` with `config/agent/executor/capabilities.yaml`:
    - `scripts/ops_data_portal.py`
    - `scripts/validate.py` (consolidate edits across steps 7, 9, 10, 11 into a single working pass per file -- multiple `Edit` tool invocations on the same file in succession are fine; do NOT use `replace_all` because of risk of clobbering unrelated lines)
    - `tests/test_ops_data_portal_validators.py`

11. **Update Python consumers (group: iam_runner_manifest path).** Replace `config/iam_runner_manifest.yaml` with `config/agent/validate/iam_runner_manifest.yaml`:
    - `scripts/validate.py` (consolidate)
    - `tests/test_validate.py` (consolidate)

12. **Add regression test for Decision 44 boundary recognition at new path.** Add a test case to `tests/test_validate.py` named something like `test_executor_boundary_matches_new_prompt_path` that asserts a path `config/agent/executor/prompts/planning.prompt.md` is recognised as an executor boundary file by `validate_executor_boundary()`. (Note: the mechanism update happens in Step 5 by editing the YAML `boundary_patterns`. This test verifies end-to-end.)

13. **Update `scripts/build_lambda.py` copy-list.** In `build_app_package()` and `build_ops_compaction_package()`, replace `shutil.copytree(ROOT / "config", app_dir / "config")` with explicit copies:
    ```python
    config_dest = app_dir / "config"
    config_dest.mkdir(parents=True)
    shutil.copy2(ROOT / "config" / "config.yaml", config_dest / "config.yaml")
    shutil.copy2(ROOT / "config" / "config.yaml.example", config_dest / "config.yaml.example")
    lambda_subtree_src = ROOT / "config" / "lambda" / "<name>"  # data-pipeline or ops-compaction
    if lambda_subtree_src.exists():
        shutil.copytree(lambda_subtree_src, config_dest / "lambda" / "<name>")
    ```
    Parametrise per-Lambda by name. Confirm the example YAMLs (`config.company.yaml`, `config.personal.yaml`) are NOT copied (they are dev-machine overlays, not Lambda runtime).

14. **Update `tests/test_build_lambda.py`.** Adjust assertions to expect:
    - Lambda zip CONTAINS `config/config.yaml`, `config/lambda/<name>/...` (when the subtree has content).
    - Lambda zip does NOT contain `config/data_quality/`, `config/prompts/`, `config/agent/`, `config/copilot_*`, `config/executor_capabilities.yaml`, `config/iam_runner_manifest.yaml`.

15. **Update `AGENTS.md` (TWO edit sites).**
    (a) Instruction Architecture Layer 5 table row (line ~121): replace `config/prompts/executor/*.prompt.md` with `config/agent/executor/prompts/*.prompt.md`.
    (b) Temporary Operational Constraints -> "Lambda deployment deferred (Decision 67)" section: replace `(`config/`, `scripts/llm_client.py`, ...)` with `(`config/config.yaml`, `config/lambda/<name>/`, `scripts/llm_client.py`, `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`)`.

16. **Update `.claude/skills/planning/SKILL.md` (TWO edit sites).**
    (a) Infrastructure & Lambda Assessment (Workflow Step 4) -> Lambda Deployment subsection: replace the broad `config/` rule with the per-Lambda glob. A plan's scope triggers Lambda Deployment Assessment when it contains any of `config/config.yaml`, files under `config/lambda/<name>/`, `src/data/handlers/`, `scripts/llm_client.py`, `.github/agents/schedule.yaml`, or `.github/prompts/scheduled/`. Note that `config/agent/` is explicitly NOT a trigger.
    (b) DQ coverage prose at line ~53 (`config/data_quality/*.yaml`): replace with `config/agent/data_quality/*.yaml`.

17. **Update `docs/DECISIONS.md` Decision 44 boundary table.** Locate the row referencing `config/prompts/executor/*.prompt.md` and replace with `config/agent/executor/prompts/*.prompt.md`. Add a one-line amendment note: "Path updated by T-1.7 (config split). Mechanism unchanged." DO NOT renumber or reorder other Decision 44 rows.

18. **Update ambient context docs and INTENT/contracts/dq surface (live consumer surface).** These are demoted-but-readable per CD.13/CD.14, NOT archived. Agents load them via workflows, so stale paths poison ambient context.
    Strategy for each file: `grep -n "config/(data_quality/\|prompts/executor/\|copilot_model_\|executor_capabilities\.yaml\|iam_runner_manifest\.yaml)" <file>` first, then `Edit` per line. Do NOT use `replace_all`.

    **Ambient context (canonical knowledge base):**
    - `docs/PROJECT_CONTEXT.md` (6 refs: lines ~43, 44, 49, 66, 145, 238) -- the LLM-loaded project knowledge base.
    - `docs/contracts/instruction-architecture.md` (line 38 Layer 5 heading, plus any body refs).
    - `docs/contracts/inference-provider.md` (line ~73).

    **INTENT docs:**
    - `docs/INTENT-recommendation-executor.md` (~9 refs).
    - `docs/INTENT-dq-enforcement.md` (~11 refs).
    - `docs/INTENT-aws-migration-platform-evolution.md` (lines ~108, 109).
    - `docs/INTENT-ci-cd-architecture.md` (line ~429).
    - `docs/INTENT-ci-rca-methodology.md` (line ~486).
    - `docs/INTENT-ops-decisions-graduation.md` (~10 refs).
    - `docs/INTENT-pre-codegen-contract-ratification.md` (~6 refs).
    - `docs/INTENT-provider-agnostic-executor.md` (line ~425).
    - `docs/INTENT-verification-system.md` (4 refs: lines 496, 497, 658, 659).

    **DQ methodology docs:**
    - `docs/dq/DQ_REMEDIATION_METHODOLOGY.md` (~11 refs).
    - `docs/dq/ops-recommendations-remediation-briefing.md` (lines ~5, 115).

    **Architecture:**
    - `docs/ARCHITECTURE-WORKFLOW.md` -- line ~335 (`config/prompts/executor/` -> `config/agent/executor/prompts/`) and line ~414 (`config/copilot_model_routing.yaml` -> `config/agent/copilot/model_routing.yaml`).

    **`.agents/` and `.claude/commands/`:**
    - `.agents/skills/planning/SKILL.md` (line ~43) -- canonical Antigravity layer per Decision 58; mirrors `.claude/skills/planning/SKILL.md` already covered in Step 16.
    - `.claude/commands/develop-executor.md` (line ~39 `config/executor_capabilities.yaml` -> `config/agent/executor/capabilities.yaml`).

    **Within-scope script docstring sweep:**
    - `scripts/data_quality_runner.py` lines ~15 and ~667 (docstring refs that drift if not updated; main code paths already covered by Step 7).

18a. **Deep-freeze: file follow-up recommendations, DO NOT edit.** Per AGENTS.md, `.github/prompts/` and `.github/agents/` are deep-frozen. The following files contain stale path references:
    - `.github/prompts/plan.prompt.md` (line ~80, `config/data_quality/*.yaml`).
    - `.github/agents/rca-analyst.agent.md` (line ~46, `config/prompts/executor/planning.prompt.md`).
    File one recommendation per stale ref:
    ```bash
    bin/venv-python -m scripts.ops_data_portal --file-rec \
      --source planning \
      --priority Medium --effort XS --risk low \
      --file ".github/prompts/plan.prompt.md" \
      --title "Update .github/prompts/plan.prompt.md stale config path post-T-1.7" \
      --context "T-1.7 config split moved config/data_quality/ to config/agent/data_quality/. .github/prompts/plan.prompt.md line 80 still references the old path. Per AGENTS.md deep-freeze rule, this file was NOT edited in T-1.7. Update when deep-freeze lifts (post-Decision-67-reversal) or when explicitly authorised." \
      --acceptance "grep -q 'config/agent/data_quality' .github/prompts/plan.prompt.md"
    ```
    Repeat with the appropriate substitution for `rca-analyst.agent.md`. Both recommendations should land in `ops_recommendations` and surface in future preflights.

19. **Update `.github/instructions/executor-*.instructions.md` (6 files).** Each has an `applyTo:` clause naming `config/prompts/executor/...`. Update each per the mapping:
    - `executor-critique.instructions.md`: `config/prompts/executor/critique*` -> `config/agent/executor/prompts/critique*`
    - `executor-planning.instructions.md`: `config/prompts/executor/planning*,config/prompts/executor/refine*` -> `config/agent/executor/prompts/planning*,config/agent/executor/prompts/refine*`
    - `executor-implement.instructions.md`: `config/prompts/executor/implement*` -> `config/agent/executor/prompts/implement*`
    - `executor-review.instructions.md`: `config/prompts/executor/code-review*` -> `config/agent/executor/prompts/code-review*`
    - `executor-supervisor-rules.instructions.md`: TWO edits -- `applyTo:` clause + table row at line ~25 referencing `config/prompts/executor/*.prompt.md`
    - `executor-supervisor-workflow.instructions.md`: `applyTo:` clause `config/prompts/executor/*.prompt.md` -> `config/agent/executor/prompts/*.prompt.md`
    AGENTS.md's deep-freeze list (`.github/prompts/`, `.github/agents/`) does NOT include `.github/instructions/`, so these files are live and must be updated.

20. **Update `.github/copilot-instructions.md` (TWO edit sites).**
    (a) Around line 95: table row `config/copilot_model_routing.yaml` -> `config/agent/copilot/model_routing.yaml`.
    (b) Around line 187: executor self-modification boundary file list -- replace `config/prompts/executor/*.prompt.md` with `config/agent/executor/prompts/*.prompt.md`. Other entries (`scripts/execute_recommendation.py`, `.github/instructions/executor-*.instructions.md`) stay as-is.

21. **Update `.github/workflows/refresh-copilot-multipliers.yml`.** Line ~48: replace `git add config/copilot_model_multipliers.yaml` with `git add config/agent/copilot/model_multipliers.yaml`. The workflow breaks if not updated -- it's a live CI consumer.

22. **Update `config/README.md`.** Rewrite the layout description to reflect the new `config/lambda/<name>/` + `config/agent/<consumer>/` structure. Document which files are at root (shared between Lambda runtime and agents) vs which moved into the new subtrees.

23. **Execute the Verification Plan.** Run each VP step in order. Loop on individual failures (e.g., a stale path string discovered by VP step 5 -> patch consumer -> re-run step 5). If VP step 10b (DQ baseline) fails with actual data-quality issues (not a path bug), STOP and file a recommendation for each failing check via `bin/venv-python -m scripts.ops_data_portal --file-rec --source ci_rca` -- these are real findings, not blockers for this plan. Note them in the report and continue.

24. **Report.** Summarise:
    - All paths moved (count files renamed)
    - Files modified (grouped by category)
    - VP step outcomes (one line per step)
    - DQ baseline verdict (PASS or failing-check IDs)
    - Decision 44 amendment note (one-line confirmation that DECISIONS.md row was updated)
    - **Explicit DEFERRED-deploy acknowledgement:** "VP step 15 (Lambda deploy + smoke test) is DEFERRED pending Decision 67 reversal -- to be executed by Plan B."
