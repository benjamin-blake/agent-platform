# AUDIT: Audit-Target Discovery -- what should we review deeply next?

You are a frontier-capability model executing a self-contained, read-only reconnaissance in a
fresh session. You cannot ask clarifying questions -- everything you need is in this file and in
the repository at HEAD. Execute it exactly as written.

This is a META-AUDIT. Its product is a ranked slate of AUDIT CANDIDATES -- recommendations for
what the next deep audit should examine, each with a grounded rationale and a priority rank. You
are NOT auditing any system for defects here; you are deciding WHICH systems, roadmap sections,
decision premises, or framelocked choices are worth the cost of a future deep audit, and arguing
why. Read Section 2 before anything else: the discipline that separates a valuable slate from a
generic wish-list is the whole game.

## 1. TASK

Survey the repository at HEAD and produce a ranked slate of audit candidates across four
categories:

- CAT-A -- a repository AREA (a code / config / infra / docs subsystem).
- CAT-B -- a platform-ROADMAP construct (a `candidate_decisions` entry or cluster, an
  `open_questions` item, a `known_gaps` item, or a `tier_items` group) in
  `docs/ROADMAP-PLATFORM.yaml`.
- CAT-C -- a DECISION PREMISE (the "because X" grounding of a `docs/DECISIONS.md` entry that may
  no longer hold).
- CAT-D -- a FRAMELOCKED CHOICE (a choice pinned to an unexamined frame, per the Decision-75
  anti-pattern, whose framing conditions may have shifted).

For every candidate that clears the audit-worthiness bar (Section 6 NORTH STAR), emit one
`findings[]` entry (schema in Section 14) carrying: the specific grounded trigger with a
`file:line` or item-id anchor; a "why now" rationale; a 3-6 line sketch of what the resulting
deep audit would investigate (this seeds a future `/audit` invocation); the payoff (what decision
or roadmap direction it could change); and a `review_priority` rank. Then answer six questions
(Section 7), rate the four categories on five dimensions (Section 8), and assemble one
cross-category ranked `audit_slate` (Section 14).

Deliverables: exactly two files --
- `audits/audit-scope-discovery-<sha>.yaml` (the structured slate), and
- `audits/audit-scope-discovery-<sha>.md` (a companion report, prose, <= 1500 words, the
  executive layer a human reads first).

`<sha>` is the short SHA of the audited commit (Section 16). You DRAFT; the human DISPOSES -- you
open a PR and stop. You do not merge, you file no recommendations or decisions, and you edit no
roadmap, decision, or code file. The ONLY files you create or modify in the repository tree are
those two deliverables. Regenerating gitignored local caches per Section 5 is expected and does
not breach this boundary (never commit them).

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE audit-targets. It hands you NO verdicts. Every candidate
observation in Section 10.1 is a neutrally-phrased hypothesis you must trace to the repository and
adjudicate -- never a target you may assume is worth auditing.

ASSUME NO CANDIDATE IS WORTH AUDITING UNTIL YOU GROUND IT. A run that merely confirms the
candidates below has failed. A run that returns a generic hygiene list -- "review your tests",
"review your security posture", "review the docs" -- has failed twice over: such a candidate names
no specific trigger, and is the single most common failure mode of this task. Every surviving
candidate must name a concrete, traced trigger (a `file:line`, an item-id, an internal
contradiction, a demonstrably-shifted premise), not a category of hygiene.

Per-candidate adjudication -- map each to exactly one outcome:

- Clears the bar AND its territory is genuinely un-owned -> `findings[]`, `dedup.classification:
  unowned`.
- Clears the bar BUT part of its territory is already owned by an open tier_item / open rec /
  recent audit, and you can point to the specific UN-examined sub-area that survives that overlap
  -> `findings[]`, `dedup.classification: partially-owned` (state the surviving sub-area in
  `dedup.note`).
- Real territory but substantially covered by a recent or in-flight audit, or by an open owning
  item, with no surviving un-examined sub-area -> `rejected_candidates[]`, `classification:
  recently-covered` or `owned`, naming the covering audit/item.
- Generic hygiene with no specific trigger, or a target whose examination would not change any
  decision -> `rejected_candidates[]`, `classification: no-specific-trigger` or `low-leverage`.

