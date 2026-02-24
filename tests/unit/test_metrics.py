"""Unit tests for metrics module symbols."""

from prometheus_client import Counter, Histogram

from nic.core import metrics


def test_metrics_objects_are_declared_with_expected_types() -> None:
    assert isinstance(metrics.http_requests_total, Counter)
    assert isinstance(metrics.http_request_duration_seconds, Histogram)
    assert isinstance(metrics.jobs_created_total, Counter)
    assert isinstance(metrics.jobs_completed_total, Counter)


def test_metrics_can_record_values() -> None:
    metrics.http_requests_total.labels(method="GET", endpoint="/health", status="200").inc()
    metrics.http_request_duration_seconds.labels(method="GET", endpoint="/health").observe(0.01)
    metrics.jobs_created_total.labels(type="PIPELINE").inc()
    metrics.jobs_completed_total.labels(type="PIPELINE", status="COMPLETED").inc()
