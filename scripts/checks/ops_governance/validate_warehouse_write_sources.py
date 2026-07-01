"""Warehouse-as-source-of-truth write-source whitelist enforcement (Decision 104)."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_warehouse_write_sources", owner="platform")
def validate_warehouse_write_sources(failed: list[str]) -> None:
    """Enforce the warehouse-as-source-of-truth invariant.

    Every call to OpsWriter().write("ops_*", ...) must originate from a
    whitelisted file. The whitelist captures the four legitimate write paths:
    1. Portal calls (file_rec/update_rec/file_decision/update_decision)
    2. Canonical ETL from a non-warehouse source of truth (DECISIONS.md -> ops_decisions)
    3. Outbox drain (write-once transient buffer, never replayable)
    4. Fresh in-memory writes (e.g. priority queue enrichment, execution plan save)

    Any new file that writes to an ops_* table must be reviewed against the
    warehouse-as-source invariant in CLAUDE.md before being added to the
    whitelist. Replaying a read cache (e.g. logs/.recommendations-log.jsonl) into
    the warehouse is the resurrection anti-pattern that creates infinite
    re-injection loops -- Iceberg DELETE removes the snapshot, the next replay
    re-injects, SCD2 dedupe surfaces the resurrection as the current row.
    """
    print("\n=== Warehouse write-source whitelist ===")
    scripts_dir = _common.ROOT / "scripts"
    src_dir = _common.ROOT / "src"
    _self_path = Path(__file__)

    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "session_postflight.py",
        scripts_dir / "sync_ops.py",
        scripts_dir / "ops_writer.py",
        scripts_dir / "s3_log_store.py",
        scripts_dir / "executor" / "plan.py",
        _self_path,  # this module's own docstring demonstrates the write call and matches the rule
    }

    _PATTERNS = [
        re.compile(r'OpsWriter\(\)\.write\(\s*["\']ops_'),
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']ops_'),
    ]

    # Table-specific block: the DuckLake-migrated tables (recs, decisions, priority_queue) must
    # NEVER route to OpsWriter/Iceberg after Decision 84 I-1 -- readers serve DuckLake, so an
    # Iceberg write is a silent split-brain. Catches any site, including whitelisted files.
    # Self-excluded: this module's docstring demonstrates the write call and would otherwise self-flag.
    # Tracked exemption: scripts/s3_log_store.py's dormant queue producer (T2.26 repoint; the
    # scheduled-agent Lambdas that drive it are disabled -- see the AGENTS.md re-enable runbook caveat).
    _MIGRATED = r"ops_(?:recommendations|decisions|priority_queue)"
    _MIGRATED_BLOCK_PATTERNS = [
        re.compile(r'OpsWriter\(\)\.write\(\s*["\']' + _MIGRATED),
        re.compile(r'OpsWriter\(\)\.compact\(\s*["\']' + _MIGRATED),
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']' + _MIGRATED),
        re.compile(r'\b(?:writer|ops|_writer)\.compact\(\s*["\']' + _MIGRATED),
    ]
    _MIGRATED_BLOCK_EXEMPT = {scripts_dir / "s3_log_store.py"}  # dormant queue producer, T2.26

    errors: list[str] = []
    for search_dir in [scripts_dir, src_dir]:
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue

            # Table-specific migrated-tables block (applies to ALL files, including whitelist).
            if py_file != _self_path and py_file not in _MIGRATED_BLOCK_EXEMPT:
                for recs_pat in _MIGRATED_BLOCK_PATTERNS:
                    if recs_pat.search(content):
                        rel = py_file.relative_to(_common.ROOT)
                        errors.append(
                            f"{rel}: writes/compacts a DuckLake-migrated table via OpsWriter -- "
                            "recs/decisions/priority_queue transit the closed boundary (Decision 84 I-1). "
                            "Use the ops_data_portal surface."
                        )
                        break

            if py_file in _WHITELIST:
                continue
            for pattern in _PATTERNS:
                if pattern.search(content):
                    rel = py_file.relative_to(_common.ROOT)
                    errors.append(
                        f"{rel}: writes to ops_* table but not on warehouse-write whitelist. "
                        f"See validate_warehouse_write_sources docstring."
                    )
                    break

    if errors:
        print("Warehouse write-source violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("All ops_* writes originate from whitelisted files.")