You are expected to reject candidates -- a candidate dismissed with a named covering audit or a
"no specific trigger" verdict is a successful adjudication, not a failure. Equally, you are
expected to surface candidates NOT in Section 10.1: the seed list is a floor on your attention,
not a ceiling. The single most valuable output is a candidate no one told you to look for, traced
to a concrete trigger, in a category (especially CAT-C decision premises and CAT-D framelocks)
that the existing audits do not cover.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

Internalise these before reading anything else; each will misdirect you if you do not.

- TRAP-1 (two numbering systems). `candidate_decisions` are `CD.N` (e.g. CD.7), living in
  `docs/ROADMAP-PLATFORM.yaml`. `Decisions` are `Decision N` / `dec-NNN` (e.g. Decision 75),
  living in `docs/DECISIONS.md`. A `CD.N` in `state: pending` is NOT a ratified `Decision`; a
  ratified `CD.N` carries `ratified_as: dec-NNN`. Never conflate the two. CAT-B concerns `CD.N`
  and other roadmap constructs; CAT-C concerns `Decision N` premises.
- TRAP-2 (two roadmaps). `docs/ROADMAP-PLATFORM.yaml` (tier_items, infra, governance) is IN
  SCOPE. `docs/ROADMAP-PRODUCT.yaml` (trading phases, market features) is CONTEXT-ONLY: do not
  mine it for candidates unless you trace a specific, grounded premise tension into it, and if you
  do, say why in the finding.
- TRAP-3 (framelock vs "decided"). A framelock (Decision 75) is a choice pinned to an UNEXAMINED
  frame -- an assumption that was never surfaced, such that alternatives outside the frame were
  never considered. It is NOT the same as "this was decided." Most decided choices are not
  framelocks. To classify a candidate CAT-D you must name the specific unexamined frame and the
  out-of-frame alternative that a reframing would surface. Apply the Decision-75 definition
  (Section 10 anchor); do not label every decision a framelock.
- TRAP-4 (candidates, not audits). Your output is AUDIT CANDIDATES -- ranked recommendations to
  audit, each with rationale. It is NOT the audits themselves and NOT code-level defect findings.
  Do not open `src/execution/async_engine.py` and start hunting bugs; decide instead WHETHER
  `src/execution/` deserves a deep audit, and argue why with a traced trigger. Depth of tracing is
  in service of the adjudication, not a substitute audit.
- TRAP-5 ("pending" is overloaded). A `CD.N` in `state: pending` can mean "realized in code but
  not yet formally ratified through the ratification lane" (Decision 105), NOT "undecided". Check
  each CD's `detail` and `realization_evidence` fields before treating `pending` as an open
  question. Separately, some `pending` CDs are effectively superseded (their `detail` says so) yet
  are not marked `state: superseded` (see CO-1). Trace each before you classify it.

## 4. SCOPE

Surfaces (all at HEAD; obtain every file/line/count by reading the file -- trust no number quoted
in this prompt; re-derive from the repo and record any non-resolving anchor in
`meta.stale_anchors`):

- `docs/ROADMAP-PLATFORM.yaml` -- the platform roadmap: `tier_items`, `candidate_decisions`,
  `open_questions`, `known_gaps`, `cross_tier_gates`, `north_star`. IN SCOPE (CAT-B).
- `docs/DECISIONS.md` -- open/recent decisions; `docs/DECISIONS_ARCHIVE.md` -- archived resolved
  decisions. IN SCOPE (CAT-C, CAT-D).
- `src/` (subsystems: `common`, `data`, `execution`, `lab`, `lambdas`, `live`, `meta_learner`,
  `schemas`), `scripts/`, `config/`, `terraform/`, `tests/`, `docs/`, `.claude/` -- IN SCOPE
  (CAT-A). You may treat any of these as an area candidate.
- `logs/.recommendations-log.jsonl` -- the open-rec backlog; a read cache (Section 5), usable for
  dedup and as a signal source, never a write target.
- `audits/` and `docs/audit-prompts/` -- the record of what has already been / is being audited;
  central to dedup (Section 13).

Out of scope (one line each): running or modifying any audited system; filing recommendations or
decisions; editing the roadmap or any decision; performing the deep audits you recommend;
`docs/ROADMAP-PRODUCT.yaml` beyond TRAP-2's narrow exception.

Vocabulary: a "candidate" is a proposed audit target. A candidate "clears the bar" when it
satisfies the NORTH STAR test (Section 6). "Owned" means an open tier_item, open recommendation,
or recent/in-flight audit already covers the territory. "Recently-covered" means a completed or
in-flight audit (Section 10 lists them) substantially examined it. `review_priority` is the rank
driver (Section 15).

