# Plan

## Intent
Land `scripts/product_roadmap.py` (Pydantic structural validator) plus presubmit
and session-preflight wiring for `docs/ROADMAP-PRODUCT.yaml`, so the canonical
product roadmap is structurally enforced before merge. This closes the
agent-first invariant gap (CD.13) for PRODUCT the same way PLATFORM:T-1.5
closed it for PLATFORM. Bound together with the in-flight YAML reorganisation
on this branch so the artefact and its validator merge as a single PR.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
claude/convert-roadmap-yaml-Vdlhv  (UNUSUAL: explicit user override — do NOT
branch from main; layer this work on top of the existing audit-driven
reorganisation of docs/ROADMAP-PRODUCT.yaml. See Context section.)

## Phase
Cross-cutting — agent-first artefacts invariant (CD.13). Parallels PLATFORM
tier T-1 (T-1.5 architectural template). No PLATFORM tier_item alignment
required; bypasses tier-eligibility check via the planning skill's
`user_explicit_out_of_scope` soft-warn exception category.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/product_roadmap.py` | Create | ProductRoadmapDocument Pydantic schema, loader, layer-shortcut + tier-shortcut resolver, cross-roadmap resolver (PLATFORM tier_item / GAP / CD), gate-rule grammar validator (inherits PLATFORM helpers + PRODUCT-local helpers), reverse-index computation, ProductRoadmapState class for preflight |
| `scripts/validate.py` | Modify | Add `validate_product_roadmap()` mirroring `validate_platform_roadmap()` at line 1598; wire into `main()` call list at line 1899 |
| `scripts/session_preflight.py` | Modify | Add `product_roadmap` block to preflight report alongside existing `platform_roadmap` block; include `platform_consumers` reverse-index map |
| `docs/ROADMAP-PRODUCT.yaml` | Modify | (a) Add top-level `known_platform_gaps:` list (6 entries — one per PLATFORM:GAP-* reference currently in the file). (b) For each non-exempt tier_item missing `five_property_test`, add a `five_property_test_waiver:` block with `reason` and `will_attest_when` fields. Exempt items: those where `status == "complete"` (regardless of layer). This is the broadened exemption rule -- see Context "five_property_test waiver decision" for why the narrower `layer == platform_infra` second condition was dropped after critique surfaced L0.5 (status=complete, layer=lab_offline) as a real edge case. Under the broadened rule: 5 items exempt (L0.1, L0.2, L0.3, L0.5, L0.6); 30 items need waivers. |
| `tests/test_product_roadmap.py` | Create | Schema and grammar tests: malformed YAML rejection, missing required fields, duplicate ids, dangling intra-roadmap `depends_on`, cycle detection (direct and layer-shortcut), gate-rule grammar (unknown helper, arity mismatch), cross-roadmap resolution in all three forms (PLATFORM tier_item / GAP / CD), missing five_property_test without waiver = fail, waiver schema validation, retired/reserved PLATFORM ref rejection, reverse-index correctness on a fixture pair |
| `tests/test_product_roadmap_state.py` | Create | ProductRoadmapState helpers: eligible_items, compute_blocked, layer_complete, resolve_depends_on (including layer-shortcut), active_layer, strategic_pending_items, platform_consumers map |
| `tests/test_session_preflight_product_roadmap.py` | Create | Preflight integration: product_roadmap block shape, platform_consumers emission when /plan starts on a PLATFORM tier_item, degradation when PRODUCT YAML is malformed |
| `tests/fixtures/product_roadmap/__init__.py` | Create | Empty package marker |
| `tests/fixtures/product_roadmap/minimal_platform.yaml` | Create | Tiny PLATFORM fixture (4 tier_items, 2 CDs, gate_helpers block) for cross-roadmap resolution tests |
| `tests/fixtures/product_roadmap/minimal_product.yaml` | Create | Tiny PRODUCT fixture (4 tier_items, 2 CDs, known_platform_gaps with 1 entry, gate_helpers with 1 PRODUCT-local helper) referencing the minimal_platform fixture in all three forms |

## Bundled Recommendations
None. (Aligned-rec search returned 0 hits against keywords: product_roadmap,
product-roadmap, five_property, cross_roadmap, platform_consumers,
PLATFORM:GAP, roadmap validator, roadmap schema.)

## Acceptance Criteria
- [ ] `bin/venv-python -m scripts.validate` exits 0 with `docs/ROADMAP-PRODUCT.yaml` in its current state (after waiver additions for the 30 non-exempt items missing five_property_test: 1 L0 + 5 D.fast + 8 D.lake + 11 E.env + 5 MVP).
- [ ] `bin/venv-python -m scripts.validate --pre` exits 0 with same state, AND includes the product-roadmap schema check in its output. This deliberately diverges from the platform-roadmap check's current placement (full-tier only) -- see Step 2's `--pre` wiring instructions for the rationale.
- [ ] Injecting a duplicate tier_item id into `docs/ROADMAP-PRODUCT.yaml` causes `bin/venv-python -m scripts.validate` to exit non-zero with a "Duplicate" error message.
- [ ] Injecting a dangling intra-roadmap `depends_on` causes validate to exit non-zero with "does not resolve".
- [ ] Injecting a dangling `cross_roadmap_depends_on: ["PLATFORM:T999.0"]` causes validate to exit non-zero with a cross-roadmap resolution failure.
- [ ] Injecting `cross_roadmap_depends_on: ["PLATFORM:GAP-unregistered"]` (where the slug is not in known_platform_gaps) causes validate to exit non-zero.
- [ ] Removing a `five_property_test` block from a non-exempt tier_item without adding a waiver causes validate to exit non-zero with a "five_property_test required" message.
- [ ] `bin/venv-python -m scripts.session_preflight` produces `logs/.preflight-report.json` containing a top-level `product_roadmap` key whose value has `next_eligible`, `in_progress`, `blocked`, `strategic_pending`, `active_layer`, `platform_tier_item_consumers`, `platform_gap_consumers`, `platform_cd_consumers` fields. The reverse-index is split into three namespace-typed maps (not one mixed map) so downstream readers don't have to inspect key prefixes -- see Context "platform_consumers namespace policy".
- [ ] `platform_tier_item_consumers` is a dict keyed by PLATFORM tier_item id with values being lists of PRODUCT tier_item ids that cross_roadmap_depends_on that PLATFORM id; correctness asserted against the live YAML pair (at least one PLATFORM id has more than one PRODUCT consumer; e.g. `PLATFORM:T0.13` is currently consumed by L0.1, L0.2, L0.3, L0.4). `platform_gap_consumers` and `platform_cd_consumers` follow the same shape for their respective namespaces.
- [ ] `bin/venv-python -m pytest tests/test_product_roadmap.py tests/test_product_roadmap_state.py tests/test_session_preflight_product_roadmap.py -v` exits 0 with all tests green.
- [ ] `bin/venv-python -m scripts.test_coverage_checker` exits 0 (every new source file has corresponding test coverage of all new code).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | Load current PRODUCT YAML through new validator | `bin/venv-python -c "from scripts.product_roadmap import load; load('docs/ROADMAP-PRODUCT.yaml')"` | Exits 0; no exception printed | If ValidationError: missing waivers, dangling refs, or schema field mismatch. Re-read the failure path and either fix the validator field shape or add the missing waiver/gap entry to the YAML. |
| 2 | pre-deploy | Live YAML loads via main loader entry point and exposes reverse-index | `bin/venv-python -m scripts.product_roadmap --check docs/ROADMAP-PRODUCT.yaml --platform docs/ROADMAP-PLATFORM.yaml` | Prints "PASS" and a one-line summary "platform_consumers: N entries"; exits 0 | If ImportError: confirm `from scripts.platform_roadmap import load as load_platform` works. If empty reverse-index: walk a known cross-ref item and trace why it didn't accumulate. |
| 3 | pre-deploy | Full presubmit including new check | `bin/venv-python -m scripts.validate` | "Product roadmap schema validation" section appears and reports "PASS"; full validate exits 0 | If new section absent: confirm `validate_product_roadmap()` is wired into `main()` call list. If FAIL: same root-cause path as Step 1. |
| 4 | pre-deploy | Fast-tier presubmit includes new check | `bin/venv-python -m scripts.validate --pre` | "Product roadmap schema validation" section appears and reports "PASS"; --pre exits 0 in well under 5 seconds | If absent: confirm the new check is registered in both code paths (not behind a full-tier-only gate). |
| 5 | pre-deploy | Negative: duplicate id rejection | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestIdUniqueness -v` | All tests in class pass | If any test fails: the duplicate-detection branch in the model_validator isn't firing; trace via single-test rerun with `-s`. |
| 6 | pre-deploy | Negative: cycle detection | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestCycleDetection -v` | All tests pass | If cycle test passes against a real cycle, the DFS gray-set logic isn't tracking layer-shortcut expansion correctly. |
| 7 | pre-deploy | Negative: dangling cross-roadmap ref | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestCrossRoadmapResolution -v` | All tests pass — covers PLATFORM tier_item, GAP, and CD forms plus dangling for each | If any tier_item/GAP/CD form passes a dangling input: the per-form validator branch is missing or short-circuiting. |
| 8 | pre-deploy | Negative: five_property_test enforcement | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestFivePropertyEnforcement -v` | All tests pass — covers (a) missing-block-without-waiver rejection, (b) exempt-item passes, (c) waiver-with-required-fields passes, (d) waiver missing fields rejected | If exempt-item path fails: the exemption predicate (`status == "complete"`, no layer condition -- broadened rule) is wrong; verify both a platform_infra-complete fixture AND a lab_offline-complete fixture both pass through the exemption path. If waiver path fails: waiver model is mis-shaped (check that both `reason` and `will_attest_when` are required non-empty strings). |
| 9 | pre-deploy | Negative: gate-rule grammar | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestGateRuleGrammar -v` | All tests pass — covers unknown helper, arity mismatch on inherited PLATFORM helper, arity mismatch on PRODUCT-local helper, valid combined rule | If PRODUCT-local helpers aren't recognised: confirm document.gate_helpers (with scope='product_local') is merged with inherited PLATFORM helpers at validation time. |
| 10 | pre-deploy | Reverse-index correctness | `bin/venv-python -m pytest tests/test_product_roadmap.py::TestReverseIndex -v` | All tests pass — fixture pair has known PLATFORM ids consumed by known PRODUCT ids; assertion compares computed map to expected dict | If wrong: walk a single fixture entry's cross_roadmap_depends_on by hand and trace what platform_consumers picked up. |
| 11 | pre-deploy | State helpers | `bin/venv-python -m pytest tests/test_product_roadmap_state.py -v` | All tests pass — eligible_items, compute_blocked, layer_complete (including layer-shortcut aggregates D and E), active_layer, strategic_pending_items | If layer-shortcut aggregate fails (e.g. "D" should resolve to all D.fast + D.lake items): the shortcut regex needs both per-layer (D.fast) and aggregate (D) handling. |
| 12 | pre-deploy | Preflight integration | `bin/venv-python -m pytest tests/test_session_preflight_product_roadmap.py -v` | All tests pass — product_roadmap block present in report, platform_consumers populated, malformed-YAML degrades gracefully (returns dict with error key) | If preflight crashes: confirm the try/except mirrors `platform_roadmap.compute_state_dict` pattern. |
| 13 | pre-deploy | End-to-end preflight emits new block | `bin/venv-python -m scripts.session_preflight` | `logs/.preflight-report.json` contains a top-level `product_roadmap` key whose value has `next_eligible`, `in_progress`, `blocked`, `strategic_pending`, `active_layer`, `platform_tier_item_consumers`, `platform_gap_consumers`, `platform_cd_consumers` sub-keys (three split namespace maps, not one mixed map); verifiable via `bin/venv-python -m scripts.product_roadmap --check-preflight-report logs/.preflight-report.json` | If the helper script is missing: add it to scripts/product_roadmap.py as the `--check-preflight-report` CLI subcommand (assertion: all 8 expected sub-keys exist with the right types). |
| 14 | pre-deploy | Test coverage check | `bin/venv-python -m scripts.test_coverage_checker` | Exits 0 | If non-zero: a new source file lacks 100% line coverage on new code. Re-read tests/CLAUDE.md "Coverage policy" and add missing test cases. |
| 15 | pre-deploy | Full presubmit final pass | `bin/venv-python -m scripts.validate` | Exits 0 across all checks | If any other validator started failing: the new code touched a shared path. Triage from the failing-check output. |

