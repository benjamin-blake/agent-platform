# AUDIT: Decision Knowledge Persistence Scalability

## TASK

Run this audit as GPT-5.6 Sol, a model created by OpenAI. Before SETUP, confirm your self-reported
model is exactly `GPT-5.6 Sol`. If it is not, create or modify nothing and stop with: `This audit
requires GPT-5.6 Sol.` Do not substitute another model or simulate that identity. Confirmation is
internal and is recorded only in the two deliverables' `meta.model` and `meta.model_provider`; it
does not create a third artifact or require a pre-audit chat response.

Audit the repository architecture used to preserve architectural ideas, rationale, semantics,
constraints, rejected alternatives, amendments, reversal conditions, and planned intent across
thousands of stateless AI-agent sessions. Assess both the built mechanisms and the designed-but-
unbuilt platform-roadmap end state: the Markdown decision corpus and archive; decision-entry
grammar, parser, generated index, validation, and decision-scout retrieval; `ops_decisions`, its
Class A contract, portal/backfill/cache paths, and intended SCD2 authority transition; machine-
readable contracts; candidate decisions and tier items; instruction routing; prior audit findings;
and Git history as provenance. Answer Q1-Q7. Deliver exactly two files:
`audits/decision-knowledge-persistence-scalability-<sha>.yaml` and
`audits/decision-knowledge-persistence-scalability-<sha>.md`. Other than the ignored/preflight
side effects explicitly allowed in SETUP, the ONLY repository-tree files you create or modify are
those two deliverables; never commit caches. This is a read-only architecture audit: you
draft the assessment; the human disposes. Do not implement, edit audited surfaces, or file or
update recommendations.

## CANDIDATE OBSERVATIONS VS VERDICTS

This prompt supplies facts and candidate hypotheses, never verdicts. ASSUME NO CANDIDATE IS A
REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the candidates below has failed.

Map every candidate to exactly one outcome:

- A confirmed defect with no sufficient owner goes in `findings`, classification `novel`.
- A defect owned by roadmap work whose remedy is insufficient or unbuilt goes in `findings`,
  classification `planned-insufficient` or `planned-unbuilt`.
- A candidate fully covered by traced implemented behavior goes in `rejected_candidates`, naming
  that implementation and its owner.
- A non-defect goes in `rejected_candidates`, naming the property-matched compensating control or
  explaining why absence is correct by design.

Owner sufficiency is pinned as follows. `planned-unbuilt` means a not-complete owning item has exit
criteria that property-match the whole remedy but the current defect remains. `planned-insufficient`
means an owner exists but its exit criteria omit part of the property needed to close the gap. A
candidate is `fully covered` only when implemented behavior is traced and passes the same
counterfactual; a roadmap promise alone is not full coverage. The executor judges property match.

Severity is assigned only after tracing and compensating-control analysis. Precision outranks
volume. Every candidate C1-C16 below must appear once in either `findings[].candidate_ids` or
`rejected_candidates[].candidate_ids`; extensions discovered by you need no candidate id.

## READ FIRST - DISAMBIGUATION TRAPS

1. `docs/DECISIONS.md`, `docs/DECISIONS_ARCHIVE.md`, `docs/decisions-index.json`,
   `logs/.decisions-index.jsonl`, and the `ops_decisions` table are distinct. Establish the
   authority and projection direction of each before judging duplication.
2. Contracts preserve normative machine-consumed semantics. Decisions preserve commitments,
   rationale, alternatives, consequences, and reversibility. Moving a rule into a contract does
   not by itself justify deleting or compacting its decision record.
3. Archive is not deletion. Compaction is not archival. A generated projection is not a manually
   synchronized companion. Name the exact lifecycle operation you recommend.
4. Decision 134 consciously retains prose-monolith authoring as an interim bridge. T1.5 plans a
   portal-read end state after parity and consumer cutover. Judge both horizons separately.
5. An SCD2 storage engine does not prove correct knowledge grain. Separately assess decisions,
   clauses, amendments, semantic assertions, and relationship edges.
6. Lower byte count is not scalable retrieval if the consumer still retrieves irrelevant content
   or misses binding context. Treat storage growth and per-session context selection separately.
7. `candidate_decisions[]` contains proposed commitments and gate relationships; numbered
   Decisions contain ratified commitments. Do not treat their state transitions as equivalent.
8. Prior audits covered premise integrity, growth/consolidation, prose authoring format, and agent
   context governance. They are dedup and sufficiency evidence, not facts to re-file under new ids.
9. T1.5 is roadmap item `T1.5`, not bootstrap schema item `T-1.5`. T5.4 is a reserved/tombstoned
   former retirement owner; verify the current ownership text rather than reviving it.
10. Git history is provenance, but not necessarily an adequate retrieval interface. Conversely,
    lack of a normalized field is not a defect if raw-block history plus a bounded projection
    property-matches the requirement.

## SCOPE

Built, first-class surfaces:

- `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md`: live and archived decision prose.
- `docs/contracts/decision-entry.yaml`: forward authoring, significance, compaction, and lifecycle
  grammar.
- `scripts/decisions_md.py`, `scripts/decisions_index.py`, `docs/decisions-index.json`, and
  `scripts/checks/decisions/`: parsing, projection, indexing, conformance, lifecycle, and size
  enforcement.
- `.claude/skills/decision-scout/SKILL.md`: planning-time retrieval and relevance consumer.
- `docs/contracts/ops_decisions.yaml`, `src/schemas/decision.py`, `scripts/ops_portal/decisions.py`,
  and relevant named-read/sync implementations: structured persistence and read paths.
- `docs/contracts/*.yaml`, especially file routing, instruction architecture, contract joins, and
  candidate-decision ratification: alternative semantic homes and traceability controls.
- `docs/ROADMAP-PLATFORM.yaml` candidate decisions and tier items relevant to persistence,
  contracts, context retrieval, decision graduation, or portal cutover.
- `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, and `.claude` workflow pointers only where they define
  how persistent knowledge reaches a fresh agent session.
- The four prior audit prompt/YAML/report trios whose exact paths are named in GROUNDING MAP.

Designed-but-unbuilt, first-class surface: T1.5's phases 2-6, including semantic definition,
content parity, decision read portal, named verb/cache retrieval, SCD2 authority, consumer and CI
guard repointing, and retirement conditions. Include any other relevant `not_started`,
`in_progress`, or `deferred_post_mvp` tier item found by targeted roadmap projection.

Context-only: Git history for provenance and change-frequency sampling; recommendation cache for
dedup; product roadmaps only if a persistence mechanism explicitly points to them.

Out of scope: adjudicating trading strategy or alpha; changing the DuckLake vendor choice;
redesigning unrelated CI, Terraform, or Lambda deployment; implementing findings; confidential
cloud identifiers or credentials.

Trust nothing. Verify every claim you rely on by reading its in-scope file or bounded sample in the
pinned tree. Re-derive every number you cite; do not attempt an unbounded repository inventory.
Put non-resolving or materially changed anchors in `meta.stale_anchors` and use the pinned tree as
truth.

Use exactly these assessment surfaces everywhere an output field says `surface`: S1
`decision_corpus`; S2 `authoring_lifecycle`; S3 `parser_index_guards`; S4 `agent_retrieval`; S5
`ops_decisions_data_plane`; S6 `contract_traceability`; S7 `roadmap_transition`; S8
`provenance_resilience`; or `shared`. Use `shared` only for a finding spanning at least two named
S1-S8 surfaces, and list those affected surfaces in its gap.

## SETUP

Evaluate setup in this order: (1) unborn repository -> stop; (2) dirty tree or target branch
collision -> remain on current HEAD and use the degraded path below; (3) clean tree with
`origin/main` available -> run the success path; (4) clean tree without `origin/main` -> run the
fallback path. First check `git status --porcelain`, then establish the audited base and branch.
The success path is:

```bash
git fetch origin main
BASE_SHA=$(git rev-parse --short origin/main)
git switch -c "audit/decision-knowledge-persistence-scalability-$BASE_SHA" origin/main
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

The audited tree is the new branch at `$BASE_SHA`; derive it once and use it in filenames,
`meta.audited_commit`, and the branch name. Create the branch before reading audited files or
running preflight, so preflight cannot exercise its main-only log-commit path. The audit workflow
authorizes this narrow clean-branch exception to the repository's default harness-session branch
rule; it exists so the PR diff contains exactly the two outputs. Do not audit unrelated
pre-existing working-tree changes.

If fetch or `origin/main` resolution fails, run instead:

