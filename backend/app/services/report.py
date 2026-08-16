"""报告生成服务（文档 4.3 / 6.4 / 10.3）。

报告结构：
1. 报告概览（邀请码/备注/完成时间/知情同意/组合包/各量表总分总览表）
2. 逐量表详细报告（简介、逐题作答、维度得分、总分与常模对比、分科参考标签）
3. 综合分科参考（全量表条件组合规则输出）
4. 报告尾部固定信息（免责声明硬编码、生成时间戳、版权）

注意：免责声明为硬编码常量，禁止从配置表读取（文档 10.1 第三层）。
"""
import json
from collections import defaultdict
from datetime import datetime

from ..extensions import db
from ..models import Norm, ReferralRule, Scale, ScaleItem, ScalePackage

from .rule_engine import evaluate_referral_rules, involved_scale_ids
from .scoring import score_scale

# 硬编码免责声明（四层兜底第三层）
REPORT_DISCLAIMER = (
    "本报告基于患者自评量表数据生成，仅反映患者作答期间的主观感受，不代表临床诊断。"
    "量表的任何分数或分科建议仅供专业人士参考，请结合临床面诊进行综合判断。"
)

COPYRIGHT_LINE = "本平台所用量表部分来源于《心理量表自评手册》（198X年版）及其他公开学术资源，非商业用途，仅供学习参考使用。各量表版权归原作者所有。"


def build_report(session, viewer_role="doctor"):
    """构建完整报告字典（JSON 可序列化）。"""
    invite = session.invite_code
    package = (db.session.get(ScalePackage, session.push_package_id)
               if session.push_package_id else None)

    # 作答数据按量表分组
    responses = list(session.responses.all())
    by_scale = defaultdict(dict)
    for r in responses:
        by_scale[r.scale_id][r.item_number] = r

    # 组合包内量表（含顺序）
    ordered = package.ordered_scales() if package else []

    scales_data = []
    scale_scores = {}
    for scale, _order in ordered:
        raw_map = {num: r.raw_score for num, r in by_scale.get(scale.id, {}).items()}
        if not raw_map:
            continue
        try:
            score = score_scale(scale, raw_map)
        except Exception:
            continue
        scale_scores[scale.id] = score

        items = (ScaleItem.query
                 .filter_by(scale_id=scale.id)
                 .order_by(ScaleItem.sort_order.asc(), ScaleItem.item_number.asc())
                 .all())
        item_rows = []
        for it in items:
            resp = by_scale.get(scale.id, {}).get(it.item_number)
            try:
                options = json.loads(it.options_json or "[]")
            except ValueError:
                options = []
            chosen = None
            for opt in options:
                if resp and opt.get("score") == resp.raw_score:
                    chosen = opt.get("text")
            item_rows.append({
                "item_number": it.item_number,
                "item_text": it.item_text,
                "chosen_text": chosen,
                "raw_score": resp.raw_score if resp else None,
                "final_score": resp.final_score if resp else None,
                "reversed": it.is_reversed,
                "dimension": it.dimension,
                "options": options,
            })

        norm = find_norm(scale.id, "total")
        scales_data.append({
            "scale_id": scale.id,
            "name_zh": scale.name_zh,
            "name_en": scale.name_en,
            "abbreviation": scale.abbreviation,
            "source": scale.source,
            "description": scale.description,
            "estimated_minutes": scale.estimated_minutes,
            "score": {
                "total_score": score["total_score"],
                "max_score": score["max_score"],
                "dimension_scores": score["dimension_scores"],
            },
            "norm": norm,
            "items": item_rows,
        })

    # 分科参考标签
    all_labels = evaluate_referral_rules(scale_scores, viewer_role=viewer_role)
    # 逐量表归属标签：规则条件仅涉及该量表时归入该量表
    per_scale_labels = {scale_id: [] for scale_id in scale_scores}
    for rule in all_labels:
        involved = involved_scale_ids_for(rule["rule_id"])
        if len(involved) == 1:
            sid = next(iter(involved))
            if sid in per_scale_labels:
                per_scale_labels[sid].append(rule)

    # 概览表
    overview = {
        "invite_code": invite.code,
        "remark": invite.remark,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "consent": {
            "given": session.consent_given,
            "at": session.consent_at.isoformat() if session.consent_at else None,
            "ua_hash": session.consent_ua_hash,
        },
        "package_name": package.name if package else None,
        "package_description": package.description if package else None,
        "summary": [
            {
                "scale_id": s["scale_id"],
                "abbreviation": s["abbreviation"],
                "name_zh": s["name_zh"],
                "total_score": s["score"]["total_score"],
                "max_score": s["score"]["max_score"],
            }
            for s in scales_data
        ],
        "phq4": {
            "total": session.phq4_total,
            "anxiety": session.phq4_anxiety,
            "depression": session.phq4_depression,
            "sleep_flag": session.sleep_flag,
            "stress_flag": session.stress_flag,
        } if session.phq4_total is not None else None,
    }

    return {
        "session_id": session.id,
        "invite_code_id": session.invite_code_id,
        "overview": overview,
        "scales": scales_data,
        "per_scale_labels": per_scale_labels,
        "referral_labels": all_labels,
        "generated_at": datetime.utcnow().isoformat(),
        "disclaimer": REPORT_DISCLAIMER,
        "copyright": COPYRIGHT_LINE,
    }


def involved_scale_ids_for(rule_id):
    from ..models import ReferralRule
    rule = db.session.get(ReferralRule, rule_id)
    if rule is None:
        return set()
    return involved_scale_ids(rule)


def find_norm(scale_id, dimension="total"):
    """查找启用常模；暂无则返回 None（报告中显示"暂无适用常模数据"）。"""
    norm = (Norm.query
            .filter_by(scale_id=scale_id, dimension=dimension, status="active")
            .first())
    if norm is None:
        return None
    data = norm.to_dict()
    # 患者分数相对常模位置的文字描述（文档 4.3：使用描述性语言）
    return {
        "population_group": data["population_group"],
        "sample_size": data["sample_size"],
        "source": data["source"],
        "mean": data["mean"],
        "std_dev": data["std_dev"],
        "percentiles": data["percentiles"],
        "thresholds": data["thresholds"],
    }


def norm_position_text(score, norm):
    """生成常模对比描述（描述性语言，避免"异常"等标签化表述）。"""
    if not norm or norm.get("mean") is None:
        return "暂无适用常模数据"
    mean = norm["mean"]
    std = norm["std_dev"]
    if not std:
        return "暂无适用常模数据"
    z = (score - mean) / std
    if z <= -0.5:
        return "低于常见人群平均水平"
    if z <= 0.5:
        return "处于常见人群平均水平范围"
    if z <= 1.0:
        return "处于中等偏高水平"
    if z <= 1.5:
        return "处于偏高水平，值得关注"
    return "处于显著偏高水平，建议优先关注"
