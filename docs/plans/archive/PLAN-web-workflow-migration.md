# Plan

## Intent
Migrate the interactive `/plan` and `/implement` workflows from their local-dev (Windows + Git Bash, `agent/{slug}` branches, `gh` CLI) assumptions to the Claude-Code-on-the-web harness, and establish `.claude/` as the canonical interactive-workflow layer now that the project has migrated off Antigravity. Keeps the self-improvement loop (plan -> implement -> merge) operable on the platform the human actually uses.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Plan Path
docs/plans/PLAN-web-workflow-migration.md

(Authored on this session's harness-assigned branch `claude/dazzling-allen-NjdEH` -- no `agent/` branch was created. This plan is the first artefact produced under the new flow it specifies.)

## Phase
Phase Platform / workflow tooling (instruction-architecture Layers 3-4: `.claude/commands/*` + `.claude/skills/*`). Not a product/platform roadmap tier_item; this is `user_explicit_out_of_scope` workflow infrastructure requested directly by the human.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.claude/skills/planning/SKILL.md` | Modify | `#1` pin `opus[1m]`; `#2/3` relax `branch_creation` invariant, rewrite "Create Branch", PLAN template `## Branch`->`## Plan Path`, rewrite Confirmation Messages to the handoff format |
| `.claude/commands/plan.md` | Modify | `#1` add `model: opus[1m]` frontmatter + per-turn-revert note; `#2/3` rewrite Step 7 (no `agent/` branch), add plan->main merge step, rewrite Step 12 handoff message |
| `.claude/commands/implement.md` | Modify | `#3` add `argument-hint` frontmatter + accept plan path as `$ARGUMENTS` in Step 2; `#4` Step 7 wording (MCP, no `gh`) |
| `.claude/skills/implement/SKILL.md` | Modify | `#4` rewrite Commit Flows: GitHub MCP + `subscribe_pr_activity`; delete all `gh pr` and `sleep 300`/`/loop` |
| `scripts/find_plan.py` | Modify | `#3` add explicit-path argument as primary resolution; retain `agent/` + legacy as fallbacks |
| `tests/test_find_plan.py` | Modify | `#3` add tests for explicit-path behaviour (keep 100% coverage; existing tests stay green) |
| `.claude/settings.json` | Modify | `#4` remove dead `Bash(gh pr ...)` + `Bash(gh api:*)` permissions; add GitHub MCP PR/merge/subscribe tools to `allow` |
| `docs/PROJECT_CONTEXT.md` | Modify | `#2/3` Branching rule (line ~16) + "Git branching workflow" Known Gotcha (line ~234); canonical promotion: File Router lines ~147-150 point at `.claude/` not `.agents/`/`.github/prompts` |
| `AGENTS.md` | Modify | `#2/3` update "Create a working branch" guidance (line ~31); `#4` add `subscribe_pr_activity`/MCP event-driven flow + Decision 76 cite to "Merge protocol" |
| `docs/contracts/instruction-architecture.md` | Modify | Canonical promotion: name `.claude/` as the canonical interactive-workflow layer (Layers 3-4); demote `.agents/` to legacy alongside `.github/` |
| `docs/DECISIONS.md` | Modify | Add Decision 76 (next free number; verified) recording the migration + canonical promotion; amends Decision 72 (Branch Protection) clause 4 and Decision 23; supersedes Decision 58 |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] Planning pinned to Opus 1M: `model: opus[1m]` in both `.claude/commands/plan.md` and `.claude/skills/planning/SKILL.md` frontmatter; `.claude/skills/implement/SKILL.md` still `model: sonnet`.
- [ ] No `agent/{slug}` branch ceremony remains in `plan.md` or `planning/SKILL.md`; the planning workflow writes `docs/plans/PLAN-{slug}.md` on the harness branch and merges it to main.
- [ ] `plan.md` Step 12 emits a copy-paste handoff naming the explicit plan path (`/implement docs/plans/PLAN-{slug}.md`).
- [ ] `/implement` resolves the plan from its `$ARGUMENTS` path; `find_plan.py` returns an explicitly-passed path and still passes its existing test suite at 100% coverage.
- [ ] `.claude/skills/implement/SKILL.md` Commit Flows contain zero `gh pr`, zero `sleep 300`, zero `/loop`; they use `mcp__github__create_pull_request`, `subscribe_pr_activity`, `merge_pull_request`.
- [ ] `.claude/settings.json` is valid JSON, contains no `gh pr` allow entries, and lists the GitHub MCP PR/merge/subscribe tools.
- [ ] `docs/contracts/instruction-architecture.md` names `.claude/` as the canonical interactive-workflow layer; `.agents/` is designated legacy.
- [ ] `docs/DECISIONS.md` has a new entry `## Decision 76: Claude-Code-on-the-Web Workflow Migration ...` amending Decisions 72 (Branch Protection) and 23, and superseding Decision 58. `logs/.decisions-index.jsonl` is NOT edited.
- [ ] Full `bin/venv-python -m scripts.validate` (not just `--pre`) exits 0 locally before the PR is opened.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | find_plan.py honours an explicit path | `bin/venv-python scripts/find_plan.py docs/plans/PLAN-web-workflow-migration.md` | Prints `docs/plans/PLAN-web-workflow-migration.md` | Wire the explicit-path branch in `find_plan_file()` + `main()` |
| 2 | pre-deploy | find_plan.py reports a missing explicit path | `bin/venv-python scripts/find_plan.py docs/plans/PLAN-does-not-exist.md` | Prints `NOT_FOUND` | Explicit-but-missing must return None, not fall back |
| 3 | pre-deploy | find_plan tests pass at 100% | `bin/venv-python -m pytest tests/test_find_plan.py -q` | All tests pass (old + new) | Fix logic or tests until green |
| 4 | pre-deploy | Planning on Opus 1M, implement on sonnet | `grep -l "model: opus\[1m\]" .claude/commands/plan.md .claude/skills/planning/SKILL.md && grep -q "model: sonnet" .claude/skills/implement/SKILL.md && echo OK` | Both planning files listed, then `OK` | Apply frontmatter edits |
| 5 | pre-deploy | No `gh`/`sleep`/`loop` in the implement workflow | `! grep -rEn "gh pr\|sleep 300\|/loop" .claude/skills/implement/SKILL.md .claude/commands/implement.md` | Succeeds (no matches) | Remove remaining legacy command(s) |
| 6 | pre-deploy | MCP event-driven flow present | `grep -q "subscribe_pr_activity" .claude/skills/implement/SKILL.md && grep -q "merge_pull_request" .claude/skills/implement/SKILL.md && echo OK` | Prints `OK` | Add the MCP commit-flow text |
| 7 | pre-deploy | settings.json valid + gh removed | `bin/venv-python -m json.tool .claude/settings.json >/dev/null && [ "$(grep -c 'gh pr' .claude/settings.json)" = "0" ] && echo OK` | Prints `OK` | Fix JSON / remove gh entries |
| 8 | pre-deploy | Decision 76 entry added (exact number) | `grep -q "^## Decision 76: Claude-Code-on-the-Web Workflow Migration" docs/DECISIONS.md && echo OK` | Prints `OK` | Add/renumber the entry to exactly 76 |
| 9 | pre-deploy | JSONL cache untouched (canonical-write safety) | `git diff --name-only origin/main...HEAD -- logs/.decisions-index.jsonl \| grep -q . && echo TOUCHED \|\| echo CLEAN` | Prints `CLEAN` | Revert any edit to the JSONL cache; author only in DECISIONS.md |
| 10 | pre-deploy | `.claude/` named canonical in the contract | `grep -q "\.claude/" docs/contracts/instruction-architecture.md && echo OK` | Prints `OK` | Update the contract Layer 3-4 designation |
| 11 | pre-deploy | Handoff + branch-flow language landed in plan.md | `grep -q "/implement docs/plans/PLAN-" .claude/commands/plan.md && ! grep -q "git checkout -b agent/" .claude/commands/plan.md && echo OK` | Prints `OK` | Rewrite Steps 7/12 |
| 12 | pre-deploy | FULL gate passes locally (manages the "fails CI if unmanaged" risk) | `bin/venv-python -m scripts.validate` | Exit 0 (full presubmit PASS) | Fix whatever the full gate reports BEFORE opening the PR |

