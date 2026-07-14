# Plan

## Intent
Restore the autonomous self-improving loop after three rapid provider migrations (Copilot CLI -> Bedrock -> Personal Bedrock -> Gemini CLI) left the executor non-functional and the scheduled agents disabled. This directly serves the North Star by re-establishing the feedback sensors and execution machinery that drive continuous improvement.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-state-of-repo

## Phase
Phase Platform (automation infrastructure) -- cross-wave recovery

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/llm_client.py` | Modify | Fix `_resolve_provider()` to use `model_registry.resolve_provider()` instead of hardcoded `"bedrock"` default |
| `scripts/execute_recommendation.py` | Modify | Set `LLM_PROVIDER=gemini` in `os.environ` at executor entry point as safety net |
| `.github/agents/schedule.yaml` | Modify | Revert all agents from `provider: bedrock` to `provider: copilot-sdk`, models to `claude-haiku-4.5`, `enabled: true` |
| `docs/contracts/inference-provider.md` | Modify | Update provider status: Copilot SDK active for Lambda, Gemini CLI active for executor, Bedrock dormant |
| `docs/DECISIONS.md` | Modify | Add Decision 54: Lambda agents revert to Copilot SDK |
| `logs/.recommendations-log.jsonl` | Modify | Bulk-update 24 recs: supersede 22, close 2 |
| `docs/ROADMAP.md` | Modify | Update Phase Platform wave statuses to reflect current reality |
| `.github/copilot-instructions.md` | Modify | Update Known Gotchas: add executor provider gap fix, update Gemini CLI gotcha |
| `scripts/build_lambda.py` | Modify | Re-enable Copilot SDK pip install (`github-copilot-sdk==0.2.2`) in `build_app_package()` for Lambda deployment |
| `tests/test_llm_client.py` | Modify | Update existing `TestResolveProvider` tests to expect `"gemini"` default instead of `"bedrock"` |

## Bundled Recommendations
None directly. rec-379 and rec-380 are closed as already-implemented. 22 recs superseded (see Step 7).

## Acceptance Criteria
- [ ] `LLM_PROVIDER=gemini python -c "from scripts.llm_client import _resolve_provider; assert _resolve_provider() == 'gemini'"` passes
- [ ] `grep -q 'provider: copilot-sdk' .github/agents/schedule.yaml && grep -c 'enabled: true' .github/agents/schedule.yaml` returns 6
- [ ] `python -m pytest tests/test_llm_client.py -q` passes
- [ ] `python -m scripts.validate --scope all` exits 0 (on the branch, after branch check bypass)
- [ ] `grep -c '"status": "superseded"' logs/.recommendations-log.jsonl` is >= 22 more than current count
- [ ] `grep -c '"status": "closed"' logs/.recommendations-log.jsonl` is >= 2 more than current count (rec-379, rec-380)
- [ ] `grep -q '_COPILOT_SDK_PACKAGE' scripts/build_lambda.py` -- SDK install re-enabled (not commented out)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Verify executor provider resolution uses model_registry | `LLM_PROVIDER=gemini python -c "from scripts.llm_client import _resolve_provider; print(_resolve_provider())"` | Prints `gemini` | `_resolve_provider()` still hardcodes `"bedrock"` default -- check import of `model_registry` |
| 2 | [pre-deploy] | Verify schedule.yaml agents all use copilot-sdk and are enabled | Write tmp_vp2.py: `import yaml; agents=yaml.safe_load(open('.github/agents/schedule.yaml'))['agents']; assert all(a['provider']=='copilot-sdk' for a in agents); assert all(a.get('enabled',True) for a in agents); print(f"{len(agents)} agents: all copilot-sdk, all enabled")`. Run `python tmp_vp2.py`. | Prints `6 agents: all copilot-sdk, all enabled` | Provider or enabled field not updated for all agents |
| 3 | [pre-deploy] | Run full test suite | `python -m pytest tests/ -q --tb=short` | All tests pass, zero failures | Test assertion mismatch -- update test expectations |
| 4 | [pre-deploy] | Verify JSONL triage counts | Write tmp_vp4.py: `import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl')]; sup=sum(1 for r in recs if r.get('status')=='superseded'); clo=sum(1 for r in recs if r.get('status')=='closed'); print(f'superseded={sup} closed={clo}'); assert sup >= 46; assert clo >= 288`. Run `python tmp_vp4.py`. | `superseded` >= 46 (24 existing + 22 new), `closed` >= 288 (286 existing + 2 new) | Missed a rec in the bulk update -- check line-by-line |
| 5 | [post-deploy] | Build and deploy Lambda with reverted schedule.yaml | `python -m scripts.build_lambda && python -m scripts.build_lambda --deploy` | Build succeeds, deploy uploads to S3 and updates Lambda function code | Build failure -- check `_LAMBDA_SCRIPTS` includes required files |
| 6 | [post-deploy] | Smoke test one scheduled agent via Lambda | `python -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Agent runs successfully with copilot-sdk provider, produces findings or empty output without error | PAT expired or copilot-sdk package missing from Lambda layer -- check Secrets Manager and layer contents |
| 7 | [post-deploy] | Run executor on a safe XS rec to prove Gemini CLI path works | `LLM_PROVIDER=gemini python -m scripts.execute_recommendation --rec-id rec-325` | Executor completes planning phase and produces a plan. Full success not required -- planning phase completing proves the LLM call path works. | Gemini CLI not found or prompt too large -- check `gemini --version` and prompt assembly |

## Constraints
- Python 3.12+, type hints required
- Shell: Bash syntax only, no PowerShell
- Copilot SDK models: `claude-haiku-4.5` for lightweight agents (per inference-provider.md swap-back plan)
- Lambda deployment required for schedule.yaml changes to take effect
- Executor boundary rule: this plan does NOT modify executor internal logic (plan.py, step_runner.py, postflight.py) -- only the LLM client routing and the entry point env var
- JSONL edits must preserve the existing format (one JSON object per line, space after colon)

## Context
- Decision 52: Bedrock migration (dormant -- personal account quotas throttled to 0)
- Decision 53: Gemini CLI as executor provider (active for local executor, NOT for Lambda agents)
- `docs/contracts/inference-provider.md` documents the swap-back plan for copilot-sdk
- `scripts/copilot_sdk_client.py` is marked DEPRECATED but fully functional
- `_invoke_copilot_sdk()` in `scheduled_agent_handler.py` is fully wired and tested
- The `model_registry.resolve_provider()` function already defaults to `"gemini"` -- the bug is that `llm_client._resolve_provider()` has its own independent default of `"bedrock"`
- Session telemetry Phase B instrumentation is active; both old JSONL and new OpsWriter paths write simultaneously (Phase F will remove the old path)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Fix `llm_client._resolve_provider()` to use `model_registry`

**File:** `scripts/llm_client.py`

**What to change:** Replace the hardcoded `"bedrock"` default in `_resolve_provider()` with a call to `scripts.model_registry.resolve_provider()`. The function currently reads `LLM_PROVIDER` env var and defaults to `"bedrock"`. After this change, it should delegate to `model_registry.resolve_provider()` which already reads the same env var but defaults to `"gemini"` (the correct executor default). This unifies the provider resolution logic.

**Specific edit:** In `_resolve_provider()` (around line 64-75), replace the function body with:

```python
def _resolve_provider() -> str:
    """Return the active inference provider.

    Delegates to ``model_registry.resolve_provider()`` which reads the
    ``LLM_PROVIDER`` environment variable and defaults to ``"gemini"``
    for executor use.  Lambda handlers do not call this path (they route
    by the ``provider`` field in schedule.yaml).
    """
    from scripts.model_registry import resolve_provider
    return resolve_provider()
