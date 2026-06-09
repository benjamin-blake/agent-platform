# AUDIT PROMPT - Comprehensive audit of docs/ROADMAP-PLATFORM.yaml

> Stand-alone prompt for a fresh agent session. Hand this entire file to the
> auditor as their starting context. The auditor has no view of any prior chat.

---

## 1. Mission

Perform a comprehensive, REPORT-ONLY audit of `docs/ROADMAP-PLATFORM.yaml` -
the canonical platform roadmap. The audit answers one question:

> Is this roadmap a trustworthy, complete, and internally consistent control
> surface for autonomous agents to plan and sequence platform work from?

You are NOT fixing the roadmap, NOT editing it, NOT filing recommendations.
You are producing exactly one primary artefact:

- `docs/audit-reports/PLATFORM-ROADMAP-AUDIT-{YYYY-MM-DD}.yaml` - a
  machine-parseable findings report conforming to the Section 8 schema,
  committed and pushed on your session branch.

Plus intermediate subagent outputs under `docs/audit-reports/wave-1-outputs/`
(Section 7). Narrative summary is your final chat reply, not a stored
artefact (per AGENTS.md agent-first rules: no human-readable companion doc).

Judgment boundaries: you judge the roadmap's quality freely - that is the
audit's purpose. You do NOT relitigate ratified decisions, pivot-era design
commitments, or the roadmap's chosen architecture (tiers, gates, CD
governance). Where roadmap content contradicts a ratified decision or the
repo's actual state, that is a finding; where you merely prefer a different
design, that is at most an `open_questions_for_user` entry, not a finding.

All line counts and item counts quoted in this prompt are authoring-time
hints (2026-06-09). Re-measure everything; do not trust the numbers here.

---

## 2. Operating context (hard rules - do not violate)

Read `CLAUDE.md` / `AGENTS.md` at repo root first - everything below is a
summary, the originals are authoritative.

- **Branching**: never edit on `main`. On Claude Code on the web you are
  already on a harness-assigned `claude/...` session branch - confirm with
  `git branch --show-current`. Do NOT create an `agent/` branch on web.
  (Local fallback: `git checkout main && git pull && git checkout -b
  agent/platform-roadmap-audit`.)
- **No emojis** anywhere. Plain ASCII hyphens (`-`). No em dashes.
- **Python wrapper**: invoke `bin/venv-python`, never `python` / `python3`.
- **Single Portal Invariant**: do NOT write to `logs/.recommendations-log.jsonl`
  or `logs/.decisions-index.jsonl`. Reading them is fine (they are read
  caches and may be stale - see Section 5, D4).
- **No rec filing**: this audit does NOT call `ops_data_portal file_rec`.
  Findings that should become recs are marked `proposed_rec: true` in the
  report; the user converts accepted findings in a follow-up session.
- **Read-only toward the warehouse**: do not run `sync_ops sync`, any drain,
  or any AWS write. `aws sts get-caller-identity --profile agent_platform`
  is permitted if you need to confirm why a read fails.
- **Zero edits to audit targets**: `docs/ROADMAP-PLATFORM.yaml`,
  `docs/ROADMAP-PRODUCT.yaml`, `scripts/platform_roadmap.py`,
  `scripts/validate.py`, `scripts/session_preflight.py` must be untouched.
  At the end, `git status` may show ONLY new files under
  `docs/audit-reports/`.
- **STRATEGIC plans are suspended** (CD.17). This audit is REPORT-ONLY and
  files no plan of any type.
- **No PR** unless the user explicitly asks. Commit and push the report on
  the session branch, then stop.
- Running read-only commands (`rg`, `git log`, `bin/venv-python -m pytest
  tests/<targeted test>`) is allowed and encouraged for evidence gathering.

---

## 3. Mandatory preflight reads (auditor reads these, in full, in order)

Do not delegate these to subagents - you need the full mental model to brief
them and to run Wave 1.5 yourself.

1. `docs/ROADMAP-PLATFORM.yaml` - the audit target. Read ALL of it, in
   slices if needed. Internalise: the ten top-level keys (`document`,
   `north_star`, `cost_projection`, `rebuild_vs_refactor`,
   `foundation_already_shipped`, `candidate_decisions`, `tier_items`,
   `cross_tier_gates`, `open_questions`, `known_gaps`), the
   `document.agent_instructions` block (eligibility semantics, bootstrap
   clauses, gate grammar), and the `gate_helpers` table.
