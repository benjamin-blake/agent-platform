# Plan

## Intent
Land three small T-1 bootstrap items in a single IMPLEMENTATION plan: (1) sweep the ~30 stale `docs/ROADMAP.md` consumers left over from the PR #335 rename to `docs/ROADMAP-PRODUCT.md` (tier item T-1.0); (2) install a portable `pre-commit` framework as commit-time backup to the `never_on_main` hook (tier item T0.10); (3) add a new T-1.7 tier_item to `docs/ROADMAP-PLATFORM.yaml` persisting the config-split work as a successor / prerequisite for T-1.6. Together this fixes the live consumer-breakage from the rename, hardens the main-branch protection at the git layer, and persists the architectural direction for the next plan.

## Plan Type
IMPLEMENTATION

Compatible with Decision 67's freeze: no STRATEGIC decomposition, no Lambda code changes, no infrastructure. The single Lambda-packaged file modified (`src/data/handlers/scheduled_agent_handler.py`) only updates the docs payload it bundles; Lambda build / deploy / smoke-test are DEFERRED per Decision 67 and the currently-disabled dispatcher per CLAUDE.md runbook.

## Verification Tier
V2

Mixed surface: grep correctness for the sweep, Python import smoke + preflight functional run for the handler/preflight changes, behavioural test for the pre-commit hook, YAML parse + structural assertions for the roadmap edit.

## Branch
agent/t-1-bootstrap-cleanup

## Phase
T-1 (Governance ratification + harness integration). Items T-1.0 and T0.10 are bootstrap-eligible per the `agent_instructions` clause in `docs/ROADMAP-PLATFORM.yaml`. The T-1.7 addition is roadmap-edit work, not the implementation of T-1.7 itself (that lands in a separate plan).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/PROJECT_CONTEXT.md | Modify | Add per-call-site disambiguation rule: when to reference ROADMAP-PRODUCT.md vs ROADMAP-PLATFORM.yaml |
| scripts/session_preflight.py | Modify | Replace `docs/ROADMAP.md` constant and `roadmap_phase` extraction with new paths |
| scripts/build_lambda.py | Modify | Update Lambda packaging copy list to reference the renamed file(s) |
| src/data/handlers/scheduled_agent_handler.py | Modify | Lambda-packaged: update runtime path resolution for roadmap context |
| .claude/commands/plan.md | Modify | Update context references |
| .claude/skills/planning/SKILL.md | Modify | Update context references |
| .claude/skills/plan-critique/SKILL.md | Modify | Update context-loading list (critical — this skill loads roadmap as context) |
| .claude/skills/code-review/SKILL.md | Modify | Update context references |
| .claude/agents/scheduled/rec-curator.md | Modify | Update context references |
| .agents/workflows/plan.md | Modify | Vendor-portable harness alternative; update references |
| .agents/skills/planning/SKILL.md | Modify | Update references |
| .agents/skills/plan-critique/SKILL.md | Modify | Update references |
| .agents/skills/code-review/SKILL.md | Modify | Update references |
| .github/copilot-instructions.md | Modify | Legacy VS Code instructions; update references |
| .github/prompts/plan.prompt.md | Modify | Legacy VS Code prompt; update references |
| .github/prompts/documentation_update.prompt.md | Modify | Reroute writes that targeted ROADMAP.md to the correct sibling |
| .github/prompts/scheduled/doc-freshness.prompt.md | Modify | Update references (likely needs both roadmaps) |
| .github/prompts/scheduled/prompt-quality.prompt.md | Modify | Update references |
| .github/prompts/scheduled/rec-curator.prompt.md | Modify | Update references |
| .github/agents/code-review.agent.md | Modify | Update references |
| .github/agents/plan-critique.agent.md | Modify | Update references |
| docs/ARCHITECTURE.md | Modify | Update cross-references |
| docs/ARCHITECTURE-WORKFLOW.md | Modify | Update cross-references |
| docs/GETTING_STARTED.md | Modify | Update cross-references |
| docs/INTENT-ops-decisions-graduation.md | Modify | Update demoted-INTENT cross-references |
| docs/INTENT-autonomous-improvement-control-plane.md | Modify | Update demoted-INTENT cross-references |
| docs/INTENT-ci-cd-architecture.md | Modify | Update demoted-INTENT cross-references |
| terraform/README.md | Modify | Update cross-references |
| README.md | Modify | Update top-level project intro references |
| docs/ROADMAP-PLATFORM.yaml | Modify | Add T-1.7 tier_item; add `T-1.7` to T-1.6's depends_on |
| .pre-commit-config.yaml | Modify | Add `no-commit-to-branch` hook to existing config. The file already exists with ruff / detect-secrets / 6 stock hooks; T0.10's actual gap is only the main-branch protection hook. |
| requirements-dev.txt | Create | New file. `pre-commit` is installed in the venv (v4.5.1) but unpinned in any requirements file; this tracks it. |
| docs/plans/PLAN-t-1-bootstrap-cleanup.md | Create | This file |

