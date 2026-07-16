"""Package conftest for tests/ci_rca/evidence/ (rec-2709 Wave 10).

Hoists the shared fixtures from the former tests/test_ci_rca_evidence.py monolith VERBATIM:
`reset_taxonomy_cache` (autouse -- resets scripts.ci_rca.taxonomy._TAXONOMY_CACHE before/after
each test), `taxonomy_file` (writes MINI_TAXONOMY to a tmp_path file), and `log_file`. Layers
UNDER the root tests/conftest.py (global recursion/socket/env-clearing autouse fixtures) without
redeclaring any of them.
"""

import pytest
import yaml

import scripts.ci_rca.taxonomy as taxonomy_mod
from tests.fixtures.ci_rca.evidence_taxonomies import MINI_TAXONOMY


@pytest.fixture(autouse=True)
def reset_taxonomy_cache():
    taxonomy_mod._TAXONOMY_CACHE = None
    yield
    taxonomy_mod._TAXONOMY_CACHE = None


@pytest.fixture
def taxonomy_file(tmp_path):
    p = tmp_path / "taxonomy.yaml"
    p.write_text(yaml.dump(MINI_TAXONOMY))
    return p


@pytest.fixture
def log_file(tmp_path):
    p = tmp_path / "ci-failed.log"
    p.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")
    return p
