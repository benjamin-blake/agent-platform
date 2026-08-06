# AUDIT: Decision / contract / change-record content routing, and why prior interventions eroded

## TASK

Audit the content-routing frontier in this repository: which durable content belongs in a numbered
`## Decision NNN:` entry, which belongs in a machine-readable contract under `docs/contracts/`,
and which belongs in a change record (commit message / PR body) -- plus the mechanisms, if any,
that make the correct routing happen rather than merely stating it. Five surfaces are in scope
(S1-S5, enumerated under SCOPE). The audit runs three arcs: **Arc A (diagnosis)** -- why four
prior audit-driven intervention rounds in this territory produced only short-term relief; **Arc B
(end-state)** -- what the separation between the three record types should be; **Arc C
(transition)** -- the ordered path from here to there, with blockers, reversibility, and abort
criteria. Nine questions (Q1-Q9) and six rubric dimensions (VD1-VD6) are pinned below.

Deliverables, and the ONLY files you create or modify anywhere in the repository tree:

- `audits/contract-first-governance-<base-short-sha>.yaml`
- `audits/contract-first-governance-<base-short-sha>.md`

Regenerating gitignored local caches per SETUP is expected and does not breach that boundary;
never commit them. You draft; the human disposes. You open a pull request and end your turn --
you do not merge, and nothing you recommend takes effect from this audit alone.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** Every candidate under GROUNDING MAP
is a neutrally-phrased observation or an unadjudicated hypothesis. Several will turn out to be
correct-by-design, adequately compensated, or already owned. **A run that merely confirms the
candidates below has failed.**

Adjudicate each candidate to exactly one of:

| Adjudication | Goes to |
|---|---|
| CONFIRMED defect, not owned by any existing item | `findings[]`, `roadmap_crossref.classification: novel` |
| Owned by an existing item, but that item's remedy is insufficient | `findings[]`, classification `planned-insufficient` |
| Owned by an existing item whose remedy is designed but unbuilt | `findings[]`, classification `planned-unbuilt` |
| Owned and fully covered by the existing item | `rejected_candidates[]` (never `findings[]`) |
| Not a defect -- a compensating control covers it | `rejected_candidates[]`, naming the control |

Severity is never inherited from this prompt's framing. Assign it after judgment, per SEVERITY.

## READ FIRST -- disambiguation traps

Six terms in this repository name two different things. Misreading any of them will send an
entire arc of this audit at the wrong target.

1. **"Contract" names two populations with different governance.** `docs/contracts/` holds (a) a
   **ritual** population carrying a top-level `contract:` block with a `class:` field (Class A =
   table/field schemas, Class B = Lambda verb surfaces, Class C = cross-system identifier
   invariants), schema-validated by `scripts/contracts.py` and gated by
   `validate_contract_drift`; and (b) a **free-form** population with no `contract:` block --
   registries, grammars, routing indexes, procedure carriers. A recommendation to "move this
   content into a contract" is TWO DIFFERENT recommendations depending on which population you
   mean. Never write "contract" unqualified in a finding; write "ritual contract" or "free-form
   contract".
2. **"Decision" names two things.** A numbered `## Decision NNN:` entry in `docs/DECISIONS.md`
   (ratified, immutable-by-convention), and a `candidate_decision` `CD.NN` in
   `docs/ROADMAP-PLATFORM.yaml` (pending, binding until ratified or superseded). They have
   separate lifecycles, separate guards, and separate numbering authorities.
3. **`validate_contract_drift` does not detect contract-vs-code drift.** Despite the name it
   gates *ritual-schema* drift: YAML parseability, schema conformance, `$ref` resolution,
   amendment-log presence on changed contracts, and status transitions. Whether a contract's
   stated semantics still match the code implementing them is a different property. Do not treat
   the check's existence as coverage of the second property, and do not treat the name as
   evidence of either.
4. **Four decision surfaces exist, not one.** `docs/DECISIONS.md` (live), `docs/DECISIONS_ARCHIVE.md`
   (archived), `docs/decisions-index.json` (a committed generated projection consumed by the
   decision-scout gate), and the `ops_decisions` warehouse table (backfilled from the markdown).
   A claim about "the decision log" must name which.
5. **Two artifacts both look like "the decision contract".** `docs/contracts/decision-entry.yaml`
   is the *authoring grammar* for markdown entries. `docs/contracts/ops_decisions.yaml` is the
   Class A *table schema* for the warehouse projection. They govern different layers.
6. **Decision 150's significance BAR is not the `**Significance:**` STANZA.** The bar is a
   `significance:` section inside `decision-entry.yaml` describing four routing rows. The stanza
   is a bold marker some entries carry in their body. Whether the stanza is required, optional,
   or unmentioned by the contract is a question for you, not an assumption -- re-derive it.

Two plausible-but-wrong audit targets: this is **not** an audit of whether individual past
Decisions were correct, and **not** an audit of the warehouse ETL's fidelity (that was covered by
a prior audit -- see DEDUP DISCIPLINE). The target is the routing rule, its enforcement, and why
prior fixes to it did not hold.

## SCOPE

### Surfaces

