"""Verification registry schema validation (T3.1, Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


def _entries_at_ref(ref: str) -> list[dict]:
    """Read config/agent/verification_registry/registry.yaml 'entries' at git ref `ref`.

    Returns [] when the file (or the ref) doesn't resolve -- treated as an empty baseline.
    """
    result = _common.run(
        ["git", "show", f"{ref}:config/agent/verification_registry/registry.yaml"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode != 0:
        return []
    import yaml as _yaml  # noqa: PLC0415

    try:
        data = _yaml.safe_load(result.stdout)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("entries") or []
    return entries if isinstance(entries, list) else []


def _added_entries(current_entries: list[dict]) -> list[dict]:
    """Entries present now but absent from origin/main, matched by check_id (VF-06 c2)."""
    baseline_ids = {e.get("check_id") for e in _entries_at_ref("origin/main") if isinstance(e, dict)}
    return [e for e in current_entries if isinstance(e, dict) and e.get("check_id") not in baseline_ids]


def _run_added_entry_differentials(added: list[dict], failed: list[str]) -> None:
    """VF-06 c2: for each entry added in this diff, run the REAL differential admission gate.

    Materializes each entry's check_spec and asserts it FAILS on origin/main (real git worktree
    revert) and PASSES on HEAD/live. Refuses tautological/non-admitted outcomes and any
    materialize/worktree/revert error with a clear failure message (Decision 55 fail-loud) --
    never a silent pass.
    """
    print(f"  Differential admission gate: {len(added)} newly-added entr{'y' if len(added) == 1 else 'ies'} in this diff.")

    root_str = str(_common.ROOT)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts import verification_graduation as _vg  # noqa: PLC0415
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)

    for row in added:
        cid = row.get("check_id", "?")
        try:
            outcome = _vg.run_differential(row, repo_root=_common.ROOT)
        except _vg.GraduationError as exc:
            failed.append(f"verification-registry differential: check_id={cid}: error -- {exc}")
            continue
        if outcome.skipped:
            print(f"    skipped (non-fatal): {cid} ({outcome.reason})")
        elif not outcome.admitted:
            failed.append(f"verification-registry differential: check_id={cid}: not admitted -- {outcome.reason}")
        else:
            print(f"    admitted: {cid} ({outcome.reason})")


def _schema_errors(entries: list, canonical_slots: frozenset[str]) -> list[str]:
    """Per-entry schema checks: required fields, known primitive_slot, unique check_id."""
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
        if slot is not None and slot not in canonical_slots:
            cid_hint = entry.get("check_id", "?")
            errors.append(f"  entry[{i}] ({cid_hint}): unknown primitive_slot {slot!r} (not in CD.29 vocabulary)")
        cid = entry.get("check_id")
        if cid is not None:
            if cid in seen_ids:
                errors.append(f"  duplicate check_id: {cid!r}")
            seen_ids.add(cid)
    return errors


@registry.register("validate_verification_registry", owner="platform")
def validate_verification_registry(failed: list[str]) -> None:
    """Validate config/agent/verification_registry/registry.yaml against the CD.29 contract (--pre, T3.1).

    Checks:
    1. Registry file exists.
    2. File is valid YAML with an ``entries`` list.
    3. Every entry's primitive_slot is in CANONICAL_SLOTS.
    4. Every entry carries required fields: check_id, primitive_slot, guard_target, plan_slug, graduated_at.
    5. check_id values are unique within the file.
    6. VF-06 c2: entries ADDED in this diff pass the REAL differential admission gate (git-worktree
       revert against origin/main) -- diff-gated no-op when no entry was added.
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

    errors = _schema_errors(entries, CANONICAL_SLOTS)

    if errors:
        for e in errors:
            print(e)
        failed.append("Verification registry")
        return

    print(f"  OK: {len(entries)} graduated checks, all valid.")

    added = _added_entries(entries)
    if added:
        _run_added_entry_differentials(added, failed)
