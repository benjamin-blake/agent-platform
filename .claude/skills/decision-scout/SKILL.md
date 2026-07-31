---
name: decision-scout
description: "Use when: scope a proposed plan against active decisions, surface decision-contradiction flags before plan commitment, find related decisions a plan should cite. Mandatory pre-confirmation gate in /plan; runs in a fresh-context subagent so the bounded triage load stays off the planning agent."
---

## Intent

Given a proposed plan approach, surface every active decision that is relevant -- as context to cite, as a literal contradiction to resolve, as a related-work pointer, or as a spirit-alignment concern (the SPIRIT overlay, Phase 2). Triage is BOUNDED (Phase 1 step 1): the committed `docs/decisions-index.json` projection plus targeted reads of only shortlisted entries -- the corpus never loads wholesale into this subagent's context, let alone the parent's; only the structured summary returns.

This is a BLOCKING gate before `/plan` Step 6 "Present Findings and Confirm". A superficial scan that misses a contradiction is worse than not running -- the parent agent and human both trust this output to be exhaustive.

### Why a subagent, and why bounded

A naive inline grep from the planning agent misses implicit contradictions (different vocabulary, same concept) and would force it to load the corpus to judge -- the exact cost this gate avoids. Bounded retrieval keeps that judgement in the subagent without the whole-corpus cost: triage every live title + `triage_excerpt` from the index, then read ONLY shortlisted entries as targeted source-file sections.

### Lambda / portal migration contract (T1.5 c1 owns this; rec-2774)

The index-plus-targeted-reads mechanism is the INTERIM arrangement, not the T1.5 portal cutover (Decision 134 clause 5). T1.5 c1 owns swapping Phase 1 step 1's two reads for a queried tool call; the output contract, buckets, severity taxonomy, and quality gates below are the stable interface across that swap.

---

## Steps

### Phase 1: Load Inputs (MANDATORY)

1. **Triage source.** Read `docs/decisions-index.json` -- committed, generated solely from `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` by `scripts.decisions_index`; used instead of the gitignored `ops_decisions` cache because CI PR roles lack reader access there and this gate stays credential-free and hermetic (Decision 105's R1-R3 guard relies on the same file-header hermeticity). Derive **M** = count of `live: true` entries -- the live-file header count, excluding the archive and distinct from the max decision number (numbering gaps). Each live entry's `title`, `triage_excerpt` (<=320 chars, Intent/Problem/Context/Decision fallback order; `triage_excerpt_source` names which; a small terse-historical band carries none), and `category_tags` (deterministic artifact/process tags, e.g. `lambda`/`terraform`/`iam`/`secrets`/`deploy`/`egress`) is the Phase 2 signal -- never a whole-file load here.

2. Read the caller's input brief, which is mandated to include:
   - **Intent** (1-2 sentences from `/plan` Step 3 clarification)
   - **Proposed approach** (paragraph from `/plan` Step 3-5 synthesis)
   - **Scope file list** (from `/plan` Step 4 Identify Affected Files)
   - **Verification Tier** (V1 / V2 / V3, from `/plan` Step 5)
   - **Explicitly cited decision IDs** (any decisions the human or planning agent has already referenced)

If any of these inputs are absent in the prompt, return immediately with `Verdict: BLOCK` and a one-line note: "Caller did not provide [missing input]. Re-dispatch after [step] completes."

### Phase 2: Triage Each Decision

3. **Shortlist.** FIRST, mechanically: derive the approach's own tag set (`lambda` = creates/touches
   a Lambda; `terraform`/`iam` = touches a terraform/ or IAM surface; `secrets` = reads/stores a
   credential or authenticates externally; `deploy` = ships code/infra by any channel; `egress` =
   reads Neon/warehouse; `decisions-corpus`/`prose-docs` = edits governance docs) and shortlist
   EVERY live entry whose `category_tags` intersects it -- a mechanical set-intersection, never
   per-entry judgment (many decisions govern by ARTIFACT TYPE, not topic keyword). THEN classify
   every REMAINING entry PROVISIONALLY via title + `triage_excerpt`:
   - **CITE** -- governs the approach; the plan MUST reference it.
   - **CONTRADICT** -- the approach violates an active decision.
   - **RELATED** -- in the neighbourhood, not mandatory.
   - **IRRELEVANT** -- discard. Tag-matched + non-IRRELEVANT + any SPIRIT candidate (step 8) =
     the final SHORTLIST.

4. **Targeted read.** For every shortlisted entry, locate its heading (`rg -n "^## Decision N:" docs/DECISIONS.md`) and Read with offset/limit spanning just that heading through the next -- one section, never the source file wholesale. Confirm or refine the provisional classification against the full text; a shortlisted entry's SPIRIT quote (step 8) may be any verbatim sentence from that section, not only the excerpt.

5. For each CONTRADICT, attach a severity:
   - **BLOCK** -- the approach cannot proceed without violating the decision. Plan must pivot.
   - **WARN** -- partial conflict; a small refactor or explicit deferral note can resolve.
   - **NOTE** -- edges close to the decision's domain but does not violate it; surface for judgement.

6. **Managed-service-native check (Decision 100 / Decision 75):** flag CONTRADICT WARN when a plan
   vendors client tooling or custom scripts to replicate a capability the managed service already
   exposes natively (pg_dump/pg_restore instead of Neon branching; manual S3 copy instead of S3
   replication; custom schema-copy instead of RDS snapshot). Fires even if previously recorded as a
   "human decision" -- that does not exempt it. Decision 100 extends Decision 75 to ALL managed services.

