# Plan

## Intent

Restore the autonomous scheduled-agent pipeline by replacing the now-inaccessible AWS Bedrock inference provider with the GitHub Copilot SDK, giving Lambda agents access to Claude models (Haiku 4.5, Sonnet 4) via zip-packaged deployment. This directly serves the North Star by ensuring the self-improving feedback loop -- scheduled code analysis, recommendation curation, friction detection -- continues operating without interruption.

## Plan Type

IMPLEMENTATION

## Verification Tier

V3 (Integration) -- Lambda-packaged files modified, requires deploy + invoke + verify output.

## Branch

agent/platform-copilot-sdk-migration

## Phase

Phase Platform (automation infrastructure)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| scripts/copilot_sdk_client.py | Create | New inference client wrapping Copilot SDK for Lambda agents |
| src/data/handlers/scheduled_agent_handler.py | Modify | Add `copilot-sdk` provider routing path |
| .github/agents/schedule.yaml | Modify | Update all 6 agents: `provider: copilot-sdk`, Copilot SDK model IDs |
| scripts/build_lambda.py | Modify | Add `copilot_sdk_client.py` to `_LAMBDA_SCRIPTS`; add SDK pip install step in `build_app_package()` |
| docs/contracts/inference-provider.md | Modify | Add `copilot-sdk` provider, SDK model ID format, update compliance checklist |
| docs/DECISIONS.md | Modify | Supersede Decision 47 with Decision 49 (Copilot SDK replaces Bedrock) |
| .github/copilot-instructions.md | Modify | Update Known Gotcha for inference provider model IDs; add copilot_sdk_client.py to File Router |
| terraform/scheduled_agents.tf | Modify | Remove BedrockInference IAM statement (no longer needed; Bedrock access revoked) |
| tests/test_copilot_sdk_client.py | Create | Unit tests for the new client |
| tests/test_scheduled_agent_handler.py | Modify | Add tests for `copilot-sdk` provider path |
| tests/test_build_lambda.py | Modify | Add test for SDK pip install step |

## Bundled Recommendations

None -- this is a new plan driven by external event (Bedrock access revocation).

## Infrastructure Dependencies

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| aws_iam_policy.scheduled_agent_lambda (remove BedrockInference statement) | modify | No -- removing unused permissions | pre-merge | N/A -- removal only |

### Rollback Notes

- BedrockInference IAM removal: re-add the statement block if Bedrock access is restored. No data migration.
- Copilot SDK rollback: revert `schedule.yaml` to `provider: bedrock`, revert handler routing, rebuild and deploy Lambda.

## Acceptance Criteria

- [ ] `scripts/copilot_sdk_client.py` exists with `copilot_sdk_inference()` function that returns flat dict matching existing response shape
- [ ] `src/data/handlers/scheduled_agent_handler.py` contains `_invoke_copilot_sdk()` function and routes `provider: copilot-sdk` agents to it
- [ ] `.github/agents/schedule.yaml` has all 6 agents with `provider: copilot-sdk` and SDK model IDs (`claude-haiku-4.5` / `claude-sonnet-4.6`)
- [ ] `scripts/build_lambda.py` `_LAMBDA_SCRIPTS` includes `copilot_sdk_client.py` AND `bedrock_client.py` (dormant, retained)
- [ ] `scripts/build_lambda.py` `build_app_package()` pip-installs `github-copilot-sdk` with `--platform manylinux_2_28_x86_64`
- [ ] Built zip contains `copilot/bin/copilot` with executable permissions (`0o755`)
- [ ] `docs/contracts/inference-provider.md` documents `copilot-sdk` provider, SDK model IDs, and auth requirements
- [ ] `docs/DECISIONS.md` contains Decision 49 superseding Decision 47
- [ ] `terraform/scheduled_agents.tf` BedrockInference IAM statement removed
- [ ] `python -m pytest tests/test_copilot_sdk_client.py tests/test_scheduled_agent_handler.py tests/test_build_lambda.py -x -q` passes
- [ ] `python -m scripts.validate` exits 0
- [ ] `python -m scripts.build_lambda` builds successfully (zip created)
- [ ] `python -m scripts.build_lambda --deploy` uploads to S3 and updates Lambda function code
- [ ] Lambda smoke test: `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{"force_agent":"doc-freshness"}' --profile company-aws-profile --region eu-west-2 --cli-binary-format raw-in-base64-out /tmp/sdk-test-out.json` shows `agents_run >= 1` and `agents_failed == 0`

