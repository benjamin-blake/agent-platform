"""Package conftest for tests/session/postflight/ (rec-2709 Wave 10).

Hoists the module-level autouse fixture `_mock_sync_ops_postflight` from the former
tests/test_session_postflight.py monolith VERBATIM. Layers UNDER the root tests/conftest.py
(global recursion/socket/env-clearing autouse fixtures) without redeclaring any of them.

Importing tests.fixtures.session_postflight_module here (noqa F401) guarantees
sys.modules["session_postflight"] is registered before any patch("session_postflight.*")
string-target call resolves it -- every tests/session/postflight/test_*.py module does the same
import, so Python's own import cache makes this a no-op after the first collection, but declaring
it here too keeps the conftest self-sufficient regardless of collection order.
"""

from unittest.mock import patch

import pytest

from tests.fixtures.session_postflight_module import postflight as _postflight  # noqa: F401


@pytest.fixture(autouse=True)
def _mock_sync_ops_postflight():
    """Prevent real AWS calls from sync_ops inside run_auto() tests.

    Step 8 of run_auto calls scripts.ops_data_portal.sync(), which pulls each table via
    scripts.sync.ops._pull_single_table -- stub the pull so no test reaches the network.
    """
    with (
        patch("scripts.sync.ops.sync", return_value={"drained": {}, "pulled": {}}),
        patch("scripts.sync.ops._pull_single_table", return_value=0),
    ):
        yield
