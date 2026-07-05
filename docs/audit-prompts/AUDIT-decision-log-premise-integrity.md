# AUDIT: docs/DECISIONS.md premise integrity + supersession/keyspace sweep

You are a senior architecture reviewer. Execute this audit exactly as written in a fresh
session. It is self-contained: do NOT ask clarifying questions, and do NOT read any file that
tells you how to run an audit. Trust nothing quoted here as fact until you have re-derived it
from the repository at HEAD.

---

## 1. TASK

Audit the live decision log `docs/DECISIONS.md` as a GOVERNANCE SURFACE -- the binding decision
record that a planning subagent (`decision-scout`) loads in full and classifies against every
proposed plan. Assess it on three integrity axes:

- PREMISE LIVENESS -- does each Decided entry's grounding premise still hold at HEAD, or is it
  dead (its named substrate/artifact retired, or its stated rule inverted by a later Decision)
  with no supersession annotation?
- SUPERSESSION-ANNOTATION CONTROL -- when a later Decision invalidates an earlier one, does the
  earlier ("victim") entry carry a discoverable forward pointer? Is the practice a controlled
  invariant or ad hoc?
- WAREHOUSE-ID KEYSPACE -- do the in-file `**Warehouse ID:** dec-NNN` lines form a coherent
  keyspace under the canonical number-keying that Decision 105 established, or are there
  collisions and retired-scheme residue that hazard the DECISIONS.md -> `ops_decisions` ETL?

Answer questions Q1..Q6 (Section 7). Produce exactly TWO deliverables under `audits/` (Section
14): a findings YAML and a companion report. The ONLY files you create or modify in the
repository tree are those two. You DRAFT; the human DISPOSES -- you edit no audited surface, you
re-file no existing recommendation, you move no entry. Regenerating gitignored local caches per
Section 5 is expected and is not a tree modification (never commit them).

---

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you NO verdicts. Every candidate
in Section 10 is a lead to adjudicate, not a defect to confirm.

ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the
candidates below has failed. Several candidates may survive tracing as non-defects (e.g. an
entry co-cited alongside its own superseder may be adequately contextualized; an id mismatch may
be cosmetic if nothing keys on it). Convict only on traced evidence.

Adjudicate each candidate to one of these outcomes, and map it to the output as follows:
- CONFIRMED defect traced to file:line -> `findings[]`, `roadmap_crossref.classification: novel`.
- Real gap whose owning rec/item exists but whose remedy is a point-fix insufficient for the
  systemic issue, or is unbuilt -> `findings[]`, classification `planned-insufficient` /
  `planned-unbuilt`.
- Gap fully covered by an existing owned rec/item -> `rejected_candidates[]` (name the owner).
- Not a defect -> `rejected_candidates[]`, naming the compensating control and why it holds.

Severity is NEVER inherited from this prompt's framing or ordering. Assign it after judgment
(Section 15).

---

## 3. READ FIRST -- disambiguation traps

Each names a two-things-one-name hazard or a plausible-but-wrong target. Internalize before
tracing.

- TRAP-1 (Decision 26 in two files). A `## Decision 26:` header exists in BOTH
  `docs/DECISIONS.md` (the live audit target) AND `docs/DECISIONS_ARCHIVE.md`. They have
  different titles and statuses. Do not treat them as one entry, do not silently double-count,
  and adjudicate whether the live/archive coexistence is itself a defect.
- TRAP-2 (three different "warehouse id" surfaces). The audit target is the in-file
  `**Warehouse ID:** dec-NNN` line inside `docs/DECISIONS.md` ONLY. It is DISTINCT from (a) the
  `filed_via: ops_decisions:dec-NNN` / `ratified_as` fields on `candidate_decisions[]` in
  `docs/ROADMAP-PLATFORM.yaml` (the "CD side", already reconciled by Decision 105 -- OUT OF
  SCOPE to re-fix), and (b) the actual `ops_decisions` warehouse rows (a gitignored cache).