## Constraints

- No Docker on company VM -- Lambdas use zip packaging via S3
- Bedrock access is revoked -- cannot use `bedrock_client.py` for inference
- Copilot SDK v0.2.2 (Public Preview) -- API may change; pin version in build step
- Lambda zip 250 MB unzipped limit -- SDK is ~69 MB, existing app ~20 MB, leaves ~160 MB headroom
- SDK binary is platform-specific -- must use `manylinux_2_28_x86_64` wheel (not `manylinux2014`)
- SDK is async -- Lambda handler must wrap in `asyncio.run()`
- SDK spawns a CLI subprocess -- Lambda must have sufficient memory (512 MB current, may need 1024 MB)
- `bedrock_client.py` remains in `_LAMBDA_SCRIPTS` as dormant code (zero runtime cost; available if Bedrock access is restored)
- The `copilot/bin/copilot` Linux binary in the SDK is ~58 MB -- it must be marked executable in the Lambda zip
- Auth uses existing Secrets Manager GitHub PAT (`GITHUB_PAT_SECRET_ARN`) -- no new secrets needed

## Context

- **Decision 47** (docs/DECISIONS.md): Bedrock as single Lambda inference provider -- SUPERSEDED by this plan. Bedrock access revoked by IT per AI Steering Group compliance (April 2026).
- **Decision 40** (docs/DECISIONS.md): Copilot SDK + Bedrock BYOK for executor -- deferred, separate concern. This plan addresses Lambda agents only.
- **Decision 48** (docs/DECISIONS.md): Verification Tier V3 -- this plan is V3 (deploy + invoke required).
- **docs/contracts/inference-provider.md**: Must be updated to add `copilot-sdk` provider.
- **SDK research findings** (this session):
  - Package: `github-copilot-sdk==0.2.2` (`pip install github-copilot-sdk`)
  - Linux wheel: `py3-none-manylinux_2_28_x86_64` (59.4 MB on PyPI)
  - Binary: bundled at `copilot/bin/copilot`, auto-resolved by `_get_bundled_cli_path()`
  - Auth: `SubprocessConfig(github_token="...")` -- token passed to CLI via env var
  - Session API: `client.create_session(model="claude-haiku-4.5", tools=[])` then `session.send_and_wait(prompt, timeout=300)`
  - Response: `response.data.content` contains model output text
  - Available models (confirmed via `client.list_models()`): claude-haiku-4.5, claude-sonnet-4, claude-sonnet-4.5, claude-sonnet-4.6, claude-opus-4.5, claude-opus-4.6, gpt-4.1, gpt-5-mini, gpt-5.2, gpt-5.2-codex, gpt-5.3-codex, gpt-5.4, gpt-5.4-mini
  - Live tested: `claude-sonnet-4` and `claude-haiku-4.5` both returned correct responses with `tools=[]`
- **Lambda runtime**: Amazon Linux 2023 (glibc 2.34) -- compatible with `manylinux_2_28` wheels
- **Existing Lambda memory**: 512 MB -- SDK spawns a subprocess; may need increase to 1024 MB if OOM observed during smoke test

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO session active (`aws sts get-caller-identity --profile company-aws-profile` returns account REDACTED-ACCOUNT-ID)

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Create `scripts/copilot_sdk_client.py` -- new inference client

**File:** scripts/copilot_sdk_client.py (Create)

**Pre-condition:** File does not exist.

