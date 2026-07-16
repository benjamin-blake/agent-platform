"""MIRROR for src/common/ducklake_metrics.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_runtime.py monolith: emit_metric (injected client,
swallowed client error, the default boto3 Session/client path) and make_metric_sink (unit mapping).
No FakeCon needed -- these tests use their own inline CloudWatch-client doubles.
"""

from __future__ import annotations

# boto3 is imported at MODULE scope even though the tests reference it only via a LAZY
# `import boto3` inside test_emit_metric_boto3_path. This makes the file's heavy-dep requirement
# visible to the fast tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to
# the full post-merge tier, instead of catching it REACTIVELY. boto3 is deliberately excluded from
# requirements-fast.txt. See scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401
import pytest

from src.common import ducklake_runtime as rt

pytestmark = pytest.mark.unit


def test_emit_metric_with_injected_client():
    calls = []

    class _CW:
        def put_metric_data(self, **kwargs):
            calls.append(kwargs)

    rt.emit_metric("OccRetryCount", 2.0, client=_CW())
    assert calls[0]["Namespace"] == rt.CLOUDWATCH_NAMESPACE
    assert calls[0]["MetricData"][0]["MetricName"] == "OccRetryCount"


def test_emit_metric_swallows_client_error():
    class _CW:
        def put_metric_data(self, **kwargs):
            raise RuntimeError("throttled")

    rt.emit_metric("X", 1.0, client=_CW())  # must not raise


def test_emit_metric_boto3_path(monkeypatch):
    calls = []

    class _CW:
        def put_metric_data(self, **kwargs):
            calls.append(kwargs)

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def client(self, name):
            return _CW()

    monkeypatch.setattr(boto3, "Session", _Session)
    rt.emit_metric("X", 1.0)
    assert len(calls) == 1


def test_make_metric_sink_units():
    captured = []

    class _CW:
        def put_metric_data(self, **kwargs):
            captured.append(kwargs["MetricData"][0])

    sink = rt.make_metric_sink(client=_CW())
    sink("CommitLatencyMs", 12.5)
    sink("OccRetryCount", 1.0)
    units = {d["MetricName"]: d["Unit"] for d in captured}
    assert units["CommitLatencyMs"] == "Milliseconds"
    assert units["OccRetryCount"] == "Count"
