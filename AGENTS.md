# AGENTS.md — ML Trading System

Universal rules. For full project context, see `docs/PROJECT_CONTEXT.md` on demand.

## PUBLIC repository / confidential-data boundary

This repository is PUBLIC (Decisions 73, 83, 101). Public-content boundary (Decision 101):
- NEVER publish: AWS account IDs or ARNs, IAM ExternalIds, credentials or API keys, trading alpha / strategy performance, or any internal hostname that provides an attack surface.
- SAFE to publish: platform engineering, infrastructure patterns, tooling, CI/CD design, and general LLM-agent architecture -- market the engineering, not the alpha.
- Confidential data lives ONLY in: the personal AWS account (Secrets Manager, gitignored tfvars, S3 private prefixes), and gitignored local files (e.g. `terraform/personal/terraform.personal.tfvars`, `~/.aws/credentials`). Nothing confidential is ever committed.
- The pre-commit `never-commit` hook (shape-pattern) blocks 12-digit AWS account IDs, secret-like strings, and ExternalId patterns from reaching the repo.

## Role and environment
You are a Lead Software Developer writing production-quality Python. Primary dev surface: Claude Code on the web
(CC-web; Ubuntu 24.04). PySR runs on a separate compute node. Bash is the primary shell.

## Code style
- Python 3.12+, type hints required, `async` for I/O.
- Every behavior-changing code, script, workflow, hook, or configuration edit must add or update
  an automated test that fails without the change; running an existing suite is not a substitute.
- ruff formatting; line length 127.
- No emojis in code, scripts, or documentation. Use plain ASCII hyphens (`-`) instead of em dashes.
- Default to no comments. Only add a comment when the *why* is non-obvious.
- Use Bash syntax in scripts; never emit PowerShell unless explicitly asked.

## Shell invocations
- Always invoke `bin/venv-python` instead of `python` or `python3`.
- Each Bash tool invocation is independent -- do not rely on `source .venv/bin/activate` or `source .venv/Scripts/activate`; use `bin/venv-python` directly instead.

## Safety
- Never `eval()` or `exec()`. Use `sympy.sympify()` + `sympy.lambdify()` for formula evaluation.
- Never raise exceptions during module import. Defer validation to explicit calls.
- Always wrap `filemd5()` and `file()` Terraform calls on optional artifacts with `try()`.
- Terraform apply model: see `environment-taxonomy.yaml` (Axis A + Guard classification subsection) -- that file is the sole SoT. Short form: sandbox auto-applies behind the deterministic guard (Decision 77); in-budget IAM inline-policy/attachment UPDATEs on managed boundary-carrying roles now auto-apply (T2.25 / Decision 92 point 5); trust/destroy/out-of-budget IAM route to the `tf-gated-apply` Environment. Bootstrap root is admin-only out-of-band.
- **Deployment model (Decision 126):** three agent intents, one trigger each -- infra = open a PR touching `terraform/**`, CI plans and applies; code = the governed code-deploy channel (Terraform not involved); red/drift = run the one-input Reconcile action. Agents never run terraform apply as a self-directed, routine action -- the sole exception is the human-gated break-glass admin tier (below/`terraform/CLAUDE.md`), where a human reviews and explicitly directs the apply before an agent executes it; operators may always invoke it directly. See `docs/contracts/deploy-paths.yaml` for the full intent -> trigger -> recovery index (it points at, and never restates, this file's apply-model/guard rules).
- **Lambda deploy channel (Decision 125/126):** the five DuckLake Lambdas' code is decoupled from `terraform/personal` infra apply as of #544 (see `environment-taxonomy.yaml` (conformance) and `docs/contracts/build-lambda.yaml`'s `deploy_channels`) and deploy through a governed code-deploy CD channel; `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` is break-glass-only, never the routine default. See `docs/contracts/deploy-paths.yaml` for the authoritative channel status. Heuristic: when a production action (e.g. a Lambda code deploy) is auto-denied or has no obvious in-session path, check `docs/contracts/deploy-paths.yaml` first, then grep `.github/workflows/` for a governed CD path before falling back to a local permission grant.
- Windows subprocess: pass `encoding='utf-8', errors='replace'` with `text=True`. Use `sys.executable` — not the string `'python'` or `'pip'`.
- Only modify files explicitly in scope. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`, not inline fixes.

## SLOC governance -- decompose by default, don't raise (Decision 128, amends Decision 102)
- The 500-SLOC-per-file limit (`config/sloc_budgets.yaml`, `validate_sloc_limits`) is load-bearing (rationale: Decision 128) -- a raise is never a frictionless edit.
- **When a change pushes a file past its budget (or past 500 for an unregistered file), decompose it** into a facade package (Decision 80/104/124 pattern: `__init__.py` facade re-exporting the full public surface, cohesive submodules each under budget) -- this is the default response, not a raise.
- A budget raise is a deliberate, reviewable exception: the entry line in `config/sloc_budgets.yaml` must carry an inline `# raise-approved: dec-NNN <reason>` marker naming a real `## Decision NNN:` header that AUTHORIZES the entry (Decision 165) -- `validate_sloc_budget_raises` fails the PR on any unmarked increase, new >500-SLOC registration, or unauthorized marker; decreases and removals are always unrestricted.
- `--update-sloc-budgets` never auto-seeds a newly-oversized, unregistered file -- decompose it, or register it deliberately with the marker.

