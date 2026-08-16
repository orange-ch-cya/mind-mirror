"""邀请码生成测试（文档 6.2）。"""
import re

from app.utils.code_generator import generate_invite_code, normalize_code


def test_format():
    code = generate_invite_code()
    assert re.fullmatch(r"[A-Z0-9]{8}", code)


def test_excludes_confusing_chars():
    for _ in range(500):
        code = generate_invite_code()
        assert "0" not in code and "O" not in code
        assert "1" not in code and "I" not in code and "L" not in code


def test_uniqueness():
    codes = {generate_invite_code() for _ in range(2000)}
    assert len(codes) == 2000


def test_normalize():
    assert normalize_code("  ab3c7d9 ") == "AB3C7D9"
