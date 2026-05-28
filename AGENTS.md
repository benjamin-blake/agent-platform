# AGENTS.md — ML Trading System

Universal rules for Claude Code. Auto-loaded into every session.
For full project context (AWS config, file router, recommendation schema, gotchas), see `docs/PROJECT_CONTEXT.md` — workflows load it on demand; you don't need it ambiently.

## Role and environment
You are a Lead Software Developer writing production-quality Python. The user is a sole developer building a self-improving automated trading system on AWS. Primary dev surface: Claude Code on the web (Linux container, Ubuntu 24.04). compute node is the PySR compute node, reached via REDACTED-VPN + SSH when needed. Bash is the primary shell in all agent-facing contexts.

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
- Windows subprocess: pass `encoding='utf-8', errors='replace'` with `text=True`. Use `sys.executable` — not the string `'python'` or `'pip'`.
- Only modify files explicitly in scope. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`, not inline fixes.

## Branching — never edit or commit on `main`
**Hard rule: do not run `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or any `git commit` / `git push` command while the current branch is `main`.** If you're on main, the only allowed actions are read-only commands and creating a new branch.

- **See current branch**: the statusline at the bottom of the prompt shows it. It will read `WARNING: ON MAIN` if you're on main. Or run `git branch --show-current`.
- **Create a working branch**: `git checkout main && git pull && git checkout -b agent/{slug}`.
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
  Restores when Decision 67 / CD.17 reverses.
- **Lambda deployment deferred (Decision 67):** The Lambda dispatcher is disabled. Plans
  touching Lambda-packaged files (`config/config.yaml`, `config/lambda/<name>/`, `scripts/llm_client.py`, `src/data/handlers/`,
  `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`) must include a
  `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test
  (pending Decision 67 reversal)` execution step in lieu of active deployment steps.

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

## Skills and slash commands
- `/plan` — clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.md`. Invokes the `planning` skill.
- `/implement` — executes an IMPLEMENTATION plan or scopes a STRATEGIC plan into recommendations. Invokes the `implement` and `code-review` skills.
- `/develop-executor` — supervisor for executor (Lambda) development.

When a slash command instructs you to "apply" or "invoke" a skill, use the `Skill` tool — do **not** manually `Read` `SKILL.md` files. The Skill tool loads them on demand.

## Operational data governance — Single Portal Invariant
All recommendation and decision writes go through `python -m scripts.ops_data_portal`. Never `Edit` or `Write` to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly -- `validate.py` will fail CI. IDs are allocated atomically via DynamoDB; the local JSONL files are read-only caches.

Agent surface is three functions: `file_rec`, `update_rec`, `sync`. Do not call `sync_ops`, `ops_writer`, or any drain/compact/pull CLIs directly. `update_rec` requires Athena connectivity (SSO). If unreachable, run `aws sso login --profile company-aws-profile` first.

## Warehouse-as-source-of-truth invariant
This is an append-only lakehouse. Athena (over Iceberg) is the single source of truth for all operational data. Local files have exactly two valid roles:

1. **Outbox** (`logs/.ops-outbox/`) — write-ahead buffer for offline writes. Drained once into S3 staging, then deleted. Never replayable. Each entry is a *new write that has not yet propagated*, never a *replay of an existing warehouse row*.
2. **Read cache** (`logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`) — derivative projection rebuilt FROM Athena via `sync_ops pull`. Downstream of the warehouse, never upstream.

**Hard rule: a read cache is never a write source.** Reading any file in `logs/` and calling `OpsWriter.write()` (or otherwise putting data into S3 staging) is the CRUD anti-pattern in lakehouse clothing. Iceberg DELETE only removes a snapshot; if the same row is restaged from a stale local file on any clone, runner, or worktree, it is re-injected as a new append and wins the SCD2 dedupe (because `_prepare_record` refreshes `last_updated_timestamp = now`). The result is an infinite resurrection loop where deletes never stick.

The legitimate write paths are: (a) `file_rec` / `update_rec` portal calls, and (b) ETL from a non-warehouse source of truth (e.g., `DECISIONS.md` -> `ops_decisions`). Anything else that ends in `OpsWriter.write()` must be reviewed for replay-from-cache violations.

If a clone or runner shows stale data, an operator may rebuild that environment's local cache by running `python -m scripts.sync_ops sync` (which pulls from Athena and overwrites local). Never fix drift by re-staging from the local file.

## Merge protocol
- **Authoritative pre-merge gate**: remote CI (`validate.py` on the self-hosted runner, Decision 68) is the authoritative gate. A branch is not merge-ready until CI passes.
- **Local `--pre` is advisory only**: `python -m scripts.validate --pre` runs lint/format/prompts only. It shortens the edit loop but does NOT gate merges. Passing `--pre` locally does not mean CI will pass.
- **Full presubmit**: `python -m scripts.validate` (no flags) runs the full check suite identical to CI. Use this locally before pushing to reduce round trips, but CI is still authoritative.
- Two-tier model: presubmit (default, no flags) + `--pre` (edit-loop). Decision 60 migration complete per `docs/INTENT-validation-architecture.md`.
- Never add a check to `.github/workflows/ci.yml` without adding it to `validate.py` first -- `validate.py` is the single source of truth.
- Manual confirmation: if `validate.py` appears to skip tests, run `pytest` directly to confirm.
- **On CI failure**: the ci-rca agent (`.github/workflows/ci-rca.yml`) automatically files a recommendation with `source="ci_rca"` and `priority="critical"`. The next `/plan` session will surface it under "CI RCA Recs (open)". Do NOT manually patch the failure until the rec has been reviewed in a `/plan` session -- inline fixes without architectural review reproduce the workaround anti-pattern (Decision 55, Decision 72).

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

Lambda-based scheduled agents (doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality, rec-curator) were disabled in May 2026 during migration to Claude Code scheduled agents. To re-enable:

1. **Quick (AWS CLI only, no Terraform apply):**
   ```bash
   aws events enable-rule --name agent-platform-hourly-scheduled-agents --profile company-aws-profile
   aws lambda update-function-configuration \
     --function-name agent-platform-scheduled-agent-dispatcher \
     --environment 'Variables={SCHEDULED_AGENTS_ENABLED=true,GITHUB_PAT_SECRET_ARN=<arn>,S3_LOG_BUCKET=<bucket>,GEMINI_API_KEY_SECRET_ARN=<arn>}' \
     --profile company-aws-profile
   ```

2. **Permanent (via Terraform):**
   - In `terraform/scheduled_agents.tf`: remove `state = "DISABLED"` from `aws_cloudwatch_event_rule.hourly_agents`
   - In `terraform/scheduled_agents.tf`: change `SCHEDULED_AGENTS_ENABLED = "false"` to `"true"` in the dispatcher environment block
   - Run `terraform plan` (present output to human), then `terraform apply`
   - Rebuild and deploy Lambda: `bin/venv-python -m scripts.build_lambda --deploy`

3. **Verify:**
   - Check CloudWatch logs for `/aws/lambda/agent-platform-scheduled-agent-dispatcher` — should show agents dispatching within the next hour
   - Verify agent findings files appear in S3 under `s3://bblake-platform-agent-logs/agents/`
   - Run `bin/venv-python -m scripts.run_scheduled_agent --smoke-test doc-freshness` to confirm the `OpsWriter` id-validation guard (added in dq-ops-rec-corrections) is active in the deployed package and that agent writes reach S3.

