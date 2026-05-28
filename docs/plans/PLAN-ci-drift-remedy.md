# Plan

## Intent
Fix two CI failure modes that cause local validate runs to silently pass while CI fails:
(1) missing `s3:DeleteObject` in the runner IAM policy, and (2) false-positive
`SchemaIntegrityVerifier` failures caused by a Python `ClassVar`/`from __future__ import annotations`
incompatibility and stale `injected_cols`. Install a static IAM coverage gate that runs in
`--pre` mode, so the next IAM policy gap is caught locally before it reaches CI.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/ci-drift-remedy

## Phase
Platform (CI/tooling hardening, parallel to Phase 2)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `config/iam_runner_manifest.yaml` | Create | Declarative list of all IAM actions required by CI code, with rationale and source file |
| `scripts/verifiers/harness.py` | Modify | Define `VerifierStatus.WARN` and `VerifierSeverity.WARN` |
| `scripts/validate.py` | Modify | Add `validate_iam_runner_policy()` to `--pre`; update `validate_verification_harness` to respect `ADVISORY`/`WARN` |
| `scripts/verifiers/schema_integrity.py` | Modify | Fix ClassVar exclusion via `typing.get_type_hints()`; `injected_cols` alignment; demote to `WARN` |
| `terraform/ec2_runner.tf` | Modify | Add `s3:DeleteObject` to `S3ReadWrite` IAM statement |
| `tests/test_validate.py` | Modify | Add tests for `validate_iam_runner_policy()` |
| `tests/test_verifiers/test_schema_integrity.py` | Create | Add test for ClassVar exclusion and corrected injected_cols |

## Bundled Recommendations
- **rec-602** (Remove 8 Decision-56-deprecated fields from Recommendation model): Model fields
  are already clean -- deprecated fields are handled by `extra="ignore"`. Accept as
  `already_implemented` via `ops_data_portal update_rec` at execution close.

## Infrastructure Dependencies
| Resource | Change | Timing |
|----------|--------|--------|
| `aws_iam_policy.github_runner_ci` | Add `s3:DeleteObject` to `S3ReadWrite` statement | `terraform plan` presented to human; `terraform apply` before merge |

## Acceptance Criteria
- [ ] `validate --pre` reports IAM check PASS after Terraform policy includes `s3:DeleteObject`
- [ ] `validate --pre` reports IAM check FAIL on a branch where `ec2_runner.tf` is missing a manifest action
- [ ] `SchemaIntegrityVerifier` produces WARN (not FAIL) for telemetry tables with pending schema migration
- [ ] `REQUIRED_FIELDS` and `TABLE_NAME` no longer appear in any schema drift report
- [ ] `ingested_at` and `trade_date` no longer appear as "missing in Athena" for any table
- [ ] Full `validate` exits 0 locally (SchemaIntegrityVerifier demoted to WARN/ADVISORY)
- [ ] All existing tests pass (no regressions)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Confirm IAM manifest check catches a missing action | temporarily remove `s3:DeleteObject` from `config/iam_runner_manifest.yaml`, run `--pre`, restore | `.venv/Scripts/python.exe -m scripts.validate --pre 2>&1 \| grep -i "iam\|manifest"` outputs FAIL mentioning `s3:DeleteObject` | `validate_iam_runner_policy` not wired into `--pre` |
| 2 | pre-deploy | Confirm IAM manifest check passes when policy is in sync | `.venv/Scripts/python.exe -m scripts.validate --pre 2>&1 \| grep -E "PASS\|iam_runner\|IAM runner"` | Reports PASS for IAM runner policy check | Action string mismatch between manifest and Terraform |
| 3 | pre-deploy | Confirm ClassVar fields excluded from verifier comparison | `.venv/Scripts/python.exe -c "import asyncio; from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier; r = asyncio.run(SchemaIntegrityVerifier().verify()); assert 'REQUIRED_FIELDS' not in r.message and 'TABLE_NAME' not in r.message, r.message; print('ClassVar fix: PASS')"` | Prints `ClassVar fix: PASS` | `get_type_hints()` branch not reached or ClassVar filter incorrect |
| 4 | pre-deploy | Confirm injected_cols no longer includes deprecated columns | `.venv/Scripts/python.exe -c "import asyncio; from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier; assert 'ingested_at' not in asyncio.run(SchemaIntegrityVerifier().verify()).message; print('injected_cols fix: PASS')"` | Prints `injected_cols fix: PASS` | `injected_cols` constant not updated |
| 5 | pre-deploy | Confirm verifier status is WARN, and harness doesn't fail build | `.venv/Scripts/python.exe -c "import asyncio; from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier; from scripts.verifiers.harness import VerifierStatus; r = asyncio.run(SchemaIntegrityVerifier().verify()); assert r.status == VerifierStatus.WARN; print('Severity fix: PASS')"` | Prints `Severity fix: PASS` | Status not WARN or harness still appends to `failed` |
| 6 | pre-deploy | Full test suite | `.venv/Scripts/python.exe -m pytest --tb=short -q` | All tests pass, 0 failures | Investigate and fix test regressions before proceeding |
| 7 | post-deploy | Run terraform plan (present diff to human before step 8) | `cd terraform && terraform plan -var-file=terraform.tfvars` | Plan shows exactly 1 change: `aws_iam_policy.github_runner_ci` updated to add `s3:DeleteObject` | Inspect diff; confirm no unintended changes |
| 8 | post-deploy | Terraform apply (human-approved) | `cd terraform && terraform apply -var-file=terraform.tfvars` | Apply succeeds; IAM policy updated | Check AWS console for runner role permissions |
| 9 | post-deploy | Full local validate after Terraform | `.venv/Scripts/python.exe -m scripts.validate 2>&1 \| tail -20` | Validation Summary shows no FAIL entries; SchemaIntegrityVerifier is WARN at worst | Investigate any new FAIL |

