# AGENTS.md — ML Trading System

Universal rules for Claude Code. Auto-loaded into every session.
For full project context (AWS config, file router, recommendation schema, gotchas), see `docs/PROJECT_CONTEXT.md` — workflows load it on demand; you don't need it ambiently.

## PUBLIC repository / confidential-data boundary

This repository is PUBLIC (Decisions 73, 83, 101). Public-content boundary (Decision 101):
- NEVER publish: AWS account IDs or ARNs, IAM ExternalIds, credentials or API keys, trading alpha / strategy performance, or any internal hostname that provides an attack surface.
- SAFE to publish: platform engineering, infrastructure patterns, tooling, CI/CD design, and general LLM-agent architecture -- market the engineering, not the alpha.
- Confidential data lives ONLY in: the personal AWS account (Secrets Manager, gitignored tfvars, S3 private prefixes), and gitignored local files (e.g. `terraform/personal/terraform.personal.tfvars`, `~/.aws/credentials`). Nothing confidential is ever committed.
- The pre-commit `never-commit` hook (shape-pattern) blocks 12-digit AWS account IDs, secret-like strings, and ExternalId patterns from reaching the repo.

## Role and environment
You are a Lead Software Developer writing production-quality Python. The user is a sole developer building a self-improving automated trading system on AWS. Primary dev surface: Claude Code on the web (CC-web; Linux container, Ubuntu 24.04). PySR formula discovery runs on a separate compute node. Bash is the primary shell in all agent-facing contexts.

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
- Terraform apply model: see `docs/contracts/environment-taxonomy.md` (Axis A + Guard classification subsection) -- that file is the sole SoT. Short form: sandbox auto-applies behind the deterministic guard (Decision 77); in-budget IAM inline-policy/attachment UPDATEs on managed boundary-carrying roles now auto-apply (T2.25 / Decision 92 point 5); trust/destroy/out-of-budget IAM route to the `tf-gated-apply` Environment. Bootstrap root is admin-only out-of-band.
- **Deployment model (Decision 126):** three agent intents, one trigger each -- infra = open a PR touching `terraform/**`, CI plans and applies; code = the governed code-deploy channel (Terraform not involved); red/drift = run the one-input Reconcile action. Agents never run terraform apply as a self-directed, routine action -- the sole exception is the human-gated break-glass admin tier (below/`terraform/CLAUDE.md`), where a human reviews and explicitly directs the apply before an agent executes it; operators may always invoke it directly. See `docs/contracts/deploy-paths.yaml` for the full intent -> trigger -> recovery index (it points at, and never restates, this file's apply-model/guard rules).
- **Lambda deploy channel (Decision 125/126):** the four DuckLake Lambdas' code is decoupled from `terraform/personal` infra apply as of #544 (see `docs/contracts/environment-taxonomy.md` section 5 and `docs/contracts/build-lambda.yaml`'s `deploy_channels`) -- but the governed code-deploy CD channel itself is still PENDING (tier_item T2.38); `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` remains the interim break-glass path, not yet a routine default. Heuristic: when a production action (e.g. a Lambda code deploy) is auto-denied or has no obvious in-session path, check `docs/contracts/deploy-paths.yaml` first, then grep `.github/workflows/` for a governed CD path before falling back to a local permission grant.
- Windows subprocess: pass `encoding='utf-8', errors='replace'` with `text=True`. Use `sys.executable` — not the string `'python'` or `'pip'`.
- Only modify files explicitly in scope. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`, not inline fixes.

## SLOC governance -- decompose by default, don't raise (Decision 128, amends Decision 102)
- The 500-SLOC-per-file limit (`config/sloc_budgets.yaml`, `validate_sloc_limits`) is load-bearing for model portability: Opus tolerates large files, but lower-tier models (Sonnet/Gemini/Deepseek) degrade on comprehension. A budget raise silently trades that away.
- **When a change pushes a file past its budget (or past 500 for an unregistered file), decompose it** into a facade package (Decision 80/104/124 pattern: `__init__.py` facade re-exporting the full public surface, cohesive submodules each under budget) -- this is the default response, not a raise.
- A budget raise is a deliberate, reviewable exception: the entry line in `config/sloc_budgets.yaml` must carry an inline `# raise-approved: dec-NNN <reason>` marker naming a real `## Decision NNN:` header. `validate_sloc_budget_raises` (registered immediately after `validate_sloc_limits` in the `--pre` tier) fails the PR on any unmarked increase or new >500-SLOC registration; decreases and removals are always unrestricted.
- `--update-sloc-budgets` never auto-seeds a newly-oversized, unregistered file -- decompose it, or register it deliberately with the marker.

