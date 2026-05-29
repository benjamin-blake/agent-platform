#!/usr/bin/env bash
# SessionStart hook: verify the static-key AWS assume-role chain.
#
# Credential model (personal account, CC-web-primary): the cloud-env "Setup script"
# field materialises ~/.aws/{credentials,config} -- a near-powerless agent_static
# IAM key plus an agent_platform (PlatformDev) / agent_platform_admin (PlatformAdmin)
# assume-role profile. See bin/setup-cloud-env.sh header for the exact field content.
#
# This hook does NOT create credentials. It runs every session start (including
# resume) and verifies the chain resolves, turning a silent AccessDenied into an
# obvious session-start message. Advisory only: always exits 0 so a missing or
# expired credential never blocks the session.

set -uo pipefail

log() { printf '[session_start_aws] %s\n' "$*"; }

# Profile resolution mirrors scripts/aws_profile.py: an explicit AWS_PROFILE wins
# (the admin env sets agent_platform_admin), otherwise default to agent_platform.
PROFILE="${AWS_PROFILE:-agent_platform}"

if [ ! -f "$HOME/.aws/credentials" ] && [ ! -f "$HOME/.aws/config" ]; then
    log "WARNING: ~/.aws not materialised -- AWS calls will fail."
    log "  Fix: the cloud-env Setup script must write ~/.aws (see bin/setup-cloud-env.sh header)."
    exit 0
fi

if ! command -v aws >/dev/null 2>&1; then
    log "aws CLI not on PATH yet (setup-cloud-env.sh installs it) -- skipping credential check."
    exit 0
fi

log "Verifying AWS profile '$PROFILE' (static-key assume-role chain)..."
if arn="$(aws sts get-caller-identity --profile "$PROFILE" --query Arn --output text 2>&1)"; then
    log "OK: assumed $arn"
    log "  Note: get-caller-identity needs no IAM permissions. If ops calls still fail with"
    log "  AccessDenied, the role's runtime grant is missing -- see terraform/personal/platform_roles.tf."
else
    log "WARNING: could not assume '$PROFILE':"
    log "  $arn"
    log "  Check ~/.aws/config external_id and that the agent_static key is valid / un-rotated."
fi

exit 0
