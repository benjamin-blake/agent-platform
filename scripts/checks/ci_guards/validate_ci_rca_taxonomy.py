"""CI-RCA taxonomy coverage check (Decision 60)."""

from __future__ import annotations

from scripts.checks import registry


@registry.register("validate_ci_rca_taxonomy", owner="platform")
def validate_ci_rca_taxonomy(failed: list[str]) -> None:
    """Fail if any .github/workflows/*.yml workflow name is absent from the workflows map.

    Pure file-glob + YAML parse (sub-100ms); --pre eligible (Decision 60).
    """
    print("\n=== CI-RCA taxonomy coverage (workflows map) ===")
    from scripts.ci_rca.taxonomy import enumerate_workflow_names, load_taxonomy  # noqa: PLC0415

    try:
        taxonomy = load_taxonomy()
    except (FileNotFoundError, ValueError) as exc:
        failed.append(f"CI-RCA taxonomy coverage: {exc}")
        return

    workflows_map: dict[str, dict] = taxonomy.get("workflows") or {}
    actual_names = enumerate_workflow_names()
    missing = [n for n in actual_names if n not in workflows_map]
    if missing:
        for n in missing:
            failed.append(f"CI-RCA taxonomy: workflow {n!r} absent from workflows in config/ci_rca_taxonomy.yaml")
        return
    print(f"All {len(actual_names)} workflow name(s) present in workflows.")

    # Check 1b: every REGISTERED check resolves to a category in function_to_category -- a
    # PRECONDITION of the Priority-0 attribution path (scripts.ci_rca.taxonomy.classify_failure/
    # classify_failures resolve an attributed check's failure_category through
    # func_map[check_name]), not standalone hygiene. Same shape as the workflows coverage
    # assertion above.
    func_map: dict[str, str] = taxonomy.get("function_to_category") or {}
    registered_checks = sorted(registry.all_checks())
    unmapped_checks = [c for c in registered_checks if c not in func_map]
    if unmapped_checks:
        for c in unmapped_checks:
            failed.append(
                f"CI-RCA taxonomy: registered check {c!r} absent from function_to_category in "
                f"config/ci_rca_taxonomy.yaml (Priority-0 attribution precondition)"
            )
        return
    print(f"All {len(registered_checks)} registered check(s) present in function_to_category.")

    # Check 2: failure_categories list matches classifier's actual category set
    failure_categories = taxonomy.get("failure_categories")
    if failure_categories is None:
        failed.append("CI-RCA taxonomy: missing top-level 'failure_categories:' list in config/ci_rca_taxonomy.yaml")
        return
    declared = set(failure_categories)

    # Collect categories used in function_to_category and step_name_to_category
    func_map = taxonomy.get("function_to_category") or {}
    step_map = taxonomy.get("step_name_to_category") or {}
    used_cats = set(func_map.values()) | set(step_map.values())
    # Also include code-emitted sentinels which classify_failure can return without a map entry:
    # "unknown" (taxonomy_fallback) and "evidence_insufficient" (the refusal verdict, emitted at
    # the classify_failure/classify_failures call sites, never via a func_map/step_map entry).
    used_cats.add("unknown")
    used_cats.add("evidence_insufficient")

    # Add categories from log_pattern_to_category
    for entry in taxonomy.get("log_pattern_to_category") or []:
        cat = entry.get("category")
        if cat:
            used_cats.add(cat)

    missing_from_yaml = used_cats - declared
    if missing_from_yaml:
        for cat in sorted(missing_from_yaml):
            failed.append(
                f"CI-RCA taxonomy: category {cat!r} used in taxonomy maps but absent from "
                f"failure_categories list in config/ci_rca_taxonomy.yaml"
            )
        return

    # Check reverse: every declared category must appear in a classifier map or in agent_only_categories
    agent_only = set(taxonomy.get("agent_only_categories") or [])
    unclassifiable = declared - used_cats - agent_only
    if unclassifiable:
        for cat in sorted(unclassifiable):
            failed.append(
                f"CI-RCA taxonomy: category {cat!r} declared in failure_categories but absent from "
                f"all classifier maps and agent_only_categories in config/ci_rca_taxonomy.yaml "
                f"(Decision 60: no dead enum branches)"
            )
        return
    print(f"failure_categories list has {len(declared)} entries; all used categories declared.")
