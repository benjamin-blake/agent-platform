# Plan

## Intent
Reflect the merged exploratory design record `docs/INTENT-multi-product-platform.md` in the platform and product roadmaps so the multi-product direction (one unified DuckLake operational data plane keyed by a `project_id` origin dimension; a code/repo axis that separates only at the cross-employer IP boundary) is tracked as governance state. This advances NS.4 (the repo is for agents) by keeping the roadmaps the single navigable source of platform/product direction, without committing any unbuilt work as active.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-multi-product-roadmap.md

## Phase
Platform roadmap governance edit (T-tier meta-work). Product context: Phase 1 Core Infrastructure complete; this edit touches roadmap framing only, no product tier_item.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/ROADMAP-PLATFORM.yaml | Modify | Generalize `known_gaps` KG.1 per OD-5 (N products; fix stale `.md` -> `.yaml`; PRESERVE the platform/product boundary sense Decision 78/CD.31 reference). Add `candidate_decision` CD.32 (multi-product topology, holds OD-1..OD-5 + the repo-topology open question feeding OD-3). Add `known_gap` KG.14 (multi-product enforcement substrate unbuilt). |
| docs/ROADMAP-PRODUCT.yaml | Modify | Add a `known_gaps` entry recording this is the TRADING product roadmap -- one of N -- with reaper-tools/dbt-daywork prospective and owning their own roadmaps; cross-reference the INTENT doc + platform KG.1/CD.32. |
| docs/PROJECT_CONTEXT.md | Modify | Fix the stale roadmap-disambiguation rule + quick-reference table: "product context" must point at `docs/ROADMAP-PRODUCT.yaml` (canonical), not the superseded `docs/ROADMAP-PRODUCT.md`. |
| docs/plans/PLAN-multi-product-roadmap.md | Create | This plan artefact. |

## Bundled Recommendations
None. (STRATEGIC/executor frozen per Decision 67; no executor recommendations are filed by this plan.)

## Infrastructure Dependencies (if applicable)
None. No `.tf` files in scope. No Lambda-packaged files in scope (`config/agent/` is not Lambda-packaged; the roadmap YAMLs and PROJECT_CONTEXT.md are not packaged).

