"""Standing guard: no tracked file cites the deleted AGENTS.md operational runbook for
re-enabling Lambda scheduled agents (removed by PLAN-agents-md-ambient-trim; repoint any
citation to T4.12 / Decision 84 instead). Excludes docs/plans/, docs/audit-prompts/,
audits/ and logs/, which are historical record, not live prose.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_EXCLUDED_PREFIXES = ("docs/plans/", "docs/audit-prompts/", "audits/", "logs/")

_SELF_REL = "tests/test_agents_md_citations.py"

# Split literals so this guard file never contains the strings it searches for --
# otherwise it would self-match and could never pass. The alternative precedent is a
# _self_path exclusion (scripts/checks/ops_governance/validate_warehouse_write_sources.py:32,40);
# split literals are used here instead so the sweep this test mirrors stays unweakened.
_PATTERNS = (
    "AGENTS.md" + " runbook",
    "AGENTS.md" + " re-enable runbook",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def test_no_dangling_agents_md_runbook_citations() -> None:
    offenders = []
    scanned = []
    for rel_path in _tracked_files():
        if rel_path.startswith(_EXCLUDED_PREFIXES):
            continue
        path = ROOT / rel_path
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned.append(rel_path)
        for pattern in _PATTERNS:
            if pattern in text:
                offenders.append(f"{rel_path}: {pattern!r}")
    assert not offenders, f"files still cite the deleted runbook: {offenders}"
    # This guard is only meaningful once it scans ITSELF: an untracked (or excluded) guard file
    # passes vacuously, which is exactly how the split-literal discipline was first broken -- the
    # assertion message below carried a raw literal, and the local run went green purely because
    # the file was not yet committed and so invisible to git ls-files.
    assert _SELF_REL in scanned, (
        f"{_SELF_REL} was not scanned -- the guard must be tracked and inside the swept set, "
        "otherwise a self-match (or any regression) can pass unnoticed"
    )
