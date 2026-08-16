"""常模数据模型（文档 5.3 / 6.3）。

常模按 量表-维度-人群分组 组织；同一分组只允许一条启用状态记录，
更新常模时新增记录并启用，旧记录自动停用（保留历史可回滚）。
"""
from datetime import datetime

from ..extensions import db


class Norm(db.Model):
    __tablename__ = "norms"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    scale_id = db.Column(db.Integer, db.ForeignKey("scales.id"), nullable=False, index=True)
    dimension = db.Column(db.String(50), nullable=False, default="total")
    population_group = db.Column(db.String(100), default="全人群")
    sample_size = db.Column(db.Integer)
    source = db.Column(db.String(200))             # 常模来源（如"中国成人常模，2019年版"）
    mean = db.Column(db.Float)
    std_dev = db.Column(db.Float)
    percentiles_json = db.Column(db.Text)          # {"p25":5,"p50":8,"p75":12,...}
    thresholds_json = db.Column(db.Text)           # {"mild":5,"moderate":10,"severe":15}
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        import json

        def _load(s):
            try:
                return json.loads(s) if s else {}
            except ValueError:
                return {}

        return {
            "id": self.id,
            "scale_id": self.scale_id,
            "dimension": self.dimension,
            "population_group": self.population_group,
            "sample_size": self.sample_size,
            "source": self.source,
            "mean": self.mean,
            "std_dev": self.std_dev,
            "percentiles": _load(self.percentiles_json),
            "thresholds": _load(self.thresholds_json),
            "status": self.status,
        }