- TRAP-3 (dec-081 is claimed twice). `dec-081` appears as the in-file Warehouse ID line of
  Decision 75, while the canonical owner of `dec-081` under number-keying is Decision 81 -- whose
  OWN in-file line reads a different, also-non-canonical value. Do not infer "dec-081 = Decision
  81" from the in-file lines; derive the canonical mapping from the number-keying rule and
  Decision 105's reconciliation text, then compare.
- TRAP-4 (three annotation shapes). Supersession/decay is marked in at least three ways: in the
  HEADER (`(Supersedes Decision NN)`), in a mid-body `> **... migration update:**` blockquote,
  or in the archive via a header `(Superseded by Decision NN)`. The CONTROL question (Q2) is
  whether the VICTIM (the invalidated entry) carries a pointer -- not whether the superseder
  names its target.
- TRAP-5 (archive is context, not sweep target). `docs/DECISIONS_ARCHIVE.md` is the keyspace and
  duplicate-detection peer. Enumerate its headers for the keyspace and duplicate checks (Q3,
  TRAP-1), but the PREMISE SWEEP (Q1) applies to the LIVE `docs/DECISIONS.md` set only. The one
  exception: an entry that is live but archive-eligible is in scope for Q4.
- TRAP-6 (count vs number). The live-header COUNT is not the max decision NUMBER (numbering has
  gaps, and archived numbers are absent). Any count quoted anywhere -- including a "currently N"
  figure inside a skill file -- is re-derive-only; trust none.

---

## 4. SCOPE

SURFACE (single, built): `docs/DECISIONS.md` -- the live decision log at HEAD. One markdown file,
`## Decision NNN: <title> (<status>)` headers, each followed by a prose body and (for recent
entries) a `**Warehouse ID:** dec-NNN` line.

CONTEXT-ONLY surfaces (read to adjudicate; do NOT audit or recommend changes to):
- `docs/DECISIONS_ARCHIVE.md` -- keyspace/duplicate peer (TRAP-5).
- `docs/ROADMAP-PLATFORM.yaml` `candidate_decisions[]` -- the CD side; Decision 105 already
  reconciled its `filed_via` pointers (TRAP-2).
- `.claude/skills/decision-scout/SKILL.md` -- the consumer that loads DECISIONS.md in full as
  binding plan context.
- `scripts/checks/roadmap/validate_candidate_decision_ratification.py` -- the only existing
  validate.py check that parses `## Decision` headers; the candidate home for any control you
  recommend (Q2).
- `scripts/decisions_md.py` -- an in-repo parser of the file, if present.

VOCABULARY:
- Live entry: a `## Decision` section in `docs/DECISIONS.md` (not the archive).
- Premise: the factual/architectural condition an entry's Decision rests on (a named substrate,
  tool, artifact path, or a rule asserted by an earlier Decision).
- Dead premise: the premise's named substrate/artifact is retired or deleted at HEAD, or its
  asserted rule is inverted/superseded by a later Decision.
- Supersession annotation: any in-entry marker on the VICTIM pointing forward to the Decision
  (or CD/roadmap change) that invalidated or amended it.
