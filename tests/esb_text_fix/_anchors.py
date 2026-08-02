"""Shared document loaders and locator helpers for the ESB text-fix guard package (PLAN-esb-text-fix-bundle).

Names all three target document paths as literal quoted tokens so
scripts/checks/deps/affected_tests.py channel 2 (data-edge PRECISE match) selects this package
into the --pre tier whenever "docs/ROADMAP-PLATFORM.yaml", "docs/DECISIONS.md" or
"docs/INTENT-provider-agnostic-executor.md" changes -- including in later ESB waves.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

ROADMAP_PATH = "docs/ROADMAP-PLATFORM.yaml"
DECISIONS_PATH = "docs/DECISIONS.md"
INTENT_PATH = "docs/INTENT-provider-agnostic-executor.md"

# "checkpoint-replay" deliberately omitted -- it is a strict substring superset of "replay" (any
# text containing the former necessarily contains the latter), so keeping both never changes
# detection, only pads the hits list with a redundant duplicate (code-review round 3).
BANNED_MECHANISM_TOKENS = ("durable function", "forced timeout", "replay")


def load_roadmap() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / ROADMAP_PATH).read_text(encoding="utf-8"))


def load_decisions_text() -> str:
    return (REPO_ROOT / DECISIONS_PATH).read_text(encoding="utf-8")


def load_intent_text() -> str:
    return (REPO_ROOT / INTENT_PATH).read_text(encoding="utf-8")


def cd27(roadmap: dict[str, Any] | None = None) -> dict[str, Any]:
    d = roadmap or load_roadmap()
    return next(c for c in d["candidate_decisions"] if c["id"] == "CD.27")


def tier_item(item_id: str, roadmap: dict[str, Any] | None = None) -> dict[str, Any]:
    d = roadmap or load_roadmap()
    return next(i for i in d["tier_items"] if i["id"] == item_id)


def mechanism_hits(text: str) -> list[str]:
    """Return which banned mechanism tokens (case-insensitive) appear in text."""
    low = str(text).lower()
    return [tok for tok in BANNED_MECHANISM_TOKENS if tok in low]


def persona_node_lines(t41: dict[str, Any]) -> list[str]:
    """The T4.1 state-machine-shape lines that carry a '[..., T4.2]' persona-node typing."""
    return [line for line in t41["intent"].splitlines() if "[" in line and "T4.2]" in line]
