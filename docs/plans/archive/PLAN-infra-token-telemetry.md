# Plan

## Intent
Add quantitative token-budget telemetry to make the self-improving loop measurable at the cost dimension, and fix a recurring session-start friction point (post-merge log drift) by encoding automatic log hygiene directly into `session_preflight.py` and `plan.prompt.md`.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-token-telemetry

## Phase
Phase 1: Core Infrastructure -- COMPLETE (infra workflow improvement)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/token_budget.py` | Create | New script: estimate token counts for key context files using character heuristic (no external deps); detect bloat via static high threshold + STDEV once baseline established; log to `logs/.token-budget-log.jsonl` |
| `scripts/session_preflight.py` | Modify | (A) Call `token_budget.py` and surface `token_anomalies` in preflight JSON; (B) Add `log_sync` phase: detect if only known log files are dirty on `main`, auto-commit+push them; surface conflict error and stop if push fails |
| `.github/prompts/plan.prompt.md` | Modify | Update Step 0 to handle new `log_sync_result` field: if `log_sync_result.status == "committed"` print confirmation and continue silently; if `log_sync_result.status == "conflict"` STOP and surface for triage; replaces the generic `uncommitted_changes` prompt for log-only dirty states |
| `scripts/session_postflight.py` | Modify | Add `--token-budget` flag that calls `token_budget.py` and appends result to log; call it from `run_metrics()` alongside existing plan_audit and session_metrics calls |
| `.github/prompts/cron_review.prompt.md` | Modify | Add Step 4: read `logs/.token-budget-log.jsonl` tail (last 5 entries), flag if any `anomaly` field is `true`, surface recommendation if context file tokens exceed threshold |
| `.github/prompts/strategic_review.prompt.md` | Modify | Add to Step 6b-6 (Metrics Trend Analysis): read `logs/.token-budget-log.jsonl`, report per-file token trend and flag files approaching threshold; add to Strategic Review Report `### Token Budget` section |
| `logs/.token-budget-log.jsonl` | Create | Empty placeholder so gitignore/CI does not fail on missing file |
| `tests/test_token_budget.py` | Create | Unit tests: heuristic accuracy, threshold detection, JSONL append, graceful no-op when log missing |
| `tests/test_session_preflight.py` | Modify | Add tests for `log_sync` branch (log-only dirty → auto-commit; mixed dirty → skip; conflict → error result) |

## Acceptance Criteria
- [ ] `python scripts/token_budget.py` exits 0, prints JSON with per-file token estimates and anomaly flags, appends entry to `logs/.token-budget-log.jsonl`
- [ ] `python scripts/session_preflight.py` JSON output includes `token_anomalies` list (empty or populated) and `log_sync_result` dict
- [ ] When only `logs/*.jsonl` files are dirty on `main`, running preflight results in a `log_sync_result.status == "committed"` and a clean working tree
- [ ] When dirty files include non-log files, `log_sync_result.status == "skipped"` and existing `uncommitted_changes` handling is unchanged
- [ ] When `git push` during log sync fails due to conflict, `log_sync_result.status == "conflict"` and preflight prints stop instruction
- [ ] `plan.prompt.md` Step 0 handles `log_sync_result` correctly: silent pass on `committed`, STOP + triage message on `conflict`, no change to existing flow on `skipped`
- [ ] `session_postflight.py --metrics` output includes token budget summary
- [ ] `cron_review.prompt.md` Step 4 reads token log and surfaces anomalies
- [ ] `strategic_review.prompt.md` Step 6b-6 includes token pressure analysis
- [ ] All existing tests pass; new tests cover happy path and error paths
- [ ] `python scripts/validate.py` exits 0

## Constraints
- `tiktoken` must NOT be added to `requirements.txt` (CI dependency risk). Use a character-count heuristic (`len(text) / 4`) as the token estimator — this is the standard GPT approximation and requires no dependencies
- STDEV-based anomaly detection requires N >= 4 entries in the log (same pattern as `metrics_analysis.py`). Below that threshold, use a static high-water-mark warning threshold of **50,000 tokens** per individual context file (deliberately high to avoid false positives until baseline is established). Add a `REVIEW_THRESHOLD` recommendation comment in the script referencing Decision 29 pattern: once 4+ sessions of data exist, lower the static threshold to mean + 2*STDEV
- Log sync auto-commit must run only when on `main` branch (post-merge state). On a feature branch, skip silently — the existing `uncommitted_changes` handling covers that case
- Python 3.12+, stdlib only for `token_budget.py` (no new imports outside stdlib)
- No Docker, no AWS, no external network calls
- Branching rule: this is infra work, no direct commits to main