## 5. SETUP

Permitted setup (read-only; run once at the start):

```
git fetch origin main
git rev-parse --short origin/main          # this is <sha>; use it everywhere (Section 16)
bin/venv-python -m scripts.session_preflight --roadmap-detail full
```

The preflight populates `logs/.preflight-report.json` and refreshes the read caches
`logs/.recommendations-log.jsonl` and `logs/.decisions-index.jsonl`, which DEDUP DISCIPLINE
(Section 13) depends on.

Degraded paths -- never abort; set the named flag, downgrade affected confidences, proceed:

- IF cache-gen fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`, mark
  every finding's `dedup.hit_count=null` and its `confidence=HYPOTHESIS`, and dedup against the
  on-disk `audits/`, `docs/audit-prompts/`, `docs/ROADMAP-PLATFORM.yaml`, and `docs/DECISIONS.md`
  by direct read + `rg` instead. Proceed.
- IF an anchor in this prompt does not resolve (line moved, id renamed): re-derive it from the
  repo yourself; record the mismatch in `meta.stale_anchors`; do not treat the prompt's number as
  ground truth.
- IF `git rev-parse origin/main` and your working tree differ (the tree drifted after this prompt
  was drafted): audit the tree you have, set `meta.audited_commit` to the actual working-tree
  base, and note any cited file where `origin/main` has since diverged in `meta.contract_notes`.

Repo-wide `validate.py` is advisory outside CI here: a clean YAML parse of your two deliverables
is the real pre-push gate. An unrelated `validate --pre` failure is recorded in
`meta.contract_notes`, never fixed (write boundary).

## 6. NORTH STAR

The bar a candidate must clear to enter `findings[]`. These are judgment tests you apply to each
candidate, not checkboxes -- argue each.

- NS-A (Specific trigger, not hygiene). There is a concrete, traced signal -- a `file:line`, an
  item-id, an internal contradiction, a demonstrably-shifted premise -- that makes THIS target
  worth THIS cost NOW. "It would be good to review X" is not a trigger. This is a bar you judge
  each candidate against, and it is the one most candidates fail.
- NS-B (Leverage). The likely output of a deep audit here would change something a human acts on:
  a decision, a roadmap sequencing, a build-or-defer call, a resource allocation. An audit whose
  best-case output changes nothing is low-leverage regardless of how real the trigger is.
- NS-C (Not already answered). The territory is not substantially covered by a recent or in-flight
  audit (Section 10.2) or fully owned by an open tier_item / rec whose exit criteria would resolve
  it. Partial overlap is allowed only when you name the surviving un-examined sub-area.
- NS-D (Tractable). The candidate is scoped tightly enough that one deep audit session could
  deliver a verdict. "Audit the whole platform" is not tractable; "audit whether the pending-CD
  ratification lane leaves realized-but-unratified premises un-reviewed" is.

A candidate that clears all four is a finding. A candidate that fails NS-A or NS-B is a
`rejected_candidate`. A candidate that fails NS-C is `recently-covered` / `owned`. A candidate
that fails only NS-D should be RESCOPED to the tractable core before you reject it -- a real
trigger inside an over-broad target is a finding once you narrow it.

## 7. THE QUESTIONS

Answer each in `question_answers[]` (Section 14). Q1-Q4 each carry the pinned verdict enum
`high-yield | moderate-yield | low-yield | already-covered` -- a portfolio judgment of how much
audit-worthy material that category surfaced after adjudication. Each answer's `basis` lists the
finding ids it rests on.

- Q1 (CAT-A). Which repository areas carry specific, accumulated tension that a deep audit would
  resolve -- and which are stable enough that auditing them would waste the expensive model?
- Q2 (CAT-B). Which platform-roadmap constructs (`candidate_decisions`, `open_questions`,
  `known_gaps`, tier clusters) hold premises or unresolved tensions worth deep re-examination given
  what has shipped since they were authored?
- Q3 (CAT-C). Which decision entries rest on a premise that has demonstrably shifted -- where the
  "because X" that grounded the decision no longer holds -- INDEPENDENT of the decision's `Decided`
  status? (Decided status alone does not immunize a premise; see Section 13's do-not-flag rule.)
- Q4 (CAT-D). Which choices fit the Decision-75 frame-lock pattern and are ripe to revisit --
  pinned to an unexamined frame whose conditions have changed, or where an outsider reframing would
  plausibly collapse or invert the choice? Name the frame and the out-of-frame alternative for each.
- Q5 (Ranking + top scope). Of all candidates that clear the bar, what is the ranked slate
  (1..N)? For the top 3, what would each resulting deep audit actually investigate? Q5's answer
  POINTS TO the `audit_slate` block (Section 14); its `prose` summarises the ranking logic, and
  its `verdict` is the literal string `slate-produced`.
- Q6 (Not-asked). Questions the requester did not think to ask. Seeded below; you must answer AND
  extend them. Use the `answers[]` shape (Section 14), not the verdict shape.
  - Seed a: Is the ratio of open recs (Section 10 quotes ~685, 400 from code-review) to closed
    work itself a signal that one of the finding-producing surfaces is mis-calibrated -- and is
    that a candidate?
  - Seed b: Is there a maturity gap between the platform surface (heavily roadmapped/audited) and
    the trading-product `src/` (live, meta_learner, execution, lab), and does that gap warrant an
    area candidate?
  - Seed c: Which single CAT-C or CAT-D candidate, if its premise turned out to be wrong, would
    invalidate the most currently-active work -- and is that the highest-leverage audit on the
    slate?

## 8. RUBRIC

Rate each of the four categories (CAT-A, CAT-B, CAT-C, CAT-D) on five dimensions, in
`rubric_ratings[]`. Pinned enum: `strong | adequate | weak | absent | n/a`. `n/a` is correct and
costless where a dimension does not structurally apply -- never manufacture a rating to fill a
cell. Each rating carries `evidence` (a finding id, `file:line`, or item-id) and a one-line
`note`. The rating expresses how the category scored on that dimension AS A WHOLE (the portfolio
view); per-candidate detail lives in the findings.

- VD1 Trigger specificity -- do this category's candidates rest on concrete, traced triggers
  rather than generic hygiene?
- VD2 Leverage -- would audits in this category likely change active decisions or roadmap
  direction?
- VD3 Drift exposure -- how much has the ground shifted under this category since its items were
  last examined or decided?
- VD4 Coverage gap -- how much of this category is genuinely NOT already owned by open work or
  recent/in-flight audits?
- VD5 Audit tractability -- can candidates here be scoped tightly enough for a single deep audit
  session to deliver a verdict?

Every question is served by at least one dimension (Q1-Q4 by VD1/VD3/VD4; the ranking in Q5 by
VD2/VD5); every dimension is referenced by at least one question. VD2 is the primary rank driver
in Section 15.

## 9. DEEP-DIVES

Two threads need end-to-end tracing before they can be adjudicated; treat each as a mandatory
trace feeding the named questions. Findings may still arise outside them.

- DD-A (Pending-CD premise integrity) -- feeds Q2, Q3. For the `candidate_decisions` in
  `state: pending`, walk each entry's `title`, `detail`, and `realization_evidence`. Distinguish
  three sub-states: (i) realized-in-code-but-unratified (a governance-lag signal), (ii)
  effectively-superseded-but-not-marked (a data-integrity signal; CO-1 names CD.7 and CD.11 as
  seeds -- verify and look for others), and (iii) genuinely-open (a real decision still owed).
  The audit candidate is NOT "ratify the CDs" (that is mechanical, and the loop-closure of
  governance state is already owned -- see Section 10.2 unclosed-loops); the candidate you are
  testing is whether the PREMISES inside the pending CDs have gone stale un-reviewed, which no
  existing audit covers. Adjudicate whether that is audit-worthy (NS-A..D) or already-owned.
- DD-B (Framelock detector gap) -- feeds Q4. Decision 75 names the frame-lock anti-pattern and
  states that plan-critique "does not challenge the frame itself... That gap is the institutional
  control that needs to exist" (Section 10 anchor). Trace: (i) does any built control now detect
  framelocks (search `.claude/skills/plan-critique/`, `scripts/`, `validate.py`)? (ii) if not,
  which currently-active choices are candidate framelocks that no control would catch? Produce
  CAT-D candidates only where you can name the unexamined frame and the out-of-frame alternative
  (TRAP-3). The candidate may be either a specific framelocked choice OR the missing-detector
  itself -- adjudicate both framings.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every anchor was read from disk at compose
time; re-verify each before you rely on it, and record any that does not resolve in
`meta.stale_anchors`. Facts are stated neutrally and carry no verdict.

### 10.1 Candidate observations (neutral seeds -- a floor, not a ceiling)

- CO-1 -- In `docs/ROADMAP-PLATFORM.yaml`, of ~40 `candidate_decisions`, ~23 are `state: pending`.
  CD.7 (title "LLM inference stays on Bedrock...") and CD.11 (title "Fargate-based executor...")
  each carry `detail` text beginning "[Amendment ... superseded by CD.28]" / "[Amendment ...
  superseded by CD.27]" yet remain `state: pending`; CD.14 by contrast is `state: superseded`.
  (Category signal for CAT-B / CAT-C; DD-A.)
- CO-2 -- `docs/DECISIONS.md` Decision 75 (Frame-Lock Anti-Pattern) documents the pattern and
  states plan-critique "does not challenge the frame itself... That gap is the institutional
  control that needs to exist." (CAT-D; DD-B.)
- CO-3 -- In `docs/ROADMAP-PLATFORM.yaml`, several `open_questions` remain unresolved (e.g. OQ.3,
  OQ.5, OQ.6, OQ.14) and several `known_gaps` are open with no remediation surface (e.g. KG.2
  rec-backlog-not-mapped-to-tiers; KG.3 provider-agnostic-executor INTENT not deeply consumed; KG.9
  CC-web deprecation contingency; KG.13 Test-Impact-Analysis deferred; KG.14 multi-product
  enforcement substrate unbuilt). (CAT-B.)
- CO-4 -- `logs/.recommendations-log.jsonl` holds on the order of 685 open recommendations, ~400
  with `source: code-review` and ~25 at `priority: Critical`; KG.2 records that the backlog is not
  mapped to tier_items (snapshot noted ~250, now larger). (CAT-A / Q6 seed a.)
- CO-5 -- `src/` contains trading-product subsystems (`live`, `meta_learner`, `execution`, `lab`,
  `data`) that the platform roadmap (infra/governance-oriented) does not directly govern; their
  examination cadence relative to the heavily-roadmapped platform surface is unverified. (CAT-A /
  Q6 seed b.)
- CO-6 -- `docs/DECISIONS.md` retains pre-CD-era decisions (e.g. Decision 24, 35, 37, 39, 40, 41,
  44, 48, 49) that predate the current architecture; some name substrates later changed (Decision
  37 references GitHub Models API; Decision 40 references Copilot SDK + Bedrock planning). (CAT-C.)
- CO-7 -- The `audits/unclosed-loops-<sha>.yaml` audit already covers the MECHANICAL loop-closure
  of governance state (dormant transitions, pending CDs whose gated work is realized, retired-
  substrate residue); it did not adjudicate the PREMISE VALIDITY of individual decisions. (Dedup
  boundary for CAT-B / CAT-C.)

### 10.2 Prior and in-flight audits (the dedup frontier -- Section 13)

Completed audit outputs live in `audits/` (re-derive exact filenames/shas by listing the dir):
- `unclosed-loops-<sha>` -- unclosed governance/automation loops, dormant-transition mechanics,
  retired-substrate residue (~13 findings). See CO-7 for the boundary it leaves open.
- `verification-system-review-<sha>` -- the verification system across `interactive` and
  `aws-executor` surfaces; vacuous-path exposure (~14 findings).
- `workflow-review-<sha>` -- the workflow / skill / command layer; DRY and layer violations,
  context-budget reduction (~20 findings).

Audit PROMPTS staged/in-flight in `docs/audit-prompts/` (their audits are being executed NOW --
treat their territory as actively-covered, not merely queued):
- `AUDIT-executor-roadmap-review.md` -- the PLANNED T4 autonomous-executor design (Step Functions
  + Lambda Durable Functions substrate).
- `AUDIT-platform-roadmap-mvp-triage.md` -- scope-triage / MVP-disposition of the ACTIVE
  (`not_started` / `in_progress`) tier_items.

### 10.3 Structural anchors (re-derive; do not trust the numbers)

- `docs/ROADMAP-PLATFORM.yaml` top-level keys: `north_star`, `candidate_decisions` (~40),
  `tier_items` (~132), `open_questions` (~15), `known_gaps` (~14), `cross_tier_gates` (~4).
- `docs/DECISIONS.md` -- ~81 `## Decision N` headers (open + recent); resolved ones archived in
  `docs/DECISIONS_ARCHIVE.md`. Decision 75 (Frame-Lock) is the CAT-D reference definition.
