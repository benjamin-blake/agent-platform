# Plan

## Intent
Restore the automated executor pipeline by replacing the throttled Bedrock inference backend with Google Gemini CLI, enabling the self-improvement loop to resume after 17+ days of downtime. This directly serves the North Star: a self-improving automated trading system cannot improve when its execution engine is offline.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2 (with V3 waiver -- see Constraints)

## Branch
agent/platform-gemini-executor

## Phase
Phase Platform (automation infrastructure)

## Background: Why We Are Here

The executor pipeline (`scripts/execute_recommendation.py`) has been offline since April 10, 2026. Four consecutive inference backends have been tried and failed:

1. **GitHub Copilot CLI** (original, ~March 2026): GitHub paused new Copilot Pro signups due to AI provisioning shortages. We cannot purchase a subscription. Dead end.

2. **AWS Bedrock on company account** (REDACTED-ACCOUNT-ID, ~April 2026): Working initially, but the company AI Steering Group ordered immediate cessation of all Bedrock model usage pending governance review. Bedrock access was revoked. Decision 49 documented the Copilot SDK workaround for Lambda agents.

3. **AWS Bedrock on personal account** (REDACTED-PERSONAL-ACCOUNT, April 26 2026): A 51-step migration (PLAN-bedrock-migration.md) was completed, creating `llm_client.py`, `bedrock_client.py`, `tool_runtime.py`, and `llm_utils.py`. DeepSeek V3.2 was chosen for cost and capability. Only 1,216 tokens (666 input + 550 output) succeeded in a single call before AWS throttled all subsequent requests. Investigation found: all on-demand token quotas (L-F1541587, L-C43703DE, L-3AE31EFC) set to 0 across eu-west-2, us-east-1, us-west-2, ap-northeast-1. `adjustable=False` on all quota codes. AWS re:Post threads from April 2026 confirm identical reports from multiple new-account users. AWS Support case filed. No resolution timeline.

4. **Google Gemini CLI** (this plan): The user has a Google Pro plan providing 1,500 free requests/day + 1,000 AI credits/month overflow. Gemini CLI 0.40.0-preview.4 supports Gemini 3 models (gemini-3-pro-preview, gemini-3-flash-preview) and Auto mode. Headless mode (`gemini -p "..." --output-format json`) returns structured JSON with `{response, stats, error}`. Auth via Google OAuth (browser flow locally, session token export for Lambda -- Lambda migration deferred to a separate session).

The executor has not run end-to-end since April 10. The Bedrock migration (51 steps, completed April 26) refactored every LLM call path but was tested only against mocks (1,535 tests pass). Zero live integration testing has occurred. Bugs are expected.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `GEMINI.md` | Create | Repo-root context file so Gemini CLI loads project rules |
| `config/copilot_model_routing.yaml` | Create | Provider-aware model routing config (rec-379) |
| `scripts/model_registry.py` | Create | `resolve_model()`, `resolve_provider()`, `escalate_model()` (rec-380) |
| `tests/test_model_registry.py` | Create | Full resolver test coverage |
| `scripts/llm_client.py` | Modify | Add `_gemini_call()`, provider routing via `LLM_PROVIDER`, extract `_bedrock_call()` |
| `tests/test_llm_client.py` | Modify | Test `_gemini_call()` + provider routing |
| `scripts/llm_utils.py` | Modify | Update `MODEL_PLANNING`/`MODEL_EXECUTION` defaults to Gemini model IDs |
| `tests/test_llm_utils.py` | Modify | Update model default assertions |
| `scripts/executor/plan.py` | Modify | Replace hardcoded model constants with `model_registry.resolve_model()` (rec-381) |
| `scripts/executor/step_runner.py` | Modify | Replace hardcoded model constants with `model_registry.resolve_model()` (rec-381) |
| `scripts/executor/postflight.py` | Modify | Replace `MODEL_REVIEW` hardcoded default with resolver |
| `tests/test_executor_plan.py` | Modify | Update `TestModelSelection` to test resolver delegation |
| `tests/test_executor_step_runner.py` | Modify | Update model selection tests to test resolver delegation |
| `setup.py` | Modify | Add `check_gemini_cli()` to verify CLI availability and version |
| `docs/contracts/inference-provider.md` | Modify | Add Gemini CLI as active executor provider, update model ID table |
| `docs/DECISIONS.md` | Modify | Add Decision 53: Gemini CLI for executor (supersedes Decision 52 for executor) |
| `.github/copilot-instructions.md` | Modify | Update Known Gotchas and File Router for Gemini CLI |

