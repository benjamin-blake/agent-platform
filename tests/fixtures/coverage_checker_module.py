"""Shared singleton load of scripts/test_coverage_checker.py under the "test_coverage_checker"
module name.

The three tests/test_coverage_checker_*.py files (post rec-2709 Wave 6b decomposition of the
former tests/test_coverage_checker.py monolith) need `check_test_file_exists()` /
`check_per_file_coverage()` plus `patch("test_coverage_checker.<name>")` interception to keep
working: those functions resolve module-global names (e.g. map_source_to_test, ROOT, subprocess)
on THEIR OWN module object, while `unittest.mock.patch` resolves the "test_coverage_checker.<name>"
string via `sys.modules["test_coverage_checker"]` at patch-application time.

Those two lookups only agree if every consumer shares the SAME loaded module object. If each test
file independently re-ran `importlib.util.spec_from_file_location("test_coverage_checker", ...)`,
the last one imported during pytest collection would silently win the
`sys.modules["test_coverage_checker"]` slot while every other file's own bound functions kept
dispatching through their own now-orphaned copy -- decoupling `patch("test_coverage_checker.ROOT")`
(and similar) from the call it is meant to intercept (a vacuous-pass hazard: the patch would
silently fail to take effect). It equally matters for `monkeypatch.setattr(checker,
"_RETIRING_GRANDFATHER_HOMES", ...)` in TestMirrorRule: the patched attribute must live on the SAME
module object that map_source_to_test's own global lookups read from.

Idempotent (mirrors tests/fixtures/session_preflight_module.py, Wave 4): reuses an existing
sys.modules["test_coverage_checker"] entry if one is already present. This guards the transient
working-tree window where the not-yet-deleted monolith tests/test_coverage_checker.py -- which
carries its own unconditional top-of-file loader -- could otherwise be collected alongside this
fixture and race for the sys.modules slot.

Python's own import cache (`sys.modules["tests.fixtures.coverage_checker_module"]`) guarantees this
module's body executes exactly once per process; every consumer does
`from tests.fixtures.coverage_checker_module import checker, ROOT, ...` and gets the identical
object graph.
"""

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "test_coverage_checker.py"

if "test_coverage_checker" in sys.modules:
    checker = sys.modules["test_coverage_checker"]
else:
    _spec = importlib.util.spec_from_file_location("test_coverage_checker", MODULE_PATH)
    assert _spec and _spec.loader
    checker = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["test_coverage_checker"] = checker
    _spec.loader.exec_module(checker)  # type: ignore[union-attr]

ROOT = checker.ROOT
_ALL_MIRROR_TARGET_HOMES = checker._ALL_MIRROR_TARGET_HOMES
_RETIRING_GRANDFATHER_HOMES = checker._RETIRING_GRANDFATHER_HOMES
