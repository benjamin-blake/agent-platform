"""Batch classification of open recommendations for executor eligibility.

Reads open recs from ``logs/.recommendations-log.jsonl``, applies the
eligibility criteria (XS/S effort, low risk, target file <= 800 SLOC,
not an executor boundary file), and writes the updated JSONL.

Usage
-----
python -m scripts.classify_automatable
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
_RECS_PATH = _REPO_ROOT / "logs" / ".recommendations-log.jsonl"
_MAX_SLOC = 800

_BOUNDARY_PATTERNS = (
    "execute_recommendation.py",
    "scripts/executor/",
    "config/agent/executor/prompts/",
    "executor-supervisor",
    "executor-implement",
    "executor-critique",
    "executor-planning",
    "executor-review",
    "develop-executor.prompt.md",
    "copilot_wrapper.py",
    "llm_client.py",
    "llm_utils.py",
    "tool_runtime.py",
    "tests/test_execute",
    "tests/test_executor_",
    "tests/test_copilot_wrapper",
    "tests/test_llm_client",
    "tests/test_llm_utils",
    "tests/test_tool_runtime",
)


def _is_boundary_file(file_path: str) -> bool:
    """Return True if *file_path* matches an executor boundary pattern."""
    for pat in _BOUNDARY_PATTERNS:
        if pat in file_path:
            return True
    return False


def _count_sloc(file_path: Path) -> int:
    """Count non-empty lines in a file."""
    try:
        return sum(1 for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, UnicodeDecodeError):
        return 0


def classify(rec: dict[str, object]) -> bool:
    """Return True if *rec* should be automatable."""
    effort = rec.get("effort", "M")
    if effort not in ("XS", "S"):
        return False
    if rec.get("risk") != "low":
        return False

    target_file = str(rec.get("file", ""))
    if not target_file:
        return False
    if _is_boundary_file(target_file):
        return False

    file_path = _REPO_ROOT / target_file
    if not file_path.exists():
        return False
    if _count_sloc(file_path) > _MAX_SLOC:
        return False

    return True


def run(recs_path: Path = _RECS_PATH) -> tuple[int, int]:
    """Classify all open recs and write back. Returns (automatable, non_automatable)."""
    lines = recs_path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    auto_count = 0
    non_auto_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            updated.append("")
            continue
        rec = json.loads(line)
        if rec.get("status") != "open":
            updated.append(json.dumps(rec, ensure_ascii=False))
            continue

        is_auto = classify(rec)
        rec["automatable"] = is_auto
        if is_auto:
            auto_count += 1
        else:
            non_auto_count += 1
        updated.append(json.dumps(rec, ensure_ascii=False))

    recs_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return auto_count, non_auto_count


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO)
    auto, non_auto = run()
    print(f"Classified {auto + non_auto} open recs: {auto} automatable, {non_auto} non-automatable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