2. `scripts/platform_roadmap.py` (~430 lines) - the Pydantic validator
   (`RoadmapDocument`), `GateRuleParser`, and `PlatformRoadmapState`
   (eligibility / blocked / active-tier computation consumed by preflight).
3. `scripts/validate.py` - ONLY the functions `validate_platform_roadmap`
   and `validate_product_roadmap` (locate with `rg -n "def
   validate_(platform|product)_roadmap" scripts/validate.py`). Note which
   tier each runs in (full presubmit vs `--pre`).
4. AGENTS.md sections "Temporary Operational Constraints" and "Branching" -
   these encode currently-binding constraints (CD.17 STRATEGIC suspension,
   per-Lambda gating per Decision 79) that roadmap content must not
   contradict.
5. `docs/PROJECT_CONTEXT.md` - skim for platform vocabulary only.

Defer to subagents: `docs/DECISIONS.md` (~25k tokens), `docs/SESSION_LOG.md`,
`docs/ROADMAP-PRODUCT.yaml` content, `docs/plans/*`. Do not bulk-read these
yourself.

---

## 4. Step 0 - derive the enforced-vs-unenforced split

The single most common audit failure mode is wasting effort re-checking what
CI already enforces, while missing what it does not. Before dispatching any
subagent, build a two-column table from your reading of
`scripts/platform_roadmap.py` and the two `validate.py` functions:

- **Column A - machine-enforced (do NOT re-audit, just record PASS):**
  expected to include tier_item id uniqueness; `depends_on` resolution to
  known ids or tier shortcuts; dependency cycle detection;
  `candidate_decisions[].gates` ref resolution; gate-rule helper names and
  arity (on `cross_tier_gates[].rule` and `decision_required_before`);
  `TierItem`/`CandidateDecision` field whitelists (`extra="forbid"`);
  status and effort enums on tier_items; `document.version` and
  `document.filed_via` formats; PRODUCT->PLATFORM edge resolution (via
  `scripts/product_roadmap.py::load(product_path, platform_path=...)`).
- **Column B - NOT machine-enforced (the audit surface):** candidates to
  CONFIRM against source, not assume: `completed_at` not required when
  `status == complete`; `tier_items[].related_candidate_decisions` refs
  never resolved against CD ids; CD `state` is a free string (no enum);
  `document.status` free string; `tier_items[].tier` free string (never
  checked against the canonical tier order); id uniqueness NOT checked for
  candidate_decisions / cross_tier_gates / open_questions / known_gaps;
  field paths inside gate rules (e.g. `T0.1.status`) tokenised but never
  resolved; string ARGUMENTS inside helper calls (e.g.
  `tier_complete("T9")`) never resolved; `files_in_scope` paths never
  checked for existence; `RoadmapDocument` has `extra="ignore"` so a
  misspelled TOP-LEVEL key is silently dropped; truthfulness of every
  status field; all prose content.

Record the confirmed table in the report's `verification.enforced_split`
block. Every Column-B row must be covered by at least one dimension check in
Section 5 or explicitly waived with a reason.

---

## 5. Audit dimensions

Each finding is tagged with exactly one dimension. Checks marked (prog) are
programmatic - run them yourself in Wave 0; the rest are judgment checks
owned by the named wave/subagent (Section 7).

### D1 - mechanical integrity beyond the validator (Wave 0, auditor)
- (prog) `bin/venv-python -m scripts.platform_roadmap` exits 0.
- (prog) Duplicate-id scan across CD / gate / OQ / KG id namespaces.
- (prog) Top-level key scan: every top-level YAML key maps to a
  `RoadmapDocument` field (catches `extra="ignore"` silent drops).
- (prog) `status: complete` items missing `completed_at`; non-complete
  items carrying `completed_at`.
- (prog) `related_candidate_decisions` entries that resolve to no CD id.
- (prog) `tier` values outside the canonical order list in
  `platform_roadmap.py::_CANONICAL_TIER_ORDER`.
- (prog) `files_in_scope` paths that do not exist in the repo AND are not
  self-evidently proposed-new (report as candidate findings for D7 review,
  not auto-failures).

