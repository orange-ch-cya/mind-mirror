"""从项目种子函数生成 D1 初始化 SQL，不包含默认管理员或测评数据。"""
import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from seed import (seed_configs, seed_norms, seed_packages, seed_push_rules,
                  seed_referral_rules, seed_scales)  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        for seed in (seed_configs, seed_scales, seed_packages,
                     seed_push_rules, seed_referral_rules, seed_norms):
            seed()
        db.session.commit()
        raw = db.engine.raw_connection()
        try:
            lines = list(raw.iterdump())
        finally:
            raw.close()

    schema = [line for line in lines if line.startswith(("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX"))]
    data = [line for line in lines if line.startswith("INSERT INTO ")
            and not line.startswith(('INSERT INTO "users"', 'INSERT INTO "audit_logs"',
                                     'INSERT INTO "invite_codes"', 'INSERT INTO "assessment_sessions"',
                                     'INSERT INTO "item_responses"'))]
    # sqlite iterdump 按表名排序，D1 导入时外键检查会先于被引用表触发。
    order = {name: index for index, name in enumerate((
        'scales', 'scale_items', 'scale_packages', 'norms', 'push_rules',
        'referral_rules', 'system_configs'))}
    data.sort(key=lambda line: order[line.split('"')[1]])
    (args.output_dir / "schema.sql").write_text("\n".join(schema) + "\n", encoding="utf-8")
    (args.output_dir / "seed.sql").write_text("\n".join(data) + "\n", encoding="utf-8")
    print(f"D1 SQL: {len(schema)} schema statements, {len(data)} seed rows")


if __name__ == "__main__":
    main()
