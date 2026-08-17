"""Tests for validate_oidc_failopen_guards() (Decision 172 PR-2 / OIDC immutable-subject-recovery).

Inline fixtures (not real-tree extractions, unlike the masked-errexit guard's mirror -- this is a
NEW guard with no pre-existing behaviour to stay byte-identical to) covering every masking shape
and every sanctioned classifier quoting form named in VP step 4.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ci_guards.validate_oidc_failopen_guards import validate_oidc_failopen_guards

_ROOT_PATCH_TARGET = "scripts.checks._common.ROOT"


def _run(tmp_path: Path, filename: str, content: str) -> list[str]:
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / filename).write_text(content, encoding="utf-8")
    with patch(_ROOT_PATCH_TARGET, tmp_path):
        failed: list[str] = []
        validate_oidc_failopen_guards(failed)
    return failed


_NO_ID_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Do a thing
        run: echo hi
"""

_POSITIVE_ONLY_WORKFLOW = """
name: fixture
on: push
jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: oidc_plan
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Plan
        if: success() && steps.oidc_plan.outcome == 'success'
        run: echo planning
"""

_SINGLE_QUOTED_NEGATIVE_IF_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: oidc_drift
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Fail loudly on assume failure
        if: steps.oidc_drift.outcome != 'success'
        run: exit 1
      - name: Do the real work
        if: steps.oidc_drift.outcome == 'success'
        run: echo doing work
"""

# The exact ci.yml mirror_oidc shape: double-quoted, brace-split (!= separated from `outcome` by
# the closing `}}` and a quote character), inside an inline run: body.
_DOUBLE_QUOTED_BRACE_SPLIT_RUN_WORKFLOW = """
name: fixture
on: push
jobs:
  terraform-validate:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: mirror_oidc
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Provider-mirror gate chain
        run: |
          if [ "${{ steps.mirror_oidc.outcome }}" != "success" ]; then
            reason="gate 1/3 failed"
          fi
"""

_CONCLUSION_ONLY_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: oidc_drift
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Dead classifier -- .conclusion is forced to success under continue-on-error
        if: steps.oidc_drift.conclusion != 'success'
        run: exit 1
"""

_NO_CONTINUE_ON_ERROR_WORKFLOW = """
name: fixture
on: push
jobs:
  branch:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: oidc_branch
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Do a thing
        run: echo hi
"""


_MALFORMED_YAML_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    steps: [unclosed
"""

_NON_DICT_DOCUMENT_WORKFLOW = """
- not
- a
- mapping
"""

_NON_DICT_JOBS_WORKFLOW = """
name: fixture
on: push
jobs: not-a-mapping
"""

_NON_DICT_JOB_WORKFLOW = """
name: fixture
on: push
jobs:
  drift: not-a-mapping
"""

_NON_LIST_STEPS_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps: not-a-list
"""

# A non-dict step element must be skipped identically by BOTH loops that walk the steps list --
# _job_search_text's corpus-building loop (line 75) and _scan_job's candidate loop (line 101) --
# so the fixture threads a proper compliant step alongside the malformed one to prove the scan
# still classifies the job correctly rather than merely not crashing.
_NON_DICT_STEP_ELEMENT_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - just-a-string-not-a-mapping
      - name: Configure AWS credentials
        id: oidc_drift
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Fail loudly on assume failure
        if: steps.oidc_drift.outcome != 'success'
        run: exit 1
"""

# Mixes a str env value (the classifier itself) with a non-str value so the isinstance filter on
# line 84 is genuinely exercised -- a str-only env dict would leave the filter's non-str branch
# untested even though the line executes.
_MIXED_ENV_TYPES_WORKFLOW = """
name: fixture
on: push
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        id: oidc_drift
        continue-on-error: true
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123:role/x
      - name: Classifier lives in env, mixed with a non-str value
        env:
          NEGATIVE_CHECK: "steps.oidc_drift.outcome != 'success'"
          RETRY_COUNT: 3
        run: echo hi
"""


class TestDefensiveBranchesOnMalformedInput:
    def test_skips_file_that_fails_to_parse(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "malformed.yml", _MALFORMED_YAML_WORKFLOW)
        assert failed == []

    def test_skips_non_dict_top_level_document(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "non_dict_doc.yml", _NON_DICT_DOCUMENT_WORKFLOW)
        assert failed == []

    def test_skips_non_dict_jobs_mapping(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "non_dict_jobs.yml", _NON_DICT_JOBS_WORKFLOW)
        assert failed == []

    def test_skips_non_dict_job(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "non_dict_job.yml", _NON_DICT_JOB_WORKFLOW)
        assert failed == []

    def test_skips_non_list_steps_value(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "non_list_steps.yml", _NON_LIST_STEPS_WORKFLOW)
        assert failed == []

    def test_skips_non_dict_step_element_and_still_finds_negative_branch(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "non_dict_step.yml", _NON_DICT_STEP_ELEMENT_WORKFLOW)
        assert failed == []

    def test_env_filter_tolerates_non_str_values_and_still_matches_str_classifier(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "mixed_env.yml", _MIXED_ENV_TYPES_WORKFLOW)
        assert failed == []


class TestFiresOnMaskingShapes:
    def test_fires_on_missing_id(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "no_id.yml", _NO_ID_WORKFLOW)
        assert any("no id" in f for f in failed), failed

    def test_fires_on_positive_only_gates(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "positive_only.yml", _POSITIVE_ONLY_WORKFLOW)
        assert any("no negative-branch classifier" in f for f in failed), failed

    def test_fires_on_conclusion_only_reference(self, tmp_path: Path) -> None:
        """.conclusion is forced to success under continue-on-error -- a dead classifier."""
        failed = _run(tmp_path, "conclusion_only.yml", _CONCLUSION_ONLY_WORKFLOW)
        assert any("no negative-branch classifier" in f for f in failed), failed


class TestSilentOnSanctionedClassifiers:
    def test_silent_on_single_quoted_if_level_negative_classifier(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "single_quoted.yml", _SINGLE_QUOTED_NEGATIVE_IF_WORKFLOW)
        assert failed == []

    def test_silent_on_double_quoted_brace_split_run_body_classifier(self, tmp_path: Path) -> None:
        """The exact ci.yml mirror_oidc shape -- must not be missed by an over-narrow proximity match."""
        failed = _run(tmp_path, "double_quoted.yml", _DOUBLE_QUOTED_BRACE_SPLIT_RUN_WORKFLOW)
        assert failed == []

    def test_ignores_a_step_without_continue_on_error(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, "no_coe.yml", _NO_CONTINUE_ON_ERROR_WORKFLOW)
        assert failed == []


class TestExaminedDeclaration:
    def test_examined_count_matches_candidate_steps(self, tmp_path: Path) -> None:
        with patch("scripts.checks.registry.examined") as mock_examined:
            _run(tmp_path, "positive_only.yml", _POSITIVE_ONLY_WORKFLOW)
        mock_examined.assert_called_once()
        (count,), kwargs = mock_examined.call_args
        assert count == 1
        assert kwargs.get("unit") == "continue_on_error_assume_role_steps"
