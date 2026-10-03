"""医生/家长端接口（文档第四章）。

权限模型：医生仅能查看自己生成邀请码所关联的数据（后端强制校验，
绝不在前端做权限假设）。数据导出即时生成即时返回，服务器不留存文件。
"""
import io
import json

from flask import Blueprint, g, request, send_file

from ..extensions import db
from ..middleware.auth import professional_required
from ..models import (AssessmentSession, AuditLog, InviteCode, SESSION_COMPLETED,
                      SESSION_REVOKED, Scale, ScaleItem, ScalePackage,
                      STATUS_UNUSED)
from ..services import invite_service
from ..services.report import build_report
from ..utils.code_generator import generate_invite_code
from ..utils.errors import NOT_FOUND, PERMISSION_DENIED, VALIDATION_ERROR
from ..utils.response import error, ok

bp = Blueprint("doctor", __name__, url_prefix="/api/v1/doctor")


def _pagination():
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    page = max(page, 1)
    size = min(max(size, 1), 100)
    return page, size


def _check_report_access(session):
    """报告数据归属校验：仅生成该邀请码的医生/家长可见。"""
    if session is None:
        return error(NOT_FOUND, "报告不存在")
    invite = session.invite_code
    if invite is None or invite.creator_id != g.current_user.id:
        return error(PERMISSION_DENIED, "无权访问该报告")
    return None


# ---------- 邀请码管理（文档 4.2） ----------

@bp.post("/invite-codes")
@professional_required
def create_invite_code():
    data = request.get_json(silent=True) or {}
    remark = (data.get("remark") or "").strip()[:200]
    expires_days = data.get("expires_days")

    # 唯一性：循环生成直到无冲突
    for _ in range(50):
        code = generate_invite_code()
        if InviteCode.query.filter_by(code=code).first() is None:
            break
    else:
        return error(5003, "邀请码生成失败，请重试")

    invite = InviteCode(code=code, creator_id=g.current_user.id,
                        remark=remark or None,
                        expires_days=expires_days)
    db.session.add(invite)
    db.session.add(AuditLog(action="invite_generate", user_id=g.current_user.id,
                            target_type="invite_code", target_id=invite.id,
                            detail=f"生成邀请码 {code}"))
    db.session.commit()

    return ok(invite.to_dict(), "邀请码已生成")


@bp.get("/invite-codes")
@professional_required
def list_invite_codes():
    page, size = _pagination()
    status = request.args.get("status")
    search = (request.args.get("search") or "").strip()

    query = InviteCode.query.filter_by(creator_id=g.current_user.id)
    if status:
        query = query.filter_by(status=status)
    if search:
        query = query.filter(InviteCode.code.like(f"%{search.upper()}%")
                             | InviteCode.remark.like(f"%{search}%"))

    total = query.count()
    items = (query.order_by(InviteCode.generated_at.desc())
             .offset((page - 1) * size).limit(size).all())
    return ok({
        "total": total,
        "page": page,
        "size": size,
        "items": [it.to_dict() for it in items],
    })


@bp.patch("/invite-codes/<int:invite_id>")
@professional_required
def update_invite_code(invite_id):
    data = request.get_json(silent=True) or {}
    invite = InviteCode.query.filter_by(id=invite_id,
                                        creator_id=g.current_user.id).first()
    if invite is None:
        return error(PERMISSION_DENIED, "邀请码不存在或无权操作")

    action = data.get("action")
    if action == "cancel":
        if invite.status != STATUS_UNUSED:
            return error(5003, "仅未使用的邀请码可以作废")
        from ..models import STATUS_CANCELLED
        invite.status = STATUS_CANCELLED
        db.session.add(AuditLog(action="invite_cancel", user_id=g.current_user.id,
                                target_type="invite_code", target_id=invite.id))
    elif "remark" in data:
        invite.remark = (data.get("remark") or "").strip()[:200] or None
    else:
        return error(VALIDATION_ERROR, "不支持的操作")

    db.session.commit()
    return ok(invite.to_dict())


# ---------- 报告（文档 4.3 / 4.4） ----------

@bp.get("/reports")
@professional_required
def list_reports():
    page, size = _pagination()
    status = request.args.get("status")  # used / viewed / revoked

    query = (AssessmentSession.query
             .join(InviteCode, AssessmentSession.invite_code_id == InviteCode.id)
             .filter(InviteCode.creator_id == g.current_user.id)
             .filter(AssessmentSession.status.in_([SESSION_COMPLETED, SESSION_REVOKED])))
    if status:
        query = query.filter(InviteCode.status == status)

    total = query.count()
    rows = (query.order_by(AssessmentSession.completed_at.desc())
            .offset((page - 1) * size).limit(size).all())

    items = []
    for s in rows:
        invite = s.invite_code
        pkg = db.session.get(ScalePackage, s.push_package_id) if s.push_package_id else None
        items.append({
            "session_id": s.id,
            "invite_code": invite.code,
            "remark": invite.remark,
            "invite_status": invite.status,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
            "package_name": pkg.name if pkg else None,
        })
    return ok({"total": total, "page": page, "size": size, "items": items})