## Bundled Recommendations
None. None of the top-5 priority-queue recs (rec-429, rec-027, rec-457, rec-468, rec-296) align with this scope.

## Infrastructure Dependencies
None. No `.tf` files modified.

## Lambda Deployment
DEFERRED. `src/data/handlers/scheduled_agent_handler.py` is Lambda-packaged but the dispatcher Lambda is currently disabled (CLAUDE.md "Re-enable Lambda scheduled agents" runbook + Decision 67 freeze). Per CD.16 (when ratified, in T-1.1), per-Lambda gating would require smoke-test for the dispatcher, but CD.16 explicitly defers dispatcher smoke-test until T4.3 (dispatcher re-enablement). Result: `python -m scripts.build_lambda --deploy` + `python -m scripts.run_scheduled_agent --smoke-test` are explicitly DEFERRED in this plan. Local `--dry-run` packaging inspection is sufficient verification.

## Acceptance Criteria

T-1.0:
- [ ] `grep -rn "docs/ROADMAP\.md" --exclude-dir=.git --exclude-dir=docs/plans/briefings --exclude=SESSION_LOG_ARCHIVE.md --exclude-dir=docs/plans .` returns zero hits in production code/docs (historical PLAN-*.md files retain original references — they are committed history)
- [ ] `.venv/Scripts/python.exe -m scripts.session_preflight` resolves `context.roadmap_phase` to a non-`unknown` value, proving the preflight extractor reads the new path successfully
- [ ] `.venv/Scripts/python.exe -m scripts.build_lambda --dry-run` lists `docs/ROADMAP-PRODUCT.md` (or the chosen replacement file) in the package payload, not `docs/ROADMAP.md`
- [ ] `src/data/handlers/scheduled_agent_handler.py` imports cleanly and contains no string-literal reference to `docs/ROADMAP.md`
- [ ] `.github/prompts/strategic_review.prompt.md` confirmed absent (precondition — already deleted in commit 6488579)
- [ ] Per-call-site disambiguation rule documented in `docs/PROJECT_CONTEXT.md`

T0.10:
- [ ] `.pre-commit-config.yaml` has the `no-commit-to-branch` hook added (with `args: [--branch, main]`); existing 8 bundled hooks (trailing-whitespace, end-of-file-fixer, check-yaml, check-json, check-added-large-files, check-merge-conflict, ruff/ruff-format, detect-secrets) preserved unchanged
- [ ] `requirements-dev.txt` exists and pins `pre-commit` (>=4.5,<5)
- [ ] `pre-commit install` succeeds; the resulting `.git/hooks/pre-commit` file exists and is executable (re-run after the config edit to pick up the new hook)
- [ ] `pre-commit run --all-files` runs to completion (proves config remains structurally valid after the new-hook addition)
- [ ] Hook behavioural test passes: invoking `pre-commit run no-commit-to-branch --all-files` on `main` produces a non-zero exit; on any other branch (we test on `agent/t-1-bootstrap-cleanup`) produces zero
- [ ] Existing bundled hooks (ruff, detect-secrets, etc.) NOT modified — scope discipline: T0.10 is scoped to the missing `no-commit-to-branch` hook only; any change to existing hooks belongs in its own plan

