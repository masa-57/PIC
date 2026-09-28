"""Web UI routes. Pages render Jinja2 templates; htmx requests get fragments."""

import hmac
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pic.api.deps import create_and_dispatch_job, get_db, get_or_404
from pic.config import settings
from pic.core.auth import AuthMode, get_auth_mode
from pic.core.constants import IMAGE_EXTENSIONS
from pic.models.db import JobStatus, JobType, Product
from pic.models.schemas import UploadOut, UrlIngestRequest, _validate_tag_list
from pic.services import browse, curation
from pic.services.uploads import UploadedFile, store_uploads
from pic.ui.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    require_htmx,
    require_ui_session,
    safe_next,
    session_token,
)
from pic.ui.templating import templates

router = APIRouter(prefix="/ui", dependencies=[Depends(require_ui_session)], include_in_schema=False)
public_router = APIRouter(prefix="/ui", include_in_schema=False)
legacy_router = APIRouter(include_in_schema=False)


@legacy_router.get("/api/v1/clusters/view")
async def legacy_cluster_view() -> RedirectResponse:
    """The old server-rendered cluster page moved to the web UI."""
    return RedirectResponse("/ui", status_code=307)


@public_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next_path: str = Query("/ui", alias="next")) -> Response:
    if get_auth_mode() != AuthMode.ENABLED:
        return RedirectResponse(safe_next(next_path), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": safe_next(next_path), "error": None})


@public_router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    api_key: str = Form(""),
    next_path: str = Form("/ui", alias="next"),
) -> Response:
    target = safe_next(next_path)
    if get_auth_mode() != AuthMode.ENABLED:
        return RedirectResponse(target, status_code=303)
    if not hmac.compare_digest(api_key.encode(), settings.api_key.encode()):
        return templates.TemplateResponse(
            request, "login.html", {"next": target, "error": "Wrong API key"}, status_code=401
        )
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_token(settings.api_key),
        max_age=SESSION_MAX_AGE,
        path="/ui",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@public_router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/ui/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/ui")
    return response


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("", response_class=HTMLResponse)
async def clusters_page(
    request: Request,
    offset: int = Query(0, ge=0, le=settings.max_pagination_offset),
    db: AsyncSession = Depends(get_db),
) -> Response:
    page = await browse.list_clusters(db, offset)
    unclustered = None if page.has_more else await browse.unclustered_card(db)
    context = {"page": page, "unclustered": unclustered, "active": "clusters"}
    if _is_htmx(request) and offset > 0:
        return templates.TemplateResponse(request, "_fragments/cluster_cards.html", context)
    return templates.TemplateResponse(request, "clusters.html", context)


@router.get("/clusters/{ref}", response_class=HTMLResponse)
async def cluster_detail_page(
    request: Request,
    ref: str,
    offset: int = Query(0, ge=0, le=settings.max_pagination_offset),
    db: AsyncSession = Depends(get_db),
) -> Response:
    title = await browse.get_cluster_title(db, ref)
    if title is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    groups = await browse.list_groups(db, ref, offset)
    context = {
        "title": title,
        "groups": groups,
        "ref": ref,
        "active": "clusters",
        "product_choices": await browse.list_product_choices(db),
        "message": None,
    }
    if _is_htmx(request) and offset > 0:
        return templates.TemplateResponse(request, "_fragments/group_rows.html", context)
    return templates.TemplateResponse(request, "cluster_detail.html", context)


_RUN_TYPES = {"pipeline": JobType.PIPELINE, "cluster": JobType.CLUSTER_FULL, "gdrive": JobType.GDRIVE_SYNC}
_RUN_LABELS = {"pipeline": "pipeline run", "cluster": "re-cluster", "gdrive": "Google Drive sync"}
_ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