@bp.get("/reports/<int:session_id>")
@professional_required
def report_detail(session_id):
    session = db.session.get(AssessmentSession, session_id)
    err = _check_report_access(session)
    if err:
        return err
    if session.status != SESSION_COMPLETED:
        return error(NOT_FOUND, "该测评尚未完成，暂无报告")

    viewer_role = g.current_user.role  # parent 显示家长版标签
    report = build_report(session, viewer_role=viewer_role)

    # 自动标记已阅（文档 4.3）
    invite = session.invite_code
    was_unread = invite.status == "used"
    invite_service.mark_viewed(invite)
    if was_unread:
        db.session.add(AuditLog(action="doctor_view_report", user_id=g.current_user.id,
                                target_type="assessment_session", target_id=session.id))
        db.session.commit()

    return ok(report)


@bp.get("/reports/<int:session_id>/export/pdf")
@professional_required
def export_pdf(session_id):
    import sys
    if sys.platform == "emscripten":
        return error(VALIDATION_ERROR, "Cloudflare 免费版请在报告页使用打印并保存 PDF")
    session = db.session.get(AssessmentSession, session_id)
    err = _check_report_access(session)
    if err:
        return err
    if session.status != SESSION_COMPLETED:
        return error(NOT_FOUND, "该测评尚未完成，无法导出")

    report = build_report(session, viewer_role=g.current_user.role)
    pdf_bytes = _build_pdf(report)

    invite = session.invite_code
    db.session.add(AuditLog(action="doctor_export_pdf", user_id=g.current_user.id,
                            target_type="assessment_session", target_id=session.id))
    db.session.commit()

    return send_file(
        io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
        download_name=f"心镜报告-{invite.code}.pdf")


@bp.get("/reports/<int:session_id>/export/excel")
@professional_required
def export_excel(session_id):
    import sys
    if sys.platform == "emscripten":
        return error(VALIDATION_ERROR, "Cloudflare 免费版请在报告页导出 CSV")
    session = db.session.get(AssessmentSession, session_id)
    err = _check_report_access(session)
    if err:
        return err
    if session.status != SESSION_COMPLETED:
        return error(NOT_FOUND, "该测评尚未完成，无法导出")

    report = build_report(session, viewer_role=g.current_user.role)
    xlsx_bytes = _build_excel(report)

    invite = session.invite_code
    db.session.add(AuditLog(action="doctor_export_excel", user_id=g.current_user.id,
                            target_type="assessment_session", target_id=session.id))
    db.session.commit()

    return send_file(
        io.BytesIO(xlsx_bytes), mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        as_attachment=True, download_name=f"心镜数据-{invite.code}.xlsx")


@bp.post("/reports/<int:session_id>/export-event")
@professional_required
def export_event(session_id):
    """浏览器端生成 PDF/CSV 时仍记录导出操作。"""
    session = db.session.get(AssessmentSession, session_id)
    err = _check_report_access(session)
    if err:
        return err
    if session.status != SESSION_COMPLETED:
        return error(NOT_FOUND, "该测评尚未完成，无法导出")
    kind = (request.get_json(silent=True) or {}).get("kind")
    if kind not in ("pdf", "csv"):
        return error(VALIDATION_ERROR, "导出类型无效")
    db.session.add(AuditLog(action=f"doctor_export_{kind}", user_id=g.current_user.id,
                            target_type="assessment_session", target_id=session.id))
    db.session.commit()
    return ok({"recorded": True})


# ---------- 导出实现 ----------

