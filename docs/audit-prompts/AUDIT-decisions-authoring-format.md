# AUDIT PROMPT: docs/DECISIONS.md as an authoring format (prose-monolith vs structured/warehouse-native)

You are auditing ONE surface: `docs/DECISIONS.md` **as an authoring format** -- the single
prose-markdown file into which every architectural/operational decision is written as a numbered
`## Decision NNN:` section. This file is simultaneously (a) the decision NUMBERING AUTHORITY, (b)
the UPSTREAM ETL SOURCE for the `ops_decisions` warehouse table, and (c) the human review/browse
surface. Your job is to judge whether this format is the right container for that content,
measured against the repository's own agent-first principle and its own precedents -- and to hand
the human an actionable disposition. This is a READ-ONLY design review. You draft; the human
disposes. You will run entirely on the repository at a pinned commit; you change no audited file.

Deliverables (the ONLY two files you create or modify in the repository tree):
- `audits/decisions-authoring-format-<sha>.yaml` -- the structured audit contract.
- `audits/decisions-authoring-format-<sha>.md` -- a companion report, prose, <= ~1500 words.

`<sha>` is the short SHA of the audited commit (derived in SETUP). Regenerating gitignored local
caches per SETUP is expected and does NOT breach the write boundary; never commit them.

The question stubs you will answer: Q1 consumption-path fit + cost; Q2 field-level ETL fidelity +
source-of-truth direction; Q3 governance + growth preservation; Q4 the format disposition verdict;
Q5 questions the requester did not think to ask. Full text in THE QUESTIONS.

---

## CANDIDATE OBSERVATIONS vs VERDICTS (read this before anything it governs)

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you NO verdicts. Every candidate
below is a hypothesis to adjudicate, not a defect to confirm.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** A run that merely confirms the
candidates below has failed. Your value is in the tracing, the counterfactual, and the weighing of
compensating controls -- not in echoing this list.

Per-candidate adjudication, and how each outcome maps to the output contract:
- **CONFIRMED defect, no owning roadmap item** -> `findings[]`, `roadmap_crossref.classification:
  novel`.
