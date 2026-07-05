# AUDIT PROMPT: candidate_decisions premise validity and the ratification-lane feed

You are a high-capability model running a fresh session with no prior context. Read this
document once, then execute it exactly as written. It is self-contained; do not ask clarifying
questions. Every number, path, and anchor below is a POINTER you re-derive from the repository --
trust nothing quoted here.

## 1. TASK

Audit the `candidate_decisions[]` list in `docs/ROADMAP-PLATFORM.yaml` (40 entries: 16 `state:
ratified`, 23 `state: pending`, 1 `state: superseded` -- re-derive these counts) as a *binding
instruction set*. The roadmap's own rule states that pending candidate decisions (CD.NN) MUST be
treated as binding by any agent reading the roadmap, so a CD whose premise has silently decayed
steers live agent work. Three things are in scope: (S1) the premise validity of every CD, entry
by entry; (S2) the supersession / state-transition MARKING convention -- whether a premise
recorded as retired reliably flips the machine-readable `state` field the code keys on; (S3) the
ratification-lane discovery feed (`PlatformRoadmapState.ratifiable_cds()` and
`realized_but_pending_cds()` in `scripts/platform_roadmap.py`), which is empty at the audited
commit.

Answer the questions in Section 7. Produce exactly two deliverable files (Section 14): an audit
YAML and a companion markdown report, both under the repo-root `audits/` directory. The ONLY
files you create or modify in the repository tree are those two deliverables. Regenerating
gitignored local caches per Section 5 is expected and does not breach this boundary (never commit
them). You draft; the human disposes -- you do not ratify any CD, edit the roadmap, flip any
state, or file any recommendation. Your findings are proposals for a human to action.

## 2. CANDIDATE OBSERVATIONS vs VERDICTS -- THE EPISTEMIC CONTRACT

This prompt hands you FACTS and CANDIDATE hypotheses. It never hands you verdicts. Your entire
value is judgment the composing session could not do for you.

ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the
candidates below has failed. For every candidate you must read the cited surface, apply the
counterfactual (Section 11), and reach your own verdict -- including "not a defect" with the
compensating control named.

Per-candidate adjudication enum and its mapping to the output contract:

- CONFIRMED real defect, not owned by any roadmap item / decision / open rec -> `findings[]`,
  `roadmap_crossref.classification: novel`.
- Real gap whose owning item's remedy is insufficient, or is planned but unbuilt ->
  `findings[]`, classification `planned-insufficient` or `planned-unbuilt` (cite the item).
- Fully covered by an owning item / decision / open rec -> `rejected_candidates[]` (name the
  owner).
- Not a defect (a compensating control makes the behavior correct) -> `rejected_candidates[]`
  (name the control and why it property-matches, per Section 15).

Severity is assigned by you AFTER judgment (Section 15), never inherited from this prompt's
framing or ordering.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

Each trap names a two-things-one-name hazard or a plausible-but-wrong target. Internalize before
reading anything else.

- **T1 -- "superseded" is two things.** It is a formal `state` value (one CD carries `state:
  superseded`) AND it is prose that appears inside `detail` free-text ("[Amendment ... superseded
  by CD.NN]"). The gap between a premise marked superseded IN PROSE while `state` stays `pending`
  is the sharp edge of S1/S2. Never treat prose supersession as a state transition; never treat
  the one formal `superseded` entry as the whole story.
- **T2 -- two discovery feeds, not one.** `ratifiable_cds()` surfaces pending CDs carrying a
  truthy structured `realization_evidence` field. `realized_but_pending_cds()` surfaces pending
  CDs whose `detail` carries a `[Realized` PROSE marker but no structured field. They are
  distinct signals (the second deliberately lower-confidence). Assess BOTH; report the state of
  each separately.
- **T3 -- prior-audit counts are stale.** An earlier unclosed-loops audit reported "31/39
  pending" and "5 realized-marked (incl. CD.2, CD.6)". Those figures predate a ratification wave;
  at the audited commit the counts differ and CD.2/CD.6 are ratified. Re-derive every count from
  the tree; cite no figure you did not compute this session.
