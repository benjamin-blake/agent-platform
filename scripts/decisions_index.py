"""Generated decisions index (audit finding DCG-08, PLAN-dcg-decisions-index, FINAL wave of
the dcg-* audit-consolidation series).

A lightweight, machine-parseable projection over BOTH docs/DECISIONS.md and
docs/DECISIONS_ARCHIVE.md -- number, title, status, decided_date, and typed
supersedes/superseded_by/amends edges -- derived SOLELY via the shared parser
scripts.decisions_md (DAF-03 single-parser rule): no second header/title regex lives here.

build_index() projects ONLY stable fields from each parse_decisions_md() row -- it EXCLUDES the
parser's volatile created_timestamp/last_updated_timestamp/content_hash/raw_block fields, so two
consecutive calls are byte-identical (json.dumps(..., sort_keys=True) equal) and the committed
docs/decisions-index.json can be compared for drift without a timestamp always tripping it.

Edge derivation:
  - amends: the row's own "amends" key (scripts.decisions_md.extract_amends_edges, forward
    title-relation extraction on the raw heading title).
  - superseded_by: the row's typed "superseded_by" string ('dec-NNN' or ''), coerced to
    int | None.
  - supersedes: the corpus-wide UNION of (a) the inverse of every OTHER row's superseded_by
    pointing at this number, and (b) this row's own "title_supersedes" key
    (scripts.decisions_md._extract_title_borne_supersedes, title-borne "Supersedes Decision N").

check_index_freshness(failed) fails on DRIFT (committed != regenerated) OR ABSENCE -- unlike
scripts.dependency_graph.check_export_freshness (Decision 80 lean posture: no-op when the export
is absent), this index is a required committed artifact (Step 6b fork 2: committed JSON +
registered drift check, not a gitignored synced cache), so a missing file is itself a failure.

CLI: --write (regenerate docs/decisions-index.json), --check (freshness, exit 1 on fail),
--print (dump the current index to stdout).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.decisions_md import parse_decisions_md

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXPORT_PATH = _REPO_ROOT / "docs" / "decisions-index.json"


def _superseded_by_int(raw: str) -> int | None:
    """Coerce the parser's 'dec-NNN' superseded_by string to a bare int, or None if empty."""
    if not raw:
        return None
    # raw is always exactly 'dec-NNN' here -- scripts.decisions_md._extract_superseded_by's
    # only two possible return values are '' or f"dec-{int(n):03d}" -- so split("-")[1] is safe.
    return int(raw.split("-")[1])


def build_index() -> dict[str, Any]:
    """Build the deterministic decisions index dict (docs/decisions-index.json shape).

    Sorted by number. Excludes every volatile parse_decisions_md field -- only
    number/title/status/decided_date/supersedes/superseded_by/amends survive the projection.
    """
    rows = parse_decisions_md()
    by_number = {row["decision_id"]: row for row in rows}
    superseded_by_map = {n: _superseded_by_int(row.get("superseded_by", "")) for n, row in by_number.items()}

    supersedes_map: dict[int, set[int]] = {n: set() for n in by_number}
    for n, row in by_number.items():
        sb = superseded_by_map[n]
        if sb is not None and sb in supersedes_map:
            # row n's superseded_by == sb means "n is superseded BY sb" -> sb supersedes n.
            supersedes_map[sb].add(n)
        for target in row.get("title_supersedes", []):
            if target in supersedes_map:
                # row n's own title says "Supersedes Decision target" -> n supersedes target.
                supersedes_map[n].add(target)

    decisions = [
        {
            "number": n,
            "title": by_number[n]["title"],
            "status": by_number[n]["status"],
            "decided_date": by_number[n].get("decided_date", ""),
            "supersedes": sorted(supersedes_map[n]),
            "superseded_by": superseded_by_map[n],
            "amends": sorted(t for t in by_number[n].get("amends", []) if t in by_number),
        }
        for n in sorted(by_number)
    ]

    return {
        "decisions": decisions,
        "metadata": {"generated_by": "scripts.decisions_index"},
    }


def check_index_freshness(failed: list[str]) -> None:
    """Fail on drift OR absence of the committed docs/decisions-index.json (DCG-08).

    Unlike scripts.dependency_graph.check_export_freshness (no-op when absent, Decision 80
    lean-by-default posture for a compute-on-demand oracle), this index IS a required
    committed artifact -- absence is itself a failure, with a regenerate hint, never a silent
    no-op. repo_root-relative display mirrors check_export_freshness's ValueError fallback.
    """
    current = build_index()

    if not _EXPORT_PATH.exists():
        try:
            path_display = _EXPORT_PATH.relative_to(_REPO_ROOT)
        except ValueError:
            path_display = _EXPORT_PATH
        failed.append(
            f"Decisions index {path_display} is missing. Regenerate: bin/venv-python -m scripts.decisions_index --write"
        )
        return

    try:
        committed = json.loads(_EXPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failed.append(f"Decisions index freshness: cannot read committed export: {exc}")
        return

    if committed != current:
        try:
            path_display = _EXPORT_PATH.relative_to(_REPO_ROOT)
        except ValueError:
            path_display = _EXPORT_PATH
        failed.append(
            f"Decisions index {path_display} is stale (drifted from docs/DECISIONS.md + "
            "docs/DECISIONS_ARCHIVE.md). Regenerate: bin/venv-python -m scripts.decisions_index --write"
        )


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generated decisions index -- typed supersedes/superseded_by/amends edges (DCG-08).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help=f"Write the index to {_EXPORT_PATH}.")
    group.add_argument(
        "--check", action="store_true", help="Check freshness against the committed export; exit 1 on drift/absence."
    )
    group.add_argument("--print", action="store_true", dest="print_", help="Print the current index to stdout.")
    args = parser.parse_args()

    if args.write:
        index = build_index()
        _EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _EXPORT_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Decisions index written to {_EXPORT_PATH}", file=sys.stderr)
    elif args.check:
        failed: list[str] = []
        check_index_freshness(failed)
        if failed:
            for msg in failed:
                print(msg, file=sys.stderr)
            sys.exit(1)
        print("Decisions index is current.", file=sys.stderr)
    elif args.print_:
        _print_json(build_index())
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
