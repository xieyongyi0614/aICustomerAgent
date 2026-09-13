"""CHAR-001：StyleContract 数据模型单测（纯值对象，无 IO / 无 LLM）。"""

import pytest
from pydantic import ValidationError

from app.models.style_contract import (
    ADDRESSING_EXPRESSIVENESS_LABELS,
    ADDRESSING_INITIATIVE_LABELS,
    ADDRESSING_TERM_LABELS,
    ADDRESSING_TONE_LABELS,
    Addressing,
    EmotionExpression,
    PersonalityModulation,
    StyleContract,
    TriggeredHabit,
)


def test_default_contract_constructs_with_defaults():
    contract = StyleContract()
    assert contract.addressing == Addressing()
    assert contract.emotion_constraint == EmotionExpression()
    assert contract.personality_modulation == PersonalityModulation()
    assert contract.habits == []
    assert contract.forbidden == []
    assert contract.principles == []
    assert contract.style_hint == ""
    assert contract.addressing.term == "name"
    assert contract.addressing.tone == "natural"
    assert contract.addressing.initiative == "responsive"
    assert contract.addressing.emotion_expressiveness == "natural"
    assert contract.emotion_constraint.channel_bias == "balanced"
    assert contract.emotion_constraint.expression_intensity == "natural"
    modulation = contract.personality_modulation
    assert modulation.assertiveness == 0.3
    assert modulation.warmth == 0.8
    assert modulation.curiosity == 0.6
    assert modulation.patience == 0.7


def test_default_habit_fields():
    habit = TriggeredHabit()
    assert habit.rule_id == ""
    assert habit.priority == 3
    assert habit.instruction == ""


@pytest.mark.parametrize(
    "field, valid, invalid",
    [
        ("term", "affectionate", "buddy"),
        ("tone", "warm", "angry"),
        ("initiative", "proactive", "aggressive"),
        ("emotion_expressiveness", "open", "wild"),
    ],
)
def test_addressing_literal_rejects_unknown_values(field, valid, invalid):
    assert getattr(Addressing(**{field: valid}), field) == valid
    with pytest.raises(ValidationError):
        Addressing(**{field: invalid})


@pytest.mark.parametrize(
    "field, valid, invalid",
    [
        ("channel_bias", "verbal", "gesture"),
        ("expression_intensity", "rich", "extreme"),
    ],
)
def test_emotion_expression_literal_rejects_unknown_values(field, valid, invalid):
    assert getattr(EmotionExpression(**{field: valid}), field) == valid
    with pytest.raises(ValidationError):
        EmotionExpression(**{field: invalid})


@pytest.mark.parametrize("field", ["assertiveness", "warmth", "curiosity", "patience"])
def test_personality_axis_range_rejected(field):
    with pytest.raises(ValidationError):
        PersonalityModulation(**{field: -0.1})
    with pytest.raises(ValidationError):
        PersonalityModulation(**{field: 1.1})


def test_personality_axis_boundary_values_accepted():
    modulation = PersonalityModulation(
        assertiveness=0.0, warmth=1.0, curiosity=0.0, patience=1.0
    )
    assert modulation.assertiveness == 0.0
    assert modulation.warmth == 1.0


def test_personality_metadata_rejects_unknown_axis_and_out_of_range():
    with pytest.raises(ValidationError):
        PersonalityModulation(baseline={"humor": 0.5})
    with pytest.raises(ValidationError):
        PersonalityModulation(baseline={"warmth": 1.5})
    with pytest.raises(ValidationError):
        PersonalityModulation(bound={"warmth": -0.2})


def test_habit_priority_range_rejected():
    with pytest.raises(ValidationError):
        TriggeredHabit(priority=0)
    with pytest.raises(ValidationError):
        TriggeredHabit(priority=6)


def test_field_length_limits_rejected():
    with pytest.raises(ValidationError):
        EmotionExpression(tone_directive="x" * 31)
    with pytest.raises(ValidationError):
        TriggeredHabit(instruction="x" * 41)


def test_addressing_length_limits_accepted():
    assert EmotionExpression(tone_directive="x" * 30).tone_directive == "x" * 30
    assert TriggeredHabit(instruction="x" * 40).instruction == "x" * 40


def test_prompt_lines_empty_contract_returns_empty_list():
    assert StyleContract().prompt_lines() == []


