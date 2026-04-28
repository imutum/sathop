from fastapi import APIRouter

from . import admin, batches, bundles, events, metrics, progress, receivers, shared, stream, timing, workers

router = APIRouter(prefix="/api")
for mod in [workers, receivers, batches, events, admin, stream, metrics, progress, bundles, shared, timing]:
    router.include_router(mod.router)
