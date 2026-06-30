"""Taxonomy loader and failure classifier for CI-RCA evidence bundles.

Loads config/ci_rca_taxonomy.yaml and classifies CI failures by function name (primary)
and log-pattern regex (fallback). Also resolves workflow names to tier values and
enumerates workflow names from .github/workflows/*.yml.

Used by: scripts/ci_rca_evidence.py, scripts/validate.py (validate_ci_rca_taxonomy).
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
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


def classify_failure(
    log_text: str,
    jobs: list[dict] | None = None,
    path: Path | None = None,
) -> tuple[str, str, str]:
    """Classify a CI failure. Returns (failure_category, failed_check, classification_source).

    Priority: (1) step_name_to_category on failed steps from jobs JSON,
              (2) function_to_category on failed step names from jobs JSON,
              (3) function_to_category on log text (substring scan),
              (4) log_pattern_to_category regex fallback,
              (5) taxonomy_fallback (unknown).
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

    # Priority 3: function_to_category substring scan on log text
    for func_name, category in func_map.items():
        if func_name in log_text:
            return (category, func_name, "function_to_category")

    # Priority 4: log pattern regex fallback
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
    """Enumerate all distinct failed checks. jobs-JSON step names take priority over log text."""
    taxonomy = _cached_taxonomy(path)
    func_map: dict[str, str] = taxonomy.get("function_to_category") or {}
    step_map: dict[str, str] = taxonomy.get("step_name_to_category") or {}

    results: list[tuple[str, str, str]] = []
    seen_checks: set[str] = set()

    # Priority 1+2: jobs JSON failed step names
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

    # Priority 3: function_to_category on log text (only if jobs didn't already cover)
    for func_name, category in func_map.items():
        if func_name in log_text and func_name not in seen_checks:
            results.append((category, func_name, "function_to_category"))
            seen_checks.add(func_name)

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
