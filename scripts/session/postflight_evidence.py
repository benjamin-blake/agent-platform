"""Bounded structured implementation-retrospective evidence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

EVIDENCE_PATH = Path("logs/debug/implementation-retrospective.json")
CATEGORIES = (
    "first_failure_and_fix",
    "expensive_or_duplicated_work",
    "ambiguous_instructions",
    "reviewer_only_findings",
    "validator_only_findings",
    "reviewer_false_positives",
    "late_discovered_repository_facts",
    "possible_pre_edit_checks",
    "misleading_output",
    "guard_candidates",
)
_SECRET = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*\S+")


def validate(evidence: dict[str, object]) -> None:
    if set(evidence) != set(CATEGORIES):
        raise ValueError(f"evidence requires exactly these categories: {', '.join(CATEGORIES)}")
    encoded = json.dumps(evidence)
    if len(encoded) > 16_384:
        raise ValueError("evidence exceeds 16384 bytes")
    if _SECRET.search(encoded):
        raise ValueError("evidence contains secret-like content")
    if not all(isinstance(value, list) and all(isinstance(item, str) for item in value) for value in evidence.values()):
        raise ValueError("each evidence category must be a list of strings")


def write(evidence: dict[str, object], path: Path = EVIDENCE_PATH) -> None:
    validate(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def render(evidence: dict[str, object]) -> str:
    validate(evidence)
    sections = []
    for category in CATEGORIES:
        title = category.replace("_", " ").title()
        entries = evidence[category]
        body = "\n".join(f"- {entry}" for entry in entries) or "- None recorded"
        sections.append(f"## {title}\n{body}")
    return "\n\n".join(sections)
