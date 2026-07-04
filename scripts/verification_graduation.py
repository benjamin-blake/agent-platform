"""Real differential-admission producer for the verification graduation registry (VF-05/VF-06).

Materializes a runnable kernel check (``scripts.verification_checks``) from a registry row's
``check_spec``, repointing path/cwd to a given tree root, and executes the differential
admission gate against a REAL git worktree -- never a simulated revert (Decision 55):

- Kernel entries (VF-06 c2): revert leg checks out origin/main in a temp worktree (the check
  is self-contained per its check_spec).
- Brand-new verifiers (VF-06 c3): the verifier does not exist on origin/main, so the revert
  leg checks out HEAD in a temp worktree and reverts only the covered changed files to their
  origin/main content, then runs the verifier subprocess there.

Import-pure: no filesystem or network access at import time. Worktree/materialize/revert
failures raise ``GraduationError`` (fail-loud) -- there is no silent "none graduated" path for
an error; an empty candidate set is the only legitimate case for recording nothing.
"""

from __future__ import annotations

import ast
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from scripts.checks.verification.validate_verifier_hermeticity import _verifier_is_non_hermetic
from scripts.verification_checks import (
    CANONICAL_SLOTS,
    BaseCheck,
    CheckResult,
    CheckStatus,
    CommandExitZeroCheck,
    CommandOutputMatchesCheck,
    FileAbsentCheck,
    FileExistsCheck,
    GrepCountCheck,
    MetricUnderThresholdCheck,
    TestSelectorCheck,
    is_admitted,
)

ROOT = Path(__file__).resolve().parent.parent


class GraduationError(RuntimeError):
    """Raised on any worktree/materialize/revert failure (fail-loud, Decision 55)."""


# ---------------------------------------------------------------------------
# Materialization: registry row (check_spec) -> a runnable kernel check
# ---------------------------------------------------------------------------


def _repoint_path(path: str, tree_root: str | Path | None) -> str:
    if tree_root is None:
        return path
    p = Path(path)
    return str(p) if p.is_absolute() else str(Path(tree_root) / p)


def materialize_check_in_tree(row: dict, tree_root: str | Path | None) -> BaseCheck:
    """Build a runnable kernel check from a registry row, repointed at ``tree_root``.

    ``tree_root`` of None means "the live tree" (no repointing of path/cwd fields).
    Raises GraduationError on an unknown slot or a check_spec missing a required key.
    """
    slot = row.get("primitive_slot")
    if slot not in CANONICAL_SLOTS:
        raise GraduationError(
            f"check_id={row.get('check_id')!r}: unknown primitive_slot {slot!r} (not in CD.29 CANONICAL_SLOTS)"
        )

    spec = row.get("check_spec") or {}
    check_id = row.get("check_id", "graduated-check")
    cwd = str(tree_root) if tree_root is not None else None

    def _require(*keys: str) -> None:
        missing = [k for k in keys if k not in spec]
        if missing:
            raise GraduationError(f"check_id={check_id!r} slot={slot!r}: check_spec missing required key(s): {missing}")

    if slot == "command_exit_zero":
        _require("command")
        return CommandExitZeroCheck(name=check_id, command=list(spec["command"]), cwd=cwd)
    if slot == "command_output_matches":
        _require("command", "expected")
        return CommandOutputMatchesCheck(
            name=check_id,
            command=list(spec["command"]),
            expected=spec["expected"],
            use_regex=bool(spec.get("use_regex", False)),
            cwd=cwd,
        )
    if slot == "file_presence":
        _require("path")
        path = _repoint_path(spec["path"], tree_root)
        mode = spec.get("mode", "exists")
        if mode not in ("exists", "absent"):
            raise GraduationError(f"check_id={check_id!r}: file_presence mode must be 'exists' or 'absent', got {mode!r}")
        return FileAbsentCheck(name=check_id, path=path) if mode == "absent" else FileExistsCheck(name=check_id, path=path)
    if slot == "grep_count":
        _require("path", "pattern")
        path = _repoint_path(spec["path"], tree_root)
        return GrepCountCheck(
            name=check_id,
            path=path,
            pattern=spec["pattern"],
            operator=spec.get("operator", "eq"),
            count=int(spec.get("count", 0)),
        )
    if slot == "test_selector":
        _require("node_id")
        return TestSelectorCheck(name=check_id, node_id=spec["node_id"], cwd=cwd)
    if slot == "metric_under_threshold":
        _require("command", "threshold")
        return MetricUnderThresholdCheck(
            name=check_id,
            command=list(spec["command"]),
            threshold=float(spec["threshold"]),
            cwd=cwd,
        )
    raise GraduationError(f"check_id={check_id!r}: slot {slot!r} has no materializer wired up")  # pragma: no cover


