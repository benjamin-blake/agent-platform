# INTENT: Session-Log Architecture

Substantive deliverable for platform tier_item T-1.9 (Session-log architecture
audit + redesign). Captures the deliberation that converged on a two-tier
event/aggregate split with a new agent-facing Lambda for turn-event ingestion.

| Field | Value |
|---|---|
| Tier item | T-1.9 (docs/ROADMAP-PLATFORM.yaml) |
| Plan artefact | docs/plans/PLAN-session-log-audit.md |
| Plan type | REPORT-ONLY |
| Status | Drafted; awaits CD ratification of the named CDs below |
| Filed via | pending_log_decision_lambda (T0.7b not yet deployed) |
| Related CDs / Decisions | NS.4, NS.5, CD.9, CD.10, CD.12, CD.13, CD.15, CD.20, CD.23, CD.25, CD.26; Decisions 50, 51, 55, 56, 61, 62, 63, 65, 67, 69, 74, 75 |

## 1. End-state architecture restatement

Anchors every downstream decision. Restated explicitly so the audit's
recommendations are traceable to the substrate.

- Agents call typed Lambda verbs over HTTPS Function URLs with AWS_IAM auth
  (CD.10, CD.26, NS.5). Agents never see SQL, Athena, DuckDB, or boto3
  directly. The `scripts/agent_sdk/` shim hides Function URL discovery,
  SigV4 signing, retry policy (T1.10), and idempotency-key generation.
- Iceberg over S3 is the durable substrate at every scale (NS.1). Reads
  inside Lambdas use DuckDB-on-Iceberg-snapshot (CD.15); Athena is reserved
  for escape-hatch ad-hoc large scans, not the agent path.
- ops_* tables are append-only with SCD2 dedup on
  `last_updated_timestamp` (Decision 56). Partitioning is uniform per
  CD.9: `day(last_updated_timestamp)` on every ops table.
- `scripts/ops_data_portal.py` and the outbox/sync_ops pipeline survive
  as internal Lambda implementation; they disappear from the agent contract
  (CD.10, Decision 51 subsumption).
- The 6-Lambda enumeration in the platform roadmap (log-rec, log-decision,
  query, update-rec, list-tools, maintenance) is non-exhaustive. New
  Lambdas are justified when they own distinct stateful contracts (e.g.
  agent-platform-log-turn introduced in this INTENT).

## 2. Frame challenge (Decision 75)

Before recommending a verb shape for session/turn writes, this audit
explicitly poses Decision 75's five frame-challenge questions against
the assumption that session-related writes belong on the Lambda surface
at all.

| Question | Answer |
|---|---|
| What if the orchestrator/contract was a different kind of thing? | Three alternatives considered, not one: (a) internal-only telemetry writer pattern (no agent-facing verb) -- Section 8.1; (b) direct outbox staging from hook reusing the existing `logs/.ops-outbox/` + `sync_ops` drain path (no new Lambda, leverages Decision 51 substrate) -- Section 8.4; (c) bundle into existing log-rec/log-decision verbs -- Section 8.3. Selected option is the new Lambda (8.2) with explicit reasoning per option. |
| What's the smallest version that delivers value? | The turn-events table alone, fed by a Stop hook, is the smallest valuable cut. The aggregate session table can be derived from it later (Section 9). |
| What invariants does the proposal assume that aren't actually invariants? | Assumed: every turn has a session_id and the hook can always reach the Lambda. **Stress-tested**: (i) SessionStart hook allocates session_id and exports via env var; loss modes enumerated in Section 11.3 with deterministic fallback ID derivation. (ii) Lambda unavailability handled via Section 11.2.1 outbox-failure playbook, not hand-waved. (iii) Iceberg snapshot retention means post-hoc PII redaction is not actually effective -- Section 7.3 addresses via hook-side pre-write scrubbing as launch criterion, not post-hoc polish. |
| What's the precedent in this repo for the proposed shape? | Decision 61 (scheduled-agent findings via ops_recommendations.source field) is precedent for "extend the existing surface vs new surface" reasoning. Decision 62 (no separate DQ scheduled routine) is precedent for "fold into existing primitives." Decision 51 (outbox + drain) is precedent for the rejected Section 8.4 path. All three inform Section 8's option survey. |
| What would a critic call this in six months? | Risk 1: "they made another table when they should have aggregated into telemetry_process_events." Mitigation: turn-events have a fundamentally different cardinality and query pattern (one row per agent turn vs many rows per process event); folding them in would have lost the granularity that makes cost analysis tractable. Risk 2: "they added a 7th Lambda after invoking Decision 69 Single Portal Invariant on the rejection side." Mitigation: Decision 69's invariant is *single portal per write surface*, not *single Lambda for all writes*; the turn-write surface is a distinct stateful contract from rec/decision writes. Risk 3: "the hook-side outbox is a new failure surface, not solved drift." Mitigation: Section 11.2.1 operator playbook + Decision 74 disk-pressure consideration explicit. |

Frame-challenge verdict: the new turn-events table and its dedicated
write Lambda are derived from genuine architectural need, not
path-of-least-resistance defaulting.

## 3. Current write-surface inventory

Two visible surfaces today, plus the deprecated markdown:

### 3.1 `docs/SESSION_LOG.md` (markdown ledger)

- Append-only narrative ledger keyed by date. Deprecated per NS.4 (the
  repo is for agents; narrative prose is a side effect, not an output)
  and CD.13 (markdown-with-prose retired in favour of agent-first
  artefacts).