def _build_pdf(report):
    """PDF 导出（文档 4.4）：封面 + 内容页 + 页脚免责声明。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCN", parent=styles["Title"],
                                 fontName="STSong-Light", fontSize=20,
                                 leading=28)
    h1 = ParagraphStyle("H1CN", parent=styles["Heading1"], fontName="STSong-Light",
                        fontSize=14, leading=20, spaceBefore=14)
    h2 = ParagraphStyle("H2CN", parent=styles["Heading2"], fontName="STSong-Light",
                        fontSize=12, leading=16, spaceBefore=10)
    body = ParagraphStyle("BodyCN", parent=styles["BodyText"], fontName="STSong-Light",
                          fontSize=10, leading=15)
    small = ParagraphStyle("SmallCN", parent=styles["BodyText"], fontName="STSong-Light",
                           fontSize=8, leading=11, textColor=colors.grey)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=2 * cm, leftMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    story = []

    # 封面
    story.append(Paragraph("心理状态自测报告", title_style))
    story.append(Spacer(1, 12))
    ov = report["overview"]
    story.append(Paragraph(f"邀请码：{ov['invite_code']}", body))
    story.append(Paragraph(f"测评完成时间：{ov['completed_at'] or '—'}", body))
    story.append(Paragraph(f"测评组合包：{ov['package_name'] or '—'}", body))
    story.append(Paragraph(f"导出时间：{report['generated_at']}", body))
    story.append(Spacer(1, 12))

    # 概览表
    story.append(Paragraph("一、报告概览", h1))
    table_data = [["量表", "缩写", "总分", "满分"]]
    for row in ov.get("summary", []):
        table_data.append([row["name_zh"], row["abbreviation"],
                           str(row["total_score"]), str(row["max_score"])])
    if len(table_data) > 1:
        t = Table(table_data, colWidths=[6 * cm, 3 * cm, 3 * cm, 3 * cm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(t)

    # 逐量表
    for s in report["scales"]:
        story.append(Paragraph(f"二、{s['name_zh']}（{s['abbreviation'] or ''}）", h1))
        if s.get("description"):
            story.append(Paragraph(s["description"], body))
        sc = s["score"]
        story.append(Paragraph(
            f"总分 {sc['total_score']} / {sc['max_score']}；"
            f"常模对比：{_norm_text(sc['total_score'], s.get('norm'))}", body))
        for dim, entry in sc.get("dimension_scores", {}).items():
            story.append(Paragraph(
                f"维度「{dim}」：{entry['score']} / {entry['max']}", body))
        # 逐题作答表
        story.append(Paragraph("逐题作答记录", h2))
        rows = [["题号", "题目", "患者选择", "得分"]]
        for it in s["items"]:
            rows.append([str(it["item_number"]), it["item_text"],
                         it["chosen_text"] or "—",
                         str(it["final_score"] if it["final_score"] is not None
                             else it["raw_score"])])
        t = Table(rows, colWidths=[1.5 * cm, 8 * cm, 4.5 * cm, 1.5 * cm],
                  repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

    # 综合分科参考
    if report["referral_labels"]:
        story.append(Paragraph("三、综合分科参考", h1))
        for label in report["referral_labels"]:
            story.append(Paragraph(f"· {label['label']}", body))

    # 免责声明
    story.append(Spacer(1, 12))
    story.append(Paragraph(report["disclaimer"], small))
    story.append(Paragraph(report["copyright"], small))

    doc.build(story)
    return buf.getvalue()


def _build_excel(report):
    """Excel 导出（文档 4.4）：概览 + 逐量表 + 原始数据。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="EEF2F7")
    bold = Font(bold=True)

    # 工作表1：概览
    ws = wb.active
    ws.title = "概览"
    ov = report["overview"]
    ws.append(["邀请码", ov["invite_code"]])
    ws.append(["备注", ov.get("remark") or ""])
    ws.append(["完成时间", ov.get("completed_at") or ""])
    ws.append(["组合包", ov.get("package_name") or ""])
    ws.append(["量表", "缩写", "总分", "满分"])
    for row in ov.get("summary", []):
        ws.append([row["name_zh"], row["abbreviation"],
                   row["total_score"], row["max_score"]])
    for cell in ws[5]:
        cell.font = bold
        cell.fill = header_fill

    # 逐量表工作表
    for s in report["scales"]:
        name = (s["abbreviation"] or s["name_zh"])[:31]
        sheet = wb.create_sheet(title=name)
        sc = s["score"]
        sheet.append(["量表", s["name_zh"], "总分", sc["total_score"], "满分", sc["max_score"]])
        for dim, entry in sc.get("dimension_scores", {}).items():
            sheet.append(["维度", dim, "得分", entry["score"], "满分", entry["max"]])
        sheet.append([])
        sheet.append(["题号", "题目", "维度", "患者选择", "原始分", "最终分", "反向计分"])
        for it in s["items"]:
            sheet.append([it["item_number"], it["item_text"], it.get("dimension") or "",
                          it.get("chosen_text") or "",
                          it["raw_score"] if it["raw_score"] is not None else "",
                          it["final_score"] if it["final_score"] is not None else "",
                          "是" if it["reversed"] else ""])
        for col in range(1, 8):
            sheet.column_dimensions[get_column_letter(col)].width = 16
        sheet.column_dimensions["B"].width = 60

    # 原始数据表
    raw = wb.create_sheet(title="原始数据")
    raw.append(["量表", "题号", "题目文本", "患者得分", "维度归属", "作答时间"])
    for s in report["scales"]:
        for it in s["items"]:
            raw.append([s["name_zh"], it["item_number"], it["item_text"],
                        it["final_score"] if it["final_score"] is not None
                        else it["raw_score"], it.get("dimension") or "", ""])
    for col in range(1, 7):
        raw.column_dimensions[get_column_letter(col)].width = 16
    raw.column_dimensions["C"].width = 60

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm_text(score, norm):
    from ..services.report import norm_position_text
    if norm:
        return norm_position_text(score, norm)
    return "暂无适用常模数据"
