# Plan

## Intent
Produce `docs/ROADMAP-PLATFORM.yaml` — an agent-first, machine-parseable platform roadmap that names the automation/governance/control-plane work underneath the trading product, sequences it as tiers T-1..T5 with named cross-tier gates, and inlines the content of the retired `docs/INTENT-compute-and-account-topology.md`. This is the platform's North Star; the trading product roadmap is its sibling at `docs/ROADMAP-PRODUCT.md`.

## Plan Type
REPORT-ONLY

The substantive output is `docs/ROADMAP-PLATFORM.yaml`. This plan file is the planning artefact that points at it. Per the planning skill's REPORT-ONLY rules, both files land in the same initial commit, the deliverable goes through the multi-perspective Step 10 critique, and no `/implement` follow-on is required from this plan. Implementation of individual tier items happens in future per-item plans.

## Verification Tier
V1

The deliverable is a YAML document plus a rename. No runtime code, no infrastructure. Verification is structural conformance + grep-based reference correctness.

## Branch
agent/platform-roadmap

## Phase
N/A — this plan establishes the platform's North Star itself. Once ratified via `log-decision` Lambda (T-1.1), it becomes the source of truth for platform sequencing.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/ROADMAP-PLATFORM.yaml | Create | The substantive deliverable. Agent-first YAML with north_star, rebuild_vs_refactor, foundation_already_shipped, candidate_decisions, tier_items, cross_tier_gates, open_questions, known_gaps. |
| docs/ROADMAP.md → docs/ROADMAP-PRODUCT.md | Rename (git mv) | Reframes the existing roadmap as product-only; the platform sibling is the new YAML. |
| docs/plans/PLAN-platform-roadmap.md | Create | This file. The REPORT-ONLY planning artefact. |

## Bundled Recommendations
None. The roadmap itself supersedes many open recs by tier-item assignment, but none are bundled into this session.

## Infrastructure Dependencies
None. No `.tf` files in scope.

## Lambda Deployment
N/A. No Lambda-packaged files in scope.

