import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.application import autonomy_worker, observability
from app.core.settings import get_settings
from app.services import memory_service

logging.basicConfig(level=logging.INFO)

_reclaim_task: asyncio.Task | None = None
_autonomy_task: asyncio.Task | None = None
_observability_cleanup_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _reclaim_task, _autonomy_task, _observability_cleanup_task
    _reclaim_task = asyncio.create_task(memory_service.run_memory_reclaim_loop())
    if get_settings().autonomy_enabled:
        _autonomy_task = asyncio.create_task(autonomy_worker.run_autonomy_worker())
    else:
        logging.getLogger(__name__).info("autonomy_enabled=false，Worker 未启动")
    if get_settings().observability_persist_enabled:
        _observability_cleanup_task = asyncio.create_task(
            observability.run_retention_loop()
        )
    yield
    for task in (_reclaim_task, _autonomy_task, _observability_cleanup_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _reclaim_task = None
    _autonomy_task = None
    _observability_cleanup_task = None


def create_app() -> FastAPI:

    application = FastAPI(
        title="AI Customer Service Agent",
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()


@app.get("/health")
async def health():
    return {"status": "ok"}
