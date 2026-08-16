"""冒烟测试脚本：对运行中的服务执行完整业务链路（urllib，无第三方依赖）。

用法：python scripts/smoke_flow.py [base_url]
覆盖：管理员改密→创建医生→医生登录→生成邀请码→患者全流程→报告→导出→撤回。
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS = []


def call(method, path, body=None, token=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload
            return resp.status, json.loads(payload.decode())
    except urllib.error.HTTPError as e:
        if raw:
            return e.code, e.read()
        return e.code, json.loads(e.read().decode())


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    PASS.append(cond)
    print(f"[{status}] {name} {detail}")


# 1. 管理员登录 → 修改初始密码
code, r = call("POST", "/api/v1/auth/login",
               {"username": "admin", "password": "Admin@1234"})
check("管理员登录", r["code"] == 0)
admin_token = r["data"]["token"]

code, r = call("POST", "/api/v1/auth/change-password",
               {"old_password": "Admin@1234", "new_password": "Admin@2026New"},
               token=admin_token)
check("管理员修改初始密码", r["code"] == 0, r["message"])

code, r = call("POST", "/api/v1/auth/login",
               {"username": "admin", "password": "Admin@2026New"})
check("管理员新密码登录", r["code"] == 0)
admin_token = r["data"]["token"]

# 2. 管理员创建医生账号
code, r = call("POST", "/api/v1/admin/users",
               {"username": "drwang", "initial_password": "Doctor@1234",
                "display_name": "王医生", "role": "doctor"}, token=admin_token)
check("创建医生账号", r["code"] == 0, r["message"])

# 3. 医生登录（首次登录需改密）
code, r = call("POST", "/api/v1/auth/login",
               {"username": "drwang", "password": "Doctor@1234"})
check("医生登录", r["code"] == 0)
doctor_token = r["data"]["token"]

code, r = call("GET", "/api/v1/doctor/invite-codes", token=doctor_token)
check("未改密被拦截", r["code"] == 4007, r["message"])

code, r = call("POST", "/api/v1/auth/change-password",
               {"old_password": "Doctor@1234", "new_password": "Doctor@5678"},
               token=doctor_token)
check("医生修改初始密码", r["code"] == 0)

code, r = call("POST", "/api/v1/auth/login",
               {"username": "drwang", "password": "Doctor@5678"})
doctor_token = r["data"]["token"]

# 4. 医生生成邀请码
code, r = call("POST", "/api/v1/doctor/invite-codes",
               {"remark": "门诊-小王"}, token=doctor_token)
check("生成邀请码", r["code"] == 0 and len(r["data"]["code"]) == 8)
invite_code = r["data"]["code"]

# 5. 患者流程
code, r = call("POST", "/api/v1/patient/verify-code", {"code": invite_code})
check("患者验证邀请码", r["code"] == 0 and r["data"]["valid"])

code, r = call("POST", "/api/v1/patient/consent",
               {"code": invite_code, "consent": True})
check("提交知情同意", r["code"] == 0)
session_id = r["data"]["session_id"]

code, r = call("POST", "/api/v1/patient/phq4-submit",
               {"session_id": session_id, "answers": [3, 2, 0, 0],
                "sleep_flag": False, "stress_flag": False})
check("快筛提交→推送焦虑深度包", r["code"] == 0
      and r["data"]["package"]["name"] == "焦虑深度包")
gad7 = r["data"]["package"]["scales"][0]["scale_id"]
gad7_items = r["data"]["package"]["scales"][0]["item_count"]

# 逐题作答（焦虑包：GAD-7 + SAS + HADS；作答值从量表配置动态获取，保证合法）
answered = 0
for scale_info in r["data"]["package"]["scales"]:
    sid = scale_info["scale_id"]
    n = scale_info["item_count"]
    _, items_resp = call("GET", f"/api/v1/admin/scales/{sid}/items", token=admin_token)
    items = items_resp["data"]["items"]
    for item in items:
        first_option = item["options"][0]["score"]
        code, r2 = call("POST", "/api/v1/patient/response",
                        {"session_id": session_id, "scale_id": sid,
                         "item_number": item["item_number"], "score": first_option})
        assert r2["code"] == 0, r2
        answered += 1
check("逐题作答暂存", answered == 7 + 20 + 14, f"共 {answered} 题")

code, r = call("POST", "/api/v1/patient/submit", {"session_id": session_id})
check("提交测评", r["code"] == 0 and r["data"]["completed"])

code, r = call("GET", f"/api/v1/patient/result/{session_id}")
check("患者结果页（无分数泄露）", r["code"] == 0
      and r["data"]["status"] == "completed"
      and "总分" not in json.dumps(r["data"], ensure_ascii=False))

# 6. 医生查看报告与导出
code, r = call("GET", f"/api/v1/doctor/reports/{session_id}", token=doctor_token)
check("医生查看报告", r["code"] == 0)
report = r["data"]
check("报告含逐量表数据", len(report["scales"]) == 3
      and report["scales"][0]["score"]["max_score"] == 21)

code, raw = call("GET", f"/api/v1/doctor/reports/{session_id}/export/excel",
                 token=doctor_token, raw=True)
check("Excel 导出", code == 200 and raw[:2] == b"PK")

code, raw = call("GET", f"/api/v1/doctor/reports/{session_id}/export/pdf",
                 token=doctor_token, raw=True)
check("PDF 导出", code == 200 and raw[:4] == b"%PDF")

code, r = call("GET", "/api/v1/doctor/invite-codes", token=doctor_token)
check("邀请码状态已阅", r["data"]["items"][0]["status"] == "viewed")

# 7. 管理端抽查
code, r = call("GET", "/api/v1/admin/scales?size=100", token=admin_token)
check("管理端量表列表", r["code"] == 0 and r["data"]["total"] == 11)

code, r = call("GET", "/api/v1/admin/rules", token=admin_token)
check("管理端分科规则列表", r["code"] == 0 and len(r["data"]["items"]) == 10)

code, r = call("POST", "/api/v1/admin/rules/test",
               {"scores": {"3": {"total": 16, "dimension_scores": {}}}},
               token=admin_token)
check("规则测试接口", r["code"] == 0 and r["data"]["triggered"] >= 1)

code, r = call("GET", "/api/v1/admin/logs", token=admin_token)
check("操作日志查询", r["code"] == 0 and r["data"]["total"] >= 3)

# 8. 撤回
code, r = call("POST", f"/api/v1/patient/revoke/{session_id}",
               {"confirm_text": "确认撤回"})
check("患者撤回", r["code"] == 0, r["message"])

code, r = call("POST", "/api/v1/patient/revoke/" + str(session_id),
               {"confirm_text": "确认撤回", "invite_code": invite_code})
check("重复撤回被拒绝", r["code"] == 1202)

print("\n" + "=" * 40)
print(f"冒烟结果：{sum(PASS)}/{len(PASS)} 通过")
sys.exit(0 if all(PASS) else 1)
