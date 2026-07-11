"""Ordered per-tier check registry (Decision 104).

``register()`` tags a validate_*/check_* function with its owner metadata.
``pre_sequence()`` / ``full_sequence()`` declare the ordered list of steps
(registered check names interleaved with the fixed non-check scaffolding
steps: lint, precommit, mypy, explicit pytest, unit-test invoke_step,
dependency/coverage/terraform gates, budget assertion) for each presubmit
tier. Adding a check touches only this package, never scripts/validate.py:
add the check's module under scripts/checks/<domain>/, decorate it with
``@register(...)``, and insert its name at the right position in the
sequence(s) below.

Tier dispatch (scripts/validate.py) iterates these sequences; each "check"
step is resolved via ``getattr(validate_module, name)(failed)`` at call time
so mock patches on the ``validate`` namespace still intercept, and each
"scaffold" step is resolved against a dict of closures built locally in
main() (they close over per-run locals like the diff-aware changed-files
list that a generic registry cannot own).
"""

from __future__ import annotations

import dataclasses

_VALID_OWNERS = ("platform", "trading")


@dataclasses.dataclass(frozen=True)
class Check:
    name: str
    owner: str = "platform"
    product_coupled: bool = False

    def __post_init__(self) -> None:
        if self.owner not in _VALID_OWNERS:
            raise ValueError(f"Check {self.name!r}: owner must be one of {_VALID_OWNERS}, got {self.owner!r}")


_REGISTRY: dict[str, Check] = {}


def register(name: str, owner: str = "platform", product_coupled: bool = False):
    """Decorator registering a validate_*/check_* function under `name`.

    `name` is the getattr-resolution key on the `validate` module (normally
    identical to the decorated function's own __name__) and the facade
    re-export key in scripts/validate.py.
    """

    def _decorate(fn):
        _REGISTRY[name] = Check(name=name, owner=owner, product_coupled=product_coupled)
        return fn

    return _decorate


def get_check(name: str) -> Check:
    return _REGISTRY[name]


def all_checks() -> dict[str, Check]:
    return dict(_REGISTRY)


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str  # "check" | "scaffold"
    name: str


def _c(name: str) -> Step:
    return Step(kind="check", name=name)


def _s(name: str) -> Step:
    return Step(kind="scaffold", name=name)


def pre_sequence() -> list[Step]:
    """The --pre (fast) tier, in the exact order main() runs them."""
    return [
        _s("lint"),
        _s("precommit_changed"),
        _s("mypy_diff"),
        _s("pytest_diff"),
        _c("validate_iam_runner_policy"),
        _c("validate_prompt_files"),
        _c("validate_cli_tools_in_prompts"),
        _c("validate_workflow_agent_safety"),
        _c("validate_product_roadmap"),
        _c("validate_plan_documents"),
        _c("validate_tier_floor"),
        _c("validate_candidate_decision_ratification"),
        _c("validate_cc_limits"),
        _c("validate_sloc_limits"),
        _c("validate_subprocess_encoding"),
        _c("validate_test_count_coupling"),
        _c("validate_intent_doc_freeze"),
        _c("validate_contract_drift"),
        _c("validate_placement"),
        _c("validate_field_semantics_drift"),
        _c("validate_deploy_channel_conformance"),
        _c("validate_ci_rca_taxonomy"),
        _c("validate_ops_portal_patch_targets"),
        _c("validate_claude_p_retry_wrapper"),
        _c("validate_authority_budget"),
        _c("validate_invoke_implies_resolve"),
        _c("validate_ci_workflow_guards"),
        _c("validate_ducklake_version_lockstep"),
        _c("validate_import_contracts"),
        _c("validate_lockfile_sync"),
        _c("validate_verifier_same_pr_guard"),
        _c("validate_verification_registry"),
        _c("validate_vp_replay"),
        _s("coverage_report"),
        _s("budget_assertion"),
    ]


