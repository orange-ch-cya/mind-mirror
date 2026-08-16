"""计分引擎（文档 6.3）。

逻辑：
1. 按量表条目配置逐题取原始分；
2. 反向计分条目：final = max_score - raw + min_score；
3. 累加维度分与总分（默认求和范式，覆盖 95% 量表需求；特殊计分作为代码特例扩展点）。

输出结构化计分结果：
{
  "scale_id": 3, "scale_name": "GAD-7", "abbreviation": "GAD-7",
  "total_score": 12, "max_score": 21,
  "dimension_scores": {"焦虑": {"score": 12, "max": 21}},
  "item_scores": [{"item_number":1,"raw_score":2,"final_score":2,"reversed":false}, ...]
}
"""
import json
import logging

from ..extensions import db
from ..models import Scale, ScaleItem

logger = logging.getLogger(__name__)


class MissingAnswerError(Exception):
    pass


class InvalidAnswerError(Exception):
    pass


def score_scale(scale, raw_map):
    """raw_map: {item_number: raw_score}（缺失或非法值直接抛异常，保证数据质量）。"""
    items = (ScaleItem.query
             .filter_by(scale_id=scale.id)
             .order_by(ScaleItem.sort_order.asc(), ScaleItem.item_number.asc())
             .all())

    dimension_scores = {}
    total_score = 0
    max_score = 0
    item_scores = []

    for it in items:
        if it.item_number not in raw_map:
            raise MissingAnswerError(
                f"scale={scale.abbreviation or scale.id} 缺少年第 {it.item_number} 题作答")

        raw = raw_map[it.item_number]
        try:
            options = json.loads(it.options_json or "[]")
        except ValueError:
            options = []
        option_scores = [o.get("score") for o in options if "score" in o]
        if raw not in option_scores:
            raise InvalidAnswerError(
                f"scale={scale.abbreviation or scale.id} 第 {it.item_number} 题作答值非法: {raw}")

        final = raw
        if it.is_reversed:
            final = max(option_scores) - raw + min(option_scores)

        dim = it.dimension or "total"
        dim_entry = dimension_scores.setdefault(
            dim, {"score": 0, "max": 0})
        dim_entry["score"] += final
        dim_entry["max"] += max(option_scores)

        total_score += final
        max_score += max(option_scores)
        item_scores.append({
            "item_number": it.item_number,
            "item_text": it.item_text,
            "raw_score": raw,
            "final_score": final,
            "reversed": it.is_reversed,
            "dimension": dim,
        })

    return {
        "scale_id": scale.id,
        "scale_name": scale.name_zh,
        "abbreviation": scale.abbreviation,
        "total_score": total_score,
        "max_score": max_score,
        "dimension_scores": dimension_scores,
        "item_scores": item_scores,
    }


def score_session_scales(session):
    """按会话作答记录为组合包内所有量表计分，返回 {scale_id: score_result}。"""
    from ..models import AssessmentSession

    results = {}
    responses = list(session.responses.all())
    by_scale = {}
    for r in responses:
        by_scale.setdefault(r.scale_id, {})[r.item_number] = r

    package = None
    if session.push_package_id:
        from ..models import ScalePackage
        package = db.session.get(ScalePackage, session.push_package_id)

    scale_ids = list(by_scale.keys())
    if package:
        scale_ids = [s.id for s, _ in package.ordered_scales()]

    for scale_id in scale_ids:
        scale = db.session.get(Scale, scale_id)
        if scale is None:
            continue
        raw_map = {num: r.raw_score for num, r in by_scale.get(scale_id, {}).items()}
        if not raw_map:
            continue
        try:
            results[scale_id] = score_scale(scale, raw_map)
        except (MissingAnswerError, InvalidAnswerError) as e:
            logger.warning("scoring: %s", e)
            continue
    return results
