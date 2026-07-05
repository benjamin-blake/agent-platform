# Audit: pending-CD premise validity and the ratification-lane feed

Audited commit: `f4dec93` (origin/main == local HEAD). Companion to
`audits/pending-cd-premise-validity-f4dec93.yaml` (the authoritative per-CD ledger and
finding records). Counts re-derived this session: 40 candidate decisions = 23 pending +
16 ratified + 1 superseded. Both feed functions and the referential guard were executed
live. Five findings survived dedup: 4 novel, 1 planned-insufficient; 0 critical, 0 high.
All three surfaces rate **frontier** under the pinned maturity predicates -- which here
means "no critical/high defect," not "nothing to do."

## Headline verdicts

**Q1 -- per-CD premise walk: `partial`.** No pending CD misdirects a live trusted action
today, but 8 of the 23 pending entries are not genuinely open decisions. CD.7 is fully
superseded in prose (by CD.28) with state still `pending` -- benign, because its dated
amendment is the first thing in its detail and its gates were emptied, so the counterfactual
deletion changes nothing. CD.19 is the sharpest defect: its decision window ("required
BEFORE T2.2 begins") closed when T2.2 completed 2026-05-29, the recorded de facto timestamp
policy ("original ids and timestamps preserved") diverges from the CD's recommended option
(c), and the CD was never rescoped -- it still binds, still gates T1.6, and would misdirect
the next T1.6 planning session (PCD-02). Six more pending CDs are realized but carry no
`realization_evidence`: CD.39 (its exit-criteria ledger is built, validate.py-enforced, and
in daily use), CD.9 (substance ratified by proxy via Decisions 78/81, per T2.4's own note),
CD.5 (T0.10's note literally says "CD.5 ratifies post-hoc"), CD.4, CD.28 (retirement work
observably executed; its pending state now wedges in_progress T0.4's completion), and CD.8.
The 16 ratified CDs are referentially sound -- the R1/R2/R3 guard passed live with all 15
distinct `dec-NNN` targets resolving -- with three carrying cosmetic pre-ratification prose
(two already owned by open recs). CD.14 is the correct-transition exemplar.

**Q2 -- the marking convention: `partial`.** Three treatments coexist, and the evidence
says they are more principled than they look: full supersession by a *ratified* authority
flips state (CD.14); full supersession by a *still-pending* candidate is held in prose with
gates emptied (CD.7); partial supersession and self-demotion correctly never flip (CD.11,
CD.10 -- surviving clauses bind). The defect is enforcement, not taxonomy. The load-time
guard enforces only the ratified *shape*; nothing validates the `state` value itself
(PCD-04: it is a free string that would silently drop a typo'd CD out of the binding set,
both feeds, and the guard); nothing couples supersession prose to state; and -- the sharp
edge -- nothing fires the held CD.7 flip when CD.28 ratifies (PCD-03). The convention
should require the flip *when the superseding authority becomes decision-final*, enforced
by a guard on exactly that conjunction. Requiring a flip at amendment time regardless would
be wrong per the CD.14/CD.7 asymmetry.

**Q3 -- CD.18: `unsound-favor-void`.** Target re-derived: CD.18 is the only CD containing
"2026-05-18" and "stash" -- no id discrepancy. Empirics: the stash is absent from this
clone (machine-local ref, as expected) and the branch
`agent/ops-decisions-phase-2-semantic-definition` does not exist on origin -- so the work
survives, if at all, only on the pre-CC-web Windows host whose decommission T5.1 schedules
(not_started; teardown scheduled, not imminent). The mvp-triage audit's "ratifying CD.18
early is a zero-cost unblock" prices the ratification *act* and assumes away the decision
*content*. It is only zero-cost if option (b) void is chosen; option (a) revive rests on an
unverifiable premise. The evidence favors void: the stashed WIP targets a surface
superseded twice over (CD.10 dismantles ops_data_portal as agent surface; Decision 84 moved
writes to the DuckLake boundary), and `scripts/executor/rec_write_guidance.py` now exists
in tree, independently evolved. The one piece of evidence that would settle it: `git stash
list` on the 2026-05-18 host, done opportunistically before T5.1 -- minutes of effort, not
worth blocking on. The human decides; this audit only ranks the branches.

**Q4 -- the empty feed: `process`.** Both counts are zero, observed live. Empty is *not*
"healthy/drained": the 2026-07-02/03 Decision-105 wave (dec-106..dec-113, dec-118) drained
exactly the CDs that carried prose markers or drafted evidence at lane creation, and the
Q1 walk shows six realized pending CDs left behind, none marked. The mechanism is fine
(functions correct, guard green, lane demonstrated end-to-end); the producer is named
("whoever notices"); what is missing is a trigger. /orient -- the recurring surface -- is
read-only and *explicitly forbidden* from surfacing plausibly-realized CDs without the
field; /plan is item-scoped; audits are ad-hoc; T-1.1 built the lane, ran the first batch,
and is complete. Meanwhile the scope-(c) exemption ledger already records machine-readably
which pending CDs owe post-hoc ratification. Two surfaces hold the same fact with no
linkage -- that is PCD-01, the highest-leverage change: a deterministic
realization-candidate pass in preflight (gated-items-complete OR scope-(c)-noted), surfaced
to /orient as "candidates for evidence-writing in a /plan session," keeping the Decision 55
epistemic split intact.

**Q5 -- unasked questions.** (a) All ratified cross-refs resolve; guard PASS observed.
(b) No superseded-unmarked CD gates live work; the nearest case is CD.19's prospective
wedge on not_started T1.6. (c) Self-containment holds; one locus gap -- CD.9's
decided-by-proxy status is recorded on T2.4 and in DECISIONS.md but not in CD.9's own
entry. (d) No ratified CD carries a substantively false live premise; CD.34's falsified
"blast radius zero" framing is already self-bracketed as contradicted -- exemplary.
(e) No unreleased static reference: gates compute live off `state == "pending"`; the one
CD.14 reference is annotated-released; the exemption flags were actively swept when their
terminating CDs ratified, under an explicit strip-safety rule. Own additions: the
`filed_via: pending_log_decision_lambda` placeholder on 9 pending CDs is guard-legal but
names a never-deployed vehicle (cosmetic); and the pending set is structurally bimodal --
roughly 9 forward-intent CDs correctly pending under Decision 105's evidence rule vs. the
realized ratification debt above -- so the raw pending count overstates open decision load.

## Findings (all medium/low; none block current work)

| id | sev | one-line |
|----|-----|----------|
| PCD-01 | medium | Realized-but-unevidenced CDs invisible to the lane: producer step has no recurring trigger; exemption-ledger debt never flows into `realization_evidence` |
| PCD-02 | medium | CD.19 binds on an overtaken premise (window closed at T2.2 completion; de facto policy diverged from recommendation; never rescoped) |
| PCD-03 | medium | No mechanism flips CD.7 to `superseded` when CD.28 ratifies; no guard on the pending+fully-superseded-by-ratified conjunction |
| PCD-04 | medium | `CandidateDecision.state` is an unvalidated free string; unknown values silently bypass the guard and every state-keyed surface |
| PCD-05 | low | No prose-currency sweep at ratification flip or gated-item completion; pending-tense text recurs (CD.33 unowned; CD.35/CD.31 owned; CD.29 gate-status note stale) |

Dismissed with owners named (see `rejected_candidates`): the lane mechanism itself
(Decision 105 / T-1.1), CD.35 prose (rec-2287), CD.31 prose (rec-2048), evidence-field
semantics (rec-2468), guard regex (rec-2467), CD.40 crossref (rec-2511), CD.18/CD.28
ratification scheduling (mvp-triage audit), producer *ownership* (named in the contract;
the trigger gap is the finding), the binding rule itself (deliberate design), and the
exemption flags (actively maintained -- verified discharge records).

## What a human should action, in order

1. **PCD-01** -- add the deterministic realization-candidate pass; then write evidence for
   CD.39, CD.9, CD.5, CD.4 (+ CD.8, CD.28 as scoped) and let the lane drain them.
2. **CD.28 / CD.18** -- already queued by mvp-triage; for CD.18 decide void unless a
   five-minute stash check on the old host says otherwise (before T5.1).
3. **PCD-02** -- one dated amendment rescoping CD.19 to the T1.6 freshness residue,
   recording the de facto import outcome.
4. **PCD-03 + PCD-04** -- small guard hardenings; land PCD-03 *before* CD.28 ratifies so
   the CD.7 flip is mechanical; PCD-04 can ride with rec-2467.
5. **PCD-05** -- one sentence in the lane contract's flip step; sweep CD.33/CD.29 text
   alongside rec-2287/rec-2048.

## Per-CD disposition (rendering of the YAML ledger; YAML is authoritative)

| CD | state | classification | disposition |
|----|-------|----------------|-------------|
| CD.1 | ratified | ratified-sound | leave |
| CD.2 | ratified | ratified-sound | leave |
| CD.3 | pending | pending-genuinely-open | leave; revisit when T2.6 reactivates |
| CD.4 | pending | pending-realized-unevidenced | write evidence; ratify via lane |
| CD.5 | pending | pending-realized-unevidenced | write evidence; ratify (discharges T0.10 flag) |
| CD.6 | ratified | ratified-sound | leave |
| CD.7 | pending | pending-superseded-unmarked | flip to superseded in the same edit that ratifies CD.28 (PCD-03) |
| CD.8 | pending | pending-realized-unevidenced | evidence scoped to realized engine choice; ratify necessary-not-sufficient |
| CD.9 | pending | pending-realized-unevidenced | evidence citing dec-078/081; carry proxy-ratification fact into entry |
| CD.10 | pending | pending-genuinely-open | leave; rescope detail at ratification (silent-completion near) |
| CD.11 | pending | pending-genuinely-open | leave; narrow supersession correctly recorded; never flip while surviving clause binds |
| CD.12 | pending | pending-genuinely-open | leave until T1.6 (half realized) |
| CD.13 | ratified | ratified-sound | leave |
| CD.14 | superseded | superseded-correct | leave; the transition template |
| CD.15 | pending | pending-genuinely-open | leave; rescope to DuckLake-era read contract at ratification |
| CD.16 | ratified | ratified-sound | leave |
| CD.17 | pending | pending-genuinely-open | leave; correctly pending until reversal trigger |
| CD.18 | pending | pending-genuinely-open | ratify with void unless host stash check rescues content (Q3) |
| CD.19 | pending | other (overtaken-by-events) | rescope to T1.6 residue; record de facto import policy (PCD-02) |
| CD.20 | ratified | ratified-sound | leave |
| CD.21 | ratified | ratified-sound | leave |
| CD.22 | ratified | ratified-sound | leave |
| CD.23 | pending | pending-genuinely-open | leave; inert (gates deferred T2.11b) |
| CD.24 | ratified | ratified-sound | leave |
| CD.25 | ratified | ratified-sound | leave |
| CD.26 | ratified | ratified-sound | leave |
| CD.27 | pending | pending-genuinely-open | leave until T4 begins |
| CD.28 | pending | pending-realized-unevidenced | write evidence; ratify (unwedges T0.4; scheduling owned by mvp-triage) |
| CD.29 | pending | pending-genuinely-open | leave; refresh stale gate-status note (PCD-05) |
| CD.30 | pending | pending-genuinely-open | leave |
| CD.31 | ratified | ratified-stale-prose | sweep prose with rec-2048 |
| CD.32 | pending | pending-genuinely-open | leave (rec-2060 owns enforcement_mechanism) |
| CD.33 | ratified | ratified-stale-prose | sweep pending-tense prose (PCD-05) |
| CD.34 | ratified | ratified-sound | leave; self-bracketing is the pattern to copy |
| CD.35 | ratified | ratified-stale-prose | action rec-2287; do not re-file |
| CD.36 | ratified | ratified-sound | leave |
| CD.37 | pending | pending-genuinely-open | leave; inert by design under freeze |
| CD.38 | pending | pending-genuinely-open | leave; inert by design under freeze |
| CD.39 | pending | pending-realized-unevidenced | write evidence; ratify -- mechanism fully built and enforced |
| CD.40 | pending | pending-genuinely-open | leave; the self-documenting correct-pending exemplar |
