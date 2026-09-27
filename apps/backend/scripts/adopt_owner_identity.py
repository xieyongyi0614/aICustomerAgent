"""Owner 身份归并工具（v5.0.0 §14 IDENT-005 / 基线 ADR 13）。

背景：邮箱验证码登录 find-or-create 出 `email-*` 用户，而历史对话 / 记忆 /
世界 / 账本等全量数据都在 `default-user` 名下，登录身份与数据主体脱节。
本工具把 owner 邮箱绑定到 default-user 行，并把 email-* 用户名下的散数据
并入 default-user，使「登录邮箱 → token user_id = default-user → 数据主体」
三者一致。归并后 default-user 即 owner 的稳定内部 id，后续零数据搬迁。

规则：
- 含 `user_id` 列的业务表逐表 `UPDATE user_id` 归并；与 default-user 已有行
  冲突的表（单例域）整表跳过并如实报告，不丢数据。
- 全部表归并成功时删除 email-* 用户行；存在跳过表时保留该行（email 置空）
  待人工处理。
- 幂等：重复执行零变更。

默认 dry-run 出报告（不写库）；--apply 执行。

用法：
    uv run python -m scripts.adopt_owner_identity --email owner@example.com
    uv run python -m scripts.adopt_owner_identity --email owner@example.com --apply
"""

import argparse
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, UserRow
from app.core.settings import get_settings
from app.services.identity.user_service import ensure_default_user


def tables_with_user_id(engine) -> list[str]:
    stmt = text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE column_name = 'user_id' AND table_schema = current_schema() "
        "AND table_name <> 'users' ORDER BY table_name"
    )
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(stmt)]


def count_user_rows(tables: list[str], engine, user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        with engine.connect() as conn:
            counts[table] = conn.execute(
                text(f'SELECT COUNT(*) FROM "{table}" WHERE user_id = :uid'),
                {"uid": user_id},
            ).scalar_one()
    return counts


def merge_user_data(
    source_user_id: str, target_user_id: str, tables: list[str], engine
) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for table in tables:
        try:
            with engine.begin() as conn:
                count = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table}" WHERE user_id = :src'),
                    {"src": source_user_id},
                ).scalar_one()
                merged = 0
                if count:
                    conn.execute(
                        text(
                            f'UPDATE "{table}" SET user_id = :tgt WHERE user_id = :src'
                        ),
                        {"tgt": target_user_id, "src": source_user_id},
                    )
                    merged = count
            report[table] = {"rows": count, "merged": merged, "skipped": False}
        except IntegrityError:
            report[table] = {"rows": None, "merged": 0, "skipped": True}
    return report


def bind_owner_email(email: str, *, session_factory=SessionLocal) -> dict:
    target_id = get_settings().default_user
    normalized = email.strip().lower()
    with session_factory() as session:
        target = session.get(UserRow, target_id)
        if target is None:
            raise RuntimeError(f"default-user 行不存在：{target_id}")
        stray = (
            session.query(UserRow).filter(UserRow.email == normalized).one_or_none()
        )
        if stray is not None and stray.id == target_id:
            return {"bound": True, "already": True}
        result = {
            "bound": False,
            "already": False,
            "stray_id": stray.id if stray is not None else None,
        }
        if stray is not None:
            stray.email = None
            session.flush()
        target.email = normalized
        if target.display_name is None:
            target.display_name = normalized.split("@", 1)[0]
        target.updated_at = datetime.now()
        session.commit()
        result["bound"] = True
        return result


def delete_user_row(user_id: str, *, session_factory=SessionLocal) -> bool:
    with session_factory() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def adopt_owner_identity(
    email: str,
    *,
    apply: bool = False,
    engine,
    session_factory=SessionLocal,
    tables: list[str] | None = None,
) -> dict:
    normalized = email.strip().lower()
    target_id = get_settings().default_user
    ensure_default_user()

    if tables is None:
        tables = tables_with_user_id(engine)
    stray = None
    with session_factory() as session:
        stray_row = (
            session.query(UserRow).filter(UserRow.email == normalized).one_or_none()
        )
        if stray_row is not None and stray_row.id != target_id:
            session.expunge(stray_row)
            stray = stray_row.id

    report: dict = {
        "mode": "apply" if apply else "dry_run",
        "email": normalized,
        "target_user_id": target_id,
        "stray_user_id": stray,
        "tables": tables,
    }
    if stray is not None and stray != target_id:
        report["source_rows"] = count_user_rows(tables, engine, stray)
        if apply:
            report["merge"] = merge_user_data(stray, target_id, tables, engine)
    if not apply:
        return report

    report["bind"] = bind_owner_email(normalized, session_factory=session_factory)
    skipped = [
        table for table, detail in report.get("merge", {}).items() if detail["skipped"]
    ]
    report["skipped_tables"] = skipped
    if stray is not None and stray != target_id and not skipped:
        report["stray_deleted"] = delete_user_row(stray, session_factory=session_factory)
    elif stray is not None and skipped:
        report["stray_deleted"] = False
        report["warning"] = (
            f"存在冲突跳过表 {skipped}，email-* 行保留（email 已置空）待人工处理"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Owner 身份归并（幂等）")
    parser.add_argument("--email", required=True, help="owner 邮箱")
    parser.add_argument("--apply", action="store_true", help="执行归并（默认 dry-run）")
    args = parser.parse_args()

    from app.core.db import engine

    report = adopt_owner_identity(
        args.email, apply=args.apply, engine=engine
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
