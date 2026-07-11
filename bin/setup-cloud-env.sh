#!/usr/bin/env bash
# Bootstrap a Claude Code on the web Linux container for this repo.
#
# Idempotent. Safe to re-run. Designed to be invoked from the "Setup script"
# field of the cloud environment configuration. On a personal Claude Code plan
# that field is private to you, so it is the correct home for the static-key
# credential block below (the env-var field is "visible to anyone using this
# environment" -- never put credentials there).
#
# DEV environment (PlatformDev) -- paste into the "Setup script" field, filling
# the <PLACEHOLDER> values from your local ~/.aws/credentials and ~/.aws/config:
#
#     set -euo pipefail
#     mkdir -p "$HOME/.aws" && chmod 700 "$HOME/.aws"
#
#     cat > "$HOME/.aws/credentials" <<'EOF'
#     [agent_static]
#     aws_access_key_id = <PLACEHOLDER>
#     aws_secret_access_key = <PLACEHOLDER>
#     EOF
#     chmod 600 "$HOME/.aws/credentials"
#
#     cat > "$HOME/.aws/config" <<'EOF'
#     [profile agent_static]
#     region = eu-west-2
#     output = json
#
#     [profile agent_platform]
#     role_arn = arn:aws:iam::<ACCOUNT_ID>:role/PlatformDev
#     source_profile = agent_static
#     external_id = <PLACEHOLDER>
#     duration_seconds = 36000
#     region = eu-west-2
#     output = json
#     EOF
#     chmod 600 "$HOME/.aws/config"
#
#     cd /home/user/agent-platform && bash bin/setup-cloud-env.sh
#
# boto3 then resolves the agent_platform profile and assumes PlatformDev,
# auto-refreshing the STS session from the agent_static key with no re-paste.
# Leave the env-var field EMPTY for the dev environment.
#
# ADMIN environment (PlatformAdmin, used rarely for infra) -- same block but the
# config profile is [profile agent_platform_admin] (role PlatformAdmin, its own
# external_id), and set these in the (non-secret) env-var field:
#     AWS_PROFILE=agent_platform_admin
#     INSTALL_TERRAFORM=1
#
# IMPORTANT: the "Setup script" field must include the `cd` prefix above, because
# the field runs bash from a working directory that is NOT the repo root.
# Changing the field value is a manual step (out-of-repo).
#
# GITHUB MCP (full toolset incl. Actions) -- GITHUB_MCP_PAT
# The repo-root .mcp.json defines a `github-full` GitHub MCP server (stdio; the
# github-mcp-server binary installed by step 6 below). It reads a GitHub PAT at
# runtime from ~/.config/gh-mcp/token. Supply that token via the PRIVATE "Setup
# script" field -- NOT the env-var field: a PAT is a credential and the env-var
# field is visible to anyone using the environment. Add this next to the ~/.aws
# block above, filling <PAT> from a fine-grained, read-only, single-repo
# (agent-platform), short-expiry GitHub token:
#
#     mkdir -p "$HOME/.config/gh-mcp"
#     cat > "$HOME/.config/gh-mcp/token" <<'EOF'
#     <PAT>
#     EOF
#     chmod 600 "$HOME/.config/gh-mcp/token"
#
# This keeps the token out of the process environment (mirrors the ~/.aws file
# pattern); the committed .mcp.json carries no secret. Changes apply to NEW
# sessions. (Alternative, not used: a remote http server in .mcp.json with
# `Authorization: Bearer ${GITHUB_MCP_PAT}` from the env-var field -- rejected
# because it puts the credential in the process environment.)
#
# Responsibility split (post T0.2 refactor):
#   setup-cloud-env.sh -- snapshot-cached installs (venv, deps, AWS CLI, optional Terraform, github-mcp-server, pre-commit hook envs).
#   .claude/hooks/session_start_aws.sh -- verifies the static-key assume-role chain (every session).
#   .claude/hooks/session_start_ensure_github_mcp.sh -- self-heals github-mcp-server on stale snapshots (every session).
#   .claude/hooks/session_start_sync_deps.sh -- self-heals requirements.txt/requirements-dev.txt (and terraform binary) drift on stale snapshots (every session).
#   .claude/hooks/session_start_precommit.sh -- re-wires the pre-commit .git hook (every session; .git/hooks does not survive a fresh clone).
#
# What it does:
#   1. Creates .venv with python3.12.
#   2. Installs uv (fast pip replacement); falls back to pip if install fails.
#   3. Installs AWS CLI v2.
#   4. Installs runtime + dev requirements, and (opt-in, INSTALL_TERRAFORM=1)
#      Terraform, via bin/sync-deps.sh -- also establishes the build-time
#      fingerprint so a freshly-built snapshot boots in-sync (no session-1
#      drift-install penalty). Steps 3 and 4 are parallelised: AWS CLI download
#      runs in the background while step 4 runs in the foreground.
#   5. Waits for the background AWS CLI install (step 3) to finish.
#   6. Installs the github-mcp-server binary (for the .mcp.json `github-full`
#      MCP server -- full GitHub toolset incl. Actions: workflow runs / job logs).
#   7. Pre-builds the pre-commit hook environments into ~/.cache/pre-commit so
#      the hooks (detect-secrets, ruff, file hygiene) run offline in later sessions.
#
# What it does NOT do:
#   - Materialise ~/.aws/{credentials,config} or ~/.config/gh-mcp/token (done by
#     the private "Setup script" field block above; this script only consumes them).
#   - Install gh CLI (GitHub access is via MCP -- see github-mcp-server, step 6 -- not gh).
#   - Install terraform unless INSTALL_TERRAFORM=1 (set only in the admin env).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '[setup] %s\n' "$*"; }

