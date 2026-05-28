#!/usr/bin/env bash
# Bootstrap a Claude Code on the web Linux container for this repo.
#
# Idempotent. Safe to re-run. Designed to be invoked from the "Setup script"
# field of the cloud environment configuration:
#
#     cd /home/user/agent-platform && bash bin/setup-cloud-env.sh
#
# IMPORTANT: the cloud-env panel's "Setup script" field must include the `cd`
# prefix above, because the field runs bash from a working directory that is
# NOT the repo root. Changing the field value is a manual step (out-of-repo).
#
# Responsibility split (post T0.2 refactor):
#   setup-cloud-env.sh                  -- snapshot-cached installs only (venv, deps, AWS CLI)
#   .claude/hooks/session_start_aws.sh  -- SSO cache + ~/.aws/config (runs every session)
#
# What it does:
#   1. Creates .venv with python3.12.
#   2. Installs uv (fast pip replacement); falls back to pip if install fails.
#   3. Installs runtime + dev requirements via uv (or pip).
#   4. Installs AWS CLI v2.
#   Steps 3 and 4 are parallelised: AWS CLI download runs in the background
#   while requirements install runs in the foreground.
#
# What it does NOT do:
#   - Restore AWS SSO cache (moved to .claude/hooks/session_start_aws.sh).
#   - Write ~/.aws/config (moved to .claude/hooks/session_start_aws.sh).
#   - Install gh CLI (GitHub access is via MCP, not gh).
#   - Install terraform (only needed when .tf is in scope; install on demand).

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

log "Done. Verify with: bin/venv-python -m scripts.session_preflight"
