# complexity-waiver: decision-43
"""Argparse CLI for the ops data portal.

Owner-concern: the argparse surface only. Every flag, argument group, error string, and
exit code is byte-identical to the pre-decomposition monolith (the Single Portal CLI
contract). Cross-module verb calls use FUNCTION-LOCAL imports from scripts.ops_data_portal
(the facade) INSIDE main() -- a module-level import here would bind at load time and
defeat facade patches for CLI-driven tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for the ops data portal."""
    from scripts.ops_data_portal import (
        _CI_RCA_BACK_VALIDATE_DEFAULT_SINCE,
        _print_ci_rca_back_validation_report,
        back_validate_ci_rca,
        backfill_decisions_from_md,
        bump_ci_rca_occurrence,
        enqueue_findings,
        file_decision,
        file_rec,
        find_open_ci_rca_rec_by_fingerprint,
        purge_postmortems_for,
        selftest_read,
        selftest_roundtrip,
        sync,
        update_decision,
        update_rec,
    )

    parser = argparse.ArgumentParser(
        description="Unified gateway for filing and updating recommendations and decisions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--profile", metavar="AWS_PROFILE", default=None, help="AWS profile override")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview purge without writing (use with --purge-postmortems-for)"
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--file-rec", action="store_true", help="File a new recommendation")
    action.add_argument("--update-rec", metavar="REC_ID", help="Update an existing recommendation")
    action.add_argument("--file-decision", action="store_true", help="File a new decision")
    action.add_argument(
        "--update-decision", metavar="DECISION_ID", type=str, help="Update an existing decision (e.g. dec-072)"
    )
    action.add_argument(
        "--purge-postmortems-for", metavar="REC_ID", help="Supersede all executor postmortems for REC_ID (SCD2)"
    )
    action.add_argument(
        "--backfill-decisions-md",
        action="store_true",
        help="ETL DECISIONS.md -> ops_decisions on DuckLake (idempotent caller-keyed upsert)",
    )
    action.add_argument(
        "--enqueue-findings",
        metavar="PATH",
        help="Bulk-enqueue findings from a JSONL file into ops_recommendations",
    )
    action.add_argument(
        "--guidance",
        action="store_true",
        help="Print field semantics and registered source values as YAML, then exit",
    )
    action.add_argument(
        "--sync",
        action="store_true",
        help="Refresh the local read-cache from the DuckLake reader",
    )
    action.add_argument(
        "--selftest-read",
        action="store_true",
        help="Read a sample row via the active backend's reader (rollback rehearsal, VP14)",
    )
    action.add_argument(
        "--selftest-roundtrip",
        action="store_true",
        help="Write+read a throwaway test- rec via the active backend (cutover sign-off, VP15)",
    )
    action.add_argument(
        "--back-validate",
        action="store_true",
        help="Re-validate warn-period source=ci_rca recs against the current strict-mode schema (T1.13 c2 enabler)",
    )
    action.add_argument(
        "--find-open-ci-rca-rec",
        action="store_true",
        help="Read-only: print the id of an OPEN source=ci_rca rec matching --fingerprint, or nothing (CIRCA-03(b))",
    )
    action.add_argument(
        "--bump-ci-rca-occurrence",
        metavar="REC_ID",
        help="Bump occurrence_count/last_seen on an existing source=ci_rca rec's context_v2_json (CIRCA-03(b))",
    )

    # --find-open-ci-rca-rec fields
    fp_group = parser.add_argument_group("--find-open-ci-rca-rec fields")
    fp_group.add_argument("--fingerprint", help="sha256 hex fingerprint to match against open source=ci_rca recs")

    # --back-validate fields
    bv = parser.add_argument_group("--back-validate fields")
    bv.add_argument(
        "--since",
        default=_CI_RCA_BACK_VALIDATE_DEFAULT_SINCE,
        help="ISO date/timestamp floor on created_timestamp (inclusive); default is the Phase-1 landing date",
    )
    bv.add_argument(
        "--refile-audit",
        action="store_true",
        default=False,
        help="File non_conformant recs as source=ci_rca_warn_period_audit (capped per invocation); default is report-only",
    )
    bv.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        default=False,
        help="Print the back-validation report as machine-readable JSON instead of text",
    )

    # file-rec fields
    rec = parser.add_argument_group("--file-rec fields")
    rec.add_argument("--title")
    rec.add_argument("--file", dest="target_file")
    rec.add_argument("--context", dest="rec_context")
    rec.add_argument("--acceptance")
    rec.add_argument("--effort", choices=["XS", "S", "M", "L", "XL"])
    rec.add_argument("--priority", choices=["Critical", "High", "Medium", "Low"])
    rec.add_argument("--source")
    rec.add_argument("--risk", choices=["low", "medium", "high"])
    rec.add_argument("--tags", nargs="*", default=None)
    rec.add_argument("--dependencies", nargs="*", default=None)
    rec.add_argument("--verification")
    rec.add_argument("--verification-tier", choices=["V1", "V2", "V3"], dest="verification_tier")
    rec.add_argument(
        "--context-v2-json",
        dest="context_v2_json",
        default=None,
        help="JSON-encoded structured context dict: CiRcaContext for source=ci_rca recs,"
        " or CiRcaEvidenceDispute for source=ci_rca_evidence_dispute recs",
    )

    # update-rec fields
    upd = parser.add_argument_group("--update-rec fields")
    upd.add_argument("--status", choices=["open", "closed", "failed", "declined", "superseded"])
    upd.add_argument("--execution_result", choices=["success", "failure", "manual", "already_implemented"])
    upd.add_argument("--execution_date")
    upd.add_argument("--execution_branch")
    upd.add_argument("--execution_pr_url")
    upd.add_argument("--resolution")

    # file-decision fields
    dec = parser.add_argument_group("--file-decision fields")
    dec.add_argument("--rationale")
    dec.add_argument("--decision-status", choices=["open", "closed", "superseded"], dest="decision_status")
    dec.add_argument(
        "--decision-id",
        type=int,
        dest="decision_arg_id",
        help="DECISIONS.md-assigned integer number (numbering authority is DECISIONS.md, Decision 84)",
    )

    args = parser.parse_args(argv)

    if args.file_rec:
        required = ["title", "target_file", "rec_context", "acceptance", "effort", "priority", "source", "risk"]
        missing = [r for r in required if not getattr(args, r, None)]
        if missing:
            print(f"ERROR: --file-rec requires: {', '.join(missing)}", file=sys.stderr)
            return 1
        fields: dict = {
            "title": args.title,
            "file": args.target_file,
            "context": args.rec_context,
            "acceptance": args.acceptance,
            "effort": args.effort,
            "priority": args.priority,
            "source": args.source,
            "risk": args.risk,
            "status": "open",
        }
        if args.tags is not None:
            fields["tags"] = args.tags
        if args.dependencies is not None:
            fields["dependencies"] = args.dependencies
        if args.verification:
            fields["verification"] = args.verification
        if args.verification_tier:
            fields["verification_tier"] = args.verification_tier
        context_v2_parsed: dict | None = None
        if args.context_v2_json is not None:
            try:
                context_v2_parsed = json.loads(args.context_v2_json)
            except json.JSONDecodeError as exc:
                print(f"ERROR: --context-v2-json is not valid JSON: {exc}", file=sys.stderr)
                return 1
        try:
            rec_id = file_rec(fields, context_v2_json=context_v2_parsed, profile=args.profile)
            print(rec_id)
            return 0
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.find_open_ci_rca_rec:
        if not args.fingerprint:
            print("ERROR: --find-open-ci-rca-rec requires --fingerprint", file=sys.stderr)
            return 1
        rec_id = find_open_ci_rca_rec_by_fingerprint(args.fingerprint, profile=args.profile)
        if rec_id:
            print(rec_id)
        return 0

    if args.bump_ci_rca_occurrence:
        try:
            new_count = bump_ci_rca_occurrence(args.bump_ci_rca_occurrence, profile=args.profile)
            print(f"Bumped {args.bump_ci_rca_occurrence} occurrence_count={new_count}")
            return 0
        except (ValidationError, ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.update_rec:
        updates: dict = {}
        for field in ["status", "execution_result", "execution_date", "execution_branch", "execution_pr_url", "resolution"]:
            val = getattr(args, field, None)
            if val is not None:
                updates[field] = val
        if not updates:
            print("ERROR: --update-rec requires at least one update field (e.g. --status)", file=sys.stderr)
            return 1
        try:
            update_rec(args.update_rec, updates, profile=args.profile)
            print(f"Updated {args.update_rec}")
            return 0
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.file_decision:
        required_dec = ["title", "decision_status", "rationale"]
        missing_dec = [r for r in required_dec if not getattr(args, r.replace("-", "_"), None)]
        if missing_dec:
            # Check mapped names
            actually_missing = []
            if not args.title:
                actually_missing.append("--title")
            if not args.decision_status:
                actually_missing.append("--decision-status")
            if not args.rationale:
                actually_missing.append("--rationale")
            if actually_missing:
                print(f"ERROR: --file-decision requires: {', '.join(actually_missing)}", file=sys.stderr)
                return 1
        if not args.decision_arg_id:
            print("ERROR: --file-decision requires --decision-id (DECISIONS.md number)", file=sys.stderr)
            return 1
        dec_fields: dict = {
            "title": args.title,
            "status": args.decision_status,
            "decision_text": args.rationale,
            "decision_id": args.decision_arg_id,
        }
        try:
            decision_id = file_decision(dec_fields, profile=args.profile)
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(decision_id)
        return 0

    if args.update_decision is not None:
        dec_updates: dict = {}
        if args.status:
            dec_updates["status"] = args.status
        if args.resolution:
            dec_updates["resolution"] = args.resolution
        if not dec_updates:
            print("ERROR: --update-decision requires at least one update field", file=sys.stderr)
            return 1
        update_decision(args.update_decision, dec_updates, profile=args.profile)
        print(f"Updated decision {args.update_decision}")
        return 0

    if args.backfill_decisions_md:
        result = backfill_decisions_from_md(profile=args.profile)
        print(json.dumps(result))
        return 0 if result.get("failed", 0) == 0 else 1

    if args.purge_postmortems_for:
        result = purge_postmortems_for(args.purge_postmortems_for, dry_run=args.dry_run, profile=args.profile)
        print(json.dumps(result, indent=2))
        return 0

    if args.enqueue_findings:
        result = enqueue_findings(Path(args.enqueue_findings), profile=args.profile)
        print(f"enqueued: {result['enqueued']}, invalid: {result['invalid']}, skipped: {result['skipped']}")
        return 0

    if args.guidance:
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source=args.source)
        print(yaml.dump(guidance, default_flow_style=False, sort_keys=True, allow_unicode=True))
        return 0

    if args.sync:
        result = sync()
        print(json.dumps(result, indent=2))
        return 0

    if args.selftest_read:
        result = selftest_read(profile=args.profile)
        print(json.dumps(result, indent=2))
        return 0

    if args.selftest_roundtrip:
        try:
            result = selftest_roundtrip(profile=args.profile)
        except (RuntimeError, ValueError, ValidationError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.back_validate:
        result = back_validate_ci_rca(since=args.since, refile_audit=args.refile_audit, profile=args.profile)
        if args.json_output:
            print(json.dumps(result))
        else:
            _print_ci_rca_back_validation_report(result)
        return 0

    return 0
