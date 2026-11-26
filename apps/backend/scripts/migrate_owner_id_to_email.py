"""owner 行 id 规范化：`default-user` → 邮箱派生 id（默认用户概念退役收尾）。

背景：0058 已删除 `users.is_default`；本脚本把历史 owner 行的 id 改成与
`user_service.find_or_create_by_email` 一致的口径（`email-<sha256[:16]>`），使
「user_id 一律由邮箱 / 通道身份派生」成立，彻底消掉 `default-user` 字面量。

级联范围（全部动态发现，不写死表名）：
- `users.id`：主键改名；
- 所有含 `user_id` 列的业务表：逐表 `UPDATE`；
- `worlds.id`（= `home:<user_id>`）与所有含 `world_id` 列的表：同步改写。

幂等：源 id 与目标 id 相同、或目标 id 行已存在时零变更直接返回。
默认 dry-run 出报告；`--apply` 单事务执行，失败整体回滚。

⚠️ 令牌是无状态 HMAC 签名、载荷里带 user_id：改名后**所有已签发 token 失效**，
客户端需重新登录一次。

用法：
    uv run python -m scripts.migrate_owner_id_to_email --from-id default-user
    uv run python -m scripts.migrate_owner_id_to_email --from-id default-user --apply
"""

import argparse
import json
from typing import Any

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, UserRow


def _legacy_world_id(user_id: str) -> str:
    """存量世界行主键格式（ADR-16 C2 后新世界为雪花，本脚本只改写存量行）。"""
    return f"home:{user_id}"
from app.services.identity.user_service import legacy_email_user_id


def tables_with_column(engine, column: str, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """动态发现含指定列的表（走 SQLAlchemy inspector，PG / SQLite 通用）。"""
    inspector = inspect(engine)
    return sorted(
        name
        for name in inspector.get_table_names()
        if name not in exclude
        and column in {col["name"] for col in inspector.get_columns(name)}
    )


def count_rows(engine, table: str, column: str, value: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE {column} = :v'), {"v": value}
        ).scalar_one()


def _rewrite(conn, table: str, column: str, old: str, new: str) -> int:
    result = conn.execute(
        text(f'UPDATE "{table}" SET {column} = :new WHERE {column} = :old'),
        {"new": new, "old": old},
    )
    return result.rowcount or 0


def migrate_owner_id(
    source_id: str,
    *,
    apply: bool = False,
    engine,
    session_factory=SessionLocal,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "from_id": source_id,
        "status": "planned",
    }
    with session_factory() as session:
        source = session.get(UserRow, source_id)
        if source is None:
            report["status"] = "noop_source_absent"
            report["reason"] = "源行不存在（重复执行、或 --from-id 写错）"
            return report
        if not source.email:
            raise RuntimeError(
                f"用户 {source_id} 无绑定邮箱，无法派生目标 id——请先绑定邮箱"
            )
        email = source.email.strip().lower()
        target_id = legacy_email_user_id(email)
        target_exists = session.get(UserRow, target_id) is not None

    report["to_id"] = target_id
    report["email"] = email
    report["old_world_id"] = _legacy_world_id(source_id)
    report["new_world_id"] = _legacy_world_id(target_id)
    if target_id == source_id:
        report["status"] = "noop_already_canonical"
        return report
    if target_exists:
        report["status"] = "refused_target_exists"
        report["reason"] = f"目标 id 已存在另一行：{target_id}，需人工处理"
        return report

    user_tables = tables_with_column(engine, "user_id", exclude=("users",))
    world_tables = tables_with_column(engine, "world_id")
    report["user_id_tables"] = {
        table: count_rows(engine, table, "user_id", source_id)
        for table in user_tables
    }
    report["world_id_tables"] = {
        table: count_rows(engine, table, "world_id", report["old_world_id"])
        for table in world_tables
    }
    report["worlds"] = count_rows(engine, "worlds", "id", report["old_world_id"])
    if not apply:
        return report

    with engine.begin() as conn:
        renamed = _rewrite(conn, "users", "id", source_id, target_id)
        if renamed != 1:
            raise RuntimeError(f"users.id 改名影响 {renamed} 行，非 1，已回滚")
        for table in user_tables:
            _rewrite(conn, table, "user_id", source_id, target_id)
        _rewrite(conn, "worlds", "id", report["old_world_id"], report["new_world_id"])
        for table in world_tables:
            _rewrite(conn, table, "world_id", report["old_world_id"], report["new_world_id"])

    report["status"] = "applied"
    report["warning"] = "所有已签发令牌失效，客户端需重新登录"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="owner 行 id 规范化（幂等）")
    parser.add_argument("--from-id", required=True, help="源 user_id（历史默认用户）")
    parser.add_argument("--apply", action="store_true", help="执行改名（默认 dry-run）")
    args = parser.parse_args()

    from app.core.db import engine

    report = migrate_owner_id(args.from_id, apply=args.apply, engine=engine)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
