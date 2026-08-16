"""通用条件求值引擎（文档 6.1 / 6.4 共享）。

条件子句三种格式，统一解析为上下文 key：
1. 显式 key：      {"key": ("phq4","anxiety"), "op":"gte","value":4}
2. 分科规则：      {"scale_id":3,"dimension":"total","op":"gte","value":15}
                   → key = ("scale", 3, "total")
3. 推送规则：      {"source":"phq4","dimension":"anxiety","op":"gte","value":4}
                   → key = ("phq4","anxiety")

op 取值：gt / gte / lt / lte / eq / ne / between
- 多子句之间为 AND；
- 任一子句数据缺失或类型不符 → 整条规则不匹配（保守策略）。
"""
import json


def evaluate_conditions(condition_json, context):
    try:
        conditions = json.loads(condition_json) if condition_json else []
    except (ValueError, TypeError):
        return False
    if not isinstance(conditions, list):
        return False
    for cond in conditions:
        key = _resolve_key(cond)
        if key not in context:
            return False
        actual = context[key]
        expected = cond.get("value")
        if not _match(cond.get("op", "eq"), actual, expected):
            return False
    return True


def _resolve_key(cond):
    if "key" in cond:
        return tuple(cond["key"]) if isinstance(cond["key"], list) else cond["key"]
    if "scale_id" in cond and "dimension" in cond:
        return ("scale", cond["scale_id"], cond["dimension"])
    if "source" in cond and "dimension" in cond:
        return (cond["source"], cond["dimension"])
    return None


def _match(op, actual, expected):
    try:
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "between":
            lo, hi = expected
            return lo <= actual <= hi
    except (TypeError, ValueError):
        return False
    return False
