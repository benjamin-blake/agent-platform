#!/usr/bin/env bash
# SessionStart hook: force-sync the local 'main' ref to origin/main every session.
#
# GitHub squash-merges PRs server-side (Decision 76), so feature-branch commits
# never land on the local main history via a fast-forward. A container that sat
# through several squash-merges ends up with local main diverged from
# origin/main with NO merge base -- consumers that diff against bare 'main'
# (e.g. scripts/checks/misc/validate_scheduled_agent_logs.py) then hit
# "fatal: no merge base" and silently skip. Force-updating (not pulling) local
# main to exactly origin/main each session closes that gap. Safe by
# construction: committing to local main is forbidden (CLAUDE.md hard rule +
# never_on_main.py PreToolUse + Decision 138), so local main never holds real
# work to lose.
#
# Advisory only, like session_start_sync_deps.sh: always exits 0 so a
# network-blocked fetch never blocks session start.

set -uo pipefail

log() { printf '[session_start_sync_main] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT" || exit 0

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "not a git repository; skipping"
    exit 0
fi

if ! git fetch origin main --quiet 2>/dev/null; then
    log "WARNING: git fetch origin main failed (non-fatal); local main may be stale this session"
    exit 0
fi

if ! git rev-parse --verify --quiet origin/main >/dev/null; then
    log "WARNING: origin/main did not resolve after fetch (non-fatal)"
    exit 0
fi

current_branch="$(git branch --show-current 2>/dev/null || true)"
if [ "$current_branch" = "main" ]; then
    log "on main; not force-updating the checked-out branch ref"
    exit 0
fi

if git branch -f main origin/main >/dev/null 2>&1; then
    log "local main synced to origin/main ($(git rev-parse --short origin/main))"
else
    log "WARNING: git branch -f main origin/main failed (non-fatal)"
fi

exit 0