## Constraints
- IMPLEMENTATION plan only — STRATEGIC plans suspended per AGENTS.md Temporary
  Operational Constraints (Decision 67 / CD.17 freeze).
- No Lambda code touched -> no Lambda Deployment Assessment section needed,
  no `DEFERRED:` execution step required.
- No `.tf` files touched -> no Infrastructure Dependencies section needed.
- All Python invocations via `bin/venv-python`.
- ASCII-only — no emojis, no em dashes (use ASCII hyphen).
- No `python -c` one-liners in acceptance/verification commands beyond Step 1
  of the VP (which is a single targeted load-check; Windows Git Bash handles
  short single-quoted -c invocations correctly). Tests use module dispatch.
- No rescue agents or workaround loops (Decision 55).
- Branch override is deliberate; do NOT switch to main or create a new
  `agent/{slug}` branch. The `never_on_main` hook permits edits on this branch.

## Context
- **CD.13 invariant**: agent-first artefacts are structurally validated.
  PLATFORM closed this for itself via T-1.5 (`scripts/platform_roadmap.py` +
  RoadmapDocument Pydantic schema, wired into validate.py). PRODUCT YAML
  currently has no equivalent validator -> silent field drops, dangling
  references, malformed edits slip past CI. Merging the in-flight
  reorganisation without the validator puts main in the same pre-T-1.5
  state PLATFORM was in.
