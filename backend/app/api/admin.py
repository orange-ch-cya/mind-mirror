"""管理端接口（文档第五章）。

覆盖：量表库管理、常模管理、分科规则、推送规则、医生账号、系统配置、操作日志。
权限：全部需管理员角色（admin_required）。
"""
import csv
import io
import json
import secrets
import string

from flask import Blueprint, g, request
from ..utils.passwords import generate_password_hash

from ..extensions import db
from ..middleware.auth import admin_required
from ..models import (AuditLog, Norm, PushRule, ReferralRule, Scale, ScaleItem,
                      SystemConfig, User)
from ..services.config_service import set_config
from ..services.rule_engine import evaluate_referral_rules
from ..utils.errors import NOT_FOUND, VALIDATION_ERROR
from ..utils.response import error, ok
from ..utils.sanitize import contains_disallowed, sanitize_output
from ..utils.validators import validate_password_strength, validate_username

bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


def _pagination():
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    return max(page, 1), min(max(size, 1), 100)


def _audit(action, target_type=None, target_id=None, detail=None):
    db.session.add(AuditLog(action=action, user_id=g.current_user.id,
                            target_type=target_type, target_id=target_id,
                            detail=detail))


# ===================== 量表库管理（文档 5.2） =====================

@bp.get("/scales")
@admin_required
def list_scales():
    page, size = _pagination()
    search = (request.args.get("search") or "").strip()
    status = request.args.get("status")

    query = Scale.query
    if search:
        query = query.filter(Scale.name_zh.like(f"%{search}%")
                             | Scale.abbreviation.like(f"%{search}%"))
    if status:
        query = query.filter_by(status=status)

    total = query.count()
    items = (query.order_by(Scale.id.asc())
             .offset((page - 1) * size).limit(size).all())
    return ok({"total": total, "page": page, "size": size,
               "items": [s.to_dict() for s in items]})


@bp.post("/scales")
@admin_required
def create_scale():
    data = request.get_json(silent=True) or {}
    name_zh = (data.get("name_zh") or "").strip()
    if not name_zh:
        return error(VALIDATION_ERROR, "量表中文名称为必填")

    scale = Scale(
        name_zh=name_zh,
        name_en=(data.get("name_en") or "").strip() or None,
        abbreviation=(data.get("abbreviation") or "").strip().upper() or None,
        source=data.get("source"),
        description=data.get("description"),
        target_population=data.get("target_population"),
        estimated_minutes=data.get("estimated_minutes"),
        license_status=data.get("license_status", "unauthorized"),
        status=data.get("status", "active"),
    )
    db.session.add(scale)
    db.session.flush()
    _audit("scale_create", "scale", scale.id, f"新增量表 {name_zh}")
    db.session.commit()
    return ok(scale.to_dict())


@bp.put("/scales/<int:scale_id>")
@admin_required
def update_scale(scale_id):
    scale = db.session.get(Scale, scale_id)
    if scale is None:
        return error(NOT_FOUND, "量表不存在")
    data = request.get_json(silent=True) or {}

    for field in ("name_zh", "name_en", "abbreviation", "source", "description",
                  "target_population", "estimated_minutes", "license_status",
                  "status"):
        if field in data:
            value = data[field]
            if field == "abbreviation" and value:
                value = value.strip().upper()
            setattr(scale, field, value)
    if not scale.name_zh:
        return error(VALIDATION_ERROR, "量表中文名称不能为空")

    _audit("scale_update", "scale", scale.id, f"编辑量表 {scale.name_zh}")
    db.session.commit()
    return ok(scale.to_dict())


@bp.delete("/scales/<int:scale_id>")
@admin_required
def delete_scale(scale_id):
    """软删除：停用量表，已有数据不受影响（文档 5.2 删除=软删除）。"""
    scale = db.session.get(Scale, scale_id)
    if scale is None:
        return error(NOT_FOUND, "量表不存在")
    scale.status = "inactive"
    _audit("scale_deactivate", "scale", scale.id, f"停用量表 {scale.name_zh}")
    db.session.commit()
    return ok(message="量表已停用（历史数据保留）")


@bp.get("/scales/<int:scale_id>/items")
@admin_required
def list_items(scale_id):
    scale = db.session.get(Scale, scale_id)
    if scale is None:
        return error(NOT_FOUND, "量表不存在")
    items = (ScaleItem.query.filter_by(scale_id=scale_id)
             .order_by(ScaleItem.sort_order.asc(), ScaleItem.item_number.asc())
             .all())
    return ok({"scale": scale.to_dict(), "items": [it.to_dict() for it in items]})


