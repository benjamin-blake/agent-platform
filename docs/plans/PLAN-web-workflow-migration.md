# Plan

## Intent
Migrate the interactive `/plan` and `/implement` workflows from their local-dev (Windows + Git Bash, `agent/{slug}` branches, `gh` CLI) assumptions to the Claude-Code-on-the-web harness, so planning and implementation run correctly on the remote-execution surface the project has moved to. Contributes to the North Star by keeping the self-improvement loop (plan -> implement -> merge) operable on the platform the human actually uses.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Plan Path
docs/plans/PLAN-web-workflow-migration.md

(Authored on this session's harness-assigned branch `claude/dazzling-allen-NjdEH` -- no `agent/` branch was created. This plan is itself the first artefact produced under the new flow it specifies.)

## Phase
Phase Platform / workflow tooling (Layer 3-4 of the instruction architecture: `.claude/commands/*` + `.claude/skills/*`). Not a product-roadmap tier_item; this is `user_explicit_out_of_scope` workflow infrastructure requested directly by the human.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.claude/skills/planning/SKILL.md` | Modify | `#1` pin `opus[1m]`; `#2/3` relax `branch_creation` invariant, rewrite "Create Branch", PLAN template `## Branch`->`## Plan Path`, rewrite Confirmation Messages to the handoff format |
| `.claude/commands/plan.md` | Modify | `#1` add `model: opus[1m]` frontmatter; `#2/3` rewrite Step 7 (no `agent/` branch), add plan->main merge step, rewrite Step 12 handoff message |
| `.claude/commands/implement.md` | Modify | `#3` add `argument-hint` frontmatter + accept plan path as `$ARGUMENTS` in Step 2; `#4` Step 7 wording (MCP, no `gh`) |
| `.claude/skills/implement/SKILL.md` | Modify | `#4` rewrite Commit Flows: GitHub MCP + `subscribe_pr_activity`; delete all `gh pr` and `sleep 300`/`/loop` |
| `scripts/find_plan.py` | Modify | `#3` add explicit-path argument as primary resolution; retain `agent/` + legacy as fallbacks |
| `tests/test_find_plan.py` | Modify | `#3` add tests for explicit-path behaviour (keep 100% coverage; existing tests stay green) |
| `.claude/settings.json` | Modify | `#4` remove dead `Bash(gh pr ...)` permissions; add GitHub MCP PR/merge/subscribe tools to `allow` |
| `docs/PROJECT_CONTEXT.md` | Modify | `#2/3` update Branching rule (line ~16) and the "Git branching workflow" Known Gotcha (line ~234) for the web harness |
| `AGENTS.md` | Modify | `#2/3` update "Branching -- never edit or commit on main" guidance text; `#4` update "Merge protocol" section |
| `docs/DECISIONS.md` | Modify | Add Decision 74 recording the migration; amends Decisions 72 (clause 4) and 23 (slug derivation) -- resolves the three NOTE decision flags |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] Planning agent is pinned to Opus 1M: `model: opus[1m]` appears in both `.claude/commands/plan.md` frontmatter and `.claude/skills/planning/SKILL.md` frontmatter; `.claude/skills/implement/SKILL.md` still reads `model: sonnet`.
- [ ] No `agent/{slug}` branch ceremony remains in `plan.md` or `planning/SKILL.md`; the planning workflow writes `docs/plans/PLAN-{slug}.md` on the current (harness) branch and merges it to main.
- [ ] `plan.md` Step 12 emits a copy-paste handoff naming the explicit plan path (`/implement docs/plans/PLAN-{slug}.md`).
- [ ] `/implement` resolves the plan from its `$ARGUMENTS` path; `find_plan.py` returns an explicitly-passed path and still passes its existing test suite.
- [ ] `.claude/skills/implement/SKILL.md` Commit Flows contain zero `gh pr`, zero `sleep 300`, zero `/loop`; they use `mcp__github__create_pull_request`, `subscribe_pr_activity`, `merge_pull_request`.
- [ ] `.claude/settings.json` is valid JSON, contains no `gh pr` allow entries, and lists the GitHub MCP PR/merge/subscribe tools.
- [ ] `docs/DECISIONS.md` has a new Decision (next free number, drafted as 74) amending Decisions 72 and 23.
- [ ] `bin/venv-python -m scripts.validate --pre` exits 0.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | find_plan.py honours an explicit path | `bin/venv-python scripts/find_plan.py docs/plans/PLAN-web-workflow-migration.md` | Prints `docs/plans/PLAN-web-workflow-migration.md` (the passed path) | Explicit-path branch not wired; add it to `find_plan_file()` + `main()` |
| 2 | pre-deploy | find_plan.py reports a missing explicit path | `bin/venv-python scripts/find_plan.py docs/plans/PLAN-does-not-exist.md` | Prints `NOT_FOUND` | Missing-path case silently falls back; make explicit-but-missing return None |
| 3 | pre-deploy | find_plan tests pass at 100% | `bin/venv-python -m pytest tests/test_find_plan.py -q` | All tests pass (old + new) | Fix logic or tests until green |
| 4 | pre-deploy | Planning pinned to Opus 1M, implement stays sonnet | `grep -l "model: opus\[1m\]" .claude/commands/plan.md .claude/skills/planning/SKILL.md && grep -q "model: sonnet" .claude/skills/implement/SKILL.md && echo OK` | Both planning files listed, then `OK` | Apply the frontmatter edits |
| 5 | pre-deploy | No `gh`/`sleep`/`loop` left in the implement workflow | `! grep -rEn "gh pr|sleep 300|/loop" .claude/skills/implement/SKILL.md .claude/commands/implement.md` | Command succeeds (no matches) | Remove the remaining legacy command(s) |
| 6 | pre-deploy | MCP event-driven flow is present | `grep -Eq "subscribe_pr_activity" .claude/skills/implement/SKILL.md && grep -Eq "merge_pull_request" .claude/skills/implement/SKILL.md && echo OK` | Prints `OK` | Add the MCP commit-flow text |
| 7 | pre-deploy | settings.json valid + gh removed | `bin/venv-python -m json.tool .claude/settings.json >/dev/null && [ "$(grep -c 'gh pr' .claude/settings.json)" = "0" ] && echo OK` | Prints `OK` | Fix JSON / remove gh entries |
| 8 | pre-deploy | Decision entry added | `grep -Eq "^## Decision 7[0-9]: Claude-Code-on-the-Web Workflow Migration" docs/DECISIONS.md && echo OK` | Prints `OK` | Add the Decision 74 entry |
| 9 | pre-deploy | Handoff + branch-flow language landed in plan.md | `grep -q "/implement docs/plans/PLAN-" .claude/commands/plan.md && ! grep -q "git checkout -b agent/" .claude/commands/plan.md && echo OK` | Prints `OK` | Rewrite Steps 7/12 |
| 10 | pre-deploy | Full fast-tier gate (the PR-CI tier) passes | `bin/venv-python -m scripts.validate --pre` | Exit 0 ("validate --pre: PASS") | Fix whatever the gate reports |

