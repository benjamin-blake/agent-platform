"""Mirror test for scripts/checks/deps/validate_check_manifests.py (Decision 168/169): the
grammar evaluator FAILS on an f-string module value, a "module:attr" colon form, a module that
resolves to no graph node, and a segment token present in _schema.py's SEGMENT_TOKENS but not the
contract's declared_segment_tokens (or vice versa). Each negative case is asserted to FAIL; the
clean tree is asserted to pass -- a suite that only asserted the clean case would be vacuous.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import networkx as nx

from scripts.checks.deps.validate_check_manifests import validate_check_manifests

_VALID_CONTRACT = """\
contract:
  id: check-manifest
  class: D
  contract_version: 1
  status: ratified
  ratified_via: "test fixture"
  subject: check-manifest
  evaluator:
    check: validate_check_manifests
amendment_log: []
entry_grammar:
  declared_segment_tokens:
    - full_after_lint
    - full_after_unit_tests
    - full_after_terraform_checks
    - full_after_dependency_health
    - full_after_ensure_fresh_dq
"""


def _write_tree(tmp_path: Path, manifest_body: str, contract_text: str = _VALID_CONTRACT) -> None:
    manifest_dir = tmp_path / "scripts" / "checks" / "fake_domain"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "_manifest.py").write_text(manifest_body, encoding="utf-8")
    contracts_dir = tmp_path / "docs" / "contracts"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "check-manifest.yaml").write_text(contract_text, encoding="utf-8")


def _run(tmp_path: Path, graph_nodes: tuple[str, ...] = ("scripts.checks.fake_domain.validate_x",)) -> list[str]:
    graph = nx.DiGraph()
    for node in graph_nodes:
        graph.add_node(node)
    failed: list[str] = []
    with (
        patch("scripts.checks.deps.validate_check_manifests._common.ROOT", tmp_path),
        patch("scripts.dependency_graph.build_graph", return_value=graph),
    ):
        validate_check_manifests(failed)
    return failed


_ENTRY_LITERAL = (
    "from scripts.checks._schema import Entry\n\n"
    'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain.validate_x", attr="validate_x"),)\n'
)


class TestCleanTreePasses:
    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL)
        assert _run(tmp_path) == []

    def test_real_repo_tree_passes(self) -> None:
        """Unlike every other test in this module, this one does NOT patch _common.ROOT -- it
        scans the REAL 18 production manifests. This is the sole test in this file that a
        mutation to a real scripts/checks/<domain>/_manifest.py file can ever redden; every
        other test here is isolated to a synthetic tmp_path fixture."""
        failed: list[str] = []
        validate_check_manifests(failed)
        assert failed == []


class TestFStringModuleValueFails:
    def test_f_string_module_value_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            '_stem = "validate_x"\n'
            'ENTRIES = (Entry(name="validate_x", module=f"scripts.checks.fake_domain.{_stem}", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path)
        assert any("bare string-literal constant" in f for f in failed), failed


class TestColonFormFails:
    def test_colon_form_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain:validate_x", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path, graph_nodes=())
        assert any("colon" in f for f in failed), failed


class TestUnresolvableModuleFails:
    def test_module_not_in_dependency_graph_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain.does_not_exist", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path, graph_nodes=())
        assert any("does not resolve to a real" in f for f in failed), failed


class TestSegmentTokenMismatchFails:
    def test_schema_token_absent_from_contract_fails(self, tmp_path: Path) -> None:
        contract = _VALID_CONTRACT.replace("    - full_after_ensure_fresh_dq\n", "")
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text=contract)
        failed = _run(tmp_path)
        assert any("SEGMENT_TOKENS" in f for f in failed), failed

    def test_contract_token_absent_from_schema_fails(self, tmp_path: Path) -> None:
        contract = _VALID_CONTRACT + "    - an_extra_token_not_in_schema\n"
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text=contract)
        failed = _run(tmp_path)
        assert any("SEGMENT_TOKENS" in f for f in failed), failed
