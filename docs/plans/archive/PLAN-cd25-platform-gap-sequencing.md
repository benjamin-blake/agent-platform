# Plan

## Intent
Apply the already-ratified INTENT-pre-codegen-contract-ratification roadmap edits to `docs/ROADMAP-PLATFORM.yaml`, triage the six PRODUCT-surfaced `PLATFORM:GAP-*` references into concrete platform tier items, and rewrite the PRODUCT cross-roadmap edges + `known_platform_gaps[]` + narrative prose to point at the now-real ids -- closing the loop between INTENT v4 (PR #352, merged but not yet applied), the PRODUCT roadmap (which already references the proposed scaffolding by GAP slug), and the live PLATFORM YAML.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
claude/cd25-platform-gap-sequencing-gS1Ja

## Phase
T-1 governance / pre-codegen ritual application. This plan does not begin codegen; it lands the scaffolding (CD.25 + T-1.11/T-1.12 ritual + four GAP-absorption tier items + schema fields) that downstream codegen consumes.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add CD.25; add 16 new tier_items (T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7, T1.12, T1.14, T2.14, T3.5); renumber existing T1.12 (ci-rca) -> T1.13 with all references swept; add depends_on edges to 9 existing items (T0.13, T0.7a-c, T1.1, T1.3, T1.4, T3.1, T3.2); add `bootstrap_completion_exempt: true` to 17 legacy items (T-1.0..T-1.6, T0.6, T0.7a..c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14 -- 7 + 10 = 17) AND the new ritual items; migrate T4.1.decomposition_hints from list[str] to dict shape (planning grep confirmed T4.1 is the sole list-shaped holder; T1.5 carries no such field). |
| `docs/ROADMAP-PRODUCT.yaml` | Modify | Rewrite 33 `PLATFORM:GAP-*` references across 28 tier items in tier_items[].cross_roadmap_depends_on (five items hold two references each); rewrite 6 `known_platform_gaps[].intended_platform_tier_item: pending_triage` values to the resolved PLATFORM ids; rewrite 12+ narrative prose references (in `intent:`, `description:`, `reason:`, `agent_instructions:` blocks) including the two uppercase variants `PLATFORM:GAP-TCA-aggregation` at lines 1862 and 2502. |
| `scripts/platform_roadmap.py` | Modify | Add `TierItem.bootstrap_completion_exempt: bool = False`; add `TierItem.decision_required_before: list[str] \| None = None`; widen `TierItem.decomposition_hints` (currently undeclared, silently ignored) to a typed `dict \| None`; widen `CandidateDecision.decision_required_before` from `str \| None` to `list[str] \| str \| None`; add `CandidateDecision.bootstrap_allowance: bool = False`; declare every previously-undeclared YAML field per the audit step; guard `GateRuleParser.validate()` so it only fires on grammar-shaped string entries (skip list entries and prose); flip `model_config` from `extra="ignore"` to `extra="forbid"` ONLY on `TierItem` and `CandidateDecision` (per INTENT v4 Part 8A's explicit limitation). Leave all other classes at `extra="ignore"`. |
| `tests/test_platform_roadmap.py` | Modify | Add unit tests for the three new fields, the `decomposition_hints` dict shape, the widened `CandidateDecision.decision_required_before`, the `extra="forbid"` rejection of an unknown field, the bootstrap-exemption per-item coverage, and that the post-edit `docs/ROADMAP-PLATFORM.yaml` loads cleanly. |
| `tests/test_product_roadmap_schema.py` | Modify | Add an executable test asserting no value in any tier_item's `cross_roadmap_depends_on` matches `^PLATFORM:GAP-`, and that every value resolves to a real PLATFORM id (read PLATFORM yaml in the same test). |
| `docs/INTENT-pre-codegen-contract-ratification.md` | Modify | Append a single line under "Application Status" recording that PR-this-branch applies the Part 7/8 edits to the live YAML; cross-link the resulting PR. No semantic content edits. |

## Bundled Recommendations
None. `update_rec` / `file_rec` are unreachable in this remote execution environment (no AWS SSO). Any recommendations surfaced during execution must be filed in a follow-on session with SSO available.

## Acceptance Criteria
- [ ] `bin/venv-python -m scripts.platform_roadmap docs/ROADMAP-PLATFORM.yaml` exits 0 after all edits (Pydantic load + graph validation passes with `extra="forbid"` on TierItem and CandidateDecision).
- [ ] `bin/venv-python -m scripts.product_roadmap_schema docs/ROADMAP-PRODUCT.yaml` exits 0 after all edits.
- [ ] `bin/venv-python -m pytest tests/test_platform_roadmap.py tests/test_product_roadmap_schema.py -q` passes, including new tests.
- [ ] `bin/venv-python -m scripts.validate --pre` exits 0.
- [ ] No tier_item's `cross_roadmap_depends_on` contains a `PLATFORM:GAP-*` value (executable check below).
- [ ] No tier_item's `cross_roadmap_depends_on` contains a `PLATFORM:*` value that fails to resolve to a real id in PLATFORM yaml's `tier_items[].id` or `candidate_decisions[].id` (executable check below).
- [ ] CD.25 is present in PLATFORM `candidate_decisions[]` with `state: pending`, `bootstrap_allowance: true`, and `decision_required_before` as a list[str].
- [ ] T-1.11, T-1.12, T-1.13..T-1.19, T0.12.5, T0.12.6, T0.12.7, T1.12 (renumbered Class B ratification wave), T1.13 (relocated ci-rca methodology), T1.14 (reconciliation Lambda), T2.14 (broker secrets), T3.5 (TCA aggregation) all present in PLATFORM `tier_items[]`.
- [ ] No `tier_items[].id == T1.12` carries the prior "CI-RCA methodology contract" name; the renumbered slot `T1.13` is the new home; every reference to `T1.12` across `depends_on`, `gates`, `cross_tier_gates[].rule`, `related_candidate_decisions`, and prose blocks has been swept (executable check below).
- [ ] All 17 legacy exempt items (T-1.0..T-1.6, T0.6, T0.7a..c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14) AND the new ritual items (T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7) carry `bootstrap_completion_exempt: true`. Items NOT in this set carry `bootstrap_completion_exempt: false` (default) or omit the field.
- [ ] PRODUCT `known_platform_gaps[]` block: every entry's `intended_platform_tier_item` resolves to a real PLATFORM id (no `pending_triage` values remain).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | PLATFORM yaml loads under Pydantic with targeted forbid flip | `bin/venv-python -m scripts.platform_roadmap docs/ROADMAP-PLATFORM.yaml` | exit 0, no validation errors printed | If "extra fields not permitted" appears on TierItem or CandidateDecision, the field audit (Step 2) missed a key; grep the unrecognised field name across PLATFORM yaml and add to the appropriate model. Do not loosen the flip to work around. |
| 2 | [pre-deploy] | PRODUCT yaml loads | `bin/venv-python -m scripts.product_roadmap_schema docs/ROADMAP-PRODUCT.yaml` | exit 0 | If a `cross_roadmap_depends_on` references a non-existent PLATFORM id, fix the slug-to-id map (Context section). |
| 3 | [pre-deploy] | Schema unit tests pass | `bin/venv-python -m pytest tests/test_platform_roadmap.py tests/test_product_roadmap_schema.py -q` | green, including new cases | Diagnose specifically; do not skip failing tests. |
| 4 | [pre-deploy] | Sentinel slugs retired from PRODUCT cross-edges | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PRODUCT.yaml')); bad=[(t['id'],v) for t in (d.get('tier_items') or []) for v in (t.get('cross_roadmap_depends_on') or []) if isinstance(v,str) and v.startswith('PLATFORM:GAP-')]; assert not bad, f'GAP-* still in cross_roadmap_depends_on: {bad}'; print('cross_roadmap_depends_on clean')"` | prints `cross_roadmap_depends_on clean` | If non-empty, rewrite the residuals per the slug-to-id map. |
| 5 | [pre-deploy] | All PLATFORM:* edges resolve | `bin/venv-python -c "import yaml,re; pd=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); pids={i['id'] for i in (pd.get('tier_items') or [])}.union({c['id'] for c in (pd.get('candidate_decisions') or [])}); pp=yaml.safe_load(open('docs/ROADMAP-PRODUCT.yaml')); orph=[(t['id'],v) for t in (pp.get('tier_items') or []) for v in (t.get('cross_roadmap_depends_on') or []) if isinstance(v,str) and v.startswith('PLATFORM:') and re.sub(r'^PLATFORM:','',v) not in pids]; assert not orph, f'unresolved PLATFORM refs: {orph}'; print('all PLATFORM refs resolve')"` | prints `all PLATFORM refs resolve` | If non-empty, fix the offending mapping. |
| 6 | [pre-deploy] | T1.12 collision sweep complete | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); items={i['id']:i for i in d['tier_items']}; assert 'Class B' in items['T1.12']['name'], items['T1.12']['name']; assert 'CI-RCA' in items['T1.13']['name'], items['T1.13']['name']; refs=[(t['id'],fld,v) for t in d['tier_items'] for fld in ('depends_on','related_candidate_decisions') for v in (t.get(fld) or []) if v=='T1.12' and 'Class B' not in items.get(v,{}).get('name','')]+[(c['id'],'gates',v) for c in (d.get('candidate_decisions') or []) for v in (c.get('gates') or []) if v=='T1.12' and 'Class B' not in items.get(v,{}).get('name','')]+[(g['id'],'rule',g.get('rule','')) for g in (d.get('cross_tier_gates') or []) if 'T1.12' in (g.get('rule') or '') and 'Class B' not in items['T1.12']['name']]; assert not refs, f'orphan T1.12 refs (should point at T1.13 if pre-existing): {refs}'; print('T1.12 sweep OK')"` | prints `T1.12 sweep OK` | Logic note: after the rename the `'Class B' not in items['T1.12'].name` filter exits early on the cross_tier_gates branch (post-rename T1.12 name DOES contain 'Class B'), so this VP step primarily verifies the rename HAPPENED, not that every pre-existing reference was swept. Pre-Implementation Checklist Step 1's `grep -nE "T1\.12" docs/ROADMAP-PLATFORM.yaml` is the substantive catch for missed renumber sites; treat any line returned by that grep that isn't the new T1.12 entry or a depends_on already rewritten to T1.13 as an orphan. |
| 7 | [pre-deploy] | Bootstrap exemption set complete | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); ex={i['id'] for i in d['tier_items'] if i.get('bootstrap_completion_exempt')}; need={'T-1.0','T-1.1','T-1.2','T-1.3','T-1.4','T-1.5','T-1.6','T0.6','T0.7a','T0.7b','T0.7c','T0.8','T0.9','T0.11','T0.12','T0.13','T0.14','T-1.11','T-1.12','T-1.13','T-1.14','T-1.15','T-1.16','T-1.17','T-1.18','T-1.19','T0.12.5','T0.12.6','T0.12.7'}; missing=need-ex; extra=ex-need; assert not missing, f'missing exempt flag: {missing}'; assert not extra, f'unexpected exempt flag on: {extra}'; print('exempt set OK')"` | prints `exempt set OK` | If missing, add the flag; if extra, remove it (only the named set is exempt). |
| 8 | [pre-deploy] | CD.25 wired correctly | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); cd25=next((c for c in d['candidate_decisions'] if c['id']=='CD.25'), None); assert cd25, 'CD.25 missing'; assert cd25['state']=='pending', cd25['state']; assert cd25.get('bootstrap_allowance') is True, 'bootstrap_allowance not true'; drb=cd25.get('decision_required_before'); assert isinstance(drb, list) and drb, f'decision_required_before must be non-empty list: {drb!r}'; print('CD.25 OK')"` | prints `CD.25 OK` | If the field is a string, the migration to list[str] type in scripts/platform_roadmap.py is incomplete. |
| 9 | [pre-deploy] | No list-shaped decomposition_hints survives | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); bad=[i['id'] for i in d['tier_items'] if 'decomposition_hints' in i and not isinstance(i['decomposition_hints'], dict)]; assert not bad, f'list-shaped decomposition_hints: {bad}'; print('decomposition_hints shape OK')"` | prints `decomposition_hints shape OK` | Migrate the offender to dict shape. |
| 10 | [pre-deploy] | known_platform_gaps[] fully resolved AND targets exist in PLATFORM | `bin/venv-python -c "import yaml; pp=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); pids={i['id'] for i in (pp.get('tier_items') or [])}.union({c['id'] for c in (pp.get('candidate_decisions') or [])}); d=yaml.safe_load(open('docs/ROADMAP-PRODUCT.yaml')); pending=[g['id'] for g in (d.get('known_platform_gaps') or []) if g.get('intended_platform_tier_item')=='pending_triage']; bad=[(g['id'],g.get('intended_platform_tier_item')) for g in (d.get('known_platform_gaps') or []) if g.get('intended_platform_tier_item')!='pending_triage' and g.get('intended_platform_tier_item') not in pids]; assert not pending, f'pending_triage gaps: {pending}'; assert not bad, f'gaps point at non-existent PLATFORM ids: {bad}'; print('known_platform_gaps resolved and resolvable')"` | prints `known_platform_gaps resolved and resolvable` | Pending: rewrite the entry per the slug-to-id map. Bad: fix the typo in the chosen PLATFORM id. |
| 11 | [pre-deploy] | Full presubmit | `bin/venv-python -m scripts.validate --pre` | exit 0 | Diagnose per the specific check that fails. |

