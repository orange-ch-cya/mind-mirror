"""数据校验工具（文档 13.3：所有用户输入在后端严格校验）。"""
import re

CODE_PATTERN = re.compile(r"^[A-Z0-9]{8}$")          # 邀请码：8位大写字母+数字
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{3,50}$")


def validate_invite_code(code):
    """邀请码格式校验：8 位，仅含排除易混淆字符后的字母数字（大写）。"""
    if not code:
        return False
    return bool(CODE_PATTERN.match(code.upper()))


def validate_username(username):
    return bool(username) and bool(USERNAME_PATTERN.match(username))


def validate_password_strength(password):
    """密码强度：长度 ≥ 8，且包含字母和数字（文档 13.3）。"""
    if not password or len(password) < 8:
        return False
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_letter and has_digit


def validate_answer_value(value, options):
    """作答值必须命中选项配置的某个 score。"""
    scores = {opt.get("score") for opt in options}
    return value in scores


def require_fields(payload, fields):
    """校验请求体必须包含的字段，返回缺失字段列表。"""
    if not isinstance(payload, dict):
        return list(fields)
    return [f for f in fields if f not in payload or payload[f] is None]