# 1. Python 3.12 venv ---------------------------------------------------------
t0=$SECONDS
if [ ! -x .venv/bin/python ]; then
    if ! command -v python3.12 >/dev/null 2>&1; then
        log "ERROR: python3.12 not found on PATH" >&2
        exit 1
    fi
    log "Creating .venv with $(python3.12 --version)"
    python3.12 -m venv .venv
else
    log ".venv already present ($(.venv/bin/python --version))"
fi
log "venv: $((SECONDS - t0))s"

# 2. uv install (idempotent) --------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    log "Installing uv"
    t0=$SECONDS
    curl -LsSf https://astral.sh/uv/install.sh | sh || true
    log "uv-install: $((SECONDS - t0))s"
fi

# 3. AWS CLI v2 (background) --------------------------------------------------
aws_install_pid=""
if ! command -v aws >/dev/null 2>&1; then
    (
        log "Installing AWS CLI v2 (background)"
        tmpdir="$(mktemp -d)"
        trap 'rm -rf "$tmpdir"' EXIT
        curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmpdir/awscliv2.zip"
        unzip -q "$tmpdir/awscliv2.zip" -d "$tmpdir"
        if [ "$(id -u)" -eq 0 ]; then
            "$tmpdir/aws/install" --update >/dev/null
        else
            sudo "$tmpdir/aws/install" --update >/dev/null
        fi
        log "AWS CLI installed: $(aws --version 2>&1)"
    ) &
    aws_install_pid=$!
else
    log "AWS CLI already present: $(aws --version 2>&1)"
fi

# 4. Requirements + terraform binary (foreground, parallel with step 3) ------
# Delegated to bin/sync-deps.sh -- the single dependency-sync code path shared
# with .claude/hooks/session_start_sync_deps.sh (every-session self-heal for a
# snapshot venv that predates a requirements*.txt change). This call also
# writes the fingerprint, so a freshly-built snapshot boots in-sync (no
# session-1 drift-install penalty). Installs requirements always; installs the
# terraform binary too when INSTALL_TERRAFORM=1 (admin container only).
t0=$SECONDS
bash "$REPO_ROOT/bin/sync-deps.sh"
log "sync-deps: $((SECONDS - t0))s"

# 5. Wait for background AWS CLI install --------------------------------------
if [ -n "$aws_install_pid" ]; then
    t0=$SECONDS
    wait "$aws_install_pid"
    log "aws-cli-install: $((SECONDS - t0))s"
fi