- Canonical number-keying: `dec-NNN` where `NNN` is the zero-padded decision number, one rule for
  all entries (stated on recent entries' Warehouse ID lines and in Decision 84 / Decision 105).
- Watershed Decisions (premise-shifting waves; use to prioritize, NOT to skip): Decision 77
  (sandbox auto-apply), Decision 84 (DuckLake sole ops backend / keyspace), Decision 105
  (ratification lane + CD-side keyspace reconciliation), Decisions 116/117 (provider routing /
  executor-boundary supersessions), CD.28 (Bedrock retired). Entries authored before these waves
  are likelier to carry dead premises.

OUT OF SCOPE (one line each; do not opine):
- The prose-monolith FORMAT of DECISIONS.md (whether it should be structured/warehouse-native) --
  a separate audit owns it.
- The premise validity of `candidate_decisions[]` (pending CDs) in ROADMAP-PLATFORM.yaml.
- The platform-first sequencing directive.
- decision-scout's existence, size cost, or truncation risk.

TRUST-NOTHING: obtain every file/line/count/id by reading the repository at HEAD. Trust no
number, anchor, or mapping quoted in this prompt. Re-derive each; record any anchor that does not
resolve, or any repo state that has diverged from a claim here, in `meta.stale_anchors`.

---

## 5. SETUP

Permitted setup, run once at start:

1. `git fetch origin main` then `git rev-parse --short origin/main` -- this short sha IS the
   audited base; use it in deliverable filenames, the branch name, and `meta.audited_commit`.
2. `git switch -c audit/decision-log-premise-integrity-<sha> origin/main` (Section 16).
3. Generate the dedup caches (needed for Section 13):
   `bin/venv-python -m scripts.session_preflight --roadmap-detail full`
   This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl` (the
   recommendations read cache). These are gitignored; regenerating them is not a tree edit.

DEGRADED PATHS (never abort; set the flag, downgrade, proceed):
- IF cache-gen fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`, mark
  every finding's `roadmap_crossref` with `dedup_hit_count: null` and confidence `HYPOTHESIS`
  for the dedup dimension, and proceed using whatever static grep over `docs/` you can run.
- IF `git fetch` fails: use the local `origin/main` ref; note it in `meta.contract_notes`.
- IF an anchor in this prompt does not resolve: record it in `meta.stale_anchors` and continue
  from the repository truth, never from the prompt's claim.

---

## 6. NORTH STAR

The ideal-state bar, as named principles the rubric references. Principles marked JUDGE are bars
you argue each entry against -- not patterns to match mechanically.

- NS-A (premise integrity, JUDGE): a binding governance surface contains no live entry whose
  grounding premise is dead AND unmarked -- a reader can trust every live premise, or see it
  explicitly annotated as superseded/amended. A dead premise that is annotated is NOT a defect
  against NS-A; an entry co-cited with its superseder such that a reader cannot be misled may
  satisfy NS-A -- you decide.
- NS-B (supersession is first-class): when a Decision invalidates or amends another, the victim
  carries a discoverable forward pointer, produced by a controlled practice rather than ad hoc
  memory.
- NS-C (keyspace coherence): every entry's identifier resolves deterministically to exactly one
  decision under exactly one canonical rule -- no collisions, no residue of a retired scheme,
  ETL-safe.
- NS-D (bounded live surface, JUDGE): the live set a consumer loads holds only entries that still
  govern; resolved/superseded/archive-eligible entries are moved out, keeping the binding surface
  minimal. Whether a given resolved-but-still-referenced entry should stay live is a judgment.
- NS-E (agent-first record): the record is optimized for reliable agent consumption -- machine-
  checkable structure where a human-memory practice would otherwise drift.

---

## 7. THE QUESTIONS

Answer each as a first-class entry in `question_answers[]`. Pin the verdict enum shown.

- Q1 -- PREMISE INTEGRITY. Enumerate EVERY live entry in `docs/DECISIONS.md`. Apply the Section
  11 counterfactual to each. Classify each into exactly one of:
  `premise-live | dead-but-annotated | dead-unannotated | archive-eligible | indeterminate`.
  Report the full classified enumeration in the report (a compact table) and the counts in the
  YAML answer's prose. Verdict enum: `sound | localized-drift | systemic-drift`.
- Q2 -- SUPERSESSION-ANNOTATION CONTROL. Is the absence of a mechanical invariant (a superseding
  Decision MUST leave a forward pointer on its victim, checkable in the validate.py referential-
  guard family) a real gap, given the ad-hoc practice observed on some entries? If you judge it a
  gap, your finding MUST specify the invariant concretely: its rule, where it would live
  (`scripts/checks/...`), its inputs, and a machine-checkable `acceptance` command -- but you
  write NO code; the specification is the deliverable. Verdict enum: `sufficient | partial |
  insufficient`.
- Q3 -- WAREHOUSE-ID KEYSPACE. Derive the canonical number-keying rule. Verify EVERY in-file
  `**Warehouse ID:** dec-NNN` line against it. Identify collisions (one id claimed by two
  entries), retired-scheme residue (ids not matching the number rule), and missing lines on
  entries that should carry one. Judge whether this hazards the DECISIONS.md -> `ops_decisions`
  backfill ETL. Verdict enum: `coherent | cosmetic-drift | keyspace-hazard`.
- Q4 -- LIFECYCLE / STATUS HYGIENE. Enumerate every non-`(Decided)` header status and every
  unresolved lifecycle marker (e.g. "pending review", "Deferred", "Partially Active"). Assess
  archive-eligibility against the repository's stated archival policy (find where it is stated and
  whether an enforcer exists). RECOMMEND specific archive moves and status resolutions (the human
  disposes; you move nothing). Verdict enum: `sufficient | partial | insufficient`.
