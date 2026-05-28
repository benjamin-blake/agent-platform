"""LLM-based risk classification for recommendations."""

import json
import logging
import subprocess
from pathlib import Path

from scripts.llm_client import llm_call
from scripts.s3_log_store import get_backend, read_jsonl

logger = logging.getLogger(__name__)


RISK_CRITERIA = """
Classify the risk level of this recommendation:
{recommendation_title}

Context: {recommendation_context}

Evaluate:
- Low: Safe changes, minimal side effects, well-tested area
- Medium: Some complexity, potential regressions, moderate scope
- High: High complexity, risky refactoring, critical systems, eval/exec risks

Respond with only: LOW|MEDIUM|HIGH
"""


def classify_risk(rec_id: str, title: str, context: str = "") -> str:
    """
    Classify recommendation risk as low/medium/high via LLM.
    Returns: 'low' | 'medium' | 'high' | 'unclassified'
    """
    prompt = RISK_CRITERIA.format(recommendation_title=title, recommendation_context=context or "No additional context")
    try:
        result = llm_call(
            prompt,
            timeout=60,
            tools=False,
            context_file_path=f"logs/debug/classify-risk-{rec_id}.txt",
            inline_instruction="Classify the risk level. Respond with only: LOW|MEDIUM|HIGH",
            check=False,
        )
        if result.exit_code != 0:
            logger.warning(f"Classification failed for {rec_id}: exit code {result.exit_code}")
            return "unclassified"
        risk = result.content.strip().upper()
        if risk in ["LOW", "MEDIUM", "HIGH"]:
            return risk.lower()
        logger.warning(f"Unexpected classification output for {rec_id}: {risk}")
        return "unclassified"
    except subprocess.TimeoutExpired:
        logger.error(f"Classification timeout for {rec_id}")
        return "unclassified"
    except Exception as e:
        logger.error(f"Classification error for {rec_id}: {e}")
        return "unclassified"


def classify_all_unclassified() -> int:
    """Classify all unclassified recommendations. Returns count of classified."""
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    recs_file = Path("logs/.recommendations-log.jsonl")
    if get_backend() == "s3":
        entries = read_jsonl(".recommendations-log.jsonl")
    else:
        # Local mode: read from recs_file (relative path, test-isolation via chdir)
        if not recs_file.exists():
            return 0
        entries = []
        for line in recs_file.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not entries:
        return 0
    updated_count = 0

    for entry in entries:
        if entry.get("risk") == "unclassified":
            rec_id = entry.get("id")
            if not rec_id:
                continue
            risk = classify_risk(rec_id, entry.get("title", ""), entry.get("context", ""))
            update_rec(rec_id, {"risk": risk})
            updated_count += 1

    return updated_count


def main():
    """CLI entry point."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: python scripts/classify_risk.py [--classify-all]")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--classify-all":
        count = classify_all_unclassified()
        print(f"Classified {count} recommendations")
    else:
        print("No action. Use --classify-all to classify recommendations.")


if __name__ == "__main__":
    main()
