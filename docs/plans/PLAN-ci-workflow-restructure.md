# Plan

## Intent
Land the third and final follow-on plan from Decision 73 by restructuring `.github/workflows/ci.yml` so PR CI runs the fast tier (`--pre`) and push-to-`main` CI runs the full tier exactly once (no longer a duplicate of PR CI), plus a new 3-hourly `main-canary.yml` for drift catch (L8). This unblocks the runner from being the development bottleneck and converges the INTENT-ci-cd-architecture target state for L1, L3, and L8.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
claude/fix-duplicate-ci-validation-iTl7m

> **Branch/slug deviation.** The harness-assigned branch is `claude/fix-duplicate-ci-validation-iTl7m`; the plan filename follows the INTENT cross-reference (`ci-workflow-restructure`) because that is the durable identifier referenced from `docs/INTENT-ci-cd-architecture.md` Section 2.5 and `docs/DECISIONS.md` Decision 73. `scripts/find_plan.py` will not resolve this plan from the branch name -- the `/implement` agent must be pointed at `docs/plans/PLAN-ci-workflow-restructure.md` directly. A follow-up to harden `find_plan.py` for web-container pre-assigned branches is out of scope here.

## Phase
Phase Platform (automation infrastructure) -- runs in parallel with trading-system phases per `docs/ROADMAP-PRODUCT.md`. Touches `docs/ROADMAP-PLATFORM.yaml` T2.10 (`files_in_scope` extension only; the OIDC + hosted-runner migration itself is deferred to T2.13 / public-flip).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/workflows/ci.yml` | Modify | (1) **Split the single `validate-python` job into two jobs** -- `pr-validate` (`if: github.event_name == 'pull_request'`) and `main-validate` (`if: github.event_name == 'push'`). `pr-validate` invokes `bin/venv-python -m scripts.validate --pre`; `main-validate` invokes `bin/venv-python -m scripts.validate` (full tier). (2) `pr-validate`'s `actions/checkout@v4` step sets `fetch-depth: 0` so `--pre`'s `get_changed_files()` can resolve `origin/main` (hand-off from `validate-fast-tier-reshape`); `main-validate` uses default checkout depth. (3) Add `concurrency: { group: ci-runner, cancel-in-progress: false }` to `pr-validate`, `main-validate`, and `terraform-validate`. (4) Remove the `develop` branch from `on.push.branches` -- there is no `develop` branch in active use. |
| `.github/workflows/main-canary.yml` | Create | New scheduled workflow on `[self-hosted, linux]`. Trigger: `schedule: cron: '0 */3 * * *'` (every 3 hours) plus `workflow_dispatch`. `name: Main Canary` (exact string; referenced by `ci-rca.yml`'s workflow filter). Runs `bin/venv-python -m scripts.validate` (full tier) against `main`. Declares `concurrency: { group: ci-runner, cancel-in-progress: false }` so it queues behind PR CI rather than starving it. Same Python setup, pip cache, AWS_DEFAULT_REGION env as `ci.yml`'s `main-validate` job. No special permissions beyond `contents: read`. |
| `.github/workflows/ci-rca.yml` | Modify | One-line edit: change `workflows: ["CI"]` (line 8) to `workflows: ["CI", "Main Canary"]` so a failed canary run also triggers ci-rca diagnosis. The exact string `Main Canary` must match `main-canary.yml`'s `name:` field. |
| `scripts/verify_ci_workflow.py` | Create | Small helper script invoked by VP steps 1-6. Sub-command dispatch on argv[1] (`jobs-and-flags` / `concurrency` / `fetch-depth` / `canary` / `ci-rca-filter`); each sub-command reads the relevant workflow YAML(s) and asserts the structural property described in the corresponding VP row. Exits 0 with `OK` on stdout when assertions pass; exits non-zero with the failing assertion's diagnostic on failure. Plain stdlib + `yaml`; no other dependencies. Keeps verification commands readable in the VP table rather than encoding them as multi-line `bin/venv-python -c "..."` shell strings. |
| `docs/INTENT-ci-cd-architecture.md` | Modify | (a) Section 2.5 enforcement-surface table: flip L1, L3, L8 + single-runner-concurrency rows from "UNBUILT" / "BUILT (currently duplicates PR CI)" to "BUILT (ci-workflow-restructure, 2026-05-19)". Mark L6 rows as "DEFERRED -- see Decision 73 follow-up" with one-line rationale. (b) Section 3 L8 row: change "Cron hourly, with `concurrency: ci-runner` group" to "Cron every 3 hours during sandbox-only operation, with `concurrency: ci-runner` group". (c) Section 6 (Promotion Train): add forward-looking note that L8 cadence tightens to hourly once Phase Infra-Env lands SIT, so the green-streak gate has sample granularity. (d) Section 9 single-runner concurrency paragraph: update the cadence-vs-queue math to reflect 3-hour cadence (worst-case ~16% PR-CI queue overlap vs 30%+ at hourly). (e) Section 10 "Sequencing constraint": acknowledge `ci-workflow-restructure` landed on 2026-05-19 with L6 explicitly deferred; INTENT is partially cite-as-in-force (L1/L3/L8 live; L6 still target-state). |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | T2.10 `files_in_scope` (line 1556 area): add `.github/workflows/main-canary.yml`. This ensures the OIDC + hosted-runner migration on T2.13 / public-flip also migrates the canary, not just the six existing workflows. |
| `docs/SESSION_LOG.md` | Modify | Prepend the session entry per the new Ordered Execution Step (drafted in parallel with code-review wait during `/implement`). |

Scope is 7 files. Load-bearing work is concentrated in `ci.yml`, `main-canary.yml`, and the one-line `ci-rca.yml` edit; `scripts/verify_ci_workflow.py` is a small helper that keeps the VP table readable; the three documentation files are mechanical updates that ratify the design state. Per Decision 67 STRATEGIC-plan-freeze, this stays IMPLEMENTATION.

## Bundled Recommendations
None bundled. Preflight could not query the rec queue from this web container (no AWS SSO -- accepted per the planning conversation). Adjacent CI-workflow recs may exist in the warehouse; bundling can happen on a follow-up if surfaced.

## Acceptance Criteria
- [ ] `.github/workflows/ci.yml` contains two distinct jobs `pr-validate` (gated by `if: github.event_name == 'pull_request'`) and `main-validate` (gated by `if: github.event_name == 'push'`). The previous single `validate-python` job no longer exists.
- [ ] `pr-validate` invokes `bin/venv-python -m scripts.validate --pre`; `main-validate` invokes `bin/venv-python -m scripts.validate` with no `--pre` flag.
- [ ] `pr-validate`'s `actions/checkout@v4` step sets `fetch-depth: 0`; `main-validate` does not (default depth).
- [ ] Push trigger no longer lists `develop`.
- [ ] `pr-validate`, `main-validate`, and `terraform-validate` all declare `concurrency: { group: ci-runner, cancel-in-progress: false }` at the job level.
- [ ] `.github/workflows/main-canary.yml` exists with `name: Main Canary`, `schedule: cron: '0 */3 * * *'` and `workflow_dispatch` triggers, runs on `[self-hosted, linux]`, executes the full validate tier, and declares the `concurrency: ci-runner` group.
- [ ] `.github/workflows/ci-rca.yml` line 8 reads `workflows: ["CI", "Main Canary"]` (the string `Main Canary` matches `main-canary.yml`'s `name:` field exactly).
- [ ] `docs/INTENT-ci-cd-architecture.md` Section 2.5 rows for L1, L3, L8, single-runner-concurrency are marked BUILT with the dated reference; L6 rows are marked DEFERRED with the "Owning follow-on plan" column cleared (set to `TBD -- new plan required`) so the table is internally consistent.
- [ ] `docs/INTENT-ci-cd-architecture.md` Section 3 L8 row reads "every 3 hours during sandbox-only operation".
- [ ] `docs/INTENT-ci-cd-architecture.md` Section 6 contains the L8-cadence-tightens-with-Infra-Env forward-looking note.
- [ ] `docs/INTENT-ci-cd-architecture.md` Section 9 single-runner concurrency math reflects 3-hour cadence.
- [ ] `docs/INTENT-ci-cd-architecture.md` Section 10 acknowledges `ci-workflow-restructure` landed 2026-05-19 with L6 deferred.
- [ ] `docs/ROADMAP-PLATFORM.yaml` T2.10 `files_in_scope` includes `.github/workflows/main-canary.yml`.
- [ ] `docs/SESSION_LOG.md` has a new top entry dated 2026-05-19 for this branch, drafted in parallel with the Step 5 code-review subagent wait.
- [ ] On a no-op PR pushed against this branch, only the PR-triggered fast tier runs (no duplicate full-tier run during the PR phase); after merge, exactly one full-tier run fires on push-to-main.
- [ ] `main-canary.yml` triggered manually via `workflow_dispatch` against `main` runs the full tier to completion and produces a green result.
- [ ] When PR CI and `main-canary.yml` are concurrent, GitHub Actions queues the second one (single runner) rather than running both simultaneously (verified via `gh run list` showing one job's `status: queued` while the other is `in_progress`).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | ci.yml has two jobs with correct event-gating and flag assignment | `bin/venv-python scripts/verify_ci_workflow.py jobs-and-flags` (single-purpose script created by step 1.5 of Ordered Execution Steps; reads `.github/workflows/ci.yml` and asserts: both jobs present; `validate-python` removed; `pr-validate.if == "github.event_name == 'pull_request'"`; `main-validate.if == "github.event_name == 'push'"`; `pr-validate` steps contain `--pre`; `main-validate` steps do NOT contain `--pre`) | Script exits 0 with `OK` on stdout. | Re-edit ci.yml: ensure jobs are at top level, `if:` conditions are quoted strings matching the literals above, and step `run:` lines differ in flag presence. |
| 2 | [pre-deploy] | ci.yml concurrency block present on all three jobs | `bin/venv-python scripts/verify_ci_workflow.py concurrency` (asserts all three of `pr-validate`, `main-validate`, `terraform-validate` declare `concurrency.group == 'ci-runner'` and `concurrency.cancel-in-progress is False`) | Script exits 0 with `OK`. | Add or fix the concurrency block on the named jobs at the job level (not workflow level). |
| 3 | [pre-deploy] | pr-validate has fetch-depth 0; main-validate does not | `bin/venv-python scripts/verify_ci_workflow.py fetch-depth` (asserts `pr-validate` checkout has `with.fetch-depth == 0` and `main-validate` checkout has no `with.fetch-depth` key) | Script exits 0 with `OK`. | Edit the checkout step's `with` block on `pr-validate` only. |
| 4 | [pre-deploy] | Push trigger does not list `develop`; PR trigger still targets `main` | `bin/venv-python -c "import yaml; data=yaml.safe_load(open('.github/workflows/ci.yml')); push_branches=data['on']['push']['branches']; assert 'develop' not in push_branches, f'develop still present: {push_branches}'; assert 'main' in push_branches, 'main missing'; assert 'main' in data['on']['pull_request']['branches'], 'PR target missing'; print('OK')"` | Final print `OK`. | Remove `develop` from `on.push.branches`. |
| 5 | [pre-deploy] | main-canary.yml structure check | `bin/venv-python scripts/verify_ci_workflow.py canary` (asserts `name == 'Main Canary'`; `on.schedule[0].cron == '0 */3 * * *'`; `workflow_dispatch` present; canary job's `concurrency.group == 'ci-runner'` and `cancel-in-progress is False`; `runs-on == ['self-hosted', 'linux']` (list form ONLY -- string form rejected); steps contain `scripts.validate` and do NOT contain `--pre`) | Script exits 0 with `OK`. | Re-edit main-canary.yml; the `name:` literal matters for VP step 6; `runs-on` must be the YAML list form `[self-hosted, linux]`. |
| 6 | [pre-deploy] | ci-rca.yml workflow filter matches main-canary.yml's name exactly | `bin/venv-python scripts/verify_ci_workflow.py ci-rca-filter` (asserts `ci-rca.yml`'s `on.workflow_run.workflows` list contains both `CI` and the exact string from `main-canary.yml`'s `name:` field) | Script exits 0 with `OK`. | If mismatch, decide which side to change: either fix `main-canary.yml` `name:` or fix `ci-rca.yml` `workflows:` list; the two must agree character-for-character. |
| 7 | [pre-deploy] | INTENT Section 2.5 rows show BUILT for L1, L3, L8 individually with date | `for row in 'L1 fast tier' 'L3 full tier' 'L8 hourly canary'; do grep -cE "^\\\| \\*?\\*?${row}.*ci-workflow-restructure, 2026-05-19" docs/INTENT-ci-cd-architecture.md \|\| echo "MISSING: $row"; done` | Each row prints `1` (one match per row). If any row prints `MISSING:` or `0`, the corresponding table cell was not updated. | Edit the specific Section 2.5 table row that printed `MISSING:` or `0`. |
| 8 | [pre-deploy] | INTENT Section 2.5 L6 row has owner cleared AND positive TBD marker | `grep -E "^\\\| L6 auto-merge pause.*DEFERRED.*TBD -- new plan required" docs/INTENT-ci-cd-architecture.md \| grep -cv "ci-workflow-restructure"` | Output is `1` -- exactly one row matches both the DEFERRED + TBD pattern AND does not name `ci-workflow-restructure`. | Edit Section 2.5 L6 row: state column to `DEFERRED`, owner column to literal `TBD -- new plan required`. The L2 and ci-rca-liveness rows get the same treatment; verify with the same grep substituting the row label. |
| 9 | [pre-deploy] | INTENT Section 3 L8 cadence is 3-hour | `grep -E "every 3 hours during sandbox-only" docs/INTENT-ci-cd-architecture.md` | At least one match (the Section 3 L8 row). | Edit Section 3 L8 row. |
| 10 | [pre-deploy] | INTENT Section 6 forward-looking note present | `grep -E "tightens to hourly" docs/INTENT-ci-cd-architecture.md` | At least one match (the Section 6 note). | Add the forward-looking note to Section 6. |
| 11 | [pre-deploy] | INTENT Section 10 acknowledges this plan landed | `grep -E "ci-workflow-restructure.*2026-05-19" docs/INTENT-ci-cd-architecture.md \| wc -l` | Count >= 2 (one in Section 2.5 table, one in Section 10 prose). | Add the Section 10 sequencing-constraint update. |
| 12 | [pre-deploy] | ROADMAP-PLATFORM.yaml T2.10 lists main-canary.yml | `grep -A 25 "id: T2.10" docs/ROADMAP-PLATFORM.yaml \| grep -cE "main-canary\\.yml"` | Output `1` (one match within the T2.10 block). | Add `- .github/workflows/main-canary.yml` to T2.10 `files_in_scope`. |
| 13 | [pre-deploy] | Local validate.py still passes presubmit | `bin/venv-python -m scripts.validate` | Exit 0. | Triage failures; the changes here are workflow + docs only, so any failure indicates collateral damage. |
| 14 | [pre-deploy] | Schema validators pass for the roadmap edit | `bin/venv-python -m scripts.platform_roadmap docs/ROADMAP-PLATFORM.yaml 2>&1 \| tail -5` | No structural-drift errors; exit 0 (the schema validator added by T-1.5). | Re-check the YAML indentation of the added `files_in_scope` line. |
| 15 | [pre-deploy] | SESSION_LOG.md has the new entry at top | `head -20 docs/SESSION_LOG.md \| grep -E "^## \\[2026-05-19\\].*ci-workflow-restructure\|^## \\[2026-05-19\\].*fix-duplicate-ci-validation"` | At least one match -- a heading line dated 2026-05-19 referencing this branch or plan slug appears in the first 20 lines of the file. | Prepend the session log entry per Ordered Execution Step 10. |
| 16 | [post-deploy] | During PR phase, ONLY pr-validate runs -- no push-event run fires | After pushing the branch and opening the PR, wait for the PR checks to settle, then via the GitHub MCP tools (or `gh run list --branch=<this-branch> --event=push --limit=10 --json conclusion,event,createdAt` if available): count the runs with `event: push` that fire on this branch DURING the PR phase. | Zero `event: push` runs on this branch during the PR phase. The `event: pull_request` run uses `pr-validate` (assert via `gh run view <id> --json jobs --jq '.jobs[].name'`) and executes `--pre` (assert via job log scrape: search for the literal `validate.py --pre` in the run logs or for the runtime being <5 min). | If a push-event run fired on the branch, examine the `on.push.branches` filter -- the branch name pattern should not match. If `--pre` did not appear, the job split was incorrectly wired. |
| 17 | [post-deploy] | After merge, exactly one full-tier run fires on push-to-main, ZERO PR-tier runs | `gh run list --workflow=ci.yml --branch=main --limit=5 --json conclusion,event,name,jobs` (or equivalent MCP tool) | Exactly one `event: push` run on `main` at the merge timestamp; its job list contains `main-validate` (not `pr-validate`, not `validate-python`); no `event: pull_request` run exists against `main` for this commit. | If two runs fire, check whether any other workflow is double-firing; if `pr-validate` ran on `main`, the `if:` condition is inverted. |
| 18 | [post-deploy] | Manual canary dispatch runs full tier to green | Manually trigger `main-canary.yml` against `main` via `gh workflow run main-canary.yml --ref main` (or the equivalent GitHub MCP tool), then `gh run list --workflow="Main Canary" --limit=1 --json conclusion,status` | Latest run shows `status: completed, conclusion: success`. | Read the run logs; the most likely cause is a missing env var or a venv-bootstrap step omitted from the new workflow file. Fix the workflow file and re-trigger. |
| 19 | [post-deploy] | Concurrency group serialises canary and PR CI | While the canary is in progress (started via step 18), push a trivial commit to a side branch and open a PR to force PR CI to fire. Then: `gh run list --limit=10 --json status,workflowName,createdAt` | One run is `in_progress` and the other is `queued` (not both `in_progress`). When the first completes, the queued one transitions to `in_progress`. | If both run simultaneously, the `concurrency` group is misconfigured -- check the YAML keys at the job vs workflow level; ensure both workflows declare the same `group` literal `ci-runner`. |
| 20 | [post-deploy, async report-only] | First scheduled canary fires at the next `0 */3 * * *` UTC boundary | Wait until the next 0/3/6/9/12/15/18/21 UTC hour + 30 min, then `gh run list --workflow="Main Canary" --limit=1 --json event,createdAt,conclusion`. **This step is report-only**: it does not gate the implementation's completion and may take up to ~3.5 hours to observe. Report the outcome in the final implementation report; do not loop waiting for it. | One run with `event: schedule` near the boundary; `conclusion: success`. | If the schedule did not fire after a full 3-hour cadence + 30 min slack, the cron expression may be malformed; file a follow-up rec rather than blocking. |

## Constraints
- **L6 auto-merge pause is out of scope per planning conversation.** INTENT Section 2.5 L6 rows remain marked DEFERRED in this plan's INTENT updates. `scripts/session_postflight.py:run_push()` is NOT modified.
- **L9/L10 promotion train is out of scope.** Phase Infra-Env, months away.
- **No `find_plan.py` changes.** The slug/branch mismatch documented above is accepted one-time friction; the durable fix is a separate small plan.
- **No `/implement.md` or implement-skill changes.** Formalising "draft SESSION_LOG entry in parallel with code-review" is a separate small plan; this plan demonstrates the pattern in its Ordered Execution Steps but does not codify it.
- **No edits to `validate.py`.** That landed via `validate-fast-tier-reshape` on 2026-05-13. This plan only changes which validate flag PR CI invokes.
- **No edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly** (Single Portal Invariant).
- **Branch protection remains unavailable** (Decision 72); the gates introduced here are convention + tooling.
- **Lambda deployment deferred** (Decision 67). None of the files in scope are Lambda-packaged. The DEFERRED execution-step convention does not apply here.
- **Self-hosted runner remains the substrate** for both PR CI and the canary. The OIDC + hosted-runner migration is owned by T2.10 / T2.13 / public-flip; this plan adds `main-canary.yml` to T2.10's `files_in_scope` so the migration sweeps it up later.
- **No rescue agents or workaround loops** (Decision 55). The forward-fix model already governs CI failures during this plan's own merge.

## Context

### Why this plan exists
Decision 73 (`docs/DECISIONS.md`, 2026-05-13) specified three follow-on IMPLEMENTATION plans: `planning-queue-governance`, `validate-fast-tier-reshape`, `ci-workflow-restructure`. The first two landed on 2026-05-13. This is the third and final. `docs/INTENT-ci-cd-architecture.md` Section 2.5 has named this plan as the owner for L1, L3, L6, L8, and single-runner-concurrency since ratification. L6 is deferred per the planning conversation (runner-as-bottleneck is the immediate problem; auto-merge pause is adjacent).

### Why the push trigger duplicates PR CI today
`.github/workflows/ci.yml` (current state, lines 6-10) triggers on both `pull_request: branches: [main]` and `push: branches: [main, develop]`. Both legs invoke `bin/venv-python -m scripts.validate` (unflagged = full tier). When a PR squash-merges, GitHub fires the push event against the new `main` HEAD, which is the merged content -- the full tier runs a second time on effectively identical work. Median full tier is 18 minutes (Decision 73 measured-runtime sample). On a single t3.medium runner, that's a redundant ~18 minute occupation per merge.

### Why this is not just a one-line YAML flip
Two non-obvious dependencies:

1. **`validate --pre` must be ready first.** `--pre` is now diff-aware after `validate-fast-tier-reshape`; without `fetch-depth: 0` on PR checkout, `get_changed_files()` cannot resolve `origin/main` and falls back to scanning the full repo via HEAD -- defeating the diff-aware design. The PR checkout step must change in lockstep with the flag.
2. **The canary must share the runner concurrency group with PR CI.** A 3-hourly cron firing while a PR is being checked would either preempt PR CI (bad: agents see CI fail randomly) or starve the canary (bad: drift not caught). `concurrency: { group: ci-runner, cancel-in-progress: false }` on both workflows is the GitHub-Actions-native primitive that queues rather than cancels.

### Why 3 hours (not hourly)
INTENT Section 9 originally specified hourly. At 18-50 min full-tier runtime on a single t3.medium runner, the hourly schedule overlaps with PR CI roughly 30-50% of the time worst-case -- the runner-as-bottleneck pain you raised. At 3-hour cadence, worst-case overlap is ~16% and median PR-CI queue time stays near zero. Sandbox-only operation tolerates the lower drift-catch granularity because the only consumer of the green-streak signal is the (currently-non-existent) Phase Infra-Env L9 promotion gate. When SIT lands, cadence tightens to hourly -- documented in INTENT Section 6 forward-looking note added by this plan.

### Branch/slug deviation
See Branch section above. Decision rationale: the INTENT name is the durable identifier (cross-referenced from Decision 73, INTENT Section 2.5, and the two sibling follow-on plans). The harness-assigned branch name is ephemeral. Naming the plan per INTENT preserves the cross-references at the cost of one-time friction in `find_plan.py` resolution.

### Parallel session-log step (demonstration of pattern)
The Ordered Execution Step that drafts `docs/SESSION_LOG.md` in parallel with the Step 5 code-review subagent wait is a deliberate demonstration. Today the implement workflow has no explicit step for the session-log write; it falls out implicitly via `--auto`'s `run_close()` call. Code-review on a non-trivial branch takes 2-5 minutes in a fresh-context subagent during which the main agent is idle. This plan demonstrates filling that gap. Formalising the step across all future plans is a separate small change to `.claude/commands/implement.md` and `.claude/skills/implement/SKILL.md` -- intentionally not in scope.

### Roadmap touchpoints
- **T2.10** (`docs/ROADMAP-PLATFORM.yaml` line 1542, "GitHub OIDC federation + hosted-runner migration"): we add `.github/workflows/main-canary.yml` to its `files_in_scope` so the OIDC + hosted-runner migration on public-flip also migrates the canary.
- **Phase Infra-Env** (`docs/ROADMAP-PRODUCT.md` line 640): L8 produces the green-streak signal that Phase Infra-Env's L9 promotion gate consumes. No structural roadmap edit needed; INTENT Section 6 captures the dependency.

### Related decisions
- **Decision 73**: the umbrella decision this plan implements the third slice of.
- **Decision 72** (both): branch protection unavailable; the forward-fix model already in force.
- **Decision 68**: self-hosted runner is the substrate for both PR CI and the canary.
- **Decision 60**: two-tier validation; this plan flips PR CI to honour the fast tier per the tier semantics finalised by `validate-fast-tier-reshape`.
- **Decision 67**: STRATEGIC-plan freeze; this plan is IMPLEMENTATION (5 files).
- **Decision 55**: forward-fix recovery from main-red.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (assigned: `claude/fix-duplicate-ci-validation-iTl7m`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/DECISIONS.md` read (Decision 73, 72, 68, 67, 60, 55 in particular).
- [ ] `docs/INTENT-ci-cd-architecture.md` read end-to-end (sections 2, 2.5, 3, 6, 9, 10 will be edited).
- [ ] All 7 files in Scope table located and readable (the four under-test files exist on disk; the three created-by-this-plan files -- `main-canary.yml`, `verify_ci_workflow.py`, the SESSION_LOG entry -- do not yet).
- [ ] Acceptance Criteria understood and verifiable (V3: post-deploy steps 11-15 require a live PR + workflow runs).

