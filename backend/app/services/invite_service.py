"""邀请码生命周期服务（文档 4.2 / 6.2 / 3.7）。

状态迁移均在此层完成，API 层只做参数校验与权限检查。
撤回执行物理 DELETE（文档 7.3）：作答记录、会话、知情记录随事务删除。
"""
import hashlib
import logging
import sys
from datetime import datetime, timedelta

from ..extensions import db
from ..models import (AssessmentSession, InviteCode, SESSION_COMPLETED,
                      SESSION_IN_PROGRESS, SESSION_REVOKED, STATUS_CANCELLED,
                      STATUS_EXPIRED, STATUS_REVOKED, STATUS_UNUSED,
                      STATUS_USED, STATUS_VIEWED)

logger = logging.getLogger(__name__)


def sha256(text):
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_invite_code_status(code):
    """验证邀请码可进入测评。

    返回 (invite, error_code, message)：
    - 可用：error_code=None
    - 不可用：error_code 对应错误码
    """
    from ..utils.errors import (INVALID_INVITE_CODE, INVITE_CODE_CANCELLED,
                                INVITE_CODE_EXPIRED, INVITE_CODE_REVOKED,
                                INVITE_CODE_USED)

    invite = InviteCode.query.filter_by(code=code).first()
    if invite is None:
        return None, INVALID_INVITE_CODE, "邀请码无效，请联系向您提供邀请码的人士"
    if invite.status == STATUS_REVOKED:
        return invite, INVITE_CODE_REVOKED, "该邀请码对应的数据已被撤回"
    if invite.status == STATUS_CANCELLED:
        return invite, INVITE_CODE_CANCELLED, "该邀请码已被作废，请联系邀请您的人士"
    if invite.status in (STATUS_USED, STATUS_VIEWED):
        return invite, INVITE_CODE_USED, "该邀请码已被使用，如需重新测评请联系邀请您的人士"
    if invite.status == STATUS_EXPIRED:
        return invite, INVITE_CODE_EXPIRED, "该邀请码已过期，请联系邀请您的人士获取新的邀请码"
    if invite.expired_at and invite.expired_at < datetime.utcnow():
        return invite, INVITE_CODE_EXPIRED, "该邀请码已过期，请联系邀请您的人士获取新的邀请码"
    return invite, None, ""


def get_or_create_session(invite):
    """获取或创建会话；已存在进行中会话则返回（支持断点续答）。"""
    session = AssessmentSession.query.filter_by(invite_code_id=invite.id).first()
    if session is None:
        session = AssessmentSession(invite_code_id=invite.id,
                                    status=SESSION_IN_PROGRESS)
        db.session.add(session)
        db.session.commit()
    return session


def set_resume_deadline(session, hours=None):
    """设置断点续答截止时间（文档 3.5：24 小时内可用同码继续）。"""
    if hours is None:
        from .config_service import get_config_int
        hours = get_config_int("session_resume_hours", 24)
    session.resume_deadline = datetime.utcnow() + timedelta(hours=hours)
    db.session.commit()


def mark_consent(session, ua_hash=None, ip_hash=None):
    session.consent_given = True
    session.consent_at = datetime.utcnow()
    session.consent_ua_hash = ua_hash
    session.consent_ip_hash = ip_hash
    db.session.commit()


def mark_completed(session, invite):
    from datetime import datetime
    session.status = SESSION_COMPLETED
    session.completed_at = datetime.utcnow()
    if invite is not None:  # 匿名自测会话无邀请码
        invite.status = STATUS_USED
        invite.used_at = datetime.utcnow()
    db.session.commit()


def mark_viewed(invite):
    """医生打开报告时自动标记已阅（文档 4.3）。"""
    if invite.status == STATUS_USED:
        invite.status = STATUS_VIEWED
        invite.viewed_at = datetime.utcnow()
        db.session.commit()


def revoke_session(session, invite):
    """24 小时撤回：物理删除作答记录与会话（事务保证一致性）。

    匿名自测会话 invite 为 None：仅删除会话与作答，无邀请码状态可更新。
    """
    from ..models import AuditLog

    if sys.platform == "emscripten":
        from ..cloudflare_runtime import atomic_batch

        revoked_at = datetime.utcnow().isoformat(sep=" ")
        target_type = "invite_code" if invite is not None else "assessment_session"
        target_id = invite.id if invite is not None else session.id
        detail = ("患者端撤回数据（匿名化记录，不含数据副本）"
                  if invite is not None else "匿名自测撤回")
        statements = [
            ("DELETE FROM item_responses WHERE session_id = ?", (session.id,)),
            ("DELETE FROM assessment_sessions WHERE id = ?", (session.id,)),
        ]
        if invite is not None:
            statements.append((
                "UPDATE invite_codes SET status = ?, revoked_at = ? WHERE id = ?",
                (STATUS_REVOKED, revoked_at, invite.id),
            ))
        statements.append((
            "INSERT INTO audit_logs "
            "(action, target_type, target_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("patient_revoke", target_type, target_id, detail, revoked_at),
        ))
        atomic_batch(statements)
        db.session.remove()
        return

    # 物理删除作答记录
    session.responses.delete()
    db.session.delete(session)
    if invite is not None:
        invite.status = STATUS_REVOKED
        invite.revoked_at = datetime.utcnow()
        target = ("invite_code", invite.id)
    else:
        target = ("assessment_session", session.id)
    db.session.add(AuditLog(action="patient_revoke", target_type=target[0],
                            target_id=target[1],
                            detail="匿名自测撤回" if invite is None
                            else "患者端撤回数据（匿名化记录，不含数据副本）"))
    db.session.commit()


def can_revoke(session, invite):
    """撤回可行性校验（文档 3.7；匿名自测会话同样适用）：
    1. 提交后 24 小时内（revoke_hours 可配置）；
    2. 邀请码状态为已填/已阅（匿名会话无邀请码，仅校验完成状态）。
    返回 (ok, error_code, message)。
    """
    from ..utils.errors import ALREADY_REVOKED, NOT_REVOKABLE, REVOKE_TOO_LATE
    from .config_service import get_config_int

    if invite is not None and invite.status == STATUS_REVOKED:
        return False, ALREADY_REVOKED, "该数据已被撤回"
    if session.status == SESSION_REVOKED:
        return False, ALREADY_REVOKED, "该数据已被撤回"
    if session.status != SESSION_COMPLETED or not session.completed_at:
        return False, NOT_REVOKABLE, "该测评尚未完成提交，无需撤回"
    if invite is not None and invite.status not in (STATUS_USED, STATUS_VIEWED):
        return False, NOT_REVOKABLE, "当前状态不支持撤回操作"

    revoke_hours = get_config_int("revoke_hours", 24)
    deadline = session.completed_at + timedelta(hours=revoke_hours)
    if datetime.utcnow() > deadline:
        return False, REVOKE_TOO_LATE, f"已超过 {revoke_hours} 小时撤回期限，数据无法撤回"
    return True, None, ""
