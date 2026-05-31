# Plan: GitHub MCP full toolset on Claude Code on the web

## Intent
Add a git-committed `.mcp.json` at the repo root so Claude Code on the web gains the
**full GitHub MCP toolset** -- in particular the GitHub **Actions** tools (workflow runs,
job logs, artifacts) that the platform-managed GitHub connector does NOT expose. The
server authenticates with a user-supplied GitHub Personal Access Token; **no token value
is ever committed to the repo**. Document the token's placement in `bin/setup-cloud-env.sh`
so the operator knows exactly which cloud-environment field to use.

North-Star contribution: gives the web dev surface first-class CI introspection (read
failing job logs directly instead of inferring from PR check status), which tightens the
`subscribe_pr_activity` -> diagnose -> fix loop.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1 (configuration + documentation; static validation only -- JSON parse, `bash -n`, grep
assertions. The live MCP connection is NOT assertable at implement time because the token
does not exist yet; a manual post-activation check is listed separately.)

## Branch
`claude/beautiful-noether-GKx4U` (harness-assigned session branch; not `agent/{slug}`).

## Phase
Dev-surface tooling on the Claude Code on the web bootstrap surface (T0-adjacent, same
surface as `bin/setup-cloud-env.sh`). Not roadmap-gated; no product/platform roadmap item
is consumed or advanced.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `.mcp.json` | Create | Repo-root project MCP config defining a `github-full` GitHub MCP server. Contains only `${GITHUB_MCP_PAT}` interpolation (Option A) or a token-file read command (Option B) -- never a literal token. |
| `bin/setup-cloud-env.sh` | Modify (header) | Add a documented block telling the operator where to set the PAT (env-var field vs Setup-script file), mirroring the existing AWS block. Under Option B, also add an idempotent `github-mcp-server` binary install to the executable body (snapshot-cached, same pattern as the AWS CLI install). |
| `docs/PROJECT_CONTEXT.md` | Modify (1 line) | Fix the stale "GitHub MCP config" router row that still points at the deleted `.vscode/mcp.json` (line ~166) -> point at `.mcp.json`. Confirmed by decision-scout as a free dangling-reference fix (no decision protects it). |

Three scope entries. Within IMPLEMENTATION soft-cap.

## Decision Required: where the PAT lives (A vs B)

This is the load-bearing choice. The committed `.mcp.json` carries **no secret either way**;
the difference is purely where the token value is stored in the cloud-environment config.

| | Option A -- env-var field (remote server) | Option B -- Setup-script file (local binary) |
|---|---|---|
| `.mcp.json` shape | `type: http`, remote `https://api.githubcopilot.com/mcp/`, header `Authorization: Bearer ${GITHUB_MCP_PAT}` | stdio `command` that reads `~/.config/gh-mcp/token` and execs the local `github-mcp-server` binary |
| Token stored in | **Environment variables** field (labelled "visible to anyone using this environment -- don't add secrets or credentials") | **Setup script** field (private), as a `chmod 600` file -- identical to how `~/.aws/credentials` is materialised today |
| Setup-script body change | None (header doc only) | Adds an idempotent `github-mcp-server` install (like the AWS CLI install) |
| Token reaches | the **process environment** of every session -> visible to any `env`/`printenv` by Claude, a subagent, or a crashing subprocess (and thus the transcript/logs) | only the MCP launcher, read on demand from a 600-perm file -- never enters the process environment |
| Convention fit | Breaks the script header's "never put credentials there" rule and the Decisions 49/37 "GitHub PAT is a managed secret" precedent | Convention-consistent; mirrors the established AWS file pattern |
| Network policy | OK -- environment is on **Full** network access | OK -- same; binary calls `api.github.com` |

**Recommendation: Option B** on principle (lower leakage surface, convention-consistent,
and the AWS block already demonstrates the file pattern two lines up in the same field).

**Operator signal: the user has indicated Option A is acceptable** on the grounds that this
is a single-user personal account, so the "visible to anyone using this environment" vector
is effectively nil. That reasoning is sound for the multi-user vector. The residual
consideration is process-environment exposure (row "Token reaches" above), which "single
user" does not address. With a **fine-grained, read-only, single-repo, short-expiry** PAT
the blast radius is small under either option, so Option A is a legitimate choice for this
account. This plan documents **Option A as the primary path** (per the operator signal) with
the mandatory risk note below, and Option B as a fully-specified alternative.