**Changes:** Create a new module that wraps the GitHub Copilot SDK for Lambda agent inference. The module must:

1. Import `copilot` at function scope (not module level) with `try/except ImportError` using a sentinel fallback, matching the pattern in `bedrock_client.py`.

2. Provide a single public function:
   ```python
   async def copilot_sdk_inference(
       prompt: str,
       model: str,
       github_token: str,
       max_tokens: int = 4096,
       timeout: float = 300.0,
   ) -> dict[str, Any]:
   ```

3. The function must:
   - Create a `SubprocessConfig(github_token=github_token)` and `CopilotClient(config)`
   - Call `await client.start()`
   - Create a session with `model=model`, `tools=[]` (disables agent tool use)
   - Use `PermissionHandler.approve_all` for permissions (required by API)
   - Send the prompt via `session.send_and_wait(prompt, timeout=timeout)`
   - Extract response text from `response.data.content`
   - Clean up: `await session.disconnect()`, `await client.stop()`
   - Return a flat dict matching the existing response shape:
     ```python
     {"content": str, "error": False, "message": ""}
     ```
   - On any exception, return `{"content": "", "error": True, "message": str(exc)}`

4. Provide a sync wrapper:
   ```python
   def copilot_sdk_inference_sync(
       prompt: str,
       model: str,
       github_token: str,
       max_tokens: int = 4096,
       timeout: float = 300.0,
   ) -> dict[str, Any]:
   ```
   This calls `asyncio.run(copilot_sdk_inference(...))` and is the entry point for the Lambda handler (which is synchronous).

