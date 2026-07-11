"""Decisions-JSONL direct-write-path enforcement (Decision 104)."""

from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_decisions_local_writes", owner="platform")
def validate_decisions_local_writes(failed: list[str]) -> None:
    """Enforce that no .py file directly writes to .decisions-index.jsonl.

    The local decisions cache is a read-only downstream projection of the DuckLake reader.
    All writes must go through scripts.ops_data_portal (file_decision, update_decision)
    which handles write-through. Cache rebuild happens via sync_ops pull only.

    Whitelisted files (permitted to write directly):
      - scripts/ops_data_portal.py  (write-through cache update)
      - scripts/sync/ops.py         (cache rebuild from the DuckLake reader)
    """
    print("\n=== Decisions JSONL write-path enforcement ===")
    scripts_dir = _common.ROOT / "scripts"
    personal_dir = _common.ROOT / "personal_scripts"
    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "sync" / "ops.py",
    }
    _PATTERNS = [
        re.compile(r'\.decisions-index\.jsonl.*open\(.*["\'][aw]["\']', re.DOTALL),
        re.compile(r'DECISIONS_JSONL\.open\(["\'][aw]["\']'),
        re.compile(r'decisions.index\.jsonl.*["\'][aw]["\']'),
    ]
    errors: list[str] = []

    search_dirs = [scripts_dir]
    if personal_dir.exists():
        search_dirs.append(personal_dir)

    for search_dir in search_dirs:
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file in _WHITELIST:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in _PATTERNS:
                if pattern.search(content):
                    rel = py_file.relative_to(_common.ROOT)
                    errors.append(
                        f"{rel}: writes to .decisions-index.jsonl but not on decisions write-path whitelist. "
                        f"See validate_decisions_local_writes docstring."
                    )
                    break

    if errors:
        print("Decisions JSONL write-path violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("All .decisions-index.jsonl writes originate from whitelisted files.")
