"""Link-validity gate for docs/contracts/file-router.yaml (RS-04, Decision 104).

Every non-runtime route target must resolve to a git-tracked file or directory; runtime
(read-cache) rows assert their parent directory is tracked instead, since a `git ls-files`
snapshot never contains an untracked/gitignored path. Duplicate topics and malformed rows
are gate failures too. Import-safe throughout: never raises, always appends to `failed` and
returns on any missing-file / unparseable / malformed-shape problem.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

from scripts.checks import _common, registry

_DEFAULT_ROUTER_PATH = _common.ROOT / "docs" / "contracts" / "file-router.yaml"


def _load_router(path: Path) -> list | str:
    """Load the router and validate its top-level shape.

    Returns the non-empty `routes` list on success, or an error-message string on a missing
    file, unparseable YAML, a non-mapping top level, or a missing/empty/non-list `routes`.
    The list-vs-str return is a discriminated union the caller narrows by isinstance -- this
    keeps the module raise-free (no assert) while still satisfying the type checker.
    """
    if not path.is_file():
        return f"{path} does not exist"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return f"could not read/parse {path}: {exc}"
    if not isinstance(data, dict):
        return f"{path} is not a YAML mapping"
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        return f"{path} 'routes' is missing or not a non-empty list"
    return routes


def _validate_routes_shape(routes: list) -> tuple[list[dict], list[str], set[str]]:
    """Iterate the routes LIST (never rely on mapping-key uniqueness -- yaml.safe_load
    would silently collapse duplicate mapping keys, making a duplicate-topic gate
    unconstructable). Returns (valid_routes, malformed messages, duplicate topics).

    A route survives to `valid` only if its topic is a non-empty str AND every element of its
    targets is a non-empty str -- so the dead-target scan below never calls a str method on a
    non-str element (e.g. a `targets: [42]` typo a future relocation edit could introduce).
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
        bad_targets = [t for t in targets if not isinstance(t, str) or not t]
        if bad_targets:
            malformed.append(f"route {topic!r}: non-string/empty target(s): {bad_targets!r}")
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
    directory (some snapshot path starts with target.rstrip('/') + '/'). Every target is a
    non-empty str here (guaranteed by _validate_routes_shape).
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


def _load_docs_root_allowlist(path: Path) -> tuple[set[str] | None, list[str], str | None]:
    """Parse the optional `docs_root_allowlist` sibling key from the router file.

    Returns (allowed_files, grandfathered_globs, error):
      - (None, [], None)   -> key ABSENT: rule not configured; caller skips the docs-root scan.
      - (set, list, None)  -> key present and well-formed: caller runs the scan.
      - (None, [], "msg")  -> key present but malformed: caller appends the failure.
    Never raises.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [], f"could not read/parse {path}: {exc}"
    if not isinstance(data, dict) or "docs_root_allowlist" not in data:
        return None, [], None
    block = data["docs_root_allowlist"]
    if not isinstance(block, dict):
        return None, [], "docs_root_allowlist is not a mapping"
    allowed = block.get("allowed_files", [])
    globs = block.get("grandfathered_globs", [])
    if not isinstance(allowed, list) or any(not isinstance(x, str) or not x for x in allowed):
        return None, [], "docs_root_allowlist.allowed_files must be a list of non-empty strings"
    if not isinstance(globs, list) or any(not isinstance(x, str) or not x for x in globs):
        return None, [], "docs_root_allowlist.grandfathered_globs must be a list of non-empty strings"
    return set(allowed), list(globs), None


def _docs_root_stray_files(tracked: set[str], allowed: set[str], globs: list[str]) -> list[str]:
    """Depth-1 tracked files under docs/ that are neither allowlisted nor grandfathered."""
    strays: list[str] = []
    for path_str in sorted(tracked):
        if not path_str.startswith("docs/"):
            continue
        rest = path_str[len("docs/") :]
        if not rest or "/" in rest:
            continue
        if rest in allowed or any(fnmatch.fnmatch(rest, g) for g in globs):
            continue
        strays.append(path_str)
    return strays


def _load_scripts_root_allowlist(path: Path) -> tuple[set[str] | None, list[str], str | None]:
    """Parse the optional `scripts_root_allowlist` sibling key from the router file.

    Same tolerant shape as `_load_docs_root_allowlist`: (allowed_files, grandfathered_globs, error).
      - (None, [], None)   -> key ABSENT: rule not configured; caller skips the scripts-root scan.
      - (set, list, None)  -> key present and well-formed: caller runs the scan.
      - (None, [], "msg")  -> key present but malformed: caller appends the failure.
    Never raises.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [], f"could not read/parse {path}: {exc}"
    if not isinstance(data, dict) or "scripts_root_allowlist" not in data:
        return None, [], None
    block = data["scripts_root_allowlist"]
    if not isinstance(block, dict):
        return None, [], "scripts_root_allowlist is not a mapping"
    allowed = block.get("allowed_files", [])
    globs = block.get("grandfathered_globs", [])
    if not isinstance(allowed, list) or any(not isinstance(x, str) or not x for x in allowed):
        return None, [], "scripts_root_allowlist.allowed_files must be a list of non-empty strings"
    if not isinstance(globs, list) or any(not isinstance(x, str) or not x for x in globs):
        return None, [], "scripts_root_allowlist.grandfathered_globs must be a list of non-empty strings"
    return set(allowed), list(globs), None