- **Owned by a roadmap item whose planned remedy is insufficient or not yet built** -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt`; name the item.
- **Fully covered by an owning item or a prior audit** -> `rejected_candidates[]`, naming the
  owner. NOT a finding.
- **Not a defect** (deliberate, sound, or compensated) -> `rejected_candidates[]`, naming the
  compensating control and its property-match.

Severity is assigned by YOU after judgment (see SEVERITY + MATURITY). It is never inherited from
where a candidate sits in this list or how emphatically it is phrased.

---

## READ FIRST -- disambiguation traps

This file lives in a dense naming neighbourhood. Five traps have misdirected readers before; do
not step in them.

1. **Four artifacts, one name-family.** Keep them distinct:
   - `docs/DECISIONS.md` -- the prose authoring file. **THIS is the audit target.**
   - `ops_decisions` -- a DuckLake-on-Neon table; the ETL DESTINATION that `--backfill-decisions-md`
     writes into. Context, not target.
   - `logs/.decisions-index.jsonl` -- a downstream read CACHE, rebuilt from the warehouse reader.
     Context, not target.
   - `docs/DECISIONS_ARCHIVE.md` -- holds 18 retired decisions. Context, not target.

2. **Decision 114 governs `docs/ROADMAP-PLATFORM.yaml`, NOT `docs/DECISIONS.md`.** It raised the
   ROADMAP file's size ceiling to 10,000 lines and added a code guard. It is the size-governance
   PRECEDENT you reason FROM; it is not the audit target and it has NOT been applied to
   DECISIONS.md (which has no size guard). Note also: Decision 114's "keep it one file" argument was
   made for a STRUCTURED YAML file; whether that argument transfers to a PROSE file is exactly a
   judgment you must make, not assume.

3. **Two distinct "migrations."** Tier items T1.5 and T5.4 own the STORAGE / write-path migration
   and the eventual DELETE of DECISIONS.md -- that direction is DECIDED (see DEEP-DIVES and
   DEDUP). This audit owns the orthogonal FORMAT-FRAME question: whether prose-monolith authoring
   is the right shape at all, the interim disposition until those far-future items land, and the
   end-state shape (delete vs generate-a-projection). "Already roadmapped to be deleted" is NOT a
   reason to reject a format finding; it is a reason to classify it `planned-*` and assess the
   plan's sufficiency.

4. **CAND-01 already audited this file's CONTENT; you audit its FORMAT.** A prior audit
   (`audits/decision-log-premise-integrity-8fb581e.yaml`, on main) exhaustively covered the
   decision CONTENT: live-vs-dead premises, supersession annotation, Warehouse-ID keyspace,
   duplicate-number detection, lifecycle/status hygiene, and content-discipline convention
   conformance (its Q5: status-lifecycle, immutability, stable-unique-identifiers, numbering
   authority, supersession-bidirectionality). You audit the CONTAINER: should decisions be authored
   as prose sections in one growing monolith at all. Same file, orthogonal axes. Re-deriving any
   CAND-01 content finding is out of scope and a DEDUP violation -- you may CITE CAND-01 facts as
   evidence for a FORMAT argument, but classify the fix as owned by the relevant DPI finding.

5. **Decision 86 named DECISIONS.md as a destination; it did not examine the format.** Decision 86
   routes "rationale / choices / trade-offs -> docs/DECISIONS.md (numbered)". Read this as: the
   file is the sanctioned HOME for rationale content -- NOT as a ratification of its prose-monolith
   FORM. Do not treat Decision 86 as having already decided the question you are asking.

---

## SCOPE

**In scope (one surface):** `docs/DECISIONS.md` as an authoring format -- its structure (one
monolithic prose file of numbered sections), its role as numbering authority, its role as the
`ops_decisions` ETL source, and its role as the human browse surface. Assess the format against
its consumers, its ETL, its governance, and the repo's agent-first principle.

**Context surfaces (read to judge, do NOT file findings against):** `ops_decisions` /
`scripts/ops_data_portal.py` (ETL destination + verbs); `scripts/decisions_md.py` (the parser);
`src/schemas/decision.py` (`DecisionPayload`); `.claude/skills/decision-scout/SKILL.md`,
`.claude/skills/plan-critique/SKILL.md`, `.claude/commands/implement.md` (consumers);
`docs/ROADMAP-PLATFORM.yaml` tier items T0.7b / T1.5 / T5.4 and Decisions 84 / 86 / 104 / 105 /
114 (governing context).

**Out of scope (one line each):**
- The DuckLake backend choice, keyspace mechanics, and the CD-side pointers -- owned by CAND-01 /
  Decision 84 / Decision 105.
- Decision CONTENT correctness (live/dead premises, supersession annotation) -- owned by CAND-01.
- decision-scout's stale count/size figures and the plan-critique/implement context-cost symptoms
  -- owned by the workflow-review audit (WF-04/05/14/18); cite as cost evidence, do not re-file.
- The trading product plane, terraform, CI internals -- unrelated.

**Trust nothing.** Obtain every file / line / size / count by reading the file yourself. Trust no
number quoted in this prompt; re-derive it from the repo at the audited commit and record any
non-resolving anchor in `meta.stale_anchors`. The prompt was drafted from a recent HEAD; if
`origin/main` has since moved, the tree you audit is the truth.

---

## SETUP

Run these once, at the start, from the repo root. They are read-only or cache-regenerating.

1. Derive the audited base ONCE and reuse it everywhere:
   ```
   git fetch origin main
   git rev-parse --short origin/main      # this is <sha>; used in filenames, branch, meta.audited_commit
   ```
2. Regenerate the local caches the DEDUP step depends on:
   ```
   bin/venv-python -m scripts.session_preflight --roadmap-detail full
   ```
   This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`.
   **IF this fails (creds/egress down): do NOT abort.** Set `meta.degraded_dedup = true`, mark every
   finding `confidence: HYPOTHESIS` and every `roadmap_crossref.dedup_hit_count: null`, and proceed.
   (Confidence is a top-level finding field; `roadmap_crossref` carries only `dedup_hit_count`.) The
   recommendations log may still be present as a stale cache; if so, use it and note the staleness in
   `meta.contract_notes`.
