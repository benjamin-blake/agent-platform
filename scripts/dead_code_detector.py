# complexity-waiver: decision-43
"""Deterministic dead/orphan source-code detector (T3.13, Decision 75 frame-lock).

Combines T3.12 graph reachability with a grep cross-check to produce a two-tier
verdict: high-confidence dead (graph-unreachable AND grep-absent) vs low-confidence
dynamically-referenced (graph-unreachable but referenced on some non-graph surface).
No LLM. No auto-deletion -- mark-then-surface only (Decision 55).
CLI: --granularity module|symbol.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.dependency_graph import KNOWN_UNSOUND, build_graph, roots

_REPO_ROOT = Path(__file__).parent.parent

_GREP_PY_DIRS: tuple[str, ...] = ("src", "scripts", "tests")
_GREP_GLOB_SURFACES: tuple[str, ...] = (
    "src/lambdas/*/manifest.yaml",
    "**/*.tf",
    "*.prompt.md",
    ".github/workflows/*.yml",
    ".github/agents/schedule.yaml",
    ".claude/**/*.md",
)


def _module_short_name(dotted: str) -> str:
    """Return the last-dotted component of a module or symbol name."""
    return dotted.rsplit(".", 1)[-1]


def _module_to_file(module: str, repo_root: Path) -> Path | None:
    """Best-effort reverse of dependency_graph._file_to_module for a module node."""
    rel = Path(*module.split("."))
    as_file = repo_root / rel.parent / f"{rel.name}.py"
    if as_file.is_file():
        return as_file
    as_package_init = repo_root / rel / "__init__.py"
    if as_package_init.is_file():
        return as_package_init
    return None


def _gather_grep_surfaces(repo_root: Path) -> list[Path]:
    """Enumerate every text surface searched for cross-check references."""
    surfaces: list[Path] = []
    for dir_name in _GREP_PY_DIRS:
        d = repo_root / dir_name
        if d.is_dir():
            surfaces.extend(sorted(d.rglob("*.py")))
    for pattern in _GREP_GLOB_SURFACES:
        surfaces.extend(sorted(repo_root.glob(pattern)))
    # De-dupe while preserving determinism.
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in surfaces:
        if p not in seen and p.is_file():
            seen.add(p)
            ordered.append(p)
    return sorted(ordered)


def _candidate_defining_file(candidate: str, kind: str, repo_root: Path) -> Path | None:
    """Return the source file that defines this candidate (excluded from its own grep search)."""
    module = candidate.rsplit(".", 1)[0] if kind == "symbol" else candidate
    return _module_to_file(module, repo_root)


def _grep_references(
    candidate: str,
    kind: str,
    surfaces: list[Path],
    defining_file: Path | None,
    repo_root: Path,
) -> list[str]:
    """Return sorted list of surface paths (relative to repo_root) referencing candidate.

    Searches the short (last-dotted) name; for module candidates also the full dotted path.
    The defining file itself is excluded so a module's own declaration doesn't count as a hit.
    """
    short = _module_short_name(candidate)
    needles = [short] if kind == "symbol" else [short, candidate]
    hits: list[str] = []
    for surface in surfaces:
        if defining_file is not None and surface == defining_file:
            continue
        try:
            text = surface.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(needle in text for needle in needles):
            hits.append(str(surface.relative_to(repo_root)))
    return sorted(set(hits))


def _compute_reachable_set(graph: Any) -> set[str]:
    """Union of every declared root plus its transitive descendants (single pass)."""
    import networkx as nx  # noqa: PLC0415

    reachable: set[str] = set()
    for r in roots(graph):
        reachable.add(r)
        if r in graph:
            reachable.update(nx.descendants(graph, r))
    return reachable


def _candidates(graph: Any, granularity: str) -> list[tuple[str, str]]:
    """Return sorted (name, kind) candidates: src/scripts non-test nodes unreachable from roots."""
    reachable = _compute_reachable_set(graph)
    out: list[tuple[str, str]] = []
    for node, data in graph.nodes(data=True):
        kind = data.get("kind")
        if kind not in ("module", "symbol"):
            continue
        if kind == "symbol" and granularity != "symbol":
            continue
        top = node.split(".", 1)[0]
        if top not in ("src", "scripts"):
            continue
        if node in reachable:
            continue
        out.append((node, kind))
    return sorted(out)


def detect(repo_root: Path | None = None, granularity: str = "module") -> dict[str, Any]:
    """Run the two-tier dead/orphan detector and return a deterministic result dict."""
    root = repo_root if repo_root is not None else _REPO_ROOT
    graph = build_graph(repo_root=root, granularity=granularity)
    surfaces = _gather_grep_surfaces(root)

    high_confidence: list[dict[str, str]] = []
    low_confidence: list[dict[str, Any]] = []

    for name, kind in _candidates(graph, granularity):
        defining_file = _candidate_defining_file(name, kind, root)
        references = _grep_references(name, kind, surfaces, defining_file, root)
        if references:
            low_confidence.append(
                {
                    "name": name,
                    "kind": kind,
                    "referenced_by": references,
                }
            )
        else:
            high_confidence.append({"name": name, "kind": kind})

    high_confidence.sort(key=lambda e: e["name"])
    low_confidence.sort(key=lambda e: e["name"])

    return {
        "high_confidence_dead": high_confidence,
        "low_confidence_dynamically_referenced": low_confidence,
        "summary": {
            "granularity": granularity,
            "high_confidence_count": len(high_confidence),
            "low_confidence_count": len(low_confidence),
        },
        "metadata": {
            "generated_by": "scripts.dead_code_detector",
            "known_unsound": KNOWN_UNSOUND,
        },
    }


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic dead/orphan source-code detector (T3.13).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--granularity",
        choices=["module", "symbol"],
        default="module",
        help="module (default) or symbol (adds function/class candidates).",
    )
    args = parser.parse_args()
    result = detect(granularity=args.granularity)
    _print_json(result)


if __name__ == "__main__":
    main()
