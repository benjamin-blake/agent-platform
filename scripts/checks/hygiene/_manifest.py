"""Entry literals for the hygiene domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_subprocess_encoding",
        module="scripts.checks.hygiene.validate_subprocess_encoding",
        attr="validate_subprocess_encoding",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_test_count_coupling",
        module="scripts.checks.hygiene.validate_test_count_coupling",
        attr="validate_test_count_coupling",
        pre=True,
        pre_globs=("tests/**",),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_no_cross_test_imports",
        module="scripts.checks.hygiene.validate_no_cross_test_imports",
        attr="validate_no_cross_test_imports",
        pre=True,
        pre_globs=("tests/**",),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_sys_executable",
        module="scripts.checks.hygiene.validate_sys_executable",
        attr="validate_sys_executable",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_cli_tools_in_prompts",
        module="scripts.checks.hygiene.validate_cli_tools_in_prompts",
        attr="validate_cli_tools_in_prompts",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_prose_allowlist",
        module="scripts.checks.hygiene.validate_prose_allowlist",
        attr="validate_prose_allowlist",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_placement",
        module="scripts.checks.hygiene.validate_placement",
        attr="validate_placement",
        pre=True,
        full_segment="full_after_lint",
    ),
)
