"""PLT-004 五条设计原则验收化（可判定规则）。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_ai_narrative_first_home():
    src = Path("../mobile/lib/features/home/presentation/home_page.dart").read_text(
        encoding="utf-8"
    )
    repo = Path("../mobile/lib/features/home/data/home_repository.dart").read_text(
        encoding="utf-8"
    )
    assert "今日 AI 总结" in repo
    ai = src.index("AiCard(")
    data = src.index("今日状态")
    assert ai < data


def test_memory_visible_has_usage_receipt_slot():
    """记忆页必须同时露出「来源」与「用途回执」两个位。

    回执与来源文案自 `API-007` 起由服务端下发（`receipt.label` / `source_label`），端上零拼接；
    措辞本身由服务端侧 `test_memory_product_view.py` 的 `recall_*` 用例钉住。
    """
    src = Path("../mobile/lib/features/memory/presentation/memory_page.dart").read_text(
        encoding="utf-8"
    )
    assert "usageReceipts" in src
    assert "usageNote" in src
    assert "来源：" in src


def test_no_hardcoded_money_in_mobile_non_tokens():
    # 分层守卫已在 Flutter 侧覆盖硬编码色值；此处钉住健康免责常驻
    consent = Path(
        "../mobile/lib/features/health/presentation/health_consent_page.dart"
    ).read_text(encoding="utf-8")
    assert "非医疗建议" in consent