- **Architectural template**: `scripts/platform_roadmap.py` (model
  structure, GateRuleParser, PlatformRoadmapState, compute_state_dict).
  `scripts/session_preflight.py` (line 1193: how platform_roadmap is wired
  into the preflight report). `scripts/validate.py` lines 1598-1631 (the
  validate_platform_roadmap wire pattern).
- **PRODUCT YAML shape differences from PLATFORM**: top-level keys include
  `four_layer_model`, `three_tier_data_architecture`, `environments`,
  `evaluation_metrics`, `minimum_viable_v1`, `promotion_funnel`,
  `candidate_decisions_research_pool`, `retired_items`, `out_of_product_scope`
  (none present in PLATFORM). Tier values are L0/L1/L2/L3/L4/D.fast/D.lake/
  E.env/MVP (layer-tier, not platform-tier). Candidate-decisions reference
  layer-shortcuts (`L0..L4`, `D`, `D.fast`, `D.lake`, `E`, `E.env`, `MVP`)
  where `D` and `E` are aggregates spanning their sub-tiers. tier_items
  carry richer fields: `layer`, `contract_gates`, `environment_scope`,
  `validation_lens`, `five_property_test`, `deferred`, `deferred_note`,
  `owning_layer`.
- **Cross-roadmap references**: `cross_roadmap_depends_on` carries
  `PLATFORM:<id>` strings in three valid forms:
  (a) `PLATFORM:T<x>.<y>` -> must resolve to a real PLATFORM tier_item id;
  (b) `PLATFORM:GAP-<slug>` -> must resolve to an entry in PRODUCT's
  `known_platform_gaps` registry; (c) `PLATFORM:CD.<n>` -> must resolve to
  a real PLATFORM candidate_decision id. Current YAML has 25 unique
  cross-refs spanning all three forms (6 GAPs, 4 CDs, 15 tier_items); all
  resolve cleanly against current PLATFORM state.
- **Reverse-index motivation**: when /plan starts on a PLATFORM tier_item
  (e.g. T0.7b), preflight currently shows nothing about the downstream
  PRODUCT consumers that depend on T0.7b. The reverse-index lets preflight
  print "PLATFORM:T0.7b is consumed by N product tier_items: [L3.exec.4,
  L4.ops.2, ...]" -> first-class drift visibility before the agent edits
  T0.7b in a way that breaks the consumers.
- **platform_consumers namespace policy**: the reverse-index is split
  into three namespace-typed maps (`platform_tier_item_consumers`,
  `platform_gap_consumers`, `platform_cd_consumers`) rather than one
  mixed map keyed by mixed-prefix strings (T*/GAP-*/CD.*). Rationale:
  the downstream preflight consumer that emits "PLATFORM:Tx.y is
  consumed by N product tier_items" only operates on tier_item ids; a
  mixed map would force every read site to inspect key prefixes. Three
  maps are the cleaner downstream surface, and the namespace split
  makes the data shape self-documenting.