def _build_item(scale_id, data, index=0):
    item_number = data.get("item_number")
    item_text = (data.get("item_text") or "").strip()
    options = data.get("options")
    if not item_number or not item_text:
        raise ValueError("题号与题目文本为必填")
    if not isinstance(options, list) or not options:
        raise ValueError(f"第 {item_number} 题未配置选项")
    for opt in options:
        if "text" not in opt or "score" not in opt:
            raise ValueError(f"第 {item_number} 题选项格式错误（需包含 text 与 score）")
    return ScaleItem(
        scale_id=scale_id,
        item_number=item_number,
        item_text=item_text,
        options_json=json.dumps(options, ensure_ascii=False),
        is_reversed=bool(data.get("is_reversed")),
        dimension=data.get("dimension"),
        sort_order=data.get("sort_order", index),
    )


@bp.post("/scales/<int:scale_id>/items")
@admin_required
def create_items(scale_id):
    scale = db.session.get(Scale, scale_id)
    if scale is None:
        return error(NOT_FOUND, "量表不存在")
    data = request.get_json(silent=True) or {}
    try:
        if "items" in data and isinstance(data["items"], list):
            items = [_build_item(scale_id, it, i)
                     for i, it in enumerate(data["items"])]
        else:
            items = [_build_item(scale_id, data, 0)]
    except ValueError as e:
        return error(VALIDATION_ERROR, str(e))

    for it in items:
        exists = (ScaleItem.query.filter_by(scale_id=scale_id,
                                            item_number=it.item_number).first())
        if exists:
            return error(5003, f"第 {it.item_number} 题已存在，请使用编辑操作")
        db.session.add(it)

    db.session.flush()
    _audit("scale_item_create", "scale", scale_id, f"为 {scale.name_zh} 新增 {len(items)} 个条目")
    db.session.commit()
    return ok({"created": len(items)})


@bp.put("/scales/<int:scale_id>/items/<int:item_id>")
@admin_required
def update_item(scale_id, item_id):
    item = (ScaleItem.query.filter_by(id=item_id, scale_id=scale_id).first())
    if item is None:
        return error(NOT_FOUND, "条目不存在")
    data = request.get_json(silent=True) or {}
    if "item_text" in data:
        item.item_text = data["item_text"]
    if "options" in data:
        if not isinstance(data["options"], list) or not data["options"]:
            return error(VALIDATION_ERROR, "选项列表不能为空")
        item.options_json = json.dumps(data["options"], ensure_ascii=False)
    for field in ("item_number", "is_reversed", "dimension", "sort_order"):
        if field in data:
            setattr(item, field, data[field])
    db.session.commit()
    return ok(item.to_dict())


@bp.delete("/scales/<int:scale_id>/items/<int:item_id>")
@admin_required
def delete_item(scale_id, item_id):
    item = (ScaleItem.query.filter_by(id=item_id, scale_id=scale_id).first())
    if item is None:
        return error(NOT_FOUND, "条目不存在")
    db.session.delete(item)
    db.session.commit()
    return ok(message="条目已删除")


# ===================== 常模管理（文档 5.3） =====================

def _deactivate_conflicting(scale_id, dimension, population_group, keep_id=None):
    """同分组已有启用常模时自动停用旧记录（版本管理）。"""
    q = (Norm.query.filter_by(scale_id=scale_id, dimension=dimension,
                              population_group=population_group, status="active"))
    if keep_id:
        q = q.filter(Norm.id != keep_id)
    for old in q.all():
        old.status = "inactive"


@bp.get("/norms")
@admin_required
def list_norms():
    page, size = _pagination()
    scale_id = request.args.get("scale_id", type=int)
    query = Norm.query
    if scale_id:
        query = query.filter_by(scale_id=scale_id)
    total = query.count()
    items = (query.order_by(Norm.id.desc())
             .offset((page - 1) * size).limit(size).all())
    return ok({"total": total, "page": page, "size": size,
               "items": [n.to_dict() for n in items]})