async def _job_views(db: AsyncSession) -> list[browse.JobView]:
    jobs = await browse.recent_jobs(db)
    typical = await browse.typical_durations(db) if any(j.status in _ACTIVE_STATUSES for j in jobs) else {}
    now = datetime.now(UTC)
    return [browse.job_view(job, now, typical) for job in jobs]


async def _jobs_table(
    request: Request,
    db: AsyncSession,
    message: str | None = None,
    message_kind: str = "ok",
    status_code: int = 200,
) -> Response:
    views = await _job_views(db)
    context = {
        "views": views,
        "polling": any(v.active for v in views),
        "message": message,
        "message_kind": message_kind,
    }
    return templates.TemplateResponse(request, "_fragments/jobs_table.html", context, status_code=status_code)


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    views = await _job_views(db)
    context = {
        "views": views,
        "polling": any(v.active for v in views),
        "message": None,
        "active": "jobs",
        "storage": browse.storage_info(),
        "max_upload_bytes": settings.max_upload_size_mb * 1024 * 1024,
        "image_extensions": ",".join(sorted(IMAGE_EXTENSIONS)),
        "gdrive_configured": browse.gdrive_configured(),
        "gdrive_folder_id": settings.gdrive_folder_id,
    }
    return templates.TemplateResponse(request, "jobs.html", context)


