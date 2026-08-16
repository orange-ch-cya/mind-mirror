"""计分引擎测试（文档 6.3）。"""
import json

import pytest

from app.extensions import db
from app.models import Scale, ScaleItem
from app.services.scoring import (InvalidAnswerError, MissingAnswerError,
                                  score_scale)

OPT_0_3 = [{"text": "完全没有", "score": 0}, {"text": "有几天", "score": 1},
           {"text": "一半以上天数", "score": 2}, {"text": "几乎每天", "score": 3}]


def _make_scale(app):
    with app.app_context():
        scale = Scale(name_zh="测试量表", abbreviation="TEST", status="active")
        db.session.add(scale)
        db.session.flush()
        db.session.add(ScaleItem(scale_id=scale.id, item_number=1,
                                 item_text="题目一", options_json=json.dumps(OPT_0_3),
                                 dimension="焦虑", sort_order=1))
        db.session.add(ScaleItem(scale_id=scale.id, item_number=2,
                                 item_text="题目二（反向）", options_json=json.dumps(OPT_0_3),
                                 is_reversed=True, dimension="焦虑", sort_order=2))
        db.session.add(ScaleItem(scale_id=scale.id, item_number=3,
                                 item_text="题目三", options_json=json.dumps(OPT_0_3),
                                 dimension="抑郁", sort_order=3))
        db.session.commit()
        return scale.id


def test_basic_and_reverse_scoring(app):
    scale_id = _make_scale(app)
    with app.app_context():
        scale = db.session.get(Scale, scale_id)
        result = score_scale(scale, {1: 2, 2: 1, 3: 0})
        assert result["total_score"] == 2 + (3 - 1 + 0) + 0  # 2+2+0=4
        assert result["max_score"] == 9
        assert result["dimension_scores"]["焦虑"]["score"] == 4
        assert result["dimension_scores"]["抑郁"]["score"] == 0
        items = {i["item_number"]: i for i in result["item_scores"]}
        assert items[2]["final_score"] == 2
        assert items[2]["reversed"] is True


def test_missing_answer_raises(app):
    scale_id = _make_scale(app)
    with app.app_context():
        scale = db.session.get(Scale, scale_id)
        with pytest.raises(MissingAnswerError):
            score_scale(scale, {1: 2})


def test_invalid_answer_raises(app):
    scale_id = _make_scale(app)
    with app.app_context():
        scale = db.session.get(Scale, scale_id)
        with pytest.raises(InvalidAnswerError):
            score_scale(scale, {1: 99, 2: 1, 3: 0})
