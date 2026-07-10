"""Shared primitives for the scripts.ops_portal package.

Sole source of ROOT / _REPO_ROOT / _SSO_PROFILE / _AWS_REGION (Decision 124, mirroring
the scripts/checks/_common.py precedent from Decision 104). No submodule recomputes
the repo root or these shared constants independently. This module has no dependency
on scripts.ops_data_portal so it never participates in a load-time import cycle.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT = _REPO_ROOT
_SSO_PROFILE = "agent_platform"
_AWS_REGION = "eu-west-2"