- `docs/` holds ~12 `INTENT-*.md` docs mid-retirement under T5.5 / Decision 86, mechanised by
  `docs/intent-migration/MANIFEST.yaml` (OWNED -- do not recommend auditing INTENT-doc retirement).
- Ratification lane for `candidate_decisions`: Decision 105 (shared /orient -> /plan -> /implement
  mechanism; canonical ratified-CD shape).

## 11. EMPIRICAL PASS

Two sampled classes exist; apply hard bounds and the counterfactual test; tag each derived finding
`trigger_kind: observed` (a traced artifact) vs `static` (structure alone). Observed triggers
outrank static ones at equal `review_priority`.

- Decisions sample: read AT MOST 15 decision entries in full (do NOT exceed) -- choose a spread
  across pre-CD-era (CO-6) and recent, biasing toward those whose premise names an external
  condition (a provider, a cost figure, a tool, a capacity assumption) that could have moved. For
  each, apply the counterfactual: "if I deleted the sentence stating this premise, would the
  decision still follow?" A premise whose truth has visibly changed is an `observed` CAT-C trigger.
- Pending-CD sample: cover ALL `state: pending` CDs at the title/detail level (this set is small,
  ~23) but read `realization_evidence` in full for AT MOST 10 (do NOT exceed) -- prioritise those
  whose `detail` mentions supersession or amendment.