- **five_property_test waiver decision**: 35 of 73 tier_items currently
  lack the attestation block. The bootstrapping pattern adopted (per
  architect recommendation, user approved) is structural-exemption-plus-
  explicit-waiver: items where `status == "complete"` (broadened rule,
  no layer condition) are structurally exempt; all other items must
  carry either a real five_property_test block OR a
  `five_property_test_waiver: {reason, will_attest_when}` block.
  Rationale: missing fields look identical to fields-not-yet-authored;
  the waiver formalises the gap as queryable state. This avoids the
  cargo-cult risk of agent-generated retrospective attestations on
  shipped state and keeps the validator landable today.

  **Why the rule was broadened from `status == complete AND layer ==
  platform_infra` to just `status == complete`**: the original narrower
  rule was authored on the assumption that "completed L0 items" map
  1:1 to "platform_infra layer items," but L0.5 has
  `layer: lab_offline` (a different EXISTING-COMPLETE class -- a
  research lab surface that's shipped). Under the narrower rule, L0.5
  would have needed a waiver with an incoherent `will_attest_when` --
  it's already complete, so it cannot transition to a state that would
  trigger attestation. Broadening to `status == complete` eliminates
  the boundary case cleanly and preserves the same principled
  rationale (retrospective attestation has low signal value regardless
  of which layer the item shipped in). Exempt set under broadened rule:
  L0.1, L0.2, L0.3, L0.5, L0.6 (5 items). Non-exempt set needing
  waivers: 30 items (1 L0 + 5 D.fast + 8 D.lake + 11 E.env + 5 MVP).
- **known_platform_gaps registry shape**: top-level YAML list, each entry
  `{id: GAP-<slug>, description: <str>, intended_platform_tier_item:
  pending_triage | <platform tier_item id>}`. Registry is in-file (not a
  separate loader) for self-containment. OQ.1 (the PLATFORM:GAP-* triage
  REPORT-ONLY follow-up plan) is where richer triage state lands.
- **fail vs warn on retired/reserved PLATFORM refs**: hard-fail. Currently
  T1.8 is the only reserved PLATFORM item; zero PRODUCT items consume it,
  so the rule lands clean.
- **validate.py --pre inclusion**: include. The schema check is pure
  Python, sub-second; the fast-tier budget is not at risk.
- **Branch posture**: `claude/convert-roadmap-yaml-Vdlhv` already carries
  the audit-driven reorganisation (Checkpoints 1-4). Plan filename is
  `docs/plans/PLAN-product-roadmap-schema.md` rather than
  `PLAN-convert-roadmap-yaml-Vdlhv.md` because the filename should
  describe the work content, not the existing branch slug. `find_plan.py`
  will not auto-resolve from the branch name; the implementing session
  must pass `--plan docs/plans/PLAN-product-roadmap-schema.md` explicitly
  when invoking /implement.
- **No related ci_rca recs** (preflight `ci_rca_recs == []`).
- **Cross-roadmap degradation in --pre is a known partial-coverage
  gap, not a defect of this plan**: PRODUCT validation in --pre runs
  but PLATFORM validation does NOT (the platform check is currently
  full-tier-only and this plan deliberately does not promote it). If
  PLATFORM YAML is malformed at --pre time, PRODUCT's cross-roadmap
  resolver returns `platform_doc=None`, emits a `WARNING: skipping
  cross-roadmap resolution -- PLATFORM YAML failed to load (<error>)`
  to STDERR (NOT stdout, so it surfaces visibly in --pre output rather
  than being mistaken for normal PASS output), and proceeds with
  intra-PRODUCT validation only. Full presubmit will catch the
  PLATFORM issue. A separate follow-up plan promoting PLATFORM's
  schema check to --pre would close this gap; out of scope for this
  plan to keep the --pre divergence rationale tightly scoped.
- **Out-of-scope follow-ups documented for clarity** (do NOT scope creep):
  PLATFORM:GAP-* triage REPORT-ONLY plan (OQ.1), CD.25 contract-ratification
  implementation, alignment-rec auto-filing hook ("PLATFORM edit announces
  itself"), contract-ratification ceremony on platform-exposed surfaces,
  within-layer lexicographic ordering of tier_items, the future
  hard-fail-on-status-transition ratchet for waivered items.

## Pre-Implementation Checklist
- [ ] Branch confirmed: `claude/convert-roadmap-yaml-Vdlhv` (NOT main; do
      NOT switch to main or create agent/{slug} per explicit user override)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (CD.13, CD.16, CD.17 in particular)
- [ ] All files in Scope table located and readable
- [ ] `scripts/platform_roadmap.py` read end-to-end (the architectural
      template every new file mirrors)
- [ ] `scripts/session_preflight.py` lines 1110-1240 read (the wire pattern
      for the preflight report dict)
- [ ] `scripts/validate.py` lines 1598-1635 and 1899 read (validate
      function pattern + main() wiring)
- [ ] `tests/test_platform_roadmap.py` and
      `tests/test_session_preflight_platform_roadmap.py` read (test
      structure to mirror)
- [ ] `tests/CLAUDE.md` read (coverage policy, mock exhaustion, acceptance
      command rules)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `scripts/product_roadmap.py`** with the following structure
   (mirrors `scripts/platform_roadmap.py`):
   - Module-level constants: `_SUPPORTED_VERSIONS = frozenset({1})`,
     `_OPS_DECISIONS_RE`, `_TIER_SHORTCUT_RE` (for PLATFORM tier shortcuts
     when validating cross-refs), `_LAYER_SHORTCUT_RE` (for PRODUCT layer
     shortcuts: `L\d+|D|D\.fast|D\.lake|E|E\.env|MVP`),
     `_AGGREGATE_LAYER_SHORTCUTS = {"D": ["D.fast", "D.lake"], "E": ["E.env"]}`.
   - `GateRuleParser` class (reuse the PLATFORM implementation pattern; copy
     the regex + arity-counting logic — DO NOT import from platform_roadmap
     to keep PRODUCT's validator self-contained when PLATFORM is missing or
     malformed).
   - **`extra=` policy per sub-model**: top-level `ProductRoadmapDocument`
     uses `extra='forbid'` (strict schema enforcement at the document
     level). Sub-models for richly-typed structures (TierItem, GateHelper,
     CandidateDecision, KnownPlatformGap, FivePropertyTest,
     FivePropertyWaiver, ContractGate, KnownGap, OpenQuestion,
     OutOfProductScope, RetiredItem, CrossTierGate) use `extra='forbid'`
     so silent field drops cannot mask drift. Sub-models for prose-heavy
     descriptive blocks where structural enforcement has low value
     (`CurrentState`, `ThreeTierData`, `Environments`, `EvaluationMetrics`,
     `MinimumViableV1`, `PromotionFunnel`, `NorthStar`) use
     `extra='ignore'` -- risk accepted because the validator's job at
     these surfaces is presence-checking, not field enumeration; CD.25
     contract ratification governs the real semantic check on these
     blocks. `FourLayerEntry` uses `extra='forbid'` BUT MUST enumerate
     the live extension fields (verified against current YAML):
     `contains_risk_constraints: bool = False`,
     `contains_pretrade_gates: bool = False`, `notes: str = ""`.
   - Pydantic models:
     - `GateHelper(name: str, arity: int, params: list[dict[str, Any]] = [],
       returns: str = "bool", semantics: str = "",
       scope: Literal["product_local", "inherited_from_platform"] = "product_local")`
       -- NOTE: field is `name`, not `id`, matching live YAML and
       `scripts/platform_roadmap.py:83`.
     - `DocumentMeta(id, version, status, filed_via, description,
       agent_instructions, gate_helpers: list[GateHelper])`
     - `FourLayerEntry(layer, name, responsibility, interface, inputs,
       outputs, contract_refs, contains_risk_constraints: bool = False,
       contains_pretrade_gates: bool = False, notes: str = "")` --
       extension fields enumerated to land cleanly against live YAML;
       defaults supplied so the alpha entry (no extension fields)
       and operations_telemetry entry (only `notes`) validate.
     - `CurrentState`, `ThreeTierData`, `Environments`,
       `EvaluationMetrics`, `MinimumViableV1`, `PromotionFunnel`,
       `NorthStar`: each is a BaseModel with `extra='ignore'` and any
       fields the validator actually needs to read (e.g. `NorthStar`
       only needs `.principles`). Other fields are accepted silently.
     - `ContractGate(path, class: Literal["A","B","C","D"], contract_version: int)`
     - `FivePropertyAttestation(attestation: str, cites: str)`
     - `FivePropertyTest(parameterised, versioned, composable, observable,
       evaluable — all FivePropertyAttestation)`
     - `FivePropertyWaiver(reason: str, will_attest_when: str)` -- both
       fields required non-empty; `will_attest_when` is free-form
       supporting status-transition triggers ("before status ==
       in_progress") OR ISO dates OR retrospective markers (e.g.
       "retrospective-attestation-deferred-to-archival-pass" for the
       L0.5-class case where a complete item was excluded from the
       exemption set somehow). The validator does NOT parse this string;
       it is queryable structured state for future ratchet work.
     - `TierItem(id, tier, layer, name, intent, depends_on,
       cross_roadmap_depends_on, contract_gates, environment_scope,
       effort, strategic, status, validation_lens,
       five_property_test: FivePropertyTest | None = None,
       five_property_test_waiver: FivePropertyWaiver | None = None,
       deferred: bool = False, deferred_note: str | None = None,
       owning_layer: str | None = None)` -- field set is exactly the
       union of keys appearing in the live YAML's 73 tier_items, no more.
       `completed_at` and `progress_note` are NOT included (zero
       appearances in live YAML; do not invent forward declarations).
     - `CandidateDecision(id, title, detail, gates, state,
       pivot_reference: str | None = None,
       decision_required_before: str | None = None)`
     - `ResearchPoolDecision(id, title, pivot_reference, pivot_quote,
       why_not_ratified_now, proposed_resolution, affected_tier_items)`
     - `CrossTierGate(id, name, rule, rationale, helpers_required)`
     - `RetiredItem(source_section, source_bullet_ids, reason)`
     - `OutOfProductScope(source_bullet_id, text, disposition, note)`
     - `OpenQuestion(id, question, auditor_default_recommendation,
       consequences_if_resolved_differently)`
     - `KnownGap(id, gap, notes)`
     - `KnownPlatformGap(id: must match `^GAP-[a-z0-9-]+$`,
       description, intended_platform_tier_item: str)` -- validated at
       model_validator time against PLATFORM tier_item ids OR the
       literal `pending_triage`. When platform_doc is None,
       only the `pending_triage` literal is accepted (everything else
       requires PLATFORM resolution).
     - `ProductRoadmapDocument` — top-level model with `extra='forbid'`
       and a `@model_validator(mode='after')` that runs:
       (a) id uniqueness PER COLLECTION (tier_items, candidate_decisions,
       candidate_decisions_research_pool, cross_tier_gates, open_questions,
       known_gaps, known_platform_gaps) -- not global since the
       namespaces are disjoint by prefix (L*/D.*/E.*/MVP* vs CDP* vs
       CDPR* vs G.* vs OQ.* vs KG.* vs GAP-*).
       (b) intra-roadmap depends_on resolution (against tier_item ids and
       layer shortcuts including aggregate D / E expansion).
       (c) cycle detection on the intra-roadmap dependency graph (DFS
       gray-set; layer shortcuts expand to per-layer sets, with
       aggregate D and E expanding to all D.fast+D.lake and all E.env
       items respectively).
       (d) cross_roadmap_depends_on resolution in three forms — REQUIRES
       a `platform_doc` parameter passed at validate time (see loader
       below); when `platform_doc is None`, emit a warning to stderr and
       skip cross-roadmap validation (so PRODUCT validation can degrade
       gracefully if PLATFORM loading fails — PLATFORM has its own
       validator; this branch is mostly dead in CI because
       `validate_platform_roadmap` runs before us and fails fast on
       malformed PLATFORM, but it matters for `--pre` where PLATFORM is
       not currently checked).
       (e) cross-roadmap refs to PLATFORM tier_items with status in
       {"retired", "reserved"} = HARD FAIL.
       (f) gate-rule grammar validation for cross_tier_gates.rule and
       candidate_decisions.decision_required_before (inherited PLATFORM
       helpers + PRODUCT-local helpers from document.gate_helpers
       merged into a single name->arity dict; if platform_doc is None,
       only PRODUCT-local helpers are available -- emit warning).
       (g) five_property_test enforcement: for each tier_item, exactly
       one of {five_property_test, five_property_test_waiver, exempt}
       is valid. **Exempt rule (broadened)**: `status == "complete"` --
       full stop, no layer condition. Rationale: retrospective
       attestation on already-shipped state has low signal value and
       cargo-cult risk regardless of which layer the item shipped in;
       the original narrower rule (`AND layer == "platform_infra"`)
       missed L0.5 (status=complete, layer=lab_offline) which would
       otherwise need an incoherent "before status == in_progress"
       waiver on a never-transitioning item. Missing both block AND
       waiver on a non-exempt item = HARD FAIL. Both block AND waiver
       present on the same item = HARD FAIL (XOR enforcement). Waiver
       present requires both `reason` and `will_attest_when` to be
       non-empty strings.
   - `load(path, platform_path=None)` function: loads PRODUCT YAML, then
     attempts to load PLATFORM (returns `platform_doc=None` on failure
     with a stderr warning). Calls `ProductRoadmapDocument.model_validate`
     with the platform_doc threaded through.
   - `ProductRoadmapState` class (parallel to PlatformRoadmapState):
     `eligible_items()`, `compute_blocked()`, `in_progress_items()`,
     `strategic_pending_items()`, `layer_complete(layer)`, `active_layer()`
     (canonical order: L0, L1, L2, L3, L4, D.fast, D.lake, E.env, MVP),
     `resolve_depends_on(item_id)`, and **three** namespace-typed
     reverse-index methods:
     - `platform_tier_item_consumers() -> dict[str, list[str]]` -- keyed
       by PLATFORM tier_item id (e.g. "T0.13"), values are sorted lists
       of PRODUCT tier_item ids that cross_roadmap_depends_on it.
     - `platform_gap_consumers() -> dict[str, list[str]]` -- keyed by
       GAP slug (e.g. "GAP-cd25-contract-ritual"), same value shape.
     - `platform_cd_consumers() -> dict[str, list[str]]` -- keyed by
       PLATFORM CD id (e.g. "CD.9"), same value shape.

     Rationale for splitting (per critique finding 6): the downstream
     preflight consumer that emits "PLATFORM:Tx.y is consumed by N
     product tier_items" only operates on tier_item ids; mixing GAP and
     CD into a single map would force every read site to inspect key
     prefixes. Three maps are the cleaner downstream surface.

     `to_preflight_dict()` emits all three maps under their respective
     keys (`platform_tier_item_consumers`, `platform_gap_consumers`,
     `platform_cd_consumers`).
   - `compute_state_dict(yaml_path, platform_yaml_path, latest_decision_ts=None)`
     function: mirrors `platform_roadmap.compute_state_dict`. Returns a
     dict with `error` key on parse failure and empty lists for downstream
     safety.
   - `__main__` block: argparse with `--check <path>` (loads + validates
     and prints PASS/FAIL), `--platform <path>` (PLATFORM YAML for
     cross-roadmap resolution), `--check-preflight-report <path>` (asserts
     the report has the expected product_roadmap block shape, for use in
     VP Step 13).

2. **Modify `scripts/validate.py`** — add `validate_product_roadmap(failed)`
   function immediately after `validate_platform_roadmap()` (around line
   1635). Match platform's exception ladder exactly (yaml.YAMLError gets
   its own arm for consistent error reporting under malformed YAML):
   ```python
   def validate_product_roadmap(failed: list[str]) -> None:
       """Validate docs/ROADMAP-PRODUCT.yaml against the
       ProductRoadmapDocument Pydantic schema (with cross-roadmap
       resolution against PLATFORM).

       Runs in BOTH --pre and full presubmit (see wiring note below)."""
       print("\n=== Product roadmap schema validation ===")
       product_path = ROOT / "docs" / "ROADMAP-PRODUCT.yaml"
       platform_path = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
       if not product_path.exists():
           print(f"  FAIL: {product_path.relative_to(ROOT)} not found")
           failed.append("Product roadmap schema validation")
           return
       try:
           import yaml as _yaml  # noqa: PLC0415
           from pydantic import ValidationError  # noqa: PLC0415
           from scripts.product_roadmap import load  # noqa: PLC0415

           load(product_path, platform_path=platform_path)
           print("  PASS: product roadmap schema validation passed.")
       except ImportError as exc:
           print(f"  ERROR: Could not import product_roadmap: {exc}")
           failed.append("Product roadmap schema validation")
       except _yaml.YAMLError as exc:
           print(f"  FAIL: YAML parse error:\n{exc}")
           failed.append("Product roadmap schema validation")
       except ValidationError as exc:
           print(f"  FAIL: Pydantic validation error:\n{exc}")
           failed.append("Product roadmap schema validation")
       except (ValueError, OSError) as exc:
           print(f"  FAIL: {exc}")
           failed.append("Product roadmap schema validation")
   ```

   **Wiring -- two call sites (deliberate divergence from platform):**

   (a) Full-tier path: add `validate_product_roadmap(failed)` to
   `run_python_checks()` immediately after the existing
   `validate_platform_roadmap(failed)` call (around line 1899). This
   matches platform's placement.

   (b) `--pre` (fast-tier) path: ALSO add `validate_product_roadmap(failed)`
   to the `--pre` dispatch (around lines 2209-2212 in current
   `scripts/validate.py`; re-read the file to confirm the exact insertion
   point under the args.pre branch). This DIVERGES from
   `validate_platform_roadmap()`, which is currently full-tier only.

   **Rationale for the divergence** (record this as a one-line code
   comment at the --pre call site, not just here): the product-roadmap
   schema check is pure Python over a single YAML file, runs in well
   under 100ms locally, and ROADMAP-PRODUCT.yaml is being edited by
   agents far more often than ROADMAP-PLATFORM.yaml (active product
   sequencing surface vs slower-moving platform tier surface). Catching
   structural drift in the fast-tier loop is high-value for product
   editors and cheap enough not to dent the fast-tier budget. The
   platform check is not promoted to --pre in this plan because it is
   not the active editing surface; promoting it is a separate decision
   (out of scope, captured implicitly by the divergence note).

   Pre-implementation verification: before editing the --pre branch,
   re-read `scripts/validate.py` around line 2180-2240 to confirm
   `validate_platform_roadmap()` is INDEED full-tier-only today (the
   plan-critique gate verified this against the current file but the
   implementer should re-verify in case the file changed between plan
   commit and implementation start). The platform docstring at the top
   of `validate_platform_roadmap` reads "Runs in full presubmit only
   (not --pre)" -- that line is the canonical signal.

3. **Modify `scripts/session_preflight.py`** — add a `product_roadmap`
   state computation parallel to the existing platform_roadmap one:
   - Add `ROADMAP_PRODUCT_PATH = ROOT / "docs" / "ROADMAP-PRODUCT.yaml"`
     module-level constant.
   - Import `from scripts import product_roadmap as product_roadmap_module`
     (or import inline at the call site if there's a circular concern).
   - In `main()`, after the existing
     `platform_roadmap_state = platform_roadmap.compute_state_dict(...)`
     call (line ~1193), add:
     ```python
     product_roadmap_state = product_roadmap_module.compute_state_dict(
         ROADMAP_PRODUCT_PATH,
         platform_yaml_path=ROADMAP_PLATFORM_PATH,
         latest_decision_ts=_get_latest_decision_ts(),
     )
     ```
   - Add `"product_roadmap": product_roadmap_state` to the `report` dict
     (immediately after the `platform_roadmap` entry).
   - The state-dict must include `platform_consumers` keyed off PLATFORM
     id with PRODUCT consumer-id lists.

4. **Modify `docs/ROADMAP-PRODUCT.yaml`**:
   - Add a top-level `known_platform_gaps:` list immediately above
     `known_gaps`. Six entries (one per `PLATFORM:GAP-*` string currently
     in the file):
     ```yaml
     known_platform_gaps:
       - id: GAP-cd25-contract-ritual
         description: Pre-codegen contract ratification ceremony per CD.25.
         intended_platform_tier_item: pending_triage
       - id: GAP-t-1-12-product-contracts-schema-amendment
         description: T-1.12 needs schema amendment to admit product contracts.
         intended_platform_tier_item: pending_triage
       - id: GAP-tca-aggregation
         description: Transaction-cost-analysis aggregation Lambda for L3 telemetry.
         intended_platform_tier_item: pending_triage
       - id: GAP-broker-secrets-manager
         description: Broker credentials in AWS Secrets Manager with rotation.
         intended_platform_tier_item: pending_triage
       - id: GAP-reconciliation-lambda
         description: Daily broker-vs-cache reconciliation Lambda.
         intended_platform_tier_item: pending_triage
       - id: GAP-class-b-product-lambdas
         description: Class-B Lambda packaging for product-tier handlers.
         intended_platform_tier_item: pending_triage
     ```
     Tune descriptions if any of the items already carries more precise
     wording in its surrounding intent prose; check
     docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml if it exists
     for canonical descriptions.
   - For each tier_item where:
     - `five_property_test` is absent, AND
     - the exemption (`status == "complete"` -- broadened rule, no layer
       condition) does NOT apply
     ...add a `five_property_test_waiver:` block. Identify the list via
     `bin/venv-python -m scripts.product_roadmap --list-waiver-candidates docs/ROADMAP-PRODUCT.yaml`
     (add this CLI subcommand to scripts/product_roadmap.py for ergonomics
     during this step). **Expected list: exactly 30 items** -- verified
     by the plan-critique gate against current YAML state. Breakdown:
     - **1 L0 item**: L0.4 (status=in_progress, layer=platform_infra)
     - **5 D.fast items**: D.fast.1, D.fast.2, D.fast.3, D.fast.4, D.fast.5
     - **8 D.lake items**: D.lake.1 through D.lake.8
     - **11 E.env items**: E.env.1 through E.env.11
     - **5 MVP items**: MVP.1 through MVP.5

     **L4 items are NOT in the waiver list** -- all 5 L4 items
     (L4.ops.1-L4.ops.5) already carry valid five_property_test blocks.

     **Exempt items** (5 total, no action needed): L0.1, L0.2, L0.3,
     L0.5, L0.6. All have `status == "complete"`. L0.5 is the
     boundary-case item (layer=lab_offline rather than platform_infra)
     that the broadened exemption rule cleanly catches.

     Waiver shape:
     ```yaml
     five_property_test_waiver:
       reason: "<one-line: why attestations are deferred -- typically because the design depends on a precursor tier_item or is itself a forward-design question>"
       will_attest_when: "before status == in_progress"
     ```
     Write authentic reasons, not boilerplate. Typical reason patterns:
     - **D.fast.* items**: "DynamoDB schema/keys/GSI design crystallises
       during E.env.2 (EnvironmentConfig Pydantic); attestations would
       be speculative before that."
     - **D.lake.* items**: "Iceberg table contracts ratify in CD.25
       follow-up (PLATFORM:GAP-cd25-contract-ritual); the
       parameterised/versioned attestations specifically depend on the
       SCD2 row stamp design."
     - **E.env.* items**: "Environment-as-config invariants
       crystallise during E.env.1 (EnvironmentConfig Pydantic
       authoring); per-env attestations follow."
     - **MVP.* items**: "MVP composition emerges from L1-L4 landing;
       five-property attestations are inherited from the upstream
       layer items once those land."
     - **L0.4**: "Step Functions orchestration in-progress; attestations
       follow shipping (status -> complete)."

     The user has the context for these reasons -- surface uncertainty
     in any reason that cannot be authored confidently and ask before
     committing.

5. **Create `tests/fixtures/product_roadmap/__init__.py`** — empty file
   (package marker).

6. **Create `tests/fixtures/product_roadmap/minimal_platform.yaml`** — a
   tiny self-contained PLATFORM roadmap:
   ```yaml
   document:
     id: ROADMAP-PLATFORM-FIXTURE
     version: 1
     status: draft
     filed_via: pending_log_decision_lambda
     gate_helpers:
       - {name: tier_complete, arity: 1}
       - {name: item_field_eq, arity: 3}
   tier_items:
     - {id: T-1.5, tier: T-1, name: Fixture T-1.5, depends_on: [], effort: S, strategic: false, status: complete}
     - {id: T0.1,  tier: T0,  name: Fixture T0.1,  depends_on: [], effort: S, strategic: false, status: not_started}
     - {id: T0.2,  tier: T0,  name: Fixture T0.2,  depends_on: [T0.1], effort: S, strategic: false, status: not_started}
     - {id: T1.8,  tier: T1,  name: Fixture reserved item, depends_on: [], effort: S, strategic: false, status: reserved}
   candidate_decisions:
     - {id: CD.1, title: Fixture CD.1, gates: [T-1]}
     - {id: CD.2, title: Fixture CD.2, gates: [T0]}
   cross_tier_gates: []
   ```

7. **Create `tests/fixtures/product_roadmap/minimal_product.yaml`** — a
   tiny PRODUCT roadmap that cross-references the platform fixture in all
   three valid forms plus the registry:
   ```yaml
   document:
     id: ROADMAP-PRODUCT-FIXTURE
     version: 1
     status: draft
     filed_via: pending_log_decision_lambda
     gate_helpers:
       - {name: deflated_sharpe, arity: 3, scope: product_local}
   tier_items:
     - id: L0.1
       tier: L0
       layer: platform_infra
       name: Fixture L0.1 (EXISTING-COMPLETE, exempt)
       depends_on: []
       cross_roadmap_depends_on: [PLATFORM:T-1.5]
       effort: S
       strategic: false
       status: complete
       validation_lens: structural
     - id: L1.alpha.1
       tier: L1
       layer: alpha
       name: Fixture L1.alpha.1 (cross-refs all three forms)
       depends_on: []
       cross_roadmap_depends_on: [PLATFORM:T0.1, PLATFORM:GAP-fixture-gap, PLATFORM:CD.1]
       effort: S
       strategic: false
       status: not_started
       validation_lens: structural
       five_property_test:
         parameterised: {attestation: x, cites: y}
         versioned: {attestation: x, cites: y}
         composable: {attestation: x, cites: y}
         observable: {attestation: x, cites: y}
         evaluable: {attestation: x, cites: y}
     - id: L2.portfolio.1
       tier: L2
       layer: portfolio_construction
       name: Fixture L2 with waiver
       depends_on: [L1.alpha.1]
       cross_roadmap_depends_on: [PLATFORM:T0.2]
       effort: S
       strategic: false
       status: not_started
       validation_lens: structural
       five_property_test_waiver:
         reason: Fixture waiver reason for tests.
         will_attest_when: before status == in_progress
     - id: D.fast.1
       tier: D.fast
       layer: data
       name: Fixture D.fast.1 with waiver
       depends_on: []
       cross_roadmap_depends_on: [PLATFORM:T0.1]
       effort: S
       strategic: false
       status: not_started
       validation_lens: structural
       five_property_test_waiver:
         reason: Fixture waiver for D.fast.
         will_attest_when: 2026-12-31
   candidate_decisions:
     - {id: CDP.1, title: Fixture CDP.1, gates: [L0, L1, D, MVP], state: pending}
   candidate_decisions_research_pool: []
   cross_tier_gates: []
   retired_items: []
   out_of_product_scope: []
   open_questions: []
   known_gaps: []
   known_platform_gaps:
     - {id: GAP-fixture-gap, description: Fixture gap for tests, intended_platform_tier_item: pending_triage}
   four_layer_model: []
   three_tier_data_architecture: {}
   environments: {}
   evaluation_metrics: {}
   minimum_viable_v1: {}
   promotion_funnel: {}
   current_state: {}
   north_star: {principles: []}
   ```

8. **Create `tests/test_product_roadmap.py`** — pytest test classes
   mirroring `tests/test_platform_roadmap.py`:
   - `TestLoad`: live-YAML loads (after Step 4 waiver additions); missing
     file raises FileNotFoundError; invalid YAML raises.
   - `TestStructuralValidation`: missing document raises; wrong type for
     tier_items raises; unsupported version raises; minimal valid doc passes.
   - `TestIdUniqueness`: duplicate tier_item id raises; duplicate
     candidate_decision id raises; duplicate known_platform_gap id raises.
   - `TestDanglingDependsOn`: nonexistent intra-roadmap dep raises; valid
     dep passes; layer-shortcut dep (depends_on: [L0]) passes.
   - `TestCycleDetection`: direct cycle raises; three-node cycle raises;
     layer-shortcut cycle raises; linear chain passes; aggregate-shortcut
     (depends_on: [D]) expands to D.fast + D.lake and detects cycle through them.
   - `TestGateRuleGrammar`: unknown helper raises; arity mismatch raises
     (both inherited PLATFORM helper and PRODUCT-local helper); valid
     combined rule passes; PRODUCT-local helper resolves correctly when
     platform_doc provides inherited set.
   - `TestCrossRoadmapResolution`: dangling PLATFORM:T999.0 raises;
     dangling PLATFORM:CD.999 raises; PLATFORM:GAP-unregistered raises;
     valid PLATFORM:T0.1 passes; valid PLATFORM:GAP-fixture-gap passes;
     valid PLATFORM:CD.1 passes; PLATFORM:T1.8 (reserved) raises;
     cross-roadmap validation when platform_doc is None emits warning but
     does not raise.
   - `TestFivePropertyEnforcement`: exempt item (status=complete,
     ANY layer including `platform_infra`, `lab_offline`, etc) without
     block passes -- assert with both a platform_infra-complete item
     AND a lab_offline-complete item to lock in the broadened rule;
     non-exempt without block or waiver raises; with valid block passes;
     with valid waiver passes; with both block and waiver raises (XOR
     enforcement); waiver missing `reason` raises; waiver missing
     `will_attest_when` raises; waiver with empty-string `reason` raises;
     waiver with empty-string `will_attest_when` raises.
   - `TestKnownPlatformGaps`: valid entry passes; missing id prefix raises;
     entry with intended_platform_tier_item that doesn't exist in PLATFORM
     raises (when platform_doc available); `pending_triage` always passes.
   - `TestReverseIndex`: load the fixture pair; assert each of the
     three split maps contains expected mappings:
     - `platform_tier_item_consumers`: {"T-1.5": ["L0.1"],
       "T0.1": ["D.fast.1", "L1.alpha.1"], "T0.2": ["L2.portfolio.1"]}
     - `platform_gap_consumers`: {"GAP-fixture-gap": ["L1.alpha.1"]}
     - `platform_cd_consumers`: {"CD.1": ["L1.alpha.1"]}
     Each value list is sorted for deterministic comparison.
   - `TestLiveYAML`: after Step 4, `load(docs/ROADMAP-PRODUCT.yaml,
     platform_path=docs/ROADMAP-PLATFORM.yaml)` succeeds; result has
     non-empty platform_tier_item_consumers (assert PLATFORM:T0.13 is
     keyed in this map with at least L0.1 in its value list, locking
     in the live cross-reference), all 6 GAP entries in
     platform_gap_consumers are reachable, and platform_cd_consumers
     contains at least CD.9 (the most-referenced PLATFORM CD).

9. **Create `tests/test_product_roadmap_state.py`** — mirror
   `tests/test_platform_roadmap_state.py`:
   - eligible_items with no deps; with complete dep; with layer-shortcut dep.
   - compute_blocked with incomplete dep.
   - layer_complete for L0 (all complete passes), for L1 (any incomplete
     fails), for `reserved` status excluded.
   - aggregate layer-shortcut: `layer_complete("D")` true iff all D.fast
     AND all D.lake are complete; `resolve_depends_on` against `depends_on:
     [D]` returns the union.
   - active_layer canonical-order traversal.
   - strategic_pending_items isolation from eligible_items.
   - platform_tier_item_consumers / platform_gap_consumers /
     platform_cd_consumers: each returns expected dict given fixture;
     each returns empty dict when no cross-refs of that type exist;
     value lists are sorted.

10. **Create `tests/test_session_preflight_product_roadmap.py`** — mirror
    `tests/test_session_preflight_platform_roadmap.py`:
    - Run `compute_state_dict` against the fixture pair; assert the
      returned dict has `next_eligible`, `in_progress`, `blocked`,
      `strategic_pending`, `active_layer`,
      `platform_tier_item_consumers`, `platform_gap_consumers`,
      `platform_cd_consumers` keys (three split namespaces, not one
      mixed map).
    - Malformed PRODUCT YAML -> returns dict with `error` key and empty
      lists (matches platform_roadmap degradation).
    - Missing PRODUCT YAML -> same degradation.
    - Missing PLATFORM YAML -> all three consumers maps still computed
      (intra-PRODUCT walk succeeds) but cross-roadmap resolution
      skipped with stderr warning; no crash.
    - End-to-end: call `session_preflight.main()` in a subprocess (or
      isolate via the existing test patterns), assert
      `logs/.preflight-report.json` contains `product_roadmap` top-level
      key with all expected sub-keys including the three split
      consumers maps.

11. **Run validation gauntlet** — execute the Verification Plan steps
    1-15 in order. Loop on any failure: fix root cause, re-run that VP
    step, then continue.

12. **Final commit** — once all VP steps pass and Step 14 (coverage
    checker) is green, stage and commit:
    ```bash
    git add scripts/product_roadmap.py scripts/validate.py \
            scripts/session_preflight.py docs/ROADMAP-PRODUCT.yaml \
            tests/test_product_roadmap.py tests/test_product_roadmap_state.py \
            tests/test_session_preflight_product_roadmap.py \
            tests/fixtures/product_roadmap/
    git commit -m "feat(product-roadmap): structural validator + preflight wiring"
    ```
    (Plan file itself committed separately by the planning agent before
    /implement starts.)

13. **Report** — summarise what landed: file paths, line counts of new
    code, test count, validate.py pass evidence (terminal snippet),
    preflight evidence (one-line excerpt showing product_roadmap block
    with platform_consumers map), and the count of waiver entries added
    to ROADMAP-PRODUCT.yaml.

14. **Execute Verification Plan** -- run each step. Loop until pass.
    If V3 fails unrecoverably, stop and analyze root cause (Decision 55).
    (This plan is V2 with no V3 surface, so the V3 escape hatch should
    not be reached; if any V2 test resists fixing after two attempts,
    surface to the user rather than spawning a rescue agent.)
