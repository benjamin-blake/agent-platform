"""Composite-action manifest template-expression guard (rec-2795 / rec-2796).

GitHub evaluates named-value contexts (``github.*``, ``env.*``) in composite-action metadata
at action LOAD time, before any step runs -- and ``github`` is unbound in that position, so a
stray ``${{ }}`` there fails the manifest load (root cause of the #683 incident, point-fixed by
#702/46b9fd9). The only LEGAL ``${{ }}`` positions in an action.yml are the entire ``runs:``
subtree (step-level expressions, evaluated at run time) and each ``outputs.<id>.value`` binding
(also run-time). Everything else is metadata -- flagged if it still contains ``${{``.
"""

from __future__ import annotations

import copy
from typing import Any

import yaml

from scripts.checks import _common, registry

_MANIFEST_GLOBS = ("action.yml", "action.yaml")


def _scan_manifest(data: Any) -> list[str]:
    """Return violation strings for every metadata `${{` found outside the legal positions.

    Legal positions -- exempted before the walk -- are the whole `runs:` subtree and each
    `outputs.<id>.value`. Everything else in the manifest is metadata.
    """
    if not isinstance(data, dict):
        return []

    scrubbed = copy.deepcopy(data)
    scrubbed.pop("runs", None)
    outputs = scrubbed.get("outputs")
    if isinstance(outputs, dict):
        for output in outputs.values():
            if isinstance(output, dict):
                output.pop("value", None)

    violations: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                _walk(value, f"{path}[{idx}]")
        elif isinstance(node, str) and "${{" in node:
            snippet_start = node.index("${{")
            snippet = node[snippet_start : snippet_start + 60]
            violations.append(f"{path}: {snippet}")

    _walk(scrubbed, "")
    return violations


@registry.register("validate_composite_action_manifests", owner="platform")
def validate_composite_action_manifests(failed: list[str]) -> None:
    """Lint every .github/actions/**/action.{yml,yaml} for metadata-position template expressions."""
    print("\n=== composite-action manifest guard ===")
    actions_dir = _common.ROOT / ".github" / "actions"
    manifest_paths = sorted(path for pattern in _MANIFEST_GLOBS for path in actions_dir.rglob(pattern))

    if not manifest_paths:
        print("  PASS: no composite-action manifests found")
        return

    for manifest_path in manifest_paths:
        rel = manifest_path.relative_to(_common.ROOT)
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  FAIL: {rel}: unparseable ({exc})")
            failed.append(f"composite-action manifest: {rel} unparseable")
            continue

        violations = _scan_manifest(data)
        if violations:
            print(f"  FAIL: {rel}: {len(violations)} metadata template-expression violation(s)")
            for violation in violations:
                print(f"    - {violation}")
                failed.append(f"composite-action manifest: {rel}: {violation}")
        else:
            print(f"  PASS: {rel}")