@bp.post("/norms")
@admin_required
def create_norm():
    data = request.get_json(silent=True) or {}
    scale_id = data.get("scale_id")
    if not scale_id or db.session.get(Scale, scale_id) is None:
        return error(VALIDATION_ERROR, "所属量表无效")

    population_group = data.get("population_group") or "全人群"
    _deactivate_conflicting(scale_id, data.get("dimension", "total"),
                            population_group)

    norm = Norm(
        scale_id=scale_id,
        dimension=data.get("dimension", "total"),
        population_group=population_group,
        sample_size=data.get("sample_size"),
        source=data.get("source"),
        mean=data.get("mean"),
        std_dev=data.get("std_dev"),
        percentiles_json=json.dumps(data.get("percentiles", {}), ensure_ascii=False),
        thresholds_json=json.dumps(data.get("thresholds", {}), ensure_ascii=False),
        status="active",
    )
    db.session.add(norm)
    db.session.flush()
    _audit("norm_create", "norm", norm.id, "新增常模")
    db.session.commit()
    return ok(norm.to_dict())


@bp.put("/norms/<int:norm_id>")
@admin_required
def update_norm(norm_id):
    norm = db.session.get(Norm, norm_id)
    if norm is None:
        return error(NOT_FOUND, "常模不存在")
    data = request.get_json(silent=True) or {}
    for field in ("scale_id", "dimension", "population_group", "sample_size",
                  "source", "mean", "std_dev", "status"):
        if field in data:
            setattr(norm, field, data[field])
    if "percentiles" in data:
        norm.percentiles_json = json.dumps(data["percentiles"], ensure_ascii=False)
    if "thresholds" in data:
        norm.thresholds_json = json.dumps(data["thresholds"], ensure_ascii=False)
    if norm.status == "active":
        _deactivate_conflicting(norm.scale_id, norm.dimension,
                                norm.population_group or "全人群", keep_id=norm.id)
    db.session.commit()
    return ok(norm.to_dict())


@bp.post("/norms/import")
@admin_required
def import_norms():
    """CSV 批量导入（文档 5.3）。表头：
    scale_id,dimension,population_group,sample_size,source,mean,std_dev,
    percentiles_json,thresholds_json
    """
    data = request.get_json(silent=True) or {}
    csv_text = data.get("csv") or ""
    if not csv_text:
        return error(VALIDATION_ERROR, "请提供 CSV 文本内容")

    reader = csv.DictReader(io.StringIO(csv_text))
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        try:
            scale_id = int(row["scale_id"])
            if db.session.get(Scale, scale_id) is None:
                raise ValueError("量表不存在")
            population_group = row.get("population_group") or "全人群"
            dimension = row.get("dimension") or "total"
            _deactivate_conflicting(scale_id, dimension, population_group)
            norm = Norm(
                scale_id=scale_id, dimension=dimension,
                population_group=population_group,
                sample_size=int(row["sample_size"]) if row.get("sample_size") else None,
                source=row.get("source"),
                mean=float(row["mean"]) if row.get("mean") else None,
                std_dev=float(row["std_dev"]) if row.get("std_dev") else None,
                percentiles_json=row.get("percentiles_json") or "{}",
                thresholds_json=row.get("thresholds_json") or "{}",
                status="active",
            )
            db.session.add(norm)
            created += 1
        except (KeyError, ValueError) as e:
            skipped += 1
            errors.append(f"第 {i} 行：{e}")

    db.session.flush()
    _audit("norm_import", "norm", None, f"批量导入常模：成功 {created} 条，跳过 {skipped} 条")
    db.session.commit()
    return ok({"created": created, "skipped": skipped, "errors": errors[:20]})


# ===================== 分科规则（文档 5.4） =====================

@bp.get("/rules")
@admin_required
def list_rules():
    rules = (ReferralRule.query
             .order_by(ReferralRule.priority.asc(), ReferralRule.id.asc())
             .all())
    return ok({"items": [r.to_dict() for r in rules]})


def _validate_referral_rule(data):
    name = (data.get("name") or "").strip()
    condition_json = data.get("condition_json")
    doctor_label = (data.get("output_label_doctor") or "").strip()
    if not name or not doctor_label:
        raise ValueError("规则名称与医生版标签为必填")
    try:
        conditions = json.loads(condition_json) if isinstance(condition_json, str) \
            else condition_json
    except ValueError:
        raise ValueError("触发条件不是合法的 JSON")
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("触发条件不能为空")
    for cond in conditions:
        if not cond.get("scale_id") or not cond.get("dimension") \
                or not cond.get("op") or "value" not in cond:
            raise ValueError("条件子句需包含 scale_id/dimension/op/value")
    return name, json.dumps(conditions, ensure_ascii=False), doctor_label


