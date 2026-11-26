"""亚丝娜 Personality 演化声明（V2.1.0 AGENT-002，新增文件不改既有资产）。

轴集 / 基线 / 硬边界在定义期声明：baseline 从 Persona 静态资产导出
（behavior_policy stage_params 的 initiative 阶梯、personality 文本基调），
bound 为归一化 0~1 刻度上的最大漂移幅度。运行时只读；唯一写入方为
Evolution Engine（AGENT-005），永不写回本文件。
"""

PERSONALITY_AXES: dict[str, dict[str, float]] = {
    # 主动轴：stranger=passive / partner=proactive 的行为阶梯 → 早期偏谨慎
    "assertiveness": {"baseline": 0.30, "bound": 0.20},
    # 亲近轴：温柔基调，亲和表达为常态
    "warmth": {"baseline": 0.70, "bound": 0.20},
    # 求知轴：对用户与世界的了解意愿（goals.py 关心话题倾向）
    "curiosity": {"baseline": 0.60, "bound": 0.20},
    # 耐性轴：追问与重复的容忍基线
    "patience": {"baseline": 0.60, "bound": 0.15},
}

CHARACTER_ID = "asuna"
