"""认证接口（文档 4.1 / 13.3）。

- 登录：连续 5 次失败锁定 30 分钟；
- JWT：24 小时有效期；
- 首次登录强制修改初始密码（must_change_password 拦截，见 middleware/auth.py）。
"""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..middleware.auth import create_token, token_required
from ..models import STATUS_ACTIVE, User
from ..utils.errors import (ACCOUNT_LOCKED, LOGIN_FAILED, MUST_CHANGE_PASSWORD,
                            VALIDATION_ERROR)
from ..utils.response import error, ok
from ..utils.validators import validate_password_strength, validate_username

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not validate_username(username) or not password:
        return error(VALIDATION_ERROR, "请输入正确的用户名和密码")

    user = User.query.filter_by(username=username).first()
    if user is None:
        return error(LOGIN_FAILED, "用户名或密码错误")

    # 锁定检查
    if user.locked_until and datetime.utcnow() < user.locked_until:
        remain = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        return error(ACCOUNT_LOCKED, f"连续登录失败次数过多，账号已锁定，请 {remain} 分钟后再试")

    if user.status != STATUS_ACTIVE:
        return error(LOGIN_FAILED, "账号已被停用，请联系管理员")

    if not check_password_hash(user.password_hash, password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=30)
            user.failed_attempts = 0
            db.session.commit()
            return error(ACCOUNT_LOCKED, "连续登录失败次数过多，账号已锁定 30 分钟")
        db.session.commit()
        return error(LOGIN_FAILED, f"用户名或密码错误（还可尝试 {5 - user.failed_attempts} 次）")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    db.session.commit()

    token = create_token(user)
    return ok({
        "token": token,
        "user": user.to_dict(),
        "must_change_password": user.must_change_password,
    }, "登录成功")


@bp.post("/logout")
@token_required
def logout():
    """无状态 JWT：前端丢弃 token 即完成登出，此处仅返回成功。"""
    return ok(message="已退出登录")


@bp.post("/change-password")
@token_required
def change_password():
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""

    if not check_password_hash(g.current_user.password_hash, old_password):
        return error(VALIDATION_ERROR, "原密码不正确")
    if not validate_password_strength(new_password):
        return error(VALIDATION_ERROR, "新密码长度不少于 8 位，且需同时包含字母和数字")
    if new_password == old_password:
        return error(VALIDATION_ERROR, "新密码不能与原密码相同")

    g.current_user.password_hash = generate_password_hash(new_password)
    g.current_user.must_change_password = False
    db.session.commit()
    return ok(message="密码修改成功，请重新登录")


@bp.get("/me")
@token_required
def me():
    return ok(g.current_user.to_dict())
