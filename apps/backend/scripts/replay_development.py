"""Development 审计重放工具（DEV-004）。

默认只读校验：内存重编译各 key 仲裁胜者并与在线 active 集比对，原始审计行
零改动。--rebuild 才实际清空重写（仅审计损坏修复、停写窗口执行）。

用法：
    uv run python -m scripts.replay_development --user-id u-1
    uv run python -m scripts.replay_development --user-id u-1 --rebuild
"""

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Development 审计重放工具")
    parser.add_argument("--user-id", required=True)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="实际清空重写该用户 development 两表（默认只读校验）",
    )
    args = parser.parse_args()
    from app.services.development import audit

    report = audit.verify_replay(args.user_id, rebuild=args.rebuild)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not report["consistent"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
