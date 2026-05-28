# Plan

## Intent
Unblock Claude Code on the web (Linux container) as a usable dev surface by introducing OS-aware venv resolution and Linux-generalising session preflight. North-Star contribution: shifts the primary dev surface off the Windows VM per CD.2, enabling later reduction of Windows-prescriptive instruction bloat (T0.14) and decommission of host-specific accommodations.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/linux-container-bootstrap

## Phase
Platform tier T0 (Bootstrap surface + account + minimum tooling). Bundles tier_items T0.1 (OS-aware venv-path resolution) and T0.11 (session_preflight.py Linux-generalisation). Retroactively flips T-1.0 and T0.10 — both substantively complete in PR #338 but not yet marked.

## Scope

Override note: 7 files exceeds the default IMPLEMENTATION soft-cap of 5. Override is justified because (a) Decision 67 bars STRATEGIC plans, (b) the files form a single tight cluster all touching one OS-detection refactor, (c) the roadmap groups them under two adjacent tier_items (T0.1 and T0.11), and (d) splitting would leave T0.1 verifiable only structurally — V2 verification requires the preflight path generalisation in T0.11 to be in the same commit.

| File | Action | Purpose |
|------|--------|---------|
| `bin/venv-python` | Create | POSIX shell wrapper that picks `.venv/bin/python` on Linux/macOS or `.venv/Scripts/python.exe` on Windows. Single source of truth for venv-Python invocation. |
| `.claude/settings.json` | Modify | Replace 4 hardcoded `.venv/Scripts/python.exe` occurrences: `permissions.allow` entry (`Bash(.venv/Scripts/python.exe:*)` -> `Bash(bin/venv-python:*)`), `statusLine.command`, and 2 PreToolUse hook commands. |
| `scripts/session_preflight.py` | Modify | Remove `MAIN_REPO_VENV` Windows-path constant; replace `_is_correct_venv()` Path equality check with a same-tree heuristic. Update SSO recovery to call `aws sso login --use-device-code` when `DISPLAY` is unset (Linux container has no browser). |
| `CLAUDE.md` | Modify | Update the venv-path line in the "Shell invocations on Windows" section to reference `bin/venv-python` as the canonical wrapper. Section reframing (full OS-agnostic rewrite) remains T0.14 scope and is not in this plan. |
| `tests/test_session_preflight.py` | Modify | Update tests that reference `MAIN_REPO_VENV` or assert on the old SSO subprocess call signature. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Flip status `not_started` → `complete` and add `completed_at` for T0.1, T0.11 (this plan), T-1.0, T0.10 (retroactive). |
| `.claude/statusline.py` | Verify only | Inspected — does not invoke a Python venv; only shells out to `git`. Listed in T0.1 `files_in_scope` per the roadmap but requires no edit. Verification Plan step 2 confirms it still renders correctly under the new `bin/venv-python` invocation. |

## Bundled Recommendations
None. The Linux-container migration cluster predates the recommendation backlog as a roadmap-tier work item rather than ad-hoc rec. Adjacent rec `rec-656` (build_lambda Unicode crash on Windows) is not bundled — different surface and different failure mode.

## Infrastructure Dependencies
None. No `.tf` files in scope. `docs/ROADMAP-PLATFORM.yaml` IS Lambda-packaged (copied into the Lambda zip by `scripts/build_lambda.py`), but it is non-executable documentation content -- it ships as a context payload for the scheduled-agent dispatcher, not as code or configuration that the Lambda runtime executes. Decision 67's deferral clause targets functional triggers (handlers, prompts, schedule.yaml, code in `config/`); a status flip on a tier_item does not exercise any deployed code path. Therefore no `DEFERRED: build_lambda.py --deploy ...` step is required.

