# complexity-waiver: decision-43
"""Contract drift gate (CD.25): reject ritual contract YAMLs in docs/contracts/ that violate CD.25."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_contract_drift", owner="platform")
def validate_contract_drift(failed: list[str], contracts_dir: Path | None = None) -> None:
    """Gate on contract drift: reject ritual contract YAMLs in docs/contracts/ that violate CD.25.

    Pass 1 (structural) iterates docs/contracts/*.yaml per file so unparseable YAML is caught as
    a defect (not silently swallowed as load_all_contracts does).  Pass 2 (diff-aware) runs only
    for contracts changed vs the git merge-base and checks amendment-log + status-transition rules.

    contracts_dir: override for test isolation (defaults to ROOT/docs/contracts).
    """
    print("\n=== Contract drift gate (CD.25) ===")

    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    if not target_dir.is_dir():
        print("  No docs/contracts/ directory -- gate skipped.")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)

    error_count_before = len(failed)
    yaml_paths: list[Path] = []
    ritual_contracts: list[tuple[Path, object]] = []

    try:
        import yaml as _yaml

        from scripts.contracts import ContractValidationError, load_contract, resolve_refs
        from scripts.contracts_enforcement import (
            _load_contract_from_text,
            check_amendment_for_diff,
            check_required_inline_fields,
            check_status_transition,
        )

        yaml_paths = sorted(target_dir.glob("*.yaml"))

        # Pass 1: structural validation of all present ritual contracts.
        for p in yaml_paths:
            # yaml.safe_load per file -- an unparseable file is a category-1 defect.
            # load_all_contracts swallows (OSError, yaml.YAMLError) and silently skips such files;
            # the per-file path surfaces them as gate failures.
            try:
                raw_text = p.read_text(encoding="utf-8")
                data = _yaml.safe_load(raw_text)
            except (OSError, _yaml.YAMLError) as exc:
                failed.append(f"Contract drift (cat-1): {p.name}: {exc}")
                continue

            if not isinstance(data, dict):
                failed.append(f"Contract drift (cat-1): {p.name}: not a YAML mapping")
                continue

            # Skip parseable non-ritual docs (e.g. read-engine.yaml, which has `version:` at top level
            # but no `contract:` block with a `class:` field).
            contract_block = data.get("contract")
            if not (isinstance(contract_block, dict) and "class" in contract_block):
                continue

            # load_contract: schema validation (catches cat-1 malformed + cat-8 bad change_class enum)
            try:
                doc = load_contract(p)
            except ContractValidationError as exc:
                failed.append(f"Contract drift (structural): {p.name}: {exc}")
                continue

            # resolve_refs: catches cat-3 ($ref target absent), cat-4 (chain>1), cat-5 (dup inline+ref)
            try:
                resolve_refs(doc, target_dir)
            except ContractValidationError as exc:
                failed.append(f"Contract drift (ref): {p.name}: {exc}")
                continue

            # check_required_inline_fields: cat-2 (inline Class-A field missing required descriptive keys)
            for err in check_required_inline_fields(doc):
                failed.append(f"Contract drift: {p.name}: {err}")

            ritual_contracts.append((p, doc))

        # Pass 2: diff-aware checks (cat-6 amendment log, cat-7 status transition).
        # Scoped to contracts changed vs the git merge-base.  Fails open if the merge-base
        # cannot be resolved (offline / new repo) so Pass 1 still gates unconditionally.
        base_result = _common.run(
            ["git", "merge-base", "origin/main", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=_common.ROOT,
        )
        if base_result.returncode != 0:
            print("  WARNING: merge-base unavailable; Pass 2 (diff checks) skipped -- Pass 1 still ran.")
        else:
            merge_base = base_result.stdout.strip()
            diff_result = _common.run(
                ["git", "diff", "--name-only", f"{merge_base}..HEAD", "--", "docs/contracts/"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=_common.ROOT,
            )
            changed_names = {Path(line.strip()).name for line in diff_result.stdout.splitlines() if line.strip()}

            ritual_by_name = {p.name: (p, doc) for p, doc in ritual_contracts}
            for name, (p, head_doc) in ritual_by_name.items():
                if name not in changed_names:
                    continue
                rel = Path("docs") / "contracts" / name
                show_result = _common.run(
                    ["git", "show", f"{merge_base}:{rel}"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=_common.ROOT,
                )
                if show_result.returncode != 0:
                    continue
                try:
                    base_doc = _load_contract_from_text(show_result.stdout)
                except ContractValidationError:
                    continue
                for err in check_amendment_for_diff(base_doc, head_doc):
                    failed.append(f"Contract drift: {p.name}: {err}")
                for err in check_status_transition(base_doc, head_doc):
                    failed.append(f"Contract drift: {p.name}: {err}")

        new_failures = len(failed) - error_count_before
        if new_failures == 0:
            print(f"  PASS: {len(yaml_paths)} file(s) scanned, {len(ritual_contracts)} ritual contract(s) -- no drift.")
        else:
            print(
                f"  FAIL: {len(yaml_paths)} file(s) scanned, {len(ritual_contracts)} ritual contract(s) -- "
                f"{new_failures} violation(s)."
            )

    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