# 5b. Terraform provider filesystem_mirror sync (rec-2514, Decision 119 reversal mechanism) -------
# Terraform binary install (opt-in via INSTALL_TERRAFORM=1) is delegated to
# bin/sync-deps.sh at step 4 above -- this step only syncs the provider mirror.
# Only meaningful when terraform is installed (INSTALL_TERRAFORM=1, admin container). Syncs the
# S3-seeded mirror -- populated out-of-band by the ONLY egress-having actor,
# .github/workflows/terraform-provider-mirror-seed.yml -- so a proxy-blocked CC-web session can
# `terraform init` terraform/personal locally without the github.com checksum fetch Decision 119
# 403s. Resolves config/terraform/cc-web.tfrc's __TF_MIRROR_DIR__ placeholder into a copy at a
# fixed, deterministic path outside the repo (never mutates the git-tracked template in place).
#
# CRITICAL (plan-critique #3): the TF_CLI_CONFIG_FILE export is gated on a successful, NON-EMPTY
# sync -- exporting it unconditionally would exclude neon from `direct` while the mirror is
# empty/unsynced, producing a more confusing "provider not found in mirror and excluded from
# direct" failure than the known github.com 403. On sync failure: warn, do NOT export, do NOT fail
# the session -- the mirror is an enabler, never a hard session dependency; the pre-mirror
# CI-delegated posture (terraform/CLAUDE.md) remains the fallback.
#
# Per AGENTS.md ("each Bash tool invocation is independent" -- the bin/venv-python pattern): this
# export only affects this setup script's own process tree, not later independent Bash calls in a
# session. The resolved tfrc is written to the deterministic path logged below so any later
# terraform invocation can inline `TF_CLI_CONFIG_FILE=<path>` itself rather than depend on
# inherited shell state.
if [ "${INSTALL_TERRAFORM:-0}" = "1" ]; then
    t0=$SECONDS
    MIRROR_DIR="$HOME/.terraform-mirror"
    RESOLVED_TFRC="$MIRROR_DIR/cc-web.tfrc"
    if aws s3 sync "s3://agent-platform-data-lake/tf-provider-mirror/" "$MIRROR_DIR" --only-show-errors \
        && [ -n "$(ls -A "$MIRROR_DIR" 2>/dev/null)" ]; then
        sed "s|__TF_MIRROR_DIR__|${MIRROR_DIR}|g" "$REPO_ROOT/config/terraform/cc-web.tfrc" > "$RESOLVED_TFRC"
        export TF_CLI_CONFIG_FILE="$RESOLVED_TFRC"
        log "terraform-mirror-sync: $((SECONDS - t0))s (resolved tfrc: $RESOLVED_TFRC)"
    else
        log "WARNING: terraform provider mirror sync produced no local mirror (non-fatal); TF_CLI_CONFIG_FILE not set -- terraform/personal init falls back to the pre-mirror CI-delegated posture (terraform/CLAUDE.md)."
    fi
else
    log "Terraform provider mirror sync skipped (INSTALL_TERRAFORM != 1)"
fi

# 6. github-mcp-server (for the .mcp.json `github-full` MCP server) ------------
# Idempotent install delegated to bin/ensure-github-mcp-server.sh -- the single
# source of truth for the version pin + install logic. That script is also run
# every session by .claude/hooks/session_start_ensure_github_mcp.sh, so a
# container booted from a snapshot built before this step existed self-heals (the
# binary lives outside git, so a fresh checkout alone cannot supply it).
t0=$SECONDS
if out="$(bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh")"; then
    log "$out ($((SECONDS - t0))s)"
else
    log "WARNING: github-mcp-server install failed (non-fatal); the github-full MCP server stays offline until installed."
fi

# 7. pre-commit hook environments (snapshot-cached) ---------------------------
# pre-commit itself is installed via requirements-dev.txt (step 4). This pre-builds
# the hook repos (pre-commit-hooks, ruff-pre-commit, detect-secrets) into
# ~/.cache/pre-commit now -- while setup-time network is available -- so they are
# baked into the snapshot and run offline in later sessions, mirroring the AWS CLI
# and github-mcp-server caching above. The per-session .git/hooks wiring (which
# does NOT survive a fresh clone) is re-applied by
# .claude/hooks/session_start_precommit.sh.
t0=$SECONDS
if [ -x .venv/bin/pre-commit ]; then
    if .venv/bin/pre-commit install-hooks >/dev/null 2>&1; then
        log "pre-commit hook envs cached: $((SECONDS - t0))s"
    else
        log "WARNING: pre-commit install-hooks failed (non-fatal); hooks fetch lazily on first run."
    fi
else
    log "WARNING: .venv/bin/pre-commit missing (requirements-dev.txt not installed?); skipping hook cache."
fi

log "Done. Verify with: bin/venv-python -m scripts.session.preflight"
