"""Reflection 域服务（Phase 2）。

模块拆分：lifecycle（状态机/迁移 API，REF-001）、evidence（证据窗口聚合，
REF-002）、triggers（触发与额度，REF-003）、reflector（反思执行器，REF-004）、
evaluation（离线场景集，REF-006）。边界：只写本域三表，只读 memories
（active 且非 hypothetical），不写 Memory/State/Relationship。
"""
