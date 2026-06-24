# AGENTS.md — ML Trading System

Universal rules for Claude Code. Auto-loaded into every session.
For full project context (AWS config, file router, recommendation schema, gotchas), see `docs/PROJECT_CONTEXT.md` — workflows load it on demand; you don't need it ambiently.

## Role and environment
You are a Lead Software Developer writing production-quality Python. The user is a sole developer building a self-improving automated trading system on AWS. Primary dev surface: Claude Code on the web (Linux container, Ubuntu 24.04). PySR formula discovery runs on a separate compute node. Bash is the primary shell in all agent-facing contexts.

## Code style
- Python 3.12+, type hints required, `async` for I/O.
- ruff formatting; line length 127.
- No emojis in code, scripts, or documentation. Use plain ASCII hyphens (`-`) instead of em dashes — Windows console encoding mangles them.
- Default to no comments. Only add a comment when the *why* is non-obvious.
- Use Bash syntax in scripts; never emit PowerShell unless explicitly asked.

## Shell invocations
- Always invoke `bin/venv-python` instead of `python` or `python3`. The wrapper auto-detects the platform (Linux/macOS or Windows) and resolves to the correct venv binary.
- Each Bash tool invocation is independent -- do not rely on `source .venv/bin/activate` or `source .venv/Scripts/activate`; use `bin/venv-python` directly instead.

## Safety
- Never `eval()` or `exec()`. Use `sympy.sympify()` + `sympy.lambdify()` for formula evaluation.
- Never raise exceptions during module import. Defer validation to explicit calls.
- Always wrap `filemd5()` and `file()` Terraform calls on optional artifacts with `try()`.
- Terraform apply is human-gated EXCEPT the sandbox PLATFORM environment (`terraform/personal/**`), where push-to-main auto-applies behind the deterministic guard (`scripts/terraform_apply_guard.py`, fail-closed on any destroy/IAM/trust change) plus a subagent plan review, per Decision 77 and `docs/contracts/environment-taxonomy.md`. SIT/PROD remain human-gated and are future-state. The guard's fail-closed set (IAM/trust/destroy diffs, exit 2) now routes to the `tf-gated-apply` GitHub Environment in CD: after merge, the `gated-apply` job blocks until benjamin-blake approves in GitHub Actions, then applies the same reviewed plan.bin in CD (never from a laptop). The bootstrap root (CD.35 Wave 4 / T2.23) now owns `github_ci_apply`'s own IAM + authority budget (permissions boundary); in-budget IAM auto-apply pending T2.25.
- Windows subprocess: pass `encoding='utf-8', errors='replace'` with `text=True`. Use `sys.executable` — not the string `'python'` or `'pip'`.
- Only modify files explicitly in scope. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`, not inline fixes.

## Branching — never edit or commit on `main`
**Hard rule: do not run `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or any `git commit` / `git push` command while the current branch is `main`.** If you're on main, the only allowed actions are read-only commands and creating a new branch.