## Bundled Recommendations
- **rec-379** (M, High): Create `config/copilot_model_routing.yaml` -- expanded for multi-provider
- **rec-380** (M, High): Create `scripts/model_registry.py` (renamed from `copilot_model_registry.py`) -- expanded for provider awareness
- **rec-381** (L, High): Wire all executor model selections through resolver

## Acceptance Criteria
- [ ] `LLM_PROVIDER=gemini python -c "from scripts.llm_client import llm_call"` imports without error
- [ ] `grep -q 'def resolve_model' scripts/model_registry.py` -- resolver exists
- [ ] `grep -q 'def _gemini_call' scripts/llm_client.py` -- Gemini transport exists
- [ ] `grep -q 'def _bedrock_call' scripts/llm_client.py` -- Bedrock transport extracted
- [ ] `grep -rn '_PLANNING_MODEL_HIERARCHY\|_IMPL_MODEL_HIERARCHY\|OPUS_FALLBACK' scripts/executor/ | grep -v '# removed\|# deprecated' | wc -l` returns 0 -- hardcoded model constants removed
- [ ] `python -m pytest tests/test_model_registry.py tests/test_llm_client.py tests/test_llm_utils.py tests/test_executor_plan.py tests/test_executor_step_runner.py -q` -- all pass
- [ ] `python -m scripts.validate` -- exits 0
- [ ] `gemini -p "echo hello" --output-format json` -- returns valid JSON with `response` field (live CLI test)
- [ ] `GEMINI.md` exists at repo root and includes `@.github/copilot-instructions.md` import

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Confirm model_registry resolves models for all effort bands | `python -c "from scripts.model_registry import resolve_model; print(resolve_model('planning', 'XS')); print(resolve_model('implementation', 'L')); print(resolve_model('review', 'S'))"` | Prints three Gemini model IDs (gemini-3-pro-preview or gemini-3-flash-preview) without errors | Import error or wrong model ID |
| 2 | pre-deploy | Confirm provider routing defaults to bedrock and can switch to gemini | `python -c "import os; from scripts.llm_client import _resolve_provider; print('default:', _resolve_provider()); os.environ['LLM_PROVIDER']='gemini'; print('override:', _resolve_provider())"` | Prints `default: bedrock` then `override: gemini` | Wrong default or env var not read |
| 3 | pre-deploy | Confirm Gemini CLI is callable and returns expected JSON schema | `python -c "import subprocess, json; r = subprocess.run(['gemini', '-p', 'Reply with only the word HELLO', '--output-format', 'json'], capture_output=True, text=True, encoding='utf-8', timeout=60); d = json.loads(r.stdout); assert 'response' in d, f'Missing response key: {list(d.keys())}'; assert 'stats' in d, f'Missing stats key: {list(d.keys())}'; print('OK:', 'HELLO' in d.get('response', '').upper())"` | Prints `OK: True` and no assertion errors | gemini not in PATH, auth expired, JSON parse failure, or schema changed in preview release |
| 4 | pre-deploy | Confirm GEMINI.md context file loads without error | `gemini -p "What project is this? Reply in one sentence." --output-format json 2>NUL` | JSON response references the trading system or ML sandbox | Empty response or no context loaded |
| 5 | pre-deploy | Full test suite passes | `python -m pytest tests/ -q --tb=short 2>&1 | tail -5` | All tests pass (1535+ passed, 0 failed) | Fix failing tests |
| 6 | pre-deploy | Validation clean | `python -m scripts.validate --scope all` | Exit 0 | Fix validation errors |

