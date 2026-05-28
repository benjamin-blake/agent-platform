# Plan

## Intent
Build the rec-curator scheduled-agent infrastructure on the Claude Code substrate: an
agent prompt, a path-enforcing PreToolUse hook, a validate.py check, a post-completion
telemetry write adapter, and a manual end-to-end dry-run that proves the full pipeline
works before Phase 4 wires the cron. Advances the North Star by enabling a daily
automated curation loop through the self-improving recommendation pipeline without
relying on the disabled Lambda dispatcher.

## Plan Type
IMPLEMENTATION

*Note: Scope spans 11 files, exceeding the 5-file STRATEGIC threshold. Decision 67
prohibits STRATEGIC plans; this plan is classified IMPLEMENTATION under that constraint.
All execution steps are concretely defined with no strategic scoping gates.*

## Verification Tier
V3 -- end-to-end dry-run requires a live `claude` CLI invocation, real Athena read
access for the rec-curator's input, and real OpsWriter outbox writes for telemetry.

## Branch
agent/cc-scheduled-agents-phase-3

## Phase
Platform (parallel with Phase 2 schema backfill)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/DECISIONS.md` | Modify | Decision 71: reverse parent plan D15; cron mechanism is GitHub Actions + self-hosted runner, not Anthropic-hosted `schedule` skill |
| `.claude/agents/scheduled/rec-curator.md` | Create | Agent prompt; port from `.github/prompts/scheduled/rec-curator.prompt.md`; replace S3-direct-write and Lambda-handler language with per-run file write to `logs/agents/rec-curator/{ts}.jsonl` |
| `.claude/hooks/scheduled_agent_log_only.py` | Create | PreToolUse hook: when `CC_SCHEDULED_AGENT_NAME` is set, deny Edit/Write/MultiEdit/NotebookEdit to paths outside `logs/agents/{name}/` and `logs/.ops-outbox/`; modelled on `never_on_main.py` |
| `.claude/settings.json` | Modify | Append `scheduled_agent_log_only.py` to `hooks.PreToolUse[0].hooks` array |
| `scripts/validate.py` | Modify | Add `validate_scheduled_agent_logs()`: detects scheduled-agent branches (only `logs/agents/**` and `logs/.ops-outbox/**` changed), verifies ISO-timestamp filename, JSONL schema, no canonical-state file modifications |
| `scripts/agent_telemetry_writer.py` | Create | Post-completion telemetry CLI: reads `--output-format json` stdout file, emits one `telemetry_agent_invocations` row + one `telemetry_model_calls` row to local outbox; supports `trigger=cron_workflow`, `provider=anthropic_max`, `workflow_run_id` |
| `terraform/iceberg_tables.tf` | Modify | `telemetry_agent_invocations`: add `workflow_run_id string` column; extend `trigger` and `provider` column comments to document new enum values |
| `tests/test_scheduled_agent_log_only_hook.py` | Create | Unit tests for the new PreToolUse hook |
| `tests/test_validate.py` | Modify | Add `TestValidateScheduledAgentLogs` class |
| `tests/test_agent_telemetry_writer.py` | Create | Unit tests for the telemetry writer CLI |
| `scripts/telemetry_schemas.py` | Modify | Add `workflow_run_id: str \| None = None` to `TelemetryAgentInvocations` dataclass so `OpsWriter` recognises the new column; update any dtype/timestamp maps if needed |
| `CLAUDE.md` | Modify | Add OAuth token setup and rotation runbook to the self-hosted runner section |

## Bundled Recommendations
None -- no open recommendations align with this Phase 3 scope without scope drift.

## Infrastructure Dependencies

| Resource | Change | Timing |
|----------|--------|--------|
| `trading_formulas_db.telemetry_agent_invocations` (Iceberg via Glue) | Add `workflow_run_id string` column (nullable, additive); update `trigger` and `provider` column comments | `terraform plan` presented to human for approval; `terraform apply` required before Phase 4 dry-run. No data migration -- additive column, existing Lambda rows have `workflow_run_id=null`. |

## Acceptance Criteria
- [ ] `.claude/agents/scheduled/rec-curator.md` exists; zero occurrences of `s3://`,
  `put_object`, `findings_processor`, or `overwrite_jsonl`; contains
  `logs/agents/rec-curator/` as the output path
- [ ] `.claude/hooks/scheduled_agent_log_only.py` exists; blocks Write to `src/` when
  `CC_SCHEDULED_AGENT_NAME=rec-curator` is set; allows Write to `logs/agents/rec-curator/`
- [ ] Hook is present in `.claude/settings.json` `hooks.PreToolUse[0].hooks` array
- [ ] `validate_scheduled_agent_logs()` exists in `scripts/validate.py` and is wired into
  the presubmit tier
- [ ] `scripts/agent_telemetry_writer.py` exists and emits to outbox without error given
  valid JSON input
- [ ] `terraform/iceberg_tables.tf` `telemetry_agent_invocations` block contains
  `workflow_run_id` column
- [ ] Decision 71 committed to `docs/DECISIONS.md`
- [ ] `scripts/telemetry_schemas.py` `TelemetryAgentInvocations` dataclass contains
  `workflow_run_id` field
- [ ] All new and modified tests pass; `.venv/Scripts/python.exe -m scripts.validate`
  exits 0
- [ ] `CLAUDE.md` contains OAuth token setup and rotation steps
- [ ] End-to-end dry-run produces a valid `logs/agents/rec-curator/{ts}.jsonl` containing
  at least one `priority-queue-entry` row
- [ ] `enqueue_findings` ingests dry-run output: `enqueued > 0, invalid == 0`
- [ ] Outbox contains a `telemetry_agent_invocations` row from the dry-run

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | [pre-deploy] | Hook unit tests | `.venv/Scripts/python.exe -m pytest tests/test_scheduled_agent_log_only_hook.py -v` | All pass | Fix hook implementation |
| 2 | [pre-deploy] | Validate check tests | `.venv/Scripts/python.exe -m pytest tests/test_validate.py::TestValidateScheduledAgentLogs -v` | All pass | Fix validate implementation |
| 3 | [pre-deploy] | Telemetry writer tests | `.venv/Scripts/python.exe -m pytest tests/test_agent_telemetry_writer.py -v` | All pass | Fix writer implementation |
| 4 | [pre-deploy] | Hook registered in settings | `.venv/Scripts/python.exe -c "import json; s=json.load(open('.claude/settings.json')); h=s['hooks']['PreToolUse'][0]['hooks']; assert any('scheduled_agent_log_only' in x['command'] for x in h), 'missing'; print('OK')"` | Prints `OK` | Add hook entry to settings.json |
| 5 | [pre-deploy] | Hook blocks out-of-scope write | `echo '{"tool_name":"Write","tool_input":{"file_path":"src/data/pipeline.py","content":"x"}}' \| CC_SCHEDULED_AGENT_NAME=rec-curator .venv/Scripts/python.exe .claude/hooks/scheduled_agent_log_only.py; echo "exit=$?"` | `exit=2` | Fix permitted-path logic in hook |
| 6 | [pre-deploy] | Hook allows in-scope write | `echo '{"tool_name":"Write","tool_input":{"file_path":"logs/agents/rec-curator/20260509T184700Z.jsonl","content":"[]"}}' \| CC_SCHEDULED_AGENT_NAME=rec-curator .venv/Scripts/python.exe .claude/hooks/scheduled_agent_log_only.py; echo "exit=$?"` | `exit=0` | Fix permitted-path logic in hook |
| 7 | [pre-deploy] | Prompt has no legacy S3/Lambda language | `grep -icE "s3://\|put_object\|findings_processor\|overwrite_jsonl" .claude/agents/scheduled/rec-curator.md` | Output `0` | Remove legacy language from prompt |
| 8 | [pre-deploy] | Terraform plan is additive only | `cd terraform && terraform plan 2>&1 \| grep "^Plan:"` | `Plan: 0 to add, 1 to change, 0 to destroy` | Review `iceberg_tables.tf` edit; do not apply until human approves |
| 9 | [post-deploy] | Human setup: OAuth token | `claude setup-token` (interactive -- see Ordered Execution Steps step 10 for full walkthrough) | Token stored as GH Actions secret `CLAUDE_CODE_OAUTH_TOKEN` | Re-run `claude setup-token`; check Max plan is active | # pragma: allowlist secret
| 10 | [post-deploy] | End-to-end dry-run | `CC_SCHEDULED_AGENT_NAME=rec-curator CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" claude -p "$(cat .claude/agents/scheduled/rec-curator.md)" --output-format json --allowedTools "Read,Write,Edit,Glob,Grep,Bash(git *),Bash(.venv/Scripts/python.exe *)" --permission-mode dontAsk --max-turns 10 > /tmp/agent-output.json; echo "exit=$?"` | `exit=0`; `/tmp/agent-output.json` is valid JSON with `.result` and `.usage.input_tokens` | Inspect `/tmp/agent-output.json` and stderr; check hook error messages |
| 11 | [post-deploy] | Findings file produced and valid | `ls -1t logs/agents/rec-curator/*.jsonl \| head -1 \| xargs -I{} .venv/Scripts/python.exe -c "import sys,json; rows=[json.loads(l) for l in open('{}')]; assert any(r.get('type')=='priority-queue-entry' for r in rows),'no queue entries'; print('OK rows:',len(rows))"` | `OK rows: N` where N >= 1 | Check agent output for schema errors; revise prompt |
| 12 | [post-deploy] | enqueue_findings accepts output | `.venv/Scripts/python.exe -m scripts.ops_data_portal --enqueue-findings $(ls -1t logs/agents/rec-curator/*.jsonl \| head -1) --profile company-aws-profile` | Reports `enqueued > 0, invalid == 0` | Fix finding schema against `rec-curator.md` output spec |
| 13 | [post-deploy] | Telemetry writer emits invocation row | `.venv/Scripts/python.exe scripts/agent_telemetry_writer.py --agent rec-curator --trigger cron_workflow --provider anthropic_max --json-output /tmp/agent-output.json --findings-file $(ls -1t logs/agents/rec-curator/*.jsonl \| head -1) --workflow-run-id 0 && ls logs/.ops-outbox/telemetry_agent_invocations/ \| head -1 \| xargs -I{} .venv/Scripts/python.exe -c "import json; d=json.load(open('logs/.ops-outbox/telemetry_agent_invocations/{}'))[0]; assert d.get('agent_name')=='rec-curator'; print('OK')"` | Prints `OK` | Fix writer emit path or OpsWriter call |
| 14 | [post-deploy] | Full validate passes on branch | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Fix any lint / test / check failures |

## Constraints
- Context document: `docs/plans/PLAN-cc-scheduled-agents.md`. This plan is Phase 3 of 5.
- Decision 67: IMPLEMENTATION plans only. File count exceeds 5-file threshold but
  Decision 67 prohibits STRATEGIC; execution steps are fully concrete.
- Decision 71 (filed this plan): cron mechanism is GitHub Actions + self-hosted runner.
  Reverses parent plan D15.
- Phase 4 dependency: `.github/workflows/scheduled-agents.yml` is NOT in scope here.
  Phase 3 builds the infrastructure Phase 4 drives.
- D9 (parent plan): findings-processor Lambda remains active through Phase 4 (strangler-fig).
  Phase 3 does not disable it.
- D13 (parent plan): all new surfaces under `.claude/`, not `.github/` legacy paths.
- Single Portal Invariant: the agent prompt must not write canonical state directly.
  All canonical writes go through `ops_data_portal`.
- `never_on_main.py` must continue firing. Both hooks live in `PreToolUse[0].hooks` array;
  both must pass for a tool call to proceed.
- Auth: `CLAUDE_CODE_OAUTH_TOKEN` (Max subscription). Do NOT use `ANTHROPIC_API_KEY`
  for the scheduled agent invocation. No `--max-budget-usd` flag (subscription billing).
- `--max-turns 10` is the safety ceiling for the scheduled agent invocation.
- No rescue agents or workaround loops (Decision 55).
- Validate.py is the single source of truth for CI checks (Decision 60).

## Context
- Phase 1 (PR #292): `enqueue_findings()` portal interface; `.gitignore` outbox carve-out;
  Decision 61 (findings flow through `ops_recommendations` via `source` field).
- Phase 2 (PR #293): preflight reads `ops_priority_queue_current` Athena view; SSO
  auto-login.
- Self-hosted runner (PR #310, Decision 68): EC2 t3.medium, eu-west-2,
  `[self-hosted, linux]` label. Free CI minutes; unblocks Phase 4 cron wiring.
- Decision 71 (filed this plan) reverses parent plan D15. Original rationale for D15
  (avoid OIDC, avoid GH Actions billing) is fully resolved by Decision 68.
- Telemetry target: `telemetry_agent_invocations` (standalone fact table; no FK to
  `telemetry_sessions`). Write via new `scripts/agent_telemetry_writer.py` wrapping the
  existing `src/data/handlers/agent_telemetry.py` API. `telemetry_model_calls` receives
  one aggregate row per invocation linked via `invocation_id`.
  `telemetry_model_calls.copilot_session_id` holds Claude Code's `session_id` from
  `--output-format json` output.
- Schema extension (additive only): `workflow_run_id string` on
  `telemetry_agent_invocations`; `trigger` enum adds `cron_workflow`; `provider` enum
  adds `anthropic_max`.
- `telemetry_agent_invocations.tokens_input/tokens_output` hold aggregate token counts
  from `--output-format json` `.usage` field. Cost is calculated separately in analytics
  (`tokens * price_per_million`) not at write time -- correct for Max subscription today,
  and ready for API-based billing in future.
- Legacy prompt at `.github/prompts/scheduled/rec-curator.prompt.md` is the source to
  port from. It is deep-frozen -- do not edit it.
- Hook pattern to follow: `.claude/hooks/never_on_main.py`.
- Canonical invocation (dry-run and Phase 4 target):
  ```bash
  CC_SCHEDULED_AGENT_NAME=rec-curator \
  CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN}" \
  claude -p "$(cat .claude/agents/scheduled/rec-curator.md)" \
    --output-format json \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash(git *),Bash(.venv/Scripts/python.exe *)" \
    --permission-mode dontAsk \
    --max-turns 10
  ```
- Open questions closed by this plan: Q3 (hook trigger = `CC_SCHEDULED_AGENT_NAME`);
  Q9 (GitHub credentials in GH Actions = `GITHUB_TOKEN` auto-injected by platform).
- Open questions remaining for Phases 4-5: Q6, Q7, Q8, Q10.
- Side observation (not blocking): `docs/DECISIONS.md` contains two entries numbered 69
  (ops-pipeline-consolidation and branch-protection). Out of scope; flag separately as
  a recommendation.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read in full
- [ ] `docs/DECISIONS.md` read (Decisions 55, 61, 67, 68, 69 noted)
- [ ] `docs/plans/PLAN-cc-scheduled-agents.md` Context and Decisions Register read
- [ ] `.github/prompts/scheduled/rec-curator.prompt.md` read (source to port from)
- [ ] `.claude/hooks/never_on_main.py` read (pattern to follow for new hook)
- [ ] `.claude/settings.json` read (existing hook registration pattern)
- [ ] `src/data/handlers/agent_telemetry.py` read (write API to adapt)
- [ ] `terraform/iceberg_tables.tf` `telemetry_agent_invocations` block read
- [ ] VP step 8 (terraform plan) run before writing any Terraform
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **File Decision 71 in `docs/DECISIONS.md`**
   Insert as the new leading open decision (above Decision 69). Content:
   - Problem: parent plan D15 specified Anthropic-hosted `schedule` skill as cron
     mechanism to avoid OIDC and GH Actions billing. Decision 68 (self-hosted runner)
     resolved both concerns: minutes are free, and `GITHUB_TOKEN` auto-injection solves
     the credential problem that was the core unresolved risk (parent plan Q9).
   - Decision: cron mechanism for cc-scheduled-agents Phase 4 is GitHub Actions scheduled
     workflow (`on: schedule: - cron: '0 8 * * *'`) running on `[self-hosted, linux]`.
     Claude Code CLI is invoked headlessly via `claude -p`. Auth: `CLAUDE_CODE_OAUTH_TOKEN`
     (Max subscription, zero marginal API cost). The `schedule` skill (CronCreate) is not
     used for this project.
   - Consequences: Phase 3 designs the agent for headless invocability; Phase 4 writes
     the workflow YAML. No Anthropic-hosted cron billing.
   - Status: Decided 2026-05-09.

2. **Write `.claude/agents/scheduled/rec-curator.md`**
   Port the full analytical logic from `.github/prompts/scheduled/rec-curator.prompt.md`
   (sections 1-5: Load Inputs, Cluster Open Recs, Detect Workaround Patterns, Rank,
   Output). Apply these adaptations:
   - Replace the entire "Output JSON Array" stdout instruction with: produce a JSON array
     of findings and write it to `logs/agents/rec-curator/{ts}.jsonl` where `{ts}` is
     obtained at run start via `Bash("date -u +%Y%m%dT%H%M%SZ")`. Use
     `Bash("echo '[...]' > logs/agents/rec-curator/{ts}.jsonl")` to write the file.
   - Remove all references to `findings_processor_handler.py`, `overwrite_jsonl`, `S3`,
     and "Lambda handler stores output automatically".
   - Replace "Do NOT write any files" constraint with:
     "Write findings to `logs/agents/rec-curator/{ts}.jsonl` only. Do not write to any
     other path. Do not open PRs or commit in this agent invocation -- the workflow
     orchestrator handles that."
   - Retain all schema definitions, priority queue logic, and finding type specs verbatim.
   - Add a Constraints section at the end noting: `CC_SCHEDULED_AGENT_NAME=rec-curator`
     is set in the execution environment; the hook enforces the path restriction.

3. **Write `.claude/hooks/scheduled_agent_log_only.py`**
   Follow `never_on_main.py` pattern exactly:
   - Read JSON from stdin; on malformed input exit 0 (defensive fail-open).
   - Early exit: if `CC_SCHEDULED_AGENT_NAME` env var is not set, exit 0 immediately
     (hook is fully inert in interactive sessions).
   - Test escape hatch: if `CC_HOOK_AGENT_OVERRIDE` env var is set, exit 0 (mirrors
     `CLAUDE_HOOK_BRANCH_OVERRIDE` pattern from `never_on_main.py`).
   - `_MUTATING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}`.
   - Permitted path prefixes (normalise with `os.path.normpath` before comparing):
     - `logs/agents/{agent_name}/` where `agent_name = os.environ["CC_SCHEDULED_AGENT_NAME"]`
     - `logs/.ops-outbox/`
   - For mutating tools: extract `file_path` from `tool_input`. If not under a permitted
     prefix, exit 2 with stderr message naming the blocked path and listing permitted paths.
   - `Bash` tool: exit 0 always (path restriction on Bash would block git/python calls;
     Bash enforcement is the `--allowedTools` whitelist at the invocation level).
   - Non-mutating tools (Read, Glob, Grep, etc.): exit 0 always.

4. **Modify `.claude/settings.json`**
   Append to `hooks.PreToolUse[0].hooks` array:
   ```json
   {
     "type": "command",
     "command": ".venv/Scripts/python.exe .claude/hooks/scheduled_agent_log_only.py"
   }
   ```
   Do not modify the `permissions` allow/deny list.

5. **Modify `scripts/validate.py` -- add `validate_scheduled_agent_logs()`**
   - Detection: run `git diff --name-only main...HEAD`. If ALL changed files are under
     `logs/agents/` or `logs/.ops-outbox/`, this is a scheduled-agent branch; run the
     check. Otherwise return (not applicable to feature branches).
   - For each `logs/agents/{name}/*.jsonl` file in the diff:
     - Filename: must match `\d{8}T\d{6}Z\.jsonl`.
     - Each line: must parse as JSON; must contain `type` and `timestamp` fields.
   - Fail if `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` appear
     in the diff (canonical-state write violation).
   - Register in the presubmit tier (not `--pre`).

6. **Modify `scripts/telemetry_schemas.py`**
   In `TelemetryAgentInvocations` dataclass, add field after `lambda_request_id`:
   `workflow_run_id: str | None = None`
   Check `TELEMETRY_TABLE_DTYPES` and `TELEMETRY_TABLE_TIMESTAMP_COLS` maps -- if either
   references `telemetry_agent_invocations` columns explicitly, add `workflow_run_id`
   (type `"string"`, not a timestamp). If those maps are schema-agnostic or not present,
   no further change is needed.
   Note: `telemetry_schemas.py` is Lambda-packaged (line 48 of `_LAMBDA_SCRIPTS` in
   `scripts/build_lambda.py`). See step 8 for the required DEFERRED note.

7. **Write `scripts/agent_telemetry_writer.py`**
   CLI args: `--agent`, `--trigger`, `--provider`, `--json-output <path>` (path to
   `--output-format json` output file), `--findings-file <path>`, `--workflow-run-id`.
   Write path: use `OpsWriter.emit()` directly with `TelemetryAgentInvocations` and
   `TelemetryModelCalls` dataclasses from `telemetry_schemas.py`. Do NOT wrap the
   high-level `src/data/handlers/agent_telemetry.py` API (which assumes Lambda runtime
   context and splits open/close writes). This is a post-completion single-write pattern.
   Logic:
   - Parse JSON output file: extract `usage.input_tokens`, `usage.output_tokens`,
     `session_id`, `model` (default `"claude-opus-4-7"` if absent).
   - Parse findings file: `findings_count = len(rows)`;
     `queue_entries_written = count(r for r in rows if r["type"] == "priority-queue-entry")`.
   - Build `TelemetryAgentInvocations`: `agent_name`, `trigger`, `provider`,
     `tokens_input`, `tokens_output`, `findings_count`, `queue_entries_written`,
     `outcome="success"`, `workflow_run_id`, `model_used`, `started_at`/`ended_at`
     (use current time; wall-clock precision is sufficient), `trade_date=today`.
   - Build `TelemetryModelCalls`: `invocation_id` FK, `provider`, `model`, `purpose="findings"`,
     `tokens_input`, `tokens_output`, `copilot_session_id=session_id`.
   - `OpsWriter.emit(TelemetryAgentInvocations.TABLE_NAME, row.to_dict())` for each.
   - Do not call `compact_all()` -- drain happens at next human session via postflight.

8. **Modify `terraform/iceberg_tables.tf`**
   In the `telemetry_agent_invocations` resource:
   - Add column after `lambda_request_id`:
     `{ name = "workflow_run_id", type = "string", comment = "GitHub Actions GITHUB_RUN_ID; set for cron_workflow trigger, null for eventbridge/manual" }`
   - Update `lambda_request_id` comment to:
     `"AWS Lambda request ID; set for eventbridge trigger, null for cron_workflow"`
   - Update `trigger` column comment to include `cron_workflow` in the enum list.
   - Update `provider` column comment to include `anthropic_max` in the enum list.
   - **Run VP step 8 immediately after writing**: `cd terraform && terraform plan`.
     Present output to human. Do NOT apply until human approves.

9. **DEFERRED: Lambda package rebuild (pending Decision 67 reversal)**
   `scripts/telemetry_schemas.py` is Lambda-packaged (line 48, `_LAMBDA_SCRIPTS` in
   `scripts/build_lambda.py`). Once Decision 67 is reversed, execute:
   ```bash
   .venv/Scripts/python.exe -m scripts.build_lambda --deploy
   .venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness
   ```
   This step is intentionally deferred and must NOT be executed during Phase 3. The Lambda
   dispatcher remains disabled (Decision 67); the schema change is additive and backward-
   compatible with the currently deployed Lambda package (new nullable column, existing
   rows unaffected).

10. **Write test files**
   `tests/test_scheduled_agent_log_only_hook.py`:
   - No `CC_SCHEDULED_AGENT_NAME` env var -> exit 0 for any tool
   - Env var set + Write to `logs/agents/rec-curator/20260509T000000Z.jsonl` -> exit 0
   - Env var set + Write to `src/data/pipeline.py` -> exit 2
   - Env var set + Read tool (non-mutating) -> exit 0
   - `CC_HOOK_AGENT_OVERRIDE` set -> exit 0 regardless
   - Malformed JSON stdin -> exit 0 (defensive)
   - Missing `file_path` in tool_input -> exit 0 (defensive)

   `tests/test_validate.py::TestValidateScheduledAgentLogs`:
   - All changed files under `logs/agents/` + valid JSONL -> passes
   - `logs/.recommendations-log.jsonl` in diff -> fails with clear message
   - Malformed JSONL (non-JSON line) -> fails
   - Filename not matching ISO pattern -> fails
   - Mixed diff (source file + log file) -> check skipped (not a scheduled-agent branch)

   `tests/test_agent_telemetry_writer.py`:
   - Valid JSON output file + findings file -> correct `telemetry_agent_invocations` shape
     emitted to OpsWriter
   - `queue_entries_written` counts only `priority-queue-entry` type rows
   - Missing `.usage` in JSON -> graceful: tokens default to 0, no exception raised
   - Empty findings file -> `findings_count=0`, `queue_entries_written=0`

11. **Modify `CLAUDE.md` -- OAuth token runbook**
   Add subsection "OAuth token for Claude Code scheduled agents" inside the
   "Self-hosted GitHub Actions runner" runbook section:

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

12. **Human one-time setup (required before VP step 10)**
    Complete the OAuth token setup described in CLAUDE.md step 9 above. Once
    `CLAUDE_CODE_OAUTH_TOKEN` is set as a GH Actions secret and available in your local
    shell (`export CLAUDE_CODE_OAUTH_TOKEN=<token>`), the dry-run can proceed.

13. **Execute Verification Plan** -- run steps 1-14 in order.
    Steps 1-8 are pre-deploy (no live AWS or OAuth needed).
    Steps 9-14 are post-deploy (require live AWS SSO, `CLAUDE_CODE_OAUTH_TOKEN` in shell,
    and Athena access).
    If VP step 10 exits non-zero, inspect `/tmp/agent-output.json` and stderr for hook
    blocks or auth errors before retrying. If VP step 11 finds no `priority-queue-entry`
    rows, the agent ran but produced no queue output -- revise the prompt's ranking logic
    and re-run. Do not proceed to VP step 12 until step 11 passes.

14. Report: what was implemented, VP results, Decision 71 filed, terraform plan output.
    Note any new friction observed during dry-run (do not file recs inline -- they will
    be auto-curated by the first live cron run after Phase 4). File a recommendation via
    `ops_data_portal` to fix the duplicate Decision 69 collision in `docs/DECISIONS.md`
    (one of the two 69 entries must be renumbered; the ops-pipeline-consolidation entry
    is the newer one and should be renumbered to the next available number after 70).
