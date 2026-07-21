# AUDIT: Decision-log consolidation, growth direction, and semantic-intent capture

You are a frontier-capability model running a read-only design audit in a fresh session on
this repository (`agent-platform`, a public AWS ML-trading platform built for agent
consumption). You have no memory of how this prompt was composed and no one to ask -- the
prompt is self-contained. Execute it exactly. Do not ask clarifying questions.

---

## 1. TASK

Audit the **content and structural governance of the decision log** -- `docs/DECISIONS.md`
(the live corpus) plus its authoring contract, growth guard, warehouse ETL, and consumption
path -- along three axes:

1. **Consolidation.** Which *live* decisions overlap in governing content enough to be
   consolidated, and is a consolidation mechanism warranted? You produce a semantic-overlap
   **cluster map**, a per-cluster **verdict**, and a recommended consolidation **mechanism +
   criterion**. You do NOT draft replacement decision text.
2. **Growth direction.** Is decision growth structurally unbounded, and what structural
   mechanism should *direct* it (its rate and shape), as distinct from the byte-ceiling guard
   that already exists? Rated against a named external ADR-at-scale checklist (Section 7, Q2).
3. **Semantic intent.** Should the decision record capture *semantic intent* as a first-class
   element (beyond the literal decision text), should the existing content-hash SCD2 backfill
   be extended to version it, and should the `decision-scout` skill gain an intent-alignment
   triage axis (not only literal contradiction)? You design the concrete mechanism.

Deliverables (the ONLY files you create or modify in the repository tree): an audit contract
`audits/decision-consolidation-growth-<sha>.yaml` and a companion report
`audits/decision-consolidation-growth-<sha>.md` (`<sha>` = the short SHA of `origin/main`, per
Section 16). Regenerating gitignored local caches per Section 5 is expected and does not breach
the write boundary; never commit them. You draft; the human disposes -- nothing here is applied,
merged, or filed by you.

---

## 2. CANDIDATE OBSERVATIONS vs VERDICTS (read before anything it governs)

This prompt hands you **facts** and **candidate hypotheses**. It never hands you verdicts. Every
candidate in Section 10 and every cluster in Section 11 is a hypothesis to adjudicate by tracing
the repository -- not a finding to confirm.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** A run that merely confirms the
candidates below has failed. Your value is judgment: which overlaps are genuine redundancy vs
deliberate separation; whether the growth mechanism is a real gap or adequately covered; whether
intent-capture earns its cost or is ceremony. Expect to reject candidates and to surface findings
no candidate named.

Per-candidate adjudication enum, and how each maps to the output:
- **CONFIRMED defect** (traced to file:line or a sampled artifact) -> `findings[]`, classification
  `novel`.
- **Planned, but the owning item's remedy is insufficient or unbuilt** -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt` (name the owning item).
- **Planned and fully covered by the owning item** -> `rejected_candidates[]` (name the item).
- **Not a defect** -> `rejected_candidates[]`, naming the compensating control and why it
  property-matches (Section 15).

Severity is assigned AFTER judgment, by defect class (Section 15) -- never inherited from this
prompt's framing or ordering.

---

## 3. READ FIRST -- disambiguation traps

Every trap below is a real hazard found at compose time. Misreading any one sends the audit at
the wrong target.

- **TRAP-1 -- "Directed Growth Governance" (Decision 43) is about CODE, not decisions.**
  Decision 43 governs Python-file SLOC, cyclomatic complexity, `.prompt.md`/`.agent.md` token
  budgets, and tool-tier taxonomy. It does NOT govern the decision corpus. Your growth-direction
  question (Q2) concerns the decision log itself -- a surface Decision 43 never touches. Do not
  treat Decision 43 as an existing remedy for decision growth; do treat its *name and intent* as
  a precedent you may reference.
- **TRAP-2 -- the DAF audit already settled FORMAT; you audit CONTENT.** A prior audit
  (`audits/decisions-authoring-format-d140093.yaml`, findings DAF-01..04), ratified by Decision
  134, decided: keep prose-monolith authoring; the ETL is observed-lossy and got a parity fix;
  there is a size ceiling; there is an authoring grammar. Do NOT re-litigate prose-vs-structured,
  ETL fidelity, the *existence* of a size ceiling, or the authoring grammar. Your axis is
  semantic **overlap between live entries** and the **direction** of growth -- neither is a DAF
  finding.
