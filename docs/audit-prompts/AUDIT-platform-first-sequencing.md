# AUDIT: Platform-First Sequencing Frame

You are a frontier-grade reviewer running a single, self-contained audit in a fresh session.
This file is your complete brief. Do NOT ask clarifying questions -- every term, path, enum, and
degraded path you need is pinned below. Execute it verbatim.

## 1. TASK

Audit the **platform-first sequencing frame**: the operating directive that all of one
developer-agent's build capacity goes to closing the platform's autonomous loop **before** any
trading-product-plane work begins. The platform roadmap is active; the product roadmap
(`docs/ROADMAP-PRODUCT.yaml`) is dormant (`status: draft`).

This is a **premise / governance audit, not a code audit**. You will read decision records,
roadmap artifacts, framing docs, and the controls that operate around them, and you will judge
whether the sequencing is a sound, conscious, reversible choice -- or an inherited premise that
should be examined and either ratified or changed.

You will answer six questions (Q1..Q6, Section 7), rate a rubric (Section 8), and adjudicate a
set of candidate observations to findings. You will produce **exactly two deliverable files**:
`audits/platform-first-sequencing-<sha>.yaml` (system of record) and
`audits/platform-first-sequencing-<sha>.md` (executive report, <= ~1500 words). The ONLY files
you create or modify in the repository tree are those two. You draft; **the human disposes** --
nothing you recommend takes effect until a human executes it.

**Framing you must hold throughout:** "unratified" is NOT a synonym for "wrong." An inherited
frame can be entirely correct. The two equally-valid classes of outcome are (a) recommend
changing the sequencing, and (b) recommend ratifying the current sequencing as a conscious,
reversal-conditioned decision. A run that arrives at (b) with rigor is exactly as successful as
one that arrives at (a). Do not let the observation "it was never ratified" pull you toward a
resequence verdict.

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you **facts** and **candidate hypotheses**. It hands you **no verdicts**. Every
observation in the GROUNDING MAP (Section 10) is stated as a neutral fact; every candidate in
Section 9 is a hypothesis you must trace and adjudicate. **ASSUME NO CANDIDATE IS A REAL DEFECT
UNTIL YOU TRACE IT.** A run that merely confirms the candidates below has failed.

Per-candidate adjudication enum, and where each outcome lands in the output:

- **CONFIRMED-gap** (the premise is genuinely unexamined/unsound in the way described, traced to
  file:line or artifact): -> `findings[]`, `roadmap_crossref.classification: novel`.
- **partially-owned** (an existing artifact touches it but its treatment is insufficient or the
  remedy is unbuilt): -> `findings[]`, classification `planned-insufficient` or
  `planned-unbuilt`, naming the owning artifact.
- **fully-covered** (an existing Decision / roadmap item / control adequately handles it): ->
  `rejected_candidates[]`, naming the compensating control and why it property-matches.
- **not-a-gap** (the frame is sound on this axis; the observation carries no defect): ->
  `rejected_candidates[]`.

Severity is assigned by you AFTER judgment (Section 15), never inherited from this prompt's
framing or ordering.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

Five hazards where a plausible misread will waste the session. Internalize before reading
anything else.

