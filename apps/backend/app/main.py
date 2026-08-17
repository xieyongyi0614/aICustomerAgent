from fastapi import FastAPI
from app.api.v1.router import api_router


def create_app() -> FastAPI:

    application = FastAPI(
        title="AI Customer Service Agent",
    )
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()


@app.get("/health")
async def health():
    return {"status": "ok"}