3. Size/shape probes you will re-derive (do not trust the numbers here; these are the commands):
   ```
   wc -c docs/DECISIONS.md ; wc -l docs/DECISIONS.md
   grep -cE '^## Decision ' docs/DECISIONS.md
   grep -cE '^## Decision ' docs/DECISIONS_ARCHIVE.md
   ```

Never edit any file outside the two deliverables. If any command fails in a way not covered above,
record it in `meta.contract_notes` and proceed with the affected confidences downgraded -- never
improvise a fix, never abort the audit.

---

## NORTH STAR

The bar you judge the format against. These are principles, not pass/fail switches -- argue each
surface against them.

- **NS.4 (the repo is for agents).** `docs/ROADMAP-PLATFORM.yaml` north_star: "The repo is for
  agents. Documentation, configuration, and tooling are optimised for agent consumption. Narrative
  prose is a side effect, not an output." This is the primary bar. A decision record is BOTH prose
  rationale (which NS.4 tolerates as a side effect) AND structured governing data (number, status,
  supersedes-edges, dates, related-refs). Judge whether the current format serves the structured
  half agent-efficiently, or forces agents to parse prose to recover structure.
- **Agent-first one-file principle (Decision 110 / Decision 114).** "One coherent load beats N
  files an agent must reassemble." This principle was ratified for STRUCTURED data
  (ROADMAP-PLATFORM.yaml). Judge whether it argues for keeping DECISIONS.md as one file, and
  whether "one file" and "prose" are separable properties (a single structured store is also one
  load).
- **Warehouse-as-source-of-truth (Decision 84).** Local files are downstream read caches, never
  upstream of the warehouse -- EXCEPT DECISIONS.md, which is explicitly the upstream ETL source
  ("ops_decisions is recreatable from DECISIONS.md"). Judge whether this exception is a sound,
  bounded carve-out or an inversion that should be closed.
- **Human sign-off + browse.** Decisions are human-ratified; the file is where a human reads and
  approves them. Any proposed format must preserve human authorship, review, and browse. This is a
  bar a structured alternative must clear, not a reason to stop asking.
- **CD.23 (portal is a projection, not a parallel source).** The agent-first human portal should be
  a projection of canonical state, not a second source. Judge the end-state (T5.4 deletes the file)
  against this: is deleting the browse surface, versus generating a prose projection from
  `ops_decisions`, the right call.

None of these is absolutist. Where the format legitimately serves a principle, say so and rate it
`strong`; where a principle does not structurally apply to a dimension, `n/a` is correct and
costless.

---

## THE QUESTIONS

Answer each in `question_answers[]`. Each is first-class with its own verdict from the pinned enum.

**Q1 -- Consumption-path fit + cost.** Enumerate EVERY path that consumes DECISIONS.md and, for
each, judge whether it genuinely requires a monolithic PROSE file, would be served as well or
better by structured per-decision records, or is format-agnostic. Known paths to start from (find
any others): decision-scout (loads the full file into a subagent every `/plan`); plan-critique
Phase-1 context; `implement.md` (targeted per-decision reads); the `--backfill-decisions-md` ETL +
`parse_decisions_md`; the numbering authority; human review/browse. For each path, record the
recurring cost the current format imposes (e.g. full-file reads and their token weight) and whether
that cost is intrinsic to the content or an artifact of the container. Verdict enum:
`prose-monolith-required | structured-sufficient | mixed`.

**Q2 -- Field-level ETL fidelity + source-of-truth direction.** Two parts. (a) FIDELITY: trace
what `parse_decisions_md` -> `DecisionPayload` actually captures versus what a decision block
contains. Does every governing element survive the projection, or are elements (e.g.
reversal-conditions, trailing bracketed amendments, non-schema sections) silently dropped? (b)
DIRECTION: DECISIONS.md is the UPSTREAM source that `ops_decisions` rebuilds from -- the inverse of
the warehouse-as-source-of-truth invariant every other ops table obeys. Judge whether this
upstream-prose-source arrangement is sound-and-bounded or an inversion with consequences. DEDUP:
the ETL's keyspace / duplicate-number / orphan-row mechanics are owned by CAND-01 (DPI-03/06/07) --
cite them as evidence, do not re-file the fixes. Verdict enum: `faithful-and-consistent |
lossy-or-inverted | sound-with-caveats`.

