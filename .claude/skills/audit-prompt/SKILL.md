---
name: audit-prompt
description: "Use when: running the /audit workflow, composing an audit prompt for a high-capability model, building a read-only design-review brief. Methodology for authoring a self-contained, zero-ambiguity audit prompt that a fresh expensive-model session executes without clarification. The composing session does the cheap work (grep, anchors, dedup pointers); the prompt spends the executor's cognition on judgment only."
required-context:
  - docs/PROJECT_CONTEXT.md
---

# Audit-Prompt Methodology

## Intent

This skill composes PROMPTS, not audits. The deliverable is `docs/audit-prompts/AUDIT-{slug}.md`:
a self-contained brief that a fresh session on the target high-capability model (the "executor
model") runs verbatim, with no ability to ask clarifying questions. The composing session (this
one, on a cheaper model) pays for all discovery; the executor model pays only for judgment.

Division of labor -- the single governing principle:

| Cheap (do it HERE, at compose time) | Expensive (delegate to the executor model) |
|---|---|
| Locating files, anchors, sizes | Judging whether an observed behavior is a defect |
| Enumerating surfaces, decisions, roadmap items | Weighing compensating controls |
| Stating observed facts neutrally | Adjudicating candidates to verdicts |
| Naming disambiguation traps | Rating rubric dimensions |
| Recording dedup pointers | Answering the decisive questions |
| Pinning enums, schemas, mechanics | Synthesis and recommendation |

A fact the executor must rediscover is compose-time work left undone. A verdict the prompt
pre-supplies is executor judgment stolen -- and a confirmation-bias defect (see BP2).

## Canonical Prompt Anatomy

Every generated prompt contains these sections, in this order. `M` = mandatory, `C` = conditional
(include when the trigger applies). Section headers in the generated prompt are UPPERCASE.

| # | Section | M/C | Purpose |
|---|---|---|---|
| 1 | TASK | M | One paragraph: target system, surfaces, question stubs (Q1..Qn), deliverable paths, write boundary, disposal clause ("you draft; the human disposes"). The write boundary is scoped to the repository tree: "the ONLY files you create or modify in the tree are the two deliverables"; regenerating gitignored local caches per SETUP is expected and does not breach it (never commit them). |
| 2 | CANDIDATE OBSERVATIONS vs VERDICTS | M | The epistemic contract, placed before anything it governs: the prompt hands FACTS and CANDIDATE hypotheses, never verdicts. Per-candidate adjudication enum, with its mapping to the output contract pinned: CONFIRMED-defect -> findings, classification novel; planned whose owning item's remedy is insufficient or unbuilt -> findings, classification planned-insufficient / planned-unbuilt; planned and fully covered by the owning item -> rejected_candidates; not-a-defect -> rejected_candidates (naming the compensating control). Include verbatim: "ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT" and "a run that merely confirms the candidates below has failed". |
| 3 | READ FIRST / disambiguation traps | C | Every term that names two things, every plausible-but-wrong audit target discovered at recon. State what is in scope, what is context-only, and the misread each trap invites. Trigger: recon found at least one. |
| 4 | SCOPE | M | Surfaces enumerated with their state (built vs designed-unbuilt); shared vocabulary and tier/term definitions; out-of-scope areas named in one line each; the trust-nothing clause: "obtain every file/line/size by reading the file -- trust no number quoted here; re-derive from the repo and record any non-resolving anchor in meta.stale_anchors". |
| 5 | SETUP | M | Exact permitted setup commands plus a degraded path for each anticipated failure: never abort -- set a named meta flag, downgrade affected confidences, proceed. Always present: DEDUP DISCIPLINE (13) is mandatory and depends on generated caches. In this repo the canonical executor cache-gen command to pin is `bin/venv-python -m scripts.session.preflight --roadmap-detail full` (populates `logs/.preflight-report.json` + `logs/.recommendations-log.jsonl`). Pin the degraded-dedup hatch verbatim, adapted: "IF cache-gen fails (creds/egress down): do NOT abort -- set meta.degraded_dedup=true, mark every roadmap_crossref confidence=HYPOTHESIS and dedup_hit_count=null, proceed." |
| 6 | NORTH STAR | M | The ideal-state bar as named principles the rubric references. Mark judgment-bearing principles explicitly non-absolutist ("this is a bar you judge each surface against"), so the executor argues rather than pattern-matches. |
| 7 | THE QUESTIONS | M | Full text of Q1..Qn, each first-class with its own answer slot in the output. The composer pins each question's verdict enum at compose time and presents it at the scope gate; default when nothing better fits: sufficient / partial / insufficient. If a question rates the design against industry practice, it must embed an EXTERNAL CHECKLIST -- named external practices the composer enumerates at compose time (e.g. presubmit/postsubmit split, hermetic builds, mutation testing) -- assessed property-by-property in that question's answer; the maturity top tier references this checklist as its single source. The final question is always "questions the requester did not think to ask", seeded with compose-time candidates the executor must answer AND extend. |
| 8 | RUBRIC | M | Dimensions VD1..VDn rated per surface. Pinned enum: strong / adequate / weak / absent / n/a. Derive dimensions at compose time from the North Star principles crossed with the question set: every question is served by at least one dimension, every dimension is referenced by at least one question or deep-dive. State that n/a is correct and costless where a dimension does not structurally apply -- never manufacture a rating or finding to fill a cell. |
| 9 | DEEP-DIVES | C | DD-A.. blocks, each feeding named questions, for threads needing more than a rubric cell. Trigger: any question requires end-to-end tracing. |
| 10 | GROUNDING MAP | M | file:line anchors + neutrally stated observed facts + governing decisions/contracts. Open with the cognition-allocation statement ("this map spends your cognition on judgment, not grep") and the verify-before-relying rule. Facts carry no adjectives that imply a verdict. |
| 11 | EMPIRICAL PASS | C | Hard sampling bounds ("<= N recent X -- do NOT exceed"), the counterfactual test applied per sample, evidence_kind tagging (static / observed), and the rule that observed findings outrank static ones at equal severity. Trigger: sampled artifacts exist. |
| 12 | METHOD | M | Phases P1..Pn: read -> trace -> deep-dive -> empirical -> rate -> dedup -> synthesize. Synthesis and maturity computation always LAST. |
| 13 | DEDUP DISCIPLINE | M | Before filing any finding: grep the named ownership surfaces (roadmap, decisions, recommendations log); record search terms + hit count on the finding; a hit means sufficiency-assessment or rejected_candidates, never a fresh discovery; a finding without a recorded negative search is a HYPOTHESIS. Include the deliberate-constraints do-not-flag list from recon. |
| 14 | OUTPUT | M | The pinned output contract (below): audit YAML + companion report, enums inline, counting invariant stated. |
| 15 | SEVERITY + MATURITY | M | Severity assigned AFTER judgment, by defect class, never inherited from the prompt's framing; the property-match rule for compensating controls; maturity computed last, top-down, first match wins. |
| 16 | COMMIT / PR MECHANICS | M | Exact commands: base-sha derivation, branch name, commit identity, push, PR creation call with title/body, then END THE TURN -- no polling, no merging. |
| 17 | GUARDRAILS | M | Write boundary restated as a closed list; honesty clauses: "fewer than ~N surviving findings is a valid result -- state it; do not pad" and "precision over volume". |

Formatting rules for the generated prompt: plain ASCII, no emojis, ASCII hyphens; UPPERCASE
section headers; no hard length cap but every line must earn its place -- a mature prompt for a
multi-surface design review typically lands at 2500-4500 words. Do not reference this skill, the
composing session, or any compose-time artifact from inside the prompt: the prompt must stand
alone in a session where none of them exist.

## Best-Practice Checklist (BP1-BP14)

The bar the prompt is written to and verified against. The verification gate's frame challenger
rates the draft against every row.

| ID | Property | Test |
|---|---|---|
| BP1 | Zero unresolved ambiguity | A cold reader can execute every instruction without guessing. Every term is defined; every judgment call is explicitly assigned (executor judgment vs pinned rule); no two instructions conflict. |
| BP2 | Facts, not verdicts | No observation is pre-classified as a defect; candidate lists are framed for adjudication; severity is never pre-assigned. |
| BP3 | Anti-sycophancy / anti-padding | Contains both: "a run that merely confirms the candidates has failed" and "fewer than ~N findings is a valid result -- do not pad". |
| BP4 | Trust-nothing re-derivation | Every quoted number/anchor is marked re-derive-from-repo, with a stale-anchor escape hatch (meta.stale_anchors). |
| BP5 | Escape hatches everywhere | Every anticipated failure (creds down, cache-gen failure, non-resolving anchor, unrelated gate failure) has a named degraded path; the executor never improvises or aborts. |
| BP6 | Pinned output contract | Enums inline, counting invariant stated, systems-of-record referenced not re-counted, deliverable paths exact. |
| BP7 | Bounded effort | Sampling caps ("do NOT exceed"), report word cap, no unbounded sweeps. |
| BP8 | Counterfactual tests as operations | Differential/anti-vacuity checks are spelled out as executable questions ("would this pass if the feature code were deleted?"), not vibes. |
| BP9 | Dedup before filing | Ownership surfaces named; negative-search recording required; hit -> sufficiency or rejection, never rediscovery. |
| BP10 | Severity after judgment | Defect-class severity definitions; compensating controls must PROPERTY-MATCH (exercise the same property AND fail if the defect were real, with the counterfactual applied to the control); a control that cannot catch the break neither lowers severity nor justifies dismissal. |
| BP11 | Deliberate-constraint immunity | Known frozen/decided constraints are listed as do-not-flag, each with its decision id. |
| BP12 | Disambiguation traps named | Every two-things-one-name hazard found at recon is spelled out before it can misdirect. |
| BP13 | Cognition allocation | No instruction makes the executor rediscover something the composer could have handed over; no handed-over item pre-empts executor judgment. |
| BP14 | Terminal-state mechanics | Branch/commit/PR/end-turn fully specified; explicitly no polling, no merging, no self-approval. |

## Recon Dossier (compose-time discovery)

Before drafting, assemble a dossier. Every entry that will enter the GROUNDING MAP must be
verified by reading the file in THIS session -- never from memory, CLAUDE.md, or prior-session
recall. Re-resolve every file:line anchor immediately before drafting; anchors rot.

Dossier contents:

1. **Surface inventory** -- in-scope files/dirs with one-line roles; built vs designed-unbuilt.
2. **Observed facts** -- neutral phrasing, each with its verified anchor. Neutral means: "the
   registry entries list is empty", never "the registry is unused" (verdict) or "the registry is
   dead" (adjective smuggling a verdict).
3. **Candidate list** -- possible gaps/weaknesses, each phrased as a hypothesis to adjudicate.
4. **Vocabulary** -- terms, tiers, and enums the prompt must define.
5. **Disambiguation traps** -- discovered two-things-one-name hazards and plausible wrong targets.
6. **Dedup pointers** -- roadmap items / decisions / open recommendations that already own nearby
   territory, plus the deliberate-constraints do-not-flag list (with decision ids). Extract these
   with targeted projections, never full-file reads of the large sources: a `bin/venv-python -c`
   `yaml.safe_load` projection over `docs/ROADMAP-PLATFORM.yaml` (`candidate_decisions[]` +
   `tier_items[]`), `rg` over `^## Decision` headers in `docs/DECISIONS.md`, and `rg` over
   `logs/.recommendations-log.jsonl`.
7. **Empirical-pass seeds** -- which artifact classes exist to sample, and sane bounds.
8. **Open questions for the human** -- anything recon could not settle, for the scope gate.

Breadth-first recon may fan out `Explore` subagents (this harness's read-only search agent type;
substitute any read-only search subagent if unavailable), but every anchor and fact a subagent
returns must be re-verified by the composing agent before it enters the dossier -- subagent
returns are leads, not evidence.

## Output Contract Skeleton

