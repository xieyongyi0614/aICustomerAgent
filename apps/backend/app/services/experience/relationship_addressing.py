"""V2.2.0 CHAR-004：关系快照 → 表达档的确定性映射。

只读 relationship_state 投影做翻译；D1/D2/D3/D5、里程碑、冲突状态机
零改动，不新增任何关系数学。
"""

from app.character.asuna.relationship_lexicon import (
    ADDRESSING_COMFORT_HIGH,
    ADDRESSING_COMFORT_LOW,
    ADDRESSING_EXPRESSIVENESS_LADDER,
    ADDRESSING_FAMILIARITY_HIGH,
    ADDRESSING_FAMILIARITY_LOW,
    ADDRESSING_INITIATIVE_LADDER,
    ADDRESSING_INTIMACY_HIGH,
    ADDRESSING_TONE_LADDER,
    ADDRESSING_TERM_LADDER,
    CONFLICT_ADDRESSING_OVERRIDE,
    RELATIONSHIP_EMOTION_BOOST_BY_STAGE,
    RELATIONSHIP_EMOTION_BOOST_MAX,
    STAGE_EXPRESSIVENESS,
    STAGE_INITIATIVE,
    STAGE_TONE,
    TERM_BY_STAGE,
)
from app.models.relationship import RelationshipState
from app.models.style_contract import Addressing


def _ladder_step(ladder: tuple[str, ...], base: str, offset: int) -> str:
    index = ladder.index(base) + offset
    return ladder[min(max(index, 0), len(ladder) - 1)]


def build_addressing(relationship_state: RelationshipState) -> Addressing:
    stage = relationship_state.stage
    term = TERM_BY_STAGE[stage]
    tone = STAGE_TONE[stage]
    initiative = STAGE_INITIATIVE[stage]
    expressiveness = STAGE_EXPRESSIVENESS[stage]

    if relationship_state.intimacy >= ADDRESSING_INTIMACY_HIGH:
        term = _ladder_step(ADDRESSING_TERM_LADDER, term, 1)
        expressiveness = _ladder_step(
            ADDRESSING_EXPRESSIVENESS_LADDER, expressiveness, 1
        )
    if relationship_state.comfort >= ADDRESSING_COMFORT_HIGH:
        tone = _ladder_step(ADDRESSING_TONE_LADDER, tone, 1)
    if relationship_state.familiarity >= ADDRESSING_FAMILIARITY_HIGH:
        initiative = _ladder_step(ADDRESSING_INITIATIVE_LADDER, initiative, 1)
    elif relationship_state.familiarity < ADDRESSING_FAMILIARITY_LOW:
        initiative = _ladder_step(ADDRESSING_INITIATIVE_LADDER, initiative, -1)
    if relationship_state.comfort < ADDRESSING_COMFORT_LOW:
        expressiveness = _ladder_step(
            ADDRESSING_EXPRESSIVENESS_LADDER, expressiveness, -1
        )

    conflict_status = relationship_state.conflict_status or "none"
    tone_down, initiative_down = CONFLICT_ADDRESSING_OVERRIDE.get(
        conflict_status, (0, 0)
    )
    if tone_down:
        tone = _ladder_step(ADDRESSING_TONE_LADDER, tone, -tone_down)
    if initiative_down:
        initiative = _ladder_step(
            ADDRESSING_INITIATIVE_LADDER, initiative, -initiative_down
        )

    return Addressing(
        term=term,
        tone=tone,
        initiative=initiative,
        emotion_expressiveness=expressiveness,
    )


def relationship_emotion_boost(stage: str) -> float:
    boost = RELATIONSHIP_EMOTION_BOOST_BY_STAGE.get(stage, 0.0)
    return min(max(boost, 0.0), RELATIONSHIP_EMOTION_BOOST_MAX)
