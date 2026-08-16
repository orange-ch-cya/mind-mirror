"""量表配置模型：量表、量表条目、量表组合包。

设计要点（文档 2.1 / 5.2）：
- 量表条目、选项、计分规则全部配置化存储在数据库，新增量表无需改代码；
- 反向计分由 is_reversed 标记，计分引擎自动换算；
- 组合包以 JSON 数组保存量表 ID 与展示顺序（scale_ids_json）。
"""
from datetime import datetime

from ..extensions import db


class Scale(db.Model):
    __tablename__ = "scales"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name_zh = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100))
    abbreviation = db.Column(db.String(20), index=True)
    source = db.Column(db.Text)                       # 来源与版权标注
    description = db.Column(db.Text)                  # 量表简介（报告/预览用）
    target_population = db.Column(db.String(100))     # 适用人群（逗号分隔标签）
    estimated_minutes = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="active")
    license_status = db.Column(db.String(20), default="unauthorized")  # 授权状态（文档11.2）
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    items = db.relationship("ScaleItem", backref="scale", lazy="dynamic",
                            cascade="all, delete-orphan",
                            order_by="ScaleItem.sort_order")

    @property
    def item_count(self):
        return self.items.count()

    def to_dict(self):
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "abbreviation": self.abbreviation,
            "source": self.source,
            "description": self.description,
            "target_population": self.target_population,
            "estimated_minutes": self.estimated_minutes,
            "status": self.status,
            "license_status": self.license_status,
            "item_count": self.item_count,
        }


class ScaleItem(db.Model):
    __tablename__ = "scale_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scale_id = db.Column(db.Integer, db.ForeignKey("scales.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    item_number = db.Column(db.Integer, nullable=False)
    item_text = db.Column(db.Text, nullable=False)
    # JSON: [{"text":"完全没有","score":0},{"text":"有几天","score":1},...]
    options_json = db.Column(db.Text, nullable=False)
    is_reversed = db.Column(db.Boolean, default=False)
    dimension = db.Column(db.String(50))
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "item_number": self.item_number,
            "item_text": self.item_text,
            "options": json.loads(self.options_json or "[]"),
            "is_reversed": self.is_reversed,
            "dimension": self.dimension,
            "sort_order": self.sort_order,
        }


class ScalePackage(db.Model):
    __tablename__ = "scale_packages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    estimated_time_minutes = db.Column(db.Integer)
    # JSON: [{"scale_id":3,"order":1},{"scale_id":5,"order":2},...]
    scale_ids_json = db.Column(db.Text, nullable=False, default="[]")
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def ordered_scales(self):
        """按配置顺序返回 (scale, order) 列表，自动跳过已停用/已删除量表。"""
        import json
        from .scale import Scale

        result = []
        try:
            entries = json.loads(self.scale_ids_json or "[]")
        except ValueError:
            entries = []
        for entry in sorted(entries, key=lambda e: e.get("order", 0)):
            scale = db.session.get(Scale, entry.get("scale_id"))
            if scale and scale.status == "active":
                result.append((scale, entry.get("order", 0)))
        return result

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "estimated_time_minutes": self.estimated_time_minutes,
            "scales": [
                {
                    "scale_id": e.get("scale_id"),
                    "order": e.get("order"),
                } for e in sorted(json.loads(self.scale_ids_json or "[]"),
                                  key=lambda x: x.get("order", 0))
            ],
            "status": self.status,
        }