## Acceptance Criteria
- [ ] `bin/venv-python -c "import sys; print(sys.executable)"` exits 0 and prints a path ending in `.venv/bin/python` (Linux/macOS) or `.venv/Scripts/python.exe` (Windows).
- [ ] `bin/venv-python -m scripts.session_preflight --pre` produces a fresh `logs/.preflight-report.json` with `venv_ok: true` on the current host.
- [ ] `git grep -n '\.venv/Scripts/python\.exe' .claude/settings.json scripts/session_preflight.py CLAUDE.md` returns zero hits (literal Windows path eliminated from the 4 critical call sites named in T0.1 `files_in_scope`).
- [ ] `MAIN_REPO_VENV` symbol no longer exists in `scripts/session_preflight.py` (`git grep -n MAIN_REPO_VENV scripts/` returns zero hits).
- [ ] `pytest tests/test_session_preflight.py -q` passes on the working branch.
- [ ] Editing any file on `main` is still blocked (`never_on_main.py` hook fires correctly via the new wrapper).
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses via the roadmap Pydantic schema if T-1.5 has landed (graceful pass-through if not); T0.1, T0.11, T-1.0, T0.10 each carry `status: complete` and `completed_at` ISO-8601 string.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-merge] | Exercise the wrapper directly | `bin/venv-python -c "import sys; print(sys.executable)"` | Exit 0; stdout path ends in `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Linux | Non-zero exit or stdout points outside `.venv` -- wrapper OS detection broken; inspect `uname -s` branch logic |
| 2 | [pre-merge] | Confirm statusline still renders via rewired settings.json | `bash -c '.venv/Scripts/python.exe .claude/statusline.py 2>&1; echo "EXIT=$?"'` then re-run via `bin/venv-python .claude/statusline.py` and assert both produce identical output | Both invocations print `agent/linux-container-bootstrap` (current branch) with `EXIT=0` | Output empty or `EXIT=1` -- statusline cannot resolve git; wrapper-vs-direct discrepancy means the wrapper diverges from `sys.executable` semantics |
| 3 | [pre-merge] | Exercise preflight end-to-end via the wrapper | `bin/venv-python -m scripts.session_preflight --pre` then `python -c "import json; r = json.load(open('logs/.preflight-report.json')); assert r['venv_ok'] is True, r"` | Preflight completes; assertion passes | `venv_ok: false` -- `_is_correct_venv()` heuristic rejects the new resolution path; review same-tree comparison logic |
| 4 | [pre-merge] | Unit tests cover the new resolution + SSO recovery branches | `bin/venv-python -m pytest tests/test_session_preflight.py -q` | All tests pass; new tests cover (a) wrapper-resolved venv detected as correct, (b) `--use-device-code` chosen when `DISPLAY` unset, (c) interactive `aws sso login` chosen when `DISPLAY` set | Any failure -- read the assertion; missing branch coverage means add the test case before re-running |
| 5 | [pre-merge] | never_on_main hook fires via rewired settings.json | `git checkout main && echo "test" >> CLAUDE.md` (expect block) then `git checkout - && git restore CLAUDE.md` | Hook prints a block message and the Edit/Write tool would refuse. Stage 2 restores branch. | If write succeeds on main, the PreToolUse hook command in settings.json is broken; check `bin/venv-python` resolved path matches what the hook expects |
| 6 | [pre-merge] | Roadmap YAML still parses if Pydantic schema present | `bin/venv-python -c "from pathlib import Path; import yaml; d = yaml.safe_load(Path('docs/ROADMAP-PLATFORM.yaml').read_text()); ids = {i['id']: i for i in d['tier_items']}; assert ids['T0.1']['status'] == 'complete' and ids['T0.11']['status'] == 'complete' and ids['T-1.0']['status'] == 'complete' and ids['T0.10']['status'] == 'complete'"` | Exits 0 | `KeyError` or `AssertionError` -- the bookkeeping edit missed a field; re-inspect the YAML diff |
| 7 | [pre-merge] | Critical-call-site Windows-path eradication | `git grep -nE '\.venv/Scripts/python\.exe' -- .claude/settings.json scripts/session_preflight.py CLAUDE.md` | Zero output (exit code 1 from grep meaning no matches) | Any hit -- a call site was missed; replace with `bin/venv-python` |
| 8 | [pre-merge] | Full validate.py presubmit | `bin/venv-python -m scripts.validate --pre` | Exit 0 | Investigate failure; if Pydantic roadmap schema rejects an edit, fix the YAML field shape |

## Constraints
- No Lambda-packaged files in scope; Decision 67 deferral clause does not apply.
- No STRATEGIC plans (Decision 67 / CLAUDE.md Temporary Operational Constraints); this plan is IMPLEMENTATION with file-count override justification documented in the Scope table.
- Never edit on `main` -- this plan develops on `agent/linux-container-bootstrap` only. The `.claude/hooks/never_on_main.py` hook itself is being rewired by this work; agent must remain on the working branch throughout.
- Authoritative pre-merge gate is remote CI (Decision 68). Local `validate.py --pre` is advisory.
- No rescue agents or workaround loops (Decision 55) -- if V2 fails, stop and analyse root cause.
- Memory policy (CLAUDE.md): do not write to auto-memory. Roadmap status flips happen via direct edit to `docs/ROADMAP-PLATFORM.yaml`, not via memory.
- Agent-First: no human-readable companion document is created. The plan itself is the only narrative artefact; outcomes flow back into `docs/ROADMAP-PLATFORM.yaml` and `docs/SESSION_LOG.md`.

## Context
- Originating briefing: `docs/plans/briefings/BRIEFING-linux-container-migration.md` (2026-05-17, written from inside Claude Code on the web). Sections 3.2, 3.3, and 5.3 are the source of the file inventory in Scope.
- Roadmap tier_items: T0.1 (`docs/ROADMAP-PLATFORM.yaml` line ~792) and T0.11 (line ~1017). Both `depends_on: []` after T0.1 lands; eligible to start now per the bootstrap clause (T0 items with `depends_on: []` start in the bootstrap window).
- Candidate Decisions: CD.2 (Dev surface = Claude Code on the web; Windows VM exits) -- pending ratification via log-decision Lambda (T0.7b). Per bootstrap clause, pending CDs are binding; this plan honors CD.2 without waiting for ratification.
- Decision 57 (Interactive vs Autonomous SSO): preflight is interactive -- attempt auto-login or prompt human. The `--use-device-code` branch keeps this interactive-but-browser-free, satisfying both interactive-recovery and headless-Linux constraints.
- Prior-art reference: `PLAN-agent-first-foundation.md` uses the same file-count override pattern (more than 5 files justified by tight thematic cluster).
- Retroactive bookkeeping rationale: T-1.0 exit criteria (no live `docs/ROADMAP.md` references) verified zero hits outside committed PLAN-*.md history (excluded by the criterion). T0.10 exit criteria (`.pre-commit-config.yaml` exists) verified. Both substantively complete in PR #338 but the `status:` field was not flipped in that PR.
- Out-of-scope follow-ons (named for future plans, not done here): T0.14 (Windows-assumption sweep across `scripts/`, `src/`, agent instruction files; reframes CLAUDE.md "Shell invocations on Windows" as OS-agnostic); T0.9 (AGENTS.md sidecar); T0.2 (CC-on-web env definition + setup script -- requires user action in Anthropic web UI); T0.5 (SessionStart hook) which depends on T0.2 + T0.3.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` returns `agent/linux-container-bootstrap`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/DECISIONS.md` read (specifically: 55, 57, 67, 68, 73).
- [ ] `docs/plans/briefings/BRIEFING-linux-container-migration.md` read end-to-end.
- [ ] `docs/ROADMAP-PLATFORM.yaml` tier_items T0.1 and T0.11 read; bootstrap clause in `agent_instructions` read.
- [ ] All 7 files in Scope table located and readable.
- [ ] Acceptance Criteria understood and each maps to a Verification Plan step.

## Ordered Execution Steps

1. **Create `bin/venv-python` wrapper.** POSIX shell script (works in Git Bash on Windows and bash on Linux). Resolves the repo root from its own location (`REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"`) so the wrapper functions correctly regardless of the caller's CWD -- critical because hooks and statusline may invoke from any subdirectory. Branches on `uname -s`: `MINGW*`/`MSYS*`/`CYGWIN*` -> `exec "$REPO_ROOT/.venv/Scripts/python.exe" "$@"`; otherwise `exec "$REPO_ROOT/.venv/bin/python" "$@"`. Exits non-zero with a clear diagnostic if neither path exists. Set executable bit (`chmod +x`). Lives at repo root under `bin/`.

