# Inference Provider Contract

**Version:** 6.0 -- April 2026
**Decision reference:** Decision 54 (`docs/DECISIONS.md`) supersedes Decision 52 for Lambda agents. Decision 53 (Gemini CLI) applies to executor path.
**Applies to:** All executor and Lambda-executed agent code (`scripts/`, `src/data/handlers/`)

---

## Summary

This contract defines the authoritative model naming conventions, provider field schema, and auth requirements for all inference calls.

**Active providers as of April 2026:**
- **`copilot-sdk`** -- Lambda scheduled agents (`scripts/copilot_sdk_client.copilot_sdk_inference_sync()`), `claude-haiku-4.5` / `claude-sonnet-4.6` models. See Decision 54.
- **`gemini-cli`** -- Executor pipeline (`scripts/llm_client._gemini_call`), Gemini 3 models via local CLI. See Decision 53.
- **`bedrock`** -- Dormant. Personal account quotas throttled to 0; company account revoked. Code retained for rollback.

Copilot CLI and Gemini BYOK are deprecated. See Decision 52.

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
| `copilot-sdk` | `scripts/copilot_sdk_client.copilot_sdk_inference_sync()` | Active for Lambda agents -- `claude-haiku-4.5` / `claude-sonnet-4.6` via GitHub Copilot SDK. |
| `gemini-cli` | `scripts/llm_client._gemini_call()` | Active for executor (local, Decision 53) -- Gemini 3 via Gemini CLI headless mode |
| `bedrock` | `scripts/bedrock_client.converse()` | Dormant. Personal account throttled; company account revoked. Retained for rollback. |
| `gemini` | `copilot_sdk_inference_sync()` with BYOK `ProviderConfig` | Deprecated (Decision 52) |
| `github-models` | `scripts/github_models_client.chat_completion()` | Local only -- MUST NOT be used in Lambda |

**Default (if field absent):** `copilot-sdk` -- all new entries should use explicit `provider: copilot-sdk`.

---

## Model ID Format

### Gemini CLI Model IDs (active -- executor pipeline, Decision 53)

Format: Google Gemini 3 model names passed to the CLI via `--model` flag (or omitted for Auto mode).

**Approved models (April 2026):**

| Use case | Model ID | Notes |
|----------|----------|-------|
| Auto (default -- CLI picks) | `null` / omit `--model` | CLI selects pro or flash based on task complexity |
| High-complexity tasks | `gemini-3-pro-preview` | Strong reasoning; equivalent to Opus tier |
| Fast/simple tasks | `gemini-3-flash-preview` | Low latency; equivalent to Flash/Haiku tier |

**Auth:** Google OAuth via browser flow (run `gemini` once locally). Session token export to Secrets Manager for Lambda (future -- Lambda migration deferred to separate session).

**CLI:** Headless mode: `gemini -p "prompt" --output-format json`
**Response schema:** `{"response": string, "stats": {"tokenUsage": {"inputTokens": N, "outputTokens": N}, "latency": N}, "error"?: object}`
**Exit codes:** 0=success, 1=general error, 42=bad input, 53=turn limit exceeded (retryable)

**Version requirement:** Preview (0.40.0+) required for Gemini 3 models. Stable (0.39.x) runs Gemini 1.5 Pro.
Install: `npm install -g @google/gemini-cli@preview`

**Routing:** `config/agent/copilot/model_routing.yaml` → `scripts/model_registry.py` → `scripts/llm_client._gemini_call()`
**Cost:** Free tier (personal Google Pro plan, 1,500 req/day). `_compute_cost()` returns 0.0 for Gemini models.

### Bedrock Model IDs (dormant for executor, active for Lambda agents)

Format: Bedrock model identifiers passed to `converse()` API.

**Approved models (April 2026):**

| Use case | Model ID | Notes |
|----------|----------|-------|
| Default (all agents/executor) | `deepseek.v3.2` | 128K context, $0.90/$2.61 per 1M tokens |

**Auth:** AWS profile `personal-bedrock-profile` locally; cross-account IAM credentials via Secrets Manager for Lambda.

**DeepSeek quirks:**
- Chain-of-thought: responses include `<think>...</think>` blocks, stripped by `_strip_think_blocks()` in `bedrock_client.py`
- Chinese characters may appear in reasoning traces; stripped for Windows compatibility
- Tool use supported via `converse()` with `toolConfig`

### Gemini Model IDs (deprecated -- BYOK via Copilot SDK)

Format: Google's model names passed directly to the Gemini API.

**Approved models (April 2026):**

| Use case | Model ID | Notes |
|----------|----------|-------|
| Lightweight agents | `gemini-2.5-flash` | Fast, low cost; replaces `claude-haiku-4.5` |
| Strong reasoning (rec-curator) | `gemini-2.5-pro` | High-quality output; replaces `claude-sonnet-4.6` |

**BYOK mechanism:** Copilot SDK `create_session(provider={"type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "api_key": gemini_key})`. The GitHub PAT is still required for Copilot CLI startup auth even when inference routes to Gemini. Both secrets must be present in Lambda.

**Swap-back plan (EXECUTED April 2026):** Swap-back to `copilot-sdk` was completed as part of Decision 54. Lambda agents revert to `claude-haiku-4.5` / `claude-sonnet-4.6`. See `.github/agents/schedule.yaml`.

### Copilot SDK Model IDs (deprecated)

