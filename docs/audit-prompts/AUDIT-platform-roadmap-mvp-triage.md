# AUDIT PROMPT -- Platform roadmap MVP-triage (docs/ROADMAP-PLATFORM.yaml active items)

You are a fresh agent session. This file is your entire context. You have no
view of any prior chat and no one to ask. Execute it exactly as written.

## 1. TASK

Perform a REPORT-ONLY scope-triage of the ACTIVE tier_items in
`docs/ROADMAP-PLATFORM.yaml` -- the canonical platform roadmap. "Active" means
`status` in {`not_started`, `in_progress`}. At authoring time that was 48
items; re-derive the exact set yourself (Section 5) and triage whatever set
exists at the audited commit.

For every active item you assign a DISPOSITION from a pinned enum
(`keep_active_mvp` / `defer_post_mvp` / `mark_complete` / `remove` / `rescope`;
defined in Section 2), grounded in the item's `exit_criteria` versus the actual
repo state and in the Platform-MVP boundary (Decision 93). You then answer five
questions (Section 7): the minimal MVP critical path and whether it is reachable
given the executor freeze; the deferral set; the redundancy set; whether
telemetry capture/storage is the binding constraint on recursive improvement;
and the questions the requester did not think to ask.

You draft; the human disposes. You do NOT edit the roadmap, do NOT file
recommendations, do NOT write to the warehouse. You produce exactly two files:

- `audits/platform-roadmap-mvp-triage-<sha>.yaml` -- the machine-parseable
  triage report conforming to Section 14.
- `audits/platform-roadmap-mvp-triage-<sha>.md` -- a companion report, prose,
  <= 1500 words, the executive layer a human reads first.

`<sha>` is the short SHA of the audited commit (Section 16). The ONLY files you
create or modify in the repository tree are those two deliverables. Regenerating
gitignored local caches per Section 5 is expected and does not breach this
boundary (never commit them).

The requester's stated priority: "telemetry capture and storage to drive
recursive improvement that will allow for faster iteration." Question Q4 and
deep-dive DD-A carry that lens; do not let it bias the other dispositions.

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It never hands you a
verdict. Section 12's candidate observations are starting points for
adjudication, not conclusions. ASSUME NO CANDIDATE IS TRUE UNTIL YOU TRACE IT.
A run that merely confirms the candidates below has failed.

Every active item receives exactly one disposition. The pinned enum:

- `keep_active_mvp` -- the item is on the critical path to closing the
  autonomous loop (Decision 93) and its work is not yet done. This is the NULL
  disposition (the residual): per Decision 93's defer-by-exception rule you do
  NOT enumerate a committed MVP set; keep_active_mvp simply means "no change
  recommended." keep_active_mvp entries appear ONLY in the `dispositions` block,
  never in `findings`.
- `defer_post_mvp` -- real, valid work that is NOT required to close one loop
  iteration; recommend flipping status to `deferred_post_mvp`. Subject to the
  hard DAG rule in Section 7/Q2.
- `mark_complete` -- the item's `exit_criteria` are already provably satisfied
  by shipped work; recommend flipping status to `complete`. Requires the
  anti-vacuity proof in Section 11.
- `remove` -- the item is obsolete or superseded and no longer describes wanted
  work; name what supersedes it. Pick the mechanism by this rule: recommend
  `reserved` TOMBSTONING when the item id is referenced elsewhere (another item's
  `depends_on`, a gate, a CD, a decision -- id must survive for traceability);
  recommend outright DELETION only when no such reference exists. State which and
  why in the finding.
- `rescope` -- the item is partially valid but mis-framed, over-broad, or
  should be split/merged; state the new shape.

Mapping to the output: every disposition whose verdict is NOT `keep_active_mvp`
becomes one `findings[]` entry (Section 14). `keep_active_mvp` items are
recorded in `dispositions` only. Severity (Section 15) is assigned AFTER
judgment by leverage on development speed; it is never pre-supplied here.