def test_prompt_lines_addressing_only_non_default_fields():
    contract = StyleContract(addressing=Addressing(term="affectionate", tone="warm"))
    assert contract.prompt_lines() == [
        f"称呼：{ADDRESSING_TERM_LABELS['affectionate']}",
        f"语气：{ADDRESSING_TONE_LABELS['warm']}",
    ]


def test_prompt_lines_emotion_constraint():
    contract = StyleContract(
        emotion_constraint=EmotionExpression(
            channel_bias="verbal",
            tone_directive="先确认情况，语气放柔",
            expression_intensity="rich",
        )
    )
    assert contract.prompt_lines() == [
        "表达通道：偏语言表达",
        "语气：先确认情况，语气放柔",
        "情绪强度：浓烈地流露",
    ]


def test_prompt_lines_personality_only_non_neutral_axes():
    contract = StyleContract(
        personality_modulation=PersonalityModulation(
            assertiveness=0.1, warmth=0.9, curiosity=0.5, patience=0.5
        )
    )
    assert contract.prompt_lines() == [
        "人格基调：不抢话，少替对方拿主意、关心外显"
    ]


def test_prompt_lines_habits_forbidden_principles():
    contract = StyleContract(
        habits=[
            TriggeredHabit(
                rule_id="habit_comfort_companion_first",
                priority=1,
                instruction="安慰人先陪着，不第一时间给建议",
            )
        ],
        forbidden=["不无条件赞同"],
        principles=["有自己的判断"],
    )
    assert contract.prompt_lines() == [
        "习惯：安慰人先陪着，不第一时间给建议",
        "禁止：不无条件赞同",
        "原则：有自己的判断",
    ]


def test_prompt_lines_full_contract_stable_and_brace_free():
    contract = StyleContract(
        addressing=Addressing(
            term="intimate",
            tone="affectionate",
            initiative="devoted",
            emotion_expressiveness="open",
        ),
        emotion_constraint=EmotionExpression(
            channel_bias="action", tone_directive="语气放柔", expression_intensity="subtle"
        ),
        personality_modulation=PersonalityModulation(curiosity=0.9),
        habits=[
            TriggeredHabit(rule_id="h1", priority=2, instruction="一次最多问一个问题")
        ],
        forbidden=["不表演"],
        principles=["守护亲近的人"],
    )
    lines = contract.prompt_lines()
    assert lines == [
        f"称呼：{ADDRESSING_TERM_LABELS['intimate']}",
        f"语气：{ADDRESSING_TONE_LABELS['affectionate']}",
        f"主动程度：{ADDRESSING_INITIATIVE_LABELS['devoted']}",
        f"情绪表达：{ADDRESSING_EXPRESSIVENESS_LABELS['open']}",
        "表达通道：偏动作表达",
        "语气：语气放柔",
        "情绪强度：淡淡地流露",
        "人格基调：关心外显、好奇，会追问",
        "习惯：一次最多问一个问题",
        "禁止：不表演",
        "原则：守护亲近的人",
    ]
    assert all("{" not in line and "}" not in line for line in lines)
    assert contract.prompt_lines() == lines


def test_build_style_hint_default_is_stable():
    assert StyleContract().build_style_hint() == "自然"
    assert StyleContract().build_style_hint() == StyleContract().build_style_hint()


def test_build_style_hint_combines_signals():
    contract = StyleContract(
        addressing=Addressing(term="affectionate", tone="warm", initiative="proactive"),
        emotion_constraint=EmotionExpression(tone_directive="先确认情况，语气放柔"),
        habits=[
            TriggeredHabit(priority=1, instruction="安慰人先陪着"),
            TriggeredHabit(priority=2, instruction="一次最多问一个问题"),
        ],
    )
    hint = contract.build_style_hint()
    assert hint == "先确认情况，语气放柔、亲昵、昵称、主动关心、安慰人先陪着"


def test_build_style_hint_falls_back_to_intensity_label():
    contract = StyleContract(
        emotion_constraint=EmotionExpression(expression_intensity="rich")
    )
    assert contract.build_style_hint() == "浓烈地流露"


def test_contract_json_serializable():
    contract = StyleContract(
        habits=[TriggeredHabit(rule_id="h1", priority=1, instruction="先陪着")]
    )
    payload = contract.model_dump(mode="json")
    assert isinstance(payload, dict)
    assert payload["habits"][0]["rule_id"] == "h1"
    assert isinstance(payload["addressing"]["term"], str)
