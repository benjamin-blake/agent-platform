"""Repo-wide sanctioned-prose gate (Decision 127 expanding Decision 86).

Every git-tracked .md file must classify as either a permanent agent-instruction prose
class (`prose_allowlist.allowed_globs` in docs/contracts/file-router.yaml) or a day-one
grandfathered file (`prose_allowlist.grandfathered_globs`, ratchet-only -- may only shrink
in later plans, never grow). Scope is repo-wide over ALL tracked .md files, distinct from
validate_intent_doc_freeze (docs/INTENT-*.md existence, gated by the intent-migration
MANIFEST.yaml disposition state). The two guards may overlap on the docs/INTENT-*.md
subset -- that overlap is redundant, not conflicting; validate_intent_doc_freeze is the
primary owner for whether a given INTENT doc may still exist at all, while this guard only
asks whether a currently-tracked .md file (INTENT or otherwise) is in a sanctioned class.

Fail-open (warning, no failure) if the `prose_allowlist` key is absent or unreadable, mirroring
the docs_root_allowlist / intent-doc-freeze precedent -- an unconfigured guard must never block
the build.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.checks import _common, registry

_DEFAULT_ROUTER_PATH = _common.ROOT / "docs" / "contracts" / "file-router.yaml"

_SEGMENT_TOKEN = re.compile(r"\*\*|\*|\?|[^*?]+")


def _segment_to_regex(segment: str) -> str:
    """Translate a single slash-free glob segment to regex, keeping `*`/`?` slash-safe."""
    pieces = []
    for tok in _SEGMENT_TOKEN.findall(segment):
        if tok == "*":
            pieces.append("[^/]*")
        elif tok == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(tok))
    return "".join(pieces)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a glob with genuine recursive `**` (zero-or-more full path segments).

    Unlike fnmatch.fnmatch (no `**` concept) and pathlib.PurePath.match (degrades `**` to a
    single segment in Python 3.12), a `**` segment here matches zero or more whole
    "name/"-style segments, so `docs/contracts/**/*.md` matches both
    `docs/contracts/foo.md` (zero reps) and `docs/contracts/sub/foo.md` (one rep).
    """
    segments = pattern.split("/")
    regex = "^"
    last = len(segments) - 1
    for i, seg in enumerate(segments):
        if seg == "**":
            regex += r"(?:[^/]+/)*"
            continue
        regex += _segment_to_regex(seg)
        if i != last:
            regex += "/"
    regex += "$"
    return re.compile(regex)


def path_allowed(path: str, globs: list[str]) -> bool:
    """True if `path` matches any glob in `globs` under the recursive-`**` matcher above."""
    return any(_glob_to_regex(g).match(path) for g in globs)


def _load_prose_allowlist(path: Path) -> tuple[list[str], list[str], bool, str | None]:
    """Parse the `prose_allowlist` sibling key from the router file.

    Returns (allowed_globs, grandfathered_globs, fail_open, error):
      - fail_open=True  -> the router file/key is absent or unreadable (missing file, parse
        error, missing key). The caller prints a warning and skips -- never a failure.
      - fail_open=False, error=None -> the key parsed and is well-formed; proceed to check.
      - fail_open=False, error=<msg> -> the key is PRESENT but malformed (wrong shape). This
        is a configuration bug in the router file itself, not an absence/unreadability case,
        so it is a hard failure, not fail-open.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], [], True, f"could not read/parse {path}: {exc}"
    if not isinstance(data, dict) or "prose_allowlist" not in data:
        return [], [], True, None
    block = data["prose_allowlist"]
    if not isinstance(block, dict):
        return [], [], False, "prose_allowlist is not a mapping"
    allowed = block.get("allowed_globs", [])
    grandfathered = block.get("grandfathered_globs", [])
    if not isinstance(allowed, list) or any(not isinstance(x, str) or not x for x in allowed):
        return [], [], False, "prose_allowlist.allowed_globs must be a list of non-empty strings"
    if not isinstance(grandfathered, list) or any(not isinstance(x, str) or not x for x in grandfathered):
        return [], [], False, "prose_allowlist.grandfathered_globs must be a list of non-empty strings"
    return list(allowed), list(grandfathered), False, None


def _tracked_md_files() -> list[str]:
    """`git ls-files '*.md'` -- tracked-only, so an untracked scratch file never trips this."""
    result = _common.run(["git", "ls-files", "*.md"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


@registry.register("validate_prose_allowlist", owner="platform")
def validate_prose_allowlist(failed: list[str], router_path: Path | None = None) -> None:
    """Fail on any tracked .md file matching neither allowed_globs nor grandfathered_globs.

    router_path: override for test isolation (defaults to ROOT/docs/contracts/file-router.yaml).
    """
    print("\n=== Sanctioned-prose allowlist (Decision 127) ===")
    path = router_path if router_path is not None else _DEFAULT_ROUTER_PATH

    allowed, grandfathered, fail_open, error = _load_prose_allowlist(path)
    if fail_open:
        suffix = f" ({error})" if error else " (no prose_allowlist key configured)"
        print(f"  SKIP: prose_allowlist unavailable{suffix} -- fail-open.")
        return
    if error is not None:
        failed.append(f"Prose allowlist: {error}")
        return

    all_globs = allowed + grandfathered
    unmatched = [p for p in sorted(_tracked_md_files()) if not path_allowed(p, all_globs)]

    if unmatched:
        failed.append(
            "Prose allowlist: tracked .md file(s) matching neither allowed_globs nor "
            "grandfathered_globs (Decision 127): " + ", ".join(unmatched)
        )
    else:
        print(
            f"  PASS: every tracked .md file is allowed or grandfathered "
            f"({len(allowed)} allowed, {len(grandfathered)} grandfathered globs)."
        )
