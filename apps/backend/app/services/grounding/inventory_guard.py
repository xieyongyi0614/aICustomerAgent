"""库存 grounding 守卫（ACTION-006）。

系统侧事实对账：扫描角色回复中的库存陈述，与 WorldContext.inventory（唯一账本）对齐。
冲突时确定性改写；不写库、不调 LLM、不修改 World。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.character.asuna.narrative import NARRATIVE_OBJECT_NOUNS
from app.character.asuna.world import OBJECT_CREATION_HINTS
from app.models.world import InventoryItem

_CHINESE_QTY = {
    "一": 1.0,
    "二": 2.0,
    "两": 2.0,
    "俩": 2.0,
    "三": 3.0,
    "四": 4.0,
    "五": 5.0,
    "六": 6.0,
    "七": 7.0,
    "八": 8.0,
    "九": 9.0,
    "十": 10.0,
    "半": 0.5,
}

_MEASURE = "个盒颗瓶碗份斤根片块杯桶袋罐"

_EXTRA_CLAIM_NOUNS = frozenset(
    {
        "苹果",
        "梨",
        "橘子",
        "橙子",
        "香蕉",
        "葡萄",
        "草莓",
        "番茄",
        "西红柿",
        "黄瓜",
        "土豆",
        "胡萝卜",
        "白菜",
        "卷心菜",
        "排骨",
        "鸡肉",
        "牛肉",
        "猪肉",
        "虾",
        "鱼",
        "汤",
        "粥",
        "饭",
        "剩饭",
        "便当",
        "果汁",
        "咖啡",
        "茶",
        "酸奶",
        "零食",
    }
)

_REMAIN_LEAD_RE = re.compile(
    r"(?:冰箱里|橱柜里|家里|厨房|锅里|碗里|盘子里|桌上)?"
    r"(?:还(?:有|剩下|剩|温着|放着|留着)|剩下|剩|温着|放着|留着)"
    r"([^。！？\n]{1,48})"
)

_SUBJECT_QTY_RE = re.compile(
    r"([一-鿿A-Za-z0-9]{1,10})"
    r"(?:已经)?"
    r"(?:还(?:有|剩|剩下)|剩|共有|一共)"
    r"([一二两三四五六七八九十半\d]+(?:\.\d+)?)"
    rf"([{_MEASURE}])?"
    r"(?=[，。！？\n]|$)"
)

_EXISTENCE_RE = re.compile(
    r"(?:锅里|碗里|盘子里|桌上|冰箱里|橱柜里|锅中|家里)?"
    r"(?:还)?(?:有|温着|放着|留着|剩下)"
    r"([一-鿿、和，]{1,20})"
    r"(?=[。！？\n，]|$|想|要|等|要是|如果)"
)

_DEPLETED_RE = re.compile(
    r"([一-鿿A-Za-z0-9]{1,10})"
    r"(?:已经)?"
    r"(?:没了|没有了|都(?:没|没有)了|用完了|吃完了|喝完了|光了|没有货了)"
)

_ITEM_QTY_RE = re.compile(
    r"^([一二两三四五六七八九十半\d]+(?:\.\d+)?)"
    rf"([{_MEASURE}])?"
    r"(.+)$"
)

_BARE_QTY_RE = re.compile(
    r"([一二两三四五六七八九十半\d]+(?:\.\d+)?)"
    rf"([{_MEASURE}])"
    r"([一-鿿]{1,8})"
)

_TAKE_VERBS = ("拿出", "取出", "拿走", "拿了")

_TAKE_QTY_FIRST_RE = re.compile(
    r"(拿出|取出|拿走|拿了)\s*([一二两俩三四五六七八九十半]+|\d+(?:\.\d+)?)"
    r"[个份只颗瓶盒碗块片]?\s*([一-鿿]{1,6})"
)

_TAKE_QTY_LAST_RE = re.compile(
    r"(拿出|取出|拿走|拿了)\s*([一-鿿]{1,6})\s*"
    r"([一二两俩三四五六七八九十半]+|\d+(?:\.\d+)?)[个份只颗瓶盒碗块片]?"
)

_TAKEAWAY_QTY_RE = re.compile(
    r"(拿出|取出|拿走|拿了|用了|用掉|消耗了|舀了|吃掉|喝了)"
    r"\s*([一二两俩三四五六七八九十半]+|\d+(?:\.\d+)?)"
    r"(个|份|盒|瓶|碗|块|袋|只|颗)?"
)

_LEFTOVER_QTY_RE = re.compile(
    r"(冰箱里|家里|橱柜里|桌上|厨房里|锅中|碗里|盘子里)?"
    r"(?:应该|大概|估计|可能)?(?:还(?:剩下?|剩)|剩下?|剩)"
    r"([一二两俩三四五六七八九十半]+|\d+(?:\.\d+)?)"
    r"(个|份|盒|瓶|碗|块|袋|只|颗)(?=[。！？\n，]|$)"
)
_ITEM_SPLIT_RE = re.compile(r"[、，]|以及|和|跟|与")


@dataclass
class InventoryClaim:
    kind: str
    name: str
    quantity: float | None
    unit: str | None
    span: tuple[int, int]
    text: str


@dataclass
class GroundingConflict:
    kind: str
    name: str
    claimed_quantity: float | None
    actual_quantity: float | None
    detail: str
    span: tuple[int, int]
    text: str


@dataclass
class GroundingReport:
    claims: list[InventoryClaim] = field(default_factory=list)
    conflicts: list[GroundingConflict] = field(default_factory=list)
    action: str = "pass"
    corrected_text: str | None = None

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def _parse_qty(token: str) -> float | None:
    if not token:
        return None
    if token in _CHINESE_QTY:
        return _CHINESE_QTY[token]
    try:
        return float(token)
    except ValueError:
        return None


def _inventory_map(inventory: list[InventoryItem]) -> dict[str, InventoryItem]:
    return {item.name: item for item in inventory if item.quantity > 0}


def _claimable_nouns(inventory: list[InventoryItem]) -> set[str]:
    names = {item.name for item in inventory}
    return (
        names
        | set(NARRATIVE_OBJECT_NOUNS)
        | set(OBJECT_CREATION_HINTS)
        | set(_EXTRA_CLAIM_NOUNS)
    )


def _match_inventory_name(name: str, inv: dict[str, InventoryItem]) -> str | None:
    if not name:
        return None
    if name in inv:
        return name
    for known in sorted(inv, key=len, reverse=True):
        if name in known or known in name:
            return known
    return None


def _match_strict_name(name: str, inv: dict[str, InventoryItem], claimable: set[str]) -> str | None:
    name = name.strip().strip("的了")
    if not name:
        return None
    if name in inv:
        return name
    if name in claimable:
        return _match_inventory_name(name, inv)
    for known in sorted(inv, key=len, reverse=True):
        if name == known:
            return known
    return None


def _parse_item_fragment(fragment: str) -> tuple[str, float | None, str | None]:
    text = fragment.strip().strip("的了着")
    if not text:
        return "", None, None
    match = _ITEM_QTY_RE.match(text)
    if not match:
        return text, None, None
    qty = _parse_qty(match.group(1))
    unit = match.group(2)
    name = match.group(3).strip().strip("的了着")
    return name, qty, unit


def _format_item(item: InventoryItem) -> str:
    qty = item.quantity
    qty_text = str(int(qty)) if qty == int(qty) else f"{qty:g}"
    unit = item.unit if item.unit and item.unit not in ("piece", "个") else ""
    if unit:
        return f"{item.name}{qty_text}{unit}"
    return f"{item.name}{qty_text}个"


def _format_qty_suffix(item: InventoryItem) -> str:
    qty = item.quantity
    qty_text = str(int(qty)) if qty == int(qty) else f"{qty:g}"
    unit = item.unit if item.unit and item.unit not in ("piece", "个") else "个"
    return f"{qty_text}{unit}"


def _fmt_requested_num(value: float) -> str:
    """返回请求数量的确定性文本（仅供改写替换，统一阿拉伯数字）。"""
    return str(int(value)) if value == int(value) else f"{value:g}"


def extract_requested_counts(
    message: str, inventory: list[InventoryItem]
) -> dict[str, float]:
    """从用户消息抽取『数量 + 物品』的请求要求：{库存名: 数量}。"""
    if not message:
        return {}
    inv = _inventory_map(inventory)
    requested: dict[str, float] = {}
    for name in sorted(inv, key=len, reverse=True):
        pattern = re.compile(
            r"([一二两俩三四五六七八九十半]+|\d+(?:\.\d+)?)\s*"
            r"[个份只颗瓶盒碗块片]?\s*" + re.escape(name)
        )
        match = pattern.search(message)
        if not match:
            continue
        qty = _parse_qty(match.group(1))
        if qty is not None:
            requested[name] = qty
    return requested


def _take_overreach_matches(
    reply: str,
    inv: dict[str, InventoryItem],
    claimable: set[str],
    requested: dict[str, float],
) -> list[dict]:
    """回复中『取出 N 个 X』超过用户要求 M 的越界命中。"""
    if not requested:
        return []
    out: list[dict] = []
    for regex in (_TAKE_QTY_FIRST_RE, _TAKE_QTY_LAST_RE):
        for match in regex.finditer(reply):
            if match.group(2) and _parse_qty(match.group(2)) is not None:
                num_text, name_text, qty_group = match.group(2), match.group(3), 2
            elif match.group(3) and _parse_qty(match.group(3)) is not None:
                num_text, name_text, qty_group = match.group(3), match.group(2), 3
            else:
                continue
            matched = _match_strict_name(name_text, inv, claimable)
            if matched is None or matched not in requested:
                continue
            qty = _parse_qty(num_text)
            limit = requested[matched]
            if qty is None or not (qty > limit + 1e-6):
                continue
            out.append(
                {
                    "name": matched,
                    "qty": qty,
                    "span": (match.start(qty_group), match.end(qty_group)),
                    "text": match.group(0),
                    "requested": limit,
                }
            )
    return out


def _infer_unique_name(
    text: str, inv: dict[str, InventoryItem]
) -> str | None:
    """从文本里唯一推定的库存名（字面子串或单字命中）；候选多于一个则不猜。"""
    if not text or not inv:
        return None
    hits: set[str] = set()
    text_chars = set(text)
    for name in inv:
        if name in text:
            hits.add(name)
            continue
        if set(name) & text_chars:
            hits.add(name)
    return hits.pop() if len(hits) == 1 else None


def _leftover_plan(
    reply: str,
    inv: dict[str, InventoryItem],
    context_text: str | None,
) -> list[dict]:
    """免主语存量句的对账计划：用上文唯一推定主语，
    按『库存 - 回复声称取走量』计算应剩值，不符即给出改写命中。"""
    if not context_text:
        return []
    name = _infer_unique_name(context_text, inv)
    if name is None:
        return []
    stock = inv[name].quantity
    takeaway = 0.0
    takeaway_match = _TAKEAWAY_QTY_RE.search(reply)
    if takeaway_match:
        qty = _parse_qty(takeaway_match.group(2))
        if qty is not None:
            takeaway = qty
    planned = max(0.0, round(stock - takeaway, 2))
    hits: list[dict] = []
    for match in _LEFTOVER_QTY_RE.finditer(reply):
        qty = _parse_qty(match.group(2))
        if qty is None:
            continue
        if abs(qty - planned) <= 1e-6:
            continue
        hits.append(
            {
                "name": name,
                "qty": qty,
                "planned": planned,
                "span": (match.start(2), match.end(2)),
                "text": match.group(0),
            }
        )
    return hits


def _split_items(fragment: str) -> list[str]:
    parts = _ITEM_SPLIT_RE.split(fragment)
    return [p.strip() for p in parts if p and p.strip()]


def _is_noise_fragment(name: str) -> bool:
    if not name or len(name) > 12:
        return True
    noise = {
        "刚才",
        "现在",
        "我们",
        "你们",
        "这个",
        "那个",
        "什么",
        "东西",
        "时候",
        "一下",
        "一点",
        "一些",
        "大家",
        "自己",
        "这里",
        "那里",
        "家里现成",
        "现成的",
    }
    return name in noise or name.endswith("的话")


def extract_inventory_claims(
    reply: str, inventory: list[InventoryItem]
) -> list[InventoryClaim]:
    inv = _inventory_map(inventory)
    claimable = _claimable_nouns(inventory)
    claims: list[InventoryClaim] = []

    for match in _REMAIN_LEAD_RE.finditer(reply):
        fragment = match.group(1).strip()
        span = (match.start(), match.end())
        for raw in _split_items(fragment):
            name, qty, unit = _parse_item_fragment(raw)
            if not name or _is_noise_fragment(name):
                continue
            matched = _match_inventory_name(name, inv)
            if matched is None and name not in claimable:
                continue
            claims.append(
                InventoryClaim(
                    kind="remaining",
                    name=matched or name,
                    quantity=qty,
                    unit=unit,
                    span=span,
                    text=raw,
                )
            )

    for match in _SUBJECT_QTY_RE.finditer(reply):
        raw_name = match.group(1)
        matched = _match_inventory_name(raw_name, inv)
        if matched is None and raw_name not in claimable:
            continue
        qty = _parse_qty(match.group(2))
        if qty is None:
            continue
        claims.append(
            InventoryClaim(
                kind="subject_qty",
                name=matched or raw_name,
                quantity=qty,
                unit=match.group(3),
                span=(match.start(), match.end()),
                text=match.group(0),
            )
        )

    for match in _EXISTENCE_RE.finditer(reply):
        fragment = match.group(1).strip()
        span = (match.start(), match.end())
        for raw in _split_items(fragment):
            name, qty, unit = _parse_item_fragment(raw)
            if not name or _is_noise_fragment(name):
                continue
            matched = _match_inventory_name(name, inv)
            if matched is None and name not in claimable:
                continue
            claims.append(
                InventoryClaim(
                    kind="existence",
                    name=matched or name,
                    quantity=qty,
                    unit=unit,
                    span=span,
                    text=raw,
                )
            )

    for match in _DEPLETED_RE.finditer(reply):
        raw_name = match.group(1)
        matched = _match_inventory_name(raw_name, inv)
        if matched is None and raw_name not in claimable:
            continue
        name = matched or raw_name
        claims.append(
            InventoryClaim(
                kind="depleted",
                name=name,
                quantity=0.0,
                unit=None,
                span=(match.start(), match.end()),
                text=match.group(0),
            )
        )

    for match in _BARE_QTY_RE.finditer(reply):
        qty = _parse_qty(match.group(1))
        name = match.group(3).strip()
        if not name or name[0] in "和跟与及、的了着":
            continue
        matched = _match_strict_name(name, inv, claimable)
        if matched is None:
            continue
        claims.append(
            InventoryClaim(
                kind="bare_qty",
                name=matched,
                quantity=qty,
                unit=match.group(2),
                span=(match.start(), match.end()),
                text=match.group(0),
            )
        )

    return claims


def _conflict_for_claim(
    claim: InventoryClaim, inv: dict[str, InventoryItem]
) -> GroundingConflict | None:
    matched = _match_inventory_name(claim.name, inv)

    if matched is None:
        if claim.kind in ("remaining", "existence", "bare_qty", "subject_qty"):
            return GroundingConflict(
                kind="NOT_IN_INVENTORY",
                name=claim.name,
                claimed_quantity=claim.quantity,
                actual_quantity=None,
                detail="回复声称库存中不存在的物品",
                span=claim.span,
                text=claim.text,
            )
        return None

    actual = inv[matched]
    if claim.kind == "depleted":
        if actual.quantity > 0:
            return GroundingConflict(
                kind="DEPLETED_BUT_HAS",
                name=matched,
                claimed_quantity=0.0,
                actual_quantity=actual.quantity,
                detail="回复声称已耗尽，但账本仍有库存",
                span=claim.span,
                text=claim.text,
            )
        return None

    if claim.quantity is None:
        return None
    if abs(claim.quantity - actual.quantity) > 1e-6:
        return GroundingConflict(
            kind="QTY_MISMATCH",
            name=matched,
            claimed_quantity=claim.quantity,
            actual_quantity=actual.quantity,
            detail="数量与世界账本不一致",
            span=claim.span,
            text=claim.text,
        )
    return None


def check_inventory_grounding(
    reply: str,
    inventory: list[InventoryItem],
    requested: dict[str, float] | None = None,
    context_text: str | None = None,
) -> GroundingReport:
    if not reply:
        return GroundingReport(action="pass")
    inv = _inventory_map(inventory)
    if not inv:
        return GroundingReport(action="pass")

    claims = extract_inventory_claims(reply, inventory)
    conflicts: list[GroundingConflict] = []
    for claim in claims:
        conflict = _conflict_for_claim(claim, inv)
        if conflict is not None:
            conflicts.append(conflict)

    if requested:
        claimable = _claimable_nouns(inventory)
        for hit in _take_overreach_matches(reply, inv, claimable, requested):
            conflicts.append(
                GroundingConflict(
                    kind="TAKE_EXCEEDS_REQUEST",
                    name=hit["name"],
                    claimed_quantity=hit["qty"],
                    actual_quantity=None,
                    detail="回复声称取出数量超过用户要求",
                    span=hit["span"],
                    text=hit["text"],
                )
            )

    if context_text:
        for hit in _leftover_plan(reply, inv, context_text):
            conflicts.append(
                GroundingConflict(
                    kind="LEFTOVER_MISMATCH",
                    name=hit["name"],
                    claimed_quantity=hit["qty"],
                    actual_quantity=hit["planned"],
                    detail="免主语存量陈述与账本应剩值不符",
                    span=hit["span"],
                    text=hit["text"],
                )
            )

    if not conflicts:
        return GroundingReport(claims=claims, conflicts=[], action="pass")

    corrected = rewrite_grounded(
        reply, inventory, requested=requested or {}, context_text=context_text
    )
    return GroundingReport(
        claims=claims,
        conflicts=conflicts,
        action="rewritten" if corrected and corrected != reply else "conflict_only",
        corrected_text=corrected if corrected and corrected != reply else None,
    )


def rewrite_grounded(
    reply: str,
    inventory: list[InventoryItem],
    requested: dict[str, float] | None = None,
    context_text: str | None = None,
) -> str | None:
    """把库存陈述改写成与账本一致的事实表述。覆盖跨度长的改写优先。"""
    if not reply or not inventory:
        return None
    inv = _inventory_map(inventory)
    if not inv:
        return None
    claimable = _claimable_nouns(inventory)
    replacements: list[tuple[int, int, str]] = []

    def _add(start: int, end: int, text: str) -> None:
        if start < end:
            replacements.append((start, end, text))

    if requested:
        for hit in _take_overreach_matches(reply, inv, claimable, requested):
            _add(hit["span"][0], hit["span"][1], _fmt_requested_num(hit["requested"]))

    if context_text:
        for hit in _leftover_plan(reply, inv, context_text):
            _add(hit["span"][0], hit["span"][1], _fmt_requested_num(hit["planned"]))

    for match in _SUBJECT_QTY_RE.finditer(reply):
        raw_name = match.group(1)
        matched = _match_inventory_name(raw_name, inv)
        if matched is None:
            continue
        actual = inv[matched]
        claimed = _parse_qty(match.group(2))
        if claimed is not None and abs(claimed - actual.quantity) <= 1e-6:
            continue
        _add(match.start(), match.end(), f"{matched}还有{_format_qty_suffix(actual)}")

    for match in _REMAIN_LEAD_RE.finditer(reply):
        fragment = match.group(1).strip()
        if re.fullmatch(r"[一二两三四五六七八九十半\d]+[个盒颗瓶碗份斤]?", fragment):
            continue
        kept: list[str] = []
        dropped = False
        mismatched = False
        for raw in _split_items(fragment):
            name, qty, unit = _parse_item_fragment(raw)
            if not name or _is_noise_fragment(name):
                continue
            matched = _match_inventory_name(name, inv)
            if matched is None:
                dropped = True
                continue
            kept.append(_format_item(inv[matched]))
            if qty is not None and abs(qty - inv[matched].quantity) > 1e-6:
                mismatched = True
        if dropped or mismatched:
            missing = []
            for raw in _split_items(fragment):
                name, qty, unit = _parse_item_fragment(raw)
                if not name or _is_noise_fragment(name):
                    continue
                if _match_inventory_name(name, inv) is None:
                    missing.append(name)
            if kept:
                _add(match.start(), match.end(), "还剩" + "、".join(kept))
            elif missing:
                _add(
                    match.start(),
                    match.end(),
                    f"库存里没有{'、'.join(missing[:3])}",
                )
            else:
                _add(match.start(), match.end(), "库存里没有现成的存货了")

    for match in _EXISTENCE_RE.finditer(reply):
        fragment = match.group(1).strip()
        if re.fullmatch(r"[一二两三四五六七八九十半\d]+[个盒颗瓶碗份斤]?", fragment):
            continue
        kept_names = []
        dropped = False
        for raw in _split_items(fragment):
            name, qty, unit = _parse_item_fragment(raw)
            if not name or _is_noise_fragment(name):
                continue
            matched = _match_inventory_name(name, inv)
            if matched is None:
                dropped = True
                continue
            kept_names.append(f"{matched}{_format_qty_suffix(inv[matched])}")
        if dropped:
            missing = []
            for raw in _split_items(fragment):
                name, qty, unit = _parse_item_fragment(raw)
                if not name or _is_noise_fragment(name):
                    continue
                if _match_inventory_name(name, inv) is None:
                    missing.append(name)
            if kept_names:
                _add(match.start(), match.end(), "有" + "、".join(kept_names))
            elif missing:
                _add(match.start(), match.end(), f"没有{missing[0]}")
            else:
                _add(match.start(), match.end(), "没有清单外的东西")

    for match in _DEPLETED_RE.finditer(reply):
        raw_name = match.group(1)
        matched = _match_inventory_name(raw_name, inv)
        if matched is None:
            continue
        actual = inv[matched]
        if actual.quantity > 0:
            _add(
                match.start(),
                match.end(),
                f"{matched}还有{_format_qty_suffix(actual)}",
            )

    for match in _BARE_QTY_RE.finditer(reply):
        name = match.group(3).strip()
        if not name or name[0] in "和跟与及、的了着":
            continue
        matched = _match_strict_name(name, inv, claimable)
        if matched is None:
            continue
        actual = inv[matched]
        qty = _parse_qty(match.group(1))
        if qty is None or abs(qty - actual.quantity) <= 1e-6:
            continue
        _add(match.start(), match.end(), _format_item(actual))

    if not replacements:
        return None

    replacements.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    selected: list[tuple[int, int, str]] = []
    for start, end, new in replacements:
        if any(not (end <= s or start >= e) for s, e, _ in selected):
            continue
        selected.append((start, end, new))
    selected.sort(key=lambda item: item[0])
    parts: list[str] = []
    cursor = 0
    for start, end, new in selected:
        parts.append(reply[cursor:start])
        parts.append(new)
        cursor = end
    parts.append(reply[cursor:])
    text = "".join(parts)
    return text if text != reply else None
