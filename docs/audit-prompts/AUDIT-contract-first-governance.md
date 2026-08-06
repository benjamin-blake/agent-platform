# AUDIT: Decision / contract / change-record content routing, and why prior interventions eroded

## TASK

Audit the content-routing frontier in this repository: which durable content belongs in a numbered
`## Decision NNN:` entry, which belongs in a machine-readable contract under `docs/contracts/`,
and which belongs in a change record (commit message / PR body) -- plus the mechanisms, if any,
that make the correct routing happen rather than merely stating it. Five surfaces are in scope
(S1-S5, enumerated under SCOPE). The audit runs three arcs: **Arc A (diagnosis)** -- why five
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

One framing exception, stated openly so you can discount it: this prompt's TASK asserts that
prior interventions eroded. That assertion was supplied by the requester, not established by you.
Q1 exists to test it. The `relief-still-holding` ending class and Q1's `undetermined` verdict are
the routes by which you reject it, and using them is a fully successful outcome.

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
   `docs/ROADMAP-PLATFORM.yaml` (pending, binding until ratified or superseded). Separate
   lifecycles, guards, and numbering authorities.
3. **`validate_contract_drift` does not detect contract-vs-code drift.** Despite the name it
   gates *ritual-schema* drift: YAML parseability, schema conformance, `$ref` resolution,
   amendment-log presence on changed contracts, and status transitions. Whether a contract's
   stated semantics still match the code implementing them is a different property. Do not treat
   the check's existence as coverage of the second property, and do not treat the name as
   evidence of either.
4. **Four decision surfaces exist, not one.** `docs/DECISIONS.md` (live), `docs/DECISIONS_ARCHIVE.md`
   (archived), `docs/decisions-index.json` (a committed generated projection consumed by the
   decision-scout gate), and the `ops_decisions` warehouse table (backfilled from the markdown).
   A claim about "the decision log" must name which. Any migration you propose must state its
   effect on all four.
5. **Two artifacts both look like "the decision contract".** `docs/contracts/decision-entry.yaml`
   is the *authoring grammar* for markdown entries. `docs/contracts/ops_decisions.yaml` is the
   Class A *table schema* for the warehouse projection. They govern different layers.
6. **Decision 150's significance BAR is not the `**Significance:**` STANZA.** The bar is a
   `significance:` section inside `decision-entry.yaml` describing four routing rows. The stanza
   is a bold marker some entry bodies carry. A third near-miss exists: at least one entry carries
   a differently-spelled bold lead-in beginning `**Significance bar` inside its numbered clause
   list, which is neither the bar nor the stanza and which a naive substring count will
   miscount. Count the exact marker string, and state which string you counted.

Two plausible-but-wrong audit targets: this is **not** an audit of whether individual past
Decisions were correct, and **not** an audit of the warehouse ETL's field-level fidelity (a prior
audit owns that -- see DEDUP DISCIPLINE). The target is the routing rule, its enforcement, and
why prior fixes to it did not hold.

## SCOPE

### Surfaces

| ID | Surface | State |
|---|---|---|
| S1 | The decision corpus: `docs/DECISIONS.md`, `docs/DECISIONS_ARCHIVE.md`, `docs/decisions-index.json`, and their guards under `scripts/checks/decisions/` | built |
| S2 | The **ritual** contract population under `docs/contracts/` (files carrying `contract:` + `class:`) and its enforcement (`scripts/contracts.py`, `scripts/contracts_schema.py`, `scripts/contracts_enforcement.py`, `scripts/checks/contracts/validate_contract_drift.py`) | built |
| S3 | The **free-form** contract population under `docs/contracts/` (files with no `contract:` block) | built |
| S4 | The authoring/routing instruction layer: `AGENTS.md`, `.claude/skills/planning/SKILL.md`, `docs/contracts/decision-entry.yaml`, `docs/contracts/instruction-architecture.yaml`, `docs/contracts/file-router.yaml`, `docs/PROJECT_CONTEXT.md` | built |
| S5 | The change-record surface: the commit-message conventions table in `AGENTS.md`, `.github/pull_request_template.md`, and `scripts/checks/_common.py::feat_commit_slugs` | built |

**S3/S4 overlap, pinned.** Three files sit in both lists -- `decision-entry.yaml`,
`file-router.yaml`, `instruction-architecture.yaml` -- because they are free-form contracts that
happen to carry routing content. S4 is a ROLE, not a disjoint file set. Attribute by the property
the finding is about: a finding about the file's own governance as a contract (schema, status,
size, amendment log) is **S3**; a finding about the routing rule it states or fails to state is
**S4**. If a finding genuinely spans both properties, use `surface: shared` and list both in
`surfaces_affected`.

Out of scope, one line each: the warehouse ETL's field-level fidelity (prior audit owns it); the
correctness of any individual past architectural choice; the roadmap's own sequencing; anything
under `terraform/`; the trading product.

### Vocabulary

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
below is a do-not-flag. Each may be challenged, superseded, or recommended for retirement. But
each carries a real cost, and a challenge that does not price its cost is a HYPOTHESIS, not a
finding.

| Constraint | Owner | Cost of challenging it |
|---|---|---|
| Never remove a `## Decision N:` heading; never retire or reuse a number | Decision 149; `decision-entry.yaml` `compaction.stub_grammar.never_remove_headers` | Inbound `Decision N` citations repo-wide (see G14 -- two disagreeing counts, both to be re-derived). A retirement mechanism must state how each is resolved. |
| Numbered entries are immutable; later changes come as new entries or dated in-place annotations | Decision 149; `decision-entry.yaml` `amendment_forms` | Provenance, and the `ops_decisions` SCD2 history model, assume append-not-rewrite. |
| The significance bar gates what may become a Decision | Decision 150 | It is the only stated front-door control; removing it without a replacement removes the only one. |
| Fully-superseded entries move to the archive | Decision 146 | Archived entries leave the file most agents read by default. |
| Live-header ceiling, combined byte ceiling, committed-index byte pin | Decision 160, Decision 166 (see G12 for live values) | These are the only mechanical backstops on corpus growth. |
| The CD.25 Class A/B/C ritual is the contract shape | Decision 118 | Extending, replacing, or adding a class changes what `validate_contract_drift` can enforce. |

Two boundaries are NOT open, because they govern how you write rather than what you may conclude:

