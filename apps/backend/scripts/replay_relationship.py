"""关系账本重放对账工具（REL-004 / E-REL-03，恒只读）。

用法：
    uv run python -m scripts.replay_relationship --user-id u-1
"""

import argparse
import json

from app.services import relationship_audit


def main() -> None:
    parser = argparse.ArgumentParser(description="关系账本重放对账（只读）")
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    report = relationship_audit.replay_report(args.user_id)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report.get("consistent") is False:
        raise SystemExit(f"重放对账存在不可解释偏差：{report.get('unexplained')}")


if __name__ == "__main__":
    main()