## Branching — never edit or commit on `main`
**Hard rule: do not run `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or any `git commit` / `git push` command while the current branch is `main`.** If you're on main, the only allowed actions are read-only commands and creating a new branch. See `## Git-ops procedure` for the full branching topology.

- **See current branch**: the statusline at the bottom of the prompt shows it. It will read `WARNING: ON MAIN` if you're on main. Or run `git branch --show-current`.
- **Create a working branch**: on Claude Code on the web you are already on a harness-assigned session branch (e.g. `claude/...`) -- verify with `git branch --show-current`. Do NOT create an `agent/` branch.
- A `PreToolUse` hook at `.claude/hooks/never_on_main.py` enforces this at the harness level: it blocks `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, and `Bash(git commit/push ...)` while on `main`. Other Bash commands (e.g. `git status`, `ls`) still run.

## Temporary Operational Constraints
- **STRATEGIC plans suspended (Decision 67):** during this window all plans must be
  IMPLEMENTATION type -- STRATEGIC plan-type declarations are refused (enforced by /plan,
  the planning skill, and plan-critique). The planning skill's complexity heuristic (>5 files
  or >8 steps) is also suspended -- author the work as a single larger IMPLEMENTATION plan OR
  split it into multiple atomic IMPLEMENTATION plans yourself. Restores when CD.17 / T4.2
  reverses.
- **Lambda deployment -- per-Lambda gating (Decision 79, CD.16 + CD.24):** gating is per-Lambda,
  not blanket. Active artifacts (`status: active` in `src/lambdas/<slug>/manifest.yaml`) require
  build + deploy + smoke-test (V3 tier); stub artifacts do not. `config/agent/` is NOT
  Lambda-packaged. See the planning skill for the affected-artifact detection method.

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
- Precision Context Injection: call `get_rec_write_guidance()` before `file_rec()` so
  LLM-judgment fields (title, context, acceptance) get authoritative field semantics before
  composition, not as a post-rejection error (rationale: Decision 66).
- No new standing prose-architecture docs (Decision 86): forward intent to tier_items,
  rationale to Decisions, field semantics to contracts. Creating docs/INTENT-*.md or any
  equivalent standing prose-architecture doc under docs/ is forbidden. The validate.py
  intent-doc-freeze guard enforces this on-disk.

## Skills and slash commands

Decision 90 four-tier workflow (end-goal: /orient -> /plan -> /implement -> /develop-executor; current: /orient -> /plan -> /implement, executor frozen per Decision 67):
- `/orient` — read-only orientation: surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Run before `/plan` to choose what to work on. Produces a chat reply only; writes nothing. Invokes the `orient` skill.
- `/plan` — clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.yaml`. Assumes a specific item has been chosen (run `/orient` first). Invokes the `planning` skill.
- `/implement` — executes an IMPLEMENTATION plan or scopes a STRATEGIC plan into recommendations. Invokes the `implement` and `code-review` skills.
- `/develop-executor` — supervisor for executor (Lambda) development.
- `/audit` — composes a self-contained audit prompt (`docs/audit-prompts/AUDIT-{slug}.md`) for a high-capability model to execute in a fresh session; deep recon + zero-context subagent verification happen in the composing session so the expensive model pays only for judgment. Performs no audit itself. Invokes the `audit-prompt` skill.

`/overseer` is an orchestration meta-layer, not a fifth tier: it composes the existing `/plan`
and `/implement` subagents to drive an entire platform roadmap item or audit to completion largely
unattended, with the human gating intake and completion. It never bypasses the four-tier workflow
above or the Decision 67 executor freeze -- it is interactive/human-gated, IMPLEMENTATION-only, and
does not consume the recommendation queue. Invokes the `overseer` skill.

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

**Hard rule: a read cache is never a write source.** Reading any file in `logs/` and calling
`OpsWriter.write()` (or otherwise putting data into S3 staging) is the CRUD anti-pattern in
lakehouse clothing. The Iceberg-DELETE-resurrection mechanism that makes this dangerous on the
still-Iceberg tables is recorded in Decision 84 (`ops_recommendations` on DuckLake is not
Iceberg-snapshot-based, but the same rule applies -- recs writes go only through the writer).