- Q5 -- CONVENTION CONFORMANCE (EXTERNAL CHECKLIST). Rate `docs/DECISIONS.md` against established
  decision-record conventions. Assess EACH property met | partial | missed, property-by-property,
  in this question's `external_checklist`. This field is the SOLE source the maturity top tier
  reads. The checklist:
  - `status-lifecycle`: entries carry a status from a closed, resolvable set (no perpetual
    "pending review").
  - `immutability-with-supersession-links`: superseded entries are retained and linked forward,
    not silently mutated or dropped.
  - `stable-unique-identifiers`: each entry has one stable, collision-free identifier.
  - `single-writer-numbering-authority`: decision numbers are allocated by one authority without
    parallel-branch collisions.
  - `supersession-bidirectionality`: both superseder->victim and victim->superseder directions are
    discoverable.
  A `partial` requires you to name, in the evidence, a property-matched compensating control (one
  that exercises the property and would fail if the gap were real).
- Q6 -- QUESTIONS THE REQUESTER DID NOT THINK TO ASK. Answer AND extend these seeds:
  - Does the DECISIONS.md -> `ops_decisions` backfill silently tolerate a duplicate or colliding
    `dec-NNN` (last-writer-wins), so a keyspace defect is invisible downstream? Trace the ETL
    entry point named on the Warehouse ID lines.
  - Are there live entries whose premise is not dead but whose CONCLUSION was quietly reversed by
    a later Decision without either entry annotating the other (a "silent overturn")?
  - Does any live entry cite, as a live constraint, another entry that is itself archived or
    superseded (a stale transitive citation)?
  Add any further question a thorough reviewer would raise, with its answer.

---

## 8. RUBRIC

Rate each dimension for the single surface `decisions_md`. Enum: `strong | adequate | weak |
absent | n/a`. `n/a` is correct and costless where a dimension does not structurally apply --
never manufacture a rating.

- VD1 Premise liveness (serves Q1, NS-A): proportion of the live set with live-or-annotated
  premises.
- VD2 Supersession discoverability (serves Q2, NS-B): can a reader of a victim entry find its
  superseder?
- VD3 Identifier coherence (serves Q3, NS-C): keyspace determinism and collision-freedom.
- VD4 Lifecycle/status hygiene (serves Q4, NS-D): status resolvability and boundedness of the
  live set.
- VD5 Convention conformance (serves Q5, NS-E): conformance to the external checklist.

---

## 9. DEEP-DIVES

- DD-A (feeds Q1) -- The four seed entries in CO-1..CO-3 (Decisions 26, 35, 37, 40). For each,
  trace: (i) the named premise; (ii) whether the named substrate/artifact/rule exists or was
  retired at HEAD, and by which Decision/commit; (iii) whether the entry carries any annotation;
  (iv) whether any LIVE surface (AGENTS.md, a skill, a contract) still cites the entry as binding,
  which would raise the stakes from "stale record" to "steers live work". State each seed's
  classification and whether it survives as a defect.
