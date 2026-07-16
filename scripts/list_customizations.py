#!/usr/bin/env python3
"""Generate a machine-readable manifest of .github/ customisation files.

DAF-03 (PLAN-daf-authoring-grammar, Decision 134 cl.3): the decisions-index CLI flag and
build_decisions_index() were retired here -- a 4th divergent DECISIONS.md parser (own heading
grammar, own status/date heuristics) that rebuilt logs/.decisions-index.jsonl FROM PROSE via
Path.write_text, bypassing both the warehouse and the Decision 104 write-path guard. No live
callers existed (scripts/.claude/.github/config grep, confirmed dormant). The legitimate
read-cache path is unaffected: scripts/sync/ops.py populates .decisions-index.jsonl FROM the
ducklake_reader pull, never from this script.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.WARNING)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_DIR = REPO_ROOT / ".github"


def get_last_modified(path: Path) -> str | None:
    """Return ISO timestamp of last git commit touching path, or mtime fallback."""
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
        result = subprocess.run(
            ["git", "log", "--format=%at", "-1", "--", rel],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
        )
        ts = result.stdout.strip()
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        logger.debug("git last-modified failed for %s: %s", path, exc)
    # Fallback to filesystem mtime
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from markdown content. Returns {} on failure."""
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    yaml_text = content[3:end].strip()
    try:
        result = yaml.safe_load(yaml_text)
        return result if isinstance(result, dict) else {}
    except yaml.YAMLError as exc:
        logger.warning("YAML parse error in frontmatter: %s", exc)
        return {}


def build_entry(path: Path) -> dict[str, Any]:
    """Build a manifest entry for a single customisation file."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", rel, exc)
        return {
            "path": rel,
            "name": None,
            "description": None,
            "model": None,
            "last_modified": None,
        }

    fm = parse_frontmatter(content)
    if not fm:
        logger.warning("No frontmatter found in %s — including with nulls", rel)

    name: str | None = fm.get("name") or None
    description: str | None = fm.get("description") or None
    model: str | None = fm.get("model") or None

    if not name:
        logger.warning("Missing 'name' in frontmatter of %s", rel)
    if not description:
        logger.warning("Missing 'description' in frontmatter of %s", rel)

    return {
        "path": rel,
        "name": name,
        "description": description,
        "model": model,
        "last_modified": get_last_modified(path),
    }


def scan_customizations() -> list[dict[str, Any]]:
    """Scan .github/prompts/ and .github/agents/ for customisation files.

    Only .github/prompts/scheduled/ and .github/agents/schedule.yaml remain
    as live surfaces after T-1.13 retired the legacy top-level prompt/agent files.
    Top-level *.prompt.md and *.agent.md no longer exist; the scan gracefully
    returns an empty list without error when those globs match nothing.
    """
    files: list[Path] = []

    prompts_dir = GITHUB_DIR / "prompts"
    if prompts_dir.is_dir():
        files.extend(sorted(prompts_dir.glob("*.prompt.md")))
    else:
        logger.warning("Prompts directory not found: %s", prompts_dir)

    agents_dir = GITHUB_DIR / "agents"
    if agents_dir.is_dir():
        files.extend(sorted(agents_dir.glob("*.agent.md")))
    else:
        logger.warning("Agents directory not found: %s", agents_dir)

    entries = [build_entry(f) for f in files]
    entries.sort(key=lambda e: e["path"])
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate .customizations-manifest.json from .github/ customisation files.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "logs" / ".customizations-manifest.json"),
        help="Output path for manifest JSON (default: repo-root/logs/.customizations-manifest.json)",
    )
    args = parser.parse_args()

    entries = scan_customizations()

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest written: {output_path} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
