# Inference Provider Contract

**Version:** 7.0 -- June 2026
**Decision reference:** CD.28 (`docs/ROADMAP-PLATFORM.yaml` candidate_decisions) defines the tier model and retires Bedrock from the architecture. Decision 53 (`docs/DECISIONS_ARCHIVE.md`) governs the operative executor transport (Gemini CLI). Decision 49 governs the scheduled-agent provider until PLAN-resolve-scheduled-agent-provider lands.
**Applies to:** All executor and Lambda-executed agent code (`scripts/`, `src/data/handlers/`)

---

## Summary

This contract defines the authoritative provider tier model, model naming conventions, provider field schema, and auth requirements for all inference calls.

### CD.28 tier model (committed architecture)

| Tier | Provider | Transport | State |
|------|----------|-----------|-------|
| 1 (primary) | DeepSeek-direct | LiteLLM | Committed; lands with T4.2's `PLAN-llm-client-litellm-transport` |
| 2 (warm-fetched escape hatch) | Anthropic-direct | LiteLLM | Committed; credential validated at every harness cold start |
| 3 | OpenRouter | LiteLLM | Deferred |

LiteLLM is the only Layer-1 inference protocol surface under CD.28. Direct provider-SDK imports are forbidden in the executor and in `scripts/llm_client.py`.

### Operative state (until T4.2 lands)

- **`gemini-cli`** -- Executor pipeline (`scripts/llm_client._gemini_call`), Gemini 3 models via local CLI headless mode. See Decision 53.
- Lambda scheduled agents are DISABLED (May 2026; see AGENTS.md runbook). Their `schedule.yaml` entries still declare `provider: copilot-sdk` (T4.3-owned; not migrated by this contract). Per Decision 116 (supersedes Decision 49), routine/non-agentic agents migrate to LiteLLM Tier 1 (DeepSeek) and judgment/agentic agents migrate to `claude -p`; realization is owned by CD.28's PLAN-resolve-scheduled-agent-provider follow-on.

### Retired providers

