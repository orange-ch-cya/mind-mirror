"""测评会话与作答记录模型。

测评会话（assessment_sessions）：
- 每个邀请码最多关联一个会话（invite_code_id 唯一约束，防重复提交）；
- 知情同意记录直接挂在会话上（文档 3.2：邀请码、同意时间戳、UA哈希、IP哈希）。

作答记录（item_responses）：
- 单题作答逐条暂存（文档 3.5），提交后由计分引擎计算 final_score；
- 撤回时执行物理 DELETE（文档 7.3），不留软删除标记。
"""
from datetime import datetime

from ..extensions import db

SESSION_IN_PROGRESS = "in_progress"
SESSION_COMPLETED = "completed"
SESSION_REVOKED = "revoked"


class AssessmentSession(db.Model):
    __tablename__ = "assessment_sessions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # 匿名自测会话 invite_code_id 为 NULL（anonymous=True），数据不发送给任何专业人士
    invite_code_id = db.Column(db.Integer, db.ForeignKey("invite_codes.id"),
                               unique=True, nullable=True, index=True)
    anonymous = db.Column(db.Boolean, nullable=False, default=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=SESSION_IN_PROGRESS, index=True)
    push_package_id = db.Column(db.Integer, db.ForeignKey("scale_packages.id"))

    # 知情同意记录（文档 3.2）
    consent_given = db.Column(db.Boolean, nullable=False, default=False)
    consent_at = db.Column(db.DateTime)
    consent_ua_hash = db.Column(db.String(64))
    consent_ip_hash = db.Column(db.String(64))

    # 快筛结果（PHQ-4）
    phq4_answers_json = db.Column(db.Text)   # [0,1,2,3] 四题得分
    phq4_anxiety = db.Column(db.Integer)
    phq4_depression = db.Column(db.Integer)
    phq4_total = db.Column(db.Integer)
    sleep_flag = db.Column(db.Boolean)       # 睡眠补充筛查：是否触发
    stress_flag = db.Column(db.Boolean)      # 压力补充筛查：是否触发

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    user_agent_hash = db.Column(db.String(64))
    resume_deadline = db.Column(db.DateTime)  # 断点续答有效期

    responses = db.relationship("ItemResponse", backref="session", lazy="dynamic",
                                cascade="all, delete-orphan")

    @property
    def invite_code(self):
        from .invite_code import InviteCode
        return db.session.get(InviteCode, self.invite_code_id)

    def to_dict(self):
        return {
            "id": self.id,
            "invite_code_id": self.invite_code_id,
            "status": self.status,
            "push_package_id": self.push_package_id,
            "consent_given": self.consent_given,
            "consent_at": self.consent_at.isoformat() if self.consent_at else None,
            "phq4_total": self.phq4_total,
            "phq4_anxiety": self.phq4_anxiety,
            "phq4_depression": self.phq4_depression,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ItemResponse(db.Model):
    __tablename__ = "item_responses"
    __table_args__ = (
        db.UniqueConstraint("session_id", "scale_id", "item_number",
                            name="uq_item_response_session_scale_item"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey("assessment_sessions.id"),
                           nullable=False, index=True)
    scale_id = db.Column(db.Integer, db.ForeignKey("scales.id"), nullable=False)
    item_number = db.Column(db.Integer, nullable=False)
    item_text = db.Column(db.Text, nullable=False)
    raw_score = db.Column(db.Integer, nullable=False)    # 原始选项分数
    final_score = db.Column(db.Integer)                  # 反向计分处理后得分（计分引擎回填）
    reversed = db.Column(db.Boolean, default=False)
    dimension = db.Column(db.String(50))
    responded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "scale_id": self.scale_id,
            "item_number": self.item_number,
            "item_text": self.item_text,
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "reversed": self.reversed,
            "dimension": self.dimension,
        }
