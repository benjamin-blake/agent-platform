# Plan

## Intent
Restore CI to green by fixing two independent failures that were surfaced when PR #315 wired
`ensure_fresh_dq_results` and `validate_verification_harness` into the unconditional presubmit
path: a unit test escaping to real Athena, and the verification harness failing due to a missing
AWS CLI binary and an unapplied IAM permission.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/fix-ci-harness

## Phase
Phase 1: Core Infrastructure (Complete)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `tests/test_classify_risk.py` | Modify | Fix `test_classify_all_unclassified` to mock `get_backend`, `read_jsonl`, and `ops_data_portal.update_rec` so it cannot escape to real AWS |
| `scripts/validate.py` | Modify | Replace `subprocess ["aws", "sts", "get-caller-identity", ...]` in `ensure_fresh_dq_results` with a `boto3.Session.client("sts").get_caller_identity()` call to remove the AWS CLI binary dependency |
| `terraform/ec2_runner.tf` | No code change | IAM policy already correct from PR #316. Targeted apply in execution steps below. |

## Bundled Recommendations
- **rec-726** (DataQualityVerifier on CI: AWS CLI not in PATH) -- fully resolved by Step 2.

## Acceptance Criteria
- [ ] `pytest tests/test_classify_risk.py::TestClassifyRisk::test_classify_all_unclassified -v` passes locally with zero real AWS calls
- [ ] `python -m scripts.validate --pre` passes on the branch (lint/format gate)
- [ ] `terraform plan -target=aws_iam_policy.github_runner_ci -target=aws_iam_role_policy_attachment.github_runner_ci` shows only the expected policy update and is presented to the human for review
- [ ] Human approves and `terraform apply -target=...` completes successfully
- [ ] CI run on the merged branch passes all checks including Verification Harness

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Unit test passes with mocks, no real AWS calls | `pytest tests/test_classify_risk.py::TestClassifyRisk::test_classify_all_unclassified -v -s` | `1 passed` in output; no `RuntimeError` or Athena mention | Extend mock patches to cover any remaining real call sites |
| 2 | pre-deploy | Full unit suite still passes | `pytest tests/ -m "not integration" --tb=short -q 2>&1 \| tail -5` | `0 failed` | Fix any regressions introduced by mock changes |
| 3 | pre-deploy | boto3 credential check is present in validate.py and AWS CLI check removed | `python -c "import ast, pathlib; src=pathlib.Path('scripts/validate.py').read_text(); tree=ast.parse(src); print('OK' if 'get_caller_identity' in src and 'FileNotFoundError' not in src.split('ensure_fresh_dq_results')[1].split('def ')[0] else 'FAIL')"` | `OK` | Verify `ensure_fresh_dq_results` body no longer catches `FileNotFoundError` from a subprocess aws call |
| 4 | pre-deploy | Presubmit lint/format passes | `.venv/Scripts/python.exe -m scripts.validate --pre` | `All checks passed` | Fix ruff lint or format violations |
| 5 | post-deploy | Targeted terraform plan presented for human review | `cd terraform && terraform plan -target=aws_iam_policy.github_runner_ci -target=aws_iam_role_policy_attachment.github_runner_ci -no-color 2>&1` | Plan shows update to `aws_iam_policy.github_runner_ci` adding `athena:GetWorkGroup`; 0 destroys | If plan shows unexpected destroys or replacements, stop and investigate |
| 6 | post-deploy | Human approves; terraform apply executed | `cd terraform && terraform apply -target=aws_iam_policy.github_runner_ci -target=aws_iam_role_policy_attachment.github_runner_ci -auto-approve 2>&1` | `Apply complete! Resources: 0 added, 1 changed, 0 destroyed` | If apply fails, check IAM state with `aws iam get-policy --policy-arn <arn> --profile company-aws-profile` |
| 7 | post-deploy | Verification harness passes end-to-end locally | `.venv/Scripts/python.exe -m scripts.validate 2>&1 \| grep -E "PASS\|FAIL\|SKIP" \| grep "AthenaViews\|CausalChain\|DataQuality"` | All three verifiers show `[PASS]` or `[SKIPPED]`; none show `[FAIL]` | If `AthenaViewsVerifier` still FAILs with AccessDenied, the apply did not propagate -- wait 30s and retry |
| 8 | post-deploy | CI passes on merged branch | `gh run view --branch main --limit 1 --json conclusion --jq '.conclusion'` | `"success"` | Inspect CI logs for any remaining failure; file rec if new issue discovered |

