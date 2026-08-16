"""推送决策引擎测试（文档 3.4 / 6.1）。"""
import json

from app.extensions import db
from app.models import PushRule, ScalePackage
from app.services.push_engine import decide_package


def _seed(app):
    with app.app_context():
        pkgs = {}
        for name in ("焦虑深度包", "抑郁深度包", "情绪综合包", "睡眠专项包",
                     "压力应激包", "全面筛查包"):
            pkg = ScalePackage(name=name, scale_ids_json="[]", status="active")
            db.session.add(pkg)
            db.session.flush()
            pkgs[name] = pkg.id

        rules = [
            ("焦虑分支", 10, "焦虑深度包", [
                {"source": "phq4", "dimension": "anxiety", "op": "gte", "value": 4},
                {"source": "phq4", "dimension": "depression", "op": "lt", "value": 3}]),
            ("抑郁分支", 10, "抑郁深度包", [
                {"source": "phq4", "dimension": "depression", "op": "gte", "value": 4},
                {"source": "phq4", "dimension": "anxiety", "op": "lt", "value": 3}]),
            ("混合分支", 10, "情绪综合包", [
                {"source": "phq4", "dimension": "anxiety", "op": "gte", "value": 4},
                {"source": "phq4", "dimension": "depression", "op": "gte", "value": 4}]),
            ("睡眠分支", 20, "睡眠专项包", [
                {"source": "phq4", "dimension": "total", "op": "lt", "value": 6},
                {"source": "supplement", "dimension": "sleep", "op": "eq", "value": 1}]),
            ("压力分支", 20, "压力应激包", [
                {"source": "phq4", "dimension": "total", "op": "lt", "value": 6},
                {"source": "supplement", "dimension": "stress", "op": "eq", "value": 1}]),
            ("全面筛查", 30, "全面筛查包", [
                {"source": "phq4", "dimension": "total", "op": "gte", "value": 6}]),
        ]
        for name, priority, pkg_name, conds in rules:
            db.session.add(PushRule(name=name, priority=priority,
                                    condition_json=json.dumps(conds),
                                    package_id=pkgs[pkg_name], status="active"))
        db.session.commit()
        return pkgs


def test_anxiety_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([3, 1, 0, 0])  # 焦虑4 抑郁0
        assert pkg is not None and pkg.id == pkgs["焦虑深度包"]


def test_depression_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([0, 0, 3, 1])  # 焦虑0 抑郁4
        assert pkg.id == pkgs["抑郁深度包"]


def test_mixed_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([2, 2, 2, 2])  # 焦虑4 抑郁4
        assert pkg.id == pkgs["情绪综合包"]


def test_sleep_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([1, 0, 0, 0], sleep_flag=True)
        assert pkg.id == pkgs["睡眠专项包"]


def test_stress_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([1, 1, 0, 0], stress_flag=True)
        assert pkg.id == pkgs["压力应激包"]


def test_full_screening_branch(app):
    pkgs = _seed(app)
    with app.app_context():
        pkg, _ = decide_package([2, 1, 1, 2])  # total=6
        assert pkg.id == pkgs["全面筛查包"]


def test_well_state(app):
    _seed(app)
    with app.app_context():
        pkg, detail = decide_package([1, 0, 0, 0])
        assert pkg is None
        assert detail["fallback"] is True
