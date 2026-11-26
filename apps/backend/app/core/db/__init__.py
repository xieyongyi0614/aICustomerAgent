"""ORM 模型包门面：全领域模型统一 re-export，导入路径 `app.core.db` 保持不变。

全部模型子模块必须在此导入，保证 `Base.metadata` 完整（migrations/env.py
仅导入本包，alembic autogenerate 依赖齐表注册）。
"""

from app.core.db.autonomy import (
    ActionRecordRow,
    ActionScheduleRow,
    BackgroundJobRow,
    LoopRunRow,
    OutboxEventRow,
    ProactiveActionRow,
    TriggerRegistryRow,
)
from app.core.db.base import Base, VectorType
from app.core.db.car import (
    CarLoanRow,
    CarMileageLogRow,
    CarProfileRow,
    CarServiceRecordRow,
)
from app.core.db.character import (
    CharacterStateRow,
    EmotionHistoryRow,
    PersonalityStateRow,
)
from app.core.db.conversation import (
    Conversation,
    ConversationSummary,
    Message,
    SceneStateRow,
)
from app.core.db.development import DevelopmentChangeRow, DevelopmentStateRow
from app.core.db.engine import SessionLocal, create_engine_from_url, engine
from app.core.db.goal import GoalPlanRow, GoalRow
from app.core.db.identity import (
    BriefingPreferenceRow,
    ChannelIdentityRow,
    FeishuDeliveryRow,
    FeishuDedupeLedgerRow,
    UserRow,
)
from app.core.db.ledger import (
    LedgerAccountRow,
    LedgerCategoryRow,
    LedgerEntryRow,
    LifeTaskRow,
)
from app.core.db.memory import Memory, MemoryCandidateRow, MemoryLinkRow
from app.core.db.reflection import EvidenceLinkRow, InsightRow, ReflectionRunRow
from app.core.db.relationship import (
    RelationshipConflictRow,
    RelationshipEventRow,
    RelationshipMilestoneRow,
    RelationshipSnapshotRow,
    RelationshipStateRow,
)
from app.core.db.release import AppReleaseArtifactRow, AppReleaseRow
from app.core.db.runtime import (
    AgentMetricSnapshotRow,
    AgentStateSnapshotRow,
    DecisionRecordRow,
    EvaluationReportRow,
    LlmCallRecordRow,
    PromptSnapshotRow,
    RuntimeTraceRow,
)
from app.core.db.world import (
    DailyPlanRow,
    UserSituationRow,
    WorldEntityRow,
    WorldEventRow,
    WorldRow,
    WorldSnapshotRow,
)

__all__ = [
    "ActionRecordRow",
    "ActionScheduleRow",
    "AgentMetricSnapshotRow",
    "AgentStateSnapshotRow",
    "AppReleaseArtifactRow",
    "AppReleaseRow",
    "BackgroundJobRow",
    "Base",
    "BriefingPreferenceRow",
    "CarLoanRow",
    "CarMileageLogRow",
    "CarProfileRow",
    "CarServiceRecordRow",
    "ChannelIdentityRow",
    "CharacterStateRow",
    "Conversation",
    "ConversationSummary",
    "DailyPlanRow",
    "DecisionRecordRow",
    "DevelopmentChangeRow",
    "DevelopmentStateRow",
    "EmotionHistoryRow",
    "EvaluationReportRow",
    "EvidenceLinkRow",
    "FeishuDeliveryRow",
    "FeishuDedupeLedgerRow",
    "GoalPlanRow",
    "GoalRow",
    "InsightRow",
    "LedgerAccountRow",
    "LedgerCategoryRow",
    "LedgerEntryRow",
    "LifeTaskRow",
    "LlmCallRecordRow",
    "LoopRunRow",
    "Memory",
    "MemoryCandidateRow",
    "MemoryLinkRow",
    "Message",
    "OutboxEventRow",
    "PersonalityStateRow",
    "PromptSnapshotRow",
    "ProactiveActionRow",
    "ReflectionRunRow",
    "RelationshipConflictRow",
    "RelationshipEventRow",
    "RelationshipMilestoneRow",
    "RelationshipSnapshotRow",
    "RelationshipStateRow",
    "RuntimeTraceRow",
    "SceneStateRow",
    "SessionLocal",
    "TriggerRegistryRow",
    "UserRow",
    "UserSituationRow",
    "VectorType",
    "WorldEntityRow",
    "WorldEventRow",
    "WorldRow",
    "WorldSnapshotRow",
    "create_engine_from_url",
    "engine",
]
