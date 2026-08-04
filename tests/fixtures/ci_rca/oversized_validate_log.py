"""Synthetic oversized full-tier `validate.py` failure log (real-scale, generator only).

Deliberately a GENERATOR, not a committed multi-MB log file: `build_log()` synthesises one from
real structural elements (a `validate.py --pre`-style banner, PASS lines for real check names,
pytest-style test-node PASSED lines) at call time, exceeding both
`scripts.ci_rca.log_evidence.DEFAULT_MAX_BYTES` and `DEFAULT_MAX_LINES`, and terminating in the
real "Failed checks:\\n  - Coverage below 100%" block captured from CI run 30768605340 -- the
canary run whose true cause this plan exists to surface. Lives in tests/fixtures/ because that
package is exempt from the no-cross-test-import guard by construction.
"""

from __future__ import annotations

_REAL_CHECK_NAMES = (
    "validate_sloc_limits",
    "validate_cc_limits",
    "validate_prose_limits",
    "validate_placement",
    "validate_contract_drift",
    "validate_data_model_standard",
    "validate_field_semantics_drift",
    "validate_reversal_stanzas",
    "validate_ci_rca_taxonomy",
    "validate_ci_workflow_guards",
    "validate_actions_evidence",
    "validate_invariants",
)


def build_log(*, node_count: int = 8000) -> str:
    """Synthesise an oversized full-tier `validate.py` failure log.

    node_count controls the pytest-node PASSED block size -- the default comfortably exceeds
    both DEFAULT_MAX_BYTES (256 KiB) and DEFAULT_MAX_LINES (4000 lines) so every window
    assertion against this fixture is non-vacuous.
    """
    lines: list[str] = ["Pre mode: diff-aware lint/format/mypy/pytest and prompt validation.\n"]
    for name in _REAL_CHECK_NAMES:
        lines.append(f"\n=== {name} ===\n")
        lines.append(f"  PASS: {name} completed with no findings\n")
    lines.append("\n=== Unit tests + coverage ===\n")
    for i in range(node_count):
        lines.append(f"tests/some/test_module_{i}.py::test_case_{i} PASSED [{i % 100:>3}%]\n")
    lines.append("\n=== Validation Summary (scope: all) ===\n")
    lines.append("Failed checks:\n")
    lines.append("  - Coverage below 100%\n")
    return "".join(lines)