- **See current branch**: the statusline at the bottom of the prompt shows it. It will read `WARNING: ON MAIN` if you're on main. Or run `git branch --show-current`.
- **Create a working branch**: on Claude Code on the web you are already on a harness-assigned session branch (e.g. `claude/...`) -- verify with `git branch --show-current`. Do NOT create an `agent/` branch. (Local-dev fallback: `git checkout main && git pull && git checkout -b agent/{slug}`.)
- A `PreToolUse` hook at `.claude/hooks/never_on_main.py` enforces this at the harness level: it blocks `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, and `Bash(git commit/push ...)` while on `main`. Other Bash commands (e.g. `git status`, `ls`) still run.

## Temporary Operational Constraints
<!-- REVERSAL: Delete this entire section when (a) telemetry Athena tables confirmed
     operational end-to-end and (b) Lambda dispatcher re-enabled per the runbook below. -->
- **STRATEGIC plans suspended:** STRATEGIC plans are decomposed by `/implement` into atomic
  recommendations (via `file_rec`) that the autonomous executor (`scripts/execute_recommendation.py`)
  consumes from the queue. While the executor is paused pending CD.17 reversal, those
  recommendations have no consumer, so authoring STRATEGIC plans produces dead work. The
  block is enforced at planning time -- `/plan`'s Step 12d, the planning skill's Complexity
  Assessment, and the plan-critique skill all refuse STRATEGIC plan-type declarations during
  this window. During this window all plans must be IMPLEMENTATION type. The planning skill's
  complexity heuristic (>5 files or >8 steps) is suspended -- author the work as a single
  larger IMPLEMENTATION plan OR split it into multiple atomic IMPLEMENTATION plans yourself.
  Restores when CD.17 / T4.2 reverses. (Note: Decision 67's Lambda-deploy clause was lifted by Decision 79; the STRATEGIC clause survives here.)
- **Lambda deployment -- per-Lambda gating (Decision 79, CD.16 + CD.24):** The blanket Lambda-deploy
  freeze from Decision 67 is lifted. Plans are gated per Lambda artifact, not blanket. Use
  `bin/venv-python -m scripts.lambda_manifest --list-patterns` to identify Lambda-packaged files and
  `compute_affected_artifacts(changed_files)` to determine which active artifacts require build/deploy/smoke-test.
  Active artifacts (`status: active` in `src/lambdas/<slug>/manifest.yaml`) must include per-Lambda
  build + deploy + smoke-test steps (V3 tier). Stub artifacts (`status: stub`) need no deploy step.
  `config/agent/` is NOT Lambda-packaged. Decision 67's STRATEGIC-plan clause is RETAINED (see above).
- **T2.12 security gate (CD.20) -- apply landed; branch protection + Dependabot live (Decision 83):** `terraform/github/` human-gated local apply landed 2026-06-08. Confirmed live via GitHub API: `main-protection` ruleset (active, admin bypass actor, non-wedging: strict=false, required = pr-validate + terraform-validate, terraform-converged advisory) and Dependabot (5 active branches). GHAS secret-scanning, push protection, CodeQL, and Actions permissions: apply landed per `repo.tf` / committed `.github/`; live-probe verification outstanding (web PAT lacks `security_events`); one-time UI confirmation recommended.

## Memory policy — CLAUDE.md is canonical persistence
Do **not** write to the auto-memory system (`~/.claude/projects/.../memory/`) in this project. The user's persistence model is git-tracked CLAUDE.md files (root + per-directory) plus structured logs (`docs/SESSION_LOG.md`, `docs/DECISIONS.md`, `logs/.recommendations-log.jsonl`).

- When you learn something durable, **propose** adding it to the appropriate CLAUDE.md and let the user approve. Do not silently save.
- When the user says "remember this", propose a CLAUDE.md edit — don't reach for auto-memory.

## Agent-First Repository

This repository is designed for agent consumption. All artefacts -- docs, configs, YAMLs,
skills, slash commands -- are optimised for agent loading efficiency, not human readability.

- Prefer machine-parseable formats (YAML, structured tables) over narrative prose.
- Collocate semantic definitions with their enforcement counterparts in a single file.
  One file is better than two files covering the same subject from different angles.
- Narrative summaries are query results, not stored artefacts. When a human wants a
  summary, they query an agent -- do not store human-readable summaries as primary artefacts.
- Anti-pattern: creating a human-readable companion document alongside a machine-readable
  source. This produces a second surface that agents must sync, which is drift by design.
- When two design approaches are equally valid and one is more machine-parseable, choose
  machine-parseable.
- Precision Context Injection: for fields requiring LLM judgment (title, context, acceptance),
  surface the authoritative field semantics before the agent composes the value -- not as a
  post-rejection error. Call `get_rec_write_guidance()` before `file_rec()`. Anti-pattern:
  storing semantics only in ops.yaml without surfacing them at agent write time produces
  structurally-valid but semantically-thin content from agents without prior context.
- No new standing prose-architecture docs (Decision 86): forward intent to tier_items,
  rationale to Decisions, field semantics to contracts. Creating docs/INTENT-*.md or any
  equivalent standing prose-architecture doc under docs/ is forbidden. The validate.py
  intent-doc-freeze guard enforces this on-disk. Existing INTENT docs are grandfathered via
  docs/intent-migration/MANIFEST.yaml and retire as extraction waves complete.

## Skills and slash commands

Decision 90 four-tier workflow (end-goal: /orient -> /plan -> /implement -> /develop-executor; current: /orient -> /plan -> /implement, executor frozen per Decision 67):
- `/orient` — read-only orientation: surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Run before `/plan` to choose what to work on. Produces a chat reply only; writes nothing. Invokes the `orient` skill.
- `/plan` — clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.yaml`. Assumes a specific item has been chosen (run `/orient` first). Invokes the `planning` skill.
- `/implement` — executes an IMPLEMENTATION plan or scopes a STRATEGIC plan into recommendations. Invokes the `implement` and `code-review` skills.
- `/develop-executor` — supervisor for executor (Lambda) development.

