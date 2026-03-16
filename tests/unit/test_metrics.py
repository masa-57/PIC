"""Unit tests for metrics helpers."""

from prometheus_client import Counter

from pic.core import metrics


def test_metrics_objects_are_declared_with_expected_types() -> None:
    assert isinstance(metrics.jobs_created_total, Counter)
    assert isinstance(metrics.jobs_completed_total, Counter)


def test_metrics_helper_functions_accept_strings_and_normalize_labels() -> None:
    metrics.record_job_created("pipeline")
    metrics.record_job_finished("pipeline", "completed")
