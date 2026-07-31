"""Citation-pattern extension tests for _WHY_CHAIN_CITATION_RE (scripts/ops_portal/ci_rca_schema.py).

Split out from test_ci_rca_schema.py (which carries a module-level `pytest.importorskip("duckdb")`
at line 24) so this differential is covered by the fast pr-validate tier even when duckdb is absent
(pr-validate installs only requirements-fast + requirements-dev) -- otherwise Decision 132's VF-06
differential admission gate would report `skipped (non-fatal)` instead of actually proving the
citation-widening row (PLAN-ci-rca-abstention-and-citation, AC1/AC2).
"""

from __future__ import annotations

import re

from scripts.ops_portal.ci_rca_schema import _WHY_CHAIN_CITATION_RE

# The PRE-fix pattern, hardcoded here as a literal copy of the regex as it read before this plan's
# widening (production holds only one live pattern, so the pre-fix half of the differential
# necessarily compares against a fixed copy rather than the module constant). The load-bearing
# assertion is the POST-fix half below, which runs against the live module constant.
_PRE_FIX_PATTERN = re.compile(r"[\w./-]+\.(py|yaml|tf|md|sh):\d+")


class TestCitationPatternExtensions:
    def test_pre_fix_pattern_rejects_yml_citation(self) -> None:
        assert _PRE_FIX_PATTERN.search(".github/workflows/ci.yml:12") is None

    def test_post_fix_pattern_accepts_yml_citation(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search(".github/workflows/ci.yml:12") is not None

    def test_post_fix_pattern_still_accepts_yaml(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search("config/sloc_budgets.yaml:42") is not None

    def test_post_fix_pattern_still_accepts_py(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search("scripts/validate.py:284") is not None

    def test_post_fix_pattern_still_accepts_tf(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search("terraform/personal/oidc.tf:10") is not None

    def test_post_fix_pattern_still_accepts_md(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search("docs/PROJECT_CONTEXT.md:5") is not None

    def test_post_fix_pattern_still_accepts_sh(self) -> None:
        assert _WHY_CHAIN_CITATION_RE.search(".github/actions/subagent-plan-review/review.sh:30") is not None
