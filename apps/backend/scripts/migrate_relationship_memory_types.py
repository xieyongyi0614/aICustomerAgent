"""v1 遗留 relationship_event 记忆迁移工具（REL-001）。

默认 dry-run 出报告；--apply 执行分批迁移（幂等，重跑零行）。停写窗口执行。

用法：
    uv run python -m scripts.migrate_relationship_memory_types
    uv run python -m scripts.migrate_relationship_memory_types --apply
"""

import argparse
import json

from app.services.memory2 import migration


def main() -> None:
    parser = argparse.ArgumentParser(description="relationship_event 记忆类型迁移")
    parser.add_argument("--apply", action="store_true", help="执行迁移（默认 dry-run）")
    parser.add_argument("--batch-size", type=int, default=migration.BATCH_SIZE)
    args = parser.parse_args()
    if args.apply:
        report = migration.apply_migration(batch_size=args.batch_size)
    else:
        report = {"mode": "dry_run", **migration.collect_report()}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.apply:
        verification = report.get("verification", {})
        failed = [
            key
            for key in ("alias_mapping_ok", "retriever_alias_ok", "v1_affinity_ok")
            if not verification.get(key)
        ]
        if failed or verification.get("remaining_rows") != 0:
            raise SystemExit(f"迁移校验未通过：{failed or '存在残留行'}")


if __name__ == "__main__":
    main()