- No structured schema. Written by humans and agents in ad-hoc free-form.
- Read by: `.claude/skills/planning/SKILL.md` Read Context step (referenced
  via `docs/PROJECT_CONTEXT.md`; the planning skill itself contains no
  `SESSION_LOG` literal -- verified by grep), `session_preflight.py`
  recent_sessions field, retrospective agents.
- Retirement: post-T1.5 sweep, after readers cut over to the Lambda
  query verb.

### 3.2 `ops_session_log` Iceberg table

- Currently 20646 rows (per preflight 2026-05-27). Cardinality is
  event-flavoured rather than session-flavoured; one row per session
  would be O(hundreds) not O(tens of thousands). Naming is misleading:
  `ops_` prefix suggests state but the table behaves like a log.
- Schema authority: `config/agent/data_quality/ops.yaml` per Decision
  65; DDL in `terraform/iceberg_tables.tf`. Schema-accuracy assessment
  (Section 7) compares these against actual written rows.
- Write path today: `scripts/ops_writer.py` -> outbox -> `scripts/sync_ops.py`
  drain (Decision 51 local-first pattern). The portal entry point is
  `scripts/ops_data_portal.py`.
- Retirement proposed (Section 12, CD.NN.a): functionally duplicated by
  `telemetry_process_events` and the new turn-events table; retired
  after backfill of distinct historical rows (Section 11.5).

### 3.3 `telemetry_sessions` (Iceberg)

- Currently 398 rows. One row per session = session header today, though
  the writer semantics are unverified and require schema-accuracy audit
  (Section 7).
- Promoted in this INTENT to first-class status as the future aggregate
  session table, with naming clarified (Section 9).

### 3.4 Sibling telemetry tables (referenced for join story)

- `telemetry_phases` (8 rows), `telemetry_steps` (0 rows),
  `telemetry_process_events` (6809 rows), `telemetry_model_calls` (435 rows),
  `telemetry_transcripts` (0 rows). All keyed by `session_id`; semantics
  of each unverified at audit time and required reading for any follow-on
  implementation plan.

## 4. Current read-surface inventory

| Reader | What it reads | Field assumptions |
|---|---|---|
| `scripts/session_preflight.py` | `docs/SESSION_LOG.md` for `context.recent_sessions` (last 5 dated entries) | Markdown headings of form `## [YYYY-MM-DD] - <description>`. No structured fields consumed. |
| `scripts/session_postflight.py` | (verify in audit: likely reads markdown to detect open session and ops_session_log for SCD2 close-write) | Implementation-internal; not an agent-facing concern. |
| `.claude/skills/planning/SKILL.md` Read Context | indirect via `docs/PROJECT_CONTEXT.md` | Grep of skill file shows no direct SESSION_LOG literal; reference is via context-bundle inclusion. |
| Retrospective agents (legacy, Decision 59) | telemetry tables joined on session_id | Retrospectives move to telemetry analysis per Decision 59; ops_session_log not consumed in retros. |

Notable absence: no current reader consumes `ops_session_log` directly
in the agent-facing path. This reinforces the Section 12 CD.NN.a
proposal to retire it.

## 5. Schema accuracy assessment scope

The audit recommends a follow-on data-quality pass (named in Section 13
as a follow-on IMPLEMENTATION plan stub, gated on Decision 65 ops.yaml
authority being respected) that:

1. Compares `terraform/iceberg_tables.tf` DDL for `ops_session_log` and
   `telemetry_sessions` against `config/agent/data_quality/ops.yaml`
   field semantics per Decision 65.
2. Confirms SCD2 spine (`created_timestamp`, `last_updated_timestamp`,
   `day(last_updated_timestamp)` partition) per Decision 56.
3. Pulls a sample of actual rows via `sync_ops pull` (existing SSO/Athena
   path; CD.15 confines DuckDB to Lambda-internal so audit-time tooling
   stays on Athena) and diffs declared vs observed shape.
4. Flags drift as DQ recommendations via `file_rec` in the appropriate
   follow-on session, not in this REPORT-ONLY plan.

Audit-time tooling stays on the existing Athena/sync_ops path
deliberately: exercising DuckDB ad-hoc from the agent shell would
contradict CD.15's "DuckDB lives inside the Lambda only" invariant.

## 6. Two-tier event/aggregate split (design pivot)

The substantive design output of this audit. Two tables that together
replace the conflated current state of `ops_session_log` +
`telemetry_sessions` + `docs/SESSION_LOG.md`:

| Tier | Table | Granularity | Cardinality | Write path |
|---|---|---|---|---|
| Events | `telemetry_agent_turns` + `telemetry_agent_turn_transcripts` | One pair of rows per agent turn (Stop-hook-anchored) | ~50-100 rows per session | New Lambda `agent-platform-log-turn` (Section 10) |
| Aggregate | `ops_sessions` (renamed from `telemetry_sessions`, schema TBD) | One row per session | ~1 row per session | **Deferred per Section 9** -- not a current commitment. Likely landing as derived view OR thin session-open/close verbs on an existing Lambda, decided when usage patterns make cuts obvious. |

Rationale for the split:
- Cardinality cleavage: events are O(50) per session; aggregate is O(1).
  Storing both in one table is the conflation problem driving the audit.
- Query-pattern cleavage: event-tier is queried for cost/friction/debug
  analysis (hot, structured, frequent). Aggregate-tier is queried for
  "what did session X accomplish" rollups (warm, summary, less frequent).
- Evolution cleavage: aggregate schema is bespoke per-purpose (overall
  git diffs view, tool-usage view, token aggregation view) and may need
  multiple narrow views rather than one wide table. Event schema is
  stable.

