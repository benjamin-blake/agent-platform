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

    Priority: function_to_category (primary, first match on function name in log text)
    -> log_pattern_to_category (regex fallback) -> taxonomy_fallback (unknown).
    """
    taxonomy = _cached_taxonomy(path)
    func_map: dict[str, str] = taxonomy.get("function_to_category") or {}
    pattern_list: list[dict] = taxonomy.get("log_pattern_to_category") or []

    for func_name, category in func_map.items():
        if func_name in log_text:
            return (category, func_name, "function_to_category")

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