- **T4 -- supersession can be partial.** At least one pending CD is *narrowly* superseded (only
  one clause retired; the rest stays load-bearing). Do not recommend voiding a CD whose
  surviving clauses still bind. Classify clause-by-clause where the detail says so.
- **T5 -- the realization_evidence producer IS defined.** The ratification contract names the
  producer as "whoever notices (audit, /orient session, planning)." An empty feed is therefore a
  process/backlog state, NOT an undefined-ownership defect. Do not file "no owner exists"; if you
  find a defect here, it is about whether the producer role is *actionable* / *triggered*, not
  whether it is named.
- **T6 -- self-demotion is a third pattern.** One pending CD's detail demotes part of its own
  content ("illustrative, not canonical") via amendment without a state change and without
  another CD superseding it. This is neither prose-supersession-by-another-CD nor a state flip;
  count it as its own treatment when assessing S2's convention.
- **T7 -- CD.NN is not Decision NNN.** `candidate_decisions[]` entries (CD.NN, in
  `docs/ROADMAP-PLATFORM.yaml`) are a DIFFERENT artifact class from Decisions (`## Decision NNN`,
  in `docs/DECISIONS.md`). A ratified CD cross-references a Decision via `ratified_as: dec-NNN` /
  `filed_via: ops_decisions:dec-NNN`, but the two sets are distinct. THIS audit is the CD side
  only. Premise decay of DECISIONS.md entries is a separate, owned audit surface (see Section 13
  do-not-flag) -- do not walk DECISIONS.md entries as audit targets; read them only to verify a
  CD's cross-reference resolves.

## 4. SCOPE

In scope -- all three are built surfaces:

- **S1 -- the candidate_decisions[] set (all 40 entries, every state).** The pending set is the
  sharp risk (binding-while-stale). The ratified set is in scope for the INVERSE defect
  (ratified-but-detail-prose-stale, or a ratified-shape referential break). The single superseded
  entry is in scope as the reference exemplar of a correct transition.
- **S2 -- the supersession / state-transition marking convention.** The set of practices by which
  a CD whose premise changed is (or is not) reflected in the machine-readable `state` field.
  Includes: does any load-time guard / validator prevent a `detail` that records supersession
  from coexisting with `state: pending`?
- **S3 -- the ratification-lane discovery feed.** `ratifiable_cds()` and
  `realized_but_pending_cds()` and the `realization_evidence` field they read; whether the feed
  receives input by construction.

Out of scope (one line each):

- The ratification MECHANISM itself (how a CD transitions pending -> ratified) -- built and owned
  (Section 13). You assess the FEED into it and the PREMISES flowing through it, not the lane.
- DECISIONS.md entry premise decay -- separate owned surface (T7, Section 13).
- The trading product / alpha plane, and any tier_item's implementation status except where a CD
  gates it.
- Whether pending CDs SHOULD be binding at all -- the binding rule is deliberate design (Section
  13). You assess whether specific bindings carry stale premises, not the rule.

Trust-nothing clause: obtain every file, line, count, and identifier by reading the file. Trust
no number quoted in this prompt; re-derive from the repo. Record any anchor that does not resolve
in `meta.stale_anchors` and proceed with that fact downgraded to HYPOTHESIS.

Vocabulary you must use precisely:

- **CD.NN** -- a `candidate_decisions[]` entry. **Decision NNN / dec-NNN** -- a DECISIONS.md
  entry. **state** -- the enum field on a CD: `pending | ratified | superseded`.
- **binding** -- the roadmap rule that pending CDs must be obeyed by any agent reading the
  roadmap (re-read the rule; cite its line).
- **realization_evidence** -- structured free-text field on a CD asserting its gated work is
  realized/live; truthy value makes a pending CD eligible for the ratification lane.
- **ratified shape** -- the field combination a CD must carry once ratified: `state: ratified` +
  `ratified_as: dec-NNN` + `filed_via: ops_decisions:dec-NNN`, same 3-digit NNN in both.

## 5. SETUP

Run these read-only commands first. NEVER abort on failure -- take the named degraded path.

