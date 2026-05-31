#!/usr/bin/env bash
# Idempotently ensure the github-mcp-server binary is installed at the pinned
# version. Single source of truth for the version pin + install logic, shared by:
#   - bin/setup-cloud-env.sh (step 7, runs at snapshot-build time)
#   - .claude/hooks/session_start_ensure_github_mcp.sh (runs every session, so a
#     container booted from a snapshot built before this binary/version existed
#     self-heals -- the binary lives outside git, so a fresh checkout alone cannot
#     supply it).
#
# The binary backs the repo-root .mcp.json `github-full` MCP server (full GitHub
# toolset incl. Actions: workflow runs / job logs) that the platform-managed
# connector lacks. api.github.com is proxy-blocked in the container, so the asset
# is pulled from the github.com release CDN directly at a pinned version.
#
# Idempotent: a present, correct-version binary short-circuits in milliseconds.
# Prints the outcome to stdout; progress/errors go to stderr. Exits non-zero on
# install failure -- callers decide whether that is fatal (both the setup script
# and the session hook treat it as non-fatal).
set -euo pipefail

GITHUB_MCP_SERVER_VERSION="1.1.2"
gh_mcp_bin="$HOME/.local/bin/github-mcp-server"

if "$gh_mcp_bin" --version 2>/dev/null | grep -q "Version: ${GITHUB_MCP_SERVER_VERSION}"; then
    echo "github-mcp-server ${GITHUB_MCP_SERVER_VERSION} already present"
    exit 0
fi

echo "Installing github-mcp-server ${GITHUB_MCP_SERVER_VERSION}" >&2
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
url="https://github.com/github/github-mcp-server/releases/download/v${GITHUB_MCP_SERVER_VERSION}/github-mcp-server_Linux_x86_64.tar.gz"
curl -fsSL "$url" -o "$tmpdir/gh-mcp.tar.gz"
tar -xzf "$tmpdir/gh-mcp.tar.gz" -C "$tmpdir"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$tmpdir/github-mcp-server" "$gh_mcp_bin"
echo "github-mcp-server ${GITHUB_MCP_SERVER_VERSION} installed"