```

The deferred import avoids circular import issues (model_registry imports nothing from llm_client).

**Also update:** Remove the module-level `_VALID_PROVIDERS` constant (line 62) since validation now lives in `model_registry`. Keep the constant if any other function in `llm_client.py` references it -- grep first.

**Acceptance:** `LLM_PROVIDER=gemini python -c "from scripts.llm_client import _resolve_provider; assert _resolve_provider() == 'gemini', _resolve_provider()"`

---

### Step 2: Set `LLM_PROVIDER=gemini` safety net in executor entry point

**File:** `scripts/execute_recommendation.py`

**What to change:** Near the top of `_execute_recommendation_inner()` (or `main()`), add `os.environ.setdefault("LLM_PROVIDER", "gemini")` as a safety net. This ensures that even if a user forgets to set the env var, the executor defaults to the correct provider.

**Where:** Find the `main()` or `_execute_recommendation_inner()` function. Add the `setdefault` call before any `llm_call()` invocation occurs. Place it after argument parsing but before any LLM work.

**Acceptance:** `grep -q 'LLM_PROVIDER.*gemini' scripts/execute_recommendation.py`

---

### Step 3: Update existing `TestResolveProvider` tests

**File:** `tests/test_llm_client.py`

**What to change:** The class `TestResolveProvider` already exists (around line 82). Four tests need updating to reflect the new default:
1. `test_defaults_to_bedrock` -- rename to `test_defaults_to_gemini`, change assertion from `== "bedrock"` to `== "gemini"`.
2. `test_env_var_gemini` -- no change needed (already asserts `"gemini"`).
3. `test_env_var_bedrock` -- no change needed (already asserts `"bedrock"`).
4. `test_invalid_falls_back_to_bedrock` -- rename to `test_invalid_falls_back_to_gemini`, change assertion from `== "bedrock"` to `== "gemini"`.

**Acceptance:** `python -m pytest tests/test_llm_client.py::TestResolveProvider -v`

---

### Step 4: Revert `schedule.yaml` to Copilot SDK

**File:** `.github/agents/schedule.yaml`

**What to change:** For ALL 6 agents:
- Change `model: deepseek.v3.2` to `model: claude-haiku-4.5` for 5 lightweight agents
- Change `model: deepseek.v3.2` to `model: claude-sonnet-4.6` for `rec-curator` (per Decision 49 -- most cognitively demanding agent)
- Change `provider: bedrock` to `provider: copilot-sdk`
- Change `enabled: false` to remove the `enabled` line entirely (default is `true`) or set `enabled: true`
- Remove the `# Disabled: Bedrock rate-limited...` comments

