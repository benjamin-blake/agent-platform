"""Package conftest for tests/ci_rca/taxonomy/ -- resets the module-level taxonomy cache before
and after every test so no test's loaded taxonomy leaks into another."""

import pytest

import scripts.ci_rca.taxonomy as taxonomy_mod


@pytest.fixture(autouse=True)
def reset_cache():
    taxonomy_mod._TAXONOMY_CACHE = None
    yield
    taxonomy_mod._TAXONOMY_CACHE = None
