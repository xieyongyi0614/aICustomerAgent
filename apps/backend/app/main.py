import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.db import create_tables

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(application: FastAPI):
    create_tables()
    yield


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
