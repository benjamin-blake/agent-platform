"""Tests for build_lambda module."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.build_lambda import (
    _LAMBDA_FUNCTION_NAMES,
    _LAMBDA_SCRIPTS,
    _OPS_COMPACTION_FUNCTION_NAME,
    _OPS_COMPACTION_ZIP_KEY,
    update_lambda_functions,
    validate_bucket_exists,
)

pytestmark = pytest.mark.unit


def test_validate_bucket_exists_success():
    """Test that validate_bucket_exists returns True when bucket exists."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        result = validate_bucket_exists("test-bucket", "company-aws-profile", "eu-west-2")

        assert result is True
        mock_run.assert_called_once()


def test_validate_bucket_exists_failure():
    """Test that validate_bucket_exists returns False when bucket doesn't exist."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 254

        result = validate_bucket_exists("nonexistent-bucket", "company-aws-profile", "eu-west-2")

        assert result is False
        mock_run.assert_called_once()


def test_validate_bucket_exists_call_args():
    """Test that validate_bucket_exists calls aws s3api head-bucket with correct arguments."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        validate_bucket_exists("my-bucket", "my-profile", "us-west-2")

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

            update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

            assert mock_run.call_count == 3

    def test_update_function_names(self):
        """Each call targets the correct Lambda function name."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

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

            update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

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

            update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

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

            update_lambda_functions("b", "company-aws-profile", "eu-west-2")

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

            update_lambda_functions("b", "p", "eu-west-2")

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
                update_lambda_functions("b", "p", "eu-west-2")

            assert exc_info.value.code == 1

    def test_lambda_function_names_constant(self):
        """All expected Lambda function names are present."""
        assert "agent-platform-scheduled-agent-dispatcher" in _LAMBDA_FUNCTION_NAMES
        assert "agent-platform-findings-processor" in _LAMBDA_FUNCTION_NAMES
        assert _OPS_COMPACTION_FUNCTION_NAME == "agent-platform-ops-compaction"
        assert _OPS_COMPACTION_ZIP_KEY == "lambda-packages/ops-compaction.zip"


class TestLambdaScriptsAndSdkConfig:
    """Tests for _LAMBDA_SCRIPTS constants."""

    def test_llm_client_in_lambda_scripts(self):
        """llm_client.py is listed in _LAMBDA_SCRIPTS."""
        assert "llm_client.py" in _LAMBDA_SCRIPTS

    def test_llm_utils_in_lambda_scripts(self):
        """llm_utils.py is listed in _LAMBDA_SCRIPTS."""
        assert "llm_utils.py" in _LAMBDA_SCRIPTS

    def test_tool_runtime_in_lambda_scripts(self):
        """tool_runtime.py is listed in _LAMBDA_SCRIPTS."""
        assert "tool_runtime.py" in _LAMBDA_SCRIPTS

    def test_bedrock_client_in_lambda_scripts(self):
        """bedrock_client.py is listed in _LAMBDA_SCRIPTS."""
        assert "bedrock_client.py" in _LAMBDA_SCRIPTS


class TestBuildAppPackageSdkInstall:
    """Verify Copilot SDK install step is present."""

    def test_build_app_package_installs_copilot_sdk(self, tmp_path):
        """build_app_package calls pip to install github-copilot-sdk."""

        from scripts.build_lambda import build_app_package

        (tmp_path / "app").mkdir()

        sdk_calls: list[list] = []

        def mock_run(cmd, *args, **kwargs):
            sdk_calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch("shutil.copytree"),
            patch("shutil.copy2"),
            patch("scripts.build_lambda.subprocess.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("scripts.build_lambda.OUTPUT_DIR", tmp_path),
            patch(
                "zipfile.ZipFile.__enter__",
                return_value=MagicMock(writestr=MagicMock()),
            ),
            patch("zipfile.ZipFile.__exit__", return_value=False),
            patch("pathlib.Path.rglob", return_value=[]),
            patch("pathlib.Path.mkdir"),
        ):
            with patch("scripts.build_lambda.OUTPUT_DIR", tmp_path):
                build_app_package(tmp_path)

        sdk_install_calls = [c for c in sdk_calls if any("github-copilot-sdk" in str(a) for a in c)]
        assert sdk_install_calls, "Copilot SDK install should be present (reverted from Bedrock migration)"


class TestBuildLambdaConfigScope:
    """Verify Lambda zips contain only config.yaml + lambda/<name>/ (T-1.7)."""

    def _run_build(self, builder_fn_name: str, tmp_path):
        """Run a build function with all IO patched, capturing copy2 and copytree calls."""
        import scripts.build_lambda as bm

        builder = getattr(bm, builder_fn_name)
        copy2_calls: list[tuple] = []
        copytree_calls: list[tuple] = []

        def fake_copy2(src, dst):
            copy2_calls.append((str(src), str(dst)))

        def fake_copytree(src, dst, **kw):
            copytree_calls.append((str(src), str(dst)))

        sdk_mock = MagicMock()
        sdk_mock.returncode = 0

        with (
            patch("shutil.copy2", side_effect=fake_copy2),
            patch("shutil.copytree", side_effect=fake_copytree),
            patch("scripts.build_lambda.subprocess.run", return_value=sdk_mock),
            patch("pathlib.Path.exists", return_value=True),
            patch("scripts.build_lambda.OUTPUT_DIR", tmp_path),
            patch("zipfile.ZipFile.__enter__", return_value=MagicMock(writestr=MagicMock())),
            patch("zipfile.ZipFile.__exit__", return_value=False),
            patch("pathlib.Path.rglob", return_value=[]),
            patch("pathlib.Path.mkdir"),
        ):
            builder(tmp_path)

        return copy2_calls, copytree_calls

    def test_data_pipeline_copies_config_yaml(self, tmp_path):
        """build_app_package copies config.yaml (not blanket config/ tree)."""
        copy2_calls, _ = self._run_build("build_app_package", tmp_path)
        copied_sources = [src for src, _ in copy2_calls]
        assert any("config.yaml" in s and "config.yaml.example" not in s for s in copied_sources)

    def test_data_pipeline_no_blanket_config_copytree(self, tmp_path):
        """build_app_package does NOT call shutil.copytree(ROOT/"config", ...) (T-1.7)."""
        _, copytree_calls = self._run_build("build_app_package", tmp_path)
        for src, _ in copytree_calls:
            assert not src.endswith("/config"), f"Blanket config copytree detected: {src}"
            assert "config/agent" not in src, f"Agent config must not be in Lambda zip: {src}"
            assert "config/data_quality" not in src, f"DQ config must not be in Lambda zip: {src}"

    def test_ops_compaction_copies_config_yaml(self, tmp_path):
        """build_ops_compaction_package copies config.yaml (not blanket config/ tree)."""
        copy2_calls, _ = self._run_build("build_ops_compaction_package", tmp_path)
        copied_sources = [src for src, _ in copy2_calls]
        assert any("config.yaml" in s and "config.yaml.example" not in s for s in copied_sources)

    def test_ops_compaction_no_blanket_config_copytree(self, tmp_path):
        """build_ops_compaction_package does NOT call shutil.copytree(ROOT/"config", ...)."""
        _, copytree_calls = self._run_build("build_ops_compaction_package", tmp_path)
        for src, _ in copytree_calls:
            assert not src.endswith("/config"), f"Blanket config copytree detected: {src}"
            assert "config/agent" not in src, f"Agent config must not be in Lambda zip: {src}"
