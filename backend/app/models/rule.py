"""规则模型：分科规则（referral_rules）+ 推送规则（push_rules）。

两者均采用 JSON 条件结构（文档 6.1 / 6.4）：
  condition_json 示例：
  [{"source":"phq4","dimension":"anxiety","op":"gte","value":4},
   {"source":"phq4","dimension":"depression","op":"lt","value":3}]
  op 取值：gt / gte / lt / lte / eq / between
"""
from datetime import datetime

from ..extensions import db


class ReferralRule(db.Model):
    """分科规则：报告生成时按量表得分输出分科参考标签（文档 5.4 / 6.4）。"""

    __tablename__ = "referral_rules"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=100)  # 越小越优先
    condition_json = db.Column(db.Text, nullable=False)
    output_label_doctor = db.Column(db.Text, nullable=False)       # 医生版标签（简洁专业）
    output_label_parent = db.Column(db.Text)                       # 家长版标签（详细易懂）
    output_style = db.Column(db.String(20), default="info")        # info/warning/alert
    output_tags = db.Column(db.String(200))                        # 逗号分隔场景标签
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "condition_json": self.condition_json,
            "output_label_doctor": self.output_label_doctor,
            "output_label_parent": self.output_label_parent,
            "output_style": self.output_style,
            "output_tags": self.output_tags,
            "status": self.status,
        }


class PushRule(db.Model):
    """推送规则：快筛后决定推送哪个深度组合包（文档 6.1）。"""

    __tablename__ = "push_rules"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=100)
    condition_json = db.Column(db.Text, nullable=False)
    package_id = db.Column(db.Integer, db.ForeignKey("scale_packages.id"))
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "condition_json": self.condition_json,
            "package_id": self.package_id,
            "status": self.status,
        }
