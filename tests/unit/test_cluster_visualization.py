"""Unit tests for cluster visualization helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nic.services.cluster_visualization import _build_hierarchy, generate_visualization_html, render_html


@pytest.mark.unit
def test_build_hierarchy_includes_cluster_unclustered_and_no_l1_sections() -> None:
    l2_clusters = [
        SimpleNamespace(id=1, label="Hero", member_count=1, total_images=2),
    ]
    l1_groups = [
        SimpleNamespace(id=10, representative_image_id="img-1", member_count=2, l2_cluster_id=1),
        SimpleNamespace(id=20, representative_image_id="img-3", member_count=1, l2_cluster_id=None),
    ]
    images = [
        SimpleNamespace(
            id="img-1",
            filename="a.jpg",
            s3_key="processed/a.jpg",
            s3_thumbnail_key=None,
            l1_group_id=10,
            width=100,
            height=100,
        ),
        SimpleNamespace(
            id="img-2",
            filename="b.jpg",
            s3_key="processed/b.jpg",
            s3_thumbnail_key="thumbnails/b.jpg",
            l1_group_id=10,
            width=100,
            height=100,
        ),
        SimpleNamespace(
            id="img-3",
            filename="c.jpg",
            s3_key="processed/c.jpg",
            s3_thumbnail_key=None,
            l1_group_id=20,
            width=100,
            height=100,
        ),
        SimpleNamespace(
            id="img-4",
            filename="d.jpg",
            s3_key="processed/d.jpg",
            s3_thumbnail_key=None,
            l1_group_id=None,
            width=100,
            height=100,
        ),
    ]

    with patch("nic.services.cluster_visualization._presigned", side_effect=lambda k, e: f"signed:{k}:{e}"):
        hierarchy = _build_hierarchy(l2_clusters, l1_groups, images, expiry=3600)

    assert len(hierarchy) == 3
    assert hierarchy[0]["id"] == 1
    assert hierarchy[0]["groups"][0]["images"][0]["is_rep"] is True
    assert hierarchy[1]["label"] == "Unclustered (no L2)"
    assert hierarchy[2]["id"] == "orphan"
    assert hierarchy[2]["groups"][0]["member_count"] == 1


@pytest.mark.unit
def test_render_html_escapes_untrusted_labels_and_filenames() -> None:
    hierarchy = [
        {
            "id": 1,
            "label": "<script>alert(1)</script>",
            "member_count": 1,
            "total_images": 1,
            "groups": [
                {
                    "id": 10,
                    "rep_id": "img-1",
                    "member_count": 1,
                    "images": [
                        {
                            "id": "img-1",
                            "filename": "bad'\"<tag>.jpg",
                            "thumb_url": "https://thumb",
                            "full_url": "https://full",
                            "is_rep": True,
                            "width": 100,
                            "height": 100,
                        }
                    ],
                }
            ],
        }
    ]

    html = render_html(hierarchy, total_l1=1)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "bad&#x27;&quot;&lt;tag&gt;.jpg" in html


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_visualization_html_composes_load_build_and_render() -> None:
    db = AsyncMock()
    l2 = [SimpleNamespace(id=1, label="Hero", member_count=1, total_images=1)]
    l1 = [SimpleNamespace(id=10, representative_image_id="img-1", member_count=1, l2_cluster_id=1)]
    imgs = [
        SimpleNamespace(
            id="img-1",
            filename="a.jpg",
            s3_key="processed/a.jpg",
            s3_thumbnail_key=None,
            l1_group_id=10,
            width=100,
            height=100,
        )
    ]
    built = [{"id": 1, "label": "Hero", "groups": [{"images": [{}]}]}]

    with (
        patch(
            "nic.services.cluster_visualization._load_hierarchy",
            new_callable=AsyncMock,
            return_value=(l2, l1, imgs),
        ),
        patch("nic.services.cluster_visualization._build_hierarchy", return_value=built) as mock_build,
        patch("nic.services.cluster_visualization.render_html", return_value="<html>ok</html>") as mock_render,
    ):
        html = await generate_visualization_html(db, url_expiry=1800)

    assert html == "<html>ok</html>"
    mock_build.assert_called_once_with(l2, l1, imgs, 1800)
    mock_render.assert_called_once_with(built, len(l1))