1. `git fetch origin main` then `git rev-parse --short origin/main`. This sha IS the audited
   tree; use it in the deliverable filenames, the branch name, and `meta.audited_commit`. If
   fetch fails (egress down): use `git rev-parse --short HEAD`, set
   `meta.contract_notes` to record that the base is local HEAD, proceed.
2. `bin/venv-python -m scripts.session_preflight --roadmap-detail full` -- populates
   `logs/.preflight-report.json` and refreshes `logs/.recommendations-log.jsonl`, the dedup
   caches Section 13 depends on. This regenerates gitignored local caches; that is expected and
   is not a write-boundary breach (never commit them).
   - IF this fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup = true`, mark
     every `roadmap_crossref` confidence HYPOTHESIS and every `dedup_hit_count` null, and proceed
     using direct `rg` over `logs/.recommendations-log.jsonl` if it exists, or skipping the
     rec-dedup pass entirely (recording that in `contract_notes`).
3. Confirm you can parse the roadmap:
   `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); print(len(d['candidate_decisions']))"`.
   If this errors, record it in `meta.contract_notes` and fall back to reading the YAML as text.

Repo-wide `validate.py` is advisory outside CI in this repo; do not run it as a gate. A clean
YAML parse of your two deliverables is the real pre-push check.

## 6. NORTH STAR

The ideal-state bar, as named principles the rubric (Section 8) references. Each is a bar you
JUDGE each surface against, not a rule you pattern-match -- argue the call.

- **NS-A -- a binding instruction set must be current.** An agent loading the roadmap must not be
  steered by a premise the CD's own text records as retired. A CD that binds while its detail
  says "superseded" is the failure this principle names -- but you must judge whether the
  surviving clauses still bind (T4) before convicting.
- **NS-B -- machine state is the source of truth; prose is not.** The system keys behavior on the
  `state` field, not on `detail` prose (an established principle here is that prose is not
  deliberate corroboration). A state transition that lives only in prose is invisible to every
  code path. Judge whether each premise change reached the field the code reads.
- **NS-C -- an empty-by-construction discovery surface is false assurance.** A feed with a named
  producer that never receives input looks healthy (no errors) while surfacing nothing. Judge
  whether the feed is empty because there is genuinely nothing to surface, or because the
  producing step is never triggered.
- **NS-D -- agent-first: collocate semantics with enforcement.** A convention that depends on
  author discipline (remember to flip state when you write "superseded") rather than a load-time
  guard is drift by design in this repo's stated philosophy. Judge whether S2's convention is
  enforced or merely intended.

## 7. THE QUESTIONS

Answer each as a first-class entry with its own slot in the output. Pinned verdict enums are
given per question.

- **Q1 -- Per-CD premise walk (all 40 CDs).** For every CD, classify its current premise state.
  Verdict enum per CD (the `pending_cd_disposition` block, Section 14):
  `pending-superseded-unmarked` | `pending-realized-unevidenced` | `pending-genuinely-open` |
  `ratified-sound` | `ratified-stale-prose` | `ratified-shape-defect` | `superseded-correct` |
  `other`. For each, give the evidence anchor, a one-line rationale, and a recommended
  disposition (what a human should do: flip state, add realization_evidence, strip stale prose,
  leave as-is, decide). The question-level verdict summarizes: is the pending set safe to load as
  binding today? Enum: `sufficient | partial | insufficient`.
- **Q2 -- The marking convention (S2).** Multiple treatments of a changed premise coexist:
  prose-amendment-with-no-state-change, formal `state` flip, and self-demotion within a pending
  CD (T1/T6). Is this coexistence a data-integrity defect on a binding surface? Should the
  convention REQUIRE that an amendment recording supersession flip `state` in the same edit, and
  should a load-time guard enforce it? Enum: `sufficient | partial | insufficient` (of the
  current convention).