## Constraints
- IMPLEMENTATION type only (Decision 67 -- STRATEGIC suspended during the executor freeze).
- Do NOT touch executor machinery or frozen surfaces: `scripts/execute_recommendation.py`, `scripts/executor/*`, `scripts/session_postflight.py`, `.github/prompts/*`, `.github/agents/*` (Decision 44 boundary; Decision 67 freeze; AGENTS.md deep-freeze). `.agents/*` is being demoted to legacy and is NOT edited (treated like `.github/` going forward).
- Do NOT enable GitHub branch protection / native auto-merge here (CD.20 deferred). Documented as the follow-up robustness ceiling only.
- Squash-merge policy is preserved (Decision 72 "Branch Protection Not Available", clause 4); only the transport changes (gh CLI -> GitHub MCP). Record as an amendment in Decision 76; do not silently drop it.
- Author the decision ONLY in `docs/DECISIONS.md` (the ETL source). Never `Edit`/`Write` `logs/.decisions-index.jsonl` (caught by `validate_no_direct_ops_writes` / `validate_canonical_state_writes`).
- No rescue agents or workaround loops (Decision 55): the event-driven `subscribe_pr_activity` flow replaces polling; do not reintroduce a poll loop "just in case".
- No emojis; ASCII hyphens only; line length 127; `bin/venv-python` not `python`.

