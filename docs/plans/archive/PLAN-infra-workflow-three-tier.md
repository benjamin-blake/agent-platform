# Plan

## Intent
Establish a cleanly separated three-tier workflow (`/plan` -> `/implement` -> `/develop-executor`) that enables autonomous recursive self-improvement by ensuring each agent has one job, friction capture has no open loops, and non-automatable work surfaces for human discussion rather than accumulating silently.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-workflow-three-tier

## Phase
Meta-improvement (workflow infrastructure) -- supports all phases

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/DECISIONS.md | Modify | Add Decision 42: Three-Tier Workflow Architecture |
| .github/prompts/plan.prompt.md | Modify | Output Work Areas instead of Execution Steps; add non-automatable rec discussion |
| .github/prompts/implement.prompt.md | Modify | Refactor to scoping-focused agent (no code changes) |
| .github/agents/plan-critique.agent.md | Modify | Evaluate strategic alignment only; remove per-file checks |
| scripts/session_preflight.py | Modify | Add `non_automatable_recommendations` field with details |
| tests/test_session_preflight.py | Modify | Add tests for `non_automatable_recommendations` field |
| scripts/execute_recommendation.py | Modify | Change default to compound execution (effort <= M, max 4 recs) |
| tests/test_execute_recommendation.py | Modify | Add tests for compound default behavior |
| .github/agents/rec-curator.agent.md | Modify | Add stale `automatable: false` check (30+ days) |

## Bundled Recommendations
None -- this plan defines the workflow migration directly.

## Acceptance Criteria
- [ ] Decision 42 documents the three-tier architecture with friction loop diagram
- [ ] `/plan` outputs Work Areas table instead of Ordered Execution Steps
- [ ] `/plan` Step 0 mandatory-discusses non-automatable recs surfaced by preflight
- [ ] `/implement` researches work areas and produces atomic recs (no code changes)
- [ ] `/plan-critique` evaluates strategic alignment, not per-file scope
- [ ] Preflight JSON includes `non_automatable_recommendations` count and details
- [ ] tests/test_session_preflight.py covers `non_automatable_recommendations` field
- [ ] Executor defaults to compound mode (effort <= M total, max 4 recs)
- [ ] tests/test_execute_recommendation.py covers compound default behavior
- [ ] rec-curator checks for stale `automatable: false` recs
- [ ] validate.py passes
- [ ] All friction capture points preserved (no open loops)

## Constraints
- Must preserve all existing friction capture mechanisms
- Non-automatable recs must have a resolution path (not accumulate silently)
- Compound execution bounds: effort sum <= M (XS=0.5, S=1, M=2), max 4 recs
- Same-file recs preferred in compound batches (reduces merge conflicts)

## Context
- Decision 40 (Copilot SDK migration) is deferred -- current CLI-based executor is stable
- Decision 38 (workflow consolidation) simplified implement.prompt.md to 10 steps; this builds on that
- Current `/plan` is overloaded: does strategic AND tactical work
- Current `/implement` follows execution steps but doesn't scope
- Executor compound mode works but isn't default
- Non-automatable recs accumulate without resolution path

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add Decision 42 to DECISIONS.md

Add Decision 42 after Decision 41 with this content:

**Decision 42: Three-Tier Workflow Architecture (Decided)**

**Decision:** Separate the human-agent workflow into three tiers with distinct responsibilities: `/plan` (strategic), `/implement` (scoping), `/develop-executor` (autonomous execution). Non-automatable recommendations must be surfaced and discussed in `/plan`, not accumulated silently.

**Problem:**
- `/plan` was overloaded: produced strategic decisions AND detailed execution steps
- `/implement` followed execution steps but had no scoping authority
- Non-automatable recs accumulated without resolution path
- Executor defaulted to single-rec mode, leaving throughput on the table

**Architecture (three-tier):**
```
Human Intent
     |
     v
/plan (STRATEGIC)
  - Decisions + Work Areas
  - Mandatory non-automatable rec discussion
  - Output: PLAN-{slug}.md with Work Areas table
     |
     v
/implement (SCOPING)
  - Research each Work Area
  - Break into atomic recs (effort <= M)
  - Create briefing files for complex recs
  - Output: Populated recommendations log
     |
     v
/develop-executor (AUTONOMOUS)
  - Compound execution (3-4 recs, effort <= M total)
  - Files friction recs on failure
  - Output: Code changes + PR
     |
     v
Friction recs (automatable: false)
     |
     v
Back to /plan preflight (mandatory discussion)
```

**Key design principles:**
1. **Separation of concerns** -- each agent has one job, can be tuned independently
2. **No open loops** -- every friction point has a resolution path
3. **Non-automatable recs surface** -- preflight shows them, `/plan` must discuss before proceeding
4. **Compound execution default** -- executor picks 3-4 recs (effort <= M, max 4) unless overridden
5. **Stale rec detection** -- rec-curator flags `automatable: false` recs older than 30 days

