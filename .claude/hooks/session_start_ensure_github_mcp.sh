#!/usr/bin/env bash
# SessionStart hook: ensure the github-mcp-server binary is present.
#
# bin/setup-cloud-env.sh installs github-mcp-server only at snapshot-build time. A
# session booting from a snapshot built before that step existed (or before the
# pinned version changed) would lack the binary, leaving the repo-root .mcp.json
# `github-full` MCP server offline -- and the binary lives outside git, so a fresh
# checkout alone cannot supply it. This hook closes that gap by running the same
# idempotent installer every session: a present, correct-version binary is a
# millisecond no-op; otherwise it self-heals with a one-time download.
#
# Mirrors session_start_aws.sh: advisory only, always exits 0 so a failed or
# network-blocked install never blocks the session. Delegates to
# bin/ensure-github-mcp-server.sh (the source of truth shared with setup step 7).

set -uo pipefail

log() { printf '[session_start_ensure_github_mcp] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if out="$(bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh" 2>&1)"; then
    log "$out"
else
    log "WARNING: github-mcp-server ensure failed (non-fatal); the github-full MCP"
    log "  server stays offline until installed -- retries next session. Detail:"
    printf '%s\n' "$out" | while IFS= read -r line; do log "  $line"; done
fi

exit 0
