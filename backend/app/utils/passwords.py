"""密码哈希入口：普通 Python 保持原行为，Workers 使用 WebCrypto。"""
import secrets
import sys

from werkzeug.security import check_password_hash as _werkzeug_check
from werkzeug.security import generate_password_hash as _werkzeug_generate


_METHOD = "cf-pbkdf2-sha256:100000"


def _derive(password, salt):
    from js import TextEncoder, Uint8Array, crypto
    from pyodide.ffi import run_sync, to_js

    from ..cloudflare_runtime import current_env

    pepper = str(current_env().PASSWORD_PEPPER)
    if len(pepper) < 32:
        raise RuntimeError("PASSWORD_PEPPER is not configured")

    async def calculate():
        encoder = TextEncoder.new()
        hmac_key = await crypto.subtle.importKey(
            "raw", encoder.encode(pepper),
            to_js({"name": "HMAC", "hash": "SHA-256"}), False,
            to_js(["sign"]),
        )
        prehash = await crypto.subtle.sign("HMAC", hmac_key, encoder.encode(password))
        key = await crypto.subtle.importKey(
            "raw", prehash, "PBKDF2", False, to_js(["deriveBits"]),
        )
        raw_salt = Uint8Array.new(to_js(list(bytes.fromhex(salt))))
        bits = await crypto.subtle.deriveBits(
            to_js({"name": "PBKDF2", "salt": raw_salt,
                   "iterations": 100000, "hash": "SHA-256"}),
            key, 256,
        )
        return bytes(Uint8Array.new(bits).to_py())

    return run_sync(calculate())


def generate_password_hash(password):
    if sys.platform != "emscripten":
        return _werkzeug_generate(password)

    from js import Uint8Array, crypto

    random_bytes = Uint8Array.new(16)
    crypto.getRandomValues(random_bytes)
    salt = bytes(random_bytes.to_py()).hex()
    return f"{_METHOD}${salt}${_derive(password, salt).hex()}"


def check_password_hash(stored_hash, password):
    if sys.platform != "emscripten":
        return _werkzeug_check(stored_hash, password)
    try:
        method, salt, digest = stored_hash.split("$", 2)
        if method != _METHOD or len(salt) != 32 or len(digest) != 64:
            return False
        return secrets.compare_digest(_derive(password, salt).hex(), digest)
    except (AttributeError, TypeError, ValueError):
        return False