T-1.7:
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses as valid YAML after edit
- [ ] T-1.7 entry present with `id`, `tier`, `name`, `intent`, `depends_on`, `files_in_scope`, `exit_criteria`, `related_candidate_decisions: [CD.16]`, `effort: S`, `strategic: false`, `status: not_started`
- [ ] T-1.6 `depends_on` field includes `T-1.7`

Global:
- [ ] `.venv/Scripts/python.exe -m scripts.validate --pre` exits 0
- [ ] `.venv/Scripts/python.exe -m scripts.validate` (full presubmit, no flags) exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Old path eliminated from production code/docs | `git ls-files \| xargs grep -nE "docs/ROADMAP\.md" -- ':!docs/plans/briefings/*' ':!docs/SESSION_LOG_ARCHIVE.md' ':!docs/plans/PLAN-*.md' \|\| echo "OK_zero_hits"` | Prints `OK_zero_hits` | Locate the remaining reference and update per disambiguation rule |
| 2 | pre-deploy | strategic_review.prompt.md absent (precondition) | `test ! -f .github/prompts/strategic_review.prompt.md && echo ok` | Prints `ok` | File reappeared between rebase and verification — investigate git history and remove |
| 3 | pre-deploy | scheduled_agent_handler.py has no literal old-path reference | `grep -nE "docs/ROADMAP\.md" src/data/handlers/scheduled_agent_handler.py \|\| echo "OK_zero_hits"` | Prints `OK_zero_hits` | Patch the handler |
| 4 | pre-deploy | build_lambda packaging mentions the renamed file, not the old one | `.venv/Scripts/python.exe -c "import pathlib,re; src=pathlib.Path('scripts/build_lambda.py').read_text(encoding='utf-8'); assert 'docs/ROADMAP.md' not in src, 'old path still referenced'; assert ('ROADMAP-PRODUCT' in src) or ('ROADMAP-PLATFORM' in src), 'no new roadmap reference found'; print('ok')"` | Prints `ok` | Update build_lambda packaging list |
| 5 | pre-deploy | session_preflight resolves a non-unknown roadmap_phase | `.venv/Scripts/python.exe -m scripts.session_preflight && .venv/Scripts/python.exe -c "import json; r=json.load(open('logs/.preflight-report.json',encoding='utf-8')); phase=r['context']['roadmap_phase']; assert phase != 'unknown', f'phase still unknown'; print(f'phase={phase}')"` | Prints `phase=<resolved-value>` | Inspect `_extract_roadmap_phase` in session_preflight; ensure path constant points at the right file and parser matches the new format |
| 6 | pre-deploy | PROJECT_CONTEXT.md contains the disambiguation rule | `grep -cE "ROADMAP-PRODUCT\.md.*ROADMAP-PLATFORM\.yaml\|ROADMAP-PLATFORM\.yaml.*ROADMAP-PRODUCT\.md" docs/PROJECT_CONTEXT.md \| awk '{ if ($1 < 1) { print "missing"; exit 1 } else { print "ok" } }'` | Prints `ok` | Add the disambiguation paragraph to PROJECT_CONTEXT.md |
| 7 | pre-deploy | ROADMAP-PLATFORM.yaml parses; T-1.7 present; T-1.6 depends on T-1.7 | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); t17=next((i for i in d['tier_items'] if i['id']=='T-1.7'), None); assert t17, 'T-1.7 missing'; assert t17['status']=='not_started'; assert t17['effort']=='S'; assert 'CD.16' in t17['related_candidate_decisions']; t16=next(i for i in d['tier_items'] if i['id']=='T-1.6'); assert 'T-1.7' in t16['depends_on'], f't-1.6 depends_on={t16[\"depends_on\"]}'; print('ok')"` | Prints `ok` | Fix the T-1.7 entry or T-1.6 depends_on edit |
| 8 | pre-deploy | no-commit-to-branch hook entry present in config | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('.pre-commit-config.yaml',encoding='utf-8').read()); hooks=[h['id'] for r in d['repos'] for h in r['hooks']]; assert 'no-commit-to-branch' in hooks, f'no-commit-to-branch missing; got {hooks}'; hook=next(h for r in d['repos'] for h in r['hooks'] if h['id']=='no-commit-to-branch'); assert 'main' in (hook.get('args') or []), f'main not in args={hook.get(\"args\")}'; print('ok')"` | Prints `ok` | Add hook entry per Step 7 |
| 9 | pre-deploy | pre-commit config remains structurally valid (existing hooks still parseable + new hook accepted) | `pre-commit run --all-files \|\| echo "exit=$?"` | Either zero exit OR non-zero with hook output (NOT a config-parse error). A config-parse error shows up as `An error has occurred: InvalidConfigError` in stderr. | Inspect `.pre-commit-config.yaml` syntax; re-run with `--verbose` |
| 10 | pre-deploy | pre-commit installed; hook picked up by .git/hooks | `pre-commit install && test -x .git/hooks/pre-commit && echo ok` | Prints `ok` | Re-run `pre-commit install`; check for permission issues |
| 11 | pre-deploy | no-commit-to-branch passes on the agent branch | `.venv/Scripts/python.exe -c "import subprocess; r=subprocess.run(['pre-commit','run','no-commit-to-branch','--all-files'], capture_output=True, text=True); current_branch=subprocess.run(['git','branch','--show-current'], capture_output=True, text=True).stdout.strip(); assert current_branch != 'main', f'cannot test on main; current_branch={current_branch}'; assert r.returncode == 0, f'hook unexpectedly failed on non-main branch: rc={r.returncode} stdout={r.stdout[:300]}'; print(f'branch={current_branch} rc={r.returncode} ok')"` | Prints `branch=agent/t-1-bootstrap-cleanup rc=0 ok` | Inspect hook configuration; ensure `args: [--branch, main]` is set |
| 12 | pre-deploy | requirements-dev.txt exists and pins pre-commit | `.venv/Scripts/python.exe -c "import re,pathlib; t=pathlib.Path('requirements-dev.txt').read_text(encoding='utf-8'); assert re.search(r'^pre-commit\s*[><=]', t, re.M), 'pre-commit not pinned'; print('ok')"` | Prints `ok` | Add `pre-commit>=4.5,<5` to requirements-dev.txt |
| 13 | pre-deploy | validate.py --pre passes | `.venv/Scripts/python.exe -m scripts.validate --pre` | Exit 0 | Inspect failure output; if format-only, run `ruff format` and retry |
| 14 | pre-deploy | validate.py full presubmit passes | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Address whichever check fails; do not bypass |

