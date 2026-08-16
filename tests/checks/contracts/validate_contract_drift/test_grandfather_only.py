"""VP step 3: grandfather-only forms in both directions, including the PERMITTED sweep
transition."""

from __future__ import annotations

from .conftest import validate_contract_drift


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

    def test_baseline_present_active_status_loads_without_new_file_prohibition(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        # Once the none_grandfathered guard is deleted, EVERY Class D file's evaluator must
        # genuinely resolve -- so this fixture is named file-router.yaml (the pattern
        # test_evaluator_resolution.py:22-26 uses) and declares {check: validate_placement},
        # which genuinely reads "file-router.yaml" as an executable-context literal
        # (validate_placement.py:19). A fixture named e.g. grandf.yaml with that same evaluator
        # would FAIL (proved live by test_evaluator_resolution.py's
        # test_exact_equality_not_substring): only the surviving status:active grandfather form
        # is under test here, not evaluator resolution by mismatched basename.
        text = class_d_yaml(
            contract_id="file-router",
            subject="file-router",
            status="active",
            ratified_via=None,
            evaluator={"check": "validate_placement"},
        )
        write_contract(tmp_path, "file-router.yaml", text)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/file-router.yaml"],
                show_map={"docs/contracts/file-router.yaml": text},
                batch_map={"docs/contracts/file-router.yaml": text},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed
