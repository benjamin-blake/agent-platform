from scripts.checks.registry import full_sequence, pre_sequence


def test_plan_obligation_guard_runs_in_pre_and_full_without_promoting_coverage() -> None:
    pre = [step.name for step in pre_sequence()]
    full = [step.name for step in full_sequence()]
    assert "validate_plan_documents" in pre
    assert "validate_plan_documents" in full
    assert "validate_test_coverage" not in pre
    assert "validate_test_coverage" in full
