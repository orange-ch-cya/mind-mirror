"""操作日志模型（文档 7.4）：关键操作留痕，支持审计，保留期不少于 6 个月。

记录对象：报告查看、数据导出、配置修改、邀请码生成、测评提交、数据撤回等。
注意：撤回事件仅记录操作本身，不保留数据副本。
"""
from datetime import datetime

from ..extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(50), nullable=False, index=True)
    target_type = db.Column(db.String(50))
    target_id = db.Column(db.Integer)
    detail = db.Column(db.Text)
    ip_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "detail": self.detail,
            "ip_hash": self.ip_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