| ID | Surface | State |
|---|---|---|
| S1 | The decision corpus: `docs/DECISIONS.md`, `docs/DECISIONS_ARCHIVE.md`, `docs/decisions-index.json`, and their guards under `scripts/checks/decisions/` | built |
| S2 | The **ritual** contract population under `docs/contracts/` (files carrying `contract:` + `class:`) and its enforcement (`scripts/contracts.py`, `scripts/contracts_schema.py`, `scripts/contracts_enforcement.py`, `scripts/checks/contracts/validate_contract_drift.py`) | built |
| S3 | The **free-form** contract population under `docs/contracts/` (files with no `contract:` block) | built |
| S4 | The authoring/routing instruction layer: `AGENTS.md`, `.claude/skills/planning/SKILL.md`, `docs/contracts/decision-entry.yaml`, `docs/contracts/instruction-architecture.yaml`, `docs/contracts/file-router.yaml`, `docs/PROJECT_CONTEXT.md` | built |
| S5 | The change-record surface: the commit-message conventions table in `AGENTS.md` and `.github/pull_request_template.md` | built |

Out of scope, one line each: the warehouse ETL's field-level fidelity (prior audit owns it); the
correctness of any individual past architectural choice; the roadmap's own sequencing; anything
under `terraform/`; the trading product.

### Vocabulary this audit uses

- **Rationale** -- why a choice was made over alternatives, and what would reverse it.
- **Specification** -- what is normatively true now: shapes, enums, grammars, thresholds,
  procedures, enforcement rules.
- **Change record** -- what changed in this commit and why now.
- **Routing** -- assigning a unit of durable content to exactly one home.
- **Forcing function** -- a mechanism that makes the correct routing happen without relying on
  the author electing it (as distinct from a stated rule, a convention, or a self-certification).
- **Erosion** -- an intervention producing measurable relief that later reverses, whether by
  ceiling raise, disuse, or the intervention's own cost.

### Constraints you MAY challenge -- price them first

This audit deliberately places the decision architecture itself inside the blast radius. Nothing
in the following list is a do-not-flag. Each may be challenged, superseded, or recommended for
retirement. But each carries a real cost, and a challenge that does not price its cost is a
HYPOTHESIS, not a finding.

| Constraint | Where | Cost of challenging it |
|---|---|---|
| Never remove a `## Decision N:` heading; never retire or reuse a number | `decision-entry.yaml` `compaction.stub_grammar.never_remove_headers`; Decision 149 | Inbound `Decision N` citations across the repo. The contract states ~12,103; a working-tree count measured 18,988 (see GROUNDING MAP G14 -- re-derive both, they disagree). A retirement mechanism must state how each is resolved. |
| Numbered entries are immutable; later changes come as new numbered entries or dated in-place annotations | Decision 149, `decision-entry.yaml` `amendment_forms` | Provenance and the `ops_decisions` SCD2 history model assume append-not-rewrite. |
| The significance bar gates what may become a Decision | Decision 150; `decision-entry.yaml` `significance:` | It is the only stated front-door control; removing it without a replacement removes the only one. |
| Fully-superseded entries move to the archive | Decision 146 | Archived entries leave the file most agents read by default. |
| Live-header ceiling 120; combined byte ceiling 700,000; committed-index byte pin | `validate_decisions_size.py`; `tests/test_decisions_index.py` | These are the only mechanical backstops on corpus growth. |
| The CD.25 Class A/B/C ritual is the contract shape | Decision 118 | Extending, replacing, or adding a class changes what `validate_contract_drift` can enforce. |

Two boundaries are NOT open, because they govern how you write rather than what you may conclude:

- **Public-repo content boundary** (Decision 101): never write AWS account IDs or ARNs, IAM
  ExternalIds, credentials, internal hostnames, or trading-strategy performance into your
  deliverables.
- **Single Portal Invariant** (Decision 84): do not write to `logs/.recommendations-log.jsonl`,
  `logs/.decisions-index.jsonl`, or any warehouse staging path. Your deliverables are the two
  files named in TASK; you file no recommendations.

### Trust nothing

Obtain every file path, line anchor, count, size, and date by reading the repository yourself.
Every number in this prompt was measured at compose time on a working tree and may have moved.
Trust no figure quoted here -- re-derive it, and record any anchor that does not resolve in
`meta.stale_anchors` with what you found instead. Where your re-derivation disagrees with this
prompt, YOUR measurement is the evidence and the disagreement is itself worth a line in
`meta.contract_notes`.

## SETUP

Run these, in order, from the repository root. Python is invoked as `bin/venv-python` -- never
bare `python` or `python3`. Each shell invocation is independent; do not rely on activating a
virtualenv between calls.

