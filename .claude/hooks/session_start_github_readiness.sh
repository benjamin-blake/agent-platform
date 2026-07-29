#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if ! bin/venv-python -m scripts.session.github_readiness; then
    echo "[session_start_github_readiness] WARNING: capability probe failed; GitHub readiness is degraded"
fi
exit 0