## Constraints
- IMPLEMENTATION type only (Decision 67 -- STRATEGIC suspended during the executor freeze).
- Do NOT touch executor machinery or the frozen legacy surfaces: `scripts/execute_recommendation.py`, `scripts/executor/*`, `scripts/session_postflight.py`, `.github/prompts/*`, `.github/agents/*`, `.agents/*` (Decision 44 self-modification boundary; Decision 67 freeze; AGENTS.md deep-freeze rule).
- Do NOT enable GitHub branch protection / native auto-merge in this plan (CD.20 deferred). It is documented as the follow-up robustness ceiling only.
- Squash-merge policy is preserved (Decision 72 clause 4); only the transport changes (gh CLI -> GitHub MCP). Record this as an amendment in Decision 74, do not silently drop it.
- Never `Edit`/`Write` the `logs/.decisions-index.jsonl` cache directly -- author the decision in `docs/DECISIONS.md` (the ETL source) per the warehouse invariant.
- No rescue agents or workaround loops (Decision 55): the event-driven `subscribe_pr_activity` flow and reliance on ci-rca for post-merge failures replace polling; do not reintroduce a poll loop "just in case".
- No emojis; ASCII hyphens only; line length 127; `bin/venv-python` not `python`.

## Context
- **Decisions this plan cites:** 72 (branch protection unavailable on the then-private repo; CI as merge gate; squash-merge clause 4; line 489 anticipates the public-repo migration), 73 (two-tier diff-aware CI with forward-fix: fast `--pre` PR tier + full tier on main + ci-rca on failure), 60 (origin of the two-tier `--pre`/full split), 67 (IMPLEMENTATION-only during freeze), 44 (executor self-modification boundary), 23 (parallel workflow with branch-specific plans -- being amended), 25 (git worktrees -- local-dev-only, unaffected), 55 (RCA-first, no workaround loops). CD.20 (security/branch-protection gate, deferred) and CD.21 (GitHub-hosted runners, retired the self-hosted runner of Decision 68) are ROADMAP-PLATFORM.yaml candidate-decisions cited operationally from AGENTS.md -- reference them from there, not as numbered Decisions.
- **Decision flags (all NOTE, accepted -- resolved by the Decision 74 entry):** (1) Decision 72 clause 4 names `gh pr merge --squash`; we swap transport to MCP `merge_pull_request(squash)`, policy preserved. (2) Decision 23 derived slug from branch name; we decouple them, anti-contamination now via per-session auto-branches. (3) Decision 25 references `agent/{slug}` worktrees; local-dev-only, surfaced not edited.
- **CI ground truth (`.github/workflows/ci.yml`):** `pull_request` -> `pr-validate` job runs `validate --pre` (ruff/mypy/pytest-picked/prompt checks) + `terraform-validate`; both fast (~1-3 min). `push` to main -> `main-validate` runs the full tier (DQ runner, verifier harness, OIDC), 18-50 min, post-merge only. So the merge-gating PR CI is the fast tier; the slow tier is a post-merge safety net backed by ci-rca.
- **Why the old flow stranded branches:** it opened a PR and ended the turn WITHOUT subscribing to PR activity, so nothing woke the hibernated container. `subscribe_pr_activity` is the missing primitive; it is the harness-sanctioned, event-driven alternative to heartbeats. `/loop` (a fixed-interval timer) and `Bash sleep` are explicitly the wrong tools here.
- **Model-override caveat (verify at implement time):** per Claude Code docs a skill/command `model:` override applies "for the rest of the current turn" and reverts on the next prompt. Setting it on both `plan.md` and `planning/SKILL.md` is strictly better than today (which already runs Opus via the skill). If multi-turn revert is observed, the documented fallback is `/model opus[1m]` at session start; capture this in the plan.md note text rather than engineering around it.
- **Validation safety:** `validate.py`'s prompt-compliance gate only scans `.github/prompts/*.prompt.md` and only runs the retro-lite check (never `check_plan_compliance`), so editing the `branch_creation` invariant in `.claude/skills/planning/SKILL.md` does NOT affect CI (verified in `scripts/validate.py:514-555`).
- **Out-of-scope landmine (follow-up, do not fix here):** `scripts/session_postflight.py:run_push()` is gh+`time.sleep`-poll based and non-functional on the web, but it is only reachable via executor/automation paths frozen under Decision 67. File a follow-up rec to rewrite or retire it; do not touch it in this plan.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (you are on the harness session branch; do not create an `agent/` branch)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (confirm next free Decision number; this plan assumes 74)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **`scripts/find_plan.py`** -- add explicit-path resolution as the primary path.
   - Change `find_plan_file()` signature to `find_plan_file(explicit: str | None = None) -> Path | None`.
   - If `explicit` is provided: return `Path(explicit)` if it exists, else `None` (an explicit-but-missing request must NOT silently fall back to legacy).
   - If `explicit` is `None`: keep the existing behaviour unchanged (branch starts with `agent/` -> `PLAN-{slug}.md`; else legacy `PLAN.md`; else `None`). This preserves backward compatibility for local-dev `agent/` branches.
   - In `main()`: read an optional positional arg (`sys.argv[1]` if present) and pass it to `find_plan_file()`. Keep the `NOT_FOUND`/path print contract and `exit 0`.

