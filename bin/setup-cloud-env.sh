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
# github-mcp-server binary installed by step 7 below). It reads a GitHub PAT at
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
#   .claude/hooks/session_start_precommit.sh -- re-wires the pre-commit .git hook (every session; .git/hooks does not survive a fresh clone).
#
# What it does:
#   1. Creates .venv with python3.12.
#   2. Installs uv (fast pip replacement); falls back to pip if install fails.
#   3. Installs runtime + dev requirements via uv (or pip).
#   4. Installs AWS CLI v2.
#   Steps 3 and 4 are parallelised: AWS CLI download runs in the background
#   while requirements install runs in the foreground.
#   5. (opt-in) Installs Terraform when INSTALL_TERRAFORM=1.
#   6. Installs the github-mcp-server binary (for the .mcp.json `github-full`
#      MCP server -- full GitHub toolset incl. Actions: workflow runs / job logs).
#   7. Pre-builds the pre-commit hook environments into ~/.cache/pre-commit so
#      the hooks (detect-secrets, ruff, file hygiene) run offline in later sessions.
#
# What it does NOT do:
#   - Materialise ~/.aws/{credentials,config} or ~/.config/gh-mcp/token (done by
#     the private "Setup script" field block above; this script only consumes them).
#   - Install gh CLI (GitHub access is via MCP -- see github-mcp-server, step 7 -- not gh).
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

# 4. Requirements (foreground, parallel with step 3) --------------------------
t0=$SECONDS
if command -v uv >/dev/null 2>&1; then
    log "Installing requirements.txt via uv"
    uv pip install --python .venv/bin/python -q -r requirements.txt
    if [ -f requirements-dev.txt ]; then
        log "Installing requirements-dev.txt via uv"
        uv pip install --python .venv/bin/python -q -r requirements-dev.txt
    fi
else
    log "uv unavailable -- falling back to pip"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r requirements.txt
    if [ -f requirements-dev.txt ]; then
        .venv/bin/python -m pip install --quiet -r requirements-dev.txt
    fi
fi
log "requirements: $((SECONDS - t0))s"

# 5. Wait for background AWS CLI install --------------------------------------
if [ -n "$aws_install_pid" ]; then
    t0=$SECONDS
    wait "$aws_install_pid"
    log "aws-cli-install: $((SECONDS - t0))s"
fi

# 6. Terraform (opt-in via INSTALL_TERRAFORM=1) -------------------------------
# Only the infrastructure (PlatformAdmin) cloud environment needs Terraform.
# Version is single-sourced from config/terraform-version (also read by the
# terraform-validate CI job in .github/workflows/ci.yml) so local
# `terraform fmt -check` / `validate` match CI exactly.
if [ "${INSTALL_TERRAFORM:-0}" = "1" ]; then
    TERRAFORM_VERSION="$(cat "$REPO_ROOT/config/terraform-version")"
    if command -v terraform >/dev/null 2>&1 && terraform version | head -1 | grep -q "v${TERRAFORM_VERSION}"; then
        log "Terraform ${TERRAFORM_VERSION} already present"
    else
        log "Installing Terraform ${TERRAFORM_VERSION}"
        t0=$SECONDS
        (
            tmpdir="$(mktemp -d)"
            trap 'rm -rf "$tmpdir"' EXIT
            curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o "$tmpdir/terraform.zip"
            unzip -q "$tmpdir/terraform.zip" -d "$tmpdir"
            mkdir -p "$HOME/.local/bin"
            install -m 0755 "$tmpdir/terraform" "$HOME/.local/bin/terraform"
        ) && log "terraform: $((SECONDS - t0))s ($(terraform version | head -1))" \
          || log "WARNING: Terraform install failed (non-fatal); install manually if needed."
    fi
else
    log "Terraform install skipped (set INSTALL_TERRAFORM=1 in the admin env to enable)"
fi

# 7. github-mcp-server (for the .mcp.json `github-full` MCP server) ------------
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

# 8. pre-commit hook environments (snapshot-cached) ---------------------------
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

log "Done. Verify with: bin/venv-python -m scripts.session_preflight"
