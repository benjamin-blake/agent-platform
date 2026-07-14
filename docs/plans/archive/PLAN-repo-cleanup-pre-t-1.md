# Plan

## Intent
Remove committed dead-code ceremony accumulated before platform roadmap tier work begins.
Deleting these surfaces entirely simplifies T-1.0's reference-sweep scope rather than routing
references through them.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/repo-cleanup-pre-t-1

## Phase
Pre-T-1.0 hygiene. Not a named tier item; this work reduces T-1.0 and T5.5 scope by
eliminating surfaces rather than sweeping them.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.antigravity/` (10 workflow files) | Delete (git rm -r) | Transitional Copilot surface; superseded by `.claude/` |
| `.gemini/settings.json` | Delete (git rm) | Gemini CLI legacy |
| `.gemini/telemetry.log` | Delete (rm -f, untracked) | 925 MB Gemini telemetry; frees disk |
| `.vscode/mcp.json`, `.vscode/settings.json` | Delete (git rm -r) | Editor-local config; migrating to cloud dev surface (T0.2) |
| `personal_scripts/` | Delete (git rm -r) | Personal-use scripts unrelated to repo |
| `scratch/` (5 .py files) | Delete (git rm -r) | One-off debug scripts |
| `docker/` (Dockerfile, docker-compose.yml, .env.example, Dockerfile.lambda-layer) | Delete (git rm -r) | Pre-T0.7a Lambda layer surface; T0.7a defines per-Lambda Dockerfiles at src/lambdas/*/Dockerfile |
| `scratch_list_critical.py` | Delete (git rm) | One-off root script |
| `GEMINI.md` | Delete (git rm) | Gemini agent instructions; repo uses Claude Code |
| `docs/INTENT-compute-and-account-topology.md` | Delete (git rm) | RETIRED per CD.14; content fully inlined into ROADMAP-PLATFORM.yaml |
| `docs/AGENT_WORKFLOW.md` | Delete (git rm) | VS Code Copilot workflow guide; superseded by Claude Code |
| `docs/CRON_REVIEW_SUMMARY.md` | Delete (git rm) | Empty file |
| `docs/github_copilot_cli/` (5 .md files) | Delete (git rm -r) | Copilot CLI docs; repo uses Claude Code |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Remove 3 stale scope entries referencing now-deleted paths |
| `config/executor_capabilities.yaml` | Modify | Remove `GEMINI.md` from `boundary_patterns` list |
| `CLAUDE.md` | Modify | Port Windows heredoc + kill_process_tree rules from GEMINI.md to Shell invocations section |

## Bundled Recommendations
None.

## Infrastructure Dependencies
None.

## Acceptance Criteria
- [ ] All 12 tracked delete targets absent from `git ls-files`
- [ ] `docs/ROADMAP-PLATFORM.yaml` T-1.0 files_in_scope contains no `.antigravity/workflows/` entry
- [ ] `docs/ROADMAP-PLATFORM.yaml` T2.3 files_in_scope contains no `GEMINI.md` entry
- [ ] `docs/ROADMAP-PLATFORM.yaml` T5.5 files_in_scope contains no `docs/INTENT-compute-and-account-topology.md` entry
- [ ] `scripts/validate.py` (full presubmit) exits 0
- [ ] `pytest tests/` passes in full
- [ ] `scripts/prompt_compliance.py` exits 0
- [ ] `scripts/session_preflight.py` produces valid `logs/.preflight-report.json`
- [ ] `config/executor_capabilities.yaml` `boundary_patterns` list contains no `GEMINI.md` entry
- [ ] `CLAUDE.md` contains the Windows heredoc temp-file guidance and the kill_process_tree Popen rule

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-delete | Confirm clean baseline | `git status --short` | Empty output (clean tree) | Stash or commit outstanding changes before proceeding |
| 2 | post-delete | Tracked targets gone | `git ls-files .antigravity .gemini GEMINI.md .vscode personal_scripts scratch docker scratch_list_critical.py docs/INTENT-compute-and-account-topology.md docs/AGENT_WORKFLOW.md docs/CRON_REVIEW_SUMMARY.md docs/github_copilot_cli` | No output (all 0 tracked hits) | Re-run `git rm` for any paths still shown |
| 3 | post-delete | Source dead-reference check | `grep -rn "\.antigravity\|GEMINI\.md\|scratch_list_critical\|INTENT-compute-and-account-topology\|AGENT_WORKFLOW\|CRON_REVIEW_SUMMARY\|github_copilot_cli\|personal_scripts\|docker/Dockerfile\|docker/docker-compose" --include="*.py" --include="*.yaml" --include="*.toml" --exclude-dir=".git" --exclude-dir="docs/plans" --exclude-dir="logs" --exclude="DECISIONS_ARCHIVE.md" --exclude="SESSION_LOG_ARCHIVE.md" --exclude="CHANGELOG.md" .` | Zero hits in executable source | Update live reference; if in Python source file, file rec and do not patch inline |
| 4 | post-delete | Full presubmit (= CI) | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Investigate failure; if caused by deleted-path reference, update that reference or file a rec |
| 5 | post-delete | Full test suite | `.venv/Scripts/python.exe -m pytest tests/ -x -q` | All tests pass | If ImportError from deleted path, file rec and revert only that specific deletion |
| 6 | post-delete | Prompt compliance | `.venv/Scripts/python.exe -m scripts.prompt_compliance` | Exit 0 | Investigate; if scanner itself references a deleted path, file rec |
| 7 | post-delete | Preflight health | `.venv/Scripts/python.exe -m scripts.session_preflight && .venv/Scripts/python.exe -c "import json; json.load(open('logs/.preflight-report.json')); print('preflight-json-ok')"` | Prints `preflight-json-ok` | Investigate new preflight errors against baseline |
| 8 | post-delete | ROADMAP schema check | `.venv/Scripts/python.exe -m scripts.validate --pre 2>&1 \| grep -i "roadmap\|yaml"` | No ROADMAP-related validation failure | Fix YAML structure if the 3 line removals broke the Pydantic schema (should be safe; they are list item removals) |

## Constraints
- TIER B surfaces (`.github/prompts/`, `.github/agents/`, `.github/copilot-instructions.md`,
  `.github/instructions/`, `.agents/`) are explicitly deferred to T-1.0 / T5.3; do NOT touch them.
- TIER C 10x `docs/INTENT-*.md` docs are retained per CD.14 (demotion, not deletion).
- `pip/` and `venv/` (both gitignored) are left for the Linux-container migration (T0.2).
- `docker/.env` (gitignored) will remain on disk after `git rm -r docker/`; acceptable.
- No code modifications. If a VP step reveals a live Python import of a deleted path, stop,
  file a rec via ops_data_portal, and revert only that specific deletion.
- No STRATEGIC plans (temporary constraint per CLAUDE.md / Decision 67).

## Context
- `.antigravity/` was designated "transitional surface per Decision 58." It is fully superseded
  by `.claude/` and has no live runtime consumers.
- `docs/INTENT-compute-and-account-topology.md` deletion is mandated by CD.14 (pending
  ratification, but the deletion action is unambiguous from CD.14's detail text). T5.5 still
  owns sweeping the residual consumer references (docs/PROJECT_CONTEXT.md etc.) -- those stay.
- `docker/` was the pre-roadmap Lambda layer build surface. T0.7a defines per-Lambda Dockerfiles
  at `src/lambdas/log_rec/Dockerfile` etc.; the root docker/ dir has no planned consumers.
- `config/executor_capabilities.yaml` line ~36 lists `GEMINI.md` in `boundary_patterns` as a stop-file for executor agents. Deleting GEMINI.md without removing this entry leaves a dangling constraint. Note: the executor is currently non-functional and is unlikely to be operational for a long time (per user; Fargate executor is T4.2 and Decision 67 STRATEGIC freeze remains). The boundary cleanup is still correct — a dangling reference to a deleted file is noise regardless of executor status.
- `config/executor_capabilities.yaml` is Lambda-packaged (data-pipeline.zip, via build_lambda.py). The modification therefore requires a DEFERRED Lambda deployment step per Decision 67. The DEFERRED is a formality while the executor is non-functional.
- `GEMINI.md` contains two Windows-specific rules not duplicated in CLAUDE.md: (1) heredoc failure on Git Bash (line 17); (2) `subprocess.run(timeout=N)` does NOT cascade termination on Windows — must use `Popen` + `proc.communicate` + `kill_process_tree(proc.pid)` for child-spawning processes (line 16). Both must be ported to CLAUDE.md "Shell invocations on Windows" section before the file is deleted.
- Three ROADMAP-PLATFORM.yaml edits keep the tier_item scope lists accurate:
  1. T-1.0 files_in_scope: remove `.antigravity/workflows/` (directory deleted here)
  2. T2.3 files_in_scope: remove `GEMINI.md` (file deleted here; T2.3 profile-sweep no longer applies)
  3. T5.5 files_in_scope: remove `docs/INTENT-compute-and-account-topology.md # deleted`
     (deletion happens here, not at T5.5; T5.5 consumer_fixups and exit_criteria are retained)