## Context
- **Decisions this plan cites (numbers verified against the live file -- the earlier decision-scout mis-numbered several):** Decision 72 "GitHub Branch Protection Not Available -- CI Enforcement as the Only Merge Gate" (line ~470; clause 4 = squash via `gh pr merge --squash`; line ~489 literally anticipates this work: "Any future migration to ... a public repository would unlock required_status_checks and should be revisited"), Decision 73 "Two-Tier Diff-Aware CI with Forward-Fix" (line ~97; fast `--pre` PR tier + full tier on main + ci-rca on failure), Decision 60 (origin of the two-tier split), Decision 67 (IMPLEMENTATION-only during freeze), Decision 44 (executor self-modification boundary), Decision 23 "Parallel Workflow with Branch-Specific Plans" (line ~1400; being amended), Decision 25 (git worktrees -- local-dev-only, unaffected), Decision 58 "`.agents` as Canonical Interactive Workflow Layer" (line ~358; being superseded), Decision 55 (RCA-first, no workaround loops). CD.20/CD.21 are ROADMAP-PLATFORM.yaml candidate-decisions cited operationally from AGENTS.md.
- **Pre-existing repo data issue (NOT fixed here; cite-by-title to disambiguate):** `docs/DECISIONS.md` contains TWO entries numbered "Decision 72" (line ~159 "RCA-as-Plan-Source for CI Merge Gate Failures" and line ~470 "GitHub Branch Protection Not Available"). This plan cites the line-470 one by its full title. A separate cleanup rec should be filed to renumber the duplicate; out of scope here.
- **Decision flags from the scout (all NOTE, accepted -- resolved by the Decision 76 entry):** (1) Decision 72 (Branch Protection) clause 4 names `gh pr merge --squash`; we swap transport to MCP `merge_pull_request(squash)`, policy preserved. (2) Decision 23 derived slug from branch name; we decouple it, anti-contamination now via per-session auto-branches. (3) Decision 25 references `agent/{slug}` worktrees; local-dev-only, surfaced not edited.
- **Canonical promotion (human decision):** the human chose to promote `.claude/` to the canonical interactive-workflow layer, superseding Decision 58 (which named `.agents/` canonical and predates the Claude migration). `.agents/` is demoted to legacy like `.github/`; it is NOT synced and may remain stale by design (no drift obligation once it is legacy). Optional follow-up: add one-line deprecation shims atop `.agents/workflows/{plan,implement}.md` pointing to `.claude/` -- listed as a follow-up rec, not in this plan's scope.
- **CI-failure management (the human's explicit caveat):** traced the enforcement surface. `validate.py` has NO check on `.agents/`, `.claude/` content, the instruction-architecture contract, or `docs/DECISIONS.md` markdown (`grep -c "DECISIONS\|instruction-architecture\|contract" scripts/validate.py` == 0). `validate_decisions_schema` validates `logs/.decisions-index.jsonl` (the cache), not the markdown -- so a markdown-only decision entry is CI-safe provided the JSONL cache is untouched (VP step 9). The model frontmatter is not CI-validated (`KNOWN_MODELS` scans only `.github/prompts/`). The ONE residual risk: the PR gate runs only `--pre` (fast tier), so any full-tier issue would surface post-merge on main as a ci-rca rec -- mitigated by running FULL `validate.py` locally before the PR (VP step 12).
- **CI ground truth (`.github/workflows/ci.yml`):** `pull_request` -> `pr-validate` (`validate --pre`) + `terraform-validate`, both ~1-3 min. `push` to main -> `main-validate` (full tier: DQ runner, verifier harness, OIDC), 18-50 min, post-merge only. The merge-gating PR CI is the fast tier; the slow tier is a post-merge safety net backed by ci-rca.
- **Why the old flow stranded branches:** it opened a PR and ended the turn WITHOUT subscribing, so nothing woke the hibernated container. `subscribe_pr_activity` is the missing primitive -- the harness-sanctioned, event-driven alternative to heartbeats. `/loop` (fixed-interval timer) and `Bash sleep` are the wrong tools.
- **Frame-Challenge self-check (Decision 75):** this plan is itself the kind of artefact Decision 75's Frame-Challenge phase evaluates; the chosen `subscribe_pr_activity` primitive (a native capability) over a custom poller is the frame-correct outcome, and it re-examines the now-stale Decision 72 "branch protection permanently unavailable" premise (false now the repo is public).
- **Model-override caveat (verify at implement time):** per Claude Code docs a skill/command `model:` override applies "for the rest of the current turn" and reverts next prompt. Setting it on both `plan.md` and `planning/SKILL.md` is strictly better than today. If multi-turn revert is observed, the documented fallback is `/model opus[1m]` at session start; capture this in the plan.md note text.
- **Validation safety (find_plan + invariants):** `validate.py`'s prompt-compliance gate scans only `.github/prompts/*.prompt.md` and runs only the retro-lite check (never `check_plan_compliance`), so editing the `branch_creation` invariant in `.claude/skills/planning/SKILL.md` does NOT affect CI (verified `scripts/validate.py:514-555`).
- **Out-of-scope landmine (follow-up rec, do not fix here):** `scripts/session_postflight.py:run_push()` is gh+`time.sleep`-poll based and non-functional on the web, but only reachable via executor/automation paths frozen under Decision 67.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (you are on the harness session branch; do not create an `agent/` branch)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read; confirm 76 is still the next free number against `origin/main` (75 and 74 already exist; adjust if main moved)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **`scripts/find_plan.py`** -- add explicit-path resolution as the primary path.
   - Change `find_plan_file()` to `find_plan_file(explicit: str | None = None) -> Path | None`.
   - If `explicit` is provided: return `Path(explicit)` if it exists, else `None` (an explicit-but-missing request must NOT silently fall back to legacy).
   - If `explicit` is `None`: keep existing behaviour unchanged (branch `agent/` -> `PLAN-{slug}.md`; else legacy `PLAN.md`; else `None`). Preserves backward compatibility for local-dev `agent/` branches.
   - In `main()`: read optional positional arg (`sys.argv[1]` if present) and pass it to `find_plan_file()`. Keep the `NOT_FOUND`/path print contract and `exit 0`.

2. **`tests/test_find_plan.py`** -- add coverage for the new behaviour (do not weaken existing tests).
   - Add: explicit path that exists -> returns that `Path`; explicit path that does not exist -> returns `None`; `main()` with explicit-path argv (exists -> prints path; missing -> `NOT_FOUND`). Follow the existing `patch("find_plan.subprocess.run", ...)` + `patch("find_plan.ROOT", ...)` style; patch `find_plan.sys.argv` for the CLI cases.
   - `ruff check --fix tests/test_find_plan.py`; confirm `bin/venv-python -m pytest tests/test_find_plan.py -q` green at 100% coverage (tests/CLAUDE.md policy).

3. **`.claude/skills/planning/SKILL.md`** -- model, invariants, branch section, template, confirmation messages.
   - Frontmatter: `model: opus` -> `model: opus[1m]`.
   - Behavioural Invariants: change `branch_creation: true # must create agent/{slug} branch before writing plan` to `harness_branch: true # work on the harness-assigned session branch; do NOT create agent/ branches`. Leave the other invariants.
   - "## Create Branch (Workflow Step 7)": replace the `agent/{slug}` filename-derivation prose with: the planning agent works on the harness session branch (e.g. `claude/...`), does NOT create an `agent/` branch, derives the plan slug from the task (independent of branch name), and merges the plan to `main` so a fresh `/implement` session reads it by path.
   - PLAN template: replace the `## Branch` / `agent/{slug}` field with `## Plan Path` / `docs/plans/PLAN-{slug}.md`.
   - "## Confirmation Messages (Workflow Step 12)": rewrite all three variants to state the plan is merged to `main` and instruct the human to open a NEW session and paste `/implement docs/plans/PLAN-{slug}.md` (explicit path). REPORT-ONLY keeps "no `/implement` required".

4. **`.claude/commands/plan.md`** -- frontmatter, Step 7, plan->main merge, Step 12.
   - Frontmatter: add `model: opus[1m]` (keep `description`). Add a one-line note in Step 1 that the planning agent should be on Opus 1M; if the model indicator does not show it, run `/model opus[1m]` (documents the per-turn-revert fallback).
   - Step 7 "Create Branch": replace `git checkout main && git pull && git checkout -b agent/{slug}` with: confirm you are on the harness session branch and NOT on `main` (`git branch --show-current`); do NOT create an `agent/` branch; derive a task slug for the plan filename.
   - After the critique gates, add a "merge plan to main" step: open a PR via GitHub MCP, wait for the fast PR CI via `subscribe_pr_activity`, squash-merge via `merge_pull_request` (cross-reference the implement skill's Commit-Flow text so the mechanism is defined once).
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
   - Step 2 "Load PLAN File": the plan path is provided as `$ARGUMENTS` from the handoff. If an argument is given, use it directly (verify via `bin/venv-python scripts/find_plan.py <path>`). If no argument, fall back to `bin/venv-python scripts/find_plan.py`; if still `NOT_FOUND`, list `docs/plans/PLAN-*.md` and ask the human which. Keep "if branch is main, STOP" and "if no plan, STOP". Remove branch-slug derivation as the primary mechanism (keep only as no-arg fallback via find_plan.py).
   - Step 7 wording: point at the rewritten MCP-based Commit Flow; remove any implication `gh` is used.

6. **`.claude/skills/implement/SKILL.md`** -- rewrite "## Commit Flows" (current lines ~187-240). Delete every `gh pr ...` line, the `/loop 5m` line, and the `Bash ... sleep 300` line. Keep the Pre-Push Rebase (git, not gh). Drop-in replacement:
   ```markdown
   ## Commit Flows (Workflow Step 7 -- MANDATORY)
   **Once validation passes (Step 6), execute the appropriate commit flow autonomously. Do not stop to ask permission -- the plan was approved during /plan.**

   This workflow runs on Claude Code on the web: the harness assigned this session its own branch (e.g. `claude/...`), the `gh` CLI is NOT available, and the container hibernates between turns. All GitHub operations use the GitHub MCP tools (`mcp__github__*`). Squash-merge after CI passes is preserved policy (Decision 72 "Branch Protection Not Available", clause 4); the transport is now the GitHub MCP `merge_pull_request` tool (Decision 76).

   ### Run the full gate locally first
   The PR gate runs ONLY the fast `--pre` tier; the full tier runs post-merge on main and a failure there spawns a ci-rca rec. To avoid a post-merge red main, run `bin/venv-python -m scripts.validate` (full, no flags) locally and get exit 0 BEFORE opening the PR.

   ### Wait-for-CI: event-driven, never polled
   The PR-tier CI is the fast `--pre` tier (ruff/mypy/pytest-picked/prompt checks + terraform validate, ~1-3 min; Decision 73). Wait for it via subscription, NOT polling:
   1. `mcp__github__subscribe_pr_activity(owner, repo, pullNumber)`.
   2. **End your turn.** Do NOT `Bash sleep`, do NOT `/loop`, do NOT poll -- the harness forbids busy-waiting on external events and a timer keeps the container awake for nothing. CI completion arrives as a `<github-webhook-activity>` event that WAKES this session.
   3. On wake, confirm status (`mcp__github__pull_request_read` with `method=get_status`/`get_check_runs`):
      - **All green** -> `mcp__github__merge_pull_request(owner, repo, pullNumber, merge_method="squash")`, then `mcp__github__unsubscribe_pr_activity(...)`. Report the merge.
      - **Any red** -> diagnose, fix on this branch, commit, push (re-triggers PR CI). Stay subscribed and end the turn. Do NOT inline-patch around a structural failure (Decision 55); if it is a recurring gap, run RCA (Step 8).
      - **Still running** -> end the turn; a later event wakes you.

   The slow full tier runs post-merge on `main` (Decision 73); on failure the ci-rca agent files a `priority=critical`, `source=ci_rca` rec that hard-blocks the next planning session. You do not babysit main CI.

   Robustness note: a genuinely lost webhook leaves the PR open (safe). The bulletproof upgrade is GitHub-native auto-merge (server-side merge on green, container fully out of the loop); unblocked now the repo is public but needs branch protection + required status checks (CD.20, deferred). See Decision 76.

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
   - Remove the five `Bash(gh pr ...)` entries and `Bash(gh api:*)` (dead on web).
   - Add to `allow`: `mcp__github__create_pull_request`, `mcp__github__merge_pull_request`, `mcp__github__subscribe_pr_activity`, `mcp__github__unsubscribe_pr_activity`, `mcp__github__pull_request_read`, `mcp__github__update_pull_request_branch`.
   - Validate JSON parses (`bin/venv-python -m json.tool .claude/settings.json`).

8. **`docs/PROJECT_CONTEXT.md`** -- branching + canonical promotion.
   - Line ~16 "Branching: All agent work uses `agent/{phase}-{slug}` branches...": replace with the web-harness model -- agents work on the harness-assigned session branch; never commit directly to `main`; plans are merged to main and handed off by path.
   - Line ~234 Known Gotcha "Git branching workflow: One branch, one PR...": replace with the web reality -- the harness creates the session branch; do not create `agent/` branches; merge via GitHub MCP PR; no local `gh`.
   - File Router lines ~147-150: repoint the "Interactive planning/implementation workflow" and "Planning entry point" rows at `.claude/commands/` + `.claude/skills/` (canonical); mark `.agents/` and `.github/prompts/` as legacy.
   - Touch only these anchors.

9. **`AGENTS.md`** -- branch guidance + merge protocol.
   - "Branching -- never edit or commit on `main`" section: keep the hard rule and the `never_on_main.py` hook reference. Replace the "Create a working branch: `git checkout main && git pull && git checkout -b agent/{slug}`" guidance (line ~31) with: on the web you are already on a harness session branch; verify with `git branch --show-current`; do not create `agent/` branches.
   - "## Merge protocol" section (line ~106, currently CD.21/`--pre` language, no gh/squash): ADD a bullet describing the web flow -- GitHub MCP PR + event-driven `subscribe_pr_activity` (no `gh`), fast PR `--pre` tier as the pre-merge gate, full tier post-merge with ci-rca; cite Decision 76. Do NOT claim to remove gh/squash text here (it is not in this section).

10. **`docs/contracts/instruction-architecture.md`** -- canonical promotion.
    - Current state (verified): this contract is already stale vs AGENTS.md. It lists only "three agent consumers (executor, Antigravity, legacy VS Code)" -- Claude Code is absent -- and names `GEMINI.md` (L1), `copilot-instructions.md` (L2), `.agents/workflows/` (L3), `.agents/skills/` (L4). AGENTS.md's "Instruction architecture" table already has the Claude-centric version (`CLAUDE.md`/`AGENTS.md` L1, `docs/PROJECT_CONTEXT.md` L2, `.claude/commands/*` L3, `.claude/skills/*` L4, "Claude Code is the 4th consumer").
    - Minimal scoped edit for THIS plan: update the canonical-designation lines (~55-57) and the Layer 3-4 + consumer-table rows so `.claude/commands/*` + `.claude/skills/*` are named the canonical interactive-workflow layer and Claude Code is listed as a consumer; demote `.agents/workflows/` + `.agents/skills/` to legacy alongside `.github/prompts/` + `.github/agents/`. Make it consistent with AGENTS.md's table.
    - Do NOT attempt the deeper L1/L2 reconciliation (GEMINI.md->CLAUDE.md, copilot-instructions.md->PROJECT_CONTEXT.md) here -- that is a larger contract rewrite filed as a follow-up rec (Step 13).

11. **`docs/DECISIONS.md`** -- add Decision 76 (confirm 76 is still next-free against `origin/main`; 75 and 74 already exist). Insert near the top (newest-first):
    ```markdown
    ## Decision 76: Claude-Code-on-the-Web Workflow Migration; .claude as Canonical Interactive Layer (Decided)

    **Status:** Decided
    **Date:** 2026-05-30

    **Context:** `/plan` and `/implement` were authored for local dev (Windows + Git Bash): `agent/{slug}` branches, slug derived from branch name, merge via `gh` CLI with a `sleep`/`/loop` poll for CI. On Claude Code on the web the harness auto-creates a per-session branch (`claude/...`), `gh` is unavailable, and the container hibernates between turns -- a turn that ends while polling never resumes, stranding branches.

    **Decision:**
    1. Model: planning agent pinned to `opus[1m]` (Opus, 1M context); implement agent stays `sonnet`.
    2. Branches: the `agent/{slug}` ceremony is removed. Agents work on the harness session branch; the plan slug is derived from the task, independent of the branch name.
    3. Handoff: the planning agent merges `PLAN-{slug}.md` to `main` (PR -> fast PR-tier CI -> squash-merge via GitHub MCP) and emits a copy-paste handoff (`/implement docs/plans/PLAN-{slug}.md`); a fresh `/implement` session reads the plan from main by explicit path.
    4. PR/merge: all GitHub ops use the GitHub MCP tools; waiting for CI is event-driven via `subscribe_pr_activity` (end the turn; the webhook wakes the session), never `sleep`/`/loop`.
    5. Canonical layer: `.claude/commands/` + `.claude/skills/` are now the canonical interactive-workflow layer.

    **Amends / Supersedes:**
    - Amends Decision 72 ("GitHub Branch Protection Not Available"), clause 4 (`gh pr merge --squash` after CI): squash-merge policy preserved; transport changes to GitHub MCP `merge_pull_request(merge_method="squash")` because `gh` is unavailable on the web harness.
    - Amends Decision 23 ("slug derived from branch name"): slug is decoupled from the branch; the anti-contamination intent (one tracked plan per unit of work, branched from main) is satisfied by the harness per-session auto-branch model.
    - Supersedes Decision 58 ("`.agents` as canonical interactive workflow layer"): `.claude/` is now canonical; `.agents/` is demoted to legacy alongside `.github/` (no sync obligation).

    **Unaffected:** Decision 25 (git worktrees) is a local-dev affordance, unchanged. Decisions 60/73 (two-tier CI, forward-fix) govern the tiers this flow waits on. Decision 67 keeps plans IMPLEMENTATION-type. Decision 44 keeps executor machinery out of scope.

    **Deferred follow-up:** GitHub-native auto-merge (container fully out of the merge loop) is the robustness ceiling for the lost-webhook case; unblocked now the repo is public (reversing Decision 72's "permanently unavailable" premise) but needs branch protection + required status checks (CD.20, deferred).

    **Related:** Decision 72 (Branch Protection), 73, 60, 67, 44, 23, 25, 58, 55; CD.20, CD.21.
    ```
    - Author ONLY in `docs/DECISIONS.md`. Do NOT edit `logs/.decisions-index.jsonl`.

12. **Execute Verification Plan** -- run every VP step (1-12); loop until all PASS. Produce the VP compliance table. VP step 12 (full `validate.py` exit 0) is the gate that manages the "fails CI if unmanaged" risk.

13. **File the follow-up recs** (via `bin/venv-python -m scripts.ops_data_portal --file-rec ...`, `automatable: false`): (a) rewrite/retire `scripts/session_postflight.py:run_push()` for the web (gh+sleep, frozen-executor-only); (b) renumber the duplicate "Decision 72" entries in `docs/DECISIONS.md`; (c) deeper reconcile `docs/contracts/instruction-architecture.md` Layers 1-2 (GEMINI.md->CLAUDE.md, copilot-instructions.md->PROJECT_CONTEXT.md) and the consumer list with the Claude reality; (d) optional `.agents/workflows/{plan,implement}.md` deprecation shims pointing to `.claude/`.

14. **Get this plan + changes onto main and hand off** (dogfood the new flow): after Steps 1-13 land and pass verification + code review, commit, open a PR via GitHub MCP, `subscribe_pr_activity`, end the turn; on green, squash-merge via `merge_pull_request`.

15. **Report** -- files changed, VP outcomes, code-review findings fixed, follow-up recs filed.
