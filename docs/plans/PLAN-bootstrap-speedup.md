# Plan

## Intent
Cut Claude Code on the web (Linux container) bootstrap time from ~minutes to ~30-60s on first run and decouple AWS SSO credential rotation from the environment-cache lifecycle. North-Star contribution: makes the cloud dev surface fast enough to iterate cheaply (under the docs' 5-minute soft budget so the env snapshot actually caches) AND eliminates a latent staleness bug where the SSO refresh token baked into the snapshot can diverge from the live `AWS_SSO_CACHE_B64` env var until the ~7-day cache expiry.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
claude/test-plan-command-4fBUP (harness-mandated; not the canonical `agent/{slug}` naming because this session was launched on the harness branch)

## Phase
Platform tier T0 (Bootstrap surface). Follow-on to T0.1 / T0.11 (OS-aware venv wrapper + preflight Linux-generalisation, merged in PR #339) and T0.2 (Claude Code on the web env definition + setup script, merged in PR #342). This plan refines T0.2 in light of the Claude Code on the web environment-caching semantics documented at https://code.claude.com/docs/en/claude-code-on-the-web.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `bin/setup-cloud-env.sh` | Modify | (a) Install `uv` via the upstream static binary, replace `.venv/bin/python -m pip install` with `uv pip install --python .venv/bin/python` for both requirements files. (b) Parallelise the AWS CLI v2 download/install with the requirements install using `&` + `wait` (the pattern the docs explicitly recommend). (c) Remove the SSO cache restore block and the `~/.aws/config` write block; both move to the SessionStart hook below. (d) Add per-step `time` measurements so future regressions surface in setup logs. |
| `.claude/hooks/session_start_aws.sh` | Create | POSIX shell script invoked as a SessionStart hook on every session start (including resume). Idempotent. Reads `AWS_SSO_CACHE_B64`, `AWS_SSO_START_URL`, `AWS_SSO_ACCOUNT_ID`, `AWS_SSO_ROLE_NAME`, `AWS_DEFAULT_REGION` from env and materialises `~/.aws/sso/cache/*` plus `~/.aws/config`. Each section is independently guarded so a missing env var skips that section without failing the hook. No-op if env vars are absent. Exits 0 on success or graceful skip; non-zero only on real I/O failure. |
| `.claude/settings.json` | Modify | Register the new SessionStart hook under `hooks.SessionStart`. No other changes. |
| `bin/setup-cloud-env.sh` (header comment) | Modify | Update the docstring to reflect the new responsibility split: setup script handles cached-snapshot installs only; SSO + AWS config handled by SessionStart hook. Note the cloud-env panel's Setup script field should be `cd /home/user/agent-platform && bash bin/setup-cloud-env.sh` (or absolute path equivalent) — separately flagged because the field is not in-repo and cannot be edited by this PR. |

Four scope entries (one file edited in two sections counts as one). Under the IMPLEMENTATION soft-cap of 5.

## Bundled Recommendations
None. No open recs reference the cloud-env bootstrap surface.

## Infrastructure Dependencies
None. No `.tf` files. No Lambda-packaged files. The SessionStart hook runs in the Claude Code container only; it is not deployed anywhere.

## Acceptance Criteria
- [ ] `bash bin/setup-cloud-env.sh` on a clean container completes in under 60 seconds, measured via the script's own `time` output. (Wall-clock target; baseline was ~minutes per user observation.)
- [ ] `bash bin/setup-cloud-env.sh` is idempotent: a second invocation with `.venv/` already present completes in under 10 seconds and produces no errors.
- [ ] `bin/setup-cloud-env.sh` contains no reference to `AWS_SSO_CACHE_B64` or `~/.aws/config` (responsibility moved to the SessionStart hook).
- [ ] `.claude/hooks/session_start_aws.sh` exists, is `+x`, and `bash -n` reports clean syntax.
- [ ] Invoking the hook from a clean `$HOME` with all four `AWS_SSO_*` env vars set materialises `~/.aws/sso/cache/*.json` (at least one file) and `~/.aws/config` containing `[profile company-aws-profile]`.
- [ ] Invoking the hook with `AWS_SSO_CACHE_B64` unset and `AWS_SSO_START_URL` unset exits 0 and writes nothing.
- [ ] Invoking the hook with `AWS_SSO_CACHE_B64` set but `AWS_SSO_START_URL` unset exits 0, writes `~/.aws/sso/cache/`, but does not write `~/.aws/config`.
- [ ] `.claude/settings.json` parses as valid JSON (`bin/venv-python -c "import json; json.load(open('.claude/settings.json'))"`) and the `hooks.SessionStart` entry references the new hook.
- [ ] After the changes, `bin/venv-python -m scripts.session_preflight` still produces `sso_status: ok` in `logs/.preflight-report.json` on a container where the SessionStart hook has run.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-merge] | Static syntax check on both bash files | `bash -n bin/setup-cloud-env.sh && bash -n .claude/hooks/session_start_aws.sh && echo OK` | Prints `OK`; exit 0 | Syntax error reported -- fix the offending line |
| 2 | [pre-merge] | JSON validity of settings | `bin/venv-python -c "import json,sys; d=json.load(open('.claude/settings.json')); h=d.get('hooks',{}).get('SessionStart',[]); assert h, 'no SessionStart hook'; print('SessionStart hooks:', len(h))"` | Exit 0; prints at least 1 | Assertion failure -- fix the settings.json `hooks.SessionStart` array shape |
| 3 | [pre-merge] | Clean-slate bootstrap timing | `rm -rf .venv && /usr/bin/time -f '%E' bash bin/setup-cloud-env.sh 2>&1 \| tee /tmp/setup.log \| tail -20; grep -E '^\[setup\]' /tmp/setup.log` | Exit 0; total wall-clock under 60s; per-step `time` output present | Over budget -- profile each step; consider dropping `requirements-dev.txt` from snapshot path |
| 4 | [pre-merge] | Idempotency | `bash bin/setup-cloud-env.sh 2>&1 \| tee /tmp/setup2.log; grep -c 'already present' /tmp/setup2.log` | Exit 0; output contains the `.venv already present` and `AWS CLI already present` log lines; total wall-clock under 10s | Re-creating .venv or re-downloading AWS CLI -- the existence guards regressed |
| 5 | [pre-merge] | SSO hook full-path materialisation | Run in a subshell with isolated `$HOME`: `HOME=/tmp/awstest rm -rf /tmp/awstest && HOME=/tmp/awstest bash .claude/hooks/session_start_aws.sh && ls /tmp/awstest/.aws/sso/cache/ \| head -3 && grep '\[profile company-aws-profile\]' /tmp/awstest/.aws/config` | At least one cache JSON listed; the profile header line printed | Empty cache dir or no config -- check env-var presence and `tar -xzf` decoding |
| 6 | [pre-merge] | SSO hook full-skip path (no env vars) | `env -i HOME=/tmp/awstest2 PATH=/usr/bin:/bin bash .claude/hooks/session_start_aws.sh; ls /tmp/awstest2 2>&1` | Exit 0; `/tmp/awstest2` does not exist or contains no `.aws/` directory | Hook errored or wrote files despite missing vars -- tighten the env-var guards |
| 7 | [pre-merge] | SSO hook partial-skip path (cache only) | `env -i HOME=/tmp/awstest3 PATH=/usr/bin:/bin AWS_SSO_CACHE_B64="$AWS_SSO_CACHE_B64" bash .claude/hooks/session_start_aws.sh; ls /tmp/awstest3/.aws/ 2>&1` | Exit 0; `sso/` directory present; `config` file absent | Wrote `config` despite no `AWS_SSO_START_URL` -- separate the two guards |
| 8 | [pre-merge] | Preflight integration | `rm -rf ~/.aws && bash .claude/hooks/session_start_aws.sh && bin/venv-python -m scripts.session_preflight && bin/venv-python -c "import json; r=json.load(open('logs/.preflight-report.json')); assert r['sso_status']=='ok', r['sso_status']"` | Exits 0 | `sso_status != 'ok'` -- the hook produced incomplete `~/.aws/` state; compare against pre-change output of `bin/setup-cloud-env.sh` |

## Constraints
- 5-minute soft budget on setup-script runtime (per Claude Code on the web docs) -- exceeding it disables the env-cache snapshot and the slow setup will run every session.
- Custom base images are NOT supported by Claude Code on the web (verified in docs); all install work must go through the setup script or SessionStart hook.
- No `eval()` / `exec()`; only safe bash control flow.
- `~/.aws/sso/cache/` permissions must remain `go-rwx` (preserved from current script).
- The cloud-env panel's Setup script field is out-of-repo state and cannot be PR-modified. Document the recommended value in a follow-up README/runbook (deferred -- not in this plan's scope).
- No rescue agents or workaround loops (Decision 55).