- **TRAP-3 -- the DPI audit already swept PREMISE INTEGRITY; you audit OVERLAP.** A prior audit
  (`audits/decision-log-premise-integrity-8fb581e.yaml`, findings DPI-01..07) swept dead-vs-live
  premises, supersession-annotation, warehouse-ID keyspace, and archival/lifecycle policy. Its
  point-fixes are largely still open (rec-2057, rec-2058, rec-2059, rec-2278, rec-1964). Do NOT
  re-file DPI territory. Overlap between two *live* decisions is a different axis from whether a
  decision is dead.
- **TRAP-4 -- two different "supersession" checks.**
  `scripts/checks/roadmap/validate_candidate_decision_supersession.py` governs *candidate
  decisions* (CD.NN) in the roadmap YAML, NOT `## Decision N` prose entries in `DECISIONS.md`.
  There is no mechanical supersession-annotation check on the prose entries (that absence is
  DPI-01's territory -- do not re-file it; you may reference it).
- **TRAP-5 -- "intent" already means two other things here.** The roadmap tier_items carry an
  `intent:` field, and retiring `docs/INTENT-*.md` docs exist (grandfathered, being deleted). The
  user's "semantic intent" (Q3) is a NEW decision-record concept -- the *why/spirit* behind a
  ruling, addressable by consumers. Do not assume the roadmap `intent:` field or the INTENT docs
  cover it.
- **TRAP-6 -- SCD2 for decisions already exists.** The `ops_decisions` backfill is
  content-hash-gated SCD2 (Decision 134 cl.4): amendments are recorded as SCD2 versions. Q3's
  ask is to *extend* that existing SCD2 to version an intent field -- not to introduce SCD2.
- **TRAP-7 -- the scout read-cost belongs to a parallel audit.** The `decision-scout` reads the
  entire live file every `/plan` (~65-70k tokens). You MAY cite that cost as a driver/consequence
  of unbounded growth (consolidation shrinks it). You must NOT prescribe the context-window
  architecture, a scout pagination redesign, or a tool-backed read -- those belong to a separate,
  concurrently-commissioned agent-context-management audit. Name the overlap in
  `meta.contract_notes`; defer the depth.

---

## 4. SCOPE

**In scope -- built surfaces** (obtain every file/line/size by reading the file yourself; trust
no number quoted here, re-derive from the repo, and record any non-resolving anchor in
`meta.stale_anchors`):

- `docs/DECISIONS.md` -- the live decision corpus (the content under audit).
- `docs/DECISIONS_ARCHIVE.md` -- the archive (ETL input #2; ride every consolidation proposal).
- `docs/contracts/decision-entry.yaml` -- the authoring grammar (required/optional markers).
- `scripts/decisions_md.py` -- the shared parser + the `ops_decisions` ETL source.
- `src/schemas/decision.py` -- the write-side `DecisionPayload` (the warehouse column set).
- `scripts/checks/decisions/validate_decisions_size.py` -- the byte/header ceiling guard.
- `scripts/checks/decisions/validate_decision_entry_conformance.py` -- forward marker
  conformance on new entries.
- `.claude/skills/decision-scout/SKILL.md` -- the mandatory pre-`/plan` triage gate.
- The governing decisions: 105 (ratification lane), 134 (size ceiling + prose ratification), 43
  (directed growth of code), 84 (warehouse authority + backfill), 114 (roadmap size precedent),
  86 (rationale-routing), 87 (git-vs-warehouse authoring-timing).

**In scope -- designed-unbuilt surfaces** (assess as designs, not as running code):

- Tier item **T1.5** (`docs/ROADMAP-PLATFORM.yaml`) -- STRATEGIC, `status: not_started`, frozen
  under CD.17: the `ops_decisions` warehouse migration that retires `DECISIONS.md`.
- The two relief valves named in Decision 134 cl.2: archival (DPI-04 scope) and "compact
  superseded decision bodies to pointer stubs" -- both named, neither built.

**Vocabulary:**
- *Live decision* -- a `## Decision N:` entry in `docs/DECISIONS.md` (not the archive).
- *Ratify-CD entry* -- a live decision whose title begins "Ratify", produced by the Decision-105
  lane to flip a candidate decision (CD.NN) from `pending` to `ratified`.
- *Consolidation* -- collapsing two or more live entries that govern overlapping territory into
  fewer entries, OR compacting a superseded entry's body to a pointer stub.
- *Semantic intent* -- the durable *why/spirit* a decision serves, distinct from its literal rule
  text; the property against which "is this plan aligned?" (not merely "does it contradict?") is
  judged.
- *SCD2 backfill* -- `ops_data_portal --backfill-decisions-md`, content-hash-gated, recording
  amendments as versions.

**Out of scope (one line each):**
- The prose-vs-structured format debate (ratified, D134 -- TRAP-2).
- ETL fidelity / parity fields (DAF-01, landed).
- Dead-vs-live premise sweeps, keyspace/warehouse-ID drift, archival-policy reconciliation (DPI
  audit -- TRAP-3).
- The context-window / scout-read architecture (parallel audit -- TRAP-7).
- The DuckLake backend choice and the T1.5 *destination* (D84 -- assess only how consolidation
  and intent-capture interact with it, do not re-open it).

---

## 5. SETUP

Run these read-only commands once at the start. Never abort on failure -- take the named degraded
path.

```bash
git fetch origin main && git rev-parse --short origin/main          # the audited base <sha>
rg -c '^## Decision ' docs/DECISIONS.md                              # live header count
rg -n '^## Decision ' docs/DECISIONS.md                             # the full live header map
bin/venv-python -m scripts.session.preflight --roadmap-detail full  # DEDUP caches
```

The last command populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`,
which the DEDUP DISCIPLINE (Section 13) reads.

**Degraded path (mandatory dedup, no exceptions):** IF the cache-gen command fails (creds/egress
down): do NOT abort -- set `meta.degraded_dedup=true`, mark every `roadmap_crossref` confidence
`HYPOTHESIS` and every `dedup_hit_count` `null`, and proceed using `rg` over
`logs/.recommendations-log.jsonl` (if present) and `docs/ROADMAP-PLATFORM.yaml` directly. A
finding without a recorded dedup search is a HYPOTHESIS regardless.

**Optional parser probe (for Q3 / DD-C):** you may run the real ETL parser on a single entry to
observe what it captures:
`bin/venv-python -c "from scripts.decisions_md import parse_decisions_md; import json;
print(json.dumps([d for d in parse_decisions_md() if d['decision_id']==84][0], indent=2)[:1200])"`.
IF this errors, set `meta.contract_notes` and fall back to reading `scripts/decisions_md.py`
statically -- do not treat the probe as required.

Repo-wide `validate --pre` is advisory outside CI. Do NOT run it as a gate; a clean YAML parse of
your two deliverables is the real pre-push check. If you happen to run it and it fails on
something unrelated, record it in `meta.contract_notes` and never fix it (write boundary).

---

## 6. NORTH STAR

The bar you judge each surface against. The judgment-bearing principles are explicitly
non-absolutist -- argue each surface against them; do not pattern-match.

- **NS-1 (decision-support, not archive).** The live decision log's value is that an agent can
  cheaply and completely answer "what governs this action, and is my plan aligned with the spirit
  of the corpus?" A log optimized for completeness of history at the expense of that query is
  mis-optimized. *(Judgment bar: weigh completeness against query-cost per surface.)*
- **NS-2 (directed growth).** The corpus should grow with genuinely-new architectural
  commitments and *shrink* commitments as they supersede -- so the live reasoning surface stays
  bounded relative to a finite model context window. A guard that only caps bytes treats the
  symptom; directing growth shapes what becomes a decision and what happens to a decision once
  superseded. *(Judgment bar: is there a mechanism that acts on rate/shape, or only on size?)*
- **NS-3 (intent is first-class).** A decision recorded as a rule without its captured intent is a
  rule an agent can obey literally while violating its spirit. Whether making intent explicit
  earns its authoring cost is yours to judge -- but the *absence* of any intent-addressable
  element is a real property, not a style preference. *(Judgment bar: does the cost of capture
  buy a guarantee the corpus cannot otherwise give?)*
- **NS-4 (ride the existing substrate).** Consolidation and intent-capture should ride the
  existing warehouse/SCD2/backfill/authoring machinery, not stand up a parallel store. A proposal
  that duplicates T1.5's destination or the SCD2 backend is more expensive than the gap it closes.
- **NS-5 (self-consistency).** A governance surface should carry the same ratify + reversal +
  intent machinery it demands of the rest of the system. If materially smaller choices carry full
  reversal stanzas while the log's own growth policy does not, that asymmetry is a finding
  (precedent: Decision 133 made exactly this argument about an unratified frame).

---

## 7. THE QUESTIONS

Each question is first-class and gets its own `question_answers[]` entry. Verdict enums are pinned.

**Q1 -- Consolidation.** Over the live corpus, which decisions overlap in *governing content*
enough to consolidate, and is a consolidation mechanism warranted?
- Produce the semantic-overlap **cluster map** (Section 11 seeds it; extend it). For each cluster,
  emit a `consolidation_clusters` block entry with a per-cluster verdict from:
  `merge-into-one | supersede-and-archive | compact-to-stub | keep-separate`.
- Top-level Q1 verdict (the *mechanism* question): `warranted | partial | not-warranted` -- is a
  standing consolidation lifecycle (a criterion + a tool) justified, or do ad-hoc supersessions
  suffice?
- Do NOT draft replacement decision text. The deliverable is the map, the per-cluster verdicts,
  and the mechanism recommendation -- the human authors merges later.

**Q2 -- Growth direction (against industry practice).** Is decision growth structurally
unbounded, and what structural mechanism should direct it? Answer property-by-property against
this **EXTERNAL CHECKLIST** of ADR-at-scale practices (rate each `met | partial | missed` with
one line of evidence in the `external_checklist` field; `partial` requires an argued,
property-matched compensating control):
  1. **Immutability + supersession lifecycle** -- records are immutable; change is a new record
     that supersedes, with a status lifecycle (proposed/accepted/deprecated/superseded)
     (Nygard/MADR).
  2. **One-decision-per-record granularity** -- each record captures exactly one
     architecturally-significant decision; neither omnibus nor trivial.
  3. **Architecturally-significant gate** -- an explicit bar for what *becomes* a decision vs a
     recommendation/note/roadmap item.
  4. **Generated index / registry** -- a lightweight table-of-contents or metadata index is
     generated, so consumers need not scan every full record (adr-tools `toc`, log4brains).
  5. **Decision-drivers / context section** -- the record template requires a "why / decision
     drivers" section, not only the ruling (MADR "Decision Drivers"). *(This overlaps Q3 -- assess
     here as a growth/template property, there as an intent-capture property.)*
  6. **Machine-readable front-matter** -- structured metadata (id, status, tags, supersedes)
     addressable without prose parsing (MADR 3.0 YAML front-matter).
  7. **Superseded-record compaction / archival out of the hot path** -- dead or superseded records
     leave the active reasoning surface.
  8. **Periodic review / revisit cadence** -- records carry revisit conditions or dates and are
     actually revisited.
  9. **Relationship graph over prose** -- related/supersedes/amends edges are typed and traversable,
     not only mentioned in body text.
- Verdict: `sufficient | partial | insufficient`. The maturity top tier (Section 15) reads this
  `external_checklist` field as its single source.

**Q3 -- Semantic intent + SCD2 + scout.** Three sub-parts; answer each and give it a verdict from
`adopt | adopt-scoped | reject`. Where you say adopt/adopt-scoped, design the concrete mechanism
as one or more findings (marker/column/triage-bucket with acceptance criteria).
- **Q3a (record):** should a first-class *intent* element be added to the decision record -- an
  authoring marker in `decision-entry.yaml` and a column in `DecisionPayload` -- distinct from the
  existing `problem`/`decision_text`/`context` fields? (Trace what those three already capture
  before concluding intent is absent vs merely unlabeled.)
- **Q3b (SCD2):** should the content-hash-gated backfill version intent alongside the body, so an
  intent revision is an SCD2 version (riding D134 cl.4), and what is the grain?
- **Q3c (scout):** should `decision-scout` gain an intent-alignment axis -- a triage bucket
  distinct from CONTRADICT that fires when a plan violates the *spirit* of the corpus without
  literally contradicting any single decision's text -- and how is it specified so it does not
  collapse into noise?

**Q4 -- Questions the requester did not think to ask.** Answer AND extend these seeds (each with
`basis` finding ids where applicable):
- Is the *ratification lane itself* (Decision 105) the right artifact granularity, given 25 of the
  live entries are full-prose ratifications whose stated effect is a bookkeeping state-flip?
- Does consolidation *conflict* with immutability -- i.e., does merging live entries destroy the
  supersession provenance the corpus relies on, and how is that reconciled?
- If intent becomes first-class, does the SCD2 amendment history need an intent *drift* signal
  (intent changed but rule text did not, or vice versa)?
- What in this audit's remedies is authorable *now* vs blocked behind the Decision-67 STRATEGIC
  freeze / T1.5?

---

## 8. RUBRIC

Rate each dimension per surface with the pinned enum `strong | adequate | weak | absent | n/a`.
`n/a` is correct and costless where a dimension does not structurally apply -- never manufacture a
rating or a finding to fill a cell. Every dimension is referenced by at least one question or
deep-dive; every question is served by at least one dimension.

- **VD1 Non-redundancy** -- each live decision governs distinct territory; overlap is deliberate,
  not accidental. *(Q1)*
- **VD2 Growth-direction** -- a mechanism acts on the rate/shape of growth (what becomes a
  decision; what happens when one supersedes), not only on total size. *(Q2)*
- **VD3 Intent-explicitness** -- semantic intent is a first-class, addressable element of the
  record. *(Q3a/Q3b)*
- **VD4 Consumer-intent-fidelity** -- the consumers (scout, SCD2 backfill) reason about
  intent-alignment, not only literal text. *(Q3c)*
- **VD5 Consolidation-lifecycle** -- a *built* path exists to merge/compact/supersede so the live
  surface stays bounded (a named-but-unbuilt valve rates `weak` or `absent`, not `adequate`). *(Q1/Q2)*
- **VD6 Artifact-granularity** -- the decision is the right grain; the ratification lane produces
  right-sized artifacts. *(Q2/Q4)*

Surfaces to rate: `DECISIONS.md-corpus`, `decision-entry.yaml`, `decisions_md.py+DecisionPayload`,
`validate_decisions_size.py`, `decision-scout`, `Decision-105-ratification-lane`. Use `n/a`
freely where a dimension does not apply to a surface (e.g. VD3 is `n/a` for the size guard).

---

## 9. DEEP-DIVES

Each block traces end-to-end and feeds named questions.

**DD-A -- The overlap census (feeds Q1).** Build the cluster map. Start from the full header map
(Section 5) and the Section 11 seed clusters. For each candidate cluster: read the member entries
(the seeds, in full), state the *shared governing territory* in one sentence, then adjudicate
whether the separation is redundancy (same rule, restated) or deliberate (distinct clauses that
happen to share a subject). Watch the immutability tension (Q4): a supersession *chain* is not
redundancy -- superseded entries are provenance. Distinguish "these should be one entry" from
"these are correctly separate entries about one subject." Output: the `consolidation_clusters`
block + the Q1 mechanism verdict.

**DD-B -- The growth engine (feeds Q2, Q4).** Trace *why* the corpus grows. Characterize the
Decision-105 ratification lane: read a sample of ratify-CD entries (Section 11), measure their
size and their stated effect, and judge whether a full-prose immutable `## Decision N` entry is
the right artifact for a candidate-decision state-flip, or whether a lighter class / batch /
front-matter-only record would serve. Cross-check against the size guard's headroom (Section 10).
Then answer: is the byte ceiling a growth-*direction* mechanism or a growth-*symptom* guard, and
what would a direction mechanism look like (the external checklist is your yardstick)?

**DD-C -- Intent capture end-to-end (feeds Q3).** Trace the record -> parser -> schema -> consumer
path for intent. Read what `problem`/`decision_text`/`context` capture today
(`decisions_md.py:233-235`, `decision.py:35-37`) and judge whether intent is genuinely absent or
merely unlabeled within `context`/`Rationale`. Then design: the marker (in `decision-entry.yaml`),
the column (in `DecisionPayload`, with the DQ-annotation caveat that `raw_block` documents at
`decision.py:41-46`), the SCD2 grain (Q3b), and the scout triage bucket (Q3c) -- specify each as a
finding with an `acceptance` command. Confront NS-3's cost bar: does captured intent buy the
alignment guarantee, or is `context` already enough?

---

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every anchor was read from disk at compose
time on a recent `origin/main`; some may have shifted -- **verify each before relying on it**, and
record any that does not resolve in `meta.stale_anchors`. Facts are stated neutrally; no fact here
is a verdict.

- `docs/DECISIONS.md` -- live corpus. At compose time: **103** `## Decision` headers, **398,438
  bytes**. Highest number **143**; numbering has gaps (archived/renumbered entries).
- `scripts/checks/decisions/validate_decisions_size.py:17-19` -- ceilings
  `_DECISIONS_LIVE_MAX_BYTES = 400_000`, `_DECISIONS_LIVE_MAX_H2 = 120`,
  `_DECISIONS_COMBINED_MAX_BYTES = 700_000`. Registered (`:64`) `owner="platform"`; the docstring
  (`:1-9`) states it runs in both `--pre` and full tiers. `_RELIEF_VALVES` (`:21-25`) names
  archival (DPI-04) and "compact superseded decision bodies to pointer stubs."
- `docs/contracts/decision-entry.yaml:39-56` -- `required_markers` = Status, Date, Decision;
  `optional_markers_fixed_spelling` = Problem, Rationale, Reversal conditions, Related, Warehouse
  ID. No marker named "Intent". `size_governance:` (`:101-109`) restates the three ceilings and
  says approaching them "is a signal to archive ... or compact ... not to raise the ceiling."
- `src/schemas/decision.py:22-52` -- `DecisionPayload` fields include `problem`, `decision_text`,
  `context`, `related_decisions`, `raw_block`, `reversal_conditions`, `superseded_by`,
  `content_hash`, `created_timestamp`, `last_updated_timestamp`. No field named `intent`. The
  `raw_block` comment (`:41-46`) explains why parity fields are plain `str | None`, not
  `Dq`-annotated.
- `scripts/decisions_md.py:202-246` -- `parse_decisions_md` builds the per-entry dict;
  `context` (`:235`) extracts from `Rationale`/`Key details`/`Context`; `reversal_conditions`
  (`:238`) from `Reversal conditions`. `content_hash` (`:228`) is the SCD2 change key.
- `.claude/skills/decision-scout/SKILL.md:28` -- "Read the **entire** `docs/DECISIONS.md` -- do
  not Read with offset/limit" (the whole-file read; the line's parenthetical still says "currently
  67", a stale figure the skill re-derives at runtime). Triage buckets at `:41-45`: CITE /
  CONTRADICT / RELATED / IRRELEVANT. CONTRADICT is defined (`:43`) as "the proposed approach
  violates an active decision." No alignment-with-intent bucket exists.
- `docs/DECISIONS.md:1920` -- Decision 105, the candidate-decision ratification lane.
  `docs/DECISIONS.md:447` -- Decision 134 (size ceiling + prose ratification; cl.2 the ceilings,
  cl.4 the SCD2/parity direction). `docs/DECISIONS.md:314` -- Decision 136, a ratify-CD entry that
  states it "gates no tier_item (gates: []), so ratification carries no completion-gate side
  effect; it removes CD.39 from the pending / realization-candidate surfaces."
  `docs/DECISIONS.md:298` -- Decision 137, another ratify-CD entry. `docs/DECISIONS.md:4143` --
  Decision 43 "Directed Growth Governance" (code SLOC/complexity/tool-tiers; TRAP-1).
- `docs/ROADMAP-PLATFORM.yaml` -- tier item **T1.5** (`status: not_started`, `strategic: true`):
  `ops_decisions` graduation that retires `DECISIONS.md`; its exit criteria require a read portal +
  a content-parity check before retirement.
- Prior audits (dedup/do-not-redo): `audits/decisions-authoring-format-d140093.yaml` (DAF-01..04),
  `audits/decision-log-premise-integrity-8fb581e.yaml` (DPI-01..07).

Observed at compose time (verify, then judge): **25 of 103** live titles begin "Ratify"; **22 of
103** contain "supersede" or "amend"; the live file is within **~1,562 bytes** of the 400,000-byte
ceiling.

---

## 11. EMPIRICAL PASS

Bound the corpus read hard. Reading all 103 entries in full is NOT required and is discouraged.

- Read the **full header map** (one `rg -n '^## Decision '`) -- cheap, mandatory.
- Read **in full** the seed clusters below (~35 entries total). These are candidates, not
  confirmed overlaps -- adjudicate each.
- Sample **up to 15 ADDITIONAL** live entries not in a seed cluster, chosen to probe for overlap
  the seeds missed (e.g. adjacent numbers, shared title keywords). **Do NOT exceed 15.**
- Read **up to 8** ratify-CD entries for DD-B (the "Ratify"-titled set). **Do NOT exceed 8.**
- State your coverage in `meta.contract_notes` ("read N of 103 in full; sampled M ratify-CD").

Seed clusters for DD-A (adjudicate; do not assume redundancy):
- **Telemetry:** Decisions 95, 96, 97 (trace/observation model; temporal; identity).
- **DuckLake/ops-store:** Decisions 78, 81, 84, 88, 99, 107, 124.
- **Size/structural governance:** Decisions 43, 102, 114, 128, 130, 134.
- **Workflow architecture lineage:** Decisions 42, 90 (and 38, 57, 58, 59 as a supersession
  chain -- immutability test).
- **CI/validation tiering:** Decisions 60, 73, 135.
- **Ratify-CD set (DD-B sample source):** Decisions 106-141 whose titles begin "Ratify"
  (e.g. 136, 137, 140, 141).

**Counterfactual test per candidate cluster:** "If these entries were merged into one, what
governing distinction or supersession-provenance edge would be *lost*?" If nothing is lost, the
cluster leans `merge-into-one`/`compact-to-stub`; if a live clause or a provenance edge dies, it
leans `keep-separate`. Tag each finding `evidence_kind: static` (from reading) or `observed` (from
running the parser probe); an `observed` finding outranks a `static` one at equal severity.

---

## 12. METHOD

Phases run in order; synthesis and maturity are LAST.

- **P1 Read.** Setup (Section 5); read the header map, the in-scope surfaces (Section 4), the seed
  clusters (Section 11), and the governing decisions.
- **P2 Trace.** For each candidate (Section 10) and cluster (Section 11), trace to file:line before
  judging. No verdict without a trace.
- **P3 Deep-dive.** DD-A (overlap census), DD-B (growth engine), DD-C (intent path).
- **P4 Empirical.** The bounded corpus sample + the counterfactual test (Section 11); optional
  parser probe (Section 5).
- **P5 Rate.** The rubric (Section 8), per surface.
- **P6 Dedup.** Section 13, before filing anything.
- **P7 Synthesize.** Findings, `consolidation_clusters`, question answers, rejected candidates,
  summary; THEN compute maturity (Section 15) last.

---

## 13. DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding.

- Search `logs/.recommendations-log.jsonl` (open recs), `docs/ROADMAP-PLATFORM.yaml` (tier_items +
  candidate_decisions), and the two prior audit YAMLs (`decisions-authoring-format-d140093.yaml`,
  `decision-log-premise-integrity-8fb581e.yaml`). Record `dedup_search_terms` and
  `dedup_hit_count` on every finding's `roadmap_crossref`.
- A hit means the finding is `planned-insufficient` (the owner's remedy does not cover this) or
  belongs in `rejected_candidates` (fully covered) -- never a fresh `novel` discovery.
- A finding with no recorded negative search is a **HYPOTHESIS** (`confidence: HYPOTHESIS`),
  regardless of how sure you are.

**Deliberate constraints -- do NOT flag these (each is decided):**
- Prose-monolith authoring is retained until T1.5 (Decision 134 cl.1).
- The ceiling values 400,000 / 120 / 700,000 exist and are ratified (Decision 134 cl.2) -- you may
  argue the ceiling is a *symptom* mechanism (Q2), but "there is no ceiling" is false and
  DAF-owned.
- ETL parity fields + fidelity tripwire (DAF-01) and the authoring grammar + shared parser
  (DAF-03) have landed -- do not re-file them.
- Dead-corpse annotation, warehouse-ID keyspace drift, archival-policy reconciliation, duplicate
  Decision 26/72 (DPI-01..07; rec-2057/2058/2059/2278/1964 open) -- do not re-file; reference only.
- The DuckLake sole-backend and the T1.5 destination (Decision 84) are decided.
- The Decision-105 ratification lane *exists* by ratification -- Q4 may assess its *granularity*,
  but do not propose deleting the lane.
- The Decision-67 STRATEGIC-plan freeze is in force -- a remedy that needs it lifted is
  `planned-unbuilt`/blocked, flagged in `sequencing`, not a defect of this surface.

---

## 14. OUTPUT

Write exactly two files. Pin every enum inline (below). Prose report <= ~1500 words.

`audits/decision-consolidation-growth-<sha>.yaml`:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported name>, methodology_version: 1,
         scope_surfaces: [DECISIONS.md-corpus, decision-entry.yaml,
           decisions_md.py+DecisionPayload, validate_decisions_size.py, decision-scout,
           Decision-105-ratification-lane],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: warranted|partial|not-warranted, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: "",
       external_checklist: [{property: <name>, rating: met|partial|missed, evidence: ""}]}   # 9 rows
    - {q: Q3a, verdict: adopt|adopt-scoped|reject, basis: [], prose: ""}
    - {q: Q3b, verdict: adopt|adopt-scoped|reject, basis: [], prose: ""}
    - {q: Q3c, verdict: adopt|adopt-scoped|reject, basis: [], prose: ""}
    - {q: Q4, answers: [{question: "", answer: "", basis: [<finding ids>]}]}   # seeds + your own
  consolidation_clusters:                 # the Q1 decision block; one entry per adjudicated cluster
    <cluster_name>: {verdict: merge-into-one|supersede-and-archive|compact-to-stub|keep-separate,
                     member_decisions: [<numbers>], overlap_basis: "", what_changes: "",
                     cost: "", provenance_lost: "", rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: <name>, maturity: <derived last>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface, dimension: VD1..VD6, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|decision-N", note: ""}
  findings:
    - {id: DCG-01, surface: <surface|shared>, question: Q1..Q4, dimension: VD1..VD6,
       title, evidence: "file:line|decision-N", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [finding or item ids], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match, decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>,
            maturity_DECISIONS.md-corpus: <value>, maturity_decision-scout: <value>,
            maturity_Decision-105-ratification-lane: <value>}
```

**COUNTING INVARIANT (state it verbatim in the report):** `findings[]` is the SOLE enumerated
list; `total_findings = len(findings) = novel_count + planned_insufficient_count +
planned_unbuilt_count`; fully-covered candidates live in `rejected_candidates`, NOT findings;
`rubric_ratings`, `question_answers`, and `consolidation_clusters` are systems-of-record
referenced FROM findings, never re-counted; `top_improvements` and `highest_leverage_change` MUST
be finding ids.

- `control_property_match` is REQUIRED whenever a compensating control is the dismissal reason:
  name the property the control exercises, cite where it operates, and state why it would FAIL if
  the defect were real.
- `CONFIRMED` requires the behavior traced to file:line or an observed sampled artifact; anything
  less is `HYPOTHESIS`.
- A `consolidation_clusters` entry with verdict `keep-separate` is a valid, expected outcome and
  does NOT require a finding.

The companion `.md`: the executive layer a human reads first -- one-paragraph verdict, the Q1
cluster table (cluster | members | verdict | one-line basis), the Q2 external-checklist scorecard,
the Q3 three-part disposition, the maturity line with its justification, and the dedup posture.
<= ~1500 words.

---

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing.

- **critical** = the governance surface can produce a wrong-but-trusted outcome (e.g. an agent
  obeys a consolidated/merged rule that silently dropped a live governing clause; a plan passes the
  scout gate while violating corpus intent in a way that reaches production).
- **high** = a weakness that materially reduces the log's decision-support guarantee AND whose
  compensating controls you judged insufficient (e.g. growth is unbounded in a way the byte guard
  cannot catch and no other mechanism does).
- **medium** = redundancy / ambiguity / granularity issue with a clear fix (e.g. a genuine merge
  cluster; the ratify-CD artifact-weight).
- **low** = clarity / wording / documentation.

**Compensating-control property-match:** a control lowers severity or justifies dismissal ONLY if
it exercises the same property AND would fail if the defect were real (apply the counterfactual to
the control). The byte-ceiling guard does NOT property-match a *content-overlap* or
*intent-absence* defect -- it counts bytes; it cannot see two entries governing the same territory,
nor a missing intent field. State this explicitly wherever the guard is raised as a control.

**Maturity** -- compute LAST, per surface, top-down, first match wins. Pin these thresholds:
- **frontier** = 0 open critical AND 0 open high findings for the surface, AND every property in
  Q2's `external_checklist` rated `met` or `partial` (never `missed`).
- **strong** = 0 critical AND <= 1 high.
- **solid** = <= 1 critical.
- **nascent** = otherwise.

The frontier tier remains reachable if you argued a property-matched compensating control for a
checklist property (rate it `partial`, not `missed`); the framing here must not foreclose it.

---

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This SHA
   IS the audited tree; use it in both deliverable filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/decision-consolidation-growth-<sha> origin/main` -- so the PR diff is only
   your two files. (Deliberate, documented exception to the `claude/*` session-branch rule: the
   audit session needs a clean two-file diff off the audited base. The CI signal-green comment-wake
   fires only on `claude/*` PRs -- irrelevant here, because you end your turn without merging; the
   human disposes.)
3. Repo-wide validation is advisory outside CI: a clean YAML parse of the two deliverables is the
   real pre-push gate. An unrelated `validate --pre` failure goes in `meta.contract_notes`, never
   fixed (write boundary).
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign`
   (signing is unavailable in this harness; unsigned is expected). Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=`main`, ready for review, NOT draft),
   title: `audit: decision-log consolidation + growth direction + semantic-intent capture`, body =
   the `summary` block in a yaml fence + a 2-3 sentence lede naming the three axes.
6. **END THE TURN.** Do not poll, do not merge, do not subscribe, do not self-approve.

---

## 17. GUARDRAILS

- **Write boundary (closed list):** the ONLY files you create or modify in the tree are
  `audits/decision-consolidation-growth-<sha>.yaml` and `audits/decision-consolidation-growth-<sha>.md`.
  Regenerating gitignored caches per Section 5 is expected; never commit them. Touch no decision,
  contract, schema, skill, or check file -- you are auditing them, not editing them.
- **Precision over volume.** Fewer than ~6 surviving findings is a valid result -- state it; do not
  pad. A `keep-separate` verdict on every cluster, if that is what the trace shows, is a valid and
  honest Q1 answer.
- **No verdict smuggling from this prompt.** The candidate observations and cluster seeds are
  hypotheses. If the corpus is less redundant than the seeds suggest, say so and reject them.
- **Stay inside the axes.** Format (DAF), premise/keyspace (DPI), and context-window architecture
  (parallel audit) are out of bounds -- name overlaps in `meta.contract_notes`, do not audit them.
- **Honesty on coverage.** If you read N of 103 entries, say N. If the dedup caches were
  unavailable, `degraded_dedup=true` and every affected confidence downgraded. A grounding claim you
  could not verify is re-anchored or dropped -- never shipped as fact.