@bp.post("/rules")
@admin_required
def create_rule():
    data = request.get_json(silent=True) or {}
    try:
        name, condition_json, doctor_label = _validate_referral_rule(data)
    except ValueError as e:
        return error(VALIDATION_ERROR, str(e))

    hits = contains_disallowed(doctor_label + (data.get("output_label_parent") or ""))
    if hits:
        return error(VALIDATION_ERROR, f"标签文本包含禁用表述：{hits}，请使用客观状态描述")

    rule = ReferralRule(
        name=name, condition_json=condition_json,
        priority=data.get("priority", 100),
        output_label_doctor=doctor_label,
        output_label_parent=data.get("output_label_parent") or doctor_label,
        output_style=data.get("output_style", "info"),
        output_tags=data.get("output_tags"),
        status=data.get("status", "active"),
    )
    db.session.add(rule)
    db.session.flush()
    _audit("rule_create", "referral_rule", rule.id, f"新增分科规则 {name}")
    db.session.commit()
    return ok(rule.to_dict())


@bp.put("/rules/<int:rule_id>")
@admin_required
def update_rule(rule_id):
    rule = db.session.get(ReferralRule, rule_id)
    if rule is None:
        return error(NOT_FOUND, "规则不存在")
    data = request.get_json(silent=True) or {}

    # 部分更新：未提供的字段沿用原值（如仅切换 status）
    merged = {
        "name": data.get("name", rule.name),
        "condition_json": data.get("condition_json", rule.condition_json),
        "output_label_doctor": data.get("output_label_doctor",
                                        rule.output_label_doctor),
        "output_label_parent": data.get("output_label_parent",
                                        rule.output_label_parent),
    }
    try:
        name, condition_json, doctor_label = _validate_referral_rule(merged)
    except ValueError as e:
        return error(VALIDATION_ERROR, str(e))
    hits = contains_disallowed(doctor_label + (merged["output_label_parent"] or ""))
    if hits:
        return error(VALIDATION_ERROR, f"标签文本包含禁用表述：{hits}")

    rule.name = name
    rule.condition_json = condition_json
    rule.output_label_doctor = doctor_label
    rule.output_label_parent = merged["output_label_parent"] or doctor_label
    for field in ("priority", "output_style", "output_tags", "status"):
        if field in data:
            setattr(rule, field, data[field])
    db.session.commit()
    return ok(rule.to_dict())


@bp.post("/rules/test")
@admin_required
def test_rules():
    """规则测试（文档 5.4）：输入模拟分数，查看哪些规则会触发。"""
    data = request.get_json(silent=True) or {}
    scores = data.get("scores") or {}
    # {scale_id: {"total": 15, "dimension_scores": {"焦虑": 8}}}
    scale_scores = {}
    for sid, val in scores.items():
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            continue
        dims = {k: {"score": v} for k, v in (val.get("dimension_scores") or {}).items()}
        scale_scores[sid] = {"total_score": val.get("total", 0),
                             "dimension_scores": dims}
    labels = evaluate_referral_rules(scale_scores)
    return ok({"triggered": len(labels), "labels": labels})


# ===================== 推送规则（文档 6.1） =====================

@bp.get("/push-rules")
@admin_required
def list_push_rules():
    rules = (PushRule.query
             .order_by(PushRule.priority.asc(), PushRule.id.asc()).all())
    return ok({"items": [r.to_dict() for r in rules]})


@bp.post("/push-rules")
@admin_required
def create_push_rule():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    condition_json = data.get("condition_json")
    package_id = data.get("package_id")
    if not name or not condition_json or not package_id:
        return error(VALIDATION_ERROR, "规则名称、触发条件、组合包均为必填")
    try:
        json.loads(condition_json)
    except ValueError:
        return error(VALIDATION_ERROR, "触发条件不是合法的 JSON")

    rule = PushRule(name=name, condition_json=condition_json,
                    package_id=package_id, priority=data.get("priority", 100),
                    status=data.get("status", "active"))
    db.session.add(rule)
    db.session.commit()
    return ok(rule.to_dict())