## Acceptance Criteria
- [ ] KG.1 in `docs/ROADMAP-PLATFORM.yaml` is generalized from a single "trading product roadmap" to N products, points at `docs/ROADMAP-PRODUCT.yaml` (canonical) and `docs/INTENT-multi-product-platform.md`, and notes it enacts OD-5.
- [ ] KG.1 retains an explicit sentence stating the platform/product boundary is unchanged and is the one Decision 78/CD.31 reference for the Iceberg (product/market-data) vs DuckLake (platform ops/telemetry) split -- so generalizing the roadmap-location wording does NOT move the data-format boundary. (Dual-sense preserved.)
- [ ] CD.31's `discipline_points` cross-reference to "the KG.1 platform/product boundary" still resolves (CD.31 text is unchanged; KG.1 still expresses that boundary).
- [ ] A new `candidate_decision` CD.32 exists with `state: pending`, anchors to `docs/INTENT-multi-product-platform.md`, enumerates OD-1..OD-5, cross-references the migration-INTENT `project_id` stack (T0.12a / T0.7a-c / T0.15 / `config/project_registry.yaml`) as substrate-not-to-duplicate, records the monorepo-vs-separate-private-repos open question feeding OD-3, and marks the unbuilt enforcement work (egress gate, day-job onboarding interlock, COALESCE gate, rollback/freeze) as gated -- NOT eligible active work.
- [ ] A new `known_gap` KG.14 exists pointing at CD.32 and the INTENT doc's Build-state reality section.
- [ ] `docs/ROADMAP-PRODUCT.yaml` has a `known_gaps` entry recording it as the trading product roadmap (one of N) with reaper-tools/dbt-daywork prospective, cross-referencing the INTENT doc + platform KG.1/CD.32.
- [ ] `docs/PROJECT_CONTEXT.md` roadmap-disambiguation rule + quick-reference table point "product context" at `docs/ROADMAP-PRODUCT.yaml`.
- [ ] No new active `tier_items` are added to either roadmap (direction is tracked via known_gaps/candidate_decisions only).
- [ ] Both roadmaps pass their Pydantic schema validation and the full `validate.py` presubmit is green (taxonomy lint included).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Validate platform roadmap parses + schema-valid after KG.1/CD.32/KG.14 edits | `bin/venv-python -m scripts.platform_roadmap` | Exits 0; prints roadmap state with no schema error | Pydantic ValidationError -> fix the offending field (CandidateDecision is `extra="forbid"`; only use allowed fields) |
| 2 | pre-deploy | Validate product roadmap parses + cross-roadmap resolution after the known_gaps edit | `bin/venv-python -c "from pathlib import Path; from scripts.product_roadmap import load; load(Path('docs/ROADMAP-PRODUCT.yaml'), platform_path=Path('docs/ROADMAP-PLATFORM.yaml')); print('product OK')"` | Prints `product OK` | ValidationError or duplicate-id error -> fix the new known_gaps entry id/shape |
| 3 | pre-deploy | Confirm KG.1 dual-sense preserved: the platform/product boundary sentence survives and still names Decision 78 | `bin/venv-python -c "import re,sys; t=open('docs/ROADMAP-PLATFORM.yaml').read(); blk=t[t.index('id: KG.1'):t.index('id: KG.2')]; sys.exit(0 if ('platform/product boundary' in blk and 'Decision 78' in blk) else 1)"` | Exits 0 (boundary phrase + Decision 78 reference both present in the KG.1 block) | Exit 1 -> KG.1 rewrite dropped the boundary sense; restore the explicit sentence |
| 4 | pre-deploy | Confirm CD.31's reference to the KG.1 boundary is intact (unchanged) | `grep -c "KG.1 platform/product boundary" docs/ROADMAP-PLATFORM.yaml` | >= 1 (CD.31 discipline_points reference preserved) | 0 -> CD.31 was inadvertently edited; revert CD.31, it must stay unchanged |
| 5 | pre-deploy | Confirm CD.32 + KG.14 exist and CD.32 anchors to the INTENT doc and lists the Open Decisions | `bin/venv-python -c "import sys; t=open('docs/ROADMAP-PLATFORM.yaml').read(); sys.exit(0 if ('id: CD.32' in t and 'id: KG.14' in t and 'INTENT-multi-product-platform.md' in t and 'OD-5' in t and 'OD-1' in t) else 1)"` | Exits 0 | Exit 1 -> add the missing id/anchor/OD reference |
| 6 | pre-deploy | Confirm product roadmap records "one of N" framing + INTENT cross-ref | `bin/venv-python -c "import sys; t=open('docs/ROADMAP-PRODUCT.yaml').read(); sys.exit(0 if ('INTENT-multi-product-platform.md' in t and 'reaper-tools' in t and 'dbt-daywork' in t) else 1)"` | Exits 0 | Exit 1 -> add/extend the product known_gaps entry |
| 7 | pre-deploy | Confirm PROJECT_CONTEXT disambiguation now points product context at the .yaml and no longer at the bare superseded .md | `bin/venv-python -c "import sys,re; t=open('docs/PROJECT_CONTEXT.md').read(); s=t[t.index('Roadmap reference disambiguation'):]; ok=('ROADMAP-PRODUCT.yaml' in s) and (re.search(r'Product context[^\n]*ROADMAP-PRODUCT\\.md', s) is None); sys.exit(0 if ok else 1)"` | Exits 0 (product-context rule references the `.yaml`; the bare `.md` product-context pointer is gone) | Exit 1 -> finish updating the disambiguation rule + quick-reference table |
| 8 | pre-deploy | Confirm no new active tier_items were added to either roadmap | `git diff origin/main -- docs/ROADMAP-PLATFORM.yaml docs/ROADMAP-PRODUCT.yaml \| grep -E "^\+\s*- id: (T[0-9.-]+\|L[0-9]\|D\.(fast\|lake)\|E\.env\|MVP)" \|\| echo "NO_NEW_TIER_ITEMS"` | Prints `NO_NEW_TIER_ITEMS` | Any added tier_item line printed -> remove it; direction is tracked as known_gaps/candidate_decisions only |
| 9 | pre-deploy | Authoritative local gate: full presubmit (both roadmap schema checks + taxonomy lint + format) | `bin/venv-python -m scripts.validate` | Suite passes (no FAIL lines); "Environment/phase taxonomy lint" and both roadmap schema checks PASS | Any FAIL -> fix per the named check; re-run |

