# Plan

## Intent
Migrate all 6 scheduled agents from Copilot SDK native inference (consuming GitHub premium requests) to Gemini models via the SDK's BYOK mechanism, billing inference against a personal Google AI Studio API key ($10/month credit). This directly supports the North Star by preserving the autonomous agent fleet while reducing operational cost pressure from premium request limits.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/infra-gemini-byok

## Phase
Phase Platform (automation infrastructure) -- runs in parallel with domain phases.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/copilot_sdk_client.py | Modify | Add optional `provider_config: dict` parameter to both `copilot_sdk_inference()` and `copilot_sdk_inference_sync()`, pass through to `create_session(provider=...)` |
| src/data/handlers/scheduled_agent_handler.py | Modify | Add `gemini` provider branch that constructs `ProviderConfig(type="openai", base_url=GEMINI_ENDPOINT, api_key=...)` and calls `_invoke_copilot_sdk()` with provider config; read Gemini API key from Secrets Manager |
| .github/agents/schedule.yaml | Modify | Switch all 6 agents from `provider: copilot-sdk` to `provider: gemini` with Gemini model names |
| docs/contracts/inference-provider.md | Modify | Document `gemini` provider, model IDs, BYOK mechanism, and swap-back instructions |
| terraform/scheduled_agents.tf | Modify | Add Secrets Manager secret `agent-platform-gemini-api-key`, add `GEMINI_API_KEY_SECRET_ARN` Lambda env var for both dispatcher and findings-processor |
| scripts/run_scheduled_agent.py | Modify | Support `gemini` provider in local runner path (construct provider config, call `copilot_sdk_inference_sync()`) |
| scripts/build_lambda.py | No change | `copilot_sdk_client.py` already in `_LAMBDA_SCRIPTS`; SDK already packaged |
| tests/test_copilot_sdk_client.py | Modify | Add test for `provider_config` passthrough to `create_session()` |
| tests/test_scheduled_agent_handler.py | Modify | Add test for `gemini` provider routing (constructs correct ProviderConfig, calls copilot SDK) |

## Bundled Recommendations
- rec-383: Add per-invocation model telemetry record to copilot_call() -- partially addressed (model calls now route through a configurable provider, enabling future per-model tracking). NOT fully closed by this plan.

## Infrastructure Dependencies
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| `aws_secretsmanager_secret.gemini_api_key` | create | Yes -- Lambda reads API key from it | pre-merge | `aws secretsmanager get-secret-value --secret-id agent-platform-gemini-api-key --profile company-aws-profile --query SecretString --output text` returns the key |
| `aws_lambda_function.scheduled_agent_dispatcher` (env var update) | modify | Yes -- handler reads `GEMINI_API_KEY_SECRET_ARN` | pre-merge | `aws lambda get-function-configuration --function-name agent-platform-scheduled-agent-dispatcher --profile company-aws-profile --query "Environment.Variables.GEMINI_API_KEY_SECRET_ARN" --output text` returns the ARN |
| `aws_lambda_function.findings_processor` (env var update) | modify | No -- findings processor doesn't call inference | post-merge | N/A (cosmetic alignment) |