Do not sample the open-rec backlog line-by-line; use the aggregate counts (CO-4) and targeted `rg`
for dedup only.

## 12. METHOD

Phases, in order; synthesis and ranking always LAST:

- P1 Read -- Section 5 setup; read the four scope surfaces; list the prior/in-flight audits
  (Section 10.2) and note each one's territory.
- P2 Enumerate -- build the raw candidate set: Section 10.1 seeds PLUS your own, one pass per
  category (CAT-A..D).
- P3 Trace -- for each raw candidate, find and record the concrete trigger (`file:line` / item-id).
  Run DD-A and DD-B. Discard any candidate for which no specific trigger survives tracing.
- P4 Empirical -- run Section 11 within the caps; tag observed vs static.
- P5 Adjudicate -- apply NORTH STAR (Section 6): finding (unowned / partially-owned),
  recently-covered, owned, or rejected. Rescope over-broad candidates before rejecting on NS-D.
- P6 Dedup -- Section 13 for every surviving finding; a hit downgrades to partially-owned /
  recently-covered / owned unless a specific un-examined sub-area survives.
- P7 Rate -- fill the RUBRIC (Section 8); answer Q1-Q4, Q6.
- P8 Synthesise + rank -- compute `review_priority` per finding (Section 15), assemble the
  cross-category `audit_slate` (rank 1..N), answer Q5, write the companion report, compute
  per-category maturity LAST.