2. **Rewire `.claude/settings.json`.** Replace the 4 occurrences of `.venv/Scripts/python.exe` with `bin/venv-python`. Concretely: (a) the `permissions.allow` entry `Bash(.venv/Scripts/python.exe:*)` becomes `Bash(bin/venv-python:*)` so the auto-approval list still matches the rewired invocations; (b) `statusLine.command`; (c) and (d) both PreToolUse hook command entries (currently invoking `.claude/hooks/never_on_main.py` and `.claude/hooks/scheduled_agent_log_only.py`). Preserve the rest of the settings file verbatim.

3. **Generalise `scripts/session_preflight.py`.** Replace `MAIN_REPO_VENV = Path("C:/Users/bblake/...")` with a same-tree heuristic: resolve `sys.executable`, walk parents until a `.venv` directory is found, compare against `ROOT / ".venv"`. Delete the constant. **Preserve the existing `repo_name in sys.executable` fallback** -- worktrees share a central venv at the main-repo path, and removing that branch would break Windows worktree workflows. The new logic: accept if the resolved venv is `ROOT / ".venv"` OR matches the repo-name fallback. Update `_handle_sso_startup()`: detect headless (`os.environ.get("DISPLAY") is None and sys.platform != "win32"`) and append `--use-device-code` to the `aws sso login` argv when headless. Add a one-line comment citing CD.2 above the change (this is one of the rare cases where a `Why:` comment is justified -- the conditional looks arbitrary without it).

