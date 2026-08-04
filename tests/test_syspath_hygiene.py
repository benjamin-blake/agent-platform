"""Behavioural regression guard for the syspath hygiene fix (rec-2876, rec-2878).

Re-executes each of the nine module bodies that used to add an ambient duplicate of the repo
root to sys.path -- six now-DELETED dead inserts under tests/ and three now-GUARDED (genuinely
load-bearing) inserts under scripts/ -- and asserts that re-execution adds ZERO additional
repo-root copies to sys.path. For the six deleted modules this is a standing guard against
anyone re-adding the dead insert; for the three guarded modules it is the only check that
distinguishes a real guard from a bare re-indent (a grep for the insert pattern cannot tell the
difference).

MECHANISM IS PINNED: re-execute each module body via importlib.util.spec_from_file_location +
exec_module. Do NOT use `import tests.test_X` (Decision 131's cross-test-import guard,
scripts/checks/hygiene/validate_no_cross_test_imports.py, forbids it on an AST match of
ast.Import/ast.ImportFrom) and do NOT use importlib.reload (it requires a prior import, so it
inherits the same violation).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

_MODULES = [
    ROOT / "tests" / "ci_rca" / "taxonomy" / "test_load_and_classify.py",
    ROOT / "tests" / "test_ci_rca_vacuous_pass.py",
    ROOT / "tests" / "test_ci_claude_p_retry.py",
    ROOT / "tests" / "test_ci_rca_tier_map.py",
    ROOT / "tests" / "test_verification_checks.py",
    ROOT / "tests" / "test_ci_rca_evidence_ast.py",
    ROOT / "scripts" / "session" / "postflight.py",
    ROOT / "scripts" / "roadmap" / "plan_audit.py",
    ROOT / "scripts" / "agent_development" / "run_skill.py",
]


def _exec_module_body(path: Path, probe_name: str) -> None:
    spec = importlib.util.spec_from_file_location(probe_name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]


@pytest.mark.parametrize("module_path", _MODULES, ids=lambda p: str(p.relative_to(ROOT)))
def test_reexecuting_module_adds_no_duplicate_root(module_path: Path) -> None:
    root_str = str(ROOT)
    before = sys.path.count(root_str)
    _exec_module_body(module_path, f"_syspath_hygiene_probe_{module_path.stem}")
    after = sys.path.count(root_str)
    assert after == before, (
        f"{module_path.relative_to(ROOT)} added {after - before} additional repo-root "
        f"cop{'y' if after - before == 1 else 'ies'} to sys.path on re-execution "
        f"(before={before}, after={after})"
    )
