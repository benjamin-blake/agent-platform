"""Tests for scripts/terraform_apply_guard.py (Decision 77 deterministic sandbox-apply guard).

The clean-create case loads a fixture captured from a REAL `terraform show -json` run
(tests/fixtures/terraform_apply_guard/clean_create_real.json) so the guard's field paths are
validated against the actual schema, not hand-authored guesses. The destructive / IAM / trust
cases are synthesised to the same schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.terraform_apply_guard import (
    _classify_iam_change,
    _normalise_policy,
    _trust_changed,
    build_digest,
    evaluate_plan,
    main,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "terraform_apply_guard"
_REAL_CLEAN_CREATE = _FIXTURES / "clean_create_real.json"


def _write(tmp_path: Path, payload: dict) -> str:
    target = tmp_path / "plan.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return str(target)


def _rc(rtype: str, actions: list[str], before=None, after=None, address: str | None = None) -> dict:
    return {
        "address": address or f"{rtype}.example",
        "type": rtype,
        "name": "example",
        "change": {"actions": actions, "before": before, "after": after},
    }


def test_real_clean_create_passes() -> None:
    # Real terraform show -json fixture: a single create on a non-IAM resource.
    assert _REAL_CLEAN_CREATE.exists()
    plan = json.loads(_REAL_CLEAN_CREATE.read_text(encoding="utf-8"))
    assert plan["resource_changes"][0]["type"] == "terraform_data"
    assert evaluate_plan(plan) == []
    assert main([str(_REAL_CLEAN_CREATE)]) == 0


def test_delete_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_s3_bucket", ["delete"], before={"id": "b"})]}
    assert main([_write(tmp_path, plan)]) == 2


def test_replacement_delete_create_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_dynamodb_table", ["delete", "create"])]}
    assert main([_write(tmp_path, plan)]) == 2


def test_replacement_create_delete_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_dynamodb_table", ["create", "delete"])]}
    assert main([_write(tmp_path, plan)]) == 2


def test_iam_update_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_iam_role_policy", ["update"], before={"policy": "{}"}, after={"policy": "{}"})]}
    assert main([_write(tmp_path, plan)]) == 2


def test_iam_create_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_iam_role", ["create"], after={"name": "r"})]}
    assert main([_write(tmp_path, plan)]) == 2


def test_iam_noop_passes(tmp_path: Path) -> None:
    # IAM-sensitive type but inert action -> not blocked by the IAM rule and no trust diff.
    plan = {"resource_changes": [_rc("aws_iam_role", ["no-op"], before={"name": "r"}, after={"name": "r"})]}
    assert main([_write(tmp_path, plan)]) == 0


def test_trust_diff_on_non_iam_resource_blocks(tmp_path: Path) -> None:
    # The trust check applies to ANY resource type, even otherwise-allowed ones.
    before = {"assume_role_policy": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]})}
    after = {"assume_role_policy": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny"}]})}
    plan = {"resource_changes": [_rc("aws_some_resource", ["update"], before=before, after=after)]}
    assert main([_write(tmp_path, plan)]) == 2


def test_trust_diff_key_order_normalised_passes(tmp_path: Path) -> None:
    # Same policy, different key order -> normalised equal -> no trust finding.
    before = {"assume_role_policy": '{"Version":"2012-10-17","Statement":[]}'}
    after = {"assume_role_policy": '{"Statement":[],"Version":"2012-10-17"}'}
    plan = {"resource_changes": [_rc("aws_other_resource", ["update"], before=before, after=after)]}
    assert evaluate_plan(plan) == []
    assert main([_write(tmp_path, plan)]) == 0


def test_clean_update_passes(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("aws_s3_bucket", ["update"], before={"tags": {}}, after={"tags": {"a": "b"}})]}
    assert main([_write(tmp_path, plan)]) == 0


# ---------------------------------------------------------------------------
# Neon-aware policy (T2.16b / CD.34): a neon_* change auto-applies only as a pure create / no-op /
# read; an update blocks; delete + replace are caught by the existing delete rule.
# ---------------------------------------------------------------------------


def test_neon_create_passes(tmp_path: Path) -> None:
    # The provisioning path. Compensating controls (TLS + scoped role + Secrets Manager DSN), not an
    # IP allow-list, carry the posture, so a bare create is safe; sensitive/unknown after-values are
    # irrelevant to the verdict (the guard never introspects neon attributes).
    plan = {"resource_changes": [_rc("neon_project", ["create"], after={"name": "ducklake-catalog"})]}
    assert evaluate_plan(plan) == []
    assert main([_write(tmp_path, plan)]) == 0


def test_neon_database_and_role_create_pass(tmp_path: Path) -> None:
    plan = {
        "resource_changes": [
            _rc("neon_role", ["create"], after={"name": "ducklake_ops"}),
            _rc("neon_database", ["create"], after={"name": "ducklake_ops"}),
        ]
    }
    assert main([_write(tmp_path, plan)]) == 0


def test_neon_noop_passes(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("neon_project", ["no-op"], before={"name": "p"}, after={"name": "p"})]}
    assert main([_write(tmp_path, plan)]) == 0


def test_neon_read_passes(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("neon_project", ["read"], after={"name": "p"})]}
    assert main([_write(tmp_path, plan)]) == 0


def test_neon_update_blocks(tmp_path: Path) -> None:
    # An update is where an allow-list widening / credential rotation / project-setting change lands.
    plan = {"resource_changes": [_rc("neon_project", ["update"], before={"name": "p"}, after={"name": "p2"})]}
    findings = evaluate_plan(plan)
    assert len(findings) == 1
    assert findings[0]["type"] == "neon_project"
    assert "neon_*" in findings[0]["reason"]
    assert main([_write(tmp_path, plan)]) == 2


def test_neon_replace_blocks(tmp_path: Path) -> None:
    # Replace (delete+create) is caught by the delete rule -- credential/endpoint churn is unsafe.
    plan = {"resource_changes": [_rc("neon_role", ["delete", "create"])]}
    assert main([_write(tmp_path, plan)]) == 2


def test_neon_delete_blocks(tmp_path: Path) -> None:
    plan = {"resource_changes": [_rc("neon_database", ["delete"], before={"name": "ducklake_ops"})]}
    assert main([_write(tmp_path, plan)]) == 2


def test_neon_create_alongside_aws_secret_create_passes(tmp_path: Path) -> None:
    # The DSN secret (aws_secretsmanager_secret) creates alongside the neon resources -- both safe.
    plan = {
        "resource_changes": [
            _rc("neon_project", ["create"], after={"name": "ducklake-catalog"}),
            _rc("aws_secretsmanager_secret", ["create"], after={"name": "ducklake-neon-catalog-dsn"}),
        ]
    }
    assert main([_write(tmp_path, plan)]) == 0


def test_aws_verdicts_unchanged_by_neon_rule(tmp_path: Path) -> None:
    # Regression guard: the aws_ side is unchanged. A non-neon update still passes, an aws destroy
    # still blocks, and an IAM create still blocks -- the neon rule never alters an aws verdict.
    assert main([_write(tmp_path, {"resource_changes": [_rc("aws_s3_bucket", ["update"], before={}, after={})]})]) == 0
    assert main([_write(tmp_path, {"resource_changes": [_rc("aws_s3_bucket", ["delete"], before={"id": "b"})]})]) == 2
    assert main([_write(tmp_path, {"resource_changes": [_rc("aws_iam_role", ["create"], after={"name": "r"})]})]) == 2


def test_empty_plan_passes(tmp_path: Path) -> None:
    assert main([_write(tmp_path, {})]) == 0


def test_malformed_json_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert main([str(bad)]) == 1


def test_missing_file_errors(tmp_path: Path) -> None:
    assert main([str(tmp_path / "does_not_exist.json")]) == 1


def test_top_level_not_object_errors(tmp_path: Path) -> None:
    target = tmp_path / "list.json"
    target.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert main([str(target)]) == 1


def test_usage_error_no_args() -> None:
    assert main([]) == 1


def test_usage_error_too_many_args() -> None:
    assert main(["a", "b"]) == 1


def test_normalise_policy_unparseable_string() -> None:
    assert _normalise_policy("not json {{{") == "not json {{{"


def test_normalise_policy_non_string_passthrough() -> None:
    assert _normalise_policy({"already": "parsed"}) == {"already": "parsed"}
    assert _normalise_policy(None) is None


def test_trust_changed_handles_non_dict_states() -> None:
    assert _trust_changed(None, {"assume_role_policy": "{}"}) is False
    assert _trust_changed({"assume_role_policy": "{}"}, None) is False


# ---------------------------------------------------------------------------
# In-budget IAM classification (T2.25 / Decision 92 point 5): inline-policy /
# attachment UPDATE on managed boundary-carrying role auto-applies; everything
# else (wrong type, wrong action, unmanaged role, no budget) blocks.
# ---------------------------------------------------------------------------

_BUDGET = {
    "schema_version": 1,
    "boundary_policy_name": "agent-platform-github-ci-apply-boundary",
    "in_budget_managed_roles": ["agent-platform-github-ci-branch", "agent-platform-github-ci-pr"],
    "in_budget_resource_types": ["aws_iam_role_policy", "aws_iam_role_policy_attachment"],
    "in_budget_actions": ["update"],
}


def _make_budget_file(tmp_path: Path) -> Path:
    p = tmp_path / "authority_budget.json"
    p.write_text(json.dumps(_BUDGET), encoding="utf-8")
    return p


def test_in_budget_inline_policy_update_on_branch_role_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget_path = _make_budget_file(tmp_path)
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(budget_path))
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy",
                ["update"],
                before={"role": "agent-platform-github-ci-branch", "policy": "{}"},
                after={"role": "agent-platform-github-ci-branch", "policy": '{"Version":"2012-10-17"}'},
                address="aws_iam_role_policy.ci_branch_inline",
            )
        ]
    }
    assert evaluate_plan(plan, _BUDGET) == []
    assert main([_write(tmp_path, plan)]) == 0


def test_in_budget_attachment_update_on_pr_role_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget_path = _make_budget_file(tmp_path)
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(budget_path))
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy_attachment",
                ["update"],
                before={"role": "agent-platform-github-ci-pr", "policy_arn": "arn:aws:iam::aws:policy/OldPolicy"},
                after={"role": "agent-platform-github-ci-pr", "policy_arn": "arn:aws:iam::aws:policy/NewPolicy"},
            )
        ]
    }
    assert evaluate_plan(plan, _BUDGET) == []
    assert main([_write(tmp_path, plan)]) == 0


def test_out_of_budget_inline_policy_on_non_managed_role_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget_path = _make_budget_file(tmp_path)
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(budget_path))
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy",
                ["update"],
                before={"role": "some-other-role", "policy": "{}"},
                after={"role": "some-other-role", "policy": '{"Version":"2012-10-17"}'},
            )
        ]
    }
    findings = evaluate_plan(plan, _BUDGET)
    assert len(findings) == 1
    assert "out-of-budget" in findings[0]["reason"]
    assert main([_write(tmp_path, plan)]) == 2


def test_trust_diff_on_managed_role_type_still_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Trust-diff check fires BEFORE IAM classification; a trust change on an in-budget type is gated.
    budget_path = _make_budget_file(tmp_path)
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(budget_path))
    before = {
        "role": "agent-platform-github-ci-branch",
        "assume_role_policy": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]}),
    }
    after = {
        "role": "agent-platform-github-ci-branch",
        "assume_role_policy": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny"}]}),
    }
    plan = {"resource_changes": [_rc("aws_iam_role_policy", ["update"], before=before, after=after)]}
    findings = evaluate_plan(plan, _BUDGET)
    assert len(findings) == 1
    assert "trust-policy" in findings[0]["reason"]
    assert main([_write(tmp_path, plan)]) == 2


def test_iam_create_on_in_budget_type_still_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Creates are not in in_budget_actions (["update"]) -- role CREATES stay gated (new trust surface).
    budget_path = _make_budget_file(tmp_path)
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(budget_path))
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy",
                ["create"],
                after={"role": "agent-platform-github-ci-branch", "policy": "{}"},
            )
        ]
    }
    assert main([_write(tmp_path, plan)]) == 2


def test_fail_closed_on_missing_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(tmp_path / "does_not_exist.json"))
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy",
                ["update"],
                before={"role": "agent-platform-github-ci-branch", "policy": "{}"},
                after={"role": "agent-platform-github-ci-branch", "policy": '{"Version":"2012-10-17"}'},
            )
        ]
    }
    # Without a valid budget table, all IAM changes are out-of-budget (fail-closed).
    assert _classify_iam_change(plan["resource_changes"][0], None) is False
    assert main([_write(tmp_path, plan)]) == 2


def test_in_budget_fixture_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    # VP step 2: the real fixture passes when the real budget table is loaded.
    fixture = Path(__file__).parent / "fixtures" / "terraform_apply_guard" / "iam_inline_update_branch.json"
    assert fixture.exists(), f"fixture missing: {fixture}"
    # Unset any override so the default budget path (the real authority_budget.json) is used.
    monkeypatch.delenv("TF_AUTHORITY_BUDGET", raising=False)
    assert main([str(fixture)]) == 0


# ---------------------------------------------------------------------------
# --digest mode (T2.39 / rec-2658 forward-fix): bounded, decision-relevant plan summary for the
# subagent reviewer's stdin. VP steps 1-2.
# ---------------------------------------------------------------------------


def _digest_plan() -> dict:
    return {
        "resource_changes": [
            _rc("aws_s3_bucket", ["create"], after={"bucket": "new-bucket"}),
            _rc(
                "aws_iam_role_policy",
                ["update"],
                before={"role": "agent-platform-github-ci-branch", "policy": "{}"},
                after={"role": "agent-platform-github-ci-branch", "policy": '{"Version":"2012-10-17"}'},
                address="aws_iam_role_policy.ci_branch_inline",
            ),
            _rc("aws_dynamodb_table", ["delete", "create"], address="aws_dynamodb_table.replaced"),
        ]
    }


def test_digest_lists_resource_changes_content() -> None:
    digest = build_digest(_digest_plan())
    assert "3 resource change(s)" in digest
    assert "aws_s3_bucket.example (aws_s3_bucket) actions=['create'] changed_attrs=[bucket='new-bucket']" in digest
    assert "aws_iam_role_policy.ci_branch_inline (aws_iam_role_policy) actions=['update'] changed_attrs=[policy=" in digest
    assert "aws_dynamodb_table.replaced (aws_dynamodb_table) actions=['delete', 'create'] changed_attrs=[(none)]" in digest


def test_digest_reuses_resource_changes_traversal_same_set_as_evaluate_plan() -> None:
    plan = _digest_plan()
    digest = build_digest(plan)
    findings = evaluate_plan(plan)
    # Every resource address that shows up in a guard finding also appears in the digest --
    # the digest can never omit a resource the verdict was computed over.
    for finding in findings:
        assert finding["address"] in digest


def test_digest_cli_flag_prints_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = _write(tmp_path, _digest_plan())
    assert main(["--digest", path]) == 0
    out = capsys.readouterr().out
    assert "resource change(s)" in out


def test_digest_flag_still_errors_on_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert main(["--digest", str(bad)]) == 1


def test_digest_empty_plan() -> None:
    digest = build_digest({})
    assert "0 resource change(s)" in digest


def test_digest_redacts_arn_and_account_id() -> None:
    # ARN/account-id values land in the digest via the changed-attribute value snippet, so this
    # exercises the real leak surface (Decision 101), not just the redaction helper standalone.
    # Uses the AWS-managed AWSSDKPandas layer account (336392948345, public, not a secret -- the
    # pre-commit never-commit hook's explicit allowlisted exemption) as the stand-in fake account
    # id, so a genuinely fake-but-realistic 12-digit ARN doesn't itself trip that shape-based hook.
    plan = {
        "resource_changes": [
            _rc(
                "aws_iam_role_policy_attachment",
                ["update"],
                before={"policy_arn": "arn:aws:iam::336392948345:policy/OldPolicy"},
                after={"policy_arn": "arn:aws:iam::336392948345:policy/NewPolicy", "account_note": "336392948345"},
            )
        ]
    }
    digest = build_digest(plan)
    assert "336392948345" not in digest
    assert "arn:aws:iam::336392948345" not in digest
    assert "[ARN]" in digest
    assert "[ACCOUNT_ID]" in digest

    from scripts.terraform_apply_guard import _redact  # noqa: PLC0415

    assert _redact("account=336392948345 arn=arn:aws:s3:::my-bucket/336392948345/x") == "account=[ACCOUNT_ID] arn=[ARN]"


def test_digest_size_cap_truncates_with_marker() -> None:
    # Many resources so the full digest exceeds a deliberately tiny cap.
    plan = {
        "resource_changes": [
            _rc("aws_s3_bucket", ["update"], before={"tags": {}}, after={"tags": {"a": str(i)}}, address=f"aws_s3_bucket.b{i}")
            for i in range(50)
        ]
    }
    digest = build_digest(plan, size_cap=200)
    assert len(digest.encode("utf-8")) <= 200 + 10  # marker itself is within the accounted budget
    assert "DIGEST TRUNCATED" in digest
    # Truncation happens at a line boundary -- no entry is cut mid-line.
    for line in digest.split("\n... [DIGEST TRUNCATED")[0].splitlines():
        if line.startswith("- "):
            assert line.count("changed_attrs=[") == 1


def test_digest_under_cap_no_truncation_marker() -> None:
    digest = build_digest(_digest_plan(), size_cap=100_000)
    assert "TRUNCATED" not in digest
