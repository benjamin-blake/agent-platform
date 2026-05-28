# Plan

## Intent
Strengthen the self-improving feedback loop by (1) documenting boundary contracts for external tools so integration assumptions are explicit and auditable, (2) adding external integration checks to **both critique gates** so incorrect tool usage is caught before implementation in **both workflows**, (3) converting two gotchas into machine-checkable validate.py rules to close the mistake-to-prevention loop, and (4) implementing bidirectional recommendation sync between local and S3 so both manual and scheduled-agent recommendations flow into a unified view.

## Dual-Workflow Applicability

This plan affects **both** agent workflows:

| Workflow | Entry Point | Critique Gate | Who Uses It |
|----------|-------------|---------------|-------------|
| **Manual** | `/plan` then `/implement` | `.github/agents/plan-critique.agent.md` | Human-driven sessions with Opus planning |
| **Automated** | `/develop-executor` | `config/prompts/executor/critique.prompt.md` | Autonomous recommendation executor |

Both workflows read `.github/copilot-instructions.md` for rules and gotchas. Adding the External Integration Check rule there ensures both workflows enforce it. The critique gates are workflow-specific, so each must be updated separately.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-external-tool-gates

## Phase
Infra (cross-cutting workflow improvement)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/sync_recommendations.py` | Create | Core sync logic: merge S3 agent-* recs into local, push closures back |
| `scripts/session_preflight.py` | Modify | Call sync_recommendations.merge_from_s3() on startup |
| `scripts/session_postflight.py` | Modify | Call sync_recommendations.push_closures_to_s3() in --auto flow |
| `tests/test_session_preflight.py` | Modify | Mock sync call, assert new JSON field |
| `tests/test_session_postflight.py` | Modify | Mock sync call, assert new JSON field |
| `docs/contracts/copilot-cli.md` | Create | Boundary contract for Copilot CLI wrapper |
| `docs/contracts/build-lambda.md` | Create | Boundary contract for Lambda packaging |
| `.github/copilot-instructions.md` | Modify | Add External Integration Check section (applies to both workflows) |
| `.github/agents/plan-critique.agent.md` | Modify | Add Step 12 for external integration (manual workflow critique) |
| `config/prompts/executor/critique.prompt.md` | Modify | Add hard-fail rule 10 for external tools (executor workflow critique) |
| `scripts/validate.py` | Modify | Add 2 invariant checks: @file gotcha + mock count check |
| `tests/test_sync_recommendations.py` | Create | Tests for sync_recommendations.py |
| `tests/test_validate.py` | Modify | Tests for new invariant checks |

## Bundled Recommendations
- **rec-120**: Boundary contract specs for external tool wrappers (S, High)
- **rec-121**: Add external integration check to both critique gates (XS, High)
- **rec-122**: Invariant extraction: convert gotchas to machine-checkable validate.py rules (M, Medium)

## Acceptance Criteria
- [ ] `ls docs/contracts/copilot-cli.md && grep -q "Verified" docs/contracts/copilot-cli.md` passes
- [ ] `grep -q "External Integration Check" .github/copilot-instructions.md` passes
- [ ] `grep -q "external integration" .github/agents/plan-critique.agent.md` passes
- [ ] `grep -q "external tool" config/prompts/executor/critique.prompt.md` passes
- [ ] `grep -q "invariant" scripts/validate.py` passes
- [ ] `python -m scripts.sync_recommendations --help` runs without error
- [ ] `python -m pytest tests/test_sync_recommendations.py -q` passes
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Python 3.12+, type hints required
- No Docker on company VM
- Windows Git Bash shell (no PowerShell)
- Use `sys.executable` not `'python'` in subprocess calls
- Import safety: no exceptions raised during module import
- S3 bucket: `bblake-platform-agent-logs` (already exists)
- AWS profile: `company-aws-profile`

## Context
- **Two workflows affected**: Manual (`/plan` + `/implement`) and Automated (`/develop-executor`) -- see Dual-Workflow Applicability section above
- **Manual workflow critique gate**: `.github/agents/plan-critique.agent.md` (invoked by Opus at end of `/plan`)
- **Executor workflow critique gate**: `config/prompts/executor/critique.prompt.md` (invoked by executor before each step)
- **S3 recommendations path**: `s3://bblake-platform-agent-logs/recommendations/agent-recommendations.jsonl`
- **Local recommendations**: `logs/.recommendations-log.jsonl`
- **s3_log_store.py** already provides `read_jsonl()`, `append_jsonl()`, `get_backend()` for S3/local switching
- **S3 concurrency**: Read-modify-write race conditions are an accepted risk (see Decision 33 pattern); sync operations are idempotent and run during human-attended sessions, minimizing collision probability
- **Decision 37** establishes Lambda + GitHub Models API pattern for scheduled agents
- **Gotcha: Copilot CLI @file vs user message** describes the semantic difference between context injection and instruction
- **Gotcha: cleanup_after_merge mock exhaustion** describes the mock count synchronization issue

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create sync_recommendations.py
Create `scripts/sync_recommendations.py` with the following functions:

1. `merge_from_s3() -> dict` - Read S3 `recommendations/agent-recommendations.jsonl`, read local `.recommendations-log.jsonl`, merge any S3 entries with `agent-*` IDs not present locally. For closure conflicts (local closed, S3 open), prefer S3 (source of truth). Return `{"merged": N, "conflicts_resolved": N}`.

2. `push_closures_to_s3() -> dict` - Read both files. For any local entry with `status: closed` that has an S3 counterpart still `open`, update the S3 entry. Put the updated JSONL back to S3. Return `{"closures_pushed": N}`.

3. `main()` - CLI with `--merge` and `--push-closures` flags for manual invocation.

Use `s3_log_store.py` primitives. Handle `NoSuchKey` gracefully (empty file = no entries). Log operations to stdout.

**S3 concurrency note:** Read-modify-write operations on S3 are not atomic. Per the accepted risk pattern (Decision 33), this is acceptable because: (a) sync runs during human-attended sessions (low collision probability), (b) operations are idempotent (re-running merge/push produces the same result), (c) worst-case is a missed merge that gets picked up next session.

### Step 2: Create tests for sync_recommendations.py
Create `tests/test_sync_recommendations.py` with tests covering:
- `merge_from_s3()` when S3 has new entries
- `merge_from_s3()` when S3 is empty
- `merge_from_s3()` closure conflict resolution (S3 open wins)
- `push_closures_to_s3()` when local has closed entries
- `push_closures_to_s3()` when nothing to push

Mock `s3_log_store.read_jsonl` and S3 client calls. Do not make real S3 requests.

### Step 3: Integrate sync into session_preflight.py and update tests
Modify `scripts/session_preflight.py`:
- Import `from scripts.sync_recommendations import merge_from_s3`
- Call `merge_from_s3()` after checking venv/branch but before counting recommendations
- Add result to preflight JSON: `"recommendation_sync": {"merged": N, "conflicts_resolved": N}`

Modify `tests/test_session_preflight.py`:
- Mock `scripts.sync_recommendations.merge_from_s3` in existing preflight tests
- Add test that verifies `recommendation_sync` field appears in output JSON
- Verify merge is called before recommendation count (order matters for accurate count)

### Step 4: Integrate sync into session_postflight.py and update tests
Modify `scripts/session_postflight.py`:
- Import `from scripts.sync_recommendations import push_closures_to_s3`
- In the `--auto` flow (after successful push), call `push_closures_to_s3()`
- Add result to auto JSON: `"recommendation_sync": {"closures_pushed": N}`

Modify `tests/test_session_postflight.py`:
- Mock `scripts.sync_recommendations.push_closures_to_s3` in existing `--auto` tests
- Add test that verifies `recommendation_sync` field appears in `--auto` output JSON
- Verify push is called after successful git push (not on failure paths)

### Step 5: Create boundary contract for Copilot CLI
Create `docs/contracts/copilot-cli.md` with:
- **Tool**: GitHub Copilot CLI (`gh copilot suggest`, `copilot`)
- **Input semantics**: `-p "instruction"` is user message (agent acts on it); `@filepath` is document context (agent sees but does not treat as instruction)
- **What we send**: Short instruction string + file as supplementary context
- **Why**: Agentic models receiving only `@file` context ask "what should I do?" and implement the spec instead of planning against it
- **Doc page verified**: GitHub Copilot CLI docs (https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line)
- **Date last verified**: [implementation date]
- **Related gotcha**: "Copilot CLI @file vs user message" in copilot-instructions.md

