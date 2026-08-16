"""端到端 API 流程测试：患者端完整闭环 + 医生端报告 + 24小时撤回。

覆盖（文档第三章/第四章）：
验证邀请码 → 知情同意 → PHQ-4 快筛 → 深度量表逐题作答 → 提交 →
患者结果页（无分数）→ 医生报告 → 数据撤回（物理删除）。
"""
import json

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import (AssessmentSession, InviteCode, PushRule, Scale,
                        ScaleItem, ScalePackage, User)

OPT_0_3 = [{"text": "完全没有", "score": 0}, {"text": "有几天", "score": 1},
           {"text": "一半以上天数", "score": 2}, {"text": "几乎每天", "score": 3}]


def _seed_flow(app):
    """最小可用数据：管理员、医生、PHQ-4、GAD-7、焦虑深度包、推送规则。"""
    with app.app_context():
        admin = User(username="admin", password_hash=generate_password_hash("Admin@1234"),
                     role="admin", must_change_password=False)
        doctor = User(username="drzhang",
                      password_hash=generate_password_hash("Doctor@1234"),
                      role="doctor", display_name="张医生", must_change_password=False)
        db.session.add_all([admin, doctor])
        db.session.flush()

        phq4 = Scale(name_zh="患者健康问卷4题版", abbreviation="PHQ-4", status="active")
        gad7 = Scale(name_zh="广泛性焦虑障碍量表", abbreviation="GAD-7", status="active")
        db.session.add_all([phq4, gad7])
        db.session.flush()

        phq4_items = [(1, "感到紧张、焦虑或不安", "焦虑"),
                      (2, "无法停止或控制担忧", "焦虑"),
                      (3, "对事情缺乏兴趣或乐趣", "抑郁"),
                      (4, "感到情绪低落、沮丧或绝望", "抑郁")]
        for num, text, dim in phq4_items:
            db.session.add(ScaleItem(scale_id=phq4.id, item_number=num, item_text=text,
                                     options_json=json.dumps(OPT_0_3),
                                     dimension=dim, sort_order=num))
        for num in range(1, 8):
            db.session.add(ScaleItem(scale_id=gad7.id, item_number=num,
                                     item_text=f"GAD-7 题目{num}",
                                     options_json=json.dumps(OPT_0_3),
                                     dimension="焦虑", sort_order=num))

        pkg = ScalePackage(name="焦虑深度包", scale_ids_json=json.dumps(
            [{"scale_id": gad7.id, "order": 1}]), status="active")
        db.session.add(pkg)
        db.session.flush()

        db.session.add(PushRule(
            name="焦虑分支", priority=10,
            condition_json=json.dumps([
                {"source": "phq4", "dimension": "anxiety", "op": "gte", "value": 4},
                {"source": "phq4", "dimension": "depression", "op": "lt", "value": 3}]),
            package_id=pkg.id, status="active"))
        db.session.commit()
        return {"doctor_id": doctor.id}