### Option A compensating controls (MANDATORY if A is chosen) -- per CD.20 / decision-scout
- The PAT MUST be fine-grained, **Actions: Read-only** + **Metadata: Read-only** only (add
  Contents: Read-only only if artifact download is wanted), scoped to the single repo
  `benjamin-blake/agent-platform`, with a 30-90 day expiry and a rotation reminder.
- Risk note recorded here: Option A places a credential in the env-var field that
  `bin/setup-cloud-env.sh` and Anthropic's own field label mark non-secret. Because **CD.20**
  defers GHAS secret-scanning + push protection, there is no automated backstop; the
  "no token in the repo" invariant and the field choice are enforced by operator discipline.
  The minimal-scope/read-only/short-expiry token is the compensating control (same
  reasoning shape as Decision 77 clause 3).

## Decisions to Cite
- **Decision 76** -- web GitHub MCP toolset is the canonical GitHub transport; a richer
  GitHub MCP server is a direct in-domain extension. Governing rationale for *why*.
- **CD.20** -- push protection deferred on the public repo; the "no secret ever committed"
  invariant is author-discipline-only and MUST be asserted statically (VP step 2).
- **Decisions 49 / 37** (precedent, RELATED) -- GitHub PAT is treated as a managed secret,
  never a public field. Option B honours this; Option A deviates (hence the risk note).
- **Decision 77** (RELATED) -- compensating-control reasoning pattern for a deferred GitHub
  security control; the Option A risk note follows its shape.
- **Decision 67** -- verified NON-applicable (neither file is Lambda-packaged); no DEFERRED
  step required.

## Infrastructure Dependencies
None. No `.tf` files. No Lambda-packaged files. The MCP server runs only inside the Claude
Code web container.

## Acceptance Criteria
- [ ] `.mcp.json` exists at repo root, parses as valid JSON, defines exactly one server
      named `github-full`, and is NOT gitignored.
- [ ] `.mcp.json` contains the string `${GITHUB_MCP_PAT}` (Option A) or the token-file read
      command (Option B), and contains **no** literal token (no `ghp_`, no `github_pat_`).
