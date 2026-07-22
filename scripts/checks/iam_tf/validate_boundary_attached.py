"""M2 boundary-attached gate (Decision 144 / T2.48, DEP-02).

Asserts that EVERY agent-platform-* aws_iam_role declared in terraform/personal carries
permissions_boundary = the mandatory agent-platform-github-ci-apply-boundary. A forgotten boundary
on a new or edited agent-platform-* role is caught at PR time -- closing the residual
approve-then-apply DEP-02 shape (a boundary-less role would guard-route to the gated Environment
which would then approve-then-AccessDeny). PlatformDev/PlatformAdmin are named PlatformDev/PlatformAdmin
(not agent-platform-*), so they are naturally outside this prefix scope; PlatformAdmin's exclusion
from the boundary is deliberate (control identity, Decision 144 pt.3).

Credential-free (pure text parsing) -- eligible for --pre and full tiers.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry
from scripts.checks.iam_tf import validate_invoke_implies_resolve as _vir

_PERSONAL_DIR_REL = Path("terraform") / "personal"
_BOUNDARY_NAME = "agent-platform-github-ci-apply-boundary"
_ROLE_PREFIX = "agent-platform-"

_ROLE_BLOCK_RE = re.compile(r'resource\s+"aws_iam_role"\s+"([a-zA-Z0-9_]+)"\s*\{')
_LOCALS_BLOCK_RE = re.compile(r"\blocals\s*\{")
_LOCAL_ASSIGN_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_NAME_RE = re.compile(r'\bname\s*=\s*("(?:[^"\\]|\\.)*"|local\.\w+)')
_LOCAL_REF_RE = re.compile(r"^local\.(\w+)$")


def _parse_locals(text: str, locals_map: dict[str, str]) -> None:
    for m in _LOCALS_BLOCK_RE.finditer(text):
        body = _vir._extract_block(text, m.end() - 1)
        for am in _LOCAL_ASSIGN_RE.finditer(body):
            locals_map[am.group(1)] = am.group(2)


def _resolve_name(raw: str, locals_map: dict[str, str]) -> str | None:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    m = _LOCAL_REF_RE.match(raw)
    if m:
        return locals_map.get(m.group(1))
    return None


@registry.register("validate_boundary_attached", owner="platform")
def validate_boundary_attached(failed: list[str]) -> None:
    """Assert every agent-platform-* aws_iam_role in terraform/personal declares the mandatory boundary."""
    print("\n=== Boundary-attached gate (M2 / Decision 144 -- agent-platform-* roles declare the boundary) ===")
    key = "boundary-attached:"
    personal_dir = _common.ROOT / _PERSONAL_DIR_REL
    tf_files = sorted(personal_dir.glob("*.tf"))
    if not tf_files:
        failed.append(f"{key} no .tf files under {personal_dir}")
        print("  FAIL: no terraform/personal .tf files found.")
        return

    # First pass: collect locals across all files (prod roles reference name via local.*_function).
    locals_map: dict[str, str] = {}
    texts: dict[str, str] = {}
    for p in tf_files:
        text = p.read_text(encoding="utf-8")
        texts[p.name] = text
        _parse_locals(text, locals_map)

    checked = 0
    for fname, text in texts.items():
        for m in _ROLE_BLOCK_RE.finditer(text):
            rname = m.group(1)
            body = _vir._extract_block(text, m.end() - 1)
            nm = _NAME_RE.search(body)
            resolved = _resolve_name(nm.group(1), locals_map) if nm else None
            if not resolved or not resolved.startswith(_ROLE_PREFIX):
                continue
            checked += 1
            if "permissions_boundary" not in body or _BOUNDARY_NAME not in body:
                failed.append(
                    f"{key} aws_iam_role {rname!r} (name {resolved!r}) in {fname} does not declare "
                    f"permissions_boundary = the mandatory {_BOUNDARY_NAME} (Decision 144 / DEP-02) -- "
                    "every agent-platform-* role must carry the boundary"
                )

    if not any(f.startswith(key) for f in failed):
        print(f"  PASS: all {checked} agent-platform-* roles in terraform/personal declare the boundary.")


if __name__ == "__main__":  # pragma: no cover
    _failed: list[str] = []
    validate_boundary_attached(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
