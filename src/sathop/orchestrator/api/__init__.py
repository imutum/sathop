from fastapi import APIRouter

from . import (
    admin,
    batches,
    bundles,
    deliveries,
    events,
    metrics,
    progress,
    receivers,
    rollout,
    shared,
    stream,
    templates,
    timing,
    workers,
)

router = APIRouter(prefix="/api")
for mod in [
    workers,
    receivers,
    batches,
    events,
    admin,
    rollout,
    stream,
    metrics,
    progress,
    bundles,
    shared,
    timing,
    deliveries,
    templates,
]:
    router.include_router(mod.router)