- **Q3 -- CD.18 decision soundness.** The target is the CD promoted from KG.6 that requires a
  decision before a specific tier item and hinges on a git stash parked 2026-05-18; the composing
  session identified it as CD.18. Re-derive: locate the CD whose detail contains both "2026-05-18"
  and "stash" -- if that is not CD.18, the stash-bearing CD is the true target and you record the
  id discrepancy in `meta.contract_notes`; the pinned "CD.18" label does not override your
  re-derivation. Attempt to verify the stash empirically: `git stash list`, and search for the
  named branch (`git branch -a | rg 'ops-decisions-phase-2-semantic-definition'`). If the stash is
  not present in this
  clone (a stash is a machine-local ref, not committed), record that as an explicit unverifiable
  premise -- do NOT assume it exists or does not. Given the stash's host substrate is scheduled
  for teardown (re-derive which CD / tier item schedules it), and given a separate audit called
  ratifying this CD "zero-cost", is that characterization warranted? Enum:
  `sound | unsound-favor-revive | unsound-favor-void | cannot-decide-needs-empirical`. You
  ASSESS which option is safer and what evidence would settle it; you do NOT make the decision.
- **Q4 -- The empty feed (S3).** Re-derive: how many pending CDs carry truthy
  `realization_evidence` (feeds `ratifiable_cds()`)? How many carry a `[Realized` prose marker
  (feeds `realized_but_pending_cds()`)? If both are zero, is the feed empty because no pending CD
  is genuinely realized-yet-unratified, or because realized ones exist but no producer pass has
  marked them? (Cross-check against your Q1 `pending-realized-unevidenced` classifications --
  those ARE realized-but-unflagged CDs, if any.) Note that a ratification wave AFTER the lane went
  live (the ratified CDs now point at `dec-106`..`dec-118`; re-derive by reading their
  `ratified_as` fields, and note Decision 105 landed 2026-07-02) moved realized CDs OUT of
  pending; weigh whether "empty" means "healthy/drained" (realized CDs already ratified, nothing
  left to surface) or "producer never runs" (realized CDs remain in pending, unflagged). Attribute
  the root cause: `mechanism | process | ownership | not-a-defect`.
- **Q5 -- Questions the requester did not think to ask.** Answer AND extend. Seeds you must
  address, then add your own: (a) Do the 16 ratified CDs' `ratified_as`/`filed_via` cross-refs
  all resolve to real `## Decision NNN` headers, or is any ratified shape referentially broken?
  (b) Is there any CD that gates a live tier item via `completion_blocked_on_cd` whose premise
  you classified as superseded-unmarked -- i.e. a stale premise actively wedging real work? (c)
  Does the roadmap's self-contained-document invariant interact with any CD whose premise now
  lives only in a DECISIONS.md entry? (d) Note explicitly: the substantive premise decay of a
  *ratified* CD (as opposed to cosmetic `ratified-stale-prose`) is a conscious out-of-scope
  boundary here -- a ratified CD's live premise is owned by the Decision it filed as (T7). State
  in one line whether your walk nonetheless surfaced any ratified CD whose premise looks
  substantively false, as a pointer for the DECISIONS.md-side audit -- do not file it as a finding.

## 8. RUBRIC

Rate each dimension per surface (S1, S2, S3). Enum: `strong | adequate | weak | absent | n/a`.
`n/a` is correct and costless where a dimension does not structurally apply -- never manufacture
a rating or finding to fill a cell.

- **VD1 -- Premise currency** (S1): do the binding CDs' premises still hold at HEAD?
- **VD2 -- Supersession-marking integrity** (S1, S2): when a premise is retired, does the change
  reach the `state` field, or stall in prose?
- **VD3 -- State-transition enforcement** (S2): is the pending->ratified/superseded convention
  guarded at load time, or left to author discipline? Includes ratified-shape referential
  integrity.
- **VD4 -- Discovery-feed liveness** (S3): does the ratification lane actually receive input;
  is the producer step triggered?
- **VD5 -- Decision-input soundness** (S1): are CD premises safe to consume as decision input
  right now (esp. the CD.18 / CD.28-adjacent decisions other work is about to action)?

Every question is served by >=1 dimension; every dimension is referenced by >=1 question or
deep-dive.

## 9. DEEP-DIVES

