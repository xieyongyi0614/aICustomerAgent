"""记忆同题判定（LCS 相似度）。

随 memory 域清理从 `services/memory_conflict.py` 归位（2026-09-29）：
v1 的 resolve_batch / resolve_candidate 冲突消解路径已删除——生产零调用，
冲突处理由 `memory/lifecycle.py::on_promoted` 承担。
随 services 归位批次 2 再迁 `engines/memory_conflict.py`（2026-09-30，纯函数收口）。
"""

from app.core.settings import get_settings


def _lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    for char_a in a:
        current = [0]
        for index, char_b in enumerate(b, start=1):
            if char_a == char_b:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1]


def same_topic(left: str, right: str, threshold: float | None = None) -> bool:
    left = (left or "").strip()
    right = (right or "").strip()
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    resolved_threshold = (
        threshold if threshold is not None else get_settings().memory_conflict_threshold
    )
    longer = max(len(left), len(right))
    return _lcs_length(left, right) / longer >= resolved_threshold