## Constraints
- AGENTS.md Temporary Operational Constraints: STRATEGIC plans are suspended -- this work is authored as a single larger IMPLEMENTATION plan per the freeze-override.
- AGENTS.md Temporary Operational Constraints: Lambda deployment is deferred (Decision 67); this plan does not touch Lambda-packaged files. The T1.12 (Class B ratification wave), T1.14 (reconciliation Lambda), and T3.5 (TCA aggregation) tier items being added carry `decision_required_before: ["CD.16"]` so they cannot start until CD.16 ratifies and the freeze lifts.
- Single Portal Invariant: no direct edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl`. This plan touches neither.
- Warehouse-as-source-of-truth: not applicable (no `OpsWriter.write()` paths).
- No rescue agents or workaround loops (Decision 55). If validation fails repeatedly, file a rec via a follow-on session, do not patch around.
- `extra="forbid"` discipline: applied ONLY to TierItem and CandidateDecision per INTENT v4 Part 8A. All other model classes remain `extra="ignore"`. Once flipped, any field-name typo in YAML on those two classes becomes a load error -- the field audit before the flip is non-optional.
- INTENT v4 fidelity: this plan applies INTENT v4 Parts 7, 8A, 8B, 8C without semantic deviation. The only departures are (a) renumbering INTENT v4's `T1.12` (Class B ratification wave) interaction-with-existing-T1.12 collision resolved by bumping the ci-rca item to `T1.13`, and (b) absorbing `GAP-t-1-12-product-contracts-schema-amendment` into T-1.12 itself (INTENT v4's framing places the schema amendment AT T-1.12; no separate tier_item invented).
- Planning-session triage additions (not INTENT-v4 canon): **T1.14** (reconciliation Lambda absorber), **T2.14** (broker Secrets Manager absorber), **T3.5** (TCA aggregation absorber) are dispositions decided in this planning session for the four PRODUCT-surfaced GAP slugs that INTENT v4 did not anticipate (`tca-aggregation`, `broker-secrets-manager`, `reconciliation-lambda`, `class-b-product-lambdas`; the last absorbs into INTENT v4's T1.12). Future archaeology should look here, not in INTENT v4, for the rationale behind those three ids. If a subsequent INTENT revision proposes alternative anchors, reconcile. <!-- pragma: allowlist secret -->

## Context

**Why this work exists.** INTENT-pre-codegen-contract-ratification.md was authored and merged to `main` (PR #352, commit `fd314c0`, 20 May 2026) but only added the INTENT document and its companion PLAN. The roadmap edits the INTENT specifies (CD.25, T-1.11 through T-1.19, T0.12.5/6/7, T1.12, depends_on edges, bootstrap_exemption expansion, schema field additions) were never applied to `docs/ROADMAP-PLATFORM.yaml`. Meanwhile, `docs/ROADMAP-PRODUCT.yaml` was authored against the INTENT's *proposed* state -- it references `PLATFORM:GAP-*` slugs that exist only as INTENT-side proposals, not as live tier item ids. This plan closes that gap.

**The six PLATFORM:GAP slugs and their dispositions:**

| GAP slug | Disposition | Resulting PLATFORM anchor |
|---|---|---|
| `cd25-contract-ritual` | Absorbed by INTENT v4 baseline application | `PLATFORM:CD.25` |
| `t-1-12-product-contracts-schema-amendment` | Absorbed into T-1.12 itself (INTENT v4 frames schema amendment as T-1.12's own scope; the GAP slug literally names T-1.12). No separate tier_item invented. | `PLATFORM:T-1.12` |
| `tca-aggregation` | New T3-tier observability item, Class A + B contracts, gated on CD.16 | `PLATFORM:T3.5` |
| `broker-secrets-manager` | New T2-tier infrastructure item, Class C contract | `PLATFORM:T2.14` |
| `reconciliation-lambda` | New T1-tier item, Class A + B contracts, gated on CD.16 | `PLATFORM:T1.14` |
| `class-b-product-lambdas` | INTENT v4's "T1.12 Class B ratification wave" (slot restored by renumbering colliding ci-rca item) | `PLATFORM:T1.12` |

**T1.12 collision resolution.** INTENT v4 (PR #352, merged 20 May 2026) proposed `T1.12` for the Class B Lambda ratification wave. PR #358 (after #352) then claimed `T1.12` for "CI-RCA methodology contract" without checking INTENT v4. Per the planning session's resolution: the ci-rca item is bumped to `T1.13` (the next free slot) and INTENT v4's canonical numbering is restored. The single known T1.12 cross-reference in the file at planning time was the depends_on at line ~1918; Step 1's re-grep + VP Step 6's comprehensive walk catch any references introduced between plan-write and implementation.

**Schema changes (full set).** Three transitions:

1. **`TierItem.decomposition_hints`**: currently undeclared on the model and silently dropped by `extra="ignore"`. The sole list-shaped holder is **T4.1** (planning grep confirmed; T1.5 carries no `decomposition_hints` field despite the schema-survey suggesting otherwise). After this plan: declared as `dict | None`, T4.1 migrated to dict shape. The flip to `extra="forbid"` then makes any future drift load-fail.

2. **`CandidateDecision.decision_required_before`**: currently `str | None`. CD.25 carries multiple prose entries per INTENT v4 Part 7 ("T0.13 may start", "T0.7a/b/c may start", etc.). Widen to `list[str] | str | None`. The existing string-form entries on CD.18 and CD.19 (current decision_required_before holders) stay as-is (string form remains valid). The `GateRuleParser.validate()` invocation in the model_validator (currently called on the string entry) must be guarded to only fire on grammar-shaped strings -- CD.25's prose entries are documentation, not gate-rule grammar.

3. **New optional fields** (pure additive):
   - `TierItem.bootstrap_completion_exempt: bool = False`
   - `TierItem.decision_required_before: list[str] | None = None`
   - `CandidateDecision.bootstrap_allowance: bool = False`

4. **`extra="forbid"` flip**: applied ONLY to `TierItem` and `CandidateDecision` per INTENT v4 Part 8A. The field audit (Step 2) must catch every currently-used YAML field on those two classes. Per the schema survey: `TierItem` extras include `note`, `progress_note`, `notes` (variant -- normalise to `note`), `user_action_required`, `minimum_verbs`, `consumer_fixups`, `rename_history`, `related_intents`, `related_decisions`, `completed_at`, `decomposition_hints` (type-changing in transition 1). `CandidateDecision` extras include `filed_via`, `narrowly_supersedes`, `supersedes_intents`, `supersedes_decisions`, `retires_intents`, `demotes_intents`, `discipline_points`, `enforcement_mechanism`. Each must be declared as `Optional` before the flip.

**Bootstrap exemption set policy.** Per the planning session: per-item `bootstrap_completion_exempt: true` is added to ALL 13 legacy items (T-1.0..T-1.6, T0.6, T0.7a..c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14) AND the new ritual items (T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7). The flag is the single source of truth; any narrative prose at document level becomes documentation-only. This eliminates the prose-vs-flag bifurcation the critique flagged.

**PRODUCT cleanup scope.** Beyond the 28 `cross_roadmap_depends_on` rewrites, this plan also handles:
- The `known_platform_gaps[]` block (PRODUCT yaml lines 4544-4562, 6 entries): each `intended_platform_tier_item: pending_triage` is rewritten to the resolved PLATFORM id (the block becomes a satisfied-gap audit trail rather than an open-gap list).
- Narrative prose references in `intent:`, `description:`, `reason:`, `agent_instructions:` blocks (approximately 12 instances across the file, plus 2 uppercase variants at lines 1862 and 2502): rewritten to the resolved PLATFORM id. The grep at planning time found `PLATFORM:GAP-cd25-contract-ritual` mentioned in narrative form at lines 59, 1222, and across ~10 `five_property_test_waiver` reason blocks (e.g., 3464, 3495, 3522, ...); each is mechanically rewritten to `PLATFORM:CD.25`. The uppercase `PLATFORM:GAP-TCA-aggregation` variants (lines 1862, 2502) are rewritten to `PLATFORM:T3.5` and the casing normalised.

**Why no DECISIONS.md entry.** This is a mechanical application of an already-ratified INTENT, not a new decision. The decision was filed implicitly via PR #352's merge.

**Known follow-on work (out of scope here):**
1. CI drift gate enforcement (INTENT v4 Part 8A T-1.12 exit criterion): `scripts/contracts.py` canonical enums for `change_class` vocabulary + amendment_log presence validation. Successor plan.
2. T-1.13 through T-1.19 implementation: the .md->.yaml conversions for the existing `docs/contracts/*.md` files. Eight separate atomic IMPLEMENTATION plans.
3. T0.12.5, T0.12.6, T0.12.7: Class A and Class C contract ratification REPORT-ONLY plans. Three separate REPORT-ONLY plans.
4. Product-domain Class A codegen: emit `src/schemas/*.py` from ratified contract YAMLs. This is part of T-1.12's own scope per the GAP-t-1-12 absorption decision; the implementation portion (codegen) lands as a successor IMPLEMENTATION plan once contracts ratify.
5. T1.12, T1.14, T2.14, T3.5: each is its own implementation work, blocked on CD.16 ratification (T1.12, T1.14, T3.5) or T2.1+T2.9 completion (T2.14).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently on `claude/cd25-platform-gap-sequencing-gS1Ja`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/INTENT-pre-codegen-contract-ratification.md` read in full (Parts 7, 8A, 8B, 8C).
- [ ] `docs/DECISIONS.md` skim: CD.16 (Lambda deploy gating), CD.17 (executor freeze), CD.25 status confirmed.
- [ ] All files in Scope table located and readable.
- [ ] T1.12 reference set re-greped immediately before edits (`grep -nE "T1\.12" docs/ROADMAP-PLATFORM.yaml`).
- [ ] PRODUCT `PLATFORM:GAP-*` reference count re-confirmed (`bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PRODUCT.yaml')); n=sum(1 for t in (d.get('tier_items') or []) for v in (t.get('cross_roadmap_depends_on') or []) if isinstance(v,str) and v.startswith('PLATFORM:GAP-')); print(n)"`) -- planning grep returned 33 references across 28 items; if the live count differs, refresh Step 12's enumeration before edits.
- [ ] Field audit re-run immediately before the `extra="forbid"` flip: walk every TierItem and CandidateDecision entry in the live YAML; collect the union of keys; cross-check against the Pydantic model's declared fields; declare any missing optional.
- [ ] `decomposition_hints` list-shape re-grep (`bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); print([i['id'] for i in d['tier_items'] if isinstance(i.get('decomposition_hints'), list)])"`) -- result should be `['T4.1']` only; if other items appeared, migrate them in Step 4 too.
- [ ] Acceptance Criteria understood and verifiable.

## Ordered Execution Steps

1. **Re-grep T1.12 references** in `docs/ROADMAP-PLATFORM.yaml`. Capture the full set so the renumber leaves no orphan. Also re-grep for list-shaped `decomposition_hints` -- planning expected only T1.5, but any new appearance must be caught now.

2. **Re-audit the Pydantic model field set** against the live `docs/ROADMAP-PLATFORM.yaml`. Build the exhaustive list of fields per `TierItem` and `CandidateDecision` entry that need declaring before the `extra="forbid"` flip. Compare against the Context section's audit list; add any field that snuck in between plan-write and implementation.

3. **`scripts/platform_roadmap.py` -- additive schema changes (no flip yet).**
   - Add `TierItem.bootstrap_completion_exempt: bool = False`.
   - Add `TierItem.decision_required_before: list[str] | None = None`.
   - Add `TierItem.decomposition_hints: dict | None = None` (newly typed; previously undeclared).
   - Declare every previously-undeclared TierItem field surfaced by Step 2's audit (e.g., `notes`, `user_action_required`, `minimum_verbs`, `consumer_fixups`, `rename_history`, `related_intents`, `related_decisions`). Each defaults to `None` or the appropriate sentinel.
   - Widen `CandidateDecision.decision_required_before` from `str | None` to `list[str] | str | None`.
   - Add `CandidateDecision.bootstrap_allowance: bool = False`.
   - Declare every previously-undeclared CandidateDecision field surfaced by Step 2's audit (e.g., `filed_via`, `narrowly_supersedes`, `supersedes_intents`, `supersedes_decisions`, `retires_intents`, `demotes_intents`, `discipline_points`, `enforcement_mechanism`).
   - Guard `GateRuleParser.validate()`: in the model_validator for `decision_required_before`, only invoke on entries that match the grammar-shape regex (or fall back to skipping non-grammar prose); leave existing string-form entries unaffected.

4. **`docs/ROADMAP-PLATFORM.yaml` -- T4.1 decomposition_hints migration.** Rewrite the existing `list[str]` entry on **T4.1** into the new dict shape `{split_by: ..., atomic_plans: [...], rationale: ...}`. Preserve content semantically. (Note: an earlier draft cited T1.5; live grep confirms T4.1 is the sole holder.)

5. **`docs/ROADMAP-PLATFORM.yaml` -- normalise `notes` -> `note`.** Two occurrences (T-1.8, T0.14). Mechanical rename; preserve content.

6. **`docs/ROADMAP-PLATFORM.yaml` -- add `CD.25`** to `candidate_decisions[]` per INTENT v4 Part 7:
   - `id: CD.25`
   - `title: Pre-codegen contract ratification for Class A / B / C contracts`
   - `state: pending`
   - `bootstrap_allowance: true`
   - `decision_required_before: [<the list of "T0.13 may start" entries per INTENT v4>]`
   - `gates: [T-1.11, T-1.12, T-1.13, ..., T0.12.5, T0.12.6, T0.12.7, T1.12]`
   - `detail: <INTENT v4 Part 7 prose, condensed to candidate-decision detail form>`
   - `related_candidate_decisions: [CD.1, CD.9, CD.10, CD.11, CD.12, CD.16, CD.17]`

7. **`docs/ROADMAP-PLATFORM.yaml` -- T1.12 collision renumber.** Rename the existing `T1.12` (CI-RCA methodology contract) to `T1.13` -- update its `id` field; then sweep every cross-reference (`depends_on`, `gates`, `cross_tier_gates[].rule`, `related_candidate_decisions`, narrative prose) and rewrite to `T1.13`. The single known cross-reference at planning time was the `[T3.3, T1.12]` depends_on at line ~1918; Step 1's re-grep + VP Step 6's walk catch anything new.

8. **`docs/ROADMAP-PLATFORM.yaml` -- insert the new tier_items.** In tier order:
   - T-1.11 (REPORT-ONLY ritual INTENT pointer; depends_on: []; bootstrap_completion_exempt: true)
   - T-1.12 (ritual enforcement: CI drift gate + preflight hook + roadmap edits + schema work + product-contracts schema amendment; strategic: true; depends_on: [T-1.11]; bootstrap_completion_exempt: true; decomposition_hints dict per INTENT v4 Part 8A; absorbs GAP-t-1-12-product-contracts-schema-amendment)
   - T-1.13..T-1.19 (one per existing `docs/contracts/*.md` file; depends_on: [T-1.12]; bootstrap_completion_exempt: true; efforts per INTENT v4 Part 8A round-3 H4)
   - T0.12.5 (ops Class A ratification; depends_on: [T-1.12, T0.12, T0.12.7]; bootstrap_completion_exempt: true)
   - T0.12.6 (telemetry Class A ratification; strategic: true; depends_on: [T-1.12, T0.12, T0.12.7]; bootstrap_completion_exempt: true; decomposition_hints dict)
   - T0.12.7 (Class C cross-system invariants; depends_on: [T-1.12]; bootstrap_completion_exempt: true)
   - T1.12 (Class B ratification wave; strategic: true; depends_on: [T-1.12, T0.12.5, T0.12.7]; decision_required_before: ["CD.16"]; decomposition_hints dict; absorbs GAP-class-b-product-lambdas)
   - T1.14 (reconciliation Lambda + ops_reconciliations Class A contract; depends_on: [T0.6, T0.12.5]; decision_required_before: ["CD.16"]; absorbs GAP-reconciliation-lambda)
   - T2.14 (broker Secrets Manager + Class C credential-routing contract; depends_on: [T2.1, T2.9]; absorbs GAP-broker-secrets-manager)
   - T3.5 (TCA aggregation Lambda + cost-curves Class A contract; depends_on: [T0.7a, T0.12.5, T3.4]; decision_required_before: ["CD.16"]; absorbs GAP-tca-aggregation)

9. **`docs/ROADMAP-PLATFORM.yaml` -- existing-item depends_on edges per INTENT v4 Part 8B.** Add edges:
   - T0.13 depends_on += [T0.12.5]
   - T0.7a, T0.7b, T0.7c, T1.1, T1.3, T1.4 depends_on += [T1.12]
   - T3.1, T3.2 depends_on += [T0.12.6]

10. **`docs/ROADMAP-PLATFORM.yaml` -- add `bootstrap_completion_exempt: true` per-item, for the full set.** Apply the flag to: T-1.0, T-1.1, T-1.2, T-1.3, T-1.4, T-1.5, T-1.6, T0.6, T0.7a, T0.7b, T0.7c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14, T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7. Items outside this set omit the field (default False). The prose narrative block (if any) becomes documentation; the per-item flag is the single source of truth.

11. **`scripts/platform_roadmap.py` -- targeted `extra="forbid"` flip.** Change `model_config = ConfigDict(extra="ignore")` to `extra="forbid"` ONLY on `TierItem` and `CandidateDecision`. All other classes (Document, NorthStar, GateHelper, FoundationItem, CrossTierGate, OpenQuestion, KnownGap, NorthStarPrinciple, RoadmapDocument) stay `extra="ignore"`. If load fails on TierItem or CandidateDecision, return to Step 2 (audit incomplete); declare the missing field.

12. **`docs/ROADMAP-PRODUCT.yaml` -- rewrite cross_roadmap_depends_on.** For every tier item with a `PLATFORM:GAP-*` value, apply the slug-to-id map from Context. 28 items per the planning grep: D.fast.1/2/3, D.lake.1/2/3/4/5/6/7, E.env.4/5/6/8, L1.alpha.1/2, L2.pc.1/2/10, L3.exec.1/4/5/6/7/11, L4.ops.1, MVP.1/4. Mechanical; preserve list ordering and any non-GAP entries.

13. **`docs/ROADMAP-PRODUCT.yaml` -- rewrite `known_platform_gaps[]`.** For each of the 6 entries (lines 4544-4562), rewrite `intended_platform_tier_item` from `pending_triage` to the resolved PLATFORM id per the slug-to-id map. The block becomes a satisfied-gap audit trail.

14. **`docs/ROADMAP-PRODUCT.yaml` -- rewrite narrative prose references.** All non-`cross_roadmap_depends_on` occurrences of `PLATFORM:GAP-*` (in `intent:`, `description:`, `reason:`, `agent_instructions:` blocks). Approximately 12 instances per the planning grep, plus the two uppercase variants at lines 1862 and 2502. Each is rewritten to the corresponding `PLATFORM:<resolved-id>` form. Casing normalised.

15. **`tests/test_platform_roadmap.py` -- new tests.** Cover:
    - `bootstrap_completion_exempt` accepts True/False; defaults False.
    - `decision_required_before` on TierItem accepts list[str] or None.
    - `decision_required_before` on CandidateDecision accepts list[str], str, or None.
    - `bootstrap_allowance` on CandidateDecision accepts True/False; defaults False.
    - `decomposition_hints` rejects list (now-invalid type) and accepts dict shape.
    - `extra="forbid"` rejects an unknown field on TierItem (assert ValidationError with `bogus_field: 1`).
    - `extra="forbid"` rejects an unknown field on CandidateDecision (same).
    - `extra="ignore"` is preserved on other classes (assert load succeeds with an unknown field on, e.g., NorthStar or FoundationItem).
    - Bootstrap-exemption per-item coverage assertion: load PLATFORM yaml, assert the set of items with `bootstrap_completion_exempt: true` matches the canonical expected set verbatim.
    - End-to-end: `docs/ROADMAP-PLATFORM.yaml` loads cleanly post-edit.

16. **`tests/test_product_roadmap_schema.py` -- sentinel-slug + edge-resolution tests.** Two new tests:
    - `test_no_platform_gap_in_cross_edges`: walk every `tier_items[].cross_roadmap_depends_on` value in `docs/ROADMAP-PRODUCT.yaml`; assert none match `^PLATFORM:GAP-`.
    - `test_platform_cross_edges_resolve`: load `docs/ROADMAP-PLATFORM.yaml` in the same test; assert every `PLATFORM:<id>` reference in PRODUCT's `cross_roadmap_depends_on` resolves to a real PLATFORM `tier_items[].id` or `candidate_decisions[].id`.

17. **`docs/INTENT-pre-codegen-contract-ratification.md` -- application status note.** Append one line under an "Application Status" heading (create if absent): "PR <this-branch> applies Parts 7, 8A, 8B, 8C edits to `docs/ROADMAP-PLATFORM.yaml`; PRODUCT yaml cross-edges rewritten to resolved PLATFORM ids." No semantic edits.

18. **Execute Verification Plan** -- run each step in the table. Loop until pass. If a step fails unrecoverably, stop and analyse root cause per Decision 55; do not patch around.

19. **Report**: summarise what was implemented (counts of items added, edges rewired, fields added, references rewritten), verification results, and the five open follow-on plans named in Context.

## Work Areas (STRATEGIC plans only)
N/A -- this plan is IMPLEMENTATION.
