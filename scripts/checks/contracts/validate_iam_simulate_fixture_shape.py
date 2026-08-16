"""iam-simulate-fixture shape check (rec-3059 second-wave enforcer build).

Asserts docs/contracts/iam-simulate-fixture.yaml passes scripts/ci/iam_simulate.py's PURE
(AWS-free) validation layer -- load_fixture, build_triples, principal_arn -- against
NON-NUMERIC dummy placeholders (Decision 101: never a real 12-digit account id in this PUBLIC
repo), plus two parity legs the pre-existing tests lacked: expected_decision_values must equal
VALID_DECISIONS, and the fixture's declared `placeholders:` keys must equal the token set
scripts.ci.iam_simulate.resolve_placeholders actually substitutes (`account_id`, `region`).

SCOPE BOUNDARY (deliberate, load-bearing): this check NEVER touches AWS, never invokes boto3,
and never asserts a LIVE `iam:SimulatePrincipalPolicy` decision or condition-key/
identity-boundary-intersection semantics -- that is scripts/ci/iam_simulate.py's own POST-APPLY
runner, invoked out-of-band (docs/contracts/deploy-paths.yaml#admin_out_of_band.procedure), never
--pre or full-tier. Between merge and the human-gated bootstrap apply the fixture legitimately
declares verbs the live policy does not yet have; wiring a live assertion into this check would
red the very PR that fixes a legitimate gap. Do NOT "strengthen" this into a live assertion.

Deliberately NOT a leg asserting every triple's `expected_decision` is drawn from
expected_decision_values: build_triples() already rejects any value outside VALID_DECISIONS, and
the expected_decision_values-equals-VALID_DECISIONS leg above pins the declared list TO
VALID_DECISIONS -- a third leg re-asserting the same fact per-triple would be tautological, never
able to fail independently of the first two.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_NAME = "iam-simulate-fixture.yaml"

# Non-numeric dummies (Decision 101 PUBLIC-repo boundary): a literal 12-digit account id would
# trip the pre-commit never-commit hook. These never reach AWS -- load_fixture/build_triples/
# principal_arn are pure string substitution, no network, no credentials.
_DUMMY_ACCOUNT_ID = "account-id-placeholder"
_DUMMY_REGION = "region-placeholder"

# Mirrors scripts.ci.iam_simulate.resolve_placeholders's two HARDCODED substitution tokens
# (`${account_id}`, `${region}`) -- the fixture's own `placeholders:` block is documentation, not
# a data source the runner reads, so this check independently pins what the runner actually does.
_SUBSTITUTED_TOKENS = frozenset({"account_id", "region"})


@registry.register("validate_iam_simulate_fixture_shape", owner="platform")
def validate_iam_simulate_fixture_shape(failed: list[str], *, contracts_dir: Path | None = None) -> None:
    """Fail if iam-simulate-fixture.yaml does not pass iam_simulate's pure validation layer, or
    if expected_decision_values / declared placeholders drift from the runner's own vocabulary."""
    from scripts.ci.iam_simulate import (  # noqa: PLC0415 -- lazy so registry.all_checks() stays cheap
        VALID_DECISIONS,
        build_triples,
        load_fixture,
        principal_arn,
    )

    print("\n=== iam-simulate-fixture shape ===")
    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    path = target_dir / _CONTRACT_NAME

    if not path.is_file():
        failed.append(f"iam-simulate-fixture shape: {path} not found")
        registry.skipped(f"{_CONTRACT_NAME} not found")
        return

    try:
        data = load_fixture(path)
        triples = build_triples(data, _DUMMY_ACCOUNT_ID, _DUMMY_REGION)
        principal_arn(data, _DUMMY_ACCOUNT_ID, _DUMMY_REGION)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        failed.append(f"iam-simulate-fixture shape: {path} failed the pure validation layer: {exc}")
        registry.skipped(f"{_CONTRACT_NAME} failed pure validation")
        return

    error_count_before = len(failed)

    declared_decisions = data.get("expected_decision_values")
    if not isinstance(declared_decisions, list) or not declared_decisions:
        failed.append(f"iam-simulate-fixture shape: {_CONTRACT_NAME} missing or empty 'expected_decision_values'")
    elif set(declared_decisions) != set(VALID_DECISIONS):
        failed.append(
            f"iam-simulate-fixture shape: {_CONTRACT_NAME} expected_decision_values "
            f"{sorted(declared_decisions)} does not equal iam_simulate.VALID_DECISIONS {sorted(VALID_DECISIONS)}"
        )

    declared_placeholders = data.get("placeholders")
    if not isinstance(declared_placeholders, dict) or not declared_placeholders:
        failed.append(f"iam-simulate-fixture shape: {_CONTRACT_NAME} missing or empty 'placeholders'")
    elif set(declared_placeholders) != _SUBSTITUTED_TOKENS:
        failed.append(
            f"iam-simulate-fixture shape: {_CONTRACT_NAME} placeholders keys {sorted(declared_placeholders)} "
            f"does not equal the runner's substituted token set {sorted(_SUBSTITUTED_TOKENS)}"
        )

    registry.examined(len(triples), unit="triples")

    if len(failed) == error_count_before:
        print(f"  PASS: {_CONTRACT_NAME} passes the pure validation layer ({len(triples)} triples).")
