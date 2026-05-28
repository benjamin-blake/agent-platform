# Plan

## Intent
Ensure data integrity of the recommendation execution log by detecting and remediating any closed recommendations whose implementation was silently discarded by the pre-hotfix acceptance bypass bug, strengthening the self-improving feedback loop that depends on accurate execution records.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-bypass-audit

## Phase
Phase 1: Core Infrastructure (complete) -- this is infrastructure maintenance work, not phase-gated.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/plan_audit.py` | Modify | Add `--check-pr-urls` subcommand for bypass impact audit |
| `tests/test_plan_audit.py` | Modify | Add tests for the new `--check-pr-urls` functionality |

## Bundled Recommendations
- **rec-359**: Audit closed recs with execution_result=success and no execution_pr_url for acceptance bypass impact

## Acceptance Criteria
- [ ] `python -m scripts.plan_audit --check-pr-urls` exits 0 and prints a structured report
- [ ] Report categorises candidates as SAFE (on-main/compound-with-batch-PR), VERIFIED (code found on main via git log), or MISSING (code not on main)
- [ ] VERIFIED entries include the merge commit hash found
- [ ] Tests cover all three categories (SAFE, VERIFIED, MISSING) via mocked git output
- [ ] `python -m pytest tests/test_plan_audit.py -x -q` passes
- [ ] `python -m scripts.validate` exits 0

## Constraints
- Windows host with Git Bash -- all subprocess calls must use `encoding='utf-8', errors='replace'`
- No `eval()`/`exec()` -- standard JSON parsing only
- plan_audit.py currently exits 0 always (informational) -- preserve this behaviour for `--check-pr-urls`
- Do not auto-reopen or auto-modify any recommendation status -- report only

## Context
- **Hotfix 9111d16** (2026-04-14 20:20:44): Fixed acceptance bypass where finalize() was never called on post-validation success, causing implementation to be discarded with no PR
- **rec-357** (dependency): Closed via PR #192 -- regression test for the bypass is in place
- **Scope of impact**: 43 candidates (closed + success/compound, no PR URL). Breakdown: 3 safe (on main/N/A), 13 compound batch recs, 25 standalone agent branches
- **Key insight from forensics**: All spot-checked compound batches have merge commits on main despite missing `execution_pr_url` -- this is a metadata gap, not a code gap. The real risk is in standalone recs
- **Known Gotcha**: Windows subprocess must use `encoding='utf-8', errors='replace'` with `text=True`
- **Squash merge caveat**: `git log --grep="rec-NNN"` may miss squash merges whose commit message omits the rec ID. Such recs will appear as MISSING (false positive). The implementer should document this caveat in the report output

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Add `check_pr_urls()` function to `scripts/plan_audit.py`**
   - Add `argparse` to handle `--check-pr-urls` flag (preserve default behaviour when no flag)
   - Read `logs/.recommendations-log.jsonl` and find all entries where `status == "closed"` AND `execution_result in ("success", "compound")` AND `execution_pr_url` is absent/empty
   - Categorise each candidate:
     - **SAFE**: `execution_branch` is `"main"` or `"N/A"` (applied directly, no PR expected)
     - **SAFE**: `execution_result == "compound"` AND another rec in the same `execution_branch` has a non-empty `execution_pr_url` (compound batch covered by batch PR)
     - **VERIFIED**: Run `git log --oneline origin/main --grep="rec-{NNN}"` and check for merge commit. Store the commit hash found
     - **MISSING**: No merge commit found on `origin/main` for the rec ID. Note in report output that squash merges omitting `rec-NNN` from commit message will appear here as false positives
   - Print structured report to stdout with counts per category and per-rec details for VERIFIED and MISSING
   - Exit 0 always (informational)
   - Acceptance: `python -m scripts.plan_audit --check-pr-urls` exits 0 and output contains `=== PR URL Audit Report ===`

2. **Add tests for `check_pr_urls()` in `tests/test_plan_audit.py`**
   - Create `TestCheckPrUrls` class with tests for:
     - SAFE classification (on-main branch, compound-with-batch-PR)
     - VERIFIED classification (git log returns matching commit)
     - MISSING classification (git log returns no match)
     - Empty JSONL (no candidates found)
   - Mock `subprocess.run` for git calls and file I/O for JSONL reading
   - Acceptance: `python -m pytest tests/test_plan_audit.py::TestCheckPrUrls -x -q` passes

3. Run `python -m pytest tests/test_plan_audit.py -x -q` -- all tests must pass before proceeding

4. Run `python -m scripts.validate` -- must exit 0

5. Report what was implemented and any design decisions made during implementation