def test_full_patient_doctor_flow(app, client):
    _seed_flow(app)

    # 1. 医生登录
    resp = client.post("/api/v1/auth/login",
                       json={"username": "drzhang", "password": "Doctor@1234"})
    body = resp.get_json()
    assert body["code"] == 0
    token = body["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 生成邀请码
    resp = client.post("/api/v1/doctor/invite-codes", headers=headers,
                       json={"remark": "周三门诊"})
    body = resp.get_json()
    assert body["code"] == 0
    code = body["data"]["code"]
    assert len(code) == 8

    # 3. 患者验证邀请码
    resp = client.post("/api/v1/patient/verify-code", json={"code": code})
    body = resp.get_json()
    assert body["code"] == 0 and body["data"]["valid"] is True

    # 4. 知情同意
    resp = client.post("/api/v1/patient/consent", json={"code": code, "consent": True})
    body = resp.get_json()
    assert body["code"] == 0
    session_id = body["data"]["session_id"]

    # 5. 快筛提交（焦虑分支：焦虑=4，抑郁=0）
    resp = client.post("/api/v1/patient/phq4-submit",
                       json={"session_id": session_id, "answers": [3, 1, 0, 0],
                             "sleep_flag": False, "stress_flag": False})
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["need_deep_assessment"] is True
    gad7_id = body["data"]["package"]["scales"][0]["scale_id"]
    item_count = body["data"]["package"]["scales"][0]["item_count"]
    assert item_count == 7

    # 6. 逐题作答（模拟每题 300ms 自动推进的异步暂存），先答 6 题
    for num in range(1, 7):
        score = 2 if num <= 3 else 1
        resp = client.post("/api/v1/patient/response",
                           json={"session_id": session_id, "scale_id": gad7_id,
                                 "item_number": num, "score": score})
        body = resp.get_json()
        assert body["code"] == 0

    # 7. 未答完时提交应失败
    resp = client.post("/api/v1/patient/submit", json={"session_id": session_id})
    assert resp.get_json()["code"] == 1104

    # 补答最后一题
    client.post("/api/v1/patient/response",
                json={"session_id": session_id, "scale_id": gad7_id,
                      "item_number": 7, "score": 1})

    # 8. 提交完成
    resp = client.post("/api/v1/patient/submit", json={"session_id": session_id})
    body = resp.get_json()
    assert body["code"] == 0 and body["data"]["completed"] is True

    # 9. 患者结果页：不得出现任何分数
    resp = client.get(f"/api/v1/patient/result/{session_id}")
    body = resp.get_json()
    assert body["code"] == 0
    data = body["data"]
    assert data["status"] == "completed"
    assert data["revoke_available"] is True
    blob = json.dumps(data, ensure_ascii=False)
    # "分数"/"诊断"会出现在"不向您展示分数""不代表临床诊断"等法定告知文案中（文档 3.6 原文），属设计内容
    for sensitive in ("总分", "得分", "GAD-7", "焦虑症", "抑郁倾向"):
        assert sensitive not in blob, f"患者结果页不应出现敏感词: {sensitive}"

    # 10. 医生查看报告
    resp = client.get(f"/api/v1/doctor/reports/{session_id}", headers=headers)
    body = resp.get_json()
    assert body["code"] == 0
    report = body["data"]
    assert report["overview"]["invite_code"] == code
    assert report["scales"][0]["score"]["total_score"] == 3 * 2 + 4 * 1  # 10
    assert report["scales"][0]["score"]["max_score"] == 21

    # 11. 邀请码状态已阅
    invite = db.session.get(InviteCode, report["invite_code_id"])
    assert invite.status == "viewed"

    # 12. 数据导出（Excel）
    resp = client.get(f"/api/v1/doctor/reports/{session_id}/export/excel",
                      headers=headers)
    assert resp.status_code == 200
    assert resp.data[:2] == b"PK"

    # 13. 权限校验：他人不可见
    with app.app_context():
        other = User(username="drli",
                     password_hash=generate_password_hash("Doctor@1234"),
                     role="doctor", display_name="李医生", must_change_password=False)
        db.session.add(other)
        db.session.commit()
    resp = client.post("/api/v1/auth/login",
                       json={"username": "drli", "password": "Doctor@1234"})
    other_headers = {"Authorization": f"Bearer {resp.get_json()['data']['token']}"}
    resp = client.get(f"/api/v1/doctor/reports/{session_id}", headers=other_headers)
    assert resp.get_json()["code"] == 4003  # PERMISSION_DENIED

    # 14. 患者撤回（错误确认文字 → 拒绝；正确文字 → 成功）
    resp = client.post(f"/api/v1/patient/revoke/{session_id}",
                       json={"confirm_text": "不撤回"})
    assert resp.get_json()["code"] == 1204
    resp = client.post(f"/api/v1/patient/revoke/{session_id}",
                       json={"confirm_text": "确认撤回"})
    assert resp.get_json()["code"] == 0

    # 15. 撤回后数据物理删除
    with app.app_context():
        assert db.session.get(AssessmentSession, session_id) is None
        assert db.session.get(InviteCode, report["invite_code_id"]).status == "revoked"
