"""Tests for scripts/broker_secrets.py -- 100% per-file coverage required.

Covers: phase->account_type mapping, closed-set rejection, unmapped-phase NoBrokerCredentials
sentinel (no raise), routing_table well-formedness (grammar violation, duplicate secret_name,
naming-convention mismatch), _fetch_secret, and _main CLI paths.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.broker_secrets import (
    NoBrokerCredentials,
    _fetch_secret,
    _load_allowed_values,
    _main,
    _validate_routing_table,
    resolve,
)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

# Canonical secret_name literals defined once (DRY) so detect-secrets needs a
# single allowlist pragma per value rather than one per fixture occurrence.
_PAPER_SECRET = "agent-platform-broker-alpaca-paper"  # pragma: allowlist secret
_LIVE_SECRET = "agent-platform-broker-alpaca-live"  # pragma: allowlist secret

_WELL_FORMED_AV: dict[str, Any] = {
    "brokers": ["alpaca"],
    "account_types": ["paper", "live"],
    "product_phase_to_account_type": {
        "paper": "paper",
        "live_small": "live",
        "live_full": "live",
    },
    "routing_table": {
        "broker/alpaca/paper": {
            "secret_name": _PAPER_SECRET,
            "realized": False,
        },
        "broker/alpaca/live": {
            "secret_name": _LIVE_SECRET,
            "realized": False,
        },
    },
}


def _mock_doc(av: dict[str, Any] | None = None) -> MagicMock:
    doc = MagicMock()
    doc.allowed_values = av if av is not None else _WELL_FORMED_AV
    return doc


@pytest.fixture()
def patch_load():
    """Patch load_contract to return a well-formed mock document."""
    with patch("scripts.broker_secrets.load_contract", return_value=_mock_doc()) as m:
        yield m


# ---------------------------------------------------------------------------
# Phase -> account_type mapping
# ---------------------------------------------------------------------------


class TestPhaseToAccountTypeMapping:
    """product_phase_to_account_type drives the correct routing key and secret_name."""

    def test_paper_maps_to_paper_secret(self, patch_load: MagicMock) -> None:
        assert resolve("alpaca", "paper") == _PAPER_SECRET

    def test_live_small_maps_to_live_secret(self, patch_load: MagicMock) -> None:
        assert resolve("alpaca", "live_small") == _LIVE_SECRET

    def test_live_full_maps_to_live_secret(self, patch_load: MagicMock) -> None:
        assert resolve("alpaca", "live_full") == _LIVE_SECRET


# ---------------------------------------------------------------------------
# Unmapped-phase sentinel (must NOT raise)
# ---------------------------------------------------------------------------


class TestUnmappedPhaseSentinel:
    """Phases absent from product_phase_to_account_type return NoBrokerCredentials -- no raise."""

    def test_research_returns_sentinel(self, patch_load: MagicMock) -> None:
        result = resolve("alpaca", "research")
        assert isinstance(result, NoBrokerCredentials)
        assert result.product_phase == "research"

    def test_backtest_canonical_returns_sentinel(self, patch_load: MagicMock) -> None:
        result = resolve("alpaca", "backtest_canonical")
        assert isinstance(result, NoBrokerCredentials)
        assert result.product_phase == "backtest_canonical"

    def test_unmapped_phase_does_not_raise(self, patch_load: MagicMock) -> None:
        result = resolve("alpaca", "backtest_canonical")
        assert isinstance(result, NoBrokerCredentials)

    def test_sentinel_carries_reason(self, patch_load: MagicMock) -> None:
        result = resolve("alpaca", "research")
        assert isinstance(result, NoBrokerCredentials)
        assert result.reason


# ---------------------------------------------------------------------------
# Closed-set rejection
# ---------------------------------------------------------------------------


class TestClosedSetRejection:
    """Unknown broker or account_type from a phase mapping raises ValueError."""

    def test_unknown_broker_raises(self, patch_load: MagicMock) -> None:
        with pytest.raises(ValueError, match="broker 'ibkr' is not in the allowed broker set"):
            resolve("ibkr", "paper")

    def test_mapped_phase_resolving_to_unknown_account_type_raises(self) -> None:
        bad_av = {
            **_WELL_FORMED_AV,
            "product_phase_to_account_type": {"live_small": "unknown_type"},
        }
        with patch("scripts.broker_secrets.load_contract", return_value=_mock_doc(bad_av)):
            with pytest.raises(ValueError, match="account_type 'unknown_type' which is not in the allowed"):
                resolve("alpaca", "live_small")

    def test_routing_key_absent_from_table_raises(self) -> None:
        """A valid (broker, account_type) pair with no routing_table entry raises ValueError."""
        av_missing_entry = {
            **_WELL_FORMED_AV,
            "routing_table": {
                "broker/alpaca/paper": {
                    "secret_name": _PAPER_SECRET,
                },
            },
        }
        with patch("scripts.broker_secrets.load_contract", return_value=_mock_doc(av_missing_entry)):
            with pytest.raises(ValueError, match="routing key 'broker/alpaca/live' not found in routing_table"):
                resolve("alpaca", "live_small")


# ---------------------------------------------------------------------------
# routing_table well-formedness
# ---------------------------------------------------------------------------


class TestRoutingTableWellFormedness:
    """_validate_routing_table enforces grammar, uniqueness, and naming convention."""

    def test_valid_table_passes(self) -> None:
        rt = {
            "broker/alpaca/paper": {"secret_name": _PAPER_SECRET},
            "broker/alpaca/live": {"secret_name": _LIVE_SECRET},
        }
        _validate_routing_table(rt, ["alpaca"], ["paper", "live"])

    def test_grammar_violation_is_rejected(self) -> None:
        rt = {"alpaca/paper": {"secret_name": _PAPER_SECRET}}
        with pytest.raises(ValueError, match="does not match grammar"):
            _validate_routing_table(rt, ["alpaca"], ["paper"])

    def test_duplicate_secret_name_is_rejected(self) -> None:
        rt = {
            "broker/alpaca/paper": {"secret_name": _PAPER_SECRET},
            "broker/alpaca/live": {"secret_name": _PAPER_SECRET},
        }
        with pytest.raises(ValueError, match="duplicated in keys"):
            _validate_routing_table(rt, ["alpaca"], ["paper", "live"])

    def test_naming_convention_mismatch_is_rejected(self) -> None:
        rt = {"broker/alpaca/paper": {"secret_name": "mycompany-broker-alpaca-paper"}}  # pragma: allowlist secret
        with pytest.raises(ValueError, match="does not match naming convention"):
            _validate_routing_table(rt, ["alpaca"], ["paper"])

    def test_missing_secret_name_is_rejected(self) -> None:
        rt = {"broker/alpaca/paper": {"realized": False}}
        with pytest.raises(ValueError, match="missing or empty secret_name"):
            _validate_routing_table(rt, ["alpaca"], ["paper"])

    def test_unknown_broker_in_table_key_is_rejected(self) -> None:
        rt = {"broker/ibkr/paper": {"secret_name": "agent-platform-broker-ibkr-paper"}}  # pragma: allowlist secret
        with pytest.raises(ValueError, match="not in allowed broker set"):
            _validate_routing_table(rt, ["alpaca"], ["paper"])

    def test_unknown_account_type_in_table_key_is_rejected(self) -> None:
        rt = {"broker/alpaca/demo": {"secret_name": "agent-platform-broker-alpaca-demo"}}  # pragma: allowlist secret
        with pytest.raises(ValueError, match="not in allowed account_type set"):
            _validate_routing_table(rt, ["alpaca"], ["paper", "live"])


# ---------------------------------------------------------------------------
# _load_allowed_values error paths
# ---------------------------------------------------------------------------


class TestLoadAllowedValues:
    """_load_allowed_values defers load and surfaces contract errors as RuntimeError."""

    def test_contract_load_failure_raises_runtime_error(self) -> None:
        from scripts.contracts import ContractValidationError

        with patch(
            "scripts.broker_secrets.load_contract",
            side_effect=ContractValidationError("bad yaml"),
        ):
            with pytest.raises(RuntimeError, match="credential-routing contract load failed"):
                _load_allowed_values()

    def test_non_dict_allowed_values_raises_runtime_error(self) -> None:
        doc = MagicMock()
        doc.allowed_values = ["not", "a", "dict"]
        with patch("scripts.broker_secrets.load_contract", return_value=doc):
            with pytest.raises(RuntimeError, match="must be a mapping"):
                _load_allowed_values()


# ---------------------------------------------------------------------------
# _fetch_secret
# ---------------------------------------------------------------------------


class TestFetchSecret:
    """_fetch_secret calls GetSecretValue and parses the JSON string."""

    def test_returns_parsed_json(self) -> None:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": '{"api_key": "k", "api_secret": "s"}'}
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("scripts.broker_secrets.boto3") as mock_boto3:
            mock_boto3.Session.return_value = mock_session
            result = _fetch_secret(_PAPER_SECRET)

        assert result == {"api_key": "k", "api_secret": "s"}

    def test_non_json_secret_returns_raw_dict(self) -> None:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "notjson"}  # pragma: allowlist secret
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("scripts.broker_secrets.boto3") as mock_boto3:
            mock_boto3.Session.return_value = mock_session
            result = _fetch_secret(_PAPER_SECRET)

        assert result == {"raw": "notjson"}


# ---------------------------------------------------------------------------
# _main CLI paths
# ---------------------------------------------------------------------------


class TestCliMain:
    """_main() prints the correct output and returns 0 for all CLI paths."""

    def test_mapped_phase_prints_resolution_and_returns_0(
        self, patch_load: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = _main(["--broker", "alpaca", "--phase", "paper"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "resolved OK" in captured.out
        # Security: the resolved secret_name must not be echoed (CodeQL clear-text-logging).
        assert _PAPER_SECRET not in captured.out

    def test_unmapped_phase_prints_sentinel_and_returns_0(
        self, patch_load: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = _main(["--broker", "alpaca", "--phase", "backtest_canonical"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "NoBrokerCredentials" in captured.out
        assert "backtest_canonical" in captured.out

    def test_fetch_flag_calls_fetch_secret(self, patch_load: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
        mock_secret_data = {"api_key": "PLACEHOLDER", "api_secret": "PLACEHOLDER"}  # pragma: allowlist secret
        with patch("scripts.broker_secrets._fetch_secret", return_value=mock_secret_data) as mock_fetch:
            exit_code = _main(["--broker", "alpaca", "--phase", "paper", "--fetch"])
        assert exit_code == 0
        mock_fetch.assert_called_once_with(_PAPER_SECRET)
        captured = capsys.readouterr()
        # Proves the grant works via a non-sensitive field count -- no keys or values logged.
        assert "fetch OK" in captured.out
        assert "2 field(s)" in captured.out
        assert "api_key" not in captured.out
        assert "PLACEHOLDER" not in captured.out
