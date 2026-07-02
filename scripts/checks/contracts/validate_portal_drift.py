"""Portal-artefact drift gate (ULF-11): promotes the PLAN-t2-11b-portal-artefacts probes.

Checks that the curated public-repo portal (EVALUATION-PROMPTS.yaml, README.md, SECURITY.md)
stays honest: every answer-locus path resolves, each portal file still carries its projection
header, and no ops-table token leaks into the curated evaluator index (Decision 101 / CD.20 /
CD.23 public-content boundary).
"""

from __future__ import annotations

from scripts.checks import _common, registry

_PORTAL_FILES = ("README.md", "SECURITY.md", "EVALUATION-PROMPTS.yaml")
_HEADER_SCAN_LINES = 6
_OPS_TABLE_TOKENS = (
    "ops_recommendations",
    "ops_decisions",
    "ops_session_log",
    "ops_execution_plans",
    "ops_priority_queue",
    "telemetry",
)


@registry.register("validate_portal_drift", owner="platform")
def validate_portal_drift(failed: list[str]) -> None:
    """Gate on portal drift: answer-loci, projection headers, and the ops-table token ban."""
    print("\n=== Portal drift gate (ULF-11) ===")

    try:
        import yaml
    except Exception as exc:  # noqa: BLE001 -- never raise at check time (rec-2027 pattern)
        failed.append(f"Portal drift: yaml import failed: {exc}")
        return

    prompts_path = _common.ROOT / "EVALUATION-PROMPTS.yaml"
    if not prompts_path.is_file():
        failed.append("Portal drift: EVALUATION-PROMPTS.yaml is missing")
        return

    try:
        text = prompts_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Portal drift: EVALUATION-PROMPTS.yaml failed to parse: {exc}")
        return

    for question in data.get("questions", []) or []:
        qid = question.get("id", "<unknown>")
        for locus in question.get("answer_loci", []) or []:
            locus_path = str(locus).split("#")[0].strip()
            if not locus_path:
                continue
            if not (_common.ROOT / locus_path).exists():
                failed.append(f"Portal drift: {qid} answer-locus does not resolve: {locus_path!r}")

    for filename in _PORTAL_FILES:
        file_path = _common.ROOT / filename
        if not file_path.is_file():
            failed.append(f"Portal drift: portal file missing: {filename}")
            continue
        if filename == "EVALUATION-PROMPTS.yaml":
            first_line = next((line for line in text.splitlines() if line.strip()), "")
            if not first_line.strip().startswith("projection:"):
                failed.append(f"Portal drift: {filename} is missing its top-level `projection:` header")
        else:
            header_lines = file_path.read_text(encoding="utf-8").splitlines()[:_HEADER_SCAN_LINES]
            if not any("projection of" in line.lower() for line in header_lines):
                failed.append(
                    f"Portal drift: {filename} is missing a 'projection of' line in its first {_HEADER_SCAN_LINES} lines"
                )

    lower_text = text.lower()
    for token in _OPS_TABLE_TOKENS:
        if token in lower_text:
            failed.append(f"Portal drift: ops-table token {token!r} appears in EVALUATION-PROMPTS.yaml")
