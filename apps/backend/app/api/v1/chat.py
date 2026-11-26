"""对话接口（V1 API）。

对外暴露 `POST /chat/message`：接收一条用户消息，以 NDJSON 流式返回
角色回复过程中的各类事件（工具步骤、回合元信息、增量 token、结束帧等）。

本模块是「HTTP 传输层」——只负责协议编解码与流式拼装，真正的对话编排
（记忆/情绪/目标/世界状态等）委托给 `app.application.chat_pipeline.stream_chat`。
"""

import json
import logging

import openai
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.auth import require_user
from app.api.v1.deps import get_chat_llm
from app.api.v1.schemas import ChatRequest
from app.services.observability import collector as trace_collector
from app.services.observability.analytics import track_event
from app.application.chat_pipeline import EmptyLLMResponseError, stream_chat
from app.services.tool.step_events import (
    CollectingToolStepSink,
    bind_tool_step_sink,
    reset_tool_step_sink,
)

from app.core import ids

chat_router = APIRouter()

logger = logging.getLogger(__name__)


def _stream_json(payload: dict) -> str:
    """把事件字典序列化成一行 NDJSON（末尾补换行，关闭 ASCII 转义以保留中文）。"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _llm_error(exc: openai.APIStatusError) -> dict:
    """从 OpenAI 风格异常中提取结构化的错误信息。

    上游若返回了规范的 error body（dict），则取 code/message；
    否则退化为仅返回状态码与字符串化的异常本身。
    """
    body_error = exc.body.get("error") if isinstance(exc.body, dict) else None
    if isinstance(body_error, dict):
        return {
            "status": exc.status_code,
            "code": body_error.get("code"),
            "message": body_error.get("message"),
        }
    return {"status": exc.status_code, "message": str(exc)}


@chat_router.post("/chat/message")
async def chat_message(
    request: Request,
    body: ChatRequest,
    llm=Depends(get_chat_llm),
    user_id: str = Depends(require_user),
):
    """流式对话入口。

    请求体只带 content（必需）与可选的 session_id / profile_id：
    - session_id 为空即视为新会话，由服务端生成并在响应头回传；
    - profile_id 缺省时回退到 `x-llm-profile` 请求头，用于选择 LLM 配置。

    返回值是 NDJSON 流（media_type=application/x-ndjson），而非一次性 JSON。
    """
    # 空内容直接拒绝，避免进入昂贵的对话管线。
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="content 不能为空")
    # 未传 session_id 即新建会话；new_session 用于在响应头标记本次是新建。
    session_id = body.session_id or ids.new_id_str()
    new_session = body.session_id is None
    track_event("chat_message", session_new=new_session)
    # LLM profile：优先取请求体，其次取请求头（前端/调试台可动态切换）。
    profile_id = body.profile_id or request.headers.get("x-llm-profile")

    async def generate():
        """生成器：驱动对话管线并把内部事件翻译成 NDJSON 帧。

        事件协议（每帧一行 JSON）：
        - 工具步骤帧：由 step_sink 收集的 tool step，随时可能插入；
        - turn_meta：回合级元信息（角色模式、分析、场景、意图、目标、行为等）；
        - token：模型增量文本（{"delta": ...}）；
        - reply_replace：整段替换已推送的文本；
        - done：结束帧，携带 session_id 与 turn_id。
        """
        turn_id = None
        # 收集本轮工具执行步骤：管线内部通过 sink 上报，这里在事件间隙统一 drain 出去。
        step_sink = CollectingToolStepSink()
        # 把 sink 绑定到当前上下文（ContextVar），退出时必须 reset 归还。
        sink_token = bind_tool_step_sink(step_sink)
        try:
            # trace 定义在下方（闭包捕获），此处按请求生命周期贯穿全链路。
            async for event in stream_chat(
                session_id, user_id, body.content, llm=llm, trace=trace
            ):
                # 每个事件到来前，先把已积累的工具步骤冲刷出去，保证顺序可见。
                for step in step_sink.drain():
                    yield _stream_json(step.to_ndjson_dict())
                kind = event.get("kind")
                if kind == "turn_meta":
                    # 回合元信息：只透传存在的字段，避免向前端推送 null 造成歧义。
                    payload = {
                        "type": "turn_meta",
                        "role_mode": event["role_mode"].model_dump(),
                        "analysis": event["analysis"].model_dump(),
                    }
                    if "scene_intent" in event:
                        payload["scene_intent"] = event["scene_intent"].model_dump()
                    if "scene_state" in event:
                        payload["scene_state"] = event["scene_state"].model_dump(
                            mode="json"
                        )
                    if "intention" in event:
                        # 兼容前端字段命名：把 intention 值改键为 type。
                        intention_payload = event["intention"].model_dump()
                        intention_payload["type"] = intention_payload.pop("intention")
                        payload["intention"] = intention_payload
                    if event.get("current_goal") is not None:
                        payload["current_goal"] = event["current_goal"]
                    if "behavior" in event:
                        payload["behavior"] = event["behavior"]
                    if "mode" in event:
                        payload["mode"] = event["mode"]
                    if "action_intent" in event:
                        payload["action_intent"] = event["action_intent"]
                    if event.get("memory_refs"):
                        payload["memory_refs"] = event["memory_refs"]
                    yield _stream_json(payload)
                elif kind == "token":
                    # 增量文本帧。
                    yield _stream_json({"delta": event["text"]})
                elif kind == "reply_replace":
                    # 整段替换帧：用于回溯修正已推送内容。
                    yield _stream_json({"type": "reply_replace", "text": event["text"]})
                elif kind == "done":
                    # 结束事件里带回 turn_id，供最终帧使用。
                    turn_id = event["turn_id"]
        except openai.APIStatusError as exc:
            # 上游模型服务返回非 2xx：记录日志并回传结构化错误。
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 调用失败", "error": _llm_error(exc)})
            return
        except EmptyLLMResponseError:
            # 模型返回空内容，通常是服务商侧异常或额度问题。
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 返回空响应，请检查模型服务商状态或额度"})
            return
        except Exception:
            # 兜底：任何未预期异常都转成一条错误帧，避免流中断无提示。
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 调用失败"})
            return
        finally:
            # 无论成功/失败/取消，都要冲刷剩余工具步骤并解绑 sink（防 ContextVar 泄漏）。
            for step in step_sink.drain():
                yield _stream_json(step.to_ndjson_dict())
            reset_tool_step_sink(sink_token)
        # 正常结束帧：始终带上 session_id，turn_id 存在时一并返回。
        final = {"done": True, "session_id": session_id}
        if turn_id is not None:
            final["turn_id"] = turn_id
        yield _stream_json(final)

    # 开启一次 trace，其 request_id 会随响应头返回，便于前后端对齐排查。
    trace = trace_collector.get_trace_collector().begin_trace()
    headers = {"X-Session-Id": session_id, "X-Request-Id": trace.request_id}
    if new_session:
        headers["X-Session-New"] = "true"
    if profile_id:
        headers["X-LLM-Profile"] = profile_id
    # 以 NDJSON 流式响应返回，真正的事件由 generate() 异步产出。
    return StreamingResponse(
        generate(), media_type="application/x-ndjson", headers=headers
    )
