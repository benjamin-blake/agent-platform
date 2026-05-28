#!/usr/bin/env python3
"""Post-completion telemetry CLI for Claude Code scheduled agents.

Reads a `claude -p --output-format json` output file and a findings JSONL file,
then emits one telemetry_agent_invocations row and one telemetry_model_calls row
to the local OpsWriter outbox. Drain happens at the next human session preflight.

Usage:
    bin/venv-python -m scripts.agent_telemetry_writer \
        --agent rec-curator \
        --trigger cron_workflow \
        --provider anthropic_max \
        --json-output /tmp/agent-output.json \
        --findings-file logs/agents/rec-curator/20260509T080000Z.jsonl \
        --workflow-run-id 1234567890
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# Add repo root to sys.path so sibling package imports resolve when run as a script
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ops_writer import OpsWriter  # noqa: E402
from scripts.telemetry_schemas import TelemetryAgentInvocations, TelemetryModelCalls  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def parse_json_output(path: Path) -> tuple[int, int, str | None, str]:
    """Parse a `claude --output-format json` output file.

    Returns (tokens_input, tokens_output, session_id, model).
    Defaults to zeros and empty strings on missing or malformed data.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return 0, 0, None, "claude-opus-4-7"

    usage = data.get("usage") or {}
    tokens_input = int(usage.get("input_tokens") or 0)
    tokens_output = int(usage.get("output_tokens") or 0)
    session_id = data.get("session_id") or None
    model = data.get("model") or "claude-opus-4-7"
    return tokens_input, tokens_output, session_id, model


def parse_findings(path: Path) -> tuple[int, int]:
    """Parse a findings JSONL file.

    Returns (findings_count, queue_entries_written).
    """
    try:
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return 0, 0

    rows: list[dict] = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    findings_count = len(rows)
    queue_entries_written = sum(1 for r in rows if r.get("type") == "priority-queue-entry")
    return findings_count, queue_entries_written


def emit_telemetry(
    agent_name: str,
    trigger: str,
    provider: str,
    json_output_path: Path,
    findings_path: Path,
    workflow_run_id: str | None,
) -> None:
    """Parse inputs and emit telemetry rows to the local outbox."""
    tokens_input, tokens_output, session_id, model = parse_json_output(json_output_path)
    findings_count, queue_entries_written = parse_findings(findings_path)

    invocation_id = str(uuid.uuid4())
    now = _now_iso()

    invocation_record = TelemetryAgentInvocations(
        invocation_id=invocation_id,
        agent_name=agent_name,
        trigger=trigger,
        started_at=now,
        ended_at=now,
        outcome="success",
        model_used=model,
        provider=provider,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        findings_count=findings_count,
        queue_entries_written=queue_entries_written,
        workflow_run_id=workflow_run_id,
        trade_date=_today_iso(),
    )

    model_call_record = TelemetryModelCalls(
        call_id=str(uuid.uuid4()),
        timestamp=now,
        provider=provider,
        model=model,
        purpose="findings",
        invocation_id=invocation_id,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        copilot_session_id=session_id,
    )

    writer = OpsWriter()
    writer.emit(TelemetryAgentInvocations.TABLE_NAME, invocation_record.to_dict())
    writer.emit(TelemetryModelCalls.TABLE_NAME, model_call_record.to_dict())

    print(
        f"Telemetry written: invocation_id={invocation_id}, findings={findings_count}, queue_entries={queue_entries_written}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Write post-completion telemetry for a Claude Code scheduled agent.")
    parser.add_argument("--agent", required=True, help="Agent name (e.g. rec-curator)")
    parser.add_argument("--trigger", required=True, help="Trigger type (e.g. cron_workflow, manual)")
    parser.add_argument("--provider", required=True, help="Provider (e.g. anthropic_max)")
    parser.add_argument(
        "--json-output",
        required=True,
        dest="json_output",
        help="Path to claude --output-format json output file",
    )
    parser.add_argument(
        "--findings-file",
        required=True,
        dest="findings_file",
        help="Path to findings JSONL file written by the agent",
    )
    parser.add_argument(
        "--workflow-run-id",
        dest="workflow_run_id",
        default=None,
        help="GitHub Actions GITHUB_RUN_ID (null for non-cron triggers)",
    )
    args = parser.parse_args()

    emit_telemetry(
        agent_name=args.agent,
        trigger=args.trigger,
        provider=args.provider,
        json_output_path=Path(args.json_output),
        findings_path=Path(args.findings_file),
        workflow_run_id=args.workflow_run_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
