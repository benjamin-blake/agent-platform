# Decisions

The canonical corpus of ratified architectural and operational decisions, and the sole ETL source for the `ops_decisions` warehouse table (Decision 84). Fully-superseded entries move to `docs/DECISIONS_ARCHIVE.md` per the archival policy in Decision 146.

## Decision 173: Executor inference tiers are ROLES -- provider identity is configuration, and a tier's cold-start assertion follows its billing shape (amends Decisions 116, 122 and 164) (Decided)

```yaml
number: 173
status: Decided
decided_date: "2026-08-19"
amends: [116, 122, 164]
significance:
  value: numbered_decision
  justification: >-
    Tier MEMBERSHIP becomes configuration -- a provider swap is a contract edit, never a Decision
    amendment -- and three entries' reversal conditions are re-keyed onto role and billing shape. The
    provider VALUES do route to inference-provider.yaml (this entry performs that re-homing), but no
    contract note constrains how future DECISIONS are written; amendment_forms was rejected because
    this amends THREE entries and adds rules none carried.
```

**Status:** Decided
**Date:** 2026-08-19
**Warehouse ID:** dec-173

**Problem:**
Decision 122 ratified the tier model in VENDOR terms -- DeepSeek model ids, the Anthropic "Max x5
programmatic pool" -- and keyed its reversal conditions to one vendor's unit price and the other's
pool utilization; Decision 164's rationale and Decision 116's shared-pool condition are anchored the
same way. LiteLLM was adopted so models and providers can change as they ship, and provider is to
become a measured performance VARIABLE later. Vendor identity as architecture inverts that, and
duplicates `litellm_tier_models` in `docs/contracts/inference-provider.yaml`, content
Decision 86/127 routes to the contract.

**Intent:** Tier 1 and Tier 2 were the right SELECTIONS at ratification and EXAMPLES of a
primary/fallback mechanism, never the architecture; the ROLES are the commitment.

**Decision:**
1. **The tiers are ROLES.** Tier 1 = primary route; Tier 2 = warm-fetched fallback on a provider
   INDEPENDENT of Tier 1's (Decision 47's lock-in escape hatch), validated at every harness cold
   start; Tier 3 = deferred aggregator. DeepSeek-direct and Anthropic-direct are the CURRENT
   selections and examples of that mechanism; Decision 122's naming of them is a selection record.
   Unchanged: LiteLLM as the sole Layer-1 inference surface (provider-SDK imports forbidden),
   Bedrock's retirement, the role pair, and the Decision-121 reconciliation.
2. **Provider VALUES live in the contract, not in prose.** Which provider and model ids fill a role
   is stated in `docs/contracts/inference-provider.yaml`; changing it needs no amendment. Three
   limits bound it: (a) no role may be filled by an id in that file's `retired_providers` --
   restoring one requires a Decision superseding the entry that retired it (122/CD.28 for bedrock,
   116 for copilot-sdk and gemini_byok); (b) primary and fallback must resolve to DIFFERENT providers
   -- a same-vendor pair is no escape hatch; (c) a swap changing the vendor or billing shape under
   Decision 116's shared-allowance coupling re-arms Decisions 116's and 164's reversal conditions and
   owes a dated annotation on both. Untouched:
   `provider_defaults.executor_path` and `model_registry.py`'s `_VALID_PROVIDERS` /
   `_DEFAULT_EXECUTOR_PROVIDER`, the T4.2-owned interim transport set.
3. **Decision 164's argument is restated as SHAPE claims**, which is what lets it survive a swap:
   METERED marginal cost versus a FIXED, NON-ROLLOVER ALLOWANCE, and an HTTP transport
   (runtime-agnostic) versus a CLI transport (needs a CLI-hosting runtime). Neither is a vendor
   claim, so its conclusion and substrate-collapse obligation both survive. Its condition (c) is
   re-read onto the PRIMARY role's metered unit price, and Decision 116's onto the fallback role's
   fixed-allowance contention.
4. **New rule, conditional on billing shape:** a tier billed as a FIXED, NON-ROLLOVER ALLOWANCE
   requires a remaining-allowance assertion at cold start; a METERED tier, a credential-liveness
   probe; a Deferred tier declares `not_applicable` until committed. This supersedes CD.28's ">10%
   remaining Anthropic pool" wording, now that rule's fixed-allowance INSTANCE, and makes
   `billing_shape` a contract field.
5. **Provider-agnostic is the COMMITMENT; the implementation reaches it at T4.2.**
   `scripts/llm/client.py` raises `LLMResponseError` for any provider but `gemini` and discards
   `system_prompt`; no tier routing exists in code until T4.2's LiteLLM transport lands. It moves
   no traffic and edits no transport. Disclosed per ESB-02
   (`audits/executor-substrate-and-billing-shape-ad02653.yaml`), where a recorded-but-inoperative
   control produced a false dismissal downstream.

**Reversal conditions:** each reopens the QUESTION, never the answer; the price and utilization
ones re-key Decisions 122's and 116's onto role and billing shape.

```yaml reversal-conditions
decision: 173
review_by: 2026-11-19
on_trigger: "re-decide via /plan whether the role model still holds; update or re-arm this stanza"
conditions:
  - id: fallback-billing-shape-change
    kind: manual
    description: "Fallback-role billing changes between metered and fixed-non-rollover-allowance -> re-derive clause 4's cold-start assertion"
  - id: primary-unit-price-move
    kind: manual
    description: "The primary role's metered unit price moves >5x either way -> re-decide role membership"
  - id: fixed-allowance-saturation
    kind: manual
    description: "A fixed-non-rollover-allowance fallback passes 70% utilization over 30 days, or contends with scheduled-agent draw on the same allowance (Decision 116's, re-keyed)"
  - id: single-provider-collapse
    kind: manual
    description: "Only one provider stays reachable behind LiteLLM, or primary and fallback resolve to one vendor -> re-decide the role model"
```

**Related:** Decision 122 (amended -- ratification converted to roles), Decision 164 (amended --
argument restated as shape claims; condition (c) re-read onto the primary role), Decision 116
(amended -- its shared-allowance condition re-keyed onto the fallback role's billing shape; its
routing unchanged), Decisions 121, 47 (archived), 86, 127, 133, 167, 84, 55, CD.28, tier_items
T4.2 and T4.17.

---

## Decision 172: GitHub's immutable OIDC subject-claim format governs post-rename repositories; trust additively, contract only with live proof (Decided)

```yaml
number: 172
status: Decided
decided_date: "2026-08-15"
amends: []
significance:
  value: numbered_decision
  justification: A durable architectural commitment to trust GitHub's immutable numeric-id OIDC subject additively for every rename-eligible repository, with reversal-relevant consequences for how every future rename is staged.
```

**Status:** Decided
**Date:** 2026-08-15
**Warehouse ID:** dec-172 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
GitHub applies an immutable OIDC subject-claim format, `repo:OWNER@OWNER-ID/REPO@REPO-ID:<context>`, to any repository renamed or transferred after 2026-07-15 -- replacing the mutable `repo:OWNER/REPO:<context>` form this repository's five CI roles trusted exclusively. `benjamin-blake/theseus` was created 2026-05-28 (mutable format) and renamed 2026-08-15T12:55:57Z (`agent-platform` -> `theseus`), migrating at the rename. Every role's trust policy inspected as correct (Decision 171's in-flight dual-slug work varies only the NAME half) yet matched nothing post-rename -- the rename changed the subject SHAPE, a dimension no prior trust-policy work anticipated. STS denied every assume from 12:55:57Z onward; the same outage also disabled `ci-rca`/`convergence-health`, so no recommendation auto-filed and a stale-green convergence record masked the failure.

**Decision:**
1. **Trust the immutable numeric-id subject additively, alongside the existing name-only entries -- never in place of them.** `local.github_repos` in `terraform/personal/oidc.tf` and `terraform/bootstrap/github_ci_apply.tf` gains a third entry, a repo SEGMENT of the form `OWNER@OWNER-ID/REPO@REPO-ID` (never a `repo:`-prefixed literal -- every sub site already renders `repo:${repo}:<suffix>`). For this repository: `benjamin-blake@217728084/theseus@1252427466`.
2. **The numeric ids, not either name, are the durable identity.** A future rename changes only the NAME half of the immutable form; the ids (`217728084` / `1252427466`) are permanent for this repository's lifetime. Trusting a not-yet-mintable sub is harmless (a StringLike/StringEquals entry against a subject nothing can ever present costs nothing), so the standing playbook going forward is: **before** any future rename, pre-stage the new name's immutable entry additively, so no gap between rename and trust-repair ever recurs.
3. **Exact-match only -- no wildcard.** IAM `StringLike` `*` spans `:` and `/`, and GitHub environment names are attacker-chosen free text with no documented charset restriction, so a pattern like `repo:*@217728084/*@1252427466:...` would be forgeable by a foreign repository via a crafted environment name. Rename-proofing is procedural (point 2), never a wildcard.
4. **Contraction is a future, separately-evidenced act -- not this Decision.** The two legacy name-only entries are provably dead going forward (a renamed repository's old slug can never mint a subject again, and any new repository later claiming the old slug is itself post-cutoff and immutable), but they stay trusted until live `RoleLastUsed` proof lands for every role under the immutable sub and a follow-on contraction removes them explicitly.

**Rationale:**
An IAM trust diff already routes to the gated-apply path regardless of shape (Decision 77/92), so additive trust is no more expensive to apply than a narrowing edit, and it avoids reviewing a removal under incident time-pressure for no safety benefit (the legacy entries cost nothing extra to keep trusted). GitHub's repository-level OIDC subject-claim customization API (forcing a name-only sub) was examined and rejected: rename-fragile in exactly the way this incident proves, and it re-pins identity to a mutable name instead of adopting the durable one.

**Reversal conditions:**
This trust stays additive until superseded by a scoped contraction: (a) the two legacy name-only entries are removed only once every role records live proof of a successful assume under the immutable sub (this plan's VP steps 11-12) and `github_ci_deploy`'s currently-pending evidence closes -- tracked as a follow-on recommendation, never automatic; (b) if a future rename lands WITHOUT its new name's immutable entry pre-staged beforehand (point 2's playbook not followed), this Decision's recovery procedure applies again and a process gap is filed.

```yaml reversal-conditions
decision: 172
review_by: 2026-11-15
on_trigger: "re-decide via /plan whether contraction is evidenced; update or re-arm this stanza"
conditions:
  - id: legacy-entries-provably-dead-with-proof
    kind: manual
    description: "All five CI roles record a live RoleLastUsed timestamp under the immutable sub (this plan's VP steps 11-12) and github_ci_deploy's pending evidence closes -> contract local.github_repos to the immutable entry alone via a follow-on plan, never silently."
  - id: future-rename-not-prestaged
    kind: manual
    description: "A future repository rename/transfer lands without the new name's immutable entry pre-staged additively beforehand -> this Decision's playbook (point 2) was not followed; re-run the same recovery and file a process gap."
```

**Related:** Decision 94 (both-sub-forms guard this entry must not weaken), Decision 77 + Decision 92 (gated-apply routing for the IAM trust diff), Decision 55 (forward-fix, never a workaround), Decision 35 (exact-match enumeration principle the no-wildcard constraint rests on), Decision 167 (typed envelope / Significance claim), Decision 133 (reversal-conditions stanza grammar this entry follows).

---

## Decision 171: The repository is renamed agent-platform -> theseus and relicensed Apache-2.0 -> BUSL-1.1, forward-only (Decided)

```yaml
number: 171
status: Decided
decided_date: "2026-08-16"
amends: [101, 127]
significance:
  value: numbered_decision
  justification: An irreversible change to the repository's public identity and outbound licence, with standing consequences for contribution posture, the sanctioned-prose taxonomy, and every trust claim keyed on the repository slug.
```

**Status:** Decided
**Date:** 2026-08-16
**Warehouse ID:** dec-171 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 101 ratified Theseus as the platform's external brand but froze the repository name as an internal identifier "not to be altered without a separate explicit decision", and deferred a paid service offering as separately gated. The repo therefore shipped under a name used nowhere externally, under Apache-2.0 -- a licence permitting unrestricted commercial redistribution of a platform whose engineering IS the product. Both need one explicit decision because they share a blast radius: the slug is embedded in every OIDC trust policy, and the licence flip needs an unambiguous boundary commit a rename must not disturb.

**Decision:**
1. **Rename `benjamin-blake/agent-platform` -> `benjamin-blake/theseus`, in place.** This promotes ONLY Decision 101 point (b)'s repository-name row into the presentation layer. Every other (b) row is re-affirmed FROZEN -- `agent-platform-*` AWS resource names, the `agent_platform` profile and Glue database, `/agent-platform/*` SSM paths, `project_id = trading-system` -- and the deep internal rename stays deferred post-MVP. In place rather than a fresh repository; that rationale is in `LICENSING.md`.
2. **Relicense to BUSL-1.1, forward-only.** Every version published up to and including commit `4de9df86e02b7eeccf58df83e74f6061fc1303e2` remains Apache-2.0 irrevocably, preserved verbatim at `LICENSE-APACHE`; no artefact makes a retroactive claim. The boundary, its provenance-scoped self-verifying rule, and why it lives in `LICENSING.md` rather than `NOTICE` (Apache-2.0 4(d) burdens a root NOTICE with a redistribution obligation) are stated there, not restated here.
3. **Change Date 2030-08-15, Change License Apache-2.0.** The date is the exact four-year anniversary of the flip, rounded DOWN, never up: rounding up would breach BUSL-1.1's own cap, and a published version's Change Date may only ever move EARLIER. Apache-2.0 satisfies BUSL-1.1's GPL-compatibility requirement for the Change License because it is GPLv3-compatible; it is not GPLv2-compatible, and BUSL does not require that.
4. **The Additional Use Grant restates the non-production baseline AND disclaims exhaustiveness inside the parameter value.** That slot exists to permit LIMITED PRODUCTION use, so a bare enumeration there invites an expressio unius reading that NARROWS the baseline the Terms already grant. The non-limitation sentence sits inside the parameter -- a clause in another section does not qualify a parameter.
5. **Contribution posture changes, and Decision 101 point (f)'s "secondary aspiration: open-source community" is amended accordingly.** BUSL-1.1 is source-available, NOT OSI open source. Dual licensing rests on sole copyright ownership, which is UNVERIFIED: GitHub's inbound=outbound terms put contributions under the outbound licence, conferring no right to sublicense commercially, and AGENTS.md mandates a `Co-Authored-By` trailer on every commit (54 of the 60 commits visible in this shallow clone carry one). A trailer is a convention, not an assignment. `CONTRIBUTING.md` therefore requires assignment or an equivalently broad grant; a real CLA/DCO mechanism is a follow-on recommendation, and the trailer convention is NOT quietly dropped as a workaround.
6. **Point (f)'s paid-service gate is discharged for the LICENCE half only.** Dual licensing is authorised; no commercial surface, pricing or terms is built here. `COMMERCIAL-LICENSE.md` is a contact stub at the repo root -- deliberately not `marketing/`, which Decision 101(c) names as the home for commercial PROSE, whereas a licence file belongs where licence files conventionally live.
7. **Decision 127 point 1 gains a permanent prose class: licence-and-attribution artefacts** (`LICENSING.md`, `CONTRIBUTING.md`, `COMMERCIAL-LICENSE.md`). They enter `prose_allowlist.allowed_globs`, never `grandfathered_globs`, which is ratchet-only and may not grow. Precedent: Decision 101(c)'s scoped `marketing/**` carve-out. `validate_licence_consistency` enforces mutual consistency of the licence artefacts and guards the class-(a) repository-reference / class-(b) AWS-name split the rename turns on.

**Rationale:**
Decision 111's curated public-portal enumeration goes stale on merge -- three new root portal files land. The invariant is untouched, because licence artefacts are curated projection rather than an operational-data export, so Decision 111's reversal conditions do not fire; the enumeration is simply extended.

**Reversal conditions:**
Asymmetric by half. The RENAME was reversible by an owner-executed rename-back only while the old-slug OIDC subjects stayed trusted; that window closed with Decision 172's contraction, and a further rename now follows Decision 172 point 2's pre-stage playbook. The LICENCE flip is not reversible for published versions -- a later, more permissive relicense is always available prospectively, but no published BUSL version can be unpublished. Re-decide if: (a) a copyright-provenance audit finds a contribution not covered by an assignment, in which case the dual-licensing posture must be settled BEFORE any commercial licence is sold, not after; or (b) the Additional Use Grant is read as narrowing despite point 4, in which case it reverts to "None" and the Terms stand alone.

**Related:** Decision 101, Decision 111, Decision 127, Decision 128, Decision 167, Decision 172.

---

## Decision 170: The registered-check contract gains a second, declarative output channel -- examined()/skipped() -- so a vacuous pass, a skip, and an enforced pass stop collapsing into one indistinguishable green, governed by a shrink-only adoption ratchet (Decided)

```yaml
number: 170
status: Decided
decided_date: "2026-08-13"
amends: []
significance:
  value: numbered_decision
  justification: A durable architectural commitment adding a second output channel to the registered-check contract, a new evidence schema version, and a structurally-enforced adoption ratchet, with reversal-relevant consequences for how every future check is authored.
```

**Status:** Decided
**Date:** 2026-08-13
**Warehouse ID:** dec-170 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** A registered check's only output was membership in `failed` -- an empty-domain check, a skip, and a genuine enforced pass were byte-identical: absent from `failed`. rec-2915 measured 35 unconditional-success early-return sites across 24 checks. rec-3085 found two DQ-unavailable degradations swallowed into a silent WARN-and-return; `_check_graduation_guard` was separately found to be a DEAD GATE -- its `git diff HEAD` base is the empty working tree on every clean checkout, so it early-returned before it could ever enforce.

**Decision:**
1. **A second, additive output channel.** `scripts/checks/registry.py` gains `examined(count, unit=)`/`skipped(reason)` (public API for a check body, or a scaffold via `outcome_scope(name, kind=)`). `validation_result.py` brackets each dispatch, harvests the outcome into a per-run `CheckOutcome` row accumulator (`_ATTRIBUTIONS` lifecycle), and `validation-result.json` becomes schema_version 3 (`check_outcomes` rows + `ran/skipped/vacuous/undeclared_checks` rollups); `failed_checks`/`failed_check_attributions` keep their exact v2 shape (Decision 142 -- CI-RCA Priority-0 is a live consumer). ONE derivation function computes all five states so they cannot drift: an append to `failed` always wins as "failed"; else `skipped`->"skipped", `examined(0)`->"vacuous", `examined(n>0)`->"enforced", no declaration->"undeclared". Full rule/grain/schema live in `docs/contracts/check-accounting.yaml` (Decision 86/127 routing).
2. **Two defects fixed under the same channel.** `ensure_fresh_dq_results` and `_check_graduation_guard` now declare a skip on every dq-latest.json degradation (rec-3085) instead of WARN-and-return; the former's blanket `except Exception:` becomes a named credential classifier (mirrors `ops_portal.reader_transient`'s isinstance/message-fallback shape) -- a non-matching exception now appends to `failed` (new fail-closed behaviour). The guard now derives BOTH its changed-file set and its `git show` read from the same committed, push-aware base -- it starts actually enforcing in CI. Both hunks are independently revertible from the channel and from each other (see Rollback).
3. **A shrink-only adoption ratchet (rec-2915's structural-prevention half).** `validate_check_accounting` (both tiers) AST-scans every check's module for a declaration; fails an undeclared, unbaselined check. `config/check_accounting_baseline.yaml` grandfathers the 96 not adopted here (101 minus 5: `validate_test_coverage`, `validate_scheduled_agent_logs`, `validate_environment_taxonomy`, `validate_lambda_deploy_gating`, `_check_graduation_guard`) -- no marker escape (Decision 165), bounded by the guard's own frozen `_BASELINE_SEED` (a config edit alone cannot grow it), touch-it-fix-it (Decision 162 r3 shape).
4. **Registration now touches SEVEN surfaces, not six** -- `registry.py`'s docstring gains the declaration obligation as surface 7.

**Explicitly NOT committed:** fail-closed vacuity enforcement (Decision 163 -- declared-but-ungated is a real failure mode). **Ratchet limitation:** the AST scan proves a declaration exists in a MODULE, not on every exit path (rec-2915's 35-site measurement is exactly that gap). **Deferred trigger:** revisit fail-closed once a path-aware declaring-coverage metric clears a stated threshold.

**Reversal conditions:** (a) the channel proves noise (no vacuous finding drives a fix in a stated window) -- unwind channel+baseline+schema v3 TOGETHER; (b) the ratchet wedges unrelated PRs -- same combined unwind, never a config escape hatch; (c) the graduation-guard base fix blocks a legitimate PR -- revert that hunk alone, file the finding; (d) the credential classifier misses a real shape and reddens post-merge `main` -- revert that hunk alone, extend via a `source=ci_rca` rec (Decision 55, never inline). (c)/(d) revert independently of (a)/(b) and each other.

**Rationale:** The channel is a cheap per-call declaration harvested by the existing dispatch loop. A shrink-only, frozen-ceiling ratchet (not a config-editable allowlist) is what gives rec-2915's "unbuildable next instance" property teeth; fixing rec-3085 and the dead gate under the same Decision proves the observable on real, not only synthetic, data.

**Related:** Decision 104/169 (registry/manifest mechanism extended), Decision 168 (Class D contract mechanism), Decision 165 (marker-guard NOT bound into; `default_base_reader` reused as a bounded read only), Decision 159 (one-time-roster template), Decision 162 (frozen no-marker-escape / touch-it-fix-it precedent), Decision 155 (credential-classifier shape precedent), Decision 142 (v2 consumer contract preserved), Decision 163 (deferred fail-closed rationale), Decision 55 (forward-fix-not-workaround, condition (d)), Decision 86/127 (field-semantics routing). Roadmap ref: PLAN-validate-vacuous-pass-accounting (bundles rec-2915, rec-3089, rec-3085).

---

## Decision 169: scripts/validate.py's check facade is retired in favour of per-domain declarative manifests -- dispatch, tier sequencing, and the equivalence oracle all move off the aggregator (amends Decision 104) (Decided)

```yaml
number: 169
status: Decided
decided_date: "2026-08-11"
amends: [104]
significance:
  value: numbered_decision
  justification: A durable architectural commitment removing the check-facade mechanism Decision 104 installed and replacing its dispatch, tier-sequencing, and equivalence-oracle clauses with a new mechanism, with reversal-relevant consequences for how every future check is added.
```

**Status:** Decided
**Date:** 2026-08-11
**Warehouse ID:** dec-169 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** Decision 104 decomposed the pre-existing `scripts/validate.py` monolith into `scripts/checks/<domain>/` modules, but kept one coupling in place: `scripts/validate.py` retained a 187-SLOC block of 98 `from scripts.checks.<domain>.<module> import <name>` re-export statements (120 names), dispatched via `globals()[name](failed)`. Every new check therefore required an edit to `scripts/validate.py` -- the exact "adding a check touches the SLOC-capped aggregator" coupling Decision 104 was meant to end, just moved one level down from function bodies to import statements. The facade block's own growth rate (roughly 2 lines per check) meant `scripts/validate.py` was on the same upward SLOC trajectory Decision 104 was ratified to stop. Decision 104's byte-for-byte "Equivalence oracle" clause compounded this: `tests/test_checks_registry.py` froze the exact ordered check sequence for both tiers, so registry changes needed synchronous, coupled test edits -- a coupling that escaped the diff-aware `--pre` tier twice (rec-2673, rec-2674) because nothing bound registry.py changes to that frozen test file's selection.

**Decision:**
This amends Decision 104 by negating three of its clauses and replacing them with a new mechanism:

1. **The facade re-export clause is negated.** `scripts/validate.py`'s check-facade block (98 import statements exporting 120 names) is deleted outright. `scripts/validate.py` retains only the argparse surface, the recursion/branch guards, the fast-tier budget assertion, the non-check scaffolding steps, and the RETAINED `_common`/`_scaffolding` primitive re-exports (unaffected -- these back ~60 live patch targets and are not part of this Decision). `scripts/validate.py` drops from 499 to 314 SLOC, with no entry added to `config/sloc_budgets.yaml` (Decision 128: decompose, never raise).
2. **The `globals()[name](failed)` dispatch clause is negated.** Dispatch now resolves through `scripts.checks.registry.resolve(name)`, which imports the check's OWN DEFINING module and does a late-bound `getattr` at call time -- never caching the resolved callable, so `patch("<the check's defining module>.<name>", ...)` intercepts through a real dispatch pass exactly as `patch("validate.<name>")` did before. Adding a check now touches only `scripts/checks/<domain>/`: the module, its `@register(...)` call, and one `Entry` literal in that domain's `scripts/checks/<domain>/_manifest.py` -- `scripts/validate.py` is never touched again.
3. **The byte-for-byte "Equivalence oracle" clause is negated.** `tests/test_checks_registry.py`'s frozen ordered-tuple baseline is retired (the file is deleted; its nine test classes relocate to `tests/checks/registry/` and `tests/checks/_common/`, concern-split per Decision 131). Tier sequencing (`pre_sequence()`/`full_sequence()`) is now DERIVED from the 18 per-domain manifests plus a compact, checked-in per-segment domain-order key (Decision 169's own `_PRE_DOMAIN_ORDER`/`_FULL_SEGMENT_DOMAIN_ORDER` constants in `registry.py`) -- not hand-authored, and not required to match the pre-change byte order. MEMBERSHIP parity is still required and asserted (both tiers' check-name sets are unchanged except for one deliberate addition, `validate_check_manifests`); byte-parity of ORDER is explicitly NOT claimed or achievable, since domain-block grouping is a genuine reordering relative to the prior 45-non-contiguous-run sequence.

**New mechanism.** Each domain's `scripts/checks/<domain>/_manifest.py` declares a tuple of `Entry(name=, module=, attr=, ...)` literals (`scripts/checks/_schema.py`), naming its checks' defining module and attribute as BARE STRING LITERALS -- never a combined `"module:attr"` form, and never computed (an f-string or joined value is invisible to `scripts.dependency_graph`'s AST-based edge scan and would silently sever the driver->check graph edge, Decision 135's failure class). `docs/contracts/check-manifest.yaml` (a new Class D contract, Decision 168) owns this grammar; `scripts/checks/deps/validate_check_manifests.py` is its registered, tier-sequenced evaluator, enforcing the bare-literal rule and graph-node resolution by AST, and asserting `scripts.checks._schema.SEGMENT_TOKENS` equals the contract's own declared token set (derive-and-assert, so the dataclass and the contract cannot silently drift). `registry.all_checks()` eagerly imports every manifest-declared module AT CALL TIME (never at `registry.py`'s own import time, which would be a genuine circular import) to populate the `@register` roster for consumers like `validate_ci_rca_taxonomy` that need a complete roster without importing `scripts.validate`.

**Table-shaped vs logic-shaped decomposition precedent.** The facade-to-manifest conversion is a specific instance of a general, reusable call: convert a growing SET OF SIMILAR ITEMS from one-statement-per-item CODE into a DATA TABLE plus one generic interpreter, when ALL THREE hold:
   (a) the items are a flat collection of (name, target) pairs with no meaningful per-item control flow -- dispatch is purely by name lookup;
   (b) the file's growth is driven by ADDING MORE ITEMS OF THE SAME SHAPE, not by adding new behaviour; and
   (c) the consuming code can be written ONCE as a generic loop over the data, with no per-item special-casing required in the driver.
`scripts/validate.py`'s facade block satisfied all three (98 near-identical import statements, growth by check addition alone, one generic `globals()[name]` dispatch loop) -- this is why the manifest/`Entry` conversion applies here. `scripts/checks/_scaffolding.py` does NOT qualify: its scaffold functions (terraform checks, dependency health, DQ-freshness auto-invoke, budget-breach/bypass rec filing) have genuinely different control flow and side effects per function, failing condition (a) -- a table-shaped conversion would not fit. If `_scaffolding.py` ever needs decomposing under Decision 128's SLOC pressure, the correct instrument is a COHESION SPLIT (grouping related scaffold functions into separate modules, the ordinary Decision 80/104 facade-package pattern), never a manifest table.

**Reversal conditions:** (a) the per-domain manifest/`Entry` grammar proves unable to express a genuine check registration (e.g. a check needing per-item control flow beyond name/module/attr and tier/segment membership) -- extend the `Entry` dataclass, never fork a second dispatch mechanism; (b) `registry.resolve()`'s late-bound, non-caching contract is shown to regress test-interception reliability more than once -- fix the resolution path, never reintroduce a facade re-export as a workaround; (c) the domain-order derivation constants are shown to produce an UNDETERMINED sequence (two implementers deriving different rosters) -- pin the missing order explicitly, never fall back to hand-authoring the full sequence.

**Rationale:** The facade block was Decision 104's own acknowledged residual coupling -- every check addition still touched the one SLOC-capped file, just via an import line instead of a function body. Converting that coupling from CODE (98 statements, one per check) to DATA (18 small manifest files, one `Entry` per check, aggregated by one generic `registry.py`) is what actually ends the "adding a check touches `scripts/validate.py`" property Decision 104 targeted but did not fully close. The equivalence-oracle retirement follows from the same logic: a frozen byte-for-byte baseline is itself a facade-shaped coupling (every registry change needs a synchronised test edit), replaced here by membership-parity assertions plus a small set of explicit, checked ordering invariants (OD-0 through OD-6, `tests/checks/registry/test_sequences.py`) that do not grow with the check count.

**Significance:** clears the Decision 150 significance bar -- a durable architectural commitment removing a coupling mechanism Decision 104 installed and replacing it with a new one, with reversal-relevant consequences for how every future `scripts/checks/**` check is registered and dispatched; not a CD state-flip, operational fact, or field-semantics change (the full `Entry` grammar, the bare-string-literal rule, and the segment-token vocabulary live in `docs/contracts/check-manifest.yaml` per Decision 86/127 routing, not restated here).

**Related:** Decision 104 (amended -- the facade/dispatch/equivalence-oracle clauses this Decision negates), Decision 168 (the Class D contract mechanism `docs/contracts/check-manifest.yaml` uses), Decision 135 (the AST-based driver->check graph edge scan the bare-string-literal rule protects), Decision 131 (test-mirror convention the relocated `tests/test_checks_registry.py` classes follow), Decision 128 (decompose-by-default -- `scripts/validate.py`'s 314 SLOC, no budget entry added), Decision 165 (the shared raise-marker mechanism the `config/coverage_baseline.yaml` `baseline-lowered` marker on `scripts/validate.py` binds to, since the 187 deleted lines were fully-covered imports and their removal lowers the file's measured coverage below the prior dec-159 grandfather pin), Decision 159 (the coverage-baseline grandfather roster this Decision's marker amends one entry of; the `_CHECKS_REGISTRY_MECHANISM_FILES` retirement this Decision discharges, folding `scripts/checks/registry.py`/`scripts/checks/_common.py` into `scripts.test_coverage_checker`'s `_CONCERN_SPLIT_TEST_PACKAGES` instead), Decision 86/127 (rationale-in-Decision, field-semantics-in-contract routing this entry and `docs/contracts/check-manifest.yaml` follow). Roadmap ref: PLAN-validate-facade-manifest-dispatch (this Decision's carrying plan; PR2 of a two-PR split, PR1 merged as c2d0acd (#881)).

---

## Decision 168: Contracts gain a fourth class -- Class D mechanism contracts, gated on a declared evaluator that demonstrably reads the contract (amends Decision 118) (Decided)

```yaml
number: 168
status: Decided
decided_date: "2026-08-10"
amends: [118]
significance:
  value: numbered_decision
  justification: A durable architectural commitment adding a fourth contract class with an enforced, machine-checked obligation and reversal-relevant consequences for how docs/contracts/ governs mechanism content.
```

**Status:** Decided
**Date:** 2026-08-10
**Warehouse ID:** dec-168 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** audits/contract-first-governance-33c8667.yaml's migration step 3 (MECHANISM half) found docs/contracts/ was not a first-class destination for mechanism content: nothing gave a mechanism-shaped contract (marker-grammar.yaml, file-router.yaml, decision-entry.yaml, and 18 siblings) a real class in the CD.25 taxonomy, so 21 gate-visible files carried no declared shape and no enforced obligation -- CFG-03's finding, "a rule with no evaluator is not a rule," had no substrate to close against.

**Decision:**
1. **Class D joins A/B/C.** `scripts/contracts_schema.py` widens `ContractClass` to include `D` and `ContractStatus` to include `active` (grandfather-only: in force and consumed but never ritually ratified). A Class D contract requires both `subject` and `evaluator`; any `status: ratified` contract (any class) requires `ratified_via`. `scripts/contracts.py::load_contract_meta` validates only the `contract:` envelope, never constructing `ContractDocument` -- how a heterogeneous D body escapes the shared `extra="forbid"` model without relaxing it for A/B/C.
2. **The evaluator obligation is resolution by evidence of reading, not by mention.** `docs/contracts/contract-population.yaml` (this Decision's own self-hosting Class D contract, evaluator `{check: validate_contract_drift}`) defines the rule: a `{check: name}` evaluator resolves only if `name` is a sequenced, registered check whose module -- or a one-hop `scripts/` import -- contains the contract's basename as an executable-context string literal. This is not a new bar; it makes explicit the assertion CD.25's design already rested on.
3. **Grandfather-only forms, closed at birth and on kind-change.** `status: active` and `evaluator.none_grandfathered` may never be declared by a new file, and an evaluator may never regress from a resolving kind to `none_grandfathered` -- but `absent -> none_grandfathered` on a baseline-present file is permitted, since that is exactly the population sweep's own shape.
4. **Subject uniqueness and a downward-only ratchet.** Every Class D `subject` must be unique against the union of declared subjects and ritual contract ids; a file-router route's topic must equal its Class D file's subject. `contract-population.yaml`'s `ratchet.grandfathered_max` pins the gate-visible non-ritual population at 21 (verified independently four times), raised only through the ratified `# raise-approved: dec-NNN` mechanism already governing `config/sloc_budgets.yaml`.

**Reversal conditions:** (a) the evaluator-resolution rule proves unable to express a genuine evaluator (e.g. a non-Python agent surface the `agent_surface` kind cannot cover) -- extend the union, never bypass the resolution bar; (b) the population sweep (this Decision's own completing act, not performed here) finds the ratchet pin measured wrong -- correct the count, never round up; (c) Class D proves to be an escape hatch from Class A/B's per-field obligations despite the smuggling detectors -- tighten the shape rule.

**Rationale:** Class D stays cheaper to author than A/B by design (mechanism bodies are heterogeneous and cannot carry Class A's per-field obligations); what this Decision removes is the FREE choice -- a D contract now requires a guard that demonstrably reads it. This is EXPLICITLY NOT migration-step-3 completion: the 21 existing free-form files are not seeded here (forward-only), and this Decision does not fire Decision 167 clause 3. Subject uniqueness is a precision-optimal, recall-poor detector by honest design: it prevents FUTURE duplicate-subject claims and detects NONE of CFG-05's existing named instances, since there is no population to check uniqueness against until the sweep lands.

**Significance:** clears the Decision 150 significance bar -- a durable architectural commitment (a fourth contract class, an enforced evaluator-resolution mechanism, and a machine-checked ratchet) with reversal-relevant consequences; not a CD state-flip, operational fact, or field-semantics change (the full shape grammar, evaluator-kind union, and change-detection rules live in `docs/contracts/contract-population.yaml` per Decision 86/127 routing, not restated here).

**Related:** Decision 118 (the CD.25 ritual this Decision extends with a fourth class), Decision 86 / Decision 127 (field-semantics-in-contract routing this Decision's own field-semantics home follows), Decision 165 (the shared raise-marker mechanism the ratchet binds to as a sixth consumer), Decision 128 (decompose-by-default -- the `_population.py` split), Decision 104 (the check-registry pattern the evaluator-resolution rule reads). Roadmap refs: audits/contract-first-governance-33c8667.yaml findings CFG-03/CFG-04/CFG-05/CFG-09 (partially addressed; population sweep remains open), tier_item T2.56 (not_started; this Decision closes none of its criteria), rec-3054 (the standing consumer of this Decision's filed drain recommendation).

[Amendment 2026-08-16: clause 3's none_grandfathered half is inoperative -- rec-3059 wave 2 (PLAN-class-d-enforcers-wave-2) converted the last two contracts carrying the grandfather-only evaluator.none_grandfathered kind to resolving evaluators and then retired the kind itself: it is no longer declarable at all. See docs/contracts/contract-population.yaml's retirement_notes.evaluator_none_grandfathered for the live record (what, why, reversal path).]

---

## Decision 167: Decision-entry flow governance -- typed metadata envelope, required Significance routing claim, and a WARN-tier per-entry authoring size norm (amends Decision 150 and Decision 160) (Decided)

```yaml
number: 167
status: Decided
decided_date: "2026-08-07"
amends: [150, 160]
significance:
  value: numbered_decision
  justification: A durable architectural commitment installing three enforced governance mechanisms with reversal-relevant consequences.
```

**Status:** Decided
**Date:** 2026-08-07
**Warehouse ID:** dec-167 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** The decision corpus's sole front-door control on new-entry SHAPE (the Decision 150 Significance bar) was self-certified prose with no machine check, and neither Decision-134/166 size ceiling paced how fast an INDIVIDUAL new entry grows the corpus -- only its total stock. audits/contract-first-governance-33c8667.yaml findings CFG-01/CFG-03/CFG-07 (migration step 2): a new entry could mint a numbered Decision without ever declaring which of the four significance.routing rows applies, and no per-entry byte norm bent the corpus's accrual RATE the way Decision 160 point 11 named as the missing lever.

**Decision:**
1. **Typed metadata envelope.** A new decision entry (absent from the origin/main baseline) carries a fenced ```yaml metadata envelope immediately after its heading (docs/contracts/decision-entry.yaml `metadata_envelope`), read by `scripts/decisions_md.py`'s `parse_decisions_md` in PREFERENCE to the legacy bold-marker/title grammar, which remains the permanent fallback for every entry without one -- additive, never a cutover. `scripts/checks/decisions/validate_decision_entry_conformance.py` enforces well-formedness, the envelope's `number` against its heading, and envelope/bold-marker conflicts on new entries only; a Decision 149 compacted stub is exempt.
2. **Required Significance routing claim.** The envelope's `significance` field is required on every new entry: a value naming one of `decision-entry.yaml`'s four `significance.routing` tokens, plus a non-empty one-line justification, read from the contract at check time. `operational_fact` and `field_semantics` are REJECTED outright -- both routing rows' own text says the content is "Never a numbered Decision," so claiming either on an entry that is by construction minting one is a contradiction the check catches rather than trusts.
3. **Per-entry authoring size norm, WARN tier.** A new entry over 6,144 bytes (heading-to-next-heading UTF-8 span) triggers a named WARN from `validate_decisions_size`, never a `--pre` failure -- a DATED pre-commitment, not the accrual-rate lever itself: Decision 160 point 11 named a per-entry norm as the only lever that bends the corpus's growth RATE, and this clause explicitly disclaims that the lever is installed until migration step 3 (destination readiness) flips it to hard-fail.
4. **Routing rule and standing commitment homed in the contract.** The three-question routing rule (durable commitment? reversal-relevant? unclaimed by another row?) and its standing-commitment clause live in `decision-entry.yaml`'s `significance.routing_rule` / `significance.standing_commitment` keys, machine-checkable rather than asserted only in this prose.

**Reversal conditions:** (a) more than 2 of the first 10 new entries authored under the 6,144-byte cap cannot fit their ruling/rationale/reversal content without losing DECISION substance -- retune the cap value or abort the norm, never raise it silently to fit a single entry; (b) two or more entries land in the SAME PR specifically to evade the per-entry cap (split-then-recombine) -- close the loophole at the check, not by raising the cap; (c) T1.5's portal cutover retires the flow this envelope feeds -- these obligations retire with it; (d) migration step 3 never lands and the cap stays WARN-tier indefinitely -- re-audit whether the lever does any work at WARN tier alone. Per Decision 166 point 6 / Decision 145's own precedent: the response to cap pressure is compaction or trimming Related pointer blocks, never a raise to fit.

**Rationale:** The envelope and the Significance claim are the same shape decision-scout already reads machine-readably for triage (category_tags, triage_excerpt) -- extending that machine-readability to the routing claim itself closes the "self-certified with no record" gap CFG-03 named. The WARN-tier cap is staged behind a destination-readiness gate (migration step 3) so the pressure is felt before the lever is armed to fail builds -- the audit's own sequencing warning against pressure before a landing spot exists for it.

**Significance:** clears the Decision 150 significance bar -- a durable architectural commitment (a typed envelope grammar, an enforced Significance routing claim, and a dated WARN-tier size norm, each backed by a `--pre`-registered check) with reversal-relevant consequences; not a CD state-flip, operational fact, or field-semantics change (field shapes and the exact byte value live in `docs/contracts/decision-entry.yaml`, not restated here).

> **Update (2026-08-17):** The f2 routing-consistency lint proposed by
> audits/contract-first-governance-33c8667.yaml's amendment is REJECTED, not built. Four
> independent consults found it malformed on construct-validity grounds -- proxy P1 duplicates
> the already-armed per-entry size cap (clause 3) and adds no discriminating signal beyond it;
> proxy P2 is anti-directional, since Decision 168 already rewards a `docs/contracts/` reference
> and the window's top P2 scorer is already correctly classified -- and on Goodhart grounds:
> proxy P3 would reward an agent author for trimming legitimate enforcement references to clear
> the warning, degrading the very traceability Decision 168 protects. The deterministic subset
> already deployed by clauses 1-4 above (the envelope, the required routing claim, and the
> per-entry size norm) is the permanent control; no lint is added alongside it.

```yaml reversal-conditions
decision: 167
review_by: 2026-11-17
on_trigger: "re-decide via /plan whether the deterministic subset still suffices or the f2 routing-consistency lint should be reconsidered; update or re-arm this stanza"
conditions:
  - id: mis-routed-past-both-gates
    kind: manual
    description: "A post-167 entry is demonstrated mis-routed past BOTH the decision-entry conformance check and the plan-critique category-consistency verdict (.claude/skills/plan-critique/SKILL.md section 12p) -> the deterministic-subset-only control proved insufficient; re-open the routing-consistency-lint question with the new failure instance as evidence."
```

**Related:** Decision 150 (the Significance bar enforced machine-readably), Decision 160 (point 11's accrual-rate lever, installed here at WARN tier only), Decision 134 (the two stock size ceilings this norm sits alongside), Decision 145 (the never-raise-to-fit precedent), Decision 149 (the compacted-stub exemption), Decision 84 (warehouse-safety boundary keeping `significance` index-only), Decision 153 (the shared, memoized baseline read). Roadmap refs: audits/contract-first-governance-33c8667.yaml findings CFG-01/CFG-03/CFG-07 (closed), rec-2934 (resolved by `per_entry_size_norm`), tier_item T2.56 (eventual owner of this corpus's shape; closes none of its criteria here).

---

## Decision 166: Structural-size governance extends beyond Python -- one parameterized class engine over a classified non-Python file taxonomy (completes Decision 43's declared scope; builds on Decisions 102/128/130) (Decided)

**Status:** Decided
**Date:** 2026-08-04
**Warehouse ID:** dec-166 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** audits/size-governance-expansion-3dee4a5.yaml findings SGE-01 (terraform has never been scanned by any size gate), SGE-02 (machine-consumed config registries are ungoverned) and SGE-04 (agent-consumed contracts accrete unguarded): Decision 43 declared structural size limits "across all repository code, prompts, and agents" and Decision 130 extended the scan whole-repo, but both were scoped to Python by implementation only -- `iter_gated_py_files` skips every non-.py file, and terraform's presence in `_SLOC_EXCLUDE_DIRS` excluded Python under `terraform/`, never `.tf` files themselves.

**Decision:**
1. **One engine, one registry, one guard.** `config/structural_size_budgets.yaml` carries a first-match-wins class table (twelve classes: generated, terraform, config, contracts, ci_workflows, shell, lambda_manifests, roadmaps, workflow_outputs, test_fixtures, data_query, residual) plus two flat per-file grandfather rosters (`budgets:`, `long_line_budgets:`). One new check, `validate_structural_size_limits`, enforces it in BOTH presubmit tiers, unscoped. One raise-guard, `validate_structural_size_budget_raises`, binds to the shared `scripts/checks/_marker_guard.py` module (Decision 165) as its SIXTH CONSUMER via two section-scoped `RegistrySpec`s -- never a sixth copy of the marker-guard mechanism -- and is ALSO registered in BOTH presubmit tiers (`validate_coverage_baseline_edits` / `validate_mypy_baseline_edits` precedent: both `pre=True, full=True`), a deliberate divergence from the `validate_sloc_budget_raises` precedent (`--pre`-only). The five incumbent size gates (SLOC, prose, roadmap, decisions, composite bodies) are UNCHANGED; this Decision records a convergence path but does not execute one.
2. **Classification is layered, first-match-wins:** exclusions (suffixes `.py`/`.md`, vendored/tooling directories), then a provenance override (a narrow "GENERATED -- DO NOT EDIT" banner in the first 10 lines, or membership in the checked-in `generated_pinned` list for known machine-regenerated files that carry no banner), then the ordered class table's directory+extension globs, then a mandatory `residual` row governing any unmatched tracked file at the implicit 500-effective-line default (govern-by-default, not block-until-classified or leave-ungoverned).
3. **Limits.** 500 effective lines / 2,000-character longest line for every governed class. The `roadmaps` class row's limit is also 500 -- NOT the audit draft's proposed 6,000 class ceiling for that row, which is a sibling slice's (SGE-05) call to ratify, not pre-empted here. `docs/ROADMAP-PLATFORM.yaml` is deferred by EXACT FILENAME to its incumbent `validate_platform_roadmap` gate (Decisions 114/147) and is not measured by this engine; `docs/ROADMAP-PRODUCT.yaml` IS measured and is grandfathered at its current size (4,707 effective lines) in `budgets:`.
4. **Exemptions key on provenance and production pattern, never on consumer tier.** `generated` (no agent hand-edits a generated file; governance belongs on the producer), `workflow_outputs` (`docs/plans/**`, `audits/**` -- produced whole per run, post-merge edits are narrow field flips, never whole-file comprehension edits) and `test_fixtures` (captured data asserted against, sometimes byte-for-byte; a cap on captured reality is an NS-B tax) carry no roster and no line-length companion.
5. **One-time grandfather, sixteen entries across two rosters (thirteen in `budgets:`, three in `long_line_budgets:`; fifteen DISTINCT keys, since `config/agent/verification_registry/registry.yaml` is seeded in both), each carrying an inline `# raise-approved: dec-166 <reason>` marker.** This is a roster-expansion beyond the audit's own draft, which named twelve entries on one unit (effective lines only): a re-census at the installing HEAD found three governed-class files also breaching the 2,000-character long-line companion that the audit's workflow_outputs-only long-line census never reached. The fifteen distinct roster keys, named here VERBATIM (required: `_expand_ancestor_candidates` generates no ancestor candidate for a 2-segment key, so a directory mention cannot authorize one -- five of these fifteen are exactly that shape):
   - `terraform/iceberg_tables.tf`
   - `terraform/bootstrap/github_ci_apply.tf`
   - `terraform/personal/oidc.tf`
   - `terraform/data_pipeline.tf`
   - `terraform/personal/platform_roles.tf`
   - `config/agent/verification_registry/registry.yaml`
   - `config/agent/data_quality/decisions/ops_recommendations.yaml`
   - `docs/contracts/iam-simulate-fixture.yaml`
   - `docs/contracts/ops_recommendations.yaml`
   - `.github/workflows/reconcile.yml`
   - `.github/workflows/terraform-apply-sandbox.yml`
   - `docs/intent-migration/MANIFEST.yaml`
   - `docs/ROADMAP-PRODUCT.yaml`
   - `logs/.retro-lite-log.jsonl`
   - `logs/.execution-step-telemetry.jsonl`
6. **`config/agent/verification_registry/registry.yaml` is seeded at a CALIBRATED 6,000-effective-line CEILING, not a grandfather at its current measured size (3,987 effective lines at landing, including this Decision's own 12 graduation rows).** Measured growth: 22 commits in 60 days, every one append-only with zero deletions, 66-167 lines each, roughly 1,200 lines/month -- because every graduating `/implement` plan appends to it, including this one. A 500-line cap grandfathered at current size would fail the very next graduating plan, and "each append is a reviewable cited raise" is false: `scripts.checks._marker_guard.authorization_failure` matches the entry KEY, never its VALUE, so one marker permanently authorizes every future bump of that entry -- Decision 128's own Problem statement reproduced in YAML form. The 6,000 ceiling buys roughly 1.7 months of runway at the landed size. **Pre-commitment:** when the 6,000 ceiling fires, the response is the CD.29 mark-then-drop archival lifecycle (a recommendation for which is filed by the same implementing session as this Decision), NEVER a second raise -- mirroring Decision 145's own warning that a second stopgap raise signals the structural fix is overdue, not a routine act to repeat. This is the audit's own prescribed relief valve for this class (`class_verdicts.config.relief_valve`: "archive/retire entries per lifecycle (valves 4/5); compact resolved rows; loud cited raise; decompose only where cohesion permits"), not an exception to the rule this same Decision installs -- decomposing this specific file into a facade is explicitly Python-specific machinery (the audit's Q4 sound-needs-generalization finding) and does not transfer to a YAML append-only registry.
7. **Amendment: Decision 130 clause 1's `terraform` entry in `_SLOC_EXCLUDE_DIRS` was an `iter_gated_py_files` PYTHON-SCAN ARTIFACT, not a structural-axis exemption.** It excluded Python source files located under `terraform/`, never `.tf` files themselves -- absence of coverage was absence of scanning, not a recorded exemption (the audit's READ FIRST 3, confirmed). This structural-size class engine is the first gate to ever scan `.tf` files.
8. **Amendment: Decision 43's declared "all repository code, prompts, and agents" scope is now implemented for the non-Python hand-authored structured-file population this engine covers** (terraform, config, contracts, ci_workflows, shell, lambda_manifests, roadmaps, data_query, residual). Markdown remains wholly out of scope (a future markdown decision inherits this taxonomy's shape, not its unit, per the audit's draft clause 9).
9. **Amendment: Decision 160 point 9's committed `docs/decisions-index.json` byte pin is reassessed, exactly as that point invited** ("A future owner should reassess whether this indirect bound remains adequate as the corpus grows past the header ceiling's current runway"). This Decision's own installing PR is the acute instance: the prior 110,000-byte pin had only 236 bytes of headroom before this entry existed and is mathematically exhausted -- verified, not assumed (a maximally-terse version of this very entry, title and Problem section both compressed far below the 320-character triage-excerpt cap, still regenerated the index to 110,151 bytes). `tests/test_decisions_index.py`'s pin is RE-DERIVED (not bumped on faith) to 131,000 bytes: a live term (120-row `live_max_h2_headers` ceiling x 764 measured bytes/row, indent=2 pretty-printed) plus an archive term (54 rows -- twice the current 27-row archive population, a multi-quarter buffer -- x 726 measured bytes/row), full arithmetic recorded in the test module itself. Precedent: Decisions 159 and 160 both landed in this identical acute shape -- an entry whose own landing would fail the gate it is part of -- by shipping the governing entry and the guard change in the same PR; this Decision does the same. `docs/decisions-index.json` is recorded here as a T1.5-INTERIM surface: Decision 160 point 13 already names it so ("This arrangement is INTERIM, not the T1.5 portal cutover"), and T1.5 c1 -- per that item's own exit criteria, "T1.5 c1 owns swapping its bounded index-plus-targeted-reads mechanism for a queried tool call" -- is the single owner of retiring decision-scout's Phase 1 index read once the DuckLake ops-decisions portal cutover lands; T1.5 itself is STRATEGIC and CD.17-frozen (AGENTS.md Temporary Operational Constraints), so this re-derived pin is not a permanent fixture but persists at least that long. The archive term's structural fix -- skeleton rows for `live: false` entries, dropping the `triage_excerpt`/`category_tags` fields decision-scout never reads for archived rows -- is deferred to rec-3012 (filed alongside this Decision), not built here: the human explicitly chose the minimal scope extension (this test file only) over also thinning the generator in the same PR, to limit new surface on this keystone slice. NOTED, not relieved by this point: the 120-header `live_max_h2_headers` ceiling itself (Decision 134 clause 2) measures 119/120 live headers at this entry's landing -- binding within ONE more live entry, not two, regardless of this byte-pin re-derivation; only an operator-disposed archival wave under Decision 146 relieves it, and queuing one is out of this Decision's scope.

**Reversal conditions:** (a) the engine false-positives against a genuinely-conformant shape more than once per class-year -- fix the classifier or the class row, never widen the marker escape; (b) a measured fast-tier budget breach attributes materially to the census walk -- move the engine full-tier-only (the raise-guard stays fast-tier); (c) a class row's recorded `actual_purpose` loses its referent (its consumer is rebuilt or retired) -- retire that ROW, Decision-160 style; the engine survives its classes; (d) the grandfather roster shows net growth over any 90-day window -- re-audit the gate design rather than raising budgets; (e) the assumed NS-A harm (lower-tier mis-edits scaling with file size) is ever OBSERVED in a governed non-Python class -- revisit the audit's Q6 calm sequencing toward active drain waves; (f) a second raise fires on `config/agent/verification_registry/registry.yaml` past its 6,000-line ceiling -- this re-audits the registry's design (its grain, its retirement discipline, whether CD.29 needs to be exercised sooner) rather than renewing the ceiling a second time; (g) point 9's re-derived 131,000-byte `docs/decisions-index.json` pin is itself approached again -- the correct response is landing rec-3012 (archive-row skeletonization) first, never a third bump on faith, unless T1.5 c1 has by then retired the surface entirely.

**Rationale:** The ratchet family (registry, implicit default, one-directional movement, marker-gated raises, bounded grandfathers) is sound and portable -- proven end to end by rec-2709 draining Decision 130's own 24-file `tests/` grandfather to a single marked survivor -- and Python-specific exactly where the relief valves live: this repository already runs six distinct relief valves, and each class here is assigned its honest one (decompose for terraform's native multi-file roots; archival lifecycle for the verification registry; rotation for tracked jsonl journals) rather than inheriting decompose-into-a-facade uniformly. One parameterized engine, not per-class replication, because the raise-marker guard was already quintuplicated across five incumbent gates before Decision 165 consolidated it (SGE-07) -- a sixth copy here would have reproduced exactly the defect that consolidation closed. Exemptions key on provenance and production pattern, never on which model reads a file, because the workflow_outputs exemption (82 percent of the audit's affected population) rests on a traced edit pattern -- narrow field flips, never whole-file comprehension -- not on a claim about model capability.

**Significance:** clears the Decision 150 significance bar -- a durable architectural commitment (a new, whole-repo-completing size-governance class engine, enforced in both presubmit tiers, with a calibrated ceiling and a pre-committed drain mechanism for its own highest-pressure roster entry), with reversal-relevant consequences and explicit reversal conditions; not a CD state-flip, operational fact, or field-semantics change (point 3 above states the headline effective-line and long-line-character limits for orientation; the full class-by-class table, counting rule and glob grammar are field semantics that live in `config/structural_size_budgets.yaml` per `decision-entry.yaml`'s `significance.routing.field_semantics` row, not restated here).

**Related:** Decision 165 (the shared `scripts/checks/_marker_guard.py` module this engine's raise-guard consumes as its sixth binding, never a sixth copy), Decision 43 (the original "all repository code" scope this Decision completes for the non-Python population), Decision 130 (whole-repo scan intent and the one-time-grandfather form this Decision reuses; clause 1's terraform exclusion clarified in point 7 above as a Python-scan artifact, not a structural exemption), Decision 128 (decompose-by-default and the raise-marker discipline this engine's rosters follow; the authorization-matches-key-not-value property that motivates the calibrated verification-registry ceiling in point 6), Decision 102 (the downward-only ratchet precedent), Decision 104 (the check-registry pattern `validate_structural_size_limits`/`validate_structural_size_budget_raises` follow), Decision 114 / Decision 147 (the `docs/ROADMAP-PLATFORM.yaml` fixed-ceiling-plus-compaction precedent this engine defers to by exact filename, never re-governs), Decision 150 (the significance bar this entry clears), Decision 153 (the fast-tier budget this engine's ~0.1-0.2s census fits comfortably inside), Decision 127 / Decision 86 (rationale-in-Decision, field-semantics-in-contract routing this entry and `config/structural_size_budgets.yaml` follow), Decision 48 (V2 verification tier), Decision 160 (amended at point 9 above -- the `docs/decisions-index.json` byte-pin reassessment its own point 9 invited; point 13's shipped-in-the-same-PR precedent this entry follows), Decision 159 (the sibling acute-landing precedent Decision 160 itself followed), Decision 134 clause 2 (the `live_max_h2_headers` ceiling point 9's live term is bounded by, and the noted-not-relieved 119/120 measurement), Decision 146 (the operator-disposed archival wave that is the only real relief for the header ceiling), Decision 145 (the stopgap-vs-permanent-fix distinction point 9's T1.5-interim framing deliberately does NOT reproduce, since a dated successor already exists). Roadmap refs (not DECISIONS.md entries): audits/size-governance-expansion-3dee4a5.yaml findings SGE-01/SGE-02/SGE-04 (closed by this Decision), SGE-03/SGE-05 (sibling slices that depend on the class table this Decision installs and land after it), SGE-07 (Decision 165's own finding, the marker-guard consolidation this engine consumes), rec-2928 (the `.yml`/`.yaml` glob-spelling defect this engine's every YAML-matching class row covers both spellings against), CD.29 (the verification-registry archival lifecycle named as the point-6 pre-commitment's drain owner), rec-2968 (open -- the prose prediction of point 9's now-confirmed dynamic), rec-3001 (the confirmed-blocking measurement this point 9 resolves), rec-3012 (open -- the deferred archive-row-skeletonization structural fix), rec-3020 (open --
code-review round 1 LOW finding: `_classify.py` fails open if the residual class row is ever
removed), rec-3021 (open -- code-review round 1 LOW finding: `_marker_guard.py`'s pre-existing
"origin/main unreachable" message is misleading for a brand-new registry's own installing PR),
T1.5 (the STRATEGIC, CD.17-frozen portal cutover that eventually retires `docs/decisions-index.json` entirely, named in point 9 as the surface's actual successor).

---

## Decision 165: Raise-marker validation narrows from existence to authorization; the retroactive scan is load-bearing over present markers (amends Decision 128 clause 3, amends Decision 159, amends Decision 161 clause 4, amends Decision 162 R3, and amends Decision 149) (Decided)

**Status:** Decided
**Date:** 2026-08-04
**Warehouse ID:** dec-165 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** Audit finding SGE-07 (audits/size-governance-expansion-3dee4a5.yaml): all five raise-marker guards (`validate_sloc_budget_raises`, `validate_prose_budget_raises`, `validate_coverage_baseline_edits`, `validate_mypy_baseline_edits`, and R3 of `validate_composite_action_shell_bodies`) validated only that a cited `# raise-approved: dec-NNN` / `# baseline-lowered: dec-NNN` / `# baseline-raised: dec-NNN` marker named a `## Decision NNN:` header that EXISTS -- never that the Decision's body actually AUTHORIZES the specific entry being marked. rec-2974 found the live instance: `config/sloc_budgets.yaml`'s `tests/test_checks_registry.py` entry cited `dec-161` (a mypy-gate Decision whose body never mentions this path or `tests/` at all), when `dec-159` (whose body names the path verbatim) is what actually authorizes it.

**Decision:**
1. Marker validation narrows from EXISTENCE to AUTHORIZATION across all five guards, consolidated onto one shared module (`scripts/checks/_marker_guard.py`) rather than five independent copies of the fix. Authorization mechanics (key-side ancestor-prefix generation, the >=2-segment floor, the Decision 149 supersession hop, the moved-from same-diff proof, the retroactive-scan token scoping) are field semantics and live in `docs/contracts/marker-grammar.yaml`, not restated here.
2. The scan is RETROACTIVE, not diff-only: every currently-committed marker bearing a guard's own token is authorization-checked on every `--pre`/full run, regardless of whether it changed in the diff under validation. This is what makes a persisted marker load-bearing and is required to catch rec-2974's own instance -- a diff-only guard structurally cannot re-examine an already-merged, unchanged entry. Amends Decision 128 clause 3 ("marker persistence is not required... authorized at the diff-vs-base moment") explicitly: a marker that IS present is now retroactively load-bearing, though it still need not persist for the diff-time gate alone.
3. Amends Decision 159 clause 3 (the coverage tamper guard), amends Decision 161 clause 4 (the mypy tamper guard, including its first real implementation of the `moved from <old-path>` same-diff proof), and amends Decision 162 point 3 (composite R3's marker escape) to the same authorization standard, via the shared module each now binds to.
4. Retroactive scope is justified by SGE-07's own acceptance clause ("a marker citing a Decision whose text nowhere mentions the file fails; rec-2974's instance is caught retroactively") and bounded against this repo's forward-conformance precedent (Decision 151: prior grammar changes here have been forward-enforced only) by a frozen, EMPTY-at-install grandfather hook (`RETRO_SCAN_GRANDFATHER`) -- the measured install-state marker population (3 total: one sloc, two prose) is fully authorization-clean post-fix, so retroactive enforcement costs zero migration on day one. Growing the hook later is a reviewed code edit, never a config edit.
5. rec-2974 itself is fixed at the source in this same change: the `tests/test_checks_registry.py` entry's marker is retargeted from `dec-161` to `dec-159`.

**Rationale:** An existence-only check on a marker whose entire purpose is to gate an authorization decision is a category error -- it proves a citation was well-formed, not that the citation justifies the change. Consolidating five copy-pasted guards onto one shared module before upgrading them (rather than patching each independently) closes the drift risk that produced five near-identical implementations in the first place, and gives the not-yet-built structural-size governance engine (Slice B) a stable, single binding surface instead of a sixth copy.

**Reversal conditions:** If the retroactive scan's grandfather hook grows past a small, explainable handful, that is a signal the population assumption (rare, already-clean) no longer holds and the mechanism needs re-audit, not a bigger hook -- mirrors Decision 159/161's own reversal conditions. If a future declared `Governs:` marker (the design alternative considered and deferred at plan time) lands, this mention-based authorization becomes a fallback rather than the primary mechanism.

**Related:** Decision 128 (the raise-marker mechanism this amends clause 3 of), Decision 159 (coverage tamper guard amended), Decision 161 (mypy tamper guard amended, including clause 4's first implementation), Decision 162 (composite R3 amended), Decision 149 (the compaction lifecycle whose compact-in-place interaction the supersession hop closes), Decision 151 (the forward-conformance precedent this retroactive scope departs from, bounded by the empty grandfather hook), Decision 134 (the shared decisions_md.py parser this module consumes, DAF-03 / clause 3), Decision 104 (`_common.py`'s five-primitive reservation; this module's top-level placement), Decision 86/127 (contract-vs-Decision routing this entry and `docs/contracts/marker-grammar.yaml` follow), Decision 130 (whole-repo SLOC scope; the raise-approved grammar's precedent), Decision 153 (composite guard's subprocess-free fast-tier budget, preserved). Bundled: rec-2974. Roadmap ref: audits/size-governance-expansion-3dee4a5.yaml finding SGE-07 (not a DECISIONS.md entry).

---

## Decision 164: Executor agentic personas route to LiteLLM tiers, not `claude -p`; reopening that split collapses the viable persona substrate set to the CLI-hosting class (amends Decision 122 and Decision 116) (Decided)

**Status:** Decided
**Date:** 2026-08-03
**Warehouse ID:** dec-164 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** Decision 122 ratifies the executor steady state as LiteLLM tiers (Tier 1 DeepSeek-direct,
Tier 2 Anthropic-direct) and confines Decision 116's `claude -p` split to scheduled agents. But Decision
116's own criterion for that split is agentic-vs-non-agentic tool use, and T4.2's personas are agentic
tool-using loops by exactly that criterion -- so 116's principle reaches the personas on its face while 122
routes them the other way, and no recorded statement addresses the conflict. A rationale does exist, but
only distributed across three surfaces, none of which states it as a principle:
`cost_projection.current_scale.breakdown.deepseek_executor_inference` in docs/ROADMAP-PLATFORM.yaml prices
executor volume at ~$0.05/rec on DeepSeek-direct; Decision 116's own reversal condition names executor
Tier-2 and scheduled `claude -p` as competing draws on one shared Max pool; and Decision 122 cites Decision
47's lock-in lesson. Separately, nothing anywhere records the CONSEQUENCE of reopening the question. Filed
against audits/executor-substrate-and-billing-shape-ad02653.yaml ESB-03 (medium, CONFIRMED).

**Intent:** T4.2's Lambda personas are agentic tool-using loops, so Decision 116's agentic criterion reaches them on its face; they route to LiteLLM tiers anyway. Reopening that toward `claude -p` collapses the viable persona substrate set to the CLI-hosting class, eliminating the CD.27 incumbent and its named fallback at once.

**Decision:** Executor agent personas (T4.2) route to the Decision 122 LiteLLM tiers. Decision 116's
agentic/non-agentic split governs SCHEDULED AGENTS ONLY and does not extend to the executor personas,
notwithstanding that those personas satisfy 116's agentic criterion. The same criterion yields a different
answer on each side because the two sides differ in DRAW SHAPE, not in agenticity:

- Volume and unit price. Scheduled-agent traffic is a handful of invocations per agent per day; executor
  traffic is per-rec and per-turn, priced at ~$0.05/rec on DeepSeek-direct. A `claude -p` route bills
  against the fixed, non-rollover Max x5 programmatic pool, so at executor volume it converts a metered
  marginal cost into contention for a fixed monthly allowance -- exactly the contention Decision 116's own
  reversal condition already names.
- Substrate freedom. An HTTP transport (LiteLLM) is runtime-agnostic; a CLI transport requires a
  CLI-hosting runtime. Routing therefore constrains substrate, and the executor is the side of the split
  whose substrate question CD.27 layer 2 still owns.
- Escape-hatch preservation. Decision 47's lock-in lesson is answered on the executor side by keeping
  Anthropic-direct warm as Tier 2 behind the same LiteLLM surface -- a provider swap, not a process-shape
  swap. A `claude -p` route would reintroduce that coupling at the process layer.

Reopening this to route personas via `claude -p` is not a transport-level change: it eliminates most of the
candidate substrate set. Of the five candidates assessed in
audits/executor-substrate-and-billing-shape-ad02653.yaml Q2a `cli_hosting`, only `long_running_container`
and `hosted_cli_runner` can host a session-shaped CLI outright. The other three are `can_host_cli:
conditional` and degenerate under it -- including the CD.27 incumbent `durable_functions` (checkpoint
granularity collapses to the whole CLI run) and the CD.27 fallback specified under ESB-02
(`self_checkpointed_lambda_dynamodb`, same per-invocation ceiling). A reopen would therefore retire the
incumbent substrate and its own contingency in one move. Any future proposal to reopen persona routing MUST
price that collapse explicitly; a reopen that does not is incomplete on its face.

This is a governance-record change only: it moves no traffic, changes no tier, provider or substrate, and edits
no code. Its shape follows Decision 133 -- the conversion of a cited-as-given premise into a conscious,
reversal-conditioned choice -- and it discharges Decision 75's requirement that carrying an existing frame
forward be a conscious choice rather than an inherited one, which is exactly the condition Decision 122's
persona routing was in: decided, but only implicitly against Decision 116's principle.

**Reversal conditions:** revisit persona routing if (a) Decision 116's own reversal condition fires --
shared Max-pool contention between executor Tier-2 and scheduled `claude -p` -- AND the resolution under
consideration moves personas rather than scheduled agents; or (b) CD.27 layer 2 ratifies onto
`long_running_container` or `hosted_cli_runner`, which removes the substrate-collapse cost above and makes
the routing question genuinely open again; or (c) DeepSeek-direct unit pricing moves enough to void the
volume argument (Decision 122's own >5x pricing trigger). Each of these reopens the QUESTION; none of them
pre-decides the answer.

**Related:** Decision 122 (amended -- the executor-tier ratification this rationale is addressed to),
Decision 116 (amended -- its agentic/non-agentic principle is scoped to scheduled agents explicitly here
rather than by implication), Decision 47 (lock-in lesson; archived and superseded, cited for the reasoning
Decision 122 inherits from it, not as an active decision), Decision 84 (DECISIONS.md canonical + portal
backfill), Decision 86 (rationale routes to a numbered Decision, never a new prose doc), Decision 55
(RCA-first), Decision 150 (clause 1 -- the significance bar this entry is adjudicated against; clause 2's
batch-wave form does not apply, since this is not a CD state-flip), Decision 160 (the bounded
decision-scout retrieval model that makes a numbered entry findable where an in-body amendment is not;
points 9 and 11's index pin and header runway are the budget this entry spends), Decision 151 (the
Intent marker used above -- its Problem -> Intent -> Decision placement, and clause 3(ii)'s rule that
after merge this Intent is never rewritten but accretes dated, source-cited annotations inside itself,
under clause 3(iv)'s ~3-clarification / ~120-150-word cap), Decision 163 (a
universal, exceptionless obligation is enforced structurally, not gated -- the reopen obligation stated
above is a completeness standard on a future argument, not a gated step in a mechanized flow: it has no
diff-detectable trigger, so this entry deliberately claims no structural carrier for it), Decision 75 (frame-lock
anti-pattern -- its Constraints clause is the standing authority for carrying a frame forward
consciously), Decision 133 (the in-corpus precedent for a governance-record-only entry that converts a
cited-as-given premise into a conscious, reversal-conditioned choice). CD.27 layer 2 (the substrate set a
reopen would collapse), CD.28 (ratified as Decision 122), tier_items T4.2 and T4.12 (the executor and
scheduled sides of the split).

[Amendment 2026-08-19: Decision 173 restates this entry's rationale as SHAPE claims -- metered
marginal cost versus a fixed, non-rollover allowance, and an HTTP transport (runtime-agnostic)
versus a CLI transport (needs a CLI-hosting runtime) -- so the argument and its substrate-collapse
pricing obligation survive a change of which provider fills either tier. The DeepSeek/Anthropic
naming above is the then-current selection, not the premise. Two reversal conditions are re-read
accordingly: (c)'s "DeepSeek-direct unit pricing" is read as the PRIMARY role's metered unit price,
and (a)'s shared-Max-pool contention as contention on the FALLBACK role's fixed-non-rollover
allowance. The conclusion -- personas route to the LiteLLM tiers rather than claude -p -- and the
reopen-pricing obligation are unchanged. A swap changing the vendor or billing shape under either
re-keyed condition re-arms it and owes a further dated annotation here.]

---

## Decision 163: A universal, exceptionless obligation is enforced structurally, not gated -- the pre-handoff full-tier run is now a checked verification-plan step, not declared metadata alone (Decided)

**Status:** Decided
**Date:** 2026-08-03
**Warehouse ID:** dec-163 (canonical; per Decision 84)

> **Amended by Decision 169 (2026-08-11):** `validate_handoff_full_tier`'s matcher no longer
> reaches through a `scripts/validate.py` facade -- the check is dispatched via
> `scripts.checks.registry.resolve()` (Decision 169 retires Decision 104's check-facade
> mechanism). This body is otherwise unedited; see Decision 169 for the full derivation.

**Problem:**
rec-2965: main went red on the next push touching `scripts/checks/roadmap/validate_candidate_decision_ratification.py`, because PR #836's carrying plan declared `handoff_policy.full_validation_required_before_commit: true` -- mandatory, required metadata on every schema_version-3 IMPLEMENTATION plan (`plan_document.py`, `Literal[True]`, no opt-out) -- while its `verification_plan` executed only the fast (`--pre`) tier. The fast tier's diff-scoped coverage check cannot catch a gap on a file that was already below 100% before the PR touched it (measured: the file was 87% covered pre-#836, identical four arms uncovered; PR #836's extraction of `_load_roadmap` merely moved them and raised the ratio to 92.1%, still short of the file's own 100% requirement once touched). The declared obligation -- run the full tier before handoff -- was pure prose plus a metadata flag; nothing executable checked that the plan's own steps actually invoked it, so the obligation was silently skippable by construction, not merely skipped by oversight this one time.

**Decision:**
1. **The enforcement-shape principle.** Autonomy is lost to judgment-required checkpoints, not to hard walls. A deterministic, exceptionless rule requires a human's attention zero times; a discretionary gate (a reviewable exception path, a waiver, an escalation) requires one every time it is invoked, whether or not the exception is ultimately granted. For an obligation whose owner would never actually grant an exception -- this repo's full-tier-before-handoff rule is exactly this shape, since `handoff_policy.full_validation_required_before_commit` is `Literal[True]` with no schema-level opt-out -- the correct instrument is removing the exception path entirely (make the obligation structurally unskippable), not building a gate around it that a future session could argue its way past. A policy that is universal in name but discretionary in enforcement is strictly worse than either a genuinely optional check or a genuinely mandatory one: it carries the appearance of the latter with the failure mode of the former.
2. **The declared-vs-executed failure mode, named.** A policy expressed only as metadata plus prose -- a YAML flag, a paragraph of AGENTS.md text -- with no executable verification_plan step asserting it ran, is invisible to every automated gate and is skipped silently the first time an implementing session under load reaches for the faster path. This is not specific to `handoff_policy`; it is the general shape rec-2965 surfaced, and the reason `scripts/checks/verification/validate_handoff_full_tier.py` now exists: it fails a diff-added/modified plan declaring the obligation unless at least one of its own `verification_plan` steps invokes `-m scripts.validate` (module entry-point form) without `--pre`, registered in both presubmit tiers and reachable through the `scripts/validate.py` facade.
3. **The pre-handoff full-tier obligation and its cost basis, made explicit in AGENTS.md.** The two-tier presubmit table's Full row now states "Pre-handoff (local) + post-merge on `main`" rather than "Post-merge on `main`" alone -- amending Decision 73's CI-scoped two-tier split in the FORWARD direction only (Decision 73's own text is untouched; this is a superseding clarification, not a retroactive edit). The cost basis: CC-web containers are ephemeral and per-implementation, so a full local run (measured this session: `validate_test_coverage` alone over `scripts/validate.py` runs approximately 3m17s) is an affordable one-time cost per plan. That same cost is NOT extended to the automated executor (frozen per Decision 67) -- this obligation is scoped to the interactive CC-web implementing session, not to a future always-on executor loop where a full-tier run on every step would be materially different economics.

**Rationale:**
The fast (`--pre`) tier's diff-scoped design (Decision 73) is deliberately narrow -- it exists to keep the PR edit loop fast, not to catch every regression. The full tier is where whole-file gates like per-file coverage actually run to completion. Treating "the plan declares the full-tier obligation" as sufficient, without checking that the plan's own executable steps discharge it, let a mandatory-by-schema obligation silently degrade to optional-by-habit. `validate_handoff_full_tier` closes the specific gap; this Decision records the general principle so the next universal, non-negotiable rule in this repo defaults to a structural check rather than a documented expectation.

**Reversal conditions:** (a) the matcher (`-m\s+scripts\.validate(?![\w.])`, excluding segments containing `--pre`) is shown to false-positive or false-negative against a genuinely-compliant or genuinely-noncompliant plan more than once, indicating the classifier needs correction rather than the obligation needs loosening; (b) the executor (CD.17 reversal) goes live and the pre-handoff full-tier cost is shown to be materially unaffordable at executor scale, requiring a scoped carve-out for executor-authored plans specifically (not a general weakening); (c) a full, deliberate audit decides the enforcement-shape principle in point 1 should not generalize beyond this one obligation -- revert path is deleting `validate_handoff_full_tier`'s registration in `scripts/checks/registry.py` and its facade line in `scripts/validate.py`, and reverting the AGENTS.md table row.

**Significance:** clears the Decision 150 significance bar -- a durable, repo-wide authoring commitment (a new universal check enforced in both presubmit tiers, plus a named governance principle for future universal obligations), with reversal-relevant consequences and explicit reversal conditions; not a CD state-flip, operational fact, or field-semantics change.

**Related:** Decision 48 (executor autonomy calibration -- the judgment-required-vs-hard-wall framing this Decision's point 1 generalizes), Decision 60 (static-key recovery is non-fatal but non-negotiable -- a prior instance of the same enforcement-shape distinction), Decision 73 (the two-tier presubmit model this Decision amends in the forward direction only), Decision 128 (decompose-by-default / raise-approved marker grammar -- the same "remove the exception path" instrument applied to SLOC budgets), Decision 132 (verification-graduation obligation -- this plan's VP steps 3-8, 11-12, 14 graduate into the registry per that Decision's mechanism), Decision 148 (hermetic:true default for narrow deterministic pre-deploy steps, restored and relied on by this plan's own VP steps), Decision 150 (significance bar this entry clears), Decision 153 (fast-tier budget -- the reason this obligation is scoped to the full tier and not promoted into `--pre`), Decision 159 (coverage-baseline grandfather is one-time, not precedent -- the framing this Decision's Problem section relies on when explaining why rec-2965's debt is paid rather than baselined), Decision 161 (mypy downward-ratchet -- a sibling instance of a structurally-unskippable obligation this Decision's principle also describes).

## Decision 162: A composite-action shell body producing a consumed step output must be a thin adapter to a testable script, ratcheted against reintroducing rec-2923's defect class (Decided)

**Status:** Decided
**Date:** 2026-08-02
**Warehouse ID:** dec-162 (canonical; per Decision 84)

> **Amended by Decision 165 (2026-08-04):** point 3's R3 marker escape (the composite guard's
> `validate_composite_action_shell_bodies.py`) now delegates to the shared
> `scripts/checks/_marker_guard.py` authorization mechanism, upgrading its marker check from
> existence to authorization. This body is otherwise unedited; see Decision 165 for the full
> derivation.

> **Amended by Decision 169 (2026-08-11):** the reversal path in point 4's Rationale-adjacent
> registration language (registration in `scripts/checks/registry.py` and `scripts/validate.py`)
> is unaffected in substance -- `scripts/validate.py` no longer carries a check facade, but the
> guard's own registration in `scripts/checks/registry.py` is what the revert path names. This
> body is otherwise unedited; see Decision 169 for the full derivation.

**Problem:**
rec-2923: `write-convergence-record`'s always-run status writer accepted an EMPTY reviewer outcome as if it meant "not starved," latching a false platform-halting red for a run in which terraform apply never executed. The producer half was already fixed by PR #812 (commit 0726593) -- `review.sh` clears the inherited composite-step errexit and pre-writes a fail-closed `outcome=starved` before any fallible command -- but that fix addressed one symptom of a defect CLASS that remains structurally reproducible anywhere else in this repo's `.github/actions/`: CI-embedded shell whose control flow can silently not run (inherited errexit aborting a body mid-assignment), leaving a step output undefined for a downstream consumer to misread as a legitimate value. Two of the three actions that bind a step output to a consumed `outputs.<id>.value` today -- `deterministic-guard` and `fetch-saved-plan` -- still carry inline, non-delegated bash bodies producing exactly such outputs; only `subagent-plan-review` (post-#812) is a thin, testable adapter. Nothing prevented a fourth such action, or a regression of the third, from reintroducing rec-2923's shape unnoticed.

**Decision:**
1. **R1 -- thin adapter required for output-producing bodies.** Any composite `shell: bash`/`sh` step body that PRODUCES a consumed `outputs.<id>.value` binding must delegate to a `.sh` script under the action directory (a shell invocation of that script plus, at most, an `if`/`then`/`exit`/`fi` control-flow wrapper -- no other computation). `scripts/checks/ci_guards/validate_composite_action_shell_bodies.py` enforces this in both presubmit tiers, filesystem-only (no network, no subprocess -- Decision 153 fast-tier budget). The rule has **no marker escape, ever**, on either axis. MEMBERSHIP: `deterministic-guard` and `fetch-saved-plan` are pinned as known, pre-existing instances of the rec-2923 class in `config/composite_action_body_baseline.yaml`'s `r1:` section, cross-checked against a frozen constant in the guard module itself -- a config-file edit alone can never admit a third violator; growing the set requires editing the guard's own source in a reviewed change. SIZE: each pinned entry's declared line count is an enforced ceiling, so a pinned body that grows FAILS, and no `# raise-approved:` marker rescues it (that escape is R3-only). The section is strictly shrinking on both axes: extract or reduce, never grow.
2. **R2 -- literal-argv test coverage for every R1-conformant delegate.** Each script an output-producing step delegates to must be driven by a test under the LITERAL GitHub composite-step invocation, `bash --noprofile --norc -e -o pipefail <script>` -- the exact argv whose inherited errexit was rec-2923's root cause. A script never exercised under that literal argv has never had its errexit-inheritance behaviour actually proven; a convenience `bash script.sh` invocation would silently drop the `-e` that is the whole point (the pattern `tests/test_subagent_review_wiring.py` and the new `tests/test_convergence_review_outcome_contract.py` both establish).
3. **R3 -- ratcheted line-count ceiling on every other inline body.** Every remaining inline `shell: bash`/`sh` body (non-output-producing, or an output-producing body that already fails R1) is measured by effective (non-blank, non-comment) line count against `config/composite_action_body_baseline.yaml`'s `r3:` section. A live body exceeding its declared ceiling fails UNLESS the baseline entry carries an inline `# raise-approved: dec-NNN <reason>` marker (Decision 128's grammar, reused verbatim) naming a real `## Decision N:` header -- scoped to R3 only. The `r3:` baseline is seeded at the state this Decision's carrying plan (PLAN-ci-rca-starved-surface) leaves the repo in: a ONE-TIME grandfather in the sense of Decision 130 clause 2, explicitly not a precedent, so the PR installing the ratchet is not punished by its own rule. Touch-it-fix-it binds from the next edit onward.
4. **The strict consumer, as the concrete R1 instance closing rec-2923 itself.** `write-convergence-record/assert_review_outcome.sh` enforces the two-sided contract this Decision's rule R1 exists to generalise: when a review step ran (`REVIEW_STEP_OUTCOME` is `success`/`failure`), `REVIEW_OUTCOME` must be exactly one of `proceed`/`revise`/`starved` -- empty or unrecognised fails loudly, BEFORE any S3 write, exactly the rec-2923 counterfactual. When no review step ran, `REVIEW_OUTCOME` must be empty. It sits AFTER all five pre-existing skip/marker branches (refused/still-actionable/routed/pre-apply-failure/STARVED) and immediately before the green/red write, so a genuine STARVED episode is never hard-failed by a future contract bug, and the placement is invoked via an explicit `if ! bash "..."; then exit 1; fi` rather than a bare call relying on ambient errexit.

**Rationale:**
A strict CONSUMER ranks above every producer-side control: a consumer that switch-cases on a value and treats "anything unrecognised, including empty" as a legitimate branch is a latent bug regardless of how the producer fails -- rec-2923 had TWO independent failures, and the consumer accepting an empty value is the one that turned a contained reviewer stall into a platform-halting false red. But a fixed consumer alone only closes the ONE call site already known to be broken; the defect CLASS -- inline, non-delegated shell producing a consumed output -- remains reproducible anywhere a future action author reaches for a quick inline body instead of the `review.sh` pattern. R1/R2 name and enforce the shape that already worked (`review.sh`, extracted at rec-2924, shellcheckable and testable under the literal errexit-bearing argv); R3 extends the same "measure, don't guess" discipline broadly to prevent long inline bodies -- output-producing or not -- from creeping to a size where extraction becomes its own separately-reviewed migration. The r1/r3 split matters: r1 targets the EXACT rec-2923 shape (a consumed, potentially-undefined output) and is escape-free because that shape is never acceptable going forward; r3 targets general inline-body bloat, where an occasional deliberate exception (cited, reviewed) is legitimate.

**Sequencing, deliberate:** full extraction of `write-convergence-record`'s own ~97-line inline body (the highest-blast-radius script in the system, R3-baselined here rather than extracted) is deliberately NOT bundled into this incident remediation -- a follow-on recommendation, filed post-merge and scoped to the r1 entries first (the two known rec-2923-class violators), then the r3 entries, with `write-convergence-record` last. Bundling the highest-blast-radius refactor into incident remediation is how remediation changes cause the next incident.

**Reversal conditions:** (a) R1/R2/R3 are observed to false-positive against a genuinely-conformant shape more than once, indicating the thin-adapter classifier (`_delegated_script`) or the R2 literal-argv detector is mis-scoped -- fix the classifier, do not widen the escape; (b) the guard's fast-tier cost is shown to breach the Decision 153 budget meaningfully, requiring a full-tier-only relocation; (c) a full, deliberate audit decides the R1 known-violator set should never shrink further (unlikely -- extraction remains the standing intent) -- revert path is deleting the check's registration in `scripts/checks/registry.py` and `scripts/validate.py`, and the baseline file.

**Significance:** clears the Decision 150 significance bar -- a durable, repo-wide authoring commitment (a new class guard enforced in both presubmit tiers), with reversal-relevant consequences and explicit reversal conditions; not a CD state-flip, operational fact, or field-semantics change.

**Related:** Decision 55 (anti-masking / fail-closed default -- the governing principle the strict consumer and R1 are both checked against), Decision 92 (gated-apply Environment model; the assert's placement preserves its marker-write guarantees), Decision 77 (no-TOCTOU; the pre-apply-failure marker family this Decision's placement sits alongside), Decision 126 (point 5 / T2.39 STARVED-class precedent this Decision preserves unchanged), Decision 142 (ci-rca fingerprint v2 / chain-lifecycle -- rec-2923's closure route), Decision 103 (closure needs a proof, not an assertion -- the live closure proof gathered for rec-2923), Decision 84 (Single Portal Invariant -- the rec-2664 filing job's sole write path), Decision 104 (test-mirror colocation convention this guard's test follows), Decision 131 (mirror-convention precedent for `tests/checks/ci_guards/`), Decision 132 (verification-graduation obligation this plan's VP steps satisfy), Decision 128 (SLOC raise-gate marker grammar R3 reuses verbatim), Decision 130 (whole-repo ratchet scope / one-time-grandfather precedent R3's seeding follows), Decision 150 (significance bar this entry clears), Decision 149 (compaction lifecycle, cited for the marker-shape precedent DCG-03 established), Decision 105 (Reversal-stanza convention), Decision 158 (terminal route set -- the rec-2664 filing job is deliberately no part of it), Decision 156 (IAM inline-policy headroom -- why the transcript-archival grant was verified rather than added), Decision 155 (the DCG-03 orphan-guard marker shape this Decision's STARVED marker mirrors), Decision 86 / Decision 127 (machine-readable contract routing -- `docs/contracts/composite-action-shape.yaml`'s home), Decision 134 (decisions-index freshness this entry's regeneration satisfies), Decision 72 (RCA-as-plan-source -- rec-2923 is the CI-RCA rec this Decision's carrying plan closes), Decision 73 (two-tier presubmit model the new check registers into). Roadmap refs (not DECISIONS.md entries): rec-2923 (closed by this plan's carrying merge, manual closure route per `docs/contracts/ci-rca-lifecycle.yaml`), rec-2664 (closed via the Resolves trailer).

## Decision 161: Mypy gate status is an error-count downward-ratchet -- per-file baseline, full-tier enforcement, tamper-guarded (VTS-15) (Decided)

**Status:** Decided
**Date:** 2026-07-31
**Warehouse ID:** dec-161 (canonical; per Decision 84)

> **Amended by Decision 165 (2026-08-04):** clause 4's mypy tamper guard
> (`validate_mypy_baseline_edits`) now delegates to the shared `scripts/checks/_marker_guard.py`
> authorization mechanism, upgrading its marker check from existence to authorization, and
> receives clause 4's `moved from <old-path>` form's first real implementation as a same-diff
> proof. This body is otherwise unedited; see Decision 165 for the full derivation.

**Problem:** VTS-15: mypy runs in both presubmit tiers but is purely informational (the retired `_scaffold_mypy_full` step only printed a warning); no Decision owned that status, leaving 129 measured pre-existing errors across 57 `scripts/`+`src/` files ungoverned.

**Decision:** Option (iii), an error-count DOWNWARD-RATCHET (mirrors the SLOC/Decision 128 and coverage/Decision 159 grandfather-roster precedents).
1. `pyproject.toml` gains a minimal `[tool.mypy]` block (`disable_error_code = ["import-untyped"]`) -- surgical stub-noise silencing; `[import-not-found]` stays live.
2. `config/mypy_baseline.yaml`: per-file `entries: {path: int}` roster (57 entries / 129 errors seeded), scoped to `scripts/`+`src/`. An unregistered file's implicit baseline is 0 (mirrors the SLOC/coverage registries). `--seed` is the one-time creation (refuses if the file exists); `--update` is downward-only, never seeding a newly-dirty file.
3. `validate_mypy_ratchet` (FULL TIER ONLY, `scripts/checks/typing/mypy_baseline.py`) fails a file whose measured count exceeds its baseline; a lower count passes with a non-blocking advisory. Full-tier-only: a cold run costs ~57s against the fast tier's 5-minute budget, and only `main-validate` pins mypy via `requirements.lock`. A proof-of-execution guard treats stdout lacking both "Found N errors in M files" and "Success: no issues found" as a loud failure, never as zero errors everywhere. Retires the informational `_scaffold_mypy_full` scaffold (the `--pre` diff-aware scaffold is untouched).
4. `validate_mypy_baseline_edits` (BOTH TIERS): tamper guard -- an unmarked increase or new registration fails; `# baseline-raised: dec-NNN <reason>` citing a real Decision header passes it; decreases/removals are unrestricted. Also authorises re-registering unchanged debt after a pure structural move under `# baseline-raised: dec-161 moved from <old-path>`, so a Decision-128 decomposition need not mint a new Decision.

**Rationale:** Per-file (not a repo-wide total) gives blame locality and somewhere to hang the approval marker; a changed-files-only gate was rejected for dirty-file inheritance (blocks a PR on unrelated debt in a touched file). Full-tier placement nets +27s on `main-validate` rather than spending the fast tier's already-breach-prone budget on an unpinned-interpreter measurement.

**Reversal conditions:** (a) pre-merge-blocking upgrade: a parallel CI job running the ratchet, pinned via `requirements.lock`, later required by `main-protection` -- until then a regression is a post-merge forward-fix rec, not a blocked PR; (b) an emptied roster retires the baseline/tamper-guard clauses; (c) net roster growth over any 90-day window triggers a gate-design re-audit, mirroring Decision 159's own condition.

**Related:** Decision 128 (SLOC raise-gate mechanism mirrored here), Decision 159 (closest sibling), Decision 130 (whole-repo scope), Decision 150 (significance bar), Decision 134/145/146 (size governance), Decision 60 (two-tier presubmit definition), Decision 132 (verification-graduation obligation), Decision 160 (retired the live-byte ceiling this entry's sizing relies on).

## Decision 160: Retire the DECISIONS.md live-byte ceiling for bounded decision-scout retrieval; amends Decision 145, Decision 134 clause 2, and Decision 146; widens Decision 152 gate (ii) (Decided)

**Status:** Decided
**Date:** 2026-07-31
**Warehouse ID:** dec-160 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
At authoring time docs/DECISIONS.md sat at 499,960 / 500,000 bytes (Decision 145's stopgap live-byte
ceiling) and 112 / 120 live headers -- this entry's own landing would fail `validate_decisions_size` in
the `--pre` tier unless the retirement below lands in the SAME PR, mirroring Decision 159's acute-state
framing. Decision 134's live-byte ceiling existed to size ONE thing: the decision-scout gate's mandatory
whole-live-file read (Decision 145: "~500 KB is ~125k tokens, under 200k" of context budget). Decision
145's own reversal conditions and Decision 152's own reversal conditions both name removing that
whole-file-read as the trigger that unwinds the stopgaps built on top of it -- but neither could fire
literally, because nothing had yet built the bounded read they anticipate. PLAN-decision-scout-bounded-retrieval
builds it: `scripts/decisions_index.py` now derives a `live` boolean per entry (from
`decision_header_numbers(paths=[docs/DECISIONS.md])`) plus a bounded `triage_excerpt` (<=320 chars,
Intent -> Problem -> Context -> Decision fallback order, sourced solely via the shared parser) in the
committed `docs/decisions-index.json`; `.claude/skills/decision-scout/SKILL.md` Phase 1 step 1 now
triages every live entry via that index and reads ONLY shortlisted entries as targeted sections of the
source file -- never the corpus wholesale. Lowering the byte ceiling further is arithmetically
impossible (the file already exceeds any value below its current size); per Decision 145's own warning,
a second stopgap raise "is itself a signal that the structural fix is overdue." Retirement, not another
raise, is the sanctioned response.

**Decision:**
1. **Retire `_DECISIONS_LIVE_MAX_BYTES`** (Decision 145's 500,000-byte stopgap value) entirely from
   `scripts/checks/decisions/validate_decisions_size.py` -- the constant, its `_decisions_size_issues`
   parameter, and its FAIL branch are all removed, not merely raised or lowered. The bounded-retrieval
   mechanism above is what makes retirement safe: no consumer reads the live file wholesale anymore.

2. **Reversal-trigger adjudication (Decision 145 / Decision 152).** Decision 145 condition (b) reads
   "the decision-scout moves to a warehouse/portal read (Decision 134's protected consumer is gone)";
   Decision 152's reads "the removal of the whole-file-read inefficiency is ITSELF the reversal trigger."
   This plan satisfies the PURPOSE of both -- the protected whole-file-read consumer is gone; the
   whole-file-read inefficiency is removed -- but NOT the LITERAL action of either: it declines a
   warehouse/portal/verb read on Decision 88 zero-egress grounds (invariant (ii), "never an ad-hoc
   re-fetch of data in hand"), reading the source files by targeted section instead. T0.8's MCP server
   (`scripts/agent_sdk/mcp_server.py`, registered in `.mcp.json` as `ducklake-reads`, `docs/ROADMAP-PLATFORM.yaml`
   status now `complete`) is deliberately NOT used by decision-scout here -- it is certified delivered
   while its use in this gate is declined and deferred to T1.5 c1, which is exactly what makes the
   literal trigger reachable for the first time. Both conditions are ADJUDICATED SATISFIED under this
   purpose-vs-literal reading, the same treatment point 6 below gives the Decision 114 analogy.

3. **Amends Decision 145** (retires the byte-ceiling value its stopgap raise set; its own
   reversal-condition text is satisfied per point 2 above) **and amends Decision 134 clause 2** (the
   live-byte ceiling clause; superseded by the bounded-retrieval read model plus the combined-ceiling
   backstop, point 4). Per the forward-direction amendment convention (Decision 126/143, reused by
   Decision 145 point 2), neither amended Decision's body text is edited -- the amendment is stated only
   here.

4. **The two surviving ceilings are retained, unchanged:** `_DECISIONS_LIVE_MAX_H2` (120 live headers)
   and `_DECISIONS_COMBINED_MAX_BYTES` (700,000 combined bytes) remain enforced, in both the `--pre` and
   full `validate.py` tiers. Decision 150's significance bar (gating what MAY become a new entry) is
   COMPLEMENTARY to these size guards (gating how large the corpus MAY grow), not a substitute for
   either. The combined ceiling now implicitly bounds the live file on its own
   (live <= 700,000 - archive_bytes, ~588,930 bytes at this entry's authoring time) -- this IS the
   intended backstop, not an accidental side effect of retiring point 1.

5. **Decision 146 amendment.** Decision 146 named archival (moving a fully-superseded live entry to
   `docs/DECISIONS_ARCHIVE.md`) as a live-file size-pressure relief valve, alongside compaction. Measured
   under the surviving combined ceiling, archival is INERT: it only moves bytes between the two counted
   files (`docs/DECISIONS.md` + `docs/DECISIONS_ARCHIVE.md`), so it cannot relieve
   `_DECISIONS_COMBINED_MAX_BYTES`. `_RELIEF_VALVES` in `validate_decisions_size.py` is rewritten
   accordingly, naming only valves that actually reduce combined bytes: compaction of superseded bodies
   to pointer stubs (Decision 149) and the per-entry authoring size norm (point 10 below). Decision 146's
   archival policy is otherwise UNCHANGED -- archival remains sanctioned for corpus-hygiene and
   citation-hygiene reasons; it simply no longer functions as a combined-ceiling relief valve, and this
   Decision's own measurement (9,048 bytes of live `**Status:** Superseded` entries; ~15.7 KB of
   realistic reclaim across 12 archive-shaped candidates, ten of which carry armed reversal conditions
   or live "necessary, not sufficient" scoping) is why declining an outflow wave here is an
   operator-disposed judgement, not a bypass of Decision 146.

6. **Decision 114 analogy, addressed.** Decision 114 rejected splitting `ROADMAP-PLATFORM.yaml` into
   per-tier files because doing so "trades one coherent load for N files an agent must reassemble,"
   choosing a raised ceiling + deterministic guard instead. This plan does NOT split `docs/DECISIONS.md`
   -- the source file stays single and coherent, exactly as Decision 114 required. Only the READ is
   bounded: decision-scout triages a generated index (itself derived from the one source file by the
   shared parser, `scripts.decisions_md`, never hand-maintained) and reads targeted sections of that same
   single source file for shortlisted entries. The anti-pattern Decision 114 and Decision 110 guard
   against -- N files an agent must reassemble -- does not apply: there is still exactly one source file
   and one generated index, not N fragments.

7. **Decision 152 gate (ii) widened; Decision 152's mandated revisit performed.** The SPIRIT lane's
   verbatim-quotability requirement (Decision 152 gate (ii)) now admits a quote of the entry's
   Decision-marker clause -- a REQUIRED marker per `docs/contracts/decision-entry.yaml` -- in addition to
   the existing Intent-marker and a specific Problem/Rationale sentence. This widening is what
   takes `triage_excerpt` coverage from 115 to 135 of 139 entries (measured at authoring time). It also
   performs the revisit Decision 152's own reversal conditions mandated once the whole-file-read
   inefficiency is removed: "make the SPIRIT axis leaner and query-driven rather than prose-budget-funded."
   The freed whole-file-read prose in `.claude/skills/decision-scout/SKILL.md` funds the new bounded
   protocol text in place; the skill's `config/prose_budgets.yaml` S4 entry is ratcheted DOWN (11379 ->
   11325 bytes, measured) and its `# raise-approved: dec-152` marker is REMOVED (a decrease needs no
   marker) -- the raise Decision 152 point 3 authorized is retired along with the text it funded.

8. **Residual, stated not hidden.** A small terse-historical band -- live Decisions 63, 64, 65, and 67
   (the pre-Decision-77 band already carried in the DAF-01 fidelity baseline) -- carries no quotable
   marker (Intent/Problem/Context/Decision) at all, even after the point 7 widening. If such an entry is
   NOT shortlisted during a `/plan` triage pass, its `triage_excerpt` is empty and decision-scout cannot
   emit a SPIRIT flag against it from the index alone. This is an accepted residual of bounded retrieval,
   not a defect to work around; a shortlisted read of the entry's full section text remains fully
   quotable regardless.

9. **New surface, its own guard named.** `docs/decisions-index.json` becomes a NEW read-in-full-every-
   `/plan` surface (decision-scout's Phase 1 step 1). It carries NO byte guard of its own -- it is bounded
   only INDIRECTLY, by the 120-header live ceiling (point 4, since the index's live-row count tracks the
   live header count 1:1) and by this plan's own acceptance-criterion pin (the committed projection must
   stay <= 110,000 bytes; measured 105,609 bytes, ~20.4% of the live file, at this entry's FINAL
   measured state -- the point 7/14 `category_tags` addition grew the projection after an earlier
   draft of this point recorded a smaller pre-category_tags figure; this is the corrected number). A future
   owner should reassess whether this indirect bound remains adequate as the corpus grows past the
   header ceiling's current runway (point 11).

10. **Decision 151 backstop consequence.** Decision 151 clause 3(v) left its Intent-marker accretion cap
    convention-only, "backstopped by the existing 500,000-byte live-file ceiling and ordinary PR review."
    That specific numeric backstop is retired by point 1. The surviving combined ceiling (point 4) plus
    ordinary PR review now serve as the backstop instead; no separate Intent-specific ceiling is
    introduced here. If Intent-marker accretion becomes material on its own, it remains visible the same
    way any other accretion is -- via the combined ceiling and the dated runway below.

11. **The dated runway -- days, not months, and a named owner.** At this plan's own measured inflow rate
    (294 KB and 56 entries/month) and MEASURED including THIS entry as committed: live headers are 113 /
    120 (headroom 7 headers, ~4 days of runway at ~1.87 headers/day); live+archive combined bytes are
    625,905 / 700,000 (headroom 74,095 bytes, ~8 days of runway at ~9,800 bytes/day -- this entry landed
    larger than the plan's own ~12 KB pre-authoring estimate, which is why the combined figure is ~8 days
    rather than the plan's earlier ~8-9 day forecast; the header figure is unaffected since one entry is
    always +1 header regardless of its byte size). The HEADER ceiling is the FIRST binding constraint, the
    COMBINED ceiling second. "Nothing goes unguarded" is true; "nothing is urgent" is NOT. OWNER: the
    deferred per-entry authoring size norm (rec filed by this plan, point 12) is the only lever that bends
    the accrual RATE; until it lands, the runway above is the honest, disclosed cost of deferring it, not
    an oversight -- and THIS entry's own above-estimate size is itself a live illustration of why the norm
    is needed.

12. **Follow-on recommendations filed, by substitution not deletion.** rec-2783 ("watch docs/DECISIONS.md
    headroom against the Decision 145 500,000-byte ceiling") named a ceiling this Decision retires, so it
    is superseded rather than left stale: a new successor-watch recommendation (naming the surviving
    120-header and 700,000-combined-byte ceilings this Decision retains) is filed by this plan and named
    as rec-2783's resolution when it is closed. A second new recommendation for the deferred per-entry
    authoring size norm (point 11's named owner) is also filed by this plan.

13. **This arrangement is INTERIM, not the T1.5 portal cutover.** Decision 134 clause 5 designates the
    end state as a portal/warehouse read; T1.5 c1 still owns replacing decision-scout's Phase 1 step 1 (the
    index-plus-targeted-reads mechanism this Decision installs) with a queried tool call, per the T1.5
    relationship this plan's own context recorded and per point 2 above. The scout's output contract
    (buckets, severity taxonomy, quality gates, `Decisions triaged: N of M` echo, Verdict line) is
    UNCHANGED and stays the stable interface across that future swap.

14. **Recall measurement and the `category_tags` fix (VP step 9), FINAL measured state.** Live
    decision-scout dispatches -- whole-file baseline vs bounded protocol, same two probe briefs
    (a Neon-Postgres pg_dump-backup-Lambda proposal; a DECISIONS.md-topic-registry-split proposal)
    -- measured a REAL recall regression in the first cut of the bounded index-pass triage: a
    decision that governs by ARTIFACT TYPE (e.g. any new Lambda touches the Lambda-packaging/
    deploy-channel decisions regardless of what it does) rather than shared vocabulary was being
    silently discarded as IRRELEVANT before ever reaching a targeted read -- round 1 lost 5 of 6
    CITE entries on the pg_dump probe alone. Two rounds of SKILL.md prose-only tightening each
    recovered some entries and left others (e.g. Decision 126's title says "deployment model", not
    "deploy", so a prose rule enumerating only "Lambda/Terraform/IAM/Secrets Manager" nouns missed
    it even though the scout followed the rule as written) -- a per-entry LLM judgment call over
    ~113 live entries in one context is inherently unreliable. A Fable advice-consult diagnosed the
    residual as a prompt-level instruction-following ceiling, not a further-fixable prose problem,
    and recommended converting the shortlist from an LLM judgment call into a mechanical lookup:
    `scripts/decisions_index.py` derives a deterministic `category_tags` list per entry (regex
    classes over title + `triage_excerpt` only, never the full body -- eight classes including
    lambda/terraform/iam/deploy/egress and credential-handling, each verified under ~17% of live
    entries so the shortlist stays materially smaller than the corpus), and
    `.claude/skills/decision-scout/SKILL.md` Phase 2 step 3 shortlists by tag-set intersection
    FIRST, before any judgment-based triage. Round 4 (post-fix) measured: pg_dump probe, 5 of 6
    baseline CITE entries now match EXACTLY (including Decision 126, the round 1-3 holdout), one
    (Decision 157) found but bucketed RELATED instead of CITE; topic_registries probe, 2 of 4 match
    exactly, one (Decision 149) found but bucketed CONTRADICT instead of CITE, one (Decision 105 --
    carries no category_tags match, a pure judgment-lane entry) genuinely absent, present in round
    3's dispatch on the identical probe but not round 4's. `category_tags` closed every FULLY-MISSED
    artifact-type entry measured across all four rounds. The residual that remains -- 3 of 10 total
    baseline CITE entries across both probes, ALL either found-but-reclassified (157, 149) or a
    single non-tagged entry with round-to-round presence variance (105) -- is judged, per the Fable
    consult, to be ordinary inter-run LLM judgment noise on entries `category_tags` cannot reach by
    construction (no artifact-type signal to key on), the same class of variance two whole-file
    baseline runs would likely also show against each other. This is the disclosed, HONEST COST of
    bounded retrieval per this plan's own self-attestation framing (AC5): not zero, materially
    better than any of rounds 1-3, and not further closable by index enrichment without a
    structurally different mechanism (e.g. a full warehouse/portal read -- T1.5's eventual scope,
    point 13). `category_tags` is generator-internal and revisable without Decision ceremony -- a
    retrieval aid, not a governance taxonomy; the tag vocabulary may grow as new artifact classes
    accrue decisions, without amending this entry.

**Reversal conditions:** Revisit if the header ceiling (120) or the combined ceiling (700,000) is
breached before the per-entry authoring size norm (point 11's named owner) lands -- a breach at that
point would mean the runway was mis-measured or the norm arrived too late, and the response is to
re-derive the runway and escalate the norm's priority, never a silent re-raise. Revisit when T1.5 c1's
portal/verb read supersedes the source-file-read mechanism installed here (expected -- this is the
literal action point 2 adjudicated as satisfied only in purpose, not yet in fact). Revisit if a future
`/plan` session's live decision-scout dispatch surfaces a CITE or SPIRIT regression against the
pre-bounded-retrieval baseline (VP step 9 of this plan's own verification) that cannot be closed by
enriching the `triage_excerpt` projection -- in that case, per this plan's own rollback note, the
SKILL.md bounded-read change may be reverted alone while keeping the index's `live` field, which is
independently useful.

**Related:** Decision 145 (amended -- point 3), Decision 134 (clause 2 amended -- point 3; clause 5's
portal end-state -- point 13), Decision 146 (amended -- point 5), Decision 152 (mandated revisit
performed and gate (ii) widened -- point 7), Decision 151 (backstop consequence -- point 10), Decision
150 (significance bar, complementary to these size guards -- point 4), Decision 114 (splitting-vs-bounding
analogy addressed -- point 6), Decision 110 (agent-first one-file-load principle, not violated -- point
6), Decision 88 (zero-egress grounds for declining the verb/warehouse read -- point 2), Decision 105
(committed-index hermeticity re-grounded in `.claude/skills/decision-scout/SKILL.md` -- the index is used
instead of the gitignored `ops_decisions` cache because CI PR roles lack reader access there), Decision
84 (`docs/DECISIONS.md` remains the sole ETL source for `ops_decisions`; this Decision changes how the
corpus is READ, never where it is written), Decision 149 (compaction-to-stub relief valve named in point
5), Decision 128 (decompose-by-default / ratchet-down convention mirrored by the prose-budget decrease in
point 7), Decision 55 (fail-loud, no rescue agents; the residual in point 8 is stated, not silently
absorbed). Provenance: decision-scout's own plan-time triage (112 of 112 live decisions) flagged
CONTRADICT WARN on Decision 145 (retire-vs-raise, resolved by point 1/2), Decision 152 (mandated revisit,
resolved by point 7), and Decision 88 (egress re-fetch, resolved by point 2); plan-critique converged
after 3 rounds with all blocking items applied. Roadmap/queue refs (not DECISIONS.md entries): T0.8
(closed out alongside this entry, Tier Item Freshness Gate), T1.5 c1, rec-2783, rec-2774, rec-2479.

> **Amended by Decision 167 (2026-08-07):** Decision 167 installs the per-entry authoring size norm
> this point 11 named as the only lever bending the corpus's accrual RATE, at WARN tier pending
> migration step 3 (destination readiness).

## Decision 158: Reconcile's recovery path may substitute a freshly-planned artifact for the saved plan.bin, and its complete terminal route set narrows the tf-gated-apply Environment's reach (Decided)

**Status:** Decided
**Date:** 2026-07-30
**Warehouse ID:** dec-158 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`reconcile.yml`'s DEP-10 fresh-replan fallthrough was gated solely on the saved-plan apply step's `stale` output. A destroy or out-of-budget IAM change ALWAYS guard-BLOCKs, which SKIPS that apply step, so the output is never set and all six fallthrough steps were STRUCTURALLY UNREACHABLE on exactly the episodes most likely to need them (rec-2847) -- a guard-BLOCK episode's own partial gated apply advances the tfstate serial and thereby stales its own saved plan, so that is the MOST PROBABLE red shape. The recovery path was total on paper and empty in practice: dispatching burned a human approval and re-latched red. Separately, the pre-existing right of a fresh re-plan to SUBSTITUTE for the saved plan.bin AT ALL -- live on the STALE route since DEP-10 -- was sanctioned only in a `reconcile.yml` workflow comment and in `terraform/CLAUDE.md` prose, never in a numbered Decision.

**Decision:** Both narrowings are recorded here, in ONE entry.

1. **The substitution is sanctioned.** On the recovery path a fresh re-plan MAY stand in for the saved plan.bin. Its entry condition is a UNION of two causes -- saved plan stale, OR saved-plan guard-routed -- collapsed by `reconcile.yml`'s `route` step into one `needs_fresh_plan` signal, so no fallthrough step reads one cause in isolation again.

2. **The COMPLETE terminal route set out of a saved-plan guard-BLOCK is exactly these three. There is no fourth, and no episode entering that path ends anywhere else.**
   - (i) **fresh guard-PASS** -> the digest-fed subagent review runs, then `apply_fresh` AUTO-APPLIES inside `apply-reconcile`. That review is the ONLY gate; there is NO `tf-gated-apply` Environment approval. Pre-fix this cell was structurally impossible.
   - (ii) **fresh guard-ROUTE** -> the fresh plan.bin crosses to `gated-apply-reconcile` as `RECONCILE_FRESH_PLAN_ARTIFACT` (run-scoped artifact, symmetric sha256 EMIT/VERIFY over the job boundary) and is applied behind the Environment approval.
   - (iii) **fresh re-plan failure** -> every downstream step short-circuits on `success()` and the always-run record write latches RED. Pre-ratified: Decision 154 point 5(i) deliberately EXCLUDES `replan` from the closed pre-apply-failure allow-list, fail-closed and safe.

3. **What Decision 77 preserves, stated precisely -- this is the whole basis for consistency rather than amendment.** Decision 77's operative property is guard-to-apply ARTIFACT IDENTITY: `guard_fresh` inspects the SAME plan.bin that is applied, and the sha256 pair protects byte integrity across the job boundary. That holds on every route above; nothing is ever applied unguarded. Decision 77 nowhere ratifies reviewer-vs-apply DIFF identity -- that a human or PR reviewer saw the same DIFF that is applied. Artifact identity is preserved; diff identity was never promised. An account that blurs the two either overclaims Decision 77 or falsely implies this breaks it.

4. **The accepted cost, not softened.** Route (i) NARROWS the `tf-gated-apply` Environment control's REACH, permanently and not merely for the episode that motivated the fix: pre-fix a saved-plan guard-BLOCK ALWAYS terminated at the Environment; post-fix a guard-BLOCK recovery whose fresh re-plan comes back fully in-budget APPLIES WITHOUT REACHING A HUMAN. The HUMAN adjudicated this at plan time and accepted it. The reasoning: anything the deterministic guard PASSes is by definition in-budget, non-IAM-trust and non-destroy, and such a change ALREADY auto-applies elsewhere under the sandbox CD contract -- the guard, not the Environment, is the classifier of "does this need a human", and a fresh-guard PASS is that classifier speaking about the artifact that will actually be applied.

**Reversal conditions:** Re-narrow if a fresh-guard-PASS auto-apply lands a change a human would have caught, or if evidence shows the guard's in-budget classification is weaker than the Environment gate it displaces on this path. **The mechanism is a TWO-SITE change, not a one-liner** -- recorded because a later reader will otherwise assume the narrowing was declined on taste and is cheap to undo. Adding a `fresh_reason != 'guard_routed'` conjunct to `apply_fresh`/`review_fresh` ALONE strands a fresh-guard-PASS episode with NO UPLOADER: `upload_fresh_plan_sha256` and the upload-artifact step are gated on `guard_fresh.outputs.routed == 'true'`, so no artifact is produced, `fresh_plan_pending` stays false, `gated-apply-reconcile` falls back to fetch-saved-plan, and the episode ends applying the STALE saved plan -- the exact failure this entry exists to remove, reached by a longer road. A reverser needs BOTH sites plus matching updates to the `recovery-workflow-topology` guard's assertions (ii) and (iv).

**Related:** Decision 77 (speculative plan / no-TOCTOU; the artifact-vs-diff distinction in point 3), Decision 92 (the `tf-gated-apply` Environment as the authorization boundary -- whose reach point 4 narrows), Decision 126 / T2.37 (one dispatch, one approval: why a second Environment approval was rejected), Decision 154 (point 5(i) pre-ratifies route (iii)'s red latch; point 2's dispatch-ref side-checkout narrowing is why the re-plan runs against the RED_SHA checkout, not the dispatch ref), Decision 150 (the significance bar this entry clears). Provenance: decision-scout judged the newly-reachable cell a durable architectural commitment with reversal-relevant consequences, and separately found that the pre-existing STALE-route substitution had never been numbered. Roadmap/queue refs (not DECISIONS.md entries): T2.47/T2.48, rec-2847.

## Decision 159: push-context diff-base class fix restores the post-merge diff-aware validation layer; a bounded, tamper-guarded coverage baseline unblocks the 100%-coverage gate going live (Decided)

**Status:** Decided
**Date:** 2026-07-30
**Warehouse ID:** dec-159 (canonical; per Decision 84)

> **Amended by Decision 165 (2026-08-04):** clause 3's coverage tamper guard
> (`validate_coverage_baseline_edits`) now delegates to the shared `scripts/checks/_marker_guard.py`
> authorization mechanism, upgrading its marker check from existence to authorization. This body
> is otherwise unedited; see Decision 165 for the full derivation.

> **Amendment (2026-08-18, PLAN-root-scoped-diff-base / rec-3166, forward reference -- mints no new
> Decision number):** clause 1's `push_context_base()` gains an optional `root: Path | None = None`
> parameter, threaded through `get_changed_files()` and `get_status_aware_diff()` as well -- every
> git probe and path-existence filter inside all three now runs against `root` (defaulting to
> `_common.ROOT` when omitted, so this widening is contract-unchanged for every existing caller,
> per Decision 135 pt 3). The `GITHUB_EVENT_NAME` / `GITHUB_EVENT_BEFORE` env signal stays
> job-global regardless of `root` -- only the git probes and existence filters became root-scoped.
> This closes rec-3166: a check evaluating an injected root (e.g. a fixture repository in a test)
> had a `root` seam with no paired `base` seam, so in push context it silently read the REAL
> repository's push-context base instead of the injected one. This body is otherwise unedited; see
> PLAN-root-scoped-diff-base for the full derivation.

**Problem:** `get_status_aware_diff()` and `test_coverage_checker.get_changed_source_files()` resolve their base via `merge-base(origin/main, HEAD)`, which equals HEAD on a clean post-merge main checkout; `get_changed_files()` diffs `origin/main` directly, also HEAD on main. Same result either way: every diff-aware full-tier check silently no-ops post-merge. A MEASUREMENT CORRECTION (Decision 82 framing), not a relaxation.

**Decision:**
1. **`push_context_base()`** (sole home: `scripts/checks/_common.py`) returns a base ONLY in push context -- `GITHUB_EVENT_NAME == "push"`, OR (branch == "main" AND `merge-base(origin/main, HEAD) == HEAD`) -- else `None`. The branch-name conjunct is required: `merge-base == HEAD` alone also matches a fresh session branch before its first commit. Prefers `GITHUB_EVENT_BEFORE` when non-zero/local, else `HEAD~1`; `None` with a loud warning if `HEAD~1` doesn't resolve. Each of the three consumers tries it first and falls back to its OWN existing base on `None` (Decision 135 pt 3 unchanged-contract holds); `get_changed_files()` newly changes behaviour ON main in push context, which is the correction itself. `ci.yml` main-validate and `main-canary.yml` checkout `fetch-depth: 2` (squash convention, Decision 76).
2. **`config/coverage_baseline.yaml`** is a one-time grandfather roster (Decision 130 style): an entry-bearing file fails iff measured < entry; unbaselined files keep 100% -- narrowing Decision 48's V2 row by forward reference. rec-943's parent-directory `--cov` spec fix (a single-file/dotted spec silently collects no data) makes previously info-skipped files measurable.
3. **Tamper guard** (Decision 128 mirror): `validate_coverage_baseline_edits` fails a lowered/new-sub-100 entry lacking an inline `# baseline-lowered: dec-NNN <reason>` marker naming a real Decision header; raises/removals unrestricted. Missing-base (this seeding PR) SKIPs.
4. **Amends Decision 124's premise** by forward reference: "the merge-base diff is empty on main post-merge" is corrected; the `scripts/ops_portal/**` carve-out is unaffected, VP-verified.
5. **Accepted residuals:** full-tier-only tripwire (Decision 73); a multi-commit direct push under-selects with `HEAD~1` (Decision 76 squash assumption). `tests/test_checks_registry.py` takes one marked SLOC raise (mechanism-mirror role) -- test-SLOC debt re-introduced after rec-2709 retired all 24 Decision 130 grandfathers.

**Reversal / retirement conditions:** net roster growth over any 90-day window triggers a gate-design re-audit (Decision 62 alarm-not-gate); when the roster empties, the baseline clauses retire and Decision 48's V2 row reads unamended; the SLOC raise retires by folding `_CHECKS_REGISTRY_MECHANISM_FILES` into a concern-split test package; a diff-line-coverage ratchet (Platform End-State section 6) would likely obsolete this mechanism outright, in which case this Decision is revisited rather than extended.

**Related:** Decision 104/148 (`_common.py` sole-home), Decision 135 pt 3, Decision 73/142 (two-tier presubmit), Decision 82 (measurement-correction framing), Decision 48 (100% coverage V2 row, narrowed), Decision 124 (amended), Decision 128 (tamper-guard mirror), Decision 130 (roster precedent), Decision 76 (squash-merge), Decision 55/72/129 (fix the generator -- supersedes rec-2903's fetch-depth-alone fix). Bundled: rec-2903, rec-943.

## Decision 157: Secrets Manager split by value-capability -- metadata verbs ride the agent-platform-* prefix, value verbs enumerated (amends Decision 129 pt 2) (Decided)

**Status:** Decided
**Date:** 2026-07-30
**Warehouse ID:** dec-157 (canonical; per Decision 84)

**Problem:**
Decision 129 pt 2 holds Secrets Manager enumerated on the ground that "secrets return VALUES". Advice-consult VERIFIED against hashicorp/aws v5.100.0 source: `aws_secretsmanager_secret`'s refresh (`resourceSecretRead`) calls ONLY `DescribeSecret` + `GetResourcePolicy`, NEVER `GetSecretValue` (tags ride that response); values come solely from `aws_secretsmanager_secret_version` (resource and data source) -- here the neon api key data source and the DuckLake DSN version, both already enumerated. Pt 2's GROUND is thus a `GetSecretValue`-class argument that does not bear on metadata reads, while its unqualified TEXT forbids them. Why now: the new read/write scope-parity check found, first outing, that the pipeline could `CreateSecret agent-platform-newthing` at the prefix yet not refresh-read it -- AccessDenied at the NEXT plan, silent and deferred. The three obvious fixes were worse: narrowing the write buys NO security (metadata reads are value-free) at a human-gated bootstrap apply per new secret; widening `Get*` reads is the control-trade a review gate already BLOCKED; an exemption spends the rule's first genuine finding on suppression.

**Decision:** Restate pt 2 by value-capability, not by service.
1. **Value-capable actions stay ENUMERATED per-ARN**: `secretsmanager:GetSecretValue`, and `secretsmanager:UpdateSecret` per Decision 143 clause 1 (worst reachable verb).
2. **Value-free metadata actions -- `Describe*`, `List*`, `GetResourcePolicy` -- MAY ride the `agent-platform-*` prefix, on BOTH the read and write side.** Decision 129's resource-axis reasoning carries over; only its Secrets Manager carve-out narrows.

**Rationale (decisive: autonomy):** a secret whose value is human-seeded out-of-band (five of six existing secrets) now costs ZERO bootstrap applies: one PR, auto-applied. The human gate fires ONLY when terraform needs the VALUE -- the control paying out exactly when value-plane access is requested.

**Invariant and its fragility:** "metadata = `Describe*`/`List*`/`GetResourcePolicy`" must stay true as AWS adds verbs. A new METADATA verb outside those classes fails loud at refresh (the accepted rec-2305 read-wildcard closure risk). A new VALUE verb inside `Describe*`/`List*` would silently widen -- vanishingly unlikely (AWS deliberately named `BatchGetSecretValue` outside the `Get*` pattern), but NAMED so review catches it.

**Accepted residuals:** (a) at the prefix, `DescribeSecret`/`GetResourcePolicy` expose any `agent-platform-*` secret's description, tags, rotation config and resource policy to CI; names are already public in this repo's HCL (Decision 101) -- acceptable. (b) `CreateSecret` takes a SecretString, so force-delete-then-recreate-same-name is value-REPLACEMENT (not disclosure) inside the prefix -- closed here by a `BoolIfExists` `ForceDeleteWithoutRecovery = false` condition making the 7-30 day recovery window mandatory.

**Corollary:** parity must compare a type's REFRESH-READ set, not its whole service read class -- `data:aws_secretsmanager_secret_version` requires `GetSecretValue` specifically; without that, a wide `Describe*` satisfies parity falsely and reinstates the silent deferred failure this rule kills.

**Reversal conditions:** re-narrow the metadata prefix to enumerated ARNs if (a) an `agent-platform-*` secret appears whose metadata CI must not see; (b) AWS adds a value-returning verb inside those metadata classes; or (c) an incident shows prefix metadata exposure was material. Revert: pt 2's enumerated form -- a Resource-list edit per side.

**Related:** Decision 129 (pt 2 amended -- see its forward pointer; resource-axis model extended), Decision 143 (clause 1 worst-verb scoping: why `UpdateSecret` stays enumerated), Decision 156 (the policy split this lands with), Decision 101 (public-repo boundary).

## Decision 156: github_ci_apply identity-policy split -- read grants relocate to the customer-managed agent-platform-github-ci-apply-reads policy, write authority stays inline (Decided)

**Status:** Decided
**Date:** 2026-07-30
**Warehouse ID:** dec-156 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The `agent-platform-github-ci-apply` role's entire authority lives in ONE inline `aws_iam_role_policy` in `terraform/bootstrap/github_ci_apply.tf`. Measured with `terraform console` over the extracted locals (length-accurate placeholder account id, region eu-west-2), that document is **10,156 B minified against the AWS 10,240 B inline-policy hard limit -- 84 B of headroom across 33 statements** (confirmed statement-by-statement: 10,085 B of statement bodies + 39 B of document wrapper + 32 inter-statement commas = 10,156 B exactly). The rec-2882 / rec-2845 companion-verb remediation adds **~2,384 B**, which would land the inline document roughly 2,300 B OVER a hard AWS limit. Decisively: an inline-policy `LimitExceeded` is **INVISIBLE to `terraform plan`** -- it surfaces only at apply, i.e. inside the human-gated admin window, after the approval has already been spent. The split is therefore a PREREQUISITE for the fix, not an optimisation.

**Decision:**
1. **What moves -- READS MOVE, AUTHORITY STAYS.** The 11 read-only Sids (IAMRolesRead, DataLakeBucketManage, SecretsManagerReadOnly, LambdaRead, SSMParameterRead, EventBridgeRead, SNSRead, CloudWatchAlarmsRead, SNSSubscriptionRead, CloudWatchLogsRead, SSMDescribeParameters -- 3,821 B of statement body) are MOVED, not copied, out of the inline policy into ONE new customer-managed `aws_iam_policy` named **`agent-platform-github-ci-apply-reads`**, attached to the same role. Every write Sid -- every `iam:` write included -- and BOTH Deny statements stay INLINE. Post-change byte model: inline 8,580 B / 10,240 (27 statements), reads 3,998 B / 6,144 (11 statements), boundary 1,548 B / 6,144 (4 statements); one attached-policy slot consumed beyond the boundary's own slot, of ten.
2. **Reversal hazard -- the ORDER is load-bearing.** Do NOT roll this back by detaching `agent-platform-github-ci-apply-reads` alone. A bare detach strips the apply role's ENTIRE refresh-read surface, after which every subsequent CD `terraform plan` fails AccessDenied BEFORE the deterministic guard runs -- including the reconcile path that would otherwise be the recovery, so the detach locks the CD path out of its own remedy. **Correct rollback order: restore the read Sids into the inline policy FIRST, then detach.** The forward-apply window is closed the other way, by the `depends_on` edge that lands the attachment BEFORE the inline shrink applies.
3. **Protection model after the move.** The relocated grants sit behind the same EXPLICIT Deny that protects the boundary document: `DenyBoundaryPolicyModification`'s Resource list is extended with the new policy's ARN. `iam:CreatePolicy*` is absent from BOTH the identity policy and the boundary ceiling, so the role cannot mint or version a replacement; and `DenySelfInlinePolicyWrite` -- which stays INLINE -- denies `iam:DetachRolePolicy` on the role's own ARN, so the role cannot detach the reads policy from itself.
4. **Guard classification is UNCHANGED.** This is a policy-ARCHITECTURE change only: no verb's scope changes (the moved Sids move verbatim, unwidened), no apply-routing changes, no authority-budget input changes. Decision 92 point 5's in-budget inline-policy/attachment UPDATE classification and Decision 77's deterministic guard behave exactly as they did before the split.

**Reversal conditions:** The split MAY be reversed if (a) the identity policy later shrinks enough that the whole surface fits inline under 10,240 B again, or (b) AWS raises the inline-policy limit. In either case the reversal MUST follow the order in point 2 -- restore the inline read Sids first, then detach -- never a bare detach.

**Related:** Decision 144 (the allow-list inversion this split serves -- the split is the enabler for that remediation, not a change to its target model), Decision 143 (worst-verb scoping preserved, not traded away: relocation is byte-motivated and scope-neutral), Decision 92 point 5 and Decision 77 (guard classification and apply-routing unchanged by the split; see point 4), Decision 150 (the significance bar this entry clears -- a durable architectural commitment whose reversal ORDER is itself the reversal-relevant consequence, which is why this is a numbered Decision rather than an HCL comment). Provenance: raised as decision-scout's M2 finding against PLAN-iam-write-surface-completion and resolved YES by the human at plan time. Roadmap/queue refs (not DECISIONS.md entries): T2.48, rec-2882, rec-2845.

## Decision 155: The DCG-03 orphan guard tolerates a deterministically-classified transient reader outage: skip-with-marker, not job failure (amends Decision 149 clause 3's guard failure-contract by forward reference) (Decided)

**Status:** Decided
**Date:** 2026-07-27
**Warehouse ID:** dec-155 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
CI run 30101021966's `rec-autoclose` backfill job (job 89506781941) ran ~2m20s of continuous successful warehouse traffic against DuckLake -- writing/checking ~150 `ops_decisions` rows, with only one genuine write failure (dec-151, a real 502) -- before the DCG-03 orphan guard's own advisory read (`_assert_no_orphaned_current_rows`'s `current_state("ops_decisions")` call) hit a transient 502/503/504 from the DuckLake reader at the very end of the run and raised. Decision 149 clause 3 grounds that guard's RuntimeError in Decision 55 (fail loud), so the transient read blip crashed a job that had otherwise done all of its real work correctly, and `classify_closed_head` (ci_rca_lifecycle.py:178-192, "drop" only when the failing sha is an ancestor of `fixed_by_sha`) would have filed a false Critical REGRESSION rec for a run that never actually regressed. `src/common/iceberg_reader.py:430` also mislabels every such 502 as "retrying after cold-resume backoff" -- a framing this incident disproves and that steered two prior RCA agents to the wrong root cause.

**Intent:**
Stop a transient DuckLake reader infra blip on the DCG-03 guard's own advisory read from failing an otherwise-successful `ops_decisions` backfill job, while keeping every other failure mode of the guard exactly as loud as Decision 149 designed it to be.

**Decision:**
1. **Narrow scope, one named call site.** Only the `active_reader.current_state("ops_decisions")` read inside `_assert_no_orphaned_current_rows` (`scripts/ops_portal/decisions.py`) is wrapped. On `is_reader_unavailable(exc)` (the extracted, deterministic classifier at `scripts/ops_portal/reader_transient.py`), the guard emits a distinct greppable marker (`[PORTAL] DCG-03 orphan guard SKIPPED (transient reader outage)`), mirrors it to `GITHUB_STEP_SUMMARY` when set, and returns without running the orphan comparison. Every other exception, and a genuine NEW orphan, still raises exactly as before (Decision 55 fail-closed default preserved).
2. **Deterministic classification only.** `is_reader_unavailable` accepts exactly `requests.ConnectionError`/`Timeout`, or a `RuntimeError` whose message matches the reader's own transient status set (`src.common.iceberg_reader._READER_TRANSIENT_STATUS` = `{502, 503, 504}`) with no structured `error_type` marker. A structured handler error (any `error_type`-bearing message) or a 4xx is never treated as transient -- it still gates. The classifier is a single shared definition (`scripts/ops_portal/reader_transient.py`), extracted verbatim from the already-landed private copy in `scripts/data_quality_execute.py`, so the two consumers cannot drift; its accepted set is asserted equal to the reader's own authoritative set rather than restated.
3. **No general "advisory guards may skip" rule.** This Decision licenses no reclassification of the guard itself as advisory -- Decision 149 designed it to be loud, and only its dependency-read failure mode is narrowed, at this one named call site. Extending this tolerance to any other guard requires a new clause naming that call site.

**Rationale:**
Two structural facts justify the narrowing, independent of Decision 55's recovery carve-out (which is not relied on here, since it ratifies deterministic retry/reopen, not deterministic skip): (1) an independent, loud substantive signal already exists -- `_fetch_decision_from_reader` sits inside the per-row try in the same backfill, so a persistent reader outage trips `failed` on every row and the backfill's `sys.exit(1 if result["failed"] else 0)` (`.github/workflows/rec-autoclose.yml`) still exits non-zero, which `ci-rca` (a watched workflow) still files Critical on. The guard's own read can only be the sole casualty when the reader served the entire row loop and blipped on the final read -- exactly the observed incident. The backfill step is gated by `steps.detect-decisions.outputs.changed == 'true'`, and the orphan guard runs only on that same gated path, so the two are co-gated: wherever the guard can skip, the substantive signal is live. (2) The guard checks persistent warehouse state (a row with no matching `## Decision N:` header), not a transient event -- a skipped run delays detection to the next backfill rather than losing it permanently. Corroborating precedent: `scripts/data_quality_execute.py`'s DuckLake check dispatch already implements this exact tolerance (`UNAVAILABLE` verdict, not a hard failure) on this exact substrate, and Decision 62's 2026-06-16 amendment established that a reader-502-broken check is a recognised problem class on this substrate (though it ratified relocating such a check to a non-gating monitor, not skipping in place -- the in-place choice here is argued on its own merits above, not by extension of that precedent).

**Observability:** the marker is distinct and greppable, and mirrors to `GITHUB_STEP_SUMMARY` when set. No automated counter exists today, so reversal condition (a) below is operator-observed; if the marker fires regularly, the correct escalation is Decision 62's non-gating-monitor shape, not a wider skip.

**Reversal conditions:** Revert to unconditional raise-on-any-reader-error if (a) the marker is observed more than once in any 7-day window; (b) any incident in which a skipped advisory read is shown to have masked a real divergence; or (c) the substantive signal that justifies this asymmetry (the failed-counter exit at `rec-autoclose.yml`'s "Backfill decisions to warehouse" step) is removed or weakened, at which point the advisory skip must be reverted in the same change -- and unlike (a) and (b), this one is mechanically enforced by the graduated standing check `rec-autoclose-failed-counter-exit-present` (`TestSubstantiveSignalPin::test_rec_autoclose_exits_nonzero_on_failed_rows`), which fails the build if that exit line disappears or is neutralised. **Revert path:** delete the try/except around the `current_state` call in `_assert_no_orphaned_current_rows`.

**Uncomfortable properties, stated plainly:** this scope bound is prose-only for point 3 above (no mechanical backstop preventing a future author from importing `is_reader_unavailable` into another guard); the bound relies on review discipline, and a future author adopting it elsewhere must add a clause here rather than merely importing the classifier.

**Significance:** clears the Decision 150 significance bar -- a durable, reversal-relevant narrowing of a Decision-55-grounded loud-failure contract at one named call site, not a CD state-flip, operational fact, or field-semantics change.

**Related:** Decision 149 (clause 3 -- owns `_assert_no_orphaned_current_rows`; this Decision narrows its guard failure-contract by forward reference), Decision 154 (structurally identical same-day precedent: a pre-condition infra failure stops latching a hard block, via a named marker plus itemised reversal conditions -- the marker shape is modelled on it), Decision 55 (anti-masking / fail-closed default -- the governing principle every point above is checked against; its "deterministic recovery remains valid" carve-out is explicitly NOT relied on here), Decision 84 (I-3 closed named-verb read boundary -- the orphan read stays on `reader.current_state`, no fallback path, no caller SQL, no new Lambda verb), Decision 72 (RCA-as-plan-source -- this Decision is filed from the required `/plan` review that AGENTS.md forbids bypassing with an inline patch), Decision 62 (2026-06-16 amendment -- weaker corroboration than an earlier plan draft claimed; cited only for establishing reader-502-driven check failure as a recognised problem class, not for ratifying an in-place skip), Decision 150 (significance bar / batch-wave convention this entry follows). Roadmap refs (not DECISIONS.md entries): rec-2876, rec-2878 (the bundled recommendations this Decision's carrying plan, PLAN-syspath-hygiene-advisory-read-tolerance, resolves).

## Decision 154: Pre-apply failures write a non-blocking infra_error marker, not a red convergence latch (amends Decision 92 by forward reference) (Decided)

**Status:** Decided
**Date:** 2026-07-26
**Warehouse ID:** dec-154 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Run 30160878397's gated-apply job failed at "Build DuckLake lambda packages" with `DUCKLAKE_ZIP_MISMATCH ducklake-deps-layer.zip local=974c4a6564be86dc748955f7345dc1a7 remote=c6c2488d79470321851936d5253c08c8`. Apply was skipped (`APPLY_OUTCOME=skipped`), so the always-run writer took its else branch and latched status=red. Timeline: 13:59Z PR #754's speculative-plan job uploads the layer (baked pytz 2026.3); 14:03Z the push apply-sandbox job rebuilds and the assert PASSES (`DUCKLAKE_ZIP_IDEMPOTENT_OK`), guard routes to gated-apply; 15:12:05Z pytz 2026.3.post1 is published to PyPI; 15:33Z the human approves, gated-apply rebuilds, resolves 2026.3.post1, and the bytes differ. The human-approval wait IS the exposure window -- the longer a reviewer takes, the likelier a rebuild-and-reassert fails on an unrelated PyPI release. That inversion (approval latency causing platform-halting red) is the defect, not the pytz release itself.

Both sanctioned heal paths were then blocked for different reasons: Reconcile checks out the red commit and rebuilds with mode:assert, re-hitting the same mismatch, and a fix landed on main never reached its checkout; the `acknowledge_red_commit` dispatch re-plans fresh, but that plan still contains an IAM CREATE the guard BLOCKs, routing to a job gated on `github.event_name == 'push'` and therefore unreachable from a dispatch (the rec-2647 / rec-2523 deadlock).

**Intent:**
Stop a pre-apply build/fetch failure from latching the platform-halting red that only a genuine apply failure should latch, and make every human-gated apply path consume the already-reviewed DuckLake artifact bytes instead of re-deriving them across an unbounded approval wait.

**Decision:**
1. **Fetch, don't rebuild, on every human-gated apply path.** `scripts/ci/ducklake_artifacts.py` gains `fetch_reviewed()`: it downloads the per-sha reviewed artifacts (`lambda-packages/<artifact_sha>/<name>`, iterating `DUCKLAKE_ARTIFACT_NAMES` verbatim so the fetch set and the assert set cannot drift apart) and server-side `copy_object`s each onto its fixed key, failing closed (`DucklakeArtifactError`) on any missing per-sha object -- Decision 77 no-TOCTOU is preserved by the ORIGINAL PR-time byte-identical assert plus this fetch's own fail-closed missing-object check, not by a repeated rebuild-assert. It deliberately does NOT re-upload to the per-sha key (the immutable reviewed reference) and prints `DUCKLAKE_FETCH_OK` so a green record can be attributed to this route. The gated-apply job (`terraform-apply-sandbox.yml`) and both Reconcile jobs (`apply-reconcile`, `gated-apply-reconcile`) switch to `mode: fetch`; the push-path `apply-sandbox` job keeps `mode: assert` as the sole remaining reproducibility canary (its window is minutes, with no approval-wait exposure).
2. **Reconcile's own tooling must load the NEW code.** `reconcile.yml`'s two apply jobs checkout the RED commit as their root checkout (needed so terraform's own plan/state checks operate against the tree plan.bin was captured from); the composite action reference for the artifact-fetch step alone is repointed to a SECOND, dispatch-ref-pinned side-checkout (`path: .dispatch-tooling`, placed AFTER the root checkout so its `git clean` cannot wipe it) with the composite action's `working-directory` also set to `.dispatch-tooling` -- omitting the working-directory would still resolve the OLD RED_SHA copy of `scripts.ci.ducklake_artifacts` (which has no `--mode fetch`) and die on the unrecognized argument, stranding the episode exactly as before. guard.py, review_verdict.py, fetch-saved-plan, materialise-tfvars, terraform-init-retry, and write-convergence-record all still resolve from the RED_SHA checkout -- ONLY the artifact-fetch step moves to the dispatch ref.
3. **Exact-pin the DuckLake deps layer.** `scripts/build_lambda_config.py`'s five floor-pinned `DUCKLAKE_DEPS` entries (`pytz`, `psycopg2-binary`, `python-ulid`, `typing_extensions`, `pyyaml`) are exact-pinned at the versions already baked into the reviewed layer, so a PyPI release published inside a future approval window cannot flip the resolved bytes again -- this closes the root cause at its source, independent of point 1's routing fix.
4. **Three-branch convergence-record write semantics.** `write-convergence-record`'s always-run writer gains a `pre-apply-failure` input (default `"false"`, fail-closed to red). When true, it merges a non-status `infra_error` MARKER (`routed_at`, `run_url`, `commit_sha`, `failed_step`) using the SAME read-modify-write shape as the existing DEP-11 `pending_gated` marker -- status is read-modify-written UNCHANGED and the write verifies via read-back against the PRIOR status (not a literal), so the write can never silently move status while claiming to leave it alone. `pre-apply-failure` is the CONJUNCTION of (a) every apply-step id in the job reports outcome `skipped` (apply-sandbox: `apply`; gated-apply: `apply`; apply-reconcile: `apply` AND `apply_fresh`; gated-apply-reconcile: `apply`) -- the safety-critical half, since if any apply step started, infrastructure may have been mutated and the record MUST latch red regardless of what else is true -- and (b) at least one step from a CLOSED, enumerated allow-list reports outcome `failure`: `{artifact_sha, tfvars, tf_init, build_ducklake, fetch_plan}`. This is deliberately NOT "any step before the apply step": `guard` and `review` (and their Reconcile-side re-plan counterparts `replan`/`guard_fresh`/`review_fresh`) also precede apply yet MUST keep latching red, because a guard BLOCK is a fail-closed IAM/trust/destroy verdict (Decision 77/55) and an explicit reviewer REVISE is a plan rejection -- neither is an infra error. The expression is computed INLINE at each of the four write-convergence-record call sites, never routed through a job-level aggregator (apply-reconcile's `resolved` step is defined AFTER both apply steps, so permitting it would contradict the subset rule).
5. **Two deliberate, named properties of the allow-list** (stated here rather than left implicit, since a narrowing of the sole hard block demands an explicit account): (i) it is UNDER-inclusive on purpose -- `plan` (terraform-apply-sandbox.yml) and `replan` (reconcile.yml) are pre-apply yet keep latching red, which is fail-closed and safe, though it means a plan failure during backlog drain re-latches red; (ii) `fetch_plan` IS in the list, and its failure set includes the DEP-07 c2 sha256 digest-mismatch branch -- so a saved-plan TAMPER signal is downgraded from the sole hard block to a non-status marker. This is defensible (the job still fails red in GitHub Actions and ci-rca still files Critical on the sandbox path) but is named here precisely so reversal condition (a) below covers it.
6. **Anti-masking is preserved structurally, by a DIFFERENT mechanism on each of two path families** (a blanket claim would be false): on the SANDBOX paths (apply-sandbox, gated-apply), ci-rca watches `terraform-apply-sandbox.yml` independently of the record (Decision 142) and still files a Critical rec, and the marker leaving status green at an older commit while the merged tf change stays unapplied trips `stale_green_backlog` at severity=high within ~2 hours (escalate.py files a rec) -- the stronger of the two signals, and the one reversal condition (c) below is really about. On the RECONCILE paths (apply-reconcile, gated-apply-reconcile), ci-rca does NOT watch `reconcile.yml` (absent from its workflow filter) -- but masking is structurally impossible there anyway: Reconcile only ever runs against an ALREADY-red record, so leaving status unchanged leaves it RED; the marker can never turn a red into a green on this path family. The operator is woken by Reconcile's own PR wake comment and the still-red record.
7. **Health-surface visibility, not an enforcement path.** `scripts/convergence_health/record.py` gains `read_infra_error_marker()` (degrades malformed markers to `None` rather than raising); `assess.py` adds an `infra_error` field to `HealthVerdict` and FLOORS severity at `"low"` when a marker is present (raises `"none"` to `"low"`; never overrides a higher value, e.g. an already-`"high"` stuck-approval or red-age escalation). This deliberately diverges from `pending_gated`'s convention, which does NOT force severity on its own (see `test_pending_gated_does_not_force_high_severity_on_its_own`) -- `pending_gated` marks a healthy waiting state, `infra_error` marks a failure, so the floor is warranted for one and not the other. Stated honestly: severity is emitted SOLELY by `scripts/convergence_health/__main__.py`; `escalate.py` never reads it, and preflight does not read it at all -- so this floor aids a human reading `convergence_health` output only and files nothing on its own.

**Rationale:**
The sandbox convergence record's red status means "an apply ran and left infrastructure in an unknown state" -- that is the predicate the platform-wide hard block (Decision 77) exists to protect. A failure in a step BEFORE terraform apply (artifact fetch, tfvars materialisation, terraform init, saved-plan fetch) does not satisfy that predicate: the apply never ran, so infrastructure is provably in its LAST-KNOWN state, not an unknown one. Latching the same hard-block red for both cases conflates "infrastructure may be broken" with "a CI step timed out on an unrelated PyPI release," and the human-approval wait inherent to the gated paths turns that conflation into a standing landmine: the longer a reviewer takes, the likelier an unrelated rebuild fails and halts the whole platform pipeline. Fetching the reviewed bytes instead of re-deriving them removes the landmine at its source (no rebuild, so no exposure to a mid-wait PyPI release); the exact-pin closes the same root cause independently, in case a future call site reintroduces a rebuild; and the three-branch write semantics is the fallback net that keeps a bounded regression (a transient S3 blip, a botocore issue) from ever again latching a platform-halting red for something that never touched infrastructure. Precedent: Decision 94's VP10 correction already ratified that a creds-stage failure writes NO red record at all, discharging anti-masking via ci-rca -- this decision is strictly LOUDER than that baseline (it still writes something, a non-status marker, rather than nothing); and Decision 126 point 5 / T2.39 already removed the STARVED reviewer class from the red-latch path on the same reasoning, so this decision is a continuation of an established pattern, not a novel exception.

**Reversal conditions:** Revert to unconditional red if (a) any episode is observed where a pre-apply-classified failure (including a `fetch_plan` digest-mismatch, per point 5(ii) above) DID leave infrastructure mutated -- the closed allow-list's classification would then be proven unsafe, not merely under-inclusive; (b) ci-rca stops firing independently of the convergence record (Decision 142's chain-lifecycle watch lapses or is narrowed), so the `infra_error` marker becomes the ONLY signal an episode occurred; or (c) `infra_error` markers are observed accumulating unactioned for more than 7 days on the sandbox path family, indicating the "still loud via `stale_green_backlog`" claim in point 6 is false in practice. Full reversal is a one-input revert: drop the `pre-apply-failure` input's true branch (or set every call site's expression to a literal `"false"`) and every pre-apply failure again latches red, exactly as before this decision.

**Significance:** clears the Decision 150 significance bar -- a durable architectural narrowing of the sole platform-halting hard block (Decision 77), with reversal-relevant consequences and explicit, itemised reversal conditions; not a CD state-flip, operational fact, or field-semantics change.

**Related:** Decision 92 (amended by forward reference -- the gated-apply / tf-gated-apply Environment model whose always-run write this decision narrows from two branches to three; Decision 92's own body is not edited, per the Decision 126/143/145 amend-only convention), Decision 77 (no-TOCTOU; the platform-halting hard block this decision narrows the LATCH TRIGGER for, not the block itself), Decision 55 (anti-masking -- the governing principle every point above is checked against), Decision 72 (ci-rca forward-fix precedent), Decision 94 (VP10 creds-stage correction this decision is strictly louder than), Decision 126 (point 5 / T2.39 STARVED-class precedent; point 2, agents never self-direct terraform apply), Decision 142 (ci-rca fingerprint v2 / chain-lifecycle -- the sandbox-path anti-masking mechanism point 6 relies on), Decision 150 (significance bar; batch-wave/reversal-conditions convention this entry follows), Decision 143 (derive-the-set-assert-equality pattern `fetch_reviewed()` follows for `DUCKLAKE_ARTIFACT_NAMES`), Decision 131 (test-mirror convention -- not applied here; `tests/ci/` does not exist, the file is `tests/test_ducklake_artifacts.py`). Roadmap refs (not DECISIONS.md entries): T2.22 (gated-apply), T2.37 (Reconcile heal button), T2.42 (DuckLake artifact identity / c1 layer decoupling this decision's rationale depends on), T2.48 / DEP-02 (the stalled live-proof this decision unblocks), rec-2862 / rec-2824 / rec-2522 (the bundled recommendations this plan resolves).

## Decision 153: Fast-tier budget assertion waives a full-suite-forced --pre run (warn, not hard-fail) bounded by a forced-run ceiling derived from the pr-validate job timeout (amends Decision 73 enforcement + Decision 135) (Decided)

**Status:** Decided
**Date:** 2026-07-24
**Warehouse ID:** dec-153 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 135's affected-set selector (as hardened by audit finding VTS-03) forces FULL-suite scope on the --pre fast tier whenever a PR changes the root `tests/conftest.py`, emitting a `full_suite_forced` flag into the selection manifest. That signal was wired to nothing: Decision 73's fast-tier BUDGET assertion (`scripts/validate.py::_scaffold_budget_assertion`) hard-fails the build (exit 1) whenever elapsed exceeds the 5-minute (300s) budget, with no knowledge of the forced-scope flag. A root-conftest edit deterministically runs the full ~6930-test suite (~19.8 min, already at `-n auto`), so the budget assertion hard-blocks ANY conftest-editing PR from merging via normal CI -- it blocked Slice B's PR #727. Slice A's plan (`PLAN-affected-set-recall-hardening`) called the budget assertion a "sanctioned backstop" and cited Decision 135 reversal-condition (b)/KG.13 as the relief valve, but that relief valve is structurally dead at this repo's concurrency: the KG.13 build-orchestrator revisit trigger (Decision 80 point 4, line 3768; Decision 135's KG.13 boundary note, line 911) is an AND-gate requiring `executor concurrency > 1 AND (KG.13 filed OR a fast-tier-budget breach recurs)`, and this is a sole-developer repo at concurrency 1 ("At T4.1 concurrency = 1", Decision 80). The AND-gate can never fire, so a breach never arms any relief -- the "backstop" was in practice an unbypassable blocker.

**Intent:**
Teach the fast-tier budget gate about its own `full_suite_forced` signal so a deterministic, already-diagnosed full-suite run (a root-conftest PR) warns-and-passes instead of hard-failing, while keeping the gate's anti-drift teeth for every ordinary breach and bounding the forced path with a guardrail derived from the pr-validate job timeout.

**Decision:**
This decision preserves Decision 60/73's two-tier model unchanged: exactly two named validate surfaces (--pre and default) and exactly two CI gating roles (pre-merge PR gate; post-merge full tier). It adds no invocation flag, no workflow job or trigger, no registered check or scaffold step (registry.py and FROZEN_PRE_SCAFFOLDS untouched), and no selection behaviour -- the forced-scope selection it responds to was ratified by Decision 135/VTS-03. A forced run remains a fast-tier run by every tier-defining property: it executes the fast tier's own check sequence (registry.pre_sequence()), in the same pr-validate job, with no AWS credentials and none of the full tier's exclusive checks; only its pytest selection breadth differs, which Decision 135 already governs.

1. **Forced-scope waiver (amends Decision 73 enforcement).** In `scripts/validate.py::_scaffold_budget_assertion`, when the selection manifest's `full_suite_forced` is true AND elapsed exceeds the 5-minute (300s) budget but is at or under a 25-minute (1500s) forced-run ceiling, the assertion emits a DISTINCT "budget waived: full-suite scope forced by root-conftest change" notice (mirrored to the CI step summary), skips the already-diagnosed `_file_budget_breach_rec` stream, and does NOT exit non-zero. This narrows Decision 73's "the fast tier asserts wall-clock budget and fails non-zero on breach" (point 1 / the "Enforced budgets" rationale) for exactly one deterministic, self-identified case.
2. **Hard-fail preserved for every non-forced breach.** When `full_suite_forced` is falsy, behaviour is EXACTLY as before: `_file_budget_breach_rec` + the existing ERROR diagnostic + exit 1. The gate's anti-drift purpose is intact; this is not a general weakening. The read is fail-closed -- `_empty_manifest` sets `full_suite_forced=False` and the code reads it with `.get(..., False)`, so a Decision-55 derivation-failure fallback hard-fails rather than accidentally waiving.
3. **Forced-run ceiling (a derived guardrail, not a second budget).** Even when `full_suite_forced`, elapsed above the 1500s ceiling hard-fails (exit 1) with a distinct ceiling-breach notice; this path is INTENTIONALLY rec-free (it does not file `_file_budget_breach_rec` -- the ceiling notice mirrors to the CI step summary instead). The fast tier retains exactly ONE design budget: 300s. 1500s is not a second budget; it is derived -- the pr-validate job's 30-minute infrastructure timeout (`.github/workflows/ci.yml`) minus a ~5-minute diagnostic margin, expressed on validate.py's own elapsed clock so the identical bound holds locally, where `timeout-minutes` does not exist. The bound lives in validate.py rather than being delegated to the job timeout because validate.py is the single source of truth for validation logic (AGENTS.md merge protocol) and because a timeout kill is an opaque infra cancellation with no elapsed/dominant-phase diagnostic. If pr-validate's `timeout-minutes` changes, the ceiling is re-derived from it; it is never renegotiated independently.
4. **Not a new tier (the ceiling is a guardrail).** A tier in this repo is a chooseable validation surface -- an invocation flag plus check sequence, selection scope, trigger/role, and budget contract selected ex ante (Decision 60's "which flag should I use"; Decision 73 points 1-2). The forced-run ceiling has none of these properties: it cannot be invoked, requested, or routed to; it selects and schedules nothing; it fires ex post inside the existing budget_assertion step and only maps an already-elapsed run to pass/warn/fail. It is a bounded guardrail WITHIN the fast tier, in the same ratified class as the budget-vs-timeout distinction the full tier already exhibits (honest 15-30-min budget, no assertion, 60-minute job timeout) -- an outer runaway bound, not a second budget regime and not a third tier.

**Amends Decision 135:** the `full_suite_forced` manifest flag (Decision 135 point 5 surface, populated by VTS-03) becomes a load-bearing gate input, not merely an observability field. Decision 135 carries an internal inconsistency on the KG.13 trigger: its KG.13 boundary note (line 911) states `concurrency > 1 AND (KG.13 filed OR budget breach)` while reversal-condition (b) (line 942) parenthetically reads `concurrency > 1 OR a genuine fast-tier-budget breach`. The AUTHORITATIVE form is the AND-gate boundary note (concordant with Decision 80 point 4); reversal-condition (b) is a design-REVISIT SIGNAL (it invites re-examining whether a selection/coverage cache is warranted), NOT a runtime waiver -- a breach never lets the stranded PR pass. That is precisely why an in-band budget-gate waiver, not the KG.13 relief valve, is the correct forward-fix.

**Rationale:**
The budget assertion exists to catch fast-tier DRIFT -- a check silently growing past its contract (Decision 73 "Enforced budgets"). A root-conftest change is not drift: it is a rare, deterministic, self-identified event whose full-suite cost is understood and expected (Slice A consciously routed it to full scope). Blocking it teaches nothing and merely strands the PR, because the only sanctioned escape (`--ignore-budget`) is forbidden in CI (the `validate.py` CI guard) and the KG.13 relief valve cannot arm at concurrency 1. Warning-and-passing the forced case while preserving the hard-fail for every ordinary breach keeps the anti-drift signal exactly where it is meaningful, and the derived forced-run ceiling (the pr-validate job timeout surfaced ~5 minutes early on validate.py's own clock) preserves an enforced upper bound so the forced path cannot itself become an unbounded escape.

**Known residual (deliberately not engineered):** `full_suite_forced` is set only for the ROOT `tests/conftest.py` (`scripts/checks/deps/affected_tests.py`). An autouse-fixture-bearing SUB-conftest uncaps its own subtree (VTS-03 `conftest_subtree_forced` provenance) but sets `full_suite_forced=False`, so a large forced subtree could still hard-fail the 5-minute gate. This is left as-is: sub-conftest subtrees are bounded and the case is rare; widening the waiver to a per-subtree budget is out of scope and would dilute the signal. If it manifests, the remedy is to extend the flag (or add a bounded per-subtree allowance), tracked then, not now.

**Reversal conditions:** Revisit if (a) forced-scope waivers become frequent enough that they mask genuine fast-tier drift landing in the same PRs as conftest edits (tighten to require the manifest also show no non-conftest slow-check growth); (b) the 25-minute ceiling is hit in practice (the forced full suite genuinely exceeds it -- then the suite itself, not the gate, is the problem, and this arms the Decision 80 point 4 / KG.13 revisit on its own terms if concurrency has by then risen above 1); (c) the known-residual sub-conftest case starts hard-failing real PRs (extend the flag); (d) if the ceiling's value is ever proposed for change independently of the pr-validate job timeout (or vice versa), it has drifted into being a de-facto second budget -- re-adjudicate against the two-tier commitment stated here before amending. Full reversal (drop the waiver, restore the unconditional hard-fail) is a one-function revert with no data or schema migration.

**Significance:** clears the Decision 150 significance bar -- a durable architectural commitment (amends a ratified CI enforcement invariant), with reversal-relevant consequences and explicit reversal conditions; not a CD state-flip, operational fact, or field-semantics change.

**Related:** Decision 73 (fast-tier budget enforcement this narrows -- amended in Decision 153's body per the Decision 134/145 amend-only convention; Decision 73's own body is not edited), Decision 135 (the `full_suite_forced` signal source and the KG.13 boundary this reconciles), Decision 80 point 4 (the concurrency>1 AND-gate KG.13 revisit trigger that is the dead relief valve at concurrency 1), Decision 60 (the tier-definition authority -- the named-surface test this decision's not-a-tier adjudication applies -- and originating two-tier / 5-minute-budget ratification), Decision 150 (significance bar this entry is checked against), Decision 55 (fail-loud fallback -- the waiver reads fail-closed), Decision 48 (V2 verification tier), Decision 131 (test-colocation mirror -- the new tests live beside the budget-assertion tests), Decision 84 (warehouse SoT + decision-numbering authority). Roadmap refs (not DECISIONS.md entries): KG.13 / T3.11 c5 (the deferred TIA/cache work, still undisturbed), the validate-test-suite audit (VTS-03, which introduced `full_suite_forced`), Slice B PR #727 (the PR this unblocks).

## Decision 152: Decision-scout SPIRIT axis -- a quotability-gated intent-alignment triage lane distinct from literal contradiction (audit finding DCG-07, Q3c adopt-scoped) (Decided)

**Status:** Decided
**Date:** 2026-07-24
**Warehouse ID:** dec-152 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The decision-scout gate triages a proposed plan against the corpus on ONE axis only -- literal
contradiction (`.claude/skills/decision-scout/SKILL.md` CONTRADICT bucket = "violates an active
decision"). A plan can obey every literal clause while working against the durable *spirit* of a
ruling, and that failure mode passes the gate as NO_FLAGS (or at best surfaces as diluted RELATED
context with no violation semantics). Audit finding DCG-07
(audits/decision-consolidation-growth-f79d6b5.yaml, Q3c adopt-scoped) names this as the unconsumed
half of NS-1's query -- "is my plan aligned with the spirit of the corpus?" -- now that Decision 151
(DCG-06) has given the corpus a quotable **Intent:** anchor to align against.

**Intent:**
Give the scout a second, intent-alignment triage lane so a spirit violation without literal
contradiction is surfaced, WITHOUT letting that fuzzier axis collapse into the defensive-over-citation
noise the skill's own doctrine forbids. The anti-noise gating IS the design: a SPIRIT flag exists only
when it can be grounded in a verbatim quote of the violated Intent/Problem/Rationale, never carries
BLOCK, is capped at 3, and never double-flags a decision already caught literally. The lane is
prompt-level methodology (convention-only, no validator, mirroring Decision 146), tractable precisely
because the scout already reads the whole corpus -- audit TRAP-7: this adds a judgment axis, never a
change to HOW the corpus is read (the deferred agent-context-governance audit owns that). That
tractability is itself regime-dependent, not a permanent given: the SPIRIT lane and the prose budget it
consumes are workable at current scale precisely because the scout's whole-file `docs/DECISIONS.md`
read already exists, and that dependency ties to the same post-MVP migration to cloud-hosted,
verb-queried decision-corpus access that Decision 151's SCD2-precursor rationale anticipates (see
Reversal conditions below).

**Decision:**
1. **SPIRIT bucket + four gates.** `.claude/skills/decision-scout/SKILL.md` gains a Phase-2
   spirit-alignment overlay step defining a SPIRIT bucket that fires ONLY when all four hold: (i) no
   literal CONTRADICT on the same decision (literal supersedes; a decision appears in at most one
   lane); (ii) the flag quotes VERBATIM the violated decision's **Intent:** marker (new entries) or a
   specific Problem/Rationale sentence (historical band) -- unquotable means no flag; (iii) severity
   WARN or NOTE only (BLOCK stays literal-contradiction-only); (iv) capped at 3 flags, inside the
   existing ~1,200-word response budget.
2. **Output contract + verdict.** A mandatory-even-when-empty `### Spirit-Alignment Flags (SPIRIT)`
   section with a "None" default (the parent parser never branches), and a widened Verdict definition:
   FLAGS_FOUND fires on >=1 SPIRIT flag OR >=1 CONTRADICT WARN/NOTE. The three verdict strings
   (NO_FLAGS | FLAGS_FOUND | BLOCK) and the `## Decision Scout Report` / `Verdict` interface are
   UNCHANGED -- every existing caller (the /plan Step 6a gate, the overseer decision-scout gate) parses
   the same surface. Two Quality-Gate rows enforce the gates (every SPIRIT flag carries a verbatim
   quote; SPIRIT count <= 3 with no CONTRADICT overlap).
3. **Prose-budget funding.** The addition breaches the skill's zero-headroom `config/prose_budgets.yaml`
   S4 entry; this Decision funds the raise via a `# raise-approved: dec-152` marker (Decision 127/43
   sanctioned-prose taxonomy). Decision 128's decompose-don't-raise relief valve is SLOC-specific and,
   by the prose registry's own header, does not apply here; the registry forbids @-import fragmentation
   (Decision 114/110), so a loud Decision-cited raise is the correct relief valve. Only the FILE byte
   budget is raised; the ~1,200-word RESPONSE cap is unchanged.

**Rationale:**
The SPIRIT axis is the consumer that makes Decision 151's Intent marker load-bearing end-to-end: DCG-06
gave the corpus a quotable anchor, DCG-07 gives a gate that quotes it. It is a distinct lane rather than
an extension of CONTRADICT because the two have different evidentiary bars (literal clause-violation vs.
quotable spirit-divergence) and different consequences (BLOCK-eligible vs. WARN/NOTE-only); folding
spirit judgement into CONTRADICT would either over-block on soft tensions or dilute the literal lane.
The quote-or-drop gate is the same operator-disposed, non-mechanically-decidable judgement stance
Decision 146 settled for archival eligibility -- "aligned with the spirit" is not machine-decidable, so
it routes to grounded LLM judgement with a hard evidentiary floor (the verbatim quote), not an automated
check. Routed per Decision 86: methodology in the skill, this rationale here, no new prose doc.

**Reversal conditions:** The SPIRIT axis in its current form is a CONSEQUENCE of the present regime in
which the decision-scout reads the ENTIRE `docs/DECISIONS.md` corpus into context (an all-file prose
dump) -- the SPIRIT lane and the prose budget it consumes are workable at current scale PRECISELY
BECAUSE that whole-corpus read already exists. The planned post-MVP migration of the decision corpus to
cloud-hosted, VERB-QUERIED access (the same migration Decision 151's SCD2-precursor rationale
anticipates) removes that whole-file-read inefficiency; when it lands, THIS decision is revisited to
make the SPIRIT axis leaner and query-driven rather than prose-budget-funded. The removal of the
whole-file-read inefficiency is ITSELF the reversal trigger. Separately and sooner than that migration,
revert the SPIRIT axis (remove the bucket, restore the CONTRADICT-only verdict, and lower the prose
budget back) if in practice it produces net noise -- e.g. SPIRIT flags are routinely waved through at
Step 6b without changing plans, or the quote-gate proves insufficient to prevent defensive
over-citation. If instead the axis proves valuable but convention-only enforcement drifts, the
escalation is a mechanical quote-presence check in the scout's Quality Gate, not removal.

**Related:** Decision 151 (the **Intent:** marker this lane quotes; DCG-06, this finding's depends_on),
Decision 150 (the significance bar this Decision clears and the routing taxonomy it exercises), Decision
127 and Decision 43 (the sanctioned-prose byte-budget taxonomy governing the prose_budgets.yaml raise),
Decision 128 (SLOC decompose-by-default -- SLOC-specific, explicitly not applicable to the prose
registry; the raise is the sanctioned prose relief valve), Decision 134 and Decision 145 (the
DECISIONS.md live byte ceiling this entry stays within, and the scout's own size-ceiling context),
Decision 146 (the operator-disposed, convention-only-enforcement stance this axis's quote-or-drop
judgement mirrors), Decision 100 and Decision 75 (the managed-service-native WARN check in the same
Phase 2, preserved unchanged), Decision 105 (this is a forward governance Decision, NOT a CD
ratification -- the R1-R3 guard is not engaged), Decision 90 (the four-tier workflow whose Step 6a gate
the scout serves), Decision 86 (methodology-in-skill / rationale-in-Decision routing -- no new prose
doc), Decision 55 (loud-fail, no rescue).

## Decision 151: Decision-record Intent as a first-class optional element -- typed extraction, dated append-only accretion convention (audit finding DCG-06, Q3a adopt-scoped / Q3b adopt) (Decided)

**Status:** Decided
**Date:** 2026-07-24
**Warehouse ID:** dec-151 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
A decision's durable semantic "why" -- the one-line intent a future consumer can quote without re-deriving
it from the full Rationale prose -- has no typed home. It is either buried inside Problem/Rationale prose
(never separately queryable) or omitted entirely. Audit finding DCG-06
(audits/decision-consolidation-growth-f79d6b5.yaml, Q3a adopt-scoped / Q3b adopt) recommends an OPTIONAL
`Intent` element and a typed `intent` column purely for surfacing this quotable why -- never a
required-marker change, never retro-enforcement of the historical band (DAF-03 forward conformance
untouched, mirroring the Decision 134 cl.3 authoring-grammar precedent).

**Intent:**
Give the decision-record format a place for the durable "why" a consumer can quote, without retroactively
obligating the historical corpus to supply one. The typed column is populated exactly the way
raw_block/reversal_conditions/superseded_by/content_hash were (Decision 134 cl.4, DAF-01): additive,
nullable, parser-extracted, DQ-deferred. This entry's own Intent text is also the first worked example of
the mutability convention it records below: once ratified it is never rewritten in place, only extended by
dated, source-cited, append-only annotations -- a deliberately SCD2-shaped choice, so the in-band dates
supply the reader-visible valid-time the current transaction-time-only SCD2 substrate otherwise lacks,
letting a post-MVP migration to cloud-hosted verb-queried storage map this field's accretion onto warehouse
SCD2 versioning with no remodel.

**Decision:**
1. **Optional Intent marker.** `docs/contracts/decision-entry.yaml`'s `optional_markers_fixed_spelling`
   gains `Intent`, placed narratively after `Problem` and before `Decision` (Problem -> Intent -> Decision
   -> Rationale). Exactly as optional and forward-only as the other five entries in that list -- no change
   to `required_markers`, no retro-enforcement of the historical band.
2. **Typed extraction, warehouse column, and deploy path.** `scripts/decisions_md.py::parse_decisions_md`
   gains an `intent` key via `_extract_multiline_section(body, "Intent")`, a NEW separate key -- the
   existing `context` extraction (Rationale/Key details/Context) is untouched. `docs/contracts/
   ops_decisions.yaml` (the CD.25 Class A contract, Decision 118) gains a nullable `intent` field mirroring
   the raw_block/reversal_conditions shape (`dq_intent.not_null.enforced: false`, Phase-2 deferral),
   regenerated into `config/lambda/ducklake/field_semantics.yaml` via `scripts.schema_to_field_semantics`
   (never hand-edited, Decision 65). `intent` is threaded onto both `src/schemas/decision.py::
   DecisionPayload` and `scripts/executor/jsonl_store.py::Decision` as a PLAIN `str | None` -- never
   `Annotated[...]`/`DqNotNull`/any `Dq*` marker (keeps `validate_pydantic_yaml_drift` out of scope, same
   reasoning as the DAF-01 fields) -- and into `scripts/ops_portal/decisions.py::_DECISION_BACKFILL_COLS`
   so the backfill ETL threads it to the writer. Ships through the governed DuckLake code-deploy channel
   (Decision 79/125/126); the physical `ALTER TABLE ADD COLUMN` is an operator-invoked `reconcile_columns`
   admin verb (Decision 143), never autonomous.
3. **Intent mutability convention (Step 6b option c).** Once ratified, an Intent section is never freely
   rewritten in place. (i) draft-until-merge -- before merge, the Intent marker is an ordinary draft,
   rewritten freely during PR review (this entry's own Intent marker above was drafted and revised under
   exactly this rule); ratification (merge) is the mutability boundary. (ii) post-merge accretion -- after
   merge, the original Intent text is NEVER rewritten; clarifications, caveats, and exceptions accrue as
   dated, source-cited, append-only annotations INSIDE the Intent section, using the EXISTING
   `docs/contracts/decision-entry.yaml` `amendment_forms` grammar (no new marker syntax), so the typed
   `intent` column carries "original + dated deltas" automatically and each edit still bumps `content_hash`
   into a new SCD2 version like any other body change. This layers two conventions on top of that existing
   grammar, not a divergent shape from it: (a) the `trailing_bracket` form's annotation gains a `<source>`
   citation clause -- `[Amendment YYYY-MM-DD, <source>: ...]` -- tightening, not replacing, the base
   `[Amendment YYYY-MM-DD: ...]` shape; (b) placement narrows to INSIDE the Intent section specifically, one
   legal location within the base grammar's broader "appended after the entry's original body" description.
   (iii) provenance -- every clarification cites a ratified source: a later Decision, an audit id, or
   explicit operator direction. The correction CHANNEL is open to agents (via hand-back or a recommendation
   proposing the wording); the correction AUTHORITY is not -- an agent's evolved understanding lands only at
   operator direction or by citing an already-ratified source, mirroring the CLAUDE.md memory policy
   (propose, do not silently save). A clarification may narrow or annotate but never negate the decision's
   effect -- an intent that contradicts the decision text is a mis-drawn decision, which supersedes, not
   clarifies. (iv) cap -- at roughly 3 accreted clarifications, or the Intent section exceeding ~120-150
   words (whichever first), escalate to a SUPERSEDING Decision -- itself clearing this same significance
   bar, being reversal-relevant -- followed by a Decision 149 compaction of the superseded entry. A
   cap-driven supersession is a normal, expected lifecycle event, not a failure. (v) enforcement --
   convention-only, mirroring Decision 146's operator-disposed archival stance: NO validator, no stored
   guard, no intent-drift signal now (a read-time query later, per audit Q4, is a different, unbuilt thing)
   -- backstopped by the existing 500,000-byte live-file ceiling (Decision 134/145) and ordinary PR review.
4. **`decision-entry.yaml` pointer note.** A short `intent_accretion_note` paragraph is added adjacent to
   `amendment_forms`, stating the Intent marker follows this same dated-append accretion model
   post-ratification and pointing here for the full convention. `significance:` (Decision 150) and
   `compaction:` (Decision 149) are untouched.

**Rationale:**
The dated-append-only model is deliberately SCD2-shaped, and that is the load-bearing reason it was chosen
over free in-place editing: `ops_decisions` is Type-2 SCD on TRANSACTION time only (a new row version
records when a write happened, not what span of real-world time the recorded fact was valid for). An Intent
section that could be edited in place would lose exactly the valid-time dimension a reader needs to answer
"was this true when I read it before, or did it silently change?" -- and this transaction-time-only
substrate cannot answer that on its own. In-band, source-cited dates on each accreted clarification supply
that missing reader-visible valid-time without any warehouse remodel: each dated annotation is itself a
small valid-time interval nested inside the entry's single current transaction-time row. This also means a
post-MVP migration of decisions to cloud-hosted, verb-queried storage maps the field's accretion pattern
onto genuine warehouse SCD2 versioning (one row per accretion) with no remodel -- the convention is a
forward-compatible precursor to that migration, not merely a governance nicety. Convention-only enforcement
(no validator) follows Decision 146's already-settled operator-disposed stance for a structurally similar
judgment call (archival eligibility): "fully superseded" and "clarification vs. supersession-worthy" are
both non-mechanically-decidable, so both route to operator/PR-review judgment rather than an automated
gate. Per Decision 86, rationale lives here and the field's mechanical semantics live in the owning
contract (`ops_decisions.yaml`) and `decision-entry.yaml` -- no new standing prose document.

**Reversal conditions:** Revisit the dated-append-only mutability convention if PR review proves an
insufficient backstop in practice (e.g. clarifications routinely drift from their cited source) -- the
escalation path would then need a mechanical trigger instead of the ~3-clarification / ~120-150-word
convention-only cap. Revisit the optional-forever posture on the marker itself only if a future audit finds
the historical corpus's absence of intent is itself a live cost worth a retro-enforcement campaign -- not
anticipated by this Decision.

**Related:** Decision 134 (the DAF-01 parity-column precedent this element's typed-extraction /
nullable-column shape and content_hash-over-raw_block mechanism directly reuses), Decision 150 (the
significance bar this Decision clears, and the significance-taxonomy routing this Decision itself
exercises), Decision 149 (the compaction lifecycle a cap-driven Intent supersession will invoke), Decision
84 (warehouse-as-source-of-truth, the backfill ETL, and the caller-keyed decisions numbering exception,
I-2), Decision 118 (the CD.25 pre-codegen contract-ratification ritual this `ops_decisions.yaml` field_add
amendment follows), Decision 79 (per-Lambda packaging / deploy-verify gating, the authority for the writer
redeploy this column's live path depends on), Decision 125 and Decision 126 (the DuckLake governed decoupled
code-deploy channel this change ships through), Decision 143 (privileged-verb decomposition --
`reconcile_columns` is admin-tier, amending Decision 81), Decision 132 (verification-graduation as an
enforced pre-merge obligation -- every pre-deploy VP step on this change carries a disposition), Decision
119 (CI-delegation / grep-only local verification for generated-and-deployed assets), Decision 65 (the
contract is the field-semantic authority and generation source), Decision 86 (field semantics route to the
owning contract, not a new prose doc -- the routing this Decision's own pointer note follows), Decision 55
(loud-fail, no rescue loops -- governs the writer-health-gated post-deploy legs), Decision 128 (SLOC
decompose-by-default, preserved unchanged by this narrowly-scoped change), Decision 99 (no `version.yaml`
DuckDB lockstep bump for an additive column), Decision 98 (deploy-role provisioning precondition -- the
no-op-green risk this change's V3 verification checks for), Decision 105 (candidate-decision ratification
lane -- NOT engaged here; this is a forward governance Decision, not a CD ratification), Decision 81 (the
closed reader/writer boundary that Decision 143 amends and `reconcile_columns` operates within), Decision 70
(append-only physical-deletion lifecycle, context for why this column is additive-only and never retrofits
historical rows), Decision 146 (the operator-disposed, convention-only-enforcement stance this Decision's
mutability convention explicitly mirrors).

---

## Decision 150: Decision-log growth direction -- significance bar for numbered Decisions + batch-wave ratified form (amends Decision 105) (Decided)

**Status:** Decided
**Date:** 2026-07-24
**Warehouse ID:** dec-150 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 145's stopgap ceiling raise and Decision 149's compaction lifecycle both treat decision-log
growth as a SIZE problem (bytes/headers), but audit finding DCG-05 (high,
audits/decision-consolidation-growth-f79d6b5.yaml Q2) names an unaddressed DIRECTION problem:
nothing states the bar for what MAY become a numbered `## Decision NNN:` entry in the first place,
so the corpus can keep growing unbounded in SHAPE even after compaction reclaims bytes --
degrading decision-scout triage cost and lower-tier-model portability. DCG-04 (medium, same audit)
names a second symptom of the same shapeless growth: Decision 105's ratification lane already
reconciled a many-CDs-to-one-Decision shape in practice (CD.16/CD.24 -> dec-079) but never
codified it as a reusable form, so each future same-session batch of gate-clear ratifications
defaults to minting one Decision per CD instead of one shared wave entry.

**Decision:**
1. **Significance bar (realizes DCG-05).** `docs/contracts/decision-entry.yaml` gains a
   `significance:` section: a numbered `## Decision NNN:` entry is reserved for a durable
   architectural commitment with reversal-relevant consequences; three other classes of durable
   content route elsewhere instead of minting a new number -- a CD state-flip routes to the
   batch-wave clause below (clause 2), an operational fact routes to a recommendation or tier_item
   note, and field semantics route to a governance note in the owning contract (Decision 86/127
   routing). `.claude/skills/planning/SKILL.md` cites this section at a new "Decision Significance
   Gate" note just before the Candidate Decision Ratification step (Step 5b), so any
   numbered-Decision draft -- fresh governance Decision or CD ratification -- is checked against it
   before drafting. The section's four routing rows are a citable classification vocabulary in
   their own right, independent of any one Decision.
2. **Batch-wave ratified form (amends Decision 105, realizes DCG-04).** Same-session PURE
   candidate_decision (CD.NN) ratifications -- gate-clears carrying no content beyond "this CD's
   work is realized" -- may land as ONE `## Decision N` wave entry instead of one entry per CD:
   each bundled CD gets its own clause inside the shared entry, and each CD's `ratified_as` /
   `filed_via` points at the same shared `dec-NNN`. A ratification that carries independent
   content keeps its own entry; it is never bundled. This codifies forward, as a first-class form,
   the many-to-one shape Decision 105's own ratification lane already exercised (CD.16 and CD.24
   both ratified under Decision 79; Decision 105 itself reconciled 5 CDs in one entry) --
   `docs/contracts/candidate-decision-ratification.yaml` gains a `batch_wave_ratified_form` section
   documenting the shape and noting that the R1-R3 referential guard tolerates it by construction
   (each CD is checked independently; no cross-CD `ratified_as` uniqueness bar).
   `.claude/skills/implement/SKILL.md`'s CD Ratification Bookkeeping step gains a matching
   batch-wave clause: entry-authoring and the portal ETL run once for the whole wave, but the three
   per-CD sub-steps -- the roadmap-flip, the marking-convention obligation, and the pending-window
   prose sweep -- repeat once per bundled CD; preflight and validate still run once over all
   bundled CDs; tier_item status flips remain a separate bookkeeping step (Decision 90, unchanged).

**Rationale:**
Decision 134/145 govern how big the corpus may get and Decision 149 governs how a superseded entry
sheds body weight, but neither constrains what is ALLOWED IN at the front door -- the audit (Q2)
frames the significance bar and the batch-wave form as two facets of one answer to that gap: a bar
that is worthless without a legal outlet for the content it excludes (the batch-wave form IS that
outlet for the largest deflected class, CD state-flips), and an outlet that is worthless without a
bar motivating anyone to use it instead of minting a fresh Decision by default. The two clauses are
interdependent by construction -- the significance taxonomy's `cd_state_flip` row routes directly
into the batch-wave form -- so one two-clause Decision carries both facets under a single
reversible identity rather than splitting a single direction mechanism across two numbers. Routed
here per Decision 86 (rationale in this Decision, taxonomy in `decision-entry.yaml`, mechanism in
`candidate-decision-ratification.yaml` and the two skill files) -- no new standing prose doc.

**Reversal conditions:** The batch-wave form reverts to one-entry-per-CD if the wave shape is found
to obscure per-CD provenance in practice. The significance bar relaxes (or a routing row is
re-drawn) if it is found to suppress content that is genuinely decision-worthy.

**Related:** Decision 105 (amended -- see its reciprocal marker), Decision 145 (the byte-ceiling
stopgap this direction mechanism complements), Decision 149 (the compaction/shape-after-entry
sibling mechanism), Decision 146 (the archival policy in the same growth-governance family),
Decision 134 (the size-governance ceilings and authoring grammar this extends), Decision 86
(rationale/routing precedent this Decision and its contracts follow), Decision 84 (Single Portal
Invariant / numbering authority for the ETL landing this entry), Decision 90 (tier_item status
flips stay a separate bookkeeping step from ratification, preserved unchanged), Decision 79 (the
CD.16/CD.24 -> dec-079 precedent the batch-wave form codifies forward).

> **Amended by Decision 167 (2026-08-07):** Decision 167 extends this significance bar with a
> machine-enforced routing claim (the required envelope `significance` field) and a routing
> rule / standing-commitment pair in `docs/contracts/decision-entry.yaml`.

---

## Decision 149: Number-preserving decision-compaction lifecycle -- compact-in-place stub grammar, never-remove-headers, and the DCG-03 orphan-divergence guard (DCG-02/DCG-03, compact-in-place sibling of Decision 146's archival policy) (Decided)

**Status:** Decided
**Date:** 2026-07-23
**Warehouse ID:** dec-149 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 155 (2026-07-27):** clause 3's DCG-03 orphan guard now tolerates a
> deterministically-classified transient DuckLake reader outage on its own `current_state`
> read (skip-with-marker, not job failure) at the single named call site
> `_assert_no_orphaned_current_rows`. This body is otherwise unedited; see Decision 155 for the
> full derivation, constraints, and reversal conditions.

> **Amended by Decision 165 (2026-08-04):** the compact-in-place stub grammar's interaction with
> the five raise-marker guards is closed by a one-hop supersession fallback in the shared
> `scripts/checks/_marker_guard.py` authorization mechanism -- when a cited Decision's body is a
> compaction stub, the superseder's body is also consulted for authorization, so a future
> compaction of a live-cited Decision cannot silently un-authorize every marker citing it. This
> body is otherwise unedited; see Decision 165 for the full derivation.

**Problem:**
Decision 145's stopgap ceiling raise (400,000 -> 500,000 bytes) bought headroom but explicitly named the un-built structural fix as audits/decision-consolidation-growth-f79d6b5.yaml's DCG-01/DCG-02/DCG-05: a number-preserving compact-to-stub lifecycle, so the live corpus can shed fully-superseded bodies without breaking the ~12,103 unguarded inbound "Decision N" citations or orphaning a warehouse current-projection row (DCG-03: if a header were ever removed from both files, its ops_decisions current row would be served forever in its last state with no signal it was retired). Decision 146 (the archival sibling, landed first) covers entries with no live citations outside the corpus; it explicitly carves out entries "still cited as a LIVE constraint" (its own worked example: Decision 44 -> 117) as staying in the corpus, with no compaction mechanism yet built for them.

**Decision:**
1. **Compaction lifecycle.** `docs/contracts/decision-entry.yaml` gains a `compaction:` section: an eligibility criterion (an entry compacts only when its ENTIRE body is superseded/inert and the superseder restates/subsumes every live clause; direction-consistency -- only the superseded victim compacts, never the superseder, per the archived-52-supersedes-live-37/40 inversion), a stub grammar (the header line and its ORIGINAL parenthetical are unchanged; the body carries `**Status:** Superseded`, an ISO `**Date:**`, a non-empty one-line `**Decision:**`, and the exact `**Superseded by: Decision N**` marker), and a never-remove-headers rule (number retirement and destructive merges are permanently out of the mechanism's vocabulary). An operator `procedure:` block (Decision 127 pattern) names the archive-vs-compact branch: archive whole per Decision 146 when nothing live cites the number by name; compact in place only when it can't.
2. **First exercised compaction: Decision 44.** Its ~40-line boundary-pattern-table body is replaced with a conforming stub. The table itself has lived in `config/agent/executor/capabilities.yaml` since Decision 117; the stub stays in DECISIONS.md (not archived) because `capabilities.yaml` and `scripts/checks/executor/validate_executor_boundary.py` still cite "Decision 44" by name.
3. **DCG-03 orphan-divergence guard.** `scripts/ops_portal/decisions.py`'s `backfill_decisions_from_md` gains `_assert_no_orphaned_current_rows()`: bulk-reads the `ops_decisions` current projection via the closed Decision-84-I-3 named-verb boundary (`reader.current_state('ops_decisions')`, no caller SQL, no new Lambda verb), diffs it against `scripts.decisions_md.decision_header_numbers()` (both files), and raises `RuntimeError` loudly (Decision 55) on any current-projection id with no matching header that is not in the checked-in allowlist-diff baseline, `config/agent/data_quality/decisions/orphan_baseline.yaml` (mirrors the sibling `fidelity_baseline.yaml` pattern). The baseline seeds exactly one entry, `dec-010` -- a pre-existing leaked "Test Decision" warehouse row with no header ever written in either file and zero citations, discovered during this Decision's implementation. It is allowlisted (Decision 55: a loud, cited allowlist entry, never a silently-dropped assertion) rather than physically deleted in this same change; its physical removal (a Decision-70-sanctioned exception) is tracked separately by rec-2814, out of this Decision's scope. The dec-010 discovery itself was surfaced to the operator as a hand-back, not filed as a recommendation, per this plan's default no-new-recommendations stance; rec-2814 is a deliberate, sanctioned exception to that default, filed at the operator's explicit direction at plan approval (the Step 6b confirmation) specifically to carry the deferred physical-removal follow-up forward.
4. **`decision-entry.yaml` doc-drift fix.** `size_governance.live_max_bytes` is corrected from a stale 400000 to 500000 -- the value `scripts/checks/decisions/validate_decisions_size.py` has actually enforced since Decision 145. This Decision does not itself lower the enforced ceiling; it only reconciles this file's documentation to the validator it describes.

**Rationale:**
This Decision is the structural mechanism Decision 145's own reversal conditions name ("when the DCG structural mechanism... lands and reclaims live headroom") -- it is authored as the owner of eventually triggering that reversal, not as the reversal itself: the compaction exercised here nets only a small live-byte reclaim (Decision 44's body shrank by roughly 2KB, largely offset by this entry), so the 500,000-byte ceiling stays exactly where Decision 145 set it. A future archival/compaction wave using this mechanism is what will actually reclaim enough headroom to revisit Decision 145's ceiling. Per Decision 86, rationale lives here and forward intent lives in the audit/contract, not in a new prose document -- `decision-entry.yaml` carries the mechanism's grammar and procedure, this Decision carries the why. The orphan baseline is an allowlist-diff, not a zero-assertion, because a zero-assertion would wedge on the pre-existing dec-010 orphan on the very first real backfill after this guard lands -- Decision 55 requires the divergence be loud and disposed (allowlisted with a reason, or fixed), never silently tolerated by weakening the guard itself.

**Reversal conditions:** Revisit if a future clause-parity merge tool is built (the audit explicitly recommends against one now; keep-separate verdicts show no redundancy pressure justifying it), or if the orphan baseline ever grows past a small, explainable handful (a growing baseline is a signal the guard's assumption -- that orphans are rare, disposed exceptions -- no longer holds and the write path itself needs an audit, not a bigger allowlist).

**Related:** Decision 145 (the stopgap ceiling raise this mechanism is the eventual structural reverser of), Decision 146 (the archival sibling -- compact-in-place is the branch for entries that cannot archive), Decision 134 (the size-governance ceilings and authoring grammar this extends), Decision 117 (Decision 44's superseder -- the capabilities.yaml SSOT this compaction points at), Decision 84 (the DuckLake closed-boundary reader the divergence guard reads through, and the ETL this compaction feeds), Decision 55 (loud-fail / no silent counters -- governs both the divergence guard's RuntimeError and the allowlist-not-silent-drop choice for dec-010), Decision 70 (the physical-deletion sanctioned-exception path dec-010's eventual cleanup, rec-2814, will use), Decision 147 (adjacent in-place-compaction precedent -- ROADMAP-PLATFORM.yaml terminal-content compaction in a single preserved file, 2026-07-22), audits/decision-consolidation-growth-f79d6b5.yaml (DCG-02/DCG-03, the findings this Decision closes).

---

## Decision 148: VF-01 hermetic VP-replay: replay at implement-time, not plan-time; hermetic-default restored (amends Decision 104, mirrors Decision 132) (Decided)

**Status:** Decided
**Date:** 2026-07-22
**Warehouse ID:** dec-148 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** The VF-01 hermetic VP-replay system (`validate_vp_replay`, T3.15 criterion c2) carried two traps that forced plan authors to mark feature-verification steps `hermetic: false`, defeating the independent re-execution guarantee VF-01 exists to provide. Trap A: `validate_vp_replay` replayed a diff-added/modified plan's hermetic pre-deploy steps directly against the plan-only-PR tree, where the two-PR plan/implement flow (Decision 76) means the implementation is absent by construction -- every hermetic feature-verification step failed regardless of whether the eventual implementation was correct. Trap B: `bin/venv-python` hard-failed with no fallback when `.venv` was absent, but `pr-validate` / `main-validate` / `terraform-validate` run venv-less by design (`requirements-fast.txt` into a hosted interpreter, avoiding ~3GB of torch/CUDA on disk) -- the AGENTS.md-mandated wrapper was thus incompatible with the CI jobs a hermetic step actually runs in.

**Decision:** Fix both traps at root cause rather than accommodating them:
1. **Replay timing (Trap A):** `validate_vp_replay` now resolves plans via the same two-leg model `validate_graduation_completeness` already uses (Decision 132): a **plan-only-PR leg** recognizes a diff-added/modified `PLAN-*.yaml` with no co-present `feat({slug})` commit and DEFERS replay with a printed reason -- no execution against an implementation-less tree. An **implement-PR leg** resolves `PLAN-{slug}.yaml` from `feat({slug})` commit subjects on `git log origin/main..HEAD` (covering both a dedicated implement PR and a co-present plan+code PR), loads the plan from disk, and replays its `phase: pre-deploy` + `hermetic: true` steps against the complete, implementation-bearing tree. Advisory-SKIPs (never fails) on unreachable `origin/main` or an absent plan, inheriting Decision 132's disclosed residual limitation B (a code PR that omits the `feat({slug})` commit prefix escapes replay). The plan-resolution helpers (`PLAN_PATH_RE`, `plan_paths_from_changed`, `load_plan`, `feat_commit_slugs`, `origin_main_reachable`) that were duplicated across `validate_vp_replay.py` and `validate_graduation_completeness.py` are consolidated into their sole home, `scripts/checks/_common.py` (Decision 104 sole-home discipline, extending its surface).
2. **`bin/venv-python` fallback (Trap B):** the wrapper keeps its OS-aware `.venv` resolution as the first choice; when no `.venv` exists, it falls back to the first PATH interpreter (`python3`/`python` on POSIX, `python`/`py` on Windows) that can import a sentinel dependency (`pydantic`, shipped by both `requirements.txt` and `requirements-fast.txt`). If no candidate qualifies, the wrapper stays fail-loud with its existing error message and a non-zero exit (Decision 55) -- it never silently substitutes a depless interpreter.
3. **Hermetic-default restored:** `.claude/skills/planning/SKILL.md`'s Hermetic authoring guidance now states `hermetic: true` is the correct default again for `pre-deploy` feature-verification VP steps, since they are replayed at implement time (not plan time) and `bin/venv-python` is now safe to invoke inside a hermetic step in every CI job, venv-less or not.

**Rationale:** Both traps shared a root cause -- a timing/environment mismatch between when/where a hermetic step was designed to run and when/where VF-01 actually executed it -- not a flaw in hermetic authoring itself. Mirroring Decision 132's already-proven two-leg model for Trap A (rather than inventing a second mechanism) keeps exactly one plan-resolution contract in the repo, now shared via `_common.py`. Fixing Trap B with a scoped, sentinel-probed fallback (rather than relaxing `bin/venv-python`'s fail-loud contract) preserves Decision 55's no-silent-substitution guarantee while making the wrapper actually compatible with the venv-less CI jobs it is invoked from today. Accommodating either trap by leaving `hermetic: false` as the practical default (the state before this Decision) would have permanently traded away VF-01's independent-re-execution guarantee for the most common case -- feature-verification steps -- which is the exact gap VF-01 was built to close.

**Reversal conditions:** If the two-PR plan/implement flow (Decision 76) is ever replaced by co-present plan+code PRs as the norm, the plan-only-PR defer branch becomes dead code and replay can revert to diff-added triggering. If CI ever adopts a universal `.venv` across all jobs, the `bin/venv-python` fallback becomes redundant (harmless to leave in place, but no longer load-bearing).

**Related:** Decision 132 (the two-leg replay/enforcement model this mirrors), Decision 104 (`_common.py` sole-home discipline, extended here), Decision 76 (the two-PR plan/implement flow whose absence-of-implementation this fix accounts for), Decision 73 (fast-tier budget guards, preserved unchanged), Decision 55 (fail-loud, no silent substitution -- governs both the replay advisory-SKIPs and the wrapper fallback).

[Amendment 2026-08-17: the commit-subject resolution mechanism this entry describes (`feat({slug})` commit subjects on `git log origin/main..HEAD`) is replaced by an explicit, schema-validated `implementation_declared` boolean on `PlanDocument`, resolved content-keyed via `scripts.checks._common.resolve_declared_plans` (PLAN-plan-resolution-content-keyed, provenance: explicit operator direction given during that plan's authoring). The two-leg model and advisory-SKIP shape this entry describes are unchanged; only the resolution signal moves from commit-message grammar to diff-carried plan content.]

---

## Decision 147: Respond to Decision 114 reversal trigger by compacting ROADMAP-PLATFORM.yaml terminal content in place (single file preserved) (Decided)

**Status:** Decided
**Date:** 2026-07-22
**Warehouse ID:** dec-147 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** docs/ROADMAP-PLATFORM.yaml reached 9,996 of the 10,000-line ceiling (`_ROADMAP_MAX_LINES`, enforced in both the `--pre` and full presubmit tiers per `validate_platform_roadmap`), firing the reversal trigger Decision 114 wrote for exactly this event ("when the file breaches the 10,000-line ceiling again, or when /plan-time load cost becomes prohibitive"). Roughly 52% of the file (~5,200 of its ~9,200 non-preamble lines) was terminal/dead content: the 26 ratified/superseded `candidate_decisions` carried `detail`/`realization_evidence` prose that duplicates DECISIONS.md verbatim (Decision 86 already assigns rationale storage to DECISIONS.md, not the roadmap), and the 93 completed/reserved `tier_items` (89 complete + 4 reserved) carried `progress_note`/`note`/`decomposition_hints` narrating work already finished, plus multi-line `intent` prose and stale `files_in_scope` file lists no longer read by anything once an item is done.

**Decision:** Compact the roadmap's terminal/dead content in place, preserving the single agent-first file (Decision 110) -- this is Path A from the reversal-trigger response set, not Path C (per-tier split, which Decision 110/114 already rejected as the N-files-to-reassemble anti-pattern) and not Path D (a bare ceiling raise, the Decision 128 silent-trade anti-pattern).
1. **Candidate decisions (26 ratified/superseded):** drop `detail`/`realization_evidence` prose entirely (or, where a guard reads a literal phrase inside it -- CD.7's "fully superseded by CD.28" marker that `validate_candidate_decision_supersession` depends on -- retain a single compact line carrying that phrase). Keep `id`, `title`, `gates`, `state`, `ratified_as`, `filed_via`, and every supersession machine field (`narrowly_supersedes`, `supersedes_*`, `retires_intents`, `demotes_intents`, etc.) untouched. All 14 pending CDs are left byte-identical.
2. **Tier items (93 complete/reserved):** drop `progress_note`, `note`, and `decomposition_hints` entirely, and collapse multi-line `intent` prose to one descriptive line. Additionally -- discovered necessary mid-implementation once the above two moves alone landed at 7,709 lines, still over the 7,600-line target this Decision's own acceptance bar sets -- empty the `files_in_scope` list on `status: complete` items (nothing in `scripts/` reads `files_in_scope` programmatically; it is pure post-hoc provenance, and provenance for finished work survives in git history same as everything else this Decision removes). `id`, `tier`, `name`, `status`, `depends_on`, `completed_at`, `met_by`, and the entire `exit_criteria` block are kept byte-for-byte on every touched item; no `- id:` line was added, removed, or reordered, and no `not_started`/`in_progress`/`deferred_post_mvp` item was touched.
3. **Result:** 9,996 -> 7,329 lines (2,667 removed), restoring >= 2,600 lines of headroom below the 10,000-line ceiling. Schema validation, the platform-roadmap criteria-integrity guard, the candidate-decision ratification and supersession guards, and an eligibility-invariance differential (comparing `compute_state_dict`'s `next_eligible`/`in_progress`/`blocked`/`blocked_on_cd`/`ratifiable_cds`/`deferred_post_mvp` projections between origin/main's roadmap and the trimmed tree) all confirm the trim changed no forward-planning behavior.
4. **Durable norm:** ratified candidate_decisions and completed/reserved tier_items are stored in compact form going forward -- their narrative lives in DECISIONS.md (already true per Decision 86) or in git history, not in the roadmap. A follow-on recommendation (rec-2781, filed at plan time) tracks building a mechanical anti-regrowth guard so this compaction does not silently erode on the next edit to a terminal item.

**Rationale:** Decision 110 already settled that ROADMAP-PLATFORM.yaml stays a single agent-first file rather than splitting into per-tier files -- reopening that question at every ceiling breach would be a standing tax on every future revisit. Decision 128 already settled that a raised limit is a deliberate, cited, reversal-conditioned exception, not the default response to hitting a ceiling -- a bare raise here would silently trade away the load-cost property the ceiling protects. In-place compaction is the only response that relieves the ceiling without reopening either settled question: the content removed is genuinely dead (a ratified CD's rationale is provably duplicated in DECISIONS.md; a completed item's progress narrative and file list serve no forward-planning read once the item is done), and every field the eligibility computation or the referential guards (ratification, supersession, criteria-integrity) read is left untouched or verified invariant.

**Reversal conditions:** If the file breaches 10,000 lines again after this compaction, escalate rather than repeating an ad hoc trim -- either lifecycle archival (a separate ROADMAP-PLATFORM-ARCHIVE.yaml holding fully-retired items behind dependency-resolving stubs, mirroring the DECISIONS.md/DECISIONS_ARCHIVE.md split) or a consciously-cited, temporary, reversal-conditioned ceiling raise (mirroring this Decision 145 precedent for DECISIONS.md's own byte ceiling). A second ad hoc trim on top of this one is itself a signal that the structural fix is overdue.

**Related:** Decision 114 (the reversal trigger this Decision responds to), Decision 110 (single-file agent-first structure, preserved), Decision 105 (candidate-decision ratification guard, whose read fields are preserved verbatim), Decision 136 (supersession-adjacent guard context), Decision 93, Decision 108 (adopts the roadmap as canonical platform-sequencing source), Decision 86 (rationale lives in DECISIONS.md, the premise this compaction acts on), Decision 84 (portal/warehouse sync for this entry), Decision 128 (anti-silent-raise posture, the rejected Path D), Decision 145 (temporary-ceiling-raise precedent named as a reversal option).

---

## Decision 146: DECISIONS.md is the canonical decision corpus, not an open-decisions-only file; fully-superseded entries move to the archive (retitles the stale "# Open Decisions" H1; reconciles the drifted archival policy to Decision-84-era reality) (Decided)

**Status:** Decided
**Date:** 2026-07-21
**Warehouse ID:** dec-146 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** docs/DECISIONS.md opened with the H1 "# Open Decisions" and a subtitle framing it as decisions "that need to be made" -- an open-decisions-only framing that predated Decision 84. Two facts made it stale: (1) Decision 84 made this file the SOLE ETL source for the `ops_decisions` warehouse table, so it is the canonical corpus of every ratified decision, not a scratchpad of pending ones; (2) the archival policy PROJECT_CONTEXT.md once credited to a `strategic_review` enforcer never had a mechanical enforcer -- the only surviving open-decisions signal is scripts/session/preflight.py's advisory counter, and the strategic_review.prompt.md the policy named was deleted (T-1.13). Audit finding DPI-04 (audits/decision-log-premise-integrity-8fb581e.yaml) flagged the H1/subtitle drift and the enforcer-that-does-not-exist. (PROJECT_CONTEXT.md's policy text was independently reconciled to the Decision-134 deterministic-guard framing before this Decision.)

**Decision:** docs/DECISIONS.md is the canonical decision corpus -- the sole ETL source for `ops_decisions` (Decision 84) -- holding ratified decisions regardless of lifecycle status. The H1 is retitled "# Decisions". Fully-superseded entries move to docs/DECISIONS_ARCHIVE.md with a "(Superseded by Decision NN)" header suffix per the archive's existing convention. "Fully superseded" is a per-entry test: a repo-wide search for the decision number returns only its own entry plus already-annotated / superseded mentions. An entry still cited as a LIVE constraint stays in the corpus -- so superseded-but-still-cited entries (e.g. Decision 44 -> 117 cited by live enforcement code, Decision 58 -> 76 cited by ROADMAP-PLATFORM.yaml, Decision 37 -> 116) remain until their citations retire, and archival proceeds in bounded, operator-disposed waves rather than one sweep. Because scripts/decisions_md.py parses BOTH files (`_DECISIONS_MD_PATHS`), an archive move is warehouse-safe: the entry keeps its number-keyed `dec-NNN` identity, the backfill re-upserts it unchanged, and the move only relocates bytes out of the decision-scout hot-read path. Archival is operator-disposed (the audit recommends candidates; the operator confirms each move), NOT mechanically enforced -- there is no "keeps-only-open" guard and none is created here. Live-file size pressure is governed by validate_decisions_size (Decision 134; ceiling raised to 500,000 by the Decision 145 stopgap), whose named relief valves are exactly this archival and superseded-body compaction.

**Rationale:** The "open decisions" framing credited an enforcer that does not exist and contradicted the post-Decision-84 reality that this file IS the warehouse's decision of record. Recording the correction as a numbered Decision (not prose in PROJECT_CONTEXT.md) follows Decision 86: rationale lives in a numbered Decision, collocated with the corpus it governs. Archival stays a judgment-based, operator-gated disposition rather than an automated sweep because "fully superseded" is not mechanically decidable -- automated duplicate-number detection and any eligibility enforcer are separate, unbuilt scope (audit DPI-06).

**Revisit condition:** if a mechanical archival-eligibility enforcer or duplicate-number guard (DPI-06) is ever built, revisit the "operator-disposed, not mechanically enforced" clause.

**Related:** Decision 84 (sole ops_decisions ETL source), Decision 86 (rationale -> numbered Decision), Decision 105 (ratification guard resolves headers across both files), Decision 134 (size governance + authoring grammar), Decision 145 (byte-ceiling stopgap + archival as the named relief valve), audit DPI-04 (audits/decision-log-premise-integrity-8fb581e.yaml).

[Amendment 2026-08-07: Decision 160 lists this entry among its amends targets (retiring the live-byte ceiling this entry's Rationale cites); see Decision 160 for the citation. This entry's own Decision text is unchanged by that title-level relation.]

---

## Decision 145: Arbitrary stopgap raise of the DECISIONS.md live byte ceiling (400,000 -> 500,000) pending the structural growth-direction mechanism (amends Decision 134 clause 2) (Decided)

**Status:** Decided
**Date:** 2026-07-21
**Warehouse ID:** dec-145 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
docs/DECISIONS.md sits at 398,438 / 400,000 bytes (the Decision 134 clause 2 live-byte ceiling), so
the two forward-direction Decisions this same wave adds (Decision 144's allow-list-inversion anchor,
plus this one) cannot land as pure additions under the current ceiling. The STRUCTURAL fix -- a
number-preserving compact-to-stub lifecycle, a significance gate on inflow, and a near-term relief
sweep -- is designed but UNBUILT and UNOWNED: audits/decision-consolidation-growth-f79d6b5.yaml
findings DCG-01 (near-term relief sweep), DCG-02 (compact-to-stub + archival lifecycle), and DCG-05
(explicit significance gate on inflow) all carry dedup_hit_count 0. Decision 134 clause 2's own
doctrine, and decision-entry.yaml, warn that raising the ceiling silently trades away the
read-cost/portability guard the decision-scout subagent depends on (it reads the whole live file
every /plan, uncached, within a 200k-token window) -- so a raise must be a conscious, cited,
temporary act, never a frictionless constant edit.

**Decision:**
1. **Raise `_DECISIONS_LIVE_MAX_BYTES`** in `scripts/checks/decisions/validate_decisions_size.py`
   from 400,000 to 500,000. This is an ARBITRARY, TEMPORARY stopgap sized for headroom, not a
   re-derived sizing exercise. The 500,000-byte ceiling still fits the decision-scout's mandatory
   whole-live-file read comfortably inside the 200k-token context window (~500 KB is ~125k tokens,
   under 200k), so Decision 134's bridge-guard protected-consumer assumption still holds.
   `_DECISIONS_LIVE_MAX_H2` (120) and `_DECISIONS_COMBINED_MAX_BYTES` (700,000) are UNCHANGED.
2. **Amends Decision 134 clause 2:** the live-byte ceiling value is now 500,000 (was 400,000).
   Decision 134 clause 2 otherwise STANDS unmodified -- the dual guard (byte ceiling + header-count
   ceiling), the 700,000-byte combined backstop, and the relief-valve naming (archival per DPI-04;
   compaction of superseded bodies to pointer stubs) are all retained as-is. No edit is made to the
   Decision 134 body text itself (the forward-direction amendment convention of Decision 126/143:
   amendments are stated only in the amending Decision).
3. **This is a STOPGAP, NOT the fix.** The structural/architectural remedy for unbounded
   decision-log growth is authored and unactioned in
   `audits/decision-consolidation-growth-f79d6b5.yaml`: DCG-01 (a human-disposed near-term relief
   sweep restoring >= 20 KB of headroom via archival/compaction), DCG-02 (the number-preserving
   compact-to-stub + archival lifecycle: eligibility criterion, stub grammar, terminal-SCD2
   semantics), and DCG-05 (an explicit significance gate shaping inflow so not every session-scale
   decision becomes a permanent live header). This raise buys headroom only until that mechanism is
   designed, built, and owned -- it does not substitute for it, and per the Decision 128 /
   decision-entry.yaml anti-pattern (a raise silently trades away a portability/read-cost guard) it
   must never become the standing response to future pressure on this ceiling.
4. **Provenance recorded inline.** The raised constant in `validate_decisions_size.py` carries an
   inline comment citing this Decision, and the module docstring / FAIL-message Decision citation is
   updated to name this amendment. No new raise-marker guard is added -- unlike
   `config/sloc_budgets.yaml`'s `# raise-approved: dec-NNN` convention enforced by
   `validate_sloc_budget_raises`, `validate_decisions_size` carries no raise-approval mechanism of
   its own, so the durable record of this raise is this Decision plus the inline comment plus git
   history.

**Reversal conditions:** Retire or lower this ceiling when the DCG structural mechanism (the
compaction lifecycle + significance gate) lands and reclaims live headroom, so the ceiling can
return toward 400,000 or the guard itself can retire per Decision 134's own reversal trigger; or
when the decision-scout moves to a warehouse/portal read (Decision 134's protected consumer is
gone); or when a 500,000-byte read no longer comfortably fits the operating model's context window.
This is re-decided, never silently renewed: a SECOND stopgap raise on top of this one is itself a
signal that the structural fix is overdue, not a routine act to repeat.

**Rationale:**
The alternative relief valve -- compacting superseded decision bodies to stubs in this same PR --
was rejected for this anchor wave: victim-selection (which bodies to compact) is a DPI-04-class
human disposition with a body-citation hazard (a mis-compacted body that some other Decision or
tier_item cites by content becomes wrong-but-still-trusted), and bundling that judgment-heavy edit
into the governance-anchor PR couples two unrelated concerns. A conscious, cited, temporary ceiling
raise is the lower-risk stopgap for this PR, provided it is recorded as its own
reversal-conditioned Decision naming both the structural fix and the audit that owns it -- which is
what this Decision does. Per Decision 86, rationale lives here and forward intent lives in the
audit/tier_items, not in a new prose document; per Decision 128 / decision-entry.yaml, the raise is
loud and Decision-cited, never silent.

**Related:** Decision 134 (clause 2 amended -- the ceiling this raises; its dual guard, header and
combined ceilings, and relief-valve doctrine are otherwise retained), Decision 128 (the
raise-is-a-silent-trade anti-pattern this Decision consciously avoids by being loud and cited rather
than frictionless), Decision 114 (the size-ceiling + reversal-conditions precedent Decision 134
itself mirrors), Decision 126 (the forward-direction amendment convention -- amend in the amending
Decision, never the amended Decision's body), Decision 86 (rationale routes here; no new standing
prose doc), Decision 84 (numbering authority + backfill ETL -- authored here, backfilled to
`ops_decisions` post-merge, never written directly), `audits/decision-consolidation-growth-f79d6b5.yaml`
(DCG-01/DCG-02/DCG-05 -- the structural fix this stopgap tides over until built).

---

## Decision 144: Allow-list inversion: broad-but-bounded deployer under the mandatory permissions boundary as the target Terraform deploy/IAM model (forward-direction; amends Decision 98 point 1 and Decision 92 point 5; extends Decision 129 from reads to writes) (Decided)

**Status:** Decided
**Date:** 2026-07-21
**Warehouse ID:** dec-144 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`github_ci_apply`'s WRITE authority is an enumerated per-resource allow-list that structurally lags
the `terraform/personal` module: a guard-PASS change can still die `AccessDenied` at apply because
the resource it touches was never individually added to the allow-list, latching the convergence
record red on a change the guard already approved. Separately, the IAM-write authority budget
(Decision 92 point 5) stops at branch/pr role policy updates and treats every new role as
boundary-less by default, so a gated-apply for a new role can be human-approved and still fail
AccessDenied at the AWS-IAM layer. Decision 129 already fixed exactly this shape for the READ axis
-- an account-scoped `agent-platform-*` prefix ended a class that had recurred 15+ times in six
weeks -- and deliberately left the WRITE axis enumerated for a later wave. The audit
`audits/terraform-deploy-redesign-b67955b.yaml` traced both symptoms to one underlying cause, a
multiple-compounding allow-list-IAM family (its highest-leverage finding, DEP-02): the binding
constraint is the AWS-side identity policy, not the guard's plan-content budget, and enumeration
cannot keep pace with a growing module. The target model that fixes this was never recorded
anywhere as a single citable decision, so this Decision records it now, before it is realized,
following the Decision 126 forward-direction precedent.

**Decision:**
1. **Target model.** Invert `github_ci_apply`'s authority from "enumerate what it may write" to a
   broad-but-bounded deployer operating under an existing mandatory permissions boundary
   (`agent-platform-github-ci-apply-boundary`): broad DataPlaneAllow wildcards on the managed
   resource types, paired with `DenyIAMEscalation` (conditioned on boundary propagation),
   `DenyBoundaryRemoval`, and `DenyBoundaryPolicyModification` -- a verified AWS-native SCP
   substitute for an account that has no AWS Organizations layer yet. The deterministic guard and
   the authority budget continue to carry danger classification in front of this identity; the full
   CD.35 control theory (saved-plan no-TOCTOU, fail-closed guard, the server-side convergence
   anchor, the Environment-gates-execution model, the bootstrap fixed point -- Decisions
   77/92/119/120/126) is KEPT VERBATIM. This target is REALIZED by tier_item T2.48, not by this
   Decision -- this Decision records the target and the rationale only.
2. **Extends Decision 129 from reads to writes.** The same per-service, account-scoped
   `agent-platform-*` prefix pattern Decision 129 applied to the read axis now applies to the WRITE
   axis: `logs:CreateLogGroup`/`PutRetentionPolicy` on `/aws/lambda/agent-platform-*`, the Lambda
   lifecycle verbs on `function:agent-platform-*`, `cloudwatch:PutMetricAlarm`/`DeleteAlarms` on the
   `agent-platform-*`/`ducklake-*` alarm namespaces, EventBridge writes on `rule/agent-platform-*`,
   and `iam:TagRole`/`UpdateRoleDescription` on `role/agent-platform-*`.
   `validate_ci_refresh_read_coverage` is extended to also assert WRITE coverage per managed
   resource type. Decision 129's reversal trigger (re-narrow on a non-`agent-platform-*` resource,
   or on any over-grant incident) applies to the write axis exactly as it does to the read axis.
3. **Mandatory boundary, with one explicit exclusion.** The boundary becomes MANDATORY on every
   `agent-platform-*` CI and execution role and on `PlatformDev`. It EXCLUDES `PlatformAdmin`:
   PlatformAdmin is the control identity that must remain able to amend the boundary itself, and
   attaching `DenyBoundaryPolicyModification` to it would wedge the one identity capable of fixing
   the boundary if it ever needs to change. PlatformAdmin's own reachability is hardened separately,
   by DEP-13 (severing the ExternalId-in-state escalation path) rather than by boundary attachment
   -- Decision 113's two-principal PlatformDev/PlatformAdmin split is unchanged by this Decision.
4. **Amends Decision 98 point 1.** Decision 98 point 1 currently requires that new peer CI roles be
   admin-provisioned in `terraform/personal/` via `agent_platform_admin` -- NOT minted by the
   pipeline. This Decision amends that: the pipeline (`github_ci_apply`) MAY mint boundary-carrying
   `agent-platform-*` roles via the gated `tf-gated-apply` Environment path, riding the Decision 94
   trust of `environment:tf-gated-apply`. Because a new role now declares the mandatory boundary in
   its own HCL, `iam:CreateRole` satisfies `IAMRoleCreateBounded`'s boundary-propagation condition
   and the gated apply can succeed instead of AccessDenying. Admin-create via `agent_platform_admin`
   REMAINS the path for non-prefixed roles and for bootstrap-tier roles (`terraform/bootstrap/**`
   owns its own state, admin-only) -- Decision 98 points 2-4 are unchanged. Decision 143's
   human-gate durability property is PRESERVED, not violated: role CREATE still routes through the
   Environment's required-reviewer gate, a materially higher bar than an in-handler edit (Decision
   143 clause 1 stands); only its exec-role-CREATE MECHANISM text (admin-create as the sole path) is
   re-grounded to admin-create-or-gated-Environment-executable for boundary-carrying
   `agent-platform-*` roles, effective when T2.48 lands.
5. **Amends Decision 92 point 5 (authority-budget v2 direction).** Effective when T2.48's AWS-side
   widening lands: create+update of inline policies/attachments on ANY boundary-carrying
   `agent-platform-*` role becomes in-budget (today this is enumerated to exactly two named roles,
   `agent-platform-github-ci-branch` and `agent-platform-github-ci-pr`). Role CREATE stays GATED --
   it still routes to the `tf-gated-apply` Environment -- but becomes EXECUTABLE by the gated job
   rather than AccessDenying. `IAMRoleWriteBounded`/`IAMRoleCreateBounded` widen their Resource match
   to `role/agent-platform-*`, keeping the boundary-propagation condition, the self-ARN exclusion,
   and all three boundary self-protection denies intact. The ratchet model itself -- autonomy earned
   and revocable per change-class, budget amendments via the bootstrap tier only,
   `validate_authority_budget`'s drift gate -- is UNCHANGED and now simply governs a wider set of
   classes. This Decision records the target and the rationale ONLY: the actual guard-classification
   and budget-rule change lands in `environment-taxonomy.md` and `authority_budget.json` at T2.48
   (Decision 92 point 5 remains the sole SoT for the rule itself; this Decision's body is not a
   competing enforcement surface, per Decision 86's no-drift principle).
6. **Retains Decisions 77 and 101 untouched.** Decision 77 (single-account-until-`live_full`;
   sandbox auto-apply behind the deterministic guard, itself the scoping of Decision 35's "apply is
   never automatic") is not re-opened here -- only the authority model INSIDE the pipeline changes;
   Decision 77's `live_full` trigger remains the named condition for the audit's conditional Phase 4
   (AWS Organizations + org CloudTrail + SCP conversion), which is out of scope for this Decision.
   Decision 101 (the public-content / confidential-data boundary) is likewise retained untouched:
   this Decision names roles by logical name and resources by prefix throughout, with no account
   IDs, ARNs, or ExternalId values anywhere in its text.
7. **Sequencing.** Seven new tier_items carry the remaining audit work forward: T2.44 (Phase-0
   hardening, DEP-04/DEP-09/DEP-13), T2.45 (guard resource-based-policy classification, DEP-06),
   T2.46 (apply-chain consolidation + saved-plan digest integrity, DEP-07/DEP-08), T2.47
   (recovery-path unification + routed-pending observability, DEP-10/DEP-11), T2.48 (this Decision's
   Phase-2 inversion, DEP-01/DEP-02), T2.49 (CI/deploy role consolidation, DEP-12, `depends_on:
   [T2.48]`), and T2.50 (protected amendment channel, DEP-05, sequenced last). Audit finding DEP-03
   is already owned by the existing tier_item T2.42 (its c1/c3 criteria are DEP-03's remedy) and
   gets no new tier_item. T2.48 additionally `depends_on: [T2.45]`, so the guard classifies
   resource-based policies before the write surface broadens onto them.

**Reversal conditions:** Inherits Decision 129's re-narrow trigger (re-narrow the prefix grant if
the account ever hosts a non-`agent-platform-*` resource of a covered type, or on any incident
showing an over-grant). If the bespoke pipeline this Decision extends ever proves unmaintainable at
scale, re-evaluate against a managed reconciler per Decision 126's own reversal condition, scoped
against the Decision 101 boundary. The Phase-4 multi-account posture supersedes this single-account
boundary substitute only when Decision 77's `live_full` trigger fires -- not before.

**Rationale:**
Decision 129 already proved this pattern works for reads, ending a class that had recurred 15+
times; the deny-list substrate this Decision proposes for writes -- a permissions boundary plus a
boundary-propagation condition plus three self-protection denies -- is the same kind of verified
AWS-native SCP substitute Decision 100/75 already commits this platform to preferring over vendored
tooling, so this redesign is an INVERSION of material already on hand, not a greenfield build. The
boundary is what makes "broad" safe: a broad deployer cannot escalate its own privileges
(`DenyIAMEscalation`) and cannot detach or weaken its own cap
(`DenyBoundaryRemoval`/`DenyBoundaryPolicyModification`). Recording the target model before it is
realized follows the Decision 126 precedent exactly (record once, in one citable place, so the
follow-on tier_items have a fixed point instead of each landing its own ad hoc framing); per
Decision 86, rationale lives here and forward intent lives in the tier_items, with no new standing
prose document. This is a forward-direction Decision, not a Decision-105 candidate-CD ratification,
because the model it records is not realized end-to-end yet (the Decision 87 precedent: the
CD-to-Decision ratification lane is for already-realized CDs). Authored with a Fable design-consult
in the overseer run that produced this PR.

**Related:** Decision 129 (per-service prefix pattern extended from reads to writes), Decision 98
(point 1 amended, above), Decision 92 (point 5 amended, above; the ratchet model retained;
`environment-taxonomy.md` stays the sole SoT for the rule itself), Decision 77 (retained untouched;
its `live_full` trigger is the named condition for the audit's Phase 4, not re-opened here),
Decision 101 (retained untouched; this Decision's public-content boundary compliance), Decision 126
(the record-the-model-before-realization precedent this Decision follows; the CD.35 control theory
it keeps verbatim), Decision 143 (worst-reachable-verb identity scoping -- complementary: the
mandatory boundary now also covers exec roles, and role-create staying gated-via-Environment
preserves 143's "materially higher bar than an in-handler edit" property; 143's admin-create-only
mechanism text is re-grounded when T2.48 lands), Decision 94 (the `github_ci_apply` trust of
`environment:tf-gated-apply` that the gated role-create path rides), Decision 113 (the static-key
two-principal PlatformDev/PlatformAdmin split -- the boundary attaches to PlatformDev and explicitly
excludes PlatformAdmin; DEP-13 severs PlatformAdmin's separate escalation path), Decision 100/75
(managed-service-native primitives -- the boundary is this Decision's AWS-native SCP substitute),
Decision 105 (the CD-ratification lane deliberately NOT used here; see Rationale), Decision 35
("apply is never automatic" -- already scoped by Decision 77 and not re-opened by this Decision),
Decision 83 (non-wedging branch protection; DEP-05/T2.50 retains the admin-bypass actor), Decision
55/72 (RCA-first, forward-fix-the-generator -- the enumerated allow-list model this Decision retires
fed its own recurring change-stream), Decision 84 (authored here, backfilled to `ops_decisions`
post-merge, never written directly).

---

## Decision 143: Privileged-verb Lambda decomposition -- scope identities by worst reachable verb; enforce the boundary in a primitive outside the agent merge loop (amends Decision 81 cl.1) (Decided)

**Status:** Decided
**Date:** 2026-07-20
**Warehouse ID:** dec-143 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
T2.18's `ducklake_maintenance` Lambda dispatched both the non-destructive smoke cadences
(merge/gc/hot_merge/breaker_probe -- safe to run against the disposable smoke catalog) and the
production-destructive/operational verbs (catalog_reinit, restore_drill, reconcile_columns,
catalog_stats, clone_catalog, merge_ops) from one function behind one IAM execution role. c9 (an
autonomous CD-invoked post-deploy smoke gate for the maintenance pipeline) required granting SOME
CI identity `lambda:InvokeFunction` on this Lambda -- but `lambda:InvokeFunction` authorizes the
whole function, not a single dispatched action, so granting invoke to the always-on public-repo CI
identity (github_ci_branch) would also grant it reachability to catalog_reinit/restore_drill/
clone_catalog against the production DuckLake catalog (recs/decisions/operational memory -- factory
state, production-grade even pre-MVP). The DuckLake catalog's exposure on a public repo makes this
confused-deputy-adjacent: an injection into the CI identity's context (a malicious PR body, a
compromised dependency) could otherwise reach a production-destructive verb.

**Decision:**
1. **Scope every identity by the worst verb it can reach**, and enforce that scope in a primitive
   OUTSIDE the agent's merge loop -- not an in-handler guard the agent-authored codebase could edit
   out, but a resource-shape boundary (a separate Lambda + IAM execution role) that AWS IAM itself
   enforces. `lambda:InvokeFunction` is per-function, not per-action, so the only way to give a CI
   identity narrower reach than "everything this Lambda can do" is to put the narrower verb set on
   its own function.
2. **Realized by splitting** `ducklake_maintenance` into two runtime artifacts:
   - `ducklake_maintenance_smoke` (new): CI-invokable, dispatch table EXACTLY {merge, gc,
     breaker_probe, hot_merge}, env-pinned to the disposable smoke catalog (never reads
     data_path/meta_schema from the event), smoke-prefix-scoped IAM execution role (no production
     S3 access). `github_ci_branch` holds `lambda:InvokeFunction`/`InvokeFunctionUrl`/
     `GetFunctionUrlConfig` on this function's ARN only (`MaintenanceSmokeInvokeCI`).
   - `ducklake_maintenance` (retained, admin-gated): keeps the production-destructive and
     operational verbs (catalog_reinit, restore_drill, reconcile_columns, catalog_stats,
     clone_catalog) plus the scheduled `merge_ops` cadence. `github_ci_branch` is NEVER granted
     invoke on this function's ARN -- admin-invoked only (`aws lambda invoke` under
     `agent_platform_admin`), matching its pre-split posture.
3. **Reversible-and-disposable verbs are agent-autonomous by default; irreversible or
   factory-state verbs get their own resource** so IAM -- not handler code -- is the boundary that
   says no. This is the general rule this split instantiates; it generalizes beyond DuckLake
   maintenance to any future Lambda that mixes a CI-safe verb subset with a production-destructive
   one.
4. **Amends Decision 81 clause 1**: the CD.33 runtime-artifact enumeration (writer / reader /
   maintenance) becomes FOUR artifacts (writer / reader / maintenance / maintenance_smoke).
   `reserved_concurrent_executions=1` (singleton) is preserved on BOTH maintenance functions -- each
   independently must not run concurrently with itself; this is not a shared concurrency budget
   between them.
5. **Closes T2.18 c9** (autonomous post-deploy smoke gate): the four maintenance smoke gates now
   run unattended in the governed CD channel (`.github/workflows/deploy-ducklake-lambdas.yml`)
   under `github_ci_branch`'s scoped invoke grant, rather than requiring an `agent_platform_admin`
   session to invoke them by hand.

**Rationale:**
(Fable frontier-architecture consult, cited in `docs/plans/PLAN-ducklake-maintenance-smoke-split.yaml`
context.) Two alternatives were considered and rejected: (A) keep c9 human-gated (an operator
invokes the smoke gates manually post-deploy) -- rejected because it re-introduces a
human-in-the-critical-path dependency the self-improving loop's North Star is designed to
eliminate. (B-i) grant `github_ci_branch` invoke on the existing multi-tool `ducklake_maintenance`
function -- rejected because it grants CI reachability to catalog_reinit/restore_drill/
clone_catalog against production, the exact confused-deputy exposure this Decision closes. (B-ii,
adopted) split the function so the CI-safe verb subset is a materially different, narrower-privileged
resource. The resource split is more durable than an in-handler action allowlist: a handler-level
guard lives in the same agent-editable codebase as the verbs it's supposed to gate, so a future edit
(or an injected instruction) could silently widen it; a separate Lambda + IAM role requires an
out-of-band Terraform apply (admin-create OR -- for a boundary-carrying `agent-platform-*` role --
gated-Environment-executable through the required-reviewer `tf-gated-apply` Environment; the exec-role
CREATE mechanism was re-grounded by Decision 144 / T2.48 from "admin-create only / human-gated per
T2.25/Decision 92 pt.5" to "admin-create OR gated-Environment-executable for boundary-carrying
agent-platform-* roles") to widen, which is a materially higher bar than an in-handler edit -- role
CREATE still routes through the required-reviewer Environment (the identity-scoping RULE in clause 1
and this higher-bar property are preserved verbatim).

**Reversal conditions:** At MVP, when the SIT/PROD accounts stand up (Decision 77's platform
promotion train), the production-destructive `ducklake_maintenance` function moves behind a
second-approver gate as part of that promotion -- the split performed here is a durable artifact
this future state builds on, not throwaway scaffolding. If AWS Lambda ever ships per-action (not
per-function) IAM authorization, the resource split may be revisited (a single function could
re-consolidate behind per-action IAM conditions), but the identity-scoping RULE (clause 1 above)
stands regardless of the enforcement primitive.

**Related:** Decision 81 (CD.33 runtime architecture; clause 1 amended here), Decision 79 (per-Lambda
packaging manifests + deploy gating -- the manifest/build/deploy wiring this split follows),
Decision 92 + Decision 98 (IAM authority-budget / admin-create precedent -- the new exec role's
CREATE is out-of-budget and requires `agent_platform_admin`), Decision 129 (data-plane resource-axis
broadening -- the smoke function's refresh-read coverage rides the existing `agent-platform-*`
prefix with no new grant), Decision 125 + Decision 126 (governed code-deploy channel + code/infra
decoupling -- the smoke function's code deploys via the same `deploy-ducklake-lambdas.yml` channel),
Decision 55 (loud-failure / no-workaround doctrine -- the split enforces the boundary structurally
rather than papering over it with a guard).

---

## Decision 142: CI-RCA fingerprint v2 (cause-anchored) + status-aware chain lifecycle replaces the CIRCA-03(a) step-name key and the rec-2644 close-then-recur revive path (Decided)

**Status:** Decided
**Date:** 2026-07-17
**Warehouse ID:** dec-142 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The CIRCA-03(a) grouping fingerprint (`scripts/ci_rca/evidence.py:65` `_compute_fingerprint`) keyed
on `(workflow_slug, failed_check, failure_category)` -- `failed_check` is the CI STEP name (e.g.
"Unit tests + coverage"), identical for ANY pytest failure in that step. Two DISTINCT failing tests
collided onto the same fingerprint, so an unrelated `session_preflight` failure was masked into an
already-fixed rec (rec-2710) instead of filing its own record. Separately, the write-time backstop's
close-then-recur fix (rec-2644: `find_recent_ci_rca_rec_by_fingerprint` + `reopen_ci_rca_rec` in
`scripts/ops_portal/ci_rca_runtime.py`) flipped a CLOSED rec back to `open` on any fingerprint match
within a 14-day window -- discarding the closed rec's fix-proof with no verification that the new
failure was actually the SAME unfixed cause recurring, rather than a genuine regression or an
unrelated new failure sharing the coarse key.

**Decision:**
1. **Fingerprint v2** (`scripts/ci_rca/fingerprint.py`, new): `compute_fingerprint_v2(workflow_slug,
   failure_category, error_signature) -> sha256` with a literal `"v2"` salt folded into the hashed
   payload -- guarantees disjointness from any v1 fingerprint for the same logical failure, so NO
   warehouse migration is required (the two keyspaces never collide). `error_signature` is
   `"{exception_type}::{deepest_in_app_frame}::{normalized_message_head}"`, where
   `deepest_in_app_frame` is `"{module}::{function}"` (no line number) -- the traceback frame,
   walked bottom-up, that is the first one NOT in site-packages/pytest-internals/conftest.py.
   junit-parsed (`error_signature_from_junit`, grouping failing testcases by identical raw tuple --
   the anti-masking property AND cause-grouping fall out of this single walk: a plain assertion
   failure's deepest in-app frame is the test function itself, so distinct tests never collide; an
   error raised inside a shared `src/` helper resolves to that helper, so distinct tests sharing one
   cause collapse together). Special cases: a pytest collection error keys on the failing MODULE
   PATH (`failure_category=collection_error`, a taxonomy category this Decision adds to
   `config/ci_rca_taxonomy.yaml` since none existed for a genuine collection failure, distinct from
   the pre-existing `test_collection_empty` vacuous-pass category); a non-pytest failure (including a
   terraform-apply-sandbox apply failure, Decision 92) uses `error_signature_from_log_tail(tool,
   normalized-line)`; more than ~5 distinct new signatures in one run collapse to a single run-level
   record (`collapse_mass_failure`).
2. **junit wiring end-to-end**: `--junitxml=logs/debug/pytest-junit.xml` added to
   `scripts/checks/_scaffolding.py`'s `_build_unit_test_cmd()` (additive to the hermeticity flags);
   `.github/workflows/ci.yml`'s `main-validate` job and `.github/workflows/main-canary.yml`'s
   `canary` job upload it as the `pytest-junit` artifact on `if: always()`; `.github/workflows/ci-
   rca.yml` downloads it for the failing run (best-effort -- a non-pytest failure has no such
   artifact and falls back to the log-tail signature, never blocking the job).
3. **Status-aware chain, never closed->open**
   (`scripts/ops_portal/ci_rca_lifecycle.py`, new): `resolve_chain(fingerprint)` returns every
   source=ci_rca record matching a fingerprint, newest first. Only the NEWEST record, and only
   while `status=open`, is ever bumped (`newest_open_in_chain`) -- a closed head is never mutated.
   The rec-2644 revive path (`reopen_ci_rca_rec` / `find_recent_ci_rca_rec_by_fingerprint`) is
   REMOVED from `scripts/ops_portal/ci_rca_runtime.py`, and its call site -- the `file_rec()`
   write-time backstop in `scripts/ops_data_portal.py` -- is repointed at the chain helpers in the
   SAME change (portal-wedge guard: the two dead imports are deleted; `import
   scripts.ops_data_portal` and the `tests/ops_data_portal/` suite are the standing proof it is not
   ImportError-wedged). A closed-head fingerprint match runs `git merge-base --is-ancestor
   <failing-commit> <head.fixed_by_sha>`: an ancestor (stale-code rerun) is dropped with a no-op
   note (no insert, no bump, no reopen); a non-ancestor files a NEW record with `regression_of` set,
   a `"REGRESSION: "` title prefix, and `priority="Critical"`. A closed head with NO `fixed_by_sha`
   (every rec closed before this change; any manual closure) FAILS CLOSED to a REGRESSION -- the
   ancestry check cannot run without a fix commit to compare against, so this never silently drops a
   possibly-real recurrence (Decision 55). The closed->open prohibition is a fresh forward rule
   CITING Decision 103's closure-proof clause (a closed rec's `fixed_by_sha` is exactly that proof;
   reopening would discard it without contrary evidence) -- it does NOT amend a closed->open clause
   in Decision 103 (no such clause exists there); Decision 70 governs bootstrap-record deletion, not
   this.
4. **Auto-close, three paths, all deterministic**: (a) fix-linked --
   `.github/workflows/rec-autoclose.yml`, on closing a source=ci_rca rec from a `Resolves:`
   trailer, calls the importable helper `ci_rca_lifecycle.stamp_fixed_by_sha(rec_id,
   <merge-commit-sha>)`, recording the fix commit that powers point 3's ancestry check; (b) a purely
   TIMESTAMP-based inactivity predicate (`is_inactive` -- `last_seen`/`created_timestamp` older than
   a 30-day window AND rec created-age >= 14 days, BOTH bounds) closes via
   `scripts/ci_rca/inactivity_sweep.py` (new; `.github/workflows/ci-rca-inactivity-sweep.yml`, new
   scheduled + `workflow_dispatch` runner, OIDC creds, reads via the DuckLake reader NAMED VERBS
   only -- Decision 84 I-3 / Decision 88) with `resolution=stale_no_recurrence` and the recorded
   proof -- a purely deterministic timestamp probe stays inside Decision 103's
   deterministic-satisfaction boundary (no `close_proposed` needed, no run-history data source
   named); (c) a chain reaching 3 records is tagged `flaky` and quarantined instead of filing
   another fresh critical.
5. **Escape-attribution** (`ci_rca_lifecycle.compute_escape_class`): a post-merge full-tier failure
   is tagged `escape_class` in `{no-edge, capped, unknown-data-edge}` by diffing the failed test's
   file against the merged PR's Decision-135 `--pre` selection manifest -- `no-edge` (never
   selected, no reverse-dependency edge existed), `capped` (selected but deferred over the
   transitive-residue cap), or `unknown-data-edge` (was selected and should have run, but still
   escaped -- flagged for manual review, never silently assumed benign). `ci-rca.yml` best-effort
   resolves the merged PR from the failing commit and downloads its `selection-manifest` artifact;
   any resolution failure degrades to omitting `escape_class`, never blocking the job.
6. **Projection, not columns**: `regression_of`, `fixed_by_sha`, `affected_nodeids`, `flaky`, and
   `escape_class` are added to `CiRcaContext` (`scripts/ops_portal/ci_rca_schema.py`) as
   `Optional[...]=None` fields riding in `context_v2_json` -- NO `schema_version` ceiling raise (all
   backward-compatible additions), NO new `ops_recommendations` columns (Decision 84/103/63: the
   `ducklake_writer` owns the keyspace; fix-state is not denormalized onto the rec row). Field
   semantics are declared in `docs/contracts/ci-rca-lifecycle.yaml` (Decision 86: rationale here,
   semantics there), a non-ritual projection contract (no `contract:`/`class:` block, per Decision
   118/CD.25) mirroring `docs/contracts/recommendation-relevance.yaml`'s shape.

**Verification tier:** V2 (Decision 48/79) -- `compute_affected_artifacts` over the full scope set
(including `scripts/ops_data_portal.py`) returns `{}`; no active Lambda artifact is affected. The
junit-XML + selection-manifest handoff between `ci.yml`/`main-canary.yml` and `ci-rca.yml` is an
intra-repo CI artifact contract (no external service, no deploy) verified behaviourally via unit
tests, structural greps of the workflow wiring, and the natural post-merge self-test -- not a Lambda
deploy.

**Rationale:**
Anchoring the fingerprint on the failure's CAUSE (the deepest in-app traceback frame + exception
type + normalized message, or the failing module path for a collection error, or a normalized
log-tail signature for a non-pytest tool) rather than the CI step name is what makes two distinct
test failures in the same step stop masking each other while still letting one shared-helper
infrastructure error group correctly across the different tests it surfaces through. Making the
closed-head path a status-aware, ancestry-verified regression-or-drop decision -- instead of a
window-bounded reopen -- means a closed rec's fix-proof is never silently discarded: either the
ancestry check proves the new failure predates the fix (drop, no mutation) or it cannot prove that
and a fresh record captures the recurrence with its own investigation trail. The fail-closed default
on a missing `fixed_by_sha` extends that same discipline to the entire pre-this-change population of
closed recs, which carry no fix commit to check against.

**Reversal conditions:** Revisit this design if (a) the deepest-in-app-frame heuristic proves too
coarse or too fine in practice (e.g. a widely-shared low-level helper causing over-grouping of
genuinely distinct causes, or per-test-function attribution proving too granular for a class of
parametrized-test failures) -- adjust the frame-exclusion list or the message-head normalization
rules rather than reverting to a step-name key; (b) the ancestry check
(`git merge-base --is-ancestor`) proves unreliable on a shallow-clone runner in practice (ci-rca.yml
already checks out `fetch-depth: 2`, which may be insufficient for an old `fixed_by_sha` -- widen the
fetch depth or fall back to a deeper fetch on ancestry-check failure, never silently drop); (c) the
escape-attribution manifest-resolution path's best-effort PR/artifact lookup proves too fragile in
practice (a durable manifest->commit mapping, e.g. a DuckLake-registered table per the Decision 135
T2.36 deferral, would replace the current gh-api chase).

**Related:** Decision 135 (the `--pre` affected-set selection manifest this Decision consumes for
escape-attribution), Decision 103 (closure-proof clause this Decision's closed->open prohibition
cites; do NOT cite Decision 70 for this), Decision 84 (portal-only writes / named-verb reads / no
new Class A columns), Decision 92 (terraform-apply-sandbox apply-failure records carry
fingerprints -- the non-pytest fallback must cover them), Decision 72 (RCA-as-plan-source), Decision
55 (deterministic-in-code, fail-closed, no LLM-authored dedup/regression/inactivity/escape
decisions), Decision 86 (rationale->Decision, semantics->contract, no new prose doc), Decision 128
(SLOC decompose-by-default -- this work's two new submodules, `fingerprint.py` and
`ci_rca_lifecycle.py`, keep `evidence.py` and `ci_rca_runtime.py` under budget), Decision 104
(check-registry / `_scaffolding.py` command-builder home), Decision 63 (no denormalized fix-state),
Decision 62 (scheduled monitor / alarm-not-gate -- the inactivity-sweep workflow), Decision 48 +
Decision 79 (per-Lambda + verification-tier gating; V2 verdict), Decision 73 (public-repo boundary).
Supersedes CIRCA-03's grouping-fingerprint contract; resolves rec-2710 and rec-2644.

---

## Decision 141: Ratify CD.19 -- SCD2 timestamp policy on the T2.2 ops-table import was settled de facto as option (b) (created preserved, last_updated = import_time); resolved-by-events closure (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-141 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.19 (promoted from KG.10) required a timestamp-preservation decision BEFORE T2.2 imported ops_recommendations + ops_decisions from the company profile into the personal account, recommending option (c) (preserve created_timestamp; set last_updated = import_time; tag source='import-bootstrap' with a schema change in T0.12/T1.6). T2.2 completed 2026-05-29 out of order under a scope-(c) bootstrap exemption, and the decision window closed WITHOUT a formal ratification -- CD.19 was left `state: pending`, reading as a live pre-T2.2 decision that can no longer be taken (audit PCD-02: overtaken by events). This is a RESOLVED-BY-EVENTS closure decided by the human principal, NOT a realized-by-gate-completion ratification (T1.6, which CD.19 also gates, remains not_started).

**Decision:** Ratifies CD.19, recording the de facto outcome. T2.2 applied OPTION (b): created_timestamp preserved verbatim; last_updated_timestamp SET TO import_time. Rationale (principal's firsthand account): last_updated_timestamp is deterministically derived, so a workaround to preserve the original last_updated was not warranted at this stage. The recommended option (c) source='import-bootstrap' tag / schema change was deliberately NOT done. Consequence, accepted: last_updated lineage for import-era rows is not preserved (history loss, tolerable at this early dev stage). The false-positive-freshness flood that CD.19 feared was option (a)'s risk (preserve BOTH timestamps verbatim) and does NOT arise under option (b): last_updated = import_time makes imported rows read FRESH to any freshness check; moreover no freshness consumers are live (rec-curator disabled; the ratchet/drift detector depends on T3.7, unbuilt; the T1.6 DQ-runner reshape is not_started). Ratification clears CD.19's completion gate on T1.6 (and on the already-complete T0.12 and T2.2). T2.2's stale note ("original ids and timestamps preserved") is corrected in the same edit to state created preserved / last_updated = import_time.

**Reversal conditions:** none -- the timestamp policy is a settled historical fact of the completed T2.2 import, not a reversible forward commitment. If a future need to reconstruct pre-import last_updated lineage arises, that is NEW work (a re-import or a lineage-backfill) decided under its own Decision, not a reversal of this one. Any surviving live question about how the T1.6 DQ-runner treats import-era rows is ordinary T1.6 design scope, not a CD.19 gate.

**Related:** CD.19 (this ratifies it), CD.12 / T1.6 (DQ-runner reshape -- import-era rows read fresh under option (b); ordinary T1.6 design scope, no longer CD.19-gated), T2.2 (gated item, complete 2026-05-29; its scope-(c) bootstrap_completion_exempt is discharged by this ratification -- CD.6 + CD.19 now both ratified), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane), audit PCD-02 (audits/pending-cd-premise-validity-f4dec93.yaml -- the overtaken-by-events finding this closes; note the audit mis-recorded the outcome as option-(a)-shaped, corrected here to option (b) per the principal).

---

## Decision 140: Ratify CD.8 -- DuckDB is the realized default operational read engine (scoped to the engine choice; necessary not sufficient) (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-140 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.8 ("DuckDB = default operational read engine -- embedded, sub-second, no SSO, runs anywhere; Athena retained conditionally per CD.15; the typed query Lambda hides the engine from agents") was realized -- the engine choice is live -- but CD.8 stayed `state: pending`, gating completion of T1.2 and T2.5 and carrying no realization_evidence.

**Decision:** Ratifies CD.8, scoped to the realized ENGINE CHOICE. DuckDB is the embedded default operational read engine and DuckLake-on-Neon is the live ops read substrate: the ducklake_reader closed named-verb boundary (Decision 84 I-3) serves ops_recommendations / ops_decisions / ops_priority_queue reads, and the local read paths (sync_ops, ops_data_portal, session_preflight) route through the DuckDB reader (src/common/iceberg_reader.py) with the Athena escape hatch retained conditionally per CD.15. This ratification is NECESSARY, NOT SUFFICIENT (CD.2/CD.6/CD.20 precedent): it clears CD.8's completion gate on the items it gates -- T2.5 (DuckDB swap on read paths, complete 2026-05-31) and T1.2 (query-Lambda full verb expansion, completed_at 2026-07-07, flipped via the T1.16 verb-surface-closeout joint-closeout bookkeeping per RMAP-11) -- but does not itself close those items' code criteria (already met) and does not resolve the still-open CD.15 Athena-escape-hatch clause (OQ.7). T2.5's bootstrap_completion_exempt flag is RETAINED because its co-gating CD.15 remains pending (strip-only-when-ALL-gating-CDs-ratified).

**Reversal conditions:** revisit the default-engine choice if operational read scale exceeds what the embedded DuckDB reader serves within budget (the CD.15 Athena escape hatch is the retained relief valve; a sustained shift of the primary read path off DuckDB would supersede this Decision). The engine choice is coupled to CD.31 / Decision 78 (DuckLake as the native table format); a reversal of DuckLake adoption would reopen the engine question.

**Related:** CD.8 (this ratifies it), CD.15 (Athena escape-hatch clause -- still pending; co-gates T2.5, whose exemption is retained), CD.31 / Decision 78 (DuckLake table format under which DuckDB serves reads), T2.5 and T1.2 (gated items, both complete), Decision 118 (CD.25 ratification -- the "necessary NOT sufficient" scoping precedent this Decision follows, alongside CD.2/CD.6/CD.20 = Decisions 109/106/111), Decision 84 (closed ducklake_reader named-verb boundary + DECISIONS.md canonical/backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 139: Ratify CD.4 -- vendor lock-in to Claude Code on the web is acceptable; AGENTS.md is the realized portability hedge (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-139 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.4 ("vendor lock-in to Claude Code on the web is acceptable; AGENTS.md is the portability hedge -- symlinked or duplicated to CLAUDE.md so other harnesses pick up the same instructions") was realized when T0.9 (AGENTS.md sidecar + CLAUDE.md linkage) completed 2026-05-19, but CD.4 stayed `state: pending` with no realization_evidence.

**Decision:** Ratifies CD.4. The portability hedge is live: root `CLAUDE.md` is `@AGENTS.md` (an import directive), so AGENTS.md is the single canonical instruction surface and any other agent harness that reads AGENTS.md (Cursor, Aider, OpenHands, Continue, Codex) inherits the same universal rules without a per-harness fork. The deliberate lock-in to CC-web as the sole primary development surface (CD.2) is operating reality; the project consciously does not over-invest in cross-harness abstraction beyond the AGENTS.md hedge. Ratification clears CD.4's completion gate on T0.9 (already complete) -- necessary, not sufficient -- and discharges T0.9's bootstrap_completion_exempt flag (T0.9 gated solely by CD.4).

**Reversal conditions:** re-evaluate the lock-in acceptance and the level of cross-harness abstraction investment if a second agent harness becomes a first-class (co-primary) development surface, or if CC-web availability/pricing changes materially. The AGENTS.md hedge is the retained escape hatch that keeps that reversal cheap.

**Related:** CD.4 (this ratifies it), CD.2 (CC-web as sole primary surface -- the lock-in this Decision accepts), T0.9 (gated item, complete; exemption discharged), CD.20 / Decision 111 (AGENTS.md is part of the public curated portal), CD.5 / Decision 138 (sibling ratification in the same wave), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 138: Ratify CD.5 -- pre-commit augments (does not replace) the never_on_main hook; keep both commit-safety layers (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-138 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.5 ("pre-commit augments, does not replace, the never_on_main hook -- keep both; scheduled_agent_log_only.py stays, no portable analog") was realized when T0.10 (Pre-commit safety net) completed 2026-05-19, and T0.10's own exemption note already records "CD.5 ratifies post-hoc via the portal vehicle" -- but the evidence was never written and CD.5 stayed `state: pending`, invisible to the ratification lane.

**Decision:** Ratifies CD.5. The two commit-safety layers are both live and both retained: `.claude/hooks/never_on_main.py` intercepts intent-to-edit at the harness/PreToolUse layer (blocks Edit/Write/MultiEdit/NotebookEdit and git commit/push while on main); `.pre-commit-config.yaml` intercepts at commit-time in any clone (portable backstop, optionally bundling ruff / EOF / secrets scan). `scheduled_agent_log_only.py` stays (no portable analog). Ratification clears CD.5's completion gate on T0.10 (already complete) -- necessary, not sufficient -- and discharges T0.10's scope-(c) bootstrap_completion_exempt flag (T0.10 gated solely by CD.5; strip-only-when-ALL-gating-CDs-ratified is satisfied).

**Reversal conditions:** revisit if the harness-level never_on_main interceptor is retired or a single hook layer is shown to subsume both intercept points (harness intent-to-edit AND commit-time in a bare clone). Absent that, the augment-not-replace posture stands.

**Related:** CD.5 (this ratifies it), T0.10 (gated item, complete; scope-(c) exemption discharged by this Decision), CD.4 / Decision 139 (sibling portability-hedge ratification in the same wave), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 137: Ratify CD.9 -- partition-every-table uniform rule (substance already ratified by proxy via Decisions 78/81; this closes the locus gap) (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-137 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.9 ("partition every table; uniform rule -- ops/telemetry by day(last_updated_timestamp), market data by day(trade_date); new tables inherit the partitioned template; no unpartitioned-table path") was realized, and its substance was already ratified BY PROXY through Decision 78 (CD.31, DuckLake adoption) and Decision 81 (the CD.9 amendment establishing ALTER ... SET PARTITIONED BY as the DuckLake partitioning mechanism). That fact was recorded only in T2.4's note (the gated item), not on CD.9's own entry -- so an agent reading candidate_decisions[] saw a fully open decision (audit Q5c: same file, wrong locus). CD.9 carried no realization_evidence and was invisible to the ratification lane.

**Decision:** Ratifies CD.9, folding the proxy-ratification fact into the CD entry itself. The partitioning rule is in force. The three ops tables (ops_recommendations, ops_decisions, ops_priority_queue) live on DuckLake-on-Neon -- the sole backend (Decision 84) -- where partitioning is applied via ALTER ... SET PARTITIONED BY (a metadata-only operation), row/file-count-conditional per Decision 81 and not warranted at current ops-table sizes; T2.33 owns DuckLake partition-as-code going forward. Their day(last_updated_timestamp) partitioning originated in the T2.1 Iceberg era and is carried forward under DuckLake (the frozen Iceberg copy stopped being a live read path when writes moved to the DuckLake boundary, Decision 84). For the still-Iceberg tables (product D.lake.* + market data), scripts/schema_to_iceberg.py (T0.13) raises MissingPartitionSpec on @partition_by-less models and emits PARTITIONED BY verbatim (two-arg bucket/truncate extraction fixed by rec-2314). The "no unpartitioned-table path" absolute holds. Ratification clears CD.9's completion gate on T2.4 (already complete) -- necessary, not sufficient (T2.4's own criteria were already met).

**Reversal conditions:** none anticipated -- partition-everywhere is a uniform durable rule. Revisit only if a specific table's access pattern makes day-granularity partitioning net-negative at scale, in which case amend this Decision with the per-table exception rather than relaxing the uniform rule (Decision 81's mechanism-level CD.9 amendment is the precedent for a mechanism, not policy, change).

**Related:** CD.9 (this ratifies it), Decision 78 / dec-078 (CD.31 DuckLake adoption -- proxy ratification of the partitioning substance), Decision 81 / dec-081 (CD.9 ALTER-partitioning mechanism amendment), T2.4 (gated item, complete; its note carried the proxy fact this Decision folds back), T2.33 (DuckLake partition-as-code owner), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 136: Ratify CD.39 -- exit-criteria ledger (per-criterion status) is the realized in_progress-resolution mechanism; follow-on planning is the in_progress default (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-136 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.39 promoted each exit_criteria entry from free-text prose to a structured object {id, text, status: open|met|rehomed, met_by} so that "remaining work" on an in_progress item is the deterministic set of open criteria (Decision 59), replacing the conflation of mid-implementing / needs-next-plan / blocked under a single in_progress status. The mechanism is fully built, validate.py-enforced, and in daily bookkeeping use across the live roadmap, but CD.39 remained `state: pending` -- presenting as an open decision and (realization_evidence absent) invisible to the ratification lane.

**Decision:** Ratifies CD.39. The structured exit-criteria ledger is the realized, enforced mechanism: `scripts/checks/roadmap/validate_platform_roadmap.py` requires met/rehomed criteria to carry a met_by resolving to a real plan/commit/item, forbids a touched tier_item from retaining bare-string criteria, and resolves plan closes_criteria refs to real item criteria. The harness consumes it end to end -- /orient ranks in_progress items fewest-open-criteria-first and emits follow-on /plan prompts; /plan's follow-on mode declares closes_criteria; /implement flips declared criteria open->met on a verified VP pass and NEVER auto-flips an all-criteria-met item to complete (Status-Trusted-Never-Inferred, T2.20). CD.39 gates no tier_item (gates: []), so ratification carries no completion-gate side effect; it removes CD.39 from the pending / realization-candidate surfaces.

**Reversal conditions:** the git-YAML ledger is the lightweight near-term stand-in for T4.5 / Decision 87 (ops_plans / ops_plan_revisions warehouse entities, gated on CD.17); met_by is forward-compatible as a future ops_plans foreign key. When T4.5 lands, the ledger migrates to the warehouse (met_by becomes an ops_plans FK) -- a forward migration of the storage substrate, not a reversal of the per-criterion-status decision itself. Reversal proper would require abandoning deterministic per-criterion resolution for item-grain status only; file a superseding Decision if that is ever chosen.

**Related:** CD.39 (this ratifies it), Decision 59 (deterministic remaining-work), Decision 90 (three-tier /orient->/plan->/implement workflow the ledger feeds), Decision 87 / T4.5 (future ops_plans warehouse home; met_by FK forward-compat), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 135: Live, cacheless, strictly-additive affected-set selection replaces the --pre edited-set tier gate (amends Decision 73, 2nd amendment; builds on 80/104/124/131) (Decided)

**Status:** Decided
**Date:** 2026-07-17
**Warehouse ID:** dec-135 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The --pre fast tier's pytest selection (Decision 73, amended by the PR #334 explicit-paths fix)
only ever ran tests that were THEMSELVES literally present in the diff (the "edited-set"). A
source-only PR that broke a test it did not itself touch, or broke a downstream consumer of a
changed data file / roadmap YAML, passed the fast gate clean and only reddened post-merge on the
full tier (or the Main Canary) -- surfaced via rec-2638 (validate --pre under-checks untracked new
files) and repeated CI-RCA incidents where a data-shape change (Incident A: a YAML entry-count
edit) or a deleted file's dependents (Incident B) escaped the fast gate. Decision 73's own Known
Gap flagged this directly ("pytest --picked may be upgraded if false-negatives accumulate").

**Decision:**
1. **Four-channel live affected-set derivation** (`scripts/checks/deps/affected_tests.py`), unioned
   over the edited-set STRICTLY ADDITIVELY (selection can only grow): (a) import-closure
   reverse-deps, computed via `nx.ancestors` over `scripts/dependency_graph.py`'s live import
   graph; (b) a PRECISE data-edge channel (path or quoted-token match, never a bare substring) over
   non-.py data artifacts changed in the diff plus deleted-.py-bytes (Incident B) -- generalizes and
   retires the `select_roadmap_guard_tests` special case; (c)
   `scripts.test_coverage_checker.map_source_to_test()`'s mirror map (read-only use); (d) a
   conftest-subtree rule. A ~35-module cap protects against the import-closure channel's
   combinatorial blow-up: the edited-set, DIRECT reverse-deps, and data-edge hits are never
   deferred; only the transitive residue (plus the bounded mirror-map/conftest-subtree
   contributions) is capped, and any overflow defers LOUDLY -- the full post-merge tier still
   covers it. On an internal derivation exception, the selector falls back to the edited-set with a
   loud warning (Decision 55), never silently shrinking below it.
2. **Two dependency-graph soundness patches** (`scripts/dependency_graph.py`): (i) `__init__.py`
   package facades (Decision 124) are now graph nodes, so an importer of the PACKAGE (not a
   specific submodule) keeps its edge instead of silently dropping it; (ii) an AST pass unions
   string-constant module edges (e.g. `mock.patch("scripts.x.y")` targets), resolved to the longest
   existing graph-node module prefix.
3. **A new status-aware diff primitive** (`scripts/checks/_common.py`'s `get_status_aware_diff()`),
   added ALONGSIDE `get_changed_files()` (whose own contract for its existing callers is
   unchanged): `git diff --name-status` against the origin/main merge-base (deletions carry `D`
   status) plus `git ls-files --others --exclude-standard` (untracked new files) -- co-resolves
   rec-2638.
4. **Batched collect-only partitioning** (`scripts/checks/_scaffolding.py`): the per-file serial
   `--collect-only` loop is replaced by ONE batched invocation over every affected test file, with
   collection-ERROR blocks and `-rs` SKIPPED lines attributed back to their own file (never a
   whole-batch mis-defer on one bad file) -- nets ~30x fewer collect-only subprocess spawns, funding
   the derivation's added cost inside the 5-minute fast-tier budget.
5. **A per-run `selection-manifest.json`** (sha, status-aware diff, per-test provenance/channel,
   selected/capped/deferred, timings) is printed to the CI log, uploaded as a GitHub Actions
   artifact (`pr-validate`, `if: always()`), and best-effort-uploaded to S3
   (`ci/selection/<sha>/`, lazy-imports boto3, LOUD-skips when creds/boto3 are absent -- the
   no-creds fast tier). The manifest is an APPEND-ONLY OBSERVABILITY ARTIFACT consumed only by
   future CI-RCA escape-attribution -- it is NEVER read back as a selection input (structurally
   proven: the derivation never reads a prior manifest). DuckLake table / named-verb registration
   for the manifest is DEFERRED to T2.36, triggered by "first written cross-run query" -- this
   Decision does not build that registration.
6. **`select_roadmap_guard_tests` retired** (function + call site removed from
   `scripts/validate.py`); its behavior is subsumed by the general data-edge channel (proven by
   `TestRoadmapGuardSubsumption`).
7. **Inline implementation path taken.** The derivation feeds the EXISTING `pytest_diff` scaffold
   in `scripts/validate.py`'s `--pre` block; `scripts/checks/registry.py` and the
   `tests/test_checks_registry.py` frozen-baseline (`FROZEN_PRE_SCAFFOLDS`) are UNTOUCHED -- no new
   registered check or scaffold step was introduced.

**KG.13 boundary (explicitly NOT engaged):** KG.13 is the deferred Bazel/Pants-style
Test-Impact-Analysis + selection/coverage-CACHE work (`ROADMAP-PLATFORM.yaml` T3.11 c5), gated by a
revisit trigger (concurrency > 1 AND (KG.13 filed OR a fast-tier-budget breach)). This Decision's
derivation is LIVE, CACHELESS, and tool-free (ast/networkx only) -- explicitly NOT a selection cache
and NOT a coverage cache -- so it lands in Decision 80 point 3's sanctioned "live derivation"
bucket, not point 4's deferred-orchestrator bucket. This Decision files NO KG.13 tier_item and ARMS
NO revisit trigger; KG.13 stays deferred and undisturbed.

**Net-budget math:** the added live-derivation cost (import-graph build ~2-4s + the data-edge
single-pass scan + manifest emission) is net-funded by the collect-only batching's ~30x
subprocess-spawn reduction; the S3 upload leg is best-effort/async and never counts against the
5-minute budget assertion (Decision 73). VP step 17 (`validate --pre` dogfooding this very diff) is
the empirical proof; p90 target ~2-2.5 minutes.

**Verification tier:** V2 (Decision 48) -- the `ci.yml` edit is an `actions/upload-artifact` STEP
(not a check; not in Decision 48's V3 trigger list), and the S3 manifest object is best-effort
observability, not a contract another service consumes. The substantive verification is unit-level
incident-replay against the REAL selector (`tests/checks/deps/test_affected_tests.py`), not a live
deploy/invoke.

**Rationale:**
The prior edited-set selection was structurally blind to exactly the failure shape it exists to
catch (a change whose blast radius extends beyond the files it touches). A live, additive
derivation over the real import graph and data-references closes that gap without trading away
Decision 73's non-wedging fast-tier design: the additive-only invariant guarantees the new
selection is never a strict subset of the old one (no regression risk from the upgrade itself), the
cap+defer keeps worst-case cost bounded, and the manifest gives CI-RCA a forward-looking
escape-attribution surface without becoming a second source of truth (it is never read back).

**Reversal conditions:** Revisit this design if (a) the ~35-module cap's transitive-residue defer
rate proves high enough in practice that the full tier is routinely catching what should have been
fast-tier-caught (tighten the cap's channel-priority ordering, or promote the manifest's
deferred-count telemetry into a tier_item); (b) T3.11 c5's KG.13 revisit trigger fires for an
unrelated reason (concurrency > 1 or a genuine fast-tier-budget breach) -- re-examine whether this
design's live per-run cost still nets out, or whether a genuine selection/coverage cache (KG.13) is
now warranted; (c) the manifest's first written cross-run query need materializes -- action the
deferred T2.36 DuckLake/named-verb registration then, not preemptively.

**Related:** Decision 73 (fast-tier selection mechanism this amends, 2nd amendment after the PR
#334 explicit-paths fix), Decision 80 (import-graph oracle; the sanctioned-live-derivation vs
deferred-cache boundary this Decision sits inside), Decision 104 (checks registry / `_common.py`
sole-home discipline; the inline path this Decision took leaves both untouched), Decision 124
(facade re-export pattern the `__init__.py` soundness patch preserves), Decision 131 (mirror-map /
conftest hierarchy / per-package `__init__.py` -- channel 3's read-only dependency and channel 4's
rule), Decision 84 (warehouse SoT + numbering; DuckLake/named-verb registration deferred to T2.36
under this same authority), Decision 86 (agent-first; the manifest and this Decision's rationale
route here, not a new prose doc), Decision 128 / Decision 130 (SLOC decompose-by-default discipline
every touched/new file stays under), Decision 55 (fail-loud fallback on derivation exception; no
rescue loops), Decision 132 (verification graduation obligation this plan's VP dispositions
satisfy). Roadmap refs (not DECISIONS.md entries): rec-2638 (co-resolved: untracked new files now
visible to `--pre` selection), T2.36 (deferred DuckLake/named-verb registration for the manifest),
KG.13 / T3.11 c5 (deliberately undisturbed, see boundary note above).

---

## Decision 134: Ratify prose-monolith DECISIONS.md authoring with Decision-114-parity size governance; adopt the DAF-01/DAF-03 ETL-parity and authoring-contract direction as forward work; correct the T1.5 retirement end-state (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-134 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies the `ratify-prose-with-size-governance` disposition of the decisions-authoring-format audit (audits/decisions-authoring-format-d140093.yaml, findings DAF-01..DAF-04, confidence CONFIRMED) as the conscious ruling that audit found absent (its VD5 "absent" rating). This is the Decision-114 parity act for the decision log itself. Five clauses:

1. Prose-monolith authoring RETAINED for the interim. docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md stay human-authored reverse-chronological prose, git-authoritative and PR-diff-reviewed, on Decision 87 cl.2-3's own property test: human-authored, low-frequency, diff-reviewed content is correctly git-authoritative until a machine produces it at frequency. This holds until the T1.5 authority flip; it is a conscious retention, not drift. Flipping the container to a structured store ahead of T1.5 was assessed and rejected (L-XL cost, duplicates T1.5 Phase 2/3a work, and CD.17 freezes the capacity that would execute it) -- every measured machine-side deficiency is S-effort fixable inside the prose format.

2. Size ceiling + deterministic dual guard (Decision-114 parity). A new registry check validate_decisions_size (scripts/checks/decisions/validate_decisions_size.py, owner=platform), registered in BOTH the --pre (fast) and full validate tiers -- it is a cheap stat + header-count, so it blocks pre-merge and satisfies the audit's full-tier acceptance. Three module-level ceilings, all set ABOVE current size (336 KB / 92 live headers / 430 KB combined at ratification) so the guard does not fire on day one: _DECISIONS_LIVE_MAX_BYTES = 400_000 (the binding constraint -- the decision-scout subagent reads the whole LIVE file every /plan; ~2x headroom on a 200k-token window), _DECISIONS_LIVE_MAX_H2 = 120 (live `^## Decision` header count; a triage-quality guard), and _DECISIONS_COMBINED_MAX_BYTES = 700_000 (a live+archive backstop, since archival only shuffles bytes between the two files). The check covers docs/DECISIONS.md AND docs/DECISIONS_ARCHIVE.md, and on breach its message names the two relief valves: archival per DPI-04's dispositions (audits/decision-log-premise-integrity-8fb581e.yaml) and compaction of superseded decision bodies to pointer stubs. The archival tool itself is DPI-04's scope, not built here -- this guard only names it.

3. DAF-03 authoring-contract + single-shared-parser direction ADOPTED, implemented as forward work. The absent authoring grammar (~120 distinct section markers across the entry corpus; four independent hand-rolled parsers with divergent grammars) is to be closed by a docs/contracts decision-entry grammar (canonical marker set, forward-enforced; the archive h2 convention named) and consolidation onto one shared parser module every structural consumer imports. Scoped to a follow-on IMPLEMENTATION plan; not built by this Decision.

4. DAF-01 ETL-parity + fidelity-tripwire direction ADOPTED, implemented as forward work. The prose->ops_decisions projection is observed-lossy (8/8 sampled entries lose at least one governing element; empty decision_text on Decision 84, a garbage decided_date on Decision 67, all 15 Reversal-conditions carriers dropped). The forward fix: add a raw_block full-text parity backstop plus typed reversal_conditions and superseded_by columns, make the backfill differential via content-hash-gated SCD2 (amendments are recorded as SCD2 versions, not a separate column), fix the decorated-marker / plural-cite / date-fallback bugs, and add a loud backfill fidelity tripwire that fails when a live entry parses to an empty decision_text or a non-ISO date. Scoped to a follow-on IMPLEMENTATION plan; this Decision does not touch scripts/decisions_md.py or src/schemas/decision.py.

5. Roadmap retirement end-state CORRECTED (DAF-04). T1.5's first exit criterion is rewritten so docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md are retired ONLY AFTER (a) a decisions read portal (read-lambda + named verbs + a synced hermetic cache, mirroring the recs read path -- the ducklake_reader closed boundary + logs/.recommendations-log.jsonl synced via sync.ops pull) is live and ALL consumers read from it: planning agents (decision-scout, preflight) AND CI guards, including the R1 ratification guard validate_candidate_decision_ratification repointed off its prose-header grep onto the portal/cache; AND (b) a consumer-visible content-parity check (the DAF-01 parity gate, added as an explicit T1.5 exit criterion and mirrored in the Phase 3b wording) confirms every live-entry governing section is recoverable from ops_decisions before any reader is repointed. This supersedes the audit's "generate DECISIONS.md as a projection markdown file" framing: the end-state is portal-read, not a generated prose projection. T5.4 was already tombstoned into T1.5 c1 (2026-07-06 audit RMAP-05); the portal BUILD stays future T1.5 work (strategic, frozen under CD.17), and this Decision edits roadmap TEXT only.

**Reversal conditions:** The size ceiling is a BRIDGE guard protecting the decision-scout read until the read-portal authority flip. Revisit or retire the ceiling + guard when the scout moves to a warehouse/portal read (the guard's protected consumer is gone), when the model context window changes materially (the 200k-window headroom assumption no longer binds), or on a live breach whose only relief is a prohibitive /plan load cost in practice (not merely theoretical) -- mirroring Decision 114's reversal trigger. The retained prose-authoring clause reverses at the T1.5 authority flip, when a machine produces the decision corpus at frequency (per Decision 87 cl.2-3).

**Related:** Decision 84 (DECISIONS.md -> ops_decisions authoring/sync authority + the recreatability premise DAF-01 qualifies), Decision 86 (extend the machine-parseable schema rather than prose -- the DAF-03 authoring-contract direction), Decision 87 (cl.2-3 git-vs-warehouse authoring-timing property test this ratification rests on), Decision 104 (the registry-check pattern the new guard follows), Decision 105 (the R1 ratification guard's hermetic in-repo referential target that the portal end-state must repoint), Decision 110 (agent-first one-file/one-load principle), Decision 114 (the size-ceiling + deterministic-guard + reversal-conditions precedent this mirrors for the decision log), Decision 123 (ratifies CD.18, unblocking T1.5 Phase 2 whose end-state this corrects), Decision 132 (verification graduation is an enforced pre-merge obligation -- this plan's verification steps carry graduation dispositions per it), CD.23 (the curated-projection principle the corrected end-state honors), Decision 67 (the STRATEGIC/CD.17 freeze that makes interim ratify-in-place correct over a flip-now).

---

## Decision 133: Platform-first sequencing of build capacity (ratified with reversal conditions) (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-133 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
All of the sole operator's build capacity flows to the platform plane under a "platform-first" directive that, until now, existed nowhere as a ratified decision. The audit `audits/platform-first-sequencing-f4dec93.yaml` (executive summary `audits/platform-first-sequencing-f4dec93.md`) census found 41 citations of the frame and ZERO ratify-class artifacts: the frame was cited as a given by Decision 93 ("per the platform-first directive", twice) and recorded only as a user steer in one plan's scoping fields (`docs/plans/PLAN-platform-mvp-boundary.yaml:17`, restated `:146`, ~2026-06-20). None of the live Decision headers ratified plane sequencing; no alternative was recorded as examined; the only end-condition language was circular ("until product work begins" / "revisited when the product roadmap is activated" / T2.6 "when product formula-discovery work begins"). This is the system's single most consequential standing allocation carried as an inherited premise while materially smaller choices (file formats, provider routing, size ceilings) carry full ratification + reversal machinery (SEQ-01).

**Decision:**
Ratify platform-first sequencing of build capacity as a CONSCIOUS, reversal-conditioned choice: while the platform-MVP boundary (Decision 93) is open, the sole operator's build capacity is sequenced to the platform plane rather than interleaved with a manual product/paper trading loop. This is a governance-record change ONLY -- it reallocates no build capacity, changes no code or infra, and leaves `docs/ROADMAP-PRODUCT.yaml` at `status: draft`. The allocation is held for a recorded reason (below), not by inheritance, and is bounded by the observable reversal/review conditions in the stanza below -- it is never silently renewed.

**Frame provenance (conscious choice, not agent inertia):**
The frame is a conscious human steer, dated ~2026-06-20 in `docs/plans/PLAN-platform-mvp-boundary.yaml:17` (restated `:146`) as "the user's 'complete the full platform first' directive", and cited-as-given in Decision 93 (the two "per the platform-first directive" lines). The pivot transcript settles the ARCHITECTURAL platform/product plane SEPARATION (contracts, sibling roadmaps, validation lenses) but never weighs build-capacity TIMING between the planes -- so the sequencing rationale was genuinely absent from the record, not merely unindexed. The stronger "frame-locked" reading (Decision 75) was examined and REJECTED: the operator consciously restated the steer in a dated artifact and the owned /audit chain re-asked the question, so Decision 75's "silently constrains, nobody re-asks" limb does not hold. This Decision is the Decision-75-mandated conversion of an inherited, cited-as-given premise into a conscious, reversal-conditioned choice.

**Examined alternative (the interleaved manual/paper L1+L3 loop):**
The alternative -- interleaving platform work with a manual paper-trading loop today -- is FEASIBLE (human operations bypass every absent code surface: the operator is the broker adapter, order lifecycle, and reconciliation loop, over a production-grade data plane) but HIGH-COST in the binding resource (the sole operator's attention). Costed in operator units (audit Q2): one-time setup ~20-40 hours (paper brokerage account, daily signal-extraction path, sizing rule, pre-registered promotion criteria, logging/reconciliation runbook); recurring ~2-5 hours/week of market-hours-coupled, interrupt-driven attention sustained >= 13 weeks; calendar >= one quarter before promotion-grade evidence. The load-bearing qualifier: an honest ALPHA-premise test needs a discovered-formula artifact, and the discovery substrate is parked (CD.3 pending, T2.6 deferred_post_mvp) -- without a formula artifact the loop exercises operations plumbing, not the edge.

**Corrected value model (SEQ-03 -- telemetry category separation):**
The interleave's strongest stated payoff -- "real trading telemetry feeding the T2.36/T3.x chain" -- is a CATEGORY ERROR. The Decision-95 telemetry chain (T2.36 relands the agent-telemetry write path; T3.20 captures agent turns) is the session-rooted AGENT trace/observation model; a manual paper loop does not feed the Decision-95 agent-telemetry chain (it emits none of it). Paper-trading data would land in PRODUCT tables (strategy_runs, tca_events, fills) that `current_state` lists as ABSENT (the Decision-78 / Decision-95-97 ops/telemetry vs product-table split makes this literal) -- so "real telemetry sooner" does not hold, and building those product tables early IS the resequencing decision, circularly. Net (audit Q3): on the corrected value model the interleave's headline payoff evaporates, the near-term platform critical path (T2.26 -> T2.36 -> T3.2 -> T3.3) is dual-use substrate the product's evaluation funnel needs later, and reversal stays operationally ~free -- so sequencing is favored, CONDITIONALLY on the triggers below. Full costing and category analysis: `audits/platform-first-sequencing-f4dec93.yaml` (Q2/Q3, findings SEQ-03/SEQ-04).

**CD.3 / T2.6 disposition (SEQ-04 -- alpha-premise test path):**
CD.3 (compute node for PySR formula discovery) is DEFERRED, gated on the named reversal conditions below -- specifically alpha-readiness (c) and platform-MVP close (a). No compute-node stand-up date is committed and no substitute discovery substrate is named; the PySR discovery substrate and T2.6 stay parked. CD.3's re-entry trigger BECOMES condition (c): a candidate PySR formula artifact passing the research bar. This de-circularizes the prior note (T2.6 reactivating "when product formula-discovery work begins", an event nothing defined): T2.6's reactivation clause and Decision 93's product-edge language are re-pointed at the named conditions in this same change. This keeps CD.3 DEFERRED (not ratified), so the Decision-105 candidate-decision ratified-shape / R1-R3 guard is not engaged.

**Rationale:**
The audit's core result is an asymmetry the ratify-with-conditions disposition uniquely banks: the frame is, on present evidence, the right allocation held for the wrong reason (by inheritance rather than by record). The affirmative case survives adversarial tracing (operator attention is the binding resource; the near-term platform critical path is dual-use; the interleave's payoffs shrink under scrutiny; reversal stays operationally free), AND the gap case survives (zero ratify-class artifacts, no trigger, a convention sitting unused -- 24 "Reversal conditions:" stanzas elsewhere (16 at the f4dec93 audit; the tree grew the convention since)). `resequence_interleaved` is rejected on the corrected value model; `ratify_as_is` is rejected because the bet compounds monthly against an untested load-bearing premise (NS-D); `insufficient_evidence` is rejected -- once the telemetry category error is removed the evidence discriminates. Filed as user-explicit ad-hoc governance (precedent: Decision 93 / PLAN-platform-mvp-boundary; a fresh forward Decision per the Decision 87 / Decision 126 pattern), not a new tier_item. Reversal is cheap by construction: the frame binds via one /orient scope line and ROADMAP-PRODUCT.yaml's `status: draft`, so nothing is foreclosed by sequencing longer.

**Reversal conditions:**
This sequencing is re-decided, never silently renewed, when any of the following fires: (a) the platform MVP (Decision 93 boundary) closes -- at which point a product-activation decision becomes mandatory, not optional; (b) the hard calendar review date 2026-09-30 is reached without the platform MVP having closed -- the sequencing is re-decided via /plan, not renewed by default; (c) alpha-readiness -- a candidate PySR formula artifact passing the research bar exists, collapsing the paper loop's marginal cost and re-opening the interleave question; or (d) sustained slip -- 3 consecutive orient/triage cycles show the platform-MVP date receding. Condition (b) is the top-level `review_by` in the stanza below (single source; a re-decision is a one-line diff); (a)/(c)/(d) are the enumerated conditions. On any trigger, re-decide via /plan and update or re-arm the stanza.

```yaml reversal-conditions
decision: 133
review_by: 2026-09-30
on_trigger: "re-decide sequencing via /plan; update or re-arm this stanza; never silently renew"
conditions:
  - id: platform-mvp-closes
    kind: manual
    description: "Platform MVP (Decision 93 boundary) closes -> a product-activation decision becomes mandatory, not optional"
  - id: alpha-readiness
    kind: repo_state
    predicate: null   # manual until a formula-artifact predicate is registered (CD.3/T2.6 disposition)
    params: {}
    description: "a candidate PySR formula artifact passing the research bar exists -> paper-loop marginal cost collapses; re-open the interleave question"
  - id: sustained-slip
    kind: repo_state
    predicate: null   # manual until orient/triage cycles snapshot the MVP date
    params: {consecutive: 3}
    description: "3 consecutive orient/triage cycles show the platform-MVP date receding"
```

**Related:** Decision 93 (Platform-MVP boundary + deferred_post_mvp lifecycle -- the frame this Decision reversal-conditions; its two "per the platform-first directive" lines are the annotation targets; also the user-explicit ad-hoc-governance filing precedent and the no-live-dep invariant the ROADMAP edits respect), Decision 75 (frame-lock anti-pattern -- this Decision is its mandated conscious-choice conversion), Decision 95 (session-rooted agent-telemetry trace/observation model -- the SEQ-03 category boundary), Decision 96 + Decision 97 (telemetry temporal + identity standards completing the Decision-95 trio), Decision 78 (DuckLake adoption / product-table vs ops-telemetry split that makes "absent PRODUCT tables" literal), Decision 105 (reversal-condition-drafting-as-a-plan-step convention; CD.3 stays DEFERRED so the ratified-CD guard is not engaged), Decision 84 (Single Portal Invariant / DECISIONS.md numbering authority + backfill ETL), Decision 86 (rationale routes into this Decision, not a new prose doc), Decision 67 (STRATEGIC-plan freeze / CD.17 -- plan_type is IMPLEMENTATION), Decision 87 + Decision 126 (fresh forward-Decision precedent), Decision 108 (reversal-conditions section precedent the machine-parseable stanza extends), Decision 40 (recorded-then-forgotten triggers -- the cautionary failure mode a follow-on condition-monitor prices), Decision 101 (platform-first external-brand posture -- same lineage).

---

## Decision 132: Verification graduation is an enforced pre-merge obligation, not a skippable skill instruction (amends Decision 104; successor to T3.18/VF-05/VF-06) (Decided)

**Status:** Decided
**Date:** 2026-07-16
**Warehouse ID:** dec-132 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
T3.18 shipped the VF-05 graduation PRODUCER (the implement skill's Tier_item bookkeeping walk
graduates a plan's own kernel-expressible VP steps into
`config/agent/verification_registry/registry.yaml`) and the VF-06 differential admission gate
(`validate_verification_registry` re-runs a real `git worktree` revert against `origin/main` for
every new-in-diff row). Neither is an OBLIGATION: nothing forces a fix PR to actually add the row
it owes, and a skipped graduation is invisible to CI -- zero new registry rows looks identical to
"correctly graduated nothing." PR #586 shipped 4 orphaned checks unnoticed by this gap; rec-2677
independently flagged an under-graduated plan (2 of 6 candidate rows). The graduated-validation
model stays honest only if the obligation itself is enforced, not merely documented as a skill
instruction an agent can forget under context pressure.

**Decision:**
1. **Schema: an optional, validated graduation disposition per VP step.**
   `scripts/roadmap/plan_document.py`'s `VerificationStep` gains three optional fields:
   `graduation` (`graduate | waive | not-applicable`, `None` by default), `graduation_check_id`
   (required iff `graduation == "graduate"`), `graduation_waiver_reason` (required iff
   `graduation == "waive"`). A `model_validator` enforces both directions (required-when-set and
   forbidden-when-unset). The field is optional at the schema level -- `validate_plan_documents`
   re-validates every `PLAN-*.yaml` whole-directory (Decision 85), so every historical plan
   authored before this Decision keeps validating unchanged.
2. **New registered check: `validate_graduation_completeness` (both `--pre` and full tiers).**
   Diff-scoped, two legs:
   - **Plan-PR leg:** a diff-added or diff-modified `PLAN-*.yaml` must carry a graduation
     disposition on every `pre-deploy` VP step -- field PRESENCE only, never a
     kernel-expressibility inference (that classification judgement stays a human/plan-critique
     call, at plan time, never mechanized here). Enforced only when the plan is net-new in the
     diff (`git diff --diff-filter=A`) OR it already declares >=1 disposition -- a merely-modified
     plan with zero dispositions anywhere (a correction to a pre-field plan, or the lagged `.yaml`
     archival sweep) is a pre-field plan and is skipped, not failed.
   - **Implement-PR leg:** resolves the plan(s) named by `feat({slug})` commit subjects on
     `git log origin/main..HEAD`, loads `PLAN-{slug}.yaml`, and asserts every step declared
     `graduate` produced a matching NEW-in-diff registry row (`plan_slug` + `check_id` ==
     `graduation_check_id`). `waive`/`not-applicable` require no row. A step that proves
     un-graduatable at implement time is expected to flip to `waive` (with a reason) in the same
     PR -- the implement skill's Verification Graduation section is amended accordingly.
   Both legs advisory-SKIP (never fail) rather than wedge a legitimate PR when: origin/main is
   unreachable (the implement-PR leg cannot resolve new-vs-baseline without it), or a
   `feat({slug})` commit names a plan whose `PLAN-{slug}.yaml` is absent (legacy `.md`-era,
   archived, or a typo'd slug). Genuine errors (an import failure loading
   `scripts.roadmap.plan_document`) stay fail-loud (Decision 55) -- there is no silent
   "none enforced" path for an infrastructural error.
3. **Planning and plan-critique skills carry the obligation forward.** The planning skill's VP
   Design section requires a disposition on every pre-deploy step and gives the three-way
   classification rubric plus a `graduation_check_id` naming convention. The plan-critique skill
   adds criterion 12o: flag a missing disposition, a suspect `not-applicable` on an obviously
   kernel-expressible command, or a thin/generic `waive` reason -- the fresh-context honesty check
   this enforcement structurally depends on (see residual limitation A below).
4. **`docs/contracts/verification-registry.yaml` bumped to `contract_version: 3`** (a
   `governance_note_add` amendment, no schema field change) documenting the `(plan_slug,
   check_id)` join the implement-PR leg relies on.

**Disclosed residual limitations (on the record, not deferred silently):**
- **A -- classification seam:** whether a shell command is kernel-expressible
  (`graduate`-worthy) vs. genuinely `not-applicable` is not mechanically decidable in general.
  This Decision enforces disposition PRESENCE, never the classification's correctness. The
  fresh-context plan-critique gate (12o) is the honesty check, applied at PLAN TIME -- before the
  fix exists, so there is no pressure to wave through a finished implementation. A deterministic
  "smell" backstop for the obvious cases (a bare `pytest`/`test -f` node marked `not-applicable`)
  is deferred to a later phase, not this Decision.
- **B -- trigger seam:** the implement-PR obligation resolves from the `feat({slug})` commit
  subject convention (`## Commit-message conventions` in AGENTS.md). A code PR that omits or
  varies that prefix escapes the PRODUCTION-side obligation -- a disclosed false negative. This is
  the best available signal without a heuristic diff-based plan resolution; the plan-PR presence
  leg and the planning/plan-critique disposition-emission still bind the plan side regardless.
- Backlog recovery (PR #586's 4 orphaned checks; rec-2677's under-graduated plan) is explicitly
  OUT of this Decision's scope -- the forward gate cannot reach already-merged history; a separate
  follow-on plan owns retroactive recovery (optionally via a `fix_commit`-anchored differential, or
  a one-time manual graduation for a backlog this small).

**Reversal conditions:** if the disclosed trigger-seam false-negative rate (code PRs that omit
the `feat({slug})` prefix and thus escape the implement-PR obligation) proves material in
practice, revisit the resolution mechanism (e.g. a `Resolves: rec-NNNN` secondary trigger, deferred
to Phase 2 at decision time) rather than reverting the gate. If the plan-PR presence leg produces
excessive false positives on plans that are legitimately exempt, tighten the net-new/has-disposition
predicate rather than disabling the leg.

**Rationale:**
A prevention gate succeeds here where retroactive graduation of an already-merged fix (the PR #586
backlog) is structurally tautological: this Decision's non-tautology property depends on the
Decision 76/85 two-PR flow (the plan merges first, so at implement-PR CI time `origin/main` is the
PRE-FIX baseline and the differential is valid) -- and holds equally for a single-PR flow (plan +
fix together), since the plan is new-in-diff and `origin/main` is still pre-fix either way. Field
presence, not classification correctness, is what CI can enforce loudly and deterministically;
classification honesty is delegated to the layer built for judgement calls (plan-critique),
consistent with Decision 55's fail-loud-on-genuine-error / no-heuristic-inference discipline.

**Related:** Decision 55 (fail-loud, no rescue loops, no heuristic bug-fix inference), Decision 73
(fast-tier PR-gate budget this diff-scoped check must respect), Decision 76 (two-PR plan/implement
flow this Decision's non-tautology property depends on), Decision 83 (branch protection making the
`--pre` tier authoritative), Decision 84 (Warehouse sync via `--backfill-decisions-md`), Decision 85
(whole-directory plan re-validation; optional-field backward compatibility), Decision 86
(agent-first, machine-parseable documentation), Decision 104 (registered-check pattern this new
check follows; the differential admission gate framework it extends), Decision 128 (decompose-by-
default discipline both new files stay under). Roadmap/audit refs (not DECISIONS.md entries,
grounded directly): CD.29 (six-slot kernel vocabulary, never touched by this Decision), VF-05
(the producer this Decision makes an obligation), VF-06 (the differential gate this Decision does
not modify), VF-11, tier_item T3.18 (predecessor, complete) and T3.21 (this Decision's carrier).

[Amendment 2026-08-17: the implement-PR leg's commit-subject resolution (`feat({slug})` commit subjects on `git log origin/main..HEAD`) is replaced by an explicit, schema-validated `implementation_declared` boolean on `PlanDocument`, resolved content-keyed via `scripts.checks._common.resolve_declared_plans` (PLAN-plan-resolution-content-keyed, provenance: explicit operator direction given during that plan's authoring). The plan-PR leg's disposition-presence obligation and the differential admission gate are unchanged; only the implement-PR leg's resolution signal moves from commit-message grammar to diff-carried plan content.]

---

## Decision 131: Test-colocation mapping inverted to a mirror rule + retiring grandfather-table; no-cross-test-import guard and per-package conftest hierarchy (amends Decision 104; enables rec-2709) (Decided)

**Status:** Decided
**Date:** 2026-07-15
**Warehouse ID:** dec-131 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 130 grandfathered the 24 pre-existing oversized `tests/` files and deferred both their
decomposition and the inversion of `map_source_to_test` / the Decision-104 test-colocation rule to
rec-2709. Before any of the ~14 decomposition waves can move a single test file, the program needs
shared enabling machinery: a mapping rule that supports a mirror-package test layout, a mechanism
that lets each wave retire exactly one grandfathered home without touching the other 23, a guard
against the cross-package coupling a mirror-package split would otherwise invite, and a documented
conftest layering convention for the sub-packages the splits create.

**Decision:**
1. **Mirror rule + retiring grandfather-table.** `scripts/test_coverage_checker.py`'s
   `map_source_to_test` is inverted from unconditional Decision-104 colocation to a two-rule
   function gated by a retiring grandfather-table. The pre-inversion body is preserved verbatim as
   `_grandfathered_source_to_test`. `_ALL_MIRROR_TARGET_HOMES` is the fixed 24-basename rec-2709
   roster (the Decision 130 grandfathered set); `_RETIRING_GRANDFATHER_HOMES` is a mutable subset,
   seeded identical to the full roster on day one. `map_source_to_test` resolves a source path's
   grandfathered home; while that home's basename is still in `_RETIRING_GRANDFATHER_HOMES`, the
   colocation rule applies unchanged; once a wave deletes that basename (a one-line, low-conflict
   edit), sources that grandfather to it resolve via `_mirror_source_to_test` -- drop the leading
   `src`/`scripts` root, keep the remaining sub-path, name the test `test_<stem>.py`. A declared
   concern-split monolith (`_CONCERN_SPLIT_TEST_PACKAGES`, seeded with the 11 known single-file
   monoliths with no per-submodule source to mirror 1:1) instead resolves to a test PACKAGE
   DIRECTORY. `check_test_file_exists` / `check_per_file_coverage` are extended to accept a
   directory target (passes iff it exists with >=1 `test_*.py`; coverage runs pytest against the
   directory). Day one, `_RETIRING_GRANDFATHER_HOMES == _ALL_MIRROR_TARGET_HOMES`, so the mirror
   branch is dormant and `map_source_to_test` is byte-identical to the pre-inversion function for
   every input -- proven by the pre-existing `TestMapSourceToTest` / `TestCheckTestFileExists`
   suite staying green unchanged. `scripts/executor/**` and `scripts/ops_portal/**` continue to
   return `None` on both rules (Decision 124 preserved).
2. **No-cross-test-import guard.** A new AST-based check,
   `scripts/checks/hygiene/validate_no_cross_test_imports.py`
   (`validate_no_cross_test_imports`, registered in both `pre_sequence()` and `full_sequence()`
   adjacent to `validate_test_count_coupling`), fails when a `tests/**/*.py` module imports from
   another `test_*` module. `conftest.py` and `tests/fixtures/**` are exempt by construction (their
   names never start with `test_`), encoding "each mirror package is self-contained." The one
   pre-existing violation, `tests/test_verifier_harness.py` (a documented re-export shim of
   `tests/test_verifiers/test_harness.py`), is grandfathered in
   `_GRANDFATHERED_CROSS_TEST_IMPORTS` until a later wave removes the shim.
3. **Per-package conftest hierarchy.** The global recursion guards (`_VALIDATE_DEPTH`,
   `_COVERAGE_SUBPROCESS`, the `PYTEST_CURRENT_TEST` early-exit) and socket guards
   (`--disable-socket` + `_allow_network_for_integration`) stay solely in the root
   `tests/conftest.py`; pytest merges conftests up the tree, so a sub-package
   `tests/<pkg>/conftest.py` layers under it without redeclaration. `tests/checks/conftest.py` is
   added as a docstring-only example scaffold; package-specific autouse fixtures migrate into their
   matching sub-conftest per-wave, alongside that package's test-file decomposition.
4. **Import-mode / `__init__.py` policy.** pytest stays in the default prepend import mode (the
   repo already depends on the package-path model via `from tests.fixtures.iceberg_fixture import
   ...`). Every mirror test directory carries an `__init__.py` so module paths stay fully-qualified
   and collision-free as the mirror tree grows. `tests/checks/__init__.py` and
   `tests/checks/hygiene/__init__.py` are added now (the chain above the new guard's own test);
   `tests/test_verifiers/` is left as-is, normalized by its own wave.
5. **Zero test files moved, zero grandfather entries retired.** This Decision lands ONLY the
   enabling machinery. No test file is split, renamed, or relocated, and `config/sloc_budgets.yaml`
   is untouched. rec-2709 closes only when the last `tests/` budget entry is deleted -- tracked
   per-wave, not by this Decision.

**Reversal conditions:** none anticipated for the mirror rule or the conftest-hierarchy convention
while rec-2709 stays open; if the no-cross-test-import guard produces excessive false positives
once mirror packages proliferate, the detection heuristic (final-dotted-component /
relative-import-name starts with `test_`) can be tightened without reverting the guard itself.

**Rationale:**
Inverting the mapping behind a retiring grandfather-table lets each of the ~14 later decomposition
waves retire exactly one basename with a single-line, low-merge-conflict edit, while guaranteeing
day-one behaviour is byte-identical to the pre-inversion function (verified, not asserted) so this
Decision carries zero regression risk on its own. The cross-test-import guard is scoped now, before
any mirror package exists, so the self-containment invariant is enforced from the first split
onward rather than retrofitted after packages have already coupled. The conftest-hierarchy note and
the `__init__.py` policy are recorded as explicit, agent-first documentation (Decision 86) rather
than left to be rediscovered independently by each of the ~14 waves.

**Related:** Decision 104 (test-colocation mapping this amends; check-registry pattern the new
guard follows), Decision 130 (the 24-file grandfather this program decomposes; rec-2709 filed
there), Decision 128 (decompose-by-default / raise-approved marker discipline this foundation
respects by staying under 500 SLOC), Decision 43 (SLOC/CC limits the new files stay under), Decision
86 (agent-first, machine-parseable documentation principle), Decision 84 (Warehouse sync via
`--backfill-decisions-md`); Decision 124 (the `scripts/executor/**` / `scripts/ops_portal/**`
None-return preserved unchanged by both mapping rules). The day-one byte-identical guarantee is the
gate for this Decision's own safety; rec-2709 closes only when the last `tests/` budget entry in
`config/sloc_budgets.yaml` is deleted.

---

## Decision 130: Structural-size governance covers the whole repo -- one-time grandfather of tests/ debt (completes Decision 43; amends Decisions 102/128 scan scope) (Decided)

**Status:** Decided
**Date:** 2026-07-15
**Warehouse ID:** dec-130 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`validate_sloc_limits` and `validate_cc_limits` scanned only `scripts/` and `src/` -- `tests/` was
never handed to the scanner (it is not on the deliberate vendored-exemption list). Decision 43
declared the limits apply "across all repository code," so this was an exempt-by-omission gap, not
a deliberate exclusion. 24 `tests/` files exceed the 500-SLOC limit at the time of this decision;
the two largest files in the entire repository are tests (`tests/test_validate.py`,
`tests/test_execute_recommendation.py`).

**Decision:**
1. **Whole-repo scan.** `validate_sloc_limits`, `_update_sloc_budgets`, and `validate_cc_limits` now
   walk every repository directory via one shared helper (`iter_gated_py_files()` in
   `scripts/checks/sloc/_shared.py`), excluding only a vendored/generated set (`pip`,
   `lambda-packages`, `docker`, `terraform`, `.venv`, `node_modules`, `.git`, `personal_scripts`) and
   `__init__.py`. No hand-authored directory (`tests/`, `.claude/`, `bin/`, `config/`, etc.) is
   exempt. The three gate functions consuming one shared scan definition means they can no longer
   silently drift apart (a divergence would make a future `--update-sloc-budgets` regen silently
   drop entries for a directory only some of the functions scanned).
2. **One-time grandfather of pre-existing tests/ debt.** The 24 tests/ files already over 500 SLOC
   are registered in `config/sloc_budgets.yaml`, each carrying an inline
   `# raise-approved: dec-130 ...` marker (the Decision 128 bounded-exception path for pre-existing
   debt). This is a ONE-TIME grandfather, NOT a precedent for future test growth: any tests/ file
   that grows past its registered budget still fails the gate (the ratchet is downward-only and
   full-tree, not diff-scoped).
3. **CC extended to tests/.** `validate_cc_limits` now also covers `tests/`; verified zero-cost at
   decision time (0 violations across all test files under the existing 20-branch limit).
4. **Cheap recursion-guard hardening.** `scripts/validate.py`'s `main()` now also exits early when
   `PYTEST_CURRENT_TEST` is set (in addition to the existing `_VALIDATE_DEPTH` guard), ahead of the
   test-tree reorganisation the follow-on decomposition work will perform.
5. **Deferred to rec-2709.** The actual decomposition of the 24 grandfathered files, and the
   inversion of `map_source_to_test` / the Decision 104 test-colocation rule to a mirror-package
   structure, are explicitly OUT of scope here and tracked as rec-2709 (filed the same session as
   this Decision).

**Reversal conditions:** none anticipated; reverting would mean re-narrowing the scan back to
`scripts/`+`src/`, which would reopen the exempt-by-omission gap this Decision closes. If a future
vendored/generated directory needs exemption, add it to `_SLOC_EXCLUDE_DIRS` rather than reverting
the whole-repo scan.

**Rationale:**
The SLOC/CC gates exist to protect model-portability of the comprehension surface (Sonnet/Gemini/
Deepseek-tier models degrade on large files) -- that rationale applies to `tests/` exactly as much
as to `scripts/`/`src/`. Grandfathering the 24 pre-existing files avoids a disruptive one-shot
decomposition inside a governance-hardening PR (scope creep the plan explicitly avoided), while the
raise-approved markers plus rec-2709 ensure the debt is tracked and bounded rather than silently
re-exempted.

**Related:** Decision 43 (original SLOC/CC limits; "all repository code" intent this completes),
Decision 102 (SLOC budget ratchet, amended here to whole-repo scope), Decision 128 (raise-approved
marker path this grandfather uses; decompose-by-default principle), Decision 104 (check-registry
pattern; test-colocation mapping inversion deferred to rec-2709), Decision 84 (authored here,
backfilled to `ops_decisions`, never written directly), Decision 86 (machine-parseable /
agent-first repository principle this whole-repo coverage extends to test files).

---

## Decision 129: Data-plane resource-axis read broadening for CI refresh-read grants, with a pre-merge coverage verifier (Decided)

**Status:** Decided
**Date:** 2026-07-15
**Warehouse ID:** dec-129 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 157 (2026-07-30):** point 2's "Secrets Manager stays enumerated" is
> narrowed to VALUE-CAPABLE actions only (`secretsmanager:GetSecretValue`, and
> `secretsmanager:UpdateSecret` per Decision 143 clause 1); value-free metadata actions
> (`Describe*`, `List*`, `GetResourcePolicy`) MAY ride the `agent-platform-*` prefix on both
> the read and the write side. This body is otherwise unedited; see Decision 157 for the
> derivation, accepted residuals, and reversal conditions.

**Problem:**
`github_ci_apply` refresh-reads the ENTIRE `terraform/personal` state on every plan, but its grants
live out-of-band in `terraform/bootstrap/github_ci_apply.tf` (self-grant break, T2.23) and are
enumerated per-ARN. A new resource always outruns the enumerated list by one PR/apply cycle -- this
has recurred 15+ times in ~6 weeks (rec-1985..rec-2702). T2.43 added a GitHub PAT secret + 3 prod
Lambdas + an hourly rule; `terraform/personal/oidc.tf`'s `github_ci_plan`/`github_ci_drift` grants
were kept in sync, but the cross-tier bootstrap copy lagged, causing AccessDenied on refresh and a
red sandbox convergence record (rec-2702). Pre-merge detection cannot catch this today: at PR time
the new resource isn't yet in state, and the speculative-plan/local-replan identities are both
broader than the least-privilege apply role -- so detection must be STATIC HCL coverage, not a plan.

**Decision:**
1. **Broaden the DATA-PLANE resource axis** to an account-wide `agent-platform-*` prefix for the
   two uniformly-named services -- `LambdaRead` (`function:agent-platform-*`) and `EventBridgeRead`
   (`rule/agent-platform-*`) -- in all three plan-capable role policies (`github_ci_apply` in
   `terraform/bootstrap/`; `github_ci_plan`/`github_ci_drift`'s shared `ci_full_refresh_read` in
   `terraform/personal/oidc.tf`). A future `agent-platform-*` function/rule auto-covers.
2. **`iam:` reads and Secrets Manager stay enumerated** (Decision 35/98 -- mixed naming, and
   secrets return VALUES). `terraform/bootstrap/github_ci_apply.tf` gains one enumerated Sid,
   `SecretsManagerGithubPatRead`, closing the T2.43 cross-tier lag for that one secret.
3. **Read-refresh grants sit outside the IAM-write authority budget** (Decision 92 point 5 /
   Decision 98 point 2 -- reversal window kept below the 2500-char VP scan): pt5's in/out-of-budget
   classification governs `aws_iam_role_policy` WRITE diffs on branch/pr; pt2 already established
   a read-only grant addition (there, `IAMRolesRead`) does not touch that write budget. This is the
   same shape generalized from `iam:` to `lambda:`/`events:`; `authority_budget.json`,
   `IAMRoleWriteBounded`, `DenyIAMEscalation` are untouched.
4. **New pre-merge coverage verifier** (`scripts.checks.iam_tf.validate_ci_refresh_read_coverage`,
   `--pre` + full tiers): classifies every `terraform/personal` resource type into (i) needs an
   independent refresh-read grant -- asserted covered (literal ARN / prefix / bare-or-interpolated
   reference) in ALL THREE role policies; (ii) transitively covered by a parent/sibling grant; (iii)
   `iam:` enumerated-only (never a wildcard, Decision 35/98); or (iv) not AWS-IAM-gated at all. An
   unmapped type FAILS LOUD rather than silently passing.
5. **Forward-fix, not occurrence-fix** (Decision 55/72): the three ad-hoc grants are not the
   deliverable -- the prefix broadening (Lever A) + coverage verifier (Lever B) are.

**Reversal conditions:** re-narrow `LambdaRead`/`EventBridgeRead` to enumerated literal ARNs if the
account ever hosts a non-`agent-platform-*` Lambda function or EventBridge rule, or on any incident
showing this prefix over-grants. `iam:` reads and Secrets Manager are out of scope and need no
reversal.

**Rationale:**
Every managed Lambda function and EventBridge rule here is, verified, uniformly named
`agent-platform-*` -- an account-scoped prefix (not a service-wide wildcard) safely auto-covers
future resources of these two types. Layers/secrets are mixed-named, so they stay enumerated and
rely on the coverage verifier (Lever B) instead of a prefix (Lever A); `iam:` reads are excluded on
principle (Decision 35/98) regardless of naming uniformity. Lever A closes the RESOURCE axis for
the two most-recurring types; Lever B closes detection for everything else, including a
hypothetical future resource type this repo does not yet have -- and makes "why didn't ci-rca fire"
moot for this class: a pre-merge catch means no red record and no ci-rca run.

**Related:** Decision 92 (CD.35 authority-budget/ratchet; pt5 cited above), Decision 98 (admin-create
+ read-only bootstrap grant precedent this extends from `iam:` to `lambda:`/`events:`; pt2 cited
above), Decision 35 (enumerated `iam:` reads, unchanged here), Decision 55/72 (RCA-first,
forward-fix-the-generator), Decision 104 (check-registry pattern followed), Decision 128 (SLOC
decompose-by-default -- verifier stays under budget, no raise registered), Decision 84 (authored
here, backfilled to `ops_decisions`, never written directly), Decision 94 (github_ci_apply OIDC
trust / gated-apply precedent), Decision 119/120 (provider-mirror egress -- the fresh-plan-converges
verification here is CI/admin-run, not a local CC-web plan).

---

## Decision 128: SLOC budget-raise guardrails -- decompose by default, raises must be loud and Decision-cited (amends Decision 102) (Decided)

**Status:** Decided
**Date:** 2026-07-14
**Warehouse ID:** dec-128 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 165 (2026-08-04):** clause 3 ("marker persistence is not required...
> authorized at the diff-vs-base moment") is amended -- a marker that IS present is now
> retroactively load-bearing under the shared `scripts/checks/_marker_guard.py` authorization
> mechanism. This body is otherwise unedited; see Decision 165 for the full derivation.

**Problem:**
`scripts/convergence_health.py` was created at 401 SLOC (#516) and grew to 817 via three manual
budget raises -- 600 (#559/T2.38), 800 (#565/T2.43), 817 (#566/T2.35) -- each individually
justified by module cohesion. Decision 102's ratchet enforced *downward* movement (a budget can
never silently rise on its own) but placed no friction whatsoever on the *upward* edit: raising
`config/sloc_budgets.yaml` was, and remained, a one-line YAML change with no gate, no required
justification, and no visibility distinct from any other config edit. Three individually-
reasonable raises accreted into an 817-SLOC file with no single moment where the accretion itself
was surfaced for review. The 500-SLOC limit is load-bearing for model portability: Opus tolerates
large files, but lower-tier models (Sonnet/Gemini/Deepseek) degrade on comprehension. A budget
raise silently trades that away -- which is exactly why raises must become loud, deliberate, and
Decision-cited rather than a frictionless one-line YAML edit.

**Decision:**
1. **Decompose by default.** When a change would push a scripts/ or src/ file past its SLOC
   budget (or past 500 for a currently-unregistered file), the default response is to decompose
   the file into a facade package (the Decision 80/104/124 pattern: an `__init__.py` facade
   re-exporting the full public surface, cohesive submodules each under budget). A raise is a
   deliberate, justified exception -- not the default path of least resistance.
2. **Fail-loud raise gate.** A new check, `validate_sloc_budget_raises`
   (`scripts/checks/sloc/validate_sloc_budget_raises.py`, registered in `pre_sequence()`
   immediately after `validate_sloc_limits`), diffs `config/sloc_budgets.yaml` against
   `origin/main` on every PR. It FAILS the PR on any budget INCREASE, or any NEW >500-SLOC
   registration, unless the changed entry line carries an inline `# raise-approved: dec-NNN
   <reason>` marker naming a real `## Decision NNN:` header in `docs/DECISIONS.md`. Decreases and
   removals always pass (the ratchet-down direction is unrestricted, matching Decision 102). The
   check parses the raw YAML text (not `yaml.safe_load`, which drops comments) so the marker
   survives; its base-content reader is injectable for tests and SKIPs (non-failing, advisory
   locally / authoritative in CI) when `origin/main` is unreachable, mirroring
   `validate_vp_replay`.
3. **Marker persistence is not required.** `_update_sloc_budgets` (the downward-only ratchet
   regenerator) is not required to preserve inline `# raise-approved` comments across a
   regeneration -- the raise is authorized at the diff-vs-base moment and, once merged, is
   durably recorded in git history plus the cited Decision. This deliberately avoids building a
   comment round-trip mechanism against `yaml.safe_dump`.
4. **No auto-seed (B2 / rec-2418 family).** `_update_sloc_budgets` no longer seeds a newly-
   oversized, currently-unregistered file at its current SLOC. Previously, running
   `--update-sloc-budgets` would silently register any new >500-SLOC file, defeating the purpose
   of a raise gate (an agent could regenerate its way around review). Now, a new oversized file
   fails `validate_sloc_limits` until it is either decomposed below 500 SLOC or deliberately
   registered with a `# raise-approved: dec-NNN` marker via a manual, reviewable edit.
5. **YAML-safe serialization (rec-2422).** `_update_sloc_budgets` emits `config/sloc_budgets.yaml`
   via `yaml.safe_dump` instead of raw f-string interpolation, so a future module path containing
   YAML-special characters cannot produce invalid YAML.
6. **Doctrine surfaces.** The decompose-don't-raise rule is added to `AGENTS.md` (a new SLOC-
   governance subsection) and to the `planning`, `implement`, and `plan-critique` skills, so the
   rule is visible at plan time, implement time, and critique time -- not just enforced after the
   fact by CI.

**Rationale:**
Decision 102 solved the *unbounded* growth problem (a waiver alone no longer permits infinite
SLOC) but left the *registration* mechanism itself frictionless, so the ratchet could still creep
upward one deliberate-but-unreviewed raise at a time. This Decision closes that gap by making the
upward edit as loud as a Decision citation, while leaving the downward ratchet exactly as free as
before. Per Decision 86, rationale lives here; the fail-loud check and the no-auto-seed behaviour
are the code-level enforcement; the doctrine text in AGENTS.md and the three skills is intent
routing, not a new standing prose-architecture document.

**Reversal conditions:** none identified. A future plan may relax the gate (e.g. widen the marker
format) but that is an amendment, not a reversal of the decompose-by-default doctrine.

**Related:** Decision 102 (amended here -- the raise-side gate this Decision adds), Decision 43
(original SLOC/CC limits), Decision 104 (check-registry pattern the new guard follows; the facade-
decomposition pattern this Decision's "decompose by default" doctrine reuses), Decision 80
(validate.py decomposition precedent), Decision 124 (facade-decomposition pattern extended to the
ops-data layer, same shape reused here for convergence_health.py), Decision 84 (this Decision is
authored in DECISIONS.md then backfilled to `ops_decisions`, never written directly).

---

## Decision 127: Sanctioned-prose taxonomy -- the only prose stored in this repo is agent-instruction content (expands Decision 86) (Decided)

**Status:** Decided
**Date:** 2026-07-13
**Warehouse ID:** dec-127 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 171 (2026-08-16):** point 1's enumeration gains a second separately
> sanctioned NON-agent-instruction class, **licence-and-attribution artefacts** (added inline
> below). The taxonomy's rule is unchanged; this is an addition to the permanent classes, made
> as an `allowed_globs` entry and never as a `grandfathered_globs` one, since point 3's
> grandfathered set is ratchet-only and may not grow. Points 2, 3 and 4 are unedited; see
> Decision 171 for the full derivation.

**Problem:**
Decision 86 forbade new *standing prose-architecture / deliberation* documents and retired the
INTENT-*.md corpus, but it never named the positive rule the repo actually needs: which prose is
sanctioned at all, and why. Two concrete gaps followed. First, the Decision 120 break-glass
recovery procedure lived ambiently inside `terraform/CLAUDE.md` -- a Layer-1 universal-rules
surface every terraform-directory session loads -- rather than in a quarantined, on-demand
location, exactly the ambient-visibility failure mode Decision 126 point 4 named and scheduled
for quarantine (tier_item T2.41) once the T2.37 heal button landed. Second, no deterministic
guard enforced ANY prose allowlist repo-wide (only the narrower `docs/`-root depth-1 allowlist
and the INTENT-doc freeze existed), so new prose files could land anywhere with no gate.

**Decision:**
1. **The taxonomy.** The only prose (markdown) sanctioned for permanent storage in this repository
   is content whose audience-of-record is an agent -- "agent-instruction" in the broadest sense.
   No document whose audience-of-record is a human may be stored as a standing repository
   artefact; a human-facing summary is a query result an agent produces on demand, never a
   stored artefact (AGENTS.md Agent-First Repository, extended here from principle to enforced
   taxonomy). The permanent classes are:
   - (a) Universal/directory-scoped instruction files (`CLAUDE.md`, `AGENTS.md`, `**/CLAUDE.md`).
   - (b) Machine-readable contracts and their prose companions where the contract format is
     itself markdown (`docs/contracts/**/*.md`) -- these are agent-consumed field/procedure
     semantics, not human narrative.
   - (c) Workflow surfaces: slash commands (`.claude/commands/**/*.md`), skills
     (`.claude/skills/**/SKILL.md`), executor role prompts
     (`config/agent/executor/prompts/**/*.md`).
   - (d) Planning/audit artefacts consumed by the workflows that produce and read them:
     `docs/plans/**/*.md`, `docs/audit-prompts/**/*.md`, `audits/**/*.md`.
   - (e) CI/repository-governance files under `.github/**/*.md` (issue templates, PR templates,
     scheduled-agent prompts) and `docs/PROJECT_CONTEXT.md` (the Layer-2 agent knowledge base,
     instruction-architecture.yaml).
   Permanently and separately sanctioned as a NON-agent-instruction class: `marketing/**/*.md`
   (Decision 101 point (c)'s carve-out). Marketing prose is one-way downstream -- authored for a
   human audience outside the agent loop and never fed back into any agent's context -- so it is
   not "prose whose audience-of-record is a human" in the sense this Decision forbids storing;
   it is pre-sanctioned here even though `marketing/` does not exist on disk yet, so a future
   marketing-content plan does not need to re-litigate this taxonomy.
   Also permanently and separately sanctioned as a NON-agent-instruction class (Decision 171):
   **licence-and-attribution artefacts** at the repository root -- `LICENSING.md` (the
   forward-only licence boundary and its self-verifying rule), `CONTRIBUTING.md` (the copyright
   position dual licensing depends on) and `COMMERCIAL-LICENSE.md` (the commercial-licence
   contact). These are legal instruments and their operative companions, not human narrative:
   their audience-of-record is a licensee, their content is normative rather than explanatory,
   and no `procedure:` block in a contract can carry them, because a licence must sit where a
   licensee looks for it. Their consistency is machine-checked by
   `validate_licence_consistency`, which is what keeps this class from becoming the
   unenforced-prose drift point 3 exists to prevent.
2. **`docs/runbooks/` is a retiring class.** Operator runbooks are human-audience prose by
   construction. The existing `docs/runbooks/ducklake-catalog-operations.md` is grandfathered
   (this Decision deletes nothing), but no new file may be added under `docs/runbooks/`; new
   operator procedures are `procedure:` blocks in the owning `docs/contracts/*.yaml` file (see
   point 3). `docs/CLAUDE.md`'s Class->home map is updated to drop the `docs/runbooks/` row.
3. **Enforcement -- `prose_allowlist`.** `docs/contracts/file-router.yaml` gains a
   `prose_allowlist` key (`allowed_globs` for the permanent classes above, `grandfathered_globs`
   for every currently-tracked `.md` file not otherwise covered -- seeded day-one, ratchet-only,
   may only shrink in a later plan, never grow). `scripts/checks/hygiene/validate_prose_allowlist.py`
   enforces it in both `validate.py` tiers (Decision 104 registry pattern), fail-open if the key
   is absent/unreadable. Its scope is repo-wide over every tracked `.md` file, distinct from (and
   may overlap, never conflict with) `validate_intent_doc_freeze`'s narrower ownership of whether
   a given `docs/INTENT-*.md` may still exist per the intent-migration manifest.
4. **Instruction-architecture anti-pattern.** `docs/contracts/instruction-architecture.yaml`
   gains an anti-pattern row: a human runbook / operator-prose doc belongs in a `procedure:`
   block in the owning contract, not as a standing prose companion doc.

**Rationale:**
Per Decision 86, rationale lives here, forward intent lives in tier_items (T2.41, re-grounded by
this Decision to no longer name a "runbook" target), and field/procedure semantics live in the
machine-readable contract (`docs/contracts/deploy-paths.yaml`'s new `admin_out_of_band.procedure`
block) -- no new standing prose-architecture doc is created by this Decision itself. This is a
deliberate expansion of Decision 86 from a negative rule (no NEW standing prose docs) to a
positive, enforced taxonomy (only agent-instruction prose is sanctioned at all), closing the gap
that let the Decision 120 break-glass procedure sit ambiently in Layer 1 for as long as it did.

**Reversal conditions:** none identified; a future plan (the B2 follow-on referenced in this
Decision's implementing plan) may pull the `grandfathered_globs` ratchet as owners retire their
classes, but that is additive tightening, not a reversal of the taxonomy itself.

**Related:** Decision 86 (expanded here from a negative new-doc rule to a positive taxonomy),
Decision 126 (point 4 amended below to name the `admin_out_of_band.procedure` target), Decision
120 (amended below to record the quarantine and its date), Decision 101 (point (c) marketing/
prose exception, carried forward as a permanent class here), Decision 104 (check-registry
pattern the new guard follows), Decision 84 (this Decision is authored in DECISIONS.md then
backfilled to `ops_decisions`, never written directly).

---

## Decision 126: Two-verb deployment model + heal button + operator-only admin tier (completing CD.35) (Decided)

**Status:** Decided
**Date:** 2026-07-11
**Warehouse ID:** dec-126 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The CD.35 apply pipeline (Decisions 77/92/119/120, T2.20-T2.25/T2.35) is control-theoretically
sound -- no-TOCTOU plan/apply identity, a fail-closed guard with an authority budget, anti-masking
convergence -- but the target deployment MODEL was never written down as a single citable surface.
It is smeared across 6+ documents (AGENTS.md, terraform/CLAUDE.md, environment-taxonomy.md,
build-lambda.yaml, PROJECT_CONTEXT.md, DECISIONS.md itself), two of which went stale after #544
(environment-taxonomy.md section 5 and build-lambda.yaml still described the four DuckLake
functions as coupled after the decoupling landed), and the best-documented path through that smear
is the local-apply escape hatch (Decision 120), because it is the one path with no missing verb to
route around. The concrete failure mode this produces: an agent facing "I need to deploy code" or
"the pipeline is red" has no ambient, authoritative answer for what to do, and improvises toward
whichever surface it happened to read -- which is disproportionately the escape hatch, not because
it is the sanctioned path but because it is the most visible one. rec-2646 demonstrated the
governed-channel scope evaporating when its rec closed on grep-acceptance alone, with no roadmap
tracker to catch the loss (the failure mode this Decision's tier_items are designed not to repeat).

**Decision:**
1. **The model.** Agents have exactly three intents, each with exactly one trigger:
   - **provision** (infra changes): edit `terraform/**`, open a PR; CI plans and applies (Decision
     77/92/119). No agent self-directs a `terraform apply` for this intent -- CI applies it.
   - **deploy code**: the governed code-deploy channel (T2.38 for the four DuckLake Lambdas).
     Terraform is not involved -- code ships via a build/deploy pipeline scoped to
     `UpdateFunctionCode`-equivalent permissions only.
   - **reconcile** (the pipeline is red or drifted): one input-free Reconcile action (T2.37) that
     reads the red commit from the convergence record and re-applies it -- no operator-supplied SHA,
     no manual triage step for the common case.
   Plus an **operator-only admin tier**: bootstrap root and `agent_platform_admin` IAM/trust/destroy
   changes are human-only -- an agent's only move there is to file a rec describing what's needed
   and why. The Decision 120 local-apply escape hatch is a narrower carve-out within this same
   tier: a human-gated interactive loop where an agent may execute `terraform apply` only after a
   human has reviewed the plan and explicitly directed it -- never self-directed, never the default
   path for any of the three intents above.
2. **Invariants:**
   - Agents never self-direct a `terraform apply`; operators may always invoke it directly, and an
     agent may execute it only within the human-gated break-glass admin tier below (Decision 120
     restored this for IAM/trust/destroy changes that guard-BLOCK the CD pipeline and for
     hand-applied recovery; Decision 98 admin-create; Decision 77 bootstrap -- none of that is
     revoked by this Decision).
   - The escape hatch's danger is that it is AMBIENT (the best-documented, most-reached-for path),
     not that it exists. The fix is demotion and eventual quarantine to an operator-only runbook,
     never deletion of the operator's only working recovery mechanism.
   - The heal button (T2.37) MUST land and be verified BEFORE the escape hatch is quarantined
     (T2.41) -- removing the only working recovery path before its replacement is proven turns the
     next incident into a hard outage. T2.41 `depends_on: [T2.37]` in the roadmap encodes this.
   - `docs/contracts/deploy-paths.yaml` is a navigation index pointing to
     `environment-taxonomy.md` for apply-model / guard-classification rules (Decision 92 point 5
     sole-SoT); it is never a second source of truth for those rules (Decision 86 no-drift).
3. **Amends Decision 125 point 5.** Point 5 recorded the four DuckLake Lambdas (writer, reader,
   maintenance, catalog-dr) as an interim-COUPLED, not-yet-conformant state pending a follow-on.
   #544 (commit 32a00616) landed that follow-on: every `aws_lambda_function` resource in
   `terraform/personal/ducklake_lambdas.tf`, `ducklake_catalog_dr.tf`, and `ducklake_maintenance.tf`
   now carries `lifecycle { ignore_changes = [source_code_hash] }`. The interim-COUPLED framing in
   Decision 125 point 5 is superseded by this realized state; `environment-taxonomy.md` section 5
   and `build-lambda.yaml`'s `channel_class` are corrected to DECOUPLED in the same PR that ratifies
   this Decision. The governed code-deploy CHANNEL Decision 125 point 2 named as the target is still
   pending -- that is T2.38, not yet realized by #544's physical decoupling alone.
4. **Amends Decision 120.** The local-apply escape hatch Decision 120 restored (the ADMIN
   container's interactive human-gated apply loop, `terraform/CLAUDE.md` "Interactive loop
   fallback") will be quarantined out of the ambient dev-loop doc once the heal button (T2.37)
   lands and is verified -- tracked by T2.41 (`depends_on: [T2.37]`). Decision 120's restoration
   itself is not reversed; only its documentation surface moves from ambient to a quarantined
   location reachable via `deploy-paths.yaml`'s `admin_out_of_band` pointer.
   **Amended 2026-07-13 by Decision 127:** the quarantine target is re-grounded from "a
   dedicated operator-only runbook" to the structured `admin_out_of_band.procedure` block added
   directly to `docs/contracts/deploy-paths.yaml` (Decision 127's sanctioned-prose taxonomy
   retires `docs/runbooks/` as a growth class) -- T2.41 landed against this target, not a new
   runbook file.
5. **Sequencing / roadmap.** Six new tier_items carry the engineering this Decision's foundation
   points at: T2.37 (heal button: input-free Reconcile), T2.38 (governed code-deploy channel +
   deployment record for the four DuckLake functions, realizing Decision 125's deploy verb), T2.39
   (take the non-deterministic LLM plan-review subagent out of the red-latch path -- forward-fix for
   rec-2658), T2.40 (this Decision's own navigability + SoT-integrity foundation -- deploy-paths.yaml,
   the AGENTS.md ambient rule, the terraform/CLAUDE.md decision table, the conformance staleness
   guard -- closed by the same plan that authors this Decision), T2.41 (escape-hatch quarantine,
   `depends_on: [T2.37]`, amends Decision 120), T2.42 (terraform-path hardening: layer replace
   policy, committed lock file, content-addressed zips, deduped build-step bash).

**Reversal conditions:** re-evaluate the bespoke two-verb/heal-button pipeline against a managed
reconciler (e.g. a hosted GitOps/Terraform-Cloud-class product) if the bespoke pipeline proves
unmaintainable at this scale -- any such re-evaluation must be scoped against the Decision 101
confidential-data boundary (personal AWS account credentials/ARNs never leave the gitignored/
Secrets-Manager surface) before a managed third party is considered.

**Rationale:**
A Fable (frontier) design review of the CD.35 pipeline concluded the control theory is
frontier-grade -- the gaps are recovery ergonomics, the missing deploy verb, and documentation
topology, not the apply architecture itself. This Decision records the target model once, in one
citable place, so the follow-on engineering (T2.37-T2.42) has a fixed point to build toward instead
of each landing its own ad hoc framing. Per Decision 86, rationale lives here; forward intent lives
in the tier_items; field semantics live in the `deploy-paths.yaml` machine-readable contract -- no
new standing prose-architecture doc is created. This is a fresh forward-direction Decision, not a
candidate CD, because the model it records is not yet realized end-to-end (Decision 87 precedent:
the CD->Decision lane, Decision 105, is for ratifying already-realized CDs, which this is not).

**Related:** Decision 125 (amended point 5, above), Decision 120 (amended, above), Decision 92 point
5 (apply-model / guard classification -- sole SoT, unmodified by this Decision), Decision 86
(rationale-routing / no new prose-architecture doc), Decision 98 (admin-create provisioning),
Decision 77 (bootstrap + sandbox auto-apply + deterministic guard), Decision 55 (RCA-first; no
inline-patching of the ci-rca recs this Decision defers -- rec-2658 forward-fixed by T2.39),
Decision 104 (the conformance staleness guard registers via the check registry), Decision 105 (the
candidate-decision ratification lane -- not used here; see Rationale), Decision 79 (per-Lambda
build/deploy/smoke-test gating that T2.38's governed channel extends), Decision 101 (public-content
boundary -- `deploy-paths.yaml` names roles by logical name only, no account IDs/ARNs/ExternalIds),
Decision 118 (free-form registry precedent for a non-ritual contract -- `deploy-paths.yaml` carries
no `contract:`/`class:` block), Decision 72 (architectural-review vehicle for a recurring ci-rca
class -- this Decision is that vehicle for rec-2658).

---

## Decision 125: Ratify decoupling DuckLake Lambda code deploys from terraform/personal infra apply (environment-taxonomy.md section 5 conformance) (Decided)

**Status:** Decided
**Date:** 2026-07-10
**Warehouse ID:** dec-125 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`docs/contracts/environment-taxonomy.md` section 5 already prescribed, as a load-bearing rule,
decoupling personal-account Lambda code deploys from `terraform/personal` infra applies (`lifecycle
{ ignore_changes = [source_code_hash] }`, code via a build pipeline, infra via Terraform) -- but
recorded "(No such Lambda exists today; recorded here so the first one follows the principle.)". The
four DuckLake Lambdas (writer, reader, maintenance, catalog-dr; T2.17/T2.18, Decision 81/82) are that
first case, and they never followed it: `source_code_hash = try(filemd5(zip), null)` on every
`aws_lambda_function` resource still couples code to infra apply. The concrete cost of the gap
surfaced as routing/stranding evidence: a code-only wave-3 change was routed (and then stranded) by
an unrelated out-of-budget IAM delta (`github_ci_drift` policy UPDATE) in the same
`terraform/personal` root module -- `workflow_dispatch` has no gated-apply path (gated-apply is
push-only), so nothing applied and the four functions still run pre-wave-3 code as of this Decision.
Agents also default to the local `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy`
break-glass step as if it were the routine channel, because no ambient (Layer 1) signal names a
governed CD path to check first.

**Decision:**
Ratifies conformance direction, not the physical decoupling itself (sequenced as follow-on P2, see
below):
1. The DuckLake Lambdas are recorded as the first personal-account Lambdas under section 5's
   principle -- the stale "no such Lambda exists today" premise is corrected in the same PR that
   ratifies this Decision.
2. Target channel: a dedicated, governed code-deploy CD path (extending `.github/workflows/deploy.yml`
   if it already deploys Lambda code by the time P2 lands, else a new workflow) is the CHANNEL for
   DuckLake Lambda code deploys going forward. `environment-taxonomy.md` section 5 remains the SOLE
   SoT for the apply-model / guard classification (Decision 92 point 5); this Decision does not
   restate or amend that classification, only ratifies conformance to it.
3. Local `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` is demoted to a
   break-glass / admin-IAM-path step only (i.e., used only when the governed CD channel cannot run,
   mirroring the existing `agent_platform_admin` human-gated IAM-apply precedent) -- not the default
   agent action for a routine code-only change.
4. Ambient heuristic: when a production action (e.g. a Lambda code deploy) is auto-denied or has no
   obvious in-session path, grep `.github/workflows/` for a governed CD path before falling back to a
   local permission grant or a local deploy command.
5. Interim state (until P2 lands): the four DuckLake Lambdas remain coupled
   (`source_code_hash=try(filemd5(zip),null)`); this is recorded as a known, tracked gap, not silently
   accepted as permanent.

**Reversal conditions:** revisit this Decision if (a) the DuckLake Lambdas are retired or replaced by
a mechanism that makes per-function code/infra decoupling moot (e.g. a container-image deploy model
where the image digest itself is the infra-tracked artifact), or (b) `environment-taxonomy.md` section
5's decoupling principle is itself superseded by a future Decision -- in either case this Decision's
ratification becomes vacuous and should be marked superseded rather than silently ignored.

**Rationale:**
Decoupling code from infra apply is industry-standard practice for exactly the reason the routing/
stranding incident demonstrated concretely: coupling means a routine code-only change can be silently
blocked by an unrelated infra-apply gate (here, an IAM guard routing decision) with no independent
channel to land the code anyway. Ratifying conformance as a numbered Decision (rather than leaving it
as an unenforced contract note) makes the correction citable per the Decision 86 rationale-routing
rule -- the "why we're fixing this now" lives here, the "what the target architecture is" stays in
`environment-taxonomy.md` section 5 (unchanged, extended only with the conformance note), and the
physical implementation is tracked as an explicit follow-on so this Decision does not overstate what
landed in the ratifying PR (comment-only `.tf` edits; zero resource/lifecycle/IAM delta).

**Related:** Decision 92 point 5 (apply-model / guard classification -- sole SoT, unmodified by this
Decision), Decision 77 (sandbox auto-apply + deterministic guard, the mechanism section 5's decoupling
protects), Decision 79 (per-Lambda packaging manifests + deploy/verify gating -- the build/deploy
mechanics this Decision's target channel extends), Decision 119 (CI-delegation for `terraform/personal`
-- the target channel's plan/apply steps stay CI-delegated, not local), Decision 86 (no new standing
prose-architecture doc; this Decision is the rationale record, `environment-taxonomy.md` stays the
sole classification SoT), Decision 55 / Decision 72 (RCA-first; the physical decoupling and the
masked-drift observability gap are follow-on recs, never inline-patched here).

> **Update (2026-08-13):** `docs/contracts/environment-taxonomy.md` (this Decision's own title
> parenthetical, unedited per Decision 149 never-remove-headers) was converted to the declared
> Class D contract `docs/contracts/environment-taxonomy.yaml` (CFG-11 conversion, per Decision
> 168's Class D mechanism). Section 5's conformance-status content is now the typed
> `conformance.ducklake_class` / `conformance.prod_class` fields; the content this Decision
> ratifies conformance to is unchanged -- only the file format and path changed; cite
> `docs/contracts/environment-taxonomy.yaml` going forward.

---

## Decision 124: Ratify extending the Decision 80 pt 3 / Decision 104 facade-decomposition pattern to the ops-data layer (Decided)

**Status:** Decided
**Date:** 2026-07-10
**Warehouse ID:** dec-124 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 159 (2026-07-30):** the coverage-gate mapping bullet's premise -- "on
> main post-merge the merge-base diff is empty so it no-ops" -- is corrected: `push_context_base()`
> now supplies a real post-merge diff base. The `scripts/ops_portal/**` carve-out itself is
> UNCHANGED -- verified by Decision 159's VP step 7. Body otherwise unedited; see Decision 159.

**Problem:**
scripts/ops_data_portal.py is the Single Portal write gateway and had accreted the entire
source=ci_rca structured-context subsystem, the DuckLake writer transport, risk scoring,
write-time validators, decision CRUD, maintenance verbs, and a 277-SLOC argparse CLI -- 1774
SLOC (budget 1800, 26 headroom, Decision 102). One-concern-per-module extraction behind a
behaviour-preserving facade is the structural fix, exactly as ratified for validate.py
(Decision 80 pt 3 / Decision 104).

**Decision:**
Ratifies the facade-decomposition pattern for the ops-data layer, mirroring Decision 104 with
one addition -- a patch-interception hybrid:
- scripts/ops_data_portal.py collapses to a thin facade (383 SLOC) that KEEPS DEFINED the
  patch-epicentre (file_rec, update_rec, propose_or_close_rec, _fetch_rec_from_reader, sync,
  get_ci_rca_strict_mode) so the majority of existing test patch sites need zero change; it
  imports every test-patched private dependency into its own namespace so
  `patch("scripts.ops_data_portal.<sym>")` keeps intercepting for facade-resident callers; and
  it re-exports every public symbol plus the 6 imported-name traps (subprocess, ET,
  DECISIONS_JSONL, RECS_JSONL, Recommendation, validate_source) and the
  _fetch_decision_from_athena back-compat alias.
- Ten new scripts/ops_portal/*.py modules, one concern each: _common (shared ROOT/profile/
  region primitives, Decision 104 precedent), ci_rca_schema (CiRcaContext/CiRcaEvidenceDispute
  models + shape validators), ci_rca_runtime (write-time cross-check + back-validation,
  carries the decision-43 waiver), writer_transport (DuckLake writer SigV4 transport),
  risk_scoring (risk/automatable derivation), write_validators (write-time content checks),
  cache (local read-cache refresh), decisions (ops_decisions CRUD + DECISIONS.md ETL),
  maintenance_ops (selftests, bulk-enqueue, postmortem maintenance), cli (argparse surface,
  carries the decision-43 waiver).
- Patch-interception hybrid (the addition Decision 104 did not need, since validate.py's
  extracted checks are called only through the registry dispatch loop): a private symbol
  moved to a submodule is patch-reachable at one of two namespaces depending on the calling
  context -- (a) via the facade, when the driving caller is one of the six facade-resident
  functions (which read the symbol as their own module global, since it was imported into the
  facade namespace); or (b) via the submodule that holds its own bare-imported copy, when the
  driving caller has ALSO moved to a submodule (e.g. file_decision/update_decision/
  backfill_decisions_from_md moved to decisions.py, so tests patching _ducklake_write/
  DECISIONS_JSONL/_load_write_time_validators/_fetch_decision_from_reader while driving those
  three functions target scripts.ops_portal.decisions.<sym>, not the facade). Cross-module
  calls FROM a submodule TO a facade-resident function (file_rec/update_rec/
  _fetch_rec_from_reader/get_ci_rca_strict_mode) use a function-local deferred import inside
  the calling function, both to avoid a module-load cycle and so a facade-level patch of that
  target is picked up at call time.
- Coverage-gate mapping is DELIBERATELY NOT extended: scripts/test_coverage_checker.py's
  map_source_to_test leaves scripts/ops_portal/** unmapped (returns None -> skipped), identical
  to how scripts/executor/** and scripts/verifiers/** are already treated. The per-file 100%
  gate is full-tier + diff-gated only (registry.py's full_sequence(), not pre_sequence()), and
  on main post-merge the merge-base diff is empty so it no-ops; extending the mapping would
  create an unsatisfiable full-tier requirement, since the CI-RCA subsystem's tests are spread
  across ~10 files (test_ops_data_portal.py plus test_ci_rca_*.py / _decisions / _validators)
  and no single test file covers a whole portal region -- consolidating those is a test
  reorganisation outside a behaviour-preserving code move. Deferred, not resolved.
- check_source_registry.py (scripts/checks/ops_governance/) is extended to also scan
  scripts/ops_portal/*.py for hardcoded source string literals, so the two literals that moved
  out of the facade (ci_rca_warn_period_audit -> ci_rca_runtime.py, manual ->
  maintenance_ops.py) stay validated against source_registry.yaml.
- .importlinter's no-cycles-ops-data-portal-executor contract gains scripts.ops_portal as a
  layer strictly between scripts.ops_data_portal and scripts.executor, with three new
  ignore_imports entries (scripts.ops_portal.maintenance_ops / ci_rca_runtime / cli ->
  scripts.ops_data_portal) mirroring the existing scripts.executor.jsonl_store carve-out --
  the deferred-import mechanism above is invisible to import-linter's static layers check, so
  each submodule making such a call must be named explicitly.
- Decision 123 / T1.5 / CD.10 coordination: this mechanical, behaviour-preserving facade split
  is NOT in conflict with Decision 123's revival of the stashed agent/ops-decisions-phase-2 WIP
  inside T1.5. T1.5 is strategic=true and status=not_started, frozen by Decision 67 (STRATEGIC
  suspended) -- not imminent. The facade preserves the exact agent surface
  (scripts.ops_data_portal.file_rec/update_rec/file_decision), so the stashed WIP's
  ops_decisions semantic-definition content and T1.5's eventual import-site sweep (to agent_sdk
  verbs, CD.10) rebase onto the new scripts/ops_portal/ layout rather than the 1774-SLOC
  monolith -- a better base, not wasted investment.

**Rationale:**
The patch-interception hybrid is the load-bearing difference from Decision 104's registry-
dispatch design: ops_data_portal.py's public functions are called directly by ~130 test call
sites and by every other module in the repo that files or updates a recommendation, so a
functions-only re-export (missing the 6 imported-name traps, or missing a re-import of every
test-patched private dependency) would silently break `patch("scripts.ops_data_portal.<sym>")`
at whichever of the two namespaces the calling code actually resolves it from -- a class of bug
the interception audit in this decomposition surfaced concretely (a facade-level patch of
_resolve_writer_url does not affect _ducklake_write's own resolution, since both live in
writer_transport.py; a facade-level patch of ROOT does not affect the CI-RCA evidence-bundle
loader, since it lives in ci_rca_schema.py). Naming the calling module's own namespace as the
patch target, rather than the symbol's origin module, is what test_ops_data_portal_decisions.py
and the equivalent sites in test_ops_data_portal.py now do.

**Related:** Decision 104 (direct precedent -- facade re-exports of public + test-patched
private symbols, coverage-gate mapping choice), Decision 102 (SLOC ratchet; --update-sloc-
budgets re-point, applied to every new scripts/ops_portal/** module), Decision 80 (tool-free
decomposition direction; pt 2 governs the .importlinter layer this extends), Decision 43
(500-SLOC + CC<=20; the decision-43 waiver travels into cli.py and ci_rca_runtime.py), Decision
86 (no new standing prose-architecture doc -- this Decision is the sole record of the
patch-interception-hybrid rationale), Decision 91 (verb routing preserved unchanged), Decision
103 (propose_or_close_rec home -- stays in the facade), Decision 66 (get_rec_write_guidance
callable before file_rec -- preserved in cli.py's --guidance branch), Decision 70 (purge stays
private; no public delete_rec introduced), Decision 84/55 (read-cache-only + loud-fail
preserved unchanged), Decision 123 / CD.18 / T1.5 / CD.10 (coordination note above -- this
facade is the intermediate the eventual import-site sweep rebases onto).

---

## Decision 123: Ratify CD.18 -- revive the stashed agent/ops-decisions-phase-2 WIP into T1.5's Phase-2 decomposition (Decided)

**Status:** Decided
**Date:** 2026-07-06
**Warehouse ID:** dec-123 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.18 (promoted from KG.6) required a decision before T1.5 begins on the fate of the
stashed agent/ops-decisions-phase-2-semantic-definition WIP (scripts/ops_data_portal.py,
scripts/executor/rec_write_guidance.py, tests/test_ops_data_portal_decisions.py). CD.10 dismantles
ops_data_portal as the agent surface, raising the question of whether the stashed WIP still fits the
current architecture.

**Decision:** Ratifies CD.18 option (a) -- revive the stashed work and land it inside T1.5's strategic
decomposition; its semantic-definition content directly serves Phase 2 semantics and preserves prior
planning effort.

**Reversal conditions:** if, during T1.5 decomposition, the revived WIP proves unfittable to the
current Lambda-handler / named-verb architecture (CD.10 dismantled ops_data_portal as the agent
surface), void it and re-derive Phase-2 semantics fresh per CD.18 option (b); record the reversal as
an amendment to this Decision.

**Related:** CD.18 (this ratifies it), T1.5 (gated item; this decision unblocks its start), Decision
84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision ratification lane).

---

## Decision 122: Ratify CD.28 -- executor LLM inference = DeepSeek-direct via LiteLLM (Tier 1), Anthropic-direct (Tier 2); Bedrock retired (as amended by Decision 116) (Decided)

**Status:** Decided
**Date:** 2026-07-06
**Warehouse ID:** dec-122 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:** CD.28 was operationally realized (DeepSeek + Anthropic keys live in Secrets Manager --
T0.4 c1-c3 met, LiteLLM smoke tests 200 on 2026-06-21; Bedrock code paths retired; inference-provider.yaml
v1 reflects the CD.28 tier model) but remained `state: pending`, gating completion of T0.4 and T4.1-T4.4.

**Decision:** Ratifies CD.28 AS AMENDED BY Decision 116. Executor LLM inference steady state --
Tier 1 = DeepSeek-direct via LiteLLM (deepseek/deepseek-chat, deepseek/deepseek-reasoner; remapping to
deepseek-v4-flash post-2026-07-24); Tier 2 = Anthropic-direct via LiteLLM (warm-fetched escape hatch,
Max x5 programmatic pool); Tier 3 = OpenRouter (deferred). Bedrock retired from the architecture as an
LLM substrate. Scheduled-agent provider routing is governed by Decision 116's split (routine/non-agentic
-> LiteLLM Tier 1; judgment/agentic -> claude -p), NOT CD.28's original blanket scheduled-agent clause.

Layer reconciliation (Decision 121): the tier model governs the EXECUTOR LiteLLM inference transport
(scripts/llm_client.py, repointed by T4.2). The current model_registry._VALID_PROVIDERS = {"gemini"} /
llm_client._gemini_call is the INTERIM executor transport pending T4.2's LiteLLM cutover, which OWNS its
removal (T4.2 files_in_scope scripts/llm_client.py "rewrite to LiteLLM transport; remove Bedrock +
Gemini-CLI paths"; T4.2 exit criterion "LiteLLM is the only LLM transport"). Decision 121's "Gemini is
the sole valid provider" describes that interim state, not a permanent commitment -- no contradiction.

**Reversal conditions:** revert/re-evaluate if (a) DeepSeek direct API pricing changes >5x in either
direction, or (b) the Anthropic Max x5 programmatic pool is sustained >70% utilization over 30 days
(file a rec to provision an org-billed Anthropic API key as overflow). Mirrors
`cost_projection.reevaluation_triggers`.

**Related:** Decision 116 (scheduled-agent provider split; amends CD.28's scheduled-agent clause),
Decision 49 (superseded by 116; Copilot SDK retirement), Decision 121 (model_registry interim Gemini
state; layer reconciliation), Decision 47 (lock-in lesson; Anthropic-direct preserves the warm-fetched
escape hatch), Decision 84 (DECISIONS.md canonical + portal backfill), Decision 105 (candidate-decision
ratification lane). Supersedes: CD.7 (LLM-on-Bedrock primary), Decision 40 (Copilot SDK + Bedrock
planning).

[Amendment 2026-08-03: Decision 164 records the rationale this entry's executor/scheduled routing
split rests on -- why T4.2's agentic personas route to these LiteLLM tiers even though Decision
116's agentic criterion reaches them on its face -- and records the substrate-set collapse a reopen
would cause. Audit finding ESB-03. No tier, provider, or reversal condition in this entry changes.]

[Amendment 2026-08-19: Decision 173 converts this entry's tier model from vendor-anchored to
ROLE-based. Tier 1 and Tier 2 name the primary and warm-fetched-fallback ROLES; DeepSeek-direct and
Anthropic-direct are recorded here as the then-current selections and as EXAMPLES of that mechanism,
not as architecture. The model ids and provider values now live in
docs/contracts/inference-provider.yaml (model_id_formats.litellm_tier_models, the sole home), and
this entry's >5x-price and >70%-pool reversal conditions are re-keyed there onto the PRIMARY role's
metered unit price and the FALLBACK role's fixed-non-rollover allowance. A contract edit may not
fill a role from retired_providers, and may not fill both roles from one vendor. Nothing else in
this entry changes: LiteLLM as the sole Layer-1 inference surface, Bedrock's retirement, and the
Decision-121 layer reconciliation stand.]

---

## Decision 121: Retire docs/contracts/cli-json-output.md rather than convert it -- T-1.17 exempted from the CD.25 conversion wave (Decided)

**Status:** Decided
**Date:** 2026-07-05
**Warehouse ID:** dec-121 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
`docs/contracts/cli-json-output.md` documented the GitHub Copilot CLI `--output-format=json`
schema. Its parser, `scripts/copilot_wrapper.parse_jsonl_output`, exists nowhere in the tree; its
home, `scripts/copilot_wrapper.py`, was deleted in commit 6a2f7c0 ("retire Copilot-SDK residue");
and the doc's own cited replacement, `scripts/bedrock_client.py`, never existed (bedrock retired
per CD.28 -- `model_registry._VALID_PROVIDERS = frozenset(["gemini"])`, Gemini is the sole valid
provider). The doc also carried a false premise, corrected in the same session: it claimed
`scripts/llm_utils.py` parses CLI JSON output, but `llm_utils.py` never did -- only process-safety
helpers were relocated there; the parser stayed in `copilot_wrapper.py` until its deletion.

Per Decision 86 (rationale for retiring a prose contract belongs in a numbered Decision, not a new
prose doc) and dec-118 / Decision 118 ("necessary NOT sufficient" -- CD.25 ratifying the pre-codegen
contract ritual mechanism does not itself close every per-item exit criterion), this Decision retires
the contract outright rather than converting it to YAML under T-1.17's original exit criteria.
T-1.17 (`docs/ROADMAP-PLATFORM.yaml`) is closed by explicit exemption -- the Known Gap #7 branch in
`docs/INTENT-pre-codegen-contract-ratification.md` ("keep as markdown / retire, unenforced" is a
valid outcome) -- rather than by landing the YAML conversion + `llm_utils.py` wiring its original
exit criteria described. No `bootstrap_completion_exempt` flag is set on T-1.17: it was gated
solely by CD.25, and dec-118 (Decision 118, 2026-07-03) already stripped that flag for the whole
CD.25-solely-gated subset when CD.25 ratified (`docs/ROADMAP-PLATFORM.yaml` lines ~116-124); this
closeout completes after CD.25's ratification, not ahead of it, so the exemption flag does not
apply here -- the flag's absence is deliberate and consistent with the existing
`test_live_platform_yaml_bootstrap_exemption_set` regression test, not an oversight.
`docs/INTENT-pre-codegen-
contract-ratification.md`'s conversion-table row and embedded T-1.17 replica are corrected in the
same session to strike the false `llm_utils.py` premise and mark the original conversion proposal
superseded-by-retirement. rec-146 (doc-improvement rec targeting the now-deleted file) is closed via
the ops portal as `stale_target`, with the deletion recorded as closure proof (Decision 103 --
recommendation relevance is a governed lifecycle state; a physically-absent target file is
deterministic `stale_target`, not a bare semantic assertion).

The live CLI-JSON parser today is `scripts/llm_client.py:_gemini_call`, which parses the Gemini CLI
`--output-format stream-json` schema (`init`/`message`/`result` events) -- a different vendor schema
from the retired Copilot one, currently undocumented by any contract and out of this Decision's
scope.

**Reversal conditions:** revisit only if a CLI-JSON boundary matching the retired Copilot schema is
reintroduced (e.g. a future Copilot CLI integration). In that event, restore
`docs/contracts/cli-json-output.md` from git history (or author a fresh contract against the live
schema at that time) and supersede this Decision.

**Related:** Decision 86 (retire prose contract; rationale lives in a numbered Decision), Decision 84
(DECISIONS.md canonical + portal backfill; Single-Portal Invariant), dec-118 / Decision 118 (ratifies
CD.25 -- "necessary NOT sufficient", sanctioning this per-item exemption closeout), Decision 103
(recommendation relevance governed lifecycle -- `stale_target` closure semantics for rec-146).
Related: Decision 116 / Decision 117 (the ULF-05 Copilot-SDK retirement session that deleted
`scripts/copilot_wrapper.py` and corroborates the dead path this Decision retires the doc for).
Provenance (archived context, not a live governing decision): Decision 52 (`docs/DECISIONS_ARCHIVE.md`
-- the original Bedrock/Copilot architecture this contract predates).

---

## Decision 120: Adopt the S3-backed provider filesystem_mirror as the realized Decision 119 reversal mechanism (Decided)

**Status:** Decided
**Date:** 2026-07-04
**Warehouse ID:** dec-120 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Decision 119 named an S3-backed `provider_installation` `filesystem_mirror` as its explicit reversal
condition (rec-2514). That mechanism is now realized: `.github/workflows/terraform-provider-mirror-seed.yml`
(the only egress-having actor in this architecture) runs the native `terraform providers mirror`
subcommand (Decision 100 managed-service-native discipline -- not a hand-rolled fetch/verify script)
on a GitHub-hosted runner and publishes the resulting tree to
`s3://agent-platform-data-lake/tf-provider-mirror/`. `bin/setup-cloud-env.sh` syncs that prefix to
`$HOME/.terraform-mirror/` on the admin (PlatformAdmin) container and resolves
`config/terraform/cc-web.tfrc`'s `__TF_MIRROR_DIR__` placeholder into a local copy pointed at by
`TF_CLI_CONFIG_FILE`, gated on the sync being non-empty (an empty/failed sync must not export a
config that excludes `kislerdm/*` from `direct` with nothing in the mirror to serve it instead).
With the mirror synced, `terraform init` of `terraform/personal` succeeds locally in a proxy-blocked
CC-web container (including ADMIN, same session class per Decision 119) without the github.com
checksum fetch that Decision 119 documented as permanently 403ing.

This RELAXES, but does not REMOVE, the CI-delegation Decision 119 established: `validate`/`plan`/`apply`
for `terraform/personal` in the routine (non-admin) CC-web flow remain CI-mediated (the required
`terraform-validate` job, Decision 83; the speculative-plan + apply-the-saved-plan pipeline, Decision
77 / Decision 92) -- that pipeline is the authoritative, always-available path and is unaffected by
whether any given admin container happens to have a fresh mirror sync. What changes is that the
ADMIN container's interactive human-gated apply loop (terraform/CLAUDE.md "Interactive loop
fallback"), previously unusable for `terraform/personal` per Decision 119, is now available again for
the cases that loop exists for: IAM/trust/destroy changes that guard-BLOCK the CD pipeline (Decision
94 escape hatch) and any hand-applied recovery. The IAM write needed to publish to the new
`tf-provider-mirror/` S3 prefix required NO new grant: `github_ci_apply`'s existing `DataLakeObjectIO`
Sid already covers `s3:GetObject/PutObject/DeleteObject` on the whole `agent-platform-data-lake`
bucket (verified before implementation, not assumed) -- so no out-of-band IAM change accompanies this
Decision.

**Reversal conditions:** if the S3 mirror sync stops being maintained (the seed workflow is retired,
or the mirror silently drifts stale against `.terraform.lock.hcl`'s `h1:` hashes), `bin/setup-cloud-env.sh`'s
gate-on-non-empty-sync fails closed to the pre-mirror posture (`TF_CLI_CONFIG_FILE` unset) and
Decision 119's CI-delegation guidance is the sole path again -- no code change is required to revert,
only ceasing to seed the mirror.

**Amended 2026-07-13 by Decision 127 (quarantine record):** the ADMIN container's interactive
human-gated apply loop this Decision restored for `terraform/personal` (the "Operator-only /
break-glass" subsection of `terraform/CLAUDE.md`) was quarantined out of that ambient Layer-1
doc into `docs/contracts/deploy-paths.yaml`'s `admin_out_of_band.procedure` block on 2026-07-13,
per the Decision 126 point 4 sequencing (T2.37 heal button landed and verified first, then T2.41
quarantined this procedure). This Decision's restoration of the loop itself is unaffected --
only its documentation surface moved.

**Related:** Decision 119 (the constraint this realizes the reversal condition for), Decision 100
(managed-service-native discipline -- native `terraform providers mirror`, not a hand-rolled script),
Decision 86 (rationale lives in a numbered Decision, not a new prose doc), Decision 77 (present-before-apply;
unchanged -- this Decision does not pre-authorize any apply), Decision 92 / Decision 94 (the gated-apply
/ admin-apply-as-escape-hatch framing this mechanism restores local init for), Decision 83 (the
required terraform-validate CI job, unaffected), Decision 55 (honest convergence -- no force-write of
any record; the mirror is purely an init-time enabler), Decision 127 (the quarantine + sanctioned-
prose taxonomy recorded above).

---

## Decision 119: CC-web session-class constraint -- third-party terraform provider init is github.com-egress-blocked; validate/plan for such roots is CI-delegated (Decided)

**Status:** Decided
**Date:** 2026-07-04
**Warehouse ID:** dec-119 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
In CC-web the outbound proxy scopes github.com to repo-scoped API calls, so `terraform init` of any
root using a third-party (github.com-hosted) provider (e.g. `kislerdm/neon` in `terraform/personal`)
permanently 403s fetching the provider's authentication checksums; HashiCorp providers
(releases.hashicorp.com) init fine. Therefore `terraform validate`/`plan` for third-party-provider
roots is CI-delegated verification, authoritatively enforced by the required terraform-validate job
(Decision 83) and the speculative-plan pipeline (Decision 77 / Decision 92). The local presubmit
degrades gracefully: `run_terraform_creds_free` emits a visible skip both when terraform is absent
AND when init hits the permanent proxy-403 (the prior green was incidental on terraform's absence,
since terraform is not installed by default in CC-web). Plan authors write local terraform VP steps
as grep-only (`terraform fmt -check` only when terraform is present); never a local terraform
validate/init/plan for third-party-provider roots.

**Reversal conditions:** if the CC-web session class later permits github.com provider-asset egress,
or an S3-backed `provider_installation` `filesystem_mirror` is adopted (deferred follow-up
recommendation), local init/validate becomes possible again and this delegation may relax.

**Related:** Decision 73 (two-tier presubmit -- local validate.py is advisory outside CI; PR CI is
authoritative), Decision 83 (the required terraform-validate CI job), Decision 92 / Decision 77 (the
speculative-plan + apply-the-saved-plan pipeline), Decision 86 (rationale lives in a numbered
Decision; terraform/CLAUDE.md and the planning SKILL carry enforcement/guidance only), Decision 104
(validate.py check registry -- terraform gate logic stays in scripts/checks/_scaffolding.py), Decision
55 (RCA-first / loud failure -- the proxy-skip predicate is a narrow co-occurrence check, never a
bare "403" substring, so it cannot mask a genuine non-github failure).

---

## Decision 118: Ratify CD.25 -- pre-codegen contract ratification ritual (scoped, necessary not sufficient) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-118 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.25, SCOPED to the realized ritual -- the pre-codegen contract ratification MECHANISM,
not a claim that every contract application is finished. The ritual is defined (T-1.11 landed
docs/INTENT-pre-codegen-contract-ratification.md, complete 2026-05-20) and ENFORCED in CI (T-1.12,
complete 2026-06-18: the scripts/contracts.py loader + $ref resolver; the scripts/validate.py
validate_contract_drift gate in BOTH the --pre and full tiers, covering CD.25 rejection categories
1-8; the scripts/session_preflight.py v0-provisional re-ratification scan; and the
decomposition-hints exemption-inheritance bookkeeping rule). The drift gate passes over 16 ritual
contracts spanning Class A (data schemas), Class B (the three DuckLake Lambda verb contracts --
docs/contracts/ducklake_writer.yaml / ducklake_reader.yaml / ducklake_maintenance.yaml, all at
provisional_v0), and Class C (cross-system invariants) -- so the ritual is live and mandatory, not
voluntary discipline. The CD.16 precondition ("Class B ratification unblocks on CD.16 ratification")
is satisfied via Decision 79 (dec-079). Ratification transits the shared candidate-decision
ratification lane (Decision 105) via the ops portal, superseding the dead "ratification happens once
the T0.7b log-decision Lambda is deployed" premise (2026-06-09 audit F-001; Decision 91).

Ratifying clears the COMPLETION gate CD.25 places on {T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7,
T1.12} and the decision_required_before "may start" gates on T0.13, T0.7a/b/c, T1.1, T1.3, T1.4,
and the T3.x telemetry verifiers -- necessary, NOT sufficient: it does NOT close those items' own
open code exit criteria, does NOT graduate the three provisional_v0 Class B contracts to ratified
(that lands later per each contract's re_ratification_trigger via the ULF-02 ratification lane), and
does NOT discharge exemptions for members still gated by another pending CD (T0.12.5 remains
CD.29-gated; T0.12.7 remains CD.10-gated). The CD.25-scoped bootstrap_completion_exempt subset's
termination event (roadmap agent_instructions scope (b): "Exemption ends at CD.25 ratification")
fires now; the flags on members gated solely by CD.25 are stripped in the same edit as this
ratification, per the Decisions 108-113 precedent and the flag-strip safety rule (strip only when
ALL gating CDs are ratified).

**Reversal conditions:** re-open as a candidate only if the pre-codegen contract ratification
ritual ceases to be the canonical mechanism -- e.g. docs/contracts/{name}.yaml stops being the
single canonical home for Class A/B/C field/verb/invariant semantics, or the validate_contract_drift
CI gate is removed so contracts no longer bind their code consumers.

**Related:** Decision 105 (the ratification lane executing this), Decision 86 (contracts are the
canonical machine-parseable home for field/verb semantics -- the discipline this ritual enforces),
Decision 79 / CD.16 (the satisfied Class B deploy-gating precondition), Decision 81 / CD.33 +
Decision 91 (the writer/reader/maintenance closed-boundary split the Class B contracts re-grounded
onto), Decision 84 (the portal ETL vehicle); T1.12 (the Class B contract wave whose completion this
ratification unblocks).

> **Amended by Decision 168 (2026-08-10):** extends the CD.25 ritual with a fourth contract class
> (Class D, mechanism contracts) gated on a declared, demonstrably-reading evaluator. This ritual's
> Class A/B/C scope is unchanged; see Decision 168 for the extension.

## Decision 117: Executor self-modification boundary -- capabilities.yaml is the code-level SSOT (Supersedes Decision 44) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-117 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Supersedes Decision 44. Restates the executor self-modification boundary: the executor must not
modify its own code, prompts, instructions, or tests. `config/agent/executor/capabilities.yaml`
(`boundary_patterns`) is named as the code-level single source of truth -- loaded by
`validate_executor_boundary()` in `scripts/validate.py` and `scripts/migrate_dq_ops_recs.py`.
`scripts/classify_automatable.py` carries a hardcoded duplicate list for the same purpose; both
were cleaned in the same session (ULF-05 audit closure) to drop the `copilot_wrapper.py` and
`tests/test_copilot_wrapper` boundary rows, since those files are deleted (ULF-05 Copilot-SDK
retirement). Enforcement mechanism (`validate_executor_boundary`, `select_next_batch` scope
checks) is unchanged from Decision 44 -- this decision only corrects which file is the named
authority and removes dead rows.

**Reversal conditions:** revisit if `classify_automatable.py`'s duplicate list drifts from
`capabilities.yaml` again without a lockstep fix, or if a future decomposition of the boundary
SSOT into multiple files reintroduces the sync-drift risk this decision closes.

**Related:** Decision 44 (superseded), Decision 116 (companion decision in the same ULF-05 audit
closure session), audits/unclosed-loops-44ef5c6.yaml ULF-05.

---

## Decision 116: Scheduled-agent provider routing -- routine/non-agentic agents to LiteLLM (DeepSeek), judgment/agentic agents to claude -p (Supersedes Decision 49; amends CD.28's scheduled-agent clause) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-116 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Supersedes Decision 49. Amends CD.28's scheduled-agent reconciliation clause (`docs/ROADMAP-PLATFORM.yaml`
candidate_decisions), which previously stated scheduled agents "also move to LiteLLM" as a blanket
rule. That blanket framing is replaced with a split using CD.28's own non-agentic/agentic
distinction:

- **Routine/non-agentic agents** (doc-freshness, orphan-code, code-smell) -- single-shot findings
  calls with no tool use -- route to LiteLLM Tier 1 (DeepSeek-direct), consistent with CD.28's
  standing "non-agentic LLM call site -> LiteLLM-only" rule.
- **Judgment-heavy agents** (rec-curator, transcript-review, prompt-quality) -- become AGENTIC
  (tool-using) via `claude -p` (Claude Code headless mode, Max-plan OAuth per the AGENTS.md
  `CLAUDE_CODE_OAUTH_TOKEN` runbook), and are thereby carved out of the non-agentic rule by CD.28's
  own text. `claude -p` additionally restores agentic tool use for these agents, retiring the
  `_preload_rec_curator_context` inline-data-injection workaround once the migration lands (the
  function itself is retained unchanged in this session; only its copilot-sdk/gemini call guard
  was removed since those providers are retired below).

As part of this decision, the `copilot-sdk` and `gemini` providers are RETIRED from the scheduled-agent
provider set effective this session: `scripts/copilot_sdk_client.py` and the handler dispatch
branches (`_invoke_copilot_sdk`, `_invoke_gemini`, `_get_gemini_api_key`) are deleted from
`src/data/handlers/scheduled_agent_handler.py`. An agent still declaring either provider in
`.github/agents/schedule.yaml` raises `RetiredProviderError`, which is caught locally and recorded
as a failed invocation (no silent misroute to `github-models`). Realization of the LiteLLM/claude -p
routing itself is owned by T4.3 / PLAN-resolve-scheduled-agent-provider -- this session retires the
dead provider paths and reconciles the roadmap text; it does not implement the new routing.
`.github/agents/schedule.yaml`'s six `enabled: true` flags are flipped to `enabled: false` to match
the deployed dispatcher's `SCHEDULED_AGENTS_ENABLED=false` reality (the schedule.yaml `enabled`
field previously lied about live dispatch state); `provider` fields are left unchanged (T4.3-owned).

**Reversal conditions:** revisit scheduled-agent provider routing on shared Anthropic Max-pool
capacity contention between executor Tier-2 and scheduled-agent `claude -p` usage, or on
cost_projection triggers documented in the CD.28 tier model.

**Related:** Decision 49 (superseded), CD.28 (amended -- scheduled-agent reconciliation clause,
PLAN-resolve-scheduled-agent-provider inventory entry, T4.3 intent line all updated in lockstep in
this session), Decision 52 (gemini BYOK deprecation, now fully retired rather than merely
deprecated), Decision 117 (companion decision in the same session), audits/unclosed-loops-44ef5c6.yaml
ULF-05.

[Amendment 2026-08-03: Decision 164 scopes this entry's agentic/non-agentic split explicitly to
scheduled agents. T4.2's executor personas are agentic tool-using loops by this entry's own
criterion but route to the Decision 122 LiteLLM tiers; Decision 164 records why, and records the
substrate-set collapse a reopen would cause. Audit finding ESB-03. No scheduled-agent routing in
this entry changes.]

[Amendment 2026-08-19: Decision 173 re-keys this entry's reversal condition off vendor identity:
"shared Anthropic Max-pool capacity contention between executor Tier-2 and scheduled-agent
claude -p usage" is read as contention on whatever FIXED, NON-ROLLOVER ALLOWANCE fills the executor
fallback ROLE, together with the scheduled-agent draw on that same allowance. The scheduled-agent
split itself is unchanged -- routine/non-agentic to the primary tier, judgment/agentic to
claude -p, realization still T4.3-owned -- and copilot-sdk and gemini stay retired: Decision 173
clause 2(a) forbids filling any tier role from retired_providers, so no contract edit can restore
them. A swap changing the vendor or billing shape under the coupling above re-arms this condition
and owes a further dated annotation here.]

---

## Decision 115: Transient handoffs ride PR descriptions; docs/handoffs/ pattern retired (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-115 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
The `docs/handoffs/` directory pattern (standing markdown files documenting in-flight
apply/migration state between sessions, e.g. `HANDOFF-ducklake-lambda-runtime-apply.md`) is
retired. Future transient handoffs split into two halves instead:

- **Ephemeral half** (what changed, what to verify, what's still pending) rides the PR description
  of the PR that created the handoff need -- visible to the next session via the PR's own history,
  with no separate file to go stale or require self-destruction instructions.
- **Durable half** (any exit criterion, decision, or contract implication that must survive past
  the PR) is captured directly in the plan's YAML (`docs/plans/PLAN-{slug}.yaml` acceptance
  criteria / context) or in `docs/ROADMAP-PLATFORM.yaml` exit criteria -- the structured,
  machine-parseable stores that are already the canonical persistence surfaces (AGENTS.md
  "Agent-First Repository" section).

No guard is added: this decision does not introduce a `validate.py` check forbidding new files
under `docs/handoffs/`, since the pattern is retired by convention (the directory's sole occupant,
`HANDOFF-ducklake-lambda-runtime-apply.md`, is deleted in this same session per its own
self-destruction instructions, and `docs/handoffs/` is now empty) rather than by mechanical
enforcement -- consistent with Decision 86's "no new standing prose-architecture docs" spirit
without adding a new enforcement surface for a directory that no longer has an intended use.

**Reversal conditions:** revisit if a future workflow demonstrates a genuine need for
handoff state that outlives both the originating PR description and the plan/roadmap
structured stores.

**Related:** Decision 86 (no new standing prose-architecture docs; rationale->Decisions,
forward-intent->tier_items), audits/unclosed-loops-44ef5c6.yaml ULF-12.

---

## Decision 114: Raise the ROADMAP-PLATFORM.yaml size ceiling to 10,000 lines and add a deterministic guard (supersedes KG.11's 2500-line/50K-token trigger) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-114 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Supersedes KG.11's Round-2-adversarial-era 2500-line/50K-token split-into-per-tier-files trigger.
The file is retained as a single file (agent-first, agent-loading-efficiency one-file principle,
AGENTS.md "Agent-First Repository" section / Decision 110 -- ROADMAP-PLATFORM.yaml is the realized
agent-first structured-data exemplar); splitting into per-tier YAML files with a manifest was
assessed and rejected because it trades one coherent load for N files an agent must reassemble,
which is the exact anti-pattern Decision 110 and the agent-first principles guard against. In place
of the split, the ceiling is raised to 10,000 lines and a deterministic, code-enforced guard is
added: `scripts/checks/roadmap/validate_platform_roadmap.py` gains a module-level constant
`_ROADMAP_MAX_LINES = 10_000` and a pure helper `_roadmap_size_issues()` that fails the check (full
`validate.py` tier) when the live file exceeds the ceiling. This closes KG.11 (flipped to
`status: resolved`, `resolution_ref: "Decision 114"`) and is the first ratified use of the new
OpenQuestion/KnownGap `status`/`resolution_ref` lifecycle fields (`scripts/platform_roadmap.py`,
mirroring the ExitCriterion met/rehomed precedent and the Decision 93 fail-loud enforcement style).

**Reversal conditions:** revisit a per-tier split (or a different ceiling) when the file breaches
the 10,000-line ceiling again, or when `/plan`-time load cost of the single file becomes prohibitive
in practice (not merely theoretical).

**Related:** KG.11 (the gap this resolves), CD.39 (the roadmap exit-criteria-ledger
promote-prose-to-enum precedent this migration follows for OQ/KG), Decision 84 (DECISIONS.md ->
ops_decisions authoring/sync authority), Decision 86 (extend the machine-parseable schema, not
prose), Decision 93 (deferred_post_mvp fail-loud lifecycle-status precedent), Decision 110 (ratified
CD.13 -- the agent-first structured-data exemplar this decision preserves).

---

## Decision 113: Ratify CD.26 -- Pattern-B agent auth (static-key + chained AssumeRole) supersedes Identity Center for the personal account (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-113 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.26. Realized 2026-05-29 -- `terraform/personal/platform_roles.tf` provisions Pattern B
(static-key + chained AssumeRole with two IAM roles, PlatformDev and PlatformAdmin), verified live
(PR #4; T0.3 complete). The session-start static-key assume-role chain verification hook
(`.claude/hooks/session_start_aws.sh`, PR #4) is operational. This supersedes the Identity Center
prep from PR-361 (commit 26ac4c2) for the personal account -- SSO remains a company-account
(company-aws-profile) requirement only, never a personal-account one. The two-principal semantic
(PlatformDev for daily ops, PlatformAdmin for admin/import-mode) is preserved verbatim, implemented
via IAM roles + ExternalId conditions (confused-deputy defense) instead of SSO permission sets.
Ratifying clears the completion gate CD.26 places on T0.3 (already complete) -- necessary, not
sufficient for the rest of T0.

**Reversal conditions:** re-open as a candidate only if SSO/Identity Center is reconsidered for the
personal account (e.g. a second account or an SSO requirement emerges for it).

**Related:** Decision 105 (the ratification lane executing this), CD.10 (two-principal allow-list
model the auth primitive change preserves).

---

## Decision 112: Ratify CD.21 -- CI migrated from self-hosted EC2 runner to GitHub-hosted runners + OIDC federation (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-112 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.21. Realized 2026-05-28 -- OIDC federation and CI migration to GitHub-hosted
`ubuntu-latest` runners are complete per Decision 73 (PR #1; `terraform/personal/oidc.tf` +
workflow migration). The self-hosted EC2 runner is retired; `terraform/ec2_runner.tf` is retained
(not deleted), carrying a deprecation header pointing at this Decision, per the indefinite-retention
rationale in CD.21's detail (a portfolio-positive architectural-evolution artefact with no ongoing
operational cost once the EC2 instance is terminated). This narrowly supersedes Decision 68 on the
runner-hosting question only -- Decision 68's other content is unaffected. Ratifying clears the
completion gate CD.21 places on T2.10.

**Reversal conditions:** re-open as a candidate only if CI moves off GitHub-hosted runners + OIDC
federation.

**Related:** Decision 73 (the migration realizing it), Decision 68 (superseded on the hosting
question only), Decision 105 (the ratification lane executing this).

---

## Decision 111: Ratify CD.20 -- Repository public-flip + curated-portal (not operational-data-export) commitment (scoped, necessary not sufficient) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-111 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.20, SCOPED to the realized COMMITMENT, not the fully-finished portal. Realized
(partial) 2026-05-30 -- the public flip completed (T2.13) per Decision 76; the hard invariant that
the public surface is a curated portal (README.md, AGENTS.md, EVALUATION-PROMPTS.yaml,
`.devcontainer/`, SECURITY.md) rather than an export of operational data (`ops_recommendations`,
`ops_decisions`, `ops_session_log`, telemetry) is in force. T2.12 (GHAS + branch protection)
completed 2026-06-08 (Decision 83). T2.11b is partial (2026-06-18): SECURITY.md's projection-at-top
enriched, EVALUATION-PROMPTS.yaml authored (12 questions, all answer-loci resolve). This Decision
asserts ONLY that the public-flip + curated-portal COMMITMENT is realized and in force -- it does
NOT claim portal completion is finished: T2.11a (`.devcontainer`, not started) and the T2.11b
architecture diagram (gated on T2.13 + T2.11a) remain open and are tracked by their own tier items,
not closed by this ratification. Ratifying clears the completion gate CD.20 places on its gated
items -- necessary, not sufficient; T2.11a/T2.11b's own code exit criteria are the vehicle for
finishing the portal.

**Reversal conditions:** re-open as a candidate only if the public-repo decision is reversed (the
repo returns private) or the curated-portal-projection invariant is abandoned.

**Related:** Decision 76 (the flip), Decision 83 (T2.12 GHAS + branch protection), Decision 101
(public-content boundary this ratification upholds), Decision 105 (the ratification lane executing
this).

---

## Decision 110: Ratify CD.13 -- ROADMAP-PLATFORM.yaml is the realized agent-first structured-data exemplar (scoped, necessary not sufficient) (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-110 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.13, SCOPED to the realized exemplar, not the broader documentation-migration vision.
ROADMAP-PLATFORM.yaml is pure YAML -- structured `tier_items` + `cross_tier_gates` +
`candidate_decisions`, no narrative prose -- and is consumed as structured data by the
planning/decision-scout/plan-critique/implement skills every session. Its own gated work (T-1.2,
T-1.3, T-1.4, T-1.5) is complete. This Decision asserts ONLY that the roadmap itself is the realized
agent-first structured-data exemplar; it does NOT assert the broader vision in CD.13's detail --
"future repo documentation follows this shape; markdown-with-prose is fully retired" -- is finished.
That broader migration is ongoing under T5.5 (INTENT-doc extraction) and is not closed by this
ratification. Ratifying clears the completion gate CD.13 places on T-1.2..T-1.5 (already complete)
and, via T-1.20's `related_candidate_decisions`, contributes to unwedging T-1.20 -- necessary, not
sufficient for the broader doc-migration vision.

**Reversal conditions:** re-open as a candidate only if the roadmap ceases to be the canonical
agent-first structured-data exemplar (e.g. a return to markdown-with-prose canonical docs).

**Related:** Decision 86 (rationale-to-Decisions / field-semantics-to-contracts, no new prose-
architecture docs -- the discipline this exemplar embodies), Decision 105 (the ratification lane
executing this); T5.5 (the ongoing broader migration this Decision does not claim finished).

---

## Decision 109: Ratify CD.2 -- Dev surface = Claude Code on the web; Windows VM opportunistic until T5.1 (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-109 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.2. Realized 2026-05-30 -- the CC-web (Claude Code on the web) dev surface is
operational as the primary dev surface per Decision 76 (web-workflow-migration, PR #10) and
`bin/setup-cloud-env.sh` static-key setup (PRs #4/#6). The Windows VM remains opportunistically
usable until T5.1. Ratifying clears the completion gate CD.2 places on T0 -- necessary, not
sufficient: T0.4/T0.6/T0.7+ remain outstanding and are tracked by their own tier items.

**Reversal conditions:** re-open as a candidate only if CC-web ceases to be the primary dev surface.

**Related:** Decision 76 (the web-workflow migration realizing it), Decision 105 (the ratification
lane executing this).

---

## Decision 108: Ratify CD.1 -- ROADMAP-PLATFORM.yaml (this document) adopted as the canonical platform-sequencing source of truth (Decided)

**Status:** Decided
**Date:** 2026-07-03
**Warehouse ID:** dec-108 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.1. ROADMAP-PLATFORM.yaml has been the canonical platform-sequencing source of truth
governing every `/orient`, `/plan`, `/implement` session since PR #335; the platform sections of
ROADMAP-PRODUCT.md are superseded by it. Ratifying clears the completion gate CD.1 places on T-1
(via the tier shortcut in its `gates` field) -- necessary, not sufficient: T-1's own open code exit
criteria (e.g. the remaining T-1.x items) remain a separate, ongoing concern.

**Reversal conditions:** re-open as a candidate only if a different canonical platform-roadmap
document or format is adopted (foundational -- would require re-deriving every downstream
skill/gate that reads this file).

**Related:** Decision 105 (the ratification lane executing this), Decision 91 (file_decision is the
shipped ratification vehicle, not the never-built log-decision Lambda), Decision 90 (tier-status
flips are a separate `/implement` bookkeeping step from ratification itself).

---

## Decision 107: Ratify CD.34 -- DuckLake catalog backend RDS PostgreSQL -> Neon serverless Postgres (Decision-88-amended framing) (Decided)

**Status:** Decided
**Date:** 2026-07-02
**Warehouse ID:** dec-107 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.34 as realized/live. The DuckLake catalog runs on Neon serverless Postgres via the
Terraform Neon provider behind the Decision-77 Neon-aware fail-closed guard (blocks any `neon_*`
update/replace/delete; allows a `neon_*` create on compensating controls -- TLS `sslmode=require`,
a scoped non-owner `neon_role`, Secrets Manager DSN; no IP allow-list). Inlining is disabled for
ALL tables including telemetry (`ducklake_default_data_inlining_row_limit=0`). Catalog egress is a
first-class budget governed by Decision 88's four standing access-pattern invariants (warm-
connection reuse; no read-cache re-fetch; keep the catalog compacted; DR cadence sized to
durability tier + measured egress). DR = a WEEKLY `pg_dump`-to-S3 (`cron(0 3 ? * SUN *)`, 30-day
retention, ~8-day freshness alarm), NOT the original daily cadence (Decision 88 amendment); paid-
tier Neon PITR provides finer recovery between weekly dumps. The CD.33 runtime architecture
(writer/reader/maintenance split, OCC retry, current projection, SCD2 keys, GC/merge cadences) is
UNCHANGED -- only the catalog backend + its consequential recovery/pooling mechanics change.

**Swap-back-to-RDS reversal conditions** (any one triggers a human-gated re-evaluation, Decision 35):
1. Sustained cost regression -- monthly Neon cost (compute + metered egress, WITH the Decision-88
   invariants upheld) exceeds the ~$12-15/mo micro-RDS baseline for 2 consecutive billing cycles.
2. Durability/availability floor breached -- Neon PITR/pooler cannot meet recovery objectives
   (e.g. recurring `ducklake_reader` 502s traced to scale-to-zero cold-resume that warm-connection
   reuse cannot mitigate, or a PITR window short of a required RPO).
3. Hard technical incompatibility -- the built-in pooler / direct endpoint cannot satisfy DuckLake
   postgres-catalog transaction-safety within the CD.33 OCC budget and no app-side pool remedies it.
4. Vendor viability -- discontinuation of the eligible tier, a ToS change incompatible with the
   use, or sustained SLA misses.

**Reversal mechanics:** the RDS path stays fully Terraformed as an architectural-evolution
artifact; swap-back re-points the Terraform config to the RDS module and restores the catalog from
the latest weekly `pg_dump`-to-S3 (+ Neon PITR delta) -- a METADATA restore, not a data migration
(row data is S3 Parquet). Precondition: the rec-2113 `pg_restore` restore drill must pass before
the weekly dump is relied on as the swap-back artifact.

**Related:** Decision 88 (amends here -- egress budget + weekly DR), Decision 82 (direct-vs-pooled
endpoint basis), Decision 81/CD.33 (runtime architecture retained), Decision 77 (fail-closed
guard), Decision 100/75 (managed-service-native preference the Neon choice aligns with).

---

## Decision 106: Ratify CD.6 -- Personal AWS account is the destination; rebuild not migrate (Decided)

**Status:** Decided
**Date:** 2026-07-02
**Warehouse ID:** dec-106 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Decision:**
Ratifies CD.6. Realized 2026-05-28 -- Phase B personal-account Terraform re-deploy applied and
verified per Decision 77 (PR #1); pre-live data was throwaway, only `ops_recommendations` +
`ops_decisions` were preserved (JSON export/import), infrastructure re-created by a fresh
`terraform apply` against the personal account. CD.6 gates all of T2; ratifying clears the
*completion* gate on T2 items but their open CODE criteria remain (necessary, not sufficient).

**Reversal conditions:** re-open as a candidate only if (a) a second destination account/re-
platform is chosen (re-invokes the migrate-vs-rebuild question), or (b) the "pre-live-data-is-
throwaway" premise ceases to hold (i.e., live trading data with retention/compliance value exists
AND a future account move is contemplated) -- at which point a migrate path, not a rebuild, must
be re-evaluated.

**Related:** Decision 77 (fail-closed apply pipeline that realized it), CD.34 (the catalog backend
re-platformed within this account).

---

## Decision 105: Candidate-decision ratification lane -- shared /orient->/plan->/implement mechanism; canonical ratified-CD shape; stale-CD reconciliation (Decided)

**Status:** Decided
**Date:** 2026-07-02
**Warehouse ID:** dec-105 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The four-tier workflow (`/orient` -> `/plan` -> `/implement`) can AUTHOR decisions
(`ops_data_portal file_decision`) and CITE them (decision-scout), but has no lane that RATIFIES a
candidate decision (CD.NN) whose gated work is realized. 31 of 39 CDs were `state: pending` and
several silently gate live tier items via `completion_blocked_on_cd`. 5 of the 7 pre-existing
ratified CDs pointed at retired 4-digit warehouse ids (dec-1085/1086/1089/1091) instead of their
real 3-digit DECISIONS.md numbers.

**Decision:**
Adopts a first-class CD ratification lane shared across `/orient` (surfaces pending CDs carrying
`realization_evidence` via `PlatformRoadmapState.ratifiable_cds()`), `/plan` (drafts the ratifying
Decision text, including any reversal conditions, as a plan step -- the plan confirmation + plan-
critique gates are the human sign-off), and `/implement` (executes: author the DECISIONS.md entry
-> ops portal ETL via `ops_data_portal --backfill-decisions-md` (`--file-decision` the single-row
alternative) -> flip the CD to the canonical ratified shape -> re-run preflight to confirm the
gate cleared, behind an execution-time human confirmation gate). No new top-level command is
added. Defines the canonical ratified-CD shape (`state: ratified` + `ratified_as: dec-NNN` +
`filed_via: ops_decisions:dec-NNN`, same 3-digit number in both fields) and the R1/R2/R3
referential guard (`validate_candidate_decision_ratification`), whose referential target is the
`## Decision NNN:` headers in BOTH `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` (hermetic;
the ops_decisions cache is gitignored and CI PR roles lack reader access). Reconciles the 5 pre-
existing ratified CDs whose `filed_via` pointed at retired 4-digit warehouse ids onto their real
3-digit Decisions (CD.31->dec-078, CD.16/CD.24->dec-079, CD.33->dec-081, CD.22->dec-085), and
normalizes CD.35 (adds `ratified_as: dec-092`) and CD.36 (`filed_via` -> `ops_decisions:dec-103`).

**Rationale:**
Routed here per Decision 86 (rationale in this Decision, not a new prose doc; mechanism encoded in
`.claude/` skills + `docs/contracts/candidate-decision-ratification.yaml`). Ratifying a CD clears
the COMPLETION gate on items it gates (gate derivation keys purely on `cd.state == 'pending'`) --
this is necessary but not sufficient, since open CODE exit criteria on those items remain and
tier_item status flips are a separate `/implement` bookkeeping step (Decision 90).

**Related:** Decision 90 (four-tier workflow), Decision 84 (Single Portal Invariant / numbering
authority), Decision 92 + Decision 103 (the two working ratification precedents this pattern
generalizes), Decision 104 (check registry pattern this guard follows), Decision 76/86 (canonical
mechanism surface / contract routing).

> **Amended by Decision 150 (2026-07-24):** batch-wave ratified form -- same-session pure
> gate-clears may land as ONE wave entry with per-CD clauses sharing one dec-NNN. See Decision 150.

---

## Decision 104: scripts/validate.py decomposed into an owner-tagged check registry (partially supersedes Decision 80 point 3) (Decided)

**Status:** Decided
**Date:** 2026-07-01
**Warehouse ID:** dec-104 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 169 (2026-08-11):** the facade re-export clause, the `globals()[name]`
> dispatch clause, and the byte-for-byte "Equivalence oracle" clause are each negated and
> replaced by a per-domain declarative-manifest mechanism (`scripts.checks.registry.resolve()`,
> `docs/contracts/check-manifest.yaml`). Every other clause of this Decision (the `Check`
> dataclass, the `_common.py` shared-primitives convention, the per-check-per-file decomposition,
> the owner-tagging convention, the coverage-gate mapping extension) is otherwise unedited; see
> Decision 169 for the full derivation.

**Problem:**
`scripts/validate.py` is the mandatory convergence point for every platform check ("never add a
check to ci.yml without adding it to validate.py first"), so a per-file SLOC cap on it only
ratchets upward under Decision 43/102 (3238 -> 3261 -> 3316 -> 3355 -> 3375; ~3368 SLOC, 7 lines
of headroom before this plan). Capping the aggregator was an axis error: the fix is one-concern-
per-file modules whose count grows freely while each stays flat, not a growing exemption on the
one file every check must route through.

**Decision:**
Ratifies the check-registry mechanism implemented by PLAN-validate-decomposition:
- `scripts/checks/registry.py` defines a `Check` dataclass (`name`, `owner`, `product_coupled`),
  a `register()` decorator, and two ordered per-tier sequences -- `pre_sequence()` /
  `full_sequence()` -- each a list of `Step(kind, name)` descriptors that interleave registered
  check names with fixed non-check scaffolding steps (lint, precommit, mypy, explicit pytest,
  unit-test invoke_step, dependency/terraform gates, budget assertion). Tier membership and order
  live ONLY in this package; adding a check never touches `scripts/validate.py`.
- `scripts/checks/_common.py` is the SOLE source of the shared primitives (`ROOT`, `PYTHON`,
  `run`, `invoke_step`, `get_changed_files`). Every consumer -- extracted checks, the CLI's own
  remaining scaffolding, and `scripts/checks/_scaffolding.py` -- references these via the
  qualified `_common.<name>` form (never a bare imported name), so `scripts.checks._common` is
  the single interception point regardless of which module does the calling.
- Every `validate_*`/`check_*` function moved out of the monolith into
  `scripts/checks/<domain>/<module>.py`, one concern per file (a shared `_shared.py` inside a
  domain package is permitted when 2+ checks in that SAME domain need an identical helper --
  e.g. `ci_guards/_shared.py::_ensure_root_on_path`, `contracts/_shared.py::_load_prompt_compliance`,
  `sloc/_shared.py`'s constants -- never across domains).
  `scripts/checks/_scaffolding.py` holds the non-check CLI orchestration logic (precommit, lint,
  terraform gates, dependency health, DQ-freshness auto-invoke, budget-breach/bypass rec filing,
  the unit-test command builder) that stays outside the registry (no check identity) but outside
  `scripts/validate.py` too, so the CLI entrypoint stays thin.
- `scripts/validate.py` retains ONLY: the argparse surface, the `_VALIDATE_DEPTH` recursion guard,
  the branch guard, the fast-tier budget assertion, the registry-driven dispatch loops (resolving
  each "check" step via `globals()[name](failed)` so `patch("validate.<name>")` keeps
  intercepting), and facade re-exports of every extracted check and private helper (so both
  `patch("validate.<name>")` and `from scripts.validate import <name>` keep resolving). Dropped
  from 3372 SLOC to well under the 500-SLOC limit (target <300; `validate --update-sloc-budgets`
  is the authoritative live figure, not this document). `ci.yml` is unmodified -- it still calls
  only `python -m scripts.validate`.
- **Owner-tagging convention (platform/product federation direction):** every check defaults
  `owner="platform"`. Of 58 checks, exactly one is unambiguously trading-product:
  `validate_broker_env_reads` (owner="trading"). Two are platform machinery operating over a
  trading-shaped artifact and are tagged `owner="platform", product_coupled=True`:
  `validate_product_roadmap`, `validate_environment_taxonomy`. The owner axis is registry
  metadata, not a directory split (no `theseus/`/`platform/` path segment) -- the checks tree
  stays movable as a unit; a second product's checks will federate (colocate with their product)
  with CI composed by owner+tier+affected-set when that day comes. This is architectural
  direction, not a roadmap tier_item (a parked federation item would itself be the stale artifact
  Decision 86 prevents).
- **Coverage-gate mapping extension:** `scripts/test_coverage_checker.py::map_source_to_test` now
  maps `scripts/checks/**/*.py` to `tests/test_validate.py` (where every extracted check's tests
  already live, colocated with the pre-decomposition monolith's test file), except
  `registry.py`/`_common.py` which map to the new `tests/test_checks_registry.py` (the registry
  mechanism's own dedicated suite). Previously `len(parts) == 2` silently skipped every nested
  `scripts/checks/**` module from the coverage gate entirely.
- **Equivalence oracle:** `tests/test_checks_registry.py` freezes the exact pre-refactor ordered
  step sequence (kind + name tuples, not raw stdout) for both tiers and asserts
  `registry.pre_sequence()`/`full_sequence()` match it byte-for-byte. `validate_complexity`'s
  advisory `logs/.complexity-warnings.json` output is the sole documented exception to full
  behaviour preservation (it is inherently location-dependent by construction and non-gating).
- Partially supersedes ONLY Decision 80 point 3 (validate.py's internal structure); Decision 80
  points 1/2/4 remain live and unaffected.

**Rationale:**
- A registry with declared per-tier sequences is the only design that lets "add a check" touch
  one new file instead of the SLOC-capped aggregator, while still letting the CLI single-source-
  of-truth invariant (Decision 80 point 3) hold: `ci.yml` still calls only `python -m scripts.validate`.
- Routing every shared primitive through `_common.<name>` (qualified, never a bare re-imported
  name) is what makes "patch scripts.checks._common.X" a single, uniform interception point for
  both extracted checks and the CLI's own remaining orchestration code -- the alternative (each
  module keeping its own bare-name import) would silently fork interception semantics per call
  site, exactly the class of bug this decomposition would otherwise reintroduce.
- Getattr-resolution dispatch (`globals()[name](failed)` inside `scripts/validate.py`, walking
  `registry.pre_sequence()`/`full_sequence()`) preserves the existing test suite's mock-patching
  idiom (`patch("validate.<check_name>")`) without any test rewrite for check-name patches --
  only patches targeting a MOVED shared primitive or a check-local helper/constant needed
  repointing.

**Related:** Decision 80 (ci.yml-first single-source-of-truth invariant, partially superseded --
point 3 only), Decision 102 (SLOC ratchet, applied to every new `scripts/checks/**` module),
Decision 43 (CC<=20 waiver-carry rule), Decision 86 (no new standing prose-architecture docs --
this section is the sole record of the registry rationale and owner convention), rec-2420
(the `_update_sloc_budgets` lowering-test gap this plan closed in `tests/test_checks_registry.py`).

---

## Decision 103: Recommendation relevance is a governed lifecycle state (CD.36 ratification) (Decided)

**Status:** Decided
**Date:** 2026-06-30
**Warehouse ID:** dec-103 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The roadmap had a Tier Item Freshness Gate (T-1.21) and implement-side truth-maintenance rules,
but no governed relevance discipline for operational recommendations. Open recommendations were
actioned solely on status="open", without checking whether the underlying need was still valid.
At 2026-06-24, 273 of 505 open recommendations were aging (>60 days), and no automated path
existed to surface or close satisfied/superseded work.

**Decision:**
Ratifies CD.36. Recommendation relevance is a governed lifecycle verdict -- distinct from the
rec lifecycle status (open/closed/failed/declined/superseded). The verdict set is:
`{relevant, satisfied, superseded, duplicate, contradicted, stale_target, blocked_by_decision, unknown}`.

Key constraints (binding):
- The deterministic probe is the rec's existing `acceptance` shell-command oracle. No new
  acceptance machinery is introduced.
- Deterministic satisfaction (acceptance probe passes; target file/symbol present) may auto-close
  with a recorded proof. All semantic verdicts (superseded, duplicate, contradicted, etc.)
  produce a `close_proposed` command for human or policy confirmation -- never a direct close
  (Decision 70: closure requires a closure proof, not an LLM assertion).
  [Amendment 2026-07-03, Decision-70 mis-cite (audit f80508b): the closure-proof principle cited
  above as "Decision 70" is a mis-cite -- the principle is THIS decision (Decision 103); Decision 70
  (DECISIONS.md, "Physical Deletion of Bootstrap Records") governs bootstrap-record deletion, not
  closure-proof semantics.]
- Relevance state is computed READ-TIME or stored in a named projection
  (`docs/contracts/recommendation-relevance.yaml`) -- NO new Class A columns on
  `ops_recommendations` (Decision 84: the ducklake_writer owns the keyspace).
- Queue-wide relevance surfacing serves the warmed read-cache only -- no per-session warehouse
  re-fetch (Decision 88).

**Implementation (T3.8, landed 2026-06-30):**
`scripts/rec_relevance.py` evaluator (deterministic-first: acceptance probe -> target-existence
-> decision-contradiction scan -> semantic fallback); `docs/contracts/recommendation-relevance.yaml`
projection contract; `scripts/session_preflight.py` generalised correlation engine;
`scripts/ops_data_portal.py` `propose_or_close_rec()` lifecycle helper; planning and implement
skill freshness gates.

**Related:** Decision 70 (closure-proof requirement), Decision 84 (named projection / read-only
boundary), Decision 88 (read-cache surfacing), Decision 55 (no auto-action on semantic judgment),
T3.8 (implementation item), T3.9 (post-merge reconciliation complement).

[Amendment 2026-07-03, Decision-70 mis-cite (audit f80508b): the "Decision 70 (closure-proof
requirement)" citation above is a mis-cite -- the closure-proof principle is THIS decision
(Decision 103); Decision 70 governs Physical Deletion of Bootstrap Records, not closure-proof
semantics.]

## Decision 102: SLOC Waiver Ratchet -- amends Decision 43 SLOC row (Decided)

**Status:** Decided
**Date:** 2026-06-29
**Warehouse ID:** dec-102 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 43 introduced a binary SLOC waiver: any scripts/ or src/ Python file carrying a
`# complexity-waiver: decision-43` header comment was entirely exempt from the 500-SLOC cap,
allowing unbounded growth. Seventeen files currently exceed 500 SLOC under this exemption.
The waiver mechanism provided no ratchet, no visibility into file growth, and no pressure
toward the reduction that Decision 43 itself mandated.

**Decision:**
The `# complexity-waiver: decision-43` comment no longer authorises unbounded SLOC growth.
Oversized scripts/ and src/ Python files are instead pinned to their current size in a
checked-in registry (`config/sloc_budgets.yaml`) and enforced by `validate_sloc_limits` at
`current SLOC <= budget`. Budgets ratchet DOWN only:

- Raising a budget requires a manual, reviewable edit to `config/sloc_budgets.yaml`.
- Shrinking a file and re-running `validate --update-sloc-budgets` automatically lowers the
  registered budget to the new size.
- Files that shrink to <=500 SLOC are dropped from the registry automatically.
- A file >500 SLOC that is NOT registered in `config/sloc_budgets.yaml` fails the gate,
  regardless of whether it carries the waiver comment.
- A file <=500 SLOC that still carries the waiver comment is a stale-waiver advisory (not a
  failure), because the comment may still be load-bearing for the cyclomatic-complexity gate
  (validate_cc_limits). Do not remove the comment without verifying the CC gate first.

**Preserved from Decision 43:**
The cyclomatic-complexity (CC) row of Decision 43 is UNCHANGED. The `_WAIVER_PATTERN` and the
`validate_cc_limits` gate are not modified by this decision. The shared waiver comment still
waives the CC gate; its SLOC semantics are amended here only.

**Forward-compatibility (Decision 80):**
`config/sloc_budgets.yaml` keys are repo-relative forward-slash paths. When `scripts/validate.py`
is decomposed per Decision 80, keys are re-pointed at the new module paths via
`validate --update-sloc-budgets`. No other migration is required.

**Deferred breakdown program:**
The breakdown of registered files below 500 SLOC (split each file, drop from registry,
until `budgets: {}`) is tracked as rec-2414. This decision creates the registry that rec-2414
consumes; it does not resolve rec-2414.

**Related:** Decision 43 (amended SLOC row), Decision 80 (validate.py decomposition direction),
Decision 73 (one-directional enforced-budget ratchet precedent), Decision 86 (rationale routed
to this numbered Decision).

## Decision 101: External brand identity (Theseus / Guerdon / Semanto) -- presentation-layer only, with a scoped Agent-First marketing-prose exception (Decided)

**Status:** Decided
**Date:** 2026-06-28
**Warehouse ID:** dec-101 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 171 (2026-08-16):** three clauses move, and only three. (1) Point (b)'s
> **repository-name row** is promoted into the presentation layer -- the repository is renamed
> `benjamin-blake/agent-platform` -> `benjamin-blake/theseus`. This is the "separate explicit
> decision" that row required. The other four (b) rows -- `agent-platform-*` AWS resource
> prefixes, the `agent_platform` IAM profile, the `agent_platform` Glue database, and
> `project_id = trading-system` -- are re-affirmed FROZEN, and the deep internal rename stays
> deferred post-MVP. (2) Point (f)'s **deferred paid service offering** is discharged for the
> LICENCE half only: Decision 171 relicenses to BUSL-1.1 and authorises dual licensing, but
> builds no commercial surface, pricing or terms, so the remainder of that deferral stands.
> (3) Point (f)'s **"secondary aspiration: open-source community"** is amended: BUSL-1.1 is
> source-available, NOT OSI open source, and contributions now require a copyright assignment
> or equivalently broad grant (`CONTRIBUTING.md`). Points (a), (c), (d) and (e) are unedited;
> see Decision 171 for the full derivation.

**Problem:**
The platform and its trading product were operating under purely internal identifiers (repo
`agent-platform`, AWS prefixes `agent-platform-*`, profile `agent_platform`, project_id
`trading-system`). As the system matures toward MVP, external-facing brand identity and a
public documentation/marketing presence are needed. No ratified decision named the external
brands or governed what may and may not be published publicly.

**Decision:**

**(a) Naming hierarchy:**
- **Theseus** = external brand for the PLATFORM (the self-improving host system).
- **Guerdon** = external brand for the trading PRODUCT (product #1 built on Theseus).
- **Semanto** = the external-facing marketing/comms system and the name of its roadmap
  (`docs/ROADMAP-SEMANTO.yaml`). Semanto is a PRESENTATION-LAYER-ONLY brand for the
  marketing and communications surface; it is not a product or a subsystem.

**(b) Presentation-layer only -- internal identifiers unchanged:**
The external brands apply exclusively to external/marketing surfaces. ALL internal identifiers
are unchanged by this decision and must not be altered without a separate explicit decision:
- Repository name: `agent-platform`
- AWS resource prefixes: `agent-platform-*`
- IAM profile: `agent_platform`
- Glue database: `agent_platform`
- Project ID: `trading-system` (per the INTENT-multi-product-platform origin model, which is
  unbuilt and unchanged here)

A deep internal rename (aligning identifiers to `theseus-*`) is a recognised high-blast-radius
future item DEFERRED to a post-MVP tightening refactor. Citing Decision 75 (Frame-Lock): no
fixed internal-rename scope is committed here; the scope will be bounded in a future plan.

**(c) Scoped Decision-86 marketing-prose exception:**
Decision 86 (Agent-First repository) mandates machine-parseable artefacts over narrative prose
and bans standing human-readable companion documents. Marketing prose is hereby granted a
SCOPED EXCEPTION under the following conditions:
- Marketing content lives OUTSIDE `docs/` -- the canonical directory is the top-level
  `marketing/` directory.
- Marketing content is NOT consumed by internal agents as a source of truth. It is strictly
  one-way downstream: it renders internal artefacts; it never feeds back into agent context.
- Marketing content is never a warehouse write source (Decision 84). It is read-only from the
  warehouse's perspective.
- This exception is scoped to marketing prose only and does not extend to any other
  human-readable content under `docs/`.

**(d) Public-content boundary:**
The public site (theseus.support) must enforce the following boundary at all times:
- Never publish AWS account specifics: account IDs, infra topology, VPC details, secret
  names, decision logs, or any content from `docs/` or `logs/`.
- Market the platform engineering and architecture; never publish Guerdon's trading
  alpha, performance figures, or returns. Publishing performance claims exposes
  investment-solicitation and securities-law risk.

**(e) Hosting:**
The public site is a static site on Cloudflare Pages, built with Astro and Starlight
(both free/MIT-licensed). Cloudflare Pages is the native managed primitive for static-site
hosting -- consistent with Decision 100 (use managed primitives, no client-tooling substitution
for native operations). No hand-rolled build or hosting tooling is permitted.
Domain: `theseus.support` (Cloudflare-managed DNS, already owned).

**(f) Positioning:**
- Primary audience: data-engineering hiring managers (portfolio and technical credibility signal).
- Secondary aspiration: open-source community (transparency, contribution).
- Deferred, separately gated: a paid service offering (requires its own decision and plan;
  not in scope for the MVP marketing surface).

**Scope of this decision:**
This decision ratifies branding and governance only. It DOES NOT provision any infrastructure,
deploy any site, or change any internal identifier. The theseus.support site and DNS are
deferred_post_mvp items (S1.2/S1.3 in `docs/ROADMAP-SEMANTO.yaml`). The deep internal rename
is explicitly deferred. This session's only artefacts are this decision and `docs/ROADMAP-SEMANTO.yaml`.

**Affected files:**
`docs/DECISIONS.md` (this decision), `docs/ROADMAP-SEMANTO.yaml` (new third sibling roadmap).

---

## Decision 100: Managed services own their primitives -- no client-tooling substitution for native operations (Decided)

**Status:** Decided
**Date:** 2026-06-26
**Warehouse ID:** dec-100 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
PR #273 introduced a `pg_dump -> scratch-DB -> pg_restore` mechanism for the OQ.12 pre-deploy
clone-rehearsal, despite Neon providing native copy-on-write branching (HTTPS/443 REST API,
no TCP/5432 egress required). Three compounding factors allowed this:
1. The mechanism was recorded as a "human decision" (HYBRID pg_dump->pg_restore framing),
   which was then treated as exempt from architectural review.
2. Decision 75 (Frame-Lock) was scoped to AWS-native primitives, leaving Neon's native
   primitives uncovered by an explicit decision.
3. The pg_dump egress smell was mis-resolved by citing Decision 88 (which governs the
   unavoidable DR backup egress, not the avoidable read-clone egress).

**Decision:**
Extends Decision 75 (Frame-Lock) to all managed services: when a managed service exposes a
native primitive (branching, snapshots, PITR, replication, versioning, cloning), the system
must use that primitive rather than vendoring client tooling or custom scripts to replicate
the capability outside the managed boundary. A mechanism recorded as a "human decision"
does NOT exempt it from this principle -- the decision record is evidence of a choice made,
not a permanent seal against architectural correction.

Canonical instance: OQ.12 clone-rehearsal uses Neon's native copy-on-write branching
(POST /api/v2/projects/{project_id}/branches over HTTPS/443), not pg_dump -> pg_restore.
The orchestrator owns the branch lifecycle (create before invoke, delete in finally).
The Lambda action only ATTACHes to the branch endpoint and reads catalog metadata read-only.

Decision 88 governs the DR pg_dump-to-S3 backup pipeline, which remains real and unchanged
(unavoidable egress for an offline backup). Decision 88 never applied to the read-clone path.

**Enforcement (Decision 100 procedure guard):**
The `decision-scout` skill (Phase 2 triage) is updated with a WARN check: flag any plan that
vendors client tooling or custom scripts to replicate a capability a managed service exposes
natively. Cross-references Decision 100 and Decision 75.

**Rationale:**
- Native primitives are lower-latency, eliminate operational complexity (no scratch DB lifecycle,
  no pg_restore binary dependency in Lambda layers), and stay within the managed boundary.
- The pg_dump -> pg_restore path required pg_restore in the Lambda pgclient layer, imposing a
  non-CC-web operator rebuild constraint and blocking the "DEFERRED at sign-off" restore-drill gate.
  Removing it unblocks both constraints simultaneously.
- Zero new IAM: the orchestrator's `agent_platform_admin` profile already holds
  `secretsmanager:GetSecretValue` on `neon-api-key` (no new grants needed).

**Affected files:**
`src/common/neon_api.py` (new -- Neon REST client),
`src/lambdas/ducklake_maintenance/handler.py` (action_clone_catalog rewritten),
`scripts/ducklake_neon_smoke_test.py` (canary_rehearsal branch lifecycle),
`scripts/build_lambda.py` (pg_restore guard removed from build_pgclient_layer),
`docs/runbooks/ducklake-catalog-operations.md` (Section 2 step 4 rewritten),
`.claude/skills/decision-scout/SKILL.md` (managed-service-native WARN check added).

---

## Decision 99: DuckDB/DuckLake lockstep version SSOT + first exercised version bump 1.5.3->1.5.4 (Decided)

**Status:** Decided
**Date:** 2026-06-26
**Warehouse ID:** dec-099 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The DuckDB lockstep version (`1.5.3`) was hardcoded as a literal string in four places:
`src/common/ducklake_runtime.py::PINNED_DUCKDB_VERSION`, `scripts/build_lambda.py::PINNED_DUCKDB_VERSION`,
the `requirements.txt` floor, and implicitly the S3 extension URLs. A version bump required four
coordinated edits with no machine-enforced invariant that all surfaces agreed. Additionally the
local venv ran DuckDB 1.5.4 while the pin was 1.5.3, causing `assert_duckdb_version` loud-failures
on every local DuckLake connection (PLAN-t2-28 VP6 blocker).

**Decision:**
Collapse to a single machine-readable SSOT (`config/lambda/ducklake/version.yaml`) with a shared
loader (`src/common/ducklake_version.py::pinned_duckdb_version()`). All derive surfaces read the pin
via the loader; no literal survives outside `version.yaml`. A `ducklake-version-lockstep` gate in
`validate.py` enforces drift-free coherence at every PR. The pending 1.5.3->1.5.4 bump is executed
as the cascade proof: one edit to `version.yaml`, then `sync_ducklake_version` to update
`requirements.txt`, then rebuild + redeploy the four active DuckLake Lambda artifacts.

**Rehearsal evidence (OQ.12 clone-rehearsal gate):**
- VP3 sentinel override (`DUCKLAKE_VERSION_CONFIG` env) confirmed all derive surfaces read `9.9.9`
  when the override YAML contains that value -- cascade proof PASS.
- VP8: local DuckDB 1.5.4 matches `pinned_duckdb_version()` -- assert_duckdb_version PASS.
- Clone-rehearsal (VP13-14) and production redeploy (VP15) are post-code V3 steps gated on
  AWS credentials + interactive Terraform loop (human-confirmed before merge per Decision 77).

**Rationale:**
- A single-value edit is the correct abstraction: the bump procedure now touches exactly one file,
  with machine-enforced downstream coherence (the validate gate catches any reintroduced literal).
- The SSOT pattern mirrors the existing `field_semantics.yaml` / `_load_field_semantics_cached`
  pattern in `src/common/ducklake_scd2_schema.py` -- same module-relative path resolution,
  same `lru_cache`, same env override.
- Test files may retain `1.5.3` as fixture values (testing the upgrade FROM `1.5.3`) -- the
  zero-stray gate explicitly scopes to `src/ scripts/ requirements.txt terraform/personal/` only.

**Affected files:**
`config/lambda/ducklake/version.yaml` (new SSOT), `src/common/ducklake_version.py` (new loader),
`scripts/sync_ducklake_version.py` (new sync helper), `scripts/validate.py` (new gate),
`src/common/ducklake_runtime.py`, `scripts/build_lambda.py`, `requirements.txt`,
`terraform/personal/ducklake_lambdas.tf`, four Lambda manifests.

---

## Decision 98: Provisioning model for convergence-writer and peer CI roles -- admin-create in terraform/personal, read-only bootstrap IAMRolesRead grant (Decided)

**Status:** Decided
**Date:** 2026-06-24
**Warehouse ID:** dec-098 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The post-merge gated-apply for PR #250 (CD.35 Wave 5 / T2.24) failed with an explicit deny on
`iam:CreateRole` for `agent-platform-github-ci-drift`. The deny originates from the T2.23 authority
budget (`agent-platform-github-ci-apply-boundary`): `IAMRoleCreateBounded` conditions
`iam:CreateRole` on a `iam:PermissionsBoundary` propagation constraint scoped to branch+pr roles,
implicitly denying creation of any new peer CI role (e.g. drift). The same apply also failed
`iam:PutRolePolicy` on `github_ci_plan`, leaving both the drift role and the github_ci_plan
IAMCIRolesRead drift-ARN addition unapplied to AWS.

Additionally, `IAMRolesRead` in `terraform/bootstrap/github_ci_apply.tf` did not include the drift
role ARN, meaning every future `github_ci_apply` pipeline plan would fail AccessDenied on
`iam:GetRole/GetRolePolicy` when refreshing the now-in-state drift role (GAP 3).

**Decision:**
1. New peer CI roles (convergence-writer + any future equivalent) are admin-provisioned in
   `terraform/personal/` via `agent_platform_admin` with `-target` apply -- NOT minted by the
   pipeline (`github_ci_apply`). This is the same pattern used for branch/pr/plan roles.
   > **Amended -> realized by Decision 144 / T2.48 (2026-07-22):** the pipeline MAY now mint
   > boundary-carrying `agent-platform-*` roles through the gated `tf-gated-apply` Environment
   > (`IAMRoleCreateBounded` widened to `role/agent-platform-*` under the boundary-propagation
   > condition; role CREATE still ROUTES to the gated Environment -- gated-but-executable, no longer
   > admin-tier-only). The admin-create path remains valid for non-`agent-platform-*` roles and break-glass.
2. After admin-create, the new role's ARN is added to `IAMRolesRead` in
   `terraform/bootstrap/github_ci_apply.tf` as a read-only refresh grant
   (`iam:GetRole/GetRolePolicy/ListRolePolicies/ListAttachedRolePolicies` only). This grant does
   NOT widen the IAM-WRITE budget (`IAMRoleWriteBounded` / `IAMRoleCreateBounded` unchanged).
3. In-budget IAM auto-apply (the pipeline minting roles under the permissions boundary) remains
   gated to T2.25 and is out of scope here.
   > **Realized by Decision 144 / T2.48 (2026-07-22):** authority-budget v2 makes a CREATE of an inline
   > policy/attachment on a boundary-carrying `agent-platform-*` role in-budget (auto-apply); role CREATE
   > (the `aws_iam_role` type) stays gated but is now executable by the gated job because new roles
   > declare the mandatory boundary.
4. Procedure: (a) present `terraform plan` to the human (Decision 77); (b) admin-apply; (c) verify
   global convergence (`terraform plan -detailed-exitcode` exits 0) BEFORE any dispatch-ack; (d)
   add the ARN to `IAMRolesRead` in the bootstrap root and admin-apply that root separately.

**Rationale:**
- Path B (widen pipeline to mint roles) is premature T2.25 work and couples the drift role to the
  apply boundary -- rejected (Decision 55 / 72 RCA-first, no inline hot-patch).
- Path C (re-home to bootstrap root) is more churn with no architectural benefit -- rejected.
- The branch/pr/plan roles were all admin-created and all appear in `IAMRolesRead`. Adding drift
  follows the same precedent (Decision 94 pattern).

**Related:** Decision 92 (authority budget), Decision 94 (github_ci_apply OIDC trust correction --
same admin-create pattern), Decision 55/72 (no inline hot-patch / no autonomous workaround), T2.23
(bootstrap authority budget), T2.24 (drift role this applies to), T2.25 (in-budget IAM auto-apply).

---

## Decision 97: Telemetry identity + determinism standard -- ULID keys, boundary-minting, no downstream re-derivation (Decided)

**Status:** Decided
**Date:** 2026-06-23
**Warehouse ID:** dec-097 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The draft telemetry pipeline has no canonical identity or determinism standard. session_id is a random
UUID4 (`str(uuid.uuid4())`), which is unsortable and gives no time-ordering for partition pruning or
ORDER BY; the draft child event tables (phases / steps / process_events / model_calls) have no ratified
primary-key scheme at all. Nothing states WHERE an id or an event timestamp is minted, so a child row
could re-derive its own id or `now()` timestamp instead of receiving them from its parent -- the same
non-determinism / FK-mismatch class that CD.33 / Decision 82 already closed for ducklake_writer (mint
ULID + `now()` ONCE, outside the OCC-retry loop). Telemetry needs the same rule settled before per-table
contracts are ratified, or each table re-invents it inconsistently.

**Decision:**
1. **ULID for all telemetry identity keys.** Every telemetry primary key -- session_id (target, see
   clause 4), observation_id, parent_observation_id (a reference to an observation_id), transcript_id,
   and any telemetry_agents key -- is a Crockford-base32 ULID. ULIDs are lexicographically sortable and
   time-ordered (k-sortable), so `day()`-partition pruning and natural chronological ORDER BY fall out of
   the key itself. This aligns telemetry with the ops-table identity convention already live in the
   warehouse (the `ulid` SCD2 envelope field on ops_recommendations / ops_decisions, Decision 84).

2. **Boundary-minting (mint-once).** Identity keys and event timestamps are minted exactly ONCE, at the
   boundary call that opens the entity (`open_session` / `open_observation`), and never re-derived
   downstream. A retried or resumed write reuses the already-minted id and timestamp. This restates
   CD.33 clause 2 / Decision 82 (D-2) for the telemetry path.

3. **Boundary-injection (propagate, never re-derive).** Child rows receive session_id (and
   parent_observation_id) from their parent as foreign keys; a child never re-mints a correlation key it
   did not originate. This generalises the propagation rule already in session-id.yaml ("created in the
   parent session and propagated to child telemetry rows as a foreign key") to the whole trace tree.

4. **session_id realization.** ULID is the ratified TARGET format for session_id. Existing UUID4 session
   ids are grandfathered: the format flips when the boundary-minting code
   (`scripts/executor/telemetry.py::open_session`) is migrated to mint ULIDs. session-id.yaml records
   ULID as the canonical target via an additive governance note (Decision 95); the live format stays
   UUID4 until that code lands. The flip is a downstream code-migration concern, not part of this
   REPORT-ONLY decision.

**Rationale:**
UUID4 was never chosen for telemetry -- it is the default `str(uuid.uuid4())` the draft happened to emit.
ULID costs nothing extra to mint, removes the need for a separate ordering column, and makes keys
partition-prune-friendly. Folding the determinism rule in now, before per-table ratification, stops four
observation sub-types from each re-deriving mint / propagation semantics (the shallow-ratification
anti-pattern T0.12.6's decomposition exists to avoid).

**Related:** Decision 95 (the trace/observation model these keys identify; session-id.yaml additive
amendment), Decision 96 (temporal standard -- the event timestamps minted under clause 2), Decision 84
(ULID SCD2 envelope on ops tables -- the identity convention extended here), Decision 82 / CD.33 clause 2
(mint-once-outside-retry precedent for ducklake_writer), CD.9 (partition-everything -- ULID time-ordering
serves `day()` pruning), docs/contracts/session-id.yaml, docs/contracts/telemetry-lexicon.yaml, T0.12.6
(per-table contracts author these keys).

---

## Decision 96: Telemetry temporal + partition standard -- event-time day(started_at) UTC, no trade_date (Decided)

**Status:** Decided
**Date:** 2026-06-23
**Warehouse ID:** dec-096 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Two temporal defects sit in the draft telemetry design. (1) `trade_date` -- a market-data partition
concept -- leaked into telemetry scaffolding, where it has no meaning: a telemetry session is not scoped
to a trading day. (2) the original T2.4 (partition-everything) framing prescribed
`day(last_updated_timestamp)` for "ops/telemetry" jointly, conflating two different table shapes:
ops_recommendations / ops_decisions are
SCD2 tables whose `last_updated_timestamp` is the mutation-envelope partition basis, whereas telemetry is
insert-once EVENT data with no SCD2 envelope. Partitioning telemetry by `last_updated_timestamp` is wrong
twice over -- the column is an ops-SCD2 concept, and event data should partition by event time, not
mutation time. Timestamp typing (tz-awareness, UTC) is also unspecified.

**Decision:**
1. **Telemetry is event-time data.** Each telemetry table partitions by `day()` of its OWN event-time
   column in UTC -- the session / observation start. Canonical: telemetry_sessions -> `day(started_at)`;
   telemetry_observations -> `day(started_at)`; telemetry_transcripts -> `day(created_at)`;
   telemetry_agents -> `day(started_at)` (or none if realized as a pure dimension; settled at T0.12.6).
   `started_at` is the canonical telemetry event-time column.

2. **No trade_date in telemetry.** `trade_date` is a market-data concept and is absent from every
   telemetry contract. Any draft carrying it drops it.

3. **last_updated_timestamp is an ops-SCD2 concept, not telemetry.** Telemetry rows are insert-once; they
   carry no SCD2 mutation envelope and do not partition on `last_updated_timestamp`. A correction to a
   telemetry row is a new append governed by Decision 97's mint-once rule, not an SCD2 update.

4. **Timestamps are timezone-aware UTC, ISO-8601.** Every telemetry timestamp (started_at, ended_at,
   created_at, per-observation times) is stored UTC, tz-aware. Naive or local-time timestamps are
   rejected at the boundary.

**Realization -- T2.33 / DuckLake, not T2.4:**
T2.4 (the Iceberg partition sweep) was CLOSED on 2026-06-23 (PR #239) and re-grounded to the 3 live
personal-account ops Iceberg tables, explicitly moving ops/telemetry to DuckLake-on-Neon (Decision 78/84)
and DuckLake partition-as-code to T2.33 (ALTER-conditional per Decision 81). Telemetry is therefore not in
the Iceberg sweep's scope: this standard (`day(started_at)` UTC for telemetry) is realized when telemetry
is rebuilt on its DuckLake substrate via T2.33's partition-as-code, ALTER-conditional per Decision 81 and
not warranted below the row/file-count threshold. No T2.4 edit is made; T2.4's closeout already separates
the ops-SCD2 (`day(last_updated_timestamp)`) basis from the telemetry event-time basis, corroborating this
decision.

**Related:** Decision 95 (the tables this partitions), Decision 97 (boundary-minted event timestamps),
CD.9 (partition-everything -- this supplies the telemetry column choice CD.9 left per-table), T2.4
(Iceberg partition sweep, CLOSED 2026-06-23 / PR #239 -- telemetry moved to DuckLake / T2.33, not this
sweep), T2.33 (DuckLake partition-as-code -- the telemetry realization path), Decision 81 (CD.9
ALTER-partitioning mechanism), Decision 78 (DuckLake adoption), Decision 84 (ops SCD2
`last_updated_timestamp` envelope -- the concept kept distinct from telemetry),
docs/contracts/telemetry-lexicon.yaml.

---

## Decision 95: Canonical telemetry trace/observation model -- 4 tables, root unification, canonical lexicon (Decided)

**Status:** Decided
**Date:** 2026-06-23
**Warehouse ID:** dec-095 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The draft telemetry pipeline (the seven `telemetry_*` tables T0.12.6 was scoped to ratify) is a star
schema that grew by accretion, not design, with three structural defects:
- **Rootless agent invocations.** telemetry_agent_invocations carries no session_id, so sub-agent work
  does not join the session star schema at all -- observability that cannot be correlated to the run that
  produced it.
- **Four sibling event tables with one shape.** telemetry_phases, telemetry_steps,
  telemetry_process_events, and telemetry_model_calls are all "a timed thing that happened during a
  session" -- the same node shape with different attributes. Four sibling tables force four near-duplicate
  contracts, four sets of joins, and shallow ratification (the failure mode T0.12.6's per-table
  decomposition was meant to avoid, revealed here as a modelling problem, not a plan-granularity problem).
- **No canonical vocabulary.** "phase", "step", "event", "span", "trace", "invocation" are used loosely
  and inconsistently across the draft, prompts, and DQ scaffolding, with nothing authoritative to anchor
  the per-table contracts to.

Ratifying seven contracts over this draft would ratify the accretion. The model must be settled first.

**Decision:**
Adopt a session-rooted trace/observation model (the OpenTelemetry / Langfuse shape) and collapse the
seven draft tables to FOUR canonical tables:

1. **telemetry_sessions** -- the trace ROOT. One row per session; PK session_id. Root-unification anchor:
   every telemetry row traces back to a session. A spawned sub-agent gets its own session linked to its
   parent via `parent_session_id` (nullable), so agent work is rooted, not orphaned. Carries project_id
   as a forward-declared field (realized at T2.17, per the project-id.yaml Class C pattern).

2. **telemetry_observations** -- the unified node table. One row per observation (a timed node in the
   session's trace tree); PK observation_id; FK session_id (root); FK parent_observation_id (nullable
   self-reference, building the tree). An `observation_type` discriminator
   (phase | step | process_event | model_call | ...) absorbs the four collapsed sibling tables. This is
   the core unification: one node table with a type column and a parent pointer, not four sibling tables.

3. **telemetry_transcripts** -- large-payload sidecar. Prompt / response / transcript blobs, linked by FK
   to observation_id (and session_id), kept OUT of telemetry_observations so the node table stays small
   and hot. One row per blob.

4. **telemetry_agents** -- the agent dimension. Identifies WHICH agent (agent_type, model, version) a
   session / observation belongs to, joined by session_id / observation_id. Replaces
   telemetry_agent_invocations: agent identity becomes a rooted dimension, and the agent's WORK is
   captured as observations / linked sub-sessions, resolving the rootless-invocation defect.

**Root unification rule:**
Every telemetry row is reachable from a telemetry_sessions row. There are no rootless telemetry entities.
Cross-agent linkage uses `parent_session_id` (sub-agent session -> spawning session); in-session
structure uses `parent_observation_id` (observation -> parent observation). The two pointers together
form one connected trace tree per top-level run.

**Collapse rule:**
telemetry_phases, telemetry_steps, telemetry_process_events, telemetry_model_calls are NOT separate
tables. They are values of `telemetry_observations.observation_type`. The discriminator's accepted-value
set is ratified per-table at T0.12.6.

**Canonical lexicon:**
The canonical vocabulary (session / trace, observation, observation_type, transcript, root unification,
parent_observation_id, and the deliberately-unused "span") is promoted now to
docs/contracts/telemetry-lexicon.yaml -- a free-form (non-ritual) vocabulary registry the CD.25 drift
gate skips (no top-level `contract:` / `class:`, per the read-engine.yaml / storage-substrate.yaml
precedent). The lexicon is term-level only: per-field DQ checks live in
config/agent/data_quality/telemetry.yaml and per-field contract semantics in the Class A contracts. It
exists so every downstream telemetry contract, prompt, and agent ratifies against ONE vocabulary.

**session-id.yaml amendment (recorded; executed at T0.12.6):**
session-id.yaml (Class C, ratified at T0.12.7) is amended ADDITIVELY -- semantic_break: false -- when the
new contracts land: a `prose_improvement` entry updates its stale six-table star-schema description to the
four-table model, and a `governance_note_add` entry records ULID as the canonical target for session_id
(Decision 97). No format flip and no field change occur in the amendment; the closed CD.25 change_class
vocabulary (INTENT Part 4 Invariant 3) carries no breaking-format class precisely because such a change is
forward-declared, not applied in place. The edit is coupled to the new Class A contracts and is therefore
part of the re-scoped T0.12.6, not this REPORT-ONLY decision.

**Decision 67 reversal-predicate restatement:**
Decision 67's STRATEGIC-clause reversal condition names the draft tables telemetry_process_events,
telemetry_model_calls, telemetry_phases, telemetry_steps -- which this decision collapses into
telemetry_observations. Left unamended, the predicate would name tables the canonical model deletes and
become unsatisfiable. It is restated to track the canonical model: "telemetry_sessions,
telemetry_observations, telemetry_transcripts (and telemetry_agents) confirmed operational end-to-end with
passing data quality checks, AND executor re-enabled per CD.17 / T4.2." The four named draft tables are
replaced by telemetry_observations; telemetry_sessions is retained; telemetry_transcripts /
telemetry_agents are added. The AND-executor-re-enabled clause and the CD.17 / T4.2 gate are unchanged.
Decision 67's reversal-condition text gets an inline pointer to this restatement.

**T0.12.6 re-scope:**
T0.12.6 (Ratify Class A telemetry table contracts) is re-scoped in this plan from seven per-table plans
to: four table contracts (telemetry_sessions, telemetry_observations, telemetry_transcripts,
telemetry_agents), two new Class C key contracts (observation-id.yaml, parent-observation-id.yaml at
contract_version: 1), and the additive session-id.yaml amendment above. decomposition_hints, exit_criteria,
name, and intent are updated; related_decisions records this decision. The roadmap edit lands with this
decision.

**Scope:**
REPORT-ONLY. No code or runtime behaviour changes. Deliverables are this decision (95-97), the
platform-roadmap edits (T0.12.6 re-scope, T2.4 alignment), and the canonical lexicon. The new Class A /
Class C contracts and the session-id.yaml amendment are authored later under the re-scoped T0.12.6; this
decision settles the model they ratify to.

**Related:** Decision 96 (telemetry temporal / partition standard), Decision 97 (telemetry identity +
determinism -- ULID, boundary-minting), Decision 67 (STRATEGIC-clause reversal predicate restated here
against the canonical model), CD.25 (pre-codegen contract ratification ritual -- the model these contracts
ratify under), Decision 84 (DuckLake substrate; ULID envelope; backfill-from-DECISIONS.md path), Decision
86 (rationale-to-decisions, model-to-tier_items, no new prose-architecture doc -- the lexicon is a
machine-parseable registry, not prose), T0.12.6 (re-scoped here), T0.12.7 (session-id.yaml / project-id.yaml
Class C precedents), T2.17 (project_id realization), docs/contracts/session-id.yaml,
docs/contracts/telemetry-lexicon.yaml, docs/ROADMAP-PLATFORM.yaml.

---

## Decision 94: Correct Decision 92 point 3 -- github_ci_apply OIDC trust must also trust the environment sub (Decided)

**Status:** Decided
**Date:** 2026-06-22
**Warehouse ID:** dec-094 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 92 point 3 ratified the CD.35 Wave 3 / T2.22 security model with the clause "The privileged
role OIDC trust stays pinned to refs/heads/main," on the stated premise that a GitHub Environment's
required-reviewer gate does NOT change the OIDC token's sub claim. The live VP7-VP11 end-to-end test
(2026-06-22) disproved that premise. When a job declares `environment: tf-gated-apply`, GitHub
OVERRIDES the OIDC sub to `repo:OWNER/REPO:environment:tf-gated-apply` (the environment claim REPLACES
the ref claim). With trust pinned to `refs/heads/main` only, the `gated-apply` job could never assume
`github_ci_apply` -- it failed `sts:AssumeRoleWithWebIdentity` (AccessDenied) on every run. The
T2.22 gated-apply path was non-functional as merged; all static gates (validate, terraform-validate,
unit tests, code review) passed and only live verification caught it.

**Decision:**
Correct Decision 92 point 3. `github_ci_apply`'s OIDC trust `sub` condition is a two-value
exact-match list, trusting BOTH:
- `repo:OWNER/REPO:ref:refs/heads/main` -- the routine auto-apply path (apply-sandbox job, no
  job-level environment), and
- `repo:OWNER/REPO:environment:tf-gated-apply` -- the gated-apply job (whose declared environment
  overrides the sub).

This is SAFE and does not weaken the security model: a token bearing
`sub=...:environment:tf-gated-apply` can ONLY be minted by a job that declares that environment, and
such a job cannot begin until the Environment's required reviewer approves. The environment sub is
therefore itself approval-gated -- belt-and-braces with the guard's fail-closed routing. The
Environment-gates-EXECUTION model of Decision 92 is unchanged; what is corrected is the false claim
that the sub stays `refs/heads/main`. `agent/*` and `pull/*` remain unable to assume the role.

The trust change is an IAM/trust change and was admin-applied locally (the gated CD path it fixes
could not apply it), then confirmed by a no-op merge (PR #222). Re-running VP7-VP11 with a throwaway
IAM tag then proved the gated path applies end-to-end: routed green -> reviewer approval -> assume-role
success -> saved plan.bin applied verbatim (no re-plan) -> convergence record green with plan_sha.

Secondary correction (VP10): the gated-apply always-run red-on-failure convergence write depends on
the same OIDC apply-role creds; a failure AT OR BEFORE the credentials step cannot write the red
record. The backstop is ci-rca, which triggers on the terraform-apply-sandbox workflow_run failure
conclusion independent of the record -- so a creds-stage failure still files a source=ci_rca rec and
is not silently masked. Documented at the record_write step; no code change required.

## Decision 93: Platform-MVP boundary + deferred_post_mvp lifecycle status (Decided)

**Status:** Decided
**Date:** 2026-06-20
**Warehouse ID:** dec-093 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The platform's telos is removing the human from the autonomous loop, which qualifies almost everything as "MVP-critical" -- there is no natural MVP boundary under that framing. Post-MVP hardening work (secrets rotation, backup/DR posture, devcontainer substrate, portal artefacts) competes on the same eligibility surface as critical-path items, making next-eligible noisy and sequencing ambiguous.

**Decision:**
Platform-MVP boundary defined as: "the autonomous loop closes end-to-end with no human in the critical path of one iteration (rec -> implement -> validate -> merge -> deploy -> observe -> next rec)." Introduces a `deferred_post_mvp` lifecycle status and the defer-by-exception rule to resolve the boundary without enumerating the MVP set upfront (which would trip the frame-lock anti-pattern, Decision 75).

**Boundary definition:**
An autonomous loop iteration is: a recommendation is filed, implemented by the agent, validated, merged, deployed, and produces the next observable state -- with no human in the critical path. When this closes end-to-end, the platform is at MVP. Everything after that is hardening / polish.

**Defer-by-exception rule:**
New platform work is MVP-critical by default; items leave MVP scope only by conscious deferral. The MVP set is never enumerated -- only the deferred set is. This avoids the frame-lock anti-pattern of committing to a fixed MVP surface before the autonomous loop is proven closed.

**deferred_post_mvp status semantics:**
- Living cousin of `reserved` (which marks tombstones/superseded items). Unlike `reserved`, a deferred item is REACTIVATABLE per-item by restoring status -> not_started.
- Excluded from next_eligible and tier-completion math (alongside `reserved`); a tier of [complete, deferred_post_mvp] is treated as complete and does not wedge active_tier().
- Absent from the lean preflight/orient digest, so parked items are excluded from the eligibility surface rather than displayed there. Recorded in a separate `deferred_post_mvp` bucket in the FULL compute_state (queryable on demand).
- No live platform item (status == not_started or in_progress) may depend_on a deferred_post_mvp item. The platform_roadmap.py model_validator enforces this at load time (fail loud at validation, never silently strand a dependent).

**PLATFORM-INTERNAL scoping:**
The no-live-dep restriction is enforced by platform_roadmap.py model_validator ONLY -- not added to product_roadmap.py. Cross-roadmap edges from ROADMAP-PRODUCT.yaml to deferred platform items (e.g. E.env.3 -> PLATFORM:T2.9) are permitted and remain dormant until product work begins, per the platform-first directive [ratified with reversal conditions by Decision 133 (2026-07-16); the circular "until product work begins" / "product roadmap is activated" end-condition is superseded by Decision 133's named conditions]. These edges are revisited when the product roadmap is activated.

**Items parked (deferred_post_mvp) at Decision 93 ratification:**
- T2.8 (backup/DR posture for the personal account): clean leaf; hardening, not on the autonomous-loop critical path.
- T2.9 (secrets rotation policy + automation): hardening; platform edge T2.14 corrected (see below); product edge E.env.3 left dormant per platform-first directive [ratified with reversal conditions by Decision 133].
- T2.11a (Codespaces devcontainer substrate): public-surface polish; not in the autonomous-loop critical path.
- T2.11b (public-portal artefacts): co-parked with T2.11a (depends_on T2.11a; same public-surface-polish category; downstream T2.12/T2.13 already complete so nothing live is stranded).

**T5.2 exclusion rationale:**
T5.2 (teardown) was considered but excluded: it is a near-due cost-saver (grace elapses ~2026-06-28), user_action_required, and currently eligible. Parking it would hide a billing-stopper from the eligibility surface.

**T2.14 depends_on edge correction:**
T2.14 (broker credential routing) declared depends_on: [T2.1, T2.9]. The T2.9 edge was incorrect: T2.14 provisions its own Secrets Manager surface and does not require rotation automation as a prerequisite. Edge re-pointed to depends_on: [T2.1]. Required for the no-live-dep invariant to pass with T2.9 parked.

**Related:** Decision 73 (sandbox-only / forward-fix posture -- the boundary is consistent with it, not a re-derivation), Decision 75 (frame-lock anti-pattern; defer-by-exception avoids it), Decision 80 (validate.py single source of truth; the invariant lives in platform_roadmap.py model_validator, picked up by validate_platform_roadmap via load()), Decision 86 (no new prose-architecture doc; boundary semantics live in Decision 93 + ROADMAP-PLATFORM.yaml agent_instructions only), Decision 90 (four-tier workflow; parked items are excluded from the next_eligible eligibility surface, not surfaced in an orient bucket).

---

## Decision 92: Ratify CD.35 -- agent-native Terraform CI/CD (Wave 1 shipped) (Decided)

**Status:** Decided
**Date:** 2026-06-19
**Warehouse ID:** dec-092 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

> **Amended by Decision 154 (2026-07-26):** the gated-apply job's always-run convergence-record
> write (point below) is narrowed from a two-branch (green/red) write to THREE branches -- a
> pre-apply failure (no apply step ran) now merges a non-status `infra_error` marker instead of
> latching red. This body is otherwise unedited; see Decision 154 for the full derivation,
> constraints, and reversal conditions.

**Problem:**
CD.35 (Agent-native Terraform CI/CD) specified a five-wave architecture ratified via the log-decision
path once Wave 1 / T2.20 shipped. Wave 1 is now SHIPPED AND PRODUCTION-PROVEN: the convergence
substrate landed in PRs #142 (#179 hardening, #185 SSM closure), real CONVERGENCE_RED latches fired
(rec-2236 @7678d3e, rec-2238 @bfa5229f), were refused server-side, filed as source=ci_rca recs, and
cleared via the dispatch-ack path -- behavioural proof of T2.20 exit criteria 1/2/4. The roadmap
still showed T2.20 not_started and CD.35 state:pending with a pending_log_decision_lambda clause.

**Decision:**
Wave 1 (T2.20) is SHIPPED. The following Wave-1-established architecture is ratified:

1. **Authorization division (INTENT 5.9):** native controls own AUTHORIZATION (required checks,
   linear history, GitHub Environment reviewer gate); the deterministic guard narrows to plan-CONTENT
   policy. The guard fails closed on IAM/trust/destroy changes and is never the authorization lock.

2. **Server-side convergence anchor -- sole hard block (INTENT 5.5):** the apply job writes a durable
   S3 convergence record (pipeline-writer-identity-only write-IAM; always-run, red-on-failure) and
   reads it as a precondition that refuses to apply against a red record. An absent record = first-apply-
   allowed (pass-on-absent). The record lives in its own S3 prefix outside tfstate/ so the PR role reads
   it without seeing tfstate. A red record clears ONLY via the workflow_dispatch acknowledge-and-retry
   path; a plain push never clears red (auto-allow-descendants rejected on linear-history main).
   terraform-converged is an ADVISORY PR status ONLY (not a required check -- required would wedge the
   autonomous fix-merge or be admin-bypassed; main-protection strict=false + bypass_mode=always, Decision 83).

3. **Routine-vs-gated autonomy boundary and Environment-gates-execution security model (ratified
   DIRECTION for Waves 2-5, INTENT 5.4 + 5.6):** routine (guard-PASS, non-IAM) changes ride the
   record-backed pipeline; high-blast changes (IAM/trust/destroy) route to a GitHub Environment whose
   required reviewer gates JOB EXECUTION. The privileged role OIDC trust stays pinned to refs/heads/main.
   [CORRECTED by Decision 94 (2026-06-22): the trust clause here is wrong. A job declaring
   environment: tf-gated-apply gets sub=repo:OWNER/REPO:environment:tf-gated-apply, so github_ci_apply
   must ALSO trust the environment sub (proven by VP9). The Environment-gates-EXECUTION model is
   unchanged; the environment sub is approval-gated and safe. See Decision 94.]

4. **Rejected guard-self-grant exception + privilege-tiering (INTENT 5.8, Wave 4):** the CI/CD role's
   own IAM moves to a separate terraform/bootstrap/ root applied out-of-band, breaking the self-grant
   cycle. Without that separation any automated handling of the fail-closed set is self-approval.

5. **Authority-budget + ratchet model (CD.35 points 6-9, IMPLEMENTED by T2.25 / 2026-06-29):**
   an explicit permissions boundary on github_ci_apply plus boundary-propagation condition keys
   and deterministic in-budget/out-of-budget diff classification shipped in T2.25.
   > **Widened -> realized by Decision 144 / T2.48 (2026-07-22):** `authority_budget.json` is now v2 --
   > `in_budget_actions` is `["create","update"]` (create newly in-budget) and the managed-role set is
   > the boundary-carrying `agent-platform-*` prefix (`in_budget_managed_role_prefix`), not the
   > branch/pr enumeration -- extending Decision 129's per-service prefix from reads to writes. The
   > guard's in-budget predicate (`_classify_iam_change`) widened to READ the v2 shape (subset-match on
   > actions + prefix-match on the target role + explicit apply-role self-exclusion); NO new
   > classification stage, fail-closed control theory retained. The concrete v1 example below (action
   > set `["update"]`, branch/pr roles) is retained as historical context.

   Concrete in-budget classification (machine-readable: `terraform/bootstrap/authority_budget.json`):
   - **In-budget** (auto-apply, still subject to subagent review): resource type
     `aws_iam_role_policy` or `aws_iam_role_policy_attachment`, action set `["update"]`,
     target role name `agent-platform-github-ci-branch` or `agent-platform-github-ci-pr`
     (managed boundary-carrying roles). No trust diff (trust check runs BEFORE IAM classification
     in the guard; a trust change on an in-budget resource type is always gated).
   - **Out-of-budget / gated** (routes to tf-gated-apply Environment): trust diffs, destroys,
     role CREATES (new trust surface), or any IAM change not matching all three in-budget
     criteria above. Role creates stay gated in this v1 narrowing.
   - **Fail-closed**: missing or unparseable budget table = all IAM treated as out-of-budget
     (Decision 77). Budget path overridable via `TF_AUTHORITY_BUDGET` env var (test isolation).

   Ratchet criteria: autonomy is earned and revocable PER CHANGE-CLASS -- the budget widens on
   measured track record (per change-class, after N incident-free auto-applies) and narrows on
   incident. Budget amendments via the bootstrap tier only (`terraform/bootstrap/`); subagent
   review advises, never locks. The drift gate (`scripts/validate.py:validate_authority_budget`)
   asserts the budget table stays in sync with the IAMRoleWriteBounded SCP in
   `terraform/bootstrap/github_ci_apply.tf` (pre and full tiers).

   The sole SoT for the apply-model and guard-classification rules is
   `docs/contracts/environment-taxonomy.md` Axis A + Guard classification subsection.
   CD.35 is fully ratified (no re-ratification via this amendment).

6. **Apply failures wire into ci-rca (Decision 72/55):** apply failures file source=ci_rca recs;
   drift detection (scheduled plan, alarm-only) files via the ops portal. Nothing auto-remediates.

Waves 2-5 and Wave X are RATIFIED DIRECTION -- architecture decided, implementation pending their
respective tier items (T2.21/T2.22/T2.23/T2.24/T2.25).

**Supersession of CD.35's pending_log_decision_lambda clause:**
CD.35's discipline_points contained a "does NOT edit DECISIONS.md while pending; ratified via the
log-decision path" clause and field filed_via: pending_log_decision_lambda. This Decision 92 DELIBERATELY
supersedes that clause -- the DECISIONS.md-edit + `ops_data_portal --backfill-decisions-md` ETL is the
sanctioned ratification path per Decision 84 (canonical source + ETL) and the Decision 90/91 precedents
(both ratified via the same path on 2026-06-18/19). The pending_log_decision_lambda mechanism is
superseded as of this Decision; CD.35 is now filed_via: ops_decisions:dec-092.

**Rationale:**
Mirrors CD.31->Decision 78 and CD.33->Decision 81: architecture ratified once the implementation
is production-proven. The DECISIONS.md-edit path (per Decision 84 + Decision 90/91 precedents) is
cleaner than the log-decision path, which required a separate Lambda invocation -- Decision 84 retired
the Lambda path for ops_decisions (DuckLake writer now owns it) and Decision 84 I-2 established backfill
ETL from DECISIONS.md as the rebuild path. Ratifying CD.35 here confirms that the DECISIONS.md-edit
+ backfill ETL is the canonical ratification path for all future candidate decisions.

**Related:** CD.35 (ratified here; filed_via: ops_decisions:dec-092), T2.20 (Wave 1 shipped),
T2.21-T2.25 (direction ratified; implementation pending), Decision 77 (guard fail-closed; narrowing is
T2.25/Wave X), Decision 83 (main-protection non-wedging; advisory-not-required advisory status),
Decision 84 (DECISIONS.md canonical source + ETL), Decision 90/91 (edit-and-backfill precedents),
Decision 55 (alarm + file recs; nothing auto-remediates), Decision 72 (RCA-as-plan-source).

---

## Decision 91: Ratify OQ.15 option (a) -- agent verb surface extends ducklake_writer/reader; T0.6 closed via supersession; CD.10 six-Lambda enumeration superseded (Decided)

**Status:** Decided
**Date:** 2026-06-18
**Warehouse ID:** dec-091 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
OQ.15 (opened 2026-06-09, audit F-008) asked whether the agent-facing verb surface should (a) extend
the ducklake_writer/ducklake_reader verb sets directly, or (b) use thin verb Lambdas fronting them.
The question was left open pending T0.6 plan time, but T0.6's original Terraform skeleton was never
built in the personal account -- instead the ducklake_writer/reader closed boundary shipped (T2.17/T2.19)
and T2.28 landed the NAMED_READS registry, realizing the functional scope of T0.6 via a different
mechanism. Six src/lambdas/<verb>/ stub mocks (log_rec, log_decision, query, update_rec, list_tools,
maintenance) and their work-root Terraform (lambda_tooling_platform.tf, lambda_tooling_outputs.tf,
never applied per CD.21) accumulated as dead artefacts. CD.10's six-Lambda enumeration remained
state:pending while the shipped architecture made it illustrative in practice (Decision 81 cl.2).
The roadmap carried stale files_in_scope / exit_criteria pointing at deleted stubs in six tier items
(T0.7a/b/c, T1.1/T1.2/T1.3) and stale query/ path comments in T2.5 and T2.7.

**Decision:**
1. Ratify OQ.15 option (a): the agent-facing verbs extend the ducklake_writer/ducklake_reader verb
   sets directly. This ratifies the shipped architecture per Decision 81 cl.2 (extensible verb surface,
   NOT a fresh design pick) and Decision 84 I-3 (named-verb closed boundary). The shipped routing is:
   scripts/ops_data_portal.py routes file_rec->write_ops/file_ops, update_rec->update_ops, and
   file_decision->write_ops on ducklake_writer; reads use the NAMED_READS registry
   (src/common/ducklake_scd2_schema.py) via ducklake_reader.named_read. Function-URL+AWS_IAM is
   live in terraform/personal/ducklake_lambdas.tf; PlatformDev/PlatformAdmin invoke via
   DuckLakeInvokeRuntime (platform_roles.tf:142-152 + AdminOps).
2. Close T0.6 (Lambda-tooling-platform Terraform skeleton) as realized-via-supersession. The verb
   surface T0.6 planned to provision is already live as the ducklake_writer + ducklake_reader closed
   boundary. T0.6's bootstrap_completion_exempt: true permits completion with CD.10 still state:pending.
3. Supersede CD.10's six-Lambda enumeration (log-rec, log-decision, query, update-rec, list-tools,
   maintenance as separate Lambdas). The enumeration was illustrative per Decision 81 cl.2; this
   decision records its supersession. CD.10's PlatformDev/PlatformAdmin two-principal allow-list is
   RETAINED -- realized in DuckLakeInvokeRuntime. CD.10 itself remains state:pending; only the
   six-Lambda enumeration clause is superseded.
4. Re-ground tier items T0.7a, T0.7b, T0.7c, T1.1, T1.2, T1.3 files_in_scope and exit_criteria to
   the named-verb writer/reader surface. Status remains not_started; likely silent-completion of each
   item is flagged in their notes for dedicated per-item closeout plans.
5. Delete the six src/lambdas/<verb>/ stub directories, tests/test_lambda_stubs.py,
   terraform/lambda_tooling_platform.tf, and terraform/lambda_tooling_outputs.tf. Retain
   terraform/lambda_tooling_iam.tf (agent_auth.tf circular reference + T1.15 ownership).

**Rationale:**
The Decision 81 cl.2 extensible-verb-surface and Decision 84 I-3 named-verb boundary together made option
(a) the natural landing point: fewer Lambdas, verb logic co-located with the schema gate, and the NAMED_READS
registry already provides the query-surface discovery needed for T0.7c/T1.2/T1.3. Option (b)'s per-verb SLO
benefit (T1.9) does not outweigh the added hop and the deployment blast radius of six separate Lambdas.
Recording the resolution now cleans the roadmap of stale artefacts and stops agents from planning against
deleted stub paths, while the conservative not_started status for T0.7x/T1.x preserves the formal closeout
gate for each item's unit-test coverage and import_mode edge cases.

**Related:** Decision 81 cl.2 (extensible verb surface superseding CD.10 six-Lambda enumeration),
Decision 84 I-3 (named-verb read boundary + I-2 writer-owned keyspace), Decision 79 (per-Lambda deploy
gating -- stubs are status:stub, no deploy step required), CD.10 (six-Lambda enumeration superseded here;
two-principal allow-list retained; state:pending unchanged), CD.33 (closed read/write boundary ratified),
OQ.15 (resolved to option (a) here), T0.6 (closed via supersession), T0.7a/b/c/T1.1/T1.2/T1.3
(re-grounded; still not_started), ROADMAP-PLATFORM.yaml.

---

## Decision 90: Four-Tier Workflow Architecture (Decided)

**Status:** Decided
**Date:** 2026-06-19
**Warehouse ID:** dec-090 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 42 established the Three-Tier Workflow Architecture: `/plan` -> `/implement` -> `/develop-executor`. Since then, a read-only orientation step `/orient` was added as the entry point to the pipeline (PR #183, 2026-06-18). Multiple instruction surfaces (AGENTS.md, `.claude/skills/orient/SKILL.md`) continue to cite Decision 42 as a "three-tier" architecture, misframing the pipeline for planning agents that now enter via `/orient`.

**Decision:**
The canonical end-goal workflow architecture is four tiers:

```
/orient -> /plan -> /implement -> /develop-executor
```

Tier responsibilities:
- `/orient` -- read-only orientation: surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and up to N disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Produces a chat reply only; writes nothing.
- `/plan` -- clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.yaml`. Scopes work; does not execute code changes directly.
- `/implement` -- executes IMPLEMENTATION plans directly; scopes STRATEGIC plans into atomic recommendations the executor consumes.
- `/develop-executor` -- autonomous executor: consumes atomic recommendations from the priority queue.

**Current operational state (2026-06-19):** `/orient` -> `/plan` -> `/implement` only. Executor and STRATEGIC plans are frozen per Decision 67 / CD.17; `/implement` makes code changes directly during the freeze.

**Supersedes:** Decision 42 (Three-Tier Workflow Architecture). Supersedes Decision 42's framing; Decision 42's body is preserved intact with its status annotated "Superseded by Decision 90".

**Related:** Decision 42 (superseded here), Decision 67 (executor + STRATEGIC freeze; the current operational constraint), Decision 76 (.claude/ as the canonical interactive layer).

---

## Decision 88: Neon catalog egress is a first-class budget -- four standing access-pattern invariants + a measurement obligation; amends CD.34's "negligible add-on" (Decided)

**Status:** Decided
**Date:** 2026-06-16
**Warehouse ID:** dec-088 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
On 2026-06-15 the DuckLake-on-Neon catalog breached Neon's free-tier 5 GB/month egress cap and forced a paid-plan upgrade. CU-hours stayed well under quota -- the low-compute / high-egress signature of bulk metadata transfer, not computation. The catalog holds only METADATA (row data is S3 Parquet; inlining is disabled), so the egress was self-inflicted access-pattern amplification, code-verified to four sources: (D1) a daily full-catalog pg_dump DR job; (D2) a fresh cold DuckLake ATTACH on every reader/writer invocation with no warm reuse, amplified by DuckDB's postgres scanner sequential-COPY of `ducklake_file_column_stats` per query (ducklake #859); (D3) production catalog metadata never snapshot-expired, so D1/D2 grow unbounded; (D4) a preflight reader fan-out of ~9-10 calls per session plus a full-table resync after every portal write. Nothing treated catalog egress as a budgeted resource, and nothing measured it -- the breach was the first signal.

**Decision:**
1. Catalog egress is a FIRST-CLASS cost budget for the platform, ranked beside compute and storage. It protects the near-zero-cost operating posture (Decision 84 / Decision 81) and is governed by four standing access-pattern invariants that any code touching the catalog MUST uphold:
   (i) Reuse warm catalog connections across sequential invocations -- never a cold ATTACH per request where a container can hold one. A dead session (Neon scale-to-zero) is the one expected reopen condition (Decision 55: any other error still raises).
   (ii) Never re-query data already in the local read-cache. Preflight and other read paths serve from the rows the single warm-up sync already pulled; a genuinely-needed warehouse read uses a registered named verb (Decision 84 I-3), never an ad-hoc re-fetch of data in hand.
   (iii) Keep the catalog compacted: non-destructive merge runs on ALL live ops_* tables on a cadence sized to write rate (the smaller the `ducklake_file_column_stats` footprint, the smaller every read's per-query egress). Destructive expiry/cleanup/orphan deletion stays behind a proven restore drill (see clause 4).
   (iv) Size the DR dump cadence to the durability tier and the MEASURED egress, not to a habit. A daily full dump is not free when egress is metered.
2. Measurement obligation: catalog metadata size and Neon egress-by-source must be instrumentable on demand, so this budget is enforceable rather than aspirational. The `catalog_stats` maintenance action (read-only; reads the catalog's own Postgres metadata via psycopg2 -- no ATTACH, no data_path) is the supported measurement path (the DR bucket and direct CloudWatch reads are IAM-blocked from the dev role by design). It reports total catalog-metadata bytes (exact), the `ducklake_file_column_stats` row estimate (the #859 driver), and a per-ops_*-table breakdown. The dump size and implied monthly-egress numbers are folded into the Warehouse measurement record once the post-deploy `catalog_stats` invocation runs against the live catalog (the mechanism lands with this Decision; the figures are a post-deploy measurement step, not a planning-time guess).
3. CD.34 amendment: CD.34 called the daily pg_dump-to-S3 DR "a negligible add-on". That holds for STORAGE (a versioned, lifecycle-expired bucket) but is FALSE for EGRESS -- a daily full-catalog dump is a session-independent metered-egress line. The DR cadence is lowered daily -> weekly (cron(0 3 ? * SUN *)); paid-tier Neon's 7-day PITR provides finer-grained recovery BETWEEN weekly full dumps, preserving the durability floor while cutting the pg_dump egress line ~7x. The co-required freshness-alarm lookback widens from >25h to ~8 days (evaluation_periods/datapoints_to_alarm 25 -> 192) so a weekly dump never leaves the alarm in perpetual ALARM.
4. D3b deferral (destructive GC on ops_*) is OUT OF SCOPE and gated. Only non-destructive merge runs on production ops_*; expanding destructive expire_snapshots / cleanup_old_files / delete_orphaned_files to ops_* is gated by the rec-2113 pg_restore restore drill (T2.26 owns its retirement). GC_TABLE_SCOPE stays smoke-only until that gate clears -- compaction without a proven restore is not licensed to delete production catalog state (Decision 55).

**Rationale:**
The free-tier breach proved the cap is real and the access pattern, not the workload, drove it. Encoding catalog egress as a named budget with standing invariants prevents the class of mistake recurring: each invariant maps to a verified driver (i->D2, ii->D4, iii->D3, iv->D1), so a future change that reintroduces a cold-ATTACH-per-request or a read-cache re-fetch is checkable against a ratified rule rather than rediscovered via the next bill. The measurement obligation makes the budget enforceable -- a budget you cannot read is a wish. The work is shaped as one IMPLEMENTATION effort (Decision 67 / CD.17 STRATEGIC freeze). Form follows Decision 86: the durable rationale lives here, field/measurement semantics ride the maintenance action + ops.yaml, and no new standing prose-architecture doc is created (intent-doc-freeze compliant). Citation correction (2026-06-09 audit F-033): Decision 82 governs the DIRECT-vs-pooled endpoint basis and the EC8 churn-gate N=8->4 frame -- NOT the cold-resume warm-up; the preflight warm-up attribution to Decision 82 was a mis-citation and is corrected to this Decision's invariant (i).

**Related:** Decision 84 (DuckLake sole ops backend; named-verb closed boundary I-3; no write buffering I-4 -- the cache refresh is downstream of the synchronous writer commit, never a write source), Decision 81 (maintenance cadence design, clause 6 -- merge/GC primitives this tunes), Decision 82 (DIRECT-vs-pooled endpoint + EC8 churn-gate frame; the cold-resume warm-up is NOT Decision 82, audit F-033), Decision 55 (loud failure -- the warm-connection reopen handles ONE expected condition; GC stays gated), Decision 86 (deliverable routing; intent-doc-freeze), CD.34 (amended here: "negligible add-on" is storage-true / egress-false), rec-2113 (DR restore-drill HARD GATE that unlatches D3b), rec-2096 (cold+warm connect-latency measurement, closed by this work), rec-2244 (ducklake_reader 502 -- the downstream symptom relieved by removing this egress pressure; closes on operational confirmation, not this merge), rec-2087 (Neon egress IP-allow-list -- a separate access-control concern, left open), T2.18 / T2.19 / T2.26 (`docs/ROADMAP-PLATFORM.yaml`).

---

## Decision 87: Plans, plan-critiques, and plan-revisions as first-class warehouse entities; authority-flip deferred to the autonomous producer (T4.x) (Decided)

**Status:** Decided
**Date:** 2026-06-14
**Warehouse ID:** dec-087 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`/plan` produces git-tracked `PLAN-{slug}.yaml` artefacts (Decision 85, `PlanDocument` schema_version 1) reviewed via PR (Decision 76 cl.3). This is correct for the interactive era but does not support the autonomous plan -> critique -> revision loop that T4.x requires: plans are not queryable, plan<->rec linkage is not first-class, critique verdicts are ephemeral subagent output, and revision directives have no machine-actionable home. We record the destination (plans as warehouse entities) and, separately, the deliberate decision NOT to build it now -- so neither is re-litigated.

**Decision:**
1. Plans, plan-critiques, and plan-revisions WILL become first-class warehouse entities. Destination state: warehouse-authoritative, on the DuckLake-on-Neon SCD2 substrate (Decision 84).
2. The authority-flip from git to warehouse is TIMED to the existence of the autonomous plan producer (`plan_agent`, a T4.x capability gated behind the CD.17 executor freeze) -- NOT now. For the interactive era, git/PR remains the authoritative approval surface, because `PLAN-{slug}.yaml` artefacts are human-authored, low-frequency, and diff-reviewed -- every property that favours git as source-of-truth. Warehouse-authoritative is the right model only once a machine produces plans at frequency.
3. Until the flip, `ops_execution_plans` is a downstream read-projection of the git-authoritative `PLAN-{slug}.yaml`, populated by git->warehouse ETL. This is the legitimate write path under the Decision 84 warehouse-SoT invariant -- the same sanctioned "ETL from a non-warehouse source of truth" pattern as `DECISIONS.md -> ops_decisions`, not a read-cache-as-write-source violation. The warehouse-SoT invariant remains absolute for operational records (recs, decisions, queue); plans are scoped as projection-until-T4.x.
4. [Amended 2026-08-19, PLAN-executor-two-plane-roadmap-encoding: consolidated onto ONE plans table.] Lifecycle lands on a single plans table plus telemetry, by purpose:
   - `ops_execution_plans` (SCD2) -- the plan document + status gate: `pending -> approved | rejected | needs-revision` (lifecycle-state closure per Decision 70).
     [Amendment 2026-07-03, Decision-70 mis-cite (audit f80508b): the "lifecycle-state closure per
     Decision 70" citation above is a mis-cite -- the closure-proof principle is Decision 103;
     Decision 70 governs Physical Deletion of Bootstrap Records.]
   - The original clause 4 split plan state across a SECOND, separate plans table and a companion `ops_plan_revisions` directive table. That two-table split is RETIRED-BEFORE-BUILT: neither table was ever created, so there is no migration, no deprecation window and nothing to delete. `ops_plan_revisions` was a critic-authored DIRECTIVE INBOX (machine-actionable revision directives -- the imperative "change X -> Y", authored by the critique agent for planning-agent consumption), never a history table; the consolidation therefore holds because `critique_history`, already a column on the single plan row, IS that directive's home under the critic-or-gate authorship boundary -- the critic or the gate appends the verdict and its imperative there, and the planner reads them from the row it already fetches rather than recording a verdict against itself. The SCD2 grain of the single plans table (one row per plan revision; current = latest revision) is a supporting fact, not the reason.
   - telemetry -- the critique's full deliberation/rationale (observability), for optimization and debugging. The imperative lives in `critique_history` on the single plans table; the deliberation lives in telemetry; they are not duplicated.
5. RBAC is enforced at the verb layer, extending the Decision 84 closed writer boundary (I-2 writer-owned keyspace, I-3 named verbs) and the Decision 81 cl.2 extensible verb surface: planning agents get an `insert_plan` verb that hardcodes `status=pending` and cannot mutate status; critique agents get `set_plan_status` plus the critique-append verb on the single plans table, and cannot author plan bodies. [Amended 2026-08-19, same plan: the original grant named `insert_revision`, whose target table clause 4 above retires, so that one verb is RE-POINTED at the critique-append verb on the single plans table `ops_execution_plans`, which writes `critique_history` and nothing else. Clause 5's verb-RBAC PRINCIPLE -- writer-layer role scoping -- is unchanged, and stays a writer concern rather than a schema one.] All plan writes transit `ops_data_portal` (Single-Portal Invariant, Decisions 69/78); ids are writer-allocated atomically, never client-side.
6. Plans and recs remain distinct grains: a rec is WHAT work should be done; a plan is HOW to implement it. Planning and implementation stay sequentially coupled (the executor's runtime `ExecutionPlan` stays in-process; only its persisted document would ever join `ops_execution_plans`). Decoupling -- where plans are written faster than implemented and can go stale against an evolving repo -- is gated on a plan-staleness story (base-commit pinning + divergence detection + re-validate-before-implement) that does not yet exist. Frame-lock-aware deferral per Decision 75.

[Amendment 2026-08-19, PLAN-executor-two-plane-roadmap-encoding -- RESIDENCY-SCOPED; clause 4 consolidated onto one plans table.]
Clause 2 above times the git-to-warehouse flip to the existence of the autonomous plan producer, while
T4.5's deferral rationale held that no warehouse consumer of plans exists until the T4.6 loop. Those two
are CIRCULAR once that producer is designed: the producer cannot function until its own plans are
warehouse-readable, so the producer's existence cannot itself be the trigger that makes them so. This
amendment breaks the circularity by separating RESIDENCY from AUTHORITY, and it moves RESIDENCY only.
Warehouse RESIDENCY of executor-authored plans -- written to, and read back from, `ops_execution_plans`
by named verb -- is a PREREQUISITE for T4.2 rather than a consequence of it. The AUTHORITY flip is NOT
moved: it stays timed to T4.6 exactly as clause 2 intended, so git/PR remains the authoritative approval
surface for the human `PLAN-{slug}.yaml` planning surface until T4.6 executes that flip, and Decision 85's
git-authoritative clause is not superseded early. Executor-authored plans are born warehouse-native and
never had a git life, so for them there is nothing to flip at all. Clause 4 is amended in the same act:
there is ONE single plans table, `ops_execution_plans`, and the originally-proposed two-table split is
retired-before-built, with `critique_history` on that one row carrying the critic-or-gate directive the
retired companion table would have held. The surviving NAME is ruled rather than left open:
`ops_execution_plans` is the implemented name, carried on 278 matching lines across 80 files, 32 of them
load-bearing -- terraform, `config/lambda/ducklake/field_semantics.yaml`, `.importlinter`, the
verification and data-quality registries, the portal and sync modules, and 12 test modules -- while the
rejected alternative name occurs on 30 prose-only lines across 8 files and in no schema, terraform, code,
config or test file. Ease of standardisation decides it, and the ruling adds no work: the table already
exists, so no rows, verbs, schema, terraform or contract entries move in either direction.

**Rationale:**
No downstream warehouse consumer of plans exists today, and the ones that would (autonomous `plan_agent`, plan-revision loop) are far off behind CD.17/T4.2. Flipping authority now would route the interactive loop through warehouse round-trips it does not need, for no consumer -- building ahead of need. Recording the destination + timing now captures the design while it is fresh and prevents both re-litigation ("should plans be warehouse entities?") and premature build. Form follows Decision 86: rationale here, field/schema semantics to `docs/contracts/*` (the single plans table's schema + verb-RBAC contract, as extended), forward build intent to T4.x tier_items (T4.5-T4.7). No standing prose-architecture doc is created (intent-doc-freeze compliant).

**Forward note:** At the T4.x authority-flip, Decision 85's git-authoritative clause for plans (and the plan-scoping of the Decision 84 invariant in cl.3 above) is superseded by warehouse-authoritative; until then both stand. Build work, when it lands, decomposes into atomic IMPLEMENTATION-type plans -- no STRATEGIC plan is authored under the CD.17 freeze (Decision 67 STRATEGIC clause).

**Related:** Decision 84 (DuckLake sole ops backend; writer-owned keyspace; named-verb boundary -- substrate + write-path precedent), Decision 85 (`PLAN-{slug}.yaml` / `PlanDocument` -- the entity promoted), Decision 76 cl.3 (web PR/merge -- preserved interactive approval surface), Decision 81 cl.2 (extensible verb surface), Decision 86 (forward-routing form; intent-doc-freeze), Decisions 69/78 (Single-Portal Invariant), Decision 70 (lifecycle-state closure), Decision 75 (frame-lock-aware deferral), Decision 57 (autonomous-improvement control plane -- the loop this extends), CD.17/T4.2 (executor-freeze gate), T4.5-T4.7 tier_items (forward build), `docs/ROADMAP-PLATFORM.yaml`.

[Amendment 2026-07-03, Decision-70 mis-cite (audit f80508b): the "Decision 70 (lifecycle-state
closure)" citation above is a mis-cite -- the closure-proof principle is Decision 103; Decision 70
governs Physical Deletion of Bootstrap Records, not lifecycle-state closure.]

---

## Decision 86: INTENT prose docs retired -- architectural intent routes to roadmap tier_items, Decisions, or contracts; supersedes CD.14 (Decided)

**Status:** Decided
**Date:** 2026-06-12
**Warehouse ID:** dec-086 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The 18 `docs/INTENT-*.md` documents (~10.5k lines of prose) were authored to persist the owner's architectural vision across agent sessions. Two failure modes emerged: (1) **deliverables get lost** inside long narrative docs -- an agent must read the whole document to find what is actually actionable; and (2) the docs **drift** from live roadmap/decision state (e.g. CD.14 enumerated 10 docs to handle when 18 now exist; `ops-decisions-graduation` is half-superseded by Decision 84; several docs describe the pre-CD.27/28 executor substrate that no longer exists). Prose is a human-facing surface in an agent-first repo (NS.4, CD.13); the roadmap's YAML dependency edges now serve the cross-session-persistence role the INTENT docs were created for, readable without parsing narrative.

The pending CD.14 chose to *demote* INTENT docs to "non-authoritative detail-companions" -- keeping the prose, stamping a footer, roadmap-wins-on-divergence. That preserves the drift surface (a second place agents must sync) rather than eliminating it.

**Decision:**
1. **CD.14 is SUPERSEDED.** Its demote-and-keep-prose model is replaced by extract-and-retire. The candidate decision is marked `state: superseded` (by this Decision) in `docs/ROADMAP-PLATFORM.yaml`, and tier_item `T5.5` is repointed from "demote + footer" to "extract content into tier_items/Decisions/contracts, then delete" -- mechanised by `docs/intent-migration/MANIFEST.yaml`. (This Decision is a *ratified* numbered entry under the DECISIONS.md numbering authority; ratifying it is the act that supersedes the *pending* CD.14 -- the roadmap-YAML edit lands in the Wave 0 follow-on.)
2. **Forward routing rule (the "stop the bleeding" clause).** No new *standing prose-architecture / deliberation documents* anywhere under `docs/` -- the rule forbids the BEHAVIOUR, not merely the `docs/INTENT-*.md` filename glob (a doc renamed `docs/design-foo.md` or `docs/INTENTS/foo.md` is the same anti-pattern). Architectural content routes to its canonical machine-parseable home by type:
   - **Forward-looking deliverables / sequencing** -> `docs/ROADMAP-PLATFORM.yaml` (or `ROADMAP-PRODUCT.yaml`) tier_items, with `depends_on` edges.
   - **Rationale / choices / trade-offs** -> `docs/DECISIONS.md` (numbered) or `candidate_decisions[]` (pre-ratification).
   - **Field/contract semantics** -> `docs/contracts/*.yaml`.
   - **Already-ratified content** (a feasibility verdict or arc that graduated to a Decision) -> a pointer to that Decision; preserve any still-live trigger/watch-signal as a tier_item before removing the prose (the manifest's `delete_pointer` disposition).
   - **Unbuilt exploratory direction** still referenced by a governing CD -> keep as a contract or a CD-gated future tier_item, not a standing prose doc (the manifest's `defer_or_contract` disposition).
   - Deliberation that genuinely needs a working document uses a REPORT-ONLY plan deliverable scoped to a single decision, not a standing INTENT doc.
3. **The existing 18 are grandfathered** and retired wave-by-wave per `docs/intent-migration/MANIFEST.yaml` (Waves 1-5), each with its own per-doc drift reconciliation. A `scripts/validate.py` guard (added in Wave 0) rejects new standing prose-architecture docs while allowing the grandfather set. The allowed set is DERIVED from the manifest -- a doc is permitted iff it has a `documents[]` entry with `disposition_state != done` -- so it shrinks automatically as each wave deletes a doc and flips its entry to `done`, with no hand-maintained list. Deleting a grandfathered doc requires the inbound-reference sweep (manifest findings X1/X2/X6/X7) to pass first.
4. **Enforcement is wired in Wave 0** (`PLAN-intent-migration-wave0-enforcement`): `.claude/commands/plan.md`, `.claude/skills/planning/SKILL.md` (Documentation Artefact Design), and `AGENTS.md` (Agent-First Repository) gain the routing rule; the roadmap bookkeeping (CD.14 supersession + T5.5 repoint) and the validate guard land there.

**Fast-track rationale:** This governance change is ratified directly (not filed as a pending CD that waits on the log-decision Lambda) because it is a *documentation-governance* rule with no infrastructure dependency, it is needed *now* to stop the corpus growing during the multi-wave extraction it authorises, and it only tightens an already-ratified direction (CD.13 markdown-with-prose retirement; NS.4 agent-first). The migration work it scopes is large (Wave 0 + ~5 extraction waves); each wave is an IMPLEMENTATION plan per the Decision 67 / CD.17 STRATEGIC-plan freeze.

**Related:** CD.14 (superseded here), CD.13 (agent-first exemplar -- this enacts its prose-retirement thesis), NS.4 (the repo is for agents), Decision 67 / CD.17 (STRATEGIC freeze -- all migration waves are IMPLEMENTATION type), Decision 85 / Decision 76 (PLAN-*.yaml planning artefacts), Decision 84 (DuckLake / ops_decisions backfill path; ducklake-consolidation INTENT graduates to it), Decision 80 (bazel-feasibility graduation target), Decision 57 (amends the "INTENT authoritative for domain" grants as docs retire), Decision 75 (frame-lock pointers preserved on delete), CD.32 (multi-product-platform exploratory record). Mechanised by `docs/intent-migration/MANIFEST.yaml`.

---

## Decision 85: Ratify CD.22 -- PLAN-*.yaml planning artefacts with PlanDocument schema; amends Decision 76 clause 3 (Decided)

**Status:** Decided
**Date:** 2026-06-11
**Warehouse ID:** dec-085 (canonical; retired writer-era id reconciled per Decision 105)
**Renumbering note:** originally recorded as "Decision 84" by PR #127, allocated concurrently with the DuckLake-consolidation Decision 84 on a diverged branch (both 2026-06-11). Renumbered 85 at merge -- the consolidation number is cross-referenced from deployed Lambda code, contracts, and warehouse rows, so it keeps 84. PR #127's commit message predates the renumber and is unchanged; the Warehouse ID line above is now reconciled to canonical dec-085 per Decision 105 (dec-1091 was the pre-reconciliation writer-era id).

**Problem:**
CD.22 (pending, gates T1.11) prescribed migrating planning artefacts from PLAN-*.md to PLAN-*.yaml with Pydantic structural validation -- the last narrative-markdown artefact class in the planning pipeline (CD.13). Decision 76 clause 3 hard-codes the plan handoff artefact as `PLAN-{slug}.md`, which the migration supersedes.

**Decision:**
CD.22 is RATIFIED as implemented by T1.11. `PlanDocument` (`scripts/plan_document.py`, schema_version 1, `extra="forbid"`) is the canonical structure for `docs/plans/PLAN-{slug}.yaml`; `validate.py` enforces it in both the `--pre` and full presubmit tiers. `find_plan.py` resolves `.yaml` first; the `.md` path (find_plan.py, plan_audit.py, and the planning / implement / plan-critique skills in both skill roots) emits a deprecation warning for one release cycle, then is removed.

**Decision 76 clause 3 is AMENDED:** the handoff artefact reference reads `docs/plans/PLAN-{slug}.yaml` (was `.md`). The `find_plan.py` deprecation fallback is the transition bridge until the `.claude/commands/plan.md` / `implement.md` reconciliation rec lands.

Historical PLAN-*.md files remain in the working tree and commit history; none are retroactively converted (one-way, non-rolling migration). In-flight conversion list at implementation time (1 of 1): `PLAN-t1-11-plan-yaml-migration.md -> .yaml`.

**Rationale:** Mirrors the RoadmapDocument gate (T-1.5) and the Decision 79 ratify-in-implementing-PR precedent. The `.agents/skills/` mirrors were updated as voluntary legacy hygiene -- Decision 76 supersedes Decision 58's sync obligation; no sync obligation is claimed.

**Related:** CD.13, CD.22, T1.11, Decision 76 (clause 3 amended here), Decision 79 (ratification precedent), Decision 58 (superseded mirror rule), Decision 80 (registry-friendly check design).

---

## Decision 84: DuckLake is the sole ops-store backend; Athena ops estate retired; writer-owned keyspace; named-verb read boundary (Decided)

**Status:** Decided
**Date:** 2026-06-11
**Warehouse ID:** dec-084 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The T2.19 recs-first cutover left the ops store straddling two warehouses. The retained Iceberg copy stopped being a coherent rollback target the day writes moved to DuckLake (reads would time-travel while writes kept landing in DuckLake); the offline outbox inverted its purpose on ephemeral CC-web containers (gitignored pending files die with the container); client-side DynamoDB id allocation left the write boundary unable to police its own keyspace (a colliding write_ops create silently MERGEs); half-migrated read semantics produced the rec-2170 silent false zero; and preflight burned minutes polling Athena tables dead since the 2026-05-28 account migration.

**Ratified premises:** All dev sessions run on Claude Code on the web (no local). All Athena-resident ops data is discardable. ops_decisions is recreatable from DECISIONS.md. The ops store is small and single-writer in practice.

**Decision (four invariants):**
- **I-1 Single backend.** DuckLake-on-Neon (closed reader/writer Function-URL boundary) is the only ops-store backend. The `OPS_STORAGE_BACKEND` rollback flag is deleted. The T2.19 cutover's flag-based rollback mechanism (an AGENTS.md source-of-truth provision, not a Decision 81 clause -- Decision 81 cl.7's closed boundary is RETAINED and extended) is retired. The Athena/Iceberg ops estate (tables, `_current` views, ops_compaction, OpsWriter ops paths, VarChar coercion) is demolished without data migration once live writers are repointed; demolition of non-recreatable tables is gated on the rec-2113 catalog-restore drill (T2.26 START GATE).
- **I-2 Writer-owned keyspace (scoped).** The ducklake_writer owns the `rec-NNN` keyspace: `file_ops` allocates the id inside the write transaction (counter row in the same catalog commit; OCC conflict is the serialization point; client idempotency ULID makes response-lost retries replay-safe). The DynamoDB counters table retires. Sanctioned exceptions: `dec-NNN` follows the human-assigned DECISIONS.md numbering (callers supply `decision_id`); `test-`/probe prefixes remain caller-keyed via write_ops.
- **I-3 Named-verb read boundary (staged).** Application reads use pre-established verbs registered server-side in the ducklake_reader; caller SQL is removed from application paths. `query_ops` is RETAINED for the DQ harness (its checks, including history-table checks, are not yet expressible as verbs) and is restricted/retired in a follow-up once a dq_check verb family exists. Structural `{column, value}` filters replace SQL-fragment row filters (closes rec-2170).
- **I-4 No write buffering (per-table staging).** The recs and decisions pending outboxes are deleted now; a failed write fails loudly at the call site (transient-5xx retry is licensed by the idempotency key). The OpsWriter staging outbox survives ONLY for the not-yet-migrated telemetry/session_log/execution_plans paths and retires with them (Phase 3/4).

**Operational consequences:** destructive Lambda actions gain explicit-confirm guards (create_ops_tables force_recreate; catalog_reinit loses its production-schema default); the telemetry preflight health check is stubbed until telemetry re-lands on DuckLake (Phase 4); catalog DR remains the existing ducklake_catalog_dr nightly pg_dump, with the restore-drill format gap tracked as rec-2113.

**Related:** Decision 81 (CD.33 architecture retained and extended), Decision 79 (per-Lambda deploy gating governs the reader/writer redeploys), Decision 70 (queue current-state semantics preserved inside the priority_queue_current verb), Decision 69 (Single Portal Invariant unchanged), Decision 55 (loud-failure doctrine), T2.26/T2.27/T2.28 (roadmap carriers), T2.36 (Phase 4 telemetry re-lands on DuckLake).

[Amendment 2026-07-03, Decision-70 mis-cite (audit f80508b): the "Decision 70 (queue current-state
semantics preserved inside the priority_queue_current verb)" citation above is a mis-cite --
Decision 70 governs Physical Deletion of Bootstrap Records, not queue current-state semantics; the
queue current-state semantics referenced here are this decision's own `priority_queue_current` verb.]

> **[Amendment 2026-08-17, PLAN-agents-md-ambient-trim]:** rehomes the Iceberg-DELETE-resurrection
> mechanism condensed out of AGENTS.md's read-cache-is-never-a-write-source hard rule. An Iceberg
> DELETE removes only a snapshot; if the same row is re-staged from a stale local cache on any
> clone, runner, or worktree, it is re-injected as a new append and wins the SCD2 dedupe because
> `_prepare_record` (`scripts/ops_writer.py:199`) refreshes `last_updated_timestamp = now` --
> producing an infinite resurrection loop in which deletes never stick. Scoped to the
> still-Iceberg tables; the never-re-stage-from-a-read-cache rule applies to DuckLake tables (I-4)
> regardless.

---

## Decision 83: Branch Protection Now Active -- Amends Decision 89 Premise (Decided)

**Status:** Decided
**Date:** 2026-06-08
**Warehouse ID:** dec-083 (canonical; retired writer-era id reconciled per Decision 105)

**Problem:**
Decision 89 declared GitHub branch protection "permanently unavailable" for this repository under the free GitHub plan (private-repo restriction on `required_status_checks`). The repository was made public 2026-05-30 (Decision 73 / CD.21), removing that restriction. The `terraform/github/` human-gated local apply (CD.20 / T2.12) has since landed, activating the `main-protection` ruleset. Multiple instruction surfaces still assert the false "permanently unavailable" premise, misleading autonomous planning sessions.

**Decision:**
The "permanently unavailable" premise of Decision 89 is reversed. The `main-protection` ruleset is active (`enforcement = "active"`). Configuration: admin `bypass_mode = "always"`, `strict_required_status_checks_policy = false`, required checks = `pr-validate` + `terraform-validate` only, `terraform-converged` advisory-only (CD.35). The ruleset is deliberately non-wedging so the forward-fix model, the Decision 76 squash-merge flow, and autonomous merge all continue to hold.

The merge-gate design consequences of Decision 89 are PRESERVED, not overturned. Convention-plus-tooling remains the effective gate. GitHub-native auto-merge (Decision 76 deferred follow-up) is now technically unblocked.

**Live-probe verification (2026-06-08):**
- Branch protection: `main` `protected: true` (GitHub API, authoritative).
- Dependabot: 5 `dependabot/pip/*` branches active (authoritative).
- GHAS secret-scanning + CodeQL: 403 on alert endpoints (web PAT lacks `security_events`); configuration evidence = `terraform/github/repo.tf` `secret_scanning status=enabled` + committed `.github/workflows/codeql.yml` + CodeQL workflow runs (`success`). Live-probe verification outstanding; one-time UI confirmation recommended.

**Live-probe verification (2026-08-11):**
- Secret scanning: `scanning_status=enabled` (GitHub API, `repo_http_status=200`).
- Push protection: `push_protection=enabled` (same endpoint).
- Actions permissions: `actions_enabled=True`, `allowed_actions=all` (`actions_http_status=200`; alerts endpoint `alerts_http_status=200`).
- Run: https://github.com/benjamin-blake/agent-platform/actions/runs/31536138747 (workflow_dispatch, main @ 84f9209, 2026-08-11T21:04:49Z, conclusion=success) -- the sole Actions run id cited anywhere in this file.
- This is a point-in-time probe, not continuous coverage. The monitor-blind window 2026-07-06 .. 2026-08-10 saw all six scheduled runs fail unactioned because `GHAS_PROBE_TOKEN` was unprovisioned, so the three controls were UNVERIFIED across that window (not proven-disabled) until this run confirmed them. The monitor still carries no persistent-unavailability alarm, so a recurrence before this stanza's review_by would again surface to nobody.

**Reversal conditions:**
This live-probe annotation is re-verified, never silently renewed, when either of the following fires: (a) `GHAS_PROBE_TOKEN` nears or reaches its 2027-05-31 expiry -- re-verify the three controls and record dated evidence on this Decision, or mark them UNVERIFIED, then re-arm; or (b) the ghas-probe monitor goes blind again (no successful run in more than 14 days, the 2026-07/08 shape) -- investigate and restore probing, then update the evidence. This stanza schedules re-verification of Decision 83's live-probe ANNOTATION only, never re-decision of its holding: a token expiry cannot un-reverse Decision 89's premise, which stands independent of probe cadence.

```yaml reversal-conditions
decision: 83
review_by: 2027-04-30
on_trigger: "re-verify the three controls and record dated evidence on Decision 83, or mark them UNVERIFIED, then re-arm; never silently renew"
conditions:
  - id: probe-token-expiry
    kind: manual
    description: "GHAS_PROBE_TOKEN expires 2027-05-31 and its lapse makes the 2026-08-11 evidence above stale"
  - id: probe-monitor-blind
    kind: repo_state
    predicate: null
    params: {}
    description: "no successful ghas-probe run in more than 14 days, the 2026-07/08 recurrence shape"
```

**Related:** Decision 89 (premise reversed here; merge-gate design preserved), Decision 76 (foresaw reversal; deferred follow-up now unblocked), Decision 77 (guard rationale preserved -- guard is the plan-CONTENT control, not a branch-protection substitute), Decision 73 (public flip enabling the apply), Decision 75 (sanctioned premise correction).

---

## Decision 82: EC8 churn gate measures production invocation fan-out, not in-container thread contention (Decided)

**Status:** Decided
**Date:** 2026-06-07
**Warehouse ID:** dec-082 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
T2.17 EC8 (churn commit-latency) was red after PR #89's Branch-P investigation. The gate was implemented
as `action_churn` -- 8 `ThreadPoolExecutor` writers inside ONE Lambda container. Measured wall/cpu ratio
was 31.73x at 1024MB and 10.35x at 3008MB (account max). p95_cpu_ms ~862ms is already inside the
2000ms CD.33 budget; the ONLY failing term is scheduling delay from over-subscribing 8 CPU-bound DuckDB
engines onto <2 vCPU. Reaching budget in that model required ~6 vCPU (~10240MB), blocked by an AWS
account-age Lambda max-memory quota cap.

**Decision:**
Correct the EC8 measurement SUBJECT from "8 writers inside one container" to "N concurrent Lambda
invocations, each its own container/vCPU" -- the production write model ratified by CD.33 clause 3 /
Decision 81. This is a Decision-75 measurement-subject frame correction, not a budget relaxation.

**What is unchanged (NOT a Decision-55 relaxation):**
- Budget VALUES: `COMMIT_LATENCY_BUDGET_MS = 2000.0` and `OCC_COLLISION_RATE_BUDGET = 0.20` are UNCHANGED.
- Gate term: per-invocation wall p95 (`latency_ms`) -- the same term `action_churn` used. Switching the
  comparison to `commit_ms` (which excludes connect/cold-start) would be an implicit relaxation; wall
  is the pinned term.
- `OCC_MAX_ATTEMPTS` unchanged.
- Loud-fail semantics intact (Decision 81 clause 3): schema-gate reject and OCC-retry exhaustion still raise.

**What changes:**
- Concurrency level N steered `CHURN_WRITERS = 8 -> 4` (human steer, 2026-06-07). N is the fan-out
  width, NOT a budget VALUE; the 2000ms / 0.20 ceilings are untouched. Empirical basis below.
- EC8 gate: smoke-test fans out `CHURN_WRITERS=4` concurrent `_sigv4_invoke({"action":"churn_single"})`
  calls. A pre-warm phase first issues N concurrent `attach_check` invocations to bring N containers out
  of cold-start (cold-start is already covered by EC1 `lambda_attach`; EC8 measures warm steady-state).
  One setup invocation (`setup:true`) then pre-creates tables to avoid a CREATE race. The N bodies are
  aggregated into collision_rate + p95 wall + attribution breakdown (connect/commit/cpu/wall_cpu_ratio).
- Handler: new `action_churn_single` dispatches on `"churn_single"` -- setup path calls
  `create_scd2_tables(force_recreate=True)`; normal path runs ONE connect + ONE write
  (`_churn_one_single_write`, the production-representative single-commit unit, with a unique
  `writer_id` per invocation) and returns per-stage attribution. Connectionless action.
- The legacy `action_churn` (in-container 8-thread burst) is retained as an opt-in stress diagnostic
  via `--lambda-churn-incontainer`. A budget miss from that path is informational only, not a gate failure.
- `ducklake_writer` memory_size stays at 3008MB as baseline headroom (NOT reverted). Comment updated.
- The Lambda quota-increase requirement (filed as a blocker rec at PR #89) is WITHDRAWN; the frame
  correction removes the need for >3008MB to pass EC8.

**Empirical basis for N=8 -> N=4 (2026-06-07 live runs, warm containers, DIRECT endpoint):**
- Single warm invocation: wall 1078ms (connect 393ms + commit 681ms) -- well within budget.
- N=8 fan-out (post pre-warm): wall p95 2805ms FAIL. Degradation is concurrent-Neon saturation on the
  DIRECT endpoint -- 8 simultaneous ATTACHes inflate connect p95 393->1585ms and 8 simultaneous catalog
  writes inflate commit p95 681->2285ms. Not a DuckLake code defect; OCC sub-gate still passes (0.0).
- N=4 fan-out: wall p95 1160-1512ms across 3 runs, collision_rate 0.0 -- PASS with margin.
- N=4 remains a faithful OCC + multi-invocation concurrency exercise (CD.33 clause 3) on the unpooled
  DIRECT endpoint; if higher burst width is later required, the Neon pooled endpoint (pgBouncer) is the
  documented lever, tracked separately -- not a budget change.

**Rationale:**
Production ops writes (`file_rec`/`update_rec`) are independent single-commit Lambda invocations, each
its own container/vCPU. The 8-threads-in-one-container harness was harsher than and unrepresentative of
production, and CPU-starved in a way production never will. The architecturally-meaningful OCC-collision
sub-gate is preserved (and arguably exercised more faithfully) by N truly-concurrent invocations hitting
the same Neon catalog simultaneously. The concurrency model is OCC + multiple invocations per CD.33
clause 3; reserved-concurrency=1 or SQS FIFO are not the model.

**References:** CD.33 (production concurrency model, authoritative), Decision 81, Decision 75 (frame-
correction precedent), Decision 55 (no budget relax), Decision 79 (per-Lambda V3 gating). Catalog
authority: CD.34 (Neon), not Decision 78 clause 3.

---

## Decision 81: Ratify the DuckLake ops runtime architecture (CD.33); resolve OQ.7 / OQ.10 / OQ.11 (Decided)

**Status:** Decided
**Date:** 2026-06-04
**Warehouse ID:** dec-081 (canonical; retired writer-era id reconciled per Decision 105)

**Problem:**
Decision 78 adopted DuckLake for the operational lakehouse but deferred the runtime architecture and four
open questions to T2.16-T2.19. T2.16 (RDS catalog) is complete; T2.17-T2.19 cannot proceed without a
ratified answer to: how the ops Lambdas are decomposed, how writer concurrency is enforced against
DuckLake's OCC (OQ.10), how inlining is flushed and where durability lives (OQ.11), whether an Athena
escape hatch survives DuckLake's lack of an external reader (OQ.7), how current-state reads avoid full
scans, and what the agent-facing portal surface is. CD.10's earlier six-Lambda enumeration was
illustrative, not a settled architecture.

**Decision:**
Ratify CD.33 as the authoritative DuckLake ops runtime architecture:
1. Three-artifact runtime split -- ducklake_writer / ducklake_reader / ducklake_maintenance -- partitioned
   by access pattern for IAM-principal, scaling, and deploy/blast-radius isolation, NOT for concurrency.
2. Supersede CD.10's six-Lambda enumeration. CD.10's verbs were illustrative; this decision commits only
   to the writer/reader/maintenance path split and the closed read/write boundary. The verb/tool surface
   behind writer and reader is deliberately left extensible and is NOT frozen by this decision.
3. Concurrency (OQ.10): concurrent writers + bounded application-level OCC retry (backoff+jitter, fixed
   ceiling, loud-fail on exhaustion) in ducklake_writer. Idempotency is grounded by the write-id mechanism
   (below): a monotonic ULID minted once and reused across retries is the history logical key (DuckLake has
   no engine PKs), and the append is `MERGE ... WHEN NOT MATCHED THEN INSERT` on it, so retries de-duplicate.
   ducklake_maintenance runs as a singleton; the writer-vs-expire_snapshots race is closed by a GC older_than
   grace exceeding max in-flight write duration. Reserved-concurrency=1 and SQS FIFO are rejected as
   over-serialising.
4. Portal surface = read + write categories; the sync category is eliminated because DuckLake's atomic
   catalog-snapshot commit removes the outbox/drain step. Writes are atomic at the catalog commit (no
   external sequencing); aborted commits leave orphan Parquet reclaimed by delete_orphaned_files. The
   Decision 69 Single-Portal invariant -- as carried forward by Decision 78 (which already superseded
   Decision 69) -- is PRESERVED: all writes transit scripts/ops_data_portal.py; only the transport changes.
5. ducklake_writer owns the schema-enforcement gate -- the single, un-bypassable write chokepoint; schema
   rejection and OCC-retry exhaustion fail loudly.
6. ducklake_maintenance is two deterministic scheduled cadences with no LLM / agent invocation: a daily
   non-destructive merge_adjacent_files (compaction; self-correcting) and a separately-cadenced GUARDED
   destructive GC (expire_snapshots -> cleanup_old_files -> delete_orphaned_files) behind a retention floor
   (expire 30d history / 7d current, never below the last 2 snapshots), an older_than deletion grace (>=7d),
   and a circuit breaker (abort+page at >20% files or >10GB; weekly cadence; no scheduled cleanup_all).
   OQ.11 resolved to option (c): inlining DISABLED (ducklake_default_data_inlining_row_limit=0) for
   governance tables so writes land in S3 immediately, eliminating the catalog-only durability window;
   per-table, telemetry may retain inlining.
7. Closed read/write boundary. OQ.7 resolved: no Athena escape hatch -- every read via the reader, every
   write via the writer, nothing out-of-band. Break-glass = the audited PlatformAdmin principal expanded to
   catalog+S3 read for non-routine inspect/repair; catalog DR = a daily PITR export to a dedicated S3 bucket
   with a tested restore runbook. History partitions by day(created_timestamp), current by bucket(N, id)
   (CD.9 ALTER at creation); a partition-prune smoke test gates T2.17/T2.19.
8. current write-through projection: reads come from a materialised Type-1 current table; each write is one
   DuckLake transaction (INSERT history + MERGE current from the in-hand delta). history is the append-only
   source of truth; current is rebuildable from history for DR (deterministically, ordering by
   last_updated_timestamp then ULID). Keys (no engine-enforced PK/FK): history PK = auto-generated monotonic
   ULID; rec_id is the natural key; last_updated_timestamp is high-precision, stable-per-write, ordering-only.
   DQ enforces ULID PK uniqueness, current-version uniqueness (structural via the current MERGE key on
   rec_id), and update_rec in-transaction referential existence.
9. OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal default), not
   pre-empted here.

**Capability basis:** clauses 4(atomicity)/6(partition prune)/7(single-txn multi-table + MERGE)/8 were
VERIFIED against the official DuckLake documentation (ducklake.select) before ratification: multi-table
single-snapshot ACID transaction, MERGE INTO, no engine PK/FK (ULID is a logical key enforced by MERGE+DQ),
OCC + application retry, `ducklake_default_data_inlining_row_limit=0` + `ducklake_flush_inlined_data`,
`expire_snapshots`/`cleanup_old_files`/`delete_orphaned_files`/`merge_adjacent_files` semantics, and
`ALTER ... SET PARTITIONED BY` (post-ALTER-only) with `day()`/`bucket(N,col)` transforms and pruning. The
one verified caveat encoded into the design: DuckLake GC deletion safety is a soft time-based deferral, so
the `older_than` grace must exceed the max in-flight reader/writer duration. The write-id is RESOLVED
(ULID logical PK + stable high-precision timestamp); the only T2.17 code task is moving the `_prepare_record`
`now()` re-stamp out of the OCC-retry loop.

**Rationale:**
The split is by access pattern because that is what differs operationally -- a write principal that can
mutate the catalog, a read principal that cannot, and a maintenance principal that runs DDL -- so isolating
them isolates IAM blast radius and deploy risk; concurrency is handled by DuckLake's OCC, not by collapsing
the Lambdas. OCC retry beats reserved-concurrency=1 / SQS FIFO because ops writes are idempotent id-keyed
SCD2 appends, so a conflicted snapshot is safe to retry without serialising the whole write path. Inlining
is disabled for governance tables because the catalog-only durability window is an unacceptable data-loss
exposure for irreplaceable records; the resulting small files are a cheap, self-correcting cost paid down by
daily compaction, while destructive GC is decoupled onto a slower guarded cadence so it can never race a
slow reader or runaway a delete. current is materialised as a write-through Type-1 projection because
"latest per id" is unprunable, so deriving it at read time forces a full scan; a single atomic DuckLake
transaction across history+current keeps them from drifting without external orchestration. The closed
boundary (no Athena escape hatch) is not a limitation we tolerate but the design goal: a lakehouse where
every read and write is mediated and authorised, with one audited break-glass path for DR. The agent verb
surface is left open precisely to avoid re-committing CD.10's mistake of enumerating a "final" surface
prematurely.

**Related:** CD.33 (ratified here), CD.10 (six-Lambda enumeration superseded; the six are status:stub mocks,
confirming illustrative; two-principal allow-list retained; state:pending),
Decision 78 (adopted DuckLake; deferred this runtime architecture; superseded Decision 69), Decision 79
(per-Lambda deploy gating -- the DuckLake Lambdas deploy + smoke-test per CD.16), Decision 69 (Single-Portal
invariant preserved as carried forward by Decision 78),
CD.15 (typed query reader -- refined), CD.8 (DuckDB engine -- unchanged), CD.9 (partitioning via ALTER),
CD.24 (per-Lambda manifests), OQ.7 / OQ.10 / OQ.11 (resolved), OQ.12 (left to T2.17).

---

## Decision 80: Build-Tooling Direction -- defer Bazel/Pants now; do-less baseline; decompose validate.py tool-free (Decided)

**Status:** Decided
**Date:** 2026-06-04
**Warehouse ID:** dec-080 (canonical; retired writer-era id reconciled per Decision 105)

**Problem:**
A first-principles design conversation proposed adopting Bazel to manage the `scripts/validate.py` monolith and the forthcoming CD.27 agent fleet. On a single-language (Python + Markdown), sub-scale (~36.5k first-party SLOC, one developer), agent-first repo with no compiled build, adopting a polyglot-scale build system risks frame-lock (Decision 75) and large ongoing BUILD-maintenance toil for benefits the repo largely already holds or has sequenced ahead in the roadmap.

**Decision:**
Per the evidence (a C1-C10 claims-verification matrix at commit `ddb85a0`, merged in PR #64):
1. **Do NOT adopt Bazel or Pants repo-wide now.** Only C1/C1b (premise) and C7/C8 (Bazel-specific cost) discriminate against Bazel; C3/C5/C10 bind the lighter do-less path equally (sequencing, not anti-Bazel); C9 (durable-functions readiness) is orthogonal to the build tool.
2. **Adopt the do-less baseline** -- `import-linter` (cycle + layering enforcement), a dependency lockfile, a wired revisit trigger, and a fail-closed edit-scope hook -- as the immediate-next IMPLEMENTATION plan (`PLAN-do-less-baseline`); not a STRATEGIC plan (Decision 67/79 freeze retained), no executor recs.
3. **Decompose `validate.py` tool-free** as a separate IMPLEMENTATION plan. This Decision ratifies the *direction* (a local importable check-registry, NOT a Lambda; `validate.py` stays the thin CLI so the "ci.yml-first" single-source-of-truth invariant holds); the registry *mechanism* (severity-bearing Check protocol, affected-set selection, producer/consumer ordering) is designed in that plan, not ratified here.
4. **Revisit a build orchestrator (evaluate Pants AND Bazel)** only on a wired trigger: executor `concurrency > 1` (T4.4 -- T4.1 owns emitting the concurrency signal) AND (a KG.13 test-impact/caching tier_item is filed OR a measured `_FAST_TIER_BUDGET_SECONDS` breach recurs). The CD.27 ~10-artifact fleet is a watch-signal, not a trigger (firing on it alone re-litigates Decision 79's deliberate "no transitive resolution").

**Rationale:**
At T4.1 concurrency = 1, the genuinely build-tool-only benefit (content-addressed fleet caching with reproducible multi-artifact builds) is roadmap-time-ordered to T4.4/KG.13; the dependency-closure "oracle" is already computable (`ast`/`networkx`, installed); reverse-closure test selection is roadmapped at KG.13, not yet present (`pytest --picked` is changed-test-file selection only). Decision 79 chose explicit per-Lambda manifests with "no transitive resolution" -- the opposite of Bazel's automatic-closure model. Bazel's sandbox is build-time hermeticity, not a live agent edit-scope guard; edit-scope containment for the CD.27 fleet is a present hook/IAM concern (cf. `.claude/hooks/never_on_main.py`), orthogonal to the build tool. The three module-import "cycles" are function-local deferred-import artifacts (the module-load graph is acyclic), so they are Bazel/Gazelle friction owed equally to `import-linter`, not a hard blocker.

**Consequences:**
- `PLAN-do-less-baseline` lands `import-linter` + a lockfile + the two wireable revisit-trigger arms + the edit-scope hook; an explicit owner-obligation is recorded that T4.1 emit the concurrency signal.
- The `validate.py` decomposition is a separate IMPLEMENTATION plan (its registry mechanism designed there); the dominant cost is the `test_validate.py` patch-path migration (239 of 262 patches bind off `validate.<symbol>`).
- No BUILD/WORKSPACE/`pants.toml` files are introduced.

**Related:** Decision 43 (validate.py SLOC waiver this remediates), Decision 60 / Decision 73 (two-tier diff-aware CI the do-less path extends), Decision 75 (Frame-Lock Anti-Pattern, applied to the assessment itself), Decision 67 / Decision 79 (STRATEGIC freeze retained; Lambda-deploy lifted); ROADMAP KG.13, T4.1/T4.4, CD.27 (revisit triggers); the bazel-feasibility supporting analysis (PR #64, commit `ddb85a0`; prose retired per Decision 86).

---

## Decision 79: Ratify per-Lambda packaging manifests + per-Lambda deploy/verify gating; lift Decision 67 Lambda-deploy clause (Decided)

**Status:** Decided
**Date:** 2026-06-03
**Warehouse ID:** dec-079 (canonical; retired writer-era id reconciled per Decision 105)

**Problem:**
Blanket Lambda-deploy freeze (Decision 67) + whole-src/config copytrees in `build_lambda.py`: verification tier follows filesystem layout rather than the runtime import contract. Config bundled into inactive CLI Lambdas. Plans adding files under `src/` or `config/` incur blanket V3 + DEFERRED tax even when no Lambda handler imports the new code (T0.12 case). Lambda zips carry payload they do not need. Deploy boundary invisible to reviewers.

**Decision:**
Ratify CD.16 (per-Lambda deploy/verify gating) and CD.24 (per-Lambda packaging manifests) as the authoritative architecture. Concretely:

- **Manifest = SSOT:** Each Lambda artifact owns `src/lambdas/<slug>/manifest.yaml` (Pydantic-validated `LambdaManifest` schema). The manifest lists handlers, includes, assets (runtime filesystem reads), config paths, and pip packages. No transitive resolution.
- **Coverage invariant:** `validate_lambda_manifest_coverage` in `validate.py` fails CI if any `src/lambdas/<name>/` directory lacks a manifest.
- **Bundle-completeness gate:** `validate_lambda_bundle_completeness` stages each active artifact into a temp dir, checks handler import-resolution, and asserts every declared `assets[]`/`config[]` path is staged. Full presubmit tier (NOT `--pre`) per Decision 73.
- **Tier from manifest graph:** A plan modifying files named in any active manifest triggers V3 + per-Lambda deploy steps. Pure additions to `src/` or `config/` that no manifest references stay V2.
- **Reverse ONLY Decision 67 Lambda-deploy clause:** The blanket `DEFERRED: build_lambda.py --deploy` pattern is withdrawn. Per-Lambda build/deploy/smoke-test steps are required for plans that modify active artifacts.
- **STRATEGIC clause retained:** Decision 67's STRATEGIC-plan freeze survives via CD.17 / T4.2. Step 12d of plan-critique is unchanged.
- **runtime_config tier declared, fetch deferred:** The `runtime_config[]` manifest field declares SSM/AppConfig paths; the fetch mechanism is a separable follow-on.
- **Decision 44 boundary affirmed untouched:** `build_lambda.py`, `validate.py`, `lambda_manifest.py`, and the planning/critique SKILLs are NOT executor-machinery. `scripts/llm_client.py`, `scripts/llm_utils.py`, `scripts/tool_runtime.py` are executor-boundary files but are only NAMED in the data-pipeline manifest's `includes`, never edited.

**Rationale:**
CD.16 and CD.24 are ratified together because they are one coupled architecture, not two independent changes: CD.16 ("which Lambdas a plan must deploy/verify") is policy without mechanism until CD.24's manifests make "which files a Lambda bundles" authoritatively answerable. Splitting them would ship a gating rule that still infers scope from filesystem layout -- the exact defect being retired. The manifest graph is the single source of truth from which both the deploy-scope decision (`compute_affected_artifacts`) and the file-pattern registry (`derive_lambda_file_patterns`) derive, so the verification tier now follows the runtime import/asset contract instead of where a file happens to live.

Only Decision 67's Lambda-deploy clause is lifted -- not its STRATEGIC-plan clause -- because the two clauses gate on different, independent conditions. The Lambda-deploy freeze was a workaround for executor-telemetry trust leaking into deploy decisions; per-Lambda gating (now mechanically enforced) is the correct replacement, so that clause reverses here. The STRATEGIC-plan freeze gates on the executor pipeline being paused (CD.17 / T4.2), which is unchanged by this work; reversing it here would un-block plans whose recommendations still have no consumer. Amending Decision 67 in place (rather than superseding it) preserves the audit trail for the surviving clause.

**Related:** Decision 67 (Lambda-deploy clause LIFTED, STRATEGIC clause retained), Decision 78 (ratification-mechanism precedent), Decision 48 (deterministic tier classifier), Decision 44 (executor boundary), Decision 76 (web MCP merge flow), Decision 43 (SLOC governance), CD.13 (agent-first manifests), CD.16, CD.24 (ratified here).

---

## Decision 78: Adopt DuckLake for the operational lakehouse (Decided)

**Status:** Decided
**Date:** 2026-06-02
**Warehouse ID:** dec-078 (canonical; retired writer-era id reconciled per Decision 105)

**Problem:**
The Iceberg-on-S3-metadata read path has proven operationally brittle for the ops/telemetry workload: the Athena-based reader is slow for interactive agent queries, the DuckDB-on-Iceberg snapshot read requires a full metadata scan on every invocation, and the staged CD.31 proposal formalises DuckLake v1.0 as the superior format for ops and telemetry tables -- a metadata-in-RDS-PostgreSQL + data-in-S3-Parquet open table format natively embedded in DuckDB that eliminates the Glue catalog dependency and enables sub-second DuckDB queries directly against S3 Parquet data. OQ.13 (the sole ratification-blocking open question, resolution_tier CD.31) is resolved here by generalising NS.1.

**Decision:**
1. Adopt DuckLake v1.0 for the operational lakehouse (ops and telemetry tables only). Full ratification of CD.31, enacted now including supersessions.
2. Scope: ops_recommendations, ops_decisions, ops_priority_queue, ops_execution_plans, ops_session_log, and all telemetry tables migrate to DuckLake. Product tables (D.lake.*, market_data Iceberg tier) REMAIN Iceberg per the KG.1 platform/product boundary. Market-data DuckLake assessment is deferred to FP-C.
3. Catalog backend: RDS PostgreSQL (db.t4g.micro, single-AZ, PITR enabled) as the DuckLake catalog metadata store -- a durable Glue-analog, NOT a query engine. DuckDB performs all computation against S3-backed Parquet data.
4. Supersedes Decision 50 (superseded by Decision 78: append-only-Iceberg write path -> append-only-DuckLake write path; same append semantics, new format).
5. Supersedes Decision 56 (superseded by Decision 78: SCD2 schema reproduced in DuckLake; optionally extended by ducklake_table_changes CDC and time-travel for richer audit).
6. Supersedes Decision 51 (superseded by Decision 78: JSONL-staging write path -> DuckLake writer in FP-B). CRITICAL: the Decision 69 Single-Portal primitive-level invariant is PRESERVED -- all ops writes continue to go through scripts/ops_data_portal.py; only the underlying staging mechanism changes from local-file outbox to DuckLake writer. The JSONL-staging path physically continues until FP-B/T2.19 migrates the write path.
7. Supersedes Decision 69 (superseded by Decision 78: JSONL outbox staging replaced by DuckLake writer in FP-B). The Single-Portal primitive-level invariant is PRESERVED, not removed. The portal abstraction layer (scripts/ops_data_portal.py) is unchanged; only the transport below it changes in FP-B.
8. Generalises NS.1 (OQ.13 resolution): NS.1 now reads "S3 + open table format at every scale" -- Iceberg for market-data/product tables, DuckLake for ops/telemetry per this decision.
9. Physical migration (OpsWriter replacement, DuckLake writer, SCD2 migration) is deferred to FP-B (T2.19), gated on T2.16/T2.17/T2.18. (Note: this clause originally read "Lambda deploy deferred per Decision 67"; Decision 79 subsequently lifted Decision 67's Lambda-deploy clause -- the DuckLake writer/reader Lambdas deploy + smoke-test per-Lambda per CD.16.)

**Rationale:**
DuckLake v1.0 eliminates the Glue catalog dependency while preserving S3 as the durable data plane, keeping NS.1 intact. The RDS catalog is a metadata store, not a query engine -- NS.3 actively supports a small managed cloud state-store for this role. The Single-Portal invariant is preserved at the abstraction level: the portal interface (scripts/ops_data_portal.py) is unchanged; only the underlying staging transport changes in FP-B/T2.19. Iceberg remains for product/market-data tables (KG.1 boundary), ensuring no cross-domain blast radius.

**Related:** CD.31 (ratified), Decision 50 (superseded by Decision 78), Decision 51 (superseded by Decision 78), Decision 56 (superseded by Decision 78), Decision 67 (interim ratification path used because T-1.1 is not_started; its Lambda-deploy clause was subsequently lifted by Decision 79, STRATEGIC clause retained), Decision 69 (superseded by Decision 78; Single-Portal invariant PRESERVED at primitive level -- portal abstraction unchanged)

---

## Decision 77: Two-Axis Environment/Phase Taxonomy + Sandbox Auto-Apply (Decided)

**Status:** Decided
**Date:** 2026-05-30
**Warehouse ID:** dec-077 (canonical; retired writer-era id reconciled per Decision 105; renumbered from 76 to resolve a parallel-authoring collision with the web-workflow-migration decision merged as Decision 76 in PR #10)

**Problem:**
`docs/INTENT-ci-cd-architecture.md` section 6 and Decisions 24/73 affirm a PLATFORM sandbox -> SIT
-> PROD promotion train as future-state, while `docs/ROADMAP-PRODUCT.yaml` retired_items (the "Phase
Infra-Env / Multi-account staging+production model" entry) retired a "sandbox -> staging ->
production" model as overkill. These describe TWO DIFFERENT axes that were being conflated: a
PLATFORM deploy axis (infrastructure) and a PRODUCT config-promotion axis (strategy lifecycle).
Separately, Decision 35 asserts "apply is never automatic", which -- read unconditionally -- blocks
the autonomous infrastructure-improvement substrate the North Star depends on, even for a mocked
sandbox where no real capital is at risk.

**Decision:**

1. **Two-axis taxonomy (the durable fix).** Establish `docs/contracts/environment-taxonomy.md` as
   the canonical vocabulary contract. The PLATFORM environment axis (sandbox / SIT / PROD) answers
   "does this break infrastructure / is the money real"; the PRODUCT phase axis (research,
   backtest_canonical, paper, live_small, live_full) answers "does this strategy deserve capital".
   Reserved vocabulary, enforced by `scripts/validate.py:validate_environment_taxonomy`:
   "environment" = platform axis only; product states are "phases"; "promotion" must be
   axis-qualified.

2. **Affirm the platform promotion train** (cite Decisions 24, 73). Section 6 of
   `INTENT-ci-cd-architecture.md` is the canonical platform-axis design. SIT and PROD remain
   future-state.

3. **Scope Decision 35.** Permit sandbox auto-apply on push to main behind the deterministic guard
   (`scripts/terraform_apply_guard.py`, fail-closed on any destroy / IAM / trust-policy change) plus
   a subagent plan review (`.github/workflows/terraform-apply-sandbox.yml`). SIT and PROD stay
   human-gated. This scopes -- does not overturn -- Decision 35: apply stays human-gated everywhere
   except the mocked sandbox, where the guard + review are the compensating gate (Decision 89 /
   CD.20: branch protection and required status checks are unavailable).

4. **Product promotion stays config-only.** CDP.6 / CDP.7 remain valid for the product axis:
   single-account, promotion-as-config-change. The ROADMAP-PRODUCT retirement is scoped to the
   product axis ONLY and does not touch the platform train.

5. **Single-account-until-live_full (load-bearing).** The platform stays SINGLE-ACCOUNT (the current
   personal account, sandbox environment only) until the product axis reaches live_full approaching
   real capital -- that product event is the named trigger to stand up a dedicated SIT then PROD
   account. Affirming the train as future-state does NOT re-introduce the multi-account posture
   CDP.7 retired.

6. **Re-base Decision 24 vocabulary.** "staging" is renamed "SIT" on the platform axis. Decision
   24's `envs/sandbox.tfvars` multi-tfvars model is superseded by the `terraform/personal/`
   partial-backend reality (`backend-sandbox.hcl`; a future SIT/PROD is a new backend-<env>.hcl).

**Rationale:**
- The conflation was structural: the same words ("sandbox", "staging", "promotion") meant different
  things on each axis, so one axis's retirement looked like it retired the other. A vocabulary
  contract with lint enforcement prevents re-conflation.
- The sandbox is mock-vs-real at one code version, not a version-skew tier; auto-applying it carries
  no real-capital risk, and the fail-closed guard forces every destroy / IAM / trust change onto the
  manual admin-apply path regardless.
- Single-account-until-live_full keeps the affirmation cheap: no new accounts are stood up until a
  concrete product event justifies them.

**Constraints:**
- The guard AND the workflow MUST fail closed: apply runs only on guard `success()`; the guard step
  carries no `continue-on-error`; any non-zero guard exit blocks apply; apply consumes the SAME plan
  file the guard inspected (no re-plan -- no TOCTOU).
- The bootstrap (S3 backend migration + apply role creation) is a one-time MANUAL admin apply under
  `agent_platform_admin`; the workflow takes over only afterwards.

**Related:** Decision 24 (Multi-Environment Deployment Strategy), Decision 35 (Terraform Workflow
Integration), Decision 73 (Two-Tier CI + promotion train), Decision 67 (STRATEGIC deferral; its
Lambda-deploy clause was lifted by Decision 79), Decision 72 (RCA-as-Plan-Source), Decision 89 (branch protection unavailable), CD.21 (GitHub-hosted
OIDC CI), `docs/contracts/environment-taxonomy.md`, `docs/INTENT-ci-cd-architecture.md` section 6.

> **Update (2026-08-13):** `docs/contracts/environment-taxonomy.md` was converted to the declared
> Class D contract `docs/contracts/environment-taxonomy.yaml` (CFG-11 conversion, per Decision
> 168's Class D mechanism). The two-axis vocabulary reservation and apply-model / guard
> classification content named by this Decision is unchanged -- only the file format and path
> changed; cite `docs/contracts/environment-taxonomy.yaml` going forward.

---

## Decision 76: Claude-Code-on-the-Web Workflow Migration; .claude as Canonical Interactive Layer (Decided)

**Status:** Decided
**Date:** 2026-05-30

**Context:** `/plan` and `/implement` were authored for local dev (Windows + Git Bash): `agent/{slug}` branches, slug derived from branch name, merge via `gh` CLI with a `sleep`/`/loop` poll for CI. On Claude Code on the web the harness auto-creates a per-session branch (`claude/...`), `gh` is unavailable, and the container hibernates between turns -- a turn that ends while polling never resumes, stranding branches.

**Decision:**
1. Model: planning agent pinned to `opus[1m]` (Opus, 1M context); implement agent stays `sonnet`.
2. Branches: the `agent/{slug}` ceremony is removed. Agents work on the harness session branch; the plan slug is derived from the task, independent of the branch name.
3. Handoff: the planning agent merges `PLAN-{slug}.md` to `main` (PR -> fast PR-tier CI -> squash-merge via GitHub MCP) and emits a copy-paste handoff (`/implement docs/plans/PLAN-{slug}.md`); a fresh `/implement` session reads the plan from main by explicit path.
4. PR/merge: all GitHub ops use the GitHub MCP tools; waiting for CI is event-driven via `subscribe_pr_activity` (end the turn; the webhook wakes the session), never `sleep`/`/loop`.
5. Canonical layer: `.claude/commands/` + `.claude/skills/` are now the canonical interactive-workflow layer.

**Amends / Supersedes:**
- Amends Decision 89 ("GitHub Branch Protection Not Available"), clause 4 (`gh pr merge --squash` after CI): squash-merge policy preserved; transport changes to GitHub MCP `merge_pull_request(merge_method="squash")` because `gh` is unavailable on the web harness.
- Amends Decision 23 ("slug derived from branch name"): slug is decoupled from the branch; the anti-contamination intent (one tracked plan per unit of work, branched from main) is satisfied by the harness per-session auto-branch model.
- Supersedes Decision 58 ("`.agents` as canonical interactive workflow layer"): `.claude/` is now canonical; `.agents/` is demoted to legacy alongside `.github/` (no sync obligation).

**Unaffected:** Decision 25 (git worktrees) is a local-dev affordance, unchanged. Decisions 60/73 (two-tier CI, forward-fix) govern the tiers this flow waits on. Decision 67 keeps plans IMPLEMENTATION-type. Decision 44 keeps executor machinery out of scope.

**Deferred follow-up:** GitHub-native auto-merge (container fully out of the merge loop) is the robustness ceiling for the lost-webhook case; unblocked by Decision 83 (branch protection active, CD.20 applied 2026-06-08). Implementation is a follow-on task (configure GitHub-native auto-merge on the PR).

**Related:** Decision 89 (Branch Protection), 73, 60, 67, 44, 23, 25, 58, 55; CD.20, CD.21.

## Decision 75: Frame-Lock Anti-Pattern in Architectural Planning (Decided)

**Status:** Decided
**Date:** 2026-05-27
**Warehouse ID:** dec-075 (canonical; retired writer-era id reconciled per Decision 105; corrects a prior display-layer double-claim of dec-081, which is Decision 81's canonical id)

**Problem:**
Architectural planning for the autonomous executor (CD.11, T4.1, `INTENT-provider-agnostic-executor.md` Stage 4) proposed Fargate, then Modal, then Fargate Spot via AWS Batch as candidate compute substrates -- all three options shared the unexamined assumption that the executor would be a monolithic Python process running an in-process agent loop. The Step Functions + per-step Lambda alternative -- which collapses 6 of T4.1's named subsystems into ~30 lines of Python, eliminates the substrate question entirely, aligns with NS.5 ("typed tools over HTTPS") and CD.10 ("Lambda per tool"), and uses primitives already in production (Decision 39 ratified Step Functions over Airflow; `terraform/data_pipeline.tf` ships a 5-Lambda Step Functions pipeline) -- was never raised during planning. It surfaced only when an outsider perspective, loaded without months of frame-locking context, asked "what if the executor isn't a long-running Python process?"

The miss was structural, not tactical. Three compounding biases produced it:

1. **Frame lock at the originating artefact.** `docs/INTENT-recommendation-executor.md:70` framed the executor as "Orchestrator entry point. Thin exception-catching wrapper around `_execute_recommendation_inner()` which contains all orchestration logic." Once the orchestration role was assigned to Python code, the substrate question became "what runs Python long enough?" not "what orchestrates workflows?" Step Functions never entered the executor conversation because the executor's frame was already locked to "Python orchestrator."

2. **Conceptual state machine versus managed state machine.** The executor INTENT Section 5.4 calls itself "State Machine (Work in Progress)" but the state machine being designed is a Python-internal lifecycle encoded in `_execute_recommendation_inner()` branches. The team simultaneously used Step Functions for the market data pipeline (Decision 39) but never applied the same pattern to the executor itself -- the term "state machine" carried two meanings and the conflation prevented the obvious application.

3. **Tool acquired after design committed; tool never retrofitted.** Decision 39 ratified Step Functions over Airflow at a time when the executor architecture was already in flight (`scripts/execute_recommendation.py` predates it). New capability landed in the toolkit, but no audit was triggered to ask "where else in the system could this newly-acquired capability apply?" The acquired tool stayed scoped to its original ETL use case.

**Decision:**

Recognise frame-lock as a named architectural-planning failure mode. Embed two mitigations that catch future instances:

1. **Frame-challenge phase in the plan-critique skill.** Add a mandatory phase to `.claude/skills/plan-critique/SKILL.md` and its `.agents/skills/plan-critique/SKILL.md` mirror (per Decision 58). The phase asks five questions designed to challenge the frame of a plan rather than its details:
   - What if the orchestrator wasn't this kind of thing? (Question the chosen primitive itself.)
   - What if this monolith were decomposed at a different boundary? (Question the unit of work.)
   - What existing platform primitives could absorb this custom code? (Question whether custom orchestration / retry / scheduling / state-machine / queue logic should be replaced by AWS-native primitives already in this codebase.)
   - What assumption from an earlier decision are we still carrying that the world has moved past? (Question whether constraints cited in the plan reference a Decision whose premise no longer holds.)
   - What tools or capabilities have been added since this approach was first conceived? (Question whether capabilities ratified by Decisions or added by infrastructure have retroactively changed the right shape of the work.)

   Plan-critique surfaces the answers in a new "Frame Challenge" field in its structured output. The critique recommends REVISE only when a frame challenge identifies a concrete contradiction with a Decision, a Roadmap item, or a North Star principle; otherwise the challenges are surfaced informationally for the human to consider.

2. **This decision IS the second mitigation.** Naming the failure mode and documenting it in DECISIONS.md lets future plan-critique runs flag candidate frame-lock instances by reference rather than re-deriving the diagnosis each session. Decisions 55 (RCA-First Executor) and 72 (RCA-as-Plan-Source) follow the same pattern: naming a failure mode lets agents detect and reference it by ID.

**Rationale:**

- The frame-lock pattern is detectable structurally if you know to look for it. The plan-critique skill currently challenges plan details against the existing frame; it does not challenge the frame itself. That gap is the institutional control that needs to exist.
- Two independent mitigations catch each other's misses. The skill update catches frame issues at plan time; the named Decision lets the skill and humans reference the pattern by ID rather than re-derive it.
- Cost is small: one skill section (mirrored), one Decision entry. No infrastructure change, no schema change, no runtime impact, no follow-on plans required.
- The cure for tool-acquired-after-design-committed is the same: a frame-challenge question explicitly asks "what tools have been added since this approach was conceived?" which catches the Decision 39 -> executor gap that produced this very Decision.

**Constraints:**
- The frame-challenge phase surfaces questions for human or critique-agent judgment; it does NOT enforce a particular answer. Detection by name is not automatic rejection. A plan can validly choose to carry forward an existing frame; the requirement is that the choice is conscious.
- Soft-warn semantics: plan-critique recommends REVISE only on concrete contradictions, not on every surfaced challenge. The cost of false-positive REVISE is friction in every planning session; the cost of false-negative is another frame-lock event. Bias toward surface-and-let-human-decide.

**Acknowledges:**
- Decision 39 (Step Functions over Airflow): the canonical case where ratified capability was not retrofitted into existing-design architecture.
- Decision 55 (RCA-First Executor): framing precedent for naming a failure mode as a Decision.
- Decision 58 (.agents as canonical interactive workflow layer): the skill update lands in both `.claude/skills/plan-critique/SKILL.md` and `.agents/skills/plan-critique/SKILL.md` per the cross-harness mirror rule.
- Decision 72 (RCA-as-Plan-Source for CI): framing precedent for systematic anti-pattern detection via named pattern reference.
- `docs/INTENT-recommendation-executor.md`: the source artefact whose framing locked the downstream chain (CD.11 Fargate, T4.1 XL Fargate decomposition, INTENT-provider-agnostic-executor Stage 4 substrate selection).
- `docs/INTENT-provider-agnostic-executor.md`: Stage 4 selection criteria considered six container runtimes (Lambda Container, Fargate, Batch, Modal, Cloud Run Jobs, EKS) without considering Step Functions as the orchestration layer above whichever runtime was chosen. Illustrative of the frame.

**Related:** Decision 39, Decision 55, Decision 58, Decision 72, `docs/INTENT-recommendation-executor.md`, `docs/INTENT-provider-agnostic-executor.md`, `docs/ROADMAP-PLATFORM.yaml` (CD.11, T4.1, T4.2)

> **Update (2026-08-02):** ESB-11 (audit ad02653) -- the `terraform/data_pipeline.tf` precedent this entry cites under "primitives already in production" sits at the retained-not-applied legacy Terraform root (see `terraform/CLAUDE.md`), not a deployed pipeline. The five-Lambda Step Functions shape it demonstrates is a design-and-skill precedent, not a runtime-evidence precedent. This annotation does not amend the frame-lock finding or its mitigations.

---

## Decision 74: Pre-Install Claude Code CLI in Runner user_data + workflow_dispatch Escape Hatch (Decided)

**Status:** Decided
**Date:** 2026-05-22

**Problem:**
ci-rca runs `26284914206` and `26287172232` both failed at `Install Claude Code CLI` with `npm error code EACCES ... mkdir '/usr/lib/node_modules/@anthropic-ai'`. The runner's `npm install -g` runs as the `ubuntu` user, which lacks write access to the global node_modules directory. Although Ubuntu cloud AMIs grant passwordless sudo, the existing step did not use `sudo`. The result: every CI failure since 2026-05-22 produced no ci-rca rec -- the Decision 73 forward-fix model received zero failure signals while `ci_rca_liveness_alert` fired continuously (69.6 minutes elapsed at planning time, referencing run `26286390667`). Additionally, there was no mechanism to re-run ci-rca against a past failure without pushing a fake CI commit to trigger `workflow_run`.

**Decision:**
Two changes to restore and harden the harness:

1. **Sudo + pinned install in the workflow**: Replace `npm install -g @anthropic-ai/claude-code` with `sudo npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional && sudo npm cache clean --force`. Version pin `@2.1.148` locks the install to the version confirmed working as of 2026-05-22 (`npm view @anthropic-ai/claude-code dist.unpackedSize` returned 136KB unpacked). The `--omit` flags reduce install footprint on the 20GB volume (82% used, 3.6GB free).

2. **workflow_dispatch escape hatch**: Add `workflow_dispatch: inputs: run_id` trigger to `.github/workflows/ci-rca.yml` so the agent can be manually re-dispatched against any past CI run ID without pushing a fake commit. Enables `gh workflow run ci-rca.yml --ref <branch> -f run_id=26286390667` to retroactively diagnose the SLOC limit violation on `scripts/product_roadmap.py` (631 SLOC) from the triggering CI failure.

**Deferred:** Pre-baking the CLI in `terraform/ec2_runner.tf` user_data was planned but deferred. During implementation, `terraform plan` revealed that `data.aws_ami.ubuntu_22_04 { most_recent = true }` had resolved to a newer AMI (`ami-0adb4b73a38358d7c` -> `ami-02b81edd0fb821197`), causing the instance to be flagged for destroy-and-replace regardless of the user_data change. Recreating the production runner is out of scope. A follow-on plan should pin the AMI ID (removing `most_recent = true`) before attempting the user_data pre-bake apply.

**Rationale:**
- EACCES is structural: non-root npm global install on Ubuntu requires sudo. `sudo` is the minimal correct fix.
- Pinning prevents silent upgrades from breaking the harness; version bumps are explicit future plan changes.
- The `workflow_dispatch` trigger adds an operator escape hatch missing from Decision 72's original implementation without changing `workflow_run` semantics.
- The existing runner self-heals via the workflow YAML change -- no runner recreation is needed for the immediate fix.

**Constraints:**
- Existing runner is NOT restarted or recreated. The `sudo` fix self-heals on the next ci-rca dispatch after this branch merges.
- `CLAUDE_CODE_OAUTH_TOKEN` rotation (90-day expiry) deferred -- 90-day migration window to GitHub-hosted runners makes rotation unlikely to bite before migration lands.
- Version `@2.1.148` is current as of 2026-05-22. Future plans may bump.

**Acknowledges:**
- Decision 72 (RCA-as-Plan-Source): this decision hardens the harness Decision 72 introduced.
- Decision 73 (Forward-Fix CI model): this decision restores the failure-signal path Decision 73 depends on.
- Decision 68 (Self-Hosted Runner): terraform apply deferred due to pre-existing AMI drift triggering instance replacement; see Deferred note above.

**Related:** Decision 68, Decision 72, Decision 73, failed ci-rca run `26287172232`, triggering CI run `26286390667`

> **Update (2026-07-21):** The self-hosted EC2 runner substrate this decision hardens was retired 2026-05-28 per CD.21, ratified by Decision 112. CI now runs on GitHub-hosted OIDC runners. The `workflow_dispatch` escape hatch (item 2) survives unchanged in `.github/workflows/ci-rca.yml`.

---

## Decision 73: Two-Tier Diff-Aware CI with Forward-Fix and Scheduled Promotion Train (Decided)

**Status:** Decided
**Date:** 2026-05-13

**Problem:**
Decision 60 (2026-05-05) specified a two-tier validation model with a 5-minute fast-tier budget. The budget was unattainable at ratification: V3 verifiers (PR #274, 2026-05-01) and the DQ runner integration (PR #289, same day as Decision 60) placed ~10 minutes of Athena round-trips in the default presubmit tier on day zero. Twelve subsequent commits to `validate.py` between 2026-05-06 and 2026-05-12 compounded the drift. Measured runtimes show median 18 min, max 50 min -- a 3-10x violation of the documented budget. The structural causes are: (1) the budget had no enforcement mechanism, (2) the tier was defined by exclusion of a barely-used pytest marker (`@pytest.mark.integration` is set on exactly 1 of ~30 AWS-touching test files), and (3) post-merge CI ran on push-to-main duplicating PR CI on the same content. Additionally, with GitHub branch protection permanently unavailable (Decision 89), Decision 89 made remote CI the only merge gate -- yet the gate runs the same slow tier that should be reserved for comprehensive validation. The merge model conflates pre-merge gating with comprehensive validation, and the planning queue currently treats 178 accumulated non-automatable recommendations as mandatory discussion items, which is operational noise while the executor is offline pending Decision 67 reversal.

**Decision:**
Adopt a ten-layer CI/CD architecture (L1-L10) as specified in `docs/INTENT-ci-cd-architecture.md`. The model preserves Decision 60's two-tier abstraction while redefining tier semantics and adding forward-fix merge gating and scheduled promotion design.

Key elements:

1. **Two tiers with new semantics.** Fast tier (`--pre`) becomes diff-aware (ruff/mypy on changed files only, `pytest --picked` for test selection, hard 5-min budget assertion). Full tier (default) runs everything end-to-end with an honest 15-30 min budget. The fast tier asserts wall-clock budget and fails non-zero on breach.

2. **PR gating uses fast tier.** PR CI runs `--pre`. Full tier runs on push to `main` and on hourly scheduled cron (L8 drift canary). The post-merge full tier replaces the previously-duplicate PR-then-main runs.

3. **Forward-fix merge gate, not auto-revert.** Auto-revert is excluded because it moves `main` underneath active worktrees -- structurally hostile to multi-worktree parallel development and to the future autonomous executor (Wave 4). On full-tier failure on `main`, `ci-rca` files a `priority="critical"`, `source="ci_rca"` rec; the rec hard-blocks the planning queue (L5) and pauses PR auto-merge (L6) until a forward-fix lands.

4. **Planning queue governance.** While an open ci-rca rec exists, `/plan` cannot scope unrelated work; `session_preflight.py` surfaces the block at the top of its report. Separately, the existing rule that treats `non_automatable_recommendations > 0` as MANDATORY discussion is suspended until Decision 67 reverses and the executor is back in service. Counts remain informational in the preflight report.

5. **Sandbox tolerates red `main`; SIT and PROD do not.** Sandbox is the only environment agents touch. Forward-fix recovers sandbox via the standard rec → plan → implement cycle, typically within hours. SIT and PROD inherit only sandbox commits that have been green continuously ≥24h (sandbox→SIT) or ≥7d (SIT→PROD); the green-streak resets on any ci-rca rec opening. SIT and PROD environments are months-away future work, deferred to Phase Infra-Env.

6. **Merge-mode is derived from the diff, not stored.** A path-prefix table (specified in INTENT Section 7) computes sync vs async gating from `git diff --name-only`. The `automatable` field on `ops_recommendations` retains Decision 44 semantics (executor self-modification boundary) and is not extended into merge-mode territory. Conflation was considered and rejected: actual file overlap between the two lists is near-zero, and unifying would either expand the executor boundary into non-self-modification files or over-gate executor-machinery PRs that are well-tested.

**Rationale:**

- *Agent-first throughput.* Sync pre-merge gating on a 30-minute full tier stalls the recursive self-improvement loop. Async with forward-fix unblocks agents after a 5-minute fast tier while preserving recovery via the existing rec/plan/implement infrastructure.
- *Worktree-safe.* Forward-fix touches `main` only via append; auto-revert moves `main` underneath worktrees, which is hostile to the parallel-execution pattern this repo already uses and will use more heavily in Wave 4.
- *Industry-aligned.* Optimistic merge with post-merge comprehensive validation and queued remediation is the canonical pattern at Google (TAP), Meta (Sapling/TAP), and AWS internal pipelines. The agent-first variant replaces "human notification" with "rec in priority queue"; the shape is identical.
- *Enforced budgets.* Decision 60's 5-minute fast-tier target becomes a runtime assertion. The decision becomes real when violation produces a visible failure, not when documentation says it should hold.
- *Time + green-streak promotion.* Bake time is the strongest test available against real-world conditions you cannot anticipate. Time alone is not enough -- a recently-broken commit promoted exactly 24h after merge would inherit a known-broken state. The green-streak window ensures only stable commits cross promotion gates.

**Supersedes / Amends:**
- Implementation mechanism of Decision 60 (tier definitions and enforcement). The two-tier abstraction and 5-minute fast-tier target survive; the exclusion-by-marker mechanism is replaced by diff-aware selection with an enforced budget assertion.
- Implicit "remote CI on every PR push and every main push" pattern in `.github/workflows/ci.yml`. The push-to-main trigger now runs the full tier (not duplicating the PR run); the PR trigger runs the fast tier.

**Acknowledges:**
- Decision 44 (Executor Self-Modification Boundary): preserved unchanged.
- Decision 55 (RCA-First Executor): the forward-fix model is RCA-first applied to the CI merge gate.
- Decision 67 (Lambda + STRATEGIC plans deferred): the non-automatable rec surfacing change reverts when Decision 67 reverses.
- Decision 68 (Self-Hosted Runner): compounds. Free CI minutes are what make the hourly L8 drift canary affordable.
- Decision 71 (cc-scheduled-agents): compounds. The scheduled-cron infrastructure pattern is reused for L8.
- Decision 72 (RCA-as-Plan-Source for CI): extended. ci-rca recs gain hard-block (L5) and merge-pause (L6) semantics.
- Decision 89 (Branch Protection Unavailable): the forward-fix model is designed around branch protection being permanently unavailable. *(Premise reversed by Decision 83, 2026-06-08; design consequences preserved.)*

**Consequences:**
- Three follow-on IMPLEMENTATION plans are required to land the architecture: `validate-fast-tier-reshape`, `ci-workflow-restructure`, `planning-queue-governance`. Each is independently scoped and lands in its own PR.
- L9-L10 (sandbox/SIT/PROD promotion train) are designed in `docs/INTENT-ci-cd-architecture.md` but deferred to Phase Infra-Env activation. SIT and PROD environments do not exist today; building them is months-away work.
- The 178 non-automatable recommendations currently accumulating will not be surfaced for mandatory discussion until Decision 67 reverses and the executor returns to service. They remain queryable from `ops_recommendations`; only the planning-skill behaviour changes.
- Auto-merge pause (L6) and planning hard-block (L5) require enforcement code in `scripts/session_preflight.py`, the planning skill, and the workflow YAML. These changes land in the `planning-queue-governance` and `ci-workflow-restructure` plans respectively.
- Decision 60 remains in DECISIONS.md as the originating ratification; this decision amends rather than retires it. The 5-minute fast-tier budget and the two-tier abstraction are preserved; only the implementation mechanism is replaced.

**Known Gaps (mirrored from INTENT Section 9):**
- L9-L10 promotion train: months away minimum; depends on Phase Infra-Env, SIT/PROD accounts, and trading-go-live readiness.
- Executor priority-queue rule for ci-rca recs: depends on Wave 4 + Decision 67 reversal.
- `pytest --picked` may be upgraded to `pytest-testmon` later if false-negatives accumulate.

**Related:** Decision 44, Decision 55, Decision 60, Decision 67, Decision 68, Decision 71, Decision 72 (RCA-as-Plan-Source), Decision 89 (branch protection), `docs/INTENT-ci-cd-architecture.md`, `docs/ROADMAP-PRODUCT.md` (Phase Infra-Env).

---

## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures (Decided)

**Status:** Decided
**Date:** 2026-05-11

**Problem:**
CI failures on feature branches require manual diagnosis today. There is no automated surfacing of root cause, and developers may write workarounds rather than fix the underlying issue -- the anti-pattern Decision 55 was designed to prevent. The cc-scheduled-agents pattern (Decision 71) already provides the infrastructure to extend RCA-first diagnosis to the CI merge gate, but it has not been applied there.

**Decision:**
On CI failure (`workflow_run.conclusion == 'failure'`), a `workflow_run`-triggered GitHub Actions workflow (`.github/workflows/ci-rca.yml`) invokes `claude -p` headlessly on the self-hosted runner. The ci-rca agent reads the failed run logs via `gh run view <run-id> --log-failed`, identifies the root cause with evidence, and files a recommendation with `source="ci_rca"` and `priority="critical"` via `python -m scripts.ops_data_portal file_rec`. The agent does NOT propose or execute any autonomous fix. The rec is consumed via the standard `/plan` -> `/implement` flow. A new "CI RCA Recs (open)" section in `session_preflight.py` surfaces open `ci_rca` recs in every subsequent planning session.

**Rationale:**
Reuses the cc-scheduled-agents infrastructure (Decision 71) with a `workflow_run` trigger instead of cron. Reuses `ops_recommendations` as the single rec queue (Decision 50, superseded by Decision 78). Reuses the `source` field as a discriminator (Decision 61). Honours the no-autonomous-fix invariant (Decision 55). Preserves human-in-the-loop architectural judgment -- the ci-rca agent diagnoses and signals, the developer decides and acts via `/plan`.

**Consequences:**
`workflow_run` workflows execute in the context of the default branch but check out at the `head_sha` of the triggering run. A PR that modifies `.claude/agents/scheduled/ci-rca.md` and itself fails CI will invoke ci-rca with that PR's potentially-modified agent file. This is intentional (the PR author gets feedback on their own changes), but a malformed agent definition in a PR can cause that PR's ci-rca run to fail.

**Related:** Decision 50 (Iceberg ops store, superseded by Decision 78), Decision 51 (local-first outbox, superseded by Decision 78), Decision 55 (RCA-first executor), Decision 60 (two-tier validation), Decision 61 (source discriminator), Decision 68 (self-hosted runner), Decision 71 (cc-scheduled-agents pattern)

---

## Decision 70: Physical Deletion of Bootstrap Records from ops_recommendations (Decided)

**Status:** Decided
**Date:** 2026-05-09

**Problem:**
Five hollow bootstrap records (rec-608, rec-633, rec-001, rec-002, and one null-id record)
existed in the `ops_recommendations` Iceberg base table. These records were written via the
now-closed `append_jsonl -> s3_log_store` path before PR #304 closed the direct write bypass.
They had empty or null `status`, `title`, `source`, `effort`, and `priority` fields. Because
`update_rec` validates the `status` field against a Pydantic `Literal` type, passing a null or
empty `status` raises `ValidationError` before any write is attempted -- making `update_rec`
(the normal lifecycle closure path) non-viable for these records. The records fired
`HARD_GATE` on every DQ run since they appeared in `ops_recommendations_current`.

**Decision:**
Physically deleted all five records from Iceberg on 2026-05-09 via the three-step protocol:
`DELETE FROM trading_formulas_db.ops_recommendations WHERE <predicate>`, followed by
`OPTIMIZE ... REWRITE DATA USING BIN_PACK`, followed by `VACUUM`. Tombstone entries for
rec-608 and rec-633 removed from `dq_tombstones.yaml` (physical deletion supersedes the
tombstone check).

**Decision NOT to add a general-purpose `delete_rec` function to `ops_data_portal`:**
The portal's role is lifecycle management, not destruction. Physical deletion must remain
exceptional and deliberate -- the DQ enforcement ratchet and the `append_jsonl` bypass
closure are the prevention mechanisms. `_delete_postmortems_from_iceberg` remains private
for its narrow use case. Adding a public `delete_rec` would create a routine destructive
path where none is warranted.

**Rationale:**
Records with null/empty `status` cannot be closed via `update_rec` without either patching
the record's `status` first (which requires a write -- the same problem) or loosening the
Pydantic model (which degrades validation for all callers). Physical DELETE is the only
viable path for invalid bootstrap records that bypassed validation at insertion time.

**Related:** Decision 69 (ops pipeline consolidation, superseded by Decision 78), Decision 51 (local-first outbox, superseded by Decision 78)

---

## Decision 55: RCA-First Autonomous Executor Architecture (Supersedes Decision 46) (Decided)

**Status:** Decided
**Date:** 2026-04-28

**Problem:**
The rescue agent architecture (Decision 46) introduces a correction layer that hides executor infrastructure gaps. When the executor hits an unrecoverable failure, rescue agents attempt autonomous repair — but LLM-powered "judgement" recovery compounds failures by automating workarounds rather than fixing the root cause permanently. The rec-449 transcript demonstrates this concretely: a V3 misclassification in `planning.prompt.md` caused an unresolvable critique cycling deadlock; the supervisor's instinct was `--skip-critique` (workaround) rather than diagnosing and fixing the underlying prompt rule. Recovery agents would have automated the same workaround, locking in the gap indefinitely.

**Decision:**
Replace the rescue agent layer (Decision 46) with an RCA-first model. When the executor hits an unrecoverable failure, the correct response is:

1. **Stop cleanly** — emit a structured `process_event` record with `tier=exception` and the failure context.
2. **Invoke an RCA agent** — the agent diagnoses root cause and files a recommendation to fix the gap permanently.
3. **Do not attempt repair** — no rescue agents, no workaround automation.

**Deterministic recovery remains valid.** Pattern-matched recovery for well-understood failure classes (git retry, ruff auto-fix, CLI timeout retry) continues unchanged. The removal applies only to LLM-powered "judgement" recovery decisions.

**Key points:**
- Each failure class is diagnosed once and fixed by a rec, so improvements compound permanently.
- The executor is cheaper and simpler to reason about without a rescue dispatch layer.
- The three-outcome contract (RESOLVED/CANNOT_RESOLVE/TIMEOUT), graduated autonomy gates, and recursive rescue prevention (Decision 46) are replaced by a simpler model: stop cleanly, diagnose, file rec.
- `scripts/executor/rescue.py` (planned but not yet written) is cancelled.
- The SRE blameless postmortem pattern applied to autonomous systems: failures are learning signals, not emergencies to paper over.

**Rationale:**
- One correct fix costs one diagnosis call. N recovery attempts cost N×K LLM calls and may still fail.
- Supervisor hiding (workaround routing) decreases long-term reliability by preventing gap accumulation from becoming visible.
- Structured process events + RCA agent creates a queryable audit trail in Athena that rescue agents do not provide.
- Decision 46 was premature: the executor was not yet reliable enough to trust rescue agents, and the trust calibration mechanism (graduated autonomy gates) was complex and untested.

**Supersedes:** Decision 46 (Rescue Agent Architecture). The three-outcome contract and graduated autonomy gates are retired.

**Related:** Decision 34 (state machine exit paths), Decision 46 (superseded), Decision 51 (outbox pattern for structured process events, superseded by Decision 78)

---

## Decision 57: Autonomous Improvement Control Plane as Umbrella Architecture (Decided)

**Status:** Decided
**Date:** 2026-05-01

**Problem:**
The repository has several strong self-improvement components: telemetry schemas, process events, recommendations, executor automation, scheduled agents, verification intent, and interactive workflows. Without an umbrella architecture, these components can evolve independently and leave the recursive self-improvement loop open at the most important transitions: telemetry analysis, RCA writeback, recommendation prioritisation, and proof that a fix reduced the failure mode that caused it.

**Decision:**
Create `docs/INTENT-autonomous-improvement-control-plane.md` as the umbrella intent document for the recursive self-improvement loop. Existing subsystem intent documents remain authoritative for their domains:
- `docs/INTENT-telemetry-system.md` for telemetry schema and process events
- `docs/INTENT-verification-system.md` for programmatic verification and causal-chain checks
- `docs/INTENT-recommendation-executor.md` for executor lifecycle and boundaries
- `docs/contracts/instruction-architecture.md` for instruction layering

The control-plane intent defines the target loop: execution -> telemetry -> verifier results -> process events -> failure packets or anomaly clusters -> RCA -> portal-filed recommendations -> priority queue -> executor or interactive implementation -> verification -> telemetry delta.

**Rationale:**
The architecture review concluded that the design is unusually mature for a sole-developer system, but not fully closed operationally. The missing capability is not another isolated prompt or script; it is an explicit control-plane model that sequences telemetry trust, verification, executor RCA, workflow migration, state-machine events, and recommendation governance.

**Related:** Decision 48 (verification tier), Decision 51 (local-first outbox, superseded by Decision 78), Decision 55 (RCA-first executor), `docs/INTENT-autonomous-improvement-control-plane.md`

---

## Decision 58: `.agents` as Canonical Interactive Workflow Layer (Decided)

**Status:** Superseded
**Date:** 2026-05-01

**Decision:** Superseded by Decision 76, which names `.claude/commands/` + `.claude/skills/` as the canonical interactive-workflow layer that retired the `.agents/workflows/` + `.agents/skills/` layer this entry defined; kept live here rather than archived because `docs/ROADMAP-PLATFORM.yaml` (T5.3) and `docs/contracts/instruction-architecture.yaml` still cite "Decision 58" by name (the Decision 146 still-cited-live carve-out; compacted under the DCG-02/DCG-03 lifecycle per `docs/contracts/decision-entry.yaml`'s `compaction:` section).

**Superseded by: Decision 76**

---

## Decision 59: Retrospective and Step Validation Move to Telemetry and State Machine (Decided)

**Status:** Decided
**Date:** 2026-05-01

**Problem:**
Legacy VS Code workflows used subagents such as step-validator, scope-guard, retro-lite, and retrospective to compensate for missing structured execution state and process telemetry. Migrating these subagents as-is would preserve chat-based supervision rather than advancing the target architecture.

**Decision:**
Do not migrate retrospective, retro-lite, step-validator, or scope-guard as LLM subagents by default. Their responsibilities move to deterministic mechanisms:
- Step validation becomes execution state plus acceptance and verifier results.
- Scope guard becomes a deterministic diff-vs-plan check.
- Retro-lite becomes structured `telemetry_process_events`.
- Retrospective becomes scheduled telemetry analysis, decision governance, and recommendation generation.

The concerns are still required; only the legacy LLM-agent implementation is retired. Temporary compatibility shims are allowed during migration, but new investment should target deterministic checks, process events, verifier results, and state-machine transitions.

**Rationale:**
LLM subagents are useful for judgement and RCA, but step completion, scope drift, verifier status, retry count, and session summaries are state-machine facts. Encoding those facts in telemetry makes the system queryable, auditable, and eligible for autonomous trend analysis. Recreating the old subagent model would add cost and preserve the failure mode where agents reconstruct what happened from chat rather than reading structured evidence.

**Related:** Decision 55 (RCA-first executor), `docs/INTENT-telemetry-system.md`, `docs/INTENT-verification-system.md`, `docs/INTENT-autonomous-improvement-control-plane.md`

---

## Decision 60: Two-tier validation architecture: presubmit (default) + edit-loop (`--pre`) (Decided)

**Status:** Decided
**Date:** 2026-05-05
**Amended:** 2026-05-09 (PLAN-validate-two-tier): edit-loop flag renamed `--quick` -> `--pre` by explicit user instruction during planning session. No semantic change to tier behaviour; the rename improves clarity by aligning the flag name with its position in the workflow (pre-commit edit-loop).

**Problem:**
`scripts/validate.py` has accumulated five execution surfaces (`--scope auto|all|python|terraform|docs|prompts`, `--integration`, `--ci`, `--quick`, `--verifiers`) plus advisory flags. Autonomous executors and human/agent implementations frequently call the wrong flag (e.g., `--quick` when integration was needed). Wall-clock budgets are implicit. The local `--ci` and the GitHub Actions workflow drift silently when checks are added to one path and not the other -- exactly the failure mode `validate.py` was created to prevent. The four-flag world is structurally hostile to bounded-execution autonomous agents.

**Decision:**
Migrate the surface to two named tiers:

- **Presubmit (default, no flag):** Runs the full python check suite, terraform checks, dependency health, prompt validation, V3 verifiers (when AWS available), and DQ runner auto-invoke when stale. Time budget: <= 5 minutes total. Called once per branch before merge by the developer or by the self-hosted CI runner.
- **Edit-loop (`--pre`):** Lint, format, prompt validation, copilot multipliers validation. Nothing that touches AWS, nothing that runs pytest. Time budget: <= 30 seconds. Called per-step during implementation.

`--scope`, `--ci`, `--integration`, and `--verifiers` are deleted in the consolidation step. `--coverage` is retained as an advisory and remains exit-0 unconditional.

**Substrate:** A self-hosted GitHub Actions runner on EC2 with the same SSO configuration as the developer machine. Branch protection on `main` requires the workflow to pass; the workflow calls `python -m scripts.validate` with no flags. Zero billed minutes for the default tier. Reversible in 30 seconds. *(2026-06 migration note: runner retired per CD.21; CI now on GitHub-hosted OIDC runners. Branch protection is now active per Decision 83 / T2.12.)*

**Migration sequence (each step reversible):**
1. [DONE] Land the architectural anchor (`docs/INTENT-validation-architecture.md`) and this Decision Record.
2. [DONE] Wire DQ runner auto-invoke into `--integration` (closes Gap 2 of the audit; this plan).
3. [DONE] Stand up the self-hosted EC2 runner with SSO substrate (PR #310, Decision 68).
4. [DONE] Freeze `--pre` surface with parity tests. (`--quick` renamed to `--pre`; PLAN-validate-two-tier, 2026-05-09.)
5. [DONE] Consolidate flags: deleted `--scope`, `--ci`, `--integration`, `--verifiers`. CI workflow calls `python -m scripts.validate` with no flags. (PLAN-validate-two-tier, 2026-05-09.)
6. Add scheduled postsubmit health checks (Wave 4b of `INTENT-verification-system.md`).
7. Delete the migration-sequence section of the INTENT doc once convergence is real.

**Rationale:**
- *Agent-first.* Autonomous agents cannot reason about wall-clock budgets when the surface they call has no commitment to one. Two named tiers with explicit budgets remove the "which flag should I use" judgement call.
- *No silent fallbacks.* SSO-unavailable cases skip with actionable guidance (Decision 57); they never crash and never silently weaken the gate.
- *Substrate matters.* Without a cheap, deterministic CI substrate, "default tier on every PR" is unaffordable and consolidation is impossible. Self-hosted runner solves the cost problem without reintroducing the discretion problem of local-only validation.
- *Reversible by design.* The migration is a multi-step ratchet; each step can be halted or rolled back. The convergence (deletion of legacy flags) is the moment the architecture is real.

**Related:** Decision 48 (Verification Tier Design), Decision 51 (Local-First Outbox, superseded by Decision 78), Decision 55 (RCA-First Executor -- no rescue agents), Decision 57 (Interactive vs Autonomous SSO recovery), `docs/INTENT-validation-architecture.md`, `docs/INTENT-verification-system.md`, `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (Gap 2; Future Direction).

> **2026-05 migration update:** The self-hosted EC2 runner substrate referenced in the Substrate field and migration Steps 3-5 was retired 2026-05-28 (CD.21); CI now runs on GitHub-hosted runners (`ubuntu-latest`) with OIDC. The two-tier validation model and both named tiers are unchanged; the substrate switch is transparent to the validation contract. See Decision 73.

---

## Decision 61: Scheduled-agent findings flow through ops_recommendations via the source field (Decided)

**Status:** Decided
**Date:** 2026-05-05

**Problem:**
The cc-scheduled-agents strategic plan (PLAN-cc-scheduled-agents.md) originally proposed a new `ops_agent_findings` Iceberg table and a new `ops_priority_queue_latest_run` Athena view to ingest structured findings from Claude Code scheduled agents. The plan was written before a full audit of existing infrastructure. Open Questions Q4 ("New table OR extend ops_recommendations?") and Q5 ("Does the new view risk the same _rn ambiguity?") were unresolved at planning time.

**Decision:**
Scheduled-agent findings flow through the existing `ops_recommendations` table via the `source` field. No new Iceberg table is created. No new Athena view is created.

Specific consequences:
- The `ops_agent_findings` Iceberg table proposed in the strategic plan is NOT built. The existing `source` field on `ops_recommendations` discriminates findings by origin.
- The `ops_priority_queue_latest_run` view proposed in the strategic plan is NOT built. The existing `ops_priority_queue_current` view (terraform/iceberg_tables.tf:1042-1051) already implements the latest-run-by-queue_run_id semantic via a correlated subquery, not ROW_NUMBER(), sidestepping the _rn ambiguity in `ops_recommendations_current`.
- The findings-processor Lambda will be retired in Phase 5 of the cc-scheduled-agents migration. Retirement is recorded here; the action is deferred.
- Ingestion of scheduled-agent findings is through `ops_data_portal.enqueue_findings(path)`, which routes entries through the existing offline-resilient outbox and drain cycle.

**Rationale:**
- The existing `source` field already discriminates record origins (used today for "executor-postmortem", "planning", etc.). No schema migration needed.
- The existing outbox drain cycle (Decision 51, superseded by Decision 78) is already offline-resilient. A second ingestion path would duplicate the reliability mechanism.
- The existing `ops_priority_queue_current` view avoids the `_rn` ambiguity bug present in `ops_recommendations_current`. Building a second identical view under a different name adds maintenance burden with no benefit.
- One fewer Iceberg table and one fewer view to keep in sync with the Terraform + OpsWriter dual-definition pattern.

**Closes Open Questions:** Q4 (New table OR extend? - extend via source field), Q5 (New view risk _rn ambiguity? - no new view needed).
**Deferred:** Q3, Q6, Q7, Q8, Q9, Q10 to Phases 2-5 per the strategic plan manifest.

**Related:** `docs/plans/PLAN-cc-scheduled-agents.md` (strategic plan), `docs/plans/PLAN-cc-scheduled-agents-phase-1.md` (this implementation), Decision 51 (Local-First Outbox, superseded by Decision 78), Decision 50 (Iceberg ops data store, superseded by Decision 78)

---

## Decision 89: GitHub Branch Protection Not Available -- CI Enforcement as the Only Merge Gate (Decided)

**Status:** Decided
**Date:** 2026-05-09
**Warehouse ID:** dec-089 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
PLAN-validate-two-tier required enabling `required_status_checks` branch protection on `main` (validate-python + terraform-validate) as the enforcement mechanism for the two-tier validation model. The GitHub REST API (`PUT /branches/main/protection`) returns HTTP 403 on private repositories under the free GitHub plan. The repository will remain on the free plan; upgrading to GitHub Pro is not planned.

**Decision:**
GitHub branch protection is permanently unavailable for this repository. The merge gate is enforced by convention and tooling rather than by GitHub API:

1. **Local pre-merge gate:** `python -m scripts.validate` (the default presubmit tier) must exit 0 before any PR is opened. This is the primary gate. The CLAUDE.md merge protocol documents it as mandatory.
2. **CI as a signal, not a lock:** The self-hosted runner runs `python -m scripts.validate` on every PR push. A failing CI job is a hard stop; the developer or agent must not merge a PR with a red CI status. This is enforced by convention rather than by GitHub API.
3. **Never-on-main hook:** The `.claude/hooks/never_on_main.py` pre-tool-use hook prevents direct file edits and commits on `main` within Claude Code sessions. This guards against the most common accidental-merge pattern.
4. **No squash-bypass:** All merges must be squash merges via `gh pr merge --squash` after CI passes. Direct `git push` to `main` is blocked only by the never-on-main hook; human discipline is required outside Claude Code sessions.

**Consequences:**
- Acceptance criterion "Main branch protection enabled" from PLAN-validate-two-tier cannot be met. Superseded by this decision. *(Superseded by Decision 83: criterion is now met.)*
- VP steps 9 and 10 from PLAN-validate-two-tier are permanently BLOCKED; they are retired here without resolution. *(Superseded by Decision 83: branch protection is now active.)*
- Any future migration to GitHub Pro or a public repository would unlock `required_status_checks` and should be revisited at that point. *(Superseded by Decision 83: the repository was made public 2026-05-30 per Decision 73 and the apply landed 2026-06-08.)*

**Related:** Decision 60 (Two-tier validation architecture), Decision 68 (Self-hosted EC2 runner), PLAN-validate-two-tier.

> **Amended by Decision 83 (2026-06-08):** Branch protection is now active. The `main-protection` ruleset is live (enforcement=active, non-wedging). The "permanently unavailable" premise is reversed; the merge-gate design consequences are preserved. See Decision 83 for live-probe verification and configuration details.

---

## Decision 67: Lambda Deployment and STRATEGIC Plan Execution Deferred Pending Telemetry Readiness (Amended - Partially Active)

**Status:** Amended by Decision 79 (2026-06-03). Two clauses; each has its own status.

**[LAMBDA-DEPLOY CLAUSE -- LIFTED by Decision 79 / CD.16 + CD.24]**
The blanket `DEFERRED: build_lambda.py --deploy` pattern is withdrawn. Plans are now gated per
Lambda artifact (see Decision 79 + CD.16). Step 12b of plan-critique updated accordingly.
The blanket DEFERRED marker is no longer acceptable in lieu of active per-Lambda deploy steps.

**[STRATEGIC-PLAN CLAUSE -- RETAINED, pending CD.17 / T4.2]**
**Status:** Active -- remove when reversal condition is met
**Reversal condition:** Telemetry Athena tables (`telemetry_sessions`, `telemetry_process_events`,
`telemetry_model_calls`, `telemetry_phases`, `telemetry_steps`) confirmed operational end-to-end
with passing data quality checks AND executor re-enabled per CD.17 / T4.2.

[RESTATED by Decision 95 (2026-06-23): the draft tables telemetry_process_events / telemetry_model_calls /
telemetry_phases / telemetry_steps collapse into the unified telemetry_observations table; the reversal
condition now tracks the canonical four-table model -- telemetry_sessions, telemetry_observations,
telemetry_transcripts (and telemetry_agents) operational with passing DQ checks AND executor re-enabled per
CD.17 / T4.2. The executor-re-enabled clause and the CD.17 / T4.2 gate are unchanged. See Decision 95.]

**Effect on planning (STRATEGIC clause only):**
- STRATEGIC plans are blocked. All plans must be IMPLEMENTATION type.

**Effect on plan-critique (STRATEGIC clause only):** Step 12d blocks STRATEGIC plans while
this clause is active.

**Rationale (original, preserved):** The executor telemetry pipeline (telemetry_sessions etc.)
is not yet confirmed operational. Running executor-mediated recs risks silent telemetry loss.
Lambda dispatcher is separately disabled pending telemetry confirmation and scheduled-agent
migration completion. The Lambda-deploy half reverses per Decision 79; the STRATEGIC half
reverses when telemetry is confirmed and executor re-enabled (CD.17 / T4.2).

---

## Decision 66: Precision Context Injection as Agent-First Design Principle (Decided)

**Status:** Decided
**Date:** 2026-05-08

**Problem:**
Agents composing fields that require LLM judgment (title, context, acceptance) frequently
produce thin or structurally-valid-but-semantically-empty values when they lack field
semantics in their context window. Storing semantics in ops.yaml (per Decision 65) solves
the documentation problem but not the runtime problem: an agent that never loaded ops.yaml
has no basis for producing a high-quality value.

**Decision:**
In an agent-first repository, the authoritative field semantics must be surfaced at the
moment the agent *composes* the value -- not stored passively in config, and not injected
as a post-rejection error message. Pre-composition context injection is categorically more
effective for LLM agents than post-failure correction: the agent self-evaluates against the
spec before writing rather than re-attempting after rejection.

The canonical implementation pattern is `get_rec_write_guidance()` (Wave 2 deliverable in
ops_data_portal): called before `file_rec()`, it returns the `semantics` text for each
LLM-judgment field from ops.yaml, forcing the spec into the agent's context before value
composition. Any portal function that writes agent-authored content must expose its semantic
contract proactively via this pattern.

This principle applies at all 5 instruction layers (docs/contracts/instruction-architecture.md).
The pattern generalises beyond ops_data_portal: any write gateway for agent-authored content
should expose field semantics before accepting a write, not only after rejecting one.

**Semantic Enforcement Architecture (Wave 2 addendum -- 2026-05-10):**

Formalised four enforcement tiers, each catching a different class of quality failure:

- **Tier A -- Pre-write injection:** `get_rec_write_guidance()` surfaces ops.yaml
  `description` + `semantics` + source registry to the agent before composition. Agents
  that call this before `file_rec()` self-evaluate against the spec and produce higher-quality
  values without being rejected. Auto-populated from ops.yaml column entries; no code change
  to `rec_write_guidance.py` required when new fields are added to ops.yaml.

- **Tier B -- Write-time deterministic rejection:** `file_rec()` validators enforce structural
  rules that are always correct regardless of repository state: path format (`_validate_file_path`),
  context length (`_validate_context_length` -- 80-char minimum), banned acceptance patterns
  (`lint_acceptance_command`), source registry membership (`validate_source`), and formula-derived
  fields (`automatable` from `compute_automatable`, `risk` from `compute_risk`). Validators are
  in `scripts/ops_data_portal.py`. Agents cannot override `automatable` or `risk` directly;
  the portal derives them from `config/executor_capabilities.yaml`.

- **Tier C -- Execution-time feasibility:** `validate_acceptance_feasibility()` in
  `scripts/executor/acceptance_lint.py` runs at executor invocation time, not write time.
  File existence and module availability checks are intentionally deferred here -- the target
  file may not exist until the executor creates it, so existence is context-dependent.

- **Tier D -- LLM semantic judge:** Not yet implemented. Intended to detect acceptance commands
  that are syntactically valid but semantically incorrect (e.g., grep for the wrong pattern,
  pytest for the wrong test class). Filed as a recommendation for a future session.

---

## Decision 65: ops.yaml Extended Contract is the Canonical Field Semantic Authority (Decided)

`config/data_quality/ops.yaml` (and `telemetry.yaml`) is the canonical field contract for
all DQ-governed tables. The `description` and `semantics` metadata fields within each column
entry define the field's semantic contract -- consumed by agents, ignored by the DQ runner.
This supersedes the separate human-readable briefing doc pattern (e.g.,
`docs/dq/ops-recommendations-remediation-briefing.md`). Do not create new briefing docs for
new tables. Add field context as `description` + `semantics` in the YAML directly. The briefing
doc for ops_recommendations is a legacy artefact; it is not maintained going forward. The
decision manifest YAML (`config/data_quality/decisions/{table}.yaml`) remains the remediation
state authority.

## Decision 64: Bootstrap Cohort Anchor for ops_recommendations is 2026-05-01 (Decided)

The bootstrap cohort for ops_recommendations consists of all records created before 2026-05-01
(the date the enforcement regime was established via Phase 3 ratchet PR #296 and formalised in
`docs/dq/DQ_REMEDIATION_METHODOLOGY.md`). All Class B (bootstrap artifact) temporal gates for
this table use `exclude_before: '2026-05-01'`. This anchor is fixed and must not be changed
retroactively. Bootstrap records are not corrupt -- they predate the rules. They age out of the
_current view as recommendations are closed or superseded.

## Decision 63: Execution Fields Excluded from ops_recommendations DQ Scope (Decided)

Execution fields (`execution_result`, `execution_date`, `execution_branch`, `execution_pr_url`,
`execution_steps`) are excluded from Phase 4 DQ remediation scope for ops_recommendations.
These fields record how a recommendation was executed, not its lifecycle state -- they are
telemetry, not ops state. They belong in `ops_execution_plans` or the telemetry tables.
Denormalising execution state into ops_recommendations creates two sources of truth that can
drift (rec says success, execution plan says failed). DQ enforcement for these fields is
deferred until execution state is normalised to the appropriate table (pending telemetry
maturity). Phase 4 decision manifest: `phase4_session: wave-4-deferred` for all five fields.

---

## Decision 62: No Separate DQ Scheduled Routine (Session E Elimination) (Decided)

**Status:** Decided
**Date:** 2026-05-06

**Problem:**
The original DQ enforcement strategy proposed a Session E architecture: a Claude Code cron agent would trigger an EC2 runner, which would execute the DQ runner, commit the resulting `dq-latest.json` to a branch, and auto-merge it. This introduced a separate scheduling concern, an EC2 runner dependency, a dedicated auto-merge flow, and additional operational complexity -- all separate from the existing validate.py presubmit tier.

**Decision:**
The Session E architecture is eliminated. DQ runs as part of `validate.py`'s presubmit tier on the EC2 self-hosted runner, which has SSO credentials. The presubmit tier auto-invokes the DQ runner when `logs/debug/dq-latest.json` is stale (>1h). No scheduling concern separate from validation itself.

Specific consequences:
- No Claude Code cron agent for DQ refresh.
- No dedicated EC2 runner separate from the self-hosted CI runner.
- No `dq-latest.json` PR/auto-merge flow.
- `ensure_fresh_dq_results()` in `scripts/validate.py` handles the auto-invoke when stale.

**Rationale:**
The presubmit tier on the self-hosted EC2 runner already has SSO credentials and runs before every merge. Tying DQ refresh to the validation lifecycle means freshness is enforced at merge time without a separate operational layer. The Session E architecture adds scheduling complexity and a separate failure mode (cron agent not running) that the presubmit model eliminates entirely.

**Related:** Decision 57 (Autonomous Improvement Control Plane), Decision 60 (Two-tier validation architecture), `docs/INTENT-dq-enforcement.md` (Phase 3 Decision Registry), `docs/INTENT-validation-architecture.md`

> **2026-05 migration update:** The SSO credential model and self-hosted EC2 runner referenced in the Rationale were superseded 2026-05-28 (CD.21); the presubmit DQ runner now executes on GitHub-hosted runners with OIDC. The core decision -- DQ as part of the presubmit tier, no separate Session E scheduling -- is unchanged. See Decision 73.

> **2026-06-16 amendment (premise revisit -- live-reader DQ):** The 2026-05 footnote held the "core decision ... unchanged" after CD.21. That stays true for the Session E MECHANISM itself (cron agent -> EC2 -> commit `dq-latest.json` -> auto-merge), which remains retired. But the load-bearing PREMISE of the no-separate-routine conclusion -- "the presubmit tier already has SSO credentials and runs before every merge," i.e. live DQ is cheap on the credentialed gate -- is now invalidated: CD.21 retired the SSO/EC2 substrate, Decision 73 measured ~10-min presubmit round-trips, and a DuckLake-reader 502 storm added ~17-20 min of DQ-verifier hangs plus merge-gate flapping (2026-06-15; PLAN-dq-gate-infra-resilience). For LIVE-READER-dependent DQ checks specifically (e.g. ulid_history_unique, current_merge_key_unique), the "no separate scheduled routine" conclusion is therefore DELIBERATELY REVISITED -- not reinterpreted: those checks move to a scheduled, non-gating MONITOR/canary that files recs (alarm-not-gate, CD.12), with uniqueness enforced STRUCTURALLY at write time (Decision 81 cl.3 MERGE-on-ULID + cl.8 current-MERGE-key) and only hermetic structural contract checks remaining on the merge gate. The silent-cron failure mode 62 worried about is mitigated by a persistent-unavailability alarm (Decision 74). This revisit is owned by roadmap tier_item T1.6 and is distinct from the GitHub-Actions-scheduled meta-validation (T3.7), which never re-introduced Session E. See docs/ROADMAP-PLATFORM.yaml (T1.6) and docs/plans/PLAN-dq-gate-to-monitor-roadmap.yaml.

---

## Decision 48: Verification Tier Classification (Decided)

**Decision:** Every implementation plan must declare a Verification Tier (V1, V2, or V3) based on the files in scope. The tier determines the minimum verification standard the plan's Ordered Execution Steps must meet.

**Problem:**
The rec-curator pipeline (rec-448 through rec-451) shipped with passing acceptance criteria and 100% unit test coverage, but failed on first live invocation with 7 integration bugs. Root cause: acceptance commands verified file contents (V1/structural) or ran unit tests with mocked dependencies (V2), but no step required deploying and invoking the actual Lambda to verify end-to-end behaviour (V3). The existing Lambda Deployment Assessment (Step 5d, Decision 47) addresses Lambda-specific cases but does not generalise to other integration boundaries (e.g., cross-service contracts, S3 key agreements, API schemas).

**Tier Definitions:**

| Tier | Name | Scope Trigger | Minimum Verification |
|------|------|--------------|---------------------|
| V1 | Static | Files with no runtime effect: docs, prompts, configs, .md, .yaml (non-handler) | grep/file-existence acceptance; no pytest required |
| V2 | Unit | Pure Python logic: scripts/, src/ files with no external integration | pytest with 100% coverage (existing test_coverage_checker.py gate) |
| V3 | Integration | Files that interact with external systems: Lambda handlers (src/data/handlers/), schedule.yaml, Terraform, API contracts, cross-service data flows | Deploy + invoke + verify output. Iterative: if invocation reveals bugs, fix and re-invoke in the same session. Acceptance must be behavioural (invoke and check output), never structural (grep exists). |

**Classification Rules (deterministic):**
1. If ANY file in scope matches V3 triggers, the plan is V3 (highest tier wins)
2. If no V3 triggers but any file matches V2 triggers, the plan is V2
3. Otherwise V1

**V3 Scope Triggers (exhaustive list):**
- Files under src/data/handlers/
- .github/agents/schedule.yaml (deployed to Lambda)
- .github/prompts/scheduled/ (deployed to Lambda)
- terraform/*.tf files that create/modify resources with runtime effects
- Any file listed in _LAMBDA_SCRIPTS in scripts/build_lambda.py
- Any change that modifies a cross-service contract (S3 key paths, JSONL schemas consumed by another service, API response formats)

**V3 Ordered Execution Step Requirements:**
1. Deploy step: build and deploy the artifact (e.g., python -m scripts.build_lambda --deploy)
2. Invoke step: trigger the deployed artifact and capture output (e.g., --trigger-lambda NAME, aws lambda invoke)
3. Verify step: check the output matches expectations (e.g., parse S3 output, verify status code)
4. Fix-and-retry: if invocation reveals bugs, fix the code, redeploy, and re-invoke in the same session until the output is correct
5. Acceptance command must be behavioural: it must invoke the system and verify output, not just grep for file contents

**What this does NOT include:**
- Automated tier detection script (future enhancement -- deterministic based on file paths, suitable for a Python script in scripts/)
- Changes to test_coverage_checker.py (V2 enforcement is already working; V3 is a different layer)

**Related:** Decision 43 (Directed Growth Governance), Decision 44 (Executor Boundary), Decision 47 (Lambda Deployment Assessment -- V3 subset)

**Limitation:** Verification tier classification is documentation-enforced only. No automated detection currently exists. A future rec should add a deterministic tier classifier to validate.py based on scope file paths, closing the enforcement gap that motivated this decision.

**Decision status:** Decided -- April 2026

## Decision 44: Executor Self-Modification Boundary (Decided)

**Status:** Superseded
**Date:** 2026-04

**Decision:** Superseded by Decision 117, which names `config/agent/executor/capabilities.yaml` as the code-level SSOT for the executor self-modification boundary table this entry originally defined; kept live here rather than archived because `capabilities.yaml` and `scripts/checks/executor/validate_executor_boundary.py` still cite "Decision 44" by name (Decision 146's still-cited-live-constraint carve-out; first exercised compaction under the DCG-02/DCG-03 lifecycle, docs/contracts/decision-entry.yaml's `compaction:` section).

**Superseded by: Decision 117**

---

## Decision 43: Directed Growth Governance (Decided)

**Decision:** Enforce structural size limits, tool tier taxonomy, and responsibility manifests across all repository code, prompts, and agents. Every enforcement gate supports explicit waivers with decision-id references so legitimate orchestrators are not blocked.

**Problem:**
The autonomous, recursive self-improvement loop modifies prompts, scripts, and agents. Without structural limits, files grow unbounded -- `execute_recommendation.py` reached 3177 SLOC, `validate.py` 1198 SLOC. Agent context windows are finite; monolith files degrade LLM execution quality. Tool sprawl in agent frontmatter makes reasoning about risk impossible.

**Structural limits:**

| Dimension | Limit | Waiver pattern |
|---|---|---|
| Python file SLOC | 500 non-blank, non-comment lines | `# complexity-waiver: <decision-id>` anywhere in file. [Amendment 2026-07-21: amended by Decision 102 -- the complexity-waiver comment no longer authorises unbounded SLOC growth; decompose by default per Decision 128.] |
| Cyclomatic complexity | 20 branch nodes per function | Same waiver comment in file |
| `.prompt.md` file token budget | 3000 lines | `# complexity-waiver: <decision-id>` in frontmatter comment |
| `.agent.md` file token budget | 1500 lines | Same |
| Responsibilities per orchestrator | 2 max | `max_responsibilities: 2` in frontmatter |
| Responsibilities per reviewer/scheduled/subagent | 3 max | `max_responsibilities: 3` in frontmatter |

**Tool tier taxonomy (T0-T3):**

| Tier | Permitted tools | Risk level |
|---|---|---|
| T0 | read, search | Safest -- read-only |
| T1 | T0 + terminal read (getTerminalOutput) | Terminal observation |
| T2 | T1 + file-edit (replace_string_in_file, create_file) | Standard executor |
| T3 | T2 + runInTerminal write | Highest risk -- explicit justification required |

**Day-1 waivers:** The following existing over-limit files receive `# complexity-waiver: decision-43` annotations and are targeted for reduction via Area A extractions in `PLAN-infra-directed-growth.md`: `validate.py` (1198 SLOC), `step_runner.py` (1285), `postflight.py` (1216), `plan.py` (1073), `execute_recommendation.py` (3177).

**Enforcement:** `validate.py` hard gates (SLOC, cyclomatic complexity, token budget, tool tier) -- all implemented via `PLAN-infra-directed-growth.md`. Governance configuration in `config/agent_governance.yaml` and `config/agent_tool_tiers.yaml`.

**Related:** Decision 42 (Three-Tier Workflow Architecture), Decision 44 (Executor Self-Modification Boundary)

**Decision status:** Decided -- April 2026

---

## Decision 41: Scalable Feature Architecture -- Three-Layer Data Pipeline (Decided)

**Decision:** Adopt a three-layer data architecture (Raw -> Encoder -> Discovery) that removes interpretability as a constraint, enables model-agnostic discovery, and ensures constant discovery cost regardless of raw feature count.

**Problem:**
The current Phase 2 schema design hardcodes ~35 native columns with specific deltas (delta_price_1d, zscore_rsi_30d, etc.). This approach has scaling limits:
1. Adding new data sources requires schema changes and explicit delta definitions
2. Discovery cost scales with feature count (PySR explores O(features x depth x population))
3. At 1,000+ features, discovery becomes the compute bottleneck, not storage
4. Implicit assumption that formulas must be human-interpretable limits model diversity

**Industry context:**
Top quantitative firms (Renaissance, Two Sigma, Citadel) do NOT require interpretability for trading signals. They optimize for returns, not explanation. Interpretability is a human need, not a system need. Regulatory requirements (MiFID II, SEC) apply to client-facing asset management, not proprietary trading.

**Architecture (three-layer):**

```
RAW LAYER (Athena/Iceberg, append-only, normalized)
  market_data_raw, sentiment_raw, fundamentals_raw, alt_data_raw
  - Universal transforms applied automatically (all windows x all numeric columns)
  - 1,000+ columns over time -- storage is cheap
            |
            v
ENCODER LAYER (VAE or Transformer, trained daily/weekly)
  Input: 1000+
  Output: 64-128 latent dims
            |
            v
DISCOVERY LAYER (model-agnostic)
  PySR (symbolic), LightGBM, Attention NN, Future models
            |
            v
UNIFIED EVAL (Sharpe, DD, win rate)
```

**Key design principles:**
1. **Interpretability is not a constraint** -- the system evaluates models by performance metrics (Sharpe, drawdown, win rate), not human understanding. SHAP/attention weights provide debugging capability without requiring interpretable formulas.
2. **Universal transforms** -- global config defines windows (1d, 3d, 7d, 14d, 30d) and transforms (pct_change, zscore, ema_diff, rank_percentile) applied to ALL numeric columns automatically.
3. **Encoder absorbs feature growth** -- adding 100 new raw features has zero marginal discovery cost; encoder compresses to fixed 64-128 latent dimensions.
4. **Model-agnostic discovery** -- PySR, LightGBM, neural networks, and future models all compete on the same evaluation metrics. No model type is privileged.
5. **Automated pruning** -- weekly job removes features with >95% correlation or zero usage in winning models over 8 weeks.

**Trade-offs accepted:**
- Latent dimensions are not directly interpretable (debugging via SHAP/attention instead)
- Encoder training adds compute cost:
  - Lambda path (CPU-only, 1000 features, 50 epochs): ~$0.05-0.15/day (15-min Lambda x2 at $0.0000166667/GB-s)
  - SageMaker path (ml.m5.xlarge, 4 vCPU, 16 GB RAM): ~$0.23/hr; a 1-hr training job = ~$0.23/day
  - Decision threshold: start with Lambda; switch to SageMaker when training exceeds 10 minutes
- Initial implementation requires new infrastructure (encoder training pipeline, attention layer)

**Implementation path:**
1. Add `config/features.yaml` with global transform config (rec-201)
2. Create `src/data/transform_engine.py` for universal transform generation (rec-202)
3. Create `src/models/encoder.py` for VAE/Transformer encoder (rec-203)
4. Create `src/models/attention.py` for supervised attention layer (rec-204)
5. Add `feature_vectors` Iceberg table (rec-205)
6. Update `src/lab/pysr_factory.py` to consume latent + attention-selected features (rec-206)
7. Add parallel discovery runners (LightGBM, neural attention) (rec-206)
8. Unified evaluation in `src/lab/model_evaluator.py` (Sharpe, DD, win rate) (rec-207)

**Related:** Phase 2 (schema flattening), Phase 3 (formula integration), Decision 40 (Copilot SDK migration deferred), rec-201 through rec-209

**Decision status:** Decided -- April 2026

---

## Decision 39: Workflow Orchestration — Step Functions over Airflow (Decided)

**Decision:** Use AWS Step Functions as the primary orchestrator for all mixed deterministic + LLM workflows. Do not adopt Apache Airflow (open-source or MWAA).

**Problem:**
As more scheduled tasks and LLM agents are added, they will increasingly need to interoperate: a deterministic data fetch feeds an LLM analysis, whose output conditionally triggers another deterministic step. A suitable orchestrator must handle scheduling, dependency chaining, retries, and branching — and must work within the project's constraints (no Docker on company VM, cost-sensitive, AWS-native).

**Options considered:**
- **Apache Airflow (self-hosted):** Open-source and free, but requires Docker for the scheduler and workers — not runnable on company VM. Strong DAG tooling but highest operational burden; overkill below ~100 DAGs.
- **MWAA (Managed Airflow on AWS):** Removes the Docker dependency, provides full Airflow feature set. Eliminated due to ~$350/month minimum cost and the fact that Airflow's Python DAG model adds complexity that Step Functions' JSON state language avoids.
- **AWS Step Functions:** Already in use for the data pipeline. Natively handles deterministic/LLM interleave via Lambda states. `Choice` states branch on LLM output, `Parallel` states fan out data fetches, `Map` states iterate over tickers. Built-in retry with exponential backoff (critical for LLM API rate limits). Native timeout per state. Zero additional infrastructure cost — pay per state transition.
- **Custom DAG engine:** Rejected. Step Functions IS a managed DAG engine; building a custom one would duplicate its functionality at significant maintenance cost.

**Decision:**
Step Functions is the orchestrator. Each workflow is a Step Function state machine. Each state is typed as either `task` (deterministic Lambda) or `agent` (LLM-backed Lambda). EventBridge provides cron scheduling. SQS provides a rate-limit buffer when LLM API concurrency is constrained. SNS handles failure notifications.

**Future-state architecture:**
- `config/workflows/` — YAML workflow registry (schedule, steps, types, dependencies)
- `src/tasks/` — deterministic Lambda handlers
- `src/agents/` — LLM-backed Lambda handlers
- `src/workflows/` — Step Functions definitions (or Terraform-generated from YAML registry)
- A Terraform module reads workflow YAMLs and generates state machines + EventBridge rules

This scales from the current 5 agents to 30+ workflows without architectural changes. Airflow should be re-evaluated only if the workflow count exceeds ~50 and the YAML-registry pattern becomes limiting (cyclic dependencies, complex backfill logic, multi-team access).

**Related:** rec-164 (repo restructuring), rec-159 (Fear & Greed scraper PoC proves the task/agent pattern)

**Decision status:** Decided — April 2026

> **Update (2026-08-02):** ESB-10 (audit ad02653) -- CD.27's "Regular Lambdas are deterministic-only" discipline point is scoped to the executor's ITERATIVE persona loops (CD.27 personas satisfying P1/P2/P3); it does not narrow this Decision's `agent` state type for single-shot LLM-backed regular Lambdas, which continues to govern unchanged. This annotation does not amend the Decision above.

---

## Decision 38: Workflow Consolidation — Instruction Files, Gotcha Triage, and Session Automation (Decided)

**Decision:** Consolidate duplicate `copilot_instructions.md` (underscore) and
`copilot-instructions.md` (hyphen) into a single file; triage the gotcha list from ~33 to
~25 by removing tooling-enforced entries and condensing related groups; simplify
`implement.prompt.md` from 21 steps to 10; and add `session_postflight.py --auto` for
single-command session close.

**Problem:**
- Two instruction files with divergent content consumed extra context budget and created
  confusion about which was authoritative (VS Code loads the hyphen file)
- ~33 gotchas included many that were already enforced by tooling (pre-commit, preflight,
  validate.py) or had been subsumed into other entries
- `implement.prompt.md` at 21 steps was too long to survive context compaction mid-session,
  causing model confusion and requiring "prodding" to resume correctly
- Session close required 5+ separate commands; context compaction mid-session often caused
  agents to skip or mis-sequence them

**Decision:**
- Delete `copilot_instructions.md` (underscore); update all 7 references to point to the
  hyphen file
- Condense gotchas: remove tooling-enforced entries, merge related entries (Venv+Version
  Manager, Import Safety Patterns, Windows Subprocess, Athena/Iceberg, Test Isolation)
- Rewrite `implement.prompt.md` to 10 steps, with session close consolidated into a single
  `--auto` call
- Add `--auto` flag to `session_postflight.py` that executes validate→close→metrics→commit→push
  in sequence, returning a combined JSON status

**Trade-offs accepted:**
- Some historical context removed from gotcha condensation (e.g., specific error messages);
  mitigated by keeping the essential "what to do" guidance
- Shorter implement.prompt.md cannot self-document every edge case; relies on copilot-instructions
  as the primary reference for gotchas

**Decision status:** Decided — April 2026

> **Update (2026-07-21):** `copilot-instructions.md` and `implement.prompt.md` were deleted at T-1.13 (superseded by the `.claude/skills/` + `.claude/commands/` architecture, Decision 76/90); the ghost-file guard survives as the current enforcement mechanism.

---

## Decision 37: Lambda + GitHub Models API for Scheduled Agents (Decided)

**Decision:** Replace the GitHub Actions scheduled-agents workflow with AWS Lambda functions
that call the GitHub Models API directly, using a GitHub PAT stored in Secrets Manager.

**Context:**
- Decision 36 (GitHub Actions OIDC) was blocked by SCP denying `sts:AssumeRoleWithWebIdentity`
  from external IP ranges (GitHub Actions runner IPs)
- Static IAM users are also blocked (`iam:CreateUser` SCP)
- GitHub Models API (`https://models.github.ai/inference/chat/completions`) is compatible with
  the same free-tier models used via Copilot CLI, accessible via PAT authentication

**Implementation:**
- `aws_lambda_function.scheduled_agent_dispatcher` — reads `schedule.yaml`, runs due agents
  via GitHub Models API, writes findings to `agents/{name}/{timestamp}.jsonl`
- `aws_lambda_function.findings_processor` — triggered by S3 ObjectCreated on `agents/` prefix,
  unions findings to `findings/unified.jsonl`, compares against existing recs via Models API,
  appends new ones to `recommendations/agent-recommendations.jsonl`
- `aws_secretsmanager_secret.github_pat` — stores GitHub PAT (value set manually post-deploy)
- EventBridge hourly rule triggers dispatcher; S3 event notification triggers processor
- Lambda runs at `api.github.com` endpoint (no SCP restriction — Lambda egress is not blocked)

**Trade-offs:**
- Requires a GitHub PAT in Secrets Manager (manual step after `terraform apply`)
- PAT must have GitHub Models API access (same scope as Copilot CLI PAT)
- Lambda cold-start adds ~1s latency (acceptable for scheduled background work)
- Free tier: 150 requests/day, 15 requests/minute — sufficient for 4 agents/week

**S3 key layout:**
```
agents/{name}/{timestamp}.jsonl       ← raw findings per agent
findings/unified.jsonl                ← union of all findings
recommendations/agent-recommendations.jsonl  ← agent-generated recs (agent-NNN)
```

**Recommendation namespace separation:**
- Local: `logs/.recommendations-log.jsonl` (IDs: `rec-NNN`) — manual sessions, code review
- S3: `recommendations/agent-recommendations.jsonl` (IDs: `agent-NNN`) — Lambda-generated

**Decision status:** Decided — April 2026

**Superseded by: Decision 116**

---



## Decision 35: Terraform Workflow Integration (Decided)

**Decision:** Integrate terraform plan/apply gates into the `/plan` and `/implement` workflow for
infrastructure changes.

**Context:**
- Terraform files (.tf) were validated syntactically (terraform validate, fmt) but never
  planned/applied during implementation
- The `agent/infra-s3-logs` session created S3 bucket resources but had no verification they would
  actually deploy
- Infrastructure errors were discovered post-merge rather than during implementation

**Implementation:**
1. `plan.prompt.md` Step 4 (Infrastructure Assessment) adds Infrastructure Assessment section when scope includes .tf files
2. `plan.prompt.md` Step 4 embeds the terraform gate into the plan's Ordered Execution Steps and Verification Plan
3. `session_preflight.py` reports `terraform_pending` status
4. `validate.py` warns when terraform changes are pending (exit code 2 from detailed-exitcode)

**Rationale:**
- Catches infrastructure configuration errors during implementation, not post-merge
- Maintains human-in-the-loop for terraform apply (no auto-apply)
- Aligns with Decision 24 (agents use sandbox only; promotion is human-triggered)

**Trade-offs:**
- Adds friction to purely additive infrastructure changes
- Requires AWS SSO session for plan (not just validate)
- Mitigated by "defer to post-merge" option for low-risk additions

**Decision status:** Decided — April 2026

[Amendment 2026-07-21: amended by Decision 77 clause 3 -- the unconditional "apply is never automatic" is scoped; sandbox auto-applies behind the deterministic guard (`scripts/terraform_apply_guard.py`) plus subagent plan review.]

---

## Decision 24: Multi-Environment Deployment Strategy (Decided)

**Context:** The repository currently deploys only to a sandbox AWS environment. Production trading requires a staging→production promotion path with appropriate access controls, rollback capabilities, and separation of concerns between code deployment and formula lifecycle.

**Decision:** Use GitHub Environments with single-branch promotion model:

**Branch Strategy:**
- All code lives on `main` — no separate branches for staging/production
- Promotion is a **deployment action**, not a branch merge
- Git tags (`sandbox-YYYY-MM-DD`, `staging-YYYY-MM-DD`, `prod-YYYY-MM-DD`) mark what SHA is deployed where

**GitHub Environments:**
- `sandbox`: Auto-deploys on every push to main; AWS credentials for sandbox account
- `staging`: Daily scheduled promotion (if sandbox CI green) OR manual trigger; separate AWS account
- `production`: Manual trigger with required reviewer approval; production AWS account

**Terraform Promotion (same code, different config):**
```
terraform/
  envs/
    sandbox.tfvars    # account_id, bucket_prefix, etc.
    staging.tfvars
    production.tfvars
```
- Push to main → auto `terraform apply -var-file=envs/sandbox.tfvars`
- Manual trigger to staging → `terraform apply -var-file=envs/staging.tfvars`
- Manual trigger to production → `terraform apply -var-file=envs/production.tfvars`

**Rollback Strategy:**
- `rollback.yml` workflow: checkout previous git tag, apply Terraform for that SHA
- **Orphaned resources (new resource in rolled-back-from version):** Terraform does NOT destroy resources missing from code. Options:
  1. Forward-fix: Add `removed {}` block to current code (Terraform 1.7+)
  2. Manual cleanup: `terraform state rm <resource>` then delete via AWS CLI/console
  3. Drift detection: AWS Config rules or Terraform Cloud detect out-of-band resources
- **Prevention:** AWS Service Control Policies (SCPs) block console creation; all infra via IaC only

**Emergency Escape Hatches:**
- `workflow_dispatch` with environment selector bypasses staged promotion
- Repo admin can bypass required reviewers for hotfixes
- Rollback workflow deploys previous tag directly

**Agent SSO Profile Restrictions:**
- Agents only see `company-aws-profile` profile (sandbox)
- Staging/production profiles (`company-aws-profile-staging`, `company-aws-profile-production`) exist in AWS config but are NOT referenced in any prompt or agent file
- Prevents accidental agent deployment to staging/production
- Human manually triggers promotion workflows via GitHub UI

**Formula Lifecycle vs Code Deployment (separate concerns):**
- Code deployment: GitHub Actions → sandbox/staging/production AWS accounts
- Formula lifecycle: Application logic within each environment (discovery → paper → live)
- Formulas are data in Iceberg tables, promoted by application code — not by CI/CD

**Rationale:**
- Single branch eliminates merge choreography between environment branches
- GitHub Environments provide audit trail, environment-specific secrets, and approval gates
- Git tags provide clear "what's deployed where" without inspecting Terraform state
- Formula promotion is continuous (performance-based) while code promotion is deliberate (CI-gated)
- Agent profile restriction prevents costly mistakes without blocking human operations

**Rejected alternatives:**
- Branch-per-environment (GitLab style): Creates dependency chains, forces merge order
- Separate Terraform PRs per environment: Unnecessary friction, same code applies to all
- Formula promotion as deployment action: Wrong abstraction — formulas are data, not code

**Status:** Decided — March 2026

> **2026-05 migration update:** The `company-aws-profile` credential referenced in the Agent SSO Profile Restrictions section was retired; the current model is the `agent_platform` static-key assume-role chain (Decision 73 / CD.21). The multi-environment promotion strategy (separate sandbox/staging/production AWS accounts) is architecturally superseded by the single personal-account model.

---

## Decision 25: Git Worktree Parallel Development Workflow (Decided)

**Context:** Decision 23 enabled parallel planning via branch-specific plan files (`PLAN-{slug}.md`). However, true concurrent implementation still required checkout switching between branches, blocking one feature while working on another.

**Decision:** Support git worktrees as the recommended approach for parallel feature development:

**Worktree workflow:**
1. `/plan` creates branch `agent/{slug}` and optionally sets up worktree at `../agent-platform-{slug}`
2. Developer opens worktree in separate VS Code window
3. Each window has its own working directory, branch, and plan file
4. Commits/pushes work normally (worktrees share `.git`)
5. After merge, worktree is removed: `git worktree remove ../agent-platform-{slug}`

**Benefits:**
- True parallel implementation: work on feature B while feature A is in code review
- No context switching: each feature has its own window/terminal state
- Clean separation: no risk of committing to wrong branch

**Trade-offs:**
- Disk space: each worktree is a full working copy (~50MB excluding .git)
- Cognitive load: must remember which window is which feature
- Tooling: some VS Code extensions may not handle multiple workspaces well

**Guidance:**
- Use worktrees for features expected to overlap (e.g., parallel planning + implementation)
- Use traditional checkout for sequential work (most common case)
- Always remove worktrees after merge to avoid clutter

**Status:** Decided — March 2026

---

## Decision 27: Git Bash venv Activation Fix via setup.py (Decided)

**Context:** Windows developers using Git Bash experience venv activation failures due to Python's venv module generating `.venv/Scripts/activate` scripts with Windows backslashes. Git Bash interprets backslash sequences (\U, \G, etc.) as escape codes, corrupting PATH and causing cryptic import failures. This is the highest-friction recurring issue in the development loop.

**Decision:** Implement an idempotent `fix_venv_activate_for_git_bash()` function in `setup.py` that:
1. Converts Windows backslashes to forward slashes in VIRTUAL_ENV lines (C:\path → /c/path)
2. Leaves all other script content unchanged
3. Detects if already fixed (output contains forward slashes) and skips redundantly
4. Runs automatically during `python setup.py` invocation, right after venv creation

**Implementation:**
- Core mechanism: Regex substitution with path conversion helper function
- Placement: In `setup.py` main() immediately after `create_venv()` call
- Idempotency: Check for 'VIRTUAL_ENV="/' in file content; skip if found
- Platform compatibility: Forward slashes work on both Windows and Unix systems

**Rationale:**
- **Placement in setup.py (not shell script):** Pure Python automation is platform-agnostic and doesn't depend on Git Bash/bash availability. Aligns with repository's "Python scripts only for automation" rule.
- **Idempotent design:** Developers can run setup.py multiple times without fear of corruption (e.g., after branch switching or environment reset).
- **Universal scope:** Every developer who runs setup automation gets the fix automatically; no separate workaround steps needed.
- **Regex pattern choice:** Single targeted pattern (`r'VIRTUAL_ENV="([^"]+)"'`) minimizes risk of unintended modifications to script logic.

**Design Validation:**
Comprehensive test suite (5 tests) validated:
- Basic Windows→Git Bash path conversion including drive letter transformation
- Idempotency (running twice produces unchanged output)
- Graceful handling when `.venv/Scripts/activate` doesn't exist (early return)
- Content preservation (only VIRTUAL_ENV lines modified)
- Edge case coverage (multiple drive letters D:, E:, etc.)

**Status:** Agent-decided — approved by test suite (135/135 pass) and code review (0 Critical/High findings, 1 Low style suggestion implemented)

---