2. **`tests/test_find_plan.py`** -- add coverage for the new behaviour (do not weaken existing tests).
   - Add: explicit path that exists -> returns that `Path`.
   - Add: explicit path that does not exist -> returns `None`.
   - Add: `main()` with an explicit-path argv that exists -> prints the path; with one that does not -> prints `NOT_FOUND`. Patch `find_plan.sys.argv` or call `find_plan_file(explicit=...)` directly, consistent with the existing `patch("find_plan.ROOT", ...)` style.
   - Run `ruff check --fix tests/test_find_plan.py` and confirm `bin/venv-python -m pytest tests/test_find_plan.py -q` is green at 100% coverage (per tests/CLAUDE.md coverage policy).

3. **`.claude/skills/planning/SKILL.md`** -- model, invariants, branch section, template, confirmation messages.
   - Frontmatter: `model: opus` -> `model: opus[1m]`.
   - Behavioural Invariants block: change `branch_creation: true # must create agent/{slug} branch before writing plan` to `harness_branch: true # work on the harness-assigned session branch; do NOT create agent/ branches`. (Cosmetic for CI -- not gated -- but keep it honest.) Leave `never_on_main`, `decision_scout_gate`, `critique_gate`, `preflight_run` as-is.
   - "## Create Branch (Workflow Step 7)" section: replace the `agent/{slug}` filename-derivation prose with: the planning agent works on the harness-assigned session branch (e.g. `claude/...`); it does NOT create an `agent/` branch. The plan filename slug is derived from the task, independent of the branch name. The plan is written, committed, and then merged to `main` so a fresh `/implement` session can read it by path.
   - PLAN template: replace the `## Branch` / `agent/{slug}` field with `## Plan Path` / `docs/plans/PLAN-{slug}.md`.
   - "## Confirmation Messages (Workflow Step 12)": rewrite all three (IMPLEMENTATION/STRATEGIC/REPORT-ONLY) to state the plan is merged to `main` and to instruct the human to open a NEW session and paste `/implement docs/plans/PLAN-{slug}.md` (explicit path). REPORT-ONLY keeps "no `/implement` required".

