"""Requirements.txt PyPI-existence validation (Decision 104)."""

from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_requirements", owner="platform")
def validate_requirements(failed: list[str]) -> None:
    print("\n=== Requirements validation ===")
    req_file = _common.ROOT / "requirements.txt"
    if not req_file.exists():
        print(f"requirements.txt not found at {req_file}")
        failed.append("Requirements validation")
        return

    lines = req_file.read_text(encoding="utf-8").splitlines()
    packages: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Skip git+, http(s)://, -e, and -r directives — not PyPI packages
        if re.match(r"^(git\+|https?://|-e\s|-r\s)", stripped):
            continue
        # Extract package name — stop at version specifier, extras, comment, or whitespace
        match = re.match(r"^([A-Za-z0-9_-]+)", stripped)
        if match:
            packages.append(match.group(1))

    if not packages:
        print("requirements.txt has no packages to validate.")
        return

    errors: list[str] = []
    for pkg in packages:
        # Validate package name is safe before issuing subprocess (defence-in-depth)
        if not re.match(r"^[A-Za-z0-9_-]+$", pkg):
            errors.append(f"{pkg} — skipped (non-standard name, verify manually)")
            continue
        try:
            result = _common.run(
                [_common.PYTHON, "-m", "pip", "index", "versions", pkg],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            errors.append(f"{pkg} — pip not found (check venv activation)")
            continue
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if any(word in stderr for word in ("connection", "timeout", "network", "unreachable")):
                errors.append(f"{pkg} — network error checking PyPI (retry or check connectivity)")
            else:
                errors.append(f"{pkg} — not found on PyPI (pip index versions returned non-zero)")

    if errors:
        print("Requirements validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Requirements validation")
    else:
        print(f"All {len(packages)} packages in requirements.txt found on PyPI.")