The audit recommends settling the event tier first (Section 7) and
deferring the aggregate tier (Section 9) until usage patterns make
the right cuts obvious.

## 7. Event-tier design

### 7.1 `telemetry_agent_turns` (metadata)

One row per agent turn. Append-only, immutable
(`created_timestamp == last_updated_timestamp`). SCD2 spine kept for
schema parity with other ops/telemetry tables.

| Field | Type | Notes |
|---|---|---|
| `turn_id` | UUID | Primary key. Hook-generated before POST; lets the Lambda dedupe on retry. |
| `session_id` | UUID | FK spine. Allocated by SessionStart hook; passed via env var (`CLAUDE_SESSION_ID`) to downstream hooks. |
| `turn_index` | int | Position within session (1, 2, 3, ...). Lets you reconstruct turn order without timestamp gymnastics. |
| `created_timestamp` | ts (UTC) | Hook-emit time. Decision 56 spine. |
| `last_updated_timestamp` | ts (UTC) | Same as created for immutable events. Required for schema-parity SCD2 view. |
| `principal_type` | enum | `human \| agent \| scheduled_agent \| executor` |
| `principal_id` | str | User email, agent name, scheduled agent ID |
| `agent_harness` | enum | `claude_code_cli \| claude_code_web \| copilot \| cursor \| codex \| aider \| executor`. Web/CLI split is load-bearing for cost analysis. |
| `agent_model` | str | Snapshotted per turn (model can change mid-session via /model) |
| `slash_command` | str nullable | Slash command name only (`plan`, `implement`, etc.). Args go to transcript. |
| `tool_call_count` | int | Materialised count for fast filtering |
| `input_tokens` | int | From API response |
| `cache_creation_tokens` | int nullable | Anthropic prompt cache |
| `cache_read_tokens` | int nullable | Anthropic prompt cache |
| `output_tokens` | int | From API response |
| `reasoning_tokens` | int nullable | Thinking tokens (Opus 4.7, o1-class) |
| `model_calls_count` | int | API round-trips this turn (tool-use loops) |
| `api_cost_usd` | decimal(10,6) | Computed at hook time using model pricing table; immutable snapshot. |
| `duration_ms` | int | Wall clock UserPromptSubmit -> Stop |
| `workflow_kind` | enum nullable | `plan \| implement \| develop_executor \| executor_supervision \| free_form \| scheduled_agent` |
| `branch_at_turn` | str | Git branch at turn time |
| `head_sha_at_turn` | str | Git HEAD at turn time |
| `cwd_path` | str | Working directory |
| `parent_session_id` | UUID nullable | Session FK pointing to the parent agent's session (subagent invocation case). Storing the session FK (not a turn FK) lets tree reconstruction join on `session_id`; the inverse-direction `spawned_subagent_session_ids` array below makes the parent-child relationship queryable from both sides. |
| `spawned_subagent_session_ids` | array<UUID> | Child sessions spawned via Agent tool this turn. Inverse of `parent_session_id`. |
| `agent_sdk_version` | str | Caller-stamped SDK version (e.g. `agent-sdk-0.3.1`). Lets schema evolution trace which SDK produced which payload shape. |
| `hook_version` | str | Hook script version (e.g. `stop_log_turn:v2`). Lets debugging trace which hook implementation emitted the event. |
| `files_read` | array<str> | Files touched via Read tool |
| `files_modified` | array<str> | Files touched via Edit/Write/NotebookEdit |
| `commands_run_count` | int | Bash invocations this turn (count only; full commands in transcript) |
| `filed_rec_ids` | array<str> | Recs filed via file_rec this turn |
| `filed_decision_ids` | array<str> | Decisions ratified this turn |
| `turn_outcome` | enum | `success \| user_interrupted \| api_error \| tool_error \| hook_blocked` |
| `error_class` | str nullable | Structured error class on failure (e.g. `OverloadedError`, `ToolValidationError`); full payload in transcript |

### 7.2 `telemetry_agent_turn_transcripts` (heavy content)

1:1 join with `telemetry_agent_turns` on `turn_id`. Stored separately
to keep metadata queries fast and cheap, allow independent retention
policies, defer privacy regex engineering, and decouple schema evolution.

| Field | Type | Notes |
|---|---|---|
| `turn_id` | UUID | PK + FK to `telemetry_agent_turns.turn_id` |
| `created_timestamp` | ts | Matches metadata row |
| `last_updated_timestamp` | ts | Same (immutable) |
| `user_input` | str | Full text; no truncation. Includes slash command args. |
| `assistant_output` | str | Full final assistant text. |
| `assistant_reasoning` | str nullable | Thinking-token content (Opus 4.7, o1-class). Often largest field. |
| `tool_calls` | jsonb array | Full payloads: `[{tool_name, input, output, duration_ms, success, error?}]`. No `_summary` suffixes needed. |
| `system_messages` | jsonb array nullable | Hook reminders, `<system-reminder>` blocks, `<task-notification>` events injected mid-turn -- useful for debugging "why did the agent do X?" |
| `error_payload` | jsonb nullable | Full structured error payload on failure (metadata holds the class only) |

### 7.3 Partitioning, retention, and PII

Both tables partition by `day(created_timestamp)` per CD.9 uniform rule.

Retention policy (proposed in Section 12 CD.NN.d):
- `telemetry_agent_turns`: retain indefinitely (small per-row, analytics-load-bearing).
- `telemetry_agent_turn_transcripts`: 90-day hot retention, then S3
  Intelligent-Tiering moves to Glacier; eventual purge policy deferred to
  separate CD if PII concerns surface. Iceberg `retention.ms` table
  property expressible.