4. **`.claude/commands/plan.md`** -- frontmatter, Step 7, plan->main merge, Step 12.
   - Frontmatter: add `model: opus[1m]` (keep `description`). Add a one-line note in Step 1 (or a short preamble) that the planning agent should be on Opus 1M, and if the model indicator does not show it, run `/model opus[1m]` (documents the per-turn-revert fallback).
   - Step 7 "Create Branch": replace the `git checkout main && git pull && git checkout -b agent/{slug}` block with: confirm you are on the harness session branch and NOT on `main` (`git branch --show-current`); do NOT create an `agent/` branch; derive a task slug for the plan filename.
   - Step 8 stays (write + commit the plan to the current branch), but add an explicit "merge plan to main" step after the critique gates (see Step 11 below): open a PR via GitHub MCP, wait for the fast PR CI via `subscribe_pr_activity`, squash-merge via `merge_pull_request`. (Cross-reference the implement skill's Commit-Flow text so the mechanism is defined once.)
   - Step 12 "Confirm": emit the handoff block:
     ```
     Planning complete. The plan is merged to main at docs/plans/PLAN-{slug}.md.
     To implement, open a NEW Claude Code session and paste:

         /implement docs/plans/PLAN-{slug}.md

     Summary: {one line on what the plan does}.
     ```
     Keep the telemetry `session_postflight --close-session` call.

5. **`.claude/commands/implement.md`** -- argument, Step 2, Step 7.
   - Frontmatter: add `argument-hint: [docs/plans/PLAN-slug.md]`.
   - Step 2 "Load PLAN File": the plan path is provided as `$ARGUMENTS` from the handoff. If an argument is given, use it directly (verify it exists with `find_plan.py <path>` or a file check). If no argument, fall back to `bin/venv-python scripts/find_plan.py` and, if still `NOT_FOUND`, list `docs/plans/PLAN-*.md` and ask the human which. Remove the "branch slug -> PLAN-{slug}.md" derivation as the primary mechanism (keep it only as the no-arg fallback via find_plan.py). Keep "if branch is main, STOP" and "if no plan, STOP".
   - Step 7 wording: point at the rewritten Commit Flow (MCP-based); remove any implication that `gh` is used.

6. **`.claude/skills/implement/SKILL.md`** -- rewrite "## Commit Flows" (current lines ~187-240).
   - Replace the entire section with the GitHub-MCP + `subscribe_pr_activity` flow below. Delete every `gh pr ...` line, the `/loop 5m` line, and the `Bash ... sleep 300` line. Keep the Pre-Push Rebase guidance (it is git, not gh).
   - Drop-in replacement text:
     ```markdown
     ## Commit Flows (Workflow Step 7 -- MANDATORY)
     **Once validation passes (Step 6), execute the appropriate commit flow autonomously. Do not stop to ask permission -- the plan was approved during /plan.**

     This workflow runs on Claude Code on the web: the harness assigned this session its own branch (e.g. `claude/...`), the `gh` CLI is NOT available, and the container hibernates between turns. All GitHub operations use the GitHub MCP tools (`mcp__github__*`). Squash-merge after CI passes is preserved policy (Decision 72 clause 4); the transport is now the GitHub MCP `merge_pull_request` tool (Decision 74).

     ### Wait-for-CI: event-driven, never polled
     The PR-tier CI is the fast `--pre` tier (ruff/mypy/pytest-picked/prompt checks + terraform validate, ~1-3 min; Decision 73). Wait for it via subscription, NOT polling:
     1. `mcp__github__subscribe_pr_activity(owner, repo, pullNumber)`.
     2. **End your turn.** Do NOT `Bash sleep`, do NOT `/loop`, do NOT poll -- the harness forbids busy-waiting on external events and a timer keeps the container awake for nothing. CI completion arrives as a `<github-webhook-activity>` event that WAKES this session.
     3. On wake, confirm status (`mcp__github__pull_request_read` with `method=get_status` or `get_check_runs`):
        - **All green** -> `mcp__github__merge_pull_request(owner, repo, pullNumber, merge_method="squash")`, then `mcp__github__unsubscribe_pr_activity(...)`. Report the merge.
        - **Any red** -> diagnose, fix on this branch, commit, push (re-triggers PR CI). Stay subscribed and end the turn. Do NOT inline-patch around a structural failure (Decision 55); if it is a recurring gap, run RCA (Step 8).
        - **Still running** -> end the turn; a later event wakes you.

     The slow full tier runs post-merge on `main` (Decision 73); on failure the ci-rca agent files a `priority=critical`, `source=ci_rca` rec that hard-blocks the next planning session. You do not babysit main CI.

     Robustness note: a genuinely lost webhook leaves the PR open (safe). The bulletproof upgrade is GitHub-native auto-merge (server-side merge on green, container fully out of the loop); unblocked now the repo is public but needs branch protection + required status checks (CD.20, deferred). See Decision 74.

     ### Pre-Push Rebase (applies to both flows)
     After the local commit, before pushing, refresh and rebase so the PR opens against current main:
     ```bash
     git fetch origin main
     git rebase origin/main   # STOP on conflict; do not auto-resolve -- surface to the human
     ```
     If the branch was pushed earlier in the session, the post-rebase push uses `--force-with-lease` (never `--force`).

     ### IMPLEMENTATION Commit Flow
     ```bash
     git add -A
     git commit -m "feat({slug}): implement {brief-description}"
     git fetch origin main
     git rebase origin/main   # STOP on conflict
     git push -u origin HEAD   # this session's harness branch
     ```
     Then via GitHub MCP (owner/repo from `git remote get-url origin`):
     1. `mcp__github__create_pull_request(owner, repo, head=<this branch>, base="main", title="feat({slug}): {brief-description}", body="Implemented by /implement. Verification plan passed.")`
     2. `mcp__github__subscribe_pr_activity(...)`; end the turn (see "Wait-for-CI").
     3. On green wake: `mcp__github__merge_pull_request(..., merge_method="squash")` + `unsubscribe_pr_activity`.

     ### STRATEGIC Commit Flow
     STRATEGIC plans are suspended (Decision 67). When restored, use the same MCP PR/subscribe/merge pattern, committing `docs/plans/briefings/` with a `scope({slug}): ...` message.
     ```

7. **`.claude/settings.json`** -- permissions.
   - Remove the five `Bash(gh pr ...)` entries (`gh pr create`, `gh pr view`, `gh pr list`, `gh pr checks`, `gh pr merge`) and `Bash(gh api:*)` (dead on web).
   - Add to `allow`: `mcp__github__create_pull_request`, `mcp__github__merge_pull_request`, `mcp__github__subscribe_pr_activity`, `mcp__github__unsubscribe_pr_activity`, `mcp__github__pull_request_read`, `mcp__github__update_pull_request_branch`.
   - Validate JSON parses (`bin/venv-python -m json.tool .claude/settings.json`).

8. **`docs/PROJECT_CONTEXT.md`** -- branching guidance.
   - Line ~16 "Branching: All agent work uses `agent/{phase}-{slug}` branches...": replace with the web-harness model -- agents work on the harness-assigned session branch; never commit directly to `main`; plans are merged to main and handed off by path.
   - Line ~234 Known Gotcha "Git branching workflow: One branch, one PR at a time. Checkout main and pull before creating a new branch...": replace with the web reality -- the harness creates the session branch; do not create `agent/` branches; merge via GitHub MCP PR; no local `gh`.
   - Do not rewrite the whole file; touch only these two anchors.

9. **`AGENTS.md`** -- branching + merge protocol.
   - "Branching -- never edit or commit on `main`" section: keep the hard rule and the `never_on_main.py` hook reference (still valid). Replace the "Create a working branch: `git checkout main && git pull && git checkout -b agent/{slug}`" guidance with: on the web you are already on a harness session branch; verify with `git branch --show-current`; do not create `agent/` branches.
   - "Merge protocol" section: update to reflect GitHub MCP + event-driven `subscribe_pr_activity` (no `gh`), the fast PR tier as the pre-merge gate, and the full tier as the post-merge safety net (ci-rca). Cite Decision 74.

10. **`docs/DECISIONS.md`** -- add the migration decision (confirm the next free number against `origin/main`; this plan drafts it as 74). Insert near the top (file is newest-first):
    ```markdown
    ## Decision 74: Claude-Code-on-the-Web Workflow Migration for /plan and /implement (Decided)

    **Context:** `/plan` and `/implement` were authored for local dev (Windows + Git Bash): `agent/{slug}` branches, slug derived from branch name, merge via `gh` CLI with a `sleep`/`/loop` poll for CI. On Claude Code on the web the harness auto-creates a per-session branch (`claude/...`), `gh` is unavailable, and the container hibernates between turns -- a turn that ends while polling never resumes, stranding branches.

    **Decision:**
    1. Model: planning agent pinned to `opus[1m]` (Opus, 1M context); implement agent stays `sonnet`.
    2. Branches: the `agent/{slug}` ceremony is removed. Agents work on the harness session branch; the plan slug is derived from the task, independent of the branch name.
    3. Handoff: the planning agent merges `PLAN-{slug}.md` to `main` (PR -> fast PR-tier CI -> squash-merge via GitHub MCP) and emits a copy-paste handoff (`/implement docs/plans/PLAN-{slug}.md`); a fresh `/implement` session reads the plan from main by explicit path.
    4. PR/merge: all GitHub ops use the GitHub MCP tools; waiting for CI is event-driven via `subscribe_pr_activity` (end the turn; the webhook wakes the session), never `sleep`/`/loop`.

    **Amends:**
    - Decision 72 clause 4 (`gh pr merge --squash` after CI): squash-merge policy preserved; transport changes to GitHub MCP `merge_pull_request(merge_method="squash")` because `gh` is unavailable on the web harness.
    - Decision 23 ("slug derived from branch name"): slug is decoupled from the branch; the anti-contamination intent (one tracked plan per unit of work, branched from main) is satisfied by the harness per-session auto-branch model.

    **Unaffected:** Decision 25 (git worktrees) is a local-dev affordance, unchanged on the web surface. Decisions 60/73 (two-tier CI, forward-fix) govern the tiers this flow waits on. Decision 67 keeps plans IMPLEMENTATION-type. Decision 44 keeps executor machinery out of scope.

    **Deferred follow-up:** GitHub-native auto-merge (container fully out of the merge loop) is the robustness ceiling for the lost-webhook case; unblocked now the repo is public (reversing Decision 72's "permanently unavailable" premise) but needs branch protection + required status checks (CD.20, deferred).

    **Related:** Decision 72, 73, 60, 67, 44, 23, 25, 55; CD.20, CD.21.
    ```
   - Author only in `docs/DECISIONS.md` (the ETL source). Do NOT edit `logs/.decisions-index.jsonl`.

11. **Get this plan + changes onto main and hand off** (demonstrates the new flow). After Steps 1-10 land and pass verification + code review: commit on this branch, open a PR via GitHub MCP, `subscribe_pr_activity`, end the turn; on green, squash-merge via `merge_pull_request`. (This is the very flow being authored -- dogfood it.)

12. **Execute Verification Plan** -- run every VP step above; loop until all PASS. Produce the VP compliance table.

13. **Report** -- files changed, VP outcomes, code-review findings fixed, the follow-up rec filed for `session_postflight.py:run_push()`.