The legitimate write paths are: (a) `file_rec` / `update_rec` portal calls, and (b) ETL from a non-warehouse source of truth (e.g., `DECISIONS.md` -> `ops_decisions`). Anything else that ends in `OpsWriter.write()` must be reviewed for replay-from-cache violations.

If a clone or runner shows stale data, an operator may rebuild that environment's local cache by running `python -m scripts.sync.ops sync` (which pulls every migrated table from the DuckLake reader and overwrites local). Never fix drift by re-staging from the local file.

## Data-modeling default
Before designing any table, decide **grain first** -- "one row per ___" -- then pick a write mode. This is
not a CRUD default: never design a table as "one row per entity, mutate in place." Full rules, the
write-mode table, and index pointers live in `docs/contracts/data-modeling-standard.yaml`; this is the
ambient summary.

- **Grain first.** Name the grain in one sentence before anything else (e.g. "one row per rec_id",
  "one row per event_id"). If you cannot state the grain, you are not ready to pick a write mode.
- **Write-mode branch (not "default to SCD2"):**
  - **SCD2** (history table + Type-1 current projection) for mutable-entity ops tables -- rows that get
    updated over their lifetime (e.g. `ops_priority_queue`, `ops_session_log`, `ops_execution_plans`).
  - **append_only** (history-only event journal, no current projection) for event/telemetry tables --
    insert-once rows that are never mutated (e.g. `ops_smoke_events`, the telemetry_* tables).
  - **append_only is the design default/prior, NOT a ban** on sanctioned exceptional physical deletes
    (Decision 70) or lifecycle-closure paths (Decision 103) -- those remain legitimate, scoped exceptions.
- **Identity**: ULID, minted once at the write boundary (never client-side, never a natural-key PK),
  propagated to children as FKs.
- **Merge-on-business-key**: SCD2 merges key off the table's business key, not a surrogate row id.
- **Partition every table** (CD.9) -- no unpartitioned table, event-time for append_only, mutation-time
  for SCD2 current/history as appropriate.
- **A read cache is never a write source** (see Warehouse-as-source-of-truth invariant above).

At design time (planning a table, a `field_semantics` entry, or a warehouse write path), the `planning`
skill's Data-Model Assessment walks grain -> merge_key/history-current -> identity -> join keys -> write
mode -> partitioning -> reject-CRUD checklist -> Fable escalation for load-bearing calls. See
`docs/contracts/data-modeling-standard.yaml`.

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
| Full | Pre-handoff (local) + post-merge on `main` | `bin/venv-python -m scripts.validate` | A failure spawns a `source=ci_rca`, `priority=critical` rec (forward-fix, never auto-revert); see CI-failure / RCA-first protocol in `## Merge protocol` |

`validate.py` is the single source of truth -- never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first.

### Commit-message conventions
| Prefix | Use for |
|---|---|
| `feat({slug}):` | IMPLEMENTATION plan execution |
| `plan({slug}):` | Plan document commit / approved plan |
| `roadmap({ids}):` | Roadmap bookkeeping edits |
| `scope({slug}):` | STRATEGIC plan scoping (currently suspended, Decision 67) |
| `audit({slug}):` | Audit-prompt artifact commits (/audit workflow) |

**Change-record content rule.** What changed, why now, acute state, and measurements belong in
the squash-commit or PR body -- never in a Decision entry body. Whether content clears the bar
for a numbered Decision at all, and where it routes when it does not, is governed by
`docs/contracts/decision-entry.yaml`'s `significance.routing_rule` and its four routing rows
(Decision 167 clause 4); this file points at that rule rather than restating it.