```bash
git fetch origin main
git rev-parse --short origin/main        # this is <base-short-sha>; derive it ONCE
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

The preflight populates `logs/.preflight-report.json` and refreshes
`logs/.recommendations-log.jsonl`. DEDUP DISCIPLINE (below) is mandatory and depends on both.

Degraded paths -- never abort, never improvise:

- **IF preflight fails on credentials or egress:** do NOT abort. Set `meta.degraded_dedup: true`,
  mark every `roadmap_crossref` `confidence: HYPOTHESIS` with `dedup_hit_count: null`, and
  proceed using the committed files (`docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`,
  `docs/decisions-index.json`) plus whatever `logs/.recommendations-log.jsonl` already holds.
- **IF `logs/.recommendations-log.jsonl` is absent entirely:** same flag, and note it in
  `meta.contract_notes`.
- **IF a file:line anchor in GROUNDING MAP does not resolve:** record it in `meta.stale_anchors`
  as `{anchor, expected, found}` and continue from what the file actually says.
- **IF `bin/venv-python -m scripts.validate --pre` fails on something unrelated to your two
  deliverables:** record it in `meta.contract_notes` and do NOT fix it -- that is outside your
  write boundary. Repo-wide validation is advisory outside CI here; a clean YAML parse of your
  two deliverables is the real pre-push gate.

## NORTH STAR

The bar each surface is judged against. These are principles you argue a surface against, not
rules you pattern-match -- a surface may fall short of one and be right to.

- **NS1 -- One assertion, one home.** Any normative statement has exactly one authoritative
  location. A second statement of the same thing is drift by construction, whichever copy is
  "right".
- **NS2 -- Machine-parseable beats prose.** Where two designs are equally valid and one is
  machine-parseable, that one wins. Semantic definitions are collocated with their enforcement.
- **NS3 -- A rule with no evaluator is a suggestion.** Governance that depends on the author
  electing it will hold only as long as authors elect it.
- **NS4 -- Agent-first.** Every artifact is optimised for agent loading efficiency, not human
  readability. Human-readable summaries are query results, not stored artifacts.
- **NS5 -- Bounded, retrievable state.** Governance corpora are indexed and retrieved by
  identifier, not loaded wholesale. Growth is bounded by a mechanism that does not itself consume
  the resource it rations.
- **NS6 -- The cure must be cheaper than the disease.** An intervention whose own cost is drawn
  from the scarce resource it protects is self-limiting; judge each intervention's net effect,
  not its stated intent.

## THE QUESTIONS

Each question gets a first-class entry in `question_answers[]` with the verdict enum pinned here.

### Q1 -- Erosion (Arc A keystone)

Four prior audits landed in this territory and their findings drove a lineage of numbered
Decisions (see GROUNDING MAP G8 and EMPIRICAL PASS E1). Each produced relief. The corpus is now
at or near its ceilings again.

For each prior intervention: what did it change, what relief did it produce, how long did that
relief hold, and what specifically ended it? Classify the ending: ceiling-raised /
mechanism-unused / superseded-by-a-larger-entry / cost-exceeded-benefit / relief-still-holding /
other (name it). Then answer the aggregate question: **is there a single recurring mechanism that
causes interventions in this territory to erode, or is each erosion independent?**

Every finding you file in Arc B or Arc C must name which Q1 failure mode it is designed to
survive, in `survives_failure_mode`. A recommendation that cannot name one is a candidate ninth
intervention.

**Verdict enum:** `primary-mechanism-identified` | `contributing-factors-only` | `undetermined`

### Q2 -- Routing decidability, against external practice

Is there a sound, **decidable** rule today that assigns a unit of durable content to exactly one
of {numbered Decision, ritual contract, free-form contract, change record, roadmap tier_item,
recommendation}? Decidable means: two competent authors, given the same content and only the
stated rule, reach the same home without further judgment.

This question carries an **EXTERNAL CHECKLIST**. Rate each property `met` | `partial` | `missed`
with evidence, in `question_answers[].external_checklist`. This field is the SOLE source the
`frontier` maturity tier reads. `partial` requires an argued, property-matched compensating
control in its evidence.

| ID | External property |
|---|---|
| EX1 | **ADR discipline** (Nygard / MADR): a decision record is immutable, covers one decision, and carries context / decision / status / consequences -- it records *why this choice*, and does not double as the specification of the thing chosen. |
| EX2 | **Normative vs informative separation** (IETF RFC 2119, ISO/IEC directives): normative requirements live in a specification surface and are labelled as such; rationale and discussion are explicitly non-normative and cannot be cited as a requirement. |
| EX3 | **Contract-first / spec-first authoring** (OpenAPI, Protobuf, JSON Schema): the machine-readable specification is authored with or before the implementation, and the implementation plus its tests bind to it as the single source. |
| EX4 | **Policy-as-code** (OPA/Rego, Conftest): governance rules are executable and versioned artifacts, not prose. A rule with no evaluator is not a rule. |
| EX5 | **Bidirectional traceability**: requirement -> implementing artifact -> verifying check, with orphan detection on BOTH sides (a requirement with no check, and a check with no requirement). |
| EX6 | **Change-record granularity**: the commit/PR message carries what changed and why now; the specification carries what is true; the decision record carries why this choice. Three questions, three homes. |
| EX7 | **Deprecation and supersession lifecycle**: superseded records are marked, discoverable, and shed weight; the corpus is not monotonically growing. |
| EX8 | **Bounded retrieval**: the governance corpus is indexed and retrieved by identifier rather than loaded wholesale into every consumer. |

**Verdict enum:** `sufficient` | `partial` | `insufficient`

### Q3 -- Why an author reaches for a Decision

Given the routing surfaces that exist, what structurally causes an agent authoring a change to
mint a numbered Decision rather than amend a contract? Trace the mechanics, not the motives:
consider (and reject or confirm) at minimum -- the amendment-by-forward-reference convention and
whether it manufactures reversal-relevance; the presence or absence of an authoring ritual,
review lane, or warehouse projection on the contract side; whether the significance bar is
self-certified and by what evidence; whether any contract exists whose declared subject is
"mechanism" as opposed to "field semantics"; and the relative discoverability of the two
destinations.

**Verdict enum:** `primary-cause-established` | `contributing-only` | `undetermined`

### Q4 -- Destination readiness

If content migrates out of S1 and into S2 or S3, does the destination carry equal-or-better
governance? Compare S1, S2, and S3 property-by-property on at least: schema validation, authoring
grammar, amendment/change log, status and supersession lifecycle, size governance, binding to
code, discoverability by index or router, warehouse projection, and review lane. Where the
destination is weaker, say what a migration would lose and whether that loss matters.

**Verdict enum:** `ready` | `ready-with-gaps` | `not-ready`

### Q5 -- Contract-side detection gaps

Three properties, assessed separately, each with its own rating in the answer prose:

- **(a) Parallel contracts** -- two artifacts asserting the same semantics in different places.
- **(b) Contradictory contracts** -- two artifacts asserting incompatible semantics.
- **(c) Contract-code drift** -- a contract's stated semantics no longer matching the code.

For each: is it detectable today, by what, over what subset of the population, and what is the
minimum mechanism that would detect it? Where you propose a mechanism, state its false-positive
behavior and what it costs to run.

**Verdict enum:** `sufficient` | `partial` | `insufficient`

### Q6 -- The change-record leg

What content routinely lands in a Decision that a commit message or PR body should carry
instead? Is governance of the change-record surface warranted, or is its current near-absence
correct? Answer both directions -- a finding that the absence is correct is as valuable as one
that it is not.

**Verdict enum:** `governance-warranted` | `absence-correct` | `partial`

### Q7 -- End-state (Arc B)

What SHOULD the separation between the three record types be in this repository? You have full
latitude: propose new record types, new templates, new contract classes, a different corpus
architecture, or the retirement of an existing surface. You may conclude that `docs/DECISIONS.md`
should stop being a prose corpus. You may conclude the current architecture is right and only its
enforcement is wrong.

Constraints on the ANSWER, not on its content: it must state (i) the routing rule in decidable
form, (ii) the forcing function that makes each routing happen, (iii) which Q1 failure mode each
forcing function survives, and (iv) what it costs -- in authoring effort, in agent context, and
in migration. An end-state with no forcing function is a restatement of the problem.

**Verdict enum:** `single-end-state-recommended` | `options-with-tradeoffs` | `insufficient-evidence`

### Q8 -- Transition (Arc C)

How do we get from the current state to the Q7 end-state, in what order? Populate the
`migration_sequence` block: ordered steps, each with its blocker, its reversibility, a
pre-committed abort criterion, and the Q1 failure mode it is designed to survive. Name what must
happen FIRST and why. If any step cannot proceed without a human ruling, name the ruling.

Content classification is part of this answer. Default shape: a **class taxonomy** -- named
classes of live entry, each with a routing verdict, a worked exemplar traced end-to-end, and a
count -- rather than a per-entry ledger over all live entries. Override that default only if your
Q7 end-state makes per-entry classification unnecessary or insufficient, and say so.

**Verdict enum:** `ordered-sequence-with-abort-criteria` | `partial-sequence` | `insufficient-evidence`

### Q9 -- Questions not asked

What did the requester not think to ask? Seeded below -- you must ANSWER these AND extend them
with your own:

- Does the act of auditing this territory repeatedly have a cost that the audits themselves have
  never accounted for?
- Is the growth of the decision corpus a symptom of decision-log design, or of something upstream
  -- how work is decomposed, how plans are scoped, or how amendments are triggered?
- Is there a class of content that belongs in NONE of the six homes, and is being forced into one?
- If the corpus were rebuilt from scratch today with full knowledge, how many of the current live
  entries would exist at all?

Uses the `answers[]` shape, not a verdict.

## RUBRIC

Rate every dimension for every surface S1-S5. Pinned enum: `strong` | `adequate` | `weak` |
`absent` | `n/a`. **`n/a` is correct and costless where a dimension does not structurally apply
to a surface** -- never manufacture a rating, and never manufacture a finding to fill a cell.

| ID | Dimension |
|---|---|
| VD1 | **Routing decidability** -- a cold author can assign content to this surface, or away from it, without judgment beyond the stated rule. |
| VD2 | **Mechanism** -- the rule governing this surface is enforced by something executable, not by convention or self-certification. |
| VD3 | **Governance parity** -- the surface carries lifecycle controls (schema, status, supersession, amendment log, size) proportionate to the authority of the content it holds. |
| VD4 | **Non-duplication** -- one semantic assertion has exactly one home here; parallel or contradictory statements are detectable. |
| VD5 | **Bounded growth** -- content can leave the surface by a working mechanism, and growth is rationed by something that does not itself consume the ration. |
| VD6 | **Discoverability** -- an agent finds the governing artifact by pointer or index rather than by reading the corpus. |

Every question is served by at least one dimension; every dimension is referenced by at least one
question or deep-dive.

## DEEP-DIVES

### DD-A -- The growth-governance lineage (feeds Q1, VD5, NS6)

Trace the lineage of interventions in EMPIRICAL PASS E1 end to end. For each: its trigger, its
mechanism, its size, its date, what it amended or superseded, and what happened next. Compute the
aggregate: total bytes and header slots the lineage consumed, as a share of the live corpus.
Then answer NS6 for this lineage specifically -- was the cure cheaper than the disease? Report
the arithmetic; do not assert the conclusion without it.

### DD-B -- A blocked draft, classified (feeds Q2, Q3, Q7)

The following text is a verbatim draft of a proposed Decision 167, written by an agent and
BLOCKED by the repository operator on the grounds that it is not an architectural decision but
prose around an intended implementation. It is reproduced here as a specimen. It is NOT in the
repository; do not search for it, and do not treat the operator's judgment as a verdict you must
agree with.

```
What Decision 167 would actually say
Roughly one page, four points:

