"""Extract src.* imports from Python files using AST parsing."""

import ast
import sys
from pathlib import Path

_DEFAULT_REPO_ROOT = Path(__file__).parent.parent


def _resolve_relative_import(
    file_path: Path,
    level: int,
    module: str | None,
    roots: tuple[str, ...],
    repo_root: Path | None = None,
) -> str | None:
    """Resolve a relative import to an absolute first-party module name, or None.

    level=1 means current package (one dot); level=2 means parent package (two dots).
    """
    actual_root = repo_root if repo_root is not None else _DEFAULT_REPO_ROOT
    for root in roots:
        base = actual_root / root
        try:
            rel = file_path.resolve().relative_to(base.resolve())
        except ValueError:
            continue
        parts = [root] + list(rel.parent.parts)
        if level > len(parts):
            return None
        base_parts = parts[: len(parts) - (level - 1)]
        if module:
            return ".".join(base_parts + module.split("."))
        return ".".join(base_parts)
    return None


def extract_first_party_imports(
    file_path: Path,
    roots: tuple[str, ...] = ("src", "scripts"),
    _repo_root: Path | None = None,
) -> list[str]:
    """Return unique first-party module names imported in file_path.

    Covers absolute src.*/scripts.* imports AND relative imports (ImportFrom.level > 0).
    Returns [] on syntax error or missing file. Order: first appearance.
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

    def _add(mod: str | None) -> None:
        if mod and mod not in seen:
            seen.add(mod)
            results.append(mod)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                m = alias.name
                if any(m == r or m.startswith(r + ".") for r in roots):
                    _add(m)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                if node.module:
                    # from .sub import X -- resolved submodule is the import target
                    _add(_resolve_relative_import(file_path, node.level, node.module, roots, _repo_root))
                else:
                    # from . import name1, name2 -- each name may be a first-party submodule
                    base = _resolve_relative_import(file_path, node.level, None, roots, _repo_root)
                    if base:
                        for alias in node.names:
                            _add(f"{base}.{alias.name}")
            else:
                m = node.module or ""
                if any(m == r or m.startswith(r + ".") for r in roots):
                    _add(m)

    return results


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