## Constraints
- **Executor boundary (Decision 44):** `llm_client.py`, `llm_utils.py` and their tests are on the boundary. Implementation via `/plan` -> `/implement` (this session), NOT automated executor.
- **Windows host, Git Bash shell.** No heredocs for Python one-liners -- use temp files + `subprocess.run([sys.executable, 'tmp.py'])`.
- **Gemini CLI is an npm global, not a pip dependency.** Cannot add to `requirements.txt`. `setup.py` checks availability + provides install guidance.
- **Preview CLI version (0.40.0-preview.4)** required for Gemini 3 models. Pin to `@preview` tag; note to move to `@latest` when stable release includes Gemini 3.
- **Lambda deployment is OUT OF SCOPE.** Scheduled agents remain on their current provider. Lambda auth (session token export to Secrets Manager) is a separate session.
- **Interactive VS Code sessions unchanged.** `/plan` (Opus), `/implement` (Sonnet/Opus), `/code-review` agent, `/develop-executor` supervisor all continue using Copilot Chat models in VS Code.
- **Bedrock kept dormant.** `bedrock_client.py`, `tool_runtime.py` unchanged. Activatable via `LLM_PROVIDER=bedrock` for future reactivation.
- **V3 tier waiver (Decision 48):** `llm_client.py` and `llm_utils.py` are in `_LAMBDA_SCRIPTS` (build_lambda.py), which normally triggers V3. However, Lambda handlers do not call `llm_call()` (confirmed via grep). The changes add a new code path (`_gemini_call`) that is unreachable from Lambda. The Bedrock path is unchanged. No Lambda deploy/smoke-test step is required. If any future Lambda code path begins calling `llm_call()`, a V3 re-assessment is needed.
- **Default provider stays `bedrock`.** `_resolve_provider()` defaults to `"bedrock"`, not `"gemini"`. The executor must set `LLM_PROVIDER=gemini` explicitly (via env var or `.env` file). This prevents silent Lambda breakage if any future Lambda code path calls `llm_call()` without the env var.
- **`MODEL_PLANNING`/`MODEL_EXECUTION` defaults unchanged.** The `llm_utils.py` constants remain `"deepseek.v3.2"` (valid Bedrock model IDs) as the dormant-but-functional fallback. The model_registry resolver returns `None` for Gemini Auto mode -- the constants are only used when `LLM_PROVIDER=bedrock`.

