"""Tests for scripts/build_lambda_deploy.py (Decision 104 split of tests/test_build_lambda.py)."""

import io
import json
import types
from unittest.mock import MagicMock, patch

# boto3 is imported at MODULE scope even though it is referenced only via read_deploy_record's
# lazy fallback / patch("boto3.client") strings and local `from botocore.exceptions import
# ClientError` imports below. This makes the file's heavy-dep requirement visible to the fast
# tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to the full post-merge
# tier, instead of catching it REACTIVELY -- mirrors tests/test_convergence_health.py's identical
# marker (boto3 is deliberately excluded from requirements-fast.txt; the full tier runs this file).
import boto3  # noqa: F401
import pytest

import scripts.build_lambda as bl
import scripts.build_lambda_deploy as bd
from scripts.build_lambda_config import (
    _DUCKLAKE_CATALOG_DR_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_WRITER_FUNCTION,
    _LAMBDA_FUNCTION_NAMES,
    _OPS_COMPACTION_FUNCTION_NAME,
    _OPS_COMPACTION_ZIP_KEY,
)

pytestmark = pytest.mark.unit


class _FakePath:
    """Minimal Path double exposing .name + .stat().st_size for size-assert tests."""

    def __init__(self, size=100, name="x.zip"):
        self._size = size
        self.name = name

    def stat(self):
        return types.SimpleNamespace(st_size=self._size)


