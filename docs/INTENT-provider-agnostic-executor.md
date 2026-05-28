# Intent: Provider-Agnostic Executor

**Status: DRAFT.** This document is authoritative only after the formal Decision entries recording the supersession of Decision 40 and CD.7 are filed via the log-decision Lambda (T0.7b). Filing is deferred until that Lambda lands; per the AGENTS.md Temporary Operational Constraints, the bootstrap clause allows the substrate decisions referenced below to bind even while filing-via-Lambda remains pending.

## Update Log

- **2026-05-27 -- CD.27 / CD.28 executor pivot.** The substrate and the LLM-inference-tier model have both been pivoted. Substrate (CD.27): Step Functions (workflow orchestration) + Lambda Durable Functions (agent-persona execution) + Lambda (deterministic glue). Per-step decomposition eliminates the 15-minute Lambda ceiling that originally drove the Fargate-container decision; Fargate retained only as an ECS Run Task escape hatch for >15-minute deterministic steps. LLM-inference tier model (CD.28): DeepSeek-direct via LiteLLM is Tier 1 (primary); Anthropic-direct via LiteLLM is Tier 2 (warm-fetched escape hatch funded by the user's Claude Code Max x5 programmatic-pool credit); OpenRouter is Tier 3 (deferred, unchanged). AWS Bedrock is fully retired from the architecture as an LLM substrate -- the per-token markup (~2.5x input / ~4.9x output vs DeepSeek-direct, DeepSeek excluded from Bedrock Batch, no DeepSeek prompt caching on Bedrock) made it the wrong substrate for the executor's volume profile. The Layer-1 LiteLLM abstraction commitment is preserved verbatim; only the routed provider tier changed.

---

This document defines the long-term architectural direction for the autonomous executor's LLM integration: how it talks to inference providers, how it dispatches tools, and how vendor portability is achieved without committing to any single provider's CLI, SDK, or pricing model. It exists so LLM agents working on this system can compare implementation against intended design and so future model swaps are config-level decisions, not engineering projects.

**Supersedes:** Decision 40 (Executor Platform Migration -- Copilot SDK + Bedrock Planning); CD.7 (LLM-on-Bedrock primary; fully superseded by CD.28); the Fargate-as-executor-substrate clause of CD.11 (narrowly superseded by CD.27, with ECS Run Task escape hatch retained). The original direction committed to GitHub Copilot SDK with Bedrock BYOK, then to a Fargate container calling Bedrock, then to a hybrid Bedrock + Anthropic-direct tier model. Each of those steps was abandoned for a documented reason: the Copilot SDK pivoted (Decision 49 retired it as Lambda inference provider); the Bedrock substrate carried unacceptable per-token markup for DeepSeek-class economics; the Fargate-container substrate did not match the natural state-machine shape of the per-rec executor loop. The current architecture is provider-portable at Layer 1 (LiteLLM), runtime-portable at the substrate boundary (Step Functions + Durable Functions + Lambda are all AWS-native primitives, easily migrable), and credential-portable at the Secrets Manager surface.

**Companion documents:**
- `docs/INTENT-recommendation-executor.md` -- defines what the executor does and the agent-call surface it exposes.
- `docs/INTENT-telemetry-system.md` -- defines the per-step telemetry shape this document's harness must produce.

---

## North Star

The executor's relationship to inference providers is mediated by a thin abstraction layer that treats every model as text-in / text-out. Swapping a model is a config change, not a code change. Swapping a provider is a config change plus a credential change. The executor never imports a vendor SDK directly outside that abstraction layer.

The agent loop -- the orchestration of "send prompt, parse tool calls, dispatch, append results, repeat" -- is owned in our Python code. It is not delegated to a vendor CLI (Gemini CLI, Codex CLI), a vendor SDK (claude-agent-sdk, OpenAI Agents SDK), or a heavyweight framework that conflicts with our telemetry and ops-data invariants. The loop is small, well-tested, and ours.

Tools available to the model are exposed via Model Context Protocol (MCP) servers, not defined inline in the harness. The same MCP servers serve interactive Claude Code sessions and the autonomous executor, eliminating the dual code paths that currently exist around `ops_data_portal`, Athena reads, and file operations.

---

## What This Replaces

### Current State (May 2026)

The executor invokes Gemini CLI as a subprocess to do all agentic work. Gemini CLI owns:
- The inference call (talking to Google's API).
- The tool envelope (its own tool-call format).
- The agent loop (deciding when to call tools, when to respond).
- The tool implementations (`read_file`, `edit_file`, `run_shell_command`, etc.).

`scripts/llm_client.py` exposes a provider-agnostic `llm_call()` surface and contains hand-rolled `_gemini_call` and `_bedrock_call` transports. `scripts/bedrock_client.py` is dormant code retained from before the April 2026 revocation; scheduled for deletion under the `PLAN-retire-bedrock-code-paths` follow-on filed in CD.28. The bedrock transport was not exercised in production; it served plan-critique style calls only.

Tool definitions live inside Gemini CLI. The executor cannot constrain which files a step is allowed to edit, cannot scope tools per step, and cannot inject context on demand -- everything goes in the system prompt as one block.

### Lessons That Inform the Direction

| Event | Lesson |
|---|---|
| Bedrock revocation, April 2026 (Decision 49) | A provider relationship can be revoked unilaterally. The executor must not be hard-coded to one vendor. |
| Bedrock restoration, May 2026 | Provider availability is reversible too. The architecture should welcome a returning provider without requiring re-integration work. |
| Gemini CLI rate-limit pain | Subprocess CLIs have opaque failure modes (rate limits surface as exit codes, not structured errors). In-process clients give us structured retry control. |
| Anthropic billing change (programmatic / headless calls split into a separate plan-tier-sized credit pool, June 2026) | Vendor pricing models change unilaterally. Abstracting the provider makes the change a renegotiation, not a migration. |
| Copilot SDK volatility (high release cadence -- multiple releases per week during evaluation) | Vendor SDKs are not a stable abstraction. Building on top of one is taking on their churn. |
| Bedrock DeepSeek markup discovery + pivot, May 2026 (CD.28) | Provider-hosted-model pricing diverges materially from native pricing for non-flagship vendors. Bedrock charges ~2.5x input / ~4.9x output for DeepSeek V3.2 vs DeepSeek direct API ($0.62/$1.85 vs $0.252/$0.378 per 1M tokens), excludes DeepSeek from the Batch 50%-off mode, and does not propagate DeepSeek's native context caching. The Layer-1 abstraction is what made the pivot a config change, not a re-architecture. Lesson: when a managed-model wrapper charges materially more than the native API, the wrapper's value (billing consolidation, IAM auth, residency) must be evaluated against the executor's volume profile -- at high call volumes, the native API wins. |
| Fargate-vs-Lambda substrate reframing, May 2026 (CD.27) | The original Fargate decision treated the per-rec executor loop as a single long-running process. Per-step decomposition (one Step Functions execution per rec; agent personas as Durable Functions; deterministic glue as regular Lambdas) reframes the loop as a state machine, which is its natural shape. Lesson: substrate decisions are downstream of how the workload is decomposed, not the other way around. Reconsidering decomposition can invalidate substrate choices that were previously load-bearing. |

The strategic conclusion: pick a current preferred provider, but design so the choice is reversible at config-change cost. Make the same discipline apply to the substrate -- decompose the workload such that any substrate change is a state-machine refactor, not a re-architecture.

---

## Architecture

### The Four-Layer Model

Every agentic LLM integration is composed of four layers. Conflating them is the source of most lock-in.

| Layer | What it is | Today | Target |
|---|---|---|---|
| 1. Inference protocol | Wire format to talk to a model API | Gemini CLI subprocess; raw boto3 in dormant Bedrock client | LiteLLM (single client, all providers) |
| 2. Tool-call envelope | How the model emits "call X with args Y" | Gemini CLI internal format | Normalised by LiteLLM to a single internal shape |
| 3. Agent loop | Send -> parse tool calls -> execute -> append -> repeat | Owned by Gemini CLI | Owned by us, in Python |
| 4. Tool implementations | What `read_file`, `edit_file`, `bash` actually do | Owned by Gemini CLI | Exposed as MCP servers, reused across consumers |

### Target Stack

```
+---------------------------------------------------------------------+
|  Step Functions (workflow orchestration, one execution per rec)     |
|  pick_rec -> prepare_workspace -> plan_agent ->                     |
|    Parallel(plan_critic, decision_scout, ...) ->                    |
|    critique_gate -> implement_agent -> code_reviewer ->             |
|    file_pr -> emit_telemetry                                        |
|  (ECS Run Task escape hatch for >15 min deterministic steps)        |
+----------------------+----------------------------------------------+
                       | invokes per state
                       v
+---------------------------------------------------------------------+
|  Per-persona Lambda Durable Function (agent loop)                   |
|                                                                     |
|  +-------------------------------------------------------------+    |
|  | Agent loop (our code, checkpointed by Durable Function)     |    |
|  |  - send messages                                            |    |
|  |  - parse tool calls                                         |    |
|  |  - dispatch to MCP                                          |    |
|  |  - per-turn telemetry via outbox                            |    |
|  |  - DeepSeek native cache (no manual breakpoint placement)   |    |
|  +-------------------------------------------------------------+    |
|  +-------------------------------------------------------------+    |
|  | Provider adapter (LiteLLM) -- CD.28 tier model              |    |
|  |  Tier 1 DeepSeek-direct (primary)                           |    |
|  |  Tier 2 Anthropic-direct (warm-fetched escape hatch,        |    |
|  |    funded by Max x5 programmatic-pool credit)               |    |
|  |  Tier 3 OpenRouter (deferred)                               |    |
|  |  No Bedrock transport (retired by CD.28).                   |    |
|  +-------------------------------------------------------------+    |
|  +-------------------------------------------------------------+    |
|  | MCP client                                                  |    |
|  +-------------------------------------------------------------+    |
+----------------------+----------------------------------------------+
                       | stdio / Streamable HTTP
                       v
              +---------------------+
              |  MCP servers        |
              |  - fs (edit/read)   |
              |  - bash             |
              |  - git              |
              |  - athena           |
              |  - ops_portal       |
              |  - validate         |
              +---------------------+
```

### Component Choices and Why

**LiteLLM (provider adapter).** Open-source Python library; core is MIT, the `enterprise/` directory is separately licensed (not used). Single `completion()` API across 100+ providers. Normalises tool-call envelope shapes so our agent loop sees one internal format regardless of upstream. Native DeepSeek support (`deepseek/deepseek-chat`, `deepseek/deepseek-reasoner`; aliases remap to `deepseek-v4-flash` post-2026-07-24) with thinking + reasoning_effort parameter passthrough. Native Anthropic-direct support. Rejected alternatives: hand-rolled adapter (re-solves a solved problem; we already have evidence of the maintenance cost in `_gemini_call` / `_bedrock_call`), vendor SDKs (re-introduces lock-in).

**LiteLLM dependency risk (explicit).** Adopting LiteLLM means inheriting its bug surface, release cadence, and provider-feature support gaps. The harness must:
- Pin a LiteLLM version in `requirements.txt`; upgrades reviewed in PRs.
- Retain a provider-direct SDK path (httpx + DeepSeek REST; `anthropic` Python SDK) as a documented escape route when LiteLLM regresses or lacks a feature we need. This is a thin httpx-based reimplementation per provider, not a re-introduction of Bedrock's boto3 transport (which was retired by CD.28).
- Treat LiteLLM as the primary path, not the only path. DeepSeek's native context caching is hash-based and requires no client opt-in, simplifying the agent loop versus the prior Bedrock `cachePoint` design.

**In-process Python agent loop (ours), wrapped in a Lambda Durable Function (per CD.27).** The agent loop owns retry semantics, per-turn outbox telemetry, scope enforcement (allow-list paths per step), and result validation. Per CD.27, each agent persona's loop runs inside a Lambda Durable Function -- checkpointed automatically by the Durable Function runtime, with replay-from-last-checkpoint on Lambda timeout. This eliminates the original concern that the loop needed a long-running container (Fargate) to outlast the 15-minute Lambda ceiling. Prompt cache breakpoint placement is no longer a Layer-3 concern under the DeepSeek-direct primary path (native context caching is automatic); the breakpoint-management code that was originally planned simplifies away. Size budget is "small enough to own"; expected to land in the low four figures of LoC per persona once instrumentation is included. If a persona's loop crosses ~1500 LoC during build, re-evaluate frameworks (see Open Questions). Rejected alternatives in current scope: heavyweight frameworks that own state and conflict with the warehouse-as-source-of-truth invariant, vendor SDKs that re-introduce lock-in.

**MCP servers (tool layer).** Tools live in standalone server processes addressed over stdio or Streamable HTTP (the current MCP transport standard as of the March 2025 spec). Both interactive Claude Code sessions and the autonomous executor connect to the same servers, eliminating the current dual code paths around `ops_data_portal`, Athena access, and file operations. Rejected alternative: tool definitions inline in harness code (forces re-implementation for every consumer; this is the source of today's `ops_data_portal` drift between human-via-Bash use and any future agent use).

**Substrate deployment (per CD.27).** The executor is decomposed across three AWS-native substrates: Step Functions (workflow orchestration, one execution per rec), Lambda Durable Functions (per-persona agent loops), Lambda (deterministic glue). The MCP servers run in-process inside each Durable Function (stdio transport); the harness and the MCP servers ship together in a single Lambda deployment package per persona. Credentials (DeepSeek API key, Anthropic API key per CD.28) are fetched from Secrets Manager at cold start via the execution role. ECS Run Task is reserved for the long-step escape hatch only (>15 min deterministic tasks; not the executor's primary substrate). No host dependency surface beyond AWS IAM (for Secrets Manager + the per-Lambda execution role) and outbound HTTPS to DeepSeek + Anthropic APIs.

---

## Provider Strategy

The architecture is provider-agnostic at Layer 1 (LiteLLM). The current provider choices are operationally decided and recorded here for clarity, not for permanence. Per CD.28 (2026-05-27), the tier model is:

### Tier 1: DeepSeek Direct API via LiteLLM (Active, Primary)

Used for all executor agent-persona inference work. Models routed through LiteLLM as `deepseek/deepseek-chat` and `deepseek/deepseek-reasoner` today; aliases remap to `deepseek-v4-flash` after 2026-07-24 per the upstream deprecation schedule (thinking and non-thinking modes of a single underlying model).

**Rationale:**
- **Economics.** $0.252 input / $0.378 output per 1M tokens at the time of the pivot; native context caching at $0.0252 per 1M cache-hit-input tokens with no client opt-in (hash-based, automatic). Compared to the retired Bedrock path: ~2.5x cheaper on input, ~4.9x cheaper on output, and Bedrock prompt caching does not apply to DeepSeek model families. At cost_projection-scale executor inference, the move reduces monthly inference cost by ~75%.
- **LiteLLM-native.** First-class provider support in LiteLLM including thinking + reasoning_effort parameters. No subprocess wrapping; structured JSON tool-call envelope normalised to LiteLLM's internal shape.
- **No Bedrock-Batch exclusion penalty.** DeepSeek is excluded from Bedrock's 50%-off Batch billing mode, so the standard managed-wrapper cost-optimisation path was closed on Bedrock anyway. Direct API has no such restriction.
- **Caching that matches the executor's workload.** Repeated repository-context prefix on every agent-persona invocation cache-hits at near-zero cost; the executor's volume profile (many calls per rec, each sharing a large prefix) gets the cache benefit DeepSeek-on-Bedrock could not offer.

**Constraints:**
- Region: DeepSeek serves from outside the EU. Acceptable for the executor's workload because its input is repository code + ops-table rows -- no end-user PII. If future use cases require EU residency, Tier 2 (Anthropic-direct via Bedrock-on-EU, if re-enabled) or a self-hosted DeepSeek deployment become re-evaluation triggers.
- API stability: DeepSeek's API has been stable through V3.x; CD.28 commits to pinning the LiteLLM provider version and validating the deepseek-v4-flash aliasing at the upstream switchover date.
- Output reliability: structured-output enforcement under DeepSeek varies by model variant; the agent loop validates JSON-schema conformance via Pydantic per turn and surfaces structured retries through the harness, not the provider.

### Tier 2: Anthropic Direct API via LiteLLM (Active, Warm-fetched escape hatch)

Configured in LiteLLM and warm-fetched at every harness cold start. Routed to when:
- DeepSeek API is unavailable (outage, rate-limit).
- A specific agent persona needs Claude-class judgment for a particular call (e.g., a critic persona where DeepSeek's bias profile differs materially from the reference set).
- A regression in DeepSeek model quality triggers manual failover during Stage 4 stability validation.

**Anthropic billing context.** Anthropic's June 2026 billing change splits subscription usage into two pools: an interactive pool (Claude Code in terminal, web chat) and a **programmatic pool** for headless / agent / Agent SDK / `claude -p` / GH Actions calls. The programmatic pool is sized to the active plan tier ($20/month on Pro, $100/month on Max 5x, $200/month on Max 20x), spillover billed at API rates, **does not roll over**.

**Credential source (CD.28).** The user's Claude Code Max x5 subscription provides ~$100/month of programmatic-pool credit. CD.28 routes Tier 2 inference through this credit at current scale. The credit-pool dependency is a documented known-consideration, not a blocker: if executor volume sustains >70% of pool over a 30-day window, CD.28's discipline point recommends provisioning an org-billed Anthropic API key as an overflow credential. The personal credit pool is acceptable for current-scale operations; production-scale operations file the rec.

**Boot validation.** The harness boot path validates the Tier 2 credential on every cold start regardless of routing tier. A failed Tier 2 credential validation blocks harness start with a structured error -- the escape hatch must be warm.

### Tier 3: OpenRouter (Deferred)

Not integrated. Documented here as the next provider to add when triggers fire. Unchanged from the pre-CD.28 tier model except that the comparison baseline has shifted -- the question is no longer "does OpenRouter beat Bedrock for non-Anthropic models" but "does OpenRouter beat DeepSeek-direct + Anthropic-direct for any executor use case."

Remaining OpenRouter justifications:

1. **A concrete A/B testing need for scheduled agents** (rec-curator, doc-freshness, code-smell, prompt-quality) with a measurable quality metric to evaluate against.
2. **A Gemini-specific need.** Neither DeepSeek-direct nor Anthropic-direct serves Gemini; OpenRouter or Google AI Studio direct does.
3. **DeepSeek + Anthropic both restricted simultaneously** -- if both Tier 1 and Tier 2 are unavailable, a hot Tier 3 escape hatch becomes a hardening requirement (KG.7 in ROADMAP-PLATFORM.yaml flags this as the post-CD.28 availability gap).
4. **A non-Tier-1/-2 frontier model demonstrably outperforms** for a specific executor sub-task and we want it in production.

**Pricing model note.** OpenRouter charges a 5.5% fee on credit purchases and otherwise passes provider token rates through. Some models have historically carried per-token markup. Not a flat 5% markup on every call as previously characterised.

### Provider Tier Summary

| Tier | Provider | Status | Use case |
|---|---|---|---|
| 1 | DeepSeek direct API (via LiteLLM) | Active, primary | Executor agent-persona inference; planning/critique |
| 2 | Anthropic direct API (via LiteLLM, funded by Max x5 programmatic-pool credit) | Active, warm-fetched escape hatch | Claude-class judgment when DeepSeek unavailable or persona-specific need |
| 3 | OpenRouter | Deferred | Activated on triggers above (concrete A/B need, Gemini-specific, Tier-1+-2 dual outage, frontier-model outperformance) |
| -- | AWS Bedrock | **Retired by CD.28** | Removed from the architecture as an LLM substrate. PlatformDev IAM `bedrock:InvokeModel` retained as vestigial-but-harmless per CD.28 discipline point. |

---

## Model Selection (resolved by CD.28; persona-specific re-evaluation deferred to Stage 2)

The executor's primary inference model is DeepSeek V3.2 (today; transitions to deepseek-v4-flash post-2026-07-24 per the upstream alias remapping) via the Tier 1 DeepSeek-direct path per CD.28. The "Bedrock-vs-direct-vs-Anthropic" model selection question that previously sat at this section is closed by the CD.28 tier model: DeepSeek is primary because the economics, caching profile, and code quality align; Anthropic Haiku 4.5 / Sonnet 4.6 is the warm-fetched fallback per Tier 2.

The current candidate-comparison table is preserved below as historical context; the rows describing Bedrock-hosted variants are no longer load-bearing for current architecture (Bedrock is retired per CD.28) but inform the historical reasoning behind why DeepSeek-direct won the executor-substrate choice.

| Model | Available via | Prompt caching | Code quality (subjective) | Cost profile |
|---|---|---|---|---|
| **DeepSeek V3.2 (deepseek/deepseek-chat)** | DeepSeek direct API + LiteLLM (Tier 1, ACTIVE) | Yes (native, hash-based, automatic; $0.0252 cache-hit input per 1M tokens) | Strong | Very cheap ($0.252 input / $0.378 output per 1M tokens) |
| **Claude Haiku 4.5** | Anthropic direct API + LiteLLM (Tier 2, warm-fetched) | Yes (Anthropic native cache control) | Strong | Cheap-by-Claude-standards; funded by Max x5 programmatic-pool credit at current scale |
| Claude Sonnet 4.6 | Anthropic direct API + LiteLLM (Tier 2 for upgraded-judgment cases) | Yes (Anthropic native cache control) | Frontier-class | Mid-range; reserved for cases where Haiku 4.5 underperforms |
| DeepSeek-reasoner (thinking mode) | DeepSeek direct API + LiteLLM (Tier 1 variant) | Yes (native) | Strong, with explicit reasoning trace | Same input/output as deepseek-chat; thinking mode adds output tokens |
| ~~Qwen3 Coder Next on Bedrock~~ | ~~Bedrock-managed~~ | n/a | Strong, code-specialised | RETIRED COMPARISON -- Bedrock substrate removed by CD.28 |
| ~~Llama 4 / Mistral Large 2 on Bedrock~~ | ~~Bedrock-managed~~ | n/a | Moderate | RETIRED COMPARISON |
| ~~Amazon Nova Pro / Lite~~ | ~~Bedrock-managed~~ | n/a | Untested for our use case | RETIRED COMPARISON |

**Per-persona re-evaluation (Stage 2 work).** Each agent persona (plan_agent, plan_critic, decision_scout, implement_agent, code_reviewer) lands its own Lambda Durable Function under T4.2 with its own model-tier mapping. The default is DeepSeek V3.2 (Tier 1). Persona-specific upgrades to Anthropic Haiku 4.5 or Sonnet 4.6 (Tier 2) are evaluated against the benchmark corpus per persona and recorded in the per-persona atomic IMPLEMENTATION plan.

**Benchmark corpus (carried forward from prior Open Question 1, repurposed).**
- Establish a benchmark corpus: >=10 representative recommendations covering plan + implement + recovery paths.
- Define primary quality metric: merged-without-revert rate over the corpus.
- Define cost metric: total $ per merged rec, including cache benefit.
- Run DeepSeek V3.2 (default) and Anthropic Haiku 4.5 (Tier 2 candidate for persona upgrade) against the corpus.
- Re-run on each upstream model alias remap (e.g. deepseek-v4-flash switchover) to validate the new model variant.
- Decision cadence: per-persona, recorded in the persona's atomic IMPLEMENTATION plan.

The architecture supports per-persona variation; the choice is operational and can change without touching the substrate layers.

---

## Tool Layer (MCP)

### Why MCP

Tool definitions are an interface, not implementation detail. Today they are entangled with Gemini CLI; any future executor harness must re-implement them. The `ops_data_portal` module is callable only from Python via Bash (or via a Python `Skill`-loading shim) -- it has no formal contract that an LLM agent can introspect.

Exposing tools as MCP servers gives:
- A single source of truth per tool, consumed by both interactive Claude Code sessions and the autonomous executor.
- Discoverability: the model can list tools, read descriptions, and inspect schemas without bespoke wiring.
- Process isolation: each tool runs in its own server process, sandboxable separately from the harness.
- A stable contract that survives harness changes.

### MCP Servers to Build

| Server | Wraps | Consumers |
|---|---|---|
| `ops-portal` | `scripts/ops_data_portal.py` (`file_rec`, `update_rec`, `sync`) | Executor; Claude Code interactive sessions |
| `athena` | Athena query execution against ops tables, Iceberg reads | Executor; rec-curator scheduled agent; interactive sessions |
| `fs` | Bounded file read / edit / write with allow-list path enforcement | Executor; interactive sessions |
| `bash` | Bounded shell execution with timeout and output capture | Executor; interactive sessions |
| `git` | Branch creation, status, commit, push (no force-push, no main writes) | Executor |
| `validate` | `python -m scripts.validate` invocations with structured result parsing | Executor |

The `fs` and `bash` servers are particularly valuable because they enforce scope (allow-list paths, command denylist) that Gemini CLI today cannot. Per-step tool scoping is expected to reduce scope-creep failures observed under Gemini CLI; the benefit is operationally validated post-Stage 2 against scope-creep rec history.

### MCP Server Versioning and Schema-Skew Policy

Tools served via MCP are an inter-process contract. Without explicit versioning the contract drifts silently.

- Each MCP server publishes a semantic version and a schema hash (hash of `tools/list` output).
- The harness pins a minimum-compatible version per server in config.
- On startup the harness performs a `tools/list` probe (per-server deadline; short for `fs`/`bash`/`git`, longer for `athena` and `ops-portal` which may require SSO/STS warm-up) and refuses to start if any server reports a schema hash mismatch against the pinned expectation.
- Breaking changes require a deprecation window: the server publishes both old and new tool names for one release cycle.
- Servers are versioned by container image SHA; harness pins a manifest of expected SHAs.

### Per-Step Tool Scoping

A core capability the new harness must support and Gemini CLI does not: **different agent calls expose different toolboxes.**

| Agent role | Tools exposed |
|---|---|
| Plan agent | `fs.read`, `fs.list`, `athena.query`, `git.status` |
| Plan critique agent | `fs.read`, `athena.query` |
| Implementation agent (per step) | `fs.read`, `fs.edit` (path-scoped to step's allow-list), `bash` (command-scoped), `git.status` |
| Code review agent | `fs.read`, `git.diff` |
| Recovery / CI triage agent | `fs.read`, `bash`, `validate` |

The harness enforces the allow-list; the model sees a structured refusal as a tool result and self-corrects.

### MCP Failure Semantics

MCP servers are processes. They crash, hang, and drift. The harness must define behaviour for each:

| Failure mode | Harness behaviour |
|---|---|
| Server fails startup probe (5s `tools/list` deadline) | Refuse harness start; emit alarm; do not begin step execution. |
| Server schema hash mismatch | Refuse harness start; require manual version reconciliation. |
| Tool call exceeds per-call deadline | Kill the call, mark step as `TOOL_TIMEOUT`, do not retry automatically -- escalate to recovery agent. |
| Server crashes mid-call (no response) | Mark in-flight call as `TOOL_CRASH`; restart server once; if it crashes again, terminate the step and escalate. |
| `ops-portal` crash after staging an outbox entry but before confirming | Outbox is the source of truth for "did the write happen"; on next sync, the outbox is drained idempotently. Idempotency key: `(rec_id, action, content_hash)`. Duplicate outbox entries with the same key are merged at sync time. |
| `fs.edit` crash after partial write | File system is the source of truth; the harness re-reads the affected file and decides next action based on diff vs. expectation. |
| `bash` server crash mid-command | The harness cannot recover the subprocess's filesystem effects; mark step as `BASH_CRASH`, snapshot working tree state, escalate. |

The `ops-portal` server is the only tool whose calls have transactional implications against external systems (Athena, S3 staging). All other tool calls are local-state-only and can be retried or rolled back via filesystem inspection.

---

## Cost Attribution and Reconciliation

The hand-rolled agent loop will issue many model calls per step and many steps per rec. The existing `LLMResult.cost_usd` field is computed per-call from a hardcoded price table (`_PRICING` in `scripts/llm_client.py`); this will drift from actual Bedrock pricing.

**Telemetry grain (committed):** `(rec_id, step_id, turn_index, model_id, tokens_in, tokens_out, cached_tokens_read, cached_tokens_written, est_cost_usd, latency_ms)`.

**Naming convention:** the internal field is `est_cost_usd`, not `cost_usd`. This signals to downstream consumers that it is an operations-time estimate, not authoritative billing. **Migration path:** Stage 1 ships `est_cost_usd` as an alias alongside the existing `LLMResult.cost_usd` (both populated identically). Stage 2 deprecates `cost_usd` once downstream consumers are updated. This preserves the Stage 1 "no shape break" promise while landing the naming convention early.

**Authoritative cost source:** per-provider invoice/usage export. A monthly reconciliation job compares summed telemetry `est_cost_usd` against (a) DeepSeek's usage dashboard / invoice export (Tier 1) and (b) Anthropic's usage dashboard / Console invoice (Tier 2 spillover above the Max x5 programmatic-pool credit). Discrepancies >5% trigger a price-table refresh and a post-mortem. The previous "AWS CUR is authoritative" model was retired by CD.28 -- AWS-CUR no longer captures the executor's LLM spend because Bedrock is out of the LLM substrate.

**Per-rec attribution query:** `SELECT rec_id, SUM(est_cost_usd) FROM ops_telemetry WHERE event_type = 'llm_call' GROUP BY rec_id` answers "what did rec X cost end-to-end." This requires telemetry to be tagged with `rec_id` at every turn, not just at step boundaries.

**Outbox interaction.** Per-turn telemetry is written through the existing outbox pattern (`logs/.ops-outbox/`), drained once per step boundary. The agent loop never reads its own telemetry files; the warehouse-as-source-of-truth invariant is preserved. Telemetry rows have a unique `(session_id, turn_index)` key enforced at write time.

---

## Credential Lifecycle

Post-CD.28, three credential types exist across the tier model. All are API-key-shaped (no IAM-native LLM path remains since Bedrock retired). Their handling must be coherent.

| Tier | Credential | Storage | Rotation | Local dev |
|---|---|---|---|---|
| 1: DeepSeek direct | API key | AWS Secrets Manager (per-environment) | Quarterly, calendar-reminded | Separate dev key from a dev-only Secrets Manager entry |
| 2: Anthropic direct (Max x5 programmatic-pool funded; org-billed key when overflow filed) | API key | AWS Secrets Manager (per-environment) | Quarterly, calendar-reminded | Separate dev key, never production key |
| 3: OpenRouter (when activated) | API key | AWS Secrets Manager | Quarterly | Separate dev key |

**Boot-time behaviour:**
- All credentials are mounted from AWS Secrets Manager via the per-Lambda execution role at cold start. No credentials embedded in the deployment package.
- The Tier 2 (Anthropic-direct) credential is fetched and validated on every cold start regardless of routing tier. The escape hatch must be warm. A failed Tier 2 credential validation at boot blocks harness start with a structured error.
- The Tier 1 (DeepSeek-direct) credential is fetched at cold start and validated on the first inference call (no separate boot-time validation -- the first call fails fast if the key is invalid).

**Rotation:**
- DeepSeek-direct: quarterly rotation, calendar-reminded. Rotation runs through Secrets Manager versioning; old version retained for one rotation cycle.
- Anthropic-direct: quarterly rotation, same model.
- OpenRouter: quarterly, same model.
- If a key is suspected leaked: immediate rotation via Secrets Manager + invalidation of the prior version + audit log review.

**Local dev:**
- Local dev uses dev-only Secrets Manager entries for both DeepSeek and Anthropic keys (lower quota, separate billing).
- Production keys are never copied to developer machines.
- The `bin/venv-python` wrapper resolves the local-dev Secrets Manager profile by environment variable; default points at the dev-only entry, never production.

---

## Health Signals and SLOs

Production health is not observable today (Gemini CLI failures surface as exit codes parsed from stderr). The new harness emits explicit signals.

| Signal | Metric type | Alarm threshold (initial) |
|---|---|---|
| Per-step success rate | Rolling 1-hour ratio | <90% sustained for 30 min |
| Per-rec wall time p50 / p95 | Distribution | p95 > 2x rolling 7-day baseline |
| MCP server crash count | Counter | >3 in 1 hour |
| DeepSeek 4xx rate (Tier 1) | Counter | >5 in 5 min (signals quota or config) |
| DeepSeek 5xx rate (Tier 1) | Counter | >2 in 5 min (signals provider degradation -- consider Tier 2 failover) |
| Anthropic 4xx rate (Tier 2 escape hatch) | Counter | >5 in 5 min when actively routed |
| Anthropic 5xx rate (Tier 2 escape hatch) | Counter | >2 in 5 min when actively routed |
| Anthropic programmatic-pool utilisation | Gauge | >70% of Max x5 pool over 30 days (per CD.28 discipline point -- file rec for org-billed key) |
| LiteLLM exception rate | Counter | Any exception not handled by the harness |
| Lambda Durable Function checkpoint-replay rate | Counter | >5 in 1 hour (signals persona-loop hitting Lambda timeout regularly; investigate persona work decomposition) |
| Cost-per-rec rolling avg | Gauge | >1.5x rolling 7-day baseline |
| Tier 2 Anthropic credential validation at boot | Boolean | False blocks harness start (escape hatch must be warm) |
| Outbox drain lag | Gauge | >5 min since last successful drain |

Alarms route to CloudWatch alarms with SNS notifications.

**Baseline bootstrap policy.** Rolling-baseline alarms (p95 wall time, cost-per-rec) cannot fire in week 1 of parallel-run because there is no baseline. The harness operates under absolute thresholds for the first 7 days of new-loop traffic, transitioning to relative baselines once 7 days of telemetry accumulate. Absolute thresholds are codified before Stage 2 launch and tuned conservatively (intended to alarm on order-of-magnitude regression, not normal variance).

---

## Migration Stages

Migration is gated by the data quality and telemetry priorities recorded in the operational constraints. No migration stage starts until that prerequisite is cleared. Stages are sequential; each is independently valuable.

### Stage 1: Provider Adapter Only

Replace the hand-rolled `_gemini_call` / `_bedrock_call` branching in `scripts/llm_client.py` with LiteLLM for non-agentic call sites. Keep Gemini CLI as the agent harness for now. Post-CD.28, LiteLLM routes to DeepSeek-direct (Tier 1) and Anthropic-direct (Tier 2 warm-fetched escape hatch) for any non-agentic calls (planning, critique, rec-curator) without touching the executor's core loop. The Bedrock transport is removed in Stage 1, not preserved -- per CD.28 Bedrock has no remaining role in the architecture; retaining the transport as a fallback would leave a live dispatch path to a retired substrate.

**Scope (explicit):** Stage 1 replaces transports for `tools=False` call sites only. Agentic `tools=True` paths (today: scheduled agents per Decision 49 -- see CD.28 follow-on resolution discipline_points) remain on their existing transport until Stage 2. The `excluded_tools` parameter contract is preserved at the LiteLLM boundary for `tools=False` paths; tool-scoping behaviour for the agentic paths is unchanged in Stage 1.

**Entry criteria (gating Stage 1 start):**
- `ops_telemetry` schema migration plan defined and approved: explicit ALTER plan (add `turn_index`, `cached_tokens_read`, `cached_tokens_written`, `est_cost_usd`, `latency_ms`; backfill policy; partition key impact assessment).
- Benchmark harness ownership resolved (closes Open Question 8): named owner, corpus location, update cadence, runner location (local script vs Lambda).
- DeepSeek API key + Anthropic API key provisioned in AWS Secrets Manager per CD.28 / T0.4. The Anthropic credential is the Max x5 programmatic-pool-funded personal-subscription key at current scale; org-billed-key overflow is filed per CD.28 discipline-point when sustained >70% of pool over 30 days.

**Effort:** ~3 days once entry criteria are met.
**Reversibility:** High. LiteLLM is a drop-in; reverting is a `pip uninstall` + git revert. The Bedrock transport is deleted in Stage 1 per CD.28; rollback to a Bedrock path requires a follow-on plan to reinstate the transport, which is intentional friction matching the architectural retirement.
**Telemetry impact:** `LLMResult` gains `est_cost_usd` as an alias for `cost_usd` (both populated). No removals.

**Exit criteria:**
- 7-day spend baseline published by purpose (executor / planning / scheduled agents) measured against per-provider invoice export (DeepSeek + Anthropic dashboards), not AWS CUR.
- DeepSeek native cache hit-rate measured on the executor's repository-context prefix (hash-based, automatic -- the measurement is observational, not a tuning knob).
- `excluded_tools` regression suite green at the LiteLLM boundary (`tools=False` paths only).
- Benchmark corpus populated (>=10 recs) and benchmark runner producing results.
- Model selection (Open Question 1) confirmed for the per-call-site model registry; Open Question 1 itself is already closed by CD.28 for Tier 1 default.

### Stage 2: In-Process Agent Loop

Build the Python agent loop. Replace `subprocess.run("gemini ...")` in `scripts/executor/step_runner.py` with an in-process loop calling LiteLLM and dispatching tools as direct Python function calls (not yet MCP). Tools remain inline in the harness for this stage to limit blast radius.

**Effort:** ~2-3 weeks.
**Reversibility:** Medium. The new loop ships behind an `EXECUTOR_LOOP=gemini|inproc` feature flag that remains live for at least 30 days post-cutover. The Gemini CLI path stays in `requirements.txt`. **CI enforcement:** a CI assertion verifies that both `EXECUTOR_LOOP=gemini` and `EXECUTOR_LOOP=inproc` jobs ran and passed within the last 24h before any merge to `main`; if either path has not exercised, the merge is blocked. This prevents silent rot of the rollback path. Rollback criteria are codified before Stage 2 launch (per-step success rate floor, cost ceiling, latency ceiling).
**Telemetry impact:** Significant. Per-turn token counts, cache hit rates, and tool invocations become first-class telemetry instead of being parsed from CLI transcripts. Schema changes are additive; old fields retained. `cost_usd` is deprecated in Stage 2 once `est_cost_usd` is verified equivalent.
**What persists after revert:** Telemetry rows already written in the new shape do not retract. Schema is additive so this is non-breaking, but downstream consumers must tolerate fields appearing partway through history.

**Exit criteria:**
- Per-step success rate at or above Gemini CLI baseline (measured during parallel-run).
- Cost-per-rec within agreed ceiling.
- **Step boundaries idempotent under SIGTERM at any point.** This is a precondition for Stage 4 Spot-tolerant deployment: a Spot interruption mid-step must leave the system in a state recoverable by re-running the step from its boundary. Multi-tool sequences (`fs.edit` + `git commit` + `ops-portal update_rec`) must be wrapped in a step-boundary recovery primitive that snapshots pre-step state (e.g., `git reset --hard <pre-step-sha>` plus outbox-entry replay).
- Baseline bootstrap thresholds (Health Signals section) codified and active.

**Unblocks:** Stage 3; per-step tool scoping; precise context injection via tool calls; structured retry on rate limits.

### Stage 3: MCP Tool Servers

Wrap each in-harness tool as an MCP server. One server per concern. Add the harness's MCP client. Configure interactive Claude Code sessions to consume the same MCP servers via `.mcp.json`.

**Effort:** ~1 week per server, parallelisable. Recommend `ops-portal` first (highest reuse value, eliminates dual code path with interactive sessions).
**Reversibility:** High per-server. Each server is wrapped behind a `TOOL_BACKEND_X=mcp|inline` flag; rollback restores the inline tool implementation. The inline implementation is retained until the MCP server has been stable in production for 30 days.
**Telemetry impact:** Tool invocations now flow through a stable MCP boundary, simplifying the audit trail.
**MCP failure semantics from this document apply** -- harness must implement startup probes, schema-hash checks, and crash handling before any server goes to production.
**Unblocks:** Stage 4; eliminates `ops_data_portal` interactive/automated drift; lays foundation for any future agent to use the same tools.

### Stage 4: Substrate Deployment (resolved by CD.27)

Per CD.27 (2026-05-27), the substrate is decomposed across three AWS-native primitives. The original "container deployment" framing of this stage is retired -- the harness is not a single deployment target; it is three coordinated deployment targets:

| Substrate | Role | Why |
|---|---|---|
| **Step Functions (Standard Workflow)** | Workflow orchestration -- one execution per rec | Native AWS, decision-39-ratified. Native Parallel for critic fan-out, Choice for routing, retry policies, durable state up to 1 year per execution. Eliminates the orchestration code we would otherwise hand-roll. |
| **Lambda Durable Functions** | Per-persona agent loops | Released 2026; designed exactly for agentic iterative read-LLM-tool loops. Checkpoints execution step-by-step; on Lambda timeout, the next invocation replays from the last completed checkpoint and skips completed tool calls. Eliminates the 15-minute Lambda ceiling concern that originally drove the Fargate decision. |
| **Lambda (regular)** | Deterministic glue | pick_rec, prepare_workspace, critique_gate aggregator, file_pr, emit_telemetry. Sub-15-minute by construction. <1s cold start. Per-Lambda IAM execution roles per CD.10. |
| **Fargate (via Step Functions ECS Run Task `arn:aws:states:::ecs:runTask.sync` integration)** | Escape hatch only -- deterministic steps that genuinely exceed 15 minutes (full pytest, terraform apply, large data migration) | Retained from the original Stage 4 design but demoted from primary substrate to escape-hatch role. |

**Runtimes evaluated and not selected:**

| Runtime | Status under CD.27 | Why |
|---|---|---|
| ~~AWS Lambda Container as single-process harness~~ | **N/A** | Original rejection rationale ("15-min ceiling incompatible with executor step duration") was a single-process framing. Per CD.27, the executor is decomposed across primitives; per-Lambda invocations are all sub-15-minute. The rejection rationale itself was invalidated by the substrate-decomposition reframing. Lambda IS the substrate at the per-step layer. |
| ~~AWS Fargate as single-container executor~~ | **Retired by CD.27** | Original "leading candidate" verdict was correct under the single-process framing. The substrate-decomposition reframing eliminated the single-process need. Fargate retained as ECS-Run-Task escape hatch only. |
| AWS Batch (Fargate Spot backend) | **Retired by CD.27** | Original "strong candidate" verdict assumed job-queue semantics over a single Fargate executor. Step Functions provides the queue + state machine semantics natively; AWS Batch is redundant. |
| Modal / Cloud Run Jobs / EKS | **Unchanged from prior verdict** | Modal sacrifices AWS billing consolidation; Cloud Run Jobs is wrong cloud; EKS is operational-overhead disproportionate. |
| Lambda Durable Functions alone (without Step Functions) | **Considered, rejected** | Could orchestrate the entire per-rec lifecycle inside a single Durable Function. Rejected because: (a) Step Functions is already ratified as the orchestrator per Decision 39, breaking that for the executor specifically would diverge from established precedent; (b) Step Functions provides native Parallel state for critic fan-out -- recreating that inside a single Durable Function adds complexity; (c) Step Functions executions are visible in the AWS Console with native step-by-step execution history, which is materially better for debugging than Durable Function logs alone. |

**Effort estimate.** Atomic decomposition per the freeze override + per-substrate-layer split (T4.1 Step Functions + glue Lambdas; T4.2 per-persona Durable Functions). T4.1: ~1-2 weeks. T4.2: ~1 week per persona (5 personas) = ~5 weeks. Total ~6-7 weeks across multiple atomic plans.

**Reversibility.** High at the substrate-decomposition level (the per-step layer can swap Lambda for Fargate per step without changing the Step Functions state machine shape); medium at the Durable-Functions-vs-self-checkpointed-Lambda level (re-evaluating Durable Functions requires re-implementing the checkpoint primitive but the agent loop code itself ports unchanged).

**Telemetry impact.** Step Functions execution history + per-Lambda metrics + Durable Function checkpoint events all join per-step telemetry. CloudWatch insights cover all three substrates natively.

**Decision 67 interaction.** Stage 4 is not blocked by Decision 67; it is part of the reversal trigger cascade. Per CD.17, the STRATEGIC-plan-freeze reverses when `T4.2.status == "complete" AND grace_period_elapsed(T4.2, 14) AND ...` -- T4.2 (the Stage 4 substrate) IS the trigger precondition, not the blocker. The Lambda-deploy half of Decision 67 is governed per CD.16 per-Lambda gating -- each T4.1 / T4.2 / T4.3 atomic plan inherits CD.16 + Decision 67 deferred-deployment markers in the planning skill until the dispatcher Lambda re-enables (CD.16 DEFERRED clause expires automatically at T4.3 completion). Decomposition under the freeze: T4.2 is `strategic: true` in the roadmap, so per AGENTS.md Temporary Operational Constraints, it lands as multiple atomic IMPLEMENTATION plans (per-persona Durable Function) rather than a single STRATEGIC plan.

---

## Non-Goals

- **A unified message format across providers.** LiteLLM does this for us. We do not build our own provider abstraction.
- **A full agent framework adoption in current scope.** The agent loop is small enough to own. Pydantic AI and LangGraph remain Open Questions for re-evaluation if loop complexity grows beyond expectations.
- **A single-vendor commitment.** DeepSeek-direct is the current primary (per CD.28), not the permanent answer. The architecture treats provider choice as a config-level decision -- the Layer-1 LiteLLM abstraction is what makes tier-model changes a config edit rather than a re-architecture.
- **A self-hosted LiteLLM Proxy.** The Python SDK is enough. The proxy becomes interesting when multiple non-Python runtimes need centralised LLM access; we are not at that scale.
- **Building our own MCP runtime or protocol.** MCP is an existing standard with an Anthropic-led but cross-vendor SDK. We consume; we do not extend.
- **Replacing interactive `/plan` and `/implement` workflows.** Those remain Anthropic-locked deliberately.
- **Provider-portable prompts.** The prompts in `config/agent/executor/prompts/` are tuned against specific models. Swapping the production executor model requires regression evaluation against the benchmark corpus -- prompts are not zero-cost portable across providers.
- **An immediate migration.** Data quality work on ops tables and telemetry takes precedence. This document defines target architecture, not a near-term project.

---

## Open Questions

1. **Executor model selection.** ~~Qwen3 Coder Next vs DeepSeek V3.2 vs Claude Haiku 4.5, all on Bedrock.~~ **Closed by CD.28.** Tier 1 = DeepSeek V3.2 (transitioning to deepseek-v4-flash 2026-07-24). Per-persona upgrade evaluation to Anthropic Haiku 4.5 / Sonnet 4.6 deferred to per-persona atomic plans under T4.2. Benchmark corpus (>=10 representative recs, merged-without-revert rate, $ per merged rec) carried forward for per-persona evaluation.
2. **Pydantic AI re-evaluation.** Stage 2 commits to a hand-rolled loop per Durable Function persona. If a persona's loop accumulates complexity beyond ~1500 LoC during build (multi-agent orchestration, structured-output retry, dependency injection patterns), Pydantic AI is the leading framework candidate to absorb that complexity. Decision deferred to per-persona atomic plan implementation; framework choice is per-persona, not architecture-wide.
3. **LangGraph re-evaluation.** LangGraph's `StateGraph` matches the executor's linear-with-recovery topology and provides checkpointing, replay, and time-travel debugging out of the box. Earlier dismissal on "LangChain ecosystem buy-in" grounds is outdated (LangGraph has been usable standalone since v0.2). Re-evaluate at per-persona implementation alongside Pydantic AI; the determining factor is fit with the warehouse-as-source-of-truth invariant and OpsWriter telemetry contract. Note: Lambda Durable Functions provide checkpointing natively, partially obviating LangGraph's strongest selling point for this architecture.
4. **MCP server hosting model in Stage 3.** stdio (subprocess per server) is simplest but limits sharing; Streamable HTTP (the current MCP transport standard) allows multiple consumers but adds an availability concern. Decision deferred to Stage 3. (Note: under CD.27's per-persona Lambda Durable Function packaging, stdio is the natural fit -- the MCP server runs in-process inside each Durable Function deployment. Streamable HTTP becomes interesting only if MCP servers are shared across Durable Function instances.)
5. ~~**Container runtime in Stage 4.** AWS Batch on Fargate Spot vs ECS Fargate direct vs Modal.~~ **Closed by CD.27.** Substrate is Step Functions + Lambda Durable Functions + Lambda. ECS Run Task via Step Functions integration is the long-step escape hatch. AWS Batch and Modal are retired as candidates. See Stage 4 selection table.
6. **Prompt cache strategy.** ~~Bedrock's `cachePoint` blocks require explicit placement.~~ **Reframed by CD.28.** Tier 1 (DeepSeek-direct) uses hash-based automatic context caching -- no client breakpoint placement required, no manual strategy to determine. Tier 2 (Anthropic-direct) uses Anthropic's native cache_control which is also automatic at the message-boundary level. The original breakpoint-strategy concern simplified away with the substrate change; remaining open question is purely operational (cache-hit-rate monitoring and per-persona tuning of context construction to maximise prefix-stability for cache reuse). Deferred to per-persona atomic plans.
7. **Telemetry schema versioning policy.** Additive-only changes are safe; deletions and renames require a versioning story. Defer until first breaking change is proposed.
8. **Benchmark harness ownership.** Named owner, corpus location in repo, update cadence, runner location -- carried forward from prior framing and remains a per-persona-atomic-plan prerequisite. Each persona's atomic plan owns its benchmark wedge of the corpus and the per-persona runner script.
9. **Step Functions vs Durable Functions internal orchestration boundary.** CD.27 sets the boundary at "Step Functions for graph; Durable Functions for agent loop." Open per-persona question: should a persona ever invoke a sub-Step-Function for a sub-graph (e.g. plan_agent invoking a sub-graph of read-many-files-in-parallel before composing the plan)? Default: no -- the agent loop owns its own iteration. Re-evaluate per persona if a use case emerges.

---

## Triggers and Review Cadence

This document is reviewed when any of the following occur:
- A migration stage completes (update "current state" sections accordingly).
- A Tier 3 trigger condition fires (OpenRouter activation).
- A provider revokes access, raises pricing materially, or changes terms (record the event in the "Lessons" table).
- The executor model selection question is resolved (close the Open Question; record the choice).
- A new vendor SDK or framework reaches a maturity that warrants re-evaluating the "non-goals" list.
- A LiteLLM or MCP SDK breaking change affects pinned versions.

Routine review cadence: at the same point in time as `INTENT-recommendation-executor.md` reviews, since the two documents are tightly coupled.