@bp.put("/push-rules/<int:rule_id>")
@admin_required
def update_push_rule(rule_id):
    rule = db.session.get(PushRule, rule_id)
    if rule is None:
        return error(NOT_FOUND, "规则不存在")
    data = request.get_json(silent=True) or {}
    for field in ("name", "condition_json", "package_id", "priority", "status"):
        if field in data:
            setattr(rule, field, data[field])
    db.session.commit()
    return ok(rule.to_dict())


# ===================== 医生账号管理（文档 5.5） =====================

@bp.get("/users")
@admin_required
def list_users():
    page, size = _pagination()
    query = User.query
    total = query.count()
    items = (query.order_by(User.id.asc())
             .offset((page - 1) * size).limit(size).all())
    return ok({"total": total, "page": page, "size": size,
               "items": [u.to_dict() for u in items]})


@bp.post("/users")
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("initial_password") or ""
    role = data.get("role", "doctor")

    if not validate_username(username):
        return error(VALIDATION_ERROR, "用户名需为 3-50 位字母、数字、下划线或短横线")
    if User.query.filter_by(username=username).first():
        return error(5003, "用户名已存在")
    if role not in ("doctor", "parent"):
        return error(VALIDATION_ERROR, "角色仅支持 doctor 或 parent")
    if not validate_password_strength(password):
        return error(VALIDATION_ERROR, "初始密码长度不少于 8 位且包含字母和数字")

    user = User(username=username,
                password_hash=generate_password_hash(password),
                display_name=data.get("display_name"),
                role=role, must_change_password=True)
    db.session.add(user)
    db.session.flush()
    _audit("user_create", "user", user.id, f"创建账号 {username}")
    db.session.commit()
    return ok(user.to_dict(), "账号已创建（初始密码仅本次显示，请安全告知使用者）")


@bp.put("/users/<int:user_id>")
@admin_required
def update_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return error(NOT_FOUND, "账号不存在")
    data = request.get_json(silent=True) or {}
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "role" in data:
        if data["role"] not in ("doctor", "parent"):
            return error(VALIDATION_ERROR, "角色仅支持 doctor 或 parent")
        user.role = data["role"]
    if "status" in data:
        if data["status"] not in ("active", "disabled"):
            return error(VALIDATION_ERROR, "状态仅支持 active 或 disabled")
        if user.is_admin:
            return error(VALIDATION_ERROR, "不能停用管理员账号")
        user.status = data["status"]
    db.session.commit()
    return ok(user.to_dict())


@bp.post("/users/<int:user_id>/reset-password")
@admin_required
def reset_password(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return error(NOT_FOUND, "账号不存在")
    if user.is_admin:
        return error(VALIDATION_ERROR, "管理员密码请通过系统运维方式重置")

    alphabet = string.ascii_letters + string.digits
    new_password = "".join(secrets.choice(alphabet) for _ in range(12))
    user.password_hash = generate_password_hash(new_password)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    _audit("user_reset_password", "user", user.id, f"重置账号 {user.username} 密码")
    return ok({"new_password": new_password},
              "密码已重置（仅本次显示，用户下次登录需修改）")


# ===================== 系统配置（文档 5.6） =====================

@bp.get("/configs")
@admin_required
def list_configs():
    rows = SystemConfig.query.order_by(SystemConfig.key.asc()).all()
    return ok({"items": [c.to_dict() for c in rows]})


@bp.put("/configs")
@admin_required
def update_configs():
    data = request.get_json(silent=True) or {}
    configs = data.get("configs") or []
    if not isinstance(configs, list):
        return error(VALIDATION_ERROR, "configs 需为数组")

    updated = []
    for item in configs:
        key = item.get("key")
        if not key:
            continue
        try:
            value = json.loads(item.get("value")) if isinstance(item.get("value"), str) \
                else item.get("value")
        except ValueError:
            value = item.get("value")
        set_config(key, value,
                   value_type=item.get("value_type"),
                   description=item.get("description"))
        updated.append(key)

    _audit("config_update", "config", None, f"更新配置项：{', '.join(updated)}")
    return ok({"updated": updated}, "配置已更新并立即生效")


# ===================== 操作日志（文档 7.4） =====================

@bp.get("/logs")
@admin_required
def list_logs():
    page, size = _pagination()
    action = request.args.get("action")
    query = AuditLog.query
    if action:
        query = query.filter_by(action=action)
    total = query.count()
    items = (query.order_by(AuditLog.id.desc())
             .offset((page - 1) * size).limit(size).all())
    return ok({"total": total, "page": page, "size": size,
               "items": [l.to_dict() for l in items]})
