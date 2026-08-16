"""系统配置模型（文档 5.6）：全局可变参数统一管理，修改后立即生效。

支持热更新：服务层读取时优先查配置表（带进程内缓存 + 失效机制）。
"""
from datetime import datetime

from ..extensions import db


class SystemConfig(db.Model):
    __tablename__ = "system_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value_json = db.Column(db.Text, nullable=False, default="null")
    value_type = db.Column(db.String(20), nullable=False, default="str")
    # int / float / str / json / text
    description = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value_json,
            "value_type": self.value_type,
            "description": self.description,
        }
