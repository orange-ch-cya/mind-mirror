"""重置超级管理员密码（恢复到种子初始值，must_change_password=True）。

用途：冒烟测试脚本会临时修改管理员密码以调用管理接口，运行本脚本可随时
把管理员账号恢复为文档约定的初始状态，避免"密码一直不对"。

用法：
    python scripts/reset_admin.py                    # 开发库
    python scripts/reset_admin.py --env production   # 生产库
"""
import os
import sys

# 从 scripts/ 目录运行时，把 backend/ 加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402

ADMIN_USERNAME = "admin"
INITIAL_PASSWORD = "Admin@1234"


def main():
    env = "development"
    if "--env" in sys.argv:
        env = sys.argv[sys.argv.index("--env") + 1]

    app = create_app(env)
    with app.app_context():
        admin = User.query.filter_by(username=ADMIN_USERNAME).first()
        if admin is None:
            print(f"[reset_admin] 未找到账号 {ADMIN_USERNAME}，请先运行 seed.py")
            sys.exit(1)
        admin.password_hash = generate_password_hash(INITIAL_PASSWORD)
        admin.must_change_password = True
        admin.failed_attempts = 0
        admin.locked_until = None
        db.session.commit()
        print(f"[reset_admin] 管理员密码已重置为 {INITIAL_PASSWORD}（首次登录强制修改）")


if __name__ == "__main__":
    main()
