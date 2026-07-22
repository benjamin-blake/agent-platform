"""Taxonomy loader and failure classifier for CI-RCA evidence bundles.

Loads config/ci_rca_taxonomy.yaml and classifies CI failures by function name (primary)
and log-pattern regex (fallback). Also resolves workflow names to tier values and
enumerates workflow names from .github/workflows/*.yml.

Used by: scripts/ci_rca/evidence.py, scripts/validate.py (validate_ci_rca_taxonomy).
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
_TAXONOMY_PATH = ROOT / "config" / "ci_rca_taxonomy.yaml"
_TAXONOMY_CACHE: dict | None = None


def load_taxonomy(path: Path | None = None) -> dict:
    """Load the taxonomy YAML. Raises FileNotFoundError or ValueError on failure.

    Defers all validation to explicit call (no raise at import time).
    """
    import yaml

    p = Path(path) if path is not None else _TAXONOMY_PATH
    if not p.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed taxonomy YAML at {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Taxonomy at {p} must be a mapping, got {type(data).__name__}")
    required = {"function_to_category", "log_pattern_to_category", "workflow_to_tier"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Taxonomy missing required keys: {sorted(missing)}")
    return data


def _cached_taxonomy(path: Path | None = None) -> dict:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None or path is not None:
        _TAXONOMY_CACHE = load_taxonomy(path)
    return _TAXONOMY_CACHE


_FAILED_CHECKS_HEADER = "Failed checks:"


def _parse_failed_checks_block(log_text: str) -> list[str]:
    """Parse the named check(s) out of validate.py's authoritative "Failed checks:" summary
    block (see scripts/validate.py's `Failed checks:\\n  - <name>` emission). Returns the
    checks in the order they appear; an empty list if no such block is present.

    Independent re-implementation of the same block scripts.executor.run_summary's
    _extract_validation_failed_checks parses -- kept separate on purpose: a ci_rca ->
    executor import would cross the executor self-modification boundary.
    """
    checks: list[str] = []
    in_block = False
    for raw_line in log_text.splitlines():
        stripped = raw_line.strip()
        if stripped == _FAILED_CHECKS_HEADER:
            in_block = True
            continue
        if not in_block:
            continue
        if stripped.startswith("- "):
            checks.append(stripped[2:].strip())
            continue
        if checks and (not stripped or stripped.startswith("Fix all failures") or stripped.startswith("===")):
            break
    return checks


def _classify_via_failed_checks_block(log_text: str, func_map: dict[str, str]) -> tuple[str, str, str] | None:
    """Priority-3 helper: resolve the first "Failed checks:" block entry that maps through
    function_to_category. Returns None if the block is absent or none of its entries map."""
    matches = _classify_all_via_failed_checks_block(log_text, func_map)
    return matches[0] if matches else None


def _classify_all_via_failed_checks_block(log_text: str, func_map: dict[str, str]) -> list[tuple[str, str, str]]:
    """Enumeration counterpart of `_classify_via_failed_checks_block`: every "Failed checks:"
    block entry that maps through function_to_category, deduplicated, in block order."""
    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for check_name in _parse_failed_checks_block(log_text):
        if check_name not in seen and check_name in func_map:
            results.append((func_map[check_name], check_name, "validate_failed_checks_block"))
            seen.add(check_name)
    return results


def classify_failure(
    log_text: str,
    jobs: list[dict] | None = None,
    path: Path | None = None,
) -> tuple[str, str, str]:
    """Classify a CI failure. Returns (failure_category, failed_check, classification_source).

    Priority: (1) step_name_to_category on failed steps from jobs JSON,
              (2) function_to_category on failed step names from jobs JSON,
              (3) function_to_category on the authoritative "Failed checks:" summary block
                  (validate.py's own list of checks that actually FAILED),
              (4) function_to_category on log text (whole-log substring scan),
              (5) log_pattern_to_category regex fallback,
              (6) taxonomy_fallback (unknown).
    """
    taxonomy = _cached_taxonomy(path)
    func_map: dict[str, str] = taxonomy.get("function_to_category") or {}
    step_map: dict[str, str] = taxonomy.get("step_name_to_category") or {}
    pattern_list: list[dict] = taxonomy.get("log_pattern_to_category") or []

    # Priority 1: jobs JSON failed step name -> step_name_to_category
    if jobs:
        for job in jobs:
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    step_name = step.get("name", "")
                    if step_name in step_map:
                        return (step_map[step_name], step_name, "step_name_to_category")

    # Priority 2: jobs JSON failed step name -> function_to_category (direct key match)
    if jobs:
        for job in jobs:
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    step_name = step.get("name", "")
                    if step_name in func_map:
                        return (func_map[step_name], step_name, "function_to_category")

    # Priority 3: authoritative "Failed checks:" summary block -> function_to_category. Takes
    # priority over the whole-log substring scan below so a validate.py aggregate failure is
    # categorized by the check that actually FAILED, not by an arbitrary first-substring-hit
    # against a validate_* name that merely appears in a passing check's output.
    block_result = _classify_via_failed_checks_block(log_text, func_map)
    if block_result is not None:
        return block_result

    # Priority 4: function_to_category substring scan on log text
    for func_name, category in func_map.items():
        if func_name in log_text:
            return (category, func_name, "function_to_category")

    # Priority 5: log pattern regex fallback
    for entry in pattern_list:
        pat = entry.get("pattern", "")
        category = entry.get("category", "unknown")
        check_name = entry.get("check_name", "unknown")
        try:
            if re.search(pat, log_text, re.MULTILINE):
                return (category, check_name, "log_pattern_to_category")
        except re.error:
            logger.warning("Invalid taxonomy regex: %r", pat)

    return ("unknown", "unknown", "taxonomy_fallback")


def classify_failures(
    log_text: str,
    jobs: list[dict] | None = None,
    path: Path | None = None,
) -> list[tuple[str, str, str]]:
    """Enumerate all distinct failed checks. jobs-JSON step names take priority over log text.

    Genuinely-distinct failures are enumerated from two AUTHORITATIVE sources only: (1)
    jobs-JSON failed step names (each failed step is a real, independently-reported GitHub
    Actions failure), and (2) validate.py's own "Failed checks:" summary block (each named
    entry is a check validate.py itself determined FAILED). Enumeration never falls back to a
    whole-log function_to_category substring scan -- do NOT enumerate every substring hit
    across the whole log. The fetched log is the FULL job log (gh run view --log-failed), which
    routinely mentions many unrelated validate_* function names from checks that ran and passed
    earlier in the same job; treating each substring hit as a distinct failure caused a
    spurious multi-category bundle fan-out that defeated the fingerprint dedup guard (2026-07
    incident: one real failure fanned into 6 bundles, one of which was a novel fingerprint that
    tripped the then-all-or-nothing guard). When neither authoritative source yields a match,
    fall back to a SINGLE classify_failure() call over the log text (which itself may still
    resolve via the "Failed checks:" block, or lower-priority fallbacks).
    """
    taxonomy = _cached_taxonomy(path)
    func_map: dict[str, str] = taxonomy.get("function_to_category") or {}
    step_map: dict[str, str] = taxonomy.get("step_name_to_category") or {}

    results: list[tuple[str, str, str]] = []
    seen_checks: set[str] = set()

    # Priority 1+2: jobs JSON failed step names -- the only reliable multi-failure enumeration.
    if jobs:
        for job in jobs:
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    step_name = step.get("name", "")
                    if step_name not in seen_checks:
                        if step_name in step_map:
                            results.append((step_map[step_name], step_name, "step_name_to_category"))
                            seen_checks.add(step_name)
                        elif step_name in func_map:
                            results.append((func_map[step_name], step_name, "function_to_category"))
                            seen_checks.add(step_name)

    # Priority 3: authoritative "Failed checks:" summary block -- each named entry is a genuine,
    # independently-reported validate.py failure, so (unlike the banned whole-log substring
    # scan) enumerating every entry here does not reintroduce the fan-out bug.
    if not results:
        results.extend(_classify_all_via_failed_checks_block(log_text, func_map))

    # Fallback: neither authoritative source classified anything -- single priority-ordered
    # classification over the log text (same logic classify_failure() already uses for the
    # singular case).
    if not results:
        results.append(classify_failure(log_text, jobs, path))

    return results


def resolve_workflow_tier(workflow_name: str, path: Path | None = None) -> str:
    """Map a workflow name to its tier string. Returns 'unknown' for misses and 'not_a_gate' sentinels."""
    taxonomy = _cached_taxonomy(path)
    tier_map: dict[str, str] = taxonomy.get("workflow_to_tier") or {}
    tier = tier_map.get(workflow_name)
    if tier is None:
        logger.warning("workflow_to_tier miss: %r not in taxonomy", workflow_name)
        return "unknown"
    if tier == "not_a_gate":
        return "unknown"
    return tier


def enumerate_workflow_names(workflows_dir: Path | None = None) -> list[str]:
    """Return sorted list of 'name:' values from .github/workflows/*.yml files."""
    import yaml

    wdir = workflows_dir if workflows_dir is not None else (ROOT / ".github" / "workflows")
    names = []
    for wf_path in sorted(Path(wdir).glob("*.yml")):
        try:
            with wf_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "name" in data:
                names.append(str(data["name"]))
        except Exception:
            logger.warning("Could not extract name from %s", wf_path)
    return names