## Context
- Decision 29: Friction-Free Implementation Pattern — the log dirty state is a recurring friction point (observed this session and in prior preflight reports). Auto-sync closes this loop
- Decision 28: Execution State Checkpoint — established the pattern of `status` fields in preflight JSON for conditional handling in prompts
- Known Gotcha: `Windows subprocess encoding` — all subprocess calls must use `encoding='utf-8', errors='replace'`
- Known Gotcha: `sys.executable for subprocess in venv` — use `sys.executable` not `python`
- `metrics_analysis.py` already uses `mean`/`stdev` from stdlib `statistics` — same pattern applies here for STDEV threshold once baseline exists
- `session_postflight.py --log-housekeeping` already commits logs on a feature branch; the new `log_sync` in preflight handles the `main` branch post-merge case (separate use case, not duplication)
- `logs/.token-budget-log.jsonl` must be tracked (not gitignored) — same treatment as other log files

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Create `scripts/token_budget.py`**: stdlib-only script. Define `TOKEN_STATIC_THRESHOLD = 50_000`. Define `CONTEXT_FILES` list: `[".github/copilot_instructions.md", "docs/ROADMAP.md", "docs/DECISIONS.md", "docs/SESSION_LOG.md", "docs/RECOMMENDATIONS.md"]`. For each file that exists, read text, estimate tokens as `max(1, len(text) // 4)`. Build result dict per file: `{"file": path, "tokens": N, "chars": len(text), "anomaly": bool}`. Set `anomaly = True` if tokens > TOKEN_STATIC_THRESHOLD. Append JSONL entry to `logs/.token-budget-log.jsonl` with timestamp, per-file results, total tokens, and `anomaly_files` list. Print JSON summary to stdout. Add `if __name__ == "__main__"` entry point. Add a comment above `TOKEN_STATIC_THRESHOLD`: `# TODO(threshold-review): Replace with mean+2*stdev once logs/.token-budget-log.jsonl has 4+ entries. See Decision 29.`

2. **Create `logs/.token-budget-log.jsonl`**: empty file (single newline). This ensures the file is tracked by git and CI does not fail on missing file.

3. **Modify `scripts/session_preflight.py` — add `run_token_budget()` function**: call `subprocess.run([sys.executable, str(ROOT / "scripts" / "token_budget.py")], ...)` and parse stdout JSON. Return list of anomaly file names (empty list if none or script not found). Mirror pattern of `run_friction_analysis()`.

4. **Modify `scripts/session_preflight.py` — add `run_log_sync()` function**: (a) return `{"status": "skipped", "files": []}` immediately if current branch is not `main`; (b) run `git status --porcelain`; (c) parse dirty files — classify each as `log` (matches `logs/*.jsonl` or `logs/*.json`) or `other`; (d) if `other` list is non-empty, return `{"status": "skipped", "files": []}` (existing `uncommitted_changes` path handles it); (e) if log list is empty, return `{"status": "clean", "files": []}`; (f) stage log files with `git add` + commit with `"chore: sync session logs [auto]"`; (g) push with `git push`; (h) if push fails (non-zero return or "conflict" in stderr), return `{"status": "conflict", "files": log_list, "error": stderr}`; (i) return `{"status": "committed", "files": log_list}`.

5. **Modify `scripts/session_preflight.py` — wire into `main()`**: call `run_log_sync()` before `get_git_status()` (so the subsequent status check sees a clean tree after successful sync). Call `run_token_budget()` after `run_metrics_analysis()`. Add `"log_sync_result"` and `"token_anomalies"` keys to the `report` dict. Update `uncommitted_changes` logic: if `log_sync_result.status == "committed"`, force `uncommitted` to `False` (the sync cleaned the tree).

