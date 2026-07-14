# Plan - Migrate Ops Data Instructions

## Intent
Harden the repository's operational data governance by ensuring all instructions, prompts, and skills use the `ops_data_portal.py` gateway for recommendation logging. This eliminates direct, unvalidated appends to `logs/.recommendations-log.jsonl` and ensures all data flows through the `OpsWriter` to the Athena-backed Iceberg tables, maintaining a single source of truth.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/migrate-ops-data-instructions

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `GEMINI.md` | Modify | Harden `Single Portal Invariant` language for Gemini. |
| `.github/copilot-instructions.md` | Modify | Update `Recommendation & Decision Logging` and `Known Gotchas` to emphasize portal usage. |
| `.agents/skills/code-review/SKILL.md` | Modify | Update findings output instructions to use `ops_data_portal.py` CLI/API. |
| `.agents/skills/implement/SKILL.md` | Modify | Update scoping rules to use `ops_data_portal.py` for filing recommendations. |
| `.agents/skills/planning/SKILL.md` | Modify | Update recommendation suggestion logic to mention the portal/cache sync. |
| `docs/AGENT_WORKFLOW.md` | Modify | Update workflow descriptions to reflect the `ops_data_portal.py` path. |
| `docs/ARCHITECTURE-WORKFLOW.md` | Modify | Update architecture descriptions and diagrams regarding ops data write paths. |
| `scripts/executor/postflight.py` | Modify | Refactor `cleanup_after_merge` and `finalize` to remove direct git-add/commit of the log. |
| `tests/test_execute_recommendation.py` | Modify | Update mocks to rely on `ops_data_portal` instead of file system side-effects. |

## Bundled Recommendations
None.

## Infrastructure Dependencies
None.

## Acceptance Criteria
- [ ] No instructions or skills describe "appending to `logs/.recommendations-log.jsonl`" as a manual or `write_to_file` operation.
- [ ] All recommendation filing/updating instructions explicitly cite `scripts/ops_data_portal.py`.
- [ ] `GEMINI.md` and `copilot-instructions.md` contain consistent language regarding the `Single Portal Invariant`.
- [ ] `validate.py` continues to pass, confirming no direct write paths were introduced in code.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Search for legacy append strings | `grep -r "append to logs/.recommendations-log.jsonl" .` | No matches in modified files | String still exists |
| 2 | [pre-deploy] | Search for direct write instructions | `grep -r "write_to_file.*logs/.recommendations-log.jsonl" .` | No matches in modified files | String still exists |
| 3 | [pre-deploy] | Verify portal references | `grep -r "ops_data_portal.py" .agents/skills/` | Matches in `code-review/SKILL.md` and `implement/SKILL.md` | Reference missing |
| 4 | [pre-deploy] | Run validation | `python scripts/validate.py` | All checks pass | Regression introduced |

## Constraints
- Follow `GEMINI.md` code style and safety rules.
- Maintain documentation integrity.
- Use `scripts/ops_data_portal.py` for any testing if needed (though this plan is mostly documentation).

## Context
- Decision 51: Local-First Outbox (established the `OpsWriter` pattern).
- `ops_data_portal.py` is the authoritative write gateway that handles ID allocation via DynamoDB and staging to S3.
- `validate.py` already contains a check (`validate_rec_write_paths`) to block direct writes in Python code.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Modify `GEMINI.md`**: Update `Operational Data Governance` section to be more explicit about using `ops_data_portal.py` for all operations.
2. **Modify `.github/copilot-instructions.md`**: Update sections 25-33 and 176-180 to reinforce the portal as the sole write path.
3. **Modify `.agents/skills/code-review/SKILL.md`**: Update Step 11 and Post-Report sections to instruct the caller to use `ops_data_portal.py` for filing findings.
4. **Modify `.agents/skills/implement/SKILL.md`**: Update `Strategic Scoping Rules` (Step 81) to use the portal for appending recommendations.
5. **Modify `.agents/skills/planning/SKILL.md`**: Update `Suggest Aligned Recommendations` (Step 66) to mention the portal/cache.
6. **Modify `docs/AGENT_WORKFLOW.md`**: Update sections on `Automated Recommendation Execution` and `Unified Session Telemetry`.
7. **Modify `docs/ARCHITECTURE-WORKFLOW.md`**: Update `Ops Data Pipeline` section and any related diagrams or text.
8. **Refactor `scripts/executor/postflight.py`**: Remove the manual `git add` and `git commit` logic for `logs/.recommendations-log.jsonl` in `cleanup_after_merge` and `finalize`, as the portal handles persistence and the local file is a cache.
9. **Update `tests/test_execute_recommendation.py`**: Refactor test cases (specifically `TestCleanupAfterMerge` and `TestFinalize`) to mock `ops_data_portal` methods instead of asserting on git commands for the log file.
10. **Final Review**: Run grep to ensure no legacy "append to" strings remain in the instruction set.
11. **Execute Verification Plan**.
12. Report implementation and verification results.