**PII / credential scrubbing is launch-blocking, not polish.** Iceberg
snapshot retention defeats post-hoc redaction: a SCD2 "redact" append
leaves the original payload in old parquet files until snapshot
expiration runs (typically days-to-weeks) AND orphan-file cleanup runs.
Pre-write hook-side scrubbing is the only effective control. Launch
requires the Stop hook to apply a minimal credential-scrub regex pass
before POSTing (covered patterns: AWS access keys
`AKIA[0-9A-Z]{16}`, AWS secret keys `[A-Za-z0-9/+=]{40}` adjacent to
`aws_secret`, Anthropic keys `sk-ant-[A-Za-z0-9_-]+`, GitHub PATs
`gh[pousr]_[A-Za-z0-9]{36,}`, generic `Bearer [A-Za-z0-9._-]{20,}`).
Matched strings replaced with `[REDACTED:<class>]` in both `user_input`
and `assistant_output` before the payload crosses the wire. Richer PII
detection (structured PII, custom patterns, ML-based) is follow-on
polish per Section 14 Q2. Cited via CD.NN.f.

## 8. Verb-shape decision (the load-bearing choice)

Four options considered for how session-related writes reach the
warehouse. The frame challenge (Section 2) treated all four as
genuine first-class candidates.

### 8.1 Option (i): Internal telemetry writer pattern (rejected)

Sessions/turns are infrastructure telemetry written by Lambda-side or
runner-side internal infrastructure; no agent-facing verb. Pattern matches
the current `agent_telemetry_writer.py` for the sibling telemetry tables.

Rejected reasoning:
- Multiple writers means multiple validation paths, multiple
  stateful-invariant enforcement points, multiple schema-evolution
  surfaces. Decision 69 (Single Portal Invariant) names this drift as the
  anti-pattern.
- Idempotency requires writer-side coordination across processes
  (hooks fire in distinct processes per turn). Lambda-side idempotency
  on `turn_id` is structurally simpler.
- The internal-writer story locks the contract to runtime-internal
  knowledge; future surfaces (e.g. a Cursor harness, a Codex harness)
  re-implement the writer from scratch. Lambda-as-contract is portable.

### 8.2 Option (ii): New `agent-platform-log-turn` Lambda (selected)

One new Lambda owns the turn-write contract. Verb: `log_turn(payload)`.
Internally writes to both metadata + transcript tables. Hooks call it
via `agent_sdk`.

Selected reasoning:
- Single portal (Decision 69) for the turn-write surface.
- Stateful invariants (idempotency on `turn_id`; validation of `session_id`
  exists in `ops_sessions` once that table lands) live in one place.
- Schema evolution = one Lambda redeploy + one Pydantic model update.
- Portable across harnesses: the agent_sdk shim hides Function URL
  discovery + SigV4; any harness with outbound HTTPS can participate.
- Compatible with hook-on-Claude-Code-on-the-web (same hook interface;
  outbound HTTPS reachable from the sandbox).

### 8.3 Option (iii): Bundle into existing log-rec/log-decision verbs (rejected)

Add `source=turn` to ops_recommendations or ops_decisions and overload
the existing log verbs.

Rejected reasoning:
- Decision 63 precedent: execution telemetry was deliberately excluded
  from ops_recommendations DQ scope to preserve the telemetry/ops
  boundary. Folding turn events into ops_recommendations would re-conflate
  what Decision 63 separated.
- Cardinality mismatch: ops_recommendations has O(hundreds) of rows;
  turn events would push it to O(hundreds of thousands), changing the
  table's analytical character.
- Schema mismatch: a turn-event has fields (tokens, duration, tool_calls)
  that have no analogue in ops_recommendations.

### 8.4 Option (iv): Direct outbox staging via existing Decision 51 path (rejected)

Hook writes the turn payload directly to the existing
`logs/.ops-outbox/<turn_id>.json` write-ahead buffer; the existing
`scripts/sync_ops.py` drain picks it up on next invocation and stages
to S3 staging for Iceberg append. No new Lambda. Leverages the
substrate Decision 51 ratified.

Rejected reasoning:
- **No stateful invariant enforcement at write time.** The outbox+drain
  path is fire-and-forget by design: payload validation, idempotency
  on `turn_id`, and `session_id` existence check all happen at sync
  time, far after the hook returns. Failures surface as orphans during
  the next DQ pass rather than as typed 4xx the caller can act on.
- **Drain-cadence coupling.** `sync_ops` runs on a schedule; turn events
  would not appear in the warehouse until next drain (worst case
  several hours). Live cost/friction analysis would lag agent
  activity by the drain interval -- breaks the use case for the table.
- **Schema-evolution surface widened.** Every hook in every harness
  becomes a writer with knowledge of the Iceberg row shape. Decision 69
  (Single Portal Invariant) is violated more deeply than option (i) --
  not just N internal writers but N caller-side writers across harness
  boundaries.
- **No CD.10 alignment.** The end-state architecture (Section 1)
  commits to Lambda-as-tools for agent-facing writes. Bypassing it for
  one write path creates two contracts for the same operation: the
  Decision 51 outbox AND the Lambda surface for everything else. Two
  contracts is worse than two surfaces.

Option (iv) is the closest near-miss to the selected design and is
worth naming explicitly to document that the substrate-leveraging
path was genuinely considered, not skipped past. Per Section 11.2.1,
the *new* Lambda DOES use an outbox internally (carved out as a
per-purpose outbox class, amending Decision 51) -- the rejection here
is specifically against the *agent surface* being the outbox, not
against outbox patterns generally.

