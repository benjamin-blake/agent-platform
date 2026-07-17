"""Live, cacheless, strictly-additive affected-set derivation for the --pre fast tier.

Decision affected-set-selection (amends Decision 73's fast-tier selection mechanism, its 2nd
amendment). Upgrades the --pre gate from an edited-set (test files literally in the diff) to a
live per-run affected-set (tests AFFECTED by the diff), so a source-only PR -- or a test broken
by a change it does not itself contain -- is caught pre-merge.

Unions FOUR channels over the edited-set, STRICTLY ADDITIVELY (selection can only grow, never
shrink):
  1. import-closure reverse-deps (nx.ancestors over scripts.dependency_graph.build_graph()).
  2. data-edge PRECISE match (path or quoted-token reference, never a bare substring) over
     non-.py data artifacts changed in the diff PLUS the deleted-.py-bytes case (Incident B) --
     generalises and retires scripts/validate.py's old select_roadmap_guard_tests special case.
  3. scripts.test_coverage_checker.map_source_to_test() mirror map (read-only use).
  4. conftest-subtree rule (a changed tests/**/conftest.py selects every test_*.py under it).

A ~35-module CAP protects against the import-closure channel's combinatorial blow-up: the
edited-set, DIRECT reverse-deps, and data-edge hits are NEVER deferred (the additive-only
invariant); only the TRANSITIVE residue (indirect import-closure ancestors, plus the
mirror-map/conftest-subtree channels, which are cheap/bounded in the common case but not given
the same hard protection as the three invariant-protected categories) is subject to the cap, and
any overflow is deferred LOUDLY (never silently dropped) -- the full tier still covers it.

On any internal exception, falls back to the edited-set and prints a loud warning (Decision 55:
fail loud, never silently shrink below the edited-set).

The emitted selection-manifest.json is an OUTPUT/observability artifact ONLY -- it is NEVER read
back as a selection input (no persisted selection cache, no coverage cache; this is what makes
the derivation "live" and "cacheless").
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import networkx as nx

from scripts.checks import _common
from scripts.dependency_graph import _file_to_module, build_graph
from scripts.test_coverage_checker import map_source_to_test

CAP = 35

# Same shape as scripts/validate.py's pre-existing edited-set regex (kept identical for
# continuity: the edited-set baseline must not itself narrow or widen on this change).
_EDITED_TEST_RE = re.compile(r"tests/.*test_[^/]+\.py$")

_ADDED_OR_MODIFIED = ("A", "M", "??")


def _is_changed_source_py(path: str) -> bool:
    """A non-test .py file under src/ or scripts/ -- the import-closure/mirror-map channels'
    candidate set."""
    return (
        path.endswith(".py") and (path.startswith("src/") or path.startswith("scripts/")) and not _EDITED_TEST_RE.match(path)
    )


def _module_to_test_path(module_name: str, repo_root: Path) -> str | None:
    """Map a graph module dotted-name back to an existing tests/**/test_*.py file path, or
    None (filters out package __init__ nodes and non-test modules automatically -- their
    reconstructed path either doesn't exist or doesn't match the test_ basename convention)."""
    rel = module_name.replace(".", "/") + ".py"
    if not _EDITED_TEST_RE.match(rel):
        return None
    if not (repo_root / rel).exists():
        return None
    return rel


def _import_closure_channel(changed_source_files: list[str], repo_root: Path) -> tuple[set[str], set[str]]:
    """Returns (direct, transitive_only) test-file-path sets for the import-closure channel.

    direct: test modules that DIRECTLY import a changed module (graph predecessors).
    transitive_only: the full reverse-transitive closure (nx.ancestors) MINUS direct -- the
    "transitive residue" the additive-only invariant permits deferring under the cap.
    """
    if not changed_source_files:
        return set(), set()
    graph = build_graph(repo_root=repo_root)
    direct: set[str] = set()
    transitive: set[str] = set()
    for f in changed_source_files:
        mod = _file_to_module(repo_root / f, repo_root)
        if mod is None or mod not in graph:
            continue
        for pred in graph.predecessors(mod):
            test_path = _module_to_test_path(pred, repo_root)
            if test_path:
                direct.add(test_path)
        for anc in nx.ancestors(graph, mod):
            test_path = _module_to_test_path(anc, repo_root)
            if test_path:
                transitive.add(test_path)
    transitive -= direct
    return direct, transitive


def _data_edge_reference_candidates(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(basename, relpath) candidates for the data-edge channel: any changed non-.py file
    (added/modified/untracked) PLUS any DELETED .py file (Incident B: a deleted test file's
    bytes are referenced, by basename, from a surviving meta-test)."""
    candidates: list[tuple[str, str]] = []
    for status, path in entries:
        is_py = path.endswith(".py")
        if is_py and status != "D":
            continue
        candidates.append((Path(path).name, path))
    return candidates