6. **Modify `.github/prompts/plan.prompt.md` — update Step 0 conditionals block**: after the `venv_ok: false` and `sso_status` blocks, add a new block before the `uncommitted_changes` block:
   ```
   - **`log_sync_result.status == "committed"`** — Log files were automatically committed and pushed to `main`. Print: "Session logs synced to main ([N] file(s) committed)." Continue — no action required.
   - **`log_sync_result.status == "conflict"`** — STOP. Print: "Log sync failed: push conflict on `main`. This requires manual triage before planning can proceed. Conflict details: [log_sync_result.error]". Do not proceed until the human resolves the conflict.
   ```
   Also add `token_anomalies` handling after `metrics_anomalies`:
   ```
   - **`token_anomalies` non-empty** — Surface as planning context: "Context file token warning: [file list] exceed the 50K token threshold. Consider context budget reduction before planning."
   ```

7. **Modify `scripts/session_postflight.py` — add `--token-budget` flag and `run_token_budget()` function**: the function calls `subprocess.run([sys.executable, str(ROOT / "scripts" / "token_budget.py")], ...)`, captures stdout, and returns exit code. Add `--token-budget` to the argparse group. In `run_metrics()`, after the existing plan_audit and session_metrics calls, also call `token_budget.py` and append its summary output to the metrics output.

8. **Modify `.github/prompts/cron_review.prompt.md` — add Step 4**: after the existing Step 3 (`--merge` script call), add:
   ```
   ## Step 4: Token Budget Check

   Read the last 5 entries from `logs/.token-budget-log.jsonl` (most recent lines). For each entry, check the `anomaly_files` list. If any file appears in `anomaly_files` in 2 or more of the last 5 entries, write a recommendation to `docs/RECOMMENDATIONS.md` Open table:
   - Source: `cron_review / token_budget`
   - Issue: "[filename] has exceeded the 50K-token static threshold in [N] of the last 5 sessions. Review context budget or lower the threshold using mean+2*stdev from `logs/.token-budget-log.jsonl`."
   - Date: today

   If no anomalies, print: "Token budget: all context files within threshold."
   ```

9. **Modify `.github/prompts/strategic_review.prompt.md` — extend Step 6b-6**: in the existing `### 6b-6: Metrics Trend Analysis` section, after the `metrics_analysis.py` call, add:
   ```
   Also read `logs/.token-budget-log.jsonl` (all entries). For each context file tracked, report:
   - Latest token count
   - Trend: increasing / stable / decreasing (compare first half vs second half of log)
   - Anomaly count (entries where `anomaly == true` for that file)

   Include in the Strategic Review Report under a `### Token Budget` subsection. If any file shows an increasing trend over 4+ sessions, recommend explicit context budget review (reduce file size or raise threshold with a data-backed value from mean+2*stdev).
   ```

10. **Create `tests/test_token_budget.py`**: tests covering: (a) `test_token_estimate_heuristic` — given a 4000-char string, estimate is 1000 tokens ± 1; (b) `test_anomaly_flag_above_threshold` — string with 200001 chars → anomaly True; (c) `test_anomaly_flag_below_threshold` — string with 100 chars → anomaly False; (d) `test_log_appended` — after calling main logic with tmp file paths, log file has one JSONL line with correct shape; (e) `test_missing_file_skipped` — if a context file does not exist, it is excluded from results without error.

11. **Modify `tests/test_session_preflight.py` — add `run_log_sync` tests**: add `TestLogSync` class with: (a) `test_log_sync_skipped_on_feature_branch` — mock branch = `agent/foo`, verify returns `{"status": "skipped"}`; (b) `test_log_sync_committed_when_only_logs_dirty` — mock `git status --porcelain` returns ` M logs/.friction-analysis-log.jsonl`, mock `git add`, `git commit`, `git push` return 0, verify `{"status": "committed"}`; (c) `test_log_sync_skipped_when_non_log_dirty` — dirty file = `src/main.py`, verify `{"status": "skipped"}`; (d) `test_log_sync_conflict_on_push_fail` — mock push returns non-zero, verify `{"status": "conflict"}`.

12. Run `pytest tests/test_token_budget.py tests/test_session_preflight.py -v` — all tests must pass.

13. Run `pytest tests/` — all existing tests must pass.

14. Run `python scripts/validate.py` — must exit 0.

15. Report what was implemented and any design decisions made during implementation.