## Constraints
- Decision 67 freeze: IMPLEMENTATION only. This plan is IMPLEMENTATION; freeze-compatible.
- Lambda build/deploy/smoke-test DEFERRED for the single Lambda-packaged file change (`src/data/handlers/scheduled_agent_handler.py`) per Decision 67 and the disabled-dispatcher state.
- No rescue agents or workaround loops (Decision 55). Verification failures cause the implementer to RCA and either fix or file a recommendation — no retry loops.
- Never edit on `main` (CLAUDE.md hard rule + `.claude/hooks/never_on_main.py`). Branch confirmed: `agent/t-1-bootstrap-cleanup`.
- Single Portal Invariant. No ops writes in this plan.
- Warehouse-as-source-of-truth invariant. No table writes; no reads from cache to write back.
- Authoritative pre-merge gate is remote CI (Decision 68). Local `validate.py --pre` advisory only.
- Decision 73 / planning skill exception categories: T-1.0 alignment is explicit (roadmap T-1.0). T0.10 alignment is explicit (roadmap T0.10). T-1.7 roadmap-edit alignment is meta — it's adding the roadmap item itself, which is a legitimate roadmap-maintenance action and is implicitly permitted (the planning skill flags as exception when intent is `ad_hoc_rec` or `user_explicit_out_of_scope`; this is closer to `user_explicit_out_of_scope` — the user explicitly directed adding T-1.7 in this planning session).

