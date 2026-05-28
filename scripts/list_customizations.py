#!/usr/bin/env python3
"""Generate a machine-readable manifest of .github/ customisation files.

Also supports --with-decisions to regenerate .decisions-index.jsonl.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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
    """Scan .github/prompts/*.prompt.md and .github/agents/*.agent.md."""
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


def build_decisions_index(decisions_path: Path) -> list[dict[str, Any]]:
    """Parse DECISIONS.md and build a machine-readable index."""
    if not decisions_path.exists():
        logger.warning("DECISIONS.md not found at %s", decisions_path)
        return []

    content = decisions_path.read_text(encoding="utf-8")
    entries: list[dict[str, Any]] = []

    # Match headings like: ## Decision 21: Some Title (Decided)
    # or ## Some Title (Decided) / ## Some Title (Open)
    heading_pattern = re.compile(
        r"^## (?:Decision (\d+):\s*)?(.+?)(?:\s*\((Decided|Open)\))?\s*$",
        re.MULTILINE,
    )
    date_pattern = re.compile(r"Status\b[^\n]*?[-\u2013\u2014]\s+([A-Za-z]+ \d{4}|\d{4}-\d{2}-\d{2})")

    matches = list(heading_pattern.finditer(content))
    skip_titles = {"Open Decisions", "Rejected Cron Suggestions"}

    for i, match in enumerate(matches):
        decision_num = match.group(1)
        title = match.group(2).strip()
        status_inline = match.group(3)

        if title in skip_titles:
            continue

        section_start = match.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_text = content[section_start:section_end]

        if status_inline:
            status = status_inline
        elif "Status:** Decided" in section_text or "Status: Decided" in section_text:
            status = "Decided"
        elif "Status:** Open" in section_text or "Status: Open" in section_text:
            status = "Open"
        else:
            status = "Unknown"

        date_match = date_pattern.search(section_text)
        date: str | None = date_match.group(1) if date_match else None

        keywords = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)]

        if decision_num:
            entry_id = f"dec-{decision_num.zfill(3)}"
        else:
            # Auto-number: pick the next integer not already used by explicit IDs
            used_ids = {e["id"] for e in entries}
            n = 1
            while f"dec-{n:03d}" in used_ids:
                n += 1
            entry_id = f"dec-{n:03d}"

        entries.append(
            {
                "id": entry_id,
                "title": title,
                "status": status,
                "date": date,
                "keywords": keywords,
            }
        )

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate .customizations-manifest.json from .github/ customisation files.")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "logs" / ".customizations-manifest.json"),
        help="Output path for manifest JSON (default: repo-root/logs/.customizations-manifest.json)",
    )
    parser.add_argument(
        "--with-decisions",
        action="store_true",
        help="Also regenerate .decisions-index.jsonl from DECISIONS.md",
    )
    args = parser.parse_args()

    entries = scan_customizations()

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest written: {output_path} ({len(entries)} entries)")

    if args.with_decisions:
        decisions_path = REPO_ROOT / "docs" / "DECISIONS.md"
        index = build_decisions_index(decisions_path)
        index_path = REPO_ROOT / "logs" / ".decisions-index.jsonl"
        lines = [json.dumps(entry, ensure_ascii=False) for entry in index]
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Decisions index written: {index_path} ({len(index)} entries)")


if __name__ == "__main__":
    main()