- `README.md` still references some deleted paths; out of scope here, picked up by T-1.0.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Batch-delete all tracked ceremony in one `git rm` invocation:
   ```
   git rm -r .antigravity/ .gemini/settings.json .vscode/ personal_scripts/ scratch/ docker/ docs/github_copilot_cli/
   git rm scratch_list_critical.py GEMINI.md docs/INTENT-compute-and-account-topology.md docs/AGENT_WORKFLOW.md docs/CRON_REVIEW_SUMMARY.md
   ```
2. Remove the untracked 925 MB telemetry log and clean up the now-empty `.gemini/` dir:
   ```
   rm -f .gemini/telemetry.log
   rmdir .gemini 2>/dev/null || true
   ```
3. Modify `CLAUDE.md` — add to "Shell invocations on Windows" section (after the `source .venv/Scripts/activate` note):
   ```
   - Terminal multi-line Python one-liners: heredoc (`python << EOF`) fails on Windows Git Bash -- write the script to a temp file and invoke via `.venv/Scripts/python.exe tmp_script.py`.
   - Windows subprocess cascading: `subprocess.run(timeout=N)` does NOT cascade termination to child processes on Windows. For subprocesses that may spawn children (validate.py, CLI tools), use `subprocess.Popen` + `proc.communicate(timeout=N)` + `kill_process_tree(proc.pid)` from `scripts.copilot_wrapper`.
   ```
4. Modify `config/executor_capabilities.yaml` — remove the `- GEMINI.md` line from `boundary_patterns`.
4b. DEFERRED: `build_lambda.py --deploy + run_scheduled_agent.py --smoke-test` (pending Decision 67 reversal). `config/executor_capabilities.yaml` is Lambda-packaged; deployment is deferred while executor is non-functional.
5. Modify `docs/ROADMAP-PLATFORM.yaml` — three targeted line removals:
   - T-1.0 `files_in_scope`: remove the two lines `# Antigravity workflows (transitional surface per Decision 58)` and `- .antigravity/workflows/`
   - T2.3 `files_in_scope`: remove the line `- GEMINI.md`
   - T5.5 `files_in_scope`: remove the line `- docs/INTENT-compute-and-account-topology.md    # deleted`
6. **Execute Verification Plan** -- run each step in order. Loop on any failure. If step 5
   (pytest) fails with an ImportError from a deleted path, stop, file rec, revert that deletion;
   do not patch the import to fix the test within this plan.
7. Report: files deleted, ROADMAP lines updated, VP results.
