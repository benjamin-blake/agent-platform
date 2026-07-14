# Plan

## Intent
Establish S3 as the authoritative source of truth for cloud-produced logs and deliver an end-to-end priority queue pipeline -- from ad-hoc rec-curator invocation through S3 storage to preflight display. This directly advances the North Star by closing the feedback loop between recommendation generation and prioritised execution, enabling the self-improving system to autonomously decide what to work on next.

## Plan Type
STRATEGIC

## Branch
agent/infra-curator-pipeline

## Phase
Phase 1: Core Infrastructure (complete) -- this is infrastructure hardening for the automation layer

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/DECISIONS.md` | Modify | Add Decision 45: S3 source of truth for cloud-produced logs |
| `docs/contracts/log-storage.md` | Create | Define the log storage contract (write patterns, read patterns, status values) |
| `scripts/s3_log_store.py` | Modify | Add `overwrite_jsonl()` for replace-semantics (priority queue) |
| `tests/test_s3_log_store.py` | Modify | Tests for `overwrite_jsonl()` |
| `.github/prompts/scheduled/rec-curator.prompt.md` | Modify | Output queue entries as findings (`type: priority-queue-entry`) instead of local file write; fix status value to `queued` |
| `src/data/handlers/findings_processor_handler.py` | Modify | Extract `priority-queue-entry` findings from curator output, write to S3 key `priority-queue/.priority-queue.jsonl` via overwrite semantics |
| `tests/test_findings_processor_handler.py` | Create or Modify | Tests for priority-queue extraction logic |
| `scripts/session_preflight.py` | Modify | Fix status filter from `active` to `queued`; ensure S3 read path works for priority queue |
| `tests/test_session_preflight.py` | Modify | Update priority queue filter tests |
| `scripts/run_scheduled_agent.py` | Modify | Add `--trigger-lambda` flag for ad-hoc Lambda invocation |
| `tests/test_run_scheduled_agent.py` | Modify | Tests for `--trigger-lambda` |
| `.github/agents/rec-curator.agent.md` | Modify | Update description, tools, output contract to reflect pipeline (rec-449) |

## Bundled Recommendations
- **rec-449** (XS, open): Update rec-curator.agent.md description and tools for priority queue output -- directly addressed by Area D

## Related Recommendations (not bundled -- context for implementation agent)
The following open recs are closely related to the architectural direction of this plan. The implementation agent should review these when researching each Work Area and determine whether they should be updated, superseded, or have new recs filed:

- **rec-386** (M, open): Create `scripts/log_writer.py` -- standardised CLI for all JSONL log inserts with schema validation. This is the uniform write portal concept discussed during planning. Not bundled because its full scope (all log types) exceeds this plan. Area E should assess whether rec-386 is the right next step after the priority queue pipeline is working.
- **rec-387** (S, open, depends on rec-386): `validate.py` lint for raw JSONL writes that bypass `log_writer` or `s3_log_store.append_jsonl()`. Enforcement mechanism for rec-386. Not bundled -- depends on rec-386 completion.
- **rec-364** (M, open): Unified telemetry write gateway with schema validation, dedup, and environment routing. More ambitious than rec-386 (typed event classes, dedup strategies). Area E should determine whether rec-364 should be superseded by the simpler rec-386 approach or kept as a future evolution.
- **rec-450** (XS, open): Add dedicated EventBridge rule for rec-curator to `terraform/scheduled_agents.tf`. Not bundled -- terraform changes deferred until the pipeline is validated end-to-end via ad-hoc Lambda invocation.
- **rec-452** (S, open, depends on rec-448 + rec-451): Wire `develop-executor.prompt.md` Phase 4b to write queue amendments on RCA systemic findings. Not bundled -- depends on the priority queue pipeline being operational first.
- **rec-158** (M, open): Expand `sync_recommendations.py` to sync all rec-* IDs bidirectionally with S3. Related to the S3-as-source-of-truth direction but broader scope than this plan.
- **rec-442** (M, open, depends on rec-412): Extract Phase 2 rec-selection algorithm to `scripts/supervisor_recselector.py` -- downstream consumer of the priority queue. Not bundled.

## Acceptance Criteria
- [ ] Decision 45 logged in `docs/DECISIONS.md` with rationale for S3 source of truth pattern
- [ ] `docs/contracts/log-storage.md` exists with write pattern classification and status value canonical list
- [ ] `overwrite_jsonl()` function exists in `scripts/s3_log_store.py` with tests passing
- [ ] `rec-curator.prompt.md` outputs queue entries as `type: priority-queue-entry` findings (not local file write)
- [ ] `findings_processor_handler.py` extracts priority-queue entries and writes to S3 key
- [ ] `session_preflight.py` filters on `queued` status (not `active`) and reads from S3 backend
- [ ] `run_scheduled_agent.py --trigger-lambda rec-curator` invokes the Lambda and returns exit code 0
- [ ] End-to-end manual verification (requires AWS credentials): trigger Lambda ad-hoc, verify S3 queue file exists, run preflight, see top-5 entries
- [ ] `rec-curator.agent.md` updated to reflect new output contract (rec-449 closed)
- [ ] All `pytest` tests pass; `python scripts/validate.py` exits 0

## Constraints
- No Docker on company VM -- Lambda uses zip packaging via S3
- Company SCP blocks IAM user creation and OIDC federation -- use Lambda + Secrets Manager only
- S3 `append_jsonl()` uses read-modify-write (no concurrent write safety) -- acceptable because Lambda dispatcher runs agents sequentially
- DynamoDB / SNS / SQS are overkill for current scale -- simple S3 overwrite is sufficient. If concurrent multi-window writes emerge later, add S3 conditional `PutObject` with `If-None-Match` inside `log_writer.py`
- Terraform changes (rec-450 EventBridge rule) deferred to a follow-up plan after pipeline validation

## Context
- **Decision 37**: Lambda + Secrets Manager pattern for automation (SCP blocks OIDC)
- **Decision 44**: Executor self-modification boundary -- `scripts/executor/*.py` files are not touched by this plan
- **rec-448** (closed): Defined `.priority-queue.jsonl` schema and rewrote `rec-curator.prompt.md` -- establishes the schema this plan builds on
- **rec-451** (closed): Wired `session_preflight.py` to read queue and display top-5 -- establishes the read path this plan fixes
- **Known gotcha - S3 backend + local mocking pattern**: Use `get_backend()` switch so local mode preserves original file paths that tests mock
- **Known gotcha - Terraform file-optional operations**: Wrap `filemd5()` / `file()` calls with `try()` -- relevant if terraform files enter scope
- **Bug found during planning**: `session_preflight.py` line 256 filters `status == "active"` but `rec-curator.prompt.md` writes `status: "queued"` -- status mismatch means preflight always shows empty queue
- **Bug found during planning**: `rec-curator.prompt.md` step 5 instructs the agent to write `logs/.priority-queue.jsonl` directly -- impossible in Lambda execution context where the agent runs via `github_models_client.chat_completion()` (no filesystem access)
- **Bug found during planning**: S3 key path mismatch -- Area C writes to `priority-queue/.priority-queue.jsonl` but `session_preflight.py` reads via `read_jsonl(".priority-queue.jsonl")`. Canonical key is `priority-queue/.priority-queue.jsonl`; the preflight read path must be updated to match

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Related recommendations (rec-386, rec-387, rec-364, rec-450, rec-452, rec-158, rec-442) reviewed for context

## Work Areas (STRATEGIC plans only)
> Replace the Ordered Execution Steps section above with this table when Plan Type is STRATEGIC.

| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| A: Architectural Decision + Storage Contract | `docs/DECISIONS.md`, `docs/contracts/log-storage.md` | Establishes Decision 45: S3 is source of truth for cloud-produced logs. Defines the three write patterns (cloud-produced: S3 write/local pull; locally-produced: local write/S3 push; shared-mutable: via `log_writer.py`), canonical status values (`queued`, `open`, `closed`, `failed`, `declined`, `superseded`), and the contract that all future log consumers/producers must follow. Must be done first as all other areas reference this decision. | XS |
| B: S3 Overwrite Capability | `scripts/s3_log_store.py`, `tests/test_s3_log_store.py` | `append_jsonl()` exists for append semantics but the priority queue needs full-file replace semantics each run. Add `overwrite_jsonl(key, entries)` that writes a complete JSONL file to S3 (or local fallback). Same `get_backend()` pattern as existing functions. This is a building block for Area C and any future replace-semantics log. | S |
| C: Priority Queue Pipeline (end-to-end) | `rec-curator.prompt.md`, `findings_processor_handler.py`, `session_preflight.py`, `run_scheduled_agent.py`, + associated tests | The core deliverable. Four changes: (1) **Remove or rewrite** `rec-curator.prompt.md` Step 5 (local file write) entirely -- queue entries must be emitted as `type: priority-queue-entry` findings in the Step 6 JSON array output. Do not preserve the local write path alongside the new findings-based output. (2) Modify findings processor to detect `priority-queue-entry` type, extract those entries, and call `overwrite_jsonl("priority-queue/.priority-queue.jsonl", entries)` to S3. Note: the handler currently has **no type-based routing** -- this is the first dispatch branch being added. Consider extracting a clean `_route_by_type()` helper. (3) Fix session_preflight: change status filter from `active` to `queued`, and update the S3 read key from `.priority-queue.jsonl` to `priority-queue/.priority-queue.jsonl` (see S3 key mismatch bug in Context). (4) Add `--trigger-lambda` to `run_scheduled_agent.py` as a thin CLI wrapper around `aws lambda invoke --payload '{"force_agent":"NAME"}'`. The `force_agent` field is already supported by `scheduled_agent_handler.py`. | M |
| D: rec-curator.agent.md Alignment (rec-449) | `.github/agents/rec-curator.agent.md` | Update the agent description, tools list, and output contract to reflect the new pipeline: agent outputs JSON array to stdout (findings + priority-queue-entries), does NOT write files, queue reaches S3 via findings processor. Remove stale references to direct `logs/.priority-queue.jsonl` writes. Closes rec-449. | XS |
| E: Migration Assessment (REPORT-ONLY) | Audit output only (no code changes) | Audit all JSONL write sites across the codebase. Classify each into the three patterns from Area A's contract. Determine: (1) which existing write sites already conform, (2) which need migration, (3) whether rec-386 (`log_writer.py`) is the right next step or whether rec-364 (`telemetry_gateway.py`) should supersede it, (4) recommended implementation order for incremental migration. Output as new recs or updates to existing recs (rec-386, rec-387, rec-364). Do NOT implement any migration in this plan -- scope is assessment only. | S |
