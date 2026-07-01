"""Instruction architecture layer-claims check (instruction-architecture.yaml content_locations)."""

from __future__ import annotations

from scripts.checks import registry
from scripts.checks.contracts._shared import _load_prompt_compliance


@registry.register("validate_instruction_architecture_layers", owner="platform")
def validate_instruction_architecture_layers(failed: list[str]) -> None:
    """Check that every layer in instruction-architecture.yaml resolves to at least one file."""
    print("\n=== Instruction architecture layer claims ===")
    compliance = _load_prompt_compliance()
    if compliance is None:
        print("prompt_compliance.py not found — skipping layer claims check.")
        return

    contract = compliance._load_instruction_architecture()
    violations = compliance.check_layer_compliance(contract)
    if violations:
        print("Layer claims violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Instruction architecture layer claims")
    else:
        layers = contract.get("layers", [])
        print(f"Layer claims: {len(layers)} layer(s) checked, all content_locations resolve.")