- **Public-repo content boundary** (`AGENTS.md`, "PUBLIC repository / confidential-data
  boundary"; Decision 101): never write AWS account IDs or ARNs, IAM ExternalIds, credentials,
  internal hostnames, or trading-strategy performance into your deliverables.
- **Single Portal Invariant** (Decision 84): do not write to `logs/.recommendations-log.jsonl`,
  `logs/.decisions-index.jsonl`, or any warehouse staging path. You file no recommendations.

### Trust nothing

Obtain every path, anchor, count, size, and date by reading the repository yourself. Every number
in this prompt was measured at compose time and may have moved.

Two distinct escape hatches, used differently:

- An **anchor that does not resolve** (file absent, line number pointing at something else) ->
  `meta.stale_anchors` as `{anchor, expected, found}`.
- An **anchor that resolves but whose figure has drifted** (the file is there, the count is
  different) -> keep working from YOUR number and record the drift in `meta.contract_notes`.

Where your re-derivation disagrees with this prompt, YOUR measurement is the evidence.

**Scripted aggregate scans are permitted and expected.** Several grounding figures (G6, G7, G9,
G10, G11, and DD-A's numerator) are corpus-wide aggregates that can only be re-derived by
processing all of `docs/DECISIONS.md`. Do that -- via a `bin/venv-python` script that computes and
prints the aggregate. The bounded-retrieval rule under METHOD P1 restricts what you load into
CONTEXT, not what a script may compute over. Reading a scripted count of the corpus is not
reading the corpus.

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

- **IF preflight fails for ANY reason** (credentials, egress, import error, non-zero exit,
  timeout): do NOT abort. Set `meta.degraded_dedup: true`, set `dedup_hit_count: null` on every
  finding, add `"degraded dedup"` to each `roadmap_crossref.note`, and proceed using the
  committed files (`docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`, `docs/decisions-index.json`)
  plus whatever `logs/.recommendations-log.jsonl` already holds. Record the failure text in
  `meta.contract_notes`. Note that `degraded_dedup` constrains `roadmap_crossref` only -- a
  finding's own `confidence` still follows the ordinary file:line rule under SEVERITY, and a
  traced finding remains CONFIRMED in degraded mode.
- **IF `logs/.recommendations-log.jsonl` is absent entirely:** same flag, same note.
- **IF web access is unavailable** when rating Q2's external checklist: set
  `meta.degraded_external: true` and rate against the pinned EX1-EX13 list without claiming
  anything about prevalence or industry frequency.
- **IF `bin/venv-python -m scripts.validate --pre` fails on something unrelated to your two
  deliverables:** record it in `meta.contract_notes` and do NOT fix it -- outside your write
  boundary. Repo-wide validation is advisory outside CI here; a clean YAML parse of your two
  deliverables is the real pre-push gate.

## NORTH STAR

The bar each surface is judged against. These are principles you argue a surface against, not
rules you pattern-match -- a surface may fall short of one and be right to. Each names the rubric
dimension it feeds; the rubric is where they become ratings.

- **NS1 -- One assertion, one home** (VD4). Any normative statement has exactly one authoritative
  location. A second statement of the same thing is drift by construction, whichever copy is
  "right".
- **NS2 -- Machine-parseable beats prose** (VD2). Where two designs are equally valid and one is
  machine-parseable, that one wins. Semantic definitions are collocated with their enforcement.
- **NS3 -- A rule with no evaluator is a suggestion** (VD2). Governance that depends on the
  author electing it will hold only as long as authors elect it.
- **NS4 -- Agent-first** (VD6). Every artifact is optimised for agent loading efficiency, not
  human readability. Human-readable summaries are query results, not stored artifacts.
- **NS5 -- Bounded, retrievable state** (VD5, VD6). Governance corpora are indexed and retrieved
  by identifier, not loaded wholesale.
- **NS6 -- The cure must be cheaper than the disease** (VD5). An intervention whose own cost is
  drawn from the scarce resource it protects is self-limiting; judge each intervention's net
  effect, not its stated intent.

## THE QUESTIONS

Each question gets a first-class entry in `question_answers[]` with the verdict enum pinned here.

### Q1 -- Erosion (Arc A keystone)

**Population, pinned:** `intervention_erosion[]` carries exactly two row kinds, and both are
required.

- **Kind `decision`** -- one row for each of the 9 numbered entries named in EMPIRICAL PASS E1.
- **Kind `audit_round`** -- one row for each of the 5 prior audits named in DEDUP DISCIPLINE
  (DAF, DPI, DCG, SGE, ACG), treating the audit and its landed follow-ups as one round.

That is 14 rows. Do not add rows for interventions outside these two populations; if you find one
that matters, name it in `meta.contract_notes` rather than extending the population.

For each row: what did it change, what relief did it produce, how long did that relief hold, and
what specifically ended it? Classify the ending with `ending_class`:
`ceiling-raised` | `mechanism-unused` | `superseded-by-larger-entry` | `cost-exceeded-benefit` |
`relief-still-holding` | `other`.

**A `relief-still-holding` row is a first-class outcome, and costs no more to write than any
other.** On such a row, `held_until` is the literal string `still-holding` and `note` carries the
evidence that it is still holding. Do not treat the row shape as pressure toward an erosion
verdict; if the honest answer is that most or all interventions still hold, say so and let Q1's
verdict be `undetermined`.

Then the aggregate question: **is there a single recurring mechanism that causes interventions in
this territory to erode, or is each erosion independent?**

Every finding you file in Arc B or Arc C must populate `survives_failure_mode` -- see the field's
definition under OUTPUT for what is legal there.

**Verdict enum:** `primary-mechanism-identified` | `contributing-factors-only` | `undetermined`

### Q2 -- Routing decidability, against external practice

Is there a sound, **decidable** rule today that assigns a unit of durable content to exactly one
of {numbered Decision, ritual contract, free-form contract, change record, roadmap tier_item,
recommendation}? Decidable means: two competent authors, given the same content and only the
stated rule, reach the same home without further judgment.

This question carries an **EXTERNAL CHECKLIST**. Rate each property `met` | `partial` | `missed`
with evidence, in `question_answers[].external_checklist`. This field is the SOLE source the
`frontier` maturity tier reads. `partial` requires an argued, property-matched compensating
control in its evidence. EX1-EX13 is a CLOSED list -- do not add properties.

| ID | External property |
|---|---|
| EX1 | **ADR discipline** (Nygard / MADR): a decision record is immutable, covers one decision, and carries context / decision / status / consequences -- it records *why this choice*, and does not double as the specification of the thing chosen. |
| EX2 | **Normative vs informative separation** (IETF RFC 2119, ISO/IEC directives): normative requirements live in a specification surface and are labelled as such; rationale is explicitly non-normative and cannot be cited as a requirement. |
| EX3 | **Contract-first / spec-first authoring** (OpenAPI, Protobuf, JSON Schema): the machine-readable specification is authored with or before the implementation, and the implementation plus its tests bind to it as the single source. |
| EX4 | **Policy-as-code** (OPA/Rego, Conftest): governance rules are executable, versioned artifacts, not prose. A rule with no evaluator is not a rule. |
| EX5 | **Bidirectional traceability**: requirement -> implementing artifact -> verifying check, with orphan detection on BOTH sides. |
| EX6 | **Change-record granularity**: the commit/PR message carries what changed and why now; the specification carries what is true; the decision record carries why this choice. Three questions, three homes. |
| EX7 | **Deprecation and supersession lifecycle**: superseded records are marked, discoverable, and shed weight; the corpus is not monotonically growing. |
| EX8 | **Bounded retrieval**: the governance corpus is indexed and retrieved by identifier rather than loaded wholesale into every consumer. |
| EX9 | **Stable identifiers independent of presentation and storage**: an identifier survives a move between file, index, and table without rewriting inbound references. |
| EX10 | **Single semantic authority with generated projections**: derived surfaces are generated from one authority rather than maintained as parallel authorities. |
| EX11 | **Preservation of rejected alternatives and reversal conditions**: what was considered and rejected, and what would reverse the choice, survive as first-class recoverable content. |
| EX12 | **Governed retention**: archival, compaction, and deletion are defined lifecycle operations with stated triggers, not ad-hoc relief actions. |
| EX13 | **Versioned, testable contracts**: a specification artifact carries a version, and a test or gate can fail against it -- the contract is exercisable, not merely declarative. |

If web access exists, you MAY consult at most 6 primary or authoritative sources on ADR practice,
architecture knowledge management, or specification/rationale separation; record title + URL in
`meta.external_sources`. Do not add checklist properties from them. If browsing is unavailable,
follow the `degraded_external` path in SETUP.

**Verdict enum:** `sufficient` | `partial` | `insufficient`

### Q3 -- Why an author reaches for a Decision

Given the routing surfaces that exist, what structurally causes an agent authoring a change to
mint a numbered Decision rather than amend a contract? Trace the mechanics, not the motives.
Consider (and reject or confirm) at minimum: the amendment-by-forward-reference convention and
whether it manufactures reversal-relevance; the presence or absence of an authoring ritual,
review lane, or warehouse projection on the contract side; whether the significance bar is
self-certified and by what evidence; whether any contract exists whose declared subject is
"mechanism" as opposed to "field semantics"; and the relative discoverability of the two
destinations.

**Verdict enum:** `primary-cause-established` | `contributing-only` | `undetermined`

### Q4 -- Destination readiness

If content migrates out of S1 into S2 or S3, does the destination carry equal-or-better
governance? Compare S1, S2, and S3 property-by-property on at least: schema validation, authoring
grammar, amendment/change log, status and supersession lifecycle, size governance, binding to
code, discoverability by index or router, warehouse projection, and review lane. Where the
destination is weaker, say what a migration would lose and whether that loss matters.

**Verdict enum:** `ready` | `ready-with-gaps` | `not-ready`

### Q5 -- Contract-side detection gaps

Three properties, each rated separately in `question_answers[].detection_ratings` using the
pinned enum `detected` | `partially-detected` | `undetected`:

- **(a) `parallel-contracts`** -- two artifacts asserting the same semantics in different places.
- **(b) `contradictory-contracts`** -- two artifacts asserting incompatible semantics.
- **(c) `contract-code-drift`** -- a contract's stated semantics no longer matching the code.

For each: is it detectable today, by what, over what subset of the population, and what is the
minimum mechanism that would detect it? Where you propose a mechanism, state its false-positive
behavior and what it costs to run. If a property is not well-posed absent something the
repository does not have (for instance, a declared subject per contract), say so -- that is an
answer, not an evasion.

**Verdict enum (answer-level):** `sufficient` | `partial` | `insufficient`

### Q6 -- The change-record leg

What content routinely lands in a Decision that a commit message or PR body should carry instead?
Is governance of the change-record surface warranted, or is its current shape correct? Answer
both directions -- a finding that the current shape is correct is as valuable as one that it is
not. Note that this surface is partially machine-read already (G15); assess what that mechanism
does and does not cover.

**Verdict enum:** `governance-warranted` | `absence-correct` | `partial`

### Q7 -- End-state (Arc B)

What SHOULD the separation between the three record types be in this repository? You have full
latitude: propose new record types, templates, contract classes, a different corpus architecture,
or the retirement of an existing surface. You may conclude that `docs/DECISIONS.md` should stop
being a prose corpus. You may conclude the current architecture is right and only its enforcement
is wrong.

A pinned starting option set for the corpus-shape sub-question -- choose one or argue past it:
`keep_monolith` | `extract_machine_semantics_only` | `extract_multiple_typed_fields` |
`generate_curated_index` | `accelerate_portal_transition` | `other`. Record it as
`end_state.corpus_shape`.

**Required sub-answer:** roadmap item T1.5 (exit criterion c1) already owns retiring
`docs/DECISIONS.md` behind a decisions read portal. State whether your end-state is
`sufficient_as_planned` | `sufficient_with_specific_amendments` | `materially_incomplete` |
`wrong_end_state` with respect to T1.5, in `end_state.t15_verdict`. An end-state that ignores
T1.5 is incomplete.

To ground that verdict you need the consumer inventory -- who reads the corpus today and would
have to be repointed. Derive it with this bounded command rather than by inspection:

```bash
rg -l -e 'DECISIONS\.md' -e 'decisions-index' -e 'parse_decisions_md' \
      -e 'iter_decision_headings' -e 'decision_header_numbers' -e 'ops_decisions' \
      .claude scripts src docs/contracts
```

Classify each hit as a planning-agent consumer, a CI guard, a generator, or a warehouse path, and
state which class T1.5's read portal does and does not cover.

Constraints on the ANSWER, not its content: it must state (i) the routing rule in decidable form,
(ii) the forcing function that makes each routing happen, (iii) which Q1 `ending_class` each
forcing function survives, and (iv) what it costs -- in authoring effort, agent context, and
migration. An end-state with no forcing function is a restatement of the problem.

**Verdict enum:** `single-end-state-recommended` | `options-with-tradeoffs` | `insufficient-evidence`

### Q8 -- Transition (Arc C)

How do we get from here to the Q7 end-state, in what order? Populate `migration_sequence`:
ordered steps, each with its blocker, reversibility, a pre-committed abort criterion, the Q1
failure mode it survives, and its effect on the four decision surfaces of trap 4 (index
regeneration, `ops_decisions` backfill, archive moves). Name what must happen FIRST and why. If a
step needs a human ruling, name the ruling.

Content classification has two layers, both required:

- **Class layer** (`content_class_routing[]`) -- named classes of live entry, each with a
  disposition, a worked exemplar, and a count. Classes need NOT partition the corpus; state your
  `count_method` and use `null` where you cannot estimate.
- **Entry layer** (`sampled_entry_dispositions[]`) -- one row per entry sampled in E2 and DD-C
  ONLY (at most 13 rows total). No ledger over all live entries; a full enumeration is owned
  elsewhere (see DEDUP DISCIPLINE, rec-2822).

Both layers use the same pinned disposition enum: `retain_full_decision` |
`retain_decision_plus_contract` | `compact_to_decision_pointer` | `archive` |
`migrate_to_other_governed_surface` | `remove_as_redundant_or_superseded`. For each row state
what remains authoritative, what historical material survives, and the counterfactual loss if the
move is made incorrectly.

**Verdict enum:** `ordered-sequence-with-abort-criteria` | `partial-sequence` | `insufficient-evidence`

### Q9 -- Questions not asked

What did the requester not think to ask? Seeded below -- ANSWER these AND extend with your own
(**at most 6 additions**):

- Does auditing this territory repeatedly have a cost the audits themselves have never accounted
  for?
- Is corpus growth a symptom of decision-log design, or of something upstream -- how work is
  decomposed, how plans are scoped, or how amendments are triggered?
- Is there a class of content that belongs in NONE of the six homes and is being forced into one?
- If the corpus were rebuilt from scratch today with full knowledge, how many current live
  entries would exist at all?
- Audit prompts and audit outputs are themselves durable governance content -- `docs/audit-prompts/`
  and `audits/` -- carrying no contract, no size governance, and no home in the six-home routing
  rule. THIS PROMPT is an instance of the class. Does the routing rule you propose in Q7 account
  for it, and should it?

Uses the `answers[]` shape, not a verdict.

## RUBRIC

Rate every dimension for every surface S1-S5. Pinned enum: `strong` | `adequate` | `weak` |
`absent` | `n/a`. **`n/a` is correct and costless where a dimension does not structurally apply**
-- never manufacture a rating, and never manufacture a finding to fill a cell.

| ID | Dimension |
|---|---|
| VD1 | **Routing decidability** -- a cold author can assign content to this surface, or away from it, without judgment beyond the stated rule. |
| VD2 | **Mechanism** -- the rule governing this surface is enforced by something executable, not by convention or self-certification. |
| VD3 | **Governance parity** -- lifecycle controls (schema, status, supersession, amendment log, size) are proportionate to the authority of the content held. |
| VD4 | **Non-duplication** -- one semantic assertion has exactly one home here; parallel or contradictory statements are detectable. |
| VD5 | **Bounded growth** -- content can leave the surface by a working mechanism, and growth is rationed by something that does not itself consume the ration. |
| VD6 | **Discoverability** -- an agent finds the governing artifact by pointer or index rather than by reading the corpus. |

## DEEP-DIVES

### DD-A -- The growth-governance lineage (feeds Q1, VD5, NS6)

Trace the E1 interventions end to end: trigger, mechanism, size, date, what each amended or
superseded, and what happened next. Then compute the aggregate with numerator and denominator
both pinned, so the arithmetic is comparable:

- **Byte share** = (sum of the E1 entries' own body bytes in `docs/DECISIONS.md`, header line
  through the byte before the next `## Decision` header -- the ENTRY BODIES ONLY, excluding any
  guard code, contract, config, or test each intervention also produced) / **live-file bytes**
  (`docs/DECISIONS.md` alone, not live+archive).
- **Header share** = (count of E1 entries) / the **live-header ceiling** in G12 (not the current
  header count).

Report both figures and the arithmetic. If you judge that excluding each intervention's
implementing code understates its true cost, say so and report a second figure alongside -- but
report the pinned one first, so it is comparable to any later run.

Then answer NS6 for this lineage: was the cure cheaper than the disease? Do not assert the
conclusion without showing the numbers.

### DD-B -- A blocked draft, classified (feeds Q2, Q3, Q7)

The following is a verbatim draft of a proposed Decision 167, written by an agent and BLOCKED by
the repository operator on the grounds that it is not an architectural decision but prose around
an intended implementation. It is a specimen. It is NOT in the repository; do not search for it,
and do not treat the operator's judgment as a verdict you must share.

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

**Point count, pinned:** the specimen's own text announces "four points" and then carries FIVE
body paragraphs -- the fifth being the trailing paragraph beginning "Plus a reciprocal". Classify
all five, treating that trailing paragraph as point 5. The gap between the draft's self-count and
its content is itself worth one line of comment.

Classify each of its five points against the routing rule as it exists today (Q2) and against
your proposed end-state (Q7). For each point, name the home it takes under each. Then:

1. Under today's rule, would this draft have been correctly ROUTED, correctly BLOCKED, or is the
   rule silent? If the rule is silent, that silence is the finding.
2. The work this draft describes did land in the repository. Locate what actually shipped and
   where the content went; state whether the outcome matches either routing. **If you cannot
   locate it within a bounded search, say so and set this sub-answer to `not-located`** -- that
   is a valid result, not a failure, and does not block the rest of DD-B.

### DD-C -- Migration feasibility, traced (feeds Q4, Q8)

Select THREE entries -- do not exceed three. **Selection criteria, pinned** (these are structural
and available at this phase; they do not require the Q8 class taxonomy, which is authored later):

1. One entry carrying `**Status:** Superseded` in the live file.
2. One entry whose body is predominantly mechanism specification -- shapes, enums, grammars,
   thresholds -- rather than rationale, by your E2 partitioning rule.
3. One entry cited by name from live code or a contract outside `docs/DECISIONS.md` and
   `docs/DECISIONS_ARCHIVE.md`.

If a single entry satisfies more than one criterion, pick a different entry for the others so the
three are distinct. You MAY draw one from `docs/DECISIONS_ARCHIVE.md` if it makes criterion 3
sharper; record `corpus: archive` on that row.

Trace each end-to-end through every mechanism the repository offers for moving content off S1:
archival, compact-in-place, and any migrate-then-rehome path described. For each, report what
blocks it, which mechanism (if any) can process it, and what a successful migration costs. If
none of the three can be processed by any existing mechanism, that is the finding. These three
entries also get `sampled_entry_dispositions[]` rows.

### DD-D -- The two contract populations, compared (feeds Q4, Q5)

Build Q4's property-by-property comparison as a table in the companion report. Then answer what
Q5 turns on: for the free-form population, what would it take to detect that two files assert the
same thing, or contradictory things?

## GROUNDING MAP

This map exists to spend your cognition on judgment rather than grep. Every entry was read from
disk at compose time. **Verify each before relying on it.**

Facts are stated neutrally. Where a phrasing sounds like a defect, it is not: it is an
observation awaiting your adjudication.

| ID | Observed fact | Anchor |
|---|---|---|
| G1 | The drift gate iterates every `docs/contracts/*.yaml` and `continue`s past any file whose parsed data lacks a `contract` mapping containing a `class` key. Files taking that branch receive `yaml.safe_load` and a mapping-type check only. | `scripts/checks/contracts/validate_contract_drift.py:64-72` |
| G2 | 16 of 39 contract files (37 `.yaml` + 2 `.md`) carried a `contract:` block with `class:`; 23 did not. | `docs/contracts/` |
| G3 | `file-router.yaml` carried 82 route entries; 8 of the 39 contract files appeared as a `targets` value; 31 did not. | `docs/contracts/file-router.yaml:24` |
| G4 | Contract files with no filename match under `scripts/`, `src/`, `config/`. **This count is method-dependent** -- `grep -rIlF` on the bare basename gives 15; on the stem without extension, 10; on the full `docs/contracts/<name>` path, 17. State your method before quoting a number. Further caveat: `load_all_contracts` (`scripts/contracts.py`) globs the directory, so any filename-grep undercounts glob-loaded consumers. | `docs/contracts/`, `scripts/contracts.py` |
| G5 | `instruction-architecture.yaml` defines 5 layers (universal rules, project knowledge base, slash commands, skills, executor prompts), each with a `content_locations` list. Neither `docs/contracts/` nor `docs/DECISIONS.md` appears in any layer's locations. The file also carries a 7-entry `anti_patterns` list. | `docs/contracts/instruction-architecture.yaml` |
| G6 | Median live-entry size **in bytes** by decision-number band, across 119 live entries: D<=60 = 2,327 (n=16); D61-100 = 3,898 (n=37); D101-139 = 3,241 (n=39); D>=140 = 7,257 (n=27). Measured on UTF-8 encoded entry bodies; a character-count median differs (2,315 for the first band). State your unit. | `docs/DECISIONS.md` |
| G7 | Under one proxy for mechanism density -- distinct `docs/contracts/*`, `scripts/**.py`, `config/**.yaml`, `.github/workflows/*` path references per KB -- the same four bands measured 0.33, 0.27, 0.42, 0.38. An open recommendation (rec-3023) states density "roughly HALVED (1.7 to 0.8 refs per KB)" across a similar comparison; its metric definition is not stated there. The two do not agree. Choose and STATE your own definition before drawing any conclusion from either. | `docs/DECISIONS.md`; `logs/.recommendations-log.jsonl` |
| G8 | Eight numbered entries governing decision-log growth carry dates from 2026-07-16 to 2026-07-31: D134 (7,182 B), D145 (6,465 B), D146 (4,175 B), D149 (8,210 B), D150 (5,899 B), D151 (11,272 B), D152 (7,587 B), D160 (18,879 B). D160, whose title begins "Retire the DECISIONS.md live-byte ceiling", was the largest live entry measured. D166 (17,240 B, dated 2026-08-04) was the second largest. | `docs/DECISIONS.md` |
| G9 | 28 of 119 live entries contained the string `docs/contracts/`. | `docs/DECISIONS.md` |
| G10 | The exact string `**Significance:**` appeared in 6 of 119 live entries. `decision-entry.yaml` lists `required_markers` as Status, Date, Decision, and 6 `optional_markers_fixed_spelling`; neither list contains Significance. See trap 6 on near-miss spellings. | `docs/contracts/decision-entry.yaml:39-57`; `docs/DECISIONS.md` |
| G11 | 4 live entries carried `**Status:** Superseded`. Live `## Decision` headers numbered 119. Live file 573,726 B + archive 111,070 B = 684,796 B combined. | `docs/DECISIONS.md`, `docs/DECISIONS_ARCHIVE.md` |
| G12 | The size guard's constants are `_DECISIONS_LIVE_MAX_H2 = 120` and `_DECISIONS_COMBINED_MAX_BYTES = 700_000`. The committed-index test pins `_COMMITTED_INDEX_MAX_BYTES = 131_000`, annotated as a Decision 166 re-derivation of a prior 110,000-byte pin. `docs/decisions-index.json` measured 110,582 B. | `scripts/checks/decisions/validate_decisions_size.py:20-21`; `tests/test_decisions_index.py:450` |
| G13 | `decision-entry.yaml` carries a `significance:` section with four routing rows -- `numbered_decision`, `cd_state_flip`, `operational_fact`, `field_semantics` -- of which `field_semantics` is the row naming a contract as destination. It separately carries an `amendment_forms:` section describing two dated in-place annotation shapes. | `docs/contracts/decision-entry.yaml:114-143`, `:68-81` |
| G14 | `decision-entry.yaml` states "~12,103 unguarded inbound 'Decision N' citations across the repo". A compose-time occurrence count over tracked files was materially larger -- by more than 7,000. **No figure is quoted here deliberately:** this prompt file itself contains such citations, so any number pinned here is self-referentially unstable. Derive it yourself with `git grep -oIE 'Decision [0-9]+' -- .` (occurrences) and note that `git grep -IE` (matching LINES) gives a materially smaller number. State your command, your unit, and your result. | `docs/contracts/decision-entry.yaml:192` |
| G15 | The commit-message surface is a 5-row prefix table (`feat`, `plan`, `roadmap`, `scope`, `audit`) in `AGENTS.md`. The PR template's comment block names 4 of those 5 -- `audit({slug})` is absent from it. One check DOES read commit subjects for content: `feat_commit_slugs()` runs `git log origin/main..HEAD --format=%s` and matches `_FEAT_COMMIT_RE = ^feat\(([^)]+)\):`, consumed by `validate_vp_replay` and `validate_graduation_completeness`. No check under `scripts/checks/` references the PR template. | `AGENTS.md:190`; `.github/pull_request_template.md`; `scripts/checks/_common.py:25`, `:208-226` |
| G16 | The planning skill carries two relevant sections: "Documentation Artefact Design", restating the Decision 86 routing rule, and "Decision Significance Gate", instructing a check of the `significance:` section before drafting any numbered Decision. | `.claude/skills/planning/SKILL.md:225`, `:371` |
| G17 | `validate_decision_entry_conformance` reads `required_markers` from the contract at check time and enforces them on entries whose number is absent from the `origin/main` baseline; historical entries are grandfathered. It advisory-skips when `origin/main` is unreachable. | `scripts/checks/decisions/validate_decision_entry_conformance.py` |
| G18 | The decision-scout gate triages from `docs/decisions-index.json` plus targeted reads of shortlisted entries, and describes the whole-corpus load as the cost it avoids. Its skill file names the arrangement as interim pending a portal cutover owned by roadmap item T1.5. | `.claude/skills/decision-scout/SKILL.md` |
| G19 | The ritual population spanned Class A (7 files), Class B (3, all `provisional_v0`), and Class C (6). The free-form population included `decision-entry.yaml`, `file-router.yaml`, `deploy-paths.yaml`, `data-modeling-standard.yaml`, `candidate-decision-ratification.yaml`, `instruction-architecture.yaml`, and `marker-grammar.yaml`. | `docs/contracts/` |
| G20 | `decision-entry.yaml` opens with a comment stating it is not a Class A/B/C ritual contract and that the drift gate therefore skips it, citing `file-router.yaml`, `deploy-paths.yaml`, and `read-engine.yaml` as precedent and Decision 118 for the free-form registry pattern. | `docs/contracts/decision-entry.yaml:1-5` |

## EMPIRICAL PASS

Four bounded samples. Tag findings drawn from a sample `evidence_kind: observed`; findings from
reading a rule alone are `static`. **At equal severity, an observed finding outranks a static
one.** Do NOT exceed any bound.

- **E1 -- the growth-governance lineage: exactly Decisions 134, 145, 146, 149, 150, 151, 152, 160,
  166. Do not extend.** For each: date, size, trigger, mechanism, what it amended, what superseded
  or reversed it. DD-A's input and Q1's primary evidence. (166 is included because it re-derived a
  decision-corpus byte pin -- whether that constitutes the same pattern as the other eight is
  yours to judge, not a premise.)
- **E2 -- the 10 highest-numbered live entries; do NOT exceed 10.** Partition each body by content
  type: rationale / specification / change-record / other. Report approximate byte or paragraph
  shares, and state your partitioning rule before applying it. Each gets a
  `sampled_entry_dispositions[]` row.
- **E3 -- at most 8 free-form contracts. Selection rule, pinned:** the 7 named in G19, plus one of
  your choosing. State why you picked the eighth.
- **E4 -- at most 6 ritual contracts. Selection rule, pinned:** two Class A, two Class B, two
  Class C, each pair being the largest two of its class by byte size. The comparison arm for E3
  and DD-D.

Apply this counterfactual to every mechanism you assess: **would this check still pass if the
behavior it governs were removed entirely?** If yes, the check does not exercise the property.
Apply the same test to any mechanism you PROPOSE and report the answer -- a proposed forcing
function that would pass on an empty repository is not a forcing function.

## METHOD

Ordering only -- each phase's content is defined by the questions, deep-dives, and samples it
names. Synthesis and maturity LAST.

- **P1 -- Read.** Every S1-S5 surface in SCOPE; re-resolve every GROUNDING MAP anchor.
  **Bounded for S1:** load `docs/decisions-index.json` plus targeted reads of the entries named in
  E1, E2, and DD-C -- do NOT load `docs/DECISIONS.md` whole into context. This is the repository's
  own retrieval model (G18) and NS5. It does NOT restrict scripted aggregate computation over the
  corpus -- see SCOPE / Trust nothing.
- **P2 -- Arc A.** E1, DD-A -> Q1. Answer Q1 before anything downstream; its failure modes feed
  every later phase.
- **P3 -- Routing.** DD-B, DD-D -> Q2, Q3, Q5.
- **P4 -- Destination.** E3, E4, DD-C -> Q4, Q6.
- **P5 -- Rate.** Every VD x S cell; then E2.
- **P6 -- Arcs B and C.** Q7, then Q8 -> `end_state`, `migration_sequence`,
  `content_class_routing`, `sampled_entry_dispositions`.
- **P7 -- Adversarial convergence. MANDATORY.** For every finding AND for your Q7 end-state,
  attempt to REFUTE it: state the strongest argument that the finding is not a defect, or that
  the end-state is the ninth intervention rather than the last. Where refutation succeeds, move
  the item to `rejected_candidates[]` or revise the design. Where it fails, record the attempt in
  `refutation`. Then re-run on whatever changed. Repeat until a pass changes nothing, **to a
  maximum of 3 passes**; record the count in `meta.convergence_rounds` and, if you exit on the cap
  rather than on convergence, say what remained unsettled in `meta.contract_notes`.
- **P8 -- Dedup.** Apply DEDUP DISCIPLINE to every surviving finding.
- **P9 -- Synthesize.** Q9; severities; then maturity. Write both deliverables.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding.

Surfaces: `docs/ROADMAP-PLATFORM.yaml` (`tier_items[]`, `candidate_decisions[]`),
`docs/DECISIONS.md`, `logs/.recommendations-log.jsonl`, and the prior audit outputs below.

Record on every finding: `roadmap_crossref.dedup_search_terms` (what you searched),
`dedup_hit_count`, and `classification`. **`dedup_hit_count` counts DISTINCT MATCHING ITEMS** --
recommendation ids plus tier_item ids plus decision numbers plus prior-audit finding ids -- not
search terms and not surfaces. **A hit means sufficiency-assessment or rejection, never a fresh
discovery.** A finding with no recorded negative search is `confidence: HYPOTHESIS`.

### Known owners -- assess sufficiency, do not rediscover

Prior audit outputs, named exactly. Read the `.yaml` `findings[]` lists; do NOT re-read the
corpora they audited:

| Prefix | File | Territory | In-territory? |
|---|---|---|---|
| DAF | `audits/decisions-authoring-format-d140093.yaml` | Authoring grammar, ETL parity, unbounded growth | yes |
| DPI | `audits/decision-log-premise-integrity-8fb581e.yaml` | Supersession annotation, dead premises, archival policy | yes |
| DCG | `audits/decision-consolidation-growth-f79d6b5.yaml` | Compaction lifecycle, significance bar, generated index, Intent marker | yes |
| SGE | `audits/size-governance-expansion-3dee4a5.yaml` | Size governance beyond Python; marker-authorization guards | yes |
| ACG | `audits/agent-context-governance-cdfda88.yaml` | Ambient prose surfaces, context cost, required-context | adjacent |

All five are Q1 `audit_round` rows. ACG is marked adjacent because its subject is ambient context
cost rather than record routing; assess whether that boundary holds.

**Superseded prompt.** An earlier audit prompt covering overlapping territory was composed and
then superseded by this one; it was never executed and has been removed. If you find any
reference to a "decision knowledge persistence scalability" audit, it has no output and is not an
owner -- note it in `meta.contract_notes` and move on.

Roadmap items owning adjacent territory -- read each and judge whether its remedy is sufficient,
unbuilt, or off-target:

- **T2.56** "Normative / contract / ADR layering" -- the closest owner, forward-intent-only.
  Judge specifically whether its framing (ambient-load cost, retrieval-by-id) covers the
  authoring-time ROUTING question or is orthogonal to it.
- **T2.54** "Bidirectional clause-to-check traceability" -- EX5's territory.
- **T1.5** (exit criterion c1) -- DECISIONS.md retirement behind a decisions read portal. Q7's
  required sub-answer.
- **T1.17** -- premise-integrity follow-ups.

Open recommendations in this territory. Each is a hit; assess sufficiency:

`rec-3023` (bound and enforce decision body content), `rec-2934` (per-entry authoring size norm),
`rec-3015` (justify why a contract was rejected before minting an entry), `rec-3016` (route
single-call-site tweaks to `amendment_forms`), `rec-2822` (enumerate citation-stranded entries
into a manifest -- **this owns the full per-entry ledger**), `rec-2823` (migrate-then-archive
branch), `rec-2984` (move runbooks out of ambient prose into contracts), `rec-2991` (contract
silent on block separator), `rec-3001` / `rec-3012` (index byte pin), `rec-2200` (standing-prose
guard underscopes Decision 86).

### Do-not-flag

Only two, both about how you write rather than what you may conclude: the public-repo content
boundary (Decision 101) and the Single Portal Invariant (Decision 84). Everything else in this
repository's decision architecture is inside the blast radius -- see SCOPE / Constraints you MAY
challenge, and price what you challenge.

One planning-time constraint to NOTE (not an audit boundary): a temporary freeze makes all plans
IMPLEMENTATION-type. If your Arc-C sequence is naturally a multi-phase programme, say so plainly
and describe how it decomposes into atomic implementation units -- do not silently shrink the
recommendation to fit.

## OUTPUT

Two files, exact paths, where `<sha>` is the `<base-short-sha>` derived once in SETUP:

- `audits/contract-first-governance-<sha>.yaml`
- `audits/contract-first-governance-<sha>.md` -- prose companion, **<= 2500 words**, the
  executive layer a human reads first. Lead with Arc A. Include DD-D's comparison table.

Volume caps on the YAML, so anti-padding is enforceable and not merely urged: `findings` <= 20,
`rejected_candidates` <= 25, `content_class_routing` <= 10, `sampled_entry_dispositions` <= 13,
`migration_sequence` <= 12, Q9 additions <= 6.

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
    degraded_external: false
    external_sources: []              # [{title, url}], <= 6
    convergence_rounds: <int, 1-3>
    contract_notes: ""
    stale_anchors: []                 # [{anchor, expected, found}]
  question_answers:
    - {q: Q1, verdict: primary-mechanism-identified|contributing-factors-only|undetermined,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       external_checklist: [{property: EX1..EX13, rating: met|partial|missed, evidence: ""}]}
    - {q: Q3, verdict: primary-cause-established|contributing-only|undetermined, basis: [], prose: ""}
    - {q: Q4, verdict: ready|ready-with-gaps|not-ready, basis: [], prose: ""}
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       detection_ratings: [{property: parallel-contracts|contradictory-contracts|contract-code-drift,
                            rating: detected|partially-detected|undetected, evidence: ""}]}
    - {q: Q6, verdict: governance-warranted|absence-correct|partial, basis: [], prose: ""}
    - {q: Q7, verdict: single-end-state-recommended|options-with-tradeoffs|insufficient-evidence,
       basis: [], prose: ""}
    - {q: Q8, verdict: ordered-sequence-with-abort-criteria|partial-sequence|insufficient-evidence,
       basis: [], prose: ""}
    - {q: Q9, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
  intervention_erosion:               # exactly 14 rows: 9 kind=decision, 5 kind=audit_round
    - kind: decision|audit_round
      intervention: "<Decision NNN or audit prefix>"
      date: <ISO or null>
      size_bytes: <int|null>
      what_it_changed: ""
      relief_produced: ""
      held_until: ""
      ending_class: ceiling-raised|mechanism-unused|superseded-by-larger-entry|cost-exceeded-benefit|relief-still-holding|other
      note: ""
  end_state:
    corpus_shape: keep_monolith|extract_machine_semantics_only|extract_multiple_typed_fields|generate_curated_index|accelerate_portal_transition|other
    t15_verdict: sufficient_as_planned|sufficient_with_specific_amendments|materially_incomplete|wrong_end_state
    routing_rule: ""
    forcing_functions: [{mechanism: "", survives_failure_mode: "", cost: ""}]
  content_class_routing:
    - class_name: ""
      description: ""
      live_entry_count: <int|null>
      count_method: ""
      disposition: retain_full_decision|retain_decision_plus_contract|compact_to_decision_pointer|archive|migrate_to_other_governed_surface|remove_as_redundant_or_superseded
      remains_authoritative: ""
      history_preserved: ""
      counterfactual_loss: ""
      worked_exemplar: "Decision NN"
      blocker: ""
      confidence: CONFIRMED|HYPOTHESIS
  sampled_entry_dispositions:         # only entries sampled in E2 and DD-C; <= 13 rows.
                                      # An entry sampled by BOTH gets ONE row listing both tags.
                                      # Fewer than 13 rows is expected when the samples overlap.
    - {decision: "Decision NN", corpus: live|archive, sampled_in: [E2, DD-C],
       disposition: <same enum as content_class_routing.disposition>,
       remains_authoritative: "", history_preserved: "", counterfactual_loss: ""}
  migration_sequence:
    - step: <int>
      action: ""
      blocker: ""
      reversible: true|false
      abort_criterion: ""
      survives_failure_mode: ""
      derived_surface_effects: ""     # index regeneration, ops_decisions backfill, archive moves
      requires_human_ruling: ""       # "" if none
  per_surface_assessment:             # the SOLE home for maturity; summary does not repeat it
    - {surface: S1|S2|S3|S4|S5, maturity: frontier|strong|solid|nascent,
       strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S5, dimension: VD1..VD6, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - id: CFG-01                      # CFG-NN, zero-padded to two digits, sequential from CFG-01
      surface: S1|S2|S3|S4|S5|shared
      surfaces_affected: [S1]         # REQUIRED. The surfaces this finding's maturity counts
                                      # against. One element for a single-surface finding; two or
                                      # more when surface is `shared`. Never empty.
      question: Q1..Q9
      dimension: VD1..VD6
      title: ""
      evidence: "file:line|item-id"
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      survives_failure_mode: ""
      refutation: ""                  # strongest counter-argument, and why it failed
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate|retire
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                         item_ids: [], dedup_search_terms: [], dedup_hit_count: <int|null>, note: ""}
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
```

**Field semantics for the five disposal-support fields**, so nothing is written without a reader
-- the human disposing of this audit is that reader:

- `effort` -- T-shirt size of implementing `proposed_change`: XS < 1h, S < 1d, M < 1w, L >= 1w.
- `depends_on` -- finding ids that must land BEFORE this one is implementable; `[]` if none.
- `sequencing.safe_to_queue_now` -- true iff every `depends_on` is empty or already satisfied.
- `sequencing.blocked_behind` -- finding ids or roadmap item ids blocking it; `[]` if none.
- `per_surface_assessment.strengths` -- what that surface does well, in one or two sentences;
  required, because a rubric of gaps alone misrepresents a surface.
- `per_surface_assessment.top_gaps` -- the finding ids that most drove that surface's maturity.

**`survives_failure_mode`, pinned.** Legal values, in order of preference:

1. Any `ending_class` token EXCEPT `relief-still-holding` -- surviving a mode that never failed is
   incoherent.
2. The literal `no-erosion-established` -- REQUIRED when Q1's verdict is `undetermined`, or when
   every `intervention_erosion` row is `relief-still-holding`. This exists so a no-erosion finding
   is expressible; without it the honest no-erosion outcome would have no legal value.
3. A free-text named mechanism, when the fix survives something outside that enum.
4. `""` -- ONLY for a finding filed under Q1 itself, which diagnoses rather than remedies.

The same rule applies to the field on `migration_sequence[]` and `end_state.forcing_functions[]`.

**Ranking, pinned.** "An observed finding outranks a static one at equal severity" governs the
ORDER of `top_improvements` and the choice of `highest_leverage_change`. It does not reorder
`findings[]`, which stays in id order.

**Convergence counting, pinned.** `convergence_rounds` counts refutation passes RUN, including the
final pass that changed nothing. A single pass that changes nothing is `1`.

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list. `total_findings =
len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`. Candidates
fully covered by an existing owner live in `rejected_candidates[]`, NOT `findings[]`.
`rubric_ratings`, `question_answers`, `intervention_erosion`, `end_state`,
`content_class_routing`, `sampled_entry_dispositions`, `per_surface_assessment`, and
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

**Surface attribution, pinned.** A finding counts toward the maturity of every surface listed in
its `surfaces_affected` array -- not its `surface` scalar, and not whatever its `evidence` string
happens to mention. `surfaces_affected` is never empty, so no finding escapes attribution.

Maturity is computed LAST, per surface, top-down, first match wins. It is written in exactly one
place: `per_surface_assessment[].maturity`.

- **frontier** -- 0 open critical AND 0 open high findings attributed to that surface, AND every
  EX1-EX13 property in Q2's `external_checklist` rated `met` or `partial` -- never `missed`.
- **strong** -- 0 critical AND <= 1 high.
- **solid** -- <= 1 critical.
- **nascent** -- otherwise.

The EX clause is deliberately REPO-WIDE, not per-surface: EX1-EX13 rate the routing architecture
as a whole, so a single `missed` forecloses `frontier` for every surface simultaneously. That is
intended -- `frontier` here means the architecture is exemplary, not that one corner of it is.
`frontier` remains reachable where you argued a property-matched compensating control; this
prompt's framing forecloses no rating.

## COMMIT / PR MECHANICS

1. Derive the base ONCE (SETUP): `git fetch origin main` then `git rev-parse --short origin/main`.
   That commit IS the audited tree. Use the sha in both deliverable filenames, the branch name,
   and `meta.audited_commit`.
2. `git switch -c audit/contract-first-governance-<sha> origin/main` -- so the PR diff contains
   only your two deliverable files. This is a deliberate, documented exception to the repository's
   `claude/*` session-branch rule: this session needs a clean two-file diff off the audited base.
3. Pre-push gate: a clean YAML parse of your deliverable
   (`bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/contract-first-governance-<sha>.yaml`).
   Repo-wide validation is advisory outside CI here; an unrelated `validate --pre` failure goes in
   `meta.contract_notes` and is never fixed by you.
4. Commit with `user.name=Claude` and `user.email=noreply@anthropic.com`. Commit subject, exactly:

   `audit(contract-first-governance): decision/contract/change-record routing audit`

   Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, not a
   draft), title:

   `audit: decision / contract / change-record content routing and prior-intervention erosion (S1-S5)`

   Body: a 2-3 sentence lede plus the `summary:` block in a yaml fence.
6. **END THE TURN.** Do not poll for CI. Do not merge. Do not subscribe to PR activity. Do not
   self-approve. The human disposes.

## GUARDRAILS

- **Write boundary.** Restated once here as a closed list, because it is the one rule whose breach
  cannot be undone by the human: the ONLY files you create or modify in the repository tree are
  the two deliverables named in TASK. Not `docs/DECISIONS.md`. Not any contract. Not the roadmap.
  Not a recommendation. Not a fix to a failing check. If you believe a file needs changing, that
  belief is a finding.
- **Precision over volume.** Fewer than ~8 surviving findings is a valid result -- state it
  plainly and do not pad. A padded finding costs more than a missing one, because the human
  disposes of every row you write. Rejections are output: `rejected_candidates[]` longer than
  `findings[]` is a good outcome, not a weak one.
- **You are the sixth audit in this territory.** Five prior audits produced findings that were
  implemented and produced relief. The default expected value of another taxonomy is low. If,
  after Arc A, the honest answer is "the problem is not where the previous five looked", say that
  as the headline and let the rest of the audit follow from it.
- **No new standing prose.** Do not propose creating a standing prose-architecture document as a
  remedy; this repository routes forward intent to roadmap items, rationale to decisions, and
  semantics to contracts. You may propose new machine-readable artifacts, templates, and record
  types freely.