- **DD-A -- The 40-CD premise walk (feeds Q1, Q2, Q5b).** For each CD read `detail` in full.
  Classify per Q1 enum. Adjudicate each premise against the post-May decision waves. These are
  named here with representative anchors you re-derive and extend -- do not treat the list as
  closed: (a) LLM-substrate wave -- CD.28 supersedes CD.7; (b) executor-substrate wave -- CD.27
  narrowly supersedes CD.11's Fargate clause; (c) ops-consolidation wave -- Decision 84 (Single
  Portal / DuckLake consolidation) and its downstream; (d) ratification-lane wave -- Decision 105
  (2026-07-02). Read each cited Decision/CD to confirm what it actually supersedes before relying
  on it, and surface any additional superseding Decision your walk finds. For
  a pending CD whose `detail` announces supersession by another CD, verify the superseding CD
  exists and check whether the supersession is full or partial (T4). Record, per CD, whether any
  live tier item gates on it (`completion_blocked_on_cd` referencing it) -- that is what makes a
  stale binding load-bearing rather than inert.
- **DD-B -- CD.18 stash and substrate (feeds Q3).** Trace the stash claim end-to-end: read the CD
  detail, attempt the empirical `git stash`/branch checks, identify the tier item the decision
  gates and the CD/tier item that schedules the host substrate's teardown. Lay out the decision
  as the CD frames it (revive vs void), the cost of each branch, and what single piece of
  evidence would make the call -- then give your Q3 verdict. Do not decide for the human.
- **DD-C -- The empty-feed root cause (feeds Q4, NS-C).** Read both feed functions and the
  `realization_evidence` field definition and its contract. Establish, at HEAD: the count feeding
  each function; whether the post-2026-07-02 ratification wave (ratified CDs now carrying
  `ratified_as: dec-106`..`dec-118`) drained realized CDs out of pending; and whether any pending
  CD you classified realized-but-unevidenced in Q1 SHOULD be feeding the lane but is not.
  Attribute the root cause per Q4 enum.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every entry is a POINTER: verify it by
reading the file before you rely on it; anchors rot and origin/main may have moved since drafting
-- record any non-resolving anchor in `meta.stale_anchors`. Facts are stated neutrally; the
verdict is yours.

Primary surfaces:

- `docs/ROADMAP-PLATFORM.yaml` -- `candidate_decisions[]` is the audit set. Near the top of the
  file (re-derive the line) is the rule that pending CDs "MUST still be treated as binding by any
  agent reading the roadmap". Tier items live later in the same file; some carry
  `completion_blocked_on_cd`.
- `scripts/platform_roadmap.py` -- `ratifiable_cds()` (returns pending CDs with truthy
  `realization_evidence`) and `realized_but_pending_cds()` (returns pending CDs whose `detail`
  contains a `[Realized` marker and which lack the structured field) are adjacent; the
  `CandidateDecision` model defines `realization_evidence: str | None`. Re-derive line numbers.
- `docs/contracts/candidate-decision-ratification.yaml` -- defines the canonical ratified shape,
  the `realization_evidence` surfacing signal and its producer ("whoever notices"), and the
  second lower-confidence `realized_but_pending` signal.
- `docs/DECISIONS.md` -- the Decision entries a ratified CD's `ratified_as`/`filed_via` point at;
  read only to verify cross-refs resolve (T7). The ratification-lane decision defines the lane
  and reconciled several CDs' cross-refs.
- `.claude/skills/orient/SKILL.md` -- documents how `/orient` consumes `ratifiable_cds` and
  `realized_but_pending_cds` from the preflight cache. Context for who READS the feed.

Observed facts to verify and adjudicate (neutral -- re-derive each):

- Some pending CDs' `detail` opens with an amendment line stating the CD is "fully" or "narrowly"
  superseded by another CD, while `state` remains `pending`. Identify every such CD yourself.
- One CD carries `state: superseded` with null `ratified_as`/`filed_via` -- the formal exemplar.
- One pending CD's `detail` states part of its content is "illustrative, not canonical" via a
  dated amendment, with no state change.
- At the audited commit, the count of pending CDs with truthy `realization_evidence` and the
  count with a `[Realized` prose marker are both worth re-deriving (the composing session
  observed both as zero; verify).