5. Module docstring must cite the Copilot SDK docs (https://github.com/github/copilot-sdk) and explain WHY SDK is used (Bedrock access revoked; SDK provides Claude models via Copilot infrastructure). Reference Decision 49.

**Post-condition:** File exists with `copilot_sdk_inference_sync()` function.

### Step 2: Create `tests/test_copilot_sdk_client.py` -- unit tests

**File:** tests/test_copilot_sdk_client.py (Create)

**Pre-condition:** File does not exist.

**Changes:** Create unit tests covering:

1. **Happy path:** Mock the CopilotClient, session, and response objects. Verify `copilot_sdk_inference_sync()` returns `{"content": "test output", "error": False, "message": ""}`.
2. **SDK import failure:** Verify the module loads when `copilot` is not installed (ImportError sentinel works).
3. **API error:** Mock the session to raise an exception. Verify error dict is returned: `{"content": "", "error": True, "message": "..."}`.
4. **Timeout:** Mock `send_and_wait` to raise `TimeoutError`. Verify error dict is returned.
5. **Client lifecycle:** Verify `client.start()`, `session.disconnect()`, and `client.stop()` are called in sequence.
6. **tools=[] enforcement:** Verify `create_session` is called with `tools=[]`.

All SDK imports must be mocked -- do not depend on the actual SDK being installed at test time.

**Post-condition:** `python -m pytest tests/test_copilot_sdk_client.py -x -q` passes.

### Step 3: Modify `src/data/handlers/scheduled_agent_handler.py` -- add copilot-sdk provider

**File:** src/data/handlers/scheduled_agent_handler.py (Modify)

**Pre-condition:** File contains `_invoke_bedrock()` and `_invoke_github_models()` functions. Handler routes by `provider` field.

**Changes:**

1. Add a new function `_invoke_copilot_sdk()`:
   ```python
   def _invoke_copilot_sdk(
       prompt_text: str, model: str, pat: str, max_tokens: int = 4096
   ) -> tuple[str, bool, str]:
       """Invoke Copilot SDK. Returns (output, error, message)."""
       from scripts.copilot_sdk_client import copilot_sdk_inference_sync

       response = copilot_sdk_inference_sync(
           prompt=prompt_text,
           model=model,
           github_token=pat,
           max_tokens=max_tokens,
       )
       if response.get("error"):
           return "", True, response.get("message", "")
       return response.get("content", ""), False, ""
   ```

2. In the `handler()` function, add a new routing branch in the provider dispatch block (within the `for agent in due_agents:` loop), BEFORE the existing `else` (github-models) branch:
   ```python
   elif provider == "copilot-sdk":
       if not pat_checked:
           pat = _get_github_pat()
           pat_checked = True
       if not pat:
           logger.error("Skipping agent '%s': GitHub PAT not available", name)
           agents_failed += 1
           continue
       max_tokens = 8192 if name == "rec-curator" else 4096
       output, has_error, err_msg = _invoke_copilot_sdk(
           prompt_text, model, pat, max_tokens=max_tokens
       )
   ```

3. Update the rec-curator preload conditional to also trigger for `copilot-sdk`:
   Change `if name == "rec-curator" and provider == "bedrock":` to
   `if name == "rec-curator" and provider in ("bedrock", "copilot-sdk"):`

4. Update the module docstring to mention Copilot SDK as a provider option.

**Post-condition:** Handler routes `copilot-sdk` agents to `_invoke_copilot_sdk()`.

### Step 4: Modify `tests/test_scheduled_agent_handler.py` -- add copilot-sdk tests

**File:** tests/test_scheduled_agent_handler.py (Modify)

**Pre-condition:** File contains tests for `_invoke_bedrock` and `_invoke_github_models`.

**Changes:** Add test class `TestInvokeCopilotSdk` with:

1. **Success path:** Mock `copilot_sdk_inference_sync` to return success dict. Verify `_invoke_copilot_sdk()` returns `(content, False, "")`.
2. **Error path:** Mock to return error dict. Verify `_invoke_copilot_sdk()` returns `("", True, error_message)`.
3. **Handler routing:** Mock manifest with a `provider: copilot-sdk` agent. Verify handler calls `_invoke_copilot_sdk` (not `_invoke_bedrock` or `_invoke_github_models`).
4. **rec-curator preload:** Verify `_preload_rec_curator_context()` is called for `copilot-sdk` provider when agent name is `rec-curator`.

**Post-condition:** `python -m pytest tests/test_scheduled_agent_handler.py -x -q` passes.

### Step 5: Modify `scripts/build_lambda.py` -- add SDK to Lambda package

**File:** scripts/build_lambda.py (Modify)

**Pre-condition:** `_LAMBDA_SCRIPTS` lists scripts to copy. `build_app_package()` creates `data-pipeline.zip`.

**Changes:**

1. Add `"copilot_sdk_client.py"` to `_LAMBDA_SCRIPTS` (after `"bedrock_client.py"`).

2. Add a new constant for the SDK package:
   ```python
   _COPILOT_SDK_PACKAGE = "github-copilot-sdk==0.2.2"
   ```

3. In `build_app_package()`, after copying `_LAMBDA_SCRIPTS`, add a pip install step for the Copilot SDK:
   ```python
   # Install Copilot SDK into the app package (includes bundled CLI binary).
   # Uses manylinux_2_28 (not manylinux2014) because the SDK binary requires glibc 2.28+.
   # Lambda uses Amazon Linux 2023 (glibc 2.34), which is compatible.
   print("  Installing Copilot SDK into app package...")
   sdk_result = subprocess.run(
       [
           sys.executable, "-m", "pip", "install",
           _COPILOT_SDK_PACKAGE,
           "--target", str(app_dir),
           "--platform", "manylinux_2_28_x86_64",
           "--implementation", "cp",
           "--python-version", "3.12",
           "--only-binary=:all:",
           "--quiet",
       ],
       check=False,
   )
   if sdk_result.returncode != 0:
       print(f"ERROR: Copilot SDK installation failed (exit {sdk_result.returncode})")
       sys.exit(1)
   ```

4. After the SDK pip install, ensure the CLI binary is executable in the zip. Add a post-install step inside the `ZipFile` write loop:
   ```python
   # Ensure the Copilot CLI binary has executable permissions in the zip.
   for f in app_dir.rglob("*"):
       if f.is_file():
           arcname = str(f.relative_to(app_dir))
           info = zipfile.ZipInfo(arcname)
           if "copilot/bin/" in arcname and not arcname.endswith(".py"):
               info.external_attr = 0o755 << 16  # Unix executable
           zf.writestr(info, f.read_bytes())
   ```
   This replaces the existing simple `zf.write(f, f.relative_to(app_dir))` loop.

**Post-condition:** `python -m scripts.build_lambda` produces a zip containing:
- `scripts/copilot_sdk_client.py`
- `copilot/` directory with SDK code + `copilot/bin/copilot` binary
- `pydantic/`, `pydantic_core/`, `dateutil/` (SDK dependencies)

### Step 6: Modify `tests/test_build_lambda.py` -- add SDK install test

**File:** tests/test_build_lambda.py (Modify)

**Changes:** Add test(s) verifying:

1. `"copilot_sdk_client.py"` is in `_LAMBDA_SCRIPTS`.
2. `"bedrock_client.py"` is still in `_LAMBDA_SCRIPTS` (dormant, must not be accidentally removed).
3. `_COPILOT_SDK_PACKAGE` constant is defined and contains `github-copilot-sdk`.
4. Mock `subprocess.run` and verify that `build_app_package()` (or the SDK install helper) calls pip with `--platform manylinux_2_28_x86_64` and the package name from `_COPILOT_SDK_PACKAGE`. This matches the existing test pattern for subprocess call argument verification.

**Post-condition:** `python -m pytest tests/test_build_lambda.py -x -q` passes.

### Step 7: Modify `.github/agents/schedule.yaml` -- update all agents

**File:** .github/agents/schedule.yaml (Modify)

**Pre-condition:** All 6 agents have `provider: bedrock` with Bedrock model IDs.

**Changes:** Update all 6 agents:

1. **doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality** (5 agents):
   - Change `model:` from `anthropic.claude-3-5-haiku-20241022-v1:0` to `claude-haiku-4.5`
   - Change `provider:` from `bedrock` to `copilot-sdk`

2. **rec-curator** (1 agent):
   - Change `model:` from `anthropic.claude-sonnet-4-6` to `claude-sonnet-4.6`
   - Change `provider:` from `bedrock` to `copilot-sdk`
   - Note: uses Sonnet 4.6 (not Sonnet 4) to maintain capability parity with the previous Bedrock model.

**Post-condition:** All 6 agents have `provider: copilot-sdk` with SDK model IDs.
Run `python -m pytest tests/test_run_scheduled_agent.py::TestRealManifest -x -q` to validate manifest structure.

### Step 8: Modify `docs/contracts/inference-provider.md` -- add copilot-sdk provider

**File:** docs/contracts/inference-provider.md (Modify)

**Changes:**

1. Update Summary to mention Copilot SDK as the active inference provider.

2. Add `copilot-sdk` to the Provider Field Schema table:
   ```
   | `copilot-sdk` | `scripts/copilot_sdk_client.copilot_sdk_inference_sync()` | Lambda (required) and local |
   ```

3. Add a new section "### Copilot SDK Model IDs" with the format and approved models:
   - Format: `{provider}-{family}-{version}` (e.g., `claude-haiku-4.5`, `claude-sonnet-4`)
   - Table of approved models with multipliers
   - Validation: `client.list_models()` via SDK, or reference https://docs.github.com/en/copilot/using-github-copilot/ai-models/supported-ai-models-in-copilot

4. Update the IAM Requirements section to note Bedrock IAM is no longer required (Copilot SDK uses GitHub PAT, not IAM).

5. Update the Client Interface section to document `copilot_sdk_client.py`.

6. Update the Routing Logic section to show the three-way dispatch.

7. Update the Plan Compliance Checklist:
   - Change `provider: bedrock` to `provider: copilot-sdk`
   - Change Bedrock model ID format to SDK model ID format
   - Replace `bedrock_client.py` reference with `copilot_sdk_client.py`

8. Update the Migration Reference table to show the current mapping.

**Post-condition:** Contract accurately documents the `copilot-sdk` provider as the active Lambda inference provider.

### Step 9: Modify `docs/DECISIONS.md` -- add Decision 49

**File:** docs/DECISIONS.md (Modify)

**Changes:** Add Decision 49 at the top of the file (below the header, above Decision 48):

```markdown
## Decision 49: Copilot SDK as Lambda Inference Provider (Supersedes Decision 47)

**Decision:** The GitHub Copilot SDK (`github-copilot-sdk` v0.2.2) replaces AWS Bedrock as the inference provider for all Lambda-executed scheduled agents. Model IDs use Copilot SDK format (e.g., `claude-haiku-4.5`, `claude-sonnet-4`). Auth uses the existing Secrets Manager GitHub PAT.

**Problem:**
On April 2026, AWS Bedrock access was revoked in the sandbox account (REDACTED-ACCOUNT-ID) because the models were accepted without proper AI Steering Group approval. All 6 scheduled agents stopped functioning. The GitHub Models API (the previous fallback) lacks Claude and Gemini models -- only OpenAI, DeepSeek, and Grok models are available -- making it inadequate for quality-sensitive agents like rec-curator.

**Why Copilot SDK over alternatives:**
- **GitHub Models API:** No Claude, no Gemini. GPT-4.1-mini quality too low for rec-curator.
- **Bedrock (restored):** Would require AI Steering Group re-approval. Timeline unknown.
- **Copilot SDK:** Provides Claude Haiku 4.5 (0.33x multiplier), Sonnet 4 (1x), and other high-quality models. Uses existing GitHub PAT from Secrets Manager. Fits in Lambda zip (69 MB total). Confirmed working via live tests.

**SDK architecture:**
The SDK spawns a Copilot CLI subprocess via JSON-RPC. The CLI binary (~58 MB) is bundled in the pip wheel. Auth is via `SubprocessConfig(github_token=...)`. Sessions are created per-inference call with `tools=[]` to disable agent tool use.

**Model mapping:**
| Agent | Model | Multiplier |
|-------|-------|------------|
| doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality | `claude-haiku-4.5` | 0.33x |
| rec-curator | `claude-sonnet-4.6` | 1x |

**Lambda packaging:**
SDK is pip-installed into `data-pipeline.zip` (not the deps layer) using `--platform manylinux_2_28_x86_64`. The CLI binary at `copilot/bin/copilot` must have executable permissions (0o755) in the zip. Total SDK footprint: ~69 MB (binary 58 MB + Python 1.2 MB + pydantic 9 MB + dateutil 0.6 MB).

**Constraints:**
- SDK is Public Preview (v0.2.2) -- pin version in `build_lambda.py` to prevent breakage
- `bedrock_client.py` is retained as dormant code -- available if Bedrock access is restored
- Lambda memory may need increase from 512 MB to 1024 MB if CLI subprocess causes OOM
- `_preload_rec_curator_context()` still required -- SDK `tools=[]` disables file reading

**Related:** Decision 47 (superseded), Decision 40 (Copilot SDK for executor -- still deferred, separate concern), Decision 48 (V3 verification tier), `docs/contracts/inference-provider.md`

**Decision status:** Decided -- April 2026
```

Mark Decision 47's title as `(Superseded by Decision 49)`.

**Post-condition:** Decision 49 exists. Decision 47 marked as superseded.

### Step 10: Modify `terraform/scheduled_agents.tf` -- remove Bedrock IAM

**File:** terraform/scheduled_agents.tf (Modify)

**Pre-condition:** File contains `BedrockInference` IAM statement block.

**Changes:** Remove the entire `BedrockInference` statement block from the `aws_iam_policy.scheduled_agent_lambda` policy. Update the comment above the policy to note: "Bedrock IAM removed (Decision 49 -- Copilot SDK uses GitHub PAT, not IAM). Retained: S3, Secrets Manager, CloudWatch Logs."

**Post-condition:** IAM policy no longer includes Bedrock permissions.

### Step 11: Terraform plan, human review, and apply

**HUMAN GATE -- this step requires human interaction.**

1. Run: `cd terraform && terraform plan -out=tfplan -var-file=terraform.tfvars`
2. Summarise plan output (should show 1 resource changed: IAM policy - BedrockInference statement removed)
3. **STOP and ask:** "Terraform plan shows [N] to change. [summary]. Say **apply** to proceed."
4. Only after human says "apply": `terraform apply tfplan`
5. Verify exit code 0. Clean up: `rm tfplan`

**Post-condition:** terraform apply completed. Bedrock permissions removed from Lambda role.

### Step 12: Modify `.github/copilot-instructions.md` -- update references

**File:** .github/copilot-instructions.md (Modify)

**Changes:**

1. **File Router:** Add row: `| Copilot SDK client (Lambda) | [scripts/copilot_sdk_client.py](../scripts/copilot_sdk_client.py) |`

2. **Known Gotchas -- Lambda deployment pipeline:** Update item (3) post-deploy verification to use conditional wording matching inference-provider.md. Update the model ID examples to include Copilot SDK format: "Copilot SDK model IDs (e.g., `claude-haiku-4.5`, `claude-sonnet-4`) differ from Bedrock format (revoked) and GitHub Models IDs (`gpt-5-mini`). See docs/contracts/inference-provider.md and Decision 49."

**Post-condition:** File Router lists `copilot_sdk_client.py`. Known Gotchas reflect Copilot SDK as active provider.

### Step 13: Run all tests

```bash
python -m pytest tests/test_copilot_sdk_client.py tests/test_scheduled_agent_handler.py tests/test_build_lambda.py tests/test_run_scheduled_agent.py::TestRealManifest -x -q
```

Must all pass.

### Step 14: Run validation

```bash
python -m scripts.validate
```

Must exit 0.

### Step 15: Build and deploy Lambda

**V3 iterative deploy-test-fix loop:**

1. Build: `python -m scripts.build_lambda`
   - Verify zip is created and size is < 250 MB unzipped
   - Inspect zip contents: confirm `copilot/bin/copilot` exists and `scripts/copilot_sdk_client.py` exists

2. Deploy: `python -m scripts.build_lambda --deploy`
   - Verify S3 upload succeeds
   - Verify Lambda function code update succeeds for both dispatcher and findings-processor

3. Smoke test:
   ```bash
   aws lambda invoke \
     --function-name agent-platform-scheduled-agent-dispatcher \
     --payload '{"force_agent":"doc-freshness"}' \
     --profile company-aws-profile \
     --region eu-west-2 \
     --cli-binary-format raw-in-base64-out \
     /tmp/sdk-smoke-test.json && cat /tmp/sdk-smoke-test.json
   ```
   - Expected: `agents_run >= 1`, `agents_failed == 0`
   - If `agents_failed > 0`: read CloudWatch logs, fix the issue, redeploy, re-invoke
   - Common failure modes:
     - OOM: increase Lambda memory from 512 to 1024 MB in `scheduled_agents.tf`, re-apply terraform, redeploy
     - Permission denied on binary: ensure `copilot/bin/copilot` has 0o755 in zip
     - PAT auth failure: verify Secrets Manager secret value is a valid GitHub PAT with Copilot scope
     - Timeout: increase Lambda timeout or SDK timeout parameter

4. Repeat steps 1-3 until smoke test passes.

**Post-condition:** Lambda successfully invokes doc-freshness agent via Copilot SDK.

### Step 16: Report implementation summary

Report what was implemented, any design decisions made during implementation, and Lambda smoke test results. List any issues encountered and how they were resolved.
