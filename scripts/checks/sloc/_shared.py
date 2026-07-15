"""Constants and shared scan helper for the sloc/cc_limits checks within this package only."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Iterator

from scripts.checks import _common

_SLOC_LIMIT = 500
_CC_LIMIT = 20
_WAIVER_PATTERN = re.compile(r"#\s*complexity-waiver:\s*decision-43")
_SLOC_EXCLUDE_DIRS = {
    "pip",
    "lambda-packages",
    "docker",
    "terraform",
    ".venv",
    "node_modules",
    ".git",
    "personal_scripts",
}
_BRANCH_TYPES = (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.BoolOp)


def iter_gated_py_files() -> Iterator[Path]:
    """Whole-repo scan of gated Python files (Decision 130).

    Sole scan definition consumed by validate_sloc_limits, _update_sloc_budgets, and
    validate_cc_limits, so their scan roots can never drift apart. Excludes only the
    vendored/generated directories in _SLOC_EXCLUDE_DIRS and __init__.py -- every
    hand-authored directory (tests/, .claude/, bin/, config/, etc.) is gated. Directory
    descent is pruned at excluded names (not filtered post-hoc) so the walk never
    enters e.g. .venv or node_modules.
    """
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(_common.ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SLOC_EXCLUDE_DIRS]
        for filename in filenames:
            if filename == "__init__.py" or not filename.endswith(".py"):
                continue
            matches.append(Path(dirpath) / filename)
    return iter(sorted(matches))