```bash
BASE_SHA=$(git rev-parse --short HEAD)
git switch -c "audit/decision-knowledge-persistence-scalability-$BASE_SHA" HEAD
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

Set `meta.degraded_base=true`, record the failure in `meta.contract_notes`, and downgrade claims
depending on main parity to HYPOTHESIS. Push/PR may also be unavailable; use the terminal degraded
path in COMMIT / PR MECHANICS. If a referenced file is absent, record it in
`meta.stale_anchors` and continue.

Before either branch command, require `git status --porcelain` to be empty. If it is not empty, or
branch creation fails because the target exists, do not overwrite, delete, stash, or clean: remain
on current `HEAD`, use its short SHA/current branch, set `meta.degraded_base=true`, and record the
condition. This degraded path MUST NOT push or open a PR unless the final commit contains exactly
the two deliverables. Detached HEAD is acceptable for analysis/local commit. An unborn repository
is terminal: write no deliverables and report it.

Preflight is the required dedup cache generator and is not purely read-only: it writes ignored
cache/report files under `logs/`, can synchronize read caches, and can drain legacy outbox entries.
Because it runs only after switching off `main`, it must not create a Git commit. These documented
preflight side effects are the sole setup exception to the two-deliverable repository-tree write
boundary; never stage or commit them. Record non-cache external side effects reported by preflight
in `meta.contract_notes`. If `git status --short` after preflight shows a tracked change, do not
restore or edit it: record it, exclude it from staging, and proceed; the final staged diff must
still contain exactly the two deliverables.

DEDUP DISCIPLINE is mandatory and depends on generated caches. IF cache-gen fails (creds/egress
down): do NOT abort - set meta.degraded_dedup=true, mark every roadmap_crossref
confidence=HYPOTHESIS and dedup_hit_count=null, proceed. If Git history commands fail, set
`meta.degraded_history=true`, omit empirical history conclusions, and continue with static
evidence. No setup failure permits edits outside the two deliverables.

## NORTH STAR

Judge each surface against these non-absolutist principles; these are bars to reason against, not
patterns whose absence automatically proves a defect:

- One explicit semantic authority per knowledge class, with projections flowing one way.
- Durable rationale and rejected alternatives survive normalization and storage transitions.
- Normative rules are collocated with, typed by, and enforced through their owning contract when
  that improves machine use without erasing decision provenance.
- Stable identity, explicit lifecycle, bidirectional traceability, and append-preserving history.
- Grain-first data modeling: decision, version, clause, assertion, and relationship are separated
  only where their lifecycle or query needs justify it.
- Fresh sessions retrieve bounded, sufficient, task-relevant context and can explain both the
  current rule and why alternatives lost.
- Generated projections and parity checks prevent second authorities and silent content loss.
- Growth has explicit inflow, compaction, archival, retention, and authority-transition policy.
- Degraded reads fail visibly or fall back without converting stale caches into write sources.
- Planned work has explicit ownership, sequencing, acceptance, and migration safety.

## THE QUESTIONS

Q1 - DECISION-TO-CONTRACT DISPOSITION. The content-class taxonomy is the closed eleven-class list
in DD-C. Create one `content_dispositions` row for each class observed in at least two decisions
from the bounded whole-section live/archive samples in EMPIRICAL PASS; decisions merely encountered
through links, probes, prior audits, or contracts do not count. Absent or single-occurrence classes
need no row. Create one `sampled_decision_dispositions`
row for every sampled live AND archived whole numbered decision section, with `corpus: live|archive`.
For each row choose one: `retain_full_decision`, `retain_decision_plus_contract`,
`compact_to_decision_pointer`, `archive`, `migrate_to_other_governed_surface`, or
`remove_as_redundant_or_superseded`. State what remains authoritative, what historical material
survives, and the counterfactual loss if the move is made incorrectly. Answer-level verdict:
`sufficient`, `partial`, or `insufficient`.

Q2 - SCALABILITY. Can the architecture scale across thousands of sessions and continuing corpus
growth, considering storage, indexing, retrieval cost, relevance selection, contradictions,
consumer coupling, stale knowledge, availability, and recovery? Verdict: `scalable`,
`scalable_with_planned_work`, `partially_scalable`, or `not_scalable`.

Q3 - INDUSTRY PRACTICE. Rate the architecture `leading`, `strong`, `mixed`, or `weak`. Populate
`external_checklist` property-by-property with `met|partial|missed`; `partial` requires an argued,
property-matched compensating control:

1. ADR separation of decision, context, alternatives, consequences, and status.
2. Immutable or append-preserving history.
3. Explicit supersession, amendment, reversal, and lifecycle relationships.
4. Stable identifiers independent of presentation/storage.
5. Machine-queryable metadata and bounded retrieval.
6. Separation of normative specification from historical rationale.
7. Traceability from decision to contract, enforcement, implementation, evidence, and roadmap.
8. Single semantic authority with generated projections rather than duplicated authorities.
9. Schema evolution and migration compatibility.
10. Versioned, testable contracts.
11. Relevance-based context retrieval rather than mandatory whole-corpus loading.
12. Preservation of rejected alternatives and reversal conditions.
13. Governed retention, archival, compaction, and deletion.
14. Availability, disaster recovery, and explicit degraded-mode behavior.
15. Auditable change history through Git or an equivalent immutable record.

These 15 properties are the closed benchmark. If web access exists, consult at most 6 primary or
authoritative ADR, architecture-knowledge, schema-evolution, or event-history sources and record
title + URL in `meta.external_sources`; do not add properties. If browsing is unavailable, set
`meta.degraded_external=true` and rate against the pinned checklist without claiming prevalence.

Q4 - HEADROOM AND LIFECYCLE. Which decision types can leave the live corpus without weakening
institutional memory? Use per-class verdict `keep_live`, `compact_live`, `archive`,
`move_normative_content`, `retire_after_verified_migration`, or `do_not_store_as_decision`.
Answer-level verdict: `sufficient`, `partial`, or `insufficient`.

Q5 - INTERIM HEAVY-FIELD SEPARATION. Before T1.5, choose `keep_monolith`,
`extract_machine_semantics_only`, `extract_multiple_typed_fields`, `generate_curated_index`, or
`accelerate_portal_transition`. Test exact semantics, reversals, relationship graphs, alternatives,
consequences, enforcement pointers, and roadmap links. Determine whether decision-scout should use
a bounded structured projection and whether any companion would become a second authority.

Q6 - END STATE. Is T1.5 sufficient across semantic definition, parity, read portal, all-consumer
cutover, SCD2 history, Markdown retirement, resilience, and correct grain? Verdict:
`sufficient_as_planned`, `sufficient_with_specific_amendments`, `materially_incomplete`, or
`wrong_end_state`.

Q7 - QUESTIONS NOT ASKED. Answer and extend: What is the correct persistence unit? How is relevant
context selected? How does provenance survive decision-to-contract moves? What detects cross-
surface contradictions? What is the disaster-recovery and offline-read story after Markdown?
Which fields need SCD2 and which relations need append-only edge entities? How are provisional,
rejected, superseded, reversed, and expired ideas distinguished? What thresholds trigger lifecycle
action? Does splitting fields reduce measured context cost or only move bytes? Can future agents
recover both current authority and rejected-alternative reasoning? This question uses `answers[]`,
not a single verdict.

## RUBRIC

Rate every structurally applicable surface `strong|adequate|weak|absent|n/a` on:

- VD1 semantic authority; VD2 retrieval scalability; VD3 historical fidelity; VD4 machine
  enforceability; VD5 traceability; VD6 lifecycle governance; VD7 data-model fitness; VD8 drift
  resistance; VD9 resilience; VD10 context efficiency; VD11 industry alignment; VD12 roadmap
  sufficiency.

`n/a` is correct and costless where a dimension does not apply. Never manufacture a rating or
finding to fill a matrix cell.

## DEEP-DIVES

DD-A - AUTHORITY GRAPH (feeds Q1, Q4, Q5). Draw the direction of authority/projection among
Markdown, archive, index, table, cache, contracts, roadmap, and scout. For each edge, identify its
writer, reader, parity check, and failure behavior. Flag a cycle only after tracing it.

DD-B - KNOWLEDGE-GRAIN TEST (feeds Q2, Q5, Q6). State one row per what for the current and planned
table. Test whether clauses, amendments, supersession edges, semantic assertions, alternatives, or
enforcement links have independent identity/lifecycle/query needs. Do not normalize by reflex;
compare query and integrity benefits with migration and join costs.

DD-C - CONTENT-CLASS DISPOSITION (feeds Q1, Q4). Build a content taxonomy from sampled entries:
commitment, rationale, alternative, consequence, invariant, schema/field semantics, procedure,
operational fact, roadmap status, enforcement detail, and review/reversal trigger. Map each class
to its ideal authority and retained provenance.

DD-D - RETRIEVAL PATH (feeds Q2, Q5, Q6). Trace a fresh `/plan` session from task terms through
decision-scout to binding context. Apply two counterfactuals: would it miss a relevant decision if
the full Markdown read were removed; would it still load the whole corpus if 90% were irrelevant?
Compare the built index and planned named-read/cache path.

For DD-D/T1.5 consumer completeness, inventory production references with bounded `rg` over
`.claude/`, `scripts/`, `src/`, and `docs/contracts/` for
`DECISIONS.md|DECISIONS_ARCHIVE.md|decisions-index|parse_decisions_md|decision_by_id|decisions_max_updated`.
Use exactly:

```bash
rg -n --glob '!**/__pycache__/**' --glob '!**/*.pyc' \
  'DECISIONS\.md|DECISIONS_ARCHIVE\.md|decisions-index|parse_decisions_md|decision_by_id|decisions_max_updated' \
  .claude scripts src docs/contracts