Format: `{provider}-{family}-{version}` (e.g., `claude-haiku-4.5`, `claude-sonnet-4`)

**Approved models (April 2026, confirmed via `client.list_models()`):**

| Use case | Model ID | Multiplier | Notes |
|----------|----------|-----------|-------|
| Lightweight agents | `claude-haiku-4.5` | 0.33x | Fast, low cost |
| Strong reasoning (rec-curator) | `claude-sonnet-4.6` | 1x | Matches previous Bedrock capability |

**Validation:** `python -c "from copilot import CopilotClient; ..." ` or reference https://docs.github.com/en/copilot/using-github-copilot/ai-models/supported-ai-models-in-copilot

### Bedrock Anthropic model IDs (deprecated -- replaced by DeepSeek V3.2)

Format: `{provider}.{model-family}-{date}-{revision}:{version}`

**Approved models (eu-west-2, April 2026):**

| Use case | Model ID | Notes |
|----------|----------|-------|
| Lightweight agents (replaces `gpt-5-mini`) | `anthropic.claude-3-5-haiku-20241022-v1:0` | Fast, low cost |
| Strong reasoning (replaces `openai/gpt-4.1`) | `eu.anthropic.claude-opus-4-6-v1` | rec-curator (EU cross-region inference profile) |

**Validation command:**
```bash
aws bedrock list-foundation-models --by-provider anthropic --profile company-aws-profile --region eu-west-2 --query "modelSummaries[*].modelId" --output text
```

### GitHub Models IDs (local use only)

GitHub Models uses different naming: `gpt-5-mini`, `openai/gpt-4.1`, `claude-opus-4-5`.
These IDs are NOT valid Bedrock model IDs and will fail with `ResourceNotFoundException` if passed to the Bedrock client.

**Common mistake:** Using the Copilot Chat model name `claude-opus-4.6` — this is invalid on both GitHub Models API and Bedrock. On GitHub Models the correct name is `claude-opus-4-5`. On Bedrock it is `anthropic.claude-opus-4-20241022-v1:0`.

---

## IAM Requirements

Lambda execution role MUST include:

```json
{
  "Sid": "BedrockInference",
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": "arn:aws:bedrock:eu-west-2::foundation-model/*"
}
```

For cross-account access (Lambda in sandbox REDACTED-ACCOUNT-ID calling Bedrock in personal REDACTED-PERSONAL-ACCOUNT), the Lambda uses explicit credentials stored in Secrets Manager.

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
    """Execute an LLM inference call via Bedrock.

    Returns LLMResult with keys:
      content: str       # model response text (think blocks stripped)
      exit_code: int     # 0 on success
      session_id: str    # unique call ID
      tokens_in: int
      tokens_out: int
      cost_usd: float    # computed from Bedrock pricing
      model: str         # resolved Bedrock model ID
    """
```

**Lambda packaging:** `llm_client.py`, `llm_utils.py`, `tool_runtime.py`, `bedrock_client.py` are included in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`.

---

## Routing Logic (`src/data/handlers/scheduled_agent_handler.py`)

```python
provider = agent.get("provider", "bedrock")
if provider == "bedrock":
    # Active -- DeepSeek V3.2 via Bedrock Converse API in eu-west-2 (Decision 52)
    credentials = _get_bedrock_credentials()
    from scripts.bedrock_client import converse
    response = converse(
        prompt=prompt_text, model_id=model, region="eu-west-2",
        credentials=credentials,
    )
    output = response.get("content", "")
elif provider == "copilot-sdk":
    # Dormant -- GitHub Copilot SDK native inference (retained for rollback)
    from scripts.copilot_sdk_client import copilot_sdk_inference_sync
    response = copilot_sdk_inference_sync(prompt=prompt_text, model=model, github_token=pat)
    output = response.get("content", "")
else:
    # github-models path (local/legacy)
    from scripts.github_models_client import chat_completion
    response = chat_completion(prompt=prompt_text, model=model, api_key=pat)
    output = response["choices"][0]["message"]["content"]
```

---

## Plan Compliance Checklist

When any plan or rec touches Lambda agent inference, verify:

- [ ] `provider: bedrock` on all new `schedule.yaml` entries
- [ ] Bedrock entries use model ID: `deepseek.v3.2`
- [ ] `llm_client.py`, `llm_utils.py`, `tool_runtime.py`, `bedrock_client.py` in `_LAMBDA_SCRIPTS` in `build_lambda.py`
- [ ] No Copilot CLI or Copilot SDK calls in new Lambda code paths
- [ ] Cross-account Bedrock credentials available in Secrets Manager for Lambda
- [ ] Post-deploy verification planned: use `--smoke-test NAME` if available

---

## Migration Reference

| Old (Copilot CLI/SDK/Gemini) | New (Bedrock) | Notes |
|-----------------------------|--------------|-------|
| `copilot_call()` / `copilot_sdk_inference_sync()` | `llm_call()` | Single entry point |
| `CopilotResult` | `LLMResult` | Dataclass |
| `CopilotResponseError` | `LLMResponseError` | Exception |
| `claude-haiku-4.5` / `gemini-2.5-flash` | `deepseek.v3.2` | Default model |
| `.stdout` on result | `.content` on LLMResult | Response text |
| `.premium_requests` | `.cost_usd` | Cost tracking |
| `.tokens_used` | `.tokens_in + .tokens_out` | Token tracking |
