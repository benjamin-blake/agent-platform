"""Shared singleton load of scripts/session/postflight.py under the "session_postflight" module name.

Several tests/session/postflight/ concern-split test modules (post rec-2709 Wave 10 decomposition of
the former tests/test_session_postflight.py monolith) need `_postflight.run_*()` plus
`patch("session_postflight.<name>")` interception to keep working: session_postflight.py's own code
resolves module-global names (e.g. time, sys, the run_* functions it calls internally) on ITS OWN
module object, while `unittest.mock.patch` resolves the "session_postflight.<name>" string via
`sys.modules["session_postflight"]` at patch-application time.

Those two lookups only agree if every consumer shares the SAME loaded module object. If each test
file independently re-ran `importlib.util.spec_from_file_location("session_postflight", ...)`, the
last one imported during pytest collection would silently win the `sys.modules["session_postflight"]`
slot while every other file's own `_postflight.run_push()` call kept dispatching through its own
now-orphaned copy -- decoupling `patch("session_postflight.time.sleep")` (and similar) from the
function it is meant to intercept (a vacuous-pass hazard: the patch would silently fail to take
effect).

Unlike tests/fixtures/validate_module.py (Wave 1), this loader is explicitly IDEMPOTENT: it reuses
an existing sys.modules["session_postflight"] entry if one is already present. This guards the
intermediate-commit window where the not-yet-deleted monolith tests/test_session_postflight.py --
which still carries its own unconditional top-of-file loader -- can be collected alongside this
package. Scoped collection (pytest tests/session/postflight) never co-collects the monolith, so this
only matters defensively; by the final commit the monolith is deleted and the dual-loader window no
longer exists in the merged state.

Python's own import cache (`sys.modules["tests.fixtures.session_postflight_module"]`) guarantees
this module's body executes exactly once per process; every consumer does
`from tests.fixtures.session_postflight_module import postflight as _postflight` and gets the
identical object.

MODULE_PATH is also re-exported (public, no leading underscore) so tests/session/postflight/
test_auto.py's TestRetiredDrainBlocks -- which reads the source text of scripts/session/postflight.py
directly to assert the retired drain_pending blocks are absent -- has a single source of truth for
the path instead of recomputing it locally. Direct precedent: tests/fixtures/session_preflight_module.py
(Wave 4).
"""

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "session" / "postflight.py"

if "session_postflight" in sys.modules:
    postflight = sys.modules["session_postflight"]
else:
    _spec = importlib.util.spec_from_file_location("session_postflight", MODULE_PATH)
    assert _spec and _spec.loader
    postflight = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["session_postflight"] = postflight
    _spec.loader.exec_module(postflight)  # type: ignore[union-attr]