- The ratified CDs carry `ratified_as`/`filed_via` pointing at 3-digit Decision numbers; verify
  each target header exists in `docs/DECISIONS.md` or `docs/DECISIONS_ARCHIVE.md`.
- One pending CD (promoted from a KG entry) requires a decision before a specific tier item and
  references a git stash parked 2026-05-18 on a named branch.

## 11. EMPIRICAL PASS

The sample IS the closed set of candidate_decisions -- walk ALL of them (re-derive the count; the
composing session counted 40). Do NOT exceed the set; do NOT sample DECISIONS.md entries as audit
targets (T7). Reading a Decision to verify a single CD cross-ref is fine and expected.

Counterfactual applied per CD: *"If this CD were deleted from the roadmap today, would any agent
session behave differently, or would any live tier item lose a gate?"* A CD that binds but whose
deletion changes nothing is inert; a CD whose deletion would unblock or misdirect real work is
load-bearing. Use this to separate zombie bindings from live ones -- it drives severity.

`evidence_kind` tagging: `static` = derived from roadmap/contract text alone; `observed` = a gate
actually consumed by a live tier item, a Decision wave actually landed, a feed function actually
returning empty when run. At equal severity, an `observed` finding outranks a `static` one in
`top_improvements` ordering.

## 12. METHOD

Phases, in order:

- **P1 Read** -- Section 5 setup; read the roadmap `candidate_decisions[]` in full, both feed
  functions, the ratification contract, the binding rule.
- **P2 Trace** -- DD-A: classify all 40 CDs; record gating relationships.
- **P3 Deep-dive** -- DD-B (CD.18), DD-C (empty feed).
- **P4 Empirical** -- apply the per-CD counterfactual; tag evidence_kind.
- **P5 Rate** -- rubric VD1..VD5 per surface.
- **P6 Dedup** -- Section 13, before filing anything.
- **P7 Synthesize** -- answer Q1..Q5; assign severity (Section 15); compute maturity LAST.

## 13. DEDUP DISCIPLINE

Before filing ANY finding, grep the ownership surfaces and record the search terms + hit count on
the finding's `roadmap_crossref`. A hit means the territory is owned -> sufficiency assessment
(`planned-insufficient`/`planned-unbuilt`) or `rejected_candidates`, NEVER a fresh `novel`
discovery. A finding without a recorded negative search is a HYPOTHESIS, not CONFIRMED.

Ownership surfaces: `candidate_decisions[]` and `tier_items[]` in `docs/ROADMAP-PLATFORM.yaml`;
`## Decision` headers in `docs/DECISIONS.md`; `logs/.recommendations-log.jsonl` (open recs).

Deliberate constraints -- DO NOT FLAG (each with its owner):

- The ratification MECHANISM (pending -> ratified lane, canonical shape, referential guard) is
  built and owned -- Decision 105 + `docs/contracts/candidate-decision-ratification.yaml`. Do not
  file "there is no ratification lane". The unclosed-loops ULF-02 finding owned/closed the
  mechanism gap.
- CD.35's stale pre-ratification language in its detail is owned by an open rec (re-derive its id
  via a search for "CD.35" / "pre-ratification" in the recs log; the composing session saw
  rec-2287). Do not re-file CD.35 specifically. If you find the SAME stale-prose pattern on OTHER
  ratified CDs, that is potentially novel -- file it, deduped.
- Documenting the truthy-vs-None semantics of `realization_evidence` is owned by an open rec
  (composing session saw rec-2468). Hardening the ratification guard's `_dec_number` is owned
  (rec-2467). A specific `related_candidate_decisions` crossref extension to CD.40 is owned
  (rec-2511). Re-verify each; do not re-file.
- DECISIONS.md-entry premise decay (the DECISIONS.md side, not the CD side) is a separate audit
  candidate (CAND-01 in the audit-scope-discovery slate). Keep the boundary crisp (T7): CD-side
  premise decay is YOURS; Decision-entry decay is not.