def _scripts_root_stray_files(tracked: set[str], allowed: set[str], globs: list[str]) -> list[str]:
    """Depth-1 tracked files under scripts/ that are neither allowlisted nor grandfathered."""
    strays: list[str] = []
    for path_str in sorted(tracked):
        if not path_str.startswith("scripts/"):
            continue
        rest = path_str[len("scripts/") :]
        if not rest or "/" in rest:
            continue
        if rest in allowed or any(fnmatch.fnmatch(rest, g) for g in globs):
            continue
        strays.append(path_str)
    return strays


@registry.register("validate_placement", owner="platform")
def validate_placement(failed: list[str], router_path: Path | None = None) -> None:
    """Link-validity gate (RS-04): every docs/contracts/file-router.yaml target must
    resolve to a git-tracked path. Import-safe -- never raises; appends a clear failure
    and returns early on any missing-file / malformed-shape problem.

    router_path: override for test isolation (defaults to ROOT/docs/contracts/file-router.yaml).
    """
    print("\n=== File router placement check (RS-04) ===")
    path = router_path if router_path is not None else _DEFAULT_ROUTER_PATH

    loaded = _load_router(path)
    if isinstance(loaded, str):
        failed.append(f"File router placement: {loaded}")
        return

    valid_routes, malformed, duplicate_topics = _validate_routes_shape(loaded)

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

    print("\n=== Docs-root allowlist check (RS-03) ===")
    allowed, globs, allow_err = _load_docs_root_allowlist(path)
    if allow_err is not None:
        failed.append(f"Docs-root allowlist: {allow_err}")
    elif allowed is None:
        print("  SKIP: no docs_root_allowlist key configured.")
    else:
        strays = _docs_root_stray_files(tracked, allowed, globs)
        if strays:
            failed.append("Docs-root allowlist: out-of-class docs-root file(s) (RS-03): " + ", ".join(strays))
        else:
            print(f"  PASS: docs/ root within allowlist ({len(allowed)} allowed, {len(globs)} grandfathered).")

    print("\n=== Scripts-root allowlist check (RS-01) ===")
    scripts_allowed, scripts_globs, scripts_allow_err = _load_scripts_root_allowlist(path)
    if scripts_allow_err is not None:
        failed.append(f"Scripts-root allowlist: {scripts_allow_err}")
    elif scripts_allowed is None:
        print("  SKIP: no scripts_root_allowlist key configured.")
    else:
        scripts_strays = _scripts_root_stray_files(tracked, scripts_allowed, scripts_globs)
        if scripts_strays:
            failed.append("Scripts-root allowlist: out-of-class scripts-root file(s) (RS-01): " + ", ".join(scripts_strays))
        else:
            n_allowed, n_globs = len(scripts_allowed), len(scripts_globs)
            print(f"  PASS: scripts/ root within allowlist ({n_allowed} allowed, {n_globs} grandfathered).")
