"""患者端接口（文档第三章）。

全部为免登录接口。设计要点：
- 不采集任何个人身份信息（文档 1.3 / 7.1）；IP 仅存不可逆哈希；
- 知情同意是强制前置（文档 10.1 第一层），未同意禁止一切答题接口；
- 作答单题暂存、提交后计分、24 小时内可撤回（物理删除）。
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, request

from ..extensions import db
from ..models import (AssessmentSession, ItemResponse, SESSION_COMPLETED,
                      SESSION_IN_PROGRESS, SESSION_REVOKED, Scale, ScaleItem,
                      ScalePackage)
from ..services import invite_service
from ..services.config_service import get_config_int
from ..services.push_engine import decide_package
from ..services.scoring import InvalidAnswerError, MissingAnswerError, score_scale
from ..utils.code_generator import normalize_code
from ..utils.errors import (ALREADY_REVOKED, CONSENT_REQUIRED, INVALID_ANSWERS,
                            INVALID_INVITE_CODE, INVITE_CODE_USED, NOT_FOUND,
                            PHQ4_ALREADY_SUBMITTED, RESUME_CONFLICT,
                            REVOKE_TOKEN_MISMATCH, SESSION_EXPIRED,
                            SESSION_NOT_FOUND, VALIDATION_ERROR)
from ..utils.response import error, ok
from ..utils.validators import validate_answer_value, validate_invite_code

bp = Blueprint("patient", __name__, url_prefix="/api/v1/patient")

# 患者版结果页安全文案（文档 3.6）。可配置项从 system_configs 读取，缺省用以下默认值。
DEFAULT_CLOSING = "感谢您的认真参与。自我觉察是关爱自己的第一步。您愿意花时间了解自己的状态，这件事本身就值得肯定。"
DEFAULT_ENCOURAGEMENTS = [
    "心理健康和身体健康一样重要，您今天的关注是对自己的善待。",
    "每个人的情绪都会有起伏，这完全正常，您不是一个人在面对。",
    "请记得，寻求帮助不是软弱，而是一种力量和智慧的体现。",
]
DEFAULT_TIPS = [
    "规律作息：尽量保持固定的睡眠和起床时间，身体的节律对情绪有直接影响。",
    "适度运动：每天 20-30 分钟的快走或伸展，动起来就是好的开始。",
    "正念呼吸：感到紧张时，试试 4-7-8 呼吸法——吸气 4 秒，屏住 7 秒，缓慢呼气 8 秒。",
    "社交联结：和信任的人聊聊天，人际联结是情绪缓冲的重要资源。",
    "减少信息过载：适当减少刷手机的时间，特别是睡前，给大脑留一些安静的空间。",
]
DEFAULT_CONTACT_HINT = ("您的完整测评数据已安全地发送给向您提供邀请码的人士。"
                        "如需了解详细结果和专业解读，请直接联系邀请您参与测评的人士。"
                        "出于对您的保护，平台不会直接向您展示分数和详细报告。")
DEFAULT_ANON_CONTACT_HINT = ("本次为匿名自测，您的作答数据不会发送给任何专业人士，"
                             "仅用于本次自测流程。如需获得专业解读，建议联系医生、"
                             "心理老师或家长获取邀请码后重新测评。")
# 硬编码免责声明（文档 10.1 第三层：禁止从配置读取）
PATIENT_DISCLAIMER = [
    "本结果仅反映您近期填写问卷时的心理状态倾向，不代表临床诊断。",
    "心理健康是动态变化的，本次结果仅代表您作答期间的自我感受。",
    "如您近期持续感到困扰或不适，强烈建议前往正规医院精神科/临床心理科就诊咨询。",
    "全国心理援助热线：400-161-9995（24小时）。注：热线号码请在正式上线前再次确认有效性。",
]


def _ip_hash():
    return invite_service.sha256(request.remote_addr or "")


def _ua_hash():
    return invite_service.sha256(request.user_agent.string or "")


def _session_or_error(session_id):
    session = db.session.get(AssessmentSession, session_id)
    if session is None:
        return None, error(SESSION_NOT_FOUND, "测评会话不存在")
    return session, None


@bp.post("/verify-code")
def verify_code():
    """验证邀请码有效性（文档 4.2 邀请码链接跳转逻辑）。"""
    data = request.get_json(silent=True) or {}
    code = normalize_code(data.get("code") or "")
    if not validate_invite_code(code):
        return error(INVALID_INVITE_CODE, "邀请码格式不正确，请检查后重新输入")

    invite, err_code, message = invite_service.validate_invite_code_status(code)
    if invite is None:
        return error(err_code, message)

    # 断点续答信息（文档 3.5）
    session = AssessmentSession.query.filter_by(invite_code_id=invite.id).first()
    has_in_progress = False
    resume_available = False
    if session and session.status == SESSION_IN_PROGRESS:
        has_in_progress = True
        if session.resume_deadline and session.resume_deadline > datetime.utcnow():
            resume_available = True

    return ok({
        "code": invite.code,
        "valid": True,
        "has_in_progress_session": has_in_progress,
        "resume_available": resume_available,
        "consent_given": bool(session and session.consent_given),
        "session_id": session.id if session else None,
    })


@bp.post("/anonymous-start")
def anonymous_start():
    """开启匿名自测（文档 3.1/3.2：匿名自测入口，同样须经知情同意）。

    创建不绑定邀请码的匿名会话，数据不发送给任何专业人士。
    """
    session = AssessmentSession(invite_code_id=None, anonymous=True,
                                status=SESSION_IN_PROGRESS)
    db.session.add(session)
    db.session.commit()
    return ok({"session_id": session.id,
               "anonymous": True}, "匿名自测已开启")


@bp.post("/consent")
def consent():
    """提交知情同意（文档 3.2 / 10.1 第一层）。同意记录作为数据归属追溯凭证。

    支持两种模式：
    - 邀请码模式：{code, consent}
    - 匿名模式：  {session_id, anonymous: true, consent}
    """
    data = request.get_json(silent=True) or {}
    agreed = bool(data.get("consent"))
    if not agreed:
        return error(VALIDATION_ERROR, "请先阅读并同意知情同意书")

    # 匿名模式
    if data.get("anonymous"):
        session = db.session.get(AssessmentSession, data.get("session_id"))
        if session is None or not session.anonymous:
            return error(SESSION_NOT_FOUND, "匿名测评会话不存在")
        if session.status in (SESSION_COMPLETED, SESSION_REVOKED):
            return error(RESUME_CONFLICT, "该匿名测评已完成，无法重复参与")
        invite_service.mark_consent(session, ua_hash=_ua_hash(), ip_hash=_ip_hash())
        invite_service.set_resume_deadline(session)
        return ok({
            "session_id": session.id,
            "consent_at": session.consent_at.isoformat(),
        }, "感谢您的信任，现在开始测评")

    # 邀请码模式
    code = normalize_code(data.get("code") or "")
    if not validate_invite_code(code):
        return error(INVALID_INVITE_CODE, "邀请码格式不正确")

    invite, err_code, message = invite_service.validate_invite_code_status(code)
    if invite is None:
        return error(err_code, message)

    session = invite_service.get_or_create_session(invite)
    if session.status in (SESSION_COMPLETED, SESSION_REVOKED):
        return error(INVITE_CODE_USED, "该邀请码已完成测评，无法重复参与")

    invite_service.mark_consent(session, ua_hash=_ua_hash(), ip_hash=_ip_hash())
    invite_service.set_resume_deadline(session)

    return ok({
        "session_id": session.id,
        "consent_at": session.consent_at.isoformat(),
    }, "感谢您的信任，现在开始测评")


@bp.post("/phq4-submit")
def phq4_submit():
    """提交 PHQ-4 快筛答案，返回推送的组合包（文档 3.4 / 6.1）。"""
    data = request.get_json(silent=True) or {}
    session, err = _session_or_error(data.get("session_id"))
    if err:
        return err

    if not session.consent_given:
        return error(CONSENT_REQUIRED, "请先阅读并同意知情同意书")
    if session.status != SESSION_IN_PROGRESS:
        return error(RESUME_CONFLICT, "当前会话状态不允许提交快筛")
    if session.phq4_total is not None:
        return error(PHQ4_ALREADY_SUBMITTED, "快筛已提交，请勿重复操作")

    answers = data.get("answers")
    if not isinstance(answers, list) or len(answers) != 4:
        return error(VALIDATION_ERROR, "快筛需提交 4 道题的答案")
    if any(not isinstance(a, int) or a not in (0, 1, 2, 3) for a in answers):
        return error(VALIDATION_ERROR, "快筛答案取值必须在 0-3 之间")

    sleep_flag = bool(data.get("sleep_flag"))
    stress_flag = bool(data.get("stress_flag"))

    package, detail = decide_package(answers, sleep_flag, stress_flag)

    session.phq4_answers_json = json.dumps(answers)
    session.phq4_anxiety = detail["phq4_anxiety"]
    session.phq4_depression = detail["phq4_depression"]
    session.phq4_total = detail["phq4_total"]
    session.sleep_flag = sleep_flag
    session.stress_flag = stress_flag
    session.push_package_id = package.id if package else None
    db.session.commit()

    if package is None:
        # 分支七：状态良好，无需深度测评 → 直接完成会话并跳转结果页（文档 3.4）
        invite = session.invite_code
        invite_service.mark_completed(session, invite)
        from ..models import AuditLog
        db.session.add(AuditLog(
            action="assessment_submit",
            target_type="invite_code" if invite else "assessment_session",
            target_id=invite.id if invite else session.id,
            detail="快筛通过，无深度测评（状态良好分支）"
            + ("（匿名自测）" if session.anonymous else "")))
        db.session.commit()
        return ok({
            "need_deep_assessment": False,
            "message": "根据您的快筛结果，本次无需进一步作答",
        })

    return ok({
        "need_deep_assessment": True,
        "package": _package_brief(package),
    }, "已为您准备好更详细的问卷")


@bp.post("/response")
def save_response():
    """单题作答暂存（文档 3.5：每题作答即时异步暂存，支持断点续答）。"""
    data = request.get_json(silent=True) or {}
    session, err = _session_or_error(data.get("session_id"))
    if err:
        return err

    if not session.consent_given:
        return error(CONSENT_REQUIRED, "请先阅读并同意知情同意书")
    if session.status != SESSION_IN_PROGRESS:
        return error(RESUME_CONFLICT, "当前会话已提交或已撤回")

    scale_id = data.get("scale_id")
    item_number = data.get("item_number")
    option_index = data.get("option_index")
    score = data.get("score")
    if not isinstance(scale_id, int) or not isinstance(item_number, int):
        return error(VALIDATION_ERROR, "参数格式错误")

    scale = db.session.get(Scale, scale_id)
    item = (ScaleItem.query
            .filter_by(scale_id=scale_id, item_number=item_number).first())
    if scale is None or scale.status != "active" or item is None:
        return error(VALIDATION_ERROR, "题目不存在或量表已停用")

    try:
        options = json.loads(item.options_json or "[]")
    except ValueError:
        options = []

    # 患者端传 option_index（不接触分值）；内部调用方可直接传 score
    if option_index is not None:
        if not isinstance(option_index, int) or not 0 <= option_index < len(options):
            return error(VALIDATION_ERROR, "选项下标非法")
        score = options[option_index].get("score")
    if not isinstance(score, int) or not validate_answer_value(score, options):
        return error(VALIDATION_ERROR, "作答值不在该题选项范围内")

    row = (ItemResponse.query
           .filter_by(session_id=session.id, scale_id=scale_id,
                      item_number=item_number).first())
    if row is None:
        row = ItemResponse(session_id=session.id, scale_id=scale_id,
                           item_number=item_number, item_text=item.item_text,
                           raw_score=score, dimension=item.dimension,
                           reversed=item.is_reversed)
        db.session.add(row)
    else:
        row.raw_score = score
        row.dimension = item.dimension
        row.reversed = item.is_reversed
        row.responded_at = datetime.utcnow()
    db.session.commit()

    answered = (ItemResponse.query
                .filter_by(session_id=session.id).count())
    return ok({"saved": True, "answered_count": answered})


@bp.post("/submit")
def submit():
    """提交全部作答（文档 3.5 全部完成后提交）。校验完整性→计分→状态流转。"""
    data = request.get_json(silent=True) or {}
    session, err = _session_or_error(data.get("session_id"))
    if err:
        return err

    if not session.consent_given:
        return error(CONSENT_REQUIRED, "请先阅读并同意知情同意书")
    if session.status != SESSION_IN_PROGRESS:
        return error(RESUME_CONFLICT, "当前会话已提交或已撤回")
    if session.phq4_total is None:
        return error(VALIDATION_ERROR, "请先完成快速筛查")
    if session.push_package_id is None:
        return error(VALIDATION_ERROR, "本次测评无需提交深度量表")

    package = db.session.get(ScalePackage, session.push_package_id)
    if package is None or package.status != "active":
        return error(NOT_FOUND, "测评组合包不存在或已停用")

    ordered = package.ordered_scales()
    if not ordered:
        return error(INVALID_ANSWERS, "测评组合包内没有可用量表")

    # 完整性校验：组合包内每个量表的每一题都应有作答
    for scale, _ in ordered:
        answered = (ItemResponse.query
                    .filter_by(session_id=session.id, scale_id=scale.id).count())
        if answered < scale.items.count():
            return error(INVALID_ANSWERS,
                         f"量表「{scale.name_zh}」尚有题目未完成，请完成后再提交")

    # 计分并回填 final_score
    raw_maps = {}
    responses = list(session.responses.all())
    for r in responses:
        raw_maps.setdefault(r.scale_id, {})[r.item_number] = r.raw_score

    try:
        scored = {}
        for scale, _ in ordered:
            scored[scale.id] = score_scale(scale, raw_maps.get(scale.id, {}))
    except (MissingAnswerError, InvalidAnswerError) as e:
        return error(INVALID_ANSWERS, f"计分校验未通过：{e}")

    for scale_id, result in scored.items():
        by_number = {s["item_number"]: s for s in result["item_scores"]}
        for r in responses:
            if r.scale_id == scale_id and r.item_number in by_number:
                r.final_score = by_number[r.item_number]["final_score"]
                r.reversed = by_number[r.item_number]["reversed"]

    invite = session.invite_code
    invite_service.mark_completed(session, invite)

    from ..models import AuditLog
    db.session.add(AuditLog(
        action="assessment_submit",
        target_type="invite_code" if invite else "assessment_session",
        target_id=invite.id if invite else session.id,
        detail=f"测评提交完成（{len(ordered)} 个量表）"
        + ("（匿名自测）" if session.anonymous else "")))
    db.session.commit()

    return ok({
        "session_id": session.id,
        "completed": True,
        "scales_count": len(ordered),
    }, "作答已提交，感谢您的认真参与")


@bp.get("/result/<int:session_id>")
def result(session_id):
    """患者版结果页（文档 3.6）：只展示安全、支持性内容，不含任何分数。"""
    session, err = _session_or_error(session_id)
    if err:
        return err

    if session.status == SESSION_IN_PROGRESS:
        return ok({"status": "in_progress",
                   "message": "测评尚未完成，请继续作答或稍后使用同一邀请码继续"})
    if session.status == SESSION_REVOKED:
        return ok({"status": "revoked",
                   "message": "您的数据已成功撤回并删除。如需重新测评，请联系邀请您的人士获取新的邀请码。"})

    # 撤回入口可用性（文档 3.6：提交后 24 小时内显示）
    from ..services.config_service import get_config
    revoke_hours = get_config_int("revoke_hours", 24)
    deadline = session.completed_at + timedelta(hours=revoke_hours) \
        if session.completed_at else None
    revoke_available = bool(
        deadline and datetime.utcnow() <= deadline
        and session.status == SESSION_COMPLETED)

    return ok({
        "status": "completed",
        "anonymous": session.anonymous,
        "closing_message": get_config("patient_closing_message", DEFAULT_CLOSING),
        "encouragements": get_config("patient_encouragements", DEFAULT_ENCOURAGEMENTS),
        "tips": get_config("patient_tips", DEFAULT_TIPS),
        "disclaimer": PATIENT_DISCLAIMER,
        "contact_hint": get_config(
            "patient_anon_contact_hint" if session.anonymous
            else "patient_contact_hint",
            DEFAULT_ANON_CONTACT_HINT if session.anonymous else DEFAULT_CONTACT_HINT),
        "revoke_available": revoke_available,
        "revoke_deadline": deadline.isoformat() if deadline else None,
    })


@bp.post("/revoke/<int:session_id>")
def revoke(session_id):
    """24 小时撤回（文档 3.7）：需输入"确认撤回"四字二次确认。"""
    data = request.get_json(silent=True) or {}
    confirm_text = (data.get("confirm_text") or "").strip()
    if confirm_text != "确认撤回":
        return error(REVOKE_TOKEN_MISMATCH, "请输入「确认撤回」四个字以完成撤回")

    session, err = _session_or_error(session_id)
    if err:
        # 数据已被物理删除：若附带邀请码且其状态为已撤回，返回友好提示（文档 3.7）
        code_hint = normalize_code((data.get("invite_code") or ""))
        if code_hint:
            invite = invite_service.validate_invite_code_status(code_hint)[0]
            if invite and invite.status == "revoked":
                return error(ALREADY_REVOKED, "该数据已被撤回")
        return err

    invite = session.invite_code
    can, err_code, message = invite_service.can_revoke(session, invite)
    if not can:
        return error(err_code, message)

    invite_service.revoke_session(session, invite)
    return ok(message="您的数据已成功撤回并删除，邀请码已作废")


@bp.get("/package-detail/<int:session_id>")
def package_detail(session_id):
    """深度包完整题目（文档 3.5）。

    注意：返回的选项仅含文字，不含分值——患者端绝不暴露任何计分信息。
    """
    session, err = _session_or_error(session_id)
    if err:
        return err
    if not session.consent_given:
        return error(CONSENT_REQUIRED, "请先阅读并同意知情同意书")
    if session.push_package_id is None:
        return error(VALIDATION_ERROR, "本次测评无深度量表")

    package = db.session.get(ScalePackage, session.push_package_id)
    if package is None or package.status != "active":
        return error(NOT_FOUND, "测评组合包不存在或已停用")

    scales = []
    for scale, _ in package.ordered_scales():
        items = (ScaleItem.query
                 .filter_by(scale_id=scale.id)
                 .order_by(ScaleItem.sort_order.asc(), ScaleItem.item_number.asc())
                 .all())
        scales.append({
            "scale_id": scale.id,
            "abbreviation": scale.abbreviation,
            "name_zh": scale.name_zh,
            "item_count": len(items),
            "estimated_minutes": scale.estimated_minutes,
            "items": [
                {
                    "item_number": it.item_number,
                    "item_text": it.item_text,
                    "options": [
                        {"text": opt.get("text")}
                        for opt in json.loads(it.options_json or "[]")
                    ],
                }
                for it in items
            ],
        })
    return ok({"package_id": package.id, "name": package.name,
               "scales": scales})


@bp.get("/session-answers/<int:session_id>")
def session_answers(session_id):
    """断点续答：返回会话已作答记录的选项下标（文档 3.5）。

    仅返回选项下标而非分值，患者端不接触任何计分信息。
    """
    session, err = _session_or_error(session_id)
    if err:
        return err
    if not session.consent_given:
        return error(CONSENT_REQUIRED, "请先阅读并同意知情同意书")

    by_scale = {}
    rows = (ItemResponse.query.filter_by(session_id=session.id).all())
    items_by_scale = {}
    for r in rows:
        if r.scale_id not in items_by_scale:
            item_rows = (ScaleItem.query
                         .filter_by(scale_id=r.scale_id)
                         .order_by(ScaleItem.sort_order.asc(), ScaleItem.item_number.asc())
                         .all())
            items_by_scale[r.scale_id] = {it.item_number: it for it in item_rows}
        item = items_by_scale[r.scale_id].get(r.item_number)
        index = None
        if item:
            try:
                options = json.loads(item.options_json or "[]")
            except ValueError:
                options = []
            for i, opt in enumerate(options):
                if opt.get("score") == r.raw_score:
                    index = i
                    break
        by_scale.setdefault(str(r.scale_id), {})[r.item_number] = index
    return ok(by_scale)


@bp.get("/anon-status/<int:session_id>")
def anon_status(session_id):
    """匿名会话状态查询（断点续答，文档 3.5）。"""
    session = db.session.get(AssessmentSession, session_id)
    if session is None or not session.anonymous:
        return ok({"exists": False})

    resume_available = bool(
        session.status == SESSION_IN_PROGRESS
        and session.resume_deadline and session.resume_deadline > datetime.utcnow())

    answered = {}
    if session.status == SESSION_IN_PROGRESS and session.push_package_id:
        package = db.session.get(ScalePackage, session.push_package_id)
        if package:
            for scale, _ in package.ordered_scales():
                answered[scale.id] = {
                    "abbreviation": scale.abbreviation,
                    "name_zh": scale.name_zh,
                    "answered": (ItemResponse.query
                                 .filter_by(session_id=session.id,
                                            scale_id=scale.id).count()),
                    "total": scale.items.count(),
                }

    return ok({
        "exists": True,
        "anonymous": True,
        "status": session.status,
        "consent_given": session.consent_given,
        "phq4_submitted": session.phq4_total is not None,
        "resume_available": resume_available,
        "resume_deadline": (session.resume_deadline.isoformat()
                            if session.resume_deadline else None),
        "answered": answered,
    })


@bp.get("/session-status/<code>")
def session_status(code):
    """查询邀请码对应的会话状态（用于断点续答，文档 3.5）。"""
    code = normalize_code(code)
    invite = invite_service.validate_invite_code_status(code)[0]
    if invite is None:
        return ok({"exists": False, "valid": False})

    session = AssessmentSession.query.filter_by(invite_code_id=invite.id).first()
    if session is None:
        return ok({"exists": False, "valid": True, "status": "not_started"})

    resume_available = bool(
        session.status == SESSION_IN_PROGRESS
        and session.resume_deadline and session.resume_deadline > datetime.utcnow())

    answered = {}
    if session.status == SESSION_IN_PROGRESS and session.push_package_id:
        package = db.session.get(ScalePackage, session.push_package_id)
        if package:
            for scale, _ in package.ordered_scales():
                answered[scale.id] = {
                    "abbreviation": scale.abbreviation,
                    "name_zh": scale.name_zh,
                    "answered": (ItemResponse.query
                                 .filter_by(session_id=session.id,
                                            scale_id=scale.id).count()),
                    "total": scale.items.count(),
                }

    return ok({
        "exists": True,
        "valid": True,
        "status": session.status,
        "consent_given": session.consent_given,
        "phq4_submitted": session.phq4_total is not None,
        "resume_available": resume_available,
        "resume_deadline": (session.resume_deadline.isoformat()
                            if session.resume_deadline else None),
        "answered": answered,
    })


def _package_brief(package):
    """组合包对外简报（不包含计分/规则信息）。"""
    return {
        "package_id": package.id,
        "name": package.name,
        "description": package.description,
        "estimated_time_minutes": package.estimated_time_minutes,
        "scales": [
            {
                "scale_id": scale.id,
                "abbreviation": scale.abbreviation,
                "name_zh": scale.name_zh,
                "item_count": scale.items.count(),
                "estimated_minutes": scale.estimated_minutes,
            }
            for scale, _ in package.ordered_scales()
        ],
    }