## Constraints
- No STRATEGIC plans (Decision 67 active): all steps are IMPLEMENTATION-scope with no executor dispatch
- Terraform `apply` is human-approved -- never automatic (per CLAUDE.md and terraform/CLAUDE.md)
- The `SchemaIntegrityVerifier` severity is downgraded to WARN as a temporary measure. When telemetry schema migration runs, restore it to HARD_GATE and remove this constraint note.
- `validate_iam_runner_policy()` uses string-matching against Terraform HCL text -- must match quoted strings (e.g., `"s3:DeleteObject"`) to prevent partial match false-positives.
- No rescue agents or workaround loops (Decision 55)

## Context
- **Root cause A (IAM):** `ops_writer.compact()` added `client.delete_object()` (PR #318,
  `fix(compact-temp-path-isolation)`) without updating `terraform/ec2_runner.tf`.
  Developer SSO credentials have full S3 access; the runner IAM role has a minimal scoped policy.
  No automatic coupling existed between new boto3 calls and the IAM policy.

- **Root cause B (SchemaIntegrityVerifier):** Python's `dataclasses._is_classvar()` does not handle
  string annotations produced by `from __future__ import annotations` -- confirmed empirically on
  Python 3.11.9 via `dc._is_classvar("ClassVar[str]", typing)` returning `False`. As a result,
  `TABLE_NAME: ClassVar[str]` and `REQUIRED_FIELDS: ClassVar[set[str]]` appear in
  `__dataclass_fields__` and are incorrectly compared against Athena column names.

- **Root cause C (injected_cols):** `injected_cols = {"created_timestamp", "last_updated_timestamp",
  "ingested_at", "trade_date"}` applied uniformly. Post-Decision-56 ops tables have
  `created_timestamp`/`last_updated_timestamp` but not `ingested_at`/`trade_date`. Telemetry tables
  (pre-migration) have the opposite. Both halves produce false "missing in Athena" reports.

- **Systemic drift mechanism:** `validate --pre` skips all V3 verifiers (Athena/AWS checks).
  Developers use `--pre` during edit loops; CI always runs the full suite. V3 failures
  accumulate silently until CI fires. The IAM manifest gate fixes this for IAM gaps specifically
  by moving the check into `--pre` mode (pure text, no AWS dependency).

- Decision 67 (Lambda deferred) is active -- no Lambda files are in scope.
- Decision 68: EC2 t3.medium runner in eu-west-2, `aws_iam_policy.github_runner_ci` is the target policy.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `config/iam_runner_manifest.yaml`** -- YAML list of IAM actions required by CI code;
   include `action`, `source` (file path), and `reason` for each. Must include all actions currently
   in `terraform/ec2_runner.tf` plus `s3:DeleteObject`. Format: `actions: [{action, source, reason}]`.

2. **Add `validate_iam_runner_policy()` to `scripts/validate.py`** -- Load manifest YAML, read
   `terraform/ec2_runner.tf` as text, assert each manifest `action` string appears **within quotes**
   (e.g., `f'"{action}"'`) in the Terraform file. Append to `failed` list if any are missing.
   Wire call into the `--pre` code path (after `run_lint_checks`, before `sys.exit`). Add tests in
   `tests/test_validate.py` covering: pass (all present), fail (action absent), quoted match requirement.

3. **Update `scripts/verifiers/harness.py`** -- Add `WARN = "WARN"` to `VerifierStatus` enum and
   `WARN = 15` to `VerifierSeverity` enum. Ensure `rank` property handles `WARN`.

4. **Update `scripts/validate.py` (harness logic)** -- In `validate_verification_harness()`, only
   append to `failed` if `res.status == VerifierStatus.FAIL` AND `res.severity >= VerifierSeverity.HARD_GATE`.
   If status is `WARN` or severity is `ADVISORY`, print as warning but do not fail the build.

5. **Fix `scripts/verifiers/schema_integrity.py`** -- Three changes in order:
   a. Replace `__dataclass_fields__` path with `typing.get_type_hints()` branch that explicitly
      filters out `ClassVar` annotations (check `hint.__origin__ is typing.ClassVar`); keep
      `__dataclass_fields__` as the `except`-branch fallback.
   b. Update `injected_cols` logic to use `{"created_timestamp", "last_updated_timestamp"}` for
      ops tables and `{"ingested_at", "trade_date"}` for telemetry tables.
   c. Change `severity` property to return `VerifierSeverity.WARN`.
   Create tests in `tests/test_verifiers/test_schema_integrity.py`.

6. **Add `s3:DeleteObject` to `terraform/ec2_runner.tf`** -- In the `S3ReadWrite` statement, extend
   the `Action` array from `["s3:GetObject", "s3:PutObject"]` to
   `["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]`.

7. **Close rec-602 via ops_data_portal** -- Run:
   `python -m scripts.ops_data_portal --update-rec rec-602 --status closed --execution_result already_implemented`

8. **Execute Verification Plan** -- run VP steps 1-6 (pre-deploy).

9. **Run `terraform plan`** (VP step 7) -- present output to user. Do not apply until human confirms.

10. **Run `terraform apply`** (VP step 8, human-approved) -- then run VP step 9 (full local validate).

11. **Report**: what was implemented, VP results, rec-602 closure confirmation.