## Branching — never edit or commit on `main`
**Hard rule: do not run `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or any `git commit` / `git push` command while the current branch is `main`.** If you're on main, the only allowed actions are read-only commands and creating a new branch. See `## Git-ops procedure` for the full branching topology.

- **See current branch**: the statusline at the bottom of the prompt shows it. It will read `WARNING: ON MAIN` if you're on main. Or run `git branch --show-current`.
- **Create a working branch**: on Claude Code on the web you are already on a harness-assigned session branch (e.g. `claude/...`) -- verify with `git branch --show-current`. Do NOT create an `agent/` branch.
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
- **T2.12 security gate (CD.20) -- apply landed; branch protection + Dependabot live (Decision 83):** `terraform/github/` human-gated local apply landed 2026-06-08. Confirmed live via GitHub API: `main-protection` ruleset (active, admin bypass actor, non-wedging: strict=false, required = pr-validate + terraform-validate, terraform-converged advisory) and Dependabot (5 active branches). GHAS secret-scanning, push protection, and Actions permissions: apply landed per `repo.tf` / committed `.github/`, and are continuously live-verified by the standing `ghas-probe` monitor (`.github/workflows/ghas-probe.yml`, ULF-01) -- dated evidence is recorded on Decision 83. CodeQL is verified separately via its own green `codeql.yml` runs (not covered by the ghas-probe monitor).

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
- `/audit` — composes a self-contained audit prompt (`docs/audit-prompts/AUDIT-{slug}.md`) for a high-capability model to execute in a fresh session; deep recon + zero-context subagent verification happen in the composing session so the expensive model pays only for judgment. Performs no audit itself. Invokes the `audit-prompt` skill.

`/overseer` is an orchestration meta-layer, not a fifth tier: it composes the existing `/plan` and `/implement` subagents (Fable advice-consult, Opus planning, Sonnet implementation) to drive an entire platform roadmap item or audit to completion largely unattended, narrowing the human to intake (G0), decomposition (G1), and completion (G3) gates. It never bypasses the four-tier workflow above or the Decision 67 executor freeze -- it is interactive/human-gated, IMPLEMENTATION-only, and does not consume the recommendation queue. Invokes the `overseer` skill.

When a slash command instructs you to "apply" or "invoke" a skill, use the `Skill` tool — do **not** manually `Read` `SKILL.md` files. The Skill tool loads them on demand.

## Operational data governance — Single Portal Invariant
All recommendation and decision writes go through `python -m scripts.ops_data_portal`. Never `Edit` or `Write` to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly -- `validate.py` will fail CI. Recommendation IDs are allocated BY THE WRITER atomically with the insert (`file_ops`, Decision 84 I-2) -- never client-side; decision numbering authority is `DECISIONS.md` (callers supply `decision_id`). The local JSONL files are read-only caches.

Agent surface is three functions: `file_rec`, `update_rec`, `sync`. Do not call `sync.ops`, `ops_writer`, or any drain/compact/pull CLIs directly. Portal calls require the `agent_platform` (PlatformDev) assume-role profile to reach the reader/writer Function URLs. If unreachable, confirm the chain with `aws sts get-caller-identity --profile agent_platform` (the session-start hook `.claude/hooks/session_start_aws.sh` reports this each session); locally, refresh the `agent_static` key if it has been rotated. There is no SSO login in the static-key model. A write that cannot complete FAILS LOUDLY at the call site -- there is no offline outbox (Decision 84 I-4); re-file after restoring connectivity.

