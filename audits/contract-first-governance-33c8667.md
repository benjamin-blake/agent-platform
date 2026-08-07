# Contract-first governance audit -- companion report

Audited commit: `33c8667` (origin/main, 2026-08-07). YAML system-of-record:
`audits/contract-first-governance-33c8667.yaml`. Findings: 11 (0 critical, 3 high) against 15
rejected candidates. Maturity: strong across S1-S5 (S2/S5 were initially rated frontier;
downgraded by the post-run adversarial review's EX7 correction -- see the amendment section at
the end).

## Arc A -- why the interventions eroded (Q1: primary-mechanism-identified)

Erosion is real, but it is not where five prior audits looked. The mechanisms those audits built
-- authoring grammar, shared header parser, conformance check, supersession guard, compaction
lifecycle, generated index, SPIRIT lane, prose metering -- all still hold. Every ending that WAS
an erosion belongs to one family, the size ceilings, and all five share one mechanism:

**The interventions govern stock; nothing built governs flow; and each intervention is itself
recorded as a large live entry drawn from the stock it protects.**

The evidence in one table. Levers by ceiling ("moves" = reduces the bound quantity):

| Ceiling (value at base) | Compaction (D149) | Archival (D146) | Per-entry size norm (rec-2934) | Significance bar (D150) |
|---|---|---|---|---|
| Live headers: 119/**120** -- binds first | never (never_remove_headers) | **only lever** -- operator-disposed; exercised once (07-21), declined at D160 p5 | never (+1 header regardless) | would; **no evaluator** |
| Combined bytes: 684,796/**700,000** -- ~1.5 days at measured inflow | yes -- eligible live set already empty (2/2 processed, 1,381 B remain) | never -- documented inert (`_RELIEF_VALVES`, decision-entry.yaml:236-239) | would; **unbuilt** | would; no evaluator |
| Index bytes: 110,582/**131,000** | marginal (excerpt only) | no -- archived rows keep full excerpts (rec-3012 **unbuilt**) | never (~764 B/row regardless) | would; no evaluator |

No built lever moves the first-binding ceiling. The only lever that moves all three is the one
with no evaluator. So each time a ceiling bound inside days-scale runway, the only available act
was a raise -- and that is exactly the observed record: 400k -> 500k (D145, five days after
D134); retire-at-499,960/500,000 (D160, ten days later); index pin 110k -> 131k after arithmetic
exhaustion with 236 B headroom (D166 p9); and the bridge raise of both surviving ceilings now in
flight, over a decision-scout BLOCK resolved by recorded human override -- against D145's own "a
second stopgap raise is itself a signal the structural fix is overdue" and D160's "never a silent
re-raise." Every raise was loud, cited, and reversal-conditioned. **The ritual held perfectly;
the bound did not.** That is the connecting step from partial-relief to erosion the prompt asked
for: incompleteness (disjoint levers) becomes erosion the moment inflow outruns the one lever the
binding ceiling has.

The self-consumption half (DD-A, pinned arithmetic):

| Figure | Value |
|---|---|
| E1 entry bodies (9 entries, header-to-next-header spans, UTF-8) | 86,909 B |
| Live file at base | 573,726 B |
| **Byte share** | **15.15%** |
| **Header share** (9 / 120-header ceiling) | **7.5%** |
| Reclaimed by built levers in the same window | ~5-8 KB (2 compactions; 1 archival wave -- header relief only) |
| Measured inflow, D160 -> base (518,839/113 -> 573,726/119) | ~9,150 B/day, ~1.5 headers/day (cadence-inflated window; treat as upper bounds) |
| Band medians (bytes) | D<=60: 2,327 (n=16) / D61-100: 3,898 (n=37) / D101-139: 3,241 (n=39) / D>=140: **7,257** (n=27) |

If each intervention's implementing code and contracts were counted the cost rises further
(guards, index generator, grammar contract: roughly another 40 KB outside the corpus) -- but the
pinned corpus-internal figure is the comparable one, and it alone answers NS6: the cure recorded
~87 KB against ceilings whose levers recovered ~5-8 KB. The cure was drawn from the disease's
ration. Mechanism density (my metric: distinct `docs/contracts/`, `scripts/*.py`,
`config/*.yaml`, `.github/workflows/` references per KB) runs 0.326 / 0.272 / 0.417 / 0.384
across the four bands -- the governance band is not idle prose but mechanism payload, which is
the routing point: it is specification and change narrative living in the wrong record type.
(rec-3023's "halved density" claim uses an unstated metric my re-derivation does not reproduce;
both directions support the same conclusion.)

Timeline (all 2026): DPI audit 07-05 -> DAF 07-06 -> **D134** 07-16 (ceilings installed) ->
DCG + ACG 07-21 -> **D145/D146** 07-21 (raise; archival policy + 6-entry wave #676) -> **D149**
07-23 -> **D150/151/152** 07-24 -> **D160** 07-31 (retire live-byte ceiling; bounded retrieval)
-> SGE 08-03 -> **D165/D166** 08-04 -> PR #855 08-05 (no Decision minted) -> bridge plan 08-06
(in flight). Eight of E1's nine entries landed in a fifteen-day window tracking the audit
cadence -- Candidate B's cluster observation is correct as far as it goes, and the audit rounds
themselves are `relief-still-holding` rows. What Candidate B cannot explain is why the same
ending recurred four times on the ceiling family specifically; the matrix can.

## DD-B -- the blocked Decision 167 draft

The work shipped 2026-08-05 as PR #855 (`workflow-body-ratchet`, SGE-03), with **no numbered
Decision** -- the commit message itself says so. Point-by-point (the draft says "four points" and
carries five; the self-miscount is itself a specimen of unreviewed drafting):

| Draft point | Today's rule says | Actually shipped to | My end-state |
|---|---|---|---|
| 1. R3 scope extends to workflows; R1/R2 composite-only | field_semantics -> owning contract | `composite-action-shape.yaml` r3 scope text + guard module | same |
| 2. `r3_workflows:` section, seeded at measured sizes | operational/config | `config/composite_action_body_baseline.yaml` (128 bodies, 17 files -- the draft said 127) | same |
| 3. Rides existing check, no new registered name | change record | PR #855 commit body | same |
| 4. "Last seeded grandfather; extraction is the valve; no third seeding" | **rule is silent** (standing commitment) | **enforced section allowlist in guard source** (`sections: [r1, r3, r3_workflows]`; a fourth section fails the guard) | specification -- a commitment with an evaluator is a rule, not a Decision |
| 5. Reciprocal blockquote on D162 + Significance stanza | corpus bookkeeping, only if an entry exists | nowhere -- correctly evaporated | n/a |

Verdict: correctly BLOCKED under the significance bar's rows for points 1-3 and 5 -- but the rule
did not do the blocking; the operator did, applying a rule recorded nowhere. Point 4 is the
genuine silence: within 24 hours the same content class took two different homes (D166 p6's
"never a second raise" pre-commitment lives as corpus prose; #855's "no third seeding" lives as
enforced code). That pair is Q2's sharpest decidability failure, and #855 is simultaneously the
proof that the correct routing -- mechanism to contract+config, narrative to the commit body,
nothing to the corpus -- is fully reachable under current tooling. `meta.dd_b_shipped_outcome` is
empty: located and described here.

## DD-C -- three migration traces

**Decision 58** (Superseded stub, 702 B). Compacted in the 07-21 hygiene wave; archival -- the
preferred branch -- is blocked by two live citations (ROADMAP T5.3, instruction-architecture.yaml).
Processable by existing mechanisms the moment those citations retire; cost XS. Disposition: archive
(blocked behind citation retirement; ledger territory of rec-2822).

**Decision 37** (superseded full body, 2,277 B). The sharp case: archival blocked (18 citing
files under the stated exclusion set, including terraform SM brokers/oidc and the DuckLake
runtime); compaction blocked -- the eligibility criterion requires the superseder to restate
every live clause, and D116 restates none of it ("Secrets Manager": 2 occurrences in D37, 0 in
D116); migrate-then-rehome does not exist (rec-2823 unbuilt). **No built mechanism can process
this entry** (finding CFG-10). Counterfactual loss if compacted anyway: 18 files' citations
resolve to a number whose content -- the PAT-in-Secrets-Manager architecture, key layout,
namespace split -- survives nowhere current.

**Decision 162** (active, mechanism-majority; also E2). Not superseded, so archival and
compaction are ineligible; its R1/R2/R3 semantics already have a machine home
(composite-action-shape.yaml + baseline + guard), making it the exemplar of designed parallel
statement. The load-bearing conclusion: since a ratified body is never rewritten, mechanism
content that enters the corpus stays until a supersession event -- **routing is one-way at
entry**. That is why Arc C puts authoring-side gates before any outflow work.

## DD-D -- the two contract populations (and S1) compared

| Property | S1 decision corpus | S2 ritual contracts (16: 7A/3B/6C) | S3 free-form (23, incl. 2 .md) |
|---|---|---|---|
| Schema validation | marker grammar, forward-only conformance | full schema + $ref resolution, per-file loud | none (safe_load + mapping check; .md invisible) |
| Authoring grammar | decision-entry.yaml | contracts_schema.py | none |
| Amendment log | dated annotation forms | required on change (drift Pass 2) | none |
| Status / supersession | markers + guard + index edges | status lifecycle incl. provisional_v0 re-ratification | ad-hoc keys on 3 files |
| Size governance | 120 headers + 700k combined + index pin | structural class, 500 eff lines, 2 marked grandfathers | .yaml only; .md exempt |
| Binding to code | ~19,414 citations; marker AUTHORIZATION (D165) | generated field_semantics + pydantic/DQ drift | bespoke per file (router->placement, marker-grammar->guard) or none |
| Discoverability | committed index + category_tags + scout | 8/39 router; generated bindings | 8/39 router; grep |
| Warehouse projection | ops_decisions SCD2 | n/a (they are the schema source) | none |
| Review lane | PR + scout + critique + operator gate | PR + drift gate | PR only |

Q4 answer: ready for field semantics (the ritual side is the strongest surface in scope);
**not ready for mechanism content** without CFG-04/CFG-09's minimal upgrade
(declared subject + evaluator + log-on-change), because today the routing rule sends content from
the best-governed prose surface to the least-governed structured one. Q5's free-form detection
answer follows directly: parallel and contradictory assertion are not merely undetected but not
well-posed until a subject is declared; the minimum mechanism is a subject-uniqueness assertion
in the drift gate's structural pass, whose false positives are bounded because subjects are
declared, not inferred.

## E2 -- content partition of the ten newest entries

Rule in `meta.partition_rule`; unit = approximate byte share per entry, whole-block attribution.

| Entry | Spec | Rationale | Change-record | Other |
|---|---|---|---|---|
| D157 | 55% | 25% | 15% | 5% |
| D158 | 55% | 30% | 10% | 5% |
| D159 | 60% | 20% | 15% | 5% |
| D160 | 30% | 30% | 35% | 5% |
| D161 | 55% | 25% | 15% | 5% |
| D162 | 50% | 30% | 15% | 5% |
| D163 | 25% | 45% | 25% | 5% |
| D164 | 10% | **75%** | 10% | 5% |
| D165 | 45% | 25% | 20% | 10% |
| D166 | 40% | 25% | 30% | 5% |
| **Mean** | **~43%** | **~33%** | **~19%** | ~6% |

Shares are single-rater estimates at 5-point granularity; treat them as +/-10 points -- the
conclusion survives any plausible rater error. Roughly **62% of the newest band's bytes are
specification or change narrative** -- content whose home under the routing rule is a contract or
the PR record. D164 is the existence proof that the corpus's own conventions already support the
clean ADR shape.

## Arc B -- end-state (Q7)

`docs/DECISIONS.md` becomes what its external namesakes are (Nygard/MADR): an ADR log --
rationale, ruling, reversal conditions, pointers -- retrieved by id (T2.56 c2's shape), with
specification in contracts and change narrative in the PR record. Corpus shape:
`extract_machine_semantics_only`, forward-only; no ratified body is rewritten. The decidable
rule (three ordered property tests -- checkable-without-why -> contract; this-landing/acute-state
-> PR body; why-this-choice/reversal -> entry) and three flow-side mechanisms (per-new-entry byte
cap; required Significance routing-row marker; declared subject+evaluator obligation narrowing
the drift gate's skip branch) are in the YAML with failure-mode and cost columns; each fails on
an empty repository. Per the post-run adversarial review: f2 is a recording obligation rather
than a forcing function (the author still elects the routing -- its forcing partner is f1 plus
the operator lane, with a WARN-tier consistency lint), f1 lands WARN-tier until destination
readiness completes with a split-evasion guard, and NEW entries adopt a typed YAML front-matter
envelope (number/status/date/amends/supersedes/routing row; body stays prose rationale) -- the
`extract_multiple_typed_fields` adjudication the original run skipped, which deletes CFG-06's
extractor-grammar defect class at the root (MADR ADR-0013; Structured MADR). On the corpus-shape sub-question this audit largely restates T2.56 c2 -- an ownership
finding, stated plainly. Both roadmap verdicts are `sufficient_with_specific_amendments`: T1.5
solves read cost, not authoring routing, and must not fossilize ungoverned raw_blocks as the
retrieval unit; T2.56 covers ambient-load cost but not authoring-time enforcement -- the exact
leg that eroded five interventions. The consumer inventory (74 rg hits) classifies as planning
agents, CI guards, generators, and warehouse paths; T1.5's portal scope covers the first two
IF it serves raw bodies (the marker-authorization guard needs them) -- generators retire with
the file, the warehouse path is unchanged.

## Arc C -- transition (Q8)

Eight steps, each atomic-IMPLEMENTATION-sized (freeze-compatible), full columns in the YAML:
(1) land the in-flight bridge raise -- headroom first; (2) flow-side pair f1+f2 (cap + required
routing marker) -- before anything else mints entries; (3) destination readiness (declared
subject/evaluator, .md gap CFG-11); (4) point the authoring surfaces at the new homes; (5)
rec-3012 index skeletonization -- makes archival relieve headers AND index; (6) the deferred
operator archival wave; (7) rec-2822+rec-2823 migrate-then-archive for the D37 class; (8) T2.56
ambient shrink, then T1.5 portal cutover last, retiring the ceilings per T2.56 c2. Ordering
rationale: DD-C shows misroutes cannot be undone later, so authoring gates precede outflow;
archival only becomes double-relief after step 5. The sequence adds at most two new corpus
entries (steps 2 and 3's rulings).

## What this audit did not file

Fifteen candidates were rejected with named owners or refutations -- among them: the index
archive-row weight (rec-3012 is sufficient), the binding-order staleness (rec-2968, its predicted
instance already resolved by D166 p9), the separator flip (rec-2991), the stale ~12,103 citation
figure (drift is in the conservative direction), "compaction unused" (its eligible population is
fully processed -- scarcity, not disuse), and the bridge plan's scout override (one recorded,
adjudicated override is the control working). The five prior audits' mechanisms survive; the
sixth audit's conclusion is that the next intervention must be the first one that governs flow
rather than stock -- and that it should cost the corpus almost nothing to record.

## Post-run amendment (2026-08-07, operator-directed adversarial review)

An independent adversarial review (industry AI-first-ADR lens) re-derived every load-bearing
number exactly and returned STAND WITH AMENDMENTS: all 11 findings, 15 rejections, and Q1-Q8
verdicts unchanged; the corrections are to this audit's own judgment calls, applied in place.
(1) EX7 partial -> **missed** (the corpus is measured monotonic and the only nameable
compensating control is the one CFG-01 rules property-mismatched) and EX4 met -> partial
(internal consistency with CFG-03); the single missed forecloses frontier repo-wide, so **S2 and
S5 drop to strong** -- tally now 3 met / 9 partial / 1 missed. (2) f2 reclassified: a recorded
routing claim is an audit trail, not a forcing function; a WARN-tier consistency lint closes the
residue. (3) f1 sequenced WARN-tier until destination readiness lands, with a same-PR
multi-entry split-evasion guard (two capped entries burn headers, the first-binding ceiling).
(4) Q7 now adjudicates the typed-entry option it had skipped: NEW entries adopt a YAML
front-matter metadata envelope, priced against the T1.5 sunset. (5) Step 8 gains a
retrieval-quality acceptance gate (re-run the Decision 160 point-14 probe protocol against the
portal) -- content parity tests recoverability, not findability. (6) Inflow rates are qualified
as cadence-window upper bounds; E2 shares carry an explicit +/-10-point tolerance.
