"""Broker credential resolver -- T2.14 credential-routing contract codegen follow-on.

Resolves a (broker, product_phase) pair to the AWS Secrets Manager secret_name defined in
docs/contracts/credential-routing.yaml. Unmapped product phases (research, backtest_canonical)
return a NoBrokerCredentials sentinel and never raise -- per the contract spec.

Usage (programmatic)::

    from scripts.broker_secrets import resolve, NoBrokerCredentials

    result = resolve("alpaca", "paper")
    if isinstance(result, NoBrokerCredentials):
        # phase has no broker credential (externals mocked)
        ...
    else:
        # result is the Secrets Manager secret_name
        secret_name: str = result

CLI::

    bin/venv-python -m scripts.broker_secrets --broker alpaca --phase paper
    bin/venv-python -m scripts.broker_secrets --broker alpaca --phase paper --fetch
    bin/venv-python -m scripts.broker_secrets --broker alpaca --phase backtest_canonical
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import boto3

from scripts.contracts import ContractValidationError, load_contract

_CONTRACT_PATH = Path(__file__).parent.parent / "docs" / "contracts" / "credential-routing.yaml"

_GRAMMAR = re.compile(r"^broker/([^/]+)/([^/]+)$")


@dataclass(frozen=True)
class NoBrokerCredentials:
    """Returned for product phases that intentionally carry no broker secret.

    Unmapped phases (research, backtest_canonical) place no real broker orders;
    externals are mocked under these phases, so the closed-set resolver returns this
    sentinel rather than raising. Callers must handle NoBrokerCredentials -- calling
    resolve() for an unmapped phase is a valid no-op, not a caller error.
    """

    product_phase: str
    reason: str = "phase not mapped to a broker account_type (externals mocked; no real orders)"


def _load_allowed_values() -> dict:
    """Load allowed_values from the ratified credential-routing contract.

    Deferred to call time so no exception is raised at module import.
    """
    try:
        doc = load_contract(_CONTRACT_PATH)
    except ContractValidationError as exc:
        raise RuntimeError(f"credential-routing contract load failed: {exc}") from exc
    av = doc.allowed_values
    if not isinstance(av, dict):
        raise RuntimeError(f"credential-routing.yaml allowed_values must be a mapping, got {type(av).__name__}")
    return av


def _validate_routing_table(
    routing_table: dict,
    brokers: list[str],
    account_types: list[str],
) -> None:
    """Enforce routing_table well-formedness per the contract spec.

    Checks (all must pass):
    - Every key matches routing_key_grammar: broker/<broker>/<account_type>
    - Every (broker, account_type) pair is from the closed allowed set
    - secret_names are unique across entries (no two keys resolve to the same secret)
    - Every secret_name conforms to the naming convention agent-platform-broker-<broker>-<account_type>

    Raises ValueError listing all violations if any are found.
    """
    seen_secret_names: dict[str, str] = {}
    errors: list[str] = []

    for key, entry in routing_table.items():
        m = _GRAMMAR.match(str(key))
        if not m:
            errors.append(f"key {key!r} does not match grammar broker/<broker>/<account_type>")
            continue
        broker, account_type = m.group(1), m.group(2)

        if broker not in brokers:
            errors.append(f"key {key!r}: broker {broker!r} not in allowed broker set {brokers}")
        if account_type not in account_types:
            errors.append(f"key {key!r}: account_type {account_type!r} not in allowed account_type set {account_types}")

        secret_name = entry.get("secret_name") if isinstance(entry, dict) else None
        if not secret_name:
            errors.append(f"key {key!r}: missing or empty secret_name")
            continue

        expected_name = f"agent-platform-broker-{broker}-{account_type}"
        if secret_name != expected_name:
            errors.append(
                f"key {key!r}: secret_name {secret_name!r} does not match naming convention (expected {expected_name!r})"
            )

        if secret_name in seen_secret_names:
            errors.append(f"secret_name {secret_name!r} duplicated in keys {seen_secret_names[secret_name]!r} and {key!r}")
        else:
            seen_secret_names[secret_name] = key

    if errors:
        raise ValueError("routing_table well-formedness violations:\n" + "\n".join(f"  - {e}" for e in errors))


def resolve(broker: str, product_phase: str) -> Union[str, NoBrokerCredentials]:
    """Resolve a (broker, product_phase) pair to a Secrets Manager secret_name.

    Loads the ratified docs/contracts/credential-routing.yaml on each call, validates
    routing_table well-formedness, then applies the product_phase -> account_type mapping
    and looks up the routing key.

    Args:
        broker: Registered broker slug (e.g. "alpaca"). Must be in the contract's closed
            brokers set -- an unknown broker raises ValueError.
        product_phase: Active product phase (e.g. "paper", "live_small", "backtest_canonical").
            Mapped to a broker account_type via the contract's product_phase_to_account_type
            table. Unmapped phases (research, backtest_canonical) return NoBrokerCredentials
            without raising. Unknown phases that do map to an invalid account_type raise.

    Returns:
        The Secrets Manager secret_name (str) for mapped phases, or a NoBrokerCredentials
        sentinel for unmapped phases (research, backtest_canonical).

    Raises:
        ValueError: broker not in the closed set; or product_phase maps to an account_type
            not in the contract's closed account_types set; or routing_table is malformed.
        RuntimeError: the credential-routing contract cannot be loaded.
    """
    av = _load_allowed_values()

    brokers: list[str] = av.get("brokers", [])
    account_types: list[str] = av.get("account_types", [])
    phase_map: dict[str, str] = av.get("product_phase_to_account_type", {})
    routing_table: dict = av.get("routing_table", {})

    _validate_routing_table(routing_table, brokers, account_types)

    if broker not in brokers:
        raise ValueError(
            f"broker {broker!r} is not in the allowed broker set {brokers}; "
            "add it to docs/contracts/credential-routing.yaml first"
        )

    if product_phase not in phase_map:
        return NoBrokerCredentials(product_phase=product_phase)

    account_type = phase_map[product_phase]

    if account_type not in account_types:
        raise ValueError(
            f"product_phase {product_phase!r} maps to account_type {account_type!r} "
            f"which is not in the allowed account_type set {account_types}"
        )

    routing_key = f"broker/{broker}/{account_type}"
    entry = routing_table.get(routing_key)
    if entry is None:
        raise ValueError(
            f"routing key {routing_key!r} not found in routing_table; add it to docs/contracts/credential-routing.yaml"
        )

    secret_name: str = entry.get("secret_name") if isinstance(entry, dict) else str(entry)
    return secret_name


def _fetch_secret(secret_name: str, profile: str = "agent_platform") -> dict:
    """Fetch the secret value from Secrets Manager using the given AWS profile.

    Used by the --fetch CLI flag for V3 verification (VP step 8).
    """
    session = boto3.Session(profile_name=profile)
    client = session.client("secretsmanager", region_name="eu-west-2")
    response = client.get_secret_value(SecretId=secret_name)
    secret_str = response.get("SecretString", "")
    try:
        return json.loads(secret_str)
    except json.JSONDecodeError:
        return {"raw": secret_str}


def _main(argv: list[str] | None = None) -> int:
    """CLI entry point -- separated from __main__ for 100% testability."""
    parser = argparse.ArgumentParser(description="Resolve broker credentials via the credential-routing contract (T2.14).")
    parser.add_argument("--broker", required=True, help="Broker slug (e.g. alpaca)")
    parser.add_argument(
        "--phase",
        required=True,
        help="Product phase (e.g. paper, live_small, live_full, backtest_canonical, research)",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "Fetch the secret value from Secrets Manager via the agent_platform (PlatformDev) "
            "profile -- proves the BrokerCredentialsRead IAM grant end-to-end (VP step 8)."
        ),
    )
    args = parser.parse_args(argv)

    result = resolve(args.broker, args.phase)

    if isinstance(result, NoBrokerCredentials):
        print(f"NoBrokerCredentials: phase={result.product_phase!r} -- {result.reason}")
        return 0

    print(f"secret_name: {result}")

    if args.fetch:
        secret_data = _fetch_secret(result)
        print(f"secret_value keys: {list(secret_data.keys())}")
        print(json.dumps(secret_data, indent=2))

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
