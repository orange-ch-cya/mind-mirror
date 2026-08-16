"""用户模型：医生 / 家长 / 管理员三类账号。

安全要求（文档 4.1 / 13.3）：
- 密码使用 werkzeug 的 pbkdf2 哈希存储，严禁明文；
- 连续 5 次登录失败锁定 30 分钟；
- 初始密码标记 must_change_password=1，首次登录强制修改。
"""
from datetime import datetime

from ..extensions import db

ROLE_DOCTOR = "doctor"      # 医生 / 心理老师 / 社工
ROLE_PARENT = "parent"      # 家长
ROLE_ADMIN = "admin"        # 平台管理员

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100))
    role = db.Column(db.String(20), nullable=False, default=ROLE_DOCTOR)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ACTIVE)
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    invite_codes = db.relationship("InviteCode", backref="creator", lazy="dynamic")

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_professional(self):
        """医生/家长端（含管理员）为专业读者。"""
        return self.role in (ROLE_DOCTOR, ROLE_PARENT, ROLE_ADMIN)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "status": self.status,
            "must_change_password": self.must_change_password,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