**Acceptance:** `grep -q 'provider: copilot-sdk' .github/agents/schedule.yaml && grep -c 'enabled: true' .github/agents/schedule.yaml`

---

### Step 5: Re-enable Copilot SDK install in `build_lambda.py`

**File:** `scripts/build_lambda.py`

**What to change:** The Copilot SDK pip install was commented out during the Bedrock migration (commit f17337b). Re-enable it:

1. Uncomment `_COPILOT_SDK_PACKAGE = "github-copilot-sdk==0.2.2"` (around line 54).
2. Replace the `print("  Skipping Copilot SDK install...")` line (around line 106) with the original `subprocess.run` pip install call. The original code (from commit 492c730) is:

```python
    print("  Installing Copilot SDK into app package...")
    sdk_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            _COPILOT_SDK_PACKAGE,
            "--target",
            str(app_dir),
            "--platform",
            "manylinux_2_28_x86_64",
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--quiet",
        ],
        check=False,
    )
    if sdk_result.returncode != 0:
        print(f"ERROR: Copilot SDK installation failed (exit {sdk_result.returncode})")
        sys.exit(1)
```

3. Restore the executable permissions logic in the zip writer. Change the generic `info.external_attr = 0o644 << 16` to include the `copilot/bin/` check:

```python
                if "copilot/bin/" in arcname.replace("\\", "/") and not arcname.endswith(".py"):
                    info.external_attr = 0o755 << 16  # Unix executable
                else:
                    info.external_attr = 0o644 << 16
```

4. Update the DEPRECATED comments to reflect the re-enablement.

**Acceptance:** `grep -q '_COPILOT_SDK_PACKAGE = ' scripts/build_lambda.py && grep -qv 'Skipping Copilot SDK' scripts/build_lambda.py`

