"""Deploy-channel conformance staleness gate (Decision 104, Decision 125/126).

Compares the ACTUAL terraform/personal state (does each Lambda's aws_lambda_function resource
carry lifecycle { ignore_changes = [source_code_hash] }?) against the textual SoT surfaces that
describe it -- docs/contracts/build-lambda.yaml's deploy_channels + docs/contracts/
environment-taxonomy.md section 5's conformance-status paragraph(s) -- and fails if either has
drifted from reality. This is the guard against the #544 drift class: the code shipped decoupled
but the docs kept describing it as coupled.

Covers TWO classes, each with its own actual-state scan + taxonomy paragraph (T2.43 extension):
  - ducklake (terraform/personal/ducklake*.tf; build-lambda.yaml deploy_channels.ducklake_functions;
    environment-taxonomy.md's "**Conformance status" paragraph -- the ORIGINAL, unwidened check).
  - prod (terraform/personal/prod_lambdas.tf; build-lambda.yaml deploy_channels.prod_functions /
    .ops_compaction; environment-taxonomy.md's second "**Conformance status (prod class"
    paragraph). The prod class additionally gets a completeness check (governed_channel +
    break_glass_only both populated) since its channel_class value
    ("decoupled_build_pipeline") does not use the ducklake class's _decoupled/_coupled suffix
    convention, so there is no channel_class-vs-actual comparison to make for it.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry

_DUCKLAKE_TF_GLOB = "ducklake*.tf"
_PROD_TF_GLOB = "prod_lambdas.tf"
_IGNORE_CHANGES_RE = re.compile(r"ignore_changes\s*=\s*\[[^\]]*source_code_hash[^\]]*\]")
_FUNCTION_BLOCK_RE = re.compile(r'resource\s+"aws_lambda_function"\s+"(\w+)"\s*\{')

# The prod class's conformance paragraph is worded distinctly ("(prod class") so this marker
# never collides with the ducklake paragraph's plain "**Conformance status" marker below --
# re.search always returns the FIRST match, and the ducklake paragraph is written earlier in
# section 5, so the unqualified ducklake marker keeps resolving to the ducklake paragraph
# regardless of where the prod paragraph sits.
_DUCKLAKE_TAXONOMY_MARKER = r"\*\*Conformance status"
_PROD_TAXONOMY_MARKER = r"\*\*Conformance status \(prod class"

_PROD_CHANNEL_KEYS = ("prod_functions", "ops_compaction")


def _extract_function_blocks(text: str) -> dict[str, str]:
    """Return {resource_name: block_text} for every aws_lambda_function resource, via
    brace-depth counting from the opening brace (regex alone cannot match nested braces)."""
    blocks: dict[str, str] = {}
    for match in _FUNCTION_BLOCK_RE.finditer(text):
        name = match.group(1)
        start = match.end() - 1
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        blocks[name] = text[start : i + 1]
    return blocks


def _actual_decoupled_state(
    failed: list[str],
    glob_pattern: str = _DUCKLAKE_TF_GLOB,
    class_label: str = "ducklake",
) -> bool | None:
    """Scan terraform/personal/<glob_pattern> for aws_lambda_function resources.

    Generalised (T2.43) via glob_pattern + class_label so the same scan logic serves both the
    ducklake class (default args, unchanged behaviour) and the prod class
    (glob_pattern=_PROD_TF_GLOB, class_label="prod").

    Returns True if every found function is decoupled (ignore_changes=[source_code_hash]),
    False if every found function is coupled (none carry it), or None (with a failure
    appended) if no functions were found or the state is a partial/mixed rollout --
    neither is a state the two textual SoT surfaces can validly agree with.
    """
    personal_dir = _common.ROOT / "terraform" / "personal"
    decoupled_count = 0
    total_count = 0
    for tf_path in sorted(personal_dir.glob(glob_pattern)):
        try:
            text = tf_path.read_text(encoding="utf-8")
        except OSError as exc:
            failed.append(f"Deploy-channel conformance: cannot read {tf_path}: {exc}")
            return None
        for _name, block in _extract_function_blocks(text).items():
            total_count += 1
            if _IGNORE_CHANGES_RE.search(block):
                decoupled_count += 1

    if total_count == 0:
        failed.append(
            f"Deploy-channel conformance: no aws_lambda_function resources found under "
            f"{personal_dir}/{glob_pattern} -- cannot determine actual {class_label} coupling state."
        )
        return None
    if 0 < decoupled_count < total_count:
        failed.append(
            f"Deploy-channel conformance: {decoupled_count}/{total_count} {class_label} "
            "aws_lambda_function resources carry ignore_changes=[source_code_hash] -- "
            "partial rollout is not a state either textual SoT can validly describe."
        )
        return None
    return decoupled_count == total_count


def _doc_state_from_channel_class(failed: list[str]) -> bool | None:
    """Parse build-lambda.yaml's deploy_channels.ducklake_functions.channel_class.

    Returns True for a channel_class ending in '_decoupled', False for one ending in
    '_coupled' (checked in that order since 'decoupled' ends in 'coupled' as a
    substring -- the '_decoupled' suffix match must run first), or None (with a
    failure appended) on a missing/unparseable/unrecognised value.
    """
    import yaml as _yaml  # noqa: PLC0415

    path = _common.ROOT / "docs" / "contracts" / "build-lambda.yaml"
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, _yaml.YAMLError) as exc:
        failed.append(f"Deploy-channel conformance: cannot read/parse {path}: {exc}")
        return None
    channel_class = (
        (data or {}).get("deploy_channels", {}).get("ducklake_functions", {}).get("channel_class")
        if isinstance(data, dict)
        else None
    )
    if not isinstance(channel_class, str) or not channel_class:
        failed.append(f"Deploy-channel conformance: {path} missing deploy_channels.ducklake_functions.channel_class.")
        return None
    if channel_class.endswith("_decoupled"):
        return True
    if channel_class.endswith("_coupled"):
        return False
    failed.append(
        f"Deploy-channel conformance: {path} channel_class {channel_class!r} does not end in "
        "'_coupled' or '_decoupled' -- cannot determine claimed state."
    )
    return None


def _prod_channels_complete(failed: list[str]) -> bool:
    """Parse build-lambda.yaml's deploy_channels.prod_functions / .ops_compaction for
    governed_channel + break_glass_only completeness.

    The prod class's channel_class ("decoupled_build_pipeline") does not use the ducklake
    class's _decoupled/_coupled suffix convention, so there is no channel_class-vs-actual
    coupling comparison to make for it (unlike _doc_state_from_channel_class above) -- this
    checks field COMPLETENESS instead: both governed_channel and break_glass_only must be
    populated for each of the two prod-class deploy_channels entries. Returns True iff both
    entries are complete; appends a failure (and returns False) for each incomplete entry.
    """
    import yaml as _yaml  # noqa: PLC0415

    path = _common.ROOT / "docs" / "contracts" / "build-lambda.yaml"
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, _yaml.YAMLError) as exc:
        failed.append(f"Deploy-channel conformance: cannot read/parse {path}: {exc}")
        return False

    channels = (data or {}).get("deploy_channels", {}) if isinstance(data, dict) else {}
    complete = True
    for key in _PROD_CHANNEL_KEYS:
        entry = channels.get(key) if isinstance(channels, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        if not entry.get("governed_channel") or not entry.get("break_glass_only"):
            failed.append(
                f"Deploy-channel conformance: {path} deploy_channels.{key} missing governed_channel and/or break_glass_only."
            )
            complete = False
    return complete


def _taxonomy_state(
    failed: list[str],
    marker: str = _DUCKLAKE_TAXONOMY_MARKER,
    label: str = "ducklake",
) -> bool | None:
    """Parse environment-taxonomy.md for a '<marker>' paragraph (scoped narrower than all of
    section 5, which may legitimately discuss layers' coupling separately) for a whole-word
    DECOUPLED or COUPLED marker. Word-boundary matching means \\bCOUPLED\\b does not
    false-positive inside DECOUPLED (no boundary between the 'E' and 'C').

    Generalised (T2.43) via marker + label so the same paragraph-parsing logic serves both the
    ducklake class (default args, unchanged behaviour) and the prod class
    (marker=_PROD_TAXONOMY_MARKER, label="prod")."""
    path = _common.ROOT / "docs" / "contracts" / "environment-taxonomy.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"Deploy-channel conformance: cannot read {path}: {exc}")
        return None

    para_match = re.search(marker + r".*?(?=\n\n|\Z)", text, re.DOTALL)
    if not para_match:
        failed.append(f"Deploy-channel conformance: {path} has no '{label}' conformance-status paragraph.")
        return None
    paragraph = para_match.group(0)

    has_decoupled = re.search(r"\bDECOUPLED\b", paragraph) is not None
    has_coupled = re.search(r"\bCOUPLED\b", paragraph) is not None
    if has_decoupled and has_coupled:
        failed.append(
            f"Deploy-channel conformance: {path} {label} conformance-status paragraph contains both "
            "DECOUPLED and COUPLED markers -- ambiguous conformance status."
        )
        return None
    if has_decoupled:
        return True
    if has_coupled:
        return False
    failed.append(f"Deploy-channel conformance: {path} {label} conformance-status paragraph has no DECOUPLED/COUPLED marker.")
    return None


@registry.register("validate_deploy_channel_conformance", owner="platform")
def validate_deploy_channel_conformance(failed: list[str]) -> None:
    """Fail if build-lambda.yaml or environment-taxonomy.md disagree with the actual
    terraform/personal ignore_changes=[source_code_hash] state, for EITHER the ducklake class or
    the prod class (T2.43 -- closes the ducklake-only blind spot)."""
    print("\n=== Deploy-channel conformance gate (Decision 125/126) ===")

    pre_count = len(failed)

    # --- ducklake class (original check, unwidened) ---
    actual = _actual_decoupled_state(failed)
    doc_state = _doc_state_from_channel_class(failed)
    taxonomy_state = _taxonomy_state(failed)

    if actual is not None and doc_state is not None and taxonomy_state is not None:
        if doc_state != actual:
            failed.append(
                "Deploy-channel conformance: build-lambda.yaml channel_class claims "
                f"{'decoupled' if doc_state else 'coupled'} but terraform/personal is actually "
                f"{'decoupled' if actual else 'coupled'} -- update deploy_channels.ducklake_functions.channel_class."
            )
        if taxonomy_state != actual:
            failed.append(
                "Deploy-channel conformance: environment-taxonomy.md section 5 claims "
                f"{'DECOUPLED' if taxonomy_state else 'COUPLED'} but terraform/personal is actually "
                f"{'decoupled' if actual else 'coupled'} -- update the conformance-status paragraph."
            )

    # --- prod class (T2.43 extension) ---
    actual_prod = _actual_decoupled_state(failed, glob_pattern=_PROD_TF_GLOB, class_label="prod")
    prod_taxonomy_state = _taxonomy_state(failed, marker=_PROD_TAXONOMY_MARKER, label="prod")
    _prod_channels_complete(failed)

    if actual_prod is not None and prod_taxonomy_state is not None and prod_taxonomy_state != actual_prod:
        failed.append(
            "Deploy-channel conformance: environment-taxonomy.md section 5's prod-class paragraph "
            f"claims {'DECOUPLED' if prod_taxonomy_state else 'COUPLED'} but terraform/personal is "
            f"actually {'decoupled' if actual_prod else 'coupled'} -- update the prod conformance-status paragraph."
        )

    if len(failed) == pre_count:
        print(
            "  PASS: docs and terraform/personal agree "
            f"(ducklake: {'decoupled' if actual else 'coupled'}; prod: {'decoupled' if actual_prod else 'coupled'})."
        )