- DD-B (feeds Q3) -- The keyspace. Build the full map {decision number -> in-file dec-NNN line
  value} for every entry that carries a line. Cross it against Decision 105's reconciliation text
  and the number-keying rule. Enumerate: collisions, 4-digit residue, missing lines, and any id
  that resolves to a different decision than its host. Then trace the backfill consumer (Q6 seed
  1) to judge downstream impact.
- DD-C (feeds Q2, Q5) -- The annotation practice. Sample the entries you find to be superseded or
  amended and record, for each, which of the three annotation shapes (TRAP-4) it uses or whether
  it has none. From the distribution, judge whether the practice is controlled or ad hoc, and
  specify the invariant that would make it controlled.

---

## 10. GROUNDING MAP

This map spends your cognition on JUDGMENT, not grep. Every anchor is re-derive-before-relying:
open the file, confirm the line says what is claimed, and record any drift in `meta.stale_anchors`.
Facts are stated neutrally; the verdict is yours.

Structural (re-derive counts; do not trust these numbers):
- `docs/DECISIONS.md` -- ~81 live `## Decision` headers at the time this prompt was written;
  ~271KB. `docs/DECISIONS_ARCHIVE.md` -- ~18 archived `## Decision` headers plus a
  non-decision "Decision-Making Process" section.
- Recent entries carry `**Warehouse ID:** dec-NNN (keyed on the decision number; synced to
  ops_decisions via ops_data_portal --backfill-decisions-md ...)`. Entries in the dec-086..dec-121
  band follow the 3-digit number rule; a lower band carries 4-digit `dec-1xxx` values.

Candidate seed anchors (adjudicate, do not assume defect):
- Decision 26 @ `docs/DECISIONS.md:3134` -- header status "Agent-decided -- pending review"; body
  names `.github/prompts/plan.prompt.md`, `session_close.prompt.md`, `*.agent.md`. A `## Decision
  26:` header also exists @ `docs/DECISIONS_ARCHIVE.md:1404` with a different title/status.
- Decision 35 @ `docs/DECISIONS.md:3102` -- body: "Maintains human-in-the-loop for terraform
  apply (no auto-apply)". `AGENTS.md` line ~138 cites "Decision 35" (co-listed with CD.35 /
  Decision 77). Decision 77 @ `:1934` introduced sandbox auto-apply.
- Decision 37 @ `docs/DECISIONS.md:3057` -- names the GitHub Models API dispatch for scheduled
  agents. Decision 116 @ `:220` reroutes scheduled-agent providers.
- Decision 40 @ `docs/DECISIONS.md:2878` -- names Copilot SDK + AWS Bedrock BYOK; header
  "(Decided, Deferred)"; body lists trigger conditions. CD.28 retired Bedrock for the dev surface
  (find its citation).
- Peers with annotations: Decision 68 @ `:2499` and Decision 71 @ `:2231` each carry an inline
  `> **2026-05 migration update:**` blockquote.

Keyspace anchors:
- Decision 75 @ `docs/DECISIONS.md:2038` -- `**Warehouse ID:** dec-081`.
- Decision 105 @ `docs/DECISIONS.md:554`; its reconciliation sentence @ ~`:581-583` maps CD-side
  pointers ("CD.31->dec-078, CD.16/CD.24->dec-079, CD.33->dec-081, CD.22->dec-085") and states 5
  ratified CDs had pointed at retired 4-digit ids (dec-1085/1086/1089/1091). CD.33 is ratified by
  Decision 81 @ `:1752`.
- 4-digit in-file lines observed on Decisions 77 (dec-1083), 78 (dec-1085), 79 (dec-1086), 80
  (dec-1088), 81 (dec-1089), 83 (dec-1090), 85 (dec-1091). Re-derive the full set.
