import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.services import memory_service

logging.basicConfig(level=logging.INFO)

_reclaim_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _reclaim_task
    _reclaim_task = asyncio.create_task(memory_service.run_memory_reclaim_loop())
    yield
    if _reclaim_task is not None:
        _reclaim_task.cancel()
        try:
            await _reclaim_task
        except asyncio.CancelledError:
            pass
        _reclaim_task = None


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
