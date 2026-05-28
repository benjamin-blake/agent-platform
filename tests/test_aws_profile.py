"""Tests for scripts.aws_profile.resolve_aws_profile.

The helper decides between a named ~/.aws/config profile (local / web dev) and
the boto3 default credential chain (Lambda execution role; GitHub-hosted OIDC
runner, which exports AWS_ACCESS_KEY_ID into the environment).
"""

from __future__ import annotations

import os
from unittest import mock

from scripts.aws_profile import resolve_aws_profile

_CREDENTIAL_ENV_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_LAMBDA_FUNCTION_NAME", "AWS_PROFILE")


def _env(**overrides: str) -> dict[str, str]:
    """A copy of os.environ with the credential-signal keys cleared, plus overrides."""
    base = dict(os.environ)
    for key in _CREDENTIAL_ENV_KEYS:
        base.pop(key, None)
    base.update(overrides)
    return base


def test_returns_none_when_oidc_env_credentials_present():
    with mock.patch.dict(os.environ, _env(AWS_ACCESS_KEY_ID="AKIAEXAMPLE"), clear=True):
        assert resolve_aws_profile(default="agent_platform") is None


def test_returns_none_in_lambda():
    with mock.patch.dict(os.environ, _env(AWS_LAMBDA_FUNCTION_NAME="some-fn"), clear=True):
        assert resolve_aws_profile(default="agent_platform") is None


def test_returns_named_default_when_no_env_credentials():
    with mock.patch.dict(os.environ, _env(), clear=True):
        assert resolve_aws_profile(default="agent_platform") == "agent_platform"


def test_aws_profile_env_takes_precedence_locally():
    with mock.patch.dict(os.environ, _env(AWS_PROFILE="custom-profile"), clear=True):
        assert resolve_aws_profile(default="agent_platform") == "custom-profile"


def test_explicit_override_used_locally():
    with mock.patch.dict(os.environ, _env(), clear=True):
        assert resolve_aws_profile("explicit-profile", default="agent_platform") == "explicit-profile"


def test_env_credentials_short_circuit_explicit_override():
    # On a hosted runner a named profile does not exist; ambient env creds must win
    # even if a caller passes an explicit profile.
    with mock.patch.dict(os.environ, _env(AWS_ACCESS_KEY_ID="AKIAEXAMPLE"), clear=True):
        assert resolve_aws_profile("explicit-profile", default="agent_platform") is None