## Acceptance Criteria
- [ ] `copilot_sdk_inference()` accepts an optional `provider_config` dict and passes it to `create_session(provider=...)`
- [ ] `scheduled_agent_handler.py` routes `provider: gemini` agents through Copilot SDK with BYOK `ProviderConfig`
- [ ] All 6 agents in `schedule.yaml` use `provider: gemini` with Gemini model names
- [ ] `inference-provider.md` documents the `gemini` provider, model mapping, and swap-back plan
- [ ] Terraform creates `agent-platform-gemini-api-key` secret and adds `GEMINI_API_KEY_SECRET_ARN` env var to dispatcher Lambda
- [ ] `run_scheduled_agent.py` supports `--agent NAME` with `gemini` provider locally
- [ ] All existing tests pass; new tests cover provider_config passthrough and gemini routing
- [ ] `python -m scripts.validate` exits 0
- [ ] Each of the 6 agents produces non-empty output when triggered via Lambda with `force_agent`

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm `provider_config` param exists in client | `grep -c "provider_config" scripts/copilot_sdk_client.py` | Returns `4` or more (param in both functions + usage) | Parameter not added to function signature |
| 2 | [pre-deploy] | Confirm gemini provider routing in handler | `grep -c "provider == .gemini" src/data/handlers/scheduled_agent_handler.py` | Returns `1` (or more) | Missing gemini branch in handler |
| 3 | [pre-deploy] | Confirm all agents use gemini provider | `grep -c "provider: gemini" .github/agents/schedule.yaml` | Returns `6` | schedule.yaml not updated |
| 4 | [pre-deploy] | Run full test suite | `python -m pytest tests/ -x -q` | All tests pass | Fix failing tests |
| 5 | [pre-deploy] | Run validate | `python -m scripts.validate --scope all` | Exit 0 | Fix validation errors |
| 6 | [pre-deploy] | Terraform plan (human reviews) | `cd terraform && terraform plan -out=tfplan-gemini` | Plan shows: 1 secret created, 1 IAM policy updated, 2 Lambda env var updates. No destroys. | Unexpected changes in plan |
| 7 | [post-deploy] | **HUMAN GATE:** Apply Terraform | `cd terraform && terraform apply tfplan-gemini` | Apply completes successfully | Terraform apply errors |
| 8 | [post-deploy] | **HUMAN GATE:** Store Gemini API key in Secrets Manager | `aws secretsmanager put-secret-value --secret-id agent-platform-gemini-api-key --secret-string "YOUR_KEY" --profile company-aws-profile` | Secret stored | Secrets Manager permission error |
| 9 | [post-deploy] | Build and deploy Lambda | `python -m scripts.build_lambda --deploy` | Lambda code updated for dispatcher and findings-processor | Build or deploy failure |
| 10 | [post-deploy] | Trigger doc-freshness agent | `python -m scripts.run_scheduled_agent --trigger-lambda doc-freshness` | Lambda returns `agents_run: 1, agents_failed: 0` with non-empty findings | Error in Lambda response or `agents_failed: 1` |
| 11 | [post-deploy] | Trigger orphan-code agent | `python -m scripts.run_scheduled_agent --trigger-lambda orphan-code` | Lambda returns `agents_run: 1, agents_failed: 0` | Agent failure |
| 12 | [post-deploy] | Trigger transcript-review agent | `python -m scripts.run_scheduled_agent --trigger-lambda transcript-review` | Lambda returns `agents_run: 1, agents_failed: 0` | Agent failure |
| 13 | [post-deploy] | Trigger code-smell agent | `python -m scripts.run_scheduled_agent --trigger-lambda code-smell` | Lambda returns `agents_run: 1, agents_failed: 0` | Agent failure |
| 14 | [post-deploy] | Trigger prompt-quality agent | `python -m scripts.run_scheduled_agent --trigger-lambda prompt-quality` | Lambda returns `agents_run: 1, agents_failed: 0` | Agent failure |
| 15 | [post-deploy] | Trigger rec-curator agent | `python -m scripts.run_scheduled_agent --trigger-lambda rec-curator` | Lambda returns `agents_run: 1, agents_failed: 0` with structured JSON findings | Agent failure or empty output |
| 16 | [post-deploy] | Verify findings landed in S3 | `aws s3 ls s3://bblake-platform-agent-logs/agents/ --recursive --profile company-aws-profile \| tail -6` | At least 6 recent finding files (one per triggered agent) | S3 write failed |

