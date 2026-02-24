#!/usr/bin/env python3
"""Generate an HTML visualization of L2 → L1 → Image clusters.

Connects directly to the production Neon DB and generates presigned R2 URLs
for thumbnails (grid) and full images (lightbox).

Usage:
    uv run python scripts/visualize_clusters.py                     # defaults
    uv run python scripts/visualize_clusters.py -o my_report.html   # custom output
    uv run python scripts/visualize_clusters.py --expiry 7200       # 2-hour URLs
    uv run python scripts/visualize_clusters.py --no-open           # don't open browser
"""

from __future__ import annotations

import argparse
import html as html_mod
import webbrowser
from pathlib import Path

import boto3
import psycopg2
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config (loaded from .env)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

import os  # noqa: E402 — after load_dotenv so env vars are available

DB_URL = os.environ["PIC_POSTGRES_URL"]
S3_BUCKET = os.environ.get("PIC_S3_BUCKET", "pic-images")
S3_ENDPOINT = os.environ["PIC_S3_ENDPOINT_URL"]
S3_KEY_ID = os.environ["PIC_S3_ACCESS_KEY_ID"]
S3_SECRET = os.environ["PIC_S3_SECRET_ACCESS_KEY"]

_s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_KEY_ID,
    aws_secret_access_key=S3_SECRET,
    region_name="auto",
    config=BotoConfig(signature_version="s3v4"),
)


def _presigned(s3_key: str, expiry: int) -> str:
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=expiry,
    )


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _query_clusters(conn):  # noqa: ANN001
    cur = conn.cursor()

    cur.execute("""
        SELECT id, label, member_count, total_images, centroid_image_id, viz_x, viz_y
        FROM l2_clusters ORDER BY total_images DESC
    """)
    l2_clusters = cur.fetchall()

    cur.execute("""
        SELECT id, representative_image_id, member_count, l2_cluster_id
        FROM l1_groups ORDER BY l2_cluster_id, member_count DESC
    """)
    l1_groups = cur.fetchall()

    cur.execute("""
        SELECT id, filename, s3_key, s3_thumbnail_key, l1_group_id, width, height
        FROM images WHERE has_embedding = 1
        ORDER BY l1_group_id, created_at
    """)
    images = cur.fetchall()

    return l2_clusters, l1_groups, images


# ---------------------------------------------------------------------------
# Build hierarchy
# ---------------------------------------------------------------------------


def _build_hierarchy(l2_clusters: list, l1_groups: list, images: list, expiry: int) -> list[dict]:
    # Index images by l1_group_id
    img_by_l1: dict[int | None, list] = {}
    for img in images:
        img_by_l1.setdefault(img[4], []).append(img)

    # Index L1 groups by l2_cluster_id
    l1_by_l2: dict[int | None, list] = {}
    for g in l1_groups:
        l1_by_l2.setdefault(g[3], []).append(g)

    def _img_dict(img: tuple, rep_id: str | None) -> dict:
        thumb_key = img[3] or img[2]  # prefer thumbnail, fallback to full
        return {
            "id": img[0],
            "filename": img[1],
            "thumb_url": _presigned(thumb_key, expiry),
            "full_url": _presigned(img[2], expiry),
            "is_rep": img[0] == rep_id,
            "width": img[5],
            "height": img[6],
        }

    def _group_dict(g: tuple) -> dict:
        g_id, rep_id = g[0], g[1]
        return {
            "id": g_id,
            "rep_id": rep_id,
            "member_count": g[2],
            "images": [_img_dict(i, rep_id) for i in img_by_l1.get(g_id, [])],
        }

    hierarchy: list[dict] = []

    # L2 clusters
    for l2 in l2_clusters:
        l2_id = l2[0]
        hierarchy.append(
            {
                "id": l2_id,
                "label": l2[1],
                "member_count": l2[2],
                "total_images": l2[3],
                "groups": [_group_dict(g) for g in l1_by_l2.get(l2_id, [])],
            }
        )

    # Orphan L1 groups (assigned to no L2 cluster)
    orphans = l1_by_l2.get(None, [])
    if orphans:
        hierarchy.append(
            {
                "id": None,
                "label": "Unclustered (no L2)",
                "member_count": len(orphans),
                "total_images": sum(g[2] for g in orphans),
                "groups": [_group_dict(g) for g in orphans],
            }
        )

    # Images with no L1 group at all
    no_l1 = img_by_l1.get(None, [])
    if no_l1:
        hierarchy.append(
            {
                "id": "orphan",
                "label": "No L1 Group",
                "member_count": 0,
                "total_images": len(no_l1),
                "groups": [
                    {
                        "id": None,
                        "rep_id": None,
                        "member_count": len(no_l1),
                        "images": [_img_dict(i, None) for i in no_l1],
                    }
                ],
            }
        )

    return hierarchy


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --bg: #0f0f0f; --accent2: #0f3460; --text: #eee; --muted: #888;
  --border: #333; --l1-bg: #111827; --rep: #10b981; --accent: #e94560;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
       background:var(--bg); color:var(--text); padding:24px; line-height:1.5; }