## Context
- **Decision 52** (Bedrock Migration): Established `llm_client.py`/`bedrock_client.py`/`tool_runtime.py`/`llm_utils.py` architecture. We preserve this architecture and add Gemini as a parallel transport.
- **Decision 44** (Executor Boundary): All files in scope are boundary files. This plan uses `/plan` -> `/implement` workflow.
- **GEMINI.md context system:** Gemini CLI uses hierarchical `GEMINI.md` files for project context (like Copilot's `copilot-instructions.md`). Supports `@file.md` imports. `settings.json` `context.fileName` can configure alternate names. We create a root `GEMINI.md` that imports from `copilot-instructions.md` to avoid duplication.
- **Headless mode:** `gemini -p "prompt" --output-format json` returns `{response: string, stats: {tokenUsage, latency}, error?: object}`. Exit codes: 0=success, 1=error, 42=bad input, 53=turn limit exceeded.
- **Model selection:** `gemini -m gemini-3-pro-preview` for explicit model, or Auto mode (default) which picks pro/flash based on task complexity. Auto is preferred for the executor since it optimises cost/quality automatically.
- **tool_runtime.py irrelevant for Gemini:** Gemini CLI has built-in agentic tools (file read/edit, shell exec, search, web fetch). Our Bedrock-specific `tool_runtime.py` (6 tools) is only used when `LLM_PROVIDER=bedrock`.
- **executor idle since April 10:** 17+ days of refactoring without live execution. Expect integration bugs. The live test in VP step 3-4 catches these early.
- **Known gotcha -- Gemini CLI 0.39.1 (stable) runs Gemini 1.5 Pro.** The preview release (0.40.0-preview.4) is required for Gemini 3 models. Confirmed via Gemini CLI conversation: the model running identifies itself as 1.5 Pro on stable, but 3.x on preview. The `--model` flag does NOT override sub-agents' model selection.
- **Data residency:** Decision 52 rejected Gemini BYOK citing UK data residency for the company sandbox. Decision 53 is for the executor running locally on a personal machine with a personal Google account. Prompts contain repo context and recommendation data from a personal GitHub repo, not company-regulated data. Company sandbox data residency constraints do not apply. If executor is later deployed to company infrastructure, a data residency re-assessment is required.
- **Roadmap location divergence:** Roadmap Wave 3 planned `scripts/executor/model_routing.py`. Delivered as `scripts/model_registry.py` at repo root scope (non-boundary, cross-cutting utility). Better design -- not executor-specific.
- **Google Pro plan SPOF:** The executor depends on a personal Google Pro subscription (1,500 req/day). If the subscription lapses or Google changes terms, the executor goes offline. Bedrock reactivation (`LLM_PROVIDER=bedrock`) is the fallback if/when AWS Support resolves the quota throttling.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Gemini CLI installed (`npm install -g @google/gemini-cli@preview`) and authenticated

## Ordered Execution Steps

### Step 1: Create `GEMINI.md`
Create `GEMINI.md` at repo root. This is the Gemini CLI equivalent of `.github/copilot-instructions.md`. Content:
- Import the main instructions file: `@.github/copilot-instructions.md`
- Add Gemini-specific notes: executor role only (not supervisor/interactive), avoid modifying files outside the plan scope
- Keep it minimal -- the `@` import pulls in all project rules

### Step 2: Create `config/copilot_model_routing.yaml`
Create the routing config file (rec-379 expanded). Structure:
```yaml
providers:
  gemini:
    cli_command: "gemini"
    headless_flags: ["-p", "--output-format", "json"]
    default_model: null  # null = Auto mode (recommended)
    models:
      pro: "gemini-3-pro-preview"
      flash: "gemini-3-flash-preview"
      auto: null  # CLI auto-selects
  bedrock:
    status: dormant
    default_model: "deepseek.v3.2"
    models:
      mid: "deepseek.v3.2"
      opus: "claude-opus-4.6"

executor:
  default_provider: "gemini"
  roles:
    planning:
      effort_bands:
        XS: { model_tier: "flash" }
        S: { model_tier: "auto" }
        M: { model_tier: "auto" }
        L: { model_tier: "pro" }
        XL: { model_tier: "pro" }
    implementation:
      effort_bands:
        XS: { model_tier: "flash" }
        S: { model_tier: "auto" }
        M: { model_tier: "auto" }
        L: { model_tier: "pro" }
        XL: { model_tier: "pro" }
      file_pattern_floors:
        - pattern: "scripts/executor/"
          min_tier: "pro"
        - pattern: "scripts/validate.py"
          min_tier: "pro"
        - pattern: "config/prompts/"
          min_tier: "pro"
        - pattern: ".github/prompts/"
          min_tier: "pro"
        - pattern: ".github/instructions/"
          min_tier: "pro"
        - pattern: ".github/agents/"
          min_tier: "pro"
        - pattern: "copilot-instructions.md"
          min_tier: "pro"
    review:
      effort_bands:
        XS: { model_tier: "flash" }
        S: { model_tier: "auto" }
        M: { model_tier: "auto" }
        L: { model_tier: "pro" }
        XL: { model_tier: "pro" }
  escalation:
    flash_to: "auto"
    auto_to: "pro"
    pro_to: null  # top of hierarchy -- human intervention

interactive:
  note: "Interactive sessions use VS Code Copilot Chat models (Opus, Sonnet). Not controlled by this config."
```
Also add an entry to `config/README.md` documenting this file.

### Step 3: Create `scripts/model_registry.py`
Create the resolver module (rec-380 expanded). Must implement:
- `resolve_provider() -> str`: Reads `LLM_PROVIDER` env var, validates against config, defaults to `gemini`
- `resolve_model(role: str, effort: str, file_path: str = "") -> str | None`: Applies precedence: (1) env var override (`COPILOT_MODEL_PLANNING`, `COPILOT_MODEL_EXECUTION`, `COPILOT_MODEL_REVIEW`), (2) file-pattern floor check, (3) effort-band lookup, (4) returns `None` for Gemini Auto mode (CLI picks model)
- `escalate_model(role: str, current_tier: str) -> str | None`: Reads escalation ladder from config. Returns `None` when at top (human intervention needed).
- `get_model_tier(model_id: str | None) -> str`: Maps model ID back to tier name (for telemetry/logging)
- Import safety: must load successfully even if config YAML file is missing (log warning, return safe defaults)
- Type hints on all functions, no `eval()`

### Step 4: Create `tests/test_model_registry.py`
Create comprehensive test file covering:
- `resolve_provider()`: default returns "gemini", env var override, invalid provider falls back
- `resolve_model()` for each role (planning, implementation, review) x each effort band (XS, S, M, L, XL)
- File-pattern floor override: `scripts/executor/plan.py` escalates XS to pro tier
- Env var precedence: `COPILOT_MODEL_EXECUTION` overrides effort-band lookup
- `escalate_model()`: flash->auto, auto->pro, pro->None
- Missing config file: returns safe defaults with warning log
- `get_model_tier()`: maps model IDs back to tier names

### Step 5: Modify `scripts/llm_client.py`
Refactor the main LLM transport layer:
1. Add `_resolve_provider()` function that reads `LLM_PROVIDER` env var (default: `"bedrock"` -- require explicit `LLM_PROVIDER=gemini` for local executor use)
2. Extract current Bedrock code into `_bedrock_call(prompt, model_id, tools, ...)` -- zero logic changes, just extraction
3. Add `_gemini_call(prompt, model_id, tools, timeout, purpose)`:
   - Write prompt to a temp file (Windows-safe, avoids shell quoting issues)
   - Build command: `["gemini", "-p", prompt_text, "--output-format", "json"]`
   - If `model_id` is not None: add `["--model", model_id]`
   - If `tools` is False: consider `--sandbox none` or plan-mode flag to limit tool use
   - `subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)`
   - Parse JSON stdout: extract `response` -> `content`, `stats` -> token counts
   - Handle exit code 53 (turn limit) as a retryable error
   - Return `LLMResult` with appropriate fields; `cost_usd=0.0` for Gemini (free tier)
4. Modify `llm_call()`: at the top, check provider via `_resolve_provider()`. If `"gemini"`, call `_gemini_call()`. If `"bedrock"` (or any other value), call `_bedrock_call()`. The default is `"bedrock"` -- require explicit `LLM_PROVIDER=gemini` env var for Gemini. The executor's `execute_recommendation.py` sets this env var at startup.
5. Update `_MODEL_MAP` to include Gemini model short names
6. Update `_emit_telemetry()` to pass correct `provider` string based on active provider
7. Keep `_compute_cost()` -- returns 0.0 for unknown Gemini models (free tier) vs per-token for Bedrock

### Step 6: Modify `tests/test_llm_client.py`
Add test coverage for:
- `_resolve_provider()`: defaults, env var override
- `_gemini_call()` with mocked `subprocess.run`: verify correct command construction, JSON parsing, exit code handling (0, 1, 53)
- Provider routing: `LLM_PROVIDER=gemini` routes to `_gemini_call`, `LLM_PROVIDER=bedrock` routes to `_bedrock_call`
- `_compute_cost()` returns 0.0 for Gemini models
- Existing Bedrock tests must still pass unchanged (they test `_bedrock_call()` now)

### Step 7: Modify `scripts/llm_utils.py`
Keep `MODEL_PLANNING` and `MODEL_EXECUTION` defaults at `"deepseek.v3.2"` (Bedrock dormant fallback). These constants are only used when `LLM_PROVIDER=bedrock`. When the executor runs with `LLM_PROVIDER=gemini`, the model_registry resolver handles model selection and returns `None` for Gemini Auto mode.

Changes needed:
- No default value changes
- Add a comment: `# Defaults are Bedrock model IDs -- used when LLM_PROVIDER=bedrock (dormant fallback)`
- Keep env var override mechanism as-is

### Step 8: Modify `tests/test_llm_utils.py`
Existing tests that assert on `"deepseek.v3.2"` defaults remain correct and unchanged. Add a comment explaining that these defaults serve the dormant Bedrock path.

### Step 9: Modify `scripts/executor/plan.py`
Replace hardcoded model constants with resolver calls (rec-381):
1. Remove: `PLANNING_MID_TIER_MODEL`, `PLANNING_OPUS_MODEL`, `_PLANNING_MODEL_HIERARCHY`, `_PLANNING_ESCALATION_THRESHOLD`, `_PLANNING_FAILURE_COUNT`, `_validate_model_hierarchy()`
2. Replace `get_planning_model(effort)` body: call `model_registry.resolve_model("planning", effort)` and return the result
3. Replace `escalate_planning_model(rec_id, current_model)` body: call `model_registry.escalate_model("planning", model_registry.get_model_tier(current_model))` and return the result. Track failure counts locally (rec-by-rec counter stays).
4. All call sites that reference the removed constants must use the functions instead

### Step 10: Modify `scripts/executor/step_runner.py`
Replace hardcoded model constants with resolver calls (rec-381):
1. Remove: `OPUS_FALLBACK`, `_LARGE_FILE_THRESHOLD` (moved to routing config), `_IMPL_MODEL_HIERARCHY`, `_IMPL_FAILURE_COUNT`
2. Replace `get_implementation_model(effort, file, action)` body: call `model_registry.resolve_model("implementation", effort, file_path=file)`. The file-pattern floor logic that currently lives inline (executor paths, prompt files, large file checks) is now handled by the resolver via the routing config.
3. Replace `escalate_implementation_model(rec_id, current_model)` body: delegate to `model_registry.escalate_model("implementation", ...)`. Keep per-rec failure counter locally.
4. Leave `get_step_timeout_secs()`, `_EXECUTOR_ACC_VARS`, and other non-model code unchanged

### Step 11: Modify `scripts/executor/postflight.py`
Replace `MODEL_REVIEW = os.getenv("COPILOT_MODEL_REVIEW", "deepseek.v3.2")` with a call to `model_registry.resolve_model("review", "M")` with env var override check. All call sites that pass `model=MODEL_REVIEW` now pass the result of the resolver.

### Step 12: Modify `tests/test_executor_plan.py`
Update `TestModelSelection` class:
- Tests now mock `scripts.model_registry.resolve_model` and `escalate_model` instead of testing hardcoded return values
- Verify `get_planning_model()` delegates to resolver with correct args
- Verify `escalate_planning_model()` delegates to resolver
- Remove assertions on specific Bedrock model IDs (e.g., `"deepseek.v3.2"`, `"claude-opus-4.6"`)
- Add test: env var override still takes precedence (resolver contract)

### Step 13: Modify `tests/test_executor_step_runner.py`
Update model selection tests:
- Mock `scripts.model_registry.resolve_model` instead of testing hardcoded return values
- Verify `get_implementation_model()` delegates to resolver with correct role, effort, and file_path
- Verify file-pattern floor logic is handled by resolver (mock returns pro for executor paths)
- Remove assertions on specific Bedrock model IDs
- Add test: `escalate_implementation_model()` delegates to `model_registry.escalate_model()`

### Step 14: Modify `setup.py`
Add `check_gemini_cli()` function:
- Check `shutil.which("gemini")` -- if not found, print install guidance (`npm install -g @google/gemini-cli@preview`)
- If found, run `gemini --version` and print version
- Warn if version < 0.40.0 (Gemini 3 models require preview)
- Call it from `main()` between `check_gh_cli()` and `check_git_bash()`

### Step 15: Modify `docs/contracts/inference-provider.md`
- Add Gemini CLI section as active executor provider
- Update model ID table with Gemini 3 model names (`gemini-3-pro-preview`, `gemini-3-flash-preview`, Auto mode)
- Document headless mode JSON schema: `{response, stats, error}`
- Document auth: Google OAuth (local), session token export (Lambda -- future)
- Update Provider Field Schema table: add `gemini-cli` as valid value
- Mark Bedrock section as dormant (not deprecated -- can be reactivated)

### Step 16: Modify `docs/DECISIONS.md`
Add Decision 53:
- Title: "Gemini CLI as Executor Inference Provider (Partially Supersedes Decision 52)"
- Trigger: Bedrock quotas throttled to 0 on personal account; company account Bedrock revoked by AI Steering Group; Copilot CLI signups paused
- Decision: Executor pipeline uses Gemini CLI (Google Pro plan) for all LLM calls. Interactive sessions remain on VS Code Copilot Chat. Lambda agents unchanged (separate session).
- Key details: model routing config, resolver module, preview CLI requirement, session token auth for future Lambda
- Data residency: Executor runs locally on personal machine with personal Google account. Not subject to company sandbox data residency constraints. Re-assessment needed if executor moves to company infrastructure.
- Known SPOF: Personal Google Pro subscription. Bedrock is the dormant fallback (`LLM_PROVIDER=bedrock`) if/when AWS Support resolves quota throttling.
- Supersedes: Decision 52 for executor path only (Decision 52 still applies to Lambda and general architecture)
- Related: Decision 44 (boundary), rec-379/380/381

### Step 17: Modify `.github/copilot-instructions.md`
- Add Gemini CLI to the File Router table: `GEMINI.md` and `config/copilot_model_routing.yaml`
- Add to Known Gotchas: "Gemini CLI version: stable (0.39.x) runs Gemini 1.5 Pro. Preview (0.40.0+) required for Gemini 3 models. Install with `npm install -g @google/gemini-cli@preview`."
- Update Decision 52 reference to note partial supersession by Decision 53
- Add `scripts/model_registry.py` to File Router

### Step 18: Run tests and validate
Run `python -m pytest tests/ -q --tb=short` -- all tests must pass.
Run `python -m scripts.validate --scope all` -- must exit 0.

### Step 19: Execute Verification Plan
Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

### Step 20: Report
Report: what was implemented, verification results (actual outcomes), bugs found and fixed, any deviations from plan.
