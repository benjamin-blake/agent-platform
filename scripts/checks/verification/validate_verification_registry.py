"""Verification registry schema validation (T3.1, Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_verification_registry", owner="platform")
def validate_verification_registry(failed: list[str]) -> None:
    """Validate config/agent/verification_registry/registry.yaml against the CD.29 contract (--pre, T3.1).

    Checks:
    1. Registry file exists.
    2. File is valid YAML with an ``entries`` list.
    3. Every entry's primitive_slot is in CANONICAL_SLOTS.
    4. Every entry carries required fields: check_id, primitive_slot, guard_target, plan_slug, graduated_at.
    5. check_id values are unique within the file.
    """
    print("\n=== Verification registry (T3.1) ===")
    registry_path = _common.ROOT / "config" / "agent" / "verification_registry" / "registry.yaml"
    if not registry_path.exists():
        failed.append("verification-registry: config/agent/verification_registry/registry.yaml not found")
        return

    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        failed.append(f"verification-registry: YAML parse error: {exc}")
        return

    if not isinstance(data, dict) or "entries" not in data:
        failed.append("verification-registry: missing top-level 'entries' key")
        return

    entries = data["entries"] or []
    if not isinstance(entries, list):
        failed.append("verification-registry: 'entries' must be a list")
        return

    # Lazy-import CANONICAL_SLOTS to avoid a module-level import of scripts.verification_checks.
    root_str = str(_common.ROOT)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.verification_checks import CANONICAL_SLOTS  # noqa: PLC0415
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)

    required_fields = {"check_id", "primitive_slot", "guard_target", "plan_slug", "graduated_at"}
    seen_ids: set[str] = set()
    errors: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"  entry[{i}]: not a mapping")
            continue
        missing = required_fields - entry.keys()
        if missing:
            errors.append(f"  entry[{i}] ({entry.get('check_id', '?')}): missing fields: {sorted(missing)}")
        slot = entry.get("primitive_slot")
        if slot is not None and slot not in CANONICAL_SLOTS:
            cid_hint = entry.get("check_id", "?")
            errors.append(f"  entry[{i}] ({cid_hint}): unknown primitive_slot {slot!r} (not in CD.29 vocabulary)")
        cid = entry.get("check_id")
        if cid is not None:
            if cid in seen_ids:
                errors.append(f"  duplicate check_id: {cid!r}")
            seen_ids.add(cid)

    if errors:
        for e in errors:
            print(e)
        failed.append("Verification registry")
    else:
        print(f"  OK: {len(entries)} graduated checks, all valid.")
