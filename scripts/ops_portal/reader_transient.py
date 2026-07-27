"""Classifier for a transient DuckLake reader infra outage (Decision 155).

Sole home for `is_reader_unavailable`, extracted verbatim in behaviour from the
already-landed private copy at scripts/data_quality_execute.py (`_is_reader_unavailable` /
`_TRANSIENT_HTTP_RE`), so the two consumers cannot drift.

A 502/503/504 from the DuckLake reader indicates TRANSIENT unavailability -- it is NOT
reliably a cold-resume signal. src/common/iceberg_reader.py's "retrying after cold-resume
backoff" log line asserts the latter and is misleading; that mislabel is tracked separately
(see the plan context for PLAN-syspath-hygiene-advisory-read-tolerance) and is not corrected
here because it lives in a wildcard-packaged src/ file.

Deliberately homed in scripts/ops_portal/ beside its writer-side counterpart
writer_transport.py, and NOT in src/, because the active manifests that wildcard-include
src/ would package any new src/ file and pull in Lambda build/deploy/smoke-test legs for
what is a pure-logic helper.
"""

from __future__ import annotations

import re

_TRANSIENT_HTTP_RE = re.compile(r"failed \(HTTP (?:502|503|504)\)")


def is_reader_unavailable(exc: BaseException) -> bool:
    """True when exc indicates a transient DuckLake reader infra outage.

    Transient: requests ConnectionError/Timeout, or a RuntimeError whose message
    matches the reader's own transient set {502,503,504} with no structured error_type marker.
    Structured handler errors (HTTP 500 + error_type, 4xx) are not transient -- they gate.
    """
    try:
        import requests as _req  # noqa: PLC0415

        if isinstance(exc, (_req.ConnectionError, _req.Timeout)):
            return True
    except ImportError:
        pass
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        if _TRANSIENT_HTTP_RE.search(msg) and "error_type" not in msg:
            return True
    return False