## 9. Aggregate-tier design (deferred)

The aggregate session table (`ops_sessions`, renamed from
`telemetry_sessions`) is deferred for principled reasons:

- Multiple narrow views may serve better than one wide table: a
  git-diff aggregate, a tool-usage aggregate, a token-cost rollup, a
  recs/decisions-touched rollup may want different shapes and different
  refresh cadences.
- All useful aggregates can be derived from `telemetry_agent_turns`
  via DuckDB-in-Lambda queries; landing the event table first means
  the aggregates have real data to shape against.
- Probably does not need its own write Lambda. Likely paths:
  - Materialised view computed from turn events via scheduled
    `agent-platform-maintenance` invocation.
  - Or: thin `open_session` / `close_session` verbs on an existing
    Lambda, used only by hooks, with row content derived from turn
    events at close time.
  - Or: pure derived view, no write path -- aggregate query runs at
    read time inside the `agent-platform-query` Lambda.

The decision is deferred to a follow-on REPORT-ONLY plan once the
event-tier has accumulated 3-6 months of data and usage patterns are
visible.

## 10. Write Lambda design: `agent-platform-log-turn`

Naming follows the `agent-platform-{purpose}` convention (chosen over
`agent-platform-{purpose}` so the open-source-ready surface does not
hardcode the maintainer's name).

| Aspect | Decision |
|---|---|
| Function URL auth | AWS_IAM (per CD.10, CD.26) |
| Caller principal | PlatformDev (chained AssumeRole from `agent-service-account` per CD.26) |
| Reserved concurrency | 2 (turn writes can burst when an agent is in heavy tool-use; not 1) |
| Provisioned concurrency | 0 (cold start absorbed by hook-side fire-and-forget + outbox) |
| Idempotency | Caller-supplied `turn_id`; Lambda dedupes on it (returns 200+already_exists on duplicate) |
| Validation | Annotated-Pydantic schema (CD.12); rejects malformed payloads with typed 4xx |
| Write ordering | Metadata row first, transcript row second. Orphan-metadata degrades gracefully (debug returns "no transcript"); orphan-transcript impossible by ordering. |
| Multi-table atomicity | None. Iceberg does not natively transact across tables. DQ alarm-not-gate check (per CD.12) surfaces orphans at sync time -- check named explicitly in Section 12 CD.NN.d. |
| Orphan-metadata operator playbook | When DQ check surfaces a metadata row with no matching transcript: (1) check Lambda CloudWatch error log for the corresponding `turn_id` and the transcript-write call; (2) if the Lambda fully failed mid-write (rare), append a placeholder transcript row with `user_input=assistant_output='[UNRECOVERABLE: write-mid-failure]'` and `tool_calls=[]` so downstream joins succeed; (3) file a `source=ops_rca` rec if pattern recurs (>5/week) per Decision 55. The "no transcript available" debug response is the *graceful* path, not the *fix* path. |
| File-count / compaction | Stop hook produces one parquet per turn (the natural hook write granularity). At 100 turns/session x 30 sessions/month = 3000 events/month divided across `day()` partitions, transcript-table file count grows linearly. Iceberg compaction is mandatory; owner is the existing `agent-platform-maintenance` Lambda (T1.4 / EventBridge-scheduled). Compaction policy: target ~256MB per file; rewrite runs daily during low-activity window. Compaction lag SLO (TBD in T1.9 SLO ratification): file count per partition <1000 at any time. |
| Transcript kill switch | Lambda env var `STORE_TRANSCRIPTS=true\|false`. Defaults true. Allows cost-emergency disable without changing caller code or schema. |
| Class B contract | Ratified per CD.25 at `docs/contracts/lambda-agent-platform-log-turn.yaml` (follow-on plan). |

Read verbs are NOT in this Lambda. They extend the future
`agent-platform-query` Lambda (T0.7c / T1.2, naming per the existing
platform roadmap; whether the `bblake-` prefix is itself renamed for
open-source readiness is out of scope for this audit and deferred to
a separate roadmap-renaming item) with:
- `get_turn(turn_id) -> Turn`
- `list_session_turns(session_id, since?, limit=100) -> [Turn]`
- `get_turn_full(turn_id) -> TurnWithTranscript` (joins both tables internally)
- `get_turn_cost_summary(session_id) -> CostSummary`
- `find_turns_with_tool_error(session_id?, since?) -> [Turn]`

None are urgent; defer to T1.2's query-Lambda verb expansion.

## 11. Hook mechanism (Claude Code, both CLI and web)

### 11.1 SessionStart hook (`.claude/hooks/session_start_log_turn.py`)

Fires once at session start.

1. Generate `session_id = uuid4()`
2. Export as `CLAUDE_SESSION_ID` env var so downstream hooks pick it up.
3. (Future) Call thin `open_session` verb against future session
   aggregate Lambda, OR no-op if Section 9 lands as derived-view.
4. Record `branch_at_open`, `head_sha_at_open`, `cwd_path` in env or
   tmpfile for Stop hook to consume.

### 11.2 Stop hook (`.claude/hooks/stop_log_turn.py`)

Fires once per completed turn (Claude Code guarantees Stop fires once
per turn, including on user interruption with
`turn_outcome=user_interrupted`).

1. Read `CLAUDE_SESSION_ID` from env. If absent, run the fallback ID
   derivation per Section 11.3 -- never null.
2. Gather turn payload from hook input (Stop hook receives assistant
   message, tool uses, token counts, duration).
3. Generate `turn_id = uuid4()` (idempotency key).
4. **Apply credential-scrub regex pass** to `user_input` and
   `assistant_output` per Section 7.3 -- mandatory before any network
   transmission.
5. Call `agent_sdk.log_turn(payload)` -- the SDK shim (T0.8) handles
   Function URL discovery, SigV4 signing, retry policy, and typed
   exception translation per CD.10/CD.26/NS.5. Hooks do NOT POST
   directly.
6. On `agent_sdk` exception (network, 5xx, timeout, throttled):
   delegate to outbox per Section 11.2.1. Hook never blocks the user.

### 11.2.1 Outbox-write-failure operator playbook

When the Lambda call fails, the hook attempts to write to
`logs/.ops-outbox/turns/<turn_id>.json` (per-purpose carve-out from
the existing Decision 51 outbox; the `turns/` subdir is the table
dimension, with `sync_ops` drain dispatching by subdir to the new
Lambda). This itself can fail. Operator playbook:

| Failure mode | Detection | Response |
|---|---|---|
| Disk full on EC2 runner (Decision 74 names this as already-hot risk; volume 82% used at audit time) | `OSError: [Errno 28]` from outbox write; preflight `data_quality.warnings` surfaces it | Manual cleanup of `logs/.token-budget-log.jsonl` rotation, then re-run hook. File a `source=ops_rca` rec citing Decision 74. |
| tmpfs eviction on Claude-Code-web sandbox | Silent: outbox dir vanishes between hook invocations | SessionStart hook re-creates `logs/.ops-outbox/turns/` if missing; outbox accepts data loss between sandbox lifecycles as the contract (sandbox sessions are inherently ephemeral; no SLO for pre-session-end persistence). **Coherence with Section 8.4 rejection**: this is the same fire-and-forget trade-off Section 8.4 rejected for *outbox-as-agent-surface*, scoped here to a narrower failure surface (Lambda unavailable AND sandbox restart in the same window). The rejection was against making fire-and-forget the *contract*; here it is the *fallback*. |
| Permission error (multi-user system) | `PermissionError` from outbox write | Hook logs to stderr; user notified. File a `source=ops_rca` rec citing missing `chmod` on outbox dir. |
| Outbox age exceeds threshold | `sync_ops` drain detects outbox-file age > 24h | DQ rec filed automatically (existing pattern); operator investigates whether Lambda is down or drain is stuck. |
| All-silent: hook returns success, outbox-write succeeded, but drain never picks up | `data_quality.last_run` check counts outbox entries vs Lambda-table row count weekly | Out-of-band alarm via CloudWatch metric `OutboxDrainLag`; SLO threshold TBD in T1.9 SLO ratification. |

Outbox age is tied to a CloudWatch alarm via the existing `sync_ops`
telemetry path. Per Decision 55 (RCA-First), silent telemetry loss is
the canonical failure that RCA scheduled agents are designed to
surface; the alarm above feeds the same loop.

### 11.3 SessionStart fallback ID derivation

`CLAUDE_SESSION_ID` env var is the happy path but loses in five
known modes:

| Loss mode | Cause | Fallback behaviour |
|---|---|---|
| Session restart in same shell | New SessionStart hook fires; env replaced | New session_id allocated; no recovery needed (intentional). |
| `/clear` | Conversation reset; SessionStart re-fires | Same as above. |
| Compaction event | Context summarised; SessionStart may not re-fire | Hook reads `CLAUDE_SESSION_ID`; if env present, reuse. |
| Web sandbox restart | New container; env wiped | New SessionStart fires; new session_id. Per Section 11.2.1, prior sandbox's outbox is lost. |
| Hook fires before SessionStart in some edge case | Race condition (unlikely; Claude Code guarantees SessionStart-first) | Use **fallback ID derivation**: `session_id = uuid5(NAMESPACE_URL, f"{cwd}|{first_message_sha256}|{branch}|{head_sha}")` where `NAMESPACE_URL` is a fixed agent-platform UUID. This is deterministic, joinable across same-session events, and prevents null `session_id` rows that would break cost rollups. **Privacy ordering**: `first_message_sha256` is computed over the *post-scrub* message body (per Section 7.3 regex pass), so a pasted credential never enters the hash input. The SHA256 is one-way regardless, but maintaining the scrubbed-substrate invariant keeps every downstream artefact on the same privacy floor. |

The fallback ID derivation is a real fallback, not a hand-wave: any
turn with a derived session_id is queryable, joinable, and
analytically equivalent to a SessionStart-allocated session_id. A
follow-on DQ check flags rows where the derived ID was used (via a
`session_id_provenance` field; deferred to follow-on if instrumentation
proves the edge case is non-zero in practice).

### 11.4 Web/CLI parity

Claude Code on the web supports the same `.claude/hooks/*.py` interface
as the CLI. Outbound HTTPS from the sandbox is permitted. SigV4 signing
works the same with the `agent_platform` profile credentials chained via
the SessionStart hook's SSO flow. No code branching on harness needed;
`agent_harness` field captured at hook time differentiates.

## 12. Named CDs proposed

Each is a rationale paragraph; full ratification-ready bodies land in a
follow-on filing once T0.7b (log-decision Lambda) is deployed.

### CD.NN.a -- `ops_session_log` is retired; events live in `telemetry_agent_turns`

The current `ops_session_log` table (20646 rows) is event-flavoured
despite its `ops_` prefix, has unverified writer semantics, and is not
consumed by any agent-facing reader path. Its functional role is
duplicated by `telemetry_process_events` for process-level events and by
the new `telemetry_agent_turns` for agent-turn events. Retirement
sequence: (1) writers cut over to the new Lambda; (2) any distinct
historical rows backfilled best-effort with `imported=true` flag; (3)
table dropped via Iceberg DROP TABLE in a dedicated follow-on plan.
Cites NS.4 (no narrative log surface), CD.13 (markdown-with-prose
retired), Decision 50 (Iceberg ops table contract).

### CD.NN.b -- `docs/SESSION_LOG.md` is retired post-T1.5 sweep

The markdown ledger is dead-write work per NS.4 + CD.13. Retired in
two stages: (i) writers stop appending (T1.5 sweep); (ii) the file
itself is moved to `docs/SESSION_LOG_ARCHIVE.md` for historical
preservation, with the live path returning 404 to any reader. Cites
NS.4, CD.13.

### CD.NN.c -- New Lambda `agent-platform-log-turn` for turn-event writes

Establishes the 7th platform Lambda (the 6-Lambda enumeration in the
roadmap is non-exhaustive). Owns the turn-write contract per the
design in Section 10. Class B verb contract per CD.25 ratified at
`docs/contracts/lambda-agent-platform-log-turn.yaml` in a follow-on
plan. Cites CD.10 (Lambda-per-tool), CD.25 (Class B ratification),
NS.5 (typed verbs over Function URLs), Decision 69 (Single Portal
Invariant).

### CD.NN.d -- Two-tier event/transcript split with 1:1 join + orphan DQ check

Metadata (`telemetry_agent_turns`) and content (`telemetry_agent_turn_transcripts`)
are separate tables joined on `turn_id`. Rationale: hot/cold query
separation, retention asymmetry, schema-evolution decoupling.

**Orphan DQ check required at launch**, named explicitly per CD.12
alarm-not-gate pattern: in
`config/agent/data_quality/ops.yaml`, register a check
`telemetry_agent_turn_transcripts.turn_id_has_metadata` asserting that
for every row in `telemetry_agent_turns` there exists exactly one row
in `telemetry_agent_turn_transcripts` with matching `turn_id`. Warns
(does not gate) when the count diverges. The same ops.yaml entry
defines the orphan-metadata operator playbook reference back to
Section 10.

Cites Decision 56 (SCD2 schema simplification), CD.9 (uniform `day()`
partitioning), CD.12 (Annotated-Pydantic as DQ SSOT; alarm-not-gate),
CD.15 (DuckDB inside Lambda for reads, including the join verb).

### CD.NN.e -- Aggregate session table (`ops_sessions`) is deferred with structural trigger

Defers the aggregate-tier design. The deferral has a **structural
trigger**, not a wall-clock one, following the Decision 67 precedent
for naming a reversal condition rather than a date.

Follow-on aggregate-tier REPORT-ONLY plan fires when **all three**
conditions are met:

1. `telemetry_agent_turns` row count >= 10,000 (signal: real usage
   has accumulated)
2. At least 2 distinct `source=ops_rca` or `source=user` recs are
   filed against the event tier requesting an aggregate-shape that the
   raw event table cannot answer cheaply (signal: query patterns
   demand structure)
3. Either `agent-platform-query` Lambda has a deployed verb backed
   by an event-tier query (signal: read path is exercised) OR 6
   months have elapsed since the event-tier Lambda deployment
   (signal: deferral has not slid indefinitely)

Until all three conditions are met, the aggregate-tier remains in
this INTENT's deferred state. Likely landing shape is multiple narrow
derived views rather than one wide table. Cites NS.4 (agent-first),
Decision 62 (no separate scheduled routine when folding into an
existing primitive serves), Decision 67 (precedent for structural
reversal conditions).

### CD.NN.f -- Hook-side credential scrub is a launch criterion

Pre-write credential-scrub regex pass (Section 7.3) MUST be deployed
with the initial `agent-platform-log-turn` Lambda + hook landing.
Iceberg snapshot retention defeats post-hoc redaction: a SCD2 redact
append leaves the original payload in old parquet files until
snapshot expiration AND orphan-file cleanup run. The only effective
control is pre-write hook-side scrubbing so the credential never
crosses the wire. Initial pattern set is narrow (AWS keys,
Anthropic keys, GitHub PATs, generic Bearer tokens); richer PII
detection deferred to follow-on per Section 14 Q2. Cites
Decision 50 (Iceberg immutability), CD.20 + CD.23 (private operational
data invariant), Decision 55 (silent failure surfacing -- a leaked
credential in the table is exactly the silent-failure class RCA was
designed to catch).

## 13. Follow-on IMPLEMENTATION plan stubs

Each stub names the work, the gating prerequisite, and the
Decision-67 deferral marker where applicable. None of these stubs are
written in this REPORT-ONLY plan; they are the named follow-on items
this audit proposes.

| Stub | Gated on | Notes |
|---|---|---|
| Schema-accuracy DQ pass on existing `ops_session_log` + `telemetry_sessions` | Nothing | Section 5 work; files recs for any drift via `file_rec`. |
| Annotated-Pydantic schemas for `telemetry_agent_turns` + `telemetry_agent_turn_transcripts` | T0.12 complete (status: complete) | Lands `src/schemas/telemetry/agent_turns.py` and `agent_turn_transcripts.py` per CD.12. Updates `config/agent/data_quality/ops.yaml` per Decision 65 (including the CD.NN.d orphan check). Updates `terraform/iceberg_tables.tf` DDL (DEFERRED: terraform apply blocked by Decision 67 Lambda-deploy freeze; DDL lands but is not applied until T2.1 lifts the freeze). |
| Implement `agent-platform-log-turn` Lambda | T0.6 module pattern accepted, T0.12.5+ contract ratification ritual lands | DEFERRED: `build_lambda.py --deploy + run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal). Code lands; deploy deferred. Internal write order: metadata first, transcript second. Implements env-var kill switch `STORE_TRANSCRIPTS`. |
| Class B verb contract for `agent-platform-log-turn` | T-1.12 complete (status: complete per recent merge) | `docs/contracts/lambda-agent-platform-log-turn.yaml` per the now-landed Class B ratification ritual. Re-ratification trigger: schema change to either backing table. |
| Credential-scrub regex implementation in Stop hook (`.claude/hooks/stop_log_turn.py` scrubber module) | Nothing -- launch criterion per CD.NN.f | Lands the initial regex set defined in Section 7.3. Pre-write pass before any network call. |
| SessionStart + Stop hooks (`.claude/hooks/session_start_log_turn.py`, `stop_log_turn.py`) | Lambda deployed (Decision 67 reversal) | Hook scripts land but are no-op until Lambda is live; gated on env var. Stop hook bundles the credential-scrub regex from the stub above. Includes Section 11.3 fallback ID derivation. |
| Reader rewire: `session_preflight.recent_sessions` via Lambda query verb | T1.2 (query Lambda verb expansion) deployed with `list_recent_sessions` verb | Part of T1.5 sweep. `list_recent_sessions` is not in T0.7c's minimum_verbs set; expansion belongs to T1.2. |
| Writer rewire: `session_postflight.py` calls `agent_sdk.log_session_close` | Aggregate Lambda or close-verb decision (Section 9) settled | Part of T1.5 sweep. |
| Markdown surface retirement | Reader+writer rewires complete | Per CD.NN.b. |
| Backfill historical rows | All above complete | Best-effort import from `ops_session_log` + `telemetry_sessions` with `imported=true` flag. **Downstream query-verb contract**: every query verb in `agent-platform-query` that touches `telemetry_agent_turns` must accept `include_imported: bool = False` and default-exclude `imported=true` rows from cost rollups, friction analysis, and SLO computations. Including imported rows is opt-in for historical-trend queries only. Prevents the backfill-drift class of rollup error. |
| Aggregate-tier follow-on REPORT-ONLY | Structural trigger per CD.NN.e (3 conditions, not wall-clock) | Per CD.NN.e structural-trigger definition. |
| **Rename `agent-platform-{purpose}` Lambdas to `agent-platform-{purpose}`** | T0.7c deployed (so the first Lambda renamed is the read path with the smallest blast radius) | Bounds the mixed-prefix state to a known lifetime. Sweep covers: `agent-platform-log-rec`, `agent-platform-log-decision`, `agent-platform-query`, `agent-platform-update-rec`, `agent-platform-list-tools`, `agent-platform-maintenance`. Function URLs change; Terraform outputs rewritten; agent_sdk verb-name registry updated; CloudWatch log group names migrated (drop old, create new -- accept log loss in transition). DEFERRED: `build_lambda.py --deploy` (pending Decision 67 reversal). Open-source readiness rationale per the convention introduced in CD.NN.c. |

Per CD.20/CD.23 (private operational data not exported to public repo):
no stub proposes export of session-log or turn-event data outside the
private repo.

## 14. Open questions for follow-on filing

These do not block this INTENT's acceptance but should be settled
when the relevant follow-on plan is filed:

1. **`telemetry_model_calls` overlap**: confirm by reading
   `scripts/telemetry_schemas.py` whether `telemetry_model_calls` is
   per-API-call (one row per Anthropic API request) or per-turn. If
   per-API-call, turn-events are a summary layer and the join is
   `turn_id -> [model_call rows]` (add `turn_id` field to model_calls
   during migration). If per-turn, the two tables overlap and one
   supersedes the other. The schema-accuracy DQ pass in Section 13
   should answer this.
2. **Richer PII detection**: the launch credential-scrub regex
   (Section 7.3 / CD.NN.f) covers AWS keys, Anthropic keys, GitHub
   PATs, and generic Bearer tokens. Follow-on enhancements: structured
   PII (email, phone, SSN), custom user-defined patterns, ML-based
   detection (e.g. AWS Comprehend PII). Each is a separate follow-on
   plan with its own cost/quality trade-off.
3. **Tool-level events table**: if tool-level analysis becomes a hot
   path (currently `tool_calls` jsonb in transcripts is sufficient),
   promote to a `telemetry_tool_calls` table fed from the same hook.
   Defer until query patterns demand it.
4. **`assistant_reasoning` retention**: reasoning content is high-value
   for debug but high-volume. Separate retention from
   `assistant_output` may be warranted (e.g. 30 days hot for reasoning,
   90 days for output). Defer until cost data exists.
5. **Decision 51 amendment scope**: Section 11.2.1 carves out a
   per-purpose outbox subdir (`logs/.ops-outbox/turns/`) under the
   existing Decision 51 outbox umbrella. The Decision 51 ratification
   text does not explicitly contemplate per-table subdirs in the
   outbox. Filing CD.NN.g (or amending Decision 51 inline at next
   roadmap-ratification round) to admit the per-purpose subdir
   pattern is recommended; deferred to the follow-on Lambda
   implementation plan so the amendment is grounded in concrete
   working code rather than speculative design.
6. **`session_id_provenance` field**: Section 11.3 fallback ID
   derivation should be auditable. A `session_id_provenance` enum
   field (`session_start_allocated \| derived_from_cwd_hash \|
   imported`) on `telemetry_agent_turns` would let DQ checks count
   the prevalence of fallback paths and detect if the "edge case" is
   actually structurally common. Deferred to follow-on schema-tuning
   pass; not load-bearing for initial launch.