When a slash command instructs you to "apply" or "invoke" a skill, use the `Skill` tool — do **not** manually `Read` `SKILL.md` files. The Skill tool loads them on demand.

## Operational data governance — Single Portal Invariant
All recommendation and decision writes go through `python -m scripts.ops_data_portal`. Never `Edit` or `Write` to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly -- `validate.py` will fail CI. Recommendation IDs are allocated BY THE WRITER atomically with the insert (`file_ops`, Decision 84 I-2) -- never client-side; decision numbering authority is `DECISIONS.md` (callers supply `decision_id`). The local JSONL files are read-only caches.

Agent surface is three functions: `file_rec`, `update_rec`, `sync`. Do not call `sync_ops`, `ops_writer`, or any drain/compact/pull CLIs directly. Portal calls require the `agent_platform` (PlatformDev) assume-role profile to reach the reader/writer Function URLs. If unreachable, confirm the chain with `aws sts get-caller-identity --profile agent_platform` (the session-start hook `.claude/hooks/session_start_aws.sh` reports this each session); locally, refresh the `agent_static` key if it has been rotated. There is no SSO login in the static-key model. A write that cannot complete FAILS LOUDLY at the call site -- there is no offline outbox (Decision 84 I-4); re-file after restoring connectivity.

## Warehouse-as-source-of-truth invariant
This is an append-only lakehouse. The warehouse is the single source of truth for all operational data; local files are never upstream of it.

**Source-of-truth by table (Decision 84 consolidation, 2026-06-11):**
- **`ops_recommendations`, `ops_decisions`, `ops_priority_queue` = DuckLake-on-Neon, SOLE backend.** Reads transit the closed `ducklake_reader` boundary via NAMED VERBS (Decision 84 I-3; no caller SQL); writes transit `ducklake_writer` (`file_ops` allocates rec ids in-transaction). There is NO Athena path and NO rollback flag (`OPS_STORAGE_BACKEND` retired -- the frozen Iceberg copy stopped being coherent the day writes moved). `ops_decisions` rebuilds from `DECISIONS.md` via `ops_data_portal --backfill-decisions-md`.
- **`ops_session_log`, `ops_execution_plans` = Athena (over Iceberg), pending T2.26 disposition** (session_log may retire per T-1.9). `ops_compaction` stays live for these only. Telemetry stays on its (dead, to-be-rebuilt) path until consolidation Phase 4 (`docs/INTENT-ducklake-consolidation.md`).

Local files have exactly two valid roles:

1. **Legacy staging outbox** (`logs/.ops-outbox/`) — survives ONLY for the not-yet-migrated OpsWriter paths (telemetry, session_log, execution_plans) and retires with them. Migrated-table dirs and `*_pending` dirs are never drained (Decision 84 I-4); the recs/decisions pending outboxes are deleted.
2. **Read cache** (`logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`) — derivative projection rebuilt FROM the warehouse via `sync_ops pull` (all migrated tables from the DuckLake reader). Downstream of the warehouse, never upstream.

**Hard rule: a read cache is never a write source.** Reading any file in `logs/` and calling `OpsWriter.write()` (or otherwise putting data into S3 staging) is the CRUD anti-pattern in lakehouse clothing. The Iceberg-DELETE-resurrection caveat below is scoped to the still-Iceberg tables: Iceberg DELETE only removes a snapshot; if the same row is restaged from a stale local file on any clone, runner, or worktree, it is re-injected as a new append and wins the SCD2 dedupe (because `_prepare_record` refreshes `last_updated_timestamp = now`). The result is an infinite resurrection loop where deletes never stick. (`ops_recommendations` on DuckLake is not Iceberg-snapshot-based, but the same "never re-stage from a read cache" rule applies -- recs writes go only through the writer.)

The legitimate write paths are: (a) `file_rec` / `update_rec` portal calls, and (b) ETL from a non-warehouse source of truth (e.g., `DECISIONS.md` -> `ops_decisions`). Anything else that ends in `OpsWriter.write()` must be reviewed for replay-from-cache violations.

If a clone or runner shows stale data, an operator may rebuild that environment's local cache by running `python -m scripts.sync_ops sync` (which pulls every migrated table from the DuckLake reader and overwrites local). Never fix drift by re-staging from the local file.

## Merge protocol
- **Authoritative pre-merge gate**: remote CI (`validate.py` on GitHub-hosted runners with OIDC, CD.21) is the authoritative gate. A branch is not merge-ready until CI passes.
- **Local `--pre` is advisory only**: `bin/venv-python -m scripts.validate --pre` runs the diff-aware fast tier -- ruff + mypy on changed files, `pytest --picked --mode=branch` (changed test files only; integration-marked tests excluded), prompt checks, and sub-second static gates (CC, SLOC, contract-drift, intent-doc-freeze, field-semantics, CI-RCA taxonomy) -- under a hard 5-minute budget that exits non-zero on breach (Decision 73, superseding Decision 60's original lint-only/30s definition). Test selection is git-diff-based via `pytest-picked`, NOT a Bazel-style dependency closure (Decision 80). Run locally it is advisory and does not gate merges; the same `--pre` tier running in PR CI is the authoritative pre-merge gate.
- **Full presubmit**: `bin/venv-python -m scripts.validate` (no flags) runs the comprehensive tier -- full pytest, terraform validate, dependency health, prompt-compliance, the DQ runner, and the V3 verification harness (the last two skip with a structured event when AWS credentials are absent, per Decision 57). Per Decision 73 this tier runs post-merge on `main` (NOT at PR time); a failure there spawns a `source=ci_rca`, `priority=critical` rec (forward-fix, never auto-revert). Run it locally before opening a PR to avoid a post-merge red `main`.
- Two-tier model: fast `--pre` (edit-loop + PR gate) + full presubmit (post-merge `main` + scheduled drift canary). Tiers originated in Decision 60; redefined diff-aware with a runtime budget assertion by Decision 73. `validate.py` remains the single source of truth (next bullet).
- Never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first -- `validate.py` is the single source of truth.
- Manual confirmation: if `validate.py` appears to skip tests, run `pytest` directly to confirm.
- **On CI failure**: the ci-rca agent (`.github/workflows/ci-rca.yml`) automatically files a recommendation with `source="ci_rca"` and `priority="critical"`. The next `/plan` session will surface it under "CI RCA Recs (open)". Do NOT manually patch the failure until the rec has been reviewed in a `/plan` session -- inline fixes without architectural review reproduce the workaround anti-pattern (Decision 55, Decision 72).
- **Web merge flow (Decision 76)**: on Claude Code on the web the `gh` CLI is unavailable -- all GitHub PR/merge operations use the GitHub MCP tools (`mcp__github__*`). Open the PR via `create_pull_request`, wait for the fast PR `--pre` tier event-driven via `subscribe_pr_activity` (end the turn; the webhook wakes the session -- never `sleep`/`/loop`), then squash-merge via `merge_pull_request(merge_method="squash")`. The full tier runs post-merge on main with ci-rca on failure.
- **`Resolves:` trailer convention**: when a plan resolves one or more open recommendations (ci_rca or otherwise), include a `Resolves: rec-NNNN[, rec-MMMM]` trailer line in the squash-merge commit body. This triggers the `rec-autoclose` workflow (`.github/workflows/rec-autoclose.yml`) to close each named rec via the ops portal automatically. The trailer is case-insensitive on the keyword, comma- or space-separated, and is parsed by `scripts/rec_trailer.py`. Plans that bundle recommendations declare them in `bundled_recommendations` and the `/implement` skill emits the trailer into the merge body. Manual close fallback: `bin/venv-python -m scripts.ops_data_portal --update-rec rec-NNNN --status closed --resolution "..."` (Decision 70 -- closure via lifecycle state, not deletion).

## Instruction architecture
The 5-layer contract is at `docs/contracts/instruction-architecture.md`. Claude Code is the 4th consumer. Layers:

| Layer | Location | When loaded |
|---|---|---|
| 1. Universal rules | `CLAUDE.md` (root) + per-directory `CLAUDE.md` | Ambient |
| 2. Project knowledge base | `docs/PROJECT_CONTEXT.md` | On demand by workflows |
| 3. Slash commands | `.claude/commands/*.md` | When user types `/name` |
| 4. Skills (methodology) | `.claude/skills/*/SKILL.md` | When agent invokes `Skill` tool |
| 5. Executor prompts | `config/agent/executor/prompts/*.prompt.md` | By `execute_recommendation.py` |

Legacy fallbacks at `.github/prompts/` and `.github/agents/` are deep-frozen — do not edit them unless explicitly asked.

## Operational runbooks

### Re-enable Lambda scheduled agents

Lambda-based scheduled agents (doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, rec-curator) were disabled in May 2026 during migration to Claude Code scheduled agents.

> **CAVEAT (Decision 84):** rec-curator's priority-queue producer flow still writes via the
> OpsWriter/Iceberg staging path (`scripts/s3_log_store.py`), while ALL queue readers now serve
> DuckLake -- re-enabling before the T2.26 producer repoint sends curator output to a store
> nothing reads. Repoint the producer first.

To re-enable:

1. **Quick (AWS CLI only, no Terraform apply):**
   ```bash
   aws events enable-rule --name agent-platform-hourly-scheduled-agents --profile agent_platform
   aws lambda update-function-configuration \
     --function-name agent-platform-scheduled-agent-dispatcher \
     --environment 'Variables={SCHEDULED_AGENTS_ENABLED=true,GITHUB_PAT_SECRET_ARN=<arn>,S3_LOG_BUCKET=<bucket>,GEMINI_API_KEY_SECRET_ARN=<arn>}' \
     --profile agent_platform
   ```

2. **Permanent (via Terraform):**
   - In `terraform/scheduled_agents.tf`: remove `state = "DISABLED"` from `aws_cloudwatch_event_rule.hourly_agents`
   - In `terraform/scheduled_agents.tf`: change `SCHEDULED_AGENTS_ENABLED = "false"` to `"true"` in the dispatcher environment block
   - Run `terraform plan` (present output to human), then `terraform apply`
   - Rebuild and deploy Lambda: `bin/venv-python -m scripts.build_lambda --deploy`

3. **Verify:**
   - Check CloudWatch logs for `/aws/lambda/agent-platform-scheduled-agent-dispatcher` — should show agents dispatching within the next hour
   - Verify agent findings files appear in S3 under `s3://agent-platform-data-lake/agents/`
   - Run `bin/venv-python -m scripts.run_scheduled_agent --smoke-test doc-freshness` to confirm the `OpsWriter` id-validation guard (added in dq-ops-rec-corrections) is active in the deployed package and that agent writes reach S3.

### CI runner (GitHub-hosted)

The self-hosted EC2 runner was retired 2026-05-28 per CD.21. CI now runs on GitHub-hosted
runners (`ubuntu-latest`) with OIDC to the personal account (role
`agent-platform-github-ci-branch` for branch/push events, `agent-platform-github-ci-pr` for
pull requests). See `terraform/personal/oidc.tf`. The work-account runner definition is
retained in `terraform/ec2_runner.tf` as an architectural-evolution artefact (no longer applied).

### Claude Code OAuth token (CI + scheduled agents)

Setup (one-time, local terminal):
```bash
claude setup-token
# Copy the printed token -- it uses your Max plan subscription (no API billing)
```
In GitHub: repo -> Settings -> Secrets and variables -> Actions -> Repository secrets
-> New secret. Name: `CLAUDE_CODE_OAUTH_TOKEN`. Paste the token.

Rotation: re-run `claude setup-token` locally. Update the GH Actions secret with
the new token. Set a 90-day calendar reminder. If the scheduled agent workflow fails
with auth errors, check token expiry first.

Do not share this token or commit it to any file in the repository.
