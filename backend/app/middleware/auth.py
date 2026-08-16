"""JWT 认证中间件（文档 4.1 / 7.4 / 13.3）。

- JWT 载荷：user_id、role、exp（默认 24 小时）；
- 中间件注入 g.current_user；token 无效返回 401，账号停用/锁定拒绝访问；
- 首次登录强制改密：除改密与登出外，must_change_password 用户一律拦截。
"""
import functools
from datetime import datetime, timedelta

import jwt
from flask import current_app, g, request

from ..extensions import db
from ..models import STATUS_ACTIVE, User
from ..utils.errors import (ACCOUNT_DISABLED, MUST_CHANGE_PASSWORD,
                            TOKEN_EXPIRED, UNAUTHORIZED)
from ..utils.response import error

_PASSABLE_ENDPOINTS = {"auth.change_password", "auth.logout", "auth.me"}


def create_token(user):
    payload = {
        "user_id": user.id,
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(hours=current_app.config["JWT_EXPIRES_HOURS"]),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _extract_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, UNAUTHORIZED, "未提供有效的登录凭证"
    token = auth_header[7:].strip()
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"],
                             algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, TOKEN_EXPIRED, "登录已过期，请重新登录"
    except jwt.InvalidTokenError:
        return None, UNAUTHORIZED, "登录凭证无效，请重新登录"

    user = db.session.get(User, payload.get("user_id"))
    if user is None:
        return None, UNAUTHORIZED, "账号不存在"
    if user.status != STATUS_ACTIVE:
        return None, ACCOUNT_DISABLED, "账号已被停用，请联系管理员"
    return user, 0, ""


def token_required(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        user, code, message = _extract_user()
        if user is None:
            return error(code, message)
        # 强制改密拦截
        if user.must_change_password:
            ep = request.endpoint or ""
            if ep not in _PASSABLE_ENDPOINTS:
                return error(MUST_CHANGE_PASSWORD, "首次登录须先修改初始密码")
        g.current_user = user
        return func(*args, **kwargs)

    return wrapper


def professional_required(func):
    """医生/家长/管理员均可访问（平台专业读者）。"""

    @functools.wraps(func)
    @token_required
    def wrapper(*args, **kwargs):
        if not g.current_user.is_professional:
            return error(4030, "无权限访问该资源")
        return func(*args, **kwargs)

    return wrapper


def admin_required(func):
    @functools.wraps(func)
    @token_required
    def wrapper(*args, **kwargs):
        if not g.current_user.is_admin:
            return error(4031, "需要管理员权限")
        return func(*args, **kwargs)

    return wrapper
