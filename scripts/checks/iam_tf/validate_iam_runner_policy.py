from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_iam_runner_policy", owner="platform")
def validate_iam_runner_policy(failed: list[str]) -> None:
    """Verify that all IAM actions in iam_runner_manifest.yaml are present in terraform/ec2_runner.tf.

    Wired into --pre mode: provides a static local gate that ensures infrastructure
    policy stays in sync with code requirements without requiring an AWS connection.
    """
    manifest_path = _common.ROOT / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
    terraform_path = _common.ROOT / "terraform" / "ec2_runner.tf"

    if not manifest_path.exists():
        print(f"SKIPPED: IAM runner manifest missing at {manifest_path}")
        return

    if not terraform_path.exists():
        failed.append(f"IAM runner policy check: {terraform_path} not found")
        return

    import yaml as _yaml

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _yaml.safe_load(f) or {}
    except Exception as exc:
        failed.append(f"IAM runner policy check: Failed to load manifest: {exc}")
        return

    actions = manifest.get("actions", [])
    if not actions:
        return

    try:
        hcl_content = terraform_path.read_text(encoding="utf-8")
    except Exception as exc:
        failed.append(f"IAM runner policy check: Failed to read {terraform_path}: {exc}")
        return

    missing = []
    for entry in actions:
        action = entry.get("action")
        if not action:
            continue
        # Ensure action appears within quotes to prevent partial matches
        if f'"{action}"' not in hcl_content:
            missing.append(action)

    if missing:
        failed.append(f"IAM runner policy check: Missing actions in {terraform_path}: {', '.join(missing)}")
    else:
        print("  PASS: IAM runner policy matches manifest")