## 13. DEDUP DISCIPLINE

Before a candidate becomes a finding, prove its territory is not already owned:

1. Search the ownership surfaces and RECORD the search terms + hit count on the finding
   (`dedup.search_terms`, `dedup.hit_count`):
   - `audits/*.yaml` and `docs/audit-prompts/*.md` (prior + in-flight audits -- Section 10.2).
   - `docs/ROADMAP-PLATFORM.yaml` `tier_items` (`rg` the candidate's subject; an owning item with
     live `exit_criteria` means owned).
   - `logs/.recommendations-log.jsonl` open recs (`rg` the subject; an open rec on the same
     territory means owned or partially-owned).
2. A hit means the finding is `partially-owned` (name the surviving un-examined sub-area in
   `dedup.note`), `recently-covered`, or `owned` -- NEVER a fresh `unowned` discovery. A finding
   with `dedup.hit_count > 0` and `classification: unowned` is a contradiction; fix it.
3. A finding with no recorded negative search is a HYPOTHESIS (`confidence: HYPOTHESIS`), not a
   confirmed candidate.

Deliberate constraints -- DO NOT recommend auditing these (each is covered, settled, or explicitly
trigger-gated). If a candidate lands here, it belongs in `rejected_candidates` with the id below:

- The T4 autonomous-executor DESIGN (substrate / closed-loop capabilities) -- in-flight audit
  `AUDIT-executor-roadmap-review.md`.
- Active-tier MVP scope-triage / disposition -- in-flight audit `AUDIT-platform-roadmap-mvp-triage.md`.
- The verification system (interactive + aws-executor verifiers) -- `verification-system-review`.
- The workflow / skill / command layer's DRY + layering + context budget -- `workflow-review`.
- Dormant governance loops / realized-but-pending-CD ratification MECHANICS / retired-substrate
  residue -- `unclosed-loops` (the PREMISE-validity angle, CO-7, is NOT covered and may be a finding).
