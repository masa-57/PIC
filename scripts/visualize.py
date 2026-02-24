#!/usr/bin/env python3
"""Generate an HTML report of cluster results for visual inspection.

Usage:
    python scripts/visualize.py                          # Uses live API URL
    python scripts/visualize.py --api http://localhost:8000  # Custom API URL
    python scripts/visualize.py -o report.html           # Custom output file

Opens the generated HTML file in the default browser.
"""

import argparse
import html
import json
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_API = "http://localhost:8000"


def _api_get(base_url: str, path: str) -> dict:
    """GET JSON from the API."""
    url = f"{base_url}/api/v1{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _api_post(base_url: str, path: str, body: dict) -> dict:
    """POST JSON to the API."""
    url = f"{base_url}/api/v1{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _get_image_url(base_url: str, image_id: str) -> str:
    """Get presigned S3 URL for an image."""
    data = _api_get(base_url, f"/images/{image_id}/file")
    return data.get("presigned_url", data.get("url", ""))


def _render_image_grid(base_url: str, images: list[dict], max_images: int = 20) -> str:
    """Render a grid of image thumbnails as HTML."""
    fallback_svg = (
        "data:image/svg+xml,"
        "<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22>"
        "<rect fill=%22%23ddd%22 width=%22200%22 height=%22200%22/>"
        "<text x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22"
        " text-anchor=%22middle%22 fill=%22%23999%22>No image</text></svg>"
    )
    parts = []
    for img in images[:max_images]:
        try:
            url = _get_image_url(base_url, img["id"])
        except Exception:
            url = ""
        fname = html.escape(img.get("filename", "unknown"))
        img_id_short = img["id"][:8]
        parts.append(
            f'<div class="img-card">'
            f'<img src="{url}" alt="{fname}" loading="lazy"'
            f" onerror=\"this.src='{fallback_svg}'\">"
            f'<div class="img-label">{fname}<br><small>{img_id_short}...</small></div>'
            f"</div>"
        )
    if len(images) > max_images:
        parts.append(f'<div class="img-card more">+{len(images) - max_images} more</div>')
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate visual cluster report")
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    parser.add_argument("-o", "--output", default="clusters.html", help="Output HTML file")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    args = parser.parse_args()

    base = args.api.rstrip("/")
    print(f"Fetching cluster data from {base}...")

    # Fetch hierarchy
    hierarchy = _api_get(base, "/clusters")
    l2_clusters = hierarchy["l2_clusters"]
    unclustered = hierarchy["unclustered_groups"]
    total_images = hierarchy["total_images"]
    total_l1 = hierarchy["total_l1_groups"]
    total_l2 = hierarchy["total_l2_clusters"]

    print(f"  {total_images} images, {total_l1} L1 groups, {total_l2} L2 clusters")

    # Fetch full L2 cluster details
    l2_details = []
    for c in l2_clusters:
        detail = _api_get(base, f"/clusters/level2/{c['id']}")
        l2_details.append(detail)
        print(f"  L2 Cluster {c['id']}: {detail['total_images']} images in {detail['member_count']} groups")

    # Build HTML
    summary_line = (
        f"{total_images} images &bull; {total_l1} L1 groups &bull; "
        f"{total_l2} L2 clusters &bull; {len(unclustered)} unclustered groups"
    )
    css = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; padding: 20px; }
h1 { margin-bottom: 8px; }
.summary { color: #666; margin-bottom: 24px; font-size: 14px; }
.cluster { background: white; border-radius: 8px; padding: 16px;
           margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.cluster h2 { margin-bottom: 4px; }
.cluster .meta { color: #888; font-size: 13px; margin-bottom: 12px; }
.grid { display: flex; flex-wrap: wrap; gap: 10px; }
.img-card { width: 180px; text-align: center; }
.img-card img { width: 180px; height: 180px; object-fit: cover;
                border-radius: 6px; border: 2px solid #eee; }
.img-label { font-size: 11px; color: #666; margin-top: 4px; word-break: break-all; }
.more { display: flex; align-items: center; justify-content: center;
        width: 180px; height: 180px; background: #f0f0f0;
        border-radius: 6px; color: #999; font-size: 18px; }
.l1-group { margin-bottom: 12px; padding: 8px; background: #fafafa;
            border-radius: 6px; }
.l1-group h3 { font-size: 13px; color: #555; margin-bottom: 6px; }
.unclustered { border-left: 4px solid #f0ad4e; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 10px;
       font-size: 11px; font-weight: 600; }
.tag-l2 { background: #d4edda; color: #155724; }
.tag-noise { background: #fff3cd; color: #856404; }"""

    html_parts = [
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PIC Cluster Report</title>
<style>{css}</style>
</head>
<body>
<h1>PIC Cluster Report</h1>
<div class="summary">{summary_line}</div>
"""
    ]

    # L2 clusters
    for detail in l2_details:
        cluster_id = detail["id"]
        label = detail.get("label") or f"Cluster {cluster_id}"
        html_parts.append(
            f'<div class="cluster">'
            f'<h2><span class="tag tag-l2">L2</span> {html.escape(str(label))}</h2>'
            f'<div class="meta">{detail["member_count"]} L1 groups &bull; {detail["total_images"]} images</div>'
        )
        for group in detail.get("groups", []):
            images = group.get("images", [])
            g_id = group["id"]
            html_parts.append(
                f'<div class="l1-group">'
                f"<h3>L1 Group {g_id} ({group['member_count']} images)</h3>"
                f'<div class="grid">{_render_image_grid(base, images)}</div>'
                f"</div>"
            )
        html_parts.append("</div>")

    # Unclustered
    if unclustered:
        html_parts.append(
            '<div class="cluster unclustered">'
            '<h2><span class="tag tag-noise">Unclustered</span> Noise / singleton groups</h2>'
            f'<div class="meta">{len(unclustered)} L1 groups not assigned to any L2 cluster</div>'
        )
        for group in unclustered:
            images = group.get("images", [])
            g_id = group["id"]
            html_parts.append(
                f'<div class="l1-group">'
                f"<h3>L1 Group {g_id} ({group['member_count']} images)</h3>"
                f'<div class="grid">{_render_image_grid(base, images)}</div>'
                f"</div>"
            )
        html_parts.append("</div>")

    html_parts.append("</body></html>")

    # Write output
    output_path = Path(args.output)
    output_path.write_text("\n".join(html_parts))
    print(f"\nWrote {output_path.resolve()}")

    if not args.no_open:
        webbrowser.open(f"file://{output_path.resolve()}")


if __name__ == "__main__":
    main()
