from __future__ import annotations

import re

from scripts.checks import _common, registry


def _is_inside_try(content: str, pos: int) -> bool:
    """Return True if position pos is nested inside any try() call (at any depth).

    Algorithm: walk backwards from pos tracking parenthesis depth. Every time a
    '(' is found while depth is 0, it is an enclosing call boundary. Check
    whether its identifier is exactly 'try' (word boundary enforced). If yes,
    return True. If not, keep depth at 0 and continue walking to find higher
    ancestors.

    Examples::

        try(filemd5("x"))              -> True  (direct parent)
        try(md5(file("x")))            -> True  (ancestor, not direct parent)
        filemd5("x")                   -> False (no enclosing try)
        retry(filemd5("x"))            -> False ('retry' is not 'try')
    """
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = content[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth > 0:
                depth -= 1
            else:
                # depth == 0: this ( is an enclosing call boundary
                preceding = content[max(0, i - 10) : i]
                if re.search(r"(?<![\w])try$", preceding):
                    return True
                # depth stays 0: continue looking for outer ancestors
        i -= 1
    return False


@registry.register("validate_terraform_try", owner="platform")
def validate_terraform_try(failed: list[str]) -> None:
    """Check that filemd5() and file() in .tf files are wrapped with try()."""
    print("\n=== Terraform try() lint ===")
    tf_dir = _common.ROOT / "terraform"
    errors: list[str] = []

    for tf_file in sorted(tf_dir.glob("*.tf")):
        content = tf_file.read_text(encoding="utf-8")
        for m in re.finditer(r"\bfilemd5\s*\(|(?<![\w])file\s*\(", content):
            if not _is_inside_try(content, m.start()):
                fn_name = "filemd5()" if "filemd5" in m.group() else "file()"
                line_num = content[: m.start()].count("\n") + 1
                errors.append(f"{tf_file.name}:{line_num}: {fn_name} must be wrapped in try() for CI compatibility")

    if errors:
        print("Terraform try() lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Terraform try() lint")
    else:
        print("All filemd5() and file() calls in terraform files are wrapped with try().")