**Compound execution bounds:**
- Effort weights: XS=0.5, S=1, M=2, L=4, XL=8
- Max total effort per compound batch: M (=2)
- Max recs per batch: 4
- Prefer same-file recs (reduces merge conflicts)
- Prefer recs with shared dependencies

**Trade-offs accepted:**
- `/plan` sessions may be longer due to mandatory non-automatable discussion
- Compound execution may have harder-to-attribute failures (mitigated by per-rec telemetry)

**Related:** Decision 38 (workflow consolidation), Decision 40 (Copilot SDK deferred)

**Decision status:** Decided -- April 2026

---

### Step 2: Refactor plan.prompt.md -- Remove Execution Steps, Add Work Areas

Modify `.github/prompts/plan.prompt.md`:

**2a. Update Step 0 preflight conditionals** -- Add after the `open_recommendations > 0` conditional:

```markdown
- **`non_automatable_recommendations > 0`** -- MANDATORY DISCUSSION. Present each non-automatable rec:
  > "These recommendations are marked non-automatable and need human discussion:
  > - **rec-XXX**: [title] -- [context excerpt]
  > - **rec-YYY**: [title] -- [context excerpt]
  >
  > For each, decide:
  > 1. Can this be broken into smaller automatable recs? (proceed to scope in this session)
  > 2. Is this blocked on external factors? (keep open, note the blocker)
  > 3. Should this be declined? (decline with resolution)
  >
  > Respond with your decision for each before continuing."
  Wait for the human's response. Do not proceed until all non-automatable recs are addressed.
```

**2b. Replace "Ordered Execution Steps" section** with:

```markdown
## Work Areas
| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| [area name] | [files/modules affected] | [why this work area exists] | [XS/S/M/L/XL] |

(Work Areas define WHAT needs to be done at a high level. The `/implement` session will research each area and produce specific atomic recs.)
```

**2c. Update Step 7 plan template** -- Replace "Ordered Execution Steps" with "Work Areas" table.

**2d. Update Plan Type** -- Add `STRATEGIC` option:
```markdown
## Plan Type
STRATEGIC | IMPLEMENTATION | REPORT-ONLY

(STRATEGIC plans output Work Areas for /implement to scope. IMPLEMENTATION plans have Ordered Execution Steps. REPORT-ONLY plans produce documents for human review.)
```

**2e. Update Step 9 completion message** -- Add case for STRATEGIC:

```markdown
**If `Plan Type` is `STRATEGIC`:**

> **Planning complete.** `docs/plans/PLAN-{slug}.md` is ready with Work Areas for scoping.
>
> Review it and edit if needed. When satisfied, open a new Copilot Chat and send:
>
> **`/implement`**
>
> The implement session will research each Work Area and produce atomic recommendations for the executor.
```

---

### Step 3: Refactor implement.prompt.md -- Scoping Agent

Rewrite `.github/prompts/implement.prompt.md` to be a scoping agent:

**New structure:**
```markdown
## Intent
Research Work Areas from a STRATEGIC plan and produce atomic, automatable recommendations for the executor.

## Behavioural Invariants
```yaml
preflight_run: true
never_on_main: true
no_code_changes: true  # This agent scopes, does not implement
```

## Step 0: Run Preflight
[Same as current]

## Step 1: Load PLAN File
Read `docs/plans/PLAN-{slug}.md` from the current branch. Extract:
- Intent (verify alignment with North Star)
- Work Areas table
- Constraints
- Context (relevant decisions)

If no PLAN file exists or Plan Type is not STRATEGIC, STOP and report: "No STRATEGIC plan found. Run /plan first."

## Step 2: For Each Work Area

For each row in the Work Areas table:

1. **Research the scope** -- Read the files/modules listed. Understand current state.
2. **Identify dependencies** -- What must be done first? What can be parallelized?
3. **Break into atomic recs** -- Each rec should have effort <= M. Prefer S or XS.
4. **Write full context** -- Each rec must have enough context for the executor to work alone.
5. **Define acceptance command** -- Must be a single inline command that returns 0 on success.

## Step 3: Create Briefing Files

For any rec with estimated effort > M that cannot be broken down further:
- Create `docs/plans/briefings/BRIEFING-rec-NNN.md`
- Include: detailed problem statement, solution approach, files to modify table, test strategy

## Step 4: File Recs to Log

Append all recs to `logs/.recommendations-log.jsonl` following the schema in copilot-instructions.md.

Verify each rec has:
- `automatable: true` (if not, explain why in context)
- `acceptance` command that is a single inline command
- `dependencies` array (may be empty)
- Complete `context` (executor should not need to read this plan)

## Step 5: Validate

Run `python scripts/validate.py` -- must exit 0.

## Step 6: Report

Output:
- Total recs filed
- Recs by effort level (XS/S/M/L/XL)
- Recs marked `automatable: false` (should be rare -- explain why)
- Briefing files created
- Next step: "Run `/develop-executor` or `python -m scripts.execute_recommendation rec-NNN`"
```

