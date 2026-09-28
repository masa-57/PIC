# Web UI for browsing and curating clusters

Issue: [#113](https://github.com/masa-57/PIC/issues/113) · Status: design approved in chat 2026-09-28, awaiting spec review

## Goal

Make PIC usable on its own, without n8n or scripts: a small web UI, served by
the API, to browse clusters, run the pipeline, and curate results into products.

**Success criteria**

- On the local compose stack, `http://localhost:8000/ui` shows L2 clusters as
  thumbnail grids, drills into L1 groups, and pages through large catalogs
  without loading the whole hierarchy.
- A user can start a pipeline or clustering run from the UI and watch it finish,
  including its error message when it fails.
- A user can merge groups into a product, split and prune products, and merge
  products, and that curation survives the next clustering run.
- With `PIC_API_KEY` set, the UI requires a login; with `PIC_AUTH_DISABLED=true`
  it does not.
- No Node toolchain or build step. All quality gates pass; new code has unit
  tests, and curation has integration tests.

## Decisions

| Question | Decision |
|---|---|
| How curation survives re-clustering | Products are the durable, human-owned grouping. L1 groups and L2 clusters stay machine suggestions, rebuilt on every run. No schema or clustering change. |
| UI technology | Server-rendered Jinja2 templates plus htmx (vendored, no CDN). No build step. |
| UI auth | Login page sets a signed `HttpOnly` cookie. The JSON API stays header-only. |
| Image upload | In scope (changed 2026-09-28 at user request): the Runs page has a browser folder picker that uploads a local folder's images to the storage inbox in batches, then runs the pipeline. Also `POST /api/v1/images/upload`. |

## Design

### 1. Structure

- New package `src/pic/ui/`:
  - `routes.py`: `APIRouter(prefix="/ui")`, pages and htmx fragments
  - `auth.py`: session cookie and `require_ui_session` dependency
  - `templates/`: Jinja2 templates (`base.html`, one per page, `_fragments/`)
  - `static/`: vendored `htmx.min.js` (pinned version in a comment) and `pic.css`
- `main.py` includes the UI router and mounts `/ui/static`.
- The UI reads the database through services; it never calls the JSON API over HTTP.
- New `src/pic/services/curation.py` holds all product-membership logic, shared
  by the UI and the JSON API.
- Jinja2 already ships with `fastapi[standard]`; no new Python dependency.

### 2. Pages

| Route | Content |
|---|---|
| `/ui` | L2 clusters sorted by `total_images`, as cards: up to 4 thumbnails, image count, group count. 24 per page with htmx "load more" on scroll. A final "Unclustered" card covers L1 groups with no L2 cluster. |
| `/ui/clusters/{id}` | The cluster's L1 groups as rows of member thumbnails, 20 groups per page. `id=unclustered` lists L1 groups with no L2 cluster. Groups whose images already belong to a product show a "✓ product" link. Checkboxes plus action bar (section 4). |
| `/ui/products` | Products newest first, 24 per page: representative thumbnail, title, image count. |
| `/ui/products/{id}` | Product images with checkboxes, editable title/description/tags, image and product actions (section 4). |
| `/ui/jobs` | "Run pipeline" and "Re-cluster" buttons, a URL-ingest textarea (one URL per line), and the 20 most recent jobs: type, status, progress, error, result summary, times. The table polls every 3 s while any job is pending or running and stops otherwise. |
| `/ui/login`, `/ui/logout` | Only meaningful when `PIC_API_KEY` is set. |

- Thumbnails use the storage backend's `get_url(s3_thumbnail_key)`: `/files/...`
  for local storage, presigned URLs for S3 and GCS. Clicking one opens the full
  image (`get_url(s3_key)`) in a CSS lightbox.
- Every page shares a top nav: Clusters, Products, Runs, and Logout when auth is on.
- Pages work without JavaScript for reading; htmx adds paging, polling and actions.

### 3. Auth

- Session token: `hmac.new(PIC_API_KEY, b"pic-ui-session", sha256).hexdigest()`.
  No server-side store; rotating `PIC_API_KEY` ends every session.
- Cookie `pic_session`: `HttpOnly`, `SameSite=Strict`, `Path=/ui`,
  `Max-Age=30 days`, `Secure` when the request scheme is HTTPS.
- `require_ui_session` (dependency on every `/ui` route except login and static):
  - auth disabled: allow
  - auth misconfigured: 503 page, same condition as the API
  - valid cookie (constant-time compare): allow
  - otherwise: redirect to `/ui/login?next=<path>` (303), or for htmx requests
    return 401 with `HX-Redirect: /ui/login`
- `POST /ui/login` compares the submitted key with `hmac.compare_digest`, sets the
  cookie and redirects to a local `next` path (only paths starting with `/ui`).
  A wrong key re-renders the form with an error and status 401.
- Cross-site request protection: every state-changing UI route is `POST` and
  requires the `HX-Request: true` header (400 otherwise), on top of
  `SameSite=Strict`. The login form is exempt; it only sets a cookie for a key
  the submitter already knows.

### 4. Curation

**Rule:** an image belongs to at most one product (`images.product_id`, unchanged).
Clustering never touches products.

**Service functions** (`services/curation.py`, each one transaction, all typed):

| Function | Effect |
|---|---|
| `create_product(db, *, l1_group_ids, image_ids, title, description, tags) -> CurationResult` | New product with the given images plus all images of the given groups. Images already in another product are skipped and counted. Fails with `EmptySelectionError` if nothing is left. |
| `add_to_product(db, product_id, *, l1_group_ids, image_ids) -> CurationResult` | Adds images not yet in any product; images in *another* product are skipped and counted. |
| `remove_from_product(db, product_id, image_ids) -> CurationResult` | Unlinks images. |
| `split_product(db, product_id, image_ids) -> CurationResult` | Moves the images to a new product (title copied with " (split)" appended). |
| `merge_products(db, target_id, source_id) -> CurationResult` | Moves all source images to the target and deletes the source. |

- `CurationResult` reports `product_id`, `added`, `skipped`, `removed`, and
  `deleted_product_ids`.
- Representative image: kept while it is a member, otherwise the member with
  the smallest `created_at`. A product left with no images is deleted.
- Missing product or group: `NotFoundError` (404). Merging a product into itself:
  `InvalidOperationError` (400).

**UI actions:**

- Cluster detail: select groups, then "Make product" or "Add to product…" (product picker).
- Product page: select images, then "Remove" or "Split into new product";
  "Merge into…" (product picker); edit fields; delete product (unlinks images).
- Each action re-renders the affected fragment and shows a one-line result
  ("Created product #12 with 7 images; 2 already in other products were skipped").

**JSON API parity** (thin wrappers around the service):

- `POST /api/v1/products` accepts `l1_group_ids: list[int]` in addition to the
  existing `l1_group_id`. The existing single-group request keeps its current
  behaviour, including 409 when the group already has a product.
- `POST /api/v1/products/{id}/images` with `{"image_ids": [...]}` and/or
  `{"l1_group_ids": [...]}`
- `DELETE /api/v1/products/{id}/images` with `{"image_ids": [...]}`
- `POST /api/v1/products/{id}/merge` with `{"source_product_id": n}`
- `POST /api/v1/products/{id}/split` with `{"image_ids": [...]}` (atomic; the result's
  `product_id` is the new product)

### 5. Security headers

- `/ui` pages get
  `default-src 'self'; img-src 'self' https: data:; frame-ancestors 'none'`.
  `https:` covers presigned S3/GCS thumbnail URLs on any endpoint. No inline
  scripts or styles: htmx is configured through
  `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>`.
- Cache control: `/ui/static` is cacheable for a day; `/ui` pages are `no-store`.

### 6. Errors

- Service errors map to 404/400/409 and re-render the action area with an inline
  message at that status.
- Starting a run while one holds the advisory lock shows "A pipeline or
  clustering job is already running." A full queue shows the existing 429 message.
- Unexpected errors render a small error fragment with the request ID and are
  logged as today.

### 7. Simplification in the same change

- Remove the old HTML page `GET /api/v1/clusters/view`,
  `services/cluster_visualization.py`, `browser_router`, their tests, and the old
  view's CSP branch. The old URL redirects (307) to `/ui`. The JSON endpoint
  `GET /api/v1/clusters/visualization` (2D coordinates) stays for API users.
- Delete `scripts/visualize.py` and `scripts/visualize_clusters.py`; the UI replaces them.
- Remove `_is_l1_unique_conflict` from `api/products.py`: the index it detects was
  dropped in migration 012, so it is dead code (PR 1).
- Drop `cors_origins` and `cors_allow_credentials` and the CORS middleware: the UI
  is same-origin (#119). Record in CHANGELOG with the alternative (reverse proxy)
  for anyone calling the API from a browser on another origin.
- Update README, AGENTS.md and `docs/deployment/self-hosted.md` for the UI.

## Testing

- **Unit, curation:** every service function, including skipped images,
  representative reassignment, empty-product deletion, and self-merge.
- **Unit, auth:** token derivation; dependency outcomes (disabled, misconfigured,
  valid, missing, wrong cookie); `next` limited to `/ui` paths; the
  `HX-Request` requirement on POST routes.
- **Unit, pages:** each page and fragment through `TestClient` with mocked DB:
  key content, pagination links, auth redirect, CSP and cache headers.
- **Unit, API parity:** each new or extended products endpoint.
- **Integration:** curation against real Postgres; a product survives a full
  re-cluster (seed groups, make product, run `run_full_clustering`, product and
  members unchanged).
- **Manual:** the local compose stack with a real image folder, auth on and off.

## Delivery

Three PRs, each shippable alone:

1. Curation service and JSON API parity (no UI).
2. UI shell: auth, layout, Clusters, Cluster detail, Runs; section 7 removals.
3. UI curation: actions on Cluster detail, Products list and Product page.

## Out of scope

Undo, drag-and-drop, editing L1/L2 membership by hand,
multi-user accounts, mobile-specific layouts.
