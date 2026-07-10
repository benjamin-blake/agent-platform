"""Recommendation risk/automatable derivation (rec-001 / rec-742 dual-maintenance-drift fix).

Owner-concern: turning (file, effort, coverage, complexity) into a risk tier and an
automatable boolean via a single shared derivation path, called from file_rec() (kept
in the facade) so no caller can independently drift the formula.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import yaml

from scripts.ops_portal._common import ROOT

logger = logging.getLogger(__name__)

_EFFORT_SCALE: dict[str, float] = {"XS": 0.1, "S": 0.5, "M": 1.0, "L": 3.0, "XL": 5.0}
_COVERAGE_XML = ROOT / "coverage.xml"
_CAPABILITIES_YAML = ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
_capabilities_cache: Optional[dict] = None


def _compute_risk_score(file_path: str, effort: str) -> float:
    """Return raw R = (C * S) / M for the given file and effort label.

    C = max cyclomatic complexity (1.0 fallback), S = effort scale, M = coverage + 0.1 baseline.
    """
    c = 1.0
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "radon", "cc", "-s", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            nums = [int(m) for m in re.findall(r"\((\d+)\)", proc.stdout)]
            if nums:
                c = float(max(nums))
    except Exception:  # noqa: BLE001
        pass

    s = _EFFORT_SCALE.get(effort, 1.0)

    m = 0.1
    try:
        tree = ET.parse(str(_COVERAGE_XML))
        norm_target = file_path.replace("\\", "/")
        for cls in tree.getroot().iter("class"):
            name = (cls.get("filename") or "").replace("\\", "/")
            if name.endswith(norm_target) or norm_target.endswith(name):
                m = float(cls.get("line-rate", 0.0)) + 0.1
                break
    except Exception:  # noqa: BLE001
        pass

    return (c * s) / m


def compute_risk(file_path: str, effort: str) -> str:
    """Derive risk tier from cyclomatic complexity, effort scale, and test coverage.

    R = (C * S) / M where:
      C = max cyclomatic complexity of target file (1.0 if file missing or radon returns empty)
      S = effort scale factor from _EFFORT_SCALE (1.0 fallback for unknown labels)
      M = line-rate from coverage.xml for the file + 0.1 baseline (0.1 if absent)
    Thresholds: R <= 5 -> "low", R <= 15 -> "medium", R > 15 -> "high"
    """
    r = _compute_risk_score(file_path, effort)
    if r <= 5:
        return "low"
    if r <= 15:
        return "medium"
    return "high"


def load_capabilities() -> dict:
    """Load and cache executor_capabilities.yaml. Returns empty dict on read failure."""
    global _capabilities_cache
    if _capabilities_cache is None:
        try:
            _capabilities_cache = yaml.safe_load(_CAPABILITIES_YAML.read_text(encoding="utf-8")) or {}
        except (FileNotFoundError, OSError, yaml.YAMLError):
            _capabilities_cache = {}
    return _capabilities_cache


def compute_automatable(file_path: str, effort: str) -> bool:
    """Return True iff this recommendation is within the executor's current capability boundary.

    Formula: NOT in boundary AND R <= maturity_ceiling.
    Offline fallback: returns True when file_path is empty (boundary unknown).
    """
    if not file_path:
        return True
    caps = load_capabilities()
    boundary_patterns: list[str] = caps.get("boundary_patterns", [])
    ceiling: float = float(caps.get("maturity_ceiling", 1.0))
    if any(pat in file_path for pat in boundary_patterns):
        return False
    r = _compute_risk_score(file_path, effort)
    return r <= ceiling


def _derive_computed_fields(fields: dict) -> None:
    """Derive and set risk, automatable, and created_timestamp in-place.

    Called from file_rec() to ensure a single shared
    derivation path -- prevents the dual-maintenance drift that produced rec-001
    (automatable=NULL) and rec-742 (created_timestamp midnight fallback).
    """
    if fields.get("file") and fields.get("effort"):
        derived_risk = compute_risk(fields["file"], fields["effort"])
        if fields.get("risk") and fields["risk"] != derived_risk:
            logger.warning(
                "[PORTAL] caller risk %s overridden by formula %s for %s",
                fields["risk"],
                derived_risk,
                fields.get("title", ""),
            )
        fields["risk"] = derived_risk

        derived_automatable = compute_automatable(fields["file"], fields["effort"])
        if "automatable" in fields and fields["automatable"] != derived_automatable:
            logger.warning(
                "[PORTAL] caller automatable %s overridden by formula %s for %s",
                fields["automatable"],
                derived_automatable,
                fields.get("title", ""),
            )
        fields["automatable"] = derived_automatable

    fields.setdefault("created_timestamp", datetime.now(timezone.utc).isoformat())
