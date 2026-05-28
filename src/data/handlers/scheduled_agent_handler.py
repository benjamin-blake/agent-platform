"""Lambda handler: Scheduled agent dispatcher.

Reads schedule.yaml, determines which agents are due, invokes each agent
via the configured inference provider, and writes findings to S3.

Environment variables
---------------------
GITHUB_PAT_SECRET_ARN : ARN of the Secrets Manager secret containing the
    GitHub PAT. Used by ``copilot-sdk`` and ``github-models`` providers.
BEDROCK_CREDENTIALS_SECRET_ARN : ARN of the Secrets Manager secret containing
    cross-account Bedrock credentials (JSON with ``aws_access_key_id`` and
    ``aws_secret_access_key``). Falls back to ``GITHUB_PAT_SECRET_ARN`` if unset.
S3_LOG_BUCKET          : S3 bucket name for writing agent findings
    (e.g. ``agent-platform-data-lake``).
SCHEDULED_AGENT_MODEL  : Optional model override.

Providers
---------
- ``bedrock``: AWS Bedrock Converse API (active); uses DeepSeek V3.2 in eu-west-2.
- ``copilot-sdk``: GitHub Copilot SDK (dormant); uses PAT from Secrets Manager.
- ``github-models``: GitHub Models API (local/legacy; not for Lambda).

Lambda trigger
--------------
Invoked by EventBridge (CloudWatch Events). The handler checks which
agents are due at the current UTC time and runs them sequentially.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# In Lambda the package root is /var/task; locally it's the repo root.
_HANDLER_DIR = Path(__file__).parent
_REPO_ROOT = _HANDLER_DIR.parent.parent.parent  # src/data/handlers -> repo root


def _get_github_pat() -> str:
    """Retrieve the GitHub PAT from Secrets Manager or environment.

    Returns the PAT string, or an empty string if retrieval fails.
    """
    pat_env = os.environ.get("GITHUB_PAT", "").strip()
    if pat_env:
        return pat_env

    secret_arn = os.environ.get("GITHUB_PAT_SECRET_ARN", "").strip()
    if not secret_arn:
        logger.error("GITHUB_PAT_SECRET_ARN not set and GITHUB_PAT not set")
        return ""

    try:
        import boto3

        client = boto3.client("secretsmanager", region_name="eu-west-2")
        response = client.get_secret_value(SecretId=secret_arn)
        return response.get("SecretString", "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to retrieve GitHub PAT from Secrets Manager: %s", exc)
        return ""


def _get_bedrock_credentials() -> dict[str, str] | None:
    """Retrieve Bedrock credentials from Secrets Manager for cross-account auth.

    The secret (stored in the work account) contains a JSON object with
    ``aws_access_key_id`` and ``aws_secret_access_key`` for the personal
    Bedrock account (REDACTED-PERSONAL-ACCOUNT).

    Returns dict with credential keys, or None on any failure.
    """
    secret_arn = os.environ.get(
        "BEDROCK_CREDENTIALS_SECRET_ARN",
        os.environ.get("GITHUB_PAT_SECRET_ARN", ""),
    ).strip()
    if not secret_arn:
        return None

    try:
        import boto3

        client = boto3.client("secretsmanager", region_name="eu-west-2")
        response = client.get_secret_value(SecretId=secret_arn)
        secret_str = response.get("SecretString", "").strip()
        creds = json.loads(secret_str)
        if "aws_access_key_id" in creds and "aws_secret_access_key" in creds:
            return creds
        logger.warning("Secrets Manager secret missing Bedrock credential keys")
        return None
    except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
        logger.error("Failed to retrieve Bedrock credentials from Secrets Manager: %s", exc)
        return None


def _get_gemini_api_key() -> str:
    """Retrieve the Gemini API key from Secrets Manager or environment.

    Returns the key string, or an empty string if retrieval fails.
    """
    key_env = os.environ.get("GEMINI_API_KEY", "").strip()
    if key_env:
        return key_env

    secret_arn = os.environ.get("GEMINI_API_KEY_SECRET_ARN", "").strip()
    if not secret_arn:
        logger.error("GEMINI_API_KEY_SECRET_ARN not set and GEMINI_API_KEY not set")
        return ""

    try:
        import boto3

        client = boto3.client("secretsmanager", region_name="eu-west-2")
        response = client.get_secret_value(SecretId=secret_arn)
        return response.get("SecretString", "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to retrieve Gemini API key from Secrets Manager: %s", exc)
        return ""


def _load_prompt(prompt_path: str) -> str:
    """Read a prompt file, checking repo root then /var/task."""
    candidates = [
        _REPO_ROOT / prompt_path,
        Path("/var/task") / prompt_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    logger.error("Prompt file not found: %s", prompt_path)
    return ""


def _load_manifest() -> list[dict[str, Any]]:
    """Load the agent schedule manifest from repo root or /var/task."""
    from scripts.run_scheduled_agent import load_manifest

    candidates = [
        _REPO_ROOT / ".github" / "agents" / "schedule.yaml",
        Path("/var/task") / ".github" / "agents" / "schedule.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return load_manifest(candidate)
    logger.error("schedule.yaml not found")
    return []


def _invoke_bedrock(prompt_text: str, model: str, max_tokens: int = 4096) -> tuple[str, bool, str]:
    """Invoke Bedrock converse API with cross-account credentials.

    Returns (output, error, message).
    """
    from scripts.bedrock_client import converse

    credentials = _get_bedrock_credentials()
    response = converse(
        prompt=prompt_text,
        model_id=model,
        region="eu-west-2",
        max_tokens=max_tokens,
        credentials=credentials,
    )
    if response.get("error"):
        return "", True, response.get("message", "")
    return response.get("content", ""), False, ""


def _invoke_copilot_sdk(prompt_text: str, model: str, pat: str, max_tokens: int = 4096) -> tuple[str, bool, str]:
    """Invoke Copilot SDK. Returns (output, error, message)."""
    from scripts.copilot_sdk_client import copilot_sdk_inference_sync

    response = copilot_sdk_inference_sync(
        prompt=prompt_text,
        model=model,
        github_token=pat,
        max_tokens=max_tokens,
    )
    if response.get("error"):
        return "", True, response.get("message", "")
    return response.get("content", ""), False, ""


_GEMINI_BYOK_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _invoke_gemini(prompt_text: str, model: str, pat: str) -> tuple[str, bool, str]:
    """Invoke Gemini via Copilot SDK BYOK. Returns (output, error, message).

    Reads the Gemini API key from ``GEMINI_API_KEY`` env var (local) or
    ``GEMINI_API_KEY_SECRET_ARN`` Secrets Manager secret (Lambda).  The GitHub
    PAT (``pat``) is still required by the Copilot CLI binary for startup auth
    even when inference is routed to Gemini.

    Uses a 600s timeout (vs. the 300s default) to accommodate large prompts
    such as orphan-code and transcript-review that require extended analysis.
    """
    from scripts.copilot_sdk_client import copilot_sdk_inference_sync

    gemini_key = _get_gemini_api_key()
    if not gemini_key:
        return "", True, "Gemini API key not available"

    provider_config: dict[str, str] = {
        "type": "openai",
        "base_url": _GEMINI_BYOK_ENDPOINT,
        "api_key": gemini_key,
    }
    response = copilot_sdk_inference_sync(
        prompt=prompt_text,
        model=model,
        github_token=pat,
        provider_config=provider_config,
        timeout=600.0,
    )
    if response.get("error"):
        return "", True, response.get("message", "")
    return response.get("content", ""), False, ""


def _query_athena_to_json(query: str) -> list[dict]:
    """Execute an Athena query and return results as a list of dicts.

    Uses the ``agent-platform-production`` workgroup (engine v3).
    Polls until the query completes or fails.  Returns an empty list on
    any error so the caller can fall back gracefully.
    """
    import time

    import boto3

    athena = boto3.client("athena", region_name="eu-west-2")
    workgroup = "agent-platform-production"

    try:
        start = athena.start_query_execution(
            QueryString=query,
            WorkGroup=workgroup,
        )
        qid = start["QueryExecutionId"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Athena start_query_execution failed: %s", exc)
        return []

    # Poll for completion (max ~120 s)
    for _ in range(60):
        status = athena.get_query_execution(QueryExecutionId=qid)
        state = status["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED",):
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            logger.warning("Athena query %s: %s -- %s", state, qid, reason)
            return []
        time.sleep(2)
    else:
        logger.warning("Athena query timed out: %s", qid)
        return []

    # Paginate results
    rows: list[dict] = []
    paginator = athena.get_paginator("get_query_results")
    header: list[str] = []
    for page in paginator.paginate(QueryExecutionId=qid):
        columns = page["ResultSet"].get("ResultSetMetadata", {}).get("ColumnInfo", [])
        if not header and columns:
            header = [c["Name"] for c in columns]
        for i, row in enumerate(page["ResultSet"]["Rows"]):
            vals = [d.get("VarCharValue", "") for d in row["Data"]]
            # First row of first page is the header
            if not rows and i == 0 and vals == header:
                continue
            rows.append(dict(zip(header, vals)))
    return rows


def _preload_rec_curator_context(prompt_text: str) -> str:
    """Inject recommendation and retro data into the rec-curator prompt.

    Reads open recommendations from the ``ops_recommendations_current``
    Athena view (Decision 50 -- Iceberg is the authoritative store).
    Falls back to S3 JSONL if the Athena query fails.

    Retro entries are still read from S3 (no Iceberg table for retro data).

    Files/views injected:
      - ops_recommendations_current view  (Athena, open recs only)
      - logs/.retro-lite-log.jsonl        (S3 or local via s3_log_store)
      - docs/ROADMAP-PRODUCT.md           (product phases -- Lambda filesystem at /var/task or repo root)
      - docs/ROADMAP-PLATFORM.yaml        (platform tier items -- Lambda filesystem at /var/task or repo root)
    """
    from scripts.s3_log_store import read_jsonl

    # Primary path: query Athena ops_recommendations_current view.
    open_recs = _query_athena_to_json("SELECT * FROM trading_formulas_db.ops_recommendations_current WHERE status = 'open'")
    if open_recs:
        logger.info(
            "rec-curator context: %d open recs from Athena view",
            len(open_recs),
        )
    else:
        # Fallback: read from S3 JSONL (pre-backfill or Athena unavailable).
        logger.warning("Athena view returned 0 open recs; falling back to S3 JSONL")
        recs = read_jsonl(".recommendations-log.jsonl")
        open_recs = [r for r in recs if isinstance(r, dict) and r.get("status") == "open"]
        logger.info(
            "rec-curator context: %d open recs from S3 fallback (of %d total)",
            len(open_recs),
            len(recs),
        )

    retro = read_jsonl(".retro-lite-log.jsonl")
    logger.info("rec-curator context: %d retro entries", len(retro))

    def _read_roadmap(filename: str) -> str:
        for candidate in [Path(f"/var/task/docs/{filename}"), _REPO_ROOT / "docs" / filename]:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        logger.warning("%s not found; rec-curator will run without it", filename)
        return f"({filename} not available)"

    roadmap_product_text = _read_roadmap("ROADMAP-PRODUCT.md")
    roadmap_platform_text = _read_roadmap("ROADMAP-PLATFORM.yaml")

    recs_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in open_recs) or "(empty)"
    retro_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in retro) or "(empty)"

    preamble = (
        "## Data Pre-loaded by Lambda Handler\n\n"
        "The following data has been loaded for you. "
        "Do NOT issue any bash commands to read files -- use this data directly.\n\n"
        "### Open Recommendations (from ops_recommendations_current Athena view)\n"
        "```\n"
        f"{recs_text}\n"
        "```\n\n"
        "### logs/.retro-lite-log.jsonl\n"
        "```\n"
        f"{retro_text}\n"
        "```\n\n"
        "### docs/ROADMAP-PRODUCT.md (product phases)\n"
        "```\n"
        f"{roadmap_product_text}\n"
        "```\n\n"
        "### docs/ROADMAP-PLATFORM.yaml (platform tier items)\n"
        "```\n"
        f"{roadmap_platform_text}\n"
        "```\n\n"
        "---\n\n"
    )

    return preamble + prompt_text


def _invoke_github_models(prompt_text: str, model: str, pat: str) -> tuple[str, bool, str]:
    """Invoke GitHub Models API. Returns (output, error, message)."""
    from scripts.github_models_client import chat_completion

    response = chat_completion(prompt=prompt_text, model=model, api_key=pat)
    if response.get("error"):
        return "", True, response.get("message", "")
    try:
        output = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        return "", True, f"Response missing content: {exc}"
    return output, False, ""


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point.

    Runs all agents due at the current UTC time and writes their findings
    to S3 using the convention ``agents/{name}/{timestamp}.jsonl``.

    Routes inference by the agent's ``provider`` field:
    - ``bedrock``: uses Bedrock Converse API with DeepSeek V3.2 (active; eu-west-2)
    - ``copilot-sdk``: uses GitHub Copilot SDK (dormant; retained for rollback)
    - ``github-models``: uses GitHub Models API (local/legacy)

    Args:
        event: EventBridge event payload (unused but required by Lambda).
        context: Lambda context object (unused).

    Returns:
        Summary dict with keys: ``agents_run``, ``agents_failed``,
        ``total_findings``, ``keys_written``.
    """
    if os.environ.get("SCHEDULED_AGENTS_ENABLED", "false").lower() != "true":
        logger.info("Scheduled agents are disabled (SCHEDULED_AGENTS_ENABLED not set to 'true')")
        return {"status": "disabled", "message": "Scheduled agents dispatcher is disabled"}

    from scripts.run_scheduled_agent import is_agent_due, parse_findings
    from scripts.s3_log_store import write_timestamped_findings

    now = datetime.now(timezone.utc)
    logger.info("Dispatcher invoked at %s UTC", now.isoformat())

    agents = _load_manifest()
    model_override = os.environ.get("SCHEDULED_AGENT_MODEL", "")

    # Allow forcing a specific agent via event payload (for testing / manual runs).
    # EventBridge payloads won't include this field; only manual invocations will.
    force_agent: str = event.get("force_agent", "").strip()
    if force_agent:
        due_agents = [a for a in agents if a["name"] == force_agent]
        logger.info("Force-running agent '%s' (bypassing cron check)", force_agent)
    else:
        due_agents = [a for a in agents if is_agent_due(a, now)]
        logger.info("%d agent(s) due at %s", len(due_agents), now.strftime("%H:%M UTC"))

    # Resolve PAT lazily and cache lookup result for github-models agents.
    pat: str = ""
    pat_checked = False

    agents_run = 0
    agents_failed = 0
    total_findings = 0
    keys_written: list[str] = []

    for agent in due_agents:
        name: str = agent["name"]

        if not agent.get("enabled", True):
            logger.info("Agent '%s' is disabled, skipping", name)
            continue

        model: str = model_override or agent.get("model", "gpt-4.1-mini")
        prompt_path: str = agent.get("prompt_path", "")
        provider: str = agent.get("provider", "github-models")

        logger.info(
            "Running agent '%s' with model=%s provider=%s",
            name,
            model,
            provider,
        )

        from src.data.handlers.agent_telemetry import (
            close_invocation as _close_invocation,
        )
        from src.data.handlers.agent_telemetry import (
            open_invocation as _open_invocation,
        )
        from src.data.handlers.agent_telemetry import (
            record_model_call as _record_model_call,
        )

        trigger = "manual" if force_agent else "eventbridge"
        _open_invocation(agent_name=name, trigger=trigger, model=model, provider=provider)

        prompt_text = _load_prompt(prompt_path)
        if not prompt_text:
            logger.error(
                "Skipping agent '%s': prompt not found at %s",
                name,
                prompt_path,
            )
            agents_failed += 1
            _close_invocation(outcome="failed", error="prompt not found")
            continue

        # rec-curator requires its S3 input files injected inline because
        # the Lambda environment cannot execute bash tool calls.
        if name == "rec-curator" and provider in ("bedrock", "copilot-sdk", "gemini"):
            prompt_text = _preload_rec_curator_context(prompt_text)

        import time as _time

        if provider == "bedrock":
            # rec-curator produces a large JSON array; increase output budget.
            max_tokens = 8192 if name == "rec-curator" else 4096
            _t0 = _time.monotonic()
            output, has_error, err_msg = _invoke_bedrock(prompt_text, model, max_tokens=max_tokens)
            _call_dur = int(_time.monotonic() - _t0)
            _record_model_call(
                provider=provider,
                model=model,
                purpose="findings",
                error=err_msg if has_error else None,
                duration_seconds=_call_dur,
            )
        elif provider == "copilot-sdk":
            if not pat_checked:
                pat = _get_github_pat()
                pat_checked = True
            if not pat:
                logger.error("Skipping agent '%s': GitHub PAT not available", name)
                agents_failed += 1
                _close_invocation(outcome="failed", error="PAT not available")
                continue
            max_tokens = 8192 if name == "rec-curator" else 4096
            _t0 = _time.monotonic()
            output, has_error, err_msg = _invoke_copilot_sdk(prompt_text, model, pat, max_tokens=max_tokens)
            _call_dur = int(_time.monotonic() - _t0)
            _record_model_call(
                provider=provider,
                model=model,
                purpose="findings",
                error=err_msg if has_error else None,
                duration_seconds=_call_dur,
            )
        elif provider == "gemini":
            if not pat_checked:
                pat = _get_github_pat()
                pat_checked = True
            if not pat:
                logger.error("Skipping agent '%s': GitHub PAT not available", name)
                agents_failed += 1
                _close_invocation(outcome="failed", error="PAT not available")
                continue
            _t0 = _time.monotonic()
            output, has_error, err_msg = _invoke_gemini(prompt_text, model, pat)
            _call_dur = int(_time.monotonic() - _t0)
            _record_model_call(
                provider=provider,
                model=model,
                purpose="findings",
                error=err_msg if has_error else None,
                duration_seconds=_call_dur,
            )
        else:
            if not pat_checked:
                pat = _get_github_pat()
                pat_checked = True
            if not pat:
                logger.error(
                    "Skipping agent '%s': GitHub PAT not available",
                    name,
                )
                agents_failed += 1
                _close_invocation(outcome="failed", error="PAT not available")
                continue
            _t0 = _time.monotonic()
            output, has_error, err_msg = _invoke_github_models(prompt_text, model, pat)
            _call_dur = int(_time.monotonic() - _t0)
            _record_model_call(
                provider=provider,
                model=model,
                purpose="findings",
                error=err_msg if has_error else None,
                duration_seconds=_call_dur,
            )

        if has_error:
            logger.error("Agent '%s' API call failed: %s", name, err_msg)
            agents_failed += 1
            _close_invocation(
                outcome="failed",
                error=err_msg,
                lambda_request_id=getattr(context, "aws_request_id", None),
            )
            continue

        findings = parse_findings(output)
        for finding in findings:
            finding.setdefault("agent", name)
            finding.setdefault("timestamp", now.isoformat())

        key = write_timestamped_findings(name, findings)
        if key:
            keys_written.append(key)
            total_findings += len(findings)
            agents_run += 1
            logger.info(
                "Agent '%s': %d findings written to %s",
                name,
                len(findings),
                key,
            )
            _close_invocation(
                outcome="success",
                findings_count=len(findings),
                lambda_request_id=getattr(context, "aws_request_id", None),
            )
        else:
            logger.error("Agent '%s': failed to write findings to S3", name)
            agents_failed += 1
            _close_invocation(
                outcome="failed",
                findings_count=len(findings),
                error="S3 write failed",
                lambda_request_id=getattr(context, "aws_request_id", None),
            )

    summary = {
        "agents_run": agents_run,
        "agents_failed": agents_failed,
        "total_findings": total_findings,
        "keys_written": keys_written,
    }
    logger.info("Dispatcher complete: %s", json.dumps(summary))
    return summary
