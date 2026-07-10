"""Per-bundle CI-RCA fingerprint dedup decision (CIRCA-03(b), Decision 55 fail-closed).

Single implementation, two callers -- mirrors ghas-probe's "single probe implementation,
multiple callers" invariant: .github/workflows/ci-rca.yml's fp_dedup step (the real dedup
gate) and .github/workflows/dedup-probe.yml's synthetic self-test both invoke decide() (or
this module's CLI) so the decision logic is unit-testable instead of living in untested
workflow shell.

Per-bundle, not all-or-nothing (the bug this replaces): the prior inline shell loop set
DEDUPED=true only if EVERY bundle matched an open rec, and `break`-ed on the first non-match --
so a single spurious/novel bundle skipped bumping every OTHER bundle that DID match an open rec.
Here each bundle's fingerprint is resolved independently: a matched-open bundle is skipped and
its rec's occurrence bumped regardless of what any other bundle in the same run resolved to; a
genuinely-novel or fingerprint-less bundle always contributes to running the agent (Decision 55
-- dedup never silently swallows an undiagnosed failure). The overall run-agent decision is the
OR of every bundle's individual verdict.

CLI usage (invoked by the workflow):
    bin/venv-python -m scripts.ci_rca.dedup --bundles-dir /tmp/ci-rca-bundles [--force-rca]
Prints one line per bundle verdict, then `deduped=true|false` for the workflow to capture.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

FinderFn = Callable[[str], Optional[str]]
BumperFn = Callable[[str], None]


@dataclass
class BundleVerdict:
    fingerprint: str
    matched_rec_id: Optional[str]
    run_agent: bool


@dataclass
class DedupResult:
    run_agent: bool
    verdicts: list[BundleVerdict] = field(default_factory=list)
    force_rca: bool = False

    @property
    def deduped(self) -> bool:
        return not self.run_agent


def _default_finder(fingerprint: str, profile: Optional[str] = None) -> Optional[str]:
    from scripts.ops_portal.ci_rca_runtime import find_open_ci_rca_rec_by_fingerprint  # noqa: PLC0415

    return find_open_ci_rca_rec_by_fingerprint(fingerprint, profile=profile)


def _default_bumper(rec_id: str, profile: Optional[str] = None) -> None:
    from scripts.ops_portal.ci_rca_runtime import bump_ci_rca_occurrence  # noqa: PLC0415

    bump_ci_rca_occurrence(rec_id, profile=profile)


def decide(
    fingerprints: list[str],
    *,
    force_rca: bool = False,
    finder: Optional[FinderFn] = None,
    bumper: Optional[BumperFn] = None,
    profile: Optional[str] = None,
) -> DedupResult:
    """Per-bundle dedup decision over a run's evidence-bundle fingerprints.

    Args:
        fingerprints: One fingerprint string per emitted evidence bundle for this run
            (empty string for a bundle with no fingerprint -- treated as novel/fail-closed).
        force_rca: CIRCA-03(c) / Decision 74 dedup-bypass. Bypasses ALL lookups and always
            runs the agent -- mirrors the fp_dedup step's `force_rca` input.
        finder: Injected callable(fingerprint) -> rec_id | None. Defaults to the real
            DuckLake-backed lookup (find_open_ci_rca_rec_by_fingerprint).
        bumper: Injected callable(rec_id) -> None. Defaults to the real occurrence bump
            (bump_ci_rca_occurrence). Called once per matched bundle.
        profile: AWS profile override for the default finder/bumper.

    Returns:
        DedupResult.run_agent is True (deduped is False) iff force_rca, no fingerprints were
        supplied at all (zero evidence -- fail closed), or ANY bundle's fingerprint is missing
        or has no open-rec match. A matched bundle's rec is bumped as a side effect via bumper.
    """
    if force_rca:
        return DedupResult(run_agent=True, verdicts=[], force_rca=True)

    if not fingerprints:
        return DedupResult(run_agent=True, verdicts=[])

    resolved_finder: FinderFn = finder or (lambda fp: _default_finder(fp, profile=profile))
    resolved_bumper: BumperFn = bumper or (lambda rec_id: _default_bumper(rec_id, profile=profile))

    verdicts: list[BundleVerdict] = []
    any_novel = False
    for fp in fingerprints:
        if not fp:
            verdicts.append(BundleVerdict(fingerprint=fp, matched_rec_id=None, run_agent=True))
            any_novel = True
            continue
        rec_id = resolved_finder(fp)
        if rec_id:
            resolved_bumper(rec_id)
            verdicts.append(BundleVerdict(fingerprint=fp, matched_rec_id=rec_id, run_agent=False))
        else:
            verdicts.append(BundleVerdict(fingerprint=fp, matched_rec_id=None, run_agent=True))
            any_novel = True

    return DedupResult(run_agent=any_novel, verdicts=verdicts)


def _load_fingerprints(bundles_dir: Path) -> list[str]:
    fingerprints: list[str] = []
    for f in sorted(bundles_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not parse bundle %s: %s", f, exc)
            fingerprints.append("")
            continue
        fingerprints.append(str(data.get("fingerprint") or ""))
    return fingerprints


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Per-bundle CI-RCA fingerprint dedup decision.")
    parser.add_argument("--bundles-dir", type=Path, required=True, help="Directory of emitted evidence bundle JSONs")
    parser.add_argument("--force-rca", action="store_true", help="Bypass dedup entirely (Decision 74)")
    parser.add_argument("--profile", default=None, help="AWS profile override")
    args = parser.parse_args(argv)

    fingerprints = _load_fingerprints(args.bundles_dir) if args.bundles_dir.exists() else []
    result = decide(fingerprints, force_rca=args.force_rca, profile=args.profile)

    if result.force_rca:
        print("force_rca=true; bypassing fingerprint dedup.")
    elif not fingerprints:
        print("No evidence bundles found; running agent.")
    for v in result.verdicts:
        if v.matched_rec_id:
            print(f"Fingerprint {v.fingerprint} matches open {v.matched_rec_id}; bumped occurrence.")
        elif v.fingerprint:
            print(f"Fingerprint {v.fingerprint} has no open match; running agent.")
        else:
            print("Bundle has no fingerprint; running agent.")

    print(f"deduped={'true' if result.deduped else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