**Q3 -- Governance + growth preservation.** Two parts. (a) Would decision NUMBERING AUTHORITY,
human SIGN-OFF, and human BROWSE survive a structured or warehouse-native authoring format -- and
if so, at what added mechanism cost? (b) Is the file's unbounded GROWTH consciously governed?
DECISIONS.md has no size guard; ROADMAP-PLATFORM.yaml consciously got one (Decision 114). Judge
whether the Decision 114 precedent (a ratified ceiling + deterministic guard, OR a conscious "no
ceiling needed" ruling) should apply to DECISIONS.md, and whether the absence of any such ruling is
itself the gap. Verdict enum: `preserved-and-governed | preserved-but-ungoverned | at-risk`.

**Q4 -- Format disposition (the actionable verdict).** Given everything above AND the built/planned
state (T0.7b's write path is largely built; T1.5 is STRATEGIC and frozen; T5.4 deletes the file),
what is the right disposition of the DECISIONS.md authoring format? Answer in the
`format_disposition` decision block with a single verdict from the pinned enum and full mechanism /
what-changes / cost / rationale. Verdict enum: `ratify-prose-with-size-governance |
flip-authoring-to-structured-ahead-of-T1.5 | leave-as-roadmapped | rescope-T1.5/T5.4-end-state`.
This question's `question_answers` entry carries the verdict and points to the decision block for
detail.

**Q5 -- Questions the requester did not think to ask.** Answer AND extend. Seeds you must address:
(i) Does deleting DECISIONS.md at T5.4 (rather than generating a prose projection from
`ops_decisions`) lose a governance surface CD.23 implies should be preserved? (ii) Is "one file" vs
"prose" a false binding -- could the file become generated-from-structured-source and stay one
file? (iii) Is there a lower-cost interim move (e.g. a size guard, or a structured front-matter
block per decision) that captures most of the benefit without the full T1.5 migration? Then add any
question a thorough reviewer would wish had been asked. Use the `answers[]` shape for this entry.

---

## RUBRIC

Rate the single surface `docs/DECISIONS.md` on each dimension in `rubric_ratings[]`. Enum:
`strong | adequate | weak | absent | n/a`. `n/a` is correct and costless where a dimension does
not structurally apply -- never manufacture a rating or a finding to fill a cell.

- **VD1 -- Format-content fit.** Does the prose-monolith container match what a decision record
  structurally is (numbered metadata + status + supersedes-edges + dates + prose rationale)? Serves
  Q1, Q4.
- **VD2 -- Consumption cost.** What recurring context/token cost does the format impose on its
  consumers, and is it justified by the content or an artifact of the container? Serves Q1.
- **VD3 -- ETL field-fidelity & SoT direction.** Does the prose->structured projection preserve
  governing content, and is the upstream-source direction sound? Serves Q2.
- **VD4 -- Governance preservation.** Do numbering authority, human sign-off, and browse hold under
  the current format and survive a proposed one? Serves Q3, Q4.
- **VD5 -- Growth governance.** Is unbounded growth consciously governed (ceiling/guard, or a
  reasoned exemption), per the Decision 114 precedent? Serves Q3, Q4.

Every analytical question (Q1-Q4) is served by >=1 dimension; every dimension is referenced by >=1
question. Q5 (questions-not-asked) is meta and dimension-agnostic -- a finding tagged `question: Q5`
sets `dimension` to the closest-fitting VD (or the VD its underlying gap most implicates).

---

## DEEP-DIVES

**DD-A -- Authoring -> ETL -> consumption lifecycle of one recent decision (feeds Q1, Q2).** Pick
one recent, structurally rich entry (e.g. Decision 84, which carries a trailing bracketed
amendment; or Decision 114 / 121, which carry `Reversal conditions`). Trace it end to end: (1) how
it is authored (prose section, sub-field markers); (2) what `parse_decisions_md`
(`scripts/decisions_md.py`) extracts from it -- run the parser or read its regexes and field map;
(3) what `DecisionPayload` (`src/schemas/decision.py`) retains; (4) what each consumer recovers.
Record concretely which block elements reach `ops_decisions` and which do not. This grounds the
Q2 fidelity verdict in an observed trace, not an assertion.

**DD-B -- The Decision 114 precedent, applied (feeds Q3, Q4).** Read Decision 114 in full. It kept
ROADMAP-PLATFORM.yaml as one file, raised the ceiling to 10,000 lines, added a deterministic guard,
and set reversal conditions. Determine: (1) which parts of that reasoning are format-neutral (apply
to any growing canonical file) versus structured-data-specific (rely on YAML being machine-parsed);
(2) what a conscious size-governance decision for DECISIONS.md would concretely look like; (3)
whether the one-file argument survives when the file is prose rather than structured. Do NOT
propose editing Decision 114 or the roadmap guard -- this is analysis feeding your recommendation.

---

## EMPIRICAL PASS

Sample **at most 8** decision entries -- do NOT exceed. Choose for structural variety: include at
least two with `Reversal conditions`, at least one with a trailing bracketed amendment, and a
spread across the pre-77, the 77-85, and the post-85 bands (Decision 84, the named amendment
example, sits in the 77-85 middle). For each sampled entry apply this counterfactual and
tag `evidence_kind: observed`:

> Run `parse_decisions_md` (or trace its regexes) over the entry and compare the resulting
> `DecisionPayload` fields against the raw block. Which governing elements survive, and which are
> dropped? Would a consumer reading only `ops_decisions` recover the decision's full governing
> content?

Then apply the CONVERSE probe on the same sample: what does the prose form capture that a structured
store would flatten or lose (narrative nuance, human-authored trailing amendments, browse cohesion
across related decisions)? Record BOTH directions so the Q2/Q3 verdicts weigh loss against gain, not
loss alone -- a format finding that only counts what prose drops has not done the weighing.

An observed fidelity gap (an element demonstrably dropped for a real sampled entry) outranks a
static/theoretical one at equal severity. Record the sampled decision numbers in the finding
evidence so the sample is auditable. Do not generalise beyond what the sample shows; if only some
entries drop content, say which and how many.

---

## METHOD

Phases, in order. Synthesis and maturity are always LAST.

- **P1 Read.** Read the in-scope file and every context surface named in SCOPE and the GROUNDING
  MAP. Re-derive all sizes/counts.
- **P2 Trace.** Enumerate consumption paths (Q1); trace the ETL field map (Q2); confirm the
  presence/absence of a size guard (Q3).
- **P3 Deep-dive.** Execute DD-A and DD-B.
- **P4 Empirical.** Run the sampling pass (<= 8 entries).
- **P5 Rate.** Fill `rubric_ratings[]` per surface-dimension.
- **P6 Dedup.** For every candidate finding, run DEDUP DISCIPLINE before it may become a finding.
- **P7 Synthesize.** Adjudicate each question; fill the decision block; assign severity; compute
  maturity LAST.

---

## DEDUP DISCIPLINE

Before ANY candidate becomes a `findings[]` entry, search the ownership surfaces and record the
result on the finding. A finding without a recorded negative search is a HYPOTHESIS, not a finding.

Ownership surfaces to grep:
- `docs/ROADMAP-PLATFORM.yaml` -- tier_items (T0.7b, T1.5, T5.4 especially) and `candidate_decisions`.
- `docs/DECISIONS.md` -- Decisions 84, 86, 104, 105, 114.
- `logs/.recommendations-log.jsonl` -- open recs touching decisions/format.
- Prior audits in `audits/` -- especially `decision-log-premise-integrity-8fb581e.yaml` (CAND-01)
  and `workflow-review-d107b4a.yaml`.

Record on each finding: `dedup_search_terms`, `dedup_hit_count`, and `classification`
(`novel | planned-insufficient | planned-unbuilt`). A hit means the finding is a
sufficiency-assessment of the owner (or belongs in `rejected_candidates`), NEVER a fresh discovery.

**Deliberate constraints -- do NOT flag these as defects:**
- The migration-to-warehouse DIRECTION is decided (T0.7b built; T1.5 STRATEGIC; T5.4 deletes the
  file). Assess sufficiency of the plan; do not flag "should migrate" as novel.
- T1.5 being STRATEGIC and frozen is a Decision 67 / CD.17 consequence, not a defect.
- ROADMAP-PLATFORM.yaml remaining one file with a 10,000-line ceiling is Decision 114 (precedent
  only; not a target).
- Stale size/count figures and consumer context-cost symptoms are owned by workflow-review
  (WF-04/05/14/18). Cite as cost evidence; do not re-file.
- CAND-01 owns decision CONTENT and content-discipline convention conformance (its Q5), plus ETL
  keyspace/duplicate/orphan mechanics (DPI-03/06/07). Cite; do not re-file.
- `validate_decisions_local_writes` (Decision 104) guards the `.decisions-index.jsonl` CACHE, not
  the authoring file -- do not read its existence as a guard ON DECISIONS.md.
- Public-repo confidentiality (Decision 101): propose nothing that would publish confidential data.

---

## OUTPUT

Write both deliverables. The YAML is the system of record; the `.md` is the executive layer a human
reads first.

```
audit:
  meta: {audited_commit: <short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1, scope_surfaces: ["docs/DECISIONS.md"],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: prose-monolith-required|structured-sufficient|mixed, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: faithful-and-consistent|lossy-or-inverted|sound-with-caveats, basis: [], prose: ""}
    - {q: Q3, verdict: preserved-and-governed|preserved-but-ungoverned|at-risk, basis: [], prose: ""}
    - {q: Q4, verdict: ratify-prose-with-size-governance|flip-authoring-to-structured-ahead-of-T1.5|leave-as-roadmapped|rescope-T1.5/T5.4-end-state, basis: [], prose: "<points to format_disposition>"}
    - {q: Q5, answers: [{question, answer, basis: [<finding ids>]}]}
  per_surface_assessment:
    - {surface: "docs/DECISIONS.md", maturity: <computed last>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: "docs/DECISIONS.md", dimension: VD1, rating: strong|adequate|weak|absent|n/a, evidence: "file:line|item-id", note: ""}
    # ... VD2..VD5
  format_disposition:
    "docs/DECISIONS.md": {verdict: <Q4 enum>, mechanism: "", what_changes: "", cost: "",
                          rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  findings:
    - {id: DAF-01, surface: "docs/DECISIONS.md", question: Q1..Q5, dimension: VD1..VD5,
       title, evidence: "file:line|item-id", evidence_kind: static|observed,
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
            top_improvements: [ids], highest_leverage_change: <id>, maturity_decisions_md: <value>}
```

Finding-id prefix is `DAF-` (decisions authoring format). Enums are pinned inline above; use them
verbatim.

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered or
not-a-defect candidates live in `rejected_candidates[]`, NOT `findings[]`. `rubric_ratings`,
`question_answers`, and `format_disposition` are systems-of-record referenced FROM findings, never
re-counted. `top_improvements` and `highest_leverage_change` MUST be finding ids -- EXCEPT when
`findings[]` is empty (a valid, honest result): then set `top_improvements: []` and
`highest_leverage_change: null`.

**CONFIRMED vs HYPOTHESIS.** `CONFIRMED` requires the behaviour traced to a file:line or an observed
sampled entry. Anything less is `HYPOTHESIS`.

**control_property_match** is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why the control would
FAIL if the defect were real.

---

## SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing.

- **critical** = the format causes a wrong-but-trusted governance outcome (e.g. a consumer acts on
  a decision whose governing content was silently lost, with no other path to recover it).
- **high** = a weakness that materially reduces the format's fitness AND whose compensating controls
  you judged insufficient.
- **medium** = redundancy / ambiguity / inconsistency with a clear fix.
- **low** = clarity / wording.

Compensating-control rule: a control only lowers severity if it PROPERTY-MATCHES -- it must exercise
the same property the defect would break AND fail if the defect were real (apply the counterfactual
to the control). A control that cannot catch the break neither lowers severity nor justifies
dismissal.

**Maturity** (compute LAST, for the single surface, top-down, first match wins; this prompt has no
industry-checklist question, so the top tier gates on finding counts alone):
- **frontier** = 0 open critical AND 0 open high findings.
- **strong** = 0 critical AND <= 1 high.
- **solid** = <= 1 critical.
- **nascent** = otherwise.

The top rating remains reachable if you argued a property-matched compensating control for what
would otherwise be a high/critical -- the framing here does not foreclose it.

---

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Every anchor was resolved from disk at a
recent HEAD; **verify each before relying on it** and record any that no longer resolve in
`meta.stale_anchors`. Facts are stated neutrally and carry no verdict -- convicting is your job.

Sizes/counts (re-derive; see SETUP):
- `docs/DECISIONS.md` -- ~271,398 bytes, ~3,348 lines, 81 live `## Decision NNN:` headers at the
  drafting HEAD. Newest at top (Decision 121); oldest live near the bottom (Decision 23).
- `docs/DECISIONS_ARCHIVE.md` -- ~93,598 bytes, 18 archived `## Decision` headers.
- Per-entry shape: `## Decision NNN: <title> (<status>)` followed by `**Status:**`, `**Date:**`,
  often `**Warehouse ID:**`, `**Problem:**`/`**Trigger:**`, `**Decision:**`, sometimes
  `**Reversal conditions:**`, `**Related:**`. Some entries carry trailing bracketed amendments
  (e.g. Decision 84 has a `[Amendment 2026-07-03 ...]` block after `**Related:**`).

Format governance and precedent:
- NS.4 -- `docs/ROADMAP-PLATFORM.yaml:251-253` ("The repo is for agents ... Narrative prose is a
  side effect, not an output.").
- Decision 84 -- `docs/DECISIONS.md:1634`; ratified premise "ops_decisions is recreatable from
  DECISIONS.md"; I-2 "dec-NNN follows the human-assigned DECISIONS.md numbering (callers supply
  decision_id)".
- Decision 86 -- `docs/DECISIONS.md:1582`; forward-routing clause routes rationale ->
  `docs/DECISIONS.md` (numbered); forbids new standing prose-architecture docs.
- Decision 114 -- `docs/DECISIONS.md:303`; raised ROADMAP-PLATFORM.yaml ceiling to 10,000 lines +
  deterministic guard; rejected a per-tier split; reversal = breaches ceiling OR `/plan` load cost
  prohibitive in practice.
- Size guard exists ONLY for the roadmap: `scripts/checks/roadmap/validate_platform_roadmap.py`
  (`_ROADMAP_MAX_LINES = 10_000`). No equivalent references DECISIONS.md (verify by grepping
  `scripts/` for a DECISIONS size/line constant).
- CD.23 (`docs/ROADMAP-PLATFORM.yaml` candidate_decisions) -- "portal is projection, not parallel
  source".

ETL and schema:
- Parser -- `scripts/decisions_md.py`; `parse_decisions_md` (~line 84); heading regex keys on the
  integer decision number (~line 90); duplicate handling is first-parsed-wins (~lines 91-92);
  extracts `title, status, problem (Problem/Trigger), decision_text (Decision), context
  (Rationale/Key details/Context), decided_date, related_decisions`. It has NO extraction for
  `Reversal conditions` or trailing bracketed amendments (verify).
- Schema -- `src/schemas/decision.py` `DecisionPayload` (`extra="ignore"`); fields: `id,
  decision_id, title, status, problem, decision_text, context, decided_date, related_decisions,
  related_decisions_v2, created_timestamp, last_updated_timestamp`. No `reversal_conditions` or
  amendment field (verify).
- Portal -- `scripts/ops_data_portal.py`: `file_decision` (~line 1338), `update_decision`
  (~1407), `backfill_decisions_from_md` (~1442), CLI `--backfill-decisions-md` (~1729).
- Cache guard -- `scripts/checks/ops_governance/validate_decisions_local_writes.py` (Decision 104);
  guards `.decisions-index.jsonl`, whitelists `ops_data_portal.py` + `sync_ops.py`.

Consumers:
- decision-scout -- `.claude/skills/decision-scout/SKILL.md`; `required-context: docs/DECISIONS.md`;
  Phase-1 "Read the entire docs/DECISIONS.md -- do not Read with offset/limit"; text quotes
  "currently 67" headers and ">200KB" (both stale -- owned by workflow-review WF-14; re-derive the
  live numbers yourself); carries a "Lambda migration contract" section (swap the Read for a tool
  call; output contract unchanged).
- plan-critique -- `.claude/skills/plan-critique/SKILL.md`; `required-context:
  docs/PROJECT_CONTEXT.md`.
- implement -- `.claude/commands/implement.md:50` ("Read only the decisions cited in the plan
  context ... do not load the full file").

Roadmap chain (the owned migration):
- T0.7b -- `docs/ROADMAP-PLATFORM.yaml` "log-decision Lambda (handler)"; `file_decision` write verb
  realized in `src/lambdas/ducklake_writer/handler.py`; note records it as likely
  silent-completion (backfill uses it each session).
- T1.5 -- "ops_decisions graduation Phases 2-6 ... (STRATEGIC)"; intent: Phase 3b markdown delete;
  gated on CD.18 ratification; `strategic: true`, `status: not_started`.
- T5.4 -- "Markdown DECISIONS.md retirement"; intent: "After T1.5 lands and ops_decisions is the
  source of truth, delete docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md"; `effort: XS`,
  `depends_on: [T1.5]`.

Prior audits (dedup):
- CAND-01 -- `audits/decision-log-premise-integrity-8fb581e.yaml` + `.md`; owns content premise,
  supersession annotation, keyspace (DPI-03/06/07), convention conformance (Q5). Its dedup posture
  explicitly excludes the prose-format question.
- workflow-review -- `audits/workflow-review-d107b4a.yaml`; WF-04 (implement full read -- since
  fixed), WF-05 (plan-critique Phase-1 context weight), WF-14 (stale 25k-token figure x6), WF-18
  (scout no completeness echo). Measured DECISIONS.md at 229,638 bytes at its commit; it is larger
  now (re-derive).

---

## COMMIT / PR MECHANICS

1. Base is `<sha>` from SETUP. Use it in the deliverable filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/decisions-authoring-format-<sha> origin/main` -- a deliberate, documented
   exception to the AGENTS.md `claude/*` session-branch rule, so the PR diff is exactly the two
   deliverable files off the audited base. (The CI signal-green comment wake fires only on
   `claude/*` PRs; irrelevant here -- you end your turn without merging.)
3. Repo-wide validation is advisory outside CI. A clean YAML parse of your two deliverables is the
   real pre-push gate:
   ```
   bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1])); print('ok')" audits/decisions-authoring-format-<sha>.yaml
   ```
   An unrelated `validate --pre` failure is recorded in `meta.contract_notes`, never fixed (write
   boundary).
4. Commit with identity `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if
   signing is unavailable:
   ```
   git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign -m "audit(decisions-authoring-format): findings + report at <sha>"
   git push -u origin HEAD
   ```
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review; NOT a draft),
   title `audit: docs/DECISIONS.md authoring format (prose-monolith vs structured)`, body = the
   `summary` block in a YAML fence plus a 2-3 sentence lede. Then END THE TURN -- do not poll, do
   not merge, do not subscribe. The human disposes of the PR.

---

## GUARDRAILS

- Write boundary is a CLOSED list: the only files you create or modify in the repository tree are
  `audits/decisions-authoring-format-<sha>.yaml` and `audits/decisions-authoring-format-<sha>.md`.
  Regenerating gitignored caches per SETUP is expected; never commit them. Never edit any audited or
  context surface -- if a check fails, record it in `meta.contract_notes`; do not fix it.
- Precision over volume. Fewer than ~4 surviving findings is a valid, honest result -- state it; do
  not pad. A finding you cannot trace to file:line or an observed sample is a HYPOTHESIS; label it.
- A run that merely restates the candidate observations has failed. Your deliverable is the
  adjudication, the disposition verdict, and the property-matched severity -- not confirmation.
- Do not opine on out-of-scope surfaces. Cite CAND-01 and workflow-review facts as evidence; classify
  their fixes as owned; re-file nothing they own.
