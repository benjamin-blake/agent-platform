"""Link-validity gate for docs/contracts/file-router.yaml (RS-04, Decision 104).

Every non-runtime route target must resolve to a git-tracked file or directory; runtime
(read-cache) rows assert their parent directory is tracked instead, since a `git ls-files`
snapshot never contains an untracked/gitignored path. Duplicate topics and malformed rows
are gate failures too. Import-safe throughout: never raises, always appends to `failed` and
returns on any missing-file / unparseable / malformed-shape problem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_DEFAULT_ROUTER_PATH = _common.ROOT / "docs" / "contracts" / "file-router.yaml"


def _load_router(path: Path) -> tuple[dict | None, str | None]:
    """Load and structurally validate the router's top-level shape.

    Returns (data, None) on success, or (None, error-message) on a missing file,
    unparseable YAML, a non-mapping top level, or a missing/empty/non-list `routes`.
    """
    if not path.is_file():
        return None, f"{path} does not exist"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, f"could not read/parse {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} is not a YAML mapping"
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        return None, f"{path} 'routes' is missing or not a non-empty list"
    return data, None


def _validate_routes_shape(routes: list) -> tuple[list[dict], list[str], set[str]]:
    """Iterate the routes LIST (never rely on mapping-key uniqueness -- yaml.safe_load
    would silently collapse duplicate mapping keys, making a duplicate-topic gate
    unconstructable). Returns (valid_routes, malformed messages, duplicate topics).
    """
    malformed: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    valid: list[dict] = []
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            malformed.append(f"route #{idx} is not a mapping")
            continue
        topic = route.get("topic")
        targets = route.get("targets")
        if not isinstance(topic, str) or not topic:
            malformed.append(f"route #{idx} missing a non-empty 'topic'")
            continue
        if not isinstance(targets, list) or not targets:
            malformed.append(f"route {topic!r} missing a non-empty 'targets' list")
            continue
        if topic in seen:
            duplicates.add(topic)
        seen.add(topic)
        valid.append(route)
    return valid, malformed, duplicates


def _snapshot_tracked_paths() -> set[str]:
    """One `git ls-files` snapshot of every tracked path, repo-root-relative.

    Mirrors _common.get_changed_files -- without capture_output/text the snapshot is
    empty and every directory target would read as dead.
    """
    result = _common.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
    if result.returncode != 0:
        return set()
    return set(result.stdout.splitlines())


def _dead_targets_for_route(route: dict, tracked: set[str]) -> list[str]:
    """A runtime row's target need only have its parent dir tracked (the file itself may
    be gitignored); a non-runtime row's target must itself be a tracked file, or a tracked
    directory (some snapshot path starts with target.rstrip('/') + '/').
    """
    topic = route["topic"]
    is_runtime = bool(route.get("runtime", False))
    dead: list[str] = []
    for target in route["targets"]:
        if is_runtime:
            parent = target.rsplit("/", 1)[0] + "/" if "/" in target else ""
            if not any(t.startswith(parent) for t in tracked):
                dead.append(f"{topic}: runtime target {target!r} parent dir not tracked")
        else:
            normalized = target.rstrip("/")
            if not (target in tracked or any(t.startswith(normalized + "/") for t in tracked)):
                dead.append(f"{topic}: target {target!r} not a tracked file or directory")
    return dead


@registry.register("validate_placement", owner="platform")
def validate_placement(failed: list[str], router_path: Path | None = None) -> None:
    """Link-validity gate (RS-04): every docs/contracts/file-router.yaml target must
    resolve to a git-tracked path. Import-safe -- never raises; appends a clear failure
    and returns early on any missing-file / malformed-shape problem.

    router_path: override for test isolation (defaults to ROOT/docs/contracts/file-router.yaml).
    """
    print("\n=== File router placement check (RS-04) ===")
    path = router_path if router_path is not None else _DEFAULT_ROUTER_PATH

    data, load_error = _load_router(path)
    if load_error is not None:
        failed.append(f"File router placement: {load_error}")
        return

    valid_routes, malformed, duplicate_topics = _validate_routes_shape(data["routes"])

    tracked = _snapshot_tracked_paths()
    dead_targets: list[str] = []
    for route in valid_routes:
        dead_targets.extend(_dead_targets_for_route(route, tracked))

    if malformed:
        failed.append("File router placement: malformed route(s): " + "; ".join(malformed))
    if duplicate_topics:
        failed.append("File router placement: duplicate topic(s): " + ", ".join(sorted(duplicate_topics)))
    if dead_targets:
        failed.append("File router placement: dead target(s): " + "; ".join(dead_targets))

    if not (malformed or duplicate_topics or dead_targets):
        print(f"  PASS: {len(valid_routes)} route(s), zero dead targets.")