def _args(**kw):
    import argparse

    ns = argparse.Namespace(
        skip_upload=True,
        bucket="",
        profile="agent_platform",
        region="eu-west-2",
        deploy=False,
        ducklake_only=False,
        list_bundle=None,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_validate_bucket_exists_success():
    """Test that validate_bucket_exists returns True when bucket exists."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        result = bd.validate_bucket_exists("test-bucket", "company-aws-profile", "eu-west-2")

        assert result is True
        mock_run.assert_called_once()


def test_validate_bucket_exists_failure():
    """Test that validate_bucket_exists returns False when bucket doesn't exist."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 254

        result = bd.validate_bucket_exists("nonexistent-bucket", "company-aws-profile", "eu-west-2")

        assert result is False
        mock_run.assert_called_once()


def test_validate_bucket_exists_call_args():
    """Test that validate_bucket_exists calls aws s3api head-bucket with correct arguments."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        bd.validate_bucket_exists("my-bucket", "my-profile", "us-west-2")

        call_args = mock_run.call_args[0][0]
        assert "aws" in call_args
        assert "s3api" in call_args
        assert "head-bucket" in call_args
        assert "--bucket" in call_args
        assert "my-bucket" in call_args
        assert "--profile" in call_args
        assert "my-profile" in call_args
        assert "--region" in call_args
        assert "us-west-2" in call_args


class TestUpdateLambdaFunctions:
    """Tests for the update_lambda_functions deploy path."""

    # depth-first subprocess call tree for update_lambda_functions():
    #   1. aws lambda update-function-code (dispatcher)      (subprocess.run)
    #   2. aws lambda update-function-code (findings)        (subprocess.run)
    #   3. aws lambda update-function-code (ops_compaction)  (subprocess.run)
    # Total subprocess.run count: 3 -- side_effect list must have 3 entries

    def _make_success(self) -> MagicMock:
        mock = MagicMock()
        mock.returncode = 0
        return mock

    def test_update_calls_all_functions(self):
        """All three Lambda functions receive an update-function-code call."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

            assert mock_run.call_count == 3

    def test_update_function_names(self):
        """Each call targets the correct Lambda function name."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

            all_functions = list(_LAMBDA_FUNCTION_NAMES) + [_OPS_COMPACTION_FUNCTION_NAME]
            for idx, fn_name in enumerate(all_functions):
                cmd = mock_run.call_args_list[idx][0][0]
                fn_idx = cmd.index("--function-name")
                assert cmd[fn_idx + 1] == fn_name

    def test_update_pipeline_functions_use_pipeline_zip(self):
        """Dispatcher and findings-processor use data-pipeline.zip."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

            for idx in range(len(_LAMBDA_FUNCTION_NAMES)):
                cmd = mock_run.call_args_list[idx][0][0]
                bucket_idx = cmd.index("--s3-bucket")
                assert cmd[bucket_idx + 1] == "deploy-bucket"
                key_idx = cmd.index("--s3-key")
                assert cmd[key_idx + 1] == "lambda-packages/data-pipeline.zip"

    def test_update_ops_compaction_uses_minimal_zip(self):
        """ops_compaction Lambda uses the minimal ops-compaction.zip."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

            # ops_compaction is the last call (index = len(_LAMBDA_FUNCTION_NAMES))
            ops_idx = len(_LAMBDA_FUNCTION_NAMES)
            cmd = mock_run.call_args_list[ops_idx][0][0]
            fn_idx = cmd.index("--function-name")
            assert cmd[fn_idx + 1] == _OPS_COMPACTION_FUNCTION_NAME
            key_idx = cmd.index("--s3-key")
            assert cmd[key_idx + 1] == _OPS_COMPACTION_ZIP_KEY

    def test_update_region_and_profile(self):
        """Region and profile are forwarded to the AWS CLI."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("b", "company-aws-profile", "eu-west-2")

            for c in mock_run.call_args_list:
                cmd = c[0][0]
                region_idx = cmd.index("--region")
                assert cmd[region_idx + 1] == "eu-west-2"
                profile_idx = cmd.index("--profile")
                assert cmd[profile_idx + 1] == "company-aws-profile"

    def test_update_subprocess_kwargs(self):
        """Windows-safe subprocess kwargs are set."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            bd.update_lambda_functions("b", "p", "eu-west-2")

            for c in mock_run.call_args_list:
                kwargs = c[1]
                assert kwargs["text"] is True
                assert kwargs["encoding"] == "utf-8"
                assert kwargs["errors"] == "replace"
                assert kwargs["capture_output"] is True

    def test_update_exits_on_failure(self):
        """sys.exit is called when a Lambda update fails."""
        fail_mock = MagicMock()
        fail_mock.returncode = 1
        fail_mock.stderr = "AccessDenied"

        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [fail_mock]

            with pytest.raises(SystemExit) as exc_info:
                bd.update_lambda_functions("b", "p", "eu-west-2")

            assert exc_info.value.code == 1

    def test_lambda_function_names_constant(self):
        """All expected Lambda function names are present."""
        assert "agent-platform-scheduled-agent-dispatcher" in _LAMBDA_FUNCTION_NAMES
        assert "agent-platform-findings-processor" in _LAMBDA_FUNCTION_NAMES
        assert _OPS_COMPACTION_FUNCTION_NAME == "agent-platform-ops-compaction"
        assert _OPS_COMPACTION_ZIP_KEY == "lambda-packages/ops-compaction.zip"


class TestUpdateLambdaFunctionsDucklakeOnly:
    # only_ducklake=True call sequence per function (T2.38 c3): update-function-code, THEN
    # (on success) the deploy-record S3 write -- 2 subprocess.run calls x 4 functions = 8 total.
    # See docs/PROJECT_CONTEXT.md "postflight.py function mock exhaustion" gotcha: a new
    # subprocess.run call added inside update_lambda_functions' only_ducklake branch means every
    # side_effect list feeding it here must grow to match, or the extra call silently StopIterations.

    def _update_response(self, code_sha256: str = "deadbeef"):
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"CodeSha256": code_sha256}), stderr="")

    def _write_response(self):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_only_ducklake_updates_four_functions(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
            ]
            bd.update_lambda_functions("b", "p", "eu-west-2", only_ducklake=True)
        assert mock_run.call_count == 8
        targeted = []
        for idx in range(0, 8, 2):
            cmd = mock_run.call_args_list[idx][0][0]
            targeted.append(cmd[cmd.index("--function-name") + 1])
        assert set(targeted) == {
            _DUCKLAKE_WRITER_FUNCTION,
            _DUCKLAKE_READER_FUNCTION,
            _DUCKLAKE_MAINTENANCE_FUNCTION,
            _DUCKLAKE_CATALOG_DR_FUNCTION,
        }

    def test_only_ducklake_update_call_requests_json_output(self):
        """The update-function-code call must request --output json (CodeSha256 capture, c3)."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
                self._update_response(),
                self._write_response(),
            ]
            bd.update_lambda_functions("b", "p", "eu-west-2", only_ducklake=True)
        for idx in range(0, 8, 2):
            cmd = mock_run.call_args_list[idx][0][0]
            assert "--output" in cmd
            assert cmd[cmd.index("--output") + 1] == "json"

    def test_non_ducklake_path_does_not_write_deploy_records(self):
        """The prod/ops_compaction path (only_ducklake=False, default) must never touch
        deploy-records/ducklake/ -- exactly 3 subprocess calls, none of them `aws s3 cp`."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                types.SimpleNamespace(returncode=0, stdout="", stderr=""),
                types.SimpleNamespace(returncode=0, stdout="", stderr=""),
                types.SimpleNamespace(returncode=0, stdout="", stderr=""),
            ]
            bd.update_lambda_functions("b", "p", "eu-west-2")
        assert mock_run.call_count == 3
        for c in mock_run.call_args_list:
            assert c[0][0][:3] != ["aws", "s3", "cp"]


class TestWriteDucklakeDeployRecord:
    """Unit tests for _write_ducklake_deploy_record (T2.38 c3: CodeSha256 capture + record write)."""

    def _stdout(self, code_sha256: str = "sha-abc123") -> str:
        return json.dumps({"CodeSha256": code_sha256, "FunctionName": "whatever"})

    def test_writes_record_with_expected_schema(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SHA", "deadbeefcafe")
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            captured["input"] = kw.get("input")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(
                _DUCKLAKE_WRITER_FUNCTION, self._stdout("sha-writer"), "my-bucket", "p", "eu-west-2"
            )

        assert captured["cmd"][:3] == ["aws", "s3", "cp"]
        assert captured["cmd"][3] == "-"
        assert captured["cmd"][4] == f"s3://my-bucket/deploy-records/ducklake/{_DUCKLAKE_WRITER_FUNCTION}.json"
        record = json.loads(captured["input"])
        assert record["function"] == _DUCKLAKE_WRITER_FUNCTION
        assert record["code_sha256"] == "sha-writer"
        assert record["source_git_sha"] == "deadbeefcafe"
        assert "deployed_at" in record and record["deployed_at"]

    def test_key_is_per_function(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["dest"] = cmd[4]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(_DUCKLAKE_READER_FUNCTION, self._stdout(), "bucket", "p", "eu-west-2")
        assert captured["dest"] == f"s3://bucket/deploy-records/ducklake/{_DUCKLAKE_READER_FUNCTION}.json"

    def test_source_git_sha_none_safe_when_github_sha_unset(self, monkeypatch):
        """Local break-glass path (bin/venv-python -m scripts.build_lambda --ducklake-only
        --deploy) has no GITHUB_SHA -- the record must carry source_git_sha=null, not KeyError."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        captured = {}

        def fake_run(cmd, **kw):
            captured["input"] = kw.get("input")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(_DUCKLAKE_MAINTENANCE_FUNCTION, self._stdout(), "bucket", "p", "eu-west-2")
        record = json.loads(captured["input"])
        assert record["source_git_sha"] is None

    def test_content_type_json(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(_DUCKLAKE_CATALOG_DR_FUNCTION, self._stdout(), "bucket", "p", "eu-west-2")
        cmd = captured["cmd"]
        assert "--content-type" in cmd
        assert cmd[cmd.index("--content-type") + 1] == "application/json"

    def test_exits_on_unparseable_json_response(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                bd._write_ducklake_deploy_record(_DUCKLAKE_WRITER_FUNCTION, "not-json-at-all", "bucket", "p", "eu-west-2")
            assert exc_info.value.code == 1
        mock_run.assert_not_called()

    def test_exits_when_codesha256_key_missing(self):
        with pytest.raises(SystemExit) as exc_info:
            bd._write_ducklake_deploy_record(
                _DUCKLAKE_WRITER_FUNCTION, json.dumps({"FunctionName": "x"}), "bucket", "p", "eu-west-2"
            )
        assert exc_info.value.code == 1

    def test_exits_on_s3_write_failure(self):
        fail = types.SimpleNamespace(returncode=1, stdout="", stderr="AccessDenied")
        with patch("scripts.build_lambda.subprocess.run", return_value=fail):
            with pytest.raises(SystemExit) as exc_info:
                bd._write_ducklake_deploy_record(_DUCKLAKE_WRITER_FUNCTION, self._stdout(), "bucket", "p", "eu-west-2")
            assert exc_info.value.code == 1

    def test_profile_and_region_forwarded(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(
                _DUCKLAKE_WRITER_FUNCTION, self._stdout(), "bucket", "agent_platform", "us-west-2"
            )
        cmd = captured["cmd"]
        assert "--region" in cmd and cmd[cmd.index("--region") + 1] == "us-west-2"
        assert "--profile" in cmd and cmd[cmd.index("--profile") + 1] == "agent_platform"

    def test_profileless_omits_profile_flag(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(_DUCKLAKE_WRITER_FUNCTION, self._stdout(), "bucket", "", "eu-west-2")
        assert "--profile" not in captured["cmd"]


class TestReadDeployRecord:
    """Unit tests for read_deploy_record (T2.38 c3 read-back helper; injected S3, no live AWS)."""

    def test_returns_parsed_json(self):
        payload = json.dumps(
            {"function": _DUCKLAKE_WRITER_FUNCTION, "code_sha256": "abc123", "source_git_sha": "sha1", "deployed_at": "x"}
        ).encode()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(payload)}

        result = bd.read_deploy_record(_DUCKLAKE_WRITER_FUNCTION, s3_client=mock_s3)

        assert result == {
            "function": _DUCKLAKE_WRITER_FUNCTION,
            "code_sha256": "abc123",
            "source_git_sha": "sha1",
            "deployed_at": "x",
        }
        mock_s3.get_object.assert_called_once_with(
            Bucket="agent-platform-data-lake",
            Key=f"deploy-records/ducklake/{_DUCKLAKE_WRITER_FUNCTION}.json",
        )

    def test_custom_bucket_honoured(self):
        payload = json.dumps({"code_sha256": "x"}).encode()
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(payload)}
        bd.read_deploy_record(_DUCKLAKE_READER_FUNCTION, s3_client=mock_s3, bucket="other-bucket")
        mock_s3.get_object.assert_called_once_with(
            Bucket="other-bucket",
            Key=f"deploy-records/ducklake/{_DUCKLAKE_READER_FUNCTION}.json",
        )

    def test_returns_none_on_no_such_key(self):
        from botocore.exceptions import ClientError

        error = ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = error
        assert bd.read_deploy_record(_DUCKLAKE_WRITER_FUNCTION, s3_client=mock_s3) is None

    def test_reraises_non_nosuchkey_error(self):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = err
        with pytest.raises(ClientError):
            bd.read_deploy_record(_DUCKLAKE_WRITER_FUNCTION, s3_client=mock_s3)

    def test_lazy_creates_boto3_client_when_none(self):
        with patch("boto3.client") as mock_client:
            mock_client.return_value.get_object.side_effect = RuntimeError("NoSuchKey")
            bd.read_deploy_record(_DUCKLAKE_WRITER_FUNCTION)
        mock_client.assert_called_once_with("s3")

    def test_round_trip_write_then_read(self, monkeypatch):
        """The record _write_ducklake_deploy_record writes is exactly what read_deploy_record
        parses back -- proves schema symmetry end-to-end (minus the live S3 transport)."""
        monkeypatch.setenv("GITHUB_SHA", "roundtrip-sha")
        written = {}

        def fake_run(cmd, **kw):
            written["input"] = kw.get("input")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd._write_ducklake_deploy_record(
                _DUCKLAKE_MAINTENANCE_FUNCTION,
                json.dumps({"CodeSha256": "sha-m"}),
                "roundtrip-bucket",
                "p",
                "eu-west-2",
            )

        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(written["input"].encode())}
        record = bd.read_deploy_record(_DUCKLAKE_MAINTENANCE_FUNCTION, s3_client=mock_s3, bucket="roundtrip-bucket")

        assert record["function"] == _DUCKLAKE_MAINTENANCE_FUNCTION
        assert record["code_sha256"] == "sha-m"
        assert record["source_git_sha"] == "roundtrip-sha"
        assert "deployed_at" in record


class TestResolveDucklakeProfile:
    def test_generic_default_maps_to_personal(self):
        assert bd._resolve_ducklake_profile("company-aws-profile") == "agent_platform"

    def test_explicit_profile_unchanged(self):
        assert bd._resolve_ducklake_profile("agent_platform") == "agent_platform"
        assert bd._resolve_ducklake_profile("agent_platform_admin") == "agent_platform_admin"

    def test_ducklake_build_resolves_profile(self):
        """_run_ducklake_build (the orchestrator; still defined in scripts.build_lambda) resolves
        the generic default profile to agent_platform before calling the DuckLake builders --
        exercised via the facade since the orchestrator itself does not move."""
        captured = {}
        with (
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch(
                "scripts.build_lambda.build_ducklake_function_package",
                side_effect=[
                    _FakePath(name="w.zip"),
                    _FakePath(name="r.zip"),
                    _FakePath(name="m.zip"),
                    _FakePath(name="dr.zip"),
                ],
            ),
            patch("scripts.build_lambda.build_ducklake_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch(
                "scripts.build_lambda.build_ducklake_extensions_layer",
                side_effect=lambda td, **kw: captured.update(kw) or _FakePath(name="ext.zip"),
            ),
            patch("scripts.build_lambda.build_pgclient_layer", return_value=_FakePath(name="pgclient.zip")),
            patch("scripts.build_lambda.assert_within_size_limit"),
        ):
            bl._run_ducklake_build(_args(skip_upload=True, profile="company-aws-profile"))
        assert captured["profile"] == "agent_platform"  # generic default resolved to personal


class TestResolveBucket:
    def test_terraform_output_used(self):
        with patch(
            "scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=0, stdout="tf-bucket\n")
        ):
            assert bd.resolve_bucket("p") == "tf-bucket"

    def test_empty_output_falls_back(self):
        with patch("scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=0, stdout="")):
            assert bd.resolve_bucket("p") == "agent-platform-data-lake"

    def test_terraform_missing_falls_back(self):
        with patch("scripts.build_lambda.subprocess.run", side_effect=FileNotFoundError):
            assert bd.resolve_bucket("p") == "agent-platform-data-lake"


class TestPublishCanaryLayers:
    """Unit tests for publish_canary_layers() -- mocked aws lambda publish-layer-version."""

    def _arn_response(self, layer_name: str) -> str:
        import json

        return json.dumps(
            {
                "LayerVersionArn": f"arn:aws:lambda:eu-west-2:ACCOUNT_ID_PLACEHOLDER:layer:{layer_name}:99",
                "Version": 99,
            }
        )

    def test_publishes_all_three_layers_returns_arns(self):
        call_args_list = []

        def fake_run(cmd, **kw):
            layer_name = cmd[cmd.index("--layer-name") + 1]
            call_args_list.append(layer_name)
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            arns = bd.publish_canary_layers(bucket="my-bucket", profile="agent_platform", region="eu-west-2")

        assert set(arns.keys()) == {"ducklake-deps-layer", "ducklake-extensions-layer", "ducklake-pgclient-layer"}
        for name, arn in arns.items():
            assert arn == f"arn:aws:lambda:eu-west-2:ACCOUNT_ID_PLACEHOLDER:layer:{name}:99"
        assert set(call_args_list) == {"ducklake-deps-layer", "ducklake-extensions-layer", "ducklake-pgclient-layer"}

    def test_prints_json_arns_to_stdout(self, capsys):
        def fake_run(cmd, **kw):
            layer_name = cmd[cmd.index("--layer-name") + 1]
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd.publish_canary_layers(bucket="b", profile="p", region="r")

        captured = capsys.readouterr().out
        import json

        json_line = [ln for ln in captured.splitlines() if ln.startswith("{")]
        assert json_line, "Expected a JSON line in stdout"
        data = json.loads(json_line[-1])
        assert "ducklake-deps-layer" in data

    def test_exits_on_publish_failure(self):
        def fake_run(cmd, **kw):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="AccessDenied")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            with pytest.raises(SystemExit):
                bd.publish_canary_layers(bucket="b", profile="p", region="r")

    def test_uses_correct_s3_key_per_layer(self):
        seen_keys = []

        def fake_run(cmd, **kw):
            content_arg = cmd[cmd.index("--content") + 1]
            seen_keys.append(content_arg)
            layer_name = cmd[cmd.index("--layer-name") + 1]
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bd.publish_canary_layers(bucket="my-bucket", profile="p", region="r")

        for key in seen_keys:
            assert "my-bucket" in key
            assert key.startswith("S3Bucket=my-bucket,S3Key=lambda-packages/")

    def test_canary_layers_sourced_from_accessor(self):
        """publish_canary_layers iterates _build_ducklake_layer_names(), not DUCKLAKE_LAYER_NAMES directly.

        Relocated from TestBuildLambdaContract (tests/test_build_lambda.py:902, critique finding B):
        publish_canary_layers now resolves _build_ducklake_layer_names in ITS OWN (deploy) module
        namespace, so the patch target is the string-form scripts.build_lambda_deploy accessor --
        an attribute-object-style patch against the old facade alias would silently no-op post-split.
        """
        import json

        fake_layers = ["layer-a", "layer-b"]
        call_log: list[str] = []

        def fake_run(cmd, **kw):
            layer_name = cmd[cmd.index("--layer-name") + 1]
            call_log.append(layer_name)
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"LayerVersionArn": f"arn:aws:lambda:::layer:{layer_name}:1", "Version": 1}),
                stderr="",
            )

        with (
            patch("scripts.build_lambda_deploy._build_ducklake_layer_names", return_value=fake_layers),
            patch("scripts.build_lambda.subprocess.run", side_effect=fake_run),
        ):
            bd.publish_canary_layers(bucket="b", profile="p", region="r")
        assert call_log == fake_layers


