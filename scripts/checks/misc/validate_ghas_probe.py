"""GHAS live-probe: secret-scanning, push-protection, Actions-permissions (audit finding ULF-01).

Decision 83 recorded the T2.12 confidential-data-boundary controls as verified by Terraform
configuration only. This module closes the acknowledged live-probe gap with a single _probe()
implementation (Decision 80) and two deliberately different callers:

  1. validate_ghas_probe(failed) -- the registered validate.py CHECK. SKIP-when-unscoped: an
     absent token, an auth error, or a transport error prints SKIPPED and returns without
     appending (the normal CC-web/CI default has no token). A proven-disabled control appends
     to `failed`.
  2. _run_cli() -- the standing-workflow RUNNER (Decision 55 loud-fail). In that workflow the
     token is supposed to be present, so ANY inability to verify (token absent, auth error,
     transport error) is a non-zero exit, not a skip -- a rotated/expired/mis-scoped token must
     never read green-but-blind.

Control-state-only discipline (Decision 101): only status enums, booleans, and HTTP codes are
read and reported. Raw response bodies and the token itself are never printed or logged.
"""

from __future__ import annotations

import json
import os
import urllib.error
from urllib.request import Request, urlopen

from scripts.checks import registry

_API_BASE = "https://api.github.com"
_DEFAULT_REPO = "benjamin-blake/agent-platform"


class ProbeTokenMissing(Exception):
    """The probe token is not set in the environment."""


class ProbeAuthError(Exception):
    """The probe token was rejected (401/403)."""


class ProbeTransportError(Exception):
    """A non-auth HTTP error or network-transport failure occurred."""


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", _DEFAULT_REPO)


def _get(path: str, token: str) -> tuple[int, bytes]:
    request = Request(
        f"{_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ProbeAuthError(f"HTTP {exc.code}") from exc
        raise ProbeTransportError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ProbeTransportError(str(exc.reason)) from exc


def _probe(token: str | None) -> dict:
    """Query the three GHAS control surfaces. Returns a control-state dict; never a raw body."""
    if not token:
        raise ProbeTokenMissing("probe token not set")

    repo = _repo()

    repo_status, repo_body = _get(f"/repos/{repo}", token)
    repo_data = json.loads(repo_body)
    analysis = repo_data.get("security_and_analysis") or {}
    secret_scanning = (analysis.get("secret_scanning") or {}).get("status", "unknown")
    push_protection = (analysis.get("secret_scanning_push_protection") or {}).get("status", "unknown")

    actions_status, actions_body = _get(f"/repos/{repo}/actions/permissions", token)
    actions_data = json.loads(actions_body)
    actions_enabled = bool(actions_data.get("enabled", False))
    allowed_actions = actions_data.get("allowed_actions", "unknown")

    alerts_status, _alerts_body = _get(f"/repos/{repo}/secret-scanning/alerts", token)

    return {
        "secret_scanning": secret_scanning,
        "push_protection": push_protection,
        "actions_enabled": actions_enabled,
        "allowed_actions": allowed_actions,
        "repo_http_status": repo_status,
        "actions_http_status": actions_status,
        "alerts_http_status": alerts_status,
    }


def _disabled_controls(state: dict) -> list[str]:
    disabled = []
    if state["secret_scanning"] != "enabled":  # pragma: allowlist secret -- control-state enum, not a secret
        disabled.append(f"secret_scanning={state['secret_scanning']}")
    if state["push_protection"] != "enabled":
        disabled.append(f"push_protection={state['push_protection']}")
    if not state["actions_enabled"]:
        disabled.append("actions_enabled=False")
    return disabled


def _state_summary(state: dict) -> str:
    return (
        f"secret_scanning={state['secret_scanning']} push_protection={state['push_protection']} "
        f"actions_enabled={state['actions_enabled']} allowed_actions={state['allowed_actions']} "
        f"(repo_http_status={state['repo_http_status']} actions_http_status={state['actions_http_status']} "
        f"alerts_http_status={state['alerts_http_status']})"
    )


_TOKEN_ENV_VAR = "GHAS_PROBE_TOKEN"  # pragma: allowlist secret -- env var name, not a secret value


@registry.register("validate_ghas_probe", owner="platform")
def validate_ghas_probe(failed: list[str]) -> None:
    """Registered CHECK: skip-when-unscoped GHAS live-probe (CC-web/CI default has no token)."""
    print("\n=== GHAS live-probe (secret-scanning / push-protection / Actions permissions) ===")
    token = os.environ.get(_TOKEN_ENV_VAR)
    try:
        state = _probe(token)
    except ProbeTokenMissing:
        print("Probe token not set -- SKIPPED (expected default; the standing workflow carries it).")
        return
    except (ProbeAuthError, ProbeTransportError) as exc:
        print(f"Probe SKIPPED -- unable to verify ({exc}).")
        return

    disabled = _disabled_controls(state)
    if disabled:
        print(f"GHAS probe FAILED -- disabled control(s): {disabled}")
        failed.append(f"GHAS live-probe: disabled control(s) -- {disabled}")
    else:
        print(f"GHAS probe passed -- {_state_summary(state)}")


def _run_cli() -> int:
    """Standing-workflow RUNNER: loud-fail on any inability to verify (Decision 55)."""
    token = os.environ.get(_TOKEN_ENV_VAR)
    try:
        state = _probe(token)
    except ProbeTokenMissing as exc:
        print(f"GHAS probe LOUD-FAIL -- {exc}; the standing workflow requires it to be present.")
        return 1
    except ProbeAuthError as exc:
        print(f"GHAS probe LOUD-FAIL -- auth error, cannot verify: {exc}")
        return 1
    except ProbeTransportError as exc:
        print(f"GHAS probe LOUD-FAIL -- transport error, cannot verify: {exc}")
        return 1

    disabled = _disabled_controls(state)
    if disabled:
        print(f"GHAS probe LOUD-FAIL -- disabled control(s): {disabled}")
        return 1

    print(f"GHAS probe OK -- {_state_summary(state)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_run_cli())