def full_sequence() -> list[Step]:
    """The full (default, no-flag) tier, in the exact order main() runs them.

    Spans the whole main() default-scope body: run_python_checks, the
    terraform block, validate_iam_runner_policy, run_dependency_checks +
    validate_requirements, the prompts block, ensure_fresh_dq_results,
    validate_verification_harness, and the all-files precommit run.
    validate_cli_tools_in_prompts legitimately appears twice (once inside
    run_python_checks, once in the prompts block) -- existing behaviour,
    preserved verbatim.
    """
    return [
        # run_python_checks()
        _s("lint"),
        _c("validate_subprocess_encoding"),
        _c("validate_test_count_coupling"),
        _c("validate_sys_executable"),
        _c("validate_cli_tools_in_prompts"),
        _c("validate_imports"),
        _c("validate_recommendations_schema"),
        _c("validate_outbox_staleness"),
        _c("validate_executor_boundary"),
        _c("validate_rec_write_paths"),
        _c("validate_decisions_local_writes"),
        _c("validate_warehouse_write_sources"),
        _c("validate_broker_env_reads"),
        _c("validate_invariants"),
        _c("validate_ci_rca_trigger"),
        _c("validate_ci_workflow_guards"),
        _c("validate_claude_p_retry_wrapper"),
        _c("validate_sloc_limits"),
        _c("check_source_registry"),
        _c("validate_platform_roadmap"),
        _c("validate_candidate_decision_ratification"),
        _c("validate_lambda_manifests"),
        _c("validate_lambda_manifest_coverage"),
        _c("validate_lambda_bundle_completeness"),
        _c("validate_lambda_deploy_gating"),
        _c("validate_product_roadmap"),
        _c("validate_plan_documents"),
        _c("validate_tier_floor"),
        _c("validate_pydantic_yaml_drift"),
        _c("_check_graduation_guard"),
        _c("validate_dq_manifest_gate"),
        _c("validate_test_coverage"),
        _c("validate_no_underscore_instructions"),
        _c("validate_claude_md_pointer_invariant"),
        _c("validate_environment_taxonomy"),
        _c("validate_complexity"),
        _c("validate_scheduled_agent_logs"),
        _c("validate_ghas_probe"),
        _c("validate_hermeticity_flags"),
        _c("validate_verifier_hermeticity"),
        _c("validate_verifier_same_pr_guard"),
        _c("validate_verification_registry"),
        _c("validate_differential_gate_baseline"),
        _c("validate_intent_doc_freeze"),
        _c("validate_contract_drift"),
        _c("validate_placement"),
        _c("validate_portal_drift"),
        _c("validate_rec_relevance_contract"),
        _c("validate_field_semantics_drift"),
        _c("validate_ci_rca_taxonomy"),
        _c("validate_ops_portal_patch_targets"),
        _c("validate_authority_budget"),
        _c("validate_invoke_implies_resolve"),
        _c("validate_ducklake_version_lockstep"),
        _c("validate_import_contracts"),
        _c("validate_lockfile_sync"),
        _c("validate_dependency_graph_freshness"),
        _s("unit_tests"),
        _s("mypy_full"),
        # run_terraform_checks() -- a single bundled call site (validate_terraform_try +
        # run_terraform_creds_free + the informational drift check); it is also called and
        # tested directly as one unit (tests/test_validate.py::TestRunTerraformChecks), so it
        # is modelled as one scaffold step rather than split into its 3 constituent actions.
        _s("terraform_checks"),
        _c("validate_iam_runner_policy"),
        # run_dependency_checks() + validate_requirements
        _s("dependency_health"),
        _c("validate_requirements"),
        # prompts block
        _c("validate_prompt_files"),
        _c("validate_cli_tools_in_prompts"),
        _c("validate_workflow_agent_safety"),
        _c("validate_prompt_compliance"),
        _c("validate_instruction_architecture_layers"),
        # tail
        _s("ensure_fresh_dq"),
        _c("validate_verification_harness"),
        _s("precommit_all_files"),
    ]
