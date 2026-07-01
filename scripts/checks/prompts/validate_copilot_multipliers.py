from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_copilot_multipliers", owner="platform")
def validate_copilot_multipliers(failed: list[str]) -> None:
    """Validate copilot_model_multipliers.yaml integrity and structure."""
    print("\n=== Copilot multipliers validation ===")

    import yaml

    config_path = _common.ROOT / "config" / "agent" / "copilot" / "model_multipliers.yaml"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        failed.append("Copilot multipliers validation")
        return

    try:
        content = config_path.read_text(encoding="utf-8")
        config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML in {config_path}: {e}")
        failed.append("Copilot multipliers validation")
        return
    except Exception as e:
        print(f"ERROR: Failed to read {config_path}: {e}")
        failed.append("Copilot multipliers validation")
        return

    errors: list[str] = []

    if not isinstance(config, dict):
        errors.append("Config is not a YAML dict")
    else:
        metadata = config.get("metadata", {})
        if not isinstance(metadata, dict):
            errors.append("metadata field is not a dict")
        else:
            for required_field in ("source_url", "last_verified", "next_review"):
                if required_field not in metadata:
                    errors.append(f"Missing metadata field: {required_field}")

        default_mult = config.get("default_multiplier")
        if default_mult is None:
            errors.append("Missing default_multiplier field")
        elif not isinstance(default_mult, (int, float)) or (isinstance(default_mult, bool)):
            errors.append(f"default_multiplier must be numeric, got {default_mult}")

        multipliers = config.get("multipliers", {})
        if not isinstance(multipliers, dict):
            errors.append("multipliers field is not a dict")
        else:
            for model_name, multiplier_value in multipliers.items():
                if not isinstance(multiplier_value, (int, float)) or isinstance(multiplier_value, bool):
                    errors.append((f"Model {model_name}: multiplier must be numeric, got {multiplier_value}"))
                elif not (0.0 <= multiplier_value <= 30.0):
                    errors.append((f"Model {model_name}: multiplier {multiplier_value} out of range (0.0 - 30.0)"))

    if errors:
        print("Copilot multipliers validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Copilot multipliers validation")
    else:
        print(
            f"Copilot multipliers config valid: "
            f"{len(config.get('multipliers', {}))} models, "
            f"default multiplier={config.get('default_multiplier')}"
        )