## Context
- **Rename history.** PR #335 (`plan(platform-roadmap)`) introduced `docs/ROADMAP-PLATFORM.yaml` and renamed `docs/ROADMAP.md` to `docs/ROADMAP-PRODUCT.md`. PR #336 (`feat(repo-cleanup-pre-t-1)`) deleted ceremony surfaces including `.github/prompts/strategic_review.prompt.md` and ported GEMINI.md rules to CLAUDE.md. Together these two PRs landed the roadmap rename + ceremony cleanup but did NOT sweep the downstream consumers — that sweep is T-1.0 and is the substantive content of this plan.
- **Disambiguation rule (to be persisted in PROJECT_CONTEXT.md).** When a consumer references the roadmap, the implementer applies this rule per call site:
  - Consumer needs product context (phases, milestones, market features, trading capabilities) → `docs/ROADMAP-PRODUCT.md`
  - Consumer needs platform context (tier_items, infrastructure, governance, candidate_decisions, AWS/Lambda topology) → `docs/ROADMAP-PLATFORM.yaml`
  - Consumer needs both (e.g. doc-freshness checking all roadmap content; documentation_update authoring across both) → reference both explicitly, with a short note explaining which dimension each addresses
- **T-1.7 design.** The new tier item names the config-split work as: split `config/` into `config/lambda/<lambda-name>/` (per-Lambda runtime payloads) and `config/<agent-consumed>/` subtrees (DQ rules, executor prompts, scheduling configs). Tied to CD.16 because the planning-skill rule for Lambda Deployment Assessment changes from "any `config/` change requires Lambda gating" to "only `config/lambda/<name>/` changes require gating for that Lambda." T-1.7 is added to T-1.6's `depends_on` so the per-Lambda enforcement registry has clean per-directory globs to consume.
- **T0.10 actual gap (correction during planning).** Initial scoping assumed `.pre-commit-config.yaml` did not exist. Mid-planning verification showed the file already exists with 8 hooks bundled: trailing-whitespace, end-of-file-fixer, check-yaml, check-json, check-added-large-files, check-merge-conflict, ruff/ruff-format, detect-secrets. The pre-commit framework itself is installed in the venv (`pre-commit 4.5.1`). The actual T0.10 gap is therefore narrower: (a) the `no-commit-to-branch` hook is missing — this is the specific main-branch-protection hook the roadmap calls out as the portable backup for `never_on_main`; (b) `pre-commit` is not pinned in any requirements file, so a fresh clone cannot reliably install it without out-of-band knowledge. This plan addresses both. The roadmap's T0.10 exit_criteria phrase "Bundled checks (ruff / secrets-scan) decision recorded as ratified or deferred CD" is interpreted post-discovery as already-ratified-by-existing-state: those checks have been in place; no CD authoring is needed in this plan.
- **Pre-commit T0.5 dependency.** The roadmap T0.10 exit_criteria mention `pre-commit install` being wired into the T0.5 session-start hook. T0.5 does not yet exist; this plan re-runs the install command (it persists across runs but needs to pick up the new hook) and documents the auto-install hand-off as a TODO that T0.5 will pick up. No regression risk — manual install persists in `.git/hooks/` once run, and any future clone runs `pre-commit install` once.
- **Lambda packaging change carries minimal risk.** The dispatcher Lambda is disabled (no scheduled invocations). The packaging change touches only the docs payload inside the Lambda zip; the handler code itself is updated to read the new filename but does not invoke any runtime behaviour the smoke-test currently lacks coverage for. Smoke-test deferral is therefore CD.16-compliant once ratified, and Decision-67-compliant now.
- **Per-call-site judgment is the riskiest interpretation step.** Some consumers (notably `documentation_update.prompt.md`, `doc-freshness.prompt.md`) almost certainly need both roadmaps. The implementer must read each file's context before substituting blindly — a global sed-style replacement that swaps every `docs/ROADMAP.md` for `docs/ROADMAP-PRODUCT.md` will be wrong for the platform-context consumers.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (currently `agent/t-1-bootstrap-cleanup`)
- [x] `docs/PROJECT_CONTEXT.md` read (during planning session)
- [x] `docs/DECISIONS.md` scanned for Decision 67 (freeze constraints) and Decision 68 (CI authority)
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable
- [x] `docs/ROADMAP-PLATFORM.yaml` T-1.0 / T0.10 entries read (source of truth for tier-item exit criteria)
- [x] Precondition verified: `.github/prompts/strategic_review.prompt.md` absent (rebased to origin/main)

