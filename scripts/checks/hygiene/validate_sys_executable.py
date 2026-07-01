from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_sys_executable", owner="platform")
def validate_sys_executable(failed: list[str]) -> None:
    """Check scripts use sys.executable instead of bare 'python'/'pip' in subprocess calls."""
    print("\n=== sys.executable lint ===")
    scripts_dir = _common.ROOT / "scripts"
    errors: list[str] = []

    pattern = re.compile(r"""\bsubprocess\.(run|Popen)\s*\(\s*\[\s*['\"](python|pip)['\"]""")

    for py_file in sorted(scripts_dir.glob("**/*.py")):
        content = py_file.read_text(encoding="utf-8")
        for m in pattern.finditer(content):
            line_num = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(_common.ROOT)
            errors.append(f"{rel}:{line_num}: Use sys.executable instead of '{m.group(2)}' in subprocess calls")

    if errors:
        print("sys.executable lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("sys.executable lint")
    else:
        print("All subprocess calls use sys.executable (no bare 'python'/'pip').")
