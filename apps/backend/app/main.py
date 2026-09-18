import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.rate_limit import chat_rate_limit_middleware
from app.api.v1.router import api_router
from app.application import observability
from app.application import agent_evolution_worker
from app.channels.feishu import delivery
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.core.settings import get_settings, unknown_versioned_env_keys
from app.core.settings.enablement import validate_enablement_chain
from app.services import memory_service, proactive_delivery
from app.services.tool import channel_tools
from app.services.tool.ext_api import get_manifest_loader
from app.application.life_loop import run_life_loop_worker
from app.services.development.audit import register_rollback_listener
from app.services.development.policy import (
    register_runtime as register_development_runtime,
)
from app.services.goal_planning import register_runtime as register_goal_runtime
from app.services.memory2.job_worker import run_job_worker_loop
from app.services.planning.revision_listener import (
    register_runtime as register_plan_revision_listener,
)
from app.services.reflection.reflector import register_executor
from app.services.reflection.triggers import register_with_job_worker
from app.services.relationship_narrative import register_narrative_listener

logging.basicConfig(level=logging.INFO)

_reclaim_task: asyncio.Task | None = None
_observability_cleanup_task: asyncio.Task | None = None
_job_worker_task: asyncio.Task | None = None
_life_loop_task: asyncio.Task | None = None
_agent_evolution_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _reclaim_task, _observability_cleanup_task
    global _job_worker_task
    global _life_loop_task, _agent_evolution_task
    validate_enablement_chain(get_settings())
    for unknown_key in unknown_versioned_env_keys():
        logging.getLogger(__name__).warning(
            "环境变量 %s 不对应任何 settings 字段，已被静默忽略（字段是否已改名？）",
            unknown_key,
        )
    _reclaim_task = asyncio.create_task(memory_service.run_memory_reclaim_loop())
    observability.set_main_loop(asyncio.get_running_loop())
    _job_worker_task = asyncio.create_task(run_job_worker_loop())
    register_goal_runtime()
    register_with_job_worker()
    register_executor()
    if get_settings().plan_reflection_enabled:
        register_plan_revision_listener()
    register_development_runtime()
    register_rollback_listener()
    register_narrative_listener()
    from app.services.world.event_bridge import register_character_event_listeners

    register_character_event_listeners()
    _life_loop_task = asyncio.create_task(run_life_loop_worker())
    logging.getLogger(__name__).info("life loop 已接管周期调度（归并 autonomy/world/action 三循环）")
    if get_settings().feishu_enabled:
        proactive_delivery.register_proactive_outbound(
            proactive_delivery.ProactiveOutbound(
                channel=FEISHU_CHANNEL, send=delivery.send_proactive
            )
        )
        logging.getLogger(__name__).info("主动消息出站端口已注册：%s", FEISHU_CHANNEL)
        if get_settings().tool_channel_enabled:
            channel_tools.register_channel_adapter(
                FEISHU_CHANNEL, delivery.FeishuChannelAdapter()
            )
            logging.getLogger(__name__).info(
                "工具层通道出站适配器已注册：%s", FEISHU_CHANNEL
            )
    if get_settings().tool_external_api_enabled:
        report = get_manifest_loader().load(get_settings().tool_ext_manifest_path)
        logging.getLogger(__name__).info(
            "外部 API 工具清单加载完成：path=%s loaded=%d skipped=%d",
            report.path or "<未配置>",
            len(report.loaded),
            len(report.skipped),
        )
    if get_settings().observability_persist_enabled:
        _observability_cleanup_task = asyncio.create_task(
            observability.run_retention_loop()
        )
    _agent_evolution_task = asyncio.create_task(
        agent_evolution_worker.run_agent_evolution_worker()
    )
    logging.getLogger(__name__).info(
        "agent evolution worker 已启动（指标快照 + 人格编译 + goal rebalance）"
    )
    yield
    for task in (
        _reclaim_task,
        _observability_cleanup_task,
        _job_worker_task,
        _life_loop_task,
        _agent_evolution_task,
    ):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _reclaim_task = None
    _observability_cleanup_task = None
    _job_worker_task = None
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