---

### Step 6: Run tests for build_lambda changes

**File:** `tests/test_build_lambda.py`

**What to change:** Run existing tests to make sure they still pass. If any test asserts the "Skipping Copilot SDK" message, update it to expect the new "Installing Copilot SDK" message.

**Acceptance:** `python -m pytest tests/test_build_lambda.py -v`

---

### Step 7: Bulk-update recommendations JSONL

**File:** `logs/.recommendations-log.jsonl`

**What to change:** For each of these 22 rec IDs, change `"status": "open"` to `"status": "superseded"` and add a `"resolution"` field:

**Supersede (provider migration -- Decision 53):** rec-128, rec-145, rec-276, rec-339, rec-382, rec-383, rec-384, rec-390, rec-391, rec-479

Resolution: `"Superseded by Decision 53 (Gemini CLI migration). Target code is dormant/deprecated."`

**Supersede (develop-executor.prompt.md obsolescence):** rec-270, rec-272, rec-316, rec-317, rec-321, rec-328, rec-408, rec-415, rec-417, rec-420, rec-441, rec-452

Resolution: `"Superseded: develop-executor.prompt.md is being replaced by autonomous executor. Improving the supervisor prompt has zero ROI."`

**Close (already implemented):** rec-379, rec-380

For these two, change `"status": "open"` to `"status": "closed"` and add:
- `"execution_result": "already_implemented"`
- `"execution_date": "2026-04-27T00:00:00Z"`
- `"resolution": "Already implemented as config/copilot_model_routing.yaml and scripts/model_registry.py (different filenames than originally specified)."`

**Implementation approach:** Write a Python script `tmp_triage.py` that reads the JSONL, applies the updates, and writes it back. Run it, verify the output, then delete the script.

**Acceptance:** `grep -c '"status": "superseded"' logs/.recommendations-log.jsonl` returns >= 46

---

### Step 8: Update `docs/contracts/inference-provider.md`

**File:** `docs/contracts/inference-provider.md`

**What to change:**
- Update the provider status table: Copilot SDK = "Active (Lambda scheduled agents)", Gemini CLI = "Active (executor)", Bedrock = "Dormant"
- Update the swap-back plan section to reflect that the swap-back has been executed
- Update model ID references: Lambda agents now use `claude-haiku-4.5` via copilot-sdk

**Acceptance:** `grep -q 'Active.*Lambda' docs/contracts/inference-provider.md`

---

### Step 9: Add Decision 54 to `docs/DECISIONS.md`

**File:** `docs/DECISIONS.md`

**What to change:** Add Decision 54 at the top of the decisions list (above Decision 53). Content:

```
### Decision 54: Lambda Scheduled Agents Revert to Copilot SDK (Supersedes Decision 52 for Lambda)

**Trigger:** Bedrock on-demand token quotas throttled to 0 on personal account. Company account Bedrock revoked by AI Steering Group. Gemini CLI is local-only and cannot run in Lambda. Data residency concerns prevent using Gemini API from company-adjacent infrastructure.

**Decision:** Lambda scheduled agents revert to GitHub Copilot SDK. `claude-haiku-4.5` for 5 lightweight agents, `claude-sonnet-4.6` for rec-curator (per Decision 49 -- highest reasoning demand). This was the pre-Decision-52 configuration and is documented as the swap-back plan in `docs/contracts/inference-provider.md`. Code change required: re-enable Copilot SDK pip install in `scripts/build_lambda.py`.

**Key details:**
- Provider: `copilot-sdk` (via `scripts/copilot_sdk_client.py`)
- Models: `claude-haiku-4.5` for 5 lightweight agents, `claude-sonnet-4.6` for rec-curator (per Decision 49 -- highest reasoning demand)
- Auth: GitHub OAuth token (`gho_` prefix from `gh auth token`) stored in Secrets Manager as `agent-platform-github-pat`
- Premium requests: uses the small remaining allocation of GitHub Copilot premium requests
- Executor path unchanged: still uses Gemini CLI locally (Decision 53)
- Bedrock path: dormant, retained for rollback
- Lambda build: `scripts/build_lambda.py` re-enables `github-copilot-sdk==0.2.2` pip install

**Supersedes:** Decision 52 for Lambda agents only. Decision 53 (Gemini CLI for executor) is unaffected.

**Status:** Decided -- April 2026
```

