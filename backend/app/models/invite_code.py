"""邀请码模型：连接患者数据与医生/家长权限的唯一凭证。

状态机（文档 6.2）：
  生成 → 未使用
  未使用 → 已填 / 已过期 / 已作废
  已填 → 已阅 / 已撤回
  已阅 → 已撤回（已阅不剥夺患者撤回权）
  已撤回 / 已过期 / 已作废 → 终态
"""
from datetime import datetime

from ..extensions import db

STATUS_UNUSED = "unused"
STATUS_USED = "used"        # 已填：患者已完成测评
STATUS_VIEWED = "viewed"    # 已阅：医生已打开报告
STATUS_REVOKED = "revoked"  # 已撤回（终态）
STATUS_EXPIRED = "expired"  # 已过期（终态）
STATUS_CANCELLED = "cancelled"  # 已作废（终态）


class InviteCode(db.Model):
    __tablename__ = "invite_codes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(8), unique=True, nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_UNUSED, index=True)
    remark = db.Column(db.String(200))
    generated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    used_at = db.Column(db.DateTime)
    viewed_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    expired_at = db.Column(db.DateTime)
    expires_days = db.Column(db.Integer)  # 可选有效期（天），为空表示永久有效

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "status": self.status,
            "remark": self.remark,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "used_at": self.used_at.isoformat() if self.used_at else None,
            "viewed_at": self.viewed_at.isoformat() if self.viewed_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
        }