## Constraints
- Gemini API key must NOT be committed to source. Stored in Secrets Manager only.
- `copilot-sdk` provider path must remain functional (fallback if Gemini has issues). Do not remove it.
- `bedrock` provider path remains dormant (Decision 49). Do not modify.
- Lambda zip size must stay under 262 MB. This plan adds zero new dependencies.
- Copilot SDK still needs the GitHub PAT for CLI startup auth even when BYOK routes inference to Gemini. Both secrets required in Lambda.
- Google AI Studio OpenAI-compatible endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/`
- Shell commands must be Windows Git Bash compatible (per copilot-instructions.md).

## Context
- **Decision 49:** Copilot SDK replaced Bedrock as Lambda inference provider. This plan adds Gemini BYOK as a third routing option.
- **SDK `ProviderConfig`:** Supports `type: "openai" | "azure" | "anthropic"`. Gemini uses `type: "openai"` with custom `base_url` pointing to Google's OpenAI-compatible endpoint.
- **Swap-back plan:** When GitHub Copilot opens new signups, revert `schedule.yaml` to `provider: copilot-sdk` and model names to `claude-haiku-4.5` / `claude-sonnet-4.6`. Zero code changes needed.
- **Model naming for Gemini via OpenAI-compatible endpoint:** Use Google's model names: `gemini-2.0-flash`, `gemini-2.5-pro`. These are passed as the `model` param in `create_session()`.
- **$10/month credit:** Gemini Pro subscription includes cloud credits. Paid tier RPM is significantly higher than free tier.
- **Known gotcha (copilot-instructions.md):** Copilot SDK auth requires OAuth token (`gho_` prefix from `gh auth token`), NOT a classic PAT (`ghp_`). The GitHub PAT remains needed for SDK CLI startup even with BYOK. The `GEMINI_API_KEY_SECRET_ARN` is a separate secret.
- **findings-processor Lambda:** Gets the env var for consistency but does not currently call inference. If it ever needs to, the plumbing is ready.
- **Gemini endpoint stability:** The OpenAI-compatible endpoint (`/v1beta/openai/`) is a beta API that may change without notice. The swap-back plan (revert to `copilot-sdk`) mitigates this. Monitor for deprecation notices from Google.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] BYOK validation gate passed (Step 0): `copilot_sdk_inference_sync()` with Gemini provider config returned non-empty content

## Ordered Execution Steps

0. **BYOK Validation Gate (manual, pre-implementation):** Before writing any code, manually run a one-shot BYOK test to confirm the SDK routes inference through Google's OpenAI-compatible endpoint. Set `GEMINI_API_KEY` env var locally, then call `copilot_sdk_inference_sync(prompt="Say hello", model="gemini-2.0-flash", github_token=<gh auth token output>, provider_config={"type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "api_key": <GEMINI_API_KEY>})`. Expected: non-empty `content` field, `error: False`. If this fails, STOP -- the BYOK mechanism is not viable and the plan needs redesign.

1. **Modify `scripts/copilot_sdk_client.py`:** Add `provider_config: dict[str, Any] | None = None` parameter to both `copilot_sdk_inference()` and `copilot_sdk_inference_sync()`. In `copilot_sdk_inference()`, if `provider_config` is not None, pass it as `provider=provider_config` to `client.create_session()`. The `ProviderConfig` TypedDict expects keys `type`, `base_url`, `api_key`. The sync wrapper passes the param through unchanged. Do NOT import `ProviderConfig` -- just pass the dict directly (TypedDict is structural).

2. **Modify `src/data/handlers/scheduled_agent_handler.py`:**
   - Add a `_get_gemini_api_key()` function mirroring `_get_github_pat()` but reading from `GEMINI_API_KEY_SECRET_ARN` env var (with `GEMINI_API_KEY` env var as local override).
   - Add an `_invoke_gemini()` function that:
     - Calls `_get_gemini_api_key()` for the API key
     - Constructs `provider_config = {"type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "api_key": gemini_key}`
     - Calls `copilot_sdk_inference_sync(prompt_text, model, github_token=pat, provider_config=provider_config)`
     - Returns `(output, error, message)` tuple like other invoke functions
   - In `handler()`, add `elif provider == "gemini":` branch that:
     - Resolves both PAT (for SDK CLI auth) and Gemini API key
     - Calls `_invoke_gemini(prompt_text, model, pat)`
   - Ensure `rec-curator` context preloading also triggers for `gemini` provider: update the condition to `if name == "rec-curator" and provider in ("bedrock", "copilot-sdk", "gemini")`.

3. **Modify `.github/agents/schedule.yaml`:** Change all 6 agents:
   - 5 lightweight agents: `provider: gemini`, `model: gemini-2.0-flash`
   - rec-curator: `provider: gemini`, `model: gemini-2.5-pro`
   - Keep all other fields (cron, prompt_path, description) unchanged.

4. **Modify `scripts/run_scheduled_agent.py`:** In `run_agent()`, after the `copilot_call()` invocation, the local runner currently uses the Copilot CLI. The local runner does not use `copilot_sdk_inference_sync()` -- it uses `copilot_call()` (subprocess wrapper). For Gemini BYOK to work locally, add an alternate code path: if the agent's `provider` field is `gemini`, call `copilot_sdk_inference_sync()` with the BYOK provider config instead of `copilot_call()`. Read the Gemini API key from `GEMINI_API_KEY` env var. Read the GitHub PAT from `gh auth token` subprocess or `GITHUB_PAT` env var.

5. **Modify `terraform/scheduled_agents.tf`:**
   - Add `aws_secretsmanager_secret.gemini_api_key` resource (name: `agent-platform-gemini-api-key`, description: "Gemini API key for scheduled agent BYOK inference").
   - Add `aws_secretsmanager_secret_version.gemini_api_key_placeholder` with `"PLACEHOLDER_SET_MANUALLY"` and `ignore_changes = [secret_string]`.
   - Add `GEMINI_API_KEY_SECRET_ARN = aws_secretsmanager_secret.gemini_api_key.arn` to the dispatcher Lambda environment variables.
   - Add same env var to findings-processor Lambda environment variables (consistency).
   - Add `secretsmanager:GetSecretValue` permission for the new secret ARN to the IAM policy (update the `SecretsManagerGithubPat` statement Resource array to include both secret ARNs, or add a separate statement).

6. **Modify `docs/contracts/inference-provider.md`:**
   - Add `gemini` to the Provider Field Schema valid values table: `gemini | copilot_sdk_inference_sync() with BYOK ProviderConfig | Lambda and local`
   - Add "Gemini BYOK Model IDs" section with model mapping table: `gemini-2.0-flash` (lightweight), `gemini-2.5-pro` (strong reasoning).
   - Add "BYOK Mechanism" section explaining: SDK `ProviderConfig(type="openai", base_url=GEMINI_ENDPOINT, api_key=...)`, Google AI Studio billing, swap-back instructions.
   - Update default provider note if needed.

7. **Modify `tests/test_copilot_sdk_client.py`:** Add a test `test_provider_config_passed_to_create_session()` that:
   - Mocks the SDK modules as existing tests do
   - Calls `copilot_sdk_inference_sync()` with a `provider_config` dict containing `type`, `base_url`, and `api_key` fields (use test fixture values)
   - Asserts `mock_client.create_session` was called with the same `provider_config` passed through as `provider=` kwarg

8. **Modify `tests/test_scheduled_agent_handler.py`:** Add a test for the `gemini` provider routing:
   - Mock `_get_gemini_api_key()` to return a test key
   - Mock `_get_github_pat()` to return a test PAT
   - Mock `copilot_sdk_inference_sync` to return success
   - Assert the handler constructs the correct `provider_config` dict and passes it through

9. Run `python -m pytest tests/ -x -q` -- all tests must pass.

10. Run `python -m scripts.validate --scope all` -- must exit 0.

11. **Execute Verification Plan** -- run each step from the table above. Pre-deploy steps (1-6) are agent-executable. Steps 7-8 are human-gated (terraform apply + secret storage). Steps 9-16 are post-deploy. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

12. Report: what was implemented, verification results (actual outcomes from each agent trigger), bugs found and fixed.
