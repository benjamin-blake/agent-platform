"""Lambda handler: Findings processor.

Triggered by S3 ObjectCreated events on the ``agents/`` prefix. Unions all
agent findings into ``findings/unified.jsonl``, then compares against existing
recommendations and appends new ones to ``recommendations/agent-recommendations.jsonl``.

Environment variables
---------------------
GITHUB_PAT_SECRET_ARN : ARN of the Secrets Manager secret containing the
    GitHub PAT used to call the GitHub Models API for comparison.
GITHUB_PAT             : Alternatively, the PAT can be set directly as an
    env var (for local testing).
S3_LOG_BUCKET          : S3 bucket name (e.g. ``bblake-platform-agent-logs``).

S3 key layout
-------------
agents/{name}/{timestamp}.jsonl   ← raw per-agent findings (input)
findings/unified.jsonl            ← union of all findings (Step 1 output)
recommendations/agent-recommendations.jsonl  ← agent-generated recs (Step 2 output)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_HANDLER_DIR = Path(__file__).parent
_REPO_ROOT = _HANDLER_DIR.parent.parent.parent

_UNIFIED_KEY = "findings/unified.jsonl"
_AGENT_RECS_KEY = "recommendations/agent-recommendations.jsonl"

# Comparison prompt file path (relative to repo root / /var/task)
_COMPARE_PROMPT_PATH = ".github/prompts/scheduled/findings-compare.prompt.md"


def _get_github_pat() -> str:
    """Retrieve the GitHub PAT from Secrets Manager or environment."""
    pat_env = os.environ.get("GITHUB_PAT", "").strip()
    if pat_env:
        return pat_env

    secret_arn = os.environ.get("GITHUB_PAT_SECRET_ARN", "").strip()
    if not secret_arn:
        logger.warning("GITHUB_PAT_SECRET_ARN not set; skipping agent comparison step")
        return ""

    try:
        import boto3

        client = boto3.client("secretsmanager", region_name="eu-west-2")
        response = client.get_secret_value(SecretId=secret_arn)
        return response.get("SecretString", "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to retrieve GitHub PAT from Secrets Manager: %s", exc)
        return ""


def _load_compare_prompt() -> str:
    """Load the findings-compare.prompt.md template."""
    candidates = [
        _REPO_ROOT / _COMPARE_PROMPT_PATH,
        Path("/var/task") / _COMPARE_PROMPT_PATH,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    logger.error("Compare prompt not found: %s", _COMPARE_PROMPT_PATH)
    return ""


def _next_agent_rec_id(existing_recs: list[dict]) -> str:
    """Compute the next ID in the agent-NNN namespace.

    Args:
        existing_recs: Current list of agent recommendation dicts.

    Returns:
        Next ID string, e.g. ``"agent-001"``.
    """
    max_n = 0
    for rec in existing_recs:
        rec_id: str = rec.get("id", "")
        if rec_id.startswith("agent-"):
            try:
                n = int(rec_id[6:])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"agent-{max_n + 1:03d}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point triggered by S3 ObjectCreated events.

    Step 1 (deterministic): Union all ``agents/*/...`` findings into
    ``findings/unified.jsonl``.

    Step 2 (agent comparison): Use GitHub Models API to compare unified
    findings against existing recommendations, appending new ones.

    Args:
        event: S3 event payload (used to detect triggering bucket/key).
        context: Lambda context object (unused).

    Returns:
        Summary dict with ``unified_count``, ``new_rec_count``,
        ``duplicate_count``.
    """
    from scripts.github_models_client import chat_completion
    from scripts.s3_log_store import append_jsonl, overwrite_jsonl, read_all_agent_findings, read_jsonl
    from src.data.handlers.agent_telemetry import (
        close_invocation as _close_invocation,
    )
    from src.data.handlers.agent_telemetry import (
        open_invocation as _open_invocation,
    )
    from src.data.handlers.agent_telemetry import (
        record_model_call as _record_model_call,
    )

    model = os.environ.get("SCHEDULED_AGENT_MODEL", "gpt-4.1-mini")
    _open_invocation(
        agent_name="findings-processor",
        trigger="s3_event",
        model=model,
        provider="github-models",
    )

    # ----------------------------------------------------------------
    # Step 1: Union all agent findings into findings/unified.jsonl
    # ----------------------------------------------------------------
    all_findings = read_all_agent_findings()
    logger.info("Step 1: read %d total findings from agents/*", len(all_findings))

    # ----------------------------------------------------------------
    # Priority queue routing: extract priority-queue-entry findings
    # and write them to S3 via overwrite_jsonl before the comparison
    # step so they are not treated as standard recommendations.
    # ----------------------------------------------------------------
    _PRIORITY_QUEUE_KEY = "priority-queue/.priority-queue.jsonl"
    queue_entries = [f for f in all_findings if f.get("type") == "priority-queue-entry"]
    all_findings = [f for f in all_findings if f.get("type") != "priority-queue-entry"]
    if queue_entries:
        overwrite_jsonl(_PRIORITY_QUEUE_KEY, queue_entries)
        logger.info("Wrote %d priority queue entries to S3", len(queue_entries))
    else:
        logger.info("No priority queue entries found")

    # Write unified findings (overwrite existing unified.jsonl)
    # We use append_jsonl for each entry rather than a bulk write,
    # consistent with the existing pattern. Clear first by writing empty.
    bucket = os.environ.get("S3_LOG_BUCKET", "").strip()
    if bucket:
        try:
            import boto3

            s3 = boto3.client("s3", region_name="eu-west-2")
            body = "\n".join(json.dumps(f, ensure_ascii=False) for f in all_findings)
            if all_findings:
                body += "\n"
            s3.put_object(Bucket=bucket, Key=_UNIFIED_KEY, Body=body.encode("utf-8"))
            logger.info("Wrote unified findings to s3://%s/%s", bucket, _UNIFIED_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write unified.jsonl: %s", exc)
    else:
        # Local mode: write to logs/findings/unified.jsonl
        from scripts.s3_log_store import _LOGS_DIR

        unified_path = _LOGS_DIR / _UNIFIED_KEY
        unified_path.parent.mkdir(parents=True, exist_ok=True)
        with open(unified_path, "w", encoding="utf-8") as fh:
            for finding in all_findings:
                fh.write(json.dumps(finding, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------------
    # Step 2: Agent comparison — only if PAT is available
    # ----------------------------------------------------------------
    pat = _get_github_pat()
    if not pat:
        logger.warning("No PAT available; skipping recommendation comparison")
        _close_invocation(
            outcome="success",
            findings_count=len(all_findings),
            queue_entries_written=len(queue_entries),
        )
        return {
            "unified_count": len(all_findings),
            "new_rec_count": 0,
            "duplicate_count": 0,
            "queue_entries_written": len(queue_entries),
            "skipped_comparison": True,
        }

    compare_prompt_template = _load_compare_prompt()
    if not compare_prompt_template:
        logger.error("Compare prompt template missing; skipping comparison")
        _close_invocation(
            outcome="success",
            findings_count=len(all_findings),
            queue_entries_written=len(queue_entries),
        )
        return {
            "unified_count": len(all_findings),
            "new_rec_count": 0,
            "duplicate_count": 0,
            "queue_entries_written": len(queue_entries),
            "skipped_comparison": True,
        }

    existing_agent_recs = read_jsonl(_AGENT_RECS_KEY)

    # Build comparison prompt
    model = os.environ.get("SCHEDULED_AGENT_MODEL", "gpt-4.1-mini")
    prompt = (
        f"{compare_prompt_template}\n\n"
        f"## Input\n\n"
        f"### unified_findings\n```json\n{json.dumps(all_findings, indent=2)}\n```\n\n"
        f"### existing_recommendations\n```json\n{json.dumps(existing_agent_recs, indent=2)}\n```\n"
    )

    import time as _time

    _t0 = _time.monotonic()
    response = chat_completion(prompt=prompt, model=model, api_key=pat)
    _call_dur = int(_time.monotonic() - _t0)
    _record_model_call(
        provider="github-models",
        model=model,
        purpose="comparison",
        error=response.get("message") if response.get("error") else None,
        duration_seconds=_call_dur,
    )
    if response.get("error"):
        logger.error("Comparison API call failed: %s", response.get("message"))
        _close_invocation(
            outcome="failed",
            findings_count=len(all_findings),
            queue_entries_written=len(queue_entries),
            error=response.get("message"),
        )
        return {
            "unified_count": len(all_findings),
            "new_rec_count": 0,
            "duplicate_count": 0,
            "queue_entries_written": len(queue_entries),
            "error": response.get("message"),
        }

    output = ""
    try:
        output = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("Comparison response missing content: %s", exc)
        _close_invocation(
            outcome="failed",
            findings_count=len(all_findings),
            queue_entries_written=len(queue_entries),
            error=str(exc),
        )
        return {
            "unified_count": len(all_findings),
            "new_rec_count": 0,
            "duplicate_count": 0,
            "error": str(exc),
        }

    # Parse comparison result
    try:
        comparison = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        # Strip markdown fences if present
        clean = output.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            clean = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        try:
            comparison = json.loads(clean)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Could not parse comparison JSON: %s", exc)
            _close_invocation(
                outcome="failed",
                findings_count=len(all_findings),
                queue_entries_written=len(queue_entries),
                error="Malformed comparison response",
            )
            return {
                "unified_count": len(all_findings),
                "new_rec_count": 0,
                "duplicate_count": 0,
                "queue_entries_written": len(queue_entries),
                "error": "Malformed comparison response",
            }

    duplicate_ids: list[str] = comparison.get("duplicate_ids", [])
    new_recs_raw: list[dict] = comparison.get("new_recommendations", [])

    today = date.today().isoformat()
    appended = 0
    for rec_data in new_recs_raw:
        next_id = _next_agent_rec_id(existing_agent_recs)
        rec = {
            "id": next_id,
            "date": today,
            "status": "open",
            "source": "agent-cron",
            **rec_data,
        }
        # DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)
        try:
            from scripts.executor.jsonl_store import Recommendation as _Recommendation  # noqa: PLC0415

            _Recommendation.model_validate(rec)
        except Exception as exc:  # noqa: BLE001
            logger.warning("findings_processor: rec %s failed Recommendation validation, skipping: %s", next_id, exc)
            continue
        existing_agent_recs.append(rec)
        append_jsonl(_AGENT_RECS_KEY, rec)
        appended += 1
        logger.info("Appended new recommendation %s: %s", next_id, rec.get("title"))

    logger.info(
        "Step 2 complete: %d new recs, %d duplicates skipped",
        appended,
        len(duplicate_ids),
    )
    _close_invocation(
        outcome="success",
        findings_count=len(all_findings),
        recs_created=appended,
        queue_entries_written=len(queue_entries),
    )
    return {
        "unified_count": len(all_findings),
        "new_rec_count": appended,
        "duplicate_count": len(duplicate_ids),
        "queue_entries_written": len(queue_entries),
    }
