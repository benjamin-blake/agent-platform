"""Check-accounting declaration ratchet (Decision 170, rec-2915's structural-prevention half;
docs/contracts/check-accounting.yaml).

AST-scans every registered check's defining module for an examined()/skipped() declaration
(scripts.checks.registry's accounting API -- see that module's docstring). A check absent from
config/check_accounting_baseline.yaml that declares nothing FAILS. The baseline is a ONE-TIME,
shrink-only grandfather roster with NO marker escape grammar (Decision 165) -- membership can
only shrink, is bounded by this module's own frozen `_BASELINE_SEED` constant so a config-file
edit alone can never admit a new member, and carries a touch-it-fix-it obligation: editing a
baselined check's module without adopting the declaration in the same PR FAILS.

Filesystem-only and IN-PROCESS (Decision 153 fast-tier budget) except for two bounded git reads
the shrink-only comparison structurally requires: `_marker_guard.default_base_reader` (a single
`git show origin/main:<path>`, carrying the missing-base SKIP that baseline copies) and
`_common.get_changed_files()` for the touch-it-fix-it changed-file set. No subprocess fan-out,
no pytest spawn.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import yaml

from scripts.checks import _common, _marker_guard, registry

_BASELINE_REL_PATH = "config/check_accounting_baseline.yaml"
_CONTRACT_REL_PATH = "docs/contracts/check-accounting.yaml"

# The ratchet's frozen seed -- the 96 registered checks not yet adopting the declaration
# obligation when this file landed (101 registered minus the 5 adopted in the same tranche).
# Growing this set requires editing this constant in a reviewed code change; a
# config/check_accounting_baseline.yaml edit alone can never admit a name absent from here
# (Decision 162 r3 / _R1_KNOWN_VIOLATORS precedent: scripts/checks/ci_guards/
# validate_composite_action_shell_bodies.py's frozen no-marker-escape ceiling).
_BASELINE_SEED: frozenset[str] = frozenset(
    {
        "check_source_registry",
        "validate_acceptance_literals",
        "validate_actions_evidence",
        "validate_authority_budget",
        "validate_boundary_attached",
        "validate_broker_env_reads",
        "validate_candidate_decision_ratification",
        "validate_candidate_decision_supersession",
        "validate_cc_limits",
        "validate_check_manifests",
        "validate_ci_rca_adjudication",
        "validate_ci_rca_taxonomy",
        "validate_ci_rca_trigger",
        "validate_ci_refresh_read_coverage",
        "validate_ci_workflow_guards",
        "validate_claude_md_pointer_invariant",
        "validate_claude_p_retry_wrapper",
        "validate_cli_tools_in_prompts",
        "validate_complexity",
        "validate_composite_action_manifests",
        "validate_composite_action_shell_bodies",
        "validate_contract_drift",
        "validate_convergence_writer_isolation",
        "validate_coverage_baseline_edits",
        "validate_data_model_standard",
        "validate_decision_currency",
        "validate_decision_entry_conformance",
        "validate_decisions_index_freshness",
        "validate_decisions_local_writes",
        "validate_decisions_size",
        "validate_dependency_graph_freshness",
        "validate_deploy_channel_conformance",
        "validate_differential_gate_baseline",
        "validate_dq_manifest_gate",
        "validate_ducklake_version_lockstep",
        "validate_executor_boundary",
        "validate_fallback_reevaluation",
        "validate_field_semantics_drift",
        "validate_ghas_probe",
        "validate_graduation_completeness",
        "validate_handoff_full_tier",
        "validate_hermeticity_flags",
        "validate_iam_policy_size",
        "validate_iam_runner_policy",
        "validate_import_contracts",
        "validate_instruction_architecture_layers",
        "validate_intent_doc_freeze",
        "validate_invariants",
        "validate_invoke_implies_resolve",
        "validate_lambda_bundle_completeness",
        "validate_lambda_manifest_coverage",
        "validate_lambda_manifests",
        "validate_lockfile_sync",
        "validate_masked_errexit_steps",
        "validate_mypy_baseline_edits",
        "validate_mypy_ratchet",
        "validate_no_cross_test_imports",
        "validate_no_underscore_instructions",
        "validate_ops_portal_patch_targets",
        "validate_outbox_staleness",
        "validate_placement",
        "validate_plan_documents",
        "validate_plan_scope_closure",
        "validate_platform_roadmap",
        "validate_portal_drift",
        "validate_pr_conflict_signal",
        "validate_product_roadmap",
        "validate_prompt_compliance",
        "validate_prompt_files",
        "validate_prose_allowlist",
        "validate_prose_budget_raises",
        "validate_prose_limits",
        "validate_pydantic_yaml_drift",
        "validate_rec_relevance_contract",
        "validate_rec_write_paths",
        "validate_recommendations_schema",
        "validate_reconcile_pending_gate",
        "validate_requirements",
        "validate_reversal_stanzas",
        "validate_sloc_budget_raises",
        "validate_sloc_limits",
        "validate_structural_size_budget_raises",
        "validate_structural_size_limits",
        "validate_subprocess_encoding",
        "validate_supersession_annotations",
        "validate_sys_executable",
        "validate_terraform_try",
        "validate_test_count_coupling",
        "validate_tier_floor",
        "validate_verification_harness",
        "validate_verification_registry",
        "validate_verifier_hermeticity",
        "validate_verifier_same_pr_guard",
        "validate_vp_replay",
        "validate_warehouse_write_sources",
        "validate_workflow_agent_safety",
    }
)

_DECLARING_ATTRS = frozenset({"examined", "skipped"})


def _module_declares(source: str) -> bool:
    """True iff `source`'s AST contains any call to `.examined(...)`/`.skipped(...)` (an
    attribute call, the registry.examined()/registry.skipped() call shape) or a bare
    `examined(...)`/`skipped(...)` name call (a `from ... import examined, skipped` shape).
    Module-level: proves a declaration EXISTS somewhere in the module, not that every reachable
    exit path reaches one (see docs/contracts/check-accounting.yaml's ratchet_limitation)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _DECLARING_ATTRS:
            return True
        if isinstance(func, ast.Name) and func.id in _DECLARING_ATTRS:
            return True
    return False


def _load_baseline_entries(text: str) -> list[str]:
    data = yaml.safe_load(text) or {}
    entries = data.get("entries") or []
    return [str(e) for e in entries]


def _check_module_rel_path(name: str) -> str | None:
    """Repo-relative posix path of `name`'s defining module, via registry.resolve() + inspect --
    the sanctioned public API (never reaching into registry._ALL_ENTRIES directly)."""
    try:
        fn = registry.resolve(name)
        source_file = inspect.getsourcefile(fn)
    except (registry.UnknownCheckError, TypeError, OSError):
        return None
    if source_file is None:
        return None
    try:
        return Path(source_file).resolve().relative_to(_common.ROOT).as_posix()
    except ValueError:
        return None


@registry.register("validate_check_accounting", owner="platform")
def validate_check_accounting(failed: list[str]) -> None:
    print(f"\n=== Check-accounting declaration ratchet ({_CONTRACT_REL_PATH}) ===")
    violations: list[str] = []

    contract_path = _common.ROOT / _CONTRACT_REL_PATH
    try:
        contract_data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Check-accounting ratchet: {_CONTRACT_REL_PATH}: {exc}")
        return
    declared_vocabulary = set(contract_data.get("status_vocabulary") or []) if isinstance(contract_data, dict) else set()
    if declared_vocabulary != registry.STATUS_VOCABULARY:
        violations.append(
            f"scripts.checks.registry.STATUS_VOCABULARY != {_CONTRACT_REL_PATH}'s status_vocabulary "
            f"(symmetric difference: {sorted(declared_vocabulary ^ registry.STATUS_VOCABULARY)})."
        )

    checks = registry.all_checks()
    module_rel_paths = {name: _check_module_rel_path(name) for name in checks}
    declares_by_module: dict[str, bool] = {}
    for rel_path in set(filter(None, module_rel_paths.values())):
        source = (_common.ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
        declares_by_module[rel_path] = _module_declares(source)

    def _declares(name: str) -> bool:
        rel_path = module_rel_paths.get(name)
        return rel_path is not None and declares_by_module.get(rel_path, False)

    baseline_path = _common.ROOT / _BASELINE_REL_PATH
    current_baseline_text = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
    current_baseline = set(_load_baseline_entries(current_baseline_text))

    # (a) every registered check not baselined must declare.
    for name in sorted(checks):
        if name in current_baseline:
            continue
        if not _declares(name):
            violations.append(
                f"{name}: declares no examined()/skipped() outcome and is not in {_BASELINE_REL_PATH} "
                "-- every new registered check must adopt the accounting declaration on introduction."
            )

    # (b) frozen-constant cross-check: a config-edit-alone growth is never admitted.
    unrecognized = current_baseline - _BASELINE_SEED
    if unrecognized:
        violations.append(
            f"{_BASELINE_REL_PATH} carries {sorted(unrecognized)}, which is NOT in this guard's frozen "
            "_BASELINE_SEED constant -- the baseline is shrink-only with no config-edit-alone admission "
            "path; growing it requires editing _BASELINE_SEED in a reviewed code change."
        )

    # (c) shrink-only diff against the committed base -- SKIP loudly on a missing base.
    base_text = _marker_guard.default_base_reader(_BASELINE_REL_PATH)
    if base_text is None:
        print(f"  SKIP: {_BASELINE_REL_PATH} unreachable at origin/main (advisory locally, seeding-safe in CI).")
    else:
        base_baseline = set(_load_baseline_entries(base_text))
        grown = current_baseline - base_baseline
        if grown:
            violations.append(
                f"{_BASELINE_REL_PATH} grew by {sorted(grown)} relative to origin/main -- the baseline is "
                "shrink-only (no marker escape, Decision 165); an entry may be removed, never (re-)added."
            )

    # (d) touch-it-fix-it: an edited baselined check that has not adopted the declaration fails.
    changed_files = set(_common.get_changed_files())
    for name in sorted(current_baseline & set(checks)):
        check_rel_path = module_rel_paths.get(name)
        if check_rel_path is not None and check_rel_path in changed_files and not _declares(name):
            violations.append(
                f"{name}: {check_rel_path} was edited on this branch but still declares no "
                "examined()/skipped() outcome (touch-it-fix-it) -- adopt the declaration in this "
                "PR, or leave the module unedited."
            )

    registry.examined(len(checks), unit="registered_checks")
    if violations:
        print("Check-accounting ratchet violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Check-accounting declaration ratchet")
    else:
        print(f"  PASS: {len(checks)} registered check(s) scanned; {len(current_baseline)} baselined.")
