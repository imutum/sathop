from fastapi import APIRouter

from . import (
    admin,
    batches,
    bundles,
    events,
    metrics,
    progress,
    receivers,
    rollout,
    shared,
    stream,
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
]:
    router.include_router(mod.router)
