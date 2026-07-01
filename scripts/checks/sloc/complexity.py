# complexity-waiver: decision-43
"""Code-complexity-by-package and prompt-density advisory analysis."""

from __future__ import annotations

import ast
import json
import re
import statistics
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_complexity", owner="platform")
def validate_complexity(failed: list[str]) -> list[dict]:
    """Analyze code complexity by package (Python) and prompt density.

    Performs AST-based analysis of Python files counting public functions
    and import fan-out grouped by top-level package. Analyzes prompt files
    for imperative-statement density. Flags files >2 std-devs above their
    package mean as warnings. Packages with <3 files are skipped. Writes
    warnings to logs/.complexity-warnings.json. Never appends to failed.
    """
    print("\n=== Code complexity analysis ===")

    _EXCLUDE_PATTERNS = {"__init__.py", "conftest.py"}
    _EXCLUDE_DIRS = {"pip", "lambda-packages", "docker", "terraform"}

    def _should_exclude(path: Path) -> bool:
        if path.name in _EXCLUDE_PATTERNS:
            return True
        for part in path.parts:
            if part in _EXCLUDE_DIRS:
                return True
        return False

    def _count_public_functions(filepath: Path) -> int:
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            return 0
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                count += 1
        return count

    def _count_imports(filepath: Path) -> int:
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            return 0
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return len(imports)

    def _get_package(filepath: Path) -> str:
        try:
            rel = filepath.relative_to(_common.ROOT)
            parts = rel.parts
            if parts[0] == "src" and len(parts) > 1:
                return parts[1]
            return parts[0]
        except ValueError:
            return "unknown"

    def _count_imperative_statements(filepath: Path) -> float:
        try:
            content = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            return 0.0
        if not content:
            return 0.0
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return 0.0
        imperative_count = sum(
            1
            for line in lines
            if re.match(
                r"^(You |Do |Must |Should |Add |Create |Implement |Update )",
                line,
            )
        )
        return imperative_count / len(lines)

    # Collect Python file metrics
    py_metrics: dict[str, list[tuple[Path, float]]] = {}

    src_dir = _common.ROOT / "src"
    if src_dir.exists():
        for py_file in sorted(src_dir.glob("**/*.py")):
            if _should_exclude(py_file):
                continue
            pkg = _get_package(py_file)
            complexity = float(_count_public_functions(py_file) + _count_imports(py_file))
            if pkg not in py_metrics:
                py_metrics[pkg] = []
            py_metrics[pkg].append((py_file, complexity))

    scripts_dir = _common.ROOT / "scripts"
    if scripts_dir.exists():
        for py_file in sorted(scripts_dir.glob("**/*.py")):
            if _should_exclude(py_file):
                continue
            pkg = _get_package(py_file)
            complexity = float(_count_public_functions(py_file) + _count_imports(py_file))
            if pkg not in py_metrics:
                py_metrics[pkg] = []
            py_metrics[pkg].append((py_file, complexity))

    # Flag outliers in Python files
    py_warnings: list[dict] = []
    for pkg, entries in py_metrics.items():
        if len(entries) < 3:
            continue
        values = [c for _, c in entries]
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        if stdev <= 0:
            continue
        threshold = mean + 2 * stdev
        for py_file, complexity in entries:
            if complexity > threshold:
                rel = py_file.relative_to(_common.ROOT)
                py_warnings.append(
                    {
                        "file": str(rel).replace("\\", "/"),
                        "type": "python",
                        "complexity": complexity,
                        "package": pkg,
                        "mean": round(mean, 2),
                        "stdev": round(stdev, 2),
                        "threshold": round(threshold, 2),
                    }
                )

    # Collect prompt file metrics
    prompt_warnings: list[dict] = []
    prompts_dir = _common.ROOT / ".github" / "prompts"
    if prompts_dir.exists():
        prompt_entries: list[tuple[Path, float]] = []
        for md_file in sorted(prompts_dir.glob("**/*.md")):
            density = _count_imperative_statements(md_file)
            prompt_entries.append((md_file, density))

        if len(prompt_entries) >= 3:
            densities = [d for _, d in prompt_entries]
            mean = statistics.mean(densities)
            stdev = statistics.stdev(densities) if len(densities) > 1 else 0.0
            if stdev > 0:
                threshold = mean + 2 * stdev
                for md_file, density in prompt_entries:
                    if density > threshold:
                        rel = md_file.relative_to(_common.ROOT)
                        prompt_warnings.append(
                            {
                                "file": str(rel).replace("\\", "/"),
                                "type": "prompt",
                                "density": round(density, 3),
                                "mean": round(mean, 3),
                                "stdev": round(stdev, 3),
                                "threshold": round(mean + 2 * stdev, 3),
                            }
                        )

    warnings = py_warnings + prompt_warnings

    # Write warnings to JSON file
    warnings_file = _common.ROOT / "logs" / ".complexity-warnings.json"
    warnings_file.parent.mkdir(parents=True, exist_ok=True)
    warnings_file.write_text(json.dumps(warnings, indent=2), encoding="utf-8")

    if warnings:
        print("Complexity warnings (>2 stdev above package mean):")
        for w in warnings:
            if w["type"] == "python":
                print(
                    f"  {w['file']}: complexity {w['complexity']} "
                    f"(pkg {w['package']} mean={w['mean']}, "
                    f"stdev={w['stdev']}, threshold={w['threshold']})"
                )
            else:
                print(
                    f"  {w['file']}: imperative density {w['density']} "
                    f"(mean={w['mean']}, stdev={w['stdev']}, "
                    f"threshold={w['threshold']})"
                )
    else:
        print("No complexity warnings found.")

    return warnings
