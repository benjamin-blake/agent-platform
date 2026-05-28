"""Extract src.* imports from Python files using AST parsing."""

import ast
import sys
from pathlib import Path


def extract_src_imports(file_path: Path) -> list[str]:
    """Return a list of src.* module names imported in *file_path*.

    Handles both:
      ``import src.X``
      ``from src.X import Y``

    Returns an empty list if the file has a syntax error or does not exist.
    The returned list contains unique module names, preserving order of first
    appearance.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, IOError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    seen: set[str] = set()
    results: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module == "src" or module.startswith("src."):
                    if module not in seen:
                        seen.add(module)
                        results.append(module)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "src" or module.startswith("src."):
                if module not in seen:
                    seen.add(module)
                    results.append(module)

    return results


def main() -> int:
    if len(sys.argv) < 2:
        return 0

    for arg in sys.argv[1:]:
        for module in extract_src_imports(Path(arg)):
            print(module)

    return 0


if __name__ == "__main__":
    sys.exit(main())
