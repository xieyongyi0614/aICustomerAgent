"""services 包声明。

旧顶层模块名（PEP 562 惰性映射）已随重构收口删除——全仓零引用后清理（2026-10-09），
新代码一律 import 真实路径（如 `app.services.conversation.service`，
而非 `from app.services import conversation_service`）。
"""