## Constraints
- IMPLEMENTATION plan only -- STRATEGIC is suspended (Decision 67 / AGENTS.md Temporary Operational Constraints). File no executor recommendations.
- Track direction only; commit no unbuilt work as active. The `project_id` mechanism, egress gate, COALESCE gate (T0.15), day-job onboarding interlock, and rollback/freeze path are ALL unbuilt and gated by OD-1/OD-2 + the unbuilt `project_id` stack -- they are recorded as known_gaps/candidate_decisions, never as eligible tier_items.
- Preserve the KG.1 dual sense: its literal roadmap-location text AND the "platform/product boundary" sense that Decision 78/CD.31 reference for the Iceberg-vs-DuckLake split. Do NOT edit CD.31; it must keep referencing the boundary.
- Do NOT duplicate the migration-INTENT `project_id` roadmap work (T0.12a etc.) -- cross-reference `docs/INTENT-aws-migration-platform-evolution.md` Part 2 instead.
- Respect the Decision-77 reserved environment/phase vocabulary. The two roadmap YAMLs are allowlisted in `validate_environment_taxonomy`, but this PLAN file and any prose are NOT -- avoid `<product-phase> environment` / `<platform-tier> phase` adjacency in new text.
- `CandidateDecision` schema is `extra="forbid"`: only use allowed fields (id, title, detail, gates, state, decision_required_before, bootstrap_allowance, filed_via, narrowly_supersedes, supersedes_*, retires_intents, demotes_intents, discipline_points, enforcement_mechanism). Use `state: pending` + `filed_via: pending_log_decision_lambda` (the CD.30 convention for unratified candidates).
- No rescue agents or workaround loops (Decision 55).
- No emojis, no em-dashes; plain ASCII hyphens (AGENTS.md).
- Never edit on `main`; work on the harness session branch.

