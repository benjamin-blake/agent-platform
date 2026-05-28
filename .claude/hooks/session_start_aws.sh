#!/usr/bin/env bash
# SessionStart hook: materialise AWS SSO credentials from env vars.
# Runs on every Claude Code session start (including resume). Idempotent.
#
# Environment variables (all optional; missing = graceful skip):
#   AWS_SSO_CACHE_B64    -- base64-encoded tarball of ~/.aws/sso/cache/
#   AWS_SSO_START_URL    -- e.g. https://your-org.awsapps.com/start
#   AWS_SSO_ACCOUNT_ID   -- 12-digit account number
#   AWS_SSO_ROLE_NAME    -- e.g. DeveloperAccess
#   AWS_DEFAULT_REGION   -- e.g. eu-west-2
#
# Exits 0 on success or graceful skip; non-zero only on real I/O failure.

set -euo pipefail

log() { printf '[session_start_aws] %s\n' "$*"; }

# Block 1: SSO cache from AWS_SSO_CACHE_B64
if [ -n "${AWS_SSO_CACHE_B64:-}" ]; then
    log "Restoring AWS SSO cache from AWS_SSO_CACHE_B64"
    mkdir -p "$HOME/.aws/sso"
    chmod 700 "$HOME/.aws"
    printf '%s' "$AWS_SSO_CACHE_B64" | base64 -d | tar -C "$HOME/.aws/sso" -xzf -
    chmod -R go-rwx "$HOME/.aws/sso"
    log "SSO cache restored"
else
    log "AWS_SSO_CACHE_B64 not set -- skipping SSO cache restore"
fi

# Block 2: ~/.aws/config from AWS_SSO_* env vars
if [ -n "${AWS_SSO_START_URL:-}" ] && [ -n "${AWS_SSO_ACCOUNT_ID:-}" ] && [ -n "${AWS_SSO_ROLE_NAME:-}" ]; then
    log "Writing ~/.aws/config from AWS_SSO_* env vars"
    mkdir -p "$HOME/.aws"
    chmod 700 "$HOME/.aws"
    cat > "$HOME/.aws/config" <<EOF
[profile company-aws-profile]
sso_session = company-aws-profile
sso_account_id = ${AWS_SSO_ACCOUNT_ID}
sso_role_name = ${AWS_SSO_ROLE_NAME}
region = ${AWS_DEFAULT_REGION:-eu-west-2}
output = json

[sso-session company-aws-profile]
sso_start_url = ${AWS_SSO_START_URL}
sso_region = ${AWS_DEFAULT_REGION:-eu-west-2}
sso_registration_scopes = sso:account:access
EOF
    log "~/.aws/config written"
else
    log "AWS_SSO_START_URL/ACCOUNT_ID/ROLE_NAME not all set -- skipping ~/.aws/config write"
fi