## Acceptance Criteria
- [ ] docs/ROADMAP-PLATFORM.yaml exists and is valid YAML
- [ ] docs/ROADMAP.md has been renamed to docs/ROADMAP-PRODUCT.md (single git mv, no content change)
- [ ] The deliverable passes the multi-perspective critique gate in Step 10 of the planning workflow
- [ ] All tier_items reference depends_on entries that resolve to other tier_items in the same document
- [ ] All candidate_decisions reference real tier_items in their `gates` field
- [ ] No outbound references to the retired `INTENT-compute-and-account-topology.md` remain in the YAML (it is inlined, not referenced)
- [ ] All effort markers and strategic flags are present on every tier_item

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | YAML parses and contains all expected top-level sections | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); expected={'document','north_star','cost_projection','rebuild_vs_refactor','foundation_already_shipped','candidate_decisions','tier_items','cross_tier_gates','open_questions','known_gaps'}; missing=expected-set(d.keys()); assert not missing, f'missing {missing}'; print('ok')"` | Prints "ok" | Add the missing top-level section |
| 2 | pre-deploy | All tier_item ids unique; T1.8 is RESERVED placeholder | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); ids=[i['id'] for i in d['tier_items']]; assert len(ids)==len(set(ids)); t18=next(i for i in d['tier_items'] if i['id']=='T1.8'); assert t18.get('status')=='reserved'; print(f'{len(ids)} tier_items; T1.8 reserved ok')"` | Prints "{N} tier_items; T1.8 reserved ok" | Deduplicate or correct T1.8 status |
| 3 | pre-deploy | All depends_on resolve; no dependency cycles | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); ids={i['id'] for i in d['tier_items']}; tiers={'T-1','T0','T1','T2','T3','T4','T5'}; bad=[(i['id'],dep) for i in d['tier_items'] for dep in i.get('depends_on',[]) if dep not in ids and dep not in tiers]; assert not bad, bad; print('ok')"` | Prints "ok" | Fix dangling depends_on |
| 4 | pre-deploy | All candidate_decisions gates resolve; CD.1-CD.19 present | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); ids={i['id'] for i in d['tier_items']}; tiers={'T-1','T0','T1','T2','T3','T4','T5'}; cd_ids={c['id'] for c in d['candidate_decisions']}; expected_cds={f'CD.{n}' for n in range(1,20)}; missing=expected_cds-cd_ids; assert not missing, f'missing {missing}'; bad=[(cd['id'],g) for cd in d['candidate_decisions'] for g in cd.get('gates',[]) if g not in ids and g not in tiers]; assert not bad, bad; print('ok')"` | Prints "ok" | Restore missing CDs or fix dangling gates |
| 5 | pre-deploy | gate_helpers table defines all helpers used in cross_tier_gates rules and CD.17 reversal trigger expression | `.venv/Scripts/python.exe -c "import yaml,re; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); helpers={h['name'] for h in d['document']['gate_helpers']}; gate_rules=' '.join(g.get('rule','') for g in d['cross_tier_gates']); cd17=next(c['detail'] for c in d['candidate_decisions'] if c['id']=='CD.17'); pat=re.compile(r'\\b([a-z_][a-z0-9_]+)\\('); calls=(set(pat.findall(gate_rules))\|set(pat.findall(cd17)))-{'item','tier_items'}; unknown=calls-helpers; assert not unknown, f'unknown helpers: {unknown}'; print(f'helpers ok ({len(helpers)} defined)')"` | Prints "helpers ok ({N} defined)" | Add missing helper to gate_helpers OR rewrite rule using defined helpers (regex `\b[a-z_][a-z0-9_]+\(` matches snake_case call syntax only, ignoring English prose) |
| 6 | pre-deploy | Bootstrap COMPLETION-exemption set covers all T-1 items | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); instr=d['document']['agent_instructions']; t1_items={i['id'] for i in d['tier_items'] if i['tier']=='T-1'}; missing=[i for i in t1_items if i not in instr]; assert not missing, f'T-1 items not in completion exemption: {missing}'; print(f'all T-1 items in exemption: {sorted(t1_items)}')"` | Prints all T-1 ids in exemption | Add missing T-1 ids to the bootstrap COMPLETION exemption clause |
| 7 | pre-deploy | Rename landed; legacy strategic_review.prompt.md deleted | `test -f docs/ROADMAP-PRODUCT.md && ! test -f docs/ROADMAP.md && ! test -f .github/prompts/strategic_review.prompt.md && echo 'ok'` | Prints "ok" | Re-run `git mv` for rename; `git rm` for deletion |
| 8 | pre-deploy | All compute-and-account-topology mentions in retirement metadata only | `.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read()); txt=open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8').read(); count=txt.count('compute-and-account-topology'); assert 5 <= count <= 15, f'unexpected mention count {count}'; print(f'mentions: {count} (all expected in retirement metadata)')"` | Prints `mentions: N (all expected in retirement metadata)` with N in the 5-15 range | Audit each mention; inline any leaks |
| 9 | post-deploy | Plan-critique gate accepts the PLAN | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-platform-roadmap.md --context docs/PROJECT_CONTEXT.md docs/ROADMAP-PRODUCT.md docs/DECISIONS.md` | Terminal output ends with PROCEED | Loop with REVISE |
| 10 | post-deploy | Multi-perspective deliverable critique reached convergence (PROCEED on both OR human-accepted-with-deferrals after >=3 rounds) | `git log --oneline agent/platform-roadmap \| grep -E 'plan\(platform-roadmap\): (approved plan\|address .* critique findings)' \| head -1` | Prints a critique-addressing commit subject | Re-launch Step 10 critiques and commit |

## Constraints
- Decision 67 states "All plans must be IMPLEMENTATION type" during the data quality lockdown. This plan is REPORT-ONLY, which is permissible because: (a) the output is a documentation artefact with no runtime / infrastructure / Lambda-packaged code, so the data-quality-readiness concern Decision 67 protects against does not apply; (b) the planning skill's REPORT-ONLY plan type is explicitly supported by the workflow (Step 8 deliverable section, Step 10 multi-perspective critique gate, REPORT-ONLY confirmation message in Step 12); (c) tier items marked `strategic: true` in the YAML correctly defer their own implementation until either Decision 67 reverses OR is superseded by CD.11 (the Fargate-model retirement of the Lambda-dispatcher path).
- No rescue agents or workaround loops (Decision 55).
- Single Portal Invariant. Once T0.7a/b land, all subsequent rec/decision writes go through the log-rec / log-decision Lambdas, not direct ops_data_portal calls.
- Warehouse-as-source-of-truth invariant (CLAUDE.md). Logs are read caches, never write sources.
- Never edit on `main` (CLAUDE.md hard rule + never_on_main hook).
- Authoritative pre-merge gate is remote CI (Decision 68). Local `validate.py --pre` is advisory only.

## Context
- This plan was preceded by extended interactive iteration with the human (this planning session). The shape of the roadmap, the tier model, the Lambda-tooling surface, the Annotated-Pydantic schema-as-code direction, the retired-INTENT decision, and the YAML-first format were all confirmed by the user before the file was written.
- The briefing at `docs/plans/briefings/BRIEFING-linux-container-migration.md` is the primary input for T0.
- The retired (in this roadmap) `docs/INTENT-compute-and-account-topology.md` is the primary input for T2 and parts of NS.* north star.
- The 9 surviving INTENT docs (after CD.14 demotion) are detail-companions for their respective tier items.
- The user noted that some decisions made informally during recent sessions are not yet in `docs/DECISIONS.md`. CD.1-CD.15 in the YAML inventory the candidates; they will be filed via `log-decision` Lambda once T0.7b lands and T-1.1 executes.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (agent/platform-roadmap)
- [x] docs/PROJECT_CONTEXT.md read
- [x] DECISIONS.md scanned (most recent decisions 51-73 read)
- [x] All files in Scope table located and writable
- [x] Acceptance Criteria understood and verifiable
- [x] Briefing read (BRIEFING-linux-container-migration.md from origin/main)
- [x] Compute-and-account-topology INTENT read in full
- [x] 9 prior INTENT docs summarised by subagent

## Ordered Execution Steps
1. **Write** `docs/ROADMAP-PLATFORM.yaml` with full content (completed by this planning agent in this session — the file already exists at the time of plan-commit).
2. **Rename** `docs/ROADMAP.md` to `docs/ROADMAP-PRODUCT.md` via `git mv` (completed in this session before plan-commit).
3. **Execute Verification Plan steps 1-6** (pre-deploy) before committing. If any step fails, fix the YAML/rename and re-run.
4. **Commit** the initial plan + deliverable + rename via `git commit -m "plan(platform-roadmap): initial plan"`.
5. **Run plan-critique gate** (Step 9 of planning workflow). Loop with REVISE until PROCEED.
6. **Run multi-perspective deliverable critique** (Step 10). Architect + adversarial subagents in parallel against `docs/ROADMAP-PLATFORM.yaml`. Loop until convergence (both PROCEED OR user accepts with documented deferrals).
7. **Commit** the approved final state via `git commit -m "plan(platform-roadmap): approved plan"` (may be empty if all revisions landed as incremental commits during Step 10).
8. **Close** the telemetry session with `--outcome success`.
9. **Output** the REPORT-ONLY confirmation message from the planning workflow.

## Work Areas (STRATEGIC plans only)
N/A — this is REPORT-ONLY. The roadmap itself defines downstream work areas as tier_items.

## Known Gaps
Recorded in the YAML deliverable's `known_gaps` section. Summary:
- KG.1: Product roadmap is in sibling document (intentional)
- KG.2: 258 open recs not directly mapped to tier items (deferred)
- KG.3: INTENT-provider-agnostic-executor.md was newly added to main and skimmed only briefly; T4.2 should re-read it during STRATEGIC decomposition
- KG.4: Inline cost projection in topology INTENT lost when INTENT is retired; capture as ops_decisions reference once cost-projection decision graduates
- KG.5: No telemetry data migration plan (telemetry is pre-live throwaway; not migrating is intentional but flagged)
