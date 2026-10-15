"""V3.0 Runtime 测试支撑：runtime_* 设置字段注册表（字段名 → 归属 Task）。

任一 RT 任务新增 `runtime_*` 设置字段时必须在此登记；`test_runtime_contracts.py`
的 `test_settings_runtime_fields_are_registered` 会校验登记完整性，防止后续任务
擅自发明字段名或漏登记。RT-001（契约冻结）交付空表。
"""

from __future__ import annotations

V30_RUNTIME_FIELDS: dict[str, str] = {
    "runtime_session_tracking_enabled": "RT-002",
    "runtime_state_versioning_enabled": "RT-003",
    "runtime_context_freeze_enabled": "RT-004",
    "runtime_event_bus_enabled": "RT-005",
    "runtime_loop_optional_stages": "RT-006",
    "runtime_reflect_in_loop_enabled": "RT-011",
    "runtime_inbound_gateway_channels": "RT-013",
    "runtime_outbound_gateway_channels": "RT-014",
    "runtime_six_stage_loop_enabled": "R-15",
    "runtime_orphan_run_timeout_minutes": "RT-018",
    "runtime_orphan_run_sweep_enabled": "RT-018",
}