- **`bedrock`** -- RETIRED per CD.28. `scripts/bedrock_client.py` and all dispatch branches were deleted by the T1.15 sweep (this contract's v7.0 revision). No rollback path in code; reintroduction requires a new decision.
- **`copilot-sdk`** -- RETIRED from the active provider set per Decision 116 (supersedes Decision 49). `scripts/copilot_sdk_client.py` and the handler dispatch branch are deleted; an agent declaring this provider raises `RetiredProviderError` and is recorded as a failed invocation (no silent misroute).
- **`gemini` (BYOK via Copilot SDK)** -- RETIRED alongside `copilot-sdk` per Decision 116. Same `RetiredProviderError` handling.

---

## Provider Defaults (contract = code)

These defaults are quoted from the code and MUST stay in sync with it.

**Executor path** (`scripts/llm_client.llm_call` -> `scripts/model_registry.resolve_provider`): the default provider is **`gemini`**.

```python
# scripts/model_registry.py
_VALID_PROVIDERS = frozenset(["gemini"])  # bedrock retired per CD.28
_DEFAULT_EXECUTOR_PROVIDER = "gemini"
```

`resolve_provider()` reads `LLM_PROVIDER` and falls back to `"gemini"` for any unrecognised value (including the retired `bedrock`). `llm_call` raises `LLMResponseError` if a non-gemini provider somehow resolves (defense-in-depth until T4.2's LiteLLM transport).

**Scheduled-agent path** (`src/data/handlers/scheduled_agent_handler.py`): the absent-field default is **`github-models`**.

```python
# src/data/handlers/scheduled_agent_handler.py
provider: str = agent.get("provider", "github-models")
```

All current `.github/agents/schedule.yaml` entries declare `provider: copilot-sdk` explicitly; the absent-field default exists for legacy/local use and MUST NOT be relied on for new entries.

---

## Provider Field Schema

Every agent entry in `.github/agents/schedule.yaml` MUST include a `provider` field:

```yaml
agents:
  - name: doc-freshness
    cron: "0 6 * * 1"
    model: claude-haiku-4.5
    provider: copilot-sdk
    prompt_path: .github/prompts/scheduled/doc-freshness.prompt.md
    description: ...
```

**Valid values:**

| Value | Client used | Where valid |
|-------|-------------|-------------|
| `copilot-sdk` | RETIRED -- raises `RetiredProviderError` | Not valid anywhere; Decision 116 (supersedes Decision 49). Existing `schedule.yaml` entries fail loudly until PLAN-resolve-scheduled-agent-provider migrates them |
| `gemini` | RETIRED -- raises `RetiredProviderError` | Not valid anywhere; retired alongside `copilot-sdk` per Decision 116 |
| `github-models` | `scripts/github_models_client.chat_completion()` | Local only -- MUST NOT be used in Lambda; the absent-field default |
| `litellm` | T4.2 transport (not yet built) | Future-state per CD.28; do not declare until PLAN-resolve-scheduled-agent-provider lands |

`provider: bedrock` is INVALID. The dispatch branch was removed; an agent declaring it falls through to the `github-models` default branch (PAT fetch + live GitHub Models call), which then fails loudly at the API layer on the unrecognized Bedrock-style model id.

---

## Model ID Format

### Gemini CLI Model IDs (operative -- executor pipeline, Decision 53)

Format: Google Gemini 3 model names passed to the CLI via `--model` flag (or omitted for Auto mode).

| Use case | Model ID | Notes |
|----------|----------|-------|
| Auto (default -- CLI picks) | `null` / omit `--model` | CLI selects pro or flash based on task complexity |
| High-complexity tasks | `gemini-3-pro-preview` | Strong reasoning |
| Fast/simple tasks | `gemini-3-flash-preview` | Low latency |

**Auth:** Google OAuth via browser flow (run `gemini` once locally).
**CLI:** Headless mode: prompt on stdin with `-p ""`, `--output-format stream-json`.
**Exit codes:** 0=success, 1=general error, 42=bad input, 53=turn limit exceeded (retryable)
**Version requirement:** Preview (0.40.0+) required for Gemini 3 models. Install: `npm install -g @google/gemini-cli@preview`
**Routing:** `config/agent/copilot/model_routing.yaml` -> `scripts/model_registry.py` -> `scripts/llm_client._gemini_call()`
**Cost:** Free tier (personal Google Pro plan). The gemini transport reports `cost_usd=0.0`.

### LiteLLM tier-model IDs (committed -- lands at T4.2)

| Tier | Models | Notes |
|------|--------|-------|
| 1 | `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` | Aliases remap to deepseek-v4-flash post-2026-07-24 per upstream deprecation; native context caching is hash-based and automatic |
| 2 | Anthropic-direct Claude models via LiteLLM | Funded by the Max x5 programmatic-pool credit; boot validation includes a usage-API pool check (CD.28 discipline point) |

### Copilot SDK Model IDs (legacy -- disabled scheduled agents)

Format: `{provider}-{family}-{version}` (e.g., `claude-haiku-4.5`, `claude-sonnet-4.6`). These differ from GitHub Models IDs (`gpt-5-mini`, `openai/gpt-4.1`) -- do not interchange. See Decision 49.

### GitHub Models IDs (local use only)

GitHub Models uses different naming: `gpt-5-mini`, `openai/gpt-4.1`, `claude-opus-4-5`. Not valid for any other provider.

---

## IAM Requirements

No inference-provider IAM grants are required: the operative executor transport (Gemini CLI) and the committed CD.28 tiers (DeepSeek-direct, Anthropic-direct via LiteLLM) authenticate with API keys (Secrets Manager / local credential files), not AWS IAM.

The former `BedrockInference` Lambda-execution-role statement (`bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`) is RETIRED: the live personal-account PlatformDev policy is permission-closed (no Bedrock grant; see `terraform/CLAUDE.md` reconciliation note), and the retired work-root grant text was removed by the T1.15 sweep.

Secrets in Secrets Manager consumed by the (disabled) scheduled-agent path: `agent-platform-github-pat` (OAuth `gho_` token, NOT a classic PAT) and the Gemini API key secret. See `src/data/handlers/CLAUDE.md` gotchas.

---

## Active Client Interface (`scripts/llm_client.py`)

```python
def llm_call(
    prompt: str,
    model: str | None = None,
    tools: bool = True,
    timeout: int = 300,
    purpose: str = "unknown",
    check: bool = True,
) -> LLMResult:
    """Execute an LLM inference call via the Gemini CLI transport.

    Returns LLMResult with keys:
      content: str       # model response text
      exit_code: int     # 0 on success
      session_id: str    # unique call ID (Gemini session id when available)
      tokens_in: int
      tokens_out: int
      cost_usd: float    # 0.0 on the gemini transport
      model: str         # model id or "gemini-auto"
    """
```

Compatibility note: `excluded_tools` and `system_prompt` are still accepted by `llm_call` for caller compatibility (`scripts/executor/plan.py`, `scripts/agent_development/run_skill.py`) but are ignored on the gemini transport; they are removed at T4.2's LiteLLM rewrite.

**Lambda packaging:** `llm_client.py`, `llm_utils.py`, `tool_runtime.py` are bundled per the `includes` lists in `src/lambdas/*/manifest.yaml` (mirrored by `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`). `bedrock_client.py` is deleted and MUST NOT reappear in any manifest.

---

## Routing Logic (`src/data/handlers/scheduled_agent_handler.py`)

```python
provider = agent.get("provider", "github-models")
if provider in ("copilot-sdk", "gemini"):
    # Retired per Decision 116 (supersedes Decision 49) -- raises RetiredProviderError,
    # caught locally and recorded as a failed invocation (no silent misroute).
    raise RetiredProviderError(...)
else:
    # github-models path (local/legacy; the absent-field default)
    output, has_error, err_msg = _invoke_github_models(prompt_text, model, pat)
```

There is no Bedrock branch (retired per CD.28).

---

## Plan Compliance Checklist

When any plan or rec touches inference call sites, verify:

- [ ] No `provider: bedrock` anywhere; no `scripts.bedrock_client` imports (`git grep -l -E "bedrock_client|_bedrock_call|_invoke_bedrock" -- scripts/ src/` returns nothing)
- [ ] New `schedule.yaml` entries are not added while scheduled agents are disabled; provider migration is owned by PLAN-resolve-scheduled-agent-provider
- [ ] Executor call sites go through `llm_call()` -- no direct provider-SDK imports (CD.28 discipline point)
- [ ] Stated provider defaults in this contract match `scripts/model_registry.py` and `scheduled_agent_handler.py` (Provider Defaults section)
- [ ] Lambda-packaged changes follow CD.16/Decision 79 per-Lambda build + deploy + smoke-test gating (dispatcher smoke deferred until T4.3)

---

## Migration Reference

| Old | New | Notes |
|-----|-----|-------|
| `copilot_call()` / `copilot_sdk_inference_sync()` (executor) | `llm_call()` | Single entry point |
| `_bedrock_call()` / `scripts.bedrock_client.converse()` | RETIRED (CD.28) | Gemini CLI today; LiteLLM tiers at T4.2 |
| `LLM_PROVIDER=bedrock` | falls back to `gemini` with a warning | `_VALID_PROVIDERS` no longer includes bedrock |
| `CopilotResult` / `.stdout` / `.premium_requests` | `LLMResult` / `.content` / `.cost_usd` | Dataclass mapping |
