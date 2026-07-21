---
name: decision-scout
description: "Use when: scope a proposed plan against active decisions, surface decision-contradiction flags before plan commitment, find related decisions a plan should cite. Mandatory pre-confirmation gate in /plan, runs in a fresh-context subagent so the full DECISIONS.md cost (large -- near its Decision 134 size ceiling) does not bloat the planning agent."
---

## Intent

Given a proposed plan approach, surface every active decision that is relevant -- as context to cite, as a contradiction to resolve, or as a related-work pointer. The full `docs/DECISIONS.md` (large -- near its Decision 134 size ceiling) only enters this subagent's context, never the parent planning agent's; only the structured summary returns.

This is a BLOCKING gate before `/plan` Step 6 "Present Findings and Confirm". A superficial scan that misses a contradiction is worse than not running -- the parent agent and human both trust this output to be exhaustive.

### Why a subagent and not inline grep

The naive alternative is to grep `docs/DECISIONS.md` from the planning agent for keywords from the proposed approach. That misses decisions that contradict implicitly (different vocabulary, similar concept) and forces the planning agent to load enough of DECISIONS.md to make a judgement -- the exact large-file cost (near its Decision 134 size ceiling) this gate exists to avoid.

### Lambda migration contract

When `docs/DECISIONS.md` is replaced by a Lambda-backed tool query (in-flight per project roadmap), the only change is Phase 1 step 1: swap `Read docs/DECISIONS.md` for a tool call. The output contract is unchanged. Callers do not need to update their invocation. This skill is the migration's stable interface.

---

## Steps

### Phase 1: Load Inputs (MANDATORY)

1. Read the **entire** `docs/DECISIONS.md` -- do not Read with offset/limit. A decision near the bottom of the file is just as likely to contradict the proposed approach as one near the top. (Post-Lambda-migration: call the decisions tool with no filter; pagination is acceptable only if the tool guarantees ordering by recency-of-relevance.) Before triage, run `rg -c "^## Decision " docs/DECISIONS.md` and record the count M -- this is the LIVE-FILE header count, NOT the max decision number (which reflects archive entries and numbering gaps) and NOT inclusive of `docs/DECISIONS_ARCHIVE.md`, per Decision 105.

2. Read the caller's input brief, which is mandated to include:
   - **Intent** (1-2 sentences from `/plan` Step 3 clarification)
   - **Proposed approach** (paragraph from `/plan` Step 3-5 synthesis)
   - **Scope file list** (from `/plan` Step 4 Identify Affected Files)
   - **Verification Tier** (V1 / V2 / V3, from `/plan` Step 5)
   - **Explicitly cited decision IDs** (any decisions the human or planning agent has already referenced)

If any of these inputs are absent in the prompt, return immediately with `Verdict: BLOCK` and a one-line note: "Caller did not provide [missing input]. Re-dispatch after [step] completes."

### Phase 2: Triage Each Decision

3. For each decision in `docs/DECISIONS.md`, classify against the proposed approach into one of four buckets:
   - **CITE** -- the decision directly governs the approach and the plan MUST reference it (e.g., a decision constraining how to write to Athena, when the plan writes to Athena).
   - **CONTRADICT** -- the proposed approach violates an active decision (e.g., decision says "no `python -c` in acceptance commands"; proposed approach includes a `python -c` one-liner).
   - **RELATED** -- the decision is in the neighbourhood but does not directly govern (e.g., a decision about session telemetry when the plan touches a different telemetry path). Useful context to mention but not mandatory to cite.
   - **IRRELEVANT** -- discard.

4. For each CONTRADICT, attach a severity:
   - **BLOCK** -- the proposed approach cannot proceed without violating the decision. Plan must pivot.
   - **WARN** -- the proposed approach partially conflicts; a small refactor or explicit deferral note in the plan can resolve.
   - **NOTE** -- the proposed approach edges close to the decision's domain but does not violate it; surface for the planning agent's judgement.

5. **Managed-service-native check (Decision 100 / Decision 75):** During triage, flag CONTRADICT WARN when a
   plan proposes to vendor client tooling or custom scripts to replicate a capability the managed service
   already exposes natively (examples: pg_dump/pg_restore instead of Neon branching; manual S3 copy instead
   of S3 replication; custom schema-copy instead of RDS snapshot). This check fires even when the mechanism
   was previously recorded as a "human decision" -- a decision record does not exempt a mechanism from the
   native-primitive principle. Cross-reference Decision 100 (which extends Decision 75 to ALL managed services,
   not only AWS-native primitives).

6. **Status filter.** Only flag CONTRADICT or CITE for decisions whose status is active (not reversed, not superseded, not deferred). If a decision is reversed/superseded, demote to RELATED with a one-line note: "Decision N (REVERSED by Decision M) — flagged for awareness only."

### Phase 3: Structured Output

7. Return exactly this output. Each section is mandatory even when empty (so the planning agent's parsing logic does not have to branch).

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

### Verdict
NO_FLAGS | FLAGS_FOUND | BLOCK

(NO_FLAGS = no CONTRADICT entries; CITE-only is still NO_FLAGS.
FLAGS_FOUND = at least one CONTRADICT at WARN or NOTE severity.
BLOCK = at least one CONTRADICT at BLOCK severity; planning agent must pivot before confirming.)

Decisions triaged: N of M
```

8. Cap total response at ~1,200 words. The planning agent reads this verbatim and surfaces it to the human; bloat dilutes the signal.

---

## Quality Gate (self-check before output)

Verify before returning:
- [ ] You read the full DECISIONS.md (not a truncated section)
- [ ] Every CITE and CONTRADICT entry names a decision number that actually exists in the file
- [ ] Every CONTRADICT entry has both a clause-level citation AND a severity
- [ ] The Verdict line is one of the three exact strings (no variations)
- [ ] The "Decisions triaged: N of M" line is present and N equals M (the rg -c count from Phase 1)
- [ ] Total length under 1,200 words

If any checkbox is false, fix before returning. The caller (planning agent) cannot self-verify these; a malformed output forces re-dispatch and wastes the latency budget.

---

## Anti-patterns

- **Keyword-only matching.** "The proposed approach mentions 'Lambda', so let me list every Lambda decision." -> noise. Match on whether the decision's *clause* governs the proposed approach's *action*, not on topic adjacency.
- **Defensive over-citation.** Adding every tangentially-related decision to CITE bloats the planning agent's downstream summary and trains the human to skim past flags. Be ruthless: CITE only when omission would meaningfully harm the plan.
- **Hedged contradictions.** "This *might* contradict Decision N." -> either it does or it doesn't. If you cannot determine, mark NOTE severity and explain what's uncertain. Hedge in the explanation, not in the classification.
- **Editing files.** This skill is read-only. Do not modify `docs/DECISIONS.md` or any other file under any circumstance, even to "fix obvious typos in a decision title". File a recommendation if you find something genuinely wrong.
- **Citing reversed decisions as governing.** A REVERSED decision is historical context only. Demote to RELATED with the reversal note; never CITE or CONTRADICT against it.