- The two specific ratification NEXT-ACTIONS (ratify CD.18, ratify CD.28) as SCHEDULING items are
  owned by the platform-roadmap-mvp-triage audit. You assess their PREMISE soundness (Q3); you do
  not re-file the scheduling.
- The rule that pending CDs are binding (Section 4) is deliberate design -- do not flag it.

## 14. OUTPUT

Write exactly two files (create the `audits/` directory first if it does not already exist).
Re-derive `<sha>` (Section 5). `<slug>` = `pending-cd-premise-validity` everywhere.

- `audits/pending-cd-premise-validity-<sha>.yaml` -- the structured audit (schema below).
- `audits/pending-cd-premise-validity-<sha>.md` -- a companion report: the executive layer a human
  reads first (headline verdict per question, the load-bearing findings, the CD.18 call). The
  <= ~1500-word cap applies to the NARRATIVE PROSE only; you MAY append the per-CD disposition as
  a compact table (one terse row per CD -- id, classification, one-clause disposition) that does
  NOT count against the prose budget. The authoritative per-CD ledger is the YAML
  `pending_cd_disposition`; the table is a readable rendering of it.

YAML schema (pin every enum inline as shown; fill, do not restructure):

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text -- e.g. "Claude Opus 4.x">,
         methodology_version: 1,
         scope_surfaces: [candidate_decisions_set, marking_convention, ratification_feed],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q3, verdict: sound|unsound-favor-revive|unsound-favor-void|cannot-decide-needs-empirical,
       basis: [<finding ids>], prose: ""}
    - {q: Q4, verdict: mechanism|process|ownership|not-a-defect, basis: [<finding ids>], prose: ""}
    - {q: Q5, answers: [{question, answer, basis: [<finding ids>]}]}   # incl. seeds a/b/c + your own
  pending_cd_disposition:            # ONE entry per CD in candidate_decisions[] (all 40)
    - {cd: CD.NN, state: pending|ratified|superseded,
       classification: pending-superseded-unmarked|pending-realized-unevidenced|pending-genuinely-open|ratified-sound|ratified-stale-prose|ratified-shape-defect|superseded-correct|other,
       gates_live_item: true|false, evidence: "file:line", rationale: "",
       recommended_disposition: "", confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: candidate_decisions_set|marking_convention|ratification_feed,
       maturity: frontier|strong|solid|nascent, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface, dimension: VD1..VD5, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|CD.NN", note: ""}
  findings:
    - {id: PCD-01, surface: candidate_decisions_set|marking_convention|ratification_feed|shared,
       question: Q1..Q5, dimension: VD1..VD5, title,
       evidence: "file:line|CD.NN", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [finding or roadmap ids], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match, decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>,
            # each maturity_* value is one of: frontier|strong|solid|nascent (Section 15)
            maturity_candidate_decisions_set: frontier|strong|solid|nascent,
            maturity_marking_convention: frontier|strong|solid|nascent,
            maturity_ratification_feed: frontier|strong|solid|nascent}
```

Invariants (state and obey):

- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) =
  novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered candidates live
  in `rejected_candidates[]`, NOT findings. `pending_cd_disposition`, `rubric_ratings`, and
  `question_answers` are systems-of-record referenced FROM findings, never re-counted into
  `total_findings`. `top_improvements` and `highest_leverage_change` MUST be finding ids.
- `pending_cd_disposition` has exactly one entry per CD (re-derive the count); it is a
  classification ledger, not a findings list -- a CD classified `ratified-sound` needs no finding.
- `control_property_match` is REQUIRED whenever a compensating control is the dismissal reason:
  name the property the control exercises, cite where it operates, and state why it would FAIL if
  the defect were real.
- CONFIRMED requires the behavior traced to file:line or an observed artifact; else HYPOTHESIS.

## 15. SEVERITY + MATURITY

Severity assigned AFTER judgment, by defect class, never inherited from this prompt's framing:

- **critical** = a stale-but-binding CD can cause an agent session to take a wrong, trusted
  action right now (e.g. a superseded-unmarked premise that gates a live tier item and would
  misdirect its execution), or a decision about to be actioned rests on an unsound CD premise.
- **high** = a weakness that materially reduces the integrity of the binding set AND whose
  compensating controls you judged insufficient (e.g. a systemic marking-convention gap with no
  load-time guard, where discipline demonstrably failed on >=1 CD).
- **medium** = redundancy / ambiguity / inconsistency with a clear fix (e.g. one stale-prose
  ratified CD; a feed that is empty-but-harmless with a cheap producer trigger).
- **low** = clarity / wording.

Compensating-control rule (property-match): a control lowers severity or dismisses a candidate
ONLY if it exercises the SAME property the defect would break AND would itself FAIL if the defect
were real (apply the counterfactual to the control). A control that cannot catch the break neither
lowers severity nor justifies dismissal. Example: "agents re-read the CD each session" does NOT
property-match a stale-premise defect -- re-reading stale text propagates the staleness, it does
not catch it.

Maturity -- compute LAST, per surface, top-down, first match wins (evaluate the four predicates in
this order; the first that holds is the rating). Count only OPEN findings on that surface. Pin
these thresholds (they are mutually exclusive under first-match-wins -- do not re-interpret):

- **frontier** = 0 critical AND 0 high.
- **strong** = 0 critical AND exactly 1 high.
- **solid** = at most 1 critical AND at most 2 high.
- **nascent** = otherwise (>= 2 critical, OR >= 3 high).

Worked examples to remove doubt: 0 critical / 2 high -> `solid` (fails frontier and strong, meets
solid's <=1 critical and <=2 high). 1 critical / 0 high -> `solid`. 0 critical / 3 high ->
`nascent`. 2 critical / 0 high -> `nascent`.

The top rating remains reachable if you argued a property-matched compensating control that
dismisses what would otherwise be a critical/high -- the framing here must not foreclose it.

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE (Section 5 step 1). That sha is the audited tree; use it in filenames,
   branch, and `meta.audited_commit`.
2. `git switch -c audit/pending-cd-premise-validity-<sha> origin/main` so the PR diff is only your
   two deliverables. This is a deliberate, documented exception to the `claude/*` session-branch
   rule: the audit session needs a clean two-file diff off the audited base. IF Section 5 step 1's
   `git fetch origin main` failed and you fell back to local HEAD, branch off `HEAD` instead of
   `origin/main` (`git switch -c audit/pending-cd-premise-validity-<sha> HEAD`) -- the branch base
   MUST equal the sha you recorded in `meta.audited_commit`, never a ref that disagrees with it.
3. Repo-wide validation is advisory outside CI; a clean YAML parse of both deliverables is the
   real pre-push gate. If an unrelated `validate --pre` failure appears, record it in
   `meta.contract_notes` -- never fix it (write boundary).
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign`
   (signing is unavailable in this harness; unsigned is expected). Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, NOT draft),
   title `audit: pending-CD premise validity (candidate_decisions set + ratification-lane feed)`,
   body = a 2-3 sentence lede + the `summary:` block in a yaml fence. Then END THE TURN -- do not
   poll, do not merge, do not subscribe, do not self-approve. The human disposes of the PR.

## 17. GUARDRAILS

- Write boundary (closed list): the ONLY repository files you create or modify are
  `audits/pending-cd-premise-validity-<sha>.yaml` and `audits/pending-cd-premise-validity-<sha>.md`.
  Regenerating gitignored caches per Section 5 is allowed; committing them is not. You do NOT edit
  `docs/ROADMAP-PLATFORM.yaml`, do NOT flip any CD state, do NOT ratify anything, do NOT file a
  recommendation.
- Precision over volume. Fewer than ~6 surviving findings is a valid result -- state it plainly;
  do not pad. The `pending_cd_disposition` ledger will be large (one row per CD) BY DESIGN -- that
  is a classification, not padding; keep the FINDINGS list lean and load-bearing.
- A run that merely restates the candidate observations in Section 2 has failed. Every finding
  must survive its counterfactual (Section 11) and its dedup search (Section 13).
- If an anchor does not resolve, record it in `meta.stale_anchors` and downgrade that item to
  HYPOTHESIS -- never invent, never abort.
