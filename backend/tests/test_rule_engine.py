"""分科规则引擎与禁用词过滤测试（文档 6.4 / 10.1 / 10.2）。"""
import json

from app.extensions import db
from app.models import ReferralRule, Scale
from app.services.rule_engine import evaluate_referral_rules
from app.utils.sanitize import sanitize_output


def _seed(app):
    with app.app_context():
        scale = Scale(name_zh="广泛性焦虑障碍量表", abbreviation="GAD-7", status="active")
        db.session.add(scale)
        db.session.flush()
        db.session.add(ReferralRule(
            name="GAD-7 显著偏高", priority=10,
            condition_json=json.dumps(
                [{"scale_id": scale.id, "dimension": "total", "op": "gte", "value": 15}]),
            output_label_doctor="焦虑水平显著偏高，建议进一步评估",
            output_label_parent="孩子的焦虑自评得分显著偏高，建议与专业人士沟通评估。",
            output_style="alert", status="active"))
        db.session.add(ReferralRule(
            name="GAD-7 中度", priority=20,
            condition_json=json.dumps(
                [{"scale_id": scale.id, "dimension": "total", "op": "between",
                  "value": [10, 14]}]),
            output_label_doctor="焦虑水平中度偏高",
            output_label_parent="孩子的焦虑自评得分中等偏高",
            output_style="warning", status="active"))
        db.session.commit()
        return scale.id


def test_referral_matching(app):
    scale_id = _seed(app)
    with app.app_context():
        labels = evaluate_referral_rules(
            {scale_id: {"total_score": 16, "dimension_scores": {}}},
            viewer_role="doctor")
        assert len(labels) == 1
        assert "显著偏高" in labels[0]["label_doctor"]
        assert labels[0]["style"] == "alert"


def test_between_and_role_switch(app):
    scale_id = _seed(app)
    with app.app_context():
        labels = evaluate_referral_rules(
            {scale_id: {"total_score": 12, "dimension_scores": {}}},
            viewer_role="parent")
        assert len(labels) == 1
        assert "孩子" in labels[0]["label"]


def test_no_match(app):
    scale_id = _seed(app)
    with app.app_context():
        labels = evaluate_referral_rules(
            {scale_id: {"total_score": 3, "dimension_scores": {}}})
        assert labels == []


def test_sanitize_output():
    safe, warned = sanitize_output("你有抑郁倾向，建议进行治疗。")
    assert warned is True
    assert "抑郁倾向" not in safe
    assert "情绪状态呈现出一些需要关注的特征" in safe
    assert "治疗" not in safe


def test_sanitize_clean_text():
    safe, warned = sanitize_output("您近期的情绪状态整体平稳，请继续保持良好作息。")
    assert warned is False
    assert "平稳" in safe