- Decision 85 @ `:1615` carries a `**Renumbering note:**` about a parallel-authoring collision
  (originally "Decision 84", renumbered at merge).

Governing surfaces:
- `.claude/skills/decision-scout/SKILL.md` -- required-context `docs/DECISIONS.md`; loads the
  ENTIRE file, classifies every entry GOVERNS/CONTRADICTS/RELATED against a proposed plan. Its
  Phase-1 text quotes a live-header count figure -- re-derive it; it may be stale (TRAP-6).
- `scripts/checks/roadmap/validate_candidate_decision_ratification.py` -- the R1/R2/R3 guard whose
  referential target is `## Decision NNN:` headers in BOTH DECISIONS.md and the archive. It
  validates the CD->header pointer; determine whether it (or any check) validates in-file
  Warehouse ID lines or premise liveness.
- Stated archival policy: `docs/PROJECT_CONTEXT.md` line ~18 asserts "DECISIONS.md keeps only open
  decisions (resolved decisions archived to DECISIONS_ARCHIVE.md)" and credits an enforcer.
  Verify the enforcer exists and whether the live set (many `(Decided)` entries) conforms.

---

## 11. EMPIRICAL PASS

The live-set enumeration IS the audit; do it in full.

- POPULATION: every live `## Decision` header in `docs/DECISIONS.md`. Enumerate ALL of them --
  this is a sweep, not a sample. Do NOT exceed the file: the archive and roadmap are context
  (Section 4), not population.
- PER-ENTRY BUDGET: read each entry's own body (header, premise/context, status, any annotation,
  Warehouse ID line) plus the specific later Decisions it names or that name it. Do NOT chase
  every downstream reference across the repo for every entry -- follow a citation only when it is
  needed to decide liveness. Full cross-repo tracing is reserved for the DD-A seed entries.
- COUNTERFACTUAL (apply per entry, as an operation, not a vibe): "If the substrate/artifact/rule
  this entry's premise names were deleted from the repository at HEAD -- or has it already been
  inverted by a later Decision -- would this entry still stand as written? If the premise is
  already dead, does the entry carry a forward annotation?" An entry passes Q1 as `premise-live`
  only if the premise still holds; as `dead-but-annotated` if dead with a pointer; as
  `dead-unannotated` if dead with none.
- EVIDENCE_KIND: tag each finding `observed` (traced to a specific entry/line or a retired
  artifact you confirmed absent) or `static` (structural/derived). At equal severity, `observed`
  findings outrank `static` ones in `top_improvements` ordering.
- ANTI-VACUITY: for any entry you classify `premise-live`, be able to name the still-true premise;
  for any `dead-unannotated`, name both the dead substrate/rule AND the searched-for-but-absent
  annotation.

---

## 12. METHOD

Phases, in order:
- P1 READ: enumerate the live population; build the structural map (counts, header statuses,
  Warehouse ID lines). Re-derive every Section 10 anchor; log drift to `meta.stale_anchors`.
- P2 TRACE: run the Section 11 counterfactual over the full population; classify each entry (Q1).
- P3 DEEP-DIVE: DD-A (seed entries), DD-B (keyspace), DD-C (annotation practice).
- P4 EMPIRICAL: finalize the classified enumeration and counts; tag evidence_kind.
- P5 RATE: assign VD1..VD5; answer Q1..Q6; fill Q5's external_checklist.
- P6 DEDUP: Section 13 for every candidate finding.
- P7 SYNTHESIZE: write findings, rejected_candidates, summary. Compute severity (Section 15) then
  maturity (Section 15) LAST, after all judgment is done.

---

## 13. DEDUP DISCIPLINE

Before filing ANY finding, grep the ownership surfaces and record the search on the finding.
- Surfaces: `logs/.recommendations-log.jsonl` (open recs), `docs/ROADMAP-PLATFORM.yaml`
  (`tier_items[]`, `candidate_decisions[]`, `key_gaps`/`open_questions` if present), and
  `docs/DECISIONS.md` itself (a later Decision may already own the fix).
