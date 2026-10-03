"""为全新 D1 数据库生成管理员 INSERT；从环境读取 pepper，交互读取密码。"""
import getpass
import hashlib
import hmac
import os
import secrets


def main():
    pepper = os.environ.get("PASSWORD_PEPPER", "")
    if len(pepper) < 32:
        raise SystemExit("先将与 Worker 相同的 PASSWORD_PEPPER 设为环境变量")
    password = getpass.getpass("管理员初始密码（至少 8 位，含字母数字）: ")
    if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise SystemExit("密码强度不足")
    salt = secrets.token_bytes(16)
    prehash = hmac.new(pepper.encode(), password.encode(), hashlib.sha256).digest()
    derived = hashlib.pbkdf2_hmac("sha256", prehash, salt, 100_000)
    encoded = f"cf-pbkdf2-sha256:100000${salt.hex()}${derived.hex()}"
    print("INSERT INTO users (username,password_hash,display_name,role,status,"
          "must_change_password,failed_attempts,created_at,updated_at) VALUES "
          f"('admin','{encoded}','管理员','admin','active',1,0,datetime('now'),datetime('now'));")


if __name__ == "__main__":
    main()