## Warehouse-as-source-of-truth invariant
This is an append-only lakehouse. The warehouse is the single source of truth for all operational data; local files are never upstream of it.

**Source-of-truth by table (Decision 84 consolidation, 2026-06-11):**
- **`ops_recommendations`, `ops_decisions`, `ops_priority_queue` = DuckLake-on-Neon, SOLE backend.** Reads transit the closed `ducklake_reader` boundary via NAMED VERBS (Decision 84 I-3; no caller SQL); writes transit `ducklake_writer` (`file_ops` allocates rec ids in-transaction). There is NO Athena path and NO rollback flag (`OPS_STORAGE_BACKEND` retired -- the frozen Iceberg copy stopped being coherent the day writes moved). `ops_decisions` rebuilds from `DECISIONS.md` via `ops_data_portal --backfill-decisions-md`.
- **`ops_session_log`, `ops_execution_plans` = Athena (over Iceberg), pending T2.26 disposition** (session_log may retire per T-1.9). `ops_compaction` stays live for these only. Telemetry stays on its (dead, to-be-rebuilt) path until consolidation Phase 4 (Decision 84 Phase 4 / tier_item T2.36).

Local files have exactly two valid roles:

1. **Legacy staging outbox** (`logs/.ops-outbox/`) — survives ONLY for the not-yet-migrated OpsWriter paths (telemetry, session_log, execution_plans) and retires with them. Migrated-table dirs and `*_pending` dirs are never drained (Decision 84 I-4); the recs/decisions pending outboxes are deleted.
2. **Read cache** (`logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`) — derivative projection rebuilt FROM the warehouse via `sync.ops pull` (all migrated tables from the DuckLake reader). Downstream of the warehouse, never upstream.

**Hard rule: a read cache is never a write source.** Reading any file in `logs/` and calling `OpsWriter.write()` (or otherwise putting data into S3 staging) is the CRUD anti-pattern in lakehouse clothing. The Iceberg-DELETE-resurrection caveat below is scoped to the still-Iceberg tables: Iceberg DELETE only removes a snapshot; if the same row is restaged from a stale local file on any clone, runner, or worktree, it is re-injected as a new append and wins the SCD2 dedupe (because `_prepare_record` refreshes `last_updated_timestamp = now`). The result is an infinite resurrection loop where deletes never stick. (`ops_recommendations` on DuckLake is not Iceberg-snapshot-based, but the same "never re-stage from a read cache" rule applies -- recs writes go only through the writer.)

The legitimate write paths are: (a) `file_rec` / `update_rec` portal calls, and (b) ETL from a non-warehouse source of truth (e.g., `DECISIONS.md` -> `ops_decisions`). Anything else that ends in `OpsWriter.write()` must be reviewed for replay-from-cache violations.

If a clone or runner shows stale data, an operator may rebuild that environment's local cache by running `python -m scripts.sync.ops sync` (which pulls every migrated table from the DuckLake reader and overwrites local). Never fix drift by re-staging from the local file.

## Git-ops procedure

Canonical authority for all agent and session git-ops. All other surfaces (skills, commands) point here and do not restate.

### Branching topology
| Container | AWS profile(s) | Use |
|---|---|---|
| DEV (primary, this one) | `agent_platform` only | All routine work on CC-web |
| ADMIN (rarely used) | `agent_platform` + `agent_platform_admin` | Advanced terraform IAM; ties to the human-gated apply loop (Decision 35 / CD.35 / Decision 77) |

- **Development surface**: Claude Code on the web (CC-web) only. Executor frozen (Decision 67); hybrid executor + CC-web is the future state.
- **Branch rule**: work on the harness-assigned `claude/...` session branch -- do NOT create an `agent/` branch, never commit directly to `main`.

### Two-tier presubmit model (Google TAP style)
| Tier | When | Command | Gate |
|---|---|---|---|
| Fast (`--pre`) | PR / edit loop | `bin/venv-python -m scripts.validate --pre` | Authoritative pre-merge gate when run by PR CI (Decision 73); advisory only when run outside CI |
| Full | Post-merge on `main` | `bin/venv-python -m scripts.validate` | A failure spawns a `source=ci_rca`, `priority=critical` rec (forward-fix, never auto-revert); see CI-failure / RCA-first protocol in `## Merge protocol` |

