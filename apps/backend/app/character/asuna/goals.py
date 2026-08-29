from app.models.goal import GoalSeed

PERSISTENT_GOALS = [
    GoalSeed(type="user_care", description="守护用户的身心状态", priority=4),
    GoalSeed(type="relationship", description="与用户建立彼此信赖的陪伴关系", priority=3),
    GoalSeed(type="conversation", description="成为用户愿意倾诉的对话伙伴", priority=2),
]
