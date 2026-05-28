"""Unit tests for scripts/copilot_sdk_client.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


class TestCopilotSdkInferenceSync:
    """Tests for copilot_sdk_inference_sync()."""

    def _make_sdk_mocks(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        """Return (mock_client_cls, mock_client, mock_session) with realistic attrs."""
        mock_session = MagicMock()
        mock_session.disconnect = AsyncMock()
        response = MagicMock()
        response.data.content = "test output"
        mock_session.send_and_wait = AsyncMock(return_value=response)

        mock_client = MagicMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        mock_client_cls = MagicMock(return_value=mock_client)
        return mock_client_cls, mock_client, mock_session

    def test_happy_path_returns_content(self) -> None:
        """Success: returns content dict with error=False."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()
        mock_permission_handler.approve_all = "approve_all_sentinel"

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            result = copilot_sdk_inference_sync(
                prompt="analyse this",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        assert result == {"content": "test output", "error": False, "message": ""}

    def test_sdk_import_failure_returns_error(self) -> None:
        """When copilot package missing, returns error dict without raising."""
        # Patch away any cached copilot module to simulate ImportError
        with patch.dict("sys.modules", {"copilot": None}):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            result = copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        assert result["error"] is True
        assert "not installed" in result["message"].lower() or "import" in result["message"].lower()
        assert result["content"] == ""

    def test_api_error_returns_error_dict(self) -> None:
        """When session.send_and_wait raises, error dict is returned."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()
        mock_session.send_and_wait = AsyncMock(side_effect=RuntimeError("API error"))

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            result = copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        assert result["error"] is True
        assert "API error" in result["message"]
        assert result["content"] == ""

    def test_timeout_returns_error_dict(self) -> None:
        """TimeoutError from send_and_wait is caught and returned as error."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()
        mock_session.send_and_wait = AsyncMock(side_effect=TimeoutError("timed out"))

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            result = copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        assert result["error"] is True
        assert result["content"] == ""

    def test_client_lifecycle_sequence(self) -> None:
        """client.start(), session.disconnect(), client.stop() called in order."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()
        call_order: list[str] = []

        async def record_start() -> None:
            call_order.append("start")

        async def record_send(*_a: object, **_k: object) -> MagicMock:
            call_order.append("send_and_wait")
            r = MagicMock()
            r.data.content = "ok"
            return r

        async def record_disconnect() -> None:
            call_order.append("disconnect")

        async def record_stop() -> None:
            call_order.append("stop")

        mock_client.start = record_start
        mock_client.stop = record_stop
        mock_session.send_and_wait = record_send
        mock_session.disconnect = record_disconnect

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        assert call_order == ["start", "send_and_wait", "disconnect", "stop"]

    def test_tools_empty_list_enforced(self) -> None:
        """create_session is called with tools=[] to disable agent tool use."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        create_session_call = mock_client.create_session.call_args
        assert create_session_call.kwargs.get("tools") == [] or (
            len(create_session_call.args) > 1 and create_session_call.args[1] == []
        )

    def test_provider_config_passed_to_create_session(self) -> None:
        """provider_config dict is forwarded to create_session as provider= kwarg."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()
        mock_permission_handler.approve_all = "approve_all_sentinel"

        test_provider_cfg = {
            "type": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key": "test-gemini-key",  # pragma: allowlist secret
        }

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            copilot_sdk_inference_sync(
                prompt="Say hello",
                model="gemini-2.0-flash",
                github_token="gho_test",  # pragma: allowlist secret
                provider_config=test_provider_cfg,
            )

        create_session_call = mock_client.create_session.call_args
        assert create_session_call.kwargs.get("provider") == test_provider_cfg

    def test_no_provider_kwarg_when_config_is_none(self) -> None:
        """When provider_config is None, create_session is NOT called with provider=."""
        mock_client_cls, mock_client, mock_session = self._make_sdk_mocks()

        mock_subprocess_config = MagicMock()
        mock_permission_handler = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "copilot": MagicMock(
                    CopilotClient=mock_client_cls,
                    SubprocessConfig=mock_subprocess_config,
                ),
                "copilot.session": MagicMock(PermissionHandler=mock_permission_handler),
            },
        ):
            from scripts.copilot_sdk_client import copilot_sdk_inference_sync

            copilot_sdk_inference_sync(
                prompt="test",
                model="claude-haiku-4.5",
                github_token="ghp_test",  # pragma: allowlist secret
            )

        create_session_call = mock_client.create_session.call_args
        assert "provider" not in create_session_call.kwargs

    def test_module_loads_without_copilot_installed(self) -> None:
        """Module can be imported even if copilot package is absent (no ImportError at top)."""
        # This test verifies the import-safety invariant: importing the module
        # should never raise even if the SDK is not installed.
        import importlib

        with patch.dict("sys.modules", {"copilot": None}):
            # Force reimport to check module-level code
            import scripts.copilot_sdk_client as sdk_mod

            importlib.reload(sdk_mod)
            # Must be importable -- if this line runs, the test passes.
            assert hasattr(sdk_mod, "copilot_sdk_inference_sync")
