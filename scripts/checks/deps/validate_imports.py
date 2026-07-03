"""Executor-module import-smoke validation (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_imports", owner="platform")
def validate_imports(failed: list[str]) -> None:
    """Validate that new executor modules can be imported successfully."""
    print("\n=== Import validation (executor modules) ===")
    import importlib.util
    import sys

    modules = [
        ("execute_recommendation", _common.ROOT / "scripts" / "execute_recommendation.py"),
        ("classify_risk", _common.ROOT / "scripts" / "classify_risk.py"),
    ]
    errors: list[str] = []
    # Ensure repo root is in sys.path so intra-package imports (e.g. from scripts.x) resolve
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        for module_name, module_path in modules:
            if not module_path.exists():
                errors.append(f"{module_name}: file not found at {module_path}")
                print(f"  X {module_name}: file not found")
                continue
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                print(f"  OK {module_name}")
            except Exception as e:
                errors.append(f"{module_name}: {e}")
                print(f"  ERROR {module_name}: {e}")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    if errors:
        failed.append("Import validation")
    else:
        print(f"All {len(modules)} executor modules import successfully.")
