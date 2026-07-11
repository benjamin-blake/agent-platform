from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_ducklake_version_lockstep", owner="platform")
def validate_ducklake_version_lockstep(failed: list[str]) -> None:
    """Sub-second static gate: verify no derive surface diverges from config/lambda/ducklake/version.yaml.

    Checks:
    (a) requirements.txt duckdb floor == ">=<duckdb_version>" (sync_ducklake_version --check is clean).
    (b) No hardcoded duckdb version literal in src/common/ducklake_runtime.py or scripts/build_lambda.py
        (both must reach the pin only via the loader, not a literal).

    Eligible for both --pre fast-tier AND full presubmit (pure Python, sub-second).
    """
    print("\n=== DuckLake version lockstep gate (OQ.12 / PLAN-duckdb-pin-bump-1-5-4) ===")
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        import re as _re  # noqa: PLC0415

        # (a) requirements.txt floor check
        try:
            import scripts.sync.ducklake_version as _sdv  # noqa: PLC0415

            ok = _sdv.sync(check_only=True, requirements_path=_common.ROOT / "requirements.txt")
            if not ok:
                failed.append(
                    "ducklake-version-lockstep: requirements.txt duckdb floor drifts from "
                    "config/lambda/ducklake/version.yaml -- run: bin/venv-python -m scripts.sync.ducklake_version"
                )
                print("  FAIL: requirements.txt duckdb floor drifts from the SSOT.")
            else:
                print("  PASS: requirements.txt duckdb floor matches the SSOT.")
        except Exception as exc:
            failed.append(f"ducklake-version-lockstep: requirements check raised: {exc}")

        # (b) no hardcoded version literal in derive surfaces
        derive_surfaces = [
            _common.ROOT / "src" / "common" / "ducklake_runtime.py",
            _common.ROOT / "scripts" / "build_lambda.py",
        ]
        for surface in derive_surfaces:
            try:
                text = surface.read_text(encoding="utf-8")
            except OSError as exc:
                failed.append(f"ducklake-version-lockstep: cannot read {surface}: {exc}")
                continue
            # Allow version-looking strings in comments only if they look like semver but NOT as
            # a string assignment or constant value (i.e., PINNED_DUCKDB_VERSION = "x.y.z").
            literal_assigns = _re.findall(
                r'(?:PINNED_DUCKDB_VERSION\s*=\s*["\'])([\d.]+)(["\'])',
                text,
            )
            if literal_assigns:
                failed.append(
                    f"ducklake-version-lockstep: {surface.relative_to(_common.ROOT)} contains a hardcoded "
                    f"duckdb version literal assignment (PINNED_DUCKDB_VERSION = '...'). "
                    "Repoint through src.common.ducklake_version.pinned_duckdb_version()."
                )
                print(f"  FAIL: hardcoded version literal in {surface.name}.")
            else:
                print(f"  PASS: no hardcoded version literal assignment in {surface.name}.")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
