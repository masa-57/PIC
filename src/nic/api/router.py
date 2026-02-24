from fastapi import APIRouter, Depends

from nic.api.clusters import router as clusters_router
from nic.api.clusters import view_router as clusters_view_router
from nic.api.gdrive import router as gdrive_router
from nic.api.images import router as images_router
from nic.api.jobs import router as jobs_router
from nic.api.pipeline import router as pipeline_router
from nic.api.products import router as products_router
from nic.api.search import router as search_router
from nic.core.auth import verify_api_key

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])
api_router.include_router(images_router)
api_router.include_router(clusters_router)
api_router.include_router(search_router)
api_router.include_router(jobs_router)
api_router.include_router(pipeline_router)
api_router.include_router(products_router)
api_router.include_router(gdrive_router)

# Browser-accessible routes (auth via standard API key header)
browser_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])
browser_router.include_router(clusters_view_router)