### Self-hosted GitHub Actions runner

EC2 t3.medium runner in eu-west-2 (`agent-platform-runner`). See `terraform/ec2_runner.tf` and Decision 68.

1. **Check status:**
   ```bash
   sudo systemctl status "actions.runner.*"
   ```

2. **Start/stop:**
   ```bash
   sudo systemctl start "actions.runner.*"
   sudo systemctl stop "actions.runner.*"
   ```

3. **Re-registration (token expires in 60 minutes):**
   ```bash
   cd ~/actions-runner
   sudo ./svc.sh stop
   ./config.sh remove
   # Generate new token: GitHub repo -> Settings -> Actions -> Runners -> New self-hosted runner
   ./config.sh --url https://github.com/{owner}/{repo} --token <TOKEN>
   sudo ./svc.sh install && sudo ./svc.sh start
   ```

4. **Health check (from local machine):**
   ```bash
   gh api repos/{owner}/{repo}/actions/runners --jq '.runners[]'
   ```

5. **Shell access:** No SSH key pair is configured (the runner connects to GitHub via HTTPS only; no inbound port needed). For emergency access, use **EC2 Instance Connect** from the AWS console (EC2 -> Instances -> Connect -> EC2 Instance Connect). No key pair or open port required on Ubuntu 22.04 AMIs.
   ```bash
   # Get the instance ID for console navigation:
   aws ec2 describe-instances --filters "Name=tag:Name,Values=agent-platform-runner" --profile company-aws-profile --query "Reservations[].Instances[].InstanceId" --output text
   ```

6. **AWS credential delegation block** (written by user_data; must be present at `/home/ubuntu/.aws/config`):
   ```ini
   [profile company-aws-profile]
   credential_source = Ec2InstanceMetadata
   region = eu-west-2
   ```
   If absent (user_data failure), recreate manually on the instance and re-run verification step 3 from `docs/plans/PLAN-self-hosted-runner.md`.

7. **IAM permission boundary:** Do not extend the runner's IAM policy beyond `terraform/ec2_runner.tf`. If a new CI check needs AWS access, add the specific action to `aws_iam_policy.github_runner_ci` and run `terraform plan` (present to human) then `terraform apply`.

8. **Warm runner (future intent -- not built):** See Decision 68. Do not add persistent venv caching without the drift-enforcement plan (hash-gate, workspace reset, concurrency locking).

9. **OAuth token for Claude Code scheduled agents:**

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
