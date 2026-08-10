"""Coverage-closing edge cases for validate_contract_drift.py not otherwise exercised by the
VP-step-aligned modules: the sys.path injection/restore branch, Pass 2's malformed head/base
YAML handling, the ratchet pin-error surfacing through the full gate, the best-effort router
loader's failure branches, and _class_d_meta_from_text's direct failure branches."""

from __future__ import annotations

import sys

from .conftest import _FakeGit, validate_contract_drift


class TestSysPathInjection:
    def test_root_not_on_sys_path_is_injected_and_restored(self, tmp_path, install_fake_git, FakeGit, monkeypatch) -> None:
        from scripts.checks import _common

        root_str = str(_common.ROOT)
        had_root = root_str in sys.path
        if had_root:
            monkeypatch.setattr(sys, "path", [p for p in sys.path if p != root_str])
        install_fake_git(FakeGit(merge_base_rc=1))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert root_str not in sys.path


class TestPassTwoMalformedYaml:
    def test_head_read_error_is_skipped(self, tmp_path, install_fake_git, write_contract, class_d_yaml) -> None:
        text = class_d_yaml(contract_id="edge1", subject="edge1-subject", evaluator={"check": "validate_placement"})
        write_contract(tmp_path, "edge1.yaml", text)
        fake = _FakeGit(
            merge_base_rc=0,
            merge_base="BASE0000",
            ls_tree=["docs/contracts/edge1.yaml"],
            changed=["docs/contracts/edge1.yaml"],
            show_map={"docs/contracts/edge1.yaml": text},
        )
        install_fake_git(fake)
        # Corrupt the file on disk AFTER Pass 1 would have already read it once by making the
        # second (Pass 2) read hit a decode error -- simplest deterministic way: write invalid
        # UTF-8 bytes directly, which also fails Pass 1's own read (cat-1), proving Pass 2's
        # except branch is reached via the SAME failure mode Pass 1 already reported.
        (tmp_path / "edge1.yaml").write_bytes(b"contract:\n  id: \xff\xfe bad\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat-1" in f for f in failed)

    def test_head_not_a_mapping_is_skipped(self, tmp_path, install_fake_git, write_contract) -> None:
        write_contract(tmp_path, "edge2.yaml", "- just\n- a\n- list\n")
        fake = _FakeGit(
            merge_base_rc=0,
            merge_base="BASE0000",
            ls_tree=["docs/contracts/edge2.yaml"],
            changed=["docs/contracts/edge2.yaml"],
            show_map={"docs/contracts/edge2.yaml": "- just\n- a\n- list\n"},
        )
        install_fake_git(fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        # Grandfathered (baseline-present, non-mapping both sides) -- no Pass 2 failure.
        assert not any("edge2.yaml" in f and "conformance-loss" in f for f in failed)

    def test_base_not_a_mapping_is_skipped(self, tmp_path, install_fake_git, write_contract, class_d_yaml) -> None:
        text = class_d_yaml(contract_id="edge3", subject="edge3-subject", evaluator={"check": "validate_placement"})
        write_contract(tmp_path, "edge3.yaml", text)
        fake = _FakeGit(
            merge_base_rc=0,
            merge_base="BASE0000",
            ls_tree=["docs/contracts/edge3.yaml"],
            changed=["docs/contracts/edge3.yaml"],
            show_map={"docs/contracts/edge3.yaml": "- just\n- a\n- list\n"},
        )
        install_fake_git(fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        # base parses but is not a mapping -> base_shape resolution is skipped entirely, so no
        # conformance-loss / amendment / kind-change failure fires for this file.
        assert not any(
            "edge3.yaml" in f and ("conformance-loss" in f or "amendment" in f or "kind-change" in f) for f in failed
        )


class TestRatchetErrorSurfacedThroughGate:
    def test_pin_type_error_surfaces_as_ratchet_failure(self, tmp_path, install_fake_git, FakeGit) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: 'not-an-int'\n", encoding="utf-8")
        install_fake_git(FakeGit(merge_base_rc=1))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("ratchet" in f and "non-bool int" in f for f in failed)


class TestLoadRouterRoutesFailureBranches:
    def test_unparseable_router_yields_no_routes(self, tmp_path) -> None:
        import yaml

        from scripts.checks.contracts.validate_contract_drift import _load_router_routes

        bad = tmp_path / "file-router.yaml"
        bad.write_text("{bad: [unclosed", encoding="utf-8")
        assert _load_router_routes(bad, yaml) == []

    def test_missing_router_yields_no_routes(self, tmp_path) -> None:
        import yaml

        from scripts.checks.contracts.validate_contract_drift import _load_router_routes

        assert _load_router_routes(tmp_path / "does_not_exist.yaml", yaml) == []

    def test_non_mapping_router_yields_no_routes(self, tmp_path) -> None:
        import yaml

        from scripts.checks.contracts.validate_contract_drift import _load_router_routes

        non_mapping = tmp_path / "file-router.yaml"
        non_mapping.write_text("- a\n- b\n", encoding="utf-8")
        assert _load_router_routes(non_mapping, yaml) == []


class TestClassDMetaFromTextDirect:
    def test_invalid_yaml_returns_none(self) -> None:
        from scripts.checks.contracts.validate_contract_drift import _class_d_meta_from_text

        assert _class_d_meta_from_text("{bad: [unclosed") is None

    def test_non_mapping_returns_none(self) -> None:
        from scripts.checks.contracts.validate_contract_drift import _class_d_meta_from_text

        assert _class_d_meta_from_text("- a\n- b\n") is None

    def test_contract_not_a_mapping_returns_none(self) -> None:
        from scripts.checks.contracts.validate_contract_drift import _class_d_meta_from_text

        assert _class_d_meta_from_text("contract: not-a-mapping\n") is None

    def test_valid_envelope_returns_meta(self) -> None:
        from scripts.checks.contracts.validate_contract_drift import _class_d_meta_from_text

        text = (
            "contract:\n"
            "  id: x\n"
            "  class: D\n"
            "  contract_version: 1\n"
            "  status: ratified\n"
            "  ratified_via: t\n"
            "  subject: s\n"
            "  evaluator:\n"
            "    check: validate_placement\n"
        )
        meta = _class_d_meta_from_text(text)
        assert meta is not None
        assert meta.id == "x"
