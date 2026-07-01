"""Constants shared by the sloc/cc_limits checks within this package only."""

from __future__ import annotations

import ast
import re

_SLOC_LIMIT = 500
_CC_LIMIT = 20
_WAIVER_PATTERN = re.compile(r"#\s*complexity-waiver:\s*decision-43")
_SLOC_EXCLUDE_DIRS = {"pip", "lambda-packages", "docker", "terraform", ".venv", "node_modules"}
_BRANCH_TYPES = (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.BoolOp)