- Record on each finding's `roadmap_crossref`: `dedup_search_terms`, `dedup_hit_count`,
  `item_ids`, `classification`.
- A hit means sufficiency-assessment or `rejected_candidates` -- NOT a fresh discovery. A finding
  with no recorded negative search is a HYPOTHESIS, not CONFIRMED.

KNOWN OWNED POINT-FIXES (do NOT re-file these as novel; they are POINT fixes -- the audit's novel
contribution is the SYSTEMATIC sweep and the CONTROL, not re-filing an instance). Confirm each
still exists in the recs cache and treat a match as owned:
- rec-1964 -- renumber duplicate Decision 72 entries.
- rec-2278 -- add Warehouse ID line to Decision 89.
- rec-917 / rec-918 -- Decision 66 / 65 stale path references.
- rec-2057 / rec-2058 / rec-2059 -- annotate specific stale Decision 36/37/50/51/56/69 cross-refs.
- rec-2287 -- remove stale pre-ratification language from CD.35 (roadmap side).
A systemic finding (e.g. "no supersession-annotation invariant exists") is NOT owned by these
point-fixes; it may cite them as evidence the point-fix treadmill exists.

DELIBERATE CONSTRAINTS -- DO NOT FLAG (each with its owner):
- The DuckLake ops backend / warehouse architecture (Decision 84) -- the audit examines the
  in-file KEY, never the backend.
- The CD-side `filed_via`/`ratified_as` pointers on `candidate_decisions[]` -- already reconciled
  by Decision 105; do not propose re-fixing them.
- The prose-monolith FORMAT of DECISIONS.md -- a separate audit owns it.
- pending-CD premise validity, the platform-first sequencing frame, and decision-scout's
  existence/size -- out of scope (Section 4).

---

## 14. OUTPUT

Write exactly two files (`<sha>` = the Section 5 base short sha):
- `audits/decision-log-premise-integrity-<sha>.yaml` -- the findings contract below.
- `audits/decision-log-premise-integrity-<sha>.md` -- a companion report, <= ~1500 words, the
  executive layer a human reads first: verdict per question, the Q1 classified-enumeration table,
  the keyspace map, maturity, and the top improvements. Prose, no new prescriptions beyond the
  YAML.

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered or not-a-defect
candidates live in `rejected_candidates[]`, NOT findings. `rubric_ratings`, `question_answers`,
and the Q1 enumeration table are systems-of-record referenced FROM findings, never re-counted.
`top_improvements` and `highest_leverage_change` MUST be finding ids.

