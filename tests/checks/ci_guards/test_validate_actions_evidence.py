from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from scripts.checks.ci_guards import validate_actions_evidence as subject

ROOT = Path(__file__).parents[3]


def _fixture(tmp_path: Path) -> Path:
    for relative in [subject.CONTRACT_PATH, Path(".github/workflows"), Path("scripts/ci_rca")]:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return tmp_path


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _contract(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / subject.CONTRACT_PATH
    return path, _yaml(path)


class TestActionsEvidenceCounterfactuals:
    def test_canonical_mutation_matrix(self, tmp_path: Path) -> None:
        root = _fixture(tmp_path)
        subject.validate_contract(root)
        path, baseline = _contract(root)

        def rejected(mutate, message: str) -> None:
            value = yaml.safe_load(yaml.safe_dump(baseline))
            mutate(value)
            _write(path, value)
            with pytest.raises(ValueError, match=message):
                subject.validate_contract(root)

        rejected(lambda c: c["required_retention_classes"].pop(), "exactly the four")
        rejected(lambda c: c["retention_classes"]["ordinary_ci"].update(minimum_days=15), "invalid day bounds")
        rejected(lambda c: c["retention_classes"]["ordinary_ci"].update(expiry_state="available"), "fail-closed")
        rejected(lambda c: c["s1_linkage"].update(schema="raw/v0"), "S1 linkage schema")
        rejected(lambda c: c["governed_jobs"].append(c["governed_jobs"][0]), "duplicate governed")
        rejected(lambda c: c["governed_jobs"][0].update(workflow_name="renamed"), "stale workflow")
        rejected(lambda c: c["governed_jobs"][0].update(job="absent"), "selected job is missing")
        rejected(lambda c: c["governed_jobs"][0].update(critical_step={"name": "absent"}), "critical step")
        rejected(lambda c: c["governed_jobs"][0].update(diagnostic_id="token_deadbeef"), "unsafe or unstable")
        rejected(lambda c: c["governed_jobs"][0]["surface"].update(**{"class": "unknown"}), "unknown diagnostic")
        rejected(lambda c: c["governed_jobs"][0]["surface"].update(step={"name": "elsewhere"}), "not tied")
        rejected(lambda c: c["artifact_uploads"].pop(), "inventory differs")
        rejected(lambda c: c["artifact_uploads"].append(c["artifact_uploads"][0]), "duplicate artifact")
        rejected(lambda c: c["artifact_uploads"][0].update(retention_class="unknown"), "unknown retention")


def test_real_contract_enumerates_every_upload() -> None:
    subject.validate_contract(ROOT)
    contract = _yaml(ROOT / subject.CONTRACT_PATH)
    assert len(contract["artifact_uploads"]) == len(subject._actual_uploads(ROOT)) == 6


def test_validation_result_uploads_are_declared_in_the_contract() -> None:
    contract = _yaml(ROOT / subject.CONTRACT_PATH)
    declared = {(item["workflow"], item["job"], item["step"], item["artifact"]) for item in contract["artifact_uploads"]}
    assert (
        ".github/workflows/ci.yml",
        "main-validate",
        "Upload validation-result evidence (CI-RCA attribution substrate)",
        "validation-result",
    ) in declared
    assert (
        ".github/workflows/main-canary.yml",
        "canary",
        "Upload validation-result evidence (CI-RCA attribution substrate)",
        "validation-result",
    ) in declared


@pytest.mark.parametrize(("age", "state"), [(13, "available"), (15, "unavailable_expired")])
def test_delayed_rca_state(age: int, state: str) -> None:
    policy = _yaml(ROOT / subject.CONTRACT_PATH)["retention_classes"]["ordinary_ci"]
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    result = subject.evidence_availability(policy, now - timedelta(days=age), now)
    assert result["state"] == state
    assert result["recovery"] == ("not_required" if state == "available" else "rerun_ci")


def test_delayed_rca_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        subject.evidence_availability({"delayed_rca_days": 1}, datetime.now(), datetime.now())


def test_malformed_yaml_root(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / subject.CONTRACT_PATH).write_text("- invalid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a mapping"):
        subject.validate_contract(root)


def test_contract_structure_failures(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path, contract = _contract(root)
    contract["governed_jobs"] = "bad"
    _write(path, contract)
    with pytest.raises(ValueError, match="nonempty list"):
        subject.validate_contract(root)


def test_missing_and_invalid_s1_targets(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path, contract = _contract(root)
    contract["s1_linkage"]["producer"] = "missing.py"
    _write(path, contract)
    with pytest.raises(ValueError, match="producer target is missing"):
        subject.validate_contract(root)
    contract["s1_linkage"]["producer"] = "scripts/ci_rca/taxonomy.py"
    _write(path, contract)
    with pytest.raises(ValueError, match="does not expose publish_envelope"):
        subject.validate_contract(root)


def test_upload_requires_integer_and_bounded_retention(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    data = _yaml(workflow)
    data["jobs"]["pr-validate"]["steps"][-1]["with"]["retention-days"] = "14"
    _write(workflow, data)
    with pytest.raises(ValueError, match="integer retention-days"):
        subject.validate_contract(root)
    data["jobs"]["pr-validate"]["steps"][-1]["with"]["retention-days"] = 30
    _write(workflow, data)
    with pytest.raises(ValueError, match="outside class bounds"):
        subject.validate_contract(root)


def test_selector_and_entry_shapes(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path, contract = _contract(root)
    contract["governed_jobs"][0]["critical_step"] = {"id": "x", "name": "y"}
    _write(path, contract)
    with pytest.raises(ValueError, match="exactly one"):
        subject.validate_contract(root)
    contract["governed_jobs"] = ["bad"]
    _write(path, contract)
    with pytest.raises(ValueError, match="entry must be a mapping"):
        subject.validate_contract(root)


def test_registered_check_reports_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(subject, "validate_contract", lambda _root: (_ for _ in ()).throw(ValueError("broken")))
    failed: list[str] = []
    subject.validate_actions_evidence(failed)
    assert failed == ["GitHub Actions evidence governance"]
    assert "FAIL: broken" in capsys.readouterr().out


def test_registered_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    failed: list[str] = []
    subject.validate_actions_evidence(failed)
    assert failed == []
    assert "PASS: governed diagnostics" in capsys.readouterr().out


@pytest.mark.parametrize("bad_steps", ["bad", ["bad"]])
def test_job_steps_must_be_mappings(bad_steps: Any) -> None:
    with pytest.raises(ValueError, match="list of mappings"):
        subject._steps({"steps": bad_steps})


def test_additional_contract_shape_failures(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path, baseline = _contract(root)

    def rejected(mutate, message: str) -> None:
        value = yaml.safe_load(yaml.safe_dump(baseline))
        mutate(value)
        _write(path, value)
        with pytest.raises(ValueError, match=message):
            subject.validate_contract(root)

    rejected(lambda c: c["retention_classes"].update(ordinary_ci="bad"), "expected a mapping")
    rejected(lambda c: c["governed_jobs"][0].update(critical_step={"name": ""}), "nonempty string")
    rejected(lambda c: c["governed_jobs"][0].pop("workflow"), "requires workflow and job")
    rejected(lambda c: c.update(artifact_uploads="bad"), "must be a list")


def test_s1_linkage_schema_is_v2_and_rejects_stale_v1(tmp_path: Path) -> None:
    """PLAN-ci-rca-evidence-scope-declaration: the real contract's s1_linkage.schema pins
    ci-rca-log-evidence/v2, and the guard behaviourally rejects a contract still declaring the
    superseded v1 string (a grep for the literal cannot show this -- only the guard can)."""
    contract = _yaml(ROOT / subject.CONTRACT_PATH)
    assert contract["s1_linkage"]["schema"] == "ci-rca-log-evidence/v2"

    root = _fixture(tmp_path)
    path, stale = _contract(root)
    stale["s1_linkage"]["schema"] = "ci-rca-log-evidence/v1"
    _write(path, stale)
    with pytest.raises(ValueError, match="S1 linkage schema must be ci-rca-log-evidence/v2"):
        subject.validate_contract(root)


def test_duplicate_workflow_display_name_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    workflow = root / ".github/workflows/main-canary.yml"
    workflow_data = _yaml(workflow)
    workflow_data["name"] = "CI"
    _write(workflow, workflow_data)
    path, contract = _contract(root)
    contract["governed_jobs"][4]["workflow_name"] = "CI"
    _write(path, contract)
    with pytest.raises(ValueError, match="display name is ambiguous"):
        subject.validate_contract(root)