Every generated prompt pins this contract, instantiated for the topic (rename the finding-id
prefix to a topic-appropriate one; add/remove optional blocks; pin every enum inline).
Deliverable paths: `audits/{slug}-{base-short-sha}.yaml` (repo-root `audits/`) plus a companion
report `audits/{slug}-{base-short-sha}.md` -- prose, <= ~1500 words, the executive layer a human
reads first. `{slug}` is everywhere the same value: the audit topic slug from the
`AUDIT-{slug}.md` filename.

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <executor model's self-reported name, free text>,
         methodology_version: 1, scope_surfaces: [<surfaces>],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: <pinned per-question enum>, basis: [<finding ids>], prose: ""}
    # one entry per question. Two pinned shape variants:
    # - the industry-rating question (if present) ADDS
    #   external_checklist: [{property, rating: met|partial|missed, evidence}]
    #   (partial requires an argued property-matched compensating control in evidence);
    #   this field is the SOLE source the maturity top tier reads.
    # - the final questions-not-asked entry uses INSTEAD of the verdict shape:
    #   {q: Qn, answers: [{question, answer, basis: [<finding ids>]}]}
  per_surface_assessment:
    - {surface: <name>, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface, dimension: VD1..VDn, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  # OPTIONAL: present iff a question demands a per-surface actionable verdict from a
  # pinned option set (e.g. script|agent|hybrid). Name the block after that question's
  # subject and pin the verdict enum; that question's prose entry points here.
  <decision_block_name>:
    <surface>: {verdict: <pinned enum>, mechanism: "", what_changes: "", cost: "",
                rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  findings:
    - {id: <PREFIX>-01, surface: <surface|shared>, question: Q1..Qn, dimension: VD1..VDn,
       title, evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [finding or roadmap ids],
                    note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match,
       decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>,
            maturity_<surface>: <value> ...}
```

Invariants the prompt states verbatim, adapted:

- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings)
  = novel + planned_insufficient + planned_unbuilt`; fully-covered candidates live in
  `rejected_candidates`, NOT findings; `rubric_ratings` / `question_answers` / the decision block
  are systems-of-record referenced FROM findings, never re-counted; `top_improvements` and
  `highest_leverage_change` MUST be finding ids.
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal: name the property the control exercises, cite where it operates (mechanism or
  file:line), and state why the control would FAIL if the defect were real.
- CONFIRMED requires the behavior traced to file:line or an observed sampled artifact; anything
  less is HYPOTHESIS.

Severity boilerplate (adapt the defect classes to the topic; keep the structure):

- critical = the audited system can produce a wrong-but-trusted outcome, or an irreversible act
  proceeds on an unsound verdict.
- high = a weakness that materially reduces the guarantee AND whose compensating controls the
  executor judged insufficient.
- medium = redundancy/ambiguity/inconsistency with a clear fix. low = clarity/wording.

Maturity boilerplate: compute LAST, per surface, evaluated top-down with first match winning.
Default scale -- the generated prompt may rename levels or adjust thresholds for the topic, but
must pin exact numeric thresholds; never leave the scale as an example:

- frontier = 0 open critical or high findings AND every property in the industry-rating
  question's `external_checklist` field (see the skeleton's question_answers variants) rated
  met or partial -- never missed. If the prompt has no such question, the top tier gates on
  finding counts alone.
- strong = 0 critical AND <= 1 high. solid = <= 1 critical. nascent = otherwise. (The
  high-count asymmetry below strong is deliberate in the default -- criticals dominate;
  tighten it if the topic warrants.)

Add the explicit note that the top rating remains reachable if the executor argued a
property-matched compensating control -- the prompt's framing must not foreclose it.

## Commit / PR Mechanics Boilerplate (for the generated prompt)

The generated prompt instructs the executor, concretely:

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`; this
   base IS the audited tree; use the sha in the deliverable filenames, branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/{slug}-<sha> origin/main` so the PR diff is only the two deliverable
   files. This is a deliberate, documented exception to the AGENTS.md `claude/*` session-branch
   rule: the executor session needs a clean two-file diff off the audited base. The CI
   signal-green comment wake fires only on `claude/*` PRs -- irrelevant here, because the
   executor ends its turn without merging; the human disposes of the PR.
3. Note that repo-wide validation is advisory outside CI in this repo: a clean YAML parse of the
   two deliverables is the real pre-push gate; an unrelated `validate --pre` failure is recorded
   in `meta.contract_notes`, never fixed (write boundary).
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing
   is unavailable. `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title
   `audit: <audit topic in plain words> (<scope surfaces>)`, body = the summary block in a
   yaml fence + a 2-3 sentence
   lede). Then END THE TURN -- do not poll, do not merge, do not subscribe.

## Zero-Context Verification Gate (MANDATORY)

The draft prompt is verified by fresh-context subagents before it ships. Rationale: the composer
cannot see its own ambiguity -- context it holds silently fills every gap in the text. Only a
reader with zero shared context experiences the prompt as the executor model will.

Dispatch THREE perspectives in parallel via the `Agent` tool, `subagent_type:
"general-purpose"`, each prompt self-contained. Do NOT tell any verifier what the composer was
worried about, which sections were hardest, or what a previous round found -- that biases the
read. The verifier receives the artifact path, its perspective, and the output shape. Nothing
else.

**V1 -- Cold executor (ambiguity).** Reads ONLY the prompt file; forbidden from reading any other
file, running any command, or browsing the repo. Task: "You are the agent this prompt will be
handed to, except you may not act -- only read. List every point where you would have to guess:
undefined terms, unpinned enums, conflicting instructions, unspecified paths, judgment calls with
no assigned owner, failure modes with no named degraded path, and any instruction you could not
execute without asking a human. You have no one to ask." Output: numbered ambiguities with the
exact quoted prompt text, each tagged blocking|degrading|cosmetic; Verdict PROCEED|REVISE
(REVISE iff any blocking, or 3+ degrading).

**V2 -- Fact auditor (grounding).** Full repo read access. Task: "Independently verify every
factual claim in this prompt against the repository at the current branch HEAD (the tree the
prompt was drafted from; note in your output any cited file where origin/main has since
diverged): every file path exists; every
file:line anchor resolves to what the prompt says is there; every quoted identifier (decision,
roadmap item, contract, schema field, enum) exists as cited; every command in the setup and
mechanics sections is runnable as written (run the read-only ones; static-check the rest). A
single wrong fact poisons an expensive session -- treat any mismatch as a finding." Output:
numbered mismatches with prompt-text vs repo-truth, each tagged wrong|stale|unverifiable;
Verdict PROCEED|REVISE (REVISE iff ANY finding: wrong and stale claims are corrected;
unverifiable claims are re-anchored or stripped by the composer before the next round -- a
grounding claim the fact auditor cannot verify does not ship).

**V3 -- Frame and best-practice challenger.** Full repo read access; also reads this skill's
BP1-BP14 table (pass the checklist text inline in the dispatch so the verifier does not need the
skill). Task: "Rate the prompt against each BP row (met|partial|missed, one line of evidence).
Then challenge the frame itself: is the audit target the right target; is any question missing
that the requester will wish had been asked; does the scope leak into surfaces the guardrails
forbid touching; is the output schema internally consistent (counting invariant vs schema fields;
every enum referenced is pinned; every meta flag written has a reader); do the candidates as a
set bias the executor toward a predetermined conclusion?" Output: BP scorecard + numbered frame
findings with severity; Verdict PROCEED|REVISE (REVISE iff any BP missed or any high-severity
frame finding).

Each dispatch must also: identify the prompt file by absolute path, forbid file edits, require
the structured output shape above verbatim including the final `Verdict:` line, and cap the
response (~900 words).

**Verdict handling.** The gate passes only when ALL THREE return PROCEED in the SAME round.
On any REVISE: synthesize (consensus findings first), revise the prompt, commit the revision
(`audit({slug}): address prompt-verification findings round N`), and re-dispatch all three fresh
-- a revision that fixes X can introduce Y, and only a fresh cold read catches it. A verifier
that errors or omits the `Verdict:` line has NOT completed -- re-dispatch it; never proceed past
an incomplete gate. Convergence rule: after 3 REVISE rounds, escalate to the human with the
unresolved findings and options (accept-with-deferral / re-scope / abandon).

Unanimous-PROCEED quality check: PROCEED is PROCEED -- the gate passes -- but before accepting a
round-1 unanimous pass, the composer reads each verifier's output; any verifier that returned
zero findings AND fewer than ~10 lines of substantive output (findings list or scorecard) was
dispatched too generically -- re-dispatch that verifier ONCE with a sharpened perspective. One
re-dispatch maximum; its verdict is final.

**Gate anti-patterns.** Single verifier (misses orthogonal defects by definition). Telling a
verifier what to find (confirmation bias). Reusing a verifier's context across rounds (it now
shares your context; it is no longer cold). Letting V1 read the repo (repo access lets it resolve
ambiguity the executor would pay to resolve -- V1's blindness IS the test). Accepting a unanimous
round-1 PROCEED without the quality check above.

## Composer Anti-Patterns

- **Verdict smuggling**: adjectives that pre-classify ("dead registry", "vacuous check",
  "missing gate") anywhere in TASK, SCOPE, or the GROUNDING MAP. State the fact; let the
  executor convict.
- **Memory-sourced facts**: any grounding claim not re-verified on disk this session.
- **Unbounded instructions**: "sample recent plans" without a cap; "review the history" without
  a range.
- **Orphan enums / write-only flags**: an output field whose enum is never pinned, or a meta
  flag no downstream consumer reads.
- **Prompt-time coupling**: the prompt referencing this skill, the composing session, the recon
  dossier, or any file that will not exist in the executor's fresh session.
- **Scope creep via mechanics**: mechanics that have the executor edit anything beyond its
  deliverables ("fix validate if it fails" -- never).
- **Self-verification**: skipping the gate because the draft "looks complete". The composer is
  structurally the wrong judge of its own ambiguity.
