"""快筛推送决策引擎（文档 3.4 / 6.1）。

输入：PHQ-4 四题得分、睡眠补充筛查标志、压力补充筛查标志。
输出：命中的组合包（ScalePackage）或 None（状态良好，直接跳转结果页）。

规则全部存储在 push_rules 表（可热更新），本引擎只负责：
1. 构造求值上下文；
2. 按优先级（数字小优先）依次匹配；
3. 无匹配时执行默认分支（总分≤2 → 状态良好；否则 → 全面筛查包）。
"""
import logging

from ..extensions import db
from ..models import PushRule, ScalePackage

logger = logging.getLogger(__name__)


def decide_package(phq4_answers, sleep_flag=False, stress_flag=False):
    """返回 (package, detail)。package 为 None 表示无需深度测评。"""
    anxiety = int(phq4_answers[0]) + int(phq4_answers[1])
    depression = int(phq4_answers[2]) + int(phq4_answers[3])
    total = sum(int(x) for x in phq4_answers)

    context = {
        ("phq4", "anxiety"): anxiety,
        ("phq4", "depression"): depression,
        ("phq4", "total"): total,
        ("supplement", "sleep"): 1 if sleep_flag else 0,
        ("supplement", "stress"): 1 if stress_flag else 0,
    }

    detail = {
        "phq4_anxiety": anxiety,
        "phq4_depression": depression,
        "phq4_total": total,
        "sleep_flag": bool(sleep_flag),
        "stress_flag": bool(stress_flag),
        "matched_rule": None,
        "fallback": False,
    }

    rules = (PushRule.query
             .filter_by(status="active")
             .order_by(PushRule.priority.asc(), PushRule.id.asc())
             .all())
    for rule in rules:
        from .condition_engine import evaluate_conditions
        if evaluate_conditions(rule.condition_json, context):
            pkg = db.session.get(ScalePackage, rule.package_id)
            if pkg and pkg.status == "active":
                detail["matched_rule"] = rule.name
                logger.info("push_engine: rule '%s' matched -> package %s",
                            rule.name, pkg.name)
                return pkg, detail
            # 规则命中的包已停用：继续匹配下一条
            logger.warning("push_engine: rule '%s' matched but package inactive", rule.name)

    # 默认分支：总分 ≤ 2 → 状态良好；否则推送全面筛查包
    if total <= 2:
        detail["fallback"] = True
        detail["matched_rule"] = "default-well"
        return None, detail

    default_pkg = _find_default_package()
    detail["fallback"] = True
    detail["matched_rule"] = "default-screening"
    return default_pkg, detail


def _find_default_package():
    """全面筛查包：按名称查找，找不到返回 None（由调用方降级处理）。"""
    pkg = ScalePackage.query.filter_by(name="全面筛查包", status="active").first()
    if pkg:
        return pkg
    logger.warning("push_engine: 未找到默认全面筛查包")
    return None
