from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_subprocess_encoding", owner="platform")
def validate_subprocess_encoding(failed: list[str]) -> None:
    """Check that subprocess.run/Popen with text=True also specifies encoding=."""
    print("\n=== Subprocess encoding lint ===")
    scripts_dir = _common.ROOT / "scripts"
    errors: list[str] = []

    for py_file in sorted(scripts_dir.glob("**/*.py")):
        content = py_file.read_text(encoding="utf-8")
        for match in re.finditer(r"\bsubprocess\.(run|Popen)\(", content):
            start = match.end()
            depth = 1
            pos = start
            while pos < len(content) and depth > 0:
                if content[pos] == "(":
                    depth += 1
                elif content[pos] == ")":
                    depth -= 1
                pos += 1
            call_body = content[start : pos - 1]
            if re.search(r"\btext\s*=\s*True", call_body) and not re.search(r"\bencoding\s*=", call_body):
                line_num = content[: match.start()].count("\n") + 1
                rel = py_file.relative_to(_common.ROOT)
                errors.append(f"{rel}:{line_num}: subprocess.{match.group(1)} with text=True must specify encoding='utf-8'")

    if errors:
        print("Subprocess encoding lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Subprocess encoding lint")
    else:
        print("All subprocess calls with text=True specify encoding.")