1. **Decision 93 is NOT the ratifying decision.** Decision 93 ("Platform-MVP boundary +
   deferred_post_mvp lifecycle status", `docs/DECISIONS.md:1286`) defines *what counts as
   platform-MVP* (the autonomous loop closing) plus a defer-by-exception rule. It merely *cites*
   the platform-first directive as a given ("per the platform-first directive",
   `docs/DECISIONS.md:1311`, `:1315`). It is **evidence the directive is unratified** (used, never
   decided), not its ratification. Do not treat Decision 93 as the conscious sequencing decision.

2. **Two distinct "MVP"s.** *Platform-MVP* (Decision 93: the loop closes with no human in the
   critical path) is different from the product *"minimum viable trading system v1"* (the pivot
   transcript's Part C; the `MVP.*` items in `docs/ROADMAP-PRODUCT.yaml`). This audit is about
   sequencing *between the two planes*, NOT about the internal definition of either MVP.

3. **The executor freeze (Decision 67 / CD.17) is NOT the sequencing frame.** The freeze is a
   trigger-gated pause on executor *operation* and STRATEGIC-plan *authoring*. It is a downstream
   mechanism, not the allocation frame. "Executor frozen" does not mean "product work frozen" --
   different cause. The adjacent mvp-triage audit established the freeze does not block platform
   *construction*. Do not conflate the two; do not reopen the freeze.

4. **plan-critique's "Frame Challenge" is a plan-time control, not a portfolio-allocation
   control.** Phase 2b (`.claude/skills/plan-critique/SKILL.md:69`) challenges a *single plan's*
   frame against *existing* Decisions / roadmap / North Star, and recommends REVISE only on a
   concrete contradiction with a recorded artifact. Consider carefully whether it can, even in
   principle, challenge the sequencing frame itself -- given that the frame is the unwritten
   baseline it checks *against*. Reach your own conclusion; do not assume either way.

5. **The pivot "transcript" is an audit-prompt file.** The pivot-era product rationale lives
   embedded in `docs/AUDIT-PROMPT-product-roadmap-yaml.md` Section 11 (referenced throughout
   `docs/ROADMAP-PRODUCT.yaml` as "PIVOT Part A..G"). Parts B/D/F are noted as "user questions
   only" (`docs/ROADMAP-PRODUCT.yaml:113`). There is no clean standalone "pivot decision" doc.
   **You must check whether Section 11 weighs platform-vs-product timing at all** -- if it does,
   that materially changes Q1's provenance answer. Do not presume the sequencing rationale is
   absent there without reading it.

## 4. SCOPE

**In scope -- surfaces (all are text/design; nothing executes):**

| Surface id | What it is | State |
|---|---|---|
| `sequencing-frame` | The governance object: is platform-before-product a conscious, reversible decision? | Built-as-text (Decisions, framing docs) |
| `product-loop-feasibility` | The dormant product plane's readiness to host an interleaved minimal loop | Designed-unbuilt (ROADMAP-PRODUCT + scaffold code) |

**Vocabulary (pinned):**
- *The frame / the sequencing frame* = strict platform-before-product sequencing of one agent's
  build capacity.
- *The alternative / interleaved minimal product loop* = an L1+L3 slice (alpha signal ->
  execution) run under **human operations** as paper/manual trading, with **no dependency on the
  frozen autonomous executor**, interleaved with continued platform work.
- *Platform-MVP boundary* (Decision 93) = one autonomous-loop iteration closes with no human in
  the critical path.
- *The planes*: **platform plane** = infra/governance/automation substrate (ROADMAP-PLATFORM);
  **product / trading plane** = the four-layer trading model (ROADMAP-PRODUCT).
- *Four layers*: L1 Alpha / L2 Portfolio-Construction / L3 Execution / L4 Operations-Telemetry.
- *frame-lock* (Decision 75) = a named architectural-planning failure mode: an inherited frame
  from an earlier era silently constrains every subsequent choice; nobody re-asks the framing
  question when the tool/context has moved.
- *defer-by-exception* (Decision 93) = MVP-critical by default; items leave scope only by
  conscious deferral; the MVP set is never enumerated.
- *reversal condition* = a stated, observable trigger under which a decision is revisited.

**Out of scope (name in one line; do not opine):**
- The trading product *architecture* itself -- the four-layer model, MVP-v1 composition (settled
  in the pivot transcript).
- The product *code surface* audited to file:line already (wave-1 code-surface audit).
- Whether the platform-MVP boundary definition (Decision 93) is right -- it stands.
- The executor freeze mechanism and its reversal gates (Decision 67 / CD.17).

**Trust-nothing clause:** obtain every file / line / size by reading the file. Trust no number
quoted here; re-derive it from the repo. Record any anchor that does not resolve (or that
`origin/main` has moved off) in `meta.stale_anchors` and proceed on the re-derived truth.

## 5. SETUP

You may run read-only commands to orient and to regenerate local caches. Permitted setup:

```
git fetch origin main
git rev-parse --short origin/main      # this sha feeds filenames, branch, meta.audited_commit
bin/venv-python -m scripts.session_preflight --roadmap-detail full   # populates local caches
```

The preflight populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`
(read-only caches; regenerating them is expected and does NOT breach the write boundary -- never
commit them).

**Degraded path (creds / egress down):** if `session_preflight` fails on credentials or network,
do NOT abort. Set `meta.degraded_dedup=true`, mark every `roadmap_crossref` confidence as
`HYPOTHESIS` and every `dedup_hit_count` as `null`, and proceed using direct `grep`/`rg` over the
in-repo files named in Section 13 (those are on-disk and need no credentials). The audit's core
judgment does not depend on warehouse reads.

## 6. NORTH STAR

The bar you judge each surface against. These are judgment-bearing principles, not mechanical
rules -- argue each surface against them; do not pattern-match.

- **NS-A (Conscious allocation):** consequential capacity-allocation choices should be *conscious
  decisions* with recorded alternatives, not premises inherited by default. (This is Decision
  75's own bar and the spirit of defer-by-exception.)
- **NS-B (Frames re-validate when premises move):** an inherited frame from a superseded era must
  be re-examined when its premises change. (Decision 75 mitigations 4-5.)
- **NS-C (Challengeable frames):** a standing control should be able to challenge the frame it
  operates within; a frame that no owned surface can question is a governance gap.
- **NS-D (Reversal triggers over silent renewal):** an opportunity-cost bet that compounds each
  period should carry an explicit reversal/review trigger, so it is re-chosen consciously rather
  than renewed by inertia.
- **NS-E (Load-bearing premises get tested):** the alpha premise (that the strategy has edge) is
  load-bearing for the whole endeavor; leaving it untested until the platform is finished is a
  risk concentration that should be a conscious, argued choice -- not a side effect of sequencing.

These are a bar you judge against, not absolutes: a surface can fall short of one and still be
the right call if you argue the tradeoff.

## 7. THE QUESTIONS

Answer each in `question_answers[]` with its pinned verdict enum, a `basis` list of finding ids,
and prose. Every question is first-class.

- **Q1 -- Provenance.** Is platform-first sequencing a ratified decision, an inherited
  (unratified) premise, or a frame-lock instance by Decision 75's structural test? Trace where
  (if anywhere) the sequencing was weighed -- including the pivot transcript Section 11 (trap 5).
  Verdict enum: `ratified | inherited-unratified | frame-locked`.
- **Q2 -- Alternative feasibility & cost.** Is the interleaved minimal manual/paper product loop
  (L1+L3 under human ops, no executor) feasible given today's scaffold state, and what would it
  cost to stand up and to run? Ground the feasibility in the actual current_state of the product
  code. Verdict enum: `feasible-low-cost | feasible-high-cost | infeasible`.
- **Q3 -- Feedback value vs delay risk.** Net, does interleaving the minimal loop now generate
  more value (real trading telemetry feeding the T2.36/T3.x chain; TCA/cost data; alpha-premise
  validation) than it costs in platform delay? Verdict enum:
  `interleave-favored | sequencing-favored | too-close-to-call`.
- **Q4 -- Reversal condition.** Is there any observable condition under which strict sequencing
  should stop, and is such a condition recorded anywhere today? Verdict enum:
  `defined | undefined-should-exist | not-needed`.
- **Q5 -- Disposition (owns the decision block).** Given Q1-Q4, what should happen to the frame?
  Verdict enum: `ratify_as_is | ratify_with_reversal_conditions | resequence_interleaved |
  insufficient_evidence`. Its prose entry points to the `sequencing_verdict.frame` block
  (Section 14). All four options are first-class; `insufficient_evidence` is a legitimate,
  non-cowardly verdict if the evidence genuinely does not discriminate.
- **Q6 -- Questions the requester did not think to ask.** Use the
  `question_answers` final-entry shape (`answers: [{question, answer, basis}]`). Seeds you MUST
  answer and then EXTEND with your own:
  - What is the actual marginal platform-delay cost of a human-run paper loop, given the executor
    is already frozen (so the agent is not currently consuming capacity on executor work)?
  - Does "zero telemetry captured" (rec-2173) mean the platform's own recursive-improvement loop
    is *also* currently starved -- i.e., is the platform bet itself iterating blind while it
    waits for synthetic loop traffic?
  - Is there a third option beyond interleave-vs-sequence (e.g., a time-boxed sequencing with a
    hard review date) that dominates both?

## 8. RUBRIC

Rate each dimension per surface in `rubric_ratings[]`. Enum: `strong | adequate | weak | absent |
n/a`. `n/a` is correct and costless where a dimension does not structurally apply to a surface --
never manufacture a rating or a finding to fill a cell. Each dimension below names its primary
surface; rate it `n/a` on the other unless you have a substantive reason to rate it.

- **VD1 Decision provenance** (S1 `sequencing-frame`): is the sequencing recorded as a conscious
  choice with alternatives? Serves Q1.
- **VD2 Reversal/review trigger** (S1): is there an observable end-condition, versus silent
  period-over-period renewal? Serves Q4.
- **VD3 Frame-challengeability** (S1): can any owned control question the frame? Serves Q1, Q6.
- **VD4 Alternative-costed** (S2 `product-loop-feasibility`): is the interleaved loop's
  feasibility and cost actually assessed anywhere, or only asserted? Serves Q2.
- **VD5 Feedback-value vs delay-risk weighed** (S2): is the telemetry / alpha-validation payoff
  weighed against the platform-delay cost? Serves Q3.

## 9. CANDIDATE OBSERVATIONS (adjudicate each; do not assume)

Each is a hypothesis. Trace it; it may confirm, split, or be rejected.

- **CAND-A (provenance):** the sequencing is an unratified inherited premise, possibly a
  frame-lock per Decision 75 -- never recorded as a conscious decision with examined
  alternatives. *Counter-check:* read the pivot transcript Section 11 for any weighing of
  platform-vs-product timing; if present, CAND-A weakens or splits.
- **CAND-B (reversal):** no reversal or review condition exists for the sequencing, so each
  period silently re-makes the opportunity-cost bet. *Counter-check:* search Decisions / roadmap
  for any time-box, review date, or trigger tied to product activation.
- **CAND-C (challengeability):** no owned surface can challenge the frame; plan-critique's Frame
  Challenge operates strictly inside it. *Counter-check:* does any workflow, scheduled agent, or
  audit cadence have the frame itself in scope?
- **CAND-D (alternative uncosted):** an interleaved minimal product loop is feasible and would
  feed real telemetry / validate alpha, and this tradeoff has never been costed. *Counter-check:*
  ground feasibility in the product current_state (some surfaces are absent, not merely
  scaffolded -- an L1+L3 paper loop may need more than the trigger implies); search for any prior
  costing.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every anchor was read from disk at compose
time; **re-verify each before relying on it** (trust-nothing clause) and record drift in
`meta.stale_anchors`. Facts are stated neutrally -- no adjective here implies a verdict.

**The frame's articulation points:**
- `docs/DECISIONS.md:1286-1323` -- Decision 93. The phrase "platform-first directive" occurs at
  `:1311` and `:1315`, each as "per the platform-first directive", parking product-facing edges
  dormant. No `## Decision` header in the file ratifies platform-vs-product sequencing.
- `docs/DECISIONS.md:2034+` -- Decision 75, "Frame-Lock Anti-Pattern in Architectural Planning":
  names the failure mode and defines the plan-critique Frame Challenge mitigation and its five
  questions (`:2056-2060`), including "what assumption from an earlier decision are we still
  carrying that the world has moved past?"
- `docs/PROJECT_CONTEXT.md:313-469` -- "Platform End-State": frames the destination as the
  four-tier workflow closing "with no human in the critical path of one iteration"; the product
  roadmap is named the "sibling product axis" (`:319`). No sequencing rationale is stated.

**The dormant product plane:**
- `docs/ROADMAP-PRODUCT.yaml:20` -- `status: draft`; `:21` `filed_via: pending_log_decision_lambda`;
  `:11-15` note validation is deferred to a not-yet-authored `scripts/product_roadmap.py`, so
  `validate.py` does not exercise the file.
- `docs/ROADMAP-PRODUCT.yaml:347-393` -- `current_state`: "Data plane is production-grade; trading
  plane is mostly scaffold or absent." `layer_rollup` (`:388-393`): L1 scaffold, **L2 absent
  (entirely)**, L3 latency-penalty sizer (no broker; no order lifecycle), L4 agent_telemetry
  only, risk sublayer absent.
- `src/live/rat_ensemble.py:90` -- `RATModel.predict` raises `NotImplementedError`;
  `src/live/rat_ensemble.py:78` -- `VectorMemory.retrieve_similar` returns `[]`.
- `src/execution/async_engine.py:292` -- the L3 surface `print()`s executed-trade dataclasses; no
  broker, no order_id, no submission.
- `src/main.py:129`,`:139` -- live mode wires `mock_signal_generator` and
  `mock_market_data_source`.
- `docs/AUDIT-PROMPT-product-roadmap-yaml.md` Section 11 -- the embedded pivot transcript (Parts
  A/C/E/G document data architecture, the four-layer model, identifiability/execution/funnel,
  hedging/environments). "Concurrent paper trading alongside live" appears as a design element
  (~`:288`). `docs/ROADMAP-PRODUCT.yaml:113` records Parts B/D/F as "user questions only".

**The state of the bet (from the adjacent, in-frame audits -- context, not to be re-derived):**
- `audits/platform-roadmap-mvp-triage-7d57a0d.md` and `.yaml` -- MVP reachability
  `reachable_with_resequencing`; telemetry verdict `binding_but_underscoped`; **"zero telemetry
  is captured or stored today"**, write path dead since 2026-05-28, open `rec-2173` records the
  blind spot; the executor freeze constrains plan-type/executor-operation, not construction.
- `audits/executor-roadmap-review-7d57a0d.yaml` -- the T4 executor design review (in-frame).

**Controls that operate inside the frame:**
- `.claude/skills/plan-critique/SKILL.md:69-100` -- Phase 2b "Frame Challenge (MANDATORY)":
  challenges an individual plan's frame; recommends REVISE only on a concrete contradiction with
  a Decision, roadmap item, or North Star principle (`:85`).

**Governing constraints:** Decision 67 / CD.17 (executor freeze), Decision 84 (DuckLake backend),
Decision 101 (public repo), Decision 77 (environment taxonomy), Decision 93 (defer-by-exception).

## 11. EMPIRICAL PASS

Two bounded sampling operations. Observed findings outrank static ones at equal severity; tag
each finding `evidence_kind: static | observed`.

- **Citation census (cap: ALL hits, expected < ~12 -- do NOT synthesize beyond what you find).**
  `rg -n "platform-first|platform first|platform-before-product"` across `docs/` and `audits/`
  and `logs/.recommendations-log.jsonl`. For **each** hit apply the counterfactual test: *does
  this artifact RATIFY the sequencing (records it as a decision with alternatives), or merely
  ASSUME it (cites it as an operating given)?* Tabulate ratify-vs-assume counts; this is the
  primary evidence for Q1 / VD1.
- **Pivot-timing read (cap: Section 11 of one file only).** Read
  `docs/AUDIT-PROMPT-product-roadmap-yaml.md` Section 11 and determine whether platform-vs-product
  *timing/sequencing* is discussed anywhere in it (as opposed to product architecture). Record
  the answer explicitly -- it gates trap 5 and CAND-A.

## 12. METHOD

- **P1 Read.** All Section 10 anchors, re-verifying each. Run Section 5 setup.
- **P2 Trace.** Adjudicate each Section 9 candidate against the anchors and the North Star.
- **P3 Empirical.** Run the two Section 11 passes.
- **P4 Rate.** Fill `rubric_ratings[]` per surface; answer Q1-Q6.
- **P5 Dedup.** Section 13 discipline on every prospective finding.
- **P6 Synthesize LAST.** Fill the decision block, `per_surface_assessment`, `summary`, and
  compute maturity (Section 15) top-down. Never compute maturity before findings are final.

## 13. DEDUP DISCIPLINE

Before filing ANY finding, grep the ownership surfaces and record the search on the finding
(`roadmap_crossref.dedup_search_terms`, `dedup_hit_count`). A hit means you assess *sufficiency*
(planned-insufficient / planned-unbuilt) or reject (fully-covered) -- never file it as a fresh
discovery. A finding without a recorded negative search is a `HYPOTHESIS`, not `CONFIRMED`.

Ownership surfaces:
- `docs/DECISIONS.md` (`rg "^## Decision"` for headers; full-text for premise citations).
- `docs/ROADMAP-PLATFORM.yaml` and `docs/ROADMAP-PRODUCT.yaml` `tier_items[]`.
- `logs/.recommendations-log.jsonl` (open recs).
- `audits/` (adjacent audits already own MVP-reachability and telemetry-binding -- do not
  re-derive their content; cite them).

**Deliberate-constraints do-not-flag list (each with its id -- these are settled; do not raise
them as gaps):**
- Executor freeze -- Decision 67 / CD.17 (trigger-gated).
- DuckLake sole backend -- Decision 84.
- Public-repo boundary -- Decision 101.
- Environment taxonomy / sandbox auto-apply -- Decision 77.
- defer-by-exception + no-enumerated-MVP -- Decision 93.
- The product architecture / four-layer model / MVP-v1 -- pivot transcript (settled).
- Product roadmap unvalidated (`product_roadmap.py` not yet built) -- known and tracked.

The audit examines the *allocation frame above* these. Reopening any of them is out of scope.

## 14. OUTPUT

Write both deliverables. The YAML is the system of record; the `.md` is a <= ~1500-word executive
report (the two verdicts up front, then costs, then the disposition and its rationale).

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1, scope_surfaces: [sequencing-frame, product-loop-feasibility],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: <ratified|inherited-unratified|frame-locked>, basis: [], prose: ""}
    - {q: Q2, verdict: <feasible-low-cost|feasible-high-cost|infeasible>, basis: [], prose: ""}
    - {q: Q3, verdict: <interleave-favored|sequencing-favored|too-close-to-call>, basis: [], prose: ""}
    - {q: Q4, verdict: <defined|undefined-should-exist|not-needed>, basis: [], prose: ""}
    - {q: Q5, verdict: <ratify_as_is|ratify_with_reversal_conditions|resequence_interleaved|insufficient_evidence>,
       basis: [], prose: "points to sequencing_verdict.frame"}
    - {q: Q6, answers: [{question: "", answer: "", basis: []}]}   # seeds answered AND extended
  sequencing_verdict:
    frame: {verdict: <same enum as Q5>, mechanism: "", what_changes: "", cost: "",
            rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: sequencing-frame, maturity: <derived>, strengths: "", top_gaps: []}
    - {surface: product-loop-feasibility, maturity: <derived>, strengths: "", top_gaps: []}
  rubric_ratings:
    - {surface: , dimension: VD1..VD5, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: SEQ-01, surface: sequencing-frame|product-loop-feasibility|shared,
       question: Q1..Q6, dimension: VD1..VD5, title,
       evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|ratify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match, decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [], highest_leverage_change: <id>,
            maturity_sequencing-frame: <value>, maturity_product-loop-feasibility: <value>}
```

**COUNTING INVARIANT:** `findings[]` is the SOLE enumerated list. `total_findings =
len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered
or not-a-gap candidates live in `rejected_candidates[]`, NOT findings. `rubric_ratings`,
`question_answers`, and `sequencing_verdict` are systems-of-record referenced FROM findings,
never re-counted. `top_improvements` and `highest_leverage_change` MUST be finding ids.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why it would FAIL if
the gap were real. A control that could not catch the gap neither lowers severity nor dismisses a
candidate. `CONFIRMED` requires the behavior traced to file:line or a sampled artifact; anything
less is `HYPOTHESIS`.

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing or
ordering:
- **critical** = active work across the roadmap is being materially mis-directed *right now* by
  an unsound premise (the premise is both unexamined AND you judge it likely wrong on the
  evidence).
- **high** = a governance weakness that materially reduces confidence in the allocation (e.g., a
  consequential frame with no reversal trigger and no owned challenger) AND whose compensating
  controls you judged insufficient.
- **medium** = a recorded-but-thin treatment, ambiguity, or missing ratification with a clear
  fix. **low** = clarity / wording / documentation placement.

An unratified-but-sound frame is typically NOT critical -- the defect is the *absence of a
conscious record*, whose natural remedy is `ratify_with_reversal_conditions`, not a resequence.
Let the evidence, not the word "unratified", set severity.

**Maturity** -- compute LAST, per surface, top-down, first match wins. Pin these thresholds:
- `frontier` = 0 open critical AND 0 open high findings on that surface.
- `strong` = 0 critical AND <= 1 high.
- `solid` = <= 1 critical.
- `nascent` = otherwise.

The top rating remains reachable if you argued a property-matched compensating control -- the
framing must not foreclose it.

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This
   sha IS the audited tree; use it in both deliverable filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/platform-first-sequencing-<sha> origin/main` so the PR diff is only the
   two deliverable files. This is a deliberate, documented exception to the `claude/*`
   session-branch rule: this audit session needs a clean two-file diff off the audited base. The
   CI signal-green comment wake fires only on `claude/*` PRs -- irrelevant here; you end your turn
   without merging, and the human disposes of the PR.
3. Repo-wide validation is advisory outside CI here: a clean YAML parse of the two deliverables is
   the real pre-push gate. An unrelated `validate --pre` failure is recorded in
   `meta.contract_notes`, never fixed (write boundary).
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign`
   (signing may be unavailable; that is expected). `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=`main`, ready for review, title
   `audit: platform-first sequencing frame (sequencing-frame, product-loop-feasibility)`, body =
   the `summary` block in a YAML fence plus a 2-3 sentence lede). Then **END THE TURN** -- do not
   poll, do not merge, do not subscribe.

## 17. GUARDRAILS

- **Write boundary (closed list):** the ONLY files you create or modify in the tree are
  `audits/platform-first-sequencing-<sha>.yaml` and `audits/platform-first-sequencing-<sha>.md`.
  Regenerating gitignored local caches per Section 5 is expected and does not breach this; never
  commit them. Do not edit any audited surface, any Decision, any roadmap, any skill, or
  `validate.py`.
- **Precision over volume.** Fewer than ~4 surviving findings is a valid, honest result -- state
  it; do not pad. A finding you cannot trace to file:line or a sampled artifact is a `HYPOTHESIS`
  and must say so.
- **No verdict inheritance.** "Never ratified" is a fact, not a conviction. Ratifying the frame
  as-is or with reversal conditions is a full-credit outcome. `insufficient_evidence` is
  legitimate if the evidence does not discriminate.
- **Stay above the immunized constraints (Section 13 list).** The audit is about the allocation
  frame, not the substrate beneath it.
- You draft; the human disposes. End your turn after opening the PR.