**Acceptance:** `grep -q 'Decision 54' docs/DECISIONS.md`

---

### Step 10: Update Decision 53 text in `docs/DECISIONS.md`

**File:** `docs/DECISIONS.md`

**What to change:** Decision 53 currently states: *"Default in `llm_client._resolve_provider()`: `"bedrock"` (Lambda safety)"*. Update this bullet to:

```
- Default in `llm_client._resolve_provider()`: delegates to `model_registry.resolve_provider()` which defaults to `"gemini"`. Lambda handlers do not call this path -- they route by the `provider` field in `schedule.yaml`.
```

This accurately reflects the code change from Step 1.

**Acceptance:** `grep -q 'model_registry.resolve_provider' docs/DECISIONS.md`

---

### Step 11: Update ROADMAP.md Phase Platform wave statuses

**File:** `docs/ROADMAP.md`

**What to change:**
- Wave 1 (Priority Queue Pipeline): Add `**Status:** Plan complete, atomic recs ready for execution` (if not already present)
- Wave 2 (Telemetry Root Cause Fix): Update to note this is subsumed by `docs/INTENT-telemetry-system.md`. The telemetry intent document is the broader redesign; Phase B (executor instrumentation) and Phase C (scheduled agent instrumentation) are complete. Phases D-F remain.
- Add a note after the Phase Platform section header noting that the executor currently uses Gemini CLI (Decision 53) and Lambda agents use Copilot SDK (Decision 54).

**Acceptance:** `grep -q 'INTENT-telemetry-system.md' docs/ROADMAP.md`

---

### Step 12: Update `.github/copilot-instructions.md` Known Gotchas

**File:** `.github/copilot-instructions.md`

**What to change:** Update the Gemini CLI gotcha to remove the statement that "executor must set `LLM_PROVIDER=gemini` explicitly" since the safety net now does this automatically. Add a new gotcha:

```
- **Executor provider resolution (Important):** `llm_client._resolve_provider()` delegates to `model_registry.resolve_provider()` which defaults to `"gemini"`. `execute_recommendation.py` also sets `os.environ.setdefault("LLM_PROVIDER", "gemini")` as a safety net. Lambda handlers route by `schedule.yaml` provider field, not by `LLM_PROVIDER` env var. To switch the executor to Bedrock: `LLM_PROVIDER=bedrock python -m scripts.execute_recommendation ...`.
```

**Acceptance:** `grep -q 'model_registry.resolve_provider' .github/copilot-instructions.md`

---

### Step 13: Run `python -m pytest tests/` -- all tests must pass

**Acceptance:** `python -m pytest tests/ -q --tb=short` exits 0

---

### Step 14: Run `python -m scripts.validate --scope all`

Note: `validate.py` refuses to run on `main`. Since we are on `agent/platform-state-of-repo`, this should work. If it refuses, check that `git branch --show-current` returns the expected branch name.

**Acceptance:** Exit code 0

---

### Step 15: **Execute Verification Plan**

Run each step from the Verification Plan table above (VP steps 1-4 are pre-deploy, VP steps 5-7 are post-deploy). VP steps 5-7 require Lambda build and deploy which is human-gated.

If a pre-deploy step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all pre-deploy steps pass.

Post-deploy steps (5-7) are executed after the human approves the Lambda deployment. VP step 7 (executor smoke test on rec-325) is advisory -- planning phase completing proves the Gemini CLI path works. Full rec completion is not required.

---

### Step 16: Report

Report: what was implemented, verification results (actual outcomes), bugs found and fixed. Include transcript analysis from the executor smoke test (VP step 7) -- document the Gemini CLI output quality observations.