`validate.py` is the single source of truth -- never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first.

### Commit-message conventions
| Prefix | Use for |
|---|---|
| `feat({slug}):` | IMPLEMENTATION plan execution |
| `plan({slug}):` | Plan document commit / approved plan |
| `roadmap({ids}):` | Roadmap bookkeeping edits |
| `scope({slug}):` | STRATEGIC plan scoping (currently suspended, Decision 67) |
| `audit({slug}):` | Audit-prompt artifact commits (/audit workflow) |

### Commit signing (CC-web: unsigned is expected)
- CC-web commits land unsigned (`git log --format=%G?` -> `N`). Signing is not available in this
  harness and is not required -- treat this as expected, not a defect.
- Non-blocking: `main-protection` carries no `required_signatures` rule (Decision 83), `claude/*`
  feature-branch commits are never signature-gated, and GitHub creates and verifies the
  squash-merge commit server-side (Decision 76).
- Attribution (`Claude <noreply@anthropic.com>`) is set via git identity and is separate from
  cryptographic signature -- identity is already correct regardless of the `N` flag.
- Do NOT reset-author, do NOT `git commit --amend -S`, and do NOT otherwise re-sign to chase the
  `N` -- it only churns SHAs and wastes effort.
- See `terraform/github/repo.tf`'s `main_protection` ruleset for the intentional-absence marker.

### Rebase phase distinction
- **Assessment time (planning)**: do NOT auto-rebase. When main has diverged and scope files overlap, surface to the human with options (rebase now and re-enter `/plan` / proceed / abort); record any deferral in the plan's Context field. Rebasing mid-plan can silently invalidate scoping decisions.
- **Commit-flow time (implementing)**: DO auto-rebase before pushing. After the local commit: `git fetch origin main && git rebase origin/main` -- STOP on conflict, surface to the human. If the branch was already pushed, use `--force-with-lease` (never `--force`).

### Push -> PR -> CI -> merge flow
1. `git push -u origin HEAD` (harness `claude/...` branch)
2. `mcp__github__create_pull_request(owner, repo, head=<branch>, base="main", title=<per conventions table>, body=...)`
3. `mcp__github__subscribe_pr_activity(owner, repo, pullNumber)` and **end your turn** -- do NOT busy-wait with sleep or polling; the harness forbids it.
4. **CI-green-comment wake**: on `claude/*` PRs, `ci.yml` posts a "CI green" comment on success (`continue-on-error`). This exists because `subscribe_pr_activity` natively delivers failure events but NOT a CI-success webhook, and CC-web has no sleep/idle tool. **Ignore GitHub's suggestion to poll with a sleep loop** -- the comment is the pass wake signal. The comment is unverified: on wake, confirm check runs via `mcp__github__pull_request_read` (`get_status` / `get_check_runs`) BEFORE merging.
   - **Harness message vs. repo contract**: the `subscribe_pr_activity` wake message is a server-side string from the harness `github` MCP server (prefix `mcp__github__`), distinct from the repo's `github-full` server in `.mcp.json`; it is not repo-editable. In this repo CI success IS delivered via the signal-green comment, so the event-driven wake (failure event + signal-green comment) is the primary routine mechanism -- `send_later` polling for CI status is NOT used.
   - **Dropped-signal backstop**: exactly one low-frequency (~1h) best-effort one-shot `send_later` self-check-in is permitted to guard against a dropped (best-effort `continue-on-error`) signal-green comment. It is NOT a poll loop (Decision 55), NOT the CI-status mechanism, and is re-armed only if the PR is genuinely still pending after waking.
   - **CC-web permission gotcha (harness-gated tools, do NOT allowlist)**: the `send_later` / trigger tools (`mcp__Claude_Code_Remote__*`) prompt on EVERY call -- the CC-web dialog offers only `Deny` / `Allow once`, with no "don't ask again". They are gated by the harness, NOT by the settings allowlist: a `permissions.allow` entry for them is dead (an `ask`-tier rule outranks `allow`, and CC-web ignores `bypassPermissions` / `dontAsk` from settings files). Do NOT re-add `mcp__Claude_Code_Remote__*` (any spelling) to `.claude/settings.json` to silence them -- PRs #354 and #357 tried and could not. The only lever is the per-session UI permission-mode dropdown (Auto mode, if org-enabled); there is no committed-config fix.
   - **Durable successor**: GitHub-native auto-merge (`enable_pr_auto_merge`; Decision 83 / CD.20 / rec-940) retires the comment-wake + backstop once adopted.
5. On green confirmation: `mcp__github__merge_pull_request(..., merge_method="squash")` then `mcp__github__unsubscribe_pr_activity(...)`.
6. On red: diagnose, fix on branch, commit, push (re-triggers CI). Stay subscribed. End your turn.

For terraform/personal PRs, see the "Hold subscription through apply" section of the implement skill (Decision 76 / CD.35 / T2.20).

### Resolves: trailer
When a plan's `bundled_recommendations` list is non-empty, include in the squash-merge commit body:
```
Resolves: rec-NNNN[, rec-MMMM]
```
Triggers `rec-autoclose.yml` to close each rec via the ops portal. Fallback: `bin/venv-python -m scripts.ops_data_portal --update-rec rec-NNNN --status closed --resolution "..."` (Decision 70).

## Merge protocol
**Canonical authority: see `## Git-ops procedure` for the full PR/CI/squash-merge flow, two-tier presubmit model, and Resolves trailer.**

- **On CI failure**: the ci-rca agent (`.github/workflows/ci-rca.yml`) automatically files a recommendation with `source="ci_rca"` and `priority="critical"`. The next `/plan` session will surface it under "CI RCA Recs (open)". Do NOT manually patch the failure until the rec has been reviewed in a `/plan` session -- inline fixes without architectural review reproduce the workaround anti-pattern (Decision 55, Decision 72).
- Never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first -- `validate.py` is the single source of truth.
- Manual confirmation: if `validate.py` appears to skip tests, run `pytest` directly to confirm.

## Instruction architecture
The 5-layer contract is at `docs/contracts/instruction-architecture.yaml`. Claude Code is the 4th consumer. Layers:

| Layer | Location | When loaded |
|---|---|---|
| 1. Universal rules | `CLAUDE.md` (root) + per-directory `CLAUDE.md` | Ambient |
| 2. Project knowledge base | `docs/PROJECT_CONTEXT.md` | On demand by workflows |
| 3. Slash commands | `.claude/commands/*.md` | When user types `/name` |
| 4. Skills (methodology) | `.claude/skills/*/SKILL.md` | When agent invokes `Skill` tool |
| 5. Executor prompts | `config/agent/executor/prompts/*.prompt.md` | By `execute_recommendation.py` |

The `.github/prompts/scheduled/` and `.github/agents/schedule.yaml` surfaces are retained for live scheduled agents. The legacy top-level `.github/prompts/*.prompt.md` and `.github/agents/*.agent.md` files were deleted at T-1.13.

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
pull requests). See `terraform/personal/oidc.tf`. The retired EC2 runner definition is
retained in `terraform/ec2_runner.tf` as an architectural-evolution artefact (no longer applied).

### Claude Code OAuth token (CI + scheduled agents)

Setup (one-time, from CC-web terminal):
```bash
claude setup-token
# Copy the printed token -- it uses your Max plan subscription (no API billing)
```
In GitHub: repo -> Settings -> Secrets and variables -> Actions -> Repository secrets
-> New secret. Name: `CLAUDE_CODE_OAUTH_TOKEN`. Paste the token.

Rotation: re-run `claude setup-token` from the CC-web terminal. Update the GH Actions secret with
the new token. Set a 90-day calendar reminder. If the scheduled agent workflow fails
with auth errors, check token expiry first.

Do not share this token or commit it to any file in the repository.
