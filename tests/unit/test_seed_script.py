"""Unit tests for scripts/seed.py."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest

pytestmark = pytest.mark.unit

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"


@pytest.fixture
def seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_script", SEED_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_images_filters_by_extension(seed: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.PNG").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.webp").write_bytes(b"x")

    names = [p.name for p in seed.find_images(tmp_path)]
    assert names == ["a.jpg", "b.PNG", "c.webp"]


def test_upload_images_writes_to_inbox(seed: ModuleType, tmp_path: Path) -> None:
    img = tmp_path / "shoe.jpg"
    img.write_bytes(b"jpeg-bytes")
    storage = MagicMock()

    assert seed.upload_images([img], storage) == 1
    storage.upload.assert_called_once_with("images/shoe.jpg", b"jpeg-bytes", "image/jpeg")


def _client(handler) -> httpx.Client:  # noqa: ANN001
    return httpx.Client(base_url="http://pic.test", transport=httpx.MockTransport(handler))


def test_start_pipeline_returns_job_id(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/pipeline/run"
        return httpx.Response(202, json={"id": "job-1", "status": "pending"})

    assert seed.start_pipeline(_client(handler)) == "job-1"


def test_wait_for_job_polls_until_terminal(seed: ModuleType) -> None:
    statuses = iter(["pending", "running", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/jobs/job-1"
        return httpx.Response(200, json={"id": "job-1", "status": next(statuses)})

    assert seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=5) == "completed"


def test_wait_for_job_reports_failure(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "job-1", "status": "failed", "error": "boom"})

    assert seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=5) == "failed"


def test_wait_for_job_times_out(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=json.loads('{"id": "job-1", "status": "running"}'))

    with pytest.raises(TimeoutError):
        seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=0)