---

### Step 4: Update plan-critique.agent.md -- Strategic Focus

Modify `.github/agents/plan-critique.agent.md`:

**4a. Remove from evaluation criteria:**
- Per-file scope validation
- Test coverage checks for specific files
- Acceptance command validation

**4b. Add to evaluation criteria:**
- Decision conflict check (does this contradict existing decisions?)
- North Star alignment score (1-5 with justification)
- Work Area scoping (are areas well-bounded? too large?)
- Phase dependency check
- Strategic risk assessment

**4c. Update output format:**
```markdown
**Decision Conflicts:** None / [list]
**North Star Alignment:** X/5 -- [justification]
**Work Area Scoping:**
- [Area 1]: appropriately scoped / too large (suggest split) / too small (merge with X)
**Phase Dependencies:** Aligned / [issues]
**Strategic Risks:** [list or "none identified"]
**Recommendation:** PROCEED / REVISE
```

---

### Step 5: Update session_preflight.py -- Non-Automatable Recs

Modify `scripts/session_preflight.py`:

**5a. Add to the preflight JSON output:**
```python
"non_automatable_recommendations": count,
"non_automatable_details": [
    {"id": "rec-XXX", "title": "...", "context_excerpt": "..."},
    ...
]
```

**5b. Implementation:** After loading recs, filter for `status: "open"` and `automatable: false`. Include up to 10 in details.

---

### Step 6: Update execute_recommendation.py -- Compound Default

Modify `scripts/execute_recommendation.py` main() function (around line 1640):

**6a. Change default behavior** -- When no explicit mode is specified (`--compound`, `--batch`, or `--single`), default to compound execution instead of single-rec mode.

**Current logic (approximately):**
```python
compound = args.compound or args.batch
if compound:
    # compound execution
else:
    # single execution (default)
```

**Change to:**
```python
# Single mode only when explicitly requested or forced
single_mode = args.single or (args.rec_id and not args.compound and not args.batch)

if single_mode:
    # single execution
else:
    # compound execution (default)
```

**6b. Add effort calculation for auto-batching:**
```python
EFFORT_WEIGHTS = {"XS": 0.5, "S": 1, "M": 2, "L": 4, "XL": 8}
MAX_BATCH_EFFORT = 2  # Equivalent to M
MAX_BATCH_SIZE = 4

def select_compound_batch(recs: list) -> list:
    """Select recs for compound execution (effort <= M, max 4)."""
    eligible = [r for r in recs if r.get("automatable") and r.get("status") == "open"]
    eligible.sort(key=lambda r: EFFORT_WEIGHTS.get(r.get("effort", "M"), 2))

    batch = []
    total_effort = 0
    for rec in eligible:
        effort = EFFORT_WEIGHTS.get(rec.get("effort", "M"), 2)
        if total_effort + effort <= MAX_BATCH_EFFORT and len(batch) < MAX_BATCH_SIZE:
            batch.append(rec)
            total_effort += effort
        if total_effort >= MAX_BATCH_EFFORT or len(batch) >= MAX_BATCH_SIZE:
            break
    return batch
```

**6c. Add `--single` flag to argparse** (if not already present):
```python
parser.add_argument("--single", action="store_true", help="Force single-rec execution")
```

---

### Step 7: Update rec-curator.agent.md -- Stale Non-Automatable Check

Modify `.github/agents/rec-curator.agent.md`:

**7a. Add to weekly checks:**
```markdown
## Stale Non-Automatable Recs

Scan for recs with `automatable: false` and `date` older than 30 days.

For each stale rec:
1. Check if context suggests it's now automatable (tooling improvements, dependencies closed)
2. Check if it should be declined (no longer relevant)
3. Flag for human review in findings output

Output:
```json
{
  "stale_non_automatable": [
    {"id": "rec-XXX", "age_days": 45, "suggestion": "may be automatable now / decline / keep open"}
  ]
}
```
```

---

### Step 8: Run pytest

Run `python -m pytest tests/ -q` -- all tests must pass.

---

### Step 9: Run validate.py

Run `python scripts/validate.py` -- must exit 0.

---

### Step 10: Report Implementation Summary

Report:
- Decision 42 placement in DECISIONS.md
- Files modified with summary of changes
- New Plan Type option (STRATEGIC)
- Friction loop completeness verification
- Any design decisions made during implementation
