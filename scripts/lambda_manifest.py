# complexity-waiver: decision-43
"""Pydantic schema for src/lambdas/<name>/manifest.yaml, staging, and CLI.

Parallel to scripts/roadmap/platform_roadmap.py. Owns all manifest logic (schema,
bundle-staging, py_compile-equivalent import check, LAMBDA_FILE_PATTERNS
derivation) so validate.py stays thin (Decision 43 SLOC governance).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

ROOT = Path(__file__).parent.parent
_LAMBDAS_DIR = ROOT / "src" / "lambdas"


class LambdaManifest(BaseModel):
    """Schema for src/lambdas/<artifact-slug>/manifest.yaml."""

    model_config = ConfigDict(extra="forbid")

    artifact: str  # zip name, e.g. "data-pipeline.zip"
    functions: list[str] = []  # AWS Lambda function names backed by this artifact
    handlers: list[str] = []  # entry-point .py file paths (relative to repo root)
    includes: list[str] = []  # src/ or scripts/ paths staged wholesale (dirs or files)
    excludes: list[str] = []  # paths under an includes[] dir to NOT stage / NOT mark affected
    assets: list[str] = []  # non-import files/dirs bundled verbatim, read at runtime
    config: list[str] = []  # config/lambda/<name>/ paths
    pip_packages: list[str] = []  # pip-installable packages (e.g. "boto3==1.34.0")
    runtime_config: list[str] = []  # SSM/AppConfig paths (declared; fetch deferred)
    status: Literal["active", "stub"] = "active"
    notes: str = ""

    @field_validator("artifact")
    @classmethod
    def artifact_ends_with_zip(cls, v: str) -> str:
        if not v.endswith(".zip"):
            raise ValueError(f"artifact must end with .zip, got: {v!r}")
        return v


def load(manifest_path: Path) -> LambdaManifest:
    """Load and validate a manifest.yaml file."""
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{manifest_path}: expected a YAML mapping, got {type(raw).__name__}")
    return LambdaManifest.model_validate(raw)


def load_all() -> dict[str, LambdaManifest]:
    """Load all manifests under src/lambdas/<name>/manifest.yaml.

    Returns a dict keyed by artifact-slug directory name (not zip name).
    """
    manifests: dict[str, LambdaManifest] = {}
    for child in sorted(_LAMBDAS_DIR.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        mp = child / "manifest.yaml"
        if mp.exists():
            manifests[child.name] = load(mp)
    return manifests


def _is_excluded(rel_path: str, excludes: list[str]) -> bool:
    """True if *rel_path* (repo-relative) equals or is nested under any excludes[] entry."""
    norm = rel_path.replace("\\", "/").rstrip("/")
    for ex in excludes:
        ex_norm = ex.replace("\\", "/").rstrip("/")
        if norm == ex_norm or norm.startswith(ex_norm + "/"):
            return True
    return False


def _copytree_ignore(excludes: list[str]) -> "Callable[[str, list[str]], set[str]]":
    """Build a shutil.copytree `ignore` callable that drops excludes[] entries during a dir copy."""

    def _ignore(dir_path: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        base = Path(dir_path)
        for name in names:
            try:
                rel = (base / name).resolve().relative_to(ROOT.resolve())
            except ValueError:
                continue
            if _is_excluded(str(rel), excludes):
                ignored.add(name)
        return ignored

    return _ignore


def stage_bundle(manifest: LambdaManifest, stage_dir: Path, *, skip_pip: bool = True) -> None:
    """Stage all manifest-declared files into stage_dir.

    Replicates the file-set that the old copytree approach produced, driven
    entirely from the manifest rather than from filesystem layout. Paths listed in
    manifest.excludes are skipped during the includes copy (a wildcard `includes: - src/`
    no longer drags excluded subtrees into the zip).

    Args:
        manifest: Loaded LambdaManifest.
        stage_dir: Empty directory to stage into.
        skip_pip: If True, skip pip install steps (fast; for list/coverage checks).
            Set False for a full build that includes pip packages.
    """

    def _copy_path(rel: str) -> None:
        """Copy a single path (file or directory) preserving relative structure."""
        if _is_excluded(rel, manifest.excludes):
            return
        src = ROOT / rel
        dst = stage_dir / rel
        if not src.exists():
            return
        if src.is_dir():
            ignore = _copytree_ignore(manifest.excludes) if manifest.excludes else None
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    for path in manifest.includes:
        _copy_path(path.rstrip("/"))

    for path in manifest.handlers:
        _copy_path(path)

    for path in manifest.assets:
        _copy_path(path.rstrip("/"))

    for path in manifest.config:
        _copy_path(path.rstrip("/"))

    if not skip_pip and manifest.pip_packages:
        for pkg in manifest.pip_packages:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    pkg,
                    "--target",
                    str(stage_dir),
                    "--platform",
                    "manylinux_2_28_x86_64",
                    "--platform",
                    "manylinux2014_x86_64",
                    "--implementation",
                    "cp",
                    "--python-version",
                    "3.12",
                    "--only-binary=:all:",
                    "--quiet",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                print(f"  ERROR: pip install {pkg!r} failed: {result.stderr.strip()}", file=sys.stderr)
                sys.exit(1)


def check_handler_imports(manifest: LambdaManifest, stage_dir: Path) -> list[str]:
    """Import-resolve each handler against the staged bundle.

    Uses a subprocess to avoid polluting the current Python path.  Returns
    a list of error messages; empty list means all handlers resolved.
    """
    errors: list[str] = []
    for handler_rel in manifest.handlers:
        handler_path = stage_dir / handler_rel
        if not handler_path.exists():
            errors.append(f"{handler_rel}: not found in staged bundle")
            continue
        # Derive dotted module from path relative to stage_dir
        relative = Path(handler_rel)
        parts = list(relative.with_suffix("").parts)
        dotted = ".".join(parts)
        result = subprocess.run(
            [sys.executable, "-c", f"import importlib; importlib.import_module({dotted!r})"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(stage_dir),  # '' in sys.path resolves to stage_dir, not repo root
            env={**_minimal_env(), "PYTHONPATH": str(stage_dir)},
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Extract the missing module name from ModuleNotFoundError if present
            import re as _re

            m = _re.search(r"ModuleNotFoundError: No module named '([^']+)'", stderr)
            if m:
                errors.append(f"{handler_rel}: missing module '{m.group(1)}'")
            else:
                first_line = stderr.splitlines()[0] if stderr else "import failed"
                errors.append(f"{handler_rel}: {first_line}")
    return errors


def check_assets_present(manifest: LambdaManifest, stage_dir: Path) -> list[str]:
    """Assert every declared assets[] and config[] path is present in the staged bundle.

    Only checks paths that exist at the repo root (gitignored/optional files like
    config/config.yaml are skipped if not present locally).
    """
    errors: list[str] = []
    for path in manifest.assets + manifest.config:
        clean = path.rstrip("/")
        repo_src = ROOT / clean
        if not repo_src.exists():
            # Optional / gitignored file; skip - the stage_bundle already skips it
            continue
        staged = stage_dir / clean
        if not staged.exists():
            errors.append(f"declared asset/config not staged: {path!r}")
    return errors


def compute_affected_artifacts(changed_files: list[str]) -> dict[str, list[str]]:
    """Return {artifact_slug: [matching changed files]} for each manifest that overlaps.

    Used by validate_lambda_deploy_gating to determine which Lambda artifacts
    a diff touches, enabling per-Lambda deploy-step verification.
    """
    try:
        manifests = load_all()
    except Exception:
        return {}

    result: dict[str, list[str]] = {}
    for slug, manifest in manifests.items():
        if manifest.status == "stub":
            continue
        manifest_paths: set[str] = set()
        for p in manifest.handlers + manifest.includes + manifest.assets + manifest.config:
            manifest_paths.add(p.rstrip("/"))
        matches = []
        for changed in changed_files:
            # A changed file under an excludes[] entry does NOT mark this artifact affected,
            # even if it falls under a broad includes[] prefix (e.g. src/).
            if _is_excluded(changed, manifest.excludes):
                continue
            for mp in manifest_paths:
                if changed == mp or changed.startswith(mp + "/") or changed.startswith(mp + "\\"):
                    matches.append(changed)
                    break
            # Also check if the manifest.yaml itself changed
            if changed == f"src/lambdas/{slug}/manifest.yaml":
                if changed not in matches:
                    matches.append(changed)
        if matches:
            result[slug] = matches
    return result


def derive_lambda_file_patterns() -> list[str]:
    """Derive LAMBDA_FILE_PATTERNS from the union of all manifests.

    Returns a sorted list of glob-compatible path prefixes covering every
    file or directory declared across all active manifests.  Supersedes the
    hand-curated registry from T-1.6's bootstrap form (CD.24).
    """
    try:
        manifests = load_all()
    except Exception:
        return []

    patterns: set[str] = set()
    for manifest in manifests.values():
        if manifest.status == "stub":
            continue
        for p in manifest.handlers + manifest.includes + manifest.assets + manifest.config:
            clean = p.rstrip("/")
            # A path this manifest excludes is not one of its file patterns.
            if _is_excluded(clean, manifest.excludes):
                continue
            src = ROOT / clean
            if src.is_dir():
                patterns.add(clean + "/")
            else:
                patterns.add(clean)
    return sorted(patterns)


# ---------------------------------------------------------------------------
# CLI entry-points
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    """--validate: schema-validate every manifest under src/lambdas/."""
    print("Lambda manifest schema validation")
    ok = True
    if not _LAMBDAS_DIR.exists():
        print(f"  FAIL: {_LAMBDAS_DIR} not found")
        return 1
    for child in sorted(_LAMBDAS_DIR.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        mp = child / "manifest.yaml"
        if not mp.exists():
            print(f"  SKIP: {child.name}/ has no manifest.yaml (coverage check will catch this)")
            continue
        try:
            load(mp)
            print(f"  OK   {child.name}/manifest.yaml")
        except Exception as exc:
            print(f"  FAIL {child.name}/manifest.yaml: {exc}")
            ok = False
    return 0 if ok else 1


def cmd_check_coverage(args: argparse.Namespace) -> int:
    """--check-coverage: every src/lambdas/<name>/ dir must have a manifest.yaml."""
    print("Lambda manifest coverage check")
    if not _LAMBDAS_DIR.exists():
        print(f"  FAIL: {_LAMBDAS_DIR} not found")
        return 1
    missing: list[str] = []
    found = 0
    for child in sorted(_LAMBDAS_DIR.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        mp = child / "manifest.yaml"
        if mp.exists():
            found += 1
        else:
            missing.append(child.name)
    if missing:
        for name in missing:
            print(f"  FAIL: src/lambdas/{name}/ has no manifest.yaml")
        return 1
    print(f"  OK   {found} manifest(s) found, all dirs covered")
    return 0


def cmd_check_bundles(args: argparse.Namespace) -> int:
    """--check-bundles: stage each active artifact and verify handlers + assets."""
    print("Lambda bundle completeness check")
    try:
        manifests = load_all()
    except Exception as exc:
        print(f"  FAIL: could not load manifests: {exc}")
        return 1

    overall_ok = True
    for slug, manifest in manifests.items():
        if manifest.status == "stub":
            print(f"  SKIP {slug} (stub)")
            continue
        print(f"  Checking {slug} ({manifest.artifact})...")
        with tempfile.TemporaryDirectory(prefix=f"lm-stage-{slug}-") as tmp:
            stage_dir = Path(tmp)
            try:
                stage_bundle(manifest, stage_dir, skip_pip=True)
            except Exception as exc:
                print(f"    FAIL staging: {exc}")
                overall_ok = False
                continue

            import_errors = check_handler_imports(manifest, stage_dir)
            asset_errors = check_assets_present(manifest, stage_dir)

            if import_errors:
                for e in import_errors:
                    print(f"    FAIL (import) {e}")
                overall_ok = False
            if asset_errors:
                for e in asset_errors:
                    print(f"    FAIL (asset)  {e}")
                overall_ok = False
            if not import_errors and not asset_errors:
                print("    OK   handlers import-resolved, assets present")
    return 0 if overall_ok else 1


def cmd_list_patterns(args: argparse.Namespace) -> int:
    """--list-patterns: emit LAMBDA_FILE_PATTERNS derived from all active manifests."""
    patterns = derive_lambda_file_patterns()
    for p in patterns:
        print(p)
    return 0


def _minimal_env() -> dict[str, str]:
    """Return a minimal environment dict for subprocess calls."""
    import os

    keep = {"PATH", "HOME", "USER", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT"}
    return {k: v for k, v in os.environ.items() if k in keep}


def main() -> None:
    parser = argparse.ArgumentParser(description="Lambda manifest schema validation and bundle tools")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true", help="Schema-validate all manifests")
    group.add_argument("--check-coverage", action="store_true", help="Every src/lambdas/ dir must have manifest.yaml")
    group.add_argument("--check-bundles", action="store_true", help="Stage each artifact and verify handler imports + assets")
    group.add_argument("--list-patterns", action="store_true", help="Emit LAMBDA_FILE_PATTERNS derived from manifests")
    args = parser.parse_args()

    if args.validate:
        sys.exit(cmd_validate(args))
    elif args.check_coverage:
        sys.exit(cmd_check_coverage(args))
    elif args.check_bundles:
        sys.exit(cmd_check_bundles(args))
    elif args.list_patterns:
        sys.exit(cmd_list_patterns(args))


if __name__ == "__main__":
    main()