class TestProfilelessArgv:
    """aws CLI argv omits `--profile` when the resolved profile is empty (GitHub-hosted OIDC
    runners resolve creds from the environment and have no named profile) and includes it when
    non-empty (local/agent_platform dev). Unblocks `--ducklake-only` under CI (rec-2512).

    Only the deploy-owned functions' profileless tests live here; see the config/packaging test
    files for the rest of the original TestProfilelessArgv split.
    """

    def test_upload_to_s3_omits_profile_when_empty(self, tmp_path):
        zip_path = tmp_path / "x.zip"
        zip_path.write_bytes(b"z")
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            bd.upload_to_s3(zip_path, "bucket", "", "eu-west-2")
        argv = mock_run.call_args[0][0]
        assert "--profile" not in argv

    def test_upload_to_s3_includes_profile_when_set(self, tmp_path):
        zip_path = tmp_path / "x.zip"
        zip_path.write_bytes(b"z")
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            bd.upload_to_s3(zip_path, "bucket", "agent_platform", "eu-west-2")
        argv = mock_run.call_args[0][0]
        assert "--profile" in argv
        assert "agent_platform" in argv

    def test_validate_bucket_exists_omits_profile_when_empty(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            bd.validate_bucket_exists("bucket", "", "eu-west-2")
        argv = mock_run.call_args[0][0]
        assert "--profile" not in argv

    def test_update_lambda_functions_omits_profile_when_empty(self):
        # Shared return_value covers BOTH the update-function-code call and (only_ducklake=True)
        # the deploy-record s3-cp write call, so it must carry a parseable CodeSha256 stdout.
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.return_value = types.SimpleNamespace(returncode=0, stdout=json.dumps({"CodeSha256": "sha"}), stderr="")
            bd.update_lambda_functions("bucket", "", "eu-west-2", only_ducklake=True)
        assert mock_run.call_args_list
        for call in mock_run.call_args_list:
            assert "--profile" not in call[0][0]

    def test_update_lambda_functions_includes_profile_when_set(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.return_value = types.SimpleNamespace(returncode=0, stdout=json.dumps({"CodeSha256": "sha"}), stderr="")
            bd.update_lambda_functions("bucket", "agent_platform", "eu-west-2", only_ducklake=True)
        assert mock_run.call_args_list
        for call in mock_run.call_args_list:
            assert "--profile" in call[0][0]
            assert "agent_platform" in call[0][0]