- [ ] `bin/setup-cloud-env.sh` header documents the PAT placement for the chosen option and
      preserves the existing "never put credentials in the env-var field" general rule
      (Option A's exception is explicitly bounded to a minimal-scope GitHub PAT).
- [ ] (Option B only) `bin/setup-cloud-env.sh` installs `github-mcp-server` idempotently and
      `command -v github-mcp-server` succeeds after a run.
- [ ] `bash -n bin/setup-cloud-env.sh` is clean.
- [ ] `docs/PROJECT_CONTEXT.md` "GitHub MCP config" row points at `.mcp.json`, not
      `.vscode/mcp.json`.
- [ ] `python -m scripts.validate --pre` passes locally (lint/format/prompts), then full
      `validate.py` / CI is authoritative.
- [ ] (Manual, post-activation) After the operator sets the PAT and starts a NEW session,
      the `github-full` server connects and exposes Actions tools (a workflow-run / job-log
      tool is listed); fetching logs for a recent CI run succeeds.

## Verification Plan

| # | Phase | Action | Command | Expected | Fix If |
|---|-------|--------|---------|----------|--------|
| 1 | [pre-merge] | `.mcp.json` JSON validity + shape | `bin/venv-python -c "import json; d=json.load(open('.mcp.json')); s=d['mcpServers']; assert list(s)==['github-full'], list(s); print('ok', list(s))"` | Prints `ok ['github-full']` | Fix JSON / server name |
| 2 | [pre-merge] | No literal token committed (CD.20) | `bin/venv-python -c "t=open('.mcp.json').read(); bad=[m for m in ('ghp_','github_pat_') if m in t]; assert not bad, bad; assert ('GITHUB_MCP_PAT' in t) or ('gh-mcp/token' in t), 'no token ref'; print('clean')"` | Prints `clean` | A literal token leaked in -- remove it |
| 3 | [pre-merge] | `.mcp.json` not gitignored | `git check-ignore -v .mcp.json && echo IGNORED || echo TRACKED` | Prints `TRACKED` | Add a `.gitignore` negation `!.mcp.json` |
| 4 | [pre-merge] | Setup script syntax | `bash -n bin/setup-cloud-env.sh && echo OK` | Prints `OK` | Fix the offending line |
| 5 | [pre-merge] | Header documents placement | `grep -q 'GITHUB_MCP_PAT' bin/setup-cloud-env.sh && echo OK` | Prints `OK` | Add the documented block |
| 6 | [pre-merge] | (Option B) binary install present + idempotent | `grep -q 'github-mcp-server' bin/setup-cloud-env.sh && bash bin/setup-cloud-env.sh >/dev/null 2>&1 && command -v github-mcp-server` | Prints a path | Add/fix the install block |
| 7 | [pre-merge] | Router pointer fixed | `! grep -q 'vscode/mcp.json' docs/PROJECT_CONTEXT.md && grep -q ']\(\.\./\.mcp.json\|\.mcp.json' docs/PROJECT_CONTEXT.md; echo done` | Old pointer gone | Re-edit the router row |
| 8 | [post-activation, MANUAL] | Live tools appear | Operator sets PAT, starts NEW session, then in-session run `/mcp` (or attempt a workflow-run/job-log tool) | `github-full` connected; Actions tools listed; a real CI run's logs fetch | See "Known Gaps" troubleshooting |

## Operator Instructions: create and set `GITHUB_MCP_PAT`

### 1. Create the PAT (GitHub UI)
GitHub -> **Settings** -> **Developer settings** -> **Personal access tokens** ->
**Fine-grained tokens** -> **Generate new token**:
- **Token name:** `claude-code-web-mcp`
- **Expiration:** 30-90 days (set a rotation reminder)
- **Resource owner:** your personal account
- **Repository access:** Only select repositories -> `benjamin-blake/agent-platform`
- **Repository permissions** (minimal set for CI log access):
  - **Actions: Read-only** (workflow runs + job logs) -- the whole point
  - **Metadata: Read-only** (auto-required)
  - *Optional:* Contents: Read-only (artifact download); Pull requests / Issues
    (the managed connector already covers these -- leave off to reduce duplication)
- Generate and copy the token (`github_pat_...`).

### 2a. Set it -- Option A (env-var field)
In the **Update cloud environment** dialog (`DEV`) -> **Environment variables**, add a line
under the existing `AWS_PROFILE=agent_platform`:
```
GITHUB_MCP_PAT=github_pat_xxxxxxxxxxxxxxxxxxxx
```
Click **Save changes**. The dialog notes "Changes apply to new sessions" -- start a NEW
session for it to take effect. (See the Option A risk note above: keep this token
minimal-scope/read-only/short-expiry.)

### 2b. Set it -- Option B (Setup script field, file)
In the **Setup script** field, *below* the existing `~/.aws/credentials` block, add:
```bash
mkdir -p "$HOME/.config/gh-mcp"
cat > "$HOME/.config/gh-mcp/token" <<'EOF'
github_pat_xxxxxxxxxxxxxxxxxxxx
EOF
chmod 600 "$HOME/.config/gh-mcp/token"
```
Click **Save changes**, then start a NEW session. The committed setup script installs the
`github-mcp-server` binary; `.mcp.json` reads the token from this file at launch.

### 3. Verify
New session -> run `/mcp`. The `github-full` server should be connected and list Actions
tools. Ask Claude to fetch logs for a recent CI run to confirm end to end.

## Artifacts (exact content for implementation)

### `.mcp.json` -- Option A (primary)
```json
{
  "mcpServers": {
    "github-full": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${GITHUB_MCP_PAT}",
        "X-MCP-Toolsets": "all"
      }
    }
  }
}
```
Note: the default `/mcp/` endpoint already enables the Actions toolset; `X-MCP-Toolsets: all`
is belt-and-suspenders. Verify the exact toolset header/path against current
github-mcp-server remote docs at implement time. If the remote server rejects the
fine-grained PAT, fall back to a classic PAT (`repo` + `workflow`) or switch to Option B.

### `.mcp.json` -- Option B (alternative)
```json
{
  "mcpServers": {
    "github-full": {
      "command": "bash",
      "args": [
        "-lc",
        "export GITHUB_PERSONAL_ACCESS_TOKEN=\"$(cat \"$HOME/.config/gh-mcp/token\")\"; exec github-mcp-server stdio --toolsets all"
      ]
    }
  }
}
```

### `bin/setup-cloud-env.sh` header block (both options documented; general rule preserved)
Add after the ADMIN block, before "Responsibility split":
```
# GITHUB MCP (full toolset incl. Actions) -- GITHUB_MCP_PAT
# The repo-root .mcp.json defines a `github-full` GitHub MCP server. Provide a
# fine-grained, read-only, single-repo, short-expiry GitHub PAT one of two ways:
#
#   Option A (env-var field): add to the env-var field:
#       GITHUB_MCP_PAT=github_pat_xxx
#     EXCEPTION to the "never put credentials in the env-var field" rule above,
#     bounded strictly to a minimal-scope GitHub PAT on a single-user account.
#     The token enters the process environment; keep scope/expiry minimal. CD.20:
#     no push-protection backstop, so this is operator-discipline-enforced.
#
#   Option B (Setup script field, preferred): materialise a file like ~/.aws above:
#       mkdir -p "$HOME/.config/gh-mcp"
#       printf '%s' '<PAT>' > "$HOME/.config/gh-mcp/token"; chmod 600 "$HOME/.config/gh-mcp/token"
#     Keeps the token out of the process environment (mirrors the ~/.aws pattern).
#     This script installs the github-mcp-server binary below for Option B.
```
(Option B additionally adds an idempotent `github-mcp-server` install step to the executable
body, modelled on the AWS CLI install in step 3, writing to `$HOME/.local/bin`.)

## Constraints
- No literal token in any committed file (CD.20; push protection deferred).
- Preserve the setup-script header's general "never put credentials in the env-var field"
  rule; Option A is documented as an explicitly-bounded exception, not a loosening.
- Setup-script runtime stays under the ~5-minute snapshot-cache budget (Option B's binary
  download is one cached install, comparable to the AWS CLI step).
- `.github/copilot-instructions.md` also references `.vscode/mcp.json` but lives under the
  deep-frozen `.github/` tree -- do NOT edit it (out of scope; note as a recommendation).
- Adding `github-full` means GitHub PR/issue tools exist on both the managed connector and
  the new server. Harmless, but to cut tool-count noise the operator may later scope
  `X-MCP-Toolsets` / `--toolsets` to just the gaps (e.g. `actions`).

## Context
- The platform-managed GitHub connector exposes PR/issue/repo/search/`subscribe_pr_activity`
  tools but **no Actions tools** (verified against the live tool list this session) -- the
  reason CI logs are currently unreadable.
- No `.mcp.json` exists today; `~/.claude.json` `mcpServers` is empty -- confirming the
  managed connector is platform-injected, not file-configured.
- Environment `DEV` is on **Full** network access (per the operator's screenshot), so both
  the remote `api.githubcopilot.com` endpoint and Option B's `api.github.com` calls reach.
- New MCP servers from `.mcp.json` trigger a one-time workspace-trust prompt on the next
  session; tools will prompt for permission unless `mcp__github-full__*` is added to
  `.claude/settings.json` `permissions.allow` (optional follow-up, not required).
- Decision-scout gate run this session: Verdict FLAGS_FOUND (one NOTE, confined to Option A;
  resolved by the compensating-control note above). No BLOCK.

## Ordered Execution Steps
1. Confirm the PAT-placement choice (A or B) with the operator.
2. Create `.mcp.json` with the chosen option's content (no literal token).
3. Edit `bin/setup-cloud-env.sh`: add the header block (both options documented). For
   Option B, add the idempotent `github-mcp-server` install to the executable body.
4. Fix the `docs/PROJECT_CONTEXT.md` router pointer (`.vscode/mcp.json` -> `.mcp.json`).
5. Run Verification Plan steps 1-7 (and 6 only if Option B). Loop until green.
6. `python -m scripts.validate --pre`, then commit on the session branch.
7. Hand the operator the "Operator Instructions" section; they create + set the PAT and run
   VP step 8 (manual post-activation) in a fresh session.

## Known Gaps
- VP step 8 (live tools) cannot run at implement time -- the token does not exist yet. It is
  an operator action in a fresh session.
- The cloud-environment fields (env-var / Setup script) are out-of-repo state; this plan
  cannot edit them. The operator does that via the dialog.
- If the remote server (Option A) rejects a fine-grained PAT, fall back to a classic
  `repo`+`workflow` PAT or switch to Option B (the local binary accepts fine-grained PATs).
- `.github/copilot-instructions.md`'s stale `.vscode/mcp.json` reference is left as a
  recommendation (deep-frozen tree).