## Context
- **Source of truth:** `docs/INTENT-multi-product-platform.md` (merged via PR #57) is REPORT-ONLY and deliberately exploratory. It EXTENDS, and does not supersede, the monorepo + `project_id` commitment in `docs/INTENT-aws-migration-platform-evolution.md` Part 2. Its only deferred concrete roadmap edit is OD-5 (the KG.1 wording). This plan enacts OD-5 and registers the rest as tracked direction.
- **Decisions to cite (from the Step 6a decision-scout gate, Verdict NO_FLAGS):** Decision 78 (KG.1 platform/product boundary -> Iceberg/DuckLake split; the dual-sense preservation is load-bearing), Decision 67 (IMPLEMENTATION-only / no executor recs), Decision 77 (reserved environment/phase vocabulary; taxonomy lint). RELATED: Decision 48 (V1 tier is correct for docs/.yaml/.md with no runtime effect), Decision 76 (web merge mechanics for landing the plan), Decision 75 (frame-lock: the repo-topology question is SURFACED as an open question, not committed). Decisions 50/51/56/69 are superseded by Decision 78 -- do not cite as governing.
- **Decision-scout NOTE (mitigated):** Decision 78 and CD.31 both anchor the Iceberg-vs-DuckLake split to the literal phrase "the KG.1 platform/product boundary." Generalizing KG.1 risks silently dissolving that named anchor. Mitigation: VP steps 3 and 4 are load-bearing -- they assert the boundary sentence + Decision 78 reference survive in KG.1 and that CD.31's reference is unchanged.
- **Canonical product-roadmap file:** `docs/ROADMAP-PRODUCT.yaml` is canonical (its header: "Canonical product roadmap"); `docs/ROADMAP-PRODUCT.md` carries a SUPERSEDED banner and is a retained recovery artefact -- do NOT edit it. The PROJECT_CONTEXT.md disambiguation rule still points "product context" at the superseded `.md`; that stale reference is fixed here (in scope per human direction).
- **Repo-topology open question (human-raised):** whether to keep the monorepo or move to per-product separate private repos to reduce agent context bloat. Registered inside CD.32 feeding OD-3 (the split-repo-revisit trigger). Key framing to capture: the data/identity axis stays unified regardless of repo topology (N repos can still write one DuckLake keyed by `project_id`), so this touches only the code/repo axis; per-directory `CLAUDE.md` is only a partial mitigation because the shared operational corpus (DECISIONS.md, the roadmaps, the recs log) does not shard with directory scope; and the counter-cost of separate repos is extracting/duplicating the co-located platform tooling.
- **Preflight state at planning time:** branch `claude/multi-product-roadmap-plan-JcVGY`, main 0 behind / 0 ahead (no divergence, no rebase needed), venv ok, creds ok, no uncommitted changes. Telemetry WARN (Athena `sessions` table-not-found; Iceberg reader ACCESS_DENIED falling back to Athena successfully) is unrelated to a docs-only roadmap edit. `non_automatable_softcap_breached=true` but per-rec review is suspended (Decision 73) and this plan files no recs.
- **ID allocation:** platform max ids are CD.31 and KG.13, so new entries are CD.32 and KG.14 (collision-checked: neither exists). Product known_gaps use dotted-suffix ids (e.g. `KG.multi_asset`); use a unique id such as `KG.multi_product_topology`.
- **Schema notes:** both roadmap YAMLs are Pydantic-validated by `validate.py` (platform schema check is full-tier only; product runs in `--pre` and full). Both are allowlisted in the taxonomy linter.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (Decisions 78, 77, 75, 67; CD.31)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`docs/ROADMAP-PLATFORM.yaml` -- generalize KG.1 (enacts OD-5).** Rewrite the `gap` and `notes`:
   - `gap`: change from "Trading product roadmap is in a sibling document (docs/ROADMAP-PRODUCT.md)" to a product-agnostic statement: this platform roadmap is product-agnostic and each product owns its own product roadmap.
   - `notes`: (a) trading's canonical product roadmap is `docs/ROADMAP-PRODUCT.yaml` (the `.md` is superseded); reaper-tools and dbt-daywork are prospective products that would own their own roadmaps when real; (b) an EXPLICIT sentence preserving the dual sense: "This platform/product boundary -- platform-tier concerns here vs product roadmaps elsewhere, and correspondingly DuckLake for platform ops/telemetry vs Iceberg for product/market-data -- is the boundary Decision 78 (CD.31) references; generalizing the roadmap-location wording to N products does not move that data-format boundary"; (c) a pointer to `docs/INTENT-multi-product-platform.md` and a note that this enacts its OD-5. Do NOT touch CD.31.
2. **`docs/ROADMAP-PLATFORM.yaml` -- add `candidate_decision` CD.32.** Append to `candidate_decisions` (mirror the CD.30 unratified shape): `id: CD.32`; `title: Multi-product platform topology (unified project_id data plane + IP-boundary-only repo axis)`; `state: pending`; `filed_via: pending_log_decision_lambda`; `detail`: anchor to `docs/INTENT-multi-product-platform.md` as the exploratory record; summarize the two orthogonal axes (unified DuckLake ops data plane keyed by `project_id`; code/repo split only at the cross-employer IP boundary); enumerate the doc's Open Decisions OD-1..OD-5 as the ratification gate; cross-reference `docs/INTENT-aws-migration-platform-evolution.md` Part 2 and its `project_id` stack (T0.12a / T0.7a-c / T0.15 / `config/project_registry.yaml`) as the build substrate to AVOID duplicating; record the human-raised monorepo-vs-separate-private-repos open question feeding OD-3, with the framing from the Context section (axis-orthogonality; per-directory `CLAUDE.md` partial mitigation; tooling-extraction counter-cost); and state explicitly that the unbuilt enforcement work (egress gate, day-job onboarding interlock, COALESCE gate T0.15, rollback/freeze) is gated by OD-1/OD-2 + the unbuilt `project_id` stack and is NOT an eligible active tier_item. Keep to `CandidateDecision` allowed fields only (`extra="forbid"`).
3. **`docs/ROADMAP-PLATFORM.yaml` -- add `known_gap` KG.14.** Append to `known_gaps`: `id: KG.14`; `gap`: the multi-product enforcement substrate is unbuilt (project_id mechanism, egress gate, COALESCE gate, day-job interlock, rollback/freeze); `notes`: tracked in CD.32 and the Build-state reality section of `docs/INTENT-multi-product-platform.md`; do not treat as active roadmap work.
4. **`docs/ROADMAP-PRODUCT.yaml` -- add a `known_gaps` entry.** Append (e.g. `id: KG.multi_product_topology`): `gap`: this is the TRADING product roadmap -- one of N products hosted on the platform; `notes`: reaper-tools and dbt-daywork are prospective products that would own their own product roadmaps; the platform operational data plane is shared and distinguished by `project_id`; cross-reference `docs/INTENT-multi-product-platform.md` and platform KG.1 / CD.32. Keep vocabulary taxonomy-clean.
5. **`docs/PROJECT_CONTEXT.md` -- fix the roadmap-disambiguation rule + quick-reference table.** In the "Roadmap reference disambiguation" section, change the "Product context" bullet to reference `docs/ROADMAP-PRODUCT.yaml` (canonical) instead of `docs/ROADMAP-PRODUCT.md`; update the quick-reference table row "Product roadmap (phases, milestones)" link to `docs/ROADMAP-PRODUCT.yaml`. Optionally add a half-line noting the `.md` is a superseded recovery artefact. Do not otherwise restructure the section.
6. **Execute Verification Plan** -- run each step 1-9 in order. Loop until all pass. These are all static/pre-deploy checks; there is no V3 harness. If step 9 (`validate.py`) reports a FAIL, fix per the named check and re-run from the failing step.
7. **Report:** what was implemented (the four file edits), and the verification results (each VP step's outcome, especially steps 3-4 confirming the KG.1 dual-sense preservation).
