# Plan

## Intent
The autonomous merge loop depends on a reliable green-CI wake signal. This hardens the green-CI wake comment so a watching `/implement` session is woken only after all required PR checks have actually passed, eliminating the stall where the agent wakes on the premature fast-tier comment and then misses the silent clean pass of the parallel `terraform-validate` job.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-green-ci-wake-gate.md

## Phase
Operational CI/CD hardening. No roadmap tier_item (user-requested; soft-warn exception category `user_explicit_out_of_scope`). Adjacent to Decision 76 (web merge flow) and Decision 73 (two-tier CI). Current roadmap phase: Phase 1 Core Infrastructure (complete).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/workflows/ci.yml` | Modify | Extract the green-CI wake comment out of the `pr-validate` job into a dedicated `signal-green` job gated on `needs: [pr-validate, terraform-validate]`, so the comment posts only after all required PR checks pass. Tighten `pr-validate` permissions and update the comment body wording. |

## Bundled Recommendations
None.
- **rec-940** [High/S] "Implement PR auto-merge after repo public-flip" is the future GitHub-native server-side successor to this comment-based wake; it is blocked on branch protection + required status checks (CD.20, deferred) and is intentionally NOT bundled. This plan is the interim hardening.
- **rec-831** [Low/XS] (terraform-validate cost trade-off doc) is tangential; not included.

## Infrastructure Dependencies (if applicable)
N/A. No `.tf` files in scope. The change is a GitHub Actions workflow edit only and makes zero AWS calls. (`terraform-validate` is referenced as a `needs` dependency but is not modified.)

## Acceptance Criteria
- [ ] The green-CI wake comment is posted by a dedicated `signal-green` job, not by a step inside `pr-validate`.
- [ ] `signal-green` declares `needs: [pr-validate, terraform-validate]` -- exactly those two job IDs, NOT `main-validate` (decision-scout NOTE: `main-validate` is push-only and would deadlock a PR-scoped job).
- [ ] `signal-green` runs only when both needed jobs succeed and only for `claude/*` PR head branches: `if: ${{ success() && github.event_name == 'pull_request' && startsWith(github.head_ref, 'claude/') }}`.
- [ ] The comment step retains `continue-on-error: true` so a comment failure can never red the build.
- [ ] `pr-validate` no longer contains the "Signal green CI" step and no longer requests `pull-requests: write` (reverts to `contents: read` only).
- [ ] `signal-green` holds `permissions: { contents: read, pull-requests: write }`.
- [ ] The comment body reads "all required PR checks passed" (not "fast tier (validate --pre) passed").
- [ ] On the implementation PR, `signal-green` starts only after BOTH `pr-validate` and `terraform-validate` complete, and the wake comment appears only after both are green.
- [ ] On a red check, no wake comment is posted (`signal-green` skipped); the failure-path wake is left to the existing `subscribe_pr_activity` subscription (unchanged).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Workflow YAML still parses | `bin/venv-python -c 'import yaml; yaml.safe_load(open(".github/workflows/ci.yml")); print("YAML OK")'` | Prints `YAML OK`, exit 0 | `yaml.YAMLError` -> fix indentation/syntax of the new job |
| 2 | [pre-deploy] | `signal-green` gates on exactly the two PR checks (scout NOTE) | `bin/venv-python -c 'import yaml; j=yaml.safe_load(open(".github/workflows/ci.yml"))["jobs"]["signal-green"]; assert set(j["needs"])=={"pr-validate","terraform-validate"}, j["needs"]; print("needs OK", j["needs"])'` | Prints `needs OK [...]` with exactly those two ids (order may vary), exit 0 | `KeyError` (job missing) or `AssertionError` (wrong/over-broad `needs`, e.g. includes `main-validate`) -> correct the `needs` list |
| 3 | [pre-deploy] | Gating condition correct, wake step removed from `pr-validate`, permissions moved | `bin/venv-python -c 'import yaml; w=yaml.safe_load(open(".github/workflows/ci.yml")); sg=w["jobs"]["signal-green"]; c=sg["if"]; assert "success()" in c and "pull_request" in c and "claude/" in c, c; prv=yaml.dump(w["jobs"]["pr-validate"]); assert "Signal green CI" not in prv, "wake step still in pr-validate"; assert "pull-requests" not in prv, "pr-validate still has pull-requests perm"; assert sg["permissions"]["pull-requests"]=="write"; print("gating+perms OK")'` | Prints `gating+perms OK`, exit 0 | `AssertionError` -> fix the `if:` expression, remove the leftover step, or correct the permissions blocks |
| 4 | [pre-deploy] | Comment body updated and `continue-on-error` retained | `bin/venv-python -c 'import yaml; s=yaml.safe_load(open(".github/workflows/ci.yml"))["jobs"]["signal-green"]["steps"][0]; assert s.get("continue-on-error") is True, s; assert "all required PR checks" in s["run"], s["run"]; print("body+coe OK")'` | Prints `body+coe OK`, exit 0 | `AssertionError` -> set `continue-on-error: true` and/or update the body text |
| 5 | [pre-deploy] | Full presubmit passes (incl. workflow-agent-safety, full tier) | `bin/venv-python -m scripts.validate` | Exit 0, no failures reported | Any failure -> address the specific failing check before opening the PR (authoritative local gate per merge protocol) |
| 6 | [post-deploy] | On the implementation PR, confirm ordering + comment timing (owner/repo from `git remote get-url origin`; the `/implement` agent does this as part of its normal wait-for-CI) | `mcp__github__pull_request_read(method="get_check_runs", owner=OWNER, repo=REPO, pullNumber=PR)` then `mcp__github__pull_request_read(method="get_comments", owner=OWNER, repo=REPO, pullNumber=PR)` | `check_runs` lists `pr-validate`, `terraform-validate`, `signal-green`; `signal-green.started_at` >= the later `completed_at` of the other two; `signal-green.conclusion == "success"`; the "CI green: all required PR checks passed" comment is present only after both checks are green and ABSENT while `terraform-validate` is `in_progress` | `signal-green` starts before `terraform-validate` completes (needs misconfigured); comment posts during a still-running check; or `signal-green` runs on a non-`claude/*` branch (if-guard wrong) -> correct `needs`/`if` and re-push |

## Constraints
- Only modify `.github/workflows/ci.yml` (scope discipline -- AGENTS.md "Only modify files explicitly in scope"). Docs are intentionally out of scope: the agent-side merge contract (subscribe -> wake -> re-check status -> merge) is unchanged; only the green-wake's timing becomes accurate.
- No rescue agents or workaround loops (Decision 55).
- Do NOT add `main-validate` to `signal-green`'s `needs` -- it is push-only (`if: github.event_name == 'push'`) and never runs on a PR, so a `needs` on it would deadlock the PR-scoped `signal-green` (decision-scout NOTE).
- Preserve `continue-on-error: true` on the comment step. A wake signal must never red the build -- this is the inverse of Decision 77's gating-guard discipline (advisory step may swallow failures; a gate may not).
- Do NOT register `signal-green` as a required status check if/when branch protection lands -- it is advisory only (CD.20 deferred).
- `gh` IS available on the GitHub Actions `ubuntu-latest` runner (preinstalled), so the `gh pr comment` invocation runs there with `GH_TOKEN`. The web-harness `gh`-unavailability (Decision 76) applies to the agent's local shell, NOT the runner -- do not "fix" the workflow to drop `gh`.

## Context
- **Failure mode being fixed:** the wake comment is currently a step inside `pr-validate` (`.github/workflows/ci.yml:73-85`), gated on `success()` of that job alone, so it fires when the fast `--pre` tier passes -- independent of the parallel `terraform-validate` job. Per `ci.yml:74-75`, the `subscribe_pr_activity` subscription wakes a watching session on comments and failures but NOT on clean check passes, so this comment is the ONLY green-path wake signal. When it fires early, the agent wakes, sees "still running" via `get_check_runs`, ends its turn (implement skill, "Still running -> end the turn"), and the subsequent clean pass of `terraform-validate` produces no further wake -> the agent stalls past the true all-green moment. The failure path is fine as-is: a red check produces a wake event the subscription already catches.
- **Decision 76** (Claude-Code-on-the-Web Workflow Migration): the event-driven wake contract this change repairs. CITE.
- **Decision 73** (Two-Tier Diff-Aware CI): fast `--pre` tier (`pr-validate`) gates PRs; full tier (`main-validate`) runs post-merge on `main`; `terraform-validate` has no event guard and runs on both PR and push. The bug is rooted in the wake firing on fast-tier success while the parallel terraform job was still running. The `needs: [pr-validate, terraform-validate]` set is the correct PR-event aggregation boundary. CITE.
- **Decision 72** (Branch Protection Not Available): the comment-based wake exists precisely because `required_status_checks` cannot yet gate merges; this is the interim mechanism. RELATED.
- **rec-940 / CD.20**: future GitHub-native server-side auto-merge supersedes this once branch protection + required status checks are enabled. RELATED (successor, not bundled).
- **Verified during planning:** all 7 workflow files were enumerated; on a `claude/*` PR to `main` the ONLY checks are `pr-validate` and `terraform-validate`, both defined in `ci.yml`. A single-workflow `needs`-gate therefore captures every required PR check -- no cross-workflow `check_suite` aggregation is needed. (`needs:` cannot reference jobs in other workflows, so this approach is valid only because both checks live in this file. If a future workflow adds a PR-triggered check, this gate must be revisited.)
- **Comment body is not parsed anywhere:** the agent wakes on the comment *event*, then re-checks actual status via `pull_request_read` (`get_status`/`get_check_runs`), so changing the body wording is safe.
- **GitHub Actions semantics:** a job with `needs` whose `if` includes `success()` runs only when all needed jobs succeeded; on a `push` event `pr-validate` is skipped, so `signal-green` is skipped (doubly guarded by the `github.event_name == 'pull_request'` clause). `github.head_ref` is populated only on `pull_request` events, which is exactly the context `signal-green` runs in.
- **Decision scout gate verdict:** NO_FLAGS. CITE = Decision 76, Decision 73. One NOTE (folded into Constraints + VP step 2): do not over-broaden `needs`.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md reviewed (handled via the decision-scout gate at planning time: NO_FLAGS; CITE Decision 76, 73)
- [ ] `.github/workflows/ci.yml` located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. In `.github/workflows/ci.yml`, **remove** the "Signal green CI (wake a watching session)" step (currently the last step of the `pr-validate` job, lines ~73-85) from `pr-validate`.
2. In the `pr-validate` job, change its `permissions:` block to `contents: read` only -- drop the `pull-requests: write` line and its trailing comment (the job no longer posts comments).
3. Add a new top-level job `signal-green` with: `needs: [pr-validate, terraform-validate]`; `if: ${{ success() && github.event_name == 'pull_request' && startsWith(github.head_ref, 'claude/') }}`; `runs-on: ubuntu-latest`; `timeout-minutes: 5`; `permissions: { contents: read, pull-requests: write }`; and a single step "Signal green CI (wake a watching session)" with `continue-on-error: true`, `env: { GH_TOKEN: ${{ github.token }} }`, and a `gh pr comment "${{ github.event.pull_request.number }}" --body "CI green: all required PR checks passed for ${{ github.event.pull_request.head.sha }}. Automated wake signal for a watching session; no action needed."` run command. Preserve a short explanatory comment block matching the surrounding style.
4. **Execute Verification Plan** -- run pre-deploy steps 1-5 locally; loop until they pass. Post-deploy step 6 is observed on the implementation PR (folded into the normal wait-for-CI). If V3 fails unrecoverably, stop and analyze root cause (Decision 55).
5. Report: what was implemented and verification results.
