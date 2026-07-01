from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_broker_env_reads", owner="trading")
def validate_broker_env_reads(failed: list[str]) -> None:
    """Enforce the RESOLVE-BY-KEY-ONLY invariant for broker credentials (T2.14 exit criterion 3).

    Runtime components must resolve broker credentials exclusively via scripts/broker_secrets.py
    and the credential-routing contract. Direct reads of broker API keys from os.environ are
    forbidden in production code paths (src/ and scripts/).

    Patterns flagged:
      - os.environ["ALPACA_*"]
      - os.getenv("ALPACA_*")
      - os.environ.get("ALPACA_*")

    Self-excluded: this module's own docstring (demonstrates the flagged patterns) and
    broker_secrets.py (the resolver itself; it may reference env-var naming in comments
    or error messages). Skipped: tests/ (test fixtures may plant violations intentionally).
    """
    print("\n=== Broker env-read guard (RESOLVE-BY-KEY-ONLY) ===")
    scripts_dir = _common.ROOT / "scripts"
    src_dir = _common.ROOT / "src"

    _SELF_EXCLUDE = {
        Path(__file__),
        scripts_dir / "broker_secrets.py",
    }

    _PATTERNS = [
        re.compile(r'os\.environ\s*\[\s*["\']ALPACA_'),
        re.compile(r'os\.getenv\s*\(\s*["\']ALPACA_'),
        re.compile(r'os\.environ\.get\s*\(\s*["\']ALPACA_'),
    ]

    errors: list[str] = []
    for search_dir in [scripts_dir, src_dir]:
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file in _SELF_EXCLUDE:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pat in _PATTERNS:
                if pat.search(content):
                    rel = py_file.relative_to(_common.ROOT)
                    errors.append(
                        f"{rel}: directly reads a broker API key from os.environ -- "
                        "resolve via scripts.broker_secrets.resolve() instead "
                        "(RESOLVE-BY-KEY-ONLY invariant, T2.14 exit criterion 3)"
                    )
                    break

    if errors:
        print("Broker env-read violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("No direct broker API key env reads found.")
