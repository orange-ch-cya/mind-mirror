"""统一响应封装（文档 2.1 API 约定）。

所有接口响应结构：{code, message, data}
- code=0 表示成功；业务错误统一返回 HTTP 200，通过 code 区分（错误码表见 errors.py）。
"""
from flask import jsonify


def ok(data=None, message="ok"):
    return jsonify({"code": 0, "message": message, "data": data}), 200


def error(code, message, data=None, http_status=200):
    return jsonify({"code": code, "message": message, "data": data}), http_status