def materialize_check(row: dict) -> BaseCheck:
    """Materialize a check against the live tree (no tree-root repointing)."""
    return materialize_check_in_tree(row, None)


# ---------------------------------------------------------------------------
# Real git worktree revert
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")


@contextlib.contextmanager
def git_worktree(ref: str, repo_root: Path | None = None) -> Iterator[Path]:
    """Check out ``ref`` into a temporary git worktree; remove it on exit.

    Raises GraduationError on any git failure (fail-loud, Decision 55).
    """
    root = Path(repo_root) if repo_root is not None else ROOT
    tmp_parent = tempfile.mkdtemp(prefix="verif-graduation-")
    wt_path = Path(tmp_parent) / "wt"
    add_result = _run_git(["worktree", "add", "--detach", str(wt_path), ref], root)
    if add_result.returncode != 0:
        shutil.rmtree(tmp_parent, ignore_errors=True)
        raise GraduationError(f"git worktree add failed for ref {ref!r}: {add_result.stderr.strip()}")
    try:
        yield wt_path
    finally:
        remove_result = _run_git(["worktree", "remove", "--force", str(wt_path)], root)
        if remove_result.returncode != 0:
            _run_git(["worktree", "prune"], root)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def make_worktree_revert_runner(
    row: dict, ref: str = "origin/main", repo_root: Path | None = None
) -> Callable[[BaseCheck], CheckResult]:
    """Return a revert_runner for ``scripts.verification_checks.is_admitted`` (kernel entries).

    Ignores the ``check`` argument is_admitted passes in and instead materializes the row's own
    check_spec against a real origin/main worktree -- the check parameter exists only to satisfy
    is_admitted's callable interface.
    """

    def revert_runner(_check: BaseCheck) -> CheckResult:
        with git_worktree(ref, repo_root=repo_root) as wt_root:
            reverted_check = materialize_check_in_tree(row, wt_root)
            return reverted_check.run()

    return revert_runner


@dataclass
class DifferentialOutcome:
    admitted: bool
    reason: str


def run_differential(row: dict, repo_root: Path | None = None) -> DifferentialOutcome:
    """Kernel-entry differential (VF-06 c2): origin/main must FAIL, HEAD/live must PASS."""
    root = Path(repo_root) if repo_root is not None else ROOT
    head_check = materialize_check_in_tree(row, root)
    live = head_check.run()
    if live.status != CheckStatus.PASS:
        return DifferentialOutcome(
            admitted=False, reason=f"not admitted -- check does not pass on HEAD: {live.message or live.actual}"
        )

    revert_runner = make_worktree_revert_runner(row, ref="origin/main", repo_root=root)
    if not is_admitted(head_check, revert_runner):
        return DifferentialOutcome(admitted=False, reason="not admitted -- revert did not produce FAIL (tautological)")
    return DifferentialOutcome(admitted=True, reason="admitted -- fails on origin/main, passes on HEAD")


# ---------------------------------------------------------------------------
# Brand-new verifier differential (VF-06 c3)
# ---------------------------------------------------------------------------


@dataclass
class VerifierDifferentialOutcome:
    admitted: bool
    skipped: bool
    reason: str


def _module_name_for(verifier_file: str) -> str:
    rel = verifier_file[:-3] if verifier_file.endswith(".py") else verifier_file
    return rel.replace("\\", "/").replace("/", ".")