- The executor freeze itself (Decision 67 / CD.17) -- reversal is explicitly trigger-gated, not a
  framelock.
- INTENT-doc retirement -- owned by T5.5 / Decision 86.
- The top-line CHOICE of these recently-ratified, actively-building commitments: DuckLake as sole
  ops backend (Decision 84), the two-axis environment/phase taxonomy (Decision 77), the public-repo
  boundary (Decision 101). You MAY still file a CAT-C/CAT-D candidate on a SPECIFIC, grounded,
  stale SUB-premise of one of these, but not a candidate that re-opens the top-line decision.

Immunity rule (protects the requester's actual ask): a decision's `Decided` status ALONE does NOT
immunize its premise from Q3/Q4 scrutiny. Only three things immunize a target: (a) recent
ratification PLUS active build, (b) coverage by a recent/in-flight audit above, or (c) explicit
trigger-gating. Absent those, a `Decided` decision with a demonstrably-shifted premise is a valid
CAT-C candidate.

## 14. OUTPUT

Write both deliverables. The YAML conforms to this contract exactly; pin every enum inline as
shown. Prose caps: companion report <= 1500 words.

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>, methodology_version: 1,
         scope_categories: [CAT-A, CAT-B, CAT-C, CAT-D],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: high-yield|moderate-yield|low-yield|already-covered,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: ..., basis: [...], prose: ""}
    - {q: Q3, verdict: ..., basis: [...], prose: ""}
    - {q: Q4, verdict: ..., basis: [...], prose: ""}
    - {q: Q5, verdict: slate-produced, basis: [<all slate finding ids>], prose: ""}   # points to audit_slate
    - {q: Q6, answers: [{question: "", answer: "", basis: [<finding ids>]}]}          # seeds a-c + your own
  category_assessment:
    - {category: CAT-A, maturity: <derived, Section 15>, audit_density: "", top_candidates: [<finding ids>]}
    # one entry per category CAT-A..CAT-D
  rubric_ratings:
    - {category: CAT-A, dimension: VD1..VD5, rating: strong|adequate|weak|absent|n/a,
       evidence: "finding-id|file:line|item-id", note: ""}
    # one row per (category x dimension) you choose to rate; n/a rows allowed and costless
  audit_slate:                      # THE ranked deliverable Q5 points to; cross-category total order
    - {rank: 1, finding: CAND-01, category: CAT-x, one_line_scope: "",
       review_priority: critical|high|medium|low}
    # rank is a strict 1..N total order over EVERY finding; ties broken by observed>static then leverage
  findings:
    - {id: CAND-01, category: CAT-A|CAT-B|CAT-C|CAT-D,
       target: "<the specific thing to audit: a path, an item-id, a Decision N, a CD.N>",
       title: "<what to audit, one line>",
       trigger: "<the specific grounded signal>", trigger_anchor: "file:line|item-id",
       trigger_kind: static|observed,
       why_now: "<the rationale: what changed / what tension accumulated>",
       what_a_deep_audit_would_examine: "<3-6 line scope sketch; seeds a future /audit>",
       payoff: "<what decision/direction a deep audit could change>",
       review_priority: critical|high|medium|low, priority_rationale: "",
       confidence: CONFIRMED|HYPOTHESIS,
       dedup: {classification: unowned|partially-owned|recently-covered|owned,
               owning_ids: [], search_terms: [], hit_count: 0, note: ""},
       audit_size_estimate: XS|S|M|L, depends_on: [<finding ids>]}
  rejected_candidates:
    - {candidate: "", classification: recently-covered|owned|no-specific-trigger|low-leverage,
       why_dismissed: "", covering_audit_or_item: ""}
  summary: {total_findings: 0, by_category: {CAT-A: 0, CAT-B: 0, CAT-C: 0, CAT-D: 0},
            by_classification: {unowned: 0, partially-owned: 0},
            top_audit: <finding id at rank 1>, top_three: [<finding ids>],
            highest_leverage_candidate: <finding id>,
            maturity_CAT-A: <value>, maturity_CAT-B: <value>,
            maturity_CAT-C: <value>, maturity_CAT-D: <value>}