### Step 6: Create boundary contract for build_lambda.py
Create `docs/contracts/build-lambda.md` with:
- **Tool**: `scripts/build_lambda.py`
- **Input semantics**: `--handler` specifies entry point module path; `--output` specifies zip destination; `--layer` includes Lambda layer dependencies
- **What we send**: Handler paths following `src/data/handlers/{name}_handler.py` convention
- **Why**: Mismatched handler path causes Lambda to fail at import time with "Unable to import module"
- **Doc page verified**: AWS Lambda Python handler docs
- **Date last verified**: [implementation date]

### Step 7: Add External Integration Check to copilot-instructions.md (BOTH WORKFLOWS)
Add a new section to `.github/copilot-instructions.md` under Rules. This applies to **both** workflows because both `/plan` and `/develop-executor` read copilot-instructions.md:

```markdown
## External Integration Check

When a plan step calls an external tool (Copilot CLI, gh CLI, AWS SDK, Lambda invocation, subprocess call):
1. Cite the doc page defining the input semantics
2. State WHY this delivery mechanism is correct for the use case
3. State what would go wrong if the semantics differ from what the code assumes

If a boundary contract exists in `docs/contracts/`, reference it. Both `/plan` and `/develop-executor` workflows read this file, so this rule applies to all agent work.
```

### Step 8: Add external integration step to plan-critique.agent.md (MANUAL WORKFLOW)
This modifies the critique gate for the **manual workflow** (`/plan` + `/implement`).

Modify `.github/agents/plan-critique.agent.md`:
- Add Step 12 after Step 11 (before the structured output):

```markdown
12. **Check external integration assumptions:** For any Ordered Execution Step that calls an external tool (Copilot CLI, gh CLI, AWS SDK, Lambda invocation), verify:
    - The step cites the tool docs or a boundary contract in `docs/contracts/`
    - The step justifies WHY the delivery mechanism is correct
    - If no citation exists and the tool has known semantics issues (see copilot-instructions.md gotchas), flag as a risk
```

- Update the structured output to include `**External integration gaps:** [list or "none"]`

### Step 9: Add hard-fail rule to executor critique.prompt.md (EXECUTOR WORKFLOW)
This modifies the critique gate for the **automated executor workflow** (`/develop-executor`).

Modify `config/prompts/executor/critique.prompt.md`:
- Add rule 10 to the Hard-Fail Rules section:

```markdown
10. **External tool steps must cite their contract or docs.** Steps that call external tools (Copilot CLI, gh CLI, AWS SDK, Lambda invocations) without referencing a boundary contract in `docs/contracts/` or citing the tool's documentation must be flagged as NEEDS_REVISION. Exception: trivial git commands (add, commit, push) do not require citations.
```

### Step 10: Add invariant checks to validate.py
Modify `scripts/validate.py`:
- Add function `validate_invariants(failed: list[str]) -> None`
- Implement two checks:

**Check 1 (@file gotcha):** Scan `scripts/copilot_wrapper.py` for `copilot_call` patterns. If a `-p @filepath` pattern exists without an inline instruction string, fail with "Copilot CLI @file used without instruction string".

**Check 2 (mock count):** Scan `tests/test_execute_recommendation.py` for `TestCleanupAfterMerge` class. Count `subprocess.run` calls in `cleanup_after_merge()` (from `scripts/executor/postflight.py`). Count `side_effect` list lengths in test mocks. If mismatch, fail with "cleanup_after_merge mock side_effect count mismatch".

- Call `validate_invariants(failed)` in the main validation flow when scope includes Python files.

### Step 11: Add tests for new invariant checks
Modify `tests/test_validate.py`:
- Add tests for `validate_invariants()` covering:
  - Pass case: no violations
  - Fail case: @file without instruction (mock the source file content)
  - Fail case: mock count mismatch (mock both source files)

### Step 12: Run full validation
```bash
python -m pytest tests/ -q
python scripts/validate.py
```
All tests must pass. validate.py must exit 0.

### Step 13: Report implementation summary
Report what was implemented, which recommendations were closed, and any design decisions made during implementation.
