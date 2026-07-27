from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/ci-rca.yml")


def test_admission_is_separate_and_least_privilege() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    admission = text[text.index("  admission:") : text.index("  bounded-evidence-canary:")]
    assert "permissions:\n      contents: read\n      actions: read" in admission
    rca = text[text.index("  rca:") :]
    assert "needs: admission" in rca


def test_jobs_digest_and_manual_refusal_are_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("scripts.ci_rca.log_admission") >= 2
    assert "CI_RCA_JOBS_RACE" in text
    assert "CI_RCA_HISTORICAL_REPLAY_UNSUPPORTED" in text
    assert "CI_RCA_JOBS_RACE" in text


def test_agent_consumes_verified_envelope_and_no_whole_run_fallback_exists() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    source = Path("scripts/ci_rca/fetch_logs.py").read_text(encoding="utf-8")
    assert "ci-rca-agent-envelope.log" in text
    assert "scripts.ci_rca.agent_envelope" in text
    assert '"--log"' not in source
    assert "Decision 143 mitigation" not in text