@router.get("/jobs/table", response_class=HTMLResponse)
async def jobs_table(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await _jobs_table(request, db)


@router.post("/jobs/run/{kind}", response_class=HTMLResponse, dependencies=[Depends(require_htmx)])
async def start_run(
    request: Request,
    kind: Literal["pipeline", "cluster", "gdrive"],
    db: AsyncSession = Depends(get_db),
) -> Response:
    if kind == "gdrive" and not browse.gdrive_configured():
        return await _jobs_table(request, db, "Google Drive sync is not configured.", "error", status_code=400)
    if await browse.has_active_clustering_job(db):
        return await _jobs_table(
            request, db, "A pipeline or clustering job is already running.", "error", status_code=409
        )
    try:
        await create_and_dispatch_job(db, _RUN_TYPES[kind], None)
    except HTTPException as exc:
        return await _jobs_table(request, db, str(exc.detail), "error", status_code=exc.status_code)
    return await _jobs_table(request, db, f"Started {_RUN_LABELS[kind]}.")


@router.post("/jobs/url-ingest", response_class=HTMLResponse, dependencies=[Depends(require_htmx)])
async def start_url_ingest(
    request: Request,
    urls: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    lines = [line.strip() for line in urls.splitlines() if line.strip()]
    try:
        body = UrlIngestRequest.model_validate({"urls": lines, "auto_pipeline": True})
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"] if exc.errors() else "Invalid URLs"
        return await _jobs_table(request, db, f"Could not ingest: {reason}", "error", status_code=400)
    params = {"urls": [str(u) for u in body.urls], "auto_pipeline": True}
    try:
        await create_and_dispatch_job(db, JobType.URL_INGEST, params)
    except HTTPException as exc:
        return await _jobs_table(request, db, str(exc.detail), "error", status_code=exc.status_code)
    return await _jobs_table(request, db, f"Ingesting {len(lines)} URL(s); a pipeline run follows.")


@router.post("/upload", response_model=UploadOut, dependencies=[Depends(require_htmx)])
async def upload_images_ui(files: list[UploadFile] = File(...)) -> UploadOut:
    """Store one batch of images picked with the folder dialog (upload.js sends several batches)."""
    uploaded = [UploadedFile(name=f.filename or "image", data=await f.read()) for f in files]
    result = await store_uploads(uploaded)
    return UploadOut.model_validate({"stored": len(result.stored), "keys": result.stored, "skipped": result.skipped})


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def _groups_form(
    request: Request,
    db: AsyncSession,
    ref: str,
    offset: int,
    message: str,
    message_kind: str = "ok",
    message_link: str | None = None,
    status_code: int = 200,
) -> Response:
    title = await browse.get_cluster_title(db, ref)
    if title is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    context = {
        "ref": ref,
        "groups": await browse.list_groups(db, ref, offset),
        "product_choices": await browse.list_product_choices(db),
        "message": message,
        "message_kind": message_kind,
        "message_link": message_link,
    }
    return templates.TemplateResponse(request, "_fragments/groups_form.html", context, status_code=status_code)


@router.post("/clusters/{ref}/make-product", response_class=HTMLResponse, dependencies=[Depends(require_htmx)])
async def make_product(
    request: Request,
    ref: str,
    group_ids: list[int] = Form(default=[]),
    offset: int = Form(0),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        outcome = await curation.create_product(db, l1_group_ids=group_ids)
    except curation.CurationError as exc:
        return await _groups_form(request, db, ref, offset, str(exc), "error", status_code=exc.status_code)
    message = f"Created product #{outcome.product_id} with {_plural(outcome.added, 'image')}"
    if outcome.skipped:
        message += f"; {outcome.skipped} already in other products were skipped"
    return await _groups_form(request, db, ref, offset, message, message_link=f"/ui/products/{outcome.product_id}")


@router.post("/clusters/{ref}/add-to-product", response_class=HTMLResponse, dependencies=[Depends(require_htmx)])
async def add_groups_to_product(
    request: Request,
    ref: str,
    product_id: int = Form(...),
    group_ids: list[int] = Form(default=[]),
    offset: int = Form(0),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        outcome = await curation.add_to_product(db, product_id, l1_group_ids=group_ids)
    except curation.CurationError as exc:
        return await _groups_form(request, db, ref, offset, str(exc), "error", status_code=exc.status_code)
    message = f"Added {_plural(outcome.added, 'image')} to product #{product_id}"
    if outcome.skipped:
        message += f"; {outcome.skipped} already in other products were skipped"
    return await _groups_form(request, db, ref, offset, message, message_link=f"/ui/products/{product_id}")


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    offset: int = Query(0, ge=0, le=settings.max_pagination_offset),
    db: AsyncSession = Depends(get_db),
) -> Response:
    page = await browse.list_products(db, offset)
    context = {"page": page, "active": "products"}
    if _is_htmx(request) and offset > 0:
        return templates.TemplateResponse(request, "_fragments/product_cards.html", context)
    return templates.TemplateResponse(request, "products.html", context)


async def _product_context(db: AsyncSession, product_id: int) -> dict[str, object]:
    product = await browse.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    choices = [c for c in await browse.list_product_choices(db) if c[0] != product_id]
    return {"product": product, "merge_choices": choices, "active": "products"}


@router.get("/products/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    return templates.TemplateResponse(request, "product_detail.html", await _product_context(db, product_id))


@router.post("/products/{product_id}/edit", response_class=HTMLResponse, dependencies=[Depends(require_htmx)])
async def edit_product(
    request: Request,
    product_id: int,
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    product = await get_or_404(db, Product, product_id, "Product not found")
    try:
        parsed_tags = _validate_tag_list(_parse_tags(tags))
    except ValueError as exc:
        detail = await browse.get_product(db, product_id)
        context = {"product": detail, "fields_message": str(exc), "fields_message_kind": "error"}
        return templates.TemplateResponse(request, "_fragments/product_fields.html", context, status_code=400)
    product.title = title.strip() or None
    product.description = description.strip() or None
    product.tags = parsed_tags or None
    await db.commit()
    detail = await browse.get_product(db, product_id)
    context = {"product": detail, "fields_message": "Saved.", "fields_message_kind": "ok"}
    return templates.TemplateResponse(request, "_fragments/product_fields.html", context)


@router.post("/products/{product_id}/delete", dependencies=[Depends(require_htmx)])
async def delete_product_ui(product_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    product = await get_or_404(db, Product, product_id, "Product not found")
    await db.delete(product)
    await db.commit()
    return Response(status_code=200, headers={"HX-Redirect": "/ui/products"})
