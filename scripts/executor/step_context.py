# complexity-waiver: decision-43
"""Per-step file-context gathering for the executor.

Extracted from scripts/executor/step_runner.py (SLOC decomposition, Decision
102/104 facade mechanism). Gathers file/test/pattern content to inject into
the implementation prompt, plus Known Gotcha injection for the target file
path. Routed-name references (Path, _LARGE_FILE_THRESHOLD,
_get_relevant_gotchas) resolve through the scripts.executor.step_runner
facade via a function-local import so the existing test suite's patches on
scripts.executor.step_runner.<name> keep intercepting with zero migration.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Known Gotcha injection
# ---------------------------------------------------------------------------

# Maps file-path prefixes (or substrings) to relevant Known Gotcha strings.
# Keys are matched as prefixes first, then as substrings, against the step's
# target file path. Entries are ordered from most-specific to least-specific.
_GOTCHA_MAP: dict[str, list[str]] = {
    "scripts/executor/": [
        "replace_string_in_file context boundary: Include 3-5 lines of unchanged code before "
        "and after target text. Weak boundaries cause wrong-occurrence matches or silent formatting changes.",
        "ruff E501 and multi-line section builders: Define intermediate _header, _footer, _section "
        "variables for long f-strings to stay under 127 chars.",
        "Executor self-modification boundary: Never modify executor machinery files from within the executor.",
    ],
    "terraform/": [
        "Terraform File-Optional Operations: Always wrap filemd5() and file() calls on optional "
        "artifacts with try(). BAD: source_code_hash = filemd5('build/lambda.zip'). "
        "GOOD: source_code_hash = try(filemd5('build/lambda.zip'), md5(file('module_file.tf'))).",
        "Lambda tag values must use ASCII-safe characters: use plain ASCII hyphens (-) not em dashes.",
    ],
    "tests/": [
        "Test Isolation Patterns: Never spawn pytest tests/ from a script any test imports -- "
        "recursion risk. Always mock both subprocess.Popen AND subprocess.run for subprocess-spawning functions.",
        "ruff format duplicate import consolidation: Never split the same module imports across two "
        "blocks -- ruff silently drops symbols from the second block during format.",
        "postflight.py function mock exhaustion: Count total subprocess.run call sequence and update "
        "mock side_effect counts in tests/test_execute_recommendation.py when adding new calls.",
    ],
    "src/data/handlers/": [
        "Import Safety Patterns: Never raise exceptions during module import -- breaks pytest collection in CI. "
        "Defer validation to explicit validate() calls.",
        "Lambda deployment pipeline: Any plan modifying Lambda-packaged files must include "
        "build and deploy steps via scripts/build_lambda.py.",
    ],
}

_GOTCHA_INJECTION_MAX_CHARS = 2000


def _get_relevant_gotchas(file_path: str) -> str:
    """Return a string of relevant Known Gotchas for the given file path.

    Matches entries in ``_GOTCHA_MAP`` by prefix (checked first) then
    substring. Returns an empty string when no match is found.
    """
    if not file_path:
        return ""

    matched: list[str] = []
    for key, gotchas in _GOTCHA_MAP.items():
        if file_path.startswith(key) or key in file_path:
            matched.extend(gotchas)

    if not matched:
        return ""

    lines = ["## Relevant Known Gotchas"]
    for item in matched:
        lines.append(f"- {item}")
    result = "\n".join(lines)
    if len(result) > _GOTCHA_INJECTION_MAX_CHARS:
        result = result[:_GOTCHA_INJECTION_MAX_CHARS] + "\n# ... (truncated)"
    return result


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


def gather_step_context(step: dict, max_chars: int = 28000, recommendation_target_file: str = "") -> dict:
    """Gather file context for a step to inject into the implementation prompt.

    For action == 'modify': reads step['file'] if it exists.
        For large files (> _LARGE_FILE_THRESHOLD lines), attempts to extract
        a targeted function region based on context hints in step['title']
        or step['description']. The targeted region includes: imports section
        (first 60 lines) + 50 lines before target function + entire function body.
    For action == 'create': finds the most recently modified file with the same
        extension in the same directory to use as a coding pattern.
    Always looks for a corresponding test file at tests/test_{stem}.py.

    All content is capped at max_chars total (summed across all three keys).
    Oversized content is truncated with an '# ... (N lines omitted)' marker.

    Args:
        step: PlanStep dict with keys 'action' and 'file'.
        max_chars: Maximum total characters across all returned content strings.
        recommendation_target_file: Optional fallback file path when step has
            no 'file' field. Used to provide context for the recommendation's
            target file.

    Returns:
        dict with keys: file_content, test_content, pattern_content.
        Each value is a string (empty string if not found or not applicable).
    """
    import scripts.executor.step_runner as _sr

    result: dict[str, str] = {"file_content": "", "test_content": "", "pattern_content": ""}

    file_path_str: str = step.get("file", "") or recommendation_target_file
    if not file_path_str:
        return result

    file_path = _sr.Path(file_path_str)
    action: str = step.get("action", "").lower()

    def _read_truncated(path: Path, budget: int) -> str:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if len(content) <= budget:
            return content
        truncated = content[:budget]
        lines_omitted = content[budget:].count("\n")
        return truncated + f"\n# ... ({lines_omitted} lines omitted)\n"

    def _extract_targeted_function_region(path: Path, context_hint: str, budget: int) -> str:
        """Extract targeted function region from a large file using context hints.

        Scans context_hint for function name patterns, then extracts:
        - Imports section (first 60 lines)
        - 50 lines before target function definition
        - Entire function body (until next def or class at same indentation)

        Returns empty string if no function hint found or extraction fails.
        """
        try:
            full_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

        lines = full_content.splitlines(keepends=True)

        # Extract function name from context_hint
        # Pattern: "modify function_name" or "update function_name" or just "function_name"
        # Use word boundary after optional verb to prevent matching irrelevant words
        func_pattern = r"\b(?:modify|update|enhance|add|change|fix)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        matches = re.findall(func_pattern, context_hint.lower())
        # Also try matching standalone function-like identifiers if no verb match
        if not matches:
            func_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]{3,})\b"
            matches = re.findall(func_pattern, context_hint.lower())
        if not matches:
            return ""

        # Try each extracted name as a potential function name
        for func_name in matches:
            # Find the function definition line
            # Use case-insensitive matching to support CamelCase function names
            func_def_pattern = re.compile(rf"^\s*def\s+{re.escape(func_name)}\s*\(", re.IGNORECASE)
            insertion_point = -1

            for i, line in enumerate(lines):
                if func_def_pattern.match(line):
                    insertion_point = i
                    break

            if insertion_point == -1:
                continue  # Try next function name candidate

            # Extract function body by finding the end of the function
            # Normalize indentation: count leading whitespace in visual columns
            # by expanding tabs to spaces (Python default: 8 spaces per tab)
            def get_indent_level(line: str) -> int:
                return len(line.expandtabs(8)) - len(line.expandtabs(8).lstrip())

            func_indent = get_indent_level(lines[insertion_point])
            func_end = insertion_point + 1

            for j in range(insertion_point + 1, len(lines)):
                line = lines[j]
                if line.strip() == "":
                    continue  # Skip blank lines
                current_indent = get_indent_level(line)
                # End when we hit next function/class definition at same or lower indentation
                if current_indent <= func_indent and (line.lstrip().startswith("def ") or line.lstrip().startswith("class ")):
                    func_end = j
                    break
            else:
                func_end = len(lines)  # Function extends to end of file

            # Build the targeted region
            region_parts = []

            # 1. Imports section (first 60 lines)
            import_section = "".join(lines[:60])
            region_parts.append(import_section)
            region_parts.append("\n# ... (imports section) ...\n\n")

            # 2. 50 lines before the function
            context_start = max(60, insertion_point - 50)
            if context_start < insertion_point:
                context_before = "".join(lines[context_start:insertion_point])
                region_parts.append(context_before)

            # 3. The target function body
            # Include func_end in the slice to capture the final line of the function
            function_body = "".join(lines[insertion_point : func_end + 1])
            region_parts.append(function_body)

            targeted_content = "".join(region_parts)

            # Apply budget limit
            if len(targeted_content) <= budget:
                return targeted_content

            truncated = targeted_content[:budget]
            lines_omitted = targeted_content[budget:].count("\n")
            return truncated + f"\n# ... ({lines_omitted} lines omitted)\n"

        return ""  # No valid function found

    remaining = max_chars

    if action == "modify" and file_path.exists():
        # Check if file is large and we have context hints
        try:
            file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            is_large_file = len(file_lines) > _sr._LARGE_FILE_THRESHOLD
        except OSError:
            is_large_file = False

        if is_large_file:
            # Try to extract context hint from title or description
            context_hint = step.get("title", "") + " " + step.get("description", "")
            targeted_region = _extract_targeted_function_region(file_path, context_hint, remaining)

            if targeted_region:
                result["file_content"] = targeted_region
                remaining -= len(result["file_content"])
            else:
                # Fallback to top-of-file truncation
                result["file_content"] = _read_truncated(file_path, remaining)
                remaining -= len(result["file_content"])
        else:
            # Small file: use normal truncation
            result["file_content"] = _read_truncated(file_path, remaining)
            remaining -= len(result["file_content"])

    elif action == "create":
        parent = file_path.parent
        suffix = file_path.suffix
        if parent.is_dir() and suffix:
            candidates = sorted(parent.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
            candidates = [c for c in candidates if c.resolve() != file_path.resolve()]
            if candidates:
                result["pattern_content"] = _read_truncated(candidates[0], remaining)
                remaining -= len(result["pattern_content"])

    if remaining > 0:
        stem = file_path.stem
        test_file = _sr.Path("tests") / f"test_{stem}.py"
        if test_file.exists():
            result["test_content"] = _read_truncated(test_file, remaining)

    # Inject relevant Known Gotchas for the target file path.
    gotchas = _sr._get_relevant_gotchas(file_path_str)
    if gotchas:
        result["file_content"] = result["file_content"] + "\n\n" + gotchas if result["file_content"] else gotchas

    return result