## Constraints
- No rescue agents or workaround loops (Decision 55)
- Lambda deployment deferred (Decision 67) -- no Lambda files in scope
- `terraform apply` must be preceded by presenting the plan output to the human (user's instruction for this plan)
- Do not run `terraform apply` without explicit "apply" confirmation from the human
- `terraform apply -target` is safe here because the two targeted resources (policy + attachment) have no downstream dependencies that would be affected by a partial apply
- Do not touch rec-725 (full terraform state reconciliation) -- it is out of scope

## Context
- **PR #315** (commit 44e6a8f, merged 2026-05-10) wired `ensure_fresh_dq_results` and
  `validate_verification_harness` into validate.py's unconditional presubmit path, surfacing
  two pre-existing infrastructure gaps.
- **PR #316** (commit 6147af7) added `athena:GetWorkGroup` to `ec2_runner.tf`'s IAM policy
  and `AWS_DEFAULT_REGION` to ci.yml -- the code is correct but `terraform apply` was never
  run, so the live runner IAM still lacks the permission.
- **AWS CLI** was deliberately removed from the runner's `user_data` in the original runner PR
  (4bd5b17) to avoid a 400 MB dependency. `ensure_fresh_dq_results` must not require the CLI
  binary -- switching to boto3 resolves this permanently.
- **`classify_all_unclassified`** branches on `get_backend()`: when `S3_LOG_BUCKET` is set
  (as it is in CI), it reads from S3/Athena instead of the local JSONL. The test never mocked
  this branch, causing it to hit real Athena. Added in PR #314 (ops-pipeline-consolidation);
  test not updated at that time.
- `SchemaIntegrityVerifier` SKIPS with "must specify region" -- this is a separate minor bug
  (no explicit boto3 session passed to `wr.catalog.get_table_types`). It does not contribute
  to any CI FAIL; out of scope for this plan.
- Decision 57: when SSO/credentials are unavailable, `ensure_fresh_dq_results` must print an
  actionable message and skip (not crash). The boto3 replacement must preserve this contract.
- rec-726 is fully addressed by Step 2 and should be marked `closed` after merge.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (relevant: Decision 55, 57, 67, 68)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **`tests/test_classify_risk.py` -- fix `test_classify_all_unclassified`**
   - Add `patch("scripts.classify_risk.get_backend", return_value="local")` to the patch
     context so the function takes the local-JSONL branch regardless of environment variables.
   - Add `patch("scripts.ops_data_portal.update_rec")` to prevent the lazy-imported
     `update_rec` from calling real Athena; assert `call_count == 2` to verify two records
     were processed.
   - Remove the now-unnecessary `patch("scripts.classify_risk.Path")` if the local path is
     correctly handled via `monkeypatch.chdir(tmp_path)` alone; otherwise keep it.
   - Confirm the patched test passes: `pytest tests/test_classify_risk.py::TestClassifyRisk::test_classify_all_unclassified -v`

2. **`scripts/validate.py` -- replace CLI credential check with boto3**
   - In `ensure_fresh_dq_results`, replace the `try/except FileNotFoundError` block that
     shells to `["aws", "sts", "get-caller-identity", "--profile", ...]` with:
     ```python
     try:
         import boto3
         profile = os.environ.get("AWS_PROFILE", "company-aws-profile")
         boto3.Session(profile_name=profile).client("sts", region_name="eu-west-2").get_caller_identity()
     except Exception:
         print(
             "AWS credentials not available -- skipping data_quality_runner auto-invoke. "
             "Ensure AWS credentials are configured to enable DQ refresh (Decision 57)."
         )
         return
     ```
   - Remove the `sso_check.returncode != 0` branch that follows (the boto3 call raises on
     failure; no return code to check).
   - Keep the `invoke_step("Data quality runner", ...)` call that follows unchanged.

3. **Execute Verification Plan steps 1-4** (pre-deploy) -- run each, loop until all pass.
   If V2 tests still fail, return to steps 1-2.

4. **Present terraform plan for human review**
   - Run VP step 5: `cd terraform && terraform plan -target=aws_iam_policy.github_runner_ci -target=aws_iam_role_policy_attachment.github_runner_ci -no-color`
   - Present the full plan output to the human.
   - **Stop here and wait for the human to say "apply".** Do not proceed to Step 5 until
     explicit approval is received.

5. **Apply terraform (after human approval)**
   - Run VP step 6: `cd terraform && terraform apply -target=aws_iam_policy.github_runner_ci -target=aws_iam_role_policy_attachment.github_runner_ci -auto-approve`
   - Report the apply result.

6. **Mark rec-726 done via ops_data_portal**
   - `.venv/Scripts/python.exe -m scripts.ops_data_portal update_rec rec-726 '{"status": "closed"}'`

7. **Execute Verification Plan steps 7-8** (post-deploy) -- run harness locally, then
   push and confirm CI passes.

8. **Report**: summarise what was implemented, verification results, and any follow-up
   observations (e.g., SchemaIntegrityVerifier region bug for a future rec).