**DD-B convention.** When a drafted Decision is blocked on routing grounds -- redirected to one
of `decision-entry.yaml`'s other three routing rows instead of `numbered_decision` -- the
superseding PR body names the routing row applied in one line (e.g. "Routing: field_semantics ->
docs/contracts/<file>.yaml").

### Commit signing (CC-web: SSH-signed via harness signer)
- CC-web commits ARE SSH-signed (commit.gpgsign=true, gpg.format=ssh, host-held key); GitHub
  reports them Verified.
- Local `git log --format=%G?` reads `N`/`B` only because this container cannot verify SSH
  signatures locally (no ssh-keygen) -- not evidence of a missing signature.
- `session_start_commit_signing.py` sets `gpg.ssh.allowedSignersFile` so the harness Stop hook's
  signature check stops false-positiving. If it still fires, check which half: the committer-email
  half (`%ce != noreply@anthropic.com`) is a real trigger whose remediation is correct.
- Do NOT reset-author or `git commit --amend -S` to chase the signature flag -- it only churns
  SHAs.

### Rebase phase distinction
- **Assessment time (planning)**: do NOT auto-rebase. When main has diverged and scope files overlap, surface to the human with options (rebase now and re-enter `/plan` / proceed / abort); record any deferral in the plan's Context field. Rebasing mid-plan can silently invalidate scoping decisions.
- **Commit-flow time (implementing)**: DO auto-rebase before pushing. After the local commit: `git fetch origin main && git rebase origin/main` -- STOP on conflict, surface to the human. If the branch was already pushed, use `--force-with-lease` (never `--force`).

### Local main sync
`session_start_sync_main.sh` syncs local main -> origin/main. `fresh_branch_base.py`
refreshes/blocks branch cuts off stale main. origin/main is itself a cache (Decision 84); no
signing hook, rebase is safe.

### Push -> PR -> CI -> merge flow
1. `git push -u origin HEAD` (harness `claude/...` branch)
2. `mcp__github__create_pull_request(owner, repo, head=<branch>, base="main", title=<per conventions table>, body=...)`
3. `mcp__github__subscribe_pr_activity(owner, repo, pullNumber)` and **end your turn** -- do NOT busy-wait with sleep or polling; the harness forbids it.
4. **Event-driven wake signals**: two comment-based signals cover what `subscribe_pr_activity`
   cannot deliver natively -- CI success, and a merge-conflict transition from a push to main.
   - **CI-green-comment wake**: `ci.yml`'s `signal-green` job posts a "CI green" comment on
     `claude/*` PRs on success (`continue-on-error`, retried up to 3 times). This exists because
     `subscribe_pr_activity` delivers failure events but NOT a CI-success webhook, and CC-web has
     no sleep/idle tool. **Ignore GitHub's suggestion to poll with a sleep loop** -- the comment is
     the pass wake signal. Unverified: confirm check runs via `mcp__github__pull_request_read`
     (`get_status` / `get_check_runs`) before merging.
   - **Merge-conflict wake**: `.github/workflows/pr-conflict-signal.yml` fires on every push to
     main, polls open `claude/*` PR mergeability, and posts a wake comment (idempotent per head
     SHA, `continue-on-error`) on any PR now `CONFLICTING`. This exists because a push to main
     fires NO `pull_request` event on open PRs, so the `pull_request`-only signal-green job cannot
     deliver this wake -- a silently-conflicted PR would otherwise strand the watching session
     indefinitely.
   - `send_later`/trigger calls for CI-wait or merge-conflict-wait purposes are out of scope --
     both gaps `subscribe_pr_activity` cannot cover natively are now closed by the comments above.
   - **CC-web permission gotcha (harness-gated tools, do NOT allowlist)**: the `send_later` / trigger tools (`mcp__Claude_Code_Remote__*`) prompt on EVERY call -- the CC-web dialog offers only `Deny` / `Allow once`, with no "don't ask again". They are gated by the harness, NOT by the settings allowlist: a `permissions.allow` entry for them is dead (an `ask`-tier rule outranks `allow`, and CC-web ignores `bypassPermissions` / `dontAsk` from settings files). Do NOT re-add `mcp__Claude_Code_Remote__*` (any spelling) to `.claude/settings.json` to silence them -- PRs #354 and #357 tried and could not. The only lever is the per-session UI permission-mode dropdown (Auto mode, if org-enabled); there is no committed-config fix.
   - Auto-merge (`enable_pr_auto_merge`; Decision 83 / CD.20 / rec-940) retires the CI-green
     comment-wake once adopted, but does NOT subsume the merge-conflict wake -- a conflicted PR
     simply stalls auto-merge and wakes no one, so pr-conflict-signal.yml stays necessary even
     after auto-merge lands.
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
- Manual confirmation: if `validate.py` appears to skip tests, run `pytest` directly to confirm.

## Instruction architecture
The layered contract (Layer 1 universal rules through Layer 5 executor prompts) is at
`docs/contracts/instruction-architecture.yaml` -- see it for the full layer table.

The `.github/prompts/scheduled/` and `.github/agents/schedule.yaml` surfaces are retained for
live scheduled agents. The legacy top-level `.github/prompts/*.prompt.md` and
`.github/agents/*.agent.md` files were deleted at T-1.13.

## Operational runbooks

### Claude Code OAuth token (CI + scheduled agents)

Setup (one-time, from CC-web terminal):
```bash
claude setup-token
# Copy the printed token -- it uses your Max plan subscription (no API billing)
```
In GitHub: repo -> Settings -> Secrets and variables -> Actions -> Repository secrets
-> New secret. Name: `CLAUDE_CODE_OAUTH_TOKEN`. Paste the token. Rotation procedure and expiry
tracking live in `.github/workflows/ghas-probe.yml`'s header.

Do not share this token or commit it to any file in the repository.