R3's scope extends from .github/actions/** to .github/workflows/** inline run: bodies. R1 and R2
stay composite-only -- the outputs.<id>.value binding R1 keys on, and the action-directory .sh
delegate R2 requires, have no workflow analogue.
A new r3_workflows: section in config/composite_action_body_baseline.yaml, keyed
<workflow-path>::<job-id>::<step-id | name-slug | #index>, seeded markerless at the 127 measured
body sizes.
Enforcement rides the existing validate_composite_action_shell_bodies -- no new registered check
name, since this is one rule gaining scope, not a second rule.
This is the last seeded grandfather in the R3 family. Extraction to scripts/ is the valve; there
is no third seeding.
Plus a reciprocal > **Amended by Decision 167** blockquote on 162, and a Significance: stanza --
Decision 162 carries one of those itself, so that's the corpus convention.
```

Classify each of its five points against the routing rule as it exists today (Q2) and against
your proposed end-state (Q7). For each point, name the home it would take under each. Then answer
two questions:

1. Under today's rule, would this draft have been correctly ROUTED, correctly BLOCKED, or is the
   rule silent? If the rule is silent, that silence is the finding.
2. The work this draft describes did land in the repository. Locate what actually shipped for it
   and where the content went. State whether the outcome matches either routing.

### DD-C -- Migration feasibility, traced (feeds Q4, Q8)

Select THREE live entries spanning different candidate classes -- do not exceed three. Trace each
end-to-end through every mechanism the repository offers for moving content off S1: archival,
compact-in-place, and any migrate-then-rehome path the repository describes. For each entry
report what blocks it, which mechanism (if any) can process it, and what a successful migration
would cost. If none of the three can be processed by any existing mechanism, that is the finding.

### DD-D -- The two contract populations, compared (feeds Q4, Q5)

Build the property-by-property comparison Q4 requires, as a table in the companion report. Then
answer the specific question Q5 turns on: for the free-form population, what would it take to
detect that two files assert the same thing, or contradictory things? Consider whether the
question is even well-posed absent a declared subject per contract, and say so if it is not.

## GROUNDING MAP

This map exists to spend your cognition on judgment rather than grep. Every entry was read from
disk at compose time. **Verify each before relying on it** -- files move, counts drift, and a
figure below that no longer holds is itself worth recording (see SCOPE / Trust nothing).

Facts are stated neutrally. Where a phrasing sounds like a defect, it is not: it is an
observation awaiting your adjudication.

| ID | Observed fact | Anchor |
|---|---|---|
| G1 | The drift gate iterates every `docs/contracts/*.yaml`, and `continue`s past any file whose parsed data lacks a `contract` mapping containing a `class` key. Files taking that branch receive `yaml.safe_load` and a mapping-type check only. | `scripts/checks/contracts/validate_contract_drift.py:64-72` |
| G2 | At compose time, 16 of 39 contract files (37 `.yaml` + 2 `.md`) carried a `contract:` block with `class:`; 23 did not. | `docs/contracts/` |
| G3 | `file-router.yaml` carried 82 route entries; 8 of the 39 contract files appeared as a `targets` value; 31 did not. | `docs/contracts/file-router.yaml:24` |
| G4 | 13 of 39 contract filenames produced no match under `scripts/`, `src/`, or `config/`. Caveat you must handle: `load_all_contracts` globs the directory, so a filename-grep undercounts consumers that load by glob. | `docs/contracts/`, `scripts/contracts.py` |
| G5 | `instruction-architecture.yaml` defines 5 layers: universal rules, project knowledge base, slash commands, skills, executor prompts. Neither `docs/contracts/` nor `docs/DECISIONS.md` appears as a layer. The file also carries a 7-entry `anti_patterns` list. | `docs/contracts/instruction-architecture.yaml` |
| G6 | Median live-entry size by decision-number band, measured across 119 live entries: D<=60 = 2,315 B (n=16); D61-100 = 3,898 B (n=37); D101-139 = 3,241 B (n=39); D>=140 = 7,257 B (n=27). | `docs/DECISIONS.md` |
| G7 | Under one proxy for mechanism density -- distinct `docs/contracts/*`, `scripts/**.py`, `config/**.yaml`, `.github/workflows/*` path references per KB -- the same four bands measured 0.33, 0.27, 0.42, 0.38. A recommendation in the ownership surfaces (rec-3023) states density "roughly HALVED (1.7 to 0.8 refs per KB)" across a similar comparison; its metric definition is not stated there. The two do not agree. Choose and STATE your own definition before drawing any conclusion from either. | `docs/DECISIONS.md`; `logs/.recommendations-log.jsonl` |
| G8 | Eight numbered entries governing decision-log growth carry dates from 2026-07-16 to 2026-07-31: D134 (7,182 B), D145 (6,465 B), D146 (4,175 B), D149 (8,210 B), D150 (5,899 B), D151 (11,272 B), D152 (7,587 B), D160 (18,879 B). D160, whose title begins "Retire the DECISIONS.md live-byte ceiling", was the largest live entry measured. D166 (17,240 B, dated 2026-08-04) was the second largest. | `docs/DECISIONS.md` |
| G9 | 28 of 119 live entries contained the string `docs/contracts/`. | `docs/DECISIONS.md` |
| G10 | A `**Significance:**` marker appeared in 7 of 119 live entries. `decision-entry.yaml` lists `required_markers` as Status, Date, Decision, and lists 6 `optional_markers_fixed_spelling`. | `docs/contracts/decision-entry.yaml:39-57`; `docs/DECISIONS.md` |
| G11 | 4 live entries carried `**Status:** Superseded`. Live `## Decision` headers numbered 119; the live+archive byte total measured 684,796. | `docs/DECISIONS.md`, `docs/DECISIONS_ARCHIVE.md` |
| G12 | The size guard's constants are `_DECISIONS_LIVE_MAX_H2 = 120` and `_DECISIONS_COMBINED_MAX_BYTES = 700_000`. The committed-index test pins `_COMMITTED_INDEX_MAX_BYTES = 131_000`, annotated as a Decision 166 re-derivation of a prior 110,000-byte pin. `docs/decisions-index.json` measured 110,582 bytes. | `scripts/checks/decisions/validate_decisions_size.py:20-21`; `tests/test_decisions_index.py:450` |
| G13 | `decision-entry.yaml` carries a `significance:` section with four routing rows -- `numbered_decision`, `cd_state_flip`, `operational_fact`, `field_semantics` -- of which `field_semantics` is the row naming a contract as destination. It separately carries an `amendment_forms:` section describing two dated in-place annotation shapes. | `docs/contracts/decision-entry.yaml:114-143`, `:68-81` |
| G14 | `decision-entry.yaml` states "~12,103 unguarded inbound 'Decision N' citations across the repo". A working-tree count of `Decision \d+` occurrences excluding `logs/` and `.git/` measured 18,988. Re-derive both; state your method. | `docs/contracts/decision-entry.yaml:192` |
| G15 | The commit-message surface is a 5-row prefix table (`feat`, `plan`, `roadmap`, `scope`, `audit`) in `AGENTS.md`, plus a comment block in the PR template naming the same conventions. No check under `scripts/checks/` reads either for content. | `AGENTS.md:190`; `.github/pull_request_template.md` |
| G16 | The planning skill carries two relevant sections: "Documentation Artefact Design", which restates the Decision 86 routing rule, and "Decision Significance Gate", which instructs checking the `significance:` section before drafting any numbered Decision. | `.claude/skills/planning/SKILL.md:225`, `:373` |
| G17 | `validate_decision_entry_conformance` reads `required_markers` from the contract at check time and enforces them on entries whose number is absent from the `origin/main` baseline; historical entries are grandfathered. It advisory-skips when `origin/main` is unreachable. | `scripts/checks/decisions/validate_decision_entry_conformance.py` |
| G18 | The decision-scout gate triages from `docs/decisions-index.json` plus targeted reads of shortlisted entries, and describes the whole-corpus load as the cost it avoids. Its skill file names the arrangement as interim pending a portal cutover owned by roadmap item T1.5. | `.claude/skills/decision-scout/SKILL.md` |
| G19 | The ritual population at compose time spanned Class A (7 files), Class B (3, all `provisional_v0`), and Class C (6). The free-form population included `decision-entry.yaml`, `file-router.yaml`, `deploy-paths.yaml`, `data-modeling-standard.yaml`, `candidate-decision-ratification.yaml`, `instruction-architecture.yaml`, and `marker-grammar.yaml`. | `docs/contracts/` |
| G20 | `decision-entry.yaml` opens with a comment stating it is not a Class A/B/C ritual contract and that the drift gate therefore skips it, citing `file-router.yaml`, `deploy-paths.yaml`, and `read-engine.yaml` as precedent and Decision 118 for the free-form registry pattern. | `docs/contracts/decision-entry.yaml:1-5` |

## EMPIRICAL PASS

Four bounded samples. Tag every finding drawn from a sample `evidence_kind: observed`; findings
drawn only from reading a rule are `static`. **At equal severity, an observed finding outranks a
static one.** Do NOT exceed any bound below.

- **E1 -- the growth-governance lineage (exactly the 8 entries in G8; do not extend).** For each:
  date, size, trigger, mechanism, what it amended, and what superseded or reversed it. This is
  DD-A's input and Q1's primary evidence.
- **E2 -- the 10 highest-numbered live entries; do NOT exceed 10.** For each, partition the body
  by content type: rationale / specification / change-record / other. Report the partition as
  approximate byte or paragraph shares, and state your partitioning rule before applying it.
- **E3 -- at most 8 free-form contracts.** Sample for Q5: does each declare its subject? Could two
  be mechanically compared for overlap or contradiction? What would a comparison key be?
- **E4 -- at most 6 ritual contracts.** The comparison arm for E3 and DD-D.

Apply this counterfactual to every mechanism you assess: **would this check still pass if the
behavior it governs were removed entirely?** If yes, the check does not exercise the property.
Apply the same test to any mechanism you PROPOSE, and report the answer -- a proposed forcing
function that would pass on an empty repository is not a forcing function.

## METHOD

Phases in order. Synthesis and maturity are computed LAST.

- **P1 -- Read.** Every S1-S5 surface named in SCOPE. Re-resolve every GROUNDING MAP anchor.
- **P2 -- Trace (Arc A).** Run E1 and DD-A. Answer Q1 before anything downstream -- Q1's failure
  modes are an input to every later phase.
- **P3 -- Trace (routing).** Run DD-B and DD-D. Answer Q2, Q3, Q5.
- **P4 -- Trace (destination).** Run E3, E4, DD-C. Answer Q4, Q6.
- **P5 -- Rate.** Fill every VD x S cell. Then run E2.
- **P6 -- Design (Arcs B and C).** Answer Q7, then Q8. Populate `migration_sequence`.
- **P7 -- Adversarial convergence. MANDATORY.** For every finding AND for your Q7 end-state,
  attempt to REFUTE it: state the strongest argument that the finding is not a defect, or that
  the end-state is the ninth intervention rather than the last one. Where refutation succeeds,
  move the item to `rejected_candidates[]` or revise the design. Where it fails, record the
  attempt in `refutation`. Then re-run this phase on whatever changed. Repeat until a round
  changes nothing, **to a maximum of 3 rounds**; record the count in `meta.convergence_rounds`
  and, if you exit on the cap rather than on convergence, say what remained unsettled in
  `meta.contract_notes`.
- **P8 -- Dedup.** Apply DEDUP DISCIPLINE to every surviving finding.
- **P9 -- Synthesize.** Answer Q9. Compute severities, then maturity. Write both deliverables.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding.

Surfaces to search: `docs/ROADMAP-PLATFORM.yaml` (`tier_items[]` and `candidate_decisions[]`),
`docs/DECISIONS.md`, `logs/.recommendations-log.jsonl`, and the prior audit outputs under
`audits/`.

Record on every finding: `roadmap_crossref.dedup_search_terms` (what you searched),
`dedup_hit_count`, and `classification`. **A hit means sufficiency-assessment or rejection, never
a fresh discovery.** A finding with no recorded negative search is `confidence: HYPOTHESIS`.

### Known owners in this territory -- assess sufficiency, do not rediscover

Prior audit outputs, all under `audits/` with both `.yaml` and `.md` companions. Read the YAML
`findings[]` lists; do not re-read the corpora they audited:

| Prefix | File stem | Territory |
|---|---|---|
| DAF | `decisions-authoring-format-*` | Authoring grammar, ETL parity, unbounded growth |
| DPI | `decision-log-premise-integrity-*` | Supersession annotation, dead premises, archival policy |
| DCG | `decision-consolidation-growth-*` | Compaction lifecycle, significance/direction, generated index, Intent marker |
| SGE | `size-governance-expansion-*` | Size governance beyond Python; marker-authorization guards |
| ACG | `agent-context-governance-*` | Ambient prose surfaces, context cost, required-context |

Roadmap items already owning adjacent territory -- read each and judge whether its remedy is
sufficient, unbuilt, or off-target for what you find:

- **T2.56** "Normative / contract / ADR layering" -- the closest owner. Forward-intent-only.
  Judge specifically whether its framing (ambient-load cost, retrieval-by-id) covers the
  authoring-time ROUTING question, or is orthogonal to it.
- **T2.54** "Bidirectional clause-to-check traceability" -- EX5's territory.
- **T1.5** (exit criterion c1) -- DECISIONS.md retirement behind a decisions read portal.
- **T1.17** -- premise-integrity follow-ups.

Open recommendations already in this territory. Each is a hit; assess sufficiency:

`rec-3023` (bound and enforce decision body content), `rec-2934` (per-entry authoring size norm),
`rec-3015` (justify why a contract was rejected before minting an entry), `rec-3016` (route
single-call-site tweaks to `amendment_forms`), `rec-2822` (enumerate citation-stranded entries
into a manifest), `rec-2823` (migrate-then-archive branch), `rec-2984` (move runbooks out of
ambient prose into contracts), `rec-2991` (contract silent on block separator), `rec-3001` /
`rec-3012` (index byte pin), `rec-2200` (standing-prose guard underscopes Decision 86).

### Do-not-flag

Only two, both about how you write rather than what you may conclude: the public-repo content
boundary (Decision 101) and the Single Portal Invariant (Decision 84). Everything else in this
repository's decision architecture is inside the blast radius -- see SCOPE / Constraints you MAY
challenge, and price what you challenge.

One planning-time constraint to NOTE (not to obey as an audit boundary): a temporary freeze makes
all plans IMPLEMENTATION-type. If your Arc-C sequence would naturally be a multi-phase strategic
programme, say so plainly and describe how it decomposes into atomic implementation units -- do
not silently shrink the recommendation to fit.

## OUTPUT

Two files, exact paths, where `<sha>` is the `<base-short-sha>` derived once in SETUP:

- `audits/contract-first-governance-<sha>.yaml`
- `audits/contract-first-governance-<sha>.md` -- prose companion, **<= 2500 words**, the
  executive layer a human reads first. Lead with Arc A. Include DD-D's comparison table.

### YAML contract

```yaml
audit:
  meta:
    audited_commit: <origin/main short sha>
    base_branch: main
    model: <your self-reported model name, free text>
    methodology_version: 1
    scope_surfaces: [S1, S2, S3, S4, S5]
    degraded_dedup: false
    convergence_rounds: <int, 1-3>
    contract_notes: ""
    stale_anchors: []          # [{anchor, expected, found}]
  question_answers:
    - {q: Q1, verdict: primary-mechanism-identified|contributing-factors-only|undetermined,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       external_checklist: [{property: EX1..EX8, rating: met|partial|missed, evidence: ""}]}
    - {q: Q3, verdict: primary-cause-established|contributing-only|undetermined, basis: [], prose: ""}
    - {q: Q4, verdict: ready|ready-with-gaps|not-ready, basis: [], prose: ""}
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q6, verdict: governance-warranted|absence-correct|partial, basis: [], prose: ""}
    - {q: Q7, verdict: single-end-state-recommended|options-with-tradeoffs|insufficient-evidence,
       basis: [], prose: ""}
    - {q: Q8, verdict: ordered-sequence-with-abort-criteria|partial-sequence|insufficient-evidence,
       basis: [], prose: ""}
    - {q: Q9, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
  intervention_erosion:
    - intervention: <Decision id or audit finding id>
      date: <ISO>
      size_bytes: <int|null>
      what_it_changed: ""
      relief_produced: ""
      held_until: ""
      ending_class: ceiling-raised|mechanism-unused|superseded-by-larger-entry|cost-exceeded-benefit|relief-still-holding|other
      note: ""
  content_class_routing:
    - class_name: ""
      description: ""
      live_entry_count: <int>
      verdict: migrate-to-ritual-contract|migrate-to-free-form-contract|migrate-to-change-record|compact-in-place|archive|migrate-then-archive|keep-live|other
      mechanism: ""
      worked_exemplar: "Decision NN"
      blocker: ""
      confidence: CONFIRMED|HYPOTHESIS
  migration_sequence:
    - step: <int>
      action: ""
      blocker: ""
      reversible: true|false
      abort_criterion: ""
      survives_failure_mode: "<Q1 ending_class or named mechanism>"
      requires_human_ruling: ""       # "" if none
  per_surface_assessment:
    - {surface: S1|S2|S3|S4|S5, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S5, dimension: VD1..VD6, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - id: CFG-01
      surface: S1|S2|S3|S4|S5|shared
      question: Q1..Q9
      dimension: VD1..VD6
      title: ""
      evidence: "file:line|item-id"
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      survives_failure_mode: ""       # which Q1 ending_class this finding's fix survives
      refutation: ""                  # the strongest counter-argument, and why it failed
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate|retire
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                         item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""}
      effort: XS|S|M|L
      depends_on: []
      sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: <int>
    novel_count: <int>
    planned_insufficient_count: <int>
    planned_unbuilt_count: <int>
    top_improvements: [<finding ids>]
    highest_leverage_change: <finding id>
    maturity_S1: <value>
    maturity_S2: <value>
    maturity_S3: <value>
    maturity_S4: <value>
    maturity_S5: <value>
```

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list. `total_findings =
len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`. Candidates
fully covered by an existing owner live in `rejected_candidates[]`, NOT `findings[]`.
`rubric_ratings`, `question_answers`, `intervention_erosion`, `content_class_routing`, and
`migration_sequence` are systems-of-record referenced FROM findings, never re-counted into the
total. `top_improvements` and `highest_leverage_change` MUST be finding ids.

**`control_property_match` is REQUIRED** whenever a compensating control is the reason for
dismissal: name the property the control exercises, cite where it operates (mechanism or
file:line), and state why the control would FAIL if the defect were real. A control that cannot
catch the break neither lowers severity nor justifies dismissal.

**`confidence: CONFIRMED`** requires the behavior traced to a file:line or an observed sampled
artifact. Anything less is `HYPOTHESIS`.

## SEVERITY + MATURITY

Severity is assigned AFTER judgment, by defect class:

- **critical** -- the routing architecture can produce a wrong-but-trusted governance outcome: an
  assertion becomes binding repo-wide without ever being reviewed as such, or an authoring path
  is hard-blocked with no sanctioned route through.
- **high** -- a weakness that materially reduces the guarantee AND whose compensating controls
  you judged insufficient after applying the property-match test.
- **medium** -- redundancy, ambiguity, or inconsistency with a clear fix.
- **low** -- clarity or wording.

Maturity is computed LAST, per surface, top-down, first match wins:

- **frontier** -- 0 open critical AND 0 open high findings on that surface, AND every EX1-EX8
  property in Q2's `external_checklist` rated `met` or `partial` -- never `missed`.
- **strong** -- 0 critical AND <= 1 high.
- **solid** -- <= 1 critical.
- **nascent** -- otherwise.

`frontier` remains reachable where you argued a property-matched compensating control. The
framing of this prompt does not foreclose any rating.

## COMMIT / PR MECHANICS

1. Derive the base ONCE (SETUP): `git fetch origin main` then `git rev-parse --short origin/main`.
   That commit IS the audited tree. Use the sha in both deliverable filenames, in the branch name,
   and in `meta.audited_commit`.
2. `git switch -c audit/contract-first-governance-<sha> origin/main` -- so the PR diff contains
   only your two deliverable files. This is a deliberate, documented exception to the repository's
   `claude/*` session-branch rule: this session needs a clean two-file diff off the audited base.
3. Pre-push gate: a clean YAML parse of your two deliverables
   (`bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/contract-first-governance-<sha>.yaml`).
   Repo-wide validation is advisory outside CI here; an unrelated `validate --pre` failure goes
   in `meta.contract_notes` and is never fixed by you.
4. Commit with `user.name=Claude` and `user.email=noreply@anthropic.com`. Then
   `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, not a
   draft), title:

   `audit: decision / contract / change-record content routing and prior-intervention erosion (S1-S5)`

   Body: a 2-3 sentence lede plus the `summary:` block in a yaml fence.
6. **END THE TURN.** Do not poll for CI. Do not merge. Do not subscribe to PR activity. Do not
   self-approve. The human disposes.

## GUARDRAILS

- **Write boundary, closed list.** The only files you create or modify in the repository tree are
  `audits/contract-first-governance-<sha>.yaml` and `audits/contract-first-governance-<sha>.md`.
  Not `docs/DECISIONS.md`. Not any contract. Not the roadmap. Not a recommendation. Not a fix to
  a failing check. If you believe a file needs changing, that belief is a finding.
- **Precision over volume.** Fewer than ~8 surviving findings is a valid result -- state it
  plainly and do not pad. A padded finding costs more than a missing one, because the human
  disposes of every row you write.
- **A run that merely confirms this prompt's candidates has failed.** Rejections are output.
  `rejected_candidates[]` being longer than `findings[]` is a good outcome, not a weak one.
- **You are the fifth audit in this territory.** Four prior audits produced findings that were
  implemented and that produced relief which did not hold. The default expected value of another
  taxonomy is low. If, after Arc A, you conclude that the honest answer is "the problem is not
  where the previous four looked", say that as the headline and let the rest of the audit follow
  from it.
- **No new standing prose.** Do not propose creating a standing prose-architecture document as a
  remedy; this repository routes forward intent to roadmap items, rationale to decisions, and
  semantics to contracts. You may propose new machine-readable artifacts, new templates, and new
  record types freely.
