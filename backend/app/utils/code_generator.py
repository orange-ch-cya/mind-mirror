"""邀请码生成（文档 6.2）。

- 使用 secrets（密码学安全随机数），禁用 random；
- 8 位字符，排除易混淆字符 0/O/1/I/L，可用字符集 31 个，
  组合数 31^8 ≈ 8.5×10^11，防碰撞与枚举；
- 统一转大写存储，大小写不敏感。
"""
import secrets

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去掉 0 O 1 I L


def generate_invite_code(length=8):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def normalize_code(code):
    """大小写不敏感：统一转大写。"""
    return (code or "").strip().upper()