## Ordered Execution Steps

1. **Edit `.github/workflows/ci.yml`** -- split the single `validate-python` job into two event-gated jobs:
   - Create `pr-validate` job: `if: github.event_name == 'pull_request'`, `runs-on: [self-hosted, linux]`, `timeout-minutes: 30`, `concurrency: { group: ci-runner, cancel-in-progress: false }`. Steps: `actions/checkout@v4` with `with: { fetch-depth: 0 }`, `actions/setup-python@v5` with python 3.12, `actions/cache@v4` for pip, install requirements, then `run: bin/venv-python -m scripts.validate --pre` with `env: { AWS_DEFAULT_REGION: eu-west-2 }`.
   - Create `main-validate` job: `if: github.event_name == 'push'`, same `runs-on`, `timeout-minutes: 60` (full tier honest 15-30 min, headroom for queue-behind-PR-CI case), same `concurrency` block. Steps: standard checkout (no `fetch-depth: 0`), setup-python, cache, install, then `run: bin/venv-python -m scripts.validate` (no `--pre`) with the same env.
   - `terraform-validate` job: add the same `concurrency` block (both PR and push paths need to share the runner with the python job and the canary). Keep its existing trigger semantics (no `if:` gate needed -- terraform check is cheap and benefits from running on both events).
   - Remove `develop` from `on.push.branches`. Keep `on.pull_request.branches: [main]` unchanged.
   - Delete the old `validate-python` job entirely; the two new jobs replace it. The replacement is a pure rename + split; no logic from the old job survives outside of the two new ones.