CONFIRMED requires the behavior traced to file:line or a confirmed-absent artifact; anything less
is HYPOTHESIS. `control_property_match` is REQUIRED on any `rejected_candidates` entry dismissed
because of a compensating control: name the property the control exercises, cite where it
operates, and state why it would FAIL if the defect were real.

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1, scope_surfaces: [docs/DECISIONS.md],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: sound|localized-drift|systemic-drift, basis: [<finding ids>],
       prose: "", classification_counts: {premise-live: 0, dead-but-annotated: 0,
         dead-unannotated: 0, archive-eligible: 0, indeterminate: 0}}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q3, verdict: coherent|cosmetic-drift|keyspace-hazard, basis: [<finding ids>], prose: ""}
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: "",
       external_checklist:
         - {property: status-lifecycle, rating: met|partial|missed, evidence: ""}
         - {property: immutability-with-supersession-links, rating: met|partial|missed, evidence: ""}
         - {property: stable-unique-identifiers, rating: met|partial|missed, evidence: ""}
         - {property: single-writer-numbering-authority, rating: met|partial|missed, evidence: ""}
         - {property: supersession-bidirectionality, rating: met|partial|missed, evidence: ""}}
    - {q: Q6, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
  per_surface_assessment:
    - {surface: docs/DECISIONS.md, maturity: <derived last>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: docs/DECISIONS.md, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
    # ... VD2..VD5, one row each
  findings:
    - {id: DPI-01, surface: docs/DECISIONS.md, question: Q1..Q6, dimension: VD1..VD5,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|annotate|archive,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale: "", confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [<finding ids>],
            highest_leverage_change: <finding id>, maturity_decisions_md: <value>}
```

---

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing or
candidate ordering.
- critical = a live entry's dead-but-unmarked premise (or a keyspace collision) would cause a
  planning session that loads it as binding to make a materially WRONG, trusted decision, or an
  irreversible ETL corruption proceeds on it.
- high = a dead-unmarked premise on a currently-binding entry (steers planning inputs), OR the
  absence of a control that would prevent recurrence, where you judge the existing ad-hoc practice
  and point-fix recs an INSUFFICIENT compensating control.
- medium = keyspace/metadata drift or lifecycle-hygiene gap with a clear fix and no live-work
  impact; an ad-hoc-but-currently-working practice.
- low = wording/clarity.

COMPENSATING-CONTROL PROPERTY-MATCH: a control lowers severity or justifies dismissal only if it
exercises the SAME property AND would FAIL if the defect were real (apply the counterfactual to
the control too). A point-fix rec that annotates ONE stale reference does not property-match a
finding about the SYSTEMIC absence of an annotation invariant -- it cannot catch the next
instance.

MATURITY (compute LAST, one surface, top-down, first match wins; thresholds are pinned, not
examples):
- frontier = 0 open critical AND 0 open high findings AND every property in Q5's
  `external_checklist` rated `met` or `partial` (never `missed`).
- strong = 0 critical AND <= 1 high.
- solid = <= 1 critical.
- nascent = otherwise.
The top rating remains reachable if you argued a property-matched compensating control -- the
framing here does not foreclose it.

---

## 16. COMMIT / PR MECHANICS

1. Base already derived in Section 5 (`git rev-parse --short origin/main` -> `<sha>`); it IS the
   audited tree.
2. You are on `audit/decision-log-premise-integrity-<sha>` off `origin/main` (Section 5 step 2).
   This clean two-file branch off the audited base is a deliberate, documented exception to the
   usual session-branch rule -- the PR diff must be exactly the two deliverables.
3. Repo-wide validation is advisory outside CI here: a clean YAML parse of both deliverables is
   the real pre-push gate. If an unrelated `validate --pre` check fails, record it in
   `meta.contract_notes` and do NOT fix it (write boundary).
4. Commit with identity `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign`
   if signing is unavailable. Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review):
   - title: `audit: DECISIONS.md premise-integrity + supersession/keyspace sweep (docs/DECISIONS.md)`
   - body: the `summary` block in a yaml fence, plus a 2-3 sentence lede.
6. Then END THE TURN. Do NOT poll, do NOT merge, do NOT subscribe, do NOT self-approve. The human
   disposes of the PR.

---

## 17. GUARDRAILS

- WRITE BOUNDARY (closed list): the ONLY files you create or modify in the tree are
  `audits/decision-log-premise-integrity-<sha>.yaml` and
  `audits/decision-log-premise-integrity-<sha>.md`. You do NOT edit `docs/DECISIONS.md`, you do
  NOT write or modify any `validate.py` check (Q2's control is SPECIFIED, not built), you do NOT
  re-file or update any recommendation, you move no entry to the archive. Regenerating gitignored
  caches per Section 5 is permitted and is not a tree modification.
- PRECISION OVER VOLUME. Fewer than ~4 surviving findings is a valid, honest result -- state it;
  do NOT pad. A run that merely re-confirms the candidates, or that files owned point-fixes as
  novel, has failed.
- Every finding CONFIRMED must be traced to a file:line or a confirmed-absent artifact; everything
  else is HYPOTHESIS and must say so.
- Stay inside scope: do not opine on the file's format, on pending CDs, on sequencing, or on
  decision-scout. Record, don't fix, anything out of the write boundary.
