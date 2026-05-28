"""Shared AWS profile resolution for boto3.Session(profile_name=...).

Centralises the choice between a named ~/.aws/config profile (local and
Claude-Code-on-the-web development) and the boto3 default credential chain
(AWS Lambda execution role; GitHub-hosted CI runners using OIDC, which export
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN into the
environment).

A named profile does not exist on a hosted runner or inside Lambda, so forcing
one raises botocore ProfileNotFound. Returning None lets boto3 fall through to
the ambient credentials in those environments while preserving the named-profile
behaviour for local and web development.
"""

from __future__ import annotations

import os

DEFAULT_SSO_PROFILE = "agent_platform"


def resolve_aws_profile(explicit: str | None = None, default: str | None = DEFAULT_SSO_PROFILE) -> str | None:
    """Return the profile name for boto3.Session(profile_name=...), or None for the default chain.

    Returns None when running in AWS Lambda (AWS_LAMBDA_FUNCTION_NAME set) or on a
    CI runner with environment credentials present (AWS_ACCESS_KEY_ID set) -- both
    must use the boto3 default credential chain, not a named profile. The env-credential
    check is intentionally evaluated first so a stray explicit override or AWS_PROFILE
    cannot reintroduce a ProfileNotFound on a hosted runner. Otherwise resolves the
    explicit override, then AWS_PROFILE, then the supplied default (local/web dev).
    """
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("AWS_ACCESS_KEY_ID"):
        return None
    return explicit or os.environ.get("AWS_PROFILE") or default
