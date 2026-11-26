"""账目明细 Prompt 护栏。

调用方（各自任务接线）：
- PLA-007 抽取后的写链
- PLA-011 / PLA-013 推送前的模板渲染

允许聚合语境（合计 / 总计 / 分布 / 共 N 笔）；禁止单笔明细金额形态。
"""

from __future__ import annotations

import re

_AMOUNT_PATTERN = re.compile(
    r"(?:￥|¥|\$|人民币)\s*\d+(?:\.\d{1,2})?"
    r"|\d+(?:\.\d{1,2})?\s*(?:元|块钱|块|角|分|万元|千元)"
)
_AGGREGATE_CONTEXT = re.compile(r"合计|总计|分布|共计|共\s*\d+\s*笔|小计|均|平均")


class FinancialDetailInPrompt(ValueError):
    pass


def assert_no_financial_detail(text: str) -> str:
    if not text:
        return text
    if _AGGREGATE_CONTEXT.search(text):
        return text
    if _AMOUNT_PATTERN.search(text):
        raise FinancialDetailInPrompt("账目明细金额不得进入 Prompt")
    return text