```

Include Python imports/calls, YAML fields consumed by code, and Markdown command/skill directives
that instruct an agent to read/query a decision surface. Exclude Python comments/docstrings with no
call site, YAML/Markdown examples, historical rationale, and grounding citations that merely name a
surface. This is the closed consumer inventory; record every match, verdict, and reason.

DD-E - MIGRATION SAFETY (feeds Q3, Q6). Trace content hashes/raw blocks, typed fields, SCD2 merge
keys, parity gates, cache rebuild, consumer cutover, rollback/degraded read, and Markdown retirement.
State the irreversible-loss boundary and whether acceptance criteria cover it.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify every anchor against the pinned tree
before relying on it; anchors are leads, not authority.

- `docs/PROJECT_CONTEXT.md` Rules: decisions plus archive have byte/header ceilings and the
  platform roadmap has a separate line ceiling. Its later T5.4 retirement-owner pointer is stale
  relative to the roadmap's T1.5 sole-owner text; treat that mismatch as C16 for adjudication, not
  as authority for retirement ownership.
- `docs/DECISIONS.md`, Decision 134: interim prose retention, size governance, authoring grammar,
  ETL parity direction, T1.5 portal-read correction, and reversal conditions.
- `docs/DECISIONS.md`, Decisions 146, 149, 150, and 151: archival, compaction, significance, and
  intent-capture mechanisms. Verify current numbering/titles in the file.
- `docs/contracts/decision-entry.yaml`: required/optional markers, significance routing,
  compaction grammar and procedure, amendment forms, and index/lifecycle provisions.
- `scripts/checks/decisions/validate_decisions_size.py`: live byte/header and combined ceilings.
- `scripts/decisions_md.py`: shared Markdown grammar and typed extraction.
- `scripts/decisions_index.py` plus `docs/decisions-index.json`: generated discovery projection and
  freshness contract.
- `.claude/skills/decision-scout/SKILL.md`: present full-file binding read and stated Lambda/portal
  migration contract.
- `docs/contracts/ops_decisions.yaml`: field-semantic authority, current columns, SCD2 semantics,
  parity fields, and incomplete graduation phases.
- `docs/ROADMAP-PLATFORM.yaml`, T1.5: phases 2-6, content parity, named read/cache, all-consumer
  repointing, and retirement ownership. Treat embedded `grep -r` acceptance text as a static
  roadmap string; never execute it. Use bounded `rg` equivalents.
- `docs/ROADMAP-PLATFORM.yaml`, T0.7b and T0.12.5: built decision write path and Class A contract.
- `docs/contracts/instruction-architecture.yaml`: persistent knowledge routing into fresh agent
  contexts.
- `docs/contracts/candidate-decision-ratification.yaml`: candidate-to-ratified transition and
  referential controls.
- `docs/audit-prompts/AUDIT-decision-log-premise-integrity.md`,
  `audits/decision-log-premise-integrity-8fb581e.yaml`, and
  `audits/decision-log-premise-integrity-8fb581e.md`.
- `docs/audit-prompts/AUDIT-decision-consolidation-growth.md`,
  `audits/decision-consolidation-growth-f79d6b5.yaml`, and
  `audits/decision-consolidation-growth-f79d6b5.md`.
- `docs/audit-prompts/AUDIT-decisions-authoring-format.md`,
  `audits/decisions-authoring-format-d140093.yaml`, and
  `audits/decisions-authoring-format-d140093.md`.
- `docs/audit-prompts/AUDIT-agent-context-governance.md`,
  `audits/agent-context-governance-cdfda88.yaml`, and
  `audits/agent-context-governance-cdfda88.md`.

Candidate set:

- C1 The live Markdown corpus is near its configured byte ceiling; re-derive size and headroom.
- C2 Decision 134 makes the monolith an explicit bridge rather than an accidental default.
- C3 T1.5 requires parity and consumer cutover before Markdown retirement.
- C4 A canonical grammar and shared parser exist and are forward-enforced for new entries.
- C5 A committed generated index exists while decision-scout has a full-corpus binding-read rule.
- C6 `ops_decisions` is structured and SCD2-backed while Markdown remains authoring/number authority.
- C7 Some bodies combine historical rationale with normative mechanisms also represented elsewhere.
- C8 Manual heavy-field extraction could create a second semantic authority; generation could avoid it.
- C9 Four prior audits own overlapping findings and may already cover candidate remedies.
- C10 The requested cross-session persistence scope spans more surfaces than any one prior audit.
- C11 The planned table grain may or may not fit independently evolving clauses and relationships.
- C12 Contracts can own normative semantics but do not automatically replace rationale/provenance.
- C13 Git preserves changes but is not a bounded semantic retrieval interface.
- C14 Markdown, archive, index, warehouse, cache, contracts, and roadmap form multiple representations
  whose direction and parity controls differ.
- C15 Scale has two independent axes: corpus growth and per-session relevance/cost.
- C16 `docs/PROJECT_CONTEXT.md` retains a T5.4 retirement-owner pointer while the platform roadmap
  names T1.5 as sole owner and reserves/tombstones T5.4.

## EMPIRICAL PASS

Use bounded samples only:

- Read no more than 24 full live decisions. Mandatory grounding entries are exactly Decisions 134,
  146, 149, 150, and 151. Then fill in this order, stopping at 24: up to 8 entries ordered by
  explicit `Date` descending then decision number descending; up
  to 6 entries ordered by UTF-8 byte length of the complete heading-through-section block; and up
  to 5 older entries. Visit number bands 1-39, 40-69, and 70-99 in that order, choosing lowest then
  highest live number not already selected, and cycle bands until five are selected or no candidates
  remain. Overlap counts once. Record ids and selection reason.
- Read no more than 8 archived decisions. Group by exact parsed status; visit groups in descending
  member-count order, ties alphabetical. Select each group's lowest then highest decision number;
  if fewer than 8 result, cycle the same order selecting next-lowest then next-highest unselected
  numbers until 8 are selected or the archive is exhausted. Record the observed status set.
- Inspect no more than 12 contract-to-decision links across at least four of: Class A, Class B,
  Class C, and free-form governance contracts as defined by their metadata/comments. Select up to
  three links per class in lexicographic contract-path order, taking the first citation in file
  order; stop at 12.
- Inspect no more than 12 recent Git commits touching decision mechanisms and no history earlier
  than 180 days before the audited commit.
- Run at most 8 static retrieval probes against `docs/decisions-index.json` and the decision-scout
  procedure. Seed each with a concrete concept from a sampled decision. Establish expected binding
  ids only from explicit `Related`, `Superseded by`, contract `decisions_cited`, or roadmap
  `related_decisions` edges - never from the auditor's intuition. Apply the index fields and the
  scout's written selection rules exactly as present; because the scout is an LLM procedure, do
  not claim a runtime returned set. Record discoverable ids, expected ids, edge source, and any
  static false-negative/positive mechanism. Tag every probe `static`.

For every sample ask: would the conclusion change if the duplicated surface disappeared; would a
control fail if the alleged defect were real; would an agent recover the binding rule and its why?
Tag evidence `static` or `observed`. At equal severity, observed findings outrank static findings.
Do not exceed these caps.

## METHOD

P0 complete SETUP, including clean branch creation. P1 read governing decisions/contracts and re-derive inventory. P2 trace the authority graph. P3
perform DD-A through DD-E. P4 run the bounded empirical pass. P5 rate rubric cells. P6 deduplicate
every candidate and emerging finding. P7 draft findings and question answers. P8 run the recursive
adversarial-review loop below. P9 revise only for accepted challenges, recompute counts/ratings, and
synthesize maturity last.

Before mapping C1-C16, independently write between one and five failure hypotheses derived only
from Q1-Q7, NORTH STAR, and traced surfaces. Store them in `independent_hypotheses`; only then map
C1-C16.

RECURSIVE ADVERSARIAL REVIEW - REQUIRED, MAXIMUM 3 ROUNDS. After the first complete YAML and report
draft, run three independent reviews from different angles in each round. Prefer three fresh
read-only subagents with no shared review context; if subagents are unavailable, perform three
separate passes with their evidence and conclusions kept distinct. Only the primary executor may
write the deliverables. Reviewers receive completed, immutable draft snapshots after primary
writing pauses; they run no setup, branch, Git, cache, or write commands and never edit files.

- AR-A, institutional-memory historian: attack loss of rationale, alternatives, chronology,
  reversibility, provenance, and future explainability.
- AR-B, data/knowledge architect: attack grain, SCD2 semantics, identity, graph relationships,
  projections, parity, scale, retrieval precision, and failure recovery.
- AR-C, skeptical operator/industry challenger: attack feasibility, migration sequencing,
  compensating controls, industry-checklist inflation, roadmap dedup, cost, and whether findings
  solve measured problems.

Each reviewer receives the current two drafts plus the pinned tree and returns challenges shaped
`{id, angle, target: question|finding|rating|recommendation, claim, counterevidence,
property_at_risk, reviewer_recommendation: accept|reject, rationale}`. The PRIMARY executor, not the reviewer,
sets `final_disposition` after tracing counterevidence. Record every challenge and both dispositions
in `meta.adversarial_reviews`. If any challenge is accepted in rounds 1-2, revise the deliverables,
recompute all dependent fields, and start a new round with three fresh perspectives. Stop early only when one
round produces zero accepted challenges. Stop unconditionally after round 3 and record unresolved
accepted challenges in `meta.review_residuals`; an accepted challenge is unresolved only when the
primary agrees it is valid but cannot incorporate it without breaching scope, contradicting
stronger evidence, or inventing unavailable evidence. State which condition applies and downgrade
the affected conclusion to HYPOTHESIS; do not pretend convergence. This is recursive
review of evolving drafts, not three reviews of a frozen draft. It does not authorize extra files,
unbounded repository sampling, or more than 3 rounds.

For a round-3 accepted challenge that can be incorporated, revise it, set
`resolution_state: resolved_without_revalidation`, recompute dependent fields, and do not run a
fourth round. A round-3 accepted challenge that cannot be incorporated follows the residual rule
with `resolution_state: residual`. Round 1-2 accepted challenges use
`resolution_state: resolved_and_revalidated` only after the next round examines the revision.

If subagents are unavailable, `separate_pass` means complete and record AR-A without consulting
AR-B/AR-C notes, clear working notes, then repeat for AR-B and AR-C. Set
`meta.degraded_review_independence=true`; downgrade conclusions supported only by reviewer agreement
to HYPOTHESIS. Every accepted challenge, including editorial/metadata corrections, forces revision
and another round unless recorded as a residual under the rule above.

## DEDUP DISCIPLINE

Before filing each finding, search `docs/ROADMAP-PLATFORM.yaml`, both decision files,
`logs/.recommendations-log.jsonl`, the four prior audit YAMLs, and every depth-one
`docs/plans/*.yaml` plan (the repository deliberately retains completed YAML plans there pending a
lagged sweep). Record case-insensitive literal search terms and the count of distinct matching
artifacts, not occurrence count. A hit triggers sufficiency assessment or rejection, never
rediscovery. A finding without a recorded negative search remains HYPOTHESIS. A candidate fully
covered by traced implemented behavior belongs in `rejected_candidates`, not findings.

Do not flag as defects without demonstrating their premise failed: the public/confidential-data
boundary; warehouse source-of-truth and read-cache-never-write rules; Decision 134's interim prose
choice; Decision 86 routing rationale to decisions and field semantics to contracts; Decision 110
agent-first principles; Decision 67's current STRATEGIC freeze; T1.5's parity-before-retirement
rule; or Git/PR review for low-frequency human-authored governance before authority transition.

## OUTPUT

The YAML must conform to this shape; all enums are closed as shown:

```yaml
audit:
  meta:
    audited_commit: <short sha>
    intended_base_branch: main
    base_ref: <origin/main on success; HEAD or current branch/ref on degraded path>
    model: GPT-5.6 Sol
    model_provider: OpenAI
    methodology_version: 1
    scope_surfaces: []
    degraded_dedup: false
    degraded_base: false
    degraded_history: false
    degraded_external: false
    degraded_review_independence: false
    contract_notes: ""
    stale_anchors: []
    empirical_samples: [{class, ids: [], selection: ""}]
    external_sources: [{title, url}]
    adversarial_reviews:
      - round: 1
        reviewers:
          - {angle: historian|data_architect|operator_challenger, mode: subagent|separate_pass,
             reviewer_id, context_isolation: fresh_subagent|sequential_cleared_notes,
             challenges: [{id, target, claim, counterevidence, property_at_risk,
                           reviewer_recommendation: accept|reject,
                           final_disposition: accept|reject,
                           resolution_state: rejected|resolved_and_revalidated|resolved_without_revalidation|residual,
                           rationale}]}
        accepted_count: 0
    review_residuals: []
  independent_hypotheses:
    - {id: IH-1, hypothesis: "", evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}], disposition: finding|rejected|context_only, basis: []}
  question_answers:
    - {q: Q1, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q2, verdict: scalable|scalable_with_planned_work|partially_scalable|not_scalable,
       basis: [], prose: ""}
    - q: Q3
      verdict: leading|strong|mixed|weak
      basis: []
      prose: ""
      external_checklist: [{property, rating: met|partial|missed, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]}]
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q5, verdict: keep_monolith|extract_machine_semantics_only|extract_multiple_typed_fields|generate_curated_index|accelerate_portal_transition,
       basis: [], prose: ""}
    - {q: Q6, verdict: sufficient_as_planned|sufficient_with_specific_amendments|materially_incomplete|wrong_end_state,
       basis: [], prose: ""}
    - q: Q7
      answers: [{question, answer, basis: []}]
  content_dispositions:
    - {content_class, sample_decision_ids: [], q1_verdict: retain_full_decision|retain_decision_plus_contract|compact_to_decision_pointer|archive|migrate_to_other_governed_surface|remove_as_redundant_or_superseded,
       q4_lifecycle: keep_live|compact_live|archive|move_normative_content|retire_after_verified_migration|do_not_store_as_decision,
       current_authority, target_authority, retained_provenance, rationale}
  sampled_decision_dispositions:
    - {decision_id, corpus: live|archive, selection_reason, content_classes: [], q1_verdict: retain_full_decision|retain_decision_plus_contract|compact_to_decision_pointer|archive|migrate_to_other_governed_surface|remove_as_redundant_or_superseded,
       q4_lifecycle: keep_live|compact_live|archive|move_normative_content|retire_after_verified_migration|do_not_store_as_decision,
       basis: []}
  deep_dives:
    authority_edges: [{from, to, direction: authoritative_to_projection|reference|write|read, writer, reader, parity_control, failure_behavior, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]}]
    grain_assessment: [{entity, one_row_per, identity, lifecycle, queries_served, verdict: keep_embedded|normalize|projection_only, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]}]
    retrieval_probes: [{concept, expected_ids: [], expected_edge_sources: [], discoverable_ids: [], false_negative_mechanism, false_positive_mechanism, evidence_kind: static, evidence: [{path, line_start, line_end, item_id, evidence_kind: static}]}]
    migration_boundary: {irreversible_step, parity_controls: [], degraded_read_path, verdict, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]}
    consumer_inventory: [{path, symbol_or_match, included: true|false, reason, target_state, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]}]
  per_surface_assessment:
    - {surface: S1|S2|S3|S4|S5|S6|S7|S8, maturity: frontier|strong|solid|nascent, strengths: "", top_gaps: []}
  rubric_ratings:
    - {surface: S1|S2|S3|S4|S5|S6|S7|S8, dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7|VD8|VD9|VD10|VD11|VD12,
       rating: strong|adequate|weak|absent|n/a, evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}], note: ""}
  findings:
    - id: DKP-01
      candidate_ids: []
      surface: S1|S2|S3|S4|S5|S6|S7|S8|shared
      question: Q1|Q2|Q3|Q4|Q5|Q6|Q7
      dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7|VD8|VD9|VD10|VD11|VD12
      title: ""
      evidence: [{path, line_start, line_end, item_id, evidence_kind: static|observed}]
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref:
        classification: novel|planned-insufficient|planned-unbuilt
        item_ids: []
        dedup_search_terms: []
        dedup_hit_count: 0
        confidence: CONFIRMED|HYPOTHESIS
        note: ""
      effort: XS|S|M|L
      depends_on: []
      sequencing: {safe_to_queue_now: true, blocked_behind: [], note: ""}
  rejected_candidates:
    - {candidate_ids: [], candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    top_improvements: []
    highest_leverage_change: ""
    maturity_by_surface: {}
```

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) =
novel + planned_insufficient + planned_unbuilt`; fully-covered candidates live in
`rejected_candidates`, NOT findings; `rubric_ratings` / `question_answers` /
`content_dispositions` are systems-of-record referenced FROM findings, never re-counted;
`top_improvements` and `highest_leverage_change` MUST be finding ids. If there are zero findings,
set `highest_leverage_change: "none"`.

Every `basis` list contains finding ids, rejected-candidate labels, or `context:<deep-dive-key>`.
Every evidence list uses `{path, line_start, line_end, item_id, evidence_kind}`: populate path and
positive line range for files; populate item_id for roadmap/decision/commit/observed-command
evidence; either side may be empty, never both.

`control_property_match` is required when a compensating control causes dismissal: name the
property exercised, cite where it operates, and state why that control would fail if the defect
were real. CONFIRMED requires at least one resolving structured evidence item; less is HYPOTHESIS.

The Markdown companion is the human-first executive layer, at most 1,500 words. It answers Q1-Q7,
states the recommended interim and end-state architectures, summarizes adversarial-review
convergence/residuals, and references YAML finding ids rather than duplicating the findings list.

## SEVERITY AND MATURITY

Assign severity after judgment. Critical means the persistence system can produce a wrong-but-
trusted binding rule, irreversibly lose governing knowledge, or authorize destructive migration
without parity. High materially weakens cross-session correctness and lacks sufficient
property-matched controls. Medium is bounded ambiguity, redundancy, inconsistency, or scale debt
with a clear fix. Low is clarity or wording.

Compensating controls count only if they exercise the same property and would fail if the alleged
defect were real. A control unable to catch the break neither lowers severity nor supports
dismissal.

Compute maturity last, per surface, top-down, first match wins. For a surface, count findings whose
`surface` equals that surface plus findings whose `surface` is `shared` and whose evidence or gap
explicitly names it. Apply the Q3 checklist globally because it rates the architecture as a whole;
therefore any `missed` property prevents `frontier` for every surface but does not affect lower
tiers. `frontier` = zero applicable critical/high findings and every Q3 external-checklist property
is `met` or `partial`, never `missed`. `strong` = zero applicable critical and at most one
applicable high. `solid` = at most one applicable critical. `nascent` = otherwise. Frontier remains
reachable when a `partial` is supported by a property-matched compensating control.
`per_surface_assessment[].maturity` and the same key in `summary.maturity_by_surface` must match.

## COMMIT / PR MECHANICS

1. Do not switch again. On the success or clean-HEAD fallback path, confirm SETUP created
   `audit/decision-knowledge-persistence-scalability-$BASE_SHA`. On the dirty-tree/collision
   degraded path, confirm the current branch/ref equals `meta.base_ref`. In every path, the staged
   diff must contain only the two deliverables.
2. Validate YAML with:
   `bin/venv-python -c 'import pathlib,yaml; yaml.safe_load(pathlib.Path("audits/decision-knowledge-persistence-scalability-'"$BASE_SHA"'.yaml").read_text())'`.
   Then run this minimum semantic-consistency check, which creates no file. It supplements rather
   than replaces the executor's obligation to self-check every closed enum and shape above:

   ```bash
   bin/venv-python - "$BASE_SHA" <<'PY'
   import sys
   from pathlib import Path
   import yaml
   audit = yaml.safe_load(Path(f"audits/decision-knowledge-persistence-scalability-{sys.argv[1]}.yaml").read_text())["audit"]
   findings = audit["findings"]
   summary = audit["summary"]
   assert audit["meta"]["model"] == "GPT-5.6 Sol"
   assert audit["meta"]["model_provider"] == "OpenAI"
   classes = [f["roadmap_crossref"]["classification"] for f in findings]
   assert summary["total_findings"] == len(findings)
   assert summary["novel_count"] == classes.count("novel")
   assert summary["planned_insufficient_count"] == classes.count("planned-insufficient")
   assert summary["planned_unbuilt_count"] == classes.count("planned-unbuilt")
   seen = [c for f in findings for c in f.get("candidate_ids", [])]
   seen += [c for r in audit["rejected_candidates"] for c in r.get("candidate_ids", [])]
   assert len(seen) == 16 and set(seen) == {f"C{i}" for i in range(1, 17)}
   assert 1 <= len(audit["independent_hypotheses"]) <= 5
   assert [q["q"] for q in audit["question_answers"]] == [f"Q{i}" for i in range(1, 8)]
   assert len(audit["question_answers"][2]["external_checklist"]) == 15
   assert 1 <= len(audit["meta"]["adversarial_reviews"]) <= 3
   dispositions = audit["sampled_decision_dispositions"]
   assert len(dispositions) == len(set(d["decision_id"] for d in dispositions))
   assert all(d["corpus"] in {"live", "archive"} for d in dispositions)
   finding_ids = {f["id"] for f in findings}
   assert set(summary["top_improvements"]) <= finding_ids
   assert summary["highest_leverage_change"] in finding_ids | {"none"}
   surface_maturity = {row["surface"]: row["maturity"] for row in audit["per_surface_assessment"]}
   assert summary["maturity_by_surface"] == surface_maturity
   PY
   ```
   `bin/venv-python -m scripts.validate --pre` is advisory outside CI. Record an unrelated failure
   in `meta.contract_notes`; never fix it outside the write boundary.
3. Stage only the two explicit paths with `git add
   audits/decision-knowledge-persistence-scalability-$BASE_SHA.yaml
   audits/decision-knowledge-persistence-scalability-$BASE_SHA.md`. Confirm
   `git diff --cached --name-only` returns exactly those paths. Commit using
   `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign
   -m "audit: decision knowledge persistence scalability"`. Never use `git commit -a`. Push with
   `git push -u origin HEAD`.
4. Open a ready-for-review PR against `main` with title
   `audit: decision knowledge persistence scalability (decisions, contracts, roadmap, and retrieval)`.
   The body contains a 2-3 sentence lede plus `audit.summary` in a YAML fence. If the base was
   degraded or push/PR tooling is unavailable, commit locally, record the exact failure in both
   deliverables, do not invent a PR URL, and end the turn with the local branch and commit SHA for
   human recovery.
5. END THE TURN. Do not poll, merge, subscribe, self-approve, or implement findings. The human
   disposes of the audit PR.

## GUARDRAILS

The closed write list is the two audit deliverables only. Never alter decisions, contracts,
roadmaps, caches, code, tests, recommendations, or plans. Do not expose confidential identifiers.
Do not run Terraform apply or deploy anything. Never turn a roadmap hit into a novel finding
without assessing owner sufficiency. Fewer than five surviving findings is a valid
result - state it; do not pad. Precision over volume. Complete the required recursive adversarial
review in at most three rounds, record unresolved challenges honestly, and do not convert reviewer
assertions into findings without primary evidence tracing.
