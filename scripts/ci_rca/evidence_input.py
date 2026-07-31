"""Validated retrieval input adapter for durable CI-RCA evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.ci_rca.log_evidence import read_envelope


def load_retrieval_input(envelope_path: Path, log_path: Path, run_id: int) -> dict[str, Any]:
    envelope = read_envelope(envelope_path)
    if envelope["recovery"]["state"] != "available":
        raise ValueError("raw recovery evidence has expired")
    if envelope["identity"]["run_id"] != run_id:
        raise ValueError("retrieval envelope run identity does not match --workflow-run-id")
    if log_path.read_text(encoding="utf-8") != envelope["body"]:
        raise ValueError("log file does not match the validated retrieval envelope")
    return {
        key: envelope[key]
        for key in (
            "schema",
            "identity",
            "failed_jobs",
            "retrieval_path",
            "scope",
            "fallback_selection",
            "limits",
            "recovery",
        )
    }
