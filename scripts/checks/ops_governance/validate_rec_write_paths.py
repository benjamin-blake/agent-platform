"""Recommendations-JSONL direct-write-path enforcement (Decision 104)."""

from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_rec_write_paths", owner="platform")
def validate_rec_write_paths(failed: list[str]) -> None:
    """Enforce that no .py file directly writes to the recommendations JSONL.

    All writes must go through scripts.ops_data_portal (file_rec, update_rec).
    Direct JSONL appends bypass writer-owned ID allocation (Decision 84 I-2), Pydantic validation,
    and the closed ducklake_writer boundary.

    Whitelisted files (permitted to write directly):
      - scripts/ops_data_portal.py  (the portal itself)
      - scripts/sync_recommendations.py  (cache overwrite by design)
    """
    print("\n=== Rec JSONL write-path enforcement ===")
    scripts_dir = _common.ROOT / "scripts"
    personal_dir = _common.ROOT / "personal_scripts"
    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "sync_recommendations.py",
        scripts_dir / "sync_ops.py",
        scripts_dir / "s3_log_store.py",
        scripts_dir / "session_postflight.py",
    }
    # Patterns that indicate a direct JSONL write or routing bypass
    _PATTERNS = [
        re.compile(r'RECS_JSONL\.open\(["\']a["\']'),
        re.compile(r'RECS_JSONL\.open\(["\']w["\']'),
        re.compile(r'recommendations-log\.jsonl.*open\(.*["\'][aw]["\']', re.DOTALL),
        re.compile(r"append_jsonl\s*\(\s*_RECS_KEY"),
        re.compile(r'append_jsonl\s*\(\s*["\']\.recommendations-log\.jsonl["\']'),
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
                for m in pattern.finditer(content):
                    lineno = content[: m.start()].count("\n") + 1
                    rel = py_file.relative_to(_common.ROOT)
                    errors.append(f"{rel}:{lineno}: direct rec JSONL write detected (use ops_data_portal)")
                    break  # one report per file per pattern is enough

    if errors:
        print("Rec write-path violations found:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("No direct rec JSONL writes outside whitelist.")
