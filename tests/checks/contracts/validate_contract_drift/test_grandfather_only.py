"""VP step 3: grandfather-only forms in both directions, including the PERMITTED sweep
transition."""

from __future__ import annotations

from .conftest import validate_contract_drift


def _route(**overrides: object) -> dict:
    """A minimal, fully-populated EnforcementRoute dict (migration-step-3-grandfathering)."""
    route = {
        "reason": "pre-ritual free-form doc, pending future ratification",
        "consumer": "scripts/some_consumer.py",
        "mechanism": "assert some_field matches reality",
        "blocker": "no check reads it yet",
        "shape": "check",
    }
    route.update(overrides)
    return route


class TestGrandfatherOnly:
    def test_new_file_declaring_status_active_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "grand.yaml",
            class_d_yaml(status="active", ratified_via=None, evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("grand.yaml" in f and "status: active" in f for f in failed), failed

    def test_new_file_declaring_none_grandfathered_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "grand.yaml",
            class_d_yaml(evaluator={"none_grandfathered": _route(reason="pending future ratification")}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("grand.yaml" in f and "none_grandfathered" in f for f in failed), failed

    def test_kind_change_from_resolving_to_none_grandfathered_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        head_text = class_d_yaml(
            contract_id="kc", subject="kc-subject", evaluator={"none_grandfathered": _route(reason="weakened")}
        )
        base_text = class_d_yaml(contract_id="kc", subject="kc-subject", evaluator={"check": "validate_placement"})
        write_contract(tmp_path, "kc.yaml", head_text)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/kc.yaml"],
                changed=["docs/contracts/kc.yaml"],
                show_map={"docs/contracts/kc.yaml": base_text},
                batch_map={"docs/contracts/kc.yaml": base_text},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("kc.yaml" in f and "kind-change" in f for f in failed), failed

    def test_absent_to_none_grandfathered_on_baseline_present_file_is_permitted(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        # The population-sweep shape: base was a free-form doc (no contract.class at all), head
        # newly declares Class D with none_grandfathered. This is the exact transition the sweep
        # performs and must pass.
        head_text = class_d_yaml(
            contract_id="swept",
            subject="swept-subject",
            status="active",
            ratified_via=None,
            evaluator={"none_grandfathered": _route()},
        )
        base_text = "some_free_form_key: value\n"
        write_contract(tmp_path, "swept.yaml", head_text)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/swept.yaml"],
                changed=["docs/contracts/swept.yaml"],
                show_map={"docs/contracts/swept.yaml": base_text},
                batch_map={},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed

    def test_baseline_present_active_status_loads_without_new_file_prohibition(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        text = class_d_yaml(
            contract_id="grandf",
            subject="grandf-subject",
            status="active",
            ratified_via=None,
            evaluator={"none_grandfathered": _route()},
        )
        write_contract(tmp_path, "grandf.yaml", text)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/grandf.yaml"],
                show_map={"docs/contracts/grandf.yaml": text},
                batch_map={"docs/contracts/grandf.yaml": text},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed


class TestEnforcementRoute:
    """VP step 1: a none_grandfathered claim missing any of reason/mechanism/blocker/shape is
    rejected at the SCHEMA layer (Pass 1's load_contract_meta call), surfacing as a
    "Contract drift (schema): ..." failure -- never silently admitted as a bare free-text
    grandfather claim."""

    def test_incomplete_route_fails(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=["docs/contracts/incomplete.yaml"]))
        incomplete_route = _route()
        del incomplete_route["blocker"]
        write_contract(
            tmp_path,
            "incomplete.yaml",
            class_d_yaml(
                contract_id="incomplete",
                subject="incomplete-subject",
                status="active",
                ratified_via=None,
                evaluator={"none_grandfathered": incomplete_route},
            ),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("incomplete.yaml" in f and "schema" in f for f in failed), failed

    def test_complete_route_with_null_consumer_passes(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        # consumer: null is explicitly PERMITTED where no consumer module exists at all (the
        # telemetry-lexicon.yaml route is exactly that case).
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=["docs/contracts/nullc.yaml"]))
        write_contract(
            tmp_path,
            "nullc.yaml",
            class_d_yaml(
                contract_id="nullc",
                subject="nullc-subject",
                status="active",
                ratified_via=None,
                evaluator={"none_grandfathered": _route(consumer=None)},
            ),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed
