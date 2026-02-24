"""Generate a self-contained HTML page visualizing L2 → L1 → Image clusters."""

import html as html_mod
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pic.models.db import Image, L1Group, L2Cluster
from pic.services.image_store import generate_presigned_url

# ---------------------------------------------------------------------------
# DB queries (async)
# ---------------------------------------------------------------------------


async def _load_hierarchy(
    db: AsyncSession,
) -> tuple[Sequence[Row[Any]], Sequence[Row[Any]], Sequence[Row[Any]]]:
    """Load L2 clusters, L1 groups, and images from the database."""
    l2_result = await db.execute(
        select(
            L2Cluster.id,
            L2Cluster.label,
            L2Cluster.member_count,
            L2Cluster.total_images,
        ).order_by(L2Cluster.total_images.desc())
    )
    l2_clusters = l2_result.all()

    l1_result = await db.execute(
        select(
            L1Group.id,
            L1Group.representative_image_id,
            L1Group.member_count,
            L1Group.l2_cluster_id,
        ).order_by(text("l2_cluster_id NULLS LAST"), L1Group.member_count.desc())
    )
    l1_groups = l1_result.all()

    img_result = await db.execute(
        select(
            Image.id,
            Image.filename,
            Image.s3_key,
            Image.s3_thumbnail_key,
            Image.l1_group_id,
            Image.width,
            Image.height,
        )
        .where(Image.has_embedding == 1)
        .order_by(Image.l1_group_id, Image.created_at)
    )
    images = img_result.all()

    return l2_clusters, l1_groups, images


# ---------------------------------------------------------------------------
# Build hierarchy with presigned URLs
# ---------------------------------------------------------------------------


def _presigned(s3_key: str, expiry: int) -> str:
    return generate_presigned_url(s3_key, expires_in=expiry)


def _build_hierarchy(
    l2_clusters: Sequence[Row[Any]],
    l1_groups: Sequence[Row[Any]],
    images: Sequence[Row[Any]],
    expiry: int,
) -> list[dict[str, Any]]:
    img_by_l1: dict[int | None, list[Row[Any]]] = {}
    for img in images:
        img_by_l1.setdefault(img.l1_group_id, []).append(img)

    l1_by_l2: dict[int | None, list[Row[Any]]] = {}
    for g in l1_groups:
        l1_by_l2.setdefault(g.l2_cluster_id, []).append(g)

    def _img_dict(img: Row[Any], rep_id: str | None) -> dict[str, Any]:
        thumb_key = img.s3_thumbnail_key or img.s3_key
        return {
            "id": img.id,
            "filename": img.filename,
            "thumb_url": _presigned(thumb_key, expiry),
            "full_url": _presigned(img.s3_key, expiry),
            "is_rep": img.id == rep_id,
            "width": img.width,
            "height": img.height,
        }

    def _group_dict(g: Row[Any]) -> dict[str, Any]:
        return {
            "id": g.id,
            "rep_id": g.representative_image_id,
            "member_count": g.member_count,
            "images": [_img_dict(i, g.representative_image_id) for i in img_by_l1.get(g.id, [])],
        }

    hierarchy: list[dict[str, Any]] = []

    for l2 in l2_clusters:
        hierarchy.append(
            {
                "id": l2.id,
                "label": l2.label,
                "member_count": l2.member_count,
                "total_images": l2.total_images,
                "groups": [_group_dict(g) for g in l1_by_l2.get(l2.id, [])],
            }
        )

    orphans = l1_by_l2.get(None, [])
    if orphans:
        hierarchy.append(
            {
                "id": None,
                "label": "Unclustered (no L2)",
                "member_count": len(orphans),
                "total_images": sum(g.member_count for g in orphans),
                "groups": [_group_dict(g) for g in orphans],
            }
        )

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
.l2 { border:1px solid var(--border); border-radius:12px; margin-bottom:24px;
      overflow:hidden; }
.l2-hdr { background:var(--accent2); padding:16px 20px; cursor:pointer;
          display:flex; justify-content:space-between; align-items:center;
          user-select:none; }
