"""患者端前端契约验证：完全模拟 app.js 的调用序列。

覆盖：verify-code → consent → phq4-submit → package-detail → response(option_index)
→ session-answers → submit → result；以及睡眠分支 + 断点续答。
用法：python scripts/smoke_patient_ui.py [base_url]（需使用全新种子数据库）
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS = []


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(body).encode() if body else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def check(name, cond, detail=""):
    PASS.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# ---------- 准备 ----------
_, r = call("POST", "/api/v1/auth/login",
            {"username": "admin", "password": "Admin@1234"})
if r["code"] != 0:
    print("SKIP: 管理员初始密码已变更，请先重置数据库")
    sys.exit(2)
admin_token = r["data"]["token"]

call("POST", "/api/v1/auth/change-password",
     {"old_password": "Admin@1234", "new_password": "Admin@2026New"}, token=admin_token)
_, r = call("POST", "/api/v1/auth/login",
            {"username": "admin", "password": "Admin@2026New"})
admin_token = r["data"]["token"]

_, r = call("POST", "/api/v1/admin/users",
            {"username": "drzhou", "initial_password": "Doctor@1234",
             "display_name": "周医生", "role": "doctor"}, token=admin_token)
if r["code"] != 0:
    print("SKIP: 医生账号已存在，请先重置数据库")
    sys.exit(2)

_, r = call("POST", "/api/v1/auth/login",
            {"username": "drzhou", "password": "Doctor@1234"})
doc_token = r["data"]["token"]
call("POST", "/api/v1/auth/change-password",
     {"old_password": "Doctor@1234", "new_password": "Doctor@5678"}, token=doc_token)
_, r = call("POST", "/api/v1/auth/login",
            {"username": "drzhou", "password": "Doctor@5678"})
doc_token = r["data"]["token"]

# ---------- 流程一：混合分支 + option_index 作答 ----------
_, r = call("POST", "/api/v1/doctor/invite-codes", {"remark": "前端契约"}, token=doc_token)
code = r["data"]["code"]

_, r = call("POST", "/api/v1/patient/verify-code", {"code": code})
check("1. verify-code", r["code"] == 0 and r["data"]["valid"])
sid = r["data"]["session_id"]

_, r = call("POST", "/api/v1/patient/consent", {"code": code, "consent": True})
check("2. consent", r["code"] == 0)
sid = r["data"]["session_id"]

_, r = call("POST", "/api/v1/patient/phq4-submit",
            {"session_id": sid, "answers": [2, 2, 2, 2],
             "sleep_flag": False, "stress_flag": False})
check("3. phq4-submit(混合分支)", r["code"] == 0
      and r["data"]["package"]["name"] == "情绪综合包")

_, r = call("GET", f"/api/v1/patient/package-detail/{sid}")
check("4. package-detail", r["code"] == 0 and len(r["data"]["scales"]) == 4)
blob = json.dumps(r["data"], ensure_ascii=False)
check("4b. package-detail 不含 score 字段", '"score"' not in blob)

answered = 0
for scale in r["data"]["scales"]:
    for item in scale["items"]:
        idx = answered % len(item["options"])
        _, r2 = call("POST", "/api/v1/patient/response",
                     {"session_id": sid, "scale_id": scale["scale_id"],
                      "item_number": item["item_number"], "option_index": idx})
        assert r2["code"] == 0, r2
        answered += 1
check("5. response(option_index) 全量作答", answered == 7 + 9 + 14 + 90,
      f"{answered} 题")

_, r = call("GET", f"/api/v1/patient/session-answers/{sid}")
check("6. session-answers 为选项下标", r["code"] == 0
      and len(r["data"]) == 4 and "score" not in json.dumps(r["data"]))

_, r = call("POST", "/api/v1/patient/submit", {"session_id": sid})
check("7. submit", r["code"] == 0 and r["data"]["completed"])

_, r = call("GET", f"/api/v1/patient/result/{sid}")
check("8. result", r["code"] == 0 and r["data"]["status"] == "completed")

# ---------- 流程二：睡眠分支 + 断点续答 ----------
_, r = call("POST", "/api/v1/doctor/invite-codes", {"remark": "续答"}, token=doc_token)
code2 = r["data"]["code"]
call("POST", "/api/v1/patient/consent", {"code": code2, "consent": True})
_, r = call("POST", "/api/v1/patient/verify-code", {"code": code2})
sid2 = r["data"]["session_id"]
_, r = call("POST", "/api/v1/patient/phq4-submit",
            {"session_id": sid2, "answers": [0, 0, 0, 0],
             "sleep_flag": True, "stress_flag": False})
check("9. 睡眠分支推送", r["data"]["package"]["name"] == "睡眠专项包")

_, r = call("GET", f"/api/v1/patient/package-detail/{sid2}")
psqi = r["data"]["scales"][0]
call("POST", "/api/v1/patient/response",
     {"session_id": sid2, "scale_id": psqi["scale_id"],
      "item_number": 1, "option_index": 0})
_, r = call("GET", f"/api/v1/patient/session-answers/{sid2}")
check("10. 部分作答可恢复",
      r["data"].get(str(psqi["scale_id"]), {}).get("1") == 0)

# ---------- 流程三：状态良好分支（无需深度测评） ----------
_, r = call("POST", "/api/v1/doctor/invite-codes", {"remark": "状态良好"}, token=doc_token)
code3 = r["data"]["code"]
call("POST", "/api/v1/patient/consent", {"code": code3, "consent": True})
_, r = call("POST", "/api/v1/patient/verify-code", {"code": code3})
sid3 = r["data"]["session_id"]
_, r = call("POST", "/api/v1/patient/phq4-submit",
            {"session_id": sid3, "answers": [0, 1, 0, 0],
             "sleep_flag": False, "stress_flag": False})
check("11. 状态良好分支", r["code"] == 0 and r["data"]["need_deep_assessment"] is False)
_, r = call("GET", f"/api/v1/patient/result/{sid3}")
check("12. 状态良好直接出结果页", r["code"] == 0 and r["data"]["status"] == "completed")

# 还原管理员密码（冒烟过程会临时改密，结束时恢复文档约定账号，避免影响正常登录）
import os
import subprocess

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_reset = subprocess.run([sys.executable, "scripts/reset_admin.py"], cwd=_BACKEND,
                        capture_output=True, text=True)
print((_reset.stdout or _reset.stderr).strip() or "[warn] 管理员密码还原失败")

print("\n" + "=" * 40)
print(f"患者端契约验证：{sum(PASS)}/{len(PASS)} 通过")
sys.exit(0 if all(PASS) else 1)