### D2 - dependency-graph and gating semantics (Wave 1.5, auditor)
- Deadlock analysis: for every CD with `gates`, can its gated items reach
  `complete` under the documented semantics ("CD must be ratified before
  gated tier_items can be marked complete") given current CD states and the
  per-item `bootstrap_completion_exempt` flags? Enumerate cycles the
  bootstrap exemptions do NOT cover.
- Bootstrap-clause consistency: the prose enumerations in
  `agent_instructions` vs the actual per-item `bootstrap_completion_exempt`
  flags (the flag is declared the single source of truth - diff the two).
- Gate-rule field paths and helper arguments: every `T*.field` path and
  every quoted tier/item argument inside `cross_tier_gates[].rule` and
  `decision_required_before` resolves to a real item/tier/field.
- Trivially-true and never-true gates: gates whose referenced items are all
  already complete (gate is dead) or unreachable (gate can never pass).
- Tier monotonicity: items whose `depends_on` points at a LATER tier than
  their own - legitimate exceptions exist, but each deserves a look.
- `decision_required_before` (START gate) vs `gates` (COMPLETION gate)
  used consistently with the documented distinction.
- WIP sanity: `in_progress` count vs a sole developer; items `in_progress`
  with incomplete dependencies.

### D3 - status truthfulness against the repo (Wave 1, subagent A)
For EVERY item with `status: complete` or `status: in_progress`, and every
`foundation_already_shipped` entry: verdict one of `confirmed` /
`partially_confirmed` / `unsubstantiated` / `contradicted`, with evidence.
Evidence hierarchy (strongest first): exit_criteria adjudicated against the
repo; cited tests exist and pass (run targeted pytest only); files_in_scope
exist with plausible content; corroboration in `docs/SESSION_LOG.md`,
`docs/DECISIONS.md`, or git log. A `complete` item whose exit_criteria
cannot be substantiated is a finding; severity rises if downstream items
depend on it. Also flag the inverse: `not_started` items whose exit
criteria appear ALREADY met (silent completion - stale status).

### D4 - decision-layer alignment (Wave 1, subagent B)
- Diff `candidate_decisions[]` (id, title, state, filed_via) against
  `docs/DECISIONS.md` and the read cache `logs/.decisions-index.jsonl`:
  CDs ratified in the decision record but still `state: pending` in the
  roadmap (or vice versa); CDs whose `filed_via` does not match the record.
- Contradictions between roadmap content and currently-binding constraints
  in AGENTS.md "Temporary Operational Constraints" (e.g. items implying
  STRATEGIC plan flow while CD.17 suspension holds; Lambda items not
  reflecting Decision 79 per-Lambda gating).
- The local decisions cache may be stale: where cache and DECISIONS.md
  disagree, prefer DECISIONS.md, set `confidence: low`, and note it.

### D5 - cross-roadmap coherence (Wave 1, subagent E)
Edge RESOLUTION is CI-enforced; audit the semantics instead:
- Inventory `PLATFORM:` references in `docs/ROADMAP-PRODUCT.yaml`
  (`rg -o "PLATFORM:[A-Za-z0-9._-]+" docs/ROADMAP-PRODUCT.yaml | sort -u`).
- Platform items that product depends on but that are `reserved`, gated by
  a pending CD with no bootstrap exemption, or sequenced behind long
  dependency chains - i.e. resolvable but practically blocked.
- Sibling framing holds: platform header/prose claims about the product
  roadmap (filenames, source-of-truth statements) match current repo state.
- Platform items whose intent/notes claim a product consumer that no
  longer references them (reverse-direction drift).

### D6 - consumer-contract fitness (Wave 0 + Wave 1.5, auditor)
- (prog) Run the state computation preflight uses and sanity-check it:
  `bin/venv-python -c "import json; from pathlib import Path;
  from scripts.platform_roadmap import compute_state_dict;
  print(json.dumps(compute_state_dict(Path('docs/ROADMAP-PLATFORM.yaml')),
  indent=2))"`
  - no `error` key; `next_eligible` / `blocked` / `in_progress` /
  `strategic_pending` / `active_tier` all plausible against your reading.
- Items in `next_eligible` that a planning session should NOT actually
  start (e.g. blocked-on-pending-CD via `decision_required_before`) - the
  gap between computed eligibility and documented semantics is a finding.
- `agent_instructions` claims vs implemented behavior in
  `platform_roadmap.py` / `session_preflight.py` (e.g. claims about what
  the schema rejects, how reserved items are treated).

### D7 - per-item content quality (Wave 1, subagent D)
For `not_started` and `reserved` items (the forward book of work):
- `intent` states WHY, not just what.
- `exit_criteria` are adjudicable: a fresh agent could mark each true/false
  against the repo without asking the user. Flag vague criteria ("works
  well", "is robust") - prioritise items that are currently eligible or
  one dependency away.
- `files_in_scope` plausible for the stated scope.
- `effort` calibration: XS/S items whose scope text implies multi-file
  builds; L/XL items not marked `strategic: true` (and the inverse).
- Naming/id conventions consistent with the rest of the file.

### D8 - coverage and gap analysis (Wave 1, subagent C)
- Sweep operational surfaces and check each has roadmap representation
  (tier_item, foundation entry, or known_gap): `terraform/` (incl.
  `personal/`, `github/`), `src/lambdas/*/manifest.yaml`, `scripts/`,
  `.github/workflows/`, `.claude/` (skills, commands, hooks),
  `docs/contracts/`. Unrepresented ACTIVE surfaces are candidate findings;
  unrepresented dead code is at most a note.
- `docs/plans/PLAN-*.md` and `docs/handoffs/*`: in-flight or completed work
  with no roadmap reflection (and roadmap items claiming plans that do not
  exist).
- `open_questions[]` already answered by later decisions/work but still
  open; `known_gaps[]` already closed but still listed.

### D9 - strategic coherence and sequencing sanity (Wave 2, auditor)
- Every `north_star` principle traces to at least one tier_item or an
  explicit known_gap; items that trace to NO principle are scope-drift
  candidates.
- `cost_projection` and `rebuild_vs_refactor` still describe current
  reality (compare against terraform state on disk, not memory).
- Tier balance and critical path: does the dependency graph actually lead
  somewhere (an end-state the north_star names), or do chains dead-end?
- This dimension produces FEW, high-judgment findings. Prefer one
  well-evidenced structural observation over ten vibes.

### D10 - document hygiene and self-description drift (Wave 0 + 2, auditor)
- Header comment: consumer list, source-of-truth claims, sibling filenames
  accurate.
- Stale self-references: line counts, item counts, retired-doc references
  beyond permitted retirement metadata, references to superseded
  mechanisms.
- `document.status` / `document.version` / `filed_via` consistent with the
  document's actual lifecycle stage.

---

## 6. Roadmap content rubric (completeness benchmark)

Independent of findings, score the roadmap against this rubric in the
report's `summary.rubric_coverage`. This is what a comprehensive platform
roadmap contains; for each element record `present` / `partial` / `absent`,
the carrier key(s), and one line of notes. Absences are only findings if
the element matters for THIS repo's operating model.

| id | element | typical carrier in this repo |
|----|---------|------------------------------|
| R1 | Document identity and governance: id, version, status, ratification trail, declared canonicity, schema validation | `document.*`, validate.py wiring |
| R2 | Strategic frame: north star, organising principles, explicit non-goals, sibling-roadmap boundary | `north_star`, header prose |
| R3 | Current-state baseline: what already exists, so the delta is explicit | `foundation_already_shipped` |
| R4 | Work breakdown: stable ids, intent (why), scope, verifiable exit criteria, effort, status lifecycle | `tier_items[]` |
| R5 | Sequencing: machine-checkable dependencies, tiers/phases, eligibility semantics, computable critical path | `depends_on`, tiers, `PlatformRoadmapState` |
| R6 | Decision governance: candidate decisions, start-vs-completion gating, ratification states, deadlock/bootstrap clauses | `candidate_decisions[]`, bootstrap clauses |
| R7 | Risk register: open questions with resolution points, known gaps, deferrals with reversal conditions | `open_questions[]`, `known_gaps[]` |
| R8 | Economics: cost projection, effort calibration | `cost_projection`, `effort` |
| R9 | Measurability and freshness: per-item exit criteria, roadmap-level review/refresh mechanism, status trustworthiness | `exit_criteria`, preflight staleness note |
| R10 | Consumer integration: named consumers, agent-facing reading instructions, state computable without human interpretation | header, `agent_instructions`, preflight |

Deliberately ABSENT in this repo's style (do NOT report as gaps): calendar
dates/quarters (sequencing-over-dates by design), owner/assignee fields
(sole developer), stakeholder-communication lanes.

---

## 7. Execution plan (waves)

**Wave 0 (auditor, sequential):** branch check; preflight reads (Section 3);
Step 0 split (Section 4); pin `target_git_sha` via `git rev-parse HEAD`;
run all (prog) checks from D1/D6; create `docs/audit-reports/` and
`docs/audit-reports/wave-1-outputs/`.

**Wave 1 (parallel - dispatch all subagents in a single message):**

| id | name | dimension | inputs | output |
|----|------|-----------|--------|--------|
| A | GROUND-TRUTH-VERIFIER | D3 | roadmap (complete/in_progress/foundation slices), repo, SESSION_LOG, git log | `wave-1-outputs/A.yaml` |
| B | DECISION-ALIGNMENT-AUDITOR | D4 | roadmap CD slice, `docs/DECISIONS.md`, `logs/.decisions-index.jsonl`, AGENTS.md constraints | `wave-1-outputs/B.yaml` |
| C | COVERAGE-GAP-SCANNER | D8 | repo surfaces list, roadmap id+name inventory, `docs/plans/`, `docs/handoffs/` | `wave-1-outputs/C.yaml` |
| D | CONTENT-QUALITY-REVIEWER | D7 | roadmap not_started/reserved slice | `wave-1-outputs/D.yaml` |
| E | CROSS-ROADMAP-COHERENCE | D5 | both roadmap files, edge inventory | `wave-1-outputs/E.yaml` |

Subagent briefing rules:
- Each brief is self-contained: goal, ABSOLUTE file paths, the relevant
  Section 5 dimension text copied verbatim, required output schema, output
  path. Do NOT point subagents at this whole prompt.
- Subagent outputs are YAML, not markdown: a `claims` list where every row
  is `{id, affected_ids: [...], verdict_or_classification, evidence: [...],
  proposed_severity, proposed_confidence, note}`. Severity/confidence are
  PROPOSALS; the auditor assigns final values at synthesis.
- Subagent A may be split (A1: tiers T-1/T0, A2: T1+) if its brief exceeds
  a comfortable single-agent scope - decide from the measured item count.
- Use `general-purpose` subagents for A, B, E (synthesis-heavy) and
  `Explore` for C and D if available; pass `model: "opus"` unless the user
  has said otherwise.
- Trust but verify: when a subagent returns, spot-check at least one
  non-trivial claim per subagent against the source before accepting it
  into synthesis. Record each spot-check in the report.

**Wave 1.5 (auditor, while Wave 1 runs):** the D2 gating-semantics analysis
and the D6 eligibility-vs-semantics comparison. These need the full document
model in one head - do not delegate.

**Wave 2 (auditor, after Wave 1 returns):** synthesis. Dedupe (one root
cause = one finding listing all `affected_ids`, not N copies); assign final
severity/confidence; run D9 and D10 judgment passes; score the Section 6
rubric; author the report; self-validate it (Section 10); commit and push.

---

## 8. Deliverable - findings report schema

`docs/audit-reports/PLATFORM-ROADMAP-AUDIT-{YYYY-MM-DD}.yaml`:

```yaml
audit:
  id: PLATFORM-ROADMAP-AUDIT-{YYYY-MM-DD}
  target: docs/ROADMAP-PLATFORM.yaml
  target_git_sha: "<git rev-parse HEAD at audit time>"
  date: "{YYYY-MM-DD}"
  method: docs/AUDIT-PROMPT-platform-roadmap-audit.md
  method_version: 1

summary:
  headline: |
    3-6 plain sentences: overall trustworthiness verdict, the dominant
    failure modes found (if any), and whether preflight/planning consumers
    can currently rely on the document.
  findings_by_severity: {critical: 0, high: 0, medium: 0, low: 0}
  findings_by_dimension: {D1: 0, D2: 0, D3: 0, D4: 0, D5: 0, D6: 0, D7: 0, D8: 0, D9: 0, D10: 0}
  status_truth_verdicts: {confirmed: 0, partially_confirmed: 0, unsubstantiated: 0, contradicted: 0}
  rubric_coverage:
    - id: R1
      element: "Document identity and governance"
      present: true | partial | false
      carrier_keys: [...]
      notes: "..."
    # ... R2-R10

findings:
  # sorted by severity desc, then dimension
  - id: F-001
    dimension: D3
    severity: critical | high | medium | low
    confidence: high | medium | low
    title: "one line"
    detail: |
      What is wrong, why it matters for this roadmap's consumers, and the
      blast radius. Complete sentences.
    affected_ids: [T2.3, CD.7]          # roadmap ids; [] if document-level
    evidence:
      - "docs/ROADMAP-PLATFORM.yaml:1234"
      - "command: rg -n '...' ...; output: '...'"
    proposed_remediation: "proposal only - this audit changes nothing"
    proposed_rec: true | false           # should become a portal rec after user review

verification:
  enforced_split:
    machine_enforced: [...]              # Column A, confirmed
    audit_surface: [...]                 # Column B, confirmed
    waived: [{check: "...", reason: "..."}]
  programmatic_checks:
    - {name: validator_pass, command: "bin/venv-python -m scripts.platform_roadmap", result: PASS}
    - {name: preflight_state, command: "...", result: "no error key; N eligible, M blocked"}
    # ... every (prog) check from Section 5
  subagent_spot_checks:
    - {subagent: A, claim: "...", verdict: confirmed | refuted, action_taken: "..."}

open_questions_for_user:
  - "design-preference or scope questions surfaced but NOT filed as findings"
```

Severity taxonomy:
- **critical**: the roadmap asserts false state that would misdirect
  autonomous work (false `complete` on a dependency of eligible work;
  structural deadlock no bootstrap exemption covers; a consumer
  crashes/errors on the current file).
- **high**: dangling or wrong reference the validator does not catch; CD
  state contradicting the ratified decision record; materially wrong
  eligibility computation; product-critical platform item practically
  blocked but presented as available.
- **medium**: unverifiable exit criteria on near-eligible items;
  effort/strategic inconsistency; active repo surface with no roadmap
  representation; stale open_questions/known_gaps.
- **low**: hygiene, prose drift, stale counts, naming inconsistency.

Confidence: `high` = direct repo evidence; `medium` = indirect or
single-source; `low` = depends on a possibly-stale cache or a judgment call.

Evidence rule: every finding carries at least one `path:line` or
reproducible `command + output` evidence entry. A claim without evidence is
discarded at synthesis, not downgraded.

---

## 9. Definition of done

1. All (prog) checks executed and recorded under
   `verification.programmatic_checks`.
2. Every Column-B audit-surface row covered by a dimension check or
   explicitly waived with a reason.
3. Every `complete` / `in_progress` / foundation entry has a D3 verdict.
4. Report YAML parses (`bin/venv-python -c "import yaml;
   yaml.safe_load(open('docs/audit-reports/PLATFORM-ROADMAP-AUDIT-....yaml'))"`)
   and structurally matches Section 8 (keys, enums, sort order).
5. At least one spot-check per Wave 1 subagent recorded.
6. `git status` shows ONLY new files under `docs/audit-reports/`.
7. No recs filed, no plans authored, no PR opened.
8. Report committed and pushed on the session branch
   (`git push -u origin <branch>` with the AGENTS.md retry protocol).
9. Final chat reply: headline verdict, counts by severity, top 5 findings
   in plain sentences, and the open questions - nothing that exists only
   in the report and matters to the user may be omitted from the reply.

## 10. Ask-user gates (use AskUserQuestion; otherwise do not block)

- You discover something that looks like an ACTIVE breakage beyond the
  roadmap (failing CI, security exposure): report it in chat and ask before
  doing anything beyond including it as a finding.
- A finding's severity hinges on warehouse state you cannot read
  (stale-cache ambiguity on a would-be critical finding): ask rather than
  guess.
- Anything in this prompt contradicts AGENTS.md or the repo's current
  state: AGENTS.md and the repo win; note the divergence in the report's
  `open_questions_for_user` and proceed.

## 11. Out of scope - do not do these

- Editing either roadmap or any consumer script, even for "obvious" fixes.
- Filing recommendations or decisions via the portal.
- Auditing `docs/ROADMAP-PRODUCT.yaml` content quality (separate audit) -
  only the D5 cross-roadmap surface.
- Re-deciding ratified decisions or pivot-era architecture commitments.
- Full `pytest` sweeps or full `scripts.validate` presubmit runs - targeted
  evidence commands only; nothing in this audit changes source files.
- Producing a human-readable companion summary document (the YAML report
  plus your chat reply are the only outputs, per AGENTS.md).
