"""Package conftest for tests/session/preflight/ (rec-2709 Wave 4).

Hoists the module-level autouse fixture `_disable_reader_and_git_fetch` from the former
tests/test_session_preflight.py monolith VERBATIM. Layers UNDER the root tests/conftest.py
(global recursion/socket/env-clearing autouse fixtures) without redeclaring any of them.

Importing tests.fixtures.session_preflight_module here (noqa F401) guarantees
sys.modules["session_preflight"] is registered before this fixture's string-target patch()
calls resolve it -- every tests/session/preflight/test_*.py module does the same import, so
Python's own import cache makes this a no-op after the first collection, but declaring it here
too keeps the conftest self-sufficient regardless of collection order.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: F401


@pytest.fixture(autouse=True)
def _disable_reader_and_git_fetch(request: pytest.FixtureRequest):
    """Prevent all tests from hitting the real DuckLake reader and from doing real git fetches.

    Reader: every warehouse read in this module transits _make_reader().named(verb)
    (Decision 84 I-3). The default stub returns [] for every verb so read_priority_queue()
    does not sys.exit(1) and the rec counters report empty rather than reaching the network.
    Tests that need specific rows or failures re-patch scripts.preflight._common._make_reader.

    Git fetch: check_main_freshness() shells out to ``git fetch origin main``; patch it to
    a deterministic stub for every test except TestCheckMainFreshness (which exercises the
    real function via subprocess.run mocking).
    """
    from contextlib import ExitStack  # noqa: PLC0415

    reader_stub = MagicMock()
    reader_stub.named.return_value = []
    reader_stub.current_state.return_value = []

    freshness_stub = {
        "status": "ok",
        "fetched_at": "2026-05-24T00:00:00+00:00",
        "commits_behind": 0,
        "commits_ahead": 0,
        "main_files_changed_since_branch": [],
    }
    class_name = request.cls.__name__ if request.cls else ""

    # warm_sync is the single warm-up reader touch main() makes (neon-egress-reduction D4); stub it
    # so main() integration tests never hit the network. reader_ok=True + empty rows => main derives
    # empty signals (0 open recs etc.), matching the prior empty-reader-stub behaviour.
    warm_sync_stub = {
        "drained": {},
        "pulled": {},
        "rows": {"ops_recommendations": [], "ops_decisions": [], "ops_priority_queue": []},
        "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
    }

    with ExitStack() as stack:
        stack.enter_context(patch("scripts.preflight._common._make_reader", return_value=reader_stub))
        stack.enter_context(patch("scripts.sync.ops.sync", return_value={"drained": {}, "pulled": {}}))
        stack.enter_context(patch("scripts.sync.ops.warm_sync", return_value=warm_sync_stub))
        stack.enter_context(patch("session_preflight._sync_ops_pull", return_value={}))
        if class_name != "TestCheckMainFreshness":
            stack.enter_context(patch("scripts.preflight.env_git.check_main_freshness", return_value=freshness_stub))
        yield