.l2-hdr:hover { background:#1a4a7a; }
.l2-hdr h2 { font-size:18px; font-weight:600; }
.l2-meta { font-size:13px; color:var(--muted); display:flex; gap:16px;
           align-items:center; }
.l2-body { padding:16px; }
.l2-body.hide { display:none; }
.l1 { background:var(--l1-bg); border:1px solid var(--border); border-radius:8px;
      padding:12px; margin-bottom:12px; }
.l1-hdr { font-size:14px; font-weight:500; margin-bottom:8px; color:var(--muted); }
.l1-hdr strong { color:var(--text); }
.grid { display:flex; flex-wrap:wrap; gap:8px; }
.card { position:relative; width:120px; height:120px; border-radius:6px;
        overflow:hidden; border:2px solid transparent; cursor:pointer;
        transition:transform .15s,border-color .15s; }
.card:hover { transform:scale(1.05); border-color:var(--accent); }
.card.rep { border-color:var(--rep); box-shadow:0 0 8px rgba(16,185,129,.4); }
.card img { width:100%; height:100%; object-fit:cover; }
.card .badge { position:absolute; top:4px; right:4px; background:var(--rep);
               color:#000; font-size:10px; font-weight:700; padding:1px 5px;
               border-radius:4px; }
.card .fname { position:absolute; bottom:0; left:0; right:0;
               background:rgba(0,0,0,.7); font-size:10px; padding:2px 4px;
               white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
               opacity:0; transition:opacity .15s; }
.card:hover .fname { opacity:1; }
.chev { font-size:20px; transition:transform .2s; }
.chev.shut { transform:rotate(-90deg); }
.lb { display:none; position:fixed; inset:0; background:rgba(0,0,0,.92);
      z-index:1000; justify-content:center; align-items:center;
      flex-direction:column; }
.lb.on { display:flex; }
.lb img { max-width:90vw; max-height:80vh; border-radius:8px; }
.lb .cap { margin-top:12px; font-size:14px; color:var(--muted); }
.lb .x { position:absolute; top:20px; right:24px; font-size:28px;
         cursor:pointer; color:var(--text); }
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
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('.card').forEach(card=>{
    card.addEventListener('click',e=>{
      e.stopPropagation();
      lb(card.dataset.fullUrl||'', card.dataset.caption||'');
    });
  });
  document.querySelectorAll('.l2-hdr').forEach(header=>{
    header.addEventListener('click',()=>tog(header.dataset.clusterId));
  });
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')lbOff()});
"""


def _esc(s: str) -> str:
    return html_mod.escape(s, quote=True).replace("'", "&#39;")


def render_html(hierarchy: list[dict[str, Any]], total_l1: int) -> str:
    """Render the full self-contained HTML visualization page."""
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
                    f"<div class='card{rc}' data-full-url='{fu}' data-caption='{fn_full}'>"
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
            f"<div class='l2-hdr' data-cluster-id='{_esc(cid)}'>"
            f"<h2>{label}</h2>"
            f"<div class='l2-meta'><span>{len(c['groups'])} L1 groups</span>"
            f"<span>{img_count} images</span>"
            f"<span class='chev shut' id='c-{cid}'>&#9660;</span></div></div>"
            f"<div class='l2-body hide' id='b-{cid}'>"
            f"{''.join(groups_parts)}</div></div>"
        )

    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        f"<title>PIC Cluster Visualization</title><style>{_CSS}</style></head>"
        "<body><h1>PIC Cluster Visualization</h1>"
        f"<div class='stats'><span>{total_imgs} images</span>"
        f"<span>{total_l2} L2 clusters</span>"
        f"<span>{total_l1} L1 groups</span></div>"
        "<div class='toolbar'>"
        "<button class='btn' onclick='togAll()'>Expand / Collapse All</button>"
        "</div>"
        f"<div id='clusters'>{''.join(parts)}</div>"
        "<div class='lb' id='lb' onclick='lbOff()'>"
        "<span class='x'>&times;</span>"
        "<img id='lb-i' src='' alt=''>"
        "<div class='cap' id='lb-c'></div></div>"
        f"<script>{_JS}</script></body></html>"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_visualization_html(db: AsyncSession, url_expiry: int = 3600) -> str:
    """Generate the full cluster visualization HTML page."""
    l2_clusters, l1_groups, images = await _load_hierarchy(db)
    hierarchy = _build_hierarchy(l2_clusters, l1_groups, images, url_expiry)
    return render_html(hierarchy, len(l1_groups))