def _run_verifier_subprocess(module_name: str, class_name: str, cwd: Path) -> str:
    """Run the verifier in a fresh subprocess (loads the code at ``cwd``, not this process's cache)."""
    cmd = [sys.executable, "-m", "scripts.verification_graduation", "--run-verifier", module_name, class_name]
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")
    if result.returncode not in (0, 1):
        raise GraduationError(
            f"verifier subprocess crashed (rc={result.returncode}) for {module_name}.{class_name}: "
            f"{result.stderr.strip()[:500]}"
        )
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        raise GraduationError(f"verifier subprocess produced no output for {module_name}.{class_name}: {result.stderr[:300]}")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise GraduationError(f"could not parse verifier subprocess output for {module_name}.{class_name}: {exc}") from exc
    status = payload.get("status")
    if not status:
        raise GraduationError(f"verifier subprocess output missing 'status' for {module_name}.{class_name}: {payload}")
    return status


def run_verifier_differential(
    verifier_file: str,
    class_name: str,
    covered_changed: list[str],
    repo_root: Path | None = None,
) -> VerifierDifferentialOutcome:
    """Brand-new-verifier differential (VF-06 c3, same-PR guard exception (b) backstop).

    HERMETIC: HEAD/live must PASS; a HEAD worktree with ``covered_changed`` reverted to
    origin/main content must FAIL. A verifier that still passes with its covered change
    reverted is tautological and rejected.

    NON_HERMETIC_BY_CONSTRUCTION: cannot yield a reliable fail-on-revert -- returns an
    advisory skip (does not block; documented residue distinct from c2's strict refusal).
    """
    root = Path(repo_root) if repo_root is not None else ROOT
    abs_path = root / verifier_file
    try:
        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))
    except (FileNotFoundError, SyntaxError) as exc:
        raise GraduationError(f"cannot parse verifier file {verifier_file!r}: {exc}") from exc

    class_node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if class_node is None:
        raise GraduationError(f"class {class_name!r} not found in {verifier_file!r}")

    if _verifier_is_non_hermetic(class_node):
        return VerifierDifferentialOutcome(
            admitted=False,
            skipped=True,
            reason=(
                "advisory SKIP -- NON_HERMETIC_BY_CONSTRUCTION new verifier cannot yield a "
                "reliable fail-on-revert differential"
            ),
        )

    module_name = _module_name_for(verifier_file)

    live_status = _run_verifier_subprocess(module_name, class_name, root)
    if live_status != "PASS":
        return VerifierDifferentialOutcome(
            admitted=False, skipped=False, reason=f"not admitted -- verifier status={live_status} at HEAD (expected PASS)"
        )

    with git_worktree("HEAD", repo_root=root) as wt_root:
        if covered_changed:
            checkout = _run_git(["checkout", "origin/main", "--", *covered_changed], wt_root)
            if checkout.returncode != 0:
                raise GraduationError(f"could not revert covered files in worktree: {checkout.stderr.strip()}")
        revert_status = _run_verifier_subprocess(module_name, class_name, wt_root)

    if revert_status == "PASS":
        return VerifierDifferentialOutcome(
            admitted=False, skipped=False, reason="not admitted -- verifier passes even with its covered change reverted"
        )
    if revert_status == "FAIL":
        return VerifierDifferentialOutcome(
            admitted=True, skipped=False, reason="admitted -- fails when covered change reverted, passes at HEAD"
        )
    raise GraduationError(
        f"non-deterministic verifier differential status on revert: {revert_status!r} (expected PASS or FAIL)"
    )


# ---------------------------------------------------------------------------
# Subprocess entry point (invoked as `python -m scripts.verification_graduation --run-verifier ...`)
# ---------------------------------------------------------------------------


def _run_verifier_entry(module_name: str, class_name: str) -> None:
    import asyncio
    import importlib

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    instance = cls()
    result = asyncio.run(instance.run())
    print(json.dumps({"status": result.status.value, "message": result.message}))


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--run-verifier":
        _run_verifier_entry(sys.argv[2], sys.argv[3])
    else:
        print("usage: python -m scripts.verification_graduation --run-verifier <module> <class>", file=sys.stderr)
        sys.exit(2)
