"""CI-RCA evidence bundle generator and uploader.

CLI: python -m scripts.ci_rca_evidence \\
       --log-file LOG --workflow-name NAME --workflow-run-id ID [--jobs-file JOBS] [--print-bundle]

Reads pre-fetched CI run logs (NO gh dependency at runtime -- CC-web has no gh CLI).
Assembles one evidence_bundle.json per failed check per INTENT-ci-rca-methodology Section 3.3,
uploads to the configured s3_agent_logs_bucket, falls back to logs/.ci-rca-evidence-pending/
on upload failure (loud signal, upload_status=upload_failed).
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

ROOT = Path(__file__).parent.parent
_PENDING_DIR = ROOT / "logs" / ".ci-rca-evidence-pending"
_EVIDENCE_PREFIX = "ci-rca-evidence"


def _resolve_bucket() -> str:
    """Resolve agent-logs S3 bucket via config or S3_LOG_BUCKET env override."""
    env = os.environ.get("S3_LOG_BUCKET", "").strip()
    if env:
        return env
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.common.config import Config

        val = Config().get("aws.s3_agent_logs_bucket", "")
        if val:
            return val
    except Exception:
        pass
    try:
        personal_cfg = ROOT / "config" / "config.personal.yaml"
        if personal_cfg.exists():
            import yaml

            with personal_cfg.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            val = cfg.get("aws", {}).get("s3_agent_logs_bucket", "")
            if val:
                return val
    except Exception:
        pass
    return ""


def _canonical_json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _compute_fingerprint(workflow_slug: str, failed_check: str, failure_category: str) -> str:
    """Classifier-anchored grouping key (CIRCA-03(a)) -- deliberately SEPARATE from the bundle's
    canonical sha256 (an integrity hash over the whole bundle). This key groups failures by
    root cause across runs: it is invariant to run_id/timestamp/head_sha and distinct across
    differing failed_check or failure_category.
    """
    payload = "\0".join((workflow_slug, failed_check, failure_category))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _slugify_workflow(workflow_name: str) -> str:
    """Mirror ci-rca.yml's WORKFLOW_SLUG shell derivation so the fingerprint's workflow
    component matches the same slug the workflow computes independently for status contexts."""
    slug = workflow_name.lower().replace(" ", "_").replace("/", "-")
    return re.sub(r"[^a-z0-9_-]", "", slug)


def _normalize_first_error_signature(log_text: str, failed_check: str) -> str:
    """Tie-breaker signature (CIRCA-03(a)) -- NOT the grouping key. Picks the first log line
    mentioning failed_check (else the first non-blank line) and normalizes volatile digit
    tokens (line numbers, durations, run ids) so it is stable across reruns of the same failure.
    """
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    if not lines:
        return ""
    match = next((ln for ln in lines if failed_check and failed_check in ln), None)
    line = match or lines[0]
    normalized = re.sub(r"\s+", " ", line)
    normalized = re.sub(r"\d+", "#", normalized)
    return normalized[:300]


def _sha256_of(obj: dict[str, Any]) -> str:
    payload = {k: v for k, v in obj.items() if k != "sha256"}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _upload_to_s3(body: bytes, bucket: str, key: str) -> None:
    import boto3

    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3", region_name="eu-west-2")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def _write_pending(bundle: dict[str, Any], sha: str) -> Path:
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = _PENDING_DIR / f"{sha}.json"
    dest.write_bytes(_canonical_json(bundle))
    logger.warning("EVIDENCE_BUNDLE_PENDING: upload_failed; bundle at %s", dest)
    return dest


def upload_and_persist(bundle: dict[str, Any], bucket: str) -> dict[str, str]:
    """Upload bundle to S3 or fall back to pending dir. Returns status dict."""
    sha = bundle["sha256"]
    key = f"{_EVIDENCE_PREFIX}/{sha}.json"
    s3_uri = f"s3://{bucket}/{key}"
    body = _canonical_json(bundle)

    if not bucket:
        logger.warning("EVIDENCE_BUCKET_UNRESOLVED: no bucket; writing to pending dir")
        pending = _write_pending(bundle, sha)
        return {"upload_status": "upload_failed", "s3_uri": "", "pending_path": str(pending)}

    try:
        _upload_to_s3(body, bucket, key)
        return {"upload_status": "ok", "s3_uri": s3_uri, "pending_path": ""}
    except Exception as exc:
        logger.error("S3 upload failed (%s/%s): %s", bucket, key, exc)
        pending = _write_pending(bundle, sha)
        return {"upload_status": "upload_failed", "s3_uri": "", "pending_path": str(pending)}


def _assemble_core(
    workflow_run_id: int,
    workflow_name: str,
    failed_check: str,
    failure_category: str,
    classification_source: str,
    validate_path: Path | None,
    taxonomy_path: Path | None,
    vacuous_pass: "bool | str" = "undetermined",
    merge_gate_test_coverage: str = "undetermined",
    coverage_regression: "bool | str" = "undetermined",
    first_error_signature: str = "",
) -> dict[str, Any]:
    from scripts.ci_rca_taxonomy import load_taxonomy, resolve_workflow_tier
    from scripts.ci_rca_tier_map import (
        AST_WALKER_VERSION,
        build_tier_membership,
        compute_earliest_viable_gate,
        probe_runtime,
    )
    from scripts.ci_rca_vacuous_pass import compute_escape_mode

    taxonomy = load_taxonomy(taxonomy_path)
    taxonomy_version = taxonomy.get("taxonomy_version", 1)
    wf_tier = resolve_workflow_tier(workflow_name, taxonomy_path)
    actual_gate = wf_tier if wf_tier != "unknown" else None
    gate_is_postmerge_canary = wf_tier == "CI"

    tier_membership = build_tier_membership(validate_path)
    ast_walker_error: str | None = None
    if tier_membership is None:
        ast_walker_error = "AST parse failure -- see logs"

    runtime_confidence, median_sec = probe_runtime(failed_check, validate_path)
    earliest_gate, evg_rationale = compute_earliest_viable_gate(failed_check, tier_membership, runtime_confidence, median_sec)

    escape_mode = compute_escape_mode(
        vacuous_pass=vacuous_pass,
        merge_gate_test_coverage=merge_gate_test_coverage,
        gate_is_postmerge_canary=gate_is_postmerge_canary,
        coverage_regression=coverage_regression,
    )

    check_tiers = None
    if tier_membership is not None:
        check_tiers = tier_membership.get(failed_check)

    # CIRCA-03(a): grouping fingerprint, anchored on the deterministic classifier fields only --
    # invariant to run_id/timestamp/head_sha, distinct across differing failed_check/failure_category.
    # Deliberately separate from the bundle's canonical sha256 (a whole-bundle integrity hash).
    fingerprint = _compute_fingerprint(_slugify_workflow(workflow_name), failed_check, failure_category)

    bundle: dict[str, Any] = {
        "schema_version": 3,
        "workflow_run_id": workflow_run_id,
        "workflow_name": workflow_name,
        "workflow_to_tier_resolution": wf_tier,
        "failed_check": failed_check,
        "failure_category": failure_category,
        "fingerprint": fingerprint,
        "first_error_signature": first_error_signature,
        "classification_source": classification_source,
        "tier_membership": check_tiers,
        "earliest_viable_gate": earliest_gate,
        "earliest_viable_gate_rationale": evg_rationale,
        "runtime_confidence": runtime_confidence,
        "actual_gate_that_caught_it": actual_gate,
        "gate_is_postmerge_canary": gate_is_postmerge_canary,
        "vacuous_pass": vacuous_pass,
        "merge_gate_test_coverage": merge_gate_test_coverage,
        "coverage_regression": coverage_regression,
        "escape_mode": escape_mode,
        "related_recs_by_category": [],
        "decision_records_cited": ["Decision 43", "Decision 60"],
        "ast_walker_version": AST_WALKER_VERSION,
        "taxonomy_version": taxonomy_version,
    }
    if ast_walker_error:
        bundle["ast_walker_error"] = ast_walker_error
    return bundle


def generate_bundles(
    log_file: Path,
    workflow_name: str,
    workflow_run_id: int,
    jobs_file: Path | None = None,
    validate_path: Path | None = None,
    taxonomy_path: Path | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """Parse log, classify failure(s), assemble + hash bundles. Returns one bundle per failed check."""
    from scripts.ci_rca_taxonomy import classify_failures, load_taxonomy
    from scripts.ci_rca_vacuous_pass import (
        compute_coverage_regression,
        compute_merge_gate_test_coverage,
        deleted_test_files,
        merged_diff_files,
        parse_vacuous_pass,
    )

    log_text = log_file.read_text(encoding="utf-8", errors="replace")
    jobs: list[dict] | None = None
    if jobs_file and jobs_file.exists():
        try:
            raw = json.loads(jobs_file.read_text(encoding="utf-8", errors="replace"))
            jobs = raw.get("jobs") if isinstance(raw, dict) else raw if isinstance(raw, list) else None
        except Exception:
            logger.warning("Could not parse jobs file %s", jobs_file)

    # Pre-compute shared evidence fields once per run
    vacuous_pass_val = parse_vacuous_pass(log_text)
    merged = merged_diff_files()
    deleted = deleted_test_files()
    coverage_reg = compute_coverage_regression(deleted)

    try:
        load_taxonomy(taxonomy_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("TAXONOMY_UNAVAILABLE: %s", exc)
        b: dict[str, Any] = {
            "schema_version": 3,
            "workflow_run_id": workflow_run_id,
            "workflow_name": workflow_name,
            "workflow_to_tier_resolution": "unknown",
            "failed_check": "unknown",
            "failure_category": "unknown",
            "fingerprint": _compute_fingerprint(_slugify_workflow(workflow_name), "unknown", "unknown"),
            "first_error_signature": _normalize_first_error_signature(log_text, "unknown"),
            "classification_source": "taxonomy_fallback",
            "taxonomy_error": str(exc),
            "tier_membership": None,
            "earliest_viable_gate": "undetermined",
            "earliest_viable_gate_rationale": "Taxonomy unavailable",
            "runtime_confidence": None,
            "actual_gate_that_caught_it": None,
            "gate_is_postmerge_canary": False,
            "vacuous_pass": vacuous_pass_val,
            "merge_gate_test_coverage": "undetermined",
            "coverage_regression": coverage_reg,
            "escape_mode": "undetermined",
            "related_recs_by_category": [],
            "decision_records_cited": [],
            "ast_walker_version": 1,
            "taxonomy_version": 0,
        }
        b["sha256"] = _sha256_of(b)
        return [b]

    failures = classify_failures(log_text, jobs, taxonomy_path)
    bundles: list[dict[str, Any]] = []
    for cat, check, src in failures:
        coverage = compute_merge_gate_test_coverage(check, merged)
        core = _assemble_core(
            workflow_run_id,
            workflow_name,
            check,
            cat,
            src,
            validate_path,
            taxonomy_path,
            vacuous_pass=vacuous_pass_val,
            merge_gate_test_coverage=coverage,
            coverage_regression=coverage_reg,
            first_error_signature=_normalize_first_error_signature(log_text, check),
        )
        core["sha256"] = _sha256_of(core)
        bundles.append(core)
    return bundles


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate CI-RCA evidence bundles from pre-fetched logs.")
    parser.add_argument("--log-file", required=True, type=Path)
    parser.add_argument("--jobs-file", type=Path, default=None)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--workflow-run-id", required=True, type=int)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--validate-path", type=Path, default=ROOT / "scripts" / "validate.py")
    parser.add_argument("--taxonomy-path", type=Path, default=None)
    parser.add_argument("--print-bundle", action="store_true")
    parser.add_argument(
        "--emit-dir",
        type=Path,
        default=None,
        help="Write each bundle to <dir>/<sha>.json regardless of S3 upload outcome; prints BUNDLE_LOCAL=<path>",
    )
    args = parser.parse_args(argv)

    if not args.log_file.exists():
        print(f"ERROR: log file not found: {args.log_file}", file=sys.stderr)
        sys.exit(1)

    bucket = _resolve_bucket()
    bundles = generate_bundles(
        log_file=args.log_file,
        workflow_name=args.workflow_name,
        workflow_run_id=args.workflow_run_id,
        jobs_file=args.jobs_file,
        validate_path=args.validate_path,
        taxonomy_path=args.taxonomy_path,
        repo=args.repo,
    )

    for bundle in bundles:
        sha = bundle["sha256"]
        if args.emit_dir is not None:
            args.emit_dir.mkdir(parents=True, exist_ok=True)
            local_path = args.emit_dir / f"{sha}.json"
            local_path.write_bytes(_canonical_json(bundle))
            print(f"BUNDLE_LOCAL={local_path}")
        result = upload_and_persist(bundle, bucket)
        if args.print_bundle:
            print(json.dumps({**bundle, **result}, indent=2, sort_keys=True))
        print(f"BUNDLE_SHA={sha}")
        print(f"FINGERPRINT={bundle.get('fingerprint', '')}")
        print(f"BUNDLE_S3_URI={result['s3_uri']}")
        print(f"BUNDLE_PATH={result['pending_path']}")
        if result["upload_status"] == "upload_failed":
            print("UPLOAD_STATUS=upload_failed", file=sys.stderr)


if __name__ == "__main__":
    main()