"Redundant" (the requester's word) splits into two DISTINCT dispositions with
distinct evidence: already-DONE is `mark_complete`; obsolete/SUPERSEDED is
`remove`. Never collapse them.

## 3. READ FIRST -- disambiguation traps

- **This audit is NOT the June roadmap-consistency audit.** A separate prompt,
  `docs/AUDIT-PROMPT-platform-roadmap-audit.md`, asks "is this roadmap a
  trustworthy, complete, internally-consistent control surface?" That is a
  different question. You are NOT auditing internal consistency, schema
  correctness, or anchor rot. You are triaging active items for MVP scope and
  redundancy. If you find yourself filing consistency findings, stop -- they are
  out of scope here.
- **PLATFORM vs PRODUCT roadmap.** `docs/ROADMAP-PLATFORM.yaml` (tier_items
  T-1..T5, infrastructure/governance) is in scope. `docs/ROADMAP-PRODUCT.yaml`
  (phases, trading strategy lifecycle) is OUT of scope. Do not open it except to
  confirm a cross-roadmap dependency edge exists.
- **`strategic: true` (a boolean field on tier_items) is NOT the STRATEGIC
  plan-type.** The field marks large multi-file items. The STRATEGIC plan-type
  is frozen by Decision 67 / CD.17. They are linked only in that a `strategic:
  true` item generally needs a STRATEGIC plan to execute -- which is currently
  suspended. Treat that linkage as a SEQUENCING fact (Q1), never as a defect of
  the item.
- **"Redundant" trap** (restated because it is the requester's framing):
  already-done => `mark_complete`; obsolete => `remove`. Two things, two
  dispositions.
- **`reserved` items are already tombstoned** (T1.4, T1.8 at authoring time).
  They are NOT active and NOT in the triage set. Treat as context.

## 4. SCOPE

In scope -- the ACTIVE set: every tier_item with `status` in {`not_started`,
`in_progress`}. Re-derive the exact list (Section 5). Authoring-time set (48
items, re-verify; do not trust this list -- it is a hint):
T-1.14, T-1.19, T0.4, T0.7a, T0.7b, T0.7c, T0.8, T1.1, T1.2, T1.3, T1.5, T1.6,
T1.7, T1.9, T1.10, T1.13, T2.7, T2.15, T2.18, T2.19, T2.25, T2.26, T2.29, T2.30,
T2.31, T2.32, T2.36, T3.2, T3.3, T3.4, T3.5, T3.7, T3.9, T3.10, T3.14, T3.17,
T3.20, T4.1, T4.2, T4.3, T4.4, T4.5, T4.6, T4.7, T5.1, T5.2, T5.4, T5.5.

"Active" is `status` in {`not_started`, `in_progress`} exactly. The full status
vocabulary is a closed set of five: the two active statuses plus {`complete`,
`deferred_post_mvp`, `reserved`}. IF an item carries any status outside those
five, treat it as context (not active), do not assign it a disposition, and
record it in `meta.contract_notes`.

Context, NOT triaged (do not assign dispositions):
- `complete` items (72 at authoring time) -- evidence for `mark_complete`
  adjacency and supersession, nothing more.
- `deferred_post_mvp` items (10 at authoring time: T2.6, T2.8, T2.9, T2.11a,
  T2.11b, T3.19, T4.8, T4.9, T4.10, T4.11) -- already-decided deferrals. Do NOT
  re-triage them. SINGLE EXCEPTION: you MAY emit one `remove`-class finding for
  a deferred item if it is clearly obsolete (superseded, not merely parked); tag
  such a finding `surface: deferred-context` and cap it at one per item. Never
  recommend un-deferring.
- `reserved` items (T1.4, T1.8) -- tombstones; context only.

Shared vocabulary:
- Tiers T-1 (roadmap-harness bootstrap), T0 (agent-tooling platform / verb
  Lambdas), T1 (verb surface expansion + DQ), T2 (DuckLake migration + Terraform
  CI/CD), T3 (verifier harness + telemetry analysis), T4 (autonomous executor),
  T5 (legacy teardown). Rubric (Section 8) rates per tier.
- `exit_criteria` is a MIXED representation -- do not assume one shape. For most
  active items (38 of 48 at authoring time) it is a plain list of bare STRINGS
  (no per-criterion status). For a minority (10 at authoring time: T0.4, T1.13,
  T2.18, T2.19, T2.26, T2.36, T3.17, T3.20, T4.3, T5.5 -- re-derive) it is a list
  of `{id, text, status}` objects where `status` is `open` / `met` / `rehomed`.
  Your parser must handle BOTH shapes per item (check element type). Because the
  bare-string form has no status and the dict-form status may lag reality, a
  `mark_complete` disposition NEVER rests on a YAML `status` field -- it rests on
  the artifact proof of Section 11. Treat any per-criterion `status` as a lead,
  never as the evidence.
- `depends_on` entries are EITHER specific ids (e.g. T2.18) OR tier-name
  shortcuts (e.g. "T2" = all items in tier T2 complete).

Out of scope, one line each: ROADMAP-PRODUCT.yaml; the June consistency audit;
schema/validator correctness of the roadmap harness; ratified-decision
relitigation (Section 13); any warehouse or AWS write.

Trust-nothing clause: obtain every count, id, `exit_criteria` state, and
`depends_on` edge by reading `docs/ROADMAP-PLATFORM.yaml` yourself. Trust no
number quoted in this prompt. Re-derive from the file and record any id that no
longer resolves in `meta.stale_anchors`.

## 5. SETUP

FIRST establish the audited tree, so your triage matches `meta.audited_commit`:
`git fetch origin main`, then ensure your working tree is at `origin/main` before
you project anything (Section 16 step 1 derives the sha; step 2 creates the
branch off `origin/main`). If your checkout differs from `origin/main`, switch to
it now -- projecting from a divergent tree would triage the wrong roadmap.

Read, in order: this prompt fully; `CLAUDE.md` and `AGENTS.md` at repo root;
`docs/PROJECT_CONTEXT.md` (the "Platform End-State" heading is the target-state
summary; if that heading is absent at HEAD, skip it and proceed). Then load the roadmap by id-keyed projection, NOT by line anchors (the
file is ~650KB YAML; line anchors rot). Canonical projection:

```
bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); \
print(len(d['tier_items']))"
```

Extend that pattern to project `tier_items[]` (id, tier, name, intent, status,
strategic, depends_on, effort, exit_criteria, note, progress_note),
`candidate_decisions[]` (id, title, state, gates), `cross_tier_gates[]`, and
`open_questions[]` / `known_gaps[]`.

Generate the dedup caches (needed for Section 13):

```
bin/venv-python -m scripts.session_preflight --roadmap-detail full
```

This populates `logs/.preflight-report.json` and refreshes
`logs/.recommendations-log.jsonl` (a local read cache). This refresh is a READ
of the warehouse into a local cache -- it is not a warehouse write and does not
breach the Section 1 "no warehouse write" boundary. Never hand-edit either file.

Degraded paths -- never abort, set a flag and proceed:
- IF `session_preflight` fails on creds/egress: set `meta.degraded_dedup=true`,
  mark every finding's `dedup.hit_count=null` and confidence no higher than
  HYPOTHESIS for any claim that depended on a warehouse read, and proceed using
  the on-disk `logs/.recommendations-log.jsonl` if present (note in
  `meta.contract_notes` that it may be stale).
- IF an item id in Section 4/12 does not resolve in the current file: record it
  in `meta.stale_anchors` and continue with the ids that do resolve.
- IF a `mark_complete` anti-vacuity check (Section 11) cannot reach a file it
  needs: downgrade that disposition to `keep_active_mvp` or `rescope` and note
  why; never assert completion you could not verify.

## 6. NORTH STAR

The bars you judge each surface against. These are judgment principles, not
mechanical filters -- argue each surface against them.

- **NS-LOOP (Decision 93 boundary).** The Platform-MVP boundary is: "the
  autonomous loop closes end-to-end with no human in the critical path of one
  iteration (rec -> implement -> validate -> merge -> deploy -> observe -> next
  rec)." An item is MVP-critical iff, without it, that loop cannot close for one
  iteration. This is a bar you judge each item against -- not every
  infrastructure item is on the critical path even if it is valuable.
- **NS-DEFER (Decision 93 defer-by-exception).** MVP work is critical by
  default; items leave MVP scope only by conscious deferral, and the MVP set is
  NEVER enumerated -- only the deferred set is. Your job is to name the DEFERRAL
  set and the REDUNDANT set; the residual is MVP by construction. Do not produce
  a committed "MVP list" -- that would trip the frame-lock anti-pattern the
  decision exists to avoid.
- **NS-TELEMETRY (requester's North Star).** Telemetry capture and storage exist
  to drive recursive self-improvement and faster iteration. Judge the telemetry
  chain against the question: does the loop actually get FASTER because this data
  is captured, stored, and read? Capture with no reader is not yet leverage.
- **NS-LEAN (requester's intent).** The audit exists to speed development.
  Redundant-but-harmless items still cost eligibility-surface noise (Decision 93
  problem statement). Prefer the disposition that reduces active scope when the
  evidence supports it -- but never manufacture a `mark_complete` or `remove` to
  shrink the list (Section 11 gate; Section 17 anti-padding).

## 7. THE QUESTIONS

Each question gets its own first-class answer slot in `question_answers`
(Section 14). Verdict enums are pinned per question.

- **Q1 -- MVP critical path and reachability.** Trace the depends_on DAG of the
  `keep_active_mvp` residual. What is the minimal keystone-first SEQUENCE of
  active items required to close one autonomous loop iteration (NS-LOOP)? Is that
  boundary reachable as the roadmap is currently sequenced -- given that the T4
  executor cluster (the loop's terminal consumer) is `strategic: true` and gated
  behind the Decision 67 / CD.17 STRATEGIC-plan freeze (reversal trigger: T4.2
  complete +14d AND T3.2 latest_run PASS AND T3.3 complete +7d)? Verdict enum:
  `reachable` / `reachable_with_resequencing` / `blocked_by_freeze`. The answer
  MUST include the ordered id sequence and name every freeze-gated item on it.
  Sourcing note for the freeze gates: `T3.2.latest_run.verdict` is a RUNTIME
  field, NOT stored in the static roadmap YAML (the roadmap's own
  `agent_instructions` resolve runtime fields to "deferred"/unknown). Do not hunt
  for it; treat it as not-yet-PASS unless you can cite positive evidence (a green
  causal-chain verifier run). The reversal ALSO requires T4.2 complete +14d and
  T3.3 complete +7d -- both `not_started` at authoring time -- so the freeze holds
  structurally on the earliest-unmet gate regardless of T3.2's run state; reason
  from that earliest-unmet gate and say which it is.
  Reconciliation with NS-DEFER: `mvp_sequence` is a critical-path DIAGNOSTIC
  trace (which items block loop closure and in what order), NOT a committed MVP
  scope surface. Producing it does not enumerate the residual MVP set and does
  not breach Decision 93's "never enumerate the MVP set" rule -- the deferral set
  and the redundancy set remain the only committed enumerations.
- **Q2 -- Deferral set.** Which active items should be `defer_post_mvp`?
  HARD CONSTRAINT you must enforce: Decision 93 forbids any live item
  (`not_started`/`in_progress`) from `depends_on` a `deferred_post_mvp` item
  (enforced at load by `platform_roadmap.py`). So before recommending
  `defer_post_mvp` for item X, compute the set of active items that transitively
  `depends_on` X. If any dependent is NOT also being deferred, the deferral is
  INVALID -- either extend the deferral to the dependents (and justify) or
  withhold it and record the block in the finding's `sequencing.blocked_behind`.
  A deferral finding whose dependents are not handled is a defect in your report.
  Verdict enum: `sufficient` / `partial` / `none_warranted`.
- **Q3 -- Redundancy set.** Which active items are redundant -- sub-classified as
  `mark_complete` (exit_criteria provably met, Section 11) versus `remove`
  (obsolete/superseded, name the successor)? Verdict enum: `sufficient` /
  `partial` / `none_found`.
- **Q4 -- Telemetry as binding constraint (requester's priority).** Assess the
  capture -> storage -> verification -> analysis chain (DD-A). Is telemetry
  capture and storage adequately scoped and correctly placed on the MVP critical
  path? Is telemetry the BINDING constraint on recursive improvement -- or is the
  true bottleneck upstream (e.g. the frozen executor that would consume the
  analysis, or the ops verb surface the loop writes through)? Distinguish
  "captured" from "stored durably" from "read by a live consumer": data captured
  but never read is not yet leverage (NS-TELEMETRY). Verdict enum:
  `binding_and_ready` / `binding_but_underscoped` / `not_binding_constraint`.
  This question embeds DD-A as its evidence base.
- **Q5 -- Questions the requester did not think to ask.** Answer AND extend these
  seeds: (a) Does closing the MVP loop actually depend on the T4 executor, or can
  one iteration close with a human-in-the-loop-but-not-in-the-critical-path
  interpretation that the current `/orient -> /plan -> /implement` surface
  already satisfies? (b) Is there a circular tension where the MVP boundary
  (loop closure) requires items the freeze forbids executing, making "MVP" and
  "frozen" mutually exclusive until CD.17 reverses? (c) Among `keep_active_mvp`
  items, is any a single point of failure whose slip blocks the whole residual?
  Use the `answers` shape (Section 14), not a single verdict.

## 8. RUBRIC

Rate each of the 7 tiers (T-1, T0, T1, T2, T3, T4, T5) on each dimension.
Pinned enum: `strong` / `adequate` / `weak` / `absent` / `n/a`. `n/a` is correct
and costless where a dimension does not structurally apply to a tier -- never
manufacture a rating to fill a cell.

- **VD1 MVP-criticality clarity** -- is it clear, per this tier, which active
  items are on the loop-closure critical path versus hardening? (serves Q1, Q2)
- **VD2 redundancy hygiene** -- does this tier carry active items whose work is
  already done or obsolete? `strong` = none; `weak` = several. (serves Q3)
- **VD3 telemetry contribution** -- does this tier advance capture -> storage ->
  analysis? `n/a` where structurally unrelated. (serves Q4)
- **VD4 sequencing coherence** -- are this tier's active `depends_on` edges and
  freeze interactions coherent, or do they strand items / create the
  MVP-requires-frozen tension? (serves Q1, Q2)

Every question is served by at least one dimension; every dimension serves at
least one question.

## 9. DEEP-DIVES

**DD-A -- Telemetry capture/storage/analysis chain (feeds Q4).** Trace the chain
end to end across these active items (re-derive membership; some may already be
complete): T3.20 (agent-turn telemetry capture -- hooks + turn-grain
observations), T2.36 (Phase 4: telemetry re-lands on DuckLake -- durable
storage), T2.19 / T2.26 (the DuckLake ops write/read migration the telemetry
tables ride on), T1.6 (DQ runner as alarm-not-gate over telemetry), T1.9 (Lambda
SLOs + CloudWatch alarms), T3.2 (causal-chain verifier: PRODUCE -> TRANSPORT ->
PERSIST -> QUERY -> ASSERT), T3.3 (Telemetry Phase E cloud analysis agent -- the
READER, `strategic: true`, gated by G.8 on T3.2 PASS), T4.3 (scheduled-agent
loop re-enable). Foundation already shipped: the telemetry star schema Phases
A-D (verify this claim against the repo; do not assume). For each link state:
built / in_progress / not_started; whether the NEXT link can consume it; and
where the chain breaks between "captured" and "read by a live consumer." The
deliverable of DD-A is a judgment on whether storage is the binding constraint,
or whether capture is ahead of any consumer (T3.3) that the freeze keeps unbuilt.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify every fact before
relying on it; re-derive from `docs/ROADMAP-PLATFORM.yaml` at the audited commit.

- The roadmap has (authoring-time) 132 tier_items: 72 `complete`, 41
  `not_started`, 7 `in_progress`, 10 `deferred_post_mvp`, 2 `reserved`.
- 13 items carry `strategic: true`; of the active set, 9 are strategic:
  T1.5, T3.3, T3.4, T4.1, T4.2, T4.4, T4.5, T4.6, T4.7.
- Decision 93 (`docs/DECISIONS.md`, "Platform-MVP boundary + deferred_post_mvp
  lifecycle status") states the boundary, the defer-by-exception rule, the
  `deferred_post_mvp` semantics, and the no-live-dep-on-deferred load-time
  constraint. Read it in full.
- Decision 67 / CD.17: the STRATEGIC-plan freeze and its reversal trigger. CD.17
  lives in `candidate_decisions[]` (id "CD.17", state "pending").
- Decision 90: the four-tier workflow (`/orient -> /plan -> /implement ->
  /develop-executor`); current operational state is the first three, executor
  frozen.
- `cross_tier_gates[]` includes G.8 (T3.2 PASS before T3.3), G.9 (T4.2 stable
  14d before T5.1), G.10 (T2 migration subset + 30d before T5.2). These bind
  sequencing; treat them as MUST-hold facts.
- Recent main commits merged inference-provider .md->.yaml conversion (relevant
  to T-1.14 `in_progress`). Verify current T-1.14 exit_criteria state.
- rec-2173 (open) records a preflight telemetry-health blind spot (dedup pointer
  for DD-A). Verify it still exists via the recs cache.

Facts here carry no verdicts. "T-1.14 is `in_progress`" is a fact; "T-1.14 is
done" is a disposition you must earn (Section 11).

## 11. ANTI-VACUITY GATE (mark_complete and remove)

A `mark_complete` disposition is a claim that the item's `exit_criteria` pass
TODAY. Prove it, do not infer it:

- For each criterion, name the file/commit/artifact that satisfies it and state
  the counterfactual: "if I checked this criterion right now, would it pass?"
  If any criterion cannot be shown to pass against a named artifact, the
  disposition is NOT `mark_complete` -- downgrade to `rescope` (partial) or
  `keep_active_mvp`, and say which criteria remain open.
- Do NOT rely on any YAML `exit_criteria` status; most active items have
  bare-string criteria with no status at all (Section 4), and where a status
  exists it can lag reality in either direction. The YAML is a lead, the artifact
  is the evidence.
- `evidence_kind: observed` requires you to have read the satisfying artifact
  this session; otherwise `static` and confidence HYPOTHESIS.

A `remove` disposition requires naming the concrete successor (a decision, a
shipped item, or a superseding CD) that makes the item obsolete. "Feels stale"
is not evidence. If you cannot name a successor, it is not `remove` -- it is at
most `defer_post_mvp` or `keep_active_mvp`.

## 12. CANDIDATE OBSERVATIONS (neutral -- adjudicate, do not confirm)

Starting hypotheses. Each is phrased neutrally; convict or acquit by tracing.

1. The T4 executor cluster (T4.1, T4.2, T4.4, T4.5, T4.6, T4.7) is `strategic:
   true` and behind the Decision 67 / CD.17 freeze, while Decision 93's MVP
   boundary is loop closure -- which is T4 territory. (Adjudicate: is the MVP
   boundary reachable while the freeze holds? Q1, Q5.)
2. Several T2 ops/DuckLake items (T2.19, T2.26 `in_progress`; T2.7, T2.29,
   T2.30, T2.31, T2.32) concern the migration; some `exit_criteria` may be met by
   already-merged commits. (Adjudicate per Section 11: `mark_complete`?)
3. T-1.14 (`in_progress`, inference-provider .md->.yaml) may be satisfied by a
   recent merge. (Adjudicate: `mark_complete`?)
4. T5 items (T5.1 VM decommission, T5.2 account teardown, T5.4 DECISIONS.md
   retirement, T5.5 INTENT extraction) are legacy teardown, gated by G.9/G.10.
   (Adjudicate: `defer_post_mvp` hardening, or on the critical path?)
5. T0.7a/b/c, T0.8, T1.1, T1.2, T1.3 build the typed Lambda verb surface (CD.10)
   fronting the ops boundary. (Adjudicate: MVP-critical for loop closure, or is
   the current `ops_data_portal` sufficient to close one iteration? Q1, Q5.)
6. T3 hardening items (T3.5 TCA aggregation, T3.7 mutation testing, T3.14
   context-budget metric, T3.17 V-tier floor, T3.9 post-merge rec
   reconciliation, T3.10 retire legacy verification writes). (Adjudicate: which
   are loop-closure-critical vs post-MVP?)
7. The telemetry chain (DD-A) may have capture (T3.20) and storage (T2.36) ahead
   of its only live reader (T3.3), which the freeze keeps unbuilt. (Adjudicate:
   Q4 binding-constraint verdict.)

These candidates deliberately span "defer," "complete," and "remove" so the set
does not bias you toward one disposition. Extend the set -- items not listed here
still need dispositions.

## 13. DEDUP DISCIPLINE

Before filing any `findings[]` entry, search the ownership surfaces and record
the search on the finding:

- The roadmap itself: does a `candidate_decision`, `open_question`, `known_gap`,
  or another tier_item already own this disposition? A hit means your finding is
  a sufficiency-assessment ("the roadmap already plans this defer/removal via
  X"), not a fresh discovery -- classify accordingly.
- `logs/.recommendations-log.jsonl` (the read cache): grep for the item id and
  key terms. Record the terms and count in the finding's `dedup.search_terms` and
  `dedup.hit_count` fields (Section 14 schema), and any prior owner in
  `dedup.prior_owner`. A finding with no recorded negative search is a
  HYPOTHESIS, not CONFIRMED.

Deliberate constraints -- DO NOT flag these as defects:
- Decision 93's boundary definition and defer-by-exception rule (ratified;
  classify AGAINST them, never relitigate).
- Decision 90 four-tier architecture and the CD-governance model.
- The Decision 67 / CD.17 freeze itself (a deliberate constraint; the executor
  being frozen is a sequencing FACT, not a defect of any item).
- The 10 existing `deferred_post_mvp` items (already-decided; Section 4 exception
  only).
- Unsigned CC-web commits (`git log %G? = N`) -- expected, per AGENTS.md.
- The two-roadmap split (PLATFORM vs PRODUCT) -- deliberate since PR #335.

## 14. OUTPUT CONTRACT

Write both deliverables. The YAML conforms to this shape; pin every enum inline.

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported name>, methodology_version: 1,
         scope_surfaces: [T-1, T0, T1, T2, T3, T4, T5],
         active_item_count: <re-derived>, degraded_dedup: false,
         contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: reachable|reachable_with_resequencing|blocked_by_freeze,
       basis: [<finding ids>], mvp_sequence: [<ordered item ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|none_warranted, basis: [], prose: ""}
    - {q: Q3, verdict: sufficient|partial|none_found, basis: [], prose: ""}
    - {q: Q4, verdict: binding_and_ready|binding_but_underscoped|not_binding_constraint,
       basis: [], prose: ""}
    - {q: Q5, answers: [{question, answer, basis: [<finding ids>]}]}
  dispositions:                      # ONE entry per active item -- the full triage
    <item_id>: {verdict: keep_active_mvp|defer_post_mvp|mark_complete|remove|rescope,
                tier: <tier>, rationale: "", telemetry_relevant: true|false,
                dependency_check: "<reverse-dep closure result, required for defer_post_mvp>",
                confidence: CONFIRMED|HYPOTHESIS}
  rubric_ratings:
    - {surface: <tier>, dimension: VD1|VD2|VD3|VD4,
       rating: strong|adequate|weak|absent|n/a, evidence: "<item-id|file:line>", note: ""}
  per_tier_maturity:                 # Section 15 output slot; one entry per tier
    - {surface: <tier>, maturity: lean|mostly-lean|noisy|overgrown,
       redundant_finding_count: <int>, note: ""}
  telemetry_chain_assessment:        # DD-A output, feeds Q4
    - {link: <item-id>, role: capture|storage|verification|analysis|infra,
       state: built|in_progress|not_started, next_link_can_consume: true|false, note: ""}
  findings:                          # every disposition whose verdict != keep_active_mvp
    - {id: RMAP-01, item_id: <tier_item id>, surface: <tier>|deferred-context,
       question: Q1|Q2|Q3|Q4|Q5, dimension: VD1|VD2|VD3|VD4,
       disposition: defer_post_mvp|mark_complete|remove|rescope,
       title, evidence: "<item-id|file:line>", evidence_kind: static|observed,
       current_state, recommended_state, rationale,
       redundancy_class: done|obsolete|n/a,   # done->mark_complete, obsolete->remove, else n/a
       remove_mechanism: tombstone|delete|n/a, # required when disposition==remove (Section 2 rule); else n/a
       leverage: "<how this speeds development>",
       severity: critical|high|medium|low, severity_rationale,
       confidence: CONFIRMED|HYPOTHESIS,
       dedup: {search_terms: [], hit_count: 0, prior_owner: ""},
       effort_to_action: XS|S|M|L,      # cost of the roadmap edit, not the item's own effort
       sequencing: {safe_to_action_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, disposition_would_have_been, evidence_or_decision_id}
  summary: {active_item_count, keep_active_mvp_count, defer_count, complete_count,
            remove_count, rescope_count, deferred_context_remove_count,
            total_findings, highest_leverage_change: <finding id|null>,
            top_changes: [<finding ids>],
            mvp_reachability: <Q1 verdict>, telemetry_verdict: <Q4 verdict>}
```

Invariants, stated verbatim:
- COUNTING INVARIANT: `dispositions` has EXACTLY one entry per active item;
  `len(dispositions) == meta.active_item_count`. The disposition counts partition
  the active set: `keep_active_mvp_count + defer_count + complete_count +
  remove_count + rescope_count == active_item_count`, where each `*_count` (other
  than keep) is the number of active-item dispositions with that verdict.
  `remove_count` counts ACTIVE-set removes ONLY. `deferred_context_remove_count`
  counts the separate Section-4-exception removes on already-deferred items
  (0 if none), which have NO `dispositions` entry. `findings[]` is exactly the
  active non-keep dispositions PLUS any deferred-context removes, so
  `total_findings == defer_count + complete_count + remove_count + rescope_count
  + deferred_context_remove_count`. `keep_active_mvp` items appear in
  `dispositions` only, never in `findings`. `rubric_ratings`,
  `per_tier_maturity`, `question_answers`, and `telemetry_chain_assessment` are
  systems-of-record referenced FROM findings, never re-counted.
  `highest_leverage_change` and every `top_changes` entry MUST be a finding id;
  IF `findings` is empty (a valid outcome), set `highest_leverage_change: null`
  and `top_changes: []`.
- TELEMETRY CROSS-CHECK: every disposition with `telemetry_relevant: true` must
  either appear as a `link` in `telemetry_chain_assessment` (Section 9 / DD-A) or
  carry a one-line note in its disposition `rationale` saying why it is
  telemetry-relevant but not part of the capture->storage->analysis chain. This
  is the reader for the `telemetry_relevant` flag; a true flag with neither is a
  contract gap.
- CONFIRMED requires the disposition traced to the roadmap file plus (for
  `mark_complete`) a read satisfying artifact; anything less is HYPOTHESIS.
- `dependency_check` is REQUIRED and non-empty for every `defer_post_mvp`
  disposition: state the transitive active-dependent set and how the deferral
  respects the no-live-dep-on-deferred rule.

The companion `.md` (<= 1500 words): lead with the MVP-reachability verdict (Q1)
and the telemetry verdict (Q4), then the defer / complete / remove counts, then
the top 5 highest-leverage changes with one-line rationales, then the single
highest-leverage change called out. Prose only; no re-dump of the YAML.

## 15. SEVERITY + MATURITY

Severity is assigned AFTER judgment, by leverage on DEVELOPMENT SPEED (the
requester's goal), never inherited from this prompt's framing:
- `critical` = the disposition removes a false blocker on the loop-closure
  critical path, OR corrects a misclassification that would otherwise strand a
  dependent (a deferral that violates the DAG, a `mark_complete` that is actually
  incomplete and would let a dependent start on unfinished ground).
- `high` = deferring / completing / removing this materially reduces active
  scope or unblocks sequencing on the critical path.
- `medium` = redundancy or rescope with a clear edit but modest leverage.
- `low` = naming / cosmetic.

Compensating-control rule (for `rejected_candidates`): a candidate is dismissed
only if you name the concrete control (a decision, a completed item, a gate)
that already handles it AND state why that control would fail to cover the gap if
the candidate were real. A control that cannot catch the break does not justify
dismissal.

Per-tier MATURITY -- compute LAST, per tier, top-down, first match wins, and
record each tier's result in the `per_tier_maturity` block (Section 14).
"Redundant finding" = a `mark_complete` or `remove` disposition on an item in
this tier. Evaluate the thresholds in THIS order (first match wins):
- `overgrown` = 4+ redundant findings in the tier, OR an unresolved
  DAG-stranding deferral tension in the tier (a recommended deferral whose active
  dependents are not handled, per Q2). This override is checked FIRST so it fires
  even when the redundant-count is low.
- `lean` = 0 `remove` AND 0 `mark_complete` findings in the tier (nothing
  redundant is masquerading as active) AND VD2 is `strong`.
- `mostly-lean` = <= 1 redundant finding in the tier.
- `noisy` = 2-3 redundant findings in the tier.

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then
   `git rev-parse --short origin/main`. This sha IS the audited tree; use it in
   the two deliverable filenames, the branch name, and `meta.audited_commit`.
2. `git switch -c audit/platform-roadmap-mvp-triage-<sha> origin/main`. This is a
   deliberate, documented exception to the AGENTS.md `claude/*` session-branch
   rule: the audit session needs a clean two-file diff off the audited base. The
   `never_on_main` hook blocks edits/commits only while the current branch IS
   `main`; you are on an `audit/...` branch, so it permits your work. IF any hook
   nonetheless blocks the switch/commit, do not force past it -- record the block
   in `meta.contract_notes` and stop before pushing.
3. Write the two files under `audits/` (an existing, git-tracked directory whose
   prior contents follow this same `.yaml` + `.md` companion convention -- these
   audit deliverables are query outputs a human reads and are an established
   EXEMPT surface, distinct from the AGENTS.md agent-first ban on standing
   human-readable companion docs, which governs repo architecture docs, not audit
   reports). If a file with the same `<sha>` name already exists, overwrite it
   (output is deterministic per audited commit). A clean `yaml.safe_load` of the
   YAML deliverable is your real pre-push gate. Repo-wide `validate.py` is
   advisory outside CI here; if it fails for a reason unrelated to your two
   files, record that in `meta.contract_notes` and do NOT fix it (write
   boundary).
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com
   commit --no-gpg-sign -m "audit: platform roadmap MVP-triage report"`.
   `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for
   review, title `audit: platform roadmap MVP-triage (T-1..T5 active items)`,
   body = the `summary` block in a yaml fence plus a 2-3 sentence lede). Then END
   THE TURN -- do not poll, do not merge, do not subscribe, do not self-approve.

## 17. GUARDRAILS

- Write boundary, restated as a closed list: the ONLY files you create or modify
  in the tree are `audits/platform-roadmap-mvp-triage-<sha>.yaml` and
  `audits/platform-roadmap-mvp-triage-<sha>.md`. Not the roadmap. Not the recs
  log. Not the warehouse. Regenerated gitignored caches are not committed.
- Every active item gets exactly one disposition -- completeness is the value
  here; do not skip an item because it is boring. But `keep_active_mvp` is a
  legitimate and common disposition: DO NOT manufacture a defer / complete /
  remove to look productive. A triage where most items are `keep_active_mvp` and
  only a handful move is a valid, honest result -- state it plainly.
- Precision over volume. Fewer than ~10 non-keep findings is a valid outcome if
  that is what the evidence supports; do not pad. A `mark_complete` you could not
  prove (Section 11) or a `remove` with no named successor does not ship --
  downgrade it.
- You draft; the human disposes. Nothing you recommend takes effect until a human
  executes it via `/plan`. Say so in the companion report's closing line.