h1 { font-size:28px; margin-bottom:8px; }
.stats { color:var(--muted); font-size:14px; margin-bottom:24px; }
.stats span { background:var(--accent2); padding:2px 10px; border-radius:12px;
              margin-right:8px; font-size:13px; color:var(--text); }
.toolbar { display:flex; gap:8px; margin-bottom:16px; }
.btn { background:var(--accent2); border:1px solid var(--border); color:var(--text);
       padding:8px 16px; border-radius:8px; cursor:pointer; font-size:14px; }
.btn:hover { background:#1a4a7a; }
.l2 { border:1px solid var(--border); border-radius:12px; margin-bottom:24px; overflow:hidden; }
.l2-hdr { background:var(--accent2); padding:16px 20px; cursor:pointer;
          display:flex; justify-content:space-between; align-items:center; user-select:none; }
.l2-hdr:hover { background:#1a4a7a; }
.l2-hdr h2 { font-size:18px; font-weight:600; }
.l2-meta { font-size:13px; color:var(--muted); display:flex; gap:16px; align-items:center; }
.l2-body { padding:16px; }
.l2-body.hide { display:none; }
.l1 { background:var(--l1-bg); border:1px solid var(--border); border-radius:8px;
      padding:12px; margin-bottom:12px; }
.l1-hdr { font-size:14px; font-weight:500; margin-bottom:8px; color:var(--muted); }
.l1-hdr strong { color:var(--text); }
.grid { display:flex; flex-wrap:wrap; gap:8px; }
.card { position:relative; width:120px; height:120px; border-radius:6px; overflow:hidden;
        border:2px solid transparent; cursor:pointer; transition:transform .15s,border-color .15s; }
.card:hover { transform:scale(1.05); border-color:var(--accent); }
.card.rep { border-color:var(--rep); box-shadow:0 0 8px rgba(16,185,129,.4); }
.card img { width:100%; height:100%; object-fit:cover; }
.card .badge { position:absolute; top:4px; right:4px; background:var(--rep); color:#000;
               font-size:10px; font-weight:700; padding:1px 5px; border-radius:4px; }
.card .fname { position:absolute; bottom:0; left:0; right:0; background:rgba(0,0,0,.7);
               font-size:10px; padding:2px 4px; white-space:nowrap; overflow:hidden;
               text-overflow:ellipsis; opacity:0; transition:opacity .15s; }
.card:hover .fname { opacity:1; }
.chev { font-size:20px; transition:transform .2s; }
.chev.shut { transform:rotate(-90deg); }
/* lightbox */
.lb { display:none; position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:1000;
      justify-content:center; align-items:center; flex-direction:column; }
.lb.on { display:flex; }
.lb img { max-width:90vw; max-height:80vh; border-radius:8px; }
.lb .cap { margin-top:12px; font-size:14px; color:var(--muted); }
.lb .x { position:absolute; top:20px; right:24px; font-size:28px; cursor:pointer; color:var(--text); }
"""

_JS = """\
function tog(id){
  document.getElementById('b-'+id).classList.toggle('hide');
  document.getElementById('c-'+id).classList.toggle('shut');
}
let expanded=false;
function togAll(){
  expanded=!expanded;
  document.querySelectorAll('.l2-body').forEach(b=>{
    expanded?b.classList.remove('hide'):b.classList.add('hide')});
  document.querySelectorAll('.chev').forEach(c=>{
    expanded?c.classList.remove('shut'):c.classList.add('shut')});
}
function lb(full,cap){
  document.getElementById('lb-i').src=full;
  document.getElementById('lb-c').textContent=cap;
  document.getElementById('lb').classList.add('on');
}
function lbOff(){document.getElementById('lb').classList.remove('on')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')lbOff()});
"""


def _esc(s: str) -> str:
    return html_mod.escape(s, quote=True).replace("'", "&#39;")


def _render_html(hierarchy: list[dict], total_l1: int) -> str:
    total_imgs = sum(sum(len(g["images"]) for g in c["groups"]) for c in hierarchy)
    total_l2 = sum(1 for c in hierarchy if c["id"] is not None and c["id"] != "orphan")

    parts: list[str] = []
    for idx, c in enumerate(hierarchy):
        cid = str(c["id"]) if c["id"] is not None else f"orph-{idx}"
        img_count = sum(len(g["images"]) for g in c["groups"])
        label = _esc(c["label"] or f"Cluster {c['id']}")

        groups_parts: list[str] = []
        for g in c["groups"]:
            imgs_parts: list[str] = []
            for img in g["images"]:
                rc = " rep" if img["is_rep"] else ""
                badge = '<span class="badge">REP</span>' if img["is_rep"] else ""
                fn = _esc(img["filename"][:30])
                fn_full = _esc(img["filename"])
                tu = _esc(img["thumb_url"])
                fu = _esc(img["full_url"])
                imgs_parts.append(
                    f"<div class='card{rc}' onclick=\"lb('{fu}','{fn_full}')\">"
                    f"<img src='{tu}' alt='{fn_full}' loading='lazy'>{badge}"
                    f"<span class='fname'>{fn}</span></div>"
                )
            g_label = f"L1 Group #{g['id']}" if g["id"] else "Ungrouped"
            n = len(g["images"])
            groups_parts.append(
                f"<div class='l1'><div class='l1-hdr'><strong>{g_label}</strong>"
                f" &mdash; {n} image{'s' if n != 1 else ''}</div>"
                f"<div class='grid'>{''.join(imgs_parts)}</div></div>"
            )

        parts.append(
            f"<div class='l2'>"
            f"<div class='l2-hdr' onclick=\"tog('{cid}')\">"
            f"<h2>{label}</h2>"
            f"<div class='l2-meta'><span>{len(c['groups'])} L1 groups</span>"
            f"<span>{img_count} images</span>"
            f"<span class='chev shut' id='c-{cid}'>&#9660;</span></div></div>"
            f"<div class='l2-body hide' id='b-{cid}'>{''.join(groups_parts)}</div></div>"
        )

    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        f"<title>PIC Cluster Visualization</title><style>{_CSS}</style></head><body>"
        "<h1>PIC Cluster Visualization</h1>"
        f"<div class='stats'><span>{total_imgs} images</span>"
        f"<span>{total_l2} L2 clusters</span><span>{total_l1} L1 groups</span></div>"
        "<div class='toolbar'><button class='btn' onclick='togAll()'>Expand / Collapse All</button></div>"
        f"<div id='clusters'>{''.join(parts)}</div>"
        "<div class='lb' id='lb' onclick='lbOff()'><span class='x'>&times;</span>"
        "<img id='lb-i' src='' alt=''><div class='cap' id='lb-c'></div></div>"
        f"<script>{_JS}</script></body></html>"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HTML visualization of PIC image clusters (direct DB + R2).")
    parser.add_argument(
        "-o",
        "--output",
        default="cluster_visualization.html",
        help="Output HTML file path (default: cluster_visualization.html)",
    )
    parser.add_argument(
        "--expiry",
        type=int,
        default=3600,
        help="Presigned URL expiry in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the HTML file in the default browser",
    )
    args = parser.parse_args()

    print("Connecting to database...")
    conn = psycopg2.connect(DB_URL)
    try:
        print("Querying clusters...")
        l2_clusters, l1_groups, images = _query_clusters(conn)
        print(f"  {len(l2_clusters)} L2 clusters, {len(l1_groups)} L1 groups, {len(images)} images")

        print("Building hierarchy & generating presigned URLs...")
        hierarchy = _build_hierarchy(l2_clusters, l1_groups, images, args.expiry)

        print("Rendering HTML...")
        out = _render_html(hierarchy, len(l1_groups))

        out_path = Path(args.output).resolve()
        out_path.write_text(out)
        print(f"Wrote {out_path}  (URLs valid for {args.expiry // 60} min)")

        if not args.no_open:
            webbrowser.open(f"file://{out_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