7. **Status filter.** Only flag CONTRADICT or CITE for decisions whose status is active (not reversed/superseded/deferred). If reversed/superseded, demote to RELATED with a one-line note: "Decision N (REVERSED by Decision M) — flagged for awareness only."

8. **Spirit-alignment overlay (SPIRIT bucket).** SEPARATELY from the literal CONTRADICT triage (steps
   3-5), flag an approach that violates the *spirit* of an active decision without contradicting any
   single clause. Gated hard against noise -- defensive-over-citation applies with FULL force here.
   Emit a SPIRIT flag ONLY when ALL FOUR hold:
   - (i) **No literal CONTRADICT on the same decision.** A decision appears in at most one of the two lanes; a clause that only describes the ruling's OWN scope (e.g. "no retro-enforcement") is not a standing forward prohibition -- route it to SPIRIT.
   - (ii) **Verbatim-quotable violation.** Quote, VERBATIM, the text the approach works against: `**Intent:**`, a specific Problem/Rationale sentence, OR -- widened for bounded retrieval -- the `**Decision:**` clause (a REQUIRED marker per `docs/contracts/decision-entry.yaml`, the most reliable fallback). Ungrounded means no flag. A few terse historical live entries carry no quotable marker at all; unshortlisted, their `triage_excerpt` is empty and no SPIRIT flag can fire from the index alone -- an accepted residual, not a bug.
   - (iii) **WARN or NOTE severity only.** Never BLOCK -- that stays reserved for literal contradiction (step 5).
   - (iv) **Capped at 3.** Keep the 3 highest-severity (WARN over NOTE) if more qualify; the whole report still fits the ~1,200-word budget (step 10).

### Phase 3: Structured Output

9. Return exactly this output. Each section is mandatory even when empty (so the planning agent's parsing logic does not have to branch).

```
## Decision Scout Report

### Decisions to Cite (CITE)
- **Decision N**: [title] — [one-line reason: which clause governs which part of the approach]

(or "None" if empty)

### Contradiction Flags (CONTRADICT)
- **Decision N** [BLOCK | WARN | NOTE]: [title]
  - Contradiction: [specific clause vs specific element of the proposed approach]
  - Suggested resolution: [pivot to X | add explicit deferral note citing Decision N | clarify with human before proceeding]

(or "None" if empty)

### Related Decisions (RELATED)
- **Decision N**: [title] — [one-line: in the neighbourhood, mention if discussed]

(or "None" if empty)

### Spirit-Alignment Flags (SPIRIT)
- **Decision N** [WARN | NOTE]: [title]
  - Violated intent (verbatim): "[exact quote of the entry's **Intent:**/**Problem:**/**Decision:** marker, or a specific Rationale sentence]"
  - Divergence: [the specific element of the proposed approach that works against the quoted intent]
  - Suggested resolution: [align to X | add explicit deferral note citing Decision N | clarify with human]

(or "None" if empty)

### Verdict
NO_FLAGS | FLAGS_FOUND | BLOCK

(NO_FLAGS = no CONTRADICT entries AND no SPIRIT flags; CITE-only is still NO_FLAGS.
FLAGS_FOUND = at least one CONTRADICT at WARN or NOTE severity, OR at least one SPIRIT flag (SPIRIT is
always WARN/NOTE, so a SPIRIT flag alone yields FLAGS_FOUND, never BLOCK).
BLOCK = at least one CONTRADICT at BLOCK severity; planning agent must pivot before confirming.)

Decisions triaged: N of M
```

10. Cap total response at ~1,200 words. The planning agent reads this verbatim and surfaces it to the human; bloat dilutes the signal.

---

## Quality Gate (self-check before output)

Verify before returning:
- [ ] You applied the mechanical tag shortlist (step 3) before judgment, and read ONLY shortlisted entries as targeted sections -- never a whole-file load
- [ ] Every CITE and CONTRADICT entry names a decision number that exists in the index
- [ ] Every CONTRADICT entry has both a clause-level citation AND a severity
- [ ] The Verdict line is one of the three exact strings (no variations)
- [ ] "Decisions triaged: N of M" is present and N equals M (the live:true count from Phase 1 step 1)
- [ ] Total length under 1,200 words
- [ ] Every SPIRIT flag carries a verbatim quote per gate (ii) (Intent, Problem/Rationale, or Decision-clause -- no paraphrase)
- [ ] SPIRIT flags number <= 3, and no decision appears in both SPIRIT and CONTRADICT

If any checkbox is false, fix before returning. The caller (planning agent) cannot self-verify these; a malformed output forces re-dispatch and wastes the latency budget.

---

## Anti-patterns

- **Keyword-only CITE.** "The approach mentions 'Lambda', cite every Lambda decision." -> noise. Shortlist broadly (step 3), but CITE only when the decision's *clause* governs the approach's *action*.
- **Defensive over-citation.** Bloats the downstream summary and trains the human to skim past flags. Be ruthless: CITE only when omission would meaningfully harm the plan.
- **Hedged contradictions.** "This *might* contradict Decision N." -> either it does or it doesn't. If undetermined, mark NOTE and explain what's uncertain. Hedge in the explanation, not the classification.
- **Editing files.** Read-only. Never modify `docs/DECISIONS.md` or any other file, even to "fix a typo". File a recommendation if something is genuinely wrong.
- **Citing reversed decisions as governing.** A REVERSED decision is historical context only. Demote to RELATED with the reversal note; never CITE or CONTRADICT against it.
- **SPIRIT over-citation.** The highest-noise lane -- an unquotable "this feels misaligned" is not a flag. Three well-grounded flags beat ten hedged ones.