2. **Create `.github/workflows/main-canary.yml`** -- minimal workflow that mirrors `ci.yml`'s `main-validate` job:
   - `name: Main Canary` (literal string -- referenced by VP step 6 and ci-rca.yml's workflow filter).
   - `on: { schedule: [{ cron: '0 */3 * * *' }], workflow_dispatch: {} }`
   - `permissions: { contents: read }`
   - One job on `[self-hosted, linux]` with `timeout-minutes: 60`, `concurrency: { group: ci-runner, cancel-in-progress: false }`, the standard setup-python + pip cache + install steps, then `run: bin/venv-python -m scripts.validate` with `env: { AWS_DEFAULT_REGION: eu-west-2 }`.
   - No commit-on-failure, no PR comment, no MCP plumbing. The L4 ci-rca flow handles failed runs via the existing `workflow_run` trigger on `ci-rca.yml`, extended in step 3.

3. **Edit `.github/workflows/ci-rca.yml` line 8** -- change `workflows: ["CI"]` to `workflows: ["CI", "Main Canary"]`. The literal string `Main Canary` must match `main-canary.yml`'s `name:` field character-for-character (VP step 6 enforces this).

3.5. **Create `scripts/verify_ci_workflow.py`** -- helper script for VP steps 1-6. Single file, plain stdlib + `yaml`. Dispatch on `sys.argv[1]`:
   - `jobs-and-flags`: load `.github/workflows/ci.yml`; assert `pr-validate` and `main-validate` jobs exist; `validate-python` does not; each job's `if:` is the literal expected string; `pr-validate` steps contain `--pre`; `main-validate` steps do not.
   - `concurrency`: assert all three of `pr-validate`, `main-validate`, `terraform-validate` declare `concurrency.group == 'ci-runner'` and `cancel-in-progress is False`.
   - `fetch-depth`: assert `pr-validate` checkout step's `with.fetch-depth == 0`; `main-validate` checkout step has no `with.fetch-depth` key.
   - `canary`: load `.github/workflows/main-canary.yml`; assert `name == 'Main Canary'`, `on.schedule[0].cron == '0 */3 * * *'`, `workflow_dispatch` present, canary job's `concurrency` block matches, `runs-on == ['self-hosted', 'linux']` as a LIST (reject string form), steps reference `scripts.validate` and do NOT reference `--pre`.
   - `ci-rca-filter`: load both `ci-rca.yml` and `main-canary.yml`; assert `ci-rca.yml`'s `on.workflow_run.workflows` list contains both `CI` and the canary's `name:` value.
   On all-assertions-pass, print `OK` and exit 0. On any failure, print the failing assertion diagnostic (which property, expected vs actual) and exit non-zero. No silent fallbacks; no try/except wrapping assertions.
   - **PyYAML footgun (must handle)**: `safe_load` may parse the top-level key `on:` as Python boolean `True` (YAML 1.1 quirk). Defensive access pattern: `top = data.get('on') or data.get(True)` before drilling into `top['push']['branches']` etc. Apply this in every sub-command that reads workflow trigger config. Same fix applies to VP step 4 if executed directly.

4. **Edit `docs/INTENT-ci-cd-architecture.md`** in five passes:
   - Section 2.5 table: flip L1, L3, L8, single-runner-concurrency rows from "UNBUILT" / "BUILT (currently duplicates PR CI)" / "BUILT (...needs switch to `--pre`)" to `BUILT (ci-workflow-restructure, 2026-05-19)`. Mark L2 (fast-green-AND-no-ci-rca-rec evaluator), L6 (auto-merge pause), and ci-rca-liveness-fallback rows as `DEFERRED -- see follow-up`. **Clear the "Owning follow-on plan" column on the DEFERRED rows** by replacing `ci-workflow-restructure` with `TBD -- new plan required`. This is required so the table is internally consistent: a row marked DEFERRED cannot simultaneously name this plan as its owner once this plan lands. VP step 8 enforces.
   - Section 3 L8 row: change the Trigger column text from "Cron hourly, with `concurrency: ci-runner` group" to "Cron every 3 hours during sandbox-only operation (tightens to hourly when Phase Infra-Env lands SIT), with `concurrency: ci-runner` group".
   - Section 6 (Promotion Train): add a one-paragraph note titled "L8 cadence at promotion-train activation" -- "When Phase Infra-Env lands SIT and the L9 promotion gate begins consuming the green-streak signal, the L8 canary cadence tightens to hourly so the 24-hour streak window has 24 samples rather than 8. The cron expression flips from `0 */3 * * *` to `0 * * * *` at that time; runner-capacity implications are revisited per Section 9."
   - Section 9 single-runner concurrency paragraph: update the runtime math. Replace the existing "Median canary runtime today (estimated from current full-tier-on-main runs) is 18 min; worst case 50 min." sentence-cluster with the 3-hour cadence reality: median ~18 min × 1 run / 180 min cadence = ~10% baseline runner occupancy; worst-case 50 min × 1 / 180 min = ~28% worst-case. Keep the 35-min escalation threshold and the (a)/(b)/(c) mitigation list -- those still apply.
   - Section 10 "Sequencing constraint": append a paragraph -- "`ci-workflow-restructure` landed on 2026-05-19. L1 (PR CI = fast tier), L3 (push-to-main = full tier, non-duplicate), L8 (3-hourly canary), and single-runner concurrency are now BUILT. L6 (auto-merge pause) is explicitly deferred per the planning conversation that scoped this plan; INTENT Section 2.5 L6 rows are marked DEFERRED. L2 and the ci-rca liveness fallback follow L6's deferral state. The INTENT is cite-as-in-force for L1/L3/L8; the deferred layers remain target-state."

5. **Edit `docs/ROADMAP-PLATFORM.yaml` T2.10** -- add `.github/workflows/main-canary.yml` to T2.10's `files_in_scope` list. Insert immediately after the existing `.github/workflows/ci.yml` line (line 1556) to preserve the existing alphabetical-ish grouping.

6. **Run pre-deploy verification steps 1-14** from the Verification Plan. Step 15 (SESSION_LOG presence) runs after step 10 below. Loop until each passes. Do not proceed to step 7 with any pre-deploy verification still failing.

7. **Final validation locally**: `bin/venv-python -m scripts.validate`. Must exit 0.

8. **Commit the workflow + INTENT + roadmap changes** with the message `ci: split PR fast-tier from main full-tier; add 3-hourly canary (Decision 73 L1/L3/L8)`.

9. **Dispatch the code-review subagent** (per `/implement` Step 5) via the `Agent` tool with `subagent_type: code-review`. The branch diff under critique is `git diff main...HEAD`; the plan file is `docs/plans/PLAN-ci-workflow-restructure.md`. Do not brief the subagent on what to look for.

10. **In parallel with step 9's wait**: draft the `docs/SESSION_LOG.md` entry. Use `bin/venv-python -m scripts.session_postflight --close` to generate the template, then fill in `Done`, `Key actions`, `Anomalies`, `Next`. Prepend the entry to `docs/SESSION_LOG.md` (newest-first ordering per the file's header convention). Do not block on the subagent; if drafting finishes first, that's expected -- continue to wait for the subagent to return.

11. **Address code-review findings**: implement fixes for Critical/High. File Medium/Low as recommendations via `bin/venv-python -m scripts.ops_data_portal --file-rec ...` (best-effort if SSO unavailable; the outbox handles offline).

12. **Push the branch and open the PR** via `scripts/session_postflight.py --push` (or the equivalent flow). The PR title should be `ci: split PR fast-tier from main full-tier; add 3-hourly canary` and the body should reference Decision 73 and this plan.

13. **Execute post-deploy verification steps 16-19** against the live PR + main + canary runs. Step 20 (first scheduled canary) is **report-only / async** -- run it best-effort but do not block the implementation report on it; if the cron boundary has not been reached at report time, note "step 20 outcome pending" and move on.

14. **Report**: files changed, verification results (per-step actual outcomes), code-review findings fixed, any design deviations, and a one-line confirmation that INTENT-ci-cd-architecture.md Section 2.5 L1/L3/L8 are now BUILT and citable from any subsequent plan.