```

Invariants (state them as satisfied in `meta.contract_notes` if you deviate, with the reason):

- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
  by_classification.unowned + by_classification.partially-owned`. `recently-covered` and `owned`
  candidates live in `rejected_candidates`, NOT findings. `audit_slate`, `rubric_ratings`, and
  `question_answers` are systems-of-record that REFERENCE finding ids, never re-counted.
  `audit_slate` must contain exactly one row per finding (a strict 1..N total order);
  `top_audit`, `top_three`, and `highest_leverage_candidate` MUST be finding ids.
- CONFIRMED requires the trigger traced to a resolving `file:line` or an observed sampled artifact;
  anything less is HYPOTHESIS. A finding with no recorded dedup negative-search is HYPOTHESIS.
- Every `dedup.classification: partially-owned` finding MUST name the surviving un-examined
  sub-area in `dedup.note`; every `recently-covered` / `owned` rejection MUST name the covering
  audit or item.

## 15. REVIEW-PRIORITY + MATURITY

`review_priority` is assigned AFTER adjudication, by leverage-and-reversibility class, never
inherited from this prompt's framing:

- critical = if this target's premise is wrong or its gap real, currently-active work is being
  mis-directed right now (an audit here could change what is being built this quarter).
- high = a real, grounded trigger whose deep audit would likely change a decision or roadmap
  sequencing, but not mid-flight work.
- medium = a real trigger worth an audit, but the payoff is contained or speculative.
- low = a clarity/consistency target; worth noting, low urgency.

Rank driver: `audit_slate` orders findings by `review_priority` first, then by VD2 leverage, then
`observed` above `static` at equal leverage. The `highest_leverage_candidate` in the summary is the
finding whose deep audit would change the MOST currently-active work (Q6 seed c), which need not be
rank 1 if rank 1 is critical-but-narrow.

Maturity -- compute LAST, per category, top-down, first match wins. This measures how well the
EXISTING governance already tends each category's audit space (higher = less need for new audits
here):

- well-tended = 0 findings in this category clear the `critical` or `high` bar (existing audits /
  roadmap already cover it).
- tended = 0 critical AND <= 1 high finding in this category.
- thin = exactly 1 critical, OR 2-3 high.
- neglected = otherwise (multiple critical, or a critical plus several high) -- this category is
  materially under-examined.

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This sha
   IS the audited tree; use it in `meta.audited_commit`, both deliverable filenames, and the branch
   name.
2. `git switch -c audit/audit-scope-discovery-<sha> origin/main` so the PR diff is exactly your two
   deliverable files. (This is a deliberate, documented exception to the AGENTS.md `claude/*`
   session-branch rule: the audit session needs a clean two-file diff off the audited base. The
   CI signal-green-comment wake fires only on `claude/*` PRs and is irrelevant here -- you end your
   turn without merging; the human disposes of the PR.)
3. Validate: a clean YAML parse of `audits/audit-scope-discovery-<sha>.yaml` is the real pre-push
   gate (e.g. `bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"
   audits/audit-scope-discovery-<sha>.yaml`). Repo-wide `validate --pre` is advisory outside CI;
   an unrelated failure goes in `meta.contract_notes`, never fixed.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing
   is unavailable. `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title
   `audit: audit-target discovery -- ranked slate of what to review next (CAT-A..D)`, body = the
   `summary` block in a yaml fence + a 2-3 sentence lede). Then END THE TURN -- do not poll, do not
   merge, do not subscribe.

## 17. GUARDRAILS

- Write boundary (closed list): the ONLY files you create or modify in the repository tree are
  `audits/audit-scope-discovery-<sha>.yaml` and `audits/audit-scope-discovery-<sha>.md`. No roadmap
  edit, no decision edit, no code edit, no recommendation, no decision, no merge, no self-approval.
  Regenerating gitignored local caches per Section 5 is expected and does not breach this.
- Precision over volume. Fewer than ~8 surviving candidates is a valid and expected result -- state
  it plainly; do not pad. A slate of 30 generic candidates is a failed audit; a slate of 5 sharply
  triggered ones is a success.
- A generic-hygiene candidate ("review tests / docs / security / performance") with no specific
  traced trigger is a FAILED candidate -- reject it as `no-specific-trigger`, do not launder it
  into a finding.
- You are the judge of audit-worthiness, not a list generator. Every finding must survive NS-A..D
  and the dedup discipline. When you are unsure whether a candidate clears the bar, put it in
  `rejected_candidates` with your reasoning rather than inflate the slate.
