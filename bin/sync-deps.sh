#!/usr/bin/env bash
# Single source of truth for dependency sync: fingerprints requirements.txt +
# requirements-dev.txt against .venv/.requirements-fingerprint and reinstalls via
# uv (pip fallback) only on drift. When INSTALL_TERRAFORM=1 also self-heals
# terraform binary drift against config/terraform-version.
#
# Shared by bin/setup-cloud-env.sh (snapshot-build time, establishes the
# build-time fingerprint) and .claude/hooks/session_start_sync_deps.sh (every
# session -- the repo is cloned fresh each session but the venv is baked into
# the snapshot, so requirements*.txt can be newer than the baked venv).
#
# Idempotent and non-fatal (mirrors bin/ensure-github-mcp-server.sh): the
# common in-sync case is a fingerprint hash compare (cheap, no reinstall). On
# any install failure: warn, do NOT write the fingerprint (so the next run
# retries), and still exit 0 -- a failed sync never aborts a session.
#
# Usage: bin/sync-deps.sh [--check]
#   --check: report drift status only; never installs, never writes the
#            fingerprint. Exit 0 = in sync, exit 1 = drift detected.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '[sync-deps] %s\n' "$*"; }

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=1
fi

FINGERPRINT_FILE=".venv/.requirements-fingerprint"
REQ_FILES=(requirements.txt requirements-dev.txt)

compute_fingerprint() {
    sha256sum "${REQ_FILES[@]}" 2>/dev/null | sha256sum | awk '{print $1}'
}

current_fp="$(compute_fingerprint)"
stored_fp=""
if [ -f "$FINGERPRINT_FILE" ]; then
    stored_fp="$(cat "$FINGERPRINT_FILE" 2>/dev/null || true)"
fi

py_drift=0
if [ -z "$stored_fp" ] || [ "$current_fp" != "$stored_fp" ]; then
    py_drift=1
fi

tf_drift=0
if [ "${INSTALL_TERRAFORM:-0}" = "1" ]; then
    TERRAFORM_VERSION="$(cat "$REPO_ROOT/config/terraform-version")"
    if command -v terraform >/dev/null 2>&1 && terraform version | head -1 | grep -q "v${TERRAFORM_VERSION}"; then
        tf_drift=0
    else
        tf_drift=1
    fi
fi

if [ "$CHECK_ONLY" = "1" ]; then
    if [ "$py_drift" = "1" ] || [ "$tf_drift" = "1" ]; then
        log "drift detected (python=$py_drift terraform=$tf_drift)"
        exit 1
    fi
    log "in sync"
    exit 0
fi

if [ "$py_drift" = "0" ] && [ "$tf_drift" = "0" ]; then
    log "in sync, nothing to do"
    exit 0
fi

fail=0

if [ "$py_drift" = "1" ]; then
    if [ ! -x .venv/bin/python ]; then
        if command -v python3.12 >/dev/null 2>&1; then
            log "creating .venv with python3.12 (drift: no venv)"
            python3.12 -m venv .venv || { log "WARNING: venv creation failed"; fail=1; }
        else
            log "WARNING: python3.12 not found on PATH; cannot create .venv"
            fail=1
        fi
    fi

    if [ "$fail" = "0" ]; then
        export PATH="$HOME/.local/bin:$PATH"
        if command -v uv >/dev/null 2>&1; then
            log "installing requirements.txt via uv (drift detected)"
            if ! uv pip install --python .venv/bin/python -q -r requirements.txt; then
                fail=1
            fi
            if [ "$fail" = "0" ] && [ -f requirements-dev.txt ]; then
                log "installing requirements-dev.txt via uv (drift detected)"
                if ! uv pip install --python .venv/bin/python -q -r requirements-dev.txt; then
                    fail=1
                fi
            fi
        else
            log "uv unavailable -- falling back to pip"
            if ! .venv/bin/python -m pip install --quiet -r requirements.txt; then
                fail=1
            fi
            if [ "$fail" = "0" ] && [ -f requirements-dev.txt ]; then
                if ! .venv/bin/python -m pip install --quiet -r requirements-dev.txt; then
                    fail=1
                fi
            fi
        fi

        if [ "$fail" = "1" ]; then
            log "WARNING: requirements install failed (non-fatal)"
        fi
    fi
fi

if [ "$tf_drift" = "1" ]; then
    TERRAFORM_VERSION="$(cat "$REPO_ROOT/config/terraform-version")"
    log "installing terraform ${TERRAFORM_VERSION} (drift detected)"
    tmpdir="$(mktemp -d)"
    if curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o "$tmpdir/terraform.zip" \
        && unzip -q "$tmpdir/terraform.zip" -d "$tmpdir" \
        && mkdir -p "$HOME/.local/bin" \
        && install -m 0755 "$tmpdir/terraform" "$HOME/.local/bin/terraform"; then
        log "terraform ${TERRAFORM_VERSION} installed"
    else
        log "WARNING: terraform install failed (non-fatal)"
        fail=1
    fi
    rm -rf "$tmpdir"
fi

if [ "$fail" = "0" ]; then
    mkdir -p .venv
    printf '%s' "$current_fp" > "$FINGERPRINT_FILE"
    log "sync complete, fingerprint updated"
else
    log "sync incomplete due to failure(s) above; fingerprint NOT updated (will retry next run)"
fi

exit 0