## Ordered Execution Steps
1. **Add disambiguation rule to `docs/PROJECT_CONTEXT.md`** in a sensible section (e.g. directly after the existing "Instruction architecture" or "Operational data governance" subsection, or as a new short subsection "Roadmap references"). One short paragraph stating the three-case rule (product / platform / both). This rule is the policy applied in steps 2-4.
2. **Sweep `scripts/` references (3 files: `session_preflight.py`, `build_lambda.py`, plus any others surfaced by repository grep).** Critical: `session_preflight.py`'s `ROADMAP_FILE` constant and `_extract_roadmap_phase` extraction logic must point at the new file. `build_lambda.py`'s packaging copy list must include the renamed file(s). Treat the disambiguation rule per call site: `session_preflight` extracting `roadmap_phase` is product-context (matches the existing string-search-for-Phase-N pattern).
3. **Sweep `src/data/handlers/scheduled_agent_handler.py`.** Lambda-packaged. Update any string-literal path references. If the handler injects roadmap content into scheduled-agent prompts, decide per-agent which roadmap (likely both for doc-freshness and rec-curator agents).
4. **Sweep `.claude/`, `.agents/`, `.github/` instruction surfaces** by directory in turn. Apply disambiguation rule. The plan-critique skill's context-loading list is the highest-risk consumer — verify it loads cleanly after edit.
5. **Sweep `docs/`, `README.md`, `terraform/README.md` cross-references.** Most of these are narrative cross-references and will resolve cleanly to one or the other roadmap.
6. **Add T-1.7 entry to `docs/ROADMAP-PLATFORM.yaml`.** Insert in correct numeric order within the T-1 tier_items block. Use the structure documented in the Context section above. Update T-1.6's `depends_on` to include `T-1.7`.
7. **Add `no-commit-to-branch` hook** to the existing `.pre-commit-config.yaml`. Add to the existing `pre-commit/pre-commit-hooks` repo block (same `rev: v3.2.0`) as a new hook entry with `id: no-commit-to-branch` and `args: [--branch, main]`. Do NOT modify any other hook in the file — scope discipline.
8. **Create `requirements-dev.txt`** with `pre-commit>=4.5,<5` as the initial pinned entry. One-line file. Future dev-only dependencies (e.g. pytest plugins not used in CI smoke) can be added here in later plans.
9. **Re-run `pre-commit install`** to ensure the hook registry picks up the new `no-commit-to-branch` entry. Idempotent.
10. **Execute Verification Plan** — run each step 1-12. Loop on failures; for V2 unrecoverable failure (e.g. validate.py fails for a reason orthogonal to this plan), stop and RCA per Decision 55.
11. **Report:** what was implemented, verification results, any per-call-site disambiguation choices that warrant flagging for review.

## Work Areas (STRATEGIC plans only)
N/A — IMPLEMENTATION plan.
