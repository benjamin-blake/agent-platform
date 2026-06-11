"""Unit tests for scripts/run_scheduled_agent.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import scripts.run_scheduled_agent as sched_mod
from scripts.run_scheduled_agent import (
    _match_cron_field,
    _smoke_test,
    is_agent_due,
    load_manifest,
    main,
    run_agent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_MANIFEST = {
    "agents": [
        {
            "name": "doc-freshness",
            "cron": "0 6 * * 1",
            "model": "gpt-4.1-mini",
            "prompt_path": ".github/prompts/scheduled/doc-freshness.prompt.md",
            "description": "Freshness check",
        },
        {
            "name": "orphan-code",
            "cron": "0 6 * * 2",
            "model": "gpt-4.1-mini",
            "prompt_path": ".github/prompts/scheduled/orphan-code.prompt.md",
            "description": "Orphan code check",
        },
    ]
}


@pytest.fixture()
def manifest_file(tmp_path: Path) -> Path:
    """Write a valid manifest YAML to a temp file."""
    p = tmp_path / "schedule.yaml"
    p.write_text(yaml.dump(VALID_MANIFEST), encoding="utf-8")
    return p


@pytest.fixture()
def prompt_file(tmp_path: Path) -> Path:
    """Create a minimal prompt file."""
    p = tmp_path / "agent.prompt.md"
    p.write_text("# Test Agent\nDo something.", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TestMatchCronField
# ---------------------------------------------------------------------------


class TestMatchCronField:
    def test_wildcard_always_matches(self) -> None:
        assert _match_cron_field("*", 0, 0, 59) is True
        assert _match_cron_field("*", 59, 0, 59) is True

    def test_exact_match(self) -> None:
        assert _match_cron_field("6", 6, 0, 23) is True
        assert _match_cron_field("6", 7, 0, 23) is False

    def test_comma_separated(self) -> None:
        assert _match_cron_field("1,3,5", 3, 1, 7) is True
        assert _match_cron_field("1,3,5", 2, 1, 7) is False

    def test_invalid_field_returns_false(self) -> None:
        assert _match_cron_field("abc", 6, 0, 23) is False


# ---------------------------------------------------------------------------
# TestIsAgentDue
# ---------------------------------------------------------------------------


class TestIsAgentDue:
    def _make_agent(self, cron: str) -> dict:
        return {"name": "test", "cron": cron}

    def test_matches_exact_time(self) -> None:
        # Monday (isoweekday=1), 06:00 UTC
        now = datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc)  # April 6 2026 = Monday
        agent = self._make_agent("0 6 * * 1")
        assert is_agent_due(agent, now) is True

    def test_no_match_wrong_hour(self) -> None:
        now = datetime(2026, 4, 6, 7, 0, tzinfo=timezone.utc)  # 07:00, not 06:00
        agent = self._make_agent("0 6 * * 1")
        assert is_agent_due(agent, now) is False

    def test_no_match_wrong_day(self) -> None:
        now = datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc)  # Tuesday, not Monday
        agent = self._make_agent("0 6 * * 1")
        assert is_agent_due(agent, now) is False

    def test_wildcard_day_matches_any_day(self) -> None:
        now = datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc)
        agent = self._make_agent("0 6 * * *")
        assert is_agent_due(agent, now) is True

    def test_malformed_cron_returns_false(self) -> None:
        now = datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc)
        agent = self._make_agent("0 6 * *")  # only 4 fields
        assert is_agent_due(agent, now) is False


# ---------------------------------------------------------------------------
# TestLoadManifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_loads_valid_manifest(self, manifest_file: Path) -> None:
        agents = load_manifest(manifest_file)
        assert len(agents) == 2
        assert agents[0]["name"] == "doc-freshness"

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        agents = load_manifest(tmp_path / "missing.yaml")
        assert agents == []

    def test_returns_empty_for_empty_agents_key(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text(yaml.dump({"agents": []}), encoding="utf-8")
        agents = load_manifest(p)
        assert agents == []


# ---------------------------------------------------------------------------
# TestRunAgent
# ---------------------------------------------------------------------------


class TestRunAgent:
    def _make_agent(self, prompt_path: str) -> dict:
        return {
            "name": "test-agent",
            "cron": "0 6 * * 1",
            "model": "gpt-4.1-mini",
            "prompt_path": prompt_path,
            "description": "Test agent",
        }

    def test_dry_run_returns_true(self, tmp_path: Path, prompt_file: Path) -> None:
        agent = self._make_agent(str(prompt_file))
        with patch.object(sched_mod, "_REPO_ROOT", tmp_path):
            # dry_run=True; make prompt_path absolute so REPO_ROOT / path doesn't break
            # Override agent's prompt_path to be absolute
            agent["prompt_path"] = str(prompt_file)
            # Patch _REPO_ROOT to root so Path(_REPO_ROOT) / prompt_path works
        # Use absolute path so join doesn't depend on _REPO_ROOT
        with patch.object(sched_mod, "_REPO_ROOT", prompt_file.parent):
            agent2 = dict(agent)
            agent2["prompt_path"] = prompt_file.name
            result = run_agent(agent2, dry_run=True)
        assert result is True

    def test_missing_prompt_returns_false(self, tmp_path: Path) -> None:
        agent = self._make_agent("nonexistent/path.md")
        with patch.object(sched_mod, "_REPO_ROOT", tmp_path):
            result = run_agent(agent)
        assert result is False

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        agent = self._make_agent("../../../etc/passwd")
        with patch.object(sched_mod, "_REPO_ROOT", tmp_path):
            result = run_agent(agent)
        assert result is False

    def test_live_invocation_retired_returns_false(
        self, tmp_path: Path, prompt_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # CD.28 retired the local direct (Bedrock) inference path; live
        # invocation must fail loudly and point at --trigger-lambda.
        agent = self._make_agent(prompt_file.name)

        with (
            patch.object(sched_mod, "_REPO_ROOT", prompt_file.parent),
            patch("scripts.ops_data_portal.enqueue_findings") as mock_enqueue,
        ):
            result = run_agent(agent)

        assert result is False
        assert mock_enqueue.call_count == 0
        assert "retired per CD.28" in caplog.text
        assert "--trigger-lambda" in caplog.text

    def test_model_override_still_resolves_before_retirement_error(self, tmp_path: Path, prompt_file: Path) -> None:
        # The override is resolved during validation (dry-run shows it);
        # the live path still returns False under retirement.
        agent = self._make_agent(prompt_file.name)
        with (
            patch.object(sched_mod, "_REPO_ROOT", prompt_file.parent),
            patch.object(sched_mod, "_MODEL_OVERRIDE", "override-model"),
        ):
            assert run_agent(agent, dry_run=True) is True
            assert run_agent(agent) is False

    def test_disabled_agents_skipped(self) -> None:
        agent = self._make_agent("whatever.md")
        agent["enabled"] = False
        result = run_agent(agent)
        assert result is True


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def _patch_manifest(self, manifest_path: Path) -> list[dict]:
        return VALID_MANIFEST["agents"]

    def test_list_flag_returns_zero(self, manifest_file: Path) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=VALID_MANIFEST["agents"]):
            exit_code = main(["--list"])
        assert exit_code == 0

    def test_list_empty_manifest_returns_zero(self) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=[]):
            exit_code = main(["--list"])
        assert exit_code == 0

    def test_agent_not_found_returns_one(self) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=VALID_MANIFEST["agents"]):
            exit_code = main(["--agent", "nonexistent"])
        assert exit_code == 1

    def test_agent_dry_run_returns_zero(self, prompt_file: Path) -> None:
        agents = [
            {
                "name": "doc-freshness",
                "cron": "0 6 * * 1",
                "model": "gpt-4.1-mini",
                "prompt_path": prompt_file.name,
                "description": "Test",
            }
        ]
        with (
            patch("scripts.run_scheduled_agent.load_manifest", return_value=agents),
            patch.object(sched_mod, "_REPO_ROOT", prompt_file.parent),
        ):
            exit_code = main(["--agent", "doc-freshness", "--dry-run"])
        assert exit_code == 0

    def test_due_no_agents_returns_zero(self) -> None:
        now = datetime(2026, 4, 6, 12, 30, tzinfo=timezone.utc)  # No agents due
        with (
            patch("scripts.run_scheduled_agent.load_manifest", return_value=VALID_MANIFEST["agents"]),
            patch("scripts.run_scheduled_agent.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            exit_code = main(["--due"])
        assert exit_code == 0

    def test_no_flags_returns_one(self) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=[]):
            exit_code = main([])
        assert exit_code == 1

    def test_agent_invalid_name_returns_one(self) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=VALID_MANIFEST["agents"]):
            exit_code = main(["--agent", "../etc/passwd"])
        assert exit_code == 1

    def test_agent_invalid_name_with_spaces_returns_one(self) -> None:
        with patch("scripts.run_scheduled_agent.load_manifest", return_value=VALID_MANIFEST["agents"]):
            exit_code = main(["--agent", "my agent"])
        assert exit_code == 1


# ---------------------------------------------------------------------------
# TestCronRangeValidation
# ---------------------------------------------------------------------------


class TestCronRangeValidation:
    def test_value_below_min_returns_false(self) -> None:
        assert _match_cron_field("*", -1, 0, 59) is False

    def test_value_above_max_returns_false(self) -> None:
        assert _match_cron_field("*", 60, 0, 59) is False

    def test_exact_value_above_max_returns_false(self) -> None:
        assert _match_cron_field("99", 99, 0, 59) is False

    def test_boundary_min_matches(self) -> None:
        assert _match_cron_field("0", 0, 0, 59) is True

    def test_boundary_max_matches(self) -> None:
        assert _match_cron_field("59", 59, 0, 59) is True


# ---------------------------------------------------------------------------
# TestRealManifest
# ---------------------------------------------------------------------------


class TestRealManifest:
    def test_real_manifest_loads_and_has_required_keys(self) -> None:
        """Integration test: real schedule.yaml must load and have all required agent keys."""
        agents = load_manifest()
        assert len(agents) >= 4, f"Expected at least 4 agents, got {len(agents)}"
        required_keys = {"name", "cron", "model", "prompt_path", "description"}
        for agent in agents:
            missing = required_keys - set(agent.keys())
            assert not missing, f"Agent {agent.get('name', '?')} is missing keys: {missing}"

    def test_real_manifest_agent_names_are_valid(self) -> None:
        """Agent names must match [a-z0-9-]+ pattern used in name validation."""
        import re

        agents = load_manifest()
        for agent in agents:
            name = agent.get("name", "")
            assert re.match(r"^[a-z0-9-]+$", name), f"Invalid agent name: {name!r}"


class TestRunAgentFindings:
    """The findings-write path left run_agent with the CD.28 retirement."""

    def test_rec_curator_live_path_retired(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.prompt.md"
        prompt_file.write_text("Hello", encoding="utf-8")

        agent_def = {
            "name": "rec-curator",
            "model": "gpt-4.1-mini",
            "prompt_path": prompt_file.name,
        }

        with patch("scripts.run_scheduled_agent._REPO_ROOT", tmp_path):
            assert run_agent(agent_def) is False


class TestTriggerLambda:
    """Tests for the --trigger-lambda flag and _trigger_lambda()."""

    def test_trigger_lambda_constructs_correct_subprocess_command(self) -> None:
        """--trigger-lambda passes the correct aws lambda invoke command."""
        import json as _json

        from scripts.run_scheduled_agent import _trigger_lambda

        mock_result = MagicMock()
        mock_result.returncode = 0

        tmp_response = '{"StatusCode": 200}'
        _file_ctx = MagicMock()
        _file_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=tmp_response)))
        _file_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.run_scheduled_agent.subprocess.run", return_value=mock_result) as mock_run,
            patch("scripts.run_scheduled_agent.tempfile.mkstemp", return_value=(0, "/tmp/test-out.json")),
            patch("builtins.open", MagicMock(return_value=_file_ctx)),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _trigger_lambda("rec-curator")

        assert exit_code == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "aws" in cmd
        assert "lambda" in cmd
        assert "invoke" in cmd
        assert "--function-name" in cmd
        assert "agent-platform-scheduled-agent-dispatcher" in cmd
        assert "--payload" in cmd
        payload_idx = cmd.index("--payload") + 1
        payload = _json.loads(cmd[payload_idx])
        assert payload == {"force_agent": "rec-curator"}

    def test_trigger_lambda_returns_1_on_subprocess_failure(self) -> None:
        """Returns exit code 1 when the aws CLI invocation fails."""
        from scripts.run_scheduled_agent import _trigger_lambda

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "An error occurred"

        with (
            patch("scripts.run_scheduled_agent.subprocess.run", return_value=mock_result),
            patch("scripts.run_scheduled_agent.tempfile.mkstemp", return_value=(0, "/tmp/test-out.json")),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _trigger_lambda("rec-curator")

        assert exit_code == 1


# ---------------------------------------------------------------------------
# TestSmokeTest
# ---------------------------------------------------------------------------


class TestSmokeTest:
    """Tests for the --smoke-test flag and _smoke_test()."""

    def test_smoke_test_success_full_flow(self) -> None:
        """Returns 0 when deploy, invoke, and S3 verification all succeed."""
        # depth-first subprocess call tree for _smoke_test():
        #   1. sys.executable -m scripts.build_lambda --deploy  (subprocess.run)
        #   2. aws lambda invoke ... (via _trigger_lambda)      (subprocess.run)
        #   3. aws s3api list-objects-v2 ...                    (subprocess.run)
        # Total subprocess.run count: 3
        now = datetime.now(timezone.utc).isoformat()
        s3_response = json.dumps(
            {
                "Key": "agents/doc-freshness/2026-04-19.jsonl",
                "LastModified": now,
            }
        )

        deploy_result = MagicMock(returncode=0, stdout="", stderr="")
        invoke_result = MagicMock(returncode=0, stdout="", stderr="")
        s3_result = MagicMock(returncode=0, stdout=s3_response, stderr="")

        # _trigger_lambda reads a temp file for Lambda response
        _file_ctx = MagicMock()
        _file_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value='{"StatusCode": 200}')))
        _file_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "scripts.run_scheduled_agent.subprocess.run",
                side_effect=[deploy_result, invoke_result, s3_result],
            ),
            patch(
                "scripts.run_scheduled_agent.tempfile.mkstemp",
                return_value=(0, "/tmp/smoke.json"),
            ),
            patch("builtins.open", MagicMock(return_value=_file_ctx)),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 0

    def test_smoke_test_deploy_failure_returns_1(self) -> None:
        """Returns 1 when build/deploy fails."""
        deploy_result = MagicMock(returncode=1, stdout="", stderr="build error")

        with patch(
            "scripts.run_scheduled_agent.subprocess.run",
            return_value=deploy_result,
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 1

    def test_smoke_test_invoke_failure_returns_2(self) -> None:
        """Returns 2 when Lambda invocation fails."""
        deploy_result = MagicMock(returncode=0, stdout="", stderr="")
        invoke_result = MagicMock(returncode=1, stdout="", stderr="invoke err")

        with (
            patch(
                "scripts.run_scheduled_agent.subprocess.run",
                side_effect=[deploy_result, invoke_result],
            ),
            patch(
                "scripts.run_scheduled_agent.tempfile.mkstemp",
                return_value=(0, "/tmp/smoke.json"),
            ),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 2

    def test_smoke_test_stale_object_returns_3(self) -> None:
        """Returns 3 when the latest S3 object is older than 60 seconds."""
        stale_time = "2020-01-01T00:00:00+00:00"
        s3_response = json.dumps(
            {
                "Key": "agents/doc-freshness/old.jsonl",
                "LastModified": stale_time,
            }
        )

        deploy_result = MagicMock(returncode=0, stdout="", stderr="")
        invoke_result = MagicMock(returncode=0, stdout="", stderr="")
        s3_result = MagicMock(returncode=0, stdout=s3_response, stderr="")

        _file_ctx = MagicMock()
        _file_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value='{"StatusCode": 200}')))
        _file_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "scripts.run_scheduled_agent.subprocess.run",
                side_effect=[deploy_result, invoke_result, s3_result],
            ),
            patch(
                "scripts.run_scheduled_agent.tempfile.mkstemp",
                return_value=(0, "/tmp/smoke.json"),
            ),
            patch("builtins.open", MagicMock(return_value=_file_ctx)),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 3

    def test_smoke_test_no_objects_returns_3(self) -> None:
        """Returns 3 when no objects found in S3."""
        deploy_result = MagicMock(returncode=0, stdout="", stderr="")
        invoke_result = MagicMock(returncode=0, stdout="", stderr="")
        s3_result = MagicMock(returncode=0, stdout="null", stderr="")

        _file_ctx = MagicMock()
        _file_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value='{"StatusCode": 200}')))
        _file_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "scripts.run_scheduled_agent.subprocess.run",
                side_effect=[deploy_result, invoke_result, s3_result],
            ),
            patch(
                "scripts.run_scheduled_agent.tempfile.mkstemp",
                return_value=(0, "/tmp/smoke.json"),
            ),
            patch("builtins.open", MagicMock(return_value=_file_ctx)),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 3

    def test_smoke_test_s3_command_failure_returns_3(self) -> None:
        """Returns 3 when the S3 list-objects-v2 command fails."""
        deploy_result = MagicMock(returncode=0, stdout="", stderr="")
        invoke_result = MagicMock(returncode=0, stdout="", stderr="")
        s3_result = MagicMock(returncode=1, stdout="", stderr="s3 error")

        _file_ctx = MagicMock()
        _file_ctx.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value='{"StatusCode": 200}')))
        _file_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "scripts.run_scheduled_agent.subprocess.run",
                side_effect=[deploy_result, invoke_result, s3_result],
            ),
            patch(
                "scripts.run_scheduled_agent.tempfile.mkstemp",
                return_value=(0, "/tmp/smoke.json"),
            ),
            patch("builtins.open", MagicMock(return_value=_file_ctx)),
            patch("scripts.run_scheduled_agent.os.close"),
            patch("scripts.run_scheduled_agent.os.unlink"),
        ):
            exit_code = _smoke_test("doc-freshness")

        assert exit_code == 3

    def test_main_smoke_test_invalid_name(self) -> None:
        """--smoke-test rejects invalid agent names."""
        with patch(
            "scripts.run_scheduled_agent.load_manifest",
            return_value=VALID_MANIFEST["agents"],
        ):
            exit_code = main(["--smoke-test", "../bad-name"])
        assert exit_code == 1

    def test_main_smoke_test_dispatches_to_function(self) -> None:
        """--smoke-test routes to _smoke_test with valid name."""
        with (
            patch(
                "scripts.run_scheduled_agent.load_manifest",
                return_value=VALID_MANIFEST["agents"],
            ),
            patch(
                "scripts.run_scheduled_agent._smoke_test",
                return_value=0,
            ) as mock_st,
        ):
            exit_code = main(["--smoke-test", "doc-freshness"])

        assert exit_code == 0
        mock_st.assert_called_once_with("doc-freshness")