4. **Update `CLAUDE.md`.** In the "Shell invocations on Windows" section, change the canonical-invocation line from `.venv/Scripts/python.exe ...` to `bin/venv-python ...`. Do not rewrite the surrounding prose -- that is T0.14 scope. Add a single line below noting "Linux container sessions: same invocation; the wrapper resolves to `.venv/bin/python`."

5. **Update `tests/test_session_preflight.py`.** Search for `MAIN_REPO_VENV` references (line 40-44 mock the constant); replace with assertions on the same-tree heuristic. Add four new test cases: (a) wrapper-resolved Python at `ROOT / ".venv"` detected as correct, (b) Windows worktree fallback (`sys.executable` outside `ROOT / ".venv"` but matching repo-name heuristic) still detected as correct, (c) `--use-device-code` injected when `DISPLAY` unset and platform != win32, (d) interactive form preserved when `DISPLAY` set OR platform == win32.

6. **Bookkeep `docs/ROADMAP-PLATFORM.yaml`.** For each of T0.1, T0.11, T-1.0, T0.10: change `status: not_started` to `status: complete` and add `completed_at: "2026-05-19"` immediately below the `status:` line. Use today's date for T0.1 and T0.11; use today's date for T-1.0 and T0.10 too (the retroactive flip is happening today even if the substantive work landed in PR #338 -- the YAML's `completed_at` reflects when the field was set, with the actual merge SHA captured in git blame).

7. **Execute Verification Plan.** Run each numbered step in `Verification Plan` in order. Loop on individual failures (fix and rerun the failing step only). If V2 fails unrecoverably at the same step twice in a row, stop and analyse the root cause (Decision 55); do not rescue-loop.

8. **Report.** Append a `## [2026-05-19] - implement: agent/linux-container-bootstrap` entry to `docs/SESSION_LOG.md` summarising: files touched, verification outcomes, any anomalies. Then run `bin/venv-python -m scripts.session_postflight --close-session --outcome success`.
