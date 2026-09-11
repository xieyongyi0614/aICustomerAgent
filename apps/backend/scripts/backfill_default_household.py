"""现有用户默认家庭库存一次性回填工具（Household Inventory autoseed 修复）。

背景：ensure_world 此前只在 worlds 行首次创建时播种 DEFAULT_HOUSEHOLD，
对早已存在、但默认清单缺失的旧 world（如 household 功能落地前累积过会话的
用户）从未补种，导致每轮只拿到环境、却没有默认家庭库存。
本脚本对所有已存在的 world 幂等回填缺失的默认物品。

默认 dry-run 出报告（不写库）；--apply 执行回填。重跑零副作用（seed 按名去重，
已消耗/存在的物品不会被重置，只会补齐缺失的默认项）。

用法：
    uv run python -m scripts.backfill_default_household
    uv run python -m scripts.backfill_default_household --apply
"""

import argparse
import json

from app.application import world_engine
from app.repositories import world_repository


def main() -> None:
    parser = argparse.ArgumentParser(description="默认家庭库存回填（幂等）")
    parser.add_argument("--apply", action="store_true", help="执行回填（默认 dry-run）")
    args = parser.parse_args()

    worlds = world_repository.list_all_worlds()
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "total_worlds": len(worlds),
        "total_created": 0,
        "worlds": [],
    }
    for world in worlds:
        present = {
            obj.name for obj in world_repository.list_objects(world.world_id)
        }
        missing = [
            spec["name"]
            for spec in world_engine.DEFAULT_HOUSEHOLD["objects"]
            if spec["name"] not in present
        ]
        created = (
            world_engine.seed_default_household(world.user_id) if args.apply else None
        )
        report["total_created"] += created or 0
        report["worlds"].append(
            {"user_id": world.user_id, "created": created, "missing": missing}
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()