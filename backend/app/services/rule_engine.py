"""分科规则引擎（文档 5.4 / 6.4 / 10.3）。

- 输入：各量表计分结果 {scale_id: {total_score, dimension_scores}}；
- 输出：匹配规则标签列表（医生版/家长版双轨文案，经禁用词过滤）；
- 条件格式：[{"scale_id":3,"dimension":"total","op":"gte","value":15}]，
  dimension 可为 "total" 或量表内部维度名；
- 多条规则可同时触发；按优先级排序，按标签文本 MD5 去重。
"""
import hashlib
import json
import logging

from ..extensions import db
from ..models import ReferralRule

from .condition_engine import evaluate_conditions
from ..utils.sanitize import sanitize_output

logger = logging.getLogger(__name__)


def evaluate_referral_rules(scale_scores, viewer_role="doctor"):
    """scale_scores: {scale_id: {"total_score": int, "dimension_scores": {dim: score}}}"""
    context = {}
    for scale_id, scores in scale_scores.items():
        context[("scale", scale_id, "total")] = scores["total_score"]
        for dim, entry in scores.get("dimension_scores", {}).items():
            context[("scale", scale_id, dim)] = entry["score"] if isinstance(entry, dict) else entry

    rules = (ReferralRule.query
             .filter_by(status="active")
             .order_by(ReferralRule.priority.asc(), ReferralRule.id.asc())
             .all())

    matched = []
    for rule in rules:
        if evaluate_conditions(rule.condition_json, context):
            matched.append(rule)

    # 输出标签
    labels = []
    seen = set()
    for rule in matched:
        doctor_text, w1 = sanitize_output(rule.output_label_doctor)
        parent_text, w2 = sanitize_output(rule.output_label_parent or rule.output_label_doctor)
        if not doctor_text:
            continue
        digest = hashlib.md5(doctor_text.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        labels.append({
            "rule_id": rule.id,
            "rule_name": rule.name,
            "priority": rule.priority,
            "style": rule.output_style or "info",
            "tags": [t.strip() for t in (rule.output_tags or "").split(",") if t.strip()],
            "label_doctor": doctor_text,
            "label_parent": parent_text,
            "label": parent_text if viewer_role == "parent" else doctor_text,
        })
    return labels


def involved_scale_ids(rule):
    """规则条件涉及的量表 ID 集合（用于逐量表标签归属判断）。"""
    try:
        conditions = json.loads(rule.condition_json or "[]")
    except ValueError:
        return set()
    return {c.get("scale_id") for c in conditions if c.get("scale_id")}