## Context
- The setup script is cached automatically by Anthropic's snapshot mechanism after first successful run. Re-runs are triggered only by (a) setup-script text changes, (b) network-policy changes, (c) ~7-day cache expiry. Rotating `AWS_SSO_CACHE_B64` in the env-vars panel does NOT invalidate the snapshot -- this is the latent staleness bug the SessionStart-hook split fixes.
- `uv` is the only build-time tool added; not a Python runtime dep. Installed via the upstream `curl ... \| sh` one-liner (network policy: PyPI + GitHub releases, both on the Trusted allowlist). Falls back to pip if uv install fails (defensive -- one curl, two-line guard).
- The hook runs after Claude Code launches (per docs), so any `bin/venv-python` shell commands invoked by Claude in the session will already see fresh credentials.
- The current Setup script field text (`bash bin/setup-cloud-env.sh`) is failing at session start because the cloud-env runs setup-script bash in a CWD that is NOT the repo root. The runtime fix is editing the panel value to `cd /home/user/agent-platform && bash bin/setup-cloud-env.sh`. Out of repo, surfaced in the PR description as a manual step.
- **T0.5 coexistence:** the in-flight T0.5 work item plans a Python-based `.claude/hooks/session_start.py` for device-code SSO bootstrap. This plan's hook is intentionally named `session_start_aws.sh` (filename-distinct, single responsibility) so the two register as separate entries in `.claude/settings.json` -> `hooks.SessionStart` and compose cleanly when T0.5 lands. No file-level collision; verify by inspecting the SessionStart array in `.claude/settings.json` post-merge.
- No CI RCA recs open at the time of writing (per fresh preflight).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently `claude/test-plan-command-4fBUP`)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (relevant entries: Decision 67 Lambda-deferral; doesn't apply -- no Lambda files in scope)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Verified via `WebFetch` that the Claude Code on the web docs describe env caching, 5-min budget, SessionStart hook semantics, and absence of custom-image support

## Ordered Execution Steps
1. Modify `bin/setup-cloud-env.sh`:
   - Update header docstring (responsibility split + setup-field CWD note).
   - Install `uv` (curl one-liner, idempotent guard on `command -v uv`).
   - Replace pip install lines with `uv pip install --python .venv/bin/python -r ...`.
   - Wrap AWS CLI v2 install in a `(...) &` subshell, run uv installs in foreground; `wait` at the end.
   - Delete the SSO cache restore section and the `~/.aws/config` write section.
   - Wrap each major step with `time` so per-step durations land in the setup log.
2. Create `.claude/hooks/session_start_aws.sh`:
   - Bash, `set -euo pipefail`, `chmod +x` it.
   - Two independent guarded blocks: (a) `AWS_SSO_CACHE_B64` -> materialise cache; (b) `AWS_SSO_START_URL` + `AWS_SSO_ACCOUNT_ID` + `AWS_SSO_ROLE_NAME` -> write `~/.aws/config`. Preserve `chmod 700 ~/.aws` and `go-rwx` on the SSO cache.
3. Modify `.claude/settings.json`:
   - Add `hooks.SessionStart` array with one entry pointing at the new hook. Preserve all existing keys (permissions, statusLine, hooks.PreToolUse) byte-for-byte.
4. Execute Verification Plan: run steps 1-8 in order. Loop until all pass.
5. Commit changes on the working branch with a descriptive message. Do NOT push (the user has explicit gates around pushing).
6. Report: what was implemented, verification results, and the manual cloud-env-panel update the user still needs to do (CWD fix in the Setup script field).

## Known Gaps
- Updating the Setup script field in the cloud-env panel is a manual user action and cannot be automated from this PR.
- `uv` install via curl is a network dependency on the first run; falls back to pip if it fails, but no offline mirror.
- The hook does not validate that `AWS_SSO_CACHE_B64` decodes to a valid tar archive -- failures surface as a `tar` error and a non-zero hook exit. Acceptable per the no-defensive-validation rule; the script-defined error is informative enough.
