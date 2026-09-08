import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.rate_limit import chat_rate_limit_middleware
from app.api.v1.router import api_router
from app.application import autonomy_worker, observability, world_engine
from app.core.settings import get_settings
from app.services import memory_service

logging.basicConfig(level=logging.INFO)

_reclaim_task: asyncio.Task | None = None
_autonomy_task: asyncio.Task | None = None
_observability_cleanup_task: asyncio.Task | None = None
_world_maintenance_task: asyncio.Task | None = None
_action_maintenance_task: asyncio.Task | None = None
_v2_job_worker_task: asyncio.Task | None = None
_life_loop_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _reclaim_task, _autonomy_task, _observability_cleanup_task
    global _world_maintenance_task, _action_maintenance_task, _v2_job_worker_task
    global _life_loop_task
    _reclaim_task = asyncio.create_task(memory_service.run_memory_reclaim_loop())
    observability.set_main_loop(asyncio.get_running_loop())
    if (
        get_settings().v2_memory_enabled
        or get_settings().v2_reflection_enabled
        or get_settings().v2_development_enabled
        or get_settings().v2_relationship_evolved_enabled
        or get_settings().v2_autonomy_advanced_enabled
    ):
        from app.services.memory2.job_worker import run_job_worker_loop

        _v2_job_worker_task = asyncio.create_task(run_job_worker_loop())
    if get_settings().v2_autonomy_advanced_enabled:
        from app.services.goal_planning import register_runtime

        register_runtime()
    if get_settings().v2_reflection_enabled:
        from app.services.reflection.reflector import register_executor
        from app.services.reflection.triggers import register_with_job_worker

        register_with_job_worker()
        register_executor()
    if get_settings().v2_development_enabled:
        from app.services.development.audit import register_rollback_listener
        from app.services.development.policy import register_runtime

        register_runtime()
        register_rollback_listener()
    if get_settings().v2_relationship_evolved_enabled:
        from app.services.relationship_narrative import register_narrative_listener

        register_narrative_listener()
    if get_settings().v2_life_loop_enabled:
        from app.application.life_loop import run_life_loop_worker

        _life_loop_task = asyncio.create_task(run_life_loop_worker())
        logging.getLogger(__name__).info("v2 life loop 已接管周期调度（归并 autonomy/world/action 三循环）")
    else:
        if get_settings().autonomy_enabled:
            _autonomy_task = asyncio.create_task(autonomy_worker.run_autonomy_worker())
        else:
            logging.getLogger(__name__).info("autonomy_enabled=false，Worker 未启动")
        if get_settings().world_enabled:
            _world_maintenance_task = asyncio.create_task(
                world_engine.run_world_maintenance_loop()
            )
        if get_settings().action_enabled:
            from app.application.action_engine import run_action_retry_loop

            _action_maintenance_task = asyncio.create_task(run_action_retry_loop())
    if get_settings().observability_persist_enabled:
        _observability_cleanup_task = asyncio.create_task(
            observability.run_retention_loop()
        )
    yield
    for task in (
        _reclaim_task,
        _autonomy_task,
        _observability_cleanup_task,
        _world_maintenance_task,
        _action_maintenance_task,
        _v2_job_worker_task,
        _life_loop_task,
    ):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _reclaim_task = None
    _autonomy_task = None
    _observability_cleanup_task = None
    _world_maintenance_task = None
    _action_maintenance_task = None
    _v2_job_worker_task = None
    _life_loop_task = None


def create_app() -> FastAPI:

    application = FastAPI(
        title="AI Customer Service Agent",
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix="/api/v1")
    application.middleware("http")(chat_rate_limit_middleware)
    return application


app = create_app()


@app.get("/health")
async def health():
    return {"status": "ok"}
