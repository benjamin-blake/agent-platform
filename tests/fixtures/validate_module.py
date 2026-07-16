"""Shared singleton load of scripts/validate.py under the "validate" module name.

Several mirror/orchestrator test files (post rec-2709 decomposition of the former
tests/test_validate.py monolith) need `_validate.main()` plus `patch("validate.<name>")`
interception to keep working: `_dispatch_check` in scripts/validate.py resolves each
registered check via `globals()[name]` on ITS OWN module object, while `unittest.mock.patch`
resolves the "validate.<name>" string via `sys.modules["validate"]` at patch-application time.

Those two lookups only agree if every consumer shares the SAME loaded module object. If each
test file independently re-ran `importlib.util.spec_from_file_location("validate", ...)`, the
last one imported during pytest collection would silently win the `sys.modules["validate"]`
slot while every other file's own `_validate.main()` call kept dispatching through its own
now-orphaned copy -- decoupling `patch("validate.<name>")` from the dispatch it's meant to
intercept (a vacuous-pass hazard: the patch would silently fail to take effect).

Python's own import cache (`sys.modules["tests.fixtures.validate_module"]`) guarantees this
module's body executes exactly once per process; every consumer does
`from tests.fixtures.validate_module import _validate` and gets the identical object.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate", _SCRIPT_PATH)
_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_validate)  # type: ignore[union-attr]
sys.modules["validate"] = _validate