def _quoted_token_pattern(basename: str) -> re.Pattern[str]:
    """PRECISE quoted-token match: the basename must appear as a whole quoted string, optionally
    with a path prefix ending in '/', e.g. "ROADMAP-PLATFORM.yaml" or "docs/ROADMAP-PLATFORM.yaml".
    Deliberately NOT a bare substring match -- a common basename (config.py, utils.py,
    __init__.py) embedded inside a longer, unrelated identifier (e.g. "myconfig.py_backup")
    must not match."""
    return re.compile(r"['\"]([^'\"]*/)?" + re.escape(basename) + r"['\"]")


def _data_edge_channel(entries: list[tuple[str, str]], repo_root: Path) -> set[str]:
    """Single-pass scan of tests/**/*.py: a hit is either the full candidate PATH appearing
    literally in the text, or the candidate's basename appearing as a precise quoted token
    (never a bare substring) -- see _quoted_token_pattern."""
    candidates = _data_edge_reference_candidates(entries)
    if not candidates:
        return set()
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return set()
    compiled = [(relpath, _quoted_token_pattern(basename)) for basename, relpath in candidates]
    hits: set[str] = set()
    for path in sorted(tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel_test = path.relative_to(repo_root).as_posix()
        for relpath, quoted_re in compiled:
            if relpath in text or quoted_re.search(text):
                hits.add(rel_test)
                break
    return hits


def _mirror_map_channel(changed_source_files: list[str], repo_root: Path) -> set[str]:
    """Read-only use of scripts.test_coverage_checker.map_source_to_test() (channel 3)."""
    hits: set[str] = set()
    for f in changed_source_files:
        result = map_source_to_test(repo_root / f)
        if result is None:
            continue
        if result.suffix == ".py":
            if result.exists():
                hits.add(result.relative_to(repo_root).as_posix())
        elif result.is_dir():
            hits.add(result.relative_to(repo_root).as_posix())
    return hits


def _conftest_subtree_channel(entries: list[tuple[str, str]], repo_root: Path) -> set[str]:
    """A changed (added/modified) tests/**/conftest.py selects every test_*.py in its subtree
    (pytest's conftest fixtures apply to the whole directory beneath it)."""
    hits: set[str] = set()
    for status, path in entries:
        if status not in _ADDED_OR_MODIFIED:
            continue
        if Path(path).name != "conftest.py":
            continue
        if not (path == "tests/conftest.py" or path.startswith("tests/")):
            continue
        conftest_dir = (repo_root / path).parent
        if not conftest_dir.is_dir():
            continue
        for test_file in sorted(conftest_dir.rglob("test_*.py")):
            hits.add(test_file.relative_to(repo_root).as_posix())
    return hits


def _current_sha(repo_root: Path) -> str:
    result = _common.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _empty_manifest(
    sha: str, entries: list[tuple[str, str]], edited_set: list[str], elapsed: float, cap: int
) -> dict[str, Any]:
    return {
        "sha": sha,
        "diff": [{"status": status, "path": path} for status, path in entries],
        "edited_set": edited_set,
        "selected": edited_set,
        "provenance": dict.fromkeys(edited_set, "edited_set"),
        "capped": False,
        "deferred": [],
        "cap": cap,
        "timings": {"total_s": elapsed},
    }


def derive_affected_tests(
    diff_entries: list[tuple[str, str]],
    *,
    repo_root: Path | None = None,
    cap: int = CAP,
) -> dict[str, Any]:
    """Derive the live affected test-selection set for one --pre run.

    diff_entries: the status-aware diff (scripts.checks._common.get_status_aware_diff()) --
    (status, path) tuples covering A/M/D and untracked ("??") paths.

    Returns {"selected": [...], "manifest": {...}}. NEVER reads any prior manifest (the manifest
    is output-only); on an internal exception, falls back to the edited-set with a loud warning.
    """
    t0 = time.monotonic()
    root = repo_root if repo_root is not None else _common.ROOT
    entries = list(diff_entries)
    sha = _current_sha(root)

    edited_set = sorted({path for status, path in entries if status in _ADDED_OR_MODIFIED and _EDITED_TEST_RE.match(path)})

    if not entries:
        manifest = _empty_manifest(sha, entries, edited_set, time.monotonic() - t0, cap)
        return {"selected": edited_set, "manifest": manifest}

    try:
        changed_source_files = [
            path for status, path in entries if status in _ADDED_OR_MODIFIED and _is_changed_source_py(path)
        ]

        direct, transitive = _import_closure_channel(changed_source_files, root)
        data_edge_hits = _data_edge_channel(entries, root)
        mirror_hits = _mirror_map_channel(changed_source_files, root)
        conftest_hits = _conftest_subtree_channel(entries, root)

        protected = set(edited_set) | direct | data_edge_hits
        residue_pool = (transitive | mirror_hits | conftest_hits) - protected

        budget_remaining = max(cap - len(protected), 0)
        residue_sorted = sorted(residue_pool)
        kept_residue = residue_sorted[:budget_remaining]
        deferred_residue = residue_sorted[budget_remaining:]

        provenance: dict[str, str] = {}
        for p in edited_set:
            provenance[p] = "edited_set"
        for p in direct:
            provenance.setdefault(p, "import_closure_direct")
        for p in data_edge_hits:
            provenance.setdefault(p, "data_edge")
        for p in kept_residue:
            if p in mirror_hits:
                provenance.setdefault(p, "mirror_map")
            elif p in conftest_hits:
                provenance.setdefault(p, "conftest_subtree")
            else:
                provenance.setdefault(p, "import_closure_transitive")

        selected = sorted(protected | set(kept_residue))
        capped = bool(deferred_residue)

        if capped:
            print(
                f"\n=== AFFECTED-SET CAP: deferring {len(deferred_residue)} transitive-residue "
                f"test module(s) (cap={cap}) -- the full post-merge tier still covers these ==="
            )
            for p in deferred_residue:
                print(f"  DEFERRED (transitive residue): {p}")

        manifest = {
            "sha": sha,
            "diff": [{"status": status, "path": path} for status, path in entries],
            "edited_set": edited_set,
            "selected": selected,
            "provenance": provenance,
            "capped": capped,
            "deferred": deferred_residue,
            "cap": cap,
            "timings": {"total_s": time.monotonic() - t0},
        }
        return {"selected": selected, "manifest": manifest}
    except Exception as exc:  # noqa: BLE001 -- Decision 55: fail loud, fall back, never crash --pre
        print(
            f"\n=== AFFECTED-SET DERIVATION FAILED -- FALLING BACK TO EDITED-SET (Decision 55) ===\n"
            f"{exc!r}\nSelection: the edited-set only ({len(edited_set)} file(s)). "
            "This is a LOUD fallback, not a silent shrink."
        )
        manifest = _empty_manifest(sha, entries, edited_set, time.monotonic() - t0, cap)
        manifest["fallback"] = True
        manifest["fallback_reason"] = repr(exc)
        return {"selected": edited_set, "manifest": manifest}


def _upload_manifest_best_effort(manifest: dict[str, Any]) -> None:
    """Best-effort S3 upload of the selection manifest (Decision 55: LOUD skip, never silent,
    never raising -- and never counted against the 5-min fast-tier budget assertion). Lazily
    imports boto3 so the no-creds fast tier (requirements-fast.txt omits boto3) degrades
    gracefully instead of breaking --pre."""
    bucket = os.environ.get("S3_LOG_BUCKET", "").strip()
    if not bucket:
        print("Selection manifest: S3_LOG_BUCKET not set -- skipping best-effort S3 upload (loud skip).")
        return
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        print("Selection manifest: boto3 not installed -- skipping best-effort S3 upload (loud skip, Decision 55).")
        return
    try:
        from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

        profile = resolve_aws_profile(default="agent_platform")
        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        client = session.client("s3", region_name="eu-west-2")
        sha = manifest.get("sha", "unknown")
        key = f"ci/selection/{sha}/selection-manifest.json"
        client.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        print(f"Selection manifest uploaded to s3://{bucket}/{key}")
    except Exception as exc:  # noqa: BLE001 -- Decision 55: loud skip, never raise (best-effort/async)
        print(f"Selection manifest: best-effort S3 upload failed -- loud skip (Decision 55): {exc!r}")


def emit_manifest(manifest: dict[str, Any], *, repo_root: Path | None = None) -> Path:
    """Print, write (gitignored path), and best-effort-upload the selection manifest.

    The manifest is NEVER read back as a selection input -- this function is write/print-only.
    The local write is best-effort (Decision 55: LOUD skip, never silent, never raising) --
    an observability artifact must never crash the --pre gate on a local disk I/O error, the
    same philosophy already applied to the S3 upload leg below.
    """
    root = repo_root if repo_root is not None else _common.ROOT
    print("\n=== Affected-set selection manifest ===")
    rendered = json.dumps(manifest, indent=2, sort_keys=True)
    print(rendered)
    manifest_path = root / "logs" / "debug" / "selection-manifest.json"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"Selection manifest: local write to {manifest_path} failed -- loud skip (Decision 55): {exc!r}")
    _upload_manifest_best_effort(manifest)
    return manifest_path
